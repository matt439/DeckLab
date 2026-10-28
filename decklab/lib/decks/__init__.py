"""Read and write deck files, and load the product decks.

Deck files live in magic/decks/casual/ and magic/decks/commander/, and a
person's in magic/people/<id>/decks/<kind>/ (lib/spaces.py: their ids are
"<id>/<kind>/<slug>", home's stay "<kind>/<slug>"). They are written by hand and by Claude as well as by Deck Lab, so the page only
rewrites the parts it owns (PLAN.md part 2):

- the header fields Format, Archetype, Played by, Status, Built version,
  Target bracket, Sleeves and Deck box ("Built version: target" or
  "owned-only" says which list a built deck holds, when the file has both;
  Sleeves and Deck box are a built deck's accessories, each an id from
  magic/accessories.csv or older free text such as a colour);
- the fenced decklist blocks (the target list under a "## Decklist" heading
  and the list under "### Owned-only version"). A file with no "## Decklist"
  block has no target list Deck Lab can read: list_decks() reports it with an
  error and load_deck() refuses it, rather than treating it as empty;
- the rows and total row of the owned-vs-needed table, which always describe
  the target list (set_table checks each card's Need against it);
- Deck Lab's labels at the start of a Notes cell: the leading ";"-separated
  parts that are each exactly in one of LABEL_RE's forms, "1 on the way
  (order 2026-09-29-shop-a)", "2 in use in Gruul Ramp", "not counted, no
  price: ..." on the total row, and the older "on the way (Wretched Ranks
  precon)". Anything from the first other part on is hand-written;
- the "1 USD = 1.4237 AUD (ECB rate of 2026-09-28), pulled 2026-09-28" stamp
  in the paragraph above the table (PRICE_STAMP). A table with no rate
  statement above it gets a PRICE_NOTE paragraph. One with a rate worded
  some other way can't be repriced (spans["prices_other"]; render_deck_file
  raises DeckFileError, and other_rate() says what was found), since the old
  wording would then contradict the new prices: any paragraph above the
  table, the stamp's own included, that states a conversion factor ("USD 1 =
  AUD 1.4224", "1.4224 AUD per USD", "converted at 1.4224", "price x
  1.4224") near a currency or rate word. Amounts ("A$45", "45.50 AUD") and
  prose that only names currencies don't count;
- the "Decklist changed in Deck Lab" line under the header (MARKER).

Everything else, including the rest of each Notes cell, is kept byte for
byte. An owned part that didn't change is written back exactly as it was read
too (line endings included), so a save that only changes Status leaves hand
formatting in the decklist and table alone; a part that changed is rebuilt by
the formatters.

Usage:

    from decklab.lib import decks, pool

    deck = decks.read_deck_file("magic/decks/casual/gruul-ramp.md")
    deck.target["Deck"][0].quantity = 3
    decks.set_status(deck, "building")
    decks.set_table(deck, *pool.deck_table(deck))     # worked out from deck.target as edited
    decks.mark_decklist_changed(deck, "2026-10-05")
    text = decks.render_deck_file(deck)
    inventory.apply(inventory.Op("deck.save", {"deck_id": deck.deck_id, "text": text,
                                               "base_sha256": deck.sha256}), actor, message)

    decks.list_decks()                        # deck files + product decks
    decks.beginner_box_pairings()             # the 45 two-half Beginner Box decks
    decks.load_deck("casual/gruul-ramp", "owned")
    decks.load_deck("user2/casual/elves")   # a deck in User2's space
    decks.load_deck("product/fdn-beginner-box/cats")
    decks.load_deck("pairing/cats+vampires")
    decks.find_summary("pairing/vampires+cats")   # a library summary by id, or None
    decks.engine_kind(summary)                # "commander" or "constructed"

The editor's saves (api.save_deck) go through apply_edit(), which applies
the lists and header fields the page sends and marks a decklist change;
table_changes() says how a file's table differs from rows pool.py worked
out, which is how "this table is out of date" is found.

This module never computes quantities or prices for the table: pool.py works
those out and hands over finished TableRow objects.

Where things are (every name in the submodules is also decks.<name>):

- decklist.py: decklist lines and blocks in the Arena/MTGO format;
- deckfile.py: the DeckFile model and parse_deck()/read_deck_file();
- edit.py: header fields, apply_edit(), Notes labels and set_table();
- render.py: render_deck_file(), other_rate() and new_deck_text();
- tokencards.py: a built deck's optional "Token cards" header line, the token cards it packs
  (parse_token_cards, set_token_cards), which other decks then count as in use;
- printings.py: a built deck's optional "Printings in box" header line, which physical printing
  of its cards is in the box (parse_printings, set_printings), a record that reserves nothing;
- cover.py: the optional "Cover card" header line (parse_cover, set_cover) and the automatic
  cover (auto_cover_line), the card whose art stands for the deck in the library;
- this file: everything that uses the folders (DECKS_DIR, and each person
  space's decks folder from lib/spaces.py): slugs and paths, the product
  decks (from the inventory's products: decklab/lib/inventory,
  inventory.current()) and the library.
  Tests patch DECKS_DIR, REPLACE_WAITS and the library functions on decks,
  so they and everything that reads them stay here.

Where deck files are read from (decklab/PLAN.md phase 4; the phase 4 design's R1): the
inventory's snapshot (inventory.current().decks: the deck files as the files backend reads them
under its root, or the database's texts), never the folders themselves. deck_files(),
_space_files(), find_deck_file(), existing_deck_id(), list_decks() and load_deck() list and
find the snapshot's decks, still as Paths in the space folders (deck_dir()), so every caller
keeps its paths; read_deck_file(path) parses the snapshot's text of the deck at that path, and
reads the file itself only for a path outside every space's deck folders (a fixture, a draft).
So one pinned snapshot gives the pool, the tokens, the accessories and the deck pages the same
decks as the inventory. Deck Lab saves decks only through the inventory's deck operations
(inventory/ops_decks.py); the tests write a file in the files backend's tree directly with
decklab/tests/deck_files.py.
"""
import errno
import hashlib
import re
import unicodedata
from itertools import combinations
from pathlib import Path

