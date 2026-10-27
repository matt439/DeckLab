"""Removal Undo contracts over isolated authoritative INSERT fixtures only."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import activity_undo, guard
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files
from decklab.tests import test_activity_undo_api as original, test_inventory_undo_insert as fixture


class InsertUndoApiTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.InsertUndoTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.backend = self.case.store

    def view(self):
        return activity_undo.undo_view(id=str(original.CHANGE_ID))

    def apply(self, *, reason=fixture.REASON, expect=None, id=original.CHANGE_ID, **extra):
        expect = self.view()["expect"] if expect is None else expect
        return activity_undo.apply_undo(json.dumps({"profile": "matt", "id": id, "expect": expect,
                                                   "reason": reason, **extra}).encode())

    def refused(self, code, callback, **kwargs):
        with self.assertRaises(ApiError) as caught:
            callback(**kwargs)
        self.assertEqual(caught.exception.status, code, caught.exception.message)
        return caught.exception

    def test_removal_preview_has_explicit_action_and_null_restored_without_a_zero_row(self):
        result = self.view()
        self.assertEqual(set(result), {"available", "id", "expect", "kind", "space", "label", "action",
                                       "reason_required", "current", "restored"})
        self.assertEqual(result["action"], "remove")
        self.assertTrue(result["reason_required"])
        self.assertEqual(result["current"], original.CARD)
        self.assertIsNone(result["restored"])
        self.assertEqual(self.backend.writes, [])

    def test_explicit_reason_reaches_audited_write_and_actual_absence_receipt(self):
        preview = self.view()
        history = copy.deepcopy(self.backend.audit)
        real = inventory.apply
        with mock.patch.object(inventory, "apply", wraps=real) as apply:
            result = self.apply(reason="  Correct\n accidental addition.  ", expect=preview["expect"])
        self.assertEqual(apply.call_args.kwargs["reason"], "Correct accidental addition.")
        self.assertEqual(result["action"], "remove")
        self.assertEqual(result["removed_key"], {key: original.CARD[key] for key in ("set", "collector_number", "finish")})
        self.assertIsNone(result["restored"])
        self.assertEqual(self.backend.snapshot.collection("home").rows, ())
        self.assertEqual(result["sha256"], files.rendered_sha256(self.backend.snapshot.collection("home")))
        self.assertEqual(result["revision"], self.backend.snapshot.revision)
        self.assertEqual(self.backend.writes[0][0].params["reason"], "Correct accidental addition.")
        self.assertEqual(self.backend.audit, history)

    def test_missing_blank_oversized_or_wrong_type_reason_never_writes(self):
        preview = self.view()
        for reason in (None, "", " \t\n", "\u200b", "x" * 201, [], True, "contains\x00control"):
            with self.subTest(reason=reason):
                self.refused(400, self.apply, expect=preview["expect"], reason=reason)
        body = json.dumps({"profile": "matt", "id": original.CHANGE_ID, "expect": preview["expect"]}).encode()
        self.refused(400, lambda: activity_undo.apply_undo(body))
        self.assertEqual(self.backend.writes, [])

    def test_hidden_missing_and_mixed_sources_precede_bad_reason_and_receipt(self):
        errors = [self.refused(404, self.apply, id=99, expect="bad", reason=[])]
        self.case.seed(space="user2")
        errors.append(self.refused(404, self.apply, expect="bad", reason=[]))
        self.case.seed()
        self.backend.audit[original.CHANGE_ID].append({"table": "profile_email", "after": {"email": "hidden@example.com"}})
        errors.append(self.refused(404, self.apply, expect="bad", reason=[]))
        self.assertEqual([e.message for e in errors], [activity_undo.NO_CHANGE] * 3)
        self.assertEqual(self.backend.writes, [])

    def test_bad_or_stale_receipt_and_repeated_source_do_not_remove_more(self):
        self.refused(400, self.apply, expect="bad")
        self.refused(409, self.apply, expect="0" * 64)
        preview = self.view()
        self.apply(expect=preview["expect"])
        self.refused(409, self.apply, expect=preview["expect"])
        self.assertEqual(len(self.backend.writes), 1)

    def test_candidate_is_only_a_single_global_own_collection_insert_hint(self):
        row = copy.deepcopy(self.case.source())
        change, shown = {"id": original.CHANGE_ID, "total": 1, "rows": [row]}, {"id": original.CHANGE_ID}
        self.assertEqual(activity_undo.review_hint(change, shown, guard.viewer()), {"review": True})
        for altered in ({**change, "total": 2}, {**change, "more": 1}, {**change, "groups": [{}]}):
            self.assertIsNone(activity_undo.review_hint(altered, shown, guard.viewer()))
        for field, value in (("table", "token_card"), ("op", "DELETE"), ("before", {})):
            bad = {**change, "rows": [{**row, field: value}]}
            self.assertIsNone(activity_undo.review_hint(bad, shown, guard.viewer()))

    def test_wrong_postsave_presence_or_summary_action_is_not_confirmed(self):
        preview = self.view()
        plan = self.case.review()
        after, summary = self.case.apply(plan)
        for snapshot, proof in ((self.backend.snapshot, summary),
                                (after, inventory.Summary(summary.text, summary.counts, summary.changed,
                                                          {**summary.extra, "action": "restore"}))):
            with self.subTest(snapshot=snapshot), mock.patch.object(activity_undo.saving, "apply_op", return_value=(snapshot, proof)):
                self.refused(503, self.apply, expect=preview["expect"])

    def test_update_packets_and_extra_reason_refusal_remain_unchanged(self):
        self.case.case.seed()
        preview = self.view()
        self.assertNotIn("action", preview)
        self.assertIn("fields", preview)
        self.assertIsInstance(preview["restored"], dict)
        self.refused(400, self.apply, expect=preview["expect"])
        self.assertEqual(self.backend.writes, [])
