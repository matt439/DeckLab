"""The combined run's pilot experiments (D2d-p2: profile mirrors and the hybrid AI; D2e: pilot
sensitivity): their specs from prepare-inputs, the hybrid leg's speed gate, the plan items, and the
report's sections (sim-combined-run.md sections 6 D2d/D2e, 8 item 11 and 9.3)."""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "forge-trial"
sys.path.insert(0, str(HERE))

import overnight                 # noqa: E402
import overnight_legs            # noqa: E402
import overnight_report          # noqa: E402

from decklab.lib.forge import experiment, pilots  # noqa: E402

FIELD = ["casual/gruul-ramp", "casual/izzet-prowess", "casual/mono-black-midrange", "casual/mono-white-angels",
         "casual/orzhov-vampires", "casual/selesnya-rabbits"]
SETS = {"fiery": {"status": "adopted", "files": {"f.txt": {"card": "Fiery Annihilation"}}},
        "etb": {"status": "experiment", "files": {"a.txt": {"card": "A"}, "fires.txt": {"card": "Fires"}}},
        "etb-flagged": {"status": "experiment", "files": {"fires.txt": {"card": "Fires"}, "s.txt": {"card": "S"}}},
        "tgt": {"status": "experiment", "files": {"t.txt": {"card": "T"}}}}


def _fake_env(switches=("aisim-hybrid-1", "team-pump-1")):
    return [mock.patch.object(overnight_legs, "_entry", lambda deck: {"id": deck}),
            mock.patch.object(pilots, "available", lambda: {"profiles": ["Cautious", "DLAggro", "DLControl", "Default",
                                                                         "Reckless"], "switches": list(switches)}),
            mock.patch.object(pilots, "pilot_for", lambda deck, version: {"profile": "Default", "switches": []}),
            mock.patch("decklab.lib.forge.field.field_lists", lambda fmt: [{"id": d} for d in FIELD])]


class Specs(unittest.TestCase):
    def specs(self, switches=("aisim-hybrid-1", "team-pump-1"), sets=SETS):
        patches = _fake_env(switches)
        for p in patches:
            p.start()
        try:
            return {**overnight_legs._pilot_specs(), **overnight_legs._sensitivity_specs(sets)}
        finally:
            for p in patches:
                p.stop()

    def test_experiment_sets_leave_out_adopted_and_overlapping(self):
        self.assertEqual(overnight_legs._experiment_sets(SETS), ["etb", "tgt"])

    def test_profiles_spec(self):
        spec = self.specs()["exp-profiles.json"]
        self.assertEqual(spec["games"], 800)
        self.assertIn(["casual/selesnya-rabbits", "casual/orzhov-vampires"], spec["pairs"])
        for deck in ("casual/selesnya-rabbits", "casual/gruul-ramp", "casual/mono-white-angels",
                     "casual/izzet-prowess", "casual/mono-black-midrange"):
            self.assertIn([deck, deck], spec["pairs"])
        arm = spec["arms"]["selesnya-rabbits-reckless"]
        self.assertEqual(arm, {"pilots": {"casual/selesnya-rabbits": {"profile": "Reckless", "switches": []}},
                               "sides": "a"})
        self.assertEqual(spec["arms"]["mono-black-midrange-cautious"]["pilots"]["casual/mono-black-midrange"]
                         ["profile"], "Cautious")
        self.assertEqual(len(spec["arms"]), 6)

    def test_hybrid_specs_speed_first(self):
        specs = self.specs()
        hybrid, mirror = specs["exp-hybrid.json"], specs["exp-hybrid-mirror.json"]
        self.assertEqual((hybrid["games"], hybrid["pairs"]), (100, [list(overnight_legs.WORKLOADS["IG"])]))
        self.assertTrue(all("aisim-hybrid-1" in p["switches"] for p in hybrid["arms"]["hybrid"]["pilots"].values()))
        self.assertNotIn("sides", hybrid["arms"]["hybrid"])          # both lists on the hybrid AI: speed
        self.assertEqual(mirror["games"], 400)
        self.assertEqual(mirror["arms"]["hybrid"]["sides"], "a")

    def test_no_hybrid_without_its_switch(self):
        specs = self.specs(switches=("team-pump-1",))
        self.assertNotIn("exp-hybrid.json", specs)
        self.assertIn("exp-profiles.json", specs)

    def test_sensitivity_specs(self):
        specs = self.specs()
        b, c = specs["exp-sensitivity-b.json"], specs["exp-sensitivity-c.json"]
        self.assertEqual(len(b["pairs"]), 15)                       # every pairing of the 6-list field
        self.assertEqual(b["games"], 200)
        self.assertEqual(b["arms"], {"overrides": {"overrides": ["etb", "tgt"]}})
        self.assertEqual(len(c["pairs"]), 5)
        self.assertTrue(all(p[0] == "casual/selesnya-rabbits" for p in c["pairs"]))
        arm = c["arms"]["overrides-reckless"]
        self.assertEqual(arm["overrides"], ["etb", "tgt"])
        self.assertEqual(arm["pilots"]["casual/selesnya-rabbits"]["profile"], "Reckless")

    def test_sensitivity_without_experiment_sets(self):
        specs = self.specs(sets={"fiery": SETS["fiery"]})
        self.assertNotIn("exp-sensitivity-b.json", specs)
        self.assertEqual(list(specs["exp-sensitivity-c.json"]["arms"]), ["reckless"])

    def test_specs_pass_the_experiment_check(self):
        """The real sets.json and profiles: every spec checks (check_spec), as --dry-run does first."""
        real = experiment._sets()
        patches = _fake_env()
        for p in patches:
            p.start()
        try:
            specs = {**overnight_legs._pilot_specs(), **overnight_legs._sensitivity_specs(real)}
        finally:
            for p in patches:
                p.stop()
        for name, spec in specs.items():
            with self.subTest(name):
                experiment.check_spec(json.loads(json.dumps(spec)))


