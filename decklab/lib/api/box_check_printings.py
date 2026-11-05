"""Check box's "Which printing?": record which printing is in a built deck's box during a box check.

annotate() adds box_check["printings"] to each Build decks deck offering a box check:
{name: {"held", "recorded", "options": [{set, set_name, collector_number, finish, label, free,
recorded}]}} for every non-basic card the box physically holds that the collection has in two or
more printings (a card with one printing can only be that one). free is the copies other decks'
records leave; recorded is what this deck's Printings in box line already says (only the parts
that can still be true, as the deck page shows them).

chosen() reads a box check's optional printings ({name: [{set, collector_number, finish,
quantity}]}); apply() replaces those cards' parts of the deck's Printings in box line and keeps
every other card's that can still be true. The deck.save's own checks (inventory/ops_decks.py check_printings) refuse a
record the box or the collection can't hold, so a choice is never written unchecked.
"""
from decklab.lib import cards, decks
from decklab.lib.decks import printings

from .common import ApiError, _keys

MAX_NAMES = printings.MAX_LINES


def _offers(stored, p):
    from . import deck_printings
    parsed = decks.parse_deck(stored.data, stored.slug, stored.kind, space=stored.space)
    info = deck_printings.view(parsed, stored, p)
    if info is None:
        return {}
    out = {}
    for card in info["cards"]:
        if len(card["options"]) < 2:
            continue
        options = [{**option, "set_name": (cards.printing(option["set"], option["collector_number"]) or {})
                    .get("set_name") or ""} for option in card["options"]]
        out[card["name"]] = {"held": card["held"], "recorded": sum(o["recorded"] for o in options),
                             "options": options}
    return out


def annotate(answer, p, current):
    """Add the printing offers to each deck's box_check (optional: a failure offers none)."""
    for item in answer.get("decks", []):
        meta = item.get("box_check")
        if meta is None:
            continue
        try:
            stored = current.deck(item["id"])
            meta["printings"] = _offers(stored, p) if stored is not None and p is not None else {}
        except Exception:       # the choice is optional: a box check without it still counts
            meta["printings"] = {}
    return answer


def chosen(value):
    """{canonical name: [PrintingLine]} from a request's printings, shape-checked (ApiError 400)."""
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_NAMES:
        raise ApiError(400, f"printings must map at most {MAX_NAMES} card names to the printings chosen")
    out = {}
    for name, picks in value.items():
        if not isinstance(name, str) or not name.strip() or name != name.strip() or len(name) > 300:
            raise ApiError(400, "Each printing choice needs the card's exact name")
        exact = cards.resolve(name)
        if exact != name or decks.is_basic_land(name):
            raise ApiError(400, f"{name}: printings are recorded by the card's exact name, and never for basic lands")
        if not isinstance(picks, list) or len(picks) > MAX_NAMES:
            raise ApiError(400, f"{name}: the printings chosen must be a list")
        lines = []
        for pick in picks:
            if not isinstance(pick, dict):
                raise ApiError(400, f"{name}: each printing must be {{set, collector_number, finish, quantity}}")
            _keys(pick, ("set", "collector_number", "finish", "quantity"))
            qty = pick["quantity"]
            if isinstance(qty, bool) or not isinstance(qty, int) or not 0 <= qty <= printings.MAX_QUANTITY:
                raise ApiError(400, f"{name}: a printing's quantity must be a whole number from 0 to {printings.MAX_QUANTITY}")
            if not all(isinstance(pick[k], str) and pick[k] and pick[k] == pick[k].strip() for k in ("set", "collector_number")) \
                    or pick["finish"] not in printings.FINISHES:
                raise ApiError(400, f"{name}: each printing needs its set, collector number and finish")
            if qty:
                lines.append(printings.PrintingLine(qty, name, pick["set"].lower(), pick["collector_number"], pick["finish"]))
        out[name] = printings.merged(lines)
    return out


def apply(deck, picks, owned):
    """Replace the Printings in box parts of the cards picks names; True when the line changed.

    owned is the collection's printings.capacity(). Other cards' parts that can no longer be true
    (beyond what the box holds, or a printing the collection no longer has) are dropped, as the
    deck page's save does, so an out-of-date part the sheet never shows can't refuse this save."""
    if not picks:
        return False
    try:
        before = printings.printings(deck)
    except decks.DeckFileError:
        raise ApiError(409, "This deck's Printings in box line can't be read. Put it right on the deck page "
                            "before recording printings from a box check.") from None
    others = [line for line in before if printings.canonical(line.name) not in picks]
    kept = [line for line in printings.trim(others, printings.held_counts(deck))
            if not printings.problems_against([line], owned)]
    after = printings.merged(kept + [line for lines in picks.values() for line in lines])
    if after == before:
        return False
    printings.set_printings(deck, after)
    return True
