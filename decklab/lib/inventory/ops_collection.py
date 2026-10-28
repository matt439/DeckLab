"""The collections' operations (decklab/PLAN.md phase 3, area C): one card added, changed or
removed in a space's collection, and rows merged in from an import, each a pure function of
the inventory registered with inventory.register, so the Collection page, "Add a precon" and
`python -m decklab.db collection merge` write through inventory.apply on either backend.

    collection.add      {space, row, sha256?, whose?, where?, location?}
    collection.edit     {space, original, row, sha256?, whose?, expect_decks_revision?, location?}
    collection.remove   {space, original, sha256?, whose?, expect_decks_revision?}
    collection.apply    {space, edits, removals, sha256?, whose?, expect_decks_revision?}
    collection.import   {space, sources, uploads?, sha256?, whose?, message?, limit?, fmt?,
                         problems?, dropped_basics?, expected_repeats?}
    collection.trade    {space, gave, got, sha256?, whose?, expect_decks_revision?}

collection.trade (E7-S22) is a trade as one change: gave is [[set, collector_number, finish,
quantity]] of listed rows, each lowered by quantity (removed when none are left), and got is rows
merged in as an import merges them (merge_rows), with no raw import kept: a trade isn't an import.
A printing may not be both given and got, and no row may be given twice or more copies than it has.

location (E8-S22), when given to an add or an edit, is the row's storage location ("Row 2, B";
"" clears it; rules.clean_location's rules); left out, an edit keeps the row's location, moving it
with the row when the edit changes its printing or finish. A location lives beside the row
(locations.csv; the database's collection_card.location, migration 0016) and goes when the row
does. Before migration 0016 a location can't be saved (Invalid: rules.LOCATION_REQUIRED).

A row is collection.csv's eight columns as text; original is the [set, collector_number,
finish] of the row as the page loaded it. sha256, when given, is the sha256 of the space's
collection as the page (or the command line) last read it, rendered as collection.csv
(files.rendered_sha256: the sha256 of no bytes while the space has no cards): an operation
refuses with Stale when the collection has changed since. whose is how messages name the
collection ("the home collection", "User2's collection"; collection_name() words it when it's left
out). expect_decks_revision, when given for an edit or removal, must still match the
snapshot's decks_revision inside the backend's write lock (DemandChanged otherwise).
collection.apply is several edits ([[original, row]]) and removals ([original]) as one change
(`collection apply`, E7-S26): each runs as collection.edit or collection.remove would, against
the rows the ones before it left, and any refusal refuses them all.

The rules are the ones collection.csv has always had (AGENTS.md, "magic/collection.csv"): one row
per identity key (set, collector_number, finish), merges by rules.merge_rows (quantities add,
notes are combined, a condition or language the copies don't share goes blank with the note
"Merged copies have differing or unreported ..."), and an ordinary basic land is never added
unless that printing is already tracked. An edit replaces the whole row (notes aren't merged)
and may not take another listed row's key.

collection.import merges sources ([[where, rows]], where naming each source in messages, as the
importer always has) and keeps each upload ([[stem, text]]) as a raw import of the space,
named <stem>.csv, or <stem>-2.csv, -3, ... when the space already keeps one of that name. limit
caps the bytes the space's raw imports may hold in all (TooLarge). message words the change,
"{cards}" standing for the cards merged.
expected_repeats, when given, is the earlier matching raw-import filenames the caller reviewed;
a different set refuses with RepeatsChanged before either the cards or imports are written.

Each Summary's text is the change's message ("add card Llanowar Elves (FDN 227) in User2's
collection"); counts are merge_rows' ({cards, added_rows, bumped_rows, skipped_basics}, plus
"merged" for an add); extra["body"] holds lines that say more about the change (the reason is
apply's own), extra["shown"] the row the message names, extra["imports"] the raw files to keep
and extra["raw"] their derived paths. message() words that text beforehand, for
inventory.apply's message, without running the operation.
"""
import hashlib
import re
from pathlib import PurePath

