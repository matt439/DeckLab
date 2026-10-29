"""The accessories inventory: sleeves, deck boxes and playmats (magic/accessories.csv).

Data only: reading and checking the rows, resolving the ids that deck headers
and products/status.csv hold, who holds what, and the enough-sleeves rule with
its wording. Everything is read from the inventory's snapshot
(decklab.lib.inventory.current(): its accessories sheet, its pictures' metas
and its decks), whichever backend holds it (the files under magic/, or the
database); this module never writes. The writes are the inventory operations
accessory.add, accessory.edit, accessory.remove, image.put, image.remove and
kit.set (lib/inventory/ops_accessories.py), which the Accessories page's API
(lib/api/accessories.py) and the command line run.

The CSV has the columns FIELDS, one row per accessory:

- id: a slug (ID_RE, at most 40 characters), made once from brand, name and
  colour by new_id() and never changed. Deck files' "Sleeves" and "Deck box"
  lines and status.csv's sleeves and deck_box columns hold it;
- kind: sleeves, deck_box or playmat;
- owner: whose it is: a home profile's id (matt, user1) or "shared". Deck
  Lab shows a row only to its owner, and a shared one to every home
  profile (permissions.accessory_owners). A holder belongs to the home
  profile whose plays_as is its Played by, or is shared ("either" decks and
  intact products: holder_owner), and uses only its owner's accessories or
  shared ones;
- brand, name (required), colour (the back colour or design, which tells a
  stray card's deck by its back), notes: one line each;
- quantity: 0-9999. For sleeves it counts individual sleeves of the design,
  loose ones too; otherwise items;
- capacity: for a deck box, how many sleeved cards one box holds (1-9999),
  or blank when not known; always blank for other kinds;
- image: blank, or "<id>.<jpg|png|webp>" in magic/accessories/images/;
- crop: blank (the whole picture), or "x,y,w,h", the part of the picture
  shown: its left and top edges and its width and height as fractions of
  the picture's (0-1, at most 4 decimals). Only a row with a picture has
  one; the file itself is never changed;
- link (the product page the user pasted) and image_source (where the picture
  was downloaded from): blank or http(s) URLs.

The older headers without owner, crop or capacity are still read (those
columns blank, and owner "shared"), and the next save writes FIELDS.

A holder is a built deck (its Sleeves and Deck box header lines) or an owned
product kept intact (its status.csv columns). A value that isn't an id is
older free text, shown as written and never matched by name. Only kit.set
changes either.

The list's concurrency token is per viewer (view_sha256): the sha256 of the
rows that viewer sees, rendered as the file would be, so a change to another
owner's row never makes a save refuse, nor says it happened (None while the
viewer sees no rows, list or not).

Usage:

    from decklab.lib import accessories

    inv = accessories.read()                         # lenient: bad rows go to inv.problems
    inv = accessories.read(strict=True)              # AccessoriesError on any bad row (for writes)
    accessories.view_sha256(inv, owners)             # the list's token for a viewer (None: no rows it sees)
    accessories.resolve("dragon-shield-matte-black", "sleeves", inv)   # a Ref, or None if blank
    accessories.kit("casual/izzet-otters", inv=inv)  # sleeves, deck box, need, short, warnings, info
    python -m decklab.lib.accessories --check        # the invariants
"""
import argparse
import csv
import hashlib
import io
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from decklab.lib import config, decks, inventory, pool
from decklab.lib.decks.decklist import SECTIONS, card_count
from decklab.lib.inventory import kit as product_kit
from decklab.lib.inventory import paths as inventory_paths
from decklab.lib.inventory import rules as inventory_rules

FIELDS = list(inventory_rules.ACCESSORY_FIELDS)      # the inventory keeps the rows raw, in these columns
# The columns a page or the command line gives a row (id is made once; image comes with its picture).
ROW_KEYS = ("kind", "owner", "brand", "name", "colour", "quantity", "capacity", "crop", "link", "image_source", "notes")
# Older headers, still read: before owner, before crop too, and before capacity too.
LEGACY_HEADERS = tuple([f for f in FIELDS if f not in gone]
                       for gone in (("owner",), ("owner", "crop"), ("owner", "crop", "capacity")))
SHARED = "shared"               # the owner of what both home profiles use
KINDS = inventory_rules.ACCESSORY_KINDS             # also the sort order
HOLDER_FIELDS = ("sleeves", "deck_box")             # the kinds a deck or product holds
ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
IMAGE_RE = re.compile(r"^([a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?)\.(jpg|png|webp)$")
CROP_RE = re.compile(r"^(?:0|1|0?\.\d{1,4}|1\.0{1,4})(?:,(?:0|1|0?\.\d{1,4}|1\.0{1,4})){3}$")
MIN_CROP = 0.02                 # a crop's smallest width or height, as a fraction of the picture's
URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
# Where the files backend keeps them (tests patch these); readers read the inventory's snapshot.
PATH = config.MAGIC / "accessories.csv"
IMAGES = config.MAGIC / "accessories" / "images"

