"""The warm-equivalence check (simulation wave 2, the report's R05 risk "the reset list is
incomplete"): a serve worker ("DeckLabSim serve", java/decklab/DeckLabServe.java) must play
every request as a fresh "DeckLabSim sim" process plays the same arguments, after any other
requests. cardlog-check runs it as one of its legs, so the card log (and with it the warm
pool) is used with a Forge version only when it passes; "python -m decklab.lib.forge
serve-check" runs it alone (it notes nothing).

What can't be reset: Forge's Cards and Players hash by identity, so the order of a HashSet of
them depends on the JVM's per-thread hash state, which a warm worker's game threads start
from at other points than a fresh process's. Plain Forge's own Commander games don't repeat
line for line (cli.LINE_FOR_LINE), and a Constructed game could differ the same way, rarely
(e3: 90 of 90 games the same, v-r08: 400 of 400). So the check compares Commander games by
their outcomes and gives a Constructed difference that doesn't come back when the game is
played warm again "unsure", not "failed".

Nor can what Forge itself doesn't repeat: it checks each attacker's attack requirements on a
thread pool of its own (AiAttackController, 2 threads under runner.JVM_FLAGS), so a game's
hidden card ids can come out in another order from one process to the next, fresh or warm.
Measured on 2026-10-03 without Deck Lab's AiAttackController copy (wave 2's R14b, which runs
them as a loop): 2 of WARM_DECKS' 8 games differed between three fresh runs of each (the
same lines up to a card id 2 apart, and from there the combat that card was in), and with
-XX:ActiveProcessorCount=1 (one thread: the checks in order) 31 of 31 games were the same warm
and fresh, with WarmState's reset and also without its Card.cp2card part. Such a difference
may come back when played warm again (a coin flip), so without that copy the check could fail
on these lists for no fault of the worker's: serve-check plays them only when the copy is in
the jar and playing (warm_decks).

How the check plays (warm_leg)
    One worker, started first and alone (a new Forge user folder's first start, as
    runner._play's first batch), in a slot of the PC's budget (slots.py) and pinned to that
    slot's core (cores.pin) as the pool pins its workers, plays every request, in an order of
    its own (_order: the matchups taken in turn, each one's requests last first, then the first
    again). Each different request is also played once by a fresh, unpinned DeckLabSim
    process, FRESH_AT_ONCE at a time, each in a slot. A worker is replaced as the pool replaces
    one: when a request ends with "recycle" (a game hit the clock, an AI evaluation timed out
    or a game crashed: the worker exits), and when a game hit one of Forge's time limits that
    the worker didn't see (Deck Lab's AiController copy doesn't fit): it's killed at once, as a
    stopped thread may play on into the next game. The rest of a v2 request then goes on in a
    new worker, from the next game number, as the pool re-queues it; a v1 request (one seed
    for the batch) can't, so its later games aren't compared.

    Games are compared one by one, the request's DLENGINE line too. Constructed games line for
    line, as cardlog-check compares them (timings, the games' places in their request and
    Java's stack-trace frames masked, attackers in name order), with the card log's DL| lines
    kept and the JVM's WARNING: lines and blank lines left out (a resumed part's first game has
    no blank line before it). Commander games by each game's winner, starter and length.

Raises ForgeError (a plain sentence) when the games can't be played at all: Forge or a worker
won't start, a request's arguments are refused, a process stops responding or dies part way.
This part comes after runner, cores and slots; it reads cli's masks and card-log checks when
it compares (cli imports it)."""
import errno
import inspect
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import cardlog, common, cores, processes, runner, seeds, simjar, slots
from .common import ForgeError, _os_reason
from .lists import entry_from_dck
from .logreader import AI_TIMEOUT, ENGINE_PREFIX, RE_HEADER, SLOW_STOP, LogReader

