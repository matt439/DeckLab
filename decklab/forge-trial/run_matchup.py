"""Milestone 0 step 8: play one matchup as several parallel Forge batches and pool the results.

    python run_matchup.py --a decks/compare/izzet-prowess-owned.dck --b decks/compare/gruul-ramp-owned.dck
                          --games 400 --batch 50 --workers 12 --seed-base 1000 --tag izzet-gruul-owned
                          [--src-a magic/decks/casual/izzet-prowess.md --src-b magic/decks/casual/gruul-ramp.md]
                          [--lazy] [--jvm=-XX:+DisableExplicitGC ...] [--xmx 1024m] [--quiet]
                          [--user-dir forge-user-match] [--card-log] [--ai-a PROFILE] [--ai-b PROFILE] [--dry-run]

Splits --games into batches of --batch games. Batch j (0-based) uses seed (seed-base + j) and plays
A vs B when j is even, B vs A when j is odd (half the batches with the deck order swapped). Each
batch is one `python run_sim.py ...` process (run_sim.py is used unchanged; its options pass
through), and --workers batches run at the same time.

Output in results/matchups/<tag>/: batch-<j>.json (run_sim's JSON for each batch, which lists every
game) and summary.json:
  - games, wins for A and B, draws / timeouts / errors (run_sim's corrected classification);
  - A's win rate (draws count as non-wins) with a 95% Wilson interval;
  - on the play vs on the draw: A's record when A went first and when B went first (only known
    without --quiet), the starting player's overall win rate, and a play/draw-balanced win rate
    (the mean of A's on-the-play and on-the-draw win rates, i.e. what alternating starts would
    give; Forge itself lets the previous game's loser start, so starts are not balanced);
  - A's win rate by seat (A as deck 1 vs as deck 2);
  - rounds, per-game ms, wall time and games per minute for the whole matchup;
  - deck versions: the git commit (and dirty flag) of each --src deck file, and a SHA-256 of each .dck.
Standard library only.

Since phase 4 of Deck Lab's move to a database there are no deck .md files in git (the decks are
in the database), so --src-a/--src-b and the git_version provenance they record no longer apply:
a deck path from before then resolves only in the pre-db-decks tag. To play decks by their ids,
with saved results and {deck, revision} provenance, use `python -m decklab.lib.forge play`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def wilson(w: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def git_version(path: str | None) -> dict | None:
    if not path:
        return None
    rel = Path(path)
    try:
        h = subprocess.run(["git", "log", "-1", "--format=%H", "--", str(rel)], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", str(rel)], cwd=REPO,
                                    capture_output=True, text=True).stdout.strip())
    except OSError:
        return None
    return {"file": str(rel).replace("\\", "/"), "commit": h, "dirty": dirty}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True)
    ap.add_argument("--b", type=Path, required=True)
    ap.add_argument("--src-a")
    ap.add_argument("--src-b")
    ap.add_argument("--games", type=int, required=True)
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed-base", type=int, required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--lazy", action="store_true")
    ap.add_argument("--jvm", action="append", default=[])
    ap.add_argument("--xmx", default="1024m")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--card-log", action="store_true")
    ap.add_argument("--user-dir", default=str(HERE / "forge-user-match"))
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ai-a", default="Default", help="Forge AI profile for deck A (Default, Cautious, Reckless, Experimental)")
    ap.add_argument("--ai-b", default="Default")
    ap.add_argument("--only", type=int, nargs="+",
                    help="run only these batch indexes (e.g. to redo a failed batch); the summary still pools every "
                         "batch-NNN.json of the full plan, and wall_s / games_per_min then cover only this call")
    a = ap.parse_args(argv)

    out = HERE / "results" / "matchups" / a.tag
    logs = HERE / "logs" / "matchups" / a.tag
    out.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    A, B = a.a.resolve(), a.b.resolve()
    nb = math.ceil(a.games / a.batch)
    jobs = []
    for j in range(nb):
        n = min(a.batch, a.games - j * a.batch)
        d1, d2 = (A, B) if j % 2 == 0 else (B, A)
        ai1, ai2 = (a.ai_a, a.ai_b) if j % 2 == 0 else (a.ai_b, a.ai_a)
        seed = a.seed_base + j
        cmd = [sys.executable, str(HERE / "run_sim.py"), str(d1), str(d2), "-n", str(n), "-s", str(seed),
               "-c", str(a.timeout), "--xmx", a.xmx, "--user-dir", a.user_dir,
               "--json", str(out / f"batch-{j:03d}.json"), "--log", str(logs / f"b{j:03d}-s{seed}.log")]
        cmd += ["-a", ai1, ai2]
        cmd += [f"--jvm={f}" for f in a.jvm]
        if a.lazy:
            cmd.append("--lazy")
        if a.quiet:
            cmd.append("-q")
        if a.card_log:
            cmd.append("--card-log")
        jobs.append({"j": j, "seed": seed, "order": "AB" if j % 2 == 0 else "BA", "n": n, "cmd": cmd})
    if a.dry_run:
        print(json.dumps(jobs, indent=1))
        return 0

    t0 = time.perf_counter()
    started = time.strftime("%Y-%m-%d %H:%M:%S")

    def run(job):
        r = subprocess.run(job["cmd"], cwd=HERE, capture_output=True, text=True, encoding="utf-8", errors="replace")
        job["exit"] = r.returncode
        job["t_done"] = round(time.perf_counter() - t0, 1)
        if r.returncode != 0:
            job["stderr_tail"] = r.stderr[-2000:]
        return job

    to_run = [j for j in jobs if a.only is None or j["j"] in a.only]
    for j in jobs:
        j.setdefault("t_done", None)
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(run, to_run))
    done = jobs
    wall = time.perf_counter() - t0

    games = []
    batches = []
    for job in done:
        f = out / f"batch-{job['j']:03d}.json"
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            batches.append({"j": job["j"], "seed": job["seed"], "order": job["order"], "ok": False, "error": str(e)})
            continue
        # deck index -> "A"/"B" by path (names could clash)
        idx = {}
        for d in r["decks"]:
            idx[d["index"]] = "A" if Path(d["path"]).resolve() == A else "B"
        for g in r["games"]:
            games.append({"batch": job["j"], "seed": job["seed"], "order": job["order"], "game": g["game"],
                          "result": g["result"], "winner": idx.get(g["winner"]) if g["winner"] else None,
                          "first": idx.get(g["first"]) if g.get("first") else None,
                          "rounds": g.get("rounds"), "ms": g["ms"], "loss_reason": g.get("loss_reason")})
        batches.append({"j": job["j"], "seed": job["seed"], "order": job["order"], "ok": r["ok"], "error": r["error"],
                        "games": r["games_played"], "wins": {idx[d["index"]]: d["wins"] for d in r["decks"]},
                        "startup_s": r["startup_s"], "games_wall_s": r["games_wall_s"], "wall_s": r["wall_s"],
                        "t_done": job["t_done"], "unsupported": r["unsupported_cards"], "log": r["log"]})

    n = len(games)
    wa = sum(1 for g in games if g["winner"] == "A")
    wb = sum(1 for g in games if g["winner"] == "B")
    other = {k: sum(1 for g in games if g["result"] == k) for k in ("draw", "timeout", "error")}

    def rec(sel):
        gs = [g for g in games if sel(g)]
        w = sum(1 for g in gs if g["winner"] == "A")
        lo, hi = wilson(w, len(gs))
        return {"games": len(gs), "a_wins": w, "a_winrate": round(w / len(gs), 4) if gs else None,
                "ci95": [round(lo, 4), round(hi, 4)] if gs else None}

    known_first = [g for g in games if g["first"]]
    play = rec(lambda g: g["first"] == "A")
    draw = rec(lambda g: g["first"] == "B")
    balanced = None
    if play["games"] and draw["games"]:
        p1, p2 = play["a_winrate"], draw["a_winrate"]
        se = 0.5 * math.sqrt(p1 * (1 - p1) / play["games"] + p2 * (1 - p2) / draw["games"])
        bal = (p1 + p2) / 2
        balanced = {"a_winrate": round(bal, 4), "ci95_normal": [round(bal - 1.96 * se, 4), round(bal + 1.96 * se, 4)]}
    first_wins = sum(1 for g in known_first if g["winner"] == g["first"])
    lo, hi = wilson(wa, n)
    rounds = [g["rounds"] for g in games if g["rounds"]]
    ms = [g["ms"] for g in games]
    names = {}
    for d in (A, B):
        for line in d.read_text(encoding="utf-8").splitlines():
            if line.startswith("Name="):
                names["A" if d == A else "B"] = line[5:]
                break
    summary = {
        "tag": a.tag, "started": started, "forge": "2.0.15",
        "a": {"name": names.get("A"), "dck": str(A), "dck_sha256": hashlib.sha256(A.read_bytes()).hexdigest(),
              "source": git_version(a.src_a)},
        "b": {"name": names.get("B"), "dck": str(B), "dck_sha256": hashlib.sha256(B.read_bytes()).hexdigest(),
              "source": git_version(a.src_b)},
        "settings": {"games": a.games, "batch": a.batch, "batches": nb, "workers": a.workers, "seed_base": a.seed_base,
                     "seeds": [a.seed_base, a.seed_base + nb - 1], "order": "even batches A vs B, odd batches B vs A",
                     "lazy": a.lazy, "jvm": a.jvm, "xmx": a.xmx, "quiet": a.quiet, "card_log": a.card_log,
                     "per_game_clock_s": a.timeout, "ai": f"A {a.ai_a}, B {a.ai_b}",
                     "user_dir": a.user_dir, "only": a.only},
        "all_batches_ok": all(b.get("ok") for b in batches),
        "games": n, "a_wins": wa, "b_wins": wb, **{f"{k}s": v for k, v in other.items()},
        "a_winrate": round(wa / n, 4) if n else None, "a_ci95_wilson": [round(lo, 4), round(hi, 4)],
        "b_winrate": round(wb / n, 4) if n else None,
        "first_known": len(known_first),
        "a_on_play": play, "a_on_draw": draw, "a_winrate_play_draw_balanced": balanced,
        "starter_winrate": round(first_wins / len(known_first), 4) if known_first else None,
        "a_went_first": play["games"], "b_went_first": draw["games"],
        "a_as_deck1": rec(lambda g: g["order"] == "AB"), "a_as_deck2": rec(lambda g: g["order"] == "BA"),
        "rounds": {"mean": round(statistics.mean(rounds), 2), "min": min(rounds), "max": max(rounds)} if rounds else None,
        "game_ms": {"mean": round(statistics.mean(ms), 1), "min": min(ms), "max": max(ms)} if ms else None,
        "wall_s": round(wall, 1), "games_per_min_incl_startup": round(n / wall * 60, 1) if wall else None,
        "startup_s": {"mean": round(statistics.mean(b["startup_s"] for b in batches if b.get("startup_s")), 2),
                      "max": max(b["startup_s"] for b in batches if b.get("startup_s"))} if any(b.get("startup_s") for b in batches) else None,
        "batches": batches,
        "games_list": games,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    brief = {k: v for k, v in summary.items() if k not in ("batches", "games_list")}
    print(json.dumps(brief, indent=1))
    return 0 if summary["all_batches_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
