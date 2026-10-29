"""Pure remaining-work experiment estimates: supplied plans and timing dictionaries only."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib.forge import common, estimate, experiment_estimate as timing, saved


def control(key="base", missing=900, **extra):
    return {"key": key, "pair": ["casual/a", "casual/b"], "card_shas": ["a", "b"],
            "kind": "constructed", "have": 0, "missing": missing, "source": "control", **extra}


def arm(key="arm", missing=900, **extra):
    return {**control(key, missing), "arm": key, "changes": ["pilot"], "sets": None,
            "config": None, "skipped": None, **extra}


def plan(controls=(), arms=()):
    return {"experiment": "fixture", "games": 999999, "controls": list(controls), "arms": list(arms),
            "totals": {"games": 999999, "control_games": 888888, "arm_games": 111111}}


def v2(row, runs=((400, 30, 16), (200, 10, 16))):
    return {"key": row["key"], "run_version": 2,
            "sides": [{"card_sha": sha} for sha in reversed(row["card_shas"])],
            "runs": [{"pool": "fixture-pool", "played": played, "wall_s": wall, "workers": workers}
                     for played, wall, workers in runs]}


def v1(row, times=None):
    return {"key": row["key"], "run_version": 1,
            "sides": [{"card_sha": sha} for sha in row["card_shas"]],
            "runs": [{"played": 50, "wall_s": 0.01}],
            "batches": [{"games": [{"ms": value} for value in ([2000] * 20 if times is None else times)]}]}


class ExperimentEstimateTests(unittest.TestCase):
    def test_weighted_pool_throughput_is_aggregate_and_not_divided_by_workers(self):
        row = control()
        found = timing.estimate_plan(plan([row]), samples={row["key"]: v2(row)}, workers=16)
        self.assertEqual(found["minutes"], [1.0, 1.2])
        self.assertEqual(found["remaining_games"], 900)
        self.assertEqual(found["basis"], "measured")
        detail, = found["controls"]
        self.assertEqual(detail["games_per_min"], 900)
        self.assertEqual(detail["sample_workers"], [16])
        self.assertEqual(detail["worker_context"], "known")
        self.assertIn(timing.POOL_AGGREGATE, found["assumptions"])

    def test_known_worker_mismatch_rejects_pool_rate_for_requested_worker_fallback(self):
        row = control(missing=280)
        found = timing.estimate_plan(plan([row]), samples={row["key"]: v2(row)}, workers=8)
        self.assertEqual(found["minutes"], [2.0, 2.4])
        detail, = found["controls"]
        self.assertEqual(detail["basis"], "fallback")
        self.assertEqual(detail["games_per_min"], 140)
        self.assertIsNone(detail["sample_key"])
        self.assertEqual(detail["rejected_sample"]["sample_workers"], [16])
        self.assertIn(timing.POOL_MISMATCH, found["assumptions"])

    def test_unknown_recorded_workers_remain_explicit_without_silent_scaling(self):
        row = control()
        for workers in (None, 8):
            sample = v2(row, [(400, 30, None), (200, 10, None)])
            found = timing.estimate_plan(plan([row]), samples={row["key"]: sample}, workers=workers)
            self.assertEqual(found["minutes"], [1.0, 1.2])
            detail, = found["controls"]
            self.assertEqual(detail["worker_context"], "unknown")
            self.assertIsNone(detail["sample_workers"])
            self.assertIsNone(found["assumed_workers"])
            self.assertIn(timing.POOL_UNKNOWN, found["assumptions"])
        self.assertIn(timing.POOL_PLANNING_UNKNOWN, timing.estimate_plan(
            plan([row]), samples={row["key"]: sample})["assumptions"])

    def test_mixed_historical_workers_do_not_normalize_or_hide_a_known_mismatch(self):
        row = control()
        sample = v2(row, [(400, 30, 4), (200, 10, 8)])
        found = timing.estimate_plan(plan([row]), samples={row["key"]: sample})
        self.assertEqual(found["minutes"], [1.0, 1.2])
        self.assertEqual(found["controls"][0]["worker_context"], "mixed")
        self.assertEqual(found["controls"][0]["sample_workers"], [4, 8])
        found = timing.estimate_plan(plan([row]), samples={row["key"]: sample}, workers=8)
        self.assertEqual(found["controls"][0]["basis"], "fallback")
        self.assertIn(timing.POOL_MISMATCH, found["assumptions"])

    def test_partial_unknown_context_with_known_mismatch_also_rejects_observation(self):
        row = control()
        found = timing.estimate_plan(plan([row]), samples={row["key"]: v2(
            row, [(400, 30, 16), (200, 10, None)])}, workers=8)
        self.assertEqual(found["controls"][0]["basis"], "fallback")
        self.assertEqual(found["controls"][0]["rejected_sample"]["worker_context"], "unknown")

    def test_v1_threshold_uses_only_finite_positive_samples_and_planning_workers(self):
        row = control(missing=480)
        valid = [2000] * 20 + [True, False, 0, -1, "2000", float("nan"), float("inf"), 10 ** 400]
        found = timing.estimate_plan(plan([row]), samples={row["key"]: v1(row, valid)}, workers=8)
        self.assertEqual(found["minutes"], [1.0, 1.2])
        self.assertEqual(found["controls"][0]["timing"], "v1")
        self.assertIn(timing.V1_RATE, found["assumptions"])
        found = timing.estimate_plan(plan([row]), samples={row["key"]: v1(row, [2000] * 19)}, workers=8)
        self.assertEqual(found["controls"][0]["basis"], "fallback")
        self.assertEqual(found["controls"][0]["games_per_min"], 140)

    def test_v1_unknown_worker_context_is_an_explicit_sixteen_worker_assumption(self):
        row = control(missing=960)
        found = timing.estimate_plan(plan([row]), samples={row["key"]: v1(row)})
        self.assertEqual(found["minutes"], [1.0, 1.2])
        self.assertIsNone(found["workers"])
        self.assertEqual(found["assumed_workers"], 16)
        self.assertIn(timing.UNKNOWN_WORKERS, found["assumptions"])

    def test_valid_pool_timing_takes_precedence_over_legacy_per_game_sample(self):
        row = control()
        sample = v1(row)
        sample["runs"] = v2(row)["runs"]
        found = timing.estimate_plan(plan([row]), samples={row["key"]: sample}, workers=16)
        self.assertEqual(found["controls"][0]["timing"], "v2")
        self.assertEqual(found["controls"][0]["games_per_min"], 900)

    def test_invalid_samples_leave_a_usable_format_fallback(self):
        row = control(missing=280)
        invalid = [None, [], "bad", {}, {**v2(row), "key": "other"},
                   {**v2(row), "sides": [{"card_sha": "other"}, {"card_sha": "b"}]},
                   {**v2(row), "sides": [None, "bad"]}, {**v2(row), "runs": "bad"}]
        for value in (0, -1, True, False, "1", float("nan"), float("inf"), 10 ** 400):
            sample = v2(row, [(100, 10, 16)])
            sample["runs"][0]["wall_s"] = value
            invalid.append(sample)
            sample = v2(row, [(100, 10, 16)])
            sample["runs"][0]["played"] = value
            invalid.append(sample)
        invalid.append(v2(row, [(1.5, 1, 16)]))
        invalid.append(v2(row, [(1, 1e308, 16), (1, 1e308, 16)]))
        invalid.append(v2(row, [(10 ** 308, 1, 16), (10 ** 308, 1, 16)]))
        for sample in invalid:
            with self.subTest(sample=sample):
                found = timing.estimate_plan(plan([row]), samples={row["key"]: sample}, workers=16)
                self.assertTrue(found["complete"])
                self.assertEqual(found["minutes"], [1.0, 1.2])
                self.assertEqual(found["controls"][0]["basis"], "fallback")
                json.dumps(found, allow_nan=False)

    def test_malformed_pool_markers_are_not_treated_as_aggregate_evidence(self):
        row = control(missing=280)
        for marker in (True, 1, ["local"], {"pool": "local"}, "", " ", None):
            sample = v2(row, [(900, 1, 16)])
            sample["runs"][0]["pool"] = marker
            found = timing.estimate_plan(plan([row]), samples={row["key"]: sample}, workers=16)
            self.assertEqual(found["controls"][0]["basis"], "fallback")
            self.assertEqual(found["minutes"], [1.0, 1.2])
        legacy = v1(row)
        legacy["runs"] = [{"pool": True, "played": 900, "wall_s": 1}]
        found = timing.estimate_plan(plan([row]), samples={row["key"]: legacy}, workers=16)
        self.assertEqual(found["controls"][0]["timing"], "v1")

    def test_bad_runs_are_ignored_without_diluting_good_weighted_pool_timings(self):
        row = control()
        sample = v2(row)
        sample["runs"] += [None, "bad", {"pool": "fixture", "played": True, "wall_s": 0.1},
                           {"pool": "fixture", "played": 9000, "wall_s": float("inf")},
                           {"played": 9000, "wall_s": 0.1}]
        found = timing.estimate_plan(plan([row]), samples={row["key"]: sample}, workers=16)
        self.assertEqual(found["controls"][0]["games_per_min"], 900)

    def test_fallback_rates_are_format_specific_and_validate_supplied_rate_values(self):
        base, commander = control(missing=140), control("cmd", 100, kind="commander")
        found = timing.estimate_plan(plan([base, commander]), rates={"board": 280, "commander": 200,
            "speed_up": float("nan"), "fast": True}, workers=8)
        self.assertEqual(found["minutes"], [2.0, 2.4])
        found = timing.estimate_plan(plan([control(missing=280)]), rates={"board": float("inf")}, workers=16)
        self.assertEqual(found["minutes"], [1.0, 1.2])
        self.assertEqual(found["basis"], "fallback")

    def test_bad_planning_worker_values_are_unknown_not_claimed_as_measured(self):
        for workers in (True, False, 0, -1, 8.0, "8", float("nan"), float("inf"), 10 ** 400):
            found = timing.estimate_plan(plan([control(missing=280)]), workers=workers)
            self.assertIsNone(found["workers"])
            self.assertEqual(found["assumed_workers"], 16)
            self.assertEqual(found["minutes"], [1.0, 1.2])

    def test_remaining_counts_include_seed_control_gaps_and_ignore_target_minus_have(self):
        base = control(missing=0, have=50, source="control_dir")
        extra_seed = control("seed", 7, pair=["casual/a", "casual/c"], card_shas=["a", "c"], have=43)
        changed = arm(missing=17, have=49)  # ten selected-number gaps plus seven unplayed seed-control games
        skipped = arm("skip", 9000, skipped="changes nothing")
        found = timing.estimate_plan(plan([base, extra_seed], [changed, skipped]), workers=16)
        self.assertEqual(found["remaining_games"], 24)
        self.assertEqual([row["remaining_games"] for row in found["controls"]], [0, 7])
        self.assertEqual([row["remaining_games"] for row in found["arms"]], [17, 0])
        self.assertAlmostEqual(found["minutes"][0], 24 / 280)
        self.assertAlmostEqual(found["minutes"][1], 24 / 280 * 1.2)

    def test_cached_control_measurements_can_proxy_only_the_matching_arm_pair(self):
        base, seed = control(missing=0), control("seed", 0, pair=["casual/a", "casual/c"], card_shas=["a", "c"])
        first, second = arm(), arm("second", 280, pair=["casual/b", "casual/c"], card_shas=["b", "c"])
        found = timing.estimate_plan(plan([base, seed], [first, second]),
                                     samples={base["key"]: v2(base), seed["key"]: v2(seed)}, workers=16)
        self.assertEqual(found["arms"][0]["basis"], "control_proxy")
        self.assertEqual(found["arms"][0]["sample_key"], "base")
        self.assertIn(timing.CONTROL_PROXY, found["assumptions"])
        self.assertEqual(found["arms"][1]["basis"], "fallback")
        self.assertEqual(found["minutes"], [2.0, 2.4])

    def test_same_arm_key_is_only_a_proxy_and_does_not_prove_changed_recipe(self):
        first, second = arm(), arm("second", 280)
        found = timing.estimate_plan(plan([], [first, second]), samples={first["key"]: v2(first)}, workers=16)
        self.assertEqual(found["arms"][0]["basis"], "arm_proxy")
        self.assertEqual(found["arms"][1]["basis"], "fallback")
        self.assertIn(timing.ARM_PROXY, found["assumptions"])
        self.assertEqual(found["basis"], "mixed")
        self.assertEqual(found["minutes"], [2.0, 2.4])

    def test_only_selected_plan_rows_are_counted_or_sampled(self):
        kept = arm("kept", 280)
        samples = {"not-selected": v2(control("not-selected"))}
        found = timing.estimate_plan(plan([], [kept]), samples=samples, workers=16)
        self.assertEqual(found["remaining_games"], 280)
        self.assertEqual(len(found["arms"]), 1)
        self.assertEqual(found["minutes"], [1.0, 1.2])

    def test_config_arm_is_unsupported_and_partial_rows_never_become_a_total(self):
        base = control(missing=280)
        for config in ({"forge_workers": 8}, {"forge_performance_mode": False}, {"unknown": float("nan")}):
            changed = arm("config", 100, config=config, changes=["config"])
            found = timing.estimate_plan(plan([base], [changed]),
                                         samples={changed["key"]: v2(changed)}, workers=16)
            self.assertEqual(found["remaining_games"], 380)
            self.assertFalse(found["complete"])
            self.assertIsNone(found["minutes"])
            self.assertEqual(found["controls"][0]["minutes"], [1.0, 1.2])
            self.assertEqual(found["arms"][0]["basis"], "unsupported_config")
            self.assertIsNone(found["arms"][0]["minutes"])
            self.assertIn(timing.CONFIG_UNKNOWN, found["assumptions"])
            json.dumps(found, allow_nan=False)

    def test_zero_work_never_inspects_timing_or_rates_even_for_config_or_skipped_arms(self):
        class Unreadable(dict):
            def get(self, *_args):
                raise AssertionError("Timing inputs must not be read for zero work")
        found = timing.estimate_plan(plan([control(missing=0)], [arm(missing=0, config={"arbitrary": True}),
            arm("skip", 9999, skipped="no change")]), samples=Unreadable(), rates=Unreadable())
        self.assertEqual(found["minutes"], [0, 0])
        self.assertEqual(found["remaining_games"], 0)
        self.assertTrue(found["complete"])
        self.assertEqual(found["basis"], "none")
        self.assertIsNone(found["assumed_workers"])

    def test_empty_plan_is_zero_without_assuming_requested_games_are_work(self):
        found = timing.estimate_plan(plan())
        self.assertEqual(found["minutes"], [0, 0])
        self.assertEqual(found["remaining_games"], 0)

    def test_totals_sum_unrounded_times_and_range_is_explicitly_heuristic(self):
        rows = [control(str(i), 1, pair=["casual/" + str(i), "casual/other"], card_shas=[str(i), "other"])
                for i in range(3)]
        found = timing.estimate_plan(plan(rows), samples={row["key"]: v2(row, [(3, 60, 16)]) for row in rows},
                                     workers=16)
        self.assertEqual(found["minutes"], [1.0, 1.2])
        self.assertEqual([row["minutes"][0] for row in found["controls"]], [1 / 3, 1 / 3, 1 / 3])
        self.assertIn("not a confidence interval", found["assumptions"][0])
        self.assertIn("queue wait", found["assumptions"][1])
        self.assertIn("run readiness", found["assumptions"][2])

    def test_positive_fast_or_tiny_machine_spans_survive_json_without_becoming_zero(self):
        row = control(missing=1)
        found = timing.estimate_plan(plan([row]), samples={row["key"]: v2(row, [(900, 60, 16)])}, workers=16)
        self.assertEqual(found["minutes"], [1 / 900, 1 / 900 * 1.2])
        self.assertEqual(found["controls"][0]["minutes"], found["minutes"])
        for rate in (1e200, 1e308):
            found = timing.estimate_plan(plan([row]), rates={"board": rate}, workers=16)
            decoded = json.loads(json.dumps(found, allow_nan=False))
            self.assertTrue(decoded["complete"])
            self.assertGreater(decoded["minutes"][0], 0)
            self.assertGreater(decoded["minutes"][1], 0)
            self.assertGreater(decoded["controls"][0]["minutes"][0], 0)
            self.assertEqual(decoded["minutes"][0], 1 / rate)

    def test_positive_underflow_is_unavailable_instead_of_zero(self):
        self.assertIsNone(timing._span(1e-308, 1e308))

    def test_unknown_format_invalid_counts_or_overflow_do_not_publish_partial_total(self):
        for row in (control(kind="unknown"), control(missing=True), control(missing=-1),
                    control(missing=10 ** 400)):
            found = timing.estimate_plan(plan([row]), workers=16)
            self.assertFalse(found["complete"])
            self.assertIsNone(found["minutes"])
        found = timing.estimate_plan(plan([control()]), rates={"board": 1e-320}, workers=16)
        self.assertIsNone(found["minutes"])

    def test_helper_is_pure_and_preserves_all_input_snapshots(self):
        row = control()
        given, samples, rates = plan([row], [arm()]), {row["key"]: v2(row)}, {"board": 300}
        before = copy.deepcopy((given, samples, rates))
        with mock.patch.object(common, "_settings", side_effect=AssertionError("settings read")), \
                mock.patch.object(common, "_write_atomic", side_effect=AssertionError("write")), \
                mock.patch.object(saved, "_stored", side_effect=AssertionError("results read")), \
                mock.patch.object(estimate, "rates", side_effect=AssertionError("rates read")), \
                mock.patch.object(estimate, "_workers", side_effect=AssertionError("workers read")), \
                mock.patch("pathlib.Path.open", side_effect=AssertionError("filesystem access")):
            found = timing.estimate_plan(given, samples=samples, rates=rates, workers=16)
        self.assertEqual((given, samples, rates), before)
        self.assertTrue(found["complete"])
        json.dumps(found, allow_nan=False)

    def test_aggregate_overflow_keeps_finite_row_details_but_no_whole_estimate(self):
        found = timing.estimate_plan(plan([control("one", 10 ** 308), control("two", 10 ** 308)]),
                                     rates={"board": 1}, workers=16)
        self.assertFalse(found["complete"])
        self.assertIsNone(found["minutes"])
        self.assertTrue(all(row["minutes"] is not None for row in found["controls"]))
        self.assertIn(timing.UNAVAILABLE, found["assumptions"])
        json.dumps(found, allow_nan=False)
