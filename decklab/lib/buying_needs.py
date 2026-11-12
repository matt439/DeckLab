"""Saved target-list shortfalls from the caller's current inventory snapshot.

One home pool supplies every individual deck comparison. Counts are not a
simultaneous packing allocation, and queued intent never reduces them again.
Callers supply canonical-name, message and logging callbacks; this module has
no HTTP, picture, queue, shop-cache or retailer behavior.
"""
from dataclasses import dataclass, field

from decklab.lib import inventory, pool


@dataclass
class CountedNeeds:
    """Unsorted counting facts and proof status, before a caller presents them.

    phase distinguishes early no-target/pool-failure returns from a completed
    counting pass with zero rows. status is fixed wording for non-UI callers;
    raw error details need not leave their local capture. players maps each
    canonical card name to the ids of the counted decks whose planned list needs
    it, shortfall or not: each deck's count sees the whole free pool, so a card
    two decks need can't be compared with its summed missing copies (E5-S37).
    """
    phase: str
    rows: list = field(default_factory=list)
    decks: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    message: str | None = None
    players: dict = field(default_factory=dict)

    @property
    def status(self):
        if self.phase == "unavailable":
            return "unavailable"
        return "partial" if self.errors else "ready"


def problem(summary, message):
    return {"id": summary["id"], "title": summary["title"], "message": message}


def incomplete(result, public):
    unresolved = result.get("unresolved") or ()
    warnings = result.get("warnings") or ()
    parts = [public(value) for value in warnings]
    if unresolved:
        names = sorted({item[0] for item in unresolved})
        parts.append("Unknown cards: " + ", ".join(names))
    return "; ".join(parts)


def count(summaries, *, canonical, public, log, errors=(), incomplete_for=None, problem_for=None):
    """Count the supplied saved-target summaries without changing or re-pinning them.

    An unavailable inventory still propagates to the caller. An incomplete pool
    proves no needs; an unreadable individual deck preserves other proven rows.
    Optional compatibility callbacks retain an adapter's existing helper seams.
    """
    describe = problem_for or problem
    explain = incomplete_for or (lambda result: incomplete(result, public))
    errors = list(errors)
    wanted = []
    for summary in summaries:
        if "target" not in summary.get("versions", []):
            errors.append(describe(summary, "This deck has no planned list to count."))
        else:
            wanted.append(summary)
    if not wanted:
        return CountedNeeds("no_targets", errors=errors)
    try:
        supply = pool.load_pool()
    except inventory.Unavailable:
        raise
    except Exception as error:  # noqa: BLE001 - an optional pool read keeps its existing error boundary
        log(f"Shopping missing cards: the pool could not be read: {error}")
        return CountedNeeds("unavailable", errors=errors,
                            message="The home card pool could not be read: " + public(error))
    warnings = [public(value) for value in supply.warnings]
    if supply.unresolved:
        warnings.append("Unknown cards in the home pool: " + ", ".join(sorted(supply.unresolved)))
    if warnings:
        return CountedNeeds("unavailable", errors=errors, warnings=warnings,
                            message="Missing cards cannot be counted until the home card pool is complete.")
    gathered, legacy, players = {}, [], {}
    for summary in wanted:
        try:
            result = pool.owned_vs_needed(summary["id"], "target", pool=supply, prices=False)
            why = explain(result)
            if why:
                errors.append(describe(summary, "This deck could not be fully counted: " + why))
                continue
            amounts = {}
            for row in result["rows"]:
                if row.get("need", 0) > 0:
                    holders = players.setdefault(canonical(row["name"]), [])
                    if summary["id"] not in holders:
                        holders.append(summary["id"])
                if row["missing"] > 0:
                    name = canonical(row["name"])
                    amounts[name] = amounts.get(name, 0) + row["missing"]
            missing = sum(amounts.values())
            if not missing:
                continue
            deck = {key: summary.get(key) for key in ("id", "title", "kind", "player", "status")}
            waiting = sum(qty for row in result["rows"] for _, qty in pool.row_labels(row)["on_the_way"])
            legacy.append({**deck, "missing": missing, "on_the_way": waiting})
            for name, quantity in amounts.items():
                card = gathered.setdefault(name, {"name": name, "missing": 0, "decks": []})
                card["missing"] += quantity
                card["decks"].append({**deck, "missing": quantity})
        except inventory.Unavailable:
            raise
        except Exception as error:  # noqa: BLE001 - one unreadable deck must leave other proven needs available
            log(f"Shopping missing cards: {summary['id']} could not be counted: {error}")
            errors.append(describe(summary, "This deck could not be counted: " + public(error)))
    return CountedNeeds("counted", list(gathered.values()), legacy, errors, players=players)
