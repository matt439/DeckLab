"""Tests for the database's core (decklab/db: conn, migrate, setup, profiles_sync, sql and the
audit trigger).

The pure parts run under any Python. The rest need psycopg and the local PostgreSQL server,
and skip without them (db_support.py); each class works in its own throwaway database, never
the real decklab one.

Run from the repo root: .venv\\Scripts\\python -m unittest decklab.tests.test_db_core
"""
import hashlib
import io
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from decklab.db import conn as db, migrate, profiles_sync, setup, sql
from decklab.db import __main__ as cli
from decklab.tests import db_support


def _profile(pid, name=None, role="member", space="home", plays_as="either", emails=()):
    return {"id": pid, "name": name or pid.title(), "role": role, "space": space,
            "plays_as": plays_as if space == "home" else None, "emails": list(emails)}


class PgpassTests(unittest.TestCase):

    def test_a_new_role_line_is_added_and_other_lines_kept(self):
        text = "# mine\nlocalhost:5432:*:postgres:secret\n"
        out = setup.with_entry(text, "decklab_app", "pw1")
        self.assertEqual(out, "# mine\nlocalhost:5432:*:postgres:secret\nlocalhost:5432:*:decklab_app:pw1\n")

    def test_an_existing_role_line_is_replaced_in_place(self):
        text = "localhost:5432:*:decklab_app:old\r\nlocalhost:5432:*:postgres:secret\r\n"
        out = setup.with_entry(text, "decklab_app", "new")
        self.assertEqual(out, "localhost:5432:*:decklab_app:new\r\nlocalhost:5432:*:postgres:secret\r\n")

    def test_lines_for_another_host_port_or_database_are_left_alone(self):
        text = "otherhost:5432:*:decklab_app:a\nlocalhost:5433:*:decklab_app:b\nlocalhost:5432:db:decklab_app:c\n"
        self.assertFalse(setup.has_entry(text, "decklab_app"))
        self.assertEqual(setup.with_entry(text, "decklab_app", "d").splitlines()[:3], text.splitlines())

    def test_colons_and_backslashes_are_escaped(self):
        line = setup.pgpass_line("decklab_app", "a:b\\c")
        self.assertEqual(line, "localhost:5432:*:decklab_app:a\\:b\\\\c")
        self.assertTrue(setup.has_entry(line + "\n", "decklab_app"))
        self.assertEqual(setup._unescape(setup._split(line)[4]), "a:b\\c")

    def test_write_pgpass_makes_the_folder_and_replaces_the_file(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "postgresql" / "pgpass.conf"
        setup.write_pgpass(path, "a\n")
        setup.write_pgpass(path, "b\n")
        self.assertEqual(path.read_bytes(), b"b\n")
        self.assertEqual([p.name for p in path.parent.iterdir()], ["pgpass.conf"])


class SettingsTests(unittest.TestCase):

    def test_defaults_env_and_config_block(self):
        with mock.patch.object(db.config, "load", return_value={"database": {"port": 5433, "staging_dir": None}}), \
                mock.patch.dict(os.environ, {db.NAME_ENV: "decklab_other"}):
            s = db.settings()
        self.assertEqual((s["port"], s["name"], s["host"]), (5433, "decklab_other", "localhost"))
        self.assertEqual(s["staging_dir"], str(db.config.DATA / "backups"))
        self.assertEqual((s["keep_daily"], s["keep_weekly"]), (14, 8))

    def test_localhost_connects_to_one_address(self):
        # libpq's connect_timeout is per address: localhost's two (::1, 127.0.0.1) would double it.
        calls = []
        fake = types.SimpleNamespace(OperationalError=type("OperationalError", (Exception,), {}),
                                     connect=lambda **kw: calls.append(kw) or "conn")
        with mock.patch.object(db, "_psycopg", return_value=fake):
            for host, addr in (("localhost", "127.0.0.1"), ("LocalHost", "127.0.0.1"), ("nas.lan", None)):
                calls.clear()
                with self.subTest(host=host), \
                        mock.patch.object(db.config, "load", return_value={"database": {"host": host}}):
                    db.connect("app", timeout=2)
                    self.assertEqual(calls[0]["host"], host)             # kept for pgpass's matching
                    self.assertEqual(calls[0].get("hostaddr"), addr)
                    self.assertEqual(calls[0]["connect_timeout"], 2)

    def test_change_checks_its_arguments_before_connecting(self):
        with mock.patch.object(db, "connect", side_effect=AssertionError("connected")):
            for args in [("", "cli", "m"), ("matt", "email", "m"), ("matt", "cli", "  ")]:
                with self.assertRaises(ValueError):
                    with db.change(*args):
                        pass

    def test_pg_bin_names_the_folder_it_looked_in(self):
        with mock.patch.object(db.config, "load", return_value={"database": {"pg_bin": "Z:/nowhere"}}):
            with self.assertRaisesRegex(FileNotFoundError, "nowhere"):
                db.pg_bin("pg_dump")


class MigrationFileTests(unittest.TestCase):

    def test_checksum_reads_crlf_as_lf(self):
        self.assertEqual(migrate.checksum(b"a\r\nb\r\n"), migrate.checksum(b"a\nb\n"))
        self.assertNotEqual(migrate.checksum(b"a\n"), migrate.checksum(b"b\n"))

    def test_checksum_and_sql_ignore_a_byte_order_mark(self):
        self.assertEqual(migrate.checksum(migrate.BOM + b"a\r\n"), migrate.checksum(b"a\n"))
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "0001_first.sql").write_bytes(migrate.BOM + b"select 1;\r\n")
        self.assertEqual(migrate.available(tmp)[0]["sql"], "select 1;\n")

    def test_files_are_ordered_and_misnamed_ones_refused(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "0002_second.sql").write_bytes(b"select 2;\r\n")
        (tmp / "0001_first.sql").write_bytes(b"select 1;\n")
        files = migrate.available(tmp)
        self.assertEqual([(f["version"], f["name"]) for f in files], [(1, "first"), (2, "second")])
        self.assertEqual(files[1]["sql"], "select 2;\n")
        (tmp / "3_bad.sql").write_bytes(b"")
        with self.assertRaises(migrate.MigrationError):
            migrate.available(tmp)

    def test_the_shipped_migrations_are_well_named(self):
        self.assertEqual(migrate.available()[0]["name"], "foundation")


