"""Milestone 0 step 3: run K Forge sim processes at the same time and measure throughput.

    python scale_run.py --k 8 --games 50 --tag NAME [--seed 1 | --distinct-seeds] [--lazy]
                        [--jvm=-XX:+DisableExplicitGC ...] [--xmx 1024m] [--quiet]
                        [--user-dir PATH] [--deck1 PATH --deck2 PATH] [--interval 1.0]

Each of the K processes plays DECK1 vs DECK2 (default: decks/gruul-ramp-owned.dck vs
decks/izzet-prowess-owned.dck) for --games games. By default every process uses the SAME seed
(--seed, default 1), so every process has exactly the same work to do as a single process with
that seed (Forge replays a seeded game exactly; setup-notes.md section 7): the per-game times at
K processes can be compared directly with K=1, and the winners double as a determinism check under
load. --distinct-seeds gives process i the seed (seed + i) instead.

Builds the Forge command exactly like run_sim.py (imports it: same java.exe, -Xmx, flags, user
dir handling, deck -D/-d handling and output parser), and adds:
  - a timestamp (seconds since the first launch) on every stdout line of every process, so the
    start-up time (launch -> "Ai(1)-... vs ..." header) and each game's finish time are known;
  - a sampler thread (every --interval s): system CPU busy % (GetSystemTimes; 100 % = all 32
    logical CPUs), physical memory in use (GlobalMemoryStatusEx), and the sum of the K processes'
    working sets / private bytes (GetProcessMemoryInfo) at that moment;
  - per process at exit: peak working set, peak private bytes, CPU seconds (run_sim.ProcStats).

Throughput figures in the JSON ("agg"):
  steady_games_per_min   games finished while ALL K processes were playing (from the last
                         process's header to the first process's last game), per minute of that
                         window: the rate the PC sustains with K busy workers, start-up excluded.
  sum_proc_games_per_min sum over processes of games / (last game - header): also excludes
                         start-up, but counts each process's own game phase.
  incl_startup_games_per_min  K x games / (first launch -> last process exit): what a batch of
                         this size really delivers, start-up included.

Output: results/scale/<tag>.json (summary, per process, per game timestamps),
results/scale/<tag>.timeline.csv (sampler rows) and logs/scale/<tag>-p<i>.log (raw Forge output).
Windows only. Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_sim  # noqa: E402  (shared helper; used read-only)


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def sys_times() -> tuple[int, int]:
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
    f = lambda t: (t.dwHighDateTime << 32) | t.dwLowDateTime
    return f(idle), f(kernel) + f(user)  # kernel time includes idle time


def phys_used_mb() -> tuple[float, float]:
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return (m.ullTotalPhys - m.ullAvailPhys) / 2**20, (m.ullTotalPageFile - m.ullAvailPageFile) / 2**20


def java_count() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq java.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    return sum(1 for l in out.splitlines() if l.startswith('"java.exe"'))


def cpu_busy_over(seconds: float) -> float:
    i0, t0 = sys_times()
    time.sleep(seconds)
    i1, t1 = sys_times()
    return 100.0 * (1 - (i1 - i0) / max(1, t1 - t0))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, required=True)
    ap.add_argument("--games", type=int, default=50)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--distinct-seeds", action="store_true")
    ap.add_argument("--lazy", action="store_true")
    ap.add_argument("--jvm", action="append", default=[])
    ap.add_argument("--xmx", default="1024m")
    ap.add_argument("--quiet", action="store_true", help="Forge -q (default: full game log, as Part B uses)")
    ap.add_argument("--user-dir", default=None)
    ap.add_argument("--deck1", type=Path, default=HERE / "decks" / "gruul-ramp-owned.dck")
    ap.add_argument("--deck2", type=Path, default=HERE / "decks" / "izzet-prowess-owned.dck")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--java", default=run_sim.DEFAULT_JAVA)
    ap.add_argument("--min-free-mb", type=float, default=3000,
                    help="kill every process if free physical memory drops below this (protects the PC)")
    a = ap.parse_args(argv)

    forge_dir = run_sim.DEFAULT_FORGE_DIR
    user_dir = a.user_dir or str(HERE / ("forge-user-scale-lazy" if a.lazy else "forge-user-scale"))
    env = run_sim.prepare_user_dir(user_dir, a.lazy, keep_logs=30)
    ddir, dnames, _ = run_sim.deck_args([a.deck1, a.deck2])
    jar = run_sim.find_jar(forge_dir)
    jvm = ([f"-Xmx{a.xmx}"] if a.xmx.lower() != "none" else []) + [
        "-Dio.netty.tryReflectionSetAccessible=true", "-Dfile.encoding=UTF-8"] + a.jvm
    out_dir = HERE / "results" / "scale"
    log_dir = HERE / "logs" / "scale"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    # background load before we start (other agents / Python tracks)
    pre_java = java_count()
    pre_cpu = cpu_busy_over(3.0)
    pre_mem, pre_commit = phys_used_mb()

    procs = []
    t0 = time.perf_counter()
    wall_start = time.strftime("%Y-%m-%d %H:%M:%S")
    for i in range(a.k):
        seed = a.seed + i if a.distinct_seeds else a.seed
        cmd = [a.java, *jvm, "-jar", jar, "sim", "-D", ddir, "-d", *dnames, "-n", str(a.games),
               "-f", "Constructed", "-c", str(a.timeout), "-a", "Default", "Default", "-s", str(seed)]
        if a.quiet:
            cmd.append("-q")
        t_launch = time.perf_counter() - t0
        p = subprocess.Popen(cmd, cwd=forge_dir, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                             encoding="utf-8", errors="replace", bufsize=1)
        procs.append({"i": i, "seed": seed, "cmd": cmd, "p": p, "stats": run_sim.ProcStats(p.pid),
                      "t_launch": t_launch, "t_header": None, "t_games": [], "t_exit": None,
                      "lines": [], "log": log_dir / f"{a.tag}-p{i:02d}.log"})

    def reader(pr):
        with open(pr["log"], "w", encoding="utf-8", newline="\n") as log:
            for line in pr["p"].stdout:
                t = time.perf_counter() - t0
                log.write(line)
                pr["lines"].append(line)
                s = line.rstrip("\r\n")
                if pr["t_header"] is None and run_sim.RE_HEADER.match(s):
                    pr["t_header"] = t
                elif s.startswith("Game Result: Game "):
                    pr["t_games"].append(t)
        pr["p"].wait()
        pr["t_exit"] = time.perf_counter() - t0

    threads = [threading.Thread(target=reader, args=(pr,), daemon=True) for pr in procs]
    for th in threads:
        th.start()

    timeline = []
    aborted: list[str] = []
    _m = MEMORYSTATUSEX()
    _m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(_m))
    total_mb = _m.ullTotalPhys / 2**20
    stop = threading.Event()

    def sampler():
        i0, tt0 = sys_times()
        while not stop.is_set():
            stop.wait(a.interval)
            i1, tt1 = sys_times()
            busy = 100.0 * (1 - (i1 - i0) / max(1, tt1 - tt0))
            i0, tt0 = i1, tt1
            ws = pv = 0
            alive = 0
            for pr in procs:
                if pr["t_exit"] is None:
                    m = pr["stats"]._mem()
                    if m:
                        ws += m.WorkingSetSize
                        pv += m.PagefileUsage
                        alive += 1
            used, commit = phys_used_mb()
            if total_mb - used < a.min_free_mb and not aborted:
                aborted.append(f"free memory {total_mb - used:.0f} MB < {a.min_free_mb:.0f} MB at t={time.perf_counter() - t0:.1f} s")
                for pr in procs:
                    if pr["p"].poll() is None:
                        pr["p"].kill()
            timeline.append({"t": round(time.perf_counter() - t0, 2), "cpu_busy_pct": round(busy, 1),
                             "alive": alive, "sum_ws_mb": round(ws / 2**20), "sum_private_mb": round(pv / 2**20),
                             "phys_used_mb": round(used), "commit_mb": round(commit)})

    sth = threading.Thread(target=sampler, daemon=True)
    sth.start()
    deadline = time.time() + 60 + a.games * (a.timeout + 5)
    for th in threads:
        th.join(max(1, deadline - time.time()))
    for pr in procs:
        if pr["p"].poll() is None:
            pr["p"].kill()
    for th in threads:
        th.join(5)
    stop.set()
    sth.join()

    per = []
    all_game_ms = []
    winners_ref = None
    same_winners = True
    for pr in procs:
        st = pr["stats"].finish()
        s = run_sim.parse(pr["lines"], 2)
        games = s["games"]
        winners = [g["winner"] for g in games]
        if winners_ref is None:
            winners_ref = winners
        elif winners != winners_ref and not a.distinct_seeds:
            same_winners = False
        ms = [g["ms"] for g in games]
        all_game_ms += ms
        th, tg = pr["t_header"], pr["t_games"]
        per.append({
            "i": pr["i"], "seed": pr["seed"], "games": len(games),
            "ok": len(games) == a.games and not s["unsupported"] and not s["load_errors"],
            "wins": [winners.count(1), winners.count(2)],
            "timeouts": sum(1 for g in games if g["result"] == "timeout"),
            "errors": sum(1 for g in games if g["result"] == "error"),
            "draws": sum(1 for g in games if g["result"] == "draw"),
            "t_launch": round(pr["t_launch"], 3), "startup_s": round(th - pr["t_launch"], 2) if th else None,
            "t_header": round(th, 2) if th else None, "t_last_game": round(tg[-1], 2) if tg else None,
            "t_exit": round(pr["t_exit"], 2) if pr["t_exit"] else None,
            "game_phase_s": round(tg[-1] - th, 2) if th and tg else None,
            "games_per_min": round(len(tg) / (tg[-1] - th) * 60, 1) if th and tg and tg[-1] > th else None,
            "game_ms_mean": round(statistics.mean(ms), 1) if ms else None,
            "peak_ws_mb": st["mem"]["peak_working_set_mb"], "peak_private_mb": st["mem"]["peak_private_mb"],
            "cpu_s": st["cpu_s"], "log": str(pr["log"]),
            "t_games": [round(t, 2) for t in tg], "game_ms": ms, "winners": winners,
        })

    headers = [p["t_header"] for p in per if p["t_header"] is not None]
    lasts = [p["t_last_game"] for p in per if p["t_last_game"] is not None]
    exits = [p["t_exit"] for p in per if p["t_exit"] is not None]
    total_games = sum(p["games"] for p in per)
    agg = {}
    if headers and lasts and len(headers) == a.k:
        w0, w1 = max(headers), min(lasts)
        in_win = sum(1 for p in per for t in p["t_games"] if w0 < t <= w1)
        agg["steady_window_s"] = round(w1 - w0, 2)
        agg["steady_games"] = in_win
        agg["steady_games_per_min"] = round(in_win / (w1 - w0) * 60, 1) if w1 > w0 else None
        agg["sum_proc_games_per_min"] = round(sum(p["games_per_min"] or 0 for p in per), 1)
        agg["makespan_s"] = round(max(exits), 2)
        agg["incl_startup_games_per_min"] = round(total_games / max(exits) * 60, 1)
        agg["startup_s"] = {"min": min(p["startup_s"] for p in per), "mean": round(statistics.mean(p["startup_s"] for p in per), 2),
                            "max": max(p["startup_s"] for p in per)}
        agg["game_ms_mean"] = round(statistics.mean(all_game_ms), 1)
        agg["game_ms_median"] = statistics.median(all_game_ms)
        busy_win = [r["cpu_busy_pct"] for r in timeline if w0 < r["t"] <= w1]
        agg["cpu_busy_pct_steady_mean"] = round(statistics.mean(busy_win), 1) if busy_win else None
        agg["cpu_busy_pct_max"] = max(r["cpu_busy_pct"] for r in timeline) if timeline else None
        agg["cpu_s_total"] = round(sum(p["cpu_s"] or 0 for p in per), 1)
        agg["cpu_s_per_game"] = round(agg["cpu_s_total"] / total_games, 2) if total_games else None
        agg["cores_busy_per_proc_steady"] = round(agg["cpu_busy_pct_steady_mean"] / 100 * 32 / a.k, 2) if busy_win else None
        agg["peak_ws_mb_per_proc"] = {"mean": round(statistics.mean(p["peak_ws_mb"] for p in per)),
                                      "max": max(p["peak_ws_mb"] for p in per)}
        agg["peak_private_mb_per_proc_mean"] = round(statistics.mean(p["peak_private_mb"] for p in per))
        agg["peak_sum_ws_mb"] = max(r["sum_ws_mb"] for r in timeline) if timeline else None
        agg["peak_sum_private_mb"] = max(r["sum_private_mb"] for r in timeline) if timeline else None
        agg["peak_phys_used_mb"] = max(r["phys_used_mb"] for r in timeline) if timeline else None
        agg["phys_used_increase_mb"] = round(agg["peak_phys_used_mb"] - pre_mem) if timeline else None
    result = {
        "tag": a.tag, "started": wall_start, "k": a.k, "games_per_proc": a.games, "seed": a.seed,
        "distinct_seeds": a.distinct_seeds, "lazy": a.lazy, "jvm": jvm, "quiet": a.quiet,
        "decks": [str(a.deck1), str(a.deck2)], "user_dir": user_dir,
        "all_ok": all(p["ok"] for p in per) and not aborted, "aborted": aborted or None,
        "total_games": total_games,
        "same_winners_all_procs": same_winners if not a.distinct_seeds else None,
        "winners_proc0": "".join(str(w) if w else "-" for w in (winners_ref or [])),
        "background": {"java_procs_before": pre_java, "cpu_busy_pct_3s_before": round(pre_cpu, 1),
                       "phys_used_mb_before": round(pre_mem), "commit_mb_before": round(pre_commit)},
        "agg": agg,
        "procs": per,
        "cmd_example": procs[0]["cmd"],
        "cwd": str(forge_dir),
    }
    (out_dir / f"{a.tag}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    with open(out_dir / f"{a.tag}.timeline.csv", "w", newline="", encoding="utf-8") as fh:
        if timeline:
            w = csv.DictWriter(fh, fieldnames=list(timeline[0]))
            w.writeheader()
            w.writerows(timeline)
    brief = {k: result[k] for k in ("tag", "k", "all_ok", "aborted", "total_games", "same_winners_all_procs", "winners_proc0", "background")}
    brief["agg"] = agg
    print(json.dumps(brief, indent=1))
    return 0 if result["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
