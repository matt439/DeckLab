"""Nightly queue/missing integration over fake shops and disposable inventory/cache.

No configured card cache, database, retailer, job or server is used. The domain
missing-name helper is replaced here; its counting proof has separate fixtures.
"""
import copy
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from decklab import lib
from decklab.lib import inventory, shops
from decklab.lib.inventory.model import Inventory, QUEUE_FIELDS, Sheet, WatchRow
from decklab.tests.test_shops import Clock, FakeShop, SOL_RING, entry, page, session

NOW = datetime(2026, 10, 28, 8, tzinfo=timezone.utc)
NOTICES = {
    "ready": None,
    "partial": "Some saved home decks could not be counted; only confirmed missing names were added.",
    "unavailable": "Saved home missing names could not be confirmed; the purchase queue is unchanged.",
    "over_limit": "Saved home missing names exceed the snapshot limit; the purchase queue is unchanged.",
}


def plan(names, status="ready"):
    return types.SimpleNamespace(names=tuple(names), status=status)


class NightlyMissingRefreshTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "shop.json"
        self.queue = [{"name": "Sol Ring", "quantity": "2", "printing": "any", "notes": "Fixture intent"}]
        self.snapshot = self.make_snapshot(self.queue)
        self.backend = types.SimpleNamespace(load=mock.Mock(return_value=self.snapshot))
        self.needs = types.SimpleNamespace(names=mock.Mock(return_value=plan(["Sol Ring", "New missing"])), NOTICES=NOTICES)
        self.lock = mock.Mock(return_value=77)
        self.unlock = mock.Mock()
        for patcher in (mock.patch.object(shops, "SNAPSHOT", self.path),
                        mock.patch.object(shops, "_now", return_value=NOW),
                        mock.patch.object(shops, "_fetch", side_effect=AssertionError("No real retailer")),
                        mock.patch.object(shops, "_lock", self.lock), mock.patch.object(shops, "_unlock", self.unlock),
                        mock.patch.object(inventory, "backend", return_value=self.backend),
                        mock.patch.object(lib, "shop_needs", self.needs, create=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_snapshot(self, queue):
        sheet = Sheet("fixture/watchlist", QUEUE_FIELDS, tuple(WatchRow.make(row) for row in queue), exists=True)
        return Inventory("fixture-revision", watchlist=sheet)

    def refresh(self, **kwargs):
        self.said = []
        self.shop = FakeShop({"Sol%20Ring": SOL_RING})
        return shops.refresh(say=self.said.append, session=session(self.shop), progress=False, **kwargs)

    def test_default_refresh_remains_queue_only_without_any_optional_proof(self):
        self.needs.names.side_effect = AssertionError("Default requested missing names")
        self.assertEqual(self.refresh(), 0)
        self.needs.names.assert_not_called()
        self.assertEqual(set(shops.load(self.path)["cards"]), {"Sol Ring"})

    def test_manual_dry_run_and_snapshot_do_not_opt_into_missing_names(self):
        args = types.SimpleNamespace(dry_run=True, force=False)
        with mock.patch("builtins.print"), mock.patch.object(shops, "take", side_effect=AssertionError("Dry-run fetched")):
            self.assertEqual(shops._snapshot(args), 0)
        self.needs.names.assert_not_called()
        args.dry_run = False
        with mock.patch.object(shops, "refresh", return_value=0) as refresh:
            self.assertEqual(shops._snapshot(args), 0)
        self.assertNotIn("include_missing", refresh.call_args.kwargs)

    def test_nightly_explicitly_opts_in_with_the_same_global_budget(self):
        with mock.patch.object(shops, "refresh", return_value=0) as refresh:
            self.assertEqual(shops.nightly(lambda words: None), 0)
        self.assertEqual(refresh.call_args.kwargs["budget"], 2700)
        self.assertIs(refresh.call_args.kwargs["include_missing"], True)
        self.assertIs(refresh.call_args.kwargs["progress"], False)

    def test_queue_and_missing_proof_capture_one_exact_snapshot_and_release_own_pin(self):
        order = []

        def names(queue, snapshot):
            self.assertTrue(inventory.is_pinned())
            self.assertIs(snapshot, self.snapshot)
            self.assertIs(inventory.current(), self.snapshot)
            self.assertEqual(queue[0]["notes"], "Fixture intent")
            order.append("planned")
            return plan(["Sol Ring", "New missing"])

        self.needs.names.side_effect = names
        shop = FakeShop({"Sol%20Ring": SOL_RING})

        def fetch(url):
            self.assertEqual(order[0], "planned")
            self.assertFalse(inventory.is_pinned())
            order.append("request")
            return shop(url)

        self.assertEqual(shops.refresh(include_missing=True, say=lambda words: None, progress=False,
                                      session=shops.Session(fetch=fetch, clock=Clock(), sleep=lambda seconds: None)), 0)
        self.backend.load.assert_called_once()
        self.needs.names.assert_called_once()
        self.assertEqual(set(shops.load(self.path)["cards"]), {"Sol Ring", "New missing"})

    def test_existing_pin_is_used_by_queue_and_helper_and_survives_requests(self):
        original = self.make_snapshot([{"name": "Caller queue"}])
        self.needs.names.return_value = plan(["Caller queue"])
        with inventory.pinned(original):
            self.assertEqual(self.refresh(include_missing=True), 0)
            self.assertIs(inventory.current(), original)
        self.backend.load.assert_not_called()
        self.assertEqual(self.needs.names.call_args.args[0][0]["name"], "Caller queue")
        self.assertIs(self.needs.names.call_args.args[1], original)

    def test_standalone_queue_keeps_its_old_one_load_and_leaves_no_pin(self):
        result = shops._queue()
        self.assertEqual(result[0]["name"], "Sol Ring")
        self.backend.load.assert_called_once()
        self.assertFalse(inventory.is_pinned())

    def test_early_fresh_cache_skips_helper_lock_and_all_retailer_work(self):
        fresh = {"version": 1, "cards": {}, "fetched_at": (NOW - timedelta(hours=1)).isoformat()}
        shops._write(fresh, self.path)
        self.assertEqual(self.refresh(include_missing=True), 0)
        self.needs.names.assert_not_called()
        self.lock.assert_not_called()
        self.assertEqual(self.shop.urls, [])
        self.assertIn("nothing fetched", self.said[-1])

    def test_writer_finishing_before_lock_is_rechecked_without_missing_scan_or_fetch(self):
        fresh = {"version": 1, "cards": {"Other": {}}, "fetched_at": NOW.isoformat()}
        shops._write(fresh, self.path)
        before = self.path.read_bytes()
        with mock.patch.object(shops, "load", side_effect=[None, fresh]) as load, \
                mock.patch.object(shops, "_write", side_effect=AssertionError("Overwrote another run")):
            self.assertEqual(self.refresh(include_missing=True), 0)
        self.assertEqual(load.call_count, 2)
        self.needs.names.assert_not_called()
        self.assertEqual(self.shop.urls, [])
        self.unlock.assert_called_once_with(77)
        self.assertEqual(self.path.read_bytes(), before)

    def test_force_rechecks_cache_for_carried_history_but_still_fetches(self):
        old = {"version": 1, "cards": {}, "fetched_at": (NOW - timedelta(days=2)).isoformat()}
        latest = {"version": 1, "cards": {}, "fetched_at": NOW.isoformat()}
        with mock.patch.object(shops, "load", side_effect=[old, latest]), \
                mock.patch.object(shops, "take", wraps=shops.take) as take:
            self.assertEqual(self.refresh(include_missing=True, force=True), 0)
        self.assertIs(take.call_args.kwargs["previous"], latest)
        self.needs.names.assert_called_once()
        self.assertTrue(self.shop.urls)

    def test_one_global_oldest_first_and_take_share_the_frozen_union(self):
        with mock.patch.object(shops, "oldest_first", wraps=shops.oldest_first) as oldest, \
                mock.patch.object(shops, "take", wraps=shops.take) as take:
            self.assertEqual(self.refresh(include_missing=True, budget=2700), 0)
        oldest.assert_called_once()
        take.assert_called_once()
        self.assertIsInstance(oldest.call_args.args[0], tuple)
        self.assertIsInstance(take.call_args.args[0], tuple)
        self.assertEqual(take.call_args.args[0], ("Sol Ring", "New missing"))
        self.assertEqual(take.call_args.kwargs["budget"], 2700)

    def test_ordinary_optional_failure_keeps_queue_and_never_logs_private_error_text(self):
        self.needs.names.side_effect = ValueError("private user2/deck title and notes")
        self.assertEqual(self.refresh(include_missing=True), 0)
        self.assertEqual(set(shops.load(self.path)["cards"]), {"Sol Ring"})
        self.assertIn(shops.MISSING_UNAVAILABLE, self.said)
        self.assertNotIn("private", " ".join(self.said))

    def test_partial_and_over_limit_notices_are_fixed_and_keep_the_supplied_plan(self):
        for status, names in (("partial", ["Sol Ring", "Confirmed only"]), ("over_limit", ["Sol Ring"])):
            with self.subTest(status=status):
                self.needs.names.return_value = plan(names, status)
                self.assertEqual(self.refresh(include_missing=True, force=True), 0)
                self.assertEqual(set(shops.load(self.path)["cards"]), set(names))
                self.assertIn(NOTICES[status], self.said)

    def test_queue_over_limit_is_never_truncated_on_optional_fallback(self):
        names = tuple(f"Queued {index}" for index in range(shops.MAX_SNAPSHOT_NAMES + 1))
        queued = [{"name": name} for name in names]
        self.needs.names.return_value = plan(names, "over_limit")
        with mock.patch.object(shops, "_queue", return_value=queued), \
                mock.patch.object(shops, "take", wraps=shops.take) as take:
            self.assertEqual(self.refresh(include_missing=True, budget=0), 1)
        self.assertEqual(take.call_args.args[0], names)
        self.assertEqual(len(shops.load(self.path)["cards"]), len(names))
        self.assertIn(NOTICES["over_limit"], self.said)

    def test_empty_queue_still_allows_confirmed_missing_names(self):
        self.backend.load.return_value = self.make_snapshot([])
        self.needs.names.return_value = plan(["Confirmed missing"])
        self.assertEqual(self.refresh(include_missing=True), 0)
        self.assertEqual(set(shops.load(self.path)["cards"]), {"Confirmed missing"})

    def test_empty_default_queue_and_empty_failed_optional_scan_fetch_nothing(self):
        self.backend.load.return_value = self.make_snapshot([])
        self.assertEqual(self.refresh(), 0)
        self.assertEqual(self.shop.urls, [])
        self.needs.names.return_value = plan([], "unavailable")
        self.assertEqual(self.refresh(include_missing=True), 0)
        self.assertEqual(self.shop.urls, [])
        self.assertIn(NOTICES["unavailable"], self.said)

    def test_queue_failure_keeps_exit_two_and_never_counts_or_fetches(self):
        for error in (inventory.Unavailable("fixture down"), ValueError("fixture bad queue")):
            with self.subTest(error=type(error).__name__), mock.patch.object(shops, "_queue", side_effect=error):
                self.assertEqual(self.refresh(include_missing=True), 2)
                self.needs.names.assert_not_called()
                self.assertEqual(self.shop.urls, [])

    def test_busy_lock_never_starts_optional_count_or_requests(self):
        self.lock.return_value = None
        self.assertEqual(self.refresh(include_missing=True), 1)
        self.needs.names.assert_not_called()
        self.assertEqual(self.shop.urls, [])
        self.unlock.assert_not_called()

    def test_cancellation_is_not_an_optional_failure_and_releases_lock_and_pin(self):
        self.needs.names.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.refresh(include_missing=True)
        self.unlock.assert_called_once_with(77)
        self.assertFalse(inventory.is_pinned())

    def test_queue_front_name_stays_the_cache_key_and_match_remains_in_stock(self):
        front = "Fire"
        self.backend.load.return_value = self.make_snapshot([{"name": front, "printing": "any"}])
        self.needs.names.return_value = plan([front])
        shop = FakeShop({front: page(entry(front, "mh2", "290", 250, 4))})
        self.assertEqual(shops.refresh(include_missing=True, say=lambda words: None, session=session(shop)), 0)
        data = shops.load(self.path)
        self.assertEqual(set(data["cards"]), {front})
        self.assertEqual(shops.match({"name": front, "printing": "any"}, data)["status"], "in_stock")

    def test_budget_carries_original_queue_front_timestamp_from_latest_snapshot(self):
        front, at = "Fire", "2026-10-20T01:02:03+00:00"
        self.backend.load.return_value = self.make_snapshot([{"name": front, "printing": "any"}])
        self.needs.names.return_value = plan([front, "New missing"])
        previous = {"version": 1, "fetched_at": at, "cards": {front: {"status": "ok", "at": at,
                    "listings": [{"set": "mh2", "number": "290", "finish": "nonfoil", "price": "2.50",
                                  "stock": 4, "url": shops.name_url(front)}]}}}
        shops._write(previous, self.path)
        before = copy.deepcopy(previous)
        self.assertEqual(self.refresh(include_missing=True, budget=90), 0)
        data = shops.load(self.path)
        shown = shops.match({"name": front, "printing": "any"}, data)
        self.assertEqual((shown["status"], shown["carried"], shown["fetched_at"]), ("in_stock", True, at))
        self.assertEqual(previous, before)
        self.assertTrue(data["cards"]["Fire"]["carried"])
        self.assertFalse(data["cards"]["New missing"].get("carried"))
