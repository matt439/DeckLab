"""Private bounded metadata for explicitly requested unfinished server runs.

Records are partitioned by starter before any file is read. This is operational
metadata in the gitignored cache, not inventory/state data or an automatic queue.
"""
import atexit
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time

from decklab.lib import config, profiles
from . import lifecycle
from . import slots
from .run_journal_lease import Lease

VERSION = 1
ROOT_ENV = "DECKLAB_RUN_JOURNAL"       # fixture/server-child isolation, like DECKLAB_SHOP_SNAPSHOT
MAX_RECORDS = 128
MAX_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
KINDS = frozenset({"field", "group", "gauntlet", "variant", "variant_more"})
STATES = frozenset({"queued", "running", "interrupted"})
ID = re.compile(r"[0-9a-f]{32}\Z")
FIELDS = frozenset({"version", "id", "starter", "session", "kind", "request", "manifest", "state", "created", "updated"})
UNAVAILABLE = "Unfinished-run recovery metadata cannot be verified or saved on the PC. No new run was started."


class JournalUnavailable(OSError):
    def __init__(self):
        super().__init__(UNAVAILABLE)


def root_path():
    return Path(os.environ[ROOT_ENV]) if os.environ.get(ROOT_ENV) else config.DATA / "forge" / "run-journal"


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _valid(record, starter, record_id):
    if not isinstance(record, dict) or set(record) != FIELDS or type(record["version"]) is not int \
            or record["version"] != VERSION or record["id"] != record_id or record["starter"] != starter:
        return False
    if not isinstance(record["session"], str) or not ID.fullmatch(record["session"]) \
            or record["kind"] not in KINDS or record["state"] not in STATES \
            or not isinstance(record["request"], dict) or not isinstance(record["manifest"], dict):
        return False
    try:
        return all(isinstance(record[key], str) and len(record[key]) <= 40 and datetime.fromisoformat(record[key]).tzinfo is not None
                   for key in ("created", "updated"))
    except ValueError:
        return False


