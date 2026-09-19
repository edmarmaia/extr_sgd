"""Ponte pywebview segura para acesso concorrente."""

import copy
import io
import json
import math
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
import requests

import extrator_desligamentos as status_extractor
import extrator_negacao as reasons
import localizador_programacao as schedule


class _Cancelled(Exception):
    pass


class DesktopAPI:
    LOG_LIMIT = 300

    def __init__(self):
        self._lock = threading.RLock()
        self._dialog_lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread = None
        self._window = None
        self._numbers = []
        self._selecting = False
        self._state = dict(status="idle", operation=None, phase="idle", completed=0,
                           total=0, rows=[], logs=[], error=None, input=None,
                           next_run=None, cycle=0, autosave_path=None, results_updated_at=None)

    def set_window(self, window):
        with self._lock:
            self._window = window

    def get_state(self):
        with self._lock:
            return copy.deepcopy(self._state)

    def _log(self, message):
        with self._lock:
            self._state["logs"].append(dict(time=datetime.now(timezone.utc).isoformat(),
                                            message=str(message)))
            del self._state["logs"][:-self.LOG_LIMIT]

    def _update(self, **values):
        with self._lock:
            self._state.update(values)

    def _active(self):
        return self._thread is not None and self._thread.is_alive()

    def _dialog(self, method, *args, **kwargs):
        with self._dialog_lock:
            with self._lock:
                window = self._window
            if window is None:
                raise ValueError("Janela desktop indisponivel.")
            # O WinForms exige que dialogos sejam abertos na thread da interface.
            native = getattr(window, "native", None)
            if native is not None and getattr(native, "InvokeRequired", False):
                from System import Action
                result, errors = [], []

                def invoke():
                    try:
                        result.append(getattr(window, method)(*args, **kwargs))
                    except Exception as exc:
                        errors.append(exc)

                native.Invoke(Action(invoke))
                if errors:
                    raise errors[0]
                return result[0]
            return getattr(window, method)(*args, **kwargs)

    def select_input(self):
        with self._lock:
            if self._active() or self._selecting:
                return dict(ok=False, error="Uma operacao ja esta em andamento.")
            self._selecting = True
        try:
            import webview
            selected = self._dialog("create_file_dialog", webview.FileDialog.OPEN,
                                    allow_multiple=False,
                                    file_types=("Planilha e CSV (*.xlsx;*.xls;*.csv)",))
            if not selected:
                return dict(ok=False, error="Selecao cancelada.")
            path = Path(selected if isinstance(selected, str) else selected[0]).resolve()
            if not path.is_file() or path.suffix.lower() not in (".csv", ".xlsx", ".xls"):
                raise ValueError("Selecione um arquivo CSV, XLS ou XLSX existente.")
            reader = pd.read_csv if path.suffix.lower() == ".csv" else pd.read_excel
            frame = reader(path, dtype=str)
            if "numero_desligamento" not in frame:
                raise ValueError("Coluna obrigatoria: numero_desligamento.")
            numbers = frame["numero_desligamento"].dropna().str.strip().tolist()
            numbers = [n for n in numbers if n]
            if not numbers or any(not re.fullmatch(r"[0-9]+", n) for n in numbers):
                raise ValueError("A entrada deve conter numeros SGD validos (apenas digitos).")
            info = dict(path=str(path), name=path.name, count=len(numbers))
            with self._lock:
                self._numbers = numbers
                self._state["input"] = info
            return dict(ok=True, input=copy.deepcopy(info))
        except Exception as exc:
            return dict(ok=False, error=str(exc))
        finally:
            with self._lock:
                self._selecting = False

    def start_job(self, options):
        try:
            with self._lock:
                if self._active() or self._selecting:
                    raise ValueError("Uma operacao ja esta em andamento.")
                if not isinstance(options, dict):
                    raise ValueError("Opcoes invalidas.")
                opts = dict(operation="batch", include_reasons=False, number="",
                            department="", start_date="", end_date="", identifier="", company="",
                             interval_minutes=30, delay=1, timeout=30, reason_timeout=120,
                             attempts=3, debug=False)
                opts.update(options)
                operation = opts["operation"]
                if operation not in ("batch", "single", "schedule", "monitor"):
                    raise ValueError("Operacao invalida.")
                if "include_reasons" not in options:
                    opts["include_reasons"] = operation in ("single", "monitor")
                for key in ("include_reasons", "debug"):
                    if not isinstance(opts[key], bool):
                        raise ValueError(f"{key} deve ser booleano.")
                for key in ("delay", "timeout", "reason_timeout", "attempts", "interval_minutes"):
                    value = opts[key]
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        raise ValueError(f"{key} deve ser numerico.")
                    if not math.isfinite(value) or value < 0 or (key != "delay" and value == 0):
                        raise ValueError(f"{key} fora do intervalo valido.")
                if int(opts["attempts"]) != opts["attempts"]:
                    raise ValueError("attempts deve ser inteiro.")
                opts["attempts"] = int(opts["attempts"])
                if opts["interval_minutes"] * 60 > threading.TIMEOUT_MAX or opts["delay"] > threading.TIMEOUT_MAX:
                    raise ValueError("Intervalo muito grande.")
                numbers = list(self._numbers)
                if operation in ("batch", "monitor") and not numbers:
                    raise ValueError("Selecione o arquivo de entrada primeiro.")
                if operation == "single":
                    if not isinstance(opts["number"], str) or not re.fullmatch(r"[0-9]+", opts["number"].strip()):
                        raise ValueError("Informe um numero SGD com apenas digitos.")
                    numbers = [opts["number"].strip()]
                if operation == "schedule":
                    for key in ("start_date", "end_date"):
                        if not isinstance(opts[key], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", opts[key]):
                            raise ValueError("Informe datas no formato YYYY-MM-DD.")
                        opts[key] = datetime.strptime(opts[key], "%Y-%m-%d").strftime("%d/%m/%Y")
                    opts["department"], opts["identifier"] = schedule._validar_consulta(
                        opts["department"], opts["start_date"], opts["end_date"], opts["identifier"],
                        empresa=opts["company"])
                    opts["company"] = opts["company"].strip()
                self._cancel = threading.Event()
                self._state.update(status="running", operation=operation, phase="starting",
                                   completed=0, total=1 if operation == "schedule" else len(numbers),
                                   rows=[], logs=[], error=None, next_run=None, cycle=0,
                                   autosave_path=None, results_updated_at=None)
                self._thread = threading.Thread(target=self._run, args=(opts, numbers), daemon=True)
                try:
                    self._thread.start()
                except Exception as exc:
                    self._state.update(status="error", phase="error", error=str(exc))
                    raise
            return dict(ok=True)
        except Exception as exc:
            return dict(ok=False, error=str(exc))

    def cancel_job(self):
        with self._lock:
            if not self._active():
                return dict(ok=False, error="Nenhuma operacao em andamento.")
            self._cancel.set()
        self._log("Cancelamento solicitado; aguardando a consulta em andamento.")
        return dict(ok=True)

    def _check(self):
        if self._cancel.is_set():
            raise _Cancelled()

    @staticmethod
    def _friendly_error(exc):
        if isinstance(exc, requests.Timeout):
            return ("A consulta demorou mais que o esperado. Verifique a conexão VPN "
                    "e tente novamente.")
        if isinstance(exc, requests.ConnectionError):
            return ("Não foi possivel acessar os sistemas. Verifique se a VPN "
                    "está conectada e tente novamente.")
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            if exc.response.status_code in (401, 403):
                return ("O acesso ao sistema corporativo não foi autorizado. Verifique a VPN "
                        "e suas permissões de acesso.")
            if exc.response.status_code >= 500:
                return ("O sistema corporativo está indisponível no momento. "
                        "Tente novamente em alguns minutos.")
        if isinstance(exc, requests.RequestException):
            return ("Não foi possível concluir a comunicação com o sistema corporativo. "
                    "Verifique a VPN e tente novamente.")
        return str(exc)

    def _retry(self, call, opts):
        for attempt in range(opts["attempts"]):
            self._check()
            try:
                return call()
            except requests.RequestException as exc:
                self._log(f"Tentativa {attempt + 1}: {exc}")
                if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code < 500:
                    raise
                if attempt + 1 == opts["attempts"]:
                    raise
                if self._cancel.wait(2):
                    raise _Cancelled()

    def _publish(self, rows, **values):
        # A conversao pelo pandas elimina valores incompatíveis com JSON.
        clean = json.loads(pd.DataFrame(rows).to_json(orient="records", date_format="iso"))
        # O horario pertence ao snapshot, nao as leituras ou exportacoes posteriores.
        self._update(rows=clean, results_updated_at=datetime.now(timezone.utc).isoformat(), **values)

    def _excel_bytes(self, rows):
        frame = pd.DataFrame(rows)
        for column in frame:
            frame[column] = frame[column].map(
                lambda v: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v)
        buffer = io.BytesIO()
        frame.to_excel(buffer, index=False, engine="openpyxl")
        return buffer.getvalue()

    def _autosave(self, path, rows, update_path=True):
        if path is None or not rows:
            return
        temporary = None
        try:
            content = self._excel_bytes(rows)
            # A troca no mesmo diretorio preserva o snapshot anterior ate o novo estar pronto.
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            if update_path:
                self._update(autosave_path=str(path))
            self._log(f"Autosave salvo em: {path}")
        except Exception as exc:
            self._log(f"Aviso: falha no autosave em {path}: {exc}. Resultados mantidos em memoria.")
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as exc:
                    self._log(f"Aviso: nao foi possivel remover temporario {temporary}: {exc}")

    def _run(self, opts, numbers):
        debug_dir = None
        autosave_path = None
        rows = []
        has_complete_cycle = False
        cycle_in_progress = False
        try:
            self._check()
            self._log("Operacao iniciada.")
            local_data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
            job_id = uuid4().hex
            if opts["operation"] in ("batch", "monitor"):
                result_dir = local_data / "ExtratorSGD" / "results" / job_id
                try:
                    result_dir.mkdir(parents=True, exist_ok=False)
                    autosave_path = result_dir / "resultado.xlsx"
                except OSError as exc:
                    self._log(f"Aviso: autosave indisponivel em {result_dir}: {exc}. Resultados mantidos em memoria.")
            if opts["debug"]:
                debug_dir = local_data / "ExtratorSGD" / "diagnostics" / job_id
                debug_dir.mkdir(parents=True, exist_ok=False)
                self._log(f"Debug persistente: {debug_dir}")
            with tempfile.TemporaryDirectory(prefix="sgd-job-") as folder:
                directory = Path(folder)
                if opts["operation"] == "schedule":
                    self._check()
                    self._update(phase="schedule", cycle=1)
                    rows = self._retry(lambda: schedule.localizar_programacao(
                        opts["department"], opts["start_date"], opts["end_date"],
                        opts["identifier"], timeout=opts["timeout"], tentativas=1,
                        debug_dir=debug_dir, empresa=opts["company"]), opts)
                    self._publish(rows, completed=1)
                else:
                    cycle = 0
                    with requests.Session() as session:
                        while True:
                            self._check()
                            cycle += 1
                            self._update(status="running", phase="status", completed=0,
                                         total=len(numbers), cycle=cycle, next_run=None)
                            self._log(f"Ciclo {cycle}: consultando status.")
                            rows = []
                            cycle_in_progress = True
                            detailed = opts["include_reasons"] or opts["operation"] in ("single", "monitor")
                            for index, number in enumerate(numbers):
                                self._check()
                                row = dict(numero_desligamento=number)
                                try:
                                    if detailed:
                                        data = self._retry(lambda: status_extractor.consultar_dados(
                                            number, session, opts["timeout"], debug_dir), opts)
                                        row.update(status=status_extractor._traduzir_status(data["estado"]),
                                                   departamento=data.get("dept_solicitante", ""),
                                                   data=data.get("data_criacao", ""), motivo_negacao="")
                                    else:
                                        state = self._retry(lambda: status_extractor.consultar(
                                            number, session, opts["timeout"], debug_dir), opts)
                                        row["status"] = status_extractor._traduzir_status(state)
                                except requests.RequestException as exc:
                                    row.update(status="ERRO", erro=self._friendly_error(exc))
                                    self._log(f"SGD {number}: falha de rede: {exc}")
                                row["consultado_em"] = datetime.now(timezone.utc).isoformat()
                                rows.append(row)
                                if cycle == 1:
                                    self._publish(rows, completed=index + 1)
                                else:
                                    self._update(completed=index + 1)
                                self._log(f"SGD {number}: {row['status']}")
                                self._check()
                                if index + 1 < len(numbers) and self._cancel.wait(opts["delay"]):
                                    raise _Cancelled()
                            if opts["include_reasons"]:
                                self._update(phase="reasons")
                                cache = {}
                                for row in rows:
                                    self._check()
                                    if row["status"].lower() != "negado":
                                        continue
                                    try:
                                        dept = row.get("departamento", "")
                                        dept_value = reasons._mapear_dept(dept) if dept else None
                                        if not dept_value:
                                            raise ValueError("Departamento ausente ou nao mapeado para motivo.")
                                        if not row.get("data"):
                                            raise ValueError("Data ausente para motivo.")
                                        try:
                                            datetime.strptime(row["data"], "%d/%m/%Y")
                                        except ValueError as exc:
                                            raise ValueError(f"Data invalida para motivo: {row['data']}") from exc
                                        start, end = reasons._calc_margem_mes(row["data"])
                                        key = (dept_value, start)
                                        if key not in cache:
                                            self._log(f"Buscando motivos: {dept}, {start}.")
                                            cache[key] = reasons.baixar_xls_negacao(
                                                dept, dept_value, start, end, session, opts["reason_timeout"],
                                                directory, tentativas=opts["attempts"], cancel_event=self._cancel)
                                        self._check()
                                        if not cache[key]:
                                            raise ValueError("Relatorio de negacao indisponivel (falha no download).")
                                        row["motivo_negacao"] = reasons.extrair_motivo_negacao(
                                            cache[key], row["numero_desligamento"], strict=True)
                                    except _Cancelled:
                                        raise
                                    except Exception as exc:
                                        self._check()
                                        row["erro_motivo"] = self._friendly_error(exc)
                                        self._log(f"SGD {row['numero_desligamento']}: erro_motivo: {exc}")
                                    if cycle == 1:
                                        self._publish(rows)
                            self._publish(rows)
                            has_complete_cycle = True
                            cycle_in_progress = False
                            self._autosave(autosave_path, rows)
                            if opts["operation"] != "monitor":
                                break
                            interval = opts["interval_minutes"] * 60
                            next_run = datetime.now(timezone.utc) + timedelta(seconds=interval)
                            self._update(status="waiting", phase="waiting", next_run=next_run.isoformat())
                            self._log("Aguardando proximo ciclo.")
                            if self._cancel.wait(interval):
                                raise _Cancelled()
            with self._lock:
                self._check()
                self._state.update(status="completed", phase="completed", next_run=None)
            self._log("Operacao concluida.")
        except _Cancelled:
            self._update(status="cancelled", phase="cancelled", next_run=None)
            self._log("Operacao cancelada; resultados parciais preservados.")
        except Exception as exc:
            self._update(status="cancelled" if self._cancel.is_set() else "error",
                         phase="cancelled" if self._cancel.is_set() else "error",
                         error=None if self._cancel.is_set() else self._friendly_error(exc),
                         next_run=None)
            self._log(f"Detalhes técnicos: {exc}")
        finally:
            if cycle_in_progress and rows and opts["operation"] in ("batch", "monitor"):
                if has_complete_cycle:
                    # Um ciclo parcial posterior nao substitui o ultimo snapshot completo.
                    if autosave_path is not None:
                        self._autosave(autosave_path.with_name("resultado_parcial.xlsx"), rows,
                                       update_path=False)
                else:
                    self._publish(rows)
                    self._autosave(autosave_path, rows)
            if debug_dir is not None and debug_dir.is_dir():
                self._log(f"Debug preservado em: {debug_dir}")

    def export_results(self):
        try:
            rows = self.get_state()["rows"]
            if not rows:
                raise ValueError("Nao ha resultados para exportar.")
            import webview
            selected = self._dialog("create_file_dialog", webview.FileDialog.SAVE,
                                    save_filename=f"sgd_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
                                    file_types=("Planilha Excel (*.xlsx)",))
            if not selected:
                return dict(ok=False, error="Exportacao cancelada.")
            path = Path(selected if isinstance(selected, str) else selected[0]).resolve()
            if not path.suffix:
                path = path.with_suffix(".xlsx")
            if path.suffix.lower() != ".xlsx":
                raise ValueError("O destino deve ter extensao .xlsx.")
            exists = path.exists()
            if exists and not self._dialog("create_confirmation_dialog", "Substituir arquivo?", str(path)):
                return dict(ok=False, error="Exportacao cancelada.")
            # A criacao exclusiva evita substituir um arquivo criado durante o dialogo.
            content = self._excel_bytes(rows)
            with path.open("wb" if exists else "xb") as output:
                output.write(content)
            self._log(f"Resultados exportados: {path}")
            return dict(ok=True, path=str(path))
        except Exception as exc:
            return dict(ok=False, error=str(exc))
