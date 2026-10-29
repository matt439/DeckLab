"""The PostgreSQL store: Deck Lab's personal state in the tables of migration 0003, through
decklab.db.conn (one app-role connection per call, never shared between request threads,
and conn.change() for every write, so each lands in the audit trail with who, from where,
what and why).

- Errors: a database that can't be reached (or psycopg missing) is state.Unavailable, and so
  is one that needs migrating (a missing table or column, or a refused privilege), or a
  statement that waited too long for a lock or ran too long (REQUEST_OPTIONS' timeouts); a
  unique clash, a deadlock or a serialization failure is Conflict (try again), a value the
  table's checks refuse is Invalid.
- The circuit breaker (BREAKER): after the database couldn't be reached (the connection
  failed or dropped, or the server is shutting down or full), calls fail at once for
  BREAKER_SECONDS without trying to connect, so a stopped PostgreSQL doesn't make every request
  wait for its timeout; dbstatus.py's probe resets it when the database answers again. A
  statement-level error (a timeout, a deadlock) never trips it. Trips go to db.log.
- Settings and the simulations mode are read on many polls and written mostly by this server, so
  they're cached in the process: loaded on first use and updated after each successful write.
  A cached value is served for CACHE_SECONDS, then read again, so a write by another process
  (a command line, a test server on the same database) shows up within a minute.
  A write holds a lock around the database call and its cache update, and bumps the key's
  generation, so a read that overlapped a write never puts the older value back. When the
  breaker trips the cached values stop being served by settings() and simulation_mode(), but
  are kept as the last good ones for settings_cached() and simulation_mode_cached(), which
  never connect (the polls' fallbacks while the database is down); clear_cache() forgets both.
- Visibility uses the same generation-safe cache, but its fallback grants expire after
  CACHE_SECONDS too: with no recent snapshot everything is Private. Batched flips publish
  their cache only after commit, including a confirmed no-op, and never on rollback.
- Wishlist writes for one profile are serialised by an advisory lock, and the casefold rule is
  decided in Python (rules.py) under it; the table's lower() index is only a backstop.
- Every write takes shared membership admission before its per-key locks. Member removal
  takes the exclusive counterpart, so queued saves recheck committed departure and an
  admitted transaction finishes before removal can take its snapshot.
- Play records are written under an advisory lock on the record, after checking the stored
  record's hash (rules.record_sha, worked out in Python from the rebuilt record, never from
  jsonb text) against the one the caller read.
- batch(actor, message) puts several writes from one thread into one change set (the phase-2
  import's): all of them are kept, or none.

psycopg is imported only inside the methods (through conn), so this module imports anywhere.
"""
import copy
import threading
import time
from contextlib import contextmanager
from datetime import timezone

from decklab.db import conn as db

from . import Conflict, Invalid, Unavailable, rules, visibility

REQUEST_TIMEOUT = 2                 # seconds to connect before a request gives up
# Each connection's limits, so a request thread never waits forever on a lock (an advisory
# lock included) or a slow statement: milliseconds.
REQUEST_OPTIONS = "-c lock_timeout=2000 -c statement_timeout=5000"
BREAKER_SECONDS = 30
CACHE_SECONDS = 60                  # how long settings()/simulation_mode() serve a cached value
MIGRATE_MESSAGE = "the database needs: python -m decklab.db migrate"
BUSY_MESSAGE = "The database was busy with another change at the same moment; try again"
SLOW_MESSAGE = "the database took too long to answer"
REFUSED_MESSAGE = "The database refused that value: it breaks one of the rules for what can be saved"
# SQLSTATEs meaning the schema is older than this code: undefined table, undefined column, and
# insufficient privilege (a table the migration hasn't granted yet).
NEEDS_MIGRATING = ("42P01", "42703", "42501")
# SQLSTATEs meaning the database itself can't be used (besides class 08, connection
# exceptions, and errors with no SQLSTATE at all, a connection that dropped): the server is
# shutting down or crashed, can't connect now, or has too many connections. Only these trip
# the breaker.
DOWN_STATES = ("57P01", "57P02", "57P03", "53300")
# Statement-level waits that ran out (query canceled by statement_timeout, lock_timeout).
TIMED_OUT = ("57014", "55P03")


def _log(text):
    """A line in db.log; never raises (an outage must still be answered)."""
    try:
        db.log(f"state: {text}")
    except Exception:                               # noqa: BLE001 (a log that can't be written)
        pass


def mapped_error(psycopg, error, down):
    """The state error for a psycopg error (the module docstring's mapping), or error itself
    when it's none of those. down(reason) is called for a database that can't be used: it
    trips the breaker and returns the Unavailable to raise. Shared with the inventory's
    database backend (lib/inventory/pg.py), so both say the same things the same way."""
    state = getattr(error, "sqlstate", None) or ""
    detail = (str(error).strip().splitlines() or ["no detail"])[0]
    if state in NEEDS_MIGRATING:
        return down(MIGRATE_MESSAGE)
    if state == "23505":
        return Conflict("That clashes with something already saved; reload and try again")
    if isinstance(error, psycopg.DataError) or state.startswith(("22", "23")):
        # psycopg's own refusals (a NUL in text) have no SQLSTATE but are DataErrors too.
        return Invalid(REFUSED_MESSAGE)
    if state.startswith("40"):                      # a deadlock or serialization failure
        return Conflict(BUSY_MESSAGE)
    if state in TIMED_OUT:
        return Unavailable(f"{SLOW_MESSAGE}: {detail}")
    if isinstance(error, (psycopg.OperationalError, psycopg.InterfaceError)):
        if not state or state.startswith("08") or state in DOWN_STATES:
            return down(f"the database stopped answering: {detail}")
        return Unavailable(f"the database couldn't do that just now: {detail}")
    return error


