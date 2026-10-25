"""`python -m decklab.db receive`: preview or record a recorded order's arrival (the Receipts
page's operation, lib/inventory/receive.py), with the deck tables it makes stale refreshed in
the same change.

    python -m decklab.db receive --order 2026-10-07-shop-a
    python -m decklab.db receive --order ID --component cards --verified cards --date 2026-10-08 --apply
    python -m decklab.db receive --order ID --component tokens --rows tokens=FIXED.csv --verified tokens \\
        --date 2026-10-08 --apply
    python -m decklab.db receive --order ID --component product-x --intact no --date 2026-10-08 --apply

A preview is the default and writes nothing; --apply needs the actual arrival date (--date). A
valid preview prints a token: add --expect TOKEN on apply to refuse if either the inventory or
the receipt's selected components, received rows, date or checks changed. Without --expect,
apply revalidates the current inventory as before. With
no --component every pending component is selected; repeat it for a partial shipment (for part of
one component, split it into its own component first).

--verified C says component C's physical checks were done and its rows hold the actual received
facts: a cards component with checks, and every tokens component, needs it. Token rows must keep
their physical front/back pairing and quantities, have no unresolved pairing note, and say
"single-sided verified" for a genuinely blank reverse (never guess an unknown reverse).
--rows C=FILE gives component C's rows as received (a CSV in its columns: the collection's for
cards, the token cards' for tokens), under the Receipts page's rules: the same total quantity and,
for cards, the same copies of each name, every printing and finish in the card data. A product
needs --intact yes (kept as its decks, in its own sleeves and box) or --intact no (broken up into
the shared pool); its token checks stay open until its physical tokens are recorded.

The receipt is one change (actor claude, or --actor PROFILE, from the command line), the deck tables it makes
stale refreshed inside it (the receipt kind is registered with refresh=True:
lib/inventory/refresh.py's in_op). The preview lists the parts of the inventory and the decks
that change, in plain words (inventory.changed_labels), from the same previewed change, and
refuses, as the Receipts page does, when the deck tables couldn't be refreshed from the pool
after it. A refresh that fails at apply leaves the decks as they were
and the receipt saved, the tables on the Decks page's Tables out of date list.

Exit codes: 0 done (or previewed); 1 refused, or --apply with something still required; 2 the
database is unavailable; 3 received, but the deck tables couldn't be refreshed (stderr says
why; the receipt itself is saved).
"""
import argparse
import csv
import hashlib
import hmac
import json
import sys
from datetime import datetime, timedelta, timezone

from decklab.db import cli_actor
from decklab.lib import inventory
from decklab.lib.inventory import receive, rules

FOLLOW_UP_FAILED = 3            # received, but the deck tables' refresh didn't finish
NO_TABLES = {"written": [], "skipped": [], "error": None}


