"""The token cards' commands, Claude's way to read and change a space's token and reminder cards
(the Tokens page's rows; decklab/lib/tokens), whichever inventory backend holds them:

  python -m decklab.db tokens list [--space S] [--json]
  python -m decklab.db tokens check [--space S]
  python -m decklab.db tokens add --front F --quantity N [card options] [--separate] [--expect SHA]
                                 [--space S] -m MSG
  python -m decklab.db tokens edit ROW --expect SHA [card options] [--separate] [--space S] -m MSG
  python -m decklab.db tokens remove ROW --expect SHA [--space S] -m MSG --reason R

ROW is the number tokens list prints before a row (1 for the first), and SHA the list's sha it
prints with them (its first 12 characters are enough; --json gives it as "sha256"): the space's
token cards as rendered, the same sha the Tokens page checks. An edit or removal needs it, so a
row number always names the row of the listing it came from: when the space's token cards have
changed since that listing (a page save moves rows along), the change is refused and nothing is
written (list them again). An add may give it too ("none" for a space with no token cards yet).
The check is made again under the inventory's lock, as the page's is. The card options are
--back, --set, --front-number, --back-number, --finish, --front-details, --back-details and
--notes (and --quantity); an edit keeps every column it isn't given, and "" clears one.

The writes are the Tokens page's (lib/tokens/ops.py: tokens.add, tokens.edit, tokens.remove), with
its rules: the page's limits and row rules, names checked against Scryfall's token, emblem and
reminder faces when the card index is ready (and fixed to their exact spelling), and rows never
merged: a row naming a card another row names is refused unless --separate keeps it apart, which
is allowed only when either isn't fully known. Each write is one change by "claude" (or --actor PROFILE) from the
command line with the -m message (and a removal's --reason): one change set in the audit
trail. check is python -m decklab.lib.tokens --check's: the rules a space's token cards
break, and at home its pending token orders'.

Exit codes as the other commands: 0 done, 1 refused or problems found, 2 the database can't be
reached.
"""
import json
import re
import sys

from decklab.db import cli_actor

MIN_EXPECT = 12                     # characters of the list's sha --expect needs at least
# The card options: (flag, column).
CARD_OPTIONS = (("--front", "front"), ("--back", "back"), ("--set", "set"),
                ("--front-number", "front_collector_number"), ("--back-number", "back_collector_number"),
                ("--finish", "finish"), ("--quantity", "quantity"), ("--front-details", "front_details"),
                ("--back-details", "back_details"), ("--notes", "notes"))


def register(sub):
    """Add the tokens command and its own subcommands to python -m decklab.db's parser."""
    p = sub.add_parser("tokens", help="List, check or change a space's token cards (list, check, add, edit, "
                                      "remove).",
                       description="List, check or change a space's token and reminder cards. Writes need -m "
                                   "saying what they do; a removal also --reason.")
    p.set_defaults(func=run)
    actions = p.add_subparsers(dest="action", required=True, metavar="action")

    def action(name, help_text, write=True, row=False):
        sp = actions.add_parser(name, help=help_text, description=help_text)
        if row:
            sp.add_argument("row", type=int, help="the row's number, as tokens list prints it")
        sp.add_argument("--space", default="home", help="whose token cards (default home)")
        if write:
            sp.add_argument("-m", "--message", required=True, help="what this change does, for the history")
            sp.add_argument("--dry-run", action="store_true", help="show the row before and after; save nothing")
            cli_actor.add_argument(sp)
            sp.add_argument("--expect", required=row, metavar="SHA",
                            help="the sha tokens list printed (at least its first 12 characters; \"none\" "
                                 "before the space has token cards): refused if the list has changed since")
        return sp

    sp = action("list", "Print a space's token cards, numbered, in the order they're kept.", write=False)
    sp.add_argument("--json", action="store_true", help="print the rows as JSON (the token cards' columns)")
    action("check", "Report the rules a space's token cards (and home's pending token orders) break.",
           write=False)
    sp = action("add", "Add a token card.")
    _card_options(sp, required=("--front", "--quantity"))
    sp.add_argument("--separate", action="store_true", help="keep it apart from a row naming the same card")
    sp = action("edit", "Change a token card (the columns given; the rest stay).", row=True)
    _card_options(sp)
    sp.add_argument("--separate", action="store_true", help="keep it apart from a row naming the same card")
    sp = action("remove", "Remove a token card.", row=True)
    sp.add_argument("--reason", required=True, help="why it's removed, for the history")


def _card_options(sp, required=()):
    for flag, column in CARD_OPTIONS:
        sp.add_argument(flag, dest=column, default=None, required=flag in required,
                        help=f"the card's {column.replace('_', ' ')}")


def _say(text):
    print(text, file=sys.stderr)


def _label(row):
    from decklab.lib import tokens
    return tokens.label(row)


