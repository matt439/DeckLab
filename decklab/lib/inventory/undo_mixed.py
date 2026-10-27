"""Whole-change Undo for a collection import or a plain order receipt (E11-S08).

These changes touch several kinds of data at once. An import writes collection rows and keeps
the raw upload; a receipt marks order parts received, adds cards and token cards, may set a
product owned, and refreshes the deck tables. Undo is offered only for the complete original
change, never part of it, and only when:

- the change is exactly one of those shapes (a receipt of whole parts with no corrected rows:
  no new components, order notes, payload or product-list rows);
- every row it wrote is still exactly as it left it and is still the latest audit row for its
  key, so a later edit, receipt, kit choice or token packing refuses, naming that row;
- the reversal, built with the ordinary model edits, puts back exactly those rows' former
  values and changes no other inventory row (checked on the tables the database holds);
- the copies it removes aren't held by built decks or intact products (an intact product the
  receipt itself set owned is put back on order with its cards), and token cards it removes
  aren't packed, as the narrower Undo actions check.

The deck rows a receipt's table refresh wrote are derived: they aren't restored, and the
inverse refreshes the tables again. The raw upload of an import stays kept as a record of what
was sent. Removing copies needs a reason, as removing an added row does.
"""
import copy
import hashlib
import json

from . import Summary, backend, current, paths, register, rules
from .model import Order
from decklab.lib.state import Invalid
from .undo import (COLLECTION, COLLECTION_FIELDS, SHA, TOKEN_FIELDS, TOKENS, UndoConflict, UndoMissing,
                   UndoUnsupported, _identifier, _known_decks, _label, removal_reason)

MIXED_MAX = 2000                    # rows of one original change set; the reader returns one more to refuse
IMPORT = "import_undo"
RECEIPT = "receipt_undo"
ACTIONS = (IMPORT, RECEIPT)
COMPONENT = "order_component"
STATUS = "product_status"
RAW_IMPORT = "collection_import"
DECK = "deck"
HOME = paths.HOME
KEYS = {COLLECTION: ("space_id", "set_code", "collector_number", "finish"), TOKENS: ("id",),
        COMPONENT: ("order_id", "id"), STATUS: ("file",), RAW_IMPORT: ("id",), DECK: ("id",)}
COLLECTION_CHANGES = {"quantity", "condition", "language", "notes"}
TOKEN_CHANGES = {"quantity", "notes", "position"}
COMPONENT_CHANGES = {"status", "received_on", "checks", "verified_checks", "check_links"}
STATUS_CHANGES = {"status", "intact", "notes"}
INCOMING = ("ordered", "preordered")
# The inventory tables an inverse may change, and those it must leave exactly as they are.
RESTORED_TABLES = (COLLECTION, TOKENS, COMPONENT, STATUS)
KEPT_TABLES = ("product", "product_item", "purchase_order", "order_card_item", "order_token_item", "watchlist_item")
CHECKED = "This changed after the selected change. Nothing was undone."


# ------------------------------------------------------------------ the source

def looks_like(rows, past, space):
    """IMPORT or RECEIPT when Activity's (possibly capped) rows have that shape in space, else None.

    Only an affordance for Activity's Review undo button: the review reads the whole change."""
    seen = {row.get("table") for row in rows} | set(past or ())
    def own(row):
        image = row.get("after") if isinstance(row.get("after"), dict) else row.get("before")
        return isinstance(image, dict) and image.get("space_id") == space
    if RAW_IMPORT in seen and seen <= {RAW_IMPORT, COLLECTION} and all(
            own(row) and (row.get("op") == "INSERT" or row.get("table") == COLLECTION and row.get("op") == "UPDATE")
            for row in rows):
        return IMPORT
    received = any(row.get("table") == COMPONENT and row.get("op") == "UPDATE"
                   and isinstance(row.get("before"), dict) and isinstance(row.get("after"), dict)
                   and row["before"].get("status") == "pending" and row["after"].get("status") == "received"
                   for row in rows)
    if received and space == HOME and seen <= {COMPONENT, STATUS, COLLECTION, TOKENS, DECK}:
        return RECEIPT
    return None


