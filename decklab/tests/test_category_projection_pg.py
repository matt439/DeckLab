"""Canonical category projection/backfill/save/check parity in disposable PostgreSQL only."""
import json
import os
from pathlib import Path
import tempfile
from unittest import mock

from decklab.db import check, export, migrate, migration_categories
from decklab.lib import access, api, config, inventory
from decklab.lib.inventory import model, paths, pg, pg_categories, rules
from decklab.lib.state import Actor
from decklab.lib.state import pg as state_pg
from decklab.tests import db_support
from decklab.tests import test_collection_edit as profiles_fixture
from decklab.tests import test_editor as fixture

ACTOR = Actor("matt", "Matt", source="test")
ID = "casual/table-test"


class CategoryProjectionPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-category-pg-config-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(profiles_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Category projection integration requires a disposable database")

    def setUp(self):
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        db_support.seed_membership(self.dbname, profiles_fixture.ROLES["profiles"])
        case = fixture.EditorTestCase()
        self.addCleanup(case.doCleanups)
        case.setUp()
        source = inventory.current()
        collections = {space: model.Sheet(sheet.path, sheet.columns, tuple(sorted(sheet.rows, key=rules.sort_key)), sheet.exists)
                       for space in ("home", "user2") if (sheet := source.collection(space))}
        initial = model.Inventory("category-pg-fixture", collections=collections,
                  status=model.Sheet(paths.STATUS, tuple(rules.STATUS_FIELDS), (), True),
                  watchlist=model.Sheet(paths.WATCHLIST, tuple(model.QUEUE_FIELDS), (), True), decks={ID: source.deck(ID)})
        pg.write_model(initial, ACTOR, "Seed disposable category deck", contents={}, dbname=self.dbname, decks=True, images={})
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))
        self.case = case

    def fresh(self):
        return pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker()).load()

    def rows(self, query):
        with self.connect("ro") as connection:
            return connection.execute(query).fetchall()

    def persisted(self):
        with self.connect("ro") as connection:
            return {table: connection.execute(f"select row_to_json(t)::text from {table} t order by 1").fetchall()
                    for table in ("collection_card", "inventory_revision", "decks_revision", "deck", "deck_text", "deck_revision",
                                  "audit.change_set", "audit.row_change")}

    def tag(self):
        with access.using(None), access.viewing("matt"):
            view = api.edit_view(ID)
            sent = {"target": view["lists"]["target"]}
            sent["target"]["Deck"][0]["category"] = "Ramp"
            return api.save_deck(self.case.body(id=ID, sha256=view["sha256"], lists=sent))

    def old_schema(self):
        with self.connect("owner") as connection:
            db_support.roll_back_schema(connection, 26)
        with self.connect("ro") as connection:
            self.assertFalse(pg_categories.ready(connection))

    def test_category_only_save_updates_projection_in_one_audit_without_table_or_marker_changes(self):
        before, text = self.persisted(), self.fresh().deck(ID).text
        saved = self.tag()
        self.assertTrue(saved["saved"])
        self.assertIsNone(saved["marked"])
        self.assertFalse(saved["table"]["rewritten"])
        after = self.persisted()
        self.assertEqual(len(after["audit.change_set"]), len(before["audit.change_set"]) + 1)
        self.assertEqual(after["collection_card"], before["collection_card"])
        self.assertEqual(after["inventory_revision"], before["inventory_revision"])
        self.assertEqual(self.fresh().deck(ID).text.replace(" #Ramp", ""), text)
        self.assertEqual(self.rows("select category from deck_line where deck_id = 'casual/table-test' "
                                   "and name = 'Llanowar Elves' and version = 'target'"), [("Ramp",)])
        with self.connect("ro") as connection:
            self.assertTrue(check._deck_lines(connection)()[0])
            self.assertTrue(check._round_trip(connection, self.fresh())()[0])
            copied = export.inventory_files(connection)
            self.assertIn(b"#Ramp", copied["magic/decks/casual/table-test.md"])
        with self.connect("owner") as connection:
            connection.execute("update deck_line set category = 'Draw' where category = 'Ramp'")
        with self.connect("ro") as connection:
            self.assertFalse(check._deck_lines(connection)()[0])

    def test_old_writer_keeps_text_then_migration_backfills_existing_categories_without_deck_history(self):
        self.old_schema()
        self.tag()
        before = self.persisted()
        applied = migrate.apply(dbname=self.dbname)
        self.assertEqual(applied, ["0027_deck_line_categories.sql"])
        after = self.persisted()
        for table in before.keys() - {"audit.change_set"}:
            self.assertEqual(after[table], before[table], table)
        self.assertEqual(len(after["audit.change_set"]), len(before["audit.change_set"]) + 1)
        self.assertEqual(self.rows("select category from deck_line where name = 'Llanowar Elves' and version = 'target'"), [("Ramp",)])
        with self.connect("ro") as connection:
            self.assertTrue(check._deck_lines(connection)()[0])

    def test_late_backfill_failure_rolls_back_column_projection_audit_and_migration_receipt(self):
        self.old_schema()
        self.tag()
        before, original = self.persisted(), migration_categories.backfill
        def fail(cur):
            original(cur)
            raise RuntimeError("Injected category backfill failure")
        with mock.patch.object(migration_categories, "backfill", side_effect=fail), self.assertRaisesRegex(RuntimeError, "Injected category"):
            migrate.apply(dbname=self.dbname)
        self.assertEqual(self.persisted(), before)
        with self.connect("ro") as connection:
            self.assertFalse(pg_categories.ready(connection))
            self.assertEqual(connection.execute("select count(*) from schema_migration where version = 27").fetchone(), (0,))
        migrate.apply(dbname=self.dbname)

    def test_mismatched_legacy_projection_refuses_before_any_backfill_and_reports_check_guidance(self):
        self.old_schema()
        self.tag()
        with self.connect("owner") as connection:
            connection.execute("update deck_line set quantity = quantity + 1 where name = 'Llanowar Elves'")
        before = self.persisted()
        with self.assertRaisesRegex(migrate.MigrationError, "Run python -m decklab.db check"):
            migrate.apply(dbname=self.dbname)
        self.assertEqual(self.persisted(), before)
        with self.connect("ro") as connection:
            self.assertFalse(pg_categories.ready(connection))
        with self.connect("owner") as connection:
            connection.execute("update deck_line set quantity = quantity - 1 where name = 'Llanowar Elves'")
        migrate.apply(dbname=self.dbname)
