"""Whole deleted collection batches require one explicit all-copy confirmation."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import activity_undo, guard
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files
from decklab.tests import test_activity_undo_api as original
from decklab.tests import test_inventory_undo_batch_delete as fixture


class BatchDeleteUndoApiTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.BatchDeleteUndoTests()
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

    def test_preview_shows_full_former_rows_without_fields_or_write(self):
        result = self.view()
        self.assertEqual(set(result), {"available", "id", "expect", "kind", "space", "label", "action", "row_count",
                                       "rows", "physical_confirmation_required"})
        self.assertEqual((result["action"], result["row_count"], result["kind"]), ("batch_add", 2, "collection"))
        self.assertIs(result["physical_confirmation_required"], True)
        for item in result["rows"]:
            self.assertEqual(set(item), {"key", "label", "current", "restored"})
            self.assertIsNone(item["current"])
            self.assertEqual(item["key"], {key: item["restored"][key] for key in ("set", "collector_number", "finish")})
            self.assertEqual(set(item["restored"]), set(original.CARD))
        self.assertEqual(self.backend.writes, [])

    def test_confirmation_must_be_explicit_exact_boolean_true_for_every_copy(self):
        preview = self.view()
        self.refused(400, self.apply, expect=preview["expect"])
        for value in (None, False, 0, 1, "true", "yes", [], {}):
            with self.subTest(value=value):
                self.refused(400, self.apply, expect=preview["expect"], confirm_owned=value)
        self.assertEqual(self.backend.writes, [])
        self.assertEqual(self.backend.snapshot.collection("home").rows, ())

    def test_confirmed_receipt_has_only_actual_full_rows_by_key_and_one_web_write(self):
        preview, history = self.view(), copy.deepcopy(self.backend.audit)
        result = self.apply(expect=preview["expect"], confirm_owned=True)
        self.assertEqual((result["action"], result["row_count"]), ("batch_add", 2))
        self.assertEqual(result["restored_rows"], [{"key": item["key"], "row": item["restored"]} for item in preview["rows"]])
        self.assertNotIn("added_key", result)
        self.assertNotIn("added_keys", result)
        self.assertEqual(result["sha256"], files.rendered_sha256(self.backend.snapshot.collection("home")))
        self.assertEqual(result["revision"], self.backend.snapshot.revision)
        self.assertEqual(self.backend.audit, history)
        op, actor, _, summary = self.backend.writes[0]
        self.assertEqual(dict(op.params), {"change_id": original.CHANGE_ID, "space": "home", "expect": preview["expect"],
                                           "confirm_owned": True})
        self.assertEqual((actor.id, actor.source), ("matt", "web"))
        self.assertIs(summary.extra["confirmed_owned"], True)
        self.assertEqual(len(self.backend.writes), 1)

    def test_hidden_mixed_or_beyond_limit_is_missing_before_bad_expect_or_confirmation(self):
        errors = []
        for mode in ("hidden", "mixed", "limit"):
            self.case.seed(count=51 if mode == "limit" else 2)
            if mode == "hidden":
                self.case.source()[-1]["before"]["space_id"] = "user2"
                self.case.source()[0]["before"]["unsupported"] = "Own detail"
            elif mode == "mixed":
                self.case.source()[-1] = {"table": "profile_email", "op": "DELETE", "before": {"email": "hidden@example.com"}, "after": None}
            errors.append(self.refused(404, self.apply, expect="bad", confirm_owned=False))
        self.assertEqual([error.message for error in errors], [activity_undo.NO_CHANGE] * 3)
        self.assertEqual(self.backend.writes, [])

    def test_reason_rows_quantities_and_override_are_not_accepted(self):
        preview = self.view()
        for extra in ({"rows": []}, {"keys": []}, {"quantity": 1}, {"reason": "Override"}, {"allow_in_use": True}):
            with self.subTest(extra=extra):
                self.refused(400, self.apply, expect=preview["expect"], confirm_owned=True, **extra)
        self.assertEqual(self.backend.writes, [])

    def test_collision_unsupported_card_and_stale_repeat_never_restore_subset(self):
        plan = self.case.review()
        self.backend.snapshot = self.backend.snapshot.with_collection("home", [plan["rows"][-1]["restore"]])
        self.refused(409, self.apply, expect=plan["expect"], confirm_owned=True)
        self.case.seed()
        self.case.source()[-1]["before"]["name"] = "No such fixture card"
        self.assertEqual(self.view(), {"available": False, "id": original.CHANGE_ID, "reason": activity_undo.UNSUPPORTED})
        self.refused(400, self.apply, expect="0" * 64, confirm_owned=True)
        self.case.seed()
        preview = self.view()
        self.refused(409, self.apply, expect="0" * 64, confirm_owned=True)
        self.apply(expect=preview["expect"], confirm_owned=True)
        self.refused(409, self.apply, expect=preview["expect"], confirm_owned=True)
        self.assertEqual(len(self.backend.writes), 1)

    def test_corrupt_backend_preview_never_weakens_all_copy_confirmation(self):
        plan = self.case.review()
        for mode in ("confirmation", "count", "duplicate", "key", "current", "quantity"):
            corrupt = copy.deepcopy(plan)
            if mode == "confirmation":
                corrupt["physical_confirmation_required"] = False
            elif mode == "count":
                corrupt["row_count"] = True
            elif mode == "duplicate":
                corrupt["rows"][-1] = copy.deepcopy(corrupt["rows"][0])
            elif mode == "key":
                corrupt["rows"][0]["key"]["finish"] = "etched"
            elif mode == "current":
                corrupt["rows"][0]["current"] = corrupt["rows"][0]["restore"]
            else:
                corrupt["rows"][0]["restore"]["quantity"] = 0
            with self.subTest(mode=mode), mock.patch.object(activity_undo.inventory, "undo_review", return_value=corrupt):
                self.refused(503, self.view)

    def test_actual_counts_confirmation_source_ids_and_keyed_rows_must_all_match(self):
        preview = self.view()
        after, summary = self.case.apply()
        absent = after.with_collection("home", [row.as_dict() for row in after.collection("home").rows][:-1])
        variants = [(absent, summary)]
        for key, value in (("added_rows", 1), ("bumped_rows", 1), ("skipped_basics", 1), ("merged", True), ("cards", 0)):
            variants.append((after, inventory.Summary(summary.text, {**summary.counts, key: value}, summary.changed, summary.extra)))
        for key, value in (("confirmed_owned", False), ("action", "batch_update"), ("row_change_ids", [])):
            variants.append((after, inventory.Summary(summary.text, summary.counts, summary.changed, {**summary.extra, key: value})))
        for result in variants:
            with self.subTest(result=result), mock.patch.object(activity_undo.saving, "apply_op", return_value=result):
                self.refused(503, self.apply, expect=preview["expect"], confirm_owned=True)

    def test_review_affordance_needs_complete_unmixed_owned_global_deletions(self):
        rows = copy.deepcopy(self.case.source())
        change, shown = {"id": original.CHANGE_ID, "rows": rows, "total": 2}, {"id": original.CHANGE_ID}
        self.assertEqual(activity_undo.review_hint(change, shown, guard.viewer()), {"review": True})
        for item in ({**change, "total": 3}, {**change, "more": 1}, {**change, "groups": [{}]}):
            self.assertIsNone(activity_undo.review_hint(item, shown, guard.viewer()))
        rows[-1]["op"] = "UPDATE"
        rows[-1]["after"] = copy.deepcopy(rows[-1]["before"])
        self.assertIsNone(activity_undo.review_hint(change, shown, guard.viewer()))
        rows[-1]["op"], rows[-1]["after"] = "DELETE", None
        rows[-1]["before"]["space_id"] = "user2"
        self.assertIsNone(activity_undo.review_hint(change, shown, guard.viewer()))
