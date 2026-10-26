"""Deleted-row restoration API contracts over isolated audit-shaped fixtures."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import activity_undo, guard
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files
from decklab.tests import test_activity_undo_api as original, test_inventory_undo_delete as fixture


class DeleteUndoApiTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.DeleteUndoTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.backend = self.case.store

    def view(self):
        return activity_undo.undo_view(id=str(original.CHANGE_ID))

    def apply(self, *, confirm_owned=True, expect=None, id=original.CHANGE_ID, **extra):
        expect = self.view()["expect"] if expect is None else expect
        return activity_undo.apply_undo(json.dumps({"profile": "matt", "id": id, "expect": expect,
                                                   "confirm_owned": confirm_owned, **extra}).encode())

    def refused(self, code, callback, **kwargs):
        with self.assertRaises(ApiError) as caught:
            callback(**kwargs)
        self.assertEqual(caught.exception.status, code, caught.exception.message)
        return caught.exception

    def test_preview_has_full_historical_row_and_explicit_ownership_requirement(self):
        result = self.view()
        self.assertEqual(set(result), {"available", "id", "expect", "kind", "space", "label", "action",
                                       "physical_confirmation_required", "current", "restored"})
        self.assertEqual(result["action"], "add")
        self.assertIs(result["physical_confirmation_required"], True)
        self.assertIsNone(result["current"])
        self.assertEqual(result["restored"], original.CARD)
        self.assertEqual(self.backend.writes, [])

    def test_confirmed_restore_returns_actual_row_key_sha_and_revision(self):
        preview = self.view()
        history = copy.deepcopy(self.backend.audit)
        result = self.apply(expect=preview["expect"])
        self.assertEqual(result["action"], "add")
        self.assertEqual(result["added_key"], {key: original.CARD[key] for key in ("set", "collector_number", "finish")})
        self.assertEqual(result["restored"], original.CARD)
        self.assertEqual(result["sha256"], files.rendered_sha256(self.backend.snapshot.collection("home")))
        self.assertEqual(result["revision"], self.backend.snapshot.revision)
        self.assertIs(self.backend.writes[0][0].params["confirm_owned"], True)
        self.assertEqual(self.backend.audit, history)

    def test_confirmation_must_be_supplied_as_exact_boolean_true(self):
        preview = self.view()
        for value in (None, False, 0, 1, "true", [], {}):
            with self.subTest(value=value):
                self.refused(400, self.apply, expect=preview["expect"], confirm_owned=value)
        body = json.dumps({"profile": "matt", "id": original.CHANGE_ID, "expect": preview["expect"]}).encode()
        self.refused(400, lambda: activity_undo.apply_undo(body))
        self.assertEqual(self.backend.writes, [])

    def test_hidden_missing_and_mixed_sources_precede_bad_confirmation_and_receipt(self):
        errors = [self.refused(404, self.apply, id=99, expect="bad", confirm_owned=[])]
        self.case.seed(space="user2")
        errors.append(self.refused(404, self.apply, expect="bad", confirm_owned=[]))
        self.case.seed()
        self.backend.audit[original.CHANGE_ID].append({"table": "profile_email", "after": {"email": "hidden@example.com"}})
        errors.append(self.refused(404, self.apply, expect="bad", confirm_owned=[]))
        self.assertEqual([error.message for error in errors], [activity_undo.NO_CHANGE] * 3)
        self.assertEqual(self.backend.writes, [])

    def test_browser_cannot_supply_rows_keys_quantities_or_removal_reason(self):
        preview = self.view()
        for extra in ({"row": original.CARD}, {"key": {}}, {"quantity": 9999}, {"reason": "Not a removal"}):
            with self.subTest(extra=extra):
                self.refused(400, self.apply, expect=preview["expect"], **extra)
        self.assertEqual(self.backend.writes, [])

    def test_receipt_staleness_and_repeated_source_never_add_more_copies(self):
        self.refused(400, self.apply, expect="bad")
        self.refused(409, self.apply, expect="0" * 64)
        preview = self.view()
        self.apply(expect=preview["expect"])
        self.refused(409, self.apply, expect=preview["expect"])
        self.assertEqual(len(self.backend.writes), 1)
        self.assertEqual(self.backend.snapshot.collection("home").rows[0].qty, original.CARD["quantity"])

    def test_candidate_hint_requires_single_global_own_collection_delete(self):
        row = copy.deepcopy(self.case.source())
        change, shown = {"id": original.CHANGE_ID, "total": 1, "rows": [row]}, {"id": original.CHANGE_ID}
        self.assertEqual(activity_undo.review_hint(change, shown, guard.viewer()), {"review": True})
        for altered in ({**change, "total": 2}, {**change, "more": 1}, {**change, "groups": [{}]}):
            self.assertIsNone(activity_undo.review_hint(altered, shown, guard.viewer()))
        for field, value in (("table", "token_card"), ("op", "INSERT"), ("after", {})):
            self.assertIsNone(activity_undo.review_hint({**change, "rows": [{**row, field: value}]}, shown, guard.viewer()))

    def test_wrong_actual_row_or_count_or_confirmation_proof_is_unconfirmed(self):
        preview = self.view()
        plan = self.case.review()
        after, summary = self.case.apply(plan)
        wrong = after.with_collection("home", [{**original.CARD, "notes": "Unexpected normalization"}])
        proofs = [(wrong, summary),
                  (after, inventory.Summary(summary.text, {**summary.counts, "bumped_rows": 1}, summary.changed, summary.extra)),
                  (after, inventory.Summary(summary.text, summary.counts, summary.changed,
                                            {**summary.extra, "confirmed_owned": False}))]
        for result in proofs:
            with self.subTest(result=result), mock.patch.object(activity_undo.saving, "apply_op", return_value=result):
                self.refused(503, self.apply, expect=preview["expect"])

    def test_confirmation_extension_is_rejected_for_existing_update_and_insert_protocols(self):
        self.case.case.case.seed()
        preview = self.view()
        self.refused(400, self.apply, expect=preview["expect"])
        self.case.case.seed()
        preview = self.view()
        self.refused(400, self.apply, expect=preview["expect"], reason="Correct addition")
        self.assertEqual(self.backend.writes, [])