def _space_of(row):
    image = row.get("after") if isinstance(row.get("after"), dict) else row.get("before")
    if row.get("table") in (COMPONENT, STATUS):
        return HOME                     # orders and products are home's
    return image.get("space_id") if isinstance(image, dict) else None


def _key(row):
    key, fields = row.get("key"), KEYS[row["table"]]
    image = row["after"] if row["op"] != "DELETE" else row["before"]
    if not isinstance(key, dict) or set(key) != set(fields) or not isinstance(image, dict) \
            or any(key[field] != image.get(field) for field in fields):
        raise UndoUnsupported("The original row identity cannot be checked.")
    return key


def _changed(row):
    before, after = row["before"], row["after"]
    if set(before) != set(after):
        raise UndoUnsupported("The recorded row has an unsupported schema.")
    return {field for field in after if before[field] != after[field]}


def _check_row(row, kind):
    """One original row of a supported shape, or UndoUnsupported naming why not."""
    table, op, before, after = row["table"], row["op"], row["before"], row["after"]
    _identifier(row.get("id"))
    if table == DECK:
        if op != "UPDATE" or kind != RECEIPT:
            raise UndoUnsupported("Only a deck table refresh can be part of an undoable receipt.")
        _key(row)
        return
    if table == RAW_IMPORT:
        if op != "INSERT" or before is not None or kind != IMPORT \
                or not isinstance(after.get("file_name"), str) or type(after.get("size")) is not int \
                or not isinstance(after.get("sha256"), str) or not SHA.fullmatch(after["sha256"]):
            raise UndoUnsupported("The kept upload cannot be checked.")
        _key(row)
        return
    if op not in ("INSERT", "UPDATE") or op == "INSERT" and before is not None \
            or op == "UPDATE" and not isinstance(before, dict) or not isinstance(after, dict):
        raise UndoUnsupported("Only additions and updates can be undone as part of an import or receipt.")
    _key(row)
    if table == COLLECTION:
        if set(after) != COLLECTION_FIELDS or type(after["quantity"]) is not int or after["quantity"] < 1:
            raise UndoUnsupported("The collection row has an unsupported schema.")
        if op == "UPDATE":
            changed = _changed(row)
            if not changed or changed - COLLECTION_CHANGES or type(before["quantity"]) is not int \
                    or not 1 <= before["quantity"] < after["quantity"]:
                raise UndoUnsupported("Only collection rows the change added copies to can be put back.")
        return
    if table == TOKENS:
        if kind != RECEIPT or set(after) != TOKEN_FIELDS or type(after["quantity"]) is not int or after["quantity"] < 1:
            raise UndoUnsupported("The token row has an unsupported schema.")
        if op == "UPDATE":
            changed = _changed(row)
            if not changed or changed - TOKEN_CHANGES or type(before["quantity"]) is not int \
                    or "quantity" in changed and not 1 <= before["quantity"] < after["quantity"] \
                    or "quantity" not in changed and changed - {"position"}:
                raise UndoUnsupported("Only token rows the receipt added cards to can be put back.")
        return
    if kind != RECEIPT or op != "UPDATE":
        raise UndoUnsupported("Only order parts and products the receipt updated can be put back.")
    changed = _changed(row)
    if table == COMPONENT:
        if changed - COMPONENT_CHANGES or before.get("status") != "pending" or after.get("status") != "received" \
                or after.get("kind") not in paths.KINDS or not isinstance(after.get("file_name"), str):
            raise UndoUnsupported("Only order parts this receipt marked received can be put back.")
        return
    if changed - STATUS_CHANGES or before.get("status") not in INCOMING or after.get("status") != "owned" \
            or before.get("intact") != "":
        raise UndoUnsupported("Only products this receipt set owned can be put back on order.")


