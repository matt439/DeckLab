"""Corrections to an order's record fields, registered by inventory.orders.

These fields do not change any component or its cards, so correcting them never
refreshes deck tables. The whole record is copied to retain provenance and any
metadata the writer does not understand.
"""
from decklab.lib.state import Invalid

from . import Summary, register
from .model import Order
from .orders import _order, _record_fields

FIELDS = ("seller", "ordered_on", "notes", "sources")


@register("order.record")
def record_order(inv, *, order, values, repo="."):
    """Set supplied record fields only, for an order in any receipt status.

    sources replaces the entire source list (an empty list clears it); deck source
    paths keep their historical spelling and are checked against this snapshot.
    """
    if not isinstance(values, dict) or not values or not set(values) <= set(FIELDS):
        raise Invalid("Set one or more of the order's record fields: " + ", ".join(FIELDS))
    original = _order(inv, order)
    record = original.record()
    record.update(values)
    checked = _record_fields(record, repo, inv)
    if "ordered_on" in values and checked["ordered_on"]:
        for component in original.components:
            if component.received_on and component.received_on < checked["ordered_on"]:
                raise Invalid(f"Order {order}'s {component.id}: receipt date conflicts with status or order date")
    changed = [key for key in FIELDS if key in values and original.data.get(key) != checked[key]]
    if not changed:
        return inv, Summary(f"Order {order}: nothing to change")
    for key in values:
        record[key] = checked[key]
    return inv.with_order(Order(original.file, record)), Summary(
        f"Changed order {order}: " + ", ".join(changed), extra={"fields": changed})
