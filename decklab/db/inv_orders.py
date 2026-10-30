"""The orders, products and watchlist commands (the phase 3 design's amendment Q7), Claude's way
to read and change them whichever backend holds the inventory (decklab/lib/inventory/orders.py
has the operations and their rules):

  python -m decklab.db order list [--pending] [--json]
  python -m decklab.db order show ID [--json | --csv COMPONENT]
  python -m decklab.db order add [--record RECORD.json] [--id ID] [--seller S] [--ordered-on D]
                       [--source PATH]... [--notes T] [--check COMPONENT=TEXT]...
                       [--cards CARDS.csv] [--tokens TOKENS.csv]
                       [--product STEM --product-csv FILE [--name N] [--format F]
                        [--product-status ordered|preordered] [--product-notes T]]
                       [--fulfils 'NAME[@FOR][=QTY]' | '#N[=QTY]']... [--extra-copies COMPONENT]...
                       -m MSG
  python -m decklab.db order edit ID COMPONENT --csv FILE -m MSG
  python -m decklab.db order record ID [--seller S] [--ordered-on D] [--notes T]
                       [--source PATH ... | --clear-sources] -m MSG
  python -m decklab.db order checks ID COMPONENT (--add TEXT | --resolve N | --clear | --withdraw N)
                       -m MSG
  python -m decklab.db order split ID COMPONENT --new-id NEW --take ROW[:QTY]...
                       [--move-check N]... [--keep-check N]... [--copy-check N]... -m MSG
  python -m decklab.db order cancel ID COMPONENT [--restore-queue] -m MSG --reason R
  python -m decklab.db order remove ID -m MSG --reason R
  python -m decklab.db order merge ID OTHER... [--rename OTHER:COMPONENT=NEW]... [--notes T] -m MSG
  python -m decklab.db order extra-copies ID COMPONENT [--undo] -m MSG
  python -m decklab.db product add STEM --order ID --csv FILE [--name N] [--format F]
                       [--status ordered|preordered] [--notes T] -m MSG
  python -m decklab.db product set-intact STEM yes|no -m MSG
  python -m decklab.db product kit STEM [--json]
  python -m decklab.db product set-kit STEM --expect SHA [--sleeves ID|none] [--deck-box ID|none]
                       -m MSG [--actor PROFILE] [--dry-run]
  python -m decklab.db product edit STEM [--csv FILE] [--name N] [--format F]
                       [--status ordered|preordered] [--notes T] -m MSG [--dry-run]
  python -m decklab.db watchlist list [--state S] [--csv | --json]
  python -m decklab.db watchlist set SELECT [--name ...] [--quantity Q] [--state S] ... -m MSG
  python -m decklab.db watchlist set --add --name N --state S [...] -m MSG
  python -m decklab.db watchlist remove SELECT -m MSG --reason R
  python -m decklab.db watchlist apply --csv FILE -m MSG

Placing an order is one change: `order add` records the order, its payloads, a product with its
card list and status row, and reduces the watchlist rows it fulfils. --record takes the record's
fields as a JSON object in the records' format (id, seller, ordered_on, sources, notes,
audit_notes, and optionally components [{id, kind, checks}] naming each component's id and
checks); the flags fill in or replace them. A cards or tokens payload's file is <id>.csv
(magic/orders/ or magic/orders/tokens/); a product's component is named after its stem.
--fulfils names a watchlist row as `watchlist list` shows it (NAME, NAME@FOR or #N) with the
copies the order covers (all of them when no =QTY): an exact row only by that printing.

The receipt round trip: `order show ID` prints a component's rows and checks (and `--csv C` its
file); record what the checks found in a copy (conditions, languages, printings, a token's
back), `order edit ID C --csv FILE` stores it (same totals; printings checked against the card
index), then receive it with --verified C, which keeps the checks as its verified_checks. A
pending component's checks can't be resolved or cleared before it arrives (the receipt is where
they're verified); `order checks --withdraw N` drops one added by mistake. Once a component has
arrived, `--resolve N` / `--clear` resolve checks left open (a product's token inspection),
kept in its verified_checks.

`order split` copies each check to both parts unless --move-check N (only the new part) or
--keep-check N (only the original) says otherwise, and the new part keeps the original's
extra-copies mark (`order extra-copies`) when it has one. `order cancel` keeps --reason in the record's
audit_notes (and the change's reason); --restore-queue returns its recorded fulfilled copies.
`order remove` removes an order entered by mistake, including its products and payloads, and
returns recorded fulfilled copies in the same change. Received orders can't be removed.
`order merge ID OTHER...` combines orders the shop sent as one shipment (combined postage), so the
delivery is received once: every component of each OTHER moves into ID, keeping its rows, checks
and status, and the OTHER records go. A component whose id ID already has needs --rename
OTHER:COMPONENT=NEW. The orders must share a seller and have nothing received yet; their sources
are combined and their notes joined (--notes replaces them), and their recorded fulfilment history
moves with the components, so a later cancel or remove still restores the right queue copies.
Each payload keeps its file, so the deck tables' "on the way (order <file>)" labels don't change. Historical
orders without recorded fulfilment history require manual queue review; no copies are inferred.

`order extra-copies ID COMPONENT` marks a pending cards or product component as extra copies of
printings already owned (a second copy of a printing in the collection), as one sentence in the
record's audit_notes ("Extra copies of owned printings: cards."); --undo takes it off again.
Without it, a pending component whose every printing is already in the collection makes the pool
warn that it may have been merged without a receipt, which stops every deck table refresh and
receipt (pool.py's module docstring). `order add --extra-copies COMPONENT` marks one in the same
change, for an order known to be for more copies of owned printings (instead of --force).

A watchlist row is selected by NAME, NAME@FOR (its "for" column) or #N (its number in
`watchlist list`). `watchlist list --csv` prints the whole list as CSV: edit a copy (in the
scratchpad, never magic/) with a shop check's prices and `watchlist apply --csv` it in one change.

Each write is one change (the audit trail's change set by "claude", or --actor PROFILE, from the command line, with
the -m message and a removal's --reason). --dry-run shows what a write would do without saving it. A write
that changes what decks count as on the way or in use (order add, edit, split, cancel and
extra-copies, product add and set-intact: their kinds are registered with refresh=True) refreshes the deck tables in
the same change (inventory/refresh.py's in_op) and says which it changed; a refresh that fails
leaves the decks as they were and the change saved (exit 3).
--no-check skips the printing and finish checks; card names are still checked against the card
index whenever it's there (a name it doesn't know stops every deck's table refresh), and only
with no index at all do the rows go in unchecked, with a note.

Before such a write (and its --dry-run) the deck tables' refresh is planned on what the change
would make (the change's own preview), as a receipt's preview plans it: a change after which
they couldn't be refreshed (a product kept intact with no deck lists, a pending payload whose
every card is already in the collection and that isn't marked as extra copies) is refused, since an incomplete pool refuses every
receipt, unless --force is given, which saves it with the deck tables' refresh skipped. It isn't
refused when the tables can't be refreshed before the change either.

Exit codes as the other commands: 0 done (or nothing to change), 1 refused, 2 the database
can't be reached, 3 saved, but the deck tables couldn't be refreshed (stderr says why; as
receive's).
"""
import csv
import io
import json
import sys
from pathlib import Path

