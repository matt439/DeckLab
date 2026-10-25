"""The warm pool (simulation wave 2, the report's R05 and R01b): Forge workers started once
("DeckLabSim serve", java/decklab/DeckLabServe.java) that play chunks of games from one
queue shared by every matchup waiting to be played, each worker computing only while it
holds a slot of the PC's budget (slots.py), pinned to one physical core while it does
(cores.py). Wave 2's contract (forge-trial/sim-wave2-contract.md, "Chunk policy", "Where a
run plays", "Slots and pinning") is what this follows.

    Pool(setup, *, name, idle_s=None, workers=None)
                            a pool of up to workers (config.json's forge_workers: the latest
                            run's, when not given) warm workers, each quitting after idle_s
                            (forge_pool_idle_s, idle_setting(); a local pool's: LOCAL_IDLE_S)
                            with nothing to play. setup (install._setup()) may be None
    pool.submit(job)        a run's games (runner._run_v2 builds job): a Ticket, whose events
                            the run reads, and whose stop() is the run's Stop
    pool.close(wait=None)   stop taking chunks; stop every run's ticket; tell each worker to
                            quit (one playing stops at its next game boundary), and kill those
                            still alive after wait seconds (QUIT_WAIT when None; 0 kills at
                            once, and waits KILLED_WAIT at most for their ends). Runs have
                            saved their games already: a stopped run closes its chunks'
                            readers at once and saves what they read
    pool.status()           {"name", "limit", "idle_s", "closed", "workers": [...], "starting",
                            "busy", "idle", "queued_games", "runs": [...], "service"}
    place(job, pool=None, local=False)
                            where a run plays (runner calls it): pool, a Pool or a session();
                            else the server's pool when this process is the server; else
                            the running server's, through its pool service, when one is up
                            and plays the same engine (a command line run), unless local;
                            else a pool of the run's own, closed when the run ends. Returns
                            a Placement (its ticket, "server", "local" or "remote", and the
                            Java heap the games are played with)
    session(local=False)    with session() as s: forge.run(..., pool=s): every run in the
                            block plays in one place: the server's pool (runs from the command
                            line submit to it through its pool service) unless local, none
                            is up, or it would play another engine; else a pool of this
                            process's own, closed at the block's end
    server_pool()           the server's Pool, or None (outside the server, or before
                            start_server_pool)
    start_server_pool()     the server starts its pool (lazily: workers start with the first
                            chunk) and its pool service (forge-pool-<pid>.json in slots.folder())
    stop_server_pool(wait)  the server stops both, after its runs have stopped and saved
    status()                pool.status() of this process's server pool, or None
    services()              the pool services running on this PC (the "pool" and "status"
                            commands); service_status(found) asks one for its status
    idle_setting()          config.json's forge_pool_idle_s, checked (an int of 0 or more)

The queue. A run's games are numbered (game g of a result is the same game wherever it's
played: seeds.py), and a run asks for the numbers lists.plan_v2 gives it, cut at every seat
block. One queue holds every run's: a free worker takes the oldest run (FIFO by submission,
runs by "replay" only once no other run has games queued) that has games queued and fewer
chunks playing than its workers allow, and cuts it a chunk of min(the block's rest,
CHUNK_MAX, the run's batch, max(CHUNK_MIN, ceil(Q / (2 W)))) games (Q: games queued over every
run, W: the pool's worker limit), so big queues get 25-game chunks and a run's last games
spread over several workers. A worker plays only chunks of the launch it was started with
(launch(): its command line, folder, user folder and whether game patches are on, from the
run's own setup), so a Forge upgrade, a new card-log jar or another Java never has old
workers playing a new engine's games; an idle worker whose launch no run wants any more
quits when one of another launch comes.

A chunk. The worker claims a slot (preferring the one it had: the same core), is pinned to
its core, gets a "play" request, and its reader thread feeds the request's lines to a
LogReader of the chunk's own. Each game is sent to the run as it's read, with what it adds
to the casts, land plays and card record (so a run's progress is live, and a stopped run
saves exactly the games it has); the run merges them into one batch record. A game that hit
its clock (r "timeout") or had an AI timeout taints the worker: the chunk's reader is closed
at once, the worker killed (whatever it plays next may be on a disturbed Random), and the
chunk's later games go back to the front of their run's queue with the same numbers; so do a
recycled request's (the worker says so itself: clock, ai_timeout, crash) and a dead worker's
(no end line, or the watchdog killed it). A game number goes back at most MAX_REQUEUE times;
the third time it fails, with the rest of its range. A chunk whose request ends with an error,
whose reader finds an unknown card or deck, or whose DLENGINE line isn't the run's engine
(engine.check_echo) fails at once, with the rest of its run (these would fail every chunk).
A worker quits after WORKER_MAX_GAMES games, or when its heap after GC passes HEAP_SHARE of
its -Xmx; a fresh one replaces it when needed.

Starting. While Forge's user folder is new to a Forge version (runner._first_use_marker),
one worker starts alone until it's ready. When serve can't start (it says it can't, exits
with 3, isn't ready within runner.HEADER_TIMEOUT, or two die before they're ready), the
runs of that launch play their chunks as one-shot DeckLabSim processes instead (the same
games), and say so (Ticket "fallback"); the next run tries serve again.

Sharing the PC. A worker gives its slot up at each chunk's end, and would take one back at
once for its next chunk. So that a pool with games queued doesn't keep every slot until its
queue is empty, a slot freed while another process (a command line run, a cardlog-check,
another checkout's pool) waits for one (slots.waiting: their wants) is left free for
HANDOFF_S, or until nobody else wants one, for them to take; the pool holds a want of its own
while it has a chunk ready and no slot for it, so other pools do the same for it.

Memory. Idle workers quit after idle_s; the pool also keeps no more workers alive than
forge_workers less the slots other processes hold (checked when a worker goes idle and every
CAP_CHECK_S while any is idle), so idle warm JVMs never sit beside another run's computing ones.

The pool service (the server's, for the command line): 127.0.0.1 only, a random port and
token, its address in forge-pool-<pid>.json in slots.folder(), JSON lines. A command line run
submits its job with its identity (the settings that must match, worked out per request on
both sides: identity()); the service plays it in the server's pool with its own launch and
streams each event back; each side sends a heartbeat every HEARTBEAT_S it has nothing else to
send. When the connection closes or the command line misses its heartbeat for
HEARTBEAT_TIMEOUT_S, the service stops that run's chunks (as Stop); a Stop on the command line
waits up to STOP_DRAIN_S for the games the service read before it. The command line keeps
planning, merging, locking and saving. When the server goes away mid-run (or says nothing for
HEARTBEAT_TIMEOUT_S), the run plays the games it hasn't been sent in a pool of its own
(Placement.local), so the command line's run still finishes.

Wave 3 (forge-trial/sim-wave3-contract.md section 8, package R). Each seat plays its side's pilot:
a job carries each stored side's pilot ("pilots"), and a chunk's request gives Forge's deck 1 the
pilot of the side seeds.deck1_side puts there (Chunk.seat_pilots: -a and -dlpilot, through
runner.request_args), and the chunk's DLENGINE line is checked against them
(engine.check_echo's seat_pilots). The launch identity and the compatibility identity add
engine.launch_fields (the user folder, its deployed overrides, the AI profile folder...), so a
deploy or another user folder never has old workers playing, and the compatibility identity
adds the pin mode (cores.pin_mode). A run of other override sets (runner.run's override_sets)
plays in a user folder of its own, so the server's pool service refuses it (its user folder and
overrides differ) and it plays in a pool of the command's own. The log tee: a job's "log"
({"dir", "every"}) has each chunk whose seat block's number is a multiple of "every" keep the
lines of its request (DLSERVE lines left out), written gzip-compressed, when the chunk ends, to
<dir>/<key>/<first g>-<last g>.log.gz: the lines up to its last game read (all of them when it
played every game), named by the games it kept; a chunk whose games don't count writes nothing.
The pool only takes the lines under its lock: a thread of the chunk's own compresses and writes
them, and its run's "done" waits until its files are written (Ticket.emit). Picking by seat block, not by a chunk's place in the queue, tees the same game numbers in every
result (an experiment arm's and its control's). The pool service carries both on its wire.

This part comes after runner.py (it imports it) and before servecheck.py; runner and install
reach it with an import inside the function that needs it."""
import gzip
import json
import math
import os
import queue
import re
import secrets
import socket
import socketserver
import threading
import time
import traceback
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from decklab.lib import config

