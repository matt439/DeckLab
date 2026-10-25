"""Count how often Forge's AI cast / played each card of a matchup (plain Forge logs, no card log).

    python cast_counts.py TAG [--min-copies 1] [--json OUT]

Reads results/matchups/<tag>/summary.json and every batch log it lists, splits each log into
games at "Game Result:" lines, and for each deck (matched by the player name "Ai(n)-<Name=>")
counts per card name: games in which it was cast (Add To Stack: <player> cast <Card>) or played as
a land (Land: <player> played <Card> (id)), total casts, and the deck's win rate in games where
it was / wasn't cast. Every card of the .dck is listed, so a card that is never cast shows 0.

Cards that are drawn but never cast can only be told apart from cards that are just not drawn
with the card log (run_sim.py --card-log + parse_log.py); this is the quick first look.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RE_CAST = re.compile(r"^Add To Stack: Ai\((\d+)\)-.*? cast (.+?)(?: targeting .*)?\s*$")
RE_LAND = re.compile(r"^Land: Ai\((\d+)\)-.*? played (.+?) \(\d+\)\s*$")
RE_WIN = re.compile(r"^Game Result: Game \d+ ended in \d+ ms\. Ai\((\d+)\)-")
RE_PLAYER = re.compile(r"Ai\((\d+)\)-(.*?)(?: \[[^\]]*\])?(?= vs Ai\(\d+\)-| - .+ games? of )")


def deck_cards(dck: Path) -> dict[str, int]:
    cards, main = {}, False
    for line in dck.read_text(encoding="utf-8").splitlines():
        if line.startswith("["):
            main = line.strip().lower() == "[main]"
            continue
        m = re.match(r"^(\d+) (.+)$", line.strip())
        if main and m:
            cards[m[2]] = cards.get(m[2], 0) + int(m[1])
    return cards


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    s = json.loads((HERE / "results" / "matchups" / a.tag / "summary.json").read_text(encoding="utf-8"))
    decks = {s["a"]["name"]: deck_cards(Path(s["a"]["dck"])), s["b"]["name"]: deck_cards(Path(s["b"]["dck"]))}
    stats = {d: defaultdict(lambda: {"games_cast": 0, "casts": 0, "wins_cast": 0}) for d in decks}
    games = {d: 0 for d in decks}
    wins = {d: 0 for d in decks}
    for b in s["batches"]:
        lines = Path(b["log"]).read_text(encoding="utf-8", errors="replace").splitlines()
        seat = {}
        for line in lines:
            if " games of " in line or " game of " in line:
                for m in RE_PLAYER.finditer(line):
                    seat[m[1]] = m[2]
                if seat:
                    break
        cur = {n: defaultdict(int) for n in seat}
        for line in lines:
            m = RE_CAST.match(line) or RE_LAND.match(line)
            if m and m[1] in cur:
                name = m[2].strip()
                cur[m[1]][name] += 1
                continue
            if line.startswith("Game Result:"):
                w = RE_WIN.match(line)
                winner = w[1] if w else None
                for n, deck in seat.items():
                    games[deck] += 1
                    won = winner == n
                    wins[deck] += won
                    for card, c in cur[n].items():
                        st = stats[deck][card]
                        st["games_cast"] += 1
                        st["casts"] += c
                        st["wins_cast"] += won
                cur = {n: defaultdict(int) for n in seat}
    out = {}
    for deck, cards in decks.items():
        print(f"\n{deck}: {games[deck]} games, {wins[deck]} wins ({100 * wins[deck] / max(1, games[deck]):.1f}%)")
        print(f"{'card':34s} {'n':>2s} {'games cast':>10s} {'% games':>7s} {'casts':>6s} {'WR cast':>7s} {'WR not':>7s}")
        rows = []
        for card, n in cards.items():
            st = stats[deck].get(card, {"games_cast": 0, "casts": 0, "wins_cast": 0})
            g, gc = games[deck], st["games_cast"]
            wr_c = st["wins_cast"] / gc if gc else None
            wr_n = (wins[deck] - st["wins_cast"]) / (g - gc) if g - gc else None
            rows.append({"card": card, "n": n, "games_cast": gc, "pct_games": gc / g if g else None,
                         "casts": st["casts"], "wr_cast": wr_c, "wr_not": wr_n})
        rows.sort(key=lambda r: (r["pct_games"] or 0) / r["n"])
        for r in rows:
            f = lambda x: f"{100 * x:6.1f}%" if x is not None else "     - "
            print(f"{r['card'][:34]:34s} {r['n']:2d} {r['games_cast']:10d} {f(r['pct_games'])} {r['casts']:6d} {f(r['wr_cast'])} {f(r['wr_not'])}")
        out[deck] = {"games": games[deck], "wins": wins[deck], "cards": rows}
    if a.json:
        a.json.write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
