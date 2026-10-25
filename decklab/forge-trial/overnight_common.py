"""Shared settings, checkpoint files and identity checks for the overnight harness.

Existing overnight.<name> imports and patches forward here; every shared binding
has one home."""
import argparse
import ast
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[1]                  # the checkout under test (w3-run)
PLAN_FILE = HERE / "overnight-plan.json"
LEGS = HERE / "overnight_legs.py"
PY = sys.executable

PRIORITIES = (0, 1, 2, 3)
GAME_CHOICES = (200, 400, 800, 1600, 3200)     # the game counts wave 1's play takes
SMOKE_DIV = 80                  # --smoke divides game counts by this (at least SMOKE_MIN_GAMES)
SMOKE_MIN_GAMES = 4
SMOKE_WORKERS = 4
STOP_GRACE_S = 60               # a STOPped item's time to end before TerminateJobObject
SMOKE_STOP_GRACE_S = 10
DRIFT_WARM_GAMES = 800          # a drift probe's untimed warm-up: about 50 games for each of 16 new workers
MAX_RESTARTS = 2                # the supervisor's restarts of the controller in one session
OVERRUN = 2.0                   # a P1-P3 item past this many times its estimate is stopped (cut)
SOAK_PROBE_S = 15 * 60          # a soak probe every 15 min of D
DRIFT_PROBE_S = 35 * 60         # a drift probe every 30-40 min of D
POOL_POLL_S = 5 * 60            # a pool and memory poll every 5 min
OWN_PIDS_S = 30                 # the run's process list recorded this often
SMOKE_PERIODS = {"soak": 4 * 60, "drift": 8 * 60, "poll": 60}
START_WAIT_S = 60 * 60          # the idle gate's longest wait at the start
FILLER_CHUNK_S = 20 * 60        # the filler runs in pieces of at most this long (so probes fit between)
SERVER_PORT, IDLE_PORT = 8643, 8644
EXIT_STOPPED, EXIT_DEADLINE, EXIT_FAILFAST, EXIT_NEVER_IDLE, EXIT_REFUSED = 0, 10, 11, 12, 13
EXIT_OWNER_STOP = 14            # the owner's OUT/STOP file
DRILL_EXIT = 77                 # the drill's self-kill
WRONG_IDENTITY = ("The code, the jar, Forge, the overrides or the deck lists changed since this run started: "
                  "start a new run.")

# The wave 3 packages, and how features() tells each is built in the tree under test.
PACKAGES = ("S", "J3", "E3", "R", "A", "F", "V", "X", "H")
OPTIONAL = ("A", "F", "V", "X")
R_FEATURES = ("numbers", "seeds", "key", "kind", "extra", "override_sets", "log_dir")
CHECKS = {
    "S": [("seqstats", "look"), ("seqstats", "paired_diff"), ("seqstats", "field_row")],
    "J3": [],                               # simjar.PILOT_SWITCHES filled (below)
    "E3": [("cli", "_cmd_pilots"), ("cli", "_cmd_overrides"), ("overrides", "user_dir_for")],
    "R": [("cli", "_log_args")],            # and runner.RUN_FEATURES (below)
    "A": [("adaptive", "run_adaptive")],
    "F": [("field", "run_field"), ("field", "view"), ("cli", "_cmd_field")],
    "V": [("variants", "run_test"), ("variants", "aligned_dck"), ("cli", "_cmd_variant")],
    "X": [("experiment", "run"), ("experiment", "plan"), ("cli", "_cmd_experiment")],
    "H": [("cli", "_cmd_staged_move"), ("cli", "_cmd_soak_probe")],
}


# ============================================================ state.json

