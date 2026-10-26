"""Actual intact-product token holders and their generated deck routes.

Product ids are resolved through the producer relation, never by splitting a route.
An invalid nonempty packing record stays an error so a planner cannot free its cards.
"""
from collections import Counter

from decklab.lib import decks, inventory

FAILED = "An intact product's packed token record cannot be read. Correct it before planning token cards."


def records(warnings=None, snapshot=None):
    """{canonical holder: product record}; blank records retain the legacy warning.

    Each record has product, status, title, holder, link, written, lines and error.
    Unreadable sources and malformed/ambiguous nonempty reservations add an error
    sentinel. Unrelated legacy warnings on blank records retain their old behavior.
    """
    snapshot = inventory.current() if snapshot is None else snapshot
    warnings = [] if warnings is None else warnings
    sheet = snapshot.status
    if not sheet.exists:
        return {}
    if sheet.error is not None or sheet.strict_error is not None or sheet.csv_error is not None:
        warnings.append(FAILED)
        return {"product/": {"error": FAILED, "title": "An intact product", "written": True,
                             "lines": [], "link": None}}
    files = Counter(product.file for product in snapshot.products)
    stems = Counter(product.stem for product in snapshot.products)
    status_files = Counter(row.text("file").strip() for row in sheet.rows)
    routes = None
    out = {}
    for row in sheet.rows:
        if row.text("token_cards").strip() and (row.text("status").strip().lower() != "owned"
                or row.text("intact").strip().lower() != "yes" or row.text("file").strip() not in files):
            warnings.append(FAILED)
            out["product/"] = {"error": FAILED, "title": "An intact product", "written": True,
                               "lines": [], "link": None}
    for product in snapshot.products:
        matches = [row for row in sheet.rows if row.text("file").strip() == product.file]
        if not matches:
            continue
        # Ambiguous records cannot release a possible product reservation.
        holder = f"product/{product.stem}"
        if files[product.file] != 1 or stems[product.stem] != 1 or status_files[product.file] != 1:
            if not any(row.text("token_cards").strip() for row in matches):
                continue  # Legacy blank records have no explicit reservation to free.
            warnings.append(FAILED)
            out[holder] = {"error": FAILED, "title": "An intact product", "written": True,
                           "lines": [], "link": None}
            continue
        row = matches[0]
        if row.text("status").strip().lower() != "owned" or row.text("intact").strip().lower() != "yes":
            continue
        title, _ = product.label("deck")
        value = row.text("token_cards").strip()
        error = None
        try:
            lines = decks.parse_token_cards(value)
        except (ValueError, decks.DeckFileError):
            lines, error = [], FAILED
            warnings.append(FAILED)
        if routes is None:
            routes = decks._product_decks()
        roots = [route for route in routes if route.get("id") == holder
                 and route.get("product") == product.stem and route.get("source") == product.path
                 and not route.get("error")]
        out[holder] = {"product": product, "status": row, "title": title, "holder": holder,
                       "link": holder if len(roots) == 1 else None, "written": bool(value),
                       "lines": lines, "error": error}
    return out


def for_route(deck_id, snapshot=None):
    """The clean owned/intact product that actually generated this route, or None."""
    snapshot = inventory.current() if snapshot is None else snapshot
    routes = [route for route in decks._product_decks() if route.get("id") == deck_id]
    if len(routes) != 1 or routes[0].get("error"):
        return None
    route = routes[0]
    for record in records(snapshot=snapshot).values():
        product = record.get("product")
        if product is not None and product.error is None and product.strict_error is None \
                and route.get("product") == product.stem and route.get("source") == product.path:
            return record
    return None


def holder_id(deck_id):
    # This is only a quick routing-kind check. The producer is resolved from real metadata.
    if not isinstance(deck_id, str) or not deck_id.startswith("product/"):
        return deck_id
    record = for_route(deck_id)
    return record["holder"] if record is not None else deck_id
