"""Tests for Deck Lab's time estimates (decklab/lib/forge/estimate.py, simulation wave 3;
forge-trial/sim-wave3-contract.md section 9.5): rates.json over the defaults, a pair's rate from its
saved v2 runs, else its v1 games' median Forge time over the warm speed-up, else the format's slow
class; minutes() over pairs with the slower list's rate and the tail allowance at the high end; and
the matchup page's estimates.

Run from the repo root: python -m unittest decklab.tests.test_forge_estimate
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib.forge import common, estimate, saved

A = {"card_sha": "a" * 64, "kind": "constructed"}
B = {"card_sha": "b" * 64, "kind": "constructed"}
C = {"card_sha": "c" * 64, "kind": "constructed"}
CMD = [{"card_sha": "d" * 64, "kind": "commander"}, {"card_sha": "e" * 64, "kind": "commander"}]


def side(sha):
    return {"card_sha": sha, "dck": "", "card_count": 60, "kind": "constructed", "seen_as": []}


def v2_result(key, a, b, runs):
    """A v2 result of a and b whose runs are (played, wall_s) in the warm pool."""
    games = [{"g": i, "w": i % 2, "r": "win", "first": i % 2, "rounds": 5, "ms": 500} for i in range(sum(p for p, _ in runs))]
    return {"key": key, "format": "Constructed", "run_version": 2, "updated": "2026-10-03T10:00:00",
            "seeds": {"base": 1, "stream": "0" * 16, "flip": 0}, "next_game": len(games),
            "sides": [side(a["card_sha"]), side(b["card_sha"])],
            "runs": [{"played": p, "wall_s": w, "pool": "local"} for p, w in runs],
            "batches": [{"n": 0, "first": 0, "games": games, "casts": [{}, {}], "lands": [{}, {}]}] if games else [],
            "failed": []}


def v1_result(key, a, b, ms, games=40):
    return {"key": key, "format": "Constructed", "run_version": 1, "updated": "2026-10-03T10:00:00",
            "sides": [side(a["card_sha"]), side(b["card_sha"])], "runs": [{"played": games, "wall_s": 99.0}],
            "batches": [{"n": 0, "seed": 1, "games": [{"w": 0, "r": "win", "first": 0, "rounds": 5, "ms": ms}] * games,
                         "casts": [{}, {}], "lands": [{}, {}]}], "failed": []}


class EstimateCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.results = self.tmp / "results"
        self.results.mkdir()
        self.settings = {"forge_workers": 16}
        for p in (mock.patch.object(common, "DATA_DIR", self.tmp),
                  mock.patch.object(common, "_settings", lambda: dict(self.settings))):
            p.start()
            self.addCleanup(p.stop)
        saved._read_cache.clear()

    def save(self, result):
        (self.results / f"{result['key']}.json").write_text(json.dumps(result), encoding="utf-8")


class RateTests(EstimateCase):

    def test_rates_json_over_the_defaults(self):
        self.assertEqual(estimate.rates(), estimate.DEFAULT_RATES)
        (self.tmp / estimate.RATES_FILE).write_text(json.dumps({"rates": {"board": 300, "fast": -1, "medium": "x",
                                                                          "speed_up": 2.5, "other": 3}}))
        self.assertEqual(estimate.rates(), dict(estimate.DEFAULT_RATES, board=300.0, speed_up=2.5))
        (self.tmp / estimate.RATES_FILE).write_text(json.dumps({"commander": 150}))       # top level works too
        self.assertEqual(estimate.rates()["commander"], 150.0)
        (self.tmp / estimate.RATES_FILE).write_text("{not json")
        with mock.patch.object(common, "_log") as log:
            self.assertEqual(estimate.rates(), estimate.DEFAULT_RATES)
        log.assert_called_once()

    def test_the_combined_runs_workload_rates(self):
        # overnight_report.py's rates.json: warm games a minute per workload. IG is "fast", RV "board",
        # GF "commander"; a named class wins over them.
        (self.tmp / estimate.RATES_FILE).write_text(json.dumps(
            {"version": 1, "warm_games_per_min": {"IG": 410.5, "RV": 330.0, "GF": 180.2}, "from": "B2"}))
        self.assertEqual(estimate.rates(), dict(estimate.DEFAULT_RATES, fast=410.5, board=330.0, commander=180.2))
        (self.tmp / estimate.RATES_FILE).write_text(json.dumps(
            {"warm_games_per_min": {"IG": 410.5, "GF": None}, "rates": {"board": 300}}))
        self.assertEqual(estimate.rates(), dict(estimate.DEFAULT_RATES, fast=410.5, board=300.0))

    def test_a_rates_file_with_nothing_read_is_logged_once(self):
        (self.tmp / estimate.RATES_FILE).write_text(json.dumps({"version": 1, "games_a_minute": {"IG": 400}}))
        estimate._rates_said.clear()
        self.addCleanup(estimate._rates_said.clear)
        with mock.patch.object(common, "_log") as log:
            self.assertEqual(estimate.rates(), estimate.DEFAULT_RATES)
            self.assertEqual(estimate.rates(), estimate.DEFAULT_RATES)
        log.assert_called_once()
        self.assertIn("none of the rates", log.call_args[0][0])

    def test_a_pair_without_games_takes_its_formats_slow_class(self):
        self.assertEqual(estimate.pair_rate(A, B, self.results), 280)
        self.assertEqual(estimate.pair_rate(*CMD, results_dir=self.results), 200)
        self.settings["forge_workers"] = 8                        # half the workers: half the rate
        self.assertEqual(estimate.pair_rate(A, B, self.results), 140)

    def test_saved_v2_runs_give_the_pairs_rate(self):
        self.save(v2_result("1" * 64, A, B, [(400, 30.0), (200, 10.0)]))
        self.assertEqual(estimate.pair_rate(B, A, self.results), 900.0)      # 600 games in 40 s

    def test_v1_games_give_a_rate_through_the_warm_speed_up(self):
        self.save(v1_result("2" * 64, A, C, ms=2000))
        # 16 workers × 60,000 ms / (2,000 ms / 2.0) = 960 games a minute.
        self.assertEqual(estimate.pair_rate(A, C, self.results), 960.0)
        self.save(v1_result("3" * 64, B, C, ms=2000, games=5))               # too few games to stand for it
        self.assertEqual(estimate.pair_rate(B, C, self.results), 280)

    def test_minutes_over_pairs(self):
        self.assertIsNone(estimate.minutes([], self.results))
        self.save(v2_result("1" * 64, A, B, [(1400, 60.0)]))                 # A v B: 1,400 a minute
        low, high = estimate.minutes([(A, B, 1400)], self.results)
        self.assertEqual((low, high), (1.0, 1.2))                           # both lists' own rate is the pair's
        # A v C has no games: the slow class, 280 a minute; and A's slower list rate doesn't apply (its own is
        # the faster pair's), so the high end is C's slow class with the tail allowance.
        low, high = estimate.minutes([(A, B, 1400), (A, C, 280)], self.results)
        self.assertEqual(low, 2.0)
        self.assertEqual(high, round(1.2 + 1.2, 2))

    def test_the_matchup_pages_estimates(self):
        found = estimate.matchup(A, B, [], choices=[200, 400])
        self.assertEqual(set(found), {"fixed", "assess", "ahead"})
        self.assertEqual(set(found["fixed"]), {"200", "400"})
        self.assertLess(found["fixed"]["200"][0], found["fixed"]["400"][0])
        for span in [*found["fixed"].values(), found["assess"], found["ahead"]]:
            self.assertLessEqual(span[0], span[1])
        # "ahead" from the next check (400) to the last (3,200 games).
        self.assertEqual(found["ahead"][0], round(400 / 280, 2))
        self.assertEqual(found["ahead"][1], round(3200 / 280 * 1.2, 2))
        games = [{"g": i, "w": 0, "first": i % 2} for i in range(3200)]
        self.assertEqual(estimate.matchup(A, B, games, choices=[200])["ahead"], [0.0, 0.0])
        self.assertIsNone(estimate.matchup({"kind": "constructed"}, B, []))


if __name__ == "__main__":
    unittest.main()
