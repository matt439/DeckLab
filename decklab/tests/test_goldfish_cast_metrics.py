"""Commander/copy-category/colour-wait metrics preserve physical play choices and integer merging."""
import json
import unittest

from decklab.lib import goldfish
from decklab.lib.goldfish import cast_metrics
from decklab.lib.goldfish.results import _share
from decklab.tests import test_goldfish as base
from decklab.tests.test_goldfish import setUpModule, tearDownModule  # noqa: F401


class CastMetricTests(unittest.TestCase):
    def test_commander_pair_has_independent_first_cast_and_never_counts(self):
        sections = base.parse("Commander\n1 Finneas, Ace Archer\n1 Giada, Font of Hope\nDeck\n5 Forest\n5 Plains\n4 Craw Wurm\n")
        model, _ = goldfish.compile_deck(sections, "commander")
        engine = goldfish._Engine(model)
        counts = goldfish._play_games(engine, "play", 2, 1, base.NoShuffle(), False)
        rows = cast_metrics.summary(counts["casts"], model, 2, 1, _share)["commanders"]
        self.assertEqual({row["name"] for row in rows}, {"Finneas, Ace Archer", "Giada, Font of Hope"})
        self.assertTrue(all(row["never"] == 1 and row["average_turn"] is None for row in rows))

    def test_commander_first_cast_is_recorded_separately_from_first_big_spell(self):
        order = ["Forest", "Plains", "Craw Wurm"] + base.BLANKS
        trace, counts = base.script(order, turns=3, kind="commander", commander="Finneas, Ace Archer")
        model, _ = goldfish.compile_deck(base.parse(base.deck_text(base.Counter(order), "Finneas, Ace Archer")), "commander")
        value = cast_metrics.summary(counts["casts"], model, 3, 1, _share)["commanders"][0]
        self.assertIn("Finneas, Ace Archer", trace[1]["cast"])
        self.assertEqual([row["chance"] for row in value["by_turn"]], [0, 1, 1])
        self.assertEqual((value["average_turn"], value["never"]), (2, 0))

    def test_colour_wait_uses_affordable_turns_and_average_blocked_turns(self):
        order = ["Forest", "Lightning Bolt"] + ["Craw Wurm"] * 5 + ["Mountain"] + base.BLANKS
        _trace, counts = base.script(order, turns=3)
        model, _ = goldfish.compile_deck(base.parse(base.deck_text(base.Counter(order))), "constructed")
        rows = cast_metrics.summary(counts["casts"], model, 3, 1, _share)["castability"]
        bolt = next(row for row in rows if row["name"] == "Lightning Bolt")
        self.assertEqual((bolt["enough_mana_turns"], bolt["blocked_turns"], bolt["blocked_share"]), (2, 1, .5))
        self.assertEqual((bolt["games_seen"], bolt["games_waited"], bolt["average_wait"]), (1, 1, 1))
        wurm = next(row for row in rows if row["name"] == "Craw Wurm")
        self.assertIsNone(wurm["blocked_share"])

    def test_category_labels_change_cache_key_but_not_seed_or_played_games(self):
        plain = base.parse("Deck\n12 Forest\n8 Mountain\n4 Llanowar Elves\n4 Grizzly Bears\n4 Lightning Bolt\n8 Craw Wurm\n")
        tagged = base.parse("Deck\n12 Forest #Mana\n8 Mountain #Mana\n2 Llanowar Elves #Ramp\n2 Llanowar Elves #Plan\n4 Grizzly Bears #Plan\n4 Lightning Bolt #Removal\n8 Craw Wurm #Plan\n")
        a = goldfish.simulate(plain, "constructed", games=8, turns=3, workers=1)
        b = goldfish.simulate(tagged, "constructed", games=8, turns=3, workers=1)
        self.assertEqual(a["seed"], b["seed"])
        self.assertNotEqual(goldfish.cache_key(plain, "constructed"), goldfish.cache_key(tagged, "constructed"))
        for setup in a["results"]:
            for key in ("mulligans", "land_drops", "stuck", "flood", "colours", "mana_used", "first_big", "castability"):
                self.assertEqual(a["results"][setup][key], b["results"][setup][key], (setup, key))
        categories = {row["name"]: row for row in b["results"]["play"]["categories"]}
        self.assertEqual((categories["Ramp"]["cards"], categories["Plan"]["cards"]), (2, 14))
        self.assertTrue(all(chance == 0 for turn in categories["Mana"]["by_turn"] for chance in turn["at_least"]))
        json.dumps(b, allow_nan=False)

    def test_unresolved_category_is_unknown_and_nested_integer_counts_merge(self):
        sections = base.parse("Deck\n10 Forest\n1 Llanowar Elves #Plan\n1 Unknown fixture spell #Plan\n")
        model, _ = goldfish.compile_deck(sections, "constructed")
        engine = goldfish._Engine(model)
        first = goldfish._play_games(engine, "play", 2, 1, base.NoShuffle(), False)
        second = goldfish._play_games(engine, "play", 2, 1, base.NoShuffle(), False)
        goldfish.engine._add_counts(first, second)
        category = cast_metrics.summary(first["casts"], model, 2, 2, _share)["categories"][0]
        self.assertFalse(category["checked"])
        self.assertIsNone(category["by_turn"])
        for turn in (1, 2):
            self.assertEqual(sum(row[turn] for row in first["casts"]["category_casts"][0]), 2)