MAX_ID = 40
MAX_BRAND = 40
MAX_NAME = 80
MAX_COLOUR = 40
MAX_QUANTITY = 9999
MAX_CAPACITY = 9999
MAX_LINK = 500
MAX_SOURCE = 2000               # a CDN address can be long; it's only provenance
MAX_NOTES = 300

# The words for each kind in messages: "a deck box in the accessories list".
_KIND_WORDS = {"sleeves": "sleeves", "deck_box": "a deck box", "playmat": "a playmat"}
_FIELD_WORDS = {"sleeves": "Sleeves", "deck_box": "Deck box"}
# How a stray on a product's status row is named ("Product x", by the stem product kit takes);
# a deck's is its id (lowercase, so never starting with this).
_STATUS_STRAY = "Product "
NO_PROBLEMS = "Accessories: no problems"      # what accessories check prints when all is well


class AccessoriesError(ValueError):
    """accessories.csv can't be read strictly (bad header or row), so it can't be changed."""


@dataclass
class Inventory:
    """accessories.csv as read: {id: row} (each row cleaned by validate_row,
    quantity an int), the sha256 of the whole file as rendered (None when
    there's no list yet; a viewer's token is view_sha256's) and, from a
    lenient read, the rows left out as text."""
    rows_by_id: dict = field(default_factory=dict)
    sha256: str | None = None
    problems: list = field(default_factory=list)


# ------------------------------------------------------------------ rows

def _text(row, key, limit, required=False):
    value = decks.clean_title(row.get(key) or "")
    if required and not value:
        raise ValueError(f"{key} is required")
    if len(value) > limit:
        raise ValueError(f"{key} is longer than {limit} characters")
    return value


def _url(row, key, limit):
    value = str(row.get(key) or "").strip()
    if value and (len(value) > limit or not URL_RE.match(value)):
        raise ValueError(f"{key} must be blank or an http(s) address of at most {limit} characters")
    return value


def valid_id(value):
    """True for an id Deck Lab could have made: a slug of at most 40
    characters that isn't a name Windows reserves (con, nul, com1...)."""
    return bool(ID_RE.match(str(value))) and str(value) not in decks.RESERVED_SLUGS


def _whole(value):
    """value as an int, or None when it isn't a whole number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _crop(value, image):
    """A crop as written: "" or "x,y,w,h" (see the module docstring), each
    number as written in its shortest form. Raises ValueError."""
    text = "".join(str(value or "").split())
    if not text:
        return ""
    if not image:
        raise ValueError("crop must be blank for a row without a picture")
    if not CROP_RE.match(text):
        raise ValueError(f"crop {text!r} must be blank or four numbers from 0 to 1: left,top,width,height")
    x, y, w, h = (float(n) for n in text.split(","))
    if w < MIN_CROP or h < MIN_CROP or x + w > 1.00005 or y + h > 1.00005:
        raise ValueError(f"crop {text!r} must lie inside the picture, at least {MIN_CROP:g} wide and high")
    return ",".join(f"{n:.4f}".rstrip("0").rstrip(".") or "0" for n in (x, y, w, h))


def validate_row(row):
    """A row as written to the CSV: text fields cleaned (decks.clean_title),
    quantity an int, capacity an int or None. Raises ValueError saying
    what's wrong."""
    rid = str(row.get("id") or "").strip()
    if not valid_id(rid):
        raise ValueError(f"id {rid!r} must be lowercase letters, digits and single hyphens, "
                         f"at most {MAX_ID} characters")
    kind = str(row.get("kind") or "").strip()
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r} must be one of {', '.join(KINDS)}")
    owner = str(row.get("owner") or "").strip()
    if not (owner == SHARED or ID_RE.match(owner)):
        raise ValueError(f"owner {owner!r} must be a home profile's id or {SHARED}")
    quantity = _whole(row.get("quantity"))
    if quantity is None or not 0 <= quantity <= MAX_QUANTITY:
        raise ValueError(f"quantity {row.get('quantity')!r} must be a whole number from 0 to {MAX_QUANTITY}")
    capacity = row.get("capacity")
    if capacity is None or str(capacity).strip() == "":
        capacity = None
    else:
        if kind != "deck_box":
            raise ValueError("capacity is only for a deck box; leave it blank")
        capacity = _whole(capacity)
        if capacity is None or not 1 <= capacity <= MAX_CAPACITY:
            raise ValueError(f"capacity {row.get('capacity')!r} must be blank or a whole number from 1 to {MAX_CAPACITY}")
    image = str(row.get("image") or "").strip()
    if image:
        m = IMAGE_RE.match(image)
        if not m or m.group(1) != rid:
            raise ValueError(f"image {image!r} must be blank or {rid}.jpg, .png or .webp")
    return {
        "id": rid, "kind": kind, "owner": owner,
        "brand": _text(row, "brand", MAX_BRAND),
        "name": _text(row, "name", MAX_NAME, required=True),
        "colour": _text(row, "colour", MAX_COLOUR),
        "quantity": quantity, "capacity": capacity, "image": image, "crop": _crop(row.get("crop"), image),
        "link": _url(row, "link", MAX_LINK),
        "image_source": _url(row, "image_source", MAX_SOURCE),
        "notes": _text(row, "notes", MAX_NOTES),
    }


