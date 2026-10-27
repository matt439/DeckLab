"""GET /api/cards/rulings?name=<name>: a card's Scryfall rulings for the card viewer (E1-S25;
decklab/lib/rulings.py downloads and reads them). Rulings are public card data, so every viewer gets the
same answer, as /api/cards/search's.
"""
from decklab.lib import cards, rulings

from .card_lookup import _resolve
from .carddata import _require_cards
from .common import _CONTROL_RE, MAX_NAME, ApiError


def card_rulings(name):
    """{"name" (exact), "available" (False while the PC has no rulings file yet), "updated" (Scryfall's date
    of the file, or None), "rulings": [{"date", "source" ("wotc", "scryfall" or ""), "text"}], oldest first}.
    400 for a bad name, 404 for one that isn't a card, 503 without card data."""
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or _CONTROL_RE.search(name):
        raise ApiError(400, f"Give a card name of at most {MAX_NAME} characters")
    _require_cards()
    exact = _resolve(name.strip())
    card = cards.card(exact) if exact else None
    if card is None:
        raise ApiError(404, f"No card named {name.strip()!r}")
    found = rulings.for_card(card)
    return {"name": exact, "available": found is not None, "updated": rulings.updated(),
            "rulings": found or []}
