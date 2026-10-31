"""The dice and counters' commands (E7-S24), Claude's way to read and change a space's owned dice
and counters (the Tokens page's Dice and counters panel; lib/inventory/dice_rules.py), whichever
inventory backend holds them:

  python -m decklab.db dice list [--space S] [--json]
  python -m decklab.db dice add --type die|counter --quantity N [--size Z] [--kind K] [--design D]
                               [--notes T] [--expect SHA] [--space S] -m MSG
  python -m decklab.db dice edit ROW --expect SHA [item options] [--space S] -m MSG
  python -m decklab.db dice remove ROW --expect SHA [--space S] -m MSG --reason R

ROW is the number dice list prints before a row (1 for the first), and SHA the list's sha it
prints (its first 12 characters are enough; "none" for a space with none yet): the change is
refused when the list has changed since that listing. --size is a die's (d4, d6, d8, d10, d12,
d20, spindown), --kind a counter's (+1/+1, poison, loyalty, ...; left out, a generic counter that
stands for any kind); an edit keeps every column it isn't given, and "" clears one. Each write is
one change by "claude" (or --actor PROFILE) with the -m message (and a removal's --reason), one
change set in the audit trail; --dry-run previews it. Until the database has migration 0020 the
list is empty and every write is refused, saying so. Nothing here changes a decklist, the
playable pool or a deck table.

Exit codes as the other commands: 0 done, 1 refused, 2 the database can't be reached.
"""
import json
import re
import sys

from decklab.db import cli_actor

MIN_EXPECT = 12
OPTIONS = (("--type", "type"), ("--size", "size"), ("--kind", "kind"), ("--design", "design"),
           ("--quantity", "quantity"), ("--notes", "notes"))


def register(sub):
    """Add the dice command and its own subcommands to python -m decklab.db's parser."""
    p = sub.add_parser("dice", help="List or change a space's owned dice and counters (list, add, edit, remove).",
                       description="List or change a space's owned dice and counters. Writes need -m saying what "
                                   "they do; a removal also --reason.")
    p.set_defaults(func=run)
    actions = p.add_subparsers(dest="action", required=True, metavar="action")

    def action(name, help_text, write=True, row=False):
        sp = actions.add_parser(name, help=help_text, description=help_text)
        if row:
            sp.add_argument("row", type=int, help="the row's number, as dice list prints it")
        sp.add_argument("--space", default="home", help="whose dice and counters (default home)")
        if write:
            sp.add_argument("-m", "--message", required=True, help="what this change does, for the history")
            sp.add_argument("--dry-run", action="store_true", help="show the row before and after; save nothing")
            cli_actor.add_argument(sp)
            sp.add_argument("--expect", required=row, metavar="SHA",
                            help="the sha dice list printed (at least its first 12 characters; \"none\" before the "
                                 "space has any): refused if the list has changed since")
        return sp

    sp = action("list", "Print a space's dice and counters, numbered, in the order they're kept.", write=False)
    sp.add_argument("--json", action="store_true", help="print the rows as JSON (dice.csv's columns)")
    sp = action("add", "Add a die or counter.")
    _options(sp, required=("--type", "--quantity"))
    sp = action("edit", "Change a die or counter (the columns given; the rest stay).", row=True)
    _options(sp)
    sp = action("remove", "Remove a die or counter.", row=True)
    sp.add_argument("--reason", required=True, help="why it's removed, for the history")


def _options(sp, required=()):
    for flag, column in OPTIONS:
        sp.add_argument(flag, dest=column, default=None, required=flag in required, help=f"the item's {column}")


def _say(text):
    print(text, file=sys.stderr)


def _relist(space):
    from decklab.lib import spaces
    return "dice list" if space == spaces.HOME else f"dice list --space {space}"


def _read(space):
    """(the space's dice Sheet, its rows as dicts, its sha or None, whether the backend can record them)."""
    from decklab.lib import inventory
    from decklab.lib.inventory import files
    inv = inventory.current()
    sheet = inv.dice_set(space)
    sha = files.rendered_sha256(sheet) if sheet.exists and sheet.error is None else None
    return sheet, [row.as_dict() for row in sheet.rows], sha, inv.dice_ready


