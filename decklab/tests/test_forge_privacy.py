"""E10-S31 saved-list aliases and viewer-scoped Forge evidence, using fixtures only."""
import json
import types
import unittest
from unittest import mock

from decklab.lib import api, inventory, permissions, state
from decklab.lib.api import field_page, forge_runs, guard, variant_page
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state.memory import MemoryStore
from decklab.tests.test_api import GRUUL, _write
from decklab.tests.test_api_permissions import R_DECK
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_privacy_readers import USER1, USER2, R_DECK_ID, _as
from decklab.tests.test_matchups_api import GRUUL_ID, MatchupTestCase, body


class SavedVisibilityTests(MatchupTestCase):
    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(ROLES))
        self.member = self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md"
        _write(self.member, GRUUL.split("## Substitutes")[0].replace("# Gruul Test", "# User2 Copy"))
        _write(self.box.magic / "people" / "user2" / "collection.csv",
               "name,set,collector_number,finish,quantity,condition,language,notes\n")
        self.addCleanup(inventory.use(FileInventory(self.box.root)))
        self.addCleanup(state.use(MemoryStore(mode="everyone")))

    def test_private_latest_name_uses_the_viewers_identical_list(self):
        key = self.play(bv="target")["key"]
        self.finish()
        with _as("user2"):
            item, = api.matchups()["results"]
            answer = api.matchup(key=key)
            deck = api.deck_view(R_DECK_ID)
        self.assertEqual([s["id"] for s in item["sides"]], [R_DECK_ID, R_DECK_ID])
        self.assertTrue(all(s["current"] for s in item["sides"]))
        self.assertEqual([s["title"] for s in answer["sides"]], ["User2 Copy", "User2 Copy"])
        self.assertEqual(item["by"], "someone")
        self.assertEqual(deck["matchups"]["results"][0]["key"], key)
        self.assertNotIn("Gruul", json.dumps((item, answer, deck["matchups"])))

    def test_a_visible_older_alias_keeps_results_after_its_list_changes(self):
        key = self.play(bv="target")["key"]
        self.finish()
        for side in self.forge.saved[key]["sides"]:
            side["seen_as"].insert(0, {"id": R_DECK_ID, "version": "target", "title": "Earlier User2"})
        _write(self.member, R_DECK)
        with _as("user2"):
            item, = api.matchups()["results"]
            deck = api.deck_view(R_DECK_ID)
        self.assertEqual([s["id"] for s in item["sides"]], [R_DECK_ID, R_DECK_ID])
        self.assertTrue(all(not s["current"] for s in item["sides"]))
        self.assertEqual(deck["matchups"]["results"][0]["key"], key)

    def test_hidden_opponent_excludes_card_and_ai_totals(self):
        visible = self.play(bv="target")["key"]
        self.finish()
        hidden = self.play()["key"]                 # Play-now list has no visible identical alias
        self.finish()
        with _as("user2"):
            found = api.deck_view(R_DECK_ID)["matchups"]
            self.assertApiError(404, lambda: api.matchup(key=hidden))
        self.assertEqual([item["key"] for item in found["results"]], [visible])
        self.assertEqual(found["cards"]["of"], 1600)  # visible mirror: both sides, once each
        self.assertEqual(found["ai"]["games"], 1600)
        with mock.patch.object(guard, "public_deck_spaces", return_value={"home"}), _as("user2"):
            public = api.deck_view(R_DECK_ID)["matchups"]
        self.assertEqual({item["key"] for item in public["results"]}, {visible, hidden})
        self.assertGreater(public["cards"]["of"], found["cards"]["of"])
        self.assertTrue(all(item["sides"][0]["id"] == R_DECK_ID for item in public["results"]))

    def test_hidden_stop_is_404_and_owner_can_stop(self):
        self.playing()
        key = self.play()["key"]
        self.assertTrue(self.forge.started.wait(5))
        with _as("user2"):
            self.assertApiError(404, api.stop_matchup, body(profile="user2", key=key))
        with _as("user1"):
            running = api.matchups(running=True)["running"][0]
            self.assertTrue(running["may_stop"])
            self.assertTrue(api.matchup(key=key)["job"]["may_stop"])
            answer = api.stop_matchup(body(profile="user1", key=key))
        self.assertIn(answer["status"], ("done", "none"))
        self.finish()

    def test_deleted_alias_is_private_to_its_former_space(self):
        key = self.play(bv="target")["key"]
        self.finish()
        for side in self.forge.saved[key]["sides"]:
            side["seen_as"] = [{"id": "casual/gone", "version": "target", "title": "Private retired title"}]
            side["card_sha"] = "f" * 64             # no current list can represent it
        with mock.patch.object(guard, "public_deck_spaces", return_value={"home"}), _as("user2"):
            self.assertEqual(api.matchups()["results"], [])
            self.assertApiError(404, lambda: api.matchup(key=key))
            note = {"opponents": [], "last_run": {"deck": {"id": "casual/gone", "title": "Private retired title"}}}
            shown, _, _ = field_page._seen_field(note, [], forge_runs._Seen())
            self.assertIsNone(shown["last_run"])
        with _as("user1"):
            self.assertEqual(api.matchups()["results"][0]["sides"][0]["title"], "Private retired title")

    def test_hash_fallback_prefers_own_space_before_an_identical_public_list(self):
        key = self.play(bv="target")["key"]
        self.finish()
        for side in self.forge.saved[key]["sides"]:
            side["seen_as"] = [{"id": "user4/casual/hidden", "version": "target", "title": "Private alias"}]
        with mock.patch.object(guard, "public_deck_spaces", return_value={"home"}), _as("user2"):
            item, = api.matchups()["results"]
            answer = api.matchup(key=key)
        self.assertEqual([s["id"] for s in item["sides"]], [R_DECK_ID, R_DECK_ID])
        self.assertEqual([s["id"] for s in answer["sides"]], [R_DECK_ID, R_DECK_ID])

    def test_a_deleted_public_decks_live_run_is_anonymous_to_outsiders(self):
        seen = forge_runs._Seen(USER2)
        run = types.SimpleNamespace(entry={"id": "casual/deleted", "title": "Deleted private sentinel"}, by="Matt")
        job = types.SimpleNamespace(fn=run)
        with mock.patch.object(guard, "public_deck_spaces", return_value={"home"}), \
                mock.patch.object(forge_runs.COORD_JOBS, "snapshot", return_value={"detail": {}}):
            self.assertFalse(seen.sides([run.entry]))
            self.assertFalse(seen.coordinator(job))
            self.assertTrue(forge_runs._Seen(USER1).coordinator(job))


