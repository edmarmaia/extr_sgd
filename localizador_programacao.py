"""Localiza programacoes por OT/ORDEM e/ou empresa no relatorio detalhado do SGD."""

import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from extrator_desligamentos import ENCODING, ENDPOINT, _traduzir_status
from runtime_config import SCHEDULE_DEPARTMENTS


DEPARTAMENTOS_PROGRAMACAO = SCHEDULE_DEPARTMENTS

COLUNAS_PROGRAMACAO = [
    "Referência",
    "Nível de Tensão",
    "Estado",
    "Município",
    "Clientes Afetados Prog.",
    "Iní.Previsto",
    "Fin.Previsto",
    "Descrição do Serviço",
    "Empresa Realizadora",
    "Agente de Desligamento",
]

_CABECALHOS = {
    "Referência": ("referencia",),
    "Nível de Tensão": ("nivel de tensao",),
    "Estado": ("estado",),
    "Município": ("municipio",),
    "Clientes Afetados Prog.": ("clientes afetados prog",),
    "Iní.Previsto": ("ini previsto", "inicio previsto"),
    "Fin.Previsto": ("fin previsto", "fim previsto"),
    "Descrição do Serviço": ("descricao do servico", "descricao servico"),
    "Empresa Realizadora": ("empresa realizadora",),
    "Agente de Desligamento": ("agente de desligamento",),
    "Observação Desligamento": ("observacao desligamento",),
}


def _normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.replace("\xa0", " "))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", texto.lower()).strip()


def _build_payload_programacao(
    codigo_departamento: str,
    data_inicial: str,
    data_final: str,
) -> dict[str, str]:
    return {
        "htxtRetorno": "",
        "htxtNombreFecha": "",
        "txtRef": "",
        "grupo": "1",
        "chkDetalhado": "1",
        "txtGerencia": "",
        "txtDepartamento": codigo_departamento,
        "txtTramitacao": "",
        "txtEstado": "",
        "txtTipo": "",
        "txtDataInicial": data_inicial,
        "txtDataFinal": data_final,
    }


def _validar_consulta(
    departamento: str,
    data_inicial: str,
    data_final: str,
    ordem: str = "",
    empresa: str = "",
) -> tuple[str, str]:
    departamento = departamento.strip().upper()
    if departamento not in DEPARTAMENTOS_PROGRAMACAO:
        raise ValueError(f"Departamento invalido: {departamento}")

    try:
        inicio = datetime.strptime(data_inicial.strip(), "%d/%m/%Y")
        fim = datetime.strptime(data_final.strip(), "%d/%m/%Y")
    except ValueError as exc:
        raise ValueError("As datas devem estar no formato DD/MM/AAAA.") from exc

    if inicio > fim:
        raise ValueError("A data inicial nao pode ser posterior a data final.")

    if not isinstance(ordem, str):
        raise ValueError("A OT ou ORDEM deve ser um texto.")
    empresa_normalizada = _validar_empresa(empresa)
    if not ordem.strip() and not empresa_normalizada:
        raise ValueError("Informe uma OT/ORDEM ou uma empresa para localizar.")
    identificador = re.sub(
        r"^\s*(?:OT|ORDEM)\s*[:#-]?\s*",
        "",
        ordem,
        flags=re.IGNORECASE,
    ).strip()
    if ordem.strip() and not identificador:
        raise ValueError("Informe uma OT ou ORDEM para localizar.")
    if any(ord(c) < 32 for c in identificador):
        raise ValueError("A OT ou ORDEM contem caracteres invalidos.")

    return departamento, identificador


def _validar_empresa(empresa: str) -> str:
    if not isinstance(empresa, str):
        raise ValueError("A empresa deve ser um texto.")
    empresa = empresa.strip()
    normalizada = _normalizar_texto(empresa)
    if empresa and (not normalizada or any(ord(c) < 32 for c in empresa)):
        raise ValueError("A empresa contem caracteres invalidos. Informe parte do nome.")
    return normalizada


