"""Playing a matchup: Forge's command line (DeckLabSim's, with the card log, when
simjar.card_log() says it can be used), its user folder, the loop that runs the
batches' processes (with the watchdog, progress and stopping), failure logs, the
matchup's lock, and run(), which saves the games with the matchup's earlier ones. The
rules for batches, progress, stopping, failures and saving are in the package docstring
(decklab/lib/forge/__init__.py).

Since wave 2's base commit it also builds the warm workers' command line
(serve_command) and their "play" lines (request_line, from request_args, which batches
share), and asks engine.py for the engine a run plays and its key. Wave 2's contract
(forge-trial/sim-wave2-contract.md) says which package changes which function here.
A run of the v2 engine (the card log ready) plays its game numbers in the warm pool
(pool.py) instead of cold batches: _run_v2 plans them, _play_v2 reads its chunks' games as
the pool sends them, and _record_v2 saves them as one merged batch per run."""
import hashlib
import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
from collections import deque
from copy import deepcopy
from pathlib import Path

from . import cardlog, common, engine, install, lifecycle, overrides, pilots, processes, seeds, simjar, slots
from .common import (AI_PROFILES, FORGE_RUN_VERSION, GAME_CHOICES, MIXED_KINDS, STOPS, ForgeError, _interrupts_held,
                     _now, _os_reason, _results_dir)
from .install import _forge_card, _log_names, _setup
from .lists import _batch_size, _list_lines, fmt_for, plan, plan_v2
from .logreader import LogReader
from .processes import _end_process, kill_process
from .saved import _decklab, load

# -XX:ActiveProcessorCount=2: each Forge process plays its games on one thread, but Java
# sizes itself for the whole PC (15 JIT and 23 GC threads for 32 logical CPUs), so 16
# processes starting together fight over the cores; the flag cuts that to 2 and 2.
# Measured on 16 processes (forge-trial/sim-investigation.md, R01a, 2026-10-03): 1,011 ->
# 1,086 games a minute, start-up 5.2 -> 3.4 s, and +24 % / +15 % on runs of 16 x 25 /
# 16 x 50 games; the winners were the same (checked on Izzet v Gruul only). Forge's per-attack
# thread pool also drops from 32 threads to 2, 8 processes (a 200-game run) weren't measured,
# and Java's sizing should be re-checked after a JDK upgrade.
JVM_FLAGS = ("-XX:+DisableExplicitGC", "-XX:ActiveProcessorCount=2", "-Dio.netty.tryReflectionSetAccessible=true",
             "-Dfile.encoding=UTF-8")
# Forge's preferences for every run: lazy card loading (Milestone 0), and PERFORMANCE_MODE (R08: it skips
# checks that can't apply to Deck Lab's cards, measured +5-12 % with the same games), which the engine id
# records (engine.PERFORMANCE_MODE) and DeckLabSim's DLENGINE line reports (perf=, engine.check_echo).
PREFERENCES = ("LOAD_CARD_SCRIPTS_LAZILY=true\n"
               f"PERFORMANCE_MODE={'true' if engine.PERFORMANCE_MODE else 'false'}\n")
AIPROFILES_FLAG = "-Ddecklab.aiprofiles"    # DeckLabSim's AI profile folder (wave 3, contract section 3.4)


# The watchdog (seconds). A process that prints no header line in HEADER_TIMEOUT, or no
# "Game Result" line for the per-game clock plus GAME_GRACE, has stopped responding.
HEADER_TIMEOUT = 180
GAME_GRACE = 90
PROGRESS_GAP = 0.25             # at most 4 progress calls a second
HEARTBEAT = 1.0                 # and at least one a second, so a Stop is noticed
KILL_WAIT = 10                  # seconds to wait for a killed process's reader thread
TAIL_LINES = 200                # lines of Forge's own output kept per process, for a failed batch's log
                                # (not the card log's lines, cardlog.PREFIX: about 100 a game)
CARD_PROBLEMS_LOGGED = 3        # reasons logged per batch whose games' card logs failed their checks
KEEP_FAILURE_LOGS = 50
EVENT_POLL_S = 0.2              # the run loop's longest wait for a line: how often the watchdog
                                # and the heartbeat get a look while no process prints anything
SLOT_RETRY_S = 0.5              # how often a run with batches waiting tries again for a free slot
                                # (slots.py), apart from straight after one of its own processes ends

BUSY = "This matchup is already being played."
CANT_SAVE = "Deck Lab can't save matchup results, so the run wasn't started."
NOT_SAVED = "Deck Lab couldn't save the matchup's games."
UNREADABLE = "This matchup's saved games can't be read, so the run wasn't started (saving would lose them)."
OTHER_ENGINE = ("This matchup's saved games were played with another engine, so the run wasn't started "
                "(saving would mix them).")
