"""The shop adapters' common interface (E5-S08), MTGMate's and Games Portal's, read from saved pages.

The pages are synthetic (decklab/tests/fixtures/shops/<key>/): invented prices and stock in
the shape of the shop's own page, so the parsing is checked without the network or card data.
"""
import contextlib
import html
import importlib.util
import io
import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import config, shops
from decklab.lib.shops import base, gamesportal, mtgmate

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "shops"


def saved(key, name):
    return (FIXTURES / key / name).read_text(encoding="utf-8")


class SavedShop:
    """Serves one adapter's saved pages: robots.txt, and a name page by its file."""

    def __init__(self, adapter, pages):
        self.adapter, self.pages, self.urls = adapter, pages, []

    def __call__(self, url):
        self.urls.append(url)
        if url == self.adapter.robots_url():
            return saved(self.adapter.key, "robots.txt")
        for name, file in self.pages.items():
            if url == self.adapter.name_url(name):
                return saved(self.adapter.key, file)
        return saved(self.adapter.key, "no-match.html")


class Still:
    def __call__(self):
        return 0.0

    def sleep(self, seconds):
        pass


def session(adapter, pages):
    shop, clock = SavedShop(adapter, pages), Still()
    return shop, shops.Session(fetch=shop, sleep=clock.sleep, clock=clock, adapter=adapter)


class Other(base.Adapter):
    """A second, invented shop: proves the package asks through the interface, not MTGMate's names."""
    key, name, site = "other-shop", "Other Shop", "https://other.example.com"

    def name_url(self, name):
        return f"{self.site}/singles/{name.replace(' ', '-').lower()}"

    def parse_name_page(self, text, name):
        if "No matches for" in text:
            return []
        return [{"set": "fdn", "number": "1", "finish": "nonfoil", "price": "1.00", "stock": 3,
                 "condition": "NM", "url": self.name_url(name)}]


class InterfaceTests(unittest.TestCase):
    def test_every_adapter_says_who_it_is_and_where_its_pages_are(self):
        self.assertEqual(list(shops.ADAPTERS), ["mtgmate", "gamesportal"])
        self.assertIs(shops.ADAPTER, mtgmate.ADAPTER)
        for key, adapter in shops.ADAPTERS.items():
            with self.subTest(key):
                self.assertIsInstance(adapter, base.Adapter)
                self.assertEqual(adapter.key, key)
                self.assertRegex(key, r"^[a-z0-9]+(-[a-z0-9]+)*$")
                self.assertTrue(adapter.name)
                self.assertRegex(adapter.site, r"^https://[^/]+$")
                self.assertTrue(adapter.robots_url().startswith(adapter.site + "/"))
                self.assertTrue(adapter.name_url("Sol Ring").startswith(adapter.site + "/"))
                self.assertTrue((FIXTURES / key / "robots.txt").is_file(), "each adapter has saved pages")

    def test_the_base_adapter_has_no_pages_of_its_own(self):
        with self.assertRaises(NotImplementedError):
            base.Adapter().name_url("Sol Ring")
        with self.assertRaises(NotImplementedError):
            base.Adapter().parse_name_page("", "Sol Ring")

    def test_the_package_keeps_its_names_and_the_cache_path(self):
        self.assertEqual((shops.SHOP, shops.SITE, shops.NAME_PATH), ("MTGMate", "https://www.mtgmate.com.au", "/cards/"))
        self.assertIs(shops.ShopError, base.ShopError)
        self.assertIs(shops.parse_name_page, mtgmate.parse_name_page)
        self.assertIs(shops.robots_rules, base.robots_rules)
        environ = {key: value for key, value in os.environ.items() if key != shops.SNAPSHOT_ENV}
        with mock.patch.dict(os.environ, environ, clear=True), mock.patch.object(shops, "SNAPSHOT", None):
            path = shops.snapshot_path()
            lock = shops._lock_path()
        self.assertEqual(path, Path(config.REPO) / "decklab" / "data" / "shops" / "mtgmate.json")
        self.assertEqual(lock.name, "mtgmate.lock")

    def test_the_command_runs_as_the_package(self):
        self.assertIsNotNone(importlib.util.find_spec("decklab.lib.shops.__main__"))
        with self.assertRaises(SystemExit) as stop, mock.patch("sys.stdout"):
            shops.main(["--help"])
        self.assertEqual(stop.exception.code, 0)

    def test_a_default_session_fetches_through_the_package_guard(self):
        # the tests replace shops._fetch; a Session made later still goes through it
        with mock.patch.object(shops, "_fetch", side_effect=AssertionError("no network")) as fetch:
            with self.assertRaises(AssertionError):
                shops.Session(sleep=Still().sleep, clock=Still()).start()
        self.assertEqual(fetch.call_args.args, ("https://www.mtgmate.com.au/robots.txt", "MTGMate"))

    def test_another_adapter_is_asked_through_the_interface(self):
        other, clock = Other(), Still()
        pages = {other.robots_url(): saved("mtgmate", "robots.txt"), other.name_url("Sol Ring"): "in stock"}
        sess = shops.Session(fetch=lambda url: pages.get(url, "No matches for"), sleep=clock.sleep, clock=clock,
                             adapter=other)
        data = shops.take(["Sol Ring", "Nothing"], session=sess)
        self.assertEqual((data["shop"], data["site"]), ("Other Shop", "https://other.example.com"))
        self.assertEqual(data["cards"]["Sol Ring"]["listings"][0]["url"], "https://other.example.com/singles/sol-ring")
        self.assertEqual(data["cards"]["Nothing"]["status"], "not_listed")
        shown = shops.match({"name": "Sol Ring", "printing": "any"}, data)
        self.assertEqual((shown["shop"], shown["status"], shown["price_aud"]), ("Other Shop", "in_stock", "1.00"))

    def test_a_disallowed_page_names_its_own_shop(self):
        other = Other()
        clock = Still()
        sess = shops.Session(fetch=lambda url: "User-agent: *\nDisallow: /singles/\n", sleep=clock.sleep,
                             clock=clock, adapter=other)
        with self.assertRaises(base.Disallowed) as refused:
            sess.listings("Sol Ring")
        self.assertIn("Other Shop's robots.txt", str(refused.exception))


