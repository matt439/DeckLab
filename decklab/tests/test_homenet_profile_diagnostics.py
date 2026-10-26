"""Profile status and install preflight over synthetic config and guarded system helpers."""
import json
from unittest import mock

from decklab.lib import config
from decklab.lib.homenet import commands, profile_config
from decklab.tests.homenet_support import Guarded, PORT, REAL_FACTS_NOON, Quiet, running_state
from decklab.tests import test_homenet as homenet_tests
from decklab.tests.test_profile_config_validation import home, invalid_settings


class HomenetProfileDiagnosticsTests(Guarded):
    def setUp(self):
        super().setUp()
        self.settings = {"profiles": [home(role="admin")]}
        patcher = mock.patch.object(config, "load", side_effect=lambda: self.settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.patch("decklab.lib.homenet.commands.task_user", return_value="HOMEPC\\player")
        self.patch("decklab.lib.homenet.commands.file_exists", return_value=True)

    def status(self):
        return homenet_tests.StatusCommandTests.run_status(self, REAL_FACTS_NOON, running_state(),
                                                          {"answered": True, "deck_lab": True, "cards_ready": True})

    def test_status_reports_static_entry_location_and_continues_other_checks(self):
        self.settings = invalid_settings()
        code, text = self.status()
        self.assertEqual(code, 1)
        self.assertIn("PROBLEM Profiles: Entry 2 [invalid_id]", text)
        self.assertIn("Fix that entry in decklab/config.json", text)
        self.assertIn("OK Network", text)
        for raw in ("not-valid@example.com", "Private submitted name", "private submitted space", "private@example.com"):
            self.assertNotIn(raw, text)
        self.schtasks.assert_not_called()

    def test_valid_status_does_not_add_roster_or_diagnostics(self):
        _, text = self.status()
        self.assertNotIn("Profiles:", text)
        self.assertNotIn("matt", text.lower())
        self.assertEqual(profile_config.check(self.settings), [])

    def test_install_refuses_before_platform_task_watchdog_directory_or_start_actions(self):
        self.settings = invalid_settings()
        with mock.patch.object(commands, "_windows_only") as platform, \
                mock.patch.object(commands, "pythonw_path") as pythonw, \
                mock.patch.object(commands, "register_task") as register, \
                mock.patch.object(commands, "_install_watchdog") as watchdog, \
                mock.patch.object(commands, "find_server") as find, \
                mock.patch.object(commands, "_starting") as starting, \
                mock.patch.object(commands, "_start_task") as start, Quiet() as output:
            self.assertEqual(commands.cmd_install("Fixture task", PORT), 1)
        for operation in (platform, pythonw, register, watchdog, find, starting, start):
            operation.assert_not_called()
        self.assertIn("local diagnostics", output.text)
        self.assertNotIn("Entry 2", output.text)
        self.assertNotIn("private@example.com", output.text)
        self.schtasks.assert_not_called()

    def test_main_install_refuses_generically_and_status_has_each_rejected_entry(self):
        self.settings = {"profiles": [home("claude"), home("user1", space="other"), home("user2", plays_as=None)]}
        with Quiet() as output:
            self.assertEqual(commands.main(["install", "--no-start"]), 1)
        self.assertIn("local diagnostics", output.text)
        self.assertNotIn("Entry ", output.text)
        status_code, text = self.status()
        self.assertEqual(status_code, 1)
        for entry, code in ((1, "reserved_id"), (2, "invalid_space"), (3, "invalid_plays_as")):
            self.assertIn(f"Entry {entry} [{code}]", text)
        for raw in ("claude", "user1", "user2", "other"):
            self.assertNotIn(raw, output.text)
        self.schtasks.assert_not_called()

    def test_install_config_read_failure_is_generic_and_has_no_side_effect(self):
        with mock.patch.object(config, "load", side_effect=ValueError("private@example.com")), \
                mock.patch.object(commands, "_windows_only") as platform, Quiet() as output:
            self.assertEqual(commands.cmd_install("Fixture task", PORT), 1)
        self.assertIn("could not be checked", output.text)
        self.assertNotIn("private@example.com", output.text)
        platform.assert_not_called()
        self.schtasks.assert_not_called()

    def test_diagnostics_contain_no_raw_payload_for_arbitrary_wrong_types(self):
        for raw in ("private@example.com", {"secret": "private@example.com"}, [None, False, 3]):
            lines = profile_config.check({"profiles": raw})
            self.assertTrue(lines)
            self.assertNotIn("private@example.com", json.dumps(lines))
