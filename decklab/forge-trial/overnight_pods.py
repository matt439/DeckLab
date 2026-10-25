"""The combined run's 4-player Commander pods (D4a, M6; sim-investigation.md section 5.2): the m6 leg's
games and the report's section and gate.

Pods are plain Forge (-jar, cold) "sim -f Commander" batches of four decks, a few pods a process, each batch
holding one slot of the PC's budget (slots.claim) while its process runs, at most --procs at once. The seat
order rotates between batches (Forge's seat 1 starts almost every game after game 1: formats.md 3.4), so each
deck sits in each seat equally often. 4-player games don't replay exactly once an AI decision times out
(formats.md 3.8), so the numbers are statistics only: minutes per pod, AI timeouts, clock stops (a game the
clock stopped is never a win: Forge then credits a seat anyway, 3.7), and win rates by seat and by deck with
95 % ranges. A compare series (an upgraded deck and its precon in the same pods) adds the difference between
the two. The gate is P3 and never holds up or fails the merge verdict."""
import collections
import json
import math
import os
import re
import statistics
import threading
import time
from pathlib import Path

SEATS = 4
RE_RESULT_WIN = re.compile(r"^Game Result: Game (\d+) ended in (\d+) ms\. Ai\((\d+)\)-.* has won!\s*$")
RE_RESULT_DRAW = re.compile(r"^Game Result: Game (\d+) ended in a Draw! Took (\d+) ms\.\s*$")
RE_OUTCOME = re.compile(r"^Game Outcome: Ai\((\d+)\)-.*? has (won|lost|conceded)\b(?: because)? ?(.*?)\.?\s*$")
RE_TURN = re.compile(r"^Turn: Turn (\d+) \(Ai\((\d+)\)-")
RE_NOLOAD = re.compile(r"^(Could not load deck - .*|No deck found in .*|Unknown AI profile - .*)$")
RE_UNSUPPORTED = re.compile(r'^An unsupported card was requested: "(.*)"')
AI_TIMEOUT = "AI eval thread at timeout"
TAIL_LINES = 20
STAGGER_S = 2.0                 # between the first processes' starts (run)
SLOW_STOP = "Stopping slow match as draw"


# ============================================================ reading a batch's output

class PodReader:
    """One 4-player batch's output, a line at a time (feed), into games: [{"game", "result" ("win", "clock"
    or "draw"), "w" (the winning seat, 1-4; None unless "win"), "ms", "turns", "first" (the seat of turn
    1), "ai_to" (AI decision timeouts in the game), "lost" {seat: why}}]. The AI timeout traces come while a
    game is played and its log after it, so each counts for the game its "Game Result" line ends."""

    def __init__(self):
        self.games, self.load_errors, self.unsupported = [], [], set()
        self.tail = collections.deque(maxlen=TAIL_LINES)     # the last lines, kept for a batch that failed
        self._new()

    def _new(self):
        self._g = {"turns": None, "first": None, "ai_to": 0, "clock": False, "won": set(), "lost": {}}

    def feed(self, line):
        line = line.rstrip("\r\n")
        self.tail.append(line[:300])
        g = self._g
        if AI_TIMEOUT in line:
            g["ai_to"] += 1
        if SLOW_STOP in line:
            g["clock"] = True
        m = RE_TURN.match(line)
        if m:
            n, seat = int(m[1]), int(m[2])
            g["turns"] = max(g["turns"] or 0, n)
            if n == 1:
                g["first"] = seat
            return
        m = RE_OUTCOME.match(line)
        if m:
            if m[2] == "won":
                g["won"].add(int(m[1]))
            else:
                g["lost"][int(m[1])] = m[3] or m[2]
            return
        m = RE_RESULT_WIN.match(line)
        if m:
            clock = g["clock"] or len(g["won"]) > 1        # a stopped game names every survivor a winner
            self._end(int(m[1]), int(m[2]), "clock" if clock else "win", None if clock else int(m[3]))
            return
        m = RE_RESULT_DRAW.match(line)
        if m:
            self._end(int(m[1]), int(m[2]), "clock" if g["clock"] else "draw", None)
            return
        m = RE_NOLOAD.match(line)
        if m:
            self.load_errors.append(m[1][:300])
            return
        m = RE_UNSUPPORTED.match(line)
        if m:
            self.unsupported.add(m[1])

    def _end(self, number, ms, result, winner):
        g = self._g
        self.games.append({"game": number, "result": result, "w": winner, "ms": ms, "turns": g["turns"],
                           "first": g["first"], "ai_to": g["ai_to"], "lost": {str(k): v for k, v in g["lost"].items()}})
        self._new()


