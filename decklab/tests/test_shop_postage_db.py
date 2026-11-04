"""The shops' postage (E5-S27, migration 0021) in disposable databases: the store, export and the nightly check.

A database integration test: it skips under the default fixture guards (scripts/test_fixtures.py).
"""
import csv
import io
import json
import shutil
import tempfile
from pathlib import Path

from decklab.db import backup, check, conn as db, export
from decklab.lib.state import Actor, Conflict
from decklab.lib.state import pg
from decklab.tests import db_support

ACTOR = Actor("test", "Test", source="cli")
RULES = {"mtgmate": {"postage_aud": "8.5", "free_over_aud": "100"}, "gamesportal": {"postage_aud": "", "free_over_aud": None}}
SAVED = {"v": 1, "shops": {"mtgmate": {"postage_aud": "8.50", "free_over_aud": "100.00"}}}


class ShopPostageDbTests(db_support.DbTestCase):

    def setUp(self):
        db_support.reset(self.dbname)
        self.store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())

    def invariant(self):
        with self.connect("ro") as c:
            return check._shop_postage(c)()

    def test_saved_whole_with_a_revision_unchanged_writes_nothing_and_stale_is_refused(self):
        self.assertEqual(self.store.shop_postage(), {"revision": 0, "postage": {"v": 1, "shops": {}}})
        self.assertEqual(self.invariant(), (True, False, "not configured"))
        saved = self.store.shop_postage_put(RULES, 0, ACTOR, "Set test postage")
        self.assertEqual(saved, {"revision": 1, "postage": SAVED})
        self.assertEqual(self.store.shop_postage(), saved)
        self.assertEqual(self.store.shop_postage_put(SAVED, 1, ACTOR, "Same again"), saved)
        with self.assertRaises(Conflict):
            self.store.shop_postage_put({}, 0, ACTOR, "Stale")
        with self.connect("ro") as c:
            changes = c.execute("select count(*) from audit.row_change where table_name = 'shop_postage'").fetchone()[0]
        self.assertEqual(changes, 1)
        self.assertEqual(self.invariant(), (True, False, "1 shops' postage at revision 1"))

    def test_export_and_backup_digest_cover_the_record(self):
        self.store.shop_postage_put(RULES, 0, ACTOR, "Set test postage")
        folder = Path(tempfile.mkdtemp(prefix="decklab-postage-export-"))
        self.addCleanup(shutil.rmtree, folder)
        export.write_tables(folder, dbname=self.dbname)
        row, = list(csv.DictReader(io.StringIO((folder / "tables/public.shop_postage.csv").read_text(encoding="utf-8"))))
        self.assertEqual((row["id"], row["revision"], json.loads(row["content"])), ("true", "1", SAVED))
        with self.connect("ro") as c:
            self.assertEqual(backup.count_rows(c)["public.shop_postage"], 1)

    def test_invariant_rejects_a_record_not_in_its_saved_form(self):
        from psycopg.types.json import Jsonb
        self.store.shop_postage_put(RULES, 0, ACTOR, "Set test postage")
        with self.connect("owner") as c:
            with db.change("test", "test", "break saved test postage", conn=c) as (cur, _):
                cur.execute("update shop_postage set content = %s", (Jsonb({"v": 1, "shops": {"mtgmate": {"postage_aud": "8.5"}}}),))
        ok, warning, detail = self.invariant()
        self.assertFalse(ok)
        self.assertIn("complete saved form", detail)
