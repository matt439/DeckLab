"""The accessories' commands, Claude's way to read and change the sleeves, deck boxes and playmats
(the Accessories page's rows; decklab/lib/accessories.py) and their pictures, now that Deck Lab's
inventory keeps them (the database; the phase 4 design's R7):

  python -m decklab.db accessories list [--json]
  python -m decklab.db accessories show ID
  python -m decklab.db accessories check
  python -m decklab.db accessories add --kind K --name N [row options] --expect SHA -m MSG
  python -m decklab.db accessories edit ID [row options] --expect SHA -m MSG
  python -m decklab.db accessories remove ID --expect SHA -m MSG --reason R
  python -m decklab.db image put NAME FILE -m MSG
  python -m decklab.db image remove NAME -m MSG

list prints every row (every owner's: the command line sees them all, as a local request naming
nobody does) and the list's sha (the sha256 of accessories.csv as Deck Lab writes it; "none"
before there are any), which add, edit and remove need as --expect (at least its first 12
characters): a change is refused when the list changed since that listing. show prints one row
with what holds it; check is python -m decklab.lib.accessories --check's report.

The row options are --kind, --owner (a home profile's id or shared; shared by default),
--brand, --name, --colour, --quantity, --capacity, --crop, --link, --image-source and --notes;
an edit keeps every column it isn't given, and "" clears one. A new row's id is made
from its brand, name and colour (accessories.new_id) and never changes. The writes are the
Accessories page's operations (accessory.add, accessory.edit, accessory.remove, image.put,
image.remove: lib/inventory/ops_decks.py), with their rules; each is one change by "claude" (or --actor PROFILE) from
the command line with the -m message (and a removal's --reason). A picture's NAME is the file
name a row's image column holds (<id>.jpg, .png or .webp): image put stores it and gives the
row <id> that picture, and image remove takes it away.

Exit codes as the other commands: 0 done, 1 refused or problems found, 2 the database can't be
reached.
"""
import json
import re
import sys
from pathlib import Path

from decklab.db import cli_actor

MIN_EXPECT = 12                     # characters of the list's sha --expect needs at least
# The row options: (flag, column).
ROW_OPTIONS = (("--kind", "kind"), ("--owner", "owner"), ("--brand", "brand"), ("--name", "name"),
               ("--colour", "colour"), ("--quantity", "quantity"), ("--capacity", "capacity"),
               ("--crop", "crop"), ("--link", "link"), ("--image-source", "image_source"),
               ("--notes", "notes"))


def register(sub):
    """Add the accessories and image commands to python -m decklab.db's parser."""
    p = sub.add_parser("accessories", help="List, check or change the sleeves, deck boxes and playmats.",
                       description="List, check or change the accessories. Writes need -m saying what they do "
                                   "and --expect the list's sha; a removal also --reason.")
    p.set_defaults(func=run)
    actions = p.add_subparsers(dest="action", required=True, metavar="action")
    sp = actions.add_parser("list", help="Print every accessory and the list's sha.")
    sp.add_argument("--json", action="store_true", help="print the rows as JSON (the accessories' columns)")
    sp = actions.add_parser("show", help="Print one accessory and what holds it.")
    sp.add_argument("id", help="the accessory's id")
    actions.add_parser("check", help="Report the rules the accessories break (accessories --check).")
    sp = actions.add_parser("add", help="Add an accessory.")
    _row_options(sp, required=("--kind", "--name"))
    _write_options(sp)
    sp = actions.add_parser("edit", help="Change an accessory (the columns given; the rest stay).")
    sp.add_argument("id", help="the accessory's id")
    _row_options(sp)
    _write_options(sp)
    sp = actions.add_parser("remove", help="Remove an accessory.")
    sp.add_argument("id", help="the accessory's id")
    _write_options(sp)
    sp.add_argument("--reason", required=True, help="why it's removed, for the history")

    p = sub.add_parser("image", help="Put or remove an accessory's picture.",
                       description="Put or remove an accessory's picture (stored with its row).")
    p.set_defaults(func=run_image)
    actions = p.add_subparsers(dest="action", required=True, metavar="action")
    sp = actions.add_parser("put", help="Save a picture under NAME (<id>.jpg, .png or .webp).")
    sp.add_argument("name", help="the picture's file name, as a row's image column names it")
    sp.add_argument("file", help="the picture to save")
    sp.add_argument("-m", "--message", required=True, help="what this change does, for the history")
    cli_actor.add_argument(sp)
    sp = actions.add_parser("remove", help="Remove the picture NAME.")
    sp.add_argument("name", help="the picture's file name")
    sp.add_argument("-m", "--message", required=True, help="what this change does, for the history")
    cli_actor.add_argument(sp)


