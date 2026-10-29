"""Preview and save order corrections and pending component changes on Shopping.

Every action uses the command line's inventory operations. An opaque preview is
bound to its writer, listener and exact inventory revision; confirmation cannot
replace its operation or accidentally withdraw a newly renumbered check.
"""
import csv
import io
import threading
import time
import uuid

from decklab.lib import config, inventory
from decklab.lib.inventory import orders, rules

from . import common
from .carddata import _require_cards
from .common import DATABASE_DOWN, ApiError, _keys, _parse_body, _public
from .shopping import _editable_product
from .shopping_orders import MAX_ROWS, _authorize, _object, _preview, _rows, _strings, _tables, _text

CHANGED = "Shopping changed meanwhile. Refresh Shopping and preview your change again."
PREVIEW_LIFETIME = 1800
MAX_PREVIEWS = 64
_previews = {}
_preview_lock = threading.Lock()


def _row_text(value, label):
    """Retain CSV metadata within the body limit; the operation validates identities."""
    if not isinstance(value, str) or "\0" in value:
        raise ApiError(400, f"{label} must be text without NUL")
    return value


def _product_rows(data):
    """An optional replacement list, preserving each product's own CSV columns."""
    if "csv" in data:
        if "columns" in data or "rows" in data:
            raise ApiError(400, "Give either product csv or its columns and rows")
        value = data["csv"]
        if not isinstance(value, str) or "\0" in value:
            raise ApiError(400, "csv must be CSV text without NUL")
        reader = csv.DictReader(io.StringIO(value.lstrip("\ufeff"), newline=""), strict=True)
        columns, rows = reader.fieldnames or [], list(reader)
        if any(None in row or None in row.values() for row in rows):
            raise ApiError(400, "The product CSV rows must match its header")
    elif "columns" in data or "rows" in data:
        if "columns" not in data or "rows" not in data:
            raise ApiError(400, "Give the product's columns and rows together")
        columns, rows = data["columns"], data["rows"]
    else:
        return {}
    if (not isinstance(columns, list) or not 1 <= len(columns) <= 16
            or not all(isinstance(key, str) for key in columns) or len(columns) != len(set(columns))):
        raise ApiError(400, "The product needs its unique CSV columns")
    if isinstance(rows, list):
        for row in rows:
            _keys(_object(row, "Each product row"), columns)
    _require_cards()
    return {"columns": columns, "rows": _rows(rows, columns, text=_row_text)}


def _order_id(snapshot, operation):
    if operation.kind == "product.edit":
        return next(order.id for order in snapshot.orders for component in order.components
                    if component.kind == "product" and component.product_stem == operation.params["stem"])
    return operation.params["order"]


def _split_numbers(value, label):
    if (not isinstance(value, list) or len(value) > 100
            or any(isinstance(number, bool) or not isinstance(number, int) or number < 1
                   for number in value)):
        raise ApiError(400, f"{label} must be a list of positive check numbers")
    return value


def _split(data, order_id):
    _keys(data, ("profile", "expect", "order", "action", "component", "new_id", "take"),
          ("move_checks", "keep_checks"))
    params = {"order": order_id,
              "component": _text(data["component"], "component", blank=False, limit=100),
              "new_id": _text(data["new_id"], "new_id", blank=False, limit=100)}
    take = data["take"]
    if not isinstance(take, list) or not 1 <= len(take) <= MAX_ROWS:
        raise ApiError(400, f"take must list 1 to {MAX_ROWS} rows for the new part")
    params["take"] = []
    for item in take:
        _keys(_object(item, "Each split row"), ("row", "quantity"))
        for key in ("row", "quantity"):
            if isinstance(item[key], bool) or not isinstance(item[key], int) or item[key] < 1:
                raise ApiError(400, f"Each split {key} must be a positive whole number")
        params["take"].append({"row": item["row"], "quantity": item["quantity"]})
    for key in ("move_checks", "keep_checks"):
        params[key] = _split_numbers(data.get(key, []), key)
    return inventory.Op("order.split", params)


