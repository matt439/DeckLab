"""Physical choice CSVs bind every public row to a full source receipt; no live data."""
import copy
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory.model import Inventory
from decklab.tests import test_precon_cli as cli
from decklab.tests import test_precon_tokens as fixture
from decklab.tests import test_precons as sources


class PreconTokenChoicesCliTests(fixture.PreconTokensTestCase):
    run_cli = cli.CommandLineTests.run_cli

    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory(prefix="decklab-confirmed-tokens-")
        self.addCleanup(folder.cleanup)
        self.choice_file = Path(folder.name) / "tokens.csv"
        self.choice_file.write_text("source_row,front,quantity\n1,Dinosaur,2\n2,,0\n", encoding="utf-8")

    def confirmed(self, *extra, sha=None):
        return self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "--add-tokens",
                            "--token-rows", str(self.choice_file), "--tokens-source-sha256", sha or self.offer()["source_sha256"],
                            "-m", "Fixture confirmed physical tokens", *extra)

    def test_normal_dry_run_shows_unknown_source_options_and_receipt_without_private_token_read(self):
        data = copy.deepcopy(sources.DINOS)
        data["data"]["tokens"] = [{"name": "Dinosaur"}]
        self.seed("decks/TestDinos_TST.json", data)
        sha = self.offer()["source_sha256"]
        with mock.patch.object(Inventory, "token_set", side_effect=AssertionError("opt-out token read")):
            code, out, err = self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "--dry-run", "-m", "Fixture preview")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn(f"Token source SHA: {sha}", out)
        self.assertIn("source_row,front,quantity", out)
        self.assertIn("Source token entry 1: Dinosaur; fronts: Dinosaur; physical quantity unknown", out)
        self.assertIn("Dinosaur (physical quantity unknown)", out)
        self.assertNotIn("1 Dinosaur", out)
        self.assertEqual(self.writes_made(), 0)

    def test_confirmed_dry_run_and_save_use_chosen_counts_and_leave_csv_and_source_unchanged(self):
        original = self.choice_file.read_bytes()
        source = (self.cache / "decks" / "TestDinos_TST.json").read_bytes()
        code, out, err = self.confirmed("--dry-run")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("Would add 2 token cards in 1 separate row; confirmed physical quantities", out)
        self.assertIn("2 Dinosaur (source token entry 1", out)
        self.assertEqual(self.writes_made(), 0)
        code, out, err = self.confirmed()
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("Added 2 token cards in 1 separate row", out)
        self.assertEqual(self.writes_made(), 1)
        self.assertEqual([(row["front"], row["quantity"]) for row in inventory.current().token_set("user2").rows], [("Dinosaur", "2")])
        self.assertEqual(self.choice_file.read_bytes(), original)
        self.assertEqual((self.cache / "decks" / "TestDinos_TST.json").read_bytes(), source)

    def test_file_requires_opt_in_and_full_lowercase_receipt(self):
        base = ("add-precon", "TestDinos_TST", "--space", "user2", "-m", "Fixture refusal")
        for extra, phrase in ((("--token-rows", str(self.choice_file)), "--add-tokens"),
                              (("--add-tokens", "--token-rows", str(self.choice_file)), "full source SHA"),
                              (("--add-tokens", "--tokens-source-sha256", "a" * 64), "--token-rows")):
            with self.subTest(extra=extra):
                code, _, err = self.run_cli(*base, *extra)
                self.assertEqual(code, 1)
                self.assertIn(phrase, err)
        for sha in ("a" * 12, "A" * 64, ""):
            code, _, err = self.run_cli(*base, "--add-tokens", "--token-rows", str(self.choice_file), "--tokens-source-sha256", sha)
            self.assertEqual(code, 1)
            self.assertIn("full source SHA", err)
        self.assertEqual(self.writes_made(), 0)

    def test_csv_schema_and_physical_values_are_strict_and_refuse_without_writes(self):
        for text in ("front,quantity\nDinosaur,2\n", "source_row,front,quantity,quantity\n1,Dinosaur,2,2\n",
                     "source_row,front,quantity\n1,Dinosaur,2,extra\n", "source_row,front,quantity\n1,Dinosaur\n",
                     "source_row,front,quantity\n1,Dinosaur,1.5\n2,,0\n", "source_row,front,quantity\n1,Dinosaur,-1\n2,,0\n",
                     "source_row,front,quantity\n1,Dinosaur,251\n2,,0\n", "source_row,front,quantity\n0,Dinosaur,2\n2,,0\n",
                     'source_row,front,quantity\n1,"unterminated,2\n2,,0\n'):
            with self.subTest(text=text):
                self.choice_file.write_text(text, encoding="utf-8")
                code, _, err = self.confirmed()
                self.assertEqual(code, 1)
                self.assertTrue(err)
                self.assertEqual(self.writes_made(), 0)

    def test_every_source_row_is_required_once_and_all_zero_refuses_helpfully(self):
        for text in ("source_row,front,quantity\n1,Dinosaur,2\n",
                     "source_row,front,quantity\n1,Dinosaur,2\n1,Dinosaur,2\n",
                     "source_row,front,quantity\n1,,0\n2,,0\n"):
            with self.subTest(text=text):
                self.choice_file.write_text(text, encoding="utf-8")
                code, _, err = self.confirmed()
                self.assertEqual(code, 1)
                self.assertIn("unchecked" if "1,,0" in text else "exactly once", err)
                self.assertEqual(self.writes_made(), 0)

    def test_changed_source_refuses_old_manual_rows_instead_of_reinterpreting_them(self):
        sha = self.offer()["source_sha256"]
        data = copy.deepcopy(sources.DINOS)
        data["data"]["tokens"].reverse()
        self.seed("decks/TestDinos_TST.json", data)
        code, _, err = self.confirmed(sha=sha)
        self.assertEqual(code, 1)
        self.assertIn("source list changed", err)
        self.assertEqual(self.writes_made(), 0)

    def test_unknown_source_quantity_can_be_confirmed_from_csv(self):
        data = copy.deepcopy(sources.DINOS)
        data["data"]["tokens"] = [{"name": "Dinosaur"}, {"name": "Dinosaur"}]
        self.seed("decks/TestDinos_TST.json", data)
        code, out, err = self.confirmed()
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("Added 2 token cards", out)
        self.assertEqual(self.writes_made(), 1)
