"""Simulator selection works on a fresh Mac without copying personal devices."""

import json
import subprocess
import unittest
from unittest import mock

from decklab.safari import environment, runner


class DeviceTypeMatrixTests(unittest.TestCase):
    def setUp(self):
        self.runtimes = [
            {"identifier": "ios18", "name": "iOS 18.0", "version": "18.0", "isAvailable": True},
            {"identifier": "ios26", "name": "iOS 26.0", "version": "26.0", "isAvailable": True},
            {"identifier": "ios27", "name": "iOS 27.0", "version": "27.0", "isAvailable": False},
        ]
        self.types = [
            {"name": "iPhone 15 Pro", "identifier": "type15", "minRuntimeVersion": 17 << 16},
            {"name": "iPhone 17 Pro", "identifier": "type17", "minRuntimeVersion": 26 << 16},
            {"name": "iPad Air 11-inch (M3)", "identifier": "air3"},
            {"name": "iPad Air 11-inch (M2)", "identifier": "air2"},
            {"name": "iPad Air 13-inch (M2)", "identifier": "large"},
        ]

    def test_fresh_mac_creates_all_six_without_existing_devices(self):
        rows = environment.matrix({}, self.runtimes, device_types=self.types)
        self.assertEqual([row["status"] for row in rows], ["pending"] * 6)
        self.assertEqual([row["device_type"] for row in rows], ["type15"] * 2 + ["type17"] * 2 + ["air2"] * 2)
        self.assertEqual({row["runtime"] for row in rows}, {"ios26"})
        self.assertTrue(all("udid" not in row for row in rows))

    def test_runtime_compatibility_marks_new_model_unavailable(self):
        rows = environment.matrix({}, self.runtimes, runtime="18.0", device_types=self.types)
        self.assertEqual(rows[0]["status"], "pending")
        self.assertEqual(rows[2]["status"], "unavailable")
        self.assertIn("18.0", rows[2]["reason"])

    def test_exact_ipad_overrides_default_and_missing_exact_does_not_fall_back(self):
        rows = environment.matrix({}, self.runtimes, ipad_model="iPad Air 11-inch (M3)", device_types=self.types)
        self.assertEqual(rows[4]["device_type"], "air3")
        missing = environment.matrix({}, self.runtimes, ipad_model="iPad Air 11-inch (M9)", device_types=self.types)
        self.assertEqual(missing[4]["status"], "unavailable")

    def test_runtime_supported_type_list_and_maximum_exclude_incompatible_types(self):
        runtime = [{**self.runtimes[1], "supportedDeviceTypes": [{"identifier": "type15"}]}]
        types = [{**self.types[0], "maxRuntimeVersion": (26 << 16) - 1}, self.types[1]]
        self.assertTrue(all(row["status"] == "unavailable" for row in
                            environment.matrix({}, runtime, device_types=types)))

    def test_newer_watchos_runtime_is_never_selected_for_an_iphone(self):
        runtimes = self.runtimes + [{"identifier": "watch30", "name": "watchOS 30.0",
                                    "version": "30.0", "isAvailable": True}]
        rows = environment.matrix({}, runtimes, device_types=self.types)
        self.assertEqual({row["runtime"] for row in rows}, {"ios26"})

    def test_simulator_uses_preselected_type_and_deletes_only_its_own_device(self):
        owned = "00000000-0000-0000-0000-000000000029"
        row = {"model": "iPhone 17 Pro", "runtime": "ios26", "device_type": "type17"}
        calls = []

        def command(*args, **kwargs):
            calls.append(args)
            self.assertNotIn("devicetypes", args)
            return owned if "create" in args else ""

        with mock.patch.object(environment, "run", side_effect=command):
            with runner.simulator(row) as actual:
                self.assertEqual(actual, owned)
        self.assertEqual(calls[0][-2:], ("type17", "ios26"))
        self.assertEqual(calls[-1], ("xcrun", "simctl", "delete", owned))


