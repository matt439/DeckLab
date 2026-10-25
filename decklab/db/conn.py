"""How Deck Lab reaches its database: the settings, the three roles, connections, and change(),
the one way to write audited rows.

Passwords are never handled here. libpq reads them itself from the user's pgpass file
(%APPDATA%\\postgresql\\pgpass.conf), which setup.py fills in; nothing in this package prints,
logs or passes one on a command line.

psycopg is imported only inside the functions that need it, so the rest of Deck Lab (and the
test suite under the system Python, which has no psycopg) can import this module safely.
"""
import os
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from decklab.lib import config

# The three login roles: the owner runs migrations and backups, the app reads and writes data,
# and ro only reads (the `sql` command). SUPERUSER is used by setup alone.
ROLES = {"owner": "decklab_owner", "app": "decklab_app", "ro": "decklab_ro"}
SUPERUSER = "postgres"

# The "database" block of config.json, all optional. They live here rather than in
# config.DEFAULTS so the rest of Deck Lab doesn't see them.
DEFAULTS = {
    "host": "localhost",
    "port": 5432,
    "name": "decklab",
    "pg_bin": None,               # None: PG_BIN_DEFAULT, else the newest other version there, else PATH
    # Where backup copies each dump. None (the default off Windows): no copy, the dumps stay in
    # staging_dir only. Windows keeps the original household's NAS share as its default.
    "backup_dir": r"\\NAS\Backups\DeckLab" if os.name == "nt" else None,
    "staging_dir": str(config.DATA / "backups"),
    "export_repo": str(config.REPO.parent / "DeckLabData"),
    "keep_daily": 14,
    "keep_weekly": 8,
    "restore_check_days": 28,
    "stale_backup_hours": 36,
}
PG_BIN_DEFAULT = r"C:\Program Files\PostgreSQL\18\bin"
NAME_ENV = "DECKLAB_DB_NAME"      # replaces "name" (the tests' throwaway databases)

# Where change() may say a write came from.
SOURCES = ("web", "cli", "sync", "migration", "receipt", "test")
# Which listener a web change came through: the home network or the tunnel (migration 0003).
VIAS = ("home", "tunnel")

LOG_ENV = "DECKLAB_DB_LOG"        # replaces LOG_FILE (the tests' own log, so no test writes the real one)
LOG_FILE = Path(os.environ[LOG_ENV]) if os.environ.get(LOG_ENV) else config.DATA / "logs" / "db.log"
CONNECT_TIMEOUT = 10              # seconds
LOCALHOST_ADDR = "127.0.0.1"      # the one address connect() uses for host localhost


class DbUnavailable(Exception):
    """The database can't be used from here: psycopg isn't installed for this Python, or the
    server can't be reached (or refused the login). The message says which, in plain English."""


def settings():
    """DEFAULTS overlaid with config.json's "database" block and then the environment
    (DECKLAB_DB_NAME). A staging_dir of null means the default, decklab/data/backups."""
    out = dict(DEFAULTS)
    block = config.load().get("database")
    if isinstance(block, dict):
        out.update(block)
    if out.get("staging_dir") is None:
        out["staging_dir"] = DEFAULTS["staging_dir"]
    name = os.environ.get(NAME_ENV)
    if name:
        out["name"] = name
    return out


def _psycopg():
    try:
        import psycopg
    except ImportError:
        raise DbUnavailable(f"psycopg isn't installed for this Python ({sys.executable}); install it "
                            r"with .venv\Scripts\python -m pip install -r decklab/requirements.txt") from None
    return psycopg


def role_name(role):
    """The PostgreSQL user for a key of ROLES, or "super"."""
    if role == "super":
        return SUPERUSER
    try:
        return ROLES[role]
    except KeyError:
        raise ValueError(f"unknown role {role!r}: use one of {', '.join(ROLES)} or super") from None


def connect(role="app", dbname=None, autocommit=False, timeout=None, options=None, password=None):
    """A new psycopg connection as role (a key of ROLES, or "super") to dbname (default: the
    settings' name), giving up after timeout seconds (default CONNECT_TIMEOUT; the server's
    requests use less). options: server settings for the session, as libpq's options string
    ("-c lock_timeout=2000 ..."). The password comes from pgpass. The one exception is
    password, for setup's superuser login on a new install when pgpass has no line for it: typed
    at a prompt, kept in memory for that run only, never printed or written.
    A host of localhost connects to 127.0.0.1 alone (hostaddr; host stays for pgpass's
    matching): libpq applies connect_timeout to each address a name resolves to, so ::1 then
    127.0.0.1 would double the wait while the server is down.
    Raises DbUnavailable when psycopg is missing or the server can't be reached."""
    psycopg = _psycopg()
    s = settings()
    user = role_name(role)
    dbname = dbname or s["name"]
    extra = {"options": options} if options else {}
    if password is not None:
        extra["password"] = password
    if str(s["host"]).strip().lower() == "localhost":
        extra["hostaddr"] = LOCALHOST_ADDR
    try:
        return psycopg.connect(host=s["host"], port=int(s["port"]), dbname=dbname, user=user,
                               autocommit=autocommit,
                               connect_timeout=timeout or CONNECT_TIMEOUT,
                               application_name="decklab.db", **extra)
    except psycopg.OperationalError as e:
        detail = (str(e).strip().splitlines() or ["no detail"])[-1]
        raise DbUnavailable(f"can't reach PostgreSQL at {s['host']}:{s['port']} as {user} "
                            f"(database {dbname}): {detail}") from None


