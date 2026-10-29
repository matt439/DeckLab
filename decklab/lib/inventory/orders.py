"""The inventory operations for orders, products and the watchlist (the phase 3 design's
amendment Q7 and the receipts-lens review items): pure functions registered with
inventory.register(), run by inventory.apply() or preview() on either backend.

    from decklab.lib import inventory
    from decklab.lib.inventory import orders           # registers the kinds below
    inventory.apply(inventory.Op("order.add", {...}), actor, "Order singles from MTGMate")

  order.add          a new order record with its components in one change: a cards payload, a
                     tokens payload and a product (its card list and its status row) as given,
                     and the watchlist rows it fulfils reduced or removed (fulfils)
  order.edit         a pending cards or tokens component's rows replaced (the Receipts page's
                     rules: the same total, for cards the same copies of each name, printings
                     and finishes that exist in the card index)
  order.record       supplied seller, order date, delivery notes or sources corrected without
                     changing its components or provenance; registered in order_records.py
  order.checks       a component's checks: add one, resolve one or clear them once it has
                     arrived (verified_checks keeps them), or withdraw one added by mistake
  order.split        part of a pending cards or tokens component moved to a new pending
                     component of the same order (file <stem>-<new id>.csv), totals unchanged,
                     each check copied to both parts unless it's kept or moved as asked, and
                     an extra-copies mark passed to the new part
  order.cancel       a pending component cancelled, optionally restoring recorded queue intent
  order.remove       an order with no received parts removed, restoring recorded queue intent
  order.merge        other orders' components moved into one order (one shipment, received
                     once), their records removed; registered in order_merge.py
  order.extra_copies a pending cards or product component acknowledged as extra copies of
                     printings already owned (or that undone), in the record's audit_notes
                     (rules.with_extra_copies), so the pool doesn't warn that its cards may have
                     been merged without a receipt
  product.add        a product (card list, status row and a component) added to an order
  product.edit       supplied fields and/or a pending product's card list corrected
  product.set_intact an owned product kept intact or broken up (no: its sleeves and deck box go)
  watchlist.set      one watchlist row changed, or added
  watchlist.remove   one watchlist row removed
  watchlist.add_many several rows added in one change, an identical request's quantity raised
                     instead of a second row (a deck's missing cards); registered in queue_many.py
  watchlist.replace  the whole watchlist as given (a shop check's prices in one change)

Every refusal is state.Invalid with the words today's readers and pages use for the same
problem (purchases.read_records' and read_queue's, merge_cards', the token rules', the Receipts
page's), so the command line says what Shopping would. Each operation also keeps purchases'
pairing of products and their components (an ordered or preordered product's component is
pending, an owned one's received; every product component has a status row and every status row
a component): a change that would break it is refused with Shopping's own words, while a
problem that was already there doesn't stop an unrelated change.

Rows given to an operation are plain dicts (an operation's params stay plain values, so a
preview can be run again at apply). An operation never opens a file, except that sources (a
record's, a watchlist row's) must be files in the repository, checked under params["repo"]; a
source naming a deck file must be one of the snapshot's decks instead (purchases.source_exists).

The operations that can change the deck tables' labels (order.add, edit, split, cancel and
extra_copies, product.add and set_intact) are registered with refresh=True: inventory.apply() and preview()
refresh the deck tables in the same change (refresh.in_op), their outcome in
Summary.extra["tables"].
"""
import csv
import io
from collections import Counter
from pathlib import Path, PurePosixPath

from decklab.lib import purchases
from decklab.lib.state import Invalid

from . import Summary, paths, register, rules
from .model import QUEUE_FIELDS, Component, Order, Product, ProductItem

PAYLOAD_FIELDS = {"cards": list(rules.FIELDS), "tokens": list(rules.TOKEN_FIELDS)}
INCOMING = ("ordered", "preordered")
WHOLE = "Receive a whole component. Split partial arrivals on the PC first; total quantities cannot change here."
EDIT_FIELDS = "The received rows need exactly the component's CSV fields"
NAMES_CHANGED = "Card names and total copies must match the recorded component"
NEEDS_ATTENTION = "Shopping records need attention: "


def _invalid(error):
    """A ValueError (or csv.Error) from a shared rule as state.Invalid with its words."""
    return Invalid(str(error))


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


# ------------------------------------------------------------------ products and their components

def pairing_problems(inv):
    """purchases._coverage's product rules over a snapshot, as its warning texts: a status row
    with no component, statuses that disagree (owned with received, ordered or preordered with
    pending), a product component with no status row."""
    covered = {}
    for _, c in inv.components():
        if isinstance(c.path, str):
            covered[c.path] = c
    out, seen = [], set()
    for row in inv.status.rows:
        value = f"{paths.PRODUCTS}/{row.text('file')}"
        seen.add(value)
        component = covered.get(value)
        if component is None:
            out.append(f"{value}: missing order record")
        elif component.status != ("received" if row.text("status") == "owned" else
                                  "cancelled" if row.text("status") == "cancelled" else "pending"):
            out.append(f"{value}: product and order receipt statuses disagree")
    for value, component in covered.items():
        if component.kind == "product" and value not in seen:
            out.append(f"{value}: missing product status")
    return out


def keep_pairing(before, after):
    """Refuse (state.Invalid) a change that adds a pairing problem (pairing_problems)."""
    had = set(pairing_problems(before))
    new = [p for p in pairing_problems(after) if p not in had]
    if new:
        raise Invalid(NEEDS_ATTENTION + "; ".join(new))


def _done(before, after, summary):
    keep_pairing(before, after)
    return after, summary


# ------------------------------------------------------------------ checking what's given

