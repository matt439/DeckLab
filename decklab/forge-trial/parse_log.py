"""Turn Forge sim game logs into per-game card events and draft per-card stats (prototype).

Usage
-----
    python parse_log.py LOG [LOG ...] [--events OUT.jsonl] [--json OUT.json]
                        [--source auto|cardlog|plain] [--compare] [--min-games N] [--deck NAME]

    LOG       merged stdout+stderr of a full-log run (run_sim.py without -q), e.g.
              logs/lg-cardlog-n20-s1.log. Several logs can be pooled; decks are matched by their
              Name=, so runs with the deck order swapped pool correctly.
    --events  write one JSON object per game (players, result, mulligans, and a chronological
              "events" list: turns, land drops, casts, discards, deaths, and with a card log every
              card movement) to this file.
    --json    write the per-card stats to this file.
    --source  where per-card stats come from:
                cardlog  the "Information: DL|..." lines that run_sim.py --card-log adds (exact
                         draws, opening hands and end-of-game hands);
                plain    Forge's own log only: a card counts as "seen" when it was played, cast
                         or discarded (a lower bound on "drawn"; cards that stayed in hand are
                         invisible), so only presence-based stats are possible;
                auto     cardlog when every game has DL lines, else plain (default).
    --compare with a card log, also print the plain-log proxy next to the exact numbers.
    --min-games  hide cards seen/drawn in fewer than N games (default 1).
    --deck       only print this deck (Name= from the .dck); repeatable.

What each stat means (cardlog)
    games      games this deck played in the logs.
    drawn G    games in which at least one copy reached the hand (kept opening hand, or moved to
               hand from any zone after the mulligans: draws, tutors, Eternal Witness...).
    WR drawn   deck's win rate in those games; WR not = win rate in games where no copy did.
    copies     copies that reached the hand, summed over games.
    used %     of those copies, the share cast from hand (spells) or played as the land drop
               (lands). Casting a copy from the graveyard (flashback) is counted separately.
    stuck %    of those copies, the share still in hand when the game ended.
    avg rnd    average round of each copy's first cast / land drop; a round is
               ceil(Forge turn / 2), the same count as Forge's "Game Outcome: Turn N".
    Timeouts, errors and draws count as non-wins.

Log lines used (Forge 2.0.15, GameLogFormatter.java and friends; captions from GameLogEntryType):
    Turn: Turn 7 (Ai(1)-Gruul Ramp (owned))
    Mulligan: Ai(1)-... has mulliganed down to 6 cards.   /  Mulligan: Ai(1)-... has kept a hand of 6 cards
    Land: Ai(1)-Gruul Ramp (owned) played Forest (33)
    Add To Stack: Ai(1)-Gruul Ramp (owned) cast Surrak, the Hunt Caller [targeting ...]   (no card id)
    Add To Stack: ... triggered X / activated X
    Discard: Ai(1)-Gruul Ramp (owned) discards Quaketusk Boar (59).
    Zone Change: Scavenging Ooze (12) was put into Exile from Battlefield.
    Information: DL|...   (run_sim.py --card-log only; format in DeckLabSim's source, which is
                          decklab/lib/forge/java/decklab/DeckLabSim.java since Milestone 8)
Results (winner, who went first, rounds, timeouts) come from run_sim.parse, so timeouts and
errors that Forge misreports as wins are handled the same way.

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_sim  # noqa: E402  (same folder; reuse its result parsing)

CAPTIONS = ("Game Outcome", "Match Result", "Turn", "Mulligan", "Ante", "Draft", "Zone Change",
            "Player Control", "Damage", "Life", "Land", "Discard", "Combat", "Information",
            "Resolve Stack", "Add To Stack", "Replacement Effect", "Mana", "Phase")
RE_TURN = re.compile(r"^Turn: Turn (\d+) \(Ai\((\d+)\)-")
RE_MULL = re.compile(r"^Mulligan: Ai\((\d+)\)-.* has mulliganed down to (\d+) cards\.?\s*$")
RE_KEEP = re.compile(r"^Mulligan: Ai\((\d+)\)-.* has kept a hand of (\d+) cards\s*$")
RE_ZONE = re.compile(r"^Zone Change: (.+) \((\d+)\) was put into (\w+) from (\w+)\.\s*$")


def fold(name: str) -> str:
    """Case- and accent-insensitive key, front face only (Forge matches names the same way)."""
    name = name.split(" // ")[0]
    return "".join(ch for ch in unicodedata.normalize("NFKD", name) if not unicodedata.combining(ch)).casefold()


def round_of(turn: int) -> int:
    return (turn + 1) // 2


class Game:
    def __init__(self, players: dict[int, str]):
        self.players = players          # seat -> deck name (Name= of the .dck)
        self.turn = 0
        self.active = None
        self.first = None
        self.mulligans = {s: 0 for s in players}
        self.kept = {}
        self.events: list[dict] = []
        self.deck: dict[int, dict[int, str]] = {}      # seat -> {id: name}   (card log)
        self.hands: dict[str, dict[int, list[int]]] = {}  # "start"/"end" -> seat -> ids (card log)
        self.library_end: dict[int, int] = {}
        self.has_cardlog = False
        self.result: dict = {}

    def ev(self, **kw):
        kw.setdefault("turn", self.turn)
        kw.setdefault("round", round_of(self.turn))
        kw.setdefault("active", self.active)
        self.events.append(kw)


def _prefixes(players: dict[int, str]) -> list[tuple[str, int]]:
    # longest first, so "Ai(1)-X" never matches a longer player name by accident
    return sorted(((f"Ai({s})-{n} ", s) for s, n in players.items()), key=lambda t: -len(t[0]))


def _who(rest: str, prefixes) -> tuple[int | None, str]:
    for p, s in prefixes:
        if rest.startswith(p):
            return s, rest[len(p):]
    return None, rest


def _cardlist(text: str) -> list[tuple[int, str]]:
    out = []
    for part in text.split(";"):
        if part:
            i, _, n = part.partition("=")
            out.append((int(i), n))
    return out


def _dl(g: Game, msg: str):
    f = msg.split("|")
    kind = f[1]
    g.has_cardlog = True
    if kind == "deck":
        g.deck[int(f[2])] = dict(_cardlist("|".join(f[3:])))
    elif kind == "hand":
        g.hands.setdefault(f[3], {})[int(f[4])] = [i for i, _ in _cardlist("|".join(f[5:]))]
    elif kind == "library":
        g.library_end[int(f[4])] = int(f[5])
    elif kind == "zone":
        turn, active, phase, frm, to, owner, cid = f[2:9]
        name = "|".join(f[9:])
        g.events.append({"type": "move", "turn": int(turn), "round": round_of(int(turn)),
                         "active": None if active == "-" else int(active), "phase": phase,
                         "from": frm, "to": to, "seat": int(owner) if owner.isdigit() else None,
                         "id": int(cid), "card": name})


def parse_games(lines: list[str]) -> tuple[dict[int, str], list[Game]]:
    """Split a full Forge sim log into games and extract card events."""
    players: dict[int, str] = {}
    games: list[Game] = []
    started = False
    g = None
    prefixes = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not started:
            m = run_sim.RE_HEADER.match(line)
            if m:
                for pm in re.finditer(r"Ai\((\d+)\)-(.*?)(?: \[[^\]]*\])?(?= vs Ai\(\d+\)-|$)", m[1]):
                    players[int(pm[1])] = pm[2]
                prefixes = _prefixes(players)
                started = True
                g = Game(players)
            continue
        if run_sim.RE_RESULT_WIN.match(line) or run_sim.RE_RESULT_DRAW.match(line):
            games.append(g)
            g = Game(players)
            continue
        cap, sep, msg = line.partition(": ")
        if not sep or cap not in CAPTIONS:
            continue  # combat continuation lines, stack traces, Forge noise
        if cap == "Information" and msg.startswith("DL|"):
            _dl(g, msg)
        elif cap == "Turn":
            m = RE_TURN.match(line)
            if m:
                g.turn, g.active = int(m[1]), int(m[2])
                if g.turn == 1:
                    g.first = g.active
                g.ev(type="turn")
        elif cap == "Mulligan":
            m = RE_MULL.match(line)
            if m:
                g.mulligans[int(m[1])] = g.mulligans.get(int(m[1]), 0) + 1
                continue
            m = RE_KEEP.match(line)
            if m:
                g.kept[int(m[1])] = int(m[2])
        elif cap == "Land":
            seat, rest = _who(msg, prefixes)
            m = re.match(r"^played (.+) \((\d+)\)\s*$", rest)
            if seat and m:
                g.ev(type="land", seat=seat, card=m[1], id=int(m[2]))
        elif cap == "Add To Stack":
            seat, rest = _who(msg, prefixes)
            m = re.match(r"^(cast|triggered|activated) (.+?)(?: targeting .*)?$", rest)
            if seat and m:
                g.ev(type=m[1].replace("triggered", "trigger").replace("activated", "activate"),
                     seat=seat, card=m[2])
        elif cap == "Discard":
            seat, rest = _who(msg, prefixes)
            m = re.match(r"^discards (.+) \((\d+)\)\.\s*$", rest)
            if seat and m:
                g.ev(type="discard", seat=seat, card=m[1], id=int(m[2]))
        elif cap == "Zone Change":
            m = RE_ZONE.match(line)
            if m:
                g.ev(type="leaves_battlefield", card=m[1], id=int(m[2]), to=m[3])
    return players, games


def load(paths: list[Path]) -> list[Game]:
    out = []
    for p in paths:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        players, games = parse_games(lines)
        results = run_sim.parse(lines, len(players))["games"]
        if len(results) != len(games):
            raise SystemExit(f"{p}: {len(games)} game logs but {len(results)} results")
        for g, r in zip(games, results):
            g.result = r
            g.source = str(p)
        out.extend(games)
    return out


# ---------------------------------------------------------------------------------------------
# per-game card facts


def cardlog_facts(g: Game) -> dict[int, dict]:
    """seat -> {"reached": {id}, "used": {id: round}, "graveyard_casts": n by name, "stuck": {id},
    "names": {id: name}} from the DL lines."""
    lands_by_id = {e["id"]: e["round"] for e in g.events if e["type"] == "land"}
    facts = {}
    for seat, deck in g.deck.items():
        reached = set(g.hands.get("start", {}).get(seat, []))
        used: dict[int, int] = {}
        gy_casts = defaultdict(int)
        for e in g.events:
            if e["type"] != "move" or e["id"] not in deck:
                continue
            if e["to"] == "Hand" and e["turn"] >= 1:
                reached.add(e["id"])
            if e["to"] == "Stack":
                if e["from"] == "Hand":
                    used.setdefault(e["id"], e["round"])
                else:
                    gy_casts[deck[e["id"]]] += 1
        for cid, rnd in lands_by_id.items():
            if cid in deck:
                used.setdefault(cid, rnd)
        facts[seat] = {"reached": reached, "used": used, "graveyard_casts": gy_casts,
                       "stuck": set(g.hands.get("end", {}).get(seat, [])), "names": deck}
    return facts


def plain_facts(g: Game) -> dict[int, dict]:
    """seat -> {"seen": {name}, "first_round": {name: round}, "casts": {name: n}} from Forge's own
    lines. "Seen" = played as a land, cast, or discarded; names only (cast lines carry no id)."""
    facts = {s: {"seen": set(), "first_round": {}, "casts": defaultdict(int)} for s in g.players}
    for e in g.events:
        if e["type"] in ("land", "cast", "discard") and e.get("seat") in facts:
            f = facts[e["seat"]]
            f["seen"].add(e["card"])
            if e["type"] in ("land", "cast"):
                f["first_round"].setdefault(e["card"], e["round"])
                if e["type"] == "cast":
                    f["casts"][e["card"]] += 1
    return facts


# ---------------------------------------------------------------------------------------------
# stats


def _new_row():
    return {"games": 0, "drawn_games": 0, "drawn_wins": 0, "not_games": 0, "not_wins": 0,
            "copies": 0, "used": 0, "stuck": 0, "cast_rounds": [], "graveyard_casts": 0,
            "in_deck": 0}


def stats_cardlog(games: list[Game]) -> dict:
    rows: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(_new_row))
    deck_games = defaultdict(lambda: [0, 0])
    names_display = {}
    for g in games:
        facts = cardlog_facts(g)
        for seat, f in facts.items():
            deck = g.players[seat]
            won = g.result.get("winner") == seat
            deck_games[deck][0] += 1
            deck_games[deck][1] += won
            by_name = defaultdict(list)
            for cid, n in f["names"].items():
                by_name[fold(n)].append(cid)
                names_display.setdefault(fold(n), n)
            for key, ids in by_name.items():
                r = rows[deck][key]
                r["games"] += 1
                r["in_deck"] = max(r["in_deck"], len(ids))
                reached = [i for i in ids if i in f["reached"]]
                if reached:
                    r["drawn_games"] += 1
                    r["drawn_wins"] += won
                else:
                    r["not_games"] += 1
                    r["not_wins"] += won
                r["copies"] += len(reached)
                r["used"] += sum(1 for i in reached if i in f["used"])
                r["stuck"] += sum(1 for i in reached if i in f["stuck"])
                r["cast_rounds"] += [f["used"][i] for i in ids if i in f["used"]]
                r["graveyard_casts"] += f["graveyard_casts"].get(f["names"][ids[0]], 0)
    return {"decks": {d: {"games": v[0], "wins": v[1]} for d, v in deck_games.items()},
            "cards": {d: {names_display[k]: v for k, v in sorted(rs.items())} for d, rs in rows.items()}}


def stats_plain(games: list[Game], deck_lists: dict[str, list[str]] | None = None) -> dict:
    """Presence-based proxy: 'drawn' means seen (played/cast/discarded)."""
    rows: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(_new_row))
    deck_games = defaultdict(lambda: [0, 0])
    names_display = {}
    # the card names each deck can have: from the card log's deck lists if any, else whatever
    # was seen for that deck across all games (a card never seen anywhere can't be listed)
    universe: dict[str, set[str]] = defaultdict(set)
    per_game = []
    for g in games:
        facts = plain_facts(g)
        per_game.append((g, facts))
        for seat, f in facts.items():
            deck = g.players[seat]
            for n in f["seen"]:
                universe[deck].add(fold(n))
                names_display.setdefault(fold(n), n)
            for n in g.deck.get(seat, {}).values():
                universe[deck].add(fold(n))
                names_display.setdefault(fold(n), n)
    for g, facts in per_game:
        for seat, f in facts.items():
            deck = g.players[seat]
            won = g.result.get("winner") == seat
            deck_games[deck][0] += 1
            deck_games[deck][1] += won
            seen = {fold(n) for n in f["seen"]}
            first = {fold(n): r for n, r in f["first_round"].items()}
            casts = defaultdict(int)
            for n, c in f["casts"].items():
                casts[fold(n)] += c
            for key in universe[deck]:
                r = rows[deck][key]
                r["games"] += 1
                if key in seen:
                    r["drawn_games"] += 1
                    r["drawn_wins"] += won
                else:
                    r["not_games"] += 1
                    r["not_wins"] += won
                if key in first:
                    r["cast_rounds"].append(first[key])
                r["used"] += casts.get(key, 0)
    return {"decks": {d: {"games": v[0], "wins": v[1]} for d, v in deck_games.items()},
            "cards": {d: {names_display[k]: v for k, v in sorted(rs.items())} for d, rs in rows.items()}}


def _pct(a, b):
    return f"{100 * a / b:5.0f}%" if b else "    - "


def print_table(title: str, st: dict, exact: bool, min_games: int, only: list[str] | None,
                proxy: dict | None = None):
    print(f"\n=== {title} ===")
    for deck, cards in st["cards"].items():
        if only and deck not in only:
            continue
        dg = st["decks"][deck]
        print(f"\n{deck}: {dg['games']} games, {dg['wins']} wins ({_pct(dg['wins'], dg['games']).strip()})")
        if exact:
            hdr = f"{'card':32} {'n':>2} {'drawn G':>7} {'WR drawn':>8} {'WR not':>7} {'diff':>5} {'copies':>6} {'used':>6} {'stuck':>6} {'avg rnd':>7} {'gy':>3}"
            if proxy:
                hdr += f" | {'seen G':>6} {'WR seen':>7} {'WR unseen':>9}"
        else:
            hdr = f"{'card':32} {'seen G':>6} {'WR seen':>7} {'WR unseen':>9} {'diff':>5} {'casts':>5} {'avg rnd':>7}"
        print(hdr)
        order = sorted(cards.items(), key=lambda kv: (-kv[1]["drawn_games"], kv[0]))
        for name, r in order:
            if r["drawn_games"] < min_games:
                continue
            wr_d = r["drawn_wins"] / r["drawn_games"] if r["drawn_games"] else None
            wr_n = r["not_wins"] / r["not_games"] if r["not_games"] else None
            diff = f"{100 * (wr_d - wr_n):+5.0f}" if wr_d is not None and wr_n is not None else "    -"
            avg = f"{sum(r['cast_rounds']) / len(r['cast_rounds']):7.1f}" if r["cast_rounds"] else "      -"
            nm = name if len(name) <= 32 else name[:31] + "~"
            if exact:
                line = (f"{nm:32} {r['in_deck']:>2} {r['drawn_games']:>7} {_pct(r['drawn_wins'], r['drawn_games']):>8} "
                        f"{_pct(r['not_wins'], r['not_games']):>7} {diff} {r['copies']:>6} {_pct(r['used'], r['copies']):>6} "
                        f"{_pct(r['stuck'], r['copies']):>6} {avg} {r['graveyard_casts'] or '':>3}")
                if proxy:
                    pr = proxy["cards"].get(deck, {}).get(name)
                    if pr:
                        line += (f" | {pr['drawn_games']:>6} {_pct(pr['drawn_wins'], pr['drawn_games']):>7} "
                                 f"{_pct(pr['not_wins'], pr['not_games']):>9}")
            else:
                line = (f"{nm:32} {r['drawn_games']:>6} {_pct(r['drawn_wins'], r['drawn_games']):>7} "
                        f"{_pct(r['not_wins'], r['not_games']):>9} {diff} {r['used']:>5} {avg}")
            print(line)


def check_cardlog(games: list[Game]) -> list[str]:
    """Consistency checks of the DL lines against themselves and Forge's own lines."""
    problems = []
    for gi, g in enumerate(games, 1):
        if not g.has_cardlog:
            continue
        # replaying the moves must end with the reported end-of-game hands
        zone = {}
        for seat, deck in g.deck.items():
            for cid in deck:
                zone[cid] = "Library"
        for e in g.events:
            if e["type"] == "move":
                zone[e["id"]] = e["to"]
        for label in ("start", "end"):
            missing = set(g.deck) - set(g.hands.get(label, {}))
            if missing:
                problems.append(f"game {gi}: no {label} hand for seat(s) {sorted(missing)}")
        if set(g.deck) - set(g.library_end):
            problems.append(f"game {gi}: no end library size for seat(s) {sorted(set(g.deck) - set(g.library_end))}")
        for seat, ids in g.hands.get("end", {}).items():
            replay = {cid for cid, z in zone.items() if z == "Hand" and cid in g.deck.get(seat, {})}
            if replay != set(ids):
                problems.append(f"game {gi} seat {seat}: replayed hand {sorted(replay)} != end hand {sorted(ids)}")
        for seat, n in g.library_end.items():
            replay = sum(1 for cid, z in zone.items() if z == "Library" and cid in g.deck.get(seat, {}))
            if replay != n:
                problems.append(f"game {gi} seat {seat}: replayed library {replay} != {n}")
        # kept hand size must match Forge's "has kept a hand of N cards"
        for seat, ids in g.hands.get("start", {}).items():
            if g.kept.get(seat) is not None and g.kept[seat] != len(ids):
                problems.append(f"game {gi} seat {seat}: start hand {len(ids)} != kept {g.kept[seat]}")
        # every land drop in Forge's log is a Hand -> Battlefield move of the same id in the card log
        moves = {(e["id"], e["turn"]) for e in g.events if e["type"] == "move" and e["from"] == "Hand" and e["to"] == "Battlefield"}
        for e in g.events:
            if e["type"] == "land" and (e["id"], e["turn"]) not in moves:
                problems.append(f"game {gi}: land {e['card']} ({e['id']}) turn {e['turn']} has no Hand->Battlefield move")
        # each "cast" line should match a move to the Stack of a card with that name on that turn
        stack = defaultdict(int)
        for e in g.events:
            if e["type"] == "move" and e["to"] == "Stack":
                stack[(fold(e["card"]), e["turn"])] += 1
        casts = defaultdict(int)
        for e in g.events:
            if e["type"] == "cast":
                casts[(fold(e["card"]), e["turn"])] += 1
        for k, n in casts.items():
            if stack.get(k, 0) < n:
                problems.append(f"game {gi}: {n} cast line(s) of {k[0]} on turn {k[1]} but {stack.get(k, 0)} move(s) to Stack")
    return problems


