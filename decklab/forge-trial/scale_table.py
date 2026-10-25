"""Tabulate scale_run.py results (results/scale/<tag>.json) as a Markdown table.

    python scale_table.py TAG [TAG ...]        e.g. python scale_table.py def-k1 def-k4 def-k8

Columns:
  k            processes at once
  start s      start-up (launch -> header), mean and max over the processes
  ms/game      mean of Forge's own per-game "ended in N ms"
  slow         ms/game divided by the first tag's ms/game (same seed = same games)
  steady g/min games finished while all k processes were playing, per minute (start-up excluded)
  incl g/min   k x games / (launch -> last exit) (start-up included)
  CPU %        mean system CPU busy during the steady window (100 % = 32 logical CPUs)
  bg %         system CPU busy in the 3 s before launch (other programs)
  cores/proc   (CPU % - bg %) x 32 / 100 / k during the steady window
  CPU s/game   sum of the processes' CPU seconds (start-up included) / games
  proc cores   sum of the processes' CPU seconds / sum of their lifetimes (launch -> exit): cores
               each Forge process kept busy on average, from its own counters (not affected by
               other programs, unlike cores/proc)
  WS MB/proc   peak working set per process, mean (max)
  sum WS GB    largest sum of the k working sets seen at one moment (1 s samples)
  +RAM GB      rise of physical memory in use (GlobalMemoryStatusEx), peak minus before launch
  same         every process produced the same winners (same seed only)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(tags: list[str]) -> None:
    rows = []
    base = None
    for t in tags:
        d = json.loads((HERE / "results" / "scale" / f"{t}.json").read_text(encoding="utf-8"))
        a = d["agg"]
        if not a:
            print(f"| {t} | (no aggregate: {d.get('aborted')}) |")
            continue
        if base is None:
            base = a["game_ms_mean"]
        bg = d["background"]["cpu_busy_pct_3s_before"]
        cpu = a["cpu_busy_pct_steady_mean"]
        cores = (cpu - bg) * 32 / 100 / d["k"] if cpu is not None else None
        pc = sum(p["cpu_s"] for p in d["procs"]) / sum(p["t_exit"] - p["t_launch"] for p in d["procs"])
        rows.append(
            f"| {t} | {d['k']} | {a['startup_s']['mean']:.1f} ({a['startup_s']['max']:.1f}) | {a['game_ms_mean']:.0f} | "
            f"{a['game_ms_mean'] / base:.2f} | {a['steady_games_per_min']:.0f} | {a['incl_startup_games_per_min']:.0f} | "
            f"{cpu:.0f} | {bg:.0f} | {cores:.2f} | {pc:.2f} | {a['cpu_s_per_game']:.2f} | "
            f"{a['peak_ws_mb_per_proc']['mean']:.0f} ({a['peak_ws_mb_per_proc']['max']:.0f}) | "
            f"{a['peak_sum_ws_mb'] / 1024:.1f} | {a['phys_used_increase_mb'] / 1024:.1f} | "
            f"{'yes' if d['same_winners_all_procs'] else ('n/a' if d['same_winners_all_procs'] is None else 'NO')} |")
    print("| tag | k | start s mean (max) | ms/game | slow | steady g/min | incl g/min | CPU % | bg % | cores/proc | "
          "proc cores | CPU s/game | WS MB/proc mean (max) | sum WS GB | +RAM GB | same |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    print("\n".join(rows))


if __name__ == "__main__":
    main(sys.argv[1:])
