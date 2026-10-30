"""Warm-pool chunks, workers, tickets and per-game record deltas.

pool.py keeps the public entry points and shared settings. Read those through
runtime so existing callers, overrides and test patches use one binding.
"""
import gzip
import os
import queue
import threading
import time
import traceback
from collections import deque
from copy import deepcopy
from pathlib import Path
from . import cardlog, common, pilots, runner, seeds

from . import pool as runtime


def _casts_delta(now, before):
    """What one game added to LogReader.casts ([{card: [casts, games cast in]}] per side)."""
    out = [{}, {}]
    for side in (0, 1):
        for card, numbers in now[side].items():
            was = before[side].get(card, (0, 0))
            if list(numbers) != list(was):
                out[side][card] = [a - b for a, b in zip(numbers, was)]
    return out


def _lands_delta(now, before):
    """What one game added to LogReader.lands ([{card: games}] per side)."""
    return [{card: n - before[side].get(card, 0) for card, n in now[side].items() if n != before[side].get(card, 0)}
            for side in (0, 1)]


def _cards_delta(now, before):
    """What one game added to a card record (cardlog.new_record()'s shape): its counts and
    the tallies of each card it changed, so cardlog.merge_record of every game's adds up to
    the chunk's record."""
    if now is None:
        return None
    out = {"v": now["v"], "games": now["games"] - before["games"], "bad": now["bad"] - before["bad"],
           "wins": [a - b for a, b in zip(now["wins"], before["wins"])],
           "first": [a - b for a, b in zip(now["first"], before["first"])]}
    for part in ("rows", "commander"):
        sides = now.get(part, [{}, {}])
        was = before.get(part, [{}, {}])
        out[part] = [{card: [a - b for a, b in zip(numbers, was[side].get(card, [0] * len(numbers)))]
                      for card, numbers in sides[side].items() if list(numbers) != list(was[side].get(card, []))}
                     for side in (0, 1)]
    if "tokens" in now:     # the tokens' peak counts (cardlog.tokens_less)
        out["tokens"] = cardlog.tokens_less(now["tokens"], before.get("tokens"))
    return out


class Chunk:
    """Games [first, first + games) of one run, played by one worker in one request."""

    def __init__(self, cid, ticket, first, games):
        self.cid, self.ticket, self.first, self.games = cid, ticket, first, games
        self.deck1 = seeds.deck1_side(first, ticket.flip)
        self.reader = runtime.LogReader(self.deck1, ticket.job["names"], card_log=True)
        self.lock = threading.Lock()        # the reader's feeding and closing (Ticket.stop)
        self.closed = None          # why it reads nothing more: "stop", "taint", "failed", "ended"
        self.reported = False       # its "end" has been sent to the run
        self.started = False        # its "start" has been sent (its request sent, or its process started)
        self.kept = 0               # games read (and sent to the run)
        self.worker = None
        self.request_id = None
        self.assigned_at = self.sent_at = self.last_at = self.header_at = None
        self.startup_s = None       # the start-up of a worker started for it (a one-shot
                                    # process's: to its header line)
        self.tail = deque(maxlen=runtime.TAIL_LINES)
        self.casts = [{}, {}]       # the reader's casts, lands and cards after the last game sent
        self.lands = [{}, {}]
        self.cards = deepcopy(self.reader.cards)
        # The log tee (the module docstring): its request's lines, and how many of them run to the
        # end of the last game read; None when the chunk isn't teed.
        log = ticket.job.get("log")
        self.tee = [] if log and seeds.block_of(first) % max(1, int(log.get("every") or 1)) == 0 else None
        self.tee_kept = 0

    def deck_order(self):
        """(deck 1's .dck, deck 2's) in this chunk's seat order."""
        dck = self.ticket.job["dck"]
        return (dck[0], dck[1]) if self.deck1 == 0 else (dck[1], dck[0])

    def seat_pilots(self):
        """[deck 1's pilot, deck 2's] in this chunk's seat order, from the job's stored sides'
        ("pilots": side i's at i), or None for a job without them (wave 2's)."""
        found = self.ticket.job.get("pilots")
        if not found:
            return None
        return [found[self.deck1], found[1 - self.deck1]]

    def request_pilots(self):
        """The pilots a request passes (runner.request_args' pilots): seat_pilots(), or None when
        every seat has the default pilot, which wave 2's request plays already (-a Default
        Default and no switches), so its command line stays wave 2's."""
        found = self.seat_pilots()
        if found is None or all(runtime._default_pilot(pilot) for pilot in found):
            return None
        return found


def _default_pilot(pilot):
    """Is pilot ({"profile", "switches"}) the default one (pilots.DEFAULT_PILOT)?"""
    return pilot.get("profile") == pilots.DEFAULT_PROFILE and not pilot.get("switches")


