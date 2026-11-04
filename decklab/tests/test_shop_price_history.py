"""E5-S29: a queued card's price history on Shopping (lib/api/shop_history.py, GET /api/shopping/price-history).

Only Shopping's readers may ask; only a name on the purchase queue has history; each shop's days come
oldest first with the lowest in-stock day marked; nothing reaches the network."""
import unittest
from unittest import mock

from decklab.lib import shops
from decklab.lib.api import guard, shop_history
from decklab.lib.api.common import ApiError


def reading(on, price, stock=1):
    return {"on": on, "at": f"{on}T03:00:00+10:00",
            "listings": [{"set": "40k", "number": "249", "finish": "nonfoil", "condition": "Regular",
                          "price": price, "stock": stock}]}


HISTORY = {
    "mtgmate": {"Sol Ring": [reading("2026-11-01", "4.00"), reading("2026-11-02", "3.50"),
                             reading("2026-11-03", "3.00", stock=0)]},
    "gamesportal": {},
}


class PriceHistoryTests(unittest.TestCase):
    def setUp(self):
        for target, name, value in (
                (guard, "require_sees_home_records", lambda: None),
                (shops, "_queue", lambda: [{"name": "Sol Ring"}, {"name": "Sol Ring"}, {"name": "Opt"}]),
                (shops, "load_history", lambda adapter=None, path=None: HISTORY[adapter.key]),
                (shops, "enabled_adapters", lambda settings=None: shops.SNAPSHOT_ADAPTERS)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_each_shops_days_oldest_first_with_the_lowest_in_stock_marked(self):
        answer = shop_history.price_history_view("sol ring")
        self.assertTrue(answer["queued"])
        self.assertEqual(answer["name"], "Sol Ring")
        mate, portal = answer["shops"]
        self.assertEqual((mate["shop"], portal["shop"]), ("MTGMate", "Games Portal"))
        self.assertEqual([(d["on"], d["price"], d["in_stock"], d["lowest"]) for d in mate["days"]],
                         [("2026-11-01", "4.00", True, False), ("2026-11-02", "3.50", True, True),
                          ("2026-11-03", "3.00", False, False)])
        self.assertEqual(portal["days"], [])

    def test_only_the_shops_config_checks(self):
        with mock.patch.object(shops, "enabled_adapters", lambda settings=None: shops.SNAPSHOT_ADAPTERS[:1]):
            self.assertEqual([s["shop"] for s in shop_history.price_history_view("Sol Ring")["shops"]], ["MTGMate"])
        with mock.patch.object(shops, "enabled_adapters", lambda settings=None: ()):
            self.assertEqual(shop_history.price_history_view("Sol Ring")["shops"], [])

    def test_a_name_not_queued_has_no_history(self):
        self.assertEqual(shop_history.price_history_view("Black Lotus"),
                         {"name": "Black Lotus", "queued": False, "shops": []})

    def test_a_bad_name_is_refused(self):
        for bad in (None, "", " ", "x" * 201, "Sol\nRing"):
            with self.subTest(bad=bad), self.assertRaises(ApiError) as caught:
                shop_history.price_history_view(bad)
            self.assertEqual(caught.exception.status, 400)

    def test_only_shoppings_readers_may_ask(self):
        refused = ApiError(403, "That isn't yours to see.")
        with mock.patch.object(guard, "require_sees_home_records", side_effect=refused), \
                mock.patch.object(shops, "_queue", side_effect=AssertionError("read before the check")):
            with self.assertRaises(ApiError) as caught:
                shop_history.price_history_view("Sol Ring")
        self.assertEqual(caught.exception.status, 403)


if __name__ == "__main__":
    unittest.main()
