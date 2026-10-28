"""A deck's Considering list on its page (E2-S23, lib/decks/considering.py): the deck view's
"considering" part, each card with whether a copy is free in the space's pool, and POST
/api/deck/considering, which adds a card, removes one, or moves one into the Planned list.

Every change is an ordinary deck save (saving.save_deck, with lists.considering beside the
Planned list), so its checks, history and conflicts are a save's; a move changes both lists in that
one save, and the Planned list's table and "Decklist changed" line follow as for any list edit.
A Considering card is never needed, missing or in use: the free count only says whether the pool
has a copy no built deck or intact product holds, beyond what this deck's own Planned list needs.
"""
import json
from collections import Counter

from decklab.lib import decks, pool

from . import guard
from .card_lookup import _line_json, _resolve
from .commits import _conflict, _deck_file, _parse_file, _stored
from .common import MAX_QTY, ApiError, _keys, _parse_body
from .settings import _writer

MOVE_SECTIONS = ("Deck", "Sideboard")       # where a Considering card can go in the Planned list


def _page_line(line):
    """A DeckLine as the page sends one (drafts._read_line): kept as written when the deck has it,
    its category (E2-S24) too, so a Considering save never drops one from either list."""
    item = {"name": line.name, "qty": line.quantity, "set": line.set, "number": line.number, "finish": line.finish}
    if line.category:
        item["category"] = line.category
    return item


def view(deck_file, deck_id, p, sees, warnings):
    """The deck page's "considering": {"lines": [{qty, name, set, number, finish, card, and for a viewer
    who sees the space's inventory (sees, with its pool p) "free" (copies of the card no other built
    deck or intact product holds, on the way included, less what this deck's Planned list needs; None
    for a basic land) and "on_the_way"}], "sha256"}, or None for a deck text that can't be read."""
    if deck_file is None:
        return None
    lines = deck_file.considering or []
    free = needed = None
    if sees and p is not None:
        free = pool.free_copies(p, pool.self_ids(deck_id))
        needed = Counter()
        for section in deck_file.target.values():
            for line in section:
                needed[_resolve(line.name) or line.name] += line.quantity
    out = []
    for line in lines:
        item = _line_json(line, "Considering", warnings)
        if free is not None:
            name = _resolve(line.name) or line.name
            item["free"] = None if decks.is_basic_land(name) else max(free.get(name, 0) - needed.get(name, 0), 0)
            item["on_the_way"] = sum(qty for _, qty in p.on_the_way.get(name, []))
        out.append(item)
    return {"lines": out, "sha256": deck_file.sha256}


def save_considering(body):
    """POST /api/deck/considering {"profile", "id", "sha256", "action", ...}: one save of the deck.

    action "add" with line {"name", "qty", "set"?, "number"?, "finish"?} adds a card (to the line of
    the same card and printing when there is one; a new name is checked as the editor checks it);
    "remove" with index takes that line off; "move" with index, optional qty (default all its
    copies) and section (Deck or Sideboard, default Deck) takes the copies off Considering and adds
    them to that section of the Planned list, in the same save. Returns save_deck's answer."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "id", "sha256", "action"), ("line", "index", "qty", "section"))
    deck_id = data["id"]
    kind, slug, path = _deck_file(deck_id)
    stored = _stored(deck_id, viewer=profile)
    deck = _parse_file(stored.data, kind, slug, path, deck_id)
    guard.require(profile, "deck.edit", deck)
    if stored.sha256 != data["sha256"]:
        raise _conflict(deck_id, deck.title, viewer=profile)
    considering = [_page_line(line) for line in deck.considering or []]
    lists = {"considering": considering}
    action = data["action"]
    if action == "add":
        line = data.get("line")
        if not isinstance(line, dict):
            raise ApiError(400, "line must be a card line: {name, qty, set?, number?, finish?}")
        same = next((item for item in considering if item["name"] == line.get("name")
                     and (line.get("set") in (None, "", item["set"]))
                     and (line.get("number") in (None, "", item["number"]))
                     and (line.get("finish") or "nonfoil") == item["finish"]), None)
        if same is not None and isinstance(line.get("qty"), int) and not isinstance(line.get("qty"), bool):
            same["qty"] = min(same["qty"] + max(line["qty"], 0), MAX_QTY)
        else:
            considering.append(line)
    elif action in ("remove", "move"):
        index = data.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(considering):
            raise ApiError(400, "index must name a line of the Considering list")
        line = considering[index]
        qty = data.get("qty", line["qty"]) if action == "move" else line["qty"]
        if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= line["qty"]:
            raise ApiError(400, f"qty must be a whole number from 1 to {line['qty']}")
        if qty == line["qty"]:
            del considering[index]
        else:
            line["qty"] -= qty
        if action == "move":
            section = data.get("section") or "Deck"
            if section not in MOVE_SECTIONS:
                raise ApiError(400, f"section must be one of {', '.join(MOVE_SECTIONS)}")
            target = {name: [_page_line(item) for item in lines] for name, lines in deck.target.items()}
            moved = dict(line, qty=qty)
            key = lambda item: (item["name"], item["set"], item["number"], item["finish"])  # noqa: E731
            here = next((item for item in target.setdefault(section, []) if key(item) == key(moved)), None)
            if here is not None:
                here["qty"] = min(here["qty"] + qty, MAX_QTY)
            else:
                target[section].append(moved)
            lists["target"] = target
    else:
        raise ApiError(400, "action must be add, remove or move")
    from .saving import save_deck
    return save_deck(json.dumps({"profile": data["profile"], "id": deck_id, "sha256": data["sha256"],
                                 "lists": lists}).encode("utf-8"))
