"""Whole INSERT batches expose one strict, reasoned removal without client row facts."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import activity_undo, guard
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files
from decklab.tests import test_activity_undo_api as original
from decklab.tests import test_inventory_undo_batch_insert as fixture


class BatchInsertUndoApiTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.BatchInsertUndoTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.backend = self.case.store

    def view(self):
        return activity_undo.undo_view(id=str(original.CHANGE_ID))

    def apply(self, *, expect=None, **extra):
        expect = self.view()["expect"] if expect is None else expect
        return activity_undo.apply_undo(json.dumps({"profile": "matt", "id": original.CHANGE_ID,
                                                   "expect": expect, **extra}).encode())

    def refused(self, status, call, **kwargs):
        with self.assertRaises(ApiError) as caught:
            call(**kwargs)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        return caught.exception

    def test_preview_lists_full_current_rows_without_fields_or_ownership_confirmation(self):
        result = self.view()
        self.assertEqual(set(result), {"available", "id", "expect", "kind", "space", "label", "action", "row_count", "rows", "reason_required"})
        self.assertEqual((result["action"], result["row_count"], result["kind"]), ("batch_remove", 2, "collection"))
        self.assertIs(result["reason_required"], True)
        for item in result["rows"]:
            self.assertEqual(set(item), {"key", "label", "current", "restored"})
            self.assertIsNone(item["restored"])
            self.assertEqual(item["key"], {key: item["current"][key] for key in ("set", "collector_number", "finish")})
            self.assertEqual(set(item["current"]), set(original.CARD))
        self.assertEqual(self.backend.writes, [])

    def test_one_nonblank_bounded_reason_is_required_and_normalized_for_audit(self):
        preview = self.view()
        self.refused(400, self.apply, expect=preview["expect"])
        for reason in (None, "", " \n\t ", 1, [], {}, "x" * 201, "Embedded\0reason"):
            with self.subTest(reason=repr(reason)):
                self.refused(400, self.apply, expect=preview["expect"], reason=reason)
        self.assertEqual(self.backend.writes, [])
        result = self.apply(expect=preview["expect"], reason="  Correct  accidental restoration.  ")
        self.assertEqual(result["action"], "batch_remove")
        op, _, _, summary = self.backend.writes[0]
        self.assertEqual(op.params["reason"], "Correct accidental restoration.")
        self.assertEqual(summary.extra["undo_reason"], "Correct accidental restoration.")

    def test_removed_key_receipt_confirms_actual_empty_result_and_one_write(self):
        preview, history = self.view(), copy.deepcopy(self.backend.audit)
        result = self.apply(expect=preview["expect"], reason="Correct accidental restoration.")
        self.assertEqual((result["action"], result["row_count"]), ("batch_remove", 2))
        self.assertEqual(result["removed_keys"], [item["key"] for item in preview["rows"]])
        self.assertIsNone(result["restored"])
        self.assertNotIn("restored_rows", result)
        self.assertNotIn("collection_rows_after", result)
        self.assertEqual(self.backend.snapshot.collection("home").rows, ())
        self.assertEqual(result["sha256"], files.rendered_sha256(self.backend.snapshot.collection("home")))
        self.assertEqual(result["revision"], self.backend.snapshot.revision)
        self.assertEqual(self.backend.audit, history)
        self.assertEqual(dict(self.backend.writes[0][0].params), {"change_id": original.CHANGE_ID, "space": "home",
                         "expect": preview["expect"], "reason": "Correct accidental restoration."})
        self.assertEqual(len(self.backend.writes), 1)

    def test_hidden_raw_import_and_beyond_limit_hide_all_rows_before_bad_reason_or_expect(self):
        for mode in ("hidden", "raw_import", "limit"):
            self.case.seed(count=51 if mode == "limit" else 2)
            if mode == "hidden":
                self.case.source()[0]["after"]["unsupported"] = "Own detail"
                self.case.source()[-1]["after"]["space_id"] = "user2"
            elif mode == "raw_import":
                self.case.source()[-1] = {"table": "collection_import", "op": "INSERT", "before": None,
                                         "after": {"space_id": "home", "content": "Opaque source"}}
            with self.subTest(mode=mode):
                self.assertEqual(self.refused(404, self.apply, expect="bad", reason=None).message, activity_undo.NO_CHANGE)
        self.assertEqual(self.backend.writes, [])

    def test_client_cannot_override_or_select_rows_or_supply_confirmation(self):
        preview = self.view()
        for extra in ({"rows": []}, {"keys": []}, {"quantity": 1}, {"confirm_owned": True}, {"allow_in_use": True}):
            with self.subTest(extra=extra):
                self.refused(400, self.apply, expect=preview["expect"], reason="Correct accidental restoration.", **extra)
        self.assertEqual(self.backend.writes, [])

    def test_any_same_name_holder_blocks_whole_batch_despite_other_printing_surplus(self):
        self.case.case.built("1 Llanowar Elves\n59 Forest")
        rows = [row.as_dict() for row in self.backend.snapshot.collection("home").rows]
        self.backend.snapshot = self.backend.snapshot.with_collection("home", [*rows, {**original.CARD, "finish": "foil", "quantity": 99}])
        before = self.backend.snapshot
        self.refused(409, self.view)
        self.refused(409, self.apply, expect="0" * 64, reason="Correct accidental restoration.")
        self.assertEqual(self.backend.snapshot, before)
        self.assertEqual(self.backend.writes, [])

    def test_corrupt_preview_flags_keys_rows_and_counts_are_not_offered(self):
        plan = self.case.review()
        for mode in ("reason", "count", "duplicate", "key", "current", "restore"):
            corrupt = copy.deepcopy(plan)
            if mode == "reason":
                corrupt["reason_required"] = False
            elif mode == "count":
                corrupt["row_count"] = True
            elif mode == "duplicate":
                corrupt["rows"][-1] = copy.deepcopy(corrupt["rows"][0])
            elif mode == "key":
                corrupt["rows"][0]["key"]["finish"] = "etched"
            elif mode == "current":
                corrupt["rows"][0]["current"] = None
            else:
                corrupt["rows"][0]["restore"] = copy.deepcopy(corrupt["rows"][0]["current"])
            with self.subTest(mode=mode), mock.patch.object(activity_undo.inventory, "undo_review", return_value=corrupt):
                self.refused(503, self.view)

    def test_actual_survivors_target_absence_counts_and_reason_must_match(self):
        unrelated = {**original.CARD, "finish": "foil", "quantity": 8, "notes": "Unrelated survivor"}
        rows = [row.as_dict() for row in self.backend.snapshot.collection("home").rows]
        self.backend.snapshot = self.backend.snapshot.with_collection("home", [*rows, unrelated])
        preview, plan = self.view(), self.case.review()
        after, summary = self.case.apply(plan)
        variants = [(after.with_collection("home", []), summary),
                    (after.with_collection("home", [unrelated, plan["rows"][0]["current"]]), summary)]
        for key, value in (("edited", 1), ("removed", 1)):
            variants.append((after, inventory.Summary(summary.text, {**summary.counts, key: value}, summary.changed, summary.extra)))
        for key, value in (("action", "batch_add"), ("undo_reason", "Different reason"), ("row_change_ids", [])):
            variants.append((after, inventory.Summary(summary.text, summary.counts, summary.changed, {**summary.extra, key: value})))
        for result in variants:
            with self.subTest(result=result), mock.patch.object(activity_undo.saving, "apply_op", return_value=result):
                self.refused(503, self.apply, expect=preview["expect"], reason="Correct accidental restoration.")

    def test_activity_hint_requires_complete_own_collection_insert_only_source(self):
        rows = copy.deepcopy(self.case.source())
        change, shown = {"id": original.CHANGE_ID, "rows": rows, "total": 2}, {"id": original.CHANGE_ID}
        self.assertEqual(activity_undo.review_hint(change, shown, guard.viewer()), {"review": True})
        for item in ({**change, "total": 3}, {**change, "more": 1}, {**change, "groups": [{}]}):
            self.assertIsNone(activity_undo.review_hint(item, shown, guard.viewer()))
        for table in ("collection_import", "order_component", "deck"):
            rows[-1]["table"] = table
            self.assertIsNone(activity_undo.review_hint(change, shown, guard.viewer()))
        rows[-1]["table"], rows[-1]["op"] = "collection_card", "UPDATE"
        rows[-1]["before"] = copy.deepcopy(rows[-1]["after"])
        self.assertIsNone(activity_undo.review_hint(change, shown, guard.viewer()))
