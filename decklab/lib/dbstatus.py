"""Whether Deck Lab's database can be used, for the footer: GET /api/status's "database" block.

Every open page polls /api/status about every 30 seconds, from every device, so the answer
can't open a connection each time. Instead a daemon thread (start(), at server startup)
checks once a minute with ONE app-role connection that gives up after TIMEOUT seconds (and
whose statements have the state store's lock and statement timeouts): which migrations are
still to apply (migrate.pending), whether phase 2's tables can be read (so a later pending
migration doesn't make the stores look broken), and when the last pg_dump that worked
finished (ops.backup_run), and how the newest nightly check of the data (check.py) and restore
check went. view() answers from that snapshot at once.

The check also feeds the state store's circuit breaker (lib/state/pg.BREAKER): it opens it
when the database stops answering (so requests fail fast at once rather than each waiting),
and closes it as soon as the database answers again (so requests needn't wait out its 30 s).
A check that fails some other way (a statement that timed out, an unexpected error) is
CHECK_FAILED and leaves the breaker alone: the database may well be answering.

Who sees what (view): everyone learns whether the stores can be used ("ok"); an admin learns
whether everything is in order instead, and also why not, in a few plain words (ERRORS), how
many migrations are pending, when the last backup was and whether it's older than
config.json's stale_backup_hours, a ready-made warning when the newest check of the data
failed, is older than stale_backup_hours or never ran, or the newest restore check failed
(checks_warning), and why .venv's packages aren't in use (lib/venv.py), when they aren't. The
raw detail goes only to db.log, once per change. An admin also learns whether the database
holds the inventory (its revision), and whether the pages are showing a stale copy because the
database can't be used (inventory_view).
"""
import threading
from datetime import datetime, timedelta

from decklab.db import conn as db
from decklab.lib import venv

REFRESH_SECONDS = 60
TIMEOUT = 2                         # seconds to connect before a check gives up

NOT_REACHABLE = "not reachable"
PSYCOPG_MISSING = "psycopg missing"
MIGRATIONS_PENDING = "migrations pending"
CHECK_FAILED = "check failed"
ERRORS = (NOT_REACHABLE, PSYCOPG_MISSING, MIGRATIONS_PENDING, CHECK_FAILED)
DOWN = (NOT_REACHABLE, PSYCOPG_MISSING)  # the errors meaning the database can't be used
# SQLSTATEs meaning the schema is older than this code (as lib/state/pg.NEEDS_MIGRATING).
NEEDS_MIGRATING = ("42P01", "42703", "42501")
# Phase 2's tables, the ones the state store reads: when each can be read, the stores work
# even with a later migration still to apply.
STATE_TABLES = ("wishlist_entry", "profile_setting", "simulation_mode", "play_record")
JOIN_SECONDS = 10                   # how long stop() waits for a check in progress to end

_lock = threading.Lock()
_snapshot = None                    # the last check's result, None before the first
_running = None                     # the running checker's (stop event, thread)


def _breaker():
    from decklab.lib.state import pg
    return pg.BREAKER


def _log(text):
    """A line in db.log; never raises (a log that can't be written mustn't stop the checks)."""
    try:
        db.log(f"dbstatus: {text}")
    except Exception:                               # noqa: BLE001
        pass


def _result(error=None, detail=None, pending=None, last=None, stale_hours=None, now=None, usable=None,
            inventory=None, runs=None):
    stale = warning = None
    if error in (None, MIGRATIONS_PENDING) and stale_hours is not None:
        now = (now or datetime.now()).astimezone()
        stale = last is None or now - last > timedelta(hours=stale_hours)
        if runs is not None:
            warning = checks_warning(runs.get("check"), runs.get("restore_check"), now, stale_hours)
    if usable is None:
        usable = error not in DOWN
    return {"ok": error is None, "usable": usable, "error": error, "detail": detail,
            "pending_migrations": pending,
            "last_backup": last.astimezone().isoformat(timespec="seconds") if last else None,
            "backup_stale": stale, "stale_hours": stale_hours, "inventory": inventory,
            "checks_warning": warning}