def _record_fields(record, repo, inv=None):
    """The record's own fields (id, seller, ordered_on, sources, notes, audit_notes) checked as
    purchases.read_records checks them; returns them in the records' key order."""
    if not isinstance(record, dict):
        raise Invalid("An order needs its record's fields")
    oid = record.get("id")
    name = f"Order {oid}"                   # the database's words (E11-S12), not its record's .json
    if not isinstance(oid, str) or not purchases.ID_RE.fullmatch(oid):
        raise Invalid(f"{name}: invalid order id")
    try:
        for key in ("seller", "notes"):
            purchases._text(record.get(key, ""), f"{name}: {key}")
        if record.get("audit_notes") is not None:
            purchases._text(record["audit_notes"], f"{name}: audit_notes")
        purchases._date(record.get("ordered_on", ""), f"{name}: ordered_on")
        sources = purchases._strings(_listed(record.get("sources", [])), f"{name}: sources")
        for source in sources:
            if not purchases.source_exists(Path(repo), source, inv=inv):
                raise ValueError(f"{name}: source {source} does not exist")
    except ValueError as e:
        raise _invalid(e) from None
    return {"id": oid, "seller": record.get("seller", ""), "ordered_on": record.get("ordered_on", ""),
            "sources": sources, "notes": record.get("notes", ""), "audit_notes": record.get("audit_notes")}


def _listed(value):
    """A tuple as a list (JSON gives lists; Python callers may pass tuples); anything else as it is."""
    return list(value) if isinstance(value, tuple) else value


def _checks(value, where):
    try:
        return purchases._strings(_listed(value if value is not None else []), where)
    except (TypeError, ValueError) as e:
        raise _invalid(e) from None


def _component_id(value, taken, where):
    if not isinstance(value, str) or not purchases.ID_RE.fullmatch(value) or value in taken:
        raise Invalid(f"{where}: invalid or repeated component id")
    taken.add(value)
    return value


def _exact_rows(rows, fields, message):
    """rows (dicts) as dicts of strings with exactly fields, refused with message otherwise."""
    if not isinstance(rows, (list, tuple)) or not rows:
        raise Invalid(message)
    out = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(fields):
            raise Invalid(message)
        out.append({k: "" if row[k] is None else str(row[k]) for k in fields})
    return out


def card_rows(rows, where, owners=None):
    """Card payload rows checked as merge_cards.read checks an incoming file (its texts, naming
    where and each row's line as written; an inventory source in its database words, owners as
    for paths.describe); the rows normalised to collection.csv's columns."""
    text = rules.csv_bytes(rows, rules.FIELDS).decode("utf-8")
    try:
        if paths.classify(where) is not None:       # an inventory source: its rows by number (E11-S12)
            return rules.parse_cards(io.StringIO(text, newline=""), paths.describe(where, owners), numbered=True)
        return rules.parse_cards(io.StringIO(text, newline=""), where)
    except (rules.InvalidCards, csv.Error) as e:
        raise _invalid(e) from None


def token_rows(rows, where, owners=None):
    """Token payload rows checked as tokens.csv rows (validate_token_row, not yet the receipt's
    stricter incoming rule); each named by its number in where's database words ("Row 2 of
    order x's token cards", E11-S12)."""
    for number, row in enumerate(rows, 1):
        try:
            rules.validate_token_row(row, paths.row_of(where, number, owners))
        except ValueError as e:
            raise _invalid(e) from None
    return rows


NO_INDEX = ("The card index isn't built, so names and printings can't be checked: run python -m "
            "decklab.lib.cards update, or give --no-check to record it unchecked")
NAMES_UNCHECKED = "Card names weren't checked: there's no card index yet (python -m decklab.lib.cards update)"


def index_ready():
    """Whether the card index can be read (loading it now when it isn't yet)."""
    from decklab.lib import cards
    try:
        cards._get()
    except cards.INDEX_ERRORS:
        return False
    return True


def check_card_rows(rows, printings=True, names_only=False):
    """Each card row's name against the card index, and with printings (not names_only, as for a
    product's list) its printing and finish too (check_printings). A name the index doesn't know
    is always refused, since one stops every deck's table refresh: printings False (--no-check)
    skips only the printing checks, and lets the rows through unchecked, with a warning, only
    when there's no card index at all. Returns the warnings."""
    if not index_ready():
        if printings:
            raise Invalid(NO_INDEX)
        return [NAMES_UNCHECKED]
    if printings and not names_only:
        check_printings(rows)
    else:
        check_product_names(rows)
    return []


def check_printings(rows):
    """Each card row's name and printing against the card index, as the Receipts page checks
    them (an ordinary basic with no collector number: its name only)."""
    from decklab.lib import cards
    for row in rows:
        card = cards.card(row["name"])
        if card is None:
            raise Invalid(f"{row['name']}: not a card name in the local Scryfall data; check the spelling "
                          "or refresh the card cache")
        if not row["collector_number"] and rules.ordinary_basic(row):
            continue
        printed = cards.printing_card(row["set"], row["collector_number"])
        printing = cards.printing(row["set"], row["collector_number"])
        if printed is None or printed["name"] != card["name"]:
            raise Invalid(f"{row['name']}: printing does not match the local Scryfall data; verify it or "
                          "refresh the card cache")
        if row["finish"] not in (printing or {}).get("finishes", []):
            raise Invalid(f"{row['name']}: that finish is not available for the printing")


def check_token_names(rows):
    """Each token row's face names against the card index (tokens.names.check_names), with the
    exact names it gives; (rows, warnings), the warning saying when the index isn't there."""
    from decklab.lib.tokens.names import check_names
    out, warnings = [], []
    for row in rows:
        try:
            fixed, said = check_names(row)
        except ValueError as e:
            raise _invalid(e) from None
        out.append(fixed)
        warnings += [w for w in said if w not in warnings]
    return out, warnings


def check_product_names(rows):
    from decklab.lib import cards
    for row in rows:
        if cards.card(row["name"]) is None:
            raise Invalid(f"{row['name']}: not a card name in the local Scryfall data; check the spelling "
                          "or refresh the card cache")


