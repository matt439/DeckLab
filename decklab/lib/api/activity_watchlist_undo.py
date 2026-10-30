"""Activity's Undo of 1-50 purchase-queue rows' updated values, or of rows added or removed (E11-S08).

The queue is home's record: reviewing and saving it is for those who may change the orders and
see home's records (orders.edit and sees_home_records, as Shopping's queue edits are). A member
is answered as for a missing change, before any permission. The inventory backend reads the
complete original change and checks it again under its write lock (inventory/undo_watchlist.py,
undo_watchlist_rows.py); Activity's rows are only a hint. The plan's proof is never sent.
"""
from decklab.lib import inventory, spaces
from decklab.lib.inventory import files
from decklab.lib.inventory.model import QUEUE_FIELDS

from . import guard, saving
from .common import ApiError

ACTION = "watchlist_update"
REMOVE = "watchlist_remove"     # rows the change added, removed again with one reason
ADD = "watchlist_add"           # rows the change removed, restored as new rows
MIXED = "watchlist_mixed"       # a change that did more than one of those (activity_watchlist_mixed_undo)
MAX_ROWS = 50
UNCONFIRMED = "The undo result could not be confirmed. Reload Activity before trying again."


def _row_shape(row):
    """Whether one Activity row looks like a value-only queue UPDATE (never authority)."""
    before, after = (row.get("before"), row.get("after")) if isinstance(row, dict) else (None, None)
    return isinstance(before, dict) and isinstance(after, dict) and row.get("table") == "watchlist_item" \
        and row.get("op") == "UPDATE" and type(after.get("id")) is int and row.get("key") == {"id": after["id"]} \
        and before.get("id") == after["id"] and "position" in before and before.get("position") == after.get("position")


def _added_or_removed(row, op):
    """Whether one Activity row looks like a whole queue INSERT or DELETE (never authority)."""
    image, empty = ("after", "before") if op == "INSERT" else ("before", "after")
    found = row.get(image) if isinstance(row, dict) else None
    return isinstance(found, dict) and row.get("table") == "watchlist_item" and row.get("op") == op \
        and row.get(empty) is None and type(found.get("id")) is int and row.get("key") == {"id": found["id"]} \
        and type(found.get("position")) is int


def hint(change, shown, profile):
    """{"review": True} for what looks like 1-50 purchase-queue value updates, rows added or
    removed, or a mix of those, shown whole to someone who may change the orders; None otherwise. The review reads
    the complete change."""
    rows = change.get("rows") or ()
    total = change.get("total", len(rows))
    if type(total) is not int or not 1 <= total <= MAX_ROWS or len(rows) != total or change.get("more") \
            or change.get("groups") or not profile or shown.get("id") != change.get("id"):
        return None
    # Updates, additions and removals alone, or a change mixing them (activity_watchlist_mixed_undo).
    if not all(_row_shape(row) or _added_or_removed(row, "INSERT") or _added_or_removed(row, "DELETE") for row in rows):
        return None
    if guard.allowed(profile, "orders.edit") and guard.sees_home_records(profile):
        return {"review": True}
    return None


def check(plan, change_id, space, profile):
    """_review's part for a queue plan: home only, then the orders' permission (403 after review)."""
    if space != spaces.HOME or plan.get("space") != spaces.HOME or plan.get("change_id") != change_id:
        raise ApiError(503, UNCONFIRMED)
    guard.require(profile, "orders.edit")
    guard.require_sees_home_records(profile)
    return plan


def _queue_row(raw):
    if not isinstance(raw, dict) or set(raw) != set(QUEUE_FIELDS) or any(not isinstance(raw[key], str) for key in raw) \
            or not raw["quantity"].isascii() or not raw["quantity"].isdigit() or int(raw["quantity"]) < 1:
        raise ApiError(503, UNCONFIRMED)
    return dict(raw)