def _first_failure(detail):
    """The name of the first sub-check that failed in a check run's JSON detail, or None."""
    import json
    try:
        data = json.loads(detail or "")
    except ValueError:
        return None
    for sub in (data.get("checks") or []) if isinstance(data, dict) else []:
        if isinstance(sub, dict) and not sub.get("ok"):
            return sub.get("name")
    return None


def checks_warning(check, restore, now, hours):
    """The footer's warning about the nightly checks (an admin's only), or None: when the newest
    check of the data (check: {"ok", "started_at", "detail"} of its ops.backup_run row, None when
    none ran) failed, is older than hours or never ran, or the newest restore check (restore,
    the same) failed."""
    out = []
    if check is None:
        out.append("No check of the database's data has run yet. Run python -m decklab.db check on the PC "
                   "(the nightly task runs it).")
    elif not check["ok"]:
        name = _first_failure(check["detail"])
        out.append(f"The database check of {check['started_at'].astimezone():%Y-%m-%d %H:%M} found a problem"
                   + (f" ({name})" if name else "") + ". On the PC, python -m decklab.db check --history says more.")
    elif now - check["started_at"] > timedelta(hours=hours):
        out.append(f"The last check of the database's data ran on {check['started_at'].astimezone():%Y-%m-%d %H:%M} "
                   f"(more than {hours:g} hours ago). Check the nightly task: python -m decklab.db schedule status.")
    if restore is not None and not restore["ok"]:
        out.append(f"The restore check of a database backup on {restore['started_at'].astimezone():%Y-%m-%d %H:%M} "
                   "failed. On the PC, python -m decklab.db status says why.")
    return " ".join(out) or None


def _runs(c):
    """{kind: {"ok", "started_at", "detail"}} of the newest check and restore check run, read on c."""
    rows = c.execute("select distinct on (kind) kind, ok, started_at, detail from ops.backup_run "
                     "where kind in ('check', 'restore_check') order by kind, id desc").fetchall()
    return {kind: {"ok": ok, "started_at": started, "detail": detail} for kind, ok, started, detail in rows}


def _inventory(c):
    """What the database holds of the inventory, read on c: {"tables": whether migration 0004's
    tables are there, "revision": its revision as text (None: not imported), "imported_at": ISO
    or None}."""
    if c.execute("select to_regclass('public.inventory_revision') is null").fetchone()[0]:
        return {"tables": False, "revision": None, "imported_at": None}
    row = c.execute("select revision, imported_at from inventory_revision").fetchone()
    return {"tables": True, "revision": str(row[0]) if row else None,
            "imported_at": row[1].astimezone().isoformat(timespec="seconds") if row else None}


