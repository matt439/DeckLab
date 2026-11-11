"""One public local card lookup and an independently guarded own-printing/location projection."""
from decklab.lib import cards, inventory
from . import common, guard
from .card_decks import _name
from .card_lookup import _card_json, _resolve, _shown_printing
from .carddata import _require_cards
from .collection import space_param
from .collection_edit import _view
from .common import ApiError, NUMBER_RE, SET_RE


def card_view(name=None, set=None, number=None):
    """Public card data only; never the autocomplete's collection-derived defaults/counts."""
    name = _name(name)
    _require_cards()
    exact = _resolve(name)
    if not exact:
        raise ApiError(404, "That card isn't in the current card data")
    card = cards.card(exact)
    shown = None
    if set or number:
        if not (isinstance(set, str) and SET_RE.fullmatch(set)
                and isinstance(number, str) and NUMBER_RE.fullmatch(number)):
            raise ApiError(400, "Choose a set and collector number together")
        shown = cards.printing(set, number)
        printed = cards.printing_card(set, number) if shown else None
        if printed is None or printed["name"] != card["name"]:
            raise ApiError(404, "That printing isn't listed for this card")
        card = printed
    return {"card": _card_json(card, shown or _shown_printing(card))}


def copies_view(name=None, space=None):
    """Owned physical collection rows only; a Public deck never grants these counts/locations."""
    space = space_param(space)
    guard.require_sees_inventory(space)
    name = _name(name)
    _require_cards()
    exact = _resolve(name)
    if not exact:
        raise ApiError(404, "That card isn't in the current card data")
    with common.state_errors():
        inv = inventory.current()
    rows, _sha = _view(inv.collection(space))
    locations = inv.locations_of(space)
    found = []
    for row in rows:
        if _resolve(row["name"]) != exact:
            continue
        key = (row["set"], row["collector_number"], row["finish"])
        found.append({"set": key[0], "number": key[1], "finish": key[2],
                      "quantity": int(row["quantity"]), "location": locations.get(key) or None})
    return {"name": exact, "space": space, "printings": found,
            "note": "Recorded storage locations; some copies may be in decks. Ordinary basic land copies aren't all tracked."}