from decklab.lib import spaces
from decklab.lib.config import MAGIC, REPO

# The parts in their own files. Their names are all here too, so callers
# keep using decks.<name>.
from . import cover, deckfile, decklist, edit, printings, render, tokencards
from .cover import (COVER_FIELD, COVER_SECTIONS, auto_cover_line, cover_field, format_cover, parse_cover, set_cover)
from .tokencards import (TOKEN_CARDS_FIELD, TokenCardLine, format_token_cards, has_token_cards,
                         parse_token_cards, set_token_cards, token_cards)
from .printings import (PRINTINGS_FIELD, PrintingLine, format_printings, has_printings, parse_printings,
                        set_printings)
from .opponents import USUAL_OPPONENTS_FIELD, parse_usual_opponents, set_usual_opponents
from .deckfile import (
    _ABOUT, _AMOUNT_AFTER_RE, _AMOUNT_BEFORE_RE, _CONTEXT_START_RE, _CUR, _NUM, _ONE, _QUOTE_CUT_RE,
    BUILT_VERSIONS, COUNT_RE, DATE_RE, FIELD_RE, FORMATS, HEADING_RE, KINDS, MARKER, MARKER_RE,
    OWNED_FIELDS, PLAYERS, PRICE_NOTE, PRICE_STAMP, PRICE_STAMP_RE, RATE_CONTEXT_RE, RATE_FORMS,
    RATE_NEAR, STATUSES, TABLE_COLUMNS, TABLE_HEADER, TABLE_RULE, TOTAL_RE, DeckFile, HeaderField,
    PriceStamp, TableRow, TotalRow, _count, _find_block, _headings, _leading_word, _Line, _lines,
    _one_line, _paragraphs, _parse_row, _rate_in, _section_end, _unbold, _without_stamp, parse_deck,
    read_deck_file)
from .decklist import (
    _BASIC_KEYS, BASIC_LANDS, CATEGORY_MAX, LINE_RE, MAIN_SECTIONS, SECTIONS, SET_IN_NAME_RE, DeckFileError,
    DeckLine, DecklistError, _section_name, card_count, categories, clean_category, clean_sections,
    format_decklist, format_line, is_basic_land, parse_decklist, parse_line, section_header)
from .edit import (
    BRACKET_NUMBERS, EDIT_FIELDS, LABEL_RE, _card_key, _check_rows_match_target, _merge_notes,
    _owned_key, _set_leading_word, _split_notes, apply_edit, clean_label, format_aud,
    mark_decklist_changed, set_built_version, set_deck_box, set_field, set_player, set_sleeves, set_status,
    set_table, set_target_bracket, sort_table_rows, table_changes)