def check(dbname=None, now=None):
    """One check of the database, as a snapshot dict: ok (everything in order), usable (the
    stores can be used: reachable, and phase 2's tables readable), error (one of ERRORS, or
    None), detail (the raw reason, for db.log only), pending_migrations, last_backup (ISO,
    local time, or None), backup_stale (None when the database couldn't be read) and
    stale_hours (config.json's stale_backup_hours, the limit). Never raises.

    NOT_REACHABLE only when the database didn't answer: no connection, a connection error
    (class 08, or none at all) or a server shutting down or full (pg.DOWN_STATES). Any other
    failure is CHECK_FAILED, with usable left True: the stores report their own errors."""
    try:
        from decklab.db import migrate
        db._psycopg()
    except db.DbUnavailable as e:
        return _result(PSYCOPG_MISSING, str(e))
    except Exception as e:                          # noqa: BLE001 (the footer must still answer)
        return _result(CHECK_FAILED, f"{type(e).__name__}: {e}")
    import psycopg
    from decklab.lib.state import pg
    try:
        hours = float(db.settings()["stale_backup_hours"])
    except Exception:                               # noqa: BLE001 (an unreadable config.json: the default)
        hours = float(db.DEFAULTS["stale_backup_hours"])
    try:
        with db.connect("app", dbname=dbname, autocommit=True, timeout=TIMEOUT,
                        options=pg.REQUEST_OPTIONS) as c:
            try:
                pending = len(migrate.pending(conn=c))
                error = MIGRATIONS_PENDING if pending else None
                detail = f"{pending} migration(s) pending" if pending else None
            except migrate.MigrationError as e:
                pending, error, detail = None, MIGRATIONS_PENDING, str(e)
            usable = True
            if error is not None:
                try:
                    for table in STATE_TABLES:
                        c.execute(f"select 1 from public.{table} limit 0")
                except psycopg.Error as e:
                    if getattr(e, "sqlstate", None) not in NEEDS_MIGRATING:
                        raise
                    usable = False
            last = c.execute("select max(finished_at) from ops.backup_run where ok and kind = 'dump'").fetchone()[0]
            runs = _runs(c)
            inventory = _inventory(c)
    except db.DbUnavailable as e:
        return _result(NOT_REACHABLE, str(e))
    except psycopg.Error as e:
        text = (str(e).strip().splitlines() or ["no detail"])[0]
        state = getattr(e, "sqlstate", None) or ""
        if state in NEEDS_MIGRATING:
            return _result(MIGRATIONS_PENDING, text, usable=False)
        if (isinstance(e, (psycopg.OperationalError, psycopg.InterfaceError))
                and (not state or state.startswith("08") or state in pg.DOWN_STATES)):
            return _result(NOT_REACHABLE, text)
        return _result(CHECK_FAILED, text)
    except Exception as e:                          # noqa: BLE001 (the footer must still answer)
        return _result(CHECK_FAILED, f"{type(e).__name__}: {e}")
    return _result(error, detail, pending, last, hours, now, usable, inventory, runs)


def refresh(dbname=None):
    """Check now (check()), keep the snapshot for view(), and tell the breaker: closed when the
    database answered, opened when it stopped answering (only on the change, so db.log gets
    one line, not one a minute); a CHECK_FAILED leaves it as it is. A change of state is
    logged to db.log. Returns the snapshot."""
    global _snapshot
    result = check(dbname)
    with _lock:
        before, _snapshot = _snapshot, result
    reachable = result["error"] not in DOWN
    was_reachable = before is not None and before["error"] not in DOWN
    breaker = _breaker()
    if result["error"] == CHECK_FAILED:
        pass
    elif reachable:
        breaker.reset()
    elif was_reachable or before is None:
        breaker.trip(result["detail"] or result["error"])
    if before is None or (before["error"], before["detail"]) != (result["error"], result["detail"]):
        _log(describe(result) + (f" ({result['detail']})" if result["detail"] else ""))
    return result


def describe(snapshot):
    """A snapshot in a few words, for the server log: "reachable", "not reachable",
    "psycopg missing", "the check failed (db.log says why)" or "reachable, 1 migration
    pending (python -m decklab.db migrate)"."""
    if snapshot["error"] is None:
        return "reachable"
    if snapshot["error"] == CHECK_FAILED:
        return "the check failed (db.log says why)"
    if snapshot["error"] == MIGRATIONS_PENDING:
        n = snapshot["pending_migrations"]
        what = f"{n} migration{'s' if n != 1 else ''} pending" if n else "the migrations need attention"
        return f"reachable, {what} (python -m decklab.db migrate)"
    return snapshot["error"]


