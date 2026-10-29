"""A Commander deck's "EDHREC ideas" (E9-S07, lib/edhrec.py): GET /api/deck/edhrec?id=<deck id>, the
commander's commonly played cards from EDHREC, grouped by EDHREC's categories with the share of its
decks that play each.

A deck the viewer may not see is the missing deck's 404 (library._find_summary), before anything
else. Every viewer of the deck gets the list; only one who may see the deck's space's inventory
(guard.sees_inventory) gets each card's mark (in the deck, free, in use, to buy) and the AUD estimate
of a card to buy: for anyone else the answer has no "status", "free", "on_the_way" or price, and no
answer names a deck holding a card. "may_add" says whether this viewer may add a card to the deck's
Considering list (POST /api/deck/considering, api/considering.py, which checks it again).

EDHREC is asked only when the page's sheet is opened, and only when the PC's copy is more than a week
old (lib/edhrec.py fetch). When it can't be reached and nothing is cached the answer is 502 with a plain
message; an older copy is given with source.stale saying why. A commander EDHREC has no page for is 404
with its own words. Nothing is written but the cache.

commander (and commander2, for a pair) are the editor's draft commander(s), E9-S07: given, the ideas are
that commander's (its EDHREC page and colour identity) instead of the saved Commander section's, so a draft
whose commander changed needn't be saved first. Each must be a card Deck Lab knows (400 otherwise); the
deck is still the saved one, seen first as above, and the marks still follow the viewer's sight of its
space's inventory, so a name sent here tells no more than the card finder does.
"""
import re

from decklab.lib import cards, decks, edhrec, spaces

from . import guard
from .card_lookup import _card_json, _shown_printing
from .carddata import _require_cards
from .common import ApiError, _public
from .library import _find_summary, _load_pool, check_deck_id

MAX_NAME = 200                      # characters in a draft commander's name


def _draft_commanders(commander, commander2):
    """The draft commander(s) as exact card names, or None for the saved deck's. 400 for one Deck Lab
    doesn't know."""
    if commander2 not in (None, "") and commander in (None, ""):
        raise ApiError(400, "commander2 needs commander: give the first commander too.")
    names = []
    for value in (commander, commander2):
        if value in (None, ""):
            continue
        value = value.strip()
        if not value or len(value) > MAX_NAME or re.search(r"[\x00-\x1f\x7f]", value):
            raise ApiError(400, f"A commander's name must be 1-{MAX_NAME} characters, with no control characters.")
        exact = cards.resolve(value)
        if not exact or cards.card(exact) is None:
            raise ApiError(400, f"{value} isn't a card Deck Lab knows, so EDHREC has no ideas for it.")
        if exact not in names:
            names.append(exact)
    return names or None


def _card(name):
    card = cards.card(name)
    return _card_json(card, _shown_printing(card)) if card else None


def edhrec_view(deck_id=None, commander=None, commander2=None):
    """GET /api/deck/edhrec?id=&commander=&commander2=: lib/edhrec.ideas' answer (with "card", the card's
    JSON for its picture, on each card), plus "sha256" (the deck text's, for a Considering add), "may_add",
    "marks" (whether the answer marks what's owned) and "warnings" (the pool's, as the deck page shows
    them). commander and commander2 are the editor's draft commander(s) (see the module's docstring)."""
    if deck_id is None:
        raise ApiError(400, "id is required: the deck's id")
    check_deck_id(deck_id)
    summary = _find_summary(deck_id)            # a hidden deck's 404 first
    space, kind, slug = spaces.split_deck_id(summary["id"])
    if kind != "commander":
        raise ApiError(400, "EDHREC ideas are for Commander decks.")
    _require_cards()
    draft = _draft_commanders(commander, commander2)
    warnings = []
    sees = guard.sees_inventory(space)
    p = _load_pool(warnings, space) if sees else None
    try:
        result = edhrec.ideas(summary["id"], p, commanders=draft)
    except (decks.DeckNotFound, FileNotFoundError):
        raise guard.no_deck(deck_id) from None
    except edhrec.NotCommander as e:
        raise ApiError(400, str(e)) from None
    except edhrec.NoPage:
        raise ApiError(404, "EDHREC has no page for this commander yet, so there are no ideas to show.") from None
    except edhrec.EdhrecError as e:
        raise ApiError(502, f"{_public(e)}. Try again later: nothing else on the page needs it.") from None
    except (decks.DeckFileError, OSError, ValueError) as e:
        raise ApiError(500, f"{summary['id']} can't be read: {_public(e)}") from None
    for group in result["groups"]:
        for row in group["cards"]:
            row["card"] = _card(row["name"])
    profile = guard.viewer()
    deck = result.pop("deck")
    result.update(sha256=deck.sha256, marks=p is not None, warnings=warnings,
                  may_add=profile is not None and guard.allowed(profile, "deck.edit", deck))
    return result