def _operation(data, before):
    order_id = _text(data["order"], "order", blank=False, limit=100)
    action = data["action"]
    if action in ("cancel", "remove"):
        from . import order_retirement
        return order_retirement.operation(data, before)
    if action == "split":
        return _split(data, order_id)
    if action == "record":
        _keys(data, ("profile", "expect", "order", "action", "values"))
        values = _object(data["values"], "values")
        _keys(values, (), ("seller", "ordered_on", "notes", "sources"))
        params = {key: _text(value, key, limit=200 if key == "seller" else 2000)
                  for key, value in values.items() if key != "sources"}
        if "sources" in values:
            params["sources"] = _strings(values["sources"], "sources")
        return inventory.Op("order.record", {"order": order_id, "values": params, "repo": str(config.REPO)})
    if action == "edit":
        _keys(data, ("profile", "expect", "order", "action", "component", "rows"))
        component_id = _text(data["component"], "component", blank=False, limit=100)
        _, component, _ = orders._pending_payload(before, order_id, component_id, "edited")
        columns = rules.TOKEN_FIELDS if component.kind == "tokens" else rules.FIELDS
        rows = data["rows"]
        if isinstance(rows, list):
            for row in rows:
                _keys(_object(row, "Each card row"), columns)
        rows = _rows(rows, columns, text=_row_text)
        _require_cards()
        return inventory.Op("order.edit", {"order": order_id, "component": component_id, "rows": rows})
    if action == "product":
        _keys(data, ("profile", "expect", "order", "action", "component", "values"),
              ("csv", "columns", "rows"))
        component_id = _text(data["component"], "component", blank=False, limit=100)
        _, component = orders._component(before, order_id, component_id)
        if component.kind != "product" or component.status != "pending":
            raise ApiError(400, "Only a pending product can be corrected here")
        values = _object(data["values"], "values")
        _keys(values, (), ("name", "format", "status", "notes"))
        params = {key: _text(value, key, limit=200 if key in ("name", "format") else 2000)
                  for key, value in values.items()}
        return inventory.Op("product.edit", {"stem": component.product_stem, "values": params,
                                             **_product_rows(data)})
    if action == "extra_copies":
        _keys(data, ("profile", "expect", "order", "action", "component", "undo"))
        component_id = _text(data["component"], "component", blank=False, limit=100)
        if not isinstance(data["undo"], bool):
            raise ApiError(400, "undo must be true or false")
        return inventory.Op("order.extra_copies", {"order": order_id, "component": component_id,
                                                  "undo": data["undo"]})
    if action != "checks":
        raise ApiError(400, "Choose a record, arrival-check, row, product, split, cancellation, removal or extra-copies change")
    _keys(data, ("profile", "expect", "order", "action", "component"), ("add", "withdraw", "target"))
    component_id = _text(data["component"], "component", blank=False, limit=100)
    params = {"order": order_id, "component": component_id}
    if ("add" in data) == ("withdraw" in data):
        raise ApiError(400, "Add or withdraw one arrival check at a time")
    if "add" in data:
        added = _strings(data["add"], "add")
        if len(added) != 1:
            raise ApiError(400, "Add one arrival check at a time")
        params["add"] = added[0]
        if "target" in data:
            target = _object(data["target"], "target")
            _keys(target, ("row", "payload_sha256"))
            params["target"] = dict(target)  # The operation validates exact row/payload proof under the lock.
    else:
        if "target" in data:
            raise ApiError(400, "Only a new arrival check may target a row")
        numbers = data["withdraw"]
        if (not isinstance(numbers, list) or len(numbers) != 1
                or isinstance(numbers[0], bool) or not isinstance(numbers[0], int) or numbers[0] < 1):
            raise ApiError(400, "Withdraw one check by its positive check number")
        params["withdraw"] = numbers[0]
    _, component = orders._component(before, order_id, component_id)
    if component.status != "pending":
        raise ApiError(400, "Change arrival checks here only while that part is pending. "
                            "Use Follow-ups for checks after delivery.")
    return inventory.Op("order.checks", params)


def _payload_component(snapshot, order, component_id):
    _, component = orders._component(snapshot, order.id, component_id)
    rows = []
    if component.kind in orders.PAYLOAD_FIELDS:
        fields = orders.PAYLOAD_FIELDS[component.kind]
        sheet = snapshot.payloads.get(component.path)
        if sheet is not None and sheet.readable:
            rows = [{key: row.text(key) for key in fields} for row in sheet.rows]
    return {"id": component.id, "kind": component.kind, "rows": rows,
            "extra_copies": component.id in rules.extra_copies(order.audit_notes)}


