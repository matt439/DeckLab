"""Removing added token cards together writes only to a guarded disposable PostgreSQL database.

These run the real PgInventory.apply, so the batch removal's pre-commit proof
(undo_token_batch_remove's confirm_in_transaction, through undo_token_delete's hook) reads this
change set's own audit rows and token layout. No card cache is read."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import config, inventory, tokens
from decklab.lib.inventory import Op, Summary, files, undo, undo_token_batch_remove as batch
from decklab.tests import db_support, test_inventory_undo_pg as existing
from decklab.tests import test_collection_edit as collection_fixture
from decklab.tests import test_inventory_undo_token_insert_pg as insert_pg

REASON = "Correct an accidental token-card batch."


class TokenBatchRemoveUndoPgTests(db_support.DbTestCase):
    setUp = existing.UndoPgTests.setUp
    fresh = existing.UndoPgTests.fresh
    sql = existing.UndoPgTests.sql
    persisted = existing.UndoPgTests.persisted
    source = existing.UndoPgTests.source
    row = staticmethod(insert_pg.TokenInsertUndoPgTests.row)
    add = insert_pg.TokenInsertUndoPgTests.add
    packed = insert_pg.TokenInsertUndoPgTests.packed

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        temporary = tempfile.TemporaryDirectory(prefix="decklab-undo-token-batch-remove-pg-", dir=root)
        cls.addClassCleanup(temporary.cleanup)
        path = Path(temporary.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Added-token batch removal requires a disposable database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def seed(self):
        """Beast added on its own; Angel // The Monarch, Treasure and Zombie added in one change: that change."""
        self.add(self.row("Beast", "", "4"))
        added = [self.row(), self.row("Treasure", "", "1"), self.row("Zombie", "", "3")]

        class AddMany:
            kind = "fixture.token-additions"

            def run(self, snapshot):
                for row in added:
                    sheet = snapshot.token_set("home")
                    snapshot, _ = tokens.ops.add(snapshot, space="home", row=row,
                                                 sha256=files.rendered_sha256(sheet) if sheet.exists else None)
                return snapshot, Summary("Fixture addition of three token cards")
        inventory.apply(AddMany(), existing.ACTOR, "Fixture token additions")
        source = self.source("token_card")
        self.assertEqual(self.sql("select table_name,op from audit.row_change where change_set_id=%s", (source,)),
                         [("token_card", "INSERT")] * 3)
        return source

    def apply(self, source, plan=None):
        plan = inventory.undo_review(source, "home") if plan is None else plan
        return inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"],
                                                     "reason": REASON}), existing.ACTOR, "Undo fixture token additions",
                               reason=REASON)

    def test_removal_is_exactly_three_deletes_with_the_survivor_packing_and_history_kept(self):
        source = self.seed()
        self.packed("1 Beast")
        plan = inventory.undo_review(source, "home")
        self.assertEqual((plan["action"], plan["row_count"], plan["cards"]), (batch.ACTION, 3, 6))
        ids = [item["token_row_id"] for item in plan["rows"]]
        layout = self.sql("select id,position from token_card order by position,id")
        original = self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,))
        before = self.persisted()
        with mock.patch.object(batch, "confirm_in_transaction", wraps=batch.confirm_in_transaction) as hook:
            after, summary = self.apply(source, plan)
        hook.assert_called_once()
        self.assertEqual(summary.extra["removed_token_row_ids"], ids)
        self.assertEqual((summary.counts["cards"], summary.counts["removed_cards"]), (4, 6))
        made = self.sql("select table_name,op,row_key from audit.row_change where change_set_id=(select max(id) from audit.change_set)")
        self.assertEqual(sorted(made, key=lambda row: row[2]["id"]), [("token_card", "DELETE", {"id": rid}) for rid in sorted(ids)])
        self.assertEqual(self.sql("select reason from audit.change_set where id=(select max(id) from audit.change_set)"), [(REASON,)])
        self.assertEqual(self.sql("select id,position from token_card order by position,id"), [row for row in layout if row[0] not in ids])
        self.assertEqual(self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,)), original)
        saved = self.persisted()
        self.assertEqual(len(saved["audit.row_change"]), len(before["audit.row_change"]) + 3)
        for table in ("collection_card", "deck", "deck_text", "deck_line", "deck_revision", "decks_revision"):
            self.assertEqual(saved[table], before[table], table)
        with self.assertRaises(inventory.Invalid):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), saved)
        self.assertEqual([row.front for row in after.token_set("home").rows], ["Beast"])

    def test_a_tampered_proof_rolls_every_delete_back(self):
        source = self.seed()
        plan = inventory.undo_review(source, "home")
        before = self.persisted()
        real = batch.confirm
        def tampered(before_inv, saved, summary, actual, layout):
            return real(before_inv, saved, summary, actual[:-1], layout)  # As if one row were kept.
        with mock.patch.object(batch, "confirm", side_effect=tampered), self.assertRaises(undo.UndoConflict) as caught:
            self.apply(source, plan)
        self.assertEqual(str(caught.exception), batch.UNCONFIRMED)
        self.assertEqual(self.persisted(), before)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))

    def test_a_packed_line_holding_one_of_them_refuses_the_whole_batch_without_write(self):
        source = self.seed()
        plan = inventory.undo_review(source, "home")
        self.packed("1 Treasure")
        before = self.persisted()
        with self.assertRaises(batch.Refused):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), before)
