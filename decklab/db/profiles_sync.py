"""Copies config.json's profiles into the database: `python -m decklab.db sync-profiles`.

config.json stays the place profiles are edited (PLAN.md, "Moving storage to a database",
decision 6); the database's space, profile and profile_email tables follow it. The spaces are
"home" plus each person's own space. Profiles keep config.json's order (position), their
emails are replaced as listed, and profiles no longer listed are removed, with the spaces
nobody uses any more.

Everything happens in one change set (actor system, source sync). When the database already
matches, nothing is written, so a sync at every start-up doesn't fill the audit trail.

Config-backed sync rejects any invalid profile entry before connecting, rather than syncing
a partial list that could remove a skipped profile. Explicit parsed inputs retain their checks.
Two further refusals guard the trail: a profile with one of profiles.RESERVED_IDS (claude, system,
test, home) is refused, since those name the trail's other actors; and an empty list never
removes every profile (a config.json that lost its "profiles" is far likelier than a house
with nobody in it): nothing is written, and db.log says so.
"""
from decklab.db import conn as db, space_members
from decklab.lib import profiles as profiles_lib

MESSAGE = "Sync profiles from config.json"


class _NothingToDo(Exception):
    pass


def wanted(listed):
    """What the tables should hold for the parsed profiles: (spaces, profiles), where profiles
    maps id -> (name, role, space, plays_as, position, sorted emails)."""
    spaces = {profiles_lib.HOME}
    rows = {}
    for position, p in enumerate(listed):
        spaces.add(p["space"])
        rows[p["id"]] = (p["name"], p["role"], p["space"], p["plays_as"], position,
                         tuple(sorted(set(p["emails"]))))
    return spaces, rows


def current(cur):
    """What the tables hold now, in wanted()'s shape."""
    cur.execute("select id from space")
    spaces = {r[0] for r in cur.fetchall()}
    cur.execute("select profile_id, email from profile_email")
    emails = {}
    for pid, email in cur.fetchall():
        emails.setdefault(pid, []).append(email)
    cur.execute("select id, name, role, space_id, plays_as, position from profile")
    rows = {r[0]: (r[1], r[2], r[3], r[4], r[5], tuple(sorted(emails.get(r[0], []))))
            for r in cur.fetchall()}
    return spaces, rows


def plan(want, have):
    """The differences, as a dict: add_spaces, add, change, remove (profile ids), drop_spaces."""
    want_spaces, want_rows = want
    have_spaces, have_rows = have
    return {
        "add_spaces": sorted(want_spaces - have_spaces),
        "add": [pid for pid in want_rows if pid not in have_rows],
        "change": [pid for pid in want_rows if pid in have_rows and want_rows[pid] != have_rows[pid]],
        "remove": sorted(pid for pid in have_rows if pid not in want_rows),
        "drop_spaces": sorted(have_spaces - want_spaces),
    }


def sync(listed=None, dbname=None, timeout=None, options=None):
    """Bring the tables in line with listed (default: profiles.read_checked(), config.json's
    profiles). timeout and options are conn.connect()'s (the server passes the state store's
    short connect timeout and lock/statement timeouts, so a lock held elsewhere fails the sync
    rather than holding up the thread it runs on). Returns {"added": [...], "changed": [...], "removed": [...]} (profile ids)."""
    if listed is None:
        from decklab.lib import profile_config
        from decklab.db import profile_edits
        with profile_config.claim(allow_pending=True):
            profile_edits._recover_locked(dbname=dbname)
            return _sync(profiles_lib.read_checked(), dbname=dbname, timeout=timeout, options=options)
    return _sync(listed, dbname=dbname, timeout=timeout, options=options)