def _list(space, args):
    from decklab.lib import tokens
    inv = tokens.read(space=space)
    from decklab.db import read_notices
    read_notices.Reporter(getattr(args, "dbname", None)).space("collection", space, label="tokens")
    if args.json:
        print(json.dumps({"sha256": inv.sha256, "rows": inv.rows}, ensure_ascii=False, indent=2))
        return 0
    cards = sum(int(row["quantity"]) for row in inv.rows)
    print(f"{tokens.label_for(space)}: {len(inv.rows)} row{'' if len(inv.rows) == 1 else 's'}, "
          f"{cards} card{'' if cards == 1 else 's'}.")
    print(f"sha {inv.sha256 or 'none'} (give it to edit or remove as --expect)")
    for n, row in enumerate(inv.rows, 1):
        printing = " ".join(filter(None, (row["set"], "/".join(filter(None, (row["front_collector_number"],
                                                                             row["back_collector_number"]))),
                                          row["finish"])))
        print(f"{n:>4}. {_label(row)} ×{row['quantity']}" + (f"  [{printing}]" if printing else ""))
        for key in ("front_details", "back_details", "notes"):
            if row[key]:
                print(f"        {key.replace('_', ' ')}: {row[key]}")
    for problem in inv.problems:
        print(f"  ! {problem}")
    return 0


def _check(space, args):
    from decklab.lib import tokens
    notes, warnings = [], []
    problems = tokens.check(notes=notes, space=space, warnings=warnings)
    for text in problems + warnings + notes:     # warnings (details that look mistyped) don't fail it
        print(text)
    if not problems:
        print(tokens.no_problems(space))
    return 1 if problems else 0


def _write(space, args, actor):
    from decklab.lib import inventory, tokens
    from decklab.lib.inventory import Op
    from decklab.lib.tokens import ops
    if not args.message.strip():
        _say("-m needs a message saying what this change does.")
        return 1
    reason = getattr(args, "reason", None)
    if args.action == "remove" and not reason.strip():
        _say("--reason needs a reason saying why the card is removed.")
        return 1
    try:
        inv = tokens.read(strict=True, space=space)
    except tokens.TokensError as e:
        _say(str(e))
        return 1
    expect = (args.expect or "").strip().lower()
    if args.expect is not None:
        if expect != "none" and not re.fullmatch(f"[0-9a-f]{{{MIN_EXPECT},64}}", expect):
            _say(f"--expect needs the sha tokens list printed (at least its first {MIN_EXPECT} characters), "
                 "or none.")
            return 1
        if (inv.sha256 is None) != (expect == "none") or inv.sha256 and not inv.sha256.startswith(expect):
            _say(f"{tokens.label_for(space)} has changed since that listing; list it again and retry.")
            return 1
    params = {"space": space, "sha256": inv.sha256}
    base = None
    if args.action != "add":
        if not 1 <= args.row <= len(inv.rows):
            _say(f"There's no row {args.row}: {tokens.label_for(space)} has {len(inv.rows)} "
                 "(tokens list numbers them).")
            return 1
        base = inv.rows[args.row - 1]
        params["base"] = base
    if args.action != "remove":
        fields = dict(base or {key: "" for key in tokens.FIELDS})
        fields.update({column: getattr(args, column) for _, column in CARD_OPTIONS
                       if getattr(args, column) is not None})
        try:
            row = tokens.validate_row(fields)
            row, warnings = tokens.check_names(row)
        except ValueError as e:
            _say(f"The token card can't be saved: {e}")
            return 1
        for warning in warnings:
            _say(f"Note: {warning}")
        params.update(row=row, separate=args.separate)
    try:
        op = Op(f"tokens.{args.action}", params)
        if getattr(args, "dry_run", False):
            after, summary = inventory.preview(op)
        else:
            after, summary = inventory.apply(op, actor, args.message.strip(),
                                             reason=reason.strip() if reason else None)
    except ops.SameRow as e:
        allowed = e.same_row["separate_allowed"]
        hint = (" Pass --separate to keep it as a separate card, or edit that row's quantity "
                f"(row {e.same_row['index'] + 1})." if allowed else
                f" Edit that row's quantity instead (row {e.same_row['index'] + 1}).")
        _say(str(e).replace(" Add to its quantity instead?", "") + hint)
        return 1
    except ops.Stale:
        _say(f"{tokens.label_for(space)} changed while this ran; list it again and retry.")
        return 1
    except ops.Broken as e:
        _say(f"{e} (a bug in Deck Lab: say what you ran).")
        return 1
    if getattr(args, "dry_run", False):
        print(f"Would {args.action} a token card in {tokens.label_for(space)}.")
        print("Before: " + (json.dumps(base, ensure_ascii=False, sort_keys=True) if base else "(no row)"))
        index = summary.extra.get("index")
        new = after.token_set(space).rows[index].as_dict() if index is not None else None
        print("After: " + (json.dumps(new, ensure_ascii=False, sort_keys=True) if new else "(no row)"))
    else:
        print(summary.text + ".")
    if (summary.extra or {}).get("resorted"):
        verb = "would sort" if getattr(args, "dry_run", False) else "sorted"
        print(f"{tokens.label_for(space)} wasn't in the standard order; this change {verb} it.")
    if getattr(args, "dry_run", False):
        print("Nothing saved (--dry-run).")
    return 0


def run(args):
    """Run one tokens command (python -m decklab.db tokens ...); returns the exit code. The
    caller (decklab.db's main) runs it in one pinned inventory snapshot and turns the
    inventory's refusals into exit 1 and an unreachable database into exit 2."""
    from decklab.lib import spaces
    try:
        if args.space != spaces.HOME:
            spaces.get(args.space)
    except spaces.SpaceNotFound:
        _say(f"There's no space {args.space!r} in decklab/config.json.")
        return 1
    if args.action == "list":
        return _list(args.space, args)
    if args.action == "check":
        return _check(args.space, args)
    return _write(args.space, args, cli_actor.resolve(args))