from . import cardlog, common, cores, engine, install, pilots, processes, runner, seeds, simjar, slots
from .common import ForgeError, _os_reason
from .logreader import LogReader

CHUNK_MAX = 25                  # the most games in a chunk (a seat block's)
CHUNK_MIN = 5                   # the fewest, unless a block's rest or the run's batch is fewer
MAX_REQUEUE = 2                 # times a game number may go back to the queue
LOCAL_IDLE_S = 30               # a local pool's workers quit after this long with nothing to play
WORKER_MAX_GAMES = 2000         # a worker quits after this many games (a fresh one replaces it)
HEAP_SHARE = 0.75               # ... or when its heap after GC passes this share of its -Xmx
CAP_CHECK_S = 10                # how often the live-JVM cap is checked while workers are idle
SLOT_RETRY_S = 0.5              # how often a pool with chunks waiting tries again for a free slot
HANDOFF_S = 1.5                 # how long a slot freed while another process waits for one is left to it
                                # (claims poll every slots.POLL_S, 0.5 s; runner's and pools' every 0.5 s)
TICK_S = 0.2                    # the pool's longest wait between looks (watchdog, idle, slots)
QUIT_WAIT = 3                   # seconds close() waits for workers to quit before it kills them
KILLED_WAIT = 1                 # ... and, with wait 0, for the killed workers' reader threads (the close
                                # and logoff handlers have about 5 s in all; otherwise runner.KILL_WAIT)
