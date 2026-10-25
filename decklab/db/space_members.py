"""Transactional membership admission shared by all normal database writers.

The shared inventory advisory claim precedes a writer's per-key locks and reads.
Removal takes its exclusive counterpart before re-reading, so an admitted save
finishes before removal, while a queued save checks the committed departure.
No cache or configuration fallback may make a departed member active again.
"""
from decklab.lib import profiles


REFUSED = "That member is no longer active in Deck Lab; nothing was saved"


def shared(cur):
    cur.execute("select pg_advisory_xact_lock_shared(hashtext(%s))", ("inventory",))


def installed(cur):
    """Before 0013 no guarded removal can run, so no durable departures exist."""
    return cur.execute("select to_regclass('public.space_departure') is not null").fetchone()[0]


def departed(cur, space_ids):
    ids = sorted(set(space_ids) - {"home"})
    if not ids or not installed(cur):
        return set()
    return {row[0] for row in cur.execute(
        "select space_id from space_departure where space_id = any(%s)", (ids,)).fetchall()}


def active_profiles(cur, profile_ids, *, lock=True):
    """Present profiles in non-departed spaces, for best-effort visit batches."""
    if lock:
        shared(cur)
    ids = sorted(set(profile_ids))
    if not ids:
        return set()
    marker = ("and not exists (select 1 from space_departure d "
              "where d.space_id = p.space_id or d.space_id = p.id) ") if installed(cur) else ""
    rows = cur.execute("select p.id from profile p join space s on s.id = p.space_id "
                       f"where p.id = any(%s) {marker}for key share of p, s", (ids,)).fetchall()
    return {row[0] for row in rows}


def admit(cur, *, profile_ids=(), space_ids=(), actor=None, lock=True, orphan_profile_ids=()):
    """Require concrete target/actor membership while holding the shared claim.

    Inventory callers already hold the stronger exclusive claim and pass
    lock=False. Reserved audit actors are not profiles and are never looked up.
    Explicit CLI wishlist targets may be orphaned; their actors and departed
    identities remain subject to the same checks as every other save.
    """
    from decklab.lib.state import Invalid
    if lock:
        shared(cur)
    pids = set(profile_ids)
    orphans = set(orphan_profile_ids)
    if not orphans <= pids:
        raise Invalid(REFUSED)
    actor_id = None
    if actor is not None and actor.id not in profiles.RESERVED_IDS:
        actor_id = actor.id
        pids.add(actor.id)
    sids = set(space_ids)
    if pids:
        rows = cur.execute("select id, space_id from profile where id = any(%s) for key share",
                           (sorted(pids),)).fetchall()
        missing = pids - {row[0] for row in rows}
        if missing - orphans or actor_id in missing:
            raise Invalid(REFUSED)
        sids.update(row[1] for row in rows)
    if departed(cur, pids | sids):
        raise Invalid(REFUSED)
    if sids:
        found = {row[0] for row in cur.execute("select id from space where id = any(%s) for key share",
                                              (sorted(sids),)).fetchall()}
        if found != sids:
            raise Invalid(REFUSED)
        members = sids - {"home"}
        if members:
            present = {row[0] for row in cur.execute(
                "select id from profile where id = space_id and id = any(%s) for key share",
                (sorted(members),)).fetchall()}
            if present != members:
                raise Invalid(REFUSED)