def _source(raw, space):
    """The complete original change, classified, or a refusal: UndoMissing when any row is
    outside space (checked for every row before any shape is diagnosed)."""
    if not isinstance(raw, list) or not raw:
        raise UndoMissing()
    if len(raw) > MIXED_MAX:
        raise UndoUnsupported(f"Undo covers imports and receipts of at most {MIXED_MAX} changed rows.")
    for row in raw:
        if not isinstance(row, dict):
            raise UndoMissing()
        if row.get("table") in KEYS:
            if row.get("op") not in ("INSERT", "UPDATE", "DELETE") or _space_of(row) != space:
                raise UndoMissing()
        elif _space_of_unknown(row, space):
            raise UndoMissing()
    tables = {row["table"] for row in raw}
    if tables - set(KEYS):
        raise UndoUnsupported("This change touches data an import or receipt Undo doesn't restore.")
    if RAW_IMPORT in tables and tables <= {COLLECTION, RAW_IMPORT}:
        kind = IMPORT
    elif COMPONENT in tables and space == HOME and tables <= {COMPONENT, STATUS, COLLECTION, TOKENS, DECK}:
        kind = RECEIPT
    else:
        raise UndoUnsupported("Only a whole collection import or a whole order receipt can be undone here.")
    seen = set()
    for row in raw:
        _check_row(row, kind)
        identity = (row["table"], json.dumps(row["key"], sort_keys=True))
        if identity in seen:
            raise UndoUnsupported("The change names one row twice.")
        seen.add(identity)
    if not any(row["table"] in (COLLECTION, TOKENS) and _restores(row) for row in raw) and kind == IMPORT:
        raise UndoUnsupported("The import added no cards.")
    if kind == RECEIPT:
        products = {row["after"]["file_name"] for row in raw if row["table"] == COMPONENT and row["after"]["kind"] == "product"}
        if {row["key"]["file"] for row in raw if row["table"] == STATUS} != products:
            raise UndoUnsupported("The receipt's product status rows don't match its products.")
    return kind


def _space_of_unknown(row, space):
    """A row of a table this Undo doesn't know: hidden (True) unless it's in space."""
    image = row.get("after") if isinstance(row.get("after"), dict) else row.get("before")
    owner = image.get("space_id") if isinstance(image, dict) else None
    return owner is not None and owner != space or owner is None and space != HOME


def _restores(row):
    """Whether an original row's inverse writes anything (a position-only token move doesn't)."""
    if row["op"] == "INSERT":
        return True
    return row["table"] not in (DECK, RAW_IMPORT) and bool(_changed(row) - {"position"})


# ------------------------------------------------------------------ rows as the database holds them

def _plain(value):
    from .table_rows import JsonColumn
    if isinstance(value, JsonColumn):
        return copy.deepcopy(value.value)
    return list(value) if isinstance(value, tuple) else value


def _images(t):
    """{table: {canonical key: row image}} of tables() for the tables an inverse restores, as
    the audit trail records rows (without token positions, which the model doesn't hold)."""
    from .table_rows import COMPONENT_COLUMNS, STATUS_COLUMNS, TOKEN_COLUMNS
    out = {COLLECTION: {}, TOKENS: {}, COMPONENT: {}, STATUS: {}}
    for (space, set_code, number, finish), (name, quantity, condition, language, notes) in t[COLLECTION].items():
        image = {"space_id": space, "set_code": set_code, "collector_number": number, "finish": finish, "name": name,
                 "quantity": quantity, "condition": condition, "language": language, "notes": notes}
        out[COLLECTION][_canon(COLLECTION, image)] = image
    for rid, space, *cells in t[TOKENS]:
        image = {"id": rid, "space_id": space, **dict(zip(TOKEN_COLUMNS, cells))}
        out[TOKENS][_canon(TOKENS, image)] = image
    for (order_id, component_id), values in t[COMPONENT].items():
        image = {"order_id": order_id, "id": component_id, **{c: _plain(v) for c, v in zip(COMPONENT_COLUMNS, values)}}
        out[COMPONENT][_canon(COMPONENT, image)] = image
    for file, values in t[STATUS].items():
        image = {"file": file, **dict(zip(STATUS_COLUMNS, values))}
        out[STATUS][_canon(STATUS, image)] = image
    return out


def _canon(table, image):
    return json.dumps({field: image[field] for field in KEYS[table]}, sort_keys=True)