def _project_rows(plan, count, rows):
    """The packet of an added-rows removal (each row's current values and stable id) or a
    removed-rows restore (each row's recorded values), or 503."""
    removing = plan["action"] == REMOVE
    words = "added purchase-queue row" if removing else "removed purchase-queue row"
    if plan.get("label") != f"{count} {words}{'s' if count > 1 else ''}" \
            or (plan.get("reason_required") is not True if removing else "reason_required" in plan):
        raise ApiError(503, UNCONFIRMED)
    shown, ids, keys = [], set(), set()
    for item in rows:
        if not isinstance(item, dict) or not isinstance(item.get("label"), str) or not item["label"].strip():
            raise ApiError(503, UNCONFIRMED)
        if removing:
            rid = item.get("watch_row_id")
            if type(rid) is not int or not 1 <= rid < 10 ** 18 or rid in ids:
                raise ApiError(503, UNCONFIRMED)
            ids.add(rid)
            shown.append({"label": item["label"], "watch_row_id": rid, "current": _queue_row(item.get("current"))})
        else:
            restored = _queue_row(item.get("restore"))
            key = tuple(restored[field] for field in ("name", "printing", "set", "collector_number", "finish", "for"))
            if key in keys:
                raise ApiError(503, UNCONFIRMED)
            keys.add(key)
            shown.append({"label": item["label"], "restored": restored})
    return {"available": True, "id": plan["change_id"], "expect": plan["expect"], "kind": "watchlist", "space": spaces.HOME,
            "label": plan["label"], "action": plan["action"], "row_count": count, "rows": shown,
            **({"reason_required": True} if removing else {})}


def project(plan):
    """The public packet of a queue plan, or 503: the rows' current and restored fields, their stable
    ids and exactly the fields that differ (for rows added or removed, their whole values)."""
    count, rows = plan.get("row_count"), plan.get("rows")
    if plan.get("action") == MIXED:
        from . import activity_watchlist_mixed_undo
        return activity_watchlist_mixed_undo.project(plan)
    if plan.get("kind") == "watchlist" and plan.get("space") == spaces.HOME and plan.get("action") in (REMOVE, ADD) \
            and type(count) is int and 1 <= count <= MAX_ROWS and isinstance(rows, list) and len(rows) == count \
            and isinstance(plan.get("expect"), str) and len(plan["expect"]) == 64:
        return _project_rows(plan, count, rows)
    if plan.get("kind") != "watchlist" or plan.get("space") != spaces.HOME or plan.get("action") != ACTION \
            or type(count) is not int or not 1 <= count <= MAX_ROWS or not isinstance(rows, list) or len(rows) != count \
            or not isinstance(plan.get("expect"), str) or len(plan["expect"]) != 64 \
            or plan.get("label") != f"Updates to {count} purchase-queue row{'s' if count > 1 else ''}":
        raise ApiError(503, UNCONFIRMED)
    shown, ids = [], set()
    for item in rows:
        rid = item.get("watch_row_id") if isinstance(item, dict) else None
        if type(rid) is not int or not 1 <= rid < 10 ** 18 or rid in ids \
                or not isinstance(item.get("label"), str) or not item["label"].strip():
            raise ApiError(503, UNCONFIRMED)
        ids.add(rid)
        current, restored = _queue_row(item.get("current")), _queue_row(item.get("restore"))
        changed = [field for field in QUEUE_FIELDS if current[field] != restored[field]]
        fields = [{"field": field, "before": current[field], "after": restored[field]} for field in changed]
        if not changed or item.get("fields") != fields:
            raise ApiError(503, UNCONFIRMED)
        shown.append({"label": item["label"], "watch_row_id": rid, "current": current, "restored": restored, "fields": fields})
    return {"available": True, "id": plan["change_id"], "expect": plan["expect"], "kind": "watchlist", "space": spaces.HOME,
            "label": plan["label"], "action": ACTION, "row_count": count, "rows": shown}


def apply(data, plan, profile, change_id, refused, changed):
    """POST's part for a queue plan, after its review and projection: a reason only when removing
    added rows, never a confirmation, the full receipt, one audited inventory Undo, then the saved
    receipt checked."""
    if plan["action"] == MIXED:
        from . import activity_watchlist_mixed_undo
        return activity_watchlist_mixed_undo.apply(data, plan, profile, change_id, refused, changed)
    removing = plan["action"] == REMOVE
    reason = None
    if removing:
        if "confirm_owned" in data:
            raise ApiError(400, "Removing added purchase-queue rows takes no physical confirmation.")
        from decklab.lib.inventory import undo
        try:
            reason = undo.removal_reason(data.get("reason"))
        except inventory.Invalid as error:
            raise ApiError(400, str(error)) from None
    elif "reason" in data or "confirm_owned" in data:
        raise ApiError(400, "Restoring purchase-queue rows takes no reason or physical confirmation.")
    expect = data["expect"]
    if not isinstance(expect, str) or len(expect) != 64 or any(c not in "0123456789abcdef" for c in expect):
        raise ApiError(400, "expect must be the full review receipt from Undo")
    if expect != plan["expect"]:
        raise changed(plan["label"])
    op = inventory.Op("inventory.undo", {"change_id": change_id, "space": spaces.HOME, "expect": expect,
                                         **({"reason": reason} if removing else {})})
    after, summary = saving.apply_op(op, profile, f"Undo activity change {change_id}", refused,
                                     **({"reason": reason} if removing else {}))
    if removing:
        return removed(after, plan, expect, summary, reason)
    if plan["action"] == ADD:
        return added(after, plan, expect, summary)
    return restored(after, plan, expect, summary)


