"""What the "Deck Lab database backup" task runs each night (schedule.py): a backup, a prune,
the visits older than about a year deleted (visits.py), an export, the check of the data
(check.py), a restore check when the last one that worked is more than restore_check_days
old (28: about monthly), and last the daily snapshots of the purchase queue's prices at
MTGMate and Games Portal (lib/shops/: one request a card name at each shop, a minute apart as
its robots.txt asks, the two shops side by side, each for at most NIGHTLY_BUDGET (45
minutes), so together they still take at most 45 minutes and the task's two-hour limit never
cuts them off; never a failed night, since a shop that can't be reached is nothing wrong with
the database, and one shop's failure never stops the other's). After the steps the heartbeat also
says whether the card data and the exchange rate are still refreshing (_card_data, E11-S85), again
never a failed night.

After a backup that worked, the shrink check (shrink.py, E11-S87), when config.json's
"database" block turns it on ("shrink_warn": true; off until Matt agrees its tables and
thresholds), compares the watched tables' counts with those of the newest good dump at least 20
hours older and logs a WARNING for each that shrank sharply; it never fails the night, but the
operator heartbeat gets "shrink" as failed. Off, it sends no "shrink" step.

Every step runs even when an earlier one failed (an unreachable NAS is no reason to skip the
export), and each one's outcome goes into decklab/data/logs/db.log. The check comes after the
backup and the export, so a problem it finds never stops either. It runs under pythonw, with no
window and no console, so the log is where to look; `python -m decklab.db status` warns when the
last dump that worked is old or the last check failed (and the footer tells an admin).

The whole run holds the PC awake (lib/keepawake.py's hold_while: a power request on Windows,
a systemd-inhibit block on Linux, nothing elsewhere), so a PC that sleeps when idle
(wake-on-request) doesn't fall asleep midway.

On Linux the timer's Persistent=true may start a missed run as soon as the user manager starts
at boot, before the system's PostgreSQL accepts connections (a user unit can't be ordered after
a system one), so the run first waits up to DB_WAIT seconds for the database (wait_for_database),
then runs every step either way. On Windows the task starts after logon and doesn't wait.
"""
import sys
import time
import traceback
from datetime import datetime, timedelta

from decklab.db import backup, conn as db

DB_WAIT = 180                     # seconds at most to wait for the database at the start (Linux)
DB_WAIT_EVERY = 10                # seconds between tries
DB_WAIT_CONNECT = 5               # seconds each try may take


def wait_for_database(limit=DB_WAIT, every=DB_WAIT_EVERY, *, connect=None, sleep=time.sleep,
                      clock=time.monotonic, log=None):
    """Try to connect as the owner until it works or limit seconds have passed. True when it
    worked. The first failure and the outcome are logged; psycopg missing isn't waited for (it
    won't appear), and anything but DbUnavailable is passed on."""
    log = log or db.log
    if connect is None:
        try:
            db._psycopg()
        except db.DbUnavailable:
            return False                  # the steps say so; waiting won't install it
        def connect():
            return db.connect("owner", timeout=DB_WAIT_CONNECT)
    started, tries = clock(), 0
    while True:
        tries += 1
        try:
            connection = connect()
        except db.DbUnavailable as e:
            waited = clock() - started
            if tries == 1:
                log(f"Nightly: the database can't be reached yet ({e}); waiting up to {round(limit)} seconds.")
            if waited + every > limit:
                log(f"Nightly: the database still can't be reached after {round(waited)} seconds; "
                    "running the steps anyway.")
                return False
            sleep(every)
            continue
        try:
            connection.close()
        except Exception:                 # noqa: BLE001 (only a check)
            pass
        if tries > 1:
            log(f"Nightly: the database answered after {round(clock() - started)} seconds.")
        return True


def restore_check_due(last, now, days):
    """True when a restore check is due: none has worked yet (last None), or the last one that
    worked started at least days ago."""
    return last is None or now - last >= timedelta(days=days)


def _step(label, func):
    """Run one step; True when it worked. A step that raises is logged, not passed on."""
    try:
        return func() == 0
    except Exception as e:                    # the next step still runs; the log says why
        db.log(f"Nightly: {label} failed: {type(e).__name__}: {e}")
        db.log("".join(traceback.format_exception(e)).rstrip())
        return False