from decklab.lib.state import Conflict, Invalid

from . import Summary, files, paths, register, rules

FIELDS = rules.FIELDS
MAX_IMPORTS = 50 * 1024 * 1024      # bytes a space's raw imports may hold in all (the page's limit)
BASIC_REFUSED = ("Ordinary basic lands aren't tracked in the collection (there are plenty); add a special one "
                 "by saying \"full art\" in its notes, or as foil")
MISSING = "That card isn't in the collection as the page sent it; look at it again."
STALE = "{title} has changed since the page loaded it; look at it again and retry."
REPEATS_CHANGED = "The matching earlier imports have changed since this preview; preview the file again."


class Stale(Conflict):
    """The collection isn't the version the caller read (its sha256 moved on)."""

    def __init__(self, space, title):
        super().__init__(STALE.format(title=title))
        self.space = space


class Missing(Conflict):
    """The row an edit or remove names isn't in the collection any more."""

    def __init__(self, space):
        super().__init__(MISSING)
        self.space = space


class DemandChanged(Conflict):
    """The built lists are no longer the ones a collection reduction warning reviewed."""


class Unreadable(Conflict):
    """The collection's file breaks collection.csv's rules, so nothing can be written to it."""


class RepeatsChanged(Conflict):
    """The raw-import matches differ from those the caller already reviewed."""


class TooLarge(Invalid):
    """The space's raw imports would hold more than the limit: held bytes now, size of the new
    upload(s), limit."""

    def __init__(self, held, size, limit):
        super().__init__(f"The imports would hold {held + size} bytes, over the limit of {limit}")
        self.held, self.size, self.limit = held, size, limit


# ------------------------------------------------------------------ reading a collection

def collection_name(space, name=None):
    """How messages name a space's collection: "the home collection", or "<name>'s collection"
    (name: the person's display name, the space id when it isn't given)."""
    return "the home collection" if space == paths.HOME else f"{name or space}'s collection"


def unreadable(sheet):
    """Why a collection can't be shown or changed (its file couldn't be read, or breaks
    collection.csv's rules, as merge_cards.read checks them), in the page's words; None when it's
    fine. A space with no file is fine: it has no cards yet."""
    why = sheet.error if sheet.error is not None else sheet.strict_error
    if not sheet.exists or why is None:
        return None
    return f"{sheet.path} can't be read: {why}. Fix it on the PC first."


def rows_of(sheet):
    """A collection's rows as collection.csv dicts (the eight columns, as text), in file order."""
    return [{k: row.text(k) for k in FIELDS} for row in sheet.rows]


def sha256_of(sheet):
    """The version a page holds of a collection: the sha256 of it rendered as collection.csv."""
    return files.rendered_sha256(sheet)


def _rows(inv, space, sha256, whose_text):
    """The space's rows as dicts, after checking the file can be read and is the version the
    caller read (sha256, when given)."""
    sheet = inv.collection(space)
    problem = unreadable(sheet)
    if problem:
        raise Unreadable(problem)
    if sha256 is not None and sha256_of(sheet) != sha256:
        raise Stale(space, whose_text[:1].upper() + whose_text[1:])
    return rows_of(sheet)


def _row(value, where="The card"):
    """value as collection.csv's eight columns of text, its quantity a positive whole number
    (Invalid otherwise, before anything else reads it)."""
    row = {k: "" if value.get(k) is None else str(value.get(k)) for k in FIELDS}
    if not re.fullmatch(r"[0-9]+", row["quantity"]) or int(row["quantity"]) <= 0:
        raise Invalid(f"{where}: quantity must be a positive whole number, got {row['quantity']!r}")
    return row


def _label(row):
    return f"{row['name']} ({row['set'].upper()} {row['collector_number']})"


