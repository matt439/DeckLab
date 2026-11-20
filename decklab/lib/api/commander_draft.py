"""Read-only review of a Commander draft from the space's physically free pool."""
from decklab.lib import cards, pool, spaces
from decklab.lib.decks import commander_draft
from decklab.lib.decks.role_pool import fits

from . import guard
from .card_lookup import _card_json, _shown_printing
from .carddata import _require_cards
from .collection import space_param
from .commander_candidates import _name, _rules
from .common import ApiError, _keys, _parse_body
from .precon_coverage import _pool
from .role_cards import _tag_counts
from .settings import _writer


def _affinity(names):
    from decklab.lib import edhrec_cuts
    try:
        page = edhrec_cuts.cached_page(names)
        if page:
            return page["url"], edhrec_cuts._inclusions(page)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None, {}


def preview(body):
    data = _parse_body(body)
    space = space_param(data.get("space"))
    guard.require_sees_inventory(space)
    profile = _writer(data) if "profile" in data else guard.viewer()
    guard.require(profile, "deck.create", {"space": space, "player": None})
    _keys(data, ("name",), ("space", "partner", "locked", "profile"))
    locked = data.get("locked", [])
    if not isinstance(locked, list) or len(locked) > 99:
        raise ApiError(400, "Lock up to 99 cards by name.")
    _require_cards()
    names = [_name(data["name"], "name")]
    if data.get("partner") not in ("", None):
        names.append(_name(data["partner"], "partner"))
    locked = [_name(n, "locked card") for n in locked]
    p = _pool(space)
    if p.warnings or p.unresolved:
        raise ApiError(409, "Resolve the collection or deck list warnings before building from free copies.")
    spare = pool.free_copies(p)
    free = pool.physical_free_copies(p, spare)
    rules = _rules()
    tag = rules.commander.MASS_LAND_DENIAL_TAG
    try:
        denial = cards.tag_members([tag], rules.commander.TAG_FILE)[tag]
    except (OSError, ValueError, KeyError):
        denial = None
    try:
        result = commander_draft.build(names, locked, free, cards.card, rules, denial, _affinity)
    except ValueError as error:
        raise ApiError(400, str(error)) from None

    def pictured(name):
        card = cards.card(name)
        return _card_json(card, _shown_printing(card))

    tagged = _tag_counts()
    missing = [r for r in cards.ROLES if not tagged.get(r)]
    if missing:
        result["warnings"].append("Role tag coverage is unavailable for " + ", ".join(missing) + ".")
    result["commanders"] = [{"name": n, "card": pictured(n)} for n in names]
    for row in result["picks"]:
        row["card"] = pictured(row["name"])
    identity = set(result["colours"])
    result["incoming"] = [{"name": n, "quantity": q} for n, q in sorted((spare - free).items())
                          if commander_draft.known_identity(cards.card(n))
                          and fits(cards.card(n), identity)
                          ] if space == spaces.HOME and guard.sees_home_records() else []
    return {**result, "space": space, "source": rules.source}
