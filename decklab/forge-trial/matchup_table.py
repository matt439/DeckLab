"""Compare pooled Forge matchups (results/matchups/<tag>/summary.json) with the 2026-09-28 report.

    python matchup_table.py TAG [TAG ...] [--json OUT]

The report's numbers are deck A's win % as given in magic/reports/2026-09-28-best-decks.md
(section 1 table) and each deck file's "Head-to-head ... (tested)" table ("original simulator" and
"re-checked simulator" rows). Its simulators alternated who went first, so the Forge figure compared
with them is the play/draw-balanced win rate (mean of A's win rate on the play and on the draw);
"agrees" means the report's range overlaps Forge's 95% interval for that figure.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# deck A's win % in the report: (low, high) over the section-1 table and both simulators
REPORT = {
    ("Mono-White Angels", "owned"): {"range": (50, 54), "text": "Angels 51-53% (table); original sim 50-52%, re-checked 52-54%"},
    ("Mono-White Angels", "target"): {"range": (51, 52), "text": "Angels 51% (table); original sim 51%, re-checked 51-52%"},
    ("Izzet Prowess", "owned"): {"range": (49, 53), "text": "Izzet 49-51% (table); original sim 51-53%, re-checked 51% (49% beginner Izzet)"},
    ("Izzet Prowess", "target"): {"range": (49, 53), "text": "Izzet 49-51% (table); original sim 51-53%, re-checked 51% (49% beginner Izzet)"},
    ("Selesnya Rabbits", "owned"): {"range": (50, 52), "text": "Rabbits 51% (table); original sim 50-51%, re-checked 52%"},
    ("Selesnya Rabbits", "target"): {"range": (51, 52), "text": "Rabbits 51-52% (table); original sim 51%, re-checked 51-52%"},
}


def pct(x):
    return f"{100 * x:.1f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="+")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    rows, out = [], []
    for t in a.tags:
        s = json.loads((HERE / "results" / "matchups" / t / "summary.json").read_text(encoding="utf-8"))
        an, bn = s["a"]["name"], s["b"]["name"]
        version = "owned" if an.endswith("(owned)") else "target"
        key = (an.replace(" (owned)", ""), version)
        rep = REPORT.get(key)
        bal = s["a_winrate_play_draw_balanced"]
        lo, hi = bal["ci95_normal"] if bal else s["a_ci95_wilson"]
        agrees = None
        if rep:
            r0, r1 = rep["range"]
            agrees = r0 / 100 <= hi and r1 / 100 >= lo
        play, drw = s["a_on_play"], s["a_on_draw"]
        rows.append(
            f"| {an} vs {bn} | {s['games']} | {s['a_wins']}-{s['b_wins']} | {s['draws']}/{s['timeouts']}/{s['errors']} | "
            f"{pct(s['a_winrate'])} ({pct(s['a_ci95_wilson'][0])}-{pct(s['a_ci95_wilson'][1])}) | "
            f"{pct(bal['a_winrate'])} ({pct(lo)}-{pct(hi)}) | "
            f"{pct(play['a_winrate'])} ({play['a_wins']}/{play['games']}) | {pct(drw['a_winrate'])} ({drw['a_wins']}/{drw['games']}) | "
            f"{pct(s['starter_winrate'])} | {pct(s['a_as_deck1']['a_winrate'])} / {pct(s['a_as_deck2']['a_winrate'])} | "
            f"{s['rounds']['mean']:.1f} | {rep['text'] if rep else '-'} | {'yes' if agrees else ('NO' if agrees is not None else '-')} |")
        out.append({"tag": t, "a": an, "b": bn, "version": version, "games": s["games"], "a_wins": s["a_wins"],
                    "b_wins": s["b_wins"], "draws": s["draws"], "timeouts": s["timeouts"], "errors": s["errors"],
                    "a_winrate": s["a_winrate"], "a_ci95_wilson": s["a_ci95_wilson"],
                    "a_winrate_balanced": bal["a_winrate"] if bal else None, "a_balanced_ci95": [lo, hi],
                    "a_on_play": play, "a_on_draw": drw, "starter_winrate": s["starter_winrate"],
                    "report": rep, "agrees": agrees})
    print("| Matchup (A vs B) | games | A-B wins | draws/timeouts/errors | A win % (Wilson 95%) | A balanced % (95%) | "
          "A on play % | A on draw % | starter wins % | A as deck 1 / 2 % | mean rounds | report (A win %) | agrees |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    print("\n".join(rows))
    if a.json:
        a.json.write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
