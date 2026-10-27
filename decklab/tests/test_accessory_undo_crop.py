"""Crop-only restoration proves current photo bytes without recovering an old photo."""
import copy
from dataclasses import replace
import unittest
from unittest import mock

from decklab.lib import accessory_fetch, inventory, profiles
from decklab.lib.inventory import accessory_undo as undo, changes
from decklab.tests import accessory_undo_crop_support as crop
from decklab.tests import accessory_undo_support as support, household_config
from decklab.tests import test_accessory_fetch as pictures


class AccessoryCropUndoTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(profiles, "read", return_value=copy.deepcopy(household_config.PROFILES)))
        self.store = crop.PhotoInventory()
        self.addCleanup(inventory.use(self.store))
        crop.seed_crop(self.store)

    def source(self):
        return self.store.audit[support.CHANGE_ID][0]

    def review(self, owners=support.OWNERS):
        return undo.review(support.CHANGE_ID, owners, self.store.snapshot, self.store)

    def test_all_formats_kinds_blank_or_rectangular_crop_and_held_photos_have_exact_full_row_review(self):
        for ext in crop.CONTENTS:
            for kind in ("sleeves", "deck_box", "playmat"):
                for current, historical in (("0.1,0.1,0.8,0.8", ""), ("", "0,0,1,1")):
                    new, old = crop.seed_crop(self.store, ext=ext, kind=kind, current=current, historical=historical, held=True)
                    before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
                    with self.subTest(ext=ext, kind=kind, historical=historical), \
                            mock.patch.object(accessory_fetch, "fetch", side_effect=AssertionError("No URL fetch")), \
                            mock.patch.object(inventory, "image", side_effect=AssertionError("Use admitted byte reader")):
                        plan, after = self.review()
                        self.assertEqual(plan["action"], "accessory_crop_update")
                        self.assertIs(plan["photo_confirmation_required"], True)
                        self.assertEqual((plan["current"], plan["restored"]), (new, old))
                        self.assertEqual(set(plan["current"]), undo.RAW)
                        self.assertEqual(plan["fields"], [{"field": "crop", "before": current, "after": historical}])
                        self.assertEqual(plan["photo"], crop.photo(self.store, new["image"]))
                        self.assertEqual(set(plan["photo"]), {"name", "size", "sha256", "version"})
                        receipt = undo.verify_saved(before, after, plan, support.actual_source(plan), store=self.store)
                        self.assertEqual((receipt["restored"], receipt["photo"]), (old, plan["photo"]))
                        self.assertTrue(self.store.photo_calls)
                        self.assertTrue(all(call == (new["image"], plan["photo"]["sha256"], plan["photo"]["size"])
                                            for call in self.store.photo_calls))
                        self.assertEqual(after.accessory_images, before.accessory_images)
                        self.assertEqual(after.decks, before.decks)
                        self.assertEqual(after.replace(accessories=before.accessories), before)
                        self.assertEqual((self.store.snapshot, self.store.audit), (before, audit))

    def test_noncanonical_invalid_or_missing_picture_crop_sources_are_never_normalized(self):
        for side in ("before", "after"):
            for value in (None, True, "0.10,0.1,0.8,0.8", "0.1, 0.1,0.8,0.8", "0,0,0,1", "0.9,0,0.2,1", "??"):
                crop.seed_crop(self.store)
                self.source()[side]["crop"] = value
                with self.subTest(side=side, crop=value), self.assertRaises(undo.UndoUnsupported):
                    self.review()
                self.assertEqual(self.store.photo_calls, [])
        crop.seed_crop(self.store)
        self.source()["before"]["image"] = self.source()["after"]["image"] = ""
        with self.assertRaises(undo.UndoUnsupported):
            self.review()
        self.assertEqual(self.store.photo_calls, [])

    def test_crop_with_any_other_raw_cell_change_refuses_without_a_photo_read(self):
        variants = {"id": "different-id", "kind": "playmat", "owner": "shared", "brand": "Earlier brand", "name": "Earlier name",
                    "colour": "blue", "notes": "Earlier note", "link": "https://example.com/former", "image_source": "https://example.com/former.jpg",
                    "quantity": "99", "capacity": "40", "image": "a-sleeves.png"}
        self.assertEqual(set(variants), undo.RAW - {"crop"})
        for field, value in variants.items():
            crop.seed_crop(self.store, kind="deck_box" if field == "capacity" else "sleeves")
            self.source()["before"][field] = value
            with self.subTest(field=field), self.assertRaises((undo.UndoMissing, undo.UndoUnsupported)):
                self.review()
            self.assertEqual(self.store.photo_calls, [])

    def test_complete_owner_current_and_latest_proofs_precede_any_actual_photo_read(self):
        for mode in ("hidden", "owner_move", "mixed", "missing", "later", "current"):
            crop.seed_crop(self.store)
            source = self.source()
            if mode == "missing":
                self.store.audit.clear()
            elif mode == "mixed":
                self.store.audit[support.CHANGE_ID].append({"table": "accessory_image", "op": "UPDATE"})
            elif mode == "later":
                self.store.latest += 1
            elif mode == "current":
                self.store.snapshot = self.store.snapshot.with_accessories([
                    {**row, "crop": "0,0,1,1"} if row["id"] == "a-sleeves" else row for row in undo.raw_rows(self.store.snapshot)])
            else:
                source["before"]["owner"] = "user1"
                if mode == "hidden":
                    source["after"]["owner"] = "user1"
            with self.subTest(mode=mode), mock.patch.object(self.store, "accessory_undo_photo", side_effect=AssertionError("No photo read")), \
                    self.assertRaises((undo.UndoMissing, undo.UndoUnsupported, undo.UndoConflict)):
                self.review()

    def test_photo_envelope_requires_exact_typed_full_identity_and_epoch_derived_version(self):
        value = crop.photo(self.store)
        self.assertEqual(undo.photo_envelope(value), value)
        self.assertIsNot(undo.photo_envelope(value), value)
        for item in (None, {}, {**value, "extra": "x"}, {**value, "name": "../a.jpg"}, {**value, "size": True},
                     {**value, "size": 0}, {**value, "size": 4 * 1024 * 1024 + 1}, {**value, "sha256": value["sha256"].upper()},
                     {**value, "sha256": value["sha256"][:8]}, {**value, "version": "00000000"}, {**value, "version": 1}):
            with self.subTest(envelope=item), self.assertRaises(undo.UndoUnsupported):
                undo.photo_envelope(item)

    def test_current_image_metadata_shape_and_content_excluded_from_equality_are_checked(self):
        original = self.store.snapshot
        name = self.source()["after"]["image"]
        meta = original.image_meta(name)
        for bad in (None, {"name": name}, replace(meta, name="different.jpg"), replace(meta, size=True),
                    replace(meta, size=0), replace(meta, sha256="bad"), replace(meta, content=b"x" * meta.size)):
            self.store.snapshot = original.replace(accessory_images={**original.accessory_images, name: bad})
            with self.subTest(meta=bad), self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)):
                self.review()
        equal_but_bad = replace(meta, content=b"x" * meta.size)
        self.assertEqual(equal_but_bad, meta)

    def test_actual_missing_wrong_length_wrong_hash_or_untyped_bytes_are_not_trusted(self):
        name = self.source()["after"]["image"]
        valid = self.store.photo_bytes[name]
        for content in (None, b"", valid[:-1], b"x" * len(valid), "not bytes", {"content": valid}):
            self.store.photo_bytes[name] = content
            with self.subTest(content_type=type(content).__name__), self.assertRaises((undo.UndoConflict, undo.UndoUnsupported)):
                self.review()
        self.store.photo_bytes[name] = valid
        self.assertEqual(self.review()[0]["photo"], crop.photo(self.store))

    def test_matching_metadata_does_not_admit_invalid_formats_dimensions_or_wrong_extension(self):
        for content in (b"not a picture", pictures.png(), pictures.jpeg(width=1), pictures.jpeg(width=6001),
                        b"x" * (4 * 1024 * 1024 + 1)):
            crop.seed_crop(self.store)
            crop.replace_photo(self.store, content)
            with self.subTest(content_size=len(content)), self.assertRaises(undo.UndoUnsupported):
                self.review()

    def test_current_same_name_photo_replacement_stales_preview_and_byte_aba_requires_no_false_history_claim(self):
        plan, _ = self.review()
        name = plan["photo"]["name"]
        content = self.store.photo_bytes[name]
        crop.replace_photo(self.store, pictures.jpeg(width=301), name)
        self.assertNotEqual(self.review()[0]["expect"], plan["expect"])
        operation = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, confirm_photo=True)
        with self.assertRaises(undo.UndoConflict):
            operation.run(self.store.snapshot)
        crop.replace_photo(self.store, content, name)
        self.assertEqual(self.review()[0]["expect"], plan["expect"])
        after, _ = operation.run(changes.detach(self.store.snapshot))
        self.assertEqual(operation.verify(self.store.snapshot, after, support.actual_source(operation.plan))["photo"], plan["photo"])

    def test_actual_reader_drift_and_wrong_crop_or_photo_receipt_fail_before_commit(self):
        plan, after = self.review()
        before = self.store.snapshot
        original = self.store.photo_bytes[plan["photo"]["name"]]
        crop.replace_photo(self.store, pictures.jpeg(width=301), update_meta=False)
        self.assertEqual(self.store.snapshot, before)
        with self.assertRaises(undo.UndoConflict):
            undo.verify_saved(before, after, plan, support.actual_source(plan), store=self.store)
        crop.replace_photo(self.store, original, update_meta=False)
        rows = support.actual_source(plan)
        rows[0]["after"]["crop"] = "0,0,1,1"
        with self.assertRaises(undo.UndoConflict):
            undo.verify_saved(before, after, plan, rows, store=self.store)
        tampered = {**plan, "photo": {**plan["photo"], "sha256": "0" * 64}}
        with self.assertRaises((undo.UndoConflict, undo.UndoUnsupported)):
            undo.verify_saved(before, after, tampered, support.actual_source(plan), store=self.store)

    def test_photo_confirmation_is_exact_and_every_other_action_control_presence_refuses(self):
        plan, _ = self.review()
        options = [{}, {"confirm_photo": False}, {"confirm_photo": None}, {"confirm_photo": 1}, {"confirm_photo": "true"}]
        options.extend({"confirm_photo": True, flag: None} for flag in ("reason", "confirm_restore", "confirm_stock", "confirm_owner", "confirm_kind", "confirm_record"))
        for values in options:
            operation = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, **values)
            with self.subTest(options=values), self.assertRaises(inventory.Invalid):
                operation.run(self.store.snapshot)
        operation = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plan["expect"], store=self.store, confirm_photo=True)
        after, _ = operation.run(changes.detach(self.store.snapshot))
        self.assertEqual(operation.verify(self.store.snapshot, after, support.actual_source(operation.plan))["restored"], plan["restored"])

    def test_old_actions_read_no_photo_and_private_unrelated_photo_changes_do_not_stale_crop(self):
        plan, _ = self.review()
        crop.replace_photo(self.store, pictures.jpeg(width=303), "c-hidden.jpg")
        self.assertEqual(self.review()[0]["expect"], plan["expect"])
        self.source()["before"] = {**self.source()["after"], "notes": "Historical details"}
        with mock.patch.object(self.store, "accessory_undo_photo", side_effect=AssertionError("No old-action photo read")):
            plain, after = self.review()
            self.assertEqual(plain["action"], "accessory_update")
            self.assertNotIn("photo", plain)
            self.assertNotIn("photo", undo.verify_saved(self.store.snapshot, after, plain, support.actual_source(plain)))
        for value in (True, False, None):
            operation = undo.MetadataRestore(support.CHANGE_ID, support.OWNERS, plain["expect"], store=self.store, confirm_photo=value)
            with self.subTest(value=value), self.assertRaises(inventory.Invalid):
                operation.run(self.store.snapshot)
