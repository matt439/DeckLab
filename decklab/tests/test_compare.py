"""GET /api/compare/shared (E1-S13, lib/api/compare.py): the cards both compared lists use, with how many
copies the pool can cover for both, only for a viewer who may see the space's collection.

Runs in test_api's sandbox: Gruul Test and Elf Commander (neither built) both use Llanowar Elves and Sol Ring;
the collection has 5 Llanowar Elves (the intact Beginner Box holds 2) and a Sol Ring, with another on the way
in the preordered precon. Nothing is written.

PrivacyTests runs as real profiles (test_deck_privacy_readers' sandbox, with user2's own deck), and
SharedHttpTests checks the route's query names.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_compare
"""
import json
import unittest
from unittest import mock

from decklab.lib.api import compare
from decklab.tests.test_api import ApiTestCase, _write
from decklab.tests.test_deck_privacy_readers import R_DECK_ID, _as, _Hidden

GRUUL = "casual/gruul-test"
ELVES = "commander/elf-commander"
MISSING = "casual/never-was"

BUILT = """# Elf Box

- **Format:** Casual 60-card, 1v1
- **Played by:** either
- **Status:** built

## Decklist

```
Deck
1 Llanowar Elves (FDN) 227
20 Forest
```
"""


def rows(answer):
    return {row["name"]: row for row in answer["cards"]}


class SharedTests(ApiTestCase):

    def shared(self, a="casual/gruul-test", b="commander/elf-commander", av=None, bv=None):
        return compare.shared_view(a, av, b, bv)

    def test_the_cards_both_use_with_the_pools_cover_for_both(self):
        answer = self.shared()
        self.assertEqual((answer["a"], answer["b"]), ({"id": "casual/gruul-test", "version": "target"},
                                                       {"id": "commander/elf-commander", "version": "target"}))
        self.assertEqual((answer["together"], answer["counts"], answer["why_no_counts"]), (True, True, None))
        # Only the cards in both (Forest, Elvish Mystic and the rest are in one list only), the shortest first.
        self.assertEqual(answer["cards"], [
            {"name": "Llanowar Elves", "a": 6, "b": 1, "need": 7, "owned": 5, "on_the_way": 0, "free": 3, "short": 4},
            {"name": "Sol Ring", "a": 1, "b": 1, "need": 2, "owned": 1, "on_the_way": 1, "free": 1, "short": 1}])
        json.dumps(answer, allow_nan=False)

    def test_other_built_decks_hold_copies_but_the_two_compared_dont(self):
        _write(self.box.magic / "decks" / "casual" / "elf-box.md", BUILT)
        self.assertEqual(rows(self.shared())["Llanowar Elves"]["free"], 2)       # Elf Box holds one
        # Compared with Elf Box itself, its own copy counts free for the two.
        answer = self.shared(b="casual/elf-box")
        self.assertEqual({k: rows(answer)["Llanowar Elves"][k] for k in ("a", "b", "need", "free", "short")},
                         {"a": 6, "b": 1, "need": 7, "free": 3, "short": 4})
        self.assertNotIn("Forest", rows(answer))                                  # basic lands aren't counted

    def test_one_decks_two_lists_need_the_larger_count(self):
        answer = self.shared(b="casual/gruul-test", bv="owned")
        self.assertFalse(answer["together"])
        self.assertEqual(answer["b"], {"id": "casual/gruul-test", "version": "owned"})
        self.assertEqual({k: rows(answer)["Llanowar Elves"][k] for k in ("a", "b", "need", "short")},
                         {"a": 6, "b": 4, "need": 6, "short": 3})

    def test_a_viewer_who_cant_see_the_collection_gets_names_only(self):
        with mock.patch("decklab.lib.api.guard.sees_inventory", return_value=False), \
                mock.patch("decklab.lib.pool.load_pool", side_effect=AssertionError("the pool isn't read")):
            answer = self.shared()
        self.assertEqual((answer["counts"], answer["why_no_counts"], answer["warnings"]), (False, None, []))
        self.assertEqual(answer["cards"], [{"name": "Llanowar Elves", "a": 6, "b": 1, "need": 7},
                                           {"name": "Sol Ring", "a": 1, "b": 1, "need": 2}])

    def test_decks_in_separate_collections_get_no_counts(self):
        real = compare.spaces.space_of
        with mock.patch.object(compare.spaces, "space_of",
                               side_effect=lambda deck_id: "user2" if deck_id.startswith("commander/") else real(deck_id)):
            answer = self.shared()
        self.assertFalse(answer["counts"])
        self.assertIn("separate collections", answer["why_no_counts"])
        self.assertFalse(any("free" in row for row in answer["cards"]))

    def test_a_deck_the_viewer_cant_see_answers_as_missing(self):
        hidden = lambda target, profile=False: "elf-commander" not in str(target.get("id") if isinstance(target, dict) else target)
        with mock.patch("decklab.lib.api.guard.sees_deck", side_effect=hidden):
            refused = self.assertApiError(404, self.shared)
        self.assertEqual(refused.message, "No deck 'commander/elf-commander'")
        with mock.patch("decklab.lib.api.guard.sees_deck", side_effect=hidden):
            self.assertApiError(404, self.shared, "commander/elf-commander", "casual/gruul-test")

    def test_bad_requests(self):
        self.assertApiError(400, self.shared, "casual/gruul-test", "commander/elf-commander", "planned")
        self.assertApiError(400, self.shared, "", "commander/elf-commander")
        self.assertApiError(404, self.shared, "casual/nope")
        self.assertApiError(404, self.shared, "casual/gruul-test", "commander/elf-commander", None, "owned")  # no Play-now list


class PrivacyTests(_Hidden):

    def shared(self, a, b):
        return compare.shared_view(a, None, b, None)

    def test_a_hidden_deck_on_either_side_is_a_missing_one(self):
        # Another space's deck, an admin included, answers exactly as a deck that doesn't exist, whichever side.
        cases = (("user2", GRUUL, R_DECK_ID), ("user1", R_DECK_ID, GRUUL), ("matt", R_DECK_ID, ELVES))
        for who, hidden, seen in cases:
            for side in (0, 1):
                pair = (hidden, seen) if side == 0 else (seen, hidden)
                gone = (MISSING, seen) if side == 0 else (seen, MISSING)
                with self.subTest(who=who, hidden=hidden, side=side):
                    got = self.error(who, self.shared, *pair)
                    self.assertEqual(got, (404, "No deck '<id>'", {}))
                    if who == "user2":      # the only deck user2 sees is their own, on the other side
                        continue
                    self.assertEqual(got, self.error(who, self.shared, *gone))
        with _as("user2"):
            answer = self.shared(R_DECK_ID, R_DECK_ID)
        self.assertEqual((answer["a"]["id"], answer["b"]["id"], answer["together"]), (R_DECK_ID, R_DECK_ID, False))

    def test_a_pairing_typed_into_the_address_bar(self):
        # A "+" in a pairing's id typed into the address bar arrives as a space.
        answer = self.shared("pairing/cats elves", GRUUL)
        self.assertTrue(answer["a"]["id"].startswith("pairing/"))
        self.assertNotIn(" ", answer["a"]["id"])


if __name__ == "__main__":
    unittest.main()
