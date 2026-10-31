"""What the database tests share (test_db_core.py, test_db_ops.py, test_db_phase2.py,
test_state_contract.py, test_inventory_contract.py): skipping when there's no database to use,
throwaway databases copied from a template, and reset() between tests that share one.

The template, decklab_tmpl_<8 hex>, is this worktree's (the hex is a hash of the repo path, so
worktrees don't share one). It's made by running the migrations and made again when their
checksums change. Each test class gets its own copy, decklab_t_<8 hex>_<pid>_<n>, dropped when
the class is done; copies an interrupted run left behind are dropped by the next run once
they're an hour old and nobody has them open. While a class runs, DECKLAB_DB_NAME names its copy, so conn.connect()
reaches it and never the real decklab database.

The test package puts .venv's psycopg on sys.path (lib/venv.py), so these run under the system
python too. Without psycopg, or with the server or the roles out of reach, the database tests
skip with the reason.
discover doesn't collect this module: its name doesn't start with test_.
"""
import hashlib
import os
import socket
import time
import unittest
from unittest import mock

from decklab.lib import config

_HASH = hashlib.sha1(str(config.REPO).lower().encode()).hexdigest()[:8]
TEMPLATE = f"decklab_tmpl_{_HASH}"
PREFIX = f"decklab_t_{_HASH}_"
MAX_AGE = 3600          # seconds before another run may drop a leftover copy
PROBE_TIMEOUT = 1       # seconds to wait for the server's port before skipping
# migration 0003's tables, which reset() empties
PHASE2_TABLES = ("wishlist_entry", "profile_setting", "simulation_mode", "play_record")
STATE_TABLES = PHASE2_TABLES + ("packing_tick", "commander_night", "visibility")
# migration 0004's audited tables, children before parents (the order reset() deletes them in;
# collection_import_content goes with collection_import, and reset() empties inventory_revision),
# then migration 0006's (the decks part: its history and derived rows before the decks, a text
# with its deck; reset() empties decks_revision too), and migration 0010's rename aliases.
DECK_TABLES = ("deck_alias", "deck_revision", "deck_line", "deck_text", "deck", "accessory", "accessory_image")
INVENTORY_TABLES = ("order_card_item", "order_token_item", "order_component", "purchase_order",
                    "product_item", "product", "product_status", "collection_card", "collection_import",
                    "token_card", "watchlist_item") + DECK_TABLES
_COMMENT = "Deck Lab test database, made at "

_state = {"reason": None, "checked": False, "cleaned": False, "n": 0}


def unavailable():
    """Why the database tests can't run here, or None when they can (checked once a process).
    The server's port is probed first with a short timeout, so a stopped PostgreSQL skips at
    once instead of waiting for a connection timeout."""
    if _state["checked"]:
        return _state["reason"]
    _state["checked"] = True
    try:
        import psycopg  # noqa: F401
    except ImportError:
        _state["reason"] = (r"psycopg isn't installed for this Python (install it with .venv\Scripts\python "
                            "-m pip install -r decklab/requirements.txt)")
        return _state["reason"]
    from decklab.db import conn as db
    s = db.settings()
    try:
        socket.create_connection((s["host"], int(s["port"])), timeout=PROBE_TIMEOUT).close()
    except OSError as e:
        _state["reason"] = f"nothing answers at {s['host']}:{s['port']} ({e}); is PostgreSQL running?"
        return _state["reason"]
    try:
        for role in db.ROLES:
            db.connect(role, dbname="postgres", autocommit=True).close()
    except db.DbUnavailable as e:
        _state["reason"] = f"the database isn't reachable ({e}); run python -m decklab.db setup"
    return _state["reason"]


def require_db(testcase=None):
    """Skip (unittest.SkipTest) with the reason when the database tests can't run here."""
    reason = unavailable()
    if reason:
        raise unittest.SkipTest(reason)


def _admin():
    from decklab.db import conn as db
    return db.connect("owner", dbname="postgres", autocommit=True)


def _dropper():
    """A connection that can drop a copy someone still has open: the superuser's when its
    pgpass line is there (only it may end other roles' sessions, which `with (force)` does),
    otherwise the owner's."""
    from decklab.db import conn as db
    try:
        return db.connect("super", dbname="postgres", autocommit=True)
    except db.DbUnavailable:
        return _admin()


def _drop(c, name):
    from psycopg import sql
    c.execute(sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name)))


