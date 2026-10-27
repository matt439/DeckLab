"""Explicit crop review and current-photo receipts over synthetic API bytes only."""
import copy
import json
from unittest import mock

from decklab.lib import access, accessory_fetch, inventory
from decklab.lib.api import accessory_undo as api
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import accessory_undo as undo
from decklab.tests import accessory_undo_crop_support as crop
from decklab.tests import accessory_undo_support as support, household_config
from decklab.tests import test_accessory_fetch as pictures
from decklab.tests.test_api import ApiTestCase

DEFAULT = object()


class AccessoryCropUndoApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.store = crop.CropAuditAccessories(support.build_snapshot())
        self.addCleanup(inventory.use(self.store))
        self.enterContext(self.identity("matt"))
        crop.seed_crop(self.store)

    def identity(self, profile):
        return access.using({"profile": profile, "email": profile + "@example.com", "remote": True})

    def view(self):
        return api.accessory_undo_view(support.CHANGE_ID)

    def apply(self, *, expect=DEFAULT, profile="matt", **options):
        if expect is DEFAULT:
            expect = self.view()["expect"]
        return api.apply_accessory_undo(json.dumps({"profile": profile, "id": support.CHANGE_ID,
                                                   "expect": expect, **options}).encode())

    def refused(self, status, function, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        return caught.exception

    def test_full_thirteen_text_crop_preview_and_current_photo_receipt_for_formats_kinds_and_holders(self):
        for ext in crop.CONTENTS:
            for kind in ("sleeves", "deck_box", "playmat"):
                for current, historical in (("0.1,0.1,0.8,0.8", ""), ("", "0,0,1,1")):
                    new, old = crop.seed_crop(self.store, ext=ext, kind=kind, current=current, historical=historical, held=True)
                    before, original = self.store.snapshot, copy.deepcopy(self.store.audit)
                    with self.subTest(ext=ext, kind=kind, historical=historical):
                        preview = self.view()
                        self.assertEqual(set(preview), {"available", "id", "expect", "kind", "action", "label", "current",
                                                       "restored", "fields", "photo", "photo_confirmation_required"})
                        self.assertEqual(preview["action"], "accessory_crop_update")
                        self.assertIs(preview["photo_confirmation_required"], True)
                        self.assertEqual((preview["current"], preview["restored"]), (new, old))
                        self.assertEqual(set(preview["restored"]), undo.RAW)
                        self.assertEqual(preview["photo"], crop.photo(self.store, new["image"]))
                        self.assertEqual(preview["fields"], [{"field": "crop", "before": current, "after": historical}])
                        result = self.apply(expect=preview["expect"], confirm_photo=True)
                        self.assertEqual(set(result), {"saved", "source_id", "expect", "kind", "action", "restored", "sha256", "revision", "summary", "photo"})
                        self.assertEqual((result["action"], result["restored"], result["photo"]), ("accessory_crop_update", old, preview["photo"]))
                        self.assertEqual((self.store.snapshot.accessory_images, self.store.snapshot.decks), (before.accessory_images, before.decks))
                        self.assertEqual(self.store.audit, original)
                        self.assertEqual(len(self.store.writes), 1)
                        actor, _, _, rows = self.store.writes[0]
                        self.assertEqual((actor.id, actor.source, actor.via), ("matt", "web", "tunnel"))
                        self.assertEqual((rows[0]["op"], rows[0]["before"], rows[0]["after"]), ("UPDATE", new, old))

    def test_missing_or_nonboolean_photo_confirmation_and_other_controls_never_write(self):
        preview = self.view()
        values = [{}, {"confirm_photo": False}, {"confirm_photo": None}, {"confirm_photo": 1}, {"confirm_photo": "true"}]
        values.extend({"confirm_photo": True, flag: None} for flag in ("reason", "confirm_restore", "confirm_stock", "confirm_owner", "confirm_kind", "confirm_record"))
        values.extend(({"confirm_photo": True, "crop": ""}, {"confirm_photo": True, "photo": preview["photo"]},
                       {"confirm_photo": True, "action": "accessory_crop_update"}))
        for options in values:
            with self.subTest(options=options):
                self.refused(400, self.apply, expect=preview["expect"], **options)
                self.assertEqual(self.store.writes, [])
        self.apply(expect=preview["expect"], confirm_photo=True)

    def test_photo_flag_presence_refuses_every_old_action_including_presence_inverses(self):
        for action in ("metadata", "stock", "owner", "kind", "record", "INSERT", "DELETE"):
            crop.seed_crop(self.store)
            source = self.store.audit[support.CHANGE_ID][0]
            source["before"] = dict(source["after"])
            if action == "metadata":
                source["before"]["notes"] = "Historical details"
            elif action == "stock":
                source["before"]["quantity"] = "99"
            elif action == "owner":
                source["before"]["owner"] = "shared"
            elif action == "kind":
                source["before"]["kind"] = "playmat"
            elif action == "record":
                source["before"].update(owner="shared", quantity="99")
            else:
                source["op"] = action
                source["before" if action == "INSERT" else "after"] = None
            for value in (True, False, None):
                with self.subTest(action=action, value=value):
                    self.refused(400, self.apply, expect="a" * 64, confirm_photo=value)
                    self.assertEqual(self.store.writes, [])
            self.assertEqual(self.store.photo_calls, [])

    def test_complete_source_and_both_owner_scope_precede_invalid_photo_flag_or_private_photo_reads(self):
        for mode in ("hidden", "owner_move", "mixed", "missing"):
            crop.seed_crop(self.store)
            source = self.store.audit[support.CHANGE_ID][0]
            if mode == "missing":
                self.store.audit.clear()
            elif mode == "mixed":
                self.store.audit[support.CHANGE_ID].append({"table": "accessory_image", "op": "UPDATE"})
            else:
                source["before"].update(owner="user1", name="Private fixture label")
                if mode == "hidden":
                    source["after"]["owner"] = "user1"
            with self.subTest(mode=mode), mock.patch.object(self.store, "accessory_undo_photo", side_effect=AssertionError("No private photo read")):
                error = self.refused(404, self.apply, expect="bad", confirm_photo="invalid")
                self.assertEqual((error.message, error.extra), (api.NO_CHANGE, {}))
            self.assertEqual(self.store.writes, [])

    def test_same_name_current_photo_replacement_invalidates_only_the_old_crop_preview(self):
        preview = self.view()
        crop.replace_photo(self.store, pictures.jpeg(width=301))
        before = self.store.snapshot
        self.refused(409, self.apply, expect=preview["expect"], confirm_photo=True)
        self.assertEqual((self.store.snapshot, self.store.writes), (before, []))
        replacement = self.view()
        self.assertNotEqual(replacement["photo"], preview["photo"])
        self.assertNotEqual(replacement["expect"], preview["expect"])
        result = self.apply(expect=replacement["expect"], confirm_photo=True)
        self.assertEqual(result["photo"], replacement["photo"])

    def test_actual_byte_reader_cannot_hide_missing_or_changed_bytes_behind_unchanged_metadata(self):
        preview = self.view()
        before = self.store.snapshot
        for value in (None, b"", pictures.jpeg(width=301)):
            self.store.photo_bytes[preview["photo"]["name"]] = value
            with self.subTest(content_type=type(value).__name__):
                self.refused(409, self.apply, expect=preview["expect"], confirm_photo=True)
                self.assertEqual((self.store.snapshot, self.store.writes), (before, []))

    def test_mixed_raw_cells_or_noncanonical_crop_are_not_available_as_partial_photo_recovery(self):
        for field, value in (("notes", "Other historical text"), ("quantity", "99"), ("owner", "shared"), ("kind", "playmat"),
                             ("image", "a-sleeves.png"), ("crop", "0.10,0.1,0.8,0.8")):
            crop.seed_crop(self.store)
            self.store.audit[support.CHANGE_ID][0]["before"][field] = value
            with self.subTest(field=field):
                self.assertEqual(self.view(), {"available": False, "id": support.CHANGE_ID, "reason": api.UNSUPPORTED})
                self.refused(400, self.apply, expect="bad", confirm_photo=True)
                self.assertEqual(self.store.writes, [])
                self.assertEqual(self.store.photo_calls, [])

    def test_forged_action_photo_name_version_shape_or_non_crop_diff_projection_fails_closed(self):
        plan = self.store.accessory_undo_review(support.CHANGE_ID, support.OWNERS)
        variants = []
        for replacement in ({"action": "accessory_update"}, {"action": "accessory_stock_update"}, {"photo_confirmation_required": False},
                            {"stock_confirmation_required": True}, {"reason_required": True}, {"fields": []},
                            {"restored": {**plan["restored"], "crop": "0,0,1,1"}},
                            {"photo": {**plan["photo"], "name": "c-hidden.jpg"}}, {"photo": {**plan["photo"], "version": "00000000"}},
                            {"photo": {**plan["photo"], "sha256": "0" * 64}}, {"photo": {**plan["photo"], "size": True}}):
            variants.append({**plan, **replacement})
        mixed = copy.deepcopy(plan)
        mixed["source"]["before"]["notes"] = "Extra historical edit"
        variants.append(mixed)
        for value in variants:
            with self.subTest(plan=value), mock.patch.object(self.store, "accessory_undo_review", return_value=value):
                self.refused(503, self.view)
        self.assertEqual(self.store.writes, [])

    def test_actual_wrong_crop_or_photo_receipt_never_acknowledges_a_save(self):
        plan = self.store.accessory_undo_review(support.CHANGE_ID, support.OWNERS)
        result = {"review": plan, "restored": plan["restored"], "sha256": plan["sha256"], "revision": str(support.ROW_ID + 1), "photo": plan["photo"]}
        replacements = [{**result, "restored": {**plan["restored"], "crop": "0,0,1,1"}},
                        {**result, "photo": {**plan["photo"], "name": "c-hidden.jpg"}},
                        {**result, "photo": {**plan["photo"], "size": plan["photo"]["size"] + 1}},
                        {**result, "photo": {**plan["photo"], "sha256": "0" * 64}},
                        {**result, "photo": {**plan["photo"], "version": "00000000"}}]
        missing = dict(result)
        del missing["photo"]
        replacements.append(missing)
        for replacement in replacements:
            with self.subTest(receipt=replacement), mock.patch.object(self.store, "accessory_undo_apply", return_value=replacement):
                self.refused(503, self.apply, expect=plan["expect"], confirm_photo=True)
        self.assertEqual(self.store.writes, [])

    def test_scoped_shared_writes_private_photo_changes_and_script_named_receipts_follow_existing_permissions(self):
        crop.seed_crop(self.store, owner="shared", held=True)
        with self.identity("user1"):
            preview = self.view()
            crop.replace_photo(self.store, pictures.jpeg(width=303), "c-hidden.jpg")
            self.assertEqual(self.view()["expect"], preview["expect"])
            self.apply(profile="user1", expect=preview["expect"], confirm_photo=True)
        crop.seed_crop(self.store)
        with access.using(None), access.viewing(None), access.answering(True):
            anonymous = self.view()
            self.refused(409, self.apply, profile="matt", expect=anonymous["expect"], confirm_photo=True)
            self.assertEqual(self.store.writes, [])
            named = undo.review(support.CHANGE_ID, support.OWNERS, self.store.snapshot, self.store)[0]
            self.apply(profile="matt", expect=named["expect"], confirm_photo=True)

    def test_latest_target_touch_and_lost_reply_do_not_retry_or_claim_crop_completion(self):
        preview = self.view()
        self.store.latest += 1
        self.refused(409, self.apply, expect=preview["expect"], confirm_photo=True)
        self.assertEqual(self.store.writes, [])
        crop.seed_crop(self.store)
        preview = self.view()
        self.store.fail_after_commit = True
        self.refused(503, self.apply, expect=preview["expect"], confirm_photo=True)
        self.assertEqual(len(self.store.writes), 1)
        self.assertEqual(self.store.snapshot.accessories.rows[0].text("crop"), "")
        self.refused(409, self.apply, expect=preview["expect"], confirm_photo=True)
        self.assertEqual(len(self.store.writes), 1)
