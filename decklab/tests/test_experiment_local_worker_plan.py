"""Explicit local worker assumptions through read-only experiment adapters and CLI.

Run with python scripts/test_fixtures.py decklab.tests.test_experiment_local_worker_plan.
Readers, settings, result receipts and engine identity are disposable stand-ins;
no server, actual configuration, process, deployment or simulation is accessed.
"""
import copy
import json
import unittest
from unittest import mock

from decklab.lib.forge import estimate, experiment, experiment_estimate as timing
from decklab.tests import test_experiment_plan_readonly as readonly
from decklab.tests import test_forge_experiment_estimate_cli as cli_fixtures
from decklab.tests.test_forge_experiment_estimate import arm, control


def config_arm(name, workers, missing=280, **extra):
    return arm(name, missing, config={"forge_workers": workers}, changes=["config"], **extra)


def timed_plan(controls=(), arms=(), *, local=True, workers=16, samples=None):
    found = cli_fixtures.found_plan(controls, arms, workers=workers, samples=samples)
    found["estimate"] = timing.estimate_plan(found, local=local, workers=workers, samples=samples)
    return found


class LocalWorkerPlanAdapterTests(unittest.TestCase):
    patch = readonly.ReadOnlyExperimentPlanTests.patch
    key = readonly.ReadOnlyExperimentPlanTests.key
    control_key = readonly.ReadOnlyExperimentPlanTests.control_key
    plan = readonly.ReadOnlyExperimentPlanTests.plan
    saved = readonly.ReadOnlyExperimentPlanTests.saved
    cache = readonly.ReadOnlyExperimentPlanTests.cache
    assert_no_effects = readonly.ReadOnlyExperimentPlanTests.assert_no_effects

    def setUp(self):
        readonly.ReadOnlyExperimentPlanTests.setUp(self)
        self.spec["pairs"] = [self.spec["pairs"][0]]
        self.spec["arms"] = {"small": {"config": {"forge_workers": 2}},
                             "large": {"config": {"forge_workers": 8}}}
        experiment._plan_timing_metadata.return_value = (dict(estimate.DEFAULT_RATES), 16)
        self.calculate = mock.Mock(wraps=timing.estimate_plan)
        self.patch(timing, "estimate_plan", self.calculate)

    def test_real_plan_keeps_two_arm_requests_distinct_from_baseline_workers_without_side_effects(self):
        before = copy.deepcopy(self.spec)
        found = self.plan(local=True)
        self.assertEqual(self.spec, before)
        self.assertEqual(found["totals"], {"control_games": 10, "arm_games": 20, "games": 30})
        self.assertEqual(self.calculate.call_args.kwargs["local"], True)
        self.assertEqual(found["estimate"]["workers"], 16)
        self.assertEqual(found["estimate"]["controls"][0]["basis"], "fallback")
        first, second = found["estimate"]["arms"]
        self.assertEqual([(row["basis"], row["requested_workers"], row["placement"]) for row in (first, second)],
                         [("config_fallback", 2, "local_assumed"), ("config_fallback", 8, "local_assumed")])
        self.assertAlmostEqual(first["minutes"][0], second["minutes"][0] * 4)
        self.assertEqual(experiment.saved.load.call_count, 3)
        experiment._plan_timing_metadata.assert_called_once_with()
        json.dumps(found, allow_nan=False)
        self.assert_no_effects()

    def test_default_and_non_boolean_local_intent_leave_the_complete_time_unknown(self):
        for local in (False, None, 1, "true"):
            with self.subTest(local=local):
                found = self.plan(local=local)
                self.assertIsNone(found["estimate"]["minutes"])
                self.assertFalse(found["estimate"]["complete"])
                self.assertEqual(self.calculate.call_args.kwargs["local"], local)
                self.assertEqual({row["basis"] for row in found["estimate"]["arms"]}, {"unsupported_config"})
                self.assertTrue(all("requested_workers" not in row for row in found["estimate"]["arms"]))
        self.assert_no_effects()

    def test_requested_arm_rates_stay_fixed_when_only_baseline_planning_workers_change(self):
        first = self.plan(local=True)
        experiment._plan_timing_metadata.return_value = (dict(estimate.DEFAULT_RATES), 4)
        second = self.plan(local=True)
        self.assertEqual(first["estimate"]["arms"], second["estimate"]["arms"])
        self.assertNotEqual(first["estimate"]["controls"][0]["minutes"],
                            second["estimate"]["controls"][0]["minutes"])
        self.assertEqual(second["estimate"]["workers"], 4)
        self.assert_no_effects()

    def test_local_intent_does_not_make_unsupported_or_mixed_config_recipes_predictable(self):
        cases = ({"forge_workers": True}, {"forge_workers": "8"}, {"forge_workers": 0},
                 {"forge_workers": 8, "other": 1}, {"unknown": 8})
        for config in cases:
            with self.subTest(config=config):
                spec = copy.deepcopy(self.spec)
                spec["arms"] = {"unknown": {"config": config}}
                found = self.plan(spec, local=True)
                self.assertIsNone(found["estimate"]["minutes"])
                self.assertFalse(found["estimate"]["complete"])
                self.assertEqual(found["estimate"]["arms"][0]["basis"], "unsupported_config")
        spec = copy.deepcopy(self.spec)
        spec["arms"] = {"mixed": {"config": {"forge_workers": 8},
                                  "pilots": {"casual/green": {"profile": "Reckless"}}}}
        found = self.plan(spec, local=True)
        self.assertEqual(found["arms"][0]["changes"], ["config", "pilot"])
        self.assertIsNone(found["estimate"]["minutes"])
        self.assertEqual(found["estimate"]["arms"][0]["basis"], "unsupported_config")
        self.assert_no_effects()

    def test_unknown_format_stays_unknown_in_a_read_only_local_plan(self):
        for entry in self.entries.values():
            entry["kind"] = "unknown"
        found = self.plan(local=True)
        self.assertIsNone(found["estimate"]["minutes"])
        self.assertFalse(found["estimate"]["complete"])
        self.assertTrue(all("requested_workers" not in row for row in found["estimate"]["arms"]))
        self.assert_no_effects()

    def test_cached_local_config_plan_bypasses_all_optional_timing_metadata(self):
        initial = self.plan(local=True)
        for row in initial["controls"]:
            self.cache(self.results / "control", row["key"], range(10))
        for row in initial["arms"]:
            self.cache(self.results / row["arm"], row["key"], range(10))
        experiment._plan_timing_metadata.reset_mock()
        experiment._plan_timing_metadata.side_effect = AssertionError("Cached work must not read rates/settings")
        self.calculate.reset_mock()
        found = self.plan(local=True)
        self.assertEqual(found["totals"]["games"], 0)
        self.assertEqual(found["estimate"]["minutes"], [0.0, 0.0])
        self.calculate.assert_called_once_with(found, local=True)
        experiment._plan_timing_metadata.assert_not_called()
        self.assertTrue(all("requested_workers" not in row for row in found["estimate"]["arms"]))
        self.assert_no_effects()

    def test_cached_control_with_only_skipped_arms_reads_no_timing_metadata(self):
        spec = copy.deepcopy(self.spec)
        spec["pairs"] = [["casual/red", "casual/blue"]]
        spec["arms"] = {"pilot": {"pilots": {"casual/green": {"profile": "Reckless"}}}}
        self.cache(self.results / "control", self.control_key(*spec["pairs"][0]), range(10))
        experiment._plan_timing_metadata.side_effect = AssertionError("Skipped work must not read metadata")
        found = self.plan(spec, local=True)
        self.assertEqual(found["totals"]["games"], 0)
        self.assertTrue(found["arms"][0]["skipped"])
        self.assertEqual(found["estimate"]["minutes"], [0.0, 0.0])
        experiment._plan_timing_metadata.assert_not_called()
        self.assert_no_effects()


