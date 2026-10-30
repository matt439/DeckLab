"""Restoring deleted token cards together writes only to a guarded disposable PostgreSQL database.

These run the real PgInventory.apply, so the batch's pre-commit proof (undo_token_batch's
confirm_in_transaction, through undo_token_delete's hook) reads this change set's own audit rows
and token layout. Card-data lookups are stubbed: no card cache is read."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import cards, config, inventory
from decklab.lib.inventory import Op, Summary, undo, undo_token_batch as batch
from decklab.lib.tokens import names
from decklab.tests import db_support, test_inventory_undo_pg as existing
from decklab.tests import test_collection_edit as collection_fixture
from decklab.tests import test_inventory_undo_token_insert_pg as insert_pg


class TokenBatchRestoreUndoPgTests(db_support.DbTestCase):
    fresh = existing.UndoPgTests.fresh
    sql = existing.UndoPgTests.sql
    persisted = existing.UndoPgTests.persisted
    source = existing.UndoPgTests.source
    add = insert_pg.TokenInsertUndoPgTests.add
    packed = insert_pg.TokenInsertUndoPgTests.packed

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        temporary = tempfile.TemporaryDirectory(prefix="decklab-undo-token-batch-pg-", dir=root)
        cls.addClassCleanup(temporary.cleanup)
        path = Path(temporary.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Deleted-token batch restoration requires a disposable database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def setUp(self):
        existing.UndoPgTests.setUp(self)
        self.enterContext(mock.patch.object(names, "check_names", side_effect=lambda row: (dict(row), [])))
        self.enterContext(mock.patch.object(cards, "printing", return_value={"digital": False, "games": ["paper"],
                                                                           "finishes": ["nonfoil"]}))

    @staticmethod
    def row(front, back, number, quantity="1"):
        return {**insert_pg.TokenInsertUndoPgTests.row(front, back, quantity), "set": "tst", "finish": "nonfoil",
                "front_collector_number": number, "back_collector_number": str(int(number) + 1) if back else ""}

    def seed(self):
        """Beast kept; Angel // The Monarch, Treasure and Zombie deleted in one change: that change."""
        for row in (self.row("Beast", "", "1", "4"), self.row("Angel", "The Monarch", "3", "2"),
                    self.row("Treasure", "", "5"), self.row("Zombie", "", "7", "3")):
            self.add(row)
        before = self.fresh()
        kept = [row for row in before.token_set("home").rows if row.front == "Beast"]

        class RemoveMany:
            kind = "fixture.token-removal"

            def run(self, snapshot):
                return snapshot.with_tokens("home", kept), Summary("Fixture removal of three token cards")
        inventory.apply(RemoveMany(), existing.ACTOR, "Fixture token deletions", reason="Fixture deletion")
        source = self.source("token_card")
        self.assertEqual(self.sql("select table_name,op from audit.row_change where change_set_id=%s", (source,)),
                         [("token_card", "DELETE")] * 3)
        return source

    def apply(self, source, plan=None):
        plan = inventory.undo_review(source, "home") if plan is None else plan
        return inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"],
                                                     "confirm_owned": True}), existing.ACTOR, "Undo fixture token deletions")

    def test_restore_is_three_fresh_inserts_with_the_survivor_packing_and_history_kept(self):
        source = self.seed()
        self.packed("1 Beast")
        plan = inventory.undo_review(source, "home")
        self.assertEqual((plan["action"], plan["row_count"], plan["cards"]), (batch.ACTION, 3, 6))
        deleted_ids = plan["proof"]["deleted_ids"]
        layout = self.sql("select id,position from token_card order by position,id")
        original = self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,))
        before = self.persisted()
        with mock.patch.object(batch, "confirm_in_transaction", wraps=batch.confirm_in_transaction) as hook:
            after, summary = self.apply(source, plan)
        hook.assert_called_once()
        ids = summary.extra["added_token_row_ids"]
        self.assertEqual(len(set(ids)), 3)
        self.assertTrue(set(ids).isdisjoint(set(deleted_ids) | {rid for rid, _ in layout}))
        self.assertEqual((summary.counts["cards"], summary.counts["restored_cards"]), (10, 6))
        self.assertIn("restore 3 deleted token-card rows (6 physical cards) as new rows", summary.text)
        made = self.sql("select table_name,op from audit.row_change where change_set_id=(select max(id) from audit.change_set)")
        self.assertEqual(made, [("token_card", "INSERT")] * 3)
        self.assertEqual([row for row in self.sql("select id,position from token_card order by position,id") if row[0] not in ids], layout)
        self.assertEqual(self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,)), original)
        saved = self.persisted()
        self.assertEqual(len(saved["audit.row_change"]), len(before["audit.row_change"]) + 3)
        for table in ("collection_card", "deck", "deck_text", "deck_line", "deck_revision", "decks_revision"):
            self.assertEqual(saved[table], before[table], table)
        with self.assertRaises(undo.UndoConflict):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), saved)
        self.assertEqual(len(after.token_set("home").rows), 4)

    def test_a_tampered_proof_rolls_every_insert_back(self):
        source = self.seed()
        plan = inventory.undo_review(source, "home")
        before = self.persisted()
        real = batch.confirm
        def tampered(before_inv, saved, summary, actual, layout):
            return real(before_inv, saved, summary, actual[:-1], layout)  # As if one row were missing.
        with mock.patch.object(batch, "confirm", side_effect=tampered), self.assertRaises(undo.UndoConflict) as caught:
            self.apply(source, plan)
        self.assertEqual(str(caught.exception), batch.UNCONFIRMED)
        self.assertEqual(self.persisted(), before)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))

    def test_a_packed_line_claiming_one_of_them_refuses_the_whole_batch_without_write(self):
        source = self.seed()
        plan = inventory.undo_review(source, "home")
        self.packed("1 Treasure")
        before = self.persisted()
        with self.assertRaises(batch.Refused):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), before)
