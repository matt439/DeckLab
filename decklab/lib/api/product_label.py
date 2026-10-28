"""An intact product's box label (E8-S21): what GET /api/deck answers as "box_label" on its deck pages.

A product kept intact lives in one box (one sleeve design and one deck box for all its decks), so it gets
one label: the product's name, the colours across its decks, each deck's name, and a QR code to one deck
page. The code opens the product's first deck (the product's own route when it has a single unnamed deck),
in its list's order, so the same label comes out whichever of its pages printed it; every product deck
page's Product storage part links the box's other decks, so a scan reaches them all.

Products are home's records: only a viewer who sees them (guard.sees_home_records) gets a label, and only
for an owned product kept intact whose list reads cleanly (tokens.products.for_route). It's an optional
decoration: anything that fails leaves it out and the page shows the deck as always.
"""
import traceback

from decklab.lib import decks
from decklab.lib.decks.identity import COLOR_ORDER, CardIdentityError, deck_colors

from . import common, guard


def box_label(deck_id):
    """{"name", "colors", "link", "decks": [{"id", "title"}]} for an intact product's deck page, else None.

    colors is the union of its decks' colour identities in WUBRG order ([] colourless), None when no deck's
    could be read or a card's identity data is damaged (the label still prints, without symbols). A deck's title is its name in the product (the product's name for an unnamed deck)."""
    if not isinstance(deck_id, str) or not deck_id.startswith("product/") or not guard.sees_home_records():
        return None
    try:
        from decklab.lib.tokens import products as product_tokens
        record = product_tokens.for_route(deck_id)
        if record is None or record.get("error") or record.get("product") is None:
            return None
        product = record["product"]
        routes = [route for route in decks._product_decks() if route.get("product") == product.stem
                  and route.get("source") == product.path and not route.get("error")]
        if not routes:
            return None
        colours, known = set(), False
        try:
            for route in routes:
                found = deck_colors(route.get("sections") or {})
                if found is not None:
                    known = True
                    colours.update(found)
        except CardIdentityError:   # only the symbols are lost: a partial union would print wrong colours
            common._log(f"The box label of {deck_id} has no colours:\n" + traceback.format_exc())
            known = False
        return {"name": record["title"], "colors": [c for c in COLOR_ORDER if c in colours] if known else None,
                "link": routes[0]["id"],
                "decks": [{"id": route["id"], "title": route.get("deck") or record["title"]} for route in routes]}
    except Exception:           # the page still shows the deck; the log has the details
        common._log(f"The box label of {deck_id} couldn't be worked out:\n" + traceback.format_exc())
        return None
