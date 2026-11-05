"""Harness checks; these do not claim to run iOS Safari on Windows."""

import contextlib
import io
import json
import tempfile
import threading
import subprocess
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from decklab.safari import environment, runner
from decklab.safari.driver import Driver, DriverError


class MatrixTests(unittest.TestCase):
    def test_missing_devices_are_explicit_and_latest_available_runtime_wins(self):
        runtimes = [{"identifier": "ios25", "version": "25.0", "isAvailable": True},
                    {"identifier": "ios26", "version": "26.0", "isAvailable": True},
                    {"identifier": "ios27", "version": "27.0", "isAvailable": False}]
        devices = {version: [{"name": "iPhone 15 Pro", "udid": version, "isAvailable": True}]
                   for version in ("ios25", "ios26", "ios27")}
        rows = environment.matrix(devices, runtimes)
        self.assertEqual(len(rows), 6)
        self.assertEqual([r["runtime"] for r in rows[:2]], ["ios26", "ios26"])
        self.assertEqual([r["status"] for r in rows[2:]], ["unavailable"] * 4)
        self.assertEqual(rows[0]["orientation"], "PORTRAIT")
        self.assertEqual(rows[1]["orientation"], "LANDSCAPE")
        pinned = environment.matrix(devices, runtimes, runtime="25.0")
        self.assertEqual(pinned[0]["runtime"], "ios25")

    def test_unavailable_ipad_and_runtime_do_not_fall_back(self):
        runtime = [{"identifier": "ios26", "version": "26.0", "isAvailable": True}]
        devices = {"ios26": [{"name": "iPad Air 11-inch (M2)", "udid": "ipad", "isAvailable": True}]}
        self.assertEqual(environment.matrix(devices, runtime)[4]["model"], "iPad Air 11-inch (M2)")
        self.assertEqual(environment.matrix(devices, runtime, ipad_model="iPad Air 11-inch (M3)")[4]["status"],
                         "unavailable")
        self.assertTrue(all(r["status"] == "unavailable" for r in
                            environment.matrix(devices, runtime, runtime="18.0")))

    def test_non_mac_check_reports_all_six_without_attempting_any_commands(self):
        with mock.patch.object(environment.platform, "system", return_value="Windows"), \
                mock.patch.object(environment, "run", side_effect=AssertionError("must not execute")):
            found = environment.inspect()
        self.assertTrue(found["errors"])
        self.assertEqual(len(found["matrix"]), 6)
        self.assertTrue(all(row["status"] == "unavailable" for row in found["matrix"]))