class MTGMatePageTests(unittest.TestCase):
    adapter = mtgmate.ADAPTER

    def test_the_saved_robots_file_disallows_search_and_keeps_the_delay(self):
        rules = base.robots_rules(saved("mtgmate", "robots.txt"))
        self.assertEqual(rules[2], 60.0)
        self.assertTrue(base.allowed("/cards/Sol%20Ring", rules))
        self.assertFalse(base.allowed("/cards/search?q=sol", rules))

    def test_the_saved_name_page_gives_its_listings_only(self):
        listings = self.adapter.parse_name_page(saved("mtgmate", "sol-ring.html"), "Sol Ring")
        self.assertEqual([(item["set"], item["number"], item["finish"], item["price"], item["stock"], item["condition"])
                          for item in listings],
                         [("40k", "249", "nonfoil", "3.80", 1, "Moderately Played"),
                          ("40k", "249", "nonfoil", "4.50", 2, "Regular"),
                          ("c16", "272", "nonfoil", "5.00", 0, "Regular"),
                          ("cmm", "410", "nonfoil", None, 0, "Regular"),
                          ("sld", "1011", "foil", "3.00", 1, "Regular")])
        for item in listings:
            self.assertEqual(tuple(item), base.LISTING_FIELDS, "nothing else from the page is kept")
            self.assertTrue(item["url"].startswith("https://www.mtgmate.com.au/cards/Sol_Ring/"))

    def test_a_double_faced_name_matches_its_front_face(self):
        name = "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki"
        listings = self.adapter.parse_name_page(saved("mtgmate", "fable.html"), name)
        self.assertEqual([(item["number"], item["finish"]) for item in listings], [("141", "nonfoil"), ("357", "foil")])

    def test_no_matches_is_empty_and_a_changed_or_broken_page_an_error(self):
        self.assertEqual(self.adapter.parse_name_page(saved("mtgmate", "no-match.html"), "Nothing Such"), [])
        for page, words in (("changed.html", "usual card table"), ("broken-table.html", "couldn't be read")):
            with self.subTest(page), self.assertRaises(base.ShopError) as failed:
                self.adapter.parse_name_page(saved("mtgmate", page), "Sol Ring")
            self.assertIn(words, str(failed.exception))
            self.assertTrue(str(failed.exception).startswith("MTGMate's "))

    def test_a_snapshot_over_the_saved_pages(self):
        shop, sess = session(self.adapter, {"Sol Ring": "sol-ring.html"})
        data = shops.take(["Sol Ring", "Nothing Such"], session=sess)
        self.assertEqual(shop.urls, ["https://www.mtgmate.com.au/robots.txt", "https://www.mtgmate.com.au/cards/Sol%20Ring",
                                     "https://www.mtgmate.com.au/cards/Nothing%20Such"])
        self.assertEqual((data["shop"], data["crawl_delay"]), ("MTGMate", 60.0))
        shown = shops.match({"name": "Sol Ring", "printing": "any", "state": "waiting_for_stock"}, data)
        self.assertEqual((shown["status"], shown["price_aud"], shown["set"], shown["in_stock_printings"]),
                         ("in_stock", "3.80", "40k", 3))
        self.assertTrue(shown["back_in_stock"])
        self.assertEqual(data["cards"]["Nothing Such"]["status"], "not_listed")

    def test_the_saved_pages_hold_no_personal_data(self):
        for path in sorted((FIXTURES / "mtgmate").iterdir()):
            with self.subTest(path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), "no email address")
                body = text.removeprefix("<!doctype html>\n")
                self.assertTrue(body.startswith(("<!-- Synthetic", "# Synthetic")), "marked synthetic in its first comment")


