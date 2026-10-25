"""Tests for the database's phase 2 foundation: migration 0003 (the personal-state tables, their
audit and truncate triggers, privileges and checks, and change_set.via), change()'s via,
migrate.pending(), the reserved profile ids and the empty-sync refusal, lib/venv.py, and
api.common.state_errors().

The database classes need the local PostgreSQL server and skip without it (db_support.py);
each works in its own throwaway database, never the real decklab one.

Run from the repo root: python -m unittest decklab.tests.test_db_phase2
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.db import conn as db, migrate, profiles_sync
from decklab.lib import profiles, state, venv
from decklab.lib.api import common
from decklab.tests import db_support

TABLES = db_support.PHASE2_TABLES

# One valid row for each table, inserted as the app inside a change set.
INSERTS = {
    "wishlist_entry": ("insert into wishlist_entry (profile_id, position, name) values ('user1', 0, 'Plains')"),
    "profile_setting": "insert into profile_setting (profile_id, key, value) values ('matt', 'theme', 'dark')",
    "simulation_mode": "insert into simulation_mode (mode, set_by, set_by_name) values ('everyone', 'matt', 'Matt')",
    "play_record": ("insert into play_record (kind, id, revision, created_on, updated_on, updated_by, deck_ids, content) "
                    "values ('games', repeat('a', 32), 1, '2026-10-11T01:02:03+00:00', "
                    "'2026-10-11T01:02:03+00:00', 'Matt', array['casual/a', 'casual/b'], '{}')"),
}


def _quiet_log(test):
    """Point db.log at a temporary file for the test."""
    folder = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, folder, True)
    patcher = mock.patch.object(db, "LOG_FILE", folder / "db.log")
    patcher.start()
    test.addCleanup(patcher.stop)
    return folder / "db.log"


def _profile(pid, name=None, space="home"):
    return {"id": pid, "name": name or pid.title(), "role": "member", "space": space,
            "plays_as": "either" if space == "home" else None, "emails": []}


class MigrationTests(db_support.DbTestCase):

    def setUp(self):
        db_support.reset(self.dbname)

    def test_every_table_refuses_a_write_without_a_change_set(self):
        import psycopg
        for table, statement in INSERTS.items():
            with self.subTest(table=table), self.connect() as c:
                with self.assertRaisesRegex(psycopg.Error, "every write needs a change set"):
                    c.execute(statement)

    def test_writes_in_a_change_set_are_audited_with_their_keys(self):
        with db.change("matt", "test", "One of each") as (cur, set_id):
            for statement in INSERTS.values():
                cur.execute(statement)
        with self.connect("ro") as c:
            rows = c.execute("select table_name, op, row_key from audit.row_change where change_set_id = %s "
                             "order by id", (set_id,)).fetchall()
        self.assertEqual(rows, [("wishlist_entry", "INSERT", {"profile_id": "user1", "position": 0}),
                                ("profile_setting", "INSERT", {"profile_id": "matt", "key": "theme"}),
                                ("simulation_mode", "INSERT", {"id": True}),
                                ("play_record", "INSERT", {"kind": "games", "id": "a" * 32})])

    def test_truncate_is_refused_even_for_the_owner(self):
        import psycopg
        for table in TABLES:
            with self.subTest(table=table), self.connect("owner") as c:
                with self.assertRaisesRegex(psycopg.Error, "truncate isn't audited"):
                    c.execute(f"truncate {table}")

    def test_ro_cannot_write_and_the_app_can(self):
        import psycopg
        for table, statement in INSERTS.items():
            with self.subTest(table=table):
                with self.connect("ro") as c:
                    # ro can't make a change set either; with a change set id set by hand, the
                    # table's own privilege refuses it before the trigger runs.
                    c.execute("select set_config('decklab.change_set', '1', false)")
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        c.execute(statement)
                with self.connect("ro") as c:
                    c.execute(f"select count(*) from {table}")
        with db.change("matt", "test", "As the app") as (cur, _):
            for statement in INSERTS.values():
                cur.execute(statement)
            cur.execute("update profile_setting set value = 'light'")
            cur.execute("delete from wishlist_entry")

    def assertRefused(self, statement):
        import psycopg
        with self.assertRaises((psycopg.errors.CheckViolation, psycopg.errors.NotNullViolation,
                                psycopg.errors.UniqueViolation, psycopg.errors.InvalidDatetimeFormat), msg=statement):
            with db.change("matt", "test", "Bad") as (cur, _):
                cur.execute(statement)

    def test_the_checks_refuse_bad_rows(self):
        for statement in (
                "insert into wishlist_entry (profile_id, position, name) values ('../x', 0, 'Plains')",
                "insert into wishlist_entry (profile_id, position, name) values ('user1', -1, 'Plains')",
                "insert into wishlist_entry (profile_id, position, name) values ('user1', 0, ' Plains')",
                "insert into wishlist_entry (profile_id, position, name) values ('user1', 0, '')",
                "insert into wishlist_entry (profile_id, position, name, set_code) values ('user1', 0, 'P', 'sld')",
                "insert into wishlist_entry (profile_id, position, name, set_code, collector_number) "
                "values ('user1', 0, 'P', 'SLD', '1')",
                "insert into profile_setting (profile_id, key, value) values ('matt', 'Theme', 'dark')",
                "insert into profile_setting (profile_id, key, value) values ('matt', 'theme', repeat('x', 201))",
                "insert into simulation_mode (mode, set_by_name) values ('nobody', 'Matt')",
                "insert into simulation_mode (id, mode, set_by_name) values (false, 'admins', 'Matt')",
                "insert into play_record (kind, id, revision, created_on, updated_on, updated_by, deck_ids, content) "
                "values ('game', repeat('a', 32), 1, '2026-10-11', '2026-10-11', 'Matt', '{}', '{}')",
                "insert into play_record (kind, id, revision, created_on, updated_on, updated_by, deck_ids, content) "
                "values ('games', 'abc', 1, '2026-10-11', '2026-10-11', 'Matt', '{}', '{}')",
                "insert into play_record (kind, id, revision, created_on, updated_on, updated_by, deck_ids, content) "
                "values ('games', repeat('a', 32), 0, '2026-10-11', '2026-10-11', 'Matt', '{}', '{}')",
                "insert into play_record (kind, id, revision, created_on, updated_on, updated_by, deck_ids, content) "
                "values ('games', repeat('a', 32), 1, 'yesterday-ish', '2026-10-11', 'Matt', '{}', '{}')",
                "insert into play_record (kind, id, revision, created_on, updated_on, updated_by, deck_ids, content) "
                "values ('games', repeat('a', 32), 1, '2026-10-11', '2026-10-11', 'Matt', '{}', '[]')"):
            with self.subTest(statement=statement):
                self.assertRefused(statement)

    def test_one_mode_row_and_names_unique_without_case(self):
        with db.change("matt", "test", "Set up") as (cur, _):
            cur.execute(INSERTS["simulation_mode"])
            cur.execute(INSERTS["wishlist_entry"])
        self.assertRefused("insert into simulation_mode (mode, set_by_name) values ('paused', 'Matt')")
        self.assertRefused("insert into wishlist_entry (profile_id, position, name) values ('user1', 1, 'PLAINS')")
        with db.change("matt", "test", "Another profile may have it") as (cur, _):
            cur.execute("insert into wishlist_entry (profile_id, position, name) values ('matt', 0, 'plains')")

    def test_via_is_recorded_and_checked(self):
        import psycopg
        with db.change("user1", "web", "From outside", via="tunnel") as (cur, outside):
            pass
        with db.change("matt", "web", "From home", via="home") as (cur, home):
            pass
        with db.change("claude", "cli", "No listener") as (cur, cli):
            pass
        with self.connect("ro") as c:
            vias = dict(c.execute("select id, via from audit.change_set where id in (%s, %s, %s)",
                                  (outside, home, cli)).fetchall())
        self.assertEqual(vias, {outside: "tunnel", home: "home", cli: None})
        with self.assertRaises(ValueError):
            with db.change("matt", "web", "Somewhere else", via="office"):
                pass
        with self.connect() as c:
            with self.assertRaises(psycopg.errors.CheckViolation):
                c.execute("insert into audit.change_set (actor, source, message, via) values ('m', 'web', 'x', 'office')")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                c.execute("update audit.change_set set via = 'home'")

    def test_nothing_is_pending_once_migrated(self):
        self.assertEqual(migrate.pending(), [])
        with self.connect() as c:
            self.assertEqual(migrate.pending(conn=c), [])


class UnmigratedTests(unittest.TestCase):
    """A database with only 0001 and 0002, as the live one is before phase 2's migrate."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db_support.require_db()
        cls.folder = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.folder, True)
        for f in migrate.available()[:2]:
            shutil.copy(f["path"], cls.folder / f["path"].name)
        cls.dbname = db_support.create_empty_database("phase1")
        cls.addClassCleanup(db_support.drop_database, cls.dbname)
        migrate.apply(dbname=cls.dbname, directory=cls.folder)
        from decklab.db import setup
        setup.secure_database(cls.dbname)

    def test_a_change_without_via_still_works(self):
        with db.connect("app", dbname=self.dbname, autocommit=True) as c:
            with db.change("system", "sync", "Phase 1 style", conn=c) as (cur, _):
                cur.execute("insert into space (id) values ('home')")
            with self.assertRaises(Exception):
                with db.change("matt", "web", "Phase 2 style", conn=c, via="home"):
                    pass

    def test_pending_lists_0003(self):
        self.assertEqual([f["version"] for f in migrate.pending(dbname=self.dbname)][:1], [3])

    def test_the_store_says_to_migrate(self):
        from decklab.lib.state import pg
        store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())
        with self.assertRaisesRegex(state.Unavailable, "decklab.db migrate"):
            store.wishlist("user1")


