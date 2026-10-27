"""Creation refuses unsafe source/actor/growth before database or Forge work."""
import json
from unittest import mock

from decklab.db import profile_admission, profile_edits
from decklab.lib import profile_config
from decklab.lib.state import Actor
from decklab.tests.test_profile_edits import ACTOR, TemporaryConfig


class ProfileCreationValidationTests(TemporaryConfig):
    def create(self, **extra):
        args = {"member_id": "user3", "name": "User3", "email": "user3@example.com",
                "config_sha256": profile_config.digest(self.path.read_bytes()), "membership_sha256": "a" * 64,
                "actor": ACTOR, **extra}
        return profile_edits.create(**args)

    def test_legacy_configuration_and_changed_actor_refuse_before_forge_or_database(self):
        with mock.patch.object(profile_admission, "forge_claim") as forge, \
                mock.patch.object(profile_edits.db, "connect") as connect:
            with self.assertRaises(profile_edits.InvalidProfileEdit):
                self.create(actor=Actor("user1", "User1", via="home"))
            for row in self.raw["profiles"]:
                row.pop("role")
            self.write(self.raw)
            with self.assertRaises(profile_edits.InvalidProfileEdit):
                self.create()
        forge.assert_not_called()
        connect.assert_not_called()
        self.assertFalse(profile_config.pending())

    def test_serialization_growth_refuses_before_forge_or_database(self):
        compact = json.dumps(self.raw, separators=(",", ":")).encode()
        self.path.write_bytes(compact)
        with mock.patch.object(profile_config, "MAX_CONFIG", len(compact) + 10), \
                mock.patch.object(profile_admission, "forge_claim") as forge, \
                mock.patch.object(profile_edits.db, "connect") as connect:
            with self.assertRaises(profile_edits.InvalidProfileEdit):
                self.create()
        forge.assert_not_called()
        connect.assert_not_called()
        self.assertFalse(profile_config.pending())
        self.assertEqual(self.path.read_bytes(), compact)
