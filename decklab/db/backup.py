"""The database's backups: a pg_dump each night, copied to the NAS, thinned out to a fortnight
of dailies and two months of weeklies, and now and then restored into a scratch database to
prove a dump can actually be read back.

  backup          pg_dump -Fc, as decklab_owner, into the staging folder (decklab/data/backups
                  unless config.json says otherwise), then a copy to backup_dir (the NAS)
  prune           delete the decklab-*.dump files outside the retention, in both folders
  restore-check   restore the newest NAS dump into <name>_restorecheck and compare row counts
                  and contents
  status          when each kind last worked, the last check's result, and a warning when the
                  last dump is old

Each run is recorded in ops.backup_run (as the owner; the table is an operational log, so it
isn't audited). A dump's row also keeps the exact row count of every table, counted in the
same snapshot pg_dump read (pg_export_snapshot), and (since phase 5) a digest of every public
and audit table's content read in that snapshot too (digest_rows; ops is left out, since the
check's own rows are added to it after the dump), so the restore check compares the restored
database with the database as it was dumped, not as it is by the time the check runs. The
counts are the row's detail ("rows: " and JSON, nothing after it) and the digests are its own
column (digests, migration 0007), so the pre-phase-5 code, a rollback's, still reads the counts
of a dump made by this code. A dump recorded before phase 5 has no digests: its restore check
compares the counts alone.

pg_dump and pg_restore get no password: libpq reads the owner's from the user's pgpass file.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from decklab.db import conn as db

DUMP_NAME = re.compile(r"^decklab-(\d{4})-(\d{2})-(\d{2})-(\d{6})\.dump$")
PARTIAL = ".partial"              # a dump or copy still being written; never counted
PARTIAL_MAX_AGE = 24 * 3600       # seconds after which a leftover .partial is a dead run's, and pruned
SCHEMAS = ("public", "audit", "ops")
RESTORE_SUFFIX = "_restorecheck"
MAX_IDENTIFIER_BYTES = 63         # the standard PostgreSQL identifier limit, measured in UTF-8 bytes
TOOL_TIMEOUT = 45 * 60            # seconds pg_dump or pg_restore may take: well inside the nightly
                                  # task's two hours, so a hung tool is stopped and recorded here
                                  # rather than the whole task being killed with nothing recorded
_SPAWN = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
_ROWS = "rows: "                  # how a dump's row counts start in its backup_run detail
DIGEST_SCHEMAS = ("public", "audit")    # the tables digest_rows covers (ops gains rows after a dump)
# The session settings every digest is read under, so a value's text is the same in the live
# database and in a restored copy whatever their own settings are.
DIGEST_SETTINGS = (("timezone", "UTC"), ("datestyle", "ISO, YMD"), ("intervalstyle", "postgres"),
                   ("bytea_output", "hex"), ("extra_float_digits", "1"))


def say(text):
    """A line of a command's output: always into decklab/data/logs/db.log, and shown once.
    db.log shows it on a terminal itself; otherwise (piped, or the nightly task's pythonw,
    which has no stdout) it also goes to stdout when there is one."""
    db.log(text)
    err = sys.stderr
    if err is not None and getattr(err, "isatty", lambda: False)():
        return
    if sys.stdout is not None:
        print(text, flush=True)


# ------------------------------------------------------------ names and retention

def dump_name(when=None):
    """The file name for a dump made at when (local time, default now)."""
    return f"decklab-{(when or datetime.now()):%Y-%m-%d-%H%M%S}.dump"


def dump_date(name):
    """The day a dump was made, from its file name, or None for a name that isn't a dump's."""
    m = DUMP_NAME.match(name)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def plan_prune(names, today, keep_daily=14, keep_weekly=8):
    """Which dumps to keep and which to delete, as (keep, delete), each a sorted list of names.

    Kept: the newest dump of each of the last keep_daily days (today included), and the newest
    of each of the last keep_weekly ISO weeks (this week included). Whatever their age, the
    newest dump of each of the newest keep_daily days (at least one) that have a dump is kept
    too: when dumps stop arriving (pg_dump failing night after night, or the clock jumping
    ahead), the last good ones must never age out. Dumps dated after today are kept (a clock
    that went backwards is no reason to delete anything). Names that aren't a dump's
    (decklab-YYYY-MM-DD-HHMMSS.dump) are in neither list: they're never deleted."""
    dumps = sorted((n for n in set(names) if dump_date(n)), reverse=True)    # newest first
    weeks = {(today - timedelta(weeks=i)).isocalendar()[:2] for i in range(max(0, keep_weekly))}
    last_days = sorted({dump_date(n) for n in dumps if dump_date(n) <= today}, reverse=True)
    last_days = set(last_days[:max(1, keep_daily)])
    keep, days_seen, weeks_seen = set(), set(), set()
    for name in dumps:
        d = dump_date(name)
        if d > today:
            keep.add(name)
            continue
        week = d.isocalendar()[:2]
        if ((today - d).days < keep_daily or d in last_days) and d not in days_seen:
            keep.add(name)
        if week in weeks and week not in weeks_seen:
            keep.add(name)
        days_seen.add(d)
        weeks_seen.add(week)
    return sorted(keep), sorted(n for n in dumps if n not in keep)