class Breaker:
    """Fails calls at once for a while after the database couldn't be used.

    trip(reason) opens it for `seconds`; reset() closes it (dbstatus's probe got an answer);
    check() raises Unavailable while it's open. trips counts the trips, so caches can tell
    one has happened since they were filled. log(text), when given, is told when it opens
    and when a reset closes it after a trip (the process-wide BREAKER writes db.log)."""

    def __init__(self, seconds=BREAKER_SECONDS, log=None):
        self.seconds = seconds
        self.trips = 0
        self._until = 0.0
        self._reason = None
        self._tripped = False
        self._log = log
        self._lock = threading.Lock()

    def trip(self, reason):
        with self._lock:
            was_open = time.monotonic() < self._until
            self._until = time.monotonic() + self.seconds
            self._reason = str(reason)
            self._tripped = True
            self.trips += 1
        if not was_open and self._log:
            self._log(f"database unavailable, failing fast for {self.seconds} s: {reason}")

    def reset(self):
        with self._lock:
            was_tripped, self._tripped = self._tripped, False
            self._until = 0.0
        if was_tripped and self._log:
            self._log("database reachable again")

    def is_open(self):
        with self._lock:
            return time.monotonic() < self._until

    def check(self):
        with self._lock:
            if time.monotonic() < self._until:
                raise Unavailable(self._reason or "the database isn't reachable")


BREAKER = Breaker(log=_log)


class _Unchanged(Exception):
    """Rolls back a change that turned out to change nothing (so no empty change set is left),
    carrying the answer to give."""

    def __init__(self, result):
        super().__init__()
        self.result = result


class _Batch:
    """The open batch of one thread: its connection, its change set, and the cache keys its
    writes touched (forgotten when it ends, whether it was kept or rolled back)."""

    def __init__(self, connection, change_set):
        self.connection = connection
        self.change_set = change_set
        self.keys = set()
        self.values = {}            # visibility writes, published to the cache only on commit


_ENTRY_COLUMNS = "name, set_code, collector_number, notes, source"
_PLAY_COLUMNS = "id, revision, created_on, updated_on, updated_by, content"
_MODE = ("mode",)                   # the simulations mode's cache key (settings': ("settings", id))
_VISIBILITY = ("visibility",)


def _entry(row):
    name, set_code, number, notes, source = row
    return {"name": name, "set": set_code or "", "number": number or "", "notes": notes, "source": source}


def _iso(value):
    """A timestamptz as the simulations file wrote it: local time to the second, with offset."""
    return value.astimezone().isoformat(timespec="seconds") if value is not None else None


def _mode_view(row):
    if row is None:
        return None
    mode, set_by, set_by_name, since = row
    return {"mode": mode, "by": set_by_name, "by_id": set_by, "since": _iso(since)}


def _audit_rows(c, ids):
    """({change set id: [row, ...]}, {}): every row of those change sets, oldest first."""
    rows = {}
    for set_id, table, op, key, old, new in c.execute(
            "select change_set_id, table_name, op, row_key, before, after "
            "from audit.row_change where change_set_id = any(%s) order by id", (ids,)).fetchall():
        rows.setdefault(set_id, []).append({"table": table, "op": op, "key": key, "before": old, "after": new})
    return rows, {}


# rules.inventory_rows in SQL: the viewer's inventory rows of each change set, position-only
# updates left out, the item tables counted by their row key without position, the other rows
# listed up to the cap with how many there are in all (n), and those past the cap summed per
# table: the copies they added and removed, and the added or removed rows whose quantity can't be
# read (rules.quantity_delta).
def _quantity_sql(side):
    """SQL for a row_change side's quantity as rules._quantity reads it: a JSON number (truncated)
    or a string of digits, else null."""
    return (f"case when jsonb_typeof({side}->'quantity') = 'number' then trunc(({side}->>'quantity')::numeric)::bigint "
            f"when jsonb_typeof({side}->'quantity') = 'string' and {side}->>'quantity' ~ '^[[:space:]]*[-+]?[0-9]+[[:space:]]*$' "
            f"then trim({side}->>'quantity')::bigint end")


_INVENTORY_ROWS = """
with r as (
    select id, change_set_id, table_name, op, row_key, before, after,
           coalesce(after->>'space_id', before->>'space_id', row_key->>'space_id', 'home') as space
    from audit.row_change
    where change_set_id = any(%(ids)s) and table_name = any(%(tables)s::text[])
      and not (op = 'UPDATE' and coalesce(before - 'position' = after - 'position', false))
), v as (
    select * from r where %(all)s or space = any(%(spaces)s::text[])
), listed as (
    select *, row_number() over (partition by change_set_id order by id) as k,
           count(*) over (partition by change_set_id) as n
    from v where not table_name = any(%(items)s::text[])
)
select 'row', change_set_id, table_name, op, row_key, before, after, n, id from listed where k <= %(cap)s
union all
select 'group', change_set_id, table_name, op, row_key - 'position', null, null, count(*), min(id)
from v where table_name = any(%(items)s::text[]) group by change_set_id, table_name, op, row_key - 'position'
union all
select 'past', change_set_id, table_name, null,
       jsonb_build_object('added', coalesce(sum(d) filter (where d > 0), 0),
                          'removed', coalesce(-sum(d) filter (where d < 0), 0),
                          'unknown', count(*) filter (where d is null and op <> 'UPDATE')),
       null, null, count(*), min(id)
from (select *, case op when 'INSERT' then qa when 'DELETE' then -qb else qa - qb end as d
      from (select *, """ + _quantity_sql("after") + " as qa, " + _quantity_sql("before") + """ as qb
            from listed where k > %(cap)s) q) p
group by change_set_id, table_name
order by 9
"""


