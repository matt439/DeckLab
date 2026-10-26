"""The collections' commands (phase 3, area C), registered with `python -m decklab.db`:

    collection list [--space S]                       a space's collection, as collection.csv
    collection merge FILE [FILE ...] [--space S] -m MESSAGE [--dry-run]
    collection edit SET NUMBER FINISH [--space S] [--quantity N] [--condition C] [--language L] [--notes T]
                    --expect SHA -m MESSAGE [--reason R] [--allow-in-use] [--dry-run]
                                                       one row changed, or removed with --quantity 0
    collection apply FILE [--space S] --expect SHA -m MESSAGE [--reason R] [--allow-in-use]
                     [--remove-missing] [--dry-run]    many rows changed or removed, as one change
    collection precons [QUERY ...]                     published precons' CODEs (MTGJSON's paper decks)
    collection add-precon CODE [--space S] [--title T] [--played-by P] -m MESSAGE [--dry-run]

merge replaces scripts/merge_cards.py: each FILE (collection.csv's columns, or a product list's)
is checked as the importer always checked it (rules.parse_cards: every column, a set code, a
finish, a positive whole quantity, a collector number except on an ordinary basic land), every
card name must be a card's exact Scryfall name (so a misspelt name never gets in: run
`python -m decklab.lib.cards update` first on a fresh clone), and then the rows are merged
additively (rules.merge_rows: quantities add on (set, collector_number, finish); ordinary basic
lands are left out unless that printing is tracked; a condition or language the copies don't
share goes blank with a note) in one inventory change, made by Claude from the command line,
with each FILE kept unchanged as one of the space's raw imports (<today>-<file name>.csv).
Recorded orders and products aren't merged this way: they arrive through a receipt, so a FILE
under magic/orders or magic/products is refused.

The change is one audited change set by "claude" (or --actor PROFILE) from the command line, as the pages' are one
by their profile. A merge doesn't refresh the decks' owned-vs-needed tables: afterwards it names
the space's decks whose tables are now out of date and the deck tables command that updates them
(or what would stop that command; inv_decks.stale_notes).

apply (E7-S26) is edit for many rows at once: FILE, an edited copy of collection list's output,
becomes the space's collection in one change (collection.apply), each changed row checked as edit
checks it and each row at quantity 0 removed. A row left out of FILE is refused unless
--remove-missing, so a cut-off, filtered or header-only copy never removes the rest. It changes and
removes rows only; a key the collection doesn't have, a changed name or a key listed twice is
refused.

add-precon (E10-S36) is the Collection page's Add a precon from the command line, for upkeep in a
space whose owner asked (since E10-S29 the page lets nobody write in another's space): the
same code (lib/api/precons.py's plan_add), so the same cards (plain basics left out), the same built deck
(the page's title unless --title; at home Played by --played-by, else the --actor's plays_as),
saved as one change (precon.add) with the deck's table worked out with the cards added. The
command line may write every space, so no profile's rights are asked; --actor only names who made
it. --dry-run prints the cards and the deck it would make and saves nothing. A title whose deck name
is taken in that space is refused, naming the deck that has it. Its last line gives the counts added
and the deck's id. Exit codes: 0 done (or previewed), 1 refused, 2 the database can't be reached.
"""
import csv
import io
import re
import sys
from datetime import date
from pathlib import Path

from decklab.db import cli_actor
from decklab.lib import config, inventory
from decklab.lib.inventory import files, paths, rules
from decklab.lib.inventory import ops_collection as ops

REFUSED = "Recorded orders/products must use python -m decklab.db receive (a receipt), not a collection merge"
PRECON_LIMIT = 40                   # precons collection precons lists (the page's search shows as many)
MIN_EXPECT = 12                     # characters of the collection's sha --expect needs at least
FINISHES = ("nonfoil", "foil", "etched")
CONDITIONS = ("NM", "LP", "MP", "HP", "DMG")       # the Collection page's (api/collection_edit.py)
MAX_QUANTITY = 9999
EDITED = ("quantity", "condition", "language", "notes")