from .render import (
    _block_text, _cell, _header_line, _lead, _marker_text, _plain, _price_text, _read_rows,
    _read_stamp, _render_header, _row, _with_endings, format_field, format_table_row,
    format_total_row, new_deck_text, other_rate, render_deck_file)

_read_file = read_deck_file             # deckfile's: read and parse a file on disk

DECKS_DIR = MAGIC / "decks"
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# Windows device names: con.md or aux.md can be written, but git can't add them.
RESERVED_SLUGS = {"con", "prn", "aux", "nul"} | {f"{p}{n}" for p in ("com", "lpt") for n in range(10)}
MAX_SLUG = 60
# Seconds between tries to replace a file something else has open (about 2 s in all): Forge's
# results (forge/common._write_atomic) and the tests' deck files (tests/deck_files.py).
REPLACE_WAITS = (0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8)
NO_DECKLIST = ("no fenced decklist block under a '## Decklist' heading, so its Planned list "
               "can't be read")

BEGINNER_BOX = "fdn-beginner-box"


class DeckNotFound(LookupError):
    """No deck with that id, or no such version of it."""


# ---------------------------------------------------------------- writing

def _slug_problem(slug):
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        return f"bad deck slug {slug!r}: use lowercase letters, digits and single hyphens"
    if slug in RESERVED_SLUGS:
        return f"bad deck slug {slug!r}: it's a Windows device name, which can't be a file name (an export writes each deck as a file)"
    return None


def valid_slug(slug):
    """True if slug can name a deck file: lowercase letters, digits and single
    hyphens, and not a Windows device name such as con or aux."""
    return _slug_problem(slug) is None


# Letters NFKD doesn't split into a plain letter and an accent.
_ASCII_LETTERS = str.maketrans({"æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe", "ø": "o", "Ø": "O",
                                "ß": "ss", "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th", "ł": "l", "Ł": "L"})
# Apostrophes a title can be typed with (straight, curly ’ and ‘, the letter
# apostrophe ʼ, a backtick, an acute accent), which a file name drops.
_APOSTROPHES = str.maketrans(dict.fromkeys("'’‘ʼ`´"))


def clean_title(text):
    """A title (or archetype) as Deck Lab writes it: without invisible
    format characters (Unicode category Cf: zero-width spaces, bidi
    overrides, soft hyphens), and with each run of whitespace of any kind
    made one space, trimmed. The duplicate check and the change's message then
    see the text the page shows."""
    text = "".join(ch for ch in str(text) if unicodedata.category(ch) != "Cf")
    return " ".join(text.split())


def title_slug(title):
    """The file name a new deck's title gives (without .md): lowercase ASCII
    letters and digits joined by single hyphens, accents dropped ("Lórien
    Elves" -> "lorien-elves", "Cats + Vampires" -> "cats-vampires"), at most
    MAX_SLUG characters. Apostrophes of every kind are dropped, so a
    possessive stays one word and a phone's curly one gives the same name as
    the PC's ("Ajani’s Pride" and "Ajani's Pride" -> "ajanis-pride"). Any
    other character separates words, whether ASCII or not ("Cats–Vampires"
    and "Cats-Vampires" -> "cats-vampires"); invisible format characters
    (see clean_title) are dropped. "" when nothing is left; check it with
    valid_slug()."""
    text = str(title).translate(_ASCII_LETTERS).translate(_APOSTROPHES)
    text = unicodedata.normalize("NFKD", text).translate(_APOSTROPHES)    # a full-width ＇ becomes '
    text = "".join(ch for ch in text if not unicodedata.combining(ch) and unicodedata.category(ch) != "Cf")
    text = "".join(ch if ch.isascii() and ch.isalnum() else "-" for ch in text.lower())
    slug = re.sub(r"-+", "-", text).strip("-")
    return slug[:MAX_SLUG].rstrip("-")


def existing_deck_id(slug, space=spaces.HOME):
    """The id of a deck file whose name is slug in either folder of a space
    (compared without case, as Windows does), or None."""
    for path in deck_files(space):
        if path.stem.lower() == str(slug).lower():
            return spaces.join_deck_id(space, path.parent.name, path.stem)
    for old_id, current_id in _snapshot().deck_aliases.items():
        old_space, _, old_slug = split_id(old_id)
        if old_space == space and old_slug.lower() == str(slug).lower():
            return current_id
    return None


