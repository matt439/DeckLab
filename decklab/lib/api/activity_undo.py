"""Review eligible collection/token updates or collection insertions/deletions from original audit rows.

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
UNSUPPORTED = "This change cannot be undone here. Supported Undo covers single-row edits, unheld nonbasic collection additions, unheld verified token additions, verified collection deletions and batches of 2-50 unheld nonbasic collection additions, collection deletions or positive quantity/condition/language/notes updates."
CHANGED = "The change can no longer be undone safely. Reload Activity and review it again."
UNCONFIRMED = "The undo result could not be confirmed. Reload Activity before trying again."
SHA = re.compile(r"[a-f0-9]{64}")
MUTABLE = {"collection": ("quantity", "condition", "language", "notes"), "tokens": ("quantity", "notes")}
TABLE_KIND = {"collection_card": "collection", "token_card": "tokens"}
BATCH_ACTIONS = ("batch_metadata", "batch_update", "batch_add", "batch_remove")


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
    total = change.get("total", len(rows))
    if total == 1 and len(rows) == 1 and not change.get("more") and not change.get("groups") and profile \
            and shown.get("id") == change.get("id"):
        row = rows[0]
        from decklab.lib.inventory import accessory_undo
        if guard.allowed(profile, "accessories.edit"):
            try:
                accessory_undo.source_record(rows, guard.accessory_owners(profile))
            except accessory_undo.UndoMissing:
                pass
            else:
                return {"review": True, "kind": "accessory"}
        from decklab.lib.state import wishlist_undo
        try:
            wishlist_undo.source_record(rows, profile.get("id"))
        except wishlist_undo.UndoMissing:
            pass
        else:
            if permissions.sees_wishlist(profile, profile["id"]) and guard.allowed(profile, "wishlist.edit", profile["id"]):
                return {"review": True, "kind": "wishlist"}
    if type(total) is int and 2 <= total <= 50 and len(rows) == total and not change.get("more") and not change.get("groups"):
        space = _space(profile)
        if shown.get("id") == change.get("id") and guard.allowed(profile, "collection.edit", space) \
                and all(isinstance(row, dict) and row.get("table") == "collection_card"
                        and (row.get("op") == "INSERT" and row.get("before") is None and isinstance(row.get("after"), dict)
                             and row["after"].get("space_id") == space
                             or isinstance(row.get("before"), dict) and row["before"].get("space_id") == space
                             and (row.get("op") == "UPDATE" and isinstance(row.get("after"), dict) and row["after"].get("space_id") == space
                                  or row.get("op") == "DELETE" and row.get("after") is None)) for row in rows) \
                and len({row["op"] for row in rows}) == 1:
            return {"review": True}
        return None
    if change.get("total", len(rows)) != 1 or len(rows) != 1 or change.get("more") or change.get("groups"):
        return None
    row = rows[0]
    kind = TABLE_KIND.get(row.get("table"))
    before, after = row.get("before"), row.get("after")
    token_insert = row.get("table") == "token_card" and isinstance(after, dict) \
        and type(after.get("id")) is int and 1 <= after["id"] < 10 ** 18 \
        and type(after.get("position")) is int and after["position"] >= 0 and row.get("key") == {"id": after["id"]}
    insertion = (row.get("table") == "collection_card" or token_insert) and row.get("op") == "INSERT" and before is None
    deletion = row.get("table") == "collection_card" and row.get("op") == "DELETE" and after is None and isinstance(before, dict)
    if not kind or not deletion and (not isinstance(after, dict) or not insertion and (row.get("op") != "UPDATE" or not isinstance(before, dict))):
        return None
    space = _space(profile)
    if not insertion and before.get("space_id") != space or not deletion and after.get("space_id") != space \
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
    if plan.get("action") in BATCH_ACTIONS:
        return _batch_project(plan)
    kind = plan["kind"]
    columns = rules.FIELDS if kind == "collection" else rules.TOKEN_FIELDS
    current, restored = plan.get("current"), plan.get("restore")
    removing = plan.get("action") == "remove"
    adding = plan.get("action") == "add"
    if not (current is None if adding else isinstance(current, dict)) \
            or not (restored is None if removing else isinstance(restored, dict)) \
            or removing and (kind not in MUTABLE or plan.get("reason_required") is not True) \
            or adding and (kind != "collection" or plan.get("physical_confirmation_required") is not True) \
            or not isinstance(plan.get("expect"), str) \
            or not SHA.fullmatch(plan["expect"]) or not isinstance(plan.get("label"), str) or not plan["label"].strip():
        raise ApiError(503, UNCONFIRMED)
    rows = []
    for source in (restored,) if adding else (current,) if removing else (current, restored):
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
    if removing:
        extra = {}
        if kind == "tokens":
            rid = plan.get("token_row_id")
            if type(rid) is not int or not 1 <= rid < 10 ** 18 or plan.get("key") != {"id": rid}:
                raise ApiError(503, UNCONFIRMED)
            extra["token_row_id"] = rid
        return {"available": True, "id": plan["change_id"], "expect": plan["expect"], "kind": kind, "space": plan["space"],
                "label": plan["label"], "action": "remove", "reason_required": True, "current": rows[0], "restored": None, **extra}
    if adding:
        return {"available": True, "id": plan["change_id"], "expect": plan["expect"], "kind": kind, "space": plan["space"],
                "label": plan["label"], "action": "add", "physical_confirmation_required": True, "current": None, "restored": rows[0]}
    current, restored = rows
    changed = [key for key in columns if current[key] != restored[key]]
    if not changed or set(changed) - set(MUTABLE[kind]):
        raise ApiError(503, UNCONFIRMED)
    fields = [{"field": key, "before": current[key], "after": restored[key]} for key in MUTABLE[kind] if key in changed]
    return {"available": True, "id": plan["change_id"], "expect": plan["expect"], "kind": kind, "space": plan["space"],
            "label": plan["label"], "fields": fields, "current": current, "restored": restored}


def _batch_project(plan):
    if plan.get("kind") != "collection" or type(plan.get("row_count")) is not int or not 2 <= plan["row_count"] <= 50 \
            or not isinstance(plan.get("rows"), list) or len(plan["rows"]) != plan["row_count"] \
            or not isinstance(plan.get("label"), str) or not plan["label"].strip():
        raise ApiError(503, UNCONFIRMED)
    rows, keys, ids = [], set(), set()
    quantity_changed = False
    adding = plan["action"] == "batch_add"
    removing = plan["action"] == "batch_remove"
    if adding and plan.get("physical_confirmation_required") is not True or removing and plan.get("reason_required") is not True:
        raise ApiError(503, UNCONFIRMED)
    for item in plan["rows"]:
        if not isinstance(item, dict) or type(item.get("row_change_id")) is not int or item["row_change_id"] < 1:
            raise ApiError(503, UNCONFIRMED)
        projected = _project({"kind": "collection", "space": plan["space"], "change_id": plan["change_id"],
                              "expect": plan["expect"], "label": item.get("label"),
                              "current": item.get("current"), "restore": item.get("restore"),
                              **({"action": "add", "physical_confirmation_required": True} if adding else {}),
                              **({"action": "remove", "reason_required": True} if removing else {})})
        key = rules.ident(projected["restored"] if adding else projected["current"])
        raw_key = item.get("key")
        if not isinstance(raw_key, dict) or set(raw_key) != {"space_id", "set_code", "collector_number", "finish"} \
                or raw_key != {"space_id": plan["space"], "set_code": key[0], "collector_number": key[1], "finish": key[2]} \
                or key in keys or item["row_change_id"] in ids \
                or not adding and not removing and any(field["field"] not in MUTABLE["collection"] for field in projected["fields"]):
            raise ApiError(503, UNCONFIRMED)
        if not adding and not removing:
            quantity_changed = quantity_changed or projected["current"]["quantity"] != projected["restored"]["quantity"]
        keys.add(key)
        ids.add(item["row_change_id"])
        rows.append({"key": dict(zip(("set", "collector_number", "finish"), key)), "label": projected["label"],
                     "current": projected["current"], "restored": projected["restored"],
                     **({} if adding or removing else {"fields": projected["fields"]})})
    if not adding and not removing and (plan["action"] == "batch_update") != quantity_changed:
        raise ApiError(503, UNCONFIRMED)
    return {"available": True, "id": plan["change_id"], "expect": plan["expect"], "kind": "collection", "space": plan["space"],
            "label": plan["label"], "action": plan["action"], "row_count": len(rows), "rows": rows,
            **({"physical_confirmation_required": True} if adding else {}), **({"reason_required": True} if removing else {})}


def _restored(after, plan):
    from decklab.lib.inventory import undo
    kind, space = plan["kind"], plan["space"]
    sheet = after.collection(space) if kind == "collection" else after.token_set(space)
    try:
        actual = undo.restored_row(after, plan)
    except (inventory.Invalid, inventory.Conflict, ValueError, TypeError, KeyError):
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
    _keys(data, ("profile", "id", "expect"), ("reason", "confirm_owned"))
    profile, change_id = _writer(data), _id(data["id"])
    plan = _review(change_id, profile)  # hidden/missing is resolved before malformed or stale receipt errors
    _project(plan)
    removing = plan.get("action") in ("remove", "batch_remove")
    adding = plan.get("action") in ("add", "batch_add")
    if adding:
        if data.get("confirm_owned") is not True:
            raise ApiError(400, "Confirm that you still physically own every recorded copy before restoring these copies.")
    elif "confirm_owned" in data:
        raise ApiError(400, "Physical ownership confirmation is accepted only when restoring a deleted collection row.")
    reason = None
    if removing:
        from decklab.lib.inventory import undo
        try:
            reason = undo.removal_reason(data.get("reason"))
        except inventory.Invalid as error:
            raise ApiError(400, str(error)) from None
    elif "reason" in data:
        raise ApiError(400, "A reason is accepted only when Undo removes an added collection or token row.")
    if not isinstance(data["expect"], str) or not SHA.fullmatch(data["expect"]):
        raise ApiError(400, "expect must be the full review receipt from Undo")
    if data["expect"] != plan["expect"]:
        raise _changed(plan["label"])
    op = inventory.Op("inventory.undo", {"change_id": change_id, "space": plan["space"], "expect": data["expect"],
                                         **({"reason": reason} if removing else {}),
                                         **({"confirm_owned": True} if adding else {})})
    after, summary = saving.apply_op(op, profile, f"Undo activity change {change_id}", _refused,
                                     **({"reason": reason} if removing else {}))
    extra, counts = summary.extra or {}, summary.counts or {}
    if plan.get("action") in BATCH_ACTIONS:
        if not summary.changed or type(counts.get("undo")) is not int or counts["undo"] != 1 \
                or extra.get("undo_of") != change_id or extra.get("kind") != "collection" or extra.get("space") != plan["space"] \
                or extra.get("action") != plan["action"] or type(extra.get("row_count")) is not int \
                or extra["row_count"] != plan["row_count"] \
                or extra.get("row_change_ids") != [item["row_change_id"] for item in plan["rows"]]:
            raise ApiError(503, UNCONFIRMED)
        if adding:
            expected = {"added_rows": plan["row_count"], "bumped_rows": 0, "skipped_basics": 0,
                        "cards": sum(item["restore"]["quantity"] for item in plan["rows"])}
            if extra.get("confirmed_owned") is not True or counts.get("merged") is not False \
                    or any(type(counts.get(key)) is not int or counts[key] != value for key, value in expected.items()):
                raise ApiError(503, UNCONFIRMED)
        elif removing:
            if type(counts.get("edited")) is not int or counts["edited"] != 0 \
                    or type(counts.get("removed")) is not int or counts["removed"] != plan["row_count"] or extra.get("undo_reason") != reason:
                raise ApiError(503, UNCONFIRMED)
        elif type(counts.get("edited")) is not int or counts["edited"] != plan["row_count"] \
                or type(counts.get("removed")) is not int or counts["removed"] != 0:
            raise ApiError(503, UNCONFIRMED)
        from decklab.lib.inventory import undo
        try:
            actual = undo.removed_keys(after, plan) if removing else undo.restored_rows(after, plan)
        except Exception:
            raise ApiError(503, UNCONFIRMED) from None
        return {"saved": True, "source_id": change_id, "expect": data["expect"], "kind": "collection", "space": plan["space"],
                "action": plan["action"], "row_count": plan["row_count"],
                **({"removed_keys": actual, "restored": None} if removing else {"restored_rows": actual}),
                "sha256": files.rendered_sha256(after.collection(plan["space"])), "revision": after.revision, "summary": summary.text}
    if not summary.changed or type(counts.get("undo")) is not int or counts["undo"] != 1 \
            or extra.get("undo_of") != change_id or extra.get("kind") != plan["kind"] or extra.get("space") != plan["space"] \
            or extra.get("row_change_id") != plan["row_change_id"]:
        raise ApiError(503, UNCONFIRMED)
    if removing and (extra.get("action") != "remove" or extra.get("undo_reason") != reason):
        raise ApiError(503, UNCONFIRMED)
    if removing and plan["kind"] == "tokens":
        if type(extra.get("removed_token_row_id")) is not int or extra["removed_token_row_id"] != plan["token_row_id"] \
                or not isinstance(plan.get("token_rows_after"), list) or type(counts.get("cards")) is not int:
            raise ApiError(503, UNCONFIRMED)
    if adding:
        expected = {"added_rows": 1, "bumped_rows": 0, "skipped_basics": 0, "cards": plan["restore"]["quantity"]}
        if extra.get("action") != "add" or extra.get("confirmed_owned") is not True or counts.get("merged") is not False \
                or any(type(counts.get(key)) is not int or counts[key] != value for key, value in expected.items()):
            raise ApiError(503, UNCONFIRMED)
    sheet, restored = _restored(after, plan)
    if removing and plan["kind"] == "tokens" and counts["cards"] != sum(row.qty for row in sheet.rows):
        raise ApiError(503, UNCONFIRMED)
    result = {"saved": True, "source_id": change_id, "expect": data["expect"], "kind": plan["kind"], "space": plan["space"],
              "sha256": files.rendered_sha256(sheet), "revision": after.revision, "restored": restored, "summary": summary.text}
    if removing:
        if plan["kind"] == "tokens":
            result.update(action="remove", removed_token_row_id=plan["token_row_id"])
        else:
            result.update(action="remove", removed_key={key: plan["current"][key] for key in ("set", "collector_number", "finish")})
    elif adding:
        result.update(action="add", added_key={key: plan["restore"][key] for key in ("set", "collector_number", "finish")})
    return result
