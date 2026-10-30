"""Owned vs needed for a deck, counting the shared card pool (PLAN.md part 3).

Usage (from the repo root):
    python -m decklab.lib.pool                        what's owned, on the way and in use
        [--space user2]    in a person's space (lib/spaces.py) instead of home's
    python -m decklab.lib.pool casual/gruul-ramp      owned vs needed for one deck
    python -m decklab.lib.pool user2/casual/elves   ... a deck in User2's space, against his pool
        [--owned]        use the deck file's owned-only list instead of the target list
        [--no-prices]    skip the AUD estimates

From code:

    from decklab.lib import decks, pool
    result = pool.owned_vs_needed("casual/gruul-ramp")   # version="owned" for the owned-only list
    result = pool.compare(sections, pool.load_pool(), pool.self_ids(deck_id))   # an unsaved list

    # A deck file's table, worked out from the target list in memory (edits included):
    decks.set_table(deck, *pool.deck_table(deck))

    pool.table_changes(deck, p)       # how that file's table differs from the pool now
    pool.stale_tables(p)              # every deck file whose table is out of date
    pool.table_blockers(p)            # what stops those tables being refreshed (never raises)
    pool.printing_counts()            # copies of each printing: owned and on the way

Any id decks.load_deck() takes works: "casual/<slug>", "commander/<slug>",
"product/<file>[/<deck>]", "pairing/<half>+<half>" and a person's
"<space>/<kind>/<slug>". To check many decks, load the pool once with
load_pool() and pass it in.

Spaces (lib/spaces.py)
    A pool is one space's: load_pool("user2") reads
    magic/people/user2/collection.csv (empty while it doesn't exist) and
    counts only User2's built decks as in use. Orders, products and
    on-the-way cards are home's only, so a person's pool has none. A deck is
    always checked against its own space's pool: owned_vs_needed, deck_table
    and stale_tables load that pool (for_space) when the one passed in is
    another space's. The table in a deck file
always describes its target list, so table_rows() refuses an owned-only
result; the owned-only comparison is for showing, not for writing.

Owned
    magic/collection.csv, plus cards that haven't arrived yet, which count as
    owned but are labelled "on the way":
    - magic/orders/*.csv (not orders/received/, which is already merged);
    - the whole card list of each product whose status in
      magic/products/status.csv is preordered or ordered.
    Products with status owned are already merged into collection.csv, so
    they aren't counted a second time. When every printing an order or
    incoming product lists is already in the collection, its cards may have
    been added without receiving it, so there's a warning: its cards would
    then count twice. Like every pool warning it makes the pool incomplete,
    which stops every deck table refresh and receipt. A real order for more
    copies of printings already owned looks the same, so a pending cards or
    product component can be acknowledged as extra copies of owned printings
    (python -m decklab.db order extra-copies ID COMPONENT; a sentence in the
    order record's audit_notes, inventory.rules.extra_copies), and then there's
    no warning for it. The rule is deliberately the plain one: an acknowledged
    component is never warned about, whatever the collection holds, since the
    collection keeps no per-copy history from which the pool could tell
    copies merged early from copies already owned before; the acknowledgement
    is the person's word, kept in the audit trail. Only pending components are
    read, so once one is received or cancelled its marker (left in the record)
    means nothing. A row of an order or
    incoming product that can't be read (a bad quantity, no name) is left out
    with a warning, and so is a whole file that can't be read, so one typo
    doesn't stop every owned-vs-needed check; a bad row in collection.csv
    still raises ValueError, since the counts can't be trusted without it.
    All of it comes from one inventory snapshot (decklab/lib/inventory:
    inventory.current(), the request's or command's pinned one), whichever
    backend holds it; the paths above are the names messages and labels use
    ("Row 2 of order x's cards: ...", "1 on the way (order <file stem>)"),
    worked out from what each piece is, so both backends say the same.

In use (a physical card can only be in one deck at a time)
    - Deck files whose Status is built. A built deck with both lists holds
      the one its "Built version" field names (target or owned-only). With no
      such field, or a value that isn't either, it holds the owned-only list,
      with a warning, since that's the list that can be put together from
      owned cards. A deck with one list holds it. (No deck was built yet on
      2026-09-29.)
    - Products with status owned and intact yes: each of their decks holds
      its cards (e.g. every Beginner Box half while the box is kept intact).
    Every section counts, commander and sideboard included, since those cards
    are kept with the deck. A deck never counts against itself: its own id,
    and for a Beginner Box pairing both of its halves, are left out of "in use
    elsewhere".

Counting
    By card name: every printing and finish plays the same, so copies are
    summed across them. Names go through cards.resolve(), so a front face
    alone or a missing accent still matches the full Scryfall name, and so
    does a decklist name that kept a lowercase set ("Llanowar Elves (fdn)",
    which the decklist parser can't tell from a name like "Hazmat Suit
    (Used)"). A name that doesn't resolve is counted as written and reported.
    Basic lands are left out everywhere: the user has plenty, and the tables
    don't list them.

    For each card the deck needs:
        available = max(owned - in use elsewhere, 0)
        missing   = max(need - available, 0)

Prices are cards.price_aud() estimates (the cheapest non-foil paper
printing's USD price times the ECB rate). The result carries the rate, its
date and Scryfall's price date once, so the page can show them with the
table, as AGENTS.md requires; table_rows() hands them to decks.set_table()
as a PriceStamp, which updates the rate line above the table. With no rate,
or an index that doesn't say when its prices were pulled, there are no
prices and price_error says why; a table rewritten then keeps only the old
price cells that still match the old rate line (see decks.TableRow).

The table's Notes cells get labels, as AGENTS.md asks: "1 on the way
(order 2026-09-29-shop-a)" for the copies this deck counts on that haven't
arrived, one per source, and "2 in use in Gruul Ramp", one per deck, for a
card this deck is short of because other decks hold copies. row_labels(row)
gives the same as data, for the page.
"""
import argparse
import contextlib
import csv
import json
import re
import sys
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from decklab.lib import cards, decks, inventory, spaces
from decklab.lib.config import REPO  # noqa: F401  (nothing here reads it; tests not yet ported patch it)
from decklab.lib.decks.identity import CardIdentityError, deck_colors
from decklab.lib.inventory import entry, rules, unreadable
from decklab.lib.inventory import files as inventory_files, paths as inventory_paths
from decklab.lib.inventory.model import Product

