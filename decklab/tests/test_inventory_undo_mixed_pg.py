"""Whole-change Undo of a real import and a real receipt through the audit trail, in disposable DBs."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import access, config, inventory
from decklab.lib.api import activity_mixed_undo
from decklab.lib.inventory import Op, model, paths, pg, receive, rules, undo
from decklab.lib.inventory.table_rows import tables
from decklab.lib.state import pg as state_pg
from decklab.tests import db_support
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests import test_collection_edit as collection_fixture
from decklab.tests import test_inventory_undo_mixed as mixed

ACTOR = mixed.ACTOR
REASON = mixed.REASON
ORDER = mixed.ORDER
TABLES = ("collection_card", "collection_import", "token_card", "order_component", "product_status", "purchase_order",
          "order_card_item", "order_token_item", "product", "product_item")


class MixedUndoPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-mixed-undo-pg-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Mixed Undo requires a disposable database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def setUp(self):
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = fixture.ActivityUndoApiTests()
        self.addCleanup(case.doCleanups)
        case.setUp()
        base = case.backend.snapshot
        product = next(item for item in base.products if item.stem == "fdc-test-precon")
        cards, tokens = (paths.payload(kind, "pending", f"{ORDER}.csv") for kind in ("cards", "tokens"))
        order = model.Order.build(ORDER, "Shop", "2026-10-20", (), "", [
            model.Component.build("cards", "cards", f"{ORDER}.csv", checks=["Confirm the Elves are near mint"]),
            model.Component.build("tokens", "tokens", f"{ORDER}.csv"),
            model.Component.build("fdc-test-precon", "product", "fdc-test-precon.csv")])
        payloads = {cards: model.Sheet(cards, model.CardRow.COLUMNS, (model.CardRow.make(mixed.NEW), model.CardRow.make(mixed.BUMP)), True),
                    tokens: model.Sheet(tokens, model.TokenRow.COLUMNS, (model.TokenRow.make(mixed.TOKEN),), True)}
        status = model.Sheet(paths.STATUS, tuple(rules.STATUS_FIELDS),
                             (model.StatusRow.make({"file": "fdc-test-precon.csv", "status": "preordered", "notes": "due soon"}),), True)
        initial = model.Inventory("mixed-undo-pg-fixture", collections={}, products=(product,), status=status, orders=(order,),
                                  payloads=payloads, watchlist=model.Sheet(paths.WATCHLIST, tuple(model.QUEUE_FIELDS), (), True))
        initial = initial.with_collection("home", [fixture.CARD]).with_collection("user2", [fixture.CARD])
        pg.write_model(initial, ACTOR, "Seed disposable mixed Undo inventory", contents={}, dbname=self.dbname, decks=True, images={})
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def fresh(self):
        return pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker()).load()

    def sql(self, statement, args=()):
        with self.connect("ro") as connection:
            return connection.execute(statement, args).fetchall()

    def persisted(self):
        with self.connect("ro") as connection:
            return {table: sorted(json.dumps(row[0], sort_keys=True) for row in connection.execute(
                        f"select row_to_json(t)::jsonb - 'position' - 'id' - 'imported_at' from {table} t").fetchall())
                    for table in TABLES}

    def latest(self):
        return self.sql("select max(id) from audit.change_set")[0][0]

    def merge(self, space="home"):
        rows = [mixed.NEW, mixed.BUMP]
        inventory.apply(Op("collection.import", {"space": space, "sources": [["upload.csv", rows]],
                                                 "uploads": [["upload", rules.collection_csv_bytes(rows).decode("utf-8")]]}),
                        ACTOR, "Fixture import")
        return self.latest()

    def receive(self, components=None):
        components = components or [{"id": "cards", "verified": True}, {"id": "tokens", "verified": True},
                                    {"id": "fdc-test-precon", "intact": "yes"}]
        inventory.apply(receive.op(ORDER, components, "2026-10-25"), ACTOR, "Fixture receipt")
        return self.latest()

    def api(self, change_id, profile="matt"):
        with access.using({"profile": profile, "email": f"{profile}@example.com", "remote": True}):
            preview = activity_mixed_undo.mixed_undo_view(id=str(change_id))
            answer = activity_mixed_undo.apply_mixed_undo(json.dumps({"profile": profile, "id": change_id,
                                                                     "expect": preview["expect"], "reason": REASON}).encode())
        return preview, answer

    def test_real_import_undo_restores_rows_keeps_upload_and_audits_once(self):
        before = self.persisted()
        change = self.merge()
        original = self.sql("select id,table_name,op,before,after from audit.row_change where change_set_id=%s order by id", (change,))
        self.assertEqual({row[1] for row in original}, {"collection_card", "collection_import"})
        preview, answer = self.api(change)
        self.assertEqual((preview["action"], answer["removed_rows"], answer["restored_rows"]), ("import_undo", 1, 1))
        written = self.persisted()
        self.assertEqual(written["collection_card"], before["collection_card"])
        self.assertEqual(len(written["collection_import"]), 1)
        undo_set = self.latest()
        self.assertEqual(self.sql("select actor,reason,message from audit.change_set where id=%s", (undo_set,)),
                         [("matt", REASON, f"Undo activity change {change}")])
        self.assertEqual({(row[0], row[1]) for row in self.sql("select table_name,op from audit.row_change where change_set_id=%s",
                                                                (undo_set,))}, {("collection_card", "DELETE"), ("collection_card", "UPDATE")})
        self.assertEqual(self.sql("select id,table_name,op,before,after from audit.row_change where change_set_id=%s order by id",
                                  (change,)), original)
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_mixed_review(change, "home")

    def test_real_receipt_undo_puts_the_order_back_and_can_be_received_again(self):
        before = self.persisted()
        change = self.receive()
        touched = {row[0] for row in self.sql("select distinct table_name from audit.row_change where change_set_id=%s", (change,))}
        self.assertTrue({"order_component", "product_status", "collection_card", "token_card"} <= touched)
        preview, answer = self.api(change)
        self.assertEqual((answer["action"], answer["components"], answer["products"]), ("receipt_undo", 3, 1))
        self.assertEqual(self.persisted(), before)
        saved = self.fresh()
        self.assertEqual([(c.status, c.received_on, c.checks, c.verified_checks) for c in saved.order(ORDER).components],
                         [("pending", "", ["Confirm the Elves are near mint"], None), ("pending", "", [], None), ("pending", "", [], None)])
        self.assertEqual(tables(saved)["order_card_item"], tables(self.fresh())["order_card_item"])
        again = self.receive()
        self.assertTrue(all(c.status == "received" for c in self.fresh().order(ORDER).components))
        self.api(again)
        self.assertEqual(self.persisted(), before)

    def test_a_later_receipt_of_the_tokens_does_not_block_undoing_the_cards(self):
        cards = self.receive([{"id": "cards", "verified": True}])
        self.receive([{"id": "tokens", "verified": True}])
        self.api(cards)
        statuses = {c.id: c.status for c in self.fresh().order(ORDER).components}
        self.assertEqual(statuses, {"cards": "pending", "tokens": "received", "fdc-test-precon": "pending"})

    def test_a_later_edit_refuses_with_its_row_and_writes_nothing(self):
        change = self.merge()
        sheet = self.fresh().collection("home")
        inventory.apply(Op("collection.edit", {"space": "home", "original": ["m19", "314", "nonfoil"],
                                               "row": {**mixed.NEW, "notes": "Sorted"},
                                               "sha256": mixed.ops_collection.sha256_of(sheet)}), ACTOR, "Later edit")
        before, sets = self.persisted(), self.latest()
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            with self.assertRaises(activity_mixed_undo.ApiError) as caught:
                activity_mixed_undo.mixed_undo_view(id=str(change))
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("M19 314", caught.exception.message)
        self.assertEqual((self.persisted(), self.latest()), (before, sets))

    def test_a_member_undoes_only_their_own_import(self):
        change = self.merge("user2")
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            with self.assertRaises(activity_mixed_undo.ApiError) as caught:
                activity_mixed_undo.mixed_undo_view(id=str(change))
        self.assertEqual(caught.exception.status, 404)
        self.api(change, "user2")
        self.assertEqual([row.as_dict()["quantity"] for row in self.fresh().collection("user2").rows], ["2"])

    def test_the_store_reads_every_row_and_latest_ids_in_one_query(self):
        change = self.merge()
        rows = self.backend.undo_audit_rows(change)
        self.assertEqual(len(rows), 3)
        found = self.backend.undo_latest_rows([(row["table"], row["key"]) for row in rows])
        self.assertEqual(found, {(row["table"], json.dumps(row["key"], sort_keys=True)): row["id"] for row in rows})
        with self.assertRaises(inventory.Invalid):
            self.backend.undo_latest_rows([("wishlist_entry", {"id": 1})])