def _cleanup(c):
    """Drop this worktree's copies older than MAX_AGE (or with no time on them) that nobody
    has open. One that can't be dropped now is left for a later run rather than failing
    every test here."""
    import psycopg
    rows = c.execute("select d.datname, shobj_description(d.oid, 'pg_database') from pg_database d "
                     "where starts_with(d.datname, %s) and not exists "
                     "(select 1 from pg_stat_activity a where a.datid = d.oid)", (PREFIX,)).fetchall()
    now = time.time()
    for name, comment in rows:
        try:
            made = float((comment or "").removeprefix(_COMMENT))
        except ValueError:
            made = 0
        if now - made > MAX_AGE:
            try:
                _drop(c, name)
            except psycopg.Error:
                pass


def _template_current(c):
    """True when the template exists and has exactly the migrations as they are now."""
    from decklab.db import conn as db, migrate
    if not c.execute("select 1 from pg_database where datname = %s", (TEMPLATE,)).fetchone():
        return False
    try:
        with db.connect("owner", dbname=TEMPLATE, autocommit=True) as t:
            rows = t.execute("select version, checksum from public.schema_migration").fetchall()
    except Exception:
        return False
    return sorted(rows) == sorted((f["version"], f["checksum"]) for f in migrate.available())


def _ensure_template(c):
    from psycopg import sql
    from decklab.db import migrate
    if _template_current(c):
        return
    _drop(c, TEMPLATE)
    c.execute(sql.SQL("create database {} encoding 'UTF8' template template0").format(sql.Identifier(TEMPLATE)))
    migrate.apply(dbname=TEMPLATE)


def new_name(label=None):
    """A name for a new throwaway database of this worktree (PREFIX, so cleanup knows it)."""
    _state["n"] += 1
    return f"{PREFIX}{os.getpid()}_{label + '_' if label else ''}{_state['n']}"


def stamp(c, name):
    """Mark a throwaway database with the time it was made, so another run's cleanup leaves
    it alone for MAX_AGE. c: a connection as its owner (or the superuser)."""
    from psycopg import sql
    c.execute(sql.SQL("comment on database {} is {}").format(
        sql.Identifier(name), sql.Literal(f"{_COMMENT}{time.time():.0f}")))


def create_database():
    """A new throwaway database, copied from the template (made or remade first if need be).
    Returns its name."""
    from psycopg import sql
    from decklab.db import setup
    name = new_name()
    with _admin() as c:
        # One run at a time builds the template or copies it (a copy needs it unused).
        c.execute("select pg_advisory_lock(hashtext(%s))", (TEMPLATE,))
        try:
            if not _state["cleaned"]:
                _cleanup(c)
                _state["cleaned"] = True
            _ensure_template(c)
            _drop(c, name)
            c.execute(sql.SQL("create database {} template {}").format(
                sql.Identifier(name), sql.Identifier(TEMPLATE)))
            stamp(c, name)
        finally:
            c.execute("select pg_advisory_unlock(hashtext(%s))", (TEMPLATE,))
    setup.secure_database(name)
    return name


def create_empty_database(label=None):
    """A new, empty throwaway database owned by decklab_owner (no migrations, no template),
    stamped like a copy so another run's cleanup leaves it alone. For tests that run
    setup or migrations themselves. Returns its name."""
    from decklab.db import setup
    name = new_name(label)
    with _admin() as c:
        c.execute("select pg_advisory_lock(hashtext(%s))", (TEMPLATE,))   # cleanup runs under it
        try:
            setup.ensure_database(c, name, say=lambda *_: None)
            stamp(c, name)
        finally:
            c.execute("select pg_advisory_unlock(hashtext(%s))", (TEMPLATE,))
    return name


def drop_database(name):
    """Drop a throwaway database (only ever one of this worktree's)."""
    if not name.startswith(PREFIX):
        raise ValueError(f"{name} isn't a test database")
    with _dropper() as c:
        _drop(c, name)


