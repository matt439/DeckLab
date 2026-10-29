"""Read-only home buying view: sum each saved deck's current planned shortfalls.

These are individual deck comparisons against one shared pool, not a simultaneous
packing allocation. The queue records purchase intent, so queued copies annotate
the result and are never deducted from missing copies a second time.
"""
# Keep the shared pool export for existing adapters' attribute patches.
from decklab.lib import buying_needs, cards, pool  # noqa: F401

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
    return buying_needs.problem(summary, message)


def _incomplete(result):
    return buying_needs.incomplete(result, common._public)


def gather(summaries, queue, card_for, *, errors=()):
    """Return (missing_cards, legacy decks_missing) from the caller's pinned snapshot.

    Home summary enumeration failures arrive in errors. A pool failure invalidates
    all comparisons; a single unreadable planned list leaves the other rows visible
    with ready=False and a named error. Pictures remain optional, as elsewhere on
    Shopping. Every matching queue row retains its purpose, state and reference data.
    """
    counted = buying_needs.count(summaries, canonical=_canonical, public=common._public, log=common._log,
                                errors=errors, incomplete_for=_incomplete, problem_for=_problem)
    errors = counted.errors
    if counted.phase == "no_targets":
        return {"ready": not errors, "rows": [], "warnings": [], "errors": errors,
                "totals": {"cards": 0, "copies": 0}}, []
    if counted.phase == "unavailable":
        return unavailable(counted.message, errors=errors, warnings=counted.warnings), []
    gathered = {row["name"]: {**row, "queue": [], "card": None} for row in counted.rows}
    legacy = counted.decks
    try:
        by_name = {name.casefold(): row for name, row in gathered.items()}
        for queued in queue:
            if queued.get("is_token") or is_token(queued):
                continue
            found = by_name.get(_canonical(queued["name"]).casefold())
            if found is not None:
                found["queue"].append(dict(queued))
    except Exception as error:  # noqa: BLE001 - preserve the optional queue-annotation boundary
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