def _location(value):
    """A request's location, cleaned (rules.clean_location), or None when it wasn't given."""
    if value is None:
        return None
    try:
        return rules.clean_location(value)
    except ValueError as e:
        raise Invalid(str(e)) from None


def _locate(before, after, space, key, location, was=None):
    """(after with key's storage location set to location, [a line saying so]); location None
    keeps the location was (the row's key before an edit) had, at key. Invalid before migration
    0016 (before.locations_ready False) for a location that isn't blank."""
    had = before.locations_of(space)
    wanted = had.get(was, "") if location is None else location
    found = after.locations_of(space)
    if found.get(key, "") == wanted:
        return after, []
    if wanted and not before.locations_ready:
        raise Invalid(rules.LOCATION_REQUIRED)
    after = after.with_locations(space, {**found, key: wanted})
    return after, [f"Storage location: {wanted}." if wanted else "Storage location cleared."] \
        if location is not None else []


def _find(rows, original, space):
    key = tuple(original)
    old = next((r for r in rows if rules.ident(r) == key), None)
    if old is None:
        raise Missing(space)
    return old


# ------------------------------------------------------------------ one card

@register("collection.add")
def add(inv, space, row, sha256=None, whose=None, where="the page", location=None):
    """One card added: a listed identity key adds to that row (merge_rows' rules)."""
    whose = whose or collection_name(space)
    location = _location(location)
    row = _row(row)
    rows = _rows(inv, space, sha256, whose)
    keys = {rules.ident(r) for r in rows}
    if rules.ordinary_basic(row) and rules.ident(row) not in keys:
        raise Invalid(BASIC_REFUSED)
    merged = rules.ident(row) in keys
    try:
        rows, counts = rules.merge_rows(rows, [(where, [row])])
    except rules.InvalidCards as e:
        raise Invalid(f"The card can't be added: {e}") from None
    after = inv.with_collection(space, rows)
    if location is not None:
        after, _ = _locate(inv, after, space, rules.ident(row), location)
    return after, Summary(
        f"add card {_label(row)} in {whose}", counts={**counts, "merged": merged}, extra={"shown": row})


def _expect_decks(inv, expected):
    """Checked inside each backend's write lock, beside its inventory revision check."""
    if expected is not None and str(expected) != inv.decks_revision:
        raise DemandChanged("The built decks or intact products changed after the warning was reviewed; "
                            "review it again.")


@register("collection.edit")
def edit(inv, space, original, row, sha256=None, whose=None, expect_decks_revision=None, location=None):
    """The row with original's key replaced by row (notes as given, not merged), its storage
    location set (location given) or kept with it."""
    whose = whose or collection_name(space)
    _expect_decks(inv, expect_decks_revision)
    location = _location(location)
    row = _row(row)
    rows = _rows(inv, space, sha256, whose)
    old = _find(rows, original, space)
    other = next((r for r in rows if rules.ident(r) == rules.ident(row)), None)
    if other is not None and other is not old:
        raise Invalid(f"{other['name']} ({row['set'].upper()} {row['collector_number']}, {row['finish']}) is "
                      f"already listed: change that row's quantity instead.")
    body = []
    if rules.ident(old) != rules.ident(row):
        body.append(f"Was {old['name']} ({old['set'].upper()} {old['collector_number']}, {old['finish']}).")
    rows = [row if r is old else r for r in rows]
    after, said = _locate(inv, inv.with_collection(space, rows), space, rules.ident(row), location, rules.ident(old))
    body.extend(said)
    return after, Summary(
        f"edit card {_label(row)} in {whose}", counts={"cards": int(row["quantity"])},
        extra={"shown": row, "body": body})


