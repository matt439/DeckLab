"""Tests for the library's popular-decks line (E3-S36): GET /api/library/gauntlet
(api/library_gauntlet.library_gauntlet_view), the Testing page's board rows (gauntlet_board.standing)
cut down to what the library shows.

They run in test_gauntlet_board's sandbox (home's casual Gruul Test and Gruul Two, User2's own R Elves, a
constructed catalogue of three popular decks and a Commander one of none) with its BoardGauntlet. Saved games
only: nothing plans, estimates or plays. No Forge game, network, database or real catalogue is used.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_library_gauntlet
"""
import json
import unittest
from unittest import mock

from decklab.lib.api import gauntlet_board, library_gauntlet
from decklab.tests import test_server as support
from decklab.tests.test_gauntlet_api import GRUUL, R_ELVES
from decklab.tests.test_gauntlet_board import IDS, BoardTestCase

FIELDS = {"format", "state", "overall", "played", "of", "games", "updated", "before", "older", "trial"}


class LibraryGauntletTests(BoardTestCase):

    def library(self, who="matt"):
        return self.call(who, library_gauntlet.library_gauntlet_view)

    def test_only_the_compact_fields_and_nothing_inventory_derived(self):
        self.g.per = {self.sha(GRUUL): {i: 0.6 for i in IDS}}
        found = self.library()
        self.assertEqual(set(found), {"formats", "decks", "notes", "error"})
        self.assertEqual(found["formats"]["constructed"], {"state": "ok", "size": 3})
        self.assertIsNone(found["error"])
        row = found["decks"][GRUUL]
        self.assertEqual(set(row), FIELDS)
        self.assertEqual((row["format"], row["state"], row["played"], row["of"], row["games"]),
                         ("constructed", "done", 3, 3, 300))
        self.assertIs(row["trial"], False)         # E3-S39: True only for a precon trial ("Not owned")
        self.assertEqual(row["overall"], {"rate": 0.6, "low": 0.5, "high": 0.7})
        self.assertFalse(any(i.startswith("product/fdn-beginner-box/") for i in found["decks"]))
        text = json.dumps(found, allow_nan=False)
        for word in ("owned", "missing", "status", "versions", "revision", "hardest", "playing", "build_command",
                     "card_sha", "title"):
            self.assertNotIn(f'"{word}"', text)
        self.assertNotIn("secret", text)

    def test_each_viewer_sees_only_their_own_decks(self):
        home, member = self.library("matt"), self.library("user2")
        self.assertIn(GRUUL, home["decks"])
        self.assertNotIn(R_ELVES, home["decks"])
        self.assertEqual(list(member["decks"]), [R_ELVES])
        self.assertNotIn("gruul", json.dumps(member))

    def test_no_catalogue_is_said_per_format(self):
        self.g.built = False
        found = self.library()
        self.assertEqual(found["formats"], {"commander": {"state": "no_catalogue", "size": None},
                                            "constructed": {"state": "no_catalogue", "size": None}})
        self.assertEqual((found["decks"], found["error"]), ({}, None))

    def test_numbers_that_cant_be_worked_out_are_an_error_never_untested(self):
        with mock.patch.object(gauntlet_board, "_built", side_effect=RuntimeError("boom")), \
                mock.patch.object(library_gauntlet.common, "_log") as log:
            found = self.library()
        self.assertEqual(found["formats"]["constructed"], {"state": "error", "size": None})
        self.assertEqual(found["error"], library_gauntlet.NO_NUMBERS)
        self.assertEqual(found["decks"], {})
        log.assert_called_once()

    def test_the_board_and_the_library_build_once_for_one_viewer(self):
        self.g.per = {self.sha(GRUUL): {IDS[0]: 0.4}}
        board = self.board("matt")
        viewed = len(self.g.viewed)
        self.assertTrue(viewed)
        found = self.library("matt")
        self.assertEqual(len(self.g.viewed), viewed)                 # the board's kept answer
        row = next(r for r in board["rows"] if r["deck"]["id"] == GRUUL)
        self.assertEqual((found["decks"][GRUUL]["state"], found["decks"][GRUUL]["overall"]),
                         (row["state"], row["overall"]))


class LibraryGauntletHttpTests(support.ServerTestCase):

    def test_get_only_without_a_query_and_starts_no_games(self):
        answer = {"formats": {}, "decks": {}, "notes": [], "error": None}
        with mock.patch.object(library_gauntlet, "library_gauntlet_view", return_value=answer) as view:
            self.assertEqual(self.get_json("/api/library/gauntlet"), answer)
            view.assert_called_once_with()
            self.assertError("/api/library/gauntlet?x=1", 400)
            code, headers, _ = self.request("POST", "/api/library/gauntlet", b"{}")
            self.assertEqual((code, headers["Allow"]), (405, "GET, HEAD"))
        self.assertFalse(self.box.forge.runs)


if __name__ == "__main__":
    unittest.main()
