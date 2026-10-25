"""Bounded token packing identities describe physical work, independent of presentation."""
import copy
import json
import unittest

from decklab.lib.api.assembly_ticks import _ids, token_packing_keys


def row(number):
    return {"front": "Soldier", "back": "Spirit", "set": "tst", "front_collector_number": str(number),
            "back_collector_number": str(number + 1), "finish": "nonfoil", "quantity": "2",
            "front_details": "1/1; white; " + "x" * 280, "back_details": "1/1; blue; " + "y" * 280,
            "notes": "An inspection note"}


def result(count, state="ready"):
    candidates = [{"row": i, "front": "Soldier", "back": "Spirit", "side": "front", "quantity": 2}
                  for i in range(count)]
    return {"needs": [{"key": "soldier-identity", "name": "Soldier", "kind": "token", "state": state,
                       "pt": "1/1", "colors": ["W"], "keywords": [], "words": "Pack a Soldier",
                       "cards": candidates if state in ("ready", "check") else [],
                       "stand_ins": candidates if state == "differs" else []}]}


class TokenPackingKeysTests(unittest.TestCase):
    def key(self, needs, rows):
        return token_packing_keys(needs, rows)["needs"][0]["packing_key"]

    def test_many_long_detail_candidates_produce_one_bounded_browser_context(self):
        rows, needs = [row(i) for i in range(100)], result(100)
        key = self.key(needs, rows)
        self.assertRegex(key, r"^[a-f0-9]{64}$")
        # Exactly the scalar packing_key the page receives fits even for a hundred variants.
        task = json.dumps(["casual/deck:target", "token|soldier-identity", 1, key])
        self.assertEqual(list(_ids([task])), [task])

    def test_neither_cached_input_nor_nested_candidates_are_mutated(self):
        needs, rows = result(2), [row(1), row(3)]
        before_needs, before_rows = copy.deepcopy(needs), copy.deepcopy(rows)
        decorated = token_packing_keys(needs, rows)
        self.assertEqual(needs, before_needs)
        self.assertEqual(rows, before_rows)
        decorated["needs"][0]["cards"][0]["side"] = "back"
        self.assertEqual(needs, before_needs)

    def test_row_order_candidate_order_notes_and_display_words_leave_the_key_unchanged(self):
        rows, needs = [row(1), row(3)], result(2)
        key = self.key(needs, rows)
        rows.reverse()
        needs["needs"][0]["cards"].reverse()
        for candidate in needs["needs"][0]["cards"]:
            candidate["row"] = 1 - candidate["row"]
        rows[0]["notes"] = "A different inspection note"
        needs["needs"][0]["words"] = "Some clearer wording"
        needs["needs"][0]["made_by"] = [{"name": "A new card", "quantity": 3}]
        self.assertEqual(self.key(needs, rows), key)

    def test_each_relevant_physical_fact_invalidates_the_tick(self):
        rows, needs = [row(1)], result(1)
        key = self.key(needs, rows)
        for field, value in (("front", "Knight"), ("back", "Angel"), ("set", "new"),
                             ("front_collector_number", "5"), ("back_collector_number", "6"),
                             ("finish", "foil"), ("quantity", "3"),
                             ("front_details", "2/2; white"), ("back_details", "2/2; blue")):
            with self.subTest(field=field):
                changed = copy.deepcopy(rows)
                changed[0][field] = value
                self.assertNotEqual(self.key(needs, changed), key)
        needs["needs"][0]["cards"][0]["side"] = "back"
        self.assertNotEqual(self.key(needs, rows), key)

    def test_need_identity_state_and_candidate_quantity_are_part_of_the_key(self):
        rows, needs = [row(1), row(3)], result(2)
        key = self.key(needs, rows)
        for field, value in (("key", "another-soldier"), ("state", "check"), ("pt", "2/2"),
                             ("colors", ["B"]), ("keywords", ["flying"])):
            with self.subTest(field=field):
                changed = copy.deepcopy(needs)
                changed["needs"][0][field] = value
                self.assertNotEqual(self.key(changed, rows), key)
        needs["needs"][0]["cards"].pop()
        self.assertNotEqual(self.key(needs, rows), key)

    def test_stand_in_key_covers_only_the_card_the_task_pulls(self):
        rows, needs = [row(1), row(3)], result(2, "differs")
        key = self.key(needs, rows)
        rows[1]["finish"] = "foil"
        self.assertEqual(self.key(needs, rows), key)
        rows[0]["finish"] = "etched"
        self.assertNotEqual(self.key(needs, rows), key)

    def test_unavailable_tokens_remain_usable_and_unmodified(self):
        for answer in ({"unavailable": "Not ready"}, {"error": "Cannot read"}):
            self.assertEqual(token_packing_keys(answer, []), answer)
