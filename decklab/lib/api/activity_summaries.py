"""The Activity page's row summaries (lib/api/activity.py's): each audit row a viewer may see,
in plain words ("Added Plains (SLD 1513) to your wishlist", "Received the Ronin Games order
(cards) on ..."), and the counted item rows ("Added 12 card rows to order X (cards)").

Pure words from a row's before and after, and the tables they belong to (the inventory's
tables, its counted item tables, its spaced tables); activity.py's _row decides whether a row
is shown at all, and re-exports the table names it reads from here.
"""
from decklab.lib import permissions
from decklab.lib.state import Invalid, pods, rules

from . import activity_aliases

# Inventory audit rows stay in their own space, independently from public readers. Collections,
# tokens and imports name theirs; the orders, products and watchlist are home's. SQL caps rows.
INVENTORY_FIELDS = {
    "collection_card": ("space_id", "name", "set_code", "collector_number", "finish", "quantity"),
    "collection_import": ("space_id", "file_name"),
    "token_card": ("space_id", "front", "back", "quantity"),
    "dice_counter": ("space_id", "item_type", "die_size", "counter_kind", "design", "quantity"),
    "product": ("stem", "name"),
    "product_status": ("file", "status", "intact", "sleeves", "deck_box"),
    "purchase_order": ("id", "seller", "ordered_on"),
    "order_component": ("order_id", "id", "kind", "status", "received_on"),
    "watchlist_item": ("name", "set_code", "collector_number", "quantity", "for_deck", "state"),
}
# Rows counted per change set rather than listed (a product's list, an order's payload): their
# audit rows hold cells without column names, and an import has hundreds of them.
ITEM_TABLES = ("product_item", "order_card_item", "order_token_item")
SPACE_TABLES = ("collection_card", "collection_import", "token_card", "dice_counter")
PROFILE_FIELDS = (("name", "name"), ("role", "role"), ("space_id", "space"), ("plays_as", "plays as"))


def _deck_space(deck_id):
    """A deck's space, with no home fallback for malformed ids."""
    return activity_aliases.deck_space(deck_id)



def _dict(value):
    return value if isinstance(value, dict) else {}



# ------------------------------------------------------------------ summaries

def _text(value, default="?"):
    return value if isinstance(value, str) and value else default


def _printing(r):
    """A wishlist row's printing as the page writes it ("SLD 1513"), or "" for none."""
    code, number = r.get("set_code"), r.get("collector_number")
    return f"{code.upper()} {number}" if isinstance(code, str) and code and isinstance(number, str) and number else ""


def _card(r):
    printing = _printing(r)
    return _text(r.get("name")) + (f" ({printing})" if printing else "")


def _wishlist_summary(op, before, after, whose):
    if op == "INSERT":
        return f"Added {_card(after)} to {whose} wishlist"
    if op == "DELETE":
        return f"Removed {_card(before)} from {whose} wishlist"
    parts = []
    if _text(before.get("name")) != _text(after.get("name")):
        parts.append(f"name {_text(before.get('name'))} → {_text(after.get('name'))}")
    if _printing(before) != _printing(after):
        parts.append(f"printing {_printing(before) or 'any'} → {_printing(after) or 'any'}")
    parts += [key for key in ("notes", "source") if before.get(key) != after.get(key)]
    if before.get("position") != after.get("position"):
        parts.append("its place in the list")
    head = f"Changed {_text(after.get('name'))} on {whose} wishlist"
    return f"{head}: {', '.join(parts)}" if parts else head


def _arrival_words(op, record):
    """An arrival notice's row in words (E6-S19, lib/arrivals.py): "arrival notice for order X" (a
    further part's "arrival notice") or "arrival notice removed" (dismissed, or the oldest dropped
    for a new one), never its stored JSON; None for any other setting."""
    from decklab.lib import arrivals
    if not arrivals.is_key(_text(record.get("key"))):
        return None
    if op == "DELETE":
        return "arrival notice removed"
    found = arrivals._parse(record.get("value"))
    return f"arrival notice for order {found['o']}" if found else "arrival notice"


