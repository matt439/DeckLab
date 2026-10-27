"""A built deck's printings in its box (lib/decks/printings.py), on its deck page.

view() is the deck page's printings_in_box part: what the Printings in box line records that can
still be true (the pool's InUse.recorded), why the rest is ignored ("out of date"), and the
choices its sheet offers. POST /api/deck/printings (save_printings) sets the line from that sheet,
one inventory operation (deck.save), as the token cards sheet's save is (token_cards.py); the
save's own checks (inventory/ops_decks.py check_printings) refuse a record the box or the
collection can't hold.
"""
from collections import Counter

from decklab.lib import cards, decks, inventory, spaces
from decklab.lib.decks import printings

from . import guard
from .commits import _conflict, _deck_file, _parse_file, _stored
from .common import ApiError, _keys, _parse_body, _public
from .cover import _expected
from .saving import _deck_refused, apply_op
from .settings import _writer


def _line_json(name, key, quantity):
    return {"name": name, "set": key[0], "collector_number": key[1], "finish": key[2],
            "label": printings.PrintingLine(1, name, *key).label(), "quantity": quantity}


def view(deck_file, stored, p):
    """{"recorded": [{name, set, collector_number, finish, label, quantity}], "stale": [why parts of
    the line are ignored], "cards": [{name, held, options: [{set, collector_number, finish, label,
    free, recorded}]}] (each non-basic card the box holds and the collection's printings of it;
    free is the copies other decks' records leave, recorded this deck's), "expect" (the text's
    sha256), "editable"} for a built home deck, else None."""
    if deck_file is None or stored is None or deck_file.status != "built" or deck_file.space != spaces.HOME:
        return None
    holder = next((item for item in (p.in_use if p is not None else []) if item.id == stored.id), None)
    if holder is None:
        return None
    owned = printings.capacity(inventory.current().collection(spaces.HOME).rows, printings.canonical)
    elsewhere = Counter()
    for item in p.in_use:
        if item.id != holder.id:
            for (_, *key), copies in item.recorded.items():
                elsewhere[tuple(key)] += copies
    mine = Counter({tuple(key): copies for (_, *key), copies in holder.recorded.items()})
    by_name = {}
    for key, (name, copies) in owned.items():
        by_name.setdefault(name, []).append((key, copies))
    out = []
    for name, held in sorted(holder.cards.items()):
        options = [{**_line_json(name, key, 0), "free": max(copies - elsewhere[key], 0), "recorded": mine[key]}
                   for key, copies in sorted(by_name.get(name, []))]
        for option in options:
            del option["quantity"], option["name"]
        out.append({"name": name, "held": held, "options": options})
    recorded = [_line_json(name, (set_code, number, finish), copies)
                for (name, set_code, number, finish), copies in sorted(holder.recorded.items())]
    return {"recorded": recorded, "stale": list(holder.recorded_stale), "cards": out,
            "expect": stored.sha256, "editable": guard.allowed(guard.viewer(), "deck.edit", deck_file)}


def _chosen(value):
    if not isinstance(value, list) or len(value) > printings.MAX_LINES:
        raise ApiError(400, f"cards must be a list of at most {printings.MAX_LINES} printings")
    lines = []
    for item in value:
        if not isinstance(item, dict):
            raise ApiError(400, "Each card must be {name, set, collector_number, finish, quantity}")
        _keys(item, ("name", "set", "collector_number", "finish", "quantity"))
        qty = item["quantity"]
        if isinstance(qty, bool) or not isinstance(qty, int) or not 0 <= qty <= printings.MAX_QUANTITY:
            raise ApiError(400, f"A card's quantity must be a whole number from 0 to {printings.MAX_QUANTITY}")
        if not all(isinstance(item[k], str) and item[k] for k in ("name", "set", "collector_number")) \
                or item["finish"] not in printings.FINISHES:
            raise ApiError(400, "Each card needs its name, set, collector number and finish")
        if qty:
            lines.append(printings.PrintingLine(qty, cards.resolve(item["name"]) or item["name"],
                                                item["set"].lower(), item["collector_number"], item["finish"]))
    return printings.merged(lines)


def save_printings(body):
    """POST /api/deck/printings {"profile", "id", "expect", "cards": [{name, set, collector_number,
    finish, quantity}]}.

    Sets a built home deck's Printings in box line to those cards ([] removes it: nothing
    recorded). The profile may change the deck as it may save its text (guard deck.edit) and see
    home's inventory. expect is the deck's revision or text sha256 (409 when it changed since).
    A record the box can't hold is refused (400), and one that would record more copies of a
    printing across the built decks than the collection has (409).

    Returns {"saved", "id", "title", "revision", "printings_in_box": the line as written}."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "id", "expect", "cards"))
    kind, slug, path = _deck_file(data["id"])
    deck_id = data["id"]
    stored = _stored(deck_id, viewer=profile)
    deck = _parse_file(stored.data, kind, slug, path, deck_id)
    guard.require(profile, "deck.edit", deck)
    space = spaces.space_of(deck_id)
    guard.require_sees_inventory(space)
    if not _expected(stored, data["expect"]):
        raise _conflict(deck_id, deck.title, viewer=profile)
    if deck.status != "built" or space != spaces.HOME:
        raise ApiError(400, "Only a built home deck records the printings in its box")
    chosen = _chosen(data["cards"])
    try:
        printings.set_printings(deck, chosen)
        out = decks.render_deck_file(deck)
    except (decks.DeckFileError, ValueError) as e:
        raise ApiError(400, f"The printings can't be written: {_public(e)}") from None
    revision = stored.revision
    if out != stored.text:
        what = (f"record printings in box of {deck.title}: {printings.format_printings(chosen)}" if chosen
                else f"record no printings in box of {deck.title}")
        op = inventory.Op("deck.save", {"deck_id": deck_id, "text": out, "base_sha256": stored.sha256})
        after, _ = apply_op(op, profile, what, _deck_refused(deck_id, deck.title, profile))
        held = after.deck(deck_id)
        revision = held.revision if held is not None else 0
    return {"saved": out != stored.text, "id": deck_id, "title": deck.title, "revision": revision,
            "printings_in_box": deck.get_field(printings.PRINTINGS_FIELD)}
