"""Whole collection identity/mixed proofs against a guarded disposable PostgreSQL only."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import config, inventory
from decklab.lib.inventory import Op, ops_collection, rules, undo
from decklab.lib.inventory import undo_collection_changes as recovery
from decklab.tests import db_support
from decklab.tests import test_collection_edit as profiles
from decklab.tests import test_inventory_undo_pg as existing

REASON = "Correct the complete disposable collection change."


class CollectionChangesPgTests(db_support.DbTestCase):
    setUp = existing.UndoPgTests.setUp
    fresh = existing.UndoPgTests.fresh
    sql = existing.UndoPgTests.sql
    persisted = existing.UndoPgTests.persisted
    source = existing.UndoPgTests.source
    card = existing.UndoPgTests.card

    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-collection-change-pg-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(profiles.ROLES), encoding="utf-8")
        for patch in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict("os.environ", {config.EXTRA_ENV: ""})):
            patch.start()
            cls.addClassCleanup(patch.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Collection recovery requires a guarded disposable database")
        db_support.seed_membership(cls.dbname, profiles.ROLES["profiles"])

    def identity(self):
        old = self.card()
        new = {**old, "set": "m19", "collector_number": "314"}
        inventory.apply(Op("collection.edit", {"space": "home", "original": list(rules.ident(old)), "row": new}),
                        existing.ACTOR, "Disposable printing correction")
        return self.source("collection_card"), old, new

    def inverse(self, source, plan=None):
        plan = inventory.undo_review(source, "home") if plan is None else plan
        return inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"],
            **({"reason": REASON} if plan["reason_required"] else {}),
            **({"confirm_owned": True} if plan["physical_confirmation_required"] else {})}), existing.ACTOR,
            "Undo disposable collection change", **({"reason": REASON} if plan["reason_required"] else {}))

    def test_identity_inverse_proves_delete_insert_and_transports_current_location_without_rewriting_source(self):
        source, old, new = self.identity()
        sheet = self.fresh().collection("home")
        inventory.apply(Op("collection.locations", {"space": "home", "keys": [list(rules.ident(new))], "location": "Row 4",
            "sha256": ops_collection.sha256_of(sheet), "locations_sha256": ops_collection.locations_sha256_of(self.fresh(), "home")}),
            existing.ACTOR, "Move disposable current location")
        original = self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s order by id", (source,))
        plan = inventory.undo_review(source, "home")
        self.assertEqual(plan["location_transfer"]["location"], "Row 4")
        with mock.patch.object(recovery, "confirm_in_transaction", wraps=recovery.confirm_in_transaction) as proof:
            after, summary = self.inverse(source, plan)
        proof.assert_called_once()
        self.assertTrue(summary.extra["collection_confirmed"])
        self.assertEqual(after.locations_of("home"), {rules.ident(old): "Row 4"})
        self.assertEqual(sorted(row[0] for row in self.sql("select op from audit.row_change where change_set_id=(select max(id) from audit.change_set)")),
                         ["DELETE", "INSERT"])
        self.assertEqual(self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s order by id", (source,)), original)

    def test_upload_free_merge_has_one_exact_whole_mixed_inverse(self):
        old = self.card()
        new = {**old, "set": "m19", "collector_number": "314", "quantity": "1"}
        before = self.fresh()
        inventory.apply(Op("collection.import", {"space": "home", "sources": [("fixture", [{**old, "quantity": "2"}, new])]}),
                        existing.ACTOR, "Disposable upload-free merge")
        source = self.source("collection_card")
        plan = inventory.undo_review(source, "home")
        self.assertEqual(plan["action"], recovery.ACTION)
        self.assertTrue(plan["reason_required"])
        self.assertFalse(plan["physical_confirmation_required"])
        after, _ = self.inverse(source, plan)
        self.assertEqual(after.collection("home"), before.collection("home"))
        self.assertEqual(sorted(row[0] for row in self.sql("select op from audit.row_change where change_set_id=(select max(id) from audit.change_set)")),
                         ["DELETE", "UPDATE"])

    def test_extra_actual_audit_row_rolls_back_every_inventory_and_audit_change(self):
        source, _, _ = self.identity()
        plan, before = inventory.undo_review(source, "home"), self.persisted()
        real = recovery.confirm
        def extra_row(before_inv, after_inv, summary, actual, reason):
            return real(before_inv, after_inv, summary, actual + actual, reason)
        with mock.patch.object(recovery, "confirm", side_effect=extra_row), self.assertRaises(undo.UndoConflict):
            self.inverse(source, plan)
        self.assertEqual(self.persisted(), before)

    def test_count_details_and_location_edit_restores_card_facts_while_current_location_is_kept(self):
        old = self.card()
        inventory.apply(Op("collection.edit", {"space": "home", "original": list(rules.ident(old)),
            "row": {**old, "quantity": str(int(old["quantity"]) + 2), "notes": "Disposable correction"}, "location": "Row 2"}),
            existing.ACTOR, "Disposable card facts and location correction")
        source = self.source("collection_card")
        plan = inventory.undo_review(source, "home")
        self.assertEqual(plan["action"], recovery.ACTION)
        self.assertFalse(plan["reason_required"] or plan["physical_confirmation_required"])
        after, _ = self.inverse(source, plan)
        restored = next(row.as_dict() for row in after.collection("home").rows if rules.ident(row.as_dict()) == rules.ident(old))
        self.assertEqual(restored, old)
        self.assertEqual(after.locations_of("home")[rules.ident(old)], "Row 2")

    def test_reused_audit_id_in_actual_proof_rolls_every_database_row_back(self):
        source, _, _ = self.identity()
        plan, before = inventory.undo_review(source, "home"), self.persisted()
        real = recovery.confirm
        def reused_id(before_inv, after_inv, summary, actual, reason):
            actual = [{**row, "id": max(summary.extra["row_change_ids"])} for row in actual]
            return real(before_inv, after_inv, summary, actual, reason)
        with mock.patch.object(recovery, "confirm", side_effect=reused_id), self.assertRaises(undo.UndoConflict):
            self.inverse(source, plan)
        self.assertEqual(self.persisted(), before)
