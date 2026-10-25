"""The goldfish package's runs and saved results: simulate() plays the games
in chunks (in this process or in worker processes), and get_or_simulate(),
cache_key() and saved_result() keep results in decklab/data/goldfish/.

Tests patch GOLDFISH_VERSION, CACHE_DIR, CACHE_MAX_FILES, CHUNK_GAMES,
default_workers, simulate, get_or_simulate and _log here, on this module,
which is the only place they're defined and read.
"""
import hashlib
import json
import multiprocessing
import os
import re
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from decklab.lib import cards, config

from .common import BIG_SPELL, COMMANDER_1V1_NOTE, DEFINITIONS, RULES, SETUPS, SETUPS_BY_KIND, SOURCES
from .engine import _add_counts, _new_counts
from .model import compile_deck
from .results import _summary
from .workers import _NewProcessGroups, _run_chunk, _start_worker

# Saved results are keyed by GOLDFISH_VERSION. The rules are in model.py (how a
# card is read) and engine.py (how a game is played): a change there that can
# change a result must raise it.
GOLDFISH_VERSION = 5        # raise when a rule changes, so saved results are recomputed
CACHE_DIR = config.DATA / "goldfish"
CACHE_MAX_FILES = 1000      # the oldest saved results go past this
DEFAULT_GAMES = 100_000     # per setup (PLAN.md part 5: "about 100,000 games per deck")
DEFAULT_TURNS = 8           # PLAN.md: "the first 6-8 turns"
MAX_TURNS = 20
MAX_GAMES = 2_000_000
CHUNK_GAMES = 2_000         # games per chunk: fixed, so results don't depend on the workers


def _deck_key(sections):
    """The main deck and commander as sorted [section, name, copies], names
    resolved to Scryfall's (printings don't matter)."""
    counts = Counter()
    for section in ("Commander", "Deck"):
        for line in sections.get(section, []):
            name = cards.resolve(line.name) or cards.fold(line.name)
            counts[(section, name)] += line.quantity
    return [[s, n, q] for (s, n), q in sorted(counts.items())]


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _prepare(sections, kind, seed):
    model, info = compile_deck(sections, kind)
    deck_key = _deck_key(sections)
    seed_source = "given"
    if seed is None:
        seed = int(_digest([deck_key, kind])[:8], 16)
        seed_source = "decklist"
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError(f"seed must be a whole number of 0 or more, not {seed!r}")
    return model, info, deck_key, seed, seed_source


def _check_settings(games, turns):
    for name, value, top in (("games", games, MAX_GAMES), ("turns", turns, MAX_TURNS)):
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= top:
            raise ValueError(f"{name} must be a whole number from 1 to {top}, not {value!r}")


def _chunk_seed(seed, setup, index):
    return int(_digest([seed, setup, index])[:16], 16)


def _setup_text(setup, kind):
    text = SETUPS[setup]["text"]
    if kind == "commander" and setup != "multiplayer":
        text += " " + COMMANDER_1V1_NOTE
    return text


def default_workers():
    """The worker process count from config ("goldfish_workers")."""
    try:
        return max(1, int(config.load().get("goldfish_workers") or 1))
    except (OSError, ValueError, TypeError):
        return max(1, int(config.DEFAULTS["goldfish_workers"]))


