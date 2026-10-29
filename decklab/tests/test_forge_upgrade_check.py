"""Tests for upgrade-check (python -m decklab.lib.forge upgrade-check, E11-S15): after a new build
of Deck Lab's Forge is installed, cardlog-check, serve-check and the overrides' upstream check
run in order, going on past a failure, with one summary, and what replay --dry-run would play
when the engine changed.

No Forge process starts: each step's command is a stand-in that prints and returns what a test
asks (or raises), and Forge's setup and replay's plan are stand-ins too, except in
UpgradeReplayTests, which uses test_forge_replay's saved results to show the replay part is
replay --dry-run's own output.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_forge_upgrade_check
"""
import pathlib
import unittest
from unittest import mock

from decklab.lib import forge
from decklab.lib.forge import cli_checks, cli_commands, cli_results, cli_shared, cli_upgrade
from decklab.tests import test_forge, test_forge_replay


def setUpModule():
    test_forge_replay.setUpModule()


def tearDownModule():
    test_forge_replay.tearDownModule()


def step(code=0, lines=(), raises=None):
    """A stand-in for a step's command: prints lines, then raises or returns code."""
    def command(args):
        for line in lines:
            print(line)
        if raises is not None:
            raise raises
        return code
    return mock.Mock(side_effect=command)


def plan_item(a, b, games, target, have, per_game_s, fmt="Constructed"):
    return {"a": {"title": a, "version": "target"}, "b": {"title": b, "version": "target"}, "format": fmt,
            "games": games, "target": target, "have": have, "per_game_s": per_game_s}


