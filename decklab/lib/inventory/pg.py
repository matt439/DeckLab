"""The database backend: the inventory in migration 0004's tables (decklab/PLAN.md, phase 3; the
phase 3 design's amendments Q3-Q6), through decklab.db.conn, giving the same snapshot the files
backend makes (model.py) so every reader works the same on either.

    inv = PgInventory().load()                     # the Inventory now (cached by revision)
    inv, summary = PgInventory().apply(op, actor, "Add 2 Llanowar Elves")
    revision = write_model(inv, actor, "Load the fixture", contents={...})

- Loading: every table is read in one REPEATABLE READ, read-only transaction, then put in order in
  Python (never by SQL collation): a collection by merge_cards' sort_key, tokens and the
  watchlist by position, products and records by name. The rows are written out as the files
  they were (canonical: LF, no BOM, each file's header) and read back by files.build, so the
  snapshot, its problems and its line numbers are the files backend's exactly; only the
  revision (the database's counter, as text), backend ("db"), the token and watchlist rows'
  hidden ids (their database ids) and the products' names (stored: the files can't carry them)
  come from the database. A space with no cards has no collection file (exists False, as an
  empty space has no file); status.csv and watchlist.csv are always there, header only when
  empty.
- The snapshot is cached in the process, keyed by the revision (and the import's time, so a
  database imported again is never mistaken for the old one): a load is one cheap query while
  nothing has changed. When the database can't be reached, load() serves the last good snapshot
  marked stale (Inventory.stale says "inventory as of <time>: the database isn't reachable"), so
  the deck pages still work; writes refuse (state.Unavailable).
- No inventory_revision row means the inventory was never imported: load() and apply() refuse
  (NotImported, an Unavailable) rather than show an empty inventory.
- apply(op, ...): one conn.change() (so the audit trail records who, from where, what and why)
  that takes the advisory lock 'inventory', reads the snapshot inside the transaction (the
  cached one while the revision hasn't moved), checks expected_revision only when given, runs
  the op on its own copy of the records (changes.detach; the op makes its own checks, such as a
  page's sha256), settles and checks the result as the files backend does (changes.prepare:
  the same normalising, the same refusals), writes the difference, bumps the revision and reads
  the result back (its new rows' ids included). An op that changes nothing leaves no change set.
  The rows a model maps to are table_rows.tables() (kept with the cached snapshot, so a write
  works out only the new snapshot's): rows with an identity (collection cards by printing, token
  and watchlist rows by id, status rows by file, products, orders and components by id) are
  inserted, updated or deleted; a product's items and a payload's rows are replaced as a whole
  when they differ (they change only when an order is added, split or edited). Every statement
  of one kind goes in one executemany batch, so a 20,000-row import holds the lock for seconds
  at most, not one round trip per row.
- write_model(inv, ...): the bulk writer (the one-time imports used it until phase 5b retired
  them; the tests load their fixtures with it), the whole snapshot in one change set, refusing
  what the database can't hold exactly (representable() lists why) and a database that already
  has an inventory unless replace=True (every inventory row deleted in the same change set).
- Errors, timeouts and the circuit breaker are the state store's (lib/state/pg.py:
  mapped_error, BREAKER, REQUEST_OPTIONS): one database, one breaker.
- Phase 4's deck parts (every space's deck texts, accessories.csv, its pictures) are migration
  0006's tables (pg_decks.py; the phase 4 design's R1, R2, R4 and R10). They're a part of the
  snapshot with its own revision (decks_revision, its own counter row) and its own cache: a load
  asks both counters in one transaction, reads again only the part whose counter moved (deck
  texts only when the decks part reloads; picture bytes never: image(name) fetches one), and
  gives the same Inventory object while neither has moved. apply() writes the decks part's
  difference with the inventory's in the same change, and bumps each counter only when its own
  rows changed (a deck save never moves the inventory's revision, so receipt previews and
  expected_revision stay valid; an inventory write whose deck-table refresh changed a deck
  bumps both). A saved text adds a deck_revision naming the change set. While the database
  holds no decks (no 0006 tables, or no decks_revision row: a fresh database, or a bad
  restore), the snapshot's decks part is empty (no decks, accessories or pictures; never read
  from files), and an operation that would change it refuses (Unavailable: DECK_SAVES_PAUSED);
  saves_decks() says which (the in-op table refresh asks it, so a receipt still goes ahead, its
  tables left alone). The database keeps LF deck texts: an operation giving a text with a
  carriage return is refused (the files backend keeps a CRLF file's exact bytes). While the
  database can't be reached, load() serves the last good snapshot with the decks part it had;
  once the database has 0006's tables, a stale snapshot without a decks part is refused
  (Unavailable).
- The deck history: deck_revisions(deck_id), deck_revision(deck_id, n) and last_revision(deck_id)
  (pg_decks.revisions/revision/last: model.DeckRevision), [] or None while it holds no decks.
- write_model(inv, ..., decks=True) imports the deck parts with the inventory, in its change
  set; write_decks() puts them into a database whose inventory is there already, with a given
  history of revisions when one is given (pg_decks.write_all).

psycopg is imported only through decklab.db.conn, inside the methods; constructing a
PgInventory activates the repo's venv (lib/venv.py), so it works from any entry point.
"""
import csv
import dataclasses
import hashlib
import io
import json
import threading
from collections import defaultdict
from datetime import datetime

from decklab.db import conn as db, space_members
from decklab.lib.state import Actor, Conflict, Invalid, Unavailable
from decklab.lib.state import pg as state_pg

from . import DECK_SAVES_PAUSED, Summary, changes, files, paths, pg_decks, pg_aliases, pg_check_links, rules
from .model import QUEUE_FIELDS, Component, ImageMeta, ImportInfo, Order
# The snapshot-as-rows code is shared with the files backend (table_rows.py); these names stay
# here for the callers and tests that use them as pg's.
from .table_rows import (CARD_COLUMNS, COMPONENT_COLUMNS, ITEM_COLUMNS, ITEM_TABLES,  # noqa: F401
                         ORDER_COLUMNS, PAYLOAD_FIELDS, STATUS_COLUMNS, TOKEN_COLUMNS, WATCH_COLUMNS,
                         JsonColumn, Unrepresentable, deck_tables, reasons, representable, tables)