def reset(dbname, tables=STATE_TABLES):
    """Empty tables (audited ones) and the audit trail in dbname, as its owner: the deletes go
    through a change set (truncate is refused and the trigger needs one), then the trail itself
    is deleted, so each test of a class sharing a database starts with nothing. When tables
    include the inventory's, the inventory_revision row goes too (the inventory is then "not
    imported" again), and with the decks' (DECK_TABLES) the decks_revision row; list them in
    INVENTORY_TABLES' order, children first."""
    from psycopg import sql
    from decklab.db import conn as db
    with db.connect("owner", dbname=dbname, autocommit=True) as c:
        with db.change("test", "test", "reset for the next test", conn=c) as (cur, _):
            # Removal's durable marker references its audit change. Test housekeeping
            # must clear it before deleting that trail, including inventory-only resets.
            if cur.execute("select to_regclass('public.space_departure')").fetchone()[0]:
                cur.execute("delete from space_departure")
            for table in tables:
                cur.execute(sql.SQL("delete from {}").format(sql.Identifier(table)))
            if set(tables) & set(INVENTORY_TABLES) - set(DECK_TABLES):
                cur.execute("delete from inventory_revision")
            if set(tables) & set(DECK_TABLES):
                cur.execute("delete from decks_revision")
            elif c.execute("select to_regclass('public.deck_revision')").fetchone()[0]:
                cur.execute("update deck_revision set change_set_id = null")    # the trail goes below
        c.execute("delete from audit.row_change")
        c.execute("delete from audit.change_set")


# What undoes each later migration, for tests that roll a throwaway database back to an older
# schema and migrate it forward again (roll_back_schema). A new migration needs its entry here.
UNDO_MIGRATION = {
    14: ("alter table product_status drop column token_cards",),
    15: ("alter table order_component drop column check_links",),
    16: ("alter table collection_card drop column location",),
    17: ("drop table public.field_policy",),
    18: ("drop table public.deck_draft",),
    19: ("drop table public.new_deck_draft",),
}


def roll_back_schema(c, version):
    """Put the throwaway database c (an owner connection) back to schema `version`: undo every
    later migration, newest first, and forget it in schema_migration, so migrate.apply() brings
    it forward again. Refuses (AssertionError) when a later migration has no UNDO_MIGRATION entry,
    so a new migration fails here by name rather than as a DuplicateTable on re-apply."""
    from decklab.db import migrate
    dbname = c.execute("select current_database()").fetchone()[0]
    if not dbname.startswith(PREFIX):
        raise ValueError(f"{dbname} isn't a test database")
    later = sorted((m["version"] for m in migrate.available() if m["version"] > version), reverse=True)
    missing = [v for v in later if v not in UNDO_MIGRATION]
    if missing:
        raise AssertionError(f"db_support.UNDO_MIGRATION has no undo for migration(s) {missing}")
    for v in later:
        for statement in UNDO_MIGRATION[v]:
            c.execute(statement)
    c.execute("delete from schema_migration where version > %s", (version,))


def seed_membership(dbname, listed=None):
    """Register state-test targets in a disposable database without seed audit noise.

    Call immediately after reset(). The default is home Matt/User1 and member
    User2/Guest; listed accepts raw config or parsed profiles.read() dicts.
    Only the supplied identities are added/updated; no unrelated member is removed.
    """
    from decklab.db import conn as db, profiles_sync
    from decklab.lib import profiles
    if not dbname.startswith(PREFIX):
        raise ValueError("membership fixtures require a disposable test database")
    if listed is None:
        listed = [
            {"id": "matt", "name": "Matt", "role": "admin", "space": "home", "plays_as": "user", "emails": []},
            {"id": "user1", "name": "User1", "role": "member", "space": "home", "plays_as": "wife", "emails": []},
            {"id": "user2", "name": "User2", "role": "member", "space": "user2", "plays_as": None, "emails": []},
            {"id": "guest", "name": "Guest", "role": "member", "space": "guest", "plays_as": None, "emails": []},
        ]
    listed = profiles.parse(listed)
    want_spaces, want_rows = profiles_sync.wanted(listed)
    with db.connect("owner", dbname=dbname, autocommit=True) as c:
        with db.change("test", "test", "Seed state-test membership", conn=c) as (cur, _):
            have_spaces, have_rows = profiles_sync.current(cur)
            todo = profiles_sync.plan((want_spaces | have_spaces, {**have_rows, **want_rows}),
                                      (have_spaces, have_rows))
            profiles_sync._write(cur, {**have_rows, **want_rows}, todo)
        c.execute("delete from audit.row_change")
        c.execute("delete from audit.change_set")


class DbTestCase(unittest.TestCase):
    """A test class with its own throwaway database, named by cls.dbname and by
    DECKLAB_DB_NAME while the class runs."""
    dbname = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        require_db()
        from decklab.db import conn as db
        cls.dbname = create_database()
        cls.addClassCleanup(drop_database, cls.dbname)
        env = mock.patch.dict(os.environ, {db.NAME_ENV: cls.dbname})
        env.start()
        cls.addClassCleanup(env.stop)

    def connect(self, role="app", autocommit=True):
        from decklab.db import conn as db
        return db.connect(role, dbname=self.dbname, autocommit=autocommit)
