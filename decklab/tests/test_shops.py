"""MTGMate's daily purchase-queue snapshot (E5-S08) and its back-in-stock mark (E5-S19).

Nothing here reaches the network: the shop is a fake that serves fixed pages.
"""
import html
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from decklab.lib import shops
from decklab.lib.api import shop_prices

ROBOTS = """User-agent: *
Content-Signal: search=yes,ai-train=no,use=reference
Allow: /

User-agent: ClaudeBot
Disallow: /

User-agent: *
Disallow: /cards/search
Crawl-delay: 60
"""


def entry(name, set_code, number, price, quantity, finish="Nonfoil", condition="Regular"):
    suffix = ":foil" if finish != "Nonfoil" else ""
    return {"name": name, "price": price, "set_code": set_code, "quantity": quantity, "finish": finish,
            "condition": condition, "link_path": f"/cards/{name.replace(' ', '_')}/{set_code.upper()}/{number}{suffix}"}


def page(*entries):
    props = {"title": "Cards named", "cards": [], "uuid": {f"u{n}": item for n, item in enumerate(entries)}}
    return ('<html><div data-react-class="FilterableTable" data-react-props="'
            + html.escape(json.dumps(props), quote=True) + '"></div></html>')


SOL_RING = page(entry("Sol Ring", "c16", "272", 500, 0), entry("Sol Ring", "40k", "249", 450, 2),
                entry("Sol Ring (Borderless 1011)", "sld", "1011", 300, 1, finish="Foil"),
                entry("Sol Ring Token", "tc16", "1", 100, 5))
NO_MATCH = "<html><p>No matches for \"Nothing\"</p></html>"


class FakeShop:
    def __init__(self, pages, fail=()):
        self.pages, self.fail, self.urls = pages, set(fail), []

    def __call__(self, url):
        self.urls.append(url)
        if url.endswith("/robots.txt"):
            return ROBOTS
        path = url.split("/cards/", 1)[1]
        if path in self.fail:
            raise shops.ShopError("MTGMate couldn't be reached (TimeoutError)")
        return self.pages.get(path, NO_MATCH)


class Clock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


def session(shop, clock=None):
    clock = clock or Clock()
    return shops.Session(fetch=shop, sleep=clock.sleep, clock=clock)


class RobotsTests(unittest.TestCase):
    def test_both_star_groups_merge_so_search_is_disallowed_and_the_delay_kept(self):
        rules = shops.robots_rules(ROBOTS)
        self.assertEqual(rules[2], 60.0)
        self.assertTrue(shops.allowed("/cards/Sol%20Ring", rules))
        self.assertFalse(shops.allowed("/cards/search?q=sol", rules))

    def test_a_disallowed_name_page_is_never_fetched(self):
        shop = FakeShop({})
        rules = (["/cards/"], [], None)
        with mock.patch.object(shops, "robots_rules", return_value=rules):
            data = shops.take(["Sol Ring"], session=session(shop))
        self.assertEqual(data["cards"]["Sol Ring"]["status"], "error")
        self.assertIn("robots.txt", data["cards"]["Sol Ring"]["error"])
        self.assertEqual([url for url in shop.urls if "/cards/" in url], [])


class PageTests(unittest.TestCase):
    def test_listings_keep_the_name_and_its_variants_only(self):
        listings = shops.parse_name_page(SOL_RING, "Sol Ring")
        self.assertEqual([(item["set"], item["number"], item["finish"], item["price"], item["stock"])
                          for item in listings],
                         [("40k", "249", "nonfoil", "4.50", 2), ("c16", "272", "nonfoil", "5.00", 0),
                          ("sld", "1011", "foil", "3.00", 1)])
        self.assertEqual(listings[0]["url"], "https://www.mtgmate.com.au/cards/Sol_Ring/40K/249")

    def test_no_matches_is_an_empty_list_and_a_changed_page_an_error(self):
        self.assertEqual(shops.parse_name_page(NO_MATCH, "Nothing"), [])
        with self.assertRaises(shops.ShopError):
            shops.parse_name_page("<html>something else</html>", "Sol Ring")

    def test_a_double_faced_name_is_quoted_whole(self):
        self.assertEqual(shops.name_url("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki"),
                         "https://www.mtgmate.com.au/cards/Fable%20of%20the%20Mirror-Breaker%20%2F%2F%20Reflection%20of%20Kiki-Jiki")


