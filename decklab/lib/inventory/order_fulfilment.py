"""Explicit watchlist intent fulfilled by an order, without a schema change.

The reserved audit-notes marker holds only intent and physical allocations, never market
references. Absence means unknown history. All helpers are pure; callers save the returned
order with the surrounding inventory operation. Imports of orders are delayed to avoid its
operation-registration cycle.
"""
import copy
import json
from collections import Counter
from pathlib import Path

from decklab.lib import purchases
from decklab.lib.state import Invalid

from . import rules
from .model import QUEUE_FIELDS, Order

PREFIX = "[[Deck Lab fulfilment v1: "
FAMILY = "[[Deck Lab fulfilment "
INTENT_FIELDS = ("name", "set", "collector_number", "finish", "for", "printing", "notes", "state", "source")
MARKET_FIELDS = ("listed_aud", "listed_at", "in_stock", "checked")


def _bad():
    return Invalid("The order's fulfilment history cannot be read safely; correct its reserved ledger before changing it")


def _positive(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _bad()
    return value


def _pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise _bad()
        out[key] = value
    return out


def _intent(value):
    if not isinstance(value, dict) or set(value) != set(INTENT_FIELDS):
        raise _bad()
    if not all(isinstance(v, str) for v in value.values()) or not value["name"].strip():
        raise _bad()
    if value["printing"] not in ("any", "exact") or value["state"] not in purchases.STATES:
        raise _bad()
    if value["finish"] not in ("", "nonfoil", "foil", "etched"):
        raise _bad()
    if value["printing"] == "exact" and not all(value[k] for k in ("set", "collector_number", "finish")):
        raise _bad()
    return value


def _row(value, kind):
    if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
        raise _bad()
    fields = set(rules.TOKEN_FIELDS if kind == "tokens" else rules.FIELDS) - {"quantity"}
    if kind == "product":
        required = set(rules.REQUIRED) - {"quantity"}
        if not required <= set(value) <= fields | rules.PRODUCT_FIELDS:
            raise _bad()
    elif set(value) != fields:
        raise _bad()
    if not value.get("front" if kind == "tokens" else "name", "").strip():
        raise _bad()
    return value


def _checked(order, ledger):
    if not isinstance(ledger, dict) or set(ledger) != {"claims", "consumed", "warnings"}:
        raise _bad()
    if not all(isinstance(ledger[k], list) for k in ledger):
        raise _bad()
    components = {c.id: c.kind for c in order.components}
    consumed = ledger["consumed"]
    if (not all(isinstance(c, str) and c in components for c in consumed)
            or len(consumed) != len(set(consumed))
            or not all(isinstance(w, str) for w in ledger["warnings"])):
        raise _bad()
    for claim in ledger["claims"]:
        if not isinstance(claim, dict) or set(claim) != {"component", "kind", "row", "quantity", "intent"}:
            raise _bad()
        cid, kind = claim["component"], claim["kind"]
        if (not isinstance(cid, str) or cid not in components or cid in consumed
                or kind not in ("cards", "tokens", "product") or components[cid] != kind):
            raise _bad()
        _positive(claim["quantity"])
        _row(claim["row"], kind)
        _intent(claim["intent"])
    return copy.deepcopy(ledger)


def _parse_marker(notes):
    if notes is None:
        return None
    if not isinstance(notes, str):
        raise _bad()
    start = notes.find(FAMILY)
    if start < 0:
        return None
    if not notes.startswith(PREFIX, start):
        raise _bad()
    try:
        ledger, end = json.JSONDecoder(object_pairs_hook=_pairs).raw_decode(notes, start + len(PREFIX))
    except (ValueError, TypeError):
        raise _bad() from None
    if not notes.startswith("]]", end) or FAMILY in notes[end + 2:]:
        raise _bad()
    return ledger, start, end + 2


def audit_span(notes):
    """Reserved marker's span for prose helpers; quoted marker text inside its JSON is data."""
    marked = _parse_marker(notes)
    return None if marked is None else (marked[1], marked[2])


def _marked(order):
    return _parse_marker(order.audit_notes)


def read(order):
    """The validated ledger, or None for an old order with unknown fulfilment history."""
    marked = _marked(order)
    return None if marked is None else _checked(order, marked[0])


def write(order, ledger):
    """Replace just the reserved marker, retaining human prose/extra-copy acknowledgements."""
    ledger = _checked(order, ledger)
    notes = order.audit_notes or ""
    marked = _marked(order)
    if marked is not None:
        _checked(order, marked[0])
    marker = PREFIX + json.dumps(ledger, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "]]"
    data = order.record()
    data["audit_notes"] = (notes[:marked[1]] + marker + notes[marked[2]:] if marked is not None
                           else marker + (" " + notes if notes else ""))
    return Order(order.file, data)


def _physical(row):
    return {k: str(v if v is not None else "") for k, v in row.items() if k != "quantity"}


def _key(row):
    return tuple(sorted(row.items()))


def _quantity(row):
    try:
        value = row["quantity"]
        if isinstance(value, bool) or not str(value).strip().isdigit() or int(value) < 1:
            raise ValueError()
        return int(value)
    except (KeyError, TypeError, ValueError):
        raise _bad() from None


def _slots(rows, component, kind):
    slots = []
    for row in rows:
        physical = _physical(row)
        _row(physical, kind)
        slots.append({"component": component, "kind": kind, "row": physical, "left": _quantity(row)})
    return slots


def _component_rows(inv, component):
    if component.kind == "product":
        product = inv.product(component.product_stem)
        if product is None or product.error is not None:
            raise _bad()
        return [{k: row.text(k) for k in product.columns} for row in product.items]
    sheet = inv.payloads.get(component.path)
    if sheet is None or not sheet.readable:
        raise _bad()
    fields = rules.TOKEN_FIELDS if component.kind == "tokens" else rules.FIELDS
    return [{k: row.text(k) for k in fields} for row in sheet.rows]


def _names(row, kind):
    if kind != "tokens":
        return {row["name"]}
    return {row["front"]} | ({f"{row['front']} // {row['back']}"} if row["back"] else set())


def _matches(intent, slot):
    row = slot["row"]
    if intent["name"] not in _names(row, slot["kind"]):
        return False
    if intent["printing"] == "any":
        return True
    numbers = ({row["front_collector_number"], row["back_collector_number"]}
               if slot["kind"] == "tokens" else {row["collector_number"]})
    return (intent["set"] == row["set"] and intent["finish"] == row["finish"]
            and intent["collector_number"] in numbers)


def _take(claim, slots, accepts):
    """Allocate up to a claim's quantity against one globally shared set of capacities."""
    left, made = claim["quantity"], []
    for slot in slots:
        if not slot["left"] or not accepts(slot):
            continue
        qty = min(left, slot["left"])
        made.append({"component": slot["component"], "kind": slot["kind"], "row": slot["row"],
                     "quantity": qty, "intent": copy.deepcopy(claim["intent"])})
        slot["left"] -= qty
        left -= qty
        if not left:
            break
    return made, left


def record(before, inv, order, fulfils):
    """Record allocations after installing new components, before reducing before's watchlist.

    Exact requests reserve physical units first. Token front and paired-face names draw from
    the same capacities, so one physical card can never fulfil both aliases.
    """
    from .orders import _quantity as quantity, _queue_dicts, one_queue_row
    if read(order) is not None:
        raise Invalid("A new order cannot supply its own fulfilment history")
    ledger = {"claims": [], "consumed": [], "warnings": []}
    if not fulfils:
        return write(order, ledger)
    rows = _queue_dicts(before)
    requests = []
    for item in fulfils:
        if not isinstance(item, dict):
            raise Invalid("Each fulfilled watchlist row needs a selector and a quantity")
        row = rows[one_queue_row(rows, item.get("select"))]
        have = quantity(row["quantity"], f"watchlist: {row['name']}")
        qty = have if item.get("quantity") is None else quantity(item["quantity"], f"watchlist: {row['name']}")
        if qty > have or have < 1:
            raise Invalid(f"watchlist: {row['name']}: only {have} queued, not {qty}")
        requests.append({"quantity": qty, "intent": _intent({k: row[k] for k in INTENT_FIELDS})})
        row["quantity"] = str(have - qty)
    slots = []
    for component in order.components:
        slots += _slots(_component_rows(inv, component), component.id, component.kind)
    for request in sorted(requests, key=lambda r: r["intent"]["printing"] != "exact"):
        made, left = _take(request, slots, lambda s: _matches(request["intent"], s))
        if left:
            raise Invalid(f"watchlist: {request['intent']['name']}: the order has too few distinct physical copies "
                          "for the fulfilled requests (exact printings must match)")
        ledger["claims"] += made
    return write(order, ledger)


def _capacity(claims, rows, kind):
    have = Counter()
    for row in rows:
        have[_key(_physical(row))] += _quantity(row)
    used = Counter()
    for claim in claims:
        if claim["kind"] != kind:
            raise _bad()
        used[_key(claim["row"])] += claim["quantity"]
    if any(qty > have[key] for key, qty in used.items()):
        raise _bad()


def split(order, component, new_component, kept_rows, moved_rows, *, moved_first=False):
    """Partition claims across exact physical rows, conserving every unit.

    Explicit splits allocate kept copies first. An atomic partial receipt opts into moved
    copies first so the arrived copies satisfy recorded intent before the pending remainder.
    """
    ledger = read(order)
    if ledger is None:
        return order
    claims = [c for c in ledger["claims"] if c["component"] == component]
    if not claims:
        return order
    kind = claims[0]["kind"]
    _capacity(claims, [*kept_rows, *moved_rows], kind)
    kept = _slots(kept_rows, component, kind)
    moved = _slots(moved_rows, new_component, kind)
    slots = moved + kept if moved_first else kept + moved
    made = []
    for claim in claims:
        allocated, left = _take(claim, slots, lambda s: s["row"] == claim["row"])
        if left:
            raise _bad()
        made += allocated
    ledger["claims"] = [c for c in ledger["claims"] if c["component"] != component] + made
    return write(order, ledger)


def edit(order, component, old_rows, new_rows):
    """Remap corrected/reordered rows, keeping exact physical matches before name matches.

    The original purchase intent survives corrections. Token name corrections fall back to
    remaining physical capacities with a warning. Products cannot be split, so their original
    physical allocation remains historical evidence even when their corrected list is smaller;
    whole-component cancellation can still offer the intent explicitly fulfilled at ordering.
    """
    ledger = read(order)
    if ledger is None:
        return order
    claims = [c for c in ledger["claims"] if c["component"] == component]
    if not claims:
        return order
    kind = claims[0]["kind"]
    if kind == "product":
        if old_rows != new_rows:
            warning = (f"{component}: its product list was corrected; any restoration offers the original "
                       "recorded purchase intent, which may differ from the corrected cards")
            if warning not in ledger["warnings"]:
                ledger["warnings"].append(warning)
        return write(order, ledger)
    _capacity(claims, old_rows, kind)
    slots = _slots(new_rows, component, kind)
    made, remaining = [], []
    for claim in claims:
        allocated, left = _take(claim, slots, lambda s: s["row"] == claim["row"])
        made += allocated
        if left:
            remaining.append({**claim, "quantity": left})
    for claim in remaining:
        names = _names(claim["row"], kind)
        allocated, left = _take(claim, slots, lambda s: bool(names & _names(s["row"], kind)))
        made += allocated
        if left and kind == "tokens":
            fallback, left = _take({**claim, "quantity": left}, slots, lambda s: True)
            made += fallback
            warning = (f"{component}: token names were corrected; any restoration offers the original "
                       "recorded purchase intent, which may differ from the corrected tokens")
            if warning not in ledger["warnings"]:
                ledger["warnings"].append(warning)
        if left:
            # Cards keep name totals and tokens keep total physical quantities. Insufficient
            # capacity here means a caller bypassed those operation checks; refuse the edit.
            raise _bad()
    ledger["claims"] = [c for c in ledger["claims"] if c["component"] != component] + made
    return write(order, ledger)


def _offered(claims):
    from .orders import queue_key
    rows = {}
    for claim in claims:
        row = {k: "" for k in QUEUE_FIELDS}
        row.update(claim["intent"])
        key = queue_key(row)
        if key not in rows:
            row["quantity"] = "0"
            rows[key] = row
        rows[key]["quantity"] = str(int(rows[key]["quantity"]) + claim["quantity"])
    return list(rows.values())


def restore(inv, order, component_ids, restore=True, *, repo="."):
    """Offer/restore pending recorded intent once, consuming selected claims even if declined.

    Return (inventory, updated_order, {known, offered, restored, warnings}). Old orders remain
    unknown; no quantities are inferred from their card names or their order notes.
    """
    from .orders import _queue_dicts, _with_queue, queue_key, queue_row
    if not isinstance(restore, bool):
        raise Invalid("Choose whether to restore the recorded watchlist intent")
    if isinstance(component_ids, str):
        component_ids = [component_ids]
    if not isinstance(component_ids, (list, tuple, set)) or not all(isinstance(c, str) for c in component_ids):
        raise Invalid("Name the components whose fulfilled intent is being withdrawn")
    selected = set(component_ids)
    components = {c.id: c for c in order.components}
    if not selected <= set(components):
        raise Invalid("A component whose intent was requested does not belong to this order")
    ledger = read(order)
    info = {"known": ledger is not None, "offered": [], "restored": [], "warnings": []}
    if ledger is None:
        info["warnings"].append("This older order has no recorded watchlist fulfilment; restore any intended purchases manually")
        return inv, order, info
    claims = [c for c in ledger["claims"] if c["component"] in selected
              and components[c["component"]].status == "pending"]
    for cid in selected:
        matching = [c for c in claims if c["component"] == cid]
        if matching and components[cid].kind != "product":
            _capacity(matching, _component_rows(inv, components[cid]), components[cid].kind)
    offered = _offered(claims)
    info["offered"] = copy.deepcopy(offered)
    info["warnings"] = list(ledger["warnings"])
    if restore and offered:
        if not inv.watchlist.readable or inv.watchlist.problems or inv.watchlist.strict_error:
            raise Invalid("The watchlist cannot be rewritten safely until its existing rows are corrected")
        rows = _queue_dicts(inv)
        existing = {queue_key(row): row for row in rows}
        for captured in offered:
            key = queue_key(captured)
            if key in existing:
                current = existing[key]
                current["quantity"] = str(_quantity(current) + int(captured["quantity"]))
            else:
                current = dict(captured)
                if current["source"] and not purchases.source_exists(Path(repo), current["source"], inv=inv):
                    info["warnings"].append(f"{current['name']}: its original source no longer exists; restored without that source")
                    current["source"] = ""
                queue_row(current, repo, inv)
                rows.append(current)
                existing[key] = current
            info["restored"].append({**current, "quantity": captured["quantity"]})
        inv = _with_queue(inv, rows)
    ledger["claims"] = [c for c in ledger["claims"] if c["component"] not in selected]
    ledger["consumed"] = list(dict.fromkeys([*ledger["consumed"], *sorted(selected)]))
    order = write(order, ledger)
    return inv, order, info
