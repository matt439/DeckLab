"""A field run end to end with the real run loop (simulation wave 3's R13, forge-trial/
sim-wave3-contract.md section 10.3): field.run_field plays its pairs through runner.run in one
pool session of its own, with the fake Forge's serve mode (fixtures/fake_forge.py) standing in for
DeckLabSim's, as test_forge_pool's PoolCase sets it up (4 slots, the card log said to be ready).
The field is three lists of test_forge's (field._field is replaced); the games are ordinary
matchup results under each pair's key, and the view reads them back.

Run from the repo root: python -m unittest decklab.tests.test_forge_field_run
"""
import unittest
from unittest import mock

from decklab.lib import forge
from decklab.lib.forge import field, seqstats
from decklab.tests import test_forge, test_forge_field
from decklab.tests.test_forge import GREEN, RED, entry
from decklab.tests.test_forge_pool import PoolCase

BLACK = """Deck
4 Murderous Rider // Swift End
2 Devout Decree
14 Swamp
"""


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


class FieldRunWithTheRunLoopTests(PoolCase):

    def setUp(self):
        super().setUp()
        self.green = entry(GREEN, "casual/green", title="Green")
        self.field = [self.green, entry(RED, "casual/red", title="Red"), entry(BLACK, "casual/black", title="Black")]
        patches = [mock.patch.object(field, "_field", lambda fmt, **kwargs: (list(self.field), []))]
        if not test_forge_field._built():
            patches += [mock.patch.object(seqstats, name, getattr(test_forge_field, "_" + name))
                        for name in ("decided_share", "apt_pick", "field_row", "field_average")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_a_small_field_run(self):
        seen = []
        note = field.run_field(self.green, 50, by="Matt", results_dir=self.results, local=True, inflight=2,
                               progress=lambda done, total, detail: seen.append((done, total, detail)))
        self.assertEqual((note["played"], note["planned"], note["stopped"], note["dropped"]), (100, 100, False, {}))
        keys = {forge.matchup_key(self.green, o) for o in self.field[1:]}
        self.assertEqual(set(note["per_opponent"]), keys)
        self.assertEqual(sorted(note["per_opponent"].values()), [50, 50])
        for key in keys:
            stored = forge.load(key, self.results)
            self.assertEqual(len(forge.views._games(stored)), 50)
        done, total, detail = seen[-1]
        self.assertEqual((done, total), (100, 100))
        for key, pair in detail["pairs"].items():
            stored = forge.load(key, self.results)
            p = forge.views._perspective(stored, self.green["card_sha"])
            games = forge.views._games(stored)
            self.assertEqual(pair["wins"], sum(1 for g in games if g["w"] == p))
            self.assertEqual(pair["other"], sum(1 for g in games if g["w"] is None))
            self.assertFalse(pair["playing"])
        # The view reads the same games back; a second run with nothing left to play plays nothing.
        found = field.view(self.green, self.results)
        self.assertEqual(sorted(o["games"] for o in found["opponents"]), [50, 50])
        self.assertEqual(field.run_field(self.green, 50, by="Matt", results_dir=self.results, local=True)["played"], 0)


if __name__ == "__main__":
    unittest.main()