class PickTests(unittest.TestCase):
    listings = shops.parse_name_page(SOL_RING, "Sol Ring")

    def test_any_printing_is_the_cheapest_nonfoil_in_stock(self):
        choice, stocked = shops.pick({"printing": "any"}, self.listings)
        self.assertEqual((choice["set"], choice["price"], stocked), ("40k", "4.50", 2))

    def test_exact_printing_answers_only_for_that_printing(self):
        choice, stocked = shops.pick({"printing": "exact", "set": "C16", "collector_number": "272"}, self.listings)
        self.assertEqual((choice["set"], choice["stock"], stocked), ("c16", 0, 0))
        none, _ = shops.pick({"printing": "exact", "set": "c16", "collector_number": "272", "finish": "foil"},
                             self.listings)
        self.assertIsNone(none)


class SnapshotTests(unittest.TestCase):
    def test_one_request_per_name_spaced_by_the_crawl_delay(self):
        shop, clock = FakeShop({"Sol%20Ring": SOL_RING}), Clock()
        data = shops.take(["Sol Ring", "Nothing"], session=session(shop, clock))
        self.assertEqual(len(shop.urls), 3)
        self.assertEqual(clock.slept, [60.0, 60.0])
        self.assertEqual(data["cards"]["Sol Ring"]["status"], "ok")
        self.assertEqual(data["cards"]["Nothing"]["status"], "not_listed")
        self.assertEqual(data["crawl_delay"], 60.0)

    def test_a_failure_leaves_the_price_unknown_and_three_stop_the_run(self):
        names = ["A", "B", "C", "D"]
        shop = FakeShop({}, fail=names)
        data = shops.take(names, session=session(shop))
        self.assertTrue(all(data["cards"][name]["status"] == "error" for name in names))
        self.assertEqual(len([url for url in shop.urls if "/cards/" in url]), 3)
        self.assertIn("Not checked", data["cards"]["D"]["error"])
        row = {"name": "A", "printing": "any", "state": "ready"}
        shown = shops.match(row, data)
        self.assertEqual((shown["status"], shown["price_aud"]), ("unknown", None))

    def test_a_waiting_row_found_in_stock_is_back_and_newly_in_stock(self):
        before = shops.take(["Sol Ring"], session=session(FakeShop({"Sol%20Ring": page(
            entry("Sol Ring", "40k", "249", 450, 0))})))
        after = shops.take(["Sol Ring"], session=session(FakeShop({"Sol%20Ring": SOL_RING})), previous=before)
        waiting = {"name": "Sol Ring", "printing": "any", "state": "waiting_for_stock"}
        shown = shops.match(waiting, after)
        self.assertEqual((shown["status"], shown["price_aud"], shown["stock"]), ("in_stock", "4.50", 2))
        self.assertTrue(shown["back_in_stock"])
        self.assertTrue(shown["newly_in_stock"])
        ready = shops.match({**waiting, "state": "ready"}, after)
        self.assertFalse(ready["back_in_stock"])
        self.assertFalse(shops.match(waiting, before)["back_in_stock"])

    def test_no_snapshot_claims_nothing_and_a_new_row_is_not_checked(self):
        self.assertIsNone(shops.match({"name": "Sol Ring"}, None))
        data = shops.take([], session=session(FakeShop({})))
        self.assertEqual(shops.match({"name": "Sol Ring", "state": "waiting_for_stock"}, data)["status"], "not_checked")

    def test_fresh_is_less_than_a_day_and_the_file_round_trips(self):
        now = datetime(2026, 10, 28, 3, 0, tzinfo=timezone.utc)
        data = {"version": 1, "cards": {}, "fetched_at": (now - timedelta(hours=2)).isoformat()}
        self.assertTrue(shops.fresh(data, now))
        self.assertFalse(shops.fresh(data, now + timedelta(hours=19)))
        self.assertFalse(shops.fresh(None, now))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shops" / "mtgmate.json"
            shops._write(data, path)
            self.assertEqual(shops.load(path), data)
            path.write_text("not json", encoding="utf-8")
            self.assertIsNone(shops.load(path))

    def test_queue_names_are_distinct_in_queue_order(self):
        self.assertEqual(shops.queue_names([{"name": "B"}, {"name": "a"}, {"name": "b"}, {"name": ""}]), ["B", "a"])


class RefreshTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "shops" / "mtgmate.json"
        for patcher in (mock.patch.object(shops, "SNAPSHOT", self.path),
                        mock.patch.object(shops, "_fetch", side_effect=AssertionError("no network")),
                        mock.patch.object(shops, "_queue", return_value=[{"name": "Sol Ring"}, {"name": "Sol Ring"}])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_saves_once_then_waits_a_day_unless_forced(self):
        said, shop = [], FakeShop({"Sol%20Ring": SOL_RING})
        self.assertEqual(shops.refresh(say=said.append, session=session(shop)), 0)
        self.assertEqual(shops.load(self.path)["cards"]["Sol Ring"]["status"], "ok")
        self.assertFalse(self.path.with_name("mtgmate.lock").exists())
        again = FakeShop({})
        self.assertEqual(shops.refresh(say=said.append, session=session(again)), 0)
        self.assertEqual(again.urls, [])
        self.assertIn("nothing fetched", said[-1])
        self.assertEqual(shops.refresh(force=True, say=said.append, session=session(again)), 0)
        self.assertEqual(shops.load(self.path)["cards"]["Sol Ring"]["status"], "not_listed")
        self.assertEqual(shops.load(self.path)["previous"]["Sol Ring"]["listings"][0]["set"], "40k")

    def test_too_many_names_for_the_night_fetch_nothing(self):
        said, shop = [], FakeShop({})
        self.assertEqual(shops.refresh(say=said.append, session=session(shop), max_names=0), 1)
        self.assertEqual(shop.urls, [])
        self.assertFalse(self.path.exists())

    def test_the_nightly_step_never_fails_the_night(self):
        logged = []
        with mock.patch.object(shops, "_queue", side_effect=RuntimeError("broken")):
            self.assertEqual(shops.nightly(logged.append), 0)
        self.assertIn("MTGMate prices failed: RuntimeError: broken", logged[-1])
        with mock.patch.object(shops, "refresh", return_value=1):
            self.assertEqual(shops.nightly(logged.append), 0)


class ApiTests(unittest.TestCase):
    def test_enrich_reads_only_the_cached_file(self):
        data = shops.take(["Sol Ring"], session=session(FakeShop({"Sol%20Ring": SOL_RING})))
        answer = {"to_buy": [{"name": "Sol Ring", "printing": "any", "state": "waiting_for_stock"},
                             {"name": "Other", "printing": "any", "state": "ready"}]}
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(shops, "_fetch", side_effect=AssertionError("no network")):
            path = Path(folder) / "mtgmate.json"
            shops._write(data, path)
            with mock.patch.object(shops, "SNAPSHOT", path):
                shop_prices.enrich(answer)
        self.assertEqual(answer["shop_snapshot"]["shop"], "MTGMate")
        self.assertTrue(answer["to_buy"][0]["shop_snapshot"]["back_in_stock"])
        self.assertEqual(answer["to_buy"][1]["shop_snapshot"]["status"], "not_checked")

    def test_without_a_snapshot_rows_say_nothing(self):
        answer = {"to_buy": [{"name": "Sol Ring"}]}
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(shops, "SNAPSHOT", Path(folder) / "none.json"):
            shop_prices.enrich(answer)
        self.assertIsNone(answer["shop_snapshot"])
        self.assertIsNone(answer["to_buy"][0]["shop_snapshot"])


if __name__ == "__main__":
    unittest.main()