class ProfileSyncTests(db_support.DbTestCase):

    def setUp(self):
        self.log = _quiet_log(self)

    def test_an_empty_list_removes_nobody(self):
        profiles_sync.sync([_profile("matt"), _profile("user1")])
        self.assertEqual(profiles_sync.sync([]), {"added": [], "changed": [], "removed": []})
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select count(*) from profile").fetchone()[0], 2)
        self.assertIn("would remove every profile", self.log.read_text(encoding="utf-8"))

    def test_reserved_ids_are_refused(self):
        for pid in sorted(profiles.RESERVED_IDS):
            with self.subTest(pid=pid), self.assertRaisesRegex(ValueError, "audit trail"):
                profiles_sync.sync([_profile("matt"), _profile(pid)])


class ReservedIdTests(unittest.TestCase):

    def test_config_profiles_with_reserved_ids_are_left_out(self):
        listed = [{"id": pid, "name": pid.title(), "role": "admin", "plays_as": "user"}
                  for pid in ("matt", "claude", "system", "test", "home")]
        self.assertEqual([p["id"] for p in profiles.parse(listed)], ["matt"])


class VenvTests(unittest.TestCase):

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        packages = self.folder / ("Lib" if os.name == "nt" else f"lib/python{sys.version_info[0]}."
                                                                f"{sys.version_info[1]}") / "site-packages"
        packages.mkdir(parents=True)
        self.packages = packages
        self.path = ["", "stdlib", os.path.join("base", "Lib", "site-packages")]
        for patcher in (mock.patch.object(venv, "VENV", self.folder), mock.patch.object(sys, "path", self.path),
                        mock.patch.object(sys, "prefix", sys.base_prefix)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_cfg(self, home=None, version=None):
        home = home or os.path.dirname(getattr(sys, "_base_executable", None) or sys.executable)
        version = version or f"{sys.version_info[0]}.{sys.version_info[1]}.0"
        (self.folder / "pyvenv.cfg").write_text(f"home = {home}\nversion = {version}\n", encoding="utf-8")

    def test_the_venv_goes_before_the_base_site_packages(self):
        self.write_cfg()
        self.assertIsNone(venv.activate())
        self.assertEqual(self.path[:3], ["", "stdlib", str(self.packages)])
        self.assertIsNone(venv.activate())
        self.assertEqual(self.path.count(str(self.packages)), 1)

    def test_another_python_or_version_is_refused(self):
        self.write_cfg(home=str(self.folder / "elsewhere"))
        self.assertIn("another Python", venv.activate())
        self.write_cfg(version="2.7.18")
        self.assertIn("2.7.18", venv.activate())
        self.assertEqual(venv.reason(), venv.activate())
        self.assertNotIn(str(self.packages), self.path)

    def test_a_venv_already_on_the_path_moves_ahead_of_the_base_one(self):
        self.write_cfg()
        self.path.append(str(self.packages))               # from PYTHONPATH, after the base site-packages
        self.assertIsNone(venv.activate())
        self.assertEqual(self.path, ["", "stdlib", str(self.packages), os.path.join("base", "Lib", "site-packages")])

    def test_inside_another_venv_it_still_checks_and_adds_this_one(self):
        self.write_cfg()
        with mock.patch.object(sys, "prefix", str(self.folder / "other-venv")):
            self.assertIsNone(venv.activate())
        self.assertIn(str(self.packages), self.path)
        self.write_cfg(version="2.7.18")
        self.path.remove(str(self.packages))
        with mock.patch.object(sys, "prefix", str(self.folder / "other-venv")):
            self.assertIn("2.7.18", venv.activate())
        with mock.patch.object(sys, "prefix", str(self.folder)):
            self.assertIsNone(venv.activate())              # inside the repo's own venv: nothing to do

    def test_no_venv_is_a_reason_not_an_error(self):
        self.assertIn("no .venv", venv.activate())


class StateErrorTests(unittest.TestCase):

    def test_store_errors_become_answers(self):
        cases = ((state.Unavailable("down"), 503, common.DATABASE_DOWN, {"reason": "database"}),
                 (state.Invalid(common_message := "A wishlist can hold at most 1000 cards"), 400, common_message, {}),
                 (state.Conflict("changed"), 409, "changed", {}))
        for error, status, message, extra in cases:
            with self.subTest(status=status), self.assertRaises(common.ApiError) as caught:
                with common.state_errors():
                    raise error
            self.assertEqual((caught.exception.status, caught.exception.message, caught.exception.extra),
                             (status, message, extra))
        with self.assertRaises(KeyError), common.state_errors():
            raise KeyError("not a store error")


if __name__ == "__main__":
    unittest.main()
