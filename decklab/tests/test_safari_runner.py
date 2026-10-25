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
