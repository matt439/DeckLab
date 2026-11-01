"""What the "Deck Lab database backup" task runs each night (schedule.py): a backup, a prune,
the visits older than about a year deleted (visits.py), an export, the check of the data
(check.py), a restore check when the last one that worked is more than restore_check_days
old (28: about monthly), and last the daily snapshots of the purchase queue's prices at
MTGMate and Games Portal (lib/shops/: one request a card name at each shop, a minute apart as
its robots.txt asks, the two shops side by side, each for at most NIGHTLY_BUDGET (45
minutes), so together they still take at most 45 minutes and the task's two-hour limit never
cuts them off; never a failed night, since a shop that can't be reached is nothing wrong with
the database, and one shop's failure never stops the other's).

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
    s = db.settings()
    last = backup.last_ok()["restore_check"]
    if not restore_check_due(last, datetime.now().astimezone(), float(s["restore_check_days"])):
        db.log(f"Nightly: no restore check tonight (the last one worked on {last.astimezone():%Y-%m-%d}).")
        return 0
    return backup.run_restore_check()


def _shop_prices():
    from decklab.lib import shops
    return shops.nightly(db.log)


def run():
    """The nightly job. Returns 0, or 1 when any step failed."""
    from decklab.lib import keepawake
    with keepawake.hold_while():
        if sys.platform.startswith("linux"):
            try:
                wait_for_database()
            except Exception as e:        # noqa: BLE001 (the steps still run and say what's wrong)
                db.log(f"Nightly: waiting for the database failed: {type(e).__name__}: {e}")
        return _run()


def _run():
    from decklab.db import check, export, visits
    db.log("Nightly: starting.")
    steps = [("backup", backup.run_backup), ("prune", backup.run_prune), ("visits", visits.run_prune),
             ("export", export.run_export),
             ("check", check.run), ("restore check", _restore_check_if_due), ("shop prices", _shop_prices)]
    failed = [label for label, func in steps if not _step(label, func)]
    if failed:
        db.log(f"Nightly: finished; failed: {', '.join(failed)}.")
        return 1
    db.log("Nightly: finished; every step worked.")
    return 0