def _file_taken(inv, kind, file_name):
    """Whether a cards or tokens payload of that file name is already there (any status, named
    by a record or not)."""
    for status in paths.STATUSES:
        if paths.payload(kind, status, file_name) in inv.payloads:
            return True
    return any(c.kind == kind and c.file_name == file_name for _, c in inv.components())


def _order(inv, order_id):
    order = inv.order(order_id) if isinstance(order_id, str) else None
    if order is None or order.error is not None or not isinstance(order.data, dict):
        raise Invalid(f"There's no order {order_id!r}.")
    return order


def _component(inv, order_id, component_id):
    order = _order(inv, order_id)
    for c in order.components:
        if c.id == component_id:
            return order, c
    raise Invalid(f"Order {order_id} has no component {component_id!r}.")


def _pending_payload(inv, order_id, component_id, verb):
    """(order, component, its payload rows as dicts) of a pending cards or tokens component."""
    order, c = _component(inv, order_id, component_id)
    if c.kind == "product":
        raise Invalid(f"{component_id} is a product; its card list can't be {verb}.")
    if c.status != "pending":
        raise Invalid(f"{component_id} is already {c.status}.")
    sheet = inv.payloads.get(c.path)
    if sheet is None or not sheet.readable:
        raise Invalid(f"{paths.title(paths.component_words(order.id, c.id, c.kind))}: nothing is there to be {verb}.")
    return order, c, [{k: row.text(k) for k in PAYLOAD_FIELDS[c.kind]} for row in sheet.rows]


def _quantity(value, where):
    if isinstance(value, bool):
        raise Invalid(f"{where}: quantity must be a positive integer")
    try:
        return purchases._quantity(str(value), where)
    except ValueError as e:
        raise _invalid(e) from None


# ------------------------------------------------------------------ products

def _product_parts(inv, product, taken, check_cards):
    """(Product, status row, Component, warnings) for a product given as {stem, columns, rows,
    name?, format?, status?, notes?, id?, checks?}. Its card names are checked against the card
    index (check_card_rows; a product list has no finish to check)."""
    if not isinstance(product, dict):
        raise Invalid("A product needs its stem, columns and rows")
    stem = product.get("stem")
    if not isinstance(stem, str) or not rules.SLUG.fullmatch(stem) or stem == "status":
        raise Invalid(f"{stem!r} isn't a product file name (lower-case letters, digits and hyphens)")
    file = f"{stem}.csv"
    if inv.product(stem) is not None or any(row.text("file") == file for row in inv.status.rows):
        raise Invalid(f"Product {stem} already exists")
    columns = product.get("columns")
    if not isinstance(columns, (list, tuple)) or not all(isinstance(c, str) for c in columns):
        raise Invalid(f"Product {stem}: missing or duplicate columns")
    columns = tuple(columns)
    rows = _exact_rows(product.get("rows"), columns, f"Product {stem}: each row needs exactly its columns")
    text = rules.csv_bytes(rows, list(columns)).decode("utf-8")
    try:
        parsed = rules.parse_cards(io.StringIO(text, newline=""), paths.describe(paths.product(stem)), numbered=True)
    except (rules.InvalidCards, csv.Error) as e:
        raise _invalid(e) from None
    warnings = check_card_rows(parsed, check_cards, names_only=True)
    status = product.get("status", "ordered")
    if status not in INCOMING:
        raise Invalid(f"Product {stem}: a new product is ordered or preordered, not {status!r}")
    notes = product.get("notes", "")
    try:
        purchases._text(notes, f"Product {stem}: notes")
        for key in ("name", "format"):
            if product.get(key) is not None:
                purchases._text(product[key], f"Product {stem}: {key}", blank=False)
    except ValueError as e:
        raise _invalid(e) from None
    cid = _component_id(product.get("id") or stem, taken, f"Order {product.get('order')}")
    made = Product(stem, columns, tuple(ProductItem.make(row, columns, line=n) for n, row in enumerate(rows, 2)),
                   product.get("name"), product.get("format"))
    _deck_lines(made)
    row = {"file": file, "status": status, "intact": "", "sleeves": "", "deck_box": "", "notes": notes}
    component = Component.build(cid, "product", file, checks=_checks(product.get("checks"), f"{cid}: checks"))
    return made, row, component, warnings


def _deck_lines(product):
    """decks._product_lines(product) (None: not a deck list), refused as Invalid in its words when
    a deck list can't be read (an unknown section, a bad finish or quantity): the pool lists such a
    product with its error, and an incomplete pool stops every deck table refresh and receipt."""
    from decklab.lib import decks
    try:
        return decks._product_lines(product)
    except decks.DeckFileError as e:
        raise Invalid(str(e)) from None         # it names the product and row (E11-S12)


def _with_status_row(inv, row):
    """status.csv with row added, keeping it in file-name order when it is (else at the end)."""
    rows = [{k: r.text(k) for k in rules.STATUS_FIELDS} for r in inv.status.rows]
    files_ = [r["file"] for r in rows]
    at = len(rows)
    if files_ == sorted(files_):
        at = next((i for i, f in enumerate(files_) if f > row["file"]), len(rows))
    rows.insert(at, row)
    return inv.with_status_rows(rows)


# ------------------------------------------------------------------ the watchlist

