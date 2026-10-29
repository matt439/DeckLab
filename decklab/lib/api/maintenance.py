"""Admin-only recorded maintenance history; reading never runs or schedules a job.

Only operational dates and outcomes leave this module. Run details, paths, sizes
and digests are deliberately absent from both SELECTs and the response. Export
uses the existing nightly stale_backup_hours grace as its freshness policy.
"""
from datetime import datetime, timedelta, timezone
import math

from decklab.db import conn as db
from decklab.lib.state import pg

from . import guard
from .common import ApiError

KINDS = ("dump", "export", "check", "restore_check")
RECENT_LIMIT = 5
ADMINS_ONLY = "Maintenance history is for signed-in admins."
UNAVAILABLE = "Maintenance history is unavailable right now. Try again later."

# Jobs record a row after completing. Attempt order is its actual start time,
# with the generated ID breaking ties, rather than its completion insertion order.
RECENT_SQL = """select kind, id, started_at, finished_at, ok from (
    select kind, id, started_at, finished_at, ok,
           row_number() over (partition by kind order by started_at desc, id desc) as run_rank
    from ops.backup_run where kind = any(%s)
) recent where run_rank <= %s order by kind, started_at desc, id desc"""
SUCCESS_SQL = """select distinct on (kind) kind, id, started_at, finished_at, ok
    from ops.backup_run where kind = any(%s) and ok and finished_at is not null
      and started_at <= %s and finished_at <= %s and finished_at >= started_at
    order by kind, started_at desc, id desc"""


def _admin():
    try:
        profile = guard.viewer()
    except ApiError:
        raise ApiError(403, ADMINS_ONLY) from None
    if not profile or not profile.get("id") or profile.get("role") != "admin":
        raise ApiError(403, ADMINS_ONLY)


def _date(value):
    if not isinstance(value, datetime):
        return None
    try:
        return value.astimezone(timezone.utc) if value.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def _run(row, now):
    _, _, started, finished, ok = row
    started, finished = _date(started), _date(finished)
    valid = started is not None and finished is not None and started <= finished <= now
    outcome = ("success" if ok else "failure") if valid and type(ok) is bool else "unknown"
    return {"started_at": started.isoformat() if started else None,
            "finished_at": finished.isoformat() if finished else None,
            "outcome": outcome}


def _order(row):
    # Invalid dates cannot be silently hidden behind a healthy dated record.
    started = _date(row[2]) or datetime.max.replace(tzinfo=timezone.utc)
    return started, row[1] if type(row[1]) is int else 0


def _interval(kind, settings):
    restore = kind == "restore_check"
    source = "restore_check_days" if restore else "stale_backup_hours"
    value = settings.get(source)
    try:
        value = float(value) if not isinstance(value, bool) else None
        if value is None or not math.isfinite(value) or value < 0:
            value = None
    except (TypeError, ValueError, OverflowError):
        value = None
    return {"value": value, "unit": "days" if restore else "hours", "source": source,
            "basis": "finished_at" if kind in ("dump", "export") else "started_at"}


def _freshness(latest, successful, interval, now):
    if successful is None:
        return "never" if latest is None or latest["outcome"] == "failure" else "unknown"
    if interval["value"] is None:
        return "unknown"
    stamp = _date(datetime.fromisoformat(successful[interval["basis"]]))
    try:
        limit = timedelta(**{interval["unit"]: interval["value"]})
    except OverflowError:
        return "unknown"
    age = now - stamp
    # The nightly restore scheduler runs when the last success started at least
    # restore_check_days ago; backup/check grace becomes stale only after its limit.
    stale = age >= limit if interval["source"] == "restore_check_days" else age > limit
    return "stale" if stale else "current"


def _project(recent, successful, settings, now):
    jobs = []
    for kind in KINDS:
        rows = sorted((row for row in recent if row[0] == kind), key=_order, reverse=True)[:RECENT_LIMIT]
        history = [_run(row, now) for row in rows]
        latest = history[0] if history else None
        passed = sorted((row for row in successful if row[0] == kind), key=_order, reverse=True)
        last = next((shown for row in passed if (shown := _run(row, now))["outcome"] == "success"), None)
        interval = _interval(kind, settings)
        freshness = _freshness(latest, last, interval, now)
        if latest is None:
            health = "never" if last is None else "unknown"
        elif latest["outcome"] == "failure":
            health = "failure"
        elif latest["outcome"] == "unknown":
            health = "unknown"
        else:
            health = {"current": "success", "stale": "stale"}.get(freshness, "unknown")
        jobs.append({"kind": kind, "latest": latest, "last_success": last, "recent": history,
                     "health": health, "freshness": freshness, "interval": interval})
    return {"available": True, "checked_at": now.isoformat(),
            "recent_limit": RECENT_LIMIT, "jobs": jobs}


def _read(connection):
    now = _date(connection.execute("select transaction_timestamp()").fetchone()[0])
    if now is None:
        raise ValueError("The history snapshot has no valid date")
    recent = connection.execute(RECENT_SQL, (list(KINDS), RECENT_LIMIT)).fetchall()
    successful = connection.execute(SUCCESS_SQL, (list(KINDS), now, now)).fetchall()
    return recent, successful, now


def maintenance_view():
    """GET /api/settings/maintenance: no script override for an unsigned request."""
    _admin()                    # before interval configuration or database reads
    try:
        settings = db.settings()
        with db.connect("app", timeout=pg.REQUEST_TIMEOUT, options=pg.REQUEST_OPTIONS) as connection:
            with connection.transaction():
                connection.execute("set transaction isolation level repeatable read, read only")
                recent, successful, now = _read(connection)
        return _project(recent, successful, settings, now)
    except Exception:
        # Raw connector/configuration errors can contain paths or credentials.
        raise ApiError(503, UNAVAILABLE, reason="maintenance") from None
