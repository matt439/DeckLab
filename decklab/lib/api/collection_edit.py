"""The Collection page's edits: single cards added, changed or removed in a
space's collection, and CSV imports from scanner and collection apps
(HISTORY.md, "Accounts and member collections"). Imported when first needed, by
feature_routes.dispatch, like the Tokens page's API.

    GET  /api/collection/rows?space=<id>    rows_view(): the snapshot's rows and sha256
    GET  /api/collection/download?space=<id>    download_view(): the collection as a CSV to save (E7-S30)
    POST /api/collection/save               save_card(body): add, edit or remove one row
    POST /api/collection/bulk               bulk_set(body): set many rows' condition and language at once
    POST /api/collection/import/preview     import_preview(body): read an upload, match it to Scryfall
    POST /api/collection/import/apply       import_apply(body): merge a preview, with the raw file
    POST /api/collection/trade/preview      collection_trade.preview_trade(body): a trade's preview (E7-S22)
    POST /api/collection/trade              collection_trade.save_trade(body): a trade as one change
    GET  /api/printings?name=<exact name>   printings_view(): a card's paper printings, newest first

A space (lib/spaces.py; "space" in the query or body, home by default) is
whose collection: the shared home space or a member's own space in the
inventory database. Runtime writes create no collection files. Every write needs
collection.edit on the space (guard.py, after the read rule): only its own
profiles, home's Matt and User1 (E10-S29, E10-S43). Receipts stay the route for recorded orders and
products (python -m decklab.db receive, the Receipts page): this is for cards
that come from nowhere Deck Lab records.

The collection is the inventory's (decklab/lib/inventory): the page reads
inventory.current() and every write is one inventory.apply of the
collection's operations (inventory/ops_collection.py). Runtime uses the database;
tests may use the file inventory backend. It keeps the CSV rules (AGENTS.md): eight
columns, one row per identity key (set, collector_number, finish), sorted by
set and then collector number (rules.sort_key). The page sends the sha256 it
loaded: that of the collection's canonical CSV bytes (the sha256 of nothing
while the space has no cards), checked by the operation under the backend's
lock; 409 {"error",
"sha256", "rows"} with the collection as it is now otherwise. Each change has
a message and the actor who made it:

    add card Llanowar Elves (FDN 227) in User2's collection           (by User2)
    import 42 cards into the home collection from manabox.csv           (by Matt)

Each is one audited change set in the database. The file backend writes plain
files only in test fixtures; it is not a runtime rollback route. Inventory
changes are not committed to git.

Imports: collection_import owns CSV detection, format conversion and upload
reading; the original parser names remain available here. This module keeps
the matching rules, mutable limits and persisted preview lifecycle.
The upload (at most MAX_IMPORT bytes of text and MAX_IMPORT_ROWS
rows) is read as one of FORMATS, told apart by its header row (column names
compared without case):

    manabox     ManaBox's CSV export: Name, Set code, Set name, Collector number,
                Foil (normal|foil|etched), Rarity, Quantity, ManaBox ID, Scryfall ID,
                Purchase price, Misprint, Altered, Condition, Language, ...
                (needs name, set code, collector number, foil, quantity)
    deckbox     Deckbox's inventory export: Count, Tradelist Count, Name, Edition,
                Edition Code?, Card Number, Condition, Language, Foil, Signed, ...
                (needs count, name, edition, card number; the set is Edition Code
                when there is one, else Edition, a set name, matched to the card's
                printings by name)
    moxfield    Moxfield's collection export: Count, Tradelist Count, Name, Edition,
                Condition, Language, Foil, Tags, Last Modified, Collector Number, ...
                (needs count, name, edition, collector number)
    collection  collection.csv's own columns (name, set, collector_number, finish,
                quantity; condition, language, notes optional)

Each row is matched to Scryfall: by set and collector number (a card
printing, not a token or art card, whose card is the row's name), else by
name and set (when the set has one printing of it), else it is a problem
("printing unknown"), as is a name Scryfall doesn't know, an online-only
printing or a finish it wasn't printed in. Conditions become NM, LP, MP, HP or
DMG (CONDITIONS; anything else stays blank, never assumed), languages
Scryfall's codes (LANGUAGES). Ordinary basic lands are dropped by
the collection's rules (rules.ordinary_basic: kept when foil, etched, noted as full art or special,
or already tracked in the collection), and rows naming one identity key
are merged. A field with a control character is a problem, a language
that isn't one of LANGUAGES goes blank, and notes starting with = + - or @
(which a spreadsheet would run as a formula) are a problem: condition and
language only ever hold their known values or nothing, and names must be
Scryfall's (so "+2 Mace" is fine).

The preview is kept in IMPORTS_DIR as <profile>.json for IMPORT_TTL seconds,
holding the upload's text, its file name and format, checked source rows and
source-set groups before merging, the problems and basics left out, and the
token that names it: one pending preview per profile, so a new
preview replaces the last (whose token then gets 410). Previews are read one
at a time (_preview_lock): a second preview while one is being checked is
refused at once with 429 ("another import is being checked"), rather than
holding another upload in memory while it waits. Applying a preview keeps
the upload unchanged (as UTF-8 text) as one of the space's raw imports,
named <date>-<file name>.csv in the inventory (stored in the database;
file-backend tests use an imports/ folder), unless they would then hold more than
MAX_IMPORTS_FOLDER bytes (413), and merges it additively
(rules.merge_rows: quantities add on the identity key), in one change with
the raw file. Rows with problems block the apply unless "skip_problems"
leaves them out, or explicit "skip_groups" names every unresolved source set.
Group selection leaves out all that set's source rows, valid ones included,
then merges the retained contributions; the upload itself stays unchanged.

The limits: 20,000 rows is a large collection. A ManaBox export's row is
about 120-180 bytes (its Scryfall ID alone is 36), so 20,000 rows are about
3 MB, and MAX_IMPORT is 4 MB (200 bytes a row). The raw files are kept for
good, so a space's raw imports are capped at 50 MB in all.
"""
import contextlib
import csv
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from collections import Counter
from datetime import date
from pathlib import Path

from decklab.lib import cards, config, decks, inventory, pool, spaces
from decklab.lib.inventory import files as inventory_files
from decklab.lib.inventory import ops_collection as ops
from decklab.lib.inventory import rules