class UpgradeCheckTests(unittest.TestCase):

    def setUp(self):
        self.cardlog = step(lines=["The card log played the same 12 Constructed and 3 Commander games."])
        self.serve = step(lines=["A warm worker played the same games as fresh processes."])
        self.overrides = step(lines=["Every override is Forge's script with its edits, made from this Forge's scripts."])
        self.setup = mock.Mock(return_value={"version": "2.0.16-decklab-abc1234"})
        self.plan = mock.Mock(return_value=[])
        self.status = mock.Mock(return_value={"card_log": {"ready": True, "problem": None}})
        for p in (mock.patch.object(cli_shared, "status", self.status),mock.patch.object(cli_checks, "_cmd_cardlog_check", self.cardlog),
                  mock.patch.object(cli_checks, "_cmd_serve_check", self.serve),
                  mock.patch.object(cli_commands, "_cmd_overrides", self.overrides),
                  mock.patch.object(cli_shared, "_setup", self.setup),
                  mock.patch.object(forge.install, "forge_version", return_value="2.0.16-decklab-abc1234"),
                  mock.patch.object(forge.engine, "today", return_value={"forge": "2.0.16+res.0123456789ab"}),
                  mock.patch.object(forge.pool, "_workers_setting", return_value=4),
                  mock.patch.object(cli_results, "_replay_plan", self.plan)):
            p.start()
            self.addCleanup(p.stop)

    def run_main(self, *argv):
        """(exit code, stdout, stderr) of upgrade-check with argv."""
        return test_forge.CommandLineTests.run_main(self, "upgrade-check", *argv)

    def summary(self, out):
        """The summary's step lines."""
        lines = out.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("Upgrade check"))
        return lines[start:start + 4]

    def test_it_is_a_command(self):
        self.assertEqual(forge.cli.COMMANDS["upgrade-check"],
                         (cli_upgrade._upgrade_check_args, cli_upgrade._cmd_upgrade_check))
        self.assertEqual(cli_upgrade.UPGRADE_STEPS, tuple(name for name, *_ in cli_upgrade._steps()))

    def test_every_step_passed(self):
        code, out, err = self.run_main()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.summary(out), ["Upgrade check of Forge 2.0.16-decklab-abc1234:",
                                             "  cardlog-check: passed", "  serve-check: passed",
                                             "  overrides check: passed"])
        self.assertTrue(out.endswith("No saved matchup needs replaying: every current matchup has as many games "
                                     "with today's engine.\nEvery check passed.\n"))
        # In order, each step's own output shown under its name, each with its command's defaults.
        self.assertLess(out.index("== cardlog-check =="), out.index("The card log played the same"))
        self.assertLess(out.index("The card log played the same"), out.index("== serve-check =="))
        self.assertLess(out.index("== serve-check =="), out.index("== overrides check =="))
        self.assertLess(out.index("Every override is Forge's script"), out.index("Upgrade check of"))
        args = self.cardlog.call_args.args[0]
        self.assertEqual((args.games, args.commander_games), (cli_checks.CHECK_GAMES, cli_checks.CHECK_COMMANDER_GAMES))
        args = self.serve.call_args.args[0]
        self.assertEqual((args.games, args.commander_games, args.v1),
                         (forge.servecheck.GAMES, forge.servecheck.COMMANDER_GAMES, False))
        args = self.overrides.call_args.args[0]
        self.assertEqual((args.action, args.json, args.set_name), ("check", False, None))     # never make

    def test_a_failed_step_is_said_and_the_rest_go_on(self):
        self.cardlog.side_effect = step(1, ["The card log changed the Constructed games it was kept in (Forge 2.0.16): "
                                            "game 3, line 40: ...",
                                            "Runs with Forge 2.0.16 go without the card log until a check passes."]
                                        ).side_effect
        code, out, err = self.run_main()
        self.assertEqual(code, 1, err)
        self.assertEqual(self.summary(out)[1:], [
            "  cardlog-check: failed: The card log changed the Constructed games it was kept in (Forge 2.0.16): game 3, "
            "line 40: ...", "  serve-check: passed", "  overrides check: passed"])
        self.serve.assert_called_once()
        self.overrides.assert_called_once()
        self.assertTrue(out.endswith("1 of 3 checks didn't pass: fix what's above and run upgrade-check again.\n"))

    def test_a_step_that_ends_with_an_error(self):
        self.serve.side_effect = step(raises=forge.ForgeError("Forge stopped answering.")).side_effect
        code, out, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(self.summary(out)[2:], ["  serve-check: failed: Forge stopped answering.",
                                                 "  overrides check: passed"])
        self.assertIn("Error: Forge stopped answering.", err)
        # A step that failed without saying why.
        self.serve.side_effect = step(1).side_effect
        self.assertIn("  serve-check: failed: it ended with exit code 1", self.run_main()[1])

    def test_an_unexpected_error_is_a_failed_step_and_the_rest_go_on(self):
        self.cardlog.side_effect = step(raises=OSError(28, "No space left on device")).side_effect
        code, out, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(self.summary(out)[1:], ["  cardlog-check: failed: OSError: [Errno 28] No space left on device",
                                                 "  serve-check: passed", "  overrides check: passed"])
        self.serve.assert_called_once()
        self.overrides.assert_called_once()
        self.assertIn("cardlog-check failed:\nTraceback (most recent call last):", err)     # logged for a bug

    def test_serve_check_is_skipped_when_the_card_log_cant_be_built(self):
        self.cardlog.side_effect = step(raises=cli_checks._CardLogUnavailable("Java's javac wasn't found.")).side_effect
        code, out, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(self.summary(out)[1:], [
            "  cardlog-check: failed: Java's javac wasn't found.",
            "  serve-check: skipped: cardlog-check couldn't build the card log, which it needs too: Java's javac "
            "wasn't found.",
            "  overrides check: passed"])
        self.serve.assert_not_called()
        self.assertTrue(out.endswith("2 of 3 checks didn't pass: fix what's above and run upgrade-check again.\n"))

    def test_serve_check_runs_when_cardlog_check_failed_after_building_the_card_log(self):
        problem = ("The check's Constructed games couldn't be played with plain Forge. A game hit one of Forge's "
                   "time limits.")
        self.cardlog.side_effect = step(raises=cli_shared._CliError(problem)).side_effect
        code, out, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(self.summary(out)[1:], [f"  cardlog-check: failed: {problem}", "  serve-check: passed",
                                                 "  overrides check: passed"])
        self.serve.assert_called_once()

    def test_cardlog_check_says_when_the_card_log_cant_be_built(self):
        """cardlog-check's own refusals before it plays are _CardLogUnavailable, its later ones not."""
        with mock.patch.object(cli_shared, "_setup", return_value={
                "version": "2.0.16", "java": "java", "forge_dir": pathlib.Path("."), "jar": "forge.jar"}), \
                mock.patch.object(cli_shared.simjar, "forge_build", return_value="b"), \
                mock.patch.object(cli_shared.simjar, "source_sha256", return_value="s"), \
                mock.patch.object(cli_shared.simjar, "card_log", return_value={"ready": False, "problem": "No javac."}):
            with self.assertRaises(cli_checks._CardLogUnavailable) as caught:
                cli_checks._cardlog_check(1, 1)
            self.assertEqual(str(caught.exception), "No javac.")
            with mock.patch.object(cli_shared.simjar, "source_sha256", side_effect=OSError("gone")):
                with self.assertRaises(cli_checks._CardLogUnavailable) as caught:
                    cli_checks._cardlog_check(1, 1)
            self.assertEqual(str(caught.exception), cli_shared.simjar.NO_SOURCE)
        self.assertTrue(issubclass(cli_checks._CardLogUnavailable, cli_shared._CliError))     # main() says it as one

    def test_the_games_are_skipped_when_forge_cant_be_started(self):
        self.setup.side_effect = forge.ForgeError("Java wasn't found, so Forge can't run.")
        code, out, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(self.summary(out)[1:], [
            "  cardlog-check: skipped: Forge can't be started: Java wasn't found, so Forge can't run.",
            "  serve-check: skipped: Forge can't be started: Java wasn't found, so Forge can't run.",
            "  overrides check: passed"])
        self.cardlog.assert_not_called()
        self.serve.assert_not_called()

    def test_overrides_that_no_longer_fit(self):
        self.overrides.side_effect = step(1, [f"! Card {n} (fixes): Forge's script isn't the one the override was "
                                              "made from" for n in (1, 2, 3)]).side_effect
        code, out, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(self.summary(out)[3], "  overrides check: failed: Card 1 (fixes): Forge's script isn't the "
                                               "one the override was made from (2 more above)")

    def test_what_needs_replaying_when_the_engine_changed(self):
        self.plan.return_value = [plan_item("Green", "Red", 500, 800, 300, 0.1),
                                  plan_item("Gisa", "Gisa", 100, 100, 0, 0.4, "Commander")]
        code, out, err = self.run_main()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.plan.call_args.args, (None, {"forge": "2.0.16+res.0123456789ab"}))
        self.assertIn("\nThe engine changed: 2 saved matchups were played with another engine than today's "
                      "(Forge 2.0.16+res.0123456789ab). replay --dry-run says:\n"
                      "Green (target) vs Red (target): 500 games (the most with an earlier engine 800, with today's 300)\n"
                      "Gisa (target) vs Gisa (target), Commander: 100 games (the most with an earlier engine 100, "
                      "with today's 0)\n"
                      "2 matchups to replay, 600 games.\n"
                      "That's about 1 minute with 4 games at once (forge_workers), going by", out)
        self.assertIn("\npython -m decklab.lib.forge replay plays them again, on an idle PC.\nEvery check passed.\n", out)
        # It goes by whether the card log can be used now, as replay --dry-run does, not by this run's
        # cardlog-check: one that couldn't tell leaves an earlier pass standing, so replay would play.
        self.cardlog.side_effect = step(1, ["A game hit one of Forge's time limits.",
                                            "Nothing was noted, so runs with Forge 2.0.16 go on as they were."]
                                        ).side_effect
        out = self.run_main()[1]
        self.assertIn("The engine changed: 2 saved matchups", out)
        self.assertIn("\npython -m decklab.lib.forge replay plays them again, on an idle PC.\n", out)
        # While the card log can't be used, replay refuses, and the check says so and why.
        self.cardlog.side_effect = step().side_effect
        self.status.return_value = {"card_log": {"ready": False, "problem": "Forge 2.0.16's card log check failed."}}
        out = self.run_main()[1]
        self.assertIn("\npython -m decklab.lib.forge replay plays them again, on an idle PC, once the card log can be "
                      "used (until then it refuses: Forge 2.0.16's card log check failed.)\n", out)

    def test_the_plan(self):
        code, out, err = self.run_main("--plan", "forge-2.0.16")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("Moving Deck Lab's Forge onto forge-2.0.16"))
        for words in ("rebase the decklab branch onto the tag forge-2.0.16", "BASE_TAG", "install.py --out",
                      "engine-check --old", "git merge --ff-only", "upgrade-check", "simjar.CHECKED", "replay"):
            self.assertIn(words, out)
        # A new release's engine-check can't pass as step 3 of a fork change does: say what to accept.
        self.assertIn("A new release is always a different engine key, so exit 1 with \"Different engine key\" and no "
                      "\"Don't install this build as it is\" line is what to expect (0 or 3 if no game changed); only "
                      "exit 2 (it couldn't run) or a \"Don't install\" line stops the upgrade.", out)
        for command in (self.cardlog, self.serve, self.overrides, self.setup, self.plan):
            command.assert_not_called()
        code, _, err = self.run_main("--plan", " ")
        self.assertEqual(code, 1)
        self.assertIn("--plan needs a release tag", err)