class Journal:
    """One local cache root. A lease is created only for an accepted start, never a read."""
    def __init__(self, root=None):
        self.root = Path(root if root is not None else root_path())
        self._lease = None
        self._lock = threading.RLock()

    def _ordinary(self, path, *, directory=True):
        try:
            if not self.root.is_absolute():
                raise JournalUnavailable()
            lifecycle._ordinary(path, directory=directory)
        except (OSError, lifecycle.LifecycleError):
            raise JournalUnavailable() from None

    def _folder(self, starter, *, create=False):
        if not profiles.valid_id(starter):
            raise JournalUnavailable()
        path = self.root / starter
        self._ordinary(path)
        if create:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def _path(self, starter, record_id):
        if not isinstance(record_id, str) or not ID.fullmatch(record_id):
            raise JournalUnavailable()
        path = self._folder(starter) / (record_id + ".json")
        self._ordinary(path, directory=False)
        return path

    def _session(self):
        if self._lease is None:
            path = self.root / ".sessions"
            self._ordinary(path)
            try:
                self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
                self._lease = Lease(path)
            except OSError:
                raise JournalUnavailable() from None
        return self._lease

    @contextmanager
    def _mutation(self, starter):
        """Serialize record claims across server processes; never wait indefinitely."""
        folder = self._folder(starter, create=True)
        path = folder / ".mutation.lock"
        self._ordinary(path, directory=False)
        fd, held = None, False
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
            for _ in range(50):
                if slots._lock(fd):
                    held = True
                    break
                time.sleep(0.01)
            if not held:
                raise JournalUnavailable()
            yield
        except OSError:
            raise JournalUnavailable() from None
        finally:
            if fd is not None:
                if held:
                    slots._drop(fd)
                else:
                    os.close(fd)

    def get(self, starter, record_id):
        try:
            path = self._path(starter, record_id)
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise JournalUnavailable()
            record = json.loads(raw)
            if not _valid(record, starter, record_id):
                raise JournalUnavailable()
            return record
        except FileNotFoundError:
            return None
        except (OSError, ValueError, RecursionError, TypeError):
            raise JournalUnavailable() from None

    def records(self, starter):
        folder = self._folder(starter)
        try:
            if not folder.exists():
                return []
            paths = sorted(path for path in folder.iterdir() if ID.fullmatch(path.stem) and path.suffix == ".json")
            if len(paths) > MAX_RECORDS or sum(path.stat().st_size for path in paths) > MAX_TOTAL_BYTES:
                raise JournalUnavailable()
            return [record for path in paths if (record := self.get(starter, path.stem)) is not None]
        except OSError:
            raise JournalUnavailable() from None

    def _write(self, record):
        target = self._path(record["starter"], record["id"])
        temporary = None
        try:
            data = _json(record)
            if len(data) > MAX_BYTES or not _valid(record, record["starter"], record["id"]):
                raise JournalUnavailable()
            existing = self.records(record["starter"])
            if sum(len(_json(item)) for item in existing if item["id"] != record["id"]) + len(data) > MAX_TOTAL_BYTES:
                raise JournalUnavailable()
            self._folder(record["starter"], create=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".run-", suffix=".tmp", dir=target.parent)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except (OSError, ValueError, TypeError, RecursionError):
            raise JournalUnavailable() from None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    def create(self, starter, kind, request, manifest):
        with self._lock, self._mutation(starter):
            if kind not in KINDS or not isinstance(request, dict) or not isinstance(manifest, dict):
                raise JournalUnavailable()
            if len(self.records(starter)) >= MAX_RECORDS:
                raise JournalUnavailable()
            now = _now()
            record = {"version": VERSION, "id": secrets.token_hex(16), "starter": starter, "session": self._session().token,
                      "kind": kind, "request": copy.deepcopy(request), "manifest": copy.deepcopy(manifest),
                      "state": "queued", "created": now, "updated": now}
            self._write(record)
            return record

    def transition(self, starter, record_id, event):
        with self._lock, self._mutation(starter):
            record = self.get(starter, record_id)
            if record is None:
                return
            if event in ("done", "cancelled", "failed", "dismissed"):
                self._path(starter, record_id).unlink(missing_ok=True)
                return
            if event not in ("running", "interrupted", "queued"):
                raise JournalUnavailable()
            record.update(state=event, updated=_now())
            if event == "queued":
                record["session"] = self._session().token
            self._write(record)

    def claim(self, starter, record_id, manifest):
        """Atomically reuse one interrupted request, after the caller revalidated its complete plan."""
        with self._lock, self._mutation(starter):
            record = self.get(starter, record_id)
            if record is None or not self.inactive(record):
                raise JournalUnavailable()
            previous = record["manifest"]
            same = previous == manifest or (isinstance(previous.get("signature"), str)
                                              and previous.get("signature") == manifest.get("signature"))
            if not same:
                raise ValueError("The original run's saved lists, engine or participants changed; start a new run instead")
            record.update(state="queued", session=self._session().token, manifest=copy.deepcopy(manifest), updated=_now())
            self._write(record)
            return record

    def inactive(self, record):
        if record["state"] == "interrupted":
            return True
        if self._lease is not None:
            return self._lease.inactive(record["session"])
        # Read-only lease probe: do not manufacture this process's own session.
        probe = object.__new__(Lease)
        probe.folder, probe.token, probe.fd = self.root / ".sessions", None, None
        self._ordinary(probe.folder)
        return probe.inactive(record["session"])

    def close(self):
        with self._lock:
            if self._lease is not None:
                self._lease.close()
                self._lease = None


_stores = {}
_stores_lock = threading.Lock()


def store():
    root = root_path()
    with _stores_lock:
        return _stores.setdefault(str(root), Journal(root))


def close():
    with _stores_lock:
        for journal in _stores.values():
            journal.close()
        _stores.clear()


def close_root(root):
    """Release one fixture/server instance without disturbing another root's lease."""
    with _stores_lock:
        journal = _stores.pop(str(Path(root)), None)
        if journal is not None:
            journal.close()


atexit.register(close)
