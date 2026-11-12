"""Operational diagnostics use disposable files/fake shops/transports, never live logs or pings."""
from collections import deque
from datetime import date, datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

from decklab.db import __main__ as cli, backup, check, conn as db, export, inv_inventory, migrate, nightly, visits
from decklab.lib import config, dbstatus, error_references as refs, operator_alerts as alerts, shops
from decklab.lib.api import error_reports
from decklab.lib.api.common import ApiError
from decklab.lib.shops import health


class DisposableOperations(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="decklab-observability-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.enterContext(mock.patch.object(config, "DATA", self.root))
        self.enterContext(mock.patch.dict(os.environ, {refs.PATH_ENV: str(self.root / "diagnostics/error-references.json")}))
        self.enterContext(mock.patch.object(shops, "SNAPSHOT", self.root / "shops/mtgmate.json"))
        self.enterContext(mock.patch.object(refs, "_received", deque()))
        self.enterContext(mock.patch.object(shops, "enabled_adapters", return_value=shops.SNAPSHOT_ADAPTERS))


class LogRotationTests(DisposableOperations):
    def test_database_log_rotates_and_huge_entries_stay_bounded(self):
        target = self.root / "logs/db.log"
        with mock.patch.object(db, "LOG_FILE", target), mock.patch.object(db, "LOG_MAX_BYTES", 160), \
                mock.patch.object(db, "LOG_BACKUPS", 2), mock.patch.object(db.sys, "stderr", io.StringIO()):
            for number in range(10):
                db.log(str(number) + "x" * 80)
            db.log("x" * 10000)
        files = sorted(target.parent.iterdir())
        self.assertEqual([path.name for path in files], ["db.log", "db.log.1", "db.log.2"])
        self.assertTrue(all(path.stat().st_size <= 160 for path in files))
        self.assertIn("[log entry truncated]", target.read_text(encoding="utf-8"))


class ShopHealthTests(DisposableOperations):
    def test_an_unreadable_optional_health_snapshot_does_not_skip_the_shop_refresh(self):
        said = []
        with mock.patch.object(shops, "load", side_effect=RuntimeError("PRIVATE_CACHE")), \
                mock.patch.object(shops, "refresh", return_value=0) as refresh:
            self.assertEqual(shops.refresh_shops((shops.ADAPTER,), say_for=lambda adapter: said.append,
                                                on_result=lambda *args: None), 0)
        refresh.assert_called_once()
        self.assertEqual(said, ["The previous shop-health snapshot could not be read.",
                                "The shop-health receipt could not be recorded."])

    def test_nightly_records_failed_shop_reads_without_changing_its_existing_success_exit(self):
        shops._write({"version": 1, "fetched_at": "2026-10-31", "cards": {
            "PRIVATE_CARD": {"status": "ok", "at": "2026-10-31", "listings": []}}}, shops.snapshot_path())
        for day in (1, 2, 3):
            moment = datetime(2026, 11, day, 3, 30, tzinfo=timezone.utc)
            def unreadable(**options):
                shops._write({"version": 1, "fetched_at": moment.isoformat(), "cards": {
                    "PRIVATE_CARD": {"status": "error", "at": moment.isoformat(), "error": "PRIVATE_MESSAGE"}},
                    "previous": {"PRIVATE_CARD": {"at": "2026-10-31"}}}, shops.snapshot_path())
                return 1
            with mock.patch.object(shops, "enabled_adapters", return_value=(shops.ADAPTER,)), \
                    mock.patch.object(shops, "_now", return_value=moment), mock.patch.object(shops, "refresh", side_effect=unreadable):
                self.assertEqual(shops.nightly(lambda text: None), 0)
        self.assertIn("3 nights in a row", health.warning())
        self.assertIn("2026-10-31", health.warning())
        self.assertNotIn("PRIVATE", health.path().read_text(encoding="utf-8"))

    def test_three_distinct_failed_nights_show_public_shop_and_last_read_date_only(self):
        for night in (date(2026, 11, 1), date(2026, 11, 1), date(2026, 11, 2)):
            health.record("mtgmate", "failed", night, "2026-10-31")
        self.assertEqual(health.read()["mtgmate"]["failed_nights"], 2)
        self.assertIsNone(health.warning())
        health.record("mtgmate", "failed", date(2026, 11, 3))
        self.assertIn("MTGMate", health.warning())
        self.assertIn("3 nights in a row", health.warning())
        self.assertIn("2026-10-31", health.warning())
        with mock.patch.object(shops, "enabled_adapters", return_value=()):
            self.assertIsNone(health.warning())

    def test_success_gaps_idle_and_unverified_checks_do_not_claim_consecutive_unreadable_nights(self):
        health.record("mtgmate", "failed", date(2026, 11, 1))
        health.record("mtgmate", "failed", date(2026, 11, 3))
        self.assertEqual(health.read()["mtgmate"]["failed_nights"], 1)
        health.record("mtgmate", "ok", date(2026, 11, 3), "2026-11-03")
        health.record("mtgmate", "failed", date(2026, 11, 3))
        self.assertEqual(health.read()["mtgmate"]["failed_nights"], 0)
        health.record("mtgmate", "unverified", date(2026, 11, 4))
        health.record("mtgmate", "failed", date(2026, 11, 5))
        self.assertEqual(health.read()["mtgmate"]["failed_nights"], 1)
        health.record("mtgmate", "idle", date(2026, 11, 6))
        self.assertEqual(health.read()["mtgmate"]["failed_nights"], 0)

    def test_snapshot_reduction_never_keeps_card_names_prices_or_error_messages(self):
        before = {"fetched_at": "2026-11-01", "cards": {"PRIVATE_CARD": {
            "status": "ok", "at": "2026-11-01T10:00:00+00:00", "listings": [{"price": 123.45}]}}}
        after = {"fetched_at": "2026-11-02", "cards": {"PRIVATE_CARD": {
            "status": "error", "at": "2026-11-02", "error": "PRIVATE_MESSAGE"}}}
        health.observe(shops.ADAPTER, 1, before, after, False, date(2026, 11, 2))
        raw = health.path().read_text(encoding="utf-8")
        for private in ("PRIVATE_CARD", "PRIVATE_MESSAGE", "123.45"):
            self.assertNotIn(private, raw)
        self.assertEqual(health.read()["mtgmate"]["last_read"], "2026-11-01")
        self.assertEqual(health.heartbeat_steps(date(2026, 11, 2)), {"shop_mtgmate": False})

    def test_unknown_health_is_not_reported_as_success_or_empty_healthy_history(self):
        health.path().parent.mkdir(parents=True)
        health.path().write_text("{damaged", encoding="utf-8")
        self.assertIn("cannot be verified", health.warning())
        self.assertEqual(health.heartbeat_steps(date(2026, 11, 2)), {"shop health": False})

    def test_shop_warning_is_never_read_for_a_member_or_outside_space_admin(self):
        snapshot = dbstatus._result()
        with mock.patch.object(dbstatus, "_snapshot", snapshot), mock.patch.object(health, "warning", return_value="Shop warning") as warn:
            for profile in ({"id": "user1", "role": "member", "space": "home"},
                            {"id": "user2", "role": "admin", "space": "user2"}):
                self.assertNotIn("Shop warning", json.dumps(dbstatus.view(profile)))
            warn.assert_not_called()
            with mock.patch.object(dbstatus, "_venv_reason", return_value=None):
                self.assertEqual(dbstatus.view({"id": "matt", "role": "admin", "space": "home"})["checks_warning"], "Shop warning")

    def test_database_status_prints_the_shop_health_warning(self):
        connection = mock.MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchone.side_effect = [(2,), (1,), (0, None)]
        output = io.StringIO()
        with mock.patch.object(db, "settings", return_value=dict(db.DEFAULTS)), \
                mock.patch.object(migrate, "status", return_value={"applied": [], "pending": []}), \
                mock.patch.object(db, "connect", return_value=connection), mock.patch.object(cli, "_personal_state", return_value="State"), \
                mock.patch.object(inv_inventory, "status_line", return_value="Inventory"), \
                mock.patch.object(inv_inventory, "decks_line", return_value="Decks"), \
                mock.patch.object(backup, "status", return_value="Backups"), \
                mock.patch.object(health, "warning", return_value="Shop readings failed; prices from 2026-10-31."), \
                mock.patch("sys.stdout", output):
            self.assertEqual(cli._status(SimpleNamespace(dbname=None)), 0)
        self.assertIn("WARNING: Shop readings failed; prices from 2026-10-31.", output.getvalue())


class ErrorReferenceTests(DisposableOperations):
    def test_records_and_admin_view_contain_only_whitelisted_operational_fields(self):
        body = {"reference": "a" * 32, "page": "deck", "type": "TypeError", "profile": "user3"}
        self.assertTrue(error_reports.report(json.dumps(body))["accepted"])
        with mock.patch.object(error_reports.guard, "viewer", return_value={"id": "matt", "role": "admin", "space": "home"}):
            found = error_reports.view()
        self.assertTrue(found["ready"])
        self.assertEqual(set(found["events"][0]), {"reference", "page", "type", "at"})
        self.assertNotIn("user3", json.dumps(found))
        with self.assertRaises(ApiError):
            error_reports.report(json.dumps({**body, "message": "PRIVATE_MESSAGE"}))
        for page in ("deck?id=private-deck", "PRIVATE_NAME", "/home/private/file.py"):
            with self.assertRaises(ApiError) as refused:
                error_reports.report(json.dumps({**body, "page": page}))
            self.assertEqual(refused.exception.status, 400)
        for viewer in (None, {"id": "user1", "role": "member", "space": "home"},
                       {"id": "user2", "role": "admin", "space": "user2"}):
            with mock.patch.object(error_reports.guard, "viewer", return_value=viewer), self.assertRaises(ApiError) as denied:
                error_reports.view()
            self.assertEqual(denied.exception.status, 403)

    def test_record_count_bytes_and_request_rate_are_bounded_and_unreadable_is_explicit(self):
        with mock.patch.object(refs, "MAX_EVENTS", 2), mock.patch.object(refs, "REPORTS_PER_MINUTE", 3):
            for value in ("a", "b", "c"):
                self.assertEqual(refs.record("deck", "Error", value * 32)[1], "stored")
            self.assertEqual([row["reference"] for row in refs.read()[0]], ["b" * 32, "c" * 32])
            self.assertEqual(refs.record("deck", "Error", "d" * 32)[1], "limited")
            self.assertLess(refs.path().stat().st_size, refs.MAX_BYTES)
        refs.path().write_text('{"events":[{"message":"PRIVATE"}]}', encoding="utf-8")
        self.assertEqual(refs.read(), ([], False))

    def test_server_context_discards_identifiers_queries_fragments_and_custom_error_names(self):
        class PRIVATE_TYPE(Exception):
            pass
        ref = refs.unexpected(PRIVATE_TYPE("PRIVATE_MESSAGE"), "/api/deck/private-name?id=private#private")
        events, ready = refs.read()
        self.assertTrue(ready)
        self.assertEqual(events[0]["reference"], ref)
        self.assertEqual((events[0]["page"], events[0]["type"]), ("deck", "Error"))
        self.assertNotIn("PRIVATE", json.dumps(events))


class HeartbeatTests(unittest.TestCase):
    def test_default_off_never_opens_a_connection(self):
        opener = mock.Mock()
        self.assertIsNone(alerts.notify({"nightly": True}, settings={}, opener=opener))
        opener.open.assert_not_called()

    def test_only_fixed_steps_and_binary_outcomes_leave_and_target_errors_are_never_logged(self):
        response = mock.MagicMock(status=204)
        response.__enter__.return_value = response
        opener = mock.Mock()
        opener.open.return_value = response
        settings = {"alerts": "https://monitor.example.com/private-token"}
        self.assertTrue(alerts.notify({"backup": True, "check": False, "PRIVATE_NAME": True, "export": "PRIVATE"},
                                     settings=settings, opener=opener))
        request = opener.open.call_args.args[0]
        self.assertEqual(json.loads(request.data), {"steps": {"backup": "ok", "check": "failed"}})
        self.assertEqual(opener.open.call_args.kwargs["timeout"], alerts.TIMEOUT)
        log = []
        opener.open.side_effect = OSError("private-token and PRIVATE_MESSAGE")
        self.assertFalse(alerts.notify({"watchdog": False}, settings=settings, opener=opener, log=log.append))
        self.assertEqual(log, ["The optional operator heartbeat could not be sent."])

    def test_nightly_reports_every_step_without_changing_database_result(self):
        ran = []
        def step(name, code=0):
            return lambda *args: ran.append(name) or code
        with mock.patch.object(backup, "run_backup", step("backup", 1)), \
                mock.patch.object(backup, "run_prune", step("prune")), \
                mock.patch.object(visits, "run_prune", step("visits")), \
                mock.patch.object(export, "run_export", step("export")), \
                mock.patch.object(check, "run", step("check")), \
                mock.patch.object(nightly, "_restore_check_if_due", step("restore check")), \
                mock.patch.object(nightly, "_shop_prices", step("shop prices")), \
                mock.patch.object(db, "log"), mock.patch.object(health, "heartbeat_steps", return_value={"shop_mtgmate": False}), \
                mock.patch.object(nightly, "_card_data", return_value=True), \
                mock.patch.object(alerts, "notify", return_value=False) as notify:
            self.assertEqual(nightly._run(), 1)
        self.assertEqual(ran, ["backup", "prune", "visits", "export", "check", "restore check", "shop prices"])
        self.assertEqual(notify.call_args.args[0], {**dict.fromkeys(ran, True), "backup": False,
                                                  "shop_mtgmate": False, "card data": True, "nightly": False})

    def test_shop_failures_remain_separate_from_successful_database_nightly(self):
        with mock.patch.object(nightly, "_step", return_value=True), mock.patch.object(db, "log"), \
                mock.patch.object(health, "heartbeat_steps", return_value={"shop_mtgmate": False}), \
                mock.patch.object(nightly, "_card_data", return_value=True), \
                mock.patch.object(alerts, "notify") as notify:
            self.assertEqual(nightly._run(), 0)
        self.assertTrue(notify.call_args.args[0]["nightly"])
        self.assertFalse(notify.call_args.args[0]["shop_mtgmate"])
