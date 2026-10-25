"""Public-switch storage, maintenance and read-only reporting; no live publication."""
import csv
import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from decklab.db import __main__ as cli
from decklab.db import backup, check, conn as db, export, migrate, profiles_sync, setup, visibility_cli
from decklab.lib import visibility as switches
from decklab.lib.state import Actor, Unavailable, visibility as values
from decklab.lib.state import pg
from decklab.lib.state.memory import MemoryStore
from decklab.tests import db_support

ACTOR = Actor("test", "Test", source="cli")
HOME = {"id": "matt", "name": "Matt", "role": "admin", "space": "home", "plays_as": "user", "emails": []}
MEMBER = {"id": "guest", "name": "Guest", "role": "member", "space": "guest", "plays_as": None, "emails": []}


def folder(test, prefix):
    path = Path(tempfile.mkdtemp(prefix=prefix))
    test.addCleanup(shutil.rmtree, path)
    return path


class VisibilityCliTests(unittest.TestCase):
    def test_every_missing_switch_is_reported_as_private(self):
        rows = visibility_cli.rows({}, ["home", "guest"])
        self.assertEqual(len(rows), 9)
        self.assertEqual({row["state"] for row in rows}, {"Private"})
        self.assertEqual({(row["owner"], row["thing"]) for row in rows if row["thing"] == "accessories"},
                         {("matt", "accessories"), ("user1", "accessories"), ("shared", "accessories")})

    def test_list_uses_the_requested_database_and_does_not_hide_unknown_rows(self):
        store = MemoryStore()
        store.visibility_set("old-space", "games", True, ACTOR, "Fixture")
        out = io.StringIO()
        with mock.patch.object(visibility_cli.pg, "PgStore", return_value=store) as make, \
                mock.patch("decklab.lib.spaces.space_ids", return_value=["home"]), redirect_stdout(out):
            self.assertEqual(cli.main(["visibility", "list", "--dbname", "disposable"]), 0)
        make.assert_called_once_with(dbname="disposable")
        self.assertIn("home\tdecks\tPrivate", out.getvalue())
        self.assertIn("old-space\tgames\tPublic\tTest\t", out.getvalue())

    def test_only_home_switches_can_be_set_and_cli_never_borrows_a_member_identity(self):
        with mock.patch.object(switches, "READY_THINGS", frozenset(values.THINGS)), \
                mock.patch.object(visibility_cli.pg, "PgStore") as make, redirect_stderr(io.StringIO()):
            for owner, thing in (("guest", "decks"), ("user2", "collection"), ("home", "accessories"),
                                 ("matt", "games"), ("unknown", "accessories"), ("Home", "decks")):
                with self.subTest(owner=owner, thing=thing):
                    self.assertEqual(cli.main(["visibility", "set", owner, thing, "on", "-m", "Fixture"]), 1)
            make.assert_not_called()
            with self.assertRaises(SystemExit):
                cli.parser().parse_args(["visibility", "set", "home", "decks", "on", "-m", "Fixture", "--actor", "guest"])

    def test_home_cli_uses_fixed_words_keeps_the_reason_and_noop_writes_no_change(self):
        store = MemoryStore()
        with mock.patch.object(switches, "READY_THINGS", frozenset(values.THINGS)), \
                mock.patch.object(visibility_cli.pg, "PgStore", return_value=store), redirect_stdout(io.StringIO()):
            for owner, thing in (("home", "collection"), ("home", "decks"), ("home", "games"),
                                 ("matt", "accessories"), ("user1", "accessories"), ("shared", "accessories")):
                self.assertEqual(cli.main(["visibility", "set", owner, thing, "on", "-m", "Owner requested publication"]), 0)
            self.assertEqual(len(store.changes()), 6)
            self.assertEqual(cli.main(["visibility", "set", "home", "decks", "on", "-m", "Already Public"]), 0)
            self.assertEqual(len(store.changes()), 6)
            self.assertEqual(cli.main(["visibility", "set", "home", "decks", "off", "-m", "Owner requested privacy"]), 0)
        change = store.changes()[-1]
        self.assertEqual((change["actor"], change["source"], change["via"], change["message"], change["reason"]),
                         ("claude", "cli", None, "Make the home decks private", "Owner requested privacy"))
        self.assertNotIn(("home", "decks"), store.visibility())
        self.assertEqual(store.visibility_cached(), store.visibility())

    def test_cli_readiness_and_nonblank_reason_are_checked_before_connecting(self):
        with mock.patch.object(switches, "READY_THINGS", frozenset()), \
                mock.patch.object(visibility_cli.pg, "PgStore") as make, redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["visibility", "set", "home", "decks", "on", "-m", "Fixture"]), 1)
            self.assertEqual(cli.main(["visibility", "set", "home", "decks", "on", "-m", " "]), 1)
            make.assert_not_called()
            for args in (("home", "tokens", "on", "-m", "Fixture"), ("home", "decks", "yes", "-m", "Fixture"),
                         ("home", "decks", "on")):
                with self.subTest(args=args), self.assertRaises(SystemExit):
                    cli.parser().parse_args(["visibility", "set", *args])

    def test_unavailable_list_reports_failure_instead_of_cached_private_state(self):
        store = MemoryStore()
        store.down = True
        with mock.patch.object(visibility_cli.pg, "PgStore", return_value=store), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["visibility", "list"]), 2)