class EnvironmentInspectionTests(unittest.TestCase):
    def setUp(self):
        self.responses = {
            ("xcodebuild", "-version"): "Xcode 27.0\nBuild version 27A266a",
            ("xcode-select", "-p"): "/Applications/Xcode.app/Contents/Developer",
            ("node", "--version"): "v24.14.0",
            ("npm", "--version"): "11.9.0",
            (str(environment.APPIUM), "--version"): "3.8.0",
            ("xcrun", "simctl", "list", "runtimes", "--json"): json.dumps({"runtimes": [
                {"identifier": "ios26", "name": "iOS 26.0", "version": "26.0", "isAvailable": True}]}),
            ("xcrun", "simctl", "list", "devices", "--json"): '{"devices": {}}',
            ("xcrun", "simctl", "list", "devicetypes", "--json"): json.dumps({"devicetypes": [
                {"name": name, "identifier": name} for name in
                ("iPhone 15 Pro", "iPhone 17 Pro", "iPad Air 11-inch (M2)")]}),
        }
        for patch in (
                mock.patch.object(environment.platform, "platform", return_value="Mac test host"),
                mock.patch.object(environment.platform, "system", return_value="Darwin"),
                mock.patch.object(environment, "run", side_effect=lambda *args: self.responses[args]),
                mock.patch.object(environment.shutil, "which", return_value="/usr/bin/xcrun"),
                mock.patch.object(environment.Path, "read_text", return_value='{"version": "12.22.7"}')):
            self.enterContext(patch)
        self.pgrep = self.enterContext(mock.patch.object(environment.subprocess, "run", return_value=
            subprocess.CompletedProcess(["pgrep", "-x", "Simulator"], 1, stdout="", stderr="")))

    def test_old_mac_python_is_a_prerequisite_error_even_when_every_model_is_available(self):
        with mock.patch.object(environment.sys, "version_info", (3, 9, 6)), \
                mock.patch.object(environment.sys, "executable", "/usr/bin/python3"):
            found = environment.inspect()

        self.assertEqual(found["python"], "3.9.6")
        self.assertEqual(found["python_executable"], "/usr/bin/python3")
        self.assertEqual([row["status"] for row in found["matrix"]], ["pending"] * 6)
        self.assertEqual(len(found["errors"]), 1)
        self.assertIn("Python 3.11 or later is required", found["errors"][0])
        self.assertIn("/usr/bin/python3", found["errors"][0])
        self.assertIn("newer Python interpreter", found["errors"][0])

    def test_running_classic_simulator_ui_refuses_headless_run_without_closing_it(self):
        self.pgrep.return_value = subprocess.CompletedProcess(
            ["pgrep", "-x", "Simulator"], 0, stdout="391\n", stderr="")
        found = environment.inspect()
        self.assertTrue(found["classic_simulator_ui_running"])
        self.assertEqual(len(found["errors"]), 1)
        self.assertIn("Close Simulator and retry", found["errors"][0])
        self.pgrep.assert_called_once_with(["pgrep", "-x", "Simulator"], capture_output=True,
                                          text=True, timeout=10, stdin=subprocess.DEVNULL)

    def test_absent_classic_simulator_ui_allows_preflight(self):
        found = environment.inspect()
        self.assertFalse(found["classic_simulator_ui_running"])
        self.assertEqual(found["errors"], [])

    def test_failed_process_check_does_not_assume_the_ui_is_absent(self):
        self.pgrep.return_value = subprocess.CompletedProcess(
            ["pgrep", "-x", "Simulator"], 2, stdout="", stderr="process query failed")
        found = environment.inspect()
        self.assertNotIn("classic_simulator_ui_running", found)
        self.assertEqual(len(found["errors"]), 1)
        self.assertIn("Cannot check for the classic Simulator UI", found["errors"][0])


if __name__ == "__main__":
    unittest.main()
