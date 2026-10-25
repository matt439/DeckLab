"""Cold Forge batches, process readers, watchdogs and failure logs.

runner.py keeps the public entry points and shared settings. Read those through
runtime so existing callers, overrides and test patches use one binding.
"""
import queue
import threading
import time
from collections import deque
from . import cardlog, common, processes, slots

from . import runner as runtime


class _Batch:
    """One Forge process playing one batch."""

    def __init__(self, spec):
        self.spec = spec
        self.proc = None
        self.thread = None
        self.reader = None
        self.tail = deque(maxlen=runtime.TAIL_LINES)
        self.started = self.header_at = self.last_game = self.ended = None
        self.killed = None          # why it was killed: the watchdog's reason, or STOP_KILL
        self.error = None
        self.partial = False        # stopped part way: only the games it finished are kept
        self.slot = None            # the slots.Lease its process runs in, until it ends


def _read(batch, events):
    """A reader thread: feed every line of one process to its LogReader, and tell the
    main loop about each header line, each game and the end."""
    try:
        for line in batch.proc.stdout:
            if not line.startswith(cardlog.PREFIX):
                batch.tail.append(line)
            what = batch.reader.feed(line)
            if what == "game":
                events.put(("game", batch, batch.reader.games[-1]))
            elif what == "header":
                events.put(("header", batch, None))
    except (OSError, ValueError):
        pass                # the pipe went away: the process was killed
    finally:
        try:
            batch.proc.wait()
            batch.proc.stdout.close()
        except OSError:
            pass
        events.put(("exit", batch, None))


def _save_failure_log(key, batch):
    """The end of a failed batch's output, in data/forge/logs/ (the newest few are kept)."""
    runtime._failure_log(key, f"seed{batch.spec['seed']}", batch.error, batch.tail)


def _failure_log(key, name, error, tail):
    """Write data/forge/logs/<key's first 12>-<name>.log: error, then tail (Forge's last
    lines); only the newest KEEP_FAILURE_LOGS logs are kept. The warm pool names a failed
    chunk's log g<its first game number>."""
    try:
        folder = common.DATA_DIR / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{key[:12]}-{name}.log"
        path.write_text(f"{error}\n\n" + "".join(tail), encoding="utf-8", newline="\n")
        logs = sorted(folder.glob("*.log"), key=lambda p: p.stat().st_mtime)
        for old in logs[:max(0, len(logs) - runtime.KEEP_FAILURE_LOGS)]:
            old.unlink()
    except OSError:
        pass


def _kill(batch):
    if batch.proc is not None:
        runtime.kill_process(batch.proc)


def _slot(budget, key, unguarded):
    """A slot of the PC's budget for one process about to start (slots.claim, without
    waiting): its Lease, or None when every slot is taken. When the slots can't be used at
    all (their folder can't be written), the log says so once a run (unguarded, a list,
    notes it) and the run goes on without them: an empty Lease."""
    if unguarded:
        return slots.Lease()
    try:
        lease = slots.claim(1, budget, wait=False, what=f"matchup {key[:12]}")
    except OSError as e:
        common._log(f"Forge's slots in {slots.folder()} can't be used ({e}), so this run starts its processes "
                    "without counting other runs'.")
        unguarded.append(True)
        return slots.Lease()
    return lease if lease else None