# rules.kit_changed in SQL: an update of an intact product's sleeves or deck box, any accessory row,
# or a deck row whose kit_version changed (missing as 0).
_KIT_CHANGED = ("(table_name = 'product_status' and op = 'UPDATE' and ("
                + " or ".join(f"coalesce(before->>'{k}', '') <> coalesce(after->>'{k}', '')" for k in rules.KIT_FIELDS)
                + f")) or table_name = '{rules.ACCESSORY_TABLE}'"
                + f" or (table_name = '{rules.DECK_TABLE}' and coalesce(before->>'{rules.KIT_VERSION}', '0')"
                + f" <> coalesce(after->>'{rules.KIT_VERSION}', '0'))")


def _inventory_audit_rows(c, ids, spec):
    """(rows, {change set id: {"groups", "more", "past", "total", "kit"}}) as rules.inventory_rows gives them,
    worked out in SQL so a change set of thousands of rows never leaves the database whole."""
    tables, cap = list(spec["tables"]), spec["cap"]
    found = c.execute("select id, change_set_id, table_name, op, row_key, before, after from audit.row_change "
                      "where change_set_id = any(%s) and not table_name = any(%s) order by id",
                      (ids, tables)).fetchall()
    merged = {}
    for rid, set_id, table, op, key, old, new in found:
        merged.setdefault(set_id, []).append((rid, {"table": table, "op": op, "key": key, "before": old, "after": new}))
    extra = {set_id: {"groups": [], "more": 0, "past": {}, "total": total, "kit": kit} for set_id, total, kit in c.execute(
        "select change_set_id, count(*), coalesce(bool_or(" + _KIT_CHANGED + "), false) from audit.row_change "
        "where change_set_id = any(%s) group by 1", (ids,)).fetchall()}
    params = {"ids": ids, "tables": tables, "items": list(spec["items"]), "cap": cap,
              "all": spec["spaces"] is None, "spaces": list(spec["spaces"] or ())}
    for kind, set_id, table, op, key, old, new, n, rid in c.execute(_INVENTORY_ROWS, params).fetchall():
        info = extra.setdefault(set_id, {"groups": [], "more": 0, "past": {}, "total": 0, "kit": False})
        if kind == "past":
            info["past"][table] = {k: int(key[k]) for k in ("added", "removed", "unknown")}
        elif kind == "group":
            info["groups"].append({"table": table, "op": op, "key": key, "count": n})
        else:
            merged.setdefault(set_id, []).append((rid, {"table": table, "op": op, "key": key, "before": old,
                                                        "after": new}))
            info["more"] = max(0, n - cap)
    rows = {set_id: [row for _, row in sorted(found, key=lambda r: r[0])] for set_id, found in merged.items()}
    return rows, extra


