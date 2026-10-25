"""Visits (lib/visits.py): the page's beacon, and an admin's view of who uses Deck Lab.

    POST /api/visit     {"route", "deck"?, "profile"?}: the page opened, from the page's router
                        (app.js noteVisit), for the profile making the request only
    GET  /api/visits    ?days=N (1-366, 30 by default) &who=<profile id>: each profile's visits,
                        for an admin (the Settings page's Visits part)

The beacon isn't a data write: no change set, no audit row and no permission rule (guard.py), so
a member's and a person's visits are recorded like an admin's. It still needs the page's write
headers (server.py's check_write), so another site can't send it. Whose visit it is comes from
the request alone: through the tunnel the Cloudflare Access login (access.current()), on the home
network the profile the page's chooser names (access.viewer()). A "profile" in the body (apiWrite
adds one) must be that same profile (403 otherwise; through the tunnel server.py has already made
it the login's), so nobody can record a visit for someone else; a request naming nobody records
nothing. Only the route's path and, on a deck's pages, the deck's id are kept (visits.ROUTES,
DECK_ROUTES), and the id only for a deck that exists (deck_exists(), the library's ids read at most
every DECKS_SECONDS), so made-up ids can't fill the tables (and the recorder keeps at most
visits.MAX_PAGES_PER_DAY pages per profile and day).

GET /api/visits answers an admin by role (the viewer: guard.viewer()), or a script naming
nobody (as for the Activity page); anyone else gets 403. Every profile in config.json is listed,
those never seen too, so an admin sees who hasn't come at all:

    {"days": 30, "people": [{"profile", "name", "space", "seen": bool, "first_seen" (YYYY-MM-DD),
      "last_seen" (ISO), "last_channel" ("home" | "remote"), "days" (visited in the window),
      "requests", "recent": [{"route", "deck", "title", "at"}], "often": [{"route", "deck",
      "title", "opens"}]}]}

A page's deck is only one the viewer may see (guard.sees_deck: its own space's, E10-S30): for any
other, "deck" is None and "title" says whose it was ("one of User2's decks", guard.hidden_deck),
and the beacon keeps no id of a deck its requester may not see.

What the server holds but hasn't written yet is written first, so the answer is up to date: that
write waits at most FLUSH_WAIT seconds for one under way and is skipped while writes are failing.
503 when the database can't be read (or migration 0008 isn't applied).
"""
import threading
import time

from decklab.lib import access, visits

from . import common
from .common import MAX_BODY, ApiError, DATABASE_DOWN, _keys, _parse_body, _public

MAX_DAYS = 366              # as decklab.db.visits.MAX_DAYS (the command's limit)
NEEDS_MIGRATION = "Visits aren't in Deck Lab's database yet: on the PC, run python -m decklab.db migrate."
ADMINS_ONLY = "Visits are for admins: they say who has used Deck Lab and what they opened."
DECKS_SECONDS = 60          # how long the decks' ids are kept before they're read again
DECKS_MISS_SECONDS = 10     # an id not among them reads them again, at most this often (a deck just made)
FLUSH_WAIT = 1              # seconds GET /api/visits waits for a write under way

_decks_lock = threading.Lock()
_deck_ids = (frozenset(), None)     # (ids, time.monotonic() when read)


def requester():
    """(profile id, channel) of the request being answered: the tunnel login's ("remote"), the home
    page's chosen profile ("home"), or (None, None) when it names nobody."""
    identity = access.current()
    if identity is not None:
        return identity.get("profile"), "remote"
    viewer = access.viewer()
    return (viewer, "home") if viewer else (None, None)


def _read_deck_ids():
    from decklab.lib import decks
    return frozenset(s["id"] for s in decks.list_decks())


def deck_exists(deck_id):
    """True when deck_id is a deck in the library (list_decks(): every space's, products' and
    pairings'), from ids read at most every DECKS_SECONDS, or DECKS_MISS_SECONDS for one not among
    them. False when they can't be read."""
    global _deck_ids
    with _decks_lock:
        ids, when = _deck_ids
        now = time.monotonic()
        if when is not None and now - when < (DECKS_SECONDS if deck_id in ids else DECKS_MISS_SECONDS):
            return deck_id in ids
        try:
            ids = _read_deck_ids()
        except Exception:
            ids = frozenset()
        _deck_ids = (ids, now)
        return deck_id in ids


def beacon(body):
    """POST /api/visit {"route", "deck"?}: note the page opened for the requester (requester()).
    {"recorded": bool}: False for a request naming nobody, a profile config.json doesn't list, a
    route the page doesn't have, or while the server records nothing (the tests)."""
    data = _parse_body(body, MAX_BODY)
    _keys(data, ("route",), ("deck", "profile"))
    route, deck = data["route"], data.get("deck")
    if not isinstance(route, str) or not (deck is None or isinstance(deck, str)):
        raise ApiError(400, "route and deck must be text")
    profile_id, channel = requester()
    if "profile" in data and data["profile"] is not None and data["profile"] != profile_id:
        raise ApiError(403, "A visit can only be noted for yourself")
    if profile_id is None:
        return {"recorded": False}
    if deck is not None and not (route in visits.DECK_ROUTES and visits.valid_deck_id(deck) and deck_exists(deck)
                                 and _requester_sees(deck)):
        deck = None                 # the page is still noted, without the id
    return {"recorded": visits.recorder().page(profile_id, channel, route, deck)}


