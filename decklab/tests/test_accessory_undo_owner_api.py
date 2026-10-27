"""Confirmed shared/home accessory ownership recovery with synthetic API state."""
import copy
from dataclasses import replace
import json
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import accessory_undo as api
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import accessory_undo as undo
from decklab.tests import accessory_undo_support as support, household_config
from decklab.tests import test_accessory_undo_api as base
from decklab.tests.test_api import ApiTestCase

DEFAULT = object()


class AccessoryOwnerUndoApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.store = base.AuditAccessories(support.build_snapshot())
        self.addCleanup(inventory.use(self.store))
        self.enterContext(self.identity("matt"))
        self.seed()

    def identity(self, profile):
        return access.using({"profile": profile, "email": profile + "@example.com", "remote": True})

    def seed(self, current="shared", historical="matt", *, kind="sleeves", quantity="100", mixed=False):
        new = support.row(owner=current, kind=kind, quantity=quantity, capacity="100" if kind == "deck_box" else "")
        old = {**new, "owner": historical}
        if mixed:
            old.update(notes="Historical <script>literal</script> note", link="https://example.com/former")
        snapshot = support.build_snapshot().with_accessories([new])
        deck = snapshot.deck("casual/fixture")
        self.store.snapshot = snapshot.with_deck(replace(deck, text=deck.text.replace("- **Sleeves:** a-sleeves\n", "")))
        self.store.audit = {support.CHANGE_ID: [{"id": support.ROW_ID, "table": "accessory", "op": "UPDATE",
                            "key": {"id": new["id"]}, "before": old, "after": new}]}
        self.store.latest = support.ROW_ID
        self.store.calls.clear()
        self.store.writes.clear()
        self.store.fail_after_commit = False
        return new, old

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

    def test_both_owner_directions_and_all_kinds_have_exact_eleven_text_review_and_actual_receipt(self):
        for profile in ("matt", "user1"):
            for current, historical in (("shared", profile), (profile, "shared")):
                for kind in ("sleeves", "deck_box", "playmat"):
                    for quantity in ("0", "100"):
                        new, old = self.seed(current, historical, kind=kind, quantity=quantity)
                        before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
                        with self.subTest(profile=profile, current=current, kind=kind, quantity=quantity), self.identity(profile):
                            preview = self.view()
                            self.assertEqual(set(preview), {"available", "id", "expect", "kind", "action", "label", "current",
                                                           "restored", "fields", "owner_confirmation_required"})
                            self.assertEqual(preview["action"], "accessory_owner_update")
                            self.assertIs(preview["owner_confirmation_required"], True)
                            self.assertEqual(preview["current"], undo.stock_meta(new))
                            self.assertEqual(preview["restored"], undo.stock_meta(old))
                            self.assertEqual(len(preview["restored"]), 11)
                            self.assertEqual(preview["fields"], [{"field": "owner", "before": current, "after": historical}])
                            result = self.apply(profile=profile, expect=preview["expect"], confirm_owner=True)
                        self.assertEqual(set(result), {"saved", "source_id", "expect", "kind", "action", "restored", "sha256", "revision", "summary"})
                        self.assertEqual((result["action"], result["restored"]), ("accessory_owner_update", preview["restored"]))
                        self.assertEqual(self.store.snapshot.accessory_images, before.accessory_images)
                        self.assertEqual(self.store.snapshot.decks, before.decks)
                        self.assertEqual(self.store.audit, audit)
                        self.assertEqual(len(self.store.writes), 1)
                        actor, _, _, rows = self.store.writes[0]
                        self.assertEqual((actor.id, actor.source, actor.via), (profile, "web", "tunnel"))
                        self.assertEqual((rows[0]["op"], rows[0]["before"], rows[0]["after"]), ("UPDATE", new, old))

    def test_missing_false_null_numeric_or_text_owner_consent_and_other_controls_never_write(self):
        preview = self.view()
        for options in ({}, {"confirm_owner": False}, {"confirm_owner": None}, {"confirm_owner": 1},
                        {"confirm_owner": "true"}, {"confirm_owner": True, "reason": None},
                        {"confirm_owner": True, "confirm_restore": None}, {"confirm_owner": True, "confirm_stock": None},
                        {"confirm_owner": True, "owner": "shared"}, {"confirm_owner": True, "action": "accessory_owner_update"}):
            with self.subTest(options=options):
                self.refused(400, self.apply, expect=preview["expect"], **options)
                self.assertEqual(self.store.writes, [])
        self.apply(expect=preview["expect"], confirm_owner=True)

    def test_owner_flag_presence_cannot_be_reused_for_metadata_stock_addition_or_removal(self):
        for action in ("metadata", "stock", "INSERT", "DELETE"):
            self.seed()
            source = self.store.audit[support.CHANGE_ID][0]
            source["before"]["owner"] = source["after"]["owner"]
            if action == "metadata":
                source["before"]["notes"] = "Old metadata"
            elif action == "stock":
                source["before"]["quantity"] = "99"
            else:
                source["op"] = action
                source["before" if action == "INSERT" else "after"] = None
            for value in (True, False, None):
                with self.subTest(action=action, value=value):
                    self.refused(400, self.apply, expect="a" * 64, confirm_owner=value)
                    self.assertEqual(self.store.writes, [])

    def test_incomplete_or_hidden_owner_source_precedes_invalid_flag_and_private_labels(self):
        for mode in ("hidden", "owner_move", "mixed", "missing"):
            self.seed()
            source = self.store.audit[support.CHANGE_ID][0]
            if mode == "missing":
                self.store.audit.clear()
            elif mode == "mixed":
                self.store.audit[support.CHANGE_ID].append({"table": "accessory_image", "op": "UPDATE"})
            else:
                source["before"].update(owner="user1", name="Private fixture label")
                if mode == "hidden":
                    source["after"]["owner"] = "user1"
            with self.subTest(mode=mode), mock.patch.object(undo, "raw_row", side_effect=AssertionError("No private row validation")):
                error = self.refused(404, self.apply, expect="bad", confirm_owner="invalid")
                self.assertEqual((error.message, error.extra), (api.NO_CHANGE, {}))
            self.assertEqual(self.store.writes, [])

    def test_script_preview_does_not_admit_profile_to_profile_nonhome_or_orphan_pairs(self):
        for current, historical in (("matt", "user1"), ("shared", "user2"), ("shared", "orphan")):
            self.seed(current, historical)
            with self.subTest(current=current, historical=historical), access.using(None), access.viewing(None), access.answering(True):
                self.assertEqual(self.view(), {"available": False, "id": support.CHANGE_ID, "reason": api.UNSUPPORTED})
            self.assertEqual(self.store.writes, [])
        self.seed("shared", "matt")
        with access.using(None), access.viewing(None), access.answering(True):
            anonymous = self.view()
            self.assertEqual(anonymous["action"], "accessory_owner_update")
            self.refused(409, self.apply, profile="matt", expect=anonymous["expect"], confirm_owner=True)
            self.assertEqual(self.store.writes, [])
            named = undo.review(support.CHANGE_ID, support.OWNERS, self.store.snapshot, self.store)[0]
            result = self.apply(profile="matt", expect=named["expect"], confirm_owner=True)
        self.assertEqual(result["restored"]["owner"], "matt")

    def test_owner_quantity_or_photo_identity_mixtures_cannot_be_partly_restored(self):
        for field, value in (("quantity", "99"), ("kind", "playmat"), ("id", "different-id"),
                             ("image", "a-sleeves.png"), ("crop", "")):
            self.seed()
            self.store.audit[support.CHANGE_ID][0]["before"][field] = value
            with self.subTest(field=field):
                self.assertEqual(self.view(), {"available": False, "id": support.CHANGE_ID, "reason": api.UNSUPPORTED})
                self.refused(400, self.apply, expect="bad", confirm_owner=True)
                self.assertEqual(self.store.writes, [])

    def test_mixed_literal_details_and_later_target_reference_recheck_keep_normal_kit(self):
        _, old = self.seed(mixed=True)
        preview = self.view()
        self.assertEqual([item["field"] for item in preview["fields"]], ["owner", "notes", "link"])
        deck = self.store.snapshot.deck("casual/fixture")
        self.store.snapshot = self.store.snapshot.with_deck(replace(deck, text=deck.text.replace("- **Built version:** target\n",
            "- **Built version:** target\n- **Deck box:** a-sleeves\n")))
        self.refused(409, self.apply, expect=preview["expect"], confirm_owner=True)
        self.assertEqual(self.store.writes, [])
        self.seed(mixed=True)
        result = self.apply(confirm_owner=True)
        self.assertEqual(result["restored"], undo.stock_meta(old))
        self.assertEqual(result["restored"]["notes"], "Historical <script>literal</script> note")

    def test_forged_owner_action_flags_quantity_or_pair_projection_fail_closed(self):
        plan = self.store.accessory_undo_review(support.CHANGE_ID, support.OWNERS)
        variants = []
        for replacement in ({"action": "accessory_update"}, {"action": "accessory_stock_update"},
                            {"owner_confirmation_required": False}, {"stock_confirmation_required": True},
                            {"reason_required": True}, {"confirmation_required": True},
                            {"current": {**plan["current"], "quantity": "0"}},
                            {"restored": {**plan["restored"], "quantity": 100}}, {"fields": plan["fields"] * 2}):
            variants.append({**plan, **replacement})
        neutral = copy.deepcopy(plan)
        neutral["source"]["before"]["owner"] = neutral["source"]["after"]["owner"]
        variants.append(neutral)
        invalid_pair = copy.deepcopy(plan)
        invalid_pair["source"]["before"]["owner"] = "orphan"
        variants.append(invalid_pair)
        for value in variants:
            with self.subTest(plan=value), mock.patch.object(self.store, "accessory_undo_review", return_value=value):
                self.refused(503, self.view)
        self.assertEqual(self.store.writes, [])

    def test_actual_owner_or_quantity_mismatch_extra_fields_and_lost_reply_never_acknowledge_or_retry(self):
        plan = self.store.accessory_undo_review(support.CHANGE_ID, support.OWNERS)
        result = {"review": plan, "restored": plan["restored"], "sha256": plan["sha256"], "revision": str(support.ROW_ID + 1)}
        for replacement in ({**result, "restored": {**plan["restored"], "owner": "shared"}},
                            {**result, "restored": {**plan["restored"], "quantity": "99"}},
                            {**result, "restored": {**plan["restored"], "image": ""}},
                            {**result, "revision": str(support.ROW_ID)}, {**result, "sha256": "0" * 64}):
            with self.subTest(receipt=replacement), mock.patch.object(self.store, "accessory_undo_apply", return_value=replacement):
                self.refused(503, self.apply, expect=plan["expect"], confirm_owner=True)
        self.assertEqual(self.store.writes, [])
        self.store.fail_after_commit = True
        self.refused(503, self.apply, expect=plan["expect"], confirm_owner=True)
        self.assertEqual(len(self.store.writes), 1)
        self.assertEqual(self.store.snapshot.accessories.rows[0].as_dict()["owner"], "matt")
        self.refused(409, self.apply, expect=plan["expect"], confirm_owner=True)
        self.assertEqual(len(self.store.writes), 1)
