"""Tests for the combined run's report and controller completeness for a long night (forge-trial/
overnight.py and overnight_report.py; sim-combined-run.md sections 5.5, 6 C, 8 and 9.1): MG10's
heap growth and heap-limit recycles, MG13's D3a adaptive-against-reference comparison, REPORT.md's
section 8 parts (replay, field, M4, experiments with adoption candidates, E3's numbers, next
steps), the fail-fast diagnostics, the supervisor's end after its last restart, D8's refusal,
A1's pool-service check, E3's card-data check, and the plan for a 12:30 deadline.

Run from the repo root: python scripts/test_fixtures.py
The fixture runner disables configured PostgreSQL and real Forge; named native
runtime cases also need separate qualification (see AGENTS.md, Tests).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "forge-trial"
sys.path.insert(0, str(HERE))

import overnight                 # noqa: E402
import overnight_legs            # noqa: E402
import overnight_report          # noqa: E402

D_START = "2026-10-03T23:00:00"


def _epoch(stamp):
    return time.mktime(time.strptime(stamp, "%Y-%m-%dT%H:%M:%S"))


def item(id_, priority=1, est_min=10, block="D", **kw):
    return dict({"id": id_, "block": block, "priority": priority, "est_s": est_min * 60.0, "status": "pending",
                 "requires": []}, **kw)


def games(n, side0_wins, first_alternates=True):
    """n games; side 0 wins the first side0_wins of them; starters alternate."""
    return [{"g": g, "first": g % 2 if first_alternates else 0, "w": 0 if g < side0_wins else 1, "r": "win"}
            for g in range(n)]


def result(key, sha_a, sha_b, played, seeds=True, **kw):
    found = {"key": key, "sides": [{"card_sha": sha_a, "dck": ""}, {"card_sha": sha_b, "dck": ""}],
             "format": "Constructed", "batches": [{"games": played}], **kw}
    if seeds:
        found["seeds"] = {"base": 1}
    return found


class SmallFixTests(unittest.TestCase):

    def test_d8_refusal_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "final.json"
            Path(str(path) + ".out.txt").write_text("error: no live server pool on port 8643\n", encoding="utf-8")
            t0 = time.time() - 2
            found = overnight.final_probe_outcome(1, path, t0)
            self.assertEqual(found["status"], "failed")
            self.assertIn("no live server pool", found["note"])
            path.write_text("{}", encoding="utf-8")
            self.assertEqual(overnight.final_probe_outcome(1, path, t0)["status"], "done")    # differences: MG7's
            self.assertEqual(overnight.final_probe_outcome(0, path, t0)["status"], "done")
            self.assertEqual(overnight.final_probe_outcome(0, path, time.time() + 60)["status"], "failed")  # stale
            self.assertEqual(overnight.final_probe_outcome(2, path, t0)["status"], "failed")

    def test_foreign_pool_services(self):
        services = [{"pid": 10, "checkout": "C:/main"}, {"pid": 11, "checkout": "C:/other"}]
        self.assertEqual([s["pid"] for s in overnight.foreign_services(services, 10, "C:/main")], [11])
        self.assertEqual([s["pid"] for s in overnight.foreign_services(services, None, "C:/main")], [11])
        self.assertEqual([s["pid"] for s in overnight.foreign_services(services, None, None)], [10, 11])
        self.assertEqual(overnight.foreign_services(None, None, None), [])

    def test_only_answering_services_gate(self):
        # a stale file whose pid Windows reused has no status: reported, never a reason to stop at A1
        answering, stale = overnight.split_answering([{"pid": 10, "status": {"workers": []}},
                                                      {"pid": 11, "status": None}, {"pid": 12}])
        self.assertEqual([s["pid"] for s in answering], [10])
        self.assertEqual([s["pid"] for s in stale], [11, 12])
        self.assertEqual(overnight.split_answering([]), ([], []))

    def test_card_data_unchanged_is_true_false_or_unknown(self):
        self.assertTrue(overnight_legs._card_data_unchanged(5.0, "5.0"))
        self.assertIs(overnight_legs._card_data_unchanged(6.0, 5.0), False)
        self.assertIsNone(overnight_legs._card_data_unchanged(None, 5.0))
        self.assertIsNone(overnight_legs._card_data_unchanged(5.0, 0))


class LongNightPlanTests(unittest.TestCase):

    def test_a_13_hour_budget_keeps_every_item_and_fills_only_the_soak_minimum(self):
        items = [item("D1", 0, 20, soak=True, pool="server"), item("D3a-ref", 1, 18, soak=True, pool="server",
                                                                    shrink_min=0.5),
                 item("D2d-p2", 2, 21, soak=True, pool="local"), item("D2e-b", 2, 25, soak=True, pool="local"),
                 item("D2e-c", 3, 7, soak=True, pool="local"), item("D4a", 3, 15), item("D4b", 3, 20)]
        now = time.mktime((2026, 10, 3, 22, 0, 0, 0, 0, -1))
        window = min(13 * 3600, overnight.deadline_epoch("12:30", now) - now)
        self.assertEqual(window, 13 * 3600)
        filler = overnight.upfront(items, window, soak_min_s=3 * 3600, end_reserve_s=900)
        self.assertTrue(all(i["status"] == "pending" and i["scale"] == 1.0 for i in items))
        planned_soak = (20 + 18 + 21 + 25 + 7) * 60
        self.assertEqual(filler, 3 * 3600 - planned_soak)          # the soak minimum stays 3 h; no idle extra
        # P2/P3 items run before the filler in plan order, and their reserve leaves them room
        self.assertGreater(window - overnight.reserve(3, items, filler, 900), 20 * 60)


class Mg10Tests(unittest.TestCase):

    def mem(self, rows):
        return [{"unix": float(t), "service": "1", "worker": w, "state": st, "games": g, "heap_mb": h}
                for t, w, st, g, h in rows]

    def test_heap_growth_per_worker(self):
        rows = []
        for t in range(0, 3 * 3600 + 1, 300):
            rows.append((t, "A", "busy", t // 10, 1000 if t < 3600 else 1300))
            rows.append((t, "B", "busy", t // 10, 1000 if t < 3600 else 1100))
        found = overnight_report.heap_growth(self.mem(rows))
        self.assertTrue(found["judged"])
        self.assertEqual(found["over"], ["A"])
        self.assertEqual(found["workers"], 2)
        short = overnight_report.heap_growth(self.mem([(0, "A", "busy", 0, 1000), (3600, "A", "busy", 9, 1000)]))
        self.assertFalse(short["judged"])
        recycled = overnight_report.heap_growth(self.mem([(t, "A" if t < 3600 else "B", "busy", 0, 1000)
                                                          for t in range(0, 3 * 3600 + 1, 300)]))
        self.assertFalse(recycled["judged"])
        self.assertIn("recycled", recycled["why"])

    def test_heap_limit_quits_upper_bound(self):
        rows = self.mem([(0, "A", "busy", 100, 900), (0, "B", "idle", 100, 900), (0, "C", "busy", 1900, 900),
                         (300, "D", "busy", 10, 500)])
        found = overnight_report.heap_limit_quits(rows, taint_recycles=0)
        self.assertEqual(found["busy_workers_gone"], 1)        # A; B was idle (idle close), C near max games
        self.assertEqual(overnight_report.heap_limit_quits(rows, taint_recycles=3)["heap_limit_at_most"], 0)

    def test_gate_fails_on_heap_growth_and_passes_with_parts_not_judged(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            start = _epoch(D_START)
            (out / "cpu.csv").write_text("t,unix,java_ws_mb\n" + "".join(
                f"{i},{start + i},8000\n" for i in range(100)), encoding="utf-8")
            mem = ["unix,service_pid,worker_pid,state,games,heap_mb"]
            for t in range(0, 3 * 3600 + 1, 300):
                mem.append(f"{int(start + t)},1,7,busy,{t // 10},{1000 if t < 3600 else 1500}")
            (out / "mem.csv").write_text("\n".join(mem) + "\n", encoding="utf-8")
            state = {"items": {"D1": {"status": "done"}, "D0": {"started": D_START}, "D9": {}}}
            found = overnight_report.gate_mg10(out, state, {"items": []})
            self.assertEqual(found["status"], "fail")
            self.assertIn("heap grew", found["detail"])
            (out / "mem.csv").write_text(mem[0] + "\n" + mem[1] + "\n", encoding="utf-8")
            found = overnight_report.gate_mg10(out, state, {"items": []})
            self.assertEqual(found["status"], "pass")
            self.assertIn("not judged: heap growth", found["detail"])


class Mg13Tests(unittest.TestCase):

    OPP = ["o1", "o2", "o3", "o4"]

    def setup(self, out, adaptive_values):
        staging = Path(out) / "staging" / "results"
        staging.mkdir(parents=True)
        for n, (opp, wins) in enumerate(zip(self.OPP, (700, 550, 450, 300))):
            (staging / f"{n}.json").write_text(json.dumps(result(f"k{n}", "deck", opp, games(1000, wins))),
                                               encoding="utf-8")
        (staging / "v1.json").write_text(json.dumps(result("v1", "deck", "o1", games(100, 0), seeds=False)),
                                         encoding="utf-8")
        view = {"deck": {"card_sha": "deck"}, "opponents": [
            {"title": opp, "card_sha": opp, "games": 400, "rate": {"value": v, "low": v - 0.05, "high": v + 0.05}}
            for opp, v in zip(self.OPP, adaptive_values)]}
        (Path(out) / "D" / "d3a-api").mkdir(parents=True)
        (Path(out) / "D" / "d3a-api" / "result.json").write_text(json.dumps({"view": view, "wall_s": 300}),
                                                                 encoding="utf-8")
        (Path(out) / "D" / "d3c").mkdir(parents=True)
        (Path(out) / "D" / "d3c" / "result.json").write_text(json.dumps(
            {"rows": [{"pair": "AL", "mode": "assess", "games": 400, "outcome": "settled"}]}), encoding="utf-8")
        return {"items": {i: {"status": "done"} for i in ("D3c", "D3a-ref", "D3a-api")}}

    def test_spearman(self):
        self.assertAlmostEqual(overnight_report.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(overnight_report.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertIsNone(overnight_report.spearman([1, 2], [1, 2]))
        self.assertAlmostEqual(overnight_report.spearman([1, 1, 2], [1, 1, 2]), 1.0)

    def test_adaptive_against_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self.setup(tmp, (0.70, 0.56, 0.44, 0.31))
            found = overnight_report.gate_mg13(Path(tmp), state, {"items": []})
            self.assertEqual(found["status"], "pass", found["detail"])
            self.assertEqual(found["numbers"]["d3a"]["spearman"], 1.0)
            self.assertEqual(len(found["numbers"]["d3a"]["rows"]), 4)
        with tempfile.TemporaryDirectory() as tmp:
            state = self.setup(tmp, (0.70, 0.56, 0.44, 0.62))       # o4: 0.30 against 0.62
            found = overnight_report.gate_mg13(Path(tmp), state, {"items": []})
            self.assertEqual(found["status"], "fail")
            self.assertIn("o4", found["detail"])
            self.assertIn("opposite sides", found["detail"])

    def test_d3a_not_run_leaves_the_gate_not_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self.setup(tmp, (0.70, 0.56, 0.44, 0.31))
            state["items"]["D3a-api"]["status"] = "dropped"
            found = overnight_report.gate_mg13(Path(tmp), state, {"items": []})
            self.assertEqual(found["status"], "not checked")
            self.assertIn("D3a", found["detail"])
            state["items"]["D3a-api"]["status"] = "failed"
            self.assertEqual(overnight_report.gate_mg13(Path(tmp), state, {"items": []})["status"], "fail")


EXPERIMENT_TEXT = """
=== python -m decklab.lib.forge experiment x.json
# Experiment overrides-remove