# ============================================================ the batches

def rotation(decks, k):
    """decks in seat order for rotation k: the list turned left k places (k=1: B, C, D, A)."""
    k %= len(decks)
    return list(decks[k:]) + list(decks[:k])


def batches(series, decks, pods, per_batch, seed_base):
    """[{"series", "batch", "seats", "pods", "seed"}]: pods split into batches of per_batch (the last one
    smaller), the seat order rotating one place each batch."""
    out, left, b = [], int(pods), 0
    while left > 0:
        n = min(per_batch, left)
        out.append({"series": series, "batch": b, "seats": rotation(decks, b), "pods": n, "seed": seed_base + b})
        left -= n
        b += 1
    return out


def command(setup, dck_names, pods, seed, clock_s):
    """Plain Forge's command line for one batch of 4-player Commander pods (run in setup["forge_dir"])."""
    from decklab.lib.forge import runner
    return [*runner._java(setup), "-jar", str(setup["jar"]), "sim", "-D", str(setup["decks_dir"]), "-d", *dck_names,
            "-n", str(pods), "-s", str(seed), "-f", "Commander", "-c", str(clock_s)]


def _real_start(argv, cwd, env):
    from decklab.lib.forge import processes
    return processes.start_process(argv, cwd=cwd, env=env)


def _real_kill(proc):
    from decklab.lib.forge import processes
    processes.kill_process(proc)


def _real_claim(cancel, what):
    """One slot of the PC's budget, waiting for it (None once cancel is set)."""
    from decklab.lib.forge import slots
    try:
        return slots.claim(1, wait=True, cancel=cancel, what=what)
    except slots.Cancelled:
        return None


def run(jobs, *, setup, env, dck_of, procs, clock_s, stopped, save, start=None, kill=None, claim=None,
        batch_timeout_s=None, stagger_s=STAGGER_S):
    """Play jobs (batches()) at most procs at once, each in a slot; dck_of[deck id] is its .dck file name.
    stopped() is polled about once a second: once true, running processes are killed and their finished
    games kept, and no new batch starts. save(done) is called after every batch with the batches so far.
    The first processes start stagger_s apart (cold JVMs starting at the same instant can fail: one of four
    did in the smoke), and a batch that ends without a game, unstopped, is played once more.
    Returns the batches: each job with "games", "load_errors", "unsupported", "exit", "killed", "wall_s"."""
    start, kill, claim = start or _real_start, kill or _real_kill, claim or _real_claim
    lock = threading.Lock()
    queue = list(jobs)
    done = []
    cancel = threading.Event()
    timeout = batch_timeout_s or max(1800, 4 * clock_s * 1.0)   # per pod: a game can't outlast its clock much

    def worker(k):
        if cancel.wait(stagger_s * k):
            return
        while not cancel.is_set():
            with lock:
                if not queue:
                    return
                job = queue.pop(0)
            lease = claim(cancel, f"m6 pods {job['series']} {job['batch']}")
            if lease is None or cancel.is_set():
                if lease is not None:
                    lease.release()
                return
            reader, began, killed, code = PodReader(), time.monotonic(), None, None
            try:
                argv = command(setup, [dck_of[d] for d in job["seats"]], job["pods"], job["seed"], clock_s)
                proc = start(argv, str(setup["forge_dir"]), env)
                limit = began + timeout * job["pods"]

                def watch():
                    nonlocal killed
                    while proc.poll() is None:
                        if cancel.is_set() or time.monotonic() > limit:
                            killed = "stopped" if cancel.is_set() else "batch timeout"
                            kill(proc)
                            return
                        time.sleep(0.5)
                watcher = threading.Thread(target=watch, daemon=True)
                watcher.start()
                for line in proc.stdout:
                    reader.feed(line)
                code = proc.wait()
                proc.stdout.close()
                watcher.join(5)
            except OSError as e:
                killed = f"couldn't start: {e}"
            finally:
                lease.release()
            row = dict(job, games=reader.games, load_errors=reader.load_errors[:10],
                       unsupported=sorted(reader.unsupported)[:20], exit=code, killed=killed,
                       wall_s=round(time.monotonic() - began, 1))
            failed = killed or code not in (0, None) or not reader.games
            if failed:
                row["tail"] = list(reader.tail)
            with lock:
                if failed and not cancel.is_set() and not job.get("attempt") and not reader.games and not killed:
                    # a process that ended without a game (a cold start racing another's) is played once more
                    queue.append(dict(job, attempt=1, first_try={"exit": code, "tail": row["tail"][-8:]}))
                    continue
                done.append(row)
                save(list(done))

    threads = [threading.Thread(target=worker, args=(k,), daemon=True) for k in range(max(1, int(procs)))]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        if stopped():
            cancel.set()                # each batch's watcher kills its process within half a second
        for t in threads:
            t.join(1.0 / len(threads))
    return sorted(done, key=lambda r: (r["series"], r["batch"]))


