"""The inventory as one immutable snapshot: the shape both backends produce (files.py from the
magic/ files, the database backend from its tables) and every reader works from.

Raw first (the phase 3 design's amendment Q1). A row keeps the strings its file holds, in the
file's column order: nothing is converted or cleaned when it's read, so each reader can still do
its own strip, lower-casing and int() and word its own problems exactly as it does today. A value
is None only where the file has no cell (a column the file lacks, or a short row), as
csv.DictReader gives it; the database backend always has every cell. Typed values come from
accessors that return None when the text isn't valid (CardRow.qty, TokenRow.qty, ...).

    Inventory
      revision      str: changes whenever any inventory file or row changes
      collections   {space: Sheet of CardRow}      a space's collection.csv
      tokens        {space: Sheet of TokenRow}     a space's tokens.csv
      locations     {space: Sheet of LocationRow}  a space's locations.csv (E8-S22): where its
                                                   collection rows' storage copies are, one row per
                                                   located (set, collector_number, finish); none
                                                   for a row with no location
      imports       {space: (ImportInfo, ...)}     names and sizes of its raw imports, no content
      status        Sheet of StatusRow             products/status.csv (its own rows: a status
                                                   row needs no product file, nor a file a row)
      products      (Product, ...)                 the product card lists, by file name
      orders        (Order, ...)                   the order records, by file name (= id)
      payloads      {path: Sheet}                  every order payload file, cards (CardRow) or
                                                   tokens (TokenRow), wherever it is (pending,
                                                   received/, cancelled/), by path
      watchlist     Sheet of WatchRow
      decks_revision  str: changes whenever a deck file, accessories.csv or a picture changes
      decks         {deck id: Deck}                every deck file (phase 4), in every space
      accessories   Sheet of AccessoryRow          magic/accessories.csv
      accessory_images  {file name: ImageMeta}     its pictures' sizes and sha256s (no bytes)
      locations_ready  whether the backend can save locations (the database: migration 0016)
      backend       "files" or "db";  stale: None, or the warning to show while the database
                    backend serves its last good snapshot because the database isn't reachable

A Sheet is one CSV-shaped source: path (derived, see paths.py), columns (the header as read),
rows, exists, error (why it couldn't be read at all: not UTF-8, not CSV, or the OS refused to read
it, such as a file another program has locked), problems (today's texts for rows a lenient reader
leaves out, with the line numbers they cite: see files.py for each source's), strict_error (the
first problem a strict read, the writers', finds) and csv_error (what csv.DictReader(strict=True),
as purchases reads payloads, products and status.csv, raises; None when it reads cleanly). Rows
have a line (where the file has them; 0 otherwise) and, for tokens and the watchlist, a hidden id
that stays with a row across edits; neither counts in equality, so the same data from either
backend compares equal.

Two rules for every reader (the foundation review):
- A TokenSet's rows are only the rows tokens.read() keeps: a row that breaks the token rules is
  only in problems. So never rewrite tokens.csv from rows alone while it has problems (the
  writers refuse: changes.check).
- Read a cell with row.text(column) ("" when the file has no cell) unless None matters: a short
  row or a column the file lacks gives None from get().

Readers return lists and dicts exactly as today, never these tuples: convert (list(...),
row.as_dict(), order.record()).

Phase 4's deck parts (the phase 4 design's R1 and R2) have a revision of their own,
decks_revision: a deck save never moves the inventory's revision (which receipt previews and
expected_revision fingerprint), and an inventory change moves decks_revision only when it
changed a deck too (the deck-table refresh). A Deck holds its file's exact text (the bytes
decoded as UTF-8, line endings and a byte order mark kept), so its sha256 (the pages'
concurrency token) is the sha256 of the bytes, as today; never a parse (readers call
decks.parse_deck on the text each time: a DeckFile is mutable). A picture is its ImageMeta
(size, sha256): the bytes are fetched from the backend by name (backend.image(name)), never held
in a snapshot, except the bytes an operation is writing (with_image).

Nothing in a snapshot can be changed in place: rows, sheets and products are frozen, the
snapshot's mappings are read-only views, and an order's components are copies. An order's data
is still a dict (json and the readers need one): never change it, take order.record() (a copy);
the backends hand an operation its own copy of every record anyway (changes.detach). The write
helpers at the end of Inventory (with_collection, with_tokens, with_status_rows, with_watchlist,
with_order, with_product, update_component, move_component, set_component_rows) make the new
snapshot an operation returns, the way every writer leaves it.
"""
import copy
import dataclasses
import hashlib
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Mapping

from . import paths, rules

INCOMING = ("preordered", "ordered")         # product statuses not in a collection yet
PREVIEW = "~preview"                         # the end of a preview's revision (never saved)
QUEUE_FIELDS = ("name", "set", "collector_number", "finish", "quantity", "for",
                "printing", "listed_aud", "listed_at", "in_stock", "checked", "notes",
                "state", "source")                # purchases.QUEUE_FIELDS


