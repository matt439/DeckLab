"""Editor drafts kept for later on PostgreSQL (migration 0018's deck_draft, and 0019's
new_deck_draft for a new deck's; deck_drafts.py has the rules). Not audited: a put is its own
short transaction, never a change set, holding the draft's advisory lock while it checks the
revision and writes.

The table is looked for before every read and write (to_regclass), so a database not yet
migrated raises deck_drafts.MissingSchema without tripping the shared breaker (an undefined
table's error would), and the rest of Deck Lab carries on as before.
"""
from datetime import timezone

from . import Conflict, Invalid, deck_drafts

_COLUMNS = "revision, saved_at, device, content"
# (table, its key's columns, the advisory lock's prefix): constants only, never a request's text.
DECK = ("deck_draft", ("profile_id", "deck_id", "version"), "deck-draft:")
NEW = ("new_deck_draft", ("profile_id", "space_id", "source"), "new-deck-draft:")


def _ready(cur, table):
    cur.execute(f"select to_regclass('public.{table}') is not null")
    if cur.fetchone() != (True,):
        raise deck_drafts.MissingSchema(deck_drafts.MIGRATE)


def _row(cur, spec, key):
    table, columns, _ = spec
    where = " and ".join(f"{column} = %s" for column in columns)
    cur.execute(f"select {_COLUMNS} from {table} where {where}", key)
    found = cur.fetchone()
    if found is None:
        return None
    revision, saved_at, device, content = found
    return {"revision": revision, "saved_at": deck_drafts.stamp(saved_at.astimezone(timezone.utc)),
            "device": device, "content": content}


def _get(store, spec, key):
    def work(c):
        with c.cursor() as cur:
            _ready(cur, spec[0])
            return deck_drafts.view(_row(cur, spec, key))

    return store._call(work)


def _put(store, spec, key, content, expected_revision, device):
    table, columns, lock = spec
    content = deck_drafts.content(content)
    expected = deck_drafts.expectation(expected_revision)
    device = deck_drafts.device(device)
    if store._batch() is not None:
        raise Invalid(deck_drafts.INDEPENDENT)
    names = ", ".join(columns)

    def work(c):
        from psycopg.types.json import Jsonb
        with c.transaction(), c.cursor() as cur:
            _ready(cur, table)
            store._lock(cur, lock + "\n".join(key))
            before = _row(cur, spec, key)
            after = deck_drafts.transition(before, expected, content, device, deck_drafts.stamp())
            if after is None:
                return deck_drafts.view(before)
            cur.execute(f"insert into {table} ({names}, revision, saved_at, device, content) "
                        f"values (%s, %s, %s, %s, now(), %s, %s) on conflict ({names}) do update "
                        "set revision = excluded.revision, saved_at = excluded.saved_at, device = excluded.device, "
                        f"content = excluded.content where {table}.revision = %s",
                        (*key, after["revision"], after["device"],
                         Jsonb(after["content"]) if after["content"] is not None else None, expected))
            saved = _row(cur, spec, key)
            if saved is None or saved["revision"] != after["revision"]:
                raise Conflict(deck_drafts.CHANGED)
            return deck_drafts.view(saved)

    return store._call(work)


def get(store, profile_id, deck_id, version):
    return _get(store, DECK, deck_drafts.key(profile_id, deck_id, version))


def put(store, profile_id, deck_id, version, content, expected_revision, *, device=""):
    return _put(store, DECK, deck_drafts.key(profile_id, deck_id, version), content, expected_revision, device)


def new_get(store, profile_id, space_id, source):
    return _get(store, NEW, deck_drafts.new_key(profile_id, space_id, source))


def new_put(store, profile_id, space_id, source, content, expected_revision, *, device=""):
    return _put(store, NEW, deck_drafts.new_key(profile_id, space_id, source), content, expected_revision, device)
