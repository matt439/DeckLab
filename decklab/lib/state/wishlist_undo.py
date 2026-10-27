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
IMMUTABLE = {"profile_id", "position", "name"}
KEY_FIELDS = {"profile_id", "position"}
FIELDS = ("set", "number", "notes", "source")
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


def source_record(source_rows, pid):
    """Whole-source privacy before row values, labels or positions are inspected."""
    if not isinstance(source_rows, list) or len(source_rows) != 1:
        raise UndoMissing()
    row = source_rows[0]
    if not isinstance(row, dict) or not {"before", "after"} <= set(row) \
            or row.get("table") != "wishlist_entry" or row.get("op") not in ("UPDATE", "INSERT", "DELETE"):
        raise UndoMissing()
    old, new, op = row.get("before"), row.get("after"), row["op"]
    if (old is not None if op == "INSERT" else not isinstance(old, dict) or old.get("profile_id") != pid) \
            or (new is not None if op == "DELETE" else not isinstance(new, dict) or new.get("profile_id") != pid):
        raise UndoMissing()
    return row


def review(change_id, pid, source_rows, raw_entries, latest_target, latest_owner):
    if not _id(change_id) or not isinstance(pid, str) or not rules.PROFILE_ID.fullmatch(pid):
        raise UndoMissing()
    row = source_record(source_rows, pid)
    old, new = row["before"], row["after"]
    if not _id(row.get("id")):
        raise UndoUnsupported("The original wishlist audit identity cannot be checked.")
    restored, current = _entry(old, pid) if old is not None else None, _entry(new, pid) if new is not None else None
    target = new if new is not None else old
    if not isinstance(row.get("key"), dict) or set(row["key"]) != KEY_FIELDS \
            or type(row["key"].get("position")) is not int \
            or row["key"] != {"profile_id": pid, "position": target["position"]} \
            or row["op"] == "UPDATE" and any(old[field] != new[field] for field in IMMUTABLE):
        raise UndoUnsupported("Only the printing preference, notes and source on the same wishlist entry can be undone here.")
    presence = row["op"] != "UPDATE"
    if latest_target != row["id"] or not _id(latest_target) or not _id(latest_owner) or latest_owner < latest_target \
            or presence and latest_owner != row["id"]:
        raise UndoConflict()
    _layout(raw_entries, pid)
    expected = copy.deepcopy(raw_entries)
    extra = {}
    if row["op"] == "DELETE":
        if any(item["position"] == old["position"] for item in raw_entries):
            raise UndoConflict()
        dto = [_entry(item, pid) for item in raw_entries]
        index = sum(item["position"] < old["position"] for item in raw_entries)
        try:
            position, moves = rules.insert_slot([item["position"] for item in raw_entries], index)
            if rules.add_plan(dto, restored) != "add" or position != old["position"] or moves:
                raise Invalid("The original slot cannot be reproduced")
        except Invalid:
            raise UndoConflict() from None
        expected.insert(index, copy.deepcopy(old))
        action, extra = "wishlist_add", {"insert_at": index}
    else:
        found = [index for index, item in enumerate(raw_entries) if item["position"] == new["position"]]
        if len(found) != 1 or raw_entries[found[0]] != new:
            raise UndoConflict()
        if row["op"] == "INSERT":
            expected.pop(found[0])
            action = "wishlist_remove"
        else:
            changed = [field for field in FIELDS if current[field] != restored[field]]
            if not changed:
                raise UndoUnsupported("There is no wishlist metadata change to undo.")
            if rules.edited(current, set=restored["set"], number=restored["number"],
                            notes=restored["notes"], source=restored["source"]) != restored:
                raise UndoUnsupported("The original wishlist values cannot be restored exactly.")
            expected[found[0]] = copy.deepcopy(old)
            action = "wishlist_update"
            extra = {"fields": [{"field": field, "before": current[field], "after": restored[field]} for field in changed]}
    expect = list_sha([change_id, source_rows, raw_entries, latest_target, latest_owner])
    return {"change_id": change_id, "profile": pid, "kind": "wishlist", "action": action, "label": target["name"],
            "current": current, "restored": restored, **extra,
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
            if row.get("before") is not None:
                _entry(row["before"], pid)
            if row.get("after") is not None:
                _entry(row["after"], pid)
        except Invalid:
            raise UndoConflict() from None
    op = {"wishlist_update": "UPDATE", "wishlist_add": "INSERT", "wishlist_remove": "DELETE"}[plan["action"]]
    target = plan["raw_restore"] if plan["raw_restore"] is not None else plan["raw_current"]
    if not isinstance(row, dict) or not {"before", "after"} <= set(row) or row.get("table") != "wishlist_entry" or row.get("op") != op \
            or not isinstance(row.get("key"), dict) or type(row["key"].get("position")) is not int \
            or row.get("key") != {"profile_id": pid, "position": target["position"]} \
            or row.get("before") != plan["raw_current"] or row.get("after") != plan["raw_restore"] \
            or not _id(row.get("id")) or row["id"] <= plan["latest_owner"] or not _id(latest_owner) or latest_owner != row["id"]:
        raise UndoConflict()
    if op == "DELETE":
        return {"restored": None, "removed_name": target["name"], "sha256": list_sha(actual_raw_entries), "revision": str(latest_owner)}
    actual = next(item for item in actual_raw_entries if item["position"] == target["position"])
    return {"restored": _entry(actual, pid), "sha256": list_sha(actual_raw_entries), "revision": str(latest_owner)}