def register(sub):
    p = sub.add_parser("collection", help="List or merge cards into a space's collection.",
                       description="List a space's collection, or merge card files into it.")
    verbs = p.add_subparsers(dest="verb", required=True, metavar="verb")
    sp = verbs.add_parser("list", help="Print a space's collection as CSV, in the collection's columns.")
    sp.add_argument("--space", default=paths.HOME, help="the space (home by default)")
    sp.set_defaults(func=_list)
    sp = verbs.add_parser("merge", help="Merge card files into a space's collection, keeping each as a raw import.")
    sp.add_argument("files", nargs="+", metavar="FILE", help="a CSV in the collection's columns, or a product list's")
    sp.add_argument("--space", default=paths.HOME, help="the space (home by default)")
    sp.add_argument("-m", "--message", required=True, help="what the change does, for the history")
    sp.add_argument("--dry-run", action="store_true", help="show added quantities and retained imports; save nothing")
    cli_actor.add_argument(sp)
    sp.set_defaults(func=_merge)
    sp = verbs.add_parser("edit", help="Change one row's condition, language, notes or quantity (0 removes it).",
                          description="Change one collection row, named by its printing, as the Collection page's "
                                      "card sheet does: only the fields given change, and --quantity 0 removes the row.")
    sp.add_argument("set", metavar="SET", help="the row's set code (fdn)")
    sp.add_argument("number", metavar="NUMBER", help="its collector number")
    sp.add_argument("finish", metavar="FINISH", choices=FINISHES, help="nonfoil, foil or etched")
    sp.add_argument("--space", default=paths.HOME, help="the space (home by default)")
    sp.add_argument("--condition", help=f"{', '.join(CONDITIONS)}, or \"\" for unknown")
    sp.add_argument("--language", help="Scryfall's language code (en, ja, ...), or \"\" for unknown")
    sp.add_argument("--notes", help="the row's notes (replacing them; \"\" clears them)")
    sp.add_argument("--quantity", type=int, help="the copies now; 0 removes the row (needs --reason)")
    sp.add_argument("--expect", required=True, metavar="SHA",
                    help=f"the sha collection list printed (at least its first {MIN_EXPECT} characters)")
    sp.add_argument("-m", "--message", required=True, help="what the change does, for the history")
    sp.add_argument("--reason", help="why (needed for a removal: sold, traded, lost ...)")
    sp.add_argument("--allow-in-use", action="store_true",
                    help="save a reduction that leaves fewer copies than built decks or intact products hold")
    sp.add_argument("--dry-run", action="store_true", help="show the row before and after; save nothing")
    cli_actor.add_argument(sp)
    sp.set_defaults(func=_edit)
    sp = verbs.add_parser("apply", help="Make a space's collection match an edited copy of collection list's output, "
                                        "as one change.",
                          description="Change or remove many collection rows in one change: FILE is collection "
                                      "list's output with some rows' quantity, condition, language or notes changed. "
                                      "Rows are matched on (set, collector_number, finish); a row at quantity 0 is "
                                      "removed (needs --reason), and a row left out of FILE is refused unless "
                                      "--remove-missing. New cards come only through collection merge.")
    sp.add_argument("file", metavar="FILE", help="an edited copy of collection list's CSV")
    sp.add_argument("--space", default=paths.HOME, help="the space (home by default)")
    sp.add_argument("--expect", required=True, metavar="SHA",
                    help=f"the sha collection list printed (at least its first {MIN_EXPECT} characters)")
    sp.add_argument("-m", "--message", required=True, help="what the change does, for the history")
    sp.add_argument("--reason", help="why (needed when rows are removed: sold, traded, lost ...)")
    sp.add_argument("--allow-in-use", action="store_true",
                    help="save reductions that leave fewer copies than built decks or intact products hold")
    sp.add_argument("--remove-missing", action="store_true",
                    help="remove every row left out of FILE too (needs --reason; without it they're refused)")
    sp.add_argument("--dry-run", action="store_true", help="show each change; save nothing")
    cli_actor.add_argument(sp)
    sp.set_defaults(func=_apply)
    sp = verbs.add_parser("precons", help="Find a published precon's CODE for add-precon (MTGJSON's paper decks).")
    sp.add_argument("query", nargs="*", help="words in its name, set or type (default: the newest)")
    sp.set_defaults(func=_precons)
    sp = verbs.add_parser("add-precon", help="Add a published precon's cards to a space and make its built deck.",
                          description="Add a published precon (MTGJSON's list) to a space: its cards into the "
                                      "collection and its built deck, in one change, as the Collection page's "
                                      "Add a precon does.")
    sp.add_argument("code", metavar="CODE", help="the precon's MTGJSON file name, as collection precons lists it "
                                                 "(such as KeenEngineering_FDC)")
    sp.add_argument("--space", default=paths.HOME, help="the space (home by default)")
    sp.add_argument("--title", help="the deck's title (default the page's: the commander and the precon's name)")
    sp.add_argument("--played-by", choices=("user", "wife", "either"),
                    help="who plays it (home only; default the --actor's plays_as, else no Played by line)")
    sp.add_argument("-m", "--message", required=True, help="what the change does, for the history")
    sp.add_argument("--dry-run", action="store_true", help="show what it would add and make; save nothing")
    sp.add_argument("--add-tokens", action="store_true",
                    help="also add token entries with explicit source counts; printing and reverse face stay unconfirmed")
    sp.add_argument("--token-rows", metavar="FILE",
                    help="confirmed physical token choices as CSV: source_row,front,quantity (0 skips an entry)")
    sp.add_argument("--tokens-source-sha256", metavar="SHA",
                    help="full source SHA shown by --dry-run; required with --token-rows")
    cli_actor.add_argument(sp)
    sp.set_defaults(func=_add_precon)


def _space(space):
    from decklab.lib import spaces
    try:
        return spaces.get(space)
    except spaces.SpaceNotFound:
        raise ValueError(f"There's no space called {space!r} in config.json") from None


