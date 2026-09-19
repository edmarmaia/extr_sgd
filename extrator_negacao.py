"""Obtém motivos de negação e os associa aos desligamentos consultados."""

import logging
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import pandas as pd

from extrator_desligamentos import processar_lote_completo, consultar_dados, _traduzir_status
from runtime_config import DENIAL_DEPARTMENTS, DENIAL_REPORT_URL

log = logging.getLogger(__name__)

NEGACAO_URL = DENIAL_REPORT_URL

# O relatório de negações usa um timeout independente por ser mais lento.
_TIMEOUT_SITE2 = (15, 120)

DEPT_MAP = DENIAL_DEPARTMENTS

def _normalizar(texto: str) -> str:
    """Remove acentos e converte para maiúsculas para comparação."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).upper().strip()


def _mapear_dept(dept_sigla: str) -> str | None:
    """Retorna o valor da option correspondente ao departamento, ou None."""
    normalizado = _normalizar(dept_sigla)
    if normalizado in DEPT_MAP:
        return DEPT_MAP[normalizado]
    for key, value in DEPT_MAP.items():
        if normalizado in key or key in normalizado:
            return value
    return None


def _get_dir_base() -> Path:
    """Retorna a pasta onde o código ou .exe está localizado."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _calc_margem_mes(data_str: str) -> tuple[str, str]:
    """
    Calcula a margem de busca para uma data no formato DD/MM/AAAA.
    Início: dia 1 do mesmo mês.
    Fim:    dia 1 do mês + 2 (margem ampla para capturar negações tardias).
    Ex: '10/04/2026' → ('01/04/2026', '01/06/2026')
    """
    partes = data_str.strip().split("/")
    mes, ano = int(partes[1]), int(partes[2])
    mes_fim = mes + 2
    ano_fim = ano
    if mes_fim > 12:
        mes_fim -= 12
        ano_fim += 1
    return f"01/{mes:02d}/{ano}", f"01/{mes_fim:02d}/{ano_fim}"


_HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


def _obter_estado_formulario(session: requests.Session, url: str, timeout=_TIMEOUT_SITE2) -> dict:
    """
    Faz GET na página ASP.NET e extrai TODOS os campos hidden (incluindo
    ClientState do MaskedEditExtender e quaisquer outros campos ocultos).
    """
    resp = session.get(url, timeout=timeout, headers={**_HEADERS_BROWSER, "Referer": url})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")

    campos: dict[str, str] = {}
    for elem in soup.find_all("input", {"type": "hidden"}):
        name = elem.get("name") or elem.get("id", "").replace("_", "$")
        if name:
            campos[name] = elem.get("value", "")
    return campos


