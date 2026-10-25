"""Keep rename metadata normalization narrow while preserving the historical golden evidence."""
import copy
import unittest

from decklab.tests import golden_dump, golden_p4


class RenameDefaultsTests(unittest.TestCase):

    @staticmethod
    def answers(generation=0):
        return {"decks_index": {"decks_revision": "volatile", "decks": [{"id": "casual/a", "missing": 2}]},
                "assembly": {"a": {"rename_versions": {"casual/a": generation}, "editable": False,
                                   "totals": {"need": 4, "missing": 2}, "warnings": ["Keep this warning"],
                                   "decks": [{"id": "casual/a", "rename_version": generation,
                                              "need": {"Opt": 4}, "steps": [{"name": "Opt", "missing": 2}]}]},
                             "": {"decks": [], "rename_versions": {}}}}

    def test_only_matching_zero_generations_and_library_tokens_are_removed(self):
        unrelated = {"rename_versions": {"casual/a": 0}, "rename_version": 0, "decks_revision": "keep",
                     "deck_aliases": {"casual/old": "casual/a"}}
        original = {**self.answers(), "by_viewer": {"matt": self.answers()}, "unrelated": unrelated}
        untouched = copy.deepcopy(original)
        actual = copy.deepcopy(original)
        golden_p4.rename_defaults(actual)
        expected = self.answers()
        expected["decks_index"].pop("decks_revision")
        for plan in expected["assembly"].values():
            plan.pop("rename_versions")
            for deck in plan["decks"]:
                deck.pop("rename_version")
        self.assertEqual(actual, {**expected, "by_viewer": {"matt": expected}, "unrelated": unrelated})
        self.assertEqual(original, untouched)

    def test_nonzero_or_malformed_generation_evidence_remains_visible(self):
        for generation in (1, False, "0", None):
            with self.subTest(generation=generation):
                original = self.answers(generation)["assembly"]
                actual = {"assembly": copy.deepcopy(original)}
                golden_p4.rename_defaults(actual)
                self.assertEqual(actual["assembly"]["a"], original["a"])
        for generations in ({}, {"casual/b": 0}, {"casual/a": 1}, {"casual/a": False},
                            {"casual/a": 0, "casual/b": 0}):
            with self.subTest(generations=generations):
                original = self.answers()
                original["assembly"]["a"]["rename_versions"] = generations
                actual = copy.deepcopy(original)
                golden_p4.rename_defaults(actual)
                self.assertEqual(actual["assembly"]["a"], original["assembly"]["a"])

    def test_counts_privacy_and_alias_differences_still_compare(self):
        base = self.answers()
        base["deck_aliases"] = {"casual/old": "casual/a"}
        for change in (lambda d: d["decks_index"]["decks"][0].update(missing=3),
                       lambda d: d["assembly"]["a"].update(editable=True),
                       lambda d: d["assembly"]["a"]["totals"].update(missing=3),
                       lambda d: d["assembly"]["a"]["decks"][0]["steps"][0].update(missing=3),
                       lambda d: d["deck_aliases"].update({"casual/old": "casual/b"})):
            with self.subTest(change=change):
                actual = copy.deepcopy(base)
                change(actual)
                expected = copy.deepcopy(base)
                golden_p4.rename_defaults(expected)
                golden_p4.rename_defaults(actual)
                self.assertIsNotNone(golden_dump.first_difference(expected, actual))


if __name__ == "__main__":
    unittest.main()