LOCK_KEY = "inventory"                       # the advisory lock every inventory write takes
NOT_IMPORTED = ("the database holds no inventory: on a new install, run python -m decklab.db setup, which "
                "starts an empty one; otherwise restore the newest backup (a decklab-*.dump from the "
                "backup folder or decklab/data/backups/, with pg_restore), after python -m decklab.db "
                "migrate if migrations are pending")
STALE = "inventory as of {when}: the database isn't reachable"
STALE_NO_DECKS = ("the database isn't reachable, and the decks weren't loaded from it before it went "
                  "away: try again once it's back")
DECKS_ALREADY = ("the database already holds the decks; import them again only with --replace-decks (which "
                 "puts the new set in place of the current one, keeping every deck's history)")
# The decks part of a database that holds no decks: what the files backend reads from no files.
EMPTY_DECKS = files.build({})
ALREADY = ("the database already holds an inventory; import it again only with "
           "--replace-inventory (which deletes every inventory row first, in the same change set)")
# Every inventory table, children before parents (the order to delete in; inserts go the other
# way). collection_import_content goes with its collection_import (on delete cascade) and
# inventory_revision isn't audited: both are handled on their own.
INVENTORY_TABLES = ("order_card_item", "order_token_item", "order_component", "purchase_order",
                    "product_item", "product", "product_status", "collection_card", "collection_import",
                    "token_card", "watchlist_item")



class NotImported(Unavailable):
    """The database has no inventory yet (no inventory_revision row)."""


class _Unchanged(Exception):
    def __init__(self, result):
        super().__init__()
        self.result = result


# ------------------------------------------------------------------ table rows as a snapshot

def _render(columns, rows):
    """(bytes, [the line each row starts on]) of a CSV with this header and these rows, as the
    files backend writes it."""
    chunks, lines, line = [], [], 2
    head = io.StringIO()
    csv.writer(head, lineterminator="\n").writerow(columns)
    chunks.append(head.getvalue())
    for cells in rows:
        out = io.StringIO()
        csv.writer(out, lineterminator="\n").writerow(["" if c is None else str(c) for c in cells])
        text = out.getvalue()
        lines.append(line)
        line += text.count("\n")
        chunks.append(text)
    return "".join(chunks).encode("utf-8"), lines


SELECTS = {
    "collection_card": "select space_id, set_code, collector_number, finish, name, quantity, condition, language, "
                       "notes from collection_card",
    "collection_import": "select i.space_id, i.file_name, i.size, i.sha256, i.imported_at, origin.name "
                         "from collection_import i left join lateral ("
                         "select coalesce(p.name, cs.actor) as name from audit.row_change rc "
                         "join audit.change_set cs on cs.id = rc.change_set_id "
                         "left join profile p on p.id = cs.actor "
                         "where rc.table_name = 'collection_import' and rc.op = 'INSERT' "
                         "and rc.row_key = jsonb_build_object('id', i.id) "
                         "order by rc.id limit 1) origin on true",
    "token_card": f"select id, space_id, position, {', '.join(TOKEN_COLUMNS)} from token_card",
    "watchlist_item": f"select id, position, {', '.join(WATCH_COLUMNS)} from watchlist_item",
    "product": "select stem, name, format, columns from product",
    "product_item": "select product_stem, position, cells from product_item",
    "product_status": f"select file, {', '.join(STATUS_COLUMNS)} from product_status",
    "purchase_order": f"select id, {', '.join(ORDER_COLUMNS)} from purchase_order",
    "order_component": f"select order_id, id, {', '.join(COMPONENT_COLUMNS)} from order_component",
    "order_card_item": f"select order_id, component_id, position, {', '.join(CARD_COLUMNS)} from order_card_item",
    "order_token_item": f"select order_id, component_id, position, {', '.join(TOKEN_COLUMNS)} from order_token_item",
}


def _select(c):
    columns = _status_columns(c)
    status = "select file, " + ", ".join(column if column in columns else "''::text as token_cards"
                                         for column in STATUS_COLUMNS) + " from product_status"
    component = pg_check_links.select(c)
    return {table: c.execute(status if table == "product_status" else component if table == "order_component" else query).fetchall()
            for table, query in SELECTS.items()}


def _status_columns(c):
    """Probe the actual column, without caching absence across a later migration."""
    ready = c.execute("select exists(select 1 from pg_catalog.pg_attribute "
                      "where attrelid=to_regclass('public.product_status') and attname='token_cards' "
                      "and not attisdropped)").fetchone()[0]
    return STATUS_COLUMNS if ready else tuple(column for column in STATUS_COLUMNS if column != "token_cards")


def _status_tables(t, columns):
    """Old schemas can represent blank unknown packing, never discard a recorded value."""
    if columns == STATUS_COLUMNS:
        return t
    token_at = STATUS_COLUMNS.index("token_cards")
    if any(row[token_at] for row in t["product_status"].values()):
        raise Invalid("Product packed token cards require migration 0014. Run the database migrations first.")
    indices = [STATUS_COLUMNS.index(column) for column in columns]
    return {**t, "product_status": {key: tuple(row[index] for index in indices)
                                    for key, row in t["product_status"].items()}}