STATUS_NAME = "status.csv"              # the products' status list's old file name (the tests' fixtures)
# What to do when an incoming order or product's cards are all in the collection already.
RECEIVE_IT = ("receive it (on the Receipts page, or python -m decklab.db receive --order <id>) and take out "
              "the copies added for it on the Collection page")

PRODUCT_STATUSES = ("owned", "preordered", "ordered", "cancelled")
INCOMING = ("preordered", "ordered")    # not in collection.csv yet


@dataclass
class ProductStatus:
    """One row of magic/products/status.csv."""
    file: str
    status: str         # owned | preordered | ordered
    intact: bool        # still kept as its decks (counts only once owned)
    notes: str = ""
    sleeves: str = ""   # accessory id or free text; only meant while owned and intact
    deck_box: str = ""  # likewise


@dataclass
class InUse:
    """A deck holding physical cards: a built deck file or an intact product deck."""
    id: str             # deck id, as decks.load_deck() takes it
    title: str
    why: str            # "built" or "intact product"
    cards: Counter      # card name -> copies, basic lands left out
    standin_warnings: list = field(default_factory=list)  # known recipe mismatches a selected repack can repair
    # (name, set, collector number, finish) -> copies, of the lines that name a printing: which printings the
    # held copies probably are (the Card list's storage counts); cards is what counts, stand-ins included
    printings: Counter = field(default_factory=Counter)
    # Logical printing hints cannot locate copies replaced by, or used as, installed stand-ins.
    # Retain these canonical names while reading the existing recipe; allocation counts stay unchanged.
    standin_names: set = field(default_factory=set)
    printing_version: str = "target"   # list supplying printings, including the installed assembly snapshot
    planned_colors: list | None = None # canonical Planned identity, independent of the hint's source version
    # (name, set, collector number, finish) -> copies the deck's Printings in box line records
    # (lib/decks/printings.py), only the parts that can still be true; recorded_stale says why
    # the rest are ignored (the deck page's "Printings in box out of date")
    recorded: Counter = field(default_factory=Counter)
    recorded_stale: list = field(default_factory=list)


@dataclass
class Pool:
    """Everything owned vs needed is worked out from (see load_pool)."""
    owned: Counter                  # card name -> copies, on-the-way copies included
    on_the_way: dict                # card name -> [(source, copies)]
    in_use: list                    # [InUse]
    unresolved: dict = field(default_factory=dict)  # name as written -> {file, ...}
    warnings: list = field(default_factory=list)    # problems worth showing, as text
    space: str = spaces.HOME                        # whose pool this is (lib/spaces.py)
    incoming_sources: dict = field(default_factory=dict)  # card -> source details, in on_the_way order
    # warning text -> the deck id it is about (a deck's or product deck's own problem); every
    # other warning of home's pool is about its records (orders, products, status lines)
    warning_decks: dict = field(default_factory=dict)


# ------------------------------------------------------------------ reading

def _snapshot():
    """A block reading one inventory snapshot (decklab/lib/inventory): the request's or the
    command's when one is pinned already, else one pinned for the block, so a pool load (and the
    product decks it reads through decks) sees one revision and loads it once."""
    return contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned()


def _rows(source):
    """The rows of an inventory source as read (a Sheet's rows, a Product's items), raising what
    reading its file raised today when it isn't there or couldn't be read (inventory.unreadable)."""
    unreadable.check(source)
    return source.items if isinstance(source, Product) else source.rows


def _canonical(name, where, unresolved):
    """The exact Scryfall name for name. A name that doesn't resolve is kept
    as written and recorded in unresolved (name -> set of places)."""
    if decks.is_basic_land(name):
        return name
    exact = cards.resolve(name)
    if exact is None:
        # "Llanowar Elves (fdn)": a lowercase set with no collector number
        # stays in the name when a decklist line is parsed.
        m = re.fullmatch(r"(.+?)\s+\([A-Za-z0-9]{2,8}\)", name)
        exact = cards.resolve(m.group(1)) if m else None
    if exact is None:
        unresolved.setdefault(name, set()).add(where)
        return name
    return exact


def _count_printings(sections, where, unresolved):
    """Copies of each non-basic printing named in a decklist: (name, set, number, finish) -> copies."""
    counts = Counter()
    for lines in sections.values():
        for line in lines:
            name = _canonical(line.name, where, unresolved)
            if line.set and line.number and not decks.is_basic_land(name):
                counts[(name, line.set.lower(), str(line.number), line.finish or "nonfoil")] += line.quantity
    return counts


def _count_sections(sections, where, unresolved):
    """Copies of each non-basic card across every section of a decklist."""
    counts = Counter()
    for lines in sections.values():
        for line in lines:
            name = _canonical(line.name, where, unresolved)
            if not decks.is_basic_land(name):
                counts[name] += line.quantity
    return counts


