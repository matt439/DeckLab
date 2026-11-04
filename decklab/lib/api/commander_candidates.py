"""The Collection page's "Commanders we could build" (E9-S28, first slice): the space's free legendary
creatures ranked by how much of a Commander deck the rest of its free pool covers in each one's colours,
counted by the Command Zone template's role targets. Writes nothing; imported when first needed, by
feature_routes.dispatch.

    GET /api/commanders/candidates?space=<id>&limit=<n>     candidates_view()
    GET /api/commanders/candidate?name=<card>&space=<id>    candidate_view(): one candidate's free cards
                                                            by name (E9-S28's second slice)

What counts is lib/decks/commander_pool.py's. The answer is the space's inventory's
(guard.require_sees_inventory: the Collection page's 403, "That collection isn't public.", for a space the
viewer may not see or that doesn't exist). Free copies are pool.free_copies': owned or on the way, less
what built decks and intact products hold; no answer names the decks holding them.
"""
from decklab.lib import cards, pool
from decklab.lib.decks import commander_pool

from . import guard
from .card_lookup import _card_json, _shown_printing
from .carddata import _require_cards
from .collection import _integer, space_param
from .common import ApiError, MAX_NAME, _CONTROL_RE
from .precon_coverage import _pool
from .role_cards import _tag_counts

MAX_LIMIT = 200


def _rules():
    """(may_lead, partners in words, the template's categories and source): lib/stats' rules, imported
    when first asked for (the API tests' stand-in stats module leaves its submodules in place)."""
    from decklab.lib.stats import commander, role_targets
    return (commander._can_be_commander, lambda card: list(commander._partner_abilities(card).values()),
            role_targets.CATEGORIES,
            {"id": role_targets.SOURCE_ID, "episode": role_targets.EPISODE,
             "episode_date": role_targets.EPISODE_DATE, "checked": role_targets.CHECKED,
             "title": role_targets.SOURCE["title"], "url": role_targets.SOURCE["url"]})


def candidates_view(space=None, limit=None):
    """GET /api/commanders/candidates: {"space", "candidates" (commander_pool.candidates' best first, at
    most limit, each with its "card" and
    "free" copies), "total" (how many there are), "source" (the role targets' template),
    "tags_available" (False when the card data holds no role tag: every role count is then 0)}.
    403 as the Collection page for a space the viewer may not see."""
    space = space_param(space)
    guard.require_sees_inventory(space)
    limit = _integer(limit, "limit", commander_pool.LIMIT, MAX_LIMIT)
    _require_cards()
    free = pool.free_copies(_pool(space))
    may_lead, partners, categories, source = _rules()
    ranked = commander_pool.candidates(free, cards.card, may_lead, categories, partners)
    shown = []
    for row in ranked[:limit]:
        card = cards.card(row["name"])
        shown.append({**row, "free": free.get(row["name"], 0), "card": _card_json(card, _shown_printing(card))})
    tagged = _tag_counts()
    return {"space": space, "candidates": shown, "total": len(ranked), "source": source,
            "tags_available": any(tagged.get(role) for role in cards.ROLES)}


def candidate_view(name=None, space=None):
    """GET /api/commanders/candidate?name=&space=: one candidate's free cards by name
    (commander_pool.cards_for), each with "card" (its JSON, for its picture): {"space", "name", "colours",
    "categories", "others", "source"}. The same reading rule as candidates_view (403 first); then 400 for a
    missing or malformed name and 404 for a card that isn't a candidate in the space (no copy free, not
    legal in Commander, or not one that may be a commander), naming no deck holding it."""
    space = space_param(space)
    guard.require_sees_inventory(space)
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or _CONTROL_RE.search(name):
        raise ApiError(400, f"name is required: the candidate's card name, 1-{MAX_NAME} characters.")
    _require_cards()
    exact = cards.resolve(name.strip()) or name.strip()
    free = pool.free_copies(_pool(space))
    may_lead, _, categories, source = _rules()
    found = commander_pool.cards_for(exact, free, cards.card, may_lead, categories)
    if found is None:
        raise ApiError(404, f"{exact} isn't a commander we could build from this collection: it needs a copy "
                            "free, to be legal in Commander and to be able to lead a deck.")

    def pictured(rows):
        return [{**row, "card": _card_json(c, _shown_printing(c))} for row in rows for c in [cards.card(row["name"])]]

    for part in found["categories"]:
        part["cards"] = pictured(part["cards"])
    found["others"]["cards"] = pictured(found["others"]["cards"])
    card = cards.card(exact)
    return {"space": space, "name": exact, "colours": [x for x in "WUBRG" if x in (card.get("color_identity") or ())],
            **found, "source": source}
