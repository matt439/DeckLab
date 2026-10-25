"""The combined run's legs (forge-trial/sim-combined-run.md section 6; wave 3's package H): each a child
process of the controller, using Deck Lab's Python API in-process.

    python decklab/forge-trial/overnight_legs.py <leg> [options]

Every leg writes <out>/result.json (what it measured) and exits 0 when it ran to the end (its numbers
say whether a gate passes: overnight_report judges them), 1 when it couldn't run. A leg stops when
DECKLAB_STOP_FILE exists (runs stop as the page's Stop does, through runner.run once R built it).

Legs not in BUILT_LEGS aren't built yet; the plan skips their items as "not built tonight (harness
leg ...)": none tonight. m6 (D4a's 4-player Commander pods) is in overnight_pods.py."""
import argparse
import gzip
import importlib.util as _import_util
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[1]
M7_INPUTS = HERE / "m7"         # D4b's external decks and published human win rates (daytime research)
sys.path.insert(0, str(TREE))

BUILT_LEGS = ("fake-item", "ignore-stop", "burn", "prepare-inputs", "rounds", "parity", "cardlog-onoff",
              "deck-order", "drift-probe", "offline", "api-field", "adaptive", "idle-close", "server-path",
              "hybrid", "m7", "m6")
WORKLOADS = {"IG": ("casual/izzet-prowess", "casual/gruul-ramp"),
             "RV": ("casual/selesnya-rabbits", "casual/orzhov-vampires"),
             "GF": ("commander/giada-angels", "commander/finneas-rabbits"),
             "AL": ("casual/mono-white-angels", "product/challenger-2019-lightning-aggro"),
             "ZL": ("casual/mono-black-zombies", "product/challenger-2019-lightning-aggro"),
             "IA": ("casual/izzet-prowess", "casual/mono-white-angels")}
LADDER_REFERENCE = {"casual/izzet-prowess": "casual/gruul-ramp", "casual/gruul-ramp": "casual/izzet-prowess",
                    "casual/selesnya-rabbits": "casual/orzhov-vampires",
                    "casual/mono-white-angels": "casual/mono-black-zombies",
                    "casual/mono-black-midrange": "product/challenger-2019-lightning-aggro"}
BASICS = ("Plains", "Island", "Swamp", "Mountain", "Forest")
# the override experiments' opponent for a field list without a ladder reference
OTHER_REFERENCE = {"Constructed": "casual/izzet-prowess", "Commander": "commander/giada-angels"}
COMMANDER_REFERENCE = {"commander/giada-angels": "commander/finneas-rabbits"}
# D2d-p2's profile mirrors (sim-combined-run.md section 6, D2d): (deck, profile). Each arm changes side a of its
# deck's mirror, and side a of its PROFILE_REFERENCE pair (the deck first), so a pilot also has a reference pair.
PROFILE_ARMS = (("casual/selesnya-rabbits", "Reckless"), ("casual/selesnya-rabbits", "DLAggro"),
                ("casual/gruul-ramp", "Reckless"), ("casual/mono-white-angels", "Reckless"),
                ("casual/izzet-prowess", "DLControl"), ("casual/mono-black-midrange", "Cautious"))
PROFILE_REFERENCE = {"casual/selesnya-rabbits": "casual/orzhov-vampires"}
HYBRID_SWITCH = "aisim-hybrid-1"
HYBRID_MIRROR = "casual/mono-black-midrange"
HYBRID_LIMIT = 3.0          # the hybrid's mirror plays only when its games cost at most 3 times plain ones
# D2e (c): (b) plus this profile for this deck, on the deck's pairings
SENSITIVITY_DECK, SENSITIVITY_PROFILE = "casual/selesnya-rabbits", "Reckless"
SENSITIVITY_GAMES = 200


def _write(out, data):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "result.json.tmp"
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, out / "result.json")


def _stop_file():
    path = os.environ.get("DECKLAB_STOP_FILE")
    return Path(path) if path else None


def _stopped():
    path = _stop_file()
    return bool(path and path.exists())


