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

With no id (a deck not saved yet: the new-deck editor's, E9-S07), commander is required and space names
the space the deck is being made in (by default the viewer's own), checked as a new deck's space is
(drafts._new_space: a space whose decks the viewer can't see answers as one that doesn't exist, 403).
The marks then count that space's pool, with nothing in the deck, again only for a viewer who sees its
inventory; there's no sha256 and may_add is false (an unsaved deck has no Considering list).

page narrows the ideas to one of EDHREC's budget, bracket or theme pages for the commander
(lib/edhrec.fetch; "pages" lists the ones offered): a page it doesn't offer is 400, one EDHREC hasn't got
is 404, and either way the rest of the sheet still works.
"""
import re

from decklab.lib import cards, decks, edhrec, spaces

from . import drafts, guard
from .card_lookup import _card_json, _shown_printing
from .carddata import _require_cards
from .common import ApiError, _public
from .library import _find_summary, _load_pool, check_deck_id

MAX_NAME = 200                      # characters in a draft commander's name
MAX_PAGE = 80                       # characters in a narrowed page's name


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


def _page(page):
    """A narrowed page's name as sent, or None for the commander's whole page. 400 for one that can't be an
    EDHREC page's name (whether this commander offers it is lib/edhrec.fetch's to say)."""
    if page in (None, ""):
        return None
    if not isinstance(page, str) or len(page) > MAX_PAGE or not edhrec._SLUG.fullmatch(page):
        raise ApiError(400, "page must be one of the EDHREC pages the ideas offer (budget, a bracket or a theme).")
    return page


def _card(name):
    card = cards.card(name)
    return _card_json(card, _shown_printing(card)) if card else None


def edhrec_view(deck_id=None, commander=None, commander2=None, space=None, page=None):
    """GET /api/deck/edhrec?id=&commander=&commander2=&space=&page=: lib/edhrec.ideas' answer (with "card",
    the card's JSON for its picture, on each card), plus "space", "sha256" (the deck text's, for a
    Considering add; None for a deck not saved yet), "may_add", "marks" (whether the answer marks what's
    owned) and "warnings" (the pool's, as the deck page shows them). commander and commander2 are the
    editor's draft commander(s), space a new deck's space and page a narrowed EDHREC page (see the module's
    docstring)."""
    if deck_id is None:
        if commander in (None, ""):
            raise ApiError(400, "id is required: the deck's id (or commander, for a deck not saved yet)")
        # A deck not saved yet: its space as a new deck's is checked, then its commander(s).
        space = drafts._new_space({} if space in (None, "") else {"space": space}, guard.viewer())
        page = _page(page)
        _require_cards()
        draft = _draft_commanders(commander, commander2)
        deck_ref = None
    else:
        if space not in (None, ""):
            raise ApiError(400, "Send id for a saved deck, or space for a deck not saved yet, not both.")
        check_deck_id(deck_id)
        summary = _find_summary(deck_id)            # a hidden deck's 404 first
        space, kind, slug = spaces.split_deck_id(summary["id"])
        if kind != "commander":
            raise ApiError(400, "EDHREC ideas are for Commander decks.")
        page = _page(page)
        _require_cards()
        draft = _draft_commanders(commander, commander2)
        deck_ref = summary["id"]
    warnings = []
    sees = guard.sees_inventory(space)
    p = _load_pool(warnings, space) if sees else None
    try:
        result = edhrec.ideas(deck_ref, p, commanders=draft, page=page)
    except (decks.DeckNotFound, FileNotFoundError):
        raise guard.no_deck(deck_id) from None
    except edhrec.NotCommander as e:
        raise ApiError(400, str(e)) from None
    except edhrec.UnknownPage as e:
        raise ApiError(400, f"{e} Choose another page: the commander's own page still works.") from None
    except edhrec.NoPage:
        if page:
            raise ApiError(404, f"EDHREC has no {page} page for this commander, so there are no ideas to show "
                                "there. Choose another page.") from None
        raise ApiError(404, "EDHREC has no page for this commander yet, so there are no ideas to show.") from None
    except edhrec.EdhrecError as e:
        raise ApiError(502, f"{_public(e)}. Try again later: nothing else on the page needs it.") from None
    except (decks.DeckFileError, OSError, ValueError) as e:
        raise ApiError(500, f"{deck_ref or 'The ideas'} can't be read: {_public(e)}") from None
    for group in result["groups"]:
        for row in group["cards"]:
            row["card"] = _card(row["name"])
    profile = guard.viewer()
    deck = result.pop("deck")
    result.update(space=space, sha256=deck.sha256 if deck else None, marks=p is not None, warnings=warnings,
                  may_add=deck is not None and profile is not None and guard.allowed(profile, "deck.edit", deck))
    return result
