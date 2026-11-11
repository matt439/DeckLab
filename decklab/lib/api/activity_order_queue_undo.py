"""Home order editors review one complete order lifecycle plus its queue intent, never partial rows."""
import copy
import re

from decklab.lib import inventory
from decklab.lib.inventory import rules, undo, undo_order_queue as order_undo
from decklab.lib.inventory import undo_order_queue_verify

from . import guard, saving
from . import activity_watchlist_undo as queue_api, activity_watchlist_mixed_undo as mixed_api
from .common import ApiError

SHA = re.compile(r"[a-f0-9]{64}")
UNCONFIRMED = "The complete order and queue Undo result could not be confirmed. Reload Activity before another review."


def hint(change, shown, profile):
    rows = change.get("rows") or ()
    total = change.get("total", len(rows))
    if not profile or shown.get("id") != change.get("id") or type(total) is not int or not 2 <= total <= order_undo.MIXED_MAX \
            or not guard.allowed(profile, "orders.edit") or not guard.sees_home_records(profile):
        return None
    tables = {row.get("table") for row in rows if isinstance(row, dict)} | set(change.get("past") or ())
    if "watchlist_item" in tables and "purchase_order" in tables \
            and tables <= {*order_undo.models.TABLES, "watchlist_item", "deck"}:
        return {"review": True, "kind": order_undo.KIND}
    return None


def tables_of(summary):
    tables = (summary.extra or {}).get("tables") or {}
    sees = guard.deck_reader()
    return {"written": [{"id": row["id"], "title": row["title"]} for row in tables.get("written", [])
                         if isinstance(row, dict) and isinstance(row.get("id"), str) and isinstance(row.get("title"), str) and sees(row["id"])],
            "needs_attention": bool(tables.get("error") or tables.get("skipped"))}


def check(plan, change_id, space, profile):
    if space != "home" or plan.get("space") != "home" or plan.get("change_id") != change_id:
        raise ApiError(503, UNCONFIRMED)
    guard.require(profile, "orders.edit")
    guard.require_sees_home_records(profile)
    operation = inventory.Op("inventory.undo_order_queue", {"change_id": change_id, "space": "home", "expect": plan["expect"],
                                                            "reason": "Preview the complete order and queue inverse"})
    try:
        # The locked review's snapshot belongs to this receipt; request caches never
        # replace it with an older read. Preview still rechecks the live audit fence.
        with inventory.pinned(plan["proof"]["base_snapshot"]):
            after, summary = inventory.preview(operation)
            summary = undo_order_queue_verify.prepare(plan["proof"]["base_snapshot"], after, summary)
    except (inventory.Invalid, inventory.Conflict, inventory.Unavailable):
        raise
    return {**plan, "tables": tables_of(summary)}


def _order(raw, order_id):
    if raw is None:
        return None
    expected = {"id", "seller", "ordered_on", "sources", "notes", "audit_notes", "components"}
    if not isinstance(raw, dict) or set(raw) != expected or raw["id"] != order_id \
            or any(not isinstance(raw[field], str) for field in expected - {"components", "sources"}) \
            or not isinstance(raw["sources"], list) or not all(isinstance(value, str) for value in raw["sources"]) \
            or not isinstance(raw["components"], list) or not 1 <= len(raw["components"]) <= order_undo.MIXED_MAX:
        raise ApiError(503, UNCONFIRMED)
    ids = set()
    for part in raw["components"]:
        basic = {"id", "kind", "status", "received_on", "checks", "verified_checks", "rows"}
        product = isinstance(part, dict) and part.get("kind") == "product"
        fields = basic | ({"product", "name", "format", "product_status"} if product else set())
        if not isinstance(part, dict) or set(part) != fields or not isinstance(part["id"], str) or not part["id"] or part["id"] in ids \
                or part["kind"] not in ("cards", "tokens", "product") or part["status"] not in ("pending", "received", "cancelled") \
                or not isinstance(part["received_on"], str) or any(not isinstance(part[key], list) or not all(isinstance(value, str) for value in part[key])
                                                                 for key in ("checks", "verified_checks")) \
                or not isinstance(part["rows"], list) or not 1 <= len(part["rows"]) <= order_undo.MIXED_MAX:
            raise ApiError(503, UNCONFIRMED)
        ids.add(part["id"])
        if product and (not isinstance(part["product"], str) or part["product_status"] not in ("ordered", "preordered", "owned", "cancelled")
                        or any(value is not None and not isinstance(value, str) for value in (part["name"], part["format"]))):
            raise ApiError(503, UNCONFIRMED)
        for row in part["rows"]:
            required = set(rules.TOKEN_FIELDS if part["kind"] == "tokens" else rules.FIELDS)
            valid_fields = set(rules.REQUIRED) <= set(row) <= set(rules.FIELDS) | rules.PRODUCT_FIELDS if product and isinstance(row, dict) \
                else isinstance(row, dict) and set(row) == required
            if not valid_fields or any(not isinstance(value, str) for value in row.values()) \
                    or not row.get("quantity", "").isascii() or not row["quantity"].isdigit() or not row["quantity"].lstrip("0"):
                raise ApiError(503, UNCONFIRMED)
    return copy.deepcopy(raw)


