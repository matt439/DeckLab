"""The listed printing's price beside the cheapest one (E5-S31): cards.printing_usd / price_aud_printing,
lib/listed_prices.py's threshold, and the fields pool.compare adds to the live owned-vs-needed rows.

Names and prices come from the fixture card index (fixtures/default_cards.jsonl): Llanowar Elves'
cheapest non-foil paper printing is M19 314 at US$0.20, and FDN 227 is US$0.25 non-foil, US$1.77 foil.
The rate is test_pool's RATE (1 USD = 2 AUD), so the expected A$ are exact.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_listed_prices
"""
import unittest
from unittest import mock

from decklab.lib import cards, decks, listed_prices, pool
from decklab.tests import test_pool
from decklab.tests.test_pool import PoolTestCase

LISTED_KEYS = {"listed_printing", "listed_finish", "listed_aud_each", "listed_aud_missing", "listed_material"}


def setUpModule():
    test_pool.setUpModule()


def tearDownModule():
    test_pool.tearDownModule()


class PrintingPriceTests(unittest.TestCase):
    def test_the_exact_printing_and_finish(self):
        self.assertEqual(cards.printing_usd("fdn", "227", "foil"), 1.77)
        self.assertEqual(cards.printing_usd("FDN", 227, "nonfoil"), 0.25)
        self.assertEqual(cards.printing_usd("fdn", "227", ""), 0.25)        # blank: non-foil
        self.assertIsNone(cards.printing_usd("fdn", "227", "etched"))       # no price in that finish
        self.assertIsNone(cards.printing_usd("fdn", "227", "shiny"))        # not a finish
        self.assertIsNone(cards.printing_usd("fdn", "99999"))               # unknown printing
        self.assertIsNone(cards.printing_usd("", "227"))
        self.assertIsNone(cards.printing_usd("fdn", None))

    def test_price_aud_printing(self):
        with mock.patch.object(cards, "usd_to_aud", return_value=(2.0, "2026-09-28")) as rate:
            price = cards.price_aud_printing("FDN", "227", "foil")
            rate.assert_called_once()
            given = cards.price_aud_printing("fdn", "227", "foil", rate=(3.0, "2026-09-27"))
            self.assertEqual(rate.call_count, 1)                # a rate given isn't fetched again
            self.assertIsNone(cards.price_aud_printing("fdn", "227", "etched"))
        self.assertEqual((price.name, price.aud, price.usd, price.set, price.collector_number, price.finish),
                         ("Llanowar Elves", 3.54, 1.77, "fdn", "227", "foil"))
        self.assertEqual((given.aud, given.rate, given.rate_date), (5.31, 3.0, "2026-09-27"))


class ThresholdTests(unittest.TestCase):
    def test_material_needs_both_five_dollars_and_half_as_much_again(self):
        self.assertTrue(listed_prices.material(1.0, 6.0))       # +A$5, 6x
        self.assertFalse(listed_prices.material(1.0, 5.99))     # 6x but under A$5 more
        self.assertFalse(listed_prices.material(20.0, 29.0))    # A$9 more but only 45% more
        self.assertTrue(listed_prices.material(20.0, 30.0))     # A$10 and 50% more
        self.assertFalse(listed_prices.material(10.0, None))    # the listing has no price
        self.assertTrue(listed_prices.material(None, 5.0))      # no cheapest price, the listing A$5
        self.assertFalse(listed_prices.material(None, 4.99))


