"""Mixed product/deck token plans are one audited change in disposable PostgreSQL."""
import json
import os
from pathlib import Path
import tempfile
from unittest import mock

from decklab.lib import config, inventory
from decklab.lib.api import token_plan as api
from decklab.lib.inventory import kit, ops_products, ops_token_plan, pg
from decklab.lib.state import pg as state_pg
from decklab.lib.tokens import ops as token_ops  # noqa: F401 (registers the racing token operation)
from decklab.tests import db_support, household_config
from decklab.tests.test_inventory_contract import adapt
from decklab.tests import test_token_plan_mixed as mixed

TABLES = ("deck", "deck_text", "deck_line", "deck_revision", "product_status", "token_card",
          "inventory_revision", "decks_revision", "audit.change_set", "audit.row_change")


class MixedTokenPlanPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-mixed-plan-config-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps({"profiles": household_config.PROFILES}), encoding="utf-8")
        for patch in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patch.start()
            cls.addClassCleanup(patch.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("A disposable mixed-token-plan database is required")
        db_support.seed_membership(cls.dbname, household_config.PROFILES)
        mixed.MixedPlanCase.setUpClass()

    def setUp(self):
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = mixed.MixedPlanCase()
        self.addCleanup(case.doCleanups)
        case.setUp()
        self.case = case
        pg.write_model(adapt(case.inventory.load()), mixed.ACTOR, "Seed disposable mixed token plan",
                       contents={}, dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def sql(self, query, params=()):
        with self.connect("ro") as connection:
            return connection.execute(query, params).fetchall()

    def persisted(self):
        with self.connect("ro") as connection:
            return {table: connection.execute(f"select row_to_json(t)::text from {table} t order by 1").fetchall()
                    for table in TABLES}

    def test_two_products_and_one_deck_save_in_one_audit_set(self):
        plan = self.case.preview()
        before = inventory.current()
        count = self.sql("select count(*) from audit.change_set")[0][0]
        answer = self.case.call(api.apply_plan, sha256=plan["sha256"])
        self.assertEqual(answer, {"saved": 1, "decks": ["casual/a"], "saved_products": 2, "products": list(mixed.STEMS)})
        self.assertEqual(self.sql("select count(*) from audit.change_set"), [(count + 1,)])
        change_id = self.sql("select max(id) from audit.change_set")[0][0]
        self.assertEqual(self.sql("select count(*) from audit.row_change where change_set_id=%s and table_name='product_status'",
                                 (change_id,)), [(2,)])
        self.assertEqual(self.sql("select count(*) from deck_revision where change_set_id=%s", (change_id,)), [(1,)])
        self.assertEqual(self.sql("select count(*) from audit.row_change where change_set_id=%s and table_name='token_card'",
                                 (change_id,)), [(0,)])
        fresh = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker()).load()
        self.assertEqual(fresh.tokens, before.tokens)
        self.assertTrue(all(ops_products.product_row(fresh, stem).text("token_cards") for stem in mixed.STEMS))
        again = self.case.preview()
        self.assertEqual(self.case.call(api.apply_plan, sha256=again["sha256"]), {"saved": 0, "decks": []})
        self.assertEqual(self.sql("select count(*) from audit.change_set"), [(count + 1,)])

    def test_late_invalid_product_and_staged_failure_preserve_every_table(self):
        _, op = self.case.operation()
        before = self.persisted()
        bad = [op.params["products"][0], {"stem": mixed.STEMS[1], "token_cards": "Broken record"}]
        with self.assertRaises(inventory.Invalid):
            inventory.apply(inventory.Op(op.kind, {**op.params, "products": bad}), mixed.ACTOR, "Invalid mixed fixture")
        self.assertEqual(self.persisted(), before)
        real = ops_products.set_tokens

        def fail_second(snapshot, **kwargs):
            if kwargs["stem"] == mixed.STEMS[1]:
                raise inventory.Invalid("Second disposable product refused")
            return real(snapshot, **kwargs)

        with mock.patch.object(ops_products, "set_tokens", side_effect=fail_second):
            with self.assertRaises(inventory.Invalid):
                inventory.apply(op, mixed.ACTOR, "Refuse staged mixed fixture")
        self.assertEqual(self.persisted(), before)

    def test_product_token_inventory_and_unwritten_deck_races_save_no_partial_plan(self):
        for source in ("product", "tokens", "deck"):
            _, stale = self.case.operation()
            snapshot = inventory.current()
            if source == "product":
                operation = inventory.Op(ops_products.KIND, {"stem": mixed.STEMS[0],
                    "sha256": kit.status_sha256(snapshot), "tokens_sha256": ops_products.token_sha256(snapshot),
                    "token_cards": "1 Zombie // Zombie Knight"})
            elif source == "tokens":
                row = snapshot.token_set("home").rows[0].as_dict()
                operation = inventory.Op("tokens.edit", {"space": "home", "sha256": ops_products.token_sha256(snapshot),
                    "base": row, "row": {**row, "quantity": str(int(row["quantity"]) + 1)}})
            else:
                stored = snapshot.deck("casual/queen")
                operation = inventory.Op("deck.save", {"deck_id": stored.id,
                    "base_sha256": stored.sha256, "text": stored.text + "\nChanged notes in an unwritten deck.\n"})
            inventory.apply(operation, mixed.ACTOR, f"Concurrent disposable {source} change")
            before = self.persisted()
            with self.subTest(source=source), self.assertRaises(ops_token_plan.PlanChanged):
                inventory.apply(stale, mixed.ACTOR, "Refuse stale mixed fixture")
            self.assertEqual(self.persisted(), before)