class SqlFormatTests(unittest.TestCase):

    def test_table_aligns_columns_and_counts_rows(self):
        out = sql.as_table(["id", "name"], [(1, "Matt"), (22, None)])
        self.assertEqual(out, "id | name\n---+-----\n1  | Matt\n22 |\n(2 rows)\n")
        self.assertEqual(sql.as_table(["n"], [(True,)]), "n\n-\nt\n(1 row)\n")

    def test_csv_has_a_header_and_lf_endings(self):
        self.assertEqual(sql.as_csv(["a", "b"], [(1, "x,y"), (None, "z")]), 'a,b\n1,"x,y"\n,z\n')


class SyncPlanTests(unittest.TestCase):

    def test_plan_lists_each_difference(self):
        want = profiles_sync.wanted([_profile("matt", emails=["m@x"]), _profile("user6", space="user6")])
        have = ({"home", "old"}, {"matt": ("Matt", "member", "home", "either", 0, ()),
                                  "gone": ("Gone", "member", "old", None, 1, ())})
        todo = profiles_sync.plan(want, have)
        self.assertEqual(todo, {"add_spaces": ["user6"], "add": ["user6"], "change": ["matt"],
                                "remove": ["gone"], "drop_spaces": ["old"]})
        self.assertFalse(any(profiles_sync.plan(want, want).values()))