class DriverTests(unittest.TestCase):
    def test_session_commands_and_w3c_errors(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append((self.path, payload))
                if self.path == "/session":
                    self.answer({"sessionId": "test", "capabilities": {"browserName": "Safari"}})
                elif self.path.endswith("/element"):
                    self.answer({"error": "no such element", "message": "missing Save"}, 404)
                else:
                    self.answer({"observed": True})

            def do_DELETE(self):
                seen.append((self.path, None))
                self.answer(None)

            def answer(self, value, code=200):
                body = json.dumps({"value": value}).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            log = io.StringIO()
            try:
                driver = Driver(f"http://127.0.0.1:{server.server_port}", {"browserName": "safari"}, log)
                self.assertEqual(driver.execute("return true"), {"observed": True})
                with self.assertRaisesRegex(DriverError, "missing Save"):
                    driver.find("css selector", "#save")
                driver.close()
            finally:
                server.shutdown()
                thread.join()
        self.assertEqual(seen[-1][0], "/session/test")
        self.assertEqual(seen[0][1]["capabilities"]["alwaysMatch"]["browserName"], "safari")
        self.assertEqual(len(log.getvalue().splitlines()), 4)

    def test_production_or_remote_appium_url_is_rejected(self):
        for url in ("https://decklab.example.com", "http://192.168.1.2:4723", "http://localhost:4723"):
            with self.assertRaises(ValueError):
                Driver(url, {}, io.StringIO())


class ReportTests(unittest.TestCase):
    def test_native_and_safari_viewport_must_both_match_requested_orientation(self):
        driver = mock.Mock()
        driver.command.return_value = "LANDSCAPE"
        driver.execute.return_value = {"width": 393, "height": 700}
        with mock.patch("decklab.safari.interaction.visit"):
            with self.assertRaisesRegex(AssertionError, "viewport does not match"):
                runner.verify_orientation(driver, mock.Mock(), "LANDSCAPE")
            driver.execute.return_value = {"width": 852, "height": 330}
            self.assertEqual(runner.verify_orientation(driver, mock.Mock(), "LANDSCAPE")["native_orientation"],
                             "LANDSCAPE")
            driver.command.return_value = "PORTRAIT"
            with self.assertRaisesRegex(AssertionError, "native orientation"):
                runner.verify_orientation(driver, mock.Mock(), "LANDSCAPE")

    def setUp(self):
        # These tests deliberately exercise failed/interrupted run reports.
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_interrupted_assertion_is_never_reported_as_passed(self):
        driver = mock.Mock()
        driver.screenshot.return_value = b"screenshot"
        driver.contexts.return_value = ["NATIVE_APP"]
        driver.command.return_value = "<native/>"
        driver.execute.return_value = {}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            row = {}
            record = runner.Recorder(driver, output, output, row)
            with self.assertRaises(KeyboardInterrupt):
                record("native Save", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
            result = row["assertions"][0]
            self.assertEqual(result["status"], "interrupted")
            self.assertNotIn("evidence", result)
            self.assertTrue(result["artifacts"])
            self.assertIn("seconds", result)

    def test_failure_keeps_evidence_and_next_assertion_still_runs(self):
        driver = mock.Mock()
        driver.screenshot.return_value = b"screenshot"
        driver.contexts.return_value = ["NATIVE_APP"]
        driver.command.return_value = "<native/>"
        driver.execute.side_effect = DriverError("native context")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            row = {}
            record = runner.Recorder(driver, output, output, row)
            self.assertFalse(record("Save reachable", lambda: (_ for _ in ()).throw(AssertionError("covered"))))
            self.assertTrue(record("Next check", lambda: {"width": 393}))
            failed = row["assertions"][0]
            self.assertEqual(len(failed["artifacts"]), 3)
            self.assertIn("browser.json", failed["diagnostic_errors"][0])
            self.assertEqual(row["assertions"][1]["evidence"], {"width": 393})
            self.assertEqual((output / failed["artifacts"][0]).read_bytes(), b"screenshot")
            driver.execute.assert_not_called()

    def test_failure_diagnostics_switch_detached_webview_to_native_before_capture(self):
        driver = mock.Mock()
        driver.current_context = "WEBVIEW_detached"

        def command(method, path):
            if path == "/context":
                return driver.current_context
            self.assertEqual((method, path), ("GET", "/source"))
            self.assertEqual(driver.current_context, "NATIVE_APP", "Web source would stall on the detached view")
            return "<AppiumAUT><XCUIElementTypeApplication/></AppiumAUT>"

        def switch(context):
            driver.current_context = context

        def screenshot():
            self.assertEqual(driver.current_context, "NATIVE_APP")
            return b"native screenshot"

        driver.command.side_effect = command
        driver.switch_context.side_effect = switch
        driver.screenshot.side_effect = screenshot
        driver.contexts.return_value = ["NATIVE_APP", "WEBVIEW_detached"]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            row = {}
            record = runner.Recorder(driver, output, output, row)
            self.assertFalse(record("failed webview", lambda: (_ for _ in ()).throw(DriverError("detached"))))
            failed = row["assertions"][0]
            self.assertEqual(failed["diagnostic_context"], {"original": "WEBVIEW_detached", "capture": "NATIVE_APP"})
            self.assertEqual(driver.current_context, "NATIVE_APP")
            source = next(path for path in failed["artifacts"] if path.endswith(".source.txt"))
            self.assertIn("XCUIElementTypeApplication", (output / source).read_text())
            self.assertTrue(any("browser.json: unavailable" in error for error in failed["diagnostic_errors"]))
            self.assertFalse(any(path.endswith(".browser.json") for path in failed["artifacts"]))
            driver.execute.assert_not_called()
            driver.switch_context.assert_called_once_with("NATIVE_APP")

    def test_failed_native_switch_skips_web_source_and_screenshot(self):
        driver = mock.Mock()
        driver.command.return_value = "WEBVIEW_detached"
        driver.switch_context.side_effect = DriverError("session disappeared")
        driver.contexts.return_value = ["NATIVE_APP"]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = {"artifacts": []}
            runner.Recorder(driver, output, output, {}).capture(result, "failed")
            self.assertEqual(result["diagnostic_context"], {"original": "WEBVIEW_detached", "capture": None})
            self.assertEqual(result["artifacts"], ["failed.contexts.json"])
            self.assertTrue(any("source.txt: unavailable" in error for error in result["diagnostic_errors"]))
            driver.command.assert_called_once_with("GET", "/context")
            driver.screenshot.assert_not_called()
            driver.execute.assert_not_called()

    def test_prerequisite_failure_writes_report_and_returns_two(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new-run"
            with mock.patch.object(environment, "source", return_value={"revision": "abc", "dirty": False}), \
                    mock.patch.object(environment, "inspect", return_value={
                        "errors": ["Xcode missing"], "matrix": environment.matrix({}, [])}), \
                    mock.patch.object(runner, "appium", side_effect=AssertionError("must not launch")):
                self.assertEqual(runner.main(["--check", "--output", str(output)]), 2)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["exit_code"], 2)
            self.assertEqual(len(report["matrix"]), 6)
            self.assertNotIn("passed", [row["status"] for row in report["matrix"]])
            self.assertIn("Physical-device acceptance is separate", (output / "report.md").read_text(encoding="utf-8"))

    def test_preflight_interruption_still_writes_six_rows_and_exit_130(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "interrupted"
            with mock.patch.object(environment, "source", return_value={"revision": "abc", "dirty": False}), \
                    mock.patch.object(environment, "inspect", side_effect=KeyboardInterrupt()):
                self.assertEqual(runner.main(["--check", "--output", str(output)]), 130)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["exit_code"], 130)
            self.assertEqual(len(report["matrix"]), 6)
            self.assertTrue(all(row["status"] == "not_run" for row in report["matrix"]))

    def test_configuration_interruption_marks_active_row_and_leaves_rest_not_run(self):
        rows = environment.matrix({}, [])
        for row in rows:
            row.update(status="pending", model="iPhone 15 Pro", os_version="26.0")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "interrupted"
            with mock.patch.object(environment, "source", return_value={"revision": "abc", "dirty": False}), \
                    mock.patch.object(environment, "inspect", return_value={"errors": [], "matrix": rows}), \
                    mock.patch.object(runner, "appium", return_value=contextlib.nullcontext("http://127.0.0.1:4723")), \
                    mock.patch.object(runner, "run_configuration", side_effect=KeyboardInterrupt()):
                self.assertEqual(runner.main(["--output", str(output)]), 130)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual([row["status"] for row in report["matrix"]], ["interrupted"] + ["not_run"] * 5)

    def test_configuration_interrupt_captures_before_driver_teardown_and_rethrows(self):
        fixture = SimpleNamespace(base_url="http://127.0.0.1:8629", logs=["fixture log"])
        driver = mock.Mock()
        driver.screenshot.return_value = b"failure screenshot"
        driver.contexts.return_value = ["NATIVE_APP"]
        driver.command.return_value = "native source"
        driver.execute.return_value = {}
        driver.capabilities = {"browserName": "safari"}
        row = {"model": "iPhone 15 Pro", "os_version": "26.0", "orientation": "PORTRAIT"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with mock.patch.object(runner, "simulator", return_value=contextlib.nullcontext("owned-test-uuid")), \
                    mock.patch("decklab.safari.fixture.FixtureServer", return_value=contextlib.nullcontext(fixture)), \
                    mock.patch.object(runner, "Driver", return_value=driver), \
                    mock.patch("decklab.safari.flows.run_flows", side_effect=KeyboardInterrupt()):
                with self.assertRaises(KeyboardInterrupt):
                    runner.run_configuration("http://127.0.0.1:4723", row, output)
            self.assertEqual(row["status"], "interrupted")
            screenshot = next(item for item in row["session_diagnostics"]["artifacts"] if item.endswith(".png"))
            self.assertEqual((output / screenshot).read_bytes(), b"failure screenshot")
            driver.close.assert_called_once()
            self.assertLess(driver.method_calls.index(mock.call.screenshot()), driver.method_calls.index(mock.call.close()))

    def test_session_screenshot_and_cleanup_failure_are_linked_in_markdown(self):
        row = {"requested_model": "iPhone 15 Pro", "orientation": "PORTRAIT", "status": "failed",
               "cleanup_notes": ["Simulator deletion timed out"],
               "session_diagnostics": {"artifacts": ["iphone/session-failure.png"]}}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            runner.write_reports(output, {"source": {"revision": "abc"}, "matrix": [row]})
            markdown = (output / "report.md").read_text(encoding="utf-8")
        self.assertIn("[iphone/session-failure.png](iphone/session-failure.png)", markdown)
        self.assertIn("Simulator deletion timed out", markdown)

    def test_simulator_cleanup_is_scoped_to_the_created_uuid(self):
        owned = "00000000-0000-0000-0000-000000000029"
        calls = []

        def command(*args, **kwargs):
            calls.append(args)
            if "devicetypes" in args:
                return json.dumps({"devicetypes": [{"name": "iPhone 15 Pro", "identifier": "type15"}]})
            if "create" in args:
                return owned
            return ""

        row = {"model": "iPhone 15 Pro", "runtime": "ios26"}
        with mock.patch.object(environment, "run", side_effect=command):
            with self.assertRaisesRegex(RuntimeError, "flow failed"):
                with runner.simulator(row) as actual:
                    self.assertEqual(actual, owned)
                    raise RuntimeError("flow failed")
        self.assertEqual(calls[-2:], [("xcrun", "simctl", "shutdown", owned),
                                     ("xcrun", "simctl", "delete", owned)])
        self.assertTrue(all("erase" not in call and "all" not in call for call in calls))

    def test_shutdown_timeout_or_oserror_still_deletes_only_owned_simulator(self):
        owned = "00000000-0000-0000-0000-000000000029"
        for failure in (subprocess.TimeoutExpired("shutdown", 30), OSError("shutdown unavailable")):
            calls = []

            def command(*args, **kwargs):
                calls.append(args)
                if "create" in args:
                    return owned
                if "shutdown" in args:
                    raise failure
                return ""

            row = {"model": "iPhone 15 Pro", "device_type": "type15", "runtime": "ios26", "status": "passed"}
            with self.subTest(failure=type(failure).__name__), mock.patch.object(environment, "run", side_effect=command):
                with runner.simulator(row):
                    pass
            self.assertEqual(calls[-1], ("xcrun", "simctl", "delete", owned))
            self.assertEqual(row["status"], "failed")
            self.assertTrue(row["cleanup_notes"])

    def test_already_shutdown_is_benign_only_for_verified_owned_uuid(self):
        owned = "00000000-0000-0000-0000-000000000029"
        shutdown_error = RuntimeError(
            "simctl shutdown: (domain=com.apple.CoreSimulator.SimError, code=405): "
            "Unable to shutdown device in current state: Shutdown")
        listings = (
            ({"udid": owned, "state": "Shutdown"}, "passed"),
            ({"udid": owned, "state": "Booted"}, "failed"),
            ({"udid": "another-device", "state": "Shutdown"}, "failed"),
        )
        for device, expected in listings:
            calls = []

            def command(*args, **kwargs):
                calls.append(args)
                if "create" in args:
                    return owned
                if "shutdown" in args:
                    raise shutdown_error
                if "list" in args:
                    return json.dumps({"devices": {"ios26": [device]}})
                return ""

            row = {"model": "iPhone 15 Pro", "device_type": "type15", "runtime": "ios26", "status": "passed"}
            with self.subTest(device=device), mock.patch.object(environment, "run", side_effect=command):
                with runner.simulator(row):
                    pass
            self.assertEqual(row["status"], expected)
            self.assertEqual(calls[-2:], [("xcrun", "simctl", "list", "devices", "--json"),
                                         ("xcrun", "simctl", "delete", owned)])
            self.assertEqual(bool(row.get("cleanup_notes")), expected == "failed")

    def test_other_shutdown_errors_and_failed_state_verification_remain_failures(self):
        owned = "00000000-0000-0000-0000-000000000029"
        errors = (
            RuntimeError("shutdown failed: unexpected failure"),
            RuntimeError("code=405: Unable to shutdown device in current state: Shutdown"),
        )
        for failure in errors:
            calls = []

            def command(*args, **kwargs):
                calls.append(args)
                if "create" in args:
                    return owned
                if "shutdown" in args:
                    raise failure
                if "list" in args:
                    raise RuntimeError("Cannot read device state")
                return ""

            row = {"model": "iPhone 15 Pro", "device_type": "type15", "runtime": "ios26", "status": "passed"}
            with self.subTest(failure=str(failure)), mock.patch.object(environment, "run", side_effect=command):
                with runner.simulator(row):
                    pass
            self.assertEqual(row["status"], "failed")
            self.assertIn(str(failure), row["cleanup_notes"][0])
            self.assertEqual(calls[-1], ("xcrun", "simctl", "delete", owned))
            self.assertEqual(any("list" in call for call in calls), "code=405" in str(failure))

    def test_shutdown_keyboard_interrupt_still_attempts_owned_deletion(self):
        owned = "00000000-0000-0000-0000-000000000029"
        calls = []

        def command(*args, **kwargs):
            calls.append(args)
            if "create" in args:
                return owned
            if "shutdown" in args:
                raise KeyboardInterrupt()
            return ""

        row = {"model": "iPhone 15 Pro", "device_type": "type15", "runtime": "ios26"}
        with mock.patch.object(environment, "run", side_effect=command), self.assertRaises(KeyboardInterrupt):
            with runner.simulator(row):
                pass
        self.assertEqual(calls[-1], ("xcrun", "simctl", "delete", owned))

    def lost_driver(self, alive):
        driver = mock.Mock()
        driver.screenshot.return_value = b"screenshot"
        driver.contexts.return_value = ["NATIVE_APP"]

        def command(method, path, body=None):
            if path == "/orientation" and not alive:
                raise DriverError("GET /orientation: connect ECONNREFUSED 127.0.0.1:8100")
            return "<native/>"

        driver.command.side_effect = command
        return driver

    def test_dead_session_text_and_failed_probe_raise_session_lost(self):
        driver = self.lost_driver(alive=False)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(runner.time, "sleep") as sleep:
            output = Path(directory)
            row = {}
            record = runner.Recorder(driver, output, output, row)
            with self.assertRaises(runner.SessionLost):
                record("receipt", lambda: (_ for _ in ()).throw(
                    DriverError("POST /execute/sync: Remote debugger is not connected")))
            result = row["assertions"][0]
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["session_lost"])
            self.assertTrue(result["artifacts"], "the dead device's screen is still captured")
        probes = [call for call in driver.command.call_args_list if call.args == ("GET", "/orientation")]
        self.assertEqual(len(probes), 2)
        sleep.assert_called_once()

    def test_dead_session_text_is_not_enough_while_the_probe_answers(self):
        driver = self.lost_driver(alive=True)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            row = {}
            record = runner.Recorder(driver, output, output, row)
            self.assertFalse(record("receipt", lambda: (_ for _ in ()).throw(
                DriverError("Remote debugger is not connected"))))
            self.assertTrue(record("next", lambda: {}))
            self.assertNotIn("session_lost", row["assertions"][0])

    def test_page_failure_never_probes_or_ends_the_session(self):
        driver = self.lost_driver(alive=False)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            row = {}
            record = runner.Recorder(driver, output, output, row)
            self.assertFalse(record("save", lambda: (_ for _ in ()).throw(AssertionError("Save covered"))))
        self.assertNotIn(mock.call("GET", "/orientation"), driver.command.call_args_list)

    def test_wrapped_wait_timeout_counts_as_session_text(self):
        try:
            try:
                raise DriverError("Could not proxy command. connect ECONNREFUSED 127.0.0.1:8100")
            except DriverError as inner:
                raise AssertionError("No inspectable Safari context") from inner
        except AssertionError as error:
            self.assertTrue(runner.suggests_lost_session(error))
        self.assertTrue(runner.suggests_lost_session(
            AssertionError("timed out: The device's display surface is not available yet")))
        self.assertFalse(runner.suggests_lost_session(AssertionError("Save covered")))
        self.assertFalse(runner.suggests_lost_session(ValueError("ECONNREFUSED 127.0.0.1:8100")))

    @contextlib.contextmanager
    def configuration(self, row, flows, drivers=None):
        """Run run_configuration with fakes; flows(record) plays the recorded checks."""
        fixture = SimpleNamespace(base_url="http://127.0.0.1:8629", logs=[])
        made = []

        def make_driver(*args):
            driver = self.lost_driver(alive=bool(drivers and drivers[len(made)]))
            driver.capabilities = {}
            made.append(driver)
            return driver

        def simulator(row):
            row["simulators"] = row.get("simulators", 0) + 1
            return contextlib.nullcontext(f"udid-{row['simulators']}")

        names = runner.all_check_names()  # before run_flows is faked below
        patches = (mock.patch.object(runner, "all_check_names", return_value=names),
                   mock.patch.object(runner, "simulator", side_effect=simulator),
                   mock.patch("decklab.safari.fixture.FixtureServer",
                              side_effect=lambda: contextlib.nullcontext(fixture)),
                   mock.patch.object(runner, "Driver", side_effect=make_driver),
                   mock.patch.object(runner, "verify_orientation", return_value={}),
                   mock.patch("decklab.safari.flows.run_flows",
                              side_effect=lambda driver, fixture, record: flows(record)),
                   mock.patch.object(runner.time, "sleep"))
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            yield made

    def test_lost_session_retries_once_in_new_folder_and_passes_visibly(self):
        attempts = []

        def flows(record):
            attempts.append(1)
            if len(attempts) == 1:
                record("receipt.initial_viewport", lambda: (_ for _ in ()).throw(
                    DriverError("Could not proxy command. connect ECONNREFUSED 127.0.0.1:8100")))
                record("never reached", lambda: self.fail("ran against a dead session"))
            else:
                record("receipt.initial_viewport", lambda: {})

        row = {"requested_model": "iPhone 15 Pro", "model": "iPhone 15 Pro", "os_version": "27.0",
               "orientation": "LANDSCAPE", "status": "running"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.configuration(row, flows, drivers=[False, True]) as made:
                runner.run_with_retry("http://127.0.0.1:4723", row, output)
            self.assertTrue((output / "iPhone-15-Pro-LANDSCAPE").is_dir())
            self.assertTrue((output / "iPhone-15-Pro-LANDSCAPE-retry1").is_dir())
            runner.write_reports(output, {"source": {"revision": "abc"}, "matrix": [row]})
            markdown = (output / "report.md").read_text(encoding="utf-8")
            saved = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(row["status"], "passed")
        self.assertEqual(row["simulators"], 2)
        self.assertEqual(len(made), 2)
        self.assertEqual([item["status"] for item in row["assertions"]], ["passed", "passed"])
        self.assertEqual(len(row["retries"]), 1)
        self.assertIn("ECONNREFUSED", row["retries"][0]["reason"])
        self.assertEqual([item["name"] for item in row["retries"][0]["assertions"]],
                         ["device.native_and_viewport_orientation", "receipt.initial_viewport"])
        self.assertIn("passed (retried once)", markdown)
        self.assertIn("Attempt 1 lost its Simulator session", markdown)
        self.assertIn("ECONNREFUSED", saved["matrix"][0]["retries"][0]["reason"])

    def test_session_lost_twice_fails_row_and_marks_rest_not_run(self):
        def flows(record):
            record("receipt.initial_viewport", lambda: (_ for _ in ()).throw(
                DriverError("Remote debugger is not connected")))

        row = {"requested_model": "iPhone 15 Pro", "model": "iPhone 15 Pro", "os_version": "27.0",
               "orientation": "LANDSCAPE", "status": "running"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.configuration(row, flows, drivers=[False, False, False]) as made:
                runner.run_with_retry("http://127.0.0.1:4723", row, output)
        self.assertEqual(len(made), 2, "at most one retry")
        self.assertEqual(row["status"], "failed")
        self.assertTrue(row["reason"].startswith("Simulator session lost (environment)"))
        statuses = {item["name"]: item["status"] for item in row["assertions"]}
        self.assertEqual(statuses["receipt.initial_viewport"], "failed")
        self.assertEqual(statuses["version.stale_detection_reload"], "not_run")
        self.assertEqual(list(statuses), runner.all_check_names())
        made[0].close.assert_called_once()
        made[1].close.assert_called_once()

    def test_page_failure_before_loss_is_not_hidden_by_a_passing_retry(self):
        attempts = []

        def flows(record):
            attempts.append(1)
            if len(attempts) == 1:
                record("receipt.initial_viewport", lambda: (_ for _ in ()).throw(AssertionError("hint covered")))
                record("receipt.image_swipe_exactly_one", lambda: (_ for _ in ()).throw(
                    DriverError("display surface is not available yet")))
            else:
                record("receipt.initial_viewport", lambda: {})

        row = {"requested_model": "iPhone 15 Pro", "model": "iPhone 15 Pro", "os_version": "27.0",
               "orientation": "PORTRAIT", "status": "running"}
        with tempfile.TemporaryDirectory() as directory:
            with self.configuration(row, flows, drivers=[False, True]):
                runner.run_with_retry("http://127.0.0.1:4723", row, Path(directory))
        self.assertEqual(row["status"], "failed")
        self.assertIn("receipt.initial_viewport", row["reason"])
        self.assertNotIn("receipt.image_swipe_exactly_one", row["reason"])

    def test_page_failures_without_a_lost_session_run_once(self):
        def flows(record):
            record("receipt.initial_viewport", lambda: (_ for _ in ()).throw(AssertionError("hint covered")))

        row = {"requested_model": "iPhone 15 Pro", "model": "iPhone 15 Pro", "os_version": "27.0",
               "orientation": "PORTRAIT", "status": "running"}
        with tempfile.TemporaryDirectory() as directory:
            with self.configuration(row, flows, drivers=[False]) as made:
                runner.run_with_retry("http://127.0.0.1:4723", row, Path(directory))
        self.assertEqual(len(made), 1)
        self.assertEqual(row["status"], "failed")
        self.assertNotIn("retries", row)

    def test_main_counts_a_passing_retry_as_passed(self):
        rows = environment.matrix({}, [])
        for row in rows:
            row.update(status="pending", model=row["requested_model"], os_version="27.0")

        def run(url, row, output):
            row.update(status="passed", assertions=[{"name": "check", "status": "passed"}],
                       retries=[{"reason": "DriverError: ECONNREFUSED 127.0.0.1:8100", "assertions": []}])

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            with mock.patch.object(environment, "source", return_value={"revision": "abc", "dirty": False}), \
                    mock.patch.object(environment, "inspect", return_value={"errors": [], "matrix": rows}), \
                    mock.patch.object(runner, "appium", return_value=contextlib.nullcontext("http://127.0.0.1:4723")), \
                    mock.patch.object(runner, "run_with_retry", side_effect=run):
                self.assertEqual(runner.main(["--output", str(output)]), 0)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertTrue(all(row["retries"] for row in report["matrix"]))

    def test_appium_owns_process_group_and_terminates_children_on_parent_exit(self):
        process = mock.Mock(pid=9321)
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("appium", 15), 0]
        status = io.BytesIO(b'{"value":{"ready":true}}')
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(runner.subprocess, "Popen", return_value=process) as popen, \
                    mock.patch.object(runner.urllib.request, "urlopen", return_value=status), \
                    mock.patch.object(runner.signal, "SIGKILL", 9, create=True), \
                    mock.patch.object(runner.os, "killpg", create=True) as killpg:
                with runner.appium(Path(directory)):
                    pass
            self.assertTrue(popen.call_args.kwargs["start_new_session"])
            self.assertEqual(killpg.call_args_list[0], mock.call(9321, runner.signal.SIGTERM))
            self.assertIn(mock.call(9321, 9), killpg.call_args_list)
            self.assertTrue(all(call.args[0] == 9321 for call in killpg.call_args_list))
