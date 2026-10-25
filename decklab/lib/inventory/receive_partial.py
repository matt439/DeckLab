"""Partition a receipt inside its existing inventory operation; no independent write.

Take indexes refer to the complete validated submitted row order. The original
component keeps its pending remainder and checks; a collision-free component is
created for the arrived copies and immediately received by receive.py.
"""
from pathlib import PurePosixPath

from decklab.lib.state import Invalid

from . import orders, rules
from .model import Order


def _take(rows, take):
    if not isinstance(take, (list, tuple)) or not take:
        raise Invalid("Select at least one arrived row with a positive quantity.")
    quantities = [orders._quantity(row.get("quantity"), "The complete component") for row in rows]
    chosen, seen = [], set()
    for item in take:
        if not isinstance(item, dict) or not set(item) <= {"row", "quantity"}:
            raise Invalid("Each arrived selection needs its row number and optional quantity.")
        row = item.get("row")
        if isinstance(row, bool) or not isinstance(row, int) or not 1 <= row <= len(rows) or row in seen:
            raise Invalid("Arrived row numbers must be distinct and belong to the complete component.")
        seen.add(row)
        if "quantity" in item and type(item["quantity"]) is not int:
            raise Invalid(f"Arrived row {row}: quantity must be a positive integer.")
        quantity = quantities[row - 1] if "quantity" not in item else orders._quantity(
            item["quantity"], f"Arrived row {row}")
        if quantity > quantities[row - 1]:
            raise Invalid(f"Arrived row {row} has only {quantities[row - 1]} copies, not {quantity}.")
        chosen.append({"row": row, "quantity": quantity})
    return chosen, sum(item["quantity"] for item in chosen), sum(quantities)


def _new_id(inv, order, component):
    taken = {part.id for part in order.components}
    number = 1
    while True:
        candidate = f"{component.id}-received-{number}"
        filename = f"{PurePosixPath(component.file_name).stem}-{candidate}.csv"
        if len(filename) > 255:
            raise Invalid("This component's file name is too long to split for a partial receipt.")
        if candidate not in taken and not orders._file_taken(inv, component.kind, filename):
            return candidate
        number += 1


def prepare(inv, order_id, component_id, rows, take):
    """Return (snapshot, received Component, assignment) after a pure in-operation split."""
    order, component = orders._component(inv, order_id, component_id)
    if component.kind == "product":
        raise Invalid("Products must be received whole; select their component instead of individual rows.")
    selected, arrived, total = _take(rows, take)
    if arrived == total:
        return inv, component, {"source": component_id, "received": component_id, "pending": None,
                                "received_quantity": arrived, "pending_quantity": 0}
    received_id = _new_id(inv, order, component)
    inv, _ = orders.split_order(inv, order=order_id, component=component_id, new_id=received_id, take=selected,
                               _arrived_first=True)
    _, received = orders._component(inv, order_id, received_id)
    return inv, received, {"source": component_id, "received": received_id, "pending": component_id,
                          "received_quantity": arrived, "pending_quantity": total - arrived}


def acknowledge_remainders(before, after, order_id, assignments):
    """Explain a new duplicate-arrival warning caused by this receipt's own copies.

    An already ambiguous original stays unacknowledged. Only a pending cards
    remainder covered by the old collection and the arrived part, with matching
    arrived printings, can be marked as additional copies.
    """
    original = {part.id: part for part in before.order(order_id).components}
    partial = [item for item in assignments if item["pending"] and original[item["source"]].kind == "cards"]
    if not partial:
        return after, []
    from decklab.lib.pool import read_printings

    collection = before.collection()
    owned = read_printings(collection) if collection.exists else {}
    order = after.order(order_id)
    current = {part.id: part for part in order.components}
    marked, added = list(rules.extra_copies(order.audit_notes)), []

    def covered(printings, available):
        return bool(printings) and all(available.get(key, 0) >= quantity for key, quantity in printings.items())

    for item in partial:
        source, pending, arrived = original[item["source"]], current[item["pending"]], current[item["received"]]
        if source.kind != "cards" or pending.id in marked:
            continue
        initial = read_printings(before.payloads[source.path])
        remaining = read_printings(after.payloads[pending.path])
        if covered(initial, owned):
            continue
        received = read_printings(after.payloads[arrived.path])
        explained = {key: owned.get(key, 0) + received.get(key, 0) for key in remaining}
        if any(received.get(key, 0) for key in remaining) and covered(remaining, explained):
            marked.append(pending.id)
            added.append(pending.id)
    if added:
        record = order.record()
        record["audit_notes"] = rules.with_extra_copies(order.audit_notes, marked)
        after = after.with_order(Order(order.file, record))
    return after, added
