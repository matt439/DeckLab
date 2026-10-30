"""Restoring edited token cards in place writes only to a guarded disposable PostgreSQL database.

These run the real PgInventory.apply, so the restore's pre-commit proof (undo_token_edit's
confirm_in_transaction) reads this change set's own audit rows and token layout. No card cache
is read: only details, quantities and notes change, so no face name is checked."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import config, inventory, tokens
from decklab.lib.inventory import Op, Summary, files, undo, undo_token_edit as edit
from decklab.tests import db_support, test_inventory_undo_pg as existing
from decklab.tests import test_collection_edit as collection_fixture
from decklab.tests import test_inventory_undo_token_insert_pg as insert_pg


class TokenEditUndoPgTests(db_support.DbTestCase):
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
        temporary = tempfile.TemporaryDirectory(prefix="decklab-undo-token-edit-pg-", dir=root)
        cls.addClassCleanup(temporary.cleanup)
        path = Path(temporary.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Token-card edit Undo requires a disposable database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def seed(self):
        """Angel // The Monarch, Beast and Treasure added on their own; Beast and Treasure then edited in one change."""
        for row in (self.row(), self.row("Beast", "", "4"), self.row("Treasure", "", "3")):
            self.add(row)
        edits = {"Beast": {"quantity": "6", "front_details": "3/3; green"}, "Treasure": {"notes": "Edited single-sided verified"}}

        class EditMany:
            kind = "fixture.token-edits"

            def run(self, snapshot):
                for front, change in edits.items():
                    sheet = snapshot.token_set("home")
                    base = next(row.as_dict() for row in sheet.rows if row.front == front)
                    snapshot, _ = tokens.ops.edit(snapshot, space="home", base=base, row={**base, **change},
                                                  sha256=files.rendered_sha256(sheet), separate=True)
                return snapshot, Summary("Fixture edit of two token cards")
        inventory.apply(EditMany(), existing.ACTOR, "Fixture token edits")
        source = self.source("token_card")
        self.assertEqual(self.sql("select table_name,op from audit.row_change where change_set_id=%s", (source,)),
                         [("token_card", "UPDATE")] * 2)
        return source

    def apply(self, source, plan=None):
        plan = inventory.undo_review(source, "home") if plan is None else plan
        return inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"]}),
                               existing.ACTOR, "Undo fixture token edits")

    def test_restore_is_exactly_two_updates_with_positions_packing_and_history_kept(self):
        source = self.seed()
        self.packed("1 Angel // The Monarch")
        plan = inventory.undo_review(source, "home")
        self.assertEqual((plan["action"], plan["row_count"], plan["label"]), (edit.ACTION, 2, "Updates to 2 token-card rows"))
        ids = [item["token_row_id"] for item in plan["rows"]]
        layout = self.sql("select id,position from token_card order by position,id")
        original = self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,))
        before = self.persisted()
        with mock.patch.object(edit, "confirm_in_transaction", wraps=edit.confirm_in_transaction) as hook:
            after, summary = self.apply(source, plan)
        hook.assert_called_once()
        self.assertEqual(summary.extra["restored_token_row_ids"], ids)
        made = self.sql("select table_name,op,row_key,before,after from audit.row_change "
                        "where change_set_id=(select max(id) from audit.change_set)")
        self.assertEqual(sorted((row[0], row[1], row[2]["id"]) for row in made), [("token_card", "UPDATE", rid) for rid in sorted(ids)])
        recorded = {row[2]["id"]: row[3] for row in original}
        self.assertEqual({row[2]["id"]: row[4] for row in made}, recorded)
        self.assertEqual(self.sql("select id,position from token_card order by position,id"), layout)
        self.assertEqual(self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,)), original)
        saved = self.persisted()
        self.assertEqual(len(saved["audit.row_change"]), len(before["audit.row_change"]) + 2)
        for table in ("collection_card", "deck", "deck_text", "deck_line", "deck_revision", "decks_revision"):
            self.assertEqual(saved[table], before[table], table)
        beast = next(row for row in after.token_set("home").rows if row.front == "Beast")
        self.assertEqual((beast.quantity, beast.front_details), ("4", ""))
        with self.assertRaises(inventory.Invalid):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), saved)

    def test_one_tokens_edit_beyond_quantity_and_notes_is_restored_in_place(self):
        self.add(self.row("Beast", "", "4"))
        sheet = self.fresh().token_set("home")
        base = sheet.rows[0].as_dict()
        inventory.apply(Op("tokens.edit", {"space": "home", "sha256": files.rendered_sha256(sheet), "base": base,
                                           "row": {**base, "front_details": "3/3; green"}, "separate": True}),
                        existing.ACTOR, "Fixture token details edit")
        source = self.source("token_card")
        plan = inventory.undo_review(source, "home")
        self.assertEqual((plan["action"], plan["label"]), (edit.ACTION, "Updates to 1 token-card row"))
        after, summary = self.apply(source, plan)
        self.assertEqual(after.token_set("home").rows[0].front_details, "")
        self.assertEqual(summary.counts["edited"], 1)

    def test_a_tampered_proof_rolls_every_update_back(self):
        source = self.seed()
        plan = inventory.undo_review(source, "home")
        before = self.persisted()
        real = edit.confirm
        def tampered(before_inv, saved, summary, actual, layout):
            return real(before_inv, saved, summary, actual[:-1], layout)  # As if one row weren't restored.
        with mock.patch.object(edit, "confirm", side_effect=tampered), self.assertRaises(undo.UndoConflict) as caught:
            self.apply(source, plan)
        self.assertEqual(str(caught.exception), edit.UNCONFIRMED)
        self.assertEqual(self.persisted(), before)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))

    def test_a_packed_line_that_would_lose_cards_refuses_the_whole_change_without_write(self):
        source = self.seed()
        plan = inventory.undo_review(source, "home")
        self.packed("5 Beast")
        before = self.persisted()
        with self.assertRaises(edit.Refused):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), before)
