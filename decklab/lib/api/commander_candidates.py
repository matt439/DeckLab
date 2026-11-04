"""The Collection page's "Commanders we could build" (E9-S28, first slice): the space's free legendary
creatures ranked by how much of a Commander deck the rest of its free pool covers in each one's colours,
counted by the Command Zone template's role targets. Writes nothing; imported when first needed, by
feature_routes.dispatch.

    GET /api/commanders/candidates?space=<id>&limit=<n>     candidates_view()

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
