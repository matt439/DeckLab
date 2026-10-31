"""Visibility reporting and home-only flips; members use their own page controls."""
from decklab.lib.state import pg, visibility


def rows(snapshot, spaces):
    """Every configured switch, including Private ones, followed by unknown stored keys."""
    keys = {(owner, thing) for owner in spaces for thing in visibility.SPACE_THINGS}
    keys.update((owner, "accessories") for owner in visibility.kit_owners())
    keys.update(snapshot)
    return [{"owner": owner, "thing": thing, "state": "Public" if (owner, thing) in snapshot else "Private",
             **snapshot.get((owner, thing), {"by": None, "by_id": None, "since": None})}
            for owner, thing in sorted(keys)]


def listing(args):
    from decklab.lib import spaces
    from decklab.lib.state import Unavailable
    from decklab.db import conn as db
    try:
        snapshot = pg.PgStore(dbname=args.dbname).visibility()
    except Unavailable as error:
        raise db.DbUnavailable(str(error)) from None
    for row in rows(snapshot, spaces.space_ids()):
        print(f"{row['owner']}\t{row['thing']}\t{row['state']}"
              + (f"\t{row['by']}\t{row['since']}" if row["state"] == "Public" else ""))
    return 0


def change(args):
    from decklab.db import conn as db
    from decklab.lib import visibility as switches
    from decklab.lib.state import Actor, Unavailable, rules
    actor = Actor("claude", "Claude", source="cli")
    rules.check_write(actor, args.message)
    owner, thing, on = args.owner, args.thing, args.value == "on"
    visibility.switch(owner, thing, on)
    if not (owner == "home" and thing in visibility.SPACE_THINGS
            or owner in visibility.kit_owners() and thing == "accessories"):
        raise ValueError("Only the home switches can be changed from the command line. "
                         "A member changes their own switches on the page.")
    if thing not in switches.READY_THINGS:
        raise ValueError("This Public switch isn't available yet.")
    try:
        store = pg.PgStore(dbname=args.dbname)
        message = visibility.message(owner, thing, on)
        with store.batch(actor, message, reason=args.message):
            store.visibility_set(owner, thing, on, actor, message)
    except Unavailable as error:
        raise db.DbUnavailable(str(error)) from None
    print(f"{owner}\t{thing}\t{'Public' if on else 'Private'}")
    return 0


def add_parser(sub):
    parser = sub.add_parser("visibility", help="Report switches or change only the home's Public/Private switches.")
    actions = parser.add_subparsers(dest="action", required=True)
    listed = actions.add_parser("list", help="Show every switch; an absent row is Private.")
    listed.add_argument("--dbname", help="the database to use instead of the settings' one (tests)")
    listed.set_defaults(func=listing)
    changed = actions.add_parser("set", help="Change a home switch; members change their own on the page.")
    changed.add_argument("owner", help="home, or a home profile's id or shared for accessories")
    changed.add_argument("thing", choices=visibility.THINGS)
    changed.add_argument("value", choices=("on", "off"), help="on: Public; off: Private")
    changed.add_argument("-m", "--message", required=True, help="why (saved beside the fixed Public/Private audit message)")
    changed.add_argument("--dbname", help="the database to use instead of the settings' one (tests)")
    changed.set_defaults(func=change)