def _list(space, args):
    from decklab.db import read_notices
    from decklab.lib.inventory import dice_rules, ops_dice
    sheet, rows, sha, ready = _read(space)
    read_notices.Reporter(getattr(args, "dbname", None)).space("collection", space, label="dice and counters")
    if args.json:
        print(json.dumps({"sha256": sha, "ready": ready, "rows": rows}, ensure_ascii=False, indent=2))
        return 0
    if not ready:
        print(dice_rules.DICE_REQUIRED)
        return 0
    if sheet.error is not None:
        _say(f"The dice and counters can't be read: {sheet.error}")
        return 1
    items = sum(int(row["quantity"]) for row in rows if str(row.get("quantity") or "").isdigit())
    print(f"{ops_dice.whose(space)[:1].upper()}{ops_dice.whose(space)[1:]}: {len(rows)} row"
          f"{'' if len(rows) == 1 else 's'}, {items} item{'' if items == 1 else 's'}.")
    print(f"sha {sha or 'none'} (give it to edit or remove as --expect)")
    for n, row in enumerate(rows, 1):
        print(f"{n:>4}. {dice_rules.label(row)} ×{row['quantity']}" + (f"  ({row['notes']})" if row["notes"] else ""))
    for problem in sheet.problems:
        print(f"  ! {problem}")
    return 0


def _write(space, args, actor):
    from decklab.lib import inventory
    from decklab.lib.inventory import Op, dice_rules, ops_dice
    if not args.message.strip():
        _say("-m needs a message saying what this change does.")
        return 1
    reason = getattr(args, "reason", None)
    if args.action == "remove" and not reason.strip():
        _say("--reason needs a reason saying why the item is removed.")
        return 1
    sheet, rows, sha, ready = _read(space)
    if not ready:
        _say(dice_rules.DICE_REQUIRED)
        return 1
    expect = (args.expect or "").strip().lower()
    if args.expect is not None:
        if expect != "none" and not re.fullmatch(f"[0-9a-f]{{{MIN_EXPECT},64}}", expect):
            _say(f"--expect needs the sha dice list printed (at least its first {MIN_EXPECT} characters), or none.")
            return 1
        if (sha is None) != (expect == "none") or sha and not sha.startswith(expect):
            _say(f"The dice and counters have changed since that listing: run {_relist(space)} again and retry "
                 "with its sha.")
            return 1
    params = {"space": space, "sha256": sha}
    base = None
    if args.action != "add":
        if not 1 <= args.row <= len(rows):
            _say(f"There's no row {args.row}: {ops_dice.whose(space)} have {len(rows)} ({_relist(space)} numbers them).")
            return 1
        base = rows[args.row - 1]
        params["base"] = base
    if args.action != "remove":
        fields = dict(base or {key: "" for key in dice_rules.DICE_FIELDS})
        fields.update({column: getattr(args, column) for _, column in OPTIONS if getattr(args, column) is not None})
        try:
            params["row"] = dice_rules.clean_row(fields)
        except ValueError as e:
            _say(f"That can't be saved: {e}")
            return 1
    try:
        op = Op(f"dice.{args.action}", params)
        if args.dry_run:
            after, summary = inventory.preview(op)
        else:
            after, summary = inventory.apply(op, actor, args.message.strip(),
                                             reason=reason.strip() if reason else None)
    except ops_dice.SameItem as e:
        _say(f"{e} (row {e.index + 1})")
        return 1
    except ops_dice.Stale:
        _say(f"The dice and counters changed while this ran: run {_relist(space)} again and retry.")
        return 1
    if args.dry_run:
        print(f"Would {args.action} an item in {ops_dice.whose(space)}.")
        print("Before: " + (json.dumps(base, ensure_ascii=False, sort_keys=True) if base else "(no row)"))
        index = summary.extra.get("index")
        new = after.dice_set(space).rows[index].as_dict() if index is not None else None
        print("After: " + (json.dumps(new, ensure_ascii=False, sort_keys=True) if new else "(no row)"))
        print("Nothing saved (--dry-run).")
    else:
        print(summary.text + ".")
    return 0


def run(args):
    """Run one dice command (python -m decklab.db dice ...); returns the exit code. The caller
    (decklab.db's main) runs it in one pinned inventory snapshot and turns the inventory's
    refusals into exit 1 and an unreachable database into exit 2."""
    from decklab.lib import spaces
    try:
        if args.space != spaces.HOME:
            spaces.get(args.space)
    except spaces.SpaceNotFound:
        _say(f"There's no space {args.space!r} in decklab/config.json.")
        return 1
    if args.action == "list":
        return _list(args.space, args)
    return _write(args.space, args, cli_actor.resolve(args))