FRESH_AT_ONCE = 2               # fresh processes playing at once, beside the worker
QUIT_WAIT = 10                  # seconds a worker gets to exit after "quit" before it's killed
TIME_LIMITS = (SLOW_STOP, AI_TIMEOUT)   # Forge's lines saying a game hit one of its time limits
RESULT = "Game Result:"
# The check's requests (check_requests): a matchup's games cut into chunks of these sizes in
# turn, and at the seat-block boundary (seeds.SEAT_BLOCK), so its requests differ in size and
# both deck orders play.
CHUNK_SIZES = (3, 5, 2, 4)
GAMES = 12                      # serve-check's games of cardlog-check's 60-card lists (--games)
COMMANDER_GAMES = 3             # and of its Commander lists (--commander-games)
# Two 60-card lists of double-faced, flip, adventure and clone cards: a game's views of them fill
# Card.cp2card (CardView.getBackup), the cache v-r05 found a warm worker kept and WarmState now
# takes back, which cardlog-check's lists never touch; their many equal creatures and cards cast
# again from exile also test the attack checks' order (the module docstring). Played for half as
# many games (at least 2), and only when Deck Lab's copy of Forge's attack checks plays
# (warm_decks).
WARM_DECKS = {
    "serve-check-transform": ([], ["4 Delver of Secrets", "4 Bonecrusher Giant", "4 Brazen Borrower", "4 Clone",
                                   "4 Akki Lavarunner", "4 Lightning Bolt", "4 Village Messenger", "4 Rimrock Knight",
                                   "4 Fable of the Mirror-Breaker", "12 Island", "12 Mountain"]),
    "serve-check-adventure": ([], ["4 Murderous Rider", "4 Lovestruck Beast", "4 Foulmire Knight",
                                   "4 Kessig Prowler", "4 Duskwatch Recruiter", "4 Llanowar Elves", "4 Murder",
                                   "4 Tangled Florahedron", "4 Mayor of Avabruck", "12 Swamp", "12 Forest"]),
}
# The id of Deck Lab's change to Forge's AiAttackController (wave 2's R14b: the attack checks as
# a loop, in attacker order), as Forge's jar lists it (simjar.FORGE_PATCH_LIST).
ATTACK_ORDER = "attack-requirements-in-order-1"


def _cli():
    """cli.py, for the masks and card-log checks cardlog-check compares with (imported when
    used: cli imports this module)."""
    from . import cli
    return cli


# ============================================================ the check's requests

def warm_decks(setup, card_log):
    """WARM_DECKS when their games repeat, else {}: they need Deck Lab's change to Forge's
    AiAttackController (ATTACK_ORDER) in Forge's jar (its id in card_log["game_patches"]) and
    playing (setup's "game_patches" not False). Without it Forge checks attack requirements
    on two threads, and some of these lists' games differ even between two fresh processes
    (the module docstring), which the check can't tell from the worker's fault."""
    if ATTACK_ORDER in card_log.get("game_patches", ()) and setup.get("game_patches") is not False:
        return WARM_DECKS
    return {}


def write_decks(folder, decks):
    """Write {name: ([Commander lines], [Main lines])} as folder/<name>.dck, as cardlog-check
    writes its lists."""
    for name, (commander, cards) in decks.items():
        sections = ([("Commander", commander)] if commander else []) + [("Main", cards)]
        text = f"[metadata]\nName={name}\n" + "".join(f"[{section}]\n" + "\n".join(lines) + "\n"
                                                     for section, lines in sections)
        (Path(folder) / f"{name}.dck").write_text(text, encoding="utf-8", newline="\n")


def _cuts(first, games):
    """[(first game, games)]: games numbered from first, cut into chunks of CHUNK_SIZES in
    turn and at every seat-block boundary (a chunk never spans two, as the pool's don't)."""
    out, g, k = [], first, 0
    while g < first + games:
        n = min(CHUNK_SIZES[k % len(CHUNK_SIZES)], first + games - g, seeds.block_end(g) - g)
        out.append((g, n))
        g, k = g + n, k + 1
    return out


