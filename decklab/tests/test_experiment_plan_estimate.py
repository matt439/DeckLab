"""Timing adapter receipts and quiet optional metadata; all data and readers are fixtures."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib.forge import estimate, experiment
from decklab.tests import test_experiment_plan_readonly as readonly

_metadata_reader = experiment._plan_timing_metadata


class ExperimentPlanEstimateTests(unittest.TestCase):
    # Compose the pure fixture setup without inheriting/discovering its prerequisite tests.
    patch = readonly.ReadOnlyExperimentPlanTests.patch
    key = readonly.ReadOnlyExperimentPlanTests.key
    control_key = readonly.ReadOnlyExperimentPlanTests.control_key
    plan = readonly.ReadOnlyExperimentPlanTests.plan
    assert_no_effects = readonly.ReadOnlyExperimentPlanTests.assert_no_effects

    def setUp(self):
        self.loaded = []
        readonly.ReadOnlyExperimentPlanTests.setUp(self)
        experiment._plan_timing_metadata.return_value = (dict(estimate.DEFAULT_RATES), 8)
        self.calculate = mock.Mock(wraps=experiment.experiment_estimate.estimate_plan)
        self.patch(experiment.experiment_estimate, "estimate_plan", self.calculate)
        for target, name in ((experiment.saved, "_stored"), (estimate, "_saved_rates"),
                             (Path, "glob"), (Path, "rglob"), (Path, "read_text"),
                             (experiment.common, "_log")):
            blocked = mock.Mock(side_effect=AssertionError("Unexpected timing reread or logging: " + name))
            self.patch(target, name, blocked)
            self.blocked[name] = blocked

    def saved(self, key, folder):
        receipt = copy.deepcopy(self.stored.get((Path(folder), key)))
        self.loaded.append((key, Path(folder), receipt))
        return receipt

    def cache(self, folder, key, numbers, pair, rate=100):
        numbers = list(numbers)
        self.stored[(Path(folder), key)] = {
            "key": key, "run_version": 2,
            "sides": [{"card_sha": self.entries[ref]["card_sha"]} for ref in pair],
            "runs": [{"pool": "local", "played": len(numbers), "wall_s": len(numbers) * 60 / rate, "workers": 8}],
            "batches": [{"games": [{"g": number} for number in numbers]}],
        }

    def reset_reads(self):
        self.loaded.clear()
        experiment.saved.load.reset_mock()
        experiment._plan_timing_metadata.reset_mock()
        self.calculate.reset_mock()

    def partial_arm(self):
        pair = self.spec["pairs"][0]
        spec = {**self.spec, "pairs": [pair]}
        control_key = self.control_key(*pair)
        self.cache(self.controls, control_key, range(10), pair)
        initial = self.plan(spec, control_dir=self.controls)
        arm_key = initial["arms"][0]["key"]
        self.cache(self.results / "pilot", arm_key, [0, 3], pair, rate=200)
        self.reset_reads()
        return spec, control_key, arm_key

    def test_exact_control_and_arm_receipts_reach_estimator_without_rereads_or_scans(self):
        spec, control_key, arm_key = self.partial_arm()
        before = copy.deepcopy(self.stored)
        found = self.plan(spec, control_dir=self.controls)
        self.assertEqual(found["totals"], {"control_games": 0, "arm_games": 8, "games": 8})
        self.assertEqual([(key, folder) for key, folder, _ in self.loaded],
                         [(control_key, self.controls), (arm_key, self.results / "pilot")])
        self.assertEqual(experiment.saved.load.call_count, 2)
        self.calculate.assert_called_once()
        self.assertIs(self.calculate.call_args.args[0], found)
        samples = self.calculate.call_args.kwargs["samples"]
        self.assertIs(samples[control_key], self.loaded[0][2])
        self.assertIs(samples[arm_key], self.loaded[1][2])
        self.assertEqual(found["estimate"]["remaining_games"], 8)
        self.assertEqual(found["estimate"]["arms"][0]["basis"], "arm_proxy")
        self.assertEqual(found["estimate"]["arms"][0]["sample_key"], arm_key)
        self.assertAlmostEqual(found["estimate"]["minutes"][0], 0.04)
        self.assertAlmostEqual(found["estimate"]["minutes"][1], 0.048)
        self.assertEqual(self.stored, before)
        self.assert_no_effects()

    def test_discarded_partial_external_control_cannot_supply_the_local_controls_rate(self):
        pair = self.spec["pairs"][0]
        spec = {**self.spec, "pairs": [pair]}
        key = self.control_key(*pair)
        self.cache(self.controls, key, range(6), pair, rate=600)
        self.cache(self.results / "control", key, range(2), pair, rate=100)
        found = self.plan(spec, control_dir=self.controls)
        self.assertEqual(found["totals"], {"control_games": 8, "arm_games": 10, "games": 18})
        self.assertEqual([folder for _, folder, _ in self.loaded],
                         [self.controls, self.results / "control", self.results / "pilot"])
        selected = self.calculate.call_args.kwargs["samples"][key]
        self.assertIs(selected, self.loaded[1][2])
        self.assertIsNot(selected, self.loaded[0][2])
        self.assertEqual(found["estimate"]["controls"][0]["games_per_min"], 100)
        self.assertEqual(found["estimate"]["arms"][0]["basis"], "control_proxy")
        self.assertAlmostEqual(found["estimate"]["minutes"][0], 0.18)
        self.assertAlmostEqual(found["estimate"]["minutes"][1], 0.216)
        self.assert_no_effects()

    def test_returned_arm_record_with_wrong_key_is_not_relabelled_as_matching_timing(self):
        spec, control_key, arm_key = self.partial_arm()
        self.stored[(self.results / "pilot", arm_key)]["key"] = "c" * 64
        found = self.plan(spec, control_dir=self.controls)
        self.assertEqual(found["arms"][0]["missing"], 8)
        self.assertIs(self.calculate.call_args.kwargs["samples"][arm_key], self.loaded[1][2])
        detail = found["estimate"]["arms"][0]
        self.assertEqual((detail["basis"], detail["sample_key"], detail["games_per_min"]),
                         ("control_proxy", control_key, 100))
        self.assert_no_effects()

    def test_zero_work_bypasses_optional_metadata_and_passes_no_samples_or_rates(self):
        spec, control_key, arm_key = self.partial_arm()
        self.cache(self.results / "pilot", arm_key, range(10), spec["pairs"][0])
        experiment._plan_timing_metadata.side_effect = AssertionError("zero-work metadata")
        found = self.plan(spec, control_dir=self.controls)
        self.assertEqual(found["totals"]["games"], 0)
        experiment._plan_timing_metadata.assert_not_called()
        self.calculate.assert_called_once_with(found, local=False)
        self.assertEqual(found["estimate"]["remaining_games"], 0)
        self.assertEqual(found["estimate"]["minutes"], [0.0, 0.0])
        self.assertEqual(found["estimate"]["basis"], "none")
        self.assertEqual(experiment.saved.load.call_count, 2)  # the original cache-count reads only
        self.assert_no_effects()

    def test_selected_only_skipped_arms_and_extra_seed_controls_use_original_missing_counts(self):
        spec = copy.deepcopy(self.spec)
        spec["pairs"] = [spec["pairs"][0]]
        spec["arms"]["seed"] = {"seeds": {"stream_from": ["casual/green", "casual/blue"],
                                            "seat_of": "casual/green"}}
        found = self.plan(spec, only=["seed"])
        self.assertEqual(found["totals"], {"control_games": 20, "arm_games": 10, "games": 30})
        self.assertEqual(len(found["estimate"]["controls"]), 2)
        self.assertEqual(len({row["key"] for row in found["estimate"]["controls"]}), 2)
        self.assertEqual(found["estimate"]["remaining_games"], 30)
        self.reset_reads()
        found = self.plan(spec, only=["pilot"])
        self.assertEqual(found["totals"], {"control_games": 10, "arm_games": 10, "games": 20})
        self.assertEqual(len(found["estimate"]["controls"]), 1)
        self.assertEqual({row["arm"] for row in found["estimate"]["arms"]}, {"pilot"})
        self.assertEqual(found["estimate"]["remaining_games"], 20)
        self.reset_reads()
        found = self.plan()
        self.assertEqual(found["arms"][1]["missing"], 0)
        self.assertTrue(found["arms"][1]["skipped"])
        self.assertEqual(found["estimate"]["arms"][1]["remaining_games"], 0)
        self.assertEqual(found["estimate"]["arms"][1]["minutes"], [0.0, 0.0])
        self.assertEqual(found["estimate"]["remaining_games"], 30)
        self.assert_no_effects()

    def test_conflicting_same_key_snapshots_drop_measurement_instead_of_last_wins(self):
        spec, control_key, _ = self.partial_arm()
        found = self.plan(spec, control_dir=self.controls)
        receipt = self.loaded[0][2]
        conflict = copy.deepcopy(receipt)
        conflict["runs"][0]["wall_s"] *= 2
        self.reset_reads()
        experiment._plan_estimate(found, [(control_key, receipt), (control_key, conflict), (control_key, receipt)])
        self.assertNotIn(control_key, self.calculate.call_args.kwargs["samples"])
        experiment.saved.load.assert_not_called()
        self.assert_no_effects()

    def test_optional_metadata_or_helper_exception_preserves_the_plan_with_fixed_unavailable_timing(self):
        baseline = self.plan()
        expected = {"remaining_games": 30, "minutes": None, "complete": False, "basis": "unavailable",
                    "workers": None, "assumed_workers": None,
                    "assumptions": [*experiment.experiment_estimate.BASE_ASSUMPTIONS,
                                    experiment.experiment_estimate.UNAVAILABLE], "controls": [], "arms": []}
        for target in (experiment._plan_timing_metadata, self.calculate):
            with self.subTest(target=target):
                target.side_effect = RuntimeError("private fixture path and diagnostic")
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    found = self.plan()
                self.assertEqual(found["estimate"], expected)
                self.assertEqual({key: value for key, value in found.items() if key != "estimate"},
                                 {key: value for key, value in baseline.items() if key != "estimate"})
                self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
                self.assertNotIn("private fixture", json.dumps(found, allow_nan=False))
                target.side_effect = None
        self.assert_no_effects()


class QuietPlanTimingMetadataTests(unittest.TestCase):

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="decklab-plan-timing-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.settings = {"forge_workers": 8}
        for target, name, value in ((experiment.common, "DATA_DIR", self.root),
                                    (experiment.common, "_settings", mock.Mock(side_effect=lambda: self.settings)),
                                    (experiment.common, "_log", mock.Mock())):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def metadata(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            found = _metadata_reader()
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
        experiment.common._log.assert_not_called()
        return found

    def write(self, value):
        (self.root / estimate.RATES_FILE).write_text(json.dumps(value), encoding="utf-8")

    def test_missing_optional_file_uses_existing_defaults_and_explicit_worker_count(self):
        self.assertEqual(self.metadata(), (estimate.DEFAULT_RATES, 8))

    def test_named_rates_override_workload_rates_without_reading_other_settings(self):
        self.write({"warm_games_per_min": {"IG": 400, "RV": 300, "GF": 190},
                    "rates": {"board": 330, "speed_up": 3, "medium": -1, "other": 999}})
        expected = {**estimate.DEFAULT_RATES, "fast": 400, "board": 330, "commander": 190, "speed_up": 3}
        self.assertEqual(self.metadata(), (expected, 8))
        experiment.common._settings.assert_called_once_with()

    def test_invalid_rate_values_and_worker_context_do_not_become_claimed_measurements(self):
        self.write({"rates": {"board": True, "fast": "bad", "commander": 0, "speed_up": float("nan")}})
        for value in (None, True, False, 8.9, "8", 0, -1, "bad", 10 ** 400, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.settings = {"forge_workers": value}
                self.assertEqual(self.metadata(), (estimate.DEFAULT_RATES, None))

    def test_corrupt_nonobject_or_failed_optional_metadata_stays_quiet_for_plan_fallback(self):
        path = self.root / estimate.RATES_FILE
        for text in ("{private fixture parse detail", "[]"):
            with self.subTest(text=text):
                path.write_text(text, encoding="utf-8")
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), self.assertRaises(ValueError):
                    _metadata_reader()
                self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
        self.write({})
        experiment.common._settings.side_effect = RuntimeError("private fixture settings detail")
        with self.assertRaises(RuntimeError):
            _metadata_reader()
        experiment.common._log.assert_not_called()
