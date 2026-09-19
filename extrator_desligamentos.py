"""Consulta e exporta o estado de desligamentos informados em CSV ou Excel."""

import argparse
import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import pandas as pd

from runtime_config import STATUS_URL

ENDPOINT = STATUS_URL
ENCODING = "windows-1252"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

def _build_payload(numero: str) -> dict:
    """Monta o payload POST replicando o comportamento do JavaScript enviardados()
    quando txtRef está preenchido (ignora os outros filtros e submete direto)."""
    return {
        "htxtRetorno": "",
        "htxtNombreFecha": "",
        "txtRef": numero,
        "grupo": "1",           # Departamento (radio button index 1)
        "chkDetalhado": "1",    # Detalhado marcado
        "txtGerencia": "",
        "txtDepartamento": "",
        "txtTramitacao": "",
        "txtEstado": "",
        "txtTipo": "",
        "txtDataInicial": "",
        "txtDataFinal": "",
    }


def _extrair_estado(html: str, numero: str, debug_dir: Path | None = None) -> str:
    """
    Faz parse do HTML de resposta e extrai o campo Estado.

    O índice da coluna "Estado" é determinado dinamicamente pelo cabeçalho.
    Retorna 'NAO_ENCONTRADO' se o número não constar na resposta.
    """
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"{numero}.html").write_text(html, encoding="utf-8", errors="replace")

    soup = BeautifulSoup(html, "html.parser")

    # A correspondência exata evita confundir Estado com Estado do Incremento.
    headers = soup.find_all("td", class_="tabConsLabel1")
    estado_idx = None
    for i, th in enumerate(headers):
        if th.get_text(strip=True).lower() == "estado":
            estado_idx = i
            break
    if estado_idx is None:
        for i, th in enumerate(headers):
            texto = th.get_text(strip=True).lower()
            if texto == "estado" or (texto.startswith("estado") and "increment" not in texto):
                estado_idx = i
                break

    if estado_idx is None:
        return "NAO_ENCONTRADO"

    estados = []
    for tr in soup.find_all("tr", attrs={"tabelalinha1": True}):
        celulas = tr.find_all("td")
        if estado_idx < len(celulas):
            valor = celulas[estado_idx].get_text(strip=True)
            if valor and valor != "\xa0":
                estados.append(valor)

    if not estados:
        return "NAO_ENCONTRADO"

    return estados[0] if len(estados) == 1 else " | ".join(estados)


_TRADUCAO_STATUS = {
    "EJECUTADO":    "Executado",
    "DENEGADO":     "Negado",
    "APROBADO":     "Aprovado",
    "PENDIENTE":    "Pendente",
    "SUSPENDIDO":   "Suspenso",
    "RECHAZADO":    "Rejeitado",
    "CANCELADO":    "Cancelado",
    "PROGRAMADO":   "Programado",
    "SOLICITADO":   "Solicitado",
    "EN EJECUCIÓN": "Em execução",
    "EN ANÁLISIS":  "Em análise",
    "EN EJECUCION": "Em execução",
    "EN ANALISIS":  "Em análise",
    "ELIMINADO":    "Eliminado",
    "NO SOLICITADO": "Não Solicitado",
    "SIN CUMPLIMENTAR": "Sem Encerrar",
}


def _traduzir_status(estado: str) -> str:
    """Traduz status em espanhol para português (case-insensitive)."""
    return _TRADUCAO_STATUS.get(estado.upper().strip(), estado)