from . import common, guard
from .carddata import _index_info, _require_cards
from .collection import space_param
from .common import MAX_NAME, NUMBER_RE, SET_RE, _CONTROL_RE, ApiError, _keys, _parse_body, _public, _unique
from .settings import _web_actor, _writer
# Parser helpers have one implementation; their limits and matching stay here.
from .collection_import import (_condition, _finish, _language, _norm, _source_rows, _too_many_rows,
                                detect, read_review, read_upload, review_rows)

# Import previews waiting to be applied. Tests patch it.
IMPORTS_DIR = config.DATA / "collection-imports"

FIELDS = rules.FIELDS
FINISHES = ("nonfoil", "foil", "etched")
MAX_SAVE_BODY = 16 * 1024           # bytes: a row and the original's key
MAX_BULK_KEYS = 50000               # rows a bulk set names at most (more than any collection holds)
MAX_BULK_BODY = 4 * 1024 * 1024     # bytes of its request (about 70 a key)
MAX_IMPORT = 4 * 1024 * 1024        # bytes of an upload's text (20,000 ManaBox rows are about 3 MB)
MAX_IMPORT_BODY = 2 * MAX_IMPORT + 64 * 1024    # bytes of its request (JSON escapes quotes and line ends)
MAX_IMPORT_ROWS = 20000             # rows of an upload read at most
MAX_IMPORT_APPLY_BODY = 256 * 1024  # the 20,000 short group ids fit; within the HTTP edit-body limit
MAX_IMPORTS_FOLDER = ops.MAX_IMPORTS     # bytes a space's raw imports may hold in all
MAX_FILENAME = 200
MAX_QUANTITY = 9999
MAX_TEXT = {"condition": 40, "language": 20, "notes": 500}
MAX_REASON = 200
IMPORT_TTL = 60 * 60                # seconds a preview can be applied for
EMPTY_SHA = hashlib.sha256(b"").hexdigest()
FORMATS = ("manabox", "deckbox", "moxfield", "collection")
# What a spreadsheet would run as a formula at the start of a cell.
FORMULA_STARTS = ("=", "+", "-", "@")
# One import preview read at a time (the module docstring).
_preview_lock = threading.Lock()

CONDITIONS = ("NM", "LP", "MP", "HP", "DMG")
# Each app's condition words (lowercase, "_" and "-" read as spaces) as
# NM/LP/MP/HP/DMG. ManaBox uses Cardmarket's scale, one step stricter than
# TCGplayer's; Deckbox's "Played" is TCGplayer's moderately played.
_CONDITION_WORDS = {
    "mint": "NM", "near mint": "NM", "nm": "NM", "m": "NM",
    "lightly played": "LP", "light played": "LP", "slightly played": "LP", "lp": "LP", "sp": "LP",
    "good (lightly played)": "LP", "excellent": "LP", "ex": "LP",
    "moderately played": "MP", "mp": "MP", "good": "MP", "gd": "MP", "played": "MP", "pl": "MP",
    "heavily played": "HP", "heavy played": "HP", "hp": "HP",
    "damaged": "DMG", "dmg": "DMG", "poor": "DMG", "po": "DMG",
}
_CONDITION_FORMAT = {"manabox": {"light played": "MP", "played": "HP"}}
# Scryfall's language codes, and the names the apps write.
LANGUAGES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
             "pt": "Portuguese", "ja": "Japanese", "ko": "Korean", "ru": "Russian",
             "zhs": "Simplified Chinese", "zht": "Traditional Chinese", "he": "Hebrew", "la": "Latin",
             "grc": "Ancient Greek", "ar": "Arabic", "sa": "Sanskrit", "ph": "Phyrexian", "qya": "Quenya"}
_LANGUAGE_WORDS = {**{name.lower(): code for code, name in LANGUAGES.items()},
                   **{code: code for code in LANGUAGES},
                   "chinese simplified": "zhs", "chinese traditional": "zht", "chinese": "zhs",
                   "portuguese (brazil)": "pt", "jp": "ja", "kr": "ko", "cn": "zhs", "tw": "zht"}


# ---- spaces and the inventory

def _whose(space):
    """How messages name a space's collection."""
    return ops.collection_name(space, spaces.get(space).name)


def _title(space):
    return "The home collection" if space == spaces.HOME else f"{spaces.get(space).name}'s collection"


def _view(sheet):
    """(rows, sha256) of a collection Sheet: ApiError 409 when it can't be read or breaks
    collection.csv's rules (ops.unreadable's words)."""
    problem = ops.unreadable(sheet)
    if problem:
        raise ApiError(409, _public(problem))
    return ops.rows_of(sheet), ops.sha256_of(sheet)


def _read(space, fresh=False):
    """(rows, sha256) of a space's collection as it is: ([], EMPTY_SHA) while it has no cards.
    ApiError 409 for one that breaks collection.csv's rules. fresh: read the backend now rather
    than the request's pinned snapshot (for a 409's "as it is now")."""
    with common.state_errors():
        inv = inventory.backend().load() if fresh else inventory.current()
    return _view(inv.collection(space))


# collection.csv's bytes for rows: its header, sorted by set and collector number, UTF-8
# without a BOM, LF line endings (the inventory's own renderer, decklab/lib/inventory/rules.py).
csv_bytes = rules.collection_csv_bytes


def _rows_json(rows):
    return [{k: row.get(k, "") for k in FIELDS} for row in sorted(rows, key=rules.sort_key)]


def _picture_key(row):
    """A row's identity key as the page writes it (collection.js colKey): "set|number|finish", lowercase."""
    return "|".join(str(row.get(k) or "").lower() for k in ("set", "collector_number", "finish"))


def _pictures(rows):
    """{_picture_key(row): card} for the Card list's thumbnails and its card viewer: the card's data
    (card_lookup._card_json) with the row's own printing's picture, or (a printing not recorded or
    not in the card data) the card's usual one with "exact": false. A row whose name Scryfall doesn't
    know has no entry; {} while the card index isn't ready. Kept apart from the rows, which stay the
    eight columns the sha256 covers."""
    from .card_lookup import _card_json, _shown_printing
    if not _ready():
        return {}
    out = {}
    try:
        for row in rows:
            exact = cards.resolve(row.get("name") or "")
            card = cards.card(exact) if exact else None
            if card is None:
                continue
            p = None
            if row.get("set") and row.get("collector_number"):
                p = cards.printing(row["set"], row["collector_number"])
                printed = cards.printing_card(row["set"], row["collector_number"]) if p else None
                if not printed or printed["name"] != card["name"]:
                    p = None
            out[_picture_key(row)] = {**_card_json(card, p or _shown_printing(card)), "exact": p is not None}
    except RuntimeError:                # the index went away meanwhile: no pictures, the rows still show
        return {}
    return out


