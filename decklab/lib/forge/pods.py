"""Four-player Commander samples, isolated from all head-to-head results.

Callers authorize and resolve all four entries first. Planning is pure when an
engine identity is supplied; engine_identity inspects the installed engine without
starting Java or preparing its folders. Runs use cold Forge processes, one shared
worker-budget lease each, and keep finished games on cooperative cancellation.
"""
import hashlib
import json
import math
import queue
import re
import threading
import time
from collections import deque
from pathlib import Path

from decklab.lib.gauntlet import pod_lineups

from . import common, engine, install, lifecycle, processes, runner, slots

VERSION = 1
SEATS = 4
GAMES = (16, 32, 64, 128)
DEFAULT_GAMES = 16
PER_BATCH = 4
DEFAULT_CLOCK = 180
DEFAULT_SEED = 1000000
MAX_PROCS = 4
POLL_S = 0.2
START_GAP = 2.0
KILL_WAIT = 10
MAX_SAVED_BYTES = 2 * 1024 * 1024
KEY_RE = re.compile(r"[0-9a-f]{64}")
NOTE = ("Four-player games do not replay exactly after an AI decision timeout. "
        "These are statistics only. Win shares count finished wins and draws; clock stops "
        "are excluded. Ranges are 95% Wilson intervals.")
UNREADABLE = "This pod run's saved results cannot be read safely."
STALE = "The decks or Forge engine changed. Review a fresh pod plan before starting."

RE_WIN = re.compile(r"^Game Result: Game (\d+) ended in (\d+) ms\. Ai\((\d+)\)-.* has won!\s*$")
RE_DRAW = re.compile(r"^Game Result: Game (\d+) ended in a Draw! Took (\d+) ms\.\s*$")
RE_OUTCOME = re.compile(r"^Game Outcome: Ai\((\d+)\)-.*? has (won|lost|conceded)\b")
RE_TURN = re.compile(r"^Turn: Turn (\d+) \(Ai\((\d+)\)-")
RE_NOLOAD = re.compile(r"^(Could not load deck - |No deck found in |Unknown AI profile - )")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def check(entries):
    """Exactly four distinct Commander entries, or a safe ValueError sentence."""
    if not isinstance(entries, (list, tuple)) or len(entries) != SEATS:
        raise ValueError("Choose exactly four different Commander decks.")
    chosen, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("kind") != "commander":
            raise ValueError("Every deck in a pod must be a Commander deck.")
        deck_id = entry.get("id")
        if not isinstance(deck_id, str) or not deck_id or deck_id in seen:
            raise ValueError("Choose exactly four different Commander decks.")
        if (entry.get("version") not in ("target", "owned") or
                not isinstance(entry.get("card_sha"), str) or not KEY_RE.fullmatch(entry["card_sha"])):
            raise ValueError("A pod deck's current list could not be confirmed.")
        seen.add(deck_id)
        chosen.append(entry)
    return chosen


def _options(games, clock_s, seed_base):
    if type(games) is not int or games not in GAMES:
        raise ValueError("Choose 16, 32, 64 or 128 pod games.")
    if type(clock_s) is not int or not 1 <= clock_s <= 3600:
        raise ValueError("A pod game's clock must be between 1 and 3600 seconds.")
    if type(seed_base) is not int or not 0 <= seed_base <= 1000000000:
        raise ValueError("A pod seed must be a whole number between 0 and 1000000000.")
    return {"games": games, "clock_s": clock_s, "seed_base": seed_base, "per_batch": PER_BATCH}


def _sides(entries):
    keys = ("id", "version", "title", "kind", "card_sha")
    optional = ("target_bracket", "precon_source")
    return [{**{key: entry.get(key) for key in keys}, **{key: entry[key] for key in optional if key in entry}}
            for entry in entries]


_hash_lock = threading.Lock()
_hashes = {}


def _jar_sha(path):
    info = path.stat()
    stamp = (info.st_size, info.st_mtime_ns)
    with _hash_lock:
        known = _hashes.get(str(path))
    if known and known[0] == stamp:
        return known[1]
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    value = digest.hexdigest()
    with _hash_lock:
        _hashes[str(path)] = (stamp, value)
    return value


