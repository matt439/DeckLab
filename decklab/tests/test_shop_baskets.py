"""Shopping's Baskets from the saved shop snapshots (E5-S27, first slice).

Run: python scripts/test_fixtures.py decklab.tests.test_shop_baskets
Every snapshot is supplied here; no shop, real snapshot file or configured database is read.
"""
import copy
import unittest
from unittest import mock

from decklab.lib import access, inventory, shops
from decklab.lib.api import common, shop_baskets, shopping
from decklab.lib.shops import gamesportal
from decklab.tests import test_shopping_missing as fixtures

AT = "2026-11-01T02:00:00+11:00"
GP_AT = "2026-11-01T02:30:00+11:00"


def listing(price="1.25", stock=2, finish="nonfoil", set_code="fdn", number="227"):
    return {"price": price, "stock": stock, "finish": finish, "set": set_code, "number": number,
            "condition": "Regular", "url": f"{shops.SITE}/cards/X/{set_code.upper()}/{number}"}


def entry(*items, status="ok", at=AT, **extra):
    return {"status": status, "at": at, "listings": list(items), **extra}


def mtgmate(cards):
    return {"version": 1, "shop": "MTGMate", "site": shops.SITE, "fetched_at": AT, "started_at": AT, "cards": cards}


def games_portal(cards):
    return {"version": 1, "shop": gamesportal.SHOP, "site": gamesportal.SITE, "fetched_at": GP_AT,
            "started_at": GP_AT, "cards": cards}


def row(name, number, **extra):
    return {"queue_row": number, "name": name, "quantity": "1", "state": "ready", "for": "Otters", "printing": "any",
            "set": "", "collector_number": "", "finish": "", **extra}


def by_name(lines):
    return {line["name"]: line for line in lines}


