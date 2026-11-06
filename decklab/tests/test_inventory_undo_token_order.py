"""Undo sorted token-card edits with the real position allocator and disposable audit facts."""
import copy

from decklab.lib import inventory
from decklab.lib.inventory import pg, undo, undo_token_edit as edit
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests.test_inventory_undo_token_delete import token
from decklab.tests.test_inventory_undo_token_edit import TokenEditFixture


class TokenOrderUndoTests(TokenEditFixture):
    def test_one_value_edit_and_position_only_survivors_restore_together(self):
        self.seed_reordered()
        source = copy.deepcopy(self.store.audit[fixture.CHANGE_ID])
        self.assertEqual(len(source), 3)
        self.assertEqual(sum(row["before"]["front_collector_number"] != row["after"]["front_collector_number"]
                             for row in source), 1)
        plan = self.review()
        self.assertEqual((plan["action"], plan["row_count"]), (edit.ACTION, 1))
        self.assertEqual([row["token_row_id"] for row in plan["rows"]], [9])
        self.assertEqual(plan["rows"][0]["fields"],
                         [{"field": "front_collector_number", "before": "0", "after": "4"}])
        actual = []
        def capture(after, made, layout):
            actual.extend(copy.deepcopy(made))
            return after, made, layout
        self.mutate = capture
        after, summary = self.run_undo(plan["expect"])
        self.assertEqual(self.stock(), self.historical_stock)
        self.assertEqual([row.id for row in after.token_set("home").rows], [7, 8, 9])
        self.assertEqual(summary.extra["restored_token_row_ids"], [9])
        self.assertEqual(summary.counts["edited"], 1)
        self.assertEqual(self.store.audit[fixture.CHANGE_ID], source)
        self.assertEqual(len(self.store.writes), 1)
        current_positions = {row["after"]["id"]: row["after"]["position"] for row in source}
        expected = pg._positions([7, 8, 9], current_positions)
        self.assertEqual(self.layout, [{"id": rid, "position": position} for rid, position in zip([7, 8, 9], expected)])
        expected_ids = {rid for rid, position in zip([7, 8, 9], expected) if current_positions[rid] != position} | {9}
        self.assertEqual({row["key"]["id"] for row in actual}, expected_ids)

    def test_inverse_can_update_a_position_only_row_absent_from_the_source(self):
        self.seed_reordered(edits={8: {"front_collector_number": "0"}}, positions={7: 1024, 8: 2048, 9: 3072})
        source = self.store.audit[fixture.CHANGE_ID]
        self.assertEqual([row["key"]["id"] for row in source], [8])
        made = []
        def capture(after, actual, layout):
            made.extend(copy.deepcopy(actual))
            return after, actual, layout
        self.mutate = capture
        plan = self.review()
        self.assertEqual([row["token_row_id"] for row in plan["rows"]], [8])
        self.run_undo(plan["expect"])
        self.assertEqual(self.stock(), self.historical_stock)
        self.assertEqual({row["key"]["id"] for row in made}, {7, 8})
        survivor = next(row for row in made if row["key"]["id"] == 7)
        self.assertEqual({key: value for key, value in survivor["before"].items() if key != "position"},
                         {key: value for key, value in survivor["after"].items() if key != "position"})
        self.assertNotEqual(self.layout, self.historical_layout)

    def test_two_value_edits_are_reviewed_without_the_positional_survivor(self):
        self.seed_reordered(edits={9: {"front_collector_number": "0"}, 8: {"notes": "New verified note"}})
        plan = self.review()
        self.assertEqual(plan["row_count"], 2)
        self.assertEqual({row["token_row_id"] for row in plan["rows"]}, {8, 9})
        self.run_undo(plan["expect"])
        self.assertEqual(self.stock(), self.historical_stock)

    def test_an_inverse_renumbering_fifty_rows_is_bounded_even_with_a_single_source_row(self):
        for count in (50, 51):
            with self.subTest(count=count):
                rows = [token("Beast", "", quantity=1, front_collector_number=f"{index + 1:03}",
                              notes="single-sided verified") for index in range(count)]
                positions = {7 + index: index + 2 for index in range(count)}
                self.seed_reordered(olds=rows, edits={8: {"front_collector_number": "0"}}, positions=positions)
                self.assertEqual(len(self.store.audit[fixture.CHANGE_ID]), 1)
                if count == 50:
                    plan = self.review()
                    self.assertEqual(len(plan["proof"]["rows"]), 50)
                    self.run_undo(plan["expect"])
                    self.assertEqual(self.stock(), self.historical_stock)
                else:
                    before = len(self.store.writes)
                    with self.assertRaises(edit.Refused) as caught:
                        self.review()
                    self.assertIn("more than 50", str(caught.exception))
                    self.assertEqual(len(self.store.writes), before)

    def test_equal_sort_keys_cannot_silently_reverse_historical_tie_order(self):
        row = token("Beast", "", quantity=2, notes="pairing unconfirmed")
        self.seed_reordered(olds=[row, {**row, "quantity": 3}], edits={7: {"front_details": "3/3"}})
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review()
        self.assertEqual(str(caught.exception), edit.UNSAFE)
        self.assertEqual(self.store.writes, [])

    def test_later_touched_changed_or_missing_positional_survivor_refuses_whole_change(self):
        def touched():
            self.touched[7] += 10
        def changed():
            self.store.snapshot = self.store.snapshot.with_tokens("home", [
                row.replace(notes="Changed since") if row.id == 7 else row for row in self.store.snapshot.token_set("home").rows])
        def removed():
            self.store.snapshot = self.store.snapshot.with_tokens("home", [
                row for row in self.store.snapshot.token_set("home").rows if row.id != 7])
            self.layout = [row for row in self.layout if row["id"] != 7]
        for mutate in (touched, changed, removed):
            with self.subTest(mutate=mutate.__name__):
                self.seed_reordered()
                mutate()
                with self.assertRaises(inventory.Invalid):
                    self.review()
                self.assertEqual(self.store.writes, [])

    def test_any_later_token_change_or_unreadable_whole_space_fence_refuses(self):
        self.seed_reordered()
        self.store.latest += 1
        with self.assertRaises(undo.UndoConflict):
            self.review()
        self.seed_reordered()
        self.store.undo_token_latest = None
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_incomplete_or_impossible_source_positions_refuse_without_facts_in_the_error(self):
        def missing(rows):
            rows[:] = [row for row in rows if row["key"]["id"] != 7]
        def duplicate(rows):
            rows[0]["before"]["position"] = rows[1]["before"]["position"]
        def corrupt(rows):
            rows[0]["before"]["position"] = 0
        def noninteger(rows):
            rows[0]["before"]["position"] = True
        for mutate in (missing, duplicate, corrupt, noninteger):
            with self.subTest(mutate=mutate.__name__):
                self.seed_reordered()
                mutate(self.store.audit[fixture.CHANGE_ID])
                with self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)) as caught:
                    self.review()
                for word in ("Angel", "Treasure", "Beast", "Paired", "tst"):
                    self.assertNotIn(word, str(caught.exception))
                self.assertEqual(self.store.writes, [])

    def test_moved_source_requires_complete_packing_even_for_unheld_cards(self):
        self.seed_reordered()
        self.built(None)
        with self.assertRaises(undo.UndoConflict):
            self.review()
        self.assertEqual(self.store.writes, [])

    def test_restoring_sort_order_cannot_move_a_packed_card_to_another_printing(self):
        rows = [token("Beast", "", quantity=3, front_collector_number=str(number), notes="single-sided verified")
                for number in (1, 2)]
        self.seed_reordered(olds=rows, edits={7: {"front_collector_number": "9"}})
        self.built("1 Beast")
        with self.assertRaises(inventory.Invalid):
            self.review()
        self.assertEqual(self.store.writes, [])

    def test_preserving_a_packed_survivor_and_other_space_is_supported(self):
        self.store.snapshot = self.store.snapshot.with_tokens("user2", [self.zombie(rid=81)])
        other = self.store.snapshot.token_set("user2")
        self.seed_reordered(survivors=(self.zombie(),))
        self.built("1 Zombie // Zombie Knight")
        self.run_undo()
        self.assertEqual(self.stock(), self.historical_stock)
        self.assertEqual(self.store.snapshot.token_set("user2"), other)

    def test_a_changed_preview_or_layout_never_writes(self):
        self.seed_reordered()
        expect = self.review()["expect"]
        self.layout[0]["position"] += 1
        with self.assertRaises(inventory.Invalid):
            self.run_undo(expect)
        self.assertEqual(self.store.writes, [])
        self.seed_reordered()
        expect = self.review()["expect"]
        self.store.snapshot = self.store.snapshot.replace(revision=self.store.snapshot.revision + "-changed")
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect)
        self.assertEqual(self.store.writes, [])

    def test_actual_position_audit_or_saved_layout_drift_rolls_back(self):
        def actual_position(after, actual, layout):
            actual[0]["after"]["position"] += 1
            return after, actual, layout
        def missing_audit(after, actual, layout):
            return after, actual[:-1], layout
        def extra_audit(after, actual, layout):
            return after, [*actual, copy.deepcopy(actual[0])], layout
        def saved_layout(after, actual, layout):
            layout[0]["position"] += 1
            return after, actual, layout
        for mutate in (actual_position, missing_audit, extra_audit, saved_layout):
            with self.subTest(mutate=mutate.__name__):
                self.seed_reordered()
                before, layout = self.store.snapshot, copy.deepcopy(self.layout)
                self.mutate = mutate
                with self.assertRaises(undo.UndoConflict) as caught:
                    self.run_undo()
                self.assertEqual(str(caught.exception), edit.UNCONFIRMED)
                self.assertEqual(self.store.snapshot, before)
                self.assertEqual(self.layout, layout)
                self.assertEqual(self.store.writes, [])

    def test_a_moved_source_in_another_space_stays_missing(self):
        self.seed_reordered(space="user2")
        with self.assertRaises(undo.UndoMissing):
            inventory.undo_review(fixture.CHANGE_ID, "home", self.store.snapshot)
        self.store.undo_token_latest.assert_not_called()
