"""Corrections to pending products, registered by inventory.orders.

The product keeps its stem and order component. Only supplied metadata changes;
an optional replacement list retains its own column order and per-row metadata.
Inventory apply/preview refresh deck tables in the same snapshot and transaction.
"""
import csv
import dataclasses
import io

from decklab.lib import purchases
from decklab.lib.state import Invalid

from . import Summary, paths, register, rules
from .model import Product, ProductItem
from .orders import INCOMING, _deck_lines, _done, _exact_rows, _invalid, _order, check_card_rows

FIELDS = ("name", "format", "status", "notes")


def _pending(inv, stem):
    if not isinstance(stem, str) or not rules.SLUG.fullmatch(stem) or stem == "status":
        raise Invalid(f"{stem!r} isn't a product file name (lower-case letters, digits and hyphens)")
    product = inv.product(stem)
    if product is None:
        raise Invalid(f"There's no product {stem!r}.")
    statuses = [row for row in inv.status.rows if row.text("file") == product.file]
    if len(statuses) != 1:
        raise Invalid(f"Product {product.stem} has {'no status' if not statuses else 'more than one status'}")
    status = statuses[0]
    if status.text("status") not in INCOMING:
        raise Invalid(f"Product {product.stem} is {status.text('status') or 'not pending'}; only a pending product can be corrected")
    found = [(order, c) for order, c in inv.components() if c.kind == "product" and c.product_stem == stem]
    if len(found) != 1:
        raise Invalid(f"Product {product.stem} needs exactly one order component before it can be corrected")
    order, component = found[0]
    _order(inv, order.id)
    if component.status != "pending" or component.received_on:
        raise Invalid(f"{component.id} is already {component.status}; only a pending product can be corrected")
    return product, status


def _list(product, columns, rows, check_cards):
    if not isinstance(columns, (list, tuple)) or not all(isinstance(c, str) for c in columns):
        raise Invalid(f"Product {product.stem}: missing or duplicate columns")
    columns = tuple(columns)
    rows = _exact_rows(rows, columns, f"Product {product.stem}: each row needs exactly its columns")
    text = rules.csv_bytes(rows, columns).decode("utf-8")
    try:
        parsed = rules.parse_cards(io.StringIO(text, newline=""), paths.describe(product.path), numbered=True)
    except (rules.InvalidCards, csv.Error) as e:
        raise _invalid(e) from None
    warnings = check_card_rows(parsed, check_cards, names_only=True)
    made = Product(product.stem, columns,
                   tuple(ProductItem.make(row, columns, line=n) for n, row in enumerate(rows, 2)),
                   product.name, product.format)
    _deck_lines(made)
    return made, warnings


@register("product.edit", refresh=True)
def edit_product(inv, *, stem, values=None, columns=None, rows=None, check_cards=True):
    """Correct supplied pending-product fields and/or replace its complete card list.

    Blank name/format clears the display override; blank notes clears the notes.
    Replacement lists may change cards and quantities. Unlike receipt corrections,
    this fixes the recorded product itself before it arrives.
    """
    values = {} if values is None else values
    if not isinstance(values, dict) or not set(values) <= set(FIELDS):
        raise Invalid("Set only the product's fields: " + ", ".join(FIELDS))
    if (columns is None) != (rows is None):
        raise Invalid("A replacement product list needs both columns and rows")
    if not values and rows is None:
        raise Invalid("Give the product fields to correct or a replacement card list")
    before = inv
    product, status = _pending(inv, stem)
    checked = {}
    for key, value in values.items():
        if key == "status":
            if value not in INCOMING:
                raise Invalid("A pending product's status is ordered or preordered")
        else:
            try:
                purchases._text(value, f"Product {product.stem}: {key}", blank=key == "notes" or value == "")
            except ValueError as e:
                raise _invalid(e) from None
        checked[key] = value
    made, warnings = _list(product, columns, rows, check_cards) if rows is not None else (product, [])
    if made.error is not None:
        raise Invalid(f"Product {made.stem}'s card list can't be read: {made.error}")
    metadata = {key: checked[key] or None for key in ("name", "format") if key in checked}
    made = dataclasses.replace(made, **metadata)
    status_values = {key: status.text(key) for key in rules.STATUS_FIELDS}
    status_values.update({key: checked[key] for key in ("status", "notes") if key in checked})
    fields = []
    for key in FIELDS:
        if key not in checked:
            continue
        old, new = ((getattr(product, key), getattr(made, key)) if key in ("name", "format")
                    else (status.text(key), status_values[key]))
        if old != new:
            fields.append(key)
    list_changed = (made.columns != product.columns or
                    [item.as_dict() for item in made.items] != [item.as_dict() for item in product.items] or
                    made.error != product.error or made.strict_error != product.strict_error)
    if list_changed:
        fields.append("card list")
    if not fields:
        return inv, Summary(f"Product {stem}: nothing to change", extra={"warnings": warnings})
    if metadata or list_changed:
        inv = inv.with_product(made)
    if any(key in fields for key in ("status", "notes")):
        inv = inv.with_status_rows([status_values if row is status else row.as_dict() for row in inv.status.rows])
    if list_changed:
        from . import order_fulfilment
        order, component = next((order, component) for order, component in inv.components()
                                if component.kind == "product" and component.product_stem == stem)
        inv = inv.with_order(order_fulfilment.edit(order, component.id,
                                                 [row.as_dict() for row in product.items],
                                                 [row.as_dict() for row in made.items]))
    count = sum(item.qty or 0 for item in made.items)
    return _done(before, inv, Summary(f"Changed pending product {stem}: " + ", ".join(fields),
                                      {"product": count}, extra={"fields": fields, "warnings": warnings}))
