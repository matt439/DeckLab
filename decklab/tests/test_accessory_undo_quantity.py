"""Recorded accessory count recovery over isolated audit-shaped snapshots."""
import copy
from dataclasses import replace
import unittest
from unittest import mock

from decklab.lib import accessories, inventory, profiles
from decklab.lib.inventory import accessory_undo as undo, changes
from decklab.tests import accessory_undo_support as support, household_config


class AccessoryQuantityUndoTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(profiles, "read", return_value=copy.deepcopy(household_config.PROFILES)))
        self.store = support.AuditAccessoryInventory()
        self.addCleanup(inventory.use(self.store))
        self.seed()

    def seed(self, current="100", historical="40", *, kind="sleeves", owner="matt", mixed=False):
        new = support.row(kind=kind, owner=owner, quantity=current, capacity="100" if kind == "deck_box" else "")
        old = {**new, "quantity": historical}
        if mixed:
            old.update(name="Historical <b>literal</b> name", notes="Historical note", link="https://example.com/former")
            if kind == "deck_box":
                old["capacity"] = "60"
        snapshot = support.build_snapshot()
        snapshot = snapshot.with_accessories([new if row.accessory_id == new["id"] else row.as_dict()
                                             for row in snapshot.accessories.rows])
        deck = snapshot.deck("casual/fixture")
        if kind != "sleeves":
            line = "- **Deck box:** a-sleeves\n" if kind == "deck_box" else ""
            snapshot = snapshot.with_deck(replace(deck, text=deck.text.replace("- **Sleeves:** a-sleeves\n", line)))
        self.store.snapshot = snapshot
        self.store.audit = {support.CHANGE_ID: [{"id": support.ROW_ID, "table": "accessory", "op": "UPDATE",
                            "key": {"id": new["id"]}, "before": old, "after": new}]}
        self.store.latest = support.ROW_ID
        return new, old

    def source(self):
        return self.store.audit[support.CHANGE_ID][0]

    def review(self, owners=support.OWNERS):
        return undo.review(support.CHANGE_ID, owners, self.store.snapshot, self.store)

    def test_all_kinds_zero_increases_decreases_and_boundaries_have_distinct_exact_stock_review(self):
        for kind in ("sleeves", "deck_box", "playmat"):
            for current, historical in (("100", "40"), ("1", "9999"), ("2", "0"), ("0", "1")):
                self.seed(current, historical, kind=kind)
                before, original = self.store.snapshot, copy.deepcopy(self.store.audit)
                with self.subTest(kind=kind, current=current, historical=historical):
                    plan, after = self.review()
                    self.assertEqual(plan["action"], "accessory_stock_update")
                    self.assertIs(plan["stock_confirmation_required"], True)
                    self.assertEqual(plan["current"], undo.stock_meta(self.source()["after"]))
                    self.assertEqual(plan["restored"], undo.stock_meta(self.source()["before"]))
                    self.assertEqual(len(plan["restored"]), 11)
                    self.assertEqual(set(plan["restored"]), {*undo.META, "quantity"})
                    self.assertEqual(plan["fields"], [{"field": "quantity", "before": current, "after": historical}])
                    self.assertTrue(all(isinstance(value, str) for value in plan["restored"].values()))
                    receipt = undo.verify_saved(before, after, plan, support.actual_source(plan))
                    self.assertEqual(receipt["restored"], plan["restored"])
                    self.assertEqual((self.store.snapshot, self.store.audit), (before, original))
                    self.assertEqual(after.accessory_images, before.accessory_images)
                    self.assertEqual(after.decks, before.decks)
                    expected = [{**row.as_dict(), "quantity": historical} if row.accessory_id == "a-sleeves"
                                else row.as_dict() for row in before.accessories.rows]
                    self.assertEqual(undo.raw_rows(after), expected)

    def test_mixed_recorded_details_and_capacity_are_restored_with_one_quantity_inverse(self):
        self.seed(kind="deck_box", mixed=True)
        before = self.store.snapshot
        plan, after = self.review()
        self.assertEqual([field["field"] for field in plan["fields"]], ["name", "notes", "link", "capacity", "quantity"])
        self.assertEqual(next(row for row in undo.raw_rows(after) if row["id"] == "a-sleeves"), self.source()["before"])
        self.assertEqual(after.replace(accessories=before.accessories), before)
        self.assertNotIn("reason_required", plan)
        self.assertNotIn("confirmation_required", plan)

    def test_quantities_require_canonical_text_on_both_source_sides(self):
        for side in ("before", "after"):
            for bad in (0, 1, True, None, "", "00", "01", "+1", "-1", " 1 ", "1.0", "10000", "١", "1\0"):
                self.seed()
                self.source()[side]["quantity"] = bad
                with self.subTest(side=side, value=bad), self.assertRaises(undo.UndoUnsupported):
                    self.review()

    def test_stock_action_cannot_change_identity_kind_owner_photo_or_crop(self):
        for field, value in (("id", "other-id"), ("kind", "playmat"), ("owner", "shared"),
                             ("image", "a-sleeves.png"), ("crop", "")):
            self.seed()
            self.source()["before"][field] = value
            with self.subTest(field=field), self.assertRaises((undo.UndoMissing, undo.UndoUnsupported)):
                self.review()

    def test_whole_source_and_writable_owners_precede_stock_or_private_label_validation(self):
        for mode in ("hidden", "owner_move", "mixed", "duplicate"):
            self.seed()
            source = self.source()
            if mode == "mixed":
                self.store.audit[support.CHANGE_ID].append({"table": "accessory_image", "op": "UPDATE"})
            elif mode == "duplicate":
                self.store.audit[support.CHANGE_ID].append(copy.deepcopy(source))
            else:
                source["before"].update(owner="user1", name="Private fixture", quantity=object())
                if mode == "hidden":
                    source["after"]["owner"] = "user1"
            with self.subTest(mode=mode), mock.patch.object(undo, "raw_row", side_effect=AssertionError("No raw proof")), \
                    self.assertRaises(undo.UndoMissing):
                self.review()

    def test_held_stock_correction_keeps_kit_and_reports_normal_shortage_or_box_count_warning(self):
        for kind, current, historical in (("sleeves", "100", "40"), ("deck_box", "1", "0")):
            self.seed(current, historical, kind=kind)
            before = self.store.snapshot
            with inventory.pinned(before):
                old_kit = accessories.kit("casual/fixture", owners=support.OWNERS)
            plan, after = self.review()
            with inventory.pinned(after):
                new_kit = accessories.kit("casual/fixture", owners=support.OWNERS)
            with self.subTest(kind=kind):
                self.assertEqual(after.decks, before.decks)
                self.assertEqual(new_kit[kind if kind == "sleeves" else "deck_box"]["id"], "a-sleeves")
                self.assertEqual(new_kit["need"], 60)
                self.assertNotEqual(new_kit["warnings"], old_kit["warnings"])
                self.assertEqual(undo.verify_saved(before, after, plan, support.actual_source(plan))["restored"]["quantity"], historical)

    def test_trusted_stock_save_requires_exact_confirmation_and_rejects_other_action_controls(self):
        plan, _ = self.review()
        for options in ({}, {"confirm_stock": False}, {"confirm_stock": None}, {"confirm_stock": 1},
                        {"confirm_stock": "true"}, {"confirm_stock": True, "reason": None},
                        {"confirm_stock": True, "confirm_restore": None}):
            op = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, **options)
            with self.subTest(options=options), self.assertRaises(inventory.Invalid):
                op.run(changes.detach(self.store.snapshot))
        op = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, confirm_stock=True)
        after, _ = op.run(changes.detach(self.store.snapshot))
        self.assertEqual(op.verify(self.store.snapshot, after, support.actual_source(op.plan))["restored"], plan["restored"])

    def test_quantity_neutral_update_retains_metadata_protocol_and_rejects_stock_flag_presence(self):
        self.store.seed()
        plan, _ = self.review()
        self.assertEqual(plan["action"], "accessory_update")
        self.assertNotIn("quantity", plan["current"])
        self.assertNotIn("stock_confirmation_required", plan)
        for value in (True, False, None):
            op = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, confirm_stock=value)
            with self.subTest(value=value), self.assertRaises(inventory.Invalid):
                op.run(self.store.snapshot)

    def test_actual_stock_proof_refuses_wrong_quantity_additional_audit_and_photo_or_survivor_drift(self):
        before = self.store.snapshot
        plan, after = self.review()
        for side in ("before", "after"):
            rows = support.actual_source(plan)
            rows[0][side]["quantity"] = "3"
            with self.subTest(side=side), self.assertRaises(undo.UndoConflict):
                undo.verify_saved(before, after, plan, rows)
        for rows in ([], support.actual_source(plan) * 2):
            with self.subTest(rows=len(rows)), self.assertRaises(undo.UndoConflict):
                undo.verify_saved(before, after, plan, rows)
        for changed in (after.with_image("a-sleeves.jpg", b"unreviewed fixture bytes"),
                        after.with_accessories([{**row, "notes": "Unexpected survivor"} if row["id"] == "b-shared" else row
                                                for row in undo.raw_rows(after)])):
            with self.assertRaises(undo.UndoConflict):
                undo.verify_saved(before, changed, plan, support.actual_source(plan))

    def test_visible_list_and_target_latest_proofs_stale_but_hidden_owner_edits_preserve_scope(self):
        plan, _ = self.review()
        rows = undo.raw_rows(self.store.snapshot)
        self.store.snapshot = self.store.snapshot.with_accessories([
            {**row, "notes": "Private unrelated correction"} if row["id"] == "c-hidden" else row for row in rows])
        self.assertEqual(self.review()[0]["expect"], plan["expect"])
        self.store.snapshot = self.store.snapshot.with_accessories([
            {**row, "notes": "Shared correction"} if row["id"] == "b-shared" else row for row in undo.raw_rows(self.store.snapshot)])
        self.assertNotEqual(self.review()[0]["expect"], plan["expect"])
        self.store.latest += 1
        with self.assertRaises(undo.UndoConflict):
            self.review()