def queue_row(row, repo, inv=None):
    """A watchlist row (dict of QUEUE_FIELDS) checked as purchases.read_queue checks one, in its
    words; the row with every value text. A source naming a deck file is looked for among inv's
    decks (purchases.source_exists; inventory.current() when inv is None)."""
    try:
        if not isinstance(row, dict) or set(row) != set(QUEUE_FIELDS):
            raise ValueError(f"watchlist: a row needs exactly the columns {','.join(QUEUE_FIELDS)}")
        row = {k: "" if row[k] is None else str(row[k]) for k in QUEUE_FIELDS}
        where = f"watchlist: {row['name']}"
        for value in row.values():
            purchases._text(value, where)
        purchases._text(row["name"], where, blank=False)
        purchases._quantity(row["quantity"], where)
        if row["state"] not in purchases.STATES:
            raise ValueError(f"{where}: invalid purchase state")
        if row["printing"] not in ("any", "exact"):
            raise ValueError(f"{where}: printing must be any or exact")
        if row["finish"] not in ("", "nonfoil", "foil", "etched"):
            raise ValueError(f"{where}: invalid finish")
        if row["printing"] == "exact" and not all(row[k] for k in ("set", "collector_number", "finish")):
            raise ValueError(f"{where}: exact printing needs set, collector number and finish")
        if row["in_stock"] not in ("", "yes", "no"):
            raise ValueError(f"{where}: stock must be yes, no or blank")
        purchases._date(row["checked"], where)
        if row["listed_aud"]:
            from decimal import Decimal, InvalidOperation
            try:
                price = Decimal(row["listed_aud"])
                if not price.is_finite() or price < 0:
                    raise InvalidOperation()
            except InvalidOperation:
                raise ValueError(f"{where}: invalid AUD reference price") from None
            if not row["checked"] or not row["listed_at"]:
                raise ValueError(f"{where}: reference price needs retailer and checked date")
        if row["source"] and not purchases.source_exists(Path(repo), row["source"], inv=inv):
            raise ValueError(f"{where}: source file does not exist")
    except ValueError as e:
        raise _invalid(e) from None
    return row


def queue_key(row):
    """read_queue's identity of a watchlist row (no two rows may share it)."""
    return tuple(row[k] for k in ("name", "printing", "set", "collector_number", "finish", "for"))


def _queue_dicts(inv):
    return [{k: r.text(k) for k in QUEUE_FIELDS} for r in inv.watchlist.rows]


def find_queue_rows(rows, select):
    """The indexes of the watchlist rows a selector names: "#N" (the Nth row, as `watchlist list`
    numbers them), "NAME" or "NAME@FOR" (the exact name, and the exact for when given)."""
    if not isinstance(select, str) or not select:
        raise Invalid("Name a watchlist row: NAME, NAME@FOR or #N")
    if select.startswith("#") and select[1:].isdigit():
        n = int(select[1:])
        if not 1 <= n <= len(rows):
            raise Invalid(f"The watchlist has no row {select} (it has {_plural(len(rows), 'row')}).")
        return [n - 1]
    name, _, deck = select.partition("@")
    return [i for i, row in enumerate(rows) if row["name"] == name and (not _ or row["for"] == deck)]


def one_queue_row(rows, select):
    found = find_queue_rows(rows, select)
    if not found:
        raise Invalid(f"No watchlist row matches {select!r}.")
    if len(found) > 1:
        listed = "; ".join(f"#{i + 1} {rows[i]['name']} for {rows[i]['for'] or '(nothing)'} "
                           f"({rows[i]['printing']} {rows[i]['set']} {rows[i]['collector_number']})".rstrip()
                           for i in found)
        raise Invalid(f"{select!r} matches more than one watchlist row ({listed}); use NAME@FOR or #N.")
    return found[0]


def _no_duplicates(rows):
    seen = set()
    for row in rows:
        if queue_key(row) in seen:
            raise Invalid(f"watchlist: {row['name']}: duplicate purchase request")
        seen.add(queue_key(row))


def _with_queue(inv, rows):
    """The watchlist as rows (dicts), keeping each kept row's hidden id (matched by position in
    the old list for rows passed through from it, else by identity)."""
    old = list(inv.watchlist.rows)
    by_key = {}
    for row in old:
        by_key.setdefault(queue_key({k: row.text(k) for k in QUEUE_FIELDS}), row)
    made = []
    for row in rows:
        source = row.pop("_row", None) if isinstance(row, dict) else None
        if source is None:
            source = by_key.get(queue_key(row))
        made.append(source.replace(**row) if source is not None else row)
    return inv.with_watchlist(made)


def _fulfil(inv, fulfils, ordered, exact):
    """The watchlist with each fulfilled row reduced (removed at 0): fulfils is
    [{select, quantity (None: the whole row)}]; ordered {name: copies in the order}, exact
    {(set, number, finish): copies}. An exact row is fulfilled only by its printing. With nothing
    to fulfil the watchlist isn't touched (so a file in an odd shape isn't rewritten)."""
    if not fulfils:
        return inv, []
    rows = _queue_dicts(inv)
    for i, row in enumerate(rows):
        row["_row"] = inv.watchlist.rows[i]
    used, left = Counter(), Counter(ordered)
    reduced = []
    for item in fulfils or ():
        if not isinstance(item, dict):
            raise Invalid("Each fulfilled watchlist row needs a selector and a quantity")
        index = one_queue_row(rows, item.get("select"))
        row = rows[index]
        have = _quantity(row["quantity"], f"watchlist: {row['name']}")
        qty = have if item.get("quantity") is None else _quantity(item["quantity"], f"watchlist: {row['name']}")
        if qty > have:
            raise Invalid(f"watchlist: {row['name']}: only {have} queued, not {qty}")
        if row["printing"] == "exact":
            key = (row["set"], row["collector_number"], row["finish"])
            if exact.get(key, 0) - used[key] < qty:
                raise Invalid(f"watchlist: {row['name']}: the order doesn't have {qty} of the exact printing "
                              f"{row['set']} {row['collector_number']} {row['finish']}")
            used[key] += qty
        if left[row["name"]] < qty:
            raise Invalid(f"watchlist: {row['name']}: the order has {left[row['name']]} of it, not {qty}")
        left[row["name"]] -= qty
        row["quantity"] = str(have - qty)
        reduced.append((row["name"], row["for"], qty))
    kept = [row for row in rows if row["quantity"] != "0"]
    return _with_queue(inv, kept), reduced