def _setting_summary(op, before, after, whose):
    key = _text((after or before).get("key"))
    whose = "Your" if whose == "your" else whose        # "Your theme", "Matt's theme"
    arrival = _arrival_words(op, after or before)
    if arrival is not None:
        return f"{whose} {arrival}"
    if op == "INSERT":
        return f"{whose} {key}: {_text(after.get('value'), '')}"
    if op == "DELETE":
        return f"{whose} {key}: {_text(before.get('value'), '')} → the default"
    return f"{whose} {key}: {_text(before.get('value'), '')} → {_text(after.get('value'), '')}"


def _mode_summary(op, before, after):
    if op == "DELETE":
        return "Simulations: back to the default"
    if op == "UPDATE" and before.get("mode") != after.get("mode"):
        return f"Simulations: {_text(before.get('mode'))} → {_text(after.get('mode'))}"
    return f"Simulations: {_text(after.get('mode'))}"


def _title(snapshot):
    snapshot = _dict(snapshot)
    return _text(snapshot.get("title"), _text(snapshot.get("id"), "a deck"))


def _play_owners(r):
    """The deck ids of a play_record row whose spaces see it: a game's sides, a sideboard plan's
    deck only (E10-S32: a plan belongs to its deck's space)."""
    ids = r.get("deck_ids") or ()
    if r.get("kind") == "games":
        try:
            if pods.mode(_dict(r.get("content"))) == "pod":
                found = pods.record_deck_ids(r["content"])
                return found if r.get("deck_ids") == found else []
        except Invalid:
            return []        # malformed or mismatched pod ownership grants nobody a read
    if r.get("kind") == "sideboards":
        deck = _dict(_dict(r.get("content")).get("deck")).get("id")
        return [deck] if isinstance(deck, str) else list(ids)[:1]
    return list(ids)


def _play_recorder(r, space_of):
    """The space whose a play_record row's saver is (play_records._recording_space): a game's
    stored "space", or for one saved before E10-S32 a home side's, else its first side's; a
    plan's deck's space (a plan belongs to its deck's space). None when none can be read."""
    content = _dict(r.get("content"))
    if r.get("kind") == "sideboards":
        deck = _dict(content.get("deck")).get("id")
        return space_of(deck) if isinstance(deck, str) else None
    if isinstance(content.get("space"), str):
        return content["space"]
    found = [space_of(d) for d in (r.get("deck_ids") or ()) if isinstance(d, str)]
    found = [space for space in found if space]
    return permissions.HOME if permissions.HOME in found else (found[0] if found else None)


def _hidden_title(deck_id, space_of, profiles):
    """A deck the viewer may not see, by its space only: "one of the home decks", "one of
    User2's decks", else "a deck" (guard.hidden_deck's words, from config.json's profiles)."""
    space = space_of(deck_id) if isinstance(deck_id, str) else None
    if space == permissions.HOME:
        return "one of the home decks"
    for profile in (profiles or {}).values():
        if space is not None and (profile.get("space") or permissions.HOME) == space:
            return f"one of {profile['name']}'s decks"
    return "a deck"


