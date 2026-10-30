"""Activity's Undo of 1-50 purchase-queue rows' updated values (E11-S08).

The queue is home's record: reviewing and saving it is for those who may change the orders and
see home's records (orders.edit and sees_home_records, as Shopping's queue edits are). A member
is answered as for a missing change, before any permission. The inventory backend reads the
complete original change and checks it again under its write lock (inventory/undo_watchlist.py);
Activity's rows are only a hint. The plan's proof is never sent.
"""
from decklab.lib import inventory, spaces
from decklab.lib.inventory import files
from decklab.lib.inventory.model import QUEUE_FIELDS

from . import guard, saving
from .common import ApiError

ACTION = "watchlist_update"
MAX_ROWS = 50
UNCONFIRMED = "The undo result could not be confirmed. Reload Activity before trying again."


def _row_shape(row):
    """Whether one Activity row looks like a value-only queue UPDATE (never authority)."""
    before, after = (row.get("before"), row.get("after")) if isinstance(row, dict) else (None, None)
    return isinstance(before, dict) and isinstance(after, dict) and row.get("table") == "watchlist_item" \
        and row.get("op") == "UPDATE" and type(after.get("id")) is int and row.get("key") == {"id": after["id"]} \
        and before.get("id") == after["id"] and "position" in before and before.get("position") == after.get("position")


def hint(change, shown, profile):
    """{"review": True} for what looks like 1-50 purchase-queue value updates shown whole to someone
    who may change the orders; None otherwise. The review reads the complete change."""
    rows = change.get("rows") or ()
    total = change.get("total", len(rows))
    if type(total) is not int or not 1 <= total <= MAX_ROWS or len(rows) != total or change.get("more") \
            or change.get("groups") or not profile or shown.get("id") != change.get("id"):
        return None
    if not all(_row_shape(row) for row in rows):
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


def project(plan):
    """The public packet of a queue plan, or 503: the rows' current and restored fields, their stable
    ids and exactly the fields that differ."""
    count, rows = plan.get("row_count"), plan.get("rows")
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
    """POST's part for a queue plan, after its review and projection: no reason or confirmation,
    the full receipt, one audited inventory Undo, then the saved receipt checked."""
    if "reason" in data or "confirm_owned" in data:
        raise ApiError(400, "Restoring purchase-queue rows takes no reason or physical confirmation.")
    expect = data["expect"]
    if not isinstance(expect, str) or len(expect) != 64 or any(c not in "0123456789abcdef" for c in expect):
        raise ApiError(400, "expect must be the full review receipt from Undo")
    if expect != plan["expect"]:
        raise changed(plan["label"])
    op = inventory.Op("inventory.undo", {"change_id": change_id, "space": spaces.HOME, "expect": expect})
    after, summary = saving.apply_op(op, profile, f"Undo activity change {change_id}", refused)
    return restored(after, plan, expect, summary)


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
