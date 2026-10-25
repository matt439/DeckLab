"""Tests for how a Forge run is split into batches (forge.plan, lists._batch_count), the
page's copy of that rule (matchups.js's batchPlan and roughMinutes), and Forge's Java
flags (runner.JVM_FLAGS).

Since 2026-10-03 (forge-trial/sim-investigation.md, R02 and R01a) a run is split into
the largest even number of batches, at least 2 and at most min(workers, games // 25),
that divides it, instead of 100-game batches below 3,200 games; config.json's
forge_batch_games no longer changes anything. Each Forge process is started with
-XX:ActiveProcessorCount=2. Neither changes the games a seed plays, so saved results
stay valid.

The page's copy runs under Node.js (test_web's _run_page) when it's installed.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import config, forge
from decklab.lib.forge import lists, runner
from decklab.tests.test_web import NODE, _run_page

_build_command = runner.build_command       # test_forge's setUpModule puts a fake in its place while it runs

# (workers, games) -> (batches, games each), as R02 gives them.
REPORT_PLANS = {
    (16, 200): (8, 25), (16, 400): (16, 25), (16, 800): (16, 50), (16, 1600): (16, 100), (16, 3200): (16, 200),
    (8, 200): (8, 25), (8, 400): (8, 50), (8, 800): (8, 100), (8, 1600): (8, 200), (8, 3200): (8, 400),
    (12, 200): (8, 25), (12, 400): (10, 40), (12, 800): (10, 80), (12, 1600): (10, 160), (12, 3200): (10, 320),
}
JS_WORKERS = (1, 2, 3, 4, 5, 8, 12, 16, 24, 32)     # the page's copy is checked at these (8, 12 and 16 above all)


def best_count(games, workers):
    """The rule written out the long way: every even count from 2 up to the cap that divides
    games, the largest kept; 1 when there's none."""
    cap = max(2, min(workers, games // lists.SMALL_BATCH))
    counts = [k for k in range(2, cap + 1) if k % 2 == 0 and games % k == 0]
    return max(counts, default=1)


class BatchPlanCase(unittest.TestCase):
    """config.json's numbers are made up per test (forge.common._settings)."""

    def setUp(self):
        self.settings = {"forge_workers": 16, "forge_batch_games": 200}
        patch = mock.patch.object(forge.common, "_settings", lambda: dict(self.settings))
        patch.start()
        self.addCleanup(patch.stop)


class BatchCountTests(BatchPlanCase):

    def test_the_report_plans(self):
        for (workers, games), (count, size) in REPORT_PLANS.items():
            batches = forge.plan(games, workers=workers)
            self.assertEqual((len(batches), {b["games"] for b in batches}), (count, {size}), (workers, games))

    def test_every_choice_and_worker_count_keeps_the_rule(self):
        # Even, at least 2, one wave (no more batches than workers, once there are 2), at least SMALL_BATCH
        # games each, all the games, and the largest such count.
        for workers in range(1, 41):
            for games in forge.GAME_CHOICES:
                batches = forge.plan(games, workers=workers)
                count, size = len(batches), batches[0]["games"]
                with self.subTest(workers=workers, games=games):
                    self.assertEqual(count % 2, 0)
                    self.assertGreaterEqual(count, 2)
                    self.assertLessEqual(count, max(2, workers))
                    self.assertGreaterEqual(size, lists.SMALL_BATCH)
                    self.assertEqual({b["games"] for b in batches}, {size})
                    self.assertEqual(count * size, games)
                    self.assertEqual(count, best_count(games, workers))

    def test_one_worker_plays_two_batches_one_after_the_other(self):
        # No even count fits under 1 worker: still 2, so each side is deck 1 in one of them.
        for games in forge.GAME_CHOICES:
            batches = forge.plan(games, workers=1)
            self.assertEqual([(b["n"], b["seed"], b["games"], b["deck1"]) for b in batches],
                             [(0, 1, games // 2, 0), (1, 2, games // 2, 1)])
        self.assertEqual(lists._batch_count(200, 2), 2)
        self.assertEqual(lists._batch_count(200, 3), 2)       # an odd number of workers: the even one below
        self.assertEqual(lists._batch_count(200, 5), 4)

    def test_runs_under_fifty_games(self):
        # Not a games choice, so plan() never asks; the rule still gives an answer: 2 batches when 2
        # divides the games (fewer than SMALL_BATCH each), else 1.
        self.assertEqual([lists._batch_count(g, 16) for g in (1, 2, 30, 48, 49, 50, 75, 150)],
                         [1, 2, 2, 2, 1, 2, 1, 6])
        self.assertEqual(lists._batch_count(30, 1), 2)
        for games in (1, 2, 30, 49):
            self.assertEqual(lists._batch_count(games, 16), best_count(games, 16))

    def test_more_workers_than_the_pc_has(self):
        self.assertEqual(lists._batch_count(3200, 32), 32)
        self.assertEqual(lists._batch_count(3200, 128), 128)
        self.assertEqual(lists._batch_count(3200, 1000), 128)      # 25 games each at least

    def test_workers_come_from_config_and_forge_batch_games_no_longer_counts(self):
        self.settings["forge_workers"] = 12
        self.assertEqual(len(forge.plan(400)), 10)
        for big in (1, 100, 200, 400, 3200, "lots", None):
            self.settings["forge_batch_games"] = big
            self.assertEqual([b["games"] for b in forge.plan(400)], [40] * 10, big)
            self.assertEqual([b["games"] for b in forge.plan(3200, workers=16)], [200] * 16, big)
        # _batch_size no longer takes it.
        self.assertEqual(forge.lists._batch_size(800, 16, None), 50)
        with self.assertRaises(TypeError):
            forge.lists._batch_size(800, 16, None, 100)

    def test_bad_games_and_workers_still_fail(self):
        for games in (0, 50, 100, 300, 5000):
            with self.assertRaises(ValueError):
                forge.plan(games, workers=16)
        for workers in (0, -1):
            with self.assertRaises(ValueError):
                forge.plan(800, workers=workers)
        self.settings["forge_workers"] = 0
        with self.assertRaises(ValueError):
            forge.plan(800)


class BatchNumberingTests(BatchPlanCase):
    """Seeds, n, deck 1 and the rules for an explicit batch and earlier batches are as they were."""

    def test_seeds_and_deck_order(self):
        batches = forge.plan(800, workers=16)
        self.assertEqual([(b["n"], b["seed"], b["deck1"]) for b in batches],
                         [(n, n + 1, n % 2) for n in range(16)])
        self.assertEqual([b["seed"] for b in forge.plan(200, workers=16, seed_base=210000)],
                         list(range(210000, 210008)))

    def test_more_games_go_on_from_the_highest_seed_failed_and_partial_included(self):
        existing = {"batches": [{"n": 0, "seed": 1}, {"n": 2, "seed": 3, "partial": True}],
                    "failed": [{"n": 1, "seed": 2}, {"n": 3, "seed": 9}]}
        batches = forge.plan(400, existing, workers=16)
        self.assertEqual([(b["n"], b["seed"], b["deck1"], b["games"]) for b in batches],
                         [(4 + i, 10 + i, i % 2, 25) for i in range(16)])
        # seed_base only counts for a result with no batches yet.
        self.assertEqual(forge.plan(400, existing, workers=16, seed_base=210000)[0]["seed"], 10)

    def test_an_explicit_batch_keeps_its_size(self):
        self.assertEqual([(b["seed"], b["games"], b["deck1"]) for b in forge.plan(400, batch=200, seed_base=210000)],
                         [(210000, 200, 0), (210001, 200, 1)])
        self.assertEqual([b["games"] for b in forge.plan(800, workers=16, batch=100)], [100] * 8)
        self.assertEqual([b["games"] for b in forge.plan(30, workers=2, batch=10)], [10] * 3)     # odd counts too
        for games, batch in ((30, 7), (0, 10), (30, 0)):
            with self.assertRaises(ValueError):
                forge.plan(games, workers=16, batch=batch)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PageCopyTests(unittest.TestCase):
    """matchups.js's batchPlan and roughMinutes, run: they split a run as forge.plan does."""

    def test_batch_plan_matches_forge_plan(self):
        cases = [(games, workers) for workers in JS_WORKERS for games in forge.GAME_CHOICES]
        calls = [f"JSON.stringify(batchPlan({games}, {workers}))" for games, workers in cases]
        with mock.patch.object(forge.common, "_settings", lambda: {"forge_workers": 16, "forge_batch_games": 200}):
            for (games, workers), answer in zip(cases, _run_page(calls), strict=True):
                batches = forge.plan(games, workers=workers)
                self.assertEqual(json.loads(answer), {"batches": len(batches), "size": batches[0]["games"]},
                                 (games, workers))

    def test_batch_plan_matches_the_rule_off_the_choices(self):
        cases = [(games, workers) for workers in (1, 2, 7, 16) for games in (1, 2, 30, 49, 50, 75, 150, 1000, 2400)]
        calls = [f"JSON.stringify(batchPlan({games}, {workers}))" for games, workers in cases]
        for (games, workers), answer in zip(cases, _run_page(calls), strict=True):
            count = lists._batch_count(games, workers)
            self.assertEqual(json.loads(answer), {"batches": count, "size": games // count}, (games, workers))

    def test_rough_time_follows_the_games_in_one_batch(self):
        # Every batch goes at once (2 one after the other with 1 worker), so the time is one batch's games.
        cases = [(games, workers) for workers in (1, 8, 12, 16) for games in forge.GAME_CHOICES]
        calls = [f"JSON.stringify(roughMinutes({games}, false, {{ workers: {workers} }})"
                 ".map((m) => m * PROCESS_GAMES_PER_MIN))" for games, workers in cases]
        for (games, workers), answer in zip(cases, _run_page(calls), strict=True):
            each = games if workers == 1 else games // lists._batch_count(games, workers)
            self.assertAlmostEqual(json.loads(answer)[0], each, places=6, msg=(games, workers))
        # The page's usual 16 workers, and its words: 200 games are 8 x 25, 3,200 16 x 200.
        default, small, big = _run_page(["JSON.stringify(roughMinutes(800).map((m) => m * PROCESS_GAMES_PER_MIN))",
                                         "roughTimeWords(200)", "roughTimeWords(3200)"])
        self.assertAlmostEqual(json.loads(default)[0], 50)
        # One estimate in words (the UI review's MU-05): the span from all workers free to the PC busy.
        self.assertEqual(small, "about 1-2 minutes")
        self.assertEqual(big, "about 4-14 minutes")

    def test_the_servers_worker_count_wins_and_batch_games_is_ignored(self):
        answers = _run_page(["JSON.stringify(batching({ workers: 12, batch_games: 100 }))",
                             "JSON.stringify(batching({ batch_games: 400 }))", "JSON.stringify(batching(null))",
                             "JSON.stringify(batching({ workers: null, batch_games: null }))"])
        self.assertEqual([json.loads(a) for a in answers],
                         [{"workers": 12}, {"workers": 16}, {"workers": 16}, {"workers": 16}])
        self.assertEqual(16, config.DEFAULTS["forge_workers"])


class JvmFlagTests(unittest.TestCase):
    """Forge's processes start with -XX:ActiveProcessorCount=2 (R01a)."""

    SETUP = {"java": "C:/jdk/bin/java.exe", "xmx": "1024m", "jar": "forge-gui-desktop-2.0.15-jar-with-dependencies.jar",
             "decks_dir": Path("D:/decks"), "clock_s": 120}

    def test_the_flag_is_set_once(self):
        self.assertIn("-XX:ActiveProcessorCount=2", runner.JVM_FLAGS)
        self.assertEqual([f for f in runner.JVM_FLAGS if f.startswith("-XX:ActiveProcessorCount")],
                         ["-XX:ActiveProcessorCount=2"])

    def test_every_command_gives_it_to_java_before_forge(self):
        card_log = {"ready": True, "jar": "decklab-sim.jar", "main": "decklab.DeckLabSim",
                    "add_opens": ["--add-opens", "java.desktop/java.beans=ALL-UNNAMED"]}
        for setup, start in ((self.SETUP, "-jar"), (dict(self.SETUP, card_log=card_log), "-cp"),
                             (dict(self.SETUP, card_log={"ready": False}), "-jar")):
            command = _build_command(setup, "Constructed", "a.dck", "b.dck", 50, 3)
            self.assertEqual(command.count("-XX:ActiveProcessorCount=2"), 1)
            self.assertLess(command.index("-XX:ActiveProcessorCount=2"), command.index(start))
            self.assertEqual(command[:2], ["C:/jdk/bin/java.exe", "-Xmx1024m"])
            self.assertEqual(command[2:2 + len(runner.JVM_FLAGS)], list(runner.JVM_FLAGS))


if __name__ == "__main__":
    unittest.main()
