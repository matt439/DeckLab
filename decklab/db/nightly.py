"""What the "Deck Lab database backup" task runs each night (schedule.py): a backup, a prune,
the visits older than about a year deleted (visits.py), an export, the check of the data
(check.py), and a restore check when the last one that worked is more than restore_check_days
old (28: about monthly).

Every step runs even when an earlier one failed (an unreachable NAS is no reason to skip the
export), and each one's outcome goes into decklab/data/logs/db.log. The check comes after the
backup and the export, so a problem it finds never stops either. It runs under pythonw, with no
window and no console, so the log is where to look; `python -m decklab.db status` warns when the
last dump that worked is old or the last check failed (and the footer tells an admin).
"""
import traceback
from datetime import datetime, timedelta

from decklab.db import backup, conn as db


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


def run():
    """The nightly job. Returns 0, or 1 when any step failed."""
    from decklab.db import check, export, visits
    db.log("Nightly: starting.")
    steps = [("backup", backup.run_backup), ("prune", backup.run_prune), ("visits", visits.run_prune),
             ("export", export.run_export),
             ("check", check.run), ("restore check", _restore_check_if_due)]
    failed = [label for label, func in steps if not _step(label, func)]
    if failed:
        db.log(f"Nightly: finished; failed: {', '.join(failed)}.")
        return 1
    db.log("Nightly: finished; every step worked.")
    return 0