from decklab.db import cli_actor
from decklab.lib.inventory.model import QUEUE_FIELDS

FOLLOW_UP_FAILED = 3            # saved, but the deck tables' refresh didn't finish
# The watchlist columns the set command's flags change ("for" is --for).
QUEUE_FLAGS = {"name": "name", "set": "set_code", "collector_number": "number", "finish": "finish",
               "quantity": "quantity", "for": "for_deck", "printing": "printing", "listed_aud": "listed_aud",
               "listed_at": "listed_at", "in_stock": "in_stock", "checked": "checked", "notes": "notes",
               "state": "state", "source": "source"}


def register(sub):
    """Add the order, product and watchlist commands to python -m decklab.db's parser."""
    p = sub.add_parser("order", help="List, show, add or change orders (list, show, add, edit, checks, split, "
                                     "record, cancel, remove, merge, extra-copies).", description="The order records and their components.")
    actions = p.add_subparsers(dest="action", required=True, metavar="action")
    sp = actions.add_parser("list", help="Every order with its status and components.")
    sp.add_argument("--pending", action="store_true", help="only orders with something still to arrive")
    sp.add_argument("--json", action="store_true", help="print the records as JSON")
    sp.set_defaults(func=order_list)
    sp = actions.add_parser("show", help="One order: its record, checks and each component's rows.")
    sp.add_argument("order")
    out = sp.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true", help="print the record as JSON")
    out.add_argument("--csv", metavar="COMPONENT", help="print that component's rows (a payload's cards or tokens, or a product's list) as CSV")
    sp.set_defaults(func=order_show)

    sp = _write(actions, "add", "Record a new order: its record, payloads, product and the watchlist rows it "
                                "fulfils, in one change.", order_add, refreshes=True)
    sp.add_argument("--record", metavar="RECORD.json", help="the record's fields as JSON (see the module help)")
    sp.add_argument("--id", help="the order id (YYYY-MM-DD-topic)")
    sp.add_argument("--seller")
    sp.add_argument("--ordered-on", metavar="YYYY-MM-DD")
    sp.add_argument("--source", action="append", metavar="PATH", help="a buylist or deck behind it (repeat)")
    sp.add_argument("--notes")
    sp.add_argument("--check", action="append", default=[], metavar="COMPONENT=TEXT",
                    help="a check for a component on arrival (repeat)")
    sp.add_argument("--cards", metavar="CARDS.csv", help="the playable cards, a CSV in the collection's columns")
    sp.add_argument("--tokens", metavar="TOKENS.csv", help="the token cards, a CSV in the token cards' columns")
    sp.add_argument("--product", metavar="STEM", help="a sealed product's id (its stem, such as fdc-wretched-ranks)")
    sp.add_argument("--product-csv", metavar="FILE", help="the product's card list")
    sp.add_argument("--name", help="the product's display name")
    sp.add_argument("--format", help="the product's deck format")
    sp.add_argument("--product-status", choices=("ordered", "preordered"), default="ordered")
    sp.add_argument("--product-notes", default="", help="the notes of the product's status")
    sp.add_argument("--fulfils", action="append", default=[], metavar="SELECT[=QTY]",
                    help="a watchlist row the order fulfils (repeat)")
    sp.add_argument("--extra-copies", action="append", default=[], metavar="COMPONENT",
                    help="mark a cards or product component as extra copies of printings already owned (repeat)")
    sp.add_argument("--no-check", action="store_true", help="don't check printings against the card index")

    sp = _write(actions, "edit", "Replace a pending cards or tokens component's rows (same totals).", order_edit,
                refreshes=True)
    sp.add_argument("order")
    sp.add_argument("component")
    sp.add_argument("--csv", required=True, metavar="FILE", help="the component's rows, in its columns")
    sp.add_argument("--no-check", action="store_true", help="don't check printings against the card index")

    sp = _write(actions, "record", "Correct an order's seller, date, notes or sources; keep its components.",
                order_record)
    sp.add_argument("order")
    sp.add_argument("--seller", help="the seller (an empty string clears it)")
    sp.add_argument("--ordered-on", metavar="YYYY-MM-DD", help="the order date (an empty string clears it)")
    sp.add_argument("--notes", help="delivery notes (an empty string clears them)")
    sources = sp.add_mutually_exclusive_group()
    sources.add_argument("--source", action="append", metavar="PATH", help="replace the sources (repeat for each)")
    sources.add_argument("--clear-sources", action="store_true", help="remove every source")

    sp = _write(actions, "checks", "Add, resolve or clear a component's checks.", order_checks)
    sp.add_argument("order")
    sp.add_argument("component")
    what = sp.add_mutually_exclusive_group(required=True)
    what.add_argument("--add", metavar="TEXT", help="a new check")
    what.add_argument("--resolve", type=int, metavar="N", help="resolve check N (as order show numbers them)")
    what.add_argument("--clear", action="store_true", help="resolve every check")
    what.add_argument("--withdraw", type=int, metavar="N",
                      help="drop check N, added by mistake (nothing is recorded as verified)")

    sp = _write(actions, "split", "Move part of a pending component to a new pending component of the order.",
                order_split, refreshes=True)
    sp.add_argument("order")
    sp.add_argument("component")
    sp.add_argument("--new-id", required=True, help="the new component's id")
    sp.add_argument("--take", action="append", required=True, metavar="ROW[:QTY]",
                    help="a row (as order show numbers them) and how many of it move (all of it without :QTY)")
    sp.add_argument("--move-check", action="append", type=int, default=[], metavar="N",
                    help="check N goes to the new component (repeat)")
    sp.add_argument("--keep-check", action="append", type=int, default=[], metavar="N",
                    help="check N stays only on the original (repeat)")
    sp.add_argument("--copy-check", action="append", type=int, default=[], metavar="N",
                    help="check N goes to both, as every check not moved or kept does (repeat)")

    sp = _write(actions, "cancel", "Cancel a pending component (cards, tokens or product).", order_cancel,
                reason=True, refreshes=True)
    sp.add_argument("order")
    sp.add_argument("component")
    sp.add_argument("--restore-queue", action="store_true",
                    help="return its recorded fulfilled copies to the queue (historical orders need manual review)")

    sp = _write(actions, "remove", "Remove an unreceived order entered by mistake and restore its recorded queue copies.",
                order_remove, reason=True, refreshes=True)
    sp.add_argument("order")

    sp = _write(actions, "merge", "Combine orders the shop sent as one shipment into one order, so the "
                                  "delivery is received once.", order_merge)
    sp.add_argument("order", help="the order the others are merged into")
    sp.add_argument("others", nargs="+", metavar="OTHER", help="an order to merge into it")
    sp.add_argument("--rename", action="append", default=[], metavar="OTHER:COMPONENT=NEW",
                    help="give a moved component a new id (needed when ORDER already has that id)")
    sp.add_argument("--notes", help="the merged order's delivery notes (default: each order's notes joined)")

    sp = _write(actions, "extra-copies", "Mark a pending cards or product component as extra copies of printings "
                                         "already owned, so the pool doesn't warn that it may have been merged "
                                         "without a receipt (--undo: unmark it).", order_extra_copies, refreshes=True)
    sp.add_argument("order")
    sp.add_argument("component")
    sp.add_argument("--undo", action="store_true", help="take the mark off again")

    p = sub.add_parser("product", help="Add or correct a product, choose its kit, or keep it intact or break it up.",
                       description="The sealed products.")
    actions = p.add_subparsers(dest="action", required=True, metavar="action")
    sp = _write(actions, "add", "Add a product (card list, status row, component) to an existing order.",
                product_add, refreshes=True)
    sp.add_argument("stem", help="the product's id (its stem, such as fdc-wretched-ranks)")
    sp.add_argument("--order", required=True, help="the order it belongs to")
    sp.add_argument("--csv", required=True, metavar="FILE", help="the product's card list")
    sp.add_argument("--name", help="the product's display name")
    sp.add_argument("--format", help="the product's deck format")
    sp.add_argument("--status", choices=("ordered", "preordered"), default="ordered")
    sp.add_argument("--notes", default="", help="the notes of its status")
    sp.add_argument("--no-check", action="store_true",
                    help="don't refuse it when there's no card index (names are checked when there is)")
    sp = _write(actions, "edit", "Correct supplied fields or replace the card list of a pending product.",
                product_edit, refreshes=True)
    sp.add_argument("stem", help="the existing product's id")
    sp.add_argument("--csv", metavar="FILE", help="replace its complete card list")
    sp.add_argument("--name", help="the product's display name (empty clears it)")
    sp.add_argument("--format", help="the product's deck format (empty clears it)")
    sp.add_argument("--status", choices=("ordered", "preordered"))
    sp.add_argument("--notes", help="the notes of its status (empty clears them)")
    sp.add_argument("--no-check", action="store_true",
                    help="don't refuse it when there's no card index (names are checked when there is)")
    sp = _write(actions, "set-intact", "Keep an owned product intact (yes) or break it up (no).", product_intact,
                refreshes=True)
    sp.add_argument("stem")
    sp.add_argument("intact", choices=("yes", "no"))

    from decklab.db import product_kit
    sp = actions.add_parser("kit", help="Show a product's sleeves, deck box and the status-list sha.")
    sp.add_argument("stem", help="the product's id")
    sp.add_argument("--json", action="store_true", help="print its kit and status-list sha as JSON")
    sp.set_defaults(func=product_kit.show)
    sp = _write(actions, "set-kit", "Choose an owned intact product's sleeves and deck box; omit a field to keep it.",
                product_kit.save)
    sp.add_argument("stem", help="the product's id")
    sp.add_argument("--expect", required=True, metavar="SHA",
                    help="the sha product kit printed (at least its first 12 characters)")
    sp.add_argument("--sleeves", metavar="ID|none", help="a shared sleeves id, or none to clear it")
    sp.add_argument("--deck-box", metavar="ID|none", help="a shared deck-box id, or none to clear it")

    from decklab.db import product_tokens
    sp = actions.add_parser("tokens", help="Show an intact product's packed-token record and source hashes.")
    sp.add_argument("stem")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=product_tokens.show)
    sp = _write(actions, "set-tokens", "Record an intact product's packed tokens; empty text clears the record.",
                product_tokens.save)
    sp.add_argument("stem")
    sp.add_argument("--expect", required=True, metavar="SHA", help="the product tokens status-list sha (at least 12 characters)")
    sp.add_argument("--tokens-sha256", required=True, metavar="SHA|none", help="the token-list sha, or none when absent")
    sp.add_argument("--tokens", required=True, metavar="TEXT", help="Token cards syntax; empty text clears the packing record")

    p = sub.add_parser("watchlist", help="List or change the purchase queue (list, set, remove, apply).",
                       description="The watchlist (the purchase queue).")
    actions = p.add_subparsers(dest="action", required=True, metavar="action")
    sp = actions.add_parser("list", help="The queue, numbered (#N selects a row).")
    sp.add_argument("--state", choices=("ready", "waiting_for_stock", "waiting_for_reprint", "deferred", "long_term"))
    out = sp.add_mutually_exclusive_group()
    out.add_argument("--csv", action="store_true", help="print it as CSV (the watchlist's columns)")
    out.add_argument("--json", action="store_true", help="print it as JSON")
    sp.set_defaults(func=watchlist_list)
    sp = _write(actions, "set", "Change one row (or add one with --add).", watchlist_set)
    sp.add_argument("select", nargs="?", help="NAME, NAME@FOR or #N")
    sp.add_argument("--add", action="store_true", help="add a new row (give --name and --state)")
    sp.add_argument("--name")
    sp.add_argument("--set", dest="set_code", metavar="SET")
    sp.add_argument("--number", help="collector number")
    sp.add_argument("--finish", choices=("", "nonfoil", "foil", "etched"))
    sp.add_argument("--quantity")
    sp.add_argument("--for", dest="for_deck", metavar="FOR")
    sp.add_argument("--printing", choices=("any", "exact"))
    sp.add_argument("--listed-aud")
    sp.add_argument("--listed-at")
    sp.add_argument("--in-stock", choices=("", "yes", "no"))
    sp.add_argument("--checked", metavar="YYYY-MM-DD")
    sp.add_argument("--notes")
    sp.add_argument("--state", choices=("ready", "waiting_for_stock", "waiting_for_reprint", "deferred", "long_term"))
    sp.add_argument("--source", metavar="PATH")
    sp = _write(actions, "remove", "Remove one row.", watchlist_remove, reason=True)
    sp.add_argument("select", help="NAME, NAME@FOR or #N")
    sp = _write(actions, "apply", "Make the queue what a CSV (in the watchlist's columns) says, in one change.",
                watchlist_apply)
    sp.add_argument("--csv", required=True, metavar="FILE")


