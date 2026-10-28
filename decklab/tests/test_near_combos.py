"""The combos a Commander deck is one card away from, on its deck page (E9-S25, lib/api/near_combos.py):
each missing piece's AUD estimate and Considering mark for every reader of the deck, and whether a copy is
free, on the way, in another deck or to buy only for a viewer who sees the space's collection.
lib/stats/commander.py's finding of them is in test_commander_readiness (NearComboTests).

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import copy
import unittest
from collections import Counter
from unittest import mock

from decklab.lib import api, cards, pool
from decklab.lib.api import deck_page, near_combos
from decklab.tests.test_deck_considering import CONSIDERING_DECK
from decklab.tests.test_editor import EditorTestCase


def match(missing, have="Llanowar Elves"):
    return {"names": [have, missing], "missing": missing, "results": ["Infinite mana"], "class": "infinite",
            "standalone": True, "floor": 3, "url": "https://commanderspellbook.com/combo/1-2/",
            "minimum_with": 3, "raises_minimum": True}


STATS = {"commander": {"bracket": {"near_combos": {"checked": True, "total": 2,
                                                   "matches": [match("Black Lotus"), match("Wrath of God")]}}}}


def price(name):
    return cards.Price(name, 2.5, 1.25, 2.0, "2026-10-27", "2026-10-26", "fdn", "1")


class AvailabilityTests(unittest.TestCase):
    def pool(self, owned, on_order=(), held=()):
        return pool.Pool(Counter(owned), {name: [("order x", qty)] for name, qty in on_order}, [
            pool.InUse("casual/other", "Other", "built", Counter(dict(held)))])

    def state(self, p, name="Opt"):
        return near_combos._availability(name, pool.free_copies(p, {"commander/here"}), p)

    def test_each_state(self):
        self.assertEqual(self.state(self.pool({"Opt": 1})), "free")
        self.assertEqual(self.state(self.pool({"Opt": 1}, on_order=[("Opt", 1)])), "on_the_way")
        self.assertEqual(self.state(self.pool({"Opt": 2}, on_order=[("Opt", 1)], held=[("Opt", 1)])), "on_the_way")
        self.assertEqual(self.state(self.pool({"Opt": 2}, held=[("Opt", 2)])), "in_use")
        self.assertEqual(self.state(self.pool({})), "to_buy")


class DeckPageTests(EditorTestCase):
    """deck_view's near combos, in the editor's sandbox (Table Test, with Black Lotus being considered)."""

    def setUp(self):
        super().setUp()
        from decklab.tests.test_api import _write
        _write(self.box.magic / "decks" / "casual" / "table-test.md", CONSIDERING_DECK)
        for patch in (mock.patch.object(deck_page, "_deck_stats", lambda *a: copy.deepcopy(STATS)),
                      mock.patch.object(cards, "price_aud", side_effect=price)):
            patch.start()
            self.addCleanup(patch.stop)

    def near(self):
        return api.deck_view("casual/table-test")["stats"]["commander"]["bracket"]["near_combos"]

    def test_prices_considering_and_availability_for_a_viewer_who_sees_the_collection(self):
        near = self.near()
        self.assertEqual(near["prices"], {"rate": 2.0, "rate_date": "2026-10-27", "price_date": "2026-10-26"})
        lotus, wrath = near["matches"]
        self.assertEqual((lotus["aud"], lotus["considering"], wrath["considering"]), (2.5, True, False))
        p = pool.load_pool()
        free = pool.free_copies(p, pool.self_ids("casual/table-test"))
        self.assertEqual([m["availability"] for m in near["matches"]],
                         [near_combos._availability(name, free, p) for name in ("Black Lotus", "Wrath of God")])
        self.assertTrue(all(m["availability"] in ("free", "on_the_way", "in_use", "to_buy") for m in near["matches"]))

    def test_no_availability_for_a_viewer_who_cant_see_the_collection(self):
        with mock.patch("decklab.lib.api.guard.sees_inventory", return_value=False):
            near = self.near()
        self.assertFalse(any("availability" in m for m in near["matches"]))
        self.assertEqual([m["aud"] for m in near["matches"]], [2.5, 2.5])       # public card data

    def test_no_rate_leaves_the_prices_out_and_the_list_in(self):
        stats = copy.deepcopy(STATS)
        with mock.patch.object(cards, "price_aud", side_effect=RuntimeError("No USD->AUD rate")):
            near_combos.annotate(stats, "casual/table-test", None, False, None)
        near = stats["commander"]["bracket"]["near_combos"]
        self.assertEqual(([m["aud"] for m in near["matches"]], near["prices"]), ([None, None], None))
        self.assertEqual(len(near["matches"]), 2)

    def test_a_deck_without_near_combos_is_left_alone(self):
        for stats in (None, {"commander": None}, {"commander": {"bracket": {}}}):
            with self.subTest(stats=stats):
                before = copy.deepcopy(stats)
                near_combos.annotate(stats, "casual/table-test", None, True, None)
                self.assertEqual(stats, before)


if __name__ == "__main__":
    unittest.main()
