"""Verified intact-product reservations beside packing's existing name-count allocation.

The product relation comes from generated product decks in the same inventory snapshot,
never from an id prefix or a card's representative picture. This metadata only provides
a readable product-deck route; the product storage workflow still owns every change.
"""
from collections import Counter

from decklab.lib import decks, inventory, pool

from . import common, guard


def _sources(p, snapshot, visible):
    holders = [holder for holder in p.in_use if holder.why == "intact product"]
    if not holders or snapshot.status.error is not None or snapshot.status.strict_error is not None:
        return {}
    holder_ids = Counter(holder.id for holder in p.in_use)
    products = {product.stem: product for product in snapshot.products}
    product_ids = Counter(product.stem for product in snapshot.products)
    # _product_decks retains the actual Product.stem relation that library summaries omit.
    with inventory.pinned(snapshot):
        generated = decks._product_decks()
    route_ids = Counter(item["id"] for item in generated)
    by_id = {item["id"]: item for item in generated}
    result = {}
    for holder in holders:
        route = by_id.get(holder.id)
        if holder_ids[holder.id] != 1 or route_ids[holder.id] != 1 or not route or route.get("error"):
            continue
        product = products.get(route.get("product"))
        if product is None or product_ids[product.stem] != 1 or product.error is not None \
                or product.strict_error is not None or route.get("source") != product.path:
            continue
        status = [row for row in snapshot.status.rows if row.text("file") == product.file]
        if len(status) != 1 or status[0].text("status") != "owned" \
                or status[0].text("intact").strip().lower() != "yes":
            continue
        unresolved = {}
        counts = pool._count_sections(route["sections"], route["source"], unresolved)
        if unresolved or counts != holder.cards or not visible(route["id"]):
            continue
        title, _format = product.label("deck")
        result[holder.id] = ({"id": product.stem, "title": title, "deck_id": route["id"]}, counts)
    return result


def annotate(plan, p, snapshot):
    """Add optional provenance to held_elsewhere without changing any allocation or input.

    Every source requires an owned/intact, readable product, a real visible generated route,
    and agreement with the pool's held counts. Unavailable optional evidence leaves counts
    intact, with no product link. No card printing or future transfer is claimed.
    """
    try:
        sources = _sources(p, snapshot, guard.deck_reader())
    except Exception:  # Optional evidence must not stop the already-computed allocation.
        try:
            common._log("The packing plan's optional intact-product sources could not be checked.")
        except Exception:  # A diagnostic failure must not turn optional evidence into a blocker.
            pass
        return plan
    if not sources:
        return plan
    rows = []
    for row in plan["rows"]:
        holders = []
        for holder in row.get("held_elsewhere", []):
            source = sources.get(holder["id"])
            quantity = holder["quantity"]
            if source and type(quantity) is int and quantity > 0 and source[1][row["name"]] == quantity:
                holder = dict(holder, intact_product=dict(source[0]))
            holders.append(holder)
        rows.append(dict(row, held_elsewhere=holders))
    return dict(plan, rows=rows)
