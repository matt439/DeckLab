"""Record placed orders from Shopping, using the command line's order.add operation.

POST /api/shopping/order/preview takes profile, expect (Shopping's exact inventory
revision), record, and optional cards/tokens/product/fulfils/extra_copies. Cards and
tokens take rows or csv and checks; a product takes columns/rows or csv plus its
metadata. Fulfilled queue rows are numbered {row, quantity}; omitted quantity means
the whole row. No prices, unchecked imports or forced table failures are accepted.

POST /api/shopping/order/apply takes profile and the opaque preview token. The
bounded, thirty-minute cache binds the validated operation to its writer and
listener. A successful apply consumes it and uses the exact preview revision.
"""
import csv
import io
import threading
import time
import uuid

from decklab.lib import cards, config, decks, inventory
from decklab.lib.inventory import changes, orders, refresh, rules

from . import common, guard
from .carddata import _require_cards
from .common import DATABASE_DOWN, ApiError, _CONTROL_RE, _keys, _parse_body, _public
from .settings import _web_actor, _writer

CHANGED = "Shopping changed meanwhile. Reload it and prepare a new order preview."
PREVIEW_LIFETIME = 1800
MAX_PREVIEWS = 64
MAX_ROWS = 500
_previews = {}
_preview_lock = threading.Lock()


def _text(value, label, *, blank=True, limit=2000):
    if (not isinstance(value, str) or len(value) > limit or _CONTROL_RE.search(value)
            or not blank and not value.strip()):
        raise ApiError(400, f"{label} must be single-line text of at most {limit} characters")
    return value.strip()


def _quantity(value):
    if (isinstance(value, bool) or not isinstance(value, (str, int))
            or not str(value).isascii() or not str(value).isdigit()
            or len(str(value)) > 9 or int(value) < 1):
        raise ApiError(400, "quantity must be a positive whole number")
    return str(value)


def _object(value, label):
    if not isinstance(value, dict):
        raise ApiError(400, f"{label} must be an object")
    return value


def _strings(value, label):
    if not isinstance(value, list) or len(value) > 100:
        raise ApiError(400, f"{label} must be a list of at most 100 text entries")
    return [_text(item, label, blank=False) for item in value]


def _rows(value, columns, *, text=_text):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_ROWS:
        raise ApiError(400, f"A component must have 1 to {MAX_ROWS} card rows")
    result = []
    for row in value:
        _object(row, "Each card row")
        _keys(row, (), columns)
        result.append({key: _quantity(row[key]) if key == "quantity" and key in row
                       else text(row.get(key, ""), key) for key in columns})
    return result


def _component(value, kind):
    _object(value, f"The {kind} component")
    product = kind == "product"
    _keys(value, (), ("rows", "csv", "checks", "id", "columns", "stem", "name", "format", "status", "notes")
          if product else ("rows", "csv", "checks", "id"))
    if ("csv" in value) == ("rows" in value):
        raise ApiError(400, f"Give either rows or csv for the {kind} component")
    result = {key: _text(value[key], key, blank=False) for key in ("id", "stem", "name", "format", "status")
              if key in value}
    if "notes" in value:
        result["notes"] = _text(value["notes"], "notes")
    result["checks"] = _strings(value.get("checks", []), "checks")
    columns = rules.TOKEN_FIELDS if kind == "tokens" else rules.FIELDS
    if "csv" in value:
        text = value["csv"]
        if not isinstance(text, str) or "\0" in text:
            raise ApiError(400, "csv must be CSV text")
        stream = io.StringIO(text.lstrip("\ufeff"), newline="")
        if product:
            reader = csv.DictReader(stream, strict=True)
            columns, given = reader.fieldnames or [], list(reader)
            if not columns or len(columns) != len(set(columns)) or any(
                    None in row or None in row.values() for row in given):
                raise ApiError(400, "The product CSV needs unique columns and rows matching its header")
        else:
            given = (rules.parse_csv(stream, columns, "Order tokens") if kind == "tokens"
                     else rules.parse_cards(stream, "Order cards"))
    else:
        given = value["rows"]
        if product:
            columns = value.get("columns")
            if (not isinstance(columns, list) or not columns or len(columns) > 16
                    or not all(isinstance(key, str) for key in columns) or len(columns) != len(set(columns))):
                raise ApiError(400, "The product needs its unique CSV columns")
    result["rows"] = _rows(given, columns)
    if kind != "tokens" and "name" in columns:
        for row in result["rows"]:
            row["name"] = cards.resolve(row["name"]) or row["name"]
    if product:
        result["columns"] = columns
    return result


