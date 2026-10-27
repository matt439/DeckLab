"""collection trade (E7-S22), added to `python -m decklab.db collection` by inv_collection.register:

    collection trade --out FILE --in FILE [--space S] [--with T] -m MESSAGE [--allow-in-use] [--dry-run]

A trade as one change (collection.trade): --out lists the cards that left, in the collection's
columns (name, set, collector_number, finish and quantity at least: the copies given, matched on
the identity key; the other columns, when present, aren't read), and --in the cards that came in,
checked and merged as collection merge checks and merges a file (every column, exact Scryfall
names, ordinary basic lands left out). No raw import is kept: the audit trail holds both sides.

The change set's message is -m followed by both sides ("Trade with T: gave 2 Llanowar Elves (FDN
227); got 1 Sol Ring (C21 263)"), and its reason "Traded" (or "Traded with T"); no prices. A
given card that built decks or intact products hold is named in the preview and refused unless
--allow-in-use, as collection edit refuses it. As merge, it doesn't refresh the decks'
owned-vs-needed tables: afterwards it names those now out of date (inv_decks.stale_notes), and
--dry-run names those it would leave. Exit codes: 0 done (or previewed), 1 refused, 2 the database
can't be reached.
"""
import csv
import io
from pathlib import Path

from decklab.db import cli_actor
from decklab.lib import inventory
from decklab.lib.inventory import ops_collection as ops
from decklab.lib.inventory import paths, rules

OUT_COLUMNS = ("name", "set", "collector_number", "finish", "quantity")
MAX_WITH = 80                       # characters of the who-with note


def add_parser(verbs):
    sp = verbs.add_parser("trade", help="Record a trade as one change: the cards that left and the cards that came in.",
                          description="Record a trade in one change: the copies in --out leave the collection (rows "
                                      "matched on set, collector_number and finish) and the cards in --in are merged "
                                      "in, as collection merge merges a file.")
    sp.add_argument("--out", required=True, metavar="FILE", dest="gave",
                    help="the cards that left, in the collection's columns (quantity: the copies given)")
    sp.add_argument("--in", required=True, metavar="FILE", dest="got",
                    help="the cards that came in, in the collection's columns")
    sp.add_argument("--space", default=paths.HOME, help="the space (home by default)")
    sp.add_argument("--with", dest="with_", metavar="T", help="who the trade was with (a short note, optional)")
    sp.add_argument("-m", "--message", required=True, help="what the change does, for the history")
    sp.add_argument("--allow-in-use", action="store_true",
                    help="save it though built decks or intact products hold copies given away")
    sp.add_argument("--dry-run", action="store_true", help="show both sides and the decks that lose cards; save nothing")
    cli_actor.add_argument(sp)
    sp.set_defaults(func=trade)


def _with(value):
    """The who-with note, one line of at most MAX_WITH characters ("" when not given)."""
    value = (value or "").strip()
    if any(ch in value for ch in "\r\n\0") or len(value) > MAX_WITH:
        raise ValueError(f"--with must be one line of at most {MAX_WITH} characters")
    return value