# ------------------------------------------------------------------ order.add

@register("order.add", refresh=True)
def add_order(inv, *, record, cards=None, tokens=None, product=None, fulfils=(), repo=".", check_cards=True,
              extra_copies=()):
    """A new order (see the module docstring). record: {id, seller, ordered_on, sources, notes,
    audit_notes?}; cards / tokens: {rows, id?, checks?}; product: {stem, columns, rows, name?,
    format?, status?, notes?, id?, checks?}; fulfils: [{select, quantity}]. check_cards False
    (--no-check) skips the printing checks (check_card_rows); token names are checked whenever the
    card index is there. extra_copies: ids of its cards or product components marked as extra
    copies of printings already owned (as order.extra_copies marks them), in the same change."""
    before = inv
    fields = _record_fields(record, repo, inv)
    oid = fields["id"]
    if inv.order(oid) is not None or any(o.file == f"{oid}.json" for o in inv.orders):
        raise Invalid(f"Order {oid} already exists")
    if not (cards or tokens or product):
        raise Invalid(f"Order {oid}: order needs components")
    taken, components, payloads, warnings = set(), [], [], []
    ordered, exact = Counter(), Counter()
    counts = {}
    for kind, given in (("cards", cards), ("tokens", tokens)):
        if not given:
            continue
        if not isinstance(given, dict):
            raise Invalid(f"The {kind} component needs its rows")
        cid = _component_id(given.get("id") or kind, taken, f"Order {oid}")
        file_name = f"{oid}.csv"
        where = paths.payload(kind, "pending", file_name)
        owners = {where: (oid, cid)}
        if _file_taken(inv, kind, file_name):
            raise Invalid(f"{paths.title(paths.component_words(oid, cid, kind))} are already in another order")
        rows = _exact_rows(given.get("rows"), PAYLOAD_FIELDS[kind],
                           f"{paths.title(paths.describe(where, owners))}: each row needs exactly the columns "
                           f"{','.join(PAYLOAD_FIELDS[kind])}")
        if kind == "cards":
            rows = card_rows(rows, where, owners)
            warnings += [w for w in check_card_rows(rows, check_cards) if w not in warnings]
            for row in rows:
                ordered[row["name"]] += int(row["quantity"])
                exact[(row["set"], row["collector_number"], row["finish"])] += int(row["quantity"])
        else:
            rows, said = check_token_names(token_rows(rows, where, owners))
            warnings += [w for w in said if w not in warnings]
            for row in rows:
                ordered[row["front"]] += int(row["quantity"])
                if row["back"]:
                    ordered[f"{row['front']} // {row['back']}"] += int(row["quantity"])
                # An exact-printing token row (its token set code and a face's number) is fulfilled
                # by either face's printing; a back with the front's number is the same card.
                numbers = {row["front_collector_number"], row["back_collector_number"]} - {""}
                for number in numbers:
                    exact[(row["set"], number, row["finish"])] += int(row["quantity"])
        counts[kind] = sum(int(row["quantity"]) for row in rows)
        components.append(Component.build(cid, kind, file_name, checks=_checks(given.get("checks"), f"{cid}: checks")))
        payloads.append((cid, rows))
    made = None
    if product:
        made, status_row, component, said = _product_parts(inv, {**product, "order": oid}, taken, check_cards)
        warnings += [w for w in said if w not in warnings]
        components.append(component)
        for item in made.items:
            ordered[item.text("name")] += int(item.text("quantity"))
            exact[(item.text("set"), item.text("collector_number"), item.text("finish"))] += int(item.text("quantity"))
        counts["product"] = sum(int(item.text("quantity")) for item in made.items)
    if extra_copies:
        if isinstance(extra_copies, str) or not isinstance(extra_copies, (list, tuple)):
            raise Invalid("Name the components that are extra copies of owned printings")
        marked = list(rules.extra_copies(fields["audit_notes"])) + list(extra_copies)
        kinds = {c.id: c.kind for c in components}
        for cid in marked:
            if kinds.get(cid) not in EXTRA_KINDS:
                raise Invalid(f"{oid}.json: {cid!r} isn't a cards or product component of this order, so it "
                              "can't be marked as extra copies of owned printings")
        fields["audit_notes"] = rules.with_extra_copies(fields["audit_notes"], marked)
    order = Order.build(oid, fields["seller"], fields["ordered_on"], fields["sources"], fields["notes"], components,
                        fields["audit_notes"])
    inv = inv.with_order(order)
    for cid, rows in payloads:
        inv = inv.set_component_rows(oid, cid, rows)
    if made is not None:
        inv = _with_status_row(inv.with_product(made), status_row)
    from . import order_fulfilment
    inv, reduced = _fulfil(inv, fulfils, ordered, exact)
    inv = inv.with_order(order_fulfilment.record(before, inv, order, fulfils))
    parts = [f"{_plural(n, 'card')}" if k == "cards" else f"{_plural(n, 'token card')}" if k == "tokens"
             else f"the product {product['stem']} ({_plural(n, 'card')})" for k, n in counts.items()]
    text = f"Recorded order {oid}: " + ", ".join(parts)
    if reduced:
        text += "; watchlist: " + ", ".join(f"{q} x {n}" + (f" for {f}" if f else "") for n, f, q in reduced)
    return _done(before, inv, Summary(text, {**counts, "watchlist_reduced": sum(q for _, _, q in reduced)},
                                      extra={"warnings": warnings, "order": oid}))


# ------------------------------------------------------------------ order.edit

