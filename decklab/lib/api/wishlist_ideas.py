"""The editor's "My wishlist" ideas (E5-S30): GET /api/deck/wishlist?id=<deck id>, the signed-in
profile's own wishlist cards that fit the deck being edited, for the Add panel's My wishlist tick.

Only the viewer's own list is ever read (a wishlist is private to its owner, E5-S14, E10-S11): a
request naming nobody, a script included, is 403, and nobody can ask for another person's list. A deck
the viewer may not see is the missing deck's 404 (library._find_summary), before anything else. A
new deck's editor sends no id: kind (casual or commander) and space (by default the viewer's own,
checked as a new deck's space is, drafts._new_space) say what it's being made as.

A Commander deck's ideas are the wished cards inside its commander's colour identity and legal in
Commander: commander (and commander2) are the editor's draft commander(s), so a changed commander
needs no save first; with none sent, the saved Commander section's. A Commander deck with no commander
yet filters on nothing and says so ("identity" None). A casual deck takes every wished card (ban lists
and legality don't matter there). Basic lands are never offered.

Each card carries its wished printing ("set", "number", "" for none) so a card added keeps it, and,
only for a viewer who may see the deck's space's inventory (guard.sees_inventory), the EDHREC ideas'
marks: "status" (in_deck, free, in_use or to_buy), "free", "on_the_way" and a to-buy card's AUD
estimate. No answer names a deck holding a card. Nothing is written.
"""
from collections import Counter

from decklab.lib import cards, currency, decks, pool, spaces, state

from . import common, drafts, guard
from .card_lookup import _card_json, _shown_printing
from .carddata import _require_cards
from .common import ApiError
from .edhrec import _draft_commanders
from .library import _find_summary, _load_pool, check_deck_id

NO_PROFILE = "Choose who you are to see your wishlist."
KINDS = ("casual", "commander")


def _counts(lines):
    out = Counter()
    for line in lines:
        out[cards.resolve(line.name) or line.name] += line.quantity
    return out


def _card(name, set_code, number):
    """The card's JSON, showing the wished printing when it's still that card's."""
    card = cards.card(name)
    if card is None:
        return None
    if set_code:
        printed = cards.printing_card(set_code, number)
        if printed and printed["name"] == card["name"]:
            return _card_json(printed, cards.printing(set_code, number))
    return _card_json(card, _shown_printing(card))


def wishlist_ideas_view(deck_id=None, commander=None, commander2=None, space=None, kind=None):
    """GET /api/deck/wishlist?id=&commander=&commander2=&space=&kind=: {"profile", "space", "kind",
    "identity" (WUBRG letters, "" colourless; None when no colour identity filters the list),
    "cards": [{"name", "set", "number", "card", "in_deck", and with marks: "status", "free",
    "on_the_way", "aud_each", "priced_printing"}] in the wishlist's order, "left_out" (how many wished
    cards don't fit), "marks", "rate", "rate_date", "price_date", "price_error", "warnings"}."""
    profile = guard.viewer()
    if profile is None:
        raise ApiError(403, NO_PROFILE)
    if deck_id in (None, ""):
        if kind not in KINDS:
            raise ApiError(400, "kind must be casual or commander for a deck not saved yet")
        space = drafts._new_space({} if space in (None, "") else {"space": space}, profile)
        _require_cards()
        draft = _draft_commanders(commander, commander2)
        deck = None
    else:
        if space not in (None, "") or kind not in (None, ""):
            raise ApiError(400, "Send id for a saved deck, or kind and space for a deck not saved yet, not both.")
        check_deck_id(deck_id)
        summary = _find_summary(deck_id)            # a hidden deck's 404 first
        space, kind, slug = spaces.split_deck_id(summary["id"])
        if kind not in KINDS:
            raise ApiError(400, "Wishlist ideas are for casual and Commander decks.")
        _require_cards()
        draft = _draft_commanders(commander, commander2)
        try:
            deck = decks.read_deck_file(decks.find_deck_file(kind, slug, space), space=space)
        except (decks.DeckNotFound, FileNotFoundError):
            raise guard.no_deck(deck_id) from None
        except (decks.DeckFileError, OSError, ValueError) as e:
            raise ApiError(500, f"{summary['id']} can't be read: {common._public(e)}") from None
        deck_id = summary["id"]
    with common.state_errors():
        entries = state.store().wishlist(profile["id"])

    identity = None
    if kind == "commander":
        names = draft or ([cards.resolve(line.name) or line.name for line in deck.target.get("Commander", [])]
                          if deck else [])
        if names:
            letters = set()
            for name in names:
                letters.update((cards.card(name) or {}).get("color_identity", []))
            identity = "".join(c for c in "WUBRG" if c in letters)
        commanders = set(names)
    else:
        commanders = set()

    warnings = []
    sees = guard.sees_inventory(space)
    p = _load_pool(warnings, space) if sees else None
    planned = _counts(line for section in deck.target.values() for line in section) if deck else Counter()
    free = pool.free_copies(p, pool.self_ids(deck_id) if deck_id else ()) if p is not None else None
    result = {"profile": profile["id"], "space": space, "kind": kind, "identity": identity, "cards": [],
              "left_out": 0, "marks": p is not None, "rate": None, "rate_date": None, "price_date": None,
              "price_error": None, "warnings": warnings}
    prices = p is not None
    if prices:
        try:
            result["rate"], result["rate_date"] = cards.usd_to_aud()
            result["price_date"] = cards.price_date()
            result.update(currency.tag(currency.code()))      # E11-S53: only when it isn't AUD
        except RuntimeError as e:
            result["price_error"] = str(e)
            prices = False
    seen = set()
    for entry in entries:
        exact = cards.resolve(entry["name"])
        card = cards.card(exact) if exact else None
        if card is None or exact in seen:
            if card is None:
                result["left_out"] += 1
            continue
        seen.add(exact)
        if decks.is_basic_land(exact) or exact in commanders:
            result["left_out"] += 1
            continue
        if kind == "commander" and (
                (identity is not None and set(card.get("color_identity", [])) - set(identity))
                or card.get("commander_legality") in ("banned", "not_legal")):
            result["left_out"] += 1
            continue
        row = {"name": exact, "set": entry.get("set") or "", "number": entry.get("number") or "",
               "card": _card(exact, entry.get("set"), entry.get("number")), "in_deck": planned.get(exact, 0) > 0}
        if free is not None:
            spare = max(free.get(exact, 0) - planned.get(exact, 0), 0)
            row["free"] = spare
            row["on_the_way"] = sum(qty for _, qty in p.on_the_way.get(exact, []))
            row["status"] = ("in_deck" if row["in_deck"] else "free" if spare else
                             "in_use" if p.owned.get(exact, 0) else "to_buy")
            price = cards.price_aud(exact) if prices and row["status"] == "to_buy" else None
            row["aud_each"] = price.aud if price else None
            row["priced_printing"] = pool._printing_label(price)
        result["cards"].append(row)
    return result
