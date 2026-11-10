"""PgStore's price settings (E11-S53, migration 0022): one household record, saved whole with a
revision, as the shops' postage is (pg.py's shop_postage), but read through the store's
CACHE_SECONDS cache, since every price estimate asks for the currency (lib/pricing_setting.py).

Before the migration is applied the read raises Unavailable(pricing.MIGRATE) without tripping the
shared breaker, so the rest of Deck Lab keeps working and config.json applies.
"""
import copy

from . import Conflict, Unavailable, rules
from . import pricing as rules_pricing

KEY = ("pricing_setting",)          # the store's cache key


def _read(cur):
    cur.execute("select to_regclass('public.pricing_setting') is not null")
    if not cur.fetchone()[0]:
        raise Unavailable(rules_pricing.MIGRATE)
    cur.execute("select revision, content from pricing_setting where id = true")
    row = cur.fetchone()
    return ({"revision": row[0], "pricing": row[1]} if row
            else {"revision": 0, "pricing": dict(rules_pricing.EMPTY)})


def get(store):
    """{revision, pricing: {v, currency, shops}}, revision 0 with both None before any save. Cached
    for CACHE_SECONDS; a write by this process replaces the cached value at once."""
    return store._cached_read(KEY, lambda c: _read(c.cursor()))


def cached(store):
    """get()'s view as last read or written by this process, or None. Never connects or raises."""
    with store._cache_lock:
        return copy.deepcopy(store._last.get(KEY))


def put(store, pricing, expected_revision, actor, message):
    """Replace the whole record after checking its revision under its lock. An unchanged save
    writes nothing (and no change set)."""
    from .pg import _Unchanged
    pricing = rules_pricing.normalize(pricing)
    expected_revision = rules_pricing.expectation(expected_revision)
    rules.check_write(actor, message)

    def work(c):
        from psycopg.types.json import Jsonb
        try:
            with store._change(c, actor, message) as (cur, _):
                store._lock(cur, "pricing:home")
                saved = _read(cur)
                if saved["revision"] != expected_revision:
                    raise Conflict(rules_pricing.CHANGED)
                if saved["pricing"] == pricing:
                    raise _Unchanged(saved)
                if pricing["v"] == 2 and not cur.execute(
                        "select exists(select 1 from pg_catalog.pg_constraint where "
                        "conrelid=to_regclass('public.pricing_setting') and conname='pricing_listing_preferences_check')").fetchone()[0]:
                    raise Unavailable(rules_pricing.PREFERENCES_MIGRATE)
                revision = saved["revision"] + 1
                cur.execute("insert into pricing_setting (id, revision, content) values (true, %s, %s) "
                            "on conflict (id) do update set revision = excluded.revision, content = excluded.content",
                            (revision, Jsonb(pricing)))
                return {"revision": revision, "pricing": copy.deepcopy(pricing)}
        except _Unchanged as unchanged:
            return unchanged.result
    return store._cached_write(KEY, work)
