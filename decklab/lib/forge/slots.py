"""The PC's budget of Forge processes: config.json's forge_workers slots, shared by every
Deck Lab checkout and worktree on the PC (the server and every command line), so runs
going at once never have more Forge processes between them than that. (Nothing limited
them before: three 1,600-game runs from the command line started 48 processes, and 32
at once played 17 % fewer games a minute than 16.) Each Forge process holds one slot
while it runs.

Slots
    A slot is an OS lock: an exclusive lock on one byte of its own file, slot-<id>.lock,
    in folder(): %LOCALAPPDATA%\\DeckLab\\forge-slots, outside every checkout, so they all
    share it (the environment variable DECKLAB_FORGE_SLOTS names another folder; the
    tests point it at one of their own). Windows lets go of the lock when the process
    holding it ends, however it ends (Ctrl+C, taskkill /F, a crash), so a slot is never
    left taken; the files stay, and nothing deletes them. The ids go from 0 to the budget
    less 1, lowest first, and no two processes on the PC hold the same id at once, so a
    worker can be pinned to a core by its slot's id. A claimer looks only at the ids
    below its own budget: a checkout whose config.json says 8 uses slots 0-7.
    The holder writes who it is at the start of the file ({"id", "pid", "what", "since",
    "checkout"}, JSON), which status() reads; the locked byte is far past it (LOCK_AT),
    because on Windows another process can't read a locked byte.

What it gives (runner._play, the warm pool (pool.py) and cli's cardlog-check use it)
    lease = claim(n, budget=None, wait=True, cancel=None, waiting=None, what=None, prefer=None)
        Claims up to n free slots, lowest ids first (prefer, an id, first when it's free and
        below the budget: a warm worker takes back the slot, and so the core, it had), and
        returns a Lease holding them.
        When none is free: with wait=False, an empty Lease at once; with wait=True, it
        tries again every POLL_S seconds until one is, calling waiting() (no arguments)
        each time before it waits (whatever waiting() raises ends the wait and goes on
        up), and raising Cancelled once cancel (a threading.Event) is set. budget None
        is config.json's forge_workers; what says what the slots are for, in a few words
        (status() shows it). OSError when the folder can't be made, or not one slot file
        can be opened. While it waits it holds a want (below), so a pool that frees a
        slot leaves it for this claim.
    lease.ids               the ids held, lowest first (a new list each time)
    len(lease), bool(lease) how many are held, and whether any
    lease.release(slot_id)  gives up one (an id of lease.ids; any other does nothing)
    lease.release()         gives up all of them (again: nothing)
    with claim(...) as lease:   gives them all up when the block ends, however it ends
    Lease()                 an empty lease, which holds nothing
    status(budget=None)     {"folder", "budget", "limit", "slots": [{"id", "held", "pid", "what",
                            "since", "checkout"}]}: every id below the budget, and any
                            higher one held now (another checkout's bigger budget)
    limit()                 the PC's worker limit (below), or None
    set_limit(n)            sets it (n: 1 or more), or clears it (None)
    A Lease that's dropped without release() gives its slots up when it's garbage
    collected, and one held until the process ends goes with the process. claim()'s
    poll (seconds) replaces POLL_S for one call.
    The warm pool (pool.py) has each worker claim one slot, without waiting, before it
    starts its process and before each chunk of games it plays (preferring the id it had
    last), pins it to the core of that slot's id (cores.py), and gives the slot up when the
    chunk ends: an idle warm worker holds none.

The worker limit
    An admin can lower how many slots are used at once while the PC is busy (Deck Lab's
    footer, PUT /api/simulations): limit.json in folder(), {"workers": n}, so it holds for
    every checkout and the command line too. claim() uses only the ids below the smaller of
    its budget and the limit, and looks again each time it tries, so a waiting claim and the
    warm pool's next chunk follow a change at once; a process already holding a higher slot
    keeps it until its chunk or batch ends. Fewer workers rather than a CPU cap: each game
    still plays at full speed, so Forge's per-game clock (forge_clock_s) means the same.

Wants: who waits for a slot
    A pool frees a worker's slot at each chunk's end and would take it back at once for
    the worker's next chunk, long before a claim polling every POLL_S looked again: so
    while a pool had games queued, nothing else on the PC (a command line run, a
    cardlog-check, another checkout's server) got a slot. So whoever waits for a slot
    says so with a want, a file want-<pid>-<n>.lock in folder() locked as a slot's is
    (so it's gone with its process however that ends), and a pool that frees a slot while
    someone else wants one leaves it free for a moment (pool.HANDOFF_S) for them to take.
    want = want(what=None)  says this process waits for a slot, until want.release() (or
                            the process ends); OSError when its file can't be made
    waiting(exclude=None)   how many wants there are now, leaving out exclude (a Want, or
                            None); the files of wants whose process has ended are deleted
    claim(..., wait=True) holds one while it waits; runner._play and the pool hold one
    while they have a process or chunk ready to start and no slot for it.

Who holds slots
    runner._play takes one slot, without waiting, for each batch's process as it starts,
    and gives it up when the process ends; a run asking for k processes so starts as
    many as it gets slots for (at least 1: when none is free it waits for one, and
    progress says so: WAITING), and starts its other batches as slots come free, its own
    or other runs'. cli's cardlog-check takes one for each of its processes, waiting for
    it. The practice-hand simulation (lib/goldfish/) takes none and never waits for a
    Forge run, as practice hands are answered while someone waits on the page. Priority
    sorts the two out instead: Forge's processes run below normal priority
    (processes.start_process) and goldfish's at normal, so when they want the same cores
    Windows runs goldfish's threads first. (Java's compiler and garbage-collector threads
    run at its highest thread priority, which below normal comes to the same as a normal
    thread, so in a Forge process's first seconds they share the cores evenly.) A practice
    run lasts a second or two plus starting its workers, and a Forge process takes 10-26 s
    just to start, so holding Forge processes back while practice workers are up would
    cost the Forge run more than it gave practice.
"""
import itertools
import json
import os
import sys
import threading
import time
import weakref
from pathlib import Path

