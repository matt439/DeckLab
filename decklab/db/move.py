"""Moving the database to another PC: `digest` and `restore` (SELF-HOSTING.md, "Moving to another PC").

  digest [-o FILE] [--compare FILE]   every public and audit table's row count and content digest,
                                      read-only in one snapshot as decklab_ro; written as JSON, or
                                      compared with a file an earlier digest wrote (exit 1 if any differ)
  restore DUMP [--expect FILE] [--replace] [--force]
                                      pg_restore a dump (python -m decklab.db backup) into a new database,
                                      check it against --expect's digest, then put it in place of the
                                      settings' database and apply this checkout's pending migrations

The digest is backup.py's: each row as PostgreSQL writes it as text, sorted bytewise, under fixed
session settings, so the same data gives the same digest on any PC. ops is left out (it gains rows
after every backup and check).

restore works as decklab_owner (which `python -m decklab.db setup` makes, with its pgpass line), so
no superuser is needed. The dump goes into <name>_restoring first; the settings' database is dropped
and the restored copy is checked against --expect, checked for migrations this checkout doesn't know
and migrated first; only then is the settings' database renamed <name>_before_restore (kept, until
the next restore) and the restored one renamed in its place, so a failed restore leaves the database
as it was. Replacing an existing database needs --replace, and one that
holds decks or cards also --force.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from decklab.db import backup, conn as db

RESTORING_SUFFIX = "_restoring"
PREVIOUS_SUFFIX = "_before_restore"
DIGEST_VERSION = 1


def _suffixed(database, suffix):
    """database + suffix, refused when PostgreSQL would truncate it (it must never be the live name)."""
    if not isinstance(database, str) or not database or "\x00" in database:
        raise ValueError("A restore needs a valid database name")
    name = database + suffix
    if len(name.encode("utf-8")) > backup.MAX_IDENTIFIER_BYTES:
        raise ValueError("The database name is too long for a distinct restore database")
    return name


def _restoring_name(database):
    return _suffixed(database, RESTORING_SUFFIX)


def take_digest(dbname=None, role="ro"):
    """{"version", "database", "taken_at", "migration", "counts", "digests"} of dbname (default the
    settings'), read in one repeatable-read read-only transaction. counts and digests cover the
    public and audit tables (backup.DIGEST_SCHEMAS)."""
    from psycopg import IsolationLevel
    name = dbname or db.settings()["name"]
    with db.connect(role, dbname=name) as c:
        c.isolation_level = IsolationLevel.REPEATABLE_READ
        c.read_only = True
        counts = {k: v for k, v in backup.count_rows(c).items() if k.split(".", 1)[0] in backup.DIGEST_SCHEMAS}
        digests = backup.digest_rows(c)
        row = c.execute("select max(version) from public.schema_migration").fetchone() \
            if c.execute("select to_regclass('public.schema_migration') is not null").fetchone()[0] else (None,)
        server = c.execute("select current_setting('server_version_num')::int").fetchone()[0]
        c.rollback()
    return {"version": DIGEST_VERSION, "database": name, "server_version": server,
            "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "migration": row[0], "counts": counts, "digests": digests}


def read_digest(path):
    """A digest file's contents, checked for its shape. ValueError when it isn't one."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"{path} can't be read as a digest file: {e}") from None
    if not isinstance(data, dict) or data.get("version") != DIGEST_VERSION \
            or not isinstance(data.get("counts"), dict) or not isinstance(data.get("digests"), dict):
        raise ValueError(f"{path} isn't a digest file written by python -m decklab.db digest")
    return data


def compare(expected, actual):
    """The differences between two digests, as plain-English lines (none: the same data). When
    actual has newer migrations than expected (a restore applies this checkout's), only the row
    counts of the tables both have are compared, since a migration may rewrite rows."""
    newer = (actual.get("migration") or 0) > (expected.get("migration") or 0)
    there, here = expected["counts"], actual["counts"]
    lines = []
    for name in sorted(set(there) | set(here)):
        if name not in here:
            lines.append(f"{name} is missing here")
        elif name not in there:
            if not newer:
                lines.append(f"{name} is here but not in the digest file")
        elif there[name] != here[name]:
            lines.append(f"{name} has {here[name]} rows here, {there[name]} in the digest file")
    if not newer:
        lines += [f"{name}'s rows differ" for name in sorted(set(expected["digests"]) & set(actual["digests"]))
                  if expected["digests"][name] != actual["digests"][name]]
    return lines


def run_digest(output=None, against=None, say=print):
    """The digest command. Returns 0, or 1 when --compare finds a difference."""
    taken = take_digest()
    tables = len(taken["counts"])
    rows = sum(taken["counts"].values())
    if output:
        Path(output).write_text(json.dumps(taken, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        say(f"Wrote the digest of {taken['database']} ({tables} tables, {rows} rows, migrations up to "
            f"{taken['migration']}) to {output}.")
    if against:
        expected = read_digest(against)
        differences = compare(expected, taken)
        if differences:
            say(f"{taken['database']} differs from {against}:")
            for line in differences:
                say(f"  {line}")
            return 1
        newer = (taken.get("migration") or 0) > (expected.get("migration") or 0)
        same = "the same row counts (contents not compared: newer migrations here)" if newer else "the same contents"
        say(f"{taken['database']} matches {against}: {tables} tables, {rows} rows, {same}.")
    if not output and not against:
        say(json.dumps(taken, indent=1, sort_keys=True))
    return 0


def _held(c):
    """(decks, collection rows, change sets) a database holds, read on c."""
    def count(table):
        if not c.execute("select to_regclass(%s) is not null", (table,)).fetchone()[0]:
            return 0
        from psycopg import sql
        schema, name = table.split(".")
        return c.execute(sql.SQL("select count(*) from {}.{}").format(sql.Identifier(schema),
                                                                      sql.Identifier(name))).fetchone()[0]
    return count("public.deck"), count("public.collection_card"), count("audit.change_set")


def _swap_names(c, name, restoring, previous, exists, say):
    """Put restoring in name's place by renaming, never dropping: name becomes previous first, and
    goes back to name if the second rename fails. c: an autocommit owner connection to postgres."""
    from psycopg import Error, sql
    ident = sql.Identifier
    if exists:
        c.execute(sql.SQL("alter database {} rename to {}").format(ident(name), ident(previous)))
    try:
        c.execute(sql.SQL("alter database {} rename to {}").format(ident(restoring), ident(name)))
    except Error:
        if exists:
            c.execute(sql.SQL("alter database {} rename to {}").format(ident(previous), ident(name)))
        raise


def run_restore(dump, expect=None, replace=False, force=False, say=print):
    """The restore command (see the module docstring). Returns 0, or 1 when it refused or failed;
    the settings' database is unchanged unless it returns 0, and the one it replaced is kept as
    <name>_before_restore."""
    from psycopg import Error, sql
    from decklab.db import migrate, setup
    s = db.settings()
    name, restoring = s["name"], _restoring_name(s["name"])
    previous = _suffixed(s["name"], PREVIOUS_SUFFIX)
    dump = Path(dump)
    if not dump.is_file():
        raise FileNotFoundError(f"There's no dump at {dump}")
    expected = read_digest(expect) if expect else None
    ident = sql.Identifier
    with db.connect("owner", dbname="postgres", autocommit=True) as c:
        exists = c.execute("select 1 from pg_database where datname = %s", (name,)).fetchone() is not None
        here = c.execute("select current_setting('server_version_num')::int").fetchone()[0]
    there = (expected or {}).get("server_version")
    if isinstance(there, int) and there // 10000 > here // 10000:
        say(f"The digest comes from PostgreSQL {there // 10000}, newer than this PC's {here // 10000}: its dump "
            "can't be restored here. Install PostgreSQL {} or later, then run restore again.".format(there // 10000))
        return 1
    if exists:
        with db.connect("owner", dbname=name, autocommit=True) as c:
            decks, cards, changes = _held(c)
        say(f"The database {name} exists: {decks} decks, {cards} collection rows, {changes} change sets.")
        if not replace:
            say("Nothing changed. Give --replace to put the dump in its place.")
            return 1
        if (decks or cards) and not force:
            say("It holds decks or cards, so nothing changed. If they really should be replaced by the dump's, "
                "give --force as well (it's kept as " + previous + ").")
            return 1
    with db.connect("owner", dbname="postgres", autocommit=True) as c:
        c.execute(sql.SQL("drop database if exists {}").format(ident(restoring)))
        try:
            c.execute(sql.SQL("create database {} encoding 'UTF8' template template0").format(ident(restoring)))
        except Error as e:
            hint = db.locale_hint(e)
            if not hint:
                raise
            say(f"The restore didn't work, so {name} is unchanged: {restoring} couldn't be made: "
                f"{str(e).strip()}.{hint}")
            return 1

    def give_up(detail):
        with db.connect("owner", dbname="postgres", autocommit=True) as c:
            c.execute(sql.SQL("drop database if exists {}").format(ident(restoring)))
        say(f"The restore didn't work, so {name} is unchanged: {detail}")
        return 1

    say(f"Restoring {dump.name} into {restoring}...")
    ok, detail = backup._tool([db.pg_bin("pg_restore"), *backup._connection_args(s, restoring),
                               "--exit-on-error", dump])
    if not ok:
        return give_up(detail)
    if expected is not None:
        differences = compare(expected, take_digest(restoring, role="owner"))
        if differences:
            return give_up("it doesn't match the digest file: " + "; ".join(differences))
        say(f"It matches {expect}: {sum(expected['counts'].values())} rows in {len(expected['counts'])} tables.")
    # Everything that can fail happens to the restored copy, before the swap.
    try:
        migrate.status(dbname=restoring)
    except migrate.MigrationError as e:
        return give_up(f"{e}. The dump has migrations this checkout doesn't know: update this PC's code to at "
                       "least the old PC's commit (git pull), then run restore again.")
    try:
        applied = migrate.apply(dbname=restoring, say=say)
        setup.secure_database(restoring)
    except (migrate.MigrationError, Error) as e:
        return give_up(f"this checkout's migrations couldn't be applied to it: {e}")
    with db.connect("owner", dbname="postgres", autocommit=True) as c:
        if exists:
            busy = c.execute("select count(*) from pg_stat_activity where datname = %s and pid <> pg_backend_pid()",
                             (name,)).fetchone()[0]
            if busy:
                c.execute(sql.SQL("drop database if exists {}").format(ident(restoring)))
                say(f"{busy} connection(s) are using {name} (the server, or a command), so it wasn't replaced: "
                    "stop Deck Lab (python -m decklab.lib.homenet stop) and run restore again.")
                return 1
            if c.execute("select 1 from pg_database where datname = %s", (previous,)).fetchone():
                say(f"Dropping {previous}, the database an earlier restore replaced.")
                c.execute(sql.SQL("drop database {}").format(ident(previous)))
        try:
            _swap_names(c, name, restoring, previous, exists, say)
        except Error as e:
            c.execute(sql.SQL("drop database if exists {}").format(ident(restoring)))
            say(f"{name} couldn't be swapped for the restored copy, so it's unchanged: {e}")
            return 1
    say(f"Restored {dump.name} as {name}" + (f", with {len(applied)} newer migration(s) applied" if applied else "") +
        "." + (f" The database it replaced is kept as {previous} (drop it once you're happy, or the next restore "
               "does)." if exists else "") +
        " Run python -m decklab.db sync-profiles if this PC's config.json has different profiles, "
        "then start Deck Lab and run python -m decklab.smoke.")
    return 0
