"""Confirmed accessory kind corrections over isolated authoritative API fixtures."""
import copy
from dataclasses import replace
import itertools
import json
from unittest import mock

from decklab.lib import access, accessory_fetch, inventory
from decklab.lib.api import accessory_undo as api
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import accessory_undo as undo
from decklab.tests import accessory_undo_support as support, household_config
from decklab.tests import test_accessory_undo_api as base
from decklab.tests.test_api import ApiTestCase

DEFAULT = object()
KINDS = ("sleeves", "deck_box", "playmat")


class AccessoryKindUndoApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.store = base.AuditAccessories(support.build_snapshot())
        self.addCleanup(inventory.use(self.store))
        self.enterContext(self.identity("matt"))
        self.seed()

    def identity(self, profile):
        return access.using({"profile": profile, "email": profile + "@example.com", "remote": True})

    def seed(self, current="sleeves", historical="deck_box", *, quantity="100", owner="matt", mixed=False):
        new = support.row(kind=current, owner=owner, quantity=quantity, capacity="100" if current == "deck_box" else "")
        old = {**new, "kind": historical, "capacity": "100" if historical == "deck_box" else ""}
        if mixed:
            old.update(notes="Historical <script>literal</script> note", link="https://example.com/former")
        rows = [new, support.row(id="b-sleeves", owner="shared", image="", crop=""),
                support.row(id="c-box", owner="shared", kind="deck_box", quantity="2", capacity="100", image="", crop=""),
                support.row(id="d-playmat", kind="playmat", quantity="1", image="", crop=""),
                support.row(id="z-hidden", owner="user1", image="", crop="")]
        snapshot = support.build_snapshot(rows)
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

    def test_six_kind_directions_and_zero_stock_have_exact_eleven_text_review_and_actual_receipt(self):
        for current, historical in itertools.permutations(KINDS, 2):
            for quantity in ("0", "100"):
                new, old = self.seed(current, historical, quantity=quantity)
                before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
                with self.subTest(current=current, historical=historical, quantity=quantity):
                    preview = self.view()
                    self.assertEqual(set(preview), {"available", "id", "expect", "kind", "action", "label", "current",
                                                   "restored", "fields", "kind_confirmation_required"})
                    self.assertEqual(preview["action"], "accessory_kind_update")
                    self.assertIs(preview["kind_confirmation_required"], True)
                    self.assertEqual(preview["current"], undo.stock_meta(new))
                    self.assertEqual(preview["restored"], undo.stock_meta(old))
                    self.assertEqual(len(preview["restored"]), 11)
                    self.assertEqual([item["field"] for item in preview["fields"]],
                                     ["kind", *(["capacity"] if "deck_box" in (current, historical) else [])])
                    result = self.apply(expect=preview["expect"], confirm_kind=True)
                    self.assertEqual(set(result), {"saved", "source_id", "expect", "kind", "action", "restored", "sha256", "revision", "summary"})
                    self.assertEqual((result["action"], result["restored"]), ("accessory_kind_update", preview["restored"]))
                    self.assertEqual(self.store.snapshot.accessory_images, before.accessory_images)
                    self.assertEqual(self.store.snapshot.decks, before.decks)
                    self.assertEqual(self.store.audit, audit)
                    self.assertEqual(len(self.store.writes), 1)
                    actor, _, _, rows = self.store.writes[0]
                    self.assertEqual((actor.id, actor.source, actor.via), ("matt", "web", "tunnel"))
                    self.assertEqual((rows[0]["op"], rows[0]["before"], rows[0]["after"]), ("UPDATE", new, old))

    def test_missing_or_nonboolean_kind_consent_and_other_action_controls_never_write(self):
        preview = self.view()
        for options in ({}, {"confirm_kind": False}, {"confirm_kind": None}, {"confirm_kind": 1},
                        {"confirm_kind": "true"}, {"confirm_kind": True, "reason": None},
                        {"confirm_kind": True, "confirm_restore": None}, {"confirm_kind": True, "confirm_stock": None},
                        {"confirm_kind": True, "confirm_owner": None}, {"confirm_kind": True, "kind": "sleeves"}):
            with self.subTest(options=options):
                self.refused(400, self.apply, expect=preview["expect"], **options)
                self.assertEqual(self.store.writes, [])
        self.apply(expect=preview["expect"], confirm_kind=True)

    def test_kind_flag_presence_is_rejected_for_metadata_stock_owner_addition_or_removal(self):
        for action in ("metadata", "stock", "owner", "INSERT", "DELETE"):
            self.seed()
            source = self.store.audit[support.CHANGE_ID][0]
            source["before"].update(kind=source["after"]["kind"], capacity=source["after"]["capacity"])
            if action == "metadata":
                source["before"]["notes"] = "Old metadata"
            elif action == "stock":
                source["before"]["quantity"] = "99"
            elif action == "owner":
                source["before"]["owner"] = "shared"
            else:
                source["op"] = action
                source["before" if action == "INSERT" else "after"] = None
            for value in (True, False, None):
                with self.subTest(action=action, value=value):
                    self.refused(400, self.apply, expect="a" * 64, confirm_kind=value)
                    self.assertEqual(self.store.writes, [])

    def test_source_both_owner_scope_and_completeness_precede_invalid_kind_flag_or_private_labels(self):
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
                error = self.refused(404, self.apply, expect="bad", confirm_kind="invalid")
                self.assertEqual((error.message, error.extra), (api.NO_CHANGE, {}))
            self.assertEqual(self.store.writes, [])

    def test_mixed_metadata_and_shared_viewer_keep_literal_values_and_current_photo(self):
        new, old = self.seed("playmat", "deck_box", owner="shared", mixed=True)
        before = self.store.snapshot
        with self.identity("user1"), mock.patch.object(accessory_fetch, "fetch", side_effect=AssertionError("No URL fetch")), \
                mock.patch.object(inventory, "image", side_effect=AssertionError("No photo bytes")):
            preview = self.view()
            result = self.apply(profile="user1", confirm_kind=True)
        self.assertEqual([item["field"] for item in preview["fields"]], ["kind", "notes", "link", "capacity"])
        self.assertEqual(result["restored"], undo.stock_meta(old))
        self.assertEqual(result["restored"]["notes"], "Historical <script>literal</script> note")
        self.assertEqual((old["image"], old["crop"]), (new["image"], new["crop"]))
        self.assertEqual(self.store.snapshot.accessory_images, before.accessory_images)

    def test_kind_mixtures_and_noncanonical_capacity_are_never_partly_restored(self):
        for field, value in (("quantity", "99"), ("owner", "shared"), ("id", "different-id"),
                             ("image", "a-sleeves.png"), ("crop", ""), ("capacity", "01")):
            self.seed()
            self.store.audit[support.CHANGE_ID][0]["before"][field] = value
            with self.subTest(field=field):
                if field in ("quantity", "owner"):
                    preview = self.view()
                    self.assertEqual(preview["action"], "accessory_record_update")
                    self.assertIs(preview["record_confirmation_required"], True)
                    self.assertNotIn("kind_confirmation_required", preview)
                    self.refused(400, self.apply, expect=preview["expect"], confirm_kind=True)
                else:
                    self.assertEqual(self.view(), {"available": False, "id": support.CHANGE_ID, "reason": api.UNSUPPORTED})
                    self.refused(400, self.apply, expect="bad", confirm_kind=True)
                self.assertEqual(self.store.writes, [])

    def test_preview_is_not_authority_after_target_acquires_a_wrong_kind_or_unbuilt_reference(self):
        for status, field in (("built", "Deck box"), ("idea", "Sleeves")):
            self.seed()
            preview = self.view()
            deck = self.store.snapshot.deck("casual/fixture")
            text = deck.text.replace("- **Status:** built", f"- **Status:** {status}")
            text = text.replace("- **Built version:** target\n", f"- **Built version:** target\n- **{field}:** a-sleeves\n")
            self.store.snapshot = self.store.snapshot.with_deck(replace(deck, text=text))
            before = self.store.snapshot
            with self.subTest(status=status, field=field):
                self.refused(409, self.apply, expect=preview["expect"], confirm_kind=True)
                self.assertEqual((self.store.snapshot, self.store.writes), (before, []))

    def test_script_preview_remains_scope_bound_before_a_named_confirmed_save(self):
        with access.using(None), access.viewing(None), access.answering(True):
            anonymous = self.view()
            self.assertEqual(anonymous["action"], "accessory_kind_update")
            self.refused(409, self.apply, profile="matt", expect=anonymous["expect"], confirm_kind=True)
            self.assertEqual(self.store.writes, [])
            named = undo.review(support.CHANGE_ID, support.OWNERS, self.store.snapshot, self.store)[0]
            result = self.apply(profile="matt", expect=named["expect"], confirm_kind=True)
        self.assertEqual(result["restored"]["kind"], "deck_box")

    def test_forged_kind_action_flags_or_quantity_change_projection_fail_closed(self):
        plan = self.store.accessory_undo_review(support.CHANGE_ID, support.OWNERS)
        variants = []
        for replacement in ({"action": "accessory_update"}, {"action": "accessory_stock_update"}, {"action": "accessory_owner_update"},
                            {"kind_confirmation_required": False}, {"stock_confirmation_required": True}, {"owner_confirmation_required": True},
                            {"reason_required": True}, {"confirmation_required": True},
                            {"current": {**plan["current"], "quantity": "0"}}, {"restored": {**plan["restored"], "quantity": 100}},
                            {"fields": plan["fields"] * 2}):
            variants.append({**plan, **replacement})
        neutral = copy.deepcopy(plan)
        neutral["source"]["before"].update(kind=neutral["source"]["after"]["kind"], capacity=neutral["source"]["after"]["capacity"])
        variants.append(neutral)
        for value in variants:
            with self.subTest(plan=value), mock.patch.object(self.store, "accessory_undo_review", return_value=value):
                self.refused(503, self.view)
        self.assertEqual(self.store.writes, [])

    def test_wrong_actual_kind_zero_quantity_or_extra_fields_never_acknowledge_a_save(self):
        self.seed(quantity="0")
        plan = self.store.accessory_undo_review(support.CHANGE_ID, support.OWNERS)
        result = {"review": plan, "restored": plan["restored"], "sha256": plan["sha256"], "revision": str(support.ROW_ID + 1)}
        for replacement in ({**result, "restored": {**plan["restored"], "kind": "playmat"}},
                            {**result, "restored": {**plan["restored"], "quantity": "1"}},
                            {**result, "restored": {**plan["restored"], "image": ""}},
                            {**result, "revision": str(support.ROW_ID)}, {**result, "sha256": "0" * 64}):
            with self.subTest(receipt=replacement), mock.patch.object(self.store, "accessory_undo_apply", return_value=replacement):
                self.refused(503, self.apply, expect=plan["expect"], confirm_kind=True)
        self.assertEqual(self.store.writes, [])

    def test_stale_latest_target_and_lost_reply_do_not_retry_or_claim_completion(self):
        preview = self.view()
        self.store.latest += 1
        self.refused(409, self.apply, expect=preview["expect"], confirm_kind=True)
        self.assertEqual(self.store.writes, [])
        self.seed()
        preview = self.view()
        self.store.fail_after_commit = True
        self.refused(503, self.apply, expect=preview["expect"], confirm_kind=True)
        self.assertEqual(len(self.store.writes), 1)
        self.assertEqual(next(row for row in self.store.snapshot.accessories.rows if row.accessory_id == "a-sleeves").text("kind"), "deck_box")
        self.refused(409, self.apply, expect=preview["expect"], confirm_kind=True)
        self.assertEqual(len(self.store.writes), 1)
