"""Optional name-level availability for an explicit paste/import review. No prices or writes."""
from decklab.lib import decks, inventory, pool, spaces

from . import common, guard
from .card_lookup import _owned_json
from .collection import space_param
from .common import ApiError, _keys
from .library import _find_summary, _load_pool, check_deck_id


def availability(sections, context):
    """Use only the visible target deck's space, or an explicitly readable new space.

    Results keep the existing pool meaning: by card name, independent of printing.
    The normal inventory projection redacts hidden holders and home's deliveries.
    """
    if not isinstance(context, dict):
        raise ApiError(400, "The import review needs its editor context")
    _keys(context, (), ("id", "space"))
    deck_id = context.get("id")
    if deck_id is not None:
        if "space" in context:
            raise ApiError(400, "Use a saved deck id or a new deck's space, not both")
        check_deck_id(deck_id)
        summary = _find_summary(deck_id)       # ordinary hidden/missing deck equivalence
        space = summary.get("space", spaces.space_of(deck_id))
    else:
        space = space_param(context.get("space"))
        guard.require_sees_inventory(space)
    if not guard.sees_inventory(space):
        return {"marks": False, "availability": None, "availability_error": None}
    with common.state_errors():
        stale = inventory.current().stale
    if stale:
        return {"marks": False, "availability": None, "availability_error": "Availability couldn't be confirmed from a current collection snapshot. Nothing is reserved or saved."}
    warnings = []
    p = _load_pool(warnings, space)
    if p is None:
        return {"marks": False, "availability": None, "availability_error": "Availability couldn't be checked. Nothing is reserved or saved."}
    parsed = {section: [decks.DeckLine(row["qty"], row["name"], row.get("set"), row.get("number"), row.get("finish") or "nonfoil",
                                      row.get("category")) for row in rows] for section, rows in sections.items()}
    result = _owned_json(pool.compare(parsed, p, pool.self_ids(deck_id) if deck_id else (), prices=False), p)
    # No prices are requested. The supplied candidate sections and the pool's
    # established hidden-holder projection are the only facts in this response.
    return {"marks": True, "availability": result, "availability_error": None}
