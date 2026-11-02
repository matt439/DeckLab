"""Shopping's "Build several decks together" (E5-S28, first slice): read-only.

    GET /api/shopping/combined?decks=casual/a,casual/b    combined_view()

For two or more chosen home decks, what to buy so that all of them can be built at
the same time from home's one pool: their Planned (target) lists' non-basic cards
added up and compared once against the pool (pool.compare), so each free copy counts
once. Copies other built decks and intact products hold aren't free; a chosen deck
that's already built holds its own copies, which count for it (pool.self_ids of every
chosen deck are excluded from the holders). Copies on the way count as available, as
the deck tables count them (E5-S04), and are labelled on the way.

Each card names the chosen decks that need it, with each deck's own shortfall alone
(pool.compare for that deck by itself), so where the decks compete for the same free
copies the combined shortfall is more than the single-deck shortfalls added up.

Shopping's readers only (home's records and inventory, as GET /api/shopping); a deck
the viewer may not see answers as a missing deck (404), before anything is counted.
Nothing is written and nothing is queued: Queue these is a later slice.
"""
import contextlib

from decklab.lib import cards, decks, inventory, pool, spaces

from . import common, guard
from .carddata import _require_cards
from .common import DATABASE_DOWN, ApiError, _public
from .library import _find_summary, check_deck_id

MIN_DECKS = 2
MAX_DECKS = 12
NOT_HOME = "Only home decks can be planned together on Shopping."


def combined_view(decks=None):
    """GET /api/shopping/combined?decks=ID,ID[,...]: the combined shortfall.

    Answers {ready, decks: [{id, title, kind, status, player, missing_alone}], rows: [{name,
    missing, missing_alone, need, available, on_the_way: [{source, copies}], held_elsewhere,
    decks: [{id, title, need, missing_alone}], card}], totals: {cards, copies, copies_alone,
    on_the_way (every copy on the way the decks count on)}, errors, warnings}. ready is False, with no rows, when the pool or a chosen
    deck couldn't be fully counted: a partial answer would understate the shortfall."""
    guard.require_sees_home_records()
    guard.require_sees_inventory(spaces.HOME)
    ids = _chosen(decks)
    _require_cards()
    try:
        with contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned():
            answer = _combined(ids)
    except ApiError:
        raise
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except (inventory.StateError, ValueError, OSError) as error:
        raise ApiError(400, "The decks could not be counted together: " + _public(error)) from None
    from .shopping import _card_for
    found = {}
    for row in answer["rows"]:
        row["card"] = _card_for(row["name"], cache=found)
    return answer