def baixar_xls_negacao(
    dept_sigla: str,
    dept_value: str,
    data_inicio: str,
    data_fim: str,
    session: requests.Session,
    timeout: int,  # Desktop (cancel_event) usa este valor; CLI preserva _TIMEOUT_SITE2.
    dest_dir: Path,
    tentativas: int = 3,
    cancel_event=None,
) -> Path | None:
    """
    Faz POST no site 2 com filtros de dept/estado/GD/data e baixa o .xls.
    Salva como negacao_{DEPT}_{AAAA-MM}.xls em dest_dir (sobrescreve).
    Retorna o Path do arquivo ou None em caso de falha.
    Tenta até `tentativas` vezes em caso de timeout ou erro transitório.
    """
    import time

    partes = data_inicio.split("/")
    ano_mes = f"{partes[2]}-{partes[1]}"
    dept_key = re.sub(r"[^A-Z0-9_-]", "_", _normalizar(dept_sigla))
    dest_path = dest_dir / f"negacao_{dept_key}_{ano_mes}.xls"
    request_timeout = timeout if cancel_event is not None else _TIMEOUT_SITE2

    for tentativa in range(1, tentativas + 1):
        if cancel_event is not None and cancel_event.is_set():
            return None
        try:
            campos_hidden = _obter_estado_formulario(session, NEGACAO_URL, request_timeout)
        except Exception as e:
            log.error("Erro ao obter estado do formulário (tentativa %d/%d): %s", tentativa, tentativas, e)
            if tentativa < tentativas:
                if cancel_event is not None:
                    cancel_event.wait(5)
                else:
                    time.sleep(5)
            continue

        payload_base = {
            **campos_hidden,
            "__EVENTARGUMENT": "",
            "ctl00$MainContent$ListBox_Departamento_Responsavel": dept_value,
            "ctl00$MainContent$ListBox_Estado": "DENEGADO",
            "ctl00$MainContent$rbGD": "T",
            "ctl00$MainContent$Control_Data_DataInicial$txtBoxData": data_inicio,
            "ctl00$MainContent$Control_Data_DataFinal$txtBoxData": data_fim,
        }

        headers_post = {
            **_HEADERS_BROWSER,
            "Referer": NEGACAO_URL,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": NEGACAO_URL.rsplit("/", 1)[0],
        }

        try:
            # A exportação depende do estado de formulário retornado pela pesquisa.
            if cancel_event is not None and cancel_event.is_set():
                return None
            payload_pesquisa = {
                **payload_base,
                "__EVENTTARGET": "ctl00$MainContent$ImageButton_Enviar",
            }
            resp_pesquisa = session.post(
                NEGACAO_URL, data=payload_pesquisa,
                timeout=request_timeout, headers=headers_post,
            )
            resp_pesquisa.raise_for_status()

            soup_pesquisa = BeautifulSoup(resp_pesquisa.content, "html.parser")
            campos_apos_pesquisa: dict[str, str] = {}
            for elem in soup_pesquisa.find_all("input", {"type": "hidden"}):
                name = elem.get("name") or elem.get("id", "").replace("_", "$")
                if name:
                    campos_apos_pesquisa[name] = elem.get("value", "")

            if cancel_event is not None and cancel_event.is_set():
                return None
            payload_export = {
                **campos_apos_pesquisa,
                "__EVENTTARGET": "ctl00$MainContent$ImageButton_Excel",
                "__EVENTARGUMENT": "",
                "ctl00$MainContent$ListBox_Departamento_Responsavel": dept_value,
                "ctl00$MainContent$ListBox_Estado": "DENEGADO",
                "ctl00$MainContent$rbGD": "T",
                "ctl00$MainContent$Control_Data_DataInicial$txtBoxData": data_inicio,
                "ctl00$MainContent$Control_Data_DataFinal$txtBoxData": data_fim,
            }
            resp = session.post(
                NEGACAO_URL, data=payload_export,
                timeout=request_timeout, headers=headers_post,
            )
            resp.raise_for_status()

            ct = resp.headers.get("Content-Type", "").lower()
            if not any(k in ct for k in ("excel", "spreadsheet", "octet-stream", "xls")):
                log.warning(
                    "Resposta inesperada do site 2 (Content-Type: %s) — arquivo não recebido (tentativa %d/%d)",
                    ct, tentativa, tentativas,
                )
                if log.isEnabledFor(logging.DEBUG):
                    snippet = resp.text[:2000].replace("\n", " ")
                    log.debug("Resposta HTML do site 2: %s", snippet)
                if tentativa < tentativas:
                    if cancel_event is not None:
                        cancel_event.wait(5)
                    else:
                        time.sleep(5)
                continue

            try:
                dest_path.write_bytes(resp.content)
            except PermissionError:
                # Arquivo provavelmente aberto no Excel — tenta reutilizar versão existente
                if dest_path.exists():
                    log.warning(
                        "Não foi possível sobrescrever %s (arquivo aberto?). "
                        "Usando versão existente em disco.", dest_path.name
                    )
                    return dest_path
                log.error(
                    "Permissão negada ao salvar %s e arquivo não existe. "
                    "Feche o arquivo no Excel e tente novamente.", dest_path.name
                )
                return None
            log.info("XLS de negação salvo em: %s", dest_path)
            return dest_path

        except Exception as e:
            log.error("Erro ao baixar XLS de negação (%s %s, tentativa %d/%d): %s",
                      dept_sigla, ano_mes, tentativa, tentativas, e)
            if tentativa < tentativas:
                if cancel_event is not None:
                    cancel_event.wait(5)
                else:
                    time.sleep(5)

    return None