def _list(args):
    _space(args.space)
    sheet = inventory.current().collection(args.space)
    problem = ops.unreadable(sheet)
    if problem:
        raise ValueError(problem)
    data = files.render_sheet(sheet) if sheet.exists else rules.collection_csv_bytes([])
    out = getattr(sys.stdout, "buffer", None)
    if out is not None and not sys.stdout.isatty():
        # Redirected to a file: its bytes as UTF-8, as deck pull writes, not the console's code
        # page (which would turn names it can't show into "?" and so break collection apply).
        sys.stdout.flush()
        out.write(data)
        out.flush()
    else:
        sys.stdout.write(data.decode("utf-8"))
    # On stderr, so the CSV on stdout stays the collection's columns alone.
    print(f"sha {ops.sha256_of(sheet)} (give it to collection edit or apply as --expect)", file=sys.stderr)
    return 0


def _check_names(rows, where):
    """ValueError for a row whose name isn't a card's exact Scryfall name (ordinary basics,
    which merge_rows leaves out or adds to a tracked row, aside)."""
    from decklab.lib import cards
    try:
        for row in rows:
            if not rules.ordinary_basic(row) and cards.card(row["name"]) is None:
                near = cards.resolve(row["name"])
                hint = f" (Scryfall calls it {near!r})" if near else ""
                raise ValueError(f"{where}: {row['name']!r} isn't a card's exact Scryfall name{hint}")
    except (FileNotFoundError, RuntimeError) as e:
        raise ValueError(f"The card data can't be read ({e}): run python -m decklab.lib.cards update first") from None


def read_file(path):
    """(rows, text) of a FILE to merge: rules.parse_cards' rows (messages naming path as given)
    and the file's text, kept unchanged as the raw import."""
    source = Path(path).resolve()
    repo = Path(config.REPO).resolve()
    if any(source.is_relative_to(repo / folder) for folder in ("magic/orders", "magic/products")):
        raise ValueError(REFUSED)
    try:
        data = source.read_bytes()
    except OSError as e:
        raise ValueError(f"{path} can't be read ({e.strerror or e})") from None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"{path} isn't UTF-8 text ({e})") from None
    try:
        rows = rules.parse_cards(io.StringIO(text.removeprefix("﻿"), newline=""), str(path))
    except rules.InvalidCards as e:
        raise ValueError(str(e)) from None
    except csv.Error as e:
        raise ValueError(f"{path} can't be read as CSV: {e}") from None
    _check_names(rows, str(path))
    return rows, text


def _merge(args):
    if not args.message.strip():
        raise ValueError("-m needs a message saying what this change does")
    actor = cli_actor.resolve(args)
    space = _space(args.space)
    sources, uploads = [], []
    for path in args.files:
        rows, text = read_file(path)
        sources.append([str(path), rows])
        uploads.append([f"{date.today().isoformat()}-{ops.safe_stem(Path(path).name)}", text])
    snapshot = inventory.current()
    before = snapshot.collection(args.space)
    if ops.unreadable(before):
        raise ValueError(ops.unreadable(before))
    whose = ops.collection_name(args.space, space.name)
    repeats = ops.repeat_imports(snapshot, args.space, uploads)
    if repeats:
        print("Warning: identical content was already imported into this space:", file=sys.stderr)
        for found in repeats:
            print(f"  {found['name']} (date: {found['imported_at'] or 'unknown'}; "
                  f"by: {found['imported_by'] or 'unknown'})", file=sys.stderr)
        print("This explicit merge is additive: its quantities will be added again.", file=sys.stderr)
    if ops.batch_repeats(uploads):
        print("Warning: identical content appears more than once in the supplied files. "
              "This explicit merge adds each file's quantities again.", file=sys.stderr)
    op = inventory.Op("collection.import", {
        "space": args.space, "sha256": ops.sha256_of(before), "whose": whose, "sources": sources,
        "uploads": uploads, "message": args.message, "limit": ops.MAX_IMPORTS,
        "expected_repeats": [r["name"] for r in repeats]})
    try:
        if getattr(args, "dry_run", False):
            after, summary = inventory.preview(op)
        else:
            after, summary = inventory.apply(op, actor, ops.message(snapshot, op.kind, op.params))
    except ops.Stale:
        raise inventory.Conflict(f"{whose[:1].upper() + whose[1:]} changed while the files were read; "
                                 "run the merge again") from None
    if getattr(args, "dry_run", False):
        _merge_preview(snapshot, after, summary, args.space, whose)
        return 0
    counts = summary.counts
    rows = after.collection(args.space).rows
    total = sum(row.qty or 0 for row in rows)
    print(f"{counts['cards']} cards merged: {counts['added_rows']} new rows, "
          f"{counts['bumped_rows']} existing rows increased.")
    print(f"{whose[:1].upper() + whose[1:]} now has {len(rows)} rows, {total} cards.")
    if counts["skipped_basics"]:
        print(f"{counts['skipped_basics']} ordinary basic lands omitted.")
    for rel in summary.extra.get("raw", ()):
        print(f"Kept {rel}.")
    from decklab.db import inv_decks
    inv_decks.stale_notes(args.space)
    return 0


