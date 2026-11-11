"""Whole paired control and independent arms with disposable saved results, never Java."""
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib.forge import cli, common, engine, runner, saved, seqstats, variants, variants_controls as controls
from decklab.tests.test_forge import GREEN, RED, entry
from decklab.tests.test_forge_variants import FakeRuns, ORDER, changed

GREEN = GREEN.replace("6 Forest", "44 Forest")
RED = RED.replace("6 Mountain", "46 Mountain")


class ControlsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.base, self.opponent = entry(GREEN, "casual/green"), entry(RED, "casual/red")
        self.eng = engine._engine("decklab", "2.0.15", 120, ORDER["game_patches"],
                                  {"hash": "", "index": {}}, {"Default": "a" * 64}, True)
        self.calls = []
        self.fakes = {}
        for patch in (mock.patch.object(engine, "today", return_value=self.eng),
                      mock.patch.object(common, "_settings", return_value={"forge_field_inflight": 1}),
                      mock.patch.object(variants, "_base_key", side_effect=lambda a, b: engine._sha(sorted([a["card_sha"], b["card_sha"]]))),
                      mock.patch.object(runner, "run", side_effect=self._fake_run)):
            patch.start()
            self.addCleanup(patch.stop)

    def _fake_run(self, a, b, n, **kwargs):
        folder = Path(kwargs["results_dir"])
        fake = self.fakes.setdefault(folder, FakeRuns(folder))
        found = fake(a, b, n, **kwargs)
        self.calls.append({**fake.calls[-1], "folder": folder})
        found.update(engine.result_fields(self.eng, [a, b]))
        for side in found["sides"]:
            side.update(engine.side_fields(self.eng, side, {}))
        path = folder / ("paired" if kwargs.get("kind") == "paired" else "") / (found["key"] + ".json")
        path.write_text(json.dumps(found), encoding="utf-8")
        return found

    def test_placebo_uses_real_paired_pipeline_and_only_experiments(self):
        before = copy.deepcopy(self.base)
        found = variants.run_placebo(self.base, self.opponent, 50, by="Matt", results_dir=self.root)
        self.assertEqual(found["kind"], "placebo")
        self.assertEqual([call["kind"] for call in self.calls], [None, "paired"])
        self.assertTrue(all(call["folder"].is_relative_to(self.root / "experiments" / "placebo") for call in self.calls))
        self.assertEqual(found["opponents"][0]["paired"]["delta"], 0)
        self.assertGreater(found["opponents"][0]["paired"]["high"], 0)   # finite range, never exact zero
        self.assertIn("unknown", found["control_note"])
        self.assertEqual(self.base, before)
        self.assertEqual(saved._stored(self.root), [])
        self.assertEqual(variants.tests_for(self.base["id"], "target", self.root), [])
        self.assertFalse(list(self.root.glob("*.json")))
        self.assertEqual(variants.variant_entry(self.base, self.base["cards"], placebo=True)["dck"], self.base["dck"])

    def test_placebo_still_refuses_ordinary_no_change_and_adaptive_look(self):
        with self.assertRaisesRegex(ValueError, "no change"):
            variants.variant_entry(self.base, self.base["cards"])
        with self.assertRaisesRegex(ValueError, "unchanged"):
            variants.variant_entry(self.base, changed(GREEN, [(1, "Fiery Annihilation")], [(1, "Shock")]), placebo=True)
        with self.assertRaisesRegex(ValueError, "--games"):
            variants.run_placebo(self.base, self.opponent, "ahead", by="Matt", results_dir=self.root)
        self.assertEqual(self.calls, [])

    def test_exact_pair_noise_receipt_and_mismatched_pilot_or_engine(self):
        receipt = {"v": 1, "engine": engine.result_fields(self.eng), "lists": sorted([self.base["card_sha"], self.opponent["card_sha"]]),
                   "matchup": engine.key(self.base, self.opponent, self.eng), "pilot": {"profile": "Default", "switches": []},
                   "games": 25, "different_winners": 0, "different_outcomes": 3}
        path = self.root / "noise.json"
        path.write_text(json.dumps({"same_install": True, "same_key": True, "noise_floors": [receipt]}), encoding="utf-8")
        found = variants.run_placebo(self.base, self.opponent, 50, by="Matt", results_dir=self.root, noise_floor=path)
        self.assertEqual(found["noise_floor"][self.opponent["card_sha"]]["different_outcomes"], 3)
        other = {**self.base, "pilot": {"profile": "Default", "switches": ["fixture-1"]}}
        self.assertEqual(controls._noise(path, other, [self.opponent], self.eng), {})
        self.assertEqual(controls._noise(path, self.base, [self.opponent], {**self.eng, "clock_s": 9}), {})
        path.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid"):
            controls._noise(path, self.base, [self.opponent], self.eng)

    def test_independent_arms_resume_without_duplicate_games_and_stay_out_of_normal_views(self):
        cards = changed(GREEN, add=[(1, "Forest")])
        first = variants.run_unpaired(self.base, cards, self.opponent, 50, by="Matt", results_dir=self.root)
        self.assertEqual(first["kind"], "unpaired")
        self.assertEqual([call["kind"] for call in self.calls], ["unpaired", "unpaired"])
        self.assertNotEqual(self.calls[0]["seeds"]["stream"], self.calls[1]["seeds"]["stream"])
        self.assertFalse(first["opponents"][0]["difference"]["paired"])
        self.assertEqual((first["base"]["card_count"], first["variant"]["card_count"]), (60, 61))
        second = variants.run_unpaired(self.base, cards, self.opponent, 50, by="Matt", results_dir=self.root)
        self.assertEqual(first["test"], second["test"])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(saved._stored(self.root), [])
        for path in self.calls[0]["folder"].glob("[0-9a-f]*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(saved._is_result(value, path.stem))

    def test_size_bounds_mixed_format_and_same_size_refused_before_launch(self):
        for cards, words in ((changed(GREEN, [(1, "Forest")]), "at least 60"),
                             (changed(GREEN, [(1, "Forest")], [(1, "Mountain")]), "same-size"),
                             (changed(GREEN, add=[(1001, "Forest")]), "limited")):
            with self.subTest(words=words), self.assertRaisesRegex(ValueError, words):
                variants.run_unpaired(self.base, cards, self.opponent, 50, by="Matt", results_dir=self.root)
        with self.assertRaisesRegex(ValueError, "--games"):
            variants.run_unpaired(self.base, changed(GREEN, add=[(1, "Forest")]), self.opponent, True, by="Matt", results_dir=self.root)
        self.assertEqual(self.calls, [])


class IndependentMathTests(unittest.TestCase):
    def test_ignores_game_numbers_and_reports_all_denominators(self):
        base = [{"g": i, "w": i % 3 == 0, "first": i % 2} for i in range(200)]
        variant = [{"g": 900+i, "w": int(i % 3 != 0), "first": i % 2} for i in range(200)]
        before = copy.deepcopy((base, variant))
        found = seqstats.unpaired_diff(base, variant, 1, 1)
        self.assertGreater(found["delta"], .3)
        self.assertLess(found["low"], found["delta"])
        self.assertGreater(found["high"], found["delta"])
        self.assertEqual((base, variant), before)
        for game in variant:
            game["g"] = 0
        self.assertEqual(seqstats.unpaired_diff(base, variant, 1, 1), found)
        variant.append({"first": None, "w": 1})
        self.assertEqual(seqstats.unpaired_diff(base, variant, 1, 1)["variant"]["unknown_starter"], 1)
        self.assertIsNone(seqstats.unpaired_diff([], variant, 0, 1)["delta"])


class ControlCliTests(ControlsTests):
    def main(self, *args):
        out, err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8"), io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err), mock.patch("decklab.lib.forge.cli_shared._cli_entry", side_effect=lambda ref, owned: self.base if ref == "base" else self.opponent):
            code = cli.main(["variant", "base", "--against", "other", "--results-dir", str(self.root), *args])
            out.flush()
        return code, out.buffer.getvalue().decode("utf-8"), err.getvalue()

    def test_controls_are_explicit_and_text_labels_unknown_noise_or_not_paired(self):
        code, out, err = self.main("--placebo", "--games", "50")
        self.assertEqual(code, 0, err)
        self.assertIn("noise floor unknown", out)
        self.calls.clear()
        code, out, err = self.main("--size-change", "--add", "1 Forest", "--games", "50")
        self.assertEqual(code, 0, err)
        self.assertIn("not paired", out)
        self.assertIn("many more games", out)
        for args in (("--placebo",), ("--placebo", "--quick", "--add", "1 Forest"),
                     ("--placebo", "--size-change", "--quick"), ("--size-change", "--add", "1 Forest")):
            with self.subTest(args=args):
                self.assertEqual(self.main(*args)[0], 1)
