"""Activity removes 2-50 added token cards of one change together, only with a reason and by stable id."""
import copy
import json
from unittest import mock

from decklab.lib import access
from decklab.lib.api import activity_undo as api, guard, saving
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, undo_token_batch_remove as batch
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests.test_inventory_undo_token_batch import batch_rows
from decklab.tests.test_inventory_undo_token_batch_insert import REASON, TokenBatchInsertFixture

PACKET = {"available", "id", "expect", "kind", "space", "label", "action", "row_count", "rows", "cards", "reason_required"}


class TokenBatchInsertApiTests(TokenBatchInsertFixture):
    def view(self):
        return api.undo_view(id=str(fixture.CHANGE_ID))

    def apply(self, profile="matt", **extra):
        return api.apply_undo(json.dumps({"profile": profile, "id": fixture.CHANGE_ID,
                                          "expect": "0" * 64, **extra}).encode())

    def refused(self, status, call, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)
        return caught.exception

    def test_packet_lists_every_current_row_its_stable_id_and_the_whole_count_without_writing(self):
        answer = self.view()
        self.assertEqual(set(answer), PACKET)
        self.assertEqual((answer["action"], answer["row_count"], answer["cards"], answer["label"], answer["reason_required"]),
                         (batch.ACTION, 3, 6, "3 added token-card rows", True))
        self.assertEqual([item["current"] for item in answer["rows"]], self.added)
        self.assertEqual([item["token_row_id"] for item in answer["rows"]], [7, 8, 9])
        self.assertEqual([set(item) for item in answer["rows"]], [{"label", "token_row_id", "current"}] * 3)
        self.assertNotIn("proof", answer)
        self.assertEqual(self.store.writes, [])

    def test_reasoned_save_returns_every_removed_id_and_records_the_reason(self):
        self.seed(survivors=(self.zombie(),))
        preview = self.view()
        answer = self.apply(expect=preview["expect"], reason="  " + REASON + "  ")
        self.assertEqual(set(answer), {"saved", "source_id", "expect", "kind", "space", "action", "row_count",
                                       "removed_token_row_ids", "restored", "sha256", "revision", "summary"})
        self.assertEqual((answer["removed_token_row_ids"], answer["restored"], answer["row_count"]), ([7, 8, 9], None, 3))
        self.assertEqual([row.id for row in self.store.snapshot.token_set("home").rows], [80])
        self.assertEqual(answer["sha256"], files.rendered_sha256(self.store.snapshot.token_set("home")))
        op, actor, message, summary, reason = self.store.writes[0]
        self.assertEqual(dict(op.params), {"change_id": fixture.CHANGE_ID, "space": "home", "expect": preview["expect"],
                                           "reason": REASON})
        self.assertEqual((actor.id, reason, summary.extra["undo_reason"]), ("matt", REASON, REASON))
        self.refused(400, self.apply, expect=preview["expect"], reason=REASON)  # Its source rows were touched since.
        self.assertEqual(len(self.store.writes), 1)

    def test_missing_reason_an_ownership_flag_and_a_stale_receipt_refuse_before_any_write(self):
        preview = self.view()
        with mock.patch.object(saving, "apply_op", side_effect=AssertionError("No write entry point")):
            for extra in ({}, {"reason": " "}, {"reason": "x" * 201}, {"reason": REASON, "confirm_owned": True}):
                with self.subTest(extra=extra):
                    self.refused(400, self.apply, expect=preview["expect"], **extra)
            self.refused(409, self.apply, expect="0" * 64, reason=REASON)
        self.assertEqual(self.store.writes, [])

    def test_an_unproved_backend_result_is_never_reported_as_saved(self):
        preview = self.view()
        self.store.apply = fixture.AuditInventory.apply.__get__(self.store)  # No transaction-local proof.
        self.refused(503, self.apply, expect=preview["expect"], reason=REASON)

    def test_too_large_or_ineligible_batches_say_how_many_and_why(self):
        self.seed(batch_rows(51))
        answer = self.view()
        self.assertEqual(set(answer), {"available", "id", "reason"})
        self.assertIn("51 token-card rows", answer["reason"])
        self.assertIn("at most 50", self.refused(400, self.apply, expect="0" * 64, reason=REASON).message)
        self.seed()
        self.built("1 Treasure")
        answer = self.view()
        self.assertIn("1 of the 3 added token-card rows can't be removed", answer["reason"])
        self.assertIn(batch.PACKED + ": 1", answer["reason"])
        self.assertNotIn("Treasure", answer["reason"])
        self.assertNotIn("fixture", answer["reason"].lower())
        self.assertEqual(self.store.writes, [])

    def test_another_spaces_batch_is_missing_to_the_admin_and_removed_only_for_its_member(self):
        self.store.snapshot = self.store.snapshot.with_tokens("home", [self.zombie()])
        self.seed(space="user2")
        self.refused(404, self.view)        # Matt (admin) can't see user2's additions
        self.refused(404, self.apply, expect="0" * 64, reason=REASON)
        self.seed(batch_rows(51), space="user2")
        self.refused(404, self.view)        # nor how many there were
        self.seed(space="user2")
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            preview = self.view()
            self.assertEqual(preview["space"], "user2")
            self.assertNotIn("Zombie", json.dumps(preview))
            answer = self.apply(profile="user2", expect=preview["expect"], reason=REASON)
        self.assertEqual((answer["space"], answer["row_count"]), ("user2", 3))
        self.assertEqual([row.id for row in self.store.snapshot.token_set("home").rows], [80])
        self.seed()
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            self.refused(404, self.view)
        self.assertEqual(len(self.store.writes), 1)

    def test_one_hidden_row_hides_the_whole_change_with_no_details(self):
        self.store.audit[fixture.CHANGE_ID][1]["after"].update(space_id="user2", notes="Private audit note")
        error = self.refused(404, self.view)
        self.assertEqual((error.message, error.extra), (api.NO_CHANGE, {}))

    def test_hint_offers_review_only_for_whole_own_space_token_additions(self):
        rows = copy.deepcopy(self.store.audit[fixture.CHANGE_ID])
        change = {"id": fixture.CHANGE_ID, "total": 3, "rows": rows}
        shown = {"id": fixture.CHANGE_ID}
        self.assertEqual(api.review_hint(change, shown, guard.viewer()), {"review": True})
        self.assertEqual(api.review_hint({**change, "total": 60, "more": 57}, shown, guard.viewer()), {"review": True})
        hidden = copy.deepcopy(rows)
        hidden[2]["after"]["space_id"] = "user2"
        for other in ({**change, "total": 4}, {**change, "groups": [{"table": "token_card"}]}, {**change, "rows": hidden},
                      {**change, "rows": rows[:1] + [{**rows[1], "op": "DELETE", "before": rows[1]["after"], "after": None}] + rows[2:]}):
            self.assertIsNone(api.review_hint(other, shown, guard.viewer()))
        self.assertIsNone(api.review_hint(change, {"id": 1}, guard.viewer()))

    def test_projection_refuses_malformed_rows_or_counts(self):
        plan = self.review()
        mutations = [lambda p: p.update(reason_required=False), lambda p: p.update(row_count=51), lambda p: p.update(cards=7),
                     lambda p: p.update(label="x"), lambda p: p["rows"].pop(),
                     lambda p: p["rows"][1].update(row_change_id=p["rows"][0]["row_change_id"]),
                     lambda p: p["rows"][1].update(token_row_id=p["rows"][0]["token_row_id"]),
                     lambda p: p["rows"][0].update(token_row_id=True),
                     lambda p: p["rows"][0]["current"].update(quantity=True),
                     lambda p: p["rows"][0]["current"].update(id=7), lambda p: p["rows"][2].update(label="Beast")]
        for mutate in mutations:
            changed = copy.deepcopy(plan)
            mutate(changed)
            with self.subTest(changed=changed):
                self.refused(503, api._project, changed)