def _sync(listed, dbname=None, timeout=None, options=None):
    """The caller holds the raw-config claim when inputs came from that file."""
    from decklab.lib import profile_config
    reserved = sorted(p["id"] for p in listed if p["id"] in profiles_lib.RESERVED_IDS)
    if reserved:
        raise ValueError(f"profile id {reserved[0]} is kept for the audit trail's own actors "
                         f"({', '.join(sorted(profiles_lib.RESERVED_IDS))}): rename it in config.json")
    if not listed:
        db.log("Profiles not synced: config.json lists none, and a sync would remove every profile.")
        return {"added": [], "changed": [], "removed": []}
    # Explicit programmatic inputs keep their no-config-read contract, but may
    # not write through an unresolved config publication from another process.
    profile_config.require_ready()
    want = wanted(listed)
    with db.connect("app", dbname=dbname, timeout=timeout, options=options) as c:
        with c.cursor() as cur:
            space_members.shared(cur)
            profile_config.require_ready()
            if space_members.departed(cur, want[0] | set(want[1])):
                raise ValueError("A departed member is still configured: remove that profile from config.json before syncing")
            todo = plan(want, current(cur))
        c.rollback()
        if not any(todo.values()):
            return {"added": [], "changed": [], "removed": []}
        try:
            with db.change("system", "sync", MESSAGE, conn=c) as (cur, _):
                # Checked again inside the change's transaction, in case another sync got there
                # first; if it did, the change set is rolled back rather than left empty.
                space_members.shared(cur)
                cur.execute("lock table profile, profile_email, space in share row exclusive mode")
                profile_config.require_ready()
                if space_members.departed(cur, want[0] | set(want[1])):
                    raise ValueError("A departed member is still configured: remove that profile from config.json before syncing")
                todo = plan(want, current(cur))
                if not any(todo.values()):
                    raise _NothingToDo
                _write(cur, want[1], todo)
        except _NothingToDo:
            return {"added": [], "changed": [], "removed": []}
    return {"added": todo["add"], "changed": todo["change"], "removed": todo["remove"]}


def _write(cur, rows, todo):
    for space in todo["add_spaces"]:
        cur.execute("insert into space (id) values (%s)", (space,))
    for pid in todo["add"]:
        name, role, space, plays_as, position, emails = rows[pid]
        cur.execute("insert into profile (id, name, role, space_id, plays_as, position) "
                    "values (%s, %s, %s, %s, %s, %s)", (pid, name, role, space, plays_as, position))
        _emails(cur, pid, emails, ())
    for pid in todo["change"]:
        name, role, space, plays_as, position, emails = rows[pid]
        cur.execute("select name, role, space_id, plays_as, position from profile where id = %s", (pid,))
        if cur.fetchone() != (name, role, space, plays_as, position):
            cur.execute("update profile set name = %s, role = %s, space_id = %s, plays_as = %s, "
                        "position = %s where id = %s", (name, role, space, plays_as, position, pid))
        cur.execute("select email from profile_email where profile_id = %s", (pid,))
        _emails(cur, pid, emails, {r[0] for r in cur.fetchall()})
    for pid in todo["remove"]:
        cur.execute("delete from profile where id = %s", (pid,))
    # A kit switch belongs to a home profile (E11-S48: any id, not only matt and user1): one whose
    # profile went, or left home, goes too, so a later profile reusing the id starts Private.
    if cur.execute("select to_regclass('public.visibility') is not null").fetchone()[0]:
        cur.execute("delete from visibility where thing = 'accessories' and owner <> 'shared' and owner not in "
                    "(select id from profile where space_id = 'home')")
    for space in todo["drop_spaces"]:
        # Visibility is opt-in without foreign keys. A reused space id must never
        # inherit its predecessor's Public switches; delete inside this same change.
        if cur.execute("select to_regclass('public.visibility') is not null").fetchone()[0]:
            cur.execute("delete from visibility where owner = %s and thing <> 'accessories'", (space,))
        cur.execute("delete from space where id = %s", (space,))


def _emails(cur, pid, wanted_emails, have):
    for email in sorted(set(have) - set(wanted_emails)):
        cur.execute("delete from profile_email where profile_id = %s and email = %s", (pid, email))
    for email in sorted(set(wanted_emails) - set(have)):
        cur.execute("insert into profile_email (profile_id, email) values (%s, %s)", (pid, email))


def describe(summary):
    """A summary in words: "added matt, user1; changed none; removed none", or "unchanged"."""
    if not any(summary.values()):
        return "unchanged"
    return "; ".join(f"{k} {', '.join(v) if v else 'none'}" for k, v in summary.items())
