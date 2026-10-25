"""The split Forge CLI keeps its existing import and patch targets working."""
import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.lib.forge import cli, cli_checks, cli_output, cli_shared


class CliModuleTests(unittest.TestCase):
    def test_compatibility_names_have_no_shadow_bindings(self):
        for name, owner in cli._OWNERS.items():
            with self.subTest(name=name):
                self.assertNotIn(name, vars(cli))
                self.assertIs(getattr(cli, name), getattr(owner, name))
                self.assertIn(name, dir(cli))

    def test_existing_deck_lookup_patch_reaches_moved_command(self):
        original = cli._cli_list
        args = SimpleNamespace(deck_id="casual/example", owned=True, results_dir=None)
        with mock.patch.object(cli, "_cli_list", side_effect=cli._CliError("missing deck")) as lookup:
            with self.assertRaisesRegex(cli._CliError, "missing deck"):
                cli._cmd_cards(args)
            lookup.assert_called_once_with("casual/example", True)
            self.assertIs(cli_shared._cli_list, lookup)
        self.assertIs(cli._cli_list, original)
        self.assertIs(cli_shared._cli_list, original)
        self.assertNotIn("_cli_list", vars(cli))

    def test_replacing_warning_state_reaches_its_owner(self):
        original = cli._said
        messages = io.StringIO()
        with mock.patch.object(cli, "_said", set()) as seen, contextlib.redirect_stderr(messages):
            cli._say_once("probe", "one warning")
            cli._say_once("probe", "second warning")
            self.assertIs(cli_checks._said, seen)
            self.assertEqual(seen, {"probe"})
        self.assertEqual(messages.getvalue(), "one warning\n")
        self.assertIs(cli._said, original)
        self.assertIs(cli_checks._said, original)

    def test_owner_patch_is_visible_through_existing_import_path(self):
        original = cli._pct
        with mock.patch.object(cli_output, "_pct", return_value="patched") as formatter:
            self.assertEqual(cli._pct(0.5), "patched")
            formatter.assert_called_once_with(0.5)
        self.assertIs(cli._pct, original)

    def test_star_import_keeps_public_names(self):
        namespace = {}
        exec("from decklab.lib.forge.cli import *", namespace)
        self.assertIs(namespace["run"], cli_shared.run)
        self.assertIs(namespace["CHECK_DECKS"], cli_checks.CHECK_DECKS)
        self.assertIs(namespace["main"], cli.main)
        self.assertNotIn("_shared", namespace)


if __name__ == "__main__":
    unittest.main()
