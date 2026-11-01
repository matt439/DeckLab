"""What a new self-hoster's Forge commands say (E11-S58's WSL qualification, 2026-11-02): the
default folder named when config.json sets no forge_dir, --games' help and refusal, --no-save's
note, and pilots for decks this install doesn't have. Nothing is played or installed."""
import argparse
import types
import unittest
from unittest import mock

from decklab.lib import config
from decklab.lib.forge import cli_commands, cli_output, cli_shared, install, pilots


class NotInstalledTests(unittest.TestCase):
    def test_a_configured_folder_stays_unnamed(self):
        self.assertEqual(install.not_installed_problem({"forge_dir": "/srv/forge-elsewhere"}),
                         "Forge isn't installed at the folder config.json names.")

    def test_the_default_folder_is_named_without_the_user_name(self):
        default = {"forge_dir": config.DEFAULTS["forge_dir"]}
        linux = install.not_installed_problem(default, windows=False)
        self.assertIn("~/tools/forge-decklab", linux)
        self.assertIn("sets no forge_dir", linux)
        self.assertIn(r"C:\Tools\forge-decklab", install.not_installed_problem(default, windows=True))


class PlayHelpTests(unittest.TestCase):
    def parser(self):
        sub = argparse.ArgumentParser(prog="forge").add_subparsers()
        cli_commands._play_args(sub)
        return sub.choices["play"]

    def test_games_help_lists_the_counts_and_batch(self):
        text = self.parser().format_help()
        for words in ("200, 400, 800, 1600, 3200", "--batch", "Play-now", "saved result"):
            self.assertIn(words, " ".join(text.split()))

    def test_refusal_says_batch_allows_smaller_counts(self):
        problem = cli_shared._games_problem(1, None)
        self.assertIn("--games 1 --batch 1", problem)
        self.assertIsNone(cli_shared._games_problem(1, 1))


class NoSaveTests(unittest.TestCase):
    def test_the_note_says_what_was_counted(self):
        result = {"runs": [{"played": 1}, {"played": 1}]}
        line = cli_output.not_saved_line(result)
        self.assertIn("this run's 1 game with the 1 saved before", line)
        self.assertIn("the saved result is unchanged", line)
        self.assertIn("only this run's 2 games", cli_output.not_saved_line({"runs": [{"played": 2}]}))


class PilotsNotHereTests(unittest.TestCase):
    def test_only_decks_this_install_has_count(self):
        inv = types.SimpleNamespace(decks={"commander/giada": object()}, deck_aliases={"casual/old": "casual/new"})
        with mock.patch("decklab.lib.inventory.current", return_value=inv):
            away = pilots.lists_not_here(["commander/giada", "commander/giada@owned", "casual/old",
                                          "casual/the-free-peoples", "pairing/a+b"])
        self.assertEqual(away, {"casual/the-free-peoples"})

    def test_an_unreadable_inventory_hides_nothing(self):
        with mock.patch("decklab.lib.inventory.current", side_effect=RuntimeError("no database")):
            self.assertEqual(pilots.lists_not_here(["casual/the-free-peoples"]), set())


if __name__ == "__main__":
    unittest.main()