def snapshot(data, revision):
    """The Inventory the rows of every table hold (data: {table: rows} as _select reads them)."""
    out = {}
    cards = defaultdict(list)
    for space, set_code, number, finish, name, qty, condition, language, notes in data["collection_card"]:
        cards[space].append({"name": name, "set": set_code, "collector_number": number, "finish": finish,
                             "quantity": str(qty), "condition": condition, "language": language, "notes": notes})
    for space, rows in cards.items():
        rows.sort(key=rules.sort_key)
        out[paths.collection(space)] = _render(rules.FIELDS, [[r[k] for k in rules.FIELDS] for r in rows])[0]
    token_ids = {}
    tokens = defaultdict(list)
    for row in data["token_card"]:
        tokens[row[1]].append(row)
    for space, rows in tokens.items():
        rows.sort(key=lambda r: (r[2], r[0]))
        out[paths.tokens(space)], lines = _render(rules.TOKEN_FIELDS, [r[3:] for r in rows])
        token_ids[space] = dict(zip(lines, (r[0] for r in rows)))
    watch = sorted(data["watchlist_item"], key=lambda r: (r[1], r[0]))
    out[paths.WATCHLIST], lines = _render(QUEUE_FIELDS, [r[2:] for r in watch])
    watch_ids = dict(zip(lines, (r[0] for r in watch)))
    status = sorted(data["product_status"], key=lambda r: (r[1], r[0]))
    out[paths.STATUS] = _render(rules.STATUS_FIELDS, [(r[0], *r[2:]) for r in status])[0]
    items = defaultdict(list)
    for stem, position, cells in data["product_item"]:
        items[stem].append((position, cells))
    names = {}
    for stem, name, fmt, columns in data["product"]:
        names[stem] = (name, fmt)
        out[paths.product(stem)] = _render(columns, [cells for _, cells in sorted(items[stem])])[0]
    payload_rows = defaultdict(list)
    for table in ITEM_TABLES.values():
        for row in data[table]:
            payload_rows[(row[0], row[1])].append((row[2], row[3:]))
    components = defaultdict(list)
    for row in data["order_component"]:
        components[row[0]].append(row)
    for oid, seller, ordered_on, sources, notes, audit_notes in data["purchase_order"]:
        built = []
        for row in sorted(components[oid], key=lambda r: r[2]):
            _, cid, _, kind, file_name, status_, received_on, checks, verified, _ = row[:10]
            metadata = row[10] if len(row) > 10 else None
            built.append(Component.build(cid, kind, file_name, status_, received_on, checks, verified, metadata))
            if kind != "product":
                rows = [cells for _, cells in sorted(payload_rows[(oid, cid)], key=lambda r: r[0])]
                out[paths.payload(kind, status_, file_name)] = _render(PAYLOAD_FIELDS[kind], rows)[0]
        order = Order.build(oid, seller, ordered_on, sources, notes, built, audit_notes)
        out[paths.record(oid)] = rules.json_bytes(order.data)
    inv = files.build(out, revision=str(revision), backend="db")
    imports = defaultdict(list)
    for space, file_name, size, digest, at, actor in data["collection_import"]:
        imports[space].append(ImportInfo(file_name, size, digest, at.isoformat() if at else None, actor))
    return inv.replace(
        imports={space: tuple(sorted(found, key=lambda i: i.name)) for space, found in sorted(imports.items())},
        products=tuple(dataclasses.replace(p, name=names[p.stem][0], format=names[p.stem][1]) for p in inv.products),
        tokens={space: dataclasses.replace(sheet, rows=tuple(
            dataclasses.replace(row, id=token_ids.get(space, {}).get(row.line, 0)) for row in sheet.rows))
            for space, sheet in inv.tokens.items()},
        watchlist=dataclasses.replace(inv.watchlist, rows=tuple(
            dataclasses.replace(row, id=watch_ids.get(row.line, 0)) for row in inv.watchlist.rows)))


# ------------------------------------------------------------------ writing rows

STEP = 1024         # the gap between token and watchlist rows' positions, so most edits move none


def _positions(ids, stored):
    """Positions for rows in this order. ids: each row's id (0 for a new one); stored: {id:
    position} for the rows as the database has them. The longest run of rows still in their
    stored order keeps its positions, so removing a row or editing one moves no other; the rest
    get positions spread between their neighbours', or, when there's no room left, every row is
    numbered afresh, STEP apart."""
    import bisect
    seq = [(i, stored[rid]) for i, rid in enumerate(ids) if rid in stored]
    tails, at, back = [], [], {}
    for k, (_, position) in enumerate(seq):
        j = bisect.bisect_left(tails, position)
        if j == len(tails):
            tails.append(position)
            at.append(k)
        else:
            tails[j], at[j] = position, k
        back[k] = at[j - 1] if j else None
    keep, k = set(), (at[-1] if at else None)
    while k is not None:
        keep.add(seq[k][0])
        k = back[k]
    out = [stored[rid] if i in keep else None for i, rid in enumerate(ids)]
    i, n = 0, len(ids)
    while i < n:
        if out[i] is not None:
            i += 1
            continue
        j = i
        while j < n and out[j] is None:
            j += 1
        low = out[i - 1] if i else 0
        high = out[j] if j < n else low + (j - i + 1) * STEP
        if high - low - 1 < j - i:
            return [(k + 1) * STEP for k in range(n)]
        step = (high - low) // (j - i + 1)
        for k in range(j - i):
            out[i + k] = low + step * (k + 1)
        i = j
    return out


def _insert(cur, table, columns, rows):
    if rows:
        cur.executemany(f"insert into {table} ({', '.join(columns)}) values ({', '.join(['%s'] * len(columns))})",
                        rows)


def _db(value):
    """A Python value as psycopg should send it (tuples as arrays)."""
    if isinstance(value, JsonColumn):
        from psycopg.types.json import Jsonb
        return Jsonb(value.value)
    return list(value) if isinstance(value, tuple) else value


def _keyed_rows(table, t, status_columns=STATUS_COLUMNS, component_columns=COMPONENT_COLUMNS):
    """(key columns, value columns, {key: values}) of one of t's keyed tables (tables()' shape)."""
    return {
        "collection_card": (("space_id", "set_code", "collector_number", "finish"),
                            ("name", "quantity", "condition", "language", "notes")),
        "product": (("stem",), ("name", "format", "columns")),
        "product_status": (("file",), status_columns),
        "purchase_order": (("id",), ORDER_COLUMNS),
        "order_component": (("order_id", "id"), component_columns),
    }[table] + (t[table],)


# The keyed tables, parents before children (product before the components naming it).
PARENTS_FIRST = ("product", "product_status", "purchase_order", "order_component", "collection_card")


def _plain_key(key):
    return key if isinstance(key, tuple) else (key,)


def _write_all(cur, t):
    """Insert every row of t (tables()' shape) into empty tables, parents first."""
    status_columns = _status_columns(cur)
    t = _status_tables(t, status_columns)  # Refuse unsupported data before any inventory DML.
    component_columns = pg_check_links.columns(cur)
    t = pg_check_links.compatible(t, component_columns)
    for table in PARENTS_FIRST:
        keys, values, rows = _keyed_rows(table, t, status_columns, component_columns)
        _insert(cur, table, keys + values, [(*_plain_key(k), *map(_db, v)) for k, v in rows.items()])
    _insert(cur, "product_item", ("product_stem", "position", "cells"),
            [(stem, n, list(cells)) for stem, found in t["product_item"].items() for n, cells in enumerate(found)])
    for table, columns in ITEM_COLUMNS.items():
        _insert(cur, table, ("order_id", "component_id", "position", *columns),
                [(*key, n, *row) for key, found in t[table].items() for n, row in enumerate(found)])
    numbered = defaultdict(int)
    tokens = []
    for row in t["token_card"]:
        numbered[row[1]] += 1
        tokens.append((row[1], numbered[row[1]] * STEP, *row[2:]))
    _insert(cur, "token_card", ("space_id", "position", *TOKEN_COLUMNS), tokens)
    _insert(cur, "watchlist_item", ("position", *WATCH_COLUMNS),
            [((n + 1) * STEP, *row[1:]) for n, row in enumerate(t["watchlist_item"])])