def _row_options(sp, required=()):
    for flag, column in ROW_OPTIONS:
        sp.add_argument(flag, dest=column, default=None, required=flag in required,
                        help=f"the accessory's {column.replace('_', ' ')}")


def _write_options(sp):
    sp.add_argument("-m", "--message", required=True, help="what this change does, for the history")
    cli_actor.add_argument(sp)
    sp.add_argument("--expect", required=True, metavar="SHA",
                    help="the sha accessories list printed (at least its first 12 characters; \"none\" before "
                         "there are any): refused if the list has changed since")


def _say(text):
    print(text, file=sys.stderr)


def _actor(args=None):
    return cli_actor.resolve(args)


def listed():
    """accessories.Inventory of the snapshot's accessories.csv (every owner's rows; its sha256 the
    list's, None when there are none)."""
    from decklab.lib import accessories, inventory
    from decklab.lib.inventory import files
    sheet = inventory.current().accessories
    if not sheet.exists:
        return accessories.Inventory()
    if sheet.error is not None:
        return accessories.Inventory(problems=[f"The accessories can't be read ({sheet.error})"])
    return accessories.parse(files.render_sheet(sheet))


def _line(row):
    from decklab.lib import accessories
    bits = [row["kind"], f"owner {row['owner']}", f"×{row['quantity']}"]
    if row["capacity"]:
        bits.append(f"holds {row['capacity']}")
    if row["image"]:
        bits.append(f"picture {row['image']}")
    return f"{row['id']}  {accessories.label(row)}  ({', '.join(bits)})"


def _list(args):
    inv = listed()
    rows = list(inv.rows_by_id.values())
    from decklab.db import read_notices
    read_notices.Reporter(getattr(args, "dbname", None)).accessories(rows)
    if args.json:
        print(json.dumps({"sha256": inv.sha256, "rows": rows, "problems": inv.problems}, ensure_ascii=False, indent=2))
        return 0
    print(f"{len(rows)} accessor{'y' if len(rows) == 1 else 'ies'}.")
    print(f"sha {inv.sha256 or 'none'} (give it to add, edit or remove as --expect)")
    for row in rows:
        print(f"  {_line(row)}")
    for problem in inv.problems:
        print(f"  ! {problem}")
    return 0


def _show(args):
    from decklab.lib import accessories
    inv = listed()
    row = inv.rows_by_id.get(args.id)
    if row is None:
        _say(f"There's no accessory {args.id!r} (accessories list lists them).")
        return 1
    print(_line(row))
    for key in ("brand", "name", "colour", "crop", "link", "image_source", "notes"):
        if row[key]:
            print(f"  {key.replace('_', ' ')}: {row[key]}")
    try:
        users = accessories.used_by(accessories.holders(inv), row)
    except Exception as e:              # noqa: BLE001 - the holders are a note
        print(f"  (what holds it can't be worked out: {e})")
        return 0
    for user in users:
        print(f"  held by {user['title']} ({user['holder']}, needs {user['need']} sleeves)")
    if not users:
        print("  held by nothing")
    return 0


def _check(args):
    from decklab.lib import accessories
    problems = accessories.check()
    for text in problems:
        print(text)
    if not problems:
        print(accessories.NO_PROBLEMS)
    return 1 if problems else 0


def expected(inv, expect):
    """None when expect (--expect) names the list as it is (inv: listed()); otherwise why not."""
    value = (expect or "").strip().lower()
    if value != "none" and not re.fullmatch(f"[0-9a-f]{{{MIN_EXPECT},64}}", value):
        return f"--expect needs the sha accessories list printed (at least its first {MIN_EXPECT} characters), or none"
    if (inv.sha256 is None) != (value == "none") or inv.sha256 and not inv.sha256.startswith(value):
        return "the accessories have changed since that listing; list them again and retry"
    return None


