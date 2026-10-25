"""The combined run's 4-player Commander pods (D4a, M6): decklab/forge-trial/overnight_pods.py, its leg in
overnight_legs.py and its section and optional gate in overnight_report.py. Forge is faked throughout."""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "forge-trial"
sys.path.insert(0, str(HERE))

import overnight                 # noqa: E402
import overnight_legs            # noqa: E402
import overnight_pods            # noqa: E402
import overnight_report          # noqa: E402

DECKS = ["commander/a", "commander/b", "commander/c", "product/p"]


def pod_lines(n, ms, winner, first=1, turns=40, clock=False, ai_to=0, draw=False):
    """Forge's output for one 4-player game (the lines PodReader reads, in Forge's order)."""
    lines = ["java.util.concurrent.TimeoutException", "AI eval thread at timeout:"] * ai_to
    if clock:
        lines.append("Stopping slow match as draw")
    seat_of_turn = [(first - 1 + t) % 4 + 1 for t in range(turns)]
    lines += [f"Turn: Turn {t + 1} (Ai({seat_of_turn[t]})-deck{seat_of_turn[t]})" for t in range(turns)][::-1]
    lines.append("Game Outcome: Match Duration 0m : 31s")
    lines.append(f"Game Outcome: Turn {(turns + 1) // 2}")
    for seat in range(1, 5):
        if clock or seat == winner:
            lines.append(f"Game Outcome: Ai({seat})-deck{seat} has won because all opponents have lost")
        else:
            lines.append(f"Game Outcome: Ai({seat})-deck{seat} has lost because life total reached 0")
    if draw:
        lines.append(f"Game Result: Game {n} ended in a Draw! Took {ms} ms.")
    else:
        lines.append(f"Game Result: Game {n} ended in {ms} ms. Ai({winner if not clock else 3})-deck has won!")
    return lines


class ReaderTests(unittest.TestCase):

    def test_win_clock_stop_draw_and_ai_timeouts(self):
        reader = overnight_pods.PodReader()
        for line in (pod_lines(1, 31974, 2, first=3, turns=36, ai_to=2) + pod_lines(2, 600000, None, clock=True)
                     + pod_lines(3, 5000, None, draw=True) + ["Could not load deck - x.dck"]):
            reader.feed(line + "\n")
        g1, g2, g3 = reader.games
        self.assertEqual((g1["result"], g1["w"], g1["ms"], g1["turns"], g1["first"], g1["ai_to"]),
                         ("win", 2, 31974, 36, 3, 2))
        self.assertEqual(g1["lost"]["1"], "life total reached 0")
        self.assertEqual((g2["result"], g2["w"], g2["ai_to"]), ("clock", None, 0))   # Forge credits seat 3: not a win
        self.assertEqual((g3["result"], g3["w"]), ("draw", None))
        self.assertEqual(reader.load_errors, ["Could not load deck - x.dck"])

    def test_every_survivor_won_is_a_clock_stop_even_without_its_line(self):
        reader = overnight_pods.PodReader()
        for line in pod_lines(1, 9000, 1, clock=True)[1:]:          # without "Stopping slow match as draw"
            reader.feed(line)
        self.assertEqual(reader.games[0]["result"], "clock")


class BatchTests(unittest.TestCase):

    def test_seats_rotate_and_pods_split(self):
        jobs = overnight_pods.batches("main", DECKS, 12, 5, 100)
        self.assertEqual([j["pods"] for j in jobs], [5, 5, 2])
        self.assertEqual([j["seed"] for j in jobs], [100, 101, 102])
        self.assertEqual(jobs[1]["seats"], DECKS[1:] + DECKS[:1])
        jobs = overnight_pods.batches("main", DECKS, 8, 1, 0)
        for seat in range(4):                    # each deck in each seat equally often over 4 batches
            self.assertEqual(sorted(j["seats"][seat] for j in jobs[:4]), sorted(DECKS))

    def test_command_is_plain_forge_with_four_decks(self):
        setup = {"java": "java", "xmx": "1024m", "jar": "forge.jar", "decks_dir": "D"}
        argv = overnight_pods.command(setup, ["a.dck", "b.dck", "c.dck", "d.dck"], 5, 7, 600)
        self.assertIn("-jar", argv)
        i = argv.index("-d")
        self.assertEqual(argv[i + 1:i + 5], ["a.dck", "b.dck", "c.dck", "d.dck"])
        self.assertEqual(argv[argv.index("-f") + 1], "Commander")
        self.assertEqual(argv[argv.index("-n") + 1], "5")
        self.assertEqual(argv[argv.index("-c") + 1], "600")
        self.assertNotIn("-a", argv)


