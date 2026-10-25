"""The one-time set-up, safe to run again: `python -m decklab.db setup`.

As the postgres superuser (its password already in pgpass), it
1. makes the three login roles if they're missing (conn.ROLES), each with a fresh random
   password that goes straight into the user's pgpass file and nowhere else;
2. makes the database, owned by decklab_owner, if it's missing, and lets only the three roles
   connect to it;
3. applies the migrations as the owner (migrate.py), and
4. syncs the profiles from config.json (profiles_sync.py).

A role that already has a pgpass line keeps its password (and gets it back on the server if
it no longer logs in with it). One without (made by hand, or the line was lost) gets a new
one, set on the server before it's written to pgpass. The password is sent to the server only
as a SCRAM verifier worked out here (libpq's PQencryptPasswordConn), so the plain text never
appears in SQL, in the server's log or on a command line, and it is never printed.
"""
import os
import secrets
import tempfile
from pathlib import Path

from decklab.db import conn as db

PGPASS_ENV = "PGPASSFILE"


def pgpass_path():
    """The pgpass file libpq reads: PGPASSFILE when set, otherwise
    %APPDATA%\\postgresql\\pgpass.conf on Windows (~/.pgpass elsewhere)."""
    if os.environ.get(PGPASS_ENV):
        return Path(os.environ[PGPASS_ENV])
    if os.name == "nt":
        return Path(os.environ["APPDATA"]) / "postgresql" / "pgpass.conf"
    return Path.home() / ".pgpass"


def _unescape(field):
    out, i = [], 0
    while i < len(field):
        if field[i] == "\\" and i + 1 < len(field):
            i += 1
        out.append(field[i])
        i += 1
    return "".join(out)


def _split(line):
    """A pgpass line's five fields (backslash escapes kept), or None for a comment, a blank
    line or one that doesn't have five."""
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    fields, current, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            current.append(line[i:i + 2])
            i += 2
            continue
        if ch == ":" and len(fields) < 4:
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    fields.append("".join(current))
    return fields if len(fields) == 5 else None


def _escape(value):
    return str(value).replace("\\", "\\\\").replace(":", "\\:")


def pgpass_line(role, password, host="localhost", port=5432):
    """The line setup writes for a role: localhost:5432:*:<role>:<password>."""
    return f"{_escape(host)}:{port}:*:{_escape(role)}:{_escape(password)}"


def has_entry(text, role, host="localhost", port=5432):
    """True when the pgpass text has setup's line for role (any database)."""
    return _find(text, role, host, port) is not None


def _find(text, role, host, port):
    for line in text.splitlines():
        f = _split(line)
        if f and _unescape(f[0]) == host and _unescape(f[1]) == str(port) and f[2] == "*" \
                and _unescape(f[3]) == role:
            return line
    return None


def with_entry(text, role, password, host="localhost", port=5432):
    """The pgpass text with setup's line for role set to password: an existing line for that
    host, port and role is replaced in place, otherwise one is added at the end. Every other
    line is kept as it was."""
    new = pgpass_line(role, password, host, port)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        f = _split(line)
        if f and _unescape(f[0]) == host and _unescape(f[1]) == str(port) and f[2] == "*" \
                and _unescape(f[3]) == role:
            lines[i] = new
            break
    else:
        lines.append(new)
    newline = "\r\n" if "\r\n" in text else "\n"
    return newline.join(lines) + newline


def write_pgpass(path, text):
    """Replace the pgpass file in one step (a temporary file beside it, then a rename), so a
    crash never leaves it half written. The folder is made when missing; the file stays under
    the user's own profile, with the permissions Windows gives it there."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".pgpass-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if os.name != "nt":
        os.chmod(path, 0o600)


def _verifier(c, role, password):
    """The SCRAM verifier for role's password, worked out client-side by libpq."""
    return c.pgconn.encrypt_password(password.encode(), role.encode(), b"scram-sha-256").decode()


def _can_log_in(key):
    """True when the role logs in with the password libpq finds in pgpass."""
    try:
        db.connect(key, dbname="postgres", autocommit=True).close()
    except db.DbUnavailable:
        return False
    return True


