"""Cooperative results-root claims for Forge writers and member maintenance.

The lock lives beside the results, so quarantining results cannot replace it.
OS handles release a crashed process's claim; durable journals still stop new
writers until maintenance has resolved the database transaction's outcome.
"""
import json
import os
import stat
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from inspect import signature
from pathlib import Path

from . import common

VERSION = 1
BUSY = "Forge results are in use; retry after the current run or maintenance finishes."
PENDING = "Forge results need member-removal recovery before another run can start."
DEPARTED = "This run refers to a removed member's deck; choose current decks again."
UNSAFE = "Forge results lifecycle files could not be checked safely."
_local = threading.local()


class LifecycleError(common.ForgeError):
    """A claim or a durable lifecycle guard refused the operation."""


@dataclass(frozen=True)
class Claim:
    root: Path
    control_dir: Path


def _ordinary(path, *, directory=True):
    """Check existing components before resolve can conceal a link/junction."""
    for item in (*reversed(path.parents), path):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, "st_file_attributes", 0) & 0x400):
            raise LifecycleError(UNSAFE)
        expected_dir = directory or item != path
        if not (stat.S_ISDIR(info.st_mode) if expected_dir else stat.S_ISREG(info.st_mode)):
            raise LifecycleError(UNSAFE)


def root_path(results_dir=None):
    path = Path(common._results_dir(results_dir))
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        # Keep lexical '..' components until every component has been checked:
        # abspath would hide a junction before '..' and claim a different root.
        _ordinary(path)
        root = path.resolve()
        if root.parent == root:
            raise LifecycleError(UNSAFE)
        return root
    except (OSError, LifecycleError) as error:
        common._log(f"Forge result root could not be claimed at {path}: {error}")
        if isinstance(error, LifecycleError):
            raise
        raise LifecycleError(UNSAFE) from None


def capability(results_dir=None):
    """Read-only identity advertised by a process using these writer hooks."""
    return {"version": VERSION, "root": str(root_path(results_dir))}


def _prepare(root):
    control = root.with_name(f".{root.name}-lifecycle")
    try:
        _ordinary(control)
        root.parent.mkdir(parents=True, exist_ok=True)
        control.mkdir(exist_ok=True)
        _ordinary(root)
        _ordinary(control)
        lock = control / "claim.lock"
        _ordinary(lock, directory=False)
        fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _ordinary(lock, directory=False)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise LifecycleError(UNSAFE)
        except BaseException:
            os.close(fd)
            raise
        return Claim(root, control), fd
    except OSError:
        raise LifecycleError(UNSAFE) from None


def _lock(fd, exclusive):
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        class Overlapped(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                        ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                        ("hEvent", wintypes.HANDLE)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        lock = kernel.LockFileEx
        lock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                         wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
        lock.restype = wintypes.BOOL
        overlap = Overlapped()
        # Shared claims overlap; the exclusive maintenance claim conflicts with all.
        if not lock(msvcrt.get_osfhandle(fd), 1 | (2 if exclusive else 0), 0, 1, 0,
                    ctypes.byref(overlap)):
            code = ctypes.get_last_error()
            raise LifecycleError(BUSY if code in (32, 33, 158) else UNSAFE)
    else:
        import fcntl
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LifecycleError(BUSY) from None


@contextmanager
def _claim(results_dir, exclusive):
    root = root_path(results_dir)
    held = getattr(_local, "held", None)
    if held is None:
        held = _local.held = {}
    key = os.path.normcase(str(root))
    if key in held:
        claim, is_exclusive = held[key]
        if exclusive and not is_exclusive:
            raise LifecycleError(BUSY)  # never upgrade a live shared claim
        yield claim
        return
    claim, fd = _prepare(root)
    try:
        _lock(fd, exclusive)
        held[key] = (claim, exclusive)
        try:
            yield claim
        finally:
            del held[key]
    finally:
        os.close(fd)  # closing releases the OS claim, including after any exception


def _departed(claim):
    path = claim.control_dir / "departed.json"
    try:
        _ordinary(path, directory=False)
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return frozenset()
    except (OSError, ValueError):
        raise LifecycleError(UNSAFE) from None
    from decklab.lib import profiles
    if (not isinstance(value, dict) or type(value.get("version")) is not int or
            value["version"] != VERSION or
            not isinstance(value.get("spaces"), list) or
            any(not profiles.valid_id(space) or space in profiles.RESERVED_SPACES
                for space in value["spaces"])):
        raise LifecycleError(UNSAFE)
    return frozenset(value["spaces"])


def references(value):
    """Deck identifiers in result provenance, without traversing game/card logs."""
    found = set()
    if isinstance(value, str):
        found.add(value)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            found.update(references(item))
    elif isinstance(value, dict):
        for key in ("id", "deck_id", "sides", "seen_as", "deck", "base", "against",
                    "opponents", "paired", "variant", "pairs", "runs"):
            if key in value:
                found.update(references(value[key]))
        if isinstance(value.get("per_opponent"), dict):
            found.update(value["per_opponent"])
    return found


def check_decks(claim, deck_ids):
    """Reject newly introduced inputs from a departed space, even queued jobs."""
    from decklab.lib import spaces
    departed = _departed(claim)
    for deck_id in deck_ids:
        if not isinstance(deck_id, str):
            continue
        if deck_id.startswith("variant:"):
            deck_id = deck_id[len("variant:"):]
        try:
            owner = spaces.split_deck_id(deck_id.split("@", 1)[0])[0]
        except ValueError:
            continue
        if owner in departed:
            raise LifecycleError(DEPARTED)


@contextmanager
def writer(results_dir=None, *, deck_ids=()):
    with _claim(results_dir, False) as claim:
        pending = claim.control_dir / "pending"
        try:
            _ordinary(pending)
            if pending.exists():
                for path in pending.iterdir():
                    _ordinary(path, directory=path.is_dir())
                    if path.suffix.lower() == ".json":
                        raise LifecycleError(PENDING)
        except OSError:
            raise LifecycleError(UNSAFE) from None
        check_decks(claim, deck_ids)
        yield claim


@contextmanager
def maintenance(results_dir=None):
    """Exclusive claim; pending journals are deliberately allowed for recovery."""
    with _claim(results_dir, True) as claim:
        yield claim


def writing(*inputs, save=None):
    """Hold a writer claim across an entire operation, including its first read.

    Bound arguments keep signatures and keyword defaults intact. `save` names
    the optional switch for operations which can deliberately avoid all writes.
    """
    def decorate(fn):
        parameters = signature(fn)

        @wraps(fn)
        def claimed(*args, **kwargs):
            bound = parameters.bind(*args, **kwargs)
            bound.apply_defaults()
            if save is not None and not bound.arguments[save]:
                return fn(*args, **kwargs)
            ids = references([bound.arguments[name] for name in inputs])
            with writer(bound.arguments.get("results_dir"), deck_ids=ids):
                return fn(*args, **kwargs)
        return claimed
    return decorate