def read_card_csv(source, unresolved, problems=None, owners=None):
    """Copies of each non-basic card in an inventory source with name and
    quantity columns: a collection, an order payload or a product list.

    A row with a bad quantity or no name raises ValueError, or, when a
    problems list is given, is described there and left out, named by its
    number in the database's words ("Row 2 of the home collection: ...",
    E11-S12). A source that isn't there or can't be read raises as its file
    did (see _rows). owners: as for inventory_paths.describe, so a payload's row names
    its order and component."""
    where = source.path
    counts = Counter()
    for n, row in enumerate(_rows(source), 1):
        name = (row.get("name") or "").strip()
        try:
            qty = int(row["quantity"])
            if qty <= 0:
                raise ValueError("quantity must be positive")
        except (KeyError, TypeError, ValueError):
            problem = f"{inventory_paths.row_of(where, n, owners)}: bad quantity {row.get('quantity')!r}"
        else:
            problem = None if name else f"{inventory_paths.row_of(where, n, owners)}: no card name"
        if problem:
            if problems is None:
                raise ValueError(problem)
            problems.append(problem)
            continue
        name = _canonical(name, where, unresolved)
        if not decks.is_basic_land(name):
            counts[name] += qty
    return counts


def read_printings(source):
    """Copies of each non-basic printing, (set, collector_number, finish) ->
    quantity, in a source with collection.csv's columns. Rows read_card_csv
    would refuse are skipped here; it reports them."""
    counts = Counter()
    for row in _rows(source):
        name = (row.get("name") or "").strip()
        try:
            qty = int(row["quantity"])
            if qty <= 0:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if name and not decks.is_basic_land(name):
            key = ((row.get("set") or "").strip().lower(),
                   (row.get("collector_number") or "").strip(),
                   (row.get("finish") or "nonfoil").strip().lower())
            counts[key] += qty
    return counts


def read_status(warnings=None):
    """{file name: ProductStatus} from the products' status list (magic/products/status.csv).

    Problems are appended to warnings as text. A row with an unknown status
    is treated as owned and not intact, which leaves the product out of every
    count, as if it weren't listed.
    """
    warnings = [] if warnings is None else warnings
    sheet = inventory.current().status
    if not sheet.exists:
        warnings.append(inventory_files.MISSING_STATUS)
        return {}
    out = {}
    for row in _rows(sheet):
        file = (row.get("file") or "").strip()
        owner = inventory_files.status_owner(file)
        status = (row.get("status") or "").strip().lower()
        intact = (row.get("intact") or "").strip().lower()
        if intact not in ("yes", "no", ""):
            warnings.append(f"{owner} has intact {intact!r}, not yes or no; treated as no")
        if status not in PRODUCT_STATUSES:
            warnings.append(f"{owner} is {status!r}, not one of "
                            f"{', '.join(PRODUCT_STATUSES)}; it is left out of every count")
            status, intact = "owned", "no"
        sleeves = (row.get("sleeves") or "").strip()
        deck_box = (row.get("deck_box") or "").strip()
        if (sleeves or deck_box) and not (status == "owned" and intact == "yes"):
            warnings.append(f"{owner} has sleeves or a deck box but the product isn't "
                            f"owned and kept intact; clear them, since its cards are stored unsleeved")
        out[file] = ProductStatus(file, status, intact == "yes", (row.get("notes") or "").strip(),
                                  sleeves, deck_box)
    return out


def _source_title(source, owners=None):
    """How a warning starts when it names an incoming source (E11-S12): "Order x's cards" (by the
    order and component owners says hold it, inventory_paths.payload_owners), "Product x's card
    list", never its old file."""
    return inventory_paths.title(inventory_paths.describe(source.path, owners))


def _product_file(inv, file_name):
    """The product whose card list is file_name ("fdc-wretched-ranks.csv"), or None."""
    return next((p for p in inv.products if p.file == file_name), None)


def _product_name(file_name):
    """A product's short name: "Calling All Angels" for fdc-calling-all-angels.csv."""
    stem = Path(file_name).stem
    return (inventory.current().product(stem) or Product(stem)).label("pool")


def load_pool(space=spaces.HOME):
    """Read the collection, orders, product statuses and decks into a Pool.

    space is the space whose pool it is (lib/spaces.py): a person's has only
    their collection and built decks (spaces.SpaceNotFound for a space
    config.json doesn't list). Everything comes from one inventory snapshot
    (see _snapshot)."""
    with _snapshot():
        if space != spaces.HOME:
            return _load_person_pool(spaces.get(space))
        return _load_pool()


def for_space(space, p=None):
    """p when it's space's pool, else that space's pool, newly loaded."""
    if p is not None and getattr(p, "space", spaces.HOME) == space:
        return p
    return load_pool() if space == spaces.HOME else load_pool(space)


def _load_person_pool(space):
    """A person's Pool: their collection (none yet is an empty one) and their built decks."""
    unresolved, warnings = {}, []
    owned = Counter()
    collection = inventory.current().collection(space.id)
    if collection.exists:
        owned = read_card_csv(collection, unresolved)
    about = {}
    in_use = _built_in_use(space.id, set(), set(), unresolved, warnings, about)
    return Pool(owned, {}, in_use, unresolved, warnings, space.id, warning_decks=about)