@register("collection.remove")
def remove(inv, space, original, sha256=None, whose=None, expect_decks_revision=None):
    """The row with original's key removed (a space with no cards left has no collection)."""
    whose = whose or collection_name(space)
    _expect_decks(inv, expect_decks_revision)
    rows = _rows(inv, space, sha256, whose)
    old = _find(rows, original, space)
    rows = [r for r in rows if r is not old]
    return inv.with_collection(space, rows), Summary(
        f"remove card {_label(old)} in {whose}", counts={"cards": int(old["quantity"] or 0)}, extra={"shown": old})


@register("collection.apply")
def apply_rows(inv, space, edits=(), removals=(), sha256=None, whose=None, expect_decks_revision=None):
    """Several rows edited and removed as one change (see the module docstring)."""
    whose = whose or collection_name(space)
    _expect_decks(inv, expect_decks_revision)
    _rows(inv, space, sha256, whose)
    body = []
    for original, row in edits:
        inv, summary = edit(inv, space, original, row, whose=whose)
        body.append(f"Changed {_label(summary.extra['shown'])}.")
        body.extend(summary.extra["body"])
    for original in removals:
        inv, summary = remove(inv, space, original, whose=whose)
        copies = summary.counts["cards"]
        body.append(f"Removed {_label(summary.extra['shown'])} ({copies} {'copy' if copies == 1 else 'copies'}).")
    words = [f"edit {_rows_word(len(edits))}"] if edits else []
    words += [f"remove {_rows_word(len(removals))}"] if removals else []
    return inv, Summary(f"{' and '.join(words) or 'change no rows'} in {whose}",
                        counts={"edited": len(edits), "removed": len(removals)}, extra={"body": body})


def _rows_word(n):
    return f"{n} row{'' if n == 1 else 's'}"


# ------------------------------------------------------------------ imports

def _sources(sources):
    """[(where, rows)] with each row checked as _row checks it (Invalid naming where)."""
    return [(where, [_row(r, where) for r in found]) for where, found in sources]


def safe_stem(filename):
    """A raw import's name from an upload's file name: its stem in lower case, runs of anything
    but letters and digits as one "-", at most 60 characters ("import" when nothing is left)."""
    stem = re.sub(r"[^a-z0-9]+", "-", PurePath(filename).stem.lower()).strip("-")[:60].strip("-")
    return stem or "import"


def import_name(taken, stem):
    """<stem>.csv, or <stem>-2.csv, -3, ... while taken (a set of names) has it."""
    name, n = f"{stem}.csv", 2
    while name in taken:
        name, n = f"{stem}-{n}.csv", n + 1
    return name


def repeat_imports(inv, space, uploads):
    """Metadata of earlier uploads with identical UTF-8 bytes in this space, by file name.
    uploads is [(stem, text)] as merge takes; raw contents and hashes never leave this helper."""
    digests = {hashlib.sha256(text.encode("utf-8")).hexdigest() for _, text in uploads}
    return [{"name": info.name, "imported_at": info.imported_at, "imported_by": info.imported_by}
            for info in sorted(inv.imports.get(space, ()), key=lambda i: i.name) if info.sha256 in digests]


def batch_repeats(uploads):
    """The later stems whose exact content is supplied more than once in one merge."""
    seen, repeated = set(), []
    for stem, text in uploads:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest in seen:
            repeated.append(stem)
        seen.add(digest)
    return repeated


def _repeat_message(text, repeats, uploads):
    if repeats:
        names = ", ".join(item["name"] for item in repeats[:20])
        if len(repeats) > 20:
            names += f" and {len(repeats) - 20} more"
        text += f"; intentional repeat import (already kept as {names}; quantities added again)"
    if batch_repeats(uploads):
        text += "; intentional repeat import within supplied files (quantities added again)"
    return text


