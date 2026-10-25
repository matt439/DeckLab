"""Deck Lab's inventory (the collections, tokens, orders, products and the watchlist) as one
snapshot behind one small interface, with two backends (decklab/PLAN.md, "Moving storage to a
database", phase 3; the phase 3 design and its amendments).

    from decklab.lib import inventory
    inv = inventory.current()                     # the Inventory now (model.py)
    with inventory.pinned():                      # one request or command: one load, consistent reads
        ...
    inv, summary = inventory.apply(Op("collection.add", {...}), actor, "Add 2 Llanowar Elves")
    inv, summary = inventory.preview(Op(...))     # the snapshot it would make, nothing written

Every reader works from current(): it takes no snapshot argument (except pure helpers already
given a pool). pinned(snapshot) makes current() return that snapshot in the current context
(contextvars: this thread or task, never a thread it starts), so a receipt preview runs the pool,
Shopping and the deck-table refresh against the snapshot after the receipt with no globals
patched; pinned() with no snapshot loads one on first use and keeps it for the block, as the
server does once per request and the command lines once per command. An apply inside a pinned
block re-pins the snapshot it made.

The backend: the innermost one a test installed with use(), else the database (pg.PgInventory).
Tests install files.FileInventory(<a temp root>), which writes plain files (the lock order:
saving._save_lock first, then apply). Phase 5b removed config.json's "inventory": {"backend":
...} switch: Deck Lab reads only the database.
With DECKLAB_STATE_EXPLICIT set (the test package sets it), current() refuses unless a test
installed a backend: no test reads the real repo's inventory by accident.

Writes are operations: Op(kind, params), whose run(inv) calls the function registered for kind
(register()), a pure function inv -> (Inventory, Summary) raising state.Invalid or
state.Conflict with the words to show. An op builds its result with the snapshot's write helpers
(Inventory.with_collection, with_tokens, with_status_rows, with_watchlist, with_order,
with_product, update_component, move_component, set_component_rows: model.py), which leave each
source as every writer does. apply(op, actor, message, reason, expected_revision) loads the
inventory under the backend's lock (the files backend: a thread lock; the database: an
advisory lock in the write's transaction), checks
expected_revision only when it's given (a receipt's or an import's preview), runs the op on its
own copy of the records (changes.detach), settles and checks the result the same way on both
backends (changes.prepare: one place normalises, a collection or tokens file with no rows is no
file, and both refuse what the database can't hold) and writes what changed. A Summary's
extra["imports"] ([(space, file name, bytes)]) is written with it: the raw file an import keeps.
changed_paths(before, after) names the files a change touches (a Summary's changed, and what
the deck tables' refresh looks at), and changed_labels(before, after) the same in plain words
(a receipt preview's "changes", the order commands' dry runs).

preview(op) gives what apply would make, settled the same way, with the revision
"<revision>~preview" (Inventory.persisted is False): nothing may cache by a preview's revision
(the tokens deck cache, Forge provenance {"product", "revision"} and any pool cache skip a
snapshot that isn't persisted), so preview data is never served as the real inventory.

The stale-snapshot warning (the database backend serving its last good snapshot while the
database is down: Inventory.stale) is added by the HTTP dispatcher only: server_http pins one
snapshot per request and, when the request loaded a stale one, adds "inventory_stale": <the
words> to a JSON object answer (pinned_stale()). Readers never add it to their own warnings
(Pool.warnings and the gate's outputs stay the same whichever backend answers).

Each area registers its own operations (collection, tokens, receipts, orders, products, the
watchlist; phase 4's decks, kits, precons, accessories and pictures: ops_decks.py), in its own
module, with kinds named "<area>.<verb>" ("collection.add", "receipt.receive", ...).

The deck tables (phase 4; the phase 4 design's R3): a kind registered with refresh=True (the
writes that can change the tables' labels: receipt.receive, order.add/edit/split/cancel,
product.add/set_intact) has its deck tables refreshed inside the same change: apply() and
preview() run the operation, then refresh.in_op() plans the tables from its settled result and
puts the new deck texts in the same snapshot (nothing when the operation changed nothing), so a
preview's changed_paths names the deck files too; a plan that fails (whatever it raises), or a
backend that can't save deck texts (backend().saves_decks() False: a database that holds no
decks; "error" is DECK_SAVES_PAUSED), leaves the decks as they were and the change goes ahead, with
Summary.extra["tables"] saying what happened ({written, skipped, commit, error}).
apply(..., refresh=False) (a command line's --force) skips it. The card index is loaded before
the backend's lock.

The decks part's other reads, the same on both backends (the foundation review's M3):
image(name, sha256=None) gives a picture's bytes (None when there's none, or when sha256 is
given and they aren't those: the snapshot a page read is older or newer); deck_revisions(deck_id)
lists a deck's saved revisions newest first, deck_revision(deck_id, n) gives one with its text,
deck_revisions_with_text(deck_id, limit) the newest limit with their texts at once, and last_revision(deck_id) the newest, each a model.DeckRevision (the files backend keeps no
history: [] and None). A revision that changed the kit (DeckRevision.kit) shows its message only
to its actor (DeckRevision.message_for).

Nothing here imports psycopg; the database backend does, inside its methods. Every command-line
entry point that reads the inventory calls lib.venv.activate() first, so it can.
"""
import contextvars
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Mapping