def _load_pool():
    inv = inventory.current()
    unresolved, warnings = {}, []
    collection = inv.collection(spaces.HOME)
    if collection.exists:
        owned = read_card_csv(collection, unresolved)
        collection_printings = read_printings(collection)
    else:                                   # a new install's empty collection, as a person's
        owned, collection_printings = Counter(), Counter()
    on_the_way, incoming_sources = {}, {}
    pending = {c.path: (order, c) for order, c in inv.components()
               if c.status == "pending" and c.kind in ("cards", "product")
               and all(isinstance(value, str) and value for value in (c.path, c.id, order.id))}

    # Pending cards and product components acknowledged as extra copies of printings already owned
    # (`order extra-copies`, rules.extra_copies): the guard below doesn't warn about them.
    extra = {c.path for order, c in inv.components()
             if c.status == "pending" and c.id in rules.extra_copies(order.audit_notes)}
    owners = inventory_paths.payload_owners(inv.orders)

    def incoming(source, label, status="ordered"):
        # A bad row or file here only leaves those cards out, with a warning,
        # as an unreadable product deck does: one typo in an order mustn't
        # stop every owned-vs-needed check.
        problems = []
        try:
            counts = read_card_csv(source, unresolved, problems, owners)
            listed = read_printings(source)
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            warnings.append(f"{_source_title(source, owners)} can't be read, so its cards aren't counted as on the way: {e}")
            return
        warnings.extend(f"{text}; that row isn't counted as on the way" for text in problems)
        order, component = pending.get(source.path, (None, None))
        product = source if isinstance(source, Product) else None
        source_name = product.label("shopping") if product else f"order {order.id}" if order else label
        details = {"source": source_name,
                   "order_id": order.id if order else None,
                   "component_id": component.id if component else None,
                   "product_id": product.stem if product else None, "status": status}
        for name, qty in counts.items():
            owned[name] += qty
            on_the_way.setdefault(name, []).append((label, qty))
            incoming_sources.setdefault(name, []).append(dict(details, quantity=qty))
        # Already added to the collection without a receipt? Then every card counts twice. (It
        # can also be an order for more copies of printings already owned: acknowledged as such,
        # in extra, it isn't warned about.)
        if listed and source.path not in extra                 and all(collection_printings[key] >= qty for key, qty in listed.items()):
            what = inventory_paths.describe(source.path, owners)      # "order x's cards" names its order
            what = what if label in what else f"{what} ({label})"
            warnings.append(f"every card in {what} is already in the collection; "
                            f"if it has arrived and been merged, {RECEIVE_IT}, or its cards count twice")

    # The pending card payloads (magic/orders/*.csv) by file name, whether or not a record names them.
    for path in inv.pending_payloads("cards"):
        incoming(inv.payloads[path], f"order {PurePosixPath(path).stem}")

    statuses = read_status(warnings)
    files = sorted(p.file for p in inv.products)
    for name in files:
        if name not in statuses:
            warnings.append(f"Product {Path(name).stem} has no status, so it counts as owned and not intact")
    for name, status in statuses.items():
        if name not in files:
            warnings.append(f"Product {Path(name).stem} has a status but no card list, so it isn't counted")
            continue
        if status.status in INCOMING:
            incoming(_product_file(inv, name), f"{_product_name(name)}, {status.status}", status.status)
            if status.intact:
                warnings.append(f"Product {Path(name).stem} is {status.status}: intact only counts once it's owned")

    # Decks holding cards: built deck files, and the decks of intact products.
    intact = {Path(name).stem for name, s in statuses.items()
              if name in files and s.status == "owned" and s.intact}
    found = set()
    about = {}
    in_use = _built_in_use(spaces.HOME, intact, found, unresolved, warnings, about)
    for stem in sorted(intact - found):
        warnings.append(f"Product {stem} is marked intact but has no deck lists, so nothing is held")

    return Pool(owned, on_the_way, in_use, unresolved, warnings, incoming_sources=incoming_sources,
                warning_decks=about)


def _planned_colors(parsed, sections, why):
    """Optional canonical deck identity from target sections already read for this holder."""
    target = sections if why == "intact product" else parsed.target if parsed is not None else None
    if target is None:
        return None                    # Never reload a target or substitute an owned/assembled list.
    try:
        return deck_colors(target)
    except (CardIdentityError, OSError, RuntimeError, EOFError, UnicodeDecodeError, json.JSONDecodeError, zlib.error):
        return None                    # Unavailable or damaged index data only removes the optional swatch.


def _built_in_use(space, intact, found, unresolved, warnings, decks_of=None):
    """[InUse] of a space's built deck files, and (home's) the decks of the
    intact products whose stems are in intact; found gets every product stem seen;
    decks_of (a dict) gets {warning text: the deck id it is about} of the warnings it adds."""
    in_use, records = [], {}
    for summary in decks.list_decks():
        before = len(warnings)
        try:
            if summary.get("space", spaces.HOME) != space:
                continue
            deck_id, source = summary["id"], summary["source"]     # a deck's id names it (a product's file)
            product = deck_id.split("/")[1] if deck_id.startswith("product/") else None
            if product:
                found.add(product)
            if summary.get("error"):
                warnings.append(f"{inventory_paths.place(source)} can't be read: {summary['error']}")
                continue
            if summary["status"] == "built":
                why, version = "built", None
            elif product in intact:
                why, version = "intact product", "target"
            else:
                continue
            try:
                from decklab.lib.decks import assembled
                stored = inventory.current().deck(deck_id) if why == "built" else None
                parsed = decks.parse_deck(stored.data, stored.slug, stored.kind, space=stored.space) if stored else None
                snapshot = assembled.get(parsed) if parsed is not None else None
                if snapshot:
                    sections, version = snapshot["sections"], snapshot["version"]
                else:
                    version = _built_version(summary, warnings) if why == "built" else version
                    sections = decks.load_deck(deck_id, version)
            except (decks.DeckNotFound, decks.DeckFileError, OSError) as e:
                warnings.append(f"{inventory_paths.place(source)} can't be read: {e}")
                continue
            held = _count_sections(sections, source, unresolved)
            standin_warnings, standin_names = [], set()
            if why == "built":
                from decklab.lib.decks import standins
                stored = inventory.current().deck(deck_id)
                if stored is not None:
                    try:
                        parsed = decks.parse_deck(stored.data, stored.slug, stored.kind, space=stored.space)
                        from decklab.lib.decks import assembled
                        sections = assembled.sections(parsed)
                        version = assembled.version(parsed)
                        held = _count_sections(sections, source, unresolved)
                        installed = standins.installed_for(parsed)
                        if installed:
                            if installed["version"] != version:
                                standin_warnings.append(f"{source}: installed stand-ins belong to another list version; repack this deck")
                            mappings = [{**row, "for": _canonical(row["for"], source, unresolved),
                                         "using": _canonical(row["using"], source, unresolved) if row["using"] else None}
                                        for row in installed["cards"]]
                            standin_names = {name for row in mappings for name in (row["for"], row["using"]) if name}
                            held = standins.physical_counts(held, mappings, standin_warnings, source)
                    except (decks.DeckFileError, standins.StandInsError) as error:
                        warnings.append(f"{source}: installed stand-ins can't be read: {error}")
                        continue
            warnings.extend(standin_warnings)
            if why == "built" and parsed is not None:
                from decklab.lib.decks import printings
                try:
                    lines = printings.printings(parsed)
                except decks.DeckFileError as error:
                    lines = []
                    records[deck_id] = error
                if lines:
                    records[deck_id] = lines
            in_use.append(InUse(deck_id, summary["title"], why, held, standin_warnings,
                                _count_printings(sections, source, unresolved), standin_names,
                                printing_version=version, planned_colors=_planned_colors(parsed, sections, why)))
        finally:
            if decks_of is not None:      # which deck each warning is about (Pool.warning_decks)
                decks_of.update((text, summary["id"]) for text in warnings[before:])
    if records:
        _recorded(space, in_use, records, unresolved)
    return in_use


