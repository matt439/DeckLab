"""Exact owner-only wishlist metadata inverses over authoritative raw audit rows.

No card index, inventory revision or physical-card inference is involved. Adapters
must supply all evidence under their admitted per-profile write/read lock.
"""
import copy
import hashlib
import json
import re

from . import Conflict, Invalid, rules

RAW_FIELDS = {"profile_id", "position", "name", "set_code", "collector_number", "notes", "source"}
IMMUTABLE = RAW_FIELDS - {"notes", "source"}
KEY_FIELDS = {"profile_id", "position"}
FIELDS = ("notes", "source")
SHA = re.compile(r"[a-f0-9]{64}")


class UndoMissing(Invalid):
    def __init__(self):
        super().__init__("That change is not available to undo.")


class UndoUnsupported(Invalid):
    pass


class UndoConflict(Conflict):
    def __init__(self):
        super().__init__("The wishlist changed. Reload Activity and review this Undo again.")


def _id(value):
    return type(value) is int and 0 < value < 2 ** 63


def _entry(raw, pid):
    if not isinstance(raw, dict) or set(raw) != RAW_FIELDS or raw["profile_id"] != pid \
            or type(raw["position"]) is not int or raw["position"] < 0:
        raise UndoUnsupported("The recorded wishlist row cannot be restored exactly.")
    entry = {"name": raw["name"], "set": raw["set_code"] or "", "number": raw["collector_number"] or "",
             "notes": raw["notes"], "source": raw["source"]}
    try:
        checked = rules.entry(entry)
        roundtrip = {"profile_id": pid, "position": raw["position"], "name": checked["name"],
                     "set_code": checked["set"] or None, "collector_number": checked["number"] or None,
                     "notes": checked["notes"], "source": checked["source"]}
        if checked != entry or roundtrip != raw:
            raise ValueError("Nonexact row")
        json.dumps(raw, ensure_ascii=False).encode("utf-8")
    except (Invalid, ValueError, TypeError, UnicodeError):
        raise UndoUnsupported("The recorded wishlist row cannot be restored exactly.") from None
    return checked


def _layout(raw_entries, pid):
    if not isinstance(raw_entries, list) or len(raw_entries) > rules.MAX_ENTRIES:
        raise UndoConflict()
    positions, names = [], set()
    for row in raw_entries:
        item = _entry(row, pid)
        if positions and row["position"] <= positions[-1] or item["name"].casefold() in names:
            raise UndoConflict()
        positions.append(row["position"])
        names.add(item["name"].casefold())


def list_sha(raw_entries):
    try:
        value = json.dumps(raw_entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    except (ValueError, TypeError, UnicodeError):
        raise UndoUnsupported("The wishlist cannot be represented exactly.") from None


def review(change_id, pid, source_rows, raw_entries, latest_target, latest_owner):
    if not _id(change_id) or not isinstance(pid, str) or not rules.PROFILE_ID.fullmatch(pid):
        raise UndoMissing()
    if not isinstance(source_rows, list) or len(source_rows) != 1:
        raise UndoMissing()
    row = source_rows[0]
    if not isinstance(row, dict) or row.get("table") != "wishlist_entry" or row.get("op") != "UPDATE" \
            or not isinstance(row.get("before"), dict) or not isinstance(row.get("after"), dict) \
            or row["before"].get("profile_id") != pid or row["after"].get("profile_id") != pid:
        raise UndoMissing()
    old, new = row["before"], row["after"]
    if not _id(row.get("id")):
        raise UndoUnsupported("The original wishlist audit identity cannot be checked.")
    restored, current = _entry(old, pid), _entry(new, pid)
    if not isinstance(row.get("key"), dict) or set(row["key"]) != KEY_FIELDS \
            or type(row["key"].get("position")) is not int \
            or row["key"] != {"profile_id": pid, "position": new["position"]} \
            or any(old[field] != new[field] for field in IMMUTABLE):
        raise UndoUnsupported("Only notes and source on the same wishlist entry can be undone here.")
    changed = [field for field in FIELDS if old[field] != new[field]]
    if not changed:
        raise UndoUnsupported("There is no wishlist metadata change to undo.")
    if rules.edited(current, notes=restored["notes"], source=restored["source"]) != restored:
        raise UndoUnsupported("The original wishlist values cannot be restored exactly.")
    _layout(raw_entries, pid)
    found = [index for index, item in enumerate(raw_entries) if item["position"] == new["position"]]
    if len(found) != 1 or raw_entries[found[0]] != new or latest_target != row["id"] \
            or not _id(latest_target) or not _id(latest_owner) or latest_owner < latest_target:
        raise UndoConflict()
    expected = copy.deepcopy(raw_entries)
    expected[found[0]] = copy.deepcopy(old)
    expect = list_sha([change_id, source_rows, raw_entries, latest_target, latest_owner])
    return {"change_id": change_id, "profile": pid, "kind": "wishlist", "action": "wishlist_update", "label": current["name"],
            "current": current, "restored": restored, "fields": [{"field": field, "before": current[field], "after": restored[field]}
                                                                  for field in changed],
            "expect": expect, "row_change_id": row["id"], "latest_owner": latest_owner, "raw_current": copy.deepcopy(new),
            "raw_restore": copy.deepcopy(old), "raw_after": expected, "sha256": list_sha(expected)}


def receipt(plan, actual_raw_entries, actual_new_source_rows, latest_owner):
    pid = plan["profile"]
    _layout(actual_raw_entries, pid)
    if actual_raw_entries != plan["raw_after"] or not isinstance(actual_new_source_rows, list) or len(actual_new_source_rows) != 1:
        raise UndoConflict()
    row = actual_new_source_rows[0]
    if isinstance(row, dict):
        try:
            _entry(row.get("before"), pid)
            _entry(row.get("after"), pid)
        except Invalid:
            raise UndoConflict() from None
    if not isinstance(row, dict) or row.get("table") != "wishlist_entry" or row.get("op") != "UPDATE" \
            or not isinstance(row.get("key"), dict) or type(row["key"].get("position")) is not int \
            or row.get("key") != {"profile_id": pid, "position": plan["raw_restore"]["position"]} \
            or row.get("before") != plan["raw_current"] or row.get("after") != plan["raw_restore"] \
            or not _id(row.get("id")) or row["id"] <= plan["latest_owner"] or not _id(latest_owner) or latest_owner != row["id"]:
        raise UndoConflict()
    actual = next(item for item in actual_raw_entries if item["position"] == plan["raw_restore"]["position"])
    return {"restored": _entry(actual, pid), "sha256": list_sha(actual_raw_entries), "revision": str(latest_owner)}