def new_id(row, taken):
    """A new row's id, from its brand, name and colour (decks.title_slug, cut
    to 40 characters), with -2, -3... added while it's in taken (ids of any
    kind) or a name Windows reserves."""
    base = decks.title_slug(" ".join(str(row.get(k) or "") for k in ("brand", "name", "colour")))
    base = base[:MAX_ID].rstrip("-") or "accessory"
    taken = {str(t).lower() for t in taken}
    candidate, n = base, 1
    while candidate in taken or not valid_id(candidate):
        n += 1
        suffix = f"-{n}"
        candidate = base[:MAX_ID - len(suffix)].rstrip("-") + suffix
    return candidate


def _sort_key(row):
    return (KINDS.index(row["kind"]) if row["kind"] in KINDS else len(KINDS), row["id"])


def csv_bytes(rows):
    """The CSV file for rows (dicts with FIELDS): sorted by kind, then id;
    UTF-8 without a byte order mark, LF line endings."""
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in sorted(rows, key=_sort_key):
        writer.writerow({k: "" if row.get(k) is None else row.get(k) for k in FIELDS})
    return out.getvalue().encode("utf-8")


def label(row):
    """How messages name an accessory: "Dragon Shield Matte (black)"."""
    text = " ".join(p for p in (row.get("brand"), row.get("name")) if p)
    return f"{text} ({row['colour']})" if row.get("colour") else text


# ------------------------------------------------------------------ reading

def read(strict=False):
    """The Inventory from the inventory's accessories.csv now (inventory.current());
    an empty one when there's none yet (the first save makes it).

    strict (for writes) raises AccessoriesError for a header other than
    FIELDS, malformed CSV, a bad row or a repeated id, worded "accessories.csv
    line N: ..." and inventory_rules.UNTIL_PUT_RIGHT. Otherwise those rows are left out and
    listed in problems. OSError when the list couldn't be read at all (the
    OS refused the file, or it isn't text)."""
    return from_sheet(inventory.current().accessories, strict)


def from_sheet(sheet, strict=False):
    """The Inventory an inventory snapshot's accessories Sheet holds, as read() reads it: the
    rows parse() keeps, and the problems and strict error the snapshot read from the file's own
    bytes (so their line numbers are the file's)."""
    from decklab.lib.inventory import files as inventory_files
    if not sheet.exists:
        return Inventory()
    if sheet.error is not None:
        raise OSError(f"{Path(sheet.path).name} can't be read: {sheet.error}")
    if strict and sheet.strict_error:
        raise AccessoriesError(sheet.strict_error)
    data = inventory_files.render_sheet(sheet)
    return Inventory(_sheet_rows(sheet), hashlib.sha256(data).hexdigest(), list(sheet.problems))


def _sheet_rows(sheet):
    """{id: row} of the rows parse() keeps from a sheet (a short or long row, a bad row and a
    repeated id are left out, as its problems say)."""
    header = list(sheet.columns or [])
    if header not in LEGACY_HEADERS and header != FIELDS and any(k not in header for k in FIELDS):
        return {}
    out = {}
    for row in sheet.rows:
        if row.overflow or any(value is None for _, value in row.values):
            continue
        values = dict(row.values)
        if not any(str(v).strip() for v in values.values()):
            continue
        if "owner" not in header:
            values["owner"] = SHARED
        try:
            found = validate_row(values)
        except ValueError:
            continue
        out.setdefault(found["id"], found)
    return out


def view_sha256(inv, owners):
    """The list's concurrency token for a viewer whose accessory owners are owners
    (permissions.accessory_owners; None: all): the sha256 of the rows it sees, rendered as the
    file would be (csv_bytes); None when it sees none, whether there's no list at all or none of
    its rows are the viewer's (so another owner's first row, or last one going, doesn't change it
    either). What GET /api/accessories gives and every save checks, so another owner's change
    never refuses (or tells of) a save."""
    rows = [r for r in inv.rows_by_id.values() if visible(r["owner"], owners)]
    return hashlib.sha256(csv_bytes(rows)).hexdigest() if rows else None


