"""Command boundaries activate the database environment without starting games on reads."""
import contextlib
import importlib
import io
import json
import unittest
from unittest import mock

from decklab.lib import decks, inventory

cli = importlib.import_module("decklab.lib.crosscheck.__main__")


class CrosscheckCliTests(unittest.TestCase):
    def invoke(self, args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = cli.main(args)
        return code, output.getvalue(), error.getvalue()

    def test_unavailable_forge_setup_has_a_plain_nonzero_failure(self):
        from decklab.lib.forge.common import ForgeError
        with mock.patch.object(cli, "prepare_forge", side_effect=ForgeError("Forge is not installed.")), \
                mock.patch.object(cli, "run") as run:
            code, _, error = self.invoke(["prepare"])
        self.assertEqual(code, 1)
        self.assertEqual(error.strip(), "Forge is not installed.")
        run.assert_not_called()

    def test_unconfirmed_prepared_identity_is_not_success(self):
        with mock.patch.object(cli, "prepare_forge", return_value={"ready": False}), \
                mock.patch.object(cli, "run") as run:
            code, output, _ = self.invoke(["prepare"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(output)["ready"])
        run.assert_not_called()

    def test_status_uses_the_inventory_entry_boundary_without_reading_or_playing(self):
        from decklab.lib.inventory import entry
        with mock.patch.object(entry, "command", return_value=contextlib.nullcontext()) as command, \
                mock.patch.object(cli, "status", return_value={"schema": 1, "engines": {}}), \
                mock.patch.object(cli, "deck_entry", side_effect=AssertionError("read decks")), \
                mock.patch.object(cli, "run", side_effect=AssertionError("play games")):
            code, output, _ = self.invoke(["status"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["schema"], 1)
        command.assert_called_once_with()

    def test_plan_forwards_the_exact_change_and_versions_without_playing(self):
        a, b = {"id": "casual/a"}, {"id": "casual/b"}
        with mock.patch.object(cli, "deck_entry", side_effect=[a, b]) as entries, \
                mock.patch.object(cli, "plan", return_value={"schema": 1}) as plan, \
                mock.patch.object(cli, "run", side_effect=AssertionError("plan cannot play")):
            code, output, _ = self.invoke(["plan", "casual/a", "casual/b", "--version", "owned",
                "--games", "20", "--remove", "1 Shock", "--add", "1 Lightning Bolt"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), {"schema": 1})
        self.assertEqual(entries.call_args_list, [mock.call("casual/a", "owned"), mock.call("casual/b", "target")])
        self.assertEqual(plan.call_args.args, (a, b))
        self.assertEqual(plan.call_args.kwargs["remove"], ["1 Shock"])
        self.assertEqual(plan.call_args.kwargs["add"], ["1 Lightning Bolt"])
        self.assertEqual(plan.call_args.kwargs["games"], 20)

    def test_database_unavailability_is_exit_two_and_never_starts_a_run(self):
        with mock.patch.object(cli, "deck_entry", side_effect=inventory.Unavailable("fixture")), \
                mock.patch.object(cli, "run") as run:
            code, _, error = self.invoke(["play", "casual/a", "casual/b"])
        self.assertEqual(code, 2)
        self.assertIn("database is unavailable", error)
        run.assert_not_called()

    def test_missing_deck_has_a_plain_failure_without_starting_games(self):
        with mock.patch.object(cli, "deck_entry", side_effect=decks.DeckNotFound("No deck 'casual/a'")), \
                mock.patch.object(cli, "run") as run:
            code, _, error = self.invoke(["plan", "casual/a", "casual/b"])
        self.assertEqual(code, 1)
        self.assertEqual(error.strip(), "No deck 'casual/a'")
        run.assert_not_called()

    def test_play_refuses_an_unready_engine_without_claiming_completion(self):
        with mock.patch.object(cli, "deck_entry", return_value={}), \
                mock.patch.object(cli, "plan", return_value={"engine_identities": {"xmage": None}}), \
                mock.patch.object(cli, "run") as run:
            code, _, error = self.invoke(["play", "casual/a", "casual/b"])
        self.assertEqual(code, 1)
        self.assertIn("not ready", error)
        run.assert_not_called()

    def test_play_holds_the_pc_awake_and_returns_nonzero_for_partial_evidence(self):
        active = []

        @contextlib.contextmanager
        def hold():
            active.append(True)
            try:
                yield
            finally:
                active.pop()

        def play(plan):
            self.assertEqual(active, [True])
            return {"status": "partial"}

        with mock.patch.object(cli, "deck_entry", return_value={}), \
                mock.patch.object(cli, "plan", return_value={"engine_identities": {"xmage": "a" * 64}}), \
                mock.patch.object(cli, "run", side_effect=play), \
                mock.patch.object(cli, "view", return_value={"schema": 1, "status": "partial"}), \
                mock.patch("decklab.lib.keepawake.hold_while", side_effect=hold):
            code, output, _ = self.invoke(["play", "casual/a", "casual/b", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["status"], "partial")
        self.assertEqual(active, [])