class StopIdentityTests(unittest.TestCase):
    def job(self, *, by_id=None):
        return types.SimpleNamespace(fn=types.SimpleNamespace(
            sides=[{"id": GRUUL_ID}], by=USER2["name"], by_id=by_id))

    def test_starter_right_uses_profile_id_and_never_a_reused_display_name(self):
        seen = forge_runs._Seen(USER2)
        self.assertFalse(seen.can_stop(self.job()))
        self.assertFalse(seen.can_stop(self.job(by_id="someone-else")))
        self.assertTrue(seen.can_stop(self.job(by_id="user2")))
        self.assertFalse(seen.can_stop(self.job(by_id="user2"), visible=False))
        self.assertTrue(forge_runs._Seen(USER1).can_stop(self.job()))  # home's own deck
        target = {"visible": True, "by": "User2", "spaces": ["home"]}
        self.assertFalse(permissions.can(USER2, "run.stop", target))

    def test_unknown_and_cross_space_duplicate_names_are_anonymous(self):
        profiles = [USER2, dict(USER1, name="User2")]
        with mock.patch.object(forge_runs, "_config_profiles", return_value=profiles):
            seen = forge_runs._Seen(USER2)
            self.assertEqual([seen.name(value) for value in ("User2", "Former Person", "Claude", "System")],
                             ["someone", "someone", "Claude", "System"])

    def test_variant_ownership_is_a_space_rule(self):
        variant_page._require_owner({"id": R_DECK_ID}, USER2)
        with self.assertRaises(api.ApiError) as raised:
            variant_page._require_owner({"id": R_DECK_ID}, USER1)
        self.assertEqual(raised.exception.status, 403)
