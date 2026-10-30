"""Activity's Undo of a purchase-queue change that mixed updated, added and removed rows (E11-S08).

The update and added/removed packets (activity_watchlist_undo) together, for one change: home's
order editors only, as those are, with the same checks, the complete source checked again under
the write lock (inventory/undo_watchlist_mixed.py) and the proof never sent. Save takes a reason
only when the Undo removes a row the change added, never a confirmation.
"""
from decklab.lib import inventory, spaces
from decklab.lib.inventory import files
from decklab.lib.inventory.model import QUEUE_FIELDS

from . import saving
from .activity_watchlist_undo import MAX_ROWS, MIXED, UNCONFIRMED, _queue_row
from .common import ApiError

CHANGES = ("updated", "added", "removed")
KEY = ("name", "printing", "set", "collector_number", "finish", "for")


def _counts(plan, rows):
    counts = plan.get("counts")
    if not isinstance(counts, dict) or set(counts) != set(CHANGES) or any(type(counts[c]) is not int or counts[c] < 0 for c in CHANGES) \
            or sum(counts.values()) != len(rows) or sum(1 for c in CHANGES if counts[c]) < 2:
        raise ApiError(503, UNCONFIRMED)
    if [item.get("change") if isinstance(item, dict) else None for item in rows] != [c for c in CHANGES for _ in range(counts[c])]:
        raise ApiError(503, UNCONFIRMED)
    return dict(counts)


def project(plan):
    """The public packet: each updated row's current and restored values and changed fields, each
    added row's current values (removed by stable id) and each removed row's recorded values (back
    as a new row), the counts and, when any row is removed, reason_required; else 503."""
    count, rows = plan.get("row_count"), plan.get("rows")
    if plan.get("kind") != "watchlist" or plan.get("space") != spaces.HOME or plan.get("action") != MIXED \
            or type(count) is not int or not 2 <= count <= MAX_ROWS or not isinstance(rows, list) or len(rows) != count \
            or not isinstance(plan.get("expect"), str) or len(plan["expect"]) != 64 \
            or plan.get("label") != f"Changes to {count} purchase-queue rows":
        raise ApiError(503, UNCONFIRMED)
    counts = _counts(plan, rows)
    if (plan.get("reason_required") is not True) if counts["added"] else ("reason_required" in plan):
        raise ApiError(503, UNCONFIRMED)
    shown, ids, keys = [], set(), set()
    for item in rows:
        if not isinstance(item.get("label"), str) or not item["label"].strip():
            raise ApiError(503, UNCONFIRMED)
        change = item["change"]
        if change != "removed":
            rid = item.get("watch_row_id")
            if type(rid) is not int or not 1 <= rid < 10 ** 18 or rid in ids:
                raise ApiError(503, UNCONFIRMED)
            ids.add(rid)
        if change == "updated":
            current, restored = _queue_row(item.get("current")), _queue_row(item.get("restore"))
            changed = [field for field in QUEUE_FIELDS if current[field] != restored[field]]
            fields = [{"field": field, "before": current[field], "after": restored[field]} for field in changed]
            if not changed or item.get("fields") != fields:
                raise ApiError(503, UNCONFIRMED)
            shown.append({"change": change, "label": item["label"], "watch_row_id": rid, "current": current,
                          "restored": restored, "fields": fields})
        elif change == "added":
            shown.append({"change": change, "label": item["label"], "watch_row_id": rid, "current": _queue_row(item.get("current"))})
        else:
            restored = _queue_row(item.get("restore"))
            key = tuple(restored[field] for field in KEY)
            if key in keys:
                raise ApiError(503, UNCONFIRMED)
            keys.add(key)
            shown.append({"change": change, "label": item["label"], "restored": restored})
    return {"available": True, "id": plan["change_id"], "expect": plan["expect"], "kind": "watchlist", "space": spaces.HOME,
            "label": plan["label"], "action": MIXED, "row_count": count, "counts": counts, "rows": shown,
            **({"reason_required": True} if counts["added"] else {})}


