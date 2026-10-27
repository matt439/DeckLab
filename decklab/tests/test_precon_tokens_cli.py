"""Precon token CLI opt-in uses fresh fixtures and the same atomic operation as the page."""
import copy

from decklab.lib import inventory
from decklab.tests import test_precon_cli as cli
from decklab.tests import test_precon_tokens as tokens_fixture
from decklab.tests import test_precons as fixtures


class PreconTokenCliTests(tokens_fixture.PreconTokensTestCase):
    run_cli = cli.CommandLineTests.run_cli

    def test_opt_in_dry_run_previews_declared_unknown_tokens_without_saving(self):
        before = self.writes_made()
        code, out, err = self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "--add-tokens",
                                      "--dry-run", "-m", "Fixture precon")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("Would add 4 token cards in 2 separate rows", out)
        self.assertIn("quantities as declared by MTGJSON", out)
        self.assertIn("printing and reverse face unconfirmed", out)
        self.assertIn("3 Dinosaur (source token entry 1", out)
        self.assertIn("1 Dinosaur (source token entry 2", out)
        self.assertEqual(self.writes_made(), before)
        self.assertFalse(inventory.current().token_set("user2").exists)

    def test_opt_in_saves_once_and_reports_token_and_playable_counts_separately(self):
        before = self.writes_made()
        code, out, err = self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "--add-tokens", "-m", "Fixture precon")
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.writes_made(), before + 1)
        self.assertIn("Added 4 token cards in 2 separate rows", out)
        self.assertEqual(out.strip().splitlines()[-1], "Added 5 cards (3 new rows) to User2's collection and made user2/commander/ghalta-test-dinos.")
        self.assertEqual(sum(r.qty for r in inventory.current().token_set("user2").rows), 4)

    def test_missing_count_refuses_tokens_only_and_names_the_unknown_quantity(self):
        data = copy.deepcopy(fixtures.DINOS)
        data["data"]["tokens"] = [{"name": "Dinosaur"}]
        self.seed("decks/TestDinos_TST.json", data)
        before = self.writes_made()
        code, _, err = self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "--add-tokens", "-m", "Fixture precon")
        self.assertEqual(code, 1)
        self.assertIn("physical quantity is unknown", err)
        self.assertEqual(self.writes_made(), before)
        self.assertEqual(self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "-m", "Playable only")[0], 0)
        self.assertFalse(inventory.current().token_set("user2").exists)

    def test_apply_builds_a_fresh_plan_instead_of_using_an_earlier_dry_run(self):
        self.assertEqual(self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "--add-tokens",
                                      "--dry-run", "-m", "Fixture preview")[0], 0)
        data = copy.deepcopy(fixtures.DINOS)
        data["data"]["tokens"] = [{"name": "Dinosaur", "count": 2}]
        self.seed("decks/TestDinos_TST.json", data)
        code, out, err = self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "--add-tokens", "-m", "Fresh fixture")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("Added 2 token cards in 1 separate row", out)
        self.assertEqual(sum(r.qty for r in inventory.current().token_set("user2").rows), 2)
