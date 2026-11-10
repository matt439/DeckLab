"""Historical goldens omit only the exact additive zero-land default, not real stats."""
import copy
import unittest

from decklab.tests import golden_p4


class StatSourceGoldenTests(unittest.TestCase):
    def answer(self):
        return {"deck_view": {"casual/test@target": {"stats": {"colours": {
            "sources": [], "colours": [{"colours": "G", "land_sources": 0}],
            "land_sources_by_colour": dict.fromkeys("WUBRGC", 0)}}}}}

    def test_only_exact_empty_source_default_is_ignored_in_each_viewer(self):
        value = self.answer()
        value["by_viewer"] = {"matt": self.answer(), "invalid": None}
        untouched = copy.deepcopy(value)
        got = golden_p4.normalise(value)
        for mine in (got, got["by_viewer"]["matt"]):
            self.assertNotIn("land_sources_by_colour", mine["deck_view"]["casual/test@target"]["stats"]["colours"])
        self.assertEqual(value, untouched)

    def test_nonzero_malformed_or_actual_land_sources_remain_visible(self):
        changes = [lambda row: row["land_sources_by_colour"].update(G=1),
                   lambda row: row["land_sources_by_colour"].pop("C"),
                   lambda row: row["land_sources_by_colour"].update(G=False),
                   lambda row: row.update(sources=[{"kind": "land", "qty": 1, "colours": "G"}]),
                   lambda row: row.update(sources=None)]
        for change in changes:
            value = self.answer()
            change(value["deck_view"]["casual/test@target"]["stats"]["colours"])
            self.assertEqual(golden_p4.normalise(value), value)
        value = {"land_sources_by_colour": dict.fromkeys("WUBRGC", 0)}
        self.assertEqual(golden_p4.normalise(value), value)
