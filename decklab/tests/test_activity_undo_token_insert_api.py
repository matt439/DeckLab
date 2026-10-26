"""Private token INSERT Undo API contract over isolated stable-ID fixtures."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import activity_undo, guard
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, model
from decklab.tests import test_activity_undo_api as original
from decklab.tests import test_inventory_undo_token_insert as fixture


class TokenInsertUndoApiTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.TokenInsertUndoTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.store = self.case.store

    def view(self):
        return activity_undo.undo_view(id=str(original.CHANGE_ID))

    def apply(self, *, expect=None, reason=fixture.REASON, **extra):
        expect = self.view()["expect"] if expect is None else expect
        return activity_undo.apply_undo(json.dumps({"profile": "matt", "id": original.CHANGE_ID,
                                                   "expect": expect, "reason": reason, **extra}).encode())

    def refused(self, status, call, **kwargs):
        with self.assertRaises(ApiError) as caught:
            call(**kwargs)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        return caught.exception

    def test_preview_is_full_owner_row_with_stable_id_and_no_printing_identity(self):
        preview = self.view()
        self.assertEqual(set(preview), {"available", "id", "expect", "kind", "space", "label", "action", "reason_required",
                                       "token_row_id", "current", "restored"})
        self.assertEqual((preview["kind"], preview["action"], preview["token_row_id"]), ("tokens", "remove", fixture.TARGET_ID))
        self.assertEqual(preview["current"], fixture.token())
        self.assertIsNone(preview["restored"])
        self.assertTrue(preview["reason_required"])
        self.assertNotIn("id", preview["current"])
        self.assertNotIn("position", preview["current"])
        self.assertEqual(self.store.writes, [])

    def test_receipt_uses_actual_remaining_rows_and_normalized_audited_reason(self):
        survivor = model.TokenRow.make(fixture.token("Zombie", "Zombie Knight", 3), id=8)
        self.case.seed(extra=(survivor,))
        original_audit = copy.deepcopy(self.store.audit)
        with mock.patch.object(activity_undo.saving, "apply_op", wraps=activity_undo.saving.apply_op) as save:
            answer = self.apply(reason="  Correct\n accidental token addition.  ")
        self.assertEqual(answer["removed_token_row_id"], fixture.TARGET_ID)
        self.assertEqual((answer["kind"], answer["action"]), ("tokens", "remove"))
        self.assertIsNone(answer["restored"])
        self.assertNotIn("removed_key", answer)
        self.assertEqual(answer["sha256"], files.rendered_sha256(self.store.snapshot.token_set("home")))
        self.assertEqual(answer["revision"], self.store.snapshot.revision)
        self.assertEqual(save.call_args.kwargs["reason"], "Correct accidental token addition.")
        self.assertEqual(self.store.writes[0][1].id, "matt")
        self.assertEqual(self.store.writes[0][1].source, "web")
        self.assertEqual(self.store.writes[0][3].counts["cards"], 3)
        self.assertEqual([(row.id, row.as_dict()) for row in self.store.snapshot.token_set("home").rows], [(8, survivor.as_dict())])
        self.assertEqual(self.store.audit, original_audit)

    def test_missing_hidden_and_mixed_sources_hide_rows_before_bad_reason_or_receipt(self):
        self.store.audit.clear()
        errors = [self.refused(404, self.apply, expect="bad", reason=None)]
        self.case.seed(space="user2")
        errors.append(self.refused(404, self.apply, expect="bad", reason=None))
        self.case.seed()
        hidden = copy.deepcopy(self.case.source())
        hidden["after"]["space_id"] = "user2"
        self.store.audit[original.CHANGE_ID].append(hidden)
        errors.append(self.refused(404, self.apply, expect="bad", reason=None))
        self.assertEqual([error.message for error in errors], [activity_undo.NO_CHANGE] * 3)
        self.assertEqual(self.store.writes, [])

    def test_unknown_pairing_is_unavailable_and_token_deletion_stays_unsupported(self):
        for row in (fixture.token(notes="reverse face unconfirmed"), fixture.token("Treasure", "", notes="printing unconfirmed")):
            self.case.seed(row)
            self.assertEqual(self.view(), {"available": False, "id": original.CHANGE_ID, "reason": activity_undo.UNSUPPORTED})
            self.refused(400, self.apply, expect="0" * 64)
        self.case.seed()
        source = self.case.source()
        source["op"], source["before"], source["after"] = "DELETE", source["after"], None
        self.refused(404, self.view)
        self.assertEqual(self.store.writes, [])

    def test_reason_required_and_no_browser_row_key_id_or_confirmation_is_accepted(self):
        preview = self.view()
        for reason in (None, "", " \n ", 5, "x" * 201):
            with self.subTest(reason=reason):
                self.refused(400, self.apply, expect=preview["expect"], reason=reason)
        for extra in ({"row": fixture.token()}, {"token_row_id": fixture.TARGET_ID}, {"key": {"id": fixture.TARGET_ID}}, {"confirm_owned": True}):
            with self.subTest(extra=extra):
                self.refused(400, self.apply, expect=preview["expect"], **extra)
        self.assertEqual(self.store.writes, [])

    def test_stale_bad_and_repeated_receipts_do_not_remove_again(self):
        self.refused(400, self.apply, expect="bad")
        self.refused(409, self.apply, expect="0" * 64)
        preview = self.view()
        self.apply(expect=preview["expect"])
        self.refused(409, self.apply, expect=preview["expect"])
        self.assertEqual(len(self.store.writes), 1)

    def test_each_member_derives_their_space_and_cannot_select_home(self):
        self.case.seed(space="user2")
        self.refused(404, self.view)
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            preview = self.view()
            answer = activity_undo.apply_undo(json.dumps({"profile": "user2", "id": original.CHANGE_ID,
                                                         "expect": preview["expect"], "reason": fixture.REASON}).encode())
        self.assertEqual((preview["space"], answer["space"], self.store.writes[0][1].id), ("user2", "user2", "user2"))

    def test_candidate_is_complete_owner_insert_only_and_makes_no_eligibility_claim(self):
        row = copy.deepcopy(self.case.source())
        change, shown = {"id": original.CHANGE_ID, "rows": [row], "total": 1}, {"id": original.CHANGE_ID}
        self.assertEqual(activity_undo.review_hint(change, shown, guard.viewer()), {"review": True})
        for changed in ({**change, "total": 2}, {**change, "more": 1}, {**change, "groups": [{}]}):
            self.assertIsNone(activity_undo.review_hint(changed, shown, guard.viewer()))
        row["after"]["space_id"] = "user2"
        self.assertIsNone(activity_undo.review_hint(change, shown, guard.viewer()))

    def test_wrong_actual_identity_survivors_totals_or_summary_never_claim_saved(self):
        survivor = model.TokenRow.make(fixture.token("Zombie", "Zombie Knight", 3), id=8)
        self.case.seed(extra=(survivor,))
        preview = self.view()
        after, summary = self.case.apply()
        wrong_id = after.with_tokens("home", [model.TokenRow.make(survivor.as_dict(), id=99)])
        kept_target = after.with_tokens("home", [model.TokenRow.make(fixture.token(), id=fixture.TARGET_ID), survivor])
        wrong_total = inventory.Summary(summary.text, {**summary.counts, "cards": 2}, summary.changed, summary.extra)
        wrong_extra = inventory.Summary(summary.text, summary.counts, summary.changed, {**summary.extra, "removed_token_row_id": True})
        for result in ((wrong_id, summary), (kept_target, summary), (after, wrong_total), (after, wrong_extra)):
            with self.subTest(result=result), mock.patch.object(activity_undo.saving, "apply_op", return_value=result):
                self.refused(503, self.apply, expect=preview["expect"])

    def test_corrupt_backend_token_identity_never_reaches_page(self):
        for identity in (None, True, 0, -1, 10 ** 18, "7"):
            plan = self.case.review()
            plan["token_row_id"] = identity
            with self.subTest(identity=identity), mock.patch.object(activity_undo.inventory, "undo_review", return_value=plan):
                self.refused(503, self.view)
