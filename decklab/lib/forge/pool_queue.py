"""Warm-pool queue, worker lifecycle and chunk execution.

pool.py keeps the public entry points and shared settings. Read those through
runtime so existing callers, overrides and test patches use one binding.
"""
import math
import os
import threading
import time
from copy import deepcopy
from pathlib import Path
from . import cardlog, common, cores, engine, processes, runner, seeds, slots

from . import pool as runtime


class Pool:
    """Warm workers sharing one queue of chunks (the module docstring)."""

    def __init__(self, setup, *, name, idle_s=None, workers=None):
        self.name = name
        self.idle_s = runtime.idle_setting() if idle_s is None else max(0, idle_s)
        self._fixed = int(workers) if workers is not None else None
        if self._fixed is not None and self._fixed < 1:
            raise ValueError("a pool needs 1 worker or more")
        self.limit = self._fixed or int((setup or {}).get("workers") or runtime._workers_setting())
        self.budget = int((setup or {}).get("workers") or runtime._workers_setting())
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self._tickets = []
        self._workers = []
        self._seq = 0
        self._cid = 0
        self._closing = self._closed = False
        self._blocked = False           # the last try for a slot found none
        self._slot_at = 0.0             # when to try for a slot again
        self._want = None               # its slots.Want while it's blocked (others leave it slots they free)
        self._hold_until = 0.0          # until then it takes no slot while another process wants one
        self._cap_at = 0.0              # when the live-JVM cap is next checked
        self._deaths = {}               # {launch key: workers that died before they were ready}
        self._what = f"warm worker ({name} pool)"      # its slots' note (slots.status)
        self.service = None
        self._thread = threading.Thread(target=self._loop, name=f"pool-{name}", daemon=True)
        self._thread.start()

    # ------------------------------------------------ the API

    def submit(self, job):
        """Queue a run's games (the module docstring); PoolClosed once the pool is closing."""
        with self._lock:
            if self._closing:
                raise runtime.PoolClosed("The warm pool is closing, so the run wasn't started.")
            self._seq += 1
            ticket = runtime.Ticket(self, job, self._seq)
            if self._fixed is None:
                self.limit = int(job["setup"].get("workers") or self.limit)
            self.budget = int(job["setup"].get("workers") or self.budget)
            self._tickets.append(ticket)
            if not ticket.queued:
                self._done(ticket, None)
            self._wake.notify_all()
            return ticket

    def close(self, wait=None):
        """Close the pool (the module docstring)."""
        wait = runtime.QUIT_WAIT if wait is None else max(0.0, float(wait))
        with self._lock:
            self._closing = True
            for ticket in list(self._tickets):
                self._stop_ticket(ticket, "closed")
            for worker in list(self._workers):
                if wait <= 0 or worker.state in ("new", "starting") or worker.oneshot:
                    self._kill(worker, "closed")
                else:
                    self._quit(worker)
            self._wake.notify_all()
            deadline = time.monotonic() + wait
            while self._live() and time.monotonic() < deadline:
                self._wake.wait(min(0.1, max(0.0, deadline - time.monotonic())))
            for worker in list(self._workers):
                self._kill(worker, "closed")
            # The kills land at once; give the reader threads a moment to see each end.
            reap = runner.KILL_WAIT if wait > 0 else runtime.KILLED_WAIT
            deadline = time.monotonic() + reap
            while self._workers and time.monotonic() < deadline:
                self._wake.wait(0.05)
            self._closed = True
            self._wanted(False)
            self._wake.notify_all()
        if threading.current_thread() is not self._thread:
            self._thread.join(reap)

    def status(self):
        """The pool's state (the module docstring), for status() and the "pool" command."""
        with self._lock:
            workers = [w.describe() for w in self._workers]
            count = lambda *states: sum(1 for w in self._workers if w.state in states)     # noqa: E731
            return {"name": self.name, "limit": self.limit, "idle_s": self.idle_s, "closed": self._closing,
                    "workers": workers, "starting": count("new", "starting"), "busy": count("busy"),
                    "idle": count("idle"), "queued_games": sum(t.queued_games() for t in self._tickets),
                    "runs": [{"key": t.key[:12], "queued_games": t.queued_games(), "playing": len(t.playing),
                              "low": t.low, "fallback": t.fallback is not None}
                             for t in self._tickets if not t.finished],
                    "service": None if self.service is None else {"port": self.service.port}}

    # ------------------------------------------------ the pool's own thread

    def _live(self):
        return [w for w in self._workers if w.state != "dead"]

    def _loop(self):
        with self._lock:
            while not self._closed:
                now = time.monotonic()
                try:
                    self._watchdog(now)
                    self._retire(now)
                    self._dispatch(now)
                    self._report_waiting()
                except Exception as e:      # a bug here mustn't stop every run's games for good
                    runtime._say_once(("loop", type(e).__name__), f"The warm pool met an error: {e!r}")
                busy = self._workers or any(not t.finished for t in self._tickets)
                self._wake.wait(runtime.TICK_S if busy else None)

    def _dispatch(self, now):
        """Give chunks to workers (the module docstring's queue)."""
        if self._closing:
            return
        tickets = [t for t in self._tickets if t.queued and not t.stopped and not t.failed]
        if not tickets:
            self._blocked = False
            self._wanted(False)
            return
        if self._blocked and now < self._slot_at:
            return
        self._blocked = False
        queued = sum(t.queued_games() for t in tickets)
        normal = any(not t.low for t in tickets)
        for ticket in sorted(tickets, key=lambda t: (t.low, t.seq)):
            if ticket.low and normal:
                continue
            while ticket.queued and len(ticket.playing) < ticket.limit:
                worker = self._worker_for(ticket)
                if worker is None:
                    break
                lease = self._claim(worker)
                if lease is None:
                    self._blocked, self._slot_at = True, now + runtime.SLOT_RETRY_S
                    self._wanted(True)
                    return
                chunk = self._cut(ticket, queued)
                self._assign(worker, chunk, lease, now)
        self._wanted(False)

    def _worker_for(self, ticket):
        """A worker that can take ticket's next chunk now: an idle one of its launch, one of its
        launch still starting with no chunk, or a new one (not started yet) when the pool has
        room; else None (and, when an idle worker of another launch takes the room, it quits)."""
        live = [w for w in self._workers if w.state in ("new", "starting", "idle", "busy")]
        if ticket.fallback is None:
            mine = [w for w in live if w.key == ticket.launch_key and not w.oneshot and w.chunk is None
                    and w.state in ("idle", "starting")]
            if mine:
                return max(mine, key=lambda w: (w.state == "idle", w.idle_since or 0))
        if len(live) >= slots._limited(self.limit):     # the PC's worker limit too (slots.py)
            others = [w for w in live if w.state == "idle" and w.key != ticket.launch_key]
            if others:
                self._quit(min(others, key=lambda w: w.idle_since or 0))
            return None
        worker = runtime.Worker(self, ticket, oneshot=ticket.fallback is not None)
        marker = worker.marker()
        if not marker.exists() and any(w.warming() and w.marker() == marker for w in live):
            return None             # Forge's first start in this user folder: one alone
        return worker

    def _claim(self, worker):
        """A slot for worker (its own when it has one), or None when every slot is taken, or
        while the pool leaves the slots it freed to another process (_holding). Slots that
        can't be used at all give an empty Lease (logged once)."""
        if worker.lease is not None:
            return worker.lease
        if self._holding():
            return None
        try:
            lease = slots.claim(1, self.budget, wait=False, what=self._what, prefer=worker.last_slot)
        except (OSError, ValueError) as e:
            runtime._say_once("slots", f"Forge's slots in {slots.folder()} can't be used ({e}), so the warm pool runs "
                               f"its workers without counting other runs'.")
            return slots.Lease()
        return lease if lease else None

    def _cut(self, ticket, queued):
        """The next chunk of ticket's queue (the module docstring's size)."""
        start, end = ticket.queued[0]
        size = min(end, seeds.block_end(start)) - start
        size = min(size, runtime.CHUNK_MAX, ticket.cap, max(runtime.CHUNK_MIN, math.ceil(queued / (2 * self.limit))))
        if start + size >= end:
            ticket.queued.popleft()
        else:
            ticket.queued[0] = [start + size, end]
        self._cid += 1
        return runtime.Chunk(self._cid, ticket, start, size)

    def _assign(self, worker, chunk, lease, now):
        worker.lease = lease
        ids = lease.ids
        worker.slot = ids[0] if ids else None
        if worker.slot is not None:
            worker.last_slot = worker.slot
        worker.chunk, chunk.worker, chunk.assigned_at = chunk, worker, now
        chunk.ticket.playing.add(chunk)
        if worker.state == "new":
            self._start(worker, chunk, now)
        elif worker.state == "idle":
            self._pin(worker)
            self._send(worker, chunk, now)
        # "starting": the chunk is sent once the worker is ready (_ready)

    def _pin(self, worker):
        if worker.slot is not None and worker.pid is not None:
            worker.pinned = cores.pin(worker.pid, worker.slot)

    def _start(self, worker, chunk, now):
        """Start worker's process for chunk (a serve worker, or a one-shot one)."""
        setup, ticket = worker.setup, chunk.ticket
        try:
            env = runner._prepare_user_dir(Path(setup["user_dir"]))
        except OSError as e:
            common._log(f"Forge's user folder couldn't be prepared: {e}")
            worker.state = "dead"
            self._release(worker)
            self._fail(chunk, runtime.CANT_PREPARE)
            return
        try:
            if worker.oneshot:
                d1, d2 = chunk.deck_order()
                more = {} if chunk.request_pilots() is None else {"pilots": chunk.request_pilots()}
                argv = runner.build_command(setup, ticket.job["fmt"], d1, d2, chunk.games, ticket.job["base"],
                                            v2={"stream": ticket.job["stream"], "first": chunk.first}, **more)
            else:
                argv = worker.launch["argv"]
            worker.proc = processes.start_process(argv, cwd=setup["forge_dir"], env=env, stdin=not worker.oneshot)
        except (OSError, ValueError) as e:
            common._log(f"A Forge worker couldn't be started: {e}")
            worker.state = "dead"
            self._release(worker)
            reason = runtime._os_reason(e) if isinstance(e, OSError) else type(e).__name__
            self._fail(chunk, f"Forge couldn't be started ({reason})")
            return
        worker.pid, worker.started_at = worker.proc.pid, now
        worker.state = "busy" if worker.oneshot else "starting"
        self._workers.append(worker)
        self._pin(worker)
        if worker.oneshot:
            chunk.sent_at = chunk.last_at = now
            self._started(chunk, None)
        threading.Thread(target=self._read, args=(worker,), name=f"pool-worker-{worker.pid}", daemon=True).start()

    def _send(self, worker, chunk, now):
        """Send chunk's request to worker (ready and idle)."""
        job = chunk.ticket.job
        d1, d2 = chunk.deck_order()
        chunk.request_id = f"c{chunk.cid}"
        try:
            more = {} if chunk.request_pilots() is None else {"pilots": chunk.request_pilots()}
            args = runner.request_args({"decks_dir": job["setup"]["decks_dir"], "clock_s": job["setup"]["clock_s"]},
                                       job["fmt"], d1, d2, chunk.games, job["base"],
                                       v2={"stream": job["stream"], "first": chunk.first}, **more)
            line = runner.request_line(chunk.request_id, args)
        except ValueError as e:
            common._log(f"A chunk's request can't be sent to a warm worker: {e}")
            worker.chunk = None
            self._idle(worker, time.monotonic())
            self._fail(chunk, runtime.FORGE_ERROR)
            return
        worker.state = "busy"
        chunk.sent_at = chunk.last_at = now
        self._started(chunk, chunk.startup_s)
        try:
            worker.proc.stdin.write(line)
            worker.proc.stdin.flush()
        except (OSError, ValueError):
            self._kill(worker, None)        # it's going: its end (_exit) puts the chunk back

    def _started(self, chunk, startup_s):
        chunk.started = True
        chunk.ticket.emit("start", chunk.cid, chunk.first, chunk.games, startup_s)

    def _watchdog(self, now):
        """Kill what stopped responding: a worker not ready within runner.HEADER_TIMEOUT, a
        chunk with no game for its clock plus runner.GAME_GRACE (a one-shot process: no
        header line within HEADER_TIMEOUT), a worker that didn't quit when told."""
        for worker in list(self._workers):
            if worker.state == "starting" and now - worker.started_at > runner.HEADER_TIMEOUT:
                self._kill(worker, "startup")
            elif worker.state == "quitting" and worker.quit_at and now - worker.quit_at > runtime.QUIT_KILL_S:
                self._kill(worker, None)
            elif worker.state == "busy" and worker.chunk is not None and worker.chunk.sent_at is not None:
                chunk = worker.chunk
                if worker.oneshot and chunk.header_at is None:
                    late = now - chunk.sent_at > runner.HEADER_TIMEOUT
                else:
                    late = now - chunk.last_at > float(worker.setup["clock_s"]) + runner.GAME_GRACE
                if late:
                    if not chunk.reported:      # (a cancelled chunk's worker that never ends: only killed)
                        with chunk.lock:
                            chunk.closed = chunk.closed or "died"
                            chunk.reader.close()
                        self._requeue_rest(chunk, "died", runtime.NOT_RESPONDING)
                    self._kill(worker, runtime.NOT_RESPONDING)

    def _retire(self, now):
        """Idle workers quit: after idle_s, when their launch is no run's any more and another
        launch has come, or beyond the live-JVM cap (the module docstring's "Memory")."""
        idle = [w for w in self._workers if w.state == "idle"]
        if not idle:
            return
        wanted = {t.launch_key for t in self._tickets if not t.finished}
        for worker in idle:
            if now - worker.idle_since >= self.idle_s or (wanted and worker.key not in wanted):
                self._quit(worker)
        if now >= self._cap_at:
            self._cap_at = now + runtime.CAP_CHECK_S
            try:
                held = slots.status(self.budget)["slots"]
                others = sum(1 for row in held if row["held"] and not (row["pid"] == os.getpid()
                                                                       and row["what"] == self._what))
            except (OSError, ValueError):
                return
            live = [w for w in self._workers if w.state in ("new", "starting", "idle", "busy")]
            excess = len(live) - max(0, slots._limited(self.limit) - others)
            for worker in sorted((w for w in live if w.state == "idle"), key=lambda w: w.idle_since)[:max(0, excess)]:
                self._quit(worker)

    def _report_waiting(self):
        """Tell each run with games queued and none playing why it waits (once per change)."""
        for ticket in self._tickets:
            if ticket.finished or ticket.stopped or ticket.failed:
                continue
            text = None
            if ticket.queued and not ticket.playing:
                text = slots.WAITING if self._blocked else runtime.QUEUED
            if text != ticket.waiting:
                ticket.waiting = text
                ticket.emit("waiting", text)

    # ------------------------------------------------ workers' lines (their reader threads)

    def _read(self, worker):
        """A worker's reader thread: protocol lines to the pool, a chunk's lines to its reader."""
        proc = worker.proc
        current = worker.chunk if worker.oneshot else None
        try:
            for line in proc.stdout:
                if not worker.oneshot and line.startswith(runner.SERVE_PREFIX):
                    try:
                        event = runner.serve_event(line)
                    except ValueError:
                        runtime._say_once("protocol", f"A warm worker printed a line Deck Lab can't read: {line.strip()!r}")
                        continue
                    with self._lock:
                        current = self._protocol(worker, event, current)
                    continue
                if current is not None:
                    self._line(worker, current, line)
        except (OSError, ValueError):
            pass                # the pipe went away: the process was killed
        finally:
            for close in (proc.wait, proc.stdout.close, getattr(proc.stdin, "close", None)):
                try:
                    if close is not None:
                        close()
                except (OSError, ValueError):
                    pass
            with self._lock:
                self._exit(worker, current)

    def _protocol(self, worker, event, current):
        """One DLSERVE| line: the chunk the next lines belong to afterwards."""
        what = event["what"]
        if what == "ready":
            self._ready(worker, event)
            return None
        if what == "begin":
            chunk = worker.chunk
            return chunk if chunk is not None and chunk.request_id == event["id"] else None
        if what == "end":
            chunk = worker.chunk
            self._end(worker, chunk if chunk is not None and chunk.request_id == event["id"] else None, event)
            return None
        if what == "bye":
            worker.bye = event["why"]
        elif what == "fail":
            worker.fail_why = event["why"]
        elif what == "bad":
            runtime._say_once(("bad", event["text"]), f"A warm worker didn't understand a command: {event['text']!r}")
        return current

    def _line(self, worker, chunk, line):
        """One line of a chunk's output: its reader's, and the run's game when one ends."""
        header = taint = problem = False
        with chunk.lock:
            if chunk.closed:
                return
            if not line.startswith(cardlog.PREFIX):
                chunk.tail.append(line)
            if chunk.tee is not None:
                chunk.tee.append(line)
            reader = chunk.reader
            what = reader.feed(line)
            if what == "header":
                header = True
                # (check_echo's sentence ends with a full stop; a failed chunk's error, as v1's
                # batches', doesn't: the run's messages add their own.) seat_pilots: each seat's
                # pilot, in this chunk's seat order, from the stored sides (wave 3).
                problem = reader.failure(0, None) or \
                    (engine.check_echo(chunk.ticket.job["engine"], reader.engine,
                                       seat_pilots=chunk.seat_pilots()) or "").rstrip(".")
                if problem:
                    chunk.closed = "failed"
                    reader.close()
                else:
                    chunk.ticket.emit("echo", chunk.cid, reader.engine_by_side())
            elif what == "game":
                game = dict(reader.games[-1], g=chunk.first + len(reader.games) - 1)
                casts, lands = runtime._casts_delta(reader.casts, chunk.casts), runtime._lands_delta(reader.lands, chunk.lands)
                cards = runtime._cards_delta(reader.cards, chunk.cards)
                chunk.casts, chunk.lands = deepcopy(reader.casts), deepcopy(reader.lands)
                chunk.cards = deepcopy(reader.cards)
                chunk.kept = len(reader.games)
                if chunk.tee is not None:
                    chunk.tee_kept = len(chunk.tee)
                chunk.last_at = time.monotonic()
                chunk.ticket.emit("game", chunk.cid, game, casts, lands, cards)
                if game["r"] == "timeout" or game.get("ai_to"):
                    taint = True
                    chunk.closed = "taint"
                    reader.close()
        if header or taint:
            with self._lock:
                if header:
                    # The first game's clock starts here, not when the request went (or the
                    # one-shot process started): a slow start-up isn't the game's.
                    chunk.header_at = chunk.last_at = time.monotonic()
                    if worker.oneshot:
                        worker.ready_at = chunk.header_at
                        chunk.startup_s = round(chunk.header_at - chunk.sent_at, 2)
                        self._first_ready(worker)
                    if problem:
                        self._fail(chunk, problem)
                        if worker.oneshot:
                            self._kill(worker, None)
                        elif worker.state == "busy" and chunk.request_id:
                            self._command(worker, f"cancel\t{chunk.request_id}\n")
                if taint:
                    self._taint(worker, chunk)

    def _ready(self, worker, event):
        if worker.state != "starting":
            return
        if event["protocol"] != runner.SERVE_PROTOCOL:
            worker.fail_why = f"protocol {event['protocol']}"
            self._kill(worker, None)
            return
        now = time.monotonic()
        worker.ready_at = now
        self._first_ready(worker)
        self._deaths.pop(worker.key, None)
        chunk = worker.chunk
        if chunk is not None and not chunk.closed:
            chunk.startup_s = round(now - worker.started_at, 2)
            self._send(worker, chunk, now)
        else:
            worker.chunk = None
            self._idle(worker, now)
        self._wake.notify_all()

    def _first_ready(self, worker):
        """The first worker of a user folder new to a Forge version is up: note it."""
        marker = worker.marker()
        if not marker.exists():
            try:
                marker.touch()
            except OSError:
                pass

    def _end(self, worker, chunk, event):
        """A request's end line."""
        status = event["status"]
        worker.games += event["games"]
        heap = runner.SERVE_HEAP.search(event.get("detail") or "")
        if heap and status in ("done", "cancelled"):
            worker.heap_mb = int(heap[1])
        if chunk is not None and not chunk.reported:
            with chunk.lock:
                if not chunk.closed:
                    chunk.closed = "ended"
                reader = chunk.reader
                reader.close()
            if status == "done" and (reader.unsupported or reader.load_errors):
                self._fail(chunk, reader.failure(chunk.games, None), drop=True)
            elif status == "done" and chunk.kept >= chunk.games:
                self._report(chunk, "done")
            elif status == "cancelled":
                self._report(chunk, "cancelled")
            elif status == "error":
                common._log(f"A warm worker's request ended with an error: {event.get('detail')}")
                sentence = reader.failure(chunk.games, None) if reader.unsupported or reader.load_errors else None
                self._fail(chunk, sentence or runtime.FORGE_ERROR, drop=bool(sentence))
            else:       # recycle, or done with games missing
                self._requeue_rest(chunk, "recycled" if status == "recycle" else "died", runtime.PART_WAY)
        if worker.chunk is chunk:
            worker.chunk = None
        if worker.state in ("dying", "dead"):
            return
        now = time.monotonic()
        if worker.state == "quitting":
            self._release(worker)
        elif status in ("recycle", "error") or worker.bye:
            self._release(worker)
            worker.state = "quitting"
            worker.quit_at = now
            if status == "error":
                self._command(worker, "quit\n")
        else:
            self._idle(worker, now)
            xmx = runtime._xmx_mb(worker.setup.get("xmx"))
            if worker.games >= runtime.WORKER_MAX_GAMES or (worker.heap_mb and xmx and worker.heap_mb > runtime.HEAP_SHARE * xmx):
                self._quit(worker)
        self._cap_at = 0.0
        self._wake.notify_all()

    def _taint(self, worker, chunk):
        """A game that hit its clock or had an AI timeout: kill the worker at once, and put the
        chunk's later games back (the module docstring)."""
        if not chunk.reported:
            self._requeue_rest(chunk, "recycled", runtime.PART_WAY)
        self._kill(worker, None)

    def _exit(self, worker, current):
        """A worker's process has ended (its reader thread's last act)."""
        was = worker.state
        worker.state = "dead"
        if worker in self._workers:
            self._workers.remove(worker)
        self._release(worker)
        processes._end_process(worker.proc)
        chunk = worker.chunk
        worker.chunk = None
        code = worker.proc.returncode
        if chunk is not None and not chunk.reported:
            with chunk.lock:
                chunk.closed = chunk.closed or "ended"
                chunk.reader.close()
            reader = chunk.reader
            if worker.oneshot:
                if reader.load_errors or reader.unsupported:
                    self._fail(chunk, reader.failure(chunk.games, code), drop=True)
                elif code == 0 and chunk.kept >= chunk.games:
                    self._report(chunk, "done")
                else:
                    self._requeue_rest(chunk, "died", worker.killed or runtime.PART_WAY)
            elif worker.ready_at is None and not chunk.started:
                # It never started this chunk: its games go back as they were, uncounted.
                chunk.ticket.playing.discard(chunk)
                if not (chunk.ticket.stopped or chunk.ticket.failed):
                    chunk.ticket.queued.appendleft([chunk.first, chunk.first + chunk.games])
            else:
                self._requeue_rest(chunk, "died", worker.killed or runtime.PART_WAY)
        if not worker.oneshot and worker.ready_at is None and was != "new" and not self._closing \
                and worker.killed != "closed":
            self._start_failed(worker, code)
        self._wake.notify_all()

    def _start_failed(self, worker, code):
        """A serve worker ended before it was ready: when serve can't start, its launch's runs
        play one-shot (FALLBACK)."""
        why = None
        if worker.fail_why is not None or code == 3:
            why = runtime.FALLBACK_FAILED
        elif worker.killed == "startup":
            why = runtime.FALLBACK_SLOW.format(seconds=runner.HEADER_TIMEOUT)
        else:
            self._deaths[worker.key] = self._deaths.get(worker.key, 0) + 1
            if self._deaths[worker.key] >= 2:
                why = runtime.FALLBACK_DIED
        if why is None:
            return
        self._deaths.pop(worker.key, None)
        sentence = runtime.FALLBACK.format(why=why)
        runtime._say_once(("fallback", worker.key, why), sentence)
        for ticket in self._tickets:
            if ticket.launch_key == worker.key and not (ticket.finished or ticket.stopped or ticket.failed) \
                    and ticket.fallback is None:
                ticket.fallback = sentence
                ticket.emit("fallback", sentence)

    # ------------------------------------------------ chunks' ends

    def _info(self, chunk, status, **more):
        now = time.monotonic()
        info = {"status": status, "kept": chunk.kept, "startup_s": chunk.startup_s,
                "wall_s": round(now - chunk.sent_at, 2) if chunk.sent_at else 0.0,
                "requeued": 0, "recycled": 0, "failed": None, "drop": False, "error": None,
                "bad": chunk.reader.cards["bad"] if chunk.reader.cards else 0,
                "card_problems": [[chunk.first + n - 1, why]
                                  for n, why in chunk.reader.card_problems[:runtime.CARD_PROBLEMS_KEPT]]}
        info.update(more)
        return info

    def _report(self, chunk, status, **more):
        """chunk is over: tell its run, and free it from its worker."""
        if chunk.reported:
            return
        chunk.reported = True
        ticket = chunk.ticket
        self._tee(chunk, status, bool(more.get("drop")))
        ticket.playing.discard(chunk)
        if chunk.worker is not None and chunk.worker.chunk is chunk and chunk.worker.state in ("new", "starting"):
            chunk.worker.chunk = None
        if chunk.started:
            ticket.emit("end", chunk.cid, self._info(chunk, status, **more))
        self._done_if_over(ticket)

    def _tee(self, chunk, status, drop):
        """A teed chunk is over: take its lines (the module docstring's log tee) and write them
        in a thread of their own (_tee_write), so the compress and the write never hold the
        pool's lock; the chunk's run hears "done" once they're written."""
        with chunk.lock:
            lines, chunk.tee = chunk.tee, None
        if lines is None or drop or not chunk.kept:
            return
        log = chunk.ticket.job["log"]
        folder = Path(log["dir"]) / (chunk.ticket.key or "nokey")
        path = folder / f"{chunk.first}-{chunk.first + chunk.kept - 1}.log.gz"
        kept = lines if status == "done" else lines[:chunk.tee_kept]
        ticket = chunk.ticket
        ticket._tee_started()
        try:
            threading.Thread(target=runtime._tee_write, args=(ticket, folder, path, kept), daemon=True,
                             name="pool-log-tee").start()
        except RuntimeError:            # no thread to be had: written here, as before
            runtime._tee_write(ticket, folder, path, kept)

    def _requeue_rest(self, chunk, status, why):
        """chunk stopped part way (a taint, a recycle, its worker's death): its games after the
        last one read go back to the front of its run's queue, each at most MAX_REQUEUE times;
        those that can't, fail (the module docstring)."""
        ticket = chunk.ticket
        start, end = chunk.first + chunk.kept, chunk.first + chunk.games
        requeued, failed = 0, None
        if start < end and not (ticket.stopped or ticket.failed):
            stuck = next((g for g in range(start, end) if ticket.requeues.get(g, 0) >= runtime.MAX_REQUEUE), None)
            back_to = end if stuck is None else stuck
            if start < back_to:
                for g in range(start, back_to):
                    ticket.requeues[g] = ticket.requeues.get(g, 0) + 1
                ticket.queued.appendleft([start, back_to])
                requeued = back_to - start
            if stuck is not None:
                failed = {"first": stuck, "games": end - stuck, "error": why}
                self._failure_log(chunk, why)
        self._report(chunk, status, requeued=requeued, failed=failed, recycled=int(status == "recycled"))

    def _fail(self, chunk, sentence, drop=False):
        """chunk failed in a way that would fail every chunk of its run: its unplayed games
        (all of them, with drop) are a failed range, and the run's other chunks stop (its
        queued ones dropped, its playing ones cancelled, their games kept)."""
        ticket = chunk.ticket
        first = chunk.first if drop else chunk.first + chunk.kept
        failed = {"first": first, "games": chunk.first + chunk.games - first, "error": sentence}
        if failed["games"] <= 0:
            failed = None
        self._failure_log(chunk, sentence)
        if not chunk.started:
            self._started(chunk, chunk.startup_s)       # so its run counts it, and its failure
        if not ticket.failed:
            ticket.failed = sentence
            ticket.queued.clear()
        self._report(chunk, "failed", failed=failed, drop=drop, error=sentence)
        for other in list(ticket.playing):
            self._close_chunk(other)
        self._done_if_over(ticket)

    def _failure_log(self, chunk, error):
        runner._failure_log(chunk.ticket.key or "nokey", f"g{chunk.first}", error, chunk.tail)

    def _close_chunk(self, chunk):
        """Stop a playing chunk (Stop, or its run failing): its reader closed at once, its
        worker told to cancel (a one-shot process killed; a worker still starting keeps going,
        with no chunk), and its run told it's over, with the games it read."""
        with chunk.lock:
            chunk.closed = chunk.closed or "stop"
            chunk.reader.close()
        worker = chunk.worker
        if worker is not None and worker.chunk is chunk:
            if worker.oneshot:
                self._kill(worker, None)
            elif worker.state == "busy" and chunk.request_id:
                self._command(worker, f"cancel\t{chunk.request_id}\n")
            elif worker.state in ("new", "starting"):
                worker.chunk = None
        self._report(chunk, "cancelled")

    def _stop_ticket(self, ticket, why):
        with self._lock:
            if ticket.finished:
                return
            ticket.stopped = True
            ticket.queued.clear()
            for chunk in list(ticket.playing):
                self._close_chunk(chunk)
            self._done(ticket, why)
            self._wake.notify_all()

    def _done_if_over(self, ticket):
        # A stopped ticket's "done" says why (_stop_ticket sends it, once its chunks are closed).
        if not ticket.finished and not ticket.stopped and not ticket.playing and (not ticket.queued or ticket.failed):
            self._done(ticket, "failed" if ticket.failed else None)

    def _done(self, ticket, why):
        if ticket.finished:
            return
        ticket.finished = True
        ticket.emit("done", why)
        self._wake.notify_all()
        # It stays listed while a chunk of it may still end (a stopped one's cancel), then goes.
        self._tickets = [t for t in self._tickets if not (t.finished and not t.playing)]

    # ------------------------------------------------ workers' commands

    def _command(self, worker, text):
        try:
            worker.proc.stdin.write(text)
            worker.proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            self._kill(worker, None)

    def _quit(self, worker):
        """Tell worker to quit (an idle one goes at once; a playing one after its game)."""
        if worker.state in ("quitting", "dying", "dead"):
            return
        if worker.state in ("new", "starting") or worker.oneshot:
            self._kill(worker, None)
            return
        if worker.state == "idle":
            self._release(worker)
        worker.state, worker.quit_at = "quitting", time.monotonic()
        self._command(worker, "quit\n")

    def _kill(self, worker, why):
        if worker.state in ("dying", "dead"):
            return
        if worker.state == "new":
            worker.state = "dead"
            self._release(worker)
            return
        worker.killed = worker.killed or why
        worker.state = "dying"
        if worker.proc is not None:
            processes.kill_process(worker.proc)

    def _idle(self, worker, now):
        self._release(worker)
        worker.state, worker.idle_since = "idle", now

    def _release(self, worker):
        if worker.lease is not None:
            held = bool(worker.lease)
            worker.lease.release()
            self._slot_at = 0.0         # a slot came free: chunks waiting for one may have it now
            if held and self._others_want():
                # ... unless another process waits for one: it's left to them for HANDOFF_S, or
                # this pool, taking it back at once, would keep every slot until its queue is empty.
                self._hold_until = time.monotonic() + runtime.HANDOFF_S
        worker.lease, worker.slot = None, None

    def _others_want(self):
        """Does a process (or another pool) other than this pool wait for a slot now (slots.waiting)?"""
        return slots.waiting(exclude=self._want) > 0

    def _holding(self):
        """Is the pool leaving the slots it freed to another process that wants one (HANDOFF_S
        after it freed one)? Over as soon as nobody else wants one."""
        if time.monotonic() >= self._hold_until:
            return False
        if self._others_want():
            return True
        self._hold_until = 0.0
        return False

    def _wanted(self, blocked):
        """Hold the pool's want while it's blocked (a chunk ready and no slot for it), so other
        pools leave it the slots they free; give it up once it isn't."""
        if blocked and self._want is None:
            try:
                self._want = slots.want(self._what)
            except OSError:
                self._want = slots.Want(None, None)     # blocked all the same, unseen (tried once a block)
        elif not blocked and self._want is not None:
            self._want.release()
            self._want = None
