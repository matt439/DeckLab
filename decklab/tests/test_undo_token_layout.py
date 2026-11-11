"""Position-only survivor proofs use synthetic rows and the real position allocator."""
import copy
from types import SimpleNamespace
import unittest

from decklab.lib.inventory import rules, undo_token_layout as layout
from decklab.lib.inventory.undo import UndoConflict, UndoMissing, UndoUnsupported


def card(number):
    return {**dict.fromkeys(rules.TOKEN_FIELDS, ""), "front": "Fixture token", "set": "tst",
            "front_collector_number": str(number), "finish": "nonfoil", "quantity": 1}


class LayoutTests(unittest.TestCase):
    def insertion(self):
        before = [{"id": 1, "row": card(10)}, {"id": 2, "row": card(20)}]
        positions = [{"id": 1, "position": 0}, {"id": 2, "position": 1}]
        after = [before[0], {"id": 3, "row": card(15)}, before[1]]
        audit, saved = layout.expected(before, positions, after, "home")
        raw = [{**item, "id": 80 + index} for index, item in enumerate(audit)]
        touched = {item["key"]["id"]: item["id"] for item in raw}
        store = SimpleNamespace(undo_token_latest=lambda space: max(touched.values()),
                                undo_latest=lambda table, key: touched.get(key["id"]),
                                undo_audit_rows=lambda change: raw)
        return raw, after, saved, store

    def test_dense_insertion_source_proves_target_and_every_position_only_survivor(self):
        raw, stock, positions, store = self.insertion()
        before = copy.deepcopy((raw, stock, positions))
        self.assertEqual(layout.looks_like(store, 1, "home", raw[:2]), "INSERT")
        targets, moves = layout.split(raw, "home", "INSERT")
        self.assertEqual(len(targets), 1)
        self.assertEqual(len(moves), 2)
        proof = layout.source_proof(raw, stock, positions, "home", store)
        self.assertEqual(proof["source"], raw)
        self.assertEqual((raw, stock, positions), before)

    def test_missing_survivor_wrong_position_or_later_touch_cannot_pass_source_proof(self):
        raw, stock, positions, store = self.insertion()
        for wrong in (raw[:-1], [{**raw[0], "before": {**raw[0]["before"], "position": 1}}, *raw[1:]]):
            with self.subTest(source=wrong), self.assertRaises(UndoConflict):
                layout.source_proof(wrong, stock, positions, "home", store)
        store.undo_token_latest = lambda space: 1000
        with self.assertRaises(UndoConflict):
            layout.source_proof(raw, stock, positions, "home", store)

    def test_hidden_source_is_missing_before_count_or_shape_errors_and_value_edits_are_not_moves(self):
        raw, stock, positions, store = self.insertion()
        hidden = copy.deepcopy(raw)
        hidden[0]["after"]["space_id"] = "user2"
        with self.assertRaises(UndoMissing):
            layout.split(hidden * 60, "home", "INSERT")
        store.undo_audit_rows = lambda change: hidden
        with self.assertRaises(UndoMissing):
            layout.looks_like(store, 1, "home", raw[:2])
        changed = copy.deepcopy(raw)
        changed[0]["after"]["notes"] = "Value edit cannot masquerade as position metadata"
        with self.assertRaises(UndoUnsupported):
            layout.split(changed, "home", "INSERT")

    def test_inverse_predicts_exact_fresh_insert_and_allocator_moves_and_refuses_extra_audit(self):
        raw, before, positions, _ = self.insertion()
        # Remove the middle row, then restore its facts under a fresh database id.
        current = [before[0], before[2]]
        current_positions = [{"id": 1, "position": 0}, {"id": 2, "position": 1}]
        restored = [before[0], {"id": 99, "row": card(15)}, before[2]]
        expected, saved = layout.expected(current, current_positions, restored, "home")
        self.assertEqual({item["op"] for item in expected}, {"INSERT", "UPDATE"})
        self.assertEqual([item["id"] for item in saved], [1, 99, 2])
        actual = [{**copy.deepcopy(item), "id": index + 100} for index, item in enumerate(expected)]
        self.assertTrue(layout.same_audit(actual, expected))
        self.assertFalse(layout.same_audit([*actual, raw[-1]], expected))
        actual[0]["after"]["notes"] = "Unexpected change"
        self.assertFalse(layout.same_audit(actual, expected))

    def test_fifty_row_bound_includes_allocator_moves_in_addition_to_the_single_physical_target(self):
        for count in (49, 50):
            before = [{"id": index + 1, "row": card(f"{10 + 2 * index:03}")} for index in range(count)]
            positions = [{"id": index + 1, "position": index} for index in range(count)]
            after = [before[0], {"id": 900, "row": card("011")}, *before[1:]]
            with self.subTest(survivors=count):
                if count == 49:
                    expected, _ = layout.expected(before, positions, after, "home")
                    self.assertEqual(len(expected), 50)
                else:
                    with self.assertRaises(ValueError):
                        layout.expected(before, positions, after, "home")