def start(first=None, dbname=None):
    """Start the checker thread (stopping one already running): it checks at once, calls
    first(snapshot) after that first check when given, then checks every REFRESH_SECONDS
    until stop(). Returns at once."""
    global _running
    stop()
    event = threading.Event()

    def safe_refresh():
        try:
            return refresh(dbname)
        except Exception as e:                      # noqa: BLE001 (the thread must keep checking)
            _log(f"the check failed: {type(e).__name__}: {e}")
            return _result(CHECK_FAILED, f"{type(e).__name__}: {e}")

    def loop():
        result = safe_refresh()
        if first is not None and not event.is_set():
            try:
                first(result)
            except Exception as e:                  # noqa: BLE001
                _log(f"the start-up report failed: {type(e).__name__}: {e}")
        while not event.wait(REFRESH_SECONDS):
            safe_refresh()

    thread = threading.Thread(target=loop, name="database-status", daemon=True)
    with _lock:
        _running = (event, thread)
    thread.start()


def stop():
    """Stop the checker thread, if one runs: it finishes a check in progress (stop() waits up
    to JOIN_SECONDS for that), then ends. The last snapshot stays for view()."""
    global _running
    with _lock:
        running, _running = _running, None
    if running is not None:
        event, thread = running
        event.set()
        if thread is not threading.current_thread():
            thread.join(JOIN_SECONDS)


def _is_admin(viewer, script):
    """By role: an admin profile, or no profile at all from a script (guard.script(); as
    permissions.activity_scope). The page before anyone is chosen isn't one."""
    if viewer is None:
        return bool(script)
    return viewer.get("role") == "admin"


def view(viewer, *, script=False):
    """/api/status's "database" block for viewer (a config.json profile dict, or None; script:
    the request is a script's, guard.script()). {"ok": None, "checking": True} before the first
    check; for most just {"ok"}, whether the stores can be used (so a pending migration they
    don't need isn't news to them); for an admin "ok" is whether everything is in order, plus
    usable, error, pending_migrations, last_backup, backup_stale, stale_hours (the limit it's
    judged by), checks_warning (checks_warning's words, or None) and venv (why .venv's packages
    aren't in use, or None, with any absolute paths cut as api.common._strip_paths does: the
    server log has them in full)."""
    with _lock:
        snapshot = _snapshot
    if snapshot is None:
        return {"ok": None, "checking": True}
    if not _is_admin(viewer, script):
        return {"ok": snapshot["usable"]}
    return {"ok": snapshot["ok"], "usable": snapshot["usable"], "error": snapshot["error"],
            "pending_migrations": snapshot["pending_migrations"],
            "last_backup": snapshot["last_backup"], "backup_stale": snapshot["backup_stale"],
            "stale_hours": snapshot["stale_hours"], "checks_warning": snapshot.get("checks_warning"),
            "venv": _venv_reason(),
            "inventory": inventory_view(snapshot)}


def inventory_view(snapshot):
    """The inventory part of an admin's block: {"imported": whether the database holds an
    inventory (None when it couldn't be read), "revision", "imported_at", and "stale": True when
    the database can't be used now, so the pages show the last snapshot the server loaded
    (inventory/pg.py) and changes to it can't be saved (no migration 0004 counts too);
    "not_imported": True when there's nothing in the database to read}."""
    held = snapshot.get("inventory")
    imported = None if held is None else held["revision"] is not None
    # Migration 0004 not applied (no inventory tables): the database can't serve the inventory
    # even though phase 2's tables leave it usable, and it isn't that nothing was imported.
    no_tables = held is not None and held.get("tables") is False
    return {"imported": imported,
            "revision": held["revision"] if held else None, "imported_at": held["imported_at"] if held else None,
            "stale": not snapshot["usable"] or no_tables,
            "not_imported": imported is False and not no_tables}


def _venv_reason():
    """venv.reason() without absolute paths (the Windows user name, the folder layout): an
    admin can see it through the tunnel too."""
    reason = venv.reason()
    if not reason:
        return None
    from decklab.lib.api.common import _strip_paths
    return _strip_paths(reason)
