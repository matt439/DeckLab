"""GET /api/cards/combos?name=<name>: a card's Game Changer flag and the known two-card combos it is a piece of,
for the card viewer (E9-S37: a commander across the table). Both are public card data read on the PC (the card
index and Commander Spellbook's two-card list, lib/combos.py), so every viewer gets the same answer, as
/api/cards/rulings's: no deck, space or profile is read, and nothing is fetched from the network.
"""
from decklab.lib import cards, combos

from .card_lookup import _resolve
from .carddata import _require_cards
from .common import _CONTROL_RE, MAX_NAME, ApiError

MAX_SHOWN = 25          # combos listed; "total" counts them all
MAX_RESULTS = 3         # each combo's result names listed, most telling first
SOURCE_URL = "https://commanderspellbook.com/"
CREDIT = "Commander Spellbook's combo list (commanderspellbook.com, with thanks)"
UNCHECKED = ("Combos weren't checked: Commander Spellbook's combo list isn't on this PC yet or can't be read "
             "(the next card data update downloads it).")


def _combo_json(combo):
    piece = combo["piece"]
    others = [{"name": p["name"], "must_be_commander": p["must_be_commander"] is True}
              for k, p in enumerate(combo["cards"]) if k != piece]
    return {"id": combo["id"], "url": combo["url"], "class": combo["class"],
            "standalone": combo["standalone"], "results": [str(r) for r in combo["results"][:MAX_RESULTS]],
            "more_results": max(0, len(combo["results"]) - MAX_RESULTS),
            "bracket_floor": combos.bracket_floor(combo),
            "must_be_commander": combo["cards"][piece].get("must_be_commander") is True, "others": others}


def card_combos(name=None):
    """{"name" (exact), "game_changer", "checked"} plus, when the list was read, "date" (the list's, YYYY-MM-DD),
    "version", "total", "combos" (at most MAX_SHOWN, most serious first: each {"id", "url", "class", "standalone",
    "results", "more_results", "bracket_floor", "must_be_commander" (this card), "others": [{"name",
    "must_be_commander"}]}), "credit" and "source_url"; or "reason" when it wasn't (never an empty list then).
    400 for a bad name, 404 for one that isn't a card, 503 without card data."""
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or _CONTROL_RE.search(name):
        raise ApiError(400, f"Give a card name of at most {MAX_NAME} characters")
    _require_cards()
    exact = _resolve(name.strip())
    card = cards.card(exact) if exact else None
    if card is None:
        raise ApiError(404, f"No card named {name.strip()!r}")
    answer = {"name": exact, "game_changer": bool(card.get("game_changer"))}
    try:
        found = combos.with_card(card.get("oracle_id"))
    except combos.ComboListError:
        return {**answer, "checked": False, "reason": UNCHECKED}
    matches = found["matches"]
    return {**answer, "checked": True, "date": found["timestamp"][:10], "version": found["version"],
            "total": len(matches), "combos": [_combo_json(c) for c in matches[:MAX_SHOWN]],
            "credit": CREDIT, "source_url": SOURCE_URL}