def consultar(numero: str, session: requests.Session, timeout: int,
              debug_dir: Path | None = None) -> str:
    """Faz o POST e retorna o estado do desligamento."""
    payload = _build_payload(str(numero).strip())
    resp = session.post(
        ENDPOINT,
        data=payload,
        timeout=timeout,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    html = resp.content.decode(ENCODING, errors="replace")
    return _extrair_estado(html, str(numero), debug_dir)


def _extrair_dados(html: str, numero: str, debug_dir: Path | None = None) -> dict:
    """
    Extrai estado, dept_solicitante e data_criacao do HTML de resposta.
    Retorna dict com chaves: 'estado', 'dept_solicitante', 'data_criacao'.
    """
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"{numero}.html").write_text(html, encoding="utf-8", errors="replace")

    soup = BeautifulSoup(html, "html.parser")

    headers = soup.find_all("td", class_="tabConsLabel1")
    nomes_headers = [th.get_text(strip=True) for th in headers]

    estado_idx = dept_idx = dept_exec_idx = data_idx = data_previsto_idx = None

    # A correspondência exata evita confundir Estado com Estado do Incremento.
    for i, texto in enumerate(nomes_headers):
        if texto.strip().lower() == "estado":
            estado_idx = i
            break

    for i, texto_orig in enumerate(nomes_headers):
        texto = texto_orig.strip().lower()
        if estado_idx is None and texto.startswith("estado") and "increment" not in texto:
            estado_idx = i
        elif dept_idx is None and "dept" in texto and "solicit" in texto:
            dept_idx = i
        elif dept_exec_idx is None and "dept" in texto and "execut" in texto:
            dept_exec_idx = i
        elif data_idx is None and "data" in texto and "cria" in texto and "incid" in texto:
            data_idx = i
        elif data_previsto_idx is None and "previsto" in texto and not texto.startswith("fin"):
            data_previsto_idx = i

    # Relatórios antigos usam nomes menos específicos para estas colunas.
    if dept_idx is None:
        for i, texto_orig in enumerate(nomes_headers):
            texto = texto_orig.strip().lower()
            if ("dept" in texto or "departament" in texto) and "execut" not in texto:
                dept_idx = i
                break

    if data_idx is None:
        for i, texto_orig in enumerate(nomes_headers):
            texto = texto_orig.strip().lower()
            if "data" in texto and "cria" in texto:
                data_idx = i
                break

    if dept_idx is None or data_idx is None:
        log.warning(
            "SGD %s — colunas não encontradas (dept_idx=%s, data_idx=%s). "
            "Headers disponíveis: %s",
            numero, dept_idx, data_idx,
            {i: n for i, n in enumerate(nomes_headers)},
        )
        diag_path = debug_dir / f"debug_sgd_{numero}.html" if debug_dir else None
        try:
            if diag_path:
                diag_path.write_text(html, encoding="utf-8", errors="replace")
                log.warning("HTML de diagnóstico salvo em: %s", diag_path)
        except Exception:
            pass

    resultado = {"estado": "NAO_ENCONTRADO", "dept_solicitante": "", "data_criacao": ""}

    if estado_idx is None:
        return resultado

    estados, depts, datas = [], [], []
    linhas_dados = soup.find_all("tr", attrs={"tabelalinha1": True})
    linhas_dados += soup.find_all("tr", attrs={"tabelalinha2": True})

    for tr in linhas_dados:
        celulas = tr.find_all("td")
        n = len(celulas)

        if estado_idx < n:
            valor = celulas[estado_idx].get_text(strip=True)
            if valor and valor != "\xa0":
                estados.append(valor)

        dept_val = ""
        if dept_idx is not None and dept_idx < n:
            dept_val = celulas[dept_idx].get_text(strip=True)
            if dept_val == "\xa0":
                dept_val = ""
        if not dept_val and dept_exec_idx is not None and dept_exec_idx < n:
            dept_val = celulas[dept_exec_idx].get_text(strip=True)
            if dept_val == "\xa0":
                dept_val = ""
        if dept_val:
            depts.append(dept_val)

        data_val = ""
        if data_idx is not None and data_idx < n:
            data_val = celulas[data_idx].get_text(strip=True)
            if data_val == "\xa0":
                data_val = ""
        if not data_val and data_previsto_idx is not None and data_previsto_idx < n:
            data_val = celulas[data_previsto_idx].get_text(strip=True)
            if data_val == "\xa0":
                data_val = ""
        if data_val:
            datas.append(data_val.split(" ")[0] if " " in data_val else data_val)

    if estados and (not depts or not datas):
        log.warning(
            "SGD %s — estado=%s mas dept=%s data=%s. "
            "Linhas de dados=%d, dept_idx=%s/%s, data_idx=%s/%s",
            numero, estados[0], depts, datas,
            len(linhas_dados),
            dept_idx, dept_exec_idx,
            data_idx, data_previsto_idx,
        )
        diag_path = debug_dir / f"debug_sgd_{numero}.html" if debug_dir else None
        try:
            if diag_path:
                diag_path.write_text(html, encoding="utf-8", errors="replace")
                log.warning("HTML de diagnóstico salvo em: %s", diag_path)
        except Exception:
            pass

    if estados:
        resultado["estado"] = estados[0] if len(estados) == 1 else " | ".join(estados)
    if depts:
        resultado["dept_solicitante"] = depts[0]
    if datas:
        resultado["data_criacao"] = datas[0]

    return resultado