class BasketTests(unittest.TestCase):
    def build(self, rows, mtg=None, gp=None):
        captured = {key: value for key, value in (("mtgmate", mtg), ("gamesportal", gp)) if value}
        return shop_baskets.build(rows, captured or None, "rev-1")

    def basket(self, built, key):
        return next(item for item in built["shops"] if item["key"] == key)

    def test_no_snapshot_at_all_gives_no_baskets_and_the_answer_is_unchanged(self):
        self.assertIsNone(self.build([row("Sol Ring", 1)]))
        answer = {"to_buy": [row("Sol Ring", 1)], "queue_revision": "rev-1"}
        before = copy.deepcopy(answer)
        self.assertEqual(shop_baskets.enrich(answer, data=None), before)

    def test_ready_rows_in_stock_with_price_fetch_time_and_total(self):
        rows = [row("Sol Ring", 1, quantity="2"), row("Llanowar Elves", 2)]
        built = self.build(rows, mtgmate({"Sol Ring": entry(listing("2.50", 5)),
                                          "Llanowar Elves": entry(listing("0.40", 3), listing("0.30", 1, set_code="m19"))}))
        self.assertEqual(built["queue_revision"], "rev-1")
        mtg = self.basket(built, "mtgmate")
        lines = by_name(mtg["rows"])
        self.assertEqual(list(lines), ["Sol Ring", "Llanowar Elves"])
        self.assertEqual((lines["Sol Ring"]["copies"], lines["Sol Ring"]["line_aud"], lines["Sol Ring"]["fetched_at"]),
                         (2, "5.00", AT))
        self.assertEqual(lines["Llanowar Elves"]["listing"]["set"], "m19")   # any: the cheapest in stock
        self.assertEqual((mtg["total_aud"], mtg["priced"], mtg["unpriced"], mtg["cards"]), ("5.30", 2, 0, 3))
        self.assertEqual(built["unavailable"], [])

    def test_out_of_stock_rows_are_unavailable_with_each_shops_reason(self):
        rows = [row("Gone", 1), row("Never", 2)]
        built = self.build(rows, mtgmate({"Gone": entry(listing(stock=0)), "Never": entry()}),
                           games_portal({"Gone": entry(listing(stock=0), at=GP_AT)}))
        self.assertEqual(self.basket(built, "mtgmate")["rows"], [])
        self.assertIsNone(self.basket(built, "mtgmate")["total_aud"])
        reasons = {item["name"]: [shop["status"] for shop in item["shops"]] for item in built["unavailable"]}
        self.assertEqual(reasons, {"Gone": ["out_of_stock", "out_of_stock"], "Never": ["not_listed", "not_checked"]})

    def test_a_shop_whose_snapshot_couldnt_be_read_claims_nothing(self):
        built = self.build([row("Sol Ring", 1)], mtgmate({"Sol Ring": entry(listing())}))
        gp = self.basket(built, "gamesportal")
        self.assertEqual((gp["read"], gp["rows"], gp["add_ons"], gp["total_aud"], gp["fetched_at"]), (False, [], [], None, None))
        self.assertEqual(self.basket(built, "mtgmate")["read"], True)

    def test_unchecked_and_unreadable_rows_are_named_and_claim_no_stock(self):
        rows = [row("Not Reached", 1), row("Broken", 2)]
        built = self.build(rows, mtgmate({"Broken": entry(status="error", error="timeout")}))
        mtg = self.basket(built, "mtgmate")
        self.assertEqual(mtg["rows"], [])
        self.assertEqual([item["name"] for item in mtg["not_checked"]], ["Not Reached"])
        self.assertEqual([item["name"] for item in mtg["unknown"]], ["Broken"])
        reasons = {item["name"]: [shop["status"] for shop in item["shops"]] for item in built["unavailable"]}
        self.assertEqual(reasons, {"Not Reached": ["not_checked", "unread"], "Broken": ["unknown", "unread"]})

    def test_exact_printing_counts_only_that_printing(self):
        exact = dict(printing="exact", set="fdn", collector_number="227", finish="nonfoil")
        rows = [row("Wanted", 1, **exact), row("Other Printing", 2, **exact)]
        built = self.build(rows, mtgmate({"Wanted": entry(listing("3.00", 1), listing("0.10", 9, set_code="m19")),
                                          "Other Printing": entry(listing("0.10", 9, set_code="m19"))}))
        mtg = self.basket(built, "mtgmate")
        self.assertEqual([(item["name"], item["listing"]["set"], item["line_aud"]) for item in mtg["rows"]],
                         [("Wanted", "fdn", "3.00")])
        self.assertEqual([item["name"] for item in built["unavailable"]], ["Other Printing"])

    def test_an_exact_printing_the_snapshot_cant_tell_is_unconfirmed_not_claimed(self):
        rows = [row("Blank Printing", 1, printing="exact", set="fdn", collector_number="1", finish="nonfoil"),
                row("No Set Recorded", 2, printing="exact")]
        built = self.build(rows, mtgmate({"Blank Printing": entry(listing(set_code="", number="")),
                                          "No Set Recorded": entry(listing())}))
        mtg = self.basket(built, "mtgmate")
        self.assertEqual(mtg["rows"], [])
        self.assertEqual([item["name"] for item in mtg["unconfirmed"]], ["Blank Printing", "No Set Recorded"])
        self.assertEqual([[shop["status"] for shop in item["shops"]] for item in built["unavailable"]],
                         [["unconfirmed", "unread"], ["unconfirmed", "unread"]])

    def test_long_term_and_waiting_rows_in_stock_are_add_ons_and_deferred_rows_are_left_out(self):
        rows = [row("Ready", 1), row("Later", 2, state="long_term"), row("Waiting", 3, state="waiting_for_stock"),
                row("Reprint", 4, state="waiting_for_reprint"), row("Deferred", 5, state="deferred"),
                row("Later Gone", 6, state="long_term")]
        cards = {name: entry(listing("1.00", 4)) for name in ("Ready", "Later", "Waiting", "Reprint", "Deferred")}
        cards["Later Gone"] = entry(listing(stock=0))
        mtg = self.basket(self.build(rows, mtgmate(cards)), "mtgmate")
        self.assertEqual([item["name"] for item in mtg["rows"]], ["Ready"])
        self.assertEqual([(item["name"], item["add_on"]) for item in mtg["add_ons"]],
                         [("Later", True), ("Waiting", True), ("Reprint", True)])
        self.assertEqual((mtg["total_aud"], mtg["add_ons_totals"]["total_aud"]), ("1.00", "3.00"))
        self.assertEqual(mtg["not_checked"], [])

    def test_totals_count_only_known_prices_and_say_how_many_have_none(self):
        rows = [row("Priced", 1, quantity="3"), row("No Price", 2)]
        gp = games_portal({"Priced": entry(listing("1.10", 1), at=GP_AT), "No Price": entry(listing(None, 1), at=GP_AT)})
        basket = self.basket(self.build(rows, None, gp), "gamesportal")
        lines = by_name(basket["rows"])
        # Games Portal says only in stock or not: every copy asked for, no count claimed.
        self.assertEqual((lines["Priced"]["copies"], lines["Priced"]["short"], lines["Priced"]["listing"]["stock"]), (3, False, None))
        self.assertIsNone(lines["No Price"]["line_aud"])
        self.assertEqual((basket["total_aud"], basket["priced"], basket["unpriced"]), ("3.30", 1, 1))
        self.assertFalse(basket["counts_stock"])

    def test_a_shop_with_fewer_copies_counts_only_those(self):
        mtg = self.basket(self.build([row("Short", 1, quantity="4")], mtgmate({"Short": entry(listing("2.00", 1))})), "mtgmate")
        line = mtg["rows"][0]
        self.assertEqual((line["copies"], line["short"], line["line_aud"], line["quantity"]), (1, True, "2.00", "4"))

    def test_an_any_printing_row_is_filled_from_the_shops_other_in_stock_printings(self):
        cards = {"Llanowar Elves": entry(listing("0.40", 1), listing("0.50", 3, set_code="m19", number="314"),
                                         listing("0.10", 9, finish="foil", set_code="dom", number="168"),
                                         listing("0.20", 0, set_code="m20", number="1"))}
        mtg = self.basket(self.build([row("Llanowar Elves", 1, quantity="4")], mtgmate(cards)), "mtgmate")
        line = mtg["rows"][0]
        self.assertEqual((line["copies"], line["short"], line["stock"], line["line_aud"]), (4, False, 4, "1.90"))
        self.assertEqual((line["listing"]["set"], line["listing"]["copies"]), ("fdn", 1))
        # nonfoil chosen, so only nonfoil listings fill it; the out-of-stock one never does
        self.assertEqual([(item["set"], item["copies"], item["price_aud"]) for item in line["more"]], [("m19", 3, "0.50")])
        self.assertEqual((mtg["cards"], mtg["total_aud"]), (4, "1.90"))

    def test_an_any_printing_row_is_short_only_when_every_printing_together_is(self):
        cards = {"Elves": entry(listing("0.40", 1), listing("0.50", 1, set_code="m19"))}
        line = self.basket(self.build([row("Elves", 1, quantity="4")], mtgmate(cards)), "mtgmate")["rows"][0]
        self.assertEqual((line["copies"], line["short"], line["stock"], line["line_aud"]), (2, True, 2, "0.90"))

    def test_a_filling_listing_without_a_price_leaves_the_line_unpriced(self):
        cards = {"Elves": entry(listing("0.40", 1), listing(None, 2, set_code="m19"))}
        line = self.basket(self.build([row("Elves", 1, quantity="3")], mtgmate(cards)), "mtgmate")["rows"][0]
        self.assertEqual((line["copies"], line["line_aud"], line["more"][0]["price_aud"]), (3, None, None))

    def test_an_exact_row_is_never_filled_from_another_printing(self):
        exact = dict(printing="exact", set="fdn", collector_number="227", finish="nonfoil", quantity="3")
        cards = {"Wanted": entry(listing("3.00", 1), listing("0.10", 9, set_code="m19"))}
        line = self.basket(self.build([row("Wanted", 1, **exact)], mtgmate(cards)), "mtgmate")["rows"][0]
        self.assertEqual((line["copies"], line["short"], line["more"], line["line_aud"]), (1, True, [], "3.00"))

    def test_inputs_are_never_changed(self):
        rows = [row("Sol Ring", 1)]
        data = {"mtgmate": mtgmate({"Sol Ring": entry(listing())})}
        before = copy.deepcopy((rows, data))
        shop_baskets.build(rows, data, "rev")
        self.assertEqual((rows, data), before)