def _config_extra(updates):
    """Merge updates over DECKLAB_CONFIG_EXTRA's file (the smoke's, if any) into a new file, and point
    the variable at it, before decklab is imported."""
    if not updates:
        return
    found = {}
    old = os.environ.get("DECKLAB_CONFIG_EXTRA")
    if old:
        try:
            found = json.loads(Path(old).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            found = {}
    found.update(updates)
    fd, path = tempfile.mkstemp(prefix="overnight-config-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(found, f)
    os.environ["DECKLAB_CONFIG_EXTRA"] = path


def _entry(deck_id):
    from decklab.lib.forge import cli
    return cli._cli_entry(deck_id, False)


def _progress():
    def progress(done, total, detail):
        if _stopped():
            from decklab.lib.forge import common
            raise common.Stopped("Stopped by the combined run's STOP file")
    return progress


def _games_of(result):
    return [game for batch in result.get("batches", []) for game in batch.get("games", [])]


def _parse_rounds(text):
    """"IG800x3,RV400x1" -> [("IG", 800, 3), ("RV", 400, 1)]."""
    out = []
    for part in text.split(","):
        m = re.fullmatch(r"([A-Z]{2})(\d+)x(\d+)", part.strip())
        if not m:
            raise SystemExit(f"Can't read the round {part!r}")
        out.append((m[1], int(m[2]), int(m[3])))
    return out


# ============================================================ tests and drills

def leg_fake_item(args):
    """A stand-in for a command (overnight.py --fake): sleeps, stopping at the STOP file."""
    until = time.monotonic() + args.seconds
    while time.monotonic() < until:
        if _stopped():
            _write(args.out, {"stopped": True})
            return 0
        time.sleep(0.1)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    with open(Path(args.out) / "fake-runs.txt", "a", encoding="utf-8") as f:
        f.write(f"{os.getpid()}\n")
    return 0


def leg_ignore_stop(args):
    """The drill: an item that ignores its STOP file (TerminateJobObject must end it)."""
    time.sleep(args.seconds)
    return 0


def leg_burn(args):
    """A synthetic CPU load of N threads at normal priority (B9's), until killed or STOP."""
    normal = 0x20 if sys.platform == "win32" else 0          # NORMAL_PRIORITY_CLASS: not the leg's BELOW_NORMAL
    procs = [subprocess.Popen([sys.executable, "-c", "while True: pass"], creationflags=normal)
             for _ in range(args.threads)]
    try:
        until = time.monotonic() + args.seconds
        while time.monotonic() < until and not _stopped():
            time.sleep(0.5)
    finally:
        for p in procs:
            p.kill()
    return 0


# ============================================================ inputs (prepare)


_CARD_ROWS = {}


# ============================================================ timing rounds (B)

def leg_rounds(args):
    """Rounds of workloads in one local pool session (B2, B4-B7, B9): round 0 starts the pool (cold),
    later rounds are warm; each round and workload into a fresh results folder, so every round
    plays games 0..N-1 of the same seeds."""
    if args.pin:
        os.environ["DECKLAB_PIN_MODE"] = args.pin
    updates = {}
    if args.workers:
        updates["forge_workers"] = args.workers
    if args.perf == "off":
        updates["forge_performance_mode"] = False
    if args.game_patches == "off":
        updates["forge_game_patches"] = False
    _config_extra(updates)
    burn = None
    if args.load:
        burn = subprocess.Popen([sys.executable, __file__, "burn", "--threads", str(args.load), "--seconds", "86400"])
        time.sleep(3)
    from decklab.lib.forge import pool, runner
    plan = _parse_rounds(args.rounds)
    rows = []
    out = Path(args.out)
    entries = {wl: [_entry(d) for d in WORKLOADS[wl]] for wl, _, _ in plan}
    try:
        with pool.session(local=True) as session:
            for r in range(max(x[2] for x in plan)):
                for wl, games, rounds in plan:
                    if r >= rounds or _stopped():
                        continue
                    a, b = entries[wl]
                    folder = out / f"round{r}" / wl
                    folder.mkdir(parents=True, exist_ok=True)
                    t0 = time.monotonic()
                    result = runner.run(a, b, games, by="overnight", progress=_progress(), results_dir=str(folder),
                                        pool=session, exact=True, seed_base=args.seed_base,
                                        workers=args.workers or None)
                    wall = time.monotonic() - t0
                    played = _games_of(result)
                    ms = [g["ms"] for g in played if isinstance(g.get("ms"), (int, float))]
                    run = (result.get("runs") or [{}])[-1]
                    rows.append({"round": r, "workload": wl, "games": len(played), "wall_s": round(wall, 2),
                                 "games_per_min": round(len(played) / wall * 60, 1) if wall else None,
                                 "median_ms": statistics.median(ms) if ms else None,
                                 "mean_ms": round(statistics.mean(ms), 1) if ms else None,
                                 "ai_timeout_games": sum(1 for g in played if g.get("ai_to")),
                                 "clock_stops": sum(1 for g in played if g.get("r") == "timeout"),
                                 "recycled": run.get("recycled"), "requeued": run.get("requeued"),
                                 "key": result["key"], "engine": result.get("engine"),
                                 "outcomes": [[g.get("g"), g.get("w"), g.get("first"), g.get("rounds"), g.get("r"),
                                               g.get("ai_to") or 0, g.get("turns")] for g in played]})
                    _write(out, {"leg": "rounds", "args": vars(args), "rows": rows})
    finally:
        if burn is not None:
            burn.kill()
    _write(out, {"leg": "rounds", "args": vars(args), "rows": rows, "complete": not _stopped()})
    return 0


# ============================================================ v2 checks (C)

def _check_decks(entries):
    """cardlog-check's deck shape {name: ([Commander lines], [Main lines])} from two entries' .dck text
    (Forge's card names, as runs give them: a double-faced card by its front face)."""
    out = {}
    for i, e in enumerate(entries):
        name = re.sub(r"[^a-z0-9]+", "-", e["id"].split("/")[-1].lower()) + f"-{i}"
        sections, current = {"Commander": [], "Main": []}, None
        for line in e["dck"].splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1]
            elif current in sections and re.match(r"\d+ ", line):
                sections[current].append(line)
        out[name] = (sections["Commander"], sections["Main"])
    return out


def _write_check_decks(folder, decks_):
    for name, (commander, cards) in decks_.items():
        sections = ([("Commander", commander)] if commander else []) + [("Main", cards)]
        text = f"[metadata]\nName={name}\n" + "".join(f"[{s}]\n" + "\n".join(lines) + "\n" for s, lines in sections)
        (folder / f"{name}.dck").write_text(text, encoding="utf-8", newline="\n")


def _check_setup():
    from decklab.lib.forge import install, simjar
    setup = install._setup()
    log = simjar.card_log(setup["java"], setup["forge_dir"], setup["jar"], setup["version"])
    if not log["ready"]:
        raise SystemExit(f"The card log isn't ready: {log.get('problem')}")
    return setup, log


def leg_parity(args):
    """C1: v2 against plain Forge on IG and GF (DeckLabSim with game patches off against plain Forge
    playing each game g alone from its own seed), with W2's masks; a difference is played again (both
    copies), and one that doesn't come back is "unsure"."""
    from decklab.lib.forge import cli, runner
    setup, log = _check_setup()
    legs = [("Constructed", _check_decks([_entry(d) for d in WORKLOADS["IG"]]), args.constructed),
            ("Commander", _check_decks([_entry(d) for d in WORKLOADS["GF"]]), args.commander)]
    folder = Path(tempfile.mkdtemp(prefix="overnight-parity-"))
    found = {}
    try:
        for _, decks_, _ in legs:
            _write_check_decks(folder, decks_)
        env = runner._prepare_user_dir(setup["user_dir"])
        for attempt in (1, 2):
            runs = {k: v for k, v in cli._check_runs(setup, folder, legs, env, log).items() if k[1] in ("off", "plain")}
            done = cli._play_check_runs(setup, folder, env, runs, False)
            for fmt, _, n in legs:
                if attempt == 2 and found.get(fmt, {}).get("kind") != "failed":
                    continue
                plain = [done[fmt, "plain", g][0] for g in range(n)]
                off, reader, _ = done[fmt, "off"]
                problem = cli._leg_problem(setup["version"], fmt, n, plain, off, reader, cli.PARITY)
                kind = problem[0] if problem else "same"
                if attempt == 2:
                    found[fmt]["again"] = kind
                    if kind == "same":
                        found[fmt]["kind"] = "unsure"       # the difference didn't come back
                else:
                    found[fmt] = {"kind": kind, "games": n, "lines": (problem or (None, []))[1][:6]}
            if not args.replay_differences or not any(v["kind"] == "failed" for v in found.values()):
                break
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
        runner._tidy_user_dir(setup["user_dir"])
    _write(args.out, {"leg": "parity", "formats": found,
                      "pass": all(v["kind"] in ("same", "unsure") for v in found.values())})
    return 0


def leg_cardlog_onoff(args):
    """C2: the card log on against off, IG, args.games games as one-shot pairs of 25 (each pair the same
    request with and without the listener); a difference is played again."""
    from decklab.lib.forge import cli, runner, seeds
    setup, log = _check_setup()
    decks_ = _check_decks([_entry(d) for d in WORKLOADS["IG"]])
    folder = Path(tempfile.mkdtemp(prefix="overnight-cardlog-"))
    found = []
    try:
        _write_check_decks(folder, decks_)
        env = runner._prepare_user_dir(setup["user_dir"])
        names, stream = cli._check_sides(decks_, "Constructed")
        chunks = [(first, min(25, args.games - first)) for first in range(0, args.games, 25)]
        for attempt in (1, 2):
            runs = {}
            for first, n in chunks:
                if attempt == 2 and not any(f["first"] == first and f["kind"] == "failed" for f in found):
                    continue
                v2 = {"stream": seeds.stream_hex(stream), "first": first}
                seated = cli._seated(names, first)
                runs["on", first] = ("Constructed", seated, n, log, cli.CHECK_SEED, v2, True)
                runs["nolog", first] = ("Constructed", seated, n, log, cli.CHECK_SEED, dict(v2, card_log=False), True)
            done = cli._play_check_runs(setup, folder, env, runs, False)
            for first, n in chunks:
                if ("on", first) not in done:
                    continue
                on, reader, _ = done["on", first]
                nolog = done["nolog", first][0]
                problem = cli._leg_problem(setup["version"], "Constructed", n, nolog, on, reader, cli.CARD_LOG_LEG)
                kind = problem[0] if problem else "same"
                if attempt == 1:
                    found.append({"first": first, "games": n, "kind": kind, "lines": (problem or (None, []))[1][:4]})
                else:
                    row = next(f for f in found if f["first"] == first)
                    row["again"] = kind
                    if kind == "same":
                        row["kind"] = "unsure"
            if not args.replay_differences or not any(f["kind"] == "failed" for f in found):
                break
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
        runner._tidy_user_dir(setup["user_dir"])
    unsure = sum(1 for f in found if f["kind"] == "unsure")
    _write(args.out, {"leg": "cardlog-onoff", "chunks": found, "unsure_chunks": unsure,
                      "pass": all(f["kind"] in ("same", "unsure") for f in found) and unsure <= 2})
    return 0


RE_DL_ZONE = re.compile(r"DL\|zone\|(\d+)\|[^|]*\|[^|]*\|([^|]*)\|([^|]*)\|(\d+|-)\|(\d+)\|(.*)$")
RE_DL_DECK = re.compile(r"DL\|deck\|(\d+)\|(.*)$")
# A player's name ("Ai(2)-0166ce8ee660"): its suffix follows the deck, so it differs between arms.
RE_PLAYER = re.compile(r"\b(Ai\(\d+\))-[0-9a-f]+")
# The AI's own println about the cards it looks at, which differs with a changed card in hand.
AI_NOISE = " Did not have activator set in SpellAbilityRestriction.canPlay()"
# A resolving effect that searches or reveals a library (Fierce Empath's "you may search your
# library" names no player): its card is the Zone Changer's, else the line's first id.
RE_LIBRARY_EFFECT = re.compile(r"^Resolve Stack: .*\b(?:search|reveal)\w* .*\b(?:your|their) library", re.I)
RE_EFFECT_CARD = re.compile(r"\[Zone Changer: .*\((\d+)\)\]|\((\d+)\)")


def _deck_ids(lines):
    """{seat: [(id, name)]} of a game's DL|deck lines, ids ascending as printed."""
    out = {}
    for line in lines:
        m = RE_DL_DECK.search(line)
        if m:
            out[m[1]] = [(int(i), n) for i, n in (part.split("=", 1) for part in m[2].split(";") if part)]
    return out


def _timed_out(line):
    """A line of the AI's decision timeout, or of the stack trace Forge prints with it."""
    return "TimeoutException" in line or line.startswith("\tat ")


def _searched(line, seat, ids):
    """Whether a (masked) line is seat searching or revealing its library, or a resolving effect
    of one of its cards (ids) that does."""
    if re.search(rf"Ai\({seat}\)\S* (?:searches|reveals)", line, re.I) or f"|Library|Library|{seat}|" in line:
        return True
    if not RE_LIBRARY_EFFECT.match(line.strip()):
        return False
    found = RE_EFFECT_CARD.findall(line)
    card = next((z for z, _ in found if z), None) or next((n for _, n in found if n), None)
    return card is not None and int(card) in ids


def _draws_since_search(game, k, seat, ids):
    """Seat's Library -> Hand moves in game[s + 1:k], s being the last line at or before k + 3
    where seat searched or revealed its library; None when there's no such line."""
    found = [i for i, line in enumerate(game[:k + 4]) if _searched(line, seat, ids)]
    if not found:
        return None
    return sum(1 for line in game[found[-1] + 1:k] if (m := RE_DL_ZONE.search(line))
               and (m[2], m[3], m[4]) == ("Library", "Hand", seat))


def _divergence(base_text, variant_text):
    """How one game's two arms compare (decklab/tests/test_forge_deckorder.divergence, for
    whichever seat's list changed): "same" when they never differ; "seen" when they first differ
    after a card of a changed slot moved; "timed out" when an AI decision timed out at, just after
    or before the first difference; "searched" when they first differ after the changed seat
    searched or revealed its library, before its next draw (CONTRACT-W3.md section 3.7 check 2's
    deviation: a hidden-library read can change the shuffle that follows); None otherwise, or when
    not exactly one seat's list changed. The whole game is cut off at the first difference, so the
    other seat's later draws, made after the change has altered the game, don't count."""
    from decklab.lib.forge import cli
    a, b = base_text.splitlines(), variant_text.splitlines()
    ids_a, ids_b = _deck_ids(a), _deck_ids(b)
    seats = [s for s in sorted(set(ids_a) | set(ids_b)) if ids_a.get(s) != ids_b.get(s)]
    if len(seats) != 1 or len(ids_a[seats[0]]) != len(ids_b.get(seats[0], [])):
        return None
    seat = seats[0]
    changed = {i for (i, x), (_, y) in zip(ids_a[seat], ids_b[seat]) if x != y}

    def kept(game):
        return [RE_PLAYER.sub(r"\1", cli.RE_ORDINAL.sub(r"\g<1>?", cli.RE_TIMING.sub("?", line))) for line in game
                if line.strip() and "DL|deck|" not in line and not line.startswith("WARNING") and AI_NOISE not in line]

    la, lb = kept(a), kept(b)
    k = next((i for i, (x, y) in enumerate(zip(la, lb)) if x != y), None)
    if k is None and len(la) == len(lb):
        return "same"
    k = min(len(la), len(lb)) if k is None else k
    before = la[:k + 1] + lb[:k + 1]     # the differing line too: it may be the changed card's own move
    if any((m := RE_DL_ZONE.search(line)) and int(m[5]) in changed for line in before):
        return "seen"
    after = la[k + 1:k + 4] + lb[k + 1:k + 4]
    if any(_timed_out(line) for line in before + after):
        return "timed out"
    ids = {i for i, _ in ids_a[seat]} | {i for i, _ in ids_b[seat]}
    if 0 in (_draws_since_search(la, k, seat, ids), _draws_since_search(lb, k, seat, ids)):
        return "searched"
    return None


def leg_deck_order(args):
    """C4: CONTRACT-W3.md section 3.7 check 2 through V's real writer: Gruul Ramp against Izzet
    Prowess, args.games v2 games with the base list and with each variant. Each game's arms are
    classed by _divergence(), and the starter is the same in every game."""
    import hashlib
    from decklab.lib.forge import pool, runner, variants
    spec = json.loads(Path(args.variants).read_text(encoding="utf-8"))
    base = _entry("casual/gruul-ramp")
    against = _entry("casual/izzet-prowess")
    out = Path(args.out)
    rows = []
    with pool.session(local=True) as session:
        base_result = runner.run(base, against, args.games, by="overnight", results_dir=str(out / "base"), pool=session,
                                 exact=True, seed_base=11, log_dir=str(out / "logs"), log_every=1)
        for v in ("1", "2"):
            changes = spec[v]
            cards = {sec: [list(x) for x in rows_] for sec, rows_ in base["cards"].items()}
            main = {n: q for q, n in cards.get("Main", [])}
            for q, n in changes["remove"]:
                main[n] = main.get(n, 0) - q
            for q, n in changes["add"]:
                main[n] = main.get(n, 0) + q
            cards["Main"] = [[q, n] for n, q in main.items() if q > 0]
            ventry = variants.variant_entry(base, cards)
            sides = [s["card_sha"] for s in base_result["sides"]]
            base_side = sides.index(base["card_sha"])
            vflip = variants.paired_flip(base_result["seeds"]["flip"], base_side,
                                         0 if ventry["card_sha"] < against["card_sha"] else 1)
            key = hashlib.sha256(f"deck-order:{base_result['key']}:{v}".encode()).hexdigest()
            vres = runner.run(ventry, against, args.games, by="overnight", results_dir=str(out / f"v{v}"),
                              pool=session, exact=True, numbers=list(range(args.games)),
                              seeds=dict(base_result["seeds"], flip=vflip), key=key, kind="experiment",
                              log_dir=str(out / "logs"), log_every=1)
            counts = {"same": 0, "seen": 0, "searched": 0, "timed out": 0, "misaligned": 0, "no log": 0}
            same_start = 0
            base_games = {g["g"]: g for g in _games_of(base_result)}
            def against_started(result, game):
                first = game.get("first")
                return first in (0, 1) and result["sides"][first]["card_sha"] == against["card_sha"]

            for g in _games_of(vres):
                bg = base_games.get(g["g"])
                if bg is None:
                    continue
                same_start += int(against_started(base_result, bg) == against_started(vres, g))
                bt = _log_game(out / "logs" / base_result["key"], g["g"])
                vt = _log_game(out / "logs" / key, g["g"])
                if bt is None or vt is None:
                    counts["no log"] += 1
                    continue
                counts[_divergence(bt, vt) or "misaligned"] += 1
            played = len(_games_of(vres))
            rows.append({"variant": v, "games": args.games, "played": played,
                         "aligned": played - counts["misaligned"] - counts["no log"], "same_starter": same_start,
                         **counts,
                         "pass": (played == args.games and same_start == played and not counts["misaligned"]
                                  and not counts["no log"]
                                  and counts["same"] + counts["seen"] >= (played - counts["timed out"]) // 2)})
    # CONTRACT-W3.md section 3.7 check 2 with J3's deviation (accepted at merge 2): no game misaligned
    # (every game the same, the same until a changed card moved, until the changed seat searched its
    # library, or until an AI decision timed out), the same starter in every game, and at least half
    # the games not timed out the same or the same until the changed card moved.
    _write(out, {"leg": "deck-order", "variants": rows, "pass": all(r["pass"] for r in rows)})
    return 0


def _log_game(folder, g):
    """Game g's text from tee'd chunk logs in folder."""
    for path in Path(folder).glob("*.log.gz"):
        m = re.fullmatch(r"(\d+)-(\d+)\.log\.gz", path.name)
        if m and int(m[1]) <= g <= int(m[2]):
            from decklab.lib.forge import cli
            return cli._soak_game_text(path, g, int(m[1]))
    return None


# ============================================================ D: probes and API legs

def leg_drift_probe(args):
    """A drift probe (section 7.2): IG warm-up untimed, then IG timed into a fresh scratch result,
    through the test server's pool (so every probe plays the same games)."""
    from decklab.lib.forge import pool, runner
    a, b = (_entry(d) for d in WORKLOADS["IG"])
    out = Path(args.out)
    before = _java_pids()
    with pool.session(local=False) as session:
        runner.run(a, b, args.warm_games, by="overnight", progress=_progress(), results_dir=str(out / "warm"),
                   pool=session, exact=True, seed_base=args.seed_base + 1000)
        at_timed = _java_pids()
        t0 = time.monotonic()
        result = runner.run(a, b, args.games, by="overnight", progress=_progress(), results_dir=str(out / "timed"),
                            pool=session, exact=True, seed_base=args.seed_base)
        wall = time.monotonic() - t0
        after = _java_pids()
    ms = [g["ms"] for g in _games_of(result) if isinstance(g.get("ms"), (int, float))]
    run = (result.get("runs") or [{}])[-1]
    # Workers the pool started for this probe (after an experiment's other launch, say) are cold: a
    # worker needs about COLD_GAMES games before its speed settles (Milestone 0), so a probe whose
    # warm-up gave its new workers fewer, or that started one while timing, measured warm-up, not
    # drift (the 2026-10-03 run's probes 1-3: twice the warm probes' time). MG11 leaves it out.
    started_warm = len(at_timed - before) if before is not None and at_timed is not None else None
    started_timed = len(after - at_timed) if at_timed is not None and after is not None else None
    cold = bool(started_timed) or bool(started_warm and args.warm_games / started_warm < COLD_GAMES)
    _write(out, {"leg": "drift-probe", "games": len(ms), "wall_s": round(wall, 2),
                 "median_ms": statistics.median(ms) if ms else None, "pool": run.get("pool"),
                 "workers_started_warm": started_warm, "workers_started_timed": started_timed, "cold": cold})
    return 0


COLD_GAMES = 40                 # games a new worker plays before its speed is judged settled


def _java_pids():
    """The java.exe process ids now (tasklist), or None when they can't be listed."""
    try:
        text = subprocess.run(["tasklist", "/FI", "IMAGENAME eq java.exe", "/FO", "CSV", "/NH"],
                              capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    pids = set()
    for line in text.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            pids.add(int(parts[1]))
    return pids


def _http(port, method, path, body=None, timeout=30):
    import urllib.request
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json", "X-Deck-Lab": "1",
                                          # a script on this PC: it reads as the command line does
                                          "X-Deck-Lab-Script": "1"})
    with urllib.request.urlopen(req, timeout=timeout) as answer:
        return answer.status, json.loads(answer.read() or b"null")


def _wait_up(port, seconds=60):
    """Wait until the server on 127.0.0.1:port answers (its page), up to seconds."""
    import urllib.request
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as answer:
                answer.read(1)
            return True
        except Exception:
            time.sleep(1)
    return False


def leg_api_field(args):
    """D3a-api: an adaptive field run through the test server's API (POST /api/field/run), polled
    until done; the wall time and the view."""
    out = Path(args.out)
    deck_id = args.deck
    from urllib.parse import quote
    profile = None
    try:
        _, people = _http(args.port, "GET", "/api/profiles")
        rows = people.get("profiles") if isinstance(people, dict) else people
        profile = (rows or [{}])[0].get("id") if isinstance((rows or [None])[0], dict) else (rows or [None])[0]
    except Exception:
        pass
    t0 = time.monotonic()
    status, answer = _http(args.port, "POST", "/api/field/run",
                           {"profile": profile, "id": deck_id, "version": "target", "budget": args.budget})
    view = None
    while True:
        if _stopped():
            break
        time.sleep(10)
        try:
            _, view = _http(args.port, "GET", f"/api/field?id={quote(deck_id)}&version=target"
                            + (f"&profile={quote(str(profile))}" if profile else ""))
        except Exception:
            continue
        if (view or {}).get("status") not in ("queued", "running"):
            break
    _write(out, {"leg": "api-field", "post_status": status, "wall_s": round(time.monotonic() - t0, 1), "view": view})
    return 0


def leg_adaptive(args):
    """D3c: assess and ahead runs on the pairs, against fixed counts: the games each used and its verdict."""
    from decklab.lib.forge import adaptive, pool
    out = Path(args.out)
    rows = []
    with pool.session(local=False) as session:
        for wl in args.pairs.split(","):
            a, b = (_entry(d) for d in WORKLOADS[wl])
            for mode in args.modes.split(","):
                if _stopped():
                    break
                t0 = time.monotonic()
                try:
                    result = adaptive.run_adaptive(a, b, mode, by="overnight", progress=_progress(),
                                                   results_dir=str(out / f"{wl}-{mode}"), pool=session,
                                                   seed_base=args.seed_base, max_games=args.max,
                                                   log_dir=args.logs_dir, log_every=10)
                except Exception as e:
                    rows.append({"pair": wl, "mode": mode, "error": f"{type(e).__name__}: {e}"})
                    continue
                summary = (result.get("adaptive") or [{}])[-1]
                rows.append({"pair": wl, "mode": mode, "games": summary.get("games_after"),
                             "outcome": summary.get("outcome"), "decision": summary.get("decision"),
                             "side": summary.get("side"), "sides": [s["card_sha"] for s in result["sides"]],
                             "a_sha": a["card_sha"], "wall_s": round(time.monotonic() - t0, 1)})
                _write(out, {"leg": "adaptive", "rows": rows})
    _write(out, {"leg": "adaptive", "rows": rows})
    return 0


def leg_hybrid(args):
    """D2d-p2h (sim-combined-run.md section 6, D2d: the hybrid AI, speed first; its item is
    exclusive). exp-hybrid.json first, with its control played here rather than taken from
    staging, so the plain and hybrid games ran under the same load and their speed ratio is fair;
    then exp-hybrid-mirror.json (its control from --control-dir) only when hybrid games cost at
    most HYBRID_LIMIT times plain ones. result.json says what ran and why."""
    from decklab.lib.forge import experiment
    inputs, results, logs = Path(args.inputs), Path(args.experiments), Path(args.logs_dir)
    row = {"leg": "hybrid", "limit": HYBRID_LIMIT, "speed": None, "slowdown": None, "mirror": "not played",
           "failed": []}
    spec = experiment.load_spec(inputs / "exp-hybrid.json")
    found = experiment.run(spec, by="overnight", progress=_progress(), results_dir=str(results / "exp-hybrid"),
                           logs_dir=str(logs / "exp-hybrid"), games=args.games)
    row["failed"] += [f"{f['arm']}: {f['error']}" for f in found.get("failed", [])]
    arm = (found.get("arms") or {}).get("hybrid") or {}
    row["speed"] = (arm.get("pooled") or {}).get("speed")
    row["slowdown"] = (row["speed"] or {}).get("slowdown")
    _write(args.out, row)
    mirror = inputs / "exp-hybrid-mirror.json"
    if _stopped():
        row["mirror"] = "not played (stopped)"
    elif not mirror.is_file():
        row["mirror"] = "not played (no exp-hybrid-mirror.json)"
    elif row["slowdown"] is None:
        row["mirror"] = "not played (the speed part has no ratio)"
    elif row["slowdown"] > HYBRID_LIMIT:
        row["mirror"] = f"not played (hybrid games cost {row['slowdown']:.2f} times plain ones, over {HYBRID_LIMIT:g})"
    else:
        found = experiment.run(experiment.load_spec(mirror), by="overnight", progress=_progress(),
                               results_dir=str(results / "exp-hybrid-mirror"), logs_dir=str(logs / "exp-hybrid-mirror"),
                               control_dir=args.control_dir, control_logs_dir=args.control_logs_dir,
                               games=args.mirror_games)
        row["failed"] += [f"{f['arm']}: {f['error']}" for f in found.get("failed", [])]
        row["mirror"] = "played"
    _write(args.out, row)
    return 1 if row["failed"] else 0


def _m7_counts(played, side):
    """A side's games and wins on the play and on the draw, and the games nobody won."""
    play = [g for g in played if g.get("first") == side]
    draw = [g for g in played if g.get("first") == 1 - side]
    return {"play": [len(play), sum(g.get("w") == side for g in play)],
            "draw": [len(draw), sum(g.get("w") == side for g in draw)],
            "no_winner": sum(g.get("w") is None for g in played)}


def _m7_saved(folder):
    """The result already saved in a pair's folder (a restarted leg's), or None."""
    for path in sorted(Path(folder).glob("*.json")) if Path(folder).is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and "batches" in data and "sides" in data:
            return data
    return None


def leg_m7(args):
    """D4b (M7): a round robin of the external decks in --inputs (human.json and the .dck files it
    names), --games a pair in a pool of the leg's own, each pair into its own results folder. A
    restarted leg keeps a pair that has its games. No new pair starts after --max-min minutes (those
    are listed as skipped). overnight_report sets Forge's matrix against the published one."""
    from decklab.lib.forge import pool, runner
    inputs, out = Path(args.inputs), Path(args.out)
    human = json.loads((inputs / "human.json").read_text(encoding="utf-8"))
    ids = [d["id"] for d in human["decks"]]
    entries = {d["id"]: _entry(str(inputs / d["file"])) for d in human["decks"]}
    pairs = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]]
    rows, start = [], time.monotonic()

    def save(complete):
        _write(out, {"leg": "m7", "args": vars(args), "human": human, "rows": rows, "complete": complete})

    with pool.session(local=True) as session:
        for a, b in pairs:
            if _stopped():
                break
            if (time.monotonic() - start) / 60 > args.max_min:
                rows.append({"a": a, "b": b, "skipped": f"over the leg's {args.max_min} minutes"})
                continue
            folder = out / "results" / f"{a}--{b}"
            t0 = time.monotonic()
            result = _m7_saved(folder)
            if result is None or len(_games_of(result)) < args.games:
                missing = args.games - (len(_games_of(result)) if result else 0)
                try:
                    result = runner.run(entries[a], entries[b], missing, by="overnight", progress=_progress(),
                                        results_dir=str(folder), pool=session, exact=True,
                                        seed_base=args.seed_base, workers=args.workers or None)
                except Exception as e:
                    if _stopped():
                        break
                    rows.append({"a": a, "b": b, "error": f"{type(e).__name__}: {e}"})
                    save(False)
                    continue
            played = _games_of(result)
            shas = [s.get("card_sha") for s in result.get("sides", [])]
            side = shas.index(entries[a]["card_sha"]) if entries[a]["card_sha"] in shas else 0
            ms = [g["ms"] for g in played if isinstance(g.get("ms"), (int, float))]
            rows.append(dict({"a": a, "b": b, "games": len(played), "wall_s": round(time.monotonic() - t0, 1),
                              "median_ms": statistics.median(ms) if ms else None,
                              "clock_stops": sum(1 for g in played if g.get("r") == "timeout"),
                              "key": result.get("key"), "engine": result.get("engine")}, **_m7_counts(played, side)))
            save(False)
    save(not _stopped() and len(rows) == len(pairs) and all("games" in r for r in rows))
    return 0


def leg_idle_close(args):
    """D10: a second test server with forge_pool_idle_s = idle_s; IG to warm it; then idle_s + 30 s
    with nothing to play, watching its workers quit; then a timed IG re-warm."""
    _config_extra({"forge_pool_idle_s": args.idle_s})
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    server = subprocess.Popen([sys.executable, str(TREE / "decklab" / "server.py"), "--host", "127.0.0.1", "--port",
                               str(args.port), "--no-update"], cwd=str(TREE), env=env,
                              stdout=open(out / "server-out.txt", "ab"), stderr=subprocess.STDOUT)
    rows, warm_s = [], None
    try:
        _wait_up(args.port)
        from decklab.lib.forge import pool, runner
        a, b = (_entry(d) for d in WORKLOADS["IG"])
        with pool.session(local=False) as session:
            runner.run(a, b, args.games, by="overnight", results_dir=str(out / "warm"), pool=session, exact=True,
                       seed_base=31)
        t0 = time.monotonic()
        quit_at = None
        while time.monotonic() - t0 < args.idle_s + 30 and not _stopped():
            states = [pool.service_status(s) for s in pool.services() if s.get("checkout") == str(TREE)]
            workers = sum(len((st or {}).get("workers") or []) for st in states)
            rows.append({"t": round(time.monotonic() - t0, 1), "workers": workers})
            if workers == 0 and quit_at is None:
                quit_at = time.monotonic() - t0
            time.sleep(1)
        t1 = time.monotonic()
        with pool.session(local=False) as session:
            runner.run(a, b, args.games, by="overnight", results_dir=str(out / "rewarm"), pool=session, exact=True,
                       seed_base=32)
        warm_s = round(time.monotonic() - t1, 1)
    finally:
        subprocess.run([sys.executable, str(TREE / "decklab" / "server.py"), "--stop", "--port", str(args.port)],
                       cwd=str(TREE), capture_output=True, timeout=120)
        try:
            server.wait(30)
        except subprocess.TimeoutExpired:
            server.kill()
    _write(out, {"leg": "idle-close", "idle_s": args.idle_s, "quit_after_s": quit_at, "rewarm_s": warm_s,
                 "samples": rows, "pass": quit_at is not None and quit_at <= args.idle_s + 30 and warm_s is not None})
    return 0


def leg_server_path(args):
    """B3: the CLI submitting to a server pool started by pythonw.exe (plan G13); rounds timed."""
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    exe = sys.executable
    if args.pythonw:
        candidate = Path(exe).with_name("pythonw.exe")
        exe = str(candidate) if candidate.exists() else exe
    server = subprocess.Popen([exe, str(TREE / "decklab" / "server.py"), "--host", "127.0.0.1", "--port",
                               str(args.port), "--no-update"], cwd=str(TREE),
                              stdout=open(out / "server-out.txt", "ab"), stderr=subprocess.STDOUT)
    rows = []
    try:
        _wait_up(args.port)
        from decklab.lib.forge import pool, runner
        for wl, games, rounds in _parse_rounds(args.rounds):
            a, b = (_entry(d) for d in WORKLOADS[wl])
            for r in range(rounds):
                t0 = time.monotonic()
                with pool.session(local=False) as session:
                    result = runner.run(a, b, games, by="overnight", progress=_progress(),
                                        results_dir=str(out / f"round{r}" / wl), pool=session, exact=True,
                                        seed_base=900001, workers=args.workers or None)
                wall = time.monotonic() - t0
                played = _games_of(result)
                rows.append({"round": r, "workload": wl, "games": len(played), "wall_s": round(wall, 2),
                             "games_per_min": round(len(played) / wall * 60, 1) if wall else None,
                             "pool": (result.get("runs") or [{}])[-1].get("pool"),
                             "outcomes": [[g.get("g"), g.get("w"), g.get("first"), g.get("rounds"), g.get("r"),
                                           g.get("ai_to") or 0, g.get("turns")] for g in played]})
    finally:
        subprocess.run([sys.executable, str(TREE / "decklab" / "server.py"), "--stop", "--port", str(args.port)],
                       cwd=str(TREE), capture_output=True, timeout=120)
        try:
            server.wait(30)
        except subprocess.TimeoutExpired:
            server.kill()
    _write(out, {"leg": "server-path", "rows": rows, "ecoqos": None,
                 "note": "EcoQoS per JVM isn't read yet (reported as not checked)"})
    return 0


# ============================================================ E3: offline checks

def _card_data_unchanged(now, recorded):
    """E3 (3): True when the card data's newest file time is A1's, False when it changed, None
    when either is unknown (no card data, or A1 recorded none)."""
    try:
        recorded = float(recorded or 0)
    except (TypeError, ValueError):
        recorded = 0.0
    if now is None or not recorded:
        return None
    return now == recorded


def leg_offline(args):
    """E3 (CPU only): (2) AI-timeout games per 1,000 and recycles from the staged v2 results; (3) the
    card data unchanged since A1. (1), the v3 early numbers recomputed from the tee'd logs, isn't built
    yet: reported as not checked."""
    staging = Path(args.staging)
    games = timeouts = 0
    recycled = {}
    for path in staging.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if "seeds" not in data or data.get("kind"):
            continue
        played = _games_of(data)
        games += len(played)
        timeouts += sum(1 for g in played if g.get("ai_to"))
        for run in data.get("runs", []):
            found = run.get("recycled")
            if isinstance(found, dict):
                for why, n in found.items():
                    recycled[why] = recycled.get(why, 0) + (n if isinstance(n, int) else 0)
            elif isinstance(found, int):
                recycled["all"] = recycled.get("all", 0) + found
    scryfall = TREE / "decklab" / "data" / "scryfall"
    try:
        now = max((p.stat().st_mtime for p in scryfall.iterdir()), default=None)
    except OSError:
        now = None
    _write(args.out, {"leg": "offline", "games": games, "ai_timeout_games": timeouts,
                      "ai_timeouts_per_1000": round(timeouts / games * 1000, 3) if games else None,
                      "recycled": recycled, "card_data_unchanged": _card_data_unchanged(now, args.card_data_mtime),
                      "early_numbers": "not checked (not built in the harness yet)"})
    return 0


# ============================================================ the command line

def leg_m6(args):
    """D4a (M6): 4-player Commander pods, plain Forge cold batches (overnight_pods.py)."""
    sys.path.insert(0, str(HERE))
    import overnight_pods
    return overnight_pods.leg(args, _stopped, lambda data: _write(args.out, data))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="overnight_legs.py")
    sub = parser.add_subparsers(dest="leg", required=True)
    p = sub.add_parser("fake-item")
    p.add_argument("--seconds", type=float, default=1)
    p.add_argument("--out", default=".")
    p = sub.add_parser("ignore-stop")
    p.add_argument("--seconds", type=float, default=300)
    p = sub.add_parser("burn")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--seconds", type=float, default=86400)
    p = sub.add_parser("prepare-inputs")
    p.add_argument("--out", required=True)
    p.add_argument("--results-dir", help="the results whose card stats rank the key cards (main's)")
    p = sub.add_parser("rounds")
    p.add_argument("--out", required=True)
    p.add_argument("--rounds", required=True)
    p.add_argument("--seed-base", type=int, default=900001)
    p.add_argument("--workers", type=int)
    p.add_argument("--pin")
    p.add_argument("--perf")
    p.add_argument("--game-patches")
    p.add_argument("--load", type=int)
    p = sub.add_parser("parity")
    p.add_argument("--out", required=True)
    p.add_argument("--constructed", type=int, default=20)
    p.add_argument("--commander", type=int, default=5)
    p.add_argument("--replay-differences", action="store_true")
    p = sub.add_parser("cardlog-onoff")
    p.add_argument("--out", required=True)
    p.add_argument("--games", type=int, default=200)
    p.add_argument("--replay-differences", action="store_true")
    p = sub.add_parser("deck-order")
    p.add_argument("--out", required=True)
    p.add_argument("--games", type=int, default=20)
    p.add_argument("--variants", required=True)
    p = sub.add_parser("drift-probe")
    p.add_argument("--port", type=int, default=8643)
    p.add_argument("--out", required=True)
    p.add_argument("--seed-base", type=int, default=7)
    p.add_argument("--games", type=int, default=200)
    p.add_argument("--warm-games", type=int, default=100)
    p = sub.add_parser("api-field")
    p.add_argument("--port", type=int, default=8643)
    p.add_argument("--deck", required=True)
    p.add_argument("--budget", default="standard")
    p.add_argument("--out", required=True)
    p = sub.add_parser("adaptive")
    p.add_argument("--out", required=True)
    p.add_argument("--pairs", default="AL,IG,ZL")
    p.add_argument("--modes", default="assess,ahead")
    p.add_argument("--seed-base", type=int, default=3)
    p.add_argument("--logs-dir")
    p.add_argument("--max", type=int, default=3200)
    p = sub.add_parser("hybrid")
    p.add_argument("--inputs", required=True)
    p.add_argument("--experiments", required=True)
    p.add_argument("--logs-dir", required=True)
    p.add_argument("--control-dir")
    p.add_argument("--control-logs-dir")
    p.add_argument("--games", type=int, default=100)
    p.add_argument("--mirror-games", type=int, default=400)
    p.add_argument("--out", required=True)
    p = sub.add_parser("m7")
    p.add_argument("--out", required=True)
    p.add_argument("--inputs", required=True)
    p.add_argument("--games", type=int, default=400)
    p.add_argument("--seed-base", type=int, default=700001)
    p.add_argument("--workers", type=int)
    p.add_argument("--max-min", type=float, default=45)
    p = sub.add_parser("idle-close")
    p.add_argument("--port", type=int, default=8644)
    p.add_argument("--idle-s", type=int, default=120)
    p.add_argument("--out", required=True)
    p.add_argument("--games", type=int, default=200)
    p = sub.add_parser("server-path")
    p.add_argument("--out", required=True)
    p.add_argument("--port", type=int, default=8643)
    p.add_argument("--pythonw", action="store_true")
    p.add_argument("--no-update", action="store_true")
    p.add_argument("--rounds", default="IG800x2")
    p.add_argument("--workers", type=int)
    p = sub.add_parser("offline")
    p.add_argument("--out", required=True)
    p.add_argument("--staging", required=True)
    p.add_argument("--logs")
    p.add_argument("--card-data-mtime", default="0")
    p = sub.add_parser("m6")
    p.add_argument("--out", required=True)
    p.add_argument("--pods", type=int, default=200)
    p.add_argument("--decks", required=True, help="the main series' 4 Commander decks")
    p.add_argument("--compare", help="a compare series' 4 decks, the upgraded deck and its precon first")
    p.add_argument("--compare-pods", type=int, default=0)
    p.add_argument("--per-batch", type=int, default=5, help="pods a Forge process (the seats rotate between)")
    p.add_argument("--procs", type=int, default=16)
    p.add_argument("--clock", type=int, default=600, help="Forge's -c: a game's time limit in seconds")
    p.add_argument("--seed-base", type=int, default=4001)
    args = parser.parse_args(argv)
    if args.leg not in BUILT_LEGS:
        print(f"The leg {args.leg} isn't built yet.", file=sys.stderr)
        return 1
    return globals()["leg_" + args.leg.replace("-", "_")](args)