# A v2 run of an existing result whose a_first asks for the other seat order (the result's own
# stays: wave 2's contract "Per-game seeds"): one line on the command line's stderr.
A_FIRST_IGNORED = ("This matchup's saved games already set which deck plays first in each block of 25, so "
                   "--a-first doesn't change them.")


PILOT_PROFILE = re.compile(r"[A-Za-z0-9_-]{1,40}")      # pilots.PROFILE_NAME
PILOT_SWITCH = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")   # simjar.GAME_PATCH_ID's form


REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")     # a serve request's id
SERVE_PREFIX = "DLSERVE|"       # the start of every line of the serve protocol a worker prints
SERVE_PROTOCOL = 1              # the protocol version DeckLabServe.PROTOCOL says it speaks
SERVE_STATUSES = ("done", "cancelled", "recycle", "error")      # how a request can end
# Why a worker recycled (an end line's detail with status recycle; DeckLabServe.recycleReason):
# a game's clock stopped it, an AI evaluation timed out in it (or still runs), or it crashed.
RECYCLE_REASONS = ("clock", "ai_timeout", "crash")
SERVE_HEAP = re.compile(r"heap_mb=(\d+)")      # a done or cancelled request's detail


# ============================================================ running batches


STOP_KILL = "stopped"           # _Batch.killed of a process a stop killed


def _side(entry_):
    """A new result's side for an entry. Since wave 3 it keeps the entry's pilot ("pilot",
    _pilot), so stored side i always holds that side's pilot (sim-wave3-contract.md section 8)."""
    side = {"card_sha": entry_["card_sha"], "dck": entry_["dck"], "card_count": entry_["card_count"],
            "kind": entry_["kind"], "cards": entry_.get("cards"), "seen_as": []}
    if isinstance(entry_.get("pilot"), dict):
        side["pilot"] = _pilot(entry_)
    return side


def _seen(side, entry_, when):
    """Note that side was played as entry_'s deck id and version (the newest last)."""
    seen = [s for s in side["seen_as"] if (s["id"], s["version"]) != (entry_["id"], entry_["version"])]
    seen.append({"id": entry_["id"], "version": entry_["version"], "title": entry_["title"],
                 "source": entry_.get("source"), "when": when})
    side["seen_as"] = seen
    if not side.get("cards") and entry_.get("cards"):
        side["cards"] = entry_["cards"]


def _check_names(sides, index):
    """Raise ForgeError naming every card Forge has no script for."""
    unknown = []
    for side in sides:
        for section in ("Commander", "Main"):
            for _, name in side["cards"].get(section, []):
                if _forge_card(name, index) is None and name not in unknown:
                    unknown.append(name)
    if unknown:
        raise ForgeError("Forge doesn't know " + ("this card" if len(unknown) == 1 else "these cards")
                         + ", so the matchup can't be played: " + ", ".join(unknown) + ".")


DCK_FILE = re.compile(r"[0-9a-f]{64}\.dck")      # an entry's own .dck name (pool.NAME_RE's shape)


def _dck_name(entry_):
    """An entry's .dck file name: its "dck_file" (wave 3: a variant's aligned .dck, named by the
    SHA-256 of its text, so it never overwrites the list's sorted <card_sha>.dck), else
    <card_sha>.dck."""
    return entry_.get("dck_file") or f"{entry_['card_sha']}.dck"


def _write_decks(decks_dir, ordered):
    """Write each list's .dck file (content-addressed: an existing one is kept), under its
    _dck_name."""
    try:
        decks_dir.mkdir(parents=True, exist_ok=True)
        for e in ordered:
            path = decks_dir / _dck_name(e)
            try:
                same = path.read_text(encoding="utf-8") == e["dck"]
            except OSError:
                same = False
            if not same:
                common._write_atomic(path, e["dck"])
    except OSError as e:
        common._log(f"Forge's deck files couldn't be written: {e}")
        raise ForgeError("Deck Lab can't write Forge's deck files in its data folder, "
                         "so the run wasn't started.") from None


