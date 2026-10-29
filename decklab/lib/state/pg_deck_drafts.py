"""Editor drafts kept for later on PostgreSQL (migration 0018's deck_draft; deck_drafts.py has
the rules). Not audited: a put is its own short transaction, never a change set, holding the
draft's advisory lock while it checks the revision and writes.

The table is looked for before every read and write (to_regclass), so a database not yet
migrated raises deck_drafts.MissingSchema without tripping the shared breaker (an undefined
table's error would), and the rest of Deck Lab carries on as before.
"""
from datetime import timezone

from . import Conflict, Invalid, deck_drafts

_COLUMNS = "revision, saved_at, device, content"


def _ready(cur):
    cur.execute("select to_regclass('public.deck_draft') is not null")
    if cur.fetchone() != (True,):
        raise deck_drafts.MissingSchema(deck_drafts.MIGRATE)


def _row(cur, key):
    cur.execute(f"select {_COLUMNS} from deck_draft where profile_id = %s and deck_id = %s and version = %s", key)
    found = cur.fetchone()
    if found is None:
        return None
    revision, saved_at, device, content = found
    return {"revision": revision, "saved_at": deck_drafts.stamp(saved_at.astimezone(timezone.utc)),
            "device": device, "content": content}


def get(store, profile_id, deck_id, version):
    key = deck_drafts.key(profile_id, deck_id, version)

    def work(c):
        with c.cursor() as cur:
            _ready(cur)
            return deck_drafts.view(_row(cur, key))

    return store._call(work)


def put(store, profile_id, deck_id, version, content, expected_revision, *, device=""):
    key = deck_drafts.key(profile_id, deck_id, version)
    content = deck_drafts.content(content)
    expected = deck_drafts.expectation(expected_revision)
    device = deck_drafts.device(device)
    if store._batch() is not None:
        raise Invalid(deck_drafts.INDEPENDENT)

    def work(c):
        from psycopg.types.json import Jsonb
        with c.transaction(), c.cursor() as cur:
            _ready(cur)
            store._lock(cur, "deck-draft:" + "\n".join(key))
            before = _row(cur, key)
            after = deck_drafts.transition(before, expected, content, device, deck_drafts.stamp())
            if after is None:
                return deck_drafts.view(before)
            cur.execute("insert into deck_draft (profile_id, deck_id, version, revision, saved_at, device, content) "
                        "values (%s, %s, %s, %s, now(), %s, %s) on conflict (profile_id, deck_id, version) do update "
                        "set revision = excluded.revision, saved_at = excluded.saved_at, device = excluded.device, "
                        "content = excluded.content where deck_draft.revision = %s",
                        (*key, after["revision"], after["device"],
                         Jsonb(after["content"]) if after["content"] is not None else None, expected))
            saved = _row(cur, key)
            if saved is None or saved["revision"] != after["revision"]:
                raise Conflict(deck_drafts.CHANGED)
            return deck_drafts.view(saved)

    return store._call(work)