def _diff(cur, old, new):
    """Write the difference between two tables() results, each kind of statement in one
    executemany batch (deletes children first, then inserts and updates parents first); returns
    how many rows it wrote."""
    status_columns = _status_columns(cur)
    new = _status_tables(new, status_columns)  # Preflight before deletes, inserts or updates.
    old = _status_tables(old, status_columns)
    component_columns = pg_check_links.columns(cur)
    new, old = (pg_check_links.compatible(t, component_columns) for t in (new, old))
    count = 0
    pending = []

    def add(sql, params):
        if params:
            pending.append((sql, params))

    def flush():
        nonlocal count
        for sql, params in pending:
            cur.executemany(sql, params)
            count += len(params)
        pending.clear()

    def where(keys):
        return " and ".join(f"{k} = %s" for k in keys)

    def insert(table, names):
        return f"insert into {table} ({', '.join(names)}) values ({', '.join(['%s'] * len(names))})"

    # Deletes, children first: whole item lists that changed, then rows gone.
    for table in ITEM_COLUMNS:
        add(f"delete from {table} where order_id = %s and component_id = %s",
            [key for key, found in old[table].items() if found != new[table].get(key)])
    add("delete from product_item where product_stem = %s",
        [(stem,) for stem, found in old["product_item"].items() if found != new["product_item"].get(stem)])
    for table in reversed(PARENTS_FIRST):
        keys, _, rows = _keyed_rows(table, old, status_columns, component_columns)
        add(f"delete from {table} where {where(keys)}", [_plain_key(key) for key in rows.keys() - new[table].keys()])
    for table in ("token_card", "watchlist_item"):
        kept = {r[0] for r in new[table] if r[0]}
        add(f"delete from {table} where id = %s", [(row[0],) for row in old[table] if row[0] not in kept])
    # Inserts and updates, parents first.
    for table in PARENTS_FIRST:
        keys, values, rows = _keyed_rows(table, new, status_columns, component_columns)
        before = old[table]
        add(insert(table, keys + values),
            [(*_plain_key(key), *map(_db, value)) for key, value in rows.items() if key not in before])
        add(f"update {table} set {', '.join(f'{v} = %s' for v in values)} where {where(keys)}",
            [(*map(_db, value), *_plain_key(key)) for key, value in rows.items()
             if key in before and before[key] != value])
    add(insert("product_item", ("product_stem", "position", "cells")),
        [(stem, n, list(cells)) for stem, found in new["product_item"].items()
         if old["product_item"].get(stem) != found for n, cells in enumerate(found)])
    for table, columns in ITEM_COLUMNS.items():
        add(insert(table, ("order_id", "component_id", "position", *columns)),
            [(*key, n, *row) for key, found in new[table].items() if old[table].get(key) != found
             for n, row in enumerate(found)])
    flush()
    # Token and watchlist rows by id, keeping the stored positions of rows that didn't move.
    for table, columns, grouped in (("token_card", TOKEN_COLUMNS, True), ("watchlist_item", WATCH_COLUMNS, False)):
        cur.execute(f"select id, position{', space_id' if grouped else ''} from {table}")
        stored = {r[0]: (r[1], r[2] if grouped else None) for r in cur.fetchall()}
        before = {r[0]: r[1:] for r in old[table]}
        groups, seen = defaultdict(list), set()
        for row in new[table]:
            rid = row[0] if row[0] in before and row[0] not in seen else 0
            seen.add(rid)
            groups[row[1] if grouped else None].append((rid, row[1:]))
        names = ("space_id", "position", *columns) if grouped else ("position", *columns)
        inserts, updates = [], []
        for group, rows in groups.items():
            positions = _positions([rid for rid, _ in rows],
                                   {rid: stored[rid][0] for rid, _ in rows if rid and stored[rid][1] == group})
            for (rid, value), position in zip(rows, positions):
                params = (value[0], position, *value[1:]) if grouped else (position, *value)
                if not rid:
                    inserts.append(params)
                elif before[rid] != value or stored[rid][0] != position:
                    updates.append((*params, rid))
        add(insert(table, names), inserts)
        add(f"update {table} set {', '.join(f'{c} = %s' for c in names)} where id = %s", updates)
        flush()
    return count


def _add_imports(cur, imports):
    """Keep raw import files ([(space, file name, bytes)]); ValueError for one already kept."""
    for space, name, data in imports:
        cur.execute("select 1 from collection_import where space_id = %s and file_name = %s", (space, name))
        if cur.fetchone():
            raise ValueError(f"{paths.imports_dir(space)}/{name} already exists")
        cur.execute("insert into collection_import (space_id, file_name, size, sha256) values (%s, %s, %s, %s) "
                    "returning id", (space, name, len(data), hashlib.sha256(data).hexdigest()))
        cur.execute("insert into collection_import_content (import_id, content) values (%s, %s)",
                    (cur.fetchone()[0], bytes(data)))
    return len(imports)


