"""The library's last played and game counts (E1-S27, library_played.played_extras): from the Game
log's two-player games the viewer may see, a hidden other side counted but never named, pods
left out, and nothing claimed when the games can't be read.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_library_played
"""
import json

from decklab.lib import access
from decklab.lib.api import deck_page, library_played
from decklab.lib.api import play_records as play
from decklab.tests.test_api import ApiTestCase
from decklab.tests.test_play_records import DECK, MixedFixture


class LibraryPlayedTests(MixedFixture, ApiTestCase):
    def setUp(self):
        super().setUp()
        (self.deckfile.parent / "unplayed.md").write_text(DECK.replace("Practice deck", "Unplayed deck"),
                                                         encoding="utf-8")

    def game_on(self, day, a, b, **extra):
        sides = [{**play._snapshot(deck_id, "target"), "player": player, "mulligans": 0}
                 for deck_id, player in ((a, "Matt"), (b, "User1"))]
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

    def test_pods_damaged_records_and_mirrors(self):
        # Pod markers on a game naming two of the decks (a real pod has seats; only the markers matter here).
        pod = self.game_on("2026-10-25", "casual/gruul-test", "casual/other")
        self.box.state._play[("games", pod)]["content"].update(mode="pod", game_version=2)
        damaged = self.game_on("2026-10-26", "casual/gruul-test", "casual/other")
        self.box.state._play[("games", damaged)]["content"]["sides"][0]["sections"]["Deck"][0]["qty"] += 1
        self.game_on("2026-10-21", "casual/unplayed", "casual/unplayed")
        with access.viewing("user1"):
            self.assertEqual(self.played(["casual/gruul-test", "casual/unplayed"]), {
                "casual/gruul-test": {"last": "2026-10-08", "games": 2},     # neither the pod nor the damaged one
                "casual/unplayed": {"last": "2026-10-21", "games": 1}})      # both sides, one game

    def test_games_that_can_t_be_read_claim_nothing(self):
        self.box.state.down = True
        with access.viewing("user1"):
            self.assertEqual(self.played(["casual/gruul-test"]), {"casual/gruul-test": None})
        self.box.state.down = False
        # A login that isn't set up sees no games (nor any deck).
        with access.using({"profile": None, "email": "someone@example.com", "remote": True}):
            self.assertEqual(self.played(["casual/gruul-test"]), {"casual/gruul-test": None})
