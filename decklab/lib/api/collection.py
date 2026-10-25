"""Read-only discovery in one space's owned (and, at home, incoming) card pool.

GET /api/collection?space=<id> shows home's pool by default, or a person's
(lib/spaces.py: magic/people/<id>/collection.csv, with no orders or products), all from the
inventory (decklab/lib/inventory).
Single-card edits and imports are lib/api/collection_edit.py's.
"""
from collections import Counter
import csv
import math

from decklab.lib import cards, decks, inventory, pool, spaces
from decklab.lib.inventory import unreadable
from .carddata import _require_cards
from .card_lookup import _card_json, _shown_printing
from .common import ApiError, _CONTROL_RE, _public, _scrub


def _text(value, name):
    value = "" if value is None else value
    if not isinstance(value, str) or len(value) > 160 or _CONTROL_RE.search(value):
        raise ApiError(400, f"{name} must be text of at most 160 characters")
    return value.strip()


def _integer(value, name, default, maximum):
    if value in (None, ""):
        return default
    if isinstance(value, bool) or not str(value).isdigit() or not 1 <= int(value) <= maximum:
        raise ApiError(400, f"{name} must be between 1 and {maximum}")
    return int(value)


def _special_basics(space=spaces.HOME):
    """Only explicitly tracked basics, never the ordinary lands in products.
    A person's space has only its collection (none when it doesn't exist yet).
    From the inventory (inventory.current()): home's collection and its pending
    card orders; a source that isn't there or can't be read raises as its file did."""
    inv = inventory.current()
    owned, incoming = Counter(), Counter()
    if space == spaces.HOME:
        sources = [(inv.collection(spaces.HOME), owned),
                   *((inv.payloads[path], incoming) for path in inv.pending_payloads("cards"))]
    else:
        spaces.get(space)                       # SpaceNotFound for a space config.json doesn't list
        sheet = inv.collection(space)
        sources = [(sheet, owned)] if sheet.exists else []
    for sheet, counts in sources:
        unreadable.check(sheet)
        for row in sheet.rows:
            written = (row.get("name") or "").strip()
            name = written if decks.is_basic_land(written) else cards.resolve(written)
            if name and decks.is_basic_land(name):
                try:
                    qty = int(row.get("quantity", ""))
                except (ValueError, TypeError):
                    continue  # load_pool reports invalid rows
                if qty > 0:
                    counts[name] += qty
    return owned, incoming


def space_choices():
    """[{"id", "name"}] of every space whose inventory this request sees
    (guard.sees_inventory), home first (named "Home")."""
    from . import guard
    seen = guard.inventory_spaces()
    return [{"id": s.id, "name": s.name} for s in spaces.list_spaces() if seen is None or s.id in seen]


def space_param(value):
    """The space a request names (home when left out or blank); ApiError 400
    for a value that isn't a space id. One config.json doesn't list answers
    as a space the request may not see would (guard.COLLECTION_HIDDEN's 403,
    E10-S29), so no answer tells a missing space from a hidden one; only a
    script naming nobody, which sees every space, gets 404 "No space"."""
    from . import guard
    if value in (None, ""):
        return spaces.HOME
    if not isinstance(value, str) or len(value) > 40:
        raise ApiError(400, "space must be home or a person's space id")
    if not spaces.exists(value):
        if guard.script() and guard.viewer() is None:
            raise ApiError(404, f"No space {value!r}")
        raise ApiError(403, guard.COLLECTION_HIDDEN)
    return value


def editable(space):
    """Whether the viewer may change space's collection (guard.py: collection.edit;
    the login's, or at home the chooser's profile; a script naming nobody may)."""
    from . import guard
    return guard.allowed(guard.viewer(), "collection.edit", space)


def collection_view(q=None, color=None, type=None, role=None, mv=None,
                    availability=None, page=None, limit=None, space=None):
    """GET /api/collection. All filters optional; name and Oracle text share q.

    color is W/U/B/R/G/C (contains that colour; C means colourless), mv is
    exact mana value. availability is all/free/incoming/held. Basic land
    allocations are not tracked, so their free_now and held values are null.
    space (home by default) is whose pool; the answer also has "space",
    "spaces" ([{"id", "name"}] of those it may see, home first, named "Home") and "editable"
    (whether this visitor may change that collection). 403 for a space whose
    inventory the visitor may not see (guard.require_sees_inventory: home's
    only the home profiles, a person's only that person, whatever the role;
    E10-S29), and the same 403 for a space that doesn't exist (space_param).
    A row's holders name only decks the visitor may see (_holders), its
    incoming is a count, and the warnings leave out what it may not be told
    (library.visible_warnings, visible_unresolved).
    """
    from . import guard
    space = space_param(space)
    guard.require_sees_inventory(space)
    q, color, type, role = (_text(value, name) for value, name in
                           ((q, "q"), (color, "color"), (type, "type"), (role, "role")))
    if color not in ("", "W", "U", "B", "R", "G", "C"):
        raise ApiError(400, "color must be W, U, B, R, G or C")
    availability = availability or "all"
    if availability not in ("all", "free", "incoming", "held"):
        raise ApiError(400, "availability must be all, free, incoming or held")
    page, limit = _integer(page, "page", 1, 10000), _integer(limit, "limit", 24, 100)
    if mv not in (None, ""):
        try:
            mv = float(mv)
            if not math.isfinite(mv) or not 0 <= mv <= 1000:
                raise ValueError()
        except (TypeError, ValueError):
            raise ApiError(400, "mv must be a nonnegative mana value") from None
    else:
        mv = None
    _require_cards()
    try:
        # One inventory snapshot: the request's (server_http pins one per request).
        p = pool.load_pool() if space == spaces.HOME else pool.load_pool(space)
        special, special_incoming = _special_basics(space)
        answer = _collection(p, special, special_incoming, q, color, type, role, mv,
                             availability, page, limit, guard.deck_reader())
    except (ValueError, OSError, csv.Error) as error:
        if space == spaces.HOME and not guard.sees_home_records():
            raise ApiError(409, "The collection couldn't be read.") from None
        raise ApiError(409, f"The collection couldn't be read: {_public(error)}") from None
    return {**answer, "space": space, "spaces": space_choices(), "editable": editable(space)}


