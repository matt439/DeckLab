"""Deck Lab's visits in the database (migration 0008): ops.visit_day and ops.visit_page.

    write(days, pages)                 the server's recorder (lib/visits.py) adding what it gathered
    summary(days=30, profile=None)     each profile's visits, as the Settings page and the command show them
    lines(people, days, profiles)      that summary as the command's lines
    prune()                            delete days older than KEEP_DAYS (the nightly task's step)

The tables are operational, like ops.backup_run: no audit trigger, no change set, not in the
export or the dumps' content digests. The server writes them as decklab_app (migration 0008 grants
it insert and update there); the summary reads as the role asked for (the server's app, the
command's ro), and the prune deletes as the owner.
"""
from datetime import date, timedelta

from decklab.db import conn as db

KEEP_DAYS = 400             # days of visits kept: about a year, plus a margin
DEFAULT_DAYS = 30           # the summary's window: days visited and the pages opened most often
MAX_DAYS = 366              # the longest window (the Settings page's API and the command)
TOP_PAGES = 5               # pages listed for each profile, most recent and most often

_DAY_SQL = """
insert into ops.visit_day as v (profile_id, day, channel, first_at, last_at, requests)
values (%s, %s, %s, %s, %s, %s)
on conflict (profile_id, day, channel) do update set
    first_at = least(v.first_at, excluded.first_at),
    last_at = greatest(v.last_at, excluded.last_at),
    requests = v.requests + excluded.requests"""

# Requests alone add to a day a page was opened on, and never make one (lib/visits.py).
_REQUESTS_SQL = """
update ops.visit_day set requests = requests + %s where profile_id = %s and day = %s and channel = %s"""

_PAGE_SQL = """
insert into ops.visit_page as p (profile_id, day, channel, route, deck_id, opens, last_at)
values (%s, %s, %s, %s, %s, %s, %s)
on conflict (profile_id, day, channel, route, deck_id) do update set
    opens = p.opens + excluded.opens,
    last_at = greatest(p.last_at, excluded.last_at)"""


def write(days, pages, dbname=None, timeout=None, options=None):
    """Add what the recorder gathered, in one transaction as decklab_app:
    days {(profile, day, channel): (first_at, last_at, requests)} and
    pages {(profile, day, channel, route, deck_id): (opens, last_at)}. A day whose times are None
    holds requests alone: they're added to that day if it's there (after this write's days), and
    dropped if not. A page's day is added when it isn't there (its first and last time the
    page's, no requests). Buffered rows for missing or departed profiles are
    discarded while other profiles' rows save. Admission shares the inventory
    transaction claim with member removal. timeout, options: db.connect's."""
    if not days and not pages:
        return
    day_rows = [(*key, *value) for key, value in sorted(days.items()) if value[0] is not None]
    request_rows = [(value[2], *key) for key, value in sorted(days.items()) if value[0] is None and value[2]]
    for (profile, day, channel, _route, _deck), (_opens, at) in pages.items():
        if days.get((profile, day, channel), (None,))[0] is None:
            day_rows.append((profile, day, channel, at, at, 0))
    page_rows = [(*key, *value) for key, value in sorted(pages.items())]
    with db.connect("app", dbname=dbname, timeout=timeout, options=options) as c:
        with c.cursor() as cur:
            from decklab.db import space_members
            allowed = space_members.active_profiles(cur, {key[0] for key in days} | {key[0] for key in pages})
            day_rows = [row for row in day_rows if row[0] in allowed]
            page_rows = [row for row in page_rows if row[0] in allowed]
            request_rows = [row for row in request_rows if row[1] in allowed]
            if day_rows:
                cur.executemany(_DAY_SQL, day_rows)
            if page_rows:
                cur.executemany(_PAGE_SQL, page_rows)
            if request_rows:
                cur.executemany(_REQUESTS_SQL, request_rows)
        c.commit()