def load_state(out):
    path = Path(out) / "state.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_state(out, state):
    path = Path(out) / "state.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def log(out, text):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}"
    print(line, flush=True)
    try:
        with open(Path(out) / "log.txt", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _git(*args, cwd=TREE):
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _sha_file(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _forge_identity():
    """Forge's version and build (its jar's manifest), and the card-log jar this tree would start
    (simjar's jar_file name for today's stamp: the Forge jar's size and time, the card log's source,
    the patches that fit and javac), worked out without building anything. A value that can't be
    read is an "error: ..." string, compared like any other."""
    found = {}
    try:
        from decklab.lib.forge import install, simjar
        setup = install._setup()
        forge_jar = Path(setup["forge_dir"]) / setup["jar"]
        found["forge_version"] = setup["version"]
        found["forge_build"] = simjar.forge_build(forge_jar)
        stamp = simjar._stamp(simjar._tool(setup["java"], "javac"), forge_jar, forge_jar.stat(),
                              simjar.source_sha256(), simjar.forge_patches(forge_jar))
        found["jar_stamp"] = simjar.jar_file(setup["version"], stamp)
    except Exception as e:
        for name in ("forge_version", "forge_build", "jar_stamp"):
            found.setdefault(name, f"error: {type(e).__name__}")
    return found


def deck_lists():
    """A sha256 of every space's played lists: each deck's id with its target and substitute
    (owned-only) decklists, as decklab/lib/decks writes them back. Since phase 4 the decks are in
    Deck Lab's database, not in magic/, so this replaces the old magic_tree. It hashes the lists
    rather than the inventory's decks_revision, which moves with any deck save (the owned-vs-needed
    table refreshes every order and receipt makes included), so only a changed list blocks a
    resume. A deck whose text can't be parsed counts by its error. An "error: ..." string when the
    decks can't be read at all (no .venv, the database down): identity_differs always counts that
    as a difference."""
    sys.path.insert(0, str(TREE))
    try:
        from decklab.lib import venv
        venv.activate()
        from decklab.lib import inventory
        from decklab.lib.decks.deckfile import parse_deck
        from decklab.lib.decks.decklist import format_decklist
        digest = hashlib.sha256()
        for deck in sorted(inventory.current().decks.values(), key=lambda d: d.id):
            try:
                parsed = parse_deck(deck.data or b"", deck.slug, deck.kind, space=deck.space)
                lists = [format_decklist(parsed.target), format_decklist(parsed.owned or {})]
            except Exception as e:      # a deck that can't be parsed counts by its error
                lists = f"error: {type(e).__name__}: {e}"
            digest.update(json.dumps([deck.id, lists]).encode("utf-8") + b"\n")
        return digest.hexdigest()
    except Exception as e:      # recorded; identity_differs always counts it as a difference
        return f"error: {type(e).__name__}"


ALWAYS_DIFFER_ON_ERROR = ("deck_lists",)     # a run can't vouch for lists it couldn't read


def identity(main):
    """What must not change across a run's sessions (section 5.3)."""
    sys.path.insert(0, str(TREE))
    found = {"commit": _git("rev-parse", "HEAD"), "main_commit": _git("rev-parse", "HEAD", cwd=main),
             "deck_lists": deck_lists(),
             "simulation_sha": _sha_file(TREE / "decklab" / "simulation.json"),
             "sets_sha": _sha_file(TREE / "decklab" / "lib" / "forge" / "overrides" / "sets.json")}
    try:
        from decklab.lib.forge import common, overrides, simjar
        found["deployed_hash"] = overrides.deployed_hash(common._user_dir())
        found["source"] = simjar.source_sha256()
    except Exception as e:      # recorded, and compared like any other value
        found["deployed_hash"] = f"error: {type(e).__name__}"
    found.update(_forge_identity())
    scryfall = TREE / "decklab" / "data" / "scryfall"
    try:
        found["card_data_mtime"] = max((p.stat().st_mtime for p in scryfall.iterdir()), default=None)
    except OSError:
        found["card_data_mtime"] = None
    return found


def identity_differs(old, new):
    """The identity keys whose values differ, plus any ALWAYS_DIFFER_ON_ERROR key either side
    couldn't read (two sessions recording the same "error: ..." vouch for nothing)."""
    def unread(k):
        return k in ALWAYS_DIFFER_ON_ERROR and any(str(d.get(k, "")).startswith("error:") for d in (old, new))
    return sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k) or unread(k))


def _json_cmd(argv):
    """The JSON a command prints first (status prints its JSON, then lines of words), or None."""
    try:
        done = subprocess.run(argv, cwd=str(TREE), capture_output=True, text=True, timeout=600)
        return json.JSONDecoder().raw_decode(done.stdout.lstrip())[0]
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


# ============================================================ status and clean

def status_text(out):
    state = load_state(out)
    if state is None:
        return "No run in that folder."
    lines = [f"Run {state['run_id']}" + (" (smoke)" if state.get("smoke") else "")]
    for n, s in enumerate(state["sessions"], 1):
        left = s["deadline_epoch"] - time.time()
        lines.append(f"  session {n}: started {s['started']}, active {s.get('active_s', 0) / 60:.0f} min, "
                     f"paused {s.get('paused_s', 0) / 60:.0f} min, soak {s.get('soak_s', 0) / 60:.0f} min "
                     f"({s.get('soak_server_s', 0) / 60:.0f} on the server's pool), deadline in "
                     f"{max(0, left) / 60:.0f} min" + (f", exit {s['exit']}" if "exit" in s else ""))
    counts = {}
    for st in state["items"].values():
        counts[st.get("status")] = counts.get(st.get("status"), 0) + 1
    lines.append("  items: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items(), key=lambda x: str(x[0]))))
    running = [k for k, st in state["items"].items() if st.get("status") == "running"]
    if running:
        lines.append("  running: " + ", ".join(running))
    for d in state.get("dropped", []):
        lines.append(f"  dropped {d['id']}: {d['why']}")
    for k, st in state["items"].items():
        if st.get("status") == "skipped":
            lines.append(f"  skipped {k}: {st.get('note')}")
    return "\n".join(lines)