@register("order.edit", refresh=True)
def edit_order(inv, *, order, component, rows, check_cards=True):
    """A pending cards or tokens component's rows replaced (the Receipts page's rules)."""
    before = inv
    o, c, previous = _pending_payload(inv, order, component, "edited")
    fields = PAYLOAD_FIELDS[c.kind]
    rows = _exact_rows(rows, fields, EDIT_FIELDS)
    owners = {c.path: (o.id, c.id)}
    if c.kind == "cards":
        rows = card_rows(rows, c.path, owners)
    else:
        rows = token_rows(rows, c.path, owners)
    if sum(int(r["quantity"]) for r in rows) != sum(int(r["quantity"]) for r in previous):
        raise Invalid(WHOLE)
    warnings = []
    if c.kind == "cards":
        def quantities(items):
            out = Counter()
            for row in items:
                out[row["name"]] += int(row["quantity"])
            return out
        if quantities(rows) != quantities(previous):
            raise Invalid(NAMES_CHANGED)
        warnings = check_card_rows(rows, check_cards)
        rows = sorted(rows, key=rules.sort_key)
    else:
        rows, warnings = check_token_names(rows)
    if rows == previous:
        return inv, Summary(f"Order {order} {component}: nothing to change")
    inv = inv.set_component_rows(order, component, rows)
    from . import order_fulfilment
    inv = inv.with_order(order_fulfilment.edit(inv.order(order), component, previous, rows))
    return _done(before, inv, Summary(f"Edited order {order} {component}: {_plural(len(rows), 'row')}",
                                      {"rows": len(rows)}, extra={"warnings": warnings}))


# ------------------------------------------------------------------ order.checks

@register("order.checks")
def order_checks(inv, *, order, component, add=None, resolve=None, clear=False, withdraw=None, target=None):
    """A component's checks: add one (text), resolve one (1-based, as `order show` numbers them),
    clear them all, or withdraw one (a check added by mistake: gone, nothing verified).
    Resolving and clearing are for a component that has arrived, which keeps what was resolved
    in verified_checks (the audit list a receipt keeps). A pending component's checks are
    verified at its receipt (receive --verified), which a cards or tokens component with checks
    can't skip, so resolving them before it arrives is refused."""
    before = inv
    _, c = _component(inv, order, component)
    from . import check_links
    if target is not None:
        if add is None or c.kind not in PAYLOAD_FIELDS or c.status != "pending":
            raise Invalid("Only a new arrival check on a pending cards or tokens part may target a row.")
        from . import backend, pg_check_links
        store = backend()
        if getattr(store, "name", None) == "db" and not store.supports_check_links():
            raise Invalid(pg_check_links.REQUIRED)
    if sum(x is not None and x is not False for x in (add, resolve, clear or None, withdraw)) != 1:
        raise Invalid("Give one of: a check to add, a check number to resolve or withdraw, or clear")
    if c.status == "cancelled":
        raise Invalid(f"{component} is cancelled; its checks no longer count.")
    if c.status == "pending" and (resolve is not None or clear):
        raise Invalid(f"{component} hasn't arrived yet: its checks are verified when it's received "
                      f"(receive --verified {component}). To drop a check added by mistake, withdraw it.")
    checks = list(c.checks or [])
    done = []
    if withdraw is not None:
        if isinstance(withdraw, bool) or not isinstance(withdraw, int) or not 1 <= withdraw <= len(checks):
            raise Invalid(f"{component} has no check {withdraw!r} (it has {_plural(len(checks), 'check')}).")
        checks.pop(withdraw - 1)
        text = f"Order {order} {component}: withdrew a check"
    elif add is not None:
        checks += _checks([add], f"{order}.json: {component}")
        text = f"Order {order} {component}: added a check"
    elif clear:
        if not checks:
            raise Invalid(f"{component} has no checks.")
        done, checks = checks, []
        text = f"Order {order} {component}: cleared {_plural(len(done), 'check')}"
    else:
        if isinstance(resolve, bool) or not isinstance(resolve, int) or not 1 <= resolve <= len(checks):
            raise Invalid(f"{component} has no check {resolve!r} (it has {_plural(len(checks), 'check')}).")
        done = [checks.pop(resolve - 1)]
        text = f"Order {order} {component}: resolved a check"
    changes = {"checks": checks}
    if add is not None:
        rows = []
        if c.kind in PAYLOAD_FIELDS and c.status == "pending":
            sheet = inv.payloads.get(c.path)
            if sheet is not None and sheet.readable and not sheet.strict_error and not sheet.csv_error:
                rows = [{key: row.text(key) for key in PAYLOAD_FIELDS[c.kind]} for row in sheet.rows]
        changes["check_links"] = check_links.append(c, rows, PAYLOAD_FIELDS.get(c.kind, ()), checks[-1], target)
    else:
        changes["check_links"] = check_links.remap(c, checks, withdraw if withdraw is not None else resolve)
    if done and c.status == "received":
        changes["verified_checks"] = list(c.verified_checks or []) + done
    inv = inv.update_component(order, component, **changes)
    return _done(before, inv, Summary(text, {"checks": len(checks)}))


# ------------------------------------------------------------------ order.split