def consultar_dados(numero: str, session: requests.Session, timeout: int,
                    debug_dir: Path | None = None) -> dict:
    """Faz o POST e retorna dict com estado, dept_solicitante e data_criacao."""
    payload = _build_payload(str(numero).strip())
    resp = session.post(
        ENDPOINT,
        data=payload,
        timeout=timeout,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    html = resp.content.decode(ENCODING, errors="replace")
    return _extrair_dados(html, str(numero), debug_dir)

def _ler_entrada(caminho: str) -> list[str]:
    """Lê a coluna 'numero_desligamento' do arquivo CSV ou XLSX."""
    p = Path(caminho)
    if not p.exists():
        log.error("Arquivo de entrada não encontrado: %s", caminho)
        sys.exit(1)

    if p.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(p, dtype=str)
    else:
        df = pd.read_csv(p, dtype=str)

    col = "numero_desligamento"
    if col not in df.columns:
        log.error("Coluna '%s' não encontrada em %s. Colunas disponíveis: %s",
                  col, caminho, list(df.columns))
        sys.exit(1)

    return df[col].dropna().str.strip().tolist()


def processar_lote(
    entrada: str,
    saida: str,
    delay: float,
    timeout: int,
    tentativas: int,
    debug: bool,
    on_progresso=None,
) -> None:
    """Processa todos os números do arquivo de entrada.

    on_progresso(i, total, numero, estado) é chamado após cada consulta.
    """
    numeros = _ler_entrada(entrada)

    log.info("Total a processar: %d", len(numeros))

    if not numeros:
        log.info("Nenhum número encontrado no arquivo de entrada.")
        return

    debug_dir = Path("debug") if debug else None
    session = requests.Session()
    linhas = []

    try:
        for i, numero in enumerate(numeros, start=1):
            log.info("[%d/%d] Consultando %s...", i, len(numeros), numero)
            estado = ""

            for tentativa in range(1, tentativas + 1):
                try:
                    estado = _traduzir_status(consultar(numero, session, timeout, debug_dir))
                    break
                except requests.exceptions.Timeout:
                    log.warning("  Tentativa %d/%d — timeout", tentativa, tentativas)
                    estado = "ERRO_TIMEOUT"
                except requests.exceptions.ConnectionError:
                    log.warning("  Tentativa %d/%d — erro de conexão", tentativa, tentativas)
                    estado = "ERRO_CONEXAO"
                except requests.exceptions.HTTPError as e:
                    log.warning("  Tentativa %d/%d — HTTP %s", tentativa, tentativas, e)
                    estado = f"ERRO_HTTP_{e.response.status_code}"
                    break
                except Exception as e:
                    log.warning("  Tentativa %d/%d — %s", tentativa, tentativas, e)
                    estado = "ERRO_DESCONHECIDO"

                if tentativa < tentativas:
                    time.sleep(2)

            timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            log.info("  → Status Atual: %s", estado or "-")
            linhas.append({
                "Numero SGD": numero,
                "Status Atual": estado,
                "Data/Horario da extração": timestamp,
            })

            if on_progresso:
                on_progresso(i, len(numeros), numero, estado)

            if i < len(numeros):
                time.sleep(delay)
    finally:
        df_saida = pd.DataFrame(linhas, columns=["Numero SGD", "Status Atual", "Data/Horario da extração"])
        df_saida.to_excel(saida, index=False)
        log.info("Resultado salvo em: %s", saida)

def processar_lote_completo(
    entrada: str,
    saida: str,
    delay: float,
    timeout: int,
    tentativas: int,
    debug: bool,
    on_progresso=None,
) -> list[dict]:
    """Processa todos os números retornando lista com todos os campos extraídos.

    Retorna lista de dicts com: Numero SGD, Status Atual, Data/Horario da extração,
    Dept Solicitante, Data Criação Incidencia.
    on_progresso(i, total, numero, estado) é chamado após cada consulta.
    """
    numeros = _ler_entrada(entrada)
    log.info("Total a processar: %d", len(numeros))

    if not numeros:
        log.info("Nenhum número encontrado no arquivo de entrada.")
        return []

    debug_dir = Path("debug") if debug else None
    session = requests.Session()
    linhas: list[dict] = []

    try:
        for i, numero in enumerate(numeros, start=1):
            log.info("[%d/%d] Consultando %s...", i, len(numeros), numero)
            dados: dict = {"estado": "", "dept_solicitante": "", "data_criacao": ""}

            for tentativa in range(1, tentativas + 1):
                try:
                    dados = consultar_dados(numero, session, timeout, debug_dir)
                    dados["estado"] = _traduzir_status(dados["estado"])
                    break
                except requests.exceptions.Timeout:
                    log.warning("  Tentativa %d/%d — timeout", tentativa, tentativas)
                    dados["estado"] = "ERRO_TIMEOUT"
                except requests.exceptions.ConnectionError:
                    log.warning("  Tentativa %d/%d — erro de conexão", tentativa, tentativas)
                    dados["estado"] = "ERRO_CONEXAO"
                except requests.exceptions.HTTPError as e:
                    log.warning("  Tentativa %d/%d — HTTP %s", tentativa, tentativas, e)
                    dados["estado"] = f"ERRO_HTTP_{e.response.status_code}"
                    break
                except Exception as e:
                    log.warning("  Tentativa %d/%d — %s", tentativa, tentativas, e)
                    dados["estado"] = "ERRO_DESCONHECIDO"

                if tentativa < tentativas:
                    time.sleep(2)

            timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            log.info("  → Status Atual: %s", dados["estado"] or "-")
            linhas.append({
                "Numero SGD": numero,
                "Status Atual": dados["estado"],
                "Data/Horario da extração": timestamp,
                "Dept Solicitante": dados["dept_solicitante"],
                "Data Criação Incidencia": dados["data_criacao"],
            })

            if on_progresso:
                on_progresso(i, len(numeros), numero, dados["estado"])

            if i < len(numeros):
                time.sleep(delay)
    finally:
        if linhas:
            df_saida = pd.DataFrame(linhas)
            df_saida.to_excel(saida, index=False)
            log.info("Resultado salvo em: %s", saida)

    return linhas


def main():
    parser = argparse.ArgumentParser(
        description="Extrai o Estado de Desligamentos do sistema SGD via POST."
    )
    parser.add_argument("--entrada",    default="entrada.csv",  help="Arquivo de entrada (CSV/XLSX)")
    parser.add_argument("--saida",      default="saida.xlsx",   help="Arquivo de saída (XLSX)")
    parser.add_argument("--delay",      type=float, default=1.0, help="Delay entre requisições (s)")
    parser.add_argument("--timeout",    type=int,   default=30,  help="Timeout HTTP (s)")
    parser.add_argument("--tentativas", type=int,   default=3,   help="Tentativas por número")
    parser.add_argument("--debug",      action="store_true",     help="Salvar HTML de resposta em debug/")
    args = parser.parse_args()

    processar_lote(
        entrada=args.entrada,
        saida=args.saida,
        delay=args.delay,
        timeout=args.timeout,
        tentativas=args.tentativas,
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
