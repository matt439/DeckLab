"""Counted bracket-cut plans and inventory-private, read-only replacement checks."""
import traceback

from decklab.lib import cards, decks
from decklab.lib.stats.commander import bracket_fixes
from . import common, deck_aliases, guard
from .common import ApiError, MAX_NAME, _keys, _parse_body, _sha

MAX_BODY = 64 * 1024
MAX_CUTS = 250


def annotate(stats, summary, deck, sees_inventory):
    """Only a configured target needs a plan; read-only readers receive no private text receipt."""
    target = summary.get("target_bracket")
    if type(target) is not int or not 1 <= target <= 5 or not isinstance(stats, dict):
        return
    commander = stats.get("commander")
    bracket = commander.get("bracket") if isinstance(commander, dict) else None
    if not isinstance(bracket, dict):
        return
    try:
        answer = bracket_fixes(bracket, target)
    except Exception:
        common._log("Counted bracket fixes failed:\n" + traceback.format_exc())
        answer = {"checked": False, "target": target, "reason": "The fewest cuts couldn't be checked. Review the named counts below."}
    profile = guard.viewer()
    editable = deck is not None and profile is not None and sees_inventory and guard.allowed(profile, "deck.edit", deck)
    answer["receipt"] = deck.sha256 if editable else None
    bracket["fixes"] = answer


def _checked_minimum(result):
    commander = result.get("commander") if isinstance(result, dict) else None
    bracket = commander.get("bracket") if isinstance(commander, dict) else None
    if not isinstance(bracket, dict):
        return None
    check = bracket_fixes(bracket, 4)   # target 4 needs no search, but validates every counted input
    if not check["checked"]:
        return None
    value = bracket.get("minimum")
    return value if type(value) is int and value == check["current_minimum"] else None


def _without(sections, cuts):
    return {section: [line for line in rows if (cards.resolve(line.name) or line.name) not in cuts]
            for section, rows in sections.items()}


def _add(sections, section, candidate):
    answer = {key: list(rows) for key, rows in sections.items()}
    printing = candidate.get("default") or {}
    answer.setdefault(section, []).append(decks.DeckLine(max(1, candidate.get("max_qty", 1)), candidate["name"],
        printing.get("set"), printing.get("number"), printing.get("finish") or "nonfoil"))
    return answer


def _valid_choice(plan, cuts):
    for option in plan["plans"]:
        fixed = set(option["fixed"])
        if not fixed <= cuts:
            continue
        choice = option.get("choose")
        if not choice and cuts == fixed or choice and len(cuts - fixed) == choice["count"] and cuts - fixed <= set(choice["names"]):
            return True
    return False


def replacements(body):
    from . import swaps
    from .deck_page import _deck_stats
    data = _parse_body(body, MAX_BODY)
    deck_id = deck_aliases.canonical_id(data.get("id"))     # hidden404 before target/cut validation
    summary, deck = swaps._deck(deck_id)                    # then inventory privacy
    guard.require(guard.viewer(), "deck.edit", deck)
    if deck.kind != "commander":
        raise ApiError(400, "Bracket fixes are for Commander decks")
    _keys(data, ("id", "sha256", "target", "cuts", "card"), ("version", "profile"))
    if _sha(data["sha256"]) != deck.sha256:
        raise ApiError(409, "The deck changed. Reload its bracket counts before checking replacements.")
    target = data["target"]
    if type(target) is not int or target != summary.get("target_bracket"):
        raise ApiError(409, "The Target bracket changed. Reload the deck before checking replacements.")
    version = data.get("version") or "target"
    if version not in ("target", "owned"):
        raise ApiError(400, "Choose target or owned")
    source = deck.target if version == "target" else deck.owned
    if not source:
        raise ApiError(404, "This deck has no selected list")
    raw_cuts = data["cuts"]
    if not isinstance(raw_cuts, list) or not 1 <= len(raw_cuts) <= MAX_CUTS or any(not isinstance(name, str) or not name or len(name) > MAX_NAME for name in raw_cuts):
        raise ApiError(400, "Choose a bounded set of named cards from the minimum-cut plan")
    cuts = {cards.resolve(name) or name for name in raw_cuts}
    name = cards.resolve(data["card"]) if isinstance(data["card"], str) else None
    if len(cuts) != len(raw_cuts) or name not in cuts:
        raise ApiError(400, "Choose one of the selected cuts")
    result = _deck_stats(source, "commander", [])
    if _checked_minimum(result) is None:
        raise ApiError(503, "The counted minimum can't be checked from the available card, tag and combo data.")
    plan = bracket_fixes(result["commander"]["bracket"], target)
    if not plan["checked"] or len(cuts) != plan["cuts"] or not _valid_choice(plan, cuts):
        raise ApiError(409, "Choose the fewest cuts from the current plan before checking replacements.")
    section = next((section for section in ("Commander", "Companion", "Deck")
                    if any((cards.resolve(line.name) or line.name) == name for line in source.get(section, []))), None)
    if section != "Deck":
        return _identity_replacements(summary, deck, source, section, name, cuts, target, version)
    answer = swaps.suggest_replacements(deck_id, version, name)
    return _assess(answer, source, section, name, cuts, target, _deck_stats)


