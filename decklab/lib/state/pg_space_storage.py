"""PgStore's storage settings (E8-S25, migration 0028): one record per space, saved whole with a
revision, as the shops' postage is (pg.py's shop_postage). Not cached: the Collection page reads
it with the rows, and writes check the revision again under the space's lock.

Before the migration is applied a read answers "nothing saved" with ready False (so home keeps its
built-in box and every page works as before), and a save raises Unavailable(space_storage.MIGRATE)
without tripping the shared breaker.
"""
import copy

from . import Conflict, Unavailable, rules
from . import space_storage as rules_storage


def _ready(cur):
    cur.execute("select to_regclass('public.space_storage') is not null")
    return bool(cur.fetchone()[0])


def _read(cur, space):
    if not _ready(cur):
        return {"space": space, "revision": 0, "storage": None, "ready": False}
    cur.execute("select revision, content from space_storage where space_id = %s", (space,))
    row = cur.fetchone()
    return {"space": space, "revision": row[0] if row else 0, "storage": row[1] if row else None, "ready": True}


def get(store, space):
    """{space, revision, storage (the saved record, or None), ready (False before 0028)}."""
    space = rules_storage.space_id(space)
    return store._call(lambda c: _read(c.cursor(), space))


def put(store, space, storage, expected_revision, actor, message):
    """Replace the space's whole record after checking its revision under the space's lock. An
    unchanged save writes nothing (and no change set); saving an empty record is a change."""
    from .pg import _Unchanged
    space = rules_storage.space_id(space)
    storage = rules_storage.normalize(storage)
    expected_revision = rules_storage.expectation(expected_revision)
    rules.check_write(actor, message)

    def work(c):
        from psycopg.types.json import Jsonb
        with c.cursor() as probe:
            if not _ready(probe):
                raise Unavailable(rules_storage.MIGRATE)
        try:
            with store._change(c, actor, message, space_ids=(space,)) as (cur, _):
                store._lock(cur, f"space-storage:{space}")
                saved = _read(cur, space)
                if saved["revision"] != expected_revision:
                    raise Conflict(rules_storage.CHANGED)
                if saved["storage"] == storage:
                    raise _Unchanged(saved)
                revision = saved["revision"] + 1
                cur.execute("insert into space_storage (space_id, revision, content) values (%s, %s, %s) "
                            "on conflict (space_id) do update set revision = excluded.revision, "
                            "content = excluded.content", (space, revision, Jsonb(storage)))
                return {"space": space, "revision": revision, "storage": copy.deepcopy(storage), "ready": True}
        except _Unchanged as unchanged:
            return unchanged.result
    return store._call(work)