def _recorded(space, in_use, records, unresolved):
    """Fill in_use's recorded and recorded_stale from records ({deck id: [PrintingLine] or the
    DeckFileError its line gave}). Never a pool warning: a stale record blocks nothing."""
    from decklab.lib.decks import printings
    canon = lambda name: _canonical(name, "Printings in box", {})   # noqa: E731
    try:
        owned = printings.capacity(_rows(inventory.current().collection(space)), canon)
    except (OSError, UnicodeDecodeError, csv.Error, RuntimeError):
        owned = {}
    by_id = {item.id: item for item in in_use}
    readable = {deck_id: lines for deck_id, lines in records.items() if isinstance(lines, list)}
    kept, stale = printings.effective(readable, {deck_id: by_id[deck_id].cards for deck_id in readable},
                                      owned, canon)
    for deck_id, lines in records.items():
        item = by_id.get(deck_id)
        if item is None:
            continue
        if not isinstance(lines, list):
            item.recorded_stale = [f"The Printings in box line can't be read: {lines}"]
            continue
        item.recorded = kept.get(deck_id, Counter())
        item.recorded_stale = stale.get(deck_id, [])


def _printing_rows(source):
    """((set, collector_number, finish), quantity) for each readable row of a
    source with collection.csv's columns, basic lands included."""
    for row in _rows(source):
        try:
            qty = int(row["quantity"])
            if qty <= 0:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        set_code = (row.get("set") or "").strip().lower()
        if set_code and (row.get("name") or "").strip():
            yield (set_code, (row.get("collector_number") or "").strip(),
                   (row.get("finish") or "nonfoil").strip().lower()), qty


def printing_counts(space=spaces.HOME):
    """{(set, collector_number, finish): {"owned": copies in collection.csv,
    "on_the_way": copies in order files and preordered or ordered products}},
    for the editor's printing picker. Basic lands count here (collection.csv
    lists the special ones). A file that can't be read is skipped: this only
    helps pick a printing, the owned-vs-needed counts come from load_pool().
    A person's space counts only their collection (nothing is on the way)."""
    with _snapshot():
        inv = inventory.current()
        counts = {}

        def add(source, key):
            try:
                for printing, qty in _printing_rows(source):
                    counts.setdefault(printing, {"owned": 0, "on_the_way": 0})[key] += qty
            except (OSError, UnicodeDecodeError, csv.Error):
                pass

        if space != spaces.HOME:
            spaces.get(space)                   # SpaceNotFound for a space config.json doesn't list
            add(inv.collection(space), "owned")
            return counts
        add(inv.collection(spaces.HOME), "owned")
        for path in inv.pending_payloads("cards"):
            add(inv.payloads[path], "on_the_way")
        for name, status in read_status([]).items():
            product = _product_file(inv, name)
            if status.status in INCOMING and product is not None:
                add(product, "on_the_way")
        return counts


def _built_version(summary, warnings):
    """Which list a built deck file holds: its Built version field when the
    file has that list, else the owned-only list if it has one."""
    version, lists = summary.get("built_version"), summary["versions"]
    if version is None and "owned" in lists:
        written = summary.get("built_version_text")
        if written is None:
            problem = "has no 'Built version' field saying which list is built"
        else:
            problem = f"has 'Built version: {written}', which isn't target or owned-only"
        # The lists by the page's names (Planned, Play-now); the field's values stay as written.
        warnings.append(f"{summary['source']} is built but {problem}; counting its Play-now "
                        f"list as in use")
        return "owned"
    if version == "owned" and "owned" not in lists:
        warnings.append(f"{summary['source']} has 'Built version: owned-only' but no Play-now "
                        f"list; counting its Planned list as in use")
        return "target"
    return version or "target"


# ----------------------------------------------------------- owned vs needed

def self_ids(deck_id):
    """The in-use ids that are this deck: the id itself, plus both halves of a
    Beginner Box pairing (in either order)."""
    deck_id = inventory.resolve_deck_id(deck_id)
    ids = {deck_id}
    if deck_id.startswith("pairing/"):
        pair = decks.find_summary(deck_id)
        if pair is not None:
            ids.update(pair["halves"])
    return ids