def _same(recorded, image):
    """Whether image holds every recorded column's value (positions aside, which the
    latest-audit check covers); a recorded column the model doesn't hold is never the same."""
    if image is None:
        return False
    for field, value in recorded.items():
        if field == "position":
            continue
        if field == "check_links" and field not in image:
            if value is not None:
                return False
            continue
        if field not in image or image[field] != value:
            return False
    return True


def _row_label(row):
    image = row["after"] if row["op"] != "DELETE" else row["before"]
    table = row["table"]
    if table == COLLECTION:
        return _label(COLLECTION, {"set" if k == "set_code" else k: v for k, v in image.items()})
    if table == TOKENS:
        return rules.token_label(image)
    if table == COMPONENT:
        return f"order {image['order_id']} ({image['id']})"
    if table == STATUS:
        return "product " + image["file"].removesuffix(".csv")
    if table == RAW_IMPORT:
        return "upload " + image["file_name"]
    return "deck " + str(image.get("id"))


# ------------------------------------------------------------------ the inverse

def _collection_cells(image):
    return {field: str(image["set_code" if field == "set" else field]) for field in rules.FIELDS}


def _token_cells(image):
    return {field: str(image["set_code" if field == "set" else field]) for field in rules.TOKEN_FIELDS}


def _restore_component(inv, before):
    """The order part as it was before the receipt: its status, date, checks and payload path."""
    from .model import COMPONENT_KEYS
    order = inv.order(before["order_id"])
    if order is None or order.error is not None:
        raise ValueError("The order record can't be read")
    data = order.record()
    items = [item for item in data.get("components") or [] if isinstance(item, dict) and item.get("id") == before["id"]]
    if len(items) != 1:
        raise ValueError("The order part isn't there once")
    item = items[0]
    old = item.get("path")
    new = paths.payload(before["kind"], before["status"], before["file_name"])
    item.update(status=before["status"], path=new, received_on=before["received_on"], checks=list(before["checks"]))
    for field in ("verified_checks", "check_links"):
        if before.get(field) is None:
            item.pop(field, None)
        else:
            item[field] = copy.deepcopy(before[field])
    ordered = {key: item[key] for key in COMPONENT_KEYS if key in item}
    ordered.update((key, value) for key, value in item.items() if key not in COMPONENT_KEYS)
    item.clear()
    item.update(ordered)
    inv = inv.with_order(Order(order.file, data))
    if old != new and old in inv.payloads:
        import dataclasses
        payloads = {k: v for k, v in inv.payloads.items() if k != old}
        payloads[new] = dataclasses.replace(inv.payloads[old], path=new)
        inv = inv.replace(payloads=dict(sorted(payloads.items())))
    return inv


def _inverse(snapshot, raw, space):
    """The ordinary model edits putting every restored row back (before settling)."""
    from .model import TokenRow
    after = snapshot
    collection = [row for row in raw if row["table"] == COLLECTION]
    if collection:
        sheet = snapshot.collection(space)
        if not sheet.exists or sheet.error is not None or sheet.strict_error is not None or sheet.csv_error is not None:
            raise ValueError("The collection can't be read")
        rows = {rules.ident(row.as_dict()): row.as_dict() for row in sheet.rows}
        for row in collection:
            key = (row["after"]["set_code"], row["after"]["collector_number"], row["after"]["finish"])
            if key not in rows:
                raise ValueError("A collection row is missing")
            if row["op"] == "INSERT":
                del rows[key]
            else:
                rows[key] = _collection_cells(row["before"])
        after = after.with_collection(space, list(rows.values()))
    tokens = [row for row in raw if row["table"] == TOKENS and _restores(row)]
    if tokens:
        sheet = snapshot.token_set(space)
        by_id = {row["key"]["id"]: row for row in tokens}
        kept = []
        for stored in sheet.rows:
            row = by_id.pop(stored.id, None)
            if row is None:
                kept.append(stored)
            elif row["op"] == "UPDATE":
                kept.append(TokenRow.make(_token_cells(row["before"]), id=stored.id))
        if by_id:
            raise ValueError("A token row is missing")
        after = after.with_tokens(space, kept)
    statuses = {row["key"]["file"]: row["before"] for row in raw if row["table"] == STATUS}
    if statuses:
        sheet = snapshot.status
        if not sheet.exists or sheet.error is not None or sheet.strict_error is not None:
            raise ValueError("The product status list can't be read")
        rows = []
        for stored in sheet.rows:
            values = {field: stored.text(field) for field in rules.STATUS_FIELDS}
            before = statuses.pop(values["file"], None)
            if before is not None:
                values.update({field: before[field] for field in STATUS_CHANGES})
            rows.append(values)
        if statuses:
            raise ValueError("A product status row is missing")
        after = after.with_status_rows(rows)
    for row in raw:
        if row["table"] == COMPONENT:
            after = _restore_component(after, row["before"])
    return after