def dumps_in(folder):
    """The dump file names in folder, oldest first (their names sort by time)."""
    return sorted(p.name for p in Path(folder).iterdir() if p.is_file() and dump_date(p.name))


def newest_dump(folder):
    """The newest dump in folder, as a Path, or None."""
    names = dumps_in(folder)
    return Path(folder) / names[-1] if names else None


# ------------------------------------------------------------ the log table

def record(kind, started, ok, path=None, size=None, detail=None, dbname=None, digests=None):
    """Add a row to ops.backup_run, as the owner. Returns its id. digests: a dump's content
    digests (digest_rows), kept in the row's digests column (migration 0007); left out while
    that migration isn't applied, so a backup is still recorded (with its counts alone)."""
    from psycopg import errors
    from psycopg.types.json import Jsonb
    values = (kind, started.astimezone(), ok, None if path is None else str(path), size, detail)
    with db.connect("owner", dbname=dbname, autocommit=True) as c:
        if digests is not None:
            try:
                return c.execute("insert into ops.backup_run (kind, started_at, finished_at, ok, path, bytes, "
                                 "detail, digests) values (%s, %s, now(), %s, %s, %s, %s, %s) returning id",
                                 (*values, Jsonb(digests))).fetchone()[0]
            except errors.UndefinedColumn:
                pass
        return c.execute("insert into ops.backup_run (kind, started_at, finished_at, ok, path, bytes, detail) "
                         "values (%s, %s, now(), %s, %s, %s, %s) returning id", values).fetchone()[0]


def last_ok(dbname=None):
    """When each kind last worked: {kind: started_at or None}."""
    with db.connect("ro", dbname=dbname, autocommit=True) as c:
        rows = dict(c.execute("select kind, max(started_at) from ops.backup_run where ok "
                              "group by kind").fetchall())
    return {kind: rows.get(kind) for kind in ("dump", "export", "restore_check", "check")}


def latest(kinds, dbname=None, conn=None):
    """The newest run of each kind, worked or not: {kind: {"ok", "started_at", "finished_at",
    "detail"} or None}. conn: read on this open connection (left open)."""
    def read(c):
        return c.execute("select distinct on (kind) kind, ok, started_at, finished_at, detail from ops.backup_run "
                         "where kind = any(%s) order by kind, id desc", (list(kinds),)).fetchall()
    if conn is None:
        with db.connect("ro", dbname=dbname, autocommit=True) as c:
            rows = read(c)
    else:
        rows = read(conn)
    found = {kind: {"ok": ok, "started_at": started, "finished_at": finished, "detail": detail}
             for kind, ok, started, finished, detail in rows}
    return {kind: found.get(kind) for kind in kinds}


def dump_detail(counts):
    """A dump row's detail: "rows: " and the counts as JSON, with nothing after them (the
    pre-phase-5 code reads it with json.loads of everything after "rows: ")."""
    return _ROWS + json.dumps(counts, sort_keys=True)


def parse_dump_detail(detail):
    """The counts in a dump row's detail (dump_detail's format) as a dict, or None."""
    if not detail or not detail.startswith(_ROWS):
        return None
    try:
        counts = json.loads(detail[len(_ROWS):])
    except ValueError:
        return None
    return counts if isinstance(counts, dict) else None