from decklab.lib.state import Actor, Conflict, Invalid, StateError, Unavailable  # noqa: F401

from .changes import changed_labels, changed_paths  # noqa: F401
from .model import PREVIEW, DeckRevision, Inventory  # noqa: F401
from .aliases import deck_lineage, resolve_deck_id, same_deck_id  # noqa: F401

EXPLICIT_ENV = "DECKLAB_STATE_EXPLICIT"         # state.EXPLICIT_ENV
# What an operation that would change a deck, accessories.csv or a picture is refused with (and
# what the in-op table refresh reports) while the backend can't save them: a database that holds
# no decks (a fresh one, or a bad restore).
DECK_SAVES_PAUSED = ("Deck, accessory and picture saves can't be made: the database holds no decks. Restore the "
                     "newest backup (a decklab-*.dump from the NAS or decklab/data/backups/, with pg_restore), "
                     "after python -m decklab.db migrate if migrations are pending.")


# ------------------------------------------------------------------ operations

@dataclass(frozen=True)
class Summary:
    """What an operation did. text: one line in plain words ("Added 2 × Llanowar Elves (FDN 227)
    to the home collection"); counts: numbers for the answer ({"cards": 2, "added_rows": 1});
    changed: {derived path: [what changed there]}; extra: anything else the caller needs back
    (extra["imports"]: raw import files to keep, see the module docstring)."""
    text: str = ""
    counts: Mapping = field(default_factory=dict)
    changed: Mapping = field(default_factory=dict)
    extra: Mapping = field(default_factory=dict)


_OPS = {}
_REFRESH = set()                    # the kinds whose deck tables are refreshed in the same change
_ops_lock = threading.Lock()


def register(kind, refresh=False):
    """Decorator registering fn(inv, **params) -> (Inventory, Summary) as the operation kind.
    A kind is registered once. refresh: its deck tables are refreshed in the same change (see
    the module docstring)."""
    def add(fn):
        with _ops_lock:
            if kind in _OPS and _OPS[kind] is not fn:
                raise ValueError(f"inventory operation {kind!r} is already registered")
            _OPS[kind] = fn
            if refresh:
                _REFRESH.add(kind)
            else:
                _REFRESH.discard(kind)
        return fn
    return add


def unregister(kind):
    """Forget an operation kind (for tests that register their own)."""
    with _ops_lock:
        _OPS.pop(kind, None)
        _REFRESH.discard(kind)


def refreshes(kind):
    """Whether kind was registered with refresh=True."""
    with _ops_lock:
        return kind in _REFRESH


def kinds():
    """The registered operation kinds, sorted."""
    with _ops_lock:
        return sorted(_OPS)


@dataclass(frozen=True)
class Op:
    """An inventory operation: kind names a registered function and params are its keyword
    arguments (plain values, so a preview can be cached and run again at apply)."""
    kind: str
    params: Mapping = field(default_factory=dict)

    def run(self, inv):
        """(the Inventory after, Summary). state.Invalid for an unknown kind."""
        with _ops_lock:
            fn = _OPS.get(self.kind)
        if fn is None:
            raise Invalid(f"There's no inventory operation called {self.kind!r}.")
        result = fn(inv, **dict(self.params))
        if not (isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], Inventory)
                and isinstance(result[1], Summary)):
            raise TypeError(f"inventory operation {self.kind!r} must return (Inventory, Summary)")
        return result