def _saved(summary, plan, counts_key):
    """Whether summary is this plan's proved Undo, its proof replaced by the ids."""
    extra, counts, count = summary.extra or {}, summary.counts or {}, plan["row_count"]
    return bool(summary.changed) and counts == {counts_key: count, "undo": 1} and extra.get("undo_of") == plan["change_id"] \
        and extra.get("kind") == "watchlist" and extra.get("space") == spaces.HOME and extra.get("action") == plan["action"] \
        and extra.get("row_count") == count and "watch_rows" not in extra \
        and extra.get("row_change_ids") == [item["row_change_id"] for item in plan["rows"]]


def removed(after, plan, expect, summary, reason):
    """The saved receipt of added rows removed: the backend's proof named every reviewed id, none is
    left and every other row is exactly as reviewed; else 503."""
    ids, extra = [item["watch_row_id"] for item in plan["rows"]], summary.extra or {}
    if not _saved(summary, plan, "removed_rows") or extra.get("undo_reason") != reason \
            or extra.get("removed_watch_row_ids") != ids \
            or [{"id": row.id, "row": row.as_dict()} for row in after.watchlist.rows] \
            != [row for row in plan["proof"]["stock"] if row["id"] not in set(ids)]:
        raise ApiError(503, UNCONFIRMED)
    return {"saved": True, "source_id": plan["change_id"], "expect": expect, "kind": "watchlist", "space": spaces.HOME,
            "action": REMOVE, "row_count": plan["row_count"], "removed_watch_row_ids": ids,
            "sha256": files.rendered_sha256(after.watchlist), "revision": after.revision, "summary": summary.text}


def added(after, plan, expect, summary):
    """The saved receipt of removed rows restored: the backend's proof named a fresh id for each,
    and each row there now holds exactly its recorded values; else 503."""
    ids, proof = (summary.extra or {}).get("restored_watch_row_ids"), plan["proof"]
    known = {row["id"] for row in proof["stock"]} | set(proof["deleted_ids"])
    if not _saved(summary, plan, "added_rows") or not isinstance(ids, list) or len(ids) != plan["row_count"] \
            or len(set(ids)) != len(ids) or any(type(rid) is not int or not 1 <= rid < 10 ** 18 or rid in known for rid in ids):
        raise ApiError(503, UNCONFIRMED)
    out = []
    for rid, item in zip(ids, plan["rows"]):
        found = [row.as_dict() for row in after.watchlist.rows if row.id == rid]
        if len(found) != 1 or found[0] != item["restore"]:
            raise ApiError(503, UNCONFIRMED)
        out.append({"watch_row_id": rid, "row": dict(item["restore"])})
    return {"saved": True, "source_id": plan["change_id"], "expect": expect, "kind": "watchlist", "space": spaces.HOME,
            "action": ADD, "row_count": plan["row_count"], "restored_rows": out,
            "sha256": files.rendered_sha256(after.watchlist), "revision": after.revision, "summary": summary.text}


def restored(after, plan, expect, summary):
    """The saved receipt: the backend's proof named every restored id, and each row there now holds
    exactly its reviewed values; else 503."""
    extra, counts, count = summary.extra or {}, summary.counts or {}, plan["row_count"]
    ids = [item["watch_row_id"] for item in plan["rows"]]
    if not summary.changed or counts != {"edited": count, "undo": 1} or extra.get("undo_of") != plan["change_id"] \
            or extra.get("kind") != "watchlist" or extra.get("space") != spaces.HOME or extra.get("action") != ACTION \
            or extra.get("row_count") != count or "watch_restore" in extra \
            or extra.get("row_change_ids") != [item["row_change_id"] for item in plan["rows"]] \
            or extra.get("restored_watch_row_ids") != ids:
        raise ApiError(503, UNCONFIRMED)
    out = []
    for item in plan["rows"]:
        found = [row.as_dict() for row in after.watchlist.rows if row.id == item["watch_row_id"]]
        if len(found) != 1 or found[0] != item["restore"]:
            raise ApiError(503, UNCONFIRMED)
        out.append({"watch_row_id": item["watch_row_id"], "row": dict(item["restore"])})
    return {"saved": True, "source_id": plan["change_id"], "expect": expect, "kind": "watchlist", "space": spaces.HOME,
            "action": ACTION, "row_count": count, "restored_rows": out,
            "sha256": files.rendered_sha256(after.watchlist), "revision": after.revision, "summary": summary.text}