def register(sub):
    sp = sub.add_parser("receive", help="Preview or record a recorded order's arrival.",
                        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp.add_argument("--order", help="the order record's id")
    sp.add_argument("--component", action="append", default=[], metavar="C",
                    help="a component that arrived (repeat; default: every pending one)")
    sp.add_argument("--verified", action="append", default=[], metavar="C",
                    help="component C's checks are done and its rows hold the received facts (repeat)")
    sp.add_argument("--intact", choices=("yes", "no"), help="for a product: keep it intact, or break it up")
    sp.add_argument("--rows", action="append", default=[], metavar="C=FILE",
                    help="component C's rows as received, from a CSV in its columns (repeat)")
    sp.add_argument("--date", default="", help="the actual arrival date, YYYY-MM-DD (needed with --apply)")
    sp.add_argument("--apply", action="store_true", help="record the arrival (a preview otherwise)")
    sp.add_argument("--expect", metavar="TOKEN",
                    help="with --apply, require the inventory and receipt intent from this preview")
    cli_actor.add_argument(sp)
    sp.set_defaults(func=run)


def _today():
    """The household's date (UTC+10), as the Receipts page takes it."""
    return datetime.now(timezone(timedelta(hours=10))).date().isoformat()


def _read_rows(value):
    """(component id, [row]) from --rows C=FILE."""
    ident, sep, name = value.partition("=")
    if not sep or not ident or not name:
        raise ValueError(f"--rows takes COMPONENT=FILE, not {value!r}")
    with open(name, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError(f"{name}: a row has the wrong number of columns")
    return ident, rows


def _components(inv, args):
    """The inputs the arguments name (receive.op's components)."""
    order = receive.record(inv, args.order)
    rows = dict(_read_rows(value) for value in args.rows)
    pending = [c.id for c in order.components if c.status == "pending"]
    wanted = list(dict.fromkeys(args.component)) or pending
    if not wanted:
        raise ValueError(f"{args.order} has no pending components")
    for name, ids in (("--verified", args.verified), ("--rows", list(rows))):
        if set(ids) - set(wanted):
            raise ValueError(f"{name} must name a selected component")
    kinds = {c.id: c.kind for c in order.components}
    out = []
    for ident in wanted:
        item = {"id": ident, "verified": ident in args.verified}
        if ident in rows:
            item["rows"] = rows[ident]
        if kinds.get(ident) == "product" and args.intact:
            item["intact"] = args.intact
        out.append(item)
    return out


def run(args):
    actor = cli_actor.resolve(args)
    if not args.order:
        raise ValueError("Specify --order ID")
    if args.apply and not args.date:
        raise ValueError("--apply requires --date YYYY-MM-DD")
    if args.expect is not None and not args.apply:
        raise ValueError("--expect is used with --apply; run a new preview without it")
    date = args.date or _today()
    try:
        rules.valid_date(date)
    except ValueError as e:
        raise ValueError(str(e)) from None
    before = inventory.current()
    components = _components(before, args)
    operation = receive.op(args.order, components, date, wording="cli")
    token = _preview_token(before.revision, operation)
    if args.expect is not None and (len(args.expect) != 64 or not args.expect.isascii()
                                    or not hmac.compare_digest(args.expect, token)):
        raise inventory.Conflict("The inventory or receipt options changed. Preview again before receiving.")
    print(f"{'Receive' if args.apply else 'Preview'} {args.order}: " + ", ".join(c["id"] for c in components))
    order = receive.record(before, args.order)
    for component in order.components:
        if component.id in {c["id"] for c in components}:
            for check in component.checks:
                print(f"  Check {component.id}: {check}")
    found = receive.blockers(before, operation)
    for blocker in found:
        print("  Required: " + blocker)
    if found:
        return 1 if args.apply else 0
    if any("rows" in c for c in components):
        from decklab.lib import cards
        cards.info()                    # the card data the edited rows are checked against
    after, summary = inventory.preview(operation)
    for kind, counts in summary.extra["totals"]:
        print(f"  {counts['cards']} {kind}; {counts['added_rows']} new rows; "
              f"{counts['bumped_rows']} existing rows increased")
        if counts.get("skipped_basics"):
            print(f"  {counts['skipped_basics']} ordinary basic lands omitted")
    tables = _tables(summary)
    if tables["error"] and tables["error"] != inventory.DECK_SAVES_PAUSED:
        raise ValueError(tables["error"])       # an incomplete pool, refused as the page refuses it
    for words in inventory.changed_labels(before, after):
        print("  " + words)
    if tables["error"]:                         # the backend can't save deck texts yet
        print(f"  Deck tables won't be refreshed: {tables['error']}", file=sys.stderr)
    if not args.apply:
        if not args.date:
            print(f"  (previewed as arriving today, {date})")
        print(f"Preview token: {token}")
        print("Preview only; nothing changed. Add --date YYYY-MM-DD --apply --expect TOKEN to receive this preview.")
        return 0
    message = f"receive {args.order}: " + ", ".join(c["id"] for c in components)
    _, summary = inventory.apply(operation, actor, message, expected_revision=before.revision)
    print("Received.")
    return 0 if _say_tables(_tables(summary)) else FOLLOW_UP_FAILED


def _preview_token(revision, operation):
    """Bind a preview to its snapshot and canonical receipt intent, with no saved state.

    Components are a selection, so their flag order is irrelevant. Received rows keep their
    order and all fields: changing the supplied physical facts requires another preview.
    The backend checks revision again under its write lock when apply saves the operation.
    """
    intent = dict(operation.params)
    intent["components"] = sorted(intent["components"], key=lambda item: item["id"])
    payload = json.dumps({"version": 1, "revision": revision, "receipt": intent},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _tables(summary):
    """The deck tables' outcome of the receipt's change (refresh.in_op's Summary.extra["tables"])."""
    found = (summary.extra or {}).get("tables")
    return dict(found) if isinstance(found, dict) else dict(NO_TABLES)


def _say_tables(result):
    """Print the deck tables' outcome of the receipt's change; False when they couldn't be
    refreshed (a deck skipped, because the receipt changed it itself or its Sleeves or Deck box
    would change, is only a warning)."""
    if result["error"]:
        print(f"Deck tables not refreshed: {result['error']}", file=sys.stderr)
        print("  Update them with Update all on the Decks page's Tables out of date list (or python -m "
              "decklab.db deck tables --apply) once that's fixed.", file=sys.stderr)
        return False
    for item in result["written"]:
        print(f"  Refreshed: {item['id']}")
    for item in result["skipped"]:
        why = {"changed": "the change rewrote it itself",
               "kit": "its Sleeves or Deck box would change"}.get(item["why"], item["why"])
        print(f"  Skipped: {item['id']} ({why}); its table stays stale", file=sys.stderr)
    if not result["written"] and not result["skipped"]:
        print("  No deck tables needed refreshing.")
    return True