def _prices(rows):
    """The Card list's estimates: {"rows": {_picture_key(row): {"usd", "aud"}}, "rate", "rate_date",
    "price_date", "price_error"}. Each is Scryfall's USD price of the row's own printing and finish
    (cards.PRICE_FINISHES), not the cheapest printing's, times the ECB rate: what that copy is worth,
    not what the deck tables would pay. A row with no printing recorded, an unknown printing or no price
    in that finish has no entry. No entries while the card index isn't ready or there's no rate
    (price_error says why). Kept apart from the rows, like the pictures."""
    answer = {"rows": {}, "rate": None, "rate_date": None, "price_date": None, "price_error": None}
    if not _ready():
        return answer
    try:
        rate, rate_date = cards.usd_to_aud()
    except RuntimeError as e:          # offline with no cached rate
        answer["price_error"] = _public(e)
        return answer
    finishes = dict(cards.PRICE_FINISHES)
    try:
        answer.update(rate=rate, rate_date=rate_date, price_date=cards.price_date() or None)
        for row in rows:
            key = finishes.get(row.get("finish") or "nonfoil")
            if not (key and row.get("set") and row.get("collector_number")):
                continue
            p = cards.printing(row["set"], row["collector_number"])
            usd = p.get(key) if p else None
            if usd is not None:
                answer["rows"][_picture_key(row)] = {"usd": usd, "aud": round(usd * rate, 2)}
    except RuntimeError:                # the index went away meanwhile: no prices, the rows still show
        answer["rows"] = {}
    return answer


def _storage(space, rows, prices):
    """The Card list's "In storage only" (E7-S28): {"rows": {_picture_key(row): {"held", "guess"}},
    "error"}. held: the row's copies built decks and intact products hold (pool.InUse), null for a
    basic land (their copies in decks aren't tracked); the rest are in storage. The decks count copies
    by name, so each name's are given first to the rows of the printings the decks' Printings in box
    lines record (recorded, only on a row with some: how many of held those are, exactly), then to those the decks' lists name, then
    the rest to its cheapest rows (prices: _prices; unpriced ones last), with guess true on a row that
    got some of those when another row could have (more rows with room than copies left to place). A row with none held has no entry. collection_sources adds visible, uncontested
    saved-list hints as listed_holders and leaves the rest unattributed; these aren't verified physical-printing assignments.
    The rows are already only for viewers who may see this space's inventory. error: why there are
    no counts (the pool can't be read), else None."""
    answer = {"rows": {}, "error": None}
    if not rows:
        return answer
    if not _ready():
        return {"rows": {}, "error": "The card data isn't ready yet."}
    try:
        p = pool.load_pool() if space == spaces.HOME else pool.load_pool(space)
        by_name = {}
        for row in rows:
            name = cards.resolve(row["name"]) or row["name"]
            if decks.is_basic_land(name):
                answer["rows"][_picture_key(row)] = {"held": None, "guess": False}
            else:
                by_name.setdefault(name, []).append(row)
        held, hinted, recorded = Counter(), Counter(), Counter()
        for deck in p.in_use:
            held.update(deck.cards)
            # A Printings in box record says where a card's copies are; its saved list's hints don't.
            exact = {key[0] for key, copies in deck.recorded.items() if copies > 0}
            recorded.update(deck.recorded)
            hinted.update({key: copies for key, copies in deck.printings.items() if key[0] not in exact})
        aud = {k: v["aud"] for k, v in prices["rows"].items()}
        for name, named in by_name.items():
            left = held[name]
            if not left:
                continue
            given, exact = {}, {}
            for source in (recorded, hinted):
                for row in named:
                    key = _picture_key(row)
                    take = min(left, int(row["quantity"]) - given.get(key, 0),
                               source[(name, row["set"].lower(), row["collector_number"], row["finish"] or "nonfoil")])
                    if take > 0:
                        given[key] = given.get(key, 0) + take
                        left -= take
                        if source is recorded:
                            exact[key] = take
            room = [r for r in named if int(r["quantity"]) > given.get(_picture_key(r), 0)]
            spare = sum(int(r["quantity"]) - given.get(_picture_key(r), 0) for r in room)
            # A guess only when there's a choice: more rows with room, and fewer copies to place than room.
            choice = len(room) > 1 and left < spare
            guessed = set()
            # Cheapest first; an unpriced row isn't known to be cheap, so it comes after the priced ones.
            for row in sorted(room, key=lambda r: (aud.get(_picture_key(r)) is None, aud.get(_picture_key(r), 0),
                                                   rules.sort_key(r))):
                if not left:
                    break
                key = _picture_key(row)
                take = min(left, int(row["quantity"]) - given.get(key, 0))
                given[key] = given.get(key, 0) + take
                left -= take
                if choice:
                    guessed.add(key)
            for key, copies in given.items():
                answer["rows"][key] = {"held": copies, "guess": key in guessed}
                if exact.get(key):
                    answer["rows"][key]["recorded"] = exact[key]
    except (ValueError, OSError, csv.Error, RuntimeError) as error:
        return {"rows": {}, "error": "The copies in decks couldn't be worked out"
                + ("." if space == spaces.HOME and not guard.sees_home_records() else f": {_public(error)}")}
    from .collection_sources import VISIBILITY_READ_ERRORS, annotate, anonymous
    try:
        sees, records = guard.deck_reader(), guard.sees_home_records()
    except VISIBILITY_READ_ERRORS:
        return anonymous(answer)
    return annotate(answer, p.in_use, by_name, sees=sees, records=records)


def _extras(space, shown):
    """The rows' prices (_prices), storage counts (_storage), storage locations and the storage
    box's count (collection_locations), for every answer that sends rows."""
    from . import collection_locations as places
    prices = _prices(shown)
    storage = _storage(space, shown, prices)
    return {"prices": prices, "storage": storage, "locations": places.locations(space, _picture_key),
            "storage_box": places.storage_box(space, shown, storage, _picture_key)}


def _stale(space, sha=None):
    """The 409 for a collection that changed since the page loaded it, with its rows, their prices and
    storage counts (_extras)."""
    rows, now = _read(space, fresh=True)
    shown = _rows_json(rows)
    return ApiError(409, ops.STALE.format(title=_title(space)), sha256=now, rows=shown, **_extras(space, shown))