def _play_summary(op, record, seen=None, profiles=None, space_of=None):
    """A play summary: hidden decks by space only, removed decks without their old identity."""
    content = _dict(record.get("content"))
    verb = {"INSERT": "Saved", "UPDATE": "Changed", "DELETE": "Removed"}.get(op, "Changed")
    space_of = space_of or _deck_space

    def title(snapshot):
        deck_id = _dict(snapshot).get("id")
        if seen is not None and not rules.is_removed_deck(snapshot) and not seen(deck_id):
            return _hidden_title(deck_id, space_of, profiles)
        return _title(snapshot)
    if record.get("kind") == "sideboards":
        return f"{verb} a sideboard plan: {title(content.get('deck'))} vs {title(content.get('opponent'))}"
    if record.get("kind") == "games":
        try:
            if pods.mode(content) == "pod":
                if not _play_owners(record):
                    return f"{verb} a play record"
                return f"{verb} a {len(content['seats'])}-player pod game"
        except Invalid:
            return f"{verb} a play record"
    sides = content.get("sides") if isinstance(content.get("sides"), list) else []
    a, b = (title(sides[i]) if i < len(sides) else "a deck" for i in (0, 1))
    result = content.get("result")
    outcome = {"a": f", {a} won", "b": f", {b} won", "draw": ", a draw"}.get(result, "")
    return f"{verb} a game: {a} vs {b}{outcome}"


def _space_summary(op, record, profiles=None):
    """"Added User3's space" (by the profile whose space it is), or "the space user3" when no
    profile config.json lists has it."""
    space = _text(record.get("id"))
    whose = _whose(space, profiles or {}) if space != "?" else None
    what = "the home space" if whose == "the home" else f"{whose} space" if whose and whose != f"{space}'s" \
        else f"the space {space}"
    return {"INSERT": f"Added {what}", "DELETE": f"Removed {what}"}.get(op, f"Changed {what}")


def _profile_summary(op, before, after):
    if op == "INSERT":
        return f"Added the profile {_text(after.get('name'))} ({_text(after.get('role'))})"
    if op == "DELETE":
        return f"Removed the profile {_text(before.get('name'))}"
    parts = [f"{words} {_text(before.get(key), 'none')} → {_text(after.get(key), 'none')}"
             for key, words in PROFILE_FIELDS if before.get(key) != after.get(key)]
    if before.get("position") != after.get("position"):
        parts.append("its place in the list")
    head = f"Changed the profile {_text(after.get('name'))}"
    return f"{head}: {', '.join(parts)}" if parts else head


# ------------------------------------------------------------------ the inventory

def _inventory_space(table, row):
    """The space an inventory row belongs to: its space_id for a collection, token or raw import
    row (home when it can't be read), home for the orders, products and the watchlist."""
    if table in SPACE_TABLES:
        for record in (row.get("after"), row.get("before"), row.get("key")):
            if isinstance(record, dict) and isinstance(record.get("space_id"), str):
                return record["space_id"]
    return permissions.HOME


def _only_position(op, before, after):
    """True for an update whose only change is the row's place in its list."""
    if op != "UPDATE" or not before or not after:
        return False
    return {k: v for k, v in before.items() if k != "position"} == {k: v for k, v in after.items() if k != "position"}


def _whose(space, profiles, own=None):
    """How a space is named in a summary: "the home" or "User2's" (by the profile whose space
    it is; the id itself for a space config.json no longer lists), and "your" for own (the
    viewer's own space, when it isn't home's)."""
    if space == permissions.HOME:
        return "the home"
    if own is not None and space == own:
        return "your"
    for profile in profiles.values():
        if (profile.get("space") or permissions.HOME) == space:
            return f"{profile['name']}'s"
    return f"{space}'s"


def _qty(r):
    q = r.get("quantity")
    return q if isinstance(q, int) and not isinstance(q, bool) else _text(q if isinstance(q, str) else None)


def _collection_card(r):
    """A collection row's card as the pages write it: "Llanowar Elves (FDN 227)", with the
    finish when it isn't nonfoil ("Llanowar Elves (FDN 227, foil)")."""
    printing = _printing(r)
    finish = r.get("finish")
    if isinstance(finish, str) and finish and finish != "nonfoil":
        printing = f"{printing}, {finish}" if printing else finish
    return _text(r.get("name")) + (f" ({printing})" if printing else "")


