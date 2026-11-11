"""Comparable public catalogue bands and casual role candidates without real caches or games."""
import copy
import unittest
from unittest import mock

from decklab.lib import cards
from decklab.lib.decks import role_pool
from decklab.lib.gauntlet import role_ranges
from decklab.lib.api import role_cards, role_ranges as api_ranges
from decklab.tests.test_role_cards import RoleCardsTestCase, GHALTA_ID
from decklab.tests.test_swaps_api import deck_text


def catalogue():
    return {"kind": "commander", "built": "2026-11-11T00:00:00+00:00", "decks": [
        {"kind": "commander", "tier": "core", "playable": True, "card_sha": str(number),
         "cards": {"Commander": [[1, "Leader"]], "Main": ([[number, "Ramp"]] if number else []) + [[99-number, "Forest"]]}}
        for number in range(10)]}


class RoleRangesTests(unittest.TestCase):
    def card(self, name):
        return {"roles": ["ramp"] if name == "Ramp" else []} if name != "Unknown" else None

    def test_dated_same_tier_quartiles_are_intrinsic_and_leave_input_unchanged(self):
        source = catalogue()
        before = copy.deepcopy(source)
        answer = role_ranges.view(source, 2, ["ramp", "draw"], self.card)
        self.assertTrue(answer["ready"])
        self.assertEqual(answer["decks"], 10)
        self.assertEqual(answer["tier"], "core")
        self.assertEqual(answer["roles"], [{"role": "ramp", "low": 2.2, "typical": 4.5, "high": 6.8},
                                           {"role": "draw", "low": 0, "typical": 0, "high": 0}])
        self.assertIn("range, not a recipe", answer["note"])
        self.assertEqual(source, before)

    def test_missing_tier_date_thin_duplicate_unknown_and_malformed_sources_have_no_band(self):
        variants = [None, {}, {**catalogue(), "built": "unknown"}]
        for key, value in (("playable", False), ("tier", "upgraded"), ("card_sha", "same"),
                           ("cards", {"Commander": [[1, "Unknown"]], "Main": [[99, "Forest"]]}),
                           ("cards", {"Commander": "broken"}), ("cards", {"Main": [[100, "Forest"]]})):
            source = catalogue()
            for deck in source["decks"]:
                deck[key] = value
            variants.append(source)
        for source in variants:
            with self.subTest(source=source):
                result = role_ranges.view(source, 2, ["ramp"], self.card)
                self.assertFalse(result["ready"])
                self.assertEqual(result["roles"], [])
        self.assertFalse(role_ranges.view(catalogue(), 4, ["ramp"], self.card)["ready"])

    def test_casual_fit_uses_colours_without_commander_legality_or_identity(self):
        card = {"name": "Fixture", "type_line": "Creature", "colors": ["G"],
                "color_identity": ["G", "B"], "commander_legality": "banned", "roles": ["ramp"]}
        self.assertTrue(role_pool.fits(card, {"G"}, "casual"))
        self.assertFalse(role_pool.fits(card, {"G"}, "commander"))
        self.assertFalse(role_pool.fits({**card, "colors": ["R"]}, {"G"}, "casual"))


class RoleRangesApiTests(RoleCardsTestCase):
    def test_casual_selected_nonland_colours_have_free_role_cards_and_no_target(self):
        self.write("colours", deck_text("Deck\n1 Llanowar Elves (FDN) 227\n20 Mountain", title="Green spells"))
        answer = role_cards.role_cards("casual/colours")
        self.assertEqual((answer["kind"], answer["colours"]), ("casual", ["G"]))
        self.assertNotIn("target", answer)
        names = [row["name"] for role in answer["roles"] for row in role["cards"]]
        self.assertIn("Pick Your Poison", names)
        self.assertNotIn("Wrath of God", names)

    def test_catalogue_ranges_use_visible_deck_and_do_not_load_a_pool(self):
        with mock.patch.object(api_ranges.catalogue, "load", return_value=catalogue()), \
                mock.patch.object(api_ranges.role_ranges, "view", return_value={"ready": True}) as view, \
                mock.patch.object(role_cards.pool, "load_pool", side_effect=AssertionError("Range read must not count inventory")):
            answer = api_ranges.ranges_view(GHALTA_ID)
        self.assertTrue(answer["ready"])
        self.assertEqual(view.call_args.args[0], catalogue())
        self.assertEqual(view.call_args.args[2], cards.ROLES)
        self.assertApiError(404, api_ranges.ranges_view, "commander/missing")
