"""Profile status and install preflight over synthetic config and guarded system helpers."""
import json
from unittest import mock

from decklab.lib import access, config, profiles
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

    def test_local_only_and_valid_access_configs_have_no_extra_profile_warnings(self):
        for access in ({}, {"access": None}):
            self.assertEqual(profile_config.check({"profiles": [home(role="admin", emails=[])], **access}), [])
        valid = {"access": {}, "profiles": [home(role="admin", emails=[" A@Example.com ", "a@example.com"]),
                                            home("user2", role="member", space="user2", emails="user2@example.com")]}
        self.assertEqual(profile_config.check(valid), [])
        self.schtasks.assert_not_called()

    def test_access_missing_and_unsupported_aliases_are_static_position_only(self):
        value = {"access": {}, "profiles": [
            home(role="admin", emails=[]),
            home("user1", role="member", name="Private submitted name", plays_as="wife",
                 emails=["", "private-unusable-address", "é@example.com", None, "usable@example.com"]),
            home("user2", role="member", space="user2", emails={"secret": "private@example.com"})]}
        before = json.dumps(value)
        with mock.patch.object(config, "load", side_effect=AssertionError("unexpected config read")):
            lines = profile_config.check(value)
        self.assertEqual(json.dumps(value), before)
        self.assertEqual([(entry["level"], entry["text"].split("]: ")[0]) for entry in lines], [
            ("PROBLEM", "Entry 1 [access_no_email"),
            ("WARN", "Entry 2 [access_invalid_email"),
            ("PROBLEM", "Entry 3 [access_no_email"),
            ("WARN", "Entry 3 [access_invalid_email")])
        text = json.dumps(lines)
        for private in ("matt", "user1", "user2", "Private submitted name", "private-unusable-address", "é@example.com",
                        "usable@example.com", "private@example.com", "secret"):
            self.assertNotIn(private, text)
        self.assertNotIn("profile sync leave", text)
        self.schtasks.assert_not_called()

    def test_cross_profile_normalized_duplicates_warn_each_affected_usable_position(self):
        value = {"access": {}, "profiles": [home(role="admin", emails=[" SHARED@example.com ", "shared@example.com"]),
                    home("user1", role="member", plays_as="wife", emails=["own@example.com", "OWN@example.com"]),
                    home("user2", role="member", space="user2", emails=["shared@example.com", "other@example.com"])]}
        lines = profile_config.check(value)
        self.assertEqual([entry["text"].split("]: ")[0] for entry in lines],
                         ["Entry 1 [access_duplicate_email", "Entry 3 [access_duplicate_email"])
        self.assertTrue(all(entry["level"] == "PROBLEM" for entry in lines))
        self.assertNotIn("example.com", json.dumps(lines))
        value["profiles"][2]["id"] = "not/valid"
        self.assertEqual([entry["area"] for entry in profile_config.check(value)], ["Profiles"])

    def test_legacy_role_check_matches_verifier_without_tightening_preflight(self):
        value = {"access": {}, "profiles": [home(emails="matt@example.com")]}
        lines = profile_config.check(value)
        self.assertEqual(len(lines), 1)
        self.assertIn("profiles [access_legacy_roles]", lines[0]["text"])
        self.assertEqual(profiles.read_checked(value)[0]["role"], "member")
        # Even a rejected entry's role key disables legacy in the existing verifier.
        value["profiles"].append({"role": "member", "emails": ["matt@example.com"]})
        lines = profile_config.check(value)
        self.assertEqual([entry["area"] for entry in lines], ["Profiles"])
        self.assertIn("Entry 2 [invalid_id]", lines[0]["text"])

    def test_invalid_containers_stay_static_and_status_alias_checks_are_pure(self):
        for raw in ("private@example.com", {"secret": "private@example.com"}, [None, False, 3]):
            with self.subTest(raw=type(raw).__name__), \
                    mock.patch.object(config, "load", side_effect=AssertionError("unexpected config read")):
                lines = profile_config.check({"access": {}, "profiles": raw})
                self.assertTrue(lines)
                self.assertNotIn("private@example.com", json.dumps(lines))
        self.schtasks.assert_not_called()

    def test_unsupported_syntax_warning_leaves_tolerant_auth_alias_matching_unchanged(self):
        value = {"access": {}, "profiles": [home(role="admin", emails=["not-an-address"])]}
        before = profiles.read_checked(value)
        self.assertIsNone(profiles.supported_email("not-an-address"))
        self.assertEqual(profiles.email_key("not-an-address"), "not-an-address")
        self.assertEqual(profiles.supported_email(" A+B@Example.COM "), "a+b@example.com")
        lines = profile_config.check(value)
        self.assertEqual([entry["level"] for entry in lines], ["WARN"])
        self.assertIn("access_invalid_email", lines[0]["text"])
        self.assertEqual(profiles.read_checked(value), before)
        self.assertEqual(access.profile_for_email("not-an-address", value["profiles"])["id"], "matt")