def parse(data, strict=False):
    """The Inventory accessories.csv's bytes hold, as read() reads the file (the inventory's
    snapshot reads its problems and strict error through this too). A problem names the list in
    the database's words and a row it leaves out by the listed row before it ("A row after row 2
    of the accessories list: ...", E11-S12), never the old file and line."""
    inv = Inventory(sha256=hashlib.sha256(data).hexdigest())
    name = "The accessories list"

    def problem(text):
        if strict:
            raise AccessoriesError(f"{text}{inventory_rules.UNTIL_PUT_RIGHT}")
        inv.problems.append(text)

    def row(text):
        listed = len(inv.rows_by_id)
        where = f"A row after row {listed}" if listed else "A row before row 1"
        problem(f"{where} of the accessories list: {text}")

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        problem(f"{name} isn't UTF-8 text")
        return inv
    reader = csv.reader(io.StringIO(text, newline=""), strict=strict)
    try:
        header = next(reader, None)
        if header in LEGACY_HEADERS:
            pass                # written before owner, crop or capacity: read, and the next save adds them
        elif header != FIELDS:
            missing = [k for k in FIELDS if k not in (header or [])]
            if strict or missing:
                problem(f"{name}'s columns must be {','.join(FIELDS)}")
                return inv
            inv.problems.append(f"{name}'s columns aren't {','.join(FIELDS)} "
                                f"(the columns were read by name)")
        for values in reader:
            if not any(v.strip() for v in values):
                continue
            if len(values) != len(header):
                row(f"{len(values)} values, not {len(header)}")
                continue
            values = dict(zip(header, values))
            if "owner" not in header:
                values["owner"] = SHARED        # written before owners: everyone's until someone claims it
            try:
                found = validate_row(values)
            except ValueError as e:
                row(str(e))
                continue
            if found["id"] in inv.rows_by_id:
                row(f"the id {found['id']} is listed twice")
                continue
            inv.rows_by_id[found["id"]] = found
    except csv.Error as e:
        row(str(e))
    return inv


def image_name(row):
    """The row's picture's file name, or None when it has none (or a bad name)."""
    name = row.get("image") or ""
    return name if IMAGE_RE.match(name) else None


def image_version(meta):
    """A new address epoch retires pictures previously cached without revalidation.
    Eight hex digits still fit the image route, but never reuse the old raw content prefix."""
    return hashlib.sha256(("accessory-private-v2:" + meta.sha256).encode("ascii")).hexdigest()[:8]


def image_url(row, inv=None):
    """"/accessory-img/<file>?v=<image_version>" for a row whose
    picture the inventory (inv, a snapshot; inventory.current() by default)
    has, else None. v changes with the picture and starts a new address epoch
    for the no-cache authorization rule. The route serves only its own v. A cropped row's ends
    "#crop=x,y,w,h": the browser never sends that part, and the page shows
    only that part of the picture."""
    name = image_name(row)
    if name is None:
        return None
    meta = (inventory.current() if inv is None else inv).image_meta(name)
    if meta is None:
        return None
    crop = f"#crop={row['crop']}" if row.get("crop") else ""
    return f"/accessory-img/{name}?v={image_version(meta)}{crop}"


# ------------------------------------------------------------------ resolving

def _state(value, kind, inv):
    """("linked" | "kind_mismatch" | "text", row or None) for a non-blank value."""
    row = inv.rows_by_id.get(value)
    if row is None:
        return "text", None
    return ("linked" if row["kind"] == kind else "kind_mismatch"), row


def resolve(value, kind, inv):
    """A header or status value as a Ref, or None when it's blank.

    A Ref is {value, id, kind, brand, name, colour, quantity, capacity,
    image_url, link, state, label}. state is "linked" when the trimmed value is the id of a row
    of this kind, "kind_mismatch" when it's the id of a row of another kind
    (kind is then that row's), and "text" for anything else: older free text,
    shown as written (id, kind and the row fields None, label the value). A
    value is never matched by name."""
    value = " ".join(str(value or "").split())
    if not value:
        return None
    state, row = _state(value, kind, inv)
    if row is None:
        return {"value": value, "id": None, "kind": None, "brand": None, "name": None, "colour": None,
                "quantity": None, "capacity": None, "image_url": None, "link": None, "state": state, "label": value}
    return {"value": value, "id": row["id"], "kind": row["kind"], "brand": row["brand"], "name": row["name"],
            "colour": row["colour"], "quantity": row["quantity"], "capacity": row["capacity"],
            "image_url": image_url(row), "link": row["link"] or None, "state": state, "label": label(row)}


# ------------------------------------------------------------------ owners

def _home_profiles(listed=None):
    """The home profiles (lib/profiles.py); [] when config.json can't be read."""
    from decklab.lib import profiles
    if listed is None:
        try:
            listed = profiles.read()
        except (OSError, ValueError):
            return []
    return [p for p in listed if p.get("space", profiles.HOME) == profiles.HOME]


def owner_ids(listed=None):
    """Every owner a row may have: the home profiles' ids, then SHARED."""
    return [p["id"] for p in _home_profiles(listed)] + [SHARED]


def player_owner(player, listed=None):
    """The owner of a home deck Played by player: the home profile whose
    plays_as it is, or SHARED ("either", the house's, or nobody's)."""
    if player and player != "either":
        for p in _home_profiles(listed):
            if p.get("plays_as") == player:
                return p["id"]
    return SHARED


def owner_name(owner, listed=None):
    """"User1" for an owner's id (the id itself when it's no profile's); "shared" for SHARED."""
    if owner == SHARED:
        return "shared"
    return next((p["name"] for p in _home_profiles(listed) if p["id"] == owner), owner)


def visible(owner, owners):
    """True when owners (permissions.accessory_owners: None for everything)
    includes owner."""
    return owners is None or owner in owners


def usable(row_owner, holder_owner):
    """True when a holder of holder_owner may use a row of row_owner: its own, or a shared one."""
    return row_owner in (holder_owner, SHARED)


