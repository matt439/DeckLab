"""The production runner/save/load path with disposable Python fake Forge processes."""
from types import SimpleNamespace
from unittest import mock

from decklab.lib import forge
from decklab.lib.forge import cli_checks, development_data
from decklab.tests import test_forge
from decklab.tests.test_forge_pool import PoolCase
from decklab.tests.test_forge_variants import changed


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


class ControlRunnerTests(PoolCase):
    def test_independent_kind_roundtrips_real_runner_and_cannot_enter_views_or_card_stats(self):
        green = test_forge.GREEN.replace("6 Forest", "44 Forest")
        red = test_forge.RED.replace("6 Mountain", "46 Mountain")
        a, b = test_forge.entry(green, "casual/green"), test_forge.entry(red, "casual/red")
        found = forge.variants.run_unpaired(a, changed(green, add=[(1, "Forest")]), b, 4,
                                            by="Matt", results_dir=self.results, local=True)
        folder = self.results / "experiments" / "unpaired" / found["test"]
        row = found["opponents"][0]
        for key in (row["base_key"], row["variant_key"]):
            result = forge.saved.load(key, folder)
            self.assertEqual((result["kind"], len(forge.views._games(result))), ("unpaired", 4))
            self.assertTrue(forge.saved._is_result(result, key))
        self.assertEqual(forge.views.results(folder), [])
        self.assertIsNone(forge.cardstats.list_cards(test_forge.sections(green), "constructed", results_dir=folder))
        self.assertEqual(forge.variants.tests_for(a["id"], "target", self.results), [])
        self.assertFalse(list(self.results.glob("*.json")))
        with mock.patch.object(forge.runner, "run", side_effect=AssertionError("no duplicate games")):
            again = forge.variants.run_unpaired(a, changed(green, add=[(1, "Forest")]), b, 4,
                                                by="Matt", results_dir=self.results, local=True)
        self.assertEqual(again["test"], found["test"])

    def test_qualification_requires_valid_nonempty_development_separate_from_card_validity(self):
        tally = development_data.game({1: {1: (1, 0), 2: (2, 1)}, 2: {1: (1, 1), 2: (2, 2)}}, lambda seat: seat - 1)
        reader = SimpleNamespace(cards={"games": 1, "development": tally})
        self.assertIsNone(cli_checks._development_problem("Constructed", 1, reader))
        for value in ({"games": 1}, {"games": 1, "development": {}},
                      {"games": 1, "development": {**tally, "bad": 1}}):
            self.assertIn("incomplete", cli_checks._development_problem("Constructed", 1, SimpleNamespace(cards=value)))
