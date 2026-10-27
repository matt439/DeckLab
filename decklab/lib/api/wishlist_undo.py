"""Private owner-only wishlist preference Undo, independent of inventory Undo."""
import re

from decklab.lib import permissions, state
from decklab.lib.state import rules, wishlist_undo as undo

from . import activity, guard
from .common import ApiError, DATABASE_DOWN, _keys, _parse_body
from .settings import _web_actor, _writer

NO_CHANGE = "No undoable wishlist change at that ID."
UNSUPPORTED = "Undo supports one wishlist entry's preferences or the latest add or removal on your wishlist."
CHANGED = "The wishlist changed. Reload Activity and review this Undo again."
UNCONFIRMED = "The wishlist Undo result could not be confirmed. Reload Activity before trying again."
REVISION = re.compile(r"[1-9][0-9]{0,18}")


def _viewer():
    viewer = guard.viewer()
    if not viewer or not isinstance(viewer.get("id"), str) or not permissions.sees_wishlist(viewer, viewer["id"]):
        raise ApiError(404, NO_CHANGE)
    guard.require_sees_wishlist(viewer["id"])
    guard.require(viewer, "wishlist.edit", viewer["id"])
    return viewer


def _id(value):
    number = activity._number(value, "id", "a change set ID (a whole number above 0)")
    if number is None or number >= 10 ** 18:
        raise ApiError(400, "id must be a change set ID (a whole number above 0)")
    return number


def _call(method, *args):
    function = getattr(state.store(), method, None)
    if not callable(function):
        raise ApiError(503, "Wishlist Undo needs its database audit trail.")
    try:
        return function(*args)
    except undo.UndoMissing:
        raise ApiError(404, NO_CHANGE) from None
    except (undo.UndoConflict, state.Conflict):
        raise ApiError(409, CHANGED) from None
    except state.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except state.Invalid:
        raise ApiError(400, UNSUPPORTED) from None


def _entry(value):
    try:
        if not isinstance(value, dict) or set(value) != set(rules.ENTRY_KEYS) or rules.entry(value) != value:
            raise ValueError("Bad entry")
    except (state.Invalid, TypeError, ValueError):
        raise ApiError(503, UNCONFIRMED) from None
    return dict(value)


def _project(plan, change_id, pid):
    if not isinstance(plan, dict) or not {"current", "restored"} <= set(plan) or plan.get("change_id") != change_id or plan.get("profile") != pid \
            or plan.get("kind") != "wishlist" or plan.get("action") not in ("wishlist_update", "wishlist_add", "wishlist_remove") \
            or not isinstance(plan.get("expect"), str) or not undo.SHA.fullmatch(plan["expect"]):
        raise ApiError(503, UNCONFIRMED)
    action = plan["action"]
    current = None if action == "wishlist_add" else _entry(plan.get("current"))
    restored = None if action == "wishlist_remove" else _entry(plan.get("restored"))
    if action == "wishlist_add" and plan.get("current") is not None \
            or action == "wishlist_remove" and plan.get("restored") is not None \
            or action == "wishlist_update" and current["name"] != restored["name"] \
            or plan.get("label") != (restored if current is None else current)["name"]:
        raise ApiError(503, UNCONFIRMED)
    extra = {}
    if action == "wishlist_update":
        fields = [{"field": field, "before": current[field], "after": restored[field]} for field in undo.FIELDS
                  if current[field] != restored[field]]
        if not fields or plan.get("fields") != fields:
            raise ApiError(503, UNCONFIRMED)
        extra = {"fields": fields}
    elif "fields" in plan:
        raise ApiError(503, UNCONFIRMED)
    return {"available": True, "id": change_id, "expect": plan["expect"], "kind": "wishlist", "action": action,
            "profile": pid, "label": plan["label"], "current": current, "restored": restored, **extra}


def wishlist_undo_view(id=None):
    viewer = _viewer()
    change_id, pid = _id(id), viewer["id"]
    try:
        return _project(_call("wishlist_undo_review", change_id, pid), change_id, pid)
    except ApiError as error:
        if error.status == 400:
            return {"available": False, "id": change_id, "reason": UNSUPPORTED}
        raise


def apply_wishlist_undo(body):
    viewer = _viewer()  # A script body can name an actor; it cannot establish this reader.
    data = _parse_body(body)
    _keys(data, ("profile", "id", "expect"))
    writer = _writer(data)
    if writer["id"] != viewer["id"] or data["profile"] != viewer["id"]:
        raise ApiError(403, "You can only change your own wishlist.")
    change_id, pid = _id(data["id"]), viewer["id"]
    result = _call("wishlist_undo_apply", change_id, pid, data["expect"], _web_actor(viewer), f"Undo wishlist change {change_id}")
    if not isinstance(result, dict):
        raise ApiError(503, UNCONFIRMED)
    raw_plan = result.get("review")
    plan = _project(raw_plan, change_id, pid)
    removing = plan["action"] == "wishlist_remove"
    actual = None if removing else _entry(result.get("restored"))
    if actual != plan["restored"] or data["expect"] != plan["expect"] \
            or removing and ("restored" not in result or result["restored"] is not None or result.get("removed_name") != plan["current"]["name"]) \
            or not removing and "removed_name" in result \
            or not isinstance(result.get("sha256"), str) or not undo.SHA.fullmatch(result["sha256"]) \
            or result["sha256"] != raw_plan.get("sha256") \
            or type(raw_plan.get("latest_owner")) is not int or not 0 < raw_plan["latest_owner"] < 2 ** 63 \
            or not isinstance(result.get("revision"), str) or not REVISION.fullmatch(result["revision"]) \
            or not raw_plan["latest_owner"] < int(result["revision"]) < 2 ** 63:
        raise ApiError(503, UNCONFIRMED)
    summary = {"wishlist_update": "restore wishlist preferences", "wishlist_add": "restore a removed wishlist entry",
               "wishlist_remove": "remove an added wishlist entry"}[plan["action"]]
    return {"saved": True, "source_id": change_id, "expect": plan["expect"], "kind": "wishlist", "action": plan["action"],
            "profile": pid, "restored": actual, "sha256": result["sha256"], "revision": result["revision"],
            **({"removed_name": result["removed_name"]} if removing else {}), "summary": f"Undo change #{change_id}: {summary}"}