# ============================================================ the numbers

def _wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def _rate(k, n):
    return {"wins": k, "pods": n, "rate": round(k / n, 4) if n else None, "range": _wilson(k, n)}


def _pods(rows):
    return [dict(g, seats=r["seats"]) for r in rows for g in r.get("games", [])]


def summary(rows, series, pair=None):
    """One series' numbers from its batches (rows): pods, minutes per pod, AI timeouts, clock stops, draws, and
    win rates by seat and by deck over the pods that ended with a result (clock stops left out), each with a
    95 % Wilson range. pair (two deck ids that share the series' pods): their win rates and the difference
    (a multinomial standard error: the two can't both win a pod)."""
    rows = [r for r in rows if r["series"] == series]
    games = _pods(rows)
    counted = [g for g in games if g["result"] != "clock"]
    minutes = sorted(g["ms"] / 60000.0 for g in games)
    decks = []
    for r in rows:
        for d in r["seats"]:
            if d not in decks:
                decks.append(d)
    out = {"series": series, "batches": len(rows), "pods": len(games), "counted": len(counted),
           "wins": sum(g["result"] == "win" for g in counted), "draws": sum(g["result"] == "draw" for g in counted),
           "clock_stops": len(games) - len(counted),
           "ai_timeouts": sum(g["ai_to"] for g in games), "ai_timeout_pods": sum(g["ai_to"] > 0 for g in games),
           "failed_batches": sum(1 for r in rows if r.get("killed") or r.get("load_errors") or r.get("exit") not in (0, None)
                                 or (not r.get("games") and r.get("pods"))),
           "load_errors": sorted({e for r in rows for e in r.get("load_errors", [])})[:5],
           "unsupported": sorted({e for r in rows for e in r.get("unsupported", [])})[:10],
           "wall_s": round(sum(r.get("wall_s") or 0 for r in rows), 1)}
    if minutes:
        out["minutes_per_pod"] = {"mean": round(statistics.mean(minutes), 2), "median": round(statistics.median(minutes), 2),
                                  "p90": round(minutes[min(len(minutes) - 1, int(0.9 * len(minutes)))], 2),
                                  "max": round(minutes[-1], 2)}
        turns = [g["turns"] for g in games if g.get("turns")]
        if turns:
            out["turns"] = {"mean": round(statistics.mean(turns), 1), "max": max(turns)}
    out["by_seat"] = {str(s): _rate(sum(g["w"] == s for g in counted), len(counted)) for s in range(1, SEATS + 1)}
    out["first_by_seat"] = {str(s): sum(g.get("first") == s for g in games) for s in range(1, SEATS + 1)}
    out["by_deck"] = {}
    for d in decks:
        mine = [g for g in counted if d in g["seats"]]
        out["by_deck"][d] = _rate(sum(g["w"] is not None and g["seats"][g["w"] - 1] == d for g in mine), len(mine))
    if pair and all(d in decks for d in pair):
        both = [g for g in counted if all(d in g["seats"] for d in pair)]
        n = len(both)
        a = sum(g["w"] is not None and g["seats"][g["w"] - 1] == pair[0] for g in both)
        b = sum(g["w"] is not None and g["seats"][g["w"] - 1] == pair[1] for g in both)
        cmp_ = {"decks": list(pair), "pods": n, "a": _rate(a, n), "b": _rate(b, n), "head_to_head": _rate(a, a + b)}
        if n:
            pa, pb = a / n, b / n
            se = math.sqrt(max(0.0, pa + pb - (pa - pb) ** 2) / n)
            cmp_["difference"] = {"value": round(pa - pb, 4), "range": [round(max(-1.0, pa - pb - 1.96 * se), 4),
                                                                       round(min(1.0, pa - pb + 1.96 * se), 4)]}
        out["compare"] = cmp_
    return out