def _merge_preview(before, after, summary, space, whose):
    """Show the planned rows and exact import names from the same operation apply runs."""
    counts = summary.counts
    print(f"Would merge {counts['cards']} cards into {whose}: {counts['added_rows']} new rows, "
          f"{counts['bumped_rows']} existing rows increased.")
    previous = {rules.ident(row): row for row in ops.rows_of(before.collection(space))}
    for row in ops.rows_of(after.collection(space)):
        old = previous.get(rules.ident(row))
        was = int(old['quantity']) if old else 0
        added = int(row['quantity']) - was
        if not added:
            continue
        print(f"  +{added} {row['name']} ({row['set']} {row['collector_number']} {row['finish']}): "
              f"{was} -> {row['quantity']} copies")
        for key in ("condition", "language", "notes"):
            if row[key] or old and old[key] != row[key]:
                print(f"    {key}: {row[key] or '(blank)'}")
    if counts['skipped_basics']:
        print(f"Would omit {counts['skipped_basics']} ordinary basic lands.")
    for rel in summary.extra.get("raw", ()):
        print(f"Would keep unchanged raw import {rel}.")
    print("Nothing saved (--dry-run).")


def _field(key, value, flag):
    """value, a new condition, language or notes, checked as the Collection page checks a row
    (api/collection_edit.py: one line, no formula start), with condition one of CONDITIONS and
    language one of Scryfall's codes, or blank (unknown: never assumed); flag names it in a
    refusal ("--notes", "cards.csv line 4: notes")."""
    from decklab.lib.api import collection_edit as page
    from decklab.lib.api.common import ApiError
    try:
        value = page._text(value, key)
    except ApiError as e:
        raise ValueError(f"{flag}: {e.message}") from None
    if key == "condition" and value.upper() not in ("", *CONDITIONS):
        raise ValueError(f"{flag} must be {', '.join(CONDITIONS)}, or \"\" for unknown")
    if key == "language" and value.lower() not in ("", *page.LANGUAGES):
        raise ValueError(f"{flag} must be one of Scryfall's codes ({', '.join(page.LANGUAGES)}), "
                         "or \"\" for unknown")
    if value.startswith(page.FORMULA_STARTS):
        raise ValueError(f"{flag} can't start with = + - or @ (a spreadsheet would run it as a formula)")
    return value.upper() if key == "condition" else value.lower() if key == "language" else value


def _edit_fields(args):
    """{field: text} of the fields collection edit was given, each checked by _field."""
    out = {}
    if args.quantity is not None:
        if not 0 <= args.quantity <= MAX_QUANTITY:
            raise ValueError(f"--quantity must be a whole number from 0 to {MAX_QUANTITY}")
        out["quantity"] = str(args.quantity)
    for key in ("condition", "language", "notes"):
        value = getattr(args, key)
        if value is not None:
            out[key] = _field(key, value, f"--{key}")
    return out


def _copies(row):
    n = int(row["quantity"])
    return f"{n} {'copy' if n == 1 else 'copies'}"


def _row_label(row):
    return f"{row['name']} ({row['set'].upper()} {row['collector_number']}, {row['finish']})"


def _differences(old, new):
    """"quantity 2 -> 3, condition (blank) -> NM": the fields edit changes."""
    return ", ".join(f"{key} {old[key] or '(blank)'} -> {new[key] or '(blank)'}" for key in EDITED if old[key] != new[key])


def _in_use(before, after, space):
    """The Collection page's in-use warnings for a reduction (collection_guards.reduction_warnings),
    as lines: copies that built decks or intact products of the space hold."""
    from decklab.lib.api.collection_guards import ReductionCheckError, reduction_warnings
    try:
        found = reduction_warnings(before, after, space)
    except ReductionCheckError as e:
        return [f"Whether these copies are in use can't be worked out: {e}"]
    return [f"{w['name']}: {w['before']} -> {w['after']} copies, but {w['in_use']} are held ("
            + ", ".join(f"{h['qty']} in {h['title']}" for h in w["holders"]) + ")" for w in found]


def _tables_left_stale(before, after, space):
    """The space's decks whose tables after's collection would leave out of date that before's
    didn't, as "id (title)"; None when that can't be worked out."""
    from decklab.lib import pool
    try:
        stale = []
        for snapshot in (before, after):
            with inventory.pinned(snapshot):
                stale.append({entry["id"]: entry["title"] for entry in
                              pool.stale_tables(pool.for_space(space), only={space})})
    except Exception:                   # noqa: BLE001 - a preview's note only
        return None
    return [f"{deck_id} ({title})" for deck_id, title in stale[1].items() if deck_id not in stale[0]]


def _expected(args):
    """--expect in lower case, refused unless it looks like (the start of) collection list's sha."""
    expect = args.expect.strip().lower()
    if not re.fullmatch(f"[0-9a-f]{{{MIN_EXPECT},64}}", expect):
        raise ValueError(f"--expect needs the sha collection list printed (at least its first {MIN_EXPECT} characters)")
    return expect


def _listed(args, expect):
    """(whose, title, snapshot, its rows, sha) of --space's collection, refused (Conflict) unless
    it's still the one the listing that printed expect showed."""
    space = _space(args.space)
    whose = ops.collection_name(args.space, space.name)
    title = whose[:1].upper() + whose[1:]
    snapshot = inventory.current()
    sheet = snapshot.collection(args.space)
    if ops.unreadable(sheet):
        raise ValueError(ops.unreadable(sheet))
    sha = ops.sha256_of(sheet)
    if not sha.startswith(expect):
        raise inventory.Conflict(f"{title} has changed since that listing; list it again and retry.")
    return whose, title, snapshot, ops.rows_of(sheet), sha