def _encontrar_indices(headers: list[str], exigir_observacao: bool = True) -> dict[str, int]:
    normalizados = [_normalizar_texto(header) for header in headers]
    indices: dict[str, int] = {}

    for campo, aliases in _CABECALHOS.items():
        if campo == "Observação Desligamento" and not exigir_observacao:
            continue
        for alias in aliases:
            if alias in normalizados:
                indices[campo] = normalizados.index(alias)
                break

    obrigatorios = list(COLUNAS_PROGRAMACAO)
    if exigir_observacao:
        obrigatorios.append("Observação Desligamento")
    ausentes = [campo for campo in obrigatorios if campo not in indices]
    if ausentes:
        raise ValueError(
            "Formato inesperado do relatorio. Colunas ausentes: "
            + ", ".join(ausentes)
        )
    return indices


def _identificador_na_observacao(observacao: str, identificador: str) -> bool:
    padrao = rf"(?<![A-Z0-9]){re.escape(identificador)}(?![A-Z0-9])"
    return re.search(padrao, observacao, flags=re.IGNORECASE) is not None


def _extrair_programacoes(
    html: str, identificador: str = "", empresa: str = ""
) -> list[dict[str, str]]:
    empresa_normalizada = _validar_empresa(empresa)
    if not identificador and not empresa_normalizada:
        raise ValueError("Informe uma OT/ORDEM ou uma empresa para localizar.")
    soup = BeautifulSoup(html, "html.parser")
    headers = [
        td.get_text(" ", strip=True)
        for td in soup.find_all("td", class_="tabConsLabel1")
    ]
    indices = _encontrar_indices(headers, exigir_observacao=bool(identificador))
    maior_indice = max(indices.values())
    resultados: list[dict[str, str]] = []

    for tr in soup.find_all("tr"):
        if not (tr.has_attr("tabelalinha1") or tr.has_attr("tabelalinha2")):
            continue

        celulas = tr.find_all("td", recursive=False)
        if len(celulas) <= maior_indice:
            continue

        valores = [
            celula.get_text("\n", strip=True).replace("\xa0", " ").strip()
            for celula in celulas
        ]
        if empresa_normalizada and empresa_normalizada not in _normalizar_texto(
            valores[indices["Empresa Realizadora"]]
        ):
            continue
        if identificador and not _identificador_na_observacao(
            valores[indices["Observação Desligamento"]], identificador
        ):
            continue

        resultado = {
            campo: valores[indices[campo]]
            for campo in COLUNAS_PROGRAMACAO
        }
        resultado["Estado"] = _traduzir_status(resultado["Estado"])
        resultados.append(resultado)

    return resultados


def localizar_programacao(
    departamento: str,
    data_inicial: str,
    data_final: str,
    ordem: str = "",
    timeout: int = 30,
    tentativas: int = 3,
    debug_dir: Path | None = None,
    empresa: str = "",
) -> list[dict[str, str]]:
    """Retorna todas as linhas dos filtros informados, no departamento e periodo.

    Empresa usa correspondencia parcial sem acentos/caixa. Quando ambos os
    filtros sao preenchidos, a linha deve corresponder a ambos.
    """
    departamento, identificador = _validar_consulta(
        departamento, data_inicial, data_final, ordem, empresa=empresa
    )
    if tentativas < 1:
        raise ValueError("O numero de tentativas deve ser maior que zero.")

    payload = _build_payload_programacao(
        DEPARTAMENTOS_PROGRAMACAO[departamento],
        data_inicial.strip(),
        data_final.strip(),
    )

    with requests.Session() as session:
        for tentativa in range(1, tentativas + 1):
            try:
                resposta = session.post(
                    ENDPOINT,
                    data=payload,
                    timeout=timeout,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resposta.raise_for_status()
                html = resposta.content.decode(ENCODING, errors="replace")
                if debug_dir is not None:
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    (debug_dir / "programacao.html").write_text(html, encoding="utf-8")
                return _extrair_programacoes(html, identificador, empresa=empresa)
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status < 500 or tentativa == tentativas:
                    raise
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if tentativa == tentativas:
                    raise

            time.sleep(2)

    return []


def salvar_programacoes_excel(
    resultados: list[dict[str, str]], caminho: str | Path
) -> None:
    pd.DataFrame(resultados, columns=COLUNAS_PROGRAMACAO).to_excel(
        caminho, index=False
    )