@dataclass(frozen=True)
class _Refreshing:
    """op, with its deck tables refreshed from its result in the same run (refresh.in_op): what
    apply() and preview() hand the backend for a kind registered with refresh=True."""
    op: Op

    @property
    def kind(self):
        return self.op.kind

    @property
    def params(self):
        return self.op.params

    def run(self, inv):
        from . import refresh as tables
        after, summary = self.op.run(inv)
        return tables.in_op(inv, after, summary)


def _with_refresh(op, refresh):
    """op as apply() and preview() run it: wrapped in _Refreshing when its kind refreshes the
    deck tables and refresh is on (the card index loaded first, before any lock)."""
    if not refresh or not refreshes(op.kind):
        return op
    from . import refresh as tables
    tables.preload()
    return _Refreshing(op)


# ------------------------------------------------------------------ backends

_lock = threading.Lock()
_active = []                        # backends installed by use(), innermost last
_defaults = {}                      # (kind, root) -> the process-wide database backend


def _database():
    try:
        from .pg import PgInventory
    except ImportError as e:
        raise Unavailable(f"The inventory's database backend can't be loaded ({e}): install psycopg in the "
                          ".venv (decklab/requirements.txt).") from None
    return PgInventory()


def backend():
    """The active backend: the innermost one use() installed, else the database (made once a
    process). RuntimeError when none was installed and DECKLAB_STATE_EXPLICIT is set."""
    with _lock:
        if _active:
            return _active[-1]
        if os.environ.get(EXPLICIT_ENV):
            raise RuntimeError(f"no inventory backend was installed ({EXPLICIT_ENV} is set): "
                               "use decklab.lib.inventory.use(FileInventory(root))")
    from decklab.lib import config
    key = ("db", str(config.REPO))
    with _lock:
        if key not in _defaults:
            _defaults[key] = _database()
        return _defaults[key]


class _Restore:
    """What use() returns: call it (or leave its with block) to put back the previous backend."""

    def __init__(self, installed):
        self.backend = installed
        self._done = False

    def __call__(self):
        with _lock:
            if self._done:
                return
            self._done = True
            for i in range(len(_active) - 1, -1, -1):
                if _active[i] is self.backend:
                    del _active[i]
                    break

    def __enter__(self):
        return self.backend

    def __exit__(self, *exc):
        self()
        return False


def use(installed):
    """Make installed the active backend until the returned callable is called (also a context
    manager; calling it twice is harmless). Backends nest, as state.use's stores do."""
    with _lock:
        _active.append(installed)
    return _Restore(installed)


# ------------------------------------------------------------------ snapshots

class _Pin:
    """A pinned block's snapshot: given, or loaded on first use (lazy: invalidate() may drop it)."""

    def __init__(self, snapshot=None):
        self.snapshot = snapshot
        self.lazy = snapshot is None


_pinned = contextvars.ContextVar("decklab_inventory_pinned", default=None)


def current():
    """The inventory now: the pinned snapshot in a pinned() block, else the active backend's."""
    pin = _pinned.get()
    if pin is None:
        return backend().load()
    if pin.snapshot is None:
        pin.snapshot = backend().load()
    return pin.snapshot


@contextmanager
def pinned(snapshot=None):
    """Make current() return snapshot in this block (this context only); with no snapshot, the
    first current() in the block loads one and the rest of the block reuses it. Yields the pin
    holder's snapshot getter."""
    token = _pinned.set(_Pin(snapshot))
    try:
        yield current
    finally:
        _pinned.reset(token)


def invalidate():
    """Forget the snapshot this pinned block loaded, so the next current() loads the inventory
    again. For a writer whose answer must show what changed since the request's snapshot was
    loaded (api/accessories.py, after a lost race, reads again), not the snapshot from before.
    A snapshot given to pinned() (a preview's) is kept; outside a pinned block nothing is
    cached, so there's nothing to do."""
    pin = _pinned.get()
    if pin is not None and pin.lazy:
        pin.snapshot = None


def is_pinned():
    return _pinned.get() is not None


