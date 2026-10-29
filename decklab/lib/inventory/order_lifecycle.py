"""Cancel pending components and remove mistaken orders through one inventory operation.

Cancelled products retain their reference card list and status for order history, but
are excluded from incoming supply and the deck library. Removing an unreceived order
also removes its payloads/products. Queue intent is restored only from the recorded
fulfilment ledger; historical orders never acquire inferred purchase requests.
"""
from decklab.lib import purchases
from decklab.lib.state import Invalid

from . import Summary, paths, register
from .model import Order
from .orders import INCOMING, _component, _done, _invalid, _order


def _reason(value, order):
    from .order_fulfilment import FAMILY
    try:
        purchases._text(value, f"{order}.json: reason", blank=False)
    except ValueError as error:
        raise _invalid(error) from None
    if FAMILY in value:
        raise Invalid("The reason contains Deck Lab's reserved fulfilment marker; enter the reason as plain text.")
    return value.strip()


def _product(inv, order, component, removing=False):
    """Refuse receipt loss or deleting a product another component also names."""
    product = inv.product(component.product_stem)
    if product is None:
        raise Invalid(f"{paths.title(paths.describe(component.path))} is missing; correct the product before changing "
                      f"its order.")
    if inv.status.error is not None or inv.status.strict_error is not None:
        raise Invalid("The products list cannot be read; correct it before changing this order.")
    statuses = [row for row in inv.status.rows if row.text("file") == product.file]
    name = f"Product {product.stem}"          # never its old file (E11-S12)
    if len(statuses) != 1:
        raise Invalid(f"{name} needs exactly one product status before changing its order.")
    status = statuses[0]
    if status.text("status") not in (*INCOMING, "cancelled"):
        raise Invalid(f"{name} is owned or not pending; its order cannot be removed or cancelled.")
    if not removing and status.text("status") not in INCOMING:
        raise Invalid(f"{name} is already {status.text('status')}.")
    if removing and status.text("intact").strip().lower() == "yes":
        raise Invalid(f"{name} is kept intact; its order cannot be removed.")
    references = [(record.id, part.id) for record, part in inv.components()
                  if part.kind == "product" and part.product_stem == product.stem]
    if references != [(order.id, component.id)]:
        raise Invalid(f"{name} is referenced by another order component; correct its records first.")
    return product, status


def cancel(inv, *, order, component, reason=None, restore_queue=False):
    """Cancel one pending component; declining its queue offer consumes that offer too."""
    from . import order_fulfilment
    before = inv
    original, part = _component(inv, order, component)
    if part.status != "pending" or part.received_on:
        raise Invalid(f"{component} is already {part.status}.")
    reason = _reason(reason, order)
    if type(restore_queue) is not bool:
        raise Invalid("Choose whether to restore this component's recorded queue requests.")
    product_status = _product(inv, original, part)[1] if part.kind == "product" else None
    inv, original, queue = order_fulfilment.restore(inv, original, [component], restore_queue)
    record = original.record()
    said = f"Component {component} cancelled: {reason.rstrip('.')}."
    record["audit_notes"] = (record.get("audit_notes") or "") + (" " if record.get("audit_notes") else "") + said
    inv = inv.with_order(Order(original.file, record)).move_component(order, component, "cancelled")
    if product_status is not None:
        values = product_status.as_dict()
        values.update(status="cancelled", intact="", sleeves="", deck_box="")
        inv = inv.with_status_rows([values if row is product_status else row.as_dict() for row in inv.status.rows])
    return _done(before, inv, Summary(f"Cancelled order {order} {component}",
                                      {"watchlist_restored": sum(int(row["quantity"]) for row in queue["restored"])},
                                      extra={"queue": queue}))


@register("order.remove", refresh=True)
def remove(inv, *, order, reason=None, restore_queue=True):
    """Remove an unreceived order, its exclusive products/payloads, and restore known intent."""
    from . import order_fulfilment
    before = inv
    original = _order(inv, order)
    if restore_queue is not True:
        raise Invalid("Removing an order restores its recorded queue requests; that cannot be skipped.")
    if any(part.status == "received" or part.received_on for part in original.components):
        raise Invalid("An order cannot be removed once any component has been received.")
    if not original.components or any(part.status not in ("pending", "cancelled") for part in original.components):
        raise Invalid("Only an order with pending or cancelled components can be removed.")
    _reason(reason, order)
    products, payloads = [], []
    for part in original.components:
        if part.kind == "product":
            products.append(_product(inv, original, part, removing=True)[0])
        else:
            if part.kind not in ("cards", "tokens"):
                raise Invalid(f"{part.id} is not a recognized order component.")
            if any(other.id != order and c.path == part.path for other, c in inv.components()):
                raise Invalid(f"{paths.title(paths.component_words(order, part.id, part.kind, part.status))}: another order names them too; correct "
                              f"its records first.")
            payloads.append(part.path)
    inv, _, queue = order_fulfilment.restore(inv, original, [part.id for part in original.components], True)
    inv = inv.without_order(order)
    inv = inv.replace(payloads={key: value for key, value in inv.payloads.items() if key not in payloads})
    for product in products:
        inv = inv.without_product(product.stem)
    removed = {product.file for product in products}
    if removed:
        inv = inv.with_status_rows([row.as_dict() for row in inv.status.rows if row.text("file") not in removed])
    return _done(before, inv, Summary(f"Removed mistaken order {order}",
                                      {"components": len(original.components), "products": len(products),
                                       "watchlist_restored": sum(int(row["quantity"]) for row in queue["restored"])},
                                      extra={"queue": queue, "removed": [original.path, *payloads,
                                                                        *(product.path for product in products)]}))
