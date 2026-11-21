"""Reviewed, one-for-one Commander precon upgrades using free copies on hand (E9-S40)."""
from collections import Counter
from dataclasses import replace

from decklab.lib import cards, decks
from decklab.lib.decks import small_swaps, swaps
from decklab.lib.decks.commander_draft import known_identity

from . import drafts, guard
from .bracket_fixes import _checked_minimum
from .card_lookup import _line_json, _resolve
from .common import ApiError, _keys, _parse_body
from .comparison_lists import published_precon
from .deck_page import _deck_stats
from .settings import _writer
from .small_swaps import INCOMPLETE, _on_hand, _own_inventory
from .swaps import _deck, _space_pool

GOAL = "early-interaction"


def _pair_options(source, stock, demand, available):
    """Rank early answers against other spells in the current list, preferring stock cuts."""
    identity = swaps.deck_colours(source, "commander", cards.card)
    protected = {_resolve(line.name) for section in ("Commander", "Companion") for line in source.get(section, ())}
    slots = []
    for index, line in enumerate(source.get("Deck", ())):
        name = _resolve(line.name)
        card = cards.card(name)
        if name not in protected and small_swaps._simple_spell(card):
            slots.append((index, name, card))
    options = []
    for name, qty in available.items():
        if qty < 1 or demand[name]:
            continue
        added = cards.card(name)
        if (not known_identity(added) or added.get("commander_legality") != "legal"
                or not swaps.castable(added, identity, "commander") or not small_swaps._simple_spell(added)
                or not small_swaps.ANSWER_ROLES.intersection(added.get("roles") or ())
                or not small_swaps._supported_cost(added, identity)):
            continue
        for index, cut_name, cut in slots:
            fit = small_swaps._fit("answers", cut, added)
            if fit is not None:
                score, reason, trade_off = fit
                lost_roles = set(cut.get("roles") or ()) - set(added.get("roles") or ())
                rank = (cut_name not in stock, len(lost_roles), score, name.casefold(), index)
                options.append((rank, index, name, reason, trade_off))
    return sorted(options)


def _trial(source, index, addition):
    rows = list(source["Deck"])
    cut = rows[index]
    if cut.quantity == 1:
        del rows[index]
    else:
        rows[index] = replace(cut, quantity=cut.quantity - 1)
    return {**source, "Deck": [*rows, addition]}


def suggest_upgrades(body):
    """Preview against the saved Planned list. Building a draft still needs explicit review."""
    data = _parse_body(body)
    _writer(data)
    _keys(data, ("profile", "id", "file", "goal"), ())
    summary, deck = _deck(data["id"])
    _own_inventory(deck.space)
    guard.require(guard.viewer(), "deck.edit", deck)
    if deck.kind != "commander" or data["goal"] != GOAL:
        raise ApiError(400, "Choose a saved Commander deck and the early interaction goal.")
    entry, kind, precon = published_precon(data["file"])
    if kind != "commander":
        raise ApiError(400, "Choose a published Commander precon.")
    answer = {"deck_id": summary["id"], "sha256": deck.sha256, "goal": GOAL, "file": entry["file"],
              "target_bracket": deck.target_bracket, "before_minimum": None, "proposals": [], "reason": None}
    source = deck.target
    before = (_deck_stats(source, "commander", []) or {}) if source else {}
    if before.get("unresolved") or not (before.get("commander") or {}).get("ok"):
        return {**answer, "reason": "Check the saved Planned list's card names and Commander rules first."}
    answer["before_minimum"] = _checked_minimum(before)
    warnings = []
    pool = _space_pool(deck.space, warnings)
    if warnings or pool.warnings or pool.unresolved:
        return {**answer, "reason": INCOMPLETE}
    demand = Counter()
    for lines in source.values():
        for line in lines:
            demand[_resolve(line.name)] += line.quantity
    available = _on_hand(pool, summary["id"], demand)
    stock = {_resolve(line.name) for line in precon.get("Deck", ())}
    seen = set()
    for _, index, name, reason, trade_off in _pair_options(source, stock, demand, available):
        if name in seen:
            continue
        seen.add(name)
        if len(seen) > 6:
            break  # at most six full rules/bracket checks, including failed trials
        # Use name-level availability like the pool. The normal edit flow picks a playable
        # printing; the free copy count does not promise the same printing as the preview image.
        validator = drafts._Draft("commander", space=deck.space)
        addition = drafts._read_line(validator, {"qty": 1, "name": name}, {"list": "target", "section": "Deck"})
        if addition is None:
            continue
        after = _deck_stats(_trial(source, index, addition), "commander", []) or {}
        if after.get("unresolved") or not (after.get("commander") or {}).get("ok"):
            continue
        cut = source["Deck"][index]
        answer["proposals"].append({"cut": _line_json(replace(cut, quantity=1), "Deck", []),
                                    "add": _line_json(decks.DeckLine(1, name), "Deck", []),
                                    "free": available[name], "stock_cut": _resolve(cut.name) in stock,
                                    "reason": reason, "trade_off": trade_off, "after_minimum": _checked_minimum(after)})
        if len(answer["proposals"]) == small_swaps.MAX_PROPOSALS:
            break
    if not answer["proposals"]:
        answer["reason"] = "No free copy on hand fits an early interaction swap in this Planned list."
    return answer