class VisibilityDatabaseTests(db_support.DbTestCase):
    def setUp(self):
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname)
        self.store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())

    def save(self, owner="home", thing="decks", on=True):
        return self.store.visibility_set(owner, thing, on, ACTOR, f"Make {owner} {thing} {'public' if on else 'private'}")

    def invariant(self, spaces=("home", "guest")):
        with self.connect("ro") as c, mock.patch("decklab.lib.spaces.space_ids", return_value=list(spaces)):
            return check._visibility(c)()

    def test_export_is_deterministic_and_digests_cover_switch_contents(self):
        with self.connect("ro") as c:
            empty = backup.digest_rows(c)["public.visibility"]
        self.save()
        path = folder(self, "decklab-visibility-export-")
        export.write_tables(path, dbname=self.dbname)
        file = path / "tables/public.visibility.csv"
        first = file.read_bytes()
        row, = list(csv.DictReader(io.StringIO(first.decode())))
        self.assertEqual((row["owner"], row["thing"], row["set_by"], row["set_by_name"]),
                         ("home", "decks", "test", "Test"))
        export.write_tables(path, dbname=self.dbname)
        self.assertEqual(file.read_bytes(), first)
        with self.connect("ro") as c:
            before = backup.digest_rows(c)["public.visibility"]
            self.assertEqual(backup.count_rows(c)["public.visibility"], 1)
        self.assertNotEqual(before, empty)
        self.save(on=False)
        self.save(thing="games")
        with self.connect("ro") as c:
            after = backup.digest_rows(c)["public.visibility"]
            self.assertEqual(backup.count_rows(c)["public.visibility"], 1)
        self.assertEqual(backup.compare_digests({"public.visibility": before}, {"public.visibility": after}),
                         ["public.visibility's rows differ from the ones dumped"])
        self.assertNotIn("public.visibility", export.INVENTORY_TABLES)

    def test_sync_removes_dropped_space_switches_in_its_change_set_and_reuse_starts_private(self):
        profiles_sync.sync(listed=[HOME, MEMBER], dbname=self.dbname)
        self.save("guest", "collection")
        self.save("guest", "decks")
        self.save("shared", "accessories")
        self.save()
        profiles_sync.sync(listed=[HOME], dbname=self.dbname)
        self.store.clear_cache()
        self.assertEqual(set(self.store.visibility()), {("home", "decks"), ("shared", "accessories")})
        newest = self.store.activity()["changes"][0]
        self.assertEqual((newest["actor"], newest["source"]), ("system", "sync"))
        self.assertEqual({(r["key"]["owner"], r["key"]["thing"]) for r in newest["rows"]
                          if r["table"] == "visibility"}, {("guest", "collection"), ("guest", "decks")})
        profiles_sync.sync(listed=[HOME, MEMBER], dbname=self.dbname)
        self.store.clear_cache()
        self.assertNotIn(("guest", "decks"), self.store.visibility())

    def test_check_accepts_space_and_kit_owners_and_flags_an_orphan(self):
        self.assertEqual(self.invariant(), (True, False, "0 Public switches; all owners valid"))
        self.save("guest", "games")
        self.save("user1", "accessories")
        self.assertTrue(self.invariant()[0])
        # Corrupt owner metadata only via the owner fixture: normal writers now
        # reject missing/departed membership before a visibility save.
        with self.connect("owner") as c:
            with db.change("test", "test", "Insert orphan switch fixture", conn=c) as (cur, _):
                cur.execute("insert into visibility (owner, thing, set_by, set_by_name) "
                            "values ('removed-space', 'decks', 'test', 'Test')")
        ok, warning, detail = self.invariant()
        self.assertFalse(ok)
        self.assertFalse(warning)
        self.assertIn("removed-space/decks", detail)

    def test_another_process_revocation_appears_after_one_minute_and_outage_fails_closed(self):
        now = [1000.0]
        self.store._clock = lambda: now[0]
        public = self.save()
        other = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())
        other.visibility_set("home", "decks", False, ACTOR, "Revoke in another process")
        self.assertEqual(self.store.visibility(), public)
        now[0] += pg.CACHE_SECONDS
        self.assertEqual(self.store.visibility(), {})
        public = self.save()
        self.store.breaker.trip("test outage")
        with mock.patch("decklab.db.conn.connect", side_effect=AssertionError("must not connect")):
            with self.assertRaises(Unavailable):
                self.store.visibility()
            self.assertEqual(self.store.visibility_cached(), public)
            now[0] += pg.CACHE_SECONDS
            self.assertEqual(self.store.visibility_cached(), {})
        self.store.clear_cache()
        self.assertEqual(self.store.visibility_cached(), {})

    def test_a_read_overlapping_a_flip_cannot_restore_the_old_cached_grant(self):
        public = self.save()
        self.store.clear_cache()
        real, raced = self.store._call, []
        def call(work):
            value = real(work)
            if not raced:
                raced.append(True)
                self.save(on=False)
            return value
        with mock.patch.object(self.store, "_call", call):
            self.assertEqual(self.store.visibility(), public)
        self.assertEqual(self.store.visibility_cached(), {})
        self.assertEqual(self.store.visibility(), {})

    def test_a_noop_batch_refreshes_the_cache_without_an_empty_audit_change(self):
        self.save()
        other = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())
        other.visibility_set("home", "decks", False, ACTOR, "Revoke in another process")
        before = self.store.activity()["changes"]
        with self.store.batch(ACTOR, "Confirm private"):
            self.store.visibility_set("home", "decks", False, ACTOR, "Confirm private")
        self.assertEqual(self.store.visibility_cached(), {})
        self.assertEqual(self.store.activity()["changes"], before)

    def test_auditing_and_read_only_privileges_are_enforced(self):
        import psycopg
        for role, statement in (("app", "insert into visibility(owner,thing,set_by_name) values ('home','decks','Test')"),
                                ("app", "truncate visibility"),
                                ("ro", "delete from visibility")):
            with self.subTest(role=role, statement=statement), self.connect(role) as c:
                with self.assertRaises(psycopg.Error):
                    c.execute(statement)

    def test_home_cli_flip_is_one_audited_change_and_member_requests_never_write(self):
        command = ["visibility", "set", "home", "decks", "on", "--dbname", self.dbname, "-m", "Fixture owner request"]
        with mock.patch.object(switches, "READY_THINGS", frozenset(values.THINGS)), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(command), 0)
            self.assertEqual(cli.main(command), 0)
            denied = ["visibility", "set", "guest", "decks", "on", "--dbname", self.dbname, "-m", "Forbidden"]
            self.assertEqual(cli.main(denied), 1)
        self.store.clear_cache()
        self.assertEqual(set(self.store.visibility()), {("home", "decks")})
        change, = self.store.activity()["changes"]
        self.assertEqual((change["actor"], change["source"], change["via"], change["message"], change["reason"]),
                         ("claude", "cli", None, "Make the home decks public", "Fixture owner request"))


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class BeforeVisibilityMigrationTests(unittest.TestCase):
    def test_missing_table_fails_closed_and_export_preserves_an_existing_csv(self):
        name = db_support.create_empty_database("pre_visibility")
        self.addCleanup(db_support.drop_database, name)
        early = folder(self, "decklab-pre-visibility-")
        for migration in migrate.available():
            if migration["version"] < 12:
                shutil.copy(migration["path"], early / migration["path"].name)
        migrate.apply(dbname=name, directory=early)
        setup.secure_database(name)
        profiles_sync.sync(listed=[HOME], dbname=name)
        store = pg.PgStore(dbname=name, breaker=pg.Breaker())
        for action in (store.visibility, lambda: store.visibility_set("home", "decks", True, ACTOR, "Test")):
            store.breaker.reset()
            with self.subTest(action=action), self.assertRaisesRegex(Unavailable, "migrate"):
                action()
            self.assertEqual(store.visibility_cached(), {})
            self.assertFalse(store.breaker.is_open())
            store.settings_put("matt", {"theme": "dark"}, ACTOR, "Unrelated existing setting")
        path = early / "export"
        (path / "tables").mkdir(parents=True)
        retained = path / "tables/public.visibility.csv"
        retained.write_bytes(b"previous export\n")
        export.write_tables(path, dbname=name)
        self.assertEqual(retained.read_bytes(), b"previous export\n")
        with db.connect("ro", dbname=name) as c:
            self.assertEqual(check._visibility(c)(), (True, False, "visibility unavailable until migration 0012"))


if __name__ == "__main__":
    unittest.main()