from decklab.lib import config

from . import common

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

ENV = "DECKLAB_FORGE_SLOTS"     # names another folder for the slots (the tests' own)
POLL_S = 0.5                    # how often a waiting claim() tries again
LOCK_AT = 1 << 20               # the byte locked: far past the holder's note, which status() reads
NOTE_MAX = 4096                 # the most of a holder's note status() reads
WANT_GLOB = "want-*.lock"        # wants' files (a want: someone waits for a slot)
LIMIT_FILE = "limit.json"       # the worker limit (the module docstring's "The worker limit")

# What progress says (detail["waiting"]) while a run has nothing playing because every
# slot is another run's.
WAITING = "Waiting for other Forge runs on this PC to finish."


class Cancelled(Exception):
    """claim()'s cancel was set while it waited for a slot."""


def folder():
    """The slots' folder: DECKLAB_FORGE_SLOTS when it's set, else DeckLab\\forge-slots in
    %LOCALAPPDATA% (elsewhere ~/.local/share). Looked up on every call."""
    named = os.environ.get(ENV)
    if named:
        return Path(named)
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "DeckLab" / "forge-slots"


def _budget(budget):
    """budget as a whole number of 1 or more; None: config.json's forge_workers."""
    if budget is None:
        try:
            budget = common._settings()["forge_workers"]
        except (KeyError, OSError, ValueError):
            budget = config.DEFAULTS["forge_workers"]
    budget = int(budget)
    if budget < 1:
        raise ValueError(f"the budget must be a whole number of 1 or more, not {budget!r}")
    return budget


def limit():
    """The PC's worker limit (1 or more), or None when there's none (or limit.json can't be
    read: a broken file limits nothing)."""
    try:
        value = json.loads((folder() / LIMIT_FILE).read_text(encoding="utf-8")).get("workers")
    except (OSError, ValueError, AttributeError):
        return None
    return value if type(value) is int and value >= 1 else None


