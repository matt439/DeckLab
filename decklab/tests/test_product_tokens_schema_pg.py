"""Blank unknown product packing remains compatible before migration 0014; no live DB."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.db import conn as db, migrate, profiles_sync, setup
from decklab.lib import config, inventory
from decklab.lib.inventory import Op, Summary, files, model, paths, pg, rules
from decklab.lib.inventory import ops_collection  # noqa: F401  (registers the ordinary edit)
from decklab.lib.state import Actor, Invalid
from decklab.lib.state import pg as state_pg
from decklab.tests import db_support, household_config

ACTOR = Actor("claude", "Claude", source="cli")
TABLES = (*pg.INVENTORY_TABLES, "inventory_revision", "audit.change_set", "audit.row_change")


class ProductTokensSchemaPgTests(unittest.TestCase):
    def test_schema13_blank_import_read_write_export_nonblank_rollback_and_later_migration(self):
        folder = tempfile.TemporaryDirectory(prefix="decklab-product-schema13-")
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        config_path = root / "config.json"
        config_path.write_text(json.dumps({"profiles": household_config.PROFILES}), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", config_path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            self.addCleanup(patcher.stop)
        db_support.require_db(self)
        name = db_support.create_empty_database("product13")
        self.addCleanup(db_support.drop_database, name)
        self.assertTrue(name.startswith(db_support.PREFIX))
        early = root / "migrations"
        early.mkdir()
        for item in migrate.available():
            if item["version"] <= 13:
                shutil.copy(item["path"], early / Path(item["path"]).name)
        migrate.apply(dbname=name, directory=early)
        setup.secure_database(name)
        profiles_sync.sync(listed=[{**profile, "plays_as": profile.get("plays_as")}
                                  for profile in household_config.PROFILES], dbname=name)

        card = dict(name="Opt", set="dom", collector_number="60", finish="nonfoil", quantity="3", condition="", language="", notes="")
        status = {field: "" for field in rules.STATUS_FIELDS}
        status.update(file="fixture.csv", status="owned", intact="yes", sleeves="legacy sleeves", deck_box="legacy box", notes="Fixture note")
        token = {field: "" for field in rules.TOKEN_FIELDS}
        token.update(front="Dog", quantity="1", notes="Printing and reverse face unconfirmed")
        initial = files.build({paths.collection("home"): rules.csv_bytes([card], rules.FIELDS),
            paths.tokens("home"): rules.tokens_csv_bytes([token]),
            paths.STATUS: rules.csv_bytes([status], rules.STATUS_FIELDS),
            paths.WATCHLIST: rules.csv_bytes([], model.QUEUE_FIELDS),
            paths.product("fixture"): rules.csv_bytes([{**card, "quantity": "1"}], rules.FIELDS)})
        def state():
            with db.connect("ro", dbname=name) as c:
                return {table: c.execute(f"select row_to_json(t)::text from {table} t order by 1").fetchall() for table in TABLES}
        def packed(snapshot):
            rows = [{**row.as_dict(), "token_cards": "1 Dog"} for row in snapshot.status.rows]
            return snapshot.with_status_rows(rows)
        empty = state()
        with self.assertRaisesRegex(Invalid, "migration 0014"):
            pg.write_model(packed(initial), ACTOR, "Unsupported fixture import", dbname=name)
        self.assertEqual(state(), empty)
        pg.write_model(initial, ACTOR, "Import blank legacy packing", dbname=name)
        backend = pg.PgInventory(dbname=name, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(backend))
        loaded = backend.load()
        self.assertEqual(loaded.status.rows[0].token_cards, "")
        self.assertEqual(loaded.status.rows[0].notes, "Fixture note")
        self.assertEqual(initial.status.rows[0].token_cards, "")
        before = state()
        with self.assertRaisesRegex(Invalid, "migration 0014"):
            pg.write_model(packed(initial), ACTOR, "Unsupported replacement", dbname=name, replace=True)
        self.assertEqual(state(), before)

        class Mixed:
            kind = "fixture.product-token-schema"
            def run(self, snapshot):
                after = snapshot.with_collection("home", [{**row.as_dict(), "quantity": "4"} for row in snapshot.collection("home").rows])
                return packed(after), Summary("Fixture mixed product record")
        with self.assertRaisesRegex(Invalid, "migration 0014"):
            inventory.apply(Mixed(), ACTOR, "Unsupported mixed update")
        self.assertEqual(state(), before)
        original = loaded.collection("home").rows[0].as_dict()
        inventory.apply(Op("collection.edit", {"space": "home", "original": list(rules.ident(original)),
                                               "row": {**original, "notes": "Corrected fixture note"}}), ACTOR, "Unrelated supported update")
        self.assertEqual(state()["product_status"], before["product_status"])
        class BlankStatus:
            kind = "fixture.legacy-product-status"
            def run(self, snapshot):
                rows = [{**row.as_dict(), "notes": "Updated fixture note"} for row in snapshot.status.rows]
                return snapshot.with_status_rows(rows), Summary("Update supported legacy product status")
        inventory.apply(BlankStatus(), ACTOR, "Update blank legacy packing")
        self.assertEqual(backend.load().status.rows[0].as_dict(), {**status, "notes": "Updated fixture note"})
        with db.connect("ro", dbname=name) as c:
            legacy = c.execute("select status,intact,sleeves,deck_box,notes from product_status").fetchone()
        self.assertEqual(legacy, ("owned", "yes", "legacy sleeves", "legacy box", "Updated fixture note"))
        with db.connect("owner", dbname=name) as c:
            from decklab.db import export
            self.assertIn("magic/products/status.csv", export.inventory_files(c))
        migrate.apply(dbname=name)  # Only this disposable database gains the missing capability.
        inventory.apply(Mixed(), ACTOR, "Record supported product tokens")
        self.assertEqual(backend.load().status.rows[0].token_cards, "1 Dog")
        with db.connect("ro", dbname=name) as c:
            columns = c.execute("select sleeves,deck_box,notes,token_cards from product_status").fetchone()
        self.assertEqual(columns, ("legacy sleeves", "legacy box", "Updated fixture note", "1 Dog"))