def _request_sha(value):
    if isinstance(value, str) and common._SHA_RE.fullmatch(value):
        return value
    raise ApiError(400, "sha256 must be the 64-character hash /api/collection/rows gave")


def _apply(space, op, actor, reason=None, expected_revision=None, message=None, return_snapshot=False):
    """Run op through inventory.apply, with message, or else the message the Summary's text will have
    (ops.message words it from the request's collection, without running op twice): (the
    space's collection Sheet after, the Summary). Held under saving.inventory_write_lock()
    (_save_lock with the files backend; the lock order: it first, then the backend's own lock),
    so a collection save waits for another save in the server. The operations' refusals become
    the page's answers: Stale 409 with the collection as it is now, Missing 409 likewise, Invalid 400,
    Conflict 409, Unavailable 503, each with no absolute path in its words. return_snapshot
    opts into the exact committed Inventory instead of its collection Sheet (filing advice)."""
    from . import saving
    if message is None:
        with common.state_errors():
            message = ops.message(inventory.current(), op.kind, op.params)
    try:
        with saving.inventory_write_lock():
            after, summary = inventory.apply(op, actor, message, reason=reason or None,
                                             expected_revision=expected_revision)
    except ops.RepeatsChanged as e:
        raise ApiError(409, str(e), repreview_required=True) from None
    except ops.Stale:
        raise _stale(space) from None
    except ops.Missing as e:
        rows, now = _read(space, fresh=True)
        raise ApiError(409, str(e), sha256=now, rows=_rows_json(rows)) from None
    except ops.TooLarge:
        raise                               # the caller words it (merge_upload: 413)
    except inventory.Unavailable:
        with common.state_errors():
            raise
    except inventory.Invalid as e:
        raise ApiError(400, _public(e)) from None
    except inventory.Conflict as e:
        if expected_revision is not None:
            raise _stale(space) from None
        raise ApiError(409, _public(e)) from None
    except ValueError as e:      # an upload's name already taken on disk
        raise ApiError(409, _public(e)) from None
    return (after if return_snapshot else after.collection(space)), summary


# ---- reading rows

def _ready():
    return _index_info()[0] is not None


def rows_view(space=None):
    """GET /api/collection/rows?space=<id>: {space, sha256 (of the collection
    rendered as collection.csv; of nothing while it has no cards), rows (its
    eight columns, as text, sorted), pictures (_pictures), prices (_prices),
    storage (_storage), locations and storage_box (collection_locations) and editable (may this visitor change it)}. 403 for a space whose inventory the visitor may not see
    (guard.require_sees_inventory)."""
    space = space_param(space)
    guard.require_sees_inventory(space)
    with common.state_errors():
        sheet = inventory.current().collection(space)
    rows, sha = _view(sheet)
    shown = _rows_json(rows)
    return {"space": space, "sha256": sha, "rows": shown, "pictures": _pictures(shown), **_extras(space, shown),
            "editable": guard.allowed(guard.viewer(), "collection.edit", space)}


def download_view(space=None):
    """GET /api/collection/download?space=<id>: {space, filename, csv}, the space's collection
    as collection.csv's text (its eight columns, sorted by set and collector number: what the
    Collection page's import reads back), for the page to save as filename,
    "<space>-collection-<YYYY-MM-DD>.csv" (E7-S30). The header alone while it has no cards.
    403 as rows_view for a space whose inventory the visitor may not see."""
    space = space_param(space)
    guard.require_sees_inventory(space)
    with common.state_errors():
        sheet = inventory.current().collection(space)
    rows, _ = _view(sheet)
    return {"space": space, "filename": f"{space}-collection-{_upload_date()}.csv",
            "csv": csv_bytes(rows).decode("utf-8")}


# ---- matching a row to Scryfall

def _card_printings(exact):
    card = cards.card(exact)
    return card["printings"] if card else []


def match(row, set_name=None):
    """(row, problem): row with the card's exact Scryfall name and, when the
    set has one printing of it, that collector number; problem is None, or
    why it can't be put in the collection as it is. set_name: a set's name
    to find the set by when row["set"] is blank (Deckbox's Edition)."""
    row = dict(row)
    exact = cards.resolve(row["name"]) if row["name"] else None
    number, set_code = row["collector_number"], row["set"]
    if set_code and number:
        p = cards.printing(set_code, number)
        if p is not None and cards.printing_card(set_code, number) is not None:
            printed = cards.resolve(p["name"])
            if printed == exact:
                row["name"] = printed
                return row, _printing_problem(p, row)
    if exact is None:
        return row, f"Scryfall has no card named {row['name']!r}" if row["name"] else "No card name"
    row["name"] = exact
    found = _card_printings(exact)
    if not set_code and set_name:
        wanted = set_name.strip().lower()
        codes = _unique(s for s, n in found
                        if ((cards.printing(s, n) or {}).get("set_name") or "").lower() == wanted)
        set_code = row["set"] = codes[0] if len(codes) == 1 else ""
    if not set_code and number:
        # No set to go by: the one printing with that collector number, if only one has it.
        codes = _unique(s for s, n in found if n == number)
        set_code = row["set"] = codes[0] if len(codes) == 1 else ""
    in_set = [n for s, n in found if s == set_code]
    if set_code and number and number not in in_set:
        return row, (f"printing unknown: {set_code.upper()} {number} isn't a printing of {exact}"
                     if in_set or not found else
                     f"printing unknown: {exact} wasn't printed in {set_code.upper()} with number {number}")
    if len(in_set) == 1:
        row["collector_number"] = in_set[0]
        return row, _printing_problem(cards.printing(set_code, in_set[0]), row)
    if in_set:
        return row, f"printing unknown: {set_code.upper()} has {len(in_set)} printings of {exact}; give its number"
    where = f"in {set_code.upper()}" if set_code else "without a set"
    return row, f"printing unknown: no printing of {exact} {where}"


def _printing_problem(p, row):
    if p["digital"] or "paper" not in p["games"]:
        return f"{row['set'].upper()} {row['collector_number']} is an online-only printing"
    if p["finishes"] and row["finish"] not in p["finishes"]:
        return f"{row['set'].upper()} {row['collector_number']} wasn't printed {row['finish']}"
    return None


# ---- one card

