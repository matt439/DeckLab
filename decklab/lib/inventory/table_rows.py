"""A snapshot as the rows migration 0004's tables hold, and what about a snapshot the database
can't hold: shared by both backends, so they refuse the same things (the phase 3 design's
amendments Q1-Q6; the foundation review's item 3).

    rows = tables(inv)                  # {table: rows}, or Unrepresentable listing every reason
    found = reasons(inv)                # {source path: [why the database can't hold it]}
    why = representable(inv)            # [...]: also what it would give back differently

The database backend writes tables() and the import writes tables(strict=True). The files
backend never writes rows, but it refuses an operation's result for the same reasons the
database would (changes.check), so an operation can't save on one backend what the other would
refuse: a quantity that isn't a whole number of at least 1, a cell a row lacks, a payload no
record names, a record that isn't the records' shape.

Phase 4's deck parts (decks, accessories.csv, its pictures) map to their own rows (the
phase 4 design's D3 with amendments R1-R5: migration 0006): deck {id: (space_id, kind, slug)}
with deck_text {id: text} (the stored text; the database derives title, status and played_by
from it when it writes, and numbers its revisions), accessory {id: ACCESSORY_COLUMNS} ("" for a
cell an older header lacks; no position: the file's order is always rules.accessory_sort_key's)
and accessory_image {file name: (size, sha256)} (the bytes are written from the operation's
ImageMeta). Both backends refuse what those can't hold: a deck file or accessories.csv that
can't be read, a NUL in a deck's text, an accessories row with more cells than the header or a
column accessories.csv doesn't have, an id there twice. strict (the import's) also refuses a
deck text with a carriage return (the database keeps LF text: git's blobs are LF, and the files
backend's CRLF working-tree copies aren't imported), a deck file name that isn't a valid slug,
and an accessories.csv whose header isn't ACCESSORY_FIELDS, whose rows aren't in its order, or
which has rows its lenient read leaves out or no rows at all (the database
can't tell a header-only file from a missing one).

Nothing here touches a database (or imports psycopg).
"""
import dataclasses
import json

from . import dice_rules, paths, rules
from .model import QUEUE_FIELDS, Component, Order

CARD_COLUMNS = ("name", "set_code", "collector_number", "finish", "quantity", "condition", "language", "notes")
TOKEN_COLUMNS = ("front", "back", "set_code", "front_collector_number", "back_collector_number", "finish",
                 "quantity", "front_details", "back_details", "notes")
# dice_counter's (migration 0020, E7-S24), in dice.csv's column order.
DICE_COLUMNS = ("item_type", "die_size", "counter_kind", "design", "quantity", "notes")
WATCH_COLUMNS = ("name", "set_code", "collector_number", "finish", "quantity", "for_deck", "printing",
                 "listed_aud", "listed_at", "in_stock", "checked", "notes", "state", "source")
STATUS_COLUMNS = ("position", "status", "intact", "sleeves", "deck_box", "notes", "token_cards")
ORDER_COLUMNS = ("seller", "ordered_on", "sources", "notes", "audit_notes")
COMPONENT_COLUMNS = ("position", "kind", "file_name", "status", "received_on", "checks", "verified_checks",
                     "product_stem", "check_links")
ITEM_TABLES = {"cards": "order_card_item", "tokens": "order_token_item"}
ITEM_COLUMNS = {"order_card_item": CARD_COLUMNS, "order_token_item": TOKEN_COLUMNS}
PAYLOAD_FIELDS = {"cards": tuple(rules.FIELDS), "tokens": tuple(rules.TOKEN_FIELDS)}
ACCESSORY_COLUMNS = tuple(rules.ACCESSORY_FIELDS[1:])        # after the id
DECK_TABLES = ("deck", "deck_text", "accessory", "accessory_image")


@dataclasses.dataclass(frozen=True)
class JsonColumn:
    value: object