def set_limit(n):
    """Set the worker limit to n (a whole number of 1 or more), or clear it (None). Written
    atomically: a temp file in the folder, then os.replace. OSError when it can't be written."""
    path = folder() / LIMIT_FILE
    if n is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    if type(n) is not int or n < 1:
        raise ValueError(f"the limit must be a whole number of 1 or more, not {n!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{LIMIT_FILE}.{os.getpid()}.tmp")
    temp.write_text(json.dumps({"workers": n}), encoding="utf-8")
    os.replace(temp, path)


def _limited(budget):
    """budget, or the worker limit when that's smaller."""
    cap = limit()
    return min(budget, cap) if cap is not None else budget


def _path(where, slot_id):
    return where / f"slot-{slot_id:02d}.lock"


def _open(path, create=True):
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0) | (os.O_CREAT if create else 0)
    return os.open(path, flags, 0o666)


def _lock(fd):
    """Take fd's slot lock if it's free (True), without waiting."""
    try:
        if sys.platform == "win32":
            os.lseek(fd, LOCK_AT, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _drop(fd):
    """Give up fd's slot lock and close it."""
    try:
        if sys.platform == "win32":
            os.lseek(fd, LOCK_AT, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def _note(fd, slot_id, what):
    """Write who holds the slot at the start of its file, for status()."""
    note = json.dumps({"id": slot_id, "pid": os.getpid(), "what": what, "since": common._now(),
                       "checkout": str(config.REPO)}, ensure_ascii=False).encode("utf-8")
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, note)
        os.ftruncate(fd, len(note))
    except OSError:
        pass                # the slot is held all the same; status() just can't say by whom


def _take(where, budget, n, what, prefer=None):
    """Lock up to n free slots of ids 0..budget-1, lowest first (prefer first, when it's one
    of them): {id: fd}. OSError when not one slot file could be opened."""
    got, error, opened = {}, None, 0
    order = list(range(budget))
    if isinstance(prefer, int) and not isinstance(prefer, bool) and 0 <= prefer < budget:
        order.remove(prefer)
        order.insert(0, prefer)
    try:
        for slot_id in order:
            if len(got) >= n:
                break
            try:
                fd = _open(_path(where, slot_id))
            except OSError as e:
                error = e
                continue
            opened += 1
            if _lock(fd):
                got[slot_id] = fd
                _note(fd, slot_id, what)
            else:
                os.close(fd)
    except BaseException:
        for fd in got.values():
            _drop(fd)
        raise
    if not opened and error is not None:
        raise error
    return got


def _let_go(fds, lock):
    """A lease's slots, given up (its finalizer)."""
    with lock:
        held = list(fds.values())
        fds.clear()
    for fd in held:
        _drop(fd)


class Lease:
    """Slots held, until release() (claim(); the module docstring has the API)."""

    def __init__(self, fds=None):
        self._fds = dict(fds or {})         # {slot id: the file descriptor holding its lock}
        self._lock = threading.Lock()
        self._finalizer = weakref.finalize(self, _let_go, self._fds, self._lock)

    @property
    def ids(self):
        with self._lock:
            return sorted(self._fds)

    def __len__(self):
        with self._lock:
            return len(self._fds)

    def __bool__(self):
        return len(self) > 0

    def release(self, slot_id=None):
        """Give up slot slot_id, or (None) every slot held."""
        with self._lock:
            if slot_id is None:
                held = list(self._fds.values())
                self._fds.clear()
            else:
                fd = self._fds.pop(slot_id, None)
                held = [] if fd is None else [fd]
        for fd in held:
            _drop(fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()

    def __repr__(self):
        return f"<slots.Lease {self.ids}>"


def claim(n, budget=None, *, wait=True, cancel=None, waiting=None, what=None, poll=None, prefer=None):
    """Claim up to n free slots of the budget's (the module docstring says how)."""
    n, budget = int(n), _budget(budget)
    if n < 1:
        raise ValueError(f"n must be a whole number of 1 or more, not {n!r}")
    poll = POLL_S if poll is None else poll
    where = folder()
    where.mkdir(parents=True, exist_ok=True)
    wanting = None              # its want while it waits (the module docstring's "Wants")
    try:
        while True:
            now = _limited(budget)          # looked at each try: the limit may change while it waits
            got = _take(where, now, min(n, now), what, prefer)
            if got or not wait:
                return Lease(got)
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if wanting is None:
                try:
                    wanting = want(what)
                except OSError:
                    wanting = Want(None, None)      # waits all the same, unseen (tried once)
            if waiting is not None:
                waiting()
            if cancel is not None:
                if cancel.wait(poll):
                    raise Cancelled()
            else:
                time.sleep(poll)
    finally:
        if wanting is not None:
            wanting.release()


class Want:
    """Someone in this process waits for a slot (want()), until release()."""

    def __init__(self, path, fd):
        self.path = path
        self._fd = fd
        self._lock = threading.Lock()
        self._finalizer = weakref.finalize(self, _let_go, {0: fd} if fd is not None else {}, self._lock)

    def release(self):
        """It waits no more: its file is unlocked and deleted (once is enough)."""
        self._finalizer()
        if self.path is not None:
            try:
                self.path.unlink()
            except OSError:
                pass            # another process looking at it now: the next waiting() deletes it
            self.path = None

    def __repr__(self):
        return f"<slots.Want {self.path}>"


_want_numbers = itertools.count()


def want(what=None):
    """Say this process waits for a slot: a Want, until its release() (the module
    docstring's "Wants"). OSError when its file can't be made."""
    where = folder()
    where.mkdir(parents=True, exist_ok=True)
    while True:
        path = where / f"want-{os.getpid()}-{next(_want_numbers)}.lock"
        fd = _open(path)
        if _lock(fd):
            _note(fd, None, what)
            return Want(path, fd)
        os.close(fd)            # (a name this process can't have used: try the next)


def waiting(exclude=None):
    """How many wants there are now on this PC, leaving out exclude (a Want, or None). A
    want whose process has ended has no lock: its file is deleted. OSError never: a
    folder that can't be read has none."""
    mine = exclude.path if exclude is not None else None
    count = 0
    try:
        paths = list(folder().glob(WANT_GLOB))
    except OSError:
        return 0
    for path in paths:
        if mine is not None and path == mine:
            continue
        try:
            fd = _open(path, create=False)
        except OSError:
            continue            # gone (released), or being made or deleted right now
        if _lock(fd):
            _drop(fd)           # nobody holds it: its process has ended (or it was just released)
            try:
                path.unlink()
            except OSError:
                pass
        else:
            os.close(fd)
            count += 1
    return count


def _read_note(fd):
    """A held slot's note (see _note), or {} when it can't be read."""
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        note = json.loads(os.read(fd, NOTE_MAX).decode("utf-8"))
    except (OSError, ValueError):
        return {}
    return note if isinstance(note, dict) else {}


def status(budget=None):
    """Which slots are held, and by whom (the module docstring has its shape). A free
    slot's lock is taken for a moment to find it free, so a claim at that very moment
    may pass it over for the next."""
    budget = _budget(budget)
    where = folder()
    ids = set(range(budget))
    try:
        for path in where.glob("slot-*.lock"):
            number = path.stem[len("slot-"):]
            if number.isdigit():
                ids.add(int(number))
    except OSError:
        pass
    rows = []
    for slot_id in sorted(ids):
        row = {"id": slot_id, "held": False, "pid": None, "what": None, "since": None, "checkout": None}
        try:
            fd = _open(_path(where, slot_id), create=False)
        except OSError:
            fd = None           # no file yet (never used), or gone: free
        if fd is not None:
            if _lock(fd):
                _drop(fd)
            else:
                note = _read_note(fd)
                os.close(fd)
                row.update(held=True, **{k: note.get(k) for k in ("pid", "what", "since", "checkout")})
        if row["held"] or slot_id < budget:
            rows.append(row)
    return {"folder": str(where), "budget": budget, "limit": limit(), "slots": rows}
