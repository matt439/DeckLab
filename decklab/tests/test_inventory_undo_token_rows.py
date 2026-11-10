"""Whole token row changes with position-only survivors; temporary snapshots and fake audit only."""
import copy
import json
from unittest import mock

from decklab.lib import access, api
from decklab.lib.inventory import model, undo, undo_token_layout
from decklab.lib.state import Invalid
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests.test_inventory_undo_token_batch import TokenBatchFixture, batch_rows
from decklab.tests.test_inventory_undo_token_batch_insert import REASON, TokenBatchInsertFixture


def source(case, before, positions):
    stock = [{"id": row.id, "row": {**row.as_dict(), "quantity": int(row.quantity)}}
             for row in case.store.snapshot.token_set(case.space).rows]
    audit, case.layout = undo_token_layout.expected(before, positions, stock, case.space)
    raw = [{**item, "id": fixture.ROW_ID + index} for index, item in enumerate(audit)]
    case.store.audit[fixture.CHANGE_ID] = raw
    case.store.latest = case.latest = max(item["id"] for item in raw)
    case.touched = {item["key"]["id"]: item["id"] for item in raw}
    case.store.undo_token_latest = mock.Mock(side_effect=lambda space: case.store.latest)
    return copy.deepcopy(raw)


class AddedWithMovesTests(TokenBatchInsertFixture):
    def seed_moved(self):
        rows = batch_rows()
        self.seed(rows=[rows[1]], survivors=(model.TokenRow.make(rows[0], id=80), model.TokenRow.make(rows[2], id=81)))
        before = [{"id": 80, "row": rows[0]}, {"id": 81, "row": rows[2]}]
        return source(self, before, [{"id": 80, "position": 0}, {"id": 81, "position": 1}])

    def test_one_added_card_with_two_survivor_moves_is_reviewed_and_removed_as_one_change(self):
        original = self.seed_moved()
        self.assertEqual([row["op"] for row in original[:2]], ["UPDATE", "UPDATE"])
        plan = self.review()
        self.assertEqual((plan["action"], plan["row_count"], plan["label"]), ("token_batch_remove", 1, "1 added token-card row"))
        self.assertEqual([item["token_row_id"] for item in plan["rows"]], [7])
        after, summary = self.run_undo(reason=REASON)
        self.assertEqual([row.id for row in after.token_set("home").rows], [80, 81])
        self.assertEqual(summary.extra["removed_token_row_ids"], [7])
        self.assertEqual(self.store.audit[fixture.CHANGE_ID], original)
        self.assertEqual(len(self.store.writes), 1)

    def test_latest_fence_and_hidden_position_row_refuse_without_any_partial_write(self):
        self.seed_moved()
        self.store.latest += 1
        with self.assertRaises(undo.UndoConflict):
            self.review()
        self.seed_moved()
        self.store.audit[fixture.CHANGE_ID][0]["before"]["space_id"] = "user2"
        with self.assertRaises(undo.UndoMissing):
            self.review()
        self.assertEqual(self.store.writes, [])

    def test_api_uses_same_reason_contract_and_never_projects_position_or_survivor_rows(self):
        self.seed_moved()
        with access.using(None), access.viewing("matt"), access.answering(False):
            shown = api.activity_undo.undo_view(str(fixture.CHANGE_ID))
            self.assertEqual(shown["row_count"], 1)
            self.assertEqual(set(shown["rows"][0]), {"label", "token_row_id", "current"})
            self.assertNotIn("position", str(shown))
            answer = api.activity_undo.apply_undo(json.dumps({"profile": "matt", "id": fixture.CHANGE_ID,
                                                             "expect": shown["expect"], "reason": REASON}).encode())
        self.assertTrue(answer["saved"])
        self.assertEqual(answer["removed_token_row_ids"], [7])

    def test_unexpected_survivor_position_change_rolls_back_the_entire_inverse(self):
        original = self.seed_moved()
        before, old_layout = self.store.snapshot, copy.deepcopy(self.layout)
        def wrong(after, actual, layout):
            source_move = next(row for row in original if row["key"] == {"id": 80})
            move = {**copy.deepcopy(source_move), "before": copy.deepcopy(source_move["after"])}
            move["after"]["position"] += 1
            actual.append(move)
            layout[0]["position"] += 1
            return after, actual, layout
        self.mutate = wrong
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(reason=REASON)
        self.assertEqual((self.store.snapshot, self.layout, self.store.writes), (before, old_layout, []))


class DeletedWithMovesTests(TokenBatchFixture):
    def seed_moved(self):
        rows = batch_rows()
        self.seed_batch(rows=[rows[1]], survivors=(model.TokenRow.make(rows[0], id=80), model.TokenRow.make(rows[2], id=81)))
        before = [{"id": 71, "row": rows[1]}, {"id": 81, "row": rows[2]}, {"id": 80, "row": rows[0]}]
        return source(self, before, [{"id": item["id"], "position": (index + 1) * 1024} for index, item in enumerate(before)])

    def test_deleted_row_with_sorted_survivor_is_restored_under_a_fresh_id_after_whole_count_confirmation(self):
        original = self.seed_moved()
        plan = self.review()
        self.assertEqual((plan["action"], plan["row_count"], plan["label"]), ("token_batch_add", 1, "1 deleted token-card row"))
        with self.assertRaises(Invalid):
            self.run_undo()
        after, summary = self.run_undo(confirm_owned=True)
        fresh, = summary.extra["added_token_row_ids"]
        self.assertNotIn(fresh, (71, 80, 81))
        self.assertEqual(set(row.id for row in after.token_set("home").rows), {80, 81, fresh})
        self.assertEqual(self.store.audit[fixture.CHANGE_ID], original)

    def test_api_has_same_ownership_confirmation_and_all_or_nothing_fresh_row_receipt(self):
        self.seed_moved()
        with access.using(None), access.viewing("matt"), access.answering(False):
            shown = api.activity_undo.undo_view(str(fixture.CHANGE_ID))
            self.assertEqual(shown["row_count"], 1)
            self.assertEqual(set(shown["rows"][0]), {"label", "restored"})
            answer = api.activity_undo.apply_undo(json.dumps({"profile": "matt", "id": fixture.CHANGE_ID,
                                                             "expect": shown["expect"], "confirm_owned": True}).encode())
        self.assertTrue(answer["saved"])
        self.assertEqual(answer["row_count"], 1)
        self.assertEqual(answer["restored_rows"], [batch_rows()[1]])

    def test_restore_from_one_plain_delete_may_renumber_dense_survivors_under_exact_proof(self):
        rows = batch_rows()
        self.seed_batch(rows=[rows[1]], survivors=(model.TokenRow.make(rows[0], id=80), model.TokenRow.make(rows[2], id=81)))
        self.layout = [{"id": 80, "position": 0}, {"id": 81, "position": 1}]
        # This standalone historical DELETE keeps the existing single-row API protocol.
        self.assertEqual(self.review()["action"], "token_add")
        after, summary = self.run_undo(confirm_owned=True)
        self.assertEqual(len(after.token_set("home").rows), 3)
        self.assertNotEqual([item for item in self.layout if item["id"] in (80, 81)],
                            [{"id": 80, "position": 0}, {"id": 81, "position": 1}])
        self.assertIsInstance(summary.extra["added_token_row_id"], int)