@register("order.split", refresh=True)
def split_order(inv, *, order, component, new_id, take, move_checks=(), copy_checks=(), keep_checks=(),
                _arrived_first=False):
    """Part of a pending cards or tokens component moved to a new pending component new_id of the
    same order, its file <the component's file stem>-<new_id>.csv, put right after it. take:
    [{row (1-based, as `order show` numbers them), quantity}]; move_checks / keep_checks: the
    1-based numbers of the checks that go only to the new component (moved) or stay only on the
    original (kept). Every other check is copied to both (copy_checks may name some), so neither
    part can be received without verifying what was asked of the whole. The total quantity is
    unchanged. A component marked as extra copies of owned printings (order.extra_copies) passes
    the mark to new_id in the same change, since its cards are part of the same acknowledged order."""
    before = inv
    o, c, rows = _pending_payload(inv, order, component, "split")
    owners = {c.path: (o.id, c.id)}
    record = o.record()
    ids = {item.get("id") for item in record["components"] if isinstance(item, dict)}
    _component_id(new_id, set(ids), f"Order {order}")
    file_name = f"{PurePosixPath(c.file_name).stem}-{new_id}.csv"
    if _file_taken(inv, c.kind, file_name):
        raise Invalid(f"{paths.title(paths.component_words(o.id, new_id, c.kind))} are already in another order")
    if not isinstance(take, (list, tuple)) or not take:
        raise Invalid("Say which rows (and how many of each) go to the new component")
    moved = []
    seen = set()
    for item in take:
        n = item.get("row") if isinstance(item, dict) else None
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= len(rows) or n in seen:
            raise Invalid(f"There's no row {n!r} of {paths.component_words(o.id, c.id, c.kind)} to take (it has "
                          f"{_plural(len(rows), 'row')}), or it's named twice")
        seen.add(n)
        row = rows[n - 1]
        have = int(row["quantity"])
        qty = have if item.get("quantity") is None else _quantity(item["quantity"], paths.row_of(c.path, n, owners))
        if qty > have:
            raise Invalid(f"{paths.row_of(c.path, n, owners)} has {have}, not {qty}")
        moved.append({**row, "quantity": str(qty)})
        row["quantity"] = str(have - qty)
    kept = [row for row in rows if row["quantity"] != "0"]
    if not kept:
        raise Invalid(f"Nothing would be left in {component}; a split leaves something in both parts")
    checks = list(c.checks or [])
    numbers = []
    for value in (*move_checks, *copy_checks, *keep_checks):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= len(checks) or value in numbers:
            raise Invalid(f"{component} has no check {value!r} (it has {_plural(len(checks), 'check')}), "
                          "or it's named twice")
        numbers.append(value)
    new_checks = [check for i, check in enumerate(checks, 1) if i not in set(keep_checks)]
    old_checks = [check for i, check in enumerate(checks, 1) if i not in set(move_checks)]
    made = Component.build(new_id, c.kind, file_name, checks=new_checks)
    items = []
    for item in record["components"]:
        items.append(item)
        if isinstance(item, dict) and item.get("id") == component:
            item["checks"] = old_checks
            item.pop("check_links", None)  # A split never transfers a row binding by position.
            items.append(made.record())
    record["components"] = items
    marked = list(rules.extra_copies(o.audit_notes))
    extra = component in marked
    if extra:
        record["audit_notes"] = rules.with_extra_copies(record.get("audit_notes"), marked + [new_id])
    inv = inv.with_order(Order(o.file, record))
    inv = inv.set_component_rows(order, component, kept).set_component_rows(order, new_id, moved)
    from . import order_fulfilment
    inv = inv.with_order(order_fulfilment.split(inv.order(order), component, new_id, kept, moved,
                                              moved_first=_arrived_first))
    qty = sum(int(r["quantity"]) for r in moved)
    text = f"Split {_plural(qty, 'card')} of order {order} {component} into {new_id}"
    if extra:
        text += f"; {new_id} is marked as extra copies of owned printings too"
    return _done(before, inv, Summary(text, {"moved": qty, "rows": len(moved)},
                                      extra={"file_name": file_name, "extra_copies": extra}))


# ------------------------------------------------------------------ order.cancel

@register("order.cancel", refresh=True)
def cancel_order(inv, *, order, component, reason=None, restore_queue=False):
    """Cancel one pending component through the shared lifecycle rules."""
    from .order_lifecycle import cancel
    return cancel(inv, order=order, component=component, reason=reason, restore_queue=restore_queue)


# ------------------------------------------------------------------ order.extra_copies

EXTRA_KINDS = ("cards", "product")      # the components pool's already-in-the-collection guard reads


@register("order.extra_copies", refresh=True)
def extra_copies(inv, *, order, component, undo=False):
    """A pending cards or product component marked (undo: no longer marked) as extra copies of
    printings already owned, in the record's audit_notes (rules.with_extra_copies: only that
    sentence changes; every other field and word stays). While it's marked, pool._load_pool doesn't
    warn that every card in it is already in the collection, so that warning (which stops every
    deck table refresh and receipt) is left for orders that may really have been merged early.
    Refused for a component that isn't pending (the guard only reads pending ones) or is a tokens
    one (the guard doesn't read those). A receipt or cancellation leaves the marker in the record
    as a record of what was said; nothing reads it then."""
    before = inv
    o, c = _component(inv, order, component)
    if c.kind not in EXTRA_KINDS:
        raise Invalid(f"{component} is a {c.kind} component; only a cards or product component can be "
                      "marked as extra copies of owned printings.")
    if c.status != "pending":
        raise Invalid(f"{component} is already {c.status}; only a pending component can be marked or unmarked.")
    marked = list(rules.extra_copies(o.audit_notes))
    if (component in marked) != bool(undo):
        state = "isn't" if undo else "is already"
        return inv, Summary(f"Order {order} {component} {state} marked as extra copies of owned printings")
    ids = [cid for cid in marked if cid != component] if undo else marked + [component]
    record = o.record()
    notes = rules.with_extra_copies(record.get("audit_notes"), ids)
    if notes is None:
        record.pop("audit_notes", None)
    else:
        record["audit_notes"] = notes
    inv = inv.with_order(Order(o.file, record))
    verb = "no longer marked" if undo else "marked"
    return _done(before, inv, Summary(f"Order {order} {component}: {verb} as extra copies of owned printings",
                                      {"marked": len(ids)}))


# ------------------------------------------------------------------ products

@register("product.add", refresh=True)
def add_product(inv, *, order, product, check_cards=True):
    """A product added to an existing order: its card list, its status row (ordered or
    preordered) and a pending product component, in one change."""
    before = inv
    o = _order(inv, order)
    taken = {c.id for c in o.components}
    made, status_row, component, warnings = _product_parts(inv, {**product, "order": order}, taken, check_cards)
    record = o.record()
    record["components"].append(component.record())
    inv = _with_status_row(inv.with_order(Order(o.file, record)).with_product(made), status_row)
    n = sum(int(item.text("quantity")) for item in made.items)
    return _done(before, inv, Summary(f"Added the product {made.stem} ({_plural(n, 'card')}) to order {order}",
                                      {"product": n}, extra={"warnings": warnings}))