def _assess(answer, source, section, name, cuts, target, read_stats):
    reduced = _without(source, cuts)
    for candidate in answer["candidates"]:
        candidate["section"] = section
        forecast = read_stats(_add(reduced, section, candidate), "commander", [])
        minimum = _checked_minimum(forecast)
        candidate["after_minimum"] = minimum
        candidate["fit"] = "unknown" if minimum is None else "unsafe" if minimum > target else "safe"
        candidate["fit_note"] = ("The counted minimum couldn't be checked." if minimum is None else
                                 f"After all selected cuts and this replacement, the counted minimum would be Bracket {minimum}.")
        one_swap = _add(_without(source, {name}), section, candidate)
        checked_swap = read_stats(one_swap, "commander", [])
        rules = checked_swap.get("commander") if isinstance(checked_swap, dict) else None
        candidate["one_swap_legal"] = isinstance(rules, dict) and rules.get("ok") is True
    answer.update(target=target, selected_cuts=sorted(cuts), note="Each check removes all selected cut cards and adds only this replacement. It does not name the deck's bracket. Test changes one slot; Check the complete deck before saving.")
    return answer


def _identity_replacements(summary, deck, source, section, name, cuts, target, version):
    """Commander/companion cuts are explicit identity changes, with their own eligibility check."""
    from decklab.lib.stats.commander import _can_be_commander
    from decklab.lib.decks import swaps as ranking
    from . import drafts, swaps
    from .deck_page import _deck_stats
    warnings = []
    p = swaps._space_pool(deck.space, warnings)
    colours = swaps._colours(deck, source)
    in_list, free, here = swaps._free_for(p, swaps.pool.self_ids(summary["id"]), source)
    slot = cards.card(name)
    spares = [(candidate, qty, cards.card(candidate)) for candidate, qty in free.items() if qty > 0 and cards.card(candidate) is not None]
    if section == "Commander":
        spares = [row for row in spares if _can_be_commander(row[2])]
    else:
        spares = [row for row in spares if "Companion" in row[2].get("keywords", [])]
    found = ranking.ranked(slot, spares, colours, "commander", 1, in_list, here)
    counts = drafts._visible_counts(deck.space)
    listed = [swaps._candidate(slot, candidate, spare, here.get(candidate, 0), take, counts, colours)
              for _, candidate, spare, take in found[:ranking.MAX_REPLACEMENTS]]
    answer = {"deck_id": summary["id"], "version": version, "kind": "commander", "card": {"name": name},
              "candidates": listed, "more": max(0, len(found) - ranking.MAX_REPLACEMENTS)}
    return _assess(answer, source, section, name, cuts, target, _deck_stats)
