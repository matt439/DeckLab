"""Read-only, on-hand Considering recommendations for a saved casual deck (E2-S33)."""
from collections import Counter

from decklab.lib import cards, decks, pool
from decklab.lib.decks import small_swaps

from . import drafts, guard
from .card_lookup import _line_json, _pickable, _resolve
from .common import ApiError, _keys, _parse_body
from .settings import _writer
from .swaps import VERSIONS, _deck, _space_pool

INCOMPLETE = ("Free copies could not be checked completely. Resolve the collection or built-deck "
              "warnings, then ask again.")
NO_FIT = ("No small change fits this goal using free cards on Considering. Try another goal, "
          "keep fewer cards off-limits, or add an alternative to Considering.")


def _own_inventory(space):
    """Free counts derive private deck holds; public collection access alone cannot expose them."""
    viewer = guard.viewer()
    if not guard.script() and (viewer is None or (viewer.get("space") or "home") != space):
        raise ApiError(403, "That collection isn't public.")


def _protected(raw, main):
    if not isinstance(raw, list) or len(raw) > 60:
        raise ApiError(400, "protected must list up to 60 cards to keep in the main deck")
    out = set()
    for name in raw:
        exact = _resolve(name) if isinstance(name, str) and 0 < len(name) <= 200 else None
        if exact is None or exact not in main:
            raise ApiError(400, "Every protected card must be a card in this main deck")
        out.add(exact)
    return out


def _on_hand(p, deck_id, demand):
    """Free physical capacity, reserving this deck's physical stand-ins as well as logical demand."""
    mine = pool.self_ids(deck_id)
    free = pool.free_copies(p, mine)
    own_holds = Counter()
    for hold in p.in_use:
        if hold.id in mine:
            own_holds.update(hold.cards)
    return {name: max(qty - sum(n for _, n in p.on_the_way.get(name, ()))
                      - max(demand.get(name, 0), own_holds.get(name, 0)), 0)
            for name, qty in free.items()}


def _has_playable_printing(line):
    """Keep the source finish even where the editor could choose a different default."""
    card = cards.card(line.name)
    return card is not None and any(
        (not line.set or set_code == line.set) and (not line.number or number == line.number)
        and (printing := cards.printing(set_code, number)) is not None
        and _pickable(printing) and line.finish in printing["finishes"]
        for set_code, number in card["printings"])


def suggest_small_swaps(body):
    """POST /api/deck/small-swaps: suggestions only; never saves, reserves cards or starts games.

    {profile,id,version?,goal,protected?} -> {deck_id,version,sha256,goal,proposals,reason}.
    Each proposal has cuts/adds (one copy), reason, trade_off and max_qty (one or two copies of
    that same experiment). The saved deck hash binds later explicit review to this exact list.
    """
    data = _parse_body(body)
    _writer(data)
    _keys(data, ("profile", "id", "goal"), ("version", "protected"))
    summary, deck = _deck(data["id"])       # hidden deck's 404 before semantic request validation
    _own_inventory(deck.space)
    version = data.get("version", "target")
    if version not in VERSIONS:
        raise ApiError(400, "version must be target or owned")
    if deck.kind != "casual":
        raise ApiError(400, "Small swaps are for saved casual 60-card decks")
    source = deck.target if version == "target" else deck.owned
    if not source:
        raise ApiError(404, "This deck has no selected list")
    if source.get("Commander") or sum(l.quantity for l in source.get("Deck", ())) != 60:
        raise ApiError(400, "Small swaps need a main deck of exactly 60 cards")
    goal = data["goal"]
    if not isinstance(goal, str) or goal not in small_swaps.GOALS:
        raise ApiError(400, "Choose earlier, draw or answers as the goal")
    # Normalize all sections once. Unknown cards stop a recommendation: their colours, demand
    # and role cannot be assumed, including when an unknown line is only in the sideboard.
    demand, normalized = Counter(), {}
    for section, lines in source.items():
        normalized[section] = []
        for line in lines:
            name = _resolve(line.name)
            if name is None:
                return _answer(summary, deck, version, goal, reason="Check the deck's unknown card names first.")
            normalized[section].append(decks.DeckLine(line.quantity, name, line.set, line.number,
                                                       line.finish, line.category))
            demand[name] += line.quantity
    main = {l.name for l in normalized.get("Deck", ())}
    protected = _protected(data.get("protected", []), main)
    if any(not decks.is_basic_land(name) and cards.card(name) is not None
           and qty > small_swaps._copies(cards.card(name)) for name, qty in demand.items()):
        return _answer(summary, deck, version, goal, reason="Check the deck's copy limits first.")
    if not deck.considering:
        return _answer(summary, deck, version, goal,
                       reason="Add alternatives to this deck's Considering list, then ask again.")
    warnings = []
    p = _space_pool(deck.space, warnings)
    if warnings or p.warnings or p.unresolved:
        return _answer(summary, deck, version, goal, reason=INCOMPLETE)
    available = _on_hand(p, summary["id"], demand)
    considering = []
    validator = drafts._Draft(deck.kind, space=deck.space)
    for line in deck.considering:
        name = _resolve(line.name)
        if name is not None:
            raw = {"name": name, "qty": line.quantity, "set": line.set, "number": line.number,
                   "finish": line.finish, "category": line.category}
            # Check as a new Planned line before ranking/deduplication, so a malformed legacy
            # Considering row cannot hide a valid alternative. Keep the original source details:
            # validation may choose a default printing for a setless line, but the linked move
            # must still match the exact Considering row the user saved.
            if drafts._read_line(validator, raw, {"list": "target", "section": "Deck"}) is not None:
                candidate = decks.DeckLine(line.quantity, name, line.set, line.number, line.finish, line.category)
                if _has_playable_printing(candidate):
                    considering.append(candidate)
    proposals = []
    for idea in small_swaps.recommend(normalized, considering, available, cards.card, goal, protected):
        added = idea["add"]
        # _line_json preserves a named Considering printing and category. A malformed printing
        # is not silently promoted into a playable list through this entry point.
        line_warnings = []
        added_json = _line_json(decks.DeckLine(1, added.name, added.set, added.number,
                                               added.finish, added.category), "Considering", line_warnings)
        if line_warnings:
            continue
        proposals.append({"cuts": [{"name": idea["cut"], "qty": 1}], "adds": [added_json],
                          "reason": idea["reason"], "trade_off": idea["trade_off"],
                          "max_qty": idea["max_qty"]})
    return _answer(summary, deck, version, goal, proposals, None if proposals else NO_FIT)


def _answer(summary, deck, version, goal, proposals=None, reason=None):
    return {"deck_id": summary["id"], "version": version, "sha256": deck.sha256, "goal": goal,
            "proposals": proposals or [], "reason": reason}
