"""Whole recorded corrections plus crop: exact source, current bytes, consent and inverse."""
import copy
import unittest
from unittest import mock

from decklab.lib import accessories, inventory, profiles
from decklab.lib.inventory import accessory_undo as undo, changes, ops_accessories
from decklab.tests import accessory_undo_crop_support as crop
from decklab.tests import accessory_undo_photo_record_support as combined
from decklab.tests import accessory_undo_support as support, household_config
from decklab.tests.test_accessory_fetch import jpeg


class AccessoryPhotoRecordTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(profiles, "read", return_value=copy.deepcopy(household_config.PROFILES)))
        self.store = crop.PhotoInventory()
        self.addCleanup(inventory.use(self.store))
        combined.seed(self.store)

    def review(self, owners=support.OWNERS):
        return undo.review(support.CHANGE_ID, owners, self.store.snapshot, self.store)

    def test_postgresql_fixture_recipe_makes_a_real_combined_crop_source_through_ordinary_edit(self):
        before = self.store.snapshot
        listing = accessories.from_sheet(before.accessories, strict=True)
        after, _ = ops_accessories.edit_accessory(before, id="a-sleeves", row=combined.source_changes(), image="keep",
            sha256=accessories.view_sha256(listing, support.OWNERS), owners=support.OWNERS)
        old = next(row for row in undo.raw_rows(before) if row["id"] == "a-sleeves")
        new = next(row for row in undo.raw_rows(after) if row["id"] == "a-sleeves")
        self.assertEqual({field for field in old if old[field] != new[field]}, {"crop", "notes", "quantity"})
        self.assertEqual(undo.update_action(old, new), "accessory_photo_record_update")

    def test_every_permitted_record_field_can_restore_with_crop_and_full_photo_receipt(self):
        variants = {"owner": "shared", "kind": "playmat", "quantity": "0", "brand": "Earlier brand", "name": "Earlier name",
                    "colour": "blue", "notes": "Earlier <script> note Second line", "link": "https://example.com/earlier",
                    "image_source": "https://example.com/earlier.jpg", "capacity": "40"}
        for field, value in variants.items():
            restored = {field: value, **({"capacity": ""} if field == "kind" else {})}
            new, old = combined.seed(self.store, restored)
            before = self.store.snapshot
            with self.subTest(field=field):
                plan, after = self.review()
                self.assertEqual(plan["action"], "accessory_photo_record_update")
                self.assertEqual((plan["current"], plan["restored"], plan["fields"]), (new, old, combined.fields(new, old)))
                self.assertIs(plan["photo_confirmation_required"], True)
                self.assertIs(plan["record_confirmation_required"], True)
                self.assertEqual(set(plan["current"]), undo.RAW)
                result = undo.verify_saved(before, after, plan, combined.actual(plan), store=self.store)
                self.assertEqual((result["restored"], result["photo"]), (old, plan["photo"]))
                self.assertEqual(after.replace(accessories=before.accessories), before)

    def test_entire_metadata_stock_sharing_classification_and_crop_restore_together(self):
        new, old = combined.seed(self.store, {"kind": "sleeves", "owner": "shared", "quantity": "125", "capacity": "",
            "brand": "Original", "name": "Recorded sleeves", "colour": "black", "notes": "Literal old note",
            "link": "https://example.com/product", "image_source": "https://example.com/source.jpg"})
        before = self.store.snapshot
        plan, expected = self.review()
        operation = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, **combined.options())
        after, summary = operation.run(changes.detach(before))
        self.assertEqual(after, expected)
        self.assertEqual(operation.verify(before, after, combined.actual(plan))["restored"], old)
        self.assertIn("current photo", summary.text)
        self.assertEqual(self.store.snapshot, before)
        self.assertEqual((new["id"], new["image"]), (old["id"], old["image"]))

    def test_both_explicit_true_confirmations_are_required_and_foreign_flags_refuse(self):
        plan, _ = self.review()
        for options in ({}, {"confirm_photo": True}, {"confirm_record": True}, {"confirm_photo": False, "confirm_record": True},
                        {"confirm_photo": True, "confirm_record": 1}, {**combined.options(), "confirm_stock": True},
                        {**combined.options(), "confirm_owner": True}, {**combined.options(), "confirm_kind": True},
                        {**combined.options(), "confirm_restore": True}, {**combined.options(), "reason": "No removal"}):
            with self.subTest(options=options), self.assertRaises(inventory.Invalid):
                undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, **options).run(self.store.snapshot)
        self.assertEqual(self.store.writes, [])

    def test_held_crop_text_and_count_are_allowed_but_owner_or_kind_corrections_require_unused(self):
        for restored in ({"notes": "Earlier"}, {"quantity": "1", "capacity": "40"}):
            combined.seed(self.store, restored, held=True)
            self.assertEqual(self.review()[0]["action"], "accessory_photo_record_update")
        for restored in ({"owner": "shared"}, {"kind": "playmat", "capacity": ""}):
            combined.seed(self.store, restored, held=True)
            with self.subTest(restored=restored), self.assertRaises((inventory.Invalid, inventory.Conflict)):
                self.review()

    def test_private_mixed_later_identity_or_image_sources_never_get_a_photo_review(self):
        for mode in ("owner", "mixed", "later", "id", "image"):
            combined.seed(self.store)
            row = self.store.audit[support.CHANGE_ID][0]
            if mode == "owner":
                row["before"]["owner"] = row["after"]["owner"] = "user1"
            elif mode == "mixed":
                self.store.audit[support.CHANGE_ID].append({"table": "accessory", "op": "DELETE"})
            elif mode == "later":
                self.store.latest += 1
            else:
                row["before"][mode] = "other-id" if mode == "id" else "a-sleeves.png"
            with self.subTest(mode=mode), self.assertRaises((inventory.Invalid, inventory.Conflict)):
                self.review()
            self.assertEqual(self.store.photo_calls, [])

    def test_photo_or_record_drift_stales_review_and_forged_inverse_rolls_back(self):
        plan, after = self.review()
        before = self.store.snapshot
        crop.replace_photo(self.store, jpeg(width=301))
        self.assertNotEqual(self.review()[0]["expect"], plan["expect"])
        with self.assertRaises(undo.UndoConflict):
            undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, **combined.options()).run(self.store.snapshot)
        combined.seed(self.store)
        plan, after = self.review()
        for field, value in (("crop", "0,0,1,1"), ("notes", "Unexpected"), ("quantity", "999"), ("image", "wrong.jpg")):
            actual = combined.actual(plan)
            actual[0]["after"][field] = value
            with self.subTest(field=field), self.assertRaises(undo.UndoConflict):
                undo.verify_saved(before, after, plan, actual, store=self.store)
        crop.replace_photo(self.store, jpeg(width=302), update_meta=False)
        with self.assertRaises(undo.UndoConflict):
            undo.verify_saved(before, after, plan, combined.actual(plan), store=self.store)