def _write(actions, name, help_text, func, reason=False, refreshes=False):
    sp = actions.add_parser(name, help=help_text, description=help_text)
    sp.add_argument("-m", "--message", required=True, help="what this change does, for the audit trail")
    cli_actor.add_argument(sp)
    if reason:
        sp.add_argument("--reason", required=True, help="why, for the audit trail")
    if refreshes:
        sp.add_argument("--force", action="store_true",
                        help="save it even when the deck tables couldn't be refreshed afterwards")
    sp.add_argument("--dry-run", action="store_true", help="show what it would do; save nothing")
    sp.set_defaults(func=func)
    return sp


# ------------------------------------------------------------------ helpers

def _say(text):
    print(text, file=sys.stderr)


def _ops():
    from decklab.lib import inventory
    from decklab.lib.inventory import orders  # noqa: F401  (registers the operations)
    return inventory


def _repo():
    from decklab.lib import config
    return str(config.REPO)


def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except OSError as e:
        raise ValueError(f"{path} can't be read: {e.strerror or e}") from None
    except UnicodeDecodeError:
        raise ValueError(f"{path} isn't UTF-8 text") from None


def read_cards(path):
    """A cards file's rows (collection.csv's columns, or a product's), checked as merge_cards.read
    checks an incoming file."""
    from decklab.lib.inventory import rules
    try:
        return rules.parse_cards(io.StringIO(_read_text(path), newline=""), path)
    except csv.Error as e:
        raise ValueError(f"{path}: {e}") from None