def name_order(name):
    """The order file names are listed in (products, records, payloads): as today's readers
    sort Paths on Windows, case-insensitively, then by the name itself so the order is total."""
    return (name.casefold(), name)


def _int(value, minimum=1):
    """int(value) as today's readers take it (Python's int(): surrounding spaces allowed), or
    None when it isn't a whole number of at least minimum."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= minimum else None


# ------------------------------------------------------------------ rows

@dataclass(frozen=True)
class Row:
    """One CSV row as read: values are (column, value) pairs in the file's column order (value
    None for a cell a short row lacks), overflow the cells past the header (csv.DictReader's
    restkey list). line is the file line the row starts on (the header is line 1; 0 when it
    didn't come from a file) and id a stable identity (tokens and the watchlist; 0 elsewhere):
    neither counts in equality."""
    values: tuple = ()
    overflow: tuple = ()
    line: int = field(default=0, compare=False)
    id: int = field(default=0, compare=False)

    COLUMNS = ()                     # the file's standard columns

    @classmethod
    def make(cls, mapping=None, columns=None, *, line=0, id=0, **values):
        """A row with columns (the class's standard ones by default), each value from mapping or
        the keyword arguments, "" when neither has it; None values become ""."""
        source = dict(mapping or {}, **values)
        columns = tuple(columns or cls.COLUMNS)
        return cls(tuple((c, "" if source.get(c) is None else str(source.get(c))) for c in columns),
                   line=line, id=id)

    def get(self, key, default=None):
        """The value of column key (the last one, for a header naming it twice, as
        csv.DictReader does), None for a cell a short row lacks, default when there's no such
        column."""
        found = default
        for column, value in self.values:
            if column == key:
                found = value
        return found

    def __getitem__(self, key):
        missing = object()
        value = self.get(key, missing)
        if value is missing:
            raise KeyError(key)
        return value

    def __contains__(self, key):
        return any(column == key for column, _ in self.values)

    def columns(self):
        return tuple(column for column, _ in self.values)

    def as_dict(self):
        """{column: value} as csv.DictReader gives it (overflow under the key None)."""
        out = dict(self.values)
        if self.overflow:
            out[None] = list(self.overflow)
        return out

    def text(self, key):
        """The value of column key as text: "" when the file has no cell for it."""
        value = self.get(key)
        return "" if value is None else value

    def replace(self, **changes):
        """A copy with these columns set (a column the row lacks is added at the end); line and
        id are kept."""
        values = [(c, str(changes.pop(c)) if c in changes else v) for c, v in self.values]
        values += [(c, str(v)) for c, v in changes.items()]
        return dataclasses.replace(self, values=tuple(values))


class CardRow(Row):
    """A collection.csv row (also a cards payload's): name, set, collector_number, finish,
    quantity, condition, language, notes."""
    COLUMNS = tuple(rules.FIELDS)

    name = property(lambda self: self.get("name"))
    set = property(lambda self: self.get("set"))
    collector_number = property(lambda self: self.get("collector_number"))
    finish = property(lambda self: self.get("finish"))
    quantity = property(lambda self: self.get("quantity"))
    condition = property(lambda self: self.get("condition"))
    language = property(lambda self: self.get("language"))
    notes = property(lambda self: self.get("notes"))

    @property
    def qty(self):
        """The quantity as today's pool takes it (int(), at least 1), or None."""
        return _int(self.get("quantity"))


class TokenRow(Row):
    """A tokens.csv row (also a tokens payload's), in rules.TOKEN_FIELDS."""
    COLUMNS = tuple(rules.TOKEN_FIELDS)

    front = property(lambda self: self.get("front"))
    back = property(lambda self: self.get("back"))
    set = property(lambda self: self.get("set"))
    front_collector_number = property(lambda self: self.get("front_collector_number"))
    back_collector_number = property(lambda self: self.get("back_collector_number"))
    finish = property(lambda self: self.get("finish"))
    quantity = property(lambda self: self.get("quantity"))
    front_details = property(lambda self: self.get("front_details"))
    back_details = property(lambda self: self.get("back_details"))
    notes = property(lambda self: self.get("notes"))

    @property
    def qty(self):
        return _int(self.get("quantity"))


class WatchRow(Row):
    """A watchlist.csv row, in QUEUE_FIELDS (the column "for" is for_deck here)."""
    COLUMNS = QUEUE_FIELDS

    name = property(lambda self: self.get("name"))
    set = property(lambda self: self.get("set"))
    collector_number = property(lambda self: self.get("collector_number"))
    finish = property(lambda self: self.get("finish"))
    quantity = property(lambda self: self.get("quantity"))
    for_deck = property(lambda self: self.get("for"))
    printing = property(lambda self: self.get("printing"))
    listed_aud = property(lambda self: self.get("listed_aud"))
    listed_at = property(lambda self: self.get("listed_at"))
    in_stock = property(lambda self: self.get("in_stock"))
    checked = property(lambda self: self.get("checked"))
    notes = property(lambda self: self.get("notes"))
    state = property(lambda self: self.get("state"))
    source = property(lambda self: self.get("source"))

    @property
    def qty(self):
        return _int(self.get("quantity"))


class StatusRow(Row):
    """A products/status.csv row, including the optional packed-token record.
    Legacy rows lack kit or token columns: get() gives None for missing columns."""
    COLUMNS = tuple(rules.STATUS_FIELDS)

    file = property(lambda self: self.get("file"))
    status = property(lambda self: self.get("status"))
    intact = property(lambda self: self.get("intact"))
    sleeves = property(lambda self: self.get("sleeves"))
    deck_box = property(lambda self: self.get("deck_box"))
    token_cards = property(lambda self: self.get("token_cards"))
    notes = property(lambda self: self.get("notes"))


class LocationRow(Row):
    """A locations.csv row: a collection row's identity key and its storage location (E8-S22)."""
    COLUMNS = tuple(rules.LOCATION_FIELDS)

    set = property(lambda self: self.get("set"))
    collector_number = property(lambda self: self.get("collector_number"))
    finish = property(lambda self: self.get("finish"))
    location = property(lambda self: self.get("location"))

    @property
    def key(self):
        return (self.text("set"), self.text("collector_number"), self.text("finish"))


class AccessoryRow(Row):
    """An accessories.csv row, in rules.ACCESSORY_FIELDS (a file with an older header has fewer
    columns: get() gives None for those)."""
    COLUMNS = tuple(rules.ACCESSORY_FIELDS)

    kind = property(lambda self: self.get("kind"))
    owner = property(lambda self: self.get("owner"))
    name = property(lambda self: self.get("name"))
    image = property(lambda self: self.get("image"))

    @property
    def accessory_id(self):
        """The row's id column (Row.id is the hidden identity, unused for accessories)."""
        return self.get("id")


class ProductItem(Row):
    """One row of a product card list, in that product's own columns (deck or section, name,
    set, collector_number, finish, quantity, rarity, in_play_boosters, notes: whichever it has)."""
    name = property(lambda self: self.get("name"))
    set = property(lambda self: self.get("set"))
    collector_number = property(lambda self: self.get("collector_number"))
    finish = property(lambda self: self.get("finish"))
    quantity = property(lambda self: self.get("quantity"))
    section = property(lambda self: self.get("section"))
    deck = property(lambda self: self.get("deck"))
    rarity = property(lambda self: self.get("rarity"))
    notes = property(lambda self: self.get("notes"))

    @property
    def qty(self):
        return _int(self.get("quantity"))


# ------------------------------------------------------------------ sources

@dataclass(frozen=True)
class Sheet:
    """One CSV-shaped source (see the module docstring). rows are Row subclasses; columns the
    header as read (None for a missing or empty file); sorted whether the rows are in the file's
    own sort order (tokens.csv's TOKEN_SORT; True elsewhere)."""
    path: str
    columns: tuple | None = None
    rows: tuple = ()
    exists: bool = False
    error: str | None = None
    problems: tuple = ()
    strict_error: str | None = None
    sorted: bool = True
    csv_error: str | None = None

    @property
    def lines(self):
        """The line each row starts on."""
        return tuple(row.line for row in self.rows)

    @property
    def readable(self):
        return self.exists and self.error is None


CardSet = Sheet          # the design's names for a collection's and a token inventory's sheets
TokenSet = Sheet


@dataclass(frozen=True)
class ImportInfo:
    """A raw import's metadata, with no content. Provenance is unknown for legacy files;
    supplementary metadata doesn't change the files/database model's identity."""
    name: str
    size: int
    sha256: str | None = field(default=None, compare=False)
    imported_at: str | None = field(default=None, compare=False)
    imported_by: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Product:
    """A product's card list. name and format are the display name and deck format it's known
    by (the database's; files.PRODUCT_NAMES's in a snapshot built from files), None when
    there's none: each reader keeps its own fallback (label()). error, problems and strict_error
    as a Sheet's."""
    stem: str
    columns: tuple | None = None
    items: tuple = ()
    name: str | None = None
    format: str | None = None
    error: str | None = None
    problems: tuple = ()
    strict_error: str | None = None
    csv_error: str | None = None

    @property
    def file(self):
        return f"{self.stem}.csv"

    @property
    def path(self):
        return paths.product(self.stem)

    @property
    def is_deck(self):
        """Whether the product reads as decks: a deck or section column (decks._product_lines'
        rule). None when the file couldn't be read (error): today
        decks._product_decks still lists such a file, with its error, so a reader must look at
        error before it skips a product that isn't a deck."""
        if self.error is not None:
            return None
        columns = self.columns or ()
        return "deck" in columns or "section" in columns

    def label(self, style):
        """The product's name as each reader words it when there's no display name:
        "deck"     (name, format) as decks._product_decks: the title-cased stem, "Product deck";
        "shopping" the name as purchases._contents: the title-cased stem;
        "pool"     the short name as pool._product_name: the name (else the stem) up to " (".
        """
        title = self.stem.replace("-", " ").title()
        if style == "deck":
            return (self.name if self.name is not None else title,
                    self.format if self.format is not None else "Product deck")
        if style == "shopping":
            return self.name if self.name is not None else title
        if style == "pool":
            return (self.name if self.name is not None else self.stem).split(" (")[0]
        raise ValueError(f"unknown label style {style!r}")


@dataclass(frozen=True)
class Deck:
    """A deck file (phase 4): its space, kind, slug and text, the file's bytes decoded as UTF-8
    exactly (line endings and a byte order mark kept: text.encode() gives the bytes back), or
    None with error saying why it couldn't be read (not UTF-8, or the OS refused). id is the
    library's ("<kind>/<slug>" at home, "<space>/<kind>/<slug>" in a person's space). revision:
    the database's number of the stored text (it rises by 1 with each save that changes it), or
    0 meaning "unknown": the files backend keeps no history, so there Forge provenance can't
    name a revision ({deck, revision} is left out) and a command line's --expect N can't be
    checked (the sha256 is the concurrency token on both); it never counts in equality, as a
    row's hidden id doesn't."""
    space: str
    kind: str
    slug: str
    text: str | None = None
    error: str | None = None
    revision: int = field(default=0, compare=False)
    rename_version: int = field(default=0, compare=False)

    @property
    def id(self):
        return f"{self.kind}/{self.slug}" if self.space == paths.HOME else f"{self.space}/{self.kind}/{self.slug}"

    @property
    def path(self):
        """Where the files backend keeps it (paths.decks_dir), and the path changes.classify and
        Summary.changed key it by. Messages name a deck by its id, never this."""
        return f"{paths.decks_dir(self.space)}/{self.kind}/{self.slug}.md"

    @property
    def data(self):
        """The file's bytes (None when it couldn't be read)."""
        return None if self.text is None else self.text.encode("utf-8")

    @property
    def sha256(self):
        """The sha256 of the file's bytes: the token the pages send back; None when it couldn't
        be read."""
        return None if self.text is None else hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def replace(self, **changes):
        return dataclasses.replace(self, **changes)


@dataclass(frozen=True)
class ImageMeta:
    """An accessory picture: its file name, size and sha256. content: its bytes, only on a
    picture an operation is writing (Inventory.with_image); a loaded snapshot never holds them.
    content never counts in equality (size and sha256 say whether it changed)."""
    name: str
    size: int
    sha256: str
    content: bytes | None = field(default=None, compare=False, repr=False)

    @property
    def path(self):
        return paths.image(self.name)

    @classmethod
    def of(cls, name, content):
        """The meta of a picture with these bytes, holding them."""
        content = bytes(content)
        return cls(name, len(content), hashlib.sha256(content).hexdigest(), content)


@dataclass(frozen=True)
class DeckRevision:
    """One saved text of a deck (the database's deck_revision row; the files backend keeps none):
    revision numbers a deck's texts from 1 (a deck made again after its deletion carries on after
    the 'D'); at is an aware datetime; actor the profile id (or "claude") who saved it; message
    the change's whole message; op "A" (made), "M" (changed) or "D" (deleted: text None);
    git_commit the commit an imported revision came from (else None) and change_set_id the
    change Deck Lab saved it in (None for an imported one). kit: the revision changed the deck's
    Sleeves or Deck box (or deleted a deck holding them), so its message names accessories,
    which are private from admins too: message_for() keeps it for its actor. text is loaded only
    by deck_revision()."""
    deck_id: str
    revision: int
    at: object
    actor: str
    message: str
    op: str
    kit: bool = False
    git_commit: str | None = None
    change_set_id: int | None = None
    text: str | None = None

    def message_for(self, viewer, everything=False):
        """The message as viewer (a profile id, or None) may see it: whole, unless the revision
        changed the kit and viewer isn't its actor (then None); everything (a script
        naming nobody, as Activity's "all") sees every message."""
        return self.message if not self.kit or everything or (viewer is not None and viewer == self.actor) else None


@dataclass(frozen=True)
class Component:
    """One component of an order record: data is its JSON object as read, in key order (never
    mutate it; record() copies)."""
    data: Mapping

    def _get(self, key, default=None):
        return self.data.get(key, default) if isinstance(self.data, dict) else default

    id = property(lambda self: self._get("id"))
    kind = property(lambda self: self._get("kind"))
    path = property(lambda self: self._get("path"))
    status = property(lambda self: self._get("status"))
    received_on = property(lambda self: self._get("received_on"))
    checks = property(lambda self: self._get("checks"))
    verified_checks = property(lambda self: self._get("verified_checks"))   # None when absent
    check_links = property(lambda self: self._get("check_links"))

    @property
    def file_name(self):
        return PurePosixPath(self.path).name if isinstance(self.path, str) else None

    @property
    def product_stem(self):
        return PurePosixPath(self.path).stem if self.kind == "product" and isinstance(self.path, str) else None

    def record(self):
        return copy.deepcopy(self.data)

    @classmethod
    def build(cls, id, kind, file_name, status="pending", received_on="", checks=(), verified_checks=None, check_links=None):
        """A component in the records' key order: id, kind, path (derived from kind, status and
        file name), status, received_on, checks, then verified_checks only when given."""
        data = {"id": id, "kind": kind, "path": paths.payload(kind, status, file_name), "status": status,
                "received_on": received_on, "checks": list(checks)}
        if verified_checks is not None:
            data["verified_checks"] = list(verified_checks)
        if check_links is not None:
            data["check_links"] = copy.deepcopy(check_links)
        return cls(data)


@dataclass(frozen=True)
class Order:
    """An order record (magic/orders/records/<id>.json). data is its JSON as read, in key order
    (never mutate it; record() copies), or None with error saying why the file couldn't be read
    (not UTF-8, not JSON, a duplicate key). Whether data follows the records' rules is for the
    reader to check (purchases.read_records), as it is today."""
    file: str
    data: object = None
    error: str | None = None

    def _get(self, key, default=None):
        return self.data.get(key, default) if isinstance(self.data, dict) else default

    version = property(lambda self: self._get("version"))
    id = property(lambda self: self._get("id"))
    seller = property(lambda self: self._get("seller"))
    ordered_on = property(lambda self: self._get("ordered_on"))
    sources = property(lambda self: self._get("sources"))
    notes = property(lambda self: self._get("notes"))
    audit_notes = property(lambda self: self._get("audit_notes"))            # None when absent

    @property
    def path(self):
        return f"{paths.RECORDS}/{self.file}"

    @property
    def components(self):
        """(Component, ...) of the components that are JSON objects (copies of them, so a reader
        can't change the snapshot through one); () when there are none."""
        items = self._get("components")
        if not isinstance(items, list):
            return ()
        return tuple(Component(copy.deepcopy(item)) for item in items if isinstance(item, dict))

    def record(self):
        return copy.deepcopy(self.data)

    @classmethod
    def build(cls, id, seller="", ordered_on="", sources=(), notes="", components=(), audit_notes=None):
        """A record in the files' key order: version (1), id, seller, ordered_on, sources, notes,
        components, then audit_notes only when given. components are Component's or dicts."""
        data = {"version": 1, "id": id, "seller": seller, "ordered_on": ordered_on,
                "sources": list(sources), "notes": notes,
                "components": [c.record() if isinstance(c, Component) else copy.deepcopy(c) for c in components]}
        if audit_notes is not None:
            data["audit_notes"] = audit_notes
        return cls(f"{id}.json", data)


# ------------------------------------------------------------------ the snapshot

@dataclass(frozen=True)
class Inventory:
    """The whole inventory at one revision (see the module docstring). Its mappings are
    read-only views (MappingProxyType) and its tuples can't change: an operation makes a new
    Inventory (replace(), or the write helpers below).

    revision: the backend's; a preview's ends with PREVIEW ("~preview"): it was never saved, so
    nothing may cache by it (see persisted). root: the folder a files backend read it from (None
    for the database's snapshots and from_git's), only so an error can name a missing file where
    it was looked for; it never counts when snapshots are compared. deck_aliases maps former
    exact IDs to their current (or retired) identity, flattened without chains; deck() does
    not resolve it. aliases_ready and deck_history_ids are backend capability/guard metadata
    (not compared), respectively enabling rename and reserving unrelated historical IDs."""
    revision: str
    collections: Mapping = field(default_factory=dict)
    tokens: Mapping = field(default_factory=dict)
    locations: Mapping = field(default_factory=dict)
    imports: Mapping = field(default_factory=dict)
    status: Sheet = field(default_factory=lambda: Sheet(paths.STATUS))
    products: tuple = ()
    orders: tuple = ()
    payloads: Mapping = field(default_factory=dict)
    watchlist: Sheet = field(default_factory=lambda: Sheet(paths.WATCHLIST))
    backend: str = "files"
    stale: str | None = None
    root: str | None = field(default=None, compare=False, repr=False)
    decks_revision: str = ""
    decks: Mapping = field(default_factory=dict)
    deck_aliases: Mapping = field(default_factory=dict)
    aliases_ready: bool = field(default=False, compare=False)
    deck_history_ids: tuple = field(default=(), compare=False)
    accessories: Sheet = field(default_factory=lambda: Sheet(paths.ACCESSORIES))
    accessory_images: Mapping = field(default_factory=dict)
    locations_ready: bool = field(default=True, compare=False)

    MAPPINGS = ("collections", "tokens", "locations", "imports", "payloads", "decks", "deck_aliases", "accessory_images")

    def __post_init__(self):
        for name in self.MAPPINGS:
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def replace(self, **changes):
        return dataclasses.replace(self, **changes)

    @property
    def persisted(self):
        """False for a preview's snapshot (its revision ends with PREVIEW). Anything that caches
        by revision (the tokens deck cache, Forge provenance, a pool cache) must skip such a
        snapshot, or a preview's data would be served as the real inventory."""
        return not self.revision.endswith(PREVIEW)

    # -------------------------------------------------------- decks and accessories (phase 4)

    def deck(self, deck_id):
        """The Deck with this id, or None."""
        return self.decks.get(deck_id)

    def space_decks(self, space=paths.HOME):
        """A space's Decks in the folders' listing order: casual first, then commander, each by
        file name (as decks.deck_files() lists the files)."""
        found = [d for d in self.decks.values() if d.space == space]
        return sorted(found, key=lambda d: (paths.DECK_KINDS.index(d.kind), f"{d.slug}.md"))

    def image_meta(self, name):
        """The ImageMeta of the picture with this file name, or None."""
        return self.accessory_images.get(name)

    # -------------------------------------------------------- spaces

    def spaces(self):
        """Every space with a collection, tokens or imports: home first, then by id."""
        found = set(self.collections) | set(self.tokens) | set(self.imports) | {paths.HOME}
        return [paths.HOME] + sorted(found - {paths.HOME})

    def collection(self, space=paths.HOME):
        """A space's collection Sheet; an empty one (exists False) when it has none."""
        return self.collections.get(space) or Sheet(paths.collection(space))

    def token_set(self, space=paths.HOME):
        return self.tokens.get(space) or Sheet(paths.tokens(space))

    def location_sheet(self, space=paths.HOME):
        """A space's locations Sheet; an empty one (exists False) when no row has a location."""
        return self.locations.get(space) or Sheet(paths.locations(space))

    def locations_of(self, space=paths.HOME):
        """{(set, collector_number, finish): location} of a space's located collection rows (E8-S22),
        only rows the collection has and only a location that is text."""
        listed = {rules.ident(row) for row in self.collection(space).rows
                  if all(isinstance(row.get(k), str) for k in ("set", "collector_number", "finish"))}
        sheet = self.location_sheet(space)
        if sheet.error is not None:
            return {}
        return {row.key: row.text("location") for row in sheet.rows
                if row.key in listed and row.text("location")}

    # -------------------------------------------------------- products and orders

    @property
    def status_rows(self):
        return self.status.rows

    def product(self, stem):
        return next((p for p in self.products if p.stem == stem), None)

    def order(self, order_id):
        return next((o for o in self.orders if o.id == order_id), None)

    def components(self):
        """[(order, component)] of every readable record, in record and component order."""
        return [(order, component) for order in self.orders for component in order.components]

    def pending_payloads(self, kind="cards"):
        """Paths of the payload files in the pending folder for kind (magic/orders for cards,
        magic/orders/tokens for tokens), in name_order: what pool counts as on the way, whether
        or not a record names them."""
        folder = paths.payload_folder(kind, "pending")
        found = [p for p in self.payloads if PurePosixPath(p).parent.as_posix() == folder]
        return sorted(found, key=lambda p: name_order(PurePosixPath(p).name))

    @property
    def loose_payloads(self):
        """Paths of pending card payloads that no record's component names (the files backend
        only: a database payload always belongs to a component)."""
        named = {c.path for _, c in self.components()}
        return [p for p in self.pending_payloads("cards") if p not in named]

    def raw_incoming_status_rows(self):
        """Status rows whose status (stripped, lower case) is preordered or ordered, in status
        order. Raw rows only, NOT the pool's rule (pool also drops a row whose product file is
        missing and lets a later row for the same file win): each reader applies its own."""
        return [row for row in self.status.rows if (row.get("status") or "").strip().lower() in INCOMING]

    @property
    def unreadable(self):
        """{path: why} for every source that couldn't be read at all."""
        out = {}
        for sheet in (*self.collections.values(), *self.tokens.values(), self.status,
                      *self.payloads.values(), self.watchlist):
            if sheet.error is not None:
                out[sheet.path] = sheet.error
        for product in self.products:
            if product.error is not None:
                out[product.path] = product.error
        for order in self.orders:
            if order.error is not None:
                out[order.path] = order.error
        return dict(sorted(out.items()))

    # -------------------------------------------------------- write helpers (for operations)
    #
    # Each returns a new Inventory with one source as every writer leaves it: the file's
    # standard columns, rows coerced to the right Row class (a mapping's missing values ""),
    # and no problems. The backend re-reads every source an operation changed before it saves
    # (changes.prepare), so problems, line numbers and strict errors come back then; an
    # operation never needs to work them out.

    def with_collection(self, space, rows):
        """space's collection holding rows (CardRow's or mappings), collection.csv's columns only,
        in rules.sort_key order (ties keep the given order); no rows: the space has no collection
        (no file, as a space with no cards has none)."""
        made = tuple(sorted((coerce(CardRow, row) for row in rows), key=rules.sort_key))
        collections = {k: v for k, v in self.collections.items() if k != space}
        if made:
            collections[space] = Sheet(paths.collection(space), CardRow.COLUMNS, made, True)
        out = self.replace(collections=dict(sorted(collections.items())))
        return out.without_stray_locations(space)

    def with_locations(self, space, found):
        """space's storage locations as found ({(set, collector_number, finish): location}): blank
        ones dropped, in collection order, locations.csv's columns; none left: no file. A key the
        collection doesn't have is dropped too (changes.prepare drops such keys anyway)."""
        listed = [rules.ident(row.as_dict()) for row in self.collection(space).rows]
        made = tuple(LocationRow.make(dict(zip(rules.LOCATION_FIELDS, (*key, found[key]))))
                     for key in listed if found.get(key))
        locations = {k: v for k, v in self.locations.items() if k != space}
        if made:
            locations[space] = Sheet(paths.locations(space), LocationRow.COLUMNS, made, True)
        return self.replace(locations=dict(sorted(locations.items())))

    def without_stray_locations(self, space=None):
        """This snapshot with each location whose collection row is gone dropped (space: only that
        one's; None: every space's). The same snapshot when there's none to drop."""
        out = self
        for each in ([space] if space is not None else list(self.locations)):
            sheet = self.locations.get(each)
            if sheet is None or sheet.error is not None or self.collection(each).error is not None:
                continue
            listed = {rules.ident(row.as_dict()) for row in self.collection(each).rows
                      if all(isinstance(row.get(k), str) for k in ("set", "collector_number", "finish"))}
            if all(row.key in listed for row in sheet.rows):
                continue
            kept = tuple(row for row in sheet.rows if row.key in listed)
            locations = {k: v for k, v in out.locations.items() if k != each}
            if kept:
                locations[each] = dataclasses.replace(sheet, rows=kept)
            out = out.replace(locations=dict(sorted(locations.items())))
        return out

    def with_tokens(self, space, rows):
        """space's token cards holding rows (TokenRow's, which keep their hidden id, or
        mappings), tokens.csv's columns, in rules.TOKEN_SORT order (ties keep the given order),
        as the Tokens page and receipts write it; no rows: no file. Refuses (state.Conflict, with
        today's strict read's words) while the space's tokens.csv has rows the snapshot can't
        hold (problems): rewriting it from rows would delete them."""
        refuse_unreadable_tokens(self.token_set(space))
        made = tuple(sorted((coerce(TokenRow, row) for row in rows), key=rules.token_sort_key))
        tokens = {k: v for k, v in self.tokens.items() if k != space}
        if made:
            tokens[space] = Sheet(paths.tokens(space), TokenRow.COLUMNS, made, True)
        return self.replace(tokens=dict(sorted(tokens.items())))

    def with_status_rows(self, rows):
        """products/status.csv holding rows (StatusRow's or mappings), always with the current
        columns (a legacy file gains blank kit and packed-token columns, as a
        receipt does)."""
        made = tuple(coerce(StatusRow, row) for row in rows)
        return self.replace(status=Sheet(paths.STATUS, StatusRow.COLUMNS, made, True))

    def with_watchlist(self, rows):
        """The watchlist holding rows (WatchRow's, which keep their hidden id, or mappings with
        the column "for"), in the order given."""
        made = tuple(coerce(WatchRow, row) for row in rows)
        return self.replace(watchlist=Sheet(paths.WATCHLIST, WatchRow.COLUMNS, made, True))

    def with_order(self, order):
        """order (an Order) added, or put in place of the record with its file name."""
        orders = [o for o in self.orders if o.file != order.file] + [order]
        return self.replace(orders=tuple(sorted(orders, key=lambda o: name_order(o.file))))

    def without_order(self, order_id):
        return self.replace(orders=tuple(o for o in self.orders if o.id != order_id))

    def with_product(self, product):
        """product (a Product) added, or put in place of the one with its stem."""
        products = [p for p in self.products if p.stem != product.stem] + [product]
        return self.replace(products=tuple(sorted(products, key=lambda p: name_order(p.file))))

    def without_product(self, stem):
        return self.replace(products=tuple(p for p in self.products if p.stem != stem))

    def with_deck(self, deck):
        """deck (a Deck with its text) added, or put in place of the one with its id. Its text is
        final: the caller renders it (decks.render_deck_file, new_deck_text) before the operation
        runs (the phase 4 design's R4)."""
        if not isinstance(deck, Deck) or not isinstance(deck.text, str):
            raise ValueError("with_deck needs a Deck with its text")
        decks = {k: v for k, v in self.decks.items() if k != deck.id}
        decks[deck.id] = deck
        return self.replace(decks=dict(sorted(decks.items())))

    def without_deck(self, deck_id):
        return self.replace(decks={k: v for k, v in self.decks.items() if k != deck_id})

    def with_accessories(self, rows):
        """accessories.csv holding rows (AccessoryRow's or mappings) with its standard columns
        (rules.ACCESSORY_FIELDS: an older header's file is rewritten whole, as a save does),
        sorted by kind, then id (rules.accessory_sort_key)."""
        made = tuple(sorted((coerce(AccessoryRow, row) for row in rows), key=rules.accessory_sort_key))
        return self.replace(accessories=Sheet(paths.ACCESSORIES, AccessoryRow.COLUMNS, made, True))

    def with_image(self, name, content):
        """The picture name holding content (bytes), added or put in place of the one there.
        ValueError for a name that can't be a picture's."""
        paths.image(name)
        images = {k: v for k, v in self.accessory_images.items() if k != name}
        images[name] = ImageMeta.of(name, content)
        return self.replace(accessory_images=dict(sorted(images.items())))

    def without_image(self, name):
        return self.replace(accessory_images={k: v for k, v in self.accessory_images.items() if k != name})

    def _component(self, order_id, component_id):
        order = self.order(order_id)
        if order is None or order.error is not None:
            raise ValueError(f"there's no readable order record {order_id!r}")
        data = order.record()
        for item in data.get("components") or []:
            if isinstance(item, dict) and item.get("id") == component_id:
                return order, data, item
        raise ValueError(f"order {order_id} has no component {component_id!r}")

    def update_component(self, order_id, component_id, **changes):
        """A component's fields changed (status, received_on, checks, verified_checks, path),
        keeping the records' key order, including optional verified_checks and check_links. Values are copied.
        ValueError for an unknown order or component, or a field components don't have."""
        order, data, item = self._component(order_id, component_id)
        for key, value in changes.items():
            if key not in COMPONENT_KEYS:
                raise ValueError(f"components have no field {key!r}")
            if key == "check_links" and value is None:
                item.pop(key, None)
            else:
                item[key] = copy.deepcopy(value) if key == "check_links" else list(value) if isinstance(value, (list, tuple)) else value
        ordered = {key: item[key] for key in COMPONENT_KEYS if key in item}
        ordered.update((key, value) for key, value in item.items() if key not in COMPONENT_KEYS)
        item.clear()
        item.update(ordered)
        return self.with_order(Order(order.file, data))

    def move_component(self, order_id, component_id, status, received_on=None):
        """A component given a new status (pending, received or cancelled; received_on too when
        given), its payload file moving with it: the record's path, the payloads key and the
        sheet's own path change together. A product component's file stays in products/."""
        _, _, item = self._component(order_id, component_id)
        old = item.get("path")
        new = paths.payload(item.get("kind"), status, PurePosixPath(old).name)
        changes = {"status": status, "path": new}
        if received_on is not None:
            changes["received_on"] = received_on
        inv = self.update_component(order_id, component_id, **changes)
        if old != new and old in self.payloads:
            payloads = {k: v for k, v in self.payloads.items() if k != old}
            payloads[new] = dataclasses.replace(self.payloads[old], path=new)
            inv = inv.replace(payloads=dict(sorted(payloads.items())))
        return inv

    def set_component_rows(self, order_id, component_id, rows):
        """A cards or tokens component's payload holding rows (CardRow/TokenRow's or mappings)
        in the order given, with the payload's standard columns (created when the component has
        no file yet)."""
        _, _, item = self._component(order_id, component_id)
        kind, path = item.get("kind"), item.get("path")
        if kind not in ("cards", "tokens"):
            raise ValueError(f"{component_id} is a {kind} component, which has no payload rows")
        cls = CardRow if kind == "cards" else TokenRow
        payloads = dict(self.payloads)
        made = Sheet(path, cls.COLUMNS, tuple(coerce(cls, row) for row in rows), True)
        previous = payloads.get(path)
        payloads[path] = made
        after = self.replace(payloads=dict(sorted(payloads.items())))
        if item.get("check_links") is not None and (previous is None or previous.rows != made.rows):
            after = after.update_component(order_id, component_id, check_links=None)
        return after


COMPONENT_KEYS = ("id", "kind", "path", "status", "received_on", "checks", "verified_checks", "check_links")


def coerce(cls, row):
    """row as a cls (a Row class) with exactly cls.COLUMNS: a cls row that has them is kept as
    it is; another Row keeps its line, id and text (cells it lacks become ""); a mapping's
    missing or None values become ""."""
    if isinstance(row, cls) and row.columns() == cls.COLUMNS and not row.overflow:
        return row
    if isinstance(row, Row):
        return cls.make({c: row.text(c) for c in cls.COLUMNS}, line=row.line, id=row.id)
    return cls.make(row)


def refuse_unreadable_tokens(sheet):
    """state.Conflict when a token sheet can't be rewritten from its rows: it couldn't be read,
    or it has rows tokens.read() leaves out (problems), which a rewrite would delete. The words
    are today's strict read's ("..." and rules.UNTIL_PUT_RIGHT)."""
    if sheet.error is None and not sheet.problems and sheet.strict_error is None:
        return
    from decklab.lib.state import Conflict
    if sheet.strict_error:
        raise Conflict(sheet.strict_error)
    first = sheet.problems[0] if sheet.problems else f"{sheet.path} can't be read ({sheet.error})"
    raise Conflict(first if "fix" in first or rules.UNTIL_PUT_RIGHT in first else f"{first}{rules.UNTIL_PUT_RIGHT}")
