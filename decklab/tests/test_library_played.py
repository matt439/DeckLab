"""The library's last played and game counts (E1-S27, library_played.played_extras): from the Game
log's two-player games the viewer may see, a hidden other side counted but never named, pods
left out, and nothing claimed when the games can't be read.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_library_played
"""
import json
import unittest
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import deck_page, library_played
from decklab.lib.api import play_pods as pods
from decklab.lib.api import play_records as play
from decklab.tests.test_api import ApiTestCase, ELF_COMMANDER, _write
from decklab.tests.test_play_pods import encoded, selector
from decklab.tests.test_play_records import DECK, MixedFixture


class LibraryPlayedTests(MixedFixture, ApiTestCase):
    def setUp(self):
        super().setUp()
        (self.deckfile.parent / "unplayed.md").write_text(DECK.replace("Practice deck", "Unplayed deck"),
                                                         encoding="utf-8")

    def game_on(self, day, a, b, *, recorded_as=(), **extra):
        sides = [{**play._snapshot(deck_id, "target"), "player": player, "mulligans": 0}
                 for deck_id, player in ((a, "Matt"), (b, "User1"))]
        for side, old in zip(sides, recorded_as):
            if old:             # recorded before the deck's rename, under its old id
                side["id"] = old
                side["sha256"] = play._hash(play._bytes({k: side[k] for k in ("id", "version", "sections")}))
        return self.put("games", {"date": day, "result": "draw", "notes": "", "sides": sides,
                                  "space": "home", **extra})

    def played(self, ids):
        return {s["id"]: s["played"] for s in library_played.played_extras([{"id": i} for i in ids])}

    def test_counts_and_last_played_from_the_viewer_s_games(self):
        self.game_on("2026-10-20", "casual/other", "casual/gruul-test")
        ids = ["casual/gruul-test", "casual/other", "casual/unplayed"]
        for viewer in ("matt", "user1"):
            with self.subTest(viewer=viewer), access.viewing(viewer):
                self.assertEqual(self.played(ids), {
                    # Home's game, the one against User2's deck and the later one.
                    "casual/gruul-test": {"last": "2026-10-20", "games": 3},
                    "casual/other": {"last": "2026-10-20", "games": 2},
                    "casual/unplayed": {"last": None, "games": 0}})

    def test_a_hidden_other_side_counts_for_the_viewer_s_deck_but_is_never_named(self):
        with access.viewing("user2"):
            index = deck_page.decks_index()
        by_id = {s["id"]: s for s in index["decks"]}
        # Home's deck against his and User3's against his both count; neither other deck is in his answer.
        self.assertEqual(by_id["user2/casual/r-elves"]["played"], {"last": "2026-10-08", "games": 2})
        self.assertEqual(set(by_id), {"user2/casual/r-elves"})
        text = json.dumps(index)
        self.assertNotIn("gruul", text)
        self.assertNotIn("m-elves", text)
        with access.viewing("user3"):
            self.assertEqual(self.played(["user3/casual/m-elves"]),
                             {"user3/casual/m-elves": {"last": "2026-10-08", "games": 1}})

    def test_a_renamed_deck_s_games_under_its_old_id_count_for_it_once(self):
        self.game_on("2026-10-22", "casual/gruul-test", "casual/other", recorded_as=("casual/old-gruul", None))
        # Both ids on one game: the deck played against itself, before and after the rename.
        self.game_on("2026-10-23", "casual/gruul-test", "casual/gruul-test", recorded_as=(None, "casual/old-gruul"))
        current = inventory.current
        renamed = lambda: current().replace(deck_aliases={"casual/old-gruul": "casual/gruul-test"})
        with access.viewing("user1"), mock.patch.object(inventory, "current", renamed):
            self.assertEqual(self.played(["casual/gruul-test", "casual/other"]), {
                "casual/gruul-test": {"last": "2026-10-23", "games": 4},
                "casual/other": {"last": "2026-10-22", "games": 2}})

    def test_a_saved_commander_pod_counts_in_no_deck_s_games(self):
        _write(self.box.magic / "decks/commander/pod-a.md",
               ELF_COMMANDER.replace("Elf Commander", "Pod fixture A").replace("wife", "user"))
        self.box.stack.enter_context(mock.patch.object(play, "_play_today", return_value="2026-10-28"))
        with access.using(None), access.viewing(None):
            deck = selector(play._snapshot("commander/pod-a", "target"))
        data = {"profile": "matt", "id": None, "sha256": None, "preview": True, "mode": "pod", "game_version": 2,
                "date": "2026-10-27", "result": "s1", "notes": "",
                "seats": [{"seat_id": "s1", "type": "deck", "player": "Matt", "deck": deck},
                          {"seat_id": "s2", "type": "external", "player": "Guest A", "commander": ""},
                          {"seat_id": "s3", "type": "external", "player": "Guest B", "commander": ""}]}
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            preview = pods.save_pod(encoded(data))
            pods.save_pod(encoded({**data, "id": preview["id"], "preview": False,
                                   "review_sha256": preview["review_sha256"]}))
        self.assertEqual(len([r for r in self.box.state.play_list("games") if r.get("mode") == "pod"]), 1)
        with access.viewing("matt"):
            self.assertEqual(self.played(["commander/pod-a", "casual/gruul-test"]), {
                "commander/pod-a": {"last": None, "games": 0},
                "casual/gruul-test": {"last": "2026-10-08", "games": 2}})

    def test_damaged_records_and_mirrors(self):
        damaged = self.game_on("2026-10-26", "casual/gruul-test", "casual/other")
        self.box.state._play[("games", damaged)]["content"]["sides"][0]["sections"]["Deck"][0]["qty"] += 1
        self.game_on("2026-10-21", "casual/unplayed", "casual/unplayed")
        with access.viewing("user1"):
            self.assertEqual(self.played(["casual/gruul-test", "casual/unplayed"]), {
                "casual/gruul-test": {"last": "2026-10-08", "games": 2},     # not the damaged one
                "casual/unplayed": {"last": "2026-10-21", "games": 1}})      # both sides, one game

    def test_games_that_can_t_be_read_claim_nothing(self):
        self.box.state.down = True
        with access.viewing("user1"):
            self.assertEqual(self.played(["casual/gruul-test"]), {"casual/gruul-test": None})
        self.box.state.down = False
        # A login that isn't set up sees no games (nor any deck).
        with access.using({"profile": None, "email": "someone@example.com", "remote": True}):
            self.assertEqual(self.played(["casual/gruul-test"]), {"casual/gruul-test": None})


class LegacyGameTests(unittest.TestCase):
    def test_only_original_two_side_games_count(self):
        sides = [{"id": "casual/a"}, {"id": "casual/b"}]
        self.assertTrue(library_played._legacy({"sides": sides}))
        for record in ({"sides": sides, "mode": "pod"}, {"sides": sides, "game_version": 2},
                       {"sides": sides[:1]}, {"sides": sides * 2}, {"sides": None}, {"seats": sides}, None, []):
            with self.subTest(record=record):
                self.assertFalse(library_played._legacy(record))
