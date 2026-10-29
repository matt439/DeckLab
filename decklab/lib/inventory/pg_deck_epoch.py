"""Bounded, same-transaction PostgreSQL proof of a current HOME deck's epoch.

``read(backend, deck_id)`` owns one read-only repeatable-read transaction on the
explicit PgInventory backend. It never uses the current/default inventory, a
history convenience reader, or the stale fallback of ``backend.load()``.

``capture_on_connection`` is internal infrastructure for a caller that already
owns a coherent transaction. Its mandatory coherence mode is checked: ``reader``
requires read-only repeatable-read/serializable, and ``inventory-locked`` requires
an already granted inventory advisory claim. The caller must retain that claim,
use the connection exclusively, and perform no intervening writes while consuming
the capture. This helper never begins/ends a transaction or acquires a lock.

Captures contain current text and minimal lineage rows, so they stay inside the
trusted caller. Public results contain only a checked epoch and current receipt;
no historical text, actor, audit message, or accessory metadata is returned.
Caps bound this proof, not the existing backend's complete inventory snapshot IO.
"""

from collections.abc import Mapping
import re

from . import deck_epoch
from .model import Deck, Inventory
from .pg import PgInventory


_REVISION = re.compile(r"[1-9][0-9]*\Z")
_INVENTORY_CLAIM = """select exists (
    select 1 from pg_locks
    where pid = pg_backend_pid() and locktype = 'advisory' and granted
      and mode in ('ShareLock', 'ExclusiveLock') and objsubid = 1
      and database = (select oid from pg_database where datname = current_database())
      and classid::bigint = ((hashtext('inventory')::bigint >> 32) & 4294967295)
      and objid::bigint = (hashtext('inventory')::bigint & 4294967295)
)"""


def _unavailable():
    return deck_epoch.Resolution("unavailable", None, None)


def _active(conn):
    status = getattr(getattr(conn, "info", None), "transaction_status", None)
    return isinstance(status, int) and not isinstance(status, bool) and status == 2


def _coherent(conn, mode):
    if not _active(conn):
        return False
    if mode == "reader":
        isolation = conn.execute("show transaction_isolation").fetchone()
        readonly = conn.execute("show transaction_read_only").fetchone()
        return isolation in (("repeatable read",), ("serializable",)) and readonly == ("on",)
    if mode == "inventory-locked":
        return conn.execute(_INVENTORY_CLAIM).fetchone() == (True,)
    return False


def _home_looking(value):
    return isinstance(value, str) and value.startswith(("casual/", "commander/"))


def _metadata(snapshot):
    """Project only HOME metadata; retain malformed edges touching HOME to reject."""
    if not isinstance(snapshot, Inventory) or not isinstance(snapshot.revision, str) \
            or not isinstance(snapshot.decks_revision, str) or snapshot.backend != "db" or snapshot.root is not None \
            or snapshot.persisted is not True or snapshot.stale is not None \
            or snapshot.aliases_ready is not True or not _REVISION.fullmatch(snapshot.revision) \
            or not _REVISION.fullmatch(snapshot.decks_revision):
        return None
    if not isinstance(snapshot.decks, Mapping) or not isinstance(snapshot.deck_aliases, Mapping):
        return None
    if any(type(key) is not str for key in snapshot.decks) or any(
            type(key) is not str or target is not None and type(target) is not str
            for key, target in snapshot.deck_aliases.items()):
        return None
    current_ids = tuple(key for key, value in snapshot.decks.items()
                        if _home_looking(key) or getattr(value, "space", None) == "home")
    aliases = {key: target for key, target in snapshot.deck_aliases.items()
               if _home_looking(key) or _home_looking(target)}
    if len(current_ids) > deck_epoch.MAX_CURRENT_IDS or len(aliases) > deck_epoch.MAX_ALIASES:
        return None
    return current_ids, aliases


def capture_on_connection(backend, conn, deck_id, *, coherence):
    """Return a private bounded capture, or None, within a verified caller transaction.

    Database errors propagate to the caller's normal transaction/error handler.
    An absent/invalid proof returns None without opening another connection. The
    mandatory mode and exclusive-use/claim-lifetime obligations are documented
    above; this API cannot protect against a caller concurrently sharing ``conn``.
    """
    if not isinstance(backend, PgInventory) or not deck_epoch.home_id(deck_id) \
            or not _coherent(conn, coherence):
        return None
    snapshot = backend.load(conn=conn)
    metadata = _metadata(snapshot)
    if metadata is None:
        return None
    current_ids, aliases = metadata
    canonical = deck_epoch.identity(deck_id, current_ids, aliases)
    if canonical is None:
        return None
    held = snapshot.decks.get(canonical)
    if not isinstance(held, Deck) or held.space != "home" or held.kind not in ("casual", "commander") \
            or held.id != canonical or type(held.revision) is not int \
            or not 1 <= held.revision <= deck_epoch.MAX_HISTORY or not isinstance(held.text, str) \
            or held.error is not None:
        return None
    row = conn.execute("select d.id, d.revision, t.text from deck d "
                       "join deck_text t on t.deck_id = d.id where d.id = %s", (canonical,)).fetchone()
    if type(row) not in (tuple, list) or len(row) != 3:
        return None
    current_id, revision, text = row
    if current_id != canonical or type(revision) is not int or not 1 <= revision <= deck_epoch.MAX_HISTORY \
            or not isinstance(text, str):
        return None
    try:
        if len(text.encode("utf-8")) > deck_epoch.MAX_TEXT_BYTES:
            return None
    except UnicodeError:
        return None
    if held.revision != revision or held.text != text:
        return None
    lineage = (canonical, *(alias for alias, target in aliases.items() if target == canonical))
    rows = conn.execute("select deck_id, revision, op, change_set_id from deck_revision "
                        "where deck_id = any(%s) order by revision, deck_id limit %s",
                        (list(lineage), deck_epoch.MAX_HISTORY + 1)).fetchall()
    if type(rows) not in (tuple, list) or not rows or len(rows) > deck_epoch.MAX_HISTORY \
            or any(type(item) not in (tuple, list) or len(item) != 4 for item in rows):
        return None
    latest = conn.execute("select deck_id, revision, text from deck_revision "
                          "where deck_id = any(%s) order by revision desc, deck_id limit 1",
                          (list(lineage),)).fetchone()
    if type(latest) not in (tuple, list) or len(latest) != 3:
        return None
    return {
        "backend": "db", "persisted": True, "stale": None, "complete": True,
        "requested_id": deck_id, "current": {"id": canonical, "revision": revision, "text": text},
        "current_ids": current_ids, "aliases": aliases,
        "history": [dict(zip(("deck_id", "revision", "op", "change_set_id"), item)) for item in rows],
        "latest": dict(zip(("deck_id", "revision", "text"), latest)),
    }


def read(backend, deck_id):
    """Read a checked epoch using only the supplied PostgreSQL backend's connection."""
    if not isinstance(backend, PgInventory) or not deck_epoch.home_id(deck_id):
        return _unavailable()

    def work(conn):
        with conn.transaction():
            conn.execute("set transaction isolation level repeatable read, read only")
            capture = capture_on_connection(backend, conn, deck_id, coherence="reader")
            return deck_epoch.resolve(capture) if capture is not None else _unavailable()

    try:
        return backend._call(work)
    except Exception:
        # The transaction/context has already unwound; never relay raw DB or deck
        # error text, and never retry through load()'s stale/default path.
        return _unavailable()