@register("collection.import")
def merge(inv, space, sources, uploads=(), sha256=None, whose=None, message=None, limit=None, fmt="",
          problems=(), dropped_basics=0, expected_repeats=None):
    """Rows merged in additively from sources, each upload kept as a raw import (see the module
    docstring)."""
    whose = whose or collection_name(space)
    repeats = repeat_imports(inv, space, uploads)
    if expected_repeats is not None and {r["name"] for r in repeats} != set(expected_repeats):
        raise RepeatsChanged(REPEATS_CHANGED)
    rows = _rows(inv, space, sha256, whose)
    try:
        merged, counts = rules.merge_rows(rows, _sources(sources))
    except rules.InvalidCards as e:
        raise Conflict(f"The import can't be merged: {e}") from None
    kept = inv.imports.get(space, ())
    taken = {info.name for info in kept}
    imports, raw = [], []
    for stem, text in uploads:
        name = import_name(taken, stem)
        taken.add(name)
        imports.append((space, name, text.encode("utf-8")))
        raw.append(f"{paths.imports_dir(space)}/{name}")
    if limit is not None and imports:
        held = sum(info.size for info in kept)
        size = sum(len(data) for _, _, data in imports)
        if held + size > limit:
            raise TooLarge(held, size, limit)
    body = [f"{counts['added_rows']} new rows, {counts['bumped_rows']} rows added to"
            + (f"; the upload is {raw[0]}" if len(raw) == 1 else
               f"; the uploads are {', '.join(raw)}" if raw else "")
            + (f" ({fmt})." if fmt else ".")]
    problems = list(problems)
    if problems:
        body.append(f"Left out {len(problems)} rows with problems: "
                    + "; ".join(f"line {p['line']}: {p['message']}" for p in problems[:20])
                    + (" ..." if len(problems) > 20 else ""))
    if dropped_basics:
        body.append(f"Left out {dropped_basics} ordinary basic lands.")
    text = _repeat_message((message or "import {cards} cards into " + whose).replace(
        "{cards}", str(counts["cards"])), repeats, uploads)
    return inv.with_collection(space, merged), Summary(
        text, counts=counts, extra={"body": body, "imports": imports, "raw": raw})


# ------------------------------------------------------------------ trades

def _copies_word(n):
    return f"{n} {'copy' if n == 1 else 'copies'}"


@register("collection.trade")
def trade(inv, space, gave, got, sha256=None, whose=None, expect_decks_revision=None):
    """The copies given lowered or removed and the copies got merged in, as one change (see the
    module docstring). extra["gave"] is [(row before, copies given)], extra["got"] the rows got as
    checked; counts are merge_rows' for the cards got plus "gave" (copies) and "removed" (rows)."""
    whose = whose or collection_name(space)
    _expect_decks(inv, expect_decks_revision)
    rows = _rows(inv, space, sha256, whose)
    by_key = {rules.ident(r): r for r in rows}
    if not gave or not got:
        raise Invalid("A trade needs both the cards that left and the cards that came in.")
    given, seen = [], set()
    for item in gave:
        set_code, number, finish, quantity = (str(v) for v in item)
        key = (set_code, number, finish)
        if key in seen:
            raise Invalid(f"{set_code.upper()} {number} {finish} is given twice; give each printing once.")
        seen.add(key)
        if not re.fullmatch(r"[0-9]+", quantity) or int(quantity) <= 0:
            raise Invalid(f"{set_code.upper()} {number} {finish}: the copies given must be a positive whole "
                          f"number, got {quantity!r}")
        old = by_key.get(key)
        if old is None:
            raise Missing(space)
        if int(quantity) > int(old["quantity"]):
            raise Invalid(f"{_label(old)}: {whose} has {_copies_word(int(old['quantity']))}, "
                          f"so {quantity} can't be given.")
        given.append((dict(old), int(quantity)))
    got = [_row(r, "A card got") for r in got]
    both = sorted({_label(r) for r in got if rules.ident(r) in seen})
    if both:
        raise Invalid(f"{', '.join(both)} is both given and got; leave it out of both.")
    kept, removed = [], 0
    for row in rows:
        left = next((n for old, n in given if rules.ident(old) == rules.ident(row)), 0)
        if left and left == int(row["quantity"]):
            removed += 1
            continue
        kept.append({**row, "quantity": str(int(row["quantity"]) - left)} if left else row)
    try:
        merged, counts = rules.merge_rows(kept, [("the cards got", got)])
    except rules.InvalidCards as e:
        raise Invalid(f"The cards got can't be added: {e}") from None
    copies = sum(n for _, n in given)
    text = f"trade in {whose}: gave {copies} {'card' if copies == 1 else 'cards'}, got {counts['cards']}"
    return inv.with_collection(space, merged), Summary(
        text, counts={**counts, "gave": copies, "removed": removed}, extra={"gave": given, "got": got})