def read_tokens(path):
    from decklab.lib.inventory import rules
    try:
        return rules.parse_csv(io.StringIO(_read_text(path), newline=""), rules.TOKEN_FIELDS, path)
    except csv.Error as e:
        raise ValueError(f"{path}: {e}") from None


def read_product(path):
    """(columns, rows) of a product's card list as written (its own columns, kept)."""
    try:
        reader = csv.DictReader(io.StringIO(_read_text(path), newline=""), strict=True)
        rows = list(reader)
        columns = reader.fieldnames
    except csv.Error as e:
        raise ValueError(f"{path}: {e}") from None
    if not columns:
        raise ValueError(f"{path} has no header")
    if any(None in row or None in row.values() for row in rows):
        raise ValueError(f"{path}: a row has the wrong number of columns")
    return list(columns), rows


def read_queue_csv(path):
    from decklab.lib.inventory import rules
    try:
        return rules.parse_csv(io.StringIO(_read_text(path), newline=""), list(QUEUE_FIELDS), path)
    except csv.Error as e:
        raise ValueError(f"{path}: {e}") from None


def _run(args, op, refresh=False):
    """Apply op (or preview it with --dry-run) and say what happened. refresh: op's kind refreshes
    the deck tables in the same change (registered with refresh=True); say how that went, and
    refuse a change after which they couldn't be refreshed unless --force (which skips the
    refresh)."""
    if not isinstance(args.message, str) or not args.message.strip():
        raise ValueError("-m needs a message saying what this change does.")
    inventory = _ops()
    actor = cli_actor.resolve(args)
    from decklab.lib.inventory import changes
    if op.kind in CHECKED:
        _load_index()
    force = bool(refresh and getattr(args, "force", False))
    if refresh and not force:
        problem = _refresh_refusal(inventory, op)
        if problem:
            _say(f"Refused: after this change the deck tables couldn't be refreshed, and every receipt would be "
                 f"refused until it's put right: {problem}")
            _say("Fix the change, or add --force to save it anyway.")
            return 1
    if args.dry_run:
        before = inventory.current()
        after, summary = inventory.preview(op, refresh=not force)
        _report(summary, preview=True)
        touched = changes.changed_labels(before, after)
        print("Dry run: nothing saved." + (" It would change:" if touched else " Nothing would change."))
        for words in touched:
            print(f"  {words}")
        if force:
            _say_forced(saved=False)
        elif refresh:
            error = ((summary.extra or {}).get("tables") or {}).get("error")
            if error:
                _say(f"Note: the deck tables wouldn't be refreshed: {error}")
        return 0
    _, summary = inventory.apply(op, actor, args.message, reason=getattr(args, "reason", None),
                                 refresh=not force)
    _report(summary, link_removed=op.kind == "order.remove")
    if force:
        _say_forced(saved=True)
    elif refresh and not say_tables((summary.extra or {}).get("tables")):
        return FOLLOW_UP_FAILED
    return 0


