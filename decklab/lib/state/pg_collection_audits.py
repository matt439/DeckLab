"""Read and record collection audit evidence under the inventory and storage claims."""
from datetime import timezone

from . import Conflict, Invalid, Unavailable, collection_audits as audit, pg_space_storage, rules, space_storage

_COLUMNS = ("section_id", "revision", "audited_at", *audit.SUMMARY)
_SELECT = "select " + ", ".join(_COLUMNS) + " from collection_section_audit where space_id = %s"


def _ready(cur):
    return cur.execute("select to_regclass('public.collection_section_audit') is not null").fetchone()[0]


def _record(row):
    saved = dict(zip(_COLUMNS, row, strict=True))
    try:
        audit.section_key(saved["section_id"])
        audit.validate({key: saved[key] for key in audit.SUMMARY})
        saved["audited_at"] = saved["audited_at"].astimezone(timezone.utc).isoformat()
    except (Invalid, AttributeError, ValueError):
        raise Unavailable(audit.UNAVAILABLE) from None
    return saved


def get(store, space):
    space = space_storage.space_id(space)

    def work(c):
        with c.cursor() as cur:
            if not _ready(cur):
                return {"ready": False, "sections": {}}
            rows = (_record(row) for row in cur.execute(_SELECT, (space,)))
            return {"ready": True, "sections": {row["section_id"]: row for row in rows}}

    return store._call(work)


def check(c):
    """Verify the stored evidence without using or disclosing current card data."""
    if not _ready(c):
        return True, False, "collection audits unavailable until migration 0031"
    count = 0
    try:
        for row in c.execute(f"select {', '.join(_COLUMNS)} from collection_section_audit"):
            _record(row)
            count += 1
    except Unavailable:
        return False, False, "a collection audit has invalid evidence"
    return True, False, f"{count} saved collection section audits"


def put(store, space, section_id, expected_revision, review, actor, message):
    from decklab.lib import storage_setting
    from decklab.lib.inventory.pg import PgInventory

    space = space_storage.space_id(space)
    section_id = audit.section_key(section_id)
    expected_revision = audit.expectation(expected_revision)
    _, message, _ = rules.check_write(actor, message)
    if store._batch() is not None:
        raise Invalid(audit.INDEPENDENT)

    def work(c):
        from psycopg.types.json import Jsonb

        # _change's shared inventory claim prevents inventory/loan/deck writes and member removal.
        # The next lock is the same one that protects the space's storage setting.
        with store._change(c, actor, message, space_ids=(space,), isolation="read committed") as (cur, _):
            if not _ready(cur):
                raise audit.MissingSchema(audit.MIGRATE)
            store._lock(cur, f"space-storage:{space}")
            previous = cur.execute("select revision from collection_section_audit "
                                   "where space_id = %s and section_id = %s", (space, section_id)).fetchone()
            if (previous[0] if previous else 0) != expected_revision:
                raise Conflict(audit.CHANGED)
            storage = storage_setting._view(space, pg_space_storage._read(cur, space), seed=False)
            backend = PgInventory(dbname=c.info.dbname, timeout=store.timeout, breaker=store.breaker)
            summary = review(backend.load(conn=c), storage)
            audit.validate(summary)
            values = (space, section_id, expected_revision + 1, *(summary[key] for key in audit.SUMMARY[:-1]),
                      Jsonb(summary["differences"]))
            fields = audit.SUMMARY
            placeholders = ", ".join(["%s"] * len(fields))
            updates = ", ".join(f"{key} = excluded.{key}" for key in ("revision", "audited_at", *fields))
            cur.execute(f"insert into collection_section_audit (space_id, section_id, revision, audited_at, "
                        f"{', '.join(fields)}) values (%s, %s, %s, clock_timestamp(), {placeholders}) "
                        f"on conflict (space_id, section_id) do update set {updates} "
                        f"returning {', '.join(_COLUMNS)}", values)
            return _record(cur.fetchone())

    return store._call(work)
