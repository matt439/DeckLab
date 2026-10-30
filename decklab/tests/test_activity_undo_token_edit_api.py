"""Activity restores 1-50 edited token-card rows of one change in place, for that space's own token editors only."""
import copy
import json
from unittest import mock

from decklab.lib import access
from decklab.lib.api import activity_undo as api, guard, saving
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, undo_token_edit as edit
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests.test_inventory_undo_token_batch import batch_rows
from decklab.tests.test_inventory_undo_token_edit import TokenEditFixture

PACKET = {"available", "id", "expect", "kind", "space", "label", "action", "row_count", "rows"}
USER2 = {"profile": "user2", "email": "user2@example.com", "remote": True}


class TokenEditApiTests(TokenEditFixture):
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

    def test_packet_lists_every_rows_current_and_restored_values_and_stable_id_without_writing(self):
        answer = self.view()
        self.assertEqual(set(answer), PACKET)
        self.assertEqual((answer["action"], answer["row_count"], answer["label"], answer["kind"], answer["space"]),
                         (edit.ACTION, 3, "Updates to 3 token-card rows", "tokens", "home"))
        self.assertEqual([item["current"] for item in answer["rows"]], self.rows)
        self.assertEqual([item["restored"] for item in answer["rows"]], self.olds)
        self.assertEqual([item["token_row_id"] for item in answer["rows"]], [7, 8, 9])
        self.assertEqual([set(item) for item in answer["rows"]], [{"label", "token_row_id", "current", "restored", "fields"}] * 3)
        self.assertEqual(answer["rows"][1]["fields"], [{"field": "front_details", "before": "", "after": "1/1; colourless"}])
        self.assertNotIn("proof", json.dumps(answer))
        self.assertEqual(self.store.writes, [])

    def test_one_row_packet_uses_singular_words(self):
        self.seed(batch_rows(1), [{**batch_rows(1)[0], "front_details": "4/4; white; flying"}])
        answer = self.view()
        self.assertEqual((answer["row_count"], answer["label"]), (1, "Updates to 1 token-card row"))

    def test_save_returns_every_restored_row_by_id_and_a_replay_refuses(self):
        self.seed(survivors=(self.zombie(),))
        preview = self.view()
        answer = self.apply(expect=preview["expect"])
        self.assertEqual(set(answer), {"saved", "source_id", "expect", "kind", "space", "action", "row_count",
                                       "restored_rows", "sha256", "revision", "summary"})
        self.assertEqual(answer["restored_rows"], [{"token_row_id": 7 + index, "row": old} for index, old in enumerate(self.olds)])
        self.assertEqual((answer["row_count"], answer["action"], answer["source_id"]), (3, edit.ACTION, fixture.CHANGE_ID))
        self.assertEqual(answer["sha256"], files.rendered_sha256(self.store.snapshot.token_set("home")))
        op, actor, message, summary, reason = self.store.writes[0]
        self.assertEqual(dict(op.params), {"change_id": fixture.CHANGE_ID, "space": "home", "expect": preview["expect"]})
        self.assertEqual((actor.id, reason), ("matt", None))
        self.refused(400, self.apply, expect=preview["expect"])  # Its source rows were touched since.
        self.assertEqual(len(self.store.writes), 1)

    def test_a_reason_an_ownership_flag_or_a_stale_receipt_refuse_before_any_write(self):
        preview = self.view()
        with mock.patch.object(saving, "apply_op", side_effect=AssertionError("No write entry point")):
            for extra in ({"reason": "Because"}, {"confirm_owned": True}):
                with self.subTest(extra=extra):
                    self.refused(400, self.apply, expect=preview["expect"], **extra)
            self.refused(400, self.apply, expect="short")
            self.refused(409, self.apply)
        self.assertEqual(self.store.writes, [])

    def test_an_unproved_backend_result_is_never_reported_as_saved(self):
        preview = self.view()
        self.store.apply = fixture.AuditInventory.apply.__get__(self.store)  # No transaction-local proof.
        self.refused(503, self.apply, expect=preview["expect"])

    def test_too_large_or_ineligible_changes_say_how_many_and_why(self):
        self.seed(batch_rows(51))
        answer = self.view()
        self.assertEqual(set(answer), {"available", "id", "reason"})
        self.assertIn("51 token-card rows", answer["reason"])
        self.assertIn("at most 50", self.refused(400, self.apply).message)
        self.seed()
        self.built("2 Beast // Dog")
        answer = self.view()
        self.assertIn("1 of the 3 updated token-card rows can't be restored", answer["reason"])
        self.assertIn(edit.PACKED + ": 1", answer["reason"])
        for word in ("Beast", "fixture", "Recorded", "colourless"):
            self.assertNotIn(word, answer["reason"])
        self.assertEqual(self.store.writes, [])

    def test_another_spaces_change_is_missing_to_the_admin_and_restored_only_for_its_member(self):
        self.store.snapshot = self.store.snapshot.with_tokens("home", [self.zombie()])
        self.seed(space="user2")
        self.refused(404, self.view)        # Matt (admin) can't see user2's edits
        self.refused(404, self.apply)
        self.seed(batch_rows(51), space="user2")
        self.refused(404, self.view)        # nor how many there were
        self.seed(space="user2")
        with access.using(USER2):
            preview = self.view()
            self.assertEqual(preview["space"], "user2")
            self.assertNotIn("Zombie", json.dumps(preview))
            answer = self.apply(profile="user2", expect=preview["expect"])
        self.assertEqual((answer["space"], answer["row_count"]), ("user2", 3))
        self.assertEqual([row.id for row in self.store.snapshot.token_set("home").rows], [80])
        self.seed()
        with access.using(USER2):
            self.refused(404, self.view)
        self.assertEqual(len(self.store.writes), 1)

    def test_one_hidden_row_hides_the_whole_change_with_no_details(self):
        self.store.audit[fixture.CHANGE_ID][1]["after"].update(space_id="user2", notes="Private audit note")
        error = self.refused(404, self.view)
        self.assertEqual((error.message, error.extra), (api.NO_CHANGE, {}))

    def test_hint_offers_review_only_for_whole_own_space_token_edits(self):
        rows = copy.deepcopy(self.store.audit[fixture.CHANGE_ID])
        change = {"id": fixture.CHANGE_ID, "total": 3, "rows": rows}
        shown = {"id": fixture.CHANGE_ID}
        self.assertEqual(api.review_hint(change, shown, guard.viewer()), {"review": True})
        self.assertEqual(api.review_hint({**change, "total": 60, "more": 57}, shown, guard.viewer()), {"review": True})
        hidden, moved = copy.deepcopy(rows), copy.deepcopy(rows)
        hidden[2]["after"]["space_id"] = "user2"
        moved[1]["after"]["position"] += 1
        for other in ({**change, "total": 4}, {**change, "groups": [{"table": "token_card"}]}, {**change, "rows": hidden},
                      {**change, "rows": moved}, {**change, "rows": rows[:2] + [{**rows[2], "table": "collection_card"}]}):
            self.assertIsNone(api.review_hint(other, shown, guard.viewer()))
        self.assertIsNone(api.review_hint(change, {"id": 1}, guard.viewer()))
        with access.using(USER2):
            self.assertIsNone(api.review_hint(change, shown, guard.viewer()))

    def test_projection_refuses_malformed_rows_or_counts(self):
        plan = self.review()
        mutations = [lambda p: p.update(row_count=51), lambda p: p.update(label="x"), lambda p: p.update(kind="collection"),
                     lambda p: p["rows"].pop(), lambda p: p.update(expect="short"),
                     lambda p: p["rows"][1].update(token_row_id=p["rows"][0]["token_row_id"]),
                     lambda p: p["rows"][0].update(token_row_id=True),
                     lambda p: p["rows"][0]["current"].update(quantity=True),
                     lambda p: p["rows"][0]["restore"].update(id=7),
                     lambda p: p["rows"][0].update(fields=[]),
                     lambda p: p["rows"][0]["fields"].reverse(),
                     lambda p: p["rows"][0].update(restore=dict(p["rows"][0]["current"])),
                     lambda p: p["rows"][2].update(label="Beast")]
        for mutate in mutations:
            changed = copy.deepcopy(plan)
            mutate(changed)
            with self.subTest(changed=changed):
                self.refused(503, api._project, changed)