def _claim(folder, key):
    """Before a run that saves: check results can be written in folder, and take the
    matchup's lock (an OS lock on <key>.lock, which goes with the process however it
    ends), so a second run of the same matchup, here or in another process, can't play
    the same seeds and overwrite this one's games. Returns the lock's file descriptor."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".write-check-", suffix=".tmp")
        os.close(fd)
        os.unlink(tmp)
    except OSError as e:
        common._log(f"Matchup results can't be saved in {folder}: {e}")
        raise ForgeError(CANT_SAVE) from None
    try:
        fd = os.open(folder / f"{key}.lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o666)
    except OSError:
        raise ForgeError(BUSY) from None        # being deleted by the run that had it
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise ForgeError(BUSY) from None
    return fd


def _release(fd, path):
    """Give up a matchup's lock (_claim), and delete its file on Windows, where no
    other run can be holding it then (elsewhere it stays: a 0-byte file)."""
    try:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    os.close(fd)
    if sys.platform == "win32":
        try:
            path.unlink()
        except OSError:
            pass                # another run has it open, trying for the lock


# The keywords of run() that wave 3's R has built (sim-wave3-contract.md section 8). Tests of the
# packages that need them skip until then (skipUnless(RUN_FEATURES >= {...})).
RUN_FEATURES = frozenset(("numbers", "seeds", "key", "kind", "extra", "override_sets", "log_dir"))
RESULT_KINDS = ("paired", "experiment")         # run(kind=...) besides None, a matchup (saved.RESULT_KINDS)
PAIRED_FOLDER = "paired"        # in the results folder: kind "paired" results, which listings never read
PAIRED_VERSION = 1              # a new paired result's "paired_version"
KEY_RE = re.compile(r"[0-9a-f]{64}")
# The harness's environment variables (sim-wave3-contract.md sections 8 and 17): a new v2 result's
# seed base when the run passes none, and a file whose existence stops every run in the process.
SEED_BASE_ENV = "DECKLAB_SEED_BASE"
STOP_FILE_ENV = "DECKLAB_STOP_FILE"
STOP_FILE_CHECK_S = 1.0         # how often a run looks for the stop file (at its progress ticks)
UPDATE_WAIT_S = 30              # how long update_result waits for a matchup's lock
UPDATE_RETRY_S = 0.25
NEEDS_V2 = ("These games need Deck Lab's card log (the v2 engine), which can't be used on this PC now, so the run "
            "wasn't started.")
CANT_DEPLOY = "Deck Lab can't set up its card-script overrides in its data folder, so the run wasn't started."
# A result's own fields, which run(extra=...) can't replace.
RESULT_FIELDS = frozenset(("key", "format", "forge_version", "run_version", "settings", "seeds", "next_game", "sides",
                           "runs", "batches", "failed", "created", "updated", "engine", "kind"))

_said = set()
_said_lock = threading.Lock()


def _say_once(what, text):
    """Log text the first time what comes up in this process."""
    with _said_lock:
        if what in _said:
            return
        _said.add(what)
    common._log(text)


@lifecycle.writing("entry_a", "entry_b", save="save")
def run(entry_a, entry_b, games, *, by, progress=None, results_dir=None, workers=None,
        batch=None, seed_base=None, a_first=False, save=True, local=False, pool=None, exact=False,
        numbers=None, seeds=None, key=None, kind=None, extra=None, override_sets=None, log_dir=None,
        log_every=1):
    """Play games of entry_a against entry_b (from entry()) and save them with the
    matchup's earlier games; returns the saved result. See the package docstring for
    batches, progress, stopping and failures. save=False keeps the result off disk.

    With the card log ready, the run plays the v2 engine (the decklab kind, engine.py): the
    result's game numbers [next_game, next_game + games) (lists.plan_v2), in chunks of the
    warm pool (pool.py), merged into one batch record (_run_v2). pool and local say where
    (wave 2's contract "Where a run plays"; pool.place): pool, a pool.session() or a Pool;
    None: the server's pool in the server, else the running server's through its pool
    service when it plays the same engine, else a pool of the run's own (closed when the run
    ends); local=True, always a pool of the run's own. When the server goes away mid-run, a
    command line run plays the rest in a pool of its own. batch caps a chunk's games (games
    then any multiple of it); seed_base is a new result's seed base (0 or more; without it,
    the environment's DECKLAB_SEED_BASE, else seeds.SEED_BASE); a_first
    puts entry_a as Forge's deck 1 in the first seat block of a new result (its seats flip
    every seeds.SEAT_BLOCK games; an existing result keeps its own, and says so). exact=True
    takes any number of games of 1 or more (the replay command's "the games missing").
    Without the card log, the run plays plain Forge's cold batches as before (_play):
    batch/seed_base as for plan(), a_first makes entry_a Forge's deck 1 in even batches.

    Wave 3 (sim-wave3-contract.md section 8; RUN_FEATURES):
        numbers     the sorted, distinct game numbers (ints of 0 or more) to play instead of
                    [next_game, next_game + games); games must be len(numbers). Chunks are cut
                    at seat blocks and at gaps; next_game becomes max(next_game, the last + 1).
                    Numbers the result holds are refused, and so, for a matchup (kind None), is
                    any number below next_game: only paired and experiment results may fill
                    holes below it (their games match another result's numbers)
        seeds       {"base", "stream" (16 hex digits, as results store it), "flip"} for a new
                    result; an existing one's must be the same. (The keyword hides the seeds
                    module in here; the functions below use it.)
        key         the result's key (64 hex digits), instead of engine.key's
        kind        None (a matchup), "paired" (saved as <results_dir>/paired/<key>.json, which
                    listings never read; it needs extra's "paired" block) or "experiment"
                    (saved with "kind": "experiment"; replay skips it)
        extra       a dict merged into a new result's top level (not over its own fields)
        override_sets
                    play in overrides.user_dir_for(those sets) instead of Forge's real user
                    folder: its overrides, key, side ids and launch identity are the folder's
        log_dir, log_every
                    the log tee: the output of each chunk whose seat block's number is a
                    multiple of log_every (pool.py) is written gzip-compressed to
                    <log_dir>/<key>/<first g>-<last g>.log.gz (v2 runs only)
    numbers, seeds and the two kinds need the v2 engine (ForgeError NEEDS_V2 without it).
    Before the engine is worked out, overrides.ensure_deployed(the run's user folder) makes its
    custom/cards hold what it should; the entries are ordered as the key's sides
    (engine.side_list, sorted), each side keeps its pilot, and pilots.check_switches refuses a
    switch the engine can't play (ForgeError). When the environment's DECKLAB_STOP_FILE names a
    file that exists, the run stops at its next progress tick as the page's Stop stops it
    (common.Stopped; its finished games are saved); a run started with the file there raises
    common.Stopped at once, saving nothing.

    ForgeError (a plain sentence) when it can't start: Forge not ready, mixed kinds,
    unknown cards, the data folder can't be written, or this matchup is already being
    played (by this process or another). ValueError for games, workers, batch, seed_base or
    a wave 3 keyword that doesn't suit."""
    asked = {"numbers": numbers, "seeds": seeds, "key": key, "kind": kind, "extra": extra,
             "override_sets": override_sets, "log_dir": log_dir}
    missing = sorted(name for name, value in asked.items() if value is not None and name not in RUN_FEATURES)
    if missing:
        raise NotImplementedError(f"runner.run's {', '.join(missing)} is wave 3's R")
    _stop_file_check()                  # with the stop file there, nothing is claimed, planned or saved
    hooks = _hooks(games, entry_a, entry_b, numbers=numbers, seed_record=seeds, key=key, kind=kind, extra=extra,
                   override_sets=override_sets, log_dir=log_dir, log_every=log_every)
    if hooks["numbers"] is not None:
        exact = True
    setup = _setup()
    if entry_a["kind"] != entry_b["kind"]:
        raise ForgeError(MIXED_KINDS)
    fmt = fmt_for(entry_a["kind"])
    workers = int(workers) if workers is not None else setup["workers"]
    if exact:                                                           # ValueError before anything
        if workers < 1 or not isinstance(games, int) or games < 1:
            raise ValueError("games and workers must be whole numbers of 1 or more")
    else:
        _batch_size(games, workers, batch)
    if seed_base is not None and int(seed_base) < 0:
        raise ValueError("the seed base must be 0 or more")              # "-s -5" is no -s to Forge
    if hooks["override_sets"] is not None:
        setup["user_dir"] = Path(overrides.user_dir_for(hooks["override_sets"],
                                                        performance_mode=_performance_mode(setup)))
        setup["override_sets"] = list(hooks["override_sets"])
    index = install.script_index()
    _check_names([_side(e) for e in (entry_a, entry_b)], index)
    _write_decks(setup["decks_dir"], [entry_a, entry_b])
    # The card log when it can be used (building its jar if need be), else plain Forge.
    setup["card_log"] = simjar.card_log(setup["java"], setup["forge_dir"], setup["jar"], setup["version"])
    _deploy(setup["user_dir"])          # before the engine: keys and launches follow what workers load
    # The engine those play (engine.py), and the matchup's key with it: the version played with.
    eng = engine.current(setup, setup["card_log"])
    if eng.get("kind") != engine.KIND_DECKLAB and (hooks["numbers"] is not None or hooks["seeds"] is not None
                                                   or hooks["kind"] is not None):
        raise ForgeError(NEEDS_V2)
    clash = sorted((set(engine.result_fields(eng)) | {"paired_version"}) & set(hooks["extra"]))
    if clash:
        raise ValueError(f"extra can't replace a result's own fields ({', '.join(clash)})")
    ordered = _ordered(entry_a, entry_b, eng)
    for e in ordered:
        try:
            pilots.check_switches(eng, _pilot(e))
        except ValueError as refused:
            raise ForgeError(str(refused)) from None
    key = hooks["key"] or engine.key(entry_a, entry_b, eng)
    folder = _results_dir(results_dir)
    if hooks["kind"] == "paired":
        folder = folder / PAIRED_FOLDER
    lock = _claim(folder, key) if save else None
    progress = _stop_file_progress(progress)
    try:
        return _run(setup, key, eng, fmt, entry_a, entry_b, ordered, games, by, progress, _results_dir(results_dir), folder,
                    workers, batch, seed_base, a_first, save, index, pool=pool, local=local, exact=exact, hooks=hooks)
    finally:
        if lock is not None:
            _release(lock, folder / f"{key}.lock")


def _hooks(games, entry_a, entry_b, *, numbers, seed_record, key, kind, extra, override_sets, log_dir, log_every):
    """run()'s wave 3 keywords, checked (ValueError for one that doesn't suit) and in the forms
    the rest of the run uses: {"numbers": [g, ...] or None, "seeds": {"base", "stream",
    "flip"} or None, "key", "kind", "extra": {} or a dict, "override_sets": [names] or None,
    "log": {"dir": an absolute path's text, "every"} or None}."""
    out = {"numbers": None, "seeds": None, "key": None, "kind": None, "extra": {}, "override_sets": None, "log": None}
    if numbers is not None:
        found = list(numbers)
        if not found or not all(type(g) is int and g >= 0 for g in found) or found != sorted(set(found)):
            raise ValueError("numbers must be game numbers of 0 or more, sorted, each once")
        if games != len(found):
            raise ValueError(f"games must be the count of numbers ({len(found)}), not {games}")
        out["numbers"] = found
    if seed_record is not None:
        if not isinstance(seed_record, dict):
            raise ValueError('seeds must be {"base", "stream", "flip"}')
        base, flip = seed_record.get("base"), seed_record.get("flip")
        if type(base) is not int or base < 0:
            raise ValueError(f"a seed base must be a whole number of 0 or more, not {base!r}")
        seeds.parse_stream(seed_record.get("stream"))           # ValueError unless 16 hex digits
        if flip not in (0, 1) or type(flip) not in (int, bool):
            raise ValueError(f"a flip must be 0 or 1, not {flip!r}")
        out["seeds"] = {"base": base, "stream": seed_record["stream"], "flip": int(flip)}
    if key is not None:
        if not isinstance(key, str) or not KEY_RE.fullmatch(key):
            raise ValueError("a result's key must be 64 hex digits")
        out["key"] = key
    if kind is not None:
        if kind not in RESULT_KINDS:
            raise ValueError(f"kind must be None or one of {', '.join(RESULT_KINDS)}, not {kind!r}")
        out["kind"] = kind
    if extra is not None:
        if not isinstance(extra, dict):
            raise ValueError("extra must be a dict")
        clash = sorted(RESULT_FIELDS & set(extra))
        if clash:
            raise ValueError(f"extra can't replace a result's own fields ({', '.join(clash)})")
        out["extra"] = deepcopy(extra)
    if kind == "paired" and not isinstance(out["extra"].get("paired"), dict):
        raise ValueError('a paired result needs extra\'s "paired" block')
    if override_sets is not None:
        sets = None if isinstance(override_sets, str) else list(override_sets)
        if sets is None or not all(isinstance(name, str) and name for name in sets):
            raise ValueError("override_sets must be a list of override set names")
        out["override_sets"] = sets
    if type(log_every) is not int or log_every < 1:
        raise ValueError("log_every must be a whole number of 1 or more")
    if log_dir is not None:
        out["log"] = {"dir": str(Path(log_dir).resolve()), "every": log_every}
    for e in (entry_a, entry_b):
        name = e.get("dck_file")
        if name is not None and not (isinstance(name, str) and DCK_FILE.fullmatch(name)):
            raise ValueError(f"an entry's dck_file must be <64 hex digits>.dck, not {name!r}")
        if name is not None and name != hashlib.sha256(e["dck"].encode("utf-8")).hexdigest() + ".dck":
            raise ValueError(f"an entry's dck_file must be the SHA-256 of its dck text, not {name!r}")
    return out


def _performance_mode(setup):
    """The PERFORMANCE_MODE a user folder made for a run's override sets gets: setup's (wave 3's
    install._setup puts the config's there), else config.json's forge_performance_mode (true
    unless it's false)."""
    if isinstance(setup.get("performance_mode"), bool):
        return setup["performance_mode"]
    try:
        return common._settings().get("forge_performance_mode", True) is not False
    except Exception:
        return True


def _deploy(user_dir):
    """overrides.ensure_deployed(user_dir), before the engine is worked out (sim-wave3-contract.md
    section 6.2): ForgeError CANT_DEPLOY when the folder can't be written."""
    try:
        overrides.ensure_deployed(user_dir)
    except OSError as e:
        common._log(f"Forge's card-script overrides couldn't be put in {user_dir}: {e}")
        raise ForgeError(CANT_DEPLOY) from None


def _pilot(entry_):
    """An entry's (or a stored side's) pilot, {"profile", "switches": sorted}: its "pilot"
    (wave 3's E3 puts one on every entry), else pilots.DEFAULT_PILOT."""
    found = entry_.get("pilot")
    if not isinstance(found, dict) or not isinstance(found.get("profile"), str):
        found = pilots.DEFAULT_PILOT
    return {"profile": found["profile"], "switches": sorted(found.get("switches") or [])}


def _side_list(entry_, eng):
    """An entry's side list, as the key's sides have it: engine.side_list (wave 3's E3) when it's
    built, else [card_sha, its pilot's profile, that profile's SHA-256], with its pilot's
    switches as a fourth element when it has any (sim-wave3-contract.md section 4.1)."""
    built = getattr(engine, "side_list", None)
    if built is not None:
        return built(entry_, eng)
    pilot = _pilot(entry_)
    side = [entry_["card_sha"], pilot["profile"], (eng.get("ai_sha") or {}).get(pilot["profile"])]
    return side + [pilot["switches"]] if pilot["switches"] else side


def _sort_key(side):
    """A side list for sorting: engine._side_order (wave 3's E3, the key's own order) when it's
    built, else the stand-in: an unknown ai_sha (None) as "", so it never meets a text in a
    comparison (two lists that tie up to it have the same profile, so the same ai_sha anyway)."""
    built = getattr(engine, "_side_order", None)
    if built is not None:
        return built(side)
    return ["" if part is None else part for part in side]


def _ordered(entry_a, entry_b, eng):
    """The two entries in the order of the key's sides: by their side lists (_side_list), with
    Python's sort, so lists of other card_shas keep wave 2's card_sha order, and a mirror whose
    sides differ only in their pilot has one order whichever was asked for first."""
    return sorted([entry_a, entry_b], key=lambda e: _sort_key(_side_list(e, eng)))


def _env_seed_base():
    """The environment's DECKLAB_SEED_BASE as a seed base (an int of 0 or more), or None when it
    isn't set or isn't one (logged once)."""
    text = os.environ.get(SEED_BASE_ENV)
    if not text:
        return None
    try:
        value = int(text)
    except ValueError:
        value = -1
    if value < 0:
        _say_once(("seed_base", text), f"{SEED_BASE_ENV} must be a whole number of 0 or more, not {text!r}, so new "
                                       f"results start at seed base {seeds.SEED_BASE}.")
        return None
    return value


def _stop_file_check():
    """common.Stopped (saved_games 0) when the environment's DECKLAB_STOP_FILE names a file that
    exists: run() looks before it claims the matchup, so a stopped harness child neither
    saves an empty result nor moves a matchup's next_game past games it never played."""
    path = os.environ.get(STOP_FILE_ENV)
    if path and os.path.exists(path):
        stopped = common.Stopped(f"Stopped: {STOP_FILE_ENV}'s file {path} exists")
        stopped.saved_games = 0
        raise stopped


def _stop_file_progress(progress):
    """progress, wrapped to look for the stop file (the environment's DECKLAB_STOP_FILE) at most
    once every STOP_FILE_CHECK_S: once it exists, it raises common.Stopped, which stops the run
    as the page's Stop does. progress itself when the variable isn't set."""
    path = os.environ.get(STOP_FILE_ENV)
    if not path:
        return progress
    looked = [None]

    def checked(done, total, detail):
        now = time.monotonic()
        if looked[0] is None or now - looked[0] >= STOP_FILE_CHECK_S:
            looked[0] = now
            if os.path.exists(path):
                raise common.Stopped(f"Stopped: {STOP_FILE_ENV}'s file {path} exists")
        if progress is not None:
            progress(done, total, detail)

    return checked


@lifecycle.writing()
def update_result(key, results_dir, fn, paired=False):
    """Change a saved result under its matchup's lock (sim-wave3-contract.md section 8): claim the
    lock (_claim; while another run or update holds it, wait up to UPDATE_WAIT_S, then ForgeError
    BUSY), load the result, apply fn(result) (which changes it in place, or returns the new
    one), write it atomically and give the lock up. Returns the result written, or None (fn
    not called) when there's no such result. paired: a paired result (in <results_dir>/paired/).
    ForgeError NOT_SAVED when it can't be written; ValueError for a key that isn't 64 hex."""
    if not isinstance(key, str) or not KEY_RE.fullmatch(key):
        raise ValueError("a result's key must be 64 hex digits")
    folder = _results_dir(results_dir)
    if paired:
        folder = folder / PAIRED_FOLDER
    deadline = time.monotonic() + UPDATE_WAIT_S
    while True:
        try:
            lock = _claim(folder, key)
            break
        except ForgeError as e:
            if str(e) != BUSY or time.monotonic() >= deadline:
                raise
            time.sleep(UPDATE_RETRY_S)
    try:
        result = load(key, folder)
        if result is None:
            return None
        before = lifecycle.references(result)
        changed = fn(result)
        if changed is not None:
            result = changed
        path = folder / f"{key}.json"
        try:
            with lifecycle.writer(results_dir, deck_ids=lifecycle.references(result) - before):
                common._write_atomic(path, json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        except OSError as e:
            common._log(f"A matchup result couldn't be saved as {path}: {e}")
            raise ForgeError(NOT_SAVED) from None
        return result
    finally:
        _release(lock, folder / f"{key}.lock")


@lifecycle.writing("entry_a", "entry_b", save="save")
def _run(setup, key, eng, fmt, entry_a, entry_b, ordered, games, by, progress, results_dir, folder,
         workers, batch, seed_base, a_first, save, index, pool=None, local=False, exact=False, hooks=None):
    """run() once the matchup is claimed (folder: where its result is saved, the paired folder
    for a paired result; hooks: _hooks()'s)."""
    hooks = hooks or _hooks(games, entry_a, entry_b, numbers=None, seed_record=None, key=None, kind=None, extra=None,
                            override_sets=None, log_dir=None, log_every=1)
    existing = load(key, folder)
    if existing is None and save and (folder / f"{key}.json").exists():
        # Saving would replace games that can't be read now (a hand edit, a file still
        # open elsewhere, a newer Deck Lab's format): leave them be.
        common._log(f"The matchup result {folder / f'{key}.json'} can't be read, so the run wasn't started.")
        raise ForgeError(UNREADABLE)
    decklab = eng.get("kind") == engine.KIND_DECKLAB
    if existing is not None and _decklab(existing) != decklab:
        # Before the v2 engine id (engine.py) both kinds of a matchup share one key.
        common._log(f"The matchup result {folder / f'{key}.json'} was played with another engine, so the run "
                    f"wasn't started.")
        raise ForgeError(OTHER_ENGINE)
    if existing is not None and existing.get("kind") != hooks["kind"]:
        raise ValueError(f"The result saved under this key is {_kind_words(existing.get('kind'))}, not "
                         f"{_kind_words(hooks['kind'])}.")
    if decklab:
        return _run_v2(setup, key, eng, fmt, entry_a, entry_b, ordered, games, by, progress, folder, workers,
                       batch, seed_base, a_first, save, index, existing, pool, local, exact, hooks)
    if exact and batch is None and games not in GAME_CHOICES:
        batch = games           # any number of games: one batch
    specs = plan(games, existing, workers, batch=batch, seed_base=seed_base)
    if a_first and ordered[0]["card_sha"] != entry_a["card_sha"]:
        for spec in specs:
            spec["deck1"] = 1 - spec["deck1"]
    sides = existing["sides"] if existing else [_side(e) for e in ordered]
    names = [_log_names([n for _, n in _list_lines(e)], index) for e in ordered]
    procs = min(workers, len(specs))
    when = _now()
    late = []           # a Ctrl+C once the games are over: raised after the save
    records, fails, stopped, stats = _play(setup, fmt, key, ordered, specs, procs, progress, names, late)
    saved = None        # this run's games, once they're saved
    with _interrupts_held(note=lambda: late.append(True)):
        result = _record(setup, key, eng, fmt, entry_a, entry_b, ordered, existing, sides, specs, procs, when, by,
                         records, fails, stopped, stats)
        if existing is None:
            result.update(deepcopy(hooks["extra"]))
        if save:
            path = folder / f"{key}.json"
            try:
                common._write_atomic(path, json.dumps(result, ensure_ascii=False, separators=(",", ":")))
                saved = result["runs"][-1]["played"]
            except OSError as e:
                common._log(f"A matchup result couldn't be saved as {path}: {e}")
                if stopped is None:
                    raise ForgeError(NOT_SAVED) from None
    if stopped is None and late:
        stopped = KeyboardInterrupt()
    if stopped is not None:
        # The games saved before it goes on up (None: none were), for the command line's message.
        try:
            stopped.saved_games = saved
        except (AttributeError, TypeError):
            pass
        raise stopped
    error = result["runs"][-1]["error"]
    if error:
        raise ForgeError(f"No games could be played: {error}.")
    return result


def _kind_words(kind):
    return {"paired": "a paired test's", "experiment": "an experiment's"}.get(kind, "a matchup's")


def _record(setup, key, eng, fmt, entry_a, entry_b, ordered, existing, sides, specs, procs, when, by,
            records, fails, stopped, stats):
    """The result with a run's batches and run record added. A new result also gets the
    engine's fields (engine.result_fields), and each side, on every run, its own
    (engine.side_fields, with what the first kept batch's DLENGINE line said of that side:
    stats["echo"])."""
    result = existing or {
        "key": key, "format": fmt, "forge_version": setup["version"], "run_version": FORGE_RUN_VERSION,
        "settings": {"clock_s": setup["clock_s"], "ai": list(AI_PROFILES), "xmx": setup["xmx"]},
        "sides": sides, "runs": [], "batches": [], "failed": [], "created": when,
        **engine.result_fields(eng, ordered),
    }
    echo = stats.get("echo") or [{}, {}]
    for i, side in enumerate(result["sides"]):
        side.update(engine.side_fields(eng, side, echo[i]))
    if result["sides"][0]["card_sha"] == result["sides"][1]["card_sha"]:
        # One list under two ids (or the same one twice): side 0 is a's, side 1 b's.
        _seen(result["sides"][0], ordered[0], when)
        _seen(result["sides"][1], ordered[1], when)
    else:
        for e in (entry_a, entry_b):
            for side in result["sides"]:
                if side["card_sha"] == e["card_sha"]:
                    _seen(side, e, when)
    played = sum(len(r["games"]) for r in records)
    used = [r["seed"] for r in records] + [f["seed"] for f in fails]
    is_stop = isinstance(stopped, STOPS)
    error = None
    if stopped is not None and not is_stop:
        error = f"The run stopped because of an error in Deck Lab ({type(stopped).__name__})."
    elif not records and fails and stopped is None:
        error = fails[0]["error"]
    log = setup.get("card_log") or {"ready": False, "problem": "The card log wasn't set up for this run."}
    run_record = {
        "when": when, "by": by, "a": entry_a["card_sha"],      # "a": the list asked for first
        "asked": sum(s["games"] for s in specs), "played": played,
        "batches": len(specs), "played_batches": len(records),
        "partial": sum(1 for r in records if r.get("partial")),
        "workers": procs, "batch_games": specs[0]["games"],
        "seeds": [min(used), max(used)] if used else None,
        "wall_s": stats["wall_s"], "startup_s": stats["startup_s"],
        # How long it waited for a slot of the PC's budget before its first process started,
        # and the most processes it had at once ("workers" is the number it could have).
        "waited_s": stats.get("waited_s"), "most_running": stats.get("most_running"),
        "stopped": is_stop, "stopped_by": getattr(stopped, "by", None) if is_stop else None,
        "failed": len(fails), "failure": fails[0]["error"] if fails else None, "error": error,
        "card_log": bool(log.get("ready")),     # played with the card log: its batches have "cards"
    }
    if not run_record["card_log"]:
        run_record["card_log_problem"] = log.get("problem")     # why not, in a plain sentence
    result["runs"].append(run_record)
    result["batches"] = sorted(result["batches"] + records, key=lambda b: b["n"])
    result["failed"] = sorted(result["failed"] + fails, key=lambda b: b["n"])
    result["updated"] = _now()
    return result


# These two patch targets stay here as the package ownership guard requires.
def build_command(setup, fmt, deck1, deck2, games, seed, v2=None, pilots=None):
    """Forge's command line for one batch (run in setup["forge_dir"]): request_args() after
    the launch. With the card log ready (setup["card_log"], simjar.card_log()), DeckLabSim
    is started from the class path (_class_path_launch); else Forge's own sim with -jar,
    which can't play v2 (ValueError). The tests replace this with a fake Forge. pilots
    (wave 3): request_args'; the warm pool's one-shot chunks pass each seat's (pool.py)."""
    log = setup.get("card_log") or {}
    if log.get("ready"):
        launch = _class_path_launch(setup)
    elif v2 is not None:
        raise ValueError("plain Forge can't play the v2 engine's games")
    else:
        launch = ["-jar", setup["jar"]]
    more = {} if pilots is None else {"pilots": pilots}
    return [*_java(setup), *launch, *request_args(setup, fmt, deck1, deck2, games, seed, v2, **more)]


def _tidy_user_dir(user_dir):
    """After a run: delete the copies of their output Forge's processes left (forge.log,
    forge1.log...). Java opens them letting others delete them, so this also deletes
    those of another run still going (checked 2026-10-01), which does no harm: that
    Forge goes on writing to the deleted file. A hard kill leaves them for the next run."""
    for old in (user_dir / "Forge").glob("forge*.log"):
        try:
            old.unlink()
        except OSError:
            pass
# Implementations read this module for shared settings and patchable entry points.
from .runner_launch import (
    _preferences, request_args, _seat_pilots, _java, _class_path_launch,
    serve_command, serve_event, request_line, _prepare_user_dir, _first_use_marker)
from .runner_cold import (
    _Batch, _read, _save_failure_log, _failure_log, _kill, _slot, _play, _log_card_problems)
from .runner_v2 import (
    _run_v2, _plan_numbers, _blocks, _play_v2, _record_v2)
