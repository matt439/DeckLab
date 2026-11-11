"""Each day's shop reading of a queued card, kept 90 days (E5-S29's first slice).

Nothing here reaches the network: the shops are the fakes test_shops.py and
test_shops_two_shops.py use, and the snapshot files are in a temporary folder.
"""
import contextlib
import io
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from decklab.lib import shops
from decklab.lib.shops import gamesportal, history, mtgmate
from decklab.tests.test_shops import SOL_RING, Clock, FakeShop, entry, page, session
# The module, not its TestCase class: a class imported here would be collected and run twice.
from decklab.tests import test_shops_missing
from decklab.tests.test_shops_missing import plan
from decklab.tests.test_shops_two_shops import TwoShopTestCase

TZ = timezone(timedelta(hours=10))


def at(day, hour=3):
    return datetime(2026, 11, day, hour, tzinfo=TZ)


def reading(on, price, stock=1):
    return {"on": on, "at": f"{on}T03:00:00+10:00",
            "listings": [{"set": "40k", "number": "249", "finish": "nonfoil", "condition": "Regular",
                          "price": price, "stock": stock}]}


def taken(names, pages, day, previous=None, queued=None, hour=3):
    return shops.take(names, session=session(FakeShop(pages)), previous=previous, now=lambda: at(day, hour),
                      queued=queued)


