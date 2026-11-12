"""Where a space's copies of a card are already filed (E8-S22's locations, E8-S27's lookup).

by_name(inv, space, wanted) is the name-keyed lookup Build decks' storage_locations and
Where these go share: {name: [location, ...]}, the distinct locations recorded on the space's
collection rows of each wanted card (any printing: copies are filed by name), in the collection's
row order. A card none of whose rows has a location isn't listed.

advice(inv, space, names) is Where these go's bounded answer (E8-S27), from the one snapshot the
advice itself is built from:

    {"ready": bool, "cards": {name: {"places": [at most 3 locations], "more": N}}}

every looked-up name is listed (places [] means "No location recorded yet"); ready is False while
the database lacks migration 0016 (then cards is {} and the page says locations are unavailable).
It raises ValueError past its bounds; callers leave the field out then, and the save and the rest
of its advice stand. The caller has already checked that the viewer reads the space's inventory.
"""
from decklab.lib import cards
from decklab.lib.inventory import rules

MAX_NAMES = 5000
MAX_SHOWN = 3


def _named(name):
    try:
        return cards.resolve(name) or name
    except RuntimeError:            # the card index went away meanwhile: the name as written
        return name


def by_name(inv, space, wanted):
    """{name: [locations in collection row order]} for the wanted names that have any."""
    wanted = set(wanted)
    found = inv.locations_of(space) if wanted else {}
    out = {}
    if not found:
        return out
    for row in inv.collection(space).rows:
        try:
            key = rules.ident(row)
        except KeyError:
            continue
        place = found.get(key)
        if not place:
            continue
        written = row.text("name")
        name = written if written in wanted else _named(written)
        if name in wanted and place not in out.setdefault(name, []):
            out[name].append(place)
    return {name: places for name, places in out.items() if places}


def advice(inv, space, names):
    """The bounded storage_locations answer (see the module docstring)."""
    names = sorted({name for name in names if isinstance(name, str) and name})
    if len(names) > MAX_NAMES:
        raise ValueError("Too many cards to look up")
    if not inv.locations_ready:
        return {"ready": False, "cards": {}}
    found = by_name(inv, space, names)
    out = {}
    for name in names:
        places = found.get(name, [])
        out[name] = {"places": places[:MAX_SHOWN], "more": max(len(places) - MAX_SHOWN, 0)}
    return {"ready": True, "cards": out}
