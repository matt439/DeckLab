"""Tests for the database's place in the running server and its files: lib/dbstatus.py (the
footer's "database" block and the circuit breaker it feeds), the export of migration 0003's
tables and the wishlists as their old files, and status's counts of the new tables.

The pure parts (who sees what in dbstatus.view) run anywhere. The rest need the local
PostgreSQL server and skip without it (db_support.py); each class works in its own throwaway
database and temporary folders, never the real decklab database, export repo or wishlists.

Run from the repo root: python -m unittest decklab.tests.test_db_runtime
"""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from decklab.db import __main__ as db_main, conn as db, export, migrate
from decklab.lib import dbstatus
from decklab.lib.state import Actor, pg
from decklab.tests import db_support
from decklab.tests import test_db_ops as ops
from decklab.tests.test_state_contract import ID_A, entry, game

SYSTEM = Actor("test", "Test", None, "test")


def _quiet_log(test):
    folder = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, folder, True)
    patcher = mock.patch.object(db, "LOG_FILE", folder / "db.log")
    patcher.start()
    test.addCleanup(patcher.stop)
    return folder / "db.log"


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _unmigrated_database(test):
    """A throwaway database as one looks before migration 0003: its tables dropped and its
    row in schema_migration removed. Dropped when the test ends. Returns its name."""
    name = db_support.create_database()
    test.addCleanup(db_support.drop_database, name)
    with db.connect("owner", dbname=name, autocommit=True) as c:
        for table in db_support.PHASE2_TABLES:
            c.execute(f"drop table public.{table} cascade")
        c.execute("delete from public.schema_migration where version = 3")
    return name


def _snapshot(**changes):
    out = {"ok": True, "usable": True, "error": None, "detail": None, "pending_migrations": 0,
           "last_backup": "2026-10-11T03:30:00+10:00", "backup_stale": False, "stale_hours": 36.0}
    out.update(changes)
    return out


class ViewTests(unittest.TestCase):
    """Who sees what of the snapshot (no database needed)."""

    def setUp(self):
        for target, name, value in ((dbstatus, "_snapshot", _snapshot(ok=False, usable=False,
                                                                       error=dbstatus.NOT_REACHABLE,
                                                                       detail="refused")),
                                    (dbstatus.venv, "reason", lambda: "there's no .venv in the repo")):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_only_an_admin_sees_the_details(self):
        admin = {"id": "matt", "role": "admin", "space": "home"}
        member = {"id": "user1", "role": "member", "space": "home"}
        details = {"ok": False, "usable": False, "error": "not reachable", "pending_migrations": 0,
                   "last_backup": "2026-10-11T03:30:00+10:00", "backup_stale": False, "stale_hours": 36.0,
                   "checks_warning": None, "venv": "there's no .venv in the repo",
                   "inventory": {"imported": None, "revision": None, "imported_at": None,
                                 "stale": True, "not_imported": False}}
        self.assertEqual(dbstatus.view(admin), details)
        self.assertEqual(dbstatus.view(admin, script=True), details)
        self.assertEqual(dbstatus.view(member, script=True), {"ok": False})      # by role, not by where
        self.assertEqual(dbstatus.view(None, script=True), details)              # a script, not the page before a pick
        self.assertEqual(dbstatus.view(None), {"ok": False})                     # any other request naming nobody
        self.assertNotIn("refused", json.dumps(dbstatus.view(admin)))            # the raw detail is db.log's

    def test_only_what_stops_the_stores_is_news_to_a_non_admin(self):
        member = {"id": "user1", "role": "member", "space": "home"}
        admin = {"id": "matt", "role": "admin", "space": "home"}
        for snapshot, seen in ((_snapshot(ok=False, error=dbstatus.MIGRATIONS_PENDING, pending_migrations=1), True),
                               (_snapshot(ok=False, usable=False, error=dbstatus.MIGRATIONS_PENDING,
                                          pending_migrations=1), False),
                               (_snapshot(ok=False, error=dbstatus.CHECK_FAILED, detail="canceled"), True)):
            with self.subTest(error=snapshot["error"], usable=snapshot["usable"]), \
                    mock.patch.object(dbstatus, "_snapshot", snapshot):
                self.assertEqual(dbstatus.view(member), {"ok": seen})
                self.assertEqual(dbstatus.view(None), {"ok": seen})
                shown = dbstatus.view(admin)
                self.assertEqual((shown["ok"], shown["usable"], shown["error"]),
                                 (False, snapshot["usable"], snapshot["error"]))

    def test_the_venv_reason_shows_no_absolute_paths(self):
        admin = {"id": "matt", "role": "admin", "space": "home"}
        text = (r".venv was made from another Python (C:\Users\someone\AppData\Local\Programs\Python\Python314), "
                r"not this one (C:\Users\someone\Python\python.exe)")
        with mock.patch.object(dbstatus.venv, "reason", lambda: text):
            shown = dbstatus.view(admin)["venv"]
        self.assertNotIn("someone", shown)
        self.assertIn("another Python", shown)
        with mock.patch.object(dbstatus.venv, "reason", lambda: None):
            self.assertIsNone(dbstatus.view(admin)["venv"])

    def test_before_the_first_check(self):
        with mock.patch.object(dbstatus, "_snapshot", None):
            self.assertEqual(dbstatus.view(None, script=True), {"ok": None, "checking": True})

    def test_describe(self):
        self.assertEqual(dbstatus.describe(_snapshot()), "reachable")
        self.assertEqual(dbstatus.describe(_snapshot(ok=False, error=dbstatus.MIGRATIONS_PENDING,
                                                     pending_migrations=2)),
                         "reachable, 2 migrations pending (python -m decklab.db migrate)")
        self.assertEqual(dbstatus.describe(_snapshot(ok=False, error=dbstatus.PSYCOPG_MISSING)), "psycopg missing")
        self.assertEqual(dbstatus.describe(_snapshot(ok=False, error=dbstatus.CHECK_FAILED)),
                         "the check failed (db.log says why)")


