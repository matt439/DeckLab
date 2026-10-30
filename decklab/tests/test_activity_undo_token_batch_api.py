"""Activity restores 2-50 deleted token cards of one change together, only confirmed and under fresh ids."""
import copy
import json
from unittest import mock

from decklab.lib import access
from decklab.lib.api import activity_undo as api, guard, saving
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, undo_token_batch as batch
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests.test_inventory_undo_token_batch import TokenBatchFixture, batch_rows

PACKET = {"available", "id", "expect", "kind", "space", "label", "action", "row_count", "rows", "cards",
          "identity_policy", "physical_confirmation_required", "packing_restored"}


class TokenBatchApiTests(TokenBatchFixture):
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

    def test_packet_lists_every_historical_row_and_the_whole_count_without_writing(self):
        answer = self.view()
        self.assertEqual(set(answer), PACKET)
        self.assertEqual((answer["action"], answer["row_count"], answer["cards"], answer["label"]),
                         (batch.ACTION, 3, 6, "3 deleted token-card rows"))
        self.assertEqual([item["restored"] for item in answer["rows"]], self.olds)
        self.assertEqual([set(item) for item in answer["rows"]], [{"label", "restored"}] * 3)
        self.assertEqual((answer["identity_policy"], answer["physical_confirmation_required"], answer["packing_restored"]),
                         ("fresh_id", True, False))
        self.assertNotIn("proof", answer)
        self.assertEqual(self.store.writes, [])

    def test_confirmed_save_returns_every_fresh_id_and_its_actual_row(self):
        preview = self.view()
        answer = self.apply(expect=preview["expect"], confirm_owned=True)
        self.assertEqual(set(answer), {"saved", "source_id", "expect", "kind", "space", "action", "row_count",
                                       "added_token_row_ids", "restored_rows", "sha256", "revision", "summary"})
        self.assertEqual(answer["restored_rows"], self.olds)
        self.assertEqual(len(set(answer["added_token_row_ids"])), 3)
        self.assertTrue(set(answer["added_token_row_ids"]).isdisjoint({71, 72, 73}))
        self.assertEqual(answer["sha256"], files.rendered_sha256(self.store.snapshot.token_set("home")))
        op, actor, message, _ = self.store.writes[0]
        self.assertEqual(dict(op.params), {"change_id": fixture.CHANGE_ID, "space": "home", "expect": preview["expect"],
                                           "confirm_owned": True})
        self.assertEqual(actor.id, "matt")
        self.refused(409, self.apply, expect=preview["expect"], confirm_owned=True)
        self.assertEqual(len(self.store.writes), 1)

    def test_missing_confirmation_a_reason_and_a_stale_receipt_refuse_before_any_write(self):
        preview = self.view()
        with mock.patch.object(saving, "apply_op", side_effect=AssertionError("No write entry point")):
            for extra in ({}, {"confirm_owned": False}, {"confirm_owned": True, "reason": "Not a removal"}):
                with self.subTest(extra=extra):
                    self.refused(400, self.apply, expect=preview["expect"], **extra)
            self.refused(409, self.apply, expect="0" * 64, confirm_owned=True)
        self.assertEqual(self.store.writes, [])

    def test_an_unproved_backend_result_is_never_reported_as_saved(self):
        preview = self.view()
        self.store.apply = fixture.AuditInventory.apply.__get__(self.store)  # No transaction-local proof.
        self.refused(503, self.apply, expect=preview["expect"], confirm_owned=True)

    def test_too_large_or_ineligible_batches_say_how_many_and_why(self):
        self.seed_batch(batch_rows(51))
        answer = self.view()
        self.assertEqual(set(answer), {"available", "id", "reason"})
        self.assertIs(answer["available"], False)
        self.assertIn("51 token-card rows", answer["reason"])
        error = self.refused(400, self.apply, expect="0" * 64, confirm_owned=True)
        self.assertIn("at most 50", error.message)
        self.seed_batch()
        self.built("1 Treasure")
        answer = self.view()
        self.assertIn("1 of the 3 deleted token-card rows can't be restored", answer["reason"])
        self.assertNotIn("Treasure", answer["reason"])
        self.assertNotIn("fixture", answer["reason"].lower())
        self.assertEqual(self.store.writes, [])

    def test_another_spaces_batch_is_missing_to_the_admin_and_restores_only_for_its_member(self):
        self.store.snapshot = self.store.snapshot.with_tokens("home", [self.zombie()])
        self.seed_batch(space="user2")
        self.refused(404, self.view)        # Matt (admin) can't see user2's deletions
        self.refused(404, self.apply, expect="0" * 64, confirm_owned=True)
        self.seed_batch(batch_rows(51), space="user2")
        self.refused(404, self.view)        # nor how many there were
        self.seed_batch(space="user2")
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            preview = self.view()
            self.assertEqual(preview["space"], "user2")
            self.assertNotIn("Zombie", json.dumps(preview))
            answer = self.apply(profile="user2", expect=preview["expect"], confirm_owned=True)
        self.assertEqual((answer["space"], answer["row_count"]), ("user2", 3))
        self.assertEqual([row.id for row in self.store.snapshot.token_set("home").rows], [80])
        self.seed_batch()
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            self.refused(404, self.view)
        self.assertEqual(len(self.store.writes), 1)

    def test_one_hidden_row_hides_the_whole_change_with_no_details(self):
        self.store.audit[fixture.CHANGE_ID][1]["before"].update(space_id="user2", notes="Private audit note")
        error = self.refused(404, self.view)
        self.assertEqual((error.message, error.extra), (api.NO_CHANGE, {}))

    def test_hint_offers_review_only_for_whole_own_space_token_deletions(self):
        rows = copy.deepcopy(self.store.audit[fixture.CHANGE_ID])
        change = {"id": fixture.CHANGE_ID, "total": 3, "rows": rows}
        shown = {"id": fixture.CHANGE_ID}
        self.assertEqual(api.review_hint(change, shown, guard.viewer()), {"review": True})
        # More than 50: the capped rows plus "more" still cover the whole change, so its review can say why.
        self.assertEqual(api.review_hint({**change, "total": 60, "more": 57}, shown, guard.viewer()), {"review": True})
        hidden = copy.deepcopy(rows)
        hidden[2]["before"]["space_id"] = "user2"
        for other in ({**change, "total": 4}, {**change, "groups": [{"table": "token_card"}]},
                      {**change, "rows": hidden}, {**change, "rows": rows[:1] + [{**rows[1], "op": "INSERT"}] + rows[2:]}):
            self.assertIsNone(api.review_hint(other, shown, guard.viewer()))
        self.assertIsNone(api.review_hint(change, {"id": 1}, guard.viewer()))

    def test_projection_refuses_weakened_policy_or_malformed_rows(self):
        plan = self.review()
        mutations = [lambda p: p.update(identity_policy="reuse_id"), lambda p: p.update(packing_restored=True),
                     lambda p: p.update(physical_confirmation_required=False), lambda p: p.update(current=None),
                     lambda p: p.update(row_count=51), lambda p: p.update(cards=7), lambda p: p.update(label="x"),
                     lambda p: p["rows"].pop(), lambda p: p["rows"][1].update(row_change_id=p["rows"][0]["row_change_id"]),
                     lambda p: p["rows"][0]["restore"].update(quantity=True),
                     lambda p: p["rows"][0]["restore"].update(notes="line\nline"),
                     lambda p: p["rows"][0]["restore"].update(id=71), lambda p: p["rows"][2].update(label="Beast")]
        for mutate in mutations:
            changed = copy.deepcopy(plan)
            mutate(changed)
            with self.subTest(changed=changed):
                self.refused(503, api._project, changed)
