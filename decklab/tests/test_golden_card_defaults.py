"""New additive metadata cannot weaken historical inventory/bracket comparisons."""
import copy
import unittest

from decklab.tests import golden_card_defaults as defaults


class GoldenCardDefaultTests(unittest.TestCase):
    def test_only_exact_role_derived_full_card_proposals_are_omitted(self):
        card = {"name": "Fixture", "type_line": "Sorcery", "img": "a", "img_small": "b", "roles": ["ramp", "removal"]}
        good, wrong = {**card, "category_suggestion": "Removal"}, {**card, "category_suggestion": "Ramp"}
        malformed = {"name": "Fixture", "roles": ["removal"], "category_suggestion": "Removal"}
        data = [good, wrong, malformed]
        defaults.normalise(data)
        self.assertNotIn("category_suggestion", good)
        self.assertEqual(wrong["category_suggestion"], "Ramp")
        self.assertIn("category_suggestion", malformed)

    def test_only_exact_missing_triple_default_changes_and_counted_floor_is_retained(self):
        base = {"size": {"cards": 100}, "bracket": {"minimum": 4, "not_automatic": [defaults.CURRENT_LIMIT]},
                "three_card_combos": copy.deepcopy(defaults.UNAVAILABLE)}
        original = copy.deepcopy(base)
        defaults.normalise(base)
        self.assertNotIn("three_card_combos", base)
        self.assertEqual(base["bracket"], {"minimum": 4, "not_automatic": [defaults.LEGACY_LIMIT]})
        for triple in ({"checked": True, "total": 0, "matches": []}, {"checked": False, "reason": "unknown cards"},
                       {**defaults.UNAVAILABLE, "matches": []}):
            data = {**copy.deepcopy(original), "three_card_combos": triple}
            before = copy.deepcopy(data)
            defaults.normalise(data)
            self.assertEqual(data, before)