@register("product.set_intact", refresh=True)
def set_intact(inv, *, stem, intact):
    """An owned product kept intact (yes) or broken up (no: its sleeves and deck box are cleared,
    as a receipt's --intact no does)."""
    before = inv
    if intact not in ("yes", "no"):
        raise Invalid("Intact is yes or no")
    file = f"{stem}.csv"
    rows = [{k: r.text(k) for k in rules.STATUS_FIELDS} for r in inv.status.rows]
    found = [row for row in rows if row["file"] == file]
    if len(found) != 1:
        raise Invalid(f"Product {stem} has {'no status' if not found else 'more than one status'}")
    row = found[0]
    if row["status"] != "owned":
        raise Invalid(f"Product {stem} is {row['status'] or 'not owned'}; only an owned product is kept intact or "
                      f"broken up")
    if row["intact"] == intact:
        return inv, Summary(f"Product {stem} is already {'kept intact' if intact == 'yes' else 'broken up'}")
    if intact == "yes":
        # The pool's own refusal (pool.load_pool): an intact product with no deck lists holds
        # nothing, and its warning stops every deck table refresh and receipt.
        product = inv.product(stem)
        if product is None:
            raise Invalid(f"Product {stem} has no card list, so it can't be kept intact")
        if product.error is not None:
            raise Invalid(f"Product {stem}'s card list can't be read: {product.error}")
        if _deck_lines(product) is None:
            raise Invalid(f"Product {stem} has no deck lists, so keeping it intact would hold nothing; "
                          "only a product with deck lists is kept intact")
    rules.set_intact(row, intact)
    inv = inv.with_status_rows(rows)
    return _done(before, inv, Summary(f"Product {stem}: {'kept intact' if intact == 'yes' else 'broken up'}"))


# ------------------------------------------------------------------ the watchlist

@register("watchlist.set")
def set_queue(inv, *, select=None, values, add=False, repo="."):
    """One watchlist row changed (values: the columns to set) or, with add, a new row added at the
    end (values: every column it needs; select None). A row whose quantity is set to 0 is
    refused: remove it instead."""
    before = inv
    if not isinstance(values, dict) or not values or not set(values) <= set(QUEUE_FIELDS):
        raise Invalid(f"Set one or more of the watchlist's columns: {', '.join(QUEUE_FIELDS)}")
    rows = _queue_dicts(inv)
    for i, row in enumerate(rows):
        row["_row"] = inv.watchlist.rows[i]
    if add:
        if select is not None:
            raise Invalid("A new watchlist row isn't selected; give its values")
        new = {k: "" for k in QUEUE_FIELDS}
        new.update({"printing": "any", "quantity": "1"})
        new.update(values)
        row = queue_row(new, repo, inv)
        rows.append(row)
        text = f"Added {row['quantity']} x {row['name']} to the watchlist ({row['state']})"
    else:
        index = one_queue_row(rows, select)
        source = rows[index].pop("_row")
        changed = {**rows[index], **values}
        row = queue_row(changed, repo, inv)
        row["_row"] = source
        if {k: v for k, v in row.items() if k != "_row"} == {k: v for k, v in rows[index].items()}:
            return inv, Summary(f"watchlist: {row['name']}: nothing to change")
        rows[index] = row
        text = f"Changed the watchlist's {row['name']}" + (f" for {row['for']}" if row["for"] else "") + \
            ": " + ", ".join(sorted(values))
    _no_duplicates(rows)
    return _done(before, _with_queue(inv, rows), Summary(text, {"rows": len(rows)}))


@register("watchlist.remove")
def remove_queue(inv, *, select):
    before = inv
    rows = _queue_dicts(inv)
    for i, row in enumerate(rows):
        row["_row"] = inv.watchlist.rows[i]
    index = one_queue_row(rows, select)
    gone = rows.pop(index)
    text = f"Removed {gone['quantity']} x {gone['name']}" + (f" for {gone['for']}" if gone["for"] else "") + \
        " from the watchlist"
    return _done(before, _with_queue(inv, rows), Summary(text, {"rows": len(rows)}))


@register("watchlist.replace")
def replace_queue(inv, *, rows, repo="."):
    """The whole watchlist as rows (dicts of every column), in that order: what a shop check's
    edited copy of watchlist.csv says, in one change. Each row is checked as read_queue checks
    it; rows keep their identity (hidden id) by read_queue's key."""
    before = inv
    if not isinstance(rows, (list, tuple)):
        raise Invalid("Give the watchlist's rows")
    made = [queue_row(row, repo, inv) for row in rows]
    _no_duplicates(made)
    old = _queue_dicts(inv)
    if made == old:
        return inv, Summary("The watchlist is already like that")
    old_keys = {queue_key(r) for r in old}
    new_keys = {queue_key(r) for r in made}
    changed = sum(1 for r in made if queue_key(r) in old_keys and r not in old)
    counts = {"added": len(new_keys - old_keys), "removed": len(old_keys - new_keys), "changed": changed}
    text = (f"Watchlist: {counts['added']} added, {counts['changed']} changed, {counts['removed']} removed "
            f"({_plural(len(made), 'row')})")
    return _done(before, _with_queue(inv, made), Summary(text, counts))


from . import order_records  # noqa: E402,F401 (registers order.record using the shared record rules)
from . import product_ops  # noqa: E402,F401 (registers pending product corrections)
from . import order_lifecycle  # noqa: E402,F401 (registers order removal)
from . import order_merge  # noqa: E402,F401 (registers combining orders that shipped together)
from . import queue_many  # noqa: E402,F401 (registers several queue rows added in one change)
