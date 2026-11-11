"""Command-line loose-card loans, using the same operations as the Collection page."""
import csv
import json
import sys

from decklab.db import cli_actor
from decklab.lib import cards, inventory
from decklab.lib.inventory import loan_rules, ops_collection, ops_loans, paths, rules


def register(verbs):
    parser = verbs.add_parser("loans", help="List this space's private loose-card loans.")
    parser.add_argument("--space", default=paths.HOME)
    parser.add_argument("--all", action="store_true", help="include returned records")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=list_loans)
    parser = verbs.add_parser("lend", help="Lend confirmed free copies of one exact printing.")
    parser.add_argument("set")
    parser.add_argument("number")
    parser.add_argument("finish", choices=rules.FINISHES)
    parser.add_argument("quantity", type=int)
    parser.add_argument("--borrower", required=True, help="the borrower's name, kept private as free text")
    parser.add_argument("--date", required=True, help="lent date, YYYY-MM-DD")
    parser.add_argument("--notes", default="")
    parser.add_argument("--expect", help="the collection list's full SHA, for an additional stale check")
    _write_args(parser)
    parser.set_defaults(func=lend)
    parser = verbs.add_parser("return", help="Record all copies of an open loan returned.")
    parser.add_argument("loan_id")
    parser.add_argument("--date", required=True, help="return date, YYYY-MM-DD")
    _write_args(parser)
    parser.set_defaults(func=return_loan)


def _write_args(parser):
    parser.add_argument("--space", default=paths.HOME)
    parser.add_argument("-m", "--message", required=True)
    parser.add_argument("--dry-run", action="store_true")
    cli_actor.add_argument(parser)


def _space(args):
    from .inv_collection import _space
    _space(args.space)


def list_loans(args):
    _space(args)
    rows = ops_loans.rows_of(inventory.current(), args.space)
    if not args.all:
        rows = loan_rules.open_rows(rows)
    print(f"Privacy: loan records in space {args.space} are private to that space. Do not relay borrower names or notes.", file=sys.stderr)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        writer = csv.DictWriter(sys.stdout, loan_rules.FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return 0


def _save(args, operation):
    _space(args)
    if not args.message.strip():
        raise ValueError("-m needs a message saying what this change does")
    actor = cli_actor.resolve(args)
    if operation.kind == "collection.lend":
        cards.info()
    if args.dry_run:
        after, summary = inventory.preview(operation)
        print("Would: " + summary.text)
    else:
        after, summary = inventory.apply(operation, actor, args.message.strip())
        print(summary.text + f"; loan {summary.extra['loan']['id']}")
    from . import inv_decks
    with inventory.pinned(after):
        inv_decks.stale_notes(args.space)
    return 0


def lend(args):
    _space(args)
    rows = ops_collection.rows_of(inventory.current().collection(args.space))
    key = args.set.lower(), args.number, args.finish
    current = next((row for row in rows if rules.ident(row) == key), None)
    if current is None:
        raise ValueError("Lend an exact printing already recorded in this collection")
    row = {key: current[key] for key in ("name", "set", "collector_number", "finish")}
    row.update(quantity=args.quantity, borrower=args.borrower, lent_on=args.date, notes=args.notes)
    return _save(args, ops_loans.op("lend", space=args.space, row=row, sha256=getattr(args, "expect", None)))


def return_loan(args):
    return _save(args, ops_loans.op("return", space=args.space, loan_id=args.loan_id, returned_on=args.date))