# ============================================================ the report's section and gate

def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def gate(out, state, plan, needs, gate_):
    """The report's optional gate M6 (D4a, P3): "pass" when the main series played at least half its pods
    with no batch that failed to load its decks and clock stops in at most 10 % of pods; else "not checked"
    with why (a problem is reported, never a FAIL: the gate doesn't hold up the merge verdict either way)."""
    missing = needs(state, plan, "D4a")
    if missing:
        return missing
    found = _read(Path(out) / "D" / "m6" / "result.json") or {}
    main = (found.get("summaries") or {}).get("main")
    if not main:
        return gate_("not checked", "D4a wrote no result")
    planned = (found.get("planned") or {}).get("main") or main["pods"]
    nums = {"pods": main["pods"], "planned": planned, "clock_stops": main["clock_stops"],
            "ai_timeout_pods": main["ai_timeout_pods"], "failed_batches": main["failed_batches"],
            "minutes_per_pod": (main.get("minutes_per_pod") or {}).get("mean")}
    problems = []
    if main["pods"] < planned / 2:
        problems.append(f"{main['pods']} of {planned} pods played")
    if main["load_errors"]:
        problems.append("decks didn't load: " + "; ".join(main["load_errors"][:2]))
    if main["pods"] and main["clock_stops"] > 0.1 * main["pods"]:
        problems.append(f"clock stops in {main['clock_stops']} of {main['pods']} pods")
    detail = (f"{main['pods']} pods, {nums['minutes_per_pod']} min a pod, {main['clock_stops']} clock stops, "
              f"AI timeouts in {main['ai_timeout_pods']} pods")
    if problems:
        return gate_("not checked", "; ".join(problems) + f" ({detail}); optional, never blocks", nums)
    return gate_("pass", detail + "; optional, never blocks", nums)


def _pct(r):
    if not r or r.get("rate") is None:
        return "-"
    lo, hi = r["range"]
    return f"{100 * r['rate']:.0f} % ({100 * lo:.0f}-{100 * hi:.0f}), {r['wins']}/{r['pods']}"