def pinned_stale():
    """The stale warning of the snapshot this pinned block has loaded (None when it loaded none,
    or a fresh one, or there's no pinned block): what the HTTP dispatcher adds to its answer,
    without loading anything itself."""
    pin = _pinned.get()
    return pin.snapshot.stale if pin is not None and pin.snapshot is not None else None


def stale_warning(inv=None):
    """The warning to show when inv (current() by default) is the database backend's last good
    snapshot, served because the database can't be reached; None otherwise. Only the HTTP
    dispatcher and the command lines show it (see the module docstring); readers never add it."""
    inv = current() if inv is None else inv
    return inv.stale


def reachable():
    """False while the active backend knows it can't be used now (the database's breaker is
    open); True otherwise."""
    return backend().reachable()


# ------------------------------------------------------------------ the decks part's other reads

def image(name, sha256=None):
    """The bytes of the accessory picture with this file name from the active backend, or None
    when there's none (or, given sha256, when its bytes aren't those)."""
    return backend().image(name, sha256)


def deck_revisions(deck_id):
    """[model.DeckRevision] of a deck's saved revisions, newest first, without their texts (a
    deleted deck's too); [] from the files backend, which keeps no history."""
    return backend().deck_revisions(deck_id)


def deck_revision(deck_id, number):
    """The model.DeckRevision number of a deck, with its text (None for a deletion), or None
    when there's no such revision (always None from the files backend)."""
    return backend().deck_revision(deck_id, number)


def deck_revisions_with_text(deck_id, limit):
    """The newest limit model.DeckRevisions of a deck with their texts, newest first, read at
    once where the backend can (the database: one query); a backend without that call reads
    deck_revisions() and then each one's text. [] from the files backend."""
    current = backend()
    read = getattr(current, "deck_revisions_with_text", None)
    if read is not None:
        return read(deck_id, limit)
    found = []
    for rev in current.deck_revisions(deck_id)[:limit]:
        full = current.deck_revision(deck_id, rev.revision)
        found.append(rev if full is None else full)
    return found


def last_revision(deck_id):
    """The newest model.DeckRevision of a deck, without its text, or None (the files backend:
    always None): who changed it last, for a page's "changed after you opened it" answer."""
    return backend().last_revision(deck_id)


def deck_edited():
    """{deck id: datetime} of when each deck that exists was last edited: its newest revision
    that changed it alone (a change set that also rewrote other decks, such as a receipt's or
    `deck tables --apply`'s table refresh, doesn't count) and changed more than the parts Deck Lab
    writes itself (a table's rows, its price stamp, the substitute list's availability note, the
    Cover card, Sleeves and Deck box lines: pg_decks.NOT_EDITS_RE). The library's "Recently changed"
    sort. {} from the files backend, which keeps no history, and from a backend without it."""
    edited = getattr(backend(), "deck_edited", None)
    return edited() if edited is not None else {}


# ------------------------------------------------------------------ writing

def preview(op, refresh=True):
    """(the Inventory op would make from current(), settled as apply would save it, with the
    revision "<current revision>~preview"; its Summary). Nothing is written. Raises what apply
    would raise for the op. Run the readers on the result inside pinned(result) to see what
    they'd say afterwards. refresh: as apply's."""
    from . import changes
    before = current()
    after, summary = _with_refresh(op, refresh).run(changes.detach(before))
    return changes.prepare(before, after, revision=before.revision + PREVIEW), summary


def apply(op, actor, message, reason=None, expected_revision=None, refresh=True):
    """Run op on the inventory as it is now and write what it changed, as one change (see the
    module docstring). Returns (the Inventory after, Summary). Raises state.Conflict when
    expected_revision is given and the inventory has moved on, state.Invalid / state.Conflict
    from the op itself, state.Unavailable when the backend can't be used. refresh: refresh the
    deck tables in the same change when op's kind was registered with refresh=True (False:
    skip it, a command line's --force)."""
    if not isinstance(actor, Actor):
        raise TypeError("apply needs a state.Actor")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("apply needs a message saying what the change does")
    after, summary = backend().apply(_with_refresh(op, refresh), actor, message, reason=reason,
                                     expected_revision=expected_revision)
    pin = _pinned.get()
    if pin is not None:
        pin.snapshot = after
    return after, summary
