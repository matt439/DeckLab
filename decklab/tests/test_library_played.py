"""The library's last played and game counts (E1-S27, library_played.played_extras): from the Game
log's two-player games the viewer may see, a hidden other side counted but never named, pods
left out, and nothing claimed when the games can't be read. The deck page's (deck_played, slices
2 and 3): the same counts and what the deck's list changed since its last game, from its revisions.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_library_played
"""
import json
import unittest
from datetime import datetime, timezone
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.inventory.model import DeckRevision
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


CHANGED = DECK.replace("4 Elvish Mystic\n", "3 Elvish Mystic\n1 Sol Ring\n").replace(
    "2 Pick Your Poison (MKM) 170", "2 Pick Your Poison (MKM) 999")


def revision(number, text, op="M"):
    return DeckRevision(deck_id="casual/gruul-test", revision=number, at=datetime(2026, 10, number, tzinfo=timezone.utc),
                        actor="matt", message="Save", op=op, text=text)


class DeckPlayedTests(MixedFixture, ApiTestCase):
    """The deck page's "played" (deck_view, library_played.deck_played): the Overview's Last played
    line and what the list changed after the last game."""

    game_on = LibraryPlayedTests.game_on

    def revisions(self, *found):
        return self.box.stack.enter_context(
            mock.patch.object(inventory, "deck_revisions_with_text", return_value=list(found)))

    def test_an_unchanged_list_says_so(self):
        with access.viewing("user1"):
            self.assertEqual(library_played.deck_played("casual/gruul-test"), {
                "last": "2026-10-08", "games": 2, "since": {"version": "target", "changes": [], "more": 0}})
            self.assertEqual(deck_page.deck_view("casual/gruul-test")["played"]["games"], 2)
            self.assertEqual(library_played.deck_played("casual/unplayed"), {"last": None, "games": 0, "since": None})

    def test_the_changes_since_the_last_game_come_from_the_revision_it_was_played_with(self):
        self.deckfile.write_text(CHANGED, encoding="utf-8")
        older = DECK.replace("52 Forest", "51 Forest\n1 Mountain")
        reads = self.revisions(revision(4, CHANGED), revision(3, None, "D"), revision(2, DECK), revision(1, older))
        with access.viewing("matt"):
            played = library_played.deck_played("casual/gruul-test")
        reads.assert_called_once_with("casual/gruul-test", library_played.MAX_REVISIONS)
        self.assertEqual(played, {"last": "2026-10-08", "games": 2, "since": {"version": "target", "more": 0, "changes": [
            {"section": "Deck", "name": "Sol Ring", "delta": 1, "printing": False},
            {"section": "Deck", "name": "Elvish Mystic", "delta": -1, "printing": False},
            {"section": "Sideboard", "name": "Pick Your Poison", "delta": 0, "printing": True}]}})
        with access.viewing("matt"), mock.patch.object(library_played, "MAX_CHANGES", 1):
            since = library_played.deck_played("casual/gruul-test")["since"]
        self.assertEqual((len(since["changes"]), since["more"]), (1, 2))

    def test_a_list_no_revision_matches_claims_nothing(self):
        self.deckfile.write_text(CHANGED, encoding="utf-8")
        self.revisions(revision(2, CHANGED))
        with access.viewing("matt"):
            self.assertEqual(library_played.deck_played("casual/gruul-test"),
                             {"last": "2026-10-08", "games": 2, "since": None})

    def test_the_last_day_s_games_only_and_a_later_list_played_wins(self):
        self.deckfile.write_text(CHANGED, encoding="utf-8")
        self.game_on("2026-10-20", "casual/gruul-test", "casual/other")      # played with CHANGED
        reads = self.revisions()
        with access.viewing("matt"):
            self.assertEqual(library_played.deck_played("casual/gruul-test"), {
                "last": "2026-10-20", "games": 3, "since": {"version": "target", "changes": [], "more": 0}})
        reads.assert_not_called()       # today's list matched: no revisions read

    def test_a_sideboard_plan_s_game_is_matched_by_the_list_before_its_swaps(self):
        side = {"id": "casual/gruul-test", "version": "target", "sha256": "0" * 64, "base_sha256": "1" * 64}
        self.assertEqual(library_played._played_with(side), ("casual/gruul-test", "target", "1" * 64))
        self.assertIsNone(library_played._played_with({"id": "casual/x", "version": "both", "sha256": "1" * 64}))

    def test_a_member_s_deck_page_names_no_hidden_side(self):
        with access.viewing("user2"):
            answer = deck_page.deck_view("user2/casual/r-elves")
        self.assertEqual(answer["played"], {"last": "2026-10-08", "games": 2,
                                            "since": {"version": "target", "changes": [], "more": 0}})
        text = json.dumps(answer["played"])
        self.assertNotIn("gruul", text)
        self.assertNotIn("m-elves", text)
        with access.viewing("user3"):
            self.assertEqual(library_played.deck_played("user3/casual/m-elves")["games"], 1)

    def test_games_that_can_t_be_read_or_a_failing_comparison(self):
        self.box.state.down = True
        with access.viewing("user1"):
            self.assertIsNone(library_played.deck_played("casual/gruul-test"))
        self.box.state.down = False
        self.deckfile.write_text(CHANGED, encoding="utf-8")
        with access.viewing("user1"), mock.patch.object(inventory, "deck_revisions_with_text", side_effect=RuntimeError):
            self.assertEqual(library_played.deck_played("casual/gruul-test")["since"], None)


class LegacyGameTests(unittest.TestCase):
    def test_only_original_two_side_games_count(self):
        sides = [{"id": "casual/a"}, {"id": "casual/b"}]
        self.assertTrue(library_played._legacy({"sides": sides}))
        for record in ({"sides": sides, "mode": "pod"}, {"sides": sides, "game_version": 2},
                       {"sides": sides[:1]}, {"sides": sides * 2}, {"sides": None}, {"seats": sides}, None, []):
            with self.subTest(record=record):
                self.assertFalse(library_played._legacy(record))