class CliTests(unittest.TestCase):

    def test_ops_commands_parse_their_options(self):
        p = cli.parser()
        self.assertEqual(p.parse_args(["backup", "--dest", "X"]).dest, "X")
        self.assertIsNone(p.parse_args(["backup"]).dest)
        a = p.parse_args(["export", "--repo", "R", "--no-push"])
        self.assertEqual((a.repo, a.no_push), ("R", True))
        self.assertEqual(p.parse_args(["schedule", "status"]).action, "status")
        self.assertEqual(p.parse_args(["sql", "--csv", "select 1"]).query, "select 1")

    def test_ops_commands_call_the_ops_modules(self):
        calls = []
        backup = types.SimpleNamespace(
            run_backup=lambda dest=None: calls.append(("backup", dest)) or 0,
            run_prune=lambda: calls.append(("prune",)) or 0,
            run_restore_check=lambda: calls.append(("restore",)) or 1)
        export = types.SimpleNamespace(run_export=lambda repo=None, push=True: calls.append(("export", repo, push)) or 0)
        nightly = types.SimpleNamespace(run=lambda: calls.append(("nightly",)) or 0)
        schedule = types.SimpleNamespace(install=lambda: calls.append(("install",)) or 0,
                                         remove=lambda: 0, status=lambda: 0)
        mods = {"decklab.db.backup": backup, "decklab.db.export": export,
                "decklab.db.nightly": nightly, "decklab.db.schedule": schedule}
        import decklab.db as pkg
        with mock.patch.dict(sys.modules, mods), \
                mock.patch.multiple(pkg, create=True, backup=backup, export=export, nightly=nightly,
                                    schedule=schedule):
            codes = [cli.main(a) for a in (["backup", "--dest", "D"], ["prune"], ["restore-check"],
                                            ["export", "--no-push"], ["nightly"], ["schedule", "install"])]
        self.assertEqual(codes, [0, 0, 1, 0, 0, 0])
        self.assertEqual(calls, [("backup", "D"), ("prune",), ("restore",), ("export", None, False),
                                 ("nightly",), ("install",)])


class TriggerTests(db_support.DbTestCase):

    def test_a_write_without_a_change_set_is_refused(self):
        import psycopg
        with self.connect() as c:
            with self.assertRaisesRegex(psycopg.Error, "every write needs a change set"):
                c.execute("insert into space (id) values ('nochange')")

    def test_an_empty_change_set_setting_is_refused_too(self):
        import psycopg
        with self.connect() as c:
            c.execute("select set_config('decklab.change_set', '', false)")
            with self.assertRaisesRegex(psycopg.Error, "every write needs a change set"):
                c.execute("insert into space (id) values ('empty')")

    def test_change_records_each_rows_before_and_after(self):
        with db.change("matt", "test", "Add a space") as (cur, first):
            cur.execute("insert into space (id) values ('alpha')")
            cur.execute("insert into profile (id, name, role, space_id, position) "
                        "values ('al', 'Al', 'member', 'alpha', 9)")
        with db.change("claude", "test", "Rename Al") as (cur, second):
            cur.execute("update profile set name = 'Alan' where id = 'al'")
        with db.change("matt", "test", "Remove Al", reason="left") as (cur, third):
            cur.execute("delete from profile where id = 'al'")
            cur.execute("delete from space where id = 'alpha'")
        with self.connect("ro") as c:
            rows = c.execute("select change_set_id, table_name, op, row_key, before, after from audit.row_change "
                             "where change_set_id in (%s, %s, %s) order by id", (first, second, third)).fetchall()
            sets = c.execute("select actor, source, message, reason from audit.change_set where id = %s",
                             (third,)).fetchone()
        self.assertEqual([(r[0], r[1], r[2]) for r in rows],
                         [(first, "space", "INSERT"), (first, "profile", "INSERT"), (second, "profile", "UPDATE"),
                          (third, "profile", "DELETE"), (third, "space", "DELETE")])
        self.assertEqual(rows[1][3], {"id": "al"})
        self.assertIsNone(rows[1][4])
        self.assertEqual((rows[2][4]["name"], rows[2][5]["name"]), ("Al", "Alan"))
        self.assertEqual((rows[3][4]["name"], rows[3][5]), ("Alan", None))
        self.assertEqual(sets, ("matt", "test", "Remove Al", "left"))

    def test_a_failed_change_leaves_nothing(self):
        with self.connect("ro") as c:
            before = c.execute("select count(*) from audit.change_set").fetchone()[0]
        with self.assertRaises(RuntimeError):
            with db.change("matt", "test", "Doomed") as (cur, _):
                cur.execute("insert into space (id) values ('doomed')")
                raise RuntimeError("stop")
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select count(*) from audit.change_set").fetchone()[0], before)
            self.assertIsNone(c.execute("select 1 from space where id = 'doomed'").fetchone())

    def test_the_setting_ends_with_the_change(self):
        import psycopg
        with self.connect(autocommit=False) as c:
            with db.change("matt", "test", "One", conn=c) as (cur, _):
                cur.execute("insert into space (id) values ('once')")
            with self.assertRaisesRegex(psycopg.Error, "every write needs a change set"):
                c.execute("insert into space (id) values ('twice')")

    def test_truncate_is_refused_even_for_the_owner(self):
        import psycopg
        for table in ("profile_email", "profile", "space"):
            with self.connect("owner") as c:
                with self.assertRaisesRegex(psycopg.Error, "truncate isn't audited"):
                    c.execute(f"truncate {table} cascade")

    def test_change_refuses_a_connection_mid_transaction(self):
        with self.connect(autocommit=False) as c:
            c.execute("select 1")
            with self.assertRaises(ValueError):
                with db.change("matt", "test", "x", conn=c):
                    pass


