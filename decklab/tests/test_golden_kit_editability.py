"""Keep historical reader comparisons sensitive to kit data and non-additive permissions."""
import copy
import unittest

from decklab.lib import access, state
from decklab.lib.api import deck_page, guard
from decklab.lib.state.memory import MemoryStore
from decklab.tests import golden_dump, golden_p4
from decklab.tests.test_api_accessories import AccessoriesApiTestCase, SLEEVES


class KitGoldenTests(unittest.TestCase):
    @staticmethod
    def answers():
        return {"deck_view": {"casual/a@target": {"editable": "legacy page field", "summary": {
            "kit": {"editable": True, "sleeves": {"name": "Red", "editable": "nested legacy field"},
                    "deck_box": None, "need": 60, "short": 0, "warnings": ["Keep warning"], "info": []}}}},
            "accessories": {"editable": True}, "decks_index": {"decks": [{"kit": {"editable": False}}]}}

    @staticmethod
    def normalised(value):
        result = copy.deepcopy(value)
        golden_p4.kit_editability(result)
        return result

    def test_only_boolean_deck_page_kit_metadata_is_ignored_for_each_viewer(self):
        original = self.answers()
        original["by_viewer"] = {"matt": self.answers(), "user1": self.answers(), "invalid": None}
        original["by_viewer"]["user1"]["deck_view"]["casual/a@target"]["summary"]["kit"]["editable"] = False
        untouched = copy.deepcopy(original)
        normalised = self.normalised(original)
        for mine in (normalised, normalised["by_viewer"]["matt"], normalised["by_viewer"]["user1"]):
            view = mine["deck_view"]["casual/a@target"]
            self.assertNotIn("editable", view["summary"]["kit"])
            self.assertEqual(view["editable"], "legacy page field")
            self.assertEqual(view["summary"]["kit"]["sleeves"]["editable"], "nested legacy field")
            self.assertEqual(mine["accessories"]["editable"], True)
            self.assertEqual(mine["decks_index"]["decks"][0]["kit"]["editable"], False)
        self.assertEqual(original, untouched)

    def test_kit_values_warnings_other_permissions_and_malformed_metadata_still_compare(self):
        baseline = self.answers()
        changes = [lambda view: view["summary"]["kit"].update(need=61),
                   lambda view: view["summary"]["kit"].update(short=1),
                   lambda view: view["summary"]["kit"].update(warnings=[]),
                   lambda view: view["summary"]["kit"]["sleeves"].update(name="Blue"),
                   lambda view: view.update(editable=False)]
        for change in changes:
            with self.subTest(change=change):
                changed = copy.deepcopy(baseline)
                change(changed["deck_view"]["casual/a@target"])
                self.assertIsNotNone(golden_dump.first_difference(self.normalised(baseline), self.normalised(changed)))
        for value in (None, 0, 1, "yes", [], {}):
            with self.subTest(value=value):
                changed = copy.deepcopy(baseline)
                changed["deck_view"]["casual/a@target"]["summary"]["kit"]["editable"] = value
                self.assertEqual(self.normalised(changed)["deck_view"]["casual/a@target"]["summary"]["kit"]["editable"], value)


class KitProjectionPermissionTests(AccessoriesApiTestCase):
    def test_public_reader_gets_kit_but_only_owner_can_choose_it(self):
        store = MemoryStore()
        self.addCleanup(state.use(store))
        hers = self.add({**SLEEVES, "owner": "user1", "colour": "pink"}, profile="user1")["changed_id"]
        self.assign("casual/hers", hers, profile="user1")
        store.visibility_set("user1", "accessories", True, state.Actor("user1", "User1"), "Fixture publication")
        summary = {"id": "casual/hers", "space": "home", "player": "wife", "status": "built"}
        for viewer, editable in (("matt", False), ("user1", True)):
            with self.subTest(viewer=viewer), access.viewing(viewer):
                self.assertTrue(guard.sees_kit(summary))
                warnings = []
                kit, revision = deck_page._view_kit(summary, {}, warnings)
                self.assertEqual(kit["sleeves"]["id"], hers)
                self.assertIs(kit["editable"], editable)
                self.assertEqual(warnings, [])
                self.assertTrue(revision)