def _play(setup, fmt, key, sides, specs, procs, progress, names, late=None):
    """Run the batches, at most procs at once, and each only once it has a slot of the
    PC's budget of Forge processes (setup["workers"] slots shared by every run on the PC:
    slots.py): a batch starts when a slot is free and gives it up when its process ends.
    While no process of the run is playing because every slot is another run's, progress
    says so (detail["waiting"] is slots.WAITING), and a stop then stops the wait. Returns
    (the kept batch records, whole and partial, failed [{"n", "seed", "deck1", "error"}],
    the exception that stopped it or None, stats). When something stops it (progress
    raising, Ctrl+C, or an error in the loop), every process is killed and each running
    batch keeps the games it finished, as a partial batch; one that finished none is left
    out, seed and all. A Ctrl+C after the loop is only noted in late (a list), for run()
    to raise once the games are saved. stats: wall_s (from the first process's start),
    startup_s, waited_s (for a slot, before the first process started), most_running
    (the most processes it had at once) and echo (LogReader.engine_by_side() of the first
    kept batch: what its DLENGINE line said of each side; [{}, {}] without one)."""
    late = [] if late is None else late
    events = queue.Queue()
    try:
        env = runtime._prepare_user_dir(setup["user_dir"])
    except OSError as e:
        common._log(f"Forge's user folder couldn't be prepared: {e}")
        raise runtime.ForgeError("Deck Lab can't write Forge's settings in its data folder, "
                         "so the run wasn't started.") from None
    marker = runtime._first_use_marker(setup["user_dir"], setup["version"])
    first_use = not marker.exists()
    waiting = deque(runtime._Batch(spec) for spec in specs)
    running, finished, failed = [], [], []
    total = sum(spec["games"] for spec in specs)
    wins, other, done = [0, 0], 0, 0
    began = t0 = time.monotonic()       # t0: when the first process started (began until then)
    first_start = None
    budget = setup.get("workers") or procs      # the PC's budget of Forge processes
    unguarded = []
    next_try = 0.0                      # when to try for a slot again after none was free
    blocked = False                     # nothing playing: every slot is another run's
    wanting = [None]                    # its slots.Want while a batch waits for a slot (so pools leave
                                        # it the slots they free: slots.py's "Wants")
    most = 0
    last_call = 0.0
    header_seen = False
    stopped = None
    dck = [runtime._dck_name(side) for side in sides]
    card_log = bool((setup.get("card_log") or {}).get("ready"))

    def start(batch):
        """Start batch's process in a free slot; False, starting nothing, when none is."""
        nonlocal next_try, first_start, t0
        spec = batch.spec
        d1, d2 = (dck[0], dck[1]) if spec["deck1"] == 0 else (dck[1], dck[0])
        argv = runtime.build_command(setup, fmt, d1, d2, spec["games"], spec["seed"])
        batch.reader = runtime.LogReader(spec["deck1"], names, card_log=card_log)
        with runtime._interrupts_held():        # a started process is always in running, a slot with its batch
            batch.slot = runtime._slot(budget, key, unguarded)
            if batch.slot is None:
                next_try = time.monotonic() + runtime.SLOT_RETRY_S
                if wanting[0] is None:
                    try:
                        wanting[0] = slots.want(f"matchup {key[:12]}")
                    except OSError:
                        wanting[0] = slots.Want(None, None)     # waits all the same, unseen
                return False
            if wanting[0] is not None:
                wanting[0].release()
                wanting[0] = None
            batch.started = batch.last_game = time.monotonic()
            if first_start is None:
                first_start = t0 = batch.started
            try:
                batch.proc = processes.start_process(argv, cwd=setup["forge_dir"], env=env)
            except OSError as e:
                batch.slot.release()
                common._log(f"A Forge process couldn't be started: {e}")
                batch.error = f"Forge couldn't be started ({runtime._os_reason(e)})"
                batch.ended = time.monotonic()
                failed.append(batch)
                return True
            except BaseException:
                batch.slot.release()
                raise
            running.append(batch)
            batch.thread = threading.Thread(target=runtime._read, args=(batch, events), daemon=True,
                                            name=f"forge-{spec['seed']}")
            batch.thread.start()
        return True

    def counts():
        rate = eta = None
        elapsed = time.monotonic() - t0
        if done and elapsed > 0:
            rate = done / elapsed * 60
            eta = round((total - done) / rate * 60) if rate else None
        return {"wins": list(wins), "other": other, "games_per_min": round(rate, 1) if rate else None,
                "eta_s": eta, "failed_batches": len(failed), "waiting": slots.WAITING if blocked else None}

    def report(final=False):
        nonlocal last_call
        now = time.monotonic()
        if progress is not None and (final or now - last_call >= runtime.PROGRESS_GAP):
            last_call = now
            progress(done, total, counts())

    def end(batch, wait=runtime.KILL_WAIT):
        """A process has ended, or a stop killed it: keep its batch (whole, or partial
        when a stop cut it short), or record why it failed."""
        nonlocal done, other
        if batch.thread is not None:
            batch.thread.join(wait)
        batch.reader.close()
        batch.ended = time.monotonic()
        running.remove(batch)
        runtime._end_process(batch.proc)
        batch.slot.release()
        r = batch.reader
        if batch.killed == runtime.STOP_KILL:
            # Its finished games count, unless Forge didn't know a card or a deck.
            batch.error = r.failure(0, None)
            batch.partial = not batch.error and len(r.games) < batch.spec["games"]
        else:
            batch.error = batch.killed or r.failure(batch.spec["games"], batch.proc.returncode)
        if batch.error:
            # Its games were counted as they came; take them off again.
            for game in r.games:
                done -= 1
                if game["w"] is None:
                    other -= 1
                else:
                    wins[game["w"]] -= 1
            failed.append(batch)
            runtime._save_failure_log(key, batch)
        elif r.games:
            finished.append(batch)
        # else: stopped before its first game ended, so it isn't kept and its seed is free

    try:
        report(final=True)
        while waiting or running:
            # On a new user folder the first process starts alone (until its header line).
            gate = first_use and not header_seen and bool(running)
            while waiting and len(running) < procs and not gate and time.monotonic() >= next_try:
                if not start(waiting[0]):
                    break               # every slot is taken: try again in SLOT_RETRY_S
                waiting.popleft()
                gate = first_use and not header_seen and bool(running)
            most = max(most, len(running))
            if not running and not waiting:
                break
            was_blocked, blocked = blocked, not running
            try:
                what, batch, game = events.get(timeout=runtime.EVENT_POLL_S)
            except queue.Empty:
                what = None
            now = time.monotonic()
            if what == "header":
                batch.header_at = batch.last_game = now
                if not header_seen:
                    header_seen = True
                    if first_use:
                        try:
                            marker.touch()
                        except OSError:
                            pass
            elif what == "game":
                batch.last_game = now
                done += 1
                if game["w"] is None:
                    other += 1
                else:
                    wins[game["w"]] += 1
            elif what == "exit":
                end(batch)
                next_try = 0.0               # its slot is free: the next batch can have it
                if first_use and not header_seen:
                    header_seen = True       # the first process failed: let the rest try
            for batch in running:
                if batch.killed:
                    continue
                if batch.header_at is None and now - batch.started > runtime.HEADER_TIMEOUT:
                    batch.killed = "Forge stopped responding"
                elif batch.header_at is not None and now - batch.last_game > setup["clock_s"] + runtime.GAME_GRACE:
                    batch.killed = "Forge stopped responding"
                if batch.killed:
                    runtime._kill(batch)
            if what in ("game", "exit") or blocked != was_blocked or now - last_call >= runtime.HEARTBEAT:
                report(final=not waiting and not running)
    except BaseException as e:      # progress raised (Stop, the server stopping), Ctrl+C, or a bug
        stopped = e
        hurry = []
        # Nothing interrupts this (a second Ctrl+C only stops the waiting), so it's saved.
        with runtime._interrupts_held(note=lambda: hurry.append(True)):
            for batch in running:
                # One that has already exited ends as it would have (its "exit" may still
                # be queued); the watchdog's keep their reason.
                if not batch.killed and batch.proc.poll() is None:
                    batch.killed = runtime.STOP_KILL
                runtime._kill(batch)
            for batch in list(running):
                end(batch, wait=0 if hurry else runtime.KILL_WAIT)
    with runtime._interrupts_held(note=lambda: late.append(True)):     # and so does run(), to the save
        if wanting[0] is not None:
            wanting[0].release()
        for batch in finished + failed:
            if batch.slot is not None:
                batch.slot.release()        # given up already; this only makes sure
        runtime._tidy_user_dir(setup["user_dir"])
        starts = [b.header_at - b.started for b in finished if b.header_at is not None]
        stats = {"wall_s": round(time.monotonic() - t0, 1),
                 "startup_s": round(max(starts), 1) if starts else None,
                 "waited_s": round((first_start or time.monotonic()) - began, 1), "most_running": most,
                 # What the first kept batch's DLENGINE line said of each side (none for plain Forge).
                 "echo": finished[0].reader.engine_by_side() if finished else [{}, {}]}
        records = []
        for batch in finished:
            r = batch.reader
            record = {
                "n": batch.spec["n"], "seed": batch.spec["seed"], "deck1": batch.spec["deck1"],
                "games": r.games, "casts": r.casts, "lands": r.lands,
                "startup_s": round(batch.header_at - batch.started, 2) if batch.header_at else None,
                "wall_s": round(batch.ended - batch.started, 2),
            }
            if batch.partial:
                record["partial"] = True
            if card_log and r.cards is not None:
                record["cards"] = r.cards       # the per-card tallies of its games (cardlog.py)
                if r.cards["bad"]:
                    runtime._log_card_problems(batch.spec, r)
            records.append(record)
        fails = [{"n": b.spec["n"], "seed": b.spec["seed"], "deck1": b.spec["deck1"], "error": b.error}
                 for b in failed]
    return records, fails, stopped, stats


def _log_card_problems(spec, reader):
    """Log, on one line, how many of a kept batch's games had card logs that failed their
    checks, and the first few reasons (LogReader.card_problems)."""
    bad, shown = reader.cards["bad"], reader.card_problems[:runtime.CARD_PROBLEMS_LOGGED]
    reasons = "; ".join(f"game {n}: {why}" for n, why in shown)
    more = "; ..." if bad > len(shown) else ""
    common._log(f"Batch {spec['n']} (seed {spec['seed']}): the card log of {bad} of its {len(reader.games)} "
                f"games failed its checks ({reasons}{more}).")
