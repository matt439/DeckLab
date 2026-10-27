"""Review narrow accessory inverses while retaining current photographs and kit."""
import re

from decklab.lib import accessories, inventory
from decklab.lib.inventory import accessory_undo as undo

from . import activity, guard
from .common import ApiError, DATABASE_DOWN, _keys, _parse_body
from .settings import _web_actor, _writer

NO_CHANGE = "No undoable accessory change at that ID."
UNSUPPORTED = "Undo restores recorded accessory details and box capacity, removes an unused image-free addition or restores an exact image-free deleted record. Current photos and kit are kept; capacity may change fit warnings."
CHANGED = "The accessories changed. Reload Activity and review this Undo again."
UNCONFIRMED = "The accessory Undo result could not be confirmed. Reload Activity before trying again."
REVISION = re.compile(r"[1-9][0-9]{0,18}")


def _id(value):
    number = activity._number(value, "id", "a change set ID (a whole number above 0)")
    if number is None or number >= 10 ** 18:
        raise ApiError(400, "id must be a change set ID (a whole number above 0)")
    return number


def _call(method, *args):
    function = getattr(inventory.backend(), method, None)
    if not callable(function):
        raise ApiError(503, "Accessory Undo needs its database audit trail.")
    try:
        return function(*args)
    except undo.UndoMissing:
        raise ApiError(404, NO_CHANGE) from None
    except inventory.Conflict:
        raise ApiError(409, CHANGED) from None
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except inventory.Invalid:
        raise ApiError(400, UNSUPPORTED) from None


def _meta(value):
    if not isinstance(value, dict) or set(value) != set(undo.META) or any(not isinstance(v, str) for v in value.values()):
        raise ApiError(503, UNCONFIRMED)
    raw = {field: "" for field in accessories.FIELDS}
    raw.update(value, quantity="0")
    try:
        if undo.meta(undo.raw_row(raw)) != value:
            raise inventory.Invalid("Bad metadata")
    except inventory.Invalid:
        raise ApiError(503, UNCONFIRMED) from None
    return dict(value)


def _project(plan, change_id, owners):
    if not isinstance(plan, dict) or plan.get("change_id") != change_id or plan.get("kind") != "accessory" \
            or plan.get("action") not in ("accessory_update", "accessory_remove", "accessory_add") or plan.get("owners") != (None if owners is None else sorted(owners)) \
            or not isinstance(plan.get("expect"), str) or not undo.SHA.fullmatch(plan["expect"]):
        raise ApiError(503, UNCONFIRMED)
    try:
        source = undo.source_record([plan.get("source")], owners)
        removing = plan["action"] == "accessory_remove"
        adding = plan["action"] == "accessory_add"
        if source["op"] != ("DELETE" if adding else "INSERT" if removing else "UPDATE"):
            raise inventory.Invalid("Bad source action")
        new, old = None if adding else undo.raw_row(source["after"]), None if removing else undo.raw_row(source["before"])
        identity = old if adding else new
        if source.get("key") != {"id": identity["id"]} or source.get("id") != plan.get("row_change_id") \
                or type(source.get("id")) is not int or not 0 < source["id"] < 10 ** 18 \
                or not removing and not adding and {field for field in undo.RAW if old[field] != new[field]} - set(undo.FIELDS):
            raise inventory.Invalid("Bad source proof")
        current, restored = (None, old) if adding else (new, None) if removing else (undo.meta(new), undo.meta(old))
    except (inventory.Invalid, KeyError):
        raise ApiError(503, UNCONFIRMED) from None
    if adding:
        if old["image"] or old["crop"] or "current" not in plan or plan["current"] is not None \
                or plan.get("restored") != restored or plan.get("confirmation_required") is not True \
                or "fields" in plan or "reason_required" in plan or plan.get("label") != old["name"]:
            raise ApiError(503, UNCONFIRMED)
        return {"available": True, "id": change_id, "expect": plan["expect"], "kind": "accessory",
                "action": "accessory_add", "label": old["name"], "current": None,
                "restored": restored, "confirmation_required": True}
    if removing:
        if new["image"] or new["crop"] or plan.get("current") != current or "restored" not in plan \
                or plan["restored"] is not None or plan.get("reason_required") is not True or "fields" in plan or "confirmation_required" in plan \
                or plan.get("label") != current["name"]:
            raise ApiError(503, UNCONFIRMED)
        return {"available": True, "id": change_id, "expect": plan["expect"], "kind": "accessory",
                "action": "accessory_remove", "label": current["name"], "current": current,
                "restored": None, "reason_required": True}
    current, restored = _meta(current), _meta(restored)
    fields = [{"field": field, "before": current[field], "after": restored[field]} for field in undo.FIELDS
              if current[field] != restored[field]]
    if not fields or any(current[field] != restored[field] for field in ("id", "kind", "owner")) \
            or plan.get("current") != current or plan.get("restored") != restored or plan.get("fields") != fields \
            or plan.get("label") != current["name"] or "reason_required" in plan or "confirmation_required" in plan:
        raise ApiError(503, UNCONFIRMED)
    return {"available": True, "id": change_id, "expect": plan["expect"], "kind": "accessory",
            "action": "accessory_update", "label": current["name"], "current": current, "restored": restored,
            "fields": fields}