def hidden_title(owner, kind="deck", listed=None):
    """How a holder the viewer can't see is named: "one of User1's decks"."""
    return f"one of {owner_name(owner, listed)}'s {'products' if kind == 'product' else 'decks'}"


# ------------------------------------------------------------------ holders

def sleeve_need(sections):
    """The sleeves a list needs: every card in every section (Commander,
    Companion, Deck, Sideboard), basic lands included."""
    return card_count(sections, SECTIONS)


def _need_words(sections):
    """"(60 in the deck, 15 in the sideboard)" when more than one section has cards, else ""."""
    counts = {s: card_count(sections, (s,)) for s in SECTIONS}
    parts = []
    for section, word in (("Commander", "commander"), ("Companion", "companion")):
        if counts[section]:
            parts.append(f"{counts[section]} {word}{'s' if counts[section] != 1 else ''}")
    for section, where in (("Deck", "in the deck"), ("Sideboard", "in the sideboard")):
        if counts[section]:
            parts.append(f"{counts[section]} {where}")
    return f" ({', '.join(parts)})" if len(parts) > 1 else ""


def _merged_sections(decklists):
    """Several lists' sections as one (the lines just listed together), for counting."""
    out = {}
    for sections in decklists:
        for name, lines in sections.items():
            out.setdefault(name, []).extend(lines)
    return out


def _product_sections(stem, product_decks):
    return _merged_sections(d["sections"] for d in product_decks
                            if d["product"] == stem and not d.get("error"))


def _statuses(inv, warnings):
    """{file name: pool.ProductStatus} of inv's products/status.csv: pool.read_status's answer
    (a later row for a file wins; an unknown status counts as owned and not intact), its
    warnings appended to warnings. OSError when the OS wouldn't read the file (locked by another
    program, say), as opening it would raise. read_status reads inv, pinned for the call
    (whatever snapshot an outer block pinned)."""
    sheet = inv.status
    if sheet.error is not None:
        raise OSError(f"{sheet.path} can't be read: {sheet.error}")
    with inventory.pinned(inv):
        return pool.read_status(warnings)


def _product_title(inv, file_name):
    """A product's short name ("Calling All Angels" for
    fdc-calling-all-angels.csv), as pool._product_name words it: the
    inventory's name for the product, else its file stem."""
    product = inv.product(Path(file_name).stem)
    return product.label("pool") if product is not None else pool._product_name(file_name)


def _has_product(inv, file_name):
    """Whether the inventory has the product file a status row names."""
    product = inv.product(Path(file_name).stem)
    return product is not None and product.file == file_name


def status_sha256():
    """The sha256 an assign must still match for a product holder (its
    holder_sha256): products/status.csv as rendered from the inventory now,
    whichever backend holds it (inventory/kit.py checks it); None when there's
    no status.csv, as for any missing file."""
    inv = inventory.current()
    return product_kit.status_sha256(inv) if inv.status.exists else None


def _scan(warnings):
    """(holders, strays): every holder as {holder, title, kind: "deck" |
    "product", owner (player_owner; SHARED for a product), sleeves,
    deck_box, sections}, and the accessory values written
    where nothing holds them, as (where, field, value): a deck that isn't
    built (where: its id), or a product status that isn't owned and intact
    (where: "Product <stem>"). Problems reading
    them go in warnings. Reads one inventory snapshot (the request's or
    command's, else one pinned for this call)."""
    from decklab.lib import inventory
    if not inventory.is_pinned():
        with inventory.pinned():
            return _scan(warnings)
    found, strays = [], []
    listed = _home_profiles()
    for summary in decks.list_decks():
        if summary["id"].startswith(("product/", "pairing/")) or summary.get("space", "home") != "home":
            continue
        values = {"sleeves": (summary.get("sleeves") or "").strip(),
                  "deck_box": (summary.get("deck_box") or "").strip()}
        if summary.get("status") != "built":
            strays.extend((summary["id"], f, v) for f, v in values.items() if v)
            continue
        if summary.get("error"):
            warnings.append(f"{inventory_paths.place(summary['source'])} can't be read: {summary['error']}")
            continue
        try:
            from decklab.lib.decks import assembled
            stored = inventory.current().deck(summary["id"])
            parsed = decks.parse_deck(stored.data, stored.slug, stored.kind, space=stored.space) if stored else None
            if parsed is not None and assembled.get(parsed):
                sections = assembled.sections(parsed)
            else:
                version = pool._built_version(summary, warnings)
                sections = decks.load_deck(summary["id"], version)
        except (decks.DeckNotFound, decks.DeckFileError, OSError) as e:
            warnings.append(f"{inventory_paths.place(summary['source'])} can't be read: {e}")
            continue
        found.append({"holder": summary["id"], "title": summary["title"], "kind": "deck",
                      "owner": player_owner(summary.get("player"), listed), **values, "sections": sections})
    inv = inventory.current()
    statuses = _statuses(inv, warnings)
    product_decks = None
    for name, status in statuses.items():
        values = {"sleeves": getattr(status, "sleeves", "") or "", "deck_box": getattr(status, "deck_box", "") or ""}
        stem = Path(name).stem
        if not (status.status == "owned" and status.intact):
            strays.extend((f"{_STATUS_STRAY}{stem}", f, v) for f, v in values.items() if v)
            continue
        if not _has_product(inv, name):
            continue
        if product_decks is None:
            product_decks = decks._product_decks()
        found.append({"holder": f"product/{stem}", "title": _product_title(inv, name), "kind": "product",
                      "owner": SHARED, **values, "sections": _product_sections(stem, product_decks)})
    return found, strays