def check_requests(folder, legs, base, v1=False):
    """The check's requests for legs [(Forge's format, {name: ([Commander lines], [Main lines])}
    of two lists, games)], the .dck files written to folder: each matchup's games cut into
    chunks (_cuts) numbered so they straddle the seat-block boundary, half before it and half
    after, so both deck orders play: [(fmt, deck1, deck2, games, seed, v2)], runner.request_args'
    arguments. v2 requests are the result's games of base and the pair's stream
    (seeds.stream_of their card_shas), deck 1 the first list in even blocks; with v1, each chunk
    is a v1 batch of its own seed (base, base + 1, ...) with the same decks and size."""
    requests = []
    for fmt, decks, games in legs:
        write_decks(folder, decks)
        names = [f"{name}.dck" for name in decks]
        stream = seeds.stream_hex(seeds.stream_of(*(entry_from_dck(Path(folder) / name)["card_sha"]
                                                    for name in names)))
        for k, (first, n) in enumerate(_cuts(max(0, seeds.SEAT_BLOCK - games // 2), games)):
            d1, d2 = names if seeds.deck1_side(first) == 0 else names[::-1]
            if v1:
                requests.append((fmt, d1, d2, n, base + k, None))
            else:
                requests.append((fmt, d1, d2, n, base, {"stream": stream, "first": first}))
    return requests


def _order(requests):
    """The order the worker plays requests in (indexes): the matchups (format and lists) in
    turn, each one's requests last first, so another matchup's request comes between two of
    the same one wherever there's another to put there; then the first played again."""
    groups = {}
    for i, (fmt, d1, d2, *_) in enumerate(requests):
        groups.setdefault((fmt, *sorted((d1, d2))), []).append(i)
    turns = [list(reversed(group)) for group in groups.values()]
    order = []
    while any(turns):
        order += [turn.pop(0) for turn in turns if turn]
    return order + order[:1]


def _label(request):
    """A request in words: "a v b, Constructed games 19-21" (v2) or "..., seed 3 (4 games)"."""
    fmt, d1, d2, games, seed, v2 = request
    decks = f"{Path(d1).stem} v {Path(d2).stem}, {fmt}"
    if v2:
        first = int(v2["first"])
        return f"{decks} game {first}" if games == 1 else f"{decks} games {first}-{first + games - 1}"
    return f"{decks} seed {seed} ({games} game{'' if games == 1 else 's'})"


def _game_name(request, i):
    """Game i of a request in words: the result's game number (v2), or its place in the batch."""
    v2 = request[5]
    return f"game {int(v2['first']) + i}" if v2 else f"game {i + 1}"


# ============================================================ processes

def _start(argv, cwd, env):
    """processes.start_process with a pipe for stdin, which a serve worker reads its requests
    from. start_process has a stdin option (wave 2's warm pool added it), so that's what
    runs; the copy below is the same start for a start_process without one (the process in
    Deck Lab's job, so it can't outlive it, and a job of its own, below normal priority, no
    window, and a job problem logged once). It no longer runs, and can go, with _warn_job
    and the test of it in test_forge_servecheck."""
    if "stdin" in inspect.signature(processes.start_process).parameters:
        # subprocess.PIPE whether the option is Popen's value or a bool (PIPE is -1: true)
        return processes.start_process(argv, cwd=cwd, env=env, stdin=subprocess.PIPE)
    kwargs = dict(cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                  text=True, encoding="utf-8", errors="replace", bufsize=1)
    if sys.platform != "win32":
        return subprocess.Popen(argv, start_new_session=True, **kwargs)
    import ctypes
    p = processes
    try:
        job = p._job_handle()
    except OSError as e:
        job = None
        _warn_job(f"Forge's processes can't be tied to Deck Lab's ({e}); a hard kill may leave some running.")
    proc = subprocess.Popen(argv, creationflags=p._SPAWN_FLAGS | (p._SUSPENDED if job else 0), **kwargs)
    if not job:
        return proc
    handle = p._k32.OpenProcess(p.PROCESS_SET_QUOTA | p.PROCESS_TERMINATE | p.PROCESS_SUSPEND_RESUME, False, proc.pid)
    try:
        if not handle or not p._k32.AssignProcessToJobObject(job, handle):
            _warn_job(f"A Forge process couldn't join Deck Lab's job (error {ctypes.get_last_error()}); "
                      "a hard kill may leave it running.")
        if handle:
            p._own_job(proc, handle)
        if not handle or p._ntdll.NtResumeProcess(handle) != 0:
            p.kill_process(proc)
            proc.wait()
            for pipe in (proc.stdin, proc.stdout):
                pipe.close()
            p._end_process(proc)
            raise OSError(errno.EPERM, "Windows wouldn't let it run")
    finally:
        if handle:
            p._k32.CloseHandle(handle)
    return proc


def _warn_job(text):
    """Log a job problem of _start's once per process: start_process's own warning, under its
    flag, so the two starts say it once between them."""
    if not getattr(processes, "_job_warned", False):
        processes._job_warned = True
        common._log(text)


class _Output:
    """A process's output lines, read on a thread of their own, so waiting for one can time out."""

    def __init__(self, proc):
        self.proc = proc
        self.lines = queue.Queue()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            for line in self.proc.stdout:
                self.lines.put(line.rstrip("\r\n"))
        except (OSError, ValueError):
            pass                # the pipe went away: the process was killed
        self.lines.put(None)

    def get(self, deadline):
        """The next line, None at the end of the output, or TimeoutError at deadline (monotonic)."""
        while True:
            try:
                return self.lines.get(timeout=max(0.0, min(0.5, deadline - time.monotonic())))
            except queue.Empty:
                if time.monotonic() >= deadline:
                    raise TimeoutError from None

    def end(self, wait=None):
        """Kill the process (unless it has ended, or does within wait seconds) and close its pipes."""
        if wait:
            try:
                self.proc.wait(wait)
            except subprocess.TimeoutExpired:
                pass
        processes.kill_process(self.proc)
        try:
            self.proc.wait(runner.KILL_WAIT)
        except subprocess.TimeoutExpired:
            pass
        self.thread.join(runner.KILL_WAIT)
        for pipe in (self.proc.stdin, self.proc.stdout):
            try:
                if pipe is not None:
                    pipe.close()
            except OSError:
                pass
        processes._end_process(self.proc)


class _Part:
    """One process's or request's lines and how its games went."""

    def __init__(self):
        self.lines = []             # its output (a request's: without DLSERVE| lines)
        self.limits = []            # per game: did it hit one of Forge's time limits?
        self.status = None          # a request's end status
        self._header = self._hit = False

    def add(self, line):
        """Keep a line; True when it ends a game (its "Game Result" line)."""
        self.lines.append(line)
        if not self._header:
            self._header = bool(RE_HEADER.match(line))
            return False
        if line.startswith(TIME_LIMITS):
            self._hit = True
        if line.startswith(RESULT):
            self.limits.append(self._hit)
            self._hit = False
            return True
        return False


class _Copy:
    """One copy of a request's games, fresh or warm (several parts when a worker had to be
    replaced part way): each game's lines, whether it hit a time limit, the first part's
    DLENGINE line, and cut (a v1 request whose later games weren't played)."""

    def __init__(self, fmt):
        self.fmt = fmt
        self.games, self.limits, self.engine, self.header, self.cut = [], [], None, None, False

    def add(self, part):
        games, cur, header = [], [], None
        for line in part.lines:
            if header is None:
                if line.startswith(ENGINE_PREFIX) and self.engine is None and not self.games:
                    self.engine = line
                if RE_HEADER.match(line):
                    header = line
                continue
            cur.append(line)
            if line.startswith(RESULT):
                games.append(cur)
                cur = []
        self.header = self.header or header
        self.games += games
        self.limits += part.limits[:len(games)]

    def masked(self, i):
        """Game i as it's compared: cardlog-check's masks, DL| lines kept, WARNING: and blank
        lines (and any DLSERVE| line) left out."""
        cli = _cli()
        return [cli.RE_ORDINAL.sub(r"\g<1>?", cli.RE_TIMING.sub("?", cli._attackers_in_order(line)))
                for line in self.games[i]
                if line.strip() and not line.startswith(("WARNING:", runner.SERVE_PREFIX))
                and not cli.RE_FRAME.match(line)]

    def read(self):
        """(a LogReader that read every game, the games' text from the header on)."""
        reader = LogReader(0, None, card_log=True)
        lines = [self.header or ""] + [line for game in self.games for line in game]
        for line in lines:
            reader.feed(line)
        reader.close()
        return reader, "\n".join(lines) + "\n"


# ============================================================ the warm worker

class _Worker:
    """One serve worker, ready to play (it raises ForgeError when it can't start)."""

    def __init__(self, check):
        self.check = check
        try:
            proc = _start(runner.serve_command(check.launch), check.launch["forge_dir"], check.env)
        except OSError as e:
            raise ForgeError(f"A warm worker couldn't be started ({_os_reason(e)}).") from None
        self.out = _Output(proc)
        self.alive = True
        check.pin(proc.pid)
        deadline = time.monotonic() + runner.HEADER_TIMEOUT
        try:
            while True:
                line = self.out.get(deadline)
                event = self._event(line)
                if line is None:
                    raise ForgeError(f"A warm worker stopped before it was ready (exit code {proc.wait()}).")
                if event and event["what"] == "fail":
                    raise ForgeError(f"A warm worker couldn't start: {event['why']}.")
                if event and event["what"] == "ready":
                    if event["protocol"] != runner.SERVE_PROTOCOL:
                        raise ForgeError(f"The warm worker speaks protocol {event['protocol']}, not "
                                         f"{runner.SERVE_PROTOCOL}.")
                    break
        except TimeoutError:
            self.end()
            raise ForgeError(f"A warm worker wasn't ready in {runner.HEADER_TIMEOUT} s.") from None
        except BaseException:
            self.end()
            raise

    @staticmethod
    def _event(line):
        try:
            return None if line is None else runner.serve_event(line)
        except ValueError:
            return None

    def play(self, request_id, args, games):
        """Play one request (runner.request_args' args, games of them): its _Part. When a game
        that hit one of Forge's time limits ends with games still to come, the worker is killed
        at once, as the pool kills one, and the part ends there (status None)."""
        self.check.pin(self.out.proc.pid)
        part = _Part()
        try:
            self.out.proc.stdin.write(runner.request_line(request_id, args))
            self.out.proc.stdin.flush()
        except OSError:
            pass                # it has died: its output says so
        grace = self.check.launch["clock_s"] + runner.GAME_GRACE
        deadline = time.monotonic() + grace
        while True:
            try:
                line = self.out.get(deadline)
            except TimeoutError:
                self.end()
                raise ForgeError(f"A warm worker stopped responding (no game finished in {grace} s).") from None
            if line is None:
                self.end()
                raise ForgeError(f"A warm worker stopped part way through a request (exit code "
                                 f"{self.out.proc.returncode}).")
            event = self._event(line)
            if event and event["what"] == "end" and event["id"] == request_id:
                part.status = event["status"]
                break
            if line.startswith(runner.SERVE_PREFIX):
                continue
            if part.add(line):
                deadline = time.monotonic() + grace
                if part.limits[-1] and len(part.limits) < games:
                    self.end()
                    return part
        if part.status == "error":
            raise ForgeError(f"A warm worker couldn't play the check's request: {event['detail']}.")
        if part.status == "cancelled":
            raise ForgeError("A warm worker stopped a request it wasn't asked to stop.")
        if part.status == "recycle":
            self.end(wait=QUIT_WAIT)         # it exits by itself ("bye|recycle")
        elif any(part.limits):
            self.end()                       # a stopped thread may still be running: as the pool does
        return part

    def quit(self):
        if not self.alive:
            return
        try:
            self.out.proc.stdin.write("quit\n")
            self.out.proc.stdin.flush()
        except OSError:
            pass
        self.end(wait=QUIT_WAIT)

    def end(self, wait=None):
        if self.alive:
            self.alive = False
            self.out.end(wait)


# ============================================================ the check

class _Check:
    """One run of the check: the worker, the fresh processes, their slots."""

    def __init__(self, setup, folder, env, card_log):
        self.launch = dict(setup, decks_dir=Path(folder), card_log=card_log)
        self.env = env
        self.worker = None
        self.slot = None            # the worker's slot (a slots.Lease), held until close()
        self.pinned = None          # was the worker pinned to its slot's core?
        self.ids = 0
        self.stopping = threading.Event()
        self.fresh = {}             # request index -> its fresh _Copy
        self.errors = []
        self.procs = set()          # fresh processes playing (_Output)
        self.lock = threading.Lock()
        self.threads = []
        self.said = set()           # what say_once() has said

    def _claim(self):
        """A slot of the PC's budget for one process, waiting for one (an empty Lease when
        the slots can't be used)."""
        try:
            return slots.claim(1, self.launch.get("workers"), cancel=self.stopping, what="serve-check",
                               waiting=lambda: self.say_once("waiting", f"  {slots.WAITING}"))
        except OSError as e:
            self.say_once("unusable", f"  Forge's slots in {slots.folder()} can't be used ({_os_reason(e)}), so "
                                      "the check doesn't wait for other Forge runs.")
            return slots.Lease()

    def say_once(self, what, text):
        with self.lock:
            if what in self.said:
                return
            self.said.add(what)
        print(text, file=sys.stderr)

    def pin(self, pid):
        """Pin the worker to its slot's core, as the pool pins a computing worker."""
        ids = self.slot.ids if self.slot else []
        pinned = bool(ids) and cores.pin(pid, ids[0])
        if self.pinned is None:
            self.pinned = pinned
            print(f"  The warm worker plays {'pinned to core ' + str(ids[0]) if pinned else 'unpinned'}; "
                  "fresh processes play unpinned.", file=sys.stderr)
        return pinned

    def current(self):
        """The worker, a new one when there's none (or it exited)."""
        if self.worker is None or not self.worker.alive:
            if self.slot is None:
                self.slot = self._claim()
            self.worker = _Worker(self)
        return self.worker

    def first_start(self):
        """The first worker, alone (Forge's user folder's first start, as runner._play)."""
        self.current()
        user_dir, version = self.launch.get("user_dir"), self.launch.get("version")
        if user_dir and version:
            try:
                runner._first_use_marker(Path(user_dir), version).touch()
            except OSError:
                pass

    def play_warm(self, request):
        """A request played by the worker: its _Copy. A worker that recycles or is killed
        part way is replaced, and the rest of a v2 request goes on in the new one."""
        fmt, d1, d2, games, seed, v2 = request
        copy, left, first = _Copy(fmt), games, (int(v2["first"]) if v2 else None)
        self.ids += 1
        n = 0
        while left:
            args = runner.request_args(self.launch, fmt, d1, d2, left, seed, v2 and dict(v2, first=first))
            part = self.current().play(f"w{self.ids}" + (f".{n}" if n else ""), args, left)
            played = len(part.limits)
            if not played:
                raise ForgeError(f"A warm worker played none of the check's request ({_label(request)}).")
            copy.add(part)
            left -= played
            if left and not v2:
                copy.cut = True         # a v1 batch can't go on from the middle
                break
            first, n = (first + played if v2 else None), n + 1
        return copy

    def replay(self, request, i):
        """Game i of request played warm again (v2: alone, a one-game request; v1: its batch up
        to it): its masked lines, or None when that copy hit a time limit or wasn't played."""
        fmt, d1, d2, games, seed, v2 = request
        if v2:
            copy, at = self.play_warm((fmt, d1, d2, 1, seed, dict(v2, first=int(v2["first"]) + i))), 0
        else:
            copy, at = self.play_warm((fmt, d1, d2, i + 1, seed, None)), i
        if len(copy.games) <= at or any(copy.limits[:at + 1]):
            return None
        return copy.masked(at)

    def play_fresh(self, index, request):
        """A request played by a fresh DeckLabSim process, in a slot: its _Copy in self.fresh."""
        fmt, d1, d2, games, seed, v2 = request
        argv = runner.build_command(self.launch, fmt, d1, d2, games, seed, v2)
        lease = self._claim()
        try:
            try:
                proc = processes.start_process(argv, cwd=self.launch["forge_dir"], env=self.env)
            except OSError as e:
                raise ForgeError(f"Forge couldn't be started ({_os_reason(e)}).") from None
            out = _Output(proc)
            with self.lock:
                self.procs.add(out)
            if self.stopping.is_set():          # close() came while it started
                processes.kill_process(proc)
            part, reader = _Part(), LogReader(0, None, card_log=True)
            grace = self.launch["clock_s"] + runner.GAME_GRACE
            deadline = time.monotonic() + runner.HEADER_TIMEOUT
            try:
                while True:
                    line = out.get(deadline)
                    if line is None:
                        break
                    reader.feed(line)
                    if part.add(line) or RE_HEADER.match(line):
                        deadline = time.monotonic() + grace
            except TimeoutError:
                raise ForgeError(f"A fresh Forge process stopped responding ({_label(request)}).") from None
            finally:
                out.end()
                with self.lock:
                    self.procs.discard(out)
        finally:
            lease.release()
        problem = reader.failure(games, proc.returncode)
        if problem:
            raise ForgeError(f"The check's games ({_label(request)}) couldn't be played by a fresh process. {problem}.")
        copy = _Copy(fmt)
        copy.add(part)
        self.fresh[index] = copy

    def start_fresh(self, requests):
        """Play each request once in a fresh process, FRESH_AT_ONCE at a time, on threads."""
        todo = queue.Queue()
        for index in range(len(requests)):
            todo.put(index)

        def run():
            while not self.stopping.is_set():
                try:
                    index = todo.get_nowait()
                except queue.Empty:
                    return
                try:
                    self.play_fresh(index, requests[index])
                except slots.Cancelled:
                    return
                except BaseException as e:      # raised again in the main thread
                    self.errors.append(e)
                    return

        self.threads = [threading.Thread(target=run, daemon=True) for _ in range(min(FRESH_AT_ONCE, len(requests)))]
        for thread in self.threads:
            thread.start()

    def wait_fresh(self):
        for thread in self.threads:
            while thread.is_alive():
                thread.join(0.2)        # short waits, so Ctrl+C is noticed
        self.raise_errors()

    def raise_errors(self):
        if self.errors:
            raise self.errors[0]

    def close(self):
        self.stopping.set()
        if self.worker is not None:
            self.worker.quit()
        with self.lock:
            playing = list(self.procs)
        for out in playing:
            processes.kill_process(out.proc)
        for thread in self.threads:
            thread.join(runner.KILL_WAIT)
        if self.slot is not None:
            self.slot.release()


def warm_leg(setup, folder, env, card_log, requests):
    """Play requests [(fmt, deck1, deck2, games, seed, v2)] (runner.request_args' arguments;
    the .dck files in folder) on one serve worker, in an order of its own and with another
    request between two of the same matchup, and each as a fresh DeckLabSim process, and
    compare them game by game (the module docstring says how). The worker is pinned the way
    the pool pins one (cores.pin, to the core of the slot it holds, when config.json's
    forge_pin is on); the fresh processes aren't, so the check also shows that pinning
    changes no game. setup is install._setup() (its "game_patches" False plays every process
    with simjar.GAME_PATCHES_OFF) with card_log (simjar.card_log()), env the environment
    runner._prepare_user_dir() gives.

    Constructed games are compared line for line, as cardlog-check compares them
    (cli._games_text's masks: timings, the games' places in their request and Java's
    stack-trace frames masked, attackers in name order) with the WARNING: lines dropped and
    the card log's DL| lines kept; Commander games by each game's winner, starter and length.
    A Constructed game whose lines differ is played warm once more, alone, on the same worker
    (Check.replay): when that copy is the fresh one's, the difference didn't come back
    (identity-hash order, the module docstring) and the game is unsure; when it differs
    again, it failed.

    Returns None when every game is the same, else (kind, [lines to print]):
      "failed"   a Constructed difference that came back, a Constructed game whose winner,
                 starter or length differs, DL| lines that differ while Forge's lines are the
                 same, a DLENGINE line that differs, or a card log that fails its checks
                 (cli._card_log_problems), in either copy
      "unsure"   nothing failed, and a difference was in or after a game that hit one of
                 Forge's time limits in the same process (either copy: a stopped game's thread
                 or a timed-out AI evaluation can play on into the next game), a Commander
                 outcome, a Constructed difference that didn't come back, or a v1 request's
                 games the worker didn't play (it was replaced part way)
    Raises ForgeError when the games can't be played (the module docstring)."""
    if not requests:
        return None
    requests = [(fmt, d1, d2, int(games), seed, dict(v2) if v2 else None)
                for fmt, d1, d2, games, seed, v2 in requests]
    check = _Check(setup, folder, env, card_log)
    findings = []
    try:
        check.first_start()
        check.start_fresh(requests)
        order = _order(requests)
        warm = []
        for index in order:
            check.raise_errors()
            warm.append((index, check.play_warm(requests[index])))
        check.wait_fresh()
        seen = set()
        for n, (index, copy) in enumerate(warm, 1):
            fresh = check.fresh[index]
            if index not in seen:
                seen.add(index)
                findings += _card_log_findings(requests[index], fresh, "fresh")
            findings += _card_log_findings(requests[index], copy, "warm")
            findings += _compare(requests[index], fresh, copy, n, len(warm),
                                 lambda i, request=requests[index]: check.replay(request, i))
    finally:
        check.close()
    return _verdict(findings, setup.get("version"))


# ============================================================ comparing

def _card_log_findings(request, copy, which):
    """A copy's card-log problems (cli._card_log_problems: a game without its DL|log line, a
    Commander game without both commanders, card data that fails its checks), as findings."""
    reader, text = copy.read()
    lines = _cli()._card_log_problems(request[0], len(copy.games), text, reader)
    return [("failed", f"{_label(request)}, played {which}: {line}") for line in lines]


_LIMIT_WORDS = ("it or a game before it in the same process hit one of Forge's time limits (\"Stopping slow "
                "match as draw\" or \"AI eval thread at timeout\"), which a busy computer can cause in one copy "
                "of a game and not the other, and a stopped game's thread can play on into the next game")


def _first_difference(fresh, warm):
    """Where two masked games first differ, in words."""
    for k, (a, b) in enumerate(zip(fresh, warm), 1):
        if a != b:
            return f"line {k} is {a!r} fresh and {b!r} warm"
    return f"the fresh copy has {len(fresh)} lines and the warm one {len(warm)}"


def _outcomes(copy):
    """Each game's (result, winner's seat - 1, starter's seat - 1, turns), read game by game (so
    a game whose lines can't be read is None, and the rest stay in place)."""
    found = []
    for game in copy.games:
        reader = LogReader(0)
        for line in [copy.header or ""] + game:
            reader.feed(line)
        g = reader.games[-1] if reader.games else None
        found.append(g and (g["r"], g["w"], g["first"], g["turns"]))
    return found


def _outcome(found):
    """A game's outcome (_outcomes) in words, as cardlog-check says it."""
    return "a game whose result can't be read" if found is None else _cli()._outcome(found)


def _compare(request, fresh, warm, n, of, replay):
    """Findings [(kind, line)] for one request played warm (the n-th of the worker's of
    requests) against its fresh copy. replay(i) plays game i warm again (Check.replay)."""
    cli = _cli()
    fmt = request[0]
    label = _label(request)
    where = f"{label} (the worker's request {n} of {of})"
    found = []
    if fresh.engine != warm.engine:
        found.append(("failed", f"{where}: the DLENGINE line is {fresh.engine!r} fresh and {warm.engine!r} warm."))
    by_line = fmt in cli.LINE_FOR_LINE
    outcome_f, outcome_w = _outcomes(fresh), _outcomes(warm)
    for i in range(min(len(fresh.games), len(warm.games))):
        a, b = fresh.masked(i), warm.masked(i)
        if a == b:
            continue
        name = f"{where}, {_game_name(request, i)}"
        limit = any(fresh.limits[:i + 1]) or warm.limits[i]
        same_outcome = outcome_f[i] == outcome_w[i]
        if not by_line:
            if not same_outcome:
                why = (_LIMIT_WORDS if limit else
                       f"plain Forge itself doesn't play a {fmt} game the same way every time")
                found.append(("unsure", f"{name} was {_outcome(outcome_f[i])} fresh and "
                                        f"{_outcome(outcome_w[i])} warm; {why}."))
            continue
        diff = _first_difference(a, b)
        if limit:
            found.append(("unsure", f"{name}: {diff}; {_LIMIT_WORDS}."))
        elif not same_outcome:
            found.append(("failed", f"{name} was {_outcome(outcome_f[i])} fresh and "
                                    f"{_outcome(outcome_w[i])} warm ({diff})."))
        elif [x for x in a if not x.startswith(cardlog.PREFIX)] == [x for x in b if not x.startswith(cardlog.PREFIX)]:
            found.append(("failed", f"{name}: only the card log's lines differ: {diff}."))
        else:
            again = replay(i)
            if again is None:
                found.append(("unsure", f"{name}: {diff}; played warm again, it hit one of Forge's time limits, "
                                        "so the check can't tell whether the difference comes back."))
            elif again == a:
                found.append(("unsure", f"{name}: {diff}; played warm again, it was the fresh game, so the "
                                        "difference didn't come back (Forge doesn't always repeat a game: the "
                                        "order of its sets of cards, which a warm worker can't put back, or its "
                                        "attack checks on two threads, can change one)."))
            else:
                found.append(("failed", f"{name}: {diff}; played warm again, it differed again "
                                        f"({_first_difference(a, again)})."))
    if warm.cut and len(warm.games) < len(fresh.games):
        found.append(("unsure", f"{where}: the worker was replaced after {len(warm.games)} of its "
                                f"{len(fresh.games)} games (one hit one of Forge's time limits or crashed), "
                                "and a v1 batch can't go on from the middle, so its later games weren't compared."))
    elif len(warm.games) != len(fresh.games):
        found.append(("failed", f"{where}: the worker played {len(warm.games)} games, the fresh process "
                                f"{len(fresh.games)}."))
    return found


def _verdict(findings, version):
    """warm_leg's answer from its findings."""
    if not findings:
        return None
    kind = "failed" if any(k == "failed" for k, _ in findings) else "unsure"
    head = ("A warm worker didn't play the same games as fresh processes"
            + (f" with Forge {version}" if version else "") + ":")
    lines = [head] + [f"  {line}" for _, line in findings]
    if kind == "unsure":
        lines.append("So the check can't tell whether a warm worker plays the same games as a fresh process. "
                     "Run it again" + (" when the computer is less busy." if any(
                         "time limit" in line for _, line in findings) else "."))
    return kind, lines
