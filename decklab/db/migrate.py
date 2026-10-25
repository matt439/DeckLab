"""The schema migrations: decklab/db/migrations/NNNN_name.sql, applied in order, each in its own
transaction, as the owner role, and recorded in public.schema_migration.

A migration's checksum is the sha256 of its bytes with CRLF turned into LF and a leading UTF-8
byte-order mark dropped, since a worktree may check the files out with Windows line endings and
Visual Studio may save them "with signature". Once applied, a migration is never edited:
a recorded one whose file now differs is refused, as is a recorded one whose file has gone.
Write a new migration instead.

Migrations run without decklab.change_set, so the audit trigger refuses any data they write;
one that writes data has to make its own change set (none does yet).
"""
import hashlib
import re
from pathlib import Path

from decklab.db import conn as db

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
FILE_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
LOCK_KEY = "decklab.migrate"      # the advisory lock that keeps two runs from overlapping

CREATE_TABLE = """
create table if not exists public.schema_migration (
    version int primary key,
    name text not null,
    checksum text not null,
    applied_at timestamptz not null default now()
)"""


class MigrationError(Exception):
    """The migrations can't be applied as they stand (the message says why)."""


BOM = b"\xef\xbb\xbf"


def _normal(data):
    """A migration's bytes as they count: no leading byte-order mark, LF line endings."""
    return data.removeprefix(BOM).replace(b"\r\n", b"\n")


def checksum(data):
    """The sha256 of a migration's bytes, with CRLF line endings read as LF and a leading
    byte-order mark ignored."""
    return hashlib.sha256(_normal(data)).hexdigest()


def available(directory=None):
    """The migration files, as a list of dicts (version, name, path, checksum, sql) in version
    order. Raises MigrationError for a misnamed .sql file or a repeated version."""
    directory = Path(directory or MIGRATIONS)
    out, seen = [], {}
    for path in sorted(directory.glob("*.sql")):
        m = FILE_NAME.match(path.name)
        if not m:
            raise MigrationError(f"{path.name} isn't named NNNN_name.sql (lowercase name), so it can't "
                                 f"be ordered")
        version = int(m.group(1))
        if version in seen:
            raise MigrationError(f"{path.name} and {seen[version]} share version {version}")
        seen[version] = path.name
        data = path.read_bytes()
        out.append({"version": version, "name": m.group(2), "path": path, "checksum": checksum(data),
                    "sql": _normal(data).decode("utf-8")})
    return out


def _applied(cur):
    cur.execute("select to_regclass('public.schema_migration') is not null")
    if not cur.fetchone()[0]:
        return {}
    cur.execute("select version, name, checksum, applied_at from public.schema_migration order by version")
    return {r[0]: {"version": r[0], "name": r[1], "checksum": r[2], "applied_at": r[3]} for r in cur.fetchall()}


def _check(files, applied):
    """Refuse recorded migrations whose file has changed or gone."""
    by_version = {f["version"]: f for f in files}
    for version, row in applied.items():
        f = by_version.get(version)
        if f is None:
            raise MigrationError(f"migration {version:04d}_{row['name']} is recorded in the database but its "
                                 f"file isn't in {MIGRATIONS.name}/: restore the file")
        if f["checksum"] != row["checksum"]:
            raise MigrationError(f"{f['path'].name} has changed since it was applied (its checksum differs "
                                 f"from the one recorded): put the file back as it was, and make any change "
                                 f"in a new migration")


def status(dbname=None, directory=None):
    """What's applied and what's pending, as a dict: applied (list of rows), pending (list of
    file dicts). Raises MigrationError when a recorded migration has changed or gone."""
    files = available(directory)
    with db.connect("owner", dbname=dbname, autocommit=True) as c:
        with c.cursor() as cur:
            applied = _applied(cur)
    _check(files, applied)
    return {"applied": [applied[v] for v in sorted(applied)],
            "pending": [f for f in files if f["version"] not in applied]}


def pending(role="app", dbname=None, conn=None, directory=None):
    """The migration files not yet applied to dbname (file dicts, in version order), read as
    role (the app may read schema_migration, so the server can ask without the owner's login),
    or on conn when given (an open connection, left open). Raises MigrationError when a
    recorded migration has changed or gone, DbUnavailable when the database can't be reached."""
    files = available(directory)
    if conn is None:
        with db.connect(role, dbname=dbname, autocommit=True) as c:
            with c.cursor() as cur:
                applied = _applied(cur)
    else:
        with conn.cursor() as cur:
            applied = _applied(cur)
    _check(files, applied)
    return [f for f in files if f["version"] not in applied]


def apply(dbname=None, directory=None, say=None):
    """Apply every pending migration to dbname (default: the settings' database), each in its
    own transaction, as the owner. Returns the names applied. Raises MigrationError (nothing
    of the refused run applied) when a recorded migration has changed or gone."""
    files = available(directory)
    done = []
    with db.connect("owner", dbname=dbname, autocommit=True) as c:
        with c.cursor() as cur:
            cur.execute("select pg_advisory_lock(hashtext(%s))", (LOCK_KEY,))
            try:
                cur.execute(CREATE_TABLE)
                applied = _applied(cur)
                _check(files, applied)
                for f in files:
                    if f["version"] in applied:
                        continue
                    with c.transaction():
                        cur.execute(f["sql"])
                        cur.execute("insert into public.schema_migration (version, name, checksum) "
                                    "values (%s, %s, %s)", (f["version"], f["name"], f["checksum"]))
                    done.append(f["path"].name)
                    if say:
                        say(f"Applied {f['path'].name}.")
            finally:
                cur.execute("select pg_advisory_unlock(hashtext(%s))", (LOCK_KEY,))
    return done