800 games a pair.

| Arm | Kind | Pairs | Matchup (pooled) | Slowdown | AI timeouts arm / control | Recommendation |
|---|---|---|---|---|---|---|
| remove | override | 2 | +4.1 pts [+1.0, +7.2] | 1.10x | 0/1600 v 0/1600 | adopt |
| flash | override | 1 | +0.1 pts [-3.0, +3.2] | 1.00x | 0/800 v 0/800 | more games |

## remove: adopt
"""


class ReportSectionTests(unittest.TestCase):

    def test_section_8_parts_and_next_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            plan = {"items": [{"id": i, "priority": 0} for i in ("A1", "D1", "E1", "E2", "E3")]}
            state = {"items": {"D1": {"status": "done"}, "D2a-crn": {"status": "done"},
                               "D2c-p1": {"status": "done"}, "D4a": {"status": "done"},
                               "D4b": {"status": "skipped", "note": "no inputs"}},
                     "sessions": [{"active_s": 600, "deadline_epoch": time.time() + 3600, "exit": 0}],
                     "diagnostics": {"runs": {"c1": {"status": "done", "codes": [0]}}, "failed_gates": ["C4"],
                                     "not_run": "the experiments"}}
            (out / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (out / "plan.resolved.json").write_text(json.dumps(plan), encoding="utf-8")
            for folder, text in (("D/d2c-p1", EXPERIMENT_TEXT), ("D/d2a-crn", json.dumps(
                    {"verdict": "not_settled", "opponents": [{"title": "Izzet", "games": 800, "paired": {
                        "delta": 0.01, "low": -0.02, "high": 0.04, "rho": 0.8, "same": 0.6, "saved_share": 0.4,
                        "unpaired": {"low": -0.05, "high": 0.07}}}]}) + "\n")):
                (out / folder).mkdir(parents=True)
                (out / folder / "out.txt").write_text(text, encoding="utf-8")
            (out / "E" / "e3").mkdir(parents=True)
            (out / "E" / "e3" / "result.json").write_text(json.dumps(
                {"games": 26000, "ai_timeout_games": 8, "ai_timeouts_per_1000": 0.308, "recycled": {"clock": 2},
                 "card_data_unchanged": False, "early_numbers": "checked"}), encoding="utf-8")
            (out / "D" / "m6").mkdir(parents=True)
            (out / "D" / "m6" / "result.json").write_text(json.dumps({"pods": 200, "minutes_per_pod": 1.5}),
                                                          encoding="utf-8")
            found = overnight_report.write(out)
            text = (out / "REPORT.md").read_text(encoding="utf-8")
        for heading in ("## Soak (section 7)", "## Fail-fast diagnostics", "## Replay (D1, E1, E2)",
                        "## M4 pairing (D2a)", "## Experiments (D2b-D2e)", "## Offline checks (E3)",
                        "## Optional: M6 and M7", "## Cleanup", "## Next steps"):
            self.assertIn(heading, text)
        self.assertLess(text.index("## Gate numbers"), text.index("## Next steps"))
        self.assertIn("card data unchanged since A1: False", text)
        self.assertIn("AI-timeout games 8 (0.308 per 1,000)", text)
        self.assertIn("| 1 | Izzet | 800 | 0.01 (-0.02 to 0.04) |", text)
        self.assertIn("Adoption candidates: remove (overrides-remove).", text)
        self.assertIn("minutes_per_pod 1.5", text)
        self.assertEqual(found["experiments"]["adopt"][0]["arm"], "remove")
        steps = " ".join(found["next_steps"])
        self.assertIn("Adoption to consider: remove", steps)
        self.assertIn("More games asked for: flash", steps)
        self.assertIn("Don't move", steps)

    def test_a_broken_section_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "state.json").write_text(json.dumps({"items": {}, "sessions": []}), encoding="utf-8")
            with mock.patch.object(overnight_report, "m4_section", side_effect=RuntimeError("boom")):
                found = overnight_report.write(out)
        self.assertEqual(found["m4"], {"error": "RuntimeError: boom"})


def _controller(out, plan_items, deadline_s=3600.0, fake_seconds=1):
    plan = {"items": plan_items, "smoke": False, "fake": True, "fake_seconds": fake_seconds, "main": str(overnight.TREE),
            "end_reserve_s": 60.0, "soak_min_s": 0}
    state = {"run_id": "t", "identity": {"fake": True}, "server_was_running": None, "test_servers": {},
             "sessions": [{"started": "x", "deadline_epoch": time.time() + deadline_s, "budget_s": deadline_s,
                           "active_s": 0.0, "paused_s": 0.0, "soak_s": 0.0, "soak_server_s": 0.0,
                           "needs_upfront": False, "restarts": 0}],
             "own_pids": [], "items": {}, "dropped": [], "smoke": False, "drill": None}
    (Path(out) / "plan.resolved.json").write_text(json.dumps(plan), encoding="utf-8")
    overnight.save_state(out, state)


@unittest.skipUnless(sys.platform == "win32", "Windows jobs")
class ControllerEndTests(unittest.TestCase):

    def test_diagnostics_rerun_the_checks_within_the_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            _controller(tmp, [item("E4", 0, 1, block="E", internal="cleanup")])
            ctrl = overnight.Controller(tmp, SimpleNamespace(fake=True))
            ctrl.item_state("C4")["gate_failed"] = True
            with mock.patch("sys.stdout"):
                ctrl._diagnostics()
            diag = overnight.load_state(tmp)["diagnostics"]
            self.assertEqual(diag["failed_gates"], ["C4"])
            self.assertEqual({k: v["status"] for k, v in diag["runs"].items()},
                             {"c1": "done", "c2": "done", "c3": "done"})
            self.assertFalse(any(k.startswith("C-diag") for k in overnight.load_state(tmp)["items"]))
        with tempfile.TemporaryDirectory() as tmp:
            _controller(tmp, [item("E4", 0, 1, block="E", internal="cleanup")], deadline_s=90)
            ctrl = overnight.Controller(tmp, SimpleNamespace(fake=True))
            with mock.patch("sys.stdout"):
                ctrl._diagnostics()                 # 90 s less E's reserve and estimate: nothing fits
            diag = overnight.load_state(tmp)["diagnostics"]
            self.assertEqual({v["status"] for v in diag["runs"].values()}, {"dropped"})

    def test_end_only_runs_d9_e4_e5_and_rewrites_the_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            _controller(tmp, [item("D1", 0, 1, cmds=[["{F}", "x"]]), item("D9", 0, 1, internal="server-stop"),
                              item("E4", 0, 1, block="E", internal="cleanup"),
                              item("E5", 0, 1, block="E", internal="report")])
            done = subprocess.run([sys.executable, str(HERE / "overnight.py"), "run", "--out", tmp,
                                   "--continue-session", "--end-only", "--fake"], capture_output=True, text=True,
                                  timeout=120)
            state = overnight.load_state(tmp)
            report = json.loads((Path(tmp) / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(state["items"].get("D1", {}).get("status", "pending"), "pending")
        self.assertEqual([state["items"][i]["status"] for i in ("D9", "E4", "E5")], ["done"] * 3)
        self.assertTrue(state["sessions"][-1]["gave_up"])
        self.assertEqual(report["items"]["E5"]["status"], "done")       # written again after E5 ended
        self.assertIsNotNone(state["clean"])


class SupervisorGiveUpTests(unittest.TestCase):

    def test_after_the_last_restart_the_end_still_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "plan.resolved.json").write_text(json.dumps({"items": [], "smoke": False}), encoding="utf-8")
            args = SimpleNamespace(out=tmp, main=None, resume=False, fake=True, smoke=False, only=None,
                                   deadline=None, budget_h=1.0)
            crashed = mock.Mock()
            crashed.wait.return_value = 99
            ran = []

            def fake_run(argv, **kw):
                ran.append(argv)
                state = overnight.load_state(out)
                state["items"]["E4"] = {"status": "done"}
                overnight.save_state(out, state)
                return SimpleNamespace(returncode=0)
            with mock.patch.object(overnight.subprocess, "Popen", return_value=crashed) as popen, \
                    mock.patch.object(overnight.subprocess, "run", side_effect=fake_run), \
                    mock.patch.object(overnight, "resolve", side_effect=lambda *a, **k: {"items": [], "smoke": False}), \
                    mock.patch("sys.stdout"):
                self.assertEqual(overnight.supervise(args), 0)
            self.assertEqual(popen.call_count, overnight.MAX_RESTARTS + 1)
            self.assertEqual(len(ran), 1)
            self.assertIn("--end-only", ran[0])
            self.assertTrue((out / "REPORT.md").exists())
            self.assertIn("gave up", (out / "log.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
