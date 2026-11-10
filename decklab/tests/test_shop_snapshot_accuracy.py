"""E5-S33: a wrong or cut-short shop match says so.

A price history read for the queue row's own printing and finish, Games Portal's first-page-only
flag, an exact row's printing matched with a little tolerance and "listed, but not matched to your
printing" with the shop's sets when it still doesn't, and a token row the shops are never asked for.

Run: python scripts/test_fixtures.py decklab.tests.test_shop_snapshot_accuracy
Nothing here reaches the network, a real snapshot file, the card data or a database.
"""
import contextlib
import io
import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from decklab.lib import cards, shops
from decklab.lib.api import guard, shop_baskets, shop_history
from decklab.lib.api.common import ApiError
from decklab.lib.shops import base, gamesportal, history, mtgmate, rows
from decklab.tests.test_shop_adapters import saved
from decklab.tests.test_shop_adapters import session as saved_session
from decklab.tests.test_shop_baskets import GP_AT, entry, games_portal, listing, row
from decklab.tests.test_shop_baskets import mtgmate as mtgmate_snapshot
from decklab.tests.test_shops_two_shops import TwoShopTestCase

TZ = timezone(timedelta(hours=10))
EXACT = dict(printing="exact", set="ltc", collector_number="12", finish="foil")


def item(set_code, number, finish, price, stock):
    return {"set": set_code, "number": number, "finish": finish, "condition": "Near Mint", "price": price, "stock": stock}


def reading(on, *listings, **extra):
    return {"on": on, "at": f"{on}T03:00:00+10:00", "listings": list(listings), **extra}


class ToleranceTests(unittest.TestCase):
    def test_an_exact_rows_set_and_number_ignore_case_spaces_and_leading_zeros(self):
        wanted = {"printing": "exact", "set": "MSC", "collector_number": "212", "finish": ""}
        choice, stocked = shops.pick(wanted, [item("msc", "0212", "nonfoil", "3.00", 2), item("c16", "272", "nonfoil", "1.00", 9)])
        self.assertEqual((choice["set"], choice["number"], stocked), ("msc", "0212", 1))
        choice, _ = shops.pick({"printing": "exact", "set": "plst", "collector_number": "cmr-1", "finish": "nonfoil"},
                               [item(" PLST", "CMR-1", "nonfoil", "2.00", 1)])
        self.assertEqual(choice["price"], "2.00")

    def test_tolerance_never_joins_two_printings_or_finishes(self):
        wanted = {"printing": "exact", "set": "msc", "collector_number": "212", "finish": "nonfoil"}
        for other in (item("msc", "2120", "nonfoil", "1.00", 1), item("msc", "212a", "nonfoil", "1.00", 1),
                      item("mscx", "212", "nonfoil", "1.00", 1), item("msc", "212", "foil", "1.00", 1)):
            with self.subTest(other=other):
                self.assertEqual(shops.pick(wanted, [other]), (None, 0))
        self.assertEqual(rows.fold_number("000"), "0")

    def test_an_exact_row_the_shop_lists_only_in_other_sets_is_not_matched_and_names_them(self):
        data = mtgmate_snapshot({"Sol Ring": entry(listing(set_code="c16", number="272"), listing(set_code="CMM", number="410")),
                                 "Nothing": entry(status="not_listed")})
        matched = shops.match({"name": "Sol Ring", "printing": "exact", "set": "ltc", "collector_number": "284"}, data)
        self.assertEqual((matched["status"], matched["shop_sets"], matched["price_aud"]), ("not_matched", ["c16", "cmm"], None))
        self.assertIn("listed, but not matched to your printing (the shop's sets: C16, CMM)", shops._describe(matched))
        # The right set in another finish or number is still the shop's listing, not this printing.
        foil = shops.match({"name": "Sol Ring", "printing": "exact", "set": "c16", "collector_number": "272", "finish": "foil"}, data)
        self.assertEqual((foil["status"], foil["shop_sets"]), ("not_matched", ["c16", "cmm"]))
        unlisted = shops.match({"name": "Nothing", "printing": "exact", "set": "ltc", "collector_number": "284"}, data)
        self.assertEqual((unlisted["status"], unlisted["shop_sets"]), ("not_listed", []))
        # Any-printing rows are answered as before, with no sets named.
        self.assertEqual(shops.match({"name": "Sol Ring", "printing": "any"}, data)["status"], "in_stock")
        self.assertEqual(shops.match({"name": "Sol Ring", "printing": "any"}, data)["shop_sets"], [])