def game_record(g: Game) -> dict:
    rec = {"source": getattr(g, "source", None), "game": g.result.get("game"), "result": g.result.get("result"),
           "winner": g.result.get("winner"), "first": g.first, "rounds": g.result.get("rounds"),
           "turns": g.turn, "players": g.players, "mulligans": g.mulligans, "kept": g.kept,
           "card_log": g.has_cardlog}
    if g.has_cardlog:
        rec["deck"] = {s: d for s, d in g.deck.items()}
        rec["opening_hand"] = {s: [g.deck[s].get(i, "?") for i in ids] for s, ids in g.hands.get("start", {}).items()}
        rec["end_hand"] = {s: [g.deck[s].get(i, "?") for i in ids] for s, ids in g.hands.get("end", {}).items()}
        rec["library_end"] = g.library_end
    rec["events"] = g.events
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Per-game events and per-card stats from Forge sim logs.")
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("--events", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--source", choices=["auto", "cardlog", "plain"], default="auto")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--min-games", type=int, default=1)
    ap.add_argument("--deck", action="append")
    a = ap.parse_args(argv)

    games = load(a.logs)
    n_cardlog = sum(1 for g in games if g.has_cardlog)
    source = a.source
    if source == "auto":
        source = "cardlog" if games and n_cardlog == len(games) else "plain"
    if source == "cardlog" and n_cardlog != len(games):
        raise SystemExit(f"--source cardlog: only {n_cardlog} of {len(games)} games have DL lines")

    res = defaultdict(int)
    for g in games:
        res[g.result.get("result")] += 1
    print(f"{len(games)} games from {len(a.logs)} log(s); results: {dict(res)}; card log in {n_cardlog} games")
    counts = defaultdict(int)
    for g in games:
        for e in g.events:
            counts[e["type"] if e["type"] != "move" else f"move {e['from']}->{e['to']}"] += 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])
    print("events: " + ", ".join(f"{k} {v}" for k, v in top[:14]) + (" ..." if len(top) > 14 else ""))
    if n_cardlog:
        problems = check_cardlog(games)
        print(f"card-log consistency checks: {len(problems)} problem(s)")
        for p in problems[:20]:
            print("  " + p)

    if a.events:
        with open(a.events, "w", encoding="utf-8", newline="\n") as f:
            for g in games:
                f.write(json.dumps(game_record(g), ensure_ascii=False) + "\n")

    if source == "cardlog":
        st = stats_cardlog(games)
        proxy = stats_plain(games) if a.compare else None
        print_table("Per-card stats from the card log (exact)", st, True, a.min_games, a.deck, proxy)
    else:
        st = stats_plain(games)
        print_table("Per-card stats from Forge's own log (proxy: 'seen' = played, cast or discarded)",
                    st, False, a.min_games, a.deck)
    if a.json:
        out = {"source": source, "games": len(games), "logs": [str(p) for p in a.logs], **st}
        a.json.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
