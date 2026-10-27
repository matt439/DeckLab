"""Precon token opt-in is atomic in a disposable PostgreSQL database, never the live one."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import config, inventory
from decklab.lib.api import precons as api
from decklab.lib.inventory import Op, model, paths, pg, rules
from decklab.lib.state import Actor
from decklab.lib.state import pg as state_pg
from decklab.lib.tokens import ops as token_ops
from decklab.tests import db_support
from decklab.tests import test_collection_edit as collection_fixture
from decklab.tests import test_precon_tokens as precon_fixture


ACTOR = Actor("claude", "Claude", source="cli")
TABLES = ("collection_card", "collection_import", "collection_import_content", "token_card", "deck", "deck_text",
          "deck_line", "deck_revision", "inventory_revision", "decks_revision", "audit.change_set", "audit.row_change")


class PreconTokensPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        # require_db() reads settings before per-test Sandbox setup. Keep even that check
        # on a synthetic config; normal local pgpass supplies only the existing test roles.
        folder = tempfile.TemporaryDirectory(prefix="decklab-precon-pg-config-")
        cls.addClassCleanup(folder.cleanup)
        config_path = Path(folder.name) / "config.json"
        config_path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", config_path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Precon integration requires a disposable test database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def setUp(self):
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = precon_fixture.PreconTokensTestCase()
        self.addCleanup(case.doCleanups)
        case.setUp()
        self.case = case
        source = case.backend.load()
        # Only the synthetic collections needed here: no products, decks, images, orders or
        # unrelated fixture history to import. The card index and MTGJSON cache stay local.
        collections = {}
        for space in ("home", "user2"):
            sheet = source.collection(space)
            collections[space] = model.Sheet(sheet.path, sheet.columns, tuple(sorted(sheet.rows, key=rules.sort_key)), sheet.exists)
        initial = model.Inventory("precon-pg-fixture", collections=collections,
            status=model.Sheet(paths.STATUS, tuple(rules.STATUS_FIELDS), (), True),
            watchlist=model.Sheet(paths.WATCHLIST, tuple(model.QUEUE_FIELDS), (), True))
        pg.write_model(initial, ACTOR, "Seed disposable precon collections", contents={},
                       dbname=self.dbname, decks=True, images={})
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def fresh(self):
        return pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker()).load()

    def sql(self, statement, args=()):
        with self.connect("ro") as connection:
            return connection.execute(statement, args).fetchall()

    def persisted_state(self):
        # Constant table names only, all read through this class's guarded throwaway dbname.
        with self.connect("ro") as connection:
            return {table: connection.execute(f"select row_to_json(t)::text from {table} t order by 1").fetchall()
                    for table in TABLES}

    def test_opt_in_persists_collection_tokens_raw_import_and_deck_in_one_audited_change(self):
        before_sets = self.sql("select id from audit.change_set order by id")
        home_before = self.fresh().collection("home")
        answer = self.case.add_tokens()
        self.assertEqual(answer["collection"]["added"], {"cards": 5, "rows": 3})
        self.assertEqual(answer["tokens"], {"cards": 4, "rows": 2})
        after_sets = self.sql("select id from audit.change_set order by id")
        self.assertEqual(len(after_sets), len(before_sets) + 1)
        change_set = after_sets[-1][0]
        touched = {row[0] for row in self.sql("select distinct table_name from audit.row_change where change_set_id = %s", (change_set,))}
        self.assertTrue({"collection_card", "collection_import", "token_card", "deck"} <= touched)
        saved = self.fresh()
        self.assertEqual(saved.collection("home"), home_before)
        elves = next(row for row in saved.collection("user2").rows if row["name"] == "Llanowar Elves")
        self.assertEqual(elves["quantity"], "4")
        token_rows = saved.token_set("user2").rows
        self.assertEqual([(row["front"], row["quantity"]) for row in token_rows], [("Dinosaur", "3"), ("Dinosaur", "1")])
        self.assertEqual(len({row.id for row in token_rows}), 2)
        self.assertTrue(all(row.id > 0 for row in token_rows))
        for row in token_rows:
            for field in ("back", "set", "front_collector_number", "back_collector_number", "finish", "front_details", "back_details"):
                self.assertEqual(row[field], "")
            self.assertIn("printing and reverse face unconfirmed", row["notes"])
        self.assertEqual(len(saved.imports["user2"]), 1)
        self.assertEqual(self.sql("select count(*) from collection_import_content"), [(1,)])
        deck_id = answer["deck"]["id"]
        deck = saved.deck(deck_id)
        self.assertEqual(deck_id, "user2/commander/ghalta-test-dinos")
        self.assertIn("- **Status:** built", deck.text)
        self.assertIn("| Sol Ring | 1 | 1 | 0 |", deck.text)
        self.assertEqual(self.sql("select revision, op, change_set_id from deck_revision where deck_id = %s", (deck_id,)),
                         [(1, "A", change_set)])

    def test_stale_token_sha_rolls_back_every_precon_table_and_audit_change(self):
        made = api.plan_add("user2", "TestDinos_TST", None, None, None, "Claude", add_tokens=True)
        inventory.apply(Op("tokens.add", {"space": "user2", "sha256": made["op"].params["tokens_sha256"],
                                          "row": made["op"].params["token_rows"][0], "separate": True}),
                        ACTOR, "Concurrent disposable token addition")
        before = self.persisted_state()
        with self.assertRaises(token_ops.Stale) as caught:
            inventory.apply(made["op"], ACTOR, "Stale disposable precon")
        refusal = made["refused"](caught.exception)
        self.assertEqual(refusal.status, 409)
        self.assertEqual(refusal.extra, {"token_conflict": True})
        self.assertEqual(self.persisted_state(), before)
        saved = self.fresh()
        self.assertIsNone(saved.deck(made["deck_id"]))
        self.assertEqual(saved.imports.get("user2", ()), ())
        self.assertEqual([(row["front"], row["quantity"]) for row in saved.token_set("user2").rows], [("Dinosaur", "3")])