def _operation(data):
    record = _object(data["record"], "record")
    _keys(record, ("id",), ("seller", "ordered_on", "sources", "notes"))
    fields = {key: _text(record[key], key, blank=key != "id")
              for key in ("id", "seller", "ordered_on", "notes") if key in record}
    fields["sources"] = _strings(record.get("sources", []), "sources")
    params = {"record": fields, "repo": str(config.REPO)}
    for kind in ("cards", "tokens", "product"):
        if kind in data:
            params[kind] = _component(data[kind], kind)
    fulfilled = data.get("fulfils", [])
    if not isinstance(fulfilled, list) or len(fulfilled) > MAX_ROWS:
        raise ApiError(400, "fulfils must list the purchase queue rows")
    params["fulfils"] = []
    seen = set()
    for item in fulfilled:
        _object(item, "Each fulfilled queue row")
        _keys(item, ("row",), ("quantity",))
        row = item["row"]
        if not isinstance(row, int) or isinstance(row, bool) or row < 1 or row in seen:
            raise ApiError(400, "Select each purchase queue row once by its positive row number")
        seen.add(row)
        quantity = None if item.get("quantity") is None else int(_quantity(item["quantity"]))
        params["fulfils"].append({"select": f"#{row}", "quantity": quantity})
    params["extra_copies"] = _strings(data.get("extra_copies", []), "extra_copies")
    return inventory.Op("order.add", params)


def _tables(summary):
    return (summary.extra or {}).get("tables") or {"written": [], "skipped": [], "error": None}


def _preview(before, operation):
    """The same refusal as inv_orders._refresh_refusal, using this one preview.

    An existing table failure may be repaired by the order. Refuse only a failure
    introduced by it; the CLI permits an existing failure and reports it clearly.
    """
    after, summary = inventory.preview(operation)
    error = _tables(summary).get("error")
    if error and error != inventory.DECK_SAVES_PAUSED:
        try:
            with inventory.pinned(before):
                refresh.plan_refresh(refresh.spaces_of(changes.changed_paths(before, after)))
        except (OSError, ValueError, RuntimeError, decks.DeckFileError, inventory.StateError):
            pass
        else:
            raise ApiError(400, "After this order the deck tables couldn't be refreshed: " + _public(error))
    return after, summary


def _result(before, after, summary, operation):
    reductions = []
    for item in operation.params["fulfils"]:
        row = before.watchlist.rows[int(item["select"][1:]) - 1]
        amount = item["quantity"] if item["quantity"] is not None else row.qty
        reductions.append({"name": row.name, "for": row.text("for"), "quantity": amount,
                           "left": row.qty - amount})
    order = after.order(operation.params["record"]["id"])
    return {"order": order.id, "summary": summary.text, "counts": dict(summary.counts),
            "checks": [{"component": c.id, "checks": list(c.checks or [])} for c in order.components],
            "watchlist_reduced": reductions, "changes": inventory.changed_labels(before, after),
            "tables": _tables(summary), "warnings": common._scrub((summary.extra or {}).get("warnings", []))}


def _authorize(data):
    profile = _writer(data)
    guard.require(profile, "orders.edit")
    guard.require_sees_home_records(profile)
    return _web_actor(profile)


def preview_order(body):
    data = _parse_body(body)
    _keys(data, ("profile", "expect", "record"), ("cards", "tokens", "product", "fulfils", "extra_copies"))
    actor = _authorize(data)
    _text(data["expect"], "expect", blank=False, limit=256)
    expect = data["expect"]
    try:
        before = inventory.current()
        if before.revision != expect:
            raise ApiError(409, CHANGED)
        _require_cards()
        operation = _operation(data)
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
        raise ApiError(400, f"The order couldn't be previewed: {_public(error)}") from None
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


def apply_order(body):
    data = _parse_body(body)
    _keys(data, ("profile", "preview"))
    actor = _authorize(data)
    token = data["preview"]
    if not isinstance(token, str) or len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
        raise ApiError(400, "Prepare an order preview first")
    with _preview_lock:
        cached = _previews.get(token)
        if (not cached or cached["actor"] != (actor.id, actor.via)
                or time.monotonic() - cached["created"] > PREVIEW_LIFETIME or cached["busy"]):
            raise ApiError(409, "This order preview is unavailable, expired or belongs to another person. "
                                "Prepare a new preview.")
        cached["busy"] = True
    try:
        from .saving import inventory_write_lock
        operation = cached["operation"]
        before = inventory.current()
        if before.revision != cached["revision"]:
            raise ApiError(409, CHANGED)
        with inventory_write_lock():
            after, summary = inventory.apply(operation, actor, f"Record placed order {operation.params['record']['id']}",
                                              expected_revision=cached["revision"])
    except ApiError:
        raise
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except inventory.Conflict:
        raise ApiError(409, CHANGED) from None
    except (inventory.Invalid, ValueError, OSError, RuntimeError) as error:
        raise ApiError(400, f"The order couldn't be saved: {_public(error)}") from None
    else:
        with _preview_lock:
            _previews.pop(token, None)
        return {"saved": True, "revision": after.revision, **_result(before, after, summary, operation)}
    finally:
        with _preview_lock:
            cached["busy"] = False
