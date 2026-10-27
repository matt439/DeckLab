"""Review narrow accessory inverses while retaining current photographs and kit."""
import re

from decklab.lib import accessories, inventory
from decklab.lib.inventory import accessory_undo as undo

from . import activity, guard
from .common import ApiError, DATABASE_DOWN, _keys, _parse_body
from .settings import _web_actor, _writer

NO_CHANGE = "No undoable accessory change at that ID."
UNSUPPORTED = "Undo restores recorded accessory details, a reviewed crop on the current photo, confirmed counts or unused record corrections, removes an unused image-free addition or restores an exact image-free deleted record. Current photos and kit are kept; recorded counts and capacity may change warnings."
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


def _meta(value, stock=False):
    if not isinstance(value, dict) or set(value) != set(undo.STOCK_META if stock else undo.META) or any(not isinstance(v, str) for v in value.values()):
        raise ApiError(503, UNCONFIRMED)
    raw = {field: "" for field in accessories.FIELDS}
    raw.update(value)
    if not stock:
        raw["quantity"] = "0"
    try:
        if (undo.stock_meta if stock else undo.meta)(undo.raw_row(raw)) != value:
            raise inventory.Invalid("Bad metadata")
    except inventory.Invalid:
        raise ApiError(503, UNCONFIRMED) from None
    return dict(value)


