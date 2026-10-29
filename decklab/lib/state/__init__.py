"""Deck Lab's personal state, behind one small interface: wishlists, profile settings, the
simulations mode and play records (decklab/PLAN.md, "Moving storage to a database", phase 2),
plus shared packing progress and the Activity page's view of the audit trail.

    from decklab.lib import state
    entries = state.store().wishlist("user1")
    changed, entries = state.store().wishlist_add("user1", entry, actor, "Add Plains to User1's wishlist")

store() is the active backend: the one a test installed with use(), else one process-wide
pg.PgStore (PostgreSQL, through decklab.db.conn). memory.MemoryStore keeps the same rules in
dicts, for tests and for running without a database. Both have these methods (pg.PgStore's
docstrings say exactly what each does; both backends behave the same, which
tests/test_state_contract.py checks):

- wishlist(profile_id) -> [{name, set, number, notes, source}], in list order, "" for no printing;
  wishlist_add(profile_id, entry, actor, message, *, at=None) -> (changed, entries) (at: the index
  to put it at, rules.insert_slot; the end when None);
  wishlist_remove(profile_id, name, actor, message, reason=None) -> (changed, entries);
  wishlist_set(profile_id, name, actor, message, *, notes=None, source=None, set=None,
               number=None) -> (changed, entries)  (the command line's; Invalid when it's absent)
- Wishlist writes also accept allow_orphan=False: an explicit CLI-only option for upkeep of
  retained lists without a profile. It never permits writes for a departed member or exempts
  the actor from membership checks.
- PostgreSQL wishlist_undo_review(change_id, profile_id) and wishlist_undo_apply(change_id,
  profile_id, expect, actor, message) review/apply one owner-only printing/notes/source UPDATE inverse
  or the latest own-wishlist INSERT/DELETE presence inverse with an exact unchanged row position.
  They require an independent transaction, exact global audit/current/list evidence and the
  shared wishlist lock. The saved receipt's decimal revision is the owner's latest audit-row
  id, not an inventory/deck revision. Memory-only tests use an explicit audit-shaped adapter.
- settings(profile_id) -> {key: value} as saved, in key order (api/settings.py checks values
  and fills in defaults); settings_put(profile_id, values, actor, message) -> {key: value},
  None removing a key; settings_cached(profile_id) -> {key: value}, the last good values
  ({} when none are known), never connecting and never Unavailable
- simulation_mode() -> {mode, by, by_id, since} or None when never set;
  simulation_mode_set(mode, actor, message, *, since=None, by_name=None) -> {mode, by, by_id, since};
  simulation_mode_cached() -> the last good view or None, never connecting and never raising
- visibility() -> {(owner, thing): {by, by_id, since}}, only Public switches; absent is Private;
  visibility_set(owner, thing, on, actor, message) -> that complete snapshot, one audited flip
  (a repeated value changes nothing); visibility_cached() -> the last good snapshot while
  younger than 60 seconds, else {}, never connecting or raising. These storage methods do not
  grant request access: public readers and owner-only controls must be ready before activation.
- play_get(kind, id) -> record or None; play_list(kind) -> [record] in id order;
  play_put(kind, record, expected_sha, actor, message) -> record
  Games retain their version-1 envelope. Explicit pod content uses stable seats
  and a separate game_version; legacy two-player bytes and hashes stay unchanged.
  Pod opponent labels carry no deck reference or invented captured list.
- packing_ticks(ids) -> [checked task hash] among ids, shared across home profiles;
  packing_activity(ids) -> latest scoped recorded {actor, at, checks} or None (never online presence);
  packing_ticks_put(changes, actor, message, *, ids=None) -> [checked task hash] among ids
  (defaults to changes' keys); changes maps opaque SHA-256 hashes to bool, patches only
  those tasks, and stores no task text or private kit labels
- commander_night() -> {night: {name, venue, target_bracket, published_min, published_max,
  house_rules, checked_on} or None, revision: int}; commander_night_put(night, expected_revision,
  actor, message, *, reason=None) -> that view; complete optimistic replacement of the home's
  dated Commander-night notes, with a required reason to clear and a retained revision after
  clearing. Unknown bracket facts are None, unknown date/venue/house rules blank; no seed data.
- field_policy(format) -> {v, format, revision, rules}; only a confirmed existing schema's
  absent row is an empty policy. field_policy_apply(format, expected_revision, expected_proof,
  rule, actor, message, reason=None) -> {changed, snapshot}; one independent audited CAS write,
  rejecting batches. The same write transaction checks the current incarnation, text receipt,
  selected version and card fingerprint before either a no-op or mutation. Exclude requires
  a bounded private audit reason, never part of policy content. Memory writes require an
  explicit locked fixture source; no provider falls back to configured inventory. These
  storage methods grant no request access and do not change field selection.
- activity(before=None, limit=50, *, visible=None, inventory=None) -> {"changes": [...], "next": id
  or None}; inventory (rules.inventory_scope's dict: tables, items, spaces, cap) filters,
  counts and caps the inventory's rows per change set (rules.inventory_rows; the database in
  SQL), and each change then also has "groups" (item rows counted), "more" (visible rows past
  the cap), "total" (every row, hidden ones included) and "kit" (an intact product's sleeves or
  deck box changed, rules.kit_changed)
- batch(actor, message, reason=None): a context manager putting every write the thread makes
  in its block into one change set, all kept or all rolled back (the phase-2 import's)
- reachable() -> bool

Every write takes an Actor (who, and from where) and a message saying what it does, which go
into the audit trail's change set; a write that changes nothing writes no change set. Errors
are StateError's: Unavailable (the database can't be used now: the api layer answers 503),
Conflict (changed since it was read, or the database was busy with another change: 409) and
Invalid (breaks a rule: 400), each carrying the words to show.

With DECKLAB_STATE_EXPLICIT set (the test package sets it), store() refuses rather than fall
back to the real database: every test has to install the store it means.

Nothing here imports psycopg; pg.py does, inside its methods.
"""
import os
import threading
from dataclasses import dataclass

