import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests

import extrator_negacao
import localizador_programacao
import runtime_config
from desktop_api import DesktopAPI
from extrator_negacao import baixar_xls_negacao, extrair_motivo_negacao


class DesktopAPITests(unittest.TestCase):
    def setUp(self):
        department_maps = (
            (runtime_config.DENIAL_DEPARTMENTS, {"DEPARTMENT_A": "denial-code-a"}),
            (runtime_config.SCHEDULE_DEPARTMENTS, {"DEPARTMENT_A": "schedule-code-a"}),
            (extrator_negacao.DEPT_MAP, {"DEPARTMENT_A": "denial-code-a"}),
            (localizador_programacao.DEPARTAMENTOS_PROGRAMACAO,
             {"DEPARTMENT_A": "schedule-code-a"}),
        )
        for mapping, values in department_maps:
            map_patch = patch.dict(mapping, values, clear=True)
            map_patch.start()
            self.addCleanup(map_patch.stop)
        self.api = DesktopAPI()
        self.window = Mock(native=None)
        self.api.set_window(self.window)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        environment = patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.network = patch("requests.sessions.Session.request", side_effect=AssertionError("HTTP real proibido"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.stop_job)

    def stop_job(self):
        self.api._cancel.set()
        if self.api._thread:
            self.api._thread.join(3)

    def finish(self):
        self.api._thread.join(3)
        self.assertFalse(self.api._thread.is_alive())
        state = self.api.get_state()
        json.dumps(state, allow_nan=False)
        return state

    def load(self, numbers=("001", "2")):
        path = Path(self.temp.name) / "entrada.csv"
        pd.DataFrame({"numero_desligamento": numbers}).to_csv(path, index=False)
        self.window.create_file_dialog.return_value = (str(path),)
        result = self.api.select_input()
        self.assertTrue(result["ok"], result)
        return result

    def test_initial_snapshot_and_selection(self):
        self.assertEqual(self.api.get_state()["status"], "idle")
        result = self.load()
        self.assertEqual(result["input"]["count"], 2)
        self.assertEqual(
            self.window.create_file_dialog.call_args.kwargs["file_types"],
            ("Planilha e CSV (*.xlsx;*.xls;*.csv)",),
        )
        result["input"]["count"] = 9
        self.assertEqual(self.api.get_state()["input"]["count"], 2)

    def test_autosave_unique_jobs_preserve_input_and_include_failures(self):
        selected = self.load(("1", "2"))
        source = Path(selected["input"]["path"])
        original = source.read_bytes()
        paths = []
        for _ in range(2):
            with patch("desktop_api.status_extractor.consultar_dados", side_effect=[
                {"estado": "DENEGADO", "dept_solicitante": "", "data_criacao": ""},
                requests.Timeout("offline")
            ]):
                self.api.start_job(dict(operation="batch", include_reasons=True, attempts=1, delay=0))
                state = self.finish()
            self.assertEqual(state["status"], "completed")
            path = Path(state["autosave_path"])
            paths.append(path)
            self.assertEqual(path.name, "resultado.xlsx")
            self.assertEqual(path.parent.parent, Path(self.temp.name) / "ExtratorSGD" / "results")
            frame = pd.read_excel(path)
            self.assertIn("Departamento", frame.iloc[0]["erro_motivo"])
            self.assertEqual(
                frame.iloc[1]["erro"],
                "A consulta demorou mais que o esperado. Verifique a conexão VPN e tente novamente.",
            )
            self.assertTrue(any(str(path) in entry["message"] for entry in state["logs"]))
        self.assertNotEqual(*paths)
        self.assertTrue(all(path.is_file() for path in paths))
        self.assertEqual(source.read_bytes(), original)

    def test_result_timestamp_is_utc_and_polling_logs_exports_do_not_change_it(self):
        self.assertIsNone(self.api.get_state()["results_updated_at"])
        before = datetime.now(timezone.utc)
        with patch("desktop_api.schedule.localizar_programacao", return_value=[{"Estado": "Executado"}]):
            self.assertTrue(self.api.start_job(dict(
                operation="schedule", department="DEPARTMENT_A", company="Empresa Exemplo",
                start_date="2026-09-01", end_date="2026-09-30",
            ))["ok"])
            state = self.finish()
        timestamp = state["results_updated_at"]
        parsed = datetime.fromisoformat(timestamp)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)
        self.assertLessEqual(before, parsed)
        self.assertLessEqual(parsed, datetime.now(timezone.utc))
        self.assertEqual(state["status"], "completed")
        for _ in range(3):
            self.assertEqual(self.api.get_state()["results_updated_at"], timestamp)
        self.api._log("Mensagem sem nova consulta")
        self.window.create_file_dialog.return_value = (str(Path(self.temp.name) / "export.xlsx"),)
        self.assertTrue(self.api.export_results()["ok"])
        self.assertEqual(self.api.get_state()["results_updated_at"], timestamp)

    def test_result_timestamp_resets_on_start_and_records_empty_success_not_error(self):
        self.api._publish([{"Estado": "Executado"}])
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def query(*args, **kwargs):
            entered.set()
            release.wait(3)
            return []

        options = dict(operation="schedule", department="DEPARTMENT_A", company="Empresa Exemplo",
                       start_date="2026-09-01", end_date="2026-09-30")
        with patch("desktop_api.schedule.localizar_programacao", side_effect=query):
            self.assertTrue(self.api.start_job(options)["ok"])
            self.assertTrue(entered.wait(3))
            self.assertIsNone(self.api.get_state()["results_updated_at"])
            release.set()
            state = self.finish()
        self.assertEqual(state["rows"], [])
        self.assertEqual(state["status"], "completed")
        self.assertIsNotNone(state["results_updated_at"])
        with patch("desktop_api.schedule.localizar_programacao", side_effect=ValueError("parser")):
            self.assertTrue(self.api.start_job(options)["ok"])
            state = self.finish()
        self.assertEqual(state["status"], "error")
        self.assertIsNone(state["results_updated_at"])

    def test_autosave_partial_on_cancel_and_error(self):
        self.load()
        for outcome in ("cancelled", "error"):
            with self.subTest(outcome=outcome):
                def query(*args):
                    if outcome == "cancelled":
                        self.api.cancel_job()
                    return "APROBADO"

                effect = query if outcome == "cancelled" else ["APROBADO", ValueError("parser")]
                with patch("desktop_api.status_extractor.consultar", side_effect=effect):
                    self.api.start_job({"delay": 0})
                    state = self.finish()
                self.assertEqual(state["status"], outcome)
                self.assertEqual(len(pd.read_excel(state["autosave_path"])), 1)

    def test_autosave_failure_keeps_previous_file_and_rows(self):
        self.load(("1",))
        with patch("desktop_api.status_extractor.consultar", return_value="APROBADO"):
            self.api.start_job({})
            state = self.finish()
        path = Path(state["autosave_path"])
        original = path.read_bytes()
        self.api._publish([{"status": "Negado"}])
        with patch("desktop_api.os.replace", side_effect=PermissionError("locked")):
            self.api._autosave(path, self.api.get_state()["rows"])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(path.parent.iterdir()), [path])
        self.assertEqual(self.api.get_state()["rows"], [{"status": "Negado"}])
        self.assertIn("Aviso: falha no autosave", self.api.get_state()["logs"][-1]["message"])

    def test_autosave_workbook_failure_does_not_fail_job(self):
        self.load(("1",))
        with patch("desktop_api.status_extractor.consultar", return_value="APROBADO"), patch.object(
            self.api, "_excel_bytes", side_effect=PermissionError("denied")
        ):
            self.api.start_job({})
            state = self.finish()
        self.assertEqual(state["status"], "completed")
        self.assertEqual(len(state["rows"]), 1)
        self.assertIsNone(state["autosave_path"])
        self.assertTrue(any("falha no autosave" in entry["message"] for entry in state["logs"]))

    def test_monitor_keeps_previous_snapshot_until_complete(self):
        self.load(("1", "2"))
        second_cycle, release = threading.Event(), threading.Event()
        calls = 0

        def query(*args):
            nonlocal calls
            calls += 1
            if calls == 4:
                second_cycle.set()
                release.wait(3)
            return {"estado": "APROBADO" if calls <= 2 else "DENEGADO",
                    "dept_solicitante": "DEPARTMENT_A", "data_criacao": "01/04/2026"}

        self.addCleanup(release.set)
        with patch("desktop_api.status_extractor.consultar_dados", side_effect=query), patch(
            "desktop_api.reasons.baixar_xls_negacao", return_value=Path("mock.xls")
        ), patch("desktop_api.reasons.extrair_motivo_negacao", return_value="=motivo"):
            self.api.start_job(dict(operation="monitor", include_reasons=True, interval_minutes=0.001, delay=0))
            self.assertTrue(second_cycle.wait(3))
            state = self.api.get_state()
            path = Path(state["autosave_path"])
            original = path.read_bytes()
            self.assertEqual([row["status"] for row in state["rows"]], ["Aprovado"] * 2)
            first_timestamp = state["results_updated_at"]
            self.assertIsNotNone(first_timestamp)
            self.assertEqual(self.api.get_state()["results_updated_at"], first_timestamp)
            self.assertEqual(pd.read_excel(path)["status"].tolist(), ["Aprovado"] * 2)
            actual_replace = os.replace
            replaced = threading.Event()

            def replace(source, destination):
                self.assertEqual(Path(source).parent, path.parent)
                self.assertEqual(Path(destination), path)
                if not replaced.is_set():
                    self.assertEqual(path.read_bytes(), original)
                actual_replace(source, destination)
                replaced.set()

            with patch("desktop_api.os.replace", side_effect=replace):
                release.set()
                self.assertTrue(replaced.wait(3))
                self.api.cancel_job()
                state = self.finish()
            frame = pd.read_excel(path)
            self.assertEqual(frame["status"].tolist(), ["Negado"] * 2)
            self.assertEqual(frame["motivo_negacao"].tolist(), ["'=motivo"] * 2)
            self.assertNotEqual(state["results_updated_at"], first_timestamp)

    def test_schedule_cancelled_before_runner_does_not_query(self):
        actual_run = self.api._run

        def cancelled_run(opts, numbers):
            self.api._cancel.set()
            actual_run(opts, numbers)

        with patch.object(self.api, "_run", side_effect=cancelled_run), patch(
            "desktop_api.schedule.localizar_programacao"
        ) as query:
            self.api.start_job(dict(operation="schedule", department="DEPARTMENT_A", start_date="2026-04-01",
                                    end_date="2026-04-30", identifier="123"))
            state = self.finish()
        self.assertEqual(state["status"], "cancelled")
        self.assertIsNone(state["autosave_path"])
        query.assert_not_called()

    def test_second_monitor_cycle_partial_never_replaces_complete_snapshot(self):
        self.load(tuple(str(n) for n in range(100)))
        for outcome in ("cancelled", "error"):
            with self.subTest(outcome=outcome):
                calls = 0
                original = {}

                def query(*args):
                    nonlocal calls
                    calls += 1
                    if calls == 101:
                        state = self.api.get_state()
                        original["rows"] = state["rows"]
                        original["path"] = Path(state["autosave_path"])
                        original["bytes"] = original["path"].read_bytes()
                    if outcome == "cancelled" and calls == 103:
                        self.api.cancel_job()
                    if outcome == "error" and calls == 104:
                        raise ValueError("second cycle failed")
                    return {"estado": "APROBADO" if calls <= 100 else "DENEGADO",
                            "dept_solicitante": "DEPARTMENT_A", "data_criacao": "01/04/2026"}

                with patch("desktop_api.status_extractor.consultar_dados", side_effect=query):
                    self.assertTrue(self.api.start_job(dict(operation="monitor", include_reasons=False,
                                                            delay=0, interval_minutes=0.00001))["ok"])
                    state = self.finish()
                self.assertEqual(state["status"], outcome)
                self.assertEqual(state["cycle"], 2)
                self.assertEqual(state["rows"], original["rows"])
                self.assertEqual(len(state["rows"]), 100)
                path = original["path"]
                self.assertEqual(state["autosave_path"], str(path))
                self.assertEqual(path.read_bytes(), original["bytes"])
                partial = path.with_name("resultado_parcial.xlsx")
                frame = pd.read_excel(partial)
                self.assertEqual(len(frame), 3)
                self.assertEqual(frame["status"].tolist(), ["Negado"] * 3)
                self.assertTrue(any(str(partial) in entry["message"] for entry in state["logs"]))

    def test_first_monitor_cycle_partial_still_uses_main_snapshot(self):
        self.load(("1", "2"))

        def query(*args):
            self.api.cancel_job()
            return {"estado": "APROBADO"}

        with patch("desktop_api.status_extractor.consultar_dados", side_effect=query):
            self.api.start_job(dict(operation="monitor", delay=0))
            state = self.finish()
        self.assertEqual(state["status"], "cancelled")
        self.assertEqual(len(state["rows"]), 1)
        path = Path(state["autosave_path"])
        self.assertEqual(path.name, "resultado.xlsx")
        self.assertEqual(len(pd.read_excel(path)), 1)
        self.assertFalse(path.with_name("resultado_parcial.xlsx").exists())

    def test_default_reasons_and_independent_reason_timeout(self):
        self.load(("1",))
        for operation in ("single", "monitor"):
            for configured in (None, 45.5):
                with self.subTest(operation=operation, reason_timeout=configured), patch(
                    "desktop_api.status_extractor.consultar_dados", return_value={
                        "estado": "DENEGADO", "dept_solicitante": "DEPARTMENT_A", "data_criacao": "01/04/2026"
                    }
                ) as query, patch("desktop_api.reasons.baixar_xls_negacao", return_value=Path("mock.xls")) as download, patch(
                    "desktop_api.reasons.extrair_motivo_negacao", return_value="Motivo"
                ):
                    opts = dict(operation=operation, number="1")
                    if configured is not None:
                        opts["reason_timeout"] = configured
                    self.assertTrue(self.api.start_job(opts)["ok"])
                    if operation == "monitor":
                        deadline = time.monotonic() + 3
                        while self.api.get_state()["status"] != "waiting" and time.monotonic() < deadline:
                            time.sleep(0.005)
                        self.assertEqual(self.api.get_state()["status"], "waiting")
                        self.api.cancel_job()
                    state = self.finish()
                    self.assertEqual(state["rows"][0]["motivo_negacao"], "Motivo")
                    self.assertEqual(query.call_args.args[2], 30)
                    self.assertEqual(download.call_args.args[5], 120 if configured is None else configured)

    def test_reason_timeout_validation(self):
        for value in (0, -1, True, False, "120", None, float("nan"), float("inf")):
            with self.subTest(value=value):
                result = self.api.start_job(dict(operation="single", number="1", reason_timeout=value))
                self.assertFalse(result["ok"])
                self.assertIn("reason_timeout", result["error"])
                self.assertEqual(self.api.get_state()["status"], "idle")

    def test_invalid_input_preserves_selection(self):
        self.load()
        path = Path(self.temp.name) / "bad.csv"
        for frame in (pd.DataFrame({"wrong": [1]}),
                      pd.DataFrame({"numero_desligamento": ["../bad"]}),
                      pd.DataFrame({"numero_desligamento": []})):
            frame.to_csv(path, index=False)
            self.window.create_file_dialog.return_value = (str(path),)
            self.assertFalse(self.api.select_input()["ok"])
            self.assertEqual(self.api.get_state()["input"]["count"], 2)

    def test_dialog_cancel_and_failure(self):
        self.window.create_file_dialog.return_value = None
        self.assertFalse(self.api.select_input()["ok"])
        self.window.create_file_dialog.side_effect = RuntimeError("dialog")
        self.assertFalse(self.api.select_input()["ok"])
        self.assertFalse(self.api._selecting)

    def test_validation(self):
        cases = [None, {}, {"operation": "bad"}, {"operation": "single", "number": "../1"},
                 {"delay": -1}, {"timeout": 0}, {"attempts": 1.5}, {"debug": "false"},
                 {"interval_minutes": float("nan")}, {"delay": float("inf")},
                 {"timeout": True}, {"operation": "schedule", "start_date": "2026-02-30"}]
        for options in cases:
            with self.subTest(options=options):
                self.assertFalse(self.api.start_job(options)["ok"])
                self.assertEqual(self.api.get_state()["status"], "idle")

    @patch("desktop_api.status_extractor.consultar", return_value="APROBADO")
    def test_simple_batch(self, query):
        self.load()
        self.assertTrue(self.api.start_job({"operation": "batch", "delay": 0})["ok"])
        state = self.finish()
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["completed"], 2)
        self.assertEqual(state["rows"][0]["numero_desligamento"], "001")
        self.assertEqual(state["rows"][0]["status"], "Aprovado")
        self.assertNotIn("motivo_negacao", state["rows"][0])
        self.assertEqual(query.call_count, 2)
        state["rows"].clear()
        self.assertEqual(len(self.api.get_state()["rows"]), 2)

    def test_detailed_flows_and_monitor_export(self):
        for operation in ("batch", "single", "monitor"):
            with self.subTest(operation=operation):
                self.load()
                with patch("desktop_api.status_extractor.consultar_dados", return_value={
                    "estado": "DENEGADO", "dept_solicitante": "DEPARTMENT_A", "data_criacao": "01/04/2026"
                }), patch("desktop_api.reasons.baixar_xls_negacao", return_value=Path("mock.xls")) as download, patch(
                    "desktop_api.reasons.extrair_motivo_negacao", return_value="Motivo teste"
                ):
                    self.assertTrue(self.api.start_job(dict(operation=operation, number="123", delay=0,
                                                            include_reasons=True))["ok"])
                    if operation == "monitor":
                        deadline = time.monotonic() + 3
                        while self.api.get_state()["status"] != "waiting" and time.monotonic() < deadline:
                            time.sleep(0.005)
                        state = self.api.get_state()
                        self.assertEqual(state["status"], "waiting")
                        self.assertEqual(state["cycle"], 1)
                        self.assertIsNotNone(state["next_run"])
                        self.assertTrue(self.api.cancel_job()["ok"])
                    state = self.finish()
                    self.assertEqual(state["rows"][0]["motivo_negacao"], "Motivo teste")
                    self.assertEqual(download.call_count, 1)
                    directory = download.call_args.args[6]
                    self.assertIn("sgd-job-", directory.name)
                    self.assertFalse(directory.exists())
                    if operation == "monitor":
                        self.assertEqual(state["status"], "cancelled")
                        self.assertIsNone(state["next_run"])
                        path = Path(self.temp.name) / "monitor.xlsx"
                        self.window.create_file_dialog.return_value = str(path)
                        self.assertTrue(self.api.export_results()["ok"])
                        self.assertEqual(pd.read_excel(path).iloc[0]["motivo_negacao"], "Motivo teste")

    def test_cancel_in_flight_and_one_job(self):
        self.load()
        entered, release = threading.Event(), threading.Event()

        def query(*args):
            entered.set()
            release.wait(3)
            return "APROBADO"

        with patch("desktop_api.status_extractor.consultar", side_effect=query) as mock:
            self.api.start_job({"operation": "batch", "delay": 0})
            self.assertTrue(entered.wait(2))
            self.assertTrue(self.api._thread.daemon)
            self.assertFalse(self.api.start_job({"operation": "batch"})["ok"])
            self.assertFalse(self.api.select_input()["ok"])
            self.assertTrue(self.api.cancel_job()["ok"])
            release.set()
            state = self.finish()
            self.assertEqual(state["status"], "cancelled")
            self.assertEqual(len(state["rows"]), 1)
            self.assertEqual(mock.call_count, 1)

    def test_cancel_delay(self):
        self.load()
        with patch("desktop_api.status_extractor.consultar", return_value="APROBADO"):
            self.api.start_job({"operation": "batch", "delay": 1000})
            deadline = time.monotonic() + 2
            while not self.api.get_state()["rows"] and time.monotonic() < deadline:
                time.sleep(0.005)
            self.api.cancel_job()
            self.assertEqual(self.finish()["status"], "cancelled")

    def test_error_preserves_partial_results(self):
        self.load()
        with patch("desktop_api.status_extractor.consultar", side_effect=["APROBADO", ValueError("parser")]):
            self.api.start_job({"operation": "batch", "delay": 0})
            state = self.finish()
            self.assertEqual(state["status"], "error")
            self.assertEqual(state["error"], "parser")
            self.assertEqual(len(state["rows"]), 1)

    def test_network_errors_have_friendly_message_and_keep_technical_log(self):
        opts = dict(operation="schedule", department="DEPARTMENT_A", start_date="2026-04-01",
                    end_date="2026-04-30", identifier="OT:123", attempts=1)
        technical = "HTTPConnectionPool: Failed to resolve example host"
        with patch("desktop_api.schedule.localizar_programacao",
                   side_effect=requests.ConnectionError(technical)):
            self.assertTrue(self.api.start_job(opts)["ok"])
            state = self.finish()
        self.assertEqual(state["status"], "error")
        self.assertEqual(
            state["error"],
            "Não foi possivel acessar os sistemas. Verifique se a VPN está conectada e tente novamente.",
        )
        self.assertTrue(any(technical in entry["message"] for entry in state["logs"]))

    def test_network_error_messages_cover_common_failures(self):
        self.assertIn("demorou mais", self.api._friendly_error(requests.Timeout()))
        response = requests.Response()
        response.status_code = 403
        self.assertIn("não foi autorizado", self.api._friendly_error(requests.HTTPError(response=response)))
        response.status_code = 503
        self.assertIn("indisponível", self.api._friendly_error(requests.HTTPError(response=response)))
        self.assertIn("comunicação", self.api._friendly_error(requests.RequestException()))

    def test_schedule_and_validation(self):
        opts = dict(operation="schedule", department="DEPARTMENT_A", start_date="2026-04-01",
                    end_date="2026-04-30", identifier="OT:123")
        for changes in ({"department": "BAD"}, {"end_date": "2025-01-01"}, {"identifier": "OT:"}):
            self.assertFalse(self.api.start_job({**opts, **changes})["ok"])
        with patch("desktop_api.schedule.localizar_programacao", return_value=[{"Estado": "Executado"}]) as query:
            self.assertTrue(self.api.start_job(opts)["ok"])
            state = self.finish()
            self.assertEqual(state["rows"], [{"Estado": "Executado"}])
            self.assertEqual(query.call_args.args, ("DEPARTMENT_A", "01/04/2026", "30/04/2026", "123"))
            self.assertEqual(query.call_args.kwargs["empresa"], "")

    def test_schedule_company_optional_identifier_and_combined_filters(self):
        opts = dict(operation="schedule", department="DEPARTMENT_A", start_date="2026-04-01",
                    end_date="2026-04-30", company="  Empresa Exemplo  ")
        rows = [{"Referência": "1", "Empresa Realizadora": "Empresa Exemplo LTDA"},
                {"Referência": "2", "Empresa Realizadora": "Empresa Exemplo LTDA"}]
        for identifier, expected in (("", ""), ("OT:000123", "000123")):
            with self.subTest(identifier=identifier), patch(
                "desktop_api.schedule.localizar_programacao", return_value=rows
            ) as query:
                self.assertTrue(self.api.start_job({**opts, "identifier": identifier})["ok"])
                state = self.finish()
                self.assertEqual(state["status"], "completed")
                self.assertEqual(state["rows"], rows)
                self.assertEqual(query.call_args.args, ("DEPARTMENT_A", "01/04/2026", "30/04/2026", expected))
                self.assertEqual(query.call_args.kwargs["empresa"], "Empresa Exemplo")

    def test_schedule_rejects_missing_or_invalid_company_before_network(self):
        opts = dict(operation="schedule", department="DEPARTMENT_A", start_date="2026-04-01",
                    end_date="2026-04-30")
        with patch("desktop_api.schedule.localizar_programacao") as query:
            for company in ("", "  ", None, 123, [], "...", "abc\x01def"):
                with self.subTest(company=company):
                    self.assertFalse(self.api.start_job({**opts, "company": company})["ok"])
                    self.assertFalse(self.api._active())
            self.assertFalse(self.api.start_job({**opts, "company": "Teste", "identifier": "OT:"})["ok"])
            query.assert_not_called()

    def test_export_confirmation_and_formula_safety(self):
        self.assertFalse(self.api.export_results()["ok"])
        self.api._publish([{"status": "=1+1", "data": float("nan")}])
        path = Path(self.temp.name) / "export.xlsx"
        self.window.create_file_dialog.return_value = (str(path),)
        self.assertTrue(self.api.export_results()["ok"])
        original = path.read_bytes()
        self.window.create_confirmation_dialog.return_value = False
        self.assertFalse(self.api.export_results()["ok"])
        self.assertEqual(path.read_bytes(), original)
        self.window.create_confirmation_dialog.return_value = True
        self.assertTrue(self.api.export_results()["ok"])
        self.assertEqual(pd.read_excel(path).iloc[0]["status"], "'=1+1")
        self.window.create_file_dialog.return_value = None
        self.assertFalse(self.api.export_results()["ok"])

    def test_logs_bounded(self):
        for i in range(1000):
            self.api._log(i)
        state = self.api.get_state()
        self.assertEqual(len(state["logs"]), self.api.LOG_LIMIT)
        self.assertEqual(state["logs"][-1]["message"], "999")

    def test_winforms_dialog_dispatch(self):
        native = Mock(InvokeRequired=True)
        native.Invoke.side_effect = lambda callback: callback()
        self.window.native = native
        self.window.create_file_dialog.return_value = None
        with patch.dict("sys.modules", {"System": SimpleNamespace(Action=lambda callback: callback)}):
            self.assertFalse(self.api.select_input()["ok"])
            native.Invoke.assert_called_once()
            self.window.create_file_dialog.side_effect = ValueError("native failure")
            self.assertEqual(self.api.select_input()["error"], "native failure")

    def test_cancel_retry_wait(self):
        self.load()
        failed = threading.Event()
        original_log = self.api._log

        def log(message):
            original_log(message)
            if str(message).startswith("Tentativa"):
                failed.set()

        with patch.object(self.api, "_log", side_effect=log), patch(
            "desktop_api.status_extractor.consultar", side_effect=requests.Timeout("timeout")
        ) as query:
            self.api.start_job({"operation": "batch", "attempts": 3})
            self.assertTrue(failed.wait(2))
            self.api.cancel_job()
            self.assertEqual(self.finish()["status"], "cancelled")
            self.assertEqual(query.call_count, 1)

    def test_export_write_failure_preserves_existing_file(self):
        self.api._publish([{"status": "Aprovado"}])
        path = Path(self.temp.name) / "existing.xlsx"
        pd.DataFrame({"original": [1]}).to_excel(path, index=False)
        original = path.read_bytes()
        self.window.create_file_dialog.return_value = (str(path),)
        self.window.create_confirmation_dialog.return_value = True
        with patch("desktop_api.pd.DataFrame.to_excel", side_effect=PermissionError("denied")):
            self.assertFalse(self.api.export_results()["ok"])
        self.assertEqual(path.read_bytes(), original)

    def test_downloader_cancel_between_requests(self):
        event = threading.Event()
        session = Mock()

        def get(*args, **kwargs):
            self.assertEqual(kwargs["timeout"], 7)
            event.set()
            return Mock(content=b"<html></html>")

        session.get.side_effect = get
        self.assertIsNone(baixar_xls_negacao(
            "DEPARTMENT_A", "denial-code-a", "01/04/2026", "01/06/2026", session, 7,
            Path(self.temp.name), cancel_event=event))
        session.post.assert_not_called()

    def test_downloader_cancel_before_request(self):
        event = threading.Event()
        event.set()
        session = Mock()
        result = baixar_xls_negacao("DEPARTMENT_A", "denial-code-a", "01/04/2026", "01/06/2026",
                                    session, 10, Path(self.temp.name), cancel_event=event)
        self.assertIsNone(result)
        session.get.assert_not_called()
        session.post.assert_not_called()

    def test_debug_persists_on_success_error_and_cancel(self):
        self.load(("1",))
        folders = []
        for outcome in ("completed", "error", "cancelled"):
            with self.subTest(outcome=outcome):
                def query(number, session, timeout, debug_dir):
                    from extrator_desligamentos import _extrair_estado
                    folders.append(debug_dir)
                    _extrair_estado("<html>diagnostic</html>", number, debug_dir)
                    if outcome == "error":
                        raise ValueError("parse failure")
                    if outcome == "cancelled":
                        self.api.cancel_job()
                    return "APROBADO"

                with patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name}), patch(
                    "desktop_api.status_extractor.consultar", side_effect=query
                ):
                    self.assertTrue(self.api.start_job({"debug": True})["ok"])
                    state = self.finish()
                self.assertEqual(state["status"], outcome)
                directory = folders[-1]
                self.assertEqual(directory.parent, Path(self.temp.name) / "ExtratorSGD" / "diagnostics")
                self.assertEqual((directory / "1.html").read_text(), "<html>diagnostic</html>")
                self.assertIn(str(directory), state["logs"][-1]["message"])
        self.assertEqual(len(set(folders)), 3)

    def test_debug_is_opt_in(self):
        self.load(("1",))
        with patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name}), patch(
            "desktop_api.status_extractor.consultar", return_value="APROBADO"
        ) as query:
            self.api.start_job({"debug": False})
            self.finish()
        self.assertIsNone(query.call_args.args[3])
        self.assertFalse((Path(self.temp.name) / "ExtratorSGD" / "diagnostics").exists())

    def test_schedule_debug_persists_before_parser_failure(self):
        session = Mock()
        session.post.return_value = Mock(content=b"<html>unexpected report</html>")
        with patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name}), patch(
            "localizador_programacao.requests.Session"
        ) as factory:
            factory.return_value.__enter__.return_value = session
            self.api.start_job(dict(operation="schedule", department="DEPARTMENT_A",
                                    start_date="2026-04-01", end_date="2026-04-30",
                                    identifier="123", debug=True))
            state = self.finish()
        self.assertEqual(state["status"], "error")
        files = list((Path(self.temp.name) / "ExtratorSGD" / "diagnostics").glob("*/programacao.html"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_text(), "<html>unexpected report</html>")

    def test_single_and_monitor_without_reasons_keep_details(self):
        self.load(("1",))
        for operation in ("single", "monitor"):
            with self.subTest(operation=operation), patch(
                "desktop_api.status_extractor.consultar_dados", return_value={
                    "estado": "DENEGADO", "dept_solicitante": "DEPARTMENT_A", "data_criacao": "01/04/2026"
                }
            ) as query, patch("desktop_api.reasons.baixar_xls_negacao") as download:
                self.api.start_job(dict(operation=operation, number="1", include_reasons=False))
                if operation == "monitor":
                    deadline = time.monotonic() + 2
                    while self.api.get_state()["status"] != "waiting" and time.monotonic() < deadline:
                        time.sleep(0.005)
                    self.assertEqual(self.api.get_state()["status"], "waiting")
                    self.api.cancel_job()
                row = self.finish()["rows"][0]
                query.assert_called_once()
                download.assert_not_called()
                self.assertEqual(row["departamento"], "DEPARTMENT_A")
                self.assertEqual(row["data"], "01/04/2026")
                self.assertEqual(row["motivo_negacao"], "")
                self.assertNotIn("erro_motivo", row)

    def test_reason_errors_are_visible_and_exportable(self):
        cases = [({}, None, "Departamento"),
                 ({"dept_solicitante": "INVALID"}, None, "Departamento"),
                  ({"dept_solicitante": "DEPARTMENT_A"}, None, "Data ausente"),
                  ({"dept_solicitante": "DEPARTMENT_A", "data_criacao": "31/02/2026"}, None, "Data invalida"),
                  ({"dept_solicitante": "DEPARTMENT_A", "data_criacao": "01/04/2026"}, None, "download"),
                  ({"dept_solicitante": "DEPARTMENT_A", "data_criacao": "01/04/2026"}, Path("mock.xls"), "parser")]
        for data, report, error in cases:
            with self.subTest(error=error), patch(
                "desktop_api.status_extractor.consultar_dados", return_value={"estado": "DENEGADO", **data}
            ), patch("desktop_api.reasons.baixar_xls_negacao", return_value=report), patch(
                "desktop_api.reasons.extrair_motivo_negacao", side_effect=ValueError("parser")
            ):
                self.api.start_job(dict(operation="single", number="1", include_reasons=True))
                state = self.finish()
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["rows"][0]["status"], "Negado")
            self.assertIn(error, state["rows"][0]["erro_motivo"])
            self.assertTrue(any("erro_motivo" in entry["message"] for entry in state["logs"]))
        path = Path(self.temp.name) / "errors.xlsx"
        self.window.create_file_dialog.return_value = str(path)
        self.assertTrue(self.api.export_results()["ok"])
        self.assertEqual(pd.read_excel(path).iloc[0]["erro_motivo"], "parser")

    def test_empty_reason_is_not_a_download_error(self):
        with patch("desktop_api.status_extractor.consultar_dados", return_value={
            "estado": "DENEGADO", "dept_solicitante": "DEPARTMENT_A", "data_criacao": "01/04/2026"
        }), patch("desktop_api.reasons.baixar_xls_negacao", return_value=Path("mock.xls")), patch(
            "desktop_api.reasons.extrair_motivo_negacao", return_value=""
        ):
            self.api.start_job(dict(operation="single", number="1", include_reasons=True))
            row = self.finish()["rows"][0]
        self.assertEqual(row["motivo_negacao"], "")
        self.assertNotIn("erro_motivo", row)

    def test_reason_parser_strict_mode_preserves_cli(self):
        for frame in (pd.DataFrame([["1"]]), None):
            with self.subTest(frame=frame):
                with patch("extrator_negacao._ler_arquivo_negacao", return_value=frame,
                           side_effect=ValueError("unreadable") if frame is None else None):
                    self.assertEqual(extrair_motivo_negacao(Path("mock.xls"), "1"), "")
                    with self.assertRaises(ValueError):
                        extrair_motivo_negacao(Path("mock.xls"), "1", strict=True)

    def test_all_reason_requests_use_desktop_timeout_cli_keeps_default(self):
        for event, expected in ((threading.Event(), 7), (None, (15, 120))):
            with self.subTest(desktop=event is not None):
                session = Mock()
                response = Mock(content=b"<html></html>", headers={"Content-Type": "application/vnd.ms-excel"})
                session.get.return_value = response
                session.post.return_value = response
                path = baixar_xls_negacao("DEPARTMENT_A", "denial-code-a", "01/04/2026", "01/06/2026",
                                         session, 7, Path(self.temp.name), cancel_event=event)
                self.assertTrue(path.is_file())
                self.assertEqual(session.get.call_args.kwargs["timeout"], expected)
                self.assertEqual(session.post.call_count, 2)
                for call in session.post.call_args_list:
                    self.assertEqual(call.kwargs["timeout"], expected)


if __name__ == "__main__":
    unittest.main()