def deck_dir(kind, space=spaces.HOME):
    """The folder of a space's deck files of a kind: magic/decks/<kind> at home,
    magic/people/<id>/decks/<kind> for a person (spaces.SpaceNotFound for a
    space config.json doesn't list). It may not exist yet."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    if space == spaces.HOME:
        return DECKS_DIR / kind
    return spaces.get(space).deck_dir(kind)


def deck_path(kind, slug, space=spaces.HOME):
    """The path of a deck file, after checking the kind and slug (and that
    config.json lists the space: ValueError otherwise)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    problem = _slug_problem(slug)
    if problem:
        raise ValueError(problem)
    try:
        return deck_dir(kind, space) / f"{slug}.md"
    except spaces.SpaceNotFound as e:
        raise ValueError(str(e)) from None


def split_id(deck_id):
    """(space, kind, slug) of a deck file's id ("casual/x" or "user2/casual/x");
    ValueError for an id that isn't a deck file's (product/..., pairing/...)."""
    space, kind, slug = spaces.split_deck_id(deck_id)
    if kind not in KINDS or "/" in slug:
        raise ValueError(f"{deck_id!r} isn't a deck file's id")
    return space, kind, slug


def path_for_id(deck_id):
    """The path a deck file's id names, after checking it as deck_path does; ValueError otherwise."""
    space, kind, slug = split_id(deck_id)
    return deck_path(kind, slug, space)


def deck_id_of(path):
    """The id of the deck file at path, or None when it isn't in a space's deck folder."""
    path = Path(path)
    space = spaces.space_of_path(path)
    if space is None or path.parent.name not in KINDS:
        return None
    return spaces.join_deck_id(space, path.parent.name, path.stem)


def _checked_path(path):
    path = Path(path)
    if not path.is_absolute():
        path = REPO / path
    resolved = path.resolve()
    allowed = [(s.decks / kind).resolve() for s in spaces.list_spaces() for kind in KINDS]
    if resolved.parent not in allowed or resolved.suffix != ".md":
        raise ValueError(f"deck files can only be written in magic/decks/casual or "
                         f"magic/decks/commander, or a person's decks folder: {path}")
    for stem in (path.stem, resolved.stem):
        problem = _slug_problem(stem)
        if problem:
            raise ValueError(problem)
    return resolved


# ------------------------------------------------------------ product decks

def _slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _product_lines(product):
    """[(deck name or None, section, DeckLine)] from one product's card list
    (an inventory Product, rows as read), or None if it isn't a deck list (no
    'deck' or 'section' column)."""
    columns = product.columns or ()
    if "deck" not in columns and "section" not in columns:
        return None
    for column in ("name", "quantity", "finish"):
        if column not in columns:
            raise DeckFileError(f"{product.file}: no {column!r} column")
    out = []
    for n, row in enumerate(product.items, 2):
        section = _section_name(row.get("section") or "deck")
        if section is None:
            raise DeckFileError(f"{product.file} line {n}: unknown section {row['section']!r}")
        if not (row.get("name") or "").strip():
            raise DeckFileError(f"{product.file} line {n}: no card name")
        if row.get("finish") not in ("nonfoil", "foil", "etched"):
            raise DeckFileError(f"{product.file} line {n}: bad finish {row.get('finish')!r}")
        try:
            qty = int(row["quantity"])
        except (TypeError, ValueError):
            raise DeckFileError(f"{product.file} line {n}: bad quantity {row.get('quantity')!r}") from None
        line = DeckLine(qty, row["name"], (row.get("set") or "").lower() or None,
                        row.get("collector_number") or None, row["finish"])
        out.append((row.get("deck") or None, section, line))
    return out