def _verify(snapshot, settled, raw):
    """The tables the database would hold: each restored row back as it was, nothing else changed."""
    from .table_rows import tables
    before_t, after_t = tables(snapshot), tables(settled)
    before_images, after_images = _images(before_t), _images(after_t)
    restored = {table: {} for table in RESTORED_TABLES}
    for row in raw:
        if row["table"] in restored and _restores(row):
            restored[row["table"]][_canon(row["table"], row["after"])] = row
    for table in RESTORED_TABLES:
        keys = set(before_images[table]) | set(after_images[table])
        for key in keys:
            row = restored[table].get(key)
            found = after_images[table].get(key)
            if row is None:
                if found != before_images[table].get(key):
                    raise ValueError(f"{table} changed outside the undone rows")
            elif row["op"] == "INSERT":
                if found is not None:
                    raise ValueError("An added row is still there")
            elif not _same(row["before"], found):
                raise ValueError("A row wasn't put back exactly")
    for table in KEPT_TABLES:
        if before_t[table] != after_t[table]:
            raise ValueError(f"{table} changed")
    if settled.imports != snapshot.imports or settled.decks != snapshot.decks \
            or settled.accessories != snapshot.accessories or settled.accessory_images != snapshot.accessory_images:
        raise ValueError("Other data changed")


# ------------------------------------------------------------------ physical copies

def _reverted_products(raw):
    return {row["key"]["file"].removesuffix(".csv") for row in raw if row["table"] == STATUS}


def _collection_proof(snapshot, after, space, raw, label):
    """Removed copies aren't held by built decks or intact products (other than a product this
    receipt set owned and Undo puts back on order). A printing the change added is refused when
    any other holder uses that card at all, since it may have taken those very copies."""
    from decklab.lib import decks, inventory, pool
    from decklab.lib.api.collection_guards import _check_holders, _physical_counts
    from decklab.lib.decks import assembled, standins
    rows = [row for row in raw if row["table"] == COLLECTION]
    if not rows:
        return
    reverted = _reverted_products(raw)
    try:
        unresolved = {}
        names = {row["after"]["name"]: pool._canonical(row["after"]["name"], "Undo", unresolved) for row in rows}
        if unresolved:
            raise ValueError("Unresolved card names")
    except Exception:
        raise UndoConflict("The cards' physical identities cannot be checked. Use the Collection editor.", label) from None
    basics = sorted(name for name in names.values() if decks.is_basic_land(name))
    if basics:
        raise UndoUnsupported("Use the Collection editor to remove tracked basic lands (" + ", ".join(basics) + ").")
    try:
        for deck in _known_decks(snapshot, space):
            if deck.status != "built":
                continue
            if sum(field.key.casefold() == standins.STAND_INS_FIELD.casefold() for field in deck.header) > 1:
                raise ValueError("Ambiguous installed markers")
            installed = standins.installed_for(deck)
            if installed:
                if installed["version"] != assembled.version(deck) or any(item["using"] is None for item in installed["cards"]):
                    raise ValueError("Unknown physical markers")
                standins.validate_rows(installed["cards"], assembled.sections(deck))
        with inventory.pinned(snapshot):
            held = pool.load_pool(space)
            _check_holders(snapshot, space, held)
        if held.unresolved or held.warning_decks or any(holder.standin_warnings for holder in held.in_use):
            raise ValueError("Uncertain physical holders")
        old, new = _physical_counts(snapshot, space), _physical_counts(after, space)
    except Exception:
        raise UndoConflict("Cards held by built decks or intact products cannot be checked. Use the Collection editor.",
                           label) from None
    others = [holder for holder in held.in_use
              if not (holder.id.startswith("product/") and holder.id.split("/")[1] in reverted)]
    for row in rows:
        name = names[row["after"]["name"]]
        if row["op"] == "INSERT" and any(holder.cards[name] > 0 for holder in others):
            raise UndoConflict("This card is used by a built deck or intact product, which may hold these copies. "
                               "Use the Collection editor.", _row_label(row))
    for name, quantity in old.items():
        if new[name] < quantity:
            in_use = sum(holder.cards[name] for holder in others)
            if new[name] < in_use:
                raise UndoConflict(f"Undo would leave fewer copies of {name} than built decks or intact products hold. "
                                   "Nothing was undone.", label)


