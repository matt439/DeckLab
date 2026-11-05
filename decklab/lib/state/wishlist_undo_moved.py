"""Undo of a wishlist addition that moved other entries along to make room (E11-S08).

The Wishlist page's Undo of a removal (and any wishlist_add with ``at``) puts an entry at a
list index; when the slot before the next entry is taken, rules.insert_slot moves the entries
from that index up to the next free position one place up first. Its change is then 1-50
position-only UPDATEs followed by one INSERT, all of one profile's wishlist. The inverse deletes
the entry and moves each of those entries back to the position it had, lowest first, so the list
is exactly as it was before the addition, positions included.

Only the owner reviews or saves it, and only while that change is still the latest audit row of
the owner's wishlist and every touched entry is exactly as the change left it. Refusals give
counts and reasons only; no message quotes a wishlist note. Pure: adapters supply the raw source
rows, the owner's raw entries and the latest audit row id under their wishlist lock.
"""
import copy

from . import Invalid, rules, wishlist_undo as undo

MAX_MOVED = 50
KEY = ("profile_id", "position")


class Unsupported(undo.UndoUnsupported):
    """A shape this module can't undo. Its message is a fixed sentence (a count at most, never a
    note), so the API passes it on after the general one."""


def _own(row, pid):
    """Whether one raw audit row belongs wholly to pid's wishlist (privacy, before any value)."""
    if not isinstance(row, dict) or row.get("table") != "wishlist_entry" or row.get("op") not in ("UPDATE", "INSERT"):
        return False
    old, new = row.get("before"), row.get("after")
    if not isinstance(new, dict) or new.get("profile_id") != pid:
        return False
    return old is None if row["op"] == "INSERT" else isinstance(old, dict) and old.get("profile_id") == pid


def source_record(source_rows, pid, total=None):
    """(inserted, moved) for a complete source of moved entries and one addition, or UndoMissing.

    total is the whole change set's audit row count when the adapter fetched fewer rows (a change
    over the bound); every fetched row must still be pid's before the bound is mentioned."""
    if not isinstance(source_rows, list) or len(source_rows) < 2 or not all(_own(row, pid) for row in source_rows):
        raise undo.UndoMissing()
    if total is not None and (type(total) is not int or total < len(source_rows)):
        raise undo.UndoMissing()
    if len(source_rows) > MAX_MOVED + 1 or (total or 0) > MAX_MOVED + 1:
        raise Unsupported(f"Undo can put back at most {MAX_MOVED} moved wishlist entries in one change.")
    inserts = [row for row in source_rows if row["op"] == "INSERT"]
    if len(inserts) != 1 or source_rows[-1] is not inserts[0]:
        raise Unsupported("Only one added wishlist entry and the entries it moved can be undone here.")
    return inserts[0], source_rows[:-1]


def _key(row, raw):
    return isinstance(row.get("key"), dict) and set(row["key"]) == set(KEY) and type(row["key"].get("position")) is int \
        and row["key"] == {"profile_id": raw["profile_id"], "position": raw["position"]}


def review(change_id, pid, source_rows, raw_entries, latest_owner, total=None):
    """The plan to delete the added entry and move the entries it moved back, or a refusal."""
    if not undo._id(change_id) or not isinstance(pid, str) or not rules.PROFILE_ID.fullmatch(pid):
        raise undo.UndoMissing()
    inserted, moved = source_record(source_rows, pid, total)
    ids = [row.get("id") for row in source_rows]
    if not all(undo._id(value) for value in ids) or ids != sorted(set(ids)):
        raise Unsupported("The original wishlist audit identity cannot be checked.")
    new = inserted["after"]
    current = undo._entry(new, pid)
    if not _key(inserted, new):
        raise Unsupported("The recorded wishlist row cannot be restored exactly.")
    moves = sorted(moved, key=lambda row: row["before"].get("position") if isinstance(row["before"].get("position"), int) else -1)
    for index, row in enumerate(moves):
        old, after = row["before"], row["after"]
        undo._entry(old, pid), undo._entry(after, pid)
        if not _key(row, after) or any(old[field] != after[field] for field in undo.RAW_FIELDS - {"position"}) \
                or old["position"] != new["position"] + index or after["position"] != old["position"] + 1:
            raise Unsupported("Only entries moved one place along to make room for the addition can be put back here.")
    if latest_owner != ids[-1] or not undo._id(latest_owner):
        raise undo.UndoConflict()
    undo._layout(raw_entries, pid)
    by_position = {row["position"]: row for row in raw_entries}
    if by_position.get(new["position"]) != new or any(by_position.get(row["after"]["position"]) != row["after"] for row in moves):
        raise undo.UndoConflict()
    restored = {row["after"]["position"]: row["before"] for row in moves}
    expected = [copy.deepcopy(restored.get(row["position"], row)) for row in raw_entries if row["position"] != new["position"]]
    expected.sort(key=lambda row: row["position"])
    try:
        undo._layout(expected, pid)
    except Invalid:
        raise undo.UndoConflict() from None
    if [row["name"] for row in expected] != [row["name"] for row in raw_entries if row["position"] != new["position"]]:
        raise undo.UndoConflict()
    expect = undo.list_sha(["moved", change_id, source_rows, total, raw_entries, latest_owner])
    return {"change_id": change_id, "profile": pid, "kind": "wishlist", "action": "wishlist_remove", "label": new["name"],
            "current": current, "restored": None, "moved": len(moves), "expect": expect, "row_change_id": ids[-1],
            "latest_owner": latest_owner, "raw_current": copy.deepcopy(new), "raw_restore": None,
            "raw_moves": [[copy.deepcopy(row["after"]), copy.deepcopy(row["before"])] for row in moves],
            "raw_after": expected, "sha256": undo.list_sha(expected)}


def receipt(plan, actual_raw_entries, actual_new_source_rows, latest_owner):
    """The saved receipt once exactly the planned DELETE and moves back were written, or UndoConflict."""
    pid = plan["profile"]
    undo._layout(actual_raw_entries, pid)
    moves = plan["raw_moves"]
    rows = actual_new_source_rows
    if actual_raw_entries != plan["raw_after"] or not isinstance(rows, list) or len(rows) != 1 + len(moves):
        raise undo.UndoConflict()
    expected = [("DELETE", plan["raw_current"], None, plan["raw_current"])] + [("UPDATE", after, before, before) for after, before in moves]
    previous = plan["latest_owner"]
    for row, (op, before, after, keyed) in zip(rows, expected):
        if not isinstance(row, dict) or row.get("table") != "wishlist_entry" or row.get("op") != op \
                or row.get("before") != before or row.get("after") != after or not _key(row, keyed) \
                or not undo._id(row.get("id")) or row["id"] <= previous:
            raise undo.UndoConflict()
        previous = row["id"]
    if not undo._id(latest_owner) or latest_owner != previous:
        raise undo.UndoConflict()
    return {"restored": None, "removed_name": plan["raw_current"]["name"], "sha256": undo.list_sha(actual_raw_entries),
            "revision": str(latest_owner)}
