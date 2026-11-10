"""Explicit whole collection-row recovery; no submitted row or location is write authority."""
import re

from decklab.lib import inventory
from decklab.lib.inventory import files, ops_collection, rules
from decklab.lib.inventory import undo_collection_changes as recovery

from . import guard, saving
from .common import ApiError

SHA = re.compile(r"[a-f0-9]{64}\Z")
UNCONFIRMED = "The complete collection Undo result could not be confirmed. Reload Activity."


def hint(change, shown, profile):
    rows = change.get("rows") or []
    if not profile or shown.get("id") != change.get("id") or change.get("groups") or change.get("more") \
            or type(change.get("total", len(rows))) is not int or change.get("total", len(rows)) != len(rows) \
            or not recovery.handles(rows):
        return None
    from .activity_undo import _space
    space = _space(profile)
    for row in rows:
        old, new = row.get("before"), row.get("after")
        if row["op"] == "UPDATE":
            fields = ["set_code" if field == "set" else field for field in rules.FIELDS]
            if not isinstance(old, dict) or not isinstance(new, dict) or all(old.get(field) == new.get(field) for field in fields):
                return None
        elif row["op"] == "INSERT":
            if old is not None or not isinstance(new, dict):
                return None
        elif row["op"] == "DELETE":
            if new is not None or not isinstance(old, dict):
                return None
        else:
            return None
    if all(isinstance(image, dict) and image.get("space_id") == space
           for row in rows for image in (row.get("before"), row.get("after")) if image is not None) \
            and guard.allowed(profile, "collection.edit", space):
        return {"review": True}
    return None


def _fact(row):
    if row is None:
        return None
    if not isinstance(row, dict) or set(row) != set(rules.FIELDS) or type(row.get("quantity")) is not int \
            or not 1 <= row["quantity"] <= 9999 or any(not isinstance(value, str) for key, value in row.items() if key != "quantity"):
        raise ApiError(503, UNCONFIRMED)
    return dict(row)


def _key(raw, space):
    if not isinstance(raw, dict) or set(raw) != {"space_id", "set_code", "collector_number", "finish"} or raw["space_id"] != space \
            or any(not isinstance(value, str) for value in raw.values()):
        raise ApiError(503, UNCONFIRMED)
    return {"set": raw["set_code"], "collector_number": raw["collector_number"], "finish": raw["finish"]}


def project(plan):
    count, rows, space = plan.get("row_count"), plan.get("rows"), plan.get("space")
    if plan.get("kind") != "collection" or plan.get("action") != recovery.ACTION or type(count) is not int \
            or not 1 <= count <= 50 or not isinstance(rows, list) or len(rows) != count \
            or not isinstance(plan.get("expect"), str) or not SHA.fullmatch(plan["expect"]) \
            or plan.get("label") != f"Complete collection change ({count} row{'s' if count != 1 else ''})":
        raise ApiError(503, UNCONFIRMED)
    shown, keys, audit_ids = [], set(), set()
    reason, confirmation = False, False
    for item in rows:
        if not isinstance(item, dict):
            raise ApiError(503, UNCONFIRMED)
        current, restored = _fact(item.get("current")), _fact(item.get("restore"))
        key = _key(item.get("key"), space)
        rid = item.get("row_change_id")
        identity = rules.ident(key)
        if type(rid) is not int or not 1 <= rid < 10 ** 18 or rid in audit_ids or identity in keys or current == restored \
                or any(rules.ident(row) != identity for row in (current, restored) if row is not None):
            raise ApiError(503, UNCONFIRMED)
        audit_ids.add(rid)
        keys.add(identity)
        from decklab.lib.inventory.undo import COLLECTION, _label
        label = _label(COLLECTION, current or restored)
        if item.get("label") != label:
            raise ApiError(503, UNCONFIRMED)
        renamed = current is not None and restored is not None and current["name"] != restored["name"]
        reason |= current is not None and (restored is None or renamed)
        confirmation |= restored is not None and (current is None or renamed)
        shown.append({"key": key, "label": label, "current": current, "restored": restored})
    if plan.get("reason_required") is not reason or plan.get("physical_confirmation_required") is not confirmation:
        raise ApiError(503, UNCONFIRMED)
    transfer = plan.get("location_transfer")
    added = [row for row in shown if row["current"] is not None and row["restored"] is None]
    deleted = [row for row in shown if row["current"] is None and row["restored"] is not None]
    if len(added) == len(deleted) == 1:
        if not isinstance(transfer, dict) or set(transfer) != {"from", "to", "location"}:
            raise ApiError(503, UNCONFIRMED)
        from_key, to_key = _key(transfer["from"], space), _key(transfer["to"], space)
        location = transfer["location"]
        try:
            valid_location = isinstance(location, str) and rules.clean_location(location) == location
        except ValueError:
            valid_location = False
        if from_key != added[0]["key"] or to_key != deleted[0]["key"] or not valid_location:
            raise ApiError(503, UNCONFIRMED)
        transfer = {"from": from_key, "to": to_key, "location": location}
    elif transfer is not None:
        raise ApiError(503, UNCONFIRMED)
    return {"available": True, "id": plan["change_id"], "expect": plan["expect"], "kind": "collection", "space": space,
            "action": recovery.ACTION, "label": plan["label"], "row_count": count, "rows": shown,
            "reason_required": reason, "physical_confirmation_required": confirmation, "location_transfer": transfer}