def simulate(sections, kind, games=DEFAULT_GAMES, turns=DEFAULT_TURNS, seed=None, workers=None,
             progress=None, mulligans=True):
    """Simulate games (per setup) of turns turns and return the JSON-safe
    result the package docstring describes. workers is the number of
    processes (None: config's "goldfish_workers"; 1 runs in this process);
    progress(done, total) is called with games finished as chunks finish.
    mulligans=False keeps every 7 (for checking the maths)."""
    _check_settings(games, turns)
    model, info, _, seed, seed_source = _prepare(sections, kind, seed)
    setups = SETUPS_BY_KIND[kind]
    model_key = _digest(model)
    tasks = []
    for setup in setups:
        for index, start in enumerate(range(0, games, CHUNK_GAMES)):
            n = min(CHUNK_GAMES, games - start)
            tasks.append((setup, (model_key, model, setup, turns, n, _chunk_seed(seed, setup, index),
                                  bool(mulligans))))
    workers = default_workers() if workers is None else max(1, int(workers))
    workers = min(workers, len(tasks))
    total = games * len(setups)
    done = 0
    counts = {s: _new_counts(turns, len(model["colours"])) for s in setups}
    started = time.perf_counter()
    if workers <= 1:
        for setup, task in tasks:
            _add_counts(counts[setup], _run_chunk(task))
            done += task[4]
            if progress:
                progress(done, total)
    else:
        context = multiprocessing.get_context("spawn")
        # The workers leave Ctrl+C to the process that started them, which stops the run, and end
        # if it's killed (_start_worker).
        with ProcessPoolExecutor(max_workers=workers, mp_context=context, initializer=_start_worker) as pool:
            with _NewProcessGroups():       # submit() starts the worker processes
                futures = {pool.submit(_run_chunk, task): (setup, task[4]) for setup, task in tasks}
            try:
                for future in as_completed(futures):
                    setup, n = futures[future]
                    _add_counts(counts[setup], future.result())
                    done += n
                    if progress:
                        progress(done, total)
            except BaseException:
                # A chunk failed, or progress() stopped the run (the server is stopping): the
                # chunks not started yet are dropped rather than played.
                pool.shutdown(wait=True, cancel_futures=True)
                raise
    seconds = time.perf_counter() - started
    big_in_deck = sum(1 for cid in model["deck"] + model["commanders"]
                      if any(o[0] >= BIG_SPELL for o in model["cards"][cid]["options"]))
    warnings = list(info["warnings"])
    size = len(model["deck"])
    if size < 7 + turns:
        # On the draw a game sees 7 + turns cards; a real game is lost on drawing from an empty library.
        play = f" (turn {size - 5} on the play)" if size - 5 <= turns else ""
        warnings.append(f"This deck has {size} cards to draw from, so from turn {size - 6} on the draw{play} "
                        "there's no card left to draw, and a real game would be lost then. Here those turns go on "
                        "without a draw, so the numbers for them mean little.")
    return {
        "version": GOLDFISH_VERSION,
        "kind": kind,
        "games": games,
        "turns": turns,
        "seed": seed,
        "seed_source": seed_source,
        "mulligans": bool(mulligans),
        "workers": workers,
        "seconds": round(seconds, 2),
        "chunks": len(tasks),
        "deck": info["deck"],
        "setups": [{"id": s, "label": SETUPS[s]["label"], "text": _setup_text(s, kind)} for s in setups],
        "results": {s: _summary(counts[s], s, turns, model["colours"], big_in_deck) for s in setups},
        "cards": {"special": info["special"], "not_modelled": info["not_modelled"],
                  "unresolved": info["unresolved"]},
        "rules": list(RULES),
        "definitions": dict(DEFINITIONS),
        "warnings": warnings,
        "sources": {k: dict(v) for k, v in SOURCES.items()},
    }


# ================================================================= cache

def cache_key(sections, kind, games=DEFAULT_GAMES, turns=DEFAULT_TURNS, seed=None, mulligans=True):
    """The name a result is saved under: a hash of the main deck and
    commander, the cards as the simulation reads them, the settings, the
    seed and GOLDFISH_VERSION."""
    model, _, deck_key, seed, _ = _prepare(sections, kind, seed)
    return _digest([deck_key, model, kind, games, turns, seed, bool(mulligans), GOLDFISH_VERSION])[:40]


def saved_result(key, cache_dir=None):
    """The result saved under key (from cache_key()) with "cached": True, or
    None when there's none, it can't be read, or an older version made it.
    Never simulates, so it answers at once (the server checks it first)."""
    if not (isinstance(key, str) and re.fullmatch(r"[0-9a-f]{40}", key)):
        raise ValueError(f"not a cache key: {key!r}")
    folder = Path(cache_dir) if cache_dir is not None else CACHE_DIR
    try:
        result = json.loads((folder / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (isinstance(result, dict) and result.get("cache_key") == key
            and result.get("version") == GOLDFISH_VERSION):
        result["cached"] = result["saved"] = True
        return result
    return None


def get_or_simulate(sections, kind, games=DEFAULT_GAMES, turns=DEFAULT_TURNS, seed=None, workers=None,
                    progress=None, mulligans=True, cache_dir=None, refresh=False):
    """A saved result for these settings, or simulate() and save it.
    Adds "cache_key" and "cached" (True when it came from the cache)."""
    _check_settings(games, turns)
    folder = Path(cache_dir) if cache_dir is not None else CACHE_DIR
    key = cache_key(sections, kind, games, turns, seed, mulligans)
    path = folder / f"{key}.json"
    if not refresh:
        result = saved_result(key, folder)
        if result is not None:
            return result
    result = simulate(sections, kind, games, turns, seed, workers, progress, mulligans)
    result["cache_key"] = key
    try:
        _save(folder, path, result)
    except OSError as e:
        # The numbers are still good: show them, and work them out again next time.
        _log(f"The practice-hand result couldn't be saved as {path}: {e}")
        reason = e.strerror or type(e).__name__
        result["warnings"].append(f"This result couldn't be saved on the PC ({reason}), so it will be worked "
                                  "out again next time.")
        result["saved"] = False
    else:
        result["saved"] = True
    result["cached"] = False
    return result


def _save(folder, path, result):
    """Write result as path (whole or not at all), then prune the folder."""
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=path.stem[:12], suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _prune(folder)


def _log(text):
    """A line for the server window (stderr, which pythonw doesn't have)."""
    if sys.stderr is not None:
        sys.stderr.write(text.rstrip("\n") + "\n")
        sys.stderr.flush()


def _prune(folder):
    """Delete the oldest saved results past CACHE_MAX_FILES."""
    files = []
    for path in folder.glob("*.json"):
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            pass                # deleted meanwhile
    files.sort()
    for _, old in files[:max(0, len(files) - CACHE_MAX_FILES)]:
        try:
            old.unlink()
        except OSError:
            pass