def _changes(before, after, fields):
    """Plain words for what changed among fields ({key: words}): a quantity, status or state as
    "quantity 2 → 3", anything else by its words alone."""
    parts = []
    for key, words in fields.items():
        if before.get(key) == after.get(key):
            continue
        if key in ("quantity", "status", "intact", "state"):
            old, new = (v if v not in (None, "") else "none" for v in (before.get(key), after.get(key)))
            parts.append(f"{words} {old} → {new}")
        else:
            parts.append(words)
    return parts


def _changed(head, parts):
    return f"{head}: {', '.join(parts)}" if parts else head


def _collection_summary(op, before, after, whose):
    where = f"{whose} collection"
    if op == "INSERT":
        return f"Added {_qty(after)} × {_collection_card(after)} to {where}"
    if op == "DELETE":
        return f"Removed {_qty(before)} × {_collection_card(before)} from {where}"
    parts = _changes(before, after, {"quantity": "quantity", "name": "name", "condition": "condition",
                                     "language": "language", "notes": "notes",
                                     "location": "storage location"})
    return _changed(f"{_collection_card(after)} in {where}", parts)


def _faces(r):
    back = r.get("back")
    return _text(r.get("front")) + (f" // {back}" if isinstance(back, str) and back else "")


def _token_summary(op, before, after, whose):
    where = f"{whose} token cards"
    if op == "INSERT":
        return f"Added {_qty(after)} × {_faces(after)} to {where}"
    if op == "DELETE":
        return f"Removed {_qty(before)} × {_faces(before)} from {where}"
    parts = _changes(before, after, {"quantity": "quantity", "front": "front", "back": "back",
                                     "front_details": "details", "back_details": "back details", "notes": "notes"})
    if any(before.get(k) != after.get(k) for k in ("set_code", "front_collector_number", "back_collector_number",
                                                     "finish")):
        parts.append("printing")
    return _changed(f"Changed {_faces(after)} in {where}", parts)


def _dice_item(r):
    """A dice_counter row as the Tokens page names it: "d20 (red)", "poison counter", "counter"."""
    if r.get("item_type") == "die":
        words = _text(r.get("die_size"), "die")
    else:
        kind = r.get("counter_kind")
        words = f"{kind} counter" if isinstance(kind, str) and kind else "counter"
    design = r.get("design")
    return f"{words} ({design})" if isinstance(design, str) and design else words


def _dice_summary(op, before, after, whose):
    where = f"{whose} dice and counters"
    if op == "INSERT":
        return f"Added {_qty(after)} × {_dice_item(after)} to {where}"
    if op == "DELETE":
        return f"Removed {_qty(before)} × {_dice_item(before)} from {where}"
    parts = _changes(before, after, {"quantity": "quantity", "item_type": "type", "die_size": "size",
                                     "counter_kind": "kind", "design": "design"})
    return _changed(f"Changed {_dice_item(after)} in {where}", parts)


def _import_summary(op, before, after, whose):
    name = _text((after or before).get("file_name"))
    if op == "DELETE":
        return f"Removed the raw import {name} of {whose} collection"
    return f"Kept the raw import {name} for {whose} collection"


def _product_name(r):
    return _text(r.get("name"), _text(r.get("stem")))


def _product_summary(op, before, after, whose):
    if op == "INSERT":
        return f"Added the product {_product_name(after)}"
    if op == "DELETE":
        return f"Removed the product {_product_name(before)}"
    parts = _changes(before, after, {"name": "name", "format": "format", "columns": "its columns"})
    return _changed(f"Changed the product {_product_name(after)}", parts)


def _stem(r):
    file = _text(r.get("file"))
    return file[:-4] if file.endswith(".csv") else file


def _status_summary(op, before, after, whose):
    if op == "INSERT":
        intact = {"yes": ", kept intact", "no": ", broken up"}.get(after.get("intact"), "")
        return f"Listed the product {_stem(after)} as {_text(after.get('status'), 'no status')}{intact}"
    if op == "DELETE":
        return f"Took the product {_stem(before)} off the status list"
    parts = _changes(before, after, {"status": "status", "intact": "intact", "sleeves": "sleeves",
                                     "deck_box": "deck box", "notes": "notes"})
    return _changed(f"The product {_stem(after)}", parts)