TRADE_NAMED = 10                    # cards each side of a trade's words names before "and N more"


def _trade_side(items):
    """"2 Llanowar Elves (FDN 227), 1 Sol Ring (C21 263)": (row, copies) pairs, at most TRADE_NAMED."""
    parts = [f"{n} {row['name']} ({row['set'].upper()} {row['collector_number']}"
             + ("" if row["finish"] == "nonfoil" else f" {row['finish']}") + ")" for row, n in items]
    if len(parts) > TRADE_NAMED:
        parts = parts[:TRADE_NAMED] + [f"and {len(parts) - TRADE_NAMED} more"]
    return ", ".join(parts)


def trade_words(gave, got, who=""):
    """A trade's words for its change set's message, both sides and no prices ("Trade with T:
    gave 2 Llanowar Elves (FDN 227); got 1 Sol Ring (C21 263)"): gave [(row, copies)], got the
    rows kept (trade_tracked)."""
    return (f"Trade{' with ' + who if who else ''}: gave {_trade_side(gave)}; "
            f"got {_trade_side([(row, int(row['quantity'])) for row in got]) or 'nothing tracked'}")


def trade_tracked(got, rows):
    """The rows got that a trade keeps: an ordinary basic land only when rows (the collection
    before it) already track that printing, as merge_rows keeps it."""
    keys = {rules.ident(r) for r in rows}
    return [row for row in got if not rules.ordinary_basic(row) or rules.ident(row) in keys]


def trade_message(message, gave, got, who=""):
    """The change set's message: message (the caller's words, may be blank), then trade_words."""
    words = trade_words(gave, got, who)
    message = (message or "").strip()
    return f"{message}{'' if message[-1] in '.!?' else '.'} {words}" if message else words


# ------------------------------------------------------------------ messages

def message(inv, kind, params):
    """The text a collection operation's Summary will have when it runs on inv with params,
    worked out from the space's rows alone (no settling, no imports), so a caller can give
    inventory.apply its message without running the operation twice. When the operation would
    refuse, the plain words "change <whose>": apply then refuses before anything is written."""
    space = params["space"]
    whose = params.get("whose") or collection_name(space)
    try:
        if kind in ("collection.add", "collection.edit"):
            return f"{kind.split('.')[1]} card {_label(_row(params['row']))} in {whose}"
        rows = _rows(inv, space, params.get("sha256"), whose)
        if kind == "collection.remove":
            return f"remove card {_label(_find(rows, params['original'], space))} in {whose}"
        if kind == "collection.apply":
            edits, removals = len(params.get("edits") or ()), len(params.get("removals") or ())
            words = [f"edit {_rows_word(edits)}"] if edits else []
            words += [f"remove {_rows_word(removals)}"] if removals else []
            return f"{' and '.join(words) or 'change no rows'} in {whose}"
        if kind == "collection.import":
            _, counts = rules.merge_rows(rows, _sources(params["sources"]))
            return _repeat_message((params.get("message") or "import {cards} cards into " + whose).replace(
                "{cards}", str(counts["cards"])), repeat_imports(inv, space, params.get("uploads", ())),
                params.get("uploads", ()))
    except (Invalid, Conflict, rules.InvalidCards):
        pass
    return f"change {whose}"