def apply(data, plan, profile, change_id, refused):
    from .activity_undo import _changed
    if plan["physical_confirmation_required"]:
        if data.get("confirm_owned") is not True:
            raise ApiError(400, "Confirm that every historical identity and deleted copy shown is still physically owned.")
    elif "confirm_owned" in data:
        raise ApiError(400, "This collection change takes no physical-restoration confirmation.")
    reason = None
    if plan["reason_required"]:
        from decklab.lib.inventory.undo import removal_reason
        try:
            reason = removal_reason(data.get("reason"))
        except inventory.Invalid as error:
            raise ApiError(400, str(error)) from None
    elif "reason" in data:
        raise ApiError(400, "This collection change removes no row or identity, so it takes no reason.")
    if not isinstance(data.get("expect"), str) or not SHA.fullmatch(data["expect"]):
        raise ApiError(400, "expect must be the full review receipt from Undo")
    if data["expect"] != plan["expect"]:
        raise _changed(plan["label"])
    after, summary = saving.apply_op(inventory.Op("inventory.undo", {"change_id": change_id, "space": plan["space"],
        "expect": data["expect"], **({"reason": reason} if plan["reason_required"] else {}),
        **({"confirm_owned": True} if plan["physical_confirmation_required"] else {})}),
        profile, f"Undo activity change {change_id}", refused, **({"reason": reason} if plan["reason_required"] else {}))
    extra = summary.extra or {}
    if not summary.changed or summary.counts != {"rows": plan["row_count"], "undo": 1} \
            or any(type(value) is not int for value in summary.counts.values()) \
            or extra.get("collection_confirmed") is not True or recovery.PROOF in extra \
            or extra.get("confirmed_owned") is not plan["physical_confirmation_required"] \
            or extra.get("row_change_ids") != [item["row_change_id"] for item in plan["rows"]] \
            or any(extra.get(key) != value for key, value in (("undo_of", change_id), ("space", plan["space"]),
                ("kind", "collection"), ("action", recovery.ACTION), ("row_count", plan["row_count"]), ("expect", data["expect"]), ("undo_reason", reason))):
        raise ApiError(503, UNCONFIRMED)
    current = recovery._remaining_collection(after, plan["space"], plan["label"])
    shown = project(plan)
    for item in shown["rows"]:
        if current.get(rules.ident(item["key"])) != item["restored"]:
            raise ApiError(503, UNCONFIRMED)
    return {"saved": True, "source_id": change_id, "expect": data["expect"], "kind": "collection", "space": plan["space"],
            "action": recovery.ACTION, "row_count": plan["row_count"], "rows": [{"key": item["key"], "row": item["restored"]} for item in shown["rows"]],
            "sha256": files.rendered_sha256(after.collection(plan["space"])),
            "locations_sha256": ops_collection.locations_sha256_of(after, plan["space"]), "summary": summary.text}