# Input preparation stays independent of how this script is imported or executed.
_input_spec = _import_util.spec_from_file_location("overnight_inputs", HERE / "overnight_inputs.py")
_inputs = _import_util.module_from_spec(_input_spec)
_input_spec.loader.exec_module(_inputs)
_main_cards = _inputs._main_cards
_is_land = _inputs._is_land
_row_score = _inputs._row_score
_decklist = _inputs._decklist
_current_pilot = _inputs._current_pilot
_experiment_sets = _inputs._experiment_sets


def _override_decks():
    return _inputs._override_decks(globals())


def _is_basic(name):
    return _inputs._is_basic(globals(), name)


def _card_rows(deck_id, results_dir=None):
    return _inputs._card_rows(globals(), deck_id, results_dir)


def _land_names(entry, results_dir=None):
    return _inputs._land_names(globals(), entry, results_dir)


def _card_scores(deck_id, results_dir=None):
    return _inputs._card_scores(globals(), deck_id, results_dir)


def _sets():
    return _inputs._sets(globals())


def leg_prepare_inputs(args):
    return _inputs.leg_prepare_inputs(globals(), args)


def _pilot_specs():
    return _inputs._pilot_specs(globals())


def _sensitivity_specs(sets):
    return _inputs._sensitivity_specs(globals(), sets)


def _copy_m7_inputs(out, source=None):
    return _inputs._copy_m7_inputs(globals(), out, source)


for _input_name in ("_override_decks", "_is_basic", "_card_rows", "_land_names", "_card_scores", "_sets",
                    "leg_prepare_inputs", "_pilot_specs", "_sensitivity_specs", "_copy_m7_inputs"):
    globals()[_input_name].__doc__ = getattr(_inputs, _input_name).__doc__
del _input_name


if __name__ == "__main__":
    sys.exit(main())