def _product_decks():
    """Every deck in the products' card lists (the inventory's products, by
    file name: decklab/lib/inventory), as dicts with their sections.

    A product that can't be read is listed once, with an "error" and no
    sections, like a deck file that can't be parsed, so one bad row doesn't
    hide the rest of the library. A product's name and format are its own
    (model.Product.name and format), else its title-cased stem and
    "Product deck"; source is where its file is, or would be
    ("magic/products/<file>")."""
    from decklab.lib import inventory
    snapshot = inventory.current()
    cancelled = {row.text("file") for row in snapshot.status.rows
                 if row.text("status").strip().lower() == "cancelled"}
    products = [product for product in snapshot.products if product.file not in cancelled]
    decks = []
    for product in products:
        name, fmt = product.label("deck")
        source = product.path
        try:
            if product.error is not None:
                raise DeckFileError(product.error)
            lines = _product_lines(product)
        except DeckFileError as e:
            decks.append({"id": f"product/{product.stem}", "title": name, "kind": "casual",
                          "format": fmt, "product": product.stem, "deck": None, "source": source,
                          "sections": {}, "error": str(e)})
            continue
        if lines is None:
            continue
        grouped = {}
        for deck_name, section, line in lines:
            grouped.setdefault(deck_name, {}).setdefault(section, []).append(line)
        for deck_name, sections in grouped.items():
            sections = {s: sections[s] for s in SECTIONS if s in sections}
            if deck_name:
                deck_id = f"product/{product.stem}/{_slugify(deck_name)}"
                title = f"{deck_name} ({name})"
            else:
                deck_id, title = f"product/{product.stem}", name
            decks.append({
                "id": deck_id, "title": title,
                "kind": "commander" if "Commander" in sections else "casual",
                "format": fmt, "product": product.stem, "deck": deck_name,
                "source": source, "sections": sections,
            })
    return decks


def _merge(*decklists):
    """Combine decklists, adding up lines for the same printing."""
    merged = {}
    for sections in decklists:
        for name, lines in sections.items():
            out = merged.setdefault(name, {})
            for l in lines:
                key = (l.name, l.set, l.number, l.finish)
                if key in out:
                    out[key].quantity += l.quantity
                else:
                    out[key] = DeckLine(l.quantity, l.name, l.set, l.number, l.finish)
    return {s: list(merged[s].values()) for s in SECTIONS if s in merged}


def _pairings():
    halves = [d for d in _product_decks() if d["product"] == BEGINNER_BOX and not d.get("error")]
    pairs = []
    for a, b in combinations(halves, 2):
        pair_id = f"pairing/{_slugify(a['deck'])}+{_slugify(b['deck'])}"
        pairs.append({
            "id": pair_id, "title": f"{a['deck']} + {b['deck']} (Beginner Box)",
            "kind": "casual", "format": "Beginner Box pairing (40 cards)",
            "product": BEGINNER_BOX, "halves": [a["id"], b["id"]], "source": a["source"],
            "sections": _merge(a["sections"], b["sections"]),
        })
    return pairs


def _summary(deck, **extra):
    sections = deck["sections"]
    summary = {
        "id": deck["id"], "space": spaces.HOME, "title": deck["title"], "kind": deck["kind"],
        "format": deck["format"], "player": None, "status": None, "built_version": None,
        "source": deck["source"], "read_only": True,
        "card_count": card_count(sections),
        "sideboard_count": card_count(sections, ("Sideboard",)),
        "versions": [] if deck.get("error") else ["target"],
    }
    if deck.get("error"):
        summary["error"] = deck["error"]
    summary.update(extra)
    return summary


# ---------------------------------------------------------------- library

def _snapshot():
    """The inventory's snapshot the decks are read from."""
    from decklab.lib import inventory
    return inventory.current()


def deck_files(space=None):
    """Paths of every deck file of a space (None: every space, home first,
    then the people in config.json's order), casual first, each folder by name:
    the inventory snapshot's decks, each at its path in the space's folder."""
    if space is None:
        return [p for _, p in _space_files()]
    try:
        folders = {kind: deck_dir(kind, space) for kind in KINDS}
    except spaces.SpaceNotFound:
        return []
    found = {kind: [] for kind in KINDS}
    for deck in _snapshot().decks.values():
        if deck.space == space:
            found[deck.kind].append(folders[deck.kind] / f"{deck.slug}.md")
    return [p for kind in KINDS for p in sorted(found[kind])]


def _space_files():
    """[(space, path)] of every deck file, in deck_files() order."""
    return [(s, p) for s in spaces.space_ids() for p in deck_files(s)]