def _usage(found, inv):
    out = {}
    for h in found:
        for f in HOLDER_FIELDS:
            value = " ".join(h[f].split())
            if value:
                state, _ = _state(value, f, inv)
                out.setdefault(value, []).append({
                    "holder": h["holder"], "title": h["title"], "kind": h["kind"], "owner": h["owner"], "field": f,
                    "need": sleeve_need(h["sections"]), "value": value, "state": state})
    return out


def holders(inv=None, warnings=None):
    """{value: [{holder, title, kind: "deck" | "product", owner, field, need,
    value, state}]}: who holds each accessory value. Holders are built deck files
    (with their built version's list) and owned products kept intact (all
    their decks; holder "product/<stem>"). A linked value is its id, so
    holders(inv)[row_id] (see used_by) lists who uses a row; free text is
    keyed as written, with runs of spaces made one. need is sleeve_need() of
    the holder's list. Everything is read once per call."""
    inv = read() if inv is None else inv
    warnings = [] if warnings is None else warnings
    found, _ = _scan(warnings)
    return _usage(found, inv)


def used_by(usage, row):
    """The holders of a row, from holders(): those whose value links to it."""
    return [h for h in usage.get(row["id"], []) if h["state"] == "linked" and h["field"] == row["kind"]]


def sharing_warning(holder_id, row_id, inv=None):
    """The command line's warning when holder_id is given sleeves other holders already use (Matt,
    2026-10-19: sharing is allowed, but whoever chooses them is told), or None. Read before the
    change, so it names the holders that had them; the command line sees every owner's."""
    inv = read() if inv is None else inv
    row = inv.rows_by_id.get(row_id) if row_id else None
    if row is None or row["kind"] != "sleeves":
        return None
    holder_id = _holder_id(holder_id)
    others = [h["title"] for h in used_by(holders(inv), row) if h["holder"] != holder_id]
    if not others:
        return None
    return (f"Warning: {', '.join(others)} {'uses' if len(others) == 1 else 'use'} {label(row)} already. "
            "Several decks can share one design: just don't play two of them against each other.")


# ------------------------------------------------------------------ the rule

def _holder_id(deck_id):
    """A product deck's holder is its product: "product/<stem>" for
    "product/<stem>/<deck>"."""
    if deck_id.startswith("product/"):
        return "/".join(deck_id.split("/")[:2])
    return inventory.resolve_deck_id(deck_id)


def _own(holder_id, warnings):
    """(title, kind, owner, values, sections, can_hold) for one holder id,
    read from its file; None is a deck not saved yet (an editor draft, owned
    by SHARED unless kit() is told)."""
    if holder_id is None:
        return "This deck", "deck", SHARED, {"sleeves": "", "deck_box": ""}, {}, True
    if holder_id.startswith("product/"):
        stem = holder_id.split("/", 1)[1]
        name = f"{stem}.csv"
        inv = inventory.current()
        status = _statuses(inv, []).get(name)
        sections = _product_sections(stem, decks._product_decks())
        values = {"sleeves": "", "deck_box": ""}
        can_hold = bool(status and status.status == "owned" and status.intact)
        if status is not None:
            values = {f: getattr(status, f, "") or "" for f in HOLDER_FIELDS}
        return _product_title(inv, name), "product", SHARED, values, sections, can_hold
    if holder_id.startswith("pairing/"):
        summary = decks.find_summary(holder_id)
        title = summary["title"] if summary else holder_id
        return title, "deck", SHARED, {"sleeves": "", "deck_box": ""}, decks.load_deck(holder_id), False
    summary = decks.find_summary(holder_id)
    if summary is None:
        raise decks.DeckNotFound(f"no deck {holder_id!r}")
    built = summary.get("status") == "built"
    values = {"sleeves": summary.get("sleeves") or "", "deck_box": summary.get("deck_box") or ""}
    sections = None
    if built:
        from decklab.lib.decks import assembled
        stored = inventory.current().deck(holder_id)
        if stored is not None:
            parsed = decks.parse_deck(stored.data, stored.slug, stored.kind, space=stored.space)
            if assembled.get(parsed):
                sections = assembled.sections(parsed)
    if sections is None:
        version = pool._built_version(summary, warnings) if built else "target"
        sections = decks.load_deck(holder_id, version)
    return (summary["title"], "deck", player_owner(summary.get("player")), values,
            sections, built)