def markdown(out):
    """The report's section 13 for M6: [] when D4a wrote nothing."""
    found = _read(Path(out) / "D" / "m6" / "result.json")
    if not found or not found.get("summaries"):
        return []
    lines = ["", "## 4-player Commander pods (D4a, M6; optional)", "",
             "Plain Forge 4-player pods, seats rotated between batches. 4-player games don't replay exactly once an "
             "AI decision times out, so these are statistics only. Win rates leave clock stops out; ranges are 95 % "
             "(Wilson). An even pod is 25 % a seat."]
    if found.get("stopped"):
        lines += ["", f"Stopped before the end ({found['stopped']}): the pods it finished are counted."]
    for name, s in found["summaries"].items():
        mpp = s.get("minutes_per_pod") or {}
        lines += ["", f"### Series: {name}", "",
                  f"{s['pods']} pods in {s['batches']} batches (planned {(found.get('planned') or {}).get(name)}); "
                  f"minutes a pod: mean {mpp.get('mean')}, median {mpp.get('median')}, 90th percentile {mpp.get('p90')}, "
                  f"max {mpp.get('max')}; turns mean {(s.get('turns') or {}).get('mean')}. Clock stops {s['clock_stops']}, "
                  f"draws {s['draws']}, AI timeouts {s['ai_timeouts']} in {s['ai_timeout_pods']} pods, failed batches "
                  f"{s['failed_batches']}.", "", "| Seat | Wins | Went first |", "|---|---|---|"]
        for seat, r in s["by_seat"].items():
            lines.append(f"| {seat} | {_pct(r)} | {s['first_by_seat'].get(seat)} |")
        lines += ["", "| Deck | Wins |", "|---|---|"]
        for deck, r in s["by_deck"].items():
            lines.append(f"| {deck} | {_pct(r)} |")
        c = s.get("compare")
        if c:
            diff = c.get("difference") or {}
            rng = diff.get("range") or [None, None]
            lines += ["", f"Upgraded against precon in the same pods ({c['decks'][0]} against {c['decks'][1]}, "
                          f"{c['pods']} pods): {_pct(c['a'])} against {_pct(c['b'])}; difference "
                          f"{diff.get('value')} (95 %: {rng[0]} to {rng[1]}); of the pods one of the two won, the "
                          f"upgraded deck won {_pct(c['head_to_head'])}."]
        if s.get("load_errors") or s.get("unsupported"):
            lines += ["", f"Load errors: {s.get('load_errors')}; unsupported cards: {s.get('unsupported')}."]
    return lines


# ============================================================ the leg

def leg(args, stopped, write):
    """The m6 leg: the main series (--decks, --pods) and, with --compare, the compare series (its first two
    decks the upgraded deck and its precon), into args.out/result.json (rewritten after every batch)."""
    from decklab.lib.forge import cli, install, runner
    decks = [d.strip() for d in args.decks.split(",") if d.strip()]
    series = [("main", decks, args.pods, None)]
    if args.compare and args.compare_pods:
        cmp_decks = [d.strip() for d in args.compare.split(",") if d.strip()]
        series.append(("compare", cmp_decks, args.compare_pods, cmp_decks[:2]))
    for name, ds, _, _ in series:
        if len(ds) != SEATS or len(set(ds)) != SEATS:
            raise SystemExit(f"The {name} series needs {SEATS} different decks, not {ds}")
    found = {"leg": "m6", "decks": {n: ds for n, ds, _, _ in series}, "planned": {n: p for n, _, p, _ in series},
             "per_batch": args.per_batch, "procs": args.procs, "clock_s": args.clock, "skipped": {}}
    entries, playable = {}, []
    for name, ds, pods, pair in series:
        try:
            for d in ds:
                if d not in entries:
                    entries[d] = cli._cli_entry(d, False)
                    if entries[d].get("kind") != "commander":
                        raise ValueError(f"{d} isn't a Commander list")
            playable.append((name, ds, pods, pair))
        except (Exception, SystemExit) as e:          # a series whose decks don't load is skipped, said why
            found["skipped"][name] = f"{type(e).__name__}: {e}"
    if not playable:
        found["error"] = "no series' decks load"
        write(found)
        return 1
    setup = install._setup()
    used = {d for _, ds, _, _ in playable for d in ds}
    runner._write_decks(setup["decks_dir"], [entries[d] for d in used])
    dck_of = {d: runner._dck_name(entries[d]) for d in used}
    found["titles"] = {d: entries[d].get("title") for d in used}
    env = runner._prepare_user_dir(setup["user_dir"])
    jobs = []
    for i, (name, ds, pods, _) in enumerate(playable):
        jobs += batches(name, ds, pods, args.per_batch, args.seed_base + 1000 * i)
    began = time.time()

    def save(rows):
        found["batches"] = rows
        found["summaries"] = {n: summary(rows, n, pair) for n, _, _, pair in playable}
        found["elapsed_s"] = round(time.time() - began, 1)
        write(found)

    save([])
    try:
        rows = run(jobs, setup=setup, env=env, dck_of=dck_of, procs=args.procs, clock_s=args.clock, stopped=stopped,
                   save=save)
    finally:
        runner._tidy_user_dir(setup["user_dir"])
    if stopped():
        found["stopped"] = "the STOP file"
    save(rows)
    return 0
