"""Whole-record consent for combined accessory corrections, using synthetic API state."""
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
CATEGORY_SETS = (("owner", "kind"), ("owner", "quantity"), ("kind", "quantity"), ("owner", "kind", "quantity"))


class AccessoryRecordUndoApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.store = base.AuditAccessories(support.build_snapshot())
        self.addCleanup(inventory.use(self.store))
        self.enterContext(self.identity("matt"))
        self.seed()

    def identity(self, profile):
        return access.using({"profile": profile, "email": profile + "@example.com", "remote": True})

    def seed(self, categories=("owner", "kind", "quantity"), *, current_kind="sleeves", historical_kind="deck_box",
             current_owner="shared", historical_owner="matt", zero=False, mixed=False):
        new = support.row(kind=current_kind, owner=current_owner if "owner" in categories else "matt",
                          quantity="1" if zero and "quantity" in categories else "0" if zero else "100",
                          capacity="100" if current_kind == "deck_box" else "")
        old = dict(new)
        if "owner" in categories:
            old["owner"] = historical_owner
        if "kind" in categories:
            old.update(kind=historical_kind, capacity="100" if historical_kind == "deck_box" else "")
        if "quantity" in categories:
            old["quantity"] = "0" if zero else "40"
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

    def test_four_compound_sets_owner_directions_kind_pairs_and_zero_counts_have_one_whole_record_review(self):
        for categories in CATEGORY_SETS:
            pairs = itertools.permutations(KINDS, 2) if "kind" in categories else ((kind, kind) for kind in KINDS)
            for current_kind, historical_kind in pairs:
                owners = (("shared", "matt"), ("matt", "shared")) if "owner" in categories else (("matt", "matt"),)
                for current_owner, historical_owner in owners:
                    for zero in (False, True):
                        new, old = self.seed(categories, current_kind=current_kind, historical_kind=historical_kind,
                            current_owner=current_owner, historical_owner=historical_owner, zero=zero)
                        before, original = self.store.snapshot, copy.deepcopy(self.store.audit)
                        with self.subTest(categories=categories, kinds=(current_kind, historical_kind), owner=current_owner, zero=zero):
                            preview = self.view()
                            self.assertEqual(set(preview), {"available", "id", "expect", "kind", "action", "label", "current",
                                                           "restored", "fields", "record_confirmation_required"})
                            self.assertEqual(preview["action"], "accessory_record_update")
                            self.assertIs(preview["record_confirmation_required"], True)
                            self.assertEqual(preview["current"], undo.stock_meta(new))
                            self.assertEqual(preview["restored"], undo.stock_meta(old))
                            self.assertEqual(len(preview["restored"]), 11)
                            changed = [field for field in ("owner", "kind", "quantity", *undo.FIELDS) if old[field] != new[field]]
                            self.assertEqual(preview["fields"], [{"field": field, "before": new[field], "after": old[field]} for field in changed])
                            result = self.apply(expect=preview["expect"], confirm_record=True)
                            self.assertEqual(set(result), {"saved", "source_id", "expect", "kind", "action", "restored", "sha256", "revision", "summary"})
                            self.assertEqual((result["action"], result["restored"]), ("accessory_record_update", preview["restored"]))
                            self.assertEqual((self.store.snapshot.accessory_images, self.store.snapshot.decks), (before.accessory_images, before.decks))
                            self.assertEqual(self.store.audit, original)
                            self.assertEqual(len(self.store.writes), 1)
                            actor, _, _, rows = self.store.writes[0]
                            self.assertEqual((actor.id, actor.source, actor.via), ("matt", "web", "tunnel"))
                            self.assertEqual((rows[0]["op"], rows[0]["before"], rows[0]["after"]), ("UPDATE", new, old))

    def test_missing_or_nonboolean_entire_record_consent_and_any_old_control_presence_refuse(self):
        preview = self.view()
        values = [{}, {"confirm_record": False}, {"confirm_record": None}, {"confirm_record": 1}, {"confirm_record": "true"}]
        values.extend({"confirm_record": True, flag: None} for flag in ("reason", "confirm_restore", "confirm_stock", "confirm_owner", "confirm_kind"))
        values.extend(({"confirm_record": True, "fields": ["quantity"]}, {"confirm_record": True, "quantity": "1"},
                       {"confirm_record": True, "action": "accessory_record_update"}))
        for options in values:
            with self.subTest(options=options):
                self.refused(400, self.apply, expect=preview["expect"], **options)
                self.assertEqual(self.store.writes, [])
        self.apply(expect=preview["expect"], confirm_record=True)

    def test_record_flag_presence_cannot_be_reused_for_zero_or_single_category_or_presence_actions(self):
        for action, categories in (("metadata", ()), ("stock", ("quantity",)), ("owner", ("owner",)), ("kind", ("kind",)),
                                   ("INSERT", ()), ("DELETE", ())):
            self.seed(categories, mixed=True)
            source = self.store.audit[support.CHANGE_ID][0]
            if action in ("INSERT", "DELETE"):
                source["op"] = action
                source["before" if action == "INSERT" else "after"] = None
            for value in (True, False, None):
                with self.subTest(action=action, value=value):
                    self.refused(400, self.apply, expect="a" * 64, confirm_record=value)
                    self.assertEqual(self.store.writes, [])

    def test_both_owner_scope_and_complete_source_precede_invalid_record_flag_or_private_labels(self):
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
            with self.subTest(mode=mode), mock.patch.object(undo, "raw_row", side_effect=AssertionError("No private validation")):
                error = self.refused(404, self.apply, expect="bad", confirm_record="invalid")
                self.assertEqual((error.message, error.extra), (api.NO_CHANGE, {}))
            self.assertEqual(self.store.writes, [])

    def test_unnamed_script_cannot_expand_owner_pair_or_reuse_its_receipt_for_a_named_save(self):
        for current, historical in (("matt", "user1"), ("shared", "user2"), ("shared", "orphan")):
            self.seed(current_owner=current, historical_owner=historical)
            with self.subTest(current=current, historical=historical), access.using(None), access.viewing(None), access.answering(True):
                self.assertEqual(self.view(), {"available": False, "id": support.CHANGE_ID, "reason": api.UNSUPPORTED})
            self.assertEqual(self.store.writes, [])
        self.seed()
        with access.using(None), access.viewing(None), access.answering(True):
            anonymous = self.view()
            self.assertEqual(anonymous["action"], "accessory_record_update")
            self.refused(409, self.apply, profile="matt", expect=anonymous["expect"], confirm_record=True)
            self.assertEqual(self.store.writes, [])
            named = undo.review(support.CHANGE_ID, support.OWNERS, self.store.snapshot, self.store)[0]
            result = self.apply(profile="matt", expect=named["expect"], confirm_record=True)
        self.assertEqual(result["restored"], named["restored"])

    def test_mixed_recorded_details_remain_literal_and_photo_bytes_are_not_read_or_fetched(self):
        _, old = self.seed(mixed=True)
        before = self.store.snapshot
        with mock.patch.object(accessory_fetch, "fetch", side_effect=AssertionError("No URL fetch")), \
                mock.patch.object(inventory, "image", side_effect=AssertionError("No image bytes")):
            preview = self.view()
            result = self.apply(confirm_record=True)
        self.assertEqual([field["field"] for field in preview["fields"]], ["owner", "kind", "quantity", "notes", "link", "capacity"])
        self.assertEqual(result["restored"], undo.stock_meta(old))
        self.assertEqual(result["restored"]["notes"], "Historical <script>literal</script> note")
        self.assertEqual(self.store.snapshot.accessory_images, before.accessory_images)

    def test_noncanonical_or_immutable_raw_fields_cannot_be_partly_restored(self):
        for field, value in (("quantity", "01"), ("quantity", "10000"), ("kind", "Deck_Box"), ("capacity", "01"),
                             ("id", "different-id"), ("image", "a-sleeves.png"), ("crop", "")):
            self.seed()
            self.store.audit[support.CHANGE_ID][0]["before"][field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(self.view(), {"available": False, "id": support.CHANGE_ID, "reason": api.UNSUPPORTED})
                self.refused(400, self.apply, expect="bad", confirm_record=True)
                self.assertEqual(self.store.writes, [])

    def test_new_wrong_kind_or_unbuilt_target_reference_invalidates_the_entire_compound_save(self):
        for categories in CATEGORY_SETS:
            for status, field in (("built", "Deck box"), ("idea", "Sleeves")):
                self.seed(categories)
                preview = self.view()
                deck = self.store.snapshot.deck("casual/fixture")
                text = deck.text.replace("- **Status:** built", f"- **Status:** {status}")
                text = text.replace("- **Built version:** target\n", f"- **Built version:** target\n- **{field}:** a-sleeves\n")
                self.store.snapshot = self.store.snapshot.with_deck(replace(deck, text=text))
                before = self.store.snapshot
                with self.subTest(categories=categories, status=status, field=field):
                    self.refused(409, self.apply, expect=preview["expect"], confirm_record=True)
                    self.assertEqual((self.store.snapshot, self.store.writes), (before, []))

    def test_compound_sources_cannot_masquerade_as_old_actions_and_single_sources_cannot_masquerade_as_record(self):
        plan = self.store.accessory_undo_review(support.CHANGE_ID, support.OWNERS)
        variants = []
        for replacement in ({"action": "accessory_update"}, {"action": "accessory_stock_update"}, {"action": "accessory_owner_update"},
                            {"action": "accessory_kind_update"}, {"record_confirmation_required": False},
                            {"stock_confirmation_required": True}, {"owner_confirmation_required": True}, {"kind_confirmation_required": True},
                            {"reason_required": True}, {"confirmation_required": True}, {"fields": plan["fields"][1:]},
                            {"current": {**plan["current"], "quantity": "0"}}, {"restored": {**plan["restored"], "owner": "shared"}}):
            variants.append({**plan, **replacement})
        for categories in ((), ("owner",), ("kind",), ("quantity",)):
            self.seed(categories, mixed=True)
            single = self.store.accessory_undo_review(support.CHANGE_ID, support.OWNERS)
            single.update(action="accessory_record_update", record_confirmation_required=True)
            for flag in ("stock_confirmation_required", "owner_confirmation_required", "kind_confirmation_required"):
                single.pop(flag, None)
            variants.append(single)
        for value in variants:
            with self.subTest(plan=value), mock.patch.object(self.store, "accessory_undo_review", return_value=value):
                self.refused(503, self.view)
        self.assertEqual(self.store.writes, [])

    def test_actual_any_category_or_zero_quantity_mismatch_is_never_acknowledged(self):
        self.seed(zero=True)
        plan = self.store.accessory_undo_review(support.CHANGE_ID, support.OWNERS)
        result = {"review": plan, "restored": plan["restored"], "sha256": plan["sha256"], "revision": str(support.ROW_ID + 1)}
        replacements = [{**result, "restored": {**plan["restored"], field: value}}
                        for field, value in (("owner", "shared"), ("kind", "playmat"), ("quantity", "1"), ("capacity", "40"), ("image", ""))]
        replacements.extend(({**result, "revision": str(support.ROW_ID)}, {**result, "sha256": "0" * 64}))
        for replacement in replacements:
            with self.subTest(receipt=replacement), mock.patch.object(self.store, "accessory_undo_apply", return_value=replacement):
                self.refused(503, self.apply, expect=plan["expect"], confirm_record=True)
        self.assertEqual(self.store.writes, [])

    def test_latest_target_staleness_and_lost_reply_do_not_retry_or_claim_completion(self):
        preview = self.view()
        self.store.latest += 1
        self.refused(409, self.apply, expect=preview["expect"], confirm_record=True)
        self.assertEqual(self.store.writes, [])
        self.seed()
        preview = self.view()
        self.store.fail_after_commit = True
        self.refused(503, self.apply, expect=preview["expect"], confirm_record=True)
        self.assertEqual(len(self.store.writes), 1)
        self.assertEqual(next(row for row in self.store.snapshot.accessories.rows if row.accessory_id == "a-sleeves").as_dict(),
                         self.store.audit[support.CHANGE_ID][0]["before"])
        self.refused(409, self.apply, expect=preview["expect"], confirm_record=True)
        self.assertEqual(len(self.store.writes), 1)