def _requester_sees(deck_id):
    """True when the requester may see the deck (guard.sees_deck): a hidden deck's
    address is noted without its id, as a made-up one is."""
    from . import guard
    try:
        return guard.sees_deck(deck_id, guard.viewer())
    except ApiError:
        return False


def _require_admin():
    """The viewer (guard.viewer()) when it's an admin by role, or None for a script naming
    nobody; ApiError 403 for anyone else."""
    from . import guard
    profile = guard.viewer()
    if profile is None and guard.script():
        return None
    if profile is not None and profile.get("role") == "admin":
        return profile
    raise ApiError(403, ADMINS_ONLY)


def _read(days, who):
    """decklab.db.visits.summary as decklab_app, with the server's request timeouts."""
    from decklab.db import conn as db
    from decklab.db import visits as db_visits
    from decklab.lib.state import pg
    with db.connect("app", autocommit=True, timeout=pg.REQUEST_TIMEOUT, options=pg.REQUEST_OPTIONS) as c:
        return db_visits.summary(days, who, conn=c)


def _titles():
    """{deck id: title} of every deck, for the pages' names; {} when they can't be read."""
    try:
        from decklab.lib import decks
        return {s["id"]: s.get("title") or s["id"] for s in decks.list_decks()}
    except Exception:
        return {}


def _days(value):
    if value is None or value == "":
        return 30
    if not (value.isascii() and value.isdigit()) or not 1 <= int(value) <= MAX_DAYS:
        raise ApiError(400, f"days must be a whole number from 1 to {MAX_DAYS}")
    return int(value)


def visits_view(days=None, who=None):
    """GET /api/visits (the module docstring)."""
    from . import guard
    from .settings import _config_profiles
    _require_admin()
    window = _days(days)
    profiles = _config_profiles()
    if who is not None and not any(p["id"] == who for p in profiles):
        raise ApiError(404, f"No profile {who!r}")
    visits.recorder().flush(wait=FLUSH_WAIT)
    try:
        seen = _read(window, who)
    except Exception as e:
        missing = getattr(e, "sqlstate", None) == "42P01"
        if not missing:
            common._log(f"Visits couldn't be read: {_public(e)}")
        raise ApiError(503, NEEDS_MIGRATION if missing else DATABASE_DOWN, reason="database") from None
    titles = _titles()
    viewer = guard.viewer()
    shown = {}

    def deck_of(deck_id):
        # (id, title) as the viewer may see them: a deck of a space it can't see (E10-S30) is
        # "one of User2's decks", with no id; a deleted deck of its own space keeps its id.
        if deck_id not in shown:
            shown[deck_id] = ((deck_id, titles.get(deck_id)) if guard.sees_deck(deck_id, viewer)
                              else (None, guard.hidden_deck(deck_id)))
        return shown[deck_id]

    def page(p, extra):
        deck, title = deck_of(p["deck"]) if p["deck"] else (None, None)
        return {"route": p["route"], "deck": deck, "title": title,
                extra: p[extra] if extra == "opens" else p[extra].astimezone().isoformat(timespec="seconds")}

    def merged(rows, extra):
        # A space's hidden decks are one row per route (E10-S30): opens summed, the newest time
        # kept, so the panel never tells how many of its private decks were opened.
        out, index = [], {}
        for row in rows:
            key = (row["route"], row["title"]) if row["deck"] is None and row["title"] else None
            if key is None or key not in index:
                if key is not None:
                    index[key] = row
                out.append(row)
            elif extra == "opens":
                index[key]["opens"] += row["opens"]
            elif row["at"] > index[key]["at"]:
                index[key]["at"] = row["at"]
        if extra == "opens":
            out.sort(key=lambda row: -row["opens"])
        return out

    by_id = {person["profile"]: person for person in seen}
    people = []
    for profile in profiles:
        if who is not None and profile["id"] != who:
            continue
        person = by_id.get(profile["id"])
        entry = {"profile": profile["id"], "name": profile["name"], "space": profile["space"], "seen": person is not None,
                 "first_seen": None, "last_seen": None, "last_channel": None, "days": 0, "requests": 0,
                 "recent": [], "often": []}
        if person is not None:
            entry.update(first_seen=person["first_seen"].isoformat(),
                         last_seen=person["last_seen"].astimezone().isoformat(timespec="seconds"),
                         last_channel=person["last_channel"], days=person["days"], requests=person["requests"],
                         recent=merged([page(p, "at") for p in person["recent"]], "at"),
                         often=merged([page(p, "opens") for p in person["often"]], "opens"))
        people.append(entry)
    seen_first = [e for e in people if e["seen"]]
    seen_first.sort(key=lambda e: e["last_seen"], reverse=True)
    return {"days": window, "people": seen_first + [e for e in people if not e["seen"]]}