def ensure_roles(c, pgpass=None, say=print):
    """Make the three roles if they're missing and give each a pgpass line (see the module
    docstring). c: an autocommit superuser connection. Returns the roles that got a new
    password.

    A new password reaches the server before pgpass, so a run cut short between the two
    leaves no line and the next run simply makes another. A role whose existing line no
    longer logs in (pgpass restored from elsewhere, an ALTER ROLE by hand) gets that line's
    password back."""
    from psycopg import sql
    s = db.settings()
    host, port = s["host"], int(s["port"])
    pgpass = Path(pgpass or pgpass_path())
    checkable = pgpass == pgpass_path()     # libpq reads this file, so a login tests it
    renewed = []
    for key, role in db.ROLES.items():
        text = pgpass.read_text(encoding="utf-8") if pgpass.exists() else ""
        line = _find(text, role, host, port)
        if line is None:
            password = secrets.token_urlsafe(32)
        else:
            password = _unescape(_split(line)[4])
        exists = c.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone() is not None
        attributes = sql.SQL("login createdb" if key == "owner" else "login")
        ident = sql.Identifier(role)
        verifier = sql.Literal(_verifier(c, role, password))
        if not exists:
            c.execute(sql.SQL("create role {} {} password {}").format(ident, attributes, verifier))
            say(f"Made the role {role}.")
        else:
            c.execute(sql.SQL("alter role {} {}").format(ident, attributes))
            if line is None:
                c.execute(sql.SQL("alter role {} password {}").format(ident, verifier))
            elif checkable and not _can_log_in(key):
                c.execute(sql.SQL("alter role {} password {}").format(ident, verifier))
                say(f"Reset {role}'s password to the one in pgpass (not shown).")
        if line is None:
            write_pgpass(pgpass, with_entry(text, role, password, host, port))
            renewed.append(role)
            say(f"Gave {role} a new password, saved in {pgpass} (not shown).")
        password = verifier = None
    return renewed


def secure_database(name):
    """Let only the three roles connect to database name, nobody but its owner make temporary
    objects in it, and nobody else make objects in its public schema. Run as its owner.
    Database privileges aren't copied from a template, so the tests' throwaway databases need
    this too (migrations 0001 and 0002 do it for the one they run in)."""
    from psycopg import sql
    with db.connect("owner", dbname=name, autocommit=True) as c:
        ident = sql.Identifier(name)
        c.execute(sql.SQL("revoke connect on database {} from public").format(ident))
        c.execute(sql.SQL("grant connect on database {} to {}").format(
            ident, sql.SQL(", ").join(sql.Identifier(r) for r in db.ROLES.values())))
        c.execute(sql.SQL("revoke temporary on database {} from public").format(ident))
        c.execute("revoke create on schema public from public")


def ensure_database(c, name, say=print):
    """Make database name, owned by decklab_owner, when it's missing. c: an autocommit
    superuser connection. Returns True when it was made."""
    from psycopg import sql
    if c.execute("select 1 from pg_database where datname = %s", (name,)).fetchone():
        return False
    c.execute(sql.SQL("create database {} owner {} encoding 'UTF8' template template0").format(
        sql.Identifier(name), sql.Identifier(db.ROLES["owner"])))
    say(f"Made the database {name}, owned by {db.ROLES['owner']}.")
    return True


def run(dbname=None, say=print):
    """The whole set-up (see the module docstring). Returns 0."""
    from decklab.db import migrate, profiles_sync
    name = dbname or db.settings()["name"]
    with db.connect("super", dbname="postgres", autocommit=True) as c:
        ensure_roles(c, say=say)
        ensure_database(c, name, say=say)
    secure_database(name)
    applied = migrate.apply(dbname=name, say=say)
    summary = profiles_sync.sync(dbname=name)
    say(f"Database {name}: {len(applied)} migration(s) applied now; profiles "
        f"{profiles_sync.describe(summary)}.")
    return 0