class PrivilegeTests(db_support.DbTestCase):

    def assertRefused(self, role, statement):
        import psycopg
        with self.connect(role) as c:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege, msg=f"{role}: {statement}"):
                c.execute(statement)

    def test_ro_cannot_write(self):
        self.assertRefused("ro", "insert into space (id) values ('x')")
        self.assertRefused("ro", "insert into audit.change_set (actor, source, message) values ('a', 'test', 'm')")
        self.assertRefused("ro", "create table public.sneaky (id int)")
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select count(*) from schema_migration").fetchone()[0],
                             len(migrate.available()))

    def test_app_cannot_write_migrations_or_the_audit_trail(self):
        self.assertRefused("app", "insert into schema_migration (version, name, checksum) values (99, 'x', 'y')")
        self.assertRefused("app", "delete from schema_migration")
        self.assertRefused("app", "insert into audit.row_change (change_set_id, table_name, op) "
                                  "values (1, 'space', 'INSERT')")
        self.assertRefused("app", "delete from audit.change_set")
        self.assertRefused("app", "update audit.change_set set actor = 'x'")
        self.assertRefused("app", "insert into ops.backup_run (kind, started_at) values ('dump', now())")
        self.assertRefused("app", "create table public.sneaky (id int)")
        self.assertRefused("app", "insert into audit.change_set (at, actor, source, message) "
                                  "values ('2000-01-01', 'a', 'test', 'm')")

    def test_no_role_but_the_owner_may_make_temporary_objects(self):
        self.assertRefused("app", "create temporary table scratch (id int)")
        self.assertRefused("ro", "create temporary table scratch (id int)")

    def test_a_temporary_jsonb_cant_borrow_the_audit_triggers_rights(self):
        # Even with TEMP granted back, the trigger (run as the owner) must not pick up the
        # session's own pg_temp.jsonb, whose check would write schema_migration as the owner.
        from psycopg import sql as pgsql
        with self.connect("owner") as c:
            c.execute(pgsql.SQL("grant temporary on database {} to decklab_app").format(
                pgsql.Identifier(self.dbname)))
        self.addCleanup(self._revoke_temp)
        with self.connect("app", autocommit=False) as c:
            c.execute("create function pg_temp.sneak(v pg_catalog.jsonb) returns boolean language sql as "
                      "$$ insert into public.schema_migration (version, name, checksum) "
                      "values (999, 'by_decklab_owner', 'x') returning true $$")
            c.execute("create domain pg_temp.jsonb as pg_catalog.jsonb check (pg_temp.sneak(value))")
            c.commit()
            with db.change("matt", "test", "Probe", conn=c) as (cur, _):
                cur.execute("insert into space (id) values ('probe')")
        with self.connect("ro") as c:
            self.assertIsNone(c.execute("select 1 from schema_migration where version = 999").fetchone())
            self.assertIsNotNone(c.execute("select 1 from space where id = 'probe'").fetchone())

    def _revoke_temp(self):
        from psycopg import sql as pgsql
        with self.connect("owner") as c:
            c.execute(pgsql.SQL("revoke temporary on database {} from decklab_app").format(
                pgsql.Identifier(self.dbname)))

    def test_only_the_three_roles_may_connect(self):
        assert_secured(self, self.dbname)


def assert_secured(test, name):
    """PUBLIC can neither connect to database name nor make temporary objects in it, and the
    app and ro roles can connect."""
    with db.connect("ro", dbname=name, autocommit=True) as c:
        acl = c.execute("select datacl::text from pg_database where datname = %s", (name,)).fetchone()[0]
    public = [e.split("/")[0] for e in acl.strip("{}").split(",") if e.startswith("=")]
    test.assertFalse([e for e in public if "c" in e or "T" in e], acl)
    test.assertIn("decklab_app=c", acl)
    test.assertIn("decklab_ro=c", acl)


