"""Product packing persists and refuses races in a guarded disposable PostgreSQL database."""
import dataclasses
import json
import os
from pathlib import Path
import tempfile
from unittest import mock

from decklab.lib import config, inventory
from decklab.lib.inventory import kit, ops_products, pg, rules
from decklab.lib.state import pg as state_pg
from decklab.lib.tokens import ops as token_ops  # noqa: F401 (registers the concurrent token operation)
from decklab.tests import db_support
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_inventory_contract import adapt
from decklab.tests.test_product_tokens import ACTOR, PACKED, STEM, ProductTokensCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401


class ProductTokensPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-product-token-config-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(ROLES), encoding="utf-8")
        for patch in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patch.start()
            cls.addClassCleanup(patch.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("A disposable product-token test database is required")
        db_support.seed_membership(cls.dbname, ROLES["profiles"])

    def setUp(self):
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = ProductTokensCase()
        self.addCleanup(case.doCleanups)
        case.setUp()
        self.case = case
        initial = adapt(case.inventory.load())
        initial = initial.replace(tokens={space: dataclasses.replace(sheet,
            rows=tuple(sorted(sheet.rows, key=lambda r: rules.token_sort_key(r.as_dict()))), sorted=True)
            for space, sheet in initial.tokens.items()})
        pg.write_model(initial, ACTOR, "Seed disposable product tokens", contents={}, dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def sql(self, query, params=()):
        with self.connect("ro") as connection:
            return connection.execute(query, params).fetchall()

    def fresh(self):
        return pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker()).load()

    def test_record_is_one_audited_status_change_without_token_or_deck_writes(self):
        before = inventory.current()
        count = self.sql("select count(*) from audit.change_set")[0][0]
        inventory.apply(self.case.op(), ACTOR, "Pack disposable product tokens")
        after = self.fresh()
        self.assertEqual(ops_products.product_row(after, STEM).text("token_cards"), PACKED)
        self.assertEqual(self.sql("select token_cards, sleeves, deck_box, notes from product_status where file=%s",
                                 (f"{STEM}.csv",)), [(PACKED, "old sleeves", "old box", "Keep this note")])
        self.assertEqual(after.tokens, before.tokens)
        self.assertEqual(after.decks_revision, before.decks_revision)
        self.assertEqual(self.sql("select count(*) from audit.change_set"), [(count + 1,)])
        self.assertEqual(self.sql("select distinct table_name from audit.row_change where change_set_id=(select max(id) from audit.change_set)"),
                         [("product_status",)])
        inventory.apply(self.case.op(), ACTOR, "No-op disposable product tokens")
        self.assertEqual(self.sql("select count(*) from audit.change_set"), [(count + 1,)])

    def test_status_race_after_initial_receipt_cannot_overwrite_or_add_audit(self):
        stale = self.case.op()
        current = inventory.current()
        inventory.apply(inventory.Op(ops_products.KIND, {"stem": STEM, "sha256": kit.status_sha256(current),
                        "tokens_sha256": ops_products.token_sha256(current), "token_cards": "1 Angel // The Monarch"}),
                        ACTOR, "Concurrent disposable product packing")
        count = self.sql("select count(*) from audit.change_set")[0][0]
        with self.assertRaises(inventory.Conflict):
            inventory.apply(stale, ACTOR, "Refuse stale disposable packing")
        self.assertEqual(ops_products.product_row(self.fresh(), STEM).text("token_cards"), "1 Angel // The Monarch")
        self.assertEqual(self.sql("select count(*) from audit.change_set"), [(count,)])

    def test_token_inventory_race_refuses_packing_without_an_extra_audit(self):
        stale = self.case.op()
        current = inventory.current()
        row = current.token_set("home").rows[0].as_dict()
        inventory.apply(inventory.Op("tokens.edit", {"space": "home", "sha256": ops_products.token_sha256(current),
                        "base": row, "row": {**row, "quantity": str(int(row["quantity"]) + 1)}}),
                        ACTOR, "Concurrent disposable token count")
        count = self.sql("select count(*) from audit.change_set")[0][0]
        with self.assertRaises(inventory.Conflict):
            inventory.apply(stale, ACTOR, "Refuse stale token inventory receipt")
        self.assertEqual(ops_products.product_row(self.fresh(), STEM).text("token_cards"), "")
        self.assertEqual(self.sql("select count(*) from audit.change_set"), [(count,)])