class RecordTests(unittest.TestCase):
    def test_each_day_adds_a_reading_and_a_rerun_replaces_that_days(self):
        first = taken(["Sol Ring"], {"Sol%20Ring": SOL_RING}, 1)
        cheaper = page(entry("Sol Ring", "40k", "249", 400, 3))
        second = taken(["Sol Ring"], {"Sol%20Ring": cheaper}, 2, previous=first)
        again = taken(["Sol Ring"], {"Sol%20Ring": page(entry("Sol Ring", "40k", "249", 350, 1))}, 2,
                      previous=second, hour=9)
        readings = again["history"]["Sol Ring"]
        self.assertEqual([item["on"] for item in readings], ["2026-11-01", "2026-11-02"])
        self.assertEqual(readings[1]["listings"], [{"set": "40k", "number": "249", "finish": "nonfoil",
                                                "condition": "Regular", "language": "", "price": "3.50", "stock": 1}])
        self.assertNotIn("url", readings[0]["listings"][0], "only what a trend needs")

    def test_not_listed_is_a_reading_but_an_error_or_a_carried_name_adds_nothing(self):
        data = taken(["Sol Ring", "Nothing"], {"Sol%20Ring": SOL_RING}, 1)
        self.assertEqual(data["history"]["Nothing"][0]["listings"], [])
        broken = shops.take(["Sol Ring"], session=session(FakeShop({}, fail={"Sol%20Ring"})), previous=data,
                            now=lambda: at(2))
        self.assertEqual([item["on"] for item in broken["history"]["Sol Ring"]], ["2026-11-01"])
        cards = {"Sol Ring": {"status": "ok", "at": at(3).isoformat(), "listings": [], "carried": True}}
        kept = history.record(data, cards, ["Sol Ring"], date(2026, 11, 3))
        self.assertEqual([item["on"] for item in kept["Sol Ring"]], ["2026-11-01"])

    def test_readings_older_than_90_days_and_names_off_the_queue_go(self):
        previous = {"history": {"Sol Ring": [reading("2026-08-04", "5.00"), reading("2026-08-05", "4.00")],
                                "Bought Already": [reading("2026-11-01", "1.00")]}}
        kept = history.record(previous, {}, ["sol ring"], date(2026, 11, 2))
        self.assertEqual(list(kept), ["sol ring"])
        self.assertEqual([item["on"] for item in kept["sol ring"]], ["2026-08-05"])
        self.assertEqual(history.record(previous, {}, [], date(2026, 11, 2)), {})

    def test_a_queued_name_the_run_did_not_reach_keeps_its_history_unchanged(self):
        previous = {"cards": {}, "history": {"Not Reached": [reading("2026-11-01", "2.00")],
                                             "Sol Ring": [reading("2026-11-01", "4.50")]}}
        clock = Clock()
        data = shops.take(["Sol Ring", "Not Reached"], session=session(FakeShop({"Sol%20Ring": SOL_RING}), clock),
                          previous=previous, budget=100, now=lambda: at(2))
        self.assertEqual(data["cards"]["Not Reached"]["status"], "error", "no carried entry: unknown this time")
        self.assertEqual(data["history"]["Not Reached"], previous["history"]["Not Reached"])
        self.assertEqual([item["on"] for item in data["history"]["Sol Ring"]], ["2026-11-01", "2026-11-02"])

    def test_history_keys_keep_the_queues_spelling(self):
        previous = {"history": {"SOL RING": [reading("2026-11-01", "4.50")]}}
        cards = {"sol ring": {"status": "ok", "at": at(2).isoformat(), "listings": []}}
        kept = history.record(previous, cards, ["Sol Ring"], date(2026, 11, 2))
        self.assertEqual(list(kept), ["Sol Ring"])
        self.assertEqual([item["on"] for item in kept["Sol Ring"]], ["2026-11-01", "2026-11-02"])

    def test_the_lowest_counts_only_days_a_copy_was_in_stock(self):
        days = [reading("2026-11-01", "4.00", 2), reading("2026-11-02", "2.50", 0), reading("2026-11-03", "4.00", 1)]
        answer = history.report("Sol Ring", [(mtgmate.ADAPTER, {"history": {"Sol Ring": days}})], shops.pick)
        self.assertEqual([day["lowest"] for day in answer["shops"][0]["days"]], [True, False, True])
        none_in_stock = [reading("2026-11-01", "4.00", 0)]
        answer = history.report("Sol Ring", [(mtgmate.ADAPTER, {"history": {"Sol Ring": none_in_stock}})], shops.pick)
        self.assertEqual([day["lowest"] for day in answer["shops"][0]["days"]], [False])

    def test_a_name_read_but_not_queued_keeps_no_history(self):
        data = taken(["Sol Ring", "Nothing"], {"Sol%20Ring": SOL_RING}, 1, queued=["Sol Ring"])
        self.assertEqual(list(data["history"]), ["Sol Ring"])

    def test_an_older_file_without_history_still_loads_and_starts_one(self):
        data = taken(["Sol Ring"], {"Sol%20Ring": SOL_RING}, 1)
        data.pop("history")
        self.assertEqual(history.of(data), {})
        self.assertEqual(history.find(data, "Sol Ring"), [])
        later = taken(["Sol Ring"], {"Sol%20Ring": SOL_RING}, 2, previous=data)
        self.assertEqual(len(later["history"]["Sol Ring"]), 1)
        self.assertEqual(history.find({"history": "broken"}, "Sol Ring"), [])