def recorded(name, dbname=None):
    """(counts, digests) recorded with the dump called name (its last row that has counts), each
    None when that dump has none (digests: a dump made before phase 5)."""
    with db.connect("ro", dbname=dbname, autocommit=True) as c:
        # to_jsonb(b)->'digests': null, not an error, while migration 0007 (the column) isn't applied.
        rows = c.execute("select path, detail, to_jsonb(b) -> 'digests' from ops.backup_run b where kind = 'dump' "
                         "and detail like %s order by id desc limit 500", (_ROWS + "%",)).fetchall()
    for path, detail, digests in rows:
        if path and Path(path).name == name:
            counts = parse_dump_detail(detail)
            if counts is not None:
                return counts, (digests if isinstance(digests, dict) else None)
    return None, None


def recorded_counts(name, dbname=None):
    """The row counts recorded with the dump called name (its last row that has them), or None."""
    return recorded(name, dbname)[0]


# ------------------------------------------------------------ counting rows

def tables(c):
    """Every table in the public, audit and ops schemas, as schema.table names, sorted."""
    rows = c.execute("select n.nspname, c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                     "where c.relkind in ('r', 'p') and n.nspname = any(%s) order by 1, 2",
                     (list(SCHEMAS),)).fetchall()
    return [f"{s}.{t}" for s, t in rows]


def count_rows(c):
    """{schema.table: exact row count} for every table tables() lists."""
    from psycopg import sql
    out = {}
    for name in tables(c):
        schema, table = name.split(".", 1)
        out[name] = c.execute(sql.SQL("select count(*) from {}.{}").format(
            sql.Identifier(schema), sql.Identifier(table))).fetchone()[0]
    return out


def digest_rows(c):
    """{schema.table: md5 of its rows' text} for every public and audit table tables() lists:
    each row as PostgreSQL writes it as text, sorted bytewise (collate "C", so the database's
    collation can't reorder them), joined by newlines. Read under DIGEST_SETTINGS (for the open
    transaction when c has one, else for the session), so the live database and a restored copy
    write every value alike."""
    from psycopg import sql
    from psycopg.pq import TransactionStatus
    local = c.info.transaction_status != TransactionStatus.IDLE
    for name, value in DIGEST_SETTINGS:
        c.execute(sql.SQL("set local {} = {}" if local else "set {} = {}").format(
            sql.Identifier(name), sql.Literal(value)))
    out = {}
    for name in tables(c):
        schema, table = name.split(".", 1)
        if schema not in DIGEST_SCHEMAS:
            continue
        out[name] = c.execute(sql.SQL(
            "select md5(coalesce(string_agg(t::text, E'\\n' order by t::text collate \"C\"), '')) from {}.{} t"
        ).format(sql.Identifier(schema), sql.Identifier(table))).fetchone()[0]
    return out


def compare_digests(expected, actual):
    """The tables whose content differs between two {table: digest} dicts, as plain-English
    lines (none: the same). Only tables both have are compared: compare_counts reports the rest."""
    return [f"{name}'s rows differ from the ones dumped" for name in sorted(set(expected) & set(actual))
            if expected[name] != actual[name]]


def compare_counts(expected, actual):
    """The differences between two {table: count} dicts, as plain-English lines (none: same)."""
    lines = []
    for name in sorted(set(expected) | set(actual)):
        if name not in actual:
            lines.append(f"{name} is missing from the restored copy")
        elif name not in expected:
            lines.append(f"{name} is in the restored copy but wasn't in the database")
        elif expected[name] != actual[name]:
            lines.append(f"{name} has {actual[name]} row(s) restored, {expected[name]} dumped")
    return lines


# ------------------------------------------------------------ running pg_dump / pg_restore

def _tool(args):
    """Run a PostgreSQL program with no window; (ok, what it said on failure)."""
    try:
        done = subprocess.run([str(a) for a in args], capture_output=True, stdin=subprocess.DEVNULL,
                              timeout=TOOL_TIMEOUT, **_SPAWN)
    except subprocess.TimeoutExpired:
        return False, f"{Path(args[0]).name} didn't finish within {TOOL_TIMEOUT // 60} minutes"
    except OSError as e:
        return False, f"{Path(args[0]).name} can't run: {e}"
    if done.returncode == 0:
        return True, ""
    text = (done.stderr or done.stdout or b"").decode("utf-8", "replace").strip().splitlines()
    return False, " ".join(text[-3:]) or f"{Path(args[0]).name} failed (exit code {done.returncode})"


def _connection_args(s, dbname):
    return ["-w", "-h", s["host"], "-p", str(s["port"]), "-U", db.ROLES["owner"], "-d", dbname]