def summary(days=DEFAULT_DAYS, profile=None, dbname=None, role="ro", today=None, conn=None):
    """Each profile seen, as a list of dicts (the most recently seen first):
        {"profile", "first_seen" (date), "last_seen" (datetime), "last_channel" ("home" or
         "remote"), "days" (days visited in the window), "requests" (in the window),
         "recent" [{"route", "deck", "at"}] (the pages opened last, newest first, ever),
         "often" [{"route", "deck", "opens"}] (the pages opened most in the window)}
    days: the window, ending today (the PC's date); profile: only that profile's."""
    today = today or date.today()
    since = today - timedelta(days=max(1, int(days)) - 1)
    only = "" if profile is None else " and profile_id = %(profile)s"
    params = {"since": since, "profile": profile, "top": TOP_PAGES}

    def read(c):
        people = c.execute(
            "select profile_id, min(day), max(last_at), "
            "count(distinct day) filter (where day >= %(since)s), "
            "coalesce(sum(requests) filter (where day >= %(since)s), 0) "
            f"from ops.visit_day where true{only} group by profile_id", params).fetchall()
        last_channel = dict((r[0], r[1]) for r in c.execute(
            "select distinct on (profile_id) profile_id, channel from ops.visit_day "
            f"where true{only} order by profile_id, last_at desc", params).fetchall())
        recent = c.execute(
            "select profile_id, route, deck_id, at from (select profile_id, route, deck_id, max(last_at) as at, "
            "row_number() over (partition by profile_id order by max(last_at) desc, route, deck_id) as n "
            f"from ops.visit_page where true{only} group by profile_id, route, deck_id) t "
            "where n <= %(top)s order by profile_id, n", params).fetchall()
        often = c.execute(
            "select profile_id, route, deck_id, opens from (select profile_id, route, deck_id, sum(opens) as opens, "
            "row_number() over (partition by profile_id order by sum(opens) desc, max(last_at) desc, route, deck_id) "
            "as n "
            f"from ops.visit_page where day >= %(since)s{only} group by profile_id, route, deck_id) t "
            "where n <= %(top)s order by profile_id, n", params).fetchall()
        return people, last_channel, recent, often

    if conn is None:
        with db.connect(role, dbname=dbname, autocommit=True) as c:
            people, last_channel, recent, often = read(c)
    else:
        people, last_channel, recent, often = read(conn)
    out = []
    for profile_id, first, last, visited, requests in people:
        out.append({"profile": profile_id, "first_seen": first, "last_seen": last,
                    "last_channel": last_channel.get(profile_id), "days": visited, "requests": int(requests),
                    "recent": [{"route": r, "deck": d or None, "at": at}
                               for p, r, d, at in recent if p == profile_id],
                    "often": [{"route": r, "deck": d or None, "opens": int(n)}
                              for p, r, d, n in often if p == profile_id]})
    out.sort(key=lambda person: person["last_seen"], reverse=True)
    return out


def page_label(page, titles=None):
    """A page as the summary names it: its route, and its deck's title (titles: {deck id: title})
    or else its id when it has one ("deck Gruul Ramp", "deck casual/gruul-ramp")."""
    deck = page.get("deck")
    return page["route"] + (f" {(titles or {}).get(deck) or deck}" if deck else "")


def lines(people, days=DEFAULT_DAYS, profiles=None, titles=None):
    """The `visits` command's lines for summary()'s list, as the Settings page's Visits part shows
    it: the profiles seen (the most recently seen first), then the other profiles of profiles
    ({profile id: name}, config.json's) as not seen yet. titles: {deck id: title}."""
    profiles = profiles or {}
    out = []
    for person in people:
        name = profiles.get(person["profile"], person["profile"])
        channel = {"home": "at home", "remote": "from outside"}.get(person["last_channel"], "")
        out.append(f"{name} ({person['profile']}): first seen {person['first_seen']:%Y-%m-%d}, last seen "
                   f"{person['last_seen'].astimezone():%Y-%m-%d %H:%M} {channel}".rstrip()
                   + f"; {person['days']} of the last {days} days, {person['requests']:,} requests")
        if person["recent"]:
            out.append("  recently: " + ", ".join(page_label(p, titles) for p in person["recent"]))
        if person["often"]:
            out.append("  most opened: " + ", ".join(f"{page_label(p, titles)} ({p['opens']})"
                                                     for p in person["often"]))
    seen = {person["profile"] for person in people}
    out.extend(f"{name} ({profile_id}): not seen yet" for profile_id, name in profiles.items() if profile_id not in seen)
    return out or ["No visits recorded yet."]


def prune(keep_days=KEEP_DAYS, dbname=None, today=None):
    """Delete the days (and their pages) older than keep_days, as the owner. Returns the days deleted."""
    cutoff = (today or date.today()) - timedelta(days=keep_days)
    with db.connect("owner", dbname=dbname, autocommit=True) as c:
        return c.execute("delete from ops.visit_day where day < %s", (cutoff,)).rowcount


def run_prune(say=db.log):
    """The nightly task's step: prune(), said in db.log. 0, or 1 when it failed; 0 with a note
    while migration 0008 isn't applied (nothing to prune yet)."""
    from psycopg import errors
    try:
        deleted = prune()
    except errors.UndefinedTable:
        say("Visits: nothing to prune (migration 0008 isn't applied yet: python -m decklab.db migrate).")
        return 0
    say(f"Visits: deleted {deleted} day(s) older than {KEEP_DAYS} days.")
    return 0