QUIT_KILL_S = 10                # a worker told to quit that's still alive after this is killed
HEARTBEAT_S = 5                 # a command line run's heartbeat to the pool service (and the service's back)
HEARTBEAT_TIMEOUT_S = 20        # ... and how long either side waits for one
STOP_DRAIN_S = 1                # how long a stopped command line run waits for the service's last games
CONNECT_S = 2                   # seconds to connect to a pool service
ANSWER_S = 60                   # seconds a service may take to answer a submit (it may build the jar)
SERVICE_PROTOCOL = 1
SERVICE_GLOB = "forge-pool-*.json"
TAIL_LINES = runner.TAIL_LINES
CARD_PROBLEMS_KEPT = 3          # a chunk's card-log problems sent to its run

# What a run's progress says (detail["waiting"]) while none of its chunks play because other
# runs' chunks hold every worker (slots.WAITING when every slot of the PC's budget is taken).
QUEUED = "Waiting for other matchups ahead in the queue."
# Why a chunk failed (the run's "failure", as v1's batches' sentences).
FORGE_ERROR = "Forge stopped with an error"
NOT_RESPONDING = "Forge stopped responding"
PART_WAY = "Forge kept stopping part way through these games"
CANT_PREPARE = "Deck Lab can't write Forge's settings in its data folder"
# Why a run's chunks play as one-shot processes (Ticket.fallback; the run record's "fallback").
FALLBACK = "Forge's warm workers couldn't start ({why}), so these games play one process at a time."
FALLBACK_FAILED = "they couldn't set Forge up to play again and again"
FALLBACK_SLOW = "none was ready within {seconds} seconds"
FALLBACK_DIED = "two stopped before they were ready"
CLOSED = "The warm pool closed before the run finished."
LOST = "The server's warm pool went away, so the rest of this run plays in a pool of this command's own."
# What the command line says when it can't play in the server's pool (one stderr line).
OTHER_SETTINGS = ("The server's warm pool plays with other settings ({what}), so this run plays in a pool of "
                  "this command's own.")
IDENTITY_WORDS = {"protocol": "the pool's protocol", "source": "the card log's source", "jar": "the card log's jar",
                  "forge": "Forge's version", "build": "Forge's build", "game_patches": "the game patches",
                  "engine": "the engine", "java": "Java", "xmx": "the Java heap (forge_xmx)",
                  "forge_pin": "pinning (forge_pin)", "pin_mode": "the pin mode (DECKLAB_PIN_MODE)"}