def free_copies(pool, exclude=()):
    """Card name -> copies free for a deck: owned (on the way included) less the copies the other
    built decks and intact products hold (exclude: the in-use ids that are this deck, self_ids, so
    its own built copies count as free). Basic lands and names with none free are left out."""
    exclude = set(exclude)
    held = Counter()
    for d in pool.in_use:
        if d.id not in exclude:
            held.update(d.cards)
    out = Counter()
    for name, qty in pool.owned.items():
        spare = qty - held.get(name, 0)
        if spare > 0 and not decks.is_basic_land(name):
            out[name] = spare
    return out


def _printing_label(price):
    """"NCC 316" for the priced printing, plus the finish when it isn't non-foil."""
    if price is None:
        return None
    finish = "" if price.finish == "nonfoil" else f" {price.finish}"
    return f"{price.set.upper()} {price.collector_number}{finish}"


def compare(sections, pool, exclude=(), prices=True):
    """Owned vs needed for a decklist {section: [DeckLine]} against a Pool.

    exclude holds the in-use deck ids that are this deck (see self_ids), so an
    unsaved list from the editor can be checked too. Returns the dict that
    owned_vs_needed() describes, without deck_id and version.
    """
    exclude = set(exclude)
    unresolved = {}
    need = _count_sections(sections, "decklist", unresolved)
    others = [d for d in pool.in_use if d.id not in exclude]

    result = {"rate": None, "rate_date": None, "price_date": None, "price_error": None}
    if prices:
        try:
            rate, rate_date = cards.usd_to_aud()
            price_date = cards.price_date()
            # AGENTS.md: a price is shown with the date it was pulled, and the
            # stamp above a deck file's table must read back.
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(rate_date)):
                raise RuntimeError(f"the USD->AUD rate has no usable date ({rate_date!r})")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(price_date)):
                raise RuntimeError(f"the card index doesn't say when Scryfall's prices were pulled "
                                   f"({price_date!r}). Run: python -m decklab.lib.cards update --force")
            result.update(rate=rate, rate_date=rate_date, price_date=price_date)
        except RuntimeError as e:          # offline with no cached rate, or no price date
            result["price_error"] = str(e)
            prices = False

    rows, conflicts = [], []
    for name, needed in need.items():
        owned = pool.owned.get(name, 0)
        coming = pool.on_the_way.get(name, [])
        used = [(d.title, d.cards[name]) for d in others if d.cards.get(name)]
        available = max(owned - sum(qty for _, qty in used), 0)
        missing = max(needed - available, 0)
        price = cards.price_aud(name) if prices and name not in unresolved else None
        rows.append({
            "name": name,
            "need": needed,
            "owned": owned,                     # on-the-way copies included
            "on_the_way": sum(qty for _, qty in coming),
            "on_the_way_from": list(coming),    # [(source, copies)]
            "incoming_sources": [dict(source) for source in pool.incoming_sources.get(name, [])],
            "in_use_elsewhere": used,           # [(deck title, copies)]
            "available": available,
            "missing": missing,
            "aud_each": price.aud if price else None,
            "aud_missing": round(price.aud * missing, 2) if price else None,
            "priced_printing": _printing_label(price),
            "priced_finish": price.finish if price else None,
        })
        if used:
            conflicts.append({
                "name": name, "need": needed, "owned": owned, "available": available,
                "missing": missing,
                # copies missing only because other decks hold them
                "short": missing - max(needed - owned, 0),
                "decks": used,
            })
    rows.sort(key=lambda r: (r["missing"] == 0, r["name"]))
    conflicts.sort(key=lambda c: c["name"])

    buying = [r for r in rows if r["missing"]]
    result.update(
        rows=rows,
        totals={
            "cards": len(rows),
            "need": sum(r["need"] for r in rows),
            "missing": sum(r["missing"] for r in buying),
            "aud_missing": round(sum(r["aud_missing"] or 0 for r in buying), 2) if prices else None,
            "unpriced": [r["name"] for r in buying if r["aud_each"] is None] if prices else [],
        },
        conflicts=conflicts,
        unresolved=sorted({(name, where) for name, places in unresolved.items() for where in places}
                          | {(name, where) for name, places in pool.unresolved.items() for where in places}),
        warnings=list(pool.warnings),
    )
    return result


def owned_vs_needed(deck_id, version="target", pool=None, prices=True):
    """Owned vs needed for one deck in the library.

    Returns a dict:
      deck_id, version
      rows: one dict per non-basic card, cards with something missing first,
            then by name: name, need, owned (on the way included), on_the_way,
            on_the_way_from [(source, copies)], incoming_sources (parallel
            source details: source, quantity, order_id, component_id,
            product_id, status ordered/preordered), in_use_elsewhere [(deck title,
            copies)], available, missing, aud_each, aud_missing and
            priced_printing ("NCC 316", or "M20 282 foil" for a card with no
            non-foil price) and priced_finish; the prices are None without a price.
      totals: cards, need, missing, aud_missing, unpriced (missing cards with
            no price)
      rate, rate_date, price_date: the USD->AUD rate, its ECB date and the date
            Scryfall's prices were pulled; price_error says why they're None
      conflicts: cards this deck needs that other built or intact decks hold:
            name, need, owned, available, missing, short (copies missing only
            because of those decks) and decks [(deck title, copies)]
      unresolved: [(name, where)] for names that aren't Scryfall card names
      warnings: problems found reading the pool, as text

    The pool is the deck's space's: one for another space (or None) is
    replaced by for_space().

    Raises decks.DeckNotFound for an unknown deck or version, and
    decks.DeckFileError for a deck file that can't be read.
    """
    sections = decks.load_deck(deck_id, version)
    pool = for_space(spaces.space_of(deck_id), pool)
    result = {"deck_id": deck_id, "version": version}
    result.update(compare(sections, pool, self_ids(deck_id), prices))
    return result