def _take_lock(cur):
    cur.execute("select pg_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))


# ------------------------------------------------------------------ the backend

class PgInventory:
    """The inventory in the database (see the module docstring). dbname: the database to use
    (default: conn.settings()'s, read at each call, so the tests' DECKLAB_DB_NAME reaches it);
    timeout: seconds to connect; breaker: the state store's by default."""

    name = "db"

    def __init__(self, dbname=None, timeout=state_pg.REQUEST_TIMEOUT, breaker=None):
        from decklab.lib import venv
        venv.activate()
        self.dbname = dbname
        self.timeout = timeout
        self.breaker = breaker or state_pg.BREAKER
        self._lock = threading.Lock()
        self._cache = None              # (key, Inventory, when loaded)
        self._rows = None               # (Inventory, its tables()): the last snapshot written from
        self._empty = None              # (database snapshot, it with an empty decks part)
        self._decks = None              # (decks key, the decks part's fields): the cached decks part
        self._joined = None             # (inventory snapshot, decks key, the two as one Inventory)
        self._migrated = False          # True once the database is seen to have 0006's tables
        self._applying = threading.local()  # .saves: whether the decks part saves, inside apply()

    def __repr__(self):
        return f"PgInventory({self.dbname or db.settings()['name']!r})"

    # -------------------------------------------------------- plumbing

    def reachable(self):
        return not self.breaker.is_open()

    def _tables(self, inv):
        """tables(inv), remembered for the last snapshot asked about (the cached one, as a rule)."""
        with self._lock:
            if self._rows is not None and self._rows[0] is inv:
                return self._rows[1]
        rows = tables(inv)
        with self._lock:
            self._rows = (inv, rows)
        return rows

    def _no_decks(self, inv):
        """inv with an empty decks part, while the database holds no decks (see the module
        docstring). The same object while inv is."""
        with self._lock:
            kept = self._empty
        if kept is not None and kept[0] is inv:
            return kept[1]
        out = inv.replace(decks=EMPTY_DECKS.decks, accessories=EMPTY_DECKS.accessories,
                          accessory_images=EMPTY_DECKS.accessory_images, decks_revision=EMPTY_DECKS.decks_revision,
                          deck_aliases={}, aliases_ready=False, deck_history_ids=())
        with self._lock:
            self._empty = (inv, out)
        return out

    def _decks_key(self, c):
        """The decks part's cache key the connection sees now, or None while the database doesn't
        hold the decks (no 0006 tables, or never imported: pg_decks.decks_key)."""
        name = self.dbname or db.settings()["name"]
        if not self._migrated:
            if not pg_decks.migrated(c):
                return None
            self._migrated = True
        row = c.execute("select revision, imported_at from decks_revision").fetchone()
        return None if row is None else (name, row[1], row[0], pg_aliases.ready(c))

    def _read_decks(self, c, remember=True):
        """(key, the decks part's fields) the connection sees (the cached part while its revision
        hasn't moved), or (None, None) while the database doesn't hold the decks."""
        key = self._decks_key(c)
        if key is None:
            return None, None
        with self._lock:
            if self._decks is not None and self._decks[0] == key:
                return key, self._decks[1]
        part = pg_decks.deck_part(pg_decks.select(c), key[2])
        if remember:
            with self._lock:
                self._decks = (key, part)
        return key, part

    def _join(self, inv, key, part):
        """inv (the inventory part) with the decks part: the database's (key, part), or an
        empty one when key is None. The same object while neither part has changed."""
        if key is None:
            return self._no_decks(inv)
        with self._lock:
            kept = self._joined
        if kept is not None and kept[0] is inv and kept[1] == key:
            return kept[2]
        out = inv.replace(**part)
        with self._lock:
            self._joined = (inv, key, out)
        return out

    def image(self, name, sha256=None):
        """The bytes of the picture with this file name, or None when there's none (or, given
        sha256, when its bytes aren't those: the snapshot a page read is older or newer). None
        while the database doesn't hold the decks."""
        def work(c):
            if self._decks_key(c) is None:
                return None
            found = pg_decks.image(c, name)
            return None if found is None else found[0]
        data = self._call(work)
        if data is not None and sha256 is not None and hashlib.sha256(data).hexdigest() != sha256:
            return None
        return data

    def saves_decks(self):
        """Whether an operation may change the deck parts now: inside apply(), whether the
        transaction's database holds the decks; otherwise asked (False when it can't be reached)."""
        saves = getattr(self._applying, "saves", None)
        if saves is not None:
            return saves
        try:
            return self._call(self._decks_key) is not None
        except Unavailable:
            return False

    def _history(self, work, empty):
        """work(connection) on the deck history, or empty while the database doesn't hold the decks."""
        return self._call(lambda c: empty if self._decks_key(c) is None else work(c))

    def deck_revisions(self, deck_id):
        """[DeckRevision] of a deck's history, newest first, without texts (the module docstring)."""
        return self._history(lambda c: pg_decks.revisions(c, deck_id), [])

    def deck_revision(self, deck_id, number):
        """The DeckRevision number of a deck with its text, or None."""
        return self._history(lambda c: pg_decks.revision(c, deck_id, int(number)), None)

    def deck_revisions_with_text(self, deck_id, limit):
        """The newest limit DeckRevisions of a deck with their texts, newest first: one connection, one query."""
        return self._history(lambda c: pg_decks.revisions_with_text(c, deck_id, int(limit)), [])

    def last_revision(self, deck_id):
        """The newest DeckRevision of a deck, without its text, or None."""
        return self._history(lambda c: pg_decks.last(c, deck_id), None)

    def deck_edited(self):
        """{deck id: when it was last edited} (inventory.deck_edited)."""
        return self._history(pg_decks.edited, {})

    def clear_cache(self):
        with self._lock:
            self._cache = None
            self._decks = None
            self._joined = None

    def _down(self, reason):
        self.breaker.trip(reason)
        return Unavailable(reason)

    def _call(self, work):
        """work(connection) on a new autocommit app-role connection, with errors mapped to
        state's (lib/state/pg.py's mapped_error)."""
        self.breaker.check()
        try:
            psycopg = db._psycopg()
            c = db.connect("app", dbname=self.dbname, autocommit=True, timeout=self.timeout,
                           options=state_pg.REQUEST_OPTIONS)
        except db.DbUnavailable as e:
            raise self._down(str(e)) from None
        try:
            with c:
                return work(c)
        except psycopg.Error as e:
            raise state_pg.mapped_error(psycopg, e, self._down) from None

    def _key(self, c):
        """The cache key of the inventory the connection sees now; NotImported without one."""
        row = c.execute("select revision, imported_at from inventory_revision").fetchone()
        if row is None:
            raise NotImported(NOT_IMPORTED)
        return (self.dbname or db.settings()["name"], row[1], row[0])

    def _read(self, c, remember=True):
        """The snapshot the connection sees (the cached one while the revision hasn't moved)."""
        key = self._key(c)
        with self._lock:
            if self._cache is not None and self._cache[0] == key:
                return self._cache[1]
        inv = snapshot(_select(c), key[2])
        if remember:
            with self._lock:
                self._cache = (key, inv, datetime.now())
        return inv

    # -------------------------------------------------------- reading

    def load(self, conn=None):
        """The inventory now. conn: read on this connection, in the caller's transaction (the
        export reads every table in one snapshot), never serving a stale copy. Otherwise, when
        the database can't be reached, the last good snapshot marked stale; NotImported when
        there's no inventory in the database."""
        if conn is not None:
            return self._join(self._read(conn, remember=False), *self._read_decks(conn, remember=False))

        def work(c):
            with c.transaction():
                c.execute("set transaction isolation level repeatable read, read only")
                return (self._read(c), *self._read_decks(c))
        try:
            return self._join(*self._call(work))
        except NotImported:
            raise
        except Unavailable:
            with self._lock:
                cached, decks, migrated = self._cache, self._decks, self._migrated
            if cached is None:
                raise
            if decks is None and migrated:
                raise Unavailable(STALE_NO_DECKS) from None     # never a stale snapshot without its decks
            stale = cached[1].replace(stale=STALE.format(when=cached[2].strftime("%Y-%m-%d %H:%M")))
            return self._join(stale, *(decks or (None, None)))

    def revision(self):
        """The inventory's revision now, as text (one query)."""
        return str(self._call(lambda c: self._key(c)[2]))

    def decks_revision(self):
        """The decks part's revision now, as text (the empty part's while the database doesn't
        hold the decks)."""
        key = self._call(self._decks_key)
        return EMPTY_DECKS.decks_revision if key is None else str(key[2])

    def last_change(self, table, match):
        """{at (an aware datetime), actor (its id), name (the profile's name, else the actor's
        id), source, message} of the newest change set that touched a row of table whose
        recorded row (before or after) holds match ({column: value}, compared as JSON), or None:
        who last changed something, for a page's "changed after you opened it" answer (the
        files backend asks git instead)."""
        import json

        def work(c):
            found = c.execute(
                "select cs.at, cs.actor, cs.source, cs.message, p.name from audit.change_set cs "
                "left join profile p on p.id = cs.actor where cs.id = ("
                "  select max(change_set_id) from audit.row_change"
                "  where table_name = %s and (after @> %s::jsonb or before @> %s::jsonb))",
                (table, json.dumps(match), json.dumps(match))).fetchone()
            if found is None:
                return None
            at, actor, source, message, name = found
            return {"at": at, "actor": actor, "name": name or actor, "source": source, "message": message}
        return self._call(work)

    def undo_audit(self, change_id):
        """Internal original rows, never Activity's filtered/capped projection.

        Two rows suffice to prove a change is outside the single-row Undo slice.
        During apply use this transaction's already-locked connection, not a second
        snapshot that could race the inventory being changed.
        """
        def work(c):
            return [{"id": rid, "table": table, "op": op, "key": key, "before": old, "after": new}
                    for rid, table, op, key, old, new in c.execute(
                        "select id,table_name,op,row_key,before,after from audit.row_change "
                        "where change_set_id=%s order by id limit 2", (change_id,)).fetchall()]
        applying = getattr(self._applying, "connection", None)
        return work(applying) if applying is not None else self._call(work)

    def undo_latest(self, table, key):
        """Latest *audit row* touching this key. Change-set IDs are allocated before
        the inventory lock and therefore cannot establish write order."""
        if table not in ("collection_card", "token_card", "accessory"):
            raise Invalid("That row does not support Undo.")
        def work(c):
            found = c.execute("select id from audit.row_change where table_name=%s and row_key=%s::jsonb "
                              "order by id desc limit 1", (table, json.dumps(key))).fetchone()
            return found[0] if found is not None else None
        applying = getattr(self._applying, "connection", None)
        return work(applying) if applying is not None else self._call(work)

    def accessory_undo_review(self, change_id, owners):
        """One locked accessory text review, with no audit change for the read."""
        from . import accessory_undo
        def work(c):
            with c.transaction():
                _take_lock(c)
                space_members.admit(c, space_ids={"home"}, lock=False)
                snapshot = self.load(conn=c)
                previous = getattr(self._applying, "connection", None)
                self._applying.connection = c
                try:
                    return accessory_undo.review(change_id, owners, snapshot, self)[0]
                finally:
                    self._applying.connection = previous
        return self._call(work)

    def accessory_undo_apply(self, change_id, owners, expect, actor, message, reason=..., confirm_restore=..., confirm_stock=..., confirm_owner=...):
        from .accessory_undo import MetadataRestore, source_record, removal_reason
        canonical = None
        if reason is not ... or confirm_restore is not ... or confirm_stock is not ... or confirm_owner is not ...:
            # Audit rows are immutable. Establish complete source ownership before
            # validating the public reason; all mutable facts are rechecked in apply.
            source = source_record(self.undo_audit(change_id), owners)
            if reason is not ...:
                if source["op"] != "INSERT":
                    raise Invalid("Only removing an added accessory takes a removal reason.")
                canonical = removal_reason(reason)
            if confirm_restore is not ... and (source["op"] != "DELETE" or confirm_restore is not True):
                raise Invalid("Confirm only the entire historical deleted accessory record.")
            if confirm_stock is not ... and (source["op"] != "UPDATE" or confirm_stock is not True
                    or source["before"].get("quantity") == source["after"].get("quantity")):
                raise Invalid("Confirm only the entire restored accessory count.")
            if confirm_owner is not ... and (source["op"] != "UPDATE" or confirm_owner is not True
                    or source["before"].get("owner") == source["after"].get("owner")):
                raise Invalid("Confirm only restored accessory sharing.")
        _, summary = self.apply(MetadataRestore(change_id, owners, expect, store=self,
            reason=canonical if reason is not ... else ..., confirm_restore=confirm_restore, confirm_stock=confirm_stock,
            confirm_owner=confirm_owner), actor, message,
                                reason=canonical)
        return summary.extra["accessory_undo"]

    def undo_audit_batch(self, change_id):
        """Unfiltered bounded original rows; the 51st row refuses a 50-row batch.

        Keep undo_audit's two-row single-source contract unchanged. No Activity
        projection or SQL ownership filter can make a mixed source look complete.
        """
        def work(c):
            return [{"id": rid, "table": table, "op": op, "key": key, "before": old, "after": new}
                    for rid, table, op, key, old, new in c.execute(
                        "select id,table_name,op,row_key,before,after from audit.row_change "
                        "where change_set_id=%s order by id limit 51", (change_id,)).fetchall()]
        applying = getattr(self._applying, "connection", None)
        return work(applying) if applying is not None else self._call(work)

    def undo_token_positions(self, space):
        """Persisted own-space token layout, on Undo's applying connection when set."""
        def work(c):
            return [{"id": rid, "position": position} for rid, position in c.execute(
                "select id,position from token_card where space_id=%s order by position,id", (space,)).fetchall()]
        applying = getattr(self._applying, "connection", None)
        return work(applying) if applying is not None else self._call(work)

    def supports_check_links(self):
        def work(c):
            return "check_links" in pg_check_links.columns(c)
        applying = getattr(self._applying, "connection", None)
        return work(applying) if applying is not None else self._call(work)

    # -------------------------------------------------------- writing

    def apply(self, op, actor, message, reason=None, expected_revision=None):
        """Run op on the inventory as it is inside one change and write what it changed
        (inventory.apply's contract; see the module docstring). Returns (the snapshot after,
        the op's Summary)."""
        if not isinstance(actor, Actor):
            raise TypeError("apply needs a state.Actor")
        result = {}

        def work(c):
            try:
                with db.change(actor.id, actor.source, message, reason, conn=c, via=actor.via) as (cur, change_set):
                    _take_lock(cur)
                    space_members.admit(cur, actor=actor, lock=False)
                    stored = self._read(c)
                    deck_key, part = self._read_decks(c)
                    before = self._join(stored, deck_key, part)
                    if expected_revision is not None and str(expected_revision) != before.revision:
                        raise Conflict(files.MOVED_MESSAGE)
                    self._applying.saves = deck_key is not None
                    previous_connection = getattr(self._applying, "connection", None)
                    self._applying.connection = c
                    try:
                        after, summary = op.run(changes.detach(before))
                    finally:
                        self._applying.saves = None
                        self._applying.connection = previous_connection
                    after = changes.prepare(before, after)
                    decks_changed = any(paths.is_deck_part(rel) for rel in changes.changed(before, after))
                    if decks_changed and deck_key is None:
                        raise Unavailable(DECK_SAVES_PAUSED)
                    imports = list((summary.extra or {}).get("imports", ()))
                    touched = {paths.space_of(rel) for rel in changes.changed_paths(before, after)}
                    touched.update(item[0] for item in imports)
                    space_members.admit(cur, space_ids=touched - {None}, lock=False)
                    try:
                        if deck_key is None:
                            old, new = self._tables(stored), tables(pg_decks.without_deck_parts(after))
                        else:
                            old, new = self._tables(before), tables(after)
                    except Unrepresentable as e:
                        raise Invalid(changes.SAVE_REFUSED.format(why=e.reasons[0])) from None
                    if decks_changed:
                        for deck_id, text in new["deck_text"].items():
                            if "\r" in text and old["deck_text"].get(deck_id) != text:
                                raise Invalid(changes.SAVE_REFUSED.format(why=f"{deck_id}: {pg_decks.CR_TEXT}"))
                    changed = _diff(cur, old, new) + _add_imports(cur, imports)
                    deck_rows = pg_decks.write_diff(cur, old, new, after, change_set, actor.id, message,
                                                   before=before, renamed=(summary.extra or {}).get("renamed")) \
                        if decks_changed else 0
                    if not changed and not deck_rows:
                        raise _Unchanged((before, summary))
                    inv_part = stored
                    if changed:
                        cur.execute("update inventory_revision set revision = revision + 1")
                        result["key"] = self._key(c)
                        result["inv"] = inv_part = snapshot(_select(c), result["key"][2])
                    if deck_rows:
                        cur.execute("update decks_revision set revision = revision + 1")
                        deck_key = self._decks_key(c)
                        part = pg_decks.deck_part(pg_decks.select(c), deck_key[2])
                        result["decks"] = (deck_key, part)
                    # This trusted accessory operation verifies actual SQL/audit effects
                    # before commit, without changing existing inventory Undo protocols.
                    from .accessory_undo import MetadataRestore
                    if isinstance(op, MetadataRestore):
                        # A failed verifier rolls this transaction back. Never cache its
                        # provisional revision: a later writer can reuse that counter.
                        saved = inv_part.replace(**part) if deck_key is not None else pg_decks.without_deck_parts(inv_part)
                        actual = [{"id": rid, "table": table, "op": action, "key": key, "before": old, "after": new}
                                  for rid, table, action, key, old, new in cur.execute(
                                      "select id,table_name,op,row_key,before,after from audit.row_change "
                                      "where change_set_id=%s order by id limit 2", (change_set,)).fetchall()]
                        receipt = op.verify(before, saved, actual)
                        if op.plan["action"] in ("accessory_remove", "accessory_add", "accessory_stock_update", "accessory_owner_update"):
                            recorded_reason = cur.execute("select reason from audit.change_set where id=%s", (change_set,)).fetchone()
                            if recorded_reason is None or recorded_reason[0] != (op.reason if op.plan["action"] == "accessory_remove" else None):
                                raise Conflict("The accessory Undo reason could not be confirmed.")
                        summary = Summary(summary.text, summary.counts, summary.changed,
                                          {**summary.extra, "accessory_undo": receipt})
                    else:
                        saved = self._join(inv_part, deck_key, part)
                    return saved, summary
            except _Unchanged as u:
                return u.result
        out = self._call(work)
        with self._lock:
            if "key" in result:
                self._cache = (result["key"], result["inv"], datetime.now())
            if "decks" in result:
                self._decks = result["decks"]
        return out


def _deck_import(inv, images, history=None, replace=False):
    """(the decks part's rows, {name: ImageMeta with its bytes}, [reasons]) for importing inv's
    deck parts: table_rows' strict reasons, a picture whose bytes (images: {name: bytes}, else
    the ImageMeta's own) aren't given or aren't its, and a history with replace."""
    t, reasons = deck_tables(inv, strict=True)
    metas = {}
    for name, meta in inv.accessory_images.items():
        data = (images or {}).get(name, meta.content)
        if data is None:
            reasons.append(f"{meta.path}: its content wasn't given")
        elif ImageMeta.of(name, data) != meta:
            reasons.append(f"{meta.path}: its content isn't the picture the snapshot has")
        else:
            metas[name] = ImageMeta.of(name, data)
    if history is not None and not isinstance(history, (list, tuple)):
        reasons.append("the deck history must be a list of revisions")
    if history is not None and replace:
        reasons.append("a history is imported only into a database with no decks (not with replace)")
    return t, metas, reasons


def _write_decks(cur, change_set, inv, t, metas, actor, message, history, replace):
    """The import of inv's deck parts inside the caller's change (its lock taken); returns the new
    decks revision (text)."""
    if not pg_decks.migrated(cur.connection):
        raise ValueError("the database has no tables for the decks yet: run python -m decklab.db migrate first")
    cur.execute("select id from space")
    missing = sorted({d.space for d in inv.decks.values()} - {r[0] for r in cur.fetchall()})
    if missing:
        raise ValueError(f"the decks are in space {', '.join(missing)}, which the database doesn't have: run "
                         f"python -m decklab.db sync-profiles first")
    space_members.admit(cur, space_ids={d.space for d in inv.decks.values()}, actor=actor, lock=False)
    cur.execute("select exists (select 1 from decks_revision) or exists (select 1 from deck) or exists "
                "(select 1 from accessory) or exists (select 1 from accessory_image) or exists "
                "(select 1 from deck_revision)")
    if cur.fetchone()[0] and not replace:
        raise ValueError(DECKS_ALREADY)
    pg_decks.write_all(cur, t, metas, change_set, actor.id, message, history=history, replace=replace)
    cur.execute("update decks_revision set revision = revision + 1, imported_at = now() returning revision")
    row = cur.fetchone()
    if row is None:
        cur.execute("insert into decks_revision (id, revision) values (true, 1) returning revision")
        row = cur.fetchone()
    return str(row[0])


def write_decks(inv, actor, message, *, images=None, history=None, replace=False, dbname=None, conn=None):
    """Put a snapshot's deck parts (every deck, accessories.csv's rows and its pictures; the rest
    of inv is ignored) into the database as one change set, with the decks_revision row: the
    import of the decks into a database whose inventory is there already (pg_decks.write_all).
    images: {file name: bytes} of every picture (else the ImageMeta's own bytes); history: the
    decks' earlier revisions, oldest first ([{deck_id, at, actor, message, op, git_commit,
    text}]), else each deck gets one revision of this change set.

    Refuses (ValueError) with every reason when the database can't hold the deck parts exactly
    (table_rows' strict reasons: a text with carriage returns, a non-slug file name, an
    accessories.csv not as Deck Lab writes it, a picture's bytes missing), a history that doesn't
    end with each deck's text, a history with replace, a deck in a space the database doesn't have, a database without
    migration 0006, and a database that holds decks already, unless replace (which keeps the
    history, see pg_decks). Returns the new decks revision (text). conn: a connection with no
    transaction open (otherwise a new app-role one)."""
    if not isinstance(actor, Actor):
        raise TypeError("write_decks needs a state.Actor")
    t, metas, reasons = _deck_import(inv, images, history, replace)
    if reasons:
        raise Unrepresentable(reasons)
    own = conn is None
    c = db.connect("app", dbname=dbname) if own else conn
    try:
        with db.change(actor.id, actor.source, message, conn=c, via=actor.via) as (cur, change_set):
            _take_lock(cur)
            return _write_decks(cur, change_set, inv, t, metas, actor, message, history, replace)
    finally:
        if own:
            c.close()


def write_model(inv, actor, message, *, contents=None, replace=False, dbname=None, conn=None, decks=False,
                images=None, history=None):
    """Put a whole snapshot into the database as one change set (the import's bulk writer):
    every table's rows, the raw import files (contents: {(space, file name): bytes}, one for each
    of inv.imports) and the inventory_revision row (inserted, or bumped with a new import time).
    With decks, its deck parts too, as write_decks() puts them (images: their pictures' bytes;
    history: their earlier revisions, oldest first, as write_decks() takes them, refused with replace;
    replace then replaces those as well); without, they're left as they are and nothing about
    them is checked (a history given without decks is refused).

    Refuses (ValueError) with every reason when the database can't hold inv exactly
    (representable(), or an import file's content missing or of another size); when inv holds
    a space the database doesn't have (sync the profiles first); and when the database already
    holds an inventory, unless replace, which deletes every inventory row first in the same
    change set. Returns the new revision (text). conn: a connection with no transaction open
    (otherwise a new app-role one)."""
    if not isinstance(actor, Actor):
        raise TypeError("write_model needs a state.Actor")
    contents = contents or {}
    reasons = representable(pg_decks.without_deck_parts(inv))
    if decks:
        deck_rows, metas, more = _deck_import(inv, images, history, replace)
        reasons += more
    elif history is not None:
        reasons.append("a deck history is imported only with the decks (decks=True)")
    imports = []
    for space, found in inv.imports.items():
        for info in found:
            data = contents.get((space, info.name))
            if data is None:
                reasons.append(f"{paths.imports_dir(space)}/{info.name}: its content wasn't given")
            elif len(data) != info.size:
                reasons.append(f"{paths.imports_dir(space)}/{info.name}: its content isn't {info.size} bytes")
            else:
                imports.append((space, info.name, data))
    if reasons:
        raise Unrepresentable(reasons)
    t = tables(pg_decks.without_deck_parts(inv), strict=True)
    spaces = set(inv.collections) | set(inv.tokens) | set(inv.imports)
    own = conn is None
    c = db.connect("app", dbname=dbname) if own else conn
    try:
        with db.change(actor.id, actor.source, message, conn=c, via=actor.via) as (cur, change_set):
            _take_lock(cur)
            cur.execute("select id from space")
            missing = sorted(spaces - {r[0] for r in cur.fetchall()})
            if missing:
                raise ValueError(f"the inventory holds space {', '.join(missing)}, which the database doesn't "
                                 f"have: run python -m decklab.db sync-profiles first")
            space_members.admit(cur, space_ids=spaces, actor=actor, lock=False)
            cur.execute("select exists (select 1 from inventory_revision)" + "".join(
                f" or exists (select 1 from {table})" for table in INVENTORY_TABLES))
            if cur.fetchone()[0]:
                if not replace:
                    raise ValueError(ALREADY)
                for table in INVENTORY_TABLES:
                    cur.execute(f"delete from {table}")
            _write_all(cur, t)
            _add_imports(cur, imports)
            cur.execute("update inventory_revision set revision = revision + 1, imported_at = now() "
                        "returning revision")
            row = cur.fetchone()
            if row is None:
                cur.execute("insert into inventory_revision (id, revision) values (true, 1) returning revision")
                row = cur.fetchone()
            if decks:
                _write_decks(cur, change_set, inv, deck_rows, metas, actor, message, history, replace)
            return str(row[0])
    finally:
        if own:
            c.close()
