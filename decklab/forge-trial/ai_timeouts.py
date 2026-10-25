"""Count Forge "AI eval thread at timeout" events per game in a matchup's logs.

    python ai_timeouts.py TAG [TAG ...]

Forge's AI gives each spell/attack evaluation 5 s (Game.AI_TIMEOUT); past that it plays nothing at that
priority and prints "AI eval thread at timeout:" + a stack trace (AiController.java:1686). Also counts
"Stopping slow match as draw" (the -c per-game clock). Splits logs into games at "Game Result:" lines;
the game's result comes from the batch JSON (run_sim's corrected classification).
"""
import json, sys, statistics
from pathlib import Path
HERE = Path(__file__).resolve().parent
for tag in sys.argv[1:]:
    s = json.loads((HERE / "results" / "matchups" / tag / "summary.json").read_text(encoding="utf-8"))
    per = []  # (batch, game, n_ai_timeouts, slow_stop, ms, winner)
    by_bg = {(g["batch"], g["game"]): g for g in s["games_list"]}
    for b in s["batches"]:
        n_to = 0; slow = False; gi = 0
        for line in Path(b["log"]).read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("AI eval thread at timeout"):
                n_to += 1
            elif line.startswith("Stopping slow match"):
                slow = True
            elif line.startswith("Game Result:"):
                gi += 1
                g = by_bg.get((b["j"], gi), {})
                per.append((b["j"], gi, n_to, slow, g.get("ms"), g.get("winner"), g.get("result")))
                n_to = 0; slow = False
    aff = [p for p in per if p[2] > 0]
    ms = [p[4] for p in per if p[4]]
    print(f"{tag}: {len(per)} games; games with >=1 AI timeout: {len(aff)} ({100*len(aff)/max(1,len(per)):.1f}%), "
          f"AI timeouts total {sum(p[2] for p in per)}; clock stops: {sum(1 for p in per if p[3])}; "
          f"ms mean {statistics.mean(ms):.0f} median {statistics.median(ms):.0f} p95 {sorted(ms)[int(.95*len(ms))]} max {max(ms)}; "
          f"games > 5 s: {sum(1 for m in ms if m > 5000)}, > 30 s: {sum(1 for m in ms if m > 30000)}")
    if aff:
        wa = sum(1 for p in aff if p[5] == "A"); wb = sum(1 for p in aff if p[5] == "B")
        print(f"   affected games: A won {wa}, B won {wb}, other {len(aff)-wa-wb}")
