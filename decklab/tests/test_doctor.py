"""Pure preflight reports and CLI over injected code providers; no configured-host probes."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

from decklab import doctor
from decklab.lib import preflight


READY = {"runtime": "runtime_ready", "config": "config_ready", "driver": "driver_ready",
         "database": "database_ready", "cards": "cards_ready", "java": "java_files_ready", "forge": "forge_files_ready"}
ORDER = ["runtime", "config", "driver", "database", "cards", "java", "forge"]
SECRET = "PRIVATE_VALUE user1@example.com C:/private/fixture password=fixture"


class Codes:
    def __init__(self, changes=None):
        self.values = {**READY, **(changes or {})}
        self.calls = []

    def __call__(self, ident):
        self.calls.append(ident)
        value = self.values[ident]
        if isinstance(value, BaseException):
            raise value
        return value


class PreflightReportTests(unittest.TestCase):
    def row(self, result, ident):
        return next(row for row in result["checks"] if row["id"] == ident)

    def test_ready_core_and_optional_files_are_ordered_without_execution_acceptance(self):
        codes = Codes()
        result = preflight.report(codes)
        self.assertEqual(codes.calls, ORDER)
        self.assertEqual([row["id"] for row in result["checks"]], ORDER)
        self.assertEqual(result["version"], 1)
        self.assertTrue(result["core_ready"])
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["optional_files_status"], "present")
        self.assertEqual(result["simulation_execution"], "not_performed")
        self.assertEqual([row["scope"] for row in result["checks"]], ["core"] * 5 + ["optional"] * 2)
        rendered = preflight.text(result)
        self.assertIn("Core preflight: ready.", rendered)
        self.assertIn("Simulation execution qualification: not performed.", rendered)
        self.assertIn("compiler tools were not qualified", rendered)
        self.assertIn("archive contents and games were not qualified", rendered)
        self.assertNotIn("simulations are ready", rendered.lower())

    def test_optional_setup_or_unverified_files_never_block_core(self):
        for java, forge, files in (("java_missing", "forge_missing", "incomplete"),
                                  ("java_unavailable", "forge_files_ready", "not_verified"),
                                  ("java_files_ready", "forge_invalid", "incomplete"),
                                  (RuntimeError(SECRET), "forge_files_ready", "not_verified")):
            with self.subTest(java=type(java).__name__, forge=forge):
                result = preflight.report(Codes({"java": java, "forge": forge}))
                self.assertTrue(result["core_ready"])
                self.assertEqual((result["exit_code"], result["optional_files_status"]), (0, files))
                self.assertEqual(result["simulation_execution"], "not_performed")
                self.assertNotIn(SECRET, json.dumps(result))

    def test_known_setup_failure_has_exit_one_and_skips_only_its_dependencies(self):
        codes = Codes({"runtime": "runtime_unsupported"})
        result = preflight.report(codes)
        self.assertEqual(result["exit_code"], 1)
        self.assertFalse(result["core_ready"])
        self.assertEqual(codes.calls, ["runtime", "config", "cards", "java", "forge"])
        self.assertEqual(self.row(result, "driver")["blocked_by"], ["runtime"])
        self.assertEqual(self.row(result, "database")["blocked_by"], ["driver"])
        self.assertEqual(self.row(result, "database")["code"], "dependency_blocked")
        self.assertEqual(self.row(result, "cards")["status"], "ready")
        self.assertIn("Python 3.14", self.row(result, "runtime")["next_step"])

    def test_bad_config_blocks_database_and_optional_settings_but_not_driver_or_cards(self):
        codes = Codes({"config": "config_missing"})
        result = preflight.report(codes)
        self.assertEqual(codes.calls, ["runtime", "config", "driver", "cards"])
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(self.row(result, "database")["blocked_by"], ["config"])
        self.assertEqual(self.row(result, "java")["blocked_by"], ["config"])
        self.assertEqual(self.row(result, "forge")["blocked_by"], ["config"])
        self.assertEqual(result["optional_files_status"], "not_verified")
        self.assertIn("config.example.json", self.row(result, "config")["next_step"])

    def test_database_unavailable_is_exit_two_with_independent_findings_and_no_server_down_claim(self):
        codes = Codes({"database": "database_unavailable", "cards": "cards_missing"})
        result = preflight.report(codes)
        self.assertEqual(codes.calls, ORDER)
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(self.row(result, "cards")["status"], "needs_setup")
        self.assertIn("cause is not classified as server downtime", self.row(result, "database")["message"])
        self.assertIn("python -m decklab.lib.cards update", self.row(result, "cards")["next_step"])

    def test_known_schema_setup_and_unverified_driver_have_distinct_exits(self):
        for changes, expected in (({"database": "database_migrations_pending"}, 1),
                                  ({"database": "database_migrations_mismatch"}, 1),
                                  ({"database": "database_uninitialized"}, 1),
                                  ({"database": "database_host_unsupported"}, 2),
                                  ({"driver": "driver_unusable"}, 2)):
            with self.subTest(changes=changes):
                result = preflight.report(Codes(changes))
                self.assertEqual(result["exit_code"], expected)
        result = preflight.report(Codes({"database": "database_ready"}))
        message = self.row(result, "database")["message"]
        self.assertIn("app-role connection", message)
        self.assertIn("migration ledger", message)
        self.assertNotIn("all data", message)
        self.assertNotIn("schema integrity", message)

    def test_unknown_objects_wrong_check_codes_and_exceptions_never_enter_public_output(self):
        class Opaque:
            def __str__(self):
                raise AssertionError("Do not stringify adapter values")

            __repr__ = __str__

        for value in (None, True, {"code": "cards_ready", "detail": SECRET}, [SECRET], SECRET,
                      "database_ready", Opaque(), RuntimeError(SECRET), ValueError(SECRET)):
            with self.subTest(kind=type(value).__name__):
                result = preflight.report(Codes({"cards": value}))
                self.assertEqual((result["exit_code"], self.row(result, "cards")["code"]), (2, "probe_unverified"))
                self.assertNotIn(SECRET, json.dumps(result, allow_nan=False))
                self.assertNotIn(SECRET, preflight.text(result))
        self.assertEqual(preflight.report(None)["exit_code"], 2)

    def test_reports_are_fresh_and_modifying_a_returned_result_cannot_change_the_catalog(self):
        codes = Codes()
        first = preflight.report(codes)
        first["checks"][0]["message"] = SECRET
        first["checks"][2]["blocked_by"].append(SECRET)
        codes.values["cards"] = "cards_missing"
        second = preflight.report(codes)
        self.assertEqual(codes.calls, ORDER * 2)
        self.assertNotIn(SECRET, json.dumps(second))
        self.assertEqual(second["exit_code"], 1)

    def test_cancellation_propagates_and_stops_later_checks(self):
        for interruption in (KeyboardInterrupt(), SystemExit(7)):
            codes = Codes({"driver": interruption})
            with self.subTest(kind=type(interruption).__name__), self.assertRaises(type(interruption)):
                preflight.report(codes)
            self.assertEqual(codes.calls, ["runtime", "config", "driver"])


class DoctorCliTests(unittest.TestCase):
    def invoke(self, args=(), factory=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = doctor.main(list(args), provider_factory=factory or (lambda: Codes()))
        return code, out.getvalue(), err.getvalue()

    def test_text_and_json_use_the_same_public_findings_and_exit(self):
        text_code, rendered, err = self.invoke()
        json_code, encoded, json_err = self.invoke(["--json"])
        result = json.loads(encoded)
        self.assertEqual((text_code, json_code, err, json_err), (0, 0, "", ""))
        self.assertEqual(rendered, preflight.text(result) + "\n")
        self.assertEqual(result["simulation_execution"], "not_performed")
        self.assertEqual(result["exit_code"], json_code)

    def test_help_creates_no_provider_and_performs_no_probes(self):
        with mock.patch.object(doctor, "_provider", side_effect=AssertionError("No adapters")) as factory, \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err, \
                self.assertRaises(SystemExit) as caught:
            doctor.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("--json", out.getvalue())
        self.assertEqual(err.getvalue(), "")
        factory.assert_not_called()

    def test_unknown_arguments_are_usage_two_without_echoing_submitted_values(self):
        with mock.patch.object(doctor, "_provider", side_effect=AssertionError("No adapters")) as factory, \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err, \
                self.assertRaises(SystemExit) as caught:
            doctor.main(["--password", SECRET])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("Invalid preflight arguments", err.getvalue())
        self.assertNotIn(SECRET, err.getvalue())
        factory.assert_not_called()

    def test_factory_failure_is_a_sanitized_json_report_instead_of_a_traceback(self):
        def failed():
            raise ImportError(SECRET)
        code, encoded, err = self.invoke(["--json"], failed)
        result = json.loads(encoded)
        self.assertEqual(code, 2)
        self.assertFalse(result["core_ready"])
        self.assertEqual(result["checks"][0]["code"], "probe_unverified")
        self.assertEqual(err, "")
        self.assertNotIn(SECRET, encoded)
        self.assertNotIn("Traceback", encoded)

    def test_default_factory_uses_fresh_inert_adapters_and_internal_settings_only(self):
        locals_created, optional_created = [], []
        local_module, forge_module = ModuleType("fake_local"), ModuleType("fake_optional")

        class Local:
            def __init__(self):
                self.settings = None
                self.calls = []
                locals_created.append(self)

            def probe(self, ident):
                self.calls.append(ident)
                if ident == "config":
                    self.settings = {"PRIVATE": SECRET}
                return READY[ident]

        class ForgeFiles:
            def __init__(self, *, settings):
                self.settings, self.seen = settings, []
                optional_created.append(self)

            def probe(self, ident):
                self.seen.append(self.settings())
                return READY[ident]

        local_module.Local, forge_module.ForgeFiles = Local, ForgeFiles
        with mock.patch.dict(sys.modules, {"decklab.lib.preflight_local": local_module, "decklab.lib.preflight_forge": forge_module}):
            for _ in range(2):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    self.assertEqual(doctor.main(["--json"]), 0)
                self.assertNotIn(SECRET, out.getvalue() + err.getvalue())
        self.assertEqual(len(locals_created), 2)
        self.assertEqual(len(optional_created), 2)
        self.assertIsNot(locals_created[0], locals_created[1])
        for local, optional in zip(locals_created, optional_created):
            self.assertEqual(local.calls, ORDER[:5])
            self.assertEqual(optional.seen, [local.settings, local.settings])

    def test_keyboard_interrupt_returns_cancellation_without_partial_json_or_later_checks(self):
        codes = Codes({"database": KeyboardInterrupt()})
        code, out, err = self.invoke(["--json"], lambda: codes)
        self.assertEqual((code, out, err), (130, "", "Preflight cancelled.\n"))
        self.assertEqual(codes.calls, ORDER[:4])

    def test_optional_factory_failure_keeps_core_ready_and_is_not_retried(self):
        local_module, forge_module = ModuleType("fake_local"), ModuleType("fake_optional")
        codes = Codes()
        local_module.Local = lambda: SimpleNamespace(settings={"PRIVATE": SECRET}, probe=codes)
        forge_module.ForgeFiles = mock.Mock(side_effect=ImportError(SECRET))
        with mock.patch.dict(sys.modules, {"decklab.lib.preflight_local": local_module, "decklab.lib.preflight_forge": forge_module}), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            self.assertEqual(doctor.main(["--json"]), 0)
        result = json.loads(out.getvalue())
        self.assertTrue(result["core_ready"])
        self.assertEqual(result["optional_files_status"], "not_verified")
        self.assertEqual(codes.calls, ORDER[:5])
        forge_module.ForgeFiles.assert_called_once()
        self.assertNotIn(SECRET, out.getvalue() + err.getvalue())

    def test_failed_configuration_never_creates_the_optional_adapter(self):
        local_module, forge_module = ModuleType("fake_local"), ModuleType("fake_optional")
        local_module.Local = lambda: SimpleNamespace(settings=None, probe=Codes({"config": "config_invalid"}))
        forge_module.ForgeFiles = mock.Mock(side_effect=AssertionError("Optional settings must stay untouched"))
        with mock.patch.dict(sys.modules, {"decklab.lib.preflight_local": local_module, "decklab.lib.preflight_forge": forge_module}), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            self.assertEqual(doctor.main(["--json"]), 1)
        self.assertFalse(json.loads(out.getvalue())["core_ready"])
        forge_module.ForgeFiles.assert_not_called()

    def test_malformed_optional_factory_result_is_fixed_unverified_and_not_retried(self):
        for value in (None, SimpleNamespace(probe=None), SimpleNamespace(probe=SECRET)):
            with self.subTest(kind=type(value).__name__):
                local_module, forge_module = ModuleType("fake_local"), ModuleType("fake_optional")
                codes = Codes()
                local_module.Local = lambda: SimpleNamespace(settings={}, probe=codes)
                forge_module.ForgeFiles = mock.Mock(return_value=value)
                with mock.patch.dict(sys.modules, {"decklab.lib.preflight_local": local_module,
                                                  "decklab.lib.preflight_forge": forge_module}), \
                        redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(doctor.main(["--json"]), 0)
                result = json.loads(out.getvalue())
                self.assertEqual(result["optional_files_status"], "not_verified")
                self.assertEqual([row["code"] for row in result["checks"][-2:]], ["probe_unverified"] * 2)
                self.assertEqual(codes.calls, ORDER[:5])
                forge_module.ForgeFiles.assert_called_once()
                self.assertNotIn(SECRET, out.getvalue() + err.getvalue())

    def test_factory_cancellation_is_respected_and_system_exit_is_not_relabelled(self):
        def cancel():
            raise KeyboardInterrupt
        self.assertEqual(self.invoke(["--json"], cancel), (130, "", "Preflight cancelled.\n"))
        with self.assertRaises(SystemExit) as caught:
            self.invoke(factory=lambda: Codes({"runtime": SystemExit(9)}))
        self.assertEqual(caught.exception.code, 9)

    def test_nonnumeric_system_exit_stops_without_echoing_its_private_payload(self):
        codes = Codes({"config": SystemExit(SECRET)})
        self.assertEqual(self.invoke(["--json"], lambda: codes), (2, "", "Preflight stopped before completing.\n"))
        self.assertEqual(codes.calls, ["runtime", "config"])
        def stopped_factory():
            raise SystemExit(SECRET)
        self.assertEqual(self.invoke(["--json"], stopped_factory), (2, "", "Preflight stopped before completing.\n"))

    def test_report_stream_failure_has_fixed_error_and_never_publishes_raw_io_details(self):
        stream = io.StringIO()
        with mock.patch.object(stream, "write", side_effect=ValueError(SECRET)), \
                redirect_stdout(stream), redirect_stderr(io.StringIO()) as err:
            self.assertEqual(doctor.main(["--json"], provider_factory=lambda: Codes()), 2)
        self.assertEqual(err.getvalue(), "The preflight report could not be written.\n")
        self.assertNotIn(SECRET, err.getvalue())

    def test_missing_error_stream_never_redirects_cancellation_into_report_output(self):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(None):
            self.assertEqual(doctor.main(["--json"], provider_factory=lambda: Codes({"runtime": KeyboardInterrupt()})), 130)
        self.assertEqual(out.getvalue(), "")
