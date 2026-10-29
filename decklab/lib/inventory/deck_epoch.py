"""Check a supplied database capture for one HOME house-deck incarnation.

No reader, connection, configuration or permissions live here. A provider must
capture current identities, aliases and complete history coherently. Only the
latest history text is needed; neither it nor private audit metadata is relayed.
An imported initial M establishes a database baseline, never a historical birth.
"""
import hashlib
import re
from dataclasses import dataclass

MAX_HISTORY = 10_000
MAX_ALIASES = 5_000
MAX_CURRENT_IDS = 5_000
MAX_TEXT_BYTES = 2 * 1024 * 1024
_CAPTURE_KEYS = frozenset({"backend", "persisted", "stale", "complete", "requested_id", "current",
                           "current_ids", "aliases", "history", "latest"})
_ROW_KEYS = frozenset({"deck_id", "revision", "op", "change_set_id"})


@dataclass(frozen=True)
class Epoch:
    kind: str
    deck_id: str
    revision: int


@dataclass(frozen=True)
class Receipt:
    deck_id: str
    revision: int
    sha256: str


@dataclass(frozen=True)
class Resolution:
    status: str
    epoch: Epoch | None = None
    receipt: Receipt | None = None


UNAVAILABLE = Resolution("unavailable")


def home_id(value):
    """Safe HOME casual/commander identity syntax, without an existence lookup."""
    if type(value) is not str or not 3 <= len(value) <= 200:
        return False
    kind, separator, slug = value.partition("/")
    if (not separator or kind not in ("casual", "commander") or not slug or slug != slug.strip()
            or slug.startswith(".") or re.search(r"[/\\:\x00-\x1f\x7f]", slug)):
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def _looks_home(value):
    return type(value) is str and value.startswith(("casual/", "commander/"))


def _identity(requested_id, current_ids, aliases):
    if (not home_id(requested_id) or type(current_ids) not in (list, tuple)
            or not 1 <= len(current_ids) <= MAX_CURRENT_IDS or type(aliases) is not dict
            or len(aliases) > MAX_ALIASES or not all(home_id(value) for value in current_ids)):
        return None
    current = set(current_ids)
    if len(current) != len(current_ids):
        return None
    home = {}
    for raw, target in aliases.items():
        if type(raw) is not str:
            return None
        if target is None:
            if _looks_home(raw):
                if not home_id(raw) or raw in current:
                    return None
                home[raw] = None  # Supplied retired sentinel; actual DB alias targets are non-NULL.
            continue
        if type(target) is not str:
            return None
        # Unrelated member edges cannot affect a HOME identity. A member edge
        # entering HOME is retained here and fails the strict endpoint checks.
        if not _looks_home(raw) and not _looks_home(target):
            continue
        if (not home_id(raw) or not home_id(target) or raw.partition("/")[0] != target.partition("/")[0]
                or raw == target or raw in current):
            return None
        home[raw] = target
    if any(target in home for target in home.values()):
        return None  # flattened means no chains or cycles, even through former names
    canonical = home.get(requested_id, requested_id)
    if canonical not in current:
        return None
    lineage = frozenset({canonical, *(raw for raw, target in home.items() if target == canonical)})
    return canonical, lineage


def identity(requested_id, current_ids, aliases):
    """Canonical current ID, or None when the bounded HOME identity proof is unknown."""
    checked = _identity(requested_id, current_ids, aliases)
    return checked[0] if checked is not None else None


def _text_bytes(value):
    if type(value) is not str or len(value) > MAX_TEXT_BYTES or "\x00" in value or "\r" in value:
        return None
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        return None
    return encoded if len(encoded) <= MAX_TEXT_BYTES else None


def resolve(capture):
    """Return only a checked immutable epoch/receipt, or one fixed unavailable result.

    history contains exact metadata dictionaries, in any order, covering every
    revision from 1 through current.revision. latest is the separately captured
    last row's identity, revision and text. complete=False includes capped reads.
    """
    if (type(capture) is not dict or capture.keys() != _CAPTURE_KEYS or type(capture["backend"]) is not str
            or capture["backend"] != "db" or capture["persisted"] is not True
            or capture["stale"] is not None or capture["complete"] is not True):
        return UNAVAILABLE
    current, latest = capture["current"], capture["latest"]
    if (type(current) is not dict or current.keys() != {"id", "revision", "text"}
            or type(current["revision"]) is not int or not 1 <= current["revision"] <= MAX_HISTORY
            or type(latest) is not dict or latest.keys() != {"deck_id", "revision", "text"}):
        return UNAVAILABLE
    checked = _identity(capture["requested_id"], capture["current_ids"], capture["aliases"])
    if checked is None:
        return UNAVAILABLE
    canonical, lineage = checked
    if type(current["id"]) is not str or current["id"] != canonical:
        return UNAVAILABLE
    rows = capture["history"]
    if type(rows) not in (list, tuple) or len(rows) != current["revision"]:
        return UNAVAILABLE
    for row in rows:
        if (type(row) is not dict or row.keys() != _ROW_KEYS or not home_id(row["deck_id"])
                or row["deck_id"] not in lineage or type(row["revision"]) is not int
                or not 1 <= row["revision"] <= current["revision"] or type(row["op"]) is not str
                or row["op"] not in ("A", "M", "D") or row["change_set_id"] is not None
                and (type(row["change_set_id"]) is not int or row["change_set_id"] < 1)):
            return UNAVAILABLE
    ordered = sorted(rows, key=lambda row: row["revision"])
    if any(row["revision"] != index for index, row in enumerate(ordered, 1)):
        return UNAVAILABLE
    alive, epoch = False, None
    for row in ordered:
        op = row["op"]
        if row["revision"] == 1 and op == "M" and row["change_set_id"] is None:
            alive, epoch = True, Epoch("baseline", row["deck_id"], 1)
        elif op == "A" and not alive:
            alive, epoch = True, Epoch("creation", row["deck_id"], row["revision"])
        elif op == "M" and alive:
            pass
        elif op == "D" and alive:
            alive, epoch = False, None
        else:
            return UNAVAILABLE
    last = ordered[-1]
    if (not alive or epoch is None or last["deck_id"] != canonical or type(latest["deck_id"]) is not str
            or latest["deck_id"] != last["deck_id"] or type(latest["revision"]) is not int
            or latest["revision"] != last["revision"]):
        return UNAVAILABLE
    text = _text_bytes(current["text"])
    if text is None or _text_bytes(latest["text"]) is None or latest["text"] != current["text"]:
        return UNAVAILABLE
    return Resolution("ready", epoch, Receipt(canonical, current["revision"], hashlib.sha256(text).hexdigest()))
