"""Stable token INSERT Undo writes only to a guarded disposable PostgreSQL database."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.db import conn as db
from decklab.lib import access, config, inventory
from decklab.lib.api import activity_undo
from decklab.lib.inventory import Op, Summary, files, model, pg, rules, undo
from decklab.lib.state import Invalid
from decklab.tests import db_support, test_inventory_undo_pg as existing
from decklab.tests import test_collection_edit as collection_fixture


class TokenInsertUndoPgTests(db_support.DbTestCase):
    setUp = existing.UndoPgTests.setUp
    fresh = existing.UndoPgTests.fresh
    sql = existing.UndoPgTests.sql
    persisted = existing.UndoPgTests.persisted
    source = existing.UndoPgTests.source

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        temporary = tempfile.TemporaryDirectory(prefix="decklab-undo-token-insert-pg-", dir=root)
        cls.addClassCleanup(temporary.cleanup)
        path = Path(temporary.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Token INSERT Undo requires a disposable database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    @staticmethod
    def row(front="Angel", back="The Monarch", quantity="2", **fields):
        return {**dict.fromkeys(rules.TOKEN_FIELDS, ""), "front": front, "back": back, "quantity": quantity,
                "notes": "Explicit paired physical cards" if back else "single-sided verified", **fields}

    def add(self, row):
        sheet = self.fresh().token_set("home")
        inventory.apply(Op("tokens.add", {"space": "home", "sha256": files.rendered_sha256(sheet) if sheet.exists else None,
                                          "row": row, "separate": True}), existing.ACTOR, "Fixture token insertion")
        return self.source("token_card")

    def seed(self, last=False):
        if not last:
            self.add(self.row("Beast", "", "4"))
            self.add(self.row("Zombie", "", "5"))
        row = self.row()
        source = self.add(row)
        self.assertEqual(self.sql("select table_name,op from audit.row_change where change_set_id=%s", (source,)), [("token_card", "INSERT")])
        return source, row

    def packed(self, line):
        text = "# Packed fixture\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** built\n" + ("- **Token cards:** " + line if line is not None else "") \
            + "\n\n## Decklist\n\n```\nDeck\n4 Llanowar Elves\n56 Forest\n```\n"
        class PutDeck:
            kind = "fixture.token-packing"
            def run(self, snapshot):
                return snapshot.with_deck(model.Deck("home", "casual", "packed", text)), Summary("Fixture explicit token packing")
        inventory.apply(PutDeck(), existing.ACTOR, "Fixture explicit token packing")

    def apply(self, source, plan=None):
        plan = inventory.undo_review(source, "home") if plan is None else plan
        reason = "Correct accidental physical token insertion."
        return inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"], "reason": reason}),
                               existing.ACTOR, "Undo fixture token insertion", reason=reason)

    def test_actual_delete_is_one_audit_row_with_stable_survivor_values_positions_and_holds(self):
        source, _ = self.seed()
        self.packed("2 Beast")
        plan = inventory.undo_review(source, "home")
        rid = plan["token_row_id"]
        before = self.persisted()
        layout = self.sql("select id,position from token_card order by position,id")
        original = self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,))
        after, summary = self.apply(source, plan)
        saved = self.persisted()
        self.assertIsNone(undo.restored_row(after, plan))
        self.assertEqual(summary.counts["cards"], 9)  # Two physical paired cards removed, not four faces.
        self.assertEqual(summary.extra["removed_token_row_id"], rid)
        self.assertEqual(self.sql("select id,position from token_card order by position,id"), [row for row in layout if row[0] != rid])
        self.assertEqual(self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,)), original)
        changes = self.sql("select table_name,op,row_key,after from audit.row_change where change_set_id=(select max(id) from audit.change_set)")
        self.assertEqual(changes, [("token_card", "DELETE", {"id": rid}, None)])
        self.assertEqual(len(saved["audit.row_change"]), len(before["audit.row_change"]) + 1)
        for table in ("collection_card", "collection_import", "collection_import_content", "deck", "deck_text", "deck_line", "deck_revision", "decks_revision"):
            self.assertEqual(saved[table], before[table], table)

    def test_web_reason_and_last_row_actual_empty_receipt_use_stable_token_id(self):
        source, _ = self.seed(last=True)
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            preview = activity_undo.undo_view(id=str(source))
            answer = activity_undo.apply_undo(json.dumps({"profile": "matt", "id": source, "expect": preview["expect"],
                                                         "reason": "  Correct\n accidental token insertion. "}).encode())
        self.assertEqual((answer["kind"], answer["action"], answer["removed_token_row_id"]), ("tokens", "remove", preview["token_row_id"]))
        self.assertNotIn("removed_key", answer)
        self.assertIsNone(answer["restored"])
        saved = self.fresh()
        self.assertFalse(saved.token_set("home").exists)
        self.assertEqual(saved.token_set("home").rows, ())
        self.assertEqual((answer["sha256"], answer["revision"]), (files.rendered_sha256(saved.token_set("home")), saved.revision))
        self.assertEqual(self.sql("select actor,source,via,reason from audit.change_set order by id desc limit 1"),
                         [("matt", "web", "tunnel", "Correct accidental token insertion.")])

    def test_late_sql_failure_rolls_back_and_layout_reader_reuses_applying_connection(self):
        source, _ = self.seed()
        plan = inventory.undo_review(source, "home")
        before = self.persisted()
        original_diff, original_call = pg._diff, self.backend._call
        def late(*args):
            original_diff(*args)
            raise Invalid("Synthetic late token removal failure")
        with mock.patch.object(pg, "_diff", side_effect=late), self.assertRaises(Invalid):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), before)
        def no_nested(work):
            self.assertIsNone(getattr(self.backend._applying, "connection", None), "Token proof opened another applying connection")
            return original_call(work)
        with mock.patch.object(self.backend, "_call", side_effect=no_nested):
            self.apply(source, plan)
        saved = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), saved)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))

    def test_both_revisions_and_later_touch_aba_never_reauthorize_original_insertion(self):
        source, row = self.seed()
        for table in ("inventory_revision", "decks_revision"):
            plan = inventory.undo_review(source, "home")
            with self.connect("owner") as c:
                c.execute("update " + table + " set revision=revision+1")
            before = self.persisted()
            with self.assertRaises(undo.UndoConflict):
                self.apply(source, plan)
            self.assertEqual(self.persisted(), before)
        for note in ("Changed fixture note", row["notes"]):
            sheet = self.fresh().token_set("home")
            inventory.apply(Op("tokens.edit", {"space": "home", "sha256": files.rendered_sha256(sheet), "base": row,
                                               "row": {**row, "notes": note}, "separate": True}), existing.ACTOR, "Fixture token edit")
            row = {**row, "notes": note}
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)

    def test_held_target_and_unknown_deck_record_refuse_without_write(self):
        source, _ = self.seed()
        self.packed("1 Angel // The Monarch")
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)
        self.packed(None)
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)

    def test_duplicate_stored_positions_refuse_instead_of_rewriting_other_rows(self):
        source, _ = self.seed()
        target = inventory.undo_review(source, "home")["token_row_id"]
        with self.connect("owner") as c:
            with db.change("claude", "cli", "Fixture malformed stored positions", conn=c) as (cur, _):
                cur.execute("update token_card set position=(select position from token_card where id=%s) where id<>%s", (target, target))
                cur.execute("update inventory_revision set revision=revision+1")
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)
