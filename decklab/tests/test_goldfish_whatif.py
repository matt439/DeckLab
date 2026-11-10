"""One-card mana trials share seed, replay settings and never alter their input deck."""
import copy
import tempfile
import unittest
from unittest import mock

from decklab.lib import goldfish
from decklab.lib.goldfish import whatif
from decklab.tests import test_goldfish as base
from decklab.tests.test_goldfish import setUpModule, tearDownModule  # noqa: F401


class LandTrialTests(unittest.TestCase):
    def test_named_and_tapped_cuts_replay_same_seed_and_do_not_change_lists(self):
        sections = base.parse("Deck\n8 Forest\n6 Mountain\n2 Temple of Abandon\n4 Grizzly Bears #Plan\n4 Lightning Bolt #Removal\n8 Craw Wurm #Plan\n")
        before = copy.deepcopy(sections)
        baseline = goldfish.simulate(sections, "constructed", games=12, turns=4, seed=9, workers=1)
        key, settings, variants = whatif.prepare(sections, "constructed", "Grizzly Bears", baseline)
        self.assertEqual(settings, {"games": 12, "turns": 4, "seed": 9, "mulligans": True})
        self.assertEqual({(row["cut"], row["add"]) for row in variants},
                         {(cut, add) for cut in ("Grizzly Bears", "Temple of Abandon") for add in ("Forest", "Mountain")})
        for row in variants:
            self.assertEqual(sum(line.quantity for line in row["sections"]["Deck"]), 32)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(goldfish.runs, "get_or_simulate", wraps=goldfish.runs.get_or_simulate) as replay:
            result = whatif.run(sections, "constructed", "Grizzly Bears", baseline, workers=1, cache_dir=folder)
            self.assertEqual(len(replay.call_args_list), 5)
            for call in replay.call_args_list:
                self.assertEqual({key: call.kwargs[key] for key in settings}, settings)
            with mock.patch.object(goldfish.runs, "get_or_simulate", side_effect=AssertionError("must use cache")):
                self.assertTrue(whatif.run(sections, "constructed", "Grizzly Bears", baseline, cache_dir=folder)["cached"])
            self.assertEqual(whatif.saved(key, folder)["baseline"], result["baseline"])
        self.assertEqual(sections, before)
        self.assertEqual([line.category for line in sections["Deck"]], [line.category for line in before["Deck"]])

    def test_bounded_replay_and_no_best_below_threshold_or_with_regression(self):
        sections = base.parse("Deck\n8 Forest\n4 Grizzly Bears\n")
        baseline = {"games": 100_000, "turns": 8, "seed": 7, "mulligans": True}
        _, settings, _ = whatif.prepare(sections, "constructed", "Grizzly Bears", baseline)
        self.assertEqual(settings["games"], 20_000)
        def row(identity, stuck, screw, flood):
            return {"id": identity, "deltas": {"play": {"stuck": stuck, "colour_screw": screw, "flood": flood}}}
        self.assertIsNone(whatif._best([row("a", -.009, -.009, 0)], "play"))
        self.assertIsNone(whatif._best([row("a", -.02, 0, .011)], "play"))
        self.assertEqual(whatif._best([row("a", -.02, 0, .005), row("b", 0, -.03, 0)], "play"), "b")
        for values in ((None, -.02, 0), (-.02, None, 0), (-.02, 0, None)):
            self.assertIsNone(whatif._best([row("short", *values)], "play"))
        with self.assertRaises(ValueError):
            whatif.prepare(sections, "constructed", "Not in this deck", baseline)

    def test_commander_trials_use_identity_and_only_the_deck_section(self):
        sections = base.parse("Commander\n1 Finneas, Ace Archer\nDeck\n10 Forest\n4 Grizzly Bears\nSideboard\n1 Lightning Bolt\n")
        self.assertEqual(whatif.choices(sections, "commander")["colours"], ["W", "G"])
        with self.assertRaises(ValueError):
            whatif.prepare(sections, "commander", "Finneas, Ace Archer", {"games": 10, "turns": 4, "seed": 1, "mulligans": True})