class FirstPageTests(unittest.TestCase):
    def page(self, name="sol-ring.html", next_link=False, repeat=1):
        text = re.sub(r'<a href="/search\?page=2[^>]*>Next</a>\n?', "", saved("gamesportal", name))
        if repeat > 1:
            head, rest = text.split('<div class="product-card-list2 ', 1)
            body, tail = rest.rsplit("</main>", 1)
            text = head + ('<div class="product-card-list2 ' + body) * repeat + "</main>" + tail
        if next_link:
            text = text.replace("</main>", '<a href="/search?page=2&amp;q=Sol Ring&amp;type=product">Next</a>\n</main>')
        return text

    def test_a_page_that_links_a_further_page_is_partial(self):
        for name, card in (("sol-ring.html", "Sol Ring"), ("no-match.html", "Nothing Such")):
            with self.subTest(name=name):
                self.assertTrue(gamesportal.parse_name_page(saved("gamesportal", name), card).partial)
        whole = gamesportal.parse_name_page(self.page(), "Sol Ring")
        self.assertFalse(whole.partial)
        self.assertTrue(gamesportal.parse_name_page(self.page(next_link=True), "Sol Ring").partial)
        self.assertEqual(list(gamesportal.parse_name_page(self.page(next_link=True), "Sol Ring")), list(whole))

    def test_a_full_page_is_partial_even_without_a_link(self):
        products = self.page().count('id="productCardList2-js-')
        self.assertLess(products, gamesportal.PAGE_SIZE)
        full = self.page(repeat=-(-gamesportal.PAGE_SIZE // products))
        self.assertTrue(gamesportal.parse_name_page(full, "Sol Ring").partial)

    def test_only_a_later_page_of_this_search_counts(self):
        for href, more in (("/search?page=2&q=Sol%20Ring", True), ("https://gamesportal.com.au/search?q=x&page=3", True),
                           ("/search?page=1&q=Sol", False), ("/search?q=Sol", False), ("/collections/all?page=2", False),
                           ("https://other.example.com/search?page=2", False), ("/search?page=two", False), (None, False)):
            with self.subTest(href=href):
                self.assertEqual(gamesportal._further_page(href), more)

    def test_no_results_and_mtgmates_whole_page_are_never_partial(self):
        empty = '<html><head><title>Search: 0 results found for "X" - Games Portal</title></head></html>'
        found = gamesportal.parse_name_page(empty, "X")
        self.assertEqual((list(found), found.partial), ([], False))
        self.assertFalse(getattr(mtgmate.parse_name_page(saved("mtgmate", "sol-ring.html"), "Sol Ring"), "partial", False))
        self.assertEqual(base.Listings([1], partial=True), [1])

    def test_the_snapshot_keeps_the_flag_carries_it_and_its_lines_say_so(self):
        _, asked = saved_session(gamesportal.ADAPTER, {"Sol Ring": "sol-ring.html"})
        data = shops.take(["Sol Ring", "Nothing Such"], session=asked, now=lambda: datetime(2026, 11, 2, 3, tzinfo=TZ))
        self.assertEqual([(name, card["status"], card.get("partial")) for name, card in data["cards"].items()],
                         [("Sol Ring", "ok", True), ("Nothing Such", "not_listed", True)])
        self.assertIs(type(data["cards"]["Sol Ring"]["listings"]), list)
        json.dumps(data)
        self.assertEqual([day.get("partial") for day in data["history"]["Sol Ring"]], [True])
        listed = shops.match({"name": "Sol Ring", "printing": "any"}, data)
        self.assertEqual((listed["status"], listed["partial"]), ("in_stock", True))
        self.assertTrue(shops._describe(listed).endswith("; first page only, more results not read"))
        unlisted = shops.match({"name": "Nothing Such", "printing": "any"}, data)
        self.assertEqual(shops._describe(unlisted), "not listed; first page only, more results not read")
        # A later run that runs out of time carries the earlier reading, flag included.
        _, again = saved_session(gamesportal.ADAPTER, {"Sol Ring": "sol-ring.html"})
        carried = shops.take(["Sol Ring"], session=again, previous=data, budget=0,
                             now=lambda: datetime(2026, 11, 3, 3, tzinfo=TZ))
        self.assertEqual((carried["cards"]["Sol Ring"].get("carried"), carried["cards"]["Sol Ring"].get("partial")), (True, True))

    def test_a_whole_page_has_no_flag(self):
        data = mtgmate_snapshot({"Sol Ring": entry(listing())})
        matched = shops.match({"name": "Sol Ring", "printing": "any"}, data)
        self.assertFalse(matched["partial"])
        self.assertNotIn("first page", shops._describe(matched))


class MissingCardFirstPageTests(unittest.TestCase):
    """Missing cards' and deck Prices' nonfoil evidence (lib/api/shop_missing_prices.py) says it too."""

    def shown(self, card):
        from decklab.lib.api import shop_missing_prices
        data = games_portal({"Sol Ring": card})
        url = f"{gamesportal.SITE}/products/sol-ring-commander-2016?variant=9002"
        for found in card.get("listings", ()):
            found["url"] = url
        return shop_missing_prices.Projection(data, None, gamesportal.ADAPTER).for_row({"name": "Sol Ring"})

    def test_a_first_page_only_reading_is_marked_and_a_whole_one_keeps_its_fields(self):
        partial = self.shown(entry(listing(), at=GP_AT, partial=True))
        self.assertEqual((partial["status"], partial["partial"]), ("in_stock", True))
        unlisted = self.shown(entry(status="not_listed", at=GP_AT, partial=True))
        self.assertEqual((unlisted["status"], unlisted["partial"]), ("not_listed", True))
        for whole in (entry(listing(), at=GP_AT), entry(listing(), at=GP_AT, partial=False),
                      entry(listing(), at=GP_AT, partial="yes")):
            self.assertNotIn("partial", self.shown(whole))
        self.assertNotIn("partial", self.shown(entry(status="error", at=GP_AT, partial=True, error="x")))


class TokenRowTests(unittest.TestCase):
    def test_a_token_row_is_never_looked_up_and_its_line_says_so(self):
        queue = [{"name": "Sol Ring"}, {"name": "Treasure", "is_token": True}, {"name": "Opt"}]
        self.assertEqual(shops.queue_names(queue), ["Sol Ring", "Opt"])
        data = mtgmate_snapshot({"Treasure": entry(listing())})       # another card's listings under the name
        matched = shops.match(queue[1], data)
        self.assertEqual((matched["status"], matched["price_aud"], matched["fetched_at"]), ("token", None, None))
        self.assertEqual(shops._describe(matched), "token cards aren't checked at this shop")

    def test_a_name_also_queued_as_a_card_is_still_looked_up(self):
        queue = [{"name": "Treasure", "is_token": True}, {"name": "treasure"}]
        self.assertEqual(shops.queue_names(queue), ["treasure"])

    def test_rows_are_marked_from_the_card_index_by_positive_evidence_only(self):
        tokens = {("tltc", "5"): ("id", ["Treasure"])}
        with mock.patch.object(cards, "token_faces_at", lambda s, n: tokens.get((s, n))), \
                mock.patch.object(cards, "printing_card", lambda s, n: {"name": "Sol Ring"} if (s, n) == ("ltc", "284") else None), \
                mock.patch.object(cards, "resolve", lambda name: name if name in ("Sol Ring", "Blood") else None), \
                mock.patch.object(cards, "token_face", lambda name: name if name in ("Treasure", "Blood") else None):
            queue = rows.flag_tokens([
                {"name": "Treasure", "set": "tltc", "collector_number": "5"}, {"name": "Treasure", "set": "", "collector_number": ""},
                {"name": "Sol Ring", "set": "ltc", "collector_number": "284"}, {"name": "Blood", "set": "", "collector_number": ""},
                {"name": "Unknown Card", "set": "", "collector_number": ""}])
        self.assertEqual([bool(found.get("is_token")) for found in queue], [True, True, False, False, False])

    def test_without_the_card_data_no_row_is_marked(self):
        with mock.patch.object(cards, "resolve", side_effect=RuntimeError("no card data")), \
                mock.patch.object(cards, "token_faces_at", side_effect=RuntimeError("no card data")):
            self.assertFalse(rows.is_token({"name": "Treasure", "set": "tltc", "collector_number": "5"}))
            self.assertFalse(rows.is_token({"name": "Treasure"}))
        self.assertTrue(rows.is_token({"name": "Treasure", "is_token": True}))


class RowHistoryTests(unittest.TestCase):
    DAYS = [reading("2026-11-01", item("c16", "272", "nonfoil", "1.00", 5), item("ltc", "12", "foil", "9.00", 1),
                    item("ltc", "12", "nonfoil", "2.00", 3)),
            reading("2026-11-02", item("c16", "272", "nonfoil", "0.50", 5), item("ltc", "012", "foil", "7.00", 0),
                    item("sld", "1011", "foil", "4.00", 2)),
            reading("2026-11-03", item("c16", "272", "nonfoil", "0.75", 5), partial=True)]

    def report(self, asked=None):
        return history.report("Sol Ring", [(mtgmate.ADAPTER, {"history": {"Sol Ring": self.DAYS}})], shops.pick, row=asked)

    def days(self, asked=None):
        return self.report(asked)["shops"][0]["days"]

    def test_an_exact_rows_days_and_lowest_are_its_own_printing_and_finish(self):
        days = self.days({"name": "Sol Ring", **EXACT})
        self.assertEqual([(day["price"], day["in_stock"], day["listed"], day["lowest"], day["elsewhere"]) for day in days],
                         [("9.00", True, True, True, False), ("7.00", False, True, False, False),
                          (None, False, False, False, True)])
        self.assertEqual([(day["set"], day["finish"]) for day in days[:2]], [("ltc", "foil"), ("ltc", "foil")])
        self.assertEqual(self.report({"name": "Sol Ring", **EXACT})["scope"], "LTC 12 foil")

    def test_a_foil_row_of_any_printing_reads_only_foil_listings(self):
        days = self.days({"name": "Sol Ring", "printing": "any", "finish": "foil"})
        self.assertEqual([(day["price"], day["set"], day["in_stock"], day["lowest"]) for day in days],
                         [("9.00", "ltc", True, False), ("4.00", "sld", True, True), (None, None, False, False)])
        self.assertTrue(days[2]["elsewhere"])
        self.assertEqual(self.report({"name": "Sol Ring", "finish": "etched"})["scope"], "any etched printing")
        self.assertEqual([day["listed"] for day in self.days({"name": "Sol Ring", "finish": "etched"})], [False] * 3)

    def test_a_plain_row_and_no_row_read_as_any_printing(self):
        for asked in (None, {"name": "Sol Ring", "printing": "any", "finish": ""},
                      {"name": "Sol Ring", "printing": "exact", "set": "", "collector_number": "", "finish": "nonfoil"}):
            with self.subTest(asked=asked):
                days = self.days(asked)
                self.assertEqual([(day["price"], day["set"], day["lowest"]) for day in days],
                                 [("1.00", "c16", False), ("0.50", "c16", True), ("0.75", "c16", False)])
                self.assertEqual(self.report(asked)["scope"], "any printing")

    def test_a_first_page_only_day_says_so(self):
        self.assertEqual([day["partial"] for day in self.days()], [False, False, True])
        said = history.lines(self.report({"name": "Sol Ring", **EXACT}))
        self.assertEqual(said[0], "Read for LTC 12 foil.")
        self.assertEqual(said[2], "  2026-11-01  A$9.00, 1 in stock (LTC 12 foil)  lowest in stock")
        self.assertEqual(said[4], "  2026-11-03  listed, but not in this printing; first page only, more results not read")
        self.assertNotIn("Read for", history.lines(self.report())[0])


class PriceHistoryRowTests(unittest.TestCase):
    QUEUE = [{"name": "Sol Ring", "printing": "any", "finish": ""}, {"name": "Sol Ring", **EXACT},
             {"name": "Opt", "printing": "any", "finish": ""}, {"name": "Treasure", "is_token": True}]

    def setUp(self):
        for target, name, value in (
                (guard, "require_sees_home_records", lambda: None),
                (shops, "_queue", lambda: [dict(found) for found in self.QUEUE]),
                (shops, "load_history", lambda adapter=None, path=None:
                    {"Sol Ring": RowHistoryTests.DAYS} if adapter.key == "mtgmate" else {}),
                (shops, "enabled_adapters", lambda settings=None: shops.SNAPSHOT_ADAPTERS)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_row_selector_reads_that_rows_own_printing(self):
        answer = shop_history.price_history_view("sol ring", row="2")
        self.assertEqual((answer["queued"], answer["scope"]), (True, "LTC 12 foil"))
        self.assertEqual([day["price"] for day in answer["shops"][0]["days"]], ["9.00", "7.00", None])
        plain = shop_history.price_history_view("Sol Ring", row=1)
        self.assertEqual((plain["scope"], [day["price"] for day in plain["shops"][0]["days"]]),
                         ("any printing", ["1.00", "0.50", "0.75"]))
        self.assertEqual(shop_history.price_history_view("Sol Ring")["scope"], "any printing")

    def test_a_row_that_is_no_longer_that_cards_is_refused_not_read_as_another(self):
        for number in (3, 9, "4"):
            with self.subTest(number=number), self.assertRaises(ApiError) as caught:
                shop_history.price_history_view("Sol Ring", row=number)
            self.assertEqual(caught.exception.status, 409)

    def test_a_bad_row_is_refused(self):
        for bad in ("0", "-1", "two", "1.5", True, [1], "1234567", "²"):
            with self.subTest(bad=bad), self.assertRaises(ApiError) as caught:
                shop_history.price_history_view("Sol Ring", row=bad)
            self.assertEqual(caught.exception.status, 400)

    def test_a_token_rows_name_has_no_history(self):
        self.assertEqual(shop_history.price_history_view("Treasure", row="4"),
                         {"name": "Treasure", "queued": False, "shops": []})

    def test_the_route_takes_the_row(self):
        from decklab.lib import feature_routes
        source = "".join(open(feature_routes.__file__, encoding="utf-8"))
        self.assertIn('("shopping", "price-history"): (_price_history, ("name", "row"))', source)


class HistoryCommandRowTests(TwoShopTestCase):
    def run_history(self, *argv, code=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(shops.main(["history", *argv]), code)
        return out.getvalue(), err.getvalue()

    def test_row_reads_the_queue_rows_own_printing_and_a_wrong_row_is_refused(self):
        shops._write({"version": 1, "shop": "MTGMate", "cards": {}, "history": {"Sol Ring": RowHistoryTests.DAYS}},
                     shops.snapshot_path(mtgmate.ADAPTER))
        with mock.patch.object(shops, "_queue", return_value=[{"name": "Opt"}, {"name": "Sol Ring", **EXACT}]):
            out, _ = self.run_history("Sol Ring", "--row", "2", "--shop", "mtgmate")
            self.assertEqual(out.splitlines()[:3], ["Read for LTC 12 foil.", "MTGMate: 3 days",
                                                    "  2026-11-01  A$9.00, 1 in stock (LTC 12 foil)  lowest in stock"])
            out, err = self.run_history("Sol Ring", "--row", "1", "--shop", "mtgmate", code=1)
            self.assertEqual(out, "")
            self.assertIn("Row #1 of the purchase queue isn't Sol Ring", err)
        with mock.patch.object(shops, "_queue", side_effect=AssertionError("the queue isn't read without --row")):
            out, _ = self.run_history("Sol Ring", "--shop", "mtgmate")
        self.assertEqual(out.splitlines()[1], "  2026-11-01  A$1.00, 5 in stock (C16 272 nonfoil)")


class BasketAccuracyTests(unittest.TestCase):
    def build(self, queue, mtg=None, gp=None):
        captured = {key: value for key, value in (("mtgmate", mtg), ("gamesportal", gp)) if value}
        return shop_baskets.build(queue, captured, "rev-1")

    def test_a_first_page_only_line_is_marked_in_the_basket_and_in_the_reasons(self):
        queue = [row("Sol Ring", 1), row("Rare Thing", 2)]
        built = self.build(queue, mtgmate_snapshot({"Sol Ring": entry(listing()), "Rare Thing": entry(status="not_listed")}),
                           games_portal({"Sol Ring": entry(listing(), at=GP_AT, partial=True),
                                         "Rare Thing": entry(status="not_listed", at=GP_AT, partial=True)}))
        mtg, gp = built["shops"]
        self.assertEqual((mtg["rows"][0]["partial"], mtg["partial"]), (False, 0))
        self.assertEqual((gp["rows"][0]["partial"], gp["partial"]), (True, 1))
        reasons = built["unavailable"][0]["shops"]
        self.assertEqual([(shop["status"], shop["partial"]) for shop in reasons], [("not_listed", False), ("not_listed", True)])

    def test_an_unmatched_exact_row_names_the_shops_sets_and_claims_no_stock(self):
        wanted = row("Sol Ring", 1, printing="exact", set="ltc", collector_number="284", finish="nonfoil")
        built = self.build([wanted], mtgmate_snapshot({"Sol Ring": entry(listing(set_code="c16"), listing(set_code="cmm"))}))
        self.assertEqual(built["shops"][0]["rows"], [])
        shop = built["unavailable"][0]["shops"][0]
        self.assertEqual((shop["status"], shop["shop_sets"]), ("not_matched", ["c16", "cmm"]))

    def test_a_token_row_is_in_no_basket_and_says_tokens_arent_checked(self):
        token = row("Treasure", 1, is_token=True, printing="exact", set="", collector_number="")
        built = self.build([token, row("Sol Ring", 2)],
                           mtgmate_snapshot({"Treasure": entry(listing()), "Sol Ring": entry(listing())}))
        mtg = built["shops"][0]
        self.assertEqual([found["name"] for found in mtg["rows"]], ["Sol Ring"])
        self.assertEqual((mtg["unconfirmed"], mtg["not_checked"]), ([], []))
        self.assertEqual([(found["name"], [shop["status"] for shop in found["shops"]]) for found in built["unavailable"]],
                         [("Treasure", ["token", "unread"])])


if __name__ == "__main__":
    unittest.main()