def _matched(new):
    """new as the page would save it: its card's exact name (page.match), skipped without the card
    data and for an ordinary basic land, as the page skips it; ValueError when it can't be saved."""
    from decklab.lib.api import collection_edit as page
    if page._ready() and not rules.ordinary_basic(new):
        new, problem = page.match(new)
        if problem:
            raise ValueError(f"The card can't be saved: {problem}")
    return new


def _save(args, op, snapshot, title, actor, reason, would, did):
    """edit's and apply's shared end: op previewed against snapshot, then for --dry-run the lines
    would, the in-use warnings and the tables it would leave out of date, else op saved and the
    lines did. A reduction below what built decks or intact products hold is refused (exit 1)
    unless --allow-in-use."""
    with inventory.pinned(snapshot):
        after, _ = inventory.preview(op, refresh=False)
    in_use = _in_use(snapshot, after, args.space)
    if args.dry_run:
        for line in would:
            print(line)
        for line in in_use:
            print(f"  In use: {line}")
        if in_use:
            print("  Saving it needs --allow-in-use.")
        stale = _tables_left_stale(snapshot, after, args.space)
        if stale is None:
            print("Whether decks' tables would go out of date couldn't be worked out.")
        elif stale:
            tables = "1 deck's owned-vs-needed table" if len(stale) == 1 else f"{len(stale)} decks' owned-vs-needed tables"
            print(f"Would leave {tables} out of date: {', '.join(stale)}.")
        print("Nothing saved (--dry-run).")
        return 0
    if in_use and not args.allow_in_use:
        print("Not saved: fewer copies would be left than built decks or intact products hold:", file=sys.stderr)
        for line in in_use:
            print(f"  {line}", file=sys.stderr)
        print("Check with Matt, then run it again with --allow-in-use.", file=sys.stderr)
        return 1
    try:
        inventory.apply(op, actor, args.message.strip(), reason=reason or None, expected_revision=snapshot.revision)
    except (ops.Stale, ops.Missing, ops.DemandChanged):
        raise inventory.Conflict(f"{title} changed meanwhile; list it again and retry.") from None
    except inventory.Conflict as e:
        raise inventory.Conflict(f"The inventory changed meanwhile ({e}); list the collection again and retry.") from None
    for line in did:
        print(line)
    from decklab.db import inv_decks
    inv_decks.stale_notes(args.space)
    return 0


def _edit(args):
    """collection edit (E7-S25): one row, named by its printing, changed as the Collection page's
    card sheet changes it (collection.edit, the same row checks), or removed with --quantity 0
    (collection.remove, with --reason). --expect is the sha collection list printed, checked here
    and again by the operation under the write lock; a reduction the page would warn about (copies
    built decks or intact products hold) needs --allow-in-use. It doesn't refresh the decks'
    tables: as merge, it names those now out of date."""
    if not args.message.strip():
        raise ValueError("-m needs a message saying what this change does")
    changes = _edit_fields(args)
    if not changes:
        raise ValueError("Give at least one of --quantity, --condition, --language and --notes")
    removing = changes.get("quantity") == "0"
    reason = (args.reason or "").strip()
    if removing and not reason:
        raise ValueError("--quantity 0 removes the row: give --reason saying why (sold, traded, lost ...)")
    expect = _expected(args)
    actor = cli_actor.resolve(args)
    whose, title, snapshot, rows, sha = _listed(args, expect)
    key = (args.set.strip().lower(), args.number.strip(), args.finish)
    old = next((row for row in rows if rules.ident(row) == key), None)
    if old is None:
        raise ValueError(f"{title} has no {key[0].upper()} {key[1]} {key[2]} row (collection list shows its rows)")
    params = {"space": args.space, "original": list(key), "sha256": sha, "whose": whose,
              "expect_decks_revision": snapshot.decks_revision}
    if removing:
        op = inventory.Op("collection.remove", params)
        would = [f"Would remove {_row_label(old)} ({_copies(old)}) from {whose}."]
        did = [f"Removed {_row_label(old)} ({_copies(old)}) from {whose}."]
    else:
        new = _matched({**old, **changes})
        if new == old:
            print(f"Nothing to change: {_row_label(old)} in {whose} already has those values.")
            return 0
        op = inventory.Op("collection.edit", {**params, "row": new})
        would = [f"Would change {_row_label(old)} in {whose}: {_differences(old, new)}."]
        did = [f"Changed {_row_label(old)} in {whose}: {_differences(old, new)}."]
    return _save(args, op, snapshot, title, actor, reason, would, did)