def _normalizar_num(v: str) -> str:
    """Remove espacos e a parte decimal adicionada pelo Excel."""
    v = v.strip()
    try:
        return str(int(float(v)))
    except (ValueError, OverflowError):
        return v


def _ler_arquivo_negacao(xls_path: Path) -> pd.DataFrame:
    """
    Lê o arquivo de negação independente do formato.
    O servidor retorna HTML com Content-Type Excel ("pseudo-XLS").
    Tenta xlrd primeiro (XLS binário real); se falhar, usa read_html.
    """
    try:
        return pd.read_excel(xls_path, engine="xlrd", dtype=str, header=0)
    except Exception as e:
        log.debug("xlrd falhou em %s: %s — tentando read_html", xls_path.name, e)

    # Alguns relatorios usam HTML com extensao XLS.
    try:
        import io as _io
        raw = xls_path.read_bytes()
        try:
            conteudo = raw.decode("utf-8")
        except UnicodeDecodeError:
            conteudo = raw.decode("latin-1")
        tabelas = pd.read_html(_io.StringIO(conteudo), header=0)
        if tabelas:
            df = tabelas[0]
            return df.astype(str)
    except Exception as e:
        log.debug("read_html falhou em %s: %s", xls_path.name, e)

    raise ValueError(f"Não foi possível ler o arquivo: {xls_path}")


def extrair_motivo_negacao(xls_path: Path, numero_sgd: str, strict: bool = False) -> str:
    """
    Lê o .xls e retorna o motivo de negação do SGD informado.
    Coluna A (índice 0) = número do SGD
    Coluna V (índice 21) = motivo da negação
    """
    try:
        df = _ler_arquivo_negacao(xls_path)
        if df.shape[1] < 23:
            if strict:
                raise ValueError("Relatorio de negacao invalido: menos de 23 colunas.")
            log.warning("XLS tem menos de 23 colunas (%d) em %s", df.shape[1], xls_path)
            return ""

        col_sgd = df.iloc[:, 0].apply(_normalizar_num)
        alvo = _normalizar_num(str(numero_sgd))
        mask = col_sgd == alvo
        if not mask.any():
            log.debug("SGD %s não encontrado em %s (%d linhas)", alvo, xls_path.name, len(df))
            return ""

        motivo = df.iloc[mask.values.argmax(), 22]
        return str(motivo).strip() if pd.notna(motivo) else ""

    except Exception as e:
        log.error("Erro ao ler XLS para SGD %s em %s: %s", numero_sgd, xls_path, e)
        if strict:
            raise
        return ""


