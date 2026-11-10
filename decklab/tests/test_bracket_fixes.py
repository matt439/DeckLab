"""Minimum cuts agree with exhaustive small-deck oracles, including overlapping combos and GC choices."""
import copy
import itertools
import unittest

from decklab.lib.stats.commander import bracket_fixes, min_bracket


def bracket(gc=(), mld=(), turns=(), combos=()):
    return {"game_changers": [{"name": name, "qty": 1} for name in gc],
            "mass_land_denial": [{"name": name, "qty": 1} for name in mld],
            "extra_turns": [{"name": name, "qty": 1} for name in turns], "unknown_cards": [],
            "combos": {"checked": True, "matches": [{"names": list(names), "floor": floor} for names, floor in combos]}}


class BracketFixTests(unittest.TestCase):
    def test_four_game_changers_are_any_one_of_four_without_picking_a_worst(self):
        original = bracket(gc=["A", "B", "C", "D"])
        unchanged = copy.deepcopy(original)
        got = bracket_fixes(original, 3)
        self.assertTrue(got["checked"])
        self.assertEqual(got["cuts"], 1)
        self.assertEqual(got["plans"][0]["fixed"], [])
        self.assertEqual(got["plans"][0]["choose"], {"count": 1, "names": ["A", "B", "C", "D"]})
        self.assertEqual(got["plans"][0]["after_minimum"], 3)
        self.assertEqual(original, unchanged)

    def test_one_shared_combo_piece_is_fewer_than_independent_cuts_and_tags_overlap(self):
        value = bracket(gc=["A", "B", "C", "D"], mld=["A"], turns=["B"],
                        combos=[(("A", "B"), 3), (("A", "C"), 4)])
        got = bracket_fixes(value, 2)
        self.assertEqual(got["cuts"], 4)
        self.assertEqual(got["plans"][0]["fixed"], ["A", "B", "C", "D"])
        self.assertEqual(got["plans"][0]["after_minimum"], 1)
        shared = bracket_fixes(bracket(combos=[(("A", "B"), 3), (("A", "C"), 3)]), 2)
        self.assertEqual(shared["cuts"], 1)
        self.assertEqual(shared["plans"][0]["fixed"], ["A"])
        self.assertEqual(shared["plans"][0]["after_minimum"], 1)

    def test_exact_count_matches_exhaustive_four_card_graphs(self):
        names = ("A", "B", "C", "D")
        pairs = list(itertools.combinations(names, 2))
        subsets = [frozenset(combo) for n in range(5) for combo in itertools.combinations(names, n)]
        for mask in range(1 << len(pairs)):
            combos = [(pair, 3 if i % 2 else 4) for i, pair in enumerate(pairs) if mask & (1 << i)]
            for gc in (set(), {"A"}, set(names)):
                value = bracket(gc=gc, mld={"B"}, turns={"C"}, combos=combos)
                for target in (1, 2, 3):
                    def after(cuts):
                        floors = [floor for pair, floor in combos if not set(pair).intersection(cuts)]
                        return min_bracket(len(gc - cuts), int("B" not in cuts) + floors.count(4), int("C" not in cuts), floors.count(3))
                    expected = min(len(cuts) for cuts in subsets if after(cuts) <= target)
                    got = bracket_fixes(value, target)
                    self.assertTrue(got["checked"])
                    self.assertEqual(got["cuts"], expected, (value, target, got))
                    for plan in got["plans"]:
                        self.assertEqual(len(plan["example"]), expected)
                        self.assertEqual(after(set(plan["example"])), plan["after_minimum"])

    def test_unreadable_or_unknown_data_never_gives_an_all_clear_and_budget_is_honest(self):
        for field, value in (("mass_land_denial", None), ("extra_turns", None), ("combos", {"checked": False}),
                             ("unknown_cards", ["Unknown card"])):
            self.assertFalse(bracket_fixes({**bracket(), field: value}, 3)["checked"])
        self.assertFalse(bracket_fixes(bracket(combos=[(("A", "B"), 3)]), 2, node_budget=0)["checked"])
        self.assertFalse(bracket_fixes(bracket(), True)["checked"])
        for value in (None, {}, "", False):
            self.assertFalse(bracket_fixes({**bracket(), "unknown_cards": value}, 3)["checked"])
        missing = bracket()
        missing.pop("unknown_cards")
        self.assertFalse(bracket_fixes(missing, 3)["checked"])

    def test_game_changer_cuts_can_also_hit_combo_edges_without_extra_cuts(self):
        value = bracket(gc=["B", "C", "D", "E", "F"], combos=[(("A", "B"), 4), (("A", "C"), 4)])
        got = bracket_fixes(value, 3)
        self.assertEqual(got["cuts"], 2)
        self.assertTrue(any(plan["fixed"] == ["B", "C"] for plan in got["plans"]))

    def test_large_game_changer_choice_is_compact_and_target_four_needs_no_cuts(self):
        value = bracket(gc=[f"GC {i}" for i in range(100)])
        answer = bracket_fixes(value, 3)
        self.assertEqual(answer["cuts"], 97)
        self.assertEqual(answer["plans"][0]["choose"]["count"], 97)
        self.assertEqual(len(answer["plans"]), 1)
        self.assertEqual(bracket_fixes(value, 4)["cuts"], 0)
