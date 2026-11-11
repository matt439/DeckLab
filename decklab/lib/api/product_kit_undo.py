"""Home-only whole-source product-kit recovery. No submitted assignment is authority."""
from decklab.lib import inventory
from decklab.lib.inventory import product_kit_undo as undo
from . import guard, saving
from .common import ApiError, DATABASE_DOWN, _keys, _parse_body
from .settings import _web_actor, _writer
from .accessory_undo import _id

UNCONFIRMED = "The complete product-kit Undo result could not be confirmed. Reload Activity."


def _owners(profile):
    guard.require_sees_home_records(profile)
    guard.require(profile, "accessories.edit")
    return guard.accessory_owners(profile)


def hint(change, shown, profile):
    rows = change.get("rows") or []
    if not profile or shown.get("id") != change.get("id") or change.get("more") or change.get("groups") \
            or not isinstance(rows, list) or type(change.get("total", len(rows))) is not int \
            or change.get("total", len(rows)) != len(rows) or not 1 <= len(rows) <= undo.MAX_ROWS:
        return None
    try:
        _owners(profile)
        undo.source(rows)
    except (ApiError, inventory.Invalid, inventory.Conflict):
        return None
    return {"review": True, "kind": "product_kit"}


def project(plan):
    try:
        if not isinstance(plan, dict) or plan.get("kind") != "product_kit" or plan.get("action") != undo.ACTION \
                or plan.get("kit_confirmation_required") is not True or not isinstance(plan.get("expect"), str) \
                or not undo.SHA.fullmatch(plan["expect"]) or not isinstance(plan.get("rows"), list) \
                or type(plan.get("row_count")) is not int or not 1 <= plan["row_count"] <= undo.MAX_ROWS or len(plan["rows"]) != plan["row_count"]:
            raise ValueError("Bad plan")
        source = undo.source(plan["proof"]["source"])
        if set(source) != {row["file"] for row in plan["rows"]}:
            raise ValueError("Wrong products")
        for row in plan["rows"]:
            raw = source[row["file"]]
            if set(row) != {"file", "title", "current", "restored"} or not isinstance(row["title"], str) or not row["title"] \
                    or any(row[side] != {field: raw[image][field] for field in undo.kit.FIELDS}
                           for side, image in (("current", "after"), ("restored", "before"))):
                raise ValueError("Wrong kit")
        return {"available": True, "id": plan["change_id"], "kind": "product_kit", "action": undo.ACTION,
                "label": "Complete product-kit change", "expect": plan["expect"], "row_count": plan["row_count"],
                "rows": plan["rows"], "kit_confirmation_required": True}
    except (ValueError, KeyError, TypeError, inventory.Invalid):
        raise ApiError(503, UNCONFIRMED) from None


def _review(change_id, owners):
    method = getattr(inventory.backend(), "product_kit_undo_review", None)
    if not callable(method):
        raise ApiError(503, "Product-kit Undo needs its database audit trail.")
    try:
        plan = method(change_id, owners)
        if not isinstance(plan, dict) or plan.get("change_id") != change_id or plan.get("owners") != (None if owners is None else sorted(owners)):
            raise ApiError(503, UNCONFIRMED)
        return plan
    except undo.UndoMissing:
        raise ApiError(404, "No complete product-kit change at that ID.") from None
    except inventory.Conflict:
        raise ApiError(409, undo.CHANGED) from None
    except inventory.Invalid:
        raise ApiError(400, undo.UNSUPPORTED) from None
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None


def view(id=None):
    owners = _owners(guard.viewer())
    cid = _id(id)
    try:
        return project(_review(cid, owners))
    except ApiError as error:
        if error.status == 400:
            return {"available": False, "id": cid, "reason": undo.UNSUPPORTED}
        raise


def apply(body):
    _owners(guard.viewer())
    data = _parse_body(body)
    writer = _writer(data)
    owners = _owners(writer)
    _keys(data, ("profile", "id", "expect", "confirm_kit"))
    cid = _id(data["id"])
    plan = _review(cid, owners)
    preview = project(plan)
    if data["confirm_kit"] is not True:
        raise ApiError(400, "Confirm every restored product-kit assignment before saving Undo.")
    operation = undo.Restore(cid, owners, data["expect"], data["confirm_kit"], inventory.backend())
    try:
        _, summary = inventory.apply(operation, _web_actor(writer), f"Undo product-kit change {cid}")
    except (inventory.Invalid, inventory.Conflict, inventory.Unavailable) as error:
        raise saving._refused(error) from None
    receipt = summary.extra.get("product_kit_undo")
    if not isinstance(receipt, dict) or set(receipt) != {"saved", "source_id", "expect", "kind", "action", "rows", "row_count", "sha256", "revision", "summary"} \
            or receipt.get("saved") is not True or receipt.get("source_id") != cid \
            or receipt.get("expect") != preview["expect"] or receipt.get("rows") != preview["rows"] \
            or receipt.get("action") != undo.ACTION or receipt.get("kind") != "product_kit" \
            or receipt.get("row_count") != preview["row_count"] or receipt.get("sha256") != plan["sha256"] \
            or not isinstance(receipt.get("revision"), str) or not receipt["revision"].isdigit() \
            or not 0 < int(receipt["revision"]) < 2 ** 63 or not isinstance(receipt.get("summary"), str) or not receipt["summary"]:
        raise ApiError(503, UNCONFIRMED)
    return receipt