def _say_forced(saved):
    """Say that --force skipped the deck tables' refresh (the change is saved all the same: exit 0)."""
    were = "weren't" if saved else "wouldn't be"
    _say(f"Note: --force: the deck tables {were} refreshed, so some may be stale.")
    _say("  Update them with Update all on the Decks page's Tables out of date list (or python -m decklab.db "
         "deck tables --apply) once the pool is put right.")


def _refresh_refusal(inventory, op):
    """Why the deck tables couldn't be refreshed after op (the error of the refresh inside op's
    preview, as a receipt's preview plans them), or None. None too when they can't be refreshed
    now in the spaces op touches (refresh.plan_refresh on the inventory as it is): a change can't
    make that worse, and it may be the one that puts it right; and None while the backend can't
    save deck texts."""
    try:
        from decklab.lib import decks
        from decklab.lib.inventory import changes, refresh
    except ImportError:
        return None
    failures = (OSError, ValueError, RuntimeError, decks.DeckFileError, inventory.StateError)
    before = inventory.current()
    after, summary = inventory.preview(op)      # refused as apply would refuse it
    error = ((summary.extra or {}).get("tables") or {}).get("error")
    if error in (None, inventory.DECK_SAVES_PAUSED):
        return None
    try:
        with inventory.pinned(before):
            refresh.plan_refresh(refresh.spaces_of(changes.changed_paths(before, after)))
    except failures:
        return None
    return error


# The operations that check names and printings against the card index (loaded before the
# inventory lock is taken: its first load takes most of a second, which a page's save waiting on
# the lock shouldn't).
CHECKED = ("order.add", "order.edit", "product.add", "product.edit")


def _load_index():
    """Load the card index now if it can be (an operation's check says what a failure means)."""
    from decklab.lib.inventory import orders
    orders.index_ready()


def _report(summary, preview=False, link_removed=False):
    print(summary.text)
    for warning in (summary.extra or {}).get("warnings", ()):
        _say(f"Note: {warning}")
    queue = (summary.extra or {}).get("queue")
    if isinstance(queue, dict):
        _queue_notes(queue, preview=preview)
    if link_removed and not preview:
        for path in dict.fromkeys((summary.extra or {}).get("removed") or []):
            _cancel_notes(path, removed=True)


def _queue_notes(queue, preview=False):
    """Report only the operation's recorded fulfilment outcome, never inferred queue copies."""
    if not queue.get("known"):
        _say("Note: this order has no recorded queue fulfilment history. Review the queue manually; "
             "no historical copies were inferred.")
    offered, restored = queue.get("offered") or [], queue.get("restored") or []
    rows = restored or offered
    action = (("Would restore" if preview else "Restored") if restored
              else ("Available to restore" if preview else "Not restored"))
    for row in rows:
        label = f"{row.get('quantity', '')} x {row.get('name', '')}"
        if row.get("for"):
            label += f" for {row['for']}"
        if row.get("printing") == "exact":
            printing = " ".join(filter(None, (row.get("set"), row.get("collector_number"), row.get("finish"))))
            label += f" (exact: {printing})"
        print(f"{action} to the queue: {label}")
    if offered and not restored:
        if preview:
            _say("Note: the queue copies above would be left unchanged; add --restore-queue to return them when cancelling.")
        else:
            _say("Note: the copies above were not restored. Re-queue any still wanted with watchlist set "
                 "(--quantity) or watchlist set --add.")
    for warning in queue.get("warnings") or []:
        _say(f"Note: {warning}")