class MigrateTests(db_support.DbTestCase):

    def test_status_shows_the_shipped_migrations_applied(self):
        state = migrate.status()
        self.assertEqual([(r["version"], r["name"]) for r in state["applied"]],
                         [(f["version"], f["name"]) for f in migrate.available()])
        self.assertEqual(state["applied"][0]["name"], "foundation")
        self.assertEqual(state["pending"], [])
        self.assertEqual(migrate.apply(), [])

    def test_a_changed_migration_is_refused(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        for f in migrate.MIGRATIONS.glob("*.sql"):
            shutil.copy(f, tmp)
        original = (migrate.MIGRATIONS / "0001_foundation.sql").read_bytes().replace(b"\r\n", b"\n")  # a CRLF checkout too
        (tmp / "0001_foundation.sql").write_bytes(original.replace(b"\n", b"\r\n"))
        self.assertEqual(migrate.status(directory=tmp)["pending"], [])     # CRLF alone is no change
        (tmp / "0001_foundation.sql").write_bytes(original + b"\n-- edited\n")
        with self.assertRaisesRegex(migrate.MigrationError, "has changed since it was applied"):
            migrate.apply(directory=tmp)
        (tmp / "0001_foundation.sql").unlink()
        with self.assertRaisesRegex(migrate.MigrationError, "isn't in"):
            migrate.status(directory=tmp)

    def test_status_prints_the_backup_part_however_it_comes(self):
        import decklab.db as pkg
        asked = []
        backup = types.SimpleNamespace(
            status=lambda dbname=None: asked.append(dbname) or "Backups: one\nBackups: two")
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"decklab.db.backup": backup}), \
                mock.patch.object(pkg, "backup", backup, create=True), redirect_stdout(out):
            self.assertEqual(cli.main(["status"]), 0)
        self.assertIn("Backups: one\nBackups: two\n", out.getvalue())
        self.assertEqual(asked, [db.settings()["name"]])    # the backups of the database shown
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"decklab.db.backup": None}), redirect_stdout(out):
            self.assertEqual(cli.main(["status"]), 0)
        self.assertIn("backup.py isn't there", out.getvalue())