def read_out(path, rows):
    """[(row as listed, copies given)] of FILE, the cards that left: every row a listed printing
    of that name, given once and no more copies than the collection has; ValueError otherwise."""
    from decklab.db.inv_collection import FINISHES, _copies, _quantity
    try:
        text = Path(path).read_bytes().decode("utf-8").removeprefix("﻿").replace("\r\n", "\n")
    except OSError as e:
        raise ValueError(f"{path} can't be read ({e.strerror or e})") from None
    except UnicodeDecodeError as e:
        raise ValueError(f"{path} isn't UTF-8 text ({e})") from None
    reader = csv.reader(io.StringIO(text, newline=""))
    current = {rules.ident(row): row for row in rows}
    out, seen = [], set()
    try:
        header = next(reader, None) or []
        if missing := [c for c in OUT_COLUMNS if c not in header]:
            raise ValueError(f"{path} needs the columns {','.join(OUT_COLUMNS)} (missing {', '.join(missing)})")
        if unknown := sorted(set(header) - set(rules.FIELDS)) or len(header) != len(set(header)):
            raise ValueError(f"{path}: only the collection's columns, once each ({','.join(rules.FIELDS)})"
                             + (f"; unknown: {', '.join(unknown)}" if unknown else ""))
        for values in reader:
            if not values:
                continue
            where = f"{path} line {reader.line_num}"
            if len(values) != len(header):
                raise ValueError(f"{where}: {len(values)} columns, not {len(header)}")
            row = dict(zip(header, values))
            finish = row["finish"].strip().lower()
            if finish not in FINISHES:
                raise ValueError(f"{where}: finish must be {', '.join(FINISHES)}, got {row['finish']!r}")
            key = (row["set"].strip().lower(), row["collector_number"].strip(), finish)
            label = f"{key[0].upper()} {key[1]} {key[2]}"
            if key in seen:
                raise ValueError(f"{where}: {label} is listed twice; give each printing once")
            seen.add(key)
            old = current.get(key)
            if old is None:
                raise ValueError(f"{where}: the collection has no {label} row (collection list shows its rows)")
            if row["name"].strip() != old["name"]:
                raise ValueError(f"{where}: {label} is {old['name']!r} in the collection, not {row['name'].strip()!r}")
            copies = int(_quantity(row["quantity"], f"{where}: quantity"))
            if not copies:
                raise ValueError(f"{where}: quantity is the copies given, at least 1")
            if copies > int(old["quantity"]):
                raise ValueError(f"{where}: the collection has {_copies(old)} of "
                                 f"{old['name']} ({label}), not {copies}")
            out.append((old, copies))
    except csv.Error as e:
        raise ValueError(f"{path} can't be read as CSV: {e}") from None
    if not out:
        raise ValueError(f"{path} lists no cards: a trade needs the cards that left")
    return out


def trade(args):
    from decklab.db.inv_collection import _copies, _listed, _save, read_file
    message = args.message.strip()
    if not message:
        raise ValueError("-m needs a message saying what this change does")
    who = _with(args.with_)
    actor = cli_actor.resolve(args)
    got, _ = read_file(args.got)
    whose, title, snapshot, rows, sha = _listed(args, "")    # no --expect: the snapshot read now
    gave = read_out(args.gave, rows)
    op = inventory.Op("collection.trade", {
        "space": args.space, "gave": [[*rules.ident(row), n] for row, n in gave], "got": got,
        "sha256": sha, "whose": whose, "expect_decks_revision": snapshot.decks_revision})
    try:
        with inventory.pinned(snapshot):
            _, summary = inventory.preview(op, refresh=False)
    except (inventory.Invalid, inventory.Conflict) as e:
        raise ValueError(f"The trade can't be saved: {e}") from None
    tracked = ops.trade_tracked(summary.extra["got"], rows)
    full = ops.trade_message(message, gave, tracked, who)
    lines = [f"  Gave {_copies({'quantity': str(n)})} of {row['name']} ({row['set'].upper()} "
             f"{row['collector_number']}, {row['finish']}): {row['quantity']} -> {int(row['quantity']) - n}"
             for row, n in gave]
    lines += [f"  Got {_copies(row)} of {row['name']} ({row['set'].upper()} {row['collector_number']}, "
              f"{row['finish']})" for row in tracked]
    skipped = summary.counts["skipped_basics"]
    if skipped:
        lines.append(f"  {skipped} ordinary basic lands got aren't tracked, so they're left out.")
    would = [f"Would record a trade in {whose}{' with ' + who if who else ''}: "
             f"gave {summary.counts['gave']} cards, got {summary.counts['cards']}.", *lines]
    did = [f"Recorded the trade in {whose}{' with ' + who if who else ''}: "
           f"gave {summary.counts['gave']} cards, got {summary.counts['cards']}.", *lines]
    return _save(args, op, snapshot, title, actor, f"Traded{' with ' + who if who else ''}", would, did,
                 message=full)
