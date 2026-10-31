"""The nightly snapshot at two shops, MTGMate and Games Portal (E5-S08, decided 2026-10-31).

Each shop has its own file, lock and failures, the shops are read side by side within one
budget, and Shopping's and deck Prices' answers list both. Nothing here reaches the network:
both shops are fakes serving saved synthetic pages (decklab/tests/fixtures/shops/).
"""
import contextlib
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import shops
from decklab.lib.api import shop_missing_prices, shop_prices
from decklab.lib.shops import gamesportal, mtgmate
from decklab.tests.test_shop_adapters import SavedShop
from decklab.tests.test_shops import SOL_RING, Clock, FakeShop
from decklab.tests.test_shops import session as mtgmate_session

GP = gamesportal.ADAPTER


def gp_session(pages=None, fail=False):
    shop, clock = SavedShop(GP, {"Sol Ring": "sol-ring.html"} if pages is None else pages), Clock()

    def fetch(url):
        if fail:
            shop.urls.append(url)
            raise shops.ShopError("Games Portal couldn't be reached (TimeoutError)")
        return shop(url)
    return shop, shops.Session(fetch=fetch, sleep=clock.sleep, clock=clock, adapter=GP)


class TwoShopTestCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "shops" / "mtgmate.json"
        for patcher in (mock.patch.object(shops, "SNAPSHOT", self.path),
                        mock.patch.object(shops, "_fetch", side_effect=AssertionError("no network")),
                        mock.patch.object(shops, "_queue", return_value=[{"name": "Sol Ring"}, {"name": "Nothing Such"}])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_both(self, gp_fail=False, **options):
        self.mtg = FakeShop({"Sol%20Ring": SOL_RING})
        self.gp, gp = gp_session(fail=gp_fail)
        said = []
        code = shops.refresh_shops(say_for=lambda adapter: lambda words: said.append((adapter.key, words)),
                                   sessions={"mtgmate": mtgmate_session(self.mtg), "gamesportal": gp}, **options)
        return code, said


class FilesAndLocksTests(TwoShopTestCase):
    def test_both_shops_are_snapshot_shops_each_with_its_own_file_and_lock(self):
        self.assertEqual([adapter.key for adapter in shops.SNAPSHOT_ADAPTERS], ["mtgmate", "gamesportal"])
        self.assertEqual(shops.snapshot_path(), self.path)
        self.assertEqual(shops.snapshot_path(GP), self.path.with_name("mtgmate.gamesportal.json"))
        self.assertEqual(shops._lock_path(GP).name, "gamesportal.lock")
        self.assertEqual(shops._lock_path().name, "mtgmate.lock")
        held = shops._lock(mtgmate.ADAPTER)
        try:
            other = shops._lock(GP)
            self.assertIsNotNone(other, "one shop's run never blocks the other's")
            shops._unlock(other)
        finally:
            shops._unlock(held)

    def test_the_real_files_are_one_a_shop(self):
        with mock.patch.object(shops, "SNAPSHOT", None), mock.patch.dict("os.environ", {shops.SNAPSHOT_ENV: ""}):
            self.assertEqual(shops.snapshot_path(GP).name, "gamesportal.json")
            self.assertEqual(shops.snapshot_path().name, "mtgmate.json")
            self.assertEqual(shops.snapshot_path(GP).parent, shops.snapshot_path().parent)

    def test_a_file_naming_another_shop_is_never_read_as_this_ones(self):
        shops._write({"version": 1, "shop": "MTGMate", "cards": {}}, shops.snapshot_path(GP))
        self.assertIsNone(shops.load(adapter=GP))
        self.assertIsNotNone(shops.load(shops.snapshot_path(GP)))


class SnapshotTests(TwoShopTestCase):
    def test_one_run_saves_each_shops_listings_in_its_own_file(self):
        code, said = self.run_both()
        self.assertEqual(code, 0)
        mtg, gp = shops.load(adapter=mtgmate.ADAPTER), shops.load(adapter=GP)
        self.assertEqual((mtg["shop"], gp["shop"]), ("MTGMate", "Games Portal"))
        self.assertEqual(mtg["cards"]["Sol Ring"]["listings"][0]["url"].split("/cards/")[0], "https://www.mtgmate.com.au")
        self.assertTrue(all(item["url"].startswith("https://gamesportal.com.au/")
                            for item in gp["cards"]["Sol Ring"]["listings"]))
        self.assertEqual(gp["cards"]["Nothing Such"]["status"], "not_listed")
        # each shop asked its own robots.txt first, then one request a name
        self.assertEqual(self.gp.urls[0], "https://gamesportal.com.au/robots.txt")
        self.assertEqual(len(self.gp.urls), 3)
        self.assertEqual(self.mtg.urls[0], "https://www.mtgmate.com.au/robots.txt")
        self.assertIn(("gamesportal", next(words for key, words in said if key == "gamesportal"
                                           and words.startswith("Looking up"))), said)
        self.assertTrue(any("on Games Portal" in words for key, words in said if key == "gamesportal"))

    def test_one_shop_down_leaves_its_prices_unknown_and_the_other_saved(self):
        code, _ = self.run_both(gp_fail=True)
        self.assertEqual(code, 1, "every Games Portal name unknown")
        gp, mtg = shops.load(adapter=GP), shops.load(adapter=mtgmate.ADAPTER)
        self.assertTrue(all(entry["status"] == "error" for entry in gp["cards"].values()))
        self.assertEqual(mtg["cards"]["Sol Ring"]["status"], "ok")
        shown = shops.match({"name": "Sol Ring", "printing": "any"}, gp)
        self.assertEqual((shown["shop"], shown["status"], shown["price_aud"]), ("Games Portal", "unknown", None))
        self.assertEqual(shops.match({"name": "Sol Ring", "printing": "any"}, mtg)["status"], "in_stock")

    def test_an_exception_at_one_shop_is_its_own(self):
        errors = []
        with mock.patch.object(GP, "parse_name_page", side_effect=RuntimeError("page changed oddly")):
            code, _ = self.run_both(on_error=lambda adapter, error: errors.append((adapter.key, str(error))))
        self.assertEqual(code, 1)
        self.assertEqual(errors, [("gamesportal", "page changed oddly")])
        self.assertEqual(shops.load(adapter=mtgmate.ADAPTER)["cards"]["Sol Ring"]["status"], "ok")
        self.assertIsNone(shops.load(adapter=GP))

    def test_a_fresh_shop_waits_while_a_due_one_is_read(self):
        self.run_both()
        before = shops.snapshot_path(GP).read_bytes()
        shops.snapshot_path().unlink()
        code, said = self.run_both()
        self.assertEqual(code, 0)
        self.assertEqual(self.gp.urls, [], "Games Portal's snapshot is less than a day old")
        self.assertEqual(shops.snapshot_path(GP).read_bytes(), before)
        self.assertTrue(self.mtg.urls)
        self.assertTrue(any("nothing fetched" in words for key, words in said if key == "gamesportal"))


class NightlyTests(unittest.TestCase):
    def test_the_shops_run_side_by_side_each_within_the_one_budget(self):
        both = threading.Barrier(2, timeout=10)
        calls = []

        def refresh(**options):
            both.wait()             # only returns once the other shop's run has started too
            calls.append((options["adapter"].key, options["budget"], options["include_missing"], options["progress"],
                          threading.current_thread().name))
            return 0
        with mock.patch.object(shops, "refresh", side_effect=refresh):
            self.assertEqual(shops.nightly(lambda words: None), 0)
        self.assertEqual(sorted(call[:4] for call in calls),
                         [("gamesportal", shops.NIGHTLY_BUDGET, True, False), ("mtgmate", shops.NIGHTLY_BUDGET, True, False)])
        self.assertEqual({call[4] for call in calls}, {"shop-mtgmate", "shop-gamesportal"})
        self.assertEqual(shops.NIGHTLY_BUDGET, 45 * 60, "side by side: the night's shop step stays at 45 minutes")

    def test_each_shops_words_are_logged_under_its_name(self):
        logged = []

        def refresh(**options):
            options["say"](f"hello from {options['adapter'].key}")
            if options["adapter"].key == "gamesportal":
                raise RuntimeError("broken page")
            return 0
        with mock.patch.object(shops, "refresh", side_effect=refresh):
            self.assertEqual(shops.nightly(logged.append), 0)
        self.assertIn("Nightly: MTGMate prices: hello from mtgmate", logged)
        self.assertIn("Nightly: Games Portal prices: hello from gamesportal", logged)
        self.assertIn("Nightly: Games Portal prices failed: RuntimeError: broken page", logged)


class CommandTests(TwoShopTestCase):
    def test_snapshot_reads_every_shop_unless_one_is_named(self):
        seen = []
        with mock.patch.object(shops, "refresh", side_effect=lambda **options: seen.append(options["adapter"].key) or 0), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(shops.main(["snapshot"]), 0)
            self.assertEqual(sorted(seen), ["gamesportal", "mtgmate"])
            seen.clear()
            self.assertEqual(shops.main(["snapshot", "--shop", "gamesportal"]), 0)
            self.assertEqual(seen, ["gamesportal"])

    def test_show_puts_both_shops_beside_each_row(self):
        self.run_both()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(shops.main(["show"]), 0)
        text = out.getvalue()
        self.assertIn("MTGMate snapshot of", text)
        self.assertIn("Games Portal snapshot of", text)
        line = next(line for line in text.splitlines() if line.startswith("#1 Sol Ring"))
        self.assertIn("MTGMate: A$4.50, 2 in stock", line)
        self.assertIn("Games Portal: A$3.00, in stock", line, "Games Portal says only available, never how many")


class ApiTests(TwoShopTestCase):
    def setUp(self):
        super().setUp()
        self.run_both()

    def test_queue_rows_carry_both_shops_with_their_own_fetch_times(self):
        answer = {"to_buy": [{"name": "Sol Ring", "printing": "any", "state": "waiting_for_stock"}]}
        shop_prices.enrich(answer)
        self.assertEqual([summary["shop"] for summary in answer["shop_snapshots"]], ["MTGMate", "Games Portal"])
        self.assertTrue(all(summary["fetched_at"] for summary in answer["shop_snapshots"]))
        self.assertEqual(answer["shop_snapshot"]["shop"], "MTGMate")
        row = answer["to_buy"][0]
        self.assertEqual([(shown["shop"], shown["status"]) for shown in row["shop_snapshots"]],
                         [("MTGMate", "in_stock"), ("Games Portal", "in_stock")])
        self.assertEqual(row["shop_snapshot"], row["shop_snapshots"][0])
        self.assertTrue(all(shown["back_in_stock"] for shown in row["shop_snapshots"]))

    def test_a_shop_whose_run_failed_shows_unknown_beside_the_other(self):
        self.run_both(gp_fail=True, force=True)
        answer = {"to_buy": [{"name": "Sol Ring", "printing": "any", "state": "ready"}]}
        shop_prices.enrich(answer)
        gp = answer["to_buy"][0]["shop_snapshots"][1]
        self.assertEqual((gp["shop"], gp["status"], gp["price_aud"]), ("Games Portal", "unknown", None))
        self.assertEqual(answer["to_buy"][0]["shop_snapshots"][0]["status"], "in_stock")

    def test_a_missing_or_unreadable_file_leaves_only_that_shop_out(self):
        shops.snapshot_path().write_text("not json", encoding="utf-8")
        answer = {"to_buy": [{"name": "Sol Ring", "printing": "any"}]}
        shop_prices.enrich(answer)
        self.assertNotIn("shop_snapshot", answer)
        self.assertEqual([summary["shop"] for summary in answer["shop_snapshots"]], ["Games Portal"])
        self.assertEqual(answer["to_buy"][0]["shop_snapshots"][0]["shop"], "Games Portal")

    def test_a_queue_write_answer_gives_both_again(self):
        captured = shop_prices.capture()
        self.assertEqual(sorted(captured), ["gamesportal", "mtgmate"])
        every = shop_prices.for_row_shops({"name": "Sol Ring", "printing": "any"}, captured)
        self.assertEqual([shown["shop"] for shown in every], ["MTGMate", "Games Portal"])
        self.assertEqual(shop_prices.for_row({"name": "Sol Ring", "printing": "any"}, captured)["shop"], "MTGMate")

    def test_missing_cards_show_each_shops_cheapest_nonfoil(self):
        rows = [{"name": "Sol Ring"}, {"name": "Nothing Such"}]
        shop_missing_prices.enrich_shops(rows, shop_prices.by_shop(shop_prices.capture()), None)
        mtg, gp = rows[0]["shop_snapshots"]
        self.assertEqual((mtg["shop"], mtg["status"], mtg["price_aud"], mtg["stock"]), ("MTGMate", "in_stock", "4.50", 2))
        self.assertEqual((gp["shop"], gp["status"], gp["price_aud"], gp["stock"]), ("Games Portal", "in_stock", "3.00", 1))
        self.assertTrue(gp["url"].startswith("https://gamesportal.com.au/products/"))
        self.assertEqual(rows[0]["shop_snapshot"], mtg)
        self.assertEqual(rows[1]["shop_snapshots"][1]["status"], "not_listed")

    def test_a_shop_without_a_snapshot_is_not_checked_and_a_foreign_link_unknown(self):
        data = shops.load(adapter=GP)
        rows = [{"name": "Sol Ring"}]
        shop_missing_prices.enrich_shops(rows, {"gamesportal": data}, None)
        self.assertEqual([(shown["shop"], shown["status"]) for shown in rows[0]["shop_snapshots"]],
                         [("MTGMate", "not_checked"), ("Games Portal", "in_stock")])
        for item in data["cards"]["Sol Ring"]["listings"]:
            item["url"] = "https://example.com/products/sol-ring"
        rows = [{"name": "Sol Ring"}]
        shop_missing_prices.enrich_shops(rows, {"gamesportal": data}, None)
        self.assertEqual(rows[0]["shop_snapshots"][1]["status"], "unknown")
        self.assertIn("Games Portal", rows[0]["shop_snapshots"][1]["error"])
        # MTGMate's file read as Games Portal's is refused, never relabelled
        rows = [{"name": "Sol Ring"}]
        shop_missing_prices.enrich_shops(rows, {"gamesportal": shops.load(adapter=mtgmate.ADAPTER)}, None)
        self.assertEqual(rows[0]["shop_snapshots"][1]["status"], "unknown")

    def test_games_portal_links_are_only_its_own_listing_pages(self):
        good = ("https://gamesportal.com.au/products/sol-ring-0212?variant=123",
                "https://gamesportal.com.au/products/sol-ring-0212",
                "https://gamesportal.com.au/search?q=Sol%20Ring&type=product")
        bad = ("https://gamesportal.com.au/cart", "https://gamesportal.com.au/products/x?variant=1&b=2",
               "http://gamesportal.com.au/products/x", "https://www.mtgmate.com.au/cards/Sol_Ring/C16/272",
               "https://gamesportal.com.au/products/x#frag")
        for url in good:
            self.assertTrue(shop_missing_prices._url(url, "gamesportal"), url)
        for url in bad:
            self.assertFalse(shop_missing_prices._url(url, "gamesportal"), url)
        self.assertTrue(shop_missing_prices._url("https://www.mtgmate.com.au/cards/Sol_Ring/C16/272"))
        self.assertFalse(shop_missing_prices._url("https://gamesportal.com.au/products/sol-ring"))


if __name__ == "__main__":
    unittest.main()
