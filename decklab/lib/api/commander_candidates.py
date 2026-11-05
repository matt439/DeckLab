"""The Collection page's "Commanders we could build" (E9-S28): the space's free legendary creatures (and
pairs of them) ranked by how much of a Commander deck the rest of its free pool covers in their colours,
counted by the Command Zone template's role targets. Writes nothing; imported when first needed, by
feature_routes.dispatch.

    GET /api/commanders/candidates?space=<id>&limit=<n>     candidates_view()
    GET /api/commanders/candidate?name=<card>&partner=<card>&space=<id>
                                                            candidate_view(): one candidate's (or pair's)
                                                            free cards by name (E9-S28's second slice)

What counts is lib/decks/commander_pool.py's. The answer is the space's inventory's
(guard.require_sees_inventory: the Collection page's 403, "That collection isn't public.", for a space the
viewer may not see or that doesn't exist). Free copies are pool.free_copies': owned or on the way, less
what built decks and intact products hold.

E9-S28's third slice: pairs of free cards that may be two commanders together (partners, partner with,
partner—[text] such as Friends forever, Choose a Background with a Background, Doctor's companion with a
Time Lord Doctor: lib/stats/commander.py's _pairing, each half able to lead or being that Background) rank
with the single candidates; and a card that may lead whose every copy a built deck or intact product holds
is a held row, listed apart after the free ones ("held", never mixed into the ranking), naming the decks
holding it as the Collection page names holders (collection._holders: a deck the viewer may not see is
"one of the home decks", and a product only to home's record readers).
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

# _pairing's kinds in words (partner—[text] is already its words, such as "partner—Friends forever").
PAIRING_WORDS = {"partner": "partner", "partner with": "partner with", "background": "Choose a Background",
                 "doctor": "Doctor's companion"}


class _Rules:
    """lib/stats' rules, imported when first asked for (the API tests' stand-in stats module leaves its
    submodules in place): may_lead, partners (in words), pairable, pair_rule, the template's categories
    and its source."""

    def __init__(self):
        from decklab.lib.stats import commander, role_targets
        self.commander = commander
        self.may_lead = commander._can_be_commander
        self.categories = role_targets.CATEGORIES
        self.source = {"id": role_targets.SOURCE_ID, "episode": role_targets.EPISODE,
                       "episode_date": role_targets.EPISODE_DATE, "checked": role_targets.CHECKED,
                       "title": role_targets.SOURCE["title"], "url": role_targets.SOURCE["url"]}

    def partners(self, card):
        return list(self.commander._partner_abilities(card).values())

    def pairable(self, card):
        c = self.commander
        return bool(c._partner_abilities(card)) or c._is_background(card) or c._is_doctor(card)

    def pair_rule(self, a, b):
        """The pairing's words when a and b may be your two commanders (702.124), else None: _pairing's
        kinds, each half able to be a commander, or the Background a Choose a Background commander takes."""
        c = self.commander
        kind = c._pairing(a, b)
        if kind is None:
            return None
        for card in (a, b):
            if not c._can_be_commander(card) and not (kind == "background" and c._is_background(card)):
                return None
        return PAIRING_WORDS.get(kind, kind)


def _rules():
    return _Rules()


def _faces(row, free):
    return [{"name": n, "free": free.get(n, 0), "card": _card_json(c, _shown_printing(c))}
            for n in row["names"] for c in [cards.card(n)]]


def candidates_view(space=None, limit=None):
    """GET /api/commanders/candidates: {"space", "candidates" (single candidates and pairs, best first by
    the same coverage, at most limit; each with "kind" ("single" or "pair"), "names", "faces" ([{"name",
    "free", "card"}], one a name), its first face's "card" and "free" copies, and a pair's "pairing"),
    "total" (how many there are), "pairs" ({"found", "left_out", "untried"}: commander_pool.pairs' caps),
    "held" (held rows, best first, at most commander_pool.MAX_HELD, each with "held_by": [{"id", "title",
    "quantity"}], a deck the viewer may not see by its space's words and no id), "held_total", "source"
    (the role targets' template), "tags_available" (False when the card data holds no role tag: every
    role count is then 0)}. 403 as the Collection page for a space the viewer may not see."""
    space = space_param(space)
    guard.require_sees_inventory(space)
    limit = _integer(limit, "limit", commander_pool.LIMIT, MAX_LIMIT)
    _require_cards()
    p = _pool(space)
    free = pool.free_copies(p)
    rules = _rules()
    singles = commander_pool.candidates(free, cards.card, rules.may_lead, rules.categories, rules.partners)
    paired, caps = commander_pool.pairs(free, cards.card, rules.pairable, rules.pair_rule, rules.categories,
                                        commander_pool.MAX_PAIRABLE, commander_pool.MAX_PAIRS)
    ranked = commander_pool.best_first(singles + paired)
    shown = []
    for row in ranked[:limit]:
        faces = _faces(row, free)
        shown.append({**row, "faces": faces, "free": faces[0]["free"], "card": faces[0]["card"]})
    held_rows = commander_pool.held(p.owned, free, cards.card, rules.may_lead, rules.categories, rules.partners)
    from .collection import _holders
    sees = guard.deck_reader()
    held = []
    for row in held_rows[:commander_pool.MAX_HELD]:
        faces = _faces(row, free)
        held.append({**row, "faces": faces, "free": 0, "card": faces[0]["card"],
                     "held_by": _holders(p, row["name"], sees)})
    tagged = _tag_counts()
    return {"space": space, "candidates": shown, "total": len(ranked), "pairs": caps,
            "held": held, "held_total": len(held_rows), "source": rules.source,
            "tags_available": any(tagged.get(role) for role in cards.ROLES)}


def _name(value, what):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_NAME or _CONTROL_RE.search(value):
        raise ApiError(400, f"{what} is required: the candidate's card name, 1-{MAX_NAME} characters.")
    return cards.resolve(value.strip()) or value.strip()


def candidate_view(name=None, space=None, partner=None):
    """GET /api/commanders/candidate?name=&partner=&space=: one candidate's free cards by name
    (commander_pool.cards_for), each with "card" (its JSON, for its picture): {"space", "name", "names",
    "colours", "categories", "others", "source", "pairing" (a pair's words, else None), "held_by" (a held
    candidate's holders, as candidates_view's; [] for a free one)}. partner names a pair's second card.
    The same reading rule as candidates_view (403 first); then 400 for a missing or malformed name and
    404 for a card (or pair) that isn't a candidate in the space (no copy free and not held, not legal in
    Commander, or not one that may be a commander, or two that can't be commanders together), naming no
    deck holding it."""
    space = space_param(space)
    guard.require_sees_inventory(space)
    _name(name, "name")
    if partner not in (None, ""):
        _name(partner, "partner")
    _require_cards()
    names = [_name(name, "name")] + ([_name(partner, "partner")] if partner not in (None, "") else [])
    p = _pool(space)
    free = pool.free_copies(p)
    rules = _rules()
    held = [n for n, qty in p.owned.items() if qty > 0 and free.get(n, 0) <= 0] if len(names) == 1 else []
    found = commander_pool.cards_for(names if len(names) == 2 else names[0], free, cards.card, rules.may_lead,
                                     rules.categories, pair_rule=rules.pair_rule, held=held)
    if found is None:
        what = " and ".join(names)
        raise ApiError(404, f"{what} isn't a commander we could build from this collection: it needs a copy "
                            "free (or held by a deck), to be legal in Commander and to be able to lead a deck"
                            + (", and the two must be able to be commanders together." if len(names) == 2 else "."))

    def pictured(rows):
        return [{**row, "card": _card_json(c, _shown_printing(c))} for row in rows for c in [cards.card(row["name"])]]

    for part in found["categories"]:
        part["cards"] = pictured(part["cards"])
    found["others"]["cards"] = pictured(found["others"]["cards"])
    identity = set().union(*(cards.card(n).get("color_identity") or () for n in names))
    pairing = rules.pair_rule(cards.card(names[0]), cards.card(names[1])) if len(names) == 2 else None
    held_by = []
    if len(names) == 1 and free.get(names[0], 0) <= 0:
        from .collection import _holders
        held_by = _holders(p, names[0], guard.deck_reader())
    return {"space": space, "name": " and ".join(names), "names": names,
            "colours": [x for x in "WUBRG" if x in identity], **found, "source": rules.source,
            "pairing": pairing, "held_by": held_by}
