"""The wishlist commands, Claude's way to read and change a wishlist now that they're in the
database (decklab/PLAN.md, phase 2):

  python -m decklab.db wishlist list <profile> [--json]
  python -m decklab.db wishlist add <profile> <name> [--set S --number N] [--notes T]
                                    [--source PATH] -m MSG
  python -m decklab.db wishlist set <profile> <name> [--notes T] [--source PATH]
                                    [--set S --number N | --no-printing] -m MSG
  python -m decklab.db wishlist remove <profile> <name> -m MSG --reason R

Each write is one change set in the audit trail, by "claude" (or --actor PROFILE) from the command line, with the
-m message (and a removal's --reason): everyone who can see the wishlist on the Activity page
sees them, so they say what changed and why, not private planning.

A new card's name is checked like the page's (api/wishlists.validated_entry): resolved to its
exact Scryfall name through the card index, with a printing that belongs to it. --no-check
skips only that card lookup (when the index isn't built); the forms are still checked. set and
remove find the card on the list by name, ignoring case, as the page does. A profile that isn't
in decklab/config.json is refused unless --allow-orphan is given (its list is kept, but
nobody can see it on the page).

list --json prints the list in the old magic/wishlists/<profile>.json format.

Exit codes as the other commands: 0 done (also an add of a card already on the list, which
changes nothing), 1 refused or nothing to do, 2 the database can't be reached.
"""
import json
import sys

from decklab.db import cli_actor


def add_parser(sub):
    """Add the wishlist command and its own subcommands to python -m decklab.db's parser."""
    p = sub.add_parser("wishlist", help="List or change a profile's wishlist (list, add, set, remove).",
                       description="List or change a profile's wishlist. Writes need -m saying what "
                                   "they do; a removal also --reason. Never quote wishlist notes in audit "
                                   "messages or removal reasons.")
    p.set_defaults(func=run)
    actions = p.add_subparsers(dest="action", required=True, metavar="action")

    def action(name, help_text, write=True):
        sp = actions.add_parser(name, help=help_text, description=help_text)
        sp.add_argument("profile", help="the profile id, as in decklab/config.json")
        if name != "list":
            sp.add_argument("name", help="the card's name")
        if write:
            sp.add_argument("-m", "--message", required=True,
                            help="what this change does, for the audit trail; never quote wishlist notes")
            cli_actor.add_argument(sp)
        sp.add_argument("--allow-orphan", action="store_true",
                        help="allow a profile that isn't in decklab/config.json")
        sp.add_argument("--dbname", help="the database to use instead of the settings' one (tests)")
        return sp

    sp = action("list", "Print a profile's wishlist, in list order.", write=False)
    sp.add_argument("--json", action="store_true", help="print it as the old wishlist file's JSON")
    sp = action("add", "Add a card to the end of a profile's wishlist.")
    _printing_args(sp)
    sp.add_argument("--notes", default="", help="notes shown under the card")
    sp.add_argument("--source", default="", help="the repo file that suggested it (a buylist or deck)")
    sp.add_argument("--no-check", action="store_true", help="don't look the card up in the card index")
    sp = action("set", "Change a card's notes, source or printing.")
    _printing_args(sp)
    sp.add_argument("--no-printing", action="store_true", help="forget the chosen printing")
    sp.add_argument("--notes", help="new notes (\"\" clears them)")
    sp.add_argument("--source", help="new source (\"\" clears it)")
    sp.add_argument("--no-check", action="store_true", help="don't check a new printing against the card index")
    sp = action("remove", "Remove a card from a profile's wishlist.")
    sp.add_argument("--reason", required=True,
                    help="why it's removed, for the audit trail; never quote wishlist notes")


def _printing_args(sp):
    sp.add_argument("--set", dest="set_code", default="", metavar="SET", help="the printing's set code (with --number)")
    sp.add_argument("--number", default="", help="the printing's collector number (with --set)")


def _say(text):
    print(text, file=sys.stderr)


def _profile(args):
    """(profile id, display name) for args.profile, or None after saying why it's refused."""
    from decklab.lib import config, profiles
    from decklab.lib.state import rules
    if not rules.PROFILE_ID.fullmatch(args.profile):
        _say(f"{args.profile!r} isn't a profile id (letters, digits, - and _).")
        return None
    try:
        listed = profiles.find(args.profile, profiles.read(config.load()))
    except (OSError, ValueError) as e:
        _say(f"decklab/config.json can't be read: {e}")
        return None
    if listed is not None:
        return listed["id"], listed["name"]
    if args.allow_orphan:
        return args.profile, args.profile
    _say(f"{args.profile} isn't a profile in decklab/config.json (pass --allow-orphan to use its list anyway).")
    return None


def _shown(entry):
    printing = f" ({entry['set']} {entry['number']})" if entry["set"] else ""
    return f"{entry['name']}{printing}"


