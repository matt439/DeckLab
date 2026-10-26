"""Review and undo one eligible collection/token update from the original audit rows.

The request supplies only a source change id and its opaque review receipt. The
inventory backend reads the complete original change and rechecks it under its
normal write lock. Activity's projected or capped rows never authorize a write.
"""
import re

from decklab.lib import inventory, permissions, spaces
from decklab.lib.inventory import files, rules

from . import activity, guard, saving
from .common import ApiError, DATABASE_DOWN, _keys, _parse_body
from .settings import _writer

NO_CHANGE = "No undoable change at that ID."
UNSUPPORTED = "This change cannot be undone here. Only a single supported collection or token edit can be undone."
CHANGED = "The change can no longer be undone safely. Reload Activity and review it again."
UNCONFIRMED = "The undo result could not be confirmed. Reload Activity before trying again."
SHA = re.compile(r"[a-f0-9]{64}")
MUTABLE = {"collection": ("quantity", "condition", "language", "notes"), "tokens": ("quantity", "notes")}
TABLE_KIND = {"collection_card": "collection", "token_card": "tokens"}


def _space(profile):
    if profile:
        return permissions._space_of(profile)
    if guard.script():
        return spaces.HOME
    raise ApiError(404, NO_CHANGE)


def _id(value):
    number = activity._number(value, "id", "a change set ID (a whole number above 0)")
    if number is None or number >= 10 ** 18:
        raise ApiError(400, "id must be a change set ID (a whole number above 0)")
    return number


def review_hint(change, shown, profile):
    """A Review undo affordance, never an eligibility claim or authority to apply.

    Check the original global row total, not how many rows Activity projected for
    this viewer. An unsupported one-row update can still explain itself on review.
    """
    rows = change.get("rows") or ()
    if change.get("total", len(rows)) != 1 or len(rows) != 1 or change.get("more") or change.get("groups"):
        return None
    row = rows[0]
    kind = TABLE_KIND.get(row.get("table"))
    before, after = row.get("before"), row.get("after")
    if not kind or row.get("op") != "UPDATE" or not isinstance(before, dict) or not isinstance(after, dict):
        return None
    space = _space(profile)
    if before.get("space_id") != space or after.get("space_id") != space \
            or not guard.allowed(profile, kind + ".edit", space) or shown.get("id") != change.get("id"):
        return None
    return {"review": True}


def _refused(error):
    from decklab.lib.inventory import undo
    if isinstance(error, undo.UndoMissing):
        return ApiError(404, NO_CHANGE)
    if isinstance(error, inventory.Unavailable):
        return ApiError(503, DATABASE_DOWN, reason="database")
    if isinstance(error, undo.UndoConflict):
        return _changed(error.label)
    if isinstance(error, inventory.Conflict):
        return ApiError(409, CHANGED)
    if isinstance(error, inventory.Invalid):
        return ApiError(400, UNSUPPORTED)
    return None


def _changed(label=None):
    if isinstance(label, str) and 0 < len(label) <= 500 and not any(ord(character) < 32 or ord(character) == 127 for character in label):
        return ApiError(409, "Cannot undo " + label + ": " + CHANGED, conflicts=[{"label": label, "reason": CHANGED}])
    return ApiError(409, CHANGED)


def _review(change_id, profile):
    space = _space(profile)
    try:
        plan = inventory.undo_review(change_id, space)
    except (inventory.Invalid, inventory.Conflict, inventory.Unavailable) as error:
        raise _refused(error) from None
    # The complete source's visibility was checked before any eligibility or receipt.
    kind = plan.get("kind")
    if kind not in MUTABLE or plan.get("space") != space or plan.get("change_id") != change_id:
        raise ApiError(503, UNCONFIRMED)
    guard.require_space_write(profile, kind + ".edit", space)
    return plan


def _project(plan):
    kind = plan["kind"]
    columns = rules.FIELDS if kind == "collection" else rules.TOKEN_FIELDS
    current, restored = plan.get("current"), plan.get("restore")
    if not isinstance(current, dict) or not isinstance(restored, dict) or not isinstance(plan.get("expect"), str) \
            or not SHA.fullmatch(plan["expect"]) or not isinstance(plan.get("label"), str) or not plan["label"].strip():
        raise ApiError(503, UNCONFIRMED)
    rows = []
    for source in (current, restored):
        row = {}
        for key in columns:
            value = source.get(key)
            if key == "quantity":
                if type(value) is not int or not 1 <= value <= 9999:
                    raise ApiError(503, UNCONFIRMED)
            elif not isinstance(value, str):
                raise ApiError(503, UNCONFIRMED)
            row[key] = value
        rows.append(row)
    current, restored = rows
    changed = [key for key in columns if current[key] != restored[key]]
    if not changed or set(changed) - set(MUTABLE[kind]):
        raise ApiError(503, UNCONFIRMED)
    fields = [{"field": key, "before": current[key], "after": restored[key]} for key in MUTABLE[kind] if key in changed]
    return {"available": True, "id": plan["change_id"], "expect": plan["expect"], "kind": kind, "space": plan["space"],
            "label": plan["label"], "fields": fields, "current": current, "restored": restored}


def _restored(after, plan):
    from decklab.lib.inventory import undo
    kind, space = plan["kind"], plan["space"]
    sheet = after.collection(space) if kind == "collection" else after.token_set(space)
    try:
        actual = undo.restored_row(after, plan)
    except (inventory.Invalid, inventory.Conflict, ValueError, TypeError):
        raise ApiError(503, UNCONFIRMED) from None
    if actual != plan["restore"]:
        raise ApiError(503, UNCONFIRMED)
    return sheet, actual


def undo_view(id=None):
    """GET /api/activity/undo?id=N: owner-only original-row review, with no write."""
    change_id, profile = _id(id), guard.viewer()
    try:
        return _project(_review(change_id, profile))
    except ApiError as error:
        if error.status == 400:
            return {"available": False, "id": change_id, "reason": UNSUPPORTED}
        raise


def apply_undo(body):
    """POST {profile,id,expect}: one new audited undo, never a history rewrite."""
    data = _parse_body(body)
    _keys(data, ("profile", "id", "expect"))
    profile, change_id = _writer(data), _id(data["id"])
    plan = _review(change_id, profile)  # hidden/missing is resolved before malformed or stale receipt errors
    _project(plan)
    if not isinstance(data["expect"], str) or not SHA.fullmatch(data["expect"]):
        raise ApiError(400, "expect must be the full review receipt from Undo")
    if data["expect"] != plan["expect"]:
        raise _changed(plan["label"])
    op = inventory.Op("inventory.undo", {"change_id": change_id, "space": plan["space"], "expect": data["expect"]})
    after, summary = saving.apply_op(op, profile, f"Undo activity change {change_id}", _refused)
    extra, counts = summary.extra or {}, summary.counts or {}
    if not summary.changed or type(counts.get("undo")) is not int or counts["undo"] != 1 \
            or extra.get("undo_of") != change_id or extra.get("kind") != plan["kind"] or extra.get("space") != plan["space"] \
            or extra.get("row_change_id") != plan["row_change_id"]:
        raise ApiError(503, UNCONFIRMED)
    sheet, restored = _restored(after, plan)
    return {"saved": True, "source_id": change_id, "expect": data["expect"], "kind": plan["kind"], "space": plan["space"],
            "sha256": files.rendered_sha256(sheet), "revision": after.revision, "restored": restored, "summary": summary.text}