# The words for each of engine.launch_fields' fields (the identities' "launch" part, wave 3).
LAUNCH_WORDS = {"overrides": "the card-script overrides", "user_dir": "Forge's user folder",
                "aiprofiles": "the AI profile folder", "performance_mode": "Forge's PERFORMANCE_MODE",
                "game_patches": "whether Deck Lab's game patches are on",
                "decision_log": "the decision log (forge_decision_log)"}
PROFILE_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")        # a pilot's profile name (sim-wave3-contract.md 3.5)
CARD_LOG_OFF = "the card log can't be used there"
SERVER_STOPPING = "the server is stopping"
NAME_RE = re.compile(r"[0-9a-f]{64}\.dck")      # a .dck a service plays (runner._write_decks' names)

_said = set()
_said_lock = threading.Lock()


def _say_once(what, text):
    """Log text the first time what comes up in this process."""
    with _said_lock:
        if what in _said:
            return
        _said.add(what)
    common._log(text)


def idle_setting(settings=None):
    """config.json's forge_pool_idle_s: an int of 0 or more (not a bool or "900"), else the
    default, config.DEFAULTS', with one log line."""
    default = config.DEFAULTS["forge_pool_idle_s"]
    if settings is None:
        try:
            settings = common._settings()
        except Exception:
            settings = {}
    value = settings.get("forge_pool_idle_s", default)
    if type(value) is int and value >= 0:
        return value
    _say_once(("forge_pool_idle_s", repr(value)), f"config.json's forge_pool_idle_s must be a whole number of 0 or "
                                                  f"more, not {value!r}, so warm workers quit after {default} s idle.")
    return default


def _workers_setting():
    """config.json's forge_workers as install._setup reads it (1 or more; else the default)."""
    try:
        value = int(common._settings()["forge_workers"])
    except Exception:
        value = 0
    return value if value >= 1 else config.DEFAULTS["forge_workers"]


def _xmx_mb(text):
    """-Xmx's size in MB ("1024m", "2g", "1073741824"), or None when it can't be read."""
    m = re.fullmatch(r"\s*(\d+)\s*([kKmMgGtT]?)\s*", str(text or ""))
    if not m:
        return None
    number, unit = int(m[1]), m[2].lower()
    return number * {"": 1 / (1 << 20), "k": 1 / 1024, "m": 1, "g": 1024, "t": 1 << 20}[unit]


def launch(setup, eng=None):
    """How a worker playing a run of setup is started (wave 2's contract "launch identity"):
    {"argv": runner.serve_command(setup), "cwd", "user_dir", "game_patches"}, and with eng (the
    run's engine, wave 3) "fields": engine.launch_fields(setup, eng), which a worker keeps from
    its start (the user folder's deployed overrides, the AI profile folder...). ValueError when
    the card log isn't ready (setup["card_log"])."""
    found = {"argv": [str(arg) for arg in runner.serve_command(setup)], "cwd": str(setup["forge_dir"]),
             "user_dir": str(setup["user_dir"]), "game_patches": setup.get("game_patches") is not False}
    if eng is not None:
        found["fields"] = engine.launch_fields(setup, eng)
    return found


def _launch_key(found):
    return json.dumps(found, sort_keys=True)


# ============================================================ the pool

class PoolClosed(ForgeError):
    """submit() on a pool that's closing."""


# ============================================================ where a run plays

class Placement:
    """Where a run plays (place()): ticket (its Ticket, or a remote one), where ("server",
    "local" or "remote"), xmx (the Java heap its games are played with), close() (closes a
    pool of the run's own), local(job) (a local ticket for what a run lost with the server:
    the module docstring)."""

    def __init__(self, ticket, where, xmx, owned=None, setup=None):
        self.ticket, self.where, self.xmx = ticket, where, xmx
        self._owned = owned
        self._setup = setup

    def local(self, job):
        """Play job in a pool of the run's own from now on."""
        if self._owned is None:
            self._owned = _own_pool(job)
        self.where = "local"
        self.ticket = self._owned.submit(job)
        return self.ticket

    def close(self, wait=None):
        """Close a pool of the run's own (Pool.close(wait): a stopped run's games are saved
        already, so it passes 0)."""
        if self._owned is not None:
            self._owned.close(wait)
            self._owned = None


