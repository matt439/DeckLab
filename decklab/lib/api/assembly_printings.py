"""Build decks' "Which printing?": the printings a pulled card can be, and Finish building's record.

A built deck's Printings in box line (lib/decks/printings.py) says which physical printing of its
cards went in its box. The plan offers, for each card a deck pulls from storage, the collection's
printings of it whose copies aren't all recorded in a box already (annotate). When only one
printing can be in storage, it's chosen already ("only printing in storage"): that's certain, not
a guess. Finish building takes the person's choices (picks) and writes the line in the same save
as the rest (record): the parts the deck's record already had and its new box still holds, then
the choices. Skipping is fine: a card left unchosen isn't recorded.
"""
from collections import Counter

from decklab.lib import cards, inventory, spaces
from decklab.lib.decks import printings

from .common import ApiError, _keys

MAX_PICKS = printings.MAX_LINES


def _label(key):
    return printings.PrintingLine(1, "", *key).label()


def _choices(p):
    """{canonical name: [(key, copies not recorded in any box)]} of the home collection."""
    owned = printings.capacity(inventory.current().collection(spaces.HOME).rows, printings.canonical)
    recorded = Counter()
    for holder in p.in_use:
        for (_, *key), copies in holder.recorded.items():
            recorded[tuple(key)] += copies
    out = {}
    for key, (name, copies) in owned.items():
        free = copies - recorded[key]
        if free > 0:
            out.setdefault(name, []).append((key, free))
    return out


def annotate(answer, p):
    """Add printing_choices to each deck of the plan: {name: {"options": [{set, collector_number,
    finish, label, free}], "only": the one printing storage can hold, else None}} for the cards it
    pulls from storage (not basic lands)."""
    try:
        choices = _choices(p)
    except Exception:           # the choice is optional: a plan without it still packs
        choices = {}
    for item in answer["decks"]:
        offered = {}
        for step in item.get("steps", []):
            if not step.get("storage"):
                continue
            name = cards.resolve(step["name"]) or step["name"]
            found = sorted(choices.get(name, []))
            if not found:
                continue
            options = [{"set": key[0], "collector_number": key[1], "finish": key[2], "label": _label(key),
                        "free": free} for key, free in found]
            only = options[0] if len(options) == 1 else None
            offered[step["name"]] = {"options": options, "only": only}
        item["printing_choices"] = offered
    return answer


def picks(value, plan):
    """{deck id: [PrintingLine]} from the request's printings ({deck id: [{name, set,
    collector_number, finish, quantity}]}), each a card that deck pulls and one of the printings
    the plan offered it, at most the copies it pulls. ApiError 400 otherwise."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ApiError(400, "printings must map deck ids to the printings chosen")
    by_id = {item["id"]: item for item in plan["decks"]}
    out = {}
    for deck_id, chosen in value.items():
        item = by_id.get(deck_id)
        if item is None:
            raise ApiError(400, "printings may name only the decks in this plan")
        if not isinstance(chosen, list) or len(chosen) > MAX_PICKS:
            raise ApiError(400, f"Each deck's printings must be a list of at most {MAX_PICKS}")
        pulled = {step["name"]: step["storage"] for step in item.get("steps", []) if step.get("storage")}
        offered = item.get("printing_choices", {})
        lines, counted = [], Counter()
        for pick in chosen:
            if not isinstance(pick, dict):
                raise ApiError(400, "Each printing must be {name, set, collector_number, finish, quantity}")
            _keys(pick, ("name", "set", "collector_number", "finish", "quantity"))
            name, qty = pick["name"], pick["quantity"]
            if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
                raise ApiError(400, "A printing's quantity must be a whole number")
            if not qty:
                continue
            options = offered.get(name, {}).get("options", []) if isinstance(name, str) else []
            option = next((o for o in options if (o["set"], o["collector_number"], o["finish"])
                           == (pick["set"], pick["collector_number"], pick["finish"])), None)
            if option is None:
                raise ApiError(409, f"{name} isn't offered in that printing any more. Refresh the plan and choose again.")
            counted[name] += qty
            if counted[name] > pulled.get(name, 0) or qty > option["free"]:
                raise ApiError(400, f"More copies of {name} were chosen than this deck pulls from storage")
            lines.append(printings.PrintingLine(qty, cards.resolve(name) or name, option["set"],
                                                option["collector_number"], option["finish"]))
        if lines:
            out[deck_id] = printings.merged(lines)
    return out


def record(parsed, chosen):
    """Write parsed's Printings in box line after its new build is installed: what it recorded
    and still holds, then chosen ([PrintingLine]), trimmed to what the box holds."""
    try:
        before = printings.printings(parsed)
    except printings.DeckFileError:
        before = []
    held = printings.held_counts(parsed)
    kept = printings.trim(before, held)
    # A pulled copy is a new one: the earlier record keeps only the copies the box held already.
    room = Counter(held)
    for line in chosen:
        room[printings.canonical(line.name)] -= line.quantity
    lines = printings.merged(printings.trim(kept, +room) + list(chosen))
    printings.set_printings(parsed, printings.trim(lines, held))
