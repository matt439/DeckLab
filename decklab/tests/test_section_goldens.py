"""Keep the historical reader goldens sensitive to physical recipes and real allocation changes."""
import copy
import unittest
from unittest import mock

from decklab.tests import golden_dump, golden_p4


class SectionGoldenTests(unittest.TestCase):

    @staticmethod
    def projection():
        return {"version": "target", "intended_version": "target", "main_count": 4,
                "sideboard_count": 0, "sideboard_intended": 0, "remaining_count": 0,
                "remaining": [], "changed": False}

    @classmethod
    def answers(cls):
        summary = {"id": "casual/a", "status": "built", "card_count": 4, "sideboard_count": 0,
                   "missing": {"target": 1}, "assembled": cls.projection()}
        deck = {"id": "casual/a", "version": "target", "assembly_key": None,
                "steps": [{"name": "Opt", "need": 2, "storage": 1, "missing": 1}],
                "basics": [{"name": "Island", "quantity": 2}], "returns": [],
                "build_scope": {"mode": "all", "label": "Main deck only", "main_count": 4,
                                "sideboard_count": 0, "sideboard_intended": 0, "return_count": 0},
                "remaining_intent": []}
        return {"assembly": {"a": {"choices": [{"id": "casual/a", "versions": ["target"],
                                                "sideboards": {"target": []}}],
                                    "selections": [{"id": "casual/a", "version": "target"}],
                                    "assembly_keys": {}, "decks": [deck], "editable": False,
                                    "totals": {"need": 2, "missing": 1}},
                             "": {"choices": [], "selections": [], "assembly_keys": {}, "decks": []}},
                "decks_index": {"decks": [copy.deepcopy(summary)]},
                "deck_view": {"casual/a@target": {"summary": summary, "version": "target",
                                                   "assembled": cls.projection(), "owned": {"missing": 1}}}}

    @staticmethod
    def normalised(answer):
        result = copy.deepcopy(answer)
        golden_p4.assembly_section_defaults(result)
        return result

    @classmethod
    def legacy(cls):
        result = cls.answers()
        for plan in result["assembly"].values():
            plan.pop("selections")
            plan.pop("assembly_keys")
            for choice in plan["choices"]:
                choice.pop("sideboards")
            for deck in plan["decks"]:
                for field in ("assembly_key", "build_scope", "remaining_intent"):
                    deck.pop(field)
        result["decks_index"]["decks"][0].pop("assembled")
        result["deck_view"]["casual/a@target"].pop("assembled")
        result["deck_view"]["casual/a@target"]["summary"].pop("assembled")
        return result

    def test_neutral_defaults_and_each_viewer_normalise_without_mutating_input(self):
        unrelated = {"selections": [], "assembly_keys": {}, "assembly_key": None,
                     "build_scope": {"mode": "all"}, "assembled": self.projection(),
                     "sideboards": {}, "remaining_intent": []}
        original = {**self.answers(), "by_viewer": {"matt": self.answers(), "empty": None},
                    "unrelated": unrelated}
        untouched = copy.deepcopy(original)
        with mock.patch.object(golden_p4, "_profiles", return_value={
                "matt": {"id": "matt", "space": "home", "role": "admin"}}):
            self.assertEqual(golden_p4.normalise(original), {
                **self.legacy(), "by_viewer": {"matt": self.legacy(), "empty": None}, "unrelated": unrelated})
        self.assertEqual(original, untouched)

    def test_explicit_recipes_and_mismatched_selections_are_retained(self):
        cases = ([{"id": "casual/a", "version": "target", "sideboard": {}}],
                 [{"id": "casual/a", "version": "target", "sideboard": {"Negate": 1}}],
                 [{"id": "casual/b", "version": "target"}],
                 [{"id": "casual/a", "version": "owned"}], [], None,
                 [{"id": "casual/a", "version": "target", "future": True}])
        for selection in cases:
            with self.subTest(selection=selection):
                original = self.answers()
                original["assembly"]["a"]["selections"] = selection
                actual = self.normalised(original)["assembly"]["a"]
                self.assertEqual(actual["selections"], selection)
                self.assertEqual(actual["assembly_keys"], {})
                self.assertIn("assembly_key", actual["decks"][0])
                self.assertEqual(actual["decks"], original["assembly"]["a"]["decks"])

    def test_physical_snapshot_keys_and_mismatched_key_maps_are_retained(self):
        for keys, key in (({"casual/a": "a" * 64}, "a" * 64), ({"casual/b": "b" * 64}, None),
                          ({"casual/a": None}, None), ({}, "a" * 64), (None, None), ({}, False)):
            with self.subTest(keys=keys, key=key):
                original = self.answers()
                original["assembly"]["a"]["assembly_keys"] = keys
                original["assembly"]["a"]["decks"][0]["assembly_key"] = key
                actual = self.normalised(original)["assembly"]["a"]
                self.assertEqual(actual["assembly_keys"], keys)
                self.assertEqual(actual["decks"], original["assembly"]["a"]["decks"])
                self.assertIn("selections", actual)

    def test_duplicate_participants_and_missing_snapshot_metadata_are_not_defaults(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                original = self.answers()
                plan = original["assembly"]["a"]
                if missing:
                    plan["decks"][0].pop("assembly_key")
                else:
                    plan["decks"].append(copy.deepcopy(plan["decks"][0]))
                    plan["selections"].append(copy.deepcopy(plan["selections"][0]))
                actual = self.normalised(original)["assembly"]["a"]
                self.assertIn("selections", actual)
                self.assertEqual(actual["decks"], plan["decks"])

    def test_partial_malformed_and_mismatched_scope_counts_remain_visible(self):
        for change in ({"mode": "main"}, {"mode": "partial"}, {"sideboard_intended": 2},
                       {"sideboard_count": 1}, {"main_count": 5}, {"main_count": True},
                       {"return_count": 1}, {"label": "Other scope"}, {"future": 0}):
            with self.subTest(change=change):
                original = self.answers()
                scope = original["assembly"]["a"]["decks"][0]["build_scope"]
                scope.update(change)
                actual = self.normalised(original)["assembly"]["a"]["decks"][0]
                self.assertEqual(actual["build_scope"], scope)
                self.assertEqual(actual["remaining_intent"], [])

    def test_matching_return_count_can_be_neutral_without_dropping_the_actual_returns(self):
        original = self.answers()
        deck = original["assembly"]["a"]["decks"][0]
        deck["returns"] = [{"name": "Shock", "quantity": 2}]
        deck["build_scope"]["return_count"] = 2
        actual = self.normalised(original)["assembly"]["a"]["decks"][0]
        self.assertNotIn("build_scope", actual)
        self.assertEqual(actual["returns"], deck["returns"])

    def test_retained_intent_is_never_dropped(self):
        original = self.answers()
        rows = [{"section": "Sideboard", "name": "Negate", "remaining": 2, "missing": 1, "on_the_way": 1}]
        original["assembly"]["a"]["decks"][0]["remaining_intent"] = rows
        self.assertEqual(self.normalised(original)["assembly"]["a"]["decks"][0]["remaining_intent"], rows)

    def test_only_empty_known_version_sideboard_maps_are_ignored(self):
        for mapping in ({"target": [{"name": "Negate", "quantity": 2}]}, {"other": []},
                        {"target": None}, [], None):
            with self.subTest(mapping=mapping):
                original = self.answers()
                original["assembly"]["a"]["choices"][0]["sideboards"] = mapping
                actual = self.normalised(original)["assembly"]["a"]
                self.assertEqual(actual["choices"][0]["sideboards"], mapping)
                self.assertIn("build_scope", actual["decks"][0])

    def test_nonempty_sideboard_choices_must_match_existing_compared_sections(self):
        original = self.answers()
        plan = original["assembly"]["a"]
        plan["choices"][0]["sideboards"] = {"target": [{"name": "Negate", "quantity": 2}]}
        plan["decks"][0]["steps"].append({"name": "Negate", "need": 2, "storage": 2, "missing": 0})
        plan["decks"][0]["build_scope"].update(
            label="Main deck + whole sideboard", sideboard_count=2, sideboard_intended=2)
        original["deck_view"]["casual/a@target"]["sections"] = {
            "Deck": [{"name": "Opt", "qty": 2}, {"name": "Island", "qty": 2}],
            "Sideboard": [{"name": "Negate", "qty": 1}, {"name": "Negate", "qty": 1}]}
        actual = self.normalised(original)
        self.assertNotIn("sideboards", actual["assembly"]["a"]["choices"][0])
        self.assertNotIn("build_scope", actual["assembly"]["a"]["decks"][0])
        self.assertEqual(actual["deck_view"]["casual/a@target"]["sections"],
                         original["deck_view"]["casual/a@target"]["sections"])
        for rows in ([], [{"name": "Negate", "quantity": 3}],
                     [{"name": "Negate", "quantity": True}],
                     [{"name": "Negate", "quantity": 2, "future": True}]):
            with self.subTest(rows=rows):
                changed = copy.deepcopy(original)
                changed["assembly"]["a"]["choices"][0]["sideboards"]["target"] = rows
                actual = self.normalised(changed)["assembly"]["a"]
                self.assertEqual(actual["choices"][0]["sideboards"]["target"], rows)
                self.assertIn("build_scope", actual["decks"][0])

    def test_partial_changed_owned_unknown_or_mismatched_physical_projections_remain(self):
        for change in ({"changed": True}, {"changed": 0}, {"version": "owned"},
                       {"intended_version": "owned"}, {"main_count": 3}, {"main_count": True},
                       {"sideboard_count": 1}, {"sideboard_intended": 1}, {"remaining_count": 1},
                       {"remaining": [{"name": "Opt", "remaining": 1}]}, {"future": 0}):
            with self.subTest(change=change):
                original = self.answers()
                projection = original["decks_index"]["decks"][0]["assembled"]
                projection.update(change)
                actual = self.normalised(original)
                self.assertEqual(actual["decks_index"]["decks"][0]["assembled"], projection)

    def test_unknown_fields_and_editor_snapshot_sleeve_need_are_preserved(self):
        original = self.answers()
        original["assembly"]["a"]["future"] = {"assembly_keys": {}, "sideboards": {}}
        original["assembly"]["a"]["decks"][0]["future"] = "keep"
        original["edit_view"] = {"casual/a": {"assembled_need": 60, "table": {"stale": True}}}
        actual = self.normalised(original)
        self.assertEqual(actual["edit_view"], original["edit_view"])
        self.assertEqual(actual["assembly"]["a"]["future"], original["assembly"]["a"]["future"])
        self.assertEqual(actual["assembly"]["a"]["decks"][0]["future"], "keep")

    def test_physical_inventory_leaks_to_other_spaces_are_never_normalised_away(self):
        original = {"by_viewer": {"user2": self.answers(), "unknown": self.answers()}}
        with mock.patch.object(golden_p4, "_profiles", return_value={
                "user2": {"id": "user2", "space": "user2", "role": "member"}}):
            actual = self.normalised(original)
        for viewer in ("user2", "unknown"):
            self.assertEqual(actual["by_viewer"][viewer]["decks_index"], original["by_viewer"][viewer]["decks_index"])
            self.assertEqual(actual["by_viewer"][viewer]["deck_view"], original["by_viewer"][viewer]["deck_view"])

    def test_actual_allocation_counts_and_permissions_still_compare(self):
        for change in (lambda d: d["assembly"]["a"]["decks"][0]["steps"][0].update(need=3),
                       lambda d: d["assembly"]["a"]["decks"][0]["steps"][0].update(missing=2),
                       lambda d: d["assembly"]["a"]["decks"][0]["basics"][0].update(quantity=3),
                       lambda d: d["assembly"]["a"].update(editable=True),
                       lambda d: d["assembly"]["a"]["totals"].update(missing=2),
                       lambda d: d["decks_index"]["decks"][0]["missing"].update(target=2),
                       lambda d: d["deck_view"]["casual/a@target"]["owned"].update(missing=2)):
            with self.subTest(change=change):
                expected = self.answers()
                actual = copy.deepcopy(expected)
                change(actual)
                self.assertIsNotNone(golden_dump.first_difference(self.normalised(expected), self.normalised(actual)))


if __name__ == "__main__":
    unittest.main()
