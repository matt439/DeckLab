"""Pure, revisioned HOME field choices for exact house-deck incarnations.

No entry leaves the legacy selector unchanged. An explicit ``rules`` entry is
a retained tombstone: its future selector adapter must mask that incarnation's
legacy edits and recompute the automatic default, including its Built version.
Include pins a list version; exclude applies to the whole incarnation.

Parsing checks representable syntax, never current identity or provenance. A
future writer must hold its transaction's shared inventory claim before taking
the format-policy lock, without upgrading that claim. It must recompute and
compare deck_epoch.Resolution and Receipt on the same write connection before
accepting a no-op or mutating. Current IDs, list hashes and previously cached
ready resolutions are not identity proofs.
This module performs no reads, writes, permission checks or selector changes.
"""
from decklab.lib.inventory.deck_epoch import MAX_HISTORY, home_id

from . import Conflict, Invalid

MAX_RULES = 5_000
MAX_REVISION = 9_223_372_036_854_775_807
INVALID = "The field policy is invalid."
CHANGED = "The field policy changed. Reload it before saving."
_FORMATS = {"Constructed": "casual", "Commander": "commander"}
_SNAPSHOT_KEYS = frozenset({"v", "format", "revision", "rules"})
_EPOCH_KEYS = frozenset({"kind", "deck_id", "revision"})


def _format(value):
    if type(value) is not str or value not in _FORMATS:
        raise Invalid(INVALID)
    return value


def _revision(value):
    if type(value) is not int or not 0 <= value <= MAX_REVISION:
        raise Invalid(INVALID)
    return value


def _epoch(value, fmt):
    if (type(value) is not dict or value.keys() != _EPOCH_KEYS
            or type(value["kind"]) is not str or value["kind"] not in ("baseline", "creation")
            or not home_id(value["deck_id"]) or value["deck_id"].partition("/")[0] != _FORMATS[fmt]
            or type(value["revision"]) is not int or not 1 <= value["revision"] <= MAX_HISTORY
            or value["kind"] == "baseline" and value["revision"] != 1):
        raise Invalid(INVALID)
    return {key: value[key] for key in ("kind", "deck_id", "revision")}


def _key(epoch):
    return epoch["kind"], epoch["deck_id"], epoch["revision"]


def _rule(value, fmt):
    if type(value) is not dict or type(value.get("mode")) is not str:
        raise Invalid(INVALID)
    mode = value["mode"]
    if mode not in ("include", "exclude", "rules"):
        raise Invalid(INVALID)
    expected = {"epoch", "mode", "version"} if mode == "include" else {"epoch", "mode"}
    if value.keys() != expected:
        raise Invalid(INVALID)
    epoch = _epoch(value["epoch"], fmt)
    out = {"epoch": epoch, "mode": mode}
    if mode == "include":
        if type(value["version"]) is not str or value["version"] not in ("target", "owned"):
            raise Invalid(INVALID)
        out["version"] = value["version"]
    return out


def empty(fmt):
    """An independent never-saved policy for one exact format name."""
    return {"v": 1, "format": _format(fmt), "revision": 0, "rules": []}


def normalize(snapshot):
    """Validate complete v1 JSON-shaped state and return a detached sorted copy.

    Keys are full structured epochs, including the immutable historical origin
    ID. Obsolete epochs remain intact and inert; no current ID lookup or pruning
    happens here. Revision zero represents only the never-saved empty policy.
    """
    if (type(snapshot) is not dict or snapshot.keys() != _SNAPSHOT_KEYS
            or type(snapshot["v"]) is not int or snapshot["v"] != 1):
        raise Invalid(INVALID)
    fmt = _format(snapshot["format"])
    revision = _revision(snapshot["revision"])
    values = snapshot["rules"]
    if type(values) is not list or len(values) > MAX_RULES or revision == 0 and values:
        raise Invalid(INVALID)
    seen, rules = set(), []
    for value in values:
        rule = _rule(value, fmt)
        key = _key(rule["epoch"])
        if key in seen:
            raise Invalid(INVALID)
        seen.add(key)
        rules.append(rule)
    rules.sort(key=lambda rule: _key(rule["epoch"]))
    return {"v": 1, "format": fmt, "revision": revision, "rules": rules}


def lookup(snapshot, epoch):
    """A detached exact-epoch rule, or None for unchanged legacy selection.

    ``None`` and a rule with mode ``rules`` have different semantics. Supplying
    a syntactically valid epoch does not establish that it belongs to a current
    deck; only the future locked provider can establish that relationship.
    """
    current = normalize(snapshot)
    wanted = _key(_epoch(epoch, current["format"]))
    return next((rule for rule in current["rules"] if _key(rule["epoch"]) == wanted), None)


def transition(snapshot, expected_revision, rule):
    """Return {changed, snapshot} for one exact-epoch intent, without side effects.

    A stale revision conflicts even for identical intent. First Use rules saves
    its tombstone; repeating it is a no-op. Existing entries can change at the
    capacity limit, and matching no-ops can succeed at the revision limit. New
    entries never evict old epochs; a real revision overflow fails closed.
    """
    current = normalize(snapshot)
    expected = _revision(expected_revision)
    if current["revision"] != expected:
        raise Conflict(CHANGED)
    desired = _rule(rule, current["format"])
    wanted = _key(desired["epoch"])
    existing = next((index for index, old in enumerate(current["rules"])
                     if _key(old["epoch"]) == wanted), None)
    if existing is not None and current["rules"][existing] == desired:
        return {"changed": False, "snapshot": current}
    if current["revision"] == MAX_REVISION or existing is None and len(current["rules"]) == MAX_RULES:
        raise Invalid(INVALID)
    if existing is None:
        current["rules"].append(desired)
    else:
        current["rules"][existing] = desired
    current["rules"].sort(key=lambda value: _key(value["epoch"]))
    current["revision"] += 1
    return {"changed": True, "snapshot": current}