def _token_proof(snapshot, after, raw, label):
    """Token cards the receipt added aren't packed in a built deck or intact product."""
    from decklab.lib import decks, inventory, tokens
    from decklab.lib.tokens import ops as token_ops
    touched = {row["key"]["id"] for row in raw if row["table"] == TOKENS and _restores(row)}
    if not touched:
        return
    reverted = _reverted_products(raw)
    try:
        from .undo import _home_products
        intact = _home_products(snapshot, HOME) - reverted
        with inventory.pinned(snapshot):
            for deck in _known_decks(snapshot, HOME):
                if deck.status == "built" and not decks.has_token_cards(deck):
                    raise ValueError("Unknown packed tokens")
            warnings = []
            from decklab.lib.tokens import products
            records = products.records(warnings, snapshot)
            if {f"product/{stem}" for stem in intact} - records.keys() or any(record["error"] for record in records.values()) \
                    or any(not record["written"] for key, record in records.items() if key.split("/", 1)[1] in intact):
                raise ValueError("Unknown product packing")
            before_tokens = tokens.read(space=HOME)
            before_holds = tokens.reserve.holds(before_tokens, space=HOME, warnings=warnings)
            stored_rows = snapshot.token_set(HOME).rows
            if len(stored_rows) != len(before_tokens.rows) or any(
                    token_ops.match_key(a.as_dict()) != token_ops.match_key(b) for a, b in zip(stored_rows, before_tokens.rows)):
                raise ValueError("Ambiguous packed token rows")
            remaining = {row.id: row.qty for row in after.token_set(HOME).rows}
            for index, row in enumerate(stored_rows):
                if row.id in touched:
                    held = sum(holder["rows"].get(index, 0) for holder_id, holder in before_holds.items()
                               if holder_id.split("/", 1)[-1] not in reverted or not holder_id.startswith("product/"))
                    if held > remaining.get(row.id, 0):
                        raise ValueError("Packed copies would be removed")
            if any(holder.get("error") or holder.get("unmatched") for holder in before_holds.values()):
                raise ValueError("Unknown packed tokens")
        with inventory.pinned(after):
            inv = tokens.read(space=HOME)
            holds = tokens.reserve.holds(inv, space=HOME, warnings=warnings)
        quantities = [int(row["quantity"]) for row in inv.rows]
        held = {}
        for holder in holds.values():
            if holder.get("error") or holder.get("unmatched"):
                raise ValueError("Unknown packed tokens")
            for index, quantity in holder["rows"].items():
                held[index] = held.get(index, 0) + quantity
        if warnings or any(quantity > quantities[index] for index, quantity in held.items()):
            raise ValueError("Packed tokens exceed the remaining cards")
    except Exception:
        raise UndoConflict("Packed token cards cannot safely be removed here. Use the Tokens page.", label) from None


# ------------------------------------------------------------------ review and apply

def _latest(store, raw):
    """Every restored row must still be the latest audit row for its key."""
    keyed = [row for row in raw if row["table"] in (COLLECTION, TOKENS, COMPONENT, STATUS)]
    found = store.undo_latest_rows([(row["table"], row["key"]) for row in keyed])
    if not isinstance(found, dict):
        raise UndoMissing()
    for row in keyed:
        if found.get((row["table"], json.dumps(row["key"], sort_keys=True))) != row["id"]:
            raise UndoConflict("This was changed after the selected change. Nothing was undone.", _row_label(row))