def _reduction_guard(op, profile, confirmation):
    """Bind an advisory warning to the exact edit and both inventory revision counters.

    A changed built deck or intact product needs a new review even when the collection's
    rows did not change. The write checks both counters under its transaction lock.
    """
    from .collection_guards import ReductionCheckError, reduction_warnings
    space = op.params["space"]
    with common.state_errors():
        before = inventory.current()
        try:
            after, _ = inventory.preview(op, refresh=False)
        except ops.Stale:
            raise _stale(space) from None
        except ops.Missing as exc:
            rows, now = _read(space, fresh=True)
            raise ApiError(409, str(exc), sha256=now, rows=_rows_json(rows)) from None
        try:
            warnings = reduction_warnings(before, after, space)
        except ReductionCheckError as exc:
            warnings = [{"message": str(exc)}]
        if warnings:
            content = {"profile": profile["id"], "kind": op.kind, "params": op.params,
                       "revision": before.revision, "decks_revision": before.decks_revision, "warnings": warnings}
            token = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            if confirmation != token:
                rows, now = _view(before.collection(space))
                raise ApiError(409, "These copies may be in use. Review the warning before saving.",
                               in_use=warnings, confirm_in_use=token, sha256=now, rows=_rows_json(rows))
    return before.revision, before.decks_revision


def _text(value, key, required=False, limit=None):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ApiError(400, f"{key} must be text")
    value = value.strip()
    limit = limit or MAX_TEXT.get(key, MAX_NAME)
    if len(value) > limit or _CONTROL_RE.search(value):
        raise ApiError(400, f"{key} must be one line of at most {limit} characters")
    if required and not value:
        raise ApiError(400, f"{key} is needed")
    return value


def _quantity(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)) \
            or not re.fullmatch(r"\d{1,4}", str(value).strip()) or not 1 <= int(str(value).strip()) <= MAX_QUANTITY:
        raise ApiError(400, f"quantity must be a whole number from 1 to {MAX_QUANTITY}")
    return str(int(str(value).strip()))


def _row_input(value):
    """A request's row: collection.csv's eight columns (condition, language
    and notes may be left out or blank), checked and tidied."""
    if not isinstance(value, dict):
        raise ApiError(400, "row must be an object")
    _keys(value, ("name", "set", "collector_number", "finish", "quantity"), ("condition", "language", "notes"))
    row = {"name": _text(value["name"], "name", True),
           "set": _text(value["set"], "set", True).lower(),
           "collector_number": _text(value["collector_number"], "collector_number", True),
           "finish": value["finish"], "quantity": _quantity(value["quantity"]),
           **{k: _text(value.get(k), k) for k in ("condition", "language", "notes")}}
    if not SET_RE.fullmatch(row["set"]):
        raise ApiError(400, "set must be Scryfall's set code: 2-8 letters and digits")
    if not NUMBER_RE.fullmatch(row["collector_number"]):
        raise ApiError(400, "collector_number must be the printing's collector number")
    if row["finish"] not in FINISHES:
        raise ApiError(400, f"finish must be {', '.join(FINISHES)}")
    for key in ("condition", "language", "notes"):
        if row[key].startswith(FORMULA_STARTS):
            raise ApiError(400, f"{key} can't start with = + - or @ (a spreadsheet would run it as a formula)")
    return row


def _key_input(value, name="original"):
    if not isinstance(value, dict):
        raise ApiError(400, f"{name} must be {{\"set\", \"collector_number\", \"finish\"}}")
    _keys(value, ("set", "collector_number", "finish"))
    if not all(isinstance(value[k], str) for k in value):
        raise ApiError(400, f"{name}'s values must be text")
    return (value["set"].strip().lower(), value["collector_number"].strip(), value["finish"])


def save_card(body):
    """POST /api/collection/save {"profile", "space"?, "sha256", "action":
    "add" | "edit" | "remove", "row"? (add, edit: the eight columns; a remove may send it, unread),
    "original"? (edit, remove: {"set", "collector_number", "finish"} of the
    row as the page loaded it), "reason"? (up to 200 characters, for the
    audit trail), "confirm_in_use"? (the token returned with an in-use warning),
    "location"? (add, edit: the row's storage location, "" clears it; left out,
    an edit keeps it: collection_locations.location_input, E8-S22)}.

    With the card index ready, the name must be a card's exact Scryfall name
    (fixed to its spelling) and set and number one of its paper printings in
    that finish (400 otherwise). An add of a listed identity key adds to that
    row's quantity ("merged": true; differing conditions or languages go
    blank with a note, as rules.merge_rows does). An edit that would give the row
    another listed row's key is refused (400): change that row instead. An
    ordinary basic land isn't added (AGENTS.md: only special basics are
    tracked) unless it's foil or its notes say full art.

    Returns {ok, sha256, rows (the whole new list), pictures (_pictures of
    the row saved, for its thumbnail), prices and storage (_extras, of the whole list), merged, stale_tables (_stale_tables)}; 409 {error,
    sha256, rows} when the file has changed since sha256."""
    data = _parse_body(body, MAX_SAVE_BODY)
    profile = _writer(data)
    space = space_param(data.get("space"))
    guard.require_space_write(profile, "collection.edit", space)
    action = data.get("action")
    if action not in ("add", "edit", "remove"):
        raise ApiError(400, "action must be add, edit or remove")
    required = {"add": ("row",), "edit": ("row", "original"), "remove": ("original",)}[action]
    # A remove may send the row too (the page does); only original names it.
    _keys(data, ("profile", "action", "sha256", *required), ("space", "reason", "row", "confirm_in_use", "location"))
    sha = _request_sha(data["sha256"])
    row = _row_input(data["row"]) if "row" in data and action != "remove" else None
    original = _key_input(data["original"]) if "original" in data else None
    reason = data.get("reason", "")
    if not isinstance(reason, str) or len(reason) > MAX_REASON:
        raise ApiError(400, f"reason must be text of at most {MAX_REASON} characters")
    reason = decks.clean_title(reason)
    confirmation = data.get("confirm_in_use")
    if confirmation is not None and (not isinstance(confirmation, str) or not common._SHA_RE.fullmatch(confirmation)):
        raise ApiError(400, "confirm_in_use must be the warning's 64-character review token")
    if row is not None and _ready() and not rules.ordinary_basic(row):     # basics: the operation's
        row, problem = match(row)
        if problem:
            raise ApiError(400, f"The card can't be saved: {problem}")
    params = {"space": space, "sha256": sha, "whose": _whose(space)}
    if action != "remove" and "location" in data:
        from .collection_locations import location_input
        with common.state_errors():
            location = location_input(data["location"])
        if location is not None:
            params["location"] = location
    if row is not None:
        params["row"] = row
    if original is not None:
        params["original"] = list(original)
    op = inventory.Op(f"collection.{action}", params)
    revision = None
    if action != "add":
        revision, decks_revision = _reduction_guard(op, profile, confirmation)
        op = inventory.Op(op.kind, {**params, "expect_decks_revision": decks_revision})
    sheet, summary = _apply(space, op, _web_actor(profile), reason, expected_revision=revision)
    rows, now = _view(sheet)
    shown = _rows_json(rows)
    changed = [r for r in shown if row is not None and _picture_key(r) == _picture_key(row)]
    return {"ok": True, "sha256": now, "rows": shown, "pictures": _pictures(changed), **_extras(space, shown),
            "merged": bool(summary.counts.get("merged")), "stale_tables": _stale_tables(space)}


