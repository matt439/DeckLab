"""A space's storage setup from the command line (E8-S25; the Collection page's Storage setup sheet
is a later slice). Claude's way to read and change it:

  python -m decklab.db storage show [--space S] [--json]
  python -m decklab.db storage set FILE [--space S] --expect N -m MSG [--actor PROFILE] [--dry-run]

show prints the setup that applies now: the space's saved record, else home's built-in storage box
(source "default") or no containers (source "none"), with its revision (0 before the space saved
one). --json prints {space, revision, ready, source, storage}; edit a copy of it in the scratchpad
and give it to set, which takes either that whole answer or just its storage object ({default,
containers}). --expect is the revision show printed: the save is refused when the record changed
since. Saving no containers is how a space (home included) says it has no particular storage.

Each save is one change set by "claude" (or --actor PROFILE) with the -m message; --dry-run checks
the file and the revision and prints what it would save, saving nothing. Until the database has
migration 0028 show answers the built-in setup and set is refused, saying so. The setup follows
the space's collection for privacy: when relaying a member's upkeep, say only that it's done.

Exit codes as the other commands: 0 done (or nothing to change, or previewed), 1 refused, 2 the
database can't be reached.
"""
import json
import sys
from pathlib import Path

from decklab.db import cli_actor

MAX_FILE = 64 * 1024


def add_parser(sub):
    """Add the storage command and its subcommands to python -m decklab.db's parser."""
    p = sub.add_parser("storage", help="Show or set a space's storage setup (show, set).",
                       description="Show or set a space's storage setup: its containers, their capacities, "
                                   "sections and order, and where loose cards with no location go.")
    p.set_defaults(func=run)
    actions = p.add_subparsers(dest="action", required=True, metavar="action")
    sp = actions.add_parser("show", help="Print the storage setup that applies to a space now.")
    sp.add_argument("--space", default="home", help="whose storage setup (default home)")
    sp.add_argument("--json", action="store_true", help="print it as JSON (set takes a copy of it)")
    sp.add_argument("--dbname", help="the database to use instead of the settings' one (tests)")
    sp = actions.add_parser("set", help="Replace a space's storage setup with a JSON file's.")
    sp.add_argument("file", help="a JSON file: show --json's answer, or its storage object alone")
    sp.add_argument("--space", default="home", help="whose storage setup (default home)")
    sp.add_argument("--expect", required=True, type=int, metavar="N",
                    help="the revision show printed (0 before the space saved one): refused if it changed since")
    sp.add_argument("-m", "--message", required=True, help="what this change does, for the history")
    sp.add_argument("--dry-run", action="store_true", help="check it and print what would be saved; save nothing")
    cli_actor.add_argument(sp)
    sp.add_argument("--dbname", help="the database to use instead of the settings' one (tests)")


def _say(text):
    print(text, file=sys.stderr)


def _store(args):
    """The store to use: a PgStore with its own breaker (tests patch this)."""
    from decklab.db import conn as db
    from decklab.lib.state import pg
    return pg.PgStore(dbname=args.dbname, timeout=db.CONNECT_TIMEOUT, breaker=pg.Breaker())


def describe(view):
    """The setup as lines of text: one per container, then the default."""
    from decklab.lib.state import space_storage as rules
    record = view["storage"]
    source = {"saved": "saved", "default": "built-in default (nothing saved)",
              "none": "none saved"}[view["source"]]
    lines = [f"Storage setup of {view['space']}: {source}, revision {view['revision']}"]
    if view.get("ready") is False:
        lines.append("  (the database lacks migration 0028: nothing can be saved yet)")
    if not record["containers"]:
        lines.append("  No containers.")
    for c in record["containers"]:
        size = "capacity not known" if c["capacity"] is None else f"holds {c['capacity']:,} cards"
        parts = [f"{c['kind']}", size, f"order {c['order']}", "sleeved" if c["sleeved"] else "unsleeved"]
        lines.append(f"  [{c['id']}] {c['name']}: {', '.join(parts)}")
        if c["sections"]:
            lines.append(f"      sections: {', '.join(c['sections'])}")
    default = rules.container(record, record["default"])
    lines.append(f"  Cards with no location go to: {default['name'] if default else 'no particular container'}")
    return lines


def _load(path):
    file = Path(path)
    data = file.read_bytes()
    if len(data) > MAX_FILE:
        raise ValueError(f"{file.name} is larger than {MAX_FILE // 1024} KiB")
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"{file.name} isn't JSON: {e}") from None
    if isinstance(value, dict) and "storage" in value and "containers" not in value:
        value = value["storage"]
    return value


def run(args):
    """Run one storage command; returns the exit code."""
    from decklab.db import read_notices
    from decklab.lib import spaces, state, storage_setting
    from decklab.lib.state import space_storage as rules
    space = args.space
    if not spaces.exists(space):
        _say(f"No space {space!r} in decklab/config.json")
        return 1
    store = _store(args)
    try:
        with state.use(store):
            current = storage_setting.read(space)
            if args.action == "show":
                read_notices.Reporter(getattr(args, "dbname", None)).space("collection", space,
                                                                          label="storage setup")
                if args.json:
                    print(json.dumps(current, ensure_ascii=False, indent=2))
                else:
                    print("\n".join(describe(current)))
                return 0
            if not args.message.strip():
                _say("-m needs a message saying what this change does.")
                return 1
            actor = cli_actor.resolve(args)
            record = rules.normalize(_load(args.file))
            expect = rules.expectation(args.expect)
            if expect != current["revision"]:
                _say(f"{rules.CHANGED} (it's at revision {current['revision']}; run storage show again)")
                return 1
            if current["ready"] is False:          # the save would be refused, so the preview is too
                _say(rules.MIGRATE)
                return 1
            if current["source"] == "saved" and current["storage"] == record:
                print("Nothing to change: the storage setup is already that.")
                return 0
            if args.dry_run:
                print("Would save:")
                print("\n".join(describe({**current, "storage": record, "source": "saved",
                                          "revision": current["revision"] + 1})))
                return 0
            saved = store.space_storage_put(space, record, expect, actor, args.message.strip())
            print("\n".join(describe(storage_setting._view(space, saved))))
            return 0
    except state.Unavailable as e:
        if str(e) == rules.MIGRATE:
            _say(str(e))
            return 1
        _say(f"The database isn't available: {e}")
        return 2
    except state.StateError as e:
        _say(str(e))
        return 1
    except (OSError, ValueError) as e:
        _say(str(e))
        return 1
