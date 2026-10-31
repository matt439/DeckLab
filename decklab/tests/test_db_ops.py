"""Tests for the database's operations (decklab/db: backup, export, schedule, nightly).

The pure parts (the prune plan, the task's XML, the nightly order) run under any Python. The
rest need psycopg and the local PostgreSQL server, and skip without them (db_support.py).
They work in throwaway databases and temporary folders only: never the NAS, the real export
repo, the real decklab database or Task Scheduler. db.log is redirected to a temporary file.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_db_ops
The fixture runner disables configured PostgreSQL and real Forge; named native
runtime cases also need separate qualification (see AGENTS.md, Tests).
"""
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from decklab.db import backup, check, conn as db, export, nightly, schedule, visits
from decklab.lib import shops
from decklab.tests import db_support


def _make_writable(func, path, exc):
    """rmtree's onexc: git writes its objects read-only, which Windows won't delete as they are."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _temp_dir(test):
    """A temporary folder removed (git objects included) when test ends."""
    tmp = Path(tempfile.mkdtemp(prefix="decklab-ops-test-"))
    test.addCleanup(shutil.rmtree, tmp, onexc=_make_writable)
    return tmp


class _QuietLog:
    """Sends db.log to a temporary file and keeps the commands' output off the test run."""

    def setUp(self):
        super().setUp()
        self.tmp = _temp_dir(self)
        patcher = mock.patch.object(db, "LOG_FILE", self.tmp / "logs" / "db.log")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.said = []
        self.say = self.said.append


def _names(*days, time="030000"):
    return [f"decklab-{d:%Y-%m-%d}-{time}.dump" for d in days]