class CheckTests(db_support.DbTestCase):
    """dbstatus.check() and refresh() on a throwaway database."""

    def setUp(self):
        self.log = _quiet_log(self)
        self.breaker = pg.Breaker()
        for target, name, value in ((pg, "BREAKER", self.breaker), (dbstatus, "_snapshot", None)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with self.connect("owner") as c:
            c.execute("delete from ops.backup_run")

    def dump(self, hours_ago, ok=True):
        when = datetime.now().astimezone() - timedelta(hours=hours_ago)
        with self.connect("owner") as c:
            c.execute("insert into ops.backup_run (kind, started_at, finished_at, ok) values ('dump', %s, %s, %s)",
                      (when, when, ok))
        return when

    def test_a_current_database_with_no_backup_yet(self):
        result = dbstatus.check()
        self.assertEqual(result, {"ok": True, "usable": True, "error": None, "detail": None, "pending_migrations": 0,
                                  "last_backup": None, "backup_stale": True, "stale_hours": 36.0,
                                  "inventory": {"tables": True, "revision": None, "imported_at": None},
                                  "checks_warning": "No check of the database's data has run yet. Run python -m "
                                                    "decklab.db check on the PC (the nightly task runs it)."})

    def run_row(self, kind, hours_ago, ok, detail=None):
        when = datetime.now().astimezone() - timedelta(hours=hours_ago)
        with self.connect("owner") as c:
            c.execute("insert into ops.backup_run (kind, started_at, finished_at, ok, detail) "
                      "values (%s, %s, %s, %s, %s)", (kind, when, when, ok, detail))
        return when

    def test_the_newest_check_and_restore_check_decide_the_checks_warning(self):
        self.run_row("check", 30, False, json.dumps({"checks": [{"name": "deck lines", "ok": False}]}))
        self.run_row("check", 2, True, json.dumps({"checks": [{"name": "accessories", "ok": True}]}))
        self.assertIsNone(dbstatus.check()["checks_warning"])           # the newest one passed
        self.run_row("check", 1, False, json.dumps({"checks": [{"name": "accessories", "ok": True},
                                                               {"name": "deck lines", "ok": False}]}))
        self.assertRegex(dbstatus.check()["checks_warning"], r"^The database check of .* found a problem "
                                                             r"\(deck lines\)\. On the PC, python -m decklab\.db "
                                                             r"check --history says more\.$")
        with self.connect("owner") as c:
            c.execute("delete from ops.backup_run")
        self.run_row("check", 40, True, "{}")
        self.assertIn("more than 36 hours ago", dbstatus.check()["checks_warning"])
        self.run_row("check", 1, True, "{}")
        self.run_row("restore_check", 1, False, "pg_restore failed")
        self.assertRegex(dbstatus.check()["checks_warning"], r"^The restore check of a database backup on .* failed")

    def test_the_last_dump_that_worked_decides_staleness(self):
        when = self.dump(2)
        self.dump(1, ok=False)                      # a failed one doesn't count
        result = dbstatus.check()
        self.assertEqual(result["last_backup"], when.isoformat(timespec="seconds"))
        self.assertIs(result["backup_stale"], False)
        with self.connect("owner") as c:
            c.execute("delete from ops.backup_run")
        self.dump(40)
        self.assertIs(dbstatus.check()["backup_stale"], True)

    def test_pending_migrations(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        for f in migrate.available():
            shutil.copy(f["path"], folder / f["path"].name)
        (folder / "0999_later.sql").write_text("select 1;\n", encoding="utf-8")
        with mock.patch.object(migrate, "MIGRATIONS", folder):
            result = dbstatus.check()
        self.assertEqual((result["ok"], result["error"], result["pending_migrations"]),
                         (False, dbstatus.MIGRATIONS_PENDING, 1))
        self.assertIs(result["usable"], True)                       # phase 2's tables are there
        self.assertIs(result["backup_stale"], True)                 # still read: the database answered

    def test_without_migration_0003_the_stores_cant_be_used(self):
        result = dbstatus.check(_unmigrated_database(self))
        self.assertEqual((result["ok"], result["usable"], result["error"], result["pending_migrations"]),
                         (False, False, dbstatus.MIGRATIONS_PENDING, 1))

    def test_the_probe_has_the_stores_timeouts(self):
        seen = []
        real = db.connect

        def connect(*args, **kwargs):
            seen.append(kwargs.get("options"))
            return real(*args, **kwargs)
        with mock.patch.object(db, "connect", connect):
            self.assertIs(dbstatus.check()["ok"], True)
        self.assertEqual(seen, [pg.REQUEST_OPTIONS])

    def test_a_check_that_fails_otherwise_isnt_an_outage(self):
        import psycopg
        failures = (psycopg.errors.QueryCanceled("canceling statement due to statement timeout"),
                    psycopg.errors.LockNotAvailable("canceling statement due to lock timeout"),
                    OSError("migrations folder unreadable"))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), \
                    mock.patch.object(migrate, "pending", side_effect=failure):
                result = dbstatus.check()
                self.assertEqual((result["ok"], result["usable"], result["error"]),
                                 (False, True, dbstatus.CHECK_FAILED))
        # refresh() leaves the breaker as it is for one: neither tripped nor reset.
        with mock.patch.object(migrate, "pending", side_effect=failures[0]):
            dbstatus.refresh()
            self.assertFalse(self.breaker.is_open())
            self.breaker.trip("a request failed")
            dbstatus.refresh()
            self.assertTrue(self.breaker.is_open())
        self.assertEqual(self.breaker.trips, 1)
        self.assertIn("dbstatus: the check failed (db.log says why) (canceling statement due to statement timeout)",
                      self.log.read_text(encoding="utf-8"))
        # A config.json that isn't an object (settings() raising) is a failed check, not a crash.
        with mock.patch.object(db, "settings", side_effect=AttributeError("'list' object has no attribute 'get'")):
            self.assertEqual(dbstatus.check()["error"], dbstatus.CHECK_FAILED)

    def test_unreachable_and_psycopg_missing(self):
        port = socket.socket()
        port.bind(("127.0.0.1", 0))
        closed = port.getsockname()[1]
        port.close()
        settings = dict(db.settings(), host="127.0.0.1", port=closed)
        with mock.patch.object(db, "settings", lambda: dict(settings)):
            result = dbstatus.check()
        self.assertEqual((result["ok"], result["error"], result["backup_stale"]), (False, dbstatus.NOT_REACHABLE, None))
        self.assertIn(str(closed), result["detail"])
        with mock.patch.object(db, "_psycopg", side_effect=db.DbUnavailable("psycopg isn't installed")):
            result = dbstatus.check()
        self.assertEqual((result["ok"], result["error"]), (False, dbstatus.PSYCOPG_MISSING))

    def test_refresh_feeds_the_breaker_and_logs_changes_once(self):
        down = _snapshot(ok=False, error=dbstatus.NOT_REACHABLE, detail="connection refused", backup_stale=None)
        with mock.patch.object(dbstatus, "check", return_value=down):
            dbstatus.refresh()
            self.assertTrue(self.breaker.is_open())
            self.breaker.reset()
            dbstatus.refresh()                      # still down: not tripped again, not logged again
        self.assertFalse(self.breaker.is_open())
        self.assertEqual(self.breaker.trips, 1)
        self.breaker.trip("a request failed")
        self.assertEqual(dbstatus.refresh()["ok"], True)       # the real check: the database answers
        self.assertFalse(self.breaker.is_open())
        text = self.log.read_text(encoding="utf-8")
        self.assertEqual(text.count("dbstatus: not reachable (connection refused)"), 1, text)
        self.assertEqual(text.count("dbstatus: reachable"), 1, text)
        self.assertEqual(dbstatus.view(None, script=True)["ok"], True)

    def test_the_thread_checks_at_once_then_every_minute_until_stopped(self):
        seen, first = [], threading.Event()
        with mock.patch.object(dbstatus, "REFRESH_SECONDS", 0.05):
            dbstatus.start(lambda snapshot: (seen.append(snapshot), first.set()))
            self.addCleanup(dbstatus.stop)
            self.assertTrue(first.wait(10))
            time.sleep(0.3)
            thread = dbstatus._running[1]
            dbstatus.stop()
        self.assertFalse(thread.is_alive())        # stop() waited for it, inside the patches
        self.assertEqual(len(seen), 1)              # first() only after the first check
        self.assertIs(seen[0]["ok"], True)
        self.assertIsNone(dbstatus._running)

    def test_a_check_that_raises_doesnt_end_the_thread(self):
        calls, first = [], threading.Event()

        def refresh(dbname=None):
            calls.append(dbname)
            if len(calls) == 1:
                raise RuntimeError("something unexpected")
            return _snapshot()
        with mock.patch.object(dbstatus, "REFRESH_SECONDS", 0.02), mock.patch.object(dbstatus, "refresh", refresh):
            dbstatus.start(lambda snapshot: first.set())
            self.addCleanup(dbstatus.stop)
            self.assertTrue(first.wait(10))         # told of the failed first check, too
            deadline = time.monotonic() + 10
            while len(calls) < 3 and time.monotonic() < deadline:
                time.sleep(0.02)
            dbstatus.stop()
        self.assertGreaterEqual(len(calls), 3)
        self.assertIn("dbstatus: the check failed: RuntimeError: something unexpected",
                      self.log.read_text(encoding="utf-8"))


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def _wishlist_bytes(entries):
    return (json.dumps({"version": 1, "entries": entries}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


class ExportTests(ops._OpsDb):
    """The new tables and the wishlists in the export repo."""

    def setUp(self):
        super().setUp()
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname)
        env = mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
                                           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"})
        env.start()
        self.addCleanup(env.stop)
        self.repo = self.tmp / "export"
        self.store = pg.PgStore(breaker=pg.Breaker())

    def test_the_new_tables_and_the_wishlists_are_exported(self):
        user1 = [entry("Plains", "sld", "1513", "Art: a meadow — full of dogs", "magic/decks/casual/x.md"),
                  entry("Forest")]
        for e in user1:
            self.store.wishlist_add("user1", e, SYSTEM, "add")
        self.store.wishlist_add("matt", entry("Island"), SYSTEM, "add")
        self.store.settings_put("matt", {"theme": "dark"}, SYSTEM, "settings")
        self.store.simulation_mode_set("everyone", SYSTEM, "mode")
        self.store.play_put("games", game(ID_A), None, SYSTEM, "game")
        self.assertEqual(export.run_export(repo=self.repo, push=False, say=self.say), 0, self.said)
        tables = self.repo / "tables"
        self.assertEqual((tables / "public.wishlist_entry.csv").read_bytes().splitlines()[:2],
                         [b"profile_id,position,name,set_code,collector_number,notes,source",
                          b"matt,0,Island,,,,"])
        self.assertIn("user1,0,Plains,sld,1513,Art: a meadow — full of dogs,magic/decks/casual/x.md".encode(),
                      (tables / "public.wishlist_entry.csv").read_bytes().splitlines())
        self.assertEqual((tables / "public.profile_setting.csv").read_bytes(), b"profile_id,key,value\nmatt,theme,dark\n")
        self.assertTrue((tables / "public.simulation_mode.csv").read_bytes().startswith(
            b"id,mode,set_by,set_by_name,since\ntrue,everyone,test,Test,"))
        rows = (tables / "public.play_record.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(rows[0], "kind,id,revision,created_on,updated_on,updated_by,deck_ids,content")
        self.assertTrue(rows[1].startswith(f"games,{ID_A},1,2026-10-11T01:02:03+00:00,"))
        # The wishlists read exactly as the old repo files did.
        self.assertEqual((self.repo / "wishlists" / "user1.json").read_bytes(), _wishlist_bytes(user1))
        self.assertEqual((self.repo / "wishlists" / "matt.json").read_bytes(), _wishlist_bytes([entry("Island")]))
        self.assertIn("wishlists/user1.json", _git(self.repo, "ls-files"))

        # A list emptied loses its file; a stale file is removed; the rest stay byte for byte.
        self.store.wishlist_remove("matt", "Island", SYSTEM, "remove")
        _write(self.repo / "wishlists" / "user2.json", "{}\n")
        self.assertEqual(export.run_export(repo=self.repo, push=False, say=self.say), 0, self.said)
        self.assertEqual(sorted(p.name for p in (self.repo / "wishlists").iterdir()), ["user1.json"])
        self.assertNotIn("wishlists/matt.json", _git(self.repo, "ls-files"))

    def test_a_database_not_yet_migrated_still_exports(self):
        # Between updating the code and running migrate: 0003's tables are skipped, a CSV
        # already written for one is kept, and the wishlists folder is left alone.
        name = _unmigrated_database(self)
        self.assertEqual(export.run_export(repo=self.repo, push=False, say=self.say), 0, self.said)
        kept = (self.repo / "tables" / "public.profile_setting.csv").read_bytes()
        _write(self.repo / "wishlists" / "user1.json", _wishlist_bytes([entry("Forest")]))
        with mock.patch.dict(os.environ, {db.NAME_ENV: name}):
            export.write_tables(self.repo, dbname=name)
        fresh = self.tmp / "fresh"
        export.write_tables(fresh, dbname=name)
        tables = sorted(p.name for p in (fresh / "tables").iterdir())
        self.assertIn("public.profile.csv", tables)
        self.assertNotIn("public.play_record.csv", tables)
        self.assertFalse((fresh / "wishlists").exists())
        self.assertEqual((self.repo / "tables" / "public.profile_setting.csv").read_bytes(), kept)
        self.assertEqual((self.repo / "wishlists" / "user1.json").read_bytes(), _wishlist_bytes([entry("Forest")]))

    def test_the_readme_is_rewritten_when_it_differs(self):
        self.assertEqual(export.run_export(repo=self.repo, push=False, say=self.say), 0, self.said)
        old = export.README.splitlines()[0] + "\n\nAn older description.\n"
        (self.repo / "README.md").write_text(old, encoding="utf-8")
        _git(self.repo, "commit", "-qam", "older readme")
        self.assertEqual(export.run_export(repo=self.repo, push=False, say=self.say), 0, self.said)
        text = (self.repo / "README.md").read_bytes()
        self.assertEqual(text, export.README.encode("utf-8"))
        self.assertIn(b"wishlists/<profile>.json", text)
        self.assertIn("committed", self.said[-1])
        self.assertEqual(export.run_export(repo=self.repo, push=False, say=self.say), 0)
        self.assertIn("no changes", self.said[-1])


class StatusTests(db_support.DbTestCase):
    """status's counts of migration 0003's tables."""

    def setUp(self):
        _quiet_log(self)
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname)
        self.store = pg.PgStore(breaker=pg.Breaker())

    def test_status_counts_the_new_tables(self):
        self.assertEqual(db_main._personal_state(self.dbname),
                         "Personal state: 0 wishlist card(s) on 0 list(s), 0 setting(s) of 0 profile(s), "
                         "simulations not set (the default applies), 0 game(s) and 0 sideboard plan(s).")
        self.store.wishlist_add("user1", entry("Swamp"), SYSTEM, "a card")
        self.store.wishlist_add("matt", entry("Island", "fdn", "253"), SYSTEM, "a card")
        self.store.wishlist_add("matt", entry("Forest"), SYSTEM, "another")
        self.assertEqual(db_main._personal_state(self.dbname),
                         "Personal state: 3 wishlist card(s) on 2 list(s), 0 setting(s) of 0 profile(s), "
                         "simulations not set (the default applies), 0 game(s) and 0 sideboard plan(s).")

if __name__ == "__main__":
    unittest.main()
