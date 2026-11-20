"""Read-only alternative deck builds against synthetic home holdings and saved retail evidence."""
import unittest
from unittest import mock

from decklab.lib import access, inventory, pool, shops
from decklab.lib.api import shopping_compare as compare
from decklab.lib.api.common import ApiError
from decklab.tests.test_shop_baskets import entry, games_portal, listing, mtgmate
from decklab.tests.test_shopping_missing import RIDER, _Fixture


class CompareTests(_Fixture, unittest.TestCase):
    left = "casual/alpha,casual/beta"
    right = "casual/alpha,casual/holding"

    def test_same_pool_and_stock_for_both_choices_without_queue_or_order_writes(self):
        snapshot = mtgmate({name: entry(listing("1.25", 8)) for name in ["Llanowar Elves", "Elvish Mystic", RIDER]})
        with mock.patch.object(compare.shop_prices, "capture", return_value=snapshot) as capture, \
                mock.patch.object(compare.shop_postage, "rules", return_value={"mtgmate": {"postage_aud": "3"}}) as rules, \
                mock.patch.object(pool, "load_pool", wraps=pool.load_pool) as supply, \
                mock.patch.object(inventory, "apply", side_effect=AssertionError("read only")):
            result = compare.compare_view(self.left, self.right)
        supply.assert_called_once()
        capture.assert_called_once()
        rules.assert_called_once()
        for side, buy, delivered in [("left", 12, "18.00"), ("right", 7, "11.75")]:
            answer = result[side]
            self.assertTrue(answer["ready"])
            self.assertEqual((answer["today_missing"], answer["incoming"], answer["buy"]), (buy + 2, 2, buy))
            self.assertEqual(answer["here_now"] + answer["today_missing"], answer["required"])
            pricing = answer["pricing"]
            self.assertEqual((pricing["wanted"], pricing["covered"], pricing["delivered_aud"]), (buy, buy, delivered))

    def test_missing_stock_retains_unchecked_names_and_incomplete_total(self):
        snapshot = mtgmate({"Llanowar Elves": entry(listing("1.25", 2))})
        with mock.patch.object(compare.shop_prices, "capture", return_value=snapshot), \
                mock.patch.object(compare.shop_postage, "rules", return_value=None):
            result = compare.compare_view(self.left, self.right)
        pricing = result["left"]["pricing"]
        self.assertEqual((pricing["covered"], pricing["wanted"], pricing["delivered_aud"]), (2, 12, None))
        self.assertEqual(pricing["known_aud"], "2.50")
        self.assertEqual(pricing["postage_unknown"], ["MTGMate"])
        unknown = next(row for row in pricing["uncovered"] if row["name"] == RIDER)
        self.assertEqual(unknown["shops"][0]["status"], "not_checked")

    def test_delivery_finishes_card_and_basket_contains_only_remainder(self):
        self.case.deck("incoming", "Incoming", "idea", "Deck\n2 Elvish Mystic\n")
        with mock.patch.object(compare.shop_prices, "capture", return_value=None):
            answer = compare.compare_view("casual/incoming,casual/holding", self.right)["left"]
        mystic = next(row for row in answer["cards"] if row["name"] == "Elvish Mystic")
        self.assertEqual((mystic["today_missing"], mystic["incoming"], mystic["buy"]), (1, 1, 0))
        self.assertEqual(mystic["on_the_way"], [{"source": "order incoming", "copies": 1}])
        self.assertEqual(answer["pricing"]["wanted"], 0)
        self.assertEqual(answer["pricing"]["delivered_aud"], "0.00")

    def test_zero_demand_and_unpriced_allocations(self):
        self.assertEqual(compare._price([], None, None, [])["delivered_aud"], "0.00")
        snapshot = mtgmate({"Card": entry(listing(None, 2))})
        pricing = compare._price([{"name": "Card", "buy": 2}], snapshot,
                                 {"mtgmate": {"postage_aud": "0"}}, [shops.ADAPTER])
        self.assertEqual((pricing["covered"], pricing["unpriced_copies"], pricing["delivered_aud"]), (2, 2, None))

    def test_bounded_search_and_unconfirmed_quantity_are_distinct_from_no_snapshot(self):
        demand = [{"name": "Card", "buy": 2}]
        no_check = compare._price(demand, None, None, [shops.ADAPTER])
        self.assertFalse(no_check["search_ran"])
        self.assertEqual(no_check["uncovered"][0]["shops"][0]["status"], "unread")
        from decklab.lib.api import shop_plan
        adapter = shops.ADAPTERS["gamesportal"]
        snapshot = {"gamesportal": games_portal({"Card": entry(listing("2", 1), partial=True, carried=True)})}
        with mock.patch.object(shop_plan, "MAX_SHOPS", 0):
            price = compare._price(demand, snapshot, {"gamesportal": {"postage_aud": "1"}}, [adapter])
        self.assertTrue(price["search_ran"])
        self.assertFalse(price["search_complete"])
        self.assertIsNone(price["delivered_aud"])
        self.assertEqual(price["stock_unknown"], [adapter.name])
        self.assertEqual((price["partial_shops"], price["carried_shops"]), ([adapter.name], [adapter.name]))

    def test_foil_fallback_shows_each_selected_printing_quantity_and_unit_price(self):
        snapshot = mtgmate({"Card": entry(listing("1.50", 1, finish="foil"),
                                          listing("2.00", 3, finish="foil", set_code="abc", number="11"))})
        pricing = compare._price([{"name": "Card", "buy": 3}], snapshot,
                                 {"mtgmate": {"postage_aud": "0"}}, [shops.ADAPTER])
        row = pricing["shops"][0]["rows"][0]
        self.assertCountEqual(row["printings"], [
            {"set": "fdn", "collector_number": "227", "finish": "foil", "copies": 1, "price_aud": "1.50"},
            {"set": "abc", "collector_number": "11", "finish": "foil", "copies": 2, "price_aud": "2.00"}])
        self.assertEqual(pricing["delivered_aud"], "5.50")

    def test_malformed_or_unavailable_saved_checks_leave_both_inventory_results_intact(self):
        malformed = mtgmate({"Llanowar Elves": entry(listing(stock="bad"))})
        for capture in ({"return_value": malformed}, {"return_value": None}, {"side_effect": OSError("unread")}):
            with self.subTest(capture=capture), mock.patch.object(compare.shop_prices, "capture", **capture), \
                    mock.patch.object(compare.shop_postage, "rules", return_value={}):
                result = compare.compare_view(self.left, self.right)
            for side, missing in [("left", 12), ("right", 7)]:
                self.assertEqual((result[side]["buy"], result[side]["today_missing"]), (missing, missing + 2))
                self.assertIsNone(result[side]["pricing"]["delivered_aud"])
                self.assertEqual(result[side]["pricing"]["covered"], 0)

    def test_availability_only_tiers_each_guarantee_one_and_counted_shop_can_fill_remainder(self):
        snapshot = {"gamesportal": games_portal({"Card": entry(listing("1", 1), listing("2", 1, number="228"))}),
                    "mtgmate": mtgmate({"Card": entry(listing("4", 3))})}
        adapters = [shops.ADAPTERS[key] for key in snapshot]
        rules = {key: {"postage_aud": "0"} for key in snapshot}
        for wanted, total in ((1, "1.00"), (2, "3.00"), (3, "7.00")):
            quote = compare._price([{"name": "Card", "buy": wanted}], snapshot, rules, adapters)
            self.assertEqual((quote["covered"], quote["delivered_aud"]), (wanted, total))
            self.assertEqual(quote["availability_only"], ["Games Portal"])
            self.assertEqual(quote["stock_unknown"], [])
        quote = compare._price([{"name": "Card", "buy": 3}], snapshot, rules, adapters[:1])
        self.assertEqual((quote["covered"], quote["delivered_aud"]), (2, None))
        self.assertEqual(quote["stock_unknown"], ["Games Portal"])

    def test_member_refused_before_data_reads_and_hidden_deck_looks_missing(self):
        with access.using({"profile": "user2", "remote": True}), \
                mock.patch.object(inventory, "pinned", side_effect=AssertionError("guard first")), \
                self.assertRaises(ApiError) as caught:
            compare.compare_view(self.left, self.right)
        self.assertEqual(caught.exception.status, 403)
        with self.assertRaises(ApiError) as caught:
            compare.compare_view(self.left, "casual/alpha,user2/casual/private")
        self.assertEqual(caught.exception.status, 404)
