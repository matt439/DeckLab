"""GET /api/cards/decks?name=<name>[&space=<id>]: one card's use in a space, for the card viewer's line (E1-S29,
first slice: the viewer opened from the deck page or the Collection page).

Under the inventory rule (R6d, E10-S29) the answer is only for a viewer who may see that space's inventory:
anyone else gets the Collection page's 403, word for word (space_param and guard.require_sees_inventory), so
nothing tells a hidden space from a missing one. Inside it, a deck the viewer may not see (E10-S30's
guard.deck_reader; a product deck's name to a viewer outside home's records, inventory_views.named_holder) is
never named or counted: it is left out of both lists, with no "one of the home decks" line. Its copies still
leave the shelf, so "free" is the Collection page's (owned less every built deck's and intact product's copies,
pool.load_pool), the same number the Card list's In decks column and the global search give.

Nothing is written.
"""
import csv

from decklab.lib import cards, decks, pool, spaces

from . import guard
from .card_lookup import _resolve
from .carddata import _require_cards
from .common import _CONTROL_RE, MAX_NAME, ApiError, _public

MAX_DECKS = 50                  # holders and wanters each: a card in more is cut, with "more" saying so


def _name(name):
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or _CONTROL_RE.search(name):
        raise ApiError(400, f"Give a card name of at most {MAX_NAME} characters")
    return name.strip()


def _wanted(summary, name, unresolved):
    """Copies of name in a deck's Planned list, else its Play-now list (the Considering list is neither), or 0."""
    for version in ("target", "owned"):
        if version not in summary.get("versions", ()):
            continue
        try:
            sections = decks.load_deck(summary["id"], version)
        except (decks.DeckNotFound, decks.DeckFileError, OSError):
            continue
        copies = pool._count_sections(sections, summary["id"], unresolved)[name]
        if copies:
            return copies
    return 0


def card_decks(name, space=None):
    """{"name" (exact), "space", "basic", "holds": [{"id", "title", "why" ("built" or "intact product"),
    "copies"}], "wants": [{"id", "title", "status", "copies"}], "more" (a list was cut at MAX_DECKS),
    "owned", "incoming", "free"}.

    holds: the decks whose physical copies are the card's (built decks first, then intact products, each by
    title), as the pool counts them; wants: the space's other decks whose Planned list (else its Play-now list)
    has the card (building first, then ideas, then built decks whose built list doesn't hold it). A basic land
    gives basic true, empty lists and null counts: its copies in decks aren't tracked, as the Card list says.
    400 for a bad name, 404 for one that isn't a card, 403 for a space whose inventory the viewer may not see
    (the same 403 for one that doesn't exist), 409 when the pool can't be read, 503 without card data."""
    from .collection import space_param
    from .inventory_views import named_holder
    name = _name(name)
    space = space_param(space)
    guard.require_sees_inventory(space)
    _require_cards()
    exact = _resolve(name)
    # A basic land is a basic land by name (decks.is_basic_land), even where the card data lacks it.
    if exact is None or (cards.card(exact) is None and not decks.is_basic_land(exact)):
        raise ApiError(404, f"No card named {name!r}")
    answer = {"name": exact, "space": space, "basic": decks.is_basic_land(exact), "holds": [], "wants": [],
              "more": False, "owned": None, "incoming": None, "free": None}
    if answer["basic"]:
        return answer
    try:
        p = pool.load_pool() if space == spaces.HOME else pool.load_pool(space)
        summaries = decks.list_decks()
    except (ValueError, OSError, csv.Error) as error:
        if space == spaces.HOME and not guard.sees_home_records():
            raise ApiError(409, "The collection couldn't be read.") from None
        raise ApiError(409, f"The collection couldn't be read: {_public(error)}") from None
    sees, records = guard.deck_reader(), guard.sees_home_records()
    holds, holding, held = [], set(), 0
    for deck in p.in_use:
        copies = deck.cards[exact]
        if not copies:
            continue
        held += copies
        holding.add(deck.id)
        if named_holder(deck.id, sees, records):
            holds.append({"id": deck.id, "title": deck.title, "why": deck.why, "copies": copies})
    holds.sort(key=lambda d: (d["why"] != "built", d["title"].casefold(), d["id"]))
    wants, unresolved = [], {}
    order = {"building": 0, "idea": 1}
    for summary in summaries:
        deck_id = summary["id"]
        if summary.get("space", spaces.HOME) != space or summary.get("error") or deck_id in holding:
            continue
        try:
            kind = spaces.split_deck_id(deck_id)[1]
        except ValueError:
            continue
        # Deck files only: a product's list is what came in the box, not a want; an intact one holds.
        if kind not in decks.KINDS or not sees(summary):
            continue
        copies = _wanted(summary, exact, unresolved)
        if copies:
            wants.append({"id": deck_id, "title": summary.get("title") or deck_id, "status": summary.get("status"),
                          "copies": copies})
    wants.sort(key=lambda d: (order.get(d["status"], 2), d["title"].casefold(), d["id"]))
    incoming = sum(qty for _, qty in p.on_the_way.get(exact, []))
    owned = max(0, p.owned[exact] - incoming)
    answer.update(holds=holds[:MAX_DECKS], wants=wants[:MAX_DECKS],
                  more=len(holds) > MAX_DECKS or len(wants) > MAX_DECKS,
                  owned=owned, incoming=incoming, free=max(0, owned - held))
    return answer