def _read_listing(path):
    """[(line number, row)] of FILE for collection apply: an edited copy of collection list's
    output, read as UTF-8 (a byte-order mark dropped, Windows line endings read as plain ones)
    with exactly the collection's columns, in any order; ValueError otherwise, naming path as
    given."""
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise ValueError(f"{path} can't be read ({e.strerror or e})") from None
    try:
        text = data.decode("utf-8").removeprefix("﻿").replace("\r\n", "\n")
    except UnicodeDecodeError as e:
        raise ValueError(f"{path} isn't UTF-8 text ({e})") from None
    reader = csv.reader(io.StringIO(text, newline=""))
    out = []
    try:
        header = next(reader, None)
        if header is None or sorted(header) != sorted(rules.FIELDS):
            raise ValueError(f"{path} needs collection list's columns as its header: {','.join(rules.FIELDS)}")
        for values in reader:
            if not values:
                continue                    # a blank line
            if len(values) != len(header):
                raise ValueError(f"{path} line {reader.line_num}: {len(values)} columns, not {len(header)}")
            out.append((reader.line_num, dict(zip(header, values))))
    except csv.Error as e:
        raise ValueError(f"{path} can't be read as CSV: {e}") from None
    return out


def _quantity(value, flag):
    """value (text) as a whole number from 0 to MAX_QUANTITY; ValueError otherwise."""
    value = value.strip()
    if not re.fullmatch(r"[0-9]{1,4}", value) or int(value) > MAX_QUANTITY:
        raise ValueError(f"{flag} must be a whole number from 0 to {MAX_QUANTITY}, got {value!r}")
    return str(int(value))


def _plan(path, listed, rows):
    """(edits [(old, new)], zeroed [old], missing [old], unchanged count) that make the
    collection's rows match listed (_read_listing's), matched on the identity key: zeroed the rows
    FILE sets to quantity 0, missing the rows it leaves out. A field the file leaves as it was isn't
    checked again, so the listing as printed always comes back unchanged. Refused (ValueError): a
    key the collection doesn't have (new cards come through collection merge), a key listed
    twice, a changed name, or a field collection edit's checks refuse."""
    current = {rules.ident(row): row for row in rows}
    seen, changed, unchanged = set(), [], 0
    for line, row in listed:
        where = f"{path} line {line}"
        finish = row["finish"].strip().lower()
        if finish not in FINISHES:
            raise ValueError(f"{where}: finish must be {', '.join(FINISHES)}, got {row['finish']!r}")
        key = (row["set"].strip().lower(), row["collector_number"].strip(), finish)
        label = f"{key[0].upper()} {key[1]} {key[2]}"
        if key in seen:
            raise ValueError(f"{where}: {label} is listed twice; give each row once")
        seen.add(key)
        old = current.get(key)
        if old is None:
            raise ValueError(f"{where}: the collection has no {label} row. collection apply only changes and "
                             "removes rows: add new cards with collection merge")
        if row["name"].strip() != old["name"]:
            raise ValueError(f"{where}: {label} is {old['name']!r} in the collection, not {row['name'].strip()!r}; "
                             "a name can't be changed here (another card is a removal and a merge)")
        new = dict(old)
        for field in EDITED:
            if row[field] == old[field]:
                continue
            new[field] = (_quantity(row[field], f"{where}: quantity") if field == "quantity"
                          else _field(field, row[field], f"{where}: {field}"))
        if new == old:
            unchanged += 1
        else:
            changed.append((old, new))
    missing = [row for key, row in current.items() if key not in seen]
    zeroed = [old for old, new in changed if new["quantity"] == "0"]
    edits = []
    for old, new in changed:
        if new["quantity"] == "0":
            continue
        try:
            new = _matched(new)
        except ValueError as e:
            raise ValueError(f"{path}: {_row_label(old)}: {e}") from None
        if new == old:
            unchanged += 1
        else:
            edits.append((old, new))
    return edits, zeroed, missing, unchanged


