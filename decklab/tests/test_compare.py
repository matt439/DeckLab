"""E1-S13's first slice: GET /api/deck/compare (lib/api/compare.py), two lists' stats side by side.

- CompareTests: both sides carry the deck page's stats and only the summary fields that name a deck (no kit),
  the same deck may be on both sides with its two lists, and a side that's missing or that the viewer may not
  see (guard.sees_deck: another space's, an admin included) answers exactly as a missing deck, whichever side.
- CompareHttpTests: the route's query names, GET and HEAD.

Run from the repo root: python -m unittest decklab.tests.test_compare
"""
import unittest
from unittest import mock

from decklab.lib import api
from decklab.lib.api import compare
from decklab.tests import test_server as server_tests
from decklab.tests.test_deck_privacy_readers import R_DECK_ID, _as, _Hidden

GRUUL = "casual/gruul-test"
ELVES = "commander/elf-commander"
MISSING = "casual/never-was"


class CompareTests(_Hidden):

    def test_two_lists_with_the_deck_page_s_stats(self):
        answer = compare.compare_view(GRUUL, ELVES)
        sides = answer["decks"]
        self.assertEqual([s["summary"]["id"] for s in sides], [GRUUL, ELVES])
        self.assertEqual([s["version"] for s in sides], ["target", "target"])
        page = api.deck_view(GRUUL)
        self.assertEqual(sides[0]["stats"], page["stats"])
        # The sandbox's stand-in stats (test_api's fake_stats), asked with each list and its kind as the deck page asks.
        self.assertEqual([c.args[1] for c in self.box.stats.call_args_list[:2]], ["constructed", "commander"])
        for side in sides:
            self.assertTrue(side["stats"])
            self.assertLessEqual(set(side["summary"]), set(compare.SUMMARY_FIELDS))
            self.assertNotIn("sleeves", side["summary"])
            self.assertNotIn("deck_box", side["summary"])

    def test_one_deck_s_two_lists(self):
        sides = compare.compare_view(GRUUL, GRUUL, "target", "owned")["decks"]
        self.assertEqual([s["version"] for s in sides], ["target", "owned"])
        self.assertEqual(sides[1]["stats"], api.deck_view(GRUUL, "owned")["stats"])

    def test_two_decks_and_known_lists_are_needed(self):
        for args in ((None, GRUUL), (GRUUL, None), ("", "")):
            with self.subTest(args=args):
                self.assertApiError(400, compare.compare_view, *args, contains="two decks")
        self.assertApiError(400, compare.compare_view, GRUUL, ELVES, "target", "neither")
        self.assertApiError(404, compare.compare_view, GRUUL, ELVES, "target", "owned")    # it has no Play-now list

    def test_a_hidden_deck_on_either_side_is_a_missing_one(self):
        cases = (("user2", GRUUL, R_DECK_ID), ("user1", R_DECK_ID, GRUUL), ("matt", R_DECK_ID, ELVES))
        for who, hidden, seen in cases:
            for side in (0, 1):
                pair = (hidden, seen) if side == 0 else (seen, hidden)
                gone = (MISSING, seen) if side == 0 else (seen, MISSING)
                with self.subTest(who=who, hidden=hidden, side=side):
                    got = self.error(who, compare.compare_view, *pair)
                    self.assertEqual(got, (404, "No deck '<id>'", {}))
                    if who == "user2":      # the only deck user2 sees is their own, on the other side
                        continue
                    self.assertEqual(got, self.error(who, compare.compare_view, *gone))
        with _as("user2"):
            sides = compare.compare_view(R_DECK_ID, R_DECK_ID)["decks"]
        self.assertEqual([s["summary"]["id"] for s in sides], [R_DECK_ID, R_DECK_ID])

    def test_a_pairing_typed_into_the_address_bar(self):
        sides = compare.compare_view("pairing/cats elves", GRUUL)["decks"]
        self.assertTrue(sides[0]["summary"]["id"].startswith("pairing/"))


class CompareHttpTests(server_tests.ServerTestCase):

    def test_get_and_head_with_only_its_query_names(self):
        with mock.patch.object(compare, "compare_view", return_value={"decks": []}) as view:
            path = "/api/deck/compare?a=casual%2Fgruul-test&b=casual%2Fgruul-test&av=target&bv=owned"
            self.assertEqual(self.get_json(path), {"decks": []})
            view.assert_called_once_with(a=GRUUL, b=GRUUL, av="target", bv="owned")
            code, _, body = self.request("HEAD", path)
            self.assertEqual((code, body), (200, b""))
            self.assertError("/api/deck/compare?a=x&id=y", 400)
            self.assertError("/api/deck/compare?a=x", 405, method="POST", body=b"{}",
                             headers=dict(server_tests.WRITE, Origin=f"http://127.0.0.1:{self.port}"))


if __name__ == "__main__":
    unittest.main()