class NightlyHistoryTests(unittest.TestCase):
    setUp = test_shops_missing.NightlyMissingRefreshTests.setUp
    make_snapshot = test_shops_missing.NightlyMissingRefreshTests.make_snapshot
    refresh = test_shops_missing.NightlyMissingRefreshTests.refresh

    def test_saved_home_missing_names_are_read_but_never_kept(self):
        self.needs.names.return_value = plan(["Sol Ring", "New missing"])
        self.assertEqual(self.refresh(include_missing=True), 0)
        data = shops.load(self.path)
        self.assertEqual(set(data["cards"]), {"Sol Ring", "New missing"})
        self.assertEqual(list(shops.load_history(path=self.path)), ["Sol Ring"])

    def test_a_card_that_leaves_the_queue_loses_its_history_at_the_next_snapshot(self):
        self.assertEqual(self.refresh(), 0)
        self.assertIn("Sol Ring", shops.load_history(path=self.path))
        self.backend.load.return_value = self.make_snapshot([{"name": "Other"}])
        self.assertEqual(self.refresh(force=True), 0)
        self.assertEqual(list(shops.load_history(path=self.path)), ["Other"])

    def test_the_history_is_its_own_file_that_the_snapshot_readers_never_parse(self):
        self.assertEqual(self.refresh(), 0)
        self.assertNotIn("history", json.loads(self.path.read_text(encoding="utf-8")))
        self.assertNotIn("history", shops.load(self.path))
        self.assertEqual(shops.history_path(path=self.path).name, "shop.history.json")
        self.assertNotIn(chr(10), shops.history_path(path=self.path).read_text(encoding="utf-8"), "written compact")

    def test_an_emptied_queue_still_prunes_the_history(self):
        self.assertEqual(self.refresh(), 0)
        self.assertIn("Sol Ring", shops.load_history(path=self.path))
        self.backend.load.return_value = self.make_snapshot([])
        self.assertEqual(self.refresh(force=True), 0)
        self.assertIn("The purchase queue is empty; nothing to look up.", self.said)
        self.assertEqual(shops.load_history(path=self.path), {})
        self.assertEqual(self.shop.urls, [], "no shop asked")

    def test_an_emptied_queue_and_no_missing_names_still_prune_on_the_nightly_path(self):
        self.assertEqual(self.refresh(), 0)
        self.backend.load.return_value = self.make_snapshot([])
        self.needs.names.return_value = plan([])
        self.assertEqual(self.refresh(force=True, include_missing=True), 0)
        self.assertEqual(shops.load_history(path=self.path), {})


class CommandTests(TwoShopTestCase):
    def write(self, adapter, readings):
        shops._write({"version": 1, "shop": adapter.name, "cards": {}, "history": {"Sol Ring": readings}},
                     shops.snapshot_path(adapter))

    def run_command(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(shops.main(["history", *argv]), 0)
        return out.getvalue()

    def test_prints_each_shops_days_in_order_with_the_lowest_marked(self):
        self.write(mtgmate.ADAPTER, [reading("2026-11-02", "4.50", 2), reading("2026-11-01", "4.00", 3)])
        self.write(gamesportal.ADAPTER, [reading("2026-11-01", "3.00", 1), reading("2026-11-02", "3.50", 0)])
        lines = self.run_command("sol ring").splitlines()
        self.assertEqual(lines[0], "MTGMate: 2 days")
        self.assertEqual(lines[1], "  2026-11-01  A$4.00, 3 in stock (40K 249 nonfoil; Condition unknown, language unknown)  lowest in stock")
        self.assertEqual(lines[2], "  2026-11-02  A$4.50, 2 in stock (40K 249 nonfoil; Condition unknown, language unknown)")
        self.assertEqual(lines[4], "  2026-11-01  A$3.00, in stock (40K 249 nonfoil; Condition unknown, language unknown)  lowest in stock",
                         "Games Portal says only in stock or not")
        self.assertEqual(lines[5], "  2026-11-02  A$3.50, out of stock (40K 249 nonfoil; Condition unknown, language unknown)")

    def test_json_and_one_shop_and_no_history(self):
        self.write(mtgmate.ADAPTER, [reading("2026-11-01", "4.00", 3)])
        answer = json.loads(self.run_command("Sol Ring", "--shop", "mtgmate", "--json"))
        self.assertEqual([shop["shop"] for shop in answer["shops"]], ["MTGMate"])
        day = answer["shops"][0]["days"][0]
        self.assertEqual((day["on"], day["price"], day["stock"], day["lowest"]), ("2026-11-01", "4.00", 3, True))
        self.assertEqual(self.run_command("Sol Ring", "--shop", "gamesportal").strip(),
                         "Games Portal: no history for Sol Ring")

    def test_it_never_asks_a_shop(self):
        with mock.patch.object(shops.Session, "listings", side_effect=AssertionError("no network")):
            self.assertIn("no history", self.run_command("Sol Ring"))


if __name__ == "__main__":
    unittest.main()