class BasketShoppingTests(fixtures._Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        for owner, name in ((shops, "_fetch"), (shops, "_write"), (inventory, "apply")):
            patcher = mock.patch.object(owner, name, side_effect=AssertionError("Baskets only read supplied evidence"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_shopping_answer_carries_baskets_bound_to_its_queue_revision(self):
        saved = mtgmate({"Llanowar Elves": entry(listing("0.50", 9))})
        with mock.patch.object(shops, "load", side_effect=lambda adapter=None, **_: saved if adapter.key == "mtgmate" else None):
            answer = self.overview()
        baskets = answer["baskets"]
        self.assertEqual(baskets["queue_revision"], answer["queue_revision"])
        self.assertEqual([item["key"] for item in baskets["shops"]], ["mtgmate", "gamesportal"])
        self.assertFalse(baskets["shops"][1]["read"])
        ready = {item["queue_row"] for item in answer["to_buy"] if item["state"] == "ready"}
        self.assertTrue(ready)
        shown = {item["queue_row"] for item in baskets["shops"][0]["rows"]} | {item["queue_row"] for item in baskets["unavailable"]}
        self.assertEqual(shown, ready)

    def test_without_any_snapshot_there_are_no_baskets(self):
        with mock.patch.object(shops, "load", return_value=None):
            self.assertNotIn("baskets", self.overview())

    def test_viewers_outside_home_are_refused_before_any_snapshot_is_read(self):
        for identity in ({"profile": "user2", "email": "", "remote": True},
                         {"profile": None, "email": "", "remote": False}):
            with self.subTest(identity=identity), access.using(identity), \
                    mock.patch.object(shops, "load", side_effect=AssertionError("Private shop reader")) as load, \
                    mock.patch.object(shop_baskets, "build", side_effect=AssertionError("Private baskets")) as build:
                with self.assertRaises(common.ApiError) as error:
                    shopping.shopping_overview()
                self.assertEqual(error.exception.status, 403)
                load.assert_not_called()
                build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
