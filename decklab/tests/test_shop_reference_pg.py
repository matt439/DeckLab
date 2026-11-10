"""Reference/target receipts, schema compatibility and audit rollback in throwaway PostgreSQL."""
import json
import os
from pathlib import Path
import tempfile
from unittest import mock

from decklab.db import check, export, migrate
from decklab.lib import config, inventory, shop_reference_source, state
from decklab.lib.inventory import files, model, paths, pg, rules
from decklab.lib.state import pg as state_pg
from decklab.tests import db_support
from decklab.tests import test_collection_edit as support
from decklab.tests import test_shop_reference_api as fixture


class ShopReferencePgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-reference-pg-config-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(support.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Reference integration requires a disposable database")

    def setUp(self):
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname, support.ROLES["profiles"])
        case = fixture._ReferenceFixture()
        self.addCleanup(case.doCleanups)
        case.setUp()
        source = case.current()
        collections = {space: model.Sheet(sheet.path, sheet.columns, tuple(sorted(sheet.rows, key=rules.sort_key)), sheet.exists)
                       for space in ("home", "user2") if (sheet := source.collection(space))}
        initial = model.Inventory("reference-pg-fixture", collections=collections,
                    status=model.Sheet(paths.STATUS, tuple(rules.STATUS_FIELDS), (), True), watchlist=source.watchlist)
        pg.write_model(initial, fixture.ACTOR, "Seed disposable reference queue", contents={}, dbname=self.dbname, decks=True, images={})
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        case.backend = self.backend
        self.case = case
        self.addCleanup(inventory.use(self.backend))

    def fresh(self):
        return pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker()).load()

    def persisted(self):
        with self.connect("ro") as connection:
            return {table: connection.execute(f"select row_to_json(t)::text from {table} t order by 1").fetchall()
                    for table in ("watchlist_item", "collection_card", "purchase_order", "inventory_revision", "deck", "deck_text",
                                  "decks_revision", "audit.change_set", "audit.row_change")}

    def test_one_audit_each_roundtrip_and_no_collection_order_or_intent_changes(self):
        before = self.persisted()
        shown = self.case.preview()
        self.assertEqual(self.persisted(), before)
        self.case.apply(shown)
        target = self.case.preview([{"row": 1, "value": "2.50"}], kind="target")
        self.case.apply(target, kind="target")
        after = self.persisted()
        self.assertEqual(len(after["audit.change_set"]), len(before["audit.change_set"]) + 2)
        for table in ("collection_card", "purchase_order", "deck", "deck_text", "decks_revision"):
            self.assertEqual(after[table], before[table], table)
        row = self.fresh().watchlist.rows[0]
        self.assertEqual((row.listed_aud, row.checked, row.buy_under_aud, row.state, row.quantity),
                         ("3.00", "2026-11-11", "2.50", "ready", "3"))
        with self.connect("ro") as connection:
            copied = files.build(export.inventory_files(connection))
            self.assertEqual(copied.watchlist.rows[0].as_dict(), row.as_dict())
            self.assertTrue(check._round_trip(connection, self.fresh())()[0])
            touched = connection.execute("select distinct table_name from audit.row_change where change_set_id = "
                                         "(select max(id) from audit.change_set)").fetchall()
            self.assertEqual(touched, [("watchlist_item",)])

    def test_late_transaction_failure_rolls_back_reference_and_target_revision_and_audit(self):
        original = pg._diff
        def fail(*args):
            original(*args)
            raise RuntimeError("Injected reference transaction failure")
        for kind in ("reference", "target"):
            shown = self.case.preview() if kind == "reference" else self.case.preview([{"row": 1, "value": "2.50"}], kind=kind)
            before = self.persisted()
            with mock.patch.object(pg, "_diff", side_effect=fail), self.assertRaisesRegex(RuntimeError, "Injected reference transaction"):
                self.case.apply(shown, kind=kind)
            self.assertEqual(self.persisted(), before)
            self.case.apply(shown, kind=kind)

    def test_before_0026_blank_reads_and_reference_writes_survive_target_refusal_then_migrate(self):
        with self.connect("owner") as connection:
            db_support.roll_back_schema(connection, 25)
        self.assertFalse(self.fresh().targets_ready)
        self.assertEqual(self.fresh().watchlist.rows[0].buy_under_aud, "")
        shown = self.case.preview()
        self.case.apply(shown)
        before = self.persisted()
        self.case.assertApiError(400, self.case.preview, [{"row": 1, "value": "2.50"}], kind="target", contains="0026")
        self.assertEqual(self.persisted(), before)
        migrate.apply(dbname=self.dbname)
        fresh = self.fresh()
        self.assertTrue(fresh.targets_ready)
        self.assertEqual((fresh.watchlist.rows[0].listed_aud, fresh.watchlist.rows[0].buy_under_aud), ("3.00", ""))
        self.case.apply(self.case.preview([{"row": 1, "value": "2.50"}], kind="target"), kind="target")
        self.assertEqual(self.fresh().watchlist.rows[0].buy_under_aud, "2.50")

    def test_review_reads_fresh_preferences_from_another_store_without_erasing_verified_fallback(self):
        first = state_pg.PgStore(dbname=self.dbname, breaker=state_pg.Breaker())
        other = state_pg.PgStore(dbname=self.dbname, breaker=state_pg.Breaker())
        initial = {"listing_preferences": fixture.PREFERENCE}
        first.pricing_setting_put(initial, 0, fixture.ACTOR, "Seed disposable matching policy")
        self.addCleanup(state.use(first))
        shown = self.case.preview()
        changed = {"listing_preferences": {"minimum_condition": "NM", "english_only": True}}
        other.pricing_setting_put(changed, 1, fixture.ACTOR, "Change disposable matching policy")
        self.assertEqual(first.pricing_setting()["revision"], 1)
        before = self.persisted()
        self.case.assertApiError(409, self.case.apply, shown)
        self.assertEqual(first.pricing_setting_cached()["revision"], 2)
        self.assertEqual(self.persisted(), before)
        with mock.patch.object(first, "_call", side_effect=state.Unavailable("Synthetic outage")):
            with self.assertRaises(shop_reference_source.Unconfirmed):
                shop_reference_source.context(fresh=True)
        self.assertEqual(first.pricing_setting_cached()["revision"], 2)