def kit(holder_id, sections=None, inv=None, usage=None, *, values=None, owner=None, owners=None,
        holder_reader=None, hidden=None):
    """A holder's sleeves and deck box and the enough-sleeves rule (the one
    place its wording comes from, for every page):

        {holder, title, owner, sleeves: Ref | None, deck_box: Ref | None,
         need, short, spare, shared_with, warnings, info}

    holder_id is a deck id (None for a deck not saved yet); a product deck's holder is its whole product
    ("product/<stem>"), which needs sleeves for all its decks, so sections is
    ignored for products. For a deck, sections is the list to count (the
    editor's draft, assembly's selected version, the deck page's shown list);
    by default its built version when built, else its target. values
    ({"sleeves", "deck_box"}, keyword only) stands in for the values in the
    holder's file, as for an editor draft. inv and usage (from holders())
    save reading them again. owner (keyword only) stands in for the
    holder's owner (player_owner of an editor draft's Played by). owners
    (permissions.accessory_owners; None: everything) names the other
    holders the viewer can't see only as "one of User1's decks". Page readers also
    pass holder_reader(h) and hidden(h), so a public kit cannot publish a private deck.

    short and spare are sleeves missing and left over (0 unless the sleeves
    are linked): the holder's own need against the row's quantity, whoever
    else uses the row. shared_with is the titles of the other holders in the
    same linked sleeves (one design may sleeve several decks and products,
    and it's up to the players not to play two of them at once, so it's
    never a warning; a holder owners can't see is "one of User1's decks").
    warnings break a rule; info only says what can't be checked
    (it never goes in warnings, whose texts mentioning "Sleeves" the editor's
    tests pin)."""
    inv = read() if inv is None else inv
    warnings, info, read_warnings = [], [], []
    holder_id = None if holder_id is None else _holder_id(holder_id)
    title, kind, own_owner, own_values, own_sections, can_hold = _own(holder_id, read_warnings)
    if owner is not None:
        own_owner = owner
    if kind == "product" or sections is None:
        sections = own_sections
    if values is not None:
        own_values = {**own_values, **{k: v or "" for k, v in values.items() if k in HOLDER_FIELDS}}
    if usage is None:
        usage = holders(inv, read_warnings)
    need = sleeve_need(sections)
    refs = {f: resolve(own_values.get(f), f, inv) for f in HOLDER_FIELDS}
    out = {"holder": holder_id, "title": title, "owner": own_owner, **refs, "need": need, "short": 0, "spare": 0,
           "shared_with": [], "warnings": warnings, "info": info}
    others = [h if visible(h.get("owner", SHARED), owners) and (holder_reader is None or holder_reader(h))
              else {**h, "title": hidden(h) if hidden else hidden_title(h["owner"], h["kind"])}
              for entries in usage.values() for h in entries if h["holder"] != holder_id]
    for f in HOLDER_FIELDS:
        ref = refs[f]
        if ref is not None and ref["state"] == "linked":
            row_owner = inv.rows_by_id[ref["id"]]["owner"]
            if not usable(row_owner, own_owner):
                warnings.append(_not_theirs(f, ref, row_owner, own_owner, kind))

    sleeves = refs["sleeves"]
    if sleeves is None:
        if kind == "product" and can_hold:
            warnings.append(f"{title} is kept intact: choose its sleeves (it needs {need}).")
    elif sleeves["state"] == "kind_mismatch":
        warnings.append(_mismatch("sleeves", sleeves))
    elif sleeves["state"] == "text":
        info.append(f"“{sleeves['value']}” isn't in the accessories list, so Deck Lab can't check "
                    f"there are enough.")
    else:
        quantity = sleeves["quantity"]
        out["short"], out["spare"] = max(0, need - quantity), max(0, quantity - need)
        if out["short"]:
            whose = "this product" if kind == "product" else "this deck"
            warnings.append(f"Not enough sleeves: {whose} needs {need}{_need_words(sections)} and "
                            f"{sleeves['label']} has {quantity}. Get {out['short']} more of the same "
                            f"sleeves, or fix the count on the Accessories page.")
        # Other holders in the same sleeves are fine (one design may sleeve several decks and products;
        # it's up to the players not to play two of them at once): named, never a warning.
        out["shared_with"] = [other["title"] for other in others if other["field"] == "sleeves"
                              and other["state"] == "linked" and other["value"] == sleeves["id"]]

    box = refs["deck_box"]
    if box is not None:
        if box["state"] == "kind_mismatch":
            warnings.append(_mismatch("deck_box", box))
        elif box["state"] == "text":
            info.append(f"“{box['value']}” isn't in the accessories list, so Deck Lab can't check it's free.")
        else:
            users = 1 + sum(1 for o in others if o["field"] == "deck_box" and o["state"] == "linked"
                            and o["value"] == box["id"])
            if users > box["quantity"]:
                warnings.append(f"{users} decks use {box['label']} but {box['quantity']} "
                                f"{'is' if box['quantity'] == 1 else 'are'} recorded.")
            if box["capacity"] is not None and need > box["capacity"]:
                whose = "this product" if kind == "product" else "this deck"
                warnings.append(f"Too big for its deck box: {whose} has {need} sleeved cards"
                                f"{_need_words(sections)} and {box['label']} holds {box['capacity']}. "
                                f"Choose a bigger deck box, or fix its capacity on the Accessories page.")
    return out


