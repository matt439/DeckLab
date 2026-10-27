"""Review and save Undo of a whole collection import or order receipt from Activity (E11-S08).

GET /api/activity/mixed-undo?id=N previews it; POST {profile, id, expect, reason} saves it as
one new audited change. The inventory backend reads the complete original change and checks it
again under its write lock (inventory/undo_mixed.py); Activity's capped rows never authorize a
write. An import is its space's own people's to undo (collection.edit), a receipt home's
admins' (receipts.apply, as receiving it was).
"""
import re

from decklab.lib import inventory
from decklab.lib.inventory import rules

from . import guard, saving
from .activity_undo import NO_CHANGE, UNCONFIRMED, _changed, _id, _space
from .common import ApiError, DATABASE_DOWN, _keys, _parse_body
from .settings import _writer

UNSUPPORTED = ("This change cannot be undone here. Whole-change Undo covers a collection import and a receipt "
               "of whole order parts, while nothing they touched has changed since.")
SHA = re.compile(r"[a-f0-9]{64}")
ACTIONS = ("import_undo", "receipt_undo")
COMPONENT_FIELDS = ("order", "component", "kind", "received_on", "checks")
PRODUCT_FIELDS = ("product", "status", "intact")


def hint(change, shown, profile):
    """A Review undo affordance for what looks like a whole import or receipt, never authority.

    The rows may be capped or partly hidden; the review reads the complete change."""
    from decklab.lib.inventory import undo_mixed
    rows = change.get("rows") or ()
    total = change.get("total", len(rows))
    if not profile or shown.get("id") != change.get("id") or change.get("groups") \
            or type(total) is not int or not 2 <= total <= undo_mixed.MIXED_MAX:
        return None
    if any(not isinstance(row, dict) for row in rows):
        return None
    space = _space(profile)
    shape = undo_mixed.looks_like(rows, change.get("past"), space)
    if shape == undo_mixed.IMPORT and guard.allowed(profile, "collection.edit", space):
        return {"review": True, "kind": "mixed"}
    if shape == undo_mixed.RECEIPT and guard.allowed(profile, "receipts.apply") and guard.sees_home_records(profile):
        return {"review": True, "kind": "mixed"}
    return None


def _refused(error):
    from decklab.lib.inventory import undo
    if isinstance(error, undo.UndoMissing):
        return ApiError(404, NO_CHANGE)
    if isinstance(error, inventory.Unavailable):
        return ApiError(503, DATABASE_DOWN, reason="database")
    if isinstance(error, undo.UndoConflict):
        return _changed(error.label) if error.label else ApiError(409, str(error))
    if isinstance(error, inventory.Conflict):
        return _changed()
    if isinstance(error, undo.UndoUnsupported):
        return ApiError(400, UNSUPPORTED, detail=str(error))
    if isinstance(error, inventory.Invalid):
        return ApiError(400, str(error))
    return None


def _review(change_id, profile):
    space = _space(profile)
    if profile:
        guard.require_space_write(profile, "collection.edit", space)
    try:
        plan = inventory.undo_mixed_review(change_id, space)
    except (inventory.Invalid, inventory.Conflict, inventory.Unavailable) as error:
        raise _refused(error) from None
    # The complete source's space was checked before any shape, row or receipt.
    if plan.get("kind") != "mixed" or plan.get("space") != space or plan.get("change_id") != change_id \
            or plan.get("action") not in ACTIONS:
        raise ApiError(503, UNCONFIRMED)
    if plan["action"] == "receipt_undo":
        guard.require(profile, "receipts.apply")
        guard.require_sees_home_records(profile)
    return plan


def _card(row, fields):
    if not isinstance(row, dict) or set(row) != set(fields):
        raise ApiError(503, UNCONFIRMED)
    for field in fields:
        value = row[field]
        if field == "quantity":
            if type(value) is not int or not 1 <= value <= 9999:
                raise ApiError(503, UNCONFIRMED)
        elif not isinstance(value, str):
            raise ApiError(503, UNCONFIRMED)
    return dict(row)


def _rows(part, fields):
    if not isinstance(part, dict) or set(part) != {"removed", "reduced"}:
        raise ApiError(503, UNCONFIRMED)
    removed = [_card(row, fields) for row in part["removed"]]
    reduced = []
    for item in part["reduced"]:
        if not isinstance(item, dict) or set(item) != {"current", "restored"}:
            raise ApiError(503, UNCONFIRMED)
        current, restored = _card(item["current"], fields), _card(item["restored"], fields)
        if restored["quantity"] >= current["quantity"]:
            raise ApiError(503, UNCONFIRMED)
        reduced.append({"current": current, "restored": restored})
    return {"removed": removed, "reduced": reduced}


