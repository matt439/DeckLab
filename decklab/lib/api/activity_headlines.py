"""The Activity page's headlines (lib/api/activity.py's): describe() words a change from only
the rows a viewer may see ("Matt received the Ronin Games order: 16 cards"), with the KINDS it
belongs to and the deck or order it links to.

It speaks through activity_summaries' words and activity_counts' totals; the orders' sellers
and contents come in as activity.OrderFacts (read from the inventory there, where the tests
patch _load_orders).
"""
from decklab.lib.state import rules

from . import activity_aliases
from .activity_counts import _copies, _n, _record
from .activity_summaries import (INVENTORY_FIELDS, ITEM_TABLES, _card, _changes, _dict, _faces, _product_name, _stem,
                                 _text, _title, _whose)


SOMEONE = "someone"                         # an actor a viewer can't be told about


# ------------------------------------------------------------------ headlines

KINDS = ("decks", "collection", "tokens", "shopping", "wishlist", "sleeves", "games", "settings")
_KIND_OF = {
    "collection_card": "collection", "collection_import": "collection", "token_card": "tokens",
    **{table: "shopping" for table in ("product", "product_status", "purchase_order", "order_component",
                                        "watchlist_item", *ITEM_TABLES)},
    rules.DECK_TABLE: "decks", "deck_alias": "decks", "packing_tick": "decks", rules.ACCESSORY_TABLE: "sleeves", "wishlist_entry": "wishlist",
    "play_record": "games", **{table: "settings" for table in ("profile_setting", "simulation_mode", "visibility", "commander_night", "space",
                                                                "profile", "profile_email")},
}
_MODE_WORDS = {"admins": "admins only", "everyone": "everyone", "paused": "paused"}
_DECK_STATUS = {"idea": "an idea", "building": "being built", "built": "built"}


def _collection_words(space, profiles, own=None):
    """How a headline names a space's collection: "the collection" at home, "User2's collection",
    "your collection" to User2."""
    whose = _whose(space, profiles or {}, own)
    return "the collection" if whose == "the home" else f"{whose} collection"


def _order_name(order_id, orders, by):
    facts = orders.get(order_id) if orders is not None else None
    seller = (facts or {}).get("seller")
    if seller is None:
        for row in by.get("purchase_order", ()):
            record = _record(row)
            if record.get("id") == order_id and isinstance(record.get("seller"), str) and record["seller"].strip():
                seller = record["seller"]
    return f"the {seller} order" if seller else f"the order {_text(order_id)}"


def _contents(order_id, component_ids, orders):
    """What components of an order hold, in words ("16 cards", "13 token cards", "Wretched
    Ranks"), or None when the inventory can't say."""
    facts = orders.get(order_id) if orders is not None else None
    if not facts or not component_ids:
        return None
    cards = tokens = 0
    products = []
    for cid in component_ids:
        part = facts["components"].get(cid)
        if part is None:
            return None
        if part["kind"] == "product":
            products.append(part["label"] or cid)
        elif part["quantity"] is None:
            return None
        elif part["kind"] == "tokens":
            tokens += part["quantity"]
        else:
            cards += part["quantity"]
    words = ([_n(cards, "card")] if cards else []) + ([_n(tokens, "token card")] if tokens else []) + products
    return " and ".join(words) if words else None


def _lower(text):
    return text[:1].lower() + text[1:]


def _upper(text):
    return text[:1].upper() + text[1:]


def _verb(rows, removed="removed"):
    """"added" when every row was added, removed (its words) when every one was, else "changed"."""
    ops = {row.get("op") for row in rows}
    return "added" if ops == {"INSERT"} else removed if ops == {"DELETE"} else "changed"