class GamesPortalPageTests(unittest.TestCase):
    adapter = gamesportal.ADAPTER

    def test_its_page_is_the_search_robots_txt_allows(self):
        self.assertEqual(self.adapter.name_url("Sol Ring"), "https://gamesportal.com.au/search?q=Sol%20Ring&type=product")
        self.assertEqual(self.adapter.name_url("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki"),
                         "https://gamesportal.com.au/search?q=Fable%20of%20the%20Mirror-Breaker%20%2F%2F%20"
                         "Reflection%20of%20Kiki-Jiki&type=product")
        rules = base.robots_rules(saved("gamesportal", "robots.txt"))
        self.assertIsNone(rules[2], "no Crawl-delay: the session keeps its own")
        self.assertTrue(base.allowed("/search", rules))
        self.assertFalse(base.allowed("/checkout", rules))
        self.assertFalse(base.allowed("/cart/add", rules))

    def test_the_saved_search_page_gives_that_cards_listings_only(self):
        listings = self.adapter.parse_name_page(saved("gamesportal", "sol-ring.html"), "Sol Ring")
        self.assertEqual([(item["set"], item["number"], item["finish"], item["price"], item["stock"], item["condition"])
                          for item in listings],
                         [("c16", "272", "nonfoil", "4.50", 1, "Lightly Played"),
                          ("c16", "272", "nonfoil", "5.00", 0, "Near Mint"),
                          ("cmm", "410", "nonfoil", None, 0, "Lightly Played, JA"),
                          ("cmm", "410", "nonfoil", "3.00", 1, "Near Mint, JA"),
                          ("sld", "1011", "foil", "35.00", 1, "Near Mint"),
                          ("sld", "1011", "nonfoil", "30.00", 0, "Near Mint")])
        for item in listings:
            self.assertEqual(tuple(item), base.LISTING_FIELDS, "nothing else from the page is kept")
            self.assertRegex(item["url"], r"^https://gamesportal\.com\.au/products/sol-ring-[a-z0-9-]+\?variant=\d+$")
        self.assertEqual(listings[0]["url"], "https://gamesportal.com.au/products/sol-ring-commander-2016?variant=9002")

    def test_a_double_faced_name_matches_its_whole_title_or_front_face(self):
        name = "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki"
        listings = self.adapter.parse_name_page(saved("gamesportal", "fable.html"), name)
        self.assertEqual([(item["set"], item["number"], item["finish"], item["stock"]) for item in listings],
                         [("neo", "141", "nonfoil", 1), ("neo", "465", "foil", 0), ("sch", "44", "nonfoil", 0)])

    @staticmethod
    def page(*products):
        """A synthetic search page of products, each (its data-product-type or None, its variants)."""
        cards = []
        for ident, (kind, variants) in enumerate(products, 4001):
            typed = "" if kind is None else f" data-product-type='{html.escape(kind)}'"
            cards.append(f'<div class="product-card-list2 product-card-list2__{ident}"><a href="/products/p-{ident}">'
                         f'</a></div><div hidden id="productCardList2-js-{ident}"'
                         f" data-product-variants='{html.escape(json.dumps(variants))}'{typed}></div>")
        return "<html><head><title>Search: 1 results</title></head><body>" + "".join(cards) + "</body></html>"

    def test_the_skus_finish_says_when_the_public_title_doesnt_and_unknown_when_neither_does(self):
        def one(public_title, sku):
            variant = {"id": 1, "name": "Sol Ring (Foil) [C16]", "public_title": public_title, "sku": sku,
                       "available": True, "price": 900}
            found = self.adapter.parse_name_page(self.page(("MTG Single", [variant])), "Sol Ring")
            return [(item["set"], item["number"], item["finish"], item["condition"]) for item in found]
        self.assertEqual(one(None, "C16-272-EN-FO-1"), [("c16", "272", "foil", "")])
        self.assertEqual(one("Default Title", "C16-272-EN-NF-1"), [("c16", "272", "nonfoil", "")])
        self.assertEqual(one(None, "C16-272-EN-XX-1"), [("c16", "272", "unknown", "")])
        self.assertEqual(one("Near Mint", "C16-272-EN-FO-1"), [("c16", "272", "unknown", "Near Mint")])
        self.assertEqual(one("Near Mint Foil Etched", "CMM-410-EN-FO-1"), [("cmm", "410", "etched", "Near Mint")])
        self.assertEqual(one("Near Mint", "PLST-CMR-1-EN-NF-1"), [("plst", "CMR-1", "nonfoil", "Near Mint")])
        self.assertEqual(one("Near Mint", "PLST-CMR-1//CMR-1-EN-NF-1"), [("plst", "CMR-1", "nonfoil", "Near Mint")])

    def test_a_variant_whose_sku_names_no_printing_is_never_a_listing(self):
        sealed = {"id": 2, "name": "Sol Ring", "public_title": None, "sku": "D0000001", "available": True, "price": 9900}
        for kind in (None, "MTG Single", "Sealed"):
            with self.subTest(kind):
                self.assertEqual(self.adapter.parse_name_page(self.page((kind, [sealed])), "Sol Ring"), [])

    def test_no_such_card_is_empty_and_a_changed_or_broken_page_an_error(self):
        self.assertEqual(self.adapter.parse_name_page(saved("gamesportal", "no-match.html"), "Nothing Such"), [])
        empty = "<html><head><title>Search: 0 results found for &quot;Nothing&quot;</title></head></html>"
        self.assertEqual(self.adapter.parse_name_page(empty, "Nothing"), [])
        for page, words in (("changed.html", "usual product data"), ("broken-variants.html", "couldn't be read"),
                            ("../mtgmate/sol-ring.html", "usual product data")):
            with self.subTest(page), self.assertRaises(base.ShopError) as failed:
                self.adapter.parse_name_page(saved("gamesportal", page), "Sol Ring")
            self.assertIn(words, str(failed.exception))
            self.assertTrue(str(failed.exception).startswith("Games Portal's "))

    def test_a_snapshot_over_the_saved_pages(self):
        shop, sess = session(self.adapter, {"Sol Ring": "sol-ring.html"})
        data = shops.take(["Sol Ring", "Nothing Such"], session=sess)
        self.assertEqual(shop.urls, ["https://gamesportal.com.au/robots.txt",
                                     "https://gamesportal.com.au/search?q=Sol%20Ring&type=product",
                                     "https://gamesportal.com.au/search?q=Nothing%20Such&type=product"])
        self.assertEqual((data["shop"], data["site"], data["crawl_delay"]),
                         ("Games Portal", "https://gamesportal.com.au", shops.DEFAULT_DELAY))
        shown = shops.match({"name": "Sol Ring", "printing": "any", "state": "waiting_for_stock"}, data)
        self.assertEqual((shown["shop"], shown["status"], shown["price_aud"], shown["set"], shown["in_stock_printings"]),
                         ("Games Portal", "in_stock", "3.00", "cmm", 3))
        exact = shops.match({"name": "Sol Ring", "printing": "exact", "set": "sld", "collector_number": "1011",
                             "finish": "foil"}, data)
        self.assertEqual((exact["status"], exact["price_aud"]), ("in_stock", "35.00"))
        self.assertEqual(data["cards"]["Nothing Such"]["status"], "not_listed")

    def test_lookup_asks_it_only_when_named(self):
        pages = SavedShop(self.adapter, {"Sol Ring": "sol-ring.html"})
        out = io.StringIO()
        with mock.patch.object(shops, "_fetch", side_effect=lambda url, shop: pages(url)), \
                mock.patch.object(shops.time, "sleep"), contextlib.redirect_stdout(out):
            code = shops.main(["lookup", "Sol Ring", "--shop", "gamesportal"])
        self.assertEqual(code, 0)
        self.assertEqual(pages.urls[0], "https://gamesportal.com.au/robots.txt")
        # its pages say only whether a listing is available, never how many
        self.assertIn("SLD 1011 foil Near Mint: A$35.00, in stock", out.getvalue())
        self.assertIn("C16 272 nonfoil Near Mint: A$5.00, out of stock", out.getvalue())
        self.assertIs(shops.ADAPTER, mtgmate.ADAPTER, "MTGMate stays the first shop")
        with mock.patch.object(shops, "_fetch", side_effect=AssertionError("no network")) as fetch, \
                mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            shops.main(["lookup", "Sol Ring", "--shop", "nowhere"])
        fetch.assert_not_called()

    def test_the_saved_pages_hold_no_personal_data(self):
        for path in sorted((FIXTURES / "gamesportal").iterdir()):
            with self.subTest(path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), "no email address")
                body = text.removeprefix("<!doctype html>\n")
                self.assertTrue(body.startswith(("<!-- Synthetic", "# Synthetic")), "marked synthetic in its first comment")


if __name__ == "__main__":
    unittest.main()
