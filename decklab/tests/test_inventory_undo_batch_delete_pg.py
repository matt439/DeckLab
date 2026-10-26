"""Whole deleted collection batches restore only inside disposable PostgreSQL."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import access, cards, config, inventory
from decklab.lib.api import activity_undo
from decklab.lib.inventory import Op, Summary, files, pg, rules, undo
from decklab.lib.state import Invalid
from decklab.tests import db_support, test_inventory_undo_pg as existing
from decklab.tests import test_collection_edit as collection_fixture


class BatchDeleteUndoPgTests(db_support.DbTestCase):
    setUp = existing.UndoPgTests.setUp
    fresh = existing.UndoPgTests.fresh
    sql = existing.UndoPgTests.sql
    persisted = existing.UndoPgTests.persisted
    source = existing.UndoPgTests.source

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        folder = tempfile.TemporaryDirectory(prefix="decklab-batch-delete-pg-", dir=root)
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Batch restoration requires a disposable database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def delete(self, count=2, *, empty=False):
        rows = [{"name": "Llanowar Elves", "set": "m19" if index == 1 else "fdn",
                 "collector_number": "227" if index == 0 else "314" if index == 1 else str(1000 + index),
                 "finish": "nonfoil", "quantity": str(2 + index % 3), "condition": "" if index % 2 else "legacy condition",
                 "language": "" if index % 2 else "en", "notes": " \tFormer note\r\nUnicode café  " if index % 2 else ""}
                for index in range(count)]
        keys = {rules.ident(row) for row in rows}
        class Seed:
            kind = "fixture.deleted-batch-seed"
            def run(self, snapshot):
                unrelated = [] if empty else [row.as_dict() for row in snapshot.collection("home").rows if rules.ident(row.as_dict()) not in keys]
                return snapshot.with_collection("home", [*unrelated, *rows]), Summary("Seed disposable former rows")
        inventory.apply(Seed(), existing.ACTOR, "Fixture deleted batch seed")
        inventory.apply(Op("collection.apply", {"space": "home", "edits": (), "removals": [list(rules.ident(row)) for row in rows]}),
                        existing.ACTOR, "Fixture whole batch deletion", reason="Synthetic source correction")
        source = self.source("collection_card")
        self.assertEqual(self.sql("select op from audit.row_change where change_set_id=%s order by id", (source,)), [("DELETE",)] * count)
        return source, rows

    def apply(self, source, plan=None, **extra):
        plan = inventory.undo_review(source, "home") if plan is None else plan
        return inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"],
                                                      "confirm_owned": True, **extra}), existing.ACTOR, "Restore disposable deleted batch")

    def test_actual_api_restores_empty_collection_with_one_audit_and_exact_keyed_rows(self):
        source, rows = self.delete(empty=True)
        self.assertEqual(self.fresh().collection("home").rows, ())
        before, snapshot = self.persisted(), self.fresh()
        original = self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s order by id", (source,))
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            preview = activity_undo.undo_view(id=str(source))
            self.assertEqual(preview["action"], "batch_add")
            result = activity_undo.apply_undo(json.dumps({"profile": "matt", "id": source, "expect": preview["expect"],
                                                        "confirm_owned": True}).encode())
        self.assertEqual((result["action"], result["row_count"]), ("batch_add", 2))
        self.assertEqual(result["restored_rows"], [{"key": item["key"], "row": item["restored"]} for item in preview["rows"]])
        self.assertEqual({rules.ident(item["row"]): item["row"] for item in result["restored_rows"]},
                         {rules.ident(row): {**row, "quantity": int(row["quantity"])} for row in rows})
        after, written = self.fresh(), self.persisted()
        self.assertEqual(result["sha256"], files.rendered_sha256(after.collection("home")))
        self.assertEqual(result["revision"], after.revision)
        self.assertEqual(after.collection("user2"), snapshot.collection("user2"))
        self.assertEqual(len(written["audit.change_set"]), len(before["audit.change_set"]) + 1)
        self.assertEqual(len(written["audit.row_change"]), len(before["audit.row_change"]) + 2)
        self.assertEqual(self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s order by id", (source,)), original)
        for table in before.keys() - {"collection_card", "inventory_revision", "audit.change_set", "audit.row_change"}:
            self.assertEqual(written[table], before[table], table)
        self.assertEqual(self.sql("select actor,source,via,reason from audit.change_set order by id desc limit 1"),
                         [("matt", "web", "tunnel", None)])

    def test_confirmation_is_required_in_locked_operation_with_no_rows_or_audit_on_refusal(self):
        source, _ = self.delete()
        plan, before = inventory.undo_review(source, "home"), self.persisted()
        for value in (None, False, 1, "true"):
            with self.subTest(value=value), self.assertRaises(Invalid):
                self.apply(source, plan, confirm_owned=value)
            self.assertEqual(self.persisted(), before)
        with self.assertRaises(Invalid):
            inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"]}),
                            existing.ACTOR, "Unconfirmed fixture batch")
        self.assertEqual(self.persisted(), before)

    def test_both_revision_changes_current_collision_and_add_remove_aba_refuse_whole_batch(self):
        source, rows = self.delete()
        for table in ("inventory_revision", "decks_revision"):
            plan = inventory.undo_review(source, "home")
            with self.connect("owner") as connection:
                connection.execute("update " + table + " set revision=revision+1")
            before = self.persisted()
            with self.subTest(table=table), self.assertRaises(undo.UndoConflict):
                self.apply(source, plan)
            self.assertEqual(self.persisted(), before)
        inventory.apply(Op("collection.add", {"space": "home", "row": rows[-1]}), existing.ACTOR, "Fixture one-key recreation")
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)
        inventory.apply(Op("collection.remove", {"space": "home", "original": list(rules.ident(rows[-1]))}),
                        existing.ACTOR, "Fixture later deletion")
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)

    def test_late_sql_failure_rolls_back_all_additions_and_same_connection_is_reused(self):
        source, _ = self.delete()
        plan, before = inventory.undo_review(source, "home"), self.persisted()
        original_diff, original_call = pg._diff, self.backend._call
        def late(*args):
            original_diff(*args)
            raise Invalid("Synthetic late whole-batch failure")
        with mock.patch.object(pg, "_diff", side_effect=late), self.assertRaises(Invalid):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), before)
        def no_nested(work):
            self.assertIsNone(getattr(self.backend._applying, "connection", None), "Batch opened another applying connection")
            return original_call(work)
        with mock.patch.object(self.backend, "_call", side_effect=no_nested):
            self.apply(source, plan)
        saved = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), saved)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))

    def test_actual_mixed_space_global_deletion_is_unavailable_without_a_partial_restore(self):
        class Mixed:
            kind = "fixture.mixed-delete"
            def run(self, snapshot):
                after = snapshot
                for space in ("home", "user2"):
                    row = after.collection(space).rows[0].as_dict()
                    after, _ = inventory.Op("collection.remove", {"space": space, "original": list(rules.ident(row))}).run(after)
                return after, Summary("Fixture mixed deletion")
        inventory.apply(Mixed(), existing.ACTOR, "Fixture mixed private deletion")
        source, before = self.source("collection_card"), self.persisted()
        with self.assertRaises(undo.UndoMissing):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)

    def test_changed_or_unavailable_cached_printing_refuses_without_any_database_write(self):
        source, _ = self.delete()
        before = self.persisted()
        for value in (None, {"name": "Elvish Mystic", "games": ["paper"], "finishes": ["nonfoil"], "digital": False}):
            with self.subTest(value=value), mock.patch.object(cards, "printing", return_value=value), self.assertRaises(undo.UndoUnsupported):
                inventory.undo_review(source, "home")
            self.assertEqual(self.persisted(), before)

    def test_complete_fifty_deletes_restore_and_default_reader_remains_bounded(self):
        source, _ = self.delete(count=50)
        self.assertEqual(len(self.backend.undo_audit(source)), 2)
        self.assertEqual(len(self.backend.undo_audit_batch(source)), 50)
        printed, card = cards.printing("fdn", "227"), cards.printing_card("fdn", "227")
        with mock.patch.object(cards, "printing", side_effect=lambda set_, number: {**printed, "set": set_, "collector_number": number}), \
                mock.patch.object(cards, "printing_card", return_value=card):
            plan = inventory.undo_review(source, "home")
            self.assertEqual(plan["row_count"], 50)
            after, summary = self.apply(source, plan)
        self.assertEqual(summary.counts["added_rows"], 50)
        self.assertEqual(len(undo.restored_rows(after, plan)), 50)

    def test_fifty_first_delete_refuses_before_card_or_row_details(self):
        source, _ = self.delete(count=51)
        before = self.persisted()
        with mock.patch.object(cards, "printing", side_effect=AssertionError("No capped authority")), self.assertRaises(undo.UndoMissing):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)
