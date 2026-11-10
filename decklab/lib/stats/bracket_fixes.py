"""Fewest named-card cuts for the existing counted bracket floor, with bounded exact search.

This changes no list and judges no intent, timing, power, commander eligibility or deck size.
Deleting a named card means deleting all its copies. Game Changer choices remain choices.
"""
from collections import Counter

from .constants import UPGRADED_MAX_GAME_CHANGERS

NODE_BUDGET = 25_000
PLAN_LIMIT = 12


def _names(rows):
    if not isinstance(rows, list):
        raise ValueError
    names = set()
    for row in rows:
        name = row.get("name") if isinstance(row, dict) else row
        if not isinstance(name, str) or not name:
            raise ValueError
        names.add(name)
    return frozenset(names)


def fixes(bracket, target, *, node_budget=NODE_BUDGET, plan_limit=PLAN_LIMIT):
    from .commander import min_bracket

    unavailable = {"checked": False, "target": target, "reason": "The fewest cuts can't be worked out from the available card, tag and two-card combo data."}
    if type(target) is not int or not 1 <= target <= 5 or not isinstance(bracket, dict):
        return unavailable
    try:
        gc = _names(bracket["game_changers"])
        mld = _names(bracket["mass_land_denial"])
        turns = _names(bracket["extra_turns"])
        combos = bracket["combos"]
        if bracket.get("unknown_cards") != [] or not isinstance(combos, dict) or combos.get("checked") is not True or not isinstance(combos.get("matches"), list):
            return unavailable
        matches = []
        for match in combos["matches"]:
            if not isinstance(match, dict) or type(match.get("floor")) is not int or match["floor"] not in (1, 3, 4):
                return unavailable
            names = _names(match["names"])
            if not 1 <= len(names) <= 2:
                return unavailable
            matches.append((names, match["floor"]))
    except (KeyError, ValueError, TypeError):
        return unavailable

    def minimum(cuts):
        standing = [floor for names, floor in matches if not names.intersection(cuts)]
        return min_bracket(len(gc - cuts), len(mld - cuts) + standing.count(4), len(turns - cuts), standing.count(3))

    current = minimum(frozenset())
    mandatory = (mld if target < 4 else frozenset()) | (gc if target < 3 else frozenset()) | (turns if target < 2 else frozenset())
    edges = frozenset(names for names, floor in matches if floor > target and not names.intersection(mandatory))
    mandatory |= frozenset(next(iter(edge)) for edge in edges if len(edge) == 1)
    edges = frozenset(edge for edge in edges if not edge.intersection(mandatory))
    gc_left = gc - mandatory
    gc_needed = max(0, len(gc_left) - UPGRADED_MAX_GAME_CHANGERS) if target == 3 else 0
    best, plans, seen, nodes = float("inf"), [], {}, 0
    limited = False

    def search(selected, remaining):
        nonlocal best, plans, nodes, limited
        nodes += 1
        if nodes > node_budget:
            limited = True
            return
        if limited:
            return
        need = max(0, gc_needed - len(selected & gc_left))
        # A disjoint edge matching is a lower bound on further cards needed.
        used, matching = set(), 0
        for edge in sorted(remaining, key=lambda edge: tuple(sorted(edge))):
            if not used.intersection(edge):
                used.update(edge)
                matching += 1
        degree = Counter(name for edge in remaining for name in edge)
        clique = []
        for name in sorted(degree, key=lambda name: (-degree[name], name)):
            if all(frozenset({name, other}) in remaining for other in clique):
                clique.append(name)
        lower = len(selected) + max(need, matching, len(clique) - 1)
        if lower > best or lower == best and len(plans) >= plan_limit:
            return
        state = (remaining, len(selected & gc_left))
        if seen.get(state, float("inf")) < len(selected):
            return
        if len(seen) < 5000:
            seen[state] = len(selected)
        if not remaining:
            cost = len(selected) + need
            if cost > best:
                return
            if cost < best:
                best, plans = cost, []
            fixed = mandatory | selected
            choices = sorted(gc_left - selected) if need else []
            example = fixed | frozenset(choices[:need])
            plan = {"fixed": sorted(fixed), "choose": {"count": need, "names": choices} if need else None,
                    "example": sorted(example), "after_minimum": minimum(example)}
            if plan not in plans and len(plans) < plan_limit:
                plans.append(plan)
            return
        edge = max(remaining, key=lambda edge: (sum(degree[name] for name in edge), tuple(sorted(edge))))
        for name in sorted(edge, key=lambda name: (-degree[name], name)):
            search(selected | frozenset({name}), frozenset(edge for edge in remaining if name not in edge))

    search(frozenset(), edges)
    if limited:
        return {"checked": False, "target": target, "reason": "Too many overlapping combo choices to prove the fewest cuts in this preview. Review the named cards and combos below."}
    return {"checked": True, "target": target, "current_minimum": current, "cuts": len(mandatory) + int(best),
            "plans": plans, "examples_only": True,
            "note": "These are cuts from the counts used by the minimum, not a claim about the deck's bracket. Replace the cut cards, then check the whole list again. Changing a commander also needs colour-identity and eligibility checks."}
