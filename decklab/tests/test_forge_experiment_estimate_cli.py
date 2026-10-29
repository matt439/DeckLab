"""Experiment dry-run presentation through the real parser with entirely in-process stand-ins."""
import contextlib
import copy
import io
import json
import unittest
from unittest import mock

from decklab.lib.forge import cli, cli_evaluate, common, engine, estimate, experiment, experiment_estimate as timing
from decklab.lib.forge import install, overrides, pool, runner
from decklab.tests.test_forge_experiment_estimate import arm, control, plan, v2


def found_plan(controls=(), arms=(), *, workers=16, samples=None):
    found = plan(controls, arms)
    found.update(games=50, results_dir="fixture-results", logs_dir="fixture-logs")
    controls_left = sum(row["missing"] for row in controls)
    arms_left = sum(row["missing"] for row in arms if not row.get("skipped"))
    found["totals"] = {"control_games": controls_left, "arm_games": arms_left, "games": controls_left + arms_left}
    found["estimate"] = timing.estimate_plan(found, samples=samples, workers=workers)
    return found


class ExperimentEstimateCliTests(unittest.TestCase):
    def run_cli(self, found, *options, load_error=None, plan_error=None, dry=True, run_result=None):
        output = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n")
        errors = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch("sys.stdout", output))
            stack.enter_context(mock.patch("sys.stderr", errors))
            load = stack.enter_context(mock.patch.object(experiment, "load_spec", return_value={"fixture": True},
                                                         side_effect=load_error))
            planned = stack.enter_context(mock.patch.object(experiment, "plan", return_value=copy.deepcopy(found),
                                                            side_effect=plan_error))
            ran = stack.enter_context(mock.patch.object(experiment, "run", return_value=run_result,
                side_effect=AssertionError("No dry-run experiment") if run_result is None else None))
            stack.enter_context(mock.patch.object(experiment, "report", return_value="Fixture report"))
            for module, name in ((common, "_settings"), (engine, "today"), (install, "_setup"),
                                 (overrides, "ensure_deployed"), (runner, "run"), (pool, "session"),
                                 (estimate, "rates")):
                stack.enter_context(mock.patch.object(module, name, side_effect=AssertionError("No runtime access")))
            stack.enter_context(mock.patch("pathlib.Path.read_text", side_effect=AssertionError("No file read")))
            stack.enter_context(mock.patch("decklab.lib.config.load", side_effect=AssertionError("No config read")))
            stack.enter_context(mock.patch("pathlib.Path.write_text", side_effect=AssertionError("No report write")))
            stack.enter_context(mock.patch("subprocess.Popen", side_effect=AssertionError("No child process")))
            code = cli.main(["experiment", "fixture-spec.json", *(["--dry-run"] if dry else []), *options])
            output.flush()
        return code, output.buffer.getvalue().decode("utf-8"), errors.getvalue(), load, planned, ran

    def test_text_keeps_existing_plan_rows_and_adds_remaining_time_only(self):
        base = control(missing=0, have=50, source="control_dir")
        changed = arm(missing=280, have=12)
        skipped = arm("skipped", 99, skipped="changes nothing")
        found = found_plan([base], [changed, skipped])
        code, text, errors, _, _, ran = self.run_cli(found, "--report", "must-not-be-written.md")
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("the control folder holds it, 0 to play", text)
        self.assertIn("12 played, 280 to play", text)
        self.assertIn("skipped (changes nothing)", text)
        self.assertIn("In all: 280 games (0 for controls, 280 for arms).", text)
        self.assertIn("Remaining game time: about 1-2 minutes.", text)
        self.assertIn("Timing basis: format fallback rates.", text)
        self.assertIn("Planning workers: 16.", text)
        ran.assert_not_called()

    def test_json_is_the_exact_augmented_plan_with_no_text_or_extra_reads(self):
        found = found_plan([control(missing=280)])
        before = copy.deepcopy(found)
        code, text, errors, _, _, ran = self.run_cli(found, "--json")
        self.assertEqual((code, errors), (0, ""))
        self.assertEqual(json.loads(text), found)
        self.assertEqual(found, before)
        self.assertNotIn("Remaining game time", text)
        ran.assert_not_called()

    def test_all_planning_arguments_are_forwarded_without_starting_a_run(self):
        code, _, _, load, planned, ran = self.run_cli(found_plan(), "--only", " arm-a, arm-b, ", "--games", "80",
            "--results-dir", "results-fixture", "--control-dir", "control-fixture",
            "--logs-dir", "logs-fixture", "--control-logs-dir", "control-logs-fixture", "--local")
        self.assertEqual(code, 0)
        load.assert_called_once_with("fixture-spec.json")
        planned.assert_called_once_with({"fixture": True}, results_dir="results-fixture", control_dir="control-fixture",
            only=["arm-a", "arm-b"], games=80, logs_dir="logs-fixture", control_logs_dir="control-logs-fixture", local=True)
        ran.assert_not_called()

    def test_subminute_json_keeps_positive_machine_spans_while_text_formats_them(self):
        row = control(missing=1)
        found = found_plan([row], samples={row["key"]: v2(row, [(900, 60, 16)])})
        code, text, errors, _, _, _ = self.run_cli(found, "--json")
        self.assertEqual((code, errors), (0, ""))
        decoded = json.loads(text)
        self.assertGreater(decoded["estimate"]["minutes"][0], 0)
        self.assertEqual(decoded["estimate"]["minutes"], found["estimate"]["minutes"])
        self.assertGreater(decoded["estimate"]["controls"][0]["minutes"][0], 0)
        _, text, _, _, _, _ = self.run_cli(found)
        self.assertIn("Remaining game time: under 1 minute.", text)

    def test_zero_and_positive_subminute_ranges_are_never_confused(self):
        _, text, _, _, _, _ = self.run_cli(found_plan([control(missing=0)]))
        self.assertIn("Remaining game time: 0 minutes; no games remain.", text)
        for span in ([0.001, 0.01], [0.5, 0.99]):
            found = found_plan([control(missing=1)])
            found["estimate"]["minutes"] = span
            _, text, _, _, _, _ = self.run_cli(found)
            self.assertIn("Remaining game time: under 1 minute.", text)
            self.assertNotIn("Remaining game time: 0", text)

    def test_longer_ranges_are_outward_rounded_and_single_minute_is_singular(self):
        for span, expected in (([1.1, 2.1], "about 1-3 minutes"), ([5, 5], "about 5 minutes"),
                               ([1, 1], "about 1 minute"), ([0.83, 1], "about 1 minute")):
            found = found_plan([control(missing=1)])
            found["estimate"]["minutes"] = span
            _, text, _, _, _, _ = self.run_cli(found)
            self.assertIn("Remaining game time: " + expected + ".", text)

    def test_measured_arm_proxy_and_control_proxy_provenance_are_distinct(self):
        base, changed = control(), arm()
        cases = [(found_plan([base], samples={base["key"]: v2(base)}), "measured control timings"),
                 (found_plan([], [changed], samples={changed["key"]: v2(changed)}), "arm proxy (prior arm timing)"),
                 (found_plan([dict(base, missing=0)], [changed], samples={base["key"]: v2(base)}),
                  "control proxy (control speed)")]
        for found, label in cases:
            _, text, _, _, _, _ = self.run_cli(found)
            self.assertIn("Timing basis: " + label + ".", text)
            if "proxy" in label:
                self.assertIn(timing.ARM_PROXY if label.startswith("arm") else timing.CONTROL_PROXY, text)

    def test_mixed_sources_list_actual_static_provenance_without_sample_keys(self):
        base = control()
        measured_arm = arm("old-arm")
        proxy = arm("proxy", pair=["casual/b", "casual/a"])
        fallback = arm("fallback", 280, pair=["casual/x", "casual/y"], card_shas=["x", "y"])
        found = found_plan([base], [measured_arm, proxy, fallback],
                           samples={base["key"]: v2(base), measured_arm["key"]: v2(measured_arm)})
        _, text, _, _, _, _ = self.run_cli(found)
        line = next(line for line in text.splitlines() if "Timing basis:" in line)
        for label in ("mixed timing sources", "measured control timings", "arm proxy", "control proxy", "format fallback"):
            self.assertIn(label, line)
        self.assertNotIn("sample_key", text)

    def test_assumed_workers_and_unknown_pool_context_stay_explicit(self):
        _, text, _, _, _, _ = self.run_cli(found_plan([control(missing=280)], workers=None))
        self.assertIn("Planning workers: unknown; legacy and format fallback rates assume 16 workers.", text)
        base = control()
        found = found_plan([base], samples={base["key"]: v2(base, [(900, 60, None)])}, workers=None)
        _, text, _, _, _, _ = self.run_cli(found)
        self.assertIn("Planning workers: unknown.", text)
        self.assertNotIn("assume 16", text)
        self.assertIn(timing.POOL_UNKNOWN, text)
        self.assertIn(timing.POOL_PLANNING_UNKNOWN, text)

    def test_known_worker_mismatch_prints_safe_reason_and_fallback_basis(self):
        base = control(missing=280)
        found = found_plan([base], samples={base["key"]: v2(base)}, workers=8)
        _, text, _, _, _, _ = self.run_cli(found)
        self.assertIn("Remaining game time: about 2-3 minutes.", text)
        self.assertIn("Planning workers: 8.", text)
        self.assertIn("Timing basis: format fallback rates.", text)
        self.assertIn(timing.POOL_MISMATCH, text)

    def test_unsupported_config_makes_whole_estimate_unavailable_not_a_partial_time(self):
        found = found_plan([control(missing=280)], [arm("config", 1, config={"arbitrary": True})])
        code, text, errors, _, _, _ = self.run_cli(found)
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("Remaining game time: estimate unavailable for the complete remaining work.", text)
        self.assertNotIn("Remaining game time: about", text)
        self.assertIn(timing.CONFIG_UNKNOWN, text)

    def test_optional_failure_or_missing_estimate_does_not_change_plan_success_or_leak_errors(self):
        for estimate_value in (None, {"minutes": None, "complete": False, "basis": "unavailable",
                                     "assumptions": ["SECRET database/config failure"]}):
            found = found_plan([control(missing=280)])
            found["estimate"] = estimate_value
            code, text, errors, _, _, _ = self.run_cli(found)
            self.assertEqual((code, errors), (0, ""))
            self.assertIn("In all: 280 games", text)
            self.assertIn("estimate unavailable", text)
            self.assertNotIn("SECRET", text)
            for assumption in timing.BASE_ASSUMPTIONS:
                self.assertIn(assumption, text)

    def test_invalid_optional_numeric_fields_are_unavailable_without_new_exit_error(self):
        for minutes in ([0, 0], [0, 0.5], [float("nan"), 2], [1, float("inf")], [-1, 1], [3, 2],
                        [True, 1], [10 ** 400, 2], "bad"):
            found = found_plan([control(missing=280)])
            found["estimate"]["minutes"] = minutes
            code, text, errors, _, _, _ = self.run_cli(found)
            self.assertEqual((code, errors), (0, ""))
            self.assertIn("estimate unavailable", text)
        found = found_plan([control(missing=280)])
        found["estimate"]["remaining_games"] = 999999
        _, text, _, _, _, _ = self.run_cli(found)
        self.assertIn("estimate unavailable", text)

    def test_fixed_assumptions_are_printed_and_arbitrary_metadata_messages_are_not(self):
        found = found_plan([control(missing=280)])
        found["estimate"]["assumptions"] += ["RAW PATH OR PRIVATE NOTE", "RAW STACK TRACE"]
        _, text, _, _, _, _ = self.run_cli(found)
        for assumption in timing.BASE_ASSUMPTIONS:
            self.assertIn(assumption, text)
        self.assertIn(timing.FORMAT_FALLBACK, text)
        self.assertNotIn("RAW", text)

    def test_malformed_optional_provenance_and_workers_cannot_raise_or_claim_a_worker_count(self):
        found = found_plan([control(missing=280)])
        found["estimate"].update(basis=[], workers=10 ** 5000, assumed_workers=True)
        code, text, errors, _, _, _ = self.run_cli(found)
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("estimate unavailable", text)
        self.assertIn("Planning workers: unknown.", text)
        found["estimate"].update(basis="mixed", controls=3, arms=[{"basis": [], "remaining_games": 10}])
        code, text, errors, _, _, _ = self.run_cli(found)
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("Timing basis: mixed timing sources.", text)

    def test_existing_spec_plan_and_argument_error_exit_paths_are_unchanged(self):
        for which in ("load_error", "plan_error"):
            code, text, errors, _, _, ran = self.run_cli(found_plan(), **{which: ValueError("Fixture spec refused")})
            self.assertEqual(code, 1)
            self.assertEqual(text, "")
            self.assertIn("Fixture spec refused", errors)
            ran.assert_not_called()
        with self.assertRaises(SystemExit) as raised:
            self.run_cli(found_plan(), "--games", "0")
        self.assertEqual(raised.exception.code, 2)

    def test_non_dry_run_report_and_success_or_failure_exit_paths_have_no_estimate_text(self):
        for failures, expected in (([], 0), ([{"arm": "fixture", "pair": ["casual/a", "casual/b"],
                                             "error": "Fixture run failed"}], 1)):
            code, text, errors, _, planned, ran = self.run_cli(found_plan(), dry=False,
                                                               run_result={"failed": failures})
            self.assertEqual(code, expected)
            self.assertEqual(text, "Fixture report\n")
            self.assertNotIn("Remaining game time", text)
            self.assertEqual(bool(errors), bool(failures))
            planned.assert_not_called()
            ran.assert_called_once()
