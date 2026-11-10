"""Distinct dual-consent combined accessory correction projection and save receipts."""
import copy
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import accessory_undo as api
from decklab.lib.inventory import accessory_undo as undo
from decklab.tests import accessory_undo_crop_support as crop
from decklab.tests import accessory_undo_photo_record_support as combined
from decklab.tests import accessory_undo_support as support, household_config
from decklab.tests.test_accessory_fetch import jpeg
from decklab.tests import test_accessory_undo_crop_api as crop_api
from decklab.tests.test_api import ApiTestCase


class AccessoryPhotoRecordApiTests(ApiTestCase):
    identity = crop_api.AccessoryCropUndoApiTests.identity
    view, apply, refused = crop_api.AccessoryCropUndoApiTests.view, crop_api.AccessoryCropUndoApiTests.apply, crop_api.AccessoryCropUndoApiTests.refused

    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.store = crop.CropAuditAccessories(support.build_snapshot())
        self.addCleanup(inventory.use(self.store))
        self.enterContext(self.identity("matt"))
        combined.seed(self.store)

    def test_full_raw_record_and_current_photo_require_two_distinct_flags(self):
        new, old = combined.seed(self.store, {"owner": "shared", "kind": "playmat", "quantity": "0", "capacity": "",
                                            "notes": "Historical <img> literal", "image_source": "https://example.com/earlier.jpg"})
        result = self.view()
        self.assertEqual(result["action"], "accessory_photo_record_update")
        self.assertEqual((result["current"], result["restored"], result["fields"]), (new, old, combined.fields(new, old)))
        self.assertEqual({key: result[key] for key in ("record_confirmation_required", "photo_confirmation_required")},
                         {"record_confirmation_required": True, "photo_confirmation_required": True})
        self.assertEqual(set(result), {"available", "id", "expect", "kind", "action", "label", "current", "restored", "fields", "photo", "record_confirmation_required", "photo_confirmation_required"})

    def test_both_confirmations_save_one_exact_audited_inverse_and_preserve_current_photo(self):
        before = self.store.snapshot
        result = self.apply(**combined.options())
        self.assertIs(result["saved"], True)
        self.assertEqual(len(self.store.writes), 1)
        self.assertEqual(result["action"], "accessory_photo_record_update")
        self.assertEqual(result["restored"], self.store.audit[support.CHANGE_ID][0]["before"])
        self.assertEqual(self.store.snapshot.accessory_images, before.accessory_images)
        actual = self.store.writes[0][-1]
        self.assertEqual((len(actual), actual[0]["op"], actual[0]["before"], actual[0]["after"]),
                         (1, "UPDATE", self.store.audit[support.CHANGE_ID][0]["after"], result["restored"]))

    def test_missing_false_nonboolean_or_unrelated_consent_never_writes(self):
        for options in ({}, {"confirm_photo": True}, {"confirm_record": True}, {"confirm_photo": 1, "confirm_record": True},
                        {"confirm_photo": True, "confirm_record": False}, {**combined.options(), "confirm_stock": True},
                        {**combined.options(), "reason": "No removal"}):
            combined.seed(self.store)
            before = self.store.snapshot
            with self.subTest(options=options):
                self.refused(400, self.apply, **options)
                self.assertEqual((self.store.snapshot, self.store.writes), (before, []))

    def test_source_projection_cannot_drop_crop_record_flag_or_other_changes(self):
        plan = self.store.accessory_undo_review(support.CHANGE_ID, support.OWNERS)
        variants = [{**plan, "action": "accessory_crop_update"}, {**plan, "action": "accessory_record_update"},
                    {**plan, "record_confirmation_required": False}, {**plan, "photo_confirmation_required": False},
                    {**plan, "fields": plan["fields"][:-1]}, {**plan, "stock_confirmation_required": True},
                    {**plan, "current": undo.stock_meta(plan["current"])},
                    {**plan, "photo": {**plan["photo"], "sha256": "0" * 64}}]
        # A changed hash is valid only with its derived image-version token; a forged envelope refuses.
        variants[-1]["photo"]["version"] = "00000000"
        for value in variants:
            with self.subTest(keys=list(value)), mock.patch.object(self.store, "accessory_undo_review", return_value=value):
                self.refused(503, self.view)

    def test_hidden_complete_source_is_refused_before_photo_or_labels(self):
        for profile in ("user1", "user2"):
            with self.identity(profile), mock.patch.object(self.store, "accessory_undo_photo", side_effect=AssertionError("No hidden photo read")):
                self.refused(404, self.view)
                self.refused(404, self.apply, expect="bad", profile=profile, **combined.options())
        self.assertEqual(self.store.writes, [])

    def test_photo_drift_and_later_row_touch_refuse_then_unknown_save_is_not_retried(self):
        preview = self.view()
        crop.replace_photo(self.store, jpeg(width=301))
        self.refused(409, self.apply, expect=preview["expect"], **combined.options())
        combined.seed(self.store)
        preview = self.view()
        self.store.latest += 1
        self.refused(409, self.apply, expect=preview["expect"], **combined.options())
        combined.seed(self.store)
        self.store.fail_after_commit = True
        self.refused(503, self.apply, **combined.options())
        self.assertEqual(len(self.store.writes), 1)

    def test_wrong_actual_row_or_photo_receipt_is_unconfirmed_after_save(self):
        for mode in ("crop", "notes", "quantity", "photo", "missing_photo", "extra"):
            combined.seed(self.store)
            original = self.store.accessory_undo_apply
            def changed(*args):
                result = copy.deepcopy(original(*args))
                if mode in ("crop", "notes", "quantity"):
                    result["restored"][mode] = "unexpected"
                elif mode == "photo":
                    result["photo"]["sha256"] = "0" * 64
                elif mode == "missing_photo":
                    result.pop("photo")
                else:
                    result["removed_id"] = "a-sleeves"
                return result
            with self.subTest(mode=mode), mock.patch.object(self.store, "accessory_undo_apply", side_effect=changed):
                self.refused(503, self.apply, **combined.options())
            self.assertEqual(len(self.store.writes), 1)