class HybridLeg(unittest.TestCase):
    def run_leg(self, slowdown):
        calls = []

        def fake_run(spec, **kw):
            calls.append((spec["name"], kw))
            return {"failed": [], "arms": {"hybrid": {"pooled": {"speed": {"slowdown": slowdown}}}}}

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "inputs").mkdir()
            for name, games in (("hybrid", 100), ("hybrid-mirror", 400)):
                pair = ["casual/izzet-prowess", "casual/gruul-ramp"] if name == "hybrid" else \
                    ["casual/mono-black-midrange"] * 2
                (tmp / "inputs" / f"exp-{name}.json").write_text(json.dumps(
                    {"name": name, "games": games, "pairs": [pair],
                     "arms": {"hybrid": {"pilots": {pair[0]: {"profile": "Default", "switches": ["aisim-hybrid-1"]}},
                                         "sides": "a"}}, "measures": ["matchup", "speed"]}), encoding="utf-8")
            args = overnight_legs.main.__globals__["argparse"].Namespace(
                inputs=str(tmp / "inputs"), experiments=str(tmp / "exp"), logs_dir=str(tmp / "logs"),
                control_dir=str(tmp / "staging"), control_logs_dir=None, games=100, mirror_games=400,
                out=str(tmp / "D"))
            with mock.patch.object(experiment, "run", fake_run), \
                    mock.patch.object(overnight_legs, "_stopped", lambda: False):
                code = overnight_legs.leg_hybrid(args)
            row = json.loads((tmp / "D" / "result.json").read_text(encoding="utf-8"))
        return code, row, calls

    def test_speed_part_plays_its_own_control(self):
        code, row, calls = self.run_leg(2.0)
        self.assertEqual(code, 0)
        self.assertNotIn("control_dir", calls[0][1])                 # same load for plain and hybrid games
        self.assertEqual([c[0] for c in calls], ["hybrid", "hybrid-mirror"])
        self.assertTrue(calls[1][1]["control_dir"].endswith("staging"))      # the mirror's control: staging
        self.assertEqual(row["mirror"], "played")

    def test_mirror_only_when_cheap_enough(self):
        code, row, calls = self.run_leg(4.5)
        self.assertEqual([c[0] for c in calls], ["hybrid"])
        self.assertIn("4.50 times", row["mirror"])