def _project(plan):
    if not isinstance(plan.get("label"), str) or not plan["label"].strip() or not isinstance(plan.get("expect"), str) \
            or not SHA.fullmatch(plan["expect"]) or plan.get("reason_required") is not True \
            or type(plan.get("cards")) is not int or plan["cards"] < 0:
        raise ApiError(503, UNCONFIRMED)
    components, products = [], []
    for item in plan.get("components") or ():
        if not isinstance(item, dict) or set(item) != set(COMPONENT_FIELDS):
            raise ApiError(503, UNCONFIRMED)
        components.append({field: item[field] for field in COMPONENT_FIELDS})
    for item in plan.get("products") or ():
        if not isinstance(item, dict) or set(item) != set(PRODUCT_FIELDS):
            raise ApiError(503, UNCONFIRMED)
        products.append({field: item[field] for field in PRODUCT_FIELDS})
    uploads = plan.get("uploads") or []
    if not all(isinstance(name, str) for name in uploads) or (plan["action"] == "import_undo") != bool(uploads) \
            or (plan["action"] == "receipt_undo") != bool(components):
        raise ApiError(503, UNCONFIRMED)
    return {"available": True, "id": plan["change_id"], "expect": plan["expect"], "kind": "mixed", "space": plan["space"],
            "action": plan["action"], "label": plan["label"], "reason_required": True, "cards": plan["cards"],
            "collection": _rows(plan["collection"], rules.FIELDS), "tokens": _rows(plan["tokens"], rules.TOKEN_FIELDS),
            "components": components, "products": products, "uploads": list(uploads)}


def mixed_undo_view(id=None):
    """GET /api/activity/mixed-undo?id=N: the whole-change review, with no write."""
    change_id, profile = _id(id), guard.viewer()
    try:
        return _project(_review(change_id, profile))
    except ApiError as error:
        if error.status == 400 and error.message == UNSUPPORTED:
            detail = getattr(error, "extra", {}).get("detail") if isinstance(getattr(error, "extra", None), dict) else None
            return {"available": False, "id": change_id, "reason": UNSUPPORTED + (" " + detail if detail else "")}
        raise


def apply_mixed_undo(body):
    """POST {profile, id, expect, reason}: one new audited change, never a history rewrite."""
    from decklab.lib.inventory import undo, undo_mixed
    data = _parse_body(body)
    _keys(data, ("profile", "id", "expect", "reason"))
    profile, change_id = _writer(data), _id(data["id"])
    plan = _review(change_id, profile)     # hidden or missing is answered before a malformed receipt
    preview = _project(plan)
    try:
        reason = undo.removal_reason(data["reason"])
    except inventory.Invalid:
        raise ApiError(400, "Give a nonblank reason of at most 200 characters for undoing this change.") from None
    if not isinstance(data["expect"], str) or not SHA.fullmatch(data["expect"]):
        raise ApiError(400, "expect must be the full review receipt from Undo")
    if data["expect"] != plan["expect"]:
        raise _changed(plan["label"])
    op = inventory.Op("inventory.undo_mixed", {"change_id": change_id, "space": plan["space"], "expect": data["expect"],
                                               "reason": reason})
    after, summary = saving.apply_op(op, profile, f"Undo activity change {change_id}", _refused, reason=reason)
    extra, counts = summary.extra or {}, summary.counts or {}
    if type(counts.get("undo")) is not int or counts["undo"] != 1 or extra.get("undo_of") != change_id \
            or extra.get("kind") != "mixed" or extra.get("space") != plan["space"] or extra.get("action") != plan["action"] \
            or extra.get("row_change_ids") != plan["row_change_ids"] or extra.get("undo_reason") != reason:
        raise ApiError(503, UNCONFIRMED)
    try:
        confirmed = undo_mixed.removed_state(after, plan)
    except Exception:
        raise ApiError(503, UNCONFIRMED) from None
    tables = extra.get("tables") or {}
    return {"saved": True, "source_id": change_id, "expect": data["expect"], "kind": "mixed", "space": plan["space"],
            "action": plan["action"], "cards": preview["cards"], **confirmed,
            "tables_refreshed": len(tables.get("written") or ()), "tables_error": bool(tables.get("error")),
            "revision": after.revision, "summary": summary.text}
