"""A space's storage setup (E8-S25, migration 0028) in disposable databases: PgStore's read and
write with a revision and the audit trail, the nightly check and the export.

A database integration test: it skips under the default fixture guards (scripts/test_fixtures.py).
"""
import csv
import io
import json
import shutil
import tempfile
from pathlib import Path

from decklab.db import check, conn as db, export
from decklab.lib.state import Actor, Conflict, Invalid, pg
from decklab.tests import db_support

ACTOR = Actor("test", "Test", source="cli")
BINDER = {"name": "Binder", "kind": "binder", "capacity": 360, "sections": ["Page 1"], "order": "set", "sleeved": True}
SAVED = {"v": 1, "default": "binder", "containers": [dict(BINDER, id="binder", holds={})]}


class SpaceStorageDbTests(db_support.DbTestCase):

    def setUp(self):
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname)
        self.store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())

    def invariant(self):
        with self.connect("ro") as c:
            return check._space_storage(c)()

    def test_saved_whole_per_space_with_a_revision_unchanged_writes_nothing(self):
        self.assertEqual(self.store.space_storage("user2"),
                         {"space": "user2", "revision": 0, "storage": None, "ready": True})
        self.assertEqual(self.invariant()[:2], (True, False))
        saved = self.store.space_storage_put("user2", {"default": "Binder", "containers": [BINDER]}, 0, ACTOR, "Set")
        self.assertEqual(saved, {"space": "user2", "revision": 1, "storage": SAVED, "ready": True})
        self.assertEqual(self.store.space_storage("user2"), saved)
        self.assertEqual(self.store.space_storage("home")["storage"], None)
        self.assertEqual(self.store.space_storage_put("user2", SAVED, 1, ACTOR, "Same again"), saved)
        with self.assertRaises(Conflict):
            self.store.space_storage_put("user2", {"containers": []}, 0, ACTOR, "Stale")
        emptied = self.store.space_storage_put("home", {"containers": []}, 0, ACTOR, "Opt out")
        self.assertEqual(emptied["storage"], {"v": 1, "default": None, "containers": []})
        with self.connect("ro") as c:
            rows = c.execute("select row_key->>'space_id', op from audit.row_change "
                             "where table_name = 'space_storage' order by id").fetchall()
        self.assertEqual(rows, [("user2", "INSERT"), ("home", "INSERT")])
        self.assertEqual(self.invariant(), (True, False, "2 spaces' storage setups"))

    def test_a_space_that_doesnt_exist_is_refused(self):
        with self.assertRaises(Invalid):
            self.store.space_storage_put("nobody", {"containers": []}, 0, ACTOR, "Set")

    def test_export_covers_the_record(self):
        self.store.space_storage_put("guest", [BINDER], 0, ACTOR, "Set")
        folder = Path(tempfile.mkdtemp(prefix="decklab-storage-export-"))
        self.addCleanup(shutil.rmtree, folder)
        export.write_tables(folder, dbname=self.dbname)
        row, = list(csv.DictReader(io.StringIO((folder / "tables/public.space_storage.csv").read_text(encoding="utf-8"))))
        self.assertEqual((row["space_id"], row["revision"]), ("guest", "1"))
        self.assertEqual(json.loads(row["content"])["containers"][0]["id"], "binder")

    def test_invariant_rejects_a_record_not_in_its_saved_form(self):
        from psycopg.types.json import Jsonb
        self.store.space_storage_put("home", [BINDER], 0, ACTOR, "Set")
        with self.connect("owner") as c:
            with db.change("test", "test", "break the saved storage", conn=c) as (cur, _):
                cur.execute("update space_storage set content = %s",
                            (Jsonb({"v": 1, "default": None, "containers": [{"name": "Binder"}]}),))
        ok, warning, detail = self.invariant()
        self.assertFalse(ok)
        self.assertIn("complete saved form", detail)
