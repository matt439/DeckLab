"""A buy-under value is a nullable market unit threshold, never spending or a paid price."""
from decimal import Decimal
import unittest

from decklab.lib.inventory import watchlist_targets as targets


class WatchlistTargetRulesTests(unittest.TestCase):
    def test_unset_and_exact_aud_cents_are_canonical_without_rounding(self):
        for value in (None, "", "   "):
            self.assertIsNone(targets.normalize(value))
        for value, expected in (("0", "0.00"), (0, "0.00"), ("00.50", "0.50"), ("3.5", "3.50"),
                                (Decimal("4.20"), "4.20"), ("999999999.99", "999999999.99")):
            self.assertEqual(targets.normalize(value), expected)
        for value in (True, False, -1, "1.005", "1e2", float("nan"), "Infinity", "1000000000", {}, "A$5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                targets.normalize(value)

    def test_only_usable_in_stock_noncarried_observations_can_hit_a_target(self):
        quote = {"status": "in_stock", "stock": 1, "carried": False, "price_aud": "3.00"}
        self.assertTrue(targets.reached("3.00", quote))
        self.assertFalse(targets.reached("2.99", quote))
        self.assertIsNone(targets.reached(None, quote))
        for change in ({"status": "out_of_stock"}, {"stock": True}, {"carried": True}, {"price_aud": "NaN"}):
            self.assertIsNone(targets.reached("3.00", {**quote, **change}))