class PlanPruneTests(unittest.TestCase):
    today = date(2026, 10, 11)          # a Sunday (ISO week 41)

    def test_names_and_dates(self):
        self.assertEqual(backup.dump_name(datetime(2026, 1, 2, 3, 4, 5)), "decklab-2026-01-02-030405.dump")
        self.assertEqual(backup.dump_date("decklab-2026-01-02-030405.dump"), date(2026, 1, 2))
        for name in ("decklab-2026-13-02-030405.dump", "decklab-2026-01-02.dump", "other-2026-01-02-030405.dump",
                     "decklab-2026-01-02-030405.dump.partial", "decklab-2026-01-02-030405.dump.bak"):
            self.assertIsNone(backup.dump_date(name), name)

    def test_the_newest_dump_of_each_recent_day_is_kept(self):
        names = ["decklab-2026-10-11-010000.dump", "decklab-2026-10-11-030000.dump",
                 "decklab-2026-10-10-030000.dump"]
        keep, delete = backup.plan_prune(names, self.today, keep_daily=14, keep_weekly=0)
        self.assertEqual(keep, ["decklab-2026-10-10-030000.dump", "decklab-2026-10-11-030000.dump"])
        self.assertEqual(delete, ["decklab-2026-10-11-010000.dump"])

    def test_daily_window_is_keep_daily_days_including_today(self):
        names = _names(*(self.today - timedelta(days=i) for i in range(20)))
        keep, delete = backup.plan_prune(names, self.today, keep_daily=14, keep_weekly=0)
        self.assertEqual(keep, sorted(_names(*(self.today - timedelta(days=i) for i in range(14)))))
        self.assertEqual(len(delete), 6)

    def test_the_newest_dump_of_each_recent_iso_week_is_kept(self):
        names = _names(*(self.today - timedelta(days=i) for i in range(120)))
        keep, delete = backup.plan_prune(names, self.today, keep_daily=14, keep_weekly=8)
        daily = set(_names(*(self.today - timedelta(days=i) for i in range(14))))
        weekly = set(keep) - daily
        # Sundays end ISO weeks: the newest dump of weeks 34 to 39 (40 and 41 are inside the dailies).
        self.assertEqual(sorted(weekly), sorted(_names(*(date(2026, 10, 4) - timedelta(weeks=i)
                                                         for i in range(1, 7)))))
        self.assertTrue(all(date.fromisoformat(n[8:18]).isoweekday() == 7 for n in weekly))
        self.assertEqual(len(keep) + len(delete), 120)
        self.assertEqual(set(keep) & set(delete), set())

    def test_a_week_that_only_has_an_old_dump_keeps_it(self):
        names = _names(date(2026, 9, 1))          # Tuesday of week 36, inside 8 weeks
        keep, delete = backup.plan_prune(names, self.today, keep_daily=14, keep_weekly=8)
        self.assertEqual((keep, delete), (names, []))
        recent = _names(*(self.today - timedelta(days=i) for i in range(14)))
        keep, delete = backup.plan_prune(recent + _names(date(2026, 7, 1)), self.today, 14, 8)
        self.assertEqual((keep, delete), (sorted(recent), _names(date(2026, 7, 1))))

    def test_the_last_dumps_are_kept_however_old_when_dumps_stop(self):
        # pg_dump failed every night since 2026-08-01: the last fortnight of good dumps stays.
        days = [date(2026, 8, 1) - timedelta(days=i) for i in range(60)]
        keep, delete = backup.plan_prune(_names(*days), self.today, keep_daily=14, keep_weekly=8)
        self.assertEqual(keep, sorted(_names(*days[:14])))
        self.assertEqual(sorted(delete), sorted(_names(*days[14:])))
        keep, delete = backup.plan_prune(_names(date(2026, 7, 1), date(2026, 7, 2)), self.today, 14, 8)
        self.assertEqual((keep, delete), (_names(date(2026, 7, 1), date(2026, 7, 2)), []))
        # Even keeping no dailies, the newest dump survives; of a day's dumps, only its newest counts.
        names = ["decklab-2026-07-02-010000.dump", "decklab-2026-07-02-030000.dump"] + _names(date(2026, 7, 1))
        keep, delete = backup.plan_prune(names, self.today, keep_daily=0, keep_weekly=0)
        self.assertEqual(keep, ["decklab-2026-07-02-030000.dump"])

    def test_other_files_are_never_planned_for_deletion_and_future_dumps_stay(self):
        recent = _names(*(self.today - timedelta(days=i) for i in range(14)))
        names = ["notes.txt", "decklab-old.dump", "decklab-2020-01-01-000000.dump.partial",
                 "decklab-2026-12-01-030000.dump", "decklab-2020-01-01-000000.dump"] + recent
        keep, delete = backup.plan_prune(names, self.today, 14, 8)
        self.assertEqual(keep, sorted(recent + ["decklab-2026-12-01-030000.dump"]))
        self.assertEqual(delete, ["decklab-2020-01-01-000000.dump"])

    def test_prune_folder_deletes_only_planned_dumps_and_dead_partials(self):
        tmp = _temp_dir(self)
        recent = _names(*(self.today - timedelta(days=i) for i in range(14)))
        old_partial, new_partial = "decklab-2020-01-01-000000.dump.partial", "decklab-2026-10-11-030000.dump.partial"
        names = recent + _names(date(2020, 1, 1)) + ["readme.txt", "old.partial", old_partial, new_partial]
        for n in names:
            (tmp / n).write_bytes(b"x")
        two_days_ago = datetime.now().timestamp() - 2 * 86400
        for n in ("old.partial", old_partial):
            os.utime(tmp / n, (two_days_ago, two_days_ago))
        deleted = backup.prune_folder(tmp, today=self.today, s={"keep_daily": 14, "keep_weekly": 8})
        self.assertEqual(deleted, _names(date(2020, 1, 1)) + [old_partial])
        self.assertEqual(sorted(p.name for p in tmp.iterdir()), sorted(set(names) - set(deleted)))


class BackupDirDefaultTests(unittest.TestCase):

    def test_no_copy_by_default_on_any_system(self):
        # E11-S48: a new install keeps its dumps in staging; the household's NAS is its own setting
        self.assertIsNone(db.DEFAULTS["backup_dir"])


class CompareCountsTests(unittest.TestCase):

    def test_differences_are_named(self):
        self.assertEqual(backup.compare_counts({"public.a": 1}, {"public.a": 1}), [])
        lines = backup.compare_counts({"public.a": 1, "public.b": 2}, {"public.a": 3, "public.c": 0})
        self.assertEqual(lines, ["public.a has 3 row(s) restored, 1 dumped",
                                 "public.b is missing from the restored copy",
                                 "public.c is in the restored copy but wasn't in the database"])


class ScratchTargetTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("psycopg"), "psycopg renders the DROP")
    def test_drop_is_confined_to_the_configured_scratch_and_never_requests_force(self):
        connection = mock.Mock()
        with mock.patch.object(db, "settings", return_value={"name": "fixture"}):
            backup._scratch_drop(connection, "fixture_restorecheck")
            sql = connection.execute.call_args.args[0].as_string()
            self.assertEqual(sql, 'drop database if exists "fixture_restorecheck"')
            self.assertNotIn("force", sql.lower())
            self.assertNotIn("terminate", sql.lower())
            connection.reset_mock()
            for name in ("fixture", "postgres", "template0", "other_restorecheck", ""):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    backup._scratch_drop(connection, name)
            connection.execute.assert_not_called()

    def test_byte_limit_refuses_names_that_would_truncate_before_any_database_connection(self):
        limit = backup.MAX_IDENTIFIER_BYTES - len(backup.RESTORE_SUFFIX.encode())
        self.assertEqual(len(backup._scratch_name("a" * limit).encode()), backup.MAX_IDENTIFIER_BYTES)
        self.assertEqual(backup._scratch_name("\u00e9" * (limit // 2)), "\u00e9" * (limit // 2) + backup.RESTORE_SUFFIX)
        for name in ("a" * (limit + 1), "\u00e9" * (limit // 2 + 1), "\x00", "", None, "\ud800"):
            with self.subTest(name=repr(name)), mock.patch.object(db, "settings", return_value={"name": name}), \
                    mock.patch.object(db, "connect") as connect, self.assertRaises(ValueError):
                backup.run_restore_check(source="unused-fixture")
            connect.assert_not_called()


class TaskXmlTests(unittest.TestCase):
    command = r"C:\Python314\pythonw.exe"
    workdir = r"C:\VSProjects\Trading & Cards"

    def task(self):
        return schedule.parse_task_xml(schedule.task_xml(self.command, self.workdir, r"PC\matt <x>",
                                                         start=date(2026, 10, 11)))

    def test_the_task_runs_nightly_daily_at_half_past_three(self):
        task = self.task()
        self.assertEqual(task["command"], self.command)
        self.assertEqual(task["arguments"], "-m decklab.db nightly")
        self.assertEqual(task["workdir"], self.workdir)          # & escaped and read back
        self.assertEqual(task["start"], "2026-10-11T03:30:00")
        self.assertEqual(task["days"], "1")
        self.assertTrue(task["enabled"] and task["trigger_enabled"])

    def test_the_task_runs_as_the_user_and_catches_up(self):
        task = self.task()
        self.assertEqual(task["user"], r"PC\matt <x>")
        self.assertEqual(task["logon_type"], "InteractiveToken")
        self.assertEqual(task["run_level"], "LeastPrivilege")
        self.assertTrue(task["catch_up"])
        self.assertEqual(task["time_limit"], "PT2H")
        self.assertEqual(task["multiple"], "IgnoreNew")

    def test_the_xml_has_no_logon_trigger_and_says_where_it_came_from(self):
        text = schedule.task_xml(self.command, self.workdir, "u", start=date(2026, 10, 11))
        self.assertNotIn("LogonTrigger", text)
        self.assertIn("python -m decklab.db schedule install", text)
        self.assertIn(r"<URI>\Deck Lab database backup</URI>", text)

    def test_not_a_task_is_refused(self):
        with self.assertRaises(ValueError):
            schedule.parse_task_xml("<Other/>")
        with self.assertRaises(ValueError):
            schedule.parse_task_xml("<Task")

    @unittest.skipUnless(sys.platform == "win32", "Task Scheduler is Windows-only")
    def test_install_refuses_a_python_without_psycopg(self):
        said = []
        with mock.patch.dict(sys.modules, {"psycopg": None}), \
                mock.patch.object(schedule, "_homenet", side_effect=AssertionError("must not register")):
            self.assertEqual(schedule.install(name="Deck Lab test task (never registered)", say=said.append), 1)
        self.assertIn("psycopg can't be imported", said[0])
        self.assertIn("python -m decklab.db schedule install with the system python", said[0])

    def test_describe_says_what_is_wrong(self):
        task = self.task()
        lines = schedule.describe(task, exists=lambda p: True)
        self.assertIn("daily at 03:30, catching up after the PC was off", lines[1])
        self.assertTrue(any("not this repo" in l for l in lines))
        lines = schedule.describe(dict(task, enabled=False), exists=lambda p: False)
        self.assertTrue(any("disabled" in l for l in lines))
        self.assertTrue(any("isn't there any more" in l for l in lines))
        self.assertIn("isn't registered", schedule.describe(None)[0])

    def test_describe_warns_about_the_venvs_launcher(self):
        system = schedule.describe(self.task(), exists=lambda p: True)
        self.assertFalse(any(".venv" in l for l in system), system)
        task = dict(self.task(), command=r"C:\Repo\.venv\Scripts\pythonw.exe")
        lines = schedule.describe(task, exists=lambda p: True)
        self.assertTrue(any("WARNING: it runs the .venv's pythonw.exe" in l for l in lines), lines)
        self.assertTrue(schedule.in_venv('"C:/Repo/.VENV/Scripts/pythonw.exe"'))
        self.assertFalse(schedule.in_venv(r"C:\Repo\venv-notes\pythonw.exe"))


class NightlyTests(_QuietLog, unittest.TestCase):

    def test_restore_check_due(self):
        now = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)
        self.assertTrue(nightly.restore_check_due(None, now, 28))
        self.assertTrue(nightly.restore_check_due(now - timedelta(days=28), now, 28))
        self.assertFalse(nightly.restore_check_due(now - timedelta(days=27, hours=23), now, 28))

    def _run(self, backup_result, last_check):
        calls = []

        def step(label, result):
            def run(*a, **k):
                calls.append(label)
                if isinstance(result, Exception):
                    raise result
                return result
            return run

        with mock.patch.object(backup, "run_backup", step("backup", backup_result)), \
                mock.patch.object(backup, "run_prune", step("prune", 0)), \
                mock.patch.object(visits, "run_prune", step("visits", 0)), \
                mock.patch.object(export, "run_export", step("export", 0)), \
                mock.patch.object(check, "run", step("check", 0)), \
                mock.patch.object(backup, "run_restore_check", step("restore", 0)),                 mock.patch.object(shops, "nightly", step("shops", 0)), \
                mock.patch.object(backup, "last_ok", lambda *a: {"restore_check": last_check}), \
                mock.patch.object(db, "settings", lambda: dict(db.DEFAULTS)):
            code = nightly.run()
        return code, calls

    def test_every_step_runs_and_a_failure_fails_the_night(self):
        code, calls = self._run(RuntimeError("NAS gone"), None)
        self.assertEqual(code, 1)
        self.assertEqual(calls, ["backup", "prune", "visits", "export", "check", "restore", "shops"])
        log = db.LOG_FILE.read_text(encoding="utf-8")
        self.assertIn("backup failed: RuntimeError: NAS gone", log)
        self.assertIn("failed: backup.", log)

    def test_a_recent_restore_check_is_not_repeated(self):
        code, calls = self._run(0, datetime.now().astimezone() - timedelta(days=3))
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["backup", "prune", "visits", "export", "check", "shops"])
        self.assertIn("every step worked", db.LOG_FILE.read_text(encoding="utf-8"))


class _OpsDb(_QuietLog, db_support.DbTestCase):
    """A throwaway database, with the backup and staging folders in a temporary folder."""

    def setUp(self):
        super().setUp()
        real = db.settings()
        self.settings = dict(real, backup_dir=str(self.tmp / "nas"), staging_dir=str(self.tmp / "staging"),
                             export_repo=str(self.tmp / "not-the-export-repo"))
        patcher = mock.patch.object(db, "settings", lambda: dict(self.settings))
        patcher.start()
        self.addCleanup(patcher.stop)
        # The class shares one database: start each test with no profiles, trail or runs.
        with self.connect("owner") as c:
            with db.change("test", "test", "reset for the next test", conn=c) as (cur, _):
                cur.execute("delete from profile_email")
                cur.execute("delete from profile")
                cur.execute("delete from space")
            c.execute("delete from audit.row_change")
            c.execute("delete from audit.change_set")
            c.execute("delete from ops.backup_run")

    def add_profile(self, pid, name, email):
        with db.change("test", "test", f"add {pid}") as (cur, _):
            cur.execute("insert into space (id) values ('home') on conflict do nothing")
            cur.execute("insert into profile (id, name, role, space_id, plays_as, position) "
                        "values (%s, %s, 'member', 'home', 'either', (select count(*) from profile))", (pid, name))
            cur.execute("insert into profile_email (profile_id, email) values (%s, %s)", (pid, email))

    def runs(self, kind):
        with self.connect("ro") as c:
            return c.execute("select ok, path, bytes, detail from ops.backup_run where kind = %s order by id",
                             (kind,)).fetchall()


class BackupTests(_OpsDb):

    def test_backup_and_restore_check_round_trip(self):
        self.add_profile("matt", "Matt", "m@example.com")
        self.assertEqual(backup.run_backup(say=self.say), 0, self.said)
        nas = backup.dumps_in(self.tmp / "nas")
        self.assertEqual(len(nas), 1)
        self.assertEqual(backup.dumps_in(self.tmp / "staging"), nas)     # the local copy stays
        self.assertEqual(list((self.tmp / "nas").glob("*.partial")), [])
        (ok, path, size, detail), = self.runs("dump")
        self.assertTrue(ok)
        self.assertEqual(Path(path), self.tmp / "nas" / nas[0])
        self.assertEqual(size, (self.tmp / "nas" / nas[0]).stat().st_size)
        counts = backup.recorded_counts(nas[0])
        self.assertEqual(counts["public.profile"], 1)
        self.assertEqual(counts["ops.backup_run"], 0)                    # counted in the dump's snapshot
        counts_again, digests = backup.recorded(nas[0])
        self.assertEqual(counts_again, counts)
        self.assertIn("public.profile", digests)
        self.assertIn("audit.change_set", digests)
        self.assertFalse(any(name.startswith("ops.") for name in digests))
        self.assertEqual(json.loads(detail[len("rows: "):]), counts)     # the pre-phase-5 code's reading

        # Rows written after the dump don't upset the check: it compares with the dump's counts.
        self.add_profile("user1", "User1", "c@example.com")
        self.assertEqual(backup.run_restore_check(say=self.say), 0, self.said)
        (ok, path, _, detail), = self.runs("restore_check")
        self.assertTrue(ok, detail)
        self.assertEqual(Path(path).name, nas[0])
        self.assertIn("same row counts and contents", self.said[-1])
        with db_support._admin() as c:
            self.assertIsNone(c.execute("select 1 from pg_database where datname = %s",
                                        (self.dbname + backup.RESTORE_SUFFIX,)).fetchone())

        lines = backup.status()
        self.assertTrue(lines[1].startswith("  last dump: 20"))
        self.assertFalse(any("WARNING" in l for l in lines), lines)

    def test_without_a_backup_dir_the_dump_stays_in_staging(self):
        self.settings["backup_dir"] = None
        self.assertEqual(backup.run_backup(say=self.say), 0, self.said)
        staging = backup.dumps_in(self.tmp / "staging")
        self.assertEqual(len(staging), 1)
        self.assertIn("stays on this computer only", self.said[-1])
        (ok, path, _, _), = self.runs("dump")
        self.assertTrue(ok)
        self.assertEqual(Path(path), self.tmp / "staging" / staging[0])
        self.assertEqual(backup.run_prune(say=self.say), 0, self.said)
        self.assertEqual(backup.run_restore_check(say=self.say), 0, self.said)

    def test_a_restore_that_differs_fails(self):
        self.assertEqual(backup.run_backup(say=self.say), 0, self.said)
        with self.connect("owner") as c:
            c.execute("update ops.backup_run set detail = replace(detail, '\"public.space\": 0', "
                      "'\"public.space\": 5') where kind = 'dump'")
        self.assertEqual(backup.run_restore_check(say=self.say), 1)
        self.assertIn("public.space has 0 row(s) restored, 5 dumped", self.said[-1])
        (ok, _, _, detail), = self.runs("restore_check")
        self.assertFalse(ok)

    def test_a_restore_whose_contents_differ_fails(self):
        self.add_profile("matt", "Matt", "m@example.com")
        self.assertEqual(backup.run_backup(say=self.say), 0, self.said)
        name = backup.dumps_in(self.tmp / "nas")[0]
        self.assertIn("public.profile", backup.recorded(name)[1])
        with self.connect("owner") as c:
            c.execute("update ops.backup_run set digests = digests || %s::jsonb where kind = 'dump'",
                      (json.dumps({"public.profile": "0" * 32}),))
        self.assertEqual(backup.run_restore_check(say=self.say), 1)
        self.assertIn("restored with different contents: public.profile's rows differ", self.said[-1])

    def test_scratch_cleanup_refuses_an_active_foreign_session_without_terminating_it(self):
        import psycopg
        from psycopg import sql
        scratch = backup._scratch_name(self.settings["name"])
        with db.connect("owner", dbname="postgres", autocommit=True) as owner:
            backup._scratch_drop(owner, scratch)
            owner.execute(sql.SQL("create database {} encoding 'UTF8' template template0").format(sql.Identifier(scratch)))
            privileges = owner.execute("select pg_has_role('decklab_owner', 'pg_signal_backend', 'MEMBER'), "
                                       "pg_has_role('decklab_owner', 'decklab_app', 'USAGE')").fetchone()
            try:
                with db.connect("app", dbname=scratch, autocommit=True) as foreign:
                    with self.assertRaises(psycopg.errors.ObjectInUse):
                        backup._scratch_drop(owner, scratch)
                    self.assertEqual(foreign.execute("select 1").fetchone(), (1,))
                    self.assertEqual(owner.execute("select pg_has_role('decklab_owner', 'pg_signal_backend', 'MEMBER'), "
                                                   "pg_has_role('decklab_owner', 'decklab_app', 'USAGE')").fetchone(), privileges)
            finally:
                backup._scratch_drop(owner, scratch)

    def test_a_dump_recorded_without_digests_is_checked_by_its_counts(self):
        self.assertEqual(backup.run_backup(say=self.say), 0, self.said)
        name = backup.dumps_in(self.tmp / "nas")[0]
        with self.connect("owner") as c:
            c.execute("update ops.backup_run set digests = null where kind = 'dump'")
        self.assertEqual(backup.recorded(name)[1], None)
        self.assertEqual(backup.run_restore_check(say=self.say), 0, self.said)
        self.assertIn("only the counts were compared", self.said[-1])

    def test_dump_details_read_back(self):
        self.assertEqual(backup.dump_detail({"b": 2, "a": 1}), 'rows: {"a": 1, "b": 2}')
        self.assertEqual(backup.parse_dump_detail(backup.dump_detail({"a": 1})), {"a": 1})
        self.assertEqual(backup.parse_dump_detail("copy to x failed"), None)
        self.assertEqual(backup.parse_dump_detail("rows: {broken"), None)
        self.assertEqual(backup.parse_dump_detail("rows: [1]"), None)

    def test_status_shows_the_last_check(self):
        self.assertIn("  last check: never (python -m decklab.db check)", backup.status())
        started = datetime.now()
        backup.record("check", started, False, detail='{"checks": [{"name": "deck lines", "ok": false, '
                                                      '"detail": "casual/x"}]}')
        lines = backup.status()
        self.assertTrue(any(l.startswith("  last check: 20") and l.endswith("FAILED: deck lines (casual/x)")
                            for l in lines), lines)
        self.assertIn("WARNING: the last check found a problem", lines[-1])
        backup.record("check", started, True, detail='{"checks": [{"name": "a", "ok": true, "warning": true}]}')
        self.assertTrue(any(l.endswith("passed (1 warning)") for l in backup.status()))
        self.settings["side_by_side_until"] = "2099-01-31"
        self.assertIn("  Side-by-side checks: until 2099-01-31 (python -m decklab.db check --history lists each "
                      "night's).", backup.status())
        self.settings["side_by_side_until"] = "not a date"
        self.assertFalse(any("Side-by-side" in l for l in backup.status()))

    def test_restore_check_with_no_dump_fails(self):
        (self.tmp / "nas").mkdir()
        self.assertEqual(backup.run_restore_check(say=self.say), 1)
        self.assertIn("there's no dump", self.said[-1])

    def test_a_failed_copy_keeps_the_local_dump_and_is_recorded(self):
        blocker = self.tmp / "a-file"
        blocker.write_text("not a folder")
        self.assertEqual(backup.run_backup(dest=blocker / "sub", say=self.say), 1)
        self.assertIn("The local copy is kept", self.said[-1])
        self.assertEqual(len(backup.dumps_in(self.tmp / "staging")), 1)
        (ok, path, size, detail), = self.runs("dump")
        self.assertFalse(ok)
        self.assertIn("copy to", detail)
        self.assertGreater(size, 0)
        lines = backup.status()
        self.assertIn("no dump has worked yet", lines[-1])

    def test_status_warns_when_the_last_dump_is_old(self):
        self.assertEqual(backup.run_backup(say=self.say), 0, self.said)
        lines = backup.status(now=datetime.now() + timedelta(hours=40))
        self.assertIn("WARNING: the last dump that worked is 40 hours old", lines[-1])

    def test_prune_command_thins_both_folders(self):
        recent = _names(*(date.today() - timedelta(days=i) for i in range(int(self.settings["keep_daily"]))))
        for folder in ("nas", "staging"):
            (self.tmp / folder).mkdir()
            for n in _names(date(2020, 1, 1)) + recent + ["keep.txt"]:
                (self.tmp / folder / n).write_bytes(b"x")
        self.assertEqual(backup.run_prune(say=self.say), 0)
        for folder in ("nas", "staging"):
            self.assertEqual(sorted(p.name for p in (self.tmp / folder).iterdir()),
                             sorted(recent + ["keep.txt"]))

    def test_a_missing_pg_dump_is_named_as_such(self):
        self.settings["pg_bin"] = str(self.tmp / "no-postgres-here")
        self.assertEqual(backup.run_backup(say=self.say), 1)
        self.assertIn("pg_dump", self.said[-1])
        self.assertNotIn("staging", self.said[-1])
        (ok, _, _, detail), = self.runs("dump")
        self.assertFalse(ok)
        self.assertIn("pg_dump", detail)

    def test_a_missing_pg_restore_is_recorded(self):
        self.assertEqual(backup.run_backup(say=self.say), 0, self.said)
        self.settings["pg_bin"] = str(self.tmp / "no-postgres-here")
        self.assertEqual(backup.run_restore_check(say=self.say), 1)
        (ok, _, _, detail), = self.runs("restore_check")
        self.assertFalse(ok)
        self.assertIn("pg_restore", detail)
        with db_support._admin() as c:
            self.assertIsNone(c.execute("select 1 from pg_database where datname = %s",
                                        (self.dbname + backup.RESTORE_SUFFIX,)).fetchone())

    def test_prune_reports_an_unreachable_nas(self):
        self.assertEqual(backup.run_prune(say=self.say), 1)
        self.assertIn("can't be reached", self.said[0])


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


class ExportTests(_OpsDb):

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
                                           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"})
        env.start()
        self.addCleanup(env.stop)
        self.repo = self.tmp / "export"

    def test_export_writes_exact_csv_and_commits_only_changes(self):
        self.add_profile("matt", "Matt, \"M\"", "m@example.com")
        self.assertEqual(export.run_export(repo=self.repo, push=False, say=self.say), 0, self.said)
        tables = self.repo / "tables"
        self.assertEqual((tables / "public.space.csv").read_bytes(), b"id\nhome\n")
        self.assertEqual((tables / "public.profile.csv").read_bytes(),
                         b"id,name,role,space_id,plays_as,position\nmatt,\"Matt, \"\"M\"\"\",member,home,either,0\n")
        self.assertEqual((tables / "public.profile_email.csv").read_bytes(),
                         b"profile_id,email\nmatt,m@example.com\n")
        with self.connect("ro") as c:
            c.execute("set timezone = 'UTC'")
            cid, at = c.execute("select id, at::text from audit.change_set").fetchone()
        # via (migration 0003) is empty: the change came through no listener.
        self.assertEqual((tables / "audit.change_set.csv").read_bytes(),
                         f"id,at,actor,source,message,reason,via\n{cid},{at},test,test,add matt,,\n".encode())
        self.assertTrue(at.endswith("+00"))
        self.assertTrue((self.repo / "README.md").is_file())
        # Every row's before and after stays out (private data included); the dumps have it.
        self.assertFalse((tables / "audit.row_change.csv").exists())
        self.assertRegex(_git(self.repo, "log", "--format=%s"), r"^Deck Lab export \d{4}-\d\d-\d\d \d\d:\d\d$")

        (tables / "stale.table.csv").write_text("x\n")
        self.assertEqual(export.run_export(repo=self.repo, push=False, say=self.say), 0)
        self.assertFalse((tables / "stale.table.csv").exists())
        self.assertIn("no changes", self.said[-1])
        self.assertEqual(len(_git(self.repo, "log", "--format=%H").splitlines()), 1)

        self.add_profile("user1", "User1", "c@example.com")
        self.assertEqual(export.run_export(repo=self.repo, push=False, say=self.say), 0)
        self.assertEqual(len(_git(self.repo, "log", "--format=%H").splitlines()), 2)
        self.assertEqual([r[0] for r in self.runs("export")], [True, True, True])

    def test_export_pushes_to_origin(self):
        bare = self.tmp / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        export.ensure_repo(self.repo)
        _git(self.repo, "remote", "add", "origin", str(bare))
        self.assertEqual(export.run_export(repo=self.repo, say=self.say), 0, self.said)
        self.assertIn("pushed to origin", self.said[-1])
        self.assertEqual(_git(bare, "log", "--format=%s", "main").count("Deck Lab export"), 1)

    def test_a_failed_push_is_recorded(self):
        export.ensure_repo(self.repo)
        _git(self.repo, "remote", "add", "origin", str(self.tmp / "no-such-remote"))
        self.assertEqual(export.run_export(repo=self.repo, say=self.say), 1)
        self.assertIn("git push", self.said[-1])
        (ok, _, _, detail), = self.runs("export")
        self.assertFalse(ok)

    def test_files_are_stored_byte_for_byte(self):
        self.assertEqual(export.run_export(repo=self.repo, push=False, say=self.say), 0, self.said)
        self.assertEqual((self.repo / ".gitattributes").read_bytes(), b"* -text\n")
        self.assertIn(".gitattributes", _git(self.repo, "ls-files"))

    def test_a_folder_in_the_deck_lab_repo_is_refused(self):
        from decklab.lib import config
        inside = Path(config.REPO) / "decklab" / "data" / "never-made-export"
        self.assertEqual(export.run_export(repo=inside, push=False, say=self.say), 1)
        self.assertFalse(inside.exists())
        self.assertIn("inside the Deck Lab repo", self.said[-1])
        (ok, _, _, detail), = self.runs("export")
        self.assertFalse(ok)

    def test_another_working_repo_is_refused(self):
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "work.txt").write_text("someone's work\n")
        self.assertEqual(export.run_export(repo=self.repo, push=False, say=self.say), 1)
        self.assertIn("not a Deck Lab export", self.said[-1])
        self.assertFalse((self.repo / "tables").exists())
        self.assertEqual(_git(self.repo, "status", "--porcelain"), "?? work.txt")

    def test_a_failing_query_is_recorded(self):
        from psycopg import errors
        denied = errors.InsufficientPrivilege("permission denied for table later_table")
        with mock.patch.object(export, "table_csv", side_effect=denied):
            self.assertEqual(export.run_export(repo=self.repo, push=False, say=self.say), 1)
        (ok, _, _, detail), = self.runs("export")
        self.assertFalse(ok)
        self.assertIn("permission denied", detail)


class GitEnvTests(unittest.TestCase):

    def test_git_never_prompts_for_credentials(self):
        seen = {}

        def fake_run(args, **kw):
            seen.update(kw["env"])
            return subprocess.CompletedProcess(args, 0, b"", b"")

        with mock.patch.object(subprocess, "run", fake_run), \
                mock.patch.dict(os.environ, {"GIT_DIR": "elsewhere", "GCM_INTERACTIVE": "always"}):
            export.git(Path("."), "status")
        self.assertEqual(seen["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(seen["GCM_INTERACTIVE"], "never")
        self.assertNotIn("GIT_DIR", seen)

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_the_export_commits_without_a_git_identity_and_keeps_the_owners(self):
        # E11-S48: a new install's git may have no user.name or user.email
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        nowhere = tmp / "no-config"
        nowhere.write_text("", encoding="utf-8")
        isolated = {"GIT_CONFIG_GLOBAL": str(nowhere), "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp),
                    "XDG_CONFIG_HOME": str(tmp)}
        drop = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL")
        with mock.patch.dict(os.environ, isolated):
            for name in drop:
                os.environ.pop(name, None)
            repo = tmp / "export"
            export.ensure_repo(repo)
            (repo / "a.csv").write_text("a\n", encoding="utf-8")
            self.assertTrue(export.commit(repo))
            self.assertEqual(export.git(repo, "log", "-1", "--format=%an <%ae>")[1], "Deck Lab <decklab@localhost>")
            export.git(repo, "config", "user.name", "Owner")
            export.git(repo, "config", "user.email", "owner@example.com")
            (repo / "a.csv").write_text("b\n", encoding="utf-8")
            self.assertTrue(export.commit(repo))
            self.assertEqual(export.git(repo, "log", "-1", "--format=%an <%ae>")[1], "Owner <owner@example.com>")


if __name__ == "__main__":
    unittest.main()
