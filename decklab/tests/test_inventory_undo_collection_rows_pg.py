"""Collection-row batch Undo proved before commit, in a disposable PostgreSQL database only."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import config, inventory
from decklab.lib.inventory import Op, undo, undo_collection_rows as rows_undo
from decklab.tests import db_support, test_inventory_undo_pg as existing
from decklab.tests import test_collection_edit as collection_fixture
from decklab.tests import test_inventory_undo_batch_delete_pg as delete_fixture

REASON = "Correct accidental restoration."


class CollectionRowsProofPgTests(db_support.DbTestCase):
    setUp = existing.UndoPgTests.setUp
    fresh = existing.UndoPgTests.fresh
    sql = existing.UndoPgTests.sql
    persisted = existing.UndoPgTests.persisted
    source = existing.UndoPgTests.source
    delete = delete_fixture.BatchDeleteUndoPgTests.delete

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        folder = tempfile.TemporaryDirectory(prefix="decklab-collection-rows-pg-", dir=root)
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Collection-row Undo proofs require a disposable database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def undo(self, source, **extra):
        plan = inventory.undo_review(source, "home")
        reason = extra.get("reason")
        return inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"], **extra}),
                               existing.ACTOR, "Fixture collection-row Undo", **({"reason": reason} if reason else {}))

    def test_restore_and_removal_are_proved_from_their_own_audit_rows_and_reason(self):
        deleted, _ = self.delete()
        with mock.patch.object(rows_undo, "confirm_in_transaction", wraps=rows_undo.confirm_in_transaction) as hook:
            _, summary = self.undo(deleted, confirm_owned=True)
        self.assertEqual(hook.call_count, 1)
        self.assertNotIn(rows_undo.PROOF, summary.extra)
        restored = self.source("collection_card")
        self.assertEqual(self.sql("select op from audit.row_change where change_set_id=%s", (restored,)), [("INSERT",)] * 2)
        self.assertEqual(self.sql("select reason from audit.change_set where id=%s", (restored,)), [(None,)])
        with mock.patch.object(rows_undo, "confirm_in_transaction", wraps=rows_undo.confirm_in_transaction) as hook:
            _, summary = self.undo(restored, reason=REASON)
        self.assertEqual(hook.call_count, 1)
        self.assertNotIn(rows_undo.PROOF, summary.extra)
        removed = self.source("collection_card")
        self.assertEqual(self.sql("select op from audit.row_change where change_set_id=%s", (removed,)), [("DELETE",)] * 2)
        self.assertEqual(self.sql("select reason from audit.change_set where id=%s", (removed,)), [(REASON,)])

    def test_an_unconfirmed_effect_rolls_back_both_directions(self):
        deleted, _ = self.delete()
        before = self.persisted()
        with mock.patch.object(rows_undo, "_remaining_collection", return_value={}), \
                self.assertRaises(undo.UndoConflict) as caught:
            self.undo(deleted, confirm_owned=True)
        self.assertEqual(str(caught.exception), rows_undo.UNCONFIRMED)
        self.assertEqual(self.persisted(), before)
        self.undo(deleted, confirm_owned=True)
        restored = self.source("collection_card")
        before = self.persisted()
        real = rows_undo.confirm
        def tampered(before_inv, saved, summary, actual, reason):
            return real(before_inv, saved, summary, actual[:1], reason)
        with mock.patch.object(rows_undo, "confirm", side_effect=tampered), self.assertRaises(undo.UndoConflict):
            self.undo(restored, reason=REASON)
        self.assertEqual(self.persisted(), before)
        self.undo(restored, reason=REASON)
        self.assertEqual(self.sql("select op from audit.row_change where change_set_id=%s", (self.source("collection_card"),)),
                         [("DELETE",)] * 2)