@contextmanager
def change(actor, source, message, reason=None, conn=None, via=None):
    """One audited write: a transaction whose audit.change_set row says who (actor: a profile
    id, or "system" or "claude"), from where (source: one of SOURCES, and for a web change via:
    the listener, one of VIAS), what (message) and, for removals, why (reason). The audit
    trigger refuses any write to an audited table without one, and records each row's before
    and after against it. via is written only when it's given, so callers that leave it out
    still work on a database without migration 0003's column.

    Yields (cursor, change_set_id). Commits when the block finishes, rolls back when it
    raises. conn, when given, must have no transaction open (otherwise this would become a
    savepoint inside the caller's transaction and never commit on its own); without it, an
    app-role connection is opened and closed here."""
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("a change needs an actor (a profile id, system or claude)")
    if source not in SOURCES:
        raise ValueError(f"unknown change source {source!r}: use one of {', '.join(SOURCES)}")
    if via is not None and via not in VIAS:
        raise ValueError(f"unknown change via {via!r}: use one of {', '.join(VIAS)}, or None")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("a change needs a message saying what it does")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        reason = None
    own = conn is None
    if own:
        conn = connect("app")
    else:
        from psycopg.pq import TransactionStatus
        if conn.info.transaction_status != TransactionStatus.IDLE:
            raise ValueError("finish the connection's open transaction before starting a change")
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                if via is None:
                    cur.execute("insert into audit.change_set (actor, source, message, reason) "
                                "values (%s, %s, %s, %s) returning id",
                                (actor.strip(), source, message.strip(), reason))
                else:
                    cur.execute("insert into audit.change_set (actor, source, message, reason, via) "
                                "values (%s, %s, %s, %s, %s) returning id",
                                (actor.strip(), source, message.strip(), reason, via))
                change_set = cur.fetchone()[0]
                cur.execute("select set_config('decklab.change_set', %s, true)", (str(change_set),))
                yield cur, change_set
    finally:
        if own:
            conn.close()


def pg_bin(name):
    """The path of one of PostgreSQL's programs (pg_dump.exe, pg_restore.exe, psql.exe ...).
    ".exe" is added on Windows when name has no suffix. With the settings' pg_bin set, only that
    folder is looked in. Without it: PG_BIN_DEFAULT, then the newest other version under
    Program Files\\PostgreSQL, then the PATH (Linux and macOS installs put them there).
    Raises FileNotFoundError, saying where it looked, when it isn't found."""
    if os.name == "nt" and not Path(name).suffix:
        name += ".exe"
    folder = settings().get("pg_bin")
    if folder:
        path = Path(folder) / name
        if not path.is_file():
            raise FileNotFoundError(f"{name} isn't in {path.parent}: install PostgreSQL there, or set "
                                    f'"pg_bin" in config.json\'s "database" block')
        return path
    path = Path(PG_BIN_DEFAULT) / name
    if path.is_file():
        return path
    root = Path(os.environ.get("ProgramFiles") or r"C:\Program Files") / "PostgreSQL"
    try:
        found = sorted((p for p in root.glob(f"*/bin/{name}") if p.is_file()),
                       key=lambda p: [int(x) if x.isdigit() else 0 for x in p.parent.parent.name.split(".")])
    except OSError:
        found = []
    if found:
        return found[-1]
    on_path = shutil.which(name)
    if on_path:
        return Path(on_path)
    raise FileNotFoundError(f"{name} isn't in {PG_BIN_DEFAULT} or on the PATH: install PostgreSQL's "
                            f'client programs, or set "pg_bin" in config.json\'s "database" block')


def log(text):
    """Append a timestamped line to decklab/data/logs/db.log (LOG_FILE: DECKLAB_DB_LOG's file
    when that's set), and show it on stderr when that is a terminal (the nightly task runs under
    pythonw, which has none)."""
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {str(text).rstrip()}"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")
    stream = sys.stderr
    if stream is not None and getattr(stream, "isatty", lambda: False)():
        stream.write(line + "\n")
        stream.flush()
