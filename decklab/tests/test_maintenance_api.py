"""Maintenance history uses synthetic rows and fake connectors, never configured PostgreSQL."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import unittest
from unittest import mock

from decklab.lib import feature_routes
from decklab.lib.api import guard, maintenance
from decklab.lib.api.common import ApiError

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
SETTINGS = {"stale_backup_hours": 36, "restore_check_days": 28}


def run(kind, number, hours=1, ok=True, *, finished=None):
    started = NOW - timedelta(hours=hours)
    return kind, number, started, finished if finished is not None else started + timedelta(minutes=1), ok


class FakeConnection:
    def __init__(self, recent=(), successful=(), now=NOW):
        self.recent, self.successful, self.now = recent, successful, now
        self.calls = []
        self.active = False
        self.transactions = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @contextmanager
    def transaction(self):
        self.transactions += 1
        self.active = True
        try:
            yield
        finally:
            self.active = False

    def execute(self, sql, params=None):
        if not self.active:
            raise AssertionError("All history statements need the same transaction")
        self.calls.append((sql, params))
        if sql.startswith("set transaction"):
            return SimpleNamespace()
        if sql == "select transaction_timestamp()":
            return SimpleNamespace(fetchone=lambda: (self.now,))
        if sql == maintenance.RECENT_SQL:
            return SimpleNamespace(fetchall=lambda: self.recent)
        if sql == maintenance.SUCCESS_SQL:
            return SimpleNamespace(fetchall=lambda: self.successful)
        raise AssertionError("Unexpected statement")


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(guard, "viewer", return_value={"id": "matt", "role": "admin"}))
        self.settings = self.enterContext(mock.patch.object(maintenance.db, "settings", return_value=SETTINGS))
        self.connection = FakeConnection()
        self.connect = self.enterContext(mock.patch.object(maintenance.db, "connect", return_value=self.connection))

    def job(self, kind="dump", recent=(), successful=(), settings=None, now=NOW):
        result = maintenance._project(recent, successful, settings or SETTINGS, now)
        return next(job for job in result["jobs"] if job["kind"] == kind)

    def refused(self, code, call=maintenance.maintenance_view):
        with self.assertRaises(ApiError) as caught:
            call()
        self.assertEqual(caught.exception.status, code)
        return caught.exception

    def test_named_admin_reads_one_consistent_app_transaction_with_bounded_safe_fields(self):
        self.connection.recent = [run(kind, i + 1) for i, kind in enumerate(maintenance.KINDS)]
        self.connection.successful = self.connection.recent
        result = maintenance.maintenance_view()
        self.assertTrue(result["available"])
        self.assertEqual(result["checked_at"], NOW.isoformat())
        self.assertEqual([job["kind"] for job in result["jobs"]], list(maintenance.KINDS))
        self.assertTrue(all(job["health"] == "success" for job in result["jobs"]))
        self.connect.assert_called_once_with("app", timeout=maintenance.pg.REQUEST_TIMEOUT, options=maintenance.pg.REQUEST_OPTIONS)
        self.assertEqual(self.connection.transactions, 1)
        self.assertFalse(self.connection.active)
        self.assertEqual(self.connection.calls[0], ("set transaction isolation level repeatable read, read only", None))
        self.assertEqual(self.connection.calls[2][1], (list(maintenance.KINDS), 5))
        self.assertEqual(self.connection.calls[3][1], (list(maintenance.KINDS), NOW, NOW))
        self.assertIn("partition by kind order by started_at desc, id desc", maintenance.RECENT_SQL)
        self.assertIn("order by kind, started_at desc, id desc", maintenance.SUCCESS_SQL)
        for sql, _ in self.connection.calls:
            self.assertTrue(sql.startswith(("select", "set transaction")))
            for secret_column in ("detail", "path", "bytes", "digests"):
                self.assertNotIn(secret_column, sql)
        for job in result["jobs"]:
            self.assertEqual(set(job["latest"]), {"started_at", "finished_at", "outcome"})

    def test_no_history_has_four_explicit_never_recorded_jobs(self):
        result = maintenance.maintenance_view()
        self.assertEqual(len(result["jobs"]), 4)
        for job in result["jobs"]:
            self.assertEqual((job["latest"], job["last_success"], job["recent"]), (None, None, []))
            self.assertEqual((job["health"], job["freshness"]), ("never", "never"))

    def test_members_unsigned_and_missing_selected_profiles_fail_before_configuration_or_database(self):
        for profile in (None, {}, {"role": "admin"}, {"id": "user1", "role": "member"}, {"id": "matt"}):
            with self.subTest(profile=profile), mock.patch.object(guard, "viewer", return_value=profile), \
                    mock.patch.object(guard, "script", return_value=True):
                self.refused(403)
        self.settings.assert_not_called()
        self.connect.assert_not_called()

    def test_unresolved_viewer_error_does_not_expose_private_configuration_details(self):
        with mock.patch.object(guard, "viewer", side_effect=ApiError(500, "FIXTURE-private-config-path")):
            error = self.refused(403)
        self.assertNotIn("FIXTURE", str(error))
        self.settings.assert_not_called()
        self.connect.assert_not_called()

    def test_configuration_database_schema_and_malformed_reader_failures_are_sanitized(self):
        canary = "password=FIXTURE-SECRET C:/private/backup.dump"
        with mock.patch.object(maintenance.db, "settings", side_effect=ValueError(canary)):
            error = self.refused(503)
        self.assertEqual(str(error), maintenance.UNAVAILABLE)
        self.connect.assert_not_called()
        with mock.patch.object(maintenance.db, "connect", side_effect=RuntimeError(canary)):
            self.assertNotIn(canary, str(self.refused(503)))
        schema_failure = RuntimeError(canary)
        schema_failure.sqlstate = "42P01"
        with mock.patch.object(self.connection, "execute", side_effect=schema_failure):
            self.assertNotIn(canary, str(self.refused(503)))
        self.assertFalse(self.connection.active)
        self.connection.now = "FIXTURE-raw-invalid-clock"
        self.assertEqual(str(self.refused(503)), maintenance.UNAVAILABLE)

    def test_actual_start_time_orders_attempts_before_completion_id_and_breaks_ties(self):
        old_started_last_completed = run("dump", 99, hours=5)
        latest_start_failed = run("dump", 10, hours=1, ok=False)
        tied_start_last_id = run("dump", 11, hours=1, ok=True)
        job = self.job(recent=[old_started_last_completed, latest_start_failed, tied_start_last_id],
                       successful=[old_started_last_completed, tied_start_last_id])
        self.assertEqual(job["latest"], maintenance._run(tied_start_last_id, NOW))
        self.assertEqual(job["recent"], [maintenance._run(row, NOW) for row in
                                          (tied_start_last_id, latest_start_failed, old_started_last_completed)])
        self.assertEqual(job["last_success"], job["latest"])

    def test_failed_latest_is_not_healthy_even_when_older_success_is_fresh(self):
        failed, good = run("dump", 2, 1, False), run("dump", 1, 2)
        job = self.job(recent=[good, failed], successful=[good])
        self.assertEqual((job["health"], job["freshness"]), ("failure", "current"))
        self.assertEqual((job["latest"]["outcome"], job["last_success"]["outcome"]), ("failure", "success"))

    def test_last_success_is_independent_of_the_five_recent_attempts(self):
        failed = [run("dump", i, i, False) for i in range(1, 9)]
        good = run("dump", 0, 48)
        job = self.job(recent=failed, successful=[good])
        self.assertEqual(len(job["recent"]), 5)
        self.assertNotIn(maintenance._run(good, NOW), job["recent"])
        self.assertEqual(job["last_success"], maintenance._run(good, NOW))
        self.assertEqual((job["health"], job["freshness"]), ("failure", "stale"))

    def test_restore_uses_its_own_days_instead_of_the_nightly_grace(self):
        restored = run("restore_check", 1, 24 * 14)
        job = self.job("restore_check", [restored], [restored])
        self.assertEqual((job["health"], job["freshness"]), ("success", "current"))
        self.assertEqual(job["interval"], {"value": 28, "unit": "days", "source": "restore_check_days", "basis": "started_at"})
        overdue = run("restore_check", 2, 24 * 29)
        self.assertEqual(self.job("restore_check", [overdue], [overdue])["health"], "stale")

    def test_restore_interval_boundary_matches_the_scheduler_and_nightly_grace_is_strict(self):
        restored = run("restore_check", 1, 24 * 28)
        self.assertEqual(self.job("restore_check", [restored], [restored])["freshness"], "stale")
        checked = run("check", 2, 36)
        self.assertEqual(self.job("check", [checked], [checked])["freshness"], "current")
        after_boundary = self.job("check", [checked], [checked], now=NOW + timedelta(microseconds=1))
        self.assertEqual(after_boundary["freshness"], "stale")

    def test_backup_export_use_completion_and_check_restore_use_start_time(self):
        for kind in ("dump", "export", "check"):
            row = run(kind, 1, 40, finished=NOW - timedelta(hours=1))
            job = self.job(kind, [row], [row])
            self.assertEqual(job["freshness"], "stale" if kind == "check" else "current")
            self.assertEqual(job["interval"]["source"], "stale_backup_hours")

    def test_fractional_restore_interval_and_zero_grace_are_preserved(self):
        row = run("restore_check", 1, 13)
        self.assertEqual(self.job("restore_check", [row], [row], {**SETTINGS, "restore_check_days": 0.5})["freshness"], "stale")
        row = run("dump", 1)
        job = self.job(recent=[row], successful=[row], settings={**SETTINGS, "stale_backup_hours": 0})
        self.assertEqual((job["interval"]["value"], job["freshness"]), (0, "stale"))

    def test_invalid_intervals_are_unknown_and_cannot_make_a_recent_success_healthy(self):
        row = run("dump", 1)
        for value in (None, True, -1, "not-a-number", float("nan"), float("inf"), 1e300):
            with self.subTest(value=value):
                job = self.job(recent=[row], successful=[row], settings={**SETTINGS, "stale_backup_hours": value})
                self.assertEqual((job["health"], job["freshness"]), ("unknown", "unknown"))
                json.dumps(job, allow_nan=False)

    def test_incomplete_malformed_naive_future_and_reversed_dates_never_invent_running_or_health(self):
        bad_rows = [("dump", 4, NOW - timedelta(hours=1), None, False),
                    ("dump", 4, "FIXTURE-private-detail", NOW, True),
                    ("dump", 4, NOW.replace(tzinfo=None), NOW, True),
                    ("dump", 4, NOW + timedelta(hours=1), NOW + timedelta(hours=2), True),
                    ("dump", 4, NOW, NOW - timedelta(hours=1), True),
                    ("dump", 4, NOW - timedelta(hours=1), NOW, "true")]
        prior = run("dump", 1, 2)
        for row in bad_rows:
            with self.subTest(row=row):
                job = self.job(recent=[row], successful=[prior])
                self.assertEqual((job["latest"]["outcome"], job["health"]), ("unknown", "unknown"))
                encoded = json.dumps(job)
                self.assertNotIn("FIXTURE", encoded)
                self.assertNotIn("running", encoded)

    def test_bad_success_records_are_not_presented_as_a_success(self):
        row = ("dump", 4, NOW, NOW + timedelta(hours=1), True)
        job = self.job(recent=[row], successful=[row])
        self.assertIsNone(job["last_success"])
        self.assertEqual((job["freshness"], job["health"]), ("unknown", "unknown"))

    def test_only_four_allowlisted_jobs_are_exposed(self):
        rows = [run("gate", 1), run("PRIVATE-job", 2)]
        result = maintenance._project(rows, rows, SETTINGS, NOW)
        self.assertEqual([job["kind"] for job in result["jobs"]], list(maintenance.KINDS))
        self.assertTrue(all(job["latest"] is None for job in result["jobs"]))

    def test_pure_dispatch_uses_get_head_query_guards_without_http(self):
        handler = SimpleNamespace(command="GET", _allow=mock.Mock(), _query=mock.Mock(return_value={}), _send_json=mock.Mock())
        with mock.patch.object(maintenance, "maintenance_view", return_value={"available": True}) as read:
            self.assertTrue(feature_routes.dispatch(handler, ["settings", "maintenance"], {}))
        handler._allow.assert_called_once_with("GET", "HEAD")
        handler._query.assert_called_once_with({}, ())
        read.assert_called_once_with()
        handler._send_json.assert_called_once_with(200, {"available": True})
