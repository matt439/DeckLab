"""Activity's Undo of 1-50 token-card rows' edited values, restored in place (E11-S08).

For the space's own token editors only (tokens.edit in that space, as the Tokens page's edits):
another space's change answers as a missing one before anything is read, an admin's included.
The inventory backend reads the complete original change and checks it again under its write
lock (inventory/undo_token_edit.py); Activity's rows are only a hint. The plan's proof is never sent.
"""
from decklab.lib.inventory import files, rules

from . import guard
from .common import ApiError

ACTION = "token_batch_update"
MAX_ROWS = 50
UNCONFIRMED = "The undo result could not be confirmed. Reload Activity before trying again."


def _row_shape(row, space):
    """Whether one Activity row looks like an own-space token UPDATE keeping its id and position
    (never authority)."""
    before, after = (row.get("before"), row.get("after")) if isinstance(row, dict) else (None, None)
    return isinstance(before, dict) and isinstance(after, dict) and row.get("table") == "token_card" \
        and row.get("op") == "UPDATE" and type(after.get("id")) is int and row.get("key") == {"id": after["id"]} \
        and before.get("id") == after["id"] and type(after.get("position")) is int \
        and before.get("position") == after["position"] \
        and before.get("space_id") == space and after.get("space_id") == space


def hint(change, shown, profile, space):
    """{"review": True} for what looks like 2-50 own-space token-card value updates shown whole to
    someone who may edit that space's tokens; None otherwise (one row keeps the single-row hint).
    The review reads the complete change, and a larger one says why it can't."""
    rows = change.get("rows") or ()
    total = change.get("total", len(rows))
    if type(total) is not int or total < 2 or not rows or change.get("groups") \
            or len(rows) + (change.get("more") or 0) != total or shown.get("id") != change.get("id"):
        return None
    if not all(_row_shape(row, space) for row in rows):
        return None
    return {"review": True} if guard.allowed(profile, "tokens.edit", space) else None


def _token_row(raw):
    """A current or recorded token row as the review sends it, or 503."""
    if not isinstance(raw, dict) or set(raw) != set(rules.TOKEN_FIELDS) or type(raw.get("quantity")) is not int \
            or not 1 <= raw["quantity"] <= 9999 or any(not isinstance(raw[key], str) for key in raw if key != "quantity") \
            or not raw["front"].strip():
        raise ApiError(503, UNCONFIRMED)
    return dict(raw)


def project(plan):
    """The public packet: each row's current and restored values, its stable id and exactly the
    fields that differ; or 503."""
    count, rows = plan.get("row_count"), plan.get("rows")
    if plan.get("kind") != "tokens" or plan.get("action") != ACTION or type(count) is not int \
            or not 1 <= count <= MAX_ROWS or not isinstance(rows, list) or len(rows) != count \
            or not isinstance(plan.get("expect"), str) or len(plan["expect"]) != 64 \
            or plan.get("label") != f"Updates to {count} token-card row{'s' if count > 1 else ''}":
        raise ApiError(503, UNCONFIRMED)
    shown, ids = [], set()
    for item in rows:
        rid = item.get("token_row_id") if isinstance(item, dict) else None
        if type(rid) is not int or not 1 <= rid < 10 ** 18 or rid in ids:
            raise ApiError(503, UNCONFIRMED)
        ids.add(rid)
        current, restored = _token_row(item.get("current")), _token_row(item.get("restore"))
        changed = [field for field in rules.TOKEN_FIELDS if current[field] != restored[field]]
        fields = [{"field": field, "before": current[field], "after": restored[field]} for field in changed]
        if not changed or item.get("fields") != fields or item.get("label") != rules.token_label(current):
            raise ApiError(503, UNCONFIRMED)
        shown.append({"label": item["label"], "token_row_id": rid, "current": current, "restored": restored, "fields": fields})
    return {"available": True, "id": plan["change_id"], "expect": plan["expect"], "kind": "tokens", "space": plan["space"],
            "label": plan["label"], "action": ACTION, "row_count": count, "rows": shown}


def saved(after, plan, expect, summary):
    """The saved receipt: the backend's transaction-local proof named every restored id, and each
    row there now holds exactly its reviewed values; else 503."""
    extra, counts, count, space = summary.extra or {}, summary.counts or {}, plan["row_count"], plan["space"]
    ids = [item["token_row_id"] for item in plan["rows"]]
    sheet = after.token_set(space)
    if not summary.changed or set(counts) != {"edited", "cards", "undo"} or counts["edited"] != count or counts["undo"] != 1 \
            or type(counts["cards"]) is not int or counts["cards"] != sum(row.qty or 0 for row in sheet.rows) \
            or extra.get("undo_of") != plan["change_id"] or extra.get("kind") != "tokens" or extra.get("space") != space \
            or extra.get("action") != ACTION or extra.get("row_count") != count or "token_edit" in extra \
            or extra.get("row_change_ids") != [item["row_change_id"] for item in plan["rows"]] \
            or extra.get("restored_token_row_ids") != ids:
        raise ApiError(503, UNCONFIRMED)
    out = []
    for item in plan["rows"]:
        found = [row.as_dict() for row in sheet.rows if row.id == item["token_row_id"]]
        if len(found) != 1 or {**found[0], "quantity": int(found[0]["quantity"])} != item["restore"]:
            raise ApiError(503, UNCONFIRMED)
        out.append({"token_row_id": item["token_row_id"], "row": dict(item["restore"])})
    return {"saved": True, "source_id": plan["change_id"], "expect": expect, "kind": "tokens", "space": space,
            "action": ACTION, "row_count": count, "restored_rows": out,
            "sha256": files.rendered_sha256(sheet), "revision": after.revision, "summary": summary.text}