def _stale_tables(space):
    """The decks of space whose owned-vs-needed tables are out of date after a collection write
    (commits._stale_list of that space's decks: {"id", "title", "sha256", "count", "changes",
    "may_update"}; only for a visitor who may see the space's inventory, R6d). The collection's
    writes don't refresh them (only receipts and order changes do). [] when they can't be
    worked out: the save stands either way."""
    from .commits import _stale_list          # when used: the editor's modules, which this
    from .library import _load_pool           # page's reads never need
    try:
        return _stale_list(_load_pool([], space), only={space})
    except Exception as e:      # noqa: BLE001 - only a note after a saved write
        common._log(f"The out-of-date tables after a collection save can't be worked out: {type(e).__name__}: {e}")
        return []


# ---- many rows at once

def _bulk_keys(value):
    """A bulk request's keys: a list of 1 to MAX_BULK_KEYS {"set", "collector_number", "finish"},
    as identity keys, each named once (400 otherwise)."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_BULK_KEYS:
        raise ApiError(400, f"keys must be a list of 1 to {MAX_BULK_KEYS:,} rows' "
                            "{\"set\", \"collector_number\", \"finish\"}")
    keys = []
    for item in value:
        key = _key_input(item, "Each key")
        # A collector number may be blank (an old special basic's row); the set and finish never are.
        if not SET_RE.fullmatch(key[0]) or key[1] and not NUMBER_RE.fullmatch(key[1]) or key[2] not in FINISHES:
            raise ApiError(400, "Each key must be a row's set code, collector number and finish")
        keys.append(key)
    if len(set(keys)) != len(keys):
        raise ApiError(400, "keys names a row more than once")
    return keys


def bulk_set(body):
    """POST /api/collection/bulk {"profile", "space"?, "sha256", "keys": [{"set",
    "collector_number", "finish"}, ...], "condition"? (one of CONDITIONS), "language"? (one of
    LANGUAGES' codes), "only_blank"? (true by default)}: the Card list's "Set condition & language"
    (E7-S29). Sets the condition and/or language (at least one) of each named row: with only_blank
    only where that field is blank, else wherever it differs. Nothing else of a row changes (its
    quantity, name and notes, so no copies are reduced and no in-use warning applies), and rows
    already as asked are left out, so the change names only the rows it changed.

    The changed rows are one collection.apply ("edit 91 rows in the home collection"), one change
    set. Returns {ok, sha256, rows (the whole list), prices and storage (_extras), changed (rows
    changed), stale_tables (_stale_tables)}; with nothing to change, changed 0 and nothing is
    written. 409 {error, sha256, rows} when the collection changed since sha256 or a key isn't
    listed (as save_card's)."""
    data = _parse_body(body, MAX_BULK_BODY)
    profile = _writer(data)
    space = space_param(data.get("space"))
    guard.require_space_write(profile, "collection.edit", space)
    _keys(data, ("profile", "sha256", "keys"), ("space", "condition", "language", "only_blank"))
    sha = _request_sha(data["sha256"])
    keys = _bulk_keys(data["keys"])
    wanted = {}
    if data.get("condition") is not None:
        if not isinstance(data["condition"], str) or data["condition"] not in CONDITIONS:
            raise ApiError(400, f"condition must be {', '.join(CONDITIONS)}")
        wanted["condition"] = data["condition"]
    if data.get("language") is not None:
        if not isinstance(data["language"], str) or data["language"] not in LANGUAGES:
            raise ApiError(400, f"language must be one of Scryfall's codes ({', '.join(LANGUAGES)})")
        wanted["language"] = data["language"]
    if not wanted:
        raise ApiError(400, "Give a condition, a language or both")
    only_blank = data.get("only_blank", True)
    if not isinstance(only_blank, bool):
        raise ApiError(400, "only_blank must be true or false")
    rows, now = _read(space)
    if now != sha:
        raise _stale(space)
    by_key = {rules.ident(r): r for r in rows}
    if any(key not in by_key for key in keys):
        raise ApiError(409, ops.MISSING, sha256=now, rows=_rows_json(rows))
    edits = []
    for key in keys:
        old = by_key[key]
        new = {**old, **{k: v for k, v in wanted.items() if old[k] != v and not (only_blank and old[k])}}
        if new != old:
            edits.append([list(key), new])
    if not edits:
        shown = _rows_json(rows)
        return {"ok": True, "sha256": now, "rows": shown, **_extras(space, shown), "changed": 0, "stale_tables": []}
    op = inventory.Op("collection.apply", {"space": space, "sha256": sha, "whose": _whose(space),
                                           "edits": edits, "removals": []})
    sheet, _ = _apply(space, op, _web_actor(profile))
    rows, now = _view(sheet)
    shown = _rows_json(rows)
    return {"ok": True, "sha256": now, "rows": shown, **_extras(space, shown), "changed": len(edits),
            "stale_tables": _stale_tables(space)}


# ---- imports

def _imports_dir():
    return Path(IMPORTS_DIR)


def _preview_path(profile):
    """A profile's one pending preview (a profile id is a slug, safe as a file name)."""
    return _imports_dir() / f"{profile['id']}.json"


def _mb(size):
    return f"{size / (1024 * 1024):.1f} MB"


def _prune_previews():
    now = time.time()
    for path in _imports_dir().glob("*.json"):
        try:
            if now - path.stat().st_mtime > IMPORT_TTL:
                path.unlink(missing_ok=True)
        except OSError:
            pass


def _filename(value):
    name = _text(value, "filename", True, MAX_FILENAME)
    return re.split(r"[\\/]", name)[-1] or "import.csv"


_safe_stem = ops.safe_stem


def import_preview(body):
    """POST /api/collection/import/preview {"profile", "space"?, "filename",
    "text"}: read an upload (at most MAX_IMPORT bytes, 413 otherwise, and
    MAX_IMPORT_ROWS rows, 400 otherwise) without changing anything, one at a
    time (429 while another is being checked), replacing the profile's last
    preview. Returns {token (for import/apply, for IMPORT_TTL seconds),
    format (FORMATS), rows [{the eight columns, "line", "problem"}],
    problems [{"line", "message"}], adds {"rows", "cards"} (the rows and
    cards without problems that the apply would merge), dropped_basics
    (ordinary basic lands left out, in cards), sha256 (the collection's now), repeat_imports
    [{name, imported_at, imported_by}] (identical earlier uploads in this space; unknown
    provenance is null, and no raw contents are returned), groups (source-set counts and
    original lines), source_rows (unmerged checked rows with source group, set and problem)}."""
    data = _parse_body(body, MAX_IMPORT_BODY)
    profile = _writer(data)
    space = space_param(data.get("space"))
    guard.require_space_write(profile, "collection.edit", space)
    _keys(data, ("profile", "filename", "text"), ("space",))
    filename = _filename(data["filename"])
    text = data["text"]
    if not isinstance(text, str):
        raise ApiError(400, "text must be the file's contents, as text")
    size = len(text.encode("utf-8"))
    if size > MAX_IMPORT:
        raise ApiError(413, f"That file is {_mb(size)}, and an import is limited to {MAX_IMPORT // (1024 * 1024)} MB "
                            f"(about {MAX_IMPORT_ROWS:,} rows of cards): split it into smaller files and import "
                            f"each one.")
    _require_cards()
    if not _preview_lock.acquire(blocking=False):
        raise ApiError(429, "Another import is being checked right now; try again in a moment.")
    try:
        existing, sha = _read(space)
        review = read_review(text, {rules.ident(r) for r in existing})
        fmt, rows, problems, dropped = (review[k] for k in ("format", "rows", "problems", "dropped_basics"))
        good = [r for r in rows if not r["problem"]]
        repeats = ops.repeat_imports(inventory.current(), space, [(filename, text)])
        token = secrets.token_hex(16)
        _prune_previews()
        # Retain unmerged contributions so leaving out a source set never removes another
        # group's copies merely because matching gave them the same final printing identity.
        record = {"version": 4, "token": token, "space": space, "profile": profile["id"], "filename": filename,
                  "text": text, "format": fmt, "good": [{k: r[k] for k in FIELDS} for r in good],
                  "problems": problems, "dropped_basics": dropped, "repeat_imports": repeats,
                  "source_rows": review["source_rows"], "groups": review["groups"]}
        try:
            inventory_files.atomic_write(_preview_path(profile),
                                         json.dumps(record, ensure_ascii=False).encode("utf-8"))
        except OSError as e:
            raise ApiError(500, f"The preview couldn't be kept on the PC: {_public(e)}") from None
    finally:
        _preview_lock.release()
    return {"token": token, "format": fmt, "rows": rows, "problems": problems,
            "adds": {"rows": len(good), "cards": sum(int(r["quantity"]) for r in good)},
            "dropped_basics": dropped, "sha256": sha, "repeat_imports": repeats,
            "source_rows": review["source_rows"], "groups": review["groups"]}


def _load_preview(token, space, profile):
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ApiError(400, "token must be the one import/preview gave")
    path = _preview_path(profile)
    gone = ApiError(410, "That import preview has expired (they last an hour) or a newer preview replaced it; "
                         "upload the file again.")
    try:
        if time.time() - path.stat().st_mtime > IMPORT_TTL:
            path.unlink(missing_ok=True)
            raise FileNotFoundError(token)
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise gone from None
    if not isinstance(record, dict) or record.get("version") not in (3, 4) \
            or not hmac.compare_digest(str(record.get("token") or ""), token):
        raise gone
    if record.get("space") != space or record.get("profile") != profile["id"]:
        raise ApiError(400, "That preview is for another collection or person; upload the file again.")
    return path, record


def _selected_import(record, value):
    """The reviewed retained import and its unresolved problems, from server-owned groups.

    Group ids name this token's original source rows. No client row facts are accepted,
    and selecting groups never rematches cards against a possibly changed card index.
    """
    if not isinstance(value, list) or len(value) > MAX_IMPORT_ROWS \
            or any(not isinstance(ident, str) or not re.fullmatch(r"g[1-9]\d{0,4}", ident) for ident in value):
        raise ApiError(400, f"skip_groups must list at most {MAX_IMPORT_ROWS:,} source group ids from this preview")
    if len(set(value)) != len(value):
        raise ApiError(400, "skip_groups names a source group more than once")
    if record.get("version") != 4:
        raise ApiError(409, "Upload the file again to review its source sets.", repreview_required=True)
    groups = {group["id"]: group for group in record["groups"]}
    if any(ident not in groups for ident in value):
        raise ApiError(400, "skip_groups must name source groups from this preview")
    selected = set(value)
    rows, problems, dropped = review_rows(record["source_rows"], selected)
    skipped = [{"line": source["line"], "message": source["problem"]} for source in record["source_rows"]
               if source["group"] in selected and source["problem"] is not None]
    reviewed = {**record, "good": [{k: row[k] for k in FIELDS} for row in rows if row["problem"] is None],
                "problems": skipped, "dropped_basics": dropped,
                "excluded_groups": [group for group in record["groups"] if group["id"] in selected]}
    return reviewed, problems


def import_apply(body):
    """POST /api/collection/import/apply {"profile", "space"?, "token",
    "sha256", "skip_problems"? | "skip_groups"?}: merge a preview into the space's
    collection, additively (rules.merge_rows), and keep the upload
    unchanged as imports/<date>-<file name>.csv, in one change "import <n>
    cards into <User2's collection | the home collection> from <file
    name>" (merge_upload). Rows with problems refuse the apply (400 with
    "problems") unless skip_problems leaves them out, or every unresolved source set is
    explicitly selected in skip_groups. A selected group leaves out all its source rows,
    valid ones included; excluded_groups reports those separately. The choices are mutually
    exclusive. Returns {ok, sha256,
    rows (the whole new list), prices and storage (_extras), added {"rows" (new rows), "cards"}, skipped
    (problem rows left out), raw (the saved upload's repo path), stale_tables (_stale_tables)}; 409
    {error, sha256, rows} when the collection changed since sha256, 410 for
    an expired preview. If the matching earlier uploads changed, 409 with
    repreview_required:true asks for a fresh preview before anything is written."""
    data = _parse_body(body, MAX_IMPORT_APPLY_BODY)
    profile = _writer(data)
    space = space_param(data.get("space"))
    guard.require_space_write(profile, "collection.edit", space)
    _keys(data, ("profile", "token", "sha256"), ("space", "skip_problems", "skip_groups"))
    sha = _request_sha(data["sha256"])
    skip = common._flag(data, "skip_problems")
    preview_path, record = _load_preview(data["token"], space, profile)
    problems = record["problems"]
    if "skip_groups" in data:
        if "skip_problems" in data:
            raise ApiError(400, "Choose skip_groups or skip_problems, not both")
        record, problems = _selected_import(record, data["skip_groups"])
    if problems and not skip:
        raise ApiError(400, f"{len(problems)} {'row has a problem' if len(problems) == 1 else 'rows have problems'}"
                            f": fix the file, or import the rest without them.", problems=problems)
    if not record["good"]:
        if record.get("excluded_groups"):
            raise ApiError(400, "There's nothing to import after leaving out those source sets.")
        raise ApiError(400, "There's nothing to import: every row has a problem or is an ordinary basic land.")
    answer = merge_upload(space, profile, sha, record, filing=True)
    preview_path.unlink(missing_ok=True)
    return answer


def merge_upload(space, profile, sha, record, message=None, filing=False):
    """Merge record's good rows (a preview's record: filename, text, format,
    good, problems, dropped_basics) into the space's collection, and keep
    its text as the upload, in one change (import_apply's: the operation
    collection.import). message: the change's message, "{cards}" standing
    for the cards merged, instead of "import {cards} cards into ... from
    <file name>".
    The caller has checked collection.edit. Returns import_apply's answer."""
    problems = record["problems"]
    whose = _whose(space)
    if filing:
        from . import collection_filing
    op = inventory.Op("collection.import", import_params(space, sha, record, message, capture_additions=filing))
    try:
        result, summary = _apply(space, op, _web_actor(profile), **({"return_snapshot": True} if filing else {}))
    except ops.TooLarge as e:
        raise ApiError(413, f"The imports folder of {whose} holds {_mb(e.held)}, and this file ({_mb(e.size)}) "
                            f"would take it over its limit of {e.limit // (1024 * 1024)} MB (the raw files are "
                            f"kept for good): ask an admin to tidy {ops.paths.imports_dir(space)} first.") from None
    sheet = result.collection(space) if filing else result
    rows, now = _view(sheet)
    counts = summary.counts
    shown = _rows_json(rows)
    with inventory.pinned(result) if filing else contextlib.nullcontext():
        answer = {"ok": True, "sha256": now, "rows": shown, **_extras(space, shown),
                  "added": {"rows": counts["added_rows"], "cards": counts["cards"]}, "skipped": len(problems),
                  "raw": summary.extra["raw"][0], "stale_tables": _stale_tables(space),
                  **({"excluded_groups": record["excluded_groups"]} if "excluded_groups" in record else {})}
        if filing:
            facts = summary.extra.get("added_printings")
            try:
                answer["filing"] = collection_filing.after_import(result, space, profile, facts, counts["cards"])
            except Exception:       # optional advice must never turn a committed import into a failed save
                common._log("Post-import filing advice could not be calculated; the import was saved.")
                answer["filing"] = collection_filing.unknown(space, profile, facts, counts["cards"])
    return answer


def import_params(space, sha, record, message=None, capture_additions=False):
    """The collection.import operation's parameters for merge_upload's record (also the
    precon add's, api/precons.py, inside its precon.add): no upload kept when record has no
    good rows."""
    good = [{k: r[k] for k in FIELDS} for r in record["good"]]
    whose = _whose(space)
    return {"space": space, "sha256": sha, "whose": whose, "sources": [[record["filename"], good]],
            "uploads": [[f"{_upload_date()}-{_safe_stem(record['filename'])}", record["text"]]] if good else [],
            "message": message or f"import {{cards}} cards into {whose} from {record['filename']}",
            "limit": MAX_IMPORTS_FOLDER, "fmt": record["format"], "problems": record["problems"],
            "dropped_basics": record.get("dropped_basics") or 0,
            **({"excluded_groups": record["excluded_groups"]} if "excluded_groups" in record else {}),
            "expected_repeats": [r["name"] for r in record["repeat_imports"]]
            if "repeat_imports" in record else None,
            **({"capture_additions": True} if capture_additions else {})}


def _upload_date():
    """Today's date for an upload's file name (the tests fix it)."""
    return date.today().isoformat()


# ---- printings

def printings_view(name=None):
    """GET /api/printings?name=<exact name>: {name, printings: [{set,
    set_name (the set's name; the code in capitals until the card data has
    names), collector_number, finishes, released, img_small (its small
    picture's Deck Lab address, or None)}]}: every paper printing
    of the card (not tokens or art cards), newest first. 404 for a name
    that isn't a card's exact Scryfall name (the Add card sheet's names come
    from /api/cards/search)."""
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or _CONTROL_RE.search(name):
        raise ApiError(400, f"Give a card name of at most {MAX_NAME} characters")
    _require_cards()
    exact = cards.resolve(name.strip())
    if exact is None or exact != name.strip() and exact.lower() != name.strip().lower():
        raise ApiError(404, f"No card named {name.strip()!r}")
    from .card_lookup import image_url
    found = []
    for set_code, number in _card_printings(exact):
        p = cards.printing(set_code, number)
        if p is None or p["digital"] or "paper" not in p["games"]:
            continue
        found.append({"set": set_code, "set_name": p.get("set_name") or set_code.upper(),
                      "collector_number": number, "finishes": list(p["finishes"]), "released": p["released_at"],
                      "img_small": image_url(set_code, number, "small") if p.get("image_small") else None})
    found.sort(key=lambda e: e["released"] or "", reverse=True)
    return {"name": exact, "printings": found}
