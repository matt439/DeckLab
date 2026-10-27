"""Local strict profile preflights preserve tolerant readers and never touch real configuration."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.db import migrate, profiles_sync, setup
from decklab.lib import config, profiles
from decklab.lib.homenet import profile_config


def home(pid="matt", **extra):
    return {"id": pid, "name": "Matt" if pid == "matt" else "User1", "plays_as": "user", **extra}


def invalid_settings():
    return {"profiles": [home(), {"id": "not-valid@example.com", "name": "Private submitted name",
                                  "space": "private submitted space", "emails": ["private@example.com"]}]}


class ProfileConfigValidationTests(unittest.TestCase):
    def test_each_existing_skip_has_a_position_code_and_static_reason(self):
        listed = [home(), "not an object", home("bad/id"), home("claude"), home(name=None),
                  home("user1", plays_as="not a player"), home("user2", space="someone-else"),
                  home("product", space="product"), home("matt")]
        before = copy.deepcopy(listed)
        parsed, issues = profiles.parse_with_diagnostics(listed)
        self.assertEqual(parsed, profiles.parse([home()]))
        self.assertEqual([(issue["index"], issue["code"]) for issue in issues],
                         [(2, "entry_type"), (3, "invalid_id"), (4, "reserved_id"), (5, "duplicate_id"),
                          (6, "invalid_plays_as"), (7, "invalid_space"), (8, "invalid_space"), (9, "duplicate_id")])
        self.assertEqual(listed, before)
        for issue in issues:
            self.assertEqual(set(issue), {"index", "code", "reason"})
            self.assertEqual(issue["reason"], profiles.ISSUE_REASONS[issue["code"]])
        _, issues = profiles.parse_with_diagnostics([home(name=None)])
        self.assertEqual(issues[0]["code"], "invalid_name")

    def test_malformed_containers_are_diagnosed_but_tolerant_parse_and_read_stay_empty(self):
        for value in (None, False, 0, "", "private@example.com", {}, (home(),)):
            with self.subTest(value=type(value).__name__):
                parsed, issues = profiles.parse_with_diagnostics(value)
                self.assertEqual(parsed, [])
                self.assertEqual(issues, [{"index": None, "code": "profiles_type",
                                           "reason": profiles.ISSUE_REASONS["profiles_type"]}])
                self.assertEqual(profiles.parse(value), [])
                self.assertEqual(profiles.read({"profiles": value}), [])
                with self.assertRaises(profiles.InvalidProfiles):
                    profiles.read_checked({"profiles": value})
        self.assertEqual(profiles.read_checked({}), [])
        self.assertEqual(profiles.read_checked({"profiles": []}), [])

    def test_rejected_role_key_still_disables_legacy_and_access_presence_keeps_its_old_rule(self):
        listed = [home(), {"role": "admin"}]
        parsed, issues = profiles.parse_with_diagnostics(listed)
        self.assertEqual(parsed[0]["role"], "member")
        self.assertEqual(issues[0]["code"], "invalid_id")
        for access in ({}, False, "", {"team": "fixture"}):
            with self.subTest(access=access):
                self.assertEqual(profiles.read_checked({"profiles": [home()], "access": access})[0]["role"], "member")
        self.assertEqual(profiles.read_checked({"profiles": [home()], "access": None})[0]["role"], "admin")

    def test_invalid_first_entry_does_not_claim_duplicate_id(self):
        listed = [home(plays_as="invalid"), home()]
        parsed, issues = profiles.parse_with_diagnostics(listed)
        self.assertEqual([p["id"] for p in parsed], ["matt"])
        self.assertEqual([(p["index"], p["code"]) for p in issues], [(1, "invalid_plays_as")])

    def test_retained_names_role_fallback_person_plays_as_and_email_rules_are_unchanged(self):
        listed = [home(name="", role="admin", emails=[" A@Example.com ", "a@example.com", "", 3, "\u212a@example.com"]),
                  home("user1", name="   ", role="admim", emails="A@example.com"),
                  home("user2", space="user2", role=None, plays_as="ignored", emails={"unusable": True})]
        parsed, issues = profiles.parse_with_diagnostics(listed)
        self.assertEqual(issues, [])
        self.assertEqual([(p["name"], p["role"], p["plays_as"], p["emails"]) for p in parsed],
                         [("", "admin", "user", ["a@example.com"]), ("   ", "member", "user", ["a@example.com"]),
                          ("User1", "member", None, [])])
        self.assertIsNone(profiles.for_email("a@example.com", parsed))
        self.assertEqual(profiles.read_checked({"profiles": listed}), profiles.parse(listed))

    def test_diagnostics_exception_and_local_formatter_never_echo_submitted_values(self):
        settings = invalid_settings()
        with self.assertRaises(profiles.InvalidProfiles) as caught:
            profiles.read_checked(settings)
        _, issues = profiles.parse_with_diagnostics(settings["profiles"])
        self.assertEqual(caught.exception.issues, issues)
        text = str(caught.exception) + json.dumps(issues) + json.dumps(profile_config.check(settings))
        for private in ("not-valid@example.com", "Private submitted name", "private submitted space", "private@example.com"):
            self.assertNotIn(private, text)
        self.assertIn("local diagnostics", str(caught.exception))
        self.assertNotIn("Entry 2", str(caught.exception))
        self.assertIn("Entry 2", json.dumps(profile_config.check(settings)))

    def test_valid_config_has_no_diagnostic_output_and_results_are_independent(self):
        listed = [home(role="admin"), home("user2", space="user2", role="member", emails=["user2@example.com"])]
        before = copy.deepcopy(listed)
        settings = {"profiles": listed}
        parsed = profiles.read_checked(settings)
        self.assertEqual(profile_config.check(settings), [])
        parsed[1]["emails"].append("other@example.com")
        parsed[0]["name"] = "Changed"
        self.assertEqual(listed, before)


class ProfileSetupSafetyTests(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        temporary = tempfile.TemporaryDirectory(prefix="decklab-profile-preflight-", dir=root)
        self.addCleanup(temporary.cleanup)
        patcher = mock.patch.object(config, "CONFIG_FILE", Path(temporary.name) / "config.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_config_backed_sync_refuses_before_connection_or_database_log(self):
        with mock.patch.object(config, "load", return_value=invalid_settings()), \
                mock.patch.object(profiles_sync.db, "connect") as connect, \
                mock.patch.object(profiles_sync.db, "log") as log:
            with self.assertRaises(profiles.InvalidProfiles):
                profiles_sync.sync()
        connect.assert_not_called()
        log.assert_not_called()

    def test_explicit_programmatic_sync_inputs_do_not_read_or_validate_config(self):
        with mock.patch.object(config, "load", side_effect=AssertionError("unexpected config read")), \
                mock.patch.object(profiles_sync.db, "connect") as connect, \
                mock.patch.object(profiles_sync.db, "log"):
            self.assertEqual(profiles_sync.sync([]), {"added": [], "changed": [], "removed": []})
            with self.assertRaisesRegex(ValueError, "audit trail"):
                profiles_sync.sync([{"id": "claude"}])
        connect.assert_not_called()

    def test_setup_refuses_before_database_settings_superuser_roles_migrations_or_sync(self):
        with mock.patch.object(config, "load", return_value=invalid_settings()), \
                mock.patch.object(setup.db, "settings") as settings, \
                mock.patch.object(setup, "_superuser") as superuser, \
                mock.patch.object(setup, "ensure_roles") as roles, \
                mock.patch.object(setup, "ensure_database") as database, \
                mock.patch.object(setup, "secure_database") as secure, \
                mock.patch.object(migrate, "apply") as migrations, \
                mock.patch.object(profiles_sync, "sync") as sync, \
                mock.patch.object(setup, "ensure_empty_inventory") as empty:
            with self.assertRaises(profiles.InvalidProfiles):
                setup.run()
        for operation in (settings, superuser, roles, database, secure, migrations, sync, empty):
            operation.assert_not_called()

    def test_valid_setup_syncs_the_exact_preflight_snapshot_without_reloading_profiles(self):
        settings = {"profiles": [home(role="admin")]}
        expected = profiles.read_checked(settings)
        with mock.patch.object(config, "load", side_effect=[settings, AssertionError("profile config reloaded")]) as load, \
                mock.patch.object(setup, "_superuser"), mock.patch.object(setup, "ensure_roles"), \
                mock.patch.object(setup, "ensure_database"), mock.patch.object(setup, "secure_database"), \
                mock.patch.object(migrate, "apply", return_value=[]) as migrations, \
                mock.patch.object(profiles_sync, "sync", return_value={"added": [], "changed": [], "removed": []}) as sync, \
                mock.patch.object(setup, "ensure_empty_inventory") as empty:
            self.assertEqual(setup.run(dbname="fixture_only", say=mock.Mock()), 0)
        load.assert_called_once_with()
        migrations.assert_called_once_with(dbname="fixture_only", say=mock.ANY)
        sync.assert_called_once_with(listed=expected, dbname="fixture_only")
        empty.assert_called_once_with("fixture_only", say=mock.ANY)
