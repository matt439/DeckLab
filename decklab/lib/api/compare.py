"""The compare page's cards both lists use (E1-S13, its second slice): GET /api/compare/shared.
Imported when first needed, by feature_routes.dispatch.

    GET /api/compare/shared?a=<deck id>&av=target|owned&b=<deck id>&bv=target|owned   shared_view()

Each list is read as its deck page reads it (library._deck_sections: a deck the viewer may not
see answers as a missing one, E10-S30's 404, before anything of the other is read). The cards
both use are named for everyone who sees both decks; how many copies the pool can cover for both
only for a viewer who sees the space's inventory (guard.sees_inventory), and only when the two
decks share a space: each space is a separate physical collection. The counts are pool's: owned
(on the way included) less what other built decks and intact products hold, the two compared
decks' own holds counted free (pool.free_copies with both decks' self_ids). No answer names the
decks holding copies.

Two decks are played at once, so a card's need is both lists' copies together; one deck's two
lists (or one list against itself) are never assembled at once, so its need is the larger.
"""
from decklab.lib import pool, spaces

from . import guard
from .common import ApiError
from .library import VERSIONS, _deck_sections, _load_pool


def _version(value, name):
    value = value or "target"
    if value not in VERSIONS:
        raise ApiError(400, f"{name} must be one of: {', '.join(VERSIONS)}")
    return value


def _side(deck_id, version, name):
    """(summary, {canonical name: copies}) of one list, basic lands left out (pool's counting)."""
    if not deck_id:
        raise ApiError(400, f"{name} must name a deck")
    if deck_id.startswith("pairing/"):
        deck_id = deck_id.replace(" ", "+")      # a "+" typed into the address bar arrives as a space
    summary, sections = _deck_sections(deck_id, _version(version, f"{name}v"))
    return summary, pool._count_sections(sections, summary["id"], {})


def shared_view(a=None, av=None, b=None, bv=None):
    """GET /api/compare/shared: {"a", "b" ({"id", "version"}: the library's ids), "together"
    (true when the need is both lists' copies added up, false for one deck's lists: the larger),
    "counts" (whether the cards carry pool counts), "why_no_counts" (a sentence, or None: the
    decks are in separate collections, or the pool couldn't be read; nothing for a viewer who
    may not see the inventory), "cards" ([{"name", "a", "b" (each list's copies), "need", and
    with counts "owned" (on the way included), "on_the_way", "free" (copies no other built deck
    or intact product holds) and "short" (need less free, at least 0)}], the shortest first,
    then by name), "warnings"}. 400 for a bad id or version; 404 for a deck or list the viewer
    can't see or that doesn't exist (as GET /api/deck)."""
    sa, ca = _side(a, av, "a")
    sb, cb = _side(b, bv, "b")
    ida, idb = sa["id"], sb["id"]
    own_a, own_b = pool.self_ids(ida), pool.self_ids(idb)
    together = not (own_a & own_b)
    space = spaces.space_of(ida)
    warnings, why, p = [], None, None
    if space != spaces.space_of(idb):
        why = "These decks are in separate collections, so no copies are counted for both."
    elif guard.sees_inventory(space):
        p = _load_pool(warnings, space)
        if p is None:
            why = "The collection couldn't be read, so no copies are counted."
    free = pool.free_copies(p, own_a | own_b) if p is not None else None
    cards = []
    for name in sorted(set(ca) & set(cb)):
        need = ca[name] + cb[name] if together else max(ca[name], cb[name])
        row = {"name": name, "a": ca[name], "b": cb[name], "need": need}
        if free is not None:
            spare = free.get(name, 0)
            row.update(owned=p.owned.get(name, 0), on_the_way=sum(qty for _, qty in p.on_the_way.get(name, [])),
                       free=spare, short=max(need - spare, 0))
        cards.append(row)
    if free is not None:
        cards.sort(key=lambda row: (row["short"] == 0, row["name"]))
    return {"a": {"id": ida, "version": av or "target"}, "b": {"id": idb, "version": bv or "target"},
            "together": together, "counts": free is not None, "why_no_counts": why, "cards": cards,
            "warnings": warnings}