def say_tables(result):
    """Say how the deck tables' refresh inside a change went (refresh.in_op's
    Summary.extra["tables"]: {written, skipped, error}); False when they couldn't be
    refreshed (the change itself is saved either way, the tables left on the Decks page's
    Tables out of date list). No outcome at all (the change changed nothing) is True."""
    if not isinstance(result, dict):
        return True
    if result.get("error"):
        _say(f"Note: the change is saved, but the deck tables weren't refreshed: {result['error']}")
        _say("  Update them with Update all on the Decks page's Tables out of date list (or python -m decklab.db "
             "deck tables --apply) once that's fixed.")
        return False
    written = result.get("written") or []
    if written:
        print(f"Deck tables refreshed: {', '.join(item.get('title') or item.get('id', '') for item in written)}")
    for item in result.get("skipped") or []:
        why = {"changed": "the change rewrote it itself",
               "kit": "its Sleeves or Deck box would change"}.get(item.get("why"), item.get("why"))
        _say(f"Note: {item.get('title') or item.get('id')}'s table wasn't refreshed ({why}); the Decks page's "
             "Tables out of date list has it.")
    return True


def _fields(record_path):
    """The record fields and component settings an --record file gives."""
    if not record_path:
        return {}, []
    try:
        data = json.loads(_read_text(record_path))
    except json.JSONDecodeError as e:
        raise ValueError(f"{record_path} isn't JSON: {e}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{record_path}: expected a JSON object (an order record's fields)")
    allowed = {"version", "id", "seller", "ordered_on", "sources", "notes", "audit_notes", "components"}
    if unknown := set(data) - allowed:
        raise ValueError(f"{record_path}: unknown keys: {', '.join(sorted(unknown))}")
    if "version" in data and (type(data["version"]) is not int or data["version"] != 1):
        raise ValueError(f"{record_path}: expected order record version 1")
    components = data.pop("components", [])
    data.pop("version", None)
    if not isinstance(components, list):
        raise ValueError(f"{record_path}: components must be a list")
    for item in components:
        if not isinstance(item, dict) or item.get("kind") not in ("cards", "tokens", "product") \
                or set(item) - {"id", "kind", "path", "status", "received_on", "checks"}:
            raise ValueError(f"{record_path}: a component needs a kind (cards, tokens or product) and may give "
                             "its id and checks")
        if item.get("status", "pending") != "pending" or item.get("received_on", "") != "":
            raise ValueError(f"{record_path}: a new order's components are pending")
    return data, components


def _select(text):
    """{select, quantity} from SELECT[=QTY]."""
    select, eq, qty = text.rpartition("=") if "=" in text else (text, "", "")
    if not eq:
        return {"select": text, "quantity": None}
    try:
        return {"select": select, "quantity": int(qty)}
    except ValueError:
        raise ValueError(f"{text!r}: the quantity after = must be a whole number") from None


# ------------------------------------------------------------------ order

def _component_label(inv, c):
    if c.kind == "product":
        product = inv.product(c.product_stem)
        n = sum(item.qty or 0 for item in product.items) if product else 0
    else:
        sheet = inv.payloads.get(c.path)
        n = sum(row.qty or 0 for row in sheet.rows) if sheet else 0
    return f"{c.id} ({c.kind}, {c.status}, {n})"


def _readable_orders(inv):
    return [o for o in inv.orders if o.error is None and isinstance(o.data, dict)]


def order_list(args):
    from decklab.lib import purchases
    inv = _ops().current()
    found = []
    for o in _readable_orders(inv):
        status = purchases.order_status([c.data for c in o.components]) if o.components else "pending"
        if args.pending and status not in ("pending", "partial"):
            continue
        found.append((o, status))
    found.sort(key=lambda pair: (pair[0].ordered_on or "", pair[0].id or ""), reverse=True)
    if args.json:
        print(json.dumps([{**o.record(), "status": s} for o, s in found], ensure_ascii=False, indent=2))
        return 0
    print(f"{len(found)} order{'' if len(found) == 1 else 's'}.")
    for o, status in found:
        print(f"  {o.id}  {status}  {o.seller or '(no seller)'}  {o.ordered_on or '(no date)'}")
        print("      " + ", ".join(_component_label(inv, c) for c in o.components))
    return 0


def order_show(args):
    from decklab.lib.inventory import files
    inv = _ops().current()
    o = inv.order(args.order)
    if o is None or o.error is not None:
        _say(f"There's no order {args.order!r}." if o is None else f"{o.path} can't be read: {o.error}")
        return 1
    if args.json:
        print(json.dumps(o.record(), ensure_ascii=False, indent=2))
        return 0
    if args.csv:
        c = next((c for c in o.components if c.id == args.csv), None)
        if c is None:
            _say(f"Order {o.id} has no component {args.csv!r}.")
            return 1
        source = inv.product(c.product_stem) if c.kind == "product" else inv.payloads.get(c.path)
        data = files.render_source(source) if source is not None else None
        if data is None:
            _say(f"{c.path} isn't there to print.")
            return 1
        sys.stdout.write(data.decode("utf-8"))
        return 0
    print(f"Order {o.id}: {o.seller or '(no seller)'}, ordered {o.ordered_on or '(no date)'}")
    if o.notes:
        print(f"  notes: {o.notes}")
    for source in o.sources or []:
        print(f"  source: {source}")
    for c in o.components:
        received = f", received {c.received_on}" if c.received_on else ""
        print(f"  {c.id}: {c.kind}, {c.status}{received}  ({c.path})")
        for n, check in enumerate(c.checks or [], 1):
            print(f"    check {n}: {check}")
        for check in c.verified_checks or []:
            print(f"    verified: {check}")
        if c.kind == "product":
            product = inv.product(c.product_stem)
            items = product.items if product else ()
            print(f"    {sum(item.qty or 0 for item in items)} cards in {len(items)} rows (--csv {c.id} prints them)")
            continue
        sheet = inv.payloads.get(c.path)
        for n, row in enumerate(sheet.rows if sheet else (), 1):
            if c.kind == "cards":
                text = (f"{row.text('quantity')} x {row.text('name')} ({row.text('set').upper()} "
                        f"{row.text('collector_number')}, {row.text('finish')})")
                extra = " ".join(filter(None, (row.text("condition"), row.text("language"))))
            else:
                face = row.text("front") + (f" // {row.text('back')}" if row.text("back") else "")
                printing = " ".join(filter(None, (row.text("set").upper(), row.text("front_collector_number"),
                                                  row.text("back_collector_number"), row.text("finish"))))
                text = f"{row.text('quantity')} x {face}" + (f" ({printing})" if printing else "")
                extra = "; ".join(filter(None, (row.text("front_details"), row.text("back_details"))))
            notes = row.text("notes")
            print(f"    {n}. {text}" + (f" {extra}" if extra else "") + (f"  [{notes}]" if notes else ""))
    return 0