def _remove(path):
    try:
        Path(path).unlink()
    except OSError:
        pass


def dump(target, s=None):
    """pg_dump the settings' database into target (written as target.partial, then renamed),
    reading the same snapshot the row counts and the content digests (digest_rows) are taken in.
    Returns (ok, counts, digests, detail)."""
    from psycopg import IsolationLevel
    s = s or db.settings()
    target = Path(target)
    partial = target.with_name(target.name + PARTIAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    with db.connect("owner", dbname=s["name"]) as c:
        c.isolation_level = IsolationLevel.REPEATABLE_READ
        c.read_only = True
        snapshot = c.execute("select pg_export_snapshot()").fetchone()[0]
        counts = count_rows(c)
        digests = digest_rows(c)
        ok, detail = _tool([db.pg_bin("pg_dump"), "-Fc", *_connection_args(s, s["name"]),
                            "--snapshot", snapshot, "-f", partial])
        c.rollback()
    if not ok:
        _remove(partial)
        return False, counts, digests, detail
    os.replace(partial, target)
    return True, counts, digests, ""


def copy_to(source, folder):
    """Copy a dump into folder (as .partial, then renamed). Returns the copy's Path."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / Path(source).name
    partial = target.with_name(target.name + PARTIAL)
    try:
        shutil.copyfile(source, partial)
        if partial.stat().st_size != Path(source).stat().st_size:
            raise OSError("the copy's size differs from the dump's")
        os.replace(partial, target)
    except OSError:
        _remove(partial)
        raise
    return target


# ------------------------------------------------------------ the commands

def run_backup(dest=None, say=say):
    """The backup command: dump into the staging folder, then copy to dest (default the
    settings' backup_dir, the NAS). The staging file stays either way (prune thins it out).
    Returns 0, or 1 when the dump or the copy failed (recorded with ok false)."""
    s = db.settings()
    dest = dest or s["backup_dir"]
    dest = Path(dest) if dest else None
    started = datetime.now()
    local = Path(s["staging_dir"]) / dump_name(started)
    try:
        db.pg_bin("pg_dump")
    except FileNotFoundError as e:
        record("dump", started, False, None, None, str(e))
        say(f"Backup failed: {e}")
        return 1
    try:
        ok, counts, digests, detail = dump(local, s)
    except OSError as e:
        ok, counts, digests, detail = False, None, None, f"the dump couldn't be made in {local.parent}: {e}"
    if not ok:
        record("dump", started, False, local, None, f"pg_dump failed: {detail}")
        say(f"Backup failed: pg_dump didn't work: {detail}")
        return 1
    size = local.stat().st_size
    rows = dump_detail(counts)
    if dest is None:
        record("dump", started, True, local, size, rows, digests=digests)
        say(f"Backup made: {local} ({size:,} bytes, {sum(counts.values()):,} rows in {len(counts)} tables). "
            'It stays on this computer only: set "backup_dir" in config.json\'s "database" block to copy '
            "each dump to another disk too.")
        return 0
    try:
        copy = copy_to(local, dest)
    except OSError as e:
        record("dump", started, False, local, size, f"copy to {dest} failed: {e}; {rows}", digests=digests)
        say(f"Backup made ({local}, {size:,} bytes), but it couldn't be copied to {dest}: {e}. "
            "The local copy is kept.")
        return 1
    record("dump", started, True, copy, size, rows, digests=digests)
    say(f"Backup made: {copy} ({size:,} bytes, {sum(counts.values()):,} rows in {len(counts)} tables).")
    return 0


def stale_partials(folder, now=None):
    """The decklab-*.dump.partial files in folder last written more than PARTIAL_MAX_AGE ago:
    left by a dump or copy that was killed partway (a power cut, the task's time limit)."""
    now = datetime.now().timestamp() if now is None else now
    out = []
    for p in Path(folder).iterdir():
        if p.name.endswith(PARTIAL) and dump_date(p.name[:-len(PARTIAL)]) and p.is_file() \
                and now - p.stat().st_mtime > PARTIAL_MAX_AGE:
            out.append(p.name)
    return sorted(out)


def prune_folder(folder, today=None, s=None):
    """Delete folder's dumps outside the retention, and dead runs' leftover .partial files.
    Returns the names deleted."""
    s = s or db.settings()
    _, delete = plan_prune(dumps_in(folder), today or date.today(), int(s["keep_daily"]), int(s["keep_weekly"]))
    delete = delete + stale_partials(folder)
    for name in delete:
        (Path(folder) / name).unlink()
    return delete


def run_prune(say=say):
    """The prune command, on the NAS folder and the staging folder. Returns 0, or 1 when a
    folder couldn't be read or a dump couldn't be deleted."""
    s = db.settings()
    failed = False
    for label, folder in (("NAS", s["backup_dir"]), ("staging", s["staging_dir"])):
        if not folder:
            continue                        # no backup_dir: the dumps are in staging only
        if not Path(folder).is_dir():
            if label == "staging":
                continue                    # nothing dumped here yet
            say(f"Prune: the {label} folder {folder} can't be reached.")
            failed = True
            continue
        try:
            deleted = prune_folder(folder, s=s)
        except OSError as e:
            say(f"Prune: the {label} folder {folder} couldn't be pruned: {e}")
            failed = True
            continue
        kept = len(dumps_in(folder))
        say(f"Prune ({label}): deleted {len(deleted)} old dump(s), {kept} kept in {folder}.")
    return 1 if failed else 0


def _scratch_name(database):
    """A distinct scratch identifier, never one PostgreSQL would truncate to the live name."""
    if not isinstance(database, str) or not database or "\x00" in database:
        raise ValueError("A restore check needs a valid database name")
    name = database + RESTORE_SUFFIX
    try:
        safe = len(name.encode("utf-8")) <= MAX_IDENTIFIER_BYTES
    except UnicodeError:
        safe = False
    if not safe:
        raise ValueError("The database name is too long for a distinct restore-check database")
    return name


def _scratch_drop(c, name):
    # The check owns this exact scratch name. Its connections have already closed;
    # a normal DROP waits for disconnects and handles autovacuum without requesting
    # permission to terminate another role's backend. An unexpected active session
    # must refuse cleanup, rather than acquire broader signal privileges.
    if name != _scratch_name(db.settings()["name"]):
        raise ValueError("Only this database's restore-check scratch database may be dropped")
    from psycopg import sql
    c.execute(sql.SQL("drop database if exists {}").format(sql.Identifier(name)))


def run_restore_check(source=None, say=say):
    """The restore-check command: pg_restore the newest dump in source (default the NAS
    folder, or the staging folder without one) into <database>_restorecheck, compare every table's row count with the counts
    recorded when it was dumped, and every public and audit table's content with the digests
    recorded with them (a dump recorded before phase 5 has none: counts only), then drop the
    scratch database. Returns 0, or 1 on any failure or difference (recorded either way)."""
    import psycopg
    from psycopg import sql
    s = db.settings()
    source = Path(source or s["backup_dir"] or s["staging_dir"])
    started = datetime.now()
    scratch = _scratch_name(s["name"])

    def failed(text, path=None, size=None):
        record("restore_check", started, False, path, size, text)
        say(f"Restore check failed: {text}")
        return 1

    try:
        newest = newest_dump(source)
    except OSError as e:
        return failed(f"the folder {source} can't be read: {e}")
    if newest is None:
        return failed(f"there's no dump in {source}")
    size, note, digested = None, "", None
    try:
        size = newest.stat().st_size
        expected, expected_digests = recorded(newest.name)
        with db.connect("owner", dbname="postgres", autocommit=True) as c:
            _scratch_drop(c, scratch)
            c.execute(sql.SQL("create database {} encoding 'UTF8' template template0").format(
                sql.Identifier(scratch)))
            try:
                ok, detail = _tool([db.pg_bin("pg_restore"), *_connection_args(s, scratch), "--exit-on-error",
                                    newest])
                if not ok:
                    return failed(f"pg_restore of {newest.name} didn't work: {detail}", newest, size)
                with db.connect("owner", dbname=scratch, autocommit=True) as r:
                    actual = count_rows(r)
                    if expected is not None and expected_digests is not None:
                        digested = compare_digests(expected_digests, digest_rows(r))
                if expected is None:
                    # A dump made some other way: compare with the database as it is now, leaving
                    # out ops (its log has had rows added since, by this very check if no other).
                    with db.connect("owner", autocommit=True) as live:
                        expected = {k: v for k, v in count_rows(live).items() if not k.startswith("ops.")}
                    actual = {k: v for k, v in actual.items() if not k.startswith("ops.")}
                    note = " (no counts were recorded with it, so it was compared with the database now, ops left out)"
            finally:
                _scratch_drop(c, scratch)
    except (OSError, psycopg.Error) as e:
        # pg_restore.exe missing, the dump unreadable, a count failing: recorded like any failure.
        return failed(f"{newest.name} couldn't be checked: {e}", newest, size)
    differences = compare_counts(expected, actual)
    if differences:
        return failed(f"{newest.name} restored with different row counts{note}: " + "; ".join(differences),
                      newest, size)
    if digested:
        return failed(f"{newest.name} restored with different contents: " + "; ".join(digested), newest, size)
    total = sum(actual.values())
    if digested is None and not note:
        note = " (no content digests were recorded with it, so only the counts were compared)"
    same = "row counts" if digested is None else "row counts and contents"
    record("restore_check", started, True, newest, size, f"{len(actual)} tables, {total} rows{note}")
    say(f"Restore check passed: {newest.name} restored with the same {same} in all {len(actual)} "
        f"tables ({total:,} rows){note}.")
    return 0


def check_summary(run):
    """A 'check' run (latest()'s dict) in a few words: "passed", "passed (2 warnings)" or
    "FAILED: <its first failing sub-check> (<what it found>)" (or what its detail says when it
    isn't check.py's JSON)."""
    try:
        detail = json.loads(run["detail"] or "")
    except ValueError:
        detail = None
    checks = detail.get("checks") if isinstance(detail, dict) else None
    if not isinstance(checks, list):
        return "passed" if run["ok"] else f"FAILED: {run['detail'] or 'no detail recorded'}"
    failed = [c for c in checks if isinstance(c, dict) and not c.get("ok")]
    if not run["ok"] or failed:
        first = failed[0] if failed else {}
        return f"FAILED: {first.get('name', 'the check')}" + (f" ({first['detail']})" if first.get("detail") else "")
    warned = sum(1 for c in checks if isinstance(c, dict) and c.get("warning"))
    return "passed" + (f" ({warned} warning{'s' if warned != 1 else ''})" if warned else "")


def side_by_side_until(s=None):
    """config.json's database.side_by_side_until (YYYY-MM-DD: the last day of the week of
    side-by-side checks after the move to the database) as a date, or None when it isn't set
    or isn't a date."""
    value = (s or db.settings()).get("side_by_side_until")
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def status(dbname=None, now=None):
    """The backups part of `status`, as a list of lines."""
    s = db.settings()
    last = last_ok(dbname)
    newest = latest(("check", "restore_check"), dbname)
    now = (now or datetime.now()).astimezone()

    def when(kind, label):
        at = last[kind]
        return f"  {label}: {at.astimezone():%Y-%m-%d %H:%M}" if at else f"  {label}: never"

    def restore_line():
        run = newest["restore_check"]
        if run is None or run["ok"]:
            return when("restore_check", "last restore check")
        line = f"  last restore check: {run['started_at'].astimezone():%Y-%m-%d %H:%M}, FAILED: {run['detail']}"
        at = last["restore_check"]
        return line + (f" (the last that worked: {at.astimezone():%Y-%m-%d %H:%M})" if at else "")

    def check_line():
        run = newest["check"]
        if run is None:
            return "  last check: never (python -m decklab.db check)"
        return f"  last check: {run['started_at'].astimezone():%Y-%m-%d %H:%M}, {check_summary(run)}"

    lines = ["Backups:", when("dump", "last dump"), when("export", "last export"), restore_line(), check_line()]
    until = side_by_side_until(s)
    if until is not None:
        state = "until" if until >= now.date() else "ended"
        lines.append(f"  Side-by-side checks: {state} {until:%Y-%m-%d} (python -m decklab.db check --history "
                     "lists each night's).")
    hours = float(s["stale_backup_hours"])
    if last["dump"] is None:
        lines.append("  WARNING: no dump has worked yet (python -m decklab.db backup).")
    elif now - last["dump"] > timedelta(hours=hours):
        age = (now - last["dump"]).total_seconds() / 3600
        lines.append(f"  WARNING: the last dump that worked is {age:.0f} hours old (more than {hours:g}); "
                     "check decklab/data/logs/db.log and the nightly task (python -m decklab.db schedule status).")
    run = newest["check"]
    if run is not None and not run["ok"]:
        lines.append("  WARNING: the last check found a problem (python -m decklab.db check --history says which).")
    return lines
