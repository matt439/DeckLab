"""Advisory exact-printing matches to products' recorded bonus rows (E5-S36).

No card data, source fetch or collection provenance is inferred. Web callers must
already authorize home's records. These optional hints never block a purchase.
"""
from . import rules


def _key(row):
    values = tuple(row.get(field) for field in ("set", "collector_number", "finish"))
    if not all(isinstance(value, str) and value for value in values) or values[2] not in rules.FINISHES:
        return None
    return values[0].lower(), values[1], values[2]


def printing_map(inv, *, statuses=("preordered", "ordered")):
    """Exact printing -> product labels, from one snapshot; explicit display cards are excluded.

    The extras section marks a fixed extra. A display commander labelled as such is
    a different extra, and never presented as a bonus. Corrupt optional rows give no hint.
    """
    try:
        state = {row.text("file"): row.text("status") for row in inv.status.rows}
        products = {}
        for _, component in inv.components():
            if component.kind == "product":
                products.setdefault(component.product_stem, set()).add(component.status)
        found = {}
        for product in inv.products:
            status = state.get(product.file)
            if status not in statuses or product.error is not None \
                    or ("received" if status == "owned" else "pending") not in products.get(product.stem, set()):
                continue
            for row in product.items:
                if not rules.extras_row(row) or "display commander" in row.text("notes").casefold():
                    continue
                key = _key(row)
                if key is None or row.qty is None or row.qty <= 0:
                    continue
                name = product.label("shopping")
                if name not in found.setdefault(key, []):
                    found[key].append(name)
        return {key: sorted(names) for key, names in found.items()}
    except Exception:
        return {}       # an optional annotation cannot refuse a valid save or change its exit code


def messages(inv, rows, *, statuses=("preordered", "ordered"), recorded=False):
    """Only exact physical printings match; any-printing queue intent never claims a duplicate."""
    try:
        products = printing_map(inv, statuses=statuses)
        warnings = []
        for row in rows:
            if row.get("printing") not in (None, "", "exact"):
                continue
            key = _key(row)
            if key is None:
                continue
            name = row.get("name")
            if not isinstance(name, str) or not name:
                continue
            for product in products.get(key, []):
                words = f"{name} ({key[0].upper()} {key[1]}, {key[2]}): " + (
                    "also listed as the bonus card in " if recorded else "expected as the bonus card in ") + product
                if words not in warnings:
                    warnings.append(words)
        return warnings
    except Exception:
        return []


def public_rows(inv):
    """A snapshot-derived printing catalog for an authorized Shopping reader; no raw notes."""
    return [{"set": key[0], "collector_number": key[1], "finish": key[2], "products": list(names)}
            for key, names in sorted(printing_map(inv).items())]
