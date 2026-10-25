"""Commander-night notes in disposable databases, exports and nightly invariants."""
import csv
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from decklab.db import backup, check, conn as db, export, migrate, profiles_sync, setup
from decklab.lib.state import Actor, Unavailable
from decklab.lib.state import pg
from decklab.tests import db_support

ACTOR = Actor("test", "Test", source="cli")
NIGHT = {"name": "Thursday Commander", "venue": "Café, upstairs", "target_bracket": 2,
         "published_min": 2, "published_max": 3,
         "house_rules": 'Ask first about "extra turns".\nBring tokens.', "checked_on": "2026-10-15"}


def _folder(test, prefix):
    folder = Path(tempfile.mkdtemp(prefix=prefix))
    test.addCleanup(shutil.rmtree, folder)
    return folder


class CommanderNightMaintenanceTests(db_support.DbTestCase):

    def setUp(self):
        db_support.reset(self.dbname)
        self.store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())

    def save(self, night=NIGHT, revision=0):
        return self.store.commander_night_put(night, revision, ACTOR, "Save test night")

    def invariant(self):
        with self.connect("ro") as c:
            return check._commander_night(c)()

    def test_export_round_trips_the_complete_notes_and_retains_a_clear_revision(self):
        saved = self.save()
        self.assertEqual(self.store.commander_night(), saved)
        folder = _folder(self, "decklab-night-export-")
        export.write_tables(folder, dbname=self.dbname)
        exported = folder / "tables/public.commander_night.csv"
        first = exported.read_bytes()
        self.assertIn("Café".encode(), first)
        row, = list(csv.DictReader(io.StringIO(first.decode("utf-8"))))
        self.assertEqual((row["id"], row["revision"]), ("true", "1"))
        self.assertEqual(json.loads(row["content"]), saved["night"])
        export.write_tables(folder, dbname=self.dbname)
        self.assertEqual(exported.read_bytes(), first)

        cleared = self.store.commander_night_put(None, 1, ACTOR, "Clear test night", reason="No longer attending")
        self.assertEqual(self.store.commander_night(), cleared)
        self.assertEqual(cleared, {"night": None, "revision": 2})
        export.write_tables(folder, dbname=self.dbname)
        self.assertEqual(exported.read_bytes(), b"id,revision,content\ntrue,2,\n")

    def test_backup_metrics_include_notes_and_detect_different_content_with_one_row(self):
        with self.connect("ro") as c:
            empty = backup.digest_rows(c)["public.commander_night"]
        self.save()
        with self.connect("ro") as c:
            counts = backup.count_rows(c)
            old = backup.digest_rows(c)
        self.assertEqual(counts["public.commander_night"], 1)
        self.assertNotEqual(old["public.commander_night"], empty)
        self.save(dict(NIGHT, house_rules="Ask before infinite combos."), revision=1)
        with self.connect("ro") as c:
            self.assertEqual(backup.count_rows(c)["public.commander_night"], counts["public.commander_night"])
            current = backup.digest_rows(c)
        # Audit rows also change; compare the note's digest to prove the note itself is covered.
        table = "public.commander_night"
        self.assertEqual(backup.compare_digests({table: old[table]}, {table: current[table]}),
                         ["public.commander_night's rows differ from the ones dumped"])

    def test_invariant_accepts_unconfigured_dated_notes_and_a_clear_tombstone(self):
        self.assertEqual(self.invariant(), (True, False, "not configured"))
        self.save()
        self.assertEqual(self.invariant(), (True, False, "valid notes at revision 1"))
        self.store.commander_night_put(None, 1, ACTOR, "Clear test night", reason="No longer attending")
        self.assertEqual(self.invariant(), (True, False, "cleared at revision 2"))

    def test_invariant_rejects_invalid_or_incomplete_stored_notes(self):
        from psycopg.types.json import Jsonb
        self.save()
        broken = [(dict(NIGHT, checked_on="2026-02-30"), "YYYY-MM-DD"),
                  (dict(NIGHT, published_min=3, published_max=2), "lower bracket"),
                  ({"name": "Incomplete"}, "complete saved form")]
        for content, message in broken:
            with self.subTest(content=content):
                with self.connect("owner") as c:
                    with db.change("test", "test", "break saved test notes", conn=c) as (cur, _):
                        cur.execute("update commander_night set content = %s", (Jsonb(content),))
                ok, warning, detail = self.invariant()
                self.assertFalse(ok)
                self.assertFalse(warning)
                self.assertIn(message, detail)

    def test_invariant_uses_its_supplied_repeatable_read_snapshot(self):
        from psycopg import IsolationLevel
        with self.connect("ro", autocommit=False) as c:
            c.isolation_level = IsolationLevel.REPEATABLE_READ
            c.read_only = True
            self.assertEqual(check._commander_night(c)(), (True, False, "not configured"))
            self.save()
            self.assertEqual(check._commander_night(c)(), (True, False, "not configured"))
        self.assertEqual(self.invariant(), (True, False, "valid notes at revision 1"))

    def test_default_state_reset_clears_notes_and_the_retained_revision(self):
        self.save()
        self.store.commander_night_put(None, 1, ACTOR, "Clear test night", reason="No longer attending")
        db_support.reset(self.dbname)
        self.assertEqual(self.store.commander_night(), {"night": None, "revision": 0})


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class BeforeCommanderNightMigrationTests(unittest.TestCase):

    def test_unmigrated_export_keeps_the_prior_notes_csv_and_does_not_mark_inventory_missing(self):
        name = db_support.create_empty_database("pre_night")
        self.addCleanup(db_support.drop_database, name)
        early = _folder(self, "decklab-pre-night-")
        for migration in migrate.available():
            if migration["version"] < 11:
                shutil.copy(migration["path"], early / Path(migration["path"]).name)
        migrate.apply(dbname=name, directory=early)
        setup.secure_database(name)
        profiles_sync.sync(listed=[{"id": "matt", "name": "Matt", "role": "admin", "space": "home",
                                   "plays_as": "user", "emails": []}], dbname=name)
        store = pg.PgStore(dbname=name, breaker=pg.Breaker())
        self.assertEqual(store.settings("matt"), {})
        for action in (store.commander_night,
                       lambda: store.commander_night_put(NIGHT, 0, ACTOR, "Save test night")):
            with self.subTest(action=action):
                trips = store.breaker.trips
                with self.assertRaisesRegex(Unavailable, "migrate"):
                    action()
                self.assertEqual(store.breaker.trips, trips)
                self.assertFalse(store.breaker.is_open())
                store.settings_put("matt", {"theme": "dark"}, ACTOR, "Save existing test setting")
                self.assertEqual(store.settings("matt"), {"theme": "dark"})
                store.settings_put("matt", {"theme": "light"}, ACTOR, "Change existing test setting")
                self.assertEqual(store.settings("matt"), {"theme": "light"})
        folder = early / "export"
        tables = folder / "tables"
        tables.mkdir(parents=True)
        preserved = tables / "public.commander_night.csv"
        preserved.write_bytes(b"prior notes export\n")
        export.write_tables(folder, dbname=name)
        self.assertEqual(preserved.read_bytes(), b"prior notes export\n")
        self.assertTrue((tables / "public.collection_card.csv").is_file())
        self.assertNotIn("public.commander_night", export.INVENTORY_TABLES)
        with db.connect("ro", dbname=name) as c:
            self.assertEqual(check._commander_night(c)(),
                             (True, False, "Commander-night notes unavailable until migration 0011"))


if __name__ == "__main__":
    unittest.main()