def read_deck_file(path, kind=None, space=None):
    """Read and parse one deck file: the inventory snapshot's text of the deck
    at path (a path in a space's deck folder: FileNotFoundError when the
    snapshot has no such deck), or the file itself for a path outside them.
    The kind comes from its folder by default, and the space from where that
    folder is (see parse_deck)."""
    path = Path(path)
    deck_id = _snapshot_id(path, space)
    if deck_id is None:
        return _read_file(path, kind, space)
    from decklab.lib import inventory
    snapshot = _snapshot()
    current_id = inventory.resolve_deck_id(deck_id, snapshot)
    found = snapshot.decks.get(current_id)
    if found is None:
        raise FileNotFoundError(errno.ENOENT, "No such file or directory", str(path))
    if found.error is not None:
        if found.error.startswith("not UTF-8"):
            raise DeckFileError(found.error)
        raise OSError(found.error)
    if current_id != deck_id:
        path = deck_path(found.kind, found.slug, found.space)
    return parse_deck(found.data, found.slug, kind or found.kind, path, space or found.space)


def _snapshot_id(path, space=None):
    """The deck id of a path in a space's deck folder, or None for a path outside them. With
    space, a path straight in that space's folder needs no look at the disk."""
    if path.parent.name not in KINDS:
        return None
    if space is not None:
        try:
            if path.parent == deck_dir(path.parent.name, space):
                return spaces.join_deck_id(space, path.parent.name, path.stem)
        except spaces.SpaceNotFound:
            pass
    return deck_id_of(path)


def text_sha(text):
    """The sha256 the pages send back for a deck's text (str, or the bytes): the sha256 of its
    UTF-8 bytes, the same as the file's on disk."""
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode("utf-8")).hexdigest()


def list_decks():
    """Summaries of every deck file and product deck, for the library page.

    Each summary is a dict: id, space (lib/spaces.py: "home", or the
    person whose decks folder holds it; products and pairings are home's),
    title, kind, format, player, status,
    built_version ("target", "owned" or None) and built_version_text (the
    field as written, or None), sleeves and deck_box (the fields as written,
    or None; present once the file is read), cover_card (the Cover card field as written, or
    None; present once the file is read: see cover.py), source (what messages name it by:
    the deck's id; a product deck's is its products' file), read_only, card_count
    (Commander + Deck), sideboard_count and versions ("target", plus "owned"
    when the file has an owned-only list). A deck file or product file that can't be read is
    still listed, with an "error" and no versions; so is a deck file with no
    fenced block under a "## Decklist" heading, whose target list can't be
    found. A deck file whose name isn't a valid slug (Gruul_Ramp.md) is
    read_only: it can be opened but not saved.
    """
    out = []
    for space, path in _space_files():
        kind, slug = path.parent.name, path.stem
        deck_id = spaces.join_deck_id(space, kind, slug)
        summary = {
            "id": deck_id, "space": space, "title": slug, "kind": kind,
            "format": None,
            "player": None, "status": None, "built_version": None, "built_version_text": None,
            "source": deck_id,
            "read_only": not valid_slug(slug), "card_count": 0, "sideboard_count": 0,
            "versions": [],
        }
        try:
            deck = read_deck_file(path, space=space)
        except (DeckFileError, OSError) as e:
            summary["error"] = str(e)
        else:
            summary.update(
                title=deck.title, format=deck.format, player=deck.player, status=deck.status,
                built_version=deck.built_version, built_version_text=deck.get_field("Built version"),
                sleeves=deck.get_field("Sleeves"), deck_box=deck.get_field("Deck box"),
                cover_card=deck.get_field(COVER_FIELD))
            if deck.kind == "commander":
                summary["target_bracket"] = deck.target_bracket
            if deck.has_decklist:
                summary.update(
                    card_count=card_count(deck.target),
                    sideboard_count=card_count(deck.target, ("Sideboard",)),
                    versions=["target"] + (["owned"] if deck.owned else []))
            else:
                summary["error"] = NO_DECKLIST
        out.append(summary)
    for deck in _product_decks():
        out.append(_summary(deck))
    return out


def beginner_box_pairings():
    """Summaries of all 45 two-half Beginner Box decks (read-only, 40 cards).

    Each also lists its two "halves" (product deck ids)."""
    return [_summary(p, halves=p["halves"]) for p in _pairings()]