def place(job, *, pool=None, local=False):
    """Submit a run's job where it plays (the module docstring): a Placement."""
    if pool is not None:
        if isinstance(pool, Session):
            return pool._place(job)
        if isinstance(pool, Pool):
            return Placement(pool.submit(job), "server" if pool is _server else "local", job["setup"]["xmx"])
        return pool.place(job)          # a stand-in (the tests')
    if _server is not None:
        return Placement(_server.submit(job), "server", job["setup"]["xmx"])
    if not local:
        placed, why = _remote(job)
        if placed is not None:
            return placed
        if why:
            common._log(why)
    own = _own_pool(job)
    return Placement(own.submit(job), "local", job["setup"]["xmx"], owned=own)


def _own_pool(job):
    """A pool of a run's own: as many workers as the run may have (its "workers", up to the
    PC's budget), so its chunks are cut for those (a session's pool, shared by its runs,
    keeps forge_workers)."""
    budget = int(job["setup"].get("workers") or _workers_setting())
    return Pool(job["setup"], name="local", idle_s=LOCAL_IDLE_S,
                workers=max(1, min(int(job.get("workers") or budget), budget)))


class Session:
    """session()'s value: runs given it as pool play in one place (the module docstring)."""

    def __init__(self, local):
        self.local = local
        self._pool = None
        self._lock = threading.Lock()
        self._said = False

    def _place(self, job):
        if _server is not None:
            return Placement(_server.submit(job), "server", job["setup"]["xmx"])
        if not self.local:
            placed, why = _remote(job)
            if placed is not None:
                return placed
            with self._lock:
                said, self._said = self._said, True
            if why and not said:
                common._log(why)
        with self._lock:
            if self._pool is None:
                self._pool = Pool(job["setup"], name="session", idle_s=LOCAL_IDLE_S)
            own = self._pool
        return Placement(own.submit(job), "local", job["setup"]["xmx"])

    def close(self):
        with self._lock:
            own, self._pool = self._pool, None
        if own is not None:
            own.close()


@contextmanager
def session(*, local=False):
    """A context manager whose value runs pass as run(pool=...): see the module docstring."""
    value = Session(local)
    try:
        yield value
    finally:
        value.close()


# ============================================================ the server's pool and its service

_server = None              # the server's Pool (start_server_pool)
_server_lock = threading.Lock()


def server_pool():
    """The server's Pool, or None."""
    return _server


def start_server_pool():
    """Start the server's pool and its service (server.py, at start-up). Its workers start
    with the first chunk. The service not starting is logged; the pool still serves the
    server's own runs."""
    global _server
    with _server_lock:
        if _server is not None:
            return _server
        _server = Pool(None, name="server")
        try:
            _server.service = _Service(_server)
        except OSError as e:
            common._log(f"The warm pool's service for the command line couldn't start ({e}); command line runs "
                        f"play in pools of their own.")
        return _server


def stop_server_pool(wait=None):
    """Stop the server's pool (server.py, once its runs have stopped and saved): its service
    first (no more command line runs), then the pool (close(wait))."""
    global _server
    with _server_lock:
        own, _server = _server, None
    if own is None:
        return
    if own.service is not None:
        own.service.close()
    own.close(wait)


def status():
    """This process's server pool's status(), or None when there's none."""
    own = _server
    return None if own is None else own.status()


# Implementations read this module for shared settings and patchable entry points.
from .pool_models import (
    _casts_delta, _lands_delta, _cards_delta, Chunk, _default_pilot, Worker, Ticket, _tee_write)
from .pool_queue import Pool
from .pool_service import (
    identity, _differences, _wire, _wire_pilot, _wire_log, _service_job, _send_line,
    _Handler, _TCPServer, _Service, _static_identity, _tidy_services, services,
    _connect, service_status, _remote, _RemoteTicket)