def processar_lote_com_negacao(
    entrada: str,
    saida: str,
    delay: float,
    timeout: int,
    tentativas: int,
    debug: bool,
    on_progresso=None,
    on_fase2=None,
) -> None:
    """
    Extrai status de todos os SGDs, busca motivo de negação para os negados
    e salva saida.xlsx com coluna extra 'Motivo Negação'.

    on_progresso(i, total, numero, estado) é chamado após cada consulta do site 1.
    on_fase2(i, total, dept_sigla, ano_mes) é chamado antes de cada download de XLS único.
    """
    linhas = processar_lote_completo(
        entrada=entrada,
        saida=saida,
        delay=delay,
        timeout=timeout,
        tentativas=tentativas,
        debug=debug,
        on_progresso=on_progresso,
    )

    if not linhas:
        return

    dir_base = _get_dir_base()
    session = requests.Session()
    # Cada relatorio de departamento e mes e baixado uma vez por execucao.
    cache_run: dict[tuple[str, str], Path | None] = {}

    combos_unicos: list[tuple[str, str, str, str, str]] = []  # (dept_value, ano_mes, dept_sigla, d_ini, d_fim)
    combos_vistos: set[tuple[str, str]] = set()
    for linha in linhas:
        if linha.get("Status Atual", "").lower() != "negado":
            continue
        dept_sigla = linha.get("Dept Solicitante", "").strip()
        data_criacao = linha.get("Data Criação Incidencia", "").strip()
        if not dept_sigla or not data_criacao:
            continue
        dept_value = _mapear_dept(dept_sigla)
        if not dept_value:
            continue
        try:
            data_inicio, data_fim = _calc_margem_mes(data_criacao)
        except Exception:
            continue
        partes = data_inicio.split("/")
        cache_key = (dept_value, f"{partes[2]}-{partes[1]}")
        if cache_key not in combos_vistos:
            combos_vistos.add(cache_key)
            combos_unicos.append((dept_value, cache_key[1], dept_sigla, data_inicio, data_fim))

    total_downloads = len(combos_unicos)
    download_idx = 0

    for linha in linhas:
        if linha.get("Status Atual", "").lower() != "negado":
            linha["Motivo Negação"] = ""
            continue

        dept_sigla = linha.get("Dept Solicitante", "").strip()
        data_criacao = linha.get("Data Criação Incidencia", "").strip()

        if not dept_sigla or not data_criacao:
            log.warning(
                "SGD %s negado mas sem dept/data — motivo não buscado", linha["Numero SGD"]
            )
            linha["Motivo Negação"] = ""
            continue

        dept_value = _mapear_dept(dept_sigla)
        if not dept_value:
            log.warning("Departamento não mapeado: '%s' (SGD %s)", dept_sigla, linha["Numero SGD"])
            linha["Motivo Negação"] = ""
            continue

        try:
            data_inicio, data_fim = _calc_margem_mes(data_criacao)
        except Exception:
            log.warning("Data inválida para SGD %s: '%s'", linha["Numero SGD"], data_criacao)
            linha["Motivo Negação"] = ""
            continue

        partes = data_inicio.split("/")
        ano_mes = f"{partes[2]}-{partes[1]}"
        cache_key = (dept_value, ano_mes)

        if cache_key not in cache_run:
            download_idx += 1
            if on_fase2:
                on_fase2(download_idx, total_downloads, dept_sigla, ano_mes)
            xls_path = baixar_xls_negacao(
                dept_sigla=dept_sigla,
                dept_value=dept_value,
                data_inicio=data_inicio,
                data_fim=data_fim,
                session=session,
                timeout=timeout,
                dest_dir=dir_base,
            )
            cache_run[cache_key] = xls_path
        else:
            xls_path = cache_run[cache_key]

        if xls_path and xls_path.exists():
            linha["Motivo Negação"] = extrair_motivo_negacao(xls_path, linha["Numero SGD"])
        else:
            linha["Motivo Negação"] = ""

    colunas = [
        "Numero SGD",
        "Status Atual",
        "Data/Horario da extração",
        "Dept Solicitante",
        "Data Criação Incidencia",
        "Motivo Negação",
    ]
    df_saida = pd.DataFrame(linhas, columns=colunas)
    df_saida.to_excel(saida, index=False)
    log.info("Resultado com motivo de negação salvo em: %s", saida)