def _apply(args):
    """collection apply (E7-S26): the space's collection made to match FILE, an edited copy of
    collection list's output, as one change (collection.apply): each changed row a collection.edit
    with collection edit's checks, each row at quantity 0 a removal, which needs --reason (a dry
    run says so instead of refusing). A row left out of FILE is refused, dry run or not, unless
    --remove-missing makes it a removal too: a cut-off, filtered or header-only copy of the listing
    would otherwise remove every row it lacks. --expect, the in-use refusal,
    --allow-in-use and --dry-run are collection edit's (_listed, _save). It only changes and
    removes rows: new cards come through collection merge, a receipt or add-precon. As edit, it
    doesn't refresh the decks' tables but names those now out of date."""
    if not args.message.strip():
        raise ValueError("-m needs a message saying what this change does")
    expect = _expected(args)
    listed = _read_listing(args.file)
    actor = cli_actor.resolve(args)
    whose, title, snapshot, rows, sha = _listed(args, expect)
    edits, zeroed, missing, unchanged = _plan(args.file, listed, rows)
    if missing and not args.remove_missing:
        raise ValueError(f"{_plural(len(missing), 'row')} of {whose} {'is' if len(missing) == 1 else 'are'} "
                         f"left out of {args.file} (it lists {_plural(len(listed), 'row')}): set a row's "
                         "quantity to 0 to remove it, or give --remove-missing to remove every row left out "
                         "(try it with --dry-run first)")
    removals = zeroed + (missing if args.remove_missing else [])
    if not edits and not removals:
        print(f"Nothing to change: {whose} already matches {args.file} ({_plural(unchanged, 'row')}).")
        return 0
    reason = (args.reason or "").strip()
    if removals and not reason and not args.dry_run:
        parts = [f"{len(zeroed)} at quantity 0"] if zeroed else []
        parts += [f"{len(missing)} left out of the file (--remove-missing)"] if missing else []
        raise ValueError(f"{_plural(len(removals), 'row')} would be removed ({', '.join(parts)}): "
                         "give --reason saying why (sold, traded, lost ...)")
    op = inventory.Op("collection.apply", {
        "space": args.space, "edits": [[list(rules.ident(old)), new] for old, new in edits],
        "removals": [list(rules.ident(old)) for old in removals], "sha256": sha, "whose": whose,
        "expect_decks_revision": snapshot.decks_revision})
    counts = f"{_plural(len(edits), 'row')} changed, {len(removals)} removed, {unchanged} unchanged"
    would = [f"Would make {whose} match {args.file}: {counts}."]
    would += [f"Would change {_row_label(old)}: {_differences(old, new)}." for old, new in edits]
    would += [f"Would remove {_row_label(old)} ({_copies(old)})." for old in removals]
    if removals and not reason:
        would.append("  Saving it needs --reason saying why they're removed (sold, traded, lost ...).")
    return _save(args, op, snapshot, title, actor, reason, would, [f"Made {whose} match {args.file}: {counts}."])


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _precons(args):
    from decklab.lib import precons
    try:
        found, more, built = precons.search(" ".join(args.query) or None, PRECON_LIMIT)
    except precons.PreconError as e:
        raise ValueError(f"MTGJSON's deck list can't be read: {e}") from None
    for entry in found:
        print(f"{entry['file']}\t{entry['name']}\t{entry['set_name'] or entry['code'].upper()}\t{entry['type']}\t"
              f"{entry['released'] or ''}")
    if not found:
        print("No paper deck MTGJSON lists matches that.")
    if more:
        print(f"More match than these {len(found)}: add words to narrow it.")
    print(f"MTGJSON's list of {built or 'an unknown date'}.")
    return 0


def _api_refusal(e):
    """The exit code (and stderr) for a refusal of the page's precon code (an ApiError): 2 when the
    database can't be reached, else 1, with each problem it lists."""
    print(f"Not added: {e.message}", file=sys.stderr)
    problems = list((e.extra or {}).get("problems") or ())
    problems.extend((e.extra or {}).get("token_problems") or ())
    for problem in problems:
        line = problem.get("line")
        print(f"  {f'line {line}: ' if line else ''}{problem.get('message')}", file=sys.stderr)
    conflict = (e.extra or {}).get("conflict")
    if conflict and conflict.get("id"):
        print(f"  The deck {conflict['id']} already has that name: give another --title.", file=sys.stderr)
    return 2 if e.status == 503 else 1


def _precon_token_choices(args):
    try:
        return _read_precon_token_choices(args)
    except (csv.Error, UnicodeError):
        raise ValueError("The token choices file must be a readable UTF-8 CSV with source_row,front,quantity") from None


def _read_precon_token_choices(args):
    """Read the deliberately small confirmation file, without changing the source cache."""
    from decklab.lib import precon_tokens, precons
    path, source_sha = args.token_rows, args.tokens_source_sha256
    if not path:
        if source_sha is not None:
            raise ValueError("--tokens-source-sha256 needs --token-rows")
        return {}
    if not args.add_tokens:
        raise ValueError("--token-rows needs --add-tokens")
    if not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha):
        raise ValueError("--token-rows needs --tokens-source-sha256 with the full source SHA from --dry-run")
    file = Path(path)
    if file.stat().st_size > 64 * 1024:
        raise ValueError("The token choices CSV is too large")
    with file.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        fields = reader.fieldnames
        if fields is None or len(fields) != 3 or set(fields) != {"source_row", "front", "quantity"}:
            raise ValueError("The token choices CSV needs exactly these columns: source_row,front,quantity")
        choices = []
        for row in reader:
            if len(choices) >= precon_tokens.MAX_ROWS:
                raise ValueError("The token choices CSV has too many source entries")
            if set(row) != set(fields) or any(value is None for value in row.values()):
                raise ValueError("Every token choices CSV row needs source_row,front,quantity")
            source_row, quantity = row["source_row"].strip(), row["quantity"].strip()
            if not re.fullmatch(r"[0-9]{1,6}", source_row) or not 1 <= int(source_row) <= precon_tokens.MAX_ROWS:
                raise ValueError("source_row must be a source token entry number from --dry-run")
            if not re.fullmatch(r"[0-9]{1,6}", quantity) or not 0 <= int(quantity) <= precons.MAX_COUNT:
                raise ValueError(f"quantity must be a whole number from 0 to {precons.MAX_COUNT}; 0 skips an entry")
            choices.append({"source_row": int(source_row), "front": row["front"].strip(), "quantity": int(quantity)})
    return {"tokens_choices": choices, "tokens_source_sha256": source_sha}