def _order_summary(op, before, after, whose):
    oid = _text((after or before).get("id"))
    if op == "INSERT":
        seller = after.get("seller")
        return f"Added the order {oid}" + (f" from {seller}" if isinstance(seller, str) and seller else "")
    if op == "DELETE":
        return f"Removed the order {oid}"
    parts = _changes(before, after, {"seller": "seller", "ordered_on": "order date", "sources": "sources",
                                     "notes": "notes", "audit_notes": "audit notes"})
    return _changed(f"Changed the order {oid}", parts)


def _order_words(order_id, orders=None):
    """An order as a row names it: "the Ronin Games order" when the inventory knows its seller
    (orders: OrderFacts), else "order 2026-10-05-shop-c"."""
    facts = orders.get(order_id) if orders is not None and isinstance(order_id, str) else None
    seller = (facts or {}).get("seller")
    return f"the {seller} order" if seller else f"order {_text(order_id)}"


def _component_summary(op, before, after, whose, orders=None):
    record = after or before
    name = f"{_order_words(record.get('order_id'), orders)} ({_text(record.get('id'))})"
    if op == "INSERT":
        return f"Added {name}: {_text(after.get('kind'))}, {_text(after.get('status'))}"
    if op == "DELETE":
        return f"Removed {name}"
    status = after.get("status")
    if status != before.get("status"):
        received = after.get("received_on")
        if status == "received":
            return f"Received {name}" + (f" on {received}" if isinstance(received, str) and received else "")
        if status == "cancelled":
            return f"Cancelled {name}"
        return f"Put {name} back to {_text(status)}"
    parts = _changes(before, after, {"checks": "checks", "verified_checks": "verified checks",
                                     "received_on": "received date", "file_name": "file", "kind": "kind"})
    return _changed(f"Changed {name}", parts)


def _watch_summary(op, before, after, whose):
    card = _card(after or before)
    if op == "INSERT":
        wanted, state_ = after.get("for_deck"), after.get("state")
        return (f"Added {_qty(after)} × {card} to the watchlist"
                + (f" for {wanted}" if isinstance(wanted, str) and wanted else "")
                + (f" ({state_})" if isinstance(state_, str) and state_ else ""))
    if op == "DELETE":
        return f"Removed {_qty(before)} × {card} from the watchlist"
    parts = _changes(before, after, {"quantity": "quantity", "state": "state", "for_deck": "what it's for",
                                     "printing": "printing", "notes": "notes", "source": "source"})
    if any(before.get(k) != after.get(k) for k in ("listed_aud", "listed_at", "in_stock", "checked")):
        parts.append("price or stock")
    return _changed(f"Changed {card} on the watchlist", parts)


INVENTORY_SUMMARIES = {
    "collection_card": _collection_summary, "collection_import": _import_summary, "token_card": _token_summary,
    "dice_counter": _dice_summary,
    "product": _product_summary, "product_status": _status_summary, "purchase_order": _order_summary,
    "order_component": _component_summary, "watchlist_item": _watch_summary,
}


def _deck_summary(op, before, after, whose):
    record = after or before
    title = _text(record.get("title"), _text(record.get("id"), "a deck"))
    deck = f"the deck {title}" if whose == "the home" else f"{whose} deck {title}"
    if op == "INSERT":
        return f"Added {deck}"
    if op == "DELETE":
        return f"Removed {deck}"
    parts = _changes(before, after, {"title": "title", "status": "status", "played_by": "played by"})
    return _changed(f"Changed {deck}", parts)


def _accessory_visible(owner, owners):
    """Whether a viewer whose accessory owners are owners (permissions.accessory_owners: None for
    everything) sees a row owned by owner (an unreadable owner: only a viewer who sees everything)."""
    return owners is None or (isinstance(owner, str) and owner in owners)


