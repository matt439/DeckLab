"""Private coordination for profile edits; ordinary configuration reads stay unchanged.

The lock is process- and thread-aware. A durable pending journal gates profile/auth
reads after a crash until the exact audited database outcome has been recovered.
This is process-crash recovery, not a hardware transaction across disk and PostgreSQL.
"""
import base64
import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from decklab.lib import config

MAX_CONFIG = 4 * 1024 * 1024
_locks = {}
_lock_guard = threading.Lock()
_local = threading.local()


class InvalidProfileEdit(ValueError):
    """A static, safe-to-display profile edit refusal."""


class StaleProfileEdit(ValueError):
    """The reviewed configuration or membership has changed."""


class PendingProfileEdit(ValueError):
    """Profile publication needs local recovery before it can be used."""


PENDING = "A member update needs recovery. Run python -m decklab.db sync-profiles on the PC, then reload."


def ordinary(path):
    path = Path(path).absolute()
    if any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)):
        raise InvalidProfileEdit("Member updates cannot use linked configuration paths.")
    return path


def control():
    return ordinary(ordinary(config.CONFIG_FILE).parent / "data" / "profile-config")


def pending():
    return ordinary(control() / "pending.json").exists()


def require_ready():
    if pending():
        raise PendingProfileEdit(PENDING)


def read_settings():
    """Profile-specific reader; DB connection settings remain readable for recovery."""
    require_ready()
    settings = config.load()
    require_ready()
    return settings


@contextmanager
def claim(*, allow_pending=False):
    """One bounded exclusive coordinator, reentrant only on its owning thread."""
    folder = control()
    key = os.path.normcase(str(folder))
    with _lock_guard:
        mutex = _locks.setdefault(key, threading.RLock())
    if not mutex.acquire(timeout=2):
        raise PendingProfileEdit("Member settings are busy. Reload and try again.")
    held = getattr(_local, "held", None)
    if held is None:
        held = _local.held = set()
    fd = None
    nested = key in held
    try:
        if not nested:
            folder.mkdir(parents=True, exist_ok=True)
            ordinary(folder)
            path = ordinary(folder / "claim.lock")
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise PendingProfileEdit("Member settings are busy or unavailable. Reload and try again.") from None
            held.add(key)
        if not allow_pending:
            require_ready()
        yield
    finally:
        if not nested:
            held.discard(key)
            if fd is not None:
                os.close(fd)
        mutex.release()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode("utf-8")


def _object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def parse(raw):
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid number")))
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidProfileEdit("Member configuration must be a valid JSON object without duplicate keys.") from None


def snapshot():
    """Read raw source, never merged defaults or harness overrides."""
    if os.environ.get(config.EXTRA_ENV):
        raise InvalidProfileEdit("Member settings cannot be edited while a configuration override is active.")
    try:
        path = ordinary(config.CONFIG_FILE)
        if path.stat().st_size > MAX_CONFIG:
            raise InvalidProfileEdit("Member configuration is too large to edit here.")
        raw = path.read_bytes()
        if len(raw) > MAX_CONFIG:
            raise InvalidProfileEdit("Member configuration is too large to edit here.")
    except OSError:
        raise InvalidProfileEdit("Member configuration could not be read. Check it locally before editing.") from None
    return raw, parse(raw)


def write_bytes(path, raw):
    """Publish a complete regular file by same-directory atomic replacement."""
    path = ordinary(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".profile-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        ordinary(path)
        os.replace(temporary, path)
        if os.name != "nt":
            parent = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(journal):
    require_ready()
    write_bytes(control() / "pending.json", json_bytes(journal))


def load_journal():
    try:
        raw = ordinary(control() / "pending.json").read_bytes()
        if len(raw) > 3 * MAX_CONFIG:
            raise ValueError
        journal = parse(raw)
        if journal.get("version") != 1 or journal.get("config_path") != str(ordinary(config.CONFIG_FILE)):
            raise ValueError
        for name in ("before", "after"):
            content = base64.b64decode(journal[name], validate=True)
            if len(content) > MAX_CONFIG or digest(content) != journal[name + "_sha256"]:
                raise ValueError
            parse(content)
        if type(journal["change_set_id"]) is not int or journal["change_set_id"] < 1:
            raise ValueError
        if not re.fullmatch(r"[0-9a-f]{32}", journal["operation"]):
            raise ValueError
        if not isinstance(journal["database"], dict) or not isinstance(journal["actor"], str):
            raise ValueError
        return journal
    except (OSError, ValueError, TypeError, KeyError):
        raise PendingProfileEdit(PENDING) from None


def complete():
    ordinary(control() / "pending.json").unlink()