def _current(snapshot, raw, space):
    from .table_rows import Unrepresentable, tables
    try:
        images = _images(tables(snapshot))
    except Unrepresentable:
        raise UndoConflict("The current inventory cannot be checked. Reload and try again.") from None
    for row in raw:
        if row["table"] in images and not _same(row["after"], images[row["table"]].get(_canon(row["table"], row["after"]))):
            raise UndoConflict(CHECKED, _row_label(row))
        if row["table"] == RAW_IMPORT:
            kept = [info for info in snapshot.imports.get(space, ()) if info.name == row["after"]["file_name"]]
            if len(kept) != 1 or kept[0].size != row["after"]["size"] \
                    or kept[0].sha256 is not None and kept[0].sha256 != row["after"]["sha256"]:
                raise UndoConflict("The kept upload changed after the selected change. Nothing was undone.", _row_label(row))


def _describe(raw, kind, space):
    """What the preview shows: every row put back, with its current and restored values."""
    def cards(image):
        values = _collection_cells(image)
        values["quantity"] = int(values["quantity"])
        return values

    def token(image):
        values = _token_cells(image)
        values["quantity"] = int(values["quantity"])
        return values
    collection = {"removed": [], "reduced": []}
    tokens = {"removed": [], "reduced": []}
    components, products, uploads = [], [], []
    for row in raw:
        table, after, before = row["table"], row["after"], row["before"]
        if table == COLLECTION:
            if row["op"] == "INSERT":
                collection["removed"].append(cards(after))
            else:
                collection["reduced"].append({"current": cards(after), "restored": cards(before)})
        elif table == TOKENS and _restores(row):
            if row["op"] == "INSERT":
                tokens["removed"].append(token(after))
            else:
                tokens["reduced"].append({"current": token(after), "restored": token(before)})
        elif table == COMPONENT:
            components.append({"position": after.get("position", 0), "order": after["order_id"], "component": after["id"], "kind": after["kind"],
                               "received_on": after["received_on"], "checks": list(before["checks"])})
        elif table == STATUS:
            products.append({"product": after["file"].removesuffix(".csv"), "status": before["status"],
                             "intact": after["intact"]})
        elif table == RAW_IMPORT:
            uploads.append(after["file_name"])
    components.sort(key=lambda item: (item["order"], item.pop("position")))
    removed = sum(item["quantity"] for item in collection["removed"]) \
        + sum(item["current"]["quantity"] - item["restored"]["quantity"] for item in collection["reduced"])
    if kind == IMPORT:
        new, bumped = len(collection["removed"]), len(collection["reduced"])
        parts = [f"{new} new {'row' if new == 1 else 'rows'}"] if new else []
        parts += [f"{bumped} {'row' if bumped == 1 else 'rows'} added to"] if bumped else []
        label = f"Import of {removed} {'card' if removed == 1 else 'cards'} ({', '.join(parts)})"
    else:
        orders = sorted({item["order"] for item in components})
        label = f"Receipt of order {', '.join(orders)} ({', '.join(item['component'] for item in components)})"
    return {"label": label, "cards": removed, "collection": collection, "tokens": tokens,
            "components": components, "products": products, "uploads": uploads}


