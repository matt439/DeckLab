"""Home-admin price reference/market-target reviews through the existing queue endpoint."""
import re
import threading
import time
import uuid

from decklab.lib import config, inventory, shop_reference_source
from decklab.lib.inventory import ops_shop_references as ops

from . import guard
from .carddata import _require_cards
from .common import DATABASE_DOWN, ApiError, _keys, _public
from .settings import _web_actor, _writer

ACTIONS = ("reference_preview", "reference_apply", "target_preview", "target_apply")
LIFETIME = 1800
MAX_PREVIEWS = 64
_previews = {}
_lock = threading.Lock()


def handle(data):
    profile = _writer(data)
    guard.require(profile, "orders.edit")
    guard.require_sees_home_records(profile)
    actor = _web_actor(profile)
    action = data["action"]
    return _apply(data, actor) if action.endswith("_apply") else _preview(data, actor)


def _preview(data, actor):
    _keys(data, ("profile", "action", "expect", "requests"))
    expect = data["expect"]
    if not isinstance(expect, str) or not expect or len(expect) > 256 or "\0" in expect:
        raise ApiError(400, "Use the exact queue revision from Shopping")
    kind = "reference" if data["action"] == "reference_preview" else "target"
    if kind == "reference":
        _require_cards()
    requests = data["requests"]
    if kind == "target":
        if not isinstance(requests, list) or not 1 <= len(requests) <= ops.MAX_ROWS:
            raise ApiError(400, f"Review 1 to {ops.MAX_ROWS} targets at once")
        current = inventory.current()
        if current.revision != expect:
            raise ApiError(409, ops.CHANGED)
        try:
            source = shop_reference_source.context(fresh=True)
            rows = ops.rows_of(current)
            supplied = []
            for request in requests:
                if not isinstance(request, dict):
                    raise ApiError(400, "Each target needs a row and an AUD unit amount")
                _keys(request, ("row", "value"), ("receipt",))
                number = request["row"]
                if type(number) is not int or not 1 <= number <= len(rows):
                    raise ApiError(409, ops.CHANGED)
                digest = shop_reference_source.receipt(rows[number - 1], source)
                if "receipt" in request and request["receipt"] != digest:
                    raise ApiError(409, ops.SOURCE_CHANGED)
                supplied.append({**request, "receipt": digest})
            requests = supplied
        except ValueError as error:
            raise ApiError(409, _public(error)) from None
    operation = inventory.Op("watchlist.reference_review", {"expect": expect, "requests": requests,
                              "kind": kind, "repo": str(config.REPO)})
    try:
        _, summary = inventory.preview(operation, refresh=False)
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except inventory.Conflict as error:
        raise ApiError(409, _public(error)) from None
    except (inventory.Invalid, ValueError, TypeError) as error:
        raise ApiError(400, _public(error)) from None
    changed = summary.counts["changed"]
    result = {"preview": None, "changes": summary.extra["review"], "changed": changed, "kind": kind}
    if not changed:
        return result
    token, now = uuid.uuid4().hex, time.monotonic()
    with _lock:
        for key, old in list(_previews.items()):
            if not old["busy"] and now - old["at"] > LIFETIME:
                del _previews[key]
        if len(_previews) >= MAX_PREVIEWS:
            removable = next((key for key, old in _previews.items() if not old["busy"]), None)
            if removable is None:
                raise ApiError(503, "Price reviews are being saved. Try again shortly.")
            del _previews[removable]
        _previews[token] = {"actor": (actor.id, actor.via), "at": now, "busy": False, "operation": operation,
                            "message": summary.text, "revision": expect, "kind": kind}
    result["preview"] = token
    return result


def _apply(data, actor):
    _keys(data, ("profile", "action", "preview"))
    token = data["preview"]
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ApiError(400, "Prepare a price review first")
    kind = "reference" if data["action"] == "reference_apply" else "target"
    with _lock:
        saved = _previews.get(token)
        if (saved is None or saved["actor"] != (actor.id, actor.via) or saved["kind"] != kind
                or saved["busy"] or time.monotonic() - saved["at"] > LIFETIME):
            raise ApiError(409, "This price review is unavailable or expired. Prepare a new review.")
        saved["busy"] = True
    try:
        if kind == "reference":
            _require_cards()
        from .saving import inventory_write_lock
        with inventory_write_lock():
            after, summary = inventory.apply(saved["operation"], actor, saved["message"],
                                              expected_revision=saved["revision"], refresh=False)
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except inventory.Conflict as error:
        raise ApiError(409, _public(error)) from None
    except (inventory.Invalid, ValueError) as error:
        raise ApiError(400, _public(error)) from None
    else:
        with _lock:
            _previews.pop(token, None)
        return {"saved": True, "revision": after.revision, "changed": summary.counts["changed"],
                "changes": summary.extra["review"]}
    finally:
        with _lock:
            saved["busy"] = False