def describe(rows, actor_name, orders=None, groups=(), profiles=None, *, own=None, past=None):
    """(headline, kinds, link) of a change, worded from only the rows a viewer may see
    (visible_change's), so nothing hidden from them is ever said: headline is a plain sentence
    ("Matt received the Ronin Games order: 16 cards"); kinds the KINDS its rows belong to (a
    deck table that an inventory change refreshed doesn't count); link what it's about,
    {"deck": id} or {"order": id}, or None. orders: OrderFacts (None: orders by their ids);
    groups: the (table, key) of the counted item rows shown; profiles: for space names; own: the
    viewer's own space when it isn't home's ("your collection"); past: the store's counts of the
    rows past the cap by table (None: not given, so totals with rows past the cap are "at
    least")."""

    def past_of(table):
        return None if past is None else _dict(past).get(table, {})
    who = _upper(actor_name or SOMEONE)
    more = any(row.get("table") is None for row in rows)
    by = {}
    for row in rows:
        if row.get("table"):
            by.setdefault(row["table"], []).append(row)
    phrases = []                # (words, link)
    covered = set()             # tables a phrase before already speaks for

    def take(table, keep=lambda row: True):
        found = [row for row in by.get(table, ()) if keep(row)]
        by[table] = [row for row in by.get(table, ()) if not keep(row)]
        return found

    # Shopping: deliveries, cancellations, new orders, changed orders and products
    received, cancelled = {}, {}
    for row in take("order_component", lambda r: r.get("op") == "UPDATE"
                    and _dict(r.get("after")).get("status") in ("received", "cancelled")
                    and _dict(r.get("before")).get("status") != _dict(r.get("after")).get("status")):
        after = _dict(row.get("after"))
        target = received if after.get("status") == "received" else cancelled
        target.setdefault(after.get("order_id"), []).append(after.get("id"))
    if received:
        if len(received) == 1:
            (oid, cids), = received.items()
            what = _contents(oid, cids, orders)
            phrases.append((f"received {_order_name(oid, orders, by)}" + (f": {what}" if what else ""), {"order": oid}))
        else:
            phrases.append((f"received {_n(len(received), 'order')}", None))
        covered.update(("collection_card", "token_card", "product_status", "collection_import"))
    for oid, cids in cancelled.items():
        what = _contents(oid, cids, orders)
        phrases.append((f"cancelled {what or 'part'} of {_order_name(oid, orders, by)}", {"order": oid}))
    new_orders = [_record(r).get("id") for r in by.get("purchase_order", ()) if r.get("op") == "INSERT"]
    if new_orders:
        if len(new_orders) == 1:
            oid = new_orders[0]
            facts = orders.get(oid) if orders is not None else None
            what = _contents(oid, list((facts or {}).get("components", {})), orders)
            phrases.append((f"recorded {_order_name(oid, orders, by)}" + (f": {what}" if what else ""), {"order": oid}))
        else:
            phrases.append((f"recorded {_n(len(new_orders), 'order')}", None))
        covered.update(("purchase_order", "order_component", "product", "product_status", *ITEM_TABLES))
    else:
        changed = {_record(r).get("id") for r in take("purchase_order")}
        changed |= {_record(r).get("order_id") for r in take("order_component")}
        changed |= {key.get("order_id") for table, key in groups if table in ("order_card_item", "order_token_item")}
        changed = {oid for oid in changed if isinstance(oid, str) and oid not in received and oid not in cancelled}
        if len(changed) == 1:
            oid = next(iter(changed))
            phrases.append((f"changed {_order_name(oid, orders, by)}", {"order": oid}))
        elif changed:
            phrases.append((f"changed {_n(len(changed), 'order')}", None))
    if "product_status" not in covered:
        for row in take("product_status"):
            before, after = _dict(row.get("before")), _dict(row.get("after"))
            name = _stem(after or before)
            if row.get("op") == "UPDATE" and before.get("intact") != after.get("intact") and after.get("intact"):
                phrases.append(({"yes": f"kept {name} intact", "no": f"broke up {name}"}.get(
                    after.get("intact"), f"changed the product {name}"), None))
            else:
                phrases.append((f"changed the product {name}", None))
    if "product" not in covered:
        products = take("product")
        if products:
            verb = _verb(products)
            phrases.append((f"{verb} the product {_product_name(_record(products[0]))}" if len(products) == 1
                            else f"{verb} {_n(len(products), 'product')}", None))

    # Decks: added, deleted, marked built, renamed. An update that changed none of the fields
    # shown is a save of its text (or, beside an inventory change, the table it refreshed).
    decks = by.get(rules.DECK_TABLE, [])
    saved = [row for row in decks if row.get("op") == "UPDATE" and activity_aliases.unchanged_header(row)
             and not _changes(_dict(row.get("before")), _dict(row.get("after")),
                              {"title": "", "status": "", "played_by": ""})]
    real = [row for row in decks if row not in saved]
    inventory_rows = any(by.get(table) for table in INVENTORY_FIELDS) or bool(groups)
    refresh_only = bool(saved) and not real and (bool(phrases) or inventory_rows)
    if len(real) == 1:
        row = real[0]
        before, after = _dict(row.get("before")), _dict(row.get("after"))
        title = _title(after or before)
        link = {"deck": _record(row).get("id")}
        if row.get("op") == "INSERT":
            phrases.append((f"added the deck {title}", link))
        elif row.get("op") == "DELETE":
            phrases.append((f"deleted the deck {title}", {"history": _record(row).get("id")}))
        elif before.get("title") != after.get("title") or before.get("id") != after.get("id"):
            phrases.append((activity_aliases.rename_words(before, after, _title(before), title), link))
        elif before.get("status") != after.get("status"):
            status = _DECK_STATUS.get(after.get("status"), _text(after.get("status")))
            phrases.append((f"marked {title} as {status}", link))
        else:
            phrases.append((f"changed who plays {title}", link))
    elif real:
        phrases.append((f"{_verb(real, 'deleted')} {_n(len(real), 'deck')}", None))
    if saved and not refresh_only and not real:
        if len(saved) == 1:
            phrases.append((f"saved {_title(_dict(saved[0].get('after')))}", {"deck": _record(saved[0]).get("id")}))
        else:
            phrases.append((f"updated {_n(len(saved), 'deck')}", None))

    # The inventory's cards and the watchlist
    if "collection_card" not in covered:
        cards = take("collection_card")
        imports = [r for r in take("collection_import") if r.get("op") != "DELETE"]
        if cards:
            spaces_ = {_record(r).get("space_id") for r in cards}
            where = _collection_words(next(iter(spaces_)), profiles, own) if len(spaces_) == 1 else "the collections"
            words = _copies(cards, more, "card", (f"to {where}", f"from {where}", f"in {where}"),
                            lambda r: _text(r.get("name")), past_of("collection_card"))
            if imports:
                words = f"imported {_text(_record(imports[0]).get('file_name'))} ({words})"
            phrases.append((words, None))
        elif imports:
            phrases.append((f"kept the raw import {_text(_record(imports[0]).get('file_name'))}", None))
    if "token_card" not in covered:
        tokens = take("token_card")
        if tokens:
            spaces_ = {_record(r).get("space_id") for r in tokens}
            whose = _whose(next(iter(spaces_)), profiles or {}, own) if len(spaces_) == 1 else "the home"
            where = "" if whose == "the home" else f"{whose} token cards"
            phrases.append((_copies(tokens, more, "token card", (f"to {where}" if where else "",
                                                                 f"from {where}" if where else "",
                                                                 f"in {where}" if where else ""),
                                    lambda r: f"the token card {_faces(r)}", past_of("token_card")), None))
    watch = take("watchlist_item")
    if watch:
        phrases.append((_copies(watch, more, "card", ("to the watchlist", "from the watchlist", "on the watchlist"),
                                lambda r: _text(r.get("name")), past_of("watchlist_item")), None))

    # Sleeves and boxes, wishlists, games, settings, and the admins' own rows
    if take("packing_tick"):
        phrases.append(("updated packing progress", None))
    for row in take("commander_night"):
        phrases.append(("cleared Commander-night notes" if row["summary"].endswith("cleared")
                        else "updated Commander-night notes", None))
    kit = take(rules.ACCESSORY_TABLE)
    if len(kit) == 1:
        phrases.append((_lower(kit[0]["summary"]), None))
    elif kit:
        phrases.append((f"{_verb(kit)} {len(kit)} sleeves, boxes and playmats", None))
    wish = take("wishlist_entry")         # only its owner ever sees a wishlist row
    if len(wish) == 1:
        name = _card(_record(wish[0]))
        phrases.append(({"INSERT": f"added {name} to your wishlist", "DELETE": f"removed {name} from your wishlist"}
                        .get(wish[0].get("op"), f"changed {name} on your wishlist"), None))
    elif wish:
        verb = _verb(wish)
        word = {"added": "to", "removed": "from"}.get(verb, "on")
        phrases.append((f"{verb} {_n(len(wish), 'card')} {word} your wishlist", None))
    games = take("play_record")
    if len(games) == 1:
        summary = games[0]["summary"]
        phrases.append((f"recorded{summary[len('Saved'):]}" if summary.startswith("Saved") else _lower(summary), None))
    elif games:
        phrases.append((f"changed {_n(len(games), 'game record')}", None))
    chosen = take("profile_setting")
    if len(chosen) == 1:
        record = _record(chosen[0])
        key = _text(record.get("key"))
        phrases.append((f"reset the {key} setting" if chosen[0].get("op") == "DELETE"
                        else f"set the {key} to {_text(record.get('value'), 'nothing')}", None))
    elif chosen:
        phrases.append((f"changed {_n(len(chosen), 'setting')}", None))
    for row in take("simulation_mode"):
        mode = _dict(row.get("after")).get("mode")
        phrases.append(("set simulations back to the default" if row.get("op") == "DELETE"
                        else f"set simulations to {_MODE_WORDS.get(mode, _text(mode))}", None))
    for row in take("visibility"):
        phrases.append((_lower(row["summary"]), None))
    if take("space") + take("profile") + take("profile_email"):
        phrases.append(("updated the profiles", None))

    words = [phrase for phrase, _link in phrases]
    for i in range(1, min(len(words), 2)):
        verb = words[0].split(" ", 1)[0]
        if words[i].startswith(verb + " ") and ":" not in words[0]:
            words[i] = words[i][len(verb) + 1:]          # "added 19 decks and 16 sleeves, ..."
    if not phrases:
        headline = f"{who} made a change"
    elif len(words) == 1:
        headline = f"{who} {words[0]}"
    elif len(words) == 2:
        joiner = ", and " if ":" in words[0] else " and "
        headline = f"{who} {words[0]}{joiner}{words[1]}"
    else:
        headline = f"{who} {words[0]}, {words[1]} and more"
    kinds = set()
    for row in rows:
        kind = _KIND_OF.get(row.get("table"))
        if kind and not (kind == "decks" and refresh_only):
            kinds.add(kind)
    if any(table in ITEM_TABLES for table, _key in groups):
        kinds.add("shopping")
    link = next((link for _words, link in phrases
                 if link and all(isinstance(value, str) and value for value in link.values())), None)
    return headline, [kind for kind in KINDS if kind in kinds], link