def _list(store, pid, name, args):
    entries = store.wishlist(pid)
    from decklab.db import read_notices
    read_notices.wishlist(pid)
    if args.json:
        print(json.dumps({"version": 1, "entries": entries}, ensure_ascii=False, indent=2))
        return 0
    print(f"{name}'s wishlist: {len(entries)} card{'' if len(entries) == 1 else 's'}.")
    for entry in entries:
        print(f"  {_shown(entry)}")
        if entry["notes"]:
            print(f"      notes: {entry['notes']}")
        if entry["source"]:
            print(f"      source: {entry['source']}")
    return 0


def _add(store, pid, name, args, actor):
    from decklab.lib.api import wishlists
    from decklab.lib.state import rules
    entry = wishlists.validated_entry(args.name, args.set_code, args.number, args.notes, args.source,
                                      check_cards=not args.no_check)
    changed, entries = store.wishlist_add(pid, entry, actor, args.message, allow_orphan=args.allow_orphan)
    if not changed:
        listed = entries[rules.find(entries, entry["name"])]
        # An add never changes a listed card, so say when the flags given would have.
        given = [key for key in ("notes", "source", "set", "number") if entry[key] and entry[key] != listed[key]]
        hint = " Use wishlist set to change its notes, source or printing." if given else ""
        print(f"{entry['name']} is already on {name}'s wishlist; nothing changed.{hint}")
    else:
        print(f"Added {_shown(entry)} to {name}'s wishlist ({len(entries)} cards).")
    return 0


def _set(store, pid, name, args, actor):
    from decklab.lib.api import wishlists
    from decklab.lib.state import rules
    if args.no_printing and (args.set_code or args.number):
        _say("Give --set and --number, or --no-printing, not both.")
        return 1
    printing = ("", "") if args.no_printing else (args.set_code, args.number) if args.set_code or args.number else None
    if printing is None and args.notes is None and args.source is None:
        _say("Nothing to change: give --notes, --source, --set and --number, or --no-printing.")
        return 1
    saved = store.wishlist(pid)
    i = rules.find(saved, args.name)
    if i is None:
        _say(f"{args.name} isn't on {name}'s wishlist.")
        return 1
    old = saved[i]
    new_set, new_number = printing if printing is not None else (old["set"], old["number"])
    # The whole entry as it would be, checked as a new one (the card only for a new printing).
    wishlists.validated_entry(old["name"], new_set, new_number,
                              old["notes"] if args.notes is None else args.notes,
                              old["source"] if args.source is None else args.source,
                              check_cards=bool(printing and printing[0]) and not args.no_check)
    changed, entries = store.wishlist_set(
        pid, old["name"], actor, args.message, notes=args.notes, source=args.source,
        set=None if printing is None else printing[0], number=None if printing is None else printing[1],
        allow_orphan=args.allow_orphan)
    if not changed:
        print(f"{old['name']} on {name}'s wishlist already has those; nothing changed.")
    else:
        print(f"Changed {_shown(entries[rules.find(entries, old['name'])])} on {name}'s wishlist.")
    return 0


def _remove(store, pid, name, args, actor):
    from decklab.lib.state import rules
    shown = store.wishlist(pid)
    i = rules.find(shown, args.name)
    changed, entries = store.wishlist_remove(pid, args.name, actor, args.message, args.reason,
                                             allow_orphan=args.allow_orphan)
    if not changed:
        _say(f"{args.name} isn't on {name}'s wishlist; nothing changed.")
        return 1
    print(f"Removed {shown[i]['name'] if i is not None else args.name} from {name}'s wishlist "
          f"({len(entries)} cards left).")
    return 0


def run(args):
    """Run one wishlist command (python -m decklab.db wishlist ...); returns the exit code."""
    from decklab.lib import state
    from decklab.lib.api.common import ApiError
    from decklab.lib.state import pg
    from decklab.db import conn as db
    # Checked here, before the card index or the database, so a blank one is refused plainly
    # (the store would drop a blank reason, leaving a removal with none).
    if args.action != "list" and not args.message.strip():
        _say("-m needs a message saying what this change does.")
        return 1
    if args.action == "remove" and not args.reason.strip():
        _say("--reason needs a reason saying why the card is removed.")
        return 1
    found = _profile(args)
    if found is None:
        return 1
    pid, name = found
    # Its own breaker: one failed call shouldn't make this process's others fail fast.
    store = pg.PgStore(dbname=args.dbname, timeout=db.CONNECT_TIMEOUT, breaker=pg.Breaker())
    actor = cli_actor.resolve(args)
    work = {"list": _list, "add": _add, "set": _set, "remove": _remove}[args.action]
    try:
        return work(store, pid, name, args) if args.action == "list" else work(store, pid, name, args, actor)
    except state.Unavailable as e:
        _say(f"The database isn't available: {e}")
        return 2
    except state.StateError as e:
        _say(str(e))
        return 1
    except ApiError as e:
        hint = " Or pass --no-check to skip the card lookup." if e.status == 503 else ""
        _say(e.message + hint)
        return 1
