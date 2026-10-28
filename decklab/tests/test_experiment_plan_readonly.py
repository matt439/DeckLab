"""Experiment plans over pure metadata and saved-reader fixtures; no Forge or private files."""
import copy
import hashlib
import io
import json
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib.forge import cli, experiment


class ReadOnlyExperimentPlanTests(unittest.TestCase):

    def setUp(self):
        self.results, self.controls, self.user = Path("fixture-results"), Path("fixture-controls"), Path("fixture-user")
        self.identity = {"kind": experiment.engine.KIND_DECKLAB, "complete": True,
                         "identity_problem": None, "fixture_identity": "same-installed-engine"}
        self.entries = {f"casual/{name}": {"id": f"casual/{name}", "version": "target", "title": name.title(),
                        "kind": "constructed", "card_sha": hashlib.sha256(name.encode()).hexdigest(),
                        "cards": {"Main": [[4, name.title() + " Card"]]}}
                        for name in ("green", "red", "blue")}
        self.spec = {"name": "read-only-plan", "games": 10,
                     "pairs": [["casual/green", "casual/red"], ["casual/red", "casual/blue"]],
                     "arms": {"pilot": {"pilots": {"casual/green": {"profile": "Reckless"}}}}}
        self.stored = {}
        self.blocked = {}
        for target, name, value in (
            (experiment, "_entry", mock.Mock(side_effect=lambda ref: copy.deepcopy(self.entries[ref]))),
            (experiment, "_adopted", mock.Mock(return_value=[])),
            (experiment, "_given_controls", mock.Mock(return_value=None)),
            (experiment, "load_spec", mock.Mock(side_effect=lambda path: copy.deepcopy(self.spec))),
            (experiment.engine, "today", mock.Mock(side_effect=lambda *args, **kwargs: copy.deepcopy(self.identity))),
            (experiment.engine, "key", mock.Mock(side_effect=self.key)),
            (experiment.saved, "load", mock.Mock(side_effect=self.saved)),
            (experiment.common, "_user_dir", mock.Mock(return_value=self.user)),
        ):
            self.patch(target, name, value)
        for target, name in (
            (experiment.overrides, "ensure_deployed"), (experiment.install, "_setup"),
            (experiment.pool, "session"), (experiment.runner, "run"),
            (experiment.subprocess, "Popen"), (experiment.subprocess, "run"),
            (experiment.common, "_write_atomic"), (experiment.engine, "_remember"),
            (experiment.common, "_settings"), (Path, "mkdir"), (Path, "write_text"), (Path, "write_bytes"),
        ):
            blocked = mock.Mock(side_effect=AssertionError("Dry run attempted " + name))
            self.patch(target, name, blocked)
            self.blocked[name] = blocked

    def patch(self, target, name, value):
        patcher = mock.patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def key(self, a, b, identity):
        # A pure identity-sensitive control key; actual engine key parity has separate fixtures.
        payload = [sorted([a["card_sha"], b["card_sha"]]), identity["fixture_identity"]]
        return hashlib.sha256(json.dumps(payload).encode()).hexdigest()

    def control_key(self, a, b):
        return self.key(self.entries[a], self.entries[b], self.identity)

    def saved(self, key, folder):
        return copy.deepcopy(self.stored.get((Path(folder), key)))

    def cache(self, folder, key, numbers):
        self.stored[(Path(folder), key)] = {"batches": [{"games": [{"g": g} for g in numbers]}]}

    def plan(self, spec=None, **options):
        return experiment.plan(spec or self.spec, results_dir=self.results, **options)

    def assert_no_effects(self):
        for name, blocked in self.blocked.items():
            with self.subTest(effect=name):
                blocked.assert_not_called()

    def invoke(self, *args):
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n")
        err = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = cli.main(["experiment", "fixture-spec.json", "--dry-run", "--results-dir", str(self.results), *args])
            out.flush()
            text = out.buffer.getvalue().decode("utf-8")
        return code, text, err.getvalue()

    def test_plan_uses_explicit_readonly_identity_and_preserves_its_existing_public_shape(self):
        found = self.plan()
        experiment.engine.today.assert_called_once_with(experiment.engine.KIND_DECKLAB, read_only=True)
        self.assertEqual(set(found), {"experiment", "results_dir", "logs_dir", "games", "controls", "arms", "totals"})
        self.assertEqual(found["totals"], {"control_games": 20, "arm_games": 10, "games": 30})
        self.assertEqual(found["arms"][0]["missing"], 10)
        self.assertTrue(found["arms"][1]["skipped"])
        self.assertEqual(found["arms"][1]["missing"], 0)
        self.assert_no_effects()

    def test_current_external_control_is_reused_exactly_and_only_missing_arm_numbers_count(self):
        spec = {**self.spec, "pairs": [self.spec["pairs"][0]]}
        key = self.control_key("casual/green", "casual/red")
        self.cache(self.controls, key, range(12))
        first = self.plan(spec, control_dir=self.controls)
        arm_key = first["arms"][0]["key"]
        self.cache(self.results / "pilot", arm_key, [0, 3])
        before = copy.deepcopy(self.stored)
        found = self.plan(spec, control_dir=self.controls)
        self.assertEqual(found["controls"][0]["key"], key)
        self.assertEqual((found["controls"][0]["source"], found["controls"][0]["have"],
                          found["controls"][0]["missing"]), ("control_dir", 10, 0))
        self.assertEqual((found["arms"][0]["have"], found["arms"][0]["missing"]), (2, 8))
        self.assertEqual(found["totals"], {"control_games": 0, "arm_games": 8, "games": 8})
        self.assertEqual(self.stored, before)
        self.assert_no_effects()

    def test_partial_external_control_keeps_existing_local_control_reuse_semantics(self):
        spec = {**self.spec, "pairs": [self.spec["pairs"][0]]}
        key = self.control_key("casual/green", "casual/red")
        self.cache(self.controls, key, range(6))
        self.cache(self.results / "control", key, range(2))
        found = self.plan(spec, control_dir=self.controls)
        self.assertEqual((found["controls"][0]["source"], found["controls"][0]["have"],
                          found["controls"][0]["missing"]), ("control", 2, 8))
        self.assertEqual(found["totals"], {"control_games": 8, "arm_games": 10, "games": 18})
        self.assert_no_effects()

    def test_only_and_skipped_pairs_do_not_create_work_for_unselected_arms(self):
        spec = copy.deepcopy(self.spec)
        spec["arms"]["blue"] = {"pilots": {"casual/blue": {"profile": "Reckless"}}}
        found = self.plan(spec, only=["blue"])
        self.assertEqual({row["arm"] for row in found["arms"]}, {"blue"})
        self.assertTrue(found["arms"][0]["skipped"])
        self.assertEqual(found["arms"][0]["missing"], 0)
        self.assertEqual(found["arms"][1]["missing"], 10)
        self.assertEqual(found["totals"], {"control_games": 20, "arm_games": 10, "games": 30})
        self.assert_no_effects()

    def test_extra_seed_control_is_counted_once_and_only_when_its_arm_is_selected(self):
        spec = {**copy.deepcopy(self.spec), "pairs": [self.spec["pairs"][0]]}
        spec["arms"]["seed"] = {"seeds": {"stream_from": ["casual/green", "casual/blue"],
                                            "seat_of": "casual/green"}}
        found = self.plan(spec, only=["seed"])
        self.assertEqual({tuple(row["pair"]) for row in found["controls"]},
                         {("casual/green", "casual/red"), ("casual/blue", "casual/green")})
        self.assertEqual(found["totals"], {"control_games": 20, "arm_games": 10, "games": 30})
        found = self.plan(spec, only=["pilot"])
        self.assertEqual(len(found["controls"]), 1)
        self.assertEqual(found["totals"], {"control_games": 10, "arm_games": 10, "games": 20})
        self.assert_no_effects()

    def test_fully_cached_plan_reports_zero_without_changing_records(self):
        spec = {**self.spec, "pairs": [self.spec["pairs"][0]]}
        key = self.control_key("casual/green", "casual/red")
        self.cache(self.controls, key, range(10))
        first = self.plan(spec, control_dir=self.controls)
        self.cache(self.results / "pilot", first["arms"][0]["key"], range(10))
        before = copy.deepcopy(self.stored)
        found = self.plan(spec, control_dir=self.controls)
        self.assertEqual(found["totals"], {"control_games": 0, "arm_games": 0, "games": 0})
        self.assertEqual(self.stored, before)
        self.assert_no_effects()

    def test_incomplete_identity_refuses_before_any_cached_control_entry_or_saved_read(self):
        self.identity.update(complete=False, identity_problem="private fixture identity detail")
        with self.assertRaises(experiment.ForgeError) as caught:
            self.plan()
        self.assertEqual(str(caught.exception), experiment.PLAN_IDENTITY_UNKNOWN)
        self.assertNotIn("private fixture", str(caught.exception))
        experiment.saved.load.assert_not_called()
        experiment._given_controls.assert_not_called()
        experiment._entry.assert_not_called()
        self.assert_no_effects()

    def test_cli_json_and_text_dry_runs_start_nothing_and_never_write_the_optional_report(self):
        before = copy.deepcopy(self.stored)
        code, text, error = self.invoke("--json", "--report", "must-not-be-written.md")
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(text)["totals"], {"control_games": 20, "arm_games": 10, "games": 30})
        code, text, error = self.invoke("--only", "pilot")
        self.assertEqual(code, 0, error)
        self.assertIn("In all: 30 games", text)
        self.assertEqual(self.stored, before)
        self.assert_no_effects()

    def test_cli_incomplete_identity_has_explicit_failure_without_successful_looking_json_counts(self):
        self.identity.update(complete=False, identity_problem="private fixture identity detail")
        code, text, error = self.invoke("--json")
        self.assertEqual(code, 1)
        self.assertEqual(text, "")
        self.assertIn(experiment.PLAN_IDENTITY_UNKNOWN, error)
        self.assertNotIn("private fixture", error)
        experiment.saved.load.assert_not_called()
        experiment._given_controls.assert_not_called()
        self.assert_no_effects()

    def test_legacy_layout_default_keeps_deployment_and_existing_today_call_shape(self):
        with mock.patch.object(experiment.overrides, "ensure_deployed") as deployed:
            found = experiment._layout(experiment.check_spec(self.spec), results_dir=self.results)
        deployed.assert_called_once_with(self.user)
        experiment.engine.today.assert_called_once_with(experiment.engine.KIND_DECKLAB)
        self.assertEqual(len(found["controls"]), 2)
        for name, blocked in self.blocked.items():
            if name != "ensure_deployed":
                blocked.assert_not_called()
