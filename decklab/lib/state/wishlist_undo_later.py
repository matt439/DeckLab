"""Undo of a wishlist removal after later changes to the same list (E11-S08).

A removal is one DELETE that leaves its position free (rules.insert_slot). Once other entries
have been added, removed or edited since, the plain presence Undo refuses, since the removal is
no longer the latest change of the owner's wishlist. This puts the entry back at exactly its old
stored position, as one new audited change through the ordinary insertion, when nothing since
has touched that position or the card's name and the ordinary rules still give that very slot
without moving any other entry.

Every later audit row of the owner's wishlist is read in full (at most MAX_LATER) and bound in
the review's expect hash with the source, the whole list and the latest audit ids, so any change
between review and save is a conflict. Only the owner reviews or saves it; refusals are fixed
sentences with counts at most, never a note. Pure: adapters supply the evidence under their
wishlist lock.
"""
from . import Invalid, rules, wishlist_undo as undo, wishlist_undo_moved as moved

MAX_LATER = 200
SIDES = ("key", "before", "after")
AGAIN = "That card was added, removed or moved on your wishlist again since."


class Unsupported(moved.Unsupported):
    """A fixed sentence saying why, passed on by the API (counts at most, never a note)."""


def _later(row, pid):
    """Whether one later audit row is wholly pid's wishlist, in a shape the fences can read."""
    if not isinstance(row, dict) or row.get("table") != "wishlist_entry" or row.get("op") not in ("UPDATE", "INSERT", "DELETE") \
            or not undo._id(row.get("id")) or not undo._id(row.get("change")):
        return False
    op, old, new = row["op"], row.get("before"), row.get("after")
    if (old is None) != (op == "INSERT") or (new is None) != (op == "DELETE"):
        return False
    sides = [row.get("key")] + [side for side in (old, new) if side is not None]
    return all(isinstance(side, dict) and side.get("profile_id") == pid and type(side.get("position")) is int for side in sides) \
        and all(isinstance(side.get("name"), str) for side in (old, new) if side is not None)


def review(change_id, pid, source_rows, later_rows, raw_entries, latest_target, latest_owner):
    """The plan to put a removed entry back at its old position after later list changes, or a
    refusal. latest_target is the latest audit row touching the old position, latest_owner the
    latest of the owner's whole wishlist."""
    if not undo._id(change_id) or not isinstance(pid, str) or not rules.PROFILE_ID.fullmatch(pid):
        raise undo.UndoMissing()
    row = undo.source_record(source_rows, pid)      # privacy before any value
    if row["op"] != "DELETE" or not undo._id(row.get("id")):
        raise undo.UndoMissing()
    old = row["before"]
    restored = undo._entry(old, pid)
    if row.get("key") != {"profile_id": pid, "position": old["position"]}:
        raise undo.UndoUnsupported("Only the printing preference, notes and source on the same wishlist entry can be undone here.")
    if latest_target != row["id"] or not undo._id(latest_owner) or latest_owner <= row["id"]:
        raise undo.UndoConflict()
    if not isinstance(later_rows, list) or not later_rows or not all(_later(item, pid) for item in later_rows):
        raise Unsupported("The later wishlist changes cannot be checked.")
    if len(later_rows) > MAX_LATER:
        raise Unsupported(f"Undo can only check up to {MAX_LATER} later changes to your wishlist.")
    ids = [item["id"] for item in later_rows]
    if ids != sorted(set(ids)) or ids[0] <= row["id"] or ids[-1] != latest_owner:
        raise Unsupported("The later wishlist changes cannot be checked.")
    name = restored["name"].casefold()
    for item in later_rows:
        sides = [item[side] for side in SIDES if item.get(side) is not None]
        if any(side["position"] == old["position"] for side in sides) \
                or any(side["name"].casefold() == name for side in sides[1:]):
            raise Unsupported(AGAIN)
    undo._layout(raw_entries, pid)
    current = [undo._entry(item, pid) for item in raw_entries]
    if any(item["position"] == old["position"] for item in raw_entries):
        raise undo.UndoConflict()
    try:
        kind = rules.add_plan(current, restored)
    except Invalid:
        raise Unsupported(f"Your wishlist is full ({rules.MAX_ENTRIES} entries).") from None
    if kind != "add":
        raise Unsupported(AGAIN)
    positions = [item["position"] for item in raw_entries]
    index = sum(position < old["position"] for position in positions)
    if rules.insert_slot(positions, index) != (old["position"], []):
        raise Unsupported("Its old place in the list can no longer be reproduced without moving other entries.")
    # Every fence above holds, so the plain presence review builds the exact same plan as if the
    # removal were still the latest change; the real latest id and the later evidence replace its own.
    plan = undo.review(change_id, pid, source_rows, raw_entries, latest_target, row["id"])
    plan.update(latest_owner=latest_owner, later=len({item["change"] for item in later_rows}),
                expect=undo.list_sha(["later", change_id, source_rows, later_rows, raw_entries, latest_target, latest_owner]))
    return plan