def row_labels(r):
    """What one result row's labels say, as data (see table_rows):
    {"on_the_way": [(source, copies)], "in_use": [(deck title, copies)]}.
    on_the_way counts only the copies this deck counts on that haven't
    arrived; in_use is filled only when other decks leave it short. The page
    shows these next to the owned-vs-needed table, so it agrees with the deck
    file's Notes cells."""
    on_the_way = []
    held = sum(qty for _, qty in r["in_use_elsewhere"])
    arrived = max(r["owned"] - r["on_the_way"] - held, 0)   # copies here now and free
    waiting = max(r["need"] - r["missing"] - arrived, 0)     # usable copies still on the way
    for source, qty in r["on_the_way_from"]:
        if waiting <= 0:
            break
        on_the_way.append((source, min(qty, waiting)))
        waiting -= qty
    short = r["missing"] > max(r["need"] - r["owned"], 0)     # short because of other decks
    return {"on_the_way": on_the_way, "in_use": list(r["in_use_elsewhere"]) if short else []}


def _labels(r):
    """The Notes labels for one result row (see table_rows)."""
    parts = row_labels(r)
    return tuple([f"{qty} on the way ({source})" for source, qty in parts["on_the_way"]]
                 + [f"{qty} in use in {title}" for title, qty in parts["in_use"]])


def table_rows(result):
    """(rows, total, prices) for decks.set_table, in the deck files' format and order.

    result must be for a target list (see deck_table): the table in a deck
    file always describes that, so an owned-only result raises ValueError.

    Owned is the copies this deck can use (owned, on the way included, minus
    copies other decks hold), capped at Need, so Missing = Need - Owned as in
    the existing tables. Prices are filled in only for cards with something
    missing; a foil or etched price (for a card with no non-foil price) says
    so, one with no price says "no price", and the total row's notes name the
    cards its total leaves out. Without prices (price_error, or prices=False)
    the price cells of cards with something missing are None, so set_table
    keeps the old ones that still apply.

    Each row's labels say how many of its copies are still on the way, from
    which orders or products ("1 on the way (order 2026-09-29-shop-a)"), and
    for a card that's short because other decks hold it, how many each of
    those decks holds ("2 in use in Gruul Ramp"); set_table puts them in
    place of the old labels and keeps any hand-written notes.

    prices is the decks.PriceStamp (rate and dates) the prices were worked
    out with, or None when the result has no prices.
    """
    if result.get("version", "target") != "target":
        raise ValueError("a deck file's owned-vs-needed table describes its target list, "
                         f"not the {result['version']} list")
    priced = result["rate"] is not None
    rows = []
    for r in result["rows"]:
        if not r["missing"]:
            each, missing = "", ""
        elif not priced:
            each, missing = None, None
        elif r["aud_each"] is not None:
            each, missing = decks.format_aud(r["aud_each"]), decks.format_aud(r["aud_missing"])
            if r["priced_finish"] != "nonfoil":
                each += f" ({r['priced_finish']})"
        else:
            each, missing = "no price", ""
        rows.append(decks.TableRow(r["name"], r["need"], r["need"] - r["missing"], r["missing"],
                                   each, missing, labels=_labels(r)))
    totals = result["totals"]
    aud = totals["aud_missing"]
    if not totals["missing"]:
        aud = ""
    elif priced:
        aud = decks.format_aud(aud)
    # Without prices it isn't known which cards have none: leave the old label.
    labels = (f"not counted, no price: {', '.join(totals['unpriced'])}",) if totals["unpriced"] else ()
    total = decks.TotalRow(totals["missing"], aud, labels=labels if priced else None)
    stamp = decks.PriceStamp(result["rate"], result["rate_date"], result["price_date"]) if priced else None
    return decks.sort_table_rows(rows), total, stamp


def deck_table(deck, pool=None, prices=True):
    """(rows, total, prices) for decks.set_table(deck, ...), worked out from
    deck.target as it is in memory, so an edit that isn't saved yet counts.
    deck is a decks.DeckFile; pool defaults to load_pool() of the deck's
    space (another space's is replaced, see for_space). Raises
    decks.DeckFileError for a file with no "## Decklist" block."""
    if not deck.has_decklist:
        raise decks.DeckFileError(f"{deck.deck_id}: {decks.NO_DECKLIST}")
    pool = for_space(deck.space, pool)
    result = compare(deck.target, pool, self_ids(deck.deck_id), prices)
    return table_rows(result)


def table_changes(deck, pool=None):
    """How a deck file's owned-vs-needed table differs from what the pool
    gives now (decks.table_changes: Need, Owned, Missing and Deck Lab's labels;
    prices don't count). [] when it matches, and for a file with no table or
    no "## Decklist" block."""
    if deck.rows is None or not deck.has_decklist:
        return []
    rows, _, _ = deck_table(deck, pool, prices=False)
    return decks.table_changes(deck, rows)