def _row(series, seats, games, **kw):
    return dict({"series": series, "batch": 0, "seats": seats, "pods": len(games), "seed": 1, "games": games,
                 "load_errors": [], "unsupported": [], "exit": 0, "killed": None, "wall_s": 10}, **kw)


def _g(w, result="win", ms=60000, ai_to=0, first=1):
    return {"game": 1, "result": result, "w": w, "ms": ms, "turns": 40, "first": first, "ai_to": ai_to, "lost": {}}


class SummaryTests(unittest.TestCase):

    def test_seat_deck_and_compare_numbers(self):
        rot = overnight_pods.rotation
        rows = [_row("main", rot(DECKS, 0), [_g(1), _g(1), _g(None, "clock", 600000)]),
                _row("main", rot(DECKS, 1), [_g(4, ai_to=3), _g(2)]),
                _row("other", DECKS, [_g(1)])]
        s = overnight_pods.summary(rows, "main", pair=("commander/a", "commander/b"))
        self.assertEqual((s["pods"], s["counted"], s["clock_stops"], s["ai_timeouts"], s["ai_timeout_pods"]),
                         (5, 4, 1, 3, 1))
        self.assertEqual(s["by_seat"]["1"]["wins"], 2)
        self.assertEqual(s["by_seat"]["4"]["wins"], 1)
        # rotation 1 puts commander/a in seat 4 and commander/c in seat 2
        self.assertEqual(s["by_deck"]["commander/a"]["wins"], 3)
        self.assertEqual(s["by_deck"]["commander/c"]["wins"], 1)
        self.assertEqual(s["by_deck"]["commander/a"]["pods"], 4)
        lo, hi = s["by_deck"]["commander/a"]["range"]
        self.assertTrue(lo < 0.75 < hi)
        self.assertEqual(s["minutes_per_pod"]["max"], 10.0)
        c = s["compare"]
        self.assertEqual((c["pods"], c["a"]["wins"], c["b"]["wins"]), (4, 3, 0))
        self.assertAlmostEqual(c["difference"]["value"], 0.75)
        self.assertEqual(c["head_to_head"]["wins"], 3)

    def test_empty_series(self):
        s = overnight_pods.summary([], "main")
        self.assertEqual(s["pods"], 0)
        self.assertIsNone(s["by_seat"]["1"]["rate"])
        self.assertNotIn("minutes_per_pod", s)


FAKE_FORGE = r"""
import sys
argv = sys.argv[1:]
mode = argv[0]
i = argv.index("-d")
n = int(argv[argv.index("-n") + 1])
seed = int(argv[argv.index("-s") + 1])
if mode == "fail-once" and seed == 1 and not __import__("os").path.exists(argv[-1]):
    open(argv[-1], "w").close()
    print("Exception in thread main java.lang.IllegalStateException: busy")
    sys.exit(1)
if mode == "hang":
    import time
    time.sleep(60)
for g in range(1, n + 1):
    w = (seed + g) % 4 + 1
    print("Turn: Turn 1 (Ai(1)-x)")
    for s in range(1, 5):
        print(f"Game Outcome: Ai({s})-x has {'won because all opponents have lost' if s == w else 'lost because life total reached 0'}")
    print(f"Game Result: Game {g} ended in {1000 * g} ms. Ai({w})-x has won!")
    sys.stdout.flush()
"""


class _FakeLease:
    released = 0

    def release(self):
        type(self).released += 1


class RunTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.script = Path(self.tmp.name) / "fake_forge.py"
        self.script.write_text(FAKE_FORGE, encoding="utf-8")
        self.setup = {"java": "java", "xmx": "1g", "jar": "f.jar", "decks_dir": self.tmp.name, "forge_dir": self.tmp.name}
        self.dck = {d: f"{i}.dck" for i, d in enumerate(DECKS)}

    def _start(self, mode):
        marker = str(Path(self.tmp.name) / "marker")

        def start(argv, cwd, env):
            rest = argv[argv.index("sim") + 1:]
            return subprocess.Popen([sys.executable, str(self.script), mode, *rest, marker], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, cwd=cwd)
        return start

    def _run(self, mode, jobs, stopped=lambda: False, **kw):
        saves = []
        rows = overnight_pods.run(jobs, setup=self.setup, env=None, dck_of=self.dck, procs=3, clock_s=600,
                                  stopped=stopped, save=saves.append, start=self._start(mode),
                                  kill=lambda p: p.kill(), claim=lambda cancel, what: _FakeLease(), stagger_s=0.1, **kw)
        return rows, saves

    def test_batches_play_and_a_failed_start_is_played_again(self):
        jobs = overnight_pods.batches("main", DECKS, 7, 3, 0)
        rows, saves = self._run("fail-once", jobs)
        self.assertEqual(sum(len(r["games"]) for r in rows), 7)
        self.assertEqual(len(saves), 3)
        again = [r for r in rows if r.get("attempt")]
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0]["first_try"]["exit"], 1)
        self.assertIn("busy", " ".join(again[0]["first_try"]["tail"]))
        s = overnight_pods.summary(rows, "main")
        self.assertEqual(s["pods"], 7)
        self.assertEqual(sum(r["wins"] for r in s["by_seat"].values()), 7)

    def test_stop_kills_and_keeps_what_finished(self):
        event = threading.Event()
        threading.Timer(1.5, event.set).start()
        jobs = overnight_pods.batches("main", DECKS, 4, 2, 10)
        rows, _ = self._run("hang", jobs, stopped=event.is_set)
        self.assertTrue(rows)
        self.assertTrue(all(r["killed"] == "stopped" for r in rows))
        self.assertFalse(any(r.get("attempt") for r in rows))       # a stopped batch isn't played again

    def test_batch_timeout_kills(self):
        rows, _ = self._run("hang", overnight_pods.batches("main", DECKS, 1, 1, 10), batch_timeout_s=1)
        self.assertEqual(rows[0]["killed"], "batch timeout")