def _holder(deck, quantity, sees):
    """One deck holding copies of a card, for the Collection page: its id and title when the
    viewer may see it (sees: guard.deck_reader()), else no id and "one of the home decks"
    (guard.hidden_deck), so no holder names a deck the viewer can't see (E10-S29)."""
    from . import guard
    from .inventory_views import named_holder
    if named_holder(deck.id, sees):
        return {"id": deck.id, "title": deck.title, "quantity": quantity}
    return {"id": None, "title": guard.hidden_deck(deck.id), "quantity": quantity}


def _holders(p, name, sees):
    """_holder of each deck holding name, the hidden ones merged into one per space's words
    (copies summed), so their count isn't told either."""
    shown, hidden = [], {}
    for d in p.in_use:
        if not d.cards[name]:
            continue
        holder = _holder(d, d.cards[name], sees)
        if holder["id"] is not None:
            shown.append(holder)
        elif holder["title"] in hidden:
            hidden[holder["title"]]["quantity"] += holder["quantity"]
        else:
            hidden[holder["title"]] = holder
    return shown + list(hidden.values())


def _collection(p, special, special_incoming, q, color, type, role, mv, availability, page, limit,
                sees=lambda deck_id: True):
    from .library import visible_unresolved, visible_warnings
    names = set(p.owned) | set(special) | set(special_incoming)
    rows, roles, types = [], set(), set()
    for name in sorted(names, key=str.casefold):
        card = cards.card(name)
        basic = decks.is_basic_land(name)
        incoming = special_incoming[name] if basic else sum(qty for _, qty in p.on_the_way.get(name, []))
        owned = special[name] if basic else max(0, p.owned[name] - incoming)
        holders = _holders(p, name, sees) if not basic else []
        held = sum(d["quantity"] for d in holders) if not basic else None
        free = max(0, owned - held) if held is not None else None
        if card:
            roles.update(card.get("roles", []))
            types.update(card.get("type_line", "").split(" — ")[0].split())
        if q.casefold() not in (name + " " + (card or {}).get("oracle_text", "")).casefold():
            continue
        if color and (not card or (bool(card["colors"]) if color == "C" else color not in card["colors"])):
            continue
        if type and (not card or type.casefold() not in card["type_line"].casefold()):
            continue
        if role and (not card or role not in card.get("roles", [])):
            continue
        if mv is not None and (not card or card["cmc"] != mv):
            continue
        if availability == "free" and not free or availability == "incoming" and not incoming \
                or availability == "held" and not held:
            continue
        rows.append({"name": name, "owned": owned, "incoming": incoming, "held": held,
                     "free_now": free, "holders": holders, "basic": basic,
                     "resolved": card is not None, "card": card})
    total = len(rows)
    # A page past the end (an old address, a smaller page size, a shrunken collection) shows the last one.
    pages = max(1, math.ceil(total / limit))
    page = min(page, pages)
    shown = rows[(page - 1) * limit:page * limit]
    for row in shown:
        if row["card"]:
            row["card"] = _card_json(row["card"], _shown_printing(row["card"]))
    # Only the warnings and unknown names this viewer may be told (E10-S29): none about a deck it
    # can't see, none about home's orders and products unless it sees home's records.
    warnings = visible_warnings(p)
    unresolved = visible_unresolved(p.unresolved, sees)
    if unresolved:
        warnings.append("Some inventory names are unresolved: " + ", ".join(sorted(unresolved)))
    return {"cards": shown, "total": total, "page": page, "limit": limit,
            "pages": pages, "roles": sorted(roles), "types": sorted(types),
            "warnings": _scrub(warnings),
            "note": "Ordinary basics are assumed plentiful. Tracked special basics are shown, but their deck allocation isn't tracked."}
