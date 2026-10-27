"""Actual product subdecks as demands, with one saved packing record per box.

This home-only reader never derives a producer from a route's spelling. A box
whose complete token needs cannot be calculated keeps its existing reservation.
"""
from collections import Counter

from decklab.lib import cards, decks, inventory, pool

from . import products

FIXED = "An intact product's token needs cannot be planned. Its recorded token cards remain packed."


def gather(inv, warnings=None, *, evaluate, section_key):
    """Eligible whole-box descriptors containing actual per-subdeck demands.

Clean boxes with no token needs stay fixed: blank still means unknown, and a
manual packing record is not cleared because no needs were detected. No caller
    outside home should call this reader. The package supplies the token
    evaluator and section digest so its patchable names keep one binding.
"""
    warnings = [] if warnings is None else warnings
    snapshot = inventory.current()
    records = products.records(warnings, snapshot)
    routes = decks._product_decks()
    ids = Counter(route.get("id") for route in routes)
    found = []
    for holder, record in sorted(records.items()):
        product = record.get("product")
        if product is None or record.get("error"):
            continue  # reserve.holds retains unreadable reservation sentinels.
        actual = [route for route in routes if route.get("product") == product.stem
                  and route.get("source") == product.path]
        bad = (product.error is not None or product.strict_error is not None or product.csv_error is not None
               or not actual or any(route.get("error") or not isinstance(route.get("id"), str)
                                    or ids[route["id"]] != 1 or not route.get("sections") for route in actual))
        participants = []
        if not bad:
            for route in sorted(actual, key=lambda item: item["id"]):
                sections = route["sections"]
                unresolved = {}
                names = [pool._canonical(line.name, "deck", unresolved)
                         for section in decks.SECTIONS for line in sections.get(section, [])]
                if any(not decks.is_basic_land(name) and cards.card(name) is None for name in names):
                    bad = True
                    break
                result = evaluate(route["id"], "target", sections, inv, [])
                if result["unlisted"] or result["copies"]:
                    bad = True
                    break
                participants.append({"id": route["id"], "title": route["title"], "needs": result["needs"],
                                     "sections_key": section_key(sections)})
        if bad:
            if FIXED not in warnings:
                warnings.append(FIXED)
            continue
        found.append({"stem": product.stem, "holder": holder, "title": record["title"], "link": record["link"],
                      "source": product.path, "before": record["status"].text("token_cards"),
                      "fixed": not any(item["needs"] for item in participants), "decks": participants})
    return found
