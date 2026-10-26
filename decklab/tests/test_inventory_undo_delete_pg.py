"""Audited deleted-row restores and rollback in one guarded disposable PostgreSQL database."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import access, config, inventory
from decklab.lib.api import activity_undo
from decklab.lib.inventory import Op, files, pg, rules, undo
from decklab.lib.state import Invalid
from decklab.tests import db_support, test_inventory_undo_pg as existing
from decklab.tests import test_collection_edit as collection_fixture


class DeleteUndoPgTests(db_support.DbTestCase):
    setUp = existing.UndoPgTests.setUp
    fresh = existing.UndoPgTests.fresh
    sql = existing.UndoPgTests.sql
    persisted = existing.UndoPgTests.persisted
    source = existing.UndoPgTests.source

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        folder = tempfile.TemporaryDirectory(prefix="decklab-undo-delete-pg-", dir=root)
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("DELETE Undo requires a disposable database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def delete(self, empty=False):
        rows = self.fresh().collection("home").rows
        row = next(row.as_dict() for row in rows if row.name == "Llanowar Elves")
        if empty:
            for other in rows:
                if rules.ident(other.as_dict()) != rules.ident(row):
                    inventory.apply(Op("collection.remove", {"space": "home", "original": list(rules.ident(other.as_dict()))}),
                                    existing.ACTOR, "Empty disposable collection")
        inventory.apply(Op("collection.remove", {"space": "home", "original": list(rules.ident(row))}),
                        existing.ACTOR, "Fixture deleted row", reason="Synthetic source removal")
        source = self.source("collection_card")
        self.assertEqual(self.sql("select op from audit.row_change where change_set_id=%s", (source,)), [("DELETE",)])
        return source, row

    def apply(self, source, plan=None):
        plan = inventory.undo_review(source, "home") if plan is None else plan
        return inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"],
                                                      "confirm_owned": True}), existing.ACTOR, "Restore fixture deleted row")

    def test_restore_is_one_exact_new_insert_without_altering_original_audit_or_other_records(self):
        source, row = self.delete()
        original = self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,))
        before = self.persisted()
        plan = inventory.undo_review(source, "home")
        after, summary = self.apply(source, plan)
        written = self.persisted()
        actual = undo.restored_row(after, plan)
        self.assertEqual(actual, {**row, "quantity": int(row["quantity"])})
        self.assertEqual(summary.counts["added_rows"], 1)
        self.assertFalse(summary.counts["merged"])
        self.assertEqual(self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,)), original)
        self.assertEqual(self.sql("select op,before from audit.row_change order by id desc limit 1"), [("INSERT", None)])
        self.assertEqual(len(written["audit.change_set"]), len(before["audit.change_set"]) + 1)
        for table in ("token_card", "deck", "deck_text", "deck_line", "deck_revision", "decks_revision"):
            self.assertEqual(written[table], before[table], table)

    def test_actual_api_confirms_empty_collection_restore_exact_metadata_and_web_actor(self):
        source, row = self.delete(empty=True)
        self.assertEqual(self.fresh().collection("home").rows, ())
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            preview = activity_undo.undo_view(id=str(source))
            result = activity_undo.apply_undo(json.dumps({"profile": "matt", "id": source, "expect": preview["expect"],
                                                        "confirm_owned": True}).encode())
        self.assertEqual(result["action"], "add")
        self.assertEqual(result["added_key"], {key: row[key] for key in ("set", "collector_number", "finish")})
        self.assertEqual(result["restored"], {**row, "quantity": int(row["quantity"])})
        after = self.fresh()
        self.assertEqual(result["sha256"], files.rendered_sha256(after.collection("home")))
        self.assertEqual(result["revision"], after.revision)
        self.assertEqual(self.sql("select actor,source,via,reason from audit.change_set order by id desc limit 1"),
                         [("matt", "web", "tunnel", None)])

    def test_missing_confirmation_does_not_create_rows_or_audit(self):
        source, _ = self.delete()
        plan = inventory.undo_review(source, "home")
        before = self.persisted()
        with self.assertRaises(Invalid):
            inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"]}),
                            existing.ACTOR, "Unconfirmed fixture restoration")
        self.assertEqual(self.persisted(), before)

    def test_current_key_and_add_remove_aba_never_reauthorize_original_delete(self):
        source, row = self.delete()
        inventory.apply(Op("collection.add", {"space": "home", "row": row}), existing.ACTOR, "Fixture recreation")
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(source, "home")
        inventory.apply(Op("collection.remove", {"space": "home", "original": list(rules.ident(row))}), existing.ACTOR, "Fixture later removal")
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)

    def test_both_revision_receipts_refuse_with_the_key_still_absent(self):
        source, _ = self.delete()
        for table in ("inventory_revision", "decks_revision"):
            with self.subTest(table=table):
                plan = inventory.undo_review(source, "home")
                with self.connect("owner") as c:
                    c.execute("update " + table + " set revision=revision+1")
                before = self.persisted()
                with self.assertRaises(undo.UndoConflict):
                    self.apply(source, plan)
                self.assertEqual(self.persisted(), before)

    def test_same_connection_repeated_restore_and_sql_failure_are_safe(self):
        source, _ = self.delete()
        plan = inventory.undo_review(source, "home")
        before = self.persisted()
        original_diff, original_call = pg._diff, self.backend._call
        def late(*args):
            original_diff(*args)
            raise Invalid("Synthetic late SQL failure")
        with mock.patch.object(pg, "_diff", side_effect=late), self.assertRaises(Invalid):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), before)
        def no_nested(work):
            self.assertIsNone(getattr(self.backend._applying, "connection", None), "Undo opened a second applying connection")
            return original_call(work)
        with mock.patch.object(self.backend, "_call", side_effect=no_nested):
            self.apply(source, plan)
        after = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), after)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))
