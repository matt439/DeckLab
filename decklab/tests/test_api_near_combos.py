"""The deck page's combos one card away (E9-S25): deck_view's near_combos, from the sandbox's
Commander deck and collection (decklab/tests/test_api.py) and a made-up combo list. Each missing
card's availability shows only to a viewer who may see the deck's space's inventory.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import json
from unittest import mock

from decklab.lib import api
from decklab.lib.api import deck_page
from decklab.lib.stats import commander as real_stats_commander
from decklab.tests.test_api import ApiTestCase, fake_stats, _write


def piece(oracle_id, name):
    return {"oracle_id": oracle_id, "name": name, "must_be_commander": False}


ELVES = piece("68954295-54e3-4303-a6bc-fc4547a4e3a3", "Llanowar Elves")
SOL_RING = piece("6ad8011d-3471-4369-9d68-b264cc027487", "Sol Ring")
COMBOS = {"format": 2, "source": "test", "timestamp": "2026-10-14T03:14:00+00:00", "version": "7.3.0", "count": 3,
          "combos": [
              # The sandbox's one Elvish Mystic is held by one of its other decks.
              {"id": "1-2", "url": "https://commanderspellbook.com/combo/1-2/",
               "cards": [ELVES, piece("3f3b2c10-21f8-4e13-be83-4ef3fa36e123", "Elvish Mystic")],
               "results": ["Infinite green mana"], "class": "infinite", "standalone": True},
              # Rhystic Study is blue: outside Ghalta's colours.
              {"id": "3-4", "url": "https://commanderspellbook.com/combo/3-4/",
               "cards": [SOL_RING, piece("53236dd7-845a-444c-96d5-f41ed7325d8f", "Rhystic Study")],
               "results": ["Draw the deck"], "class": "other", "standalone": True},
              # Not owned: to buy.
              {"id": "5-6", "url": "https://commanderspellbook.com/combo/5-6/",
               "cards": [SOL_RING, piece("9af4a832-d634-47aa-91ed-79d44fe08864", "Pick Your Poison")],
               "results": ["Lock"], "class": "lock", "standalone": False}]}


def commander_stats(sections, kind):
    result = fake_stats(sections, kind)
    if kind == "commander":
        result["commander"] = {"bracket": {"minimum": 2}}
    return result


class NearCombosPageTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        path = self.box.data / "two_card.json"
        _write(path, json.dumps(COMBOS))
        patcher = mock.patch.object(real_stats_commander, "COMBO_FILE", path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.box.stats.side_effect = commander_stats

    def test_a_commander_deck_lists_its_near_combos_with_availability(self):
        near = api.deck_view("commander/elf-commander", omit={"matchups"})["near_combos"]
        self.assertTrue(near["checked"])
        self.assertEqual(near["total"], 2)
        self.assertEqual([(m["missing"], m["held"], m["availability"]["state"], m["raises_to"]) for m in near["matches"]],
                         [("Elvish Mystic", "Llanowar Elves", "in_use", 3), ("Pick Your Poison", "Sol Ring", "buy", None)])

    def test_no_availability_for_a_viewer_who_may_not_see_the_inventory(self):
        with mock.patch.object(deck_page.guard, "sees_inventory", return_value=False):
            answer = api.deck_view("commander/elf-commander", omit={"matchups"})
        self.assertNotIn("owned", answer)
        near = answer["near_combos"]
        self.assertEqual([m["missing"] for m in near["matches"]], ["Elvish Mystic", "Pick Your Poison"])
        self.assertTrue(all("availability" not in m for m in near["matches"]))

    def test_only_commander_decks(self):
        self.assertNotIn("near_combos", api.deck_view("casual/gruul-test", omit={"matchups"}))

    def test_a_failure_is_a_warning_never_a_broken_page(self):
        with mock.patch("decklab.lib.combos.near_for_deck", side_effect=RuntimeError("boom")):
            answer = api.deck_view("commander/elf-commander", omit={"matchups"})
        self.assertNotIn("near_combos", answer)
        self.assertIn("The combos one card away couldn't be worked out (the server log says why)", answer["warnings"])
