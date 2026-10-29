"""The shop adapters' common interface (E5-S08) and MTGMate's, read from saved pages.

The pages are synthetic (decklab/tests/fixtures/shops/<key>/): invented prices and stock in
the shape of the shop's own page, so the parsing is checked without the network or card data.
"""
import importlib.util
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import config, shops
from decklab.lib.shops import base, mtgmate

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
        self.assertEqual(list(shops.ADAPTERS), ["mtgmate"])
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


if __name__ == "__main__":
    unittest.main()