def order_add(args):
    record, settings = _fields(args.record)
    for key, value in (("id", args.id), ("seller", args.seller), ("ordered_on", args.ordered_on),
                       ("sources", args.source), ("notes", args.notes)):
        if value is not None:
            if key == "id" and record.get("id") not in (None, value):
                raise ValueError(f"--id {value} isn't the record's id {record['id']}")
            record[key] = value
    if not record.get("id"):
        raise ValueError("Give the order's id (--id, or the record's id)")
    oid = record["id"]
    given = {"cards": args.cards, "tokens": args.tokens, "product": args.product}
    for item in settings:
        if not given.get(item["kind"]):
            raise ValueError(f"The record names a {item['kind']} component, but no file for it was given")
    if args.product and not args.product_csv:
        raise ValueError("--product needs --product-csv (the product's card list)")
    if args.product_csv and not args.product:
        raise ValueError("--product-csv needs --product STEM")
    by_kind = {item["kind"]: item for item in settings}
    checks = {}
    for text in args.check:
        cid, eq, check = text.partition("=")
        if not eq:
            raise ValueError(f"--check {text!r}: give it as COMPONENT=TEXT")
        checks.setdefault(cid, []).append(check)

    def part(kind, rows, default_id):
        item = by_kind.get(kind, {})
        cid = item.get("id") or default_id
        if item.get("path") is not None:
            from decklab.lib.inventory import paths
            expected = paths.product(args.product) if kind == "product" \
                else paths.payload(kind, "pending", f"{oid}.csv")
            if item["path"] != expected:
                raise ValueError(f"The record's {kind} component path should be {expected}")
        return {"id": cid, "checks": list(item.get("checks") or []) + checks.pop(cid, []), **rows}

    params = {"record": record, "repo": _repo(), "check_cards": not args.no_check,
              "fulfils": [_select(text) for text in args.fulfils]}
    if args.extra_copies:
        params["extra_copies"] = list(args.extra_copies)
    if args.cards:
        params["cards"] = part("cards", {"rows": read_cards(args.cards)}, "cards")
    if args.tokens:
        params["tokens"] = part("tokens", {"rows": read_tokens(args.tokens)}, "tokens")
    if args.product:
        columns, rows = read_product(args.product_csv)
        params["product"] = part("product", {"stem": args.product, "columns": columns, "rows": rows,
                                             "name": args.name, "format": args.format,
                                             "status": args.product_status, "notes": args.product_notes},
                                 args.product)
    if checks:
        raise ValueError(f"--check names no component of this order: {', '.join(sorted(checks))}")
    return _run(args, _ops().Op("order.add", params), refresh=True)


def order_edit(args):
    inv = _ops().current()
    o = inv.order(args.order)
    c = next((c for c in (o.components if o else ()) if c.id == args.component), None)
    rows = read_tokens(args.csv) if c is not None and c.kind == "tokens" else read_cards_exact(args.csv)
    return _run(args, _ops().Op("order.edit", {"order": args.order, "component": args.component, "rows": rows,
                                               "check_cards": not args.no_check}),
                refresh=True)


def order_record(args):
    values = {key: value for key, value in (("seller", args.seller), ("ordered_on", args.ordered_on),
                                           ("notes", args.notes), ("sources", args.source)) if value is not None}
    if args.clear_sources:
        values["sources"] = []
    return _run(args, _ops().Op("order.record", {"order": args.order, "values": values, "repo": _repo()}))


def read_cards_exact(path):
    """A cards payload copy's rows, which must have exactly collection.csv's columns."""
    from decklab.lib.inventory import rules
    try:
        return rules.parse_csv(io.StringIO(_read_text(path), newline=""), rules.FIELDS, path)
    except csv.Error as e:
        raise ValueError(f"{path}: {e}") from None


def order_checks(args):
    params = {"order": args.order, "component": args.component}
    if args.add is not None:
        params["add"] = args.add
    elif args.resolve is not None:
        params["resolve"] = args.resolve
    elif args.withdraw is not None:
        params["withdraw"] = args.withdraw
    else:
        params["clear"] = True
    return _run(args, _ops().Op("order.checks", params))


def order_split(args):
    take = []
    for text in args.take:
        row, colon, qty = text.partition(":")
        try:
            take.append({"row": int(row), "quantity": int(qty) if colon else None})
        except ValueError:
            raise ValueError(f"--take {text!r}: give it as ROW or ROW:QTY (whole numbers)") from None
    return _run(args, _ops().Op("order.split", {"order": args.order, "component": args.component,
                                                "new_id": args.new_id, "take": take,
                                                "move_checks": args.move_check, "copy_checks": args.copy_check,
                                                "keep_checks": args.keep_check}),
                refresh=True)