class LocalWorkerPlanCliTests(unittest.TestCase):
    run_cli = cli_fixtures.ExperimentEstimateCliTests.run_cli

    def test_real_estimator_text_distinguishes_baseline_and_each_requested_local_worker_count(self):
        found = timed_plan([control(missing=280)], [config_arm("small", 2), config_arm("large", 8)])
        code, text, errors, _, planned, ran = self.run_cli(found, "--local")
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("Baseline planning workers: 16.", text)
        self.assertNotIn("  Planning workers: 16.", text)
        self.assertIn("Arm small, casual/a v casual/b: requests 2 local workers for timing only.", text)
        self.assertIn("Arm large, casual/a v casual/b: requests 8 local workers for timing only.", text)
        self.assertIn("format fallback rates at requested local workers", text)
        self.assertIn(timing.CONFIG_LOCAL, text)
        self.assertIn(timing.FORMAT_FALLBACK, text)
        self.assertEqual(planned.call_args.kwargs["local"], True)
        ran.assert_not_called()

    def test_requested_one_worker_and_unknown_baseline_remain_distinct(self):
        found = timed_plan([], [config_arm("single", 1)], workers=None)
        code, text, errors, _, _, _ = self.run_cli(found, "--local")
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("Baseline planning workers: unknown.", text)
        self.assertIn("requests 1 local worker for timing only.", text)
        self.assertNotIn("requests 1 local workers", text)
        self.assertNotIn("assume 16 workers", text)

    def test_without_local_the_plan_stays_unknown_and_cli_forwards_false(self):
        found = timed_plan([control(missing=280)], [config_arm("small", 2)], local=False)
        code, text, errors, _, planned, ran = self.run_cli(found)
        self.assertEqual((code, errors), (0, ""))
        self.assertIs(planned.call_args.kwargs["local"], False)
        self.assertIn("estimate unavailable for the complete remaining work", text)
        self.assertNotIn("requests 2 local workers", text)
        self.assertIn(timing.CONFIG_UNKNOWN, text)
        self.assertNotIn(timing.CONFIG_LOCAL, text)
        ran.assert_not_called()

    def test_machine_output_retains_finite_positive_subminute_spans_and_per_arm_placement(self):
        found = timed_plan([], [config_arm("small", 2, missing=1), config_arm("large", 8, missing=1)])
        before = copy.deepcopy(found)
        code, text, errors, _, _, ran = self.run_cli(found, "--local", "--json")
        self.assertEqual((code, errors), (0, ""))
        decoded = json.loads(text)
        self.assertEqual(decoded, before)
        self.assertEqual(found, before)
        json.dumps(decoded, allow_nan=False)
        self.assertGreater(decoded["estimate"]["minutes"][0], 0)
        self.assertLess(decoded["estimate"]["minutes"][1], 1)
        self.assertEqual([row["requested_workers"] for row in decoded["estimate"]["arms"]], [2, 8])
        self.assertEqual({row["placement"] for row in decoded["estimate"]["arms"]}, {"local_assumed"})
        _, text, _, _, _, _ = self.run_cli(found, "--local")
        self.assertIn("Remaining game time: under 1 minute.", text)
        ran.assert_not_called()

    def test_invalid_or_mismatched_optional_worker_context_cannot_publish_a_request(self):
        for change in ({"requested_workers": True}, {"requested_workers": "2"}, {"requested_workers": 10 ** 400},
                       {"requested_workers": 3}, {"placement": "SECRET remote path"}, {"key": "SECRET wrong key"},
                       {"arm": "SECRET wrong arm"}, {"remaining_games": True}, {"remaining_games": 1},
                       {"basis": "SECRET provenance"}):
            with self.subTest(change=change):
                found = timed_plan([], [config_arm("small", 2)])
                found["estimate"]["arms"][0].update(change)
                code, text, errors, _, _, _ = self.run_cli(found, "--local")
                self.assertEqual((code, errors), (0, ""))
                self.assertNotIn("requests ", text)
                self.assertNotIn("SECRET", text)

    def test_optional_context_never_adds_a_request_from_a_different_row_or_partial_shape(self):
        for details in (None, 5, [], [None], [{"basis": "config_fallback", "requested_workers": 8,
            "placement": "local_assumed", "arm": "SECRET", "key": "SECRET"}]):
            with self.subTest(details=details):
                found = timed_plan([], [config_arm("small", 2)])
                found["estimate"]["arms"] = details
                code, text, errors, _, _, _ = self.run_cli(found, "--local")
                self.assertEqual((code, errors), (0, ""))
                self.assertNotIn("requests ", text)
                self.assertNotIn("SECRET", text)

    def test_config_assumptions_are_allowlisted_and_arbitrary_messages_stay_hidden(self):
        found = timed_plan([], [config_arm("small", 2)])
        found["estimate"]["assumptions"].extend(["SECRET settings", "SECRET worker inventory"])
        found["estimate"]["arms"][0]["assumptions"].append("SECRET sample path")
        code, text, errors, _, _, _ = self.run_cli(found, "--local")
        self.assertEqual((code, errors), (0, ""))
        self.assertIn(timing.CONFIG_LOCAL, text)
        self.assertNotIn("SECRET", text)

    def test_non_dry_run_keeps_its_existing_local_run_argument_and_no_estimate(self):
        code, text, errors, _, planned, ran = self.run_cli(timed_plan(), "--local", dry=False,
                                                        run_result={"failed": []})
        self.assertEqual((code, errors), (0, ""))
        self.assertEqual(text, "Fixture report\n")
        self.assertIs(ran.call_args.kwargs["local"], True)
        planned.assert_not_called()
