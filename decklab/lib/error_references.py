"""Bounded operational error references: no actors, messages, files, deck IDs or addresses."""
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from urllib.parse import urlsplit

from decklab.lib import config

MAX_EVENTS = 200
PATH_ENV = "DECKLAB_ERROR_REFERENCES"        # disposable fixture/server-child isolation, like DECKLAB_DB_LOG
MAX_BYTES = 128 * 1024
REPORTS_PER_MINUTE = 30
PAGES = frozenset({"library", "deck", "edit", "new", "collection", "tokens", "shopping", "activity", "play",
                   "settings", "history", "compare", "matchups", "matchup", "variant", "field", "gauntlet", "other"})
TYPES = frozenset({"Error", "TypeError", "RangeError", "ReferenceError", "SyntaxError", "URIError", "EvalError",
                   "AggregateError", "ValueError", "KeyError", "RuntimeError", "AttributeError", "LookupError",
                   "AssertionError", "OSError", "UnicodeError", "JSONDecodeError"})
REF = re.compile(r"[0-9a-f]{32}\Z")
_lock = threading.RLock()
_received = deque()


def path():
    return Path(os.environ[PATH_ENV]) if os.environ.get(PATH_ENV) else config.DATA / "diagnostics" / "error-references.json"


def reference():
    return secrets.token_hex(16)


def api_page(target):
    """Only the first API resource kind; discard every ID, query and fragment."""
    try:
        parts = urlsplit(target).path.strip("/").split("/")
        page = parts[1] if parts[:1] == ["api"] and len(parts) > 1 else "other"
    except (TypeError, ValueError):
        page = "other"
    return page if page in PAGES else "other"


def _valid(event):
    if not isinstance(event, dict) or set(event) != {"reference", "page", "type", "at"}:
        return False
    if not isinstance(event["reference"], str) or not REF.fullmatch(event["reference"]) \
            or not isinstance(event["page"], str) or event["page"] not in PAGES \
            or not isinstance(event["type"], str) or event["type"] not in TYPES or not isinstance(event["at"], str):
        return False
    try:
        return datetime.fromisoformat(event["at"]).tzinfo is not None and len(event["at"]) <= 40
    except ValueError:
        return False


def read():
    try:
        with path().open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return [], False
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("events"), list) \
                or len(value["events"]) > MAX_EVENTS or not all(_valid(event) for event in value["events"]):
            return [], False
        return value["events"], True
    except FileNotFoundError:
        return [], True
    except (OSError, ValueError, TypeError, RecursionError):
        return [], False


def record(page, kind, ref=None):
    """Return (reference, stored|limited|unavailable); optional source fields stay enum-only."""
    ref = ref or reference()
    event = {"reference": ref, "page": page, "type": kind,
             "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if not _valid(event):
        raise ValueError("Invalid error-reference metadata")
    with _lock:
        now = time.monotonic()
        while _received and _received[0] <= now - 60:
            _received.popleft()
        if len(_received) >= REPORTS_PER_MINUTE:
            return ref, "limited"
        _received.append(now)
        events, ready = read()
        if not ready:
            return ref, "unavailable"
        if any(item["reference"] == ref for item in events):
            return ref, "stored"
        events = [*events, event][-MAX_EVENTS:]
        target = path()
        temporary = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".error-reference-", suffix=".tmp", dir=target.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "events": events}, stream, separators=(",", ":"))
            os.replace(temporary, target)
            return ref, "stored"
        except OSError:
            return ref, "unavailable"
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)


def unexpected(error, target):
    """A server crash's safe reference; the caller logs the private traceback locally."""
    kind = type(error).__name__
    kind = kind if kind in TYPES else "Error"
    ref = reference()
    try:
        record(api_page(target), kind, ref)
    except Exception:
        pass        # a failed diagnostic must never replace the original failure
    return ref