def apply(data, plan, profile, change_id, refused, changed):
    """POST's part: a reason only when a row is removed, never a confirmation, the full receipt, one
    audited inventory Undo, then the saved receipt checked."""
    removing = bool(plan["counts"]["added"])
    reason = None
    if "confirm_owned" in data:
        raise ApiError(400, "Undoing purchase-queue changes takes no physical confirmation.")
    if removing:
        from decklab.lib.inventory import undo
        try:
            reason = undo.removal_reason(data.get("reason"))
        except inventory.Invalid as error:
            raise ApiError(400, str(error)) from None
    elif "reason" in data:
        raise ApiError(400, "Undoing these purchase-queue changes removes no row, so it takes no reason.")
    expect = data["expect"]
    if not isinstance(expect, str) or len(expect) != 64 or any(c not in "0123456789abcdef" for c in expect):
        raise ApiError(400, "expect must be the full review receipt from Undo")
    if expect != plan["expect"]:
        raise changed(plan["label"])
    op = inventory.Op("inventory.undo", {"change_id": change_id, "space": spaces.HOME, "expect": expect,
                                         **({"reason": reason} if removing else {})})
    after, summary = saving.apply_op(op, profile, f"Undo activity change {change_id}", refused,
                                     **({"reason": reason} if removing else {}))
    return saved(after, plan, expect, summary, reason)


def saved(after, plan, expect, summary, reason):
    """The saved receipt: the backend's proof named every restored and removed id and a fresh id for
    each row back, and the queue now holds exactly the reviewed values there; else 503."""
    from decklab.lib.inventory.undo_watchlist_mixed import summary_counts
    extra, counts, rows, proof = summary.extra or {}, plan["counts"], plan["rows"], plan["proof"]
    updated = [item for item in rows if item["change"] == "updated"]
    removed = [item["watch_row_id"] for item in rows if item["change"] == "added"]
    back = [item for item in rows if item["change"] == "removed"]
    new = extra.get("added_watch_row_ids")
    known = {row["id"] for row in proof["stock"]} | set(proof["deleted_ids"])
    if not summary.changed or summary.counts != summary_counts(counts) or extra.get("undo_of") != plan["change_id"] \
            or extra.get("kind") != "watchlist" or extra.get("space") != spaces.HOME or extra.get("action") != MIXED \
            or extra.get("row_count") != plan["row_count"] or "watch_mixed" in extra \
            or extra.get("row_change_ids") != [item["row_change_id"] for item in rows] \
            or (extra.get("undo_reason") != reason if counts["added"] else "undo_reason" in extra) \
            or extra.get("restored_watch_row_ids") != [item["watch_row_id"] for item in updated] \
            or extra.get("removed_watch_row_ids") != removed \
            or not isinstance(new, list) or len(new) != len(back) or len(set(new)) != len(new) \
            or any(type(rid) is not int or not 1 <= rid < 10 ** 18 or rid in known for rid in new):
        raise ApiError(503, UNCONFIRMED)
    now = {}
    for row in after.watchlist.rows:
        now.setdefault(row.id, []).append(row.as_dict())
    if any(rid in now for rid in removed):
        raise ApiError(503, UNCONFIRMED)
    restored_rows, new_rows = [], []
    for item in updated:
        if now.get(item["watch_row_id"]) != [item["restore"]]:
            raise ApiError(503, UNCONFIRMED)
        restored_rows.append({"watch_row_id": item["watch_row_id"], "row": dict(item["restore"])})
    for rid, item in zip(new, back):
        if now.get(rid) != [item["restore"]]:
            raise ApiError(503, UNCONFIRMED)
        new_rows.append({"watch_row_id": rid, "row": dict(item["restore"])})
    return {"saved": True, "source_id": plan["change_id"], "expect": expect, "kind": "watchlist", "space": spaces.HOME,
            "action": MIXED, "row_count": plan["row_count"], "restored_rows": restored_rows, "removed_watch_row_ids": removed,
            "new_rows": new_rows, "sha256": files.rendered_sha256(after.watchlist), "revision": after.revision,
            "summary": summary.text}
