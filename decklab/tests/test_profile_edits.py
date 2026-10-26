"""Profile-edit guards only touch temporary config files; no real household data."""
import copy
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from decklab.db import profile_edits
from decklab.lib import access, config, profile_config, profiles
from decklab.lib.api import settings
from decklab.lib.state import Actor

ACTOR = Actor("matt", "Matt", via="home")
LOCAL_TEMP = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None


def raw_config():
    return {"profiles": [
        {"id": "matt", "name": "Matt", "role": "admin", "space": "home", "plays_as": "user",
         "emails": ["matt@example.com"]},
        {"id": "user1", "name": "User1", "role": "member", "space": "home", "plays_as": "wife",
         "emails": ["user1@example.com"]},
        {"id": "user2", "name": "User2", "role": "member", "space": "user2",
         "emails": [" Old@Example.com ", "Alias@Example.com"], "unknown": {"keep": [1, 2]}},
    ], "unknown": {"nested": ["preserved", {"enabled": True}]}, "port": 9999}


class TemporaryConfig(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="decklab-profile-edit-", dir=LOCAL_TEMP)
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "config.json"
        self.raw = raw_config()
        self.write(self.raw)
        patcher = mock.patch.object(config, "CONFIG_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(config.EXTRA_ENV, None)

    def write(self, value):
        self.path.write_text(json.dumps(value, indent=4) + "\n", encoding="utf-8")

    def apply(self, **extra):
        args = {"config_sha256": profile_config.digest(self.path.read_bytes()),
                "membership_sha256": "a" * 64, "actor": ACTOR, **extra}
        return profile_edits.apply("user2", "old@example.com", "new@example.com", **args)


class ProfileEditValidationTests(TemporaryConfig):
    def test_new_address_validation_rejects_unusable_forms_before_connection(self):
        bad = [None, "", "no-at", "a@", "a@@example.com", "a b@example.com", "é@example.com",
               ".a@example.com", "a..b@example.com", "a.@example.com", "a@-example.com", "a@example..com",
               "a@localhost", "a" * 65 + "@example.com", "a\n@example.com"]
        with mock.patch.object(profile_edits.db, "connect") as connect:
            for value in bad:
                with self.subTest(value=value), self.assertRaises(profile_edits.InvalidProfileEdit):
                    profile_edits.apply("user2", "old@example.com", value,
                                        config_sha256="a" * 64, membership_sha256="b" * 64, actor=ACTOR)
        connect.assert_not_called()

    def test_legacy_invalid_duplicate_and_override_refuse_without_connecting(self):
        invalid = []
        legacy = copy.deepcopy(self.raw)
        for profile in legacy["profiles"]:
            profile.pop("role")
        invalid.append(legacy)
        duplicate = copy.deepcopy(self.raw)
        duplicate["profiles"][0]["emails"].append("OLD@example.com")
        invalid.append(duplicate)
        malformed = copy.deepcopy(self.raw)
        malformed["profiles"].append({"id": "bad/id"})
        invalid.append(malformed)
        with mock.patch.object(profile_edits.db, "connect") as connect:
            for raw in invalid:
                self.write(raw)
                with self.assertRaises(profile_edits.InvalidProfileEdit):
                    profile_edits.preview(actor=ACTOR)
            self.write(self.raw)
            os.environ[config.EXTRA_ENV] = "unused-fixture-path"
            with self.assertRaises(profile_edits.InvalidProfileEdit):
                profile_edits.preview(actor=ACTOR)
        connect.assert_not_called()

    def test_actor_must_still_be_a_named_home_admin(self):
        actors = [Actor("user1", "User1", via="home"), Actor("user2", "User2", via="tunnel"),
                  Actor("claude", "Claude", source="cli"), Actor("matt", "Matt", source="web")]
        with mock.patch.object(profile_edits.db, "connect") as connect:
            for actor in actors:
                with self.subTest(actor=actor.id), self.assertRaises(profile_edits.InvalidProfileEdit):
                    self.apply(actor=actor)
            self.raw["profiles"][0]["role"] = "member"
            self.write(self.raw)
            with self.assertRaises(profile_edits.InvalidProfileEdit):
                self.apply()
        connect.assert_not_called()

    def test_duplicate_json_keys_never_get_lost_by_reserialization(self):
        self.path.write_text('{"profiles": [], "unknown": 1, "unknown": 2}', encoding="utf-8")
        with self.assertRaises(profile_edits.InvalidProfileEdit), mock.patch.object(profile_edits.db, "connect") as c:
            profile_edits.preview(actor=ACTOR)
        c.assert_not_called()

    def test_serialization_growth_is_refused_before_any_database_write_or_journal(self):
        compact = json.dumps(self.raw, separators=(",", ":")).encode()
        self.path.write_bytes(compact)
        with mock.patch.object(profile_config, "MAX_CONFIG", len(compact) + 10), \
                mock.patch.object(profile_edits.db, "connect") as connect:
            with self.assertRaises(profile_edits.InvalidProfileEdit):
                self.apply()
        self.assertEqual(self.path.read_bytes(), compact)
        self.assertFalse(profile_config.pending())
        connect.assert_not_called()

    def test_pending_gate_blocks_profile_and_api_reads_but_not_database_settings(self):
        with profile_config.claim():
            profile_config.prepare({"version": 1})
        with self.assertRaises(profile_edits.PendingProfileEdit):
            profiles.read()
        with self.assertRaises(settings.ApiError) as caught:
            settings._config_profiles()
        self.assertEqual(caught.exception.status, 503)
        with self.assertRaises(profile_edits.PendingProfileEdit):
            access._config_profiles()
        self.assertEqual(config.load()["profiles"], self.raw["profiles"])
        # Explicit parsers do not consult any local pending state.
        self.assertEqual(profiles.read(self.raw), profiles.parse(self.raw["profiles"]))

    def test_claim_reentrant_and_other_thread_is_bounded(self):
        result = []
        def worker():
            try:
                with profile_config.claim():
                    result.append("unexpected")
            except profile_edits.PendingProfileEdit:
                result.append("busy")
        with profile_config.claim():
            with profile_config.claim():
                thread = threading.Thread(target=worker)
                thread.start()
                thread.join(3)
                self.assertFalse(thread.is_alive())
        self.assertEqual(result, ["busy"])

    def test_raw_alias_replace_preserves_unknown_fields_and_other_alias_spelling(self):
        listed = profiles.read_checked(self.raw)
        changed = profile_edits._replace(self.raw, listed, "user2", "old@example.com", "new@example.com")
        expected = copy.deepcopy(self.raw)
        expected["profiles"][2]["emails"][0] = "new@example.com"
        self.assertEqual(changed, expected)
        self.assertEqual(self.raw, raw_config())
        for member in ("matt", "user1", "missing"):
            with self.subTest(member=member), self.assertRaises(profile_edits.InvalidProfileEdit):
                profile_edits._replace(self.raw, listed, member, "old@example.com", "new@example.com")

    def test_alias_collisions_and_missing_source_refuse(self):
        listed = profiles.read_checked(self.raw)
        with self.assertRaises(profile_edits.InvalidProfileEdit):
            profile_edits._replace(self.raw, listed, "user2", "old@example.com", "alias@example.com")
        with self.assertRaises(profile_edits.StaleProfileEdit):
            profile_edits._replace(self.raw, listed, "user2", "missing@example.com", "new@example.com")
        self.raw["profiles"][2]["emails"].append("OLD@example.com")
        with self.assertRaises(profile_edits.StaleProfileEdit):
            profile_edits._replace(self.raw, profiles.read_checked(self.raw), "user2", "old@example.com", "new@example.com")