EXPLICIT_ENV = "DECKLAB_STATE_EXPLICIT"
VIAS = ("home", "tunnel")           # decklab.db.conn.VIAS


class StateError(Exception):
    """Something a store couldn't do; str(error) is the plain-words reason to show."""


class Unavailable(StateError):
    """The database can't be used right now (not reachable, psycopg missing, or it needs
    migrating): nothing was read or written."""


class Conflict(StateError):
    """The data changed since it was read (a play record's hash), or the write clashes with
    another row: nothing was written."""


class Invalid(StateError):
    """The request breaks one of the stores' rules (a bad id, a full wishlist, a value that's
    too long): nothing was written."""


@dataclass(frozen=True)
class Actor:
    """Who is writing, for the audit trail.

    id: a profile id, or one of the trail's own actors: "claude" (the command line's default), "system"
    (imports and syncs), "home" (someone at home whose profile isn't known), "test".
    name: the name shown (a profile's display name at the time).
    via: the listener a web change came through, "home" or "tunnel"; None for anything else.
    source: one of decklab.db.conn.SOURCES ("web", "cli", "migration", ...)."""
    id: str
    name: str
    via: str | None = None
    source: str = "web"

    def __post_init__(self):
        from decklab.db.conn import SOURCES
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("an actor needs an id")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("an actor needs a name")
        if self.via is not None and self.via not in VIAS:
            raise ValueError(f"via must be one of {', '.join(VIAS)}, or None")
        if self.source not in SOURCES:
            raise ValueError(f"source must be one of {', '.join(SOURCES)}")


_lock = threading.Lock()
_active = []                        # stores installed by use(), innermost last
_default = None                     # the process-wide PgStore, made on first use


def store():
    """The active store: the innermost one use() installed, else the process-wide PgStore.
    Raises RuntimeError when none was installed and DECKLAB_STATE_EXPLICIT is set."""
    global _default
    with _lock:
        if _active:
            return _active[-1]
        if os.environ.get(EXPLICIT_ENV):
            raise RuntimeError(f"no state store was installed ({EXPLICIT_ENV} is set): "
                               "use decklab.lib.state.use(MemoryStore(...)) or a PgStore")
        if _default is None:
            from .pg import PgStore
            _default = PgStore()
        return _default


class _Restore:
    """What use() returns: call it (or leave its with block) to put back the previous store."""

    def __init__(self, installed):
        self.store = installed
        self._done = False

    def __call__(self):
        with _lock:
            if self._done:
                return
            self._done = True
            for i in range(len(_active) - 1, -1, -1):
                if _active[i] is self.store:
                    del _active[i]
                    break

    def __enter__(self):
        return self.store

    def __exit__(self, *exc):
        self()
        return False


def use(installed):
    """Make installed the active store until the returned callable is called. The callable is
    also a context manager (`with state.use(MemoryStore()) as s:`), and calling it twice is
    harmless. Stores nest: restoring one puts back whichever was active before it."""
    with _lock:
        _active.append(installed)
    return _Restore(installed)


def reachable():
    """False while the active store knows the database can't be used (PgStore's circuit
    breaker is open after a recent failure, or a MemoryStore marked down), so a caller can
    refuse before taking a lock; True otherwise. A True isn't a promise the next call works."""
    return store().reachable()
