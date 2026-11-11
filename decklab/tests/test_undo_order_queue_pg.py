"""Real coupled-order trigger receipts, current-text table refresh and rollback in disposable DBs."""
import json
import os
from pathlib import Path
import tempfile
from unittest import mock

from decklab.lib import config, inventory
from decklab.lib.inventory import model, paths, pg, rules, undo, undo_order_queue_verify
from decklab.lib.state import Actor
from decklab.lib.state import pg as state_pg
from decklab.tests import db_support
from decklab.tests import test_collection_edit as fixture
from decklab.tests import test_undo_order_queue as facts

ACTOR = Actor("matt", "Matt", source="test")
DECK_ID = "casual/queue-fixture"
TEXT = """# Queue fixture

- **Format:** Casual 60-card, 1v1
- **Played by:** wife
- **Status:** building
- **Sleeves:** private-legacy-sleeves
- **Deck box:** private-legacy-box

## Decklist

```
Deck
4 Llanowar Elves (FDN) 227 #Ramp
20 Forest
```

## Owned vs needed

| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |
|---|---|---|---|---|---|---|
| Llanowar Elves | 4 | 1 | 3 | | | Keep this handwritten note |
| **Total to buy** | | | **3** | | | Keep the total note |

## Notes

Current authored game plan.
"""


class OrderQueueUndoPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-order-queue-undo-pg-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Order and queue Undo requires a disposable test database")

    def setUp(self):
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        db_support.seed_membership(self.dbname, fixture.ROLES["profiles"])
        case = fixture.CollectionEditTestCase()
        self.addCleanup(case.doCleanups)
        case.setUp()
        fixture.ce._require_cards()
        self.case = case
        initial = model.Inventory("order-queue-pg-fixture", status=model.Sheet(paths.STATUS, tuple(rules.STATUS_FIELDS), (), True),
                    watchlist=model.Sheet(paths.WATCHLIST, tuple(model.QUEUE_FIELDS), (model.WatchRow.make(facts.queued()),), True),
                    decks={DECK_ID: model.Deck("home", "casual", "queue-fixture", TEXT)})
        initial = initial.with_collection("home", [{**facts.card(1), "set": "fdn", "collector_number": "227", "notes": ""}])
        pg.write_model(initial, ACTOR, "Seed disposable order and queue", contents={}, dbname=self.dbname, decks=True, images={})
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def fresh(self):
        return pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker()).load()

    def sql(self, text, params=()):
        with self.connect("ro") as connection:
            return connection.execute(text, params).fetchall()

    def latest(self):
        return self.sql("select max(id) from audit.change_set")[0][0]

    def persisted(self):
        with self.connect("ro") as connection:
            return {table: connection.execute(f"select row_to_json(t)::text from {table} t order by 1").fetchall()
                    for table in ("purchase_order", "order_component", "order_card_item", "order_token_item", "product", "product_item",
                                  "product_status", "watchlist_item", "collection_card", "token_card", "deck", "deck_text", "deck_line",
                                  "deck_revision", "decks_revision", "inventory_revision", "audit.change_set", "audit.row_change")}

    def add(self, quantity=3):
        after, summary = inventory.apply(inventory.Op("order.add", {"record": {"id": facts.OID, "seller": "Fixture shop", "ordered_on": "2026-11-11"},
            "cards": {"rows": [facts.card(quantity)]}, "fulfils": [{"select": "#1", "quantity": quantity}]}), ACTOR, "Record synthetic fulfilling order")
        self.assertIsNone(summary.extra["tables"]["error"])
        return self.latest(), after

    def undo(self, source, plan=None):
        plan = inventory.undo_review(source, "home") if plan is None else plan
        return inventory.apply(inventory.Op("inventory.undo_order_queue", {"change_id": source, "space": "home", "expect": plan["expect"],
            "reason": facts.REASON}), ACTOR, "Undo synthetic order and queue", reason=facts.REASON)

    def test_add_fulfilment_inverse_has_fresh_queue_id_real_order_and_deck_audit_and_keeps_current_text(self):
        source, ordered = self.add()
        self.assertEqual({row[0] for row in self.sql("select distinct table_name from audit.row_change where change_set_id=%s", (source,))},
                         {"purchase_order", "order_component", "order_card_item", "watchlist_item", "deck"})
        original_audit = self.sql("select row_to_json(t)::text from audit.row_change t where change_set_id=%s order by id", (source,))
        old_id = self.sql("select (before->>'id')::int from audit.row_change where change_set_id=%s and table_name='watchlist_item'", (source,))[0][0]
        # A later authored edit is retained; only its live availability table is recomputed.
        current = ordered.deck(DECK_ID)
        inventory.apply(inventory.Op("deck.save", {"deck_id": DECK_ID, "text": current.text.replace("Current authored game plan.", "Later authored game plan."),
                         "base_sha256": current.sha256}), ACTOR, "Edit the synthetic prose later")
        before = self.persisted()
        after, summary = self.undo(source)
        self.assertIsNone(after.order(facts.OID))
        self.assertEqual(after.watchlist.rows[0].as_dict(), facts.queued())
        self.assertNotEqual(after.watchlist.rows[0].id, old_id)
        for text in ("Later authored game plan.", "#Ramp", "private-legacy-sleeves", "private-legacy-box", "Keep this handwritten note", "Keep the total note"):
            self.assertIn(text, after.deck(DECK_ID).text)
        self.assertIn("| Llanowar Elves | 4 | 1 | **3** |", after.deck(DECK_ID).text)
        self.assertEqual(self.sql("select row_to_json(t)::text from audit.row_change t where change_set_id=%s order by id", (source,)), original_audit)
        saved = self.persisted()
        self.assertEqual(saved["collection_card"], before["collection_card"])
        self.assertEqual(saved["token_card"], before["token_card"])
        self.assertEqual(len(saved["audit.change_set"]), len(before["audit.change_set"]) + 1)
        self.assertEqual(summary.extra["order_queue_receipt"]["queue_count"], 1)
        self.assertNotIn("order_queue", summary.extra)

    def test_cancellation_and_removal_put_back_the_whole_pending_record_and_queue_atomically(self):
        self.add(quantity=2)
        expected = self.fresh()
        inventory.apply(inventory.Op("order.cancel", {"order": facts.OID, "component": "cards", "reason": "Not supplied", "restore_queue": True}),
                        ACTOR, "Cancel synthetic cards", reason="Not supplied")
        cancelled = self.latest()
        after, _ = self.undo(cancelled)
        self.assertEqual(after.order(facts.OID), expected.order(facts.OID))
        self.assertEqual(after.watchlist, expected.watchlist)
        inventory.apply(inventory.Op("order.remove", {"order": facts.OID, "reason": "Mistaken record"}), ACTOR,
                        "Remove synthetic order", reason="Mistaken record")
        removed = self.latest()
        after, _ = self.undo(removed)
        self.assertEqual(after.order(facts.OID), expected.order(facts.OID))
        self.assertEqual(after.payloads, expected.payloads)
        self.assertEqual(after.watchlist, expected.watchlist)

    def test_tampered_actual_audit_rolls_back_order_queue_tables_revisions_and_new_audit(self):
        source, _ = self.add()
        plan, before = inventory.undo_review(source, "home"), self.persisted()
        real = undo_order_queue_verify.confirm
        original_max = max(row[0] for row in self.sql("select id from audit.row_change where change_set_id=%s", (source,)))
        for mutation in ("missing", "source-id", "duplicate-id", "boolean-id"):
            def tampered(*args):
                values = list(args)
                actual = [dict(row) for row in values[3]]
                if mutation == "missing":
                    actual = actual[:-1]
                elif mutation == "source-id":
                    actual[0]["id"] = original_max
                elif mutation == "duplicate-id":
                    actual[1]["id"] = actual[0]["id"]
                else:
                    actual[0]["id"] = True
                values[3] = actual
                return real(*values)
            with self.subTest(mutation=mutation), mock.patch.object(undo_order_queue_verify, "confirm", side_effect=tampered), self.assertRaises(undo.UndoConflict):
                self.undo(source, plan)
            self.assertEqual(self.persisted(), before)
        self.undo(source, plan)

    def test_later_order_touch_or_missing_complete_source_prevents_any_inverse_write(self):
        source, _ = self.add(quantity=2)
        plan = inventory.undo_review(source, "home")
        inventory.apply(inventory.Op("order.checks", {"order": facts.OID, "component": "cards", "add": "Check synthetic art"}),
                        ACTOR, "Later order touch")
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            self.undo(source, plan)
        self.assertEqual(self.persisted(), before)

    def test_private_member_and_private_home_kit_changes_keep_the_receipt_and_are_preserved_fresh(self):
        source, _ = self.add()
        shown = inventory.undo_review(source, "home")
        inventory.apply(inventory.Op("collection.add", {"space": "user2", "row": facts.card(2)}), ACTOR,
                        "Add a private synthetic member card")
        current = self.fresh().deck(DECK_ID)
        inventory.apply(inventory.Op("kit.set", {"holders": [{"id": DECK_ID, "expected": current.sha256}], "owners": None,
            "changes": [{"holder": DECK_ID, "field": "sleeves", "value": "new private legacy sleeves", "loose": True}]}), ACTOR,
            "Change only a private home kit header")
        refreshed = inventory.undo_review(source, "home")
        self.assertEqual(refreshed["expect"], shown["expect"])
        self.assertEqual(refreshed["queue"]["expect"], shown["queue"]["expect"])
        after, _ = self.undo(source, shown)
        self.assertIn("new private legacy sleeves", after.deck(DECK_ID).text)
        self.assertEqual(after.collection("user2").rows[0].text("quantity"), "2")

    def test_new_fulfilling_product_and_sorted_status_survivor_are_reversed_as_one_real_audit_source(self):
        columns = ("name", "set", "collector_number", "finish", "quantity")
        old_cells = {**{field: facts.card(1)[field] for field in columns}, "set": "fdn", "collector_number": "227"}
        existing = model.Product("z-existing", columns, (model.ProductItem.make(old_cells, columns),))
        old_order = model.Order.build("2026-11-01-existing", components=[model.Component.build("existing", "product", "z-existing.csv",
            status="received", received_on="2026-11-01")])
        initial = self.fresh().with_product(existing).with_order(old_order).with_status_rows([
            {"file": existing.file, "status": "owned", "intact": "yes", "sleeves": "old kit", "deck_box": "old box", "notes": "Existing fixture product"}])
        pg.write_model(initial, ACTOR, "Seed a preexisting synthetic intact product", contents={}, replace=True, dbname=self.dbname, decks=True, images={})
        cells = {field: facts.card(1)[field] for field in columns}
        inventory.apply(inventory.Op("order.add", {"record": {"id": facts.OID}, "product": {"stem": "a-new", "columns": columns, "rows": [cells]},
            "fulfils": [{"select": "#1", "quantity": 1}]}), ACTOR, "Record synthetic fulfilling product")
        source = self.latest()
        self.assertEqual({row[0] for row in self.sql("select op from audit.row_change where change_set_id=%s and table_name='product_status'", (source,))},
                         {"INSERT", "UPDATE"})
        shown = inventory.undo_review(source, "home")
        # A current kit-only update is independent of the status-position lineage.
        from decklab.lib.inventory import kit
        inventory.apply(inventory.Op("product.set-kit", {"sha256": kit.status_sha256(self.fresh()), "changes": [
            {"stem": "z-existing", "field": "sleeves", "value": "current kit"}], "hold": "z-existing"}), ACTOR,
            "Update the survivor's current legacy kit")
        self.assertEqual(inventory.undo_review(source, "home")["expect"], shown["expect"])
        after, _ = self.undo(source, shown)
        self.assertIsNone(after.order(facts.OID))
        self.assertIsNone(after.product("a-new"))
        self.assertEqual([row.text("file") for row in after.status.rows], ["z-existing.csv"])
        self.assertEqual(after.status.rows[0].text("sleeves"), "current kit")