def engine_identity(setup=None):
    """Read-only actual plain-Forge provenance; no cached-away install fallback."""
    try:
        if setup is None:
            settings = common._settings()
            folder = Path(settings["forge_dir"])
            jar, version = install._find_jar(folder)
            if jar is None or install.find_java(settings.get("forge_java")) is None:
                raise common.ForgeError("Forge and Java must be installed before planning pod games.")
            performance_mode = settings.get("forge_performance_mode", True) is not False
            user_dir = engine._read_only_user_dir(performance_mode)
        else:
            folder, jar, version = Path(setup["forge_dir"]), setup["jar"], setup["version"]
            performance_mode = setup.get("performance_mode", True) is not False
            user_dir = Path(setup["user_dir"])
        if user_dir is None:
            raise common.ForgeError("Forge's run folder must be set up before planning pod games.")
        if not (folder / install.SCRIPTS_ZIP).is_file():
            raise common.ForgeError("Forge's card scripts are missing, so pod games cannot start.")
        deployed = engine._overrides(user_dir)
        if deployed == engine.UNREADABLE_OVERRIDES:
            raise common.ForgeError("Forge's current card scripts could not be confirmed.")
        profile_sha = engine._ai_sha(folder, "Default")
        if profile_sha is None:
            raise common.ForgeError("Forge's default AI profile could not be confirmed.")
        return {"kind": "plain-pods", "version": version, "jar_sha": _jar_sha(folder / jar),
                "scripts_sha": _jar_sha(folder / install.SCRIPTS_ZIP),
                "forge": install.engine_forge(folder, jar), "ai_sha": profile_sha,
                "overrides": deployed, "performance_mode": performance_mode}
    except (OSError, TypeError, ValueError, KeyError):
        raise common.ForgeError("Forge's current engine could not be confirmed for pod games.") from None


def key(entries, games=DEFAULT_GAMES, *, clock_s=DEFAULT_CLOCK, seed_base=DEFAULT_SEED, eng=None):
    chosen = check(entries)
    sides = [{key: entry[key] for key in ("id", "version", "card_sha")} for entry in chosen]
    if pod_lineups.is_lineup(chosen):
        for side, entry in zip(sides[1:], chosen[1:]):
            side["precon_source"] = entry["precon_source"]
    identity = {"version": VERSION, "kind": "pods", "sides": sides,
                "options": _options(games, clock_s, seed_base), "engine": eng}
    return hashlib.sha256(_canonical(identity).encode("ascii")).hexdigest()


