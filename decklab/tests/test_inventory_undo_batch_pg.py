"""Complete batch Undo audit proof and atomicity in disposable PostgreSQL only."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import access, config, inventory
from decklab.lib.api import activity_undo
from decklab.lib.inventory import Op, Summary, ops_collection, pg, rules, undo
from decklab.lib.state import Invalid
from decklab.tests import db_support, test_inventory_undo_pg as existing
from decklab.tests import test_collection_edit as collection_fixture


class BatchUndoPgTests(db_support.DbTestCase):
    setUp = existing.UndoPgTests.setUp
    fresh = existing.UndoPgTests.fresh
    sql = existing.UndoPgTests.sql
    persisted = existing.UndoPgTests.persisted
    source = existing.UndoPgTests.source

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        folder = tempfile.TemporaryDirectory(prefix="decklab-undo-batch-pg-", dir=root)
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Metadata Undo requires a disposable database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def seed(self, count=2):
        rows = [{"name": "Llanowar Elves", "set": "fdn", "collector_number": str(1000 + index), "finish": "nonfoil",
                 "quantity": "2", "condition": "" if index % 2 == 0 else "legacy condition",
                 "language": "" if index % 2 == 0 else "de", "notes": "Unchanged metadata note " + str(index)}
                for index in range(count)]
        class Seed:
            kind = "fixture.metadata-seed"
            def run(self, snapshot):
                old = [row.as_dict() for row in snapshot.collection("home").rows]
                return snapshot.with_collection("home", [*old, *rows]), Summary("Seed disposable metadata rows")
        inventory.apply(Seed(), existing.ACTOR, "Fixture metadata seed")
        edits = [(list(rules.ident(row)), {**row, "condition": "NM", "language": "en"}) for row in rows]
        inventory.apply(Op("collection.apply", {"space": "home", "edits": edits}), existing.ACTOR, "Fixture metadata update")
        return self.source("collection_card"), rows

    def apply(self, source, plan=None):
        plan = inventory.undo_review(source, "home") if plan is None else plan
        return inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"]}),
                               existing.ACTOR, "Undo fixture metadata batch")

    def test_complete_fifty_row_reader_keeps_single_default(self):
        source, _ = self.seed(50)
        self.assertEqual(len(self.backend.undo_audit(source)), 2)
        self.assertEqual(len(self.backend.undo_audit_batch(source)), 50)
        self.assertEqual(inventory.undo_review(source, "home")["row_count"], 50)

    def test_fifty_first_row_refuses_without_truncated_authority(self):
        source, _ = self.seed(51)
        self.assertEqual(len(self.backend.undo_audit_batch(source)), 51)
        before = self.persisted()
        with self.assertRaises(undo.UndoMissing):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)

    def test_actual_api_restores_full_rows_in_one_new_audit_and_leaves_stock_and_source_unchanged(self):
        source, rows = self.seed()
        before = self.persisted()
        original = self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s order by id", (source,))
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            preview = activity_undo.undo_view(id=str(source))
            result = activity_undo.apply_undo(json.dumps({"profile": "matt", "id": source, "expect": preview["expect"]}).encode())
        self.assertEqual(result["action"], "batch_metadata")
        self.assertEqual(result["row_count"], 2)
        expected = {rules.ident(row): {**row, "quantity": int(row["quantity"])} for row in rows}
        self.assertEqual({rules.ident(item["row"]): item["row"] for item in result["restored_rows"]}, expected)
        written = self.persisted()
        self.assertEqual(len(written["audit.change_set"]), len(before["audit.change_set"]) + 1)
        self.assertEqual(len(written["audit.row_change"]), len(before["audit.row_change"]) + 2)
        self.assertEqual(self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s order by id", (source,)), original)
        for table in ("token_card", "deck", "deck_text", "deck_line", "deck_revision", "decks_revision"):
            self.assertEqual(written[table], before[table], table)
        self.assertEqual(self.sql("select actor,source,via from audit.change_set order by id desc limit 1"), [("matt", "web", "tunnel")])

    def test_mixed_global_source_never_authorizes_only_home_rows(self):
        source, _ = self.seed()
        class Mixed:
            kind = "fixture.mixed-metadata"
            def run(self, snapshot):
                after = snapshot
                for space in ("home", "user2"):
                    row = next(row.as_dict() for row in after.collection(space).rows)
                    after, _ = ops_collection.edit(after, space, list(rules.ident(row)), {**row, "language": "fr"})
                return after, Summary("Fixture mixed private batch")
        inventory.apply(Mixed(), existing.ACTOR, "Fixture mixed source")
        source = self.source("collection_card")
        before = self.persisted()
        with self.assertRaises(undo.UndoMissing):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)

    def test_one_later_touch_and_both_revisions_block_the_entire_batch(self):
        source, rows = self.seed()
        for table in ("inventory_revision", "decks_revision"):
            with self.subTest(table=table):
                plan = inventory.undo_review(source, "home")
                with self.connect("owner") as c:
                    c.execute("update " + table + " set revision=revision+1")
                before = self.persisted()
                with self.assertRaises(undo.UndoConflict):
                    self.apply(source, plan)
                self.assertEqual(self.persisted(), before)
        row = next(row.as_dict() for row in self.fresh().collection("home").rows if rules.ident(row.as_dict()) == rules.ident(rows[0]))
        for condition in ("LP", "NM"):
            inventory.apply(Op("collection.edit", {"space": "home", "original": list(rules.ident(row)),
                                                     "row": {**row, "condition": condition}}), existing.ACTOR, "Fixture later touch")
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(source, "home")
        self.assertEqual(self.persisted(), before)

    def test_late_sql_failure_rolls_back_every_row_and_same_connection_is_reused(self):
        source, _ = self.seed()
        plan = inventory.undo_review(source, "home")
        before = self.persisted()
        original_diff, original_call = pg._diff, self.backend._call
        def late(*args):
            original_diff(*args)
            raise Invalid("Synthetic late batch SQL failure")
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