class Worker:
    """One Forge process of the pool: a warm "serve" worker, or (oneshot) a DeckLabSim process
    playing one chunk, when the run's launch can't serve (FALLBACK)."""

    def __init__(self, pool, ticket, oneshot=False):
        self.pool = pool
        self.launch, self.key = ticket.launch, ticket.launch_key
        self.setup = ticket.job["setup"]
        self.oneshot = oneshot
        self.proc = self.pid = None
        self.state = "new"          # "new", "starting", "idle", "busy", "quitting", "dying", "dead"
        self.lease = None           # its slots.Lease while it computes
        self.slot = self.last_slot = None
        self.chunk = None
        self.games = 0
        self.heap_mb = None
        self.started_at = self.ready_at = self.idle_since = self.quit_at = None
        self.fail_why = self.bye = self.killed = None
        self.pinned = False

    def marker(self):
        return runner._first_use_marker(Path(self.setup["user_dir"]), self.setup["version"])

    def warming(self):
        """Is it starting up: a serve worker not ready yet, or a one-shot process before its
        header line?"""
        return self.state in ("new", "starting") or (self.oneshot and self.ready_at is None
                                                     and self.state not in ("dying", "dead"))

    def describe(self):
        now = time.monotonic()
        return {"pid": self.pid, "state": self.state, "oneshot": self.oneshot, "slot": self.slot,
                "pinned": self.pinned, "games": self.games, "heap_mb": self.heap_mb,
                "idle_s": round(now - self.idle_since) if self.state == "idle" and self.idle_since else None,
                "playing": None if self.chunk is None else {"key": self.chunk.ticket.key[:12],
                                                            "first": self.chunk.first, "games": self.chunk.games}}


class Ticket:
    """A run's games in the pool: what pool.submit gives the run. events (a queue.Queue) holds
    what happens, as tuples, in order:
        ("start", cid, first, games, startup_s)     a chunk's request was sent (or its one-shot
                                                    process started); startup_s the start-up
                                                    waited for, None when its worker was warm
                                                    or it's a one-shot process (whose start-up
                                                    its "end" info has)
        ("echo", cid, by_side)                      its DLENGINE line, by side (engine_by_side)
        ("game", cid, game, casts, lands, cards)    one game (with "g") and what it adds
        ("end", cid, info)                          a chunk is over: info {"status" ("done",
                                                    "cancelled", "recycled", "died", "failed"),
                                                    "kept", "startup_s" (as "start"'s; a
                                                    one-shot process's once its header came),
                                                    "wall_s", "requeued", "recycled",
                                                    "failed": {"first", "games", "error"} or
                                                    None, "drop" (its games don't count),
                                                    "error" (the run fails: the sentence),
                                                    "bad", "card_problems" [[g, why]]}
        ("waiting", text or None)                   none of its chunks play, and why
        ("fallback", text)                          its chunks play as one-shot processes
        ("done", None | "stopped" | "failed" | "closed")
    stop() is the run's Stop: its queued games are dropped, each playing chunk's reader closed
    at once (so every game it read is in events) and its worker told to cancel; "done" follows
    at once."""

    def __init__(self, pool, job, seq):
        self.pool, self.job, self.seq = pool, job, seq
        self.key = job.get("key") or ""
        self.events = queue.Queue()
        self.launch = runtime.launch(job["setup"], job.get("engine"))
        self.launch_key = runtime._launch_key(self.launch)
        self.flip = int(job["flip"])
        self.low = bool(job.get("low"))
        self.limit = max(1, int(job.get("workers") or 1))
        self.cap = max(1, min(runtime.CHUNK_MAX, int(job.get("batch") or runtime.CHUNK_MAX)))
        self.queued = deque([int(a), int(b)] for a, b in job["ranges"] if int(b) > int(a))
        self.requeues = {}
        self.playing = set()
        self.stopped = False
        self.failed = None
        self.fallback = None
        self.waiting = None
        self.finished = False
        # The log tee's writes still going (Pool._tee), and the "done" held back until they end.
        self._tee_lock = threading.Lock()
        self._tee_writing = 0
        self._held_done = None

    def queued_games(self):
        return sum(b - a for a, b in self.queued)

    def emit(self, *event):
        if event[0] == "done":
            with self._tee_lock:
                if self._tee_writing:
                    self._held_done = event         # put once the last tee file is written
                    return
        self.events.put(event)

    def _tee_started(self):
        with self._tee_lock:
            self._tee_writing += 1

    def _tee_ended(self):
        with self._tee_lock:
            self._tee_writing -= 1
            held = self._held_done if not self._tee_writing else None
            if held is not None:
                self._held_done = None
        if held is not None:
            self.events.put(held)

    def stop(self):
        """Stop (the module docstring): returns once every game read is in events."""
        self.pool._stop_ticket(self, "stopped")


def _tee_write(ticket, folder, path, lines):
    """Write a teed chunk's lines gzip-compressed to path (atomically), then tell its ticket
    (Ticket._tee_ended), whatever happened."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        data = gzip.compress("".join(lines).encode("utf-8", errors="replace"), compresslevel=6, mtime=0)
        tmp = folder / f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError as e:
        runtime._say_once(("tee", str(folder)), f"A chunk's Forge output couldn't be written in {folder}: {e}")
    except Exception:
        common._log(f"A chunk's Forge output couldn't be written as {path}:\n{traceback.format_exc()}")
    finally:
        ticket._tee_ended()
