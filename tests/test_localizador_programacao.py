import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

import localizador_programacao
import runtime_config
from localizador_programacao import (
    COLUNAS_PROGRAMACAO,
    _build_payload_programacao,
    _extrair_programacoes,
    _validar_consulta,
    localizar_programacao,
    salvar_programacoes_excel,
)


HEADERS = [
    "Observação Desligamento",
    "Estado",
    "Referência",
    "Empresa Realizadora",
    "Nível de Tensão",
    "Descrição do Serviço",
    "Município",
    "Clientes Afetados Prog.",
    "Fin.Previsto",
    "Agente de Desligamento",
    "Iní.Previsto",
]


def montar_html(linhas, headers=HEADERS):
    cabecalho = "".join(
        f'<td class="tabConsLabel1">{header}</td>' for header in headers
    )
    dados = "".join(
        f'<tr {atributo}="">'
        + "".join(f'<td class="tabConsDados1">{valor}</td>' for valor in valores)
        + "</tr>"
        for atributo, valores in linhas
    )
    return f"<html><table><tr>{cabecalho}</tr>{dados}</table></html>"


LINHA_EXEMPLO = [
    "SERVICO DE REDE - OT:10000001 - PROJETO EXEMPLO",
    "EJECUTADO",
    "20000001",
    "EMPRESA EXEMPLO",
    "MT",
    "SUBSTITUIÇÃO DE EQUIPAMENTO",
    "MUNICIPIO EXEMPLO",
    "182",
    "06/03/2026 13:00:00",
    "AGENTE TESTE",
    "06/03/2026 08:00:00",
]


