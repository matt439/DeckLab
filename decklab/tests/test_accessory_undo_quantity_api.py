"""Stock-confirmed accessory count Undo API, with synthetic state only."""
import copy
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


class AccessoryQuantityUndoApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.store = base.AuditAccessories(support.build_snapshot())
        self.addCleanup(inventory.use(self.store))
        self.enterContext(self.identity("matt"))
        self.seed()

    def identity(self, profile):
        return access.using({"profile": profile, "email": profile + "@example.com", "remote": True})

    def seed(self, current="100", historical="40", *, kind="sleeves", owner="matt", mixed=False):
        new = support.row(kind=kind, owner=owner, quantity=current, capacity="100" if kind == "deck_box" else "")
        old = {**new, "quantity": historical}
        if mixed:
            old.update(notes="Historical <script>literal</script> note", link="https://example.com/old")
        self.store.snapshot = support.build_snapshot().with_accessories([new])
        self.store.audit = {support.CHANGE_ID: [{"id": support.ROW_ID, "table": "accessory", "op": "UPDATE",
                            "key": {"id": new["id"]}, "before": old, "after": new}]}
        self.store.latest = support.ROW_ID
        self.store.writes.clear()
        self.store.calls.clear()
        return new, old

    def view(self):
        return api.accessory_undo_view(support.CHANGE_ID)

    def apply(self, *, expect=DEFAULT, profile="matt", **options):
        if expect is DEFAULT:
            expect = self.view()["expect"]
        body = {"profile": profile, "id": support.CHANGE_ID, "expect": expect, **options}
        return api.apply_accessory_undo(json.dumps(body).encode())

    def refused(self, status, function, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        return caught.exception

    def test_exact_eleven_text_stock_preview_and_receipt_cover_all_kinds_including_zero(self):
        for kind in ("sleeves", "deck_box", "playmat"):
            for current, historical in (("100", "40"), ("1", "9999"), ("2", "0"), ("0", "1")):
                new, old = self.seed(current, historical, kind=kind)
                original = copy.deepcopy(self.store.audit)
                before = self.store.snapshot
                with self.subTest(kind=kind, historical=historical):
                    preview = self.view()
                    self.assertEqual(set(preview), {"available", "id", "expect", "kind", "action", "label", "current",
                                                   "restored", "fields", "stock_confirmation_required"})
                    self.assertEqual(preview["action"], "accessory_stock_update")
                    self.assertIs(preview["stock_confirmation_required"], True)
                    self.assertEqual(preview["current"], undo.stock_meta(new))
                    self.assertEqual(preview["restored"], undo.stock_meta(old))
                    self.assertEqual(len(preview["restored"]), 11)
                    self.assertEqual(preview["fields"], [{"field": "quantity", "before": current, "after": historical}])
                    receipt = self.apply(expect=preview["expect"], confirm_stock=True)
                    self.assertEqual(set(receipt), {"saved", "source_id", "expect", "kind", "action", "restored", "sha256", "revision", "summary"})
                    self.assertEqual((receipt["action"], receipt["restored"]), ("accessory_stock_update", preview["restored"]))
                    self.assertEqual(receipt["revision"], str(support.ROW_ID + 1))
                    self.assertEqual(self.store.audit, original)
                    self.assertEqual(self.store.snapshot.accessory_images, before.accessory_images)
                    self.assertEqual(self.store.snapshot.decks, before.decks)
                    self.assertEqual(len(self.store.writes), 1)
                    actor, _, _, rows = self.store.writes[0]
                    self.assertEqual((actor.id, actor.source, actor.via), ("matt", "web", "tunnel"))
                    self.assertEqual((rows[0]["op"], rows[0]["before"], rows[0]["after"]), ("UPDATE", new, old))

    def test_missing_false_null_numeric_or_text_consent_and_unrelated_controls_never_write(self):
        preview = self.view()
        for options in ({}, {"confirm_stock": False}, {"confirm_stock": None}, {"confirm_stock": 1},
                        {"confirm_stock": "true"}, {"confirm_stock": True, "reason": None},
                        {"confirm_stock": True, "confirm_restore": True}, {"confirm_stock": True, "confirm_restore": None},
                        {"confirm_stock": True, "quantity": "1"}, {"confirm_stock": True, "action": "accessory_stock_update"}):
            with self.subTest(options=options):
                self.refused(400, self.apply, expect=preview["expect"], **options)
                self.assertEqual(self.store.writes, [])
        self.apply(expect=preview["expect"], confirm_stock=True)

    def test_stock_flag_presence_is_rejected_for_metadata_and_presence_inverses(self):
        for action in ("UPDATE", "INSERT", "DELETE"):
            self.seed()
            source = self.store.audit[support.CHANGE_ID][0]
            if action == "UPDATE":
                source["before"]["quantity"] = source["after"]["quantity"]
                source["before"]["notes"] = "Historical metadata"
            else:
                source["op"] = action
                source["before" if action == "INSERT" else "after"] = None
            for flag in (True, False, None):
                with self.subTest(action=action, flag=flag):
                    self.refused(400, self.apply, expect="a" * 64, confirm_stock=flag)
                    self.assertEqual(self.store.writes, [])

    def test_hidden_owner_or_incomplete_source_is_not_exposed_by_invalid_stock_confirmation(self):
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
            with self.subTest(mode=mode), mock.patch.object(undo, "raw_row", side_effect=AssertionError("No raw row validation")):
                error = self.refused(404, self.apply, expect="bad", confirm_stock="wrong")
                self.assertEqual((error.message, error.extra), (api.NO_CHANGE, {}))
            self.assertEqual(self.store.writes, [])

    def test_shared_stock_uses_ordinary_owner_scope_and_mixed_details_remain_literal(self):
        _, old = self.seed(owner="shared", mixed=True)
        with self.identity("user1"):
            preview = self.view()
            result = self.apply(profile="user1", confirm_stock=True)
        self.assertEqual([item["field"] for item in preview["fields"]], ["notes", "link", "quantity"])
        self.assertEqual(result["restored"], undo.stock_meta(old))
        self.assertEqual(self.store.writes[-1][0].id, "user1")
        self.assertEqual(result["restored"]["notes"], "Historical <script>literal</script> note")

    def test_noncanonical_quantities_on_either_source_side_make_review_unavailable_without_writes(self):
        for side in ("before", "after"):
            for value in (0, True, None, "", "00", "01", "-1", " 1", "1.0", "10000"):
                self.seed()
                self.store.audit[support.CHANGE_ID][0][side]["quantity"] = value
                with self.subTest(side=side, value=value):
                    self.assertEqual(self.view(), {"available": False, "id": support.CHANGE_ID, "reason": api.UNSUPPORTED})
                    self.refused(400, self.apply, expect="bad", confirm_stock=True)
                    self.assertEqual(self.store.writes, [])

    def test_forged_stock_action_projection_flags_or_quantity_neutral_source_fail_closed(self):
        plan = self.store.accessory_undo_review(support.CHANGE_ID, support.OWNERS)
        changed = []
        for replacement in ({"action": "accessory_update"}, {"stock_confirmation_required": False},
                            {"reason_required": True}, {"confirmation_required": True},
                            {"current": {**plan["current"], "quantity": 100}},
                            {"restored": {**plan["restored"], "quantity": "0"}},
                            {"fields": plan["fields"] * 2}):
            changed.append({**plan, **replacement})
        neutral = copy.deepcopy(plan)
        neutral["source"]["before"]["quantity"] = neutral["source"]["after"]["quantity"]
        changed.append(neutral)
        for replacement in changed:
            with self.subTest(plan=replacement), mock.patch.object(self.store, "accessory_undo_review", return_value=replacement):
                self.refused(503, self.view)
        self.assertEqual(self.store.writes, [])

    def test_wrong_actual_quantity_missing_or_extra_stock_projection_never_acknowledges_save(self):
        plan = self.store.accessory_undo_review(support.CHANGE_ID, support.OWNERS)
        result = {"review": plan, "restored": plan["restored"], "sha256": plan["sha256"], "revision": str(support.ROW_ID + 1)}
        missing = dict(plan["restored"])
        del missing["quantity"]
        for replacement in ({**result, "restored": {**plan["restored"], "quantity": "41"}},
                            {**result, "restored": {**plan["restored"], "quantity": 40}},
                            {**result, "restored": missing},
                            {**result, "restored": {**plan["restored"], "image": ""}},
                            {**result, "revision": str(support.ROW_ID)},
                            {**result, "sha256": "0" * 64}):
            with self.subTest(result=replacement), mock.patch.object(self.store, "accessory_undo_apply", return_value=replacement):
                self.refused(503, self.apply, expect=plan["expect"], confirm_stock=True)
        self.assertEqual(self.store.writes, [])

    def test_stale_and_lost_reply_require_fresh_review_and_do_not_retry(self):
        preview = self.view()
        self.store.latest += 1
        self.refused(409, self.apply, expect=preview["expect"], confirm_stock=True)
        self.assertEqual(self.store.writes, [])
        self.seed()
        preview = self.view()
        self.store.fail_after_commit = True
        self.refused(503, self.apply, expect=preview["expect"], confirm_stock=True)
        self.assertEqual(len(self.store.writes), 1)
        self.assertEqual(self.store.snapshot.accessories.rows[0].as_dict()["quantity"], "40")
        self.refused(409, self.apply, expect=preview["expect"], confirm_stock=True)
        self.assertEqual(len(self.store.writes), 1)