def _project(plan, change_id, owners):
    if not isinstance(plan, dict) or plan.get("change_id") != change_id or plan.get("kind") != "accessory" \
            or plan.get("action") not in (*undo.UPDATE_FIELDS, "accessory_remove", "accessory_add") or plan.get("owners") != (None if owners is None else sorted(owners)) \
            or not isinstance(plan.get("expect"), str) or not undo.SHA.fullmatch(plan["expect"]):
        raise ApiError(503, UNCONFIRMED)
    action = plan["action"]
    cropping = action == "accessory_crop_update"
    flags = ("reason_required", "confirmation_required", *undo.UPDATE_CONFIRMATIONS.values())
    try:
        source = undo.source_record([plan.get("source")], owners)
        removing = action == "accessory_remove"
        adding = action == "accessory_add"
        if source["op"] != ("DELETE" if adding else "INSERT" if removing else "UPDATE"):
            raise inventory.Invalid("Bad source action")
        new, old = None if adding else undo.raw_row(source["after"]), None if removing else undo.raw_row(source["before"])
        identity = old if adding else new
        if source.get("key") != {"id": identity["id"]} or source.get("id") != plan.get("row_change_id") \
                or type(source.get("id")) is not int or not 0 < source["id"] < 10 ** 18 \
                or not removing and not adding and (action != undo.update_action(old, new) \
                    or old["owner"] != new["owner"] and not undo.owner_pair(old, new) \
                    or {field for field in undo.RAW if old[field] != new[field]} - set(undo.UPDATE_FIELDS[action])):
            raise inventory.Invalid("Bad source proof")
        wide = action in undo.UPDATE_CONFIRMATIONS
        project = dict if cropping else undo.stock_meta if wide else undo.meta
        current, restored = (None, old) if adding else (new, None) if removing else (project(new), project(old))
        photo = undo.photo_envelope(plan.get("photo")) if cropping else None
        if cropping and (not new["image"] or photo["name"] != new["image"]) or not cropping and "photo" in plan:
            raise inventory.Invalid("Bad current photo proof")
    except (inventory.Invalid, KeyError):
        raise ApiError(503, UNCONFIRMED) from None
    if adding:
        if old["image"] or old["crop"] or "current" not in plan or plan["current"] is not None \
                or plan.get("restored") != restored or plan.get("confirmation_required") is not True \
                or "fields" in plan or any(flag in plan for flag in flags if flag != "confirmation_required") or plan.get("label") != old["name"]:
            raise ApiError(503, UNCONFIRMED)
        return {"available": True, "id": change_id, "expect": plan["expect"], "kind": "accessory",
                "action": "accessory_add", "label": old["name"], "current": None,
                "restored": restored, "confirmation_required": True}
    if removing:
        if new["image"] or new["crop"] or plan.get("current") != current or "restored" not in plan \
                or plan["restored"] is not None or plan.get("reason_required") is not True or "fields" in plan \
                or any(flag in plan for flag in flags if flag != "reason_required") \
                or plan.get("label") != current["name"]:
            raise ApiError(503, UNCONFIRMED)
        return {"available": True, "id": change_id, "expect": plan["expect"], "kind": "accessory",
                "action": "accessory_remove", "label": current["name"], "current": current,
                "restored": None, "reason_required": True}
    current, restored = (undo.raw_row(current), undo.raw_row(restored)) if cropping else (_meta(current, wide), _meta(restored, wide))
    editable = undo.UPDATE_FIELDS[action]
    flag = undo.UPDATE_CONFIRMATIONS.get(action)
    fields = [{"field": field, "before": current[field], "after": restored[field]} for field in editable
              if current[field] != restored[field]]
    if not fields or any(current[field] != restored[field] for field in current if field not in editable) \
            or plan.get("current") != current or plan.get("restored") != restored or plan.get("fields") != fields \
            or plan.get("label") != current["name"] or any(other in plan for other in flags if other != flag) \
            or flag is not None and plan.get(flag) is not True:
        raise ApiError(503, UNCONFIRMED)
    return {"available": True, "id": change_id, "expect": plan["expect"], "kind": "accessory",
            "action": action, "label": current["name"], "current": current, "restored": restored,
            "fields": fields, **({flag: True} if flag is not None else {}), **({"photo": photo} if cropping else {})}


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
    _keys(data, ("profile", "id", "expect"), ("reason", "confirm_restore", "confirm_stock", "confirm_owner", "confirm_kind", "confirm_record", "confirm_photo"))
    change_id = _id(data["id"])
    options = [data.get(field, ...) for field in ("reason", "confirm_restore", "confirm_stock", "confirm_owner", "confirm_kind", "confirm_record", "confirm_photo")]
    while options and options[-1] is ...:
        options.pop()
    result = _call("accessory_undo_apply", change_id, owners, data["expect"], _web_actor(writer),
                   f"Undo accessory change {change_id}", *options)
    if not isinstance(result, dict):
        raise ApiError(503, UNCONFIRMED)
    raw_plan = result.get("review")
    plan = _project(raw_plan, change_id, owners)
    removing = plan["action"] == "accessory_remove"
    adding = plan["action"] == "accessory_add"
    stock = plan["action"] == "accessory_stock_update"
    ownership = plan["action"] == "accessory_owner_update"
    kind_change = plan["action"] == "accessory_kind_update"
    record = plan["action"] == "accessory_record_update"
    cropping = plan["action"] == "accessory_crop_update"
    try:
        actual = undo.raw_row(result.get("restored")) if adding or cropping else None if removing else _meta(result.get("restored"), plan["action"] in undo.UPDATE_CONFIRMATIONS)
        photo = undo.photo_envelope(result.get("photo")) if cropping else None
    except inventory.Invalid:
        raise ApiError(503, UNCONFIRMED) from None
    if actual != plan["restored"] or data["expect"] != plan["expect"] \
            or cropping and photo != plan["photo"] or not cropping and "photo" in result \
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
            **({"photo": photo} if cropping else {}),
            "revision": result["revision"], "summary": f"Undo change #{change_id}: " + (
                "restore a deleted accessory record" if adding else "remove an unused added accessory" if removing else "restore a crop on the current accessory photo" if cropping else "restore a combined accessory correction" if record else "restore the recorded accessory kind" if kind_change else "restore recorded accessory sharing" if ownership else "restore a recorded accessory count" if stock else "restore recorded accessory details")}