class Plan(unittest.TestCase):
    def test_plan_items(self):
        plan = overnight.load_plan()
        items = {i["id"]: i for i in plan["items"]}
        self.assertEqual(items["D2d-p2"]["specs"], ["exp-profiles.json"])
        h = items["D2d-p2h"]
        self.assertEqual((h["priority"], h["leg"], h["exclusive"]), (2, "hybrid", True))
        self.assertIn("hybrid", overnight.leg_names())
        for name in ("D2e-b", "D2e-c"):
            cmd = items[name]["spec_cmd"]
            self.assertEqual(cmd[cmd.index("--games") + 1], "{games:200}")
        self.assertEqual((items["D2e-b"]["priority"], items["D2e-c"]["priority"]), (2, 3))

    def test_resolve_skips_the_hybrid_without_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "inputs").mkdir()
            built = {p: {"built": True} for p in ("X", "R", "A", "F", "S", "E", "C", "P", "D", "H")}
            resolved = overnight.resolve(overnight.load_plan(), out, main=str(out), built=built,
                                         legs=overnight.leg_names())
            items = {i["id"]: i for i in resolved["items"]}
            self.assertEqual(items["D2d-p2h"]["status"], "skipped")
            self.assertIn("no inputs", items["D2d-p2h"]["why"])
            (out / "inputs" / "exp-hybrid.json").write_text("{}", encoding="utf-8")
            resolved = overnight.resolve(overnight.load_plan(), out, main=str(out), built=built,
                                         legs=overnight.leg_names())
            items = {i["id"]: i for i in resolved["items"]}
            self.assertEqual(items["D2d-p2h"]["status"], "pending")


def _result(pair, games, start_wins):
    """A stored result of pair (side 0 = pair[0]) whose side 0 wins the games g < start_wins."""
    return {"key": "k", "sides": [{"card_sha": f"sha-{d}", "seen_as": [{"id": d}]} for d in pair],
            "batches": [{"games": [{"g": g, "w": 0 if g < start_wins else 1, "first": g % 2, "r": "win"}
                                   for g in range(games)]}], "updated": "2026-10-03T22:00:00"}