class Unrepresentable(ValueError):
    """A snapshot the database can't hold (exactly, for write_model): reasons lists why, each
    naming the file and line it's about."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        more = f" (and {len(self.reasons) - 10} more)" if len(self.reasons) > 10 else ""
        super().__init__("the database can't hold this inventory: " + "; ".join(self.reasons[:10]) + more)


def _where(path, row):
    return f"{path} line {row.line}" if getattr(row, "line", 0) else path


def _cells(row, columns, where, bad):
    """The row's text for columns, in order, or None (with a reason) when a cell is missing or
    the row has cells past its header."""
    if row.overflow:
        bad(f"{where}: the row has more cells than the header")
        return None
    out = []
    for column in columns:
        value = row.get(column)
        if value is None:
            bad(f"{where}: the row has no {column} cell")
            return None
        out.append(value)
    return out


def _qty(text, where, strict, bad):
    """A quantity's int, or None (with a reason) when it isn't a whole number of at least 1, or
    (strict) isn't written as the database would write it back."""
    try:
        number = int(text)
    except (TypeError, ValueError):
        number = None
    if number is None or number < 1:
        bad(f"{where}: quantity {text!r} isn't a whole number of at least 1")
        return None
    if strict and str(number) != text:
        bad(f"{where}: quantity {text!r} wouldn't come back as written (it would be {number})")
        return None
    return number


def _strings(value):
    return isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value)


class _Reasons:
    """Collects (source path, why) pairs; about(path) is a one-argument reporter for one source."""

    def __init__(self):
        self.found = []

    def about(self, path):
        return lambda text: self.found.append((path, text))