def batches(entries, games=DEFAULT_GAMES, seed_base=DEFAULT_SEED):
    """Four games per batch; each complete rotation gives every list every seat."""
    ids = [entry["id"] for entry in check(entries)]
    _options(games, DEFAULT_CLOCK, seed_base)
    return [{"batch": n, "seats": ids[n % SEATS:] + ids[:n % SEATS],
             "pods": PER_BATCH, "seed": seed_base + n} for n in range(games // PER_BATCH)]


def _root(results_dir=None):
    return common._results_dir(results_dir) / "pods"


def _path(run_key, results_dir=None):
    if not isinstance(run_key, str) or not KEY_RE.fullmatch(run_key):
        raise ValueError("That pod run key is not valid.")
    return _root(results_dir) / f"{run_key}.json"


def _read(run_key, results_dir=None):
    path = _path(run_key, results_dir)
    try:
        lifecycle._ordinary(path, directory=False)
        with path.open("rb") as handle:
            raw = handle.read(MAX_SAVED_BYTES + 1)
        if len(raw) > MAX_SAVED_BYTES:
            raise ValueError()
        found = json.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, lifecycle.LifecycleError):
        raise common.ForgeError(UNREADABLE) from None
    if not is_saved(found, run_key):
        raise common.ForgeError(UNREADABLE)
    return found


def is_saved(found, run_key):
    """Pure persisted-schema validator shared by export and member-removal guards."""
    try:
        if (not isinstance(run_key, str) or not KEY_RE.fullmatch(run_key) or
                not isinstance(found, dict) or type(found.get("pod_version")) is not int or
                found["pod_version"] != VERSION or
                found.get("kind") != "pods" or found.get("key") != run_key):
            raise ValueError()
        chosen = check(found["sides"])
        opts = found["options"]
        _options(opts["games"], opts["clock_s"], opts["seed_base"])
        if type(opts.get("per_batch")) is not int or opts["per_batch"] != PER_BATCH:
            raise ValueError()
        if key(chosen, opts["games"], clock_s=opts["clock_s"], seed_base=opts["seed_base"],
               eng=found.get("engine")) != run_key:
            raise ValueError()
        if (not isinstance(found["batches"], list) or len(found["batches"]) > 32032 or
                found.get("state", "ready") not in ("ready", "running", "stopped", "error", "done")):
            raise ValueError()
        planned = batches(chosen, opts["games"], opts["seed_base"])
        totals, attempts = {}, set()
        for row in found["batches"]:
            n, attempt = row["batch"], row["attempt"]
            if (type(n) is not int or not 0 <= n < len(planned) or
                    type(attempt) is not int or not 0 <= attempt <= 1000 or (n, attempt) in attempts or
                    row["seats"] != planned[n]["seats"] or not isinstance(row["games"], list) or
                    type(row["pods"]) is not int or not 1 <= row["pods"] <= PER_BATCH or
                    len(row["games"]) > row["pods"] or
                    type(row["seed"]) is not int or row["seed"] != planned[n]["seed"] + attempt * 1000000 or
                    type(row["failed"]) is not bool or type(row["stopped"]) is not bool):
                raise ValueError()
            attempts.add((n, attempt))
            numbers = set()
            for game in row["games"]:
                if (type(game["game"]) is not int or not 1 <= game["game"] <= row["pods"] or
                        game["game"] in numbers or
                        game["result"] not in ("win", "draw", "clock") or
                        (game["result"] == "win" and (type(game["w"]) is not int or not 1 <= game["w"] <= 4)) or
                        (game["result"] != "win" and game["w"] is not None) or
                        type(game["ms"]) is not int or not 0 <= game["ms"] <= 2 ** 53 or
                        type(game["ai_to"]) is not int or not 0 <= game["ai_to"] <= 1000000000 or
                        (game["turns"] is not None and
                         (type(game["turns"]) is not int or not 0 <= game["turns"] <= 100000000)) or
                        (game["first"] is not None and
                         (type(game["first"]) is not int or not 1 <= game["first"] <= SEATS))):
                    raise ValueError()
                numbers.add(game["game"])
            totals[n] = totals.get(n, 0) + len(row["games"])
            if totals[n] > PER_BATCH:
                raise ValueError()
    except (KeyError, TypeError, ValueError, IndexError):
        return False
    return True


def _wilson(wins, total):
    if not total:
        return None
    z, p = 1.96, wins / total
    scale = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / scale
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / scale
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _win_share(wins, total):
    return {"wins": wins, "pods": total, "rate": round(wins / total, 4) if total else None,
            "range": _wilson(wins, total)}


def _rotations(deck_id, counted):
    wins, totals = [0] * SEATS, [0] * SEATS
    for game in counted:
        seat = game["seats"].index(deck_id)
        totals[seat] += 1
        wins[seat] += game["w"] == seat + 1
    return {str(seat + 1): _win_share(wins[seat], totals[seat]) for seat in range(SEATS)}


def summary(rows, entries):
    """Draws are included in each denominator; clock stops never credit a winner."""
    games = [dict(game, seats=row["seats"]) for row in rows for game in row["games"]]
    counted = [game for game in games if game["result"] != "clock"]
    by_deck = {}
    for entry in entries:
        wins = sum(game["result"] == "win" and game["seats"][game["w"] - 1] == entry["id"]
                   for game in counted)
        by_deck[entry["id"]] = _win_share(wins, len(counted))
    if pod_lineups.is_lineup(entries):
        deck_id = entries[0]["id"]
        by_deck[deck_id]["by_seat"] = _rotations(deck_id, counted)
    return {"pods": len(games), "counted": len(counted), "wins": sum(g["result"] == "win" for g in games),
            "draws": sum(g["result"] == "draw" for g in games),
            "clock_stops": sum(g["result"] == "clock" for g in games),
            "ai_timeouts": sum(g.get("ai_to", 0) for g in games),
            "failed_batches": sum(bool(row.get("failed")) for row in rows), "by_deck": by_deck}


def _public(found):
    opts = found["options"]
    nums = summary(found["batches"], found["sides"])
    complete = nums["pods"] >= opts["games"]
    return {"key": found["key"], "kind": "pods", "decks": found["sides"], "sides": found["sides"],
            "engine": found.get("engine"), **opts, "planned": opts["games"],
            "completed": nums["pods"], "remaining": max(0, opts["games"] - nums["pods"]),
            "summary": nums, "statistical_only": True, "note": NOTE,
            "state": "done" if complete else found.get("state", "ready"),
            "by": found.get("by"), "stopped_by": found.get("stopped_by"),
            "created": found.get("created"), "updated": found.get("updated")}


def load(run_key, results_dir=None):
    """A saved public-safe view, or None; no installation needed and no raw logs."""
    found = _read(run_key, results_dir)
    return _public(found) if found is not None else None


def results(results_dir=None):
    """Newest saved public projections; the API checks all four seats' visibility."""
    try:
        paths = sorted(_root(results_dir).glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return []
    out = []
    for path in paths[:100]:
        if not KEY_RE.fullmatch(path.stem):
            continue
        try:
            saved = load(path.stem, results_dir)
        except common.ForgeError:
            continue
        if saved is not None:
            out.append(saved)
    return out


def plan(entries, games=DEFAULT_GAMES, *, clock_s=DEFAULT_CLOCK, seed_base=DEFAULT_SEED,
         eng=None, results_dir=None):
    chosen = check(entries)
    run_key = key(chosen, games, clock_s=clock_s, seed_base=seed_base, eng=eng)
    found = _read(run_key, results_dir)
    if found is None:
        found = {"key": run_key, "sides": _sides(chosen), "engine": eng,
                 "options": _options(games, clock_s, seed_base), "batches": [], "state": "ready"}
    return {**_public(found), "batches": batches(chosen, games, seed_base)}


def view(entries, games=DEFAULT_GAMES, **options):
    """The current plan and any matching saved results; no games are started."""
    return plan(entries, games, **options)


class PodReader:
    """The prototype's plain Forge four-seat output parser, with bounded valid games."""
    def __init__(self, expected=PER_BATCH):
        self.expected = expected
        self.games, self.load_errors, self.invalid = [], False, False
        self.tail = deque(maxlen=20)
        self._numbers = set()
        self._new()

    def _new(self):
        self._g = {"turns": None, "first": None, "ai_to": 0, "clock": False, "won": set()}

    def feed(self, line):
        line = line.rstrip("\r\n")
        self.tail.append(line[:300])
        g = self._g
        if "AI eval thread at timeout" in line:
            g["ai_to"] += 1
        if "Stopping slow match as draw" in line:
            g["clock"] = True
        if RE_NOLOAD.match(line) or line.startswith("An unsupported card was requested:"):
            self.load_errors = True
        match = RE_TURN.match(line)
        if match:
            turn, seat = int(match[1]), int(match[2])
            if 1 <= seat <= SEATS:
                g["turns"] = max(g["turns"] or 0, turn)
                if turn == 1:
                    g["first"] = seat
        match = RE_OUTCOME.match(line)
        if match and match[2] == "won":
            g["won"].add(int(match[1]))
        match = RE_WIN.match(line)
        if match:
            clock = g["clock"] or len(g["won"]) > 1
            return self._end(int(match[1]), int(match[2]), "clock" if clock else "win",
                             None if clock else int(match[3]))
        match = RE_DRAW.match(line)
        if match:
            return self._end(int(match[1]), int(match[2]), "clock" if g["clock"] else "draw", None)
        return None

    def _end(self, number, ms, result, winner):
        if (number in self._numbers or not 1 <= number <= self.expected or
                (winner is not None and not 1 <= winner <= SEATS)):
            self.invalid = True
            self._new()
            return None
        self._numbers.add(number)
        g = self._g
        row = {"game": number, "result": result, "w": winner, "ms": ms,
               "turns": g["turns"], "first": g["first"], "ai_to": g["ai_to"]}
        self.games.append(row)
        self._new()
        return row


def command(setup, dck_names, games, seed, clock_s):
    if len(dck_names) != SEATS:
        raise ValueError("A pod command requires four decks.")
    return [*runner._java(setup), "-jar", str(setup["jar"]), "sim", "-D", str(setup["decks_dir"]),
            "-d", *dck_names, "-n", str(games), "-s", str(seed), "-f", "Commander", "-c", str(clock_s),
            "-a", *(["Default"] * SEATS)]


class _Batch:
    def __init__(self, job, lease):
        self.job, self.lease = job, lease
        self.reader = PodReader(job["pods"])
        self.proc = self.thread = None
        self.started = self.last_game = time.monotonic()
        self.killed = None
        self.read_error = False


def _read_output(batch, events):
    try:
        for line in batch.proc.stdout:
            game = batch.reader.feed(line)
            if game is not None:
                events.put(("game", batch))
    except (OSError, ValueError):
        batch.read_error = True
    finally:
        try:
            batch.proc.wait()
            batch.proc.stdout.close()
        except OSError:
            batch.read_error = True
        events.put(("exit", batch))


def _pending(found, chosen):
    result = []
    for job in batches(chosen, found["options"]["games"], found["options"]["seed_base"]):
        old = [row for row in found["batches"] if row["batch"] == job["batch"]]
        remaining = job["pods"] - sum(len(row["games"]) for row in old)
        if remaining <= 0:
            continue
        attempt = 1 + max((row["attempt"] for row in old), default=-1)
        if attempt > 1000:
            raise common.ForgeError("This pod run has too many attempts; choose a new plan.")
        result.append(dict(job, pods=remaining, attempt=attempt,
                           seed=job["seed"] + attempt * 1000000))
    return result


def _save(found, results_dir):
    found["updated"] = common._now()
    try:
        common._write_atomic(_path(found["key"], results_dir), json.dumps(found, ensure_ascii=False))
    except OSError:
        raise common.ForgeError("Deck Lab could not save this pod run's results.") from None


def _play(found, chosen, setup, env, *, progress, results_dir, procs):
    waiting = deque(_pending(found, chosen))
    running, events = [], queue.Queue()
    dck = {entry["id"]: runner._dck_name(entry) for entry in chosen}
    stop = None
    next_start = 0.0
    wanting = None

    def report():
        if progress is not None:
            nums = summary(found["batches"], chosen)
            active = sum(len(batch.reader.games) for batch in running)
            progress(nums["pods"] + active, found["options"]["games"],
                     {"kind": "pods", "failed_batches": nums["failed_batches"],
                      "waiting": slots.WAITING if waiting and not running else None})

    def end(batch):
        batch.thread.join(KILL_WAIT)
        if batch.thread.is_alive():
            raise common.ForgeError("A pod process did not stop safely.")
        processes._end_process(batch.proc)
        batch.lease.release()
        running.remove(batch)
        reader = batch.reader
        bad = reader.load_errors or reader.invalid
        games = [] if bad else reader.games
        failed = bool(bad or batch.read_error or
                      (batch.killed and batch.killed != "stopped") or
                      (batch.killed != "stopped" and
                       (batch.proc.returncode != 0 or len(games) != batch.job["pods"])))
        # A stop before any game leaves no attempt to resume, including its seed.
        if games or failed:
            found["batches"].append(dict(batch.job, games=games, failed=failed,
                                          stopped=batch.killed == "stopped"))
            _save(found, results_dir)

    try:
        report()
        while waiting or running:
            now = time.monotonic()
            if waiting and len(running) < procs and now >= next_start:
                try:
                    lease = slots.claim(1, setup["workers"], wait=False, what=f"pod {found['key'][:12]}")
                except OSError:
                    raise common.ForgeError("Forge's shared worker budget could not be checked.") from None
                if lease:
                    job = waiting.popleft()
                    if not waiting and wanting is not None:
                        wanting.release()
                        wanting = None
                    batch = _Batch(job, lease)
                    try:
                        argv = command(setup, [dck[d] for d in job["seats"]], job["pods"], job["seed"],
                                       found["options"]["clock_s"])
                        with common._interrupts_held():
                            batch.proc = processes.start_process(argv, cwd=setup["forge_dir"], env=env)
                            running.append(batch)
                            batch.thread = threading.Thread(target=_read_output, args=(batch, events), daemon=True,
                                                            name=f"forge-pod-{job['batch']}")
                            batch.thread.start()
                    except OSError:
                        lease.release()
                        found["batches"].append(dict(job, games=[], failed=True, stopped=False))
                        _save(found, results_dir)
                    except BaseException:
                        if batch.proc is None:
                            lease.release()
                        raise
                    next_start = now + START_GAP
                else:
                    if wanting is None:
                        try:
                            wanting = slots.want(f"pod {found['key'][:12]}")
                        except OSError:
                            raise common.ForgeError("Forge's shared worker budget could not be checked.") from None
                    next_start = now + POLL_S
            if not running and not waiting:
                break
            try:
                kind, batch = events.get(timeout=POLL_S)
            except queue.Empty:
                kind, batch = None, None
            if kind == "game":
                batch.last_game = time.monotonic()
            elif kind == "exit" and batch in running:
                end(batch)
            now = time.monotonic()
            for batch in list(running):
                if now - batch.last_game > found["options"]["clock_s"] + runner.HEADER_TIMEOUT + runner.GAME_GRACE:
                    batch.killed = "timeout"
                    processes.kill_process(batch.proc)
            report()
    except BaseException as error:
        stop = error
    finally:
        if wanting is not None:
            wanting.release()
        for batch in list(running):
            batch.killed = "stopped" if isinstance(stop, common.STOPS) else (batch.killed or "error")
            processes.kill_process(batch.proc)
        for batch in list(running):
            try:
                end(batch)
            except BaseException as error:
                stop = stop or error
    return stop


def run(entries, games=DEFAULT_GAMES, *, by, progress=None, results_dir=None, clock_s=DEFAULT_CLOCK,
        seed_base=DEFAULT_SEED, procs=None, eng=None, expected_key=None):
    """Resume this bounded sample, saving finished games before propagating a stop.

    eng is the engine reviewed by the caller; expected_key binds its plan. Both are
    rechecked against the actual installation before a process starts.
    """
    chosen = check(entries)
    _options(games, clock_s, seed_base)
    if any(not isinstance(entry.get("dck"), str) or not entry["dck"] for entry in chosen):
        raise ValueError("A pod deck's Forge list could not be confirmed.")
    if procs is not None and (type(procs) is not int or not 1 <= procs <= MAX_PROCS):
        raise ValueError("Pod runs use between one and four workers.")
    setup = dict(install._setup(), game_patches=False, card_log={"ready": False})
    actual = engine_identity(setup)
    if eng is not None and eng != actual:
        raise common.ForgeError(STALE)
    run_key = key(chosen, games, clock_s=clock_s, seed_base=seed_base, eng=actual)
    if expected_key is not None and expected_key != run_key:
        raise common.ForgeError(STALE)
    root = _root(results_dir)
    # The root claim also makes a queued run recheck departed deck identities.
    with lifecycle.writer(common._results_dir(results_dir), deck_ids=[entry["id"] for entry in chosen]):
        fd = runner._claim(root, run_key)
        try:
            found = _read(run_key, results_dir)
            if found is None:
                found = {"pod_version": VERSION, "kind": "pods", "key": run_key,
                         "sides": _sides(chosen), "engine": actual,
                         "options": _options(games, clock_s, seed_base), "batches": [],
                         "created": common._now()}
            if not _pending(found, chosen):
                return _public(found)
            found.update(state="running", by=by, stopped_by=None)
            _save(found, results_dir)  # refuse an unwritable checkpoint before preparing or starting Forge
            runner._write_decks(setup["decks_dir"], chosen)
            try:
                env = runner._prepare_user_dir(setup["user_dir"])
            except OSError:
                raise common.ForgeError("Forge's run folder could not be prepared for pod games.") from None
            # Preparing preferences/overrides must not silently change the approved engine.
            if engine_identity(setup) != actual:
                found["state"] = "error"
                _save(found, results_dir)
                raise common.ForgeError(STALE)
            try:
                stopped = _play(found, chosen, setup, env, progress=progress, results_dir=results_dir,
                                procs=min(MAX_PROCS, setup["workers"], procs or MAX_PROCS))
            finally:
                runner._tidy_user_dir(setup["user_dir"])
            remaining = games - summary(found["batches"], chosen)["pods"]
            found["state"] = "stopped" if isinstance(stopped, common.STOPS) else "error" if stopped or remaining else "done"
            found["stopped_by"] = getattr(stopped, "by", None) if isinstance(stopped, common.STOPS) else None
            _save(found, results_dir)
            if stopped is not None:
                raise stopped
            if _public(found)["completed"] == 0:
                raise common.ForgeError("Forge finished no pod games. Check the pod decks before trying again.")
            return _public(found)
        finally:
            runner._release(fd, root / f"{run_key}.lock")