def consultar_sgd_unico(
    numero: str,
    timeout: int = 30,
    tentativas: int = 3,
) -> dict:
    """
    Consulta status + motivo de negação de um único SGD.
    Retorna dict: numero, estado, dept, data_criacao, motivo_negacao, erro.
    """
    session = requests.Session()
    dados = {"estado": "NAO_ENCONTRADO", "dept_solicitante": "", "data_criacao": ""}
    erro = ""

    for tentativa in range(1, tentativas + 1):
        try:
            dados = consultar_dados(numero, session, timeout)
            dados["estado"] = _traduzir_status(dados["estado"])
            break
        except Exception as e:
            erro = str(e)
            if tentativa < tentativas:
                time.sleep(2)

    resultado = {
        "numero": numero,
        "estado": dados["estado"],
        "dept": dados["dept_solicitante"],
        "data_criacao": dados["data_criacao"],
        "motivo_negacao": "",
        "erro": erro,
    }

    if dados["estado"].lower() == "negado":
        dept_value = _mapear_dept(dados["dept_solicitante"])
        if dept_value and dados["data_criacao"]:
            try:
                data_inicio, data_fim = _calc_margem_mes(dados["data_criacao"])
                xls_path = baixar_xls_negacao(
                    dept_sigla=dados["dept_solicitante"],
                    dept_value=dept_value,
                    data_inicio=data_inicio,
                    data_fim=data_fim,
                    session=session,
                    timeout=timeout,
                    dest_dir=_get_dir_base(),
                )
                if xls_path and xls_path.exists():
                    resultado["motivo_negacao"] = extrair_motivo_negacao(xls_path, numero)
            except Exception as e:
                log.error("Erro ao buscar motivo para SGD %s: %s", numero, e)
                resultado["erro"] = str(e)

    return resultado


def buscar_motivos_negados(
    linhas: list[dict],
    timeout: int = 60,
    on_progresso=None,
) -> dict[str, str]:
    """
    Para SGDs negados em `linhas`, baixa o XLS e extrai o motivo de negação.
    linhas: dicts com Numero SGD, Status Atual, Dept Solicitante, Data Criação Incidencia.
    on_progresso(i, total_downloads, dept_sigla, ano_mes) chamado a cada download único.
    Retorna dict {numero_sgd: motivo}.
    """
    session = requests.Session()
    cache_run: dict[tuple[str, str], Path | None] = {}
    resultado: dict[str, str] = {}

    negados = [l for l in linhas if l.get("Status Atual", "").lower() == "negado"]
    if not negados:
        return resultado

    combos_vistos: set[tuple[str, str]] = set()
    for linha in negados:
        dept_sigla = linha.get("Dept Solicitante", "").strip()
        data_criacao = linha.get("Data Criação Incidencia", "").strip()
        if not dept_sigla or not data_criacao:
            continue
        dept_value = _mapear_dept(dept_sigla)
        if not dept_value:
            continue
        try:
            data_inicio, _ = _calc_margem_mes(data_criacao)
            partes = data_inicio.split("/")
            combos_vistos.add((dept_value, f"{partes[2]}-{partes[1]}"))
        except Exception:
            continue
    total_downloads = len(combos_vistos)

    download_idx = 0

    for linha in negados:
        numero = linha["Numero SGD"]
        dept_sigla = linha.get("Dept Solicitante", "").strip()
        data_criacao = linha.get("Data Criação Incidencia", "").strip()

        if not dept_sigla or not data_criacao:
            resultado[numero] = ""
            continue

        dept_value = _mapear_dept(dept_sigla)
        if not dept_value:
            resultado[numero] = ""
            continue

        try:
            data_inicio, data_fim = _calc_margem_mes(data_criacao)
        except Exception:
            resultado[numero] = ""
            continue

        partes = data_inicio.split("/")
        ano_mes = f"{partes[2]}-{partes[1]}"
        cache_key = (dept_value, ano_mes)

        if cache_key not in cache_run:
            download_idx += 1
            if on_progresso:
                on_progresso(download_idx, total_downloads, dept_sigla, ano_mes)
            xls_path = baixar_xls_negacao(
                dept_sigla=dept_sigla,
                dept_value=dept_value,
                data_inicio=data_inicio,
                data_fim=data_fim,
                session=session,
                timeout=timeout,
                dest_dir=_get_dir_base(),
            )
            cache_run[cache_key] = xls_path
        else:
            xls_path = cache_run[cache_key]

        if xls_path and xls_path.exists():
            resultado[numero] = extrair_motivo_negacao(xls_path, numero)
        else:
            resultado[numero] = ""

    return resultado