def _plan(change_id, space, snapshot, store):
    _identifier(change_id)
    reader = getattr(store, "undo_audit_rows", None)
    if not callable(reader) or not callable(getattr(store, "undo_latest_rows", None)):
        raise UndoUnsupported("Undo is available only with the database audit trail.")
    raw = reader(change_id)
    kind = _source(raw, space)
    described = _describe(raw, kind, space)
    label = described["label"]
    _latest(store, raw)
    _current(snapshot, raw, space)
    from . import changes
    try:
        settled = changes.prepare(snapshot, _inverse(snapshot, raw, space))
        _verify(snapshot, settled, raw)
    except Exception:
        raise UndoConflict("The complete change cannot be put back exactly. Nothing was saved.", label) from None
    _collection_proof(snapshot, settled, space, raw, label)
    if kind == RECEIPT:
        _token_proof(snapshot, settled, raw, label)
    receipt = json.dumps([change_id, raw, snapshot.revision, snapshot.decks_revision], ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    plan = {"change_id": change_id, "kind": "mixed", "space": space, "action": kind, "reason_required": True,
            "row_count": len(raw), "row_change_ids": [row["id"] for row in raw],
            "expect": hashlib.sha256(receipt.encode("utf-8")).hexdigest(), **described}
    return plan, settled


def review(change_id, space, snapshot=None):
    """The preview of undoing a whole import or receipt in space, or a guarded refusal."""
    import re
    if not isinstance(space, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", space):
        raise UndoMissing()
    snapshot = current() if snapshot is None else snapshot
    return _plan(change_id, space, snapshot, backend())[0]


def removed_state(snapshot, plan):
    """After a save: every removed row gone and every reduced row back, read from snapshot."""
    space = plan["space"]
    sheet = snapshot.collection(space)
    rows = {rules.ident(row.as_dict()): row.as_dict() for row in sheet.rows} if sheet.exists else {}
    for item in plan["collection"]["removed"]:
        if rules.ident(_collection_cells({"set_code" if k == "set" else k: v for k, v in item.items()})) in rows:
            raise UndoConflict("The removed rows cannot be confirmed. Reload the collection.", plan["label"])
    for item in plan["collection"]["reduced"]:
        restored = item["restored"]
        found = rows.get(rules.ident({**restored, "quantity": str(restored["quantity"])}))
        if found is None or {**found, "quantity": int(found["quantity"])} != restored:
            raise UndoConflict("The restored rows cannot be confirmed. Reload the collection.", plan["label"])
    for item in plan["components"]:
        order = snapshot.order(item["order"])
        parts = [c for c in (order.components if order is not None and order.error is None else ())
                 if c.id == item["component"]]
        if len(parts) != 1 or parts[0].status != "pending" or parts[0].received_on != "":
            raise UndoConflict("The order parts cannot be confirmed back on order. Reload Shopping.", plan["label"])
    for item in plan["products"]:
        rows_ = [row for row in snapshot.status.rows if row.text("file") == item["product"] + ".csv"]
        if len(rows_) != 1 or rows_[0].text("status") != item["status"] or rows_[0].text("intact") != "":
            raise UndoConflict("The products cannot be confirmed back on order. Reload Shopping.", plan["label"])
    return {"removed_rows": len(plan["collection"]["removed"]), "restored_rows": len(plan["collection"]["reduced"]),
            "components": len(plan["components"]), "products": len(plan["products"])}


@register("inventory.undo_mixed", refresh=True)
def apply_mixed(snapshot, *, change_id, space, expect, reason=None):
    """Called inside the backend's write lock; the source and latest audit share its connection."""
    if not isinstance(expect, str) or not SHA.fullmatch(expect):
        raise UndoMissing()
    try:
        reason = removal_reason(reason)
    except Invalid:
        raise Invalid("Give a nonblank reason of at most 200 characters for undoing this change.") from None
    plan, settled = _plan(change_id, space, snapshot, backend())
    if plan["expect"] != expect:
        raise UndoConflict("The inventory or decks changed after the Undo preview. Review it again.", plan["label"])
    tokens = plan["tokens"]
    counts = {"undo": 1, "cards": plan["cards"], "removed": len(plan["collection"]["removed"]),
              "edited": len(plan["collection"]["reduced"]), "token_rows": len(tokens["removed"]) + len(tokens["reduced"]),
              "components": len(plan["components"]), "products": len(plan["products"])}
    changed = {paths.collection(space): ["undo"]} if plan["collection"]["removed"] or plan["collection"]["reduced"] else {}
    return settled, Summary(f"Undo change #{change_id}: {plan['label']}", counts, changed,
                            {"undo_of": change_id, "space": space, "kind": "mixed", "action": plan["action"],
                             "row_count": plan["row_count"], "row_change_ids": plan["row_change_ids"],
                             "undo_reason": reason})