class UpgradeReplayTests(test_forge_replay.ReplayTests):
    """The replay part is replay --dry-run's own lines, from the same saved results."""

    def test_the_replay_part_is_the_dry_runs(self):
        self.earlier_results()
        code, dry, err = self.replay("--dry-run")
        self.assertEqual(code, 0, err)
        plan = cli_results._replay_plan
        passed = mock.Mock(return_value=0)
        with mock.patch.object(cli_results, "_replay_plan", lambda _, eng: plan(self.results, eng)), \
                mock.patch.object(cli_checks, "_cmd_cardlog_check", passed), \
                mock.patch.object(cli_checks, "_cmd_serve_check", passed), \
                mock.patch.object(cli_commands, "_cmd_overrides", passed):
            code, out, err = self.run_main("upgrade-check")
        self.assertEqual(code, 0, err)
        self.assertIn("The engine changed: 3 saved matchups were played with another engine than today's", out)
        self.assertIn("replay --dry-run says:\n" + dry, out)
        self.assertEqual(self.calls, [])            # nothing played


def load_tests(loader, tests, pattern):
    """UpgradeCheckTests, and UpgradeReplayTests's own test only (not the replay tests it inherits,
    which test_forge_replay runs)."""
    suite = loader.loadTestsFromTestCase(UpgradeCheckTests)
    suite.addTest(UpgradeReplayTests("test_the_replay_part_is_the_dry_runs"))
    return suite


if __name__ == "__main__":
    unittest.main()