def stale_tables(pool=None, exclude=(), only=None):
    """Deck files whose owned-vs-needed table no longer matches the pool, as
    [{"id", "title", "sha256", "count", "changes"}] in library order (see
    table_changes). A save can cause this in other files: a built deck's list,
    status or built version changes what they can use. Files Deck Lab can't
    write (a name that isn't a slug, a file that can't be read) and ids in
    exclude are left out. Every space's decks are checked (only: just these
    spaces'), each against its own space's pool (pool is used for its space,
    the others are loaded); a space whose pool can't be loaded is left out
    (table_blockers names it)."""
    pools = {} if pool is None else {pool.space: pool}
    wanted = None if only is None else set(only)
    out = []
    with _snapshot():
        for space, path in decks._space_files():
            if wanted is not None and space not in wanted:
                continue
            deck_id = spaces.join_deck_id(space, path.parent.name, path.stem)
            if deck_id in exclude or not decks.valid_slug(path.stem):
                continue
            try:
                deck = decks.read_deck_file(path, space=space)
            except (decks.DeckFileError, OSError):
                continue
            if space not in pools:
                try:
                    pools[space] = for_space(space)
                except Exception:       # noqa: BLE001 - one person's unreadable pool hides only their decks
                    pools[space] = None
            if pools[space] is None:
                continue
            changes = table_changes(deck, pools[space])
            if changes:
                out.append({"id": deck_id, "title": deck.title, "sha256": deck.sha256,
                            "count": len(changes), "changes": changes})
    return out


def table_blockers(pool=None, only=None):
    """What stops deck tables (and an inventory change's refresh) refreshing the owned-vs-needed
    tables: {"decks": [...], "spaces": [...]}, every problem, in library order; never raises.
    pool: a Pool already loaded, used for its own space; only: just these spaces. The shapes
    and checks are inventory/refresh.py's table_blockers (the refresh's own, so they can't
    drift)."""
    from decklab.lib.inventory import refresh
    return refresh.table_blockers(pool, only)


# ------------------------------------------------------------- command line

def _print_pool(p):
    coming = Counter()
    for sources in p.on_the_way.values():
        for source, qty in sources:
            coming[source] += qty
    print(f"Owned: {sum(p.owned.values())} cards, {len(p.owned)} different "
          f"(basic lands left out), including {sum(coming.values())} on the way:")
    for source, qty in sorted(coming.items()):
        print(f"  {qty:>4}  {source}")
    print(f"In use: {len(p.in_use)} decks")
    for d in p.in_use:
        print(f"  {sum(d.cards.values()):>4}  {d.title} ({d.why})")
    _print_problems(sorted((n, w) for n, ws in p.unresolved.items() for w in ws), p.warnings)


def _print_problems(unresolved, warnings):
    for name, where in unresolved:
        print(f"Not a Scryfall card name: {name!r} ({where})")
    for text in warnings:
        print(f"Warning: {text}")


def _money(value):
    return "" if value is None else f"{value:.2f}"


def _print_result(r):
    print(f"{r['deck_id']} ({r['version']} list)")
    width = max([len(row["name"]) for row in r["rows"]] + [4])
    print(f"{'Card':<{width}}  Need  Owned  Coming  Used  Missing  A$ each  A$ missing")
    for row in r["rows"]:
        used = sum(qty for _, qty in row["in_use_elsewhere"])
        # A card with no non-foil price is priced in foil or etched; say so.
        finish = f"  ({row['priced_finish']} price)" if row["priced_finish"] not in (None, "nonfoil") else ""
        print(f"{row['name']:<{width}}  {row['need']:>4}  {row['owned']:>5}  {row['on_the_way']:>6}  "
              f"{used:>4}  {row['missing']:>7}  {_money(row['aud_each']):>7}  "
              f"{_money(row['aud_missing']) if row['missing'] else '':>10}{finish}")
    t = r["totals"]
    print(f"{t['cards']} cards, {t['need']} copies needed, {t['missing']} missing"
          + (f", about A${t['aud_missing']:.2f} to buy" if t["aud_missing"] is not None else ""))
    if t["unpriced"]:
        print("No price for: " + ", ".join(t["unpriced"]))
    if r["rate"] is not None:
        print(f"AUD estimates: Scryfall prices of {r['price_date']}, 1 USD = {r['rate']} AUD "
              f"(ECB {r['rate_date']}).")
    elif r["price_error"]:
        print(f"No prices: {r['price_error']}")
    for row in r["rows"]:
        for source, qty in row["on_the_way_from"]:
            print(f"On the way: {qty} {row['name']} ({source})")
    for c in r["conflicts"]:
        held = ", ".join(f"{title} x{qty}" for title, qty in c["decks"])
        print(f"In use elsewhere: {c['name']}: {held}"
              + (f" (leaves this deck {c['short']} short)" if c["short"] else ""))
    _print_problems(r["unresolved"], r["warnings"])


def main(argv=None):
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="python -m decklab.lib.pool",
                                     description="Owned vs needed, counting the shared card pool.")
    parser.add_argument("deck", nargs="?", help="deck id, e.g. casual/gruul-ramp, pairing/cats+elves "
                                                "or user2/casual/elves")
    parser.add_argument("--owned", action="store_true", help="use the owned-only list")
    parser.add_argument("--no-prices", action="store_true", help="skip the AUD estimates")
    parser.add_argument("--space", default=spaces.HOME,
                        help="whose pool to show with no deck: home (default) or a person's space")
    args = parser.parse_args(argv)
    with entry.command():           # the venv, and one inventory snapshot for the command
        try:
            p = load_pool(spaces.space_of(args.deck) if args.deck else args.space)
            if not args.deck:
                _print_pool(p)
                return 0
            result = owned_vs_needed(args.deck, "owned" if args.owned else "target", p,
                                     prices=not args.no_prices)
        except (decks.DeckNotFound, spaces.SpaceNotFound) as e:
            print(e)
            return 1
        except inventory.Unavailable as e:
            print(e, file=sys.stderr)
            return 2
        except (FileNotFoundError, RuntimeError, ValueError) as e:
            # No card index yet (or an old one), or a file that can't be read,
            # such as a bad row in collection.csv or a deck with no decklist block.
            print(e, file=sys.stderr)
            return 1
        _print_result(result)
        return 0


if __name__ == "__main__":
    sys.exit(main())
