"""Settings' "Reference facts to review" line (E11-S71): the hand-maintained fact groups whose review
is overdue (decklab/lib/stats/reviewed.py), for an admin.

    GET /api/settings/reference-facts

    {"today": "2026-11-10", "groups": 6,
     "announcement": "2026-02-09" or None (Wizards' newest Commander announcement, when known),
     "due": [{"id", "label", "source", "reviewed", "interval_days", "due_on", "days_overdue",
              "overdue": bool, "announced": date or None, "words"}],
     "line": "Reference facts to review: ..." or "" when nothing is due}

An admin by role, or a script naming nobody (as GET /api/visits); anyone else gets 403. Nothing here is
anyone's data: the dates are constants in the code, and the announcement's date is what the daily card
data check last found in Wizards' sitemap (official_lists.read(): a file on the PC, never a fetch), the
one the Commander readiness panel compares the bracket rules with, so the line says a rule set is older
than an announcement without a Commander deck being opened. An announcement that was never found, or
can't be read, makes nothing due: only the review dates count then.
"""
from datetime import date, datetime, timezone

from decklab.lib import official_lists

from .common import ApiError

ADMINS_ONLY = "Reference facts are for admins."
OFFICIAL_FILE = None    # None: official_lists' official_lists.json; the tests point it at a fixture


def _day():
    return datetime.now(timezone.utc).date()


def _require_admin():
    from . import guard
    profile = guard.viewer()
    if profile is None and guard.script():
        return
    if profile is None or profile.get("role") != "admin":
        raise ApiError(403, ADMINS_ONLY)


def _announced():
    """The date of Wizards' newest Commander announcement the PC knows of, or None."""
    try:
        announcement = official_lists.read(OFFICIAL_FILE)["announcement"]
        return date.fromisoformat(announcement["date"]) if announcement else None
    except (OSError, KeyError, TypeError, ValueError):
        return None


def answer(today, announced):
    """The view's answer for a day and an announcement date (or None)."""
    from decklab.lib.stats import reviewed      # when first needed, as the other parts import stats
    found = reviewed.due(today, announced)
    return {"today": today.isoformat(), "groups": len(reviewed.FACTS),
            "announcement": announced.isoformat() if announced else None,
            "due": [{"id": record["id"], "label": record["label"], "source": record["source"],
                     "reviewed": record["reviewed"].isoformat(), "interval_days": record["interval_days"],
                     "due_on": record["due_on"].isoformat(), "days_overdue": record["days_overdue"],
                     "overdue": record["overdue"],
                     "announced": record["announced"].isoformat() if record["announced"] else None,
                     "words": reviewed.words(record)} for record in found],
            "line": reviewed.line(found)}


def reference_facts_view():
    """GET /api/settings/reference-facts (the module docstring)."""
    _require_admin()
    return answer(_day(), _announced())
