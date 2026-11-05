"""The price settings (E11-S53, migration 0022) in disposable databases: the store, export, the
backup digest and the nightly check.

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
from decklab.lib.state import pricing as rules_pricing
from decklab.tests import db_support

ACTOR = Actor("test", "Test", source="cli")
SAVED = {"v": 1, "currency": "EUR", "shops": ["mtgmate"]}


class PricingSettingDbTests(db_support.DbTestCase):

    def setUp(self):
        db_support.reset(self.dbname)
        self.store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())

    def invariant(self):
        with self.connect("ro") as c:
            return check._pricing_setting(c)()

    def test_saved_whole_with_a_revision_unchanged_writes_nothing_and_stale_is_refused(self):
        self.assertEqual(self.store.pricing_setting(), {"revision": 0, "pricing": rules_pricing.EMPTY})
        self.assertEqual(self.invariant(), (True, False, "not set (config.json's apply)"))
        saved = self.store.pricing_setting_put({"currency": " eur", "shops": ["MTGMate"]}, 0, ACTOR, "Set test prices")
        self.assertEqual(saved, {"revision": 1, "pricing": SAVED})
        self.assertEqual(self.store.pricing_setting(), saved)
        self.assertEqual(self.store.pricing_setting_cached(), saved)
        self.assertEqual(self.store.pricing_setting_put(SAVED, 1, ACTOR, "Same again"), saved)
        with self.assertRaises(Conflict):
            self.store.pricing_setting_put({"currency": "GBP"}, 0, ACTOR, "Stale")
        with self.connect("ro") as c:
            changes = c.execute("select count(*) from audit.row_change where table_name = 'pricing_setting'").fetchone()[0]
        self.assertEqual(changes, 1)
        self.assertEqual(self.invariant(), (True, False, "currency EUR at revision 1"))

    def test_export_and_backup_digest_cover_the_record(self):
        self.store.pricing_setting_put(SAVED, 0, ACTOR, "Set test prices")
        folder = Path(tempfile.mkdtemp(prefix="decklab-pricing-export-"))
        self.addCleanup(shutil.rmtree, folder)
        export.write_tables(folder, dbname=self.dbname)
        row, = list(csv.DictReader(io.StringIO((folder / "tables/public.pricing_setting.csv").read_text(encoding="utf-8"))))
        self.assertEqual((row["id"], row["revision"], json.loads(row["content"])), ("true", "1", SAVED))
        with self.connect("ro") as c:
            self.assertEqual(backup.count_rows(c)["public.pricing_setting"], 1)

    def test_invariant_rejects_a_record_not_in_its_saved_form(self):
        from psycopg.types.json import Jsonb
        self.store.pricing_setting_put(SAVED, 0, ACTOR, "Set test prices")
        with self.connect("owner") as c:
            with db.change("test", "test", "break saved test prices", conn=c) as (cur, _):
                cur.execute("update pricing_setting set content = %s",
                            (Jsonb({"v": 1, "currency": "EUR", "shops": ["gamesportal", "mtgmate"]}),))
        ok, warning, detail = self.invariant()
        self.assertFalse(ok)
        self.assertIn("complete saved form", detail)