class LocalizadorProgramacaoTests(unittest.TestCase):
    def setUp(self):
        department_maps = (
            (runtime_config.SCHEDULE_DEPARTMENTS,
             {"DEPARTMENT_A": "schedule-code-a"}),
            (localizador_programacao.DEPARTAMENTOS_PROGRAMACAO,
             {"DEPARTMENT_A": "schedule-code-a"}),
        )
        for mapping, values in department_maps:
            map_patch = patch.dict(mapping, values, clear=True)
            map_patch.start()
            self.addCleanup(map_patch.stop)

    def test_payload_usa_filtros_do_relatorio_detalhado(self):
        payload = _build_payload_programacao("schedule-code-a", "01/03/2026", "31/03/2026")

        self.assertEqual(payload["grupo"], "1")
        self.assertEqual(payload["chkDetalhado"], "1")
        self.assertEqual(payload["txtDepartamento"], "schedule-code-a")
        self.assertEqual(payload["txtDataInicial"], "01/03/2026")
        self.assertEqual(payload["txtDataFinal"], "31/03/2026")
        self.assertEqual(payload["txtRef"], "")

    def test_validacao_normaliza_prefixo_e_rejeita_periodo_invertido(self):
        departamento, identificador = _validar_consulta(
            "department_a", "01/03/2026", "31/03/2026", "OT: 10000001"
        )

        self.assertEqual(departamento, "DEPARTMENT_A")
        self.assertEqual(identificador, "10000001")
        with self.assertRaisesRegex(ValueError, "data inicial"):
            _validar_consulta("DEPARTMENT_A", "31/03/2026", "01/03/2026", "10000001")

    def test_extrai_campos_por_cabecalho_e_traduz_estado(self):
        html = montar_html([("tabelalinha1", LINHA_EXEMPLO)])

        resultados = _extrair_programacoes(html, "10000001")

        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]["Referência"], "20000001")
        self.assertEqual(resultados[0]["Estado"], "Executado")
        self.assertEqual(resultados[0]["Descrição do Serviço"], "SUBSTITUIÇÃO DE EQUIPAMENTO")
        self.assertEqual(resultados[0]["Agente de Desligamento"], "AGENTE TESTE")

    def test_aceita_linhas_alternadas_e_retorna_todas_as_correspondencias(self):
        segunda = LINHA_EXEMPLO.copy()
        segunda[0] = "ORDEM 10000001"
        segunda[2] = "20000002"
        html = montar_html([
            ("tabelalinha1", LINHA_EXEMPLO),
            ("tabelalinha2", segunda),
        ])

        resultados = _extrair_programacoes(html, "10000001")

        self.assertEqual([r["Referência"] for r in resultados], ["20000001", "20000002"])

    def test_nao_aceita_identificador_parcial(self):
        html = montar_html([("tabelalinha1", LINHA_EXEMPLO)])

        self.assertEqual(_extrair_programacoes(html, "000001"), [])
        self.assertEqual(_extrair_programacoes(html, "100000010"), [])

    def test_relatorio_sem_colunas_obrigatorias_retorna_erro_explicito(self):
        html = '<table><tr><td class="tabConsLabel1">Estado</td></tr></table>'

        with self.assertRaisesRegex(ValueError, "Colunas ausentes"):
            _extrair_programacoes(html, "10000001")

    def test_empresa_retorna_todas_as_linhas_e_filtra_somente_coluna_realizadora(self):
        primeira = LINHA_EXEMPLO.copy()
        primeira[3] = "Companhia Árvore LTDA"
        segunda = primeira.copy()
        segunda[0] = ""
        segunda[2] = "20000002"
        segunda[3] = "COMPANHIA  ARVORE SERVIÇOS"
        outra = LINHA_EXEMPLO.copy()
        outra[0] = "OT 10000001 - Árvore"
        outra[5] = "Serviço na Árvore"
        sem_empresa = primeira.copy()
        sem_empresa[3] = ""
        html = montar_html([
            ("tabelalinha1", primeira), ("tabelalinha2", segunda),
            ("tabelalinha1", outra), ("tabelalinha2", sem_empresa),
        ])

        resultados = _extrair_programacoes(html, empresa="  companhia árvore  ")

        self.assertEqual([r["Referência"] for r in resultados], ["20000001", "20000002"])
        self.assertEqual(resultados[0]["Empresa Realizadora"], "Companhia Árvore LTDA")
        self.assertEqual(resultados[0]["Estado"], "Executado")
        self.assertEqual(_extrair_programacoes(html, empresa="inexistente"), [])

    def test_empresa_e_identificador_exigem_correspondencia_dos_dois(self):
        outra_ot = LINHA_EXEMPLO.copy()
        outra_ot[0] = "OT: 10000002"
        outra_ot[2] = "2"
        outra_empresa = LINHA_EXEMPLO.copy()
        outra_empresa[3] = "OUTRA EMPRESA"
        outra_empresa[2] = "3"
        html = montar_html([
            ("tabelalinha1", LINHA_EXEMPLO), ("tabelalinha2", outra_ot),
            ("tabelalinha1", outra_empresa),
        ])
        resultados = _extrair_programacoes(html, "10000001", empresa="exemplo")
        self.assertEqual([r["Referência"] for r in resultados], ["20000001"])
        self.assertEqual(_extrair_programacoes(html, "000001", empresa="exemplo"), [])

    def test_empresa_sozinha_dispensa_coluna_observacao_mas_exige_realizadora(self):
        html = montar_html([("tabelalinha1", LINHA_EXEMPLO[1:])], headers=HEADERS[1:])
        self.assertEqual(len(_extrair_programacoes(html, empresa="exemplo")), 1)
        with self.assertRaisesRegex(ValueError, "Observação Desligamento"):
            _extrair_programacoes(html, "10000001", empresa="exemplo")
        html = html.replace("Empresa Realizadora", "Outra coluna")
        with self.assertRaisesRegex(ValueError, "Empresa Realizadora"):
            _extrair_programacoes(html, empresa="teste")

    def test_validacao_empresa_nao_permite_consulta_sem_filtro_ou_invalida(self):
        args = ("DEPARTMENT_A", "01/03/2026", "31/03/2026")
        self.assertEqual(_validar_consulta(*args, empresa=" exemplo "), ("DEPARTMENT_A", ""))
        for empresa in ("", "  ", "...", "exemplo\x01abc"):
            with self.subTest(empresa=empresa), self.assertRaises(ValueError):
                _validar_consulta(*args, empresa=empresa)
        # O Cython valida a anotacao str antes da validacao em Python.
        for empresa in (None, 123, []):
            with self.subTest(empresa=empresa), self.assertRaises((ValueError, TypeError)):
                _validar_consulta(*args, empresa=empresa)
        with self.assertRaisesRegex(ValueError, "OT ou ORDEM"):
            _validar_consulta(*args, "OT:", empresa="exemplo")
        with self.assertRaisesRegex(ValueError, "data inicial"):
            _validar_consulta("DEPARTMENT_A", "31/03/2026", "01/03/2026", empresa="exemplo")
        for empresa in ("", "...", "  "):
            with self.subTest(empresa=empresa), self.assertRaises(ValueError):
                _extrair_programacoes(montar_html([]), empresa=empresa)

    @patch("localizador_programacao.requests.Session")
    def test_consulta_empresa_sem_identificador_filtra_relatorio_baixado(self, session_cls):
        resposta = MagicMock()
        resposta.content = montar_html([("tabelalinha1", LINHA_EXEMPLO)]).encode("windows-1252")
        session = session_cls.return_value.__enter__.return_value
        session.post.return_value = resposta
        resultados = localizar_programacao(
            "DEPARTMENT_A", "01/03/2026", "31/03/2026", empresa="exemplo"
        )
        self.assertEqual([r["Referência"] for r in resultados], ["20000001"])
        payload = session.post.call_args.kwargs["data"]
        self.assertEqual(payload["txtDepartamento"], "schedule-code-a")
        self.assertEqual(payload["txtDataInicial"], "01/03/2026")
        self.assertEqual(payload["txtDataFinal"], "31/03/2026")

    @patch("localizador_programacao.requests.Session")
    def test_consulta_envia_codigo_do_departamento_e_processa_resposta(self, session_cls):
        html = montar_html([("tabelalinha1", LINHA_EXEMPLO)])
        resposta = MagicMock()
        resposta.content = html.encode("windows-1252")
        resposta.raise_for_status.return_value = None
        session = session_cls.return_value.__enter__.return_value
        session.post.return_value = resposta

        resultados = localizar_programacao(
            "DEPARTMENT_A", "01/03/2026", "31/03/2026", "ORDEM:10000001"
        )

        self.assertEqual(resultados[0]["Referência"], "20000001")
        payload = session.post.call_args.kwargs["data"]
        self.assertEqual(payload["txtDepartamento"], "schedule-code-a")

    def test_exporta_excel_na_ordem_definida(self):
        resultado = {coluna: f"valor {i}" for i, coluna in enumerate(COLUNAS_PROGRAMACAO)}
        with tempfile.TemporaryDirectory() as diretorio:
            caminho = Path(diretorio) / "programacao.xlsx"

            salvar_programacoes_excel([resultado], caminho)
            planilha = pd.read_excel(caminho, dtype=str)

        self.assertEqual(list(planilha.columns), COLUNAS_PROGRAMACAO)
        self.assertEqual(len(planilha), 1)


if __name__ == "__main__":
    unittest.main()
