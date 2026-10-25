"""Read-only home buying view: sum each saved deck's current planned shortfalls.

These are individual deck comparisons against one shared pool, not a simultaneous
packing allocation. The queue records purchase intent, so queued copies annotate
the result and are never deducted from missing copies a second time.
"""
from decklab.lib import cards, inventory, pool

from . import common


def unavailable(message, *, errors=(), warnings=()):
    """An explicit unavailable result, never an apparently successful empty list."""
    return {"ready": False, "rows": [], "warnings": list(warnings),
            "errors": [*errors, {"message": message}], "totals": {"cards": 0, "copies": 0}}


def _canonical(name):
    return cards.resolve(name) or name


def is_token(row):
    """Positive token/reminder evidence; an ambiguous playable name alone is not enough."""
    try:
        set_code, number = row.get("set"), row.get("collector_number")
        if set_code and number:
            if cards.token_faces_at(set_code, number) is not None:
                return True
            if cards.printing_card(set_code, number) is not None:
                return False
        name = row.get("name", "")
        return cards.resolve(name) is None and cards.token_face(name) is not None
    except cards.INDEX_ERRORS:
        return False


def _problem(summary, message):
    return {"id": summary["id"], "title": summary["title"], "message": message}


def _incomplete(result):
    unresolved = result.get("unresolved") or ()
    warnings = result.get("warnings") or ()
    parts = [common._public(value) for value in warnings]
    if unresolved:
        names = sorted({item[0] for item in unresolved})
        parts.append("Unknown cards: " + ", ".join(names))
    return "; ".join(parts)


def gather(summaries, queue, card_for, *, errors=()):
    """Return (missing_cards, legacy decks_missing) from the caller's pinned snapshot.

    Home summary enumeration failures arrive in errors. A pool failure invalidates
    all comparisons; a single unreadable planned list leaves the other rows visible
    with ready=False and a named error. Pictures remain optional, as elsewhere on
    Shopping. Every matching queue row retains its purpose, state and reference data.
    """
    errors = list(errors)
    wanted = []
    for summary in summaries:
        if "target" not in summary.get("versions", []):
            errors.append(_problem(summary, "This deck has no planned list to count."))
        else:
            wanted.append(summary)
    if not wanted:
        return {"ready": not errors, "rows": [], "warnings": [], "errors": errors,
                "totals": {"cards": 0, "copies": 0}}, []
    try:
        supply = pool.load_pool()
    except inventory.Unavailable:
        raise
    except Exception as error:
        common._log(f"Shopping missing cards: the pool could not be read: {error}")
        return unavailable("The home card pool could not be read: " + common._public(error), errors=errors), []
    warnings = [common._public(value) for value in supply.warnings]
    if supply.unresolved:
        warnings.append("Unknown cards in the home pool: " + ", ".join(sorted(supply.unresolved)))
    if warnings:
        return unavailable("Missing cards cannot be counted until the home card pool is complete.",
                           errors=errors, warnings=warnings), []
    gathered, legacy = {}, []
    for summary in wanted:
        try:
            result = pool.owned_vs_needed(summary["id"], "target", pool=supply, prices=False)
            problem = _incomplete(result)
            if problem:
                errors.append(_problem(summary, "This deck could not be fully counted: " + problem))
                continue
            amounts = {}
            for row in result["rows"]:
                if row["missing"] > 0:
                    name = _canonical(row["name"])
                    amounts[name] = amounts.get(name, 0) + row["missing"]
            missing = sum(amounts.values())
            if not missing:
                continue
            deck = {key: summary.get(key) for key in ("id", "title", "kind", "player", "status")}
            waiting = sum(qty for row in result["rows"] for _, qty in pool.row_labels(row)["on_the_way"])
            legacy.append({**deck, "missing": missing, "on_the_way": waiting})
            for name, quantity in amounts.items():
                card = gathered.setdefault(name, {"name": name, "missing": 0, "decks": [], "queue": [], "card": None})
                card["missing"] += quantity
                card["decks"].append({**deck, "missing": quantity})
        except inventory.Unavailable:
            raise
        except Exception as error:
            common._log(f"Shopping missing cards: {summary['id']} could not be counted: {error}")
            errors.append(_problem(summary, "This deck could not be counted: " + common._public(error)))
    try:
        by_name = {name.casefold(): row for name, row in gathered.items()}
        for queued in queue:
            if queued.get("is_token") or is_token(queued):
                continue
            found = by_name.get(_canonical(queued["name"]).casefold())
            if found is not None:
                found["queue"].append(dict(queued))
    except Exception as error:
        common._log(f"Shopping missing cards: queue matching failed: {error}")
        errors.append({"message": "Queued cards could not be matched: " + common._public(error)})
    rows = list(gathered.values())
    rows.sort(key=lambda row: (-len(row["decks"]), -row["missing"], row["name"].casefold()))
    for row in rows:
        row["decks"].sort(key=lambda deck: (deck["title"].casefold(), deck["id"]))
        row["card"] = card_for(row["name"])
    legacy.sort(key=lambda deck: (deck["status"] == "idea", deck["missing"], deck["title"].casefold()))
    return {"ready": not errors, "rows": rows, "warnings": [], "errors": errors,
            "totals": {"cards": len(rows), "copies": sum(row["missing"] for row in rows)}}, legacy
