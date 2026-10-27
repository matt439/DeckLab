"""Strict whole-batch removal of actual restored INSERT audit rows in disposable DBs."""
import contextlib
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import access, cards, config, inventory
from decklab.lib.api import activity_undo
from decklab.lib.inventory import Op, Summary, files, model, pg, rules, undo
from decklab.lib.state import Invalid
from decklab.tests import db_support, test_inventory_undo_pg as existing
from decklab.tests import test_collection_edit as collection_fixture
from decklab.tests import test_inventory_undo_batch_delete_pg as delete_fixture


class BatchInsertUndoPgTests(db_support.DbTestCase):
    setUp = existing.UndoPgTests.setUp
    fresh = existing.UndoPgTests.fresh
    sql = existing.UndoPgTests.sql
    persisted = existing.UndoPgTests.persisted
    source = existing.UndoPgTests.source
    delete = delete_fixture.BatchDeleteUndoPgTests.delete

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        folder = tempfile.TemporaryDirectory(prefix="decklab-batch-insert-pg-", dir=root)
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Batch removal requires a disposable database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def restored_batch(self, count=2, *, empty=False):
        deleted, rows = self.delete(count=count, empty=empty)
        with contextlib.ExitStack() as stack:
            if count > 2:
                printed, card = cards.printing("fdn", "227"), cards.printing_card("fdn", "227")
                stack.enter_context(mock.patch.object(cards, "printing", side_effect=lambda set_, number:
                    {**printed, "set": set_, "collector_number": number}))
                stack.enter_context(mock.patch.object(cards, "printing_card", return_value=card))
            plan = inventory.undo_review(deleted, "home")
            inventory.apply(Op("inventory.undo", {"change_id": deleted, "space": "home", "expect": plan["expect"],
                                                  "confirm_owned": True}), existing.ACTOR, "Restore fixture batch")
        source = self.source("collection_card")
        self.assertEqual(self.sql("select table_name,op,before from audit.row_change where change_set_id=%s order by id", (source,)),
                         [("collection_card", "INSERT", None)] * count)
        return source, rows

    def apply(self, source, plan=None, **extra):
        plan = inventory.undo_review(source, "home") if plan is None else plan
        return inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"],
                                                      "reason": "Correct accidental restoration.", **extra}),
                               existing.ACTOR, "Remove accidental fixture restoration", reason="Correct accidental restoration.")

    def test_real_batch_add_is_eligible_and_api_removes_all_rows_with_one_reasoned_audit(self):
        source, rows = self.restored_batch(empty=True)
        before, snapshot = self.persisted(), self.fresh()
        original = self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s order by id", (source,))
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            preview = activity_undo.undo_view(id=str(source))
            self.assertEqual(preview["action"], "batch_remove")
            result = activity_undo.apply_undo(json.dumps({"profile": "matt", "id": source, "expect": preview["expect"],
                                                        "reason": "  Correct  accidental restoration.  "}).encode())
        self.assertEqual((result["action"], result["row_count"]), ("batch_remove", 2))
        self.assertEqual(result["removed_keys"], [item["key"] for item in preview["rows"]])
        self.assertIsNone(result["restored"])
        self.assertEqual({tuple(item.values()) for item in result["removed_keys"]},
                         {tuple(row[key] for key in ("set", "collector_number", "finish")) for row in rows})
        after, written = self.fresh(), self.persisted()
        self.assertEqual(after.collection("home").rows, ())
        self.assertEqual(result["sha256"], files.rendered_sha256(after.collection("home")))
        self.assertEqual(result["revision"], after.revision)
        self.assertEqual(after.collection("user2"), snapshot.collection("user2"))
        self.assertEqual(len(written["audit.change_set"]), len(before["audit.change_set"]) + 1)
        self.assertEqual(len(written["audit.row_change"]), len(before["audit.row_change"]) + 2)
        self.assertEqual(self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s order by id", (source,)), original)
        self.assertEqual(self.sql("select actor,source,via,reason from audit.change_set order by id desc limit 1"),
                         [("matt", "web", "tunnel", "Correct accidental restoration.")])
        for table in before.keys() - {"collection_card", "inventory_revision", "audit.change_set", "audit.row_change"}:
            self.assertEqual(written[table], before[table], table)

    def test_complete_survivors_and_other_physical_records_are_unchanged(self):
        source, _ = self.restored_batch()
        plan, before = inventory.undo_review(source, "home"), self.fresh()
        after, summary = self.apply(source, plan)
        self.assertEqual((summary.counts["edited"], summary.counts["removed"]), (0, 2))
        self.assertEqual(undo.removed_keys(after, plan), [{key: item["current"][key] for key in ("set", "collector_number", "finish")}
                                                       for item in plan["rows"]])
        self.assertEqual(after, before.replace(collections=after.collections, revision=after.revision))
        self.assertEqual(after.collection("user2"), before.collection("user2"))
        target_keys = {rules.ident(item["current"]) for item in plan["rows"]}
        self.assertEqual({rules.ident(row.as_dict()): row.as_dict() for row in after.collection("home").rows},
                         {rules.ident(row.as_dict()): row.as_dict() for row in before.collection("home").rows
                          if rules.ident(row.as_dict()) not in target_keys})

    def test_reason_is_required_inside_locked_operation_and_cannot_be_truthy_nontext(self):
        source, _ = self.restored_batch()
        plan, before = inventory.undo_review(source, "home"), self.persisted()
        for reason in (None, "", " \t ", 1, [], "x" * 201):
            with self.subTest(reason=repr(reason)), self.assertRaises(Invalid):
                self.apply(source, plan, reason=reason)
            self.assertEqual(self.persisted(), before)
        with self.assertRaises(Invalid):
            inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"]}),
                            existing.ACTOR, "Unreasoned fixture removal")
        self.assertEqual(self.persisted(), before)

    def test_same_name_surplus_and_unknown_installed_demand_refuse_entire_batch(self):
        source, _ = self.restored_batch()
        class Holder:
            kind = "fixture.physical-holder"
            def __init__(self, anonymous):
                self.anonymous = anonymous
            def run(self, snapshot):
                row = {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "foil", "quantity": "99",
                       "condition": "", "language": "", "notes": "Unrelated surplus printing"}
                current = [item.as_dict() for item in snapshot.collection("home").rows if rules.ident(item.as_dict()) != rules.ident(row)]
                recipe = {"target": [], "owned": [], "built": {"version": "target",
                          "cards": [{"for": "Elvish Mystic", "using": None, "qty": 1}]}}
                main = "1 Elvish Mystic" if self.anonymous else "1 Llanowar Elves"
                header = "- **Stand-ins:** " + json.dumps(recipe) + "\n" if self.anonymous else ""
                text = "# Physical fixture\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** built\n" + header \
                    + "\n## Decklist\n\n```\nDeck\n" + main + "\n59 Forest\n```\n"
                return snapshot.with_collection("home", [*current, row]).with_deck(model.Deck("home", "casual", "holder", text)), Summary("Fixture holder")
        for anonymous in (False, True):
            inventory.apply(Holder(anonymous), existing.ACTOR, "Fixture physical uncertainty")
            before = self.persisted()
            with self.subTest(anonymous=anonymous), self.assertRaises(undo.UndoConflict):
                inventory.undo_review(source, "home")
            self.assertEqual(self.persisted(), before)

    def test_actual_import_audit_is_not_reinterpreted_as_collection_insert_only(self):
        row = {"name": "Llanowar Elves", "set": "m19", "collector_number": "314", "finish": "nonfoil", "quantity": "1",
               "condition": "", "language": "", "notes": "Disposable import"}
        text = rules.collection_csv_bytes([row]).decode("utf-8")
        inventory.apply(Op("collection.import", {"space": "home", "sources": [("fixture.csv", [row])],
                                                  "uploads": [("fixture", text)]}), existing.ACTOR, "Fixture import source")
        source, before = self.source("collection_card"), self.persisted()
        self.assertIn("collection_import", {row[0] for row in self.sql("select table_name from audit.row_change where change_set_id=%s", (source,))})
        with self.assertRaises(undo.UndoMissing):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)

    def test_both_revisions_and_update_away_back_aba_block_all_removals(self):
        source, _ = self.restored_batch()
        for table in ("inventory_revision", "decks_revision"):
            plan = inventory.undo_review(source, "home")
            with self.connect("owner") as connection:
                connection.execute("update " + table + " set revision=revision+1")
            before = self.persisted()
            with self.subTest(table=table), self.assertRaises(undo.UndoConflict):
                self.apply(source, plan)
            self.assertEqual(self.persisted(), before)
        row = next(row.as_dict() for row in self.fresh().collection("home").rows if row.set == "m19")
        for note in ("Later edit", row["notes"]):
            inventory.apply(Op("collection.edit", {"space": "home", "original": list(rules.ident(row)), "row": {**row, "notes": note}}),
                            existing.ACTOR, "Fixture later target touch")
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)

    def test_late_sql_failure_rolls_back_all_deletions_and_receipts_share_locked_connection(self):
        source, _ = self.restored_batch()
        plan, before = inventory.undo_review(source, "home"), self.persisted()
        original_diff, original_call = pg._diff, self.backend._call
        def late(*args):
            original_diff(*args)
            raise Invalid("Synthetic late batch-removal SQL failure")
        with mock.patch.object(pg, "_diff", side_effect=late), self.assertRaises(Invalid):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), before)
        def no_nested(work):
            self.assertIsNone(getattr(self.backend._applying, "connection", None), "Batch opened a nested applying connection")
            return original_call(work)
        with mock.patch.object(self.backend, "_call", side_effect=no_nested):
            after, _ = self.apply(source, plan)
        self.assertEqual(len(undo.removed_keys(after, plan)), 2)
        saved = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), saved)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))

    def test_fifty_actual_restoration_rows_remove_and_fifty_first_insert_refuses(self):
        source, _ = self.restored_batch(count=50)
        self.assertEqual(len(self.backend.undo_audit(source)), 2)
        self.assertEqual(len(self.backend.undo_audit_batch(source)), 50)
        plan = inventory.undo_review(source, "home")
        after, summary = self.apply(source, plan)
        self.assertEqual(summary.counts["removed"], 50)
        self.assertEqual(len(undo.removed_keys(after, plan)), 50)
        class TooMany:
            kind = "fixture.fifty-one-inserts"
            def run(self, snapshot):
                rows = [row.as_dict() for row in snapshot.collection("home").rows]
                rows.extend({"name": "Llanowar Elves", "set": "fdn", "collector_number": str(2000 + index), "finish": "nonfoil",
                             "quantity": "1", "condition": "", "language": "", "notes": "Synthetic boundary"} for index in range(51))
                return snapshot.with_collection("home", rows), Summary("Fixture boundary source")
        inventory.apply(TooMany(), existing.ACTOR, "Fixture complete boundary")
        source, before = self.source("collection_card"), self.persisted()
        with mock.patch.object(undo, "_insert_removal", side_effect=AssertionError("No capped authority")), self.assertRaises(undo.UndoMissing):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)