def _chosen(value):
    """The chosen deck ids, in the order given, each once (a repeat is refused)."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, f"Choose {MIN_DECKS} to {MAX_DECKS} decks: decks=ID,ID")
    ids = [part.strip() for part in value.split(",")]
    if len(ids) < MIN_DECKS or len(ids) > MAX_DECKS or not all(ids):
        raise ApiError(400, f"Choose {MIN_DECKS} to {MAX_DECKS} decks: decks=ID,ID")
    for deck_id in ids:
        check_deck_id(deck_id)
    return ids


def _summaries(ids):
    """The chosen decks' summaries: a hidden or missing deck's 404 first, then a product,
    pairing or person's deck's 400, then a repeat (an alias of one already chosen)."""
    found, seen = [], set()
    for deck_id in ids:
        summary = _find_summary(deck_id)
        space, kind, _ = spaces.split_deck_id(summary["id"])
        if space != spaces.HOME or kind not in decks.KINDS:
            raise ApiError(400, NOT_HOME)
        if summary["id"] in seen:
            raise ApiError(400, f"{summary['title']} is chosen twice")
        seen.add(summary["id"])
        found.append(summary)
    return found


def _unavailable(message, chosen, errors=(), warnings=()):
    return {"ready": False, "decks": chosen, "rows": [], "errors": [*errors, {"message": message}],
            "warnings": list(warnings), "totals": {"cards": 0, "copies": 0, "copies_alone": 0, "on_the_way": 0}}


def _deck(summary):
    return {key: summary.get(key) for key in ("id", "title", "kind", "status", "player")}


def _canonical(name):
    return cards.resolve(name) or name


def _combined(ids):
    summaries = _summaries(ids)
    chosen = [_deck(summary) for summary in summaries]
    errors, lists = [], {}
    for summary in summaries:
        if summary.get("error"):
            errors.append({"id": summary["id"], "title": summary["title"], "message": "This deck could not be read."})
        elif "target" not in summary.get("versions", []):
            errors.append({"id": summary["id"], "title": summary["title"],
                           "message": "This deck has no Planned list to count."})
        else:
            try:
                lists[summary["id"]] = decks.load_deck(summary["id"], "target")
            except (decks.DeckNotFound, decks.DeckFileError, OSError, UnicodeError) as error:
                common._log(f"Shopping combined: {summary['id']} could not be read: {error}")
                errors.append({"id": summary["id"], "title": summary["title"],
                               "message": "This deck could not be read: " + _public(error)})
    if errors:
        return _unavailable("Every chosen deck needs a readable Planned list to be counted together.", chosen, errors)
    try:
        supply = pool.load_pool()
    except inventory.Unavailable:
        raise
    except Exception as error:  # noqa: BLE001 - the pool's read keeps Shopping's error boundary
        common._log(f"Shopping combined: the pool could not be read: {error}")
        return _unavailable("The home card pool could not be read: " + _public(error), chosen)
    warnings = [_public(value) for value in supply.warnings]
    if supply.unresolved:
        warnings.append("Unknown cards in the home pool: " + ", ".join(sorted(supply.unresolved)))
    if warnings:
        return _unavailable("Missing cards cannot be counted until the home card pool is complete.",
                            chosen, warnings=warnings)
    alone, own = {}, set()
    for deck in chosen:
        ids_of = pool.self_ids(deck["id"])
        own |= ids_of
        result = pool.compare(lists[deck["id"]], supply, ids_of, prices=False)
        if result["unresolved"]:
            names = sorted({name for name, _ in result["unresolved"]})
            errors.append({"id": deck["id"], "title": deck["title"],
                           "message": "This deck could not be fully counted: Unknown cards: " + ", ".join(names)})
            continue
        alone[deck["id"]] = {row["name"]: row for row in result["rows"]}
        deck["missing_alone"] = sum(row["missing"] for row in result["rows"])
    if errors:
        return _unavailable("Every chosen deck needs only known cards to be counted together.", chosen, errors)
    merged = {(deck_id, section): lines for deck_id, sections in lists.items() for section, lines in sections.items()}
    together = pool.compare(merged, supply, own, prices=False)
    sees = guard.deck_reader()
    rows = []
    for row in together["rows"]:
        if row["missing"] <= 0:
            continue
        wanting = [{"id": deck["id"], "title": deck["title"], "need": alone[deck["id"]][row["name"]]["need"],
                    "missing_alone": alone[deck["id"]][row["name"]]["missing"]}
                   for deck in chosen if row["name"] in alone[deck["id"]]]
        held = [(holder, holder.cards[row["name"]]) for holder in supply.in_use
                if holder.id not in own and holder.cards.get(row["name"])]
        waiting = [{"source": source, "copies": copies} for source, copies in pool.row_labels(row)["on_the_way"]]
        rows.append({
            "name": _canonical(row["name"]),
            "need": row["need"],
            "available": row["available"],
            "missing": row["missing"],
            "missing_alone": sum(deck["missing_alone"] for deck in wanting),
            "on_the_way": waiting,
            "held_elsewhere": [{"title": _holder_title(holder, sees), "copies": copies} for holder, copies in held],
            "decks": wanting,
            "card": None,
        })
    rows.sort(key=lambda r: (-len(r["decks"]), -(r["missing"] - r["missing_alone"]), -r["missing"], r["name"].casefold()))
    totals = {"cards": len(rows), "copies": sum(r["missing"] for r in rows),
              "copies_alone": sum(deck.get("missing_alone", 0) for deck in chosen),
              # every copy on the way the chosen decks count on, also for cards they then have enough of
              "on_the_way": sum(copies for r in together["rows"] for _, copies in pool.row_labels(r)["on_the_way"])}
    return {"ready": True, "decks": chosen, "rows": rows, "errors": [], "warnings": [], "totals": totals}


def _holder_title(holder, sees):
    """A holder's title, or how a deck the viewer may not see is named (guard.hidden_deck)."""
    from .inventory_views import named_holder
    return holder.title if named_holder(holder.id, sees) else guard.hidden_deck(holder.id)