class CompareTests(PoolTestCase):
    def rows(self, decklist, *owned):
        self.cards_csv("collection.csv", *owned)
        self.deck("a", "A", "idea", decklist)
        return self.check("casual/a", prices=True)

    def test_a_dear_listed_printing_is_priced_beside_the_cheapest(self):
        result, rows = self.rows("Deck\n3 Llanowar Elves (FDN) 227 *F*\n1 Sol Ring\n",
                                 ("Llanowar Elves", "m19", "314", "nonfoil", 1))
        row = rows["Llanowar Elves"]
        # The cheapest stays the figure: two missing at M19's A$0.40.
        self.assertEqual((row["missing"], row["aud_each"], row["aud_missing"], row["priced_printing"]),
                         (2, 0.4, 0.8, "M19 314"))
        # The owned copy isn't counted: only the two missing ones, at FDN 227 foil's A$3.54.
        self.assertEqual({k: row[k] for k in LISTED_KEYS},
                         {"listed_printing": "FDN 227 foil", "listed_finish": "foil", "listed_aud_each": 3.54,
                          "listed_aud_missing": 7.08, "listed_material": True})
        self.assertNotIn("listed_printing", rows["Sol Ring"])      # its line names no printing
        totals = result["totals"]
        self.assertEqual(totals["as_listed"], [{"name": "Llanowar Elves", "printing": "FDN 227 foil",
                                                "finish": "foil", "missing": 2, "aud_each": 3.54,
                                                "aud_missing": 7.08}])
        self.assertEqual(totals["aud_missing_as_listed"], round(totals["aud_missing"] - 0.8 + 7.08, 2))

    def test_a_small_difference_is_on_the_row_but_not_in_the_totals(self):
        # One missing foil: A$3.54 against A$0.40 is under A$5 more.
        result, rows = self.rows("Deck\n2 Llanowar Elves (FDN) 227 *F*\n",
                                 ("Llanowar Elves", "m19", "314", "nonfoil", 1))
        row = rows["Llanowar Elves"]
        self.assertEqual((row["missing"], row["listed_aud_each"], row["listed_material"]), (1, 3.54, False))
        self.assertNotIn("as_listed", result["totals"])
        self.assertNotIn("aud_missing_as_listed", result["totals"])

    def test_owned_copies_leave_nothing_to_price(self):
        result, rows = self.rows("Deck\n2 Llanowar Elves (FDN) 227 *F*\n",
                                 ("Llanowar Elves", "m19", "314", "nonfoil", 2))
        self.assertEqual(rows["Llanowar Elves"]["missing"], 0)
        self.assertFalse(LISTED_KEYS & set(rows["Llanowar Elves"]))
        self.assertNotIn("as_listed", result["totals"])

    def test_no_listed_printing_the_same_printing_or_several_printings(self):
        for decklist in ("Deck\n4 Llanowar Elves\n",
                         "Deck\n4 Llanowar Elves (M19) 314\n",
                         "Deck\n2 Llanowar Elves (FDN) 227 *F*\n2 Llanowar Elves (M19) 314\n",
                         "Deck\n2 Llanowar Elves (FDN) 227 *F*\n2 Llanowar Elves\n"):
            with self.subTest(decklist):
                result, rows = self.rows(decklist)
                self.assertEqual(rows["Llanowar Elves"]["missing"], 4)
                self.assertFalse(LISTED_KEYS & set(rows["Llanowar Elves"]))
                self.assertNotIn("as_listed", result["totals"])

    def test_a_printing_of_another_card_is_ignored(self):
        # FDN 227 is Llanowar Elves, so a Sol Ring line naming it keeps only the cheapest price.
        _, rows = self.rows("Deck\n1 Sol Ring (FDN) 227 *F*\n")
        self.assertFalse(LISTED_KEYS & set(rows["Sol Ring"]))

    def test_without_prices_nothing_is_added(self):
        self.cards_csv("collection.csv")
        self.deck("a", "A", "idea", "Deck\n3 Llanowar Elves (FDN) 227 *F*\n")
        result, rows = self.check("casual/a", prices=False)
        self.assertFalse(LISTED_KEYS & set(rows["Llanowar Elves"]))
        self.assertNotIn("as_listed", result["totals"])

    def test_only_a_planned_list_compare_prices_the_listed_printings(self):
        # The Play-now list, swaps and the saved table compare without listed=True: cheapest only.
        self.rows("Deck\n3 Llanowar Elves (FDN) 227 *F*\n")
        sections = decks.load_deck("casual/a", "target")
        plain = pool.compare(sections, pool.load_pool(), pool.self_ids("casual/a"))
        row = {r["name"]: r for r in plain["rows"]}["Llanowar Elves"]
        self.assertEqual(row["aud_missing"], 1.2)
        self.assertFalse(LISTED_KEYS & set(row))
        self.assertNotIn("as_listed", plain["totals"])
        listed = pool.compare(sections, pool.load_pool(), pool.self_ids("casual/a"), listed=True)
        self.assertTrue(LISTED_KEYS <= set(listed["rows"][0]))

    def test_the_saved_table_still_prices_the_cheapest_printing(self):
        result, _ = self.rows("Deck\n3 Llanowar Elves (FDN) 227 *F*\n")
        rows_out, total, _ = pool.table_rows(result)
        self.assertEqual(decks.format_table_row(rows_out[0]),
                         "| Llanowar Elves | 3 | 0 | **3** | ~$0.40 | ~$1.20 |  |")
        self.assertEqual((total.missing, total.aud_missing), (3, "~$1.20"))


if __name__ == "__main__":
    unittest.main()
