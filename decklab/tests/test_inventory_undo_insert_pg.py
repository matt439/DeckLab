"""Real INSERT inverse/audit/rollback checks in a guarded disposable PostgreSQL database."""
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


class InsertUndoPgTests(db_support.DbTestCase):
    setUp = existing.UndoPgTests.setUp
    fresh = existing.UndoPgTests.fresh
    sql = existing.UndoPgTests.sql
    persisted = existing.UndoPgTests.persisted
    source = existing.UndoPgTests.source

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        temporary = tempfile.TemporaryDirectory(prefix="decklab-undo-insert-pg-", dir=root)
        cls.addClassCleanup(temporary.cleanup)
        path = Path(temporary.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("INSERT Undo requires a disposable database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def add(self, last=False):
        if last:
            for row in self.fresh().collection("home").rows:
                inventory.apply(Op("collection.remove", {"space": "home", "original": list(rules.ident(row.as_dict()))}),
                                existing.ACTOR, "Empty fixture collection")
        row = {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "foil", "quantity": "2",
               "condition": "", "language": "", "notes": "Temporary inserted printing"}
        inventory.apply(Op("collection.add", {"space": "home", "row": row}), existing.ACTOR, "Fixture printing insertion")
        change_id = self.source("collection_card")
        self.assertEqual(self.sql("select op from audit.row_change where change_set_id=%s", (change_id,)), [("INSERT",)])
        return change_id, row

    def apply(self, change_id, plan=None, reason="Correct accidental insertion."):
        plan = inventory.undo_review(change_id, "home") if plan is None else plan
        return inventory.apply(Op("inventory.undo", {"change_id": change_id, "space": "home", "expect": plan["expect"],
                                                      "reason": reason}), existing.ACTOR, "Undo fixture insertion", reason=reason)

    def test_new_delete_audit_preserves_original_insertion_and_unrelated_data(self):
        change_id, _ = self.add()
        original = self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (change_id,))
        before = self.persisted()
        plan = inventory.undo_review(change_id, "home")
        after, summary = self.apply(change_id, plan)
        written = self.persisted()
        self.assertEqual(summary.extra["action"], "remove")
        self.assertIsNone(undo.restored_row(after, plan))
        self.assertEqual(self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (change_id,)), original)
        self.assertEqual(self.sql("select op,after from audit.row_change order by id desc limit 1"), [("DELETE", None)])
        self.assertEqual(len(written["audit.change_set"]), len(before["audit.change_set"]) + 1)
        for table in ("token_card", "deck", "deck_text", "deck_line", "deck_revision", "decks_revision"):
            self.assertEqual(written[table], before[table], table)

    def test_actual_api_reason_and_last_row_absence_receipt_are_confirmed(self):
        change_id, row = self.add(last=True)
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            preview = activity_undo.undo_view(id=str(change_id))
            result = activity_undo.apply_undo(json.dumps({"profile": "matt", "id": change_id, "expect": preview["expect"],
                                                        "reason": "  Correct\n accidental insertion.  "}).encode())
        self.assertEqual(result["action"], "remove")
        self.assertIsNone(result["restored"])
        self.assertEqual(result["removed_key"], {key: row[key] for key in ("set", "collector_number", "finish")})
        saved = self.fresh()
        self.assertEqual(saved.collection("home").rows, ())
        self.assertEqual(result["sha256"], files.rendered_sha256(saved.collection("home")))
        self.assertEqual(result["revision"], saved.revision)
        self.assertEqual(self.sql("select actor,source,via,reason from audit.change_set order by id desc limit 1"),
                         [("matt", "web", "tunnel", "Correct accidental insertion.")])

    def test_aba_and_delete_recreate_never_reauthorize_original_insert(self):
        change_id, row = self.add()
        for note in ("Other", row["notes"]):
            inventory.apply(Op("collection.edit", {"space": "home", "original": list(rules.ident(row)),
                                                     "row": {**row, "notes": note}}), existing.ACTOR, "Fixture later edit")
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(change_id, "home")
        inventory.apply(Op("collection.remove", {"space": "home", "original": list(rules.ident(row))}), existing.ACTOR, "Fixture removal")
        inventory.apply(Op("collection.add", {"space": "home", "row": row}), existing.ACTOR, "Fixture recreation")
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(change_id, "home")
        self.assertEqual(self.persisted(), before)

    def test_repeat_inverse_and_late_sql_failure_preserve_state_and_clear_connection(self):
        change_id, _ = self.add()
        plan = inventory.undo_review(change_id, "home")
        before = self.persisted()
        original = pg._diff
        def late(*args):
            original(*args)
            raise Invalid("Synthetic late write failure")
        with mock.patch.object(pg, "_diff", side_effect=late), self.assertRaises(Invalid):
            self.apply(change_id, plan)
        self.assertEqual(self.persisted(), before)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))
        self.apply(change_id, plan)
        saved = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            self.apply(change_id, plan)
        self.assertEqual(self.persisted(), saved)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))

    def test_either_revision_refuses_even_with_unchanged_inserted_row(self):
        change_id, _ = self.add()
        for table in ("inventory_revision", "decks_revision"):
            with self.subTest(table=table):
                plan = inventory.undo_review(change_id, "home")
                with self.connect("owner") as c:
                    c.execute("update " + table + " set revision=revision+1")
                before = self.persisted()
                with self.assertRaises(undo.UndoConflict):
                    self.apply(change_id, plan)
                self.assertEqual(self.persisted(), before)

    def test_removal_source_and_physical_checks_reuse_the_locked_connection(self):
        change_id, _ = self.add()
        plan = inventory.undo_review(change_id, "home")
        original = self.backend._call
        def no_nested_connection(work):
            self.assertIsNone(getattr(self.backend._applying, "connection", None), "Undo opened a second applying connection")
            return original(work)
        with mock.patch.object(self.backend, "_call", side_effect=no_nested_connection):
            self.apply(change_id, plan)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))