def accessory_undo_view(id=None):
    profile = guard.viewer()
    guard.require(profile, "accessories.edit")
    owners, change_id = guard.accessory_owners(profile), _id(id)
    try:
        return _project(_call("accessory_undo_review", change_id, owners), change_id, owners)
    except ApiError as error:
        if error.status == 400:
            return {"available": False, "id": change_id, "reason": UNSUPPORTED}
        raise


def apply_accessory_undo(body):
    data = _parse_body(body)
    writer = _writer(data)
    guard.require(writer, "accessories.edit")
    owners = guard.accessory_owners(writer)
    _keys(data, ("profile", "id", "expect"), ("reason", "confirm_restore"))
    change_id = _id(data["id"])
    options = []
    if "reason" in data or "confirm_restore" in data:
        options.append(data.get("reason", ...))
    if "confirm_restore" in data:
        options.append(data["confirm_restore"])
    result = _call("accessory_undo_apply", change_id, owners, data["expect"], _web_actor(writer),
                   f"Undo accessory change {change_id}", *options)
    if not isinstance(result, dict):
        raise ApiError(503, UNCONFIRMED)
    raw_plan = result.get("review")
    plan = _project(raw_plan, change_id, owners)
    removing = plan["action"] == "accessory_remove"
    adding = plan["action"] == "accessory_add"
    try:
        actual = undo.raw_row(result.get("restored")) if adding else None if removing else _meta(result.get("restored"))
    except inventory.Invalid:
        raise ApiError(503, UNCONFIRMED) from None
    if actual != plan["restored"] or data["expect"] != plan["expect"] \
            or removing and ("restored" not in result or result["restored"] is not None or result.get("removed_id") != plan["current"]["id"]) \
            or not removing and "removed_id" in result \
            or adding and result.get("added_id") != plan["restored"]["id"] \
            or not adding and "added_id" in result \
            or not isinstance(result.get("sha256"), str) or not undo.SHA.fullmatch(result["sha256"]) \
            or result["sha256"] != raw_plan.get("sha256") \
            or type(raw_plan.get("row_change_id")) is not int or not 0 < raw_plan["row_change_id"] < 2 ** 63 \
            or not isinstance(result.get("revision"), str) or not REVISION.fullmatch(result["revision"]) \
            or not raw_plan["row_change_id"] < int(result["revision"]) < 2 ** 63:
        raise ApiError(503, UNCONFIRMED)
    return {"saved": True, "source_id": change_id, "expect": plan["expect"], "kind": "accessory",
            "action": plan["action"], "restored": actual, "sha256": result["sha256"],
            **({"removed_id": result["removed_id"]} if removing else {}),
            **({"added_id": result["added_id"]} if adding else {}),
            "revision": result["revision"], "summary": f"Undo change #{change_id}: " + (
                "restore a deleted accessory record" if adding else "remove an unused added accessory" if removing else "restore recorded accessory details")}