def _order_rows(order, inv, out, claimed, reasons, strict):
    """An order record's purchase_order, order_component and item rows into out."""
    where = order.path
    bad = reasons.about(where)
    if order.error is not None:
        bad(f"{where} can't be read: {order.error}")
        return
    d = order.data
    if not isinstance(d, dict) or d.get("version") != 1 or type(d.get("version")) is not int:
        bad(f"{where}: not an order record of version 1")
        return
    oid = d.get("id")
    if not isinstance(oid, str) or order.file != f"{oid}.json":
        bad(f"{where}: its id doesn't match its file name")
        return
    texts = [d.get(k) for k in ("seller", "ordered_on", "notes")]
    if not all(isinstance(v, str) for v in texts) or not _strings(d.get("sources")) \
            or not isinstance(d.get("audit_notes", ""), str) or not isinstance(d.get("components"), list):
        bad(f"{where}: a field isn't the text or list the database keeps")
        return
    components = []
    for position, data in enumerate(d["components"]):
        c = Component(data) if isinstance(data, dict) else None
        if c is None or not all(isinstance(c.data.get(k), str) for k in ("id", "kind", "path", "status",
                                                                            "received_on")) \
                or not _strings(c.checks) or ("verified_checks" in c.data and not _strings(c.verified_checks)):
            bad(f"{where}: component {position + 1} isn't the shape the database keeps")
            return
        if c.kind not in paths.KINDS or c.status not in paths.STATUSES:
            bad(f"{where}: {c.id} has kind {c.kind!r} and status {c.status!r}")
            return
        if c.path != paths.payload(c.kind, c.status, c.file_name):
            bad(f"{where}: {c.id}'s file {c.path} isn't where its kind and status put it")
            return
        components.append((position, c))
    rebuilt = Order.build(oid, d["seller"], d["ordered_on"], d["sources"], d["notes"],
                          [Component.build(c.id, c.kind, c.file_name, c.status, c.received_on, c.checks,
                                           c.verified_checks, c.check_links) for _, c in components],
                          d.get("audit_notes"))
    if strict and rules.json_bytes(rebuilt.data) != rules.json_bytes(d):
        bad(f"{where}: its keys aren't the records' (version, id, seller, ordered_on, sources, notes, "
            f"components[, audit_notes]; a component's id, kind, path, status, received_on, checks"
            f"[, verified_checks]), or not in that order")
        return
    out["purchase_order"][oid] = (d["seller"], d["ordered_on"], tuple(d["sources"]), d["notes"],
                                  d.get("audit_notes"))
    for position, c in components:
        key = (oid, c.id)
        if key in out["order_component"]:
            bad(f"{where}: component {c.id} is there twice")
            continue
        stem = c.product_stem
        if c.kind == "product" and inv.product(stem) is None:
            bad(f"{where}: {c.id} names {c.path}, which isn't a product file")
            continue
        if c.path in claimed:
            bad(f"{where}: {c.id}'s file {c.path} is another component's too")
            continue
        claimed.add(c.path)
        verified = tuple(c.verified_checks) if c.verified_checks is not None else None
        metadata = c.check_links
        if metadata is not None:
            try:
                if len(json.dumps(metadata, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 262144:
                    raise ValueError("Too much arrival-check metadata")
            except (TypeError, ValueError, RecursionError):
                bad(f"{where}: arrival-check metadata isn't bounded JSON")
                continue
        out["order_component"][key] = (position, c.kind, c.file_name, c.status, c.received_on, tuple(c.checks),
                                       verified, stem, JsonColumn(metadata) if metadata is not None else None)
        if c.kind == "product":
            continue
        sheet = inv.payloads.get(c.path)
        if sheet is None:
            bad(f"{where}: {c.id}'s file {c.path} isn't there")
            continue
        about = reasons.about(c.path)
        if sheet.error is not None:
            about(f"{c.path} can't be read: {sheet.error}")
            continue
        fields = PAYLOAD_FIELDS[c.kind]
        if sheet.columns != fields:
            about(f"{c.path}: its header isn't {','.join(fields)}")
            continue
        rows = []
        for row in sheet.rows:
            at = _where(c.path, row)
            cells = _cells(row, fields, at, about)
            if cells is None:
                continue
            q = fields.index("quantity")
            qty = _qty(cells[q], at, strict, about)
            if qty is None:
                continue
            cells[q] = qty
            rows.append(tuple(cells))
        out[ITEM_TABLES[c.kind]][key] = tuple(rows)


def _collect(inv, strict):
    """(tables' rows, _Reasons) for inv; see tables()."""
    reasons = _Reasons()
    out = {"collection_card": {}, "token_card": [], "watchlist_item": [], "product": {}, "product_item": {},
           "product_status": {}, "purchase_order": {}, "order_component": {}, "order_card_item": {},
           "order_token_item": {}, "dice_counter": []}
    for space, sheet in inv.collections.items():
        bad = reasons.about(sheet.path)
        try:
            paths.space_root(space)
        except ValueError as e:
            bad(str(e))
            continue
        if sheet.error is not None:
            bad(f"{sheet.path} can't be read: {sheet.error}")
            continue
        if strict and sheet.exists:
            if sheet.columns != tuple(rules.FIELDS):
                bad(f"{sheet.path}: its header isn't collection.csv's")
            if sheet.strict_error:
                bad(sheet.strict_error)
            if not sheet.rows:
                bad(f"{sheet.path} has no cards (a space with none has no file)")
            dicts = [row.as_dict() for row in sheet.rows]
            try:
                if dicts != sorted(dicts, key=rules.sort_key):
                    bad(f"{sheet.path} isn't in set and collector number order (merge_cards.sort_key)")
            except (KeyError, TypeError):
                pass                                # its cells are reported below
        for row in sheet.rows:
            at = _where(sheet.path, row)
            cells = _cells(row, rules.FIELDS, at, bad)
            if cells is None:
                continue
            qty = _qty(cells[4], at, strict, bad)
            if qty is None:
                continue
            key = (space, cells[1], cells[2], cells[3])
            if key in out["collection_card"]:
                bad(f"{at}: {cells[1]} {cells[2]} {cells[3]} is there twice")
                continue
            out["collection_card"][key] = (cells[0], qty, cells[5], cells[6], cells[7], "")
    _location_rows(inv, out, reasons, strict)
    for space, sheet in inv.tokens.items():
        bad = reasons.about(sheet.path)
        try:
            paths.space_root(space)
        except ValueError as e:
            bad(str(e))
            continue
        if sheet.error is not None:
            bad(f"{sheet.path} can't be read: {sheet.error}")
            continue
        if strict and sheet.exists:
            if sheet.columns != tuple(rules.TOKEN_FIELDS):
                bad(f"{sheet.path}: its header isn't tokens.csv's")
            for problem in sheet.problems:
                bad(f"{sheet.path}: a row the Tokens page leaves out ({problem})")
            if not sheet.rows and not sheet.problems:
                bad(f"{sheet.path} has no cards (a space with none has no file)")
        for row in sheet.rows:
            at = _where(sheet.path, row)
            cells = _cells(row, rules.TOKEN_FIELDS, at, bad) if strict else \
                [row.text(column) for column in rules.TOKEN_FIELDS]
            if cells is None:
                continue
            qty = _qty(cells[6], at, strict, bad)
            if qty is None:
                continue
            cells[6] = qty
            out["token_card"].append((row.id, space, *cells))
    _dice_rows(inv, out, reasons, strict)
    status = inv.status
    bad = reasons.about(status.path)
    if status.error is not None:
        bad(f"{status.path} can't be read: {status.error}")
    else:
        if strict and not status.exists:
            bad(f"{status.path} is missing (the database always has a status list)")
        if strict and status.exists and status.columns != tuple(rules.STATUS_FIELDS):
            bad(f"{status.path}: its header isn't {','.join(rules.STATUS_FIELDS)}")
        for position, row in enumerate(status.rows):
            at = _where(status.path, row)
            if strict:
                cells = _cells(row, rules.STATUS_FIELDS, at, bad)
            elif row.overflow or any(row.get(c) is None for c in ("file", "status", "intact", "notes")):
                cells = _cells(row, rules.STATUS_FIELDS, at, bad)
            else:
                cells = [row.text(column) for column in rules.STATUS_FIELDS]
            if cells is None:
                continue
            if cells[0] in out["product_status"]:
                bad(f"{at}: {cells[0]} has two status rows")
                continue
            out["product_status"][cells[0]] = (position, *cells[1:])
    watch = inv.watchlist
    bad = reasons.about(watch.path)
    if watch.error is not None:
        bad(f"{watch.path} can't be read: {watch.error}")
    else:
        if strict and not watch.exists:
            bad(f"{watch.path} is missing (the database always has a watchlist)")
        if strict and watch.exists and watch.columns != QUEUE_FIELDS:
            bad(f"{watch.path}: its header isn't {','.join(QUEUE_FIELDS)}")
        for row in watch.rows:
            at = _where(watch.path, row)
            cells = _cells(row, QUEUE_FIELDS, at, bad)
            if cells is None:
                continue
            qty = _qty(cells[4], at, strict, bad)
            if qty is None:
                continue
            cells[4] = qty
            out["watchlist_item"].append((row.id, *cells))
    for product in inv.products:
        bad = reasons.about(product.path)
        if product.error is not None:
            bad(f"{product.path} can't be read: {product.error}")
            continue
        if product.columns is None:
            bad(f"{product.path} is empty (a product needs at least its header)")
            continue
        items = []
        for item in product.items:
            cells = _cells(item, (), _where(product.path, item), bad)   # overflow only
            if cells is None:
                continue
            values = [value for _, value in item.values]
            if None in values or item.columns() != product.columns:
                bad(f"{_where(product.path, item)}: the row doesn't have a cell for every column")
                continue
            items.append(tuple(values))
        out["product"][product.stem] = (product.name, product.format, tuple(product.columns))
        out["product_item"][product.stem] = tuple(items)
    claimed = set()
    for order in inv.orders:
        _order_rows(order, inv, out, claimed, reasons, strict)
    for path in inv.payloads:
        if path not in claimed:
            reasons.about(path)(f"{path}: no order record names it")
    _deck_rows(inv, out, reasons, strict)
    return out, reasons


def _dice_rows(inv, out, reasons, strict):
    """Each space's dice and counters (dice.csv, E7-S24) into dice_counter's rows (id, space,
    *DICE_COLUMNS), quantity an int, with every reason the database can't hold one: a file that
    can't be read, a row dice_rules refuses (the table's checks would), the wrong header."""
    for space, sheet in inv.dice.items():
        bad = reasons.about(sheet.path)
        try:
            paths.space_root(space)
        except ValueError as e:
            bad(str(e))
            continue
        if sheet.error is not None:
            bad(f"{sheet.path} can't be read: {sheet.error}")
            continue
        for problem in sheet.problems:
            bad(problem)
        if sheet.strict_error and sheet.strict_error not in sheet.problems:
            bad(sheet.strict_error)
        if strict and sheet.exists and not sheet.rows and not sheet.problems:
            bad(f"{sheet.path} has no rows (a space with none has no file)")
        if sheet.problems:
            continue
        for row in sheet.rows:
            cells = [row.text(column) for column in dice_rules.DICE_FIELDS]
            cells[4] = int(cells[4])
            out["dice_counter"].append((row.id, space, *cells))


def _location_rows(inv, out, reasons, strict):
    """Each space's storage locations (locations.csv, E8-S22) into its collection_card rows'
    location (the database's column, migration 0016), with every reason the database can't hold
    one: a file that can't be read, a row the strict read refuses, a location for a printing the
    collection doesn't have."""
    for space, sheet in inv.locations.items():
        bad = reasons.about(sheet.path)
        if sheet.error is not None:
            bad(f"{sheet.path} can't be read: {sheet.error}")
            continue
        if strict and sheet.exists and not sheet.rows and not sheet.problems:
            bad(f"{sheet.path} has no locations (a space with none has no file)")
        for problem in sheet.problems:
            bad(problem)
        if sheet.strict_error and sheet.strict_error not in sheet.problems:
            bad(sheet.strict_error)
        for row in sheet.rows:
            key = (space, *row.key)
            found = out["collection_card"].get(key)
            if found is None:
                bad(f"{_where(sheet.path, row)}: {' '.join(row.key)} isn't in the collection")
                continue
            if not found[5]:
                out["collection_card"][key] = (*found[:5], row.text("location"))


def _deck_rows(inv, out, reasons, strict):
    """The deck parts' rows into out (deck, deck_text, accessory, accessory_image), with every
    reason the database can't hold them (see the module docstring)."""
    from decklab.lib.decks import valid_slug
    out.update({table: {} for table in DECK_TABLES})
    for deck_id, deck in inv.decks.items():
        bad = reasons.about(deck.path)
        try:
            paths.space_root(deck.space)
        except ValueError as e:
            bad(str(e))
            continue
        if deck.error is not None:
            bad(f"{deck.path} can't be read: {deck.error}")
            continue
        if "\0" in deck.text:
            bad(f"{deck.path} holds a NUL character")
            continue
        if strict and "\r" in deck.text:
            bad(f"{deck.path} has carriage returns (the database keeps the LF text git holds)")
        if strict and not valid_slug(deck.slug):
            bad(f"{deck.path}: {deck.slug!r} isn't a valid deck slug")
        out["deck"][deck_id] = (deck.space, deck.kind, deck.slug)
        out["deck_text"][deck_id] = deck.text
    sheet = inv.accessories
    bad = reasons.about(sheet.path)
    if sheet.error is not None:
        bad(f"{sheet.path} can't be read: {sheet.error}")
    elif sheet.exists:
        columns = sheet.columns or ()
        unknown = [c for c in columns if c not in rules.ACCESSORY_FIELDS]
        if unknown or len(set(columns)) != len(columns):
            bad(f"{sheet.path}: its header has columns accessories.csv doesn't ({', '.join(unknown) or 'twice'})")
        else:
            if strict and columns != tuple(rules.ACCESSORY_FIELDS):
                bad(f"{sheet.path}: its header isn't {','.join(rules.ACCESSORY_FIELDS)}")
            if strict and sheet.strict_error:
                bad(sheet.strict_error)
            if strict:
                for problem in sheet.problems:
                    bad(f"{sheet.path}: a row the Accessories page leaves out ({problem})")
                if not sheet.rows:
                    bad(f"{sheet.path} has no rows (the database can't tell it from a missing file)")
                dicts = [row.as_dict() for row in sheet.rows]
                if dicts != sorted(dicts, key=rules.accessory_sort_key):
                    bad(f"{sheet.path} isn't in kind and id order")
            for row in sheet.rows:
                at = _where(sheet.path, row)
                if row.overflow:
                    bad(f"{at}: the row has more cells than the header")
                    continue
                if any(value is None for _, value in row.values):
                    bad(f"{at}: the row has no cell for every column")
                    continue
                key = row.text("id")
                if key in out["accessory"]:
                    bad(f"{at}: the id {key} is there twice")
                    continue
                out["accessory"][key] = tuple(row.text(column) for column in ACCESSORY_COLUMNS)
    for name, meta in inv.accessory_images.items():
        out["accessory_image"][name] = (meta.size, meta.sha256)


def deck_tables(inv, strict=False):
    """(the deck parts' rows: tables()' deck, deck_text, accessory and accessory_image, [every
    reason the database can't hold them]) of inv, whatever its inventory holds: what the decks'
    import writes (pg.write_decks)."""
    reasons = _Reasons()
    out = {}
    _deck_rows(inv, out, reasons, strict)
    return out, [text for _, text in reasons.found]


def tables(inv, strict=False):
    """The rows migration 0004's tables hold for inv, as {table: rows}:

        collection_card   {(space, set, number, finish): (name, quantity, condition, language, notes,
                          location)}  (location: "" unless locations.csv gives one, E8-S22)
        dice_counter      [(id, space, *DICE_COLUMNS)] in file order (E7-S24; as token_card)
        token_card        [(id, space, *TOKEN_COLUMNS)] in file order   (id 0: a row the database
                          hasn't seen; positions are worked out when written, see pg._positions)
        watchlist_item    [(id, *WATCH_COLUMNS)] in file order
        product           {stem: (name, format, columns)};  product_item {stem: (cells, ...)}
        product_status    {file: (position, status, intact, sleeves, deck_box, notes)}
        purchase_order    {id: ORDER_COLUMNS};  order_component {(order, id): COMPONENT_COLUMNS}
        order_card_item / order_token_item   {(order, component): (row, ...)}
        deck {id: (space_id, kind, slug)};  deck_text {id: text}
        accessory {id: ACCESSORY_COLUMNS};  accessory_image {file name: (size, sha256)}

    Raises Unrepresentable with every reason the database can't hold it: a source that can't be
    read, a missing cell, a quantity that isn't a whole number of at least 1, a payload no record
    names, a component whose file isn't there, a record that isn't the records' shape. strict
    (write_model's) also refuses what the database would hold differently, so a load would give a
    different snapshot: see representable()."""
    out, found = _collect(inv, strict)
    if found.found:
        raise Unrepresentable(text for _, text in found.found)
    return out


def reasons(inv, strict=False):
    """{source path: [why]} of what tables() would refuse in inv, by the source each reason is
    about (a payload's own rows by the payload's path, a record's shape by the record's); {}
    when the database can hold it."""
    out = {}
    for path, text in _collect(inv, strict)[1].found:
        out.setdefault(path, []).append(text)
    return out


def representable(inv):
    """Why the database can't hold inv exactly (so that loading it back gives the same
    snapshot), as a list of reasons; [] when it can. Besides tables()' reasons: a source a
    canonical write wouldn't give back the same (a BOM, CRLF, odd quoting, a legacy status.csv
    header), a collection out of sort_key order, a collection or tokens file with no cards, a
    missing status.csv or watchlist.csv, and a record whose keys aren't in the records' order.
    The contract tests' fixture adapter turns a fixture tree into one with no reasons."""
    from . import files
    found = []
    try:
        tables(inv, strict=True)
    except Unrepresentable as e:
        found += e.reasons
    rendered = files.render(inv)
    again = files.sources(files.build(rendered))
    for rel, source in files.sources(inv).items():
        if getattr(source, "error", None) is not None or rel not in rendered:
            continue
        twin = again.get(rel)
        if hasattr(source, "stem"):                 # products: the name isn't in the file
            twin = twin and dataclasses.replace(twin, name=source.name, format=source.format)
        if twin != source:
            found.append(f"{rel} doesn't read back the same once written as Deck Lab writes it")
    return found