class PgStore:
    """The state store on PostgreSQL (see the module docstring, and decklab.lib.state for the
    interface). dbname: the database to use (default: conn.settings()'s, read at each call, so
    the tests' DECKLAB_DB_NAME reaches it); timeout: seconds to connect."""

    def __init__(self, dbname=None, timeout=REQUEST_TIMEOUT, breaker=None):
        self.dbname = dbname
        self.timeout = timeout
        self.breaker = breaker or BREAKER
        self._cache_lock = threading.Lock()
        # Held around each settings or mode write and its cache update (and a whole batch), so
        # the cache ends with the value of the write that committed last.
        self._write_lock = threading.RLock()
        self._fresh = {}            # cache key -> (value settings()/simulation_mode() serve, when cached)
        self._last = {}             # cache key -> the last good value, kept through outages
        self._last_when = {}        # visibility fallback expires even during an outage
        self._generation = {}       # cache key -> writes begun or ended (a read that saw it change won't cache)
        self._epoch = 0             # bumped whenever the fresh values are dropped
        self._trips = self.breaker.trips
        self._local = threading.local()
        self._clock = time.monotonic    # replaced by the tests

    # ------------------------------------------------------------------ plumbing

    def reachable(self):
        """False while the breaker is open (state.reachable())."""
        return not self.breaker.is_open()

    def clear_cache(self):
        """Forget the cached settings and simulations mode, the last good values included (the
        next read goes to the database)."""
        with self._cache_lock:
            self._fresh = {}
            self._last = {}
            self._last_when = {}
            self._epoch += 1
            self._trips = self.breaker.trips

    def _expire(self):
        """Stop serving the cached values without connecting (the breaker tripped); the last
        good ones stay for the *_cached readers."""
        with self._cache_lock:
            self._fresh = {}
            self._epoch += 1
            self._trips = self.breaker.trips

    def _sync_cache(self):
        if self._trips != self.breaker.trips:
            self._expire()

    def _batch(self):
        return getattr(self._local, "batch", None)

    def _keep(self, key, value):
        """Cache value under key (fresh for CACHE_SECONDS, and the last good one); hold
        _cache_lock."""
        self._fresh[key] = (copy.deepcopy(value), self._clock())
        self._last[key] = copy.deepcopy(value)
        self._last_when[key] = self._clock()

    def _cached_read(self, key, work):
        """The value under key: the cached one while it's younger than CACHE_SECONDS, else
        work(connection)'s, which is cached only when no write to the key began or ended while
        it ran and nothing was cached meanwhile."""
        if self._batch() is not None:
            return self._call(work)                 # a batch's own view isn't committed yet
        self._sync_cache()
        with self._cache_lock:
            if key in self._fresh:
                value, when = self._fresh[key]
                if self._clock() - when < CACHE_SECONDS:
                    return copy.deepcopy(value)
                del self._fresh[key]                # stale: another process may have written it
            token = (self._epoch, self._generation.get(key, 0))
        value = self._call(work)
        with self._cache_lock:
            if key not in self._fresh and token == (self._epoch, self._generation.get(key, 0)):
                self._keep(key, value)
        return value

    def _bump(self, key):
        with self._cache_lock:
            self._generation[key] = self._generation.get(key, 0) + 1
            self._fresh.pop(key, None)

    def _cached_write(self, key, work):
        """work(connection)'s answer, the value now saved under key, cached once it's
        committed (inside a batch, only when the batch ends: see batch())."""
        with self._write_lock:
            self._bump(key)
            batch = self._batch()
            try:
                value = self._call(work)
            finally:
                self._bump(key)
            if batch is not None:
                batch.keys.add(key)
                if key == _VISIBILITY:
                    batch.values[key] = copy.deepcopy(value)
                return value
            with self._cache_lock:
                self._keep(key, value)
            return value

    def _down(self, reason):
        self.breaker.trip(reason)
        self._expire()
        return Unavailable(reason)

    def _connect(self):
        """(psycopg, a new autocommit app-role connection with REQUEST_OPTIONS)."""
        self.breaker.check()
        try:
            psycopg = db._psycopg()
            c = db.connect("app", dbname=self.dbname, autocommit=True, timeout=self.timeout,
                           options=REQUEST_OPTIONS)
        except db.DbUnavailable as e:
            raise self._down(str(e)) from None
        return psycopg, c

    def _call(self, work):
        """work(connection) on a new autocommit app-role connection (or this thread's open
        batch's), with errors mapped to state's (the module docstring)."""
        batch = self._batch()
        if batch is not None:
            import psycopg
            try:
                return work(batch.connection)
            except psycopg.Error as e:
                raise self._mapped(psycopg, e) from None
        psycopg, c = self._connect()
        try:
            with c:
                return work(c)
        except psycopg.Error as e:
            raise self._mapped(psycopg, e) from None

    def _mapped(self, psycopg, error):
        return mapped_error(psycopg, error, self._down)

    @contextmanager
    def _change(self, c, actor, message, reason=None, *, profile_ids=(), space_ids=(), orphan_profile_ids=(),
                isolation=None):
        """conn.change() for one write, yielding (cursor, change set id); inside a batch, a
        savepoint in the batch's change set instead (actor, message and reason are the
        batch's then). Admission remains held until that transaction commits.
        An explicit isolation is only valid for an independent change."""
        batch = self._batch()
        if batch is not None and isolation is not None:
            raise ValueError("an explicit transaction isolation cannot be used inside a batch")
        from decklab.db import space_members
        if batch is None:
            options = {"isolation": isolation} if isolation is not None else {}
            with db.change(actor.id, actor.source, message, reason, conn=c, via=actor.via, **options) as out:
                space_members.admit(out[0], profile_ids=profile_ids, space_ids=space_ids, actor=actor,
                                    orphan_profile_ids=orphan_profile_ids)
                yield out
        else:
            with c.transaction():
                with c.cursor() as cur:
                    space_members.admit(cur, profile_ids=profile_ids, space_ids=space_ids, actor=actor,
                                        orphan_profile_ids=orphan_profile_ids)
                    yield cur, batch.change_set

    @staticmethod
    def _lock(cur, key):
        cur.execute("select pg_advisory_xact_lock(hashtext(%s))", (key,))

    @contextmanager
    def batch(self, actor, message, reason=None):
        """One change set for every write this thread makes in the with block:

            with store.batch(Actor("system", "System", None, "migration"), "Import phase 2 files"):
                store.wishlist_add(...)
                store.settings_put(...)

        The writes still take an actor and a message (checked), but the trail records the
        batch's. They're all committed when the block ends, or all rolled back when it raises
        (a write that raised on its own is rolled back alone, so the block may go on). A batch
        whose writes changed nothing leaves no change set. Reads in the block see its writes.
        Other threads' settings and mode writes wait for it. Batches don't nest."""
        rules.check_write(actor, message, reason)
        if self._batch() is not None:
            raise ValueError("a batch is already open in this thread (batches don't nest)")
        with self._write_lock:
            psycopg, c = self._connect()
            batch = None
            committed = False
            try:
                with c:
                    with db.change(actor.id, actor.source, message, reason, conn=c, via=actor.via) as (cur, change_set):
                        from decklab.db import space_members
                        space_members.admit(cur, actor=actor)
                        batch = self._local.batch = _Batch(c, change_set)
                        try:
                            yield self
                        finally:
                            self._local.batch = None
                        cur.execute("select exists (select 1 from audit.row_change where change_set_id = %s)",
                                    (change_set,))
                        if not cur.fetchone()[0]:
                            raise _Unchanged(None)
                committed = True
            except _Unchanged:
                committed = True                    # confirmed no-op snapshots are committed facts too
            except psycopg.Error as e:
                raise self._mapped(psycopg, e) from None
            finally:
                for key in batch.keys if batch else ():
                    self._bump(key)
                if committed and batch:
                    with self._cache_lock:
                        for key, value in batch.values.items():
                            self._keep(key, value)

    # ------------------------------------------------------------------ wishlists

    @staticmethod
    def _entries(cur, profile_id):
        """(entries, positions) for the profile, in list order."""
        cur.execute(f"select position, {_ENTRY_COLUMNS} from wishlist_entry where profile_id = %s "
                    "order by position", (profile_id,))
        rows = cur.fetchall()
        return [_entry(r[1:]) for r in rows], [r[0] for r in rows]

    def wishlist(self, profile_id):
        """The profile's wishlist: [{name, set, number, notes, source}] in list order, "" for
        no printing, notes or source. [] for none."""
        pid = rules.profile_id(profile_id)

        def work(c):
            with c.cursor() as cur:
                return self._entries(cur, pid)[0]
        return self._call(work)

    def wishlist_add(self, profile_id, entry, actor, message, *, at=None, allow_orphan=False):
        """Append entry ({name, set, number[, notes, source]}) to the profile's wishlist, or
        with at, put it at that index of the list (rules.insert_slot: the page's Undo of a
        removal puts the card back where it was). Returns (changed, entries): changed False
        (nothing written) when a casefold-equal name is already there. Invalid when the entry
        breaks a rule, at isn't a whole number from 0, or the list holds MAX_ENTRIES."""
        pid = rules.profile_id(profile_id)
        new = rules.entry(entry)
        rules.check_write(actor, message)
        orphans = (pid,) if rules.wishlist_orphan(allow_orphan, actor) else ()
        rules.insert_slot([], at)           # at's form, before anything is read

        def work(c):
            import psycopg
            try:
                with self._change(c, actor, message, profile_ids=(pid,), orphan_profile_ids=orphans) as (cur, _):
                    self._lock(cur, f"wishlist:{pid}")
                    entries, positions = self._entries(cur, pid)
                    changed, result = self._wishlist_add_at(cur, pid, entries, positions, new, at=at)
                    if not changed:
                        raise _Unchanged((False, result))
                    return changed, result
            except _Unchanged as u:
                return u.result
            except psycopg.errors.UniqueViolation:
                # The lower() backstop: a name Python's casefold rule let through (it never
                # should). Nothing was written, so report it as unchanged.
                with c.cursor() as cur:
                    return False, self._entries(cur, pid)[0]
        return self._call(work)

    def wishlist_remove(self, profile_id, name, actor, message, reason=None, *, allow_orphan=False):
        """Remove the entry whose name is casefold-equal to name. Returns (changed, entries):
        changed False (nothing written) when there's none."""
        pid = rules.profile_id(profile_id)
        rules.check_write(actor, message, reason)
        orphans = (pid,) if rules.wishlist_orphan(allow_orphan, actor) else ()

        def work(c):
            try:
                with self._change(c, actor, message, reason, profile_ids=(pid,), orphan_profile_ids=orphans) as (cur, _):
                    self._lock(cur, f"wishlist:{pid}")
                    entries, positions = self._entries(cur, pid)
                    changed, result = self._wishlist_remove_at(cur, pid, entries, positions, name)
                    if not changed:
                        raise _Unchanged((False, result))
                    return changed, result
            except _Unchanged as u:
                return u.result
        return self._call(work)

    def wishlist_set(self, profile_id, name, actor, message, *, notes=None, source=None, set=None,
                     number=None, allow_orphan=False):
        """Change the given fields of the entry casefold-equal to name (None keeps a field; set
        and number go together, "" for both removes the printing). Returns (changed, entries):
        changed False when the values were already those. Invalid when there's no such entry.
        The command line's write, and the Wishlist page's sheet (notes, printing and source)."""
        pid = rules.profile_id(profile_id)
        rules.check_write(actor, message)
        orphans = (pid,) if rules.wishlist_orphan(allow_orphan, actor) else ()

        def work(c):
            try:
                with self._change(c, actor, message, profile_ids=(pid,), orphan_profile_ids=orphans) as (cur, _):
                    self._lock(cur, f"wishlist:{pid}")
                    entries, positions = self._entries(cur, pid)
                    changed, result = self._wishlist_set_at(cur, pid, entries, positions, name,
                                                          notes=notes, source=source, set=set, number=number)
                    if not changed:
                        raise _Unchanged((False, result))
                    return changed, result
            except _Unchanged as u:
                return u.result
        return self._call(work)

    @staticmethod
    def _wishlist_add_at(cur, pid, entries, positions, new, *, at=None):
        """Ordinary insertion, including its existing duplicate/no-op and position rules."""
        new = rules.entry(new)
        if rules.add_plan(entries, new) == "exists":
            return False, entries
        position, moves = rules.insert_slot(positions, at)
        for old, moved in moves:
            cur.execute("update wishlist_entry set position=%s where profile_id=%s and position=%s", (moved, pid, old))
        cur.execute("insert into wishlist_entry(profile_id,position,name,set_code,collector_number,notes,source) "
                    "values(%s,%s,%s,%s,%s,%s,%s)", (pid, position, new["name"], new["set"] or None,
                    new["number"] or None, new["notes"], new["source"]))
        index = len(entries) if at is None else min(at, len(entries))
        return True, entries[:index] + [new] + entries[index:]

    @staticmethod
    def _wishlist_remove_at(cur, pid, entries, positions, name):
        """Ordinary casefold removal on the same admitted/locked connection."""
        i = rules.find(entries, name)
        if i is None:
            return False, entries
        cur.execute("delete from wishlist_entry where profile_id=%s and position=%s", (pid, positions[i]))
        return True, entries[:i] + entries[i + 1:]

    @staticmethod
    def _wishlist_set_at(cur, pid, entries, positions, name, **fields):
        """The ordinary setter on an already admitted/locked cursor; never opens a connection."""
        i = rules.find(entries, name)
        if i is None:
            raise Invalid(f"{name} isn't on the wishlist")
        new = rules.edited(entries[i], **fields)
        if new == entries[i]:
            return False, entries
        cur.execute("update wishlist_entry set set_code = %s, collector_number = %s, notes = %s, "
                    "source = %s where profile_id = %s and position = %s",
                    (new["set"] or None, new["number"] or None, new["notes"], new["source"], pid, positions[i]))
        return True, entries[:i] + [new] + entries[i + 1:]

    def wishlist_undo_review(self, change_id, profile_id):
        from . import pg_wishlist_undo
        return pg_wishlist_undo.preview(self, change_id, profile_id)

    def wishlist_undo_apply(self, change_id, profile_id, expect, actor, message):
        from . import pg_wishlist_undo
        return pg_wishlist_undo.apply(self, change_id, profile_id, expect, actor, message)

    # ------------------------------------------------------------------ settings

    def settings(self, profile_id):
        """The profile's saved settings, {key: value} (text) in key order, {} for none. Cached."""
        pid = rules.profile_id(profile_id)

        def work(c):
            rows = c.execute('select key, value from profile_setting where profile_id = %s order by key collate "C"',
                             (pid,)).fetchall()
            return dict(rows)
        return self._cached_read(("settings", pid), work)

    def settings_cached(self, profile_id):
        """The profile's settings as last read or written successfully by this process, {} when
        nothing is known. Never connects and never raises Unavailable: the fallback of readers
        that must answer while the database is down (the matchup and field polls)."""
        pid = rules.profile_id(profile_id)
        with self._cache_lock:
            return dict(self._last.get(("settings", pid)) or {})

    def settings_put(self, profile_id, values, actor, message):
        """Save values ({key: text, or None to remove the key}) over the profile's settings,
        leaving other keys alone. Returns the saved settings after it, in key order. Writes
        nothing (no change set) when every value is already as saved."""
        pid = rules.profile_id(profile_id)
        values = rules.setting_values(values)
        rules.check_write(actor, message)

        def work(c):
            try:
                with self._change(c, actor, message, profile_ids=(pid,)) as (cur, _):
                    self._lock(cur, f"settings:{pid}")
                    cur.execute("select key, value from profile_setting where profile_id = %s", (pid,))
                    saved = dict(cur.fetchall())
                    changed = False
                    for key, value in values.items():
                        if value is None:
                            if key in saved:
                                cur.execute("delete from profile_setting where profile_id = %s and key = %s",
                                            (pid, key))
                                del saved[key]
                                changed = True
                        elif key not in saved:
                            cur.execute("insert into profile_setting (profile_id, key, value) values (%s, %s, %s)",
                                        (pid, key, value))
                            saved[key] = value
                            changed = True
                        elif saved[key] != value:
                            cur.execute("update profile_setting set value = %s where profile_id = %s and key = %s",
                                        (value, pid, key))
                            saved[key] = value
                            changed = True
                    if not changed:
                        raise _Unchanged(saved)
                    return dict(sorted(saved.items()))
            except _Unchanged as u:
                return dict(sorted(u.result.items()))
        return self._cached_write(("settings", pid), work)

    # ------------------------------------------------------------------ shared packing progress

    @staticmethod
    def _packing_ticks(cur, ids):
        cur.execute("select id from packing_tick where id = any(%s::text[]) order by id", (ids,))
        return [row[0] for row in cur.fetchall()]

    def packing_ticks(self, ids):
        """Checked physical-task hashes among ids. Shared by home, never per profile."""
        ids = rules.packing_ids(ids)
        return self._call(lambda c: self._packing_ticks(c.cursor(), ids))

    def packing_activity(self, ids):
        """Latest recorded tick/untick change affecting the requested task hashes, or None.

        Return only its raw actor id, UTC timestamp and matching audit-row count. The table-name
        filter uses the existing audit index; unrelated rows and task identities never leave SQL.
        This read neither writes audit rows nor claims the actor is currently packing or online.
        The current thread's unfinished batch is excluded until it commits, as in MemoryStore.
        """
        ids = rules.packing_ids(ids)
        if not ids:
            return None

        def work(c):
            batch = self._batch()
            pending = batch.change_set if batch is not None else None
            # Change sets are allocated before the packing lock. Audit-row IDs follow the actual
            # serialized packing writes, even when an earlier transaction takes that lock later.
            row = c.execute("with latest as (select r.change_set_id as id from audit.row_change r "
                            "where r.table_name = 'packing_tick' and r.row_key->>'id' = any(%s::text[]) "
                            "and (%s::bigint is null or r.change_set_id <> %s) order by r.id desc limit 1) "
                            "select c.actor, c.at, count(r.id) from latest l "
                            "join audit.change_set c on c.id = l.id "
                            "join audit.row_change r on r.change_set_id = c.id "
                            "where r.table_name = 'packing_tick' and r.row_key->>'id' = any(%s::text[]) "
                            "group by c.id, c.actor, c.at", (ids, pending, pending, ids)).fetchone()
            return {"actor": row[0], "at": row[1].astimezone(timezone.utc).isoformat(), "checks": row[2]} if row else None
        return self._call(work)

    def packing_ticks_put(self, changes, actor, message, *, ids=None):
        """Atomically patch individual tasks, returning checked hashes within ids.

        Different devices' unrelated ticks cannot overwrite each other. Same-task edits
        take effect in commit order. Clearing a view only changes the explicit False keys;
        tasks in another selection or a private kit remain untouched. No-op writes leave
        no change set. Only opaque hashes ever reach this store or its audit trail.
        """
        changes = rules.packing_changes(changes)
        ids = rules.packing_ids(list(changes) if ids is None else ids)
        if not set(changes) <= set(ids):
            raise Invalid("Packing changes must name tasks in the requested scope")
        rules.check_write(actor, message)

        def work(c):
            try:
                with self._change(c, actor, message) as (cur, _):
                    self._lock(cur, "packing:home")
                    changed = False
                    for key, done in changes.items():
                        if done:
                            cur.execute("insert into packing_tick (id) values (%s) on conflict do nothing", (key,))
                        else:
                            cur.execute("delete from packing_tick where id = %s", (key,))
                        changed = bool(cur.rowcount) or changed
                    ticks = self._packing_ticks(cur, ids)
                    if not changed:
                        raise _Unchanged(ticks)
                    return ticks
            except _Unchanged as unchanged:
                return unchanged.result
        return self._call(work)

    # ------------------------------------------------------------------ the household's per-format field choices

    def field_policy(self, fmt):
        """Fresh normalized policy; only a proven schema-ready absence is empty."""
        from . import pg_field_policy
        return pg_field_policy.get(self, fmt)

    def field_policy_apply(self, fmt, expected_revision, expected_proof, rule, actor, message, reason=None):
        """One independently admitted CAS change, after fresh list/epoch proof."""
        from . import pg_field_policy
        return pg_field_policy.apply(self, fmt, expected_revision, expected_proof, rule, actor, message, reason)

    # ------------------------------------------------------------------ the household's Commander night

    @staticmethod
    def _commander_night(cur):
        # This panel may be read between installing code and applying its migration.
        # A known missing optional table must not trip the shared database breaker.
        cur.execute("select to_regclass('public.commander_night') is not null")
        if not cur.fetchone()[0]:
            raise Unavailable(MIGRATE_MESSAGE)
        cur.execute("select revision, content from commander_night where id = true")
        row = cur.fetchone()
        return {"revision": row[0], "night": row[1]} if row else {"revision": 0, "night": None}

    def commander_night(self):
        """The home note and its monotonic revision, or revision 0 when never recorded.

        Not cached: an editor gets the latest complete view; writes check it again under
        the singleton's transaction lock. A missing schema is Unavailable, never empty.
        """
        return self._call(lambda c: self._commander_night(c.cursor()))

    def commander_night_put(self, night, expected_revision, actor, message, *, reason=None):
        """Replace notes after checking their complete revision; clear keeps a tombstone.

        An unchanged save leaves no audit change. The revision check happens first, so
        matching an old note's contents cannot make a stale editor current again.
        """
        from . import commander_night as notes
        night, expected_revision = notes.normalize(night), notes.expectation(expected_revision)
        if night is None:
            reason = notes.clear_reason(reason)
        rules.check_write(actor, message, reason)

        def work(c):
            from psycopg.types.json import Jsonb
            try:
                with self._change(c, actor, message, reason) as (cur, _):
                    self._lock(cur, "commander-night:home")
                    saved = self._commander_night(cur)
                    if saved["revision"] != expected_revision:
                        raise Conflict(notes.CHANGED)
                    if saved["night"] == night:
                        raise _Unchanged(saved)
                    revision = saved["revision"] + 1
                    cur.execute("insert into commander_night (id, revision, content) values (true, %s, %s) "
                                "on conflict (id) do update set revision = excluded.revision, content = excluded.content",
                                (revision, Jsonb(night) if night is not None else None))
                    return {"revision": revision, "night": copy.deepcopy(night)}
            except _Unchanged as unchanged:
                return unchanged.result
        return self._call(work)

    # ------------------------------------------------------------------ the simulations mode

    def simulation_mode(self):
        """{mode, by (the name shown), by_id (a profile id, or None), since (ISO, local time to
        the second)}, or None when nobody has set it (the default applies). Cached."""
        def work(c):
            return _mode_view(c.execute("select mode, set_by, set_by_name, since from simulation_mode").fetchone())
        return self._cached_read(_MODE, work)

    def simulation_mode_cached(self):
        """simulation_mode()'s view as last read or written successfully by this process, or None
        when nothing is known (or it was never set). Never connects and never raises: the
        simulations setting's fallback while the database is down."""
        with self._cache_lock:
            return copy.deepcopy(self._last.get(_MODE))

    def simulation_mode_set(self, mode, actor, message, *, since=None, by_name=None):
        """Set the mode (admins, everyone or paused), by actor, now. Always writes (who and when
        change even when the mode doesn't). since (a datetime or ISO text; without an offset,
        this PC's local time) and by_name are for the import from the old file: by_name records
        who by name only (by_id None). Returns simulation_mode()'s view of it."""
        mode = rules.mode(mode)
        rules.check_write(actor, message)
        since = rules.since(since)
        set_by, set_by_name = (None, rules.by_name(by_name)) if by_name is not None else (actor.id.strip(), actor.name)

        def work(c):
            with self._change(c, actor, message) as (cur, _):
                cur.execute("insert into simulation_mode (id, mode, set_by, set_by_name, since) "
                            "values (true, %s, %s, %s, coalesce(%s::timestamptz, now())) "
                            "on conflict (id) do update set mode = excluded.mode, set_by = excluded.set_by, "
                            "set_by_name = excluded.set_by_name, since = excluded.since "
                            "returning mode, set_by, set_by_name, since", (mode, set_by, set_by_name, since))
                return _mode_view(cur.fetchone())
        return self._cached_write(_MODE, work)

    # ------------------------------------------------------------------ visibility switches

    @staticmethod
    def _visibility(c):
        # A code update may precede the optional migration. Fail this reader
        # closed without opening the shared outage breaker and disabling unrelated
        # wishlist/settings writes against an otherwise healthy database.
        if c.execute("select to_regclass('public.visibility') is null").fetchone()[0]:
            raise Unavailable(MIGRATE_MESSAGE)
        rows = c.execute("select owner, thing, set_by, set_by_name, since from visibility "
                         "order by owner, thing").fetchall()
        return visibility.view((owner, thing, actor, name, _iso(since))
                               for owner, thing, actor, name, since in rows)

    def visibility(self):
        """The complete Public-switch snapshot, cached for at most CACHE_SECONDS.
        Raises Unavailable on an unreadable database; visibility_cached is the bounded,
        fail-closed fallback. No row means Private; no live switches are seeded."""
        return self._cached_read(_VISIBILITY, self._visibility)

    def visibility_cached(self):
        """Never connect. Return a copy of the last good snapshot for up to 60 seconds,
        then {}. Unlike display settings, stale access grants must expire during outages."""
        with self._cache_lock:
            when = self._last_when.get(_VISIBILITY)
            if when is None or self._clock() - when >= CACHE_SECONDS:
                return {}
            return copy.deepcopy(self._last.get(_VISIBILITY, {}))

    def visibility_set(self, owner, thing, on, actor, message):
        """Set one switch and return the complete snapshot. A repeated state is a no-op.
        The caller checks ownership/readiness: this storage seam activates no request reader."""
        owner, thing = visibility.switch(owner, thing, on)
        rules.check_write(actor, message)
        profiles = (owner,) if thing == "accessories" and owner != "shared" else ()
        spaces = ("home",) if thing == "accessories" else (owner,)

        def work(c):
            try:
                with self._change(c, actor, message, profile_ids=profiles, space_ids=spaces) as (cur, _):
                    self._lock(cur, "visibility")
                    saved = self._visibility(cur)
                    if ((owner, thing) in saved) == on:
                        raise _Unchanged(saved)
                    if on:
                        cur.execute("insert into visibility (owner, thing, set_by, set_by_name) "
                                    "values (%s, %s, %s, %s)", (owner, thing, actor.id.strip(), actor.name))
                    else:
                        cur.execute("delete from visibility where owner = %s and thing = %s", (owner, thing))
                    return self._visibility(cur)
            except _Unchanged as unchanged:
                return unchanged.result
        return self._cached_write(_VISIBILITY, work)

    # ------------------------------------------------------------------ play records

    @staticmethod
    def _record(kind, row):
        record_id, revision, created_on, updated_on, updated_by, content = row
        return rules.rebuild({"version": 1, "id": record_id, "kind": kind, "revision": revision,
                              "created_on": created_on, "updated_on": updated_on, "updated_by": updated_by},
                             content)

    def play_get(self, kind, record_id):
        """The record (a dict exactly as its file held it), or None when there's none."""
        kind, record_id = rules.play_kind(kind), rules.play_id(record_id)

        def work(c):
            row = c.execute(f"select {_PLAY_COLUMNS} from play_record where kind = %s and id = %s",
                            (kind, record_id)).fetchone()
            return self._record(kind, row) if row else None
        return self._call(work)

    def play_list(self, kind):
        """Every record of the kind, in id order."""
        kind = rules.play_kind(kind)

        def work(c):
            rows = c.execute(f"select {_PLAY_COLUMNS} from play_record where kind = %s order by id",
                             (kind,)).fetchall()
            return [self._record(kind, row) for row in rows]
        return self._call(work)

    def play_put(self, kind, record, expected_sha, actor, message):
        """Save record (the whole dict, its revision, times and updated_by already set by the
        caller) as the kind's record with its id. expected_sha: rules.record_sha of the record
        the caller read, or None for a new one. Conflict (CHANGED_MESSAGE, nothing written)
        when the stored record isn't that one. Invalid for a record jsonb wouldn't give back
        exactly (a float, a NUL). Returns the record as stored (its sha is rules.record_sha
        of it)."""
        kind = rules.play_kind(kind)
        header, content, deck_ids = rules.split_record(kind, record)
        rules.check_write(actor, message)
        from decklab.lib import spaces
        try:
            owners = {spaces.split_deck_id(deck_id)[0] for deck_id in deck_ids}
        except ValueError:
            raise Invalid("A play record must name valid deck spaces") from None
        if content.get("space"):
            owners.add(content["space"])

        def work(c):
            from psycopg.types.json import Jsonb
            with self._change(c, actor, message, space_ids=owners) as (cur, _):
                self._lock(cur, f"play:{kind}:{header['id']}")
                cur.execute(f"select {_PLAY_COLUMNS} from play_record where kind = %s and id = %s",
                            (kind, header["id"]))
                row = cur.fetchone()
                stored = rules.record_sha(self._record(kind, row)) if row else None
                if stored != expected_sha:
                    raise Conflict(rules.CHANGED_MESSAGE)
                values = (header["revision"], header["created_on"], header["updated_on"], header["updated_by"],
                          deck_ids, Jsonb(content))
                if row:
                    cur.execute("update play_record set revision = %s, created_on = %s, updated_on = %s, "
                                "updated_by = %s, deck_ids = %s, content = %s where kind = %s and id = %s "
                                f"returning {_PLAY_COLUMNS}", (*values, kind, header["id"]))
                else:
                    cur.execute("insert into play_record (revision, created_on, updated_on, updated_by, deck_ids, "
                                f"content, kind, id) values (%s, %s, %s, %s, %s, %s, %s, %s) returning {_PLAY_COLUMNS}",
                                (*values, kind, header["id"]))
                return self._record(kind, cur.fetchone())
        return self._call(work)

    # ------------------------------------------------------------------ the audit trail

    def activity(self, before=None, limit=50, *, visible=None, inventory=None):
        """The audit trail, newest first: {"changes": [...], "next": id or None}.

        Each change is {id, at (ISO, UTC), actor, source, via, message, reason, rows}, and each
        row {table, op, key, before, after}: the row_change as recorded (key, before and after
        are to_jsonb's dicts, None where there's none; a timestamptz in them is text in the
        server's TimeZone, so compare times parsed, never as text). The rows are raw, private
        data included: visible(change), when given, decides what a viewer may see
        (rules.activity_page, which also says how paging and the SCAN_CAP work). before:
        return only change sets older than this id; limit: 1 to rules.MAX_LIMIT.

        inventory (rules.inventory_scope's dict): the inventory's rows are filtered, counted and
        capped here in SQL, as rules.inventory_rows says, so a change set of thousands of rows
        (an import, a receipt) never comes back whole: each change then also has "groups",
        "more", "past" and "total"."""
        before, limit = rules.page_args(before, limit)
        spec = rules.inventory_scope(inventory)

        def work(c):
            def fetch(cursor, n):
                sets = c.execute("select id, at, actor, source, via, message, reason from audit.change_set "
                                 "where %s::bigint is null or id < %s order by id desc limit %s",
                                 (cursor, cursor, n)).fetchall()
                rows, extra = {}, {}
                if sets:
                    ids = [s[0] for s in sets]
                    rows, extra = _audit_rows(c, ids) if spec is None else _inventory_audit_rows(c, ids, spec)
                return [{"id": s[0], "at": s[1].astimezone(timezone.utc).isoformat(), "actor": s[2],
                         "source": s[3], "via": s[4], "message": s[5], "reason": s[6], "rows": rows.get(s[0], []),
                         **({} if spec is None else extra.get(s[0], {"groups": [], "more": 0, "past": {},
                                                                      "total": 0, "kit": False}))}
                        for s in sets]
            return rules.activity_page(fetch, before, limit, visible)
        return self._call(work)