_ACCESSORY_KINDS = {"sleeves": "the sleeves", "deck_box": "the deck box", "playmat": "the playmat"}


def _accessory(r):
    """An accessory as a summary names it: "the sleeves Matte (black)"."""
    kind = _ACCESSORY_KINDS.get(r.get("kind"), "the accessory")
    colour = r.get("colour")
    return f"{kind} {_text(r.get('name'))}" + (f" ({colour})" if isinstance(colour, str) and colour else "")


def _accessory_summary(op, before, after):
    if op == "INSERT":
        return f"Added {_accessory(after)}"
    if op == "DELETE":
        return f"Removed {_accessory(before)}"
    parts = _changes(before, after, {"quantity": "quantity", "name": "name", "colour": "colour", "kind": "kind"})
    others = ("owner", "brand", "capacity", "image", "crop", "link", "image_source", "notes")
    if any(before.get(k) != after.get(k) for k in others):
        parts.append("details")
    return _changed(f"Changed {_accessory(after)}", parts)


def _group(group, spaces):
    """One counted group of item rows ({table, op, key, count}) as a row a viewer who sees
    spaces' inventory (visible_change) may see, {table, op, summary}, or None: products' lists
    and orders' payloads are home's."""
    if spaces is not None and permissions.HOME not in spaces:
        return None
    table, op, key, n = group.get("table"), group.get("op"), _dict(group.get("key")), group.get("count") or 0
    if table not in ITEM_TABLES:
        return None
    rows = f"{n} {'token' if table == 'order_token_item' else 'card'} row{'' if n == 1 else 's'}"
    if table == "product_item":
        target = f"the product {_text(key.get('product_stem'))}'s list"
    else:
        target = f"order {_text(key.get('order_id'))} ({_text(key.get('component_id'))})"
    verb, word = {"INSERT": ("Added", "to"), "DELETE": ("Removed", "from")}.get(op, ("Changed", "in"))
    return {"table": table, "op": op, "summary": f"{verb} {rows} {word} {target}"}


def _group_target(table, key, orders=None):
    if table == "product_item":
        return f"the product {_text(key.get('product_stem'))}'s list"
    return f"{_order_words(key.get('order_id'), orders)} ({_text(key.get('component_id'))})"


def _group_rows(groups, orders=None):
    """The counted groups a viewer sees (visible_change has checked each with _group) as rows: one
    per group ("Added 12 card rows to the MTGMate order (cards)"), but a payload whose rows were all
    removed and written again in the change (an order edited, or corrected at its receipt) as one
    row ("Replaced the card rows of the MTGMate order (cards): 16 → 16"), in the first one's place."""
    import json
    by_key = {}
    for group in groups:
        key = json.dumps(_dict(group.get("key")), sort_keys=True)
        by_key.setdefault((group.get("table"), key), {})[group.get("op")] = group
    out, done = [], set()
    for group in groups:
        table, key = group.get("table"), _dict(group.get("key"))
        ident = (table, json.dumps(key, sort_keys=True))
        if ident in done:
            continue
        pair = by_key[ident]
        noun = "token" if table == "order_token_item" else "card"
        if "INSERT" in pair and "DELETE" in pair:
            done.add(ident)
            old, new = (pair[op].get("count") or 0 for op in ("DELETE", "INSERT"))
            out.append({"table": table, "op": "UPDATE",
                        "summary": f"Replaced the {noun} rows of {_group_target(table, key, orders)}: {old} → {new}"})
            continue
        n = group.get("count") or 0
        rows = f"{n} {noun} row{'' if n == 1 else 's'}"
        verb, word = {"INSERT": ("Added", "to"), "DELETE": ("Removed", "from")}.get(group.get("op"), ("Changed", "in"))
        out.append({"table": table, "op": group.get("op"),
                    "summary": f"{verb} {rows} {word} {_group_target(table, key, orders)}"})
    return out
