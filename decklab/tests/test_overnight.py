"""Tests for the combined run's harness (wave 3's package H: forge-trial/overnight*.py, and the
soak-probe command; forge-trial/sim-combined-run.md): what's built, plan resolution and estimates,
priorities, the up-front decision and the reserve, the soak minimum and filler, checkpoint and
resume with identity checks, the monitor's questions, cleanup touching only run-owned processes,
the report's PASS / FAIL / INCOMPLETE logic, and a --fake end-to-end run (the supervisor, the drill's
self-kill and resume, and an item that ignores STOP ended by its job).

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import gzip
import json
import os
import random
import subprocess
import sys
import tempfile
import types
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "forge-trial"
sys.path.insert(0, str(HERE))

import overnight                 # noqa: E402
import overnight_legs            # noqa: E402
import overnight_monitor         # noqa: E402
import overnight_report          # noqa: E402

from decklab.lib.forge import cli  # noqa: E402

STUBS = {
    "seqstats": "def look(games, p):\n    raise _todo('look')\ndef paired_diff(a, b, c, d):\n    raise _todo('x')\n"
                "def field_row(g, p):\n    raise _todo('x')\n",
    "cli": "def _cmd_field(args):\n    return _not_built('field', 'F')\n"
           "def _cmd_variant(args):\n    '''Doc.'''\n    return _not_built('variant', 'V')\n"
           "def _cmd_experiment(args):\n    return 1\n"
           "def _log_args(parser):\n    '''Doc.'''\n    return parser\n"
           "def _cmd_pilots(args):\n    return _not_built('pilots', 'E3')\n"
           "def _cmd_overrides(args):\n    return 0\n"
           "def _cmd_staged_move(args):\n    return 0\ndef _cmd_soak_probe(args):\n    return 0\n",
    "runner": "RUN_FEATURES = frozenset()\n",
    "simjar": "PILOT_SWITCHES = {'team-pump-1': 'x'}\n",
    "overrides": "def user_dir_for(sets):\n    return 1\n",
    "adaptive": "def run_adaptive(a):\n    raise NotImplementedError('A')\n",
    "field": "def run_field(a):\n    raise _todo('x')\ndef view(e):\n    raise _todo('x')\n",
    "variants": "def run_test(a):\n    return a\ndef aligned_dck(a, b):\n    return a\n",
    "experiment": "def run(s):\n    return s\ndef plan(s):\n    return s\n",
}


def fake_tree(folder, modules=STUBS):
    base = Path(folder) / "decklab" / "lib" / "forge"
    base.mkdir(parents=True)
    for name, text in modules.items():
        (base / f"{name}.py").write_text(text, encoding="utf-8")
    return Path(folder)


def item(id_, priority=1, est_min=10, block="D", **kw):
    return dict({"id": id_, "block": block, "priority": priority, "est_s": est_min * 60.0, "status": "pending",
                 "requires": []}, **kw)


class FeatureTests(unittest.TestCase):

    def test_stubs_and_built_code_told_from_the_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = overnight.features(fake_tree(tmp))
        self.assertFalse(found["S"]["built"])
        self.assertFalse(found["F"]["built"])
        self.assertIn("cli._cmd_field is a stub", found["F"]["why"])
        self.assertFalse(found["V"]["built"])                    # its CLI command still says "isn't built yet"
        self.assertTrue(found["X"]["built"])
        self.assertFalse(found["A"]["built"])
        self.assertFalse(found["R"]["built"])                    # _log_args returns its parser; no RUN_FEATURES
        self.assertTrue(found["J3"]["built"])
        self.assertFalse(found["E3"]["built"])
        self.assertTrue(found["H"]["built"])

    def test_r_built_when_run_features_are_filled(self):
        modules = dict(STUBS, runner="RUN_FEATURES = frozenset(('numbers', 'seeds', 'key', 'kind', 'extra', "
                                     "'override_sets', 'log_dir'))\n",
                       cli=STUBS["cli"].replace("    '''Doc.'''\n    return parser\n",
                                                "    parser.add_argument('--logs-dir')\n    return parser\n"))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(overnight.features(fake_tree(tmp, modules))["R"]["built"])

    def test_this_tree_has_h(self):
        self.assertTrue(overnight.features()["H"]["built"])
        self.assertIn("rounds", overnight.leg_names())
        self.assertIn("m6", overnight.leg_names())


class PlanTests(unittest.TestCase):

    def plan(self):
        return {"soak_min_h": 3.0, "end_reserve_min": 15, "items": [
            {"id": "A1", "block": "A", "priority": 0, "est_min": 3, "internal": "preflight"},
            {"id": "C4", "block": "C", "priority": 0, "est_min": 1, "leg": "deck-order", "requires": ["V"],
             "cmds": [["{L}", "deck-order"]]},
            {"id": "D1", "block": "D", "priority": 0, "est_min": 45, "requires": ["R"], "soak": True, "pool": "server",
             "cmds": [["{F}", "replay", "--games", "{games:800}", "{workers}"]]},
            {"id": "D4a", "block": "D", "priority": 3, "est_min": 15, "leg": "m6", "smoke": False, "cmds": [["{L}"]]},
            {"id": "D2a-m4", "block": "D", "priority": 1, "est_min": 10, "specs": ["exp-a.json", "exp-b.json"],
             "spec_cmd": ["{F}", "experiment", "{SPEC}", "--logs-dir", "{OUT}/logs/{NAME}"]},
            {"id": "X1", "block": "D", "priority": 1, "est_min": 5, "inputs": ["variants.json"], "cmds": [["{F}"]]},
        ]}

    def test_resolve_skips_not_built_and_missing_inputs(self):
        built = {p: {"built": p not in ("V",)} for p in overnight.PACKAGES}
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "inputs").mkdir()
            (Path(tmp) / "inputs" / "exp-b.json").write_text("{}", encoding="utf-8")
            found = overnight.resolve(self.plan(), tmp, main="M", built=built, legs={"deck-order"})
        items = {i["id"]: i for i in found["items"]}
        self.assertEqual(items["C4"]["status"], "skipped")
        self.assertEqual(items["C4"]["why"], "not built tonight (package V)")
        self.assertEqual(items["C4"]["not_built"], ["V"])
        self.assertEqual(items["D4a"]["why"], "not built tonight (harness leg m6)")
        self.assertEqual(items["D1"]["status"], "pending")
        self.assertEqual(items["X1"]["why"], "no inputs (variants.json)")
        self.assertEqual(len(items["D2a-m4"]["cmds"]), 1)                       # only the spec that exists
        self.assertIn("exp-b", items["D2a-m4"]["cmds"][0][-1])
        self.assertEqual(items["D2a-m4"]["est_s"], 300.0)                       # half its specs, half its time
        self.assertEqual(found["soak_min_s"], 3 * 3600)

    def test_smoke_sizes_and_items(self):
        built = {p: {"built": True} for p in overnight.PACKAGES}
        found = overnight.resolve(self.plan(), "OUT", main="M", built=built, legs={"deck-order", "m6"}, smoke=True)
        items = {i["id"]: i for i in found["items"]}
        self.assertEqual(items["D4a"]["why"], "not in --smoke")
        self.assertEqual(found["soak_min_s"], 600)
        argv, _ = overnight.expand(items["D1"]["cmds"][0], {"OUT": "o", "MAIN": "m", "smoke": True})
        self.assertEqual(argv[-4:], ["--games", "10", "--workers", "4"])
        argv, _ = overnight.expand(items["D1"]["cmds"][0], {"OUT": "o", "MAIN": "m", "smoke": False}, scale=0.5)
        self.assertEqual(argv[-2:], ["--games", "400"])

    def test_smoke_only_arguments(self):
        cmd = ["{L}", "adaptive", "--pairs", "{smoke:IG|AL,IG,ZL}", "{smoke:|--until ahead}"]
        self.assertEqual(overnight.expand(cmd, {"OUT": "o", "MAIN": "m", "smoke": True})[0][-2:], ["--pairs", "IG"])
        self.assertEqual(overnight.expand(cmd, {"OUT": "o", "MAIN": "m"})[0][-4:],
                         ["--pairs", "AL,IG,ZL", "--until", "ahead"])

    def test_wave_1_play_takes_only_its_game_choices(self):
        cmd = ["{FM}", "play", "--games", "{choice:800}"]
        self.assertEqual(overnight.expand(cmd, {"OUT": "o", "MAIN": "m"})[0][-1], "800")
        self.assertEqual(overnight.expand(cmd, {"OUT": "o", "MAIN": "m"}, scale=0.6)[0][-1], "400")
        self.assertEqual(overnight.expand(cmd, {"OUT": "o", "MAIN": "m", "smoke": True})[0][-1], "200")

    def test_main_commands_run_from_the_main_checkout(self):
        argv, cwd = overnight.expand(["{FM}", "play", "--results-dir", "{OUT}/B"], {"OUT": "o", "MAIN": "C:/main"})
        self.assertEqual(cwd, "C:/main")
        self.assertEqual(argv[1:], ["-m", "decklab.lib.forge", "play", "--results-dir", "o/B"])


class BudgetTests(unittest.TestCase):

    def test_upfront_drops_p3_then_p2_and_shrinks_p1_before_dropping(self):
        items = [item("P0", 0, 60, soak=True, pool="server"), item("a", 1, 60, shrink_min=0.5),
                 item("b", 1, 60, shrink_min=0.5), item("c", 2, 30), item("d", 3, 30)]
        filler = overnight.upfront(items, 3 * 3600, soak_min_s=3600, end_reserve_s=900)
        status = {i["id"]: (i["status"], i.get("scale")) for i in items}
        self.assertEqual(status["d"][0], "dropped")
        self.assertEqual(status["c"][0], "dropped")
        self.assertEqual(status["a"], ("pending", 0.5))
        self.assertEqual(status["b"], ("pending", 0.5))
        self.assertEqual(filler, 0.0)

    def test_upfront_counts_the_filler_the_soak_minimum_needs(self):
        items = [item("P0", 0, 60, soak=True, pool="server"), item("x", 1, 60)]
        filler = overnight.upfront(items, 10 * 3600, soak_min_s=3 * 3600, end_reserve_s=900)
        self.assertEqual(filler, 2 * 3600)
        items = [item("P0", 0, 60, soak=True, pool="server"), item("x", 1, 60)]
        overnight.upfront(items, 3.2 * 3600, soak_min_s=3 * 3600, end_reserve_s=900)
        self.assertEqual(items[1]["status"], "dropped")       # P1 makes way for the P0 filler

    def test_soak_owed_needs_half_on_the_server(self):
        self.assertEqual(overnight.soak_owed(3600, 3600, 0), 1800)
        self.assertEqual(overnight.soak_owed(3600, 1000, 1000), 2600)
        self.assertEqual(overnight.soak_owed(3600, 4000, 2000), 0)

    def test_reserve_counts_only_higher_priorities(self):
        items = [item("p0", 0, 10), item("p1", 1, 10, shrink_min=0.5), item("p2", 2, 10)]
        self.assertEqual(overnight.reserve(2, items, 0, 0), 600 + 300)
        self.assertEqual(overnight.reserve(1, items, 100, 900), 900 + 100 + 600)
        self.assertEqual(overnight.reserve(0, items, 0, 0), 0)

    def test_fit(self):
        self.assertEqual(overnight.fit(item("x", 0, 100), 0), ("run", 1.0))
        self.assertEqual(overnight.fit(item("x", 1, 10), 700), ("run", 1.0))
        self.assertEqual(overnight.fit(item("x", 1, 10, shrink_min=0.5), 400), ("run", 400 / 600))
        decision, why = overnight.fit(item("x", 2, 10), 100)
        self.assertEqual(decision, "dropped")
        self.assertIn("P2", why)

    def test_deadline_is_the_next_such_local_time(self):
        now = time.mktime((2026, 10, 3, 22, 0, 0, 0, 0, -1))
        stamp = overnight.deadline_epoch("07:00", now)
        self.assertEqual(time.localtime(stamp)[:5], (2026, 10, 4, 7, 0))
        self.assertEqual(time.localtime(overnight.deadline_epoch("23:30", now))[:5], (2026, 10, 3, 23, 30))


class StateTests(unittest.TestCase):

    def test_atomic_state_and_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            overnight.save_state(tmp, {"a": 1})
            self.assertEqual(overnight.load_state(tmp), {"a": 1})
            self.assertFalse((Path(tmp) / "state.tmp").exists())
        self.assertEqual(overnight.identity_differs({"commit": "a", "x": 1}, {"commit": "b", "x": 1}), ["commit"])
        # the deck lists vouch for nothing when either session couldn't read them; other keys'
        # "error: ..." values compare like any other
        unread = {"deck_lists": "error: OperationalError", "forge_build": "error: OSError"}
        self.assertEqual(overnight.identity_differs(unread, dict(unread)), ["deck_lists"])
        self.assertEqual(overnight.identity_differs({"deck_lists": "ab"}, {"deck_lists": "ab"}), [])

    def test_identity_records_forge_and_the_card_log_jar(self):
        from decklab.lib.forge import install, simjar
        setup = {"forge_dir": "C:/forge", "jar": "forge.jar", "version": "2.0.15", "java": "java"}
        with mock.patch.object(install, "_setup", return_value=setup), \
                mock.patch.object(simjar, "forge_build", return_value="2.0.15-SNAPSHOT-09.28"), \
                mock.patch.object(simjar, "_tool", return_value="javac"), \
                mock.patch.object(simjar, "source_sha256", return_value="s" * 64), \
                mock.patch.object(simjar, "forge_patches", return_value={}), \
                mock.patch.object(Path, "stat", return_value=mock.Mock(st_size=10, st_mtime_ns=20)):
            found = overnight._forge_identity()
            with mock.patch.object(Path, "stat", return_value=mock.Mock(st_size=10, st_mtime_ns=21)):
                rebuilt = overnight._forge_identity()
        self.assertEqual((found["forge_version"], found["forge_build"]), ("2.0.15", "2.0.15-SNAPSHOT-09.28"))
        self.assertTrue(found["jar_stamp"].startswith("decklab-sim-2.0.15-"))
        self.assertEqual(overnight.identity_differs(found, rebuilt), ["jar_stamp"])
        with mock.patch.object(install, "_setup", side_effect=OSError):
            self.assertEqual(overnight._forge_identity()["forge_build"], "error: OSError")

    def test_resume_refuses_another_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            overnight.save_state(tmp, {"identity": {"commit": "not this one"}, "sessions": [], "items": {}})
            args = mock.Mock(out=tmp, main=str(overnight.TREE), resume=True, fake=False, smoke=False, only=None,
                             deadline=None, budget_h=1.0)
            with mock.patch("sys.stderr"):
                self.assertEqual(overnight.supervise(args), overnight.EXIT_REFUSED)

    def test_no_idle_gate_starts_at_once(self):
        fake = types.SimpleNamespace(smoke=False, state={"no_idle_gate": True})
        with mock.patch.object(overnight.time, "sleep", side_effect=AssertionError("waited for idle")):
            got = overnight.Controller._internal_idle_gate(fake, {"id": "A2"}, Path("."))
        self.assertEqual(got["status"], "done")
        self.assertIn("no idle gate", got["note"])

    def test_b_anchors_run_again_in_a_new_session(self):
        state = {"items": {"B0": {"status": "done"}, "B1a": {"status": "done"}, "B2": {"status": "done"},
                           "B3": {"status": "running"}, "B1b": {"status": "pending"}}}
        self.assertTrue(overnight.rerun_b_anchors(state))
        self.assertEqual([state["items"][k]["status"] for k in ("B0", "B1a", "B2", "B1b")], ["pending"] * 4)
        done = {"items": {k: {"status": "done"} for k in ("B0", "B1a", "B2", "B1b")}}
        self.assertFalse(overnight.rerun_b_anchors(done))


class MonitorTests(unittest.TestCase):

    def monitor(self, rows):
        m = overnight_monitor.Monitor("unused.csv")
        m.t0 = time.monotonic() - rows[-1]["t"]
        for row in rows:
            m.add(row)
        return m

    def rows(self, n, idle_from=10000, other=0.0, system=0.0, java=1):
        return [{"t": float(t), "unix": 0, "own_pct": 50, "system_pct": system, "other_pct": other, "total_pct": 50,
                 "idle_s": idle_from + t, "java_n": java, "java_ws_mb": 1000} for t in range(n)]

    def test_classes(self):
        self.assertEqual(overnight_monitor.classify("java.exe", True), "own")
        self.assertEqual(overnight_monitor.classify("msmpeng.exe", False), "system")
        self.assertEqual(overnight_monitor.classify("chrome.exe", False), "other")

    def test_idle_gate_and_pause(self):
        m = self.monitor(self.rows(700))
        self.assertTrue(m.free_for(600, other_max=5.0, other_window=60))
        self.assertFalse(m.in_use())
        busy = self.monitor(self.rows(700, idle_from=0, other=20))
        self.assertTrue(busy.in_use())
        self.assertFalse(busy.free_for(300))
        hog = self.monitor(self.rows(400, other=40))
        self.assertTrue(hog.in_use_for(300, other_over=30))
        self.assertTrue(hog.in_use())

    def test_noisy_legs(self):
        self.assertFalse(overnight_monitor.noisy_rows(self.rows(100), 0))
        self.assertTrue(overnight_monitor.noisy_rows(self.rows(100, other=4), 0))
        spike = self.rows(100)
        for r in spike[10:45]:
            r["other_pct"] = 12
        self.assertTrue(overnight_monitor.noisy_rows(spike, 0))
        touched = self.rows(100)
        touched[50]["idle_s"] = 1          # input 1 s before t=50, during the leg
        self.assertTrue(overnight_monitor.noisy_rows(touched, 0))

    def test_busy_share(self):
        rows = self.rows(10) + [dict(r, t=r["t"] + 10, java_n=0) for r in self.rows(10)]
        m = self.monitor(rows)
        self.assertAlmostEqual(m.busy_share(m.t0), 0.5)


class FailFastTests(unittest.TestCase):

    def test_a_failed_engine_check_skips_d(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "C" / "c1").mkdir(parents=True)
            (out / "C" / "c1" / "result.json").write_text(json.dumps(
                {"formats": {"Constructed": {"kind": "failed"}}}), encoding="utf-8")
            ctrl = overnight.Controller.__new__(overnight.Controller)
            ctrl.out, ctrl.plan = out, {"items": []}
            ctrl.state = {"items": {"C1": {"status": "done"}}, "sessions": [{}]}
            ctrl.save = lambda: None
            with mock.patch("sys.stdout"):
                ctrl._c_gate({"id": "C1", "block": "C"})
            self.assertTrue(ctrl._failfast())
            self.assertEqual(ctrl.state["items"]["C1"]["gate"]["status"], "fail")
            (out / "C" / "c1" / "result.json").write_text(json.dumps(
                {"formats": {"Constructed": {"kind": "same"}}}), encoding="utf-8")
            ctrl.state = {"items": {"C1": {"status": "done"}}, "sessions": [{}]}
            ctrl._c_gate({"id": "C1", "block": "C"})
            self.assertFalse(ctrl._failfast())


@unittest.skipUnless(sys.platform == "win32", "Windows jobs")
class CleanupTests(unittest.TestCase):

    def test_clean_ends_only_recorded_run_processes(self):
        mine = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            time.sleep(0.3)
            with tempfile.TemporaryDirectory() as tmp:
                overnight.save_state(tmp, {"own_pids": [[mine.pid, overnight.creation_time(mine.pid)],
                                                        [other.pid, 12345]]})       # a reused pid: another process
                ended = overnight.clean(tmp)
            self.assertEqual(ended, [mine.pid])
            mine.wait(10)
            self.assertIsNone(other.poll())
        finally:
            for p in (mine, other):
                if p.poll() is None:
                    p.kill()
                p.wait(10)

    def test_item_job_leftovers(self):
        job = overnight.Job()
        with tempfile.TemporaryDirectory() as tmp:
            proc = overnight.start_child([sys.executable, "-c",
                                          "import subprocess, sys; subprocess.Popen([sys.executable, '-c', "
                                          "'import time; time.sleep(60)'])"], tmp, dict(os.environ),
                                         Path(tmp) / "out.txt", job)
            proc.wait(30)
            found = overnight.job_leftovers(job, wait_s=1)
            self.assertEqual([f["exe"] for f in found], ["python.exe"])
            job.terminate()
            time.sleep(0.5)
            self.assertEqual(overnight.job_leftovers(job, wait_s=0), [])
            job.close()


class ReportTests(unittest.TestCase):

    def gates(self, **status):
        found = {name: {"status": overnight_report.PASS, "detail": "", "numbers": {}} for name, _, _ in
                 overnight_report.GATES}
        for name, value in status.items():
            found[name]["status"] = value
        return found

    def state_plan(self, statuses=None):
        plan = {"items": [{"id": "A1", "priority": 0}, {"id": "D1", "priority": 0}, {"id": "D3c", "priority": 1}]}
        state = {"items": {k: {"status": v} for k, v in (statuses or {"A1": "done", "D1": "done"}).items()}}
        return state, plan

    def test_verdicts(self):
        state, plan = self.state_plan()
        self.assertEqual(overnight_report.verdict(self.gates(), state, plan)[0], "PASS")
        self.assertEqual(overnight_report.verdict(self.gates(MG4="fail"), state, plan)[0], "FAIL")
        self.assertEqual(overnight_report.verdict(self.gates(MG5="not built tonight"), state, plan)[0], "INCOMPLETE")
        self.assertEqual(overnight_report.verdict(self.gates(MG11="not checked"), state, plan)[0], "INCOMPLETE")
        # gates that need only P1 items don't hold up a PASS
        self.assertEqual(overnight_report.verdict(self.gates(MG13="not built tonight", MG16="not checked"), state,
                                                  plan)[0], "PASS")
        # a failed gate wins over anything missing
        self.assertEqual(overnight_report.verdict(self.gates(MG2="fail", MG5="not built tonight"), state, plan)[0],
                         "FAIL")
        state, plan = self.state_plan({"A1": "done", "D1": "skipped"})
        outcome, why = overnight_report.verdict(self.gates(), state, plan)
        self.assertEqual(outcome, "INCOMPLETE")
        self.assertIn("D1", why)

    def test_not_built_items_make_gates_not_built_never_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            plan = {"items": [{"id": "C4", "priority": 0, "not_built": ["V"], "why": "not built tonight (package V)"},
                              {"id": "D3c", "priority": 1, "not_built": ["A"], "why": "not built tonight (package A)"}]}
            state = {"items": {"C4": {"status": "skipped"}, "D3c": {"status": "skipped"}}}
            (out / "plan.resolved.json").write_text(json.dumps(plan), encoding="utf-8")
            (out / "state.json").write_text(json.dumps(state), encoding="utf-8")
            found = overnight_report.build(out)
        self.assertEqual(found["gates"]["MG5"]["status"], "not built tonight")
        self.assertEqual(found["gates"]["MG13"]["status"], "not built tonight")
        self.assertEqual(found["verdict"], "INCOMPLETE")
        self.assertEqual(found["not_built"], ["A", "V"])

    def test_gates_on_synthetic_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "C" / "c1").mkdir(parents=True)
            (out / "C" / "c1" / "result.json").write_text(json.dumps(
                {"formats": {"Constructed": {"kind": "unsure"}, "Commander": {"kind": "same"}}}), encoding="utf-8")
            state = {"items": {"C1": {"status": "done"}},
                     "clean": {"own_java": [], "own_slots": [], "test_servers": {}, "leftovers": []},
                     "drift": [{"folder": f"drift-{i}", "code": 0, "noisy": False, "at_s": i * 2400, "session": 1}
                               for i in range(4)]}
            for i, ms in enumerate((100, 104, 103, 109)):
                (out / "probes" / f"drift-{i}").mkdir(parents=True)
                (out / "probes" / f"drift-{i}" / "result.json").write_text(json.dumps({"median_ms": ms}))
            state["items"]["D1"] = {"status": "done"}
            plan = {"items": []}
            self.assertEqual(overnight_report.gate_mg2(out, state, plan)["status"], "pass")
            self.assertEqual(overnight_report.gate_mg12(out, state, plan)["status"], "pass")
            self.assertEqual(overnight_report.gate_mg11(out, state, plan)["status"], "pass")
            (out / "probes" / "drift-3" / "result.json").write_text(json.dumps({"median_ms": 120}))
            self.assertEqual(overnight_report.gate_mg11(out, state, plan)["status"], "fail")
            state["clean"]["own_java"] = [123]
            self.assertEqual(overnight_report.gate_mg12(out, state, plan)["status"], "fail")

    def test_mg11_leaves_out_cold_probes(self):
        # The 2026-10-03 run: probes 1-3 timed workers the pool had just started (twice the warm time).
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            state = {"items": {"D1": {"status": "done"}},
                     "drift": [{"folder": f"drift-{i}", "code": 0, "noisy": False, "at_s": i * 2400, "session": 1}
                               for i in range(7)]}
            for i, (ms, cold) in enumerate(((346, False), (687, True), (736, True), (728, True), (337, False),
                                            (350, False), (341, False))):
                (out / "probes" / f"drift-{i}").mkdir(parents=True)
                (out / "probes" / f"drift-{i}" / "result.json").write_text(json.dumps({"median_ms": ms, "cold": cold}))
            self.assertEqual(overnight_report.gate_mg11(out, state, {"items": []})["status"], "pass")
            for i in (1, 2, 3):
                (out / "probes" / f"drift-{i}" / "result.json").write_text(json.dumps({"median_ms": 700}))
            self.assertEqual(overnight_report.gate_mg11(out, state, {"items": []})["status"], "fail")

    def mg8_out(self, tmp, results):
        out = Path(tmp)
        for folder in ("e1", "e2"):
            (out / "E" / folder).mkdir(parents=True)
            (out / "E" / folder / "out.txt").write_text(json.dumps({"planned": [], "stale": []}), encoding="utf-8")
        staging = out / "staging" / "results"
        staging.mkdir(parents=True)
        for result in results:
            (staging / f"{result['key']}.json").write_text(json.dumps(result), encoding="utf-8")
        state = {"items": {"D1": {"status": "done"}, "E1": {"status": "done", "codes": [0]},
                           "E2": {"status": "done", "codes": [0]}}}
        return out, state, {"items": []}

    @staticmethod
    def mg8_result(key, played, failed_games):
        games = [{"g": g, "w": g % 2, "first": g % 2} for g in range(played)]
        failed = [{"first": 10000 + i * 25, "games": 25, "error": "x"} for i in range(failed_games // 25)]
        return {"key": key, "seeds": {}, "sides": [{}, {}], "batches": [{"games": games}], "failed": failed,
                "runs": [{"error": None}]}

    def test_mg8_failed_chunks_count_their_games(self):
        checks = mock.patch.object(overnight_report, "_staged_checks", return_value=[])
        with tempfile.TemporaryDirectory() as tmp, checks:
            # 25 failed of 10,025 overall (0.25 %), 25 of 1,025 in one matchup (2.4 %): the matchup rule fails
            results = [self.mg8_result(f"{i:064x}", 1000, 0) for i in range(9)] + [self.mg8_result("f" * 64, 1000, 25)]
            found = overnight_report.gate_mg8(*self.mg8_out(tmp, results))
            self.assertEqual(found["status"], "fail")
            self.assertIn("over 2 %", found["detail"])
            self.assertNotIn("over 0.5 %", found["detail"])
            self.assertEqual(found["numbers"]["failed_games"], 25)
        with tempfile.TemporaryDirectory() as tmp, checks:
            # 25 failed of 2,525 in each of two matchups (about 1 %): over 0.5 % overall, under 2 % each
            results = [self.mg8_result("a" * 64, 2500, 25), self.mg8_result("b" * 64, 2500, 25)]
            found = overnight_report.gate_mg8(*self.mg8_out(tmp, results))
            self.assertEqual(found["status"], "fail")
            self.assertIn("over 0.5 %", found["detail"])
            self.assertNotIn("over 2 %", found["detail"])
        with tempfile.TemporaryDirectory() as tmp, checks:
            results = [self.mg8_result(f"{i:064x}", 2500, 0) for i in range(4)] + [self.mg8_result("f" * 64, 2500, 25)]
            self.assertEqual(overnight_report.gate_mg8(*self.mg8_out(tmp, results))["status"], "pass")
            results[0]["runs"][0]["error"] = "Forge stopped"
            self.assertIn("ended with an error", overnight_report.gate_mg8(*self.mg8_out(f"{tmp}/again", results))["detail"])

    def test_mg8_checks_the_staged_files_or_says_it_didnt(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = self.mg8_result("a" * 64, 10, 0)
            found = overnight_report.gate_mg8(*self.mg8_out(tmp, [bad]))
            self.assertEqual(found["status"], "fail")
            self.assertIn("isn't a saved result", found["detail"])
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(overnight_report, "_staged_checks", return_value=None):
            found = overnight_report.gate_mg8(*self.mg8_out(tmp, [bad]))
            self.assertEqual(found["status"], "pass")
            self.assertIn("not judged: _is_result and views.view", found["detail"])

    def test_mg6_excuses_clock_stops_and_ai_timeouts_only(self):
        def leg(outcomes, rnd):
            return {"round": rnd, "workload": "IG", "outcomes": outcomes}

        ref = [[g, g % 2, g % 2, 10, "win", 0, 12] for g in range(400)]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            state, plan = {"items": {"B2": {"status": "done"}}}, {"items": []}

            def judge(other):
                (out / "B" / "b2").mkdir(parents=True, exist_ok=True)
                (out / "B" / "b2" / "result.json").write_text(json.dumps({"rows": [leg(ref, 1), leg(other, 2)]}))
                return overnight_report.gate_mg6(out, state, plan)

            self.assertEqual(judge([list(o) for o in ref])["status"], "pass")
            other = [list(o) for o in ref]
            other[3] = [3, 0, 1, 11, "win", 2, 13]          # an AI timeout: excused
            other[5] = [5, None, 1, 30, "timeout", 0, 30]    # a clock stop: excused
            self.assertEqual(judge(other)["status"], "pass")
            other[7] = [7, 0, 1, 10, "win", 0, 12]           # neither: the replay rule isn't built
            found = judge(other)
            self.assertEqual(found["status"], "not checked")
            self.assertEqual(found["numbers"]["unexplained"], 1)
            for g in (9, 11):
                other[g] = [g, 0, 0, 99, "win", 0, 99]
            self.assertEqual(judge(other)["status"], "fail")    # 395 of 400 identical: under 99.5 %
            other = [list(o) for o in ref]
            other[2][5] = 3                                  # the same game with an AI timeout counted is the same
            self.assertEqual(judge(other)["numbers"]["identical_share"], 1.0)

    def test_statistics(self):
        self.assertAlmostEqual(overnight_report._norm_ppf(0.975), 1.959964, places=4)
        self.assertEqual(overnight_report.rate_ratio_low(0, 1000, 0, 1000, 0.95), 0.0)
        self.assertLess(overnight_report.rate_ratio_low(3, 1000, 3, 1000, 0.95), 1.0)
        self.assertGreater(overnight_report.rate_ratio_low(1, 10000, 30, 10000, 0.95), 3.0)
        games = [{"first": i % 2, "w": 0 if i % 4 < 3 else 1} for i in range(400)]
        found = overnight_report.balanced(games, 0)
        self.assertAlmostEqual(found["value"], 0.75)
        self.assertLess(found["low"], 0.75)


class FinalCheckFixTests(unittest.TestCase):
    """The fixes from the final checks: names on two printing lines, card stats scores, MG10's D
    window, MG7's excused games, and C3's "unsure"."""

    def test_main_cards_sum_a_name_on_two_lines(self):
        entry = {"cards": {"Main": [(2, "Forest"), (4, "Llanowar Elves"), (7, "Forest")]}}
        self.assertEqual(overnight_legs._main_cards(entry), [(9, "Forest"), (4, "Llanowar Elves")])

    def test_row_score_reads_shrunk_then_the_diffs_value(self):
        self.assertEqual(overnight_legs._row_score({"shrunk": 0.02, "diff": {"value": 0.1}}), 0.02)
        self.assertEqual(overnight_legs._row_score({"shrunk": None, "diff": {"value": 0.1}}), 0.1)
        self.assertIsNone(overnight_legs._row_score({"diff": None}))

    def test_mg10_counts_only_d(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            start = time.mktime(time.strptime("2026-10-03T23:00:00", "%Y-%m-%dT%H:%M:%S"))
            rows = ["t,unix,java_ws_mb"]
            rows += [f"{i},{start - 1000 + i},40000" for i in range(100)]         # B5's K = 32, before D
            rows += [f"{i},{start + i},8000" for i in range(100)]
            (out / "cpu.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
            state = {"items": {"D1": {"status": "done"}, "D0": {"started": "2026-10-03T23:00:00"},
                               "D9": {"ended": "2026-10-03T23:05:00"}}}
            found = overnight_report.gate_mg10(out, state, {"items": []})
        self.assertEqual(found["status"], "pass")
        self.assertEqual(found["numbers"]["ws_peak_mb"], 8000)

    def test_mg7_excuses_a_difference_in_an_ai_timeout_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "staging" / "results").mkdir(parents=True)
            result = {"key": "k1", "sides": [{}, {}], "batches": [{"games": [{"g": 5, "ai_to": 1, "r": "win"}]}]}
            (out / "staging" / "results" / "k1.json").write_text(json.dumps(result), encoding="utf-8")
            (out / "probes").mkdir()
            games = [{"key": "k1", "g": 5, "format": "Constructed", "verdict": "failed"}]
            games += [{"key": "k2", "g": i, "format": "Constructed", "verdict": "same"} for i in range(9)]
            (out / "probes" / "00.json").write_text(json.dumps({"games": games}), encoding="utf-8")
            state = {"items": {"D1": {"status": "done"}},
                     "probes": [{"file": "00.json", "session": 1, "started": "2026-10-03T23:00:00"}]}
            found = overnight_report.gate_mg7(out, state, {"items": [], "soak_min_s": 600})
        self.assertNotEqual(found["status"], "fail")
        self.assertEqual(found["numbers"]["excused"], 1)

    def test_the_owners_stop_file_stops_the_running_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = overnight.Controller.__new__(overnight.Controller)
            controller.out, controller.session = Path(tmp), {"deadline_epoch": time.time() + 3600}
            controller.monitor = None
            item = {"id": "D1", "block": "D", "priority": 0}
            self.assertIsNone(controller._should_stop(item, time.monotonic(), 60, None))
            (Path(tmp) / "STOP").write_text("", encoding="utf-8")
            self.assertEqual(controller._should_stop(item, time.monotonic(), 60, None), "the owner's STOP file")

    def test_an_unsure_serve_check_counts_as_finished(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "C" / "c3").mkdir(parents=True)
            (out / "C" / "c3" / "out.txt").write_text("Checking a warm worker ...\nunsure\n", encoding="utf-8")
            controller = overnight.Controller.__new__(overnight.Controller)
            controller.out, controller.plan = out, {"items": [{"id": "C3", "priority": 0}]}
            controller.state = {"items": {"C3": {"status": "failed", "codes": [1]}}}
            controller.save = lambda: None
            controller._c_gate({"id": "C3", "block": "C"})
            self.assertEqual(controller.state["items"]["C3"]["status"], "done")
            self.assertEqual(controller.state["items"]["C3"]["gate"]["status"], "pass")


class DeckOrderTests(unittest.TestCase):
    """C4's per-game classes (overnight_legs._divergence): the whole game is cut off at its first
    difference, whichever seat it shows in, and the changed seat may be either."""

    @staticmethod
    def game(changed_deck, player, *lines):
        return "\n".join(["Information: DL|deck|1|1=Island;2=Lightning Bolt",
                          f"Information: DL|deck|2|3=Forest;4={changed_deck}",
                          f"Turn: Turn 1 ({player})", *lines]) + "\n"

    @staticmethod
    def draw(seat, card_id, name):
        return f"Information: DL|zone|1|0|MAIN1|Library|Hand|{seat}|{card_id}|{name}"

    def test_classes(self):
        base = self.game("Llanowar Elves", "Ai(2)-aaa", self.draw(1, 1, "Island"), self.draw(2, 4, "Llanowar Elves"),
                         self.draw(1, 2, "Lightning Bolt"))
        miss = self.game("Forest", "Ai(2)-bbb", self.draw(1, 2, "Lightning Bolt"), self.draw(2, 4, "Forest"))
        self.assertIsNone(overnight_legs._divergence(base, base))           # no seat's list changed
        # The opponent's later draw differs after the changed card moved: aligned, not a miss.
        seen = self.game("Forest", "Ai(2)-bbb", self.draw(1, 1, "Island"), self.draw(2, 4, "Forest"),
                         self.draw(1, 1, "Island"))
        self.assertEqual(overnight_legs._divergence(base, seen), "seen")
        self.assertIsNone(overnight_legs._divergence(base, miss))           # differs before a changed card moved
        search = "Information: Ai(2)-aaa searches their library"
        searched_a = self.game("Llanowar Elves", "Ai(2)-aaa", self.draw(1, 1, "Island"), search,
                               "Information: DL|zone|1|0|MAIN1|Library|Battlefield|2|3|Forest")
        searched_b = self.game("Forest", "Ai(2)-bbb", self.draw(1, 1, "Island"), search.replace("aaa", "bbb"),
                               "Information: DL|zone|1|0|MAIN1|Library|Battlefield|2|9|Forest")
        self.assertEqual(overnight_legs._divergence(searched_a, searched_b), "searched")
        timed = self.game("Forest", "Ai(2)-bbb", "java.util.concurrent.TimeoutException", self.draw(1, 2, "Lightning Bolt"))
        self.assertEqual(overnight_legs._divergence(
            self.game("Llanowar Elves", "Ai(2)-aaa", "java.util.concurrent.TimeoutException", self.draw(1, 1, "Island")),
            timed), "timed out")


class SoakProbeTests(unittest.TestCase):

    def test_sample_takes_unprobed_games_half_recent(self):
        now = time.time()
        result = {"format": "Constructed"}
        logs = [{"key": "a" * 64, "first": 0, "last": 24, "mtime": now - 3600, "result": result},
                {"key": "b" * 64, "first": 0, "last": 24, "mtime": now - 60, "result": result},
                {"key": "c" * 64, "first": 0, "last": 4, "mtime": now, "result": {"format": "Commander"}}]
        done = {f"{'b' * 64}:{g}" for g in range(20)}
        picked = cli._soak_sample(logs, done, 10, 2, random.Random(1), now)
        con = [(i["key"][0], g) for i, g in picked if i["result"]["format"] == "Constructed"]
        self.assertEqual(len(con), 10)
        self.assertEqual(sum(1 for k, _ in con if k == "b"), 5)          # every unprobed recent game
        self.assertFalse(any(f"{'b' * 64}:{g}" in done for k, g in con if k == "b"))
        self.assertEqual(len([1 for i, _ in picked if i["result"]["format"] == "Commander"]), 2)

    def test_game_text_from_a_chunk_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "25-27.log.gz"
            text = "\n".join(f"line {g}\nGame Result: Game {g} ended" for g in (25, 26, 27))
            path.write_bytes(gzip.compress(text.encode()))
            self.assertIn("line 26", cli._soak_game_text(path, 26, 25))
            self.assertIsNone(cli._soak_game_text(path, 30, 25))

    def test_fresh_and_chunk_copies_compare_with_masks(self):
        fresh = ("Ai(1)-a - 1 game of Constructed seed 5\nDLENGINE|v=2|deckorder=1,1\nTurn 1: Ai(1)-a\n"
                 "DL|zone|1|1|M1|Library|Hand|1|5|Shock\nGame Result: Game 1 ended in 1234 ms. Ai(1)-a has won!\n")
        warm = ("Turn 1: Ai(1)-a\nDL|zone|1|1|M1|Library|Hand|1|5|Shock\n\n"
                "Game Result: Game 17 ended in 99 ms. Ai(1)-a has won!")
        self.assertTrue(cli._soak_same("Constructed", fresh, warm))
        other = warm.replace("Shock", "Bolt")
        self.assertFalse(cli._soak_same("Constructed", fresh, other))
        self.assertIn("line 2", cli._soak_difference(fresh, other))

    def test_commander_game_cut_from_a_chunk_log_matches_its_one_shot(self):
        game = ("Turn: Turn 1 (Ai(2)-b)\nTurn: Turn 2 (Ai(1)-a)\nGame Outcome: Turn 2\n"
                "Game Outcome: Ai(1)-a has won because all opponents have lost\n"
                "Game Outcome: Ai(2)-b has lost because life total reached 0\n"
                "Game Result: Game {n} ended in {ms} ms. Ai(1)-a has won!\n")
        fresh = "Ai(1)-a - Ai(2)-b - 1 game of Commander seed 5\nDLENGINE|v=2\n" + game.format(n=1, ms=1234)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "40-42.log.gz"
            chunk = "".join(game.format(n=n, ms=90 + n) for n in (1, 2, 3))
            path.write_bytes(gzip.compress(("Ai(1)-a - Ai(2)-b - 3 games of Commander seed 5\n" + chunk).encode()))
            warm = cli._soak_game_text(path, 41, 40)
            path.write_bytes(gzip.compress(chunk.encode()))         # a request's output, no header line
            bare = cli._soak_game_text(path, 41, 40)
        for text in (warm, bare):
            self.assertEqual(cli._soak_outcomes("Commander", text), [("win", 0, 1, 2)])
            self.assertTrue(cli._soak_same("Commander", fresh, text))
        self.assertFalse(cli._soak_same("Commander", fresh, warm.replace("Ai(1)-a has won!", "Ai(2)-b has won!")
                                        .replace("Ai(1)-a has won because", "Ai(2)-b has won because")))

    def test_refuses_without_a_live_server_pool(self):
        from decklab.tests import test_forge
        with mock.patch.object(cli, "_soak_server_live", return_value=False):
            code, out, err = test_forge.CommandLineTests.run_main(
                self, "soak-probe", "--results-dir", ".", "--logs-dir", ".", "--server-port", "8643")
        self.assertEqual(code, 1)
        self.assertIn("no live server pool on port 8643", err)


@unittest.skipUnless(sys.platform == "win32", "Windows jobs")
class FakeRunTests(unittest.TestCase):
    """A --fake --smoke run end to end: the supervisor and controller as processes, every command a short
    fake child; the drill kills the controller during the first D item, the supervisor starts it again,
    and the item finishes; an item that ignores STOP is ended by its job."""

    def test_end_to_end(self):
        plan = {"items": [
            {"id": "A1", "block": "A", "priority": 0, "est_min": 1, "internal": "preflight"},
            {"id": "B0", "block": "B", "priority": 0, "est_min": 1, "timing": True, "cmds": [["{F}", "x"]]},
            {"id": "C1", "block": "C", "priority": 0, "est_min": 1, "cmds": [["{L}", "x"]]},
            {"id": "C4", "block": "C", "priority": 0, "est_min": 1, "requires": ["V"], "cmds": [["{L}", "x"]]},
            {"id": "D0", "block": "D", "priority": 0, "est_min": 1, "internal": "server-start"},
            {"id": "D1", "block": "D", "priority": 0, "est_min": 2, "soak": True, "pool": "server",
             "cmds": [["{F}", "replay"]]},
            {"id": "D3", "block": "D", "priority": 3, "est_min": 6000, "cmds": [["{F}", "x"]]},
            {"id": "D-fill", "block": "D", "priority": 0, "est_min": 0, "internal": "filler", "soak": True,
             "pool": "server", "cmds": [["{F}", "replay", "--results-dir", "{OUT}/D/filler/results"]]},
            {"id": "D9", "block": "D", "priority": 0, "est_min": 1, "internal": "server-stop"},
            {"id": "E4", "block": "E", "priority": 0, "est_min": 1, "internal": "cleanup"},
            {"id": "E5", "block": "E", "priority": 0, "est_min": 1, "internal": "report"}]}
        built = {p: {"built": p != "V"} for p in overnight.PACKAGES}
        with tempfile.TemporaryDirectory() as tmp:
            resolved = overnight.resolve(plan, tmp, main=str(overnight.TREE), built=built, legs=set(), smoke=True)
            resolved["fake_seconds"] = 6
            resolved["soak_min_s"] = 5         # owed all along (no Forge worker is busy): 3 fake pieces
            (Path(tmp) / "plan.resolved.json").write_text(json.dumps(resolved), encoding="utf-8")
            done = subprocess.run([sys.executable, str(HERE / "overnight.py"), "supervise", "--out", tmp, "--fake",
                                   "--smoke", "--budget-h", "1"], capture_output=True, text=True, timeout=240)
            state = overnight.load_state(tmp)
            report = json.loads((Path(tmp) / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(state["items"]["D1"]["status"], "done")
        self.assertEqual(state["items"]["D1"]["attempts"], 2)                  # killed once, run again
        self.assertEqual(state["drill"]["killed"]["item"], "D1")
        self.assertEqual(state["drill"]["after_kill"]["leftovers"], [])
        self.assertEqual(state["sessions"][-1]["restarts"], 1)
        self.assertTrue(state["drill"]["stop_drill"]["pass"])
        self.assertEqual(state["items"]["D3"]["status"], "dropped")            # P3 doesn't fit an hour
        self.assertEqual(state["items"]["D-fill"]["pieces"], 3)
        self.assertEqual(state.get("filler_generation", 0), 0)                 # each piece was cut at its time
        self.assertEqual(state["items"]["C4"]["status"], "skipped")
        self.assertEqual(report["gates"]["MG5"]["status"], "not built tonight")
        self.assertEqual(report["verdict"], "INCOMPLETE")
        self.assertEqual(state["clean"]["own_java"], [])


if __name__ == "__main__":
    unittest.main()