class NewMigrationTests(db_support.DbTestCase):

    def test_a_new_migration_is_applied_and_recorded(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        for f in migrate.MIGRATIONS.glob("*.sql"):
            shutil.copy(f, tmp)
        (tmp / "0900_extra.sql").write_bytes(b"create table extra (id int primary key);\n"
                                             b"create table extra2 (id int primary key);\n")
        self.assertEqual(migrate.apply(directory=tmp), ["0900_extra.sql"])
        with self.connect("ro") as c:
            # The default privileges reach a later migration's tables.
            self.assertEqual(c.execute("select count(*) from extra2").fetchone()[0], 0)
        import psycopg
        with self.connect("app") as c:
            # ... including the app's writes, which the audit trigger doesn't cover yet here.
            c.execute("insert into extra (id) values (1)")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                c.execute("insert into schema_migration (version, name, checksum) values (901, 'x', 'y')")


class ProfileSyncTests(db_support.DbTestCase):

    def _count(self):
        with self.connect("ro") as c:
            return c.execute("select count(*) from audit.change_set").fetchone()[0]

    def _profiles(self):
        with self.connect("ro") as c:
            rows = c.execute("select id, name, role, space_id, plays_as, position from profile "
                             "order by position").fetchall()
            emails = sorted(c.execute("select profile_id, email from profile_email").fetchall())
            spaces = [r[0] for r in c.execute("select id from space order by id")]
        return rows, emails, spaces

    def test_add_change_remove_and_no_op(self):
        first = [_profile("matt", role="admin", plays_as="user", emails=["m@x.com"]),
                 _profile("user1", plays_as="wife", emails=["c@x.com", "c2@x.com"]),
                 _profile("user6", space="user6")]
        self.assertEqual(profiles_sync.sync(first),
                         {"added": ["matt", "user1", "user6"], "changed": [], "removed": []})
        rows, emails, spaces = self._profiles()
        self.assertEqual(rows[2], ("user6", "User6", "member", "user6", None, 2))
        self.assertEqual(emails, [("matt", "m@x.com"), ("user1", "c2@x.com"), ("user1", "c@x.com")])
        self.assertEqual(spaces, ["home", "user6"])

        before = self._count()
        self.assertEqual(profiles_sync.sync(first), {"added": [], "changed": [], "removed": []})
        self.assertEqual(self._count(), before)

        second = [_profile("user1", plays_as="wife", emails=["c@x.com"]),
                  _profile("matt", name="Matthew", role="admin", plays_as="user", emails=["m@x.com"])]
        self.assertEqual(profiles_sync.sync(second),
                         {"added": [], "changed": ["user1", "matt"], "removed": ["user6"]})
        self.assertEqual(self._count(), before + 1)
        rows, emails, spaces = self._profiles()
        self.assertEqual([(r[0], r[1], r[5]) for r in rows], [("user1", "User1", 0), ("matt", "Matthew", 1)])
        self.assertEqual(emails, [("matt", "m@x.com"), ("user1", "c@x.com")])
        self.assertEqual(spaces, ["home"])
        with self.connect("ro") as c:
            actor = c.execute("select actor, source, message from audit.change_set order by id desc limit 1").fetchone()
        self.assertEqual(actor, ("system", "sync", profiles_sync.MESSAGE))

    def test_a_lock_held_elsewhere_fails_the_sync_within_its_timeout(self):
        import psycopg
        holder = self.connect("owner", autocommit=False)
        try:
            holder.execute("lock table profile in access exclusive mode")
            started = time.monotonic()
            with self.assertRaises(psycopg.errors.LockNotAvailable):
                profiles_sync.sync([_profile("matt")], timeout=2,
                                   options="-c lock_timeout=200 -c statement_timeout=5000")
            self.assertLess(time.monotonic() - started, 4)
        finally:
            holder.rollback()
            holder.close()


class SqlCommandTests(db_support.DbTestCase):

    def test_sql_prints_a_table_and_refuses_writes(self):
        out = io.StringIO()
        self.assertEqual(sql.run("select 1 as one, null as nothing", out=out), 0)
        self.assertEqual(out.getvalue(), "one | nothing\n----+--------\n1   |\n(1 row)\n")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(sql.run("delete from space", out=io.StringIO()), 1)
        self.assertIn("read-only", err.getvalue())


class SetupTests(unittest.TestCase):
    """setup.run against a new database (the roles already exist, so pgpass isn't touched).
    No password ever reaches an assertion's message: a failing run must not print one."""

    def test_setup_is_idempotent_and_prints_no_password(self):
        db_support.require_db()
        try:
            db.connect("super", dbname="postgres", autocommit=True).close()
        except db.DbUnavailable as e:
            self.skipTest(f"setup needs the postgres superuser ({e})")
        pgpass = setup.pgpass_path()
        before = hashlib.sha256(pgpass.read_bytes()).hexdigest()
        text = pgpass.read_text(encoding="utf-8")
        s = db.settings()
        for role in db.ROLES.values():
            if not setup.has_entry(text, role, s["host"], int(s["port"])):
                self.skipTest(f"{role} has no pgpass line, so setup would change pgpass")
        passwords = [setup._unescape(f[4]) for f in map(setup._split, text.splitlines()) if f]
        text = None
        name = db_support.create_empty_database("setup")
        self.addCleanup(db_support.drop_database, name)
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            self.assertEqual(setup.run(dbname=name), 0)
            self.assertEqual(setup.run(dbname=name), 0)
        printed = out.getvalue()
        leaked = any(pw and pw in printed for pw in passwords)
        passwords = None
        self.assertFalse(leaked, "a pgpass password appeared in setup's output")
        self.assertTrue(hashlib.sha256(pgpass.read_bytes()).hexdigest() == before, "setup changed pgpass")
        self.assertIn(f"{len(migrate.available())} migration(s) applied now", printed)
        self.assertIn("0 migration(s) applied now; profiles unchanged", printed)
        assert_secured(self, name)
        with db.connect("ro", dbname=name, autocommit=True) as c:
            self.assertGreater(c.execute("select count(*) from profile").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
