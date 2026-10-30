"""The combos a Commander deck is one card away from, on its deck page (E9-S25, lib/api/near_combos.py):
each missing piece's AUD estimate and Considering mark for every reader of the deck, and whether a copy is
free, on the way, in another deck or to buy only for a viewer who sees the space's collection.
lib/stats/commander.py's finding of them is in test_commander_readiness (NearComboTests). A failure is a
warning, never a broken deck page; python -m decklab.lib.combos near lists them on the PC.

Run from the repo root: python scripts/test_fixtures.py
"""
import copy
import io
import unittest
from collections import Counter
from contextlib import redirect_stdout
from unittest import mock

from decklab.lib import api, cards, combos, decks, pool, stats
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

    def test_the_decks_own_copies_are_free_for_it(self):
        p = self.pool({"Opt": 1}, held=[("Opt", 1)])
        self.assertEqual(near_combos._availability("Opt", pool.free_copies(p, {"casual/other"}), p), "free")


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

    def test_a_failure_is_a_warning_never_a_broken_page(self):
        with mock.patch.object(near_combos, "annotate", side_effect=RuntimeError("boom")):
            answer = api.deck_view("casual/table-test")
        self.assertNotIn("near_combos", answer["stats"]["commander"]["bracket"])
        self.assertIn("The combos one card away couldn't be worked out (the server log says why)", answer["warnings"])
        self.assertIn("sections", answer)

    def test_a_deck_without_near_combos_is_left_alone(self):
        for stats in (None, {"commander": None}, {"commander": {"bracket": {}}}):
            with self.subTest(stats=stats):
                before = copy.deepcopy(stats)
                near_combos.annotate(stats, "casual/table-test", None, True, None)
                self.assertEqual(stats, before)


class CommandLineTests(unittest.TestCase):
    """python -m decklab.lib.combos near: the deck page's list, free first, with availability (the command
    line reads every space)."""

    def setUp(self):
        summary = {"id": "commander/finneas", "kind": "commander", "target_bracket": 2}
        held = pool.InUse("commander/other", "Other", "built", Counter({"Wrath of God": 1}))
        p = pool.Pool(Counter({"Wrath of God": 2}), {}, [held])
        for patch in (mock.patch.object(decks, "find_summary", return_value=summary),
                      mock.patch.object(decks, "load_deck", return_value={}),
                      mock.patch.object(stats, "deck_stats", side_effect=lambda *a: copy.deepcopy(STATS)),
                      mock.patch.object(pool, "load_pool", return_value=p),
                      mock.patch.object(pool, "self_ids", return_value={"commander/finneas"}),
                      mock.patch.object(cards, "price_aud", side_effect=price)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_free_first_with_availability_price_and_bracket(self):
        summary, near = combos.near_for_deck("commander/finneas")
        self.assertEqual([(m["missing"], m["availability"]) for m in near["matches"]],
                         [("Wrath of God", "free"), ("Black Lotus", "to_buy")])
        out = io.StringIO()
        with redirect_stdout(out):
            combos._print_near(summary["id"], near, summary["target_bracket"])
        text = out.getvalue()
        self.assertIn("commander/finneas: 2 two-card combos one card away", text)
        self.assertIn("[free] add Wrath of God ~A$2.50 (with Llanowar Elves): Infinite mana; raises the minimum "
                      "bracket to 3, above the target 2", text)
        self.assertIn("[to buy] add Black Lotus", text)
        self.assertIn("https://commanderspellbook.com/combo/1-2/", text)
        self.assertIn("1 USD = 2.0 AUD (2026-10-27)", text)

    def test_a_deck_that_isnt_commander_is_refused(self):
        decks.find_summary.return_value = {"id": "casual/elves", "kind": "casual"}
        with self.assertRaisesRegex(ValueError, "isn't a Commander deck"):
            combos.near_for_deck("casual/elves")

    def test_a_list_that_cant_be_read_says_why(self):
        stats.deck_stats.side_effect = lambda *a: {"commander": {"bracket": {
            "combos": {"checked": False, "reason": "The combo list isn't downloaded yet"}}}}
        _, near = combos.near_for_deck("commander/finneas")
        self.assertEqual(near, {"checked": False, "reason": "The combo list isn't downloaded yet"})
        out = io.StringIO()
        with redirect_stdout(out):
            combos._print_near("commander/finneas", near, 2)
        self.assertIn("weren't checked: The combo list isn't downloaded yet", out.getvalue())


if __name__ == "__main__":
    unittest.main()