def order_cancel(args):
    inv = _ops().current()
    o = inv.order(args.order)
    c = next((c for c in (o.components if o is not None else ()) if c.id == args.component), None)
    code = _run(args, _ops().Op("order.cancel", {"order": args.order, "component": args.component,
                                                 "reason": args.reason, "restore_queue": args.restore_queue}),
                refresh=True)
    if not args.dry_run and c is not None and c.kind != "product" and code in (0, FOLLOW_UP_FAILED):
        _cancel_notes(c.path)
    return code


def order_remove(args):
    return _run(args, _ops().Op("order.remove", {"order": args.order, "reason": args.reason,
                                                  "restore_queue": True}), refresh=True)


def order_merge(args):
    renames = []
    for text in args.rename:
        left, equals, new_id = text.partition("=")
        oid, colon, component = left.rpartition(":")
        if not (equals and colon and oid and component and new_id):
            raise ValueError(f"--rename {text!r}: give it as OTHER:COMPONENT=NEW")
        renames.append({"order": oid, "component": component, "id": new_id})
    return _run(args, _ops().Op("order.merge", {"order": args.order, "others": args.others, "renames": renames,
                                                "notes": args.notes, "repo": _repo()}))


def order_extra_copies(args):
    return _run(args, _ops().Op("order.extra_copies", {"order": args.order, "component": args.component,
                                                       "undo": args.undo}),
                refresh=True)


def _cancel_notes(old, removed=False):
    """List Markdown references to a removed order or a cancelled payload's old path."""
    from decklab.lib import config
    repo = config.records_dir()
    target = old.split("/", 1)[1]          # orders/<file>.csv, as a link from magic/<folder>/ ends
    linked = []
    for path in sorted((repo / "magic").rglob("*.md")):
        try:
            if target in path.read_text(encoding="utf-8-sig"):
                linked.append(path.relative_to(repo).as_posix())
        except (OSError, UnicodeDecodeError):
            continue
    if linked:
        outcome = "was removed with the order" if removed else "is now under cancelled/"
        _say(f"Note: {', '.join(linked)} link{'' if len(linked) > 1 else 's'} to {old}, which {outcome}; "
             "update the links if they should still lead to it.")


# ------------------------------------------------------------------ product

def product_add(args):
    columns, rows = read_product(args.csv)
    product = {"stem": args.stem, "columns": columns, "rows": rows, "name": args.name, "format": args.format,
               "status": args.status, "notes": args.notes}
    return _run(args, _ops().Op("product.add", {"order": args.order, "product": product,
                                                "check_cards": not args.no_check}),
                refresh=True)


def product_intact(args):
    return _run(args, _ops().Op("product.set_intact", {"stem": args.stem, "intact": args.intact}),
                refresh=True)


def product_edit(args):
    params = {"stem": args.stem, "check_cards": not args.no_check,
              "values": {key: getattr(args, key) for key in ("name", "format", "status", "notes")
                         if getattr(args, key) is not None}}
    if args.csv:
        params["columns"], params["rows"] = read_product(args.csv)
    return _run(args, _ops().Op("product.edit", params), refresh=True)


# ------------------------------------------------------------------ watchlist

def watchlist_list(args):
    from decklab.lib.inventory import files
    inv = _ops().current()
    sheet = inv.watchlist
    if sheet.error is not None:
        _say(f"{sheet.path} can't be read: {sheet.error}")
        return 1
    if args.csv:
        sys.stdout.write(files.render_sheet(sheet, QUEUE_FIELDS).decode("utf-8"))
        return 0
    rows = [(n, {k: row.text(k) for k in QUEUE_FIELDS}) for n, row in enumerate(sheet.rows, 1)]
    if args.state:
        rows = [(n, row) for n, row in rows if row["state"] == args.state]
    if args.json:
        print(json.dumps([{"n": n, **row} for n, row in rows], ensure_ascii=False, indent=2))
        return 0
    print(f"{len(rows)} watchlist row{'' if len(rows) == 1 else 's'}.")
    for n, row in rows:
        printing = " ".join(filter(None, (row["set"].upper(), row["collector_number"], row["finish"])))
        line = f"  #{n}  {row['quantity']} x {row['name']}"
        line += f" ({row['printing']}" + (f": {printing})" if printing else ")")
        line += f" for {row['for']}" if row["for"] else ""
        line += f"  {row['state']}"
        if row["listed_aud"]:
            stock = {"yes": ", in stock", "no": ", out of stock"}.get(row["in_stock"], "")
            line += f"  A${row['listed_aud']} at {row['listed_at']}{stock}, {row['checked']}"
        print(line)
        if row["notes"]:
            print(f"      notes: {row['notes']}")
    return 0


def watchlist_set(args):
    values = {}
    for column, attr in QUEUE_FLAGS.items():
        value = getattr(args, attr)
        if value is not None:
            values[column] = value
    if args.add:
        if args.select:
            raise ValueError("--add makes a new row; don't name an existing one")
        params = {"select": None, "values": values, "add": True, "repo": _repo()}
    else:
        if not args.select:
            raise ValueError("Name the row to change (NAME, NAME@FOR or #N), or --add a new one")
        params = {"select": args.select, "values": values, "repo": _repo()}
    if not values:
        raise ValueError("Say what to set (--quantity, --state, --listed-aud, ...)")
    return _run(args, _ops().Op("watchlist.set", params))


def watchlist_remove(args):
    return _run(args, _ops().Op("watchlist.remove", {"select": args.select}))


def watchlist_apply(args):
    return _run(args, _ops().Op("watchlist.replace", {"rows": read_queue_csv(args.csv), "repo": _repo()}))
