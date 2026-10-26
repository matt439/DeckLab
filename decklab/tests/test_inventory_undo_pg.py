"""Actual audited inverse writes and lock races in one disposable PostgreSQL database."""
import copy
import json
import os
import tempfile
import threading
from pathlib import Path
from unittest import mock

from decklab.lib import access, config, inventory
from decklab.lib.api import activity_undo
from decklab.lib.inventory import Op, Summary, files, ops_collection, pg, rules, undo
from decklab.lib.state import Invalid
from decklab.lib.tokens import ops as token_ops
from decklab.tests import db_support
from decklab.tests import test_collection_edit as collection_fixture
from decklab.tests import test_precon_tokens_pg as pg_fixture

ACTOR = pg_fixture.ACTOR


class UndoPgTests(db_support.DbTestCase):
    setUp = pg_fixture.PreconTokensPgTests.setUp
    fresh = pg_fixture.PreconTokensPgTests.fresh
    sql = pg_fixture.PreconTokensPgTests.sql
    persisted = pg_fixture.PreconTokensPgTests.persisted_state

    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-undo-pg-config-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Undo integration requires a guarded disposable test database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def card(self, space="home"):
        return next(row.as_dict() for row in self.fresh().collection(space).rows if row.name == "Llanowar Elves")

    def edit_card(self, note, space="home"):
        row = self.card(space)
        return inventory.apply(Op("collection.edit", {"space": space, "original": list(rules.ident(row)),
                                                       "row": {**row, "notes": note}}), ACTOR, "Fixture card edit")

    def source(self, table):
        return self.sql("select change_set_id from audit.row_change where table_name=%s order by id desc limit 1", (table,))[0][0]

    def source_card(self):
        self.edit_card("Current fixture note")
        return self.source("collection_card")

    def source_tokens(self):
        row = {field: "" for field in rules.TOKEN_FIELDS}
        row.update(front="Dog", quantity="3", notes="Original fixture; printing and reverse face unconfirmed")
        inventory.apply(Op("tokens.add", {"space": "home", "sha256": None, "row": row, "separate": True}), ACTOR, "Fixture tokens")
        sheet = self.fresh().token_set("home")
        base = sheet.rows[0].as_dict()
        inventory.apply(Op("tokens.edit", {"space": "home", "sha256": files.rendered_sha256(sheet), "base": base,
                                            "row": {**base, "quantity": "2", "notes": "Current fixture; printing and reverse face unconfirmed"},
                                            "separate": True}), ACTOR, "Fixture token edit")
        return self.source("token_card")

    def apply_review(self, change_id, plan=None):
        plan = plan or inventory.undo_review(change_id, "home")
        return inventory.apply(Op("inventory.undo", {"change_id": change_id, "space": "home", "expect": plan["expect"]}),
                               ACTOR, f"Undo fixture change {change_id}")

    def test_one_inverse_is_new_audit_set_with_original_history_and_other_data_unchanged(self):
        change_id = self.source_card()
        plan = inventory.undo_review(change_id, "home")
        before = self.persisted()
        original = self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s order by id", (change_id,))
        after, summary = self.apply_review(change_id, plan)
        written = self.persisted()
        self.assertEqual(summary.counts["undo"], 1)
        self.assertTrue(summary.changed)
        self.assertEqual(summary.extra["undo_of"], change_id)
        self.assertEqual(undo.restored_row(after, plan), plan["restore"])
        self.assertEqual(len(written["audit.change_set"]), len(before["audit.change_set"]) + 1)
        self.assertEqual(len(written["audit.row_change"]), len(before["audit.row_change"]) + 1)
        self.assertEqual(self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s order by id", (change_id,)), original)
        for table in ("token_card", "deck", "deck_text", "deck_line", "deck_revision", "decks_revision"):
            self.assertEqual(written[table], before[table], table)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))
        with self.assertRaises(undo.UndoConflict):
            self.apply_review(change_id, plan)
        self.assertEqual(self.persisted(), written)

    def test_token_inverse_preserves_real_id_and_returns_an_actual_changed_row(self):
        change_id = self.source_tokens()
        plan = inventory.undo_review(change_id, "home")
        old_id = self.fresh().token_set("home").rows[0].id
        after, summary = self.apply_review(change_id, plan)
        self.assertEqual(after.token_set("home").rows[0].id, old_id)
        self.assertEqual(after.token_set("home").rows[0].qty, 3)
        self.assertEqual(undo.restored_row(after, plan), plan["restore"])
        self.assertTrue(summary.changed)
        self.assertEqual(summary.extra["kind"], "tokens")

    def test_real_api_receipt_uses_committed_collection_and_token_rows(self):
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            for source in (self.source_card, self.source_tokens):
                change_id = source()
                preview = activity_undo.undo_view(id=str(change_id))
                answer = activity_undo.apply_undo(json.dumps({"profile": "matt", "id": change_id,
                                                             "expect": preview["expect"]}).encode())
                self.assertTrue(answer["saved"])
                self.assertEqual(answer["source_id"], change_id)
                self.assertEqual(answer["restored"], preview["restored"])
                saved = self.fresh()
                sheet = saved.collection("home") if answer["kind"] == "collection" else saved.token_set("home")
                self.assertEqual(answer["sha256"], files.rendered_sha256(sheet))
                self.assertEqual(answer["revision"], saved.revision)
                self.assertIsInstance(answer["restored"]["quantity"], int)
                self.assertNotIn("id", answer["restored"])
                self.assertNotIn("position", answer["restored"])
                self.assertIsNone(getattr(self.backend._applying, "connection", None))

    def test_audit_reads_during_apply_reuse_the_locked_connection_and_cleanup_on_refusal(self):
        change_id = self.source_card()
        plan = inventory.undo_review(change_id, "home")
        original = self.backend._call
        def no_second_connection(work):
            self.assertIsNone(getattr(self.backend._applying, "connection", None), "Audit opened another applying connection")
            return original(work)
        with mock.patch.object(self.backend, "_call", side_effect=no_second_connection):
            self.apply_review(change_id, plan)
            with self.assertRaises(undo.UndoConflict):
                self.apply_review(change_id, plan)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))

    def test_later_touch_away_and_back_refuses_even_when_every_current_value_matches(self):
        change_id = self.source_card()
        expected = self.card()
        self.edit_card("Temporary later edit")
        self.edit_card(expected["notes"])
        self.assertEqual(self.card(), expected)
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(change_id, "home")
        self.assertEqual(self.persisted(), before)

    def test_delete_and_recreate_cannot_turn_old_audit_into_authority(self):
        change_id = self.source_card()
        row = self.card()
        inventory.apply(Op("collection.remove", {"space": "home", "original": list(rules.ident(row))}), ACTOR, "Fixture remove")
        inventory.apply(Op("collection.add", {"space": "home", "row": row}), ACTOR, "Fixture recreate")
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(change_id, "home")
        self.assertEqual(self.persisted(), before)

    def test_multirow_change_cannot_expose_hidden_space_or_undo_only_its_visible_piece(self):
        outer = self
        class TwoRows:
            kind = "fixture.two-rows"
            def run(self, snapshot):
                after = snapshot
                for space in ("home", "user2"):
                    row = outer.card(space)
                    after, _ = ops_collection.edit(after, space, list(rules.ident(row)), {**row, "notes": "Fixture combined edit"})
                return after, Summary("Fixture combined update")
        inventory.apply(TwoRows(), ACTOR, "Fixture mixed source")
        change_id = self.source("collection_card")
        before = self.persisted()
        with self.assertRaises(undo.UndoMissing):
            inventory.undo_review(change_id, "home")
        self.assertEqual(self.persisted(), before)

    def test_late_database_write_failure_rolls_back_inverse_and_audit_and_clears_context(self):
        change_id = self.source_card()
        plan = inventory.undo_review(change_id, "home")
        before = self.persisted()
        original = pg._diff
        def fail_after_sql(*args):
            original(*args)
            raise Invalid("Fixture late write failure")
        with mock.patch.object(pg, "_diff", side_effect=fail_after_sql), self.assertRaises(Invalid):
            self.apply_review(change_id, plan)
        self.assertEqual(self.persisted(), before)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))

    def test_audit_row_order_wins_when_change_set_ids_were_allocated_in_reverse_write_order(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        original = pg._take_lock
        def controlled_lock(cursor):
            if threading.current_thread().name == "undo-early-allocation":
                entered.set()
                if not release.wait(5):
                    raise AssertionError("Fixture timed out waiting for its one competing write")
            original(cursor)
        row = self.card()
        def early():
            try:
                inventory.apply(Op("collection.edit", {"space": "home", "original": list(rules.ident(row)),
                                                       "row": {**row, "notes": "Early allocated saved last"}}), ACTOR, "Fixture early allocation")
            except BaseException as error:
                errors.append(error)
        with mock.patch.object(pg, "_take_lock", side_effect=controlled_lock):
            thread = threading.Thread(target=early, name="undo-early-allocation")
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.edit_card("Later allocated saved first")
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
        if errors:
            raise errors[0]
        rows = self.sql("select id,change_set_id,after->>'notes' from audit.row_change where table_name='collection_card' "
                        "and after->>'notes' in ('Early allocated saved last','Later allocated saved first') order by id")
        self.assertEqual([row[2] for row in rows], ["Later allocated saved first", "Early allocated saved last"])
        self.assertGreater(rows[0][1], rows[1][1])
        with self.assertRaises(undo.UndoConflict):
            inventory.undo_review(rows[0][1], "home")
        plan = inventory.undo_review(rows[1][1], "home")
        self.assertEqual(plan["row_change_id"], rows[1][0])
        self.apply_review(rows[1][1], plan)
        self.assertEqual(self.card()["notes"], "Later allocated saved first")
