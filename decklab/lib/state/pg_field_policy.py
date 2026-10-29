"""Independent, audited field-policy CAS with fresh same-connection list proof.

This storage layer grants no request permissions and changes no selector. Its
writer owns an idle connection and explicit READ COMMITTED transaction: a held
inventory claim alone cannot prove freshness if an earlier repeatable-read
snapshot was established before waiting for an inventory writer. Admission takes
the shared claim before the per-format lock; no claim is upgraded.

Only a schema-ready absent row is empty. No cached policy, default inventory,
convenience history reader or separately connected proof may authorize a save.
"""
import copy

from decklab.lib.inventory import pg_deck_epoch
from decklab.lib.inventory.pg import PgInventory

from . import Conflict, Invalid, Unavailable, field_policy, rules
from . import field_policy_source as source

UNAVAILABLE = "The field policy could not be confirmed. Nothing was saved."
MIGRATE = "Field policies need the database migration: python -m decklab.db migrate"
INDEPENDENT = "Field policy changes need an independent transaction."


class _MissingSchema(Unavailable):
    pass


def _read(cur, fmt):
    cur.execute("select to_regclass('public.field_policy') is not null")
    if cur.fetchone() != (True,):
        raise _MissingSchema(MIGRATE)
    cur.execute("select revision, content from field_policy where format = %s", (fmt,))
    row = cur.fetchone()
    if row is None:
        return field_policy.empty(fmt)
    try:
        if type(row) not in (tuple, list) or len(row) != 2:
            raise Invalid(field_policy.INVALID)
        revision, content = row
        if type(revision) is not int or revision < 1 or type(content) is not dict or content.keys() != {"v", "rules"}:
            raise Invalid(field_policy.INVALID)
        supplied = {"v": content["v"], "format": fmt, "revision": revision, "rules": content["rules"]}
        checked = field_policy.normalize(supplied)
        if checked != supplied:
            raise Invalid(field_policy.INVALID)
        return checked
    except (Invalid, TypeError, ValueError):
        raise Unavailable(UNAVAILABLE) from None


def _call(store, work):
    try:
        return store._call(work)
    except _MissingSchema:
        raise
    except Unavailable:
        # Existing database error mapping may include diagnostic details. These
        # policy boundaries expose only fixed words, never private SQL/deck data.
        raise Unavailable(UNAVAILABLE) from None


def get(store, fmt):
    fmt = field_policy.empty(fmt)["format"]

    def work(conn):
        with conn.cursor() as cur:
            return _read(cur, fmt)

    return _call(store, work)


def apply(store, fmt, expected_revision, expected_proof, rule, actor, message, reason=None):
    """Return {changed, snapshot}; every accepted no-op also rechecks fresh proof."""
    fmt = field_policy.empty(fmt)["format"]
    if type(expected_revision) is not int or not 0 <= expected_revision <= field_policy.MAX_REVISION:
        raise Invalid(field_policy.INVALID)
    expected, desired = source.intent(expected_proof, rule, fmt)
    reason = source.exclusion_reason(reason, desired["mode"])
    _, message, reason = rules.check_write(actor, message, reason)
    if store._batch() is not None:
        raise Invalid(INDEPENDENT)

    def work(conn):
        from psycopg.types.json import Jsonb
        from .pg import _Unchanged
        if getattr(getattr(conn, "info", None), "transaction_status", None) != 0:
            raise Invalid(INDEPENDENT)
        name = getattr(conn.info, "dbname", None)
        if type(name) is not str or not name:
            raise Unavailable(UNAVAILABLE)
        try:
            with store._change(conn, actor, message, reason, space_ids=("home",),
                               isolation="read committed") as (cur, _):
                store._lock(cur, f"field-policy:home:{fmt}")
                saved = _read(cur, fmt)
                plan = field_policy.transition(saved, expected_revision, desired)
                backend = PgInventory(dbname=name, timeout=store.timeout, breaker=store.breaker)
                capture = pg_deck_epoch.capture_on_connection(
                    backend, conn, expected["receipt"]["deck_id"], coherence="inventory-locked")
                source.recheck(capture, expected, desired, fmt)
                if not plan["changed"]:
                    raise _Unchanged(plan)
                after = plan["snapshot"]
                content = {"v": after["v"], "rules": after["rules"]}
                cur.execute("insert into field_policy (format, revision, content) values (%s, %s, %s) "
                            "on conflict (format) do update set revision = excluded.revision, content = excluded.content "
                            "where field_policy.revision = %s returning revision",
                            (fmt, after["revision"], Jsonb(content), expected_revision))
                if cur.fetchone() != (after["revision"],):
                    raise Conflict(field_policy.CHANGED)
                return copy.deepcopy(plan)
        except _Unchanged as unchanged:
            return unchanged.result

    return _call(store, work)