def _write(args, actor):
    from decklab.lib import accessories, inventory
    from decklab.lib.inventory import Op
    inv = listed()
    if inv.problems:
        _say("The accessories have problems to fix first: " + "; ".join(inv.problems))
        return 1
    why = expected(inv, args.expect)
    if why:
        _say(f"Not saved: {why}.")
        return 1
    params = {"sha256": inv.sha256, "owners": None}
    if args.action == "remove":
        if args.id not in inv.rows_by_id:
            _say(f"There's no accessory {args.id!r}.")
            return 1
        if not args.reason.strip():
            _say("--reason needs a reason saying why the accessory is removed.")
            return 1
        op = Op("accessory.remove", {**params, "id": args.id})
    else:
        given = {column: getattr(args, column) for _, column in ROW_OPTIONS if getattr(args, column) is not None}
        if args.action == "edit":
            base = inv.rows_by_id.get(args.id)
            if base is None:
                _say(f"There's no accessory {args.id!r}.")
                return 1
            row = dict(base)
        else:
            given = {"owner": accessories.SHARED, "quantity": "1", **given}
            row = {key: "" for key in accessories.FIELDS}
        row.update(given)
        if args.action == "add":
            row["id"] = accessories.new_id(row, inv.rows_by_id)
        try:        # the whole row checked here, to refuse before the operation runs
            row = accessories.validate_row(row)
        except ValueError as e:
            _say(f"The accessory can't be saved: {e}.")
            return 1
        # The operation takes only the columns given (an edit merges them over the stored row);
        # it makes a new row's id itself, and a picture comes only through image put.
        sent = {k: row[k] for k in given if k in accessories.ROW_KEYS}
        op = Op("accessory.add", {**params, "row": sent}) if args.action == "add" else \
            Op("accessory.edit", {**params, "id": args.id, "row": sent})
    reason = getattr(args, "reason", None)
    _, summary = inventory.apply(op, actor, args.message.strip(), reason=reason.strip() if reason else None)
    print(f"{summary.text}." if summary.text else "Saved.")
    if args.action == "add" and summary.extra.get("id"):
        print(f"id: {summary.extra['id']}")       # image put names its picture <id>.<ext>
    return 0


def run(args):
    """Run one accessories command; returns the exit code (see the module docstring)."""
    from decklab.lib.inventory import ops_decks  # noqa: F401  (registers accessory.*, image.*, kit.set, deck.*)
    if args.action == "list":
        return _list(args)
    if args.action == "show":
        return _show(args)
    if args.action == "check":
        return _check(args)
    if not args.message.strip():
        _say("-m needs a message saying what this change does.")
        return 1
    return _write(args, _actor(args))


def run_image(args):
    """Run one image command; returns the exit code (see the module docstring)."""
    from decklab.lib import accessories, inventory
    from decklab.lib.inventory import Op, ops_decks  # noqa: F401  (ops_decks registers image.*)
    if not args.message.strip():
        _say("-m needs a message saying what this change does.")
        return 1
    if not accessories.IMAGE_RE.match(args.name):
        _say(f"{args.name!r} isn't a picture's name: <id>.jpg, .png or .webp, the id an accessory's.")
        return 1
    if args.action == "remove":
        if args.name not in inventory.current().accessory_images:
            _say(f"There's no picture {args.name}.")
            return 1
        op = Op("image.remove", {"name": args.name})
    else:
        try:
            content = Path(args.file).read_bytes()
        except OSError as e:
            _say(f"{args.file} can't be read ({e.strerror or e}).")
            return 1
        # The page's own limits: /accessory-img/ serves a picture only when its bytes are its extension's.
        from decklab.lib import accessory_fetch
        if not content or len(content) > accessory_fetch.MAX_IMAGE:
            _say(f"{args.file} must be a picture of 1 byte to {accessory_fetch.MAX_IMAGE // (1024 * 1024)} MiB, "
                 "as the page takes.")
            return 1
        ext = args.name.rsplit(".", 1)[1]
        found = accessory_fetch.sniff(content)
        if found != ext:
            _say(f"{args.file} isn't a .{ext} picture ({f'its bytes are a .{found}' if found else 'not a JPEG, PNG or WebP'}"
                 f"): Deck Lab wouldn't show it as {args.name}.")
            return 1
        op = Op("image.put", {"name": args.name, "content": content})
    _, summary = inventory.apply(op, _actor(args), args.message.strip())
    print(f"{summary.text}." if summary.text else "Saved.")
    return 0