def _precon_token_offer(candidate):
    """Show public row meanings and their receipt, even when physical counts are absent."""
    from decklab.lib import precon_tokens
    options = candidate.get("options", [])
    if not options:
        return
    print(f"Token source SHA: {precon_tokens.source_sha256(candidate)}")
    print("Token choices CSV columns: source_row,front,quantity; include every source entry, using 0 to skip.")
    for item in options:
        quantity = f"declared quantity {item['quantity']}" if item["quantity"] is not None else "physical quantity unknown"
        fronts = " | ".join(item["fronts"]) or "unavailable"
        print(f"  Source token entry {item['source_row']}: {item['source_name']}; fronts: {fronts}; {quantity}.")
    for problem in candidate.get("choice_problems", []):
        print(f"  Token choice unavailable: {problem['message']}")


def _add_precon(args):
    """collection add-precon (E10-S36): the page's Add a precon (lib/api/precons.py's plan_add, the
    same checks, cards and deck), made by the command line, which may write every space. The cards
    and the built deck save as one change (precon.add), the deck's table worked out with the cards
    added. The last line gives the counts and the deck's id, so Claude can say it's done without
    passing on the list (AGENTS.md, "Spaces")."""
    from decklab.lib import profiles, spaces
    from decklab.lib.api import common
    from decklab.lib.api import precons as page
    from decklab.lib.inventory import ops_decks  # noqa: F401  (registers precon.add)
    space = _space(args.space)
    if not args.message.strip():
        raise ValueError("-m needs a message saying what this change does")
    token_params = _precon_token_choices(args)
    actor = cli_actor.resolve(args)
    player = args.played_by
    if player and args.space != spaces.HOME:
        raise ValueError("--played-by is for a home deck: a person's deck is theirs by its space")
    if player is None and args.space == spaces.HOME and getattr(args, "actor", None):
        player = (profiles.find(args.actor) or {}).get("plays_as")
    try:
        # Checked with no profile: a script naming nobody may write every space, as the command line does.
        made = page.plan_add(args.space, args.code, args.title, {"player": player} if player else None, None,
                             actor.name, add_tokens=args.add_tokens, **token_params)
    except common.ApiError as e:
        return _api_refusal(e)
    built, plan, whose = made["built"], made["plan"], made["whose"]
    entry, good = built["entry"], built["good"]
    cards = sum(int(r["quantity"]) for r in good)
    sections = ", ".join(f"{s} {sum(c['qty'] for c in lines)}" for s, lines in built["sections"].items())
    left = [f"{built['dropped']} ordinary basic lands"] if built["dropped"] else []
    left += [f"{n} {what}" for what, n in built["left_out"].items()]
    tokens = page._token_words(built)
    if args.dry_run:
        print(f"Would add the {entry['name']} precon ({entry['set_name'] or entry['code'].upper()}, {entry['type']}) "
              f"to {whose}: {_plural(cards, 'card')} in {_plural(len(good), 'row')}.")
        for row in sorted(good, key=rules.sort_key):
            print(f"  {row['quantity']} {row['name']} ({row['set']} {row['collector_number']} {row['finish']})")
        if left:
            print(f"Left out: {', '.join(left)}.")
        print(f"Would make {made['deck_id']} ({plan['title']}), a built {plan['kind']} deck: {sections}.")
        if made["table"].get("note"):
            print(made["table"]["note"])
        candidate = built["token_candidates"]
        if args.add_tokens:
            quantities = "confirmed physical quantities" if args.token_rows else "quantities as declared by MTGJSON"
            print(f"Would add {_plural(candidate['cards'], 'token card')} in {_plural(len(candidate['rows']), 'separate row')}; "
                  f"{quantities}, printing and reverse face unconfirmed.")
            for item in candidate["rows"]:
                print(f"  {item['row']['quantity']} {item['row']['front']} (source token entry {item['source_row']}; check physical pairing)")
        elif tokens:
            print(f"Its token cards (in its Notes, not added to the token cards): {tokens}.")
        _precon_token_offer(candidate)
        print("Nothing saved (--dry-run).")
        return 0
    try:
        after, summary = inventory.apply(made["op"], actor, args.message.strip())
    except (inventory.Invalid, inventory.Conflict) as e:
        mapped = made["refused"](e)     # the page's words: a changed collection, a name taken meanwhile
        if mapped is None:
            raise
        return _api_refusal(mapped)
    counts = summary.counts
    if made["table"].get("note"):
        print(made["table"]["note"])
    for rel in (summary.extra or {}).get("raw", ()):
        print(f"Kept {rel}.")
    from decklab.db import inv_decks
    inv_decks.stale_notes(args.space, exclude=(made["deck_id"],), other=True)
    added = counts.get("cards", 0) if good else 0
    if args.add_tokens:
        print(f"Added {_plural(counts['token_cards'], 'token card')} in {_plural(counts['token_rows'], 'separate row')}; "
              "printing and reverse face unconfirmed.")
    print(f"Added {_plural(added, 'card')} ({counts.get('added_rows', 0) if good else 0} new rows) to {whose} "
          f"and made {made['deck_id']}.")
    return 0