def find_deck_file(kind, slug, space=spaces.HOME):
    """The path of an existing deck file, from the space, kind and slug in its id.

    A valid slug maps straight to its file. Any other name is only found
    among the files deck_files() lists, so a hand-named file such as
    Gruul_Ramp.md (read-only in the library) can still be opened, and an id
    like "casual/../x" finds nothing. Raises DeckNotFound."""
    deck_id = spaces.join_deck_id(space, kind, slug)
    from decklab.lib import inventory
    snapshot = _snapshot()
    current_id = inventory.resolve_deck_id(deck_id, snapshot)
    if current_id != deck_id:
        space, kind, slug = split_id(current_id)
        deck_id = current_id
    if kind in KINDS:
        if valid_slug(slug):
            try:
                path = deck_path(kind, slug, space)
            except ValueError:          # a space config.json doesn't list
                raise DeckNotFound(f"no deck {deck_id}") from None
            if deck_id in snapshot.decks:
                return path
        else:
            for path in deck_files(space):
                if path.parent.name == kind and path.stem == slug:
                    return path
    raise DeckNotFound(f"no deck {deck_id}")


def find_deck_id(deck_id):
    """The path of an existing deck file from its id ("casual/x" or
    "user2/casual/x"); DeckNotFound for any other id or a missing file."""
    try:
        space, kind, slug = spaces.split_deck_id(deck_id)
    except ValueError:
        raise DeckNotFound(f"no deck {deck_id!r}") from None
    return find_deck_file(kind, slug, space)


def load_deck(deck_id, version="target"):
    """The sections {section: [DeckLine]} of any deck in the library.

    deck_id is "casual/<slug>", "commander/<slug>", "product/<file>[/<deck>]"
    or "pairing/<half>+<half>" (either order), or a person's
    "<space>/<kind>/<slug>": the ids list_decks() gives.
    version "owned" is the owned-only list, which only deck files can have.
    Raises DeckNotFound, or DeckFileError for a file that can't be read (or,
    for the target version, has no "## Decklist" block).
    """
    try:
        space, kind, rest = spaces.split_deck_id(deck_id)
    except ValueError:
        raise DeckNotFound(f"no deck {deck_id!r}") from None
    if version not in ("target", "owned"):
        raise DeckNotFound(f"unknown version {version!r}")
    if kind in KINDS:
        deck = read_deck_file(find_deck_file(kind, rest, space), space=space)
        if version == "owned":
            if deck.owned is None:
                raise DeckNotFound(f"{deck_id} has no Play-now list")
            return deck.owned
        if not deck.has_decklist:
            raise DeckFileError(f"{deck_id}: {NO_DECKLIST}")
        return deck.target
    if version != "target":
        raise DeckNotFound(f"{deck_id} only has a Planned list")
    if kind == "product":
        for deck in _product_decks():
            if deck["id"] == deck_id:
                if deck.get("error"):
                    raise DeckFileError(deck["error"])
                return deck["sections"]
    elif kind == "pairing":
        halves = rest.split("+")
        for pair in _pairings():
            a, b = pair["id"].split("/", 1)[1].split("+")
            if sorted(halves) == sorted([a, b]):
                return pair["sections"]
    raise DeckNotFound(f"no deck {deck_id!r}")


def _pairing_halves(deck_id):
    """A pairing id's halves, sorted: either order names the same pairing."""
    return sorted(deck_id.split("/", 1)[1].split("+"))


def find_summary(deck_id):
    """The library summary of a deck id, or None when there's no such deck.

    A deck file or product deck is looked up in list_decks() (one that can't
    be read is found too, with its "error"); "pairing/<half>+<half>" in
    beginner_box_pairings(), its halves in either order. The summary's id is
    the library's (a pairing's halves in its order)."""
    if deck_id.startswith("pairing/"):
        wanted = _pairing_halves(deck_id)
        return next((s for s in beginner_box_pairings() if _pairing_halves(s["id"]) == wanted), None)
    from decklab.lib import inventory
    snapshot = _snapshot()
    deck_id = inventory.resolve_deck_id(deck_id, snapshot)
    with inventory.pinned(snapshot):
        return next((s for s in list_decks() if s["id"] == deck_id), None)


def engine_kind(summary):
    """The kind stats, goldfish and forge take for a library summary:
    "commander" for a Commander deck (a deck file, or a product deck with a
    Commander section, like a precon), "constructed" for everything else
    (casual deck files, other product decks and pairings)."""
    return "commander" if summary["kind"] == "commander" else "constructed"