def project(plan):
    if plan.get("kind") != order_undo.KIND or plan.get("space") != "home" or plan.get("action") != order_undo.ACTION \
            or plan.get("source_action") not in ("added", "removed", "state") or plan.get("reason_required") is not True \
            or not isinstance(plan.get("expect"), str) or not SHA.fullmatch(plan["expect"]) \
            or type(plan.get("row_count")) is not int or not 2 <= plan["row_count"] <= order_undo.MIXED_MAX:
        raise ApiError(503, UNCONFIRMED)
    current, restored = _order(plan.get("current"), plan["order_id"]), _order(plan.get("restore"), plan["order_id"])
    if (current is None) != (plan["source_action"] == "removed") or (restored is None) != (plan["source_action"] == "added"):
        raise ApiError(503, UNCONFIRMED)
    queue = queue_api.project(plan["queue"])
    if queue["row_count"] != plan["queue_count"] or queue["id"] != plan["change_id"]:
        raise ApiError(503, UNCONFIRMED)
    return {"available": True, "id": plan["change_id"], "expect": plan["expect"], "kind": order_undo.KIND, "space": "home",
            "action": order_undo.ACTION, "label": plan["label"], "source_action": plan["source_action"], "order_id": plan["order_id"],
            "row_count": plan["row_count"], "queue_count": plan["queue_count"], "current": current, "restored": restored,
            "queue": queue, "reason_required": True, "tables": plan.get("tables", {"written": [], "needs_attention": False})}


def apply(data, plan, profile, change_id, refused, changed):
    if "confirm_owned" in data:
        raise ApiError(400, "This Undo changes recorded orders and queue intent, not collection ownership.")
    try:
        reason = undo.removal_reason(data.get("reason"))
    except inventory.Invalid as error:
        raise ApiError(400, str(error)) from None
    if not isinstance(data["expect"], str) or not SHA.fullmatch(data["expect"]):
        raise ApiError(400, "expect must be the complete review receipt")
    if data["expect"] != plan["expect"]:
        raise changed(plan["label"])
    operation = inventory.Op("inventory.undo_order_queue", {"change_id": change_id, "space": "home", "expect": data["expect"], "reason": reason})
    after, summary = saving.apply_op(operation, profile, f"Undo order and queue activity change {change_id}", refused, reason=reason)
    receipt = (summary.extra or {}).get("order_queue_receipt")
    if not isinstance(receipt, dict) or receipt.get("order_id") != plan["order_id"] or receipt.get("source_action") != plan["source_action"] \
            or summary.extra.get("undo_reason") != reason or receipt.get("queue_count") != plan["queue_count"]:
        raise ApiError(503, UNCONFIRMED)
    child, child_summary = plan["queue"], receipt["queue_summary"]
    if child["action"] == queue_api.MIXED:
        queue = mixed_api.saved(after, child, child["expect"], child_summary, reason)
    elif child["action"] == queue_api.REMOVE:
        queue = queue_api.removed(after, child, child["expect"], child_summary, reason)
    elif child["action"] == queue_api.ADD:
        queue = queue_api.added(after, child, child["expect"], child_summary)
    else:
        queue = queue_api.restored(after, child, child["expect"], child_summary)
    actual = _order(order_undo._order_view(after, plan["order_id"]), plan["order_id"])
    if actual != plan["restore"]:
        raise ApiError(503, UNCONFIRMED)
    return {"saved": True, "source_id": change_id, "expect": data["expect"], "kind": order_undo.KIND, "space": "home",
            "action": order_undo.ACTION, "order_id": plan["order_id"], "order": actual, "queue": queue,
            "revision": after.revision, "summary": summary.text, "tables": tables_of(summary)}