class LegTests(unittest.TestCase):

    def test_leg_writes_both_series_and_skips_one_that_doesnt_load(self):
        from decklab.lib.forge import cli, install, runner

        def entry(deck_id, _):
            if deck_id == "commander/missing":
                raise SystemExit("no such deck")
            return {"id": deck_id, "kind": "commander", "card_sha": "%064x" % abs(hash(deck_id)), "dck": "x",
                    "title": deck_id.upper()}

        def fake_run(jobs, **kw):
            rows = [dict(j, games=[_g(1)] * j["pods"], load_errors=[], unsupported=[], exit=0, killed=None, wall_s=1)
                    for j in jobs]
            kw["save"](rows)
            return rows

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(cli, "_cli_entry", entry), \
                mock.patch.object(install, "_setup", lambda: {"decks_dir": Path(tmp), "user_dir": Path(tmp)}), \
                mock.patch.object(runner, "_write_decks"), mock.patch.object(runner, "_prepare_user_dir"), \
                mock.patch.object(runner, "_tidy_user_dir"), mock.patch.object(overnight_pods, "run", fake_run):
            code = overnight_legs.main(["m6", "--out", tmp, "--pods", "6", "--per-batch", "5", "--decks", ",".join(DECKS),
                                        "--compare", "commander/a,product/p,commander/b,commander/c",
                                        "--compare-pods", "4"])
            found = json.loads((Path(tmp) / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertEqual(found["summaries"]["main"]["pods"], 6)
            self.assertEqual(found["summaries"]["compare"]["compare"]["decks"], ["commander/a", "product/p"])
            self.assertEqual(found["titles"]["product/p"], "PRODUCT/P")
            code = overnight_legs.main(["m6", "--out", tmp, "--pods", "2", "--decks", ",".join(DECKS),
                                        "--compare", "commander/a,commander/missing,commander/b,commander/c",
                                        "--compare-pods", "4"])
            found = json.loads((Path(tmp) / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertIn("no such deck", found["skipped"]["compare"])
            self.assertEqual(list(found["summaries"]), ["main"])

    def test_leg_wants_four_different_decks(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                overnight_legs.main(["m6", "--out", tmp, "--decks", "commander/a,commander/a,commander/b,commander/c"])

    def test_m6_is_built_and_planned(self):
        self.assertIn("m6", overnight.leg_names())
        plan = json.loads((HERE / "overnight-plan.json").read_text(encoding="utf-8"))
        d4a = next(i for i in plan["items"] if i["id"] == "D4a")
        self.assertEqual(d4a["leg"], "m6")
        self.assertLessEqual(d4a["priority"], 3)
        cmd = d4a["cmds"][0]
        self.assertEqual(len(cmd[cmd.index("--decks") + 1].split(",")), 4)
        self.assertIn("product/fdc-calling-all-angels", cmd[cmd.index("--compare") + 1])


class ReportTests(unittest.TestCase):

    def _out(self, tmp, summaries, planned=200, status="done"):
        out = Path(tmp)
        (out / "D" / "m6").mkdir(parents=True)
        (out / "D" / "m6" / "result.json").write_text(json.dumps({"leg": "m6", "planned": {"main": planned},
                                                                  "summaries": summaries}), encoding="utf-8")
        state = {"items": {"D4a": {"status": status}}}
        plan = {"items": [{"id": "D4a", "priority": 2}]}
        return out, state, plan

    def _summary(self, pods=200, clock=0, load_errors=()):
        rows = [_row("main", overnight_pods.rotation(DECKS, k), [_g(k % 4 + 1)] * (pods // 4)) for k in range(4)]
        s = overnight_pods.summary(rows, "main", pair=("commander/a", "product/p"))
        s["clock_stops"] = clock
        s["load_errors"] = list(load_errors)
        return s

    def test_gate_passes_and_section_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, state, plan = self._out(tmp, {"main": self._summary()})
            g = overnight_report.gate_m6(out, state, plan)
            self.assertEqual(g["status"], "pass")
            self.assertEqual(g["numbers"]["pods"], 200)
            text = "\n".join(overnight_pods.markdown(out))
            self.assertIn("## 4-player Commander pods (D4a, M6; optional)", text)
            self.assertIn("| commander/a |", text)
            self.assertIn("Upgraded against precon", text)

    def test_problems_are_not_checked_never_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, state, plan = self._out(tmp, {"main": self._summary(pods=40, clock=20, load_errors=["Could not load"])})
            g = overnight_report.gate_m6(out, state, plan)
            self.assertEqual(g["status"], "not checked")
            self.assertIn("40 of 200 pods", g["detail"])
        with tempfile.TemporaryDirectory() as tmp:
            out, state, plan = self._out(tmp, {"main": self._summary()}, status="dropped")
            self.assertEqual(overnight_report.gate_m6(out, state, plan)["status"], "not checked")

    def test_m6_never_holds_up_or_fails_the_verdict(self):
        gates = {f"MG{i}": {"status": "pass"} for i in range(1, 17)}
        plan = {"items": []}
        for status in ("not checked", "not built tonight", "fail"):
            self.assertEqual(overnight_report.verdict(dict(gates, M6={"status": status}), {}, plan)[0], "PASS")

    def test_build_and_markdown_include_m6(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, state, plan = self._out(tmp, {"main": self._summary()})
            (out / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (out / "plan.resolved.json").write_text(json.dumps(plan), encoding="utf-8")
            found = overnight_report.write(out)
            self.assertIn("M6", found["gates"])
            text = (out / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("4-player pods (D4a, optional)", text)
            self.assertIn("### Series: main", text)


if __name__ == "__main__":
    unittest.main()
