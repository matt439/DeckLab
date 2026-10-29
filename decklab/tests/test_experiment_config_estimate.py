"""Pure explicit-local worker-arm estimates, using supplied fixtures only.

Run: python scripts/test_fixtures.py decklab.tests.test_experiment_config_estimate
"""
import copy
import json
import unittest
from unittest import mock

from decklab.lib.forge import experiment_estimate as timing
from decklab.tests import test_forge_experiment_estimate as fixtures


def worker_arm(name="workers", count=8, missing=140, **extra):
    return fixtures.arm(name, missing, config={"forge_workers": count}, changes=["config"], **extra)


class LocalWorkerEstimateTests(unittest.TestCase):
    def test_explicit_local_worker_only_arm_uses_requested_format_fallback(self):
        row = worker_arm()
        found = timing.estimate_plan(fixtures.plan([], [row]), workers=16, local=True)
        self.assertTrue(found["complete"])
        self.assertEqual(found["basis"], "config_fallback")
        self.assertEqual(found["minutes"], [1.0, 1.2])
        self.assertEqual(found["workers"], 16)
        detail, = found["arms"]
        self.assertEqual(detail["requested_workers"], 8)
        self.assertEqual(detail["placement"], "local_assumed")
        self.assertEqual(detail["games_per_min"], 140)
        self.assertIn(timing.CONFIG_LOCAL, found["assumptions"])
        self.assertIn(timing.FORMAT_FALLBACK, found["assumptions"])
        self.assertIn("worker caps", timing.CONFIG_LOCAL)
        self.assertIn("chunk limits", timing.CONFIG_LOCAL)
        self.assertIn("contention", timing.CONFIG_LOCAL)
        self.assertIn("shared PC load", timing.CONFIG_LOCAL)
        self.assertIsNone(found["assumed_workers"])

    def test_commander_uses_its_own_format_reference_at_requested_workers(self):
        row = worker_arm(count=4, missing=50, kind="commander")
        found = timing.estimate_plan(fixtures.plan([], [row]),
                                     rates={"board": 280, "commander": 200}, workers=16, local=True)
        self.assertEqual(found["minutes"], [1.0, 1.2])
        self.assertEqual(found["arms"][0]["games_per_min"], 50)

    def test_local_intent_must_be_explicit_boolean_true(self):
        for local in (False, None, 0, 1, "local", "true", [], {}):
            with self.subTest(local=local):
                found = timing.estimate_plan(fixtures.plan([], [worker_arm()]), local=local)
                self.assertFalse(found["complete"])
                self.assertIsNone(found["minutes"])
                self.assertEqual(found["arms"][0]["basis"], "unsupported_config")
                self.assertIn(timing.CONFIG_UNKNOWN, found["assumptions"])
                self.assertNotIn("requested_workers", found["arms"][0])
        self.assertFalse(timing.estimate_plan(fixtures.plan([], [worker_arm()]))["complete"])

    def test_worker_count_requires_a_finite_positive_exact_integer(self):
        for count in (None, True, False, 0, -1, "8", 8.0, float("nan"), float("inf"), 10 ** 400):
            with self.subTest(count=repr(count)[:50]):
                found = timing.estimate_plan(fixtures.plan([], [worker_arm(count=count)]), local=True)
                self.assertFalse(found["complete"])
                self.assertIsNone(found["minutes"])
                self.assertEqual(found["arms"][0]["basis"], "unsupported_config")
                json.dumps(found, allow_nan=False)

    def test_additional_keys_and_other_configuration_remain_unknown(self):
        configs = [{"forge_workers": 8, "forge_performance_mode": False},
                   {"forge_workers": 8, "other": None}, {"forge_performance_mode": True},
                   {"unknown": 8}, {}, False, "forge_workers", [8]]
        for config in configs:
            with self.subTest(config=config):
                row = fixtures.arm(config=config, changes=["config"])
                with mock.patch.object(timing, "_sample", side_effect=AssertionError("Config sampled")):
                    found = timing.estimate_plan(fixtures.plan([], [row]), local=True)
                self.assertFalse(found["complete"])
                self.assertIsNone(found["minutes"])
                self.assertEqual(found["arms"][0]["basis"], "unsupported_config")

    def test_actual_changes_must_be_exactly_one_config_change(self):
        for changes in ([], None, "config", ("config",), ["pilot"], ["config", "pilot"],
                        ["config", "seeds"], ["config", "config"]):
            with self.subTest(changes=changes):
                row = worker_arm()
                row["changes"] = changes
                with mock.patch.object(timing, "_sample", side_effect=AssertionError("Config sampled")):
                    found = timing.estimate_plan(fixtures.plan([], [row]), local=True)
                self.assertFalse(found["complete"])
                self.assertEqual(found["arms"][0]["basis"], "unsupported_config")

    def test_explicit_config_marker_without_a_config_map_is_unknown(self):
        for changes in (["config"], "config", ["config", "pilot"]):
            with self.subTest(changes=changes):
                row = fixtures.arm(config=None, changes=changes)
                found = timing.estimate_plan(fixtures.plan([], [row]), local=True)
                self.assertFalse(found["complete"])
                self.assertIsNone(found["minutes"])

    def test_empty_no_config_placeholder_preserves_ordinary_arm_timing(self):
        base, ordinary = fixtures.control(missing=0), fixtures.arm(config={})
        baseline = dict(ordinary, config=None)
        for samples, basis in (({ordinary["key"]: fixtures.v2(ordinary)}, "arm_proxy"),
                               ({base["key"]: fixtures.v2(base)}, "control_proxy"), ({}, "fallback")):
            for local in (False, True):
                with self.subTest(basis=basis, local=local):
                    expected = timing.estimate_plan(fixtures.plan([base], [baseline]),
                                                     samples=samples, workers=16, local=local)
                    found = timing.estimate_plan(fixtures.plan([base], [ordinary]),
                                                  samples=samples, workers=16, local=local)
                    self.assertEqual(found, expected)
                    self.assertEqual(found["arms"][0]["basis"], basis)

    def test_matching_historical_arm_and_control_pool_throughput_are_never_consulted(self):
        base, changed = fixtures.control(missing=0), worker_arm()
        samples = {base["key"]: fixtures.v2(base, [(1_000_000, 1, 8)]),
                   changed["key"]: fixtures.v2(changed, [(1_000_000, 1, 8)])}
        with mock.patch.object(timing, "_sample", side_effect=AssertionError("Config sampled")):
            found = timing.estimate_plan(fixtures.plan([base], [changed]), samples=samples, local=True)
        detail, = found["arms"]
        self.assertEqual(found["minutes"], [1.0, 1.2])
        self.assertIsNone(detail["timing"])
        self.assertIsNone(detail["sample_key"])
        self.assertIsNone(detail["sample_workers"])
        self.assertIsNone(detail["worker_context"])
        self.assertIsNone(detail["rejected_sample"])
        self.assertNotIn(timing.ARM_PROXY, found["assumptions"])
        self.assertNotIn(timing.CONTROL_PROXY, found["assumptions"])
        self.assertNotIn(timing.POOL_AGGREGATE, found["assumptions"])

    def test_requested_worker_changes_do_not_rescale_saved_v2_measurements(self):
        for requested, minutes in ((4, 2.0), (8, 1.0), (16, 0.5)):
            with self.subTest(requested=requested):
                row = worker_arm(count=requested)
                found = timing.estimate_plan(fixtures.plan([], [row]),
                    samples={row["key"]: fixtures.v2(row, [(10_000_000, 1, requested)])}, local=True)
                self.assertEqual(found["minutes"], [minutes, minutes * 1.2])
                self.assertEqual(found["arms"][0]["basis"], "config_fallback")

    def test_two_worker_arms_keep_the_baseline_control_context_and_independent_counts(self):
        base = fixtures.control(missing=900)
        first, second = worker_arm("four", 4), worker_arm("eight", 8)
        samples = {base["key"]: fixtures.v2(base)}
        before = timing.estimate_plan(fixtures.plan([base]), samples=samples, workers=16)
        found = timing.estimate_plan(fixtures.plan([base], [first, second]),
                                     samples=samples, workers=16, local=True)
        self.assertEqual(found["controls"], before["controls"])
        self.assertEqual(found["workers"], 16)
        self.assertEqual([row["requested_workers"] for row in found["arms"]], [4, 8])
        self.assertEqual([row["minutes"][0] for row in found["arms"]], [2.0, 1.0])
        self.assertEqual(found["minutes"], [4.0, 4.8])
        self.assertEqual(found["basis"], "mixed")
        self.assertEqual(found["remaining_games"], 1180)
        self.assertIn(timing.BASE_ASSUMPTIONS[3], found["assumptions"])

    def test_arm_worker_assumption_does_not_assign_unknown_baseline_context(self):
        found = timing.estimate_plan(fixtures.plan([], [worker_arm(count=4)]), local=True)
        self.assertIsNone(found["workers"])
        self.assertIsNone(found["assumed_workers"])
        self.assertEqual(found["arms"][0]["requested_workers"], 4)
        self.assertNotIn(timing.UNKNOWN_WORKERS, found["assumptions"])

    def test_one_unsupported_row_still_prevents_a_whole_experiment_total(self):
        valid = worker_arm()
        invalid = fixtures.arm("other", 100, config={"unsupported": True}, changes=["config"])
        found = timing.estimate_plan(fixtures.plan([], [valid, invalid]), local=True)
        self.assertFalse(found["complete"])
        self.assertIsNone(found["minutes"])
        self.assertEqual(found["arms"][0]["minutes"], [1.0, 1.2])
        self.assertIsNone(found["arms"][1]["minutes"])
        self.assertEqual(found["remaining_games"], 240)

    def test_unknown_format_and_numeric_overflow_do_not_become_partial_success(self):
        for row, rates in ((worker_arm(kind="unknown"), None),
                           (worker_arm(count=10 ** 308), None),
                           (worker_arm(), {"board": 1e-320})):
            with self.subTest(kind=row["kind"], rates=rates):
                found = timing.estimate_plan(fixtures.plan([], [row]), rates=rates, local=True)
                self.assertFalse(found["complete"])
                self.assertIsNone(found["minutes"])
                self.assertEqual(found["arms"][0]["basis"], "unavailable")
                json.dumps(found, allow_nan=False)

    def test_positive_subminute_machine_spans_remain_exact_and_json_finite(self):
        row = worker_arm(count=8, missing=1)
        for rate in (280, 1e200, 1e308):
            with self.subTest(rate=rate):
                found = timing.estimate_plan(fixtures.plan([], [row]), rates={"board": rate}, local=True)
                decoded = json.loads(json.dumps(found, allow_nan=False))
                self.assertTrue(decoded["complete"])
                self.assertEqual(decoded["minutes"][0], 1 / (rate / 2))
                self.assertGreater(decoded["minutes"][0], 0)
                self.assertGreater(decoded["minutes"][1], 0)

    def test_zero_and_skipped_work_do_not_read_config_samples_or_rates(self):
        class Unreadable(dict):
            def get(self, *_args):
                raise AssertionError("Zero-work metadata was read")
            def __bool__(self):
                raise AssertionError("Zero-work metadata was inspected")
        completed = fixtures.arm(missing=0, config=Unreadable(), changes=["config"])
        skipped = fixtures.arm("skip", 9999, config=Unreadable(), changes=["config"], skipped="unchanged")
        found = timing.estimate_plan(fixtures.plan([fixtures.control(missing=0)], [completed, skipped]),
                                     samples=Unreadable(), rates=Unreadable(), local=True)
        self.assertEqual(found["minutes"], [0.0, 0.0])
        self.assertTrue(found["complete"])
        self.assertEqual(found["remaining_games"], 0)
        self.assertTrue(all(row["basis"] == "none" for row in found["arms"]))
        self.assertTrue(all("requested_workers" not in row for row in found["arms"]))

    def test_completed_unsupported_row_is_still_zero_beside_remaining_work(self):
        class Unreadable(dict):
            def get(self, *_args):
                raise AssertionError("Completed config was read")
        completed = fixtures.arm("complete", 0, config=Unreadable(), changes=["config"])
        found = timing.estimate_plan(fixtures.plan([], [completed, worker_arm()]), local=True)
        self.assertTrue(found["complete"])
        self.assertEqual(found["minutes"], [1.0, 1.2])
        self.assertEqual(found["arms"][0]["minutes"], [0.0, 0.0])

    def test_config_arm_calculation_is_pure_and_preserves_every_input(self):
        row = worker_arm()
        given = fixtures.plan([fixtures.control(missing=0)], [row])
        samples = {row["key"]: fixtures.v2(row)}
        rates = {"board": 280}
        before = copy.deepcopy((given, samples, rates))
        with mock.patch.object(timing, "_sample", side_effect=AssertionError("Sampling")), \
                mock.patch("pathlib.Path.open", side_effect=AssertionError("Filesystem access")):
            found = timing.estimate_plan(given, samples=samples, rates=rates, workers=16, local=True)
        self.assertTrue(found["complete"])
        self.assertEqual((given, samples, rates), before)
        self.assertEqual([row["changes"] for row in given["arms"]], [["config"]])