class Report(unittest.TestCase):
    def test_bh(self):
        self.assertEqual(overnight_report._bh([0.001, 0.5, 0.02, 0.9]), {0, 2})
        self.assertEqual(overnight_report._bh([0.5, 0.6]), set())

    def write_out(self, tmp):
        out = Path(tmp)
        prof = out / "experiments" / "exp-profiles"
        prof.mkdir(parents=True)
        (prof / "experiment.json").write_text(json.dumps({"experiment": "profiles", "games": 800, "arms": {
            "selesnya-rabbits-reckless": {"recommendation": "adopt", "why": ["Every rule of section 12.4 holds."],
                                          "games_per_pair": None, "pooled": {"speed": {"slowdown": 1.1}},
                                          "pairs": [{"pair": ["r", "r"], "mirror": {"value": 0.56, "low": 0.52,
                                                                                    "high": 0.6},
                                                     "games": {"arm": 800}, "matchup": None},
                                                    {"pair": ["r", "v"], "mirror": None, "games": {"arm": 800},
                                                     "matchup": {"delta": 0.01, "low": -0.02, "high": 0.04,
                                                                 "z": 0.6}}]}}}), encoding="utf-8")
        decks = ["d1", "d2", "d3"]
        sens = out / "experiments" / "exp-sensitivity-b"
        staging = out / "staging" / "results"
        staging.mkdir(parents=True)
        pairs, skipped = [], []
        wins = {("d1", "d2"): 130, ("d1", "d3"): 160, ("d2", "d3"): 130}
        for n, (a, b) in enumerate([("d1", "d2"), ("d1", "d3"), ("d2", "d3")]):
            ck, ak = f"{n:064x}", f"{n + 10:064x}"
            control = _result([a, b], 200, wins[a, b])
            (staging / f"{ck}.json").write_text(json.dumps(control), encoding="utf-8")
            if (a, b) == ("d2", "d3"):
                skipped.append({"arm": "overrides", "pair": [a, b], "why": "the arm changes nothing in this pair"})
                continue
            arm = _result([a, b], 200, 200 - wins[a, b] if (a, b) == ("d1", "d2") else wins[a, b])
            (sens / "overrides").mkdir(parents=True, exist_ok=True)
            (sens / "overrides" / f"{ak}.json").write_text(json.dumps(arm), encoding="utf-8")
            z = -8.0 if (a, b) == ("d1", "d2") else 0.0
            pairs.append({"pair": [a, b], "key": ak, "control_key": ck, "perspective": a,
                          "matchup": {"delta": -0.5 if z else 0.0, "low": -0.6, "high": -0.4, "z": z}})
        (sens / "experiment.json").write_text(json.dumps({"experiment": "sensitivity-b", "games": 200, "arms": {
            "overrides": {"pairs": pairs}}, "skipped": skipped}), encoding="utf-8")
        sens_c = out / "experiments" / "exp-sensitivity-c"
        (sens_c / "overrides-reckless").mkdir(parents=True)
        (sens_c / "overrides-reckless" / f"{99:064x}.json").write_text(
            json.dumps(_result(["d1", "d3"], 200, 100)), encoding="utf-8")
        (sens_c / "experiment.json").write_text(json.dumps({"experiment": "sensitivity-c", "games": 200, "arms": {
            "overrides-reckless": {"pairs": [{"pair": ["d1", "d3"], "key": f"{99:064x}", "control_key": f"{1:064x}",
                                              "perspective": "d1", "matchup": {"delta": -0.3, "low": -0.4,
                                                                               "high": -0.2, "z": -6.0}}]}},
            "skipped": []}), encoding="utf-8")
        return out, decks

    def test_pilot_rows_and_sensitivity(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, decks = self.write_out(tmp)
            pil = overnight_report.pilot_rows(out)
            self.assertEqual(pil["arms"][0]["recommendation"], "adopt")
            self.assertEqual(pil["arms"][0]["mirror"][0]["games"], 800)
            sens = overnight_report.sensitivity(out)
            self.assertEqual(sens["pairings"], 3)
            self.assertEqual(set(sens["ratings"]["a"]), set(decks))
            self.assertEqual([f["pair"] for f in sens["flips"]["b"]], [["d1", "d2"]])
            ra = sens["ratings"]["a"]
            self.assertGreater(ra["d1"], ra["d2"])
            self.assertGreater(ra["d2"], ra["d3"])
            self.assertTrue(all(v is not None and v >= 0 for v in sens["spread"].values()))
            self.assertEqual([f["pair"] for f in sens["flips"]["c"]], [["d1", "d3"]])
            self.assertLess(sens["ratings"]["c"]["d1"], sens["ratings"]["b"]["d1"])
            lines = "\n".join(overnight_report._pilot_markdown(pil, sens))
            self.assertIn("Adoption candidates: selesnya-rabbits-reckless (exp-profiles)", lines)
            self.assertIn("## Pilot sensitivity (D2e)", lines)
            self.assertIn("d1 v d2", lines)

    def test_report_without_pilot_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = overnight_report.build(tmp)
            self.assertEqual(found["pilots"], {"arms": [], "hybrid": None})
            self.assertIsNone(found["sensitivity"])
            text = overnight_report._markdown(found)
            self.assertNotIn("## Pilot experiments", text)

    def test_markdown_survives_a_broken_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(overnight_report, "sensitivity", side_effect=ValueError("bad")):
                found = overnight_report.build(tmp)
            self.assertIn("error", found["sensitivity"])
            self.assertIn("couldn't work them out", overnight_report._markdown(found))


if __name__ == "__main__":
    unittest.main()