def _restore_check_if_due():
    """The restore check, when the last that worked is restore_check_days old, or the newest
    one failed (so a failure is tried again the next night, not left until the days pass)."""
    s = db.settings()
    last = backup.last_ok()["restore_check"]
    newest = backup.latest(("restore_check",))["restore_check"]
    if newest is not None and not newest["ok"]:
        db.log("Nightly: restore check again tonight, as the last one failed.")
        return backup.run_restore_check()
    if not restore_check_due(last, datetime.now().astimezone(), float(s["restore_check_days"])):
        db.log(f"Nightly: no restore check tonight (the last one worked on {last.astimezone():%Y-%m-%d}).")
        return 0
    return backup.run_restore_check()


def _shrink_check():
    """E11-S87: whether no watched table shrank sharply since the night before's good dump
    (shrink.py); None when it couldn't be read or is off. Its lines go to db.log; it never fails the night."""
    from decklab.db import shrink
    try:
        return shrink.nightly(db.log)
    except Exception as e:                # noqa: BLE001 (a warning's check never stops the night)
        db.log(f"Nightly: the shrink check failed: {type(e).__name__}.")
        return None


def _shop_prices():
    from decklab.lib import shops
    return shops.nightly(db.log)


def _card_data():
    """The "card data" heartbeat step (E11-S85): True while Scryfall's card data and the exchange
    rate on the PC are still refreshing (lib/card_freshness.py, small files only, no fetch). Its one
    fixed warning sentence goes to the log. Like the shop health, it never fails the night: the
    database steps are what the night's result is about."""
    from decklab.lib import card_freshness
    found = card_freshness.check()
    if found["warning"]:
        db.log("Nightly: " + found["warning"])
    return not found["stale"]


def _disk_space(report=None):
    """Log free disk space and the data folders' sizes (lib/disk_space.py, E11-S86). False when a
    disk is under config.json's disk_space.warn_below_gb or can't be read: the heartbeat's
    "disk space" step, never a failed nightly (a full disk fails the steps that need room)."""
    try:
        if report is None:
            from decklab.lib.disk_space import report
        entries = report()
    except Exception as e:                    # noqa: BLE001 (a warning, never the nightly)
        db.log(f"Nightly: disk space couldn't be checked: {type(e).__name__}.")
        return False
    for entry in entries:
        db.log("Nightly: " + ("WARNING: " if entry["level"] == "warn" else "") + entry["text"])
    return not any(entry["level"] == "warn" for entry in entries)


def run():
    """The nightly job. Returns 0, or 1 when any step failed."""
    from decklab.lib import keepawake
    with keepawake.hold_while():
        if sys.platform.startswith("linux"):
            try:
                wait_for_database()
            except Exception as e:        # noqa: BLE001 (the steps still run and say what's wrong)
                db.log(f"Nightly: waiting for the database failed: {type(e).__name__}: {e}")
        started = datetime.now().astimezone()
        try:
            result = _run()
        except Exception:
            _receipt(started, False)
            from decklab.lib.operator_alerts import notify
            notify({"nightly": False}, log=db.log)
            raise
        _receipt(started, result == 0)
        return result


def _receipt(started, ok):
    """Summary only; older/unavailable databases cannot turn completed steps into failure."""
    try:
        backup.record("nightly", started, ok, detail="Whole nightly completed" if ok else "Whole nightly failed")
    except Exception:
        db.log("Nightly: whole-run receipt could not be saved; check migration 0023 and database availability.")


def _run():
    from decklab.db import check, export, visits
    db.log("Nightly: starting.")
    steps = [("backup", backup.run_backup), ("prune", backup.run_prune), ("visits", visits.run_prune),
             ("export", export.run_export),
             ("check", check.run), ("restore check", _restore_check_if_due), ("shop prices", _shop_prices)]
    outcomes = {label: _step(label, func) for label, func in steps}
    failed = [label for label, ok in outcomes.items() if not ok]
    shrunk = _shrink_check() if outcomes["backup"] else None
    if failed:
        db.log(f"Nightly: finished; failed: {', '.join(failed)}.")
    else:
        db.log("Nightly: finished; every step worked.")
    from decklab.lib.operator_alerts import notify
    from decklab.lib.shops.health import heartbeat_steps
    try:
        outcomes.update(heartbeat_steps(datetime.now().astimezone().date()))
    except Exception:
        outcomes["shop health"] = False
    try:
        outcomes["card data"] = _card_data()
    except Exception:
        db.log("Nightly: whether the card data is refreshing couldn't be checked.")
        outcomes["card data"] = False
    outcomes["disk space"] = _disk_space()      # a warning, apart from the steps' result
    if shrunk is not None:
        outcomes["shrink"] = shrunk        # a warning for the heartbeat, never a failed night
    notify({**outcomes, "nightly": not failed}, log=db.log)
    return 1 if failed else 0
