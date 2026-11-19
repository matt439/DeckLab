"""Allocate saved retailer listings to queue rows, sharing each counted stock limit."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from decklab.lib.min_cost_flow import min_cost_flow

CENT = Decimal("0.01")


def money(value):
    """Decimal, or None for anything that isn't a non-negative amount."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def text(value):
    return None if value is None else f"{value.quantize(CENT)}"


def quantity(row):
    try:
        return max(int(str(row.get("quantity") or "0")), 0)
    except ValueError:
        return 0


@dataclass(frozen=True)
class Offer:
    key: tuple                     # (shop, snapshot card name, listing index)
    listing: dict
    price: Decimal | None
    stock: int | None              # None if the shop does not count copies


def _price_order(offer):
    return offer.price is None, offer.price or 0


def _card(rows, reserved):
    """Rows -> listing tiers -> sink. First maximise coverage, then exact requests and priced copies,
    then minimise the cost of those copies. The capacity on each listing is shared."""
    offers = {offer.key: offer for _, choices in rows for offer in choices}
    if not offers:
        return {}
    demand = sum(quantity(row) for row, _ in rows)
    unknown_price = 1 + demand * max((offer.price or 0 for offer in offers.values()))
    flexible = 1 + demand * unknown_price
    listing_nodes = {key: i for i, key in enumerate(offers, len(rows) + 1)}
    sink = 1 + len(rows) + len(offers)
    edges, uses = [], []
    for node, (row, choices) in enumerate(rows, 1):
        want = quantity(row)
        edges.append((0, node, want, 0 if row.get("printing") == "exact" else flexible))
        for offer in sorted(choices, key=_price_order):
            uses.append((len(edges), row.get("queue_row"), offer))
            edges.append((node, listing_nodes[offer.key], want, 0))
    for key, offer in offers.items():
        left = demand if offer.stock is None else max(offer.stock - reserved.get(key, 0), 0)
        edges.append((listing_nodes[key], sink, left, unknown_price if offer.price is None else offer.price))
    flow = min_cost_flow(sink + 1, edges, 0, sink)
    assigned = defaultdict(list)
    for index, row, offer in uses:
        if flow[index]:
            assigned[row].append((offer, flow[index]))
    return assigned


def allocate(rows, shops, offers, reserved=None):
    """{queue row: [(Offer, copies)]} across the chosen shops, independently by card name."""
    cards = defaultdict(list)
    for row in rows:
        key = row.get("queue_row")
        choices = [offer for shop in shops for offer in offers[shop].get(key, ())]
        if choices and quantity(row):
            cards[str(row.get("name") or "").casefold()].append((row, choices))
    return {key: assigned for group in cards.values() for key, assigned in _card(group, reserved or {}).items()}


def used(assignments):
    """Count the capacity already reserved by ready rows before offering optional rows."""
    counts = Counter()
    for choices in assignments.values():
        for offer, copies in choices:
            counts[offer.key] += copies
    return counts


def line(item, assigned):
    """A public basket/plan line over exactly the tiers the allocator used at this shop."""
    copies = sum(count for _, count in assigned)
    unknown = sum(count for offer, count in assigned if offer.price is None)
    known = sum((offer.price * count for offer, count in assigned if offer.price is not None), Decimal(0))
    listing, *more = [{**offer.listing, "copies": count} for offer, count in assigned]
    return {**item, "listing": listing, "more": more, "copies": copies, "short": copies < quantity(item),
            "line_aud": text(known) if not unknown else None, "known_aud": text(known), "unpriced_copies": unknown}
