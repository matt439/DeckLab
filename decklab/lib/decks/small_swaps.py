"""Small, explainable experiments for casual decks (E2-S33).

This is a deterministic shortlist, not a prediction of a deck's strength. The caller supplies
only physically free copies of Considering cards. Each alternative is one cut/add idea; two
copies may try the same idea when both the list and the pool have room. Nothing writes or runs.
"""
from collections import Counter
from math import inf
import re

from . import swaps

GOALS = ("earlier", "draw", "answers")
MAX_PROPOSALS = 3
ANSWER_ROLES = frozenset(("removal", "counterspell"))


def _mv(card):
    return card.get("cmc") or 0


def _simple_spell(card):
    # A land back face, split cost, X cost or absent mana cost needs more context than
    # these deliberately small heuristics have. Never call a suspend-only or X=0 spell cheap.
    return (card is not None and swaps.primary_type(card) not in (None, "land")
            and len(card.get("faces") or ()) <= 1 and bool(card.get("mana_cost"))
            and "{X}" not in card["mana_cost"])


def _supported_cost(card, colours):
    """Check mana symbols too: devoid changes a card's colours, not its mana cost.

    This shortlist does not qualify colourless or snow sources. Mandatory {C}/{S}
    and unknown symbols are withheld; ordinary hybrid and Phyrexian alternatives
    keep their normal coloured, generic or life-payment options.
    """
    cost = card["mana_cost"]
    if re.fullmatch(r"(?:\{[^{}]+\})+", cost) is None:
        return False
    for symbol in re.findall(r"\{([^{}]+)\}", cost):
        if re.fullmatch(r"[0-9]+", symbol) or symbol in colours:
            continue
        if re.fullmatch(r"2/[WUBRG]|[WUBRG](?:/[WUBRG])?/P", symbol):
            continue
        if re.fullmatch(r"[WUBRGC]/[WUBRGC]", symbol) and set(symbol.split("/")) & colours:
            continue
        return False
    return True


def _copies(card):
    """Ordinary casual four-copy limit, with printed any-number / larger-limit exceptions."""
    from decklab.lib.stats.commander import _copies_allowed
    from decklab.lib.stats.constants import DECK_COPIES_RE
    match = DECK_COPIES_RE.search((card.get("oracle_text") or "").lower())
    if match is None:
        return 4
    allowed = _copies_allowed(card)
    if allowed is None:
        return inf
    return allowed if match.group(1) == "only one" or match.group(3) else max(4, allowed)


def _fit(goal, cut, added):
    """A score and plain-language expectation/trade-off, or None when evidence is too weak."""
    before, after = _mv(cut), _mv(added)
    old_roles, new_roles = set(cut.get("roles") or ()), set(added.get("roles") or ())
    old_type, new_type = swaps.primary_type(cut), swaps.primary_type(added)
    same_slot = old_type == new_type or {old_type, new_type} <= {"instant", "sorcery"}
    lost = sorted(old_roles - new_roles)
    lost_words = f" It also gives up the cut card's {', '.join(lost)} role." if lost else ""
    if goal == "earlier":
        if before < 4 or after > 2 or before - after < 2:
            return None
        if not same_slot and not new_roles & {"draw", "ramp"}:
            return None
        reason = (f"Try an earlier play: {added['name']} has mana value {after:g}, "
                  f"compared with {before:g} for {cut['name']}.")
        trade = "This may smooth the opening turns, but gives up a more expensive late-game play."
        return (-(before - after), not same_slot, after), reason, trade + lost_words
    wanted = {"draw"} if goal == "draw" else ANSWER_ROLES
    if not new_roles & wanted or old_roles & wanted or after > 3:
        return None
    # Preserve the broad kind of slot when adding a role: don't silently turn a creature deck
    # into spells or suggest a new permanent strategy solely from a role tag.
    if not same_slot:
        return None
    if goal == "draw":
        reason = (f"Try another draw option: Deck Lab's card data tags {added['name']} for draw, "
                  f"at mana value {after:g}.")
        trade = ("You trade another effect for access to more cards. Check its draw conditions; "
                 "a draw tag does not guarantee extra cards in every game.")
    else:
        roles = ", ".join(sorted(new_roles & wanted))
        reason = (f"Try another answer: Deck Lab's card data tags {added['name']} for {roles}, "
                  f"at mana value {after:g}.")
        trade = ("You trade a proactive play for a situational answer. Check what it can target "
                 "and when you must hold mana open.")
    if after > before:
        trade += f" It costs {after - before:g} more mana."
    return (after, -before, cut["name"].casefold()), reason, trade + lost_words


def recommend(source, considering, available, card_of, goal, protected=()):
    """Rank at most three alternative one-copy experiments, each with a two-copy capacity.

    source is the selected list's sections, considering its DeckLines, available a name->count
    of on-hand copies after all physical holds and the selected list's own demand. The result
    retains the precise Considering line, so its printing/category can follow a reviewed move.
    """
    if goal not in GOALS:
        raise ValueError("Unknown small-swap goal")
    counts = Counter()
    main = Counter()
    for section, lines in source.items():
        for line in lines:
            counts[line.name] += line.quantity
            if section == "Deck":
                main[line.name] += line.quantity
    colours = swaps.deck_colours({"Deck": source.get("Deck", ())}, "casual", card_of)
    protected = set(protected)
    found = []
    for index, line in enumerate(considering):
        added = card_of(line.name)
        if (not _simple_spell(added) or not swaps.castable(added, colours, "casual")
                or not _supported_cost(added, colours)):
            continue
        capacity = min(2, line.quantity, available.get(line.name, 0), _copies(added) - counts[line.name])
        if capacity < 1:
            continue
        for name, qty in main.items():
            cut = card_of(name)
            if name in protected or name == line.name or not _simple_spell(cut):
                continue
            fit = _fit(goal, cut, added)
            if fit is None:
                continue
            score, reason, trade_off = fit
            found.append((score, name.casefold(), line.name.casefold(), index,
                          {"cut": name, "add": line, "reason": reason, "trade_off": trade_off,
                           "max_qty": min(qty, capacity)}))
    found.sort(key=lambda row: row[:4])
    # Multiple Considering printings of the same name are alternatives of one idea, not extra
    # recommendations. Use the first ranked concrete row; its max_qty never borrows another row.
    seen, out = set(), []
    for *_, proposal in found:
        identity = proposal["cut"], proposal["add"].name
        if identity not in seen:
            seen.add(identity)
            out.append(proposal)
            if len(out) == MAX_PROPOSALS:
                break
    return out