def _not_theirs(f, ref, row_owner, holder_owner, kind):
    """"Sleeves X are User1's: ...": a holder uses an accessory that isn't its owner's or shared."""
    whose = ("a product" if kind == "product" else "this deck") if holder_owner == SHARED else         f"{owner_name(holder_owner)}'s deck"
    uses = "only shared ones" if holder_owner == SHARED else f"only {owner_name(holder_owner)}'s or shared ones"
    return (f"{_FIELD_WORDS[f]} {ref['label']} {'are' if f == 'sleeves' else 'is'} {owner_name(row_owner)}'s: "
            f"{whose} uses {uses}.")


def _mismatch(f, ref):
    """"Sleeves “x” is a deck box in the accessories list, not sleeves."."""
    return (f"{_FIELD_WORDS[f]} “{ref['value']}” is {_KIND_WORDS[ref['kind']]} in the accessories list, "
            f"not {_KIND_WORDS[f]}.")


# ------------------------------------------------------------------ checking

def _id_shaped(value):
    """A value written like a generated id (a slug with a hyphen), not a
    plain word such as "red" that older free text uses."""
    return bool(ID_RE.match(value)) and "-" in value


def check(root=None):
    """Every broken invariant (HISTORY.md's Accessories entry, I2 and I4-I8;
    owners that aren't a home profile or shared, and holders using another
    owner's accessories) and accessories.csv's own problems, as text; [] when all is well, from
    one inventory snapshot (the pinned one, else one pinned for the call). root is accepted
    and unused (the gate calls the older check(root), which shortened deck files' paths: a deck
    is named by its id now)."""
    if not inventory.is_pinned():
        with inventory.pinned():
            return check(root)
    inv = read()
    problems = list(inv.problems)
    warnings = []
    found, strays = _scan(warnings)
    usage = _usage(found, inv)

    owners = owner_ids()
    if len(owners) > 1:         # without config.json's profiles, owners can't be checked
        for row in inv.rows_by_id.values():
            if row["owner"] not in owners:
                problems.append(f"{row['id']}: its owner {row['owner']!r} isn't a home profile or {SHARED}")
    for h in found:
        for f in HOLDER_FIELDS:
            row = inv.rows_by_id.get(" ".join(h[f].split()))
            if row is not None and row["kind"] == f and not usable(row["owner"], h["owner"]):
                problems.append(f"{h['title']}: {_not_theirs(f, resolve(row['id'], f, inv), row['owner'], h['owner'], h['kind'])}")

    pictures = inventory.current().accessory_images
    named = set()
    for row in inv.rows_by_id.values():
        name = image_name(row)
        if name is not None:
            named.add(name)
            if name not in pictures:
                problems.append(f"{row['id']}: its picture {name} is missing (image put {name} to store it)")
    for name in sorted(pictures):
        if name not in named:
            problems.append(f"The picture {name} belongs to no accessory (image remove {name} takes it away)")

    for where, f, value in strays:
        problems.append(f"{where} has {_FIELD_WORDS[f]} {value!r} but isn't "
                        f"{'owned and kept intact' if where.startswith(_STATUS_STRAY) else 'built'}; remove it")
    for value, entries in sorted(usage.items()):
        for h in entries:
            if h["state"] == "kind_mismatch":
                problems.append(f"{h['title']}: {_mismatch(h['field'], resolve(value, h['field'], inv))}")
            elif h["state"] == "text" and _id_shaped(value):
                problems.append(f"{h['title']}: {_FIELD_WORDS[h['field']]} {value!r} isn't an accessory id "
                                "(accessories list shows them)")
    for row in inv.rows_by_id.values():
        users = used_by(usage, row)
        if row["kind"] == "sleeves":
            # Several holders may share one design: each is checked against the row's quantity on its own.
            for h in users:
                if h["need"] > row["quantity"]:
                    problems.append(f"{h['title']} needs {h['need']} sleeves and {label(row)} has {row['quantity']}")
        elif row["kind"] == "deck_box":
            if len(users) > row["quantity"]:
                problems.append(f"{len(users)} decks use {label(row)} but {row['quantity']} "
                                f"{'is' if row['quantity'] == 1 else 'are'} recorded")
            for h in users:
                if row["capacity"] is not None and h["need"] > row["capacity"]:
                    problems.append(f"{h['title']} has {h['need']} sleeved cards and {label(row)} "
                                    f"holds {row['capacity']}")
    return problems


def _and(words):
    words = list(words)
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="python -m decklab.lib.accessories",
                                     description="Check the accessories inventory against the decks.")
    parser.add_argument("--check", action="store_true", help="report broken rules; exit 1 if there are any")
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 0
    from decklab.lib import venv
    venv.activate()             # the inventory may be in the database
    try:
        with inventory.pinned():
            problems = check()
            stale = inventory.pinned_stale()
    except inventory.Unavailable as e:
        print(f"The database isn't available: {e}", file=sys.stderr)
        return 2
    if stale:
        print(f"Note: {stale}.", file=sys.stderr)
    for text in problems:
        print(text)
    if not problems:
        print(NO_PROBLEMS)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