def _result(before, after, summary, operation):
    order_id = _order_id(before, operation)
    remaining = after.order(order_id)
    order = remaining or before.order(order_id)
    result = {"order": order.id, "summary": summary.text,
            "record": {"seller": order.seller, "ordered_on": order.ordered_on,
                       "notes": order.notes, "sources": list(order.sources or [])},
            "checks": [{"component": component.id, "checks": list(component.checks or [])}
                       for component in remaining.components] if remaining is not None else [],
            "changes": inventory.changed_labels(before, after),
            "tables": _tables(summary), "warnings": common._scrub((summary.extra or {}).get("warnings", []))}
    if operation.kind in ("order.cancel", "order.remove"):
        from . import order_retirement
        result.update(order_retirement.result(before, after, summary, operation))
    elif operation.kind in ("order.edit", "order.extra_copies"):
        result["component"] = _payload_component(after, order, operation.params["component"])
    elif operation.kind == "order.split":
        result["components"] = [_payload_component(after, order, operation.params[key])
                                for key in ("component", "new_id")]
        if result["components"][1]["extra_copies"]:
            result["warnings"].append(
                f"{operation.params['component']} stays marked as extra copies, and {operation.params['new_id']} "
                "is marked too. Unmark either part separately if it isn't extra copies.")
    elif operation.kind == "product.edit":
        component = next(component for component in order.components
                         if component.kind == "product" and component.product_stem == operation.params["stem"])
        result["component"] = {"id": component.id, "kind": component.kind,
                               "product": _editable_product(after, component),
                               "extra_copies": component.id in rules.extra_copies(order.audit_notes)}
    elif operation.kind == "order.checks" and operation.params.get("target") is not None:
        from . import arrival_checks
        _, component = orders._component(after, order.id, operation.params["component"])
        fields = orders.PAYLOAD_FIELDS[component.kind]
        rows = [{key: row.text(key) for key in fields} for row in after.payloads[component.path].rows]
        projected = arrival_checks.projection(component, rows, fields, True)
        index = len(component.checks) - 1
        proof = projected["check_targets"][index]
        if proof is None:
            raise inventory.Invalid("The new check's row association could not be confirmed")
        result["targeted_check"] = {"component": component.id, "check": index + 1, "text": component.checks[index],
                                    **proof, "payload_sha256": projected["check_targeting"]["payload_sha256"]}
    return result


def preview_order_change(body):
    data = _parse_body(body)
    actor = _authorize(data)
    _keys(data, ("profile", "expect", "order", "action"),
          ("values", "component", "add", "withdraw", "rows", "undo", "csv", "columns",
           "new_id", "take", "move_checks", "keep_checks", "reason", "restore_queue", "target"))
    _text(data["expect"], "expect", blank=False, limit=256)
    expect = data["expect"]
    try:
        before = inventory.current()
        if before.revision != expect:
            raise ApiError(409, CHANGED)
        operation = _operation(data, before)
        with inventory.pinned(before):
            after, summary = _preview(before, operation)
        result = _result(before, after, summary, operation)
    except ApiError:
        raise
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except inventory.Conflict:
        raise ApiError(409, CHANGED) from None
    except (inventory.Invalid, ValueError, OSError, csv.Error) as error:
        raise ApiError(400, f"The order change couldn't be previewed: {_public(error)}") from None
    token = uuid.uuid4().hex
    with _preview_lock:
        now = time.monotonic()
        for key, cached in list(_previews.items()):
            if not cached["busy"] and now - cached["created"] > PREVIEW_LIFETIME:
                del _previews[key]
        if len(_previews) >= MAX_PREVIEWS:
            available = next((key for key, value in _previews.items() if not value["busy"]), None)
            if available is None:
                raise ApiError(503, "Orders are being saved. Try preparing the preview again in a minute.")
            del _previews[available]
        _previews[token] = {"created": now, "actor": (actor.id, actor.via), "revision": expect,
                            "operation": operation, "busy": False}
    return {"preview": token, "revision": expect, **result}


def apply_order_change(body):
    data = _parse_body(body)
    actor = _authorize(data)
    _keys(data, ("profile", "preview"))
    token = data["preview"]
    if not isinstance(token, str) or len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
        raise ApiError(400, "Prepare an order-change preview first")
    with _preview_lock:
        cached = _previews.get(token)
        if (not cached or cached["actor"] != (actor.id, actor.via)
                or time.monotonic() - cached["created"] > PREVIEW_LIFETIME or cached["busy"]):
            raise ApiError(409, "This order-change preview is unavailable, expired or belongs to another person. "
                                "Prepare a new preview.")
        cached["busy"] = True
    try:
        from .saving import inventory_write_lock
        operation = cached["operation"]
        before = inventory.current()
        if before.revision != cached["revision"]:
            raise ApiError(409, CHANGED)
        with inventory_write_lock():
            verb = {"order.cancel": "Cancel part of", "order.remove": "Remove"}.get(operation.kind, "Correct")
            options = {"expected_revision": cached["revision"]}
            if operation.kind in ("order.cancel", "order.remove"):
                options["reason"] = operation.params["reason"]
            after, summary = inventory.apply(operation, actor, f"{verb} order {_order_id(before, operation)}",
                                              **options)
    except ApiError:
        raise
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except inventory.Conflict:
        raise ApiError(409, CHANGED) from None
    except (inventory.Invalid, ValueError, OSError, RuntimeError, csv.Error) as error:
        raise ApiError(400, f"The order change couldn't be saved: {_public(error)}") from None
    else:
        with _preview_lock:
            _previews.pop(token, None)
        return {"saved": True, "revision": after.revision, **_result(before, after, summary, operation)}
    finally:
        with _preview_lock:
            cached["busy"] = False
