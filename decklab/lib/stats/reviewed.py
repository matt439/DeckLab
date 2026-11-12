"""The reference facts Deck Lab's authors looked up by hand, each with the date it was last reviewed
(E11-S71), so that a figure doesn't go stale unnoticed.

Nothing here is a figure: FACTS is an index pointing at the constants that already hold them and their
dates. Each record:

    id          a short key
    label       what the page calls the group
    source      where the facts come from, in words
    where       the constants that hold the facts, as "module.NAME"
    reviewed    (module, NAME[, key]): the constant holding the date a person last compared them with
                their source (YYYY-MM-DD)
    interval    days after that date before a review is due again
    through     (module, NAME[, key]) or None: for the facts that follow Wizards' Commander
                announcements, the constant holding the date of the newest announcement they've been
                reviewed through

To record a review, change the date constant a record points at (and the facts, if they changed): never
a date here. The intervals are our choice: a year for published figures that change rarely, half a year
for another site's page layout and for the rules Wizards revises.

From code:

    from decklab.lib.stats import reviewed
    reviewed.records()                  # every group, its dates read from the constants
    reviewed.due(date.today())          # the groups whose review is overdue, the most overdue first
    reviewed.due(today, announced)      # also those older than a Commander announcement of that date
    reviewed.line(reviewed.due(today))  # "Reference facts to review: ..." or "" when none is due

due() fetches nothing and reads no file: the caller passes the announcement's date
(official_lists.read(), as the Commander checks do). The Settings page's line is
decklab/lib/api/reference_facts.py's.
"""
from datetime import date, timedelta
from importlib import import_module

_CONSTANTS = "decklab.lib.stats.constants"
_ROLE_TARGETS = "decklab.lib.stats.role_targets"
_EDHREC = "decklab.lib.edhrec"
_AVERAGE_DECKS = "decklab.lib.gauntlet.edhrec_source"
_TUNNEL = "decklab.lib.tunnel"

HALF_YEAR = 182
YEAR = 365

FACTS = (
    {"id": "bracket-rules", "label": "Commander bracket rules",
     "source": "Wizards' Commander Brackets announcements",
     "where": (f"{_CONSTANTS}.BRACKETS", f"{_CONSTANTS}.BRACKET_NOT_AUTOMATIC",
               f"{_CONSTANTS}.UPGRADED_MAX_GAME_CHANGERS"),
     "reviewed": (_CONSTANTS, "BRACKET_RULES_CHECKED"), "interval": HALF_YEAR,
     "through": (_CONSTANTS, "BRACKET_RULES_DATE")},
    {"id": "tutor-wording", "label": "Commander bracket tutor wording",
     "source": "Wizards' Commander Brackets announcements",
     "where": (f"{_CONSTANTS}.BRACKET_TUTORS",),
     "reviewed": (_CONSTANTS, "BRACKET_TUTORS", "read_on"), "interval": HALF_YEAR,
     "through": (_CONSTANTS, "BRACKET_TUTORS", "reviewed_through")},
    {"id": "karsten", "label": "Karsten's land and colour-source figures",
     "source": "Frank Karsten's land-count and coloured-source articles",
     "where": (f"{_CONSTANTS}.LAND_FORMULAS", f"{_CONSTANTS}.COLOUR_SOURCES_NEEDED",
               f"{_CONSTANTS}.COLOUR_SOURCE_RULES"),
     "reviewed": (_CONSTANTS, "KARSTEN_CHECKED"), "interval": YEAR, "through": None},
    {"id": "role-targets", "label": "Command Zone role targets",
     "source": "The Command Zone's deck-building template (episode 658)",
     "where": (f"{_ROLE_TARGETS}.CATEGORIES",),
     "reviewed": (_ROLE_TARGETS, "CHECKED"), "interval": YEAR, "through": None},
    {"id": "edhrec-page", "label": "EDHREC's commander page layout",
     "source": "EDHREC's commander pages (json.edhrec.com)",
     "where": (f"{_EDHREC}.reduce_page", f"{_EDHREC}.commander_slugs"),
     "reviewed": (_EDHREC, "SHAPE_CHECKED"), "interval": HALF_YEAR, "through": None},
    {"id": "edhrec-average-decks", "label": "EDHREC's average-deck layout (the gauntlet)",
     "source": "EDHREC's average decks and top commanders (json.edhrec.com)",
     "where": (f"{_AVERAGE_DECKS}.TOP_PATH", f"{_AVERAGE_DECKS}.AVERAGE_PATH"),
     "reviewed": (_AVERAGE_DECKS, "SHAPE_CHECKED"), "interval": HALF_YEAR, "through": None},
    {"id": "cloudflared-support", "label": "Cloudflare's cloudflared support window",
     "source": "Cloudflare's cloudflared downloads page (its Updates part)",
     "where": (f"{_TUNNEL}.SUPPORT_DAYS", f"{_TUNNEL}.SUPPORT_SOURCE"),
     "reviewed": (_TUNNEL, "SUPPORT_POLICY_CHECKED"), "interval": HALF_YEAR, "through": None},
)


def _constant(pointer):
    """The date a (module, NAME[, key]) pointer names, read now so a changed constant is seen."""
    module, name, *keys = pointer
    value = getattr(import_module(module), name)
    for key in keys:
        value = value[key]
    return date.fromisoformat(value)


def records():
    """Every group as {"id", "label", "source", "where": [...], "reviewed", "interval_days", "due_on",
    "reviewed_through" (or None)}, dates as date objects, in FACTS' order. Raises when a constant a
    record points at is missing or isn't a YYYY-MM-DD date (a mistake in the code, caught by the tests)."""
    found = []
    for fact in FACTS:
        checked = _constant(fact["reviewed"])
        found.append({"id": fact["id"], "label": fact["label"], "source": fact["source"],
                      "where": list(fact["where"]), "reviewed": checked, "interval_days": fact["interval"],
                      "due_on": checked + timedelta(days=fact["interval"]),
                      "reviewed_through": _constant(fact["through"]) if fact["through"] else None})
    return found


def due(today, announced=None):
    """The groups to review on `today` (a date): those past their interval, and, when `announced` (the
    date of Wizards' newest Commander announcement, or None when it isn't known) is given, those
    reviewed only through an older announcement. Each is its records() entry with "days_overdue" (0 when
    only the announcement makes it due), "overdue" (past its interval) and "announced" (the newer
    announcement's date, or None). The most overdue first, then FACTS' order. A group reviewed on a
    date after today (a wrong clock) isn't due."""
    found = []
    for record in records():
        late = (today - record["due_on"]).days
        newer = bool(announced and record["reviewed_through"] and record["reviewed_through"] < announced)
        if late > 0 or newer:
            found.append({**record, "days_overdue": max(late, 0), "overdue": late > 0,
                          "announced": announced if newer else None})
    found.sort(key=lambda record: -record["days_overdue"])       # stable: FACTS' order within a tie
    return found


def words(record):
    """One due() entry in words: "Commander bracket rules (last reviewed 2026-09-29; Wizards made a
    Commander announcement on 2026-12-01, newer than the 2026-02-09 one it was reviewed through)"."""
    reasons = [f"last reviewed {record['reviewed'].isoformat()}"]
    if record["overdue"]:
        days = record["interval_days"]
        reasons.append(f"due every {days} days")
    if record["announced"]:
        reasons.append(f"Wizards made a Commander announcement on {record['announced'].isoformat()}, "
                       f"newer than the {record['reviewed_through'].isoformat()} one it was reviewed through")
    return f"{record['label']} ({'; '.join(reasons)})"


def line(found):
    """The Settings page's line for due()'s entries, or "" when there are none."""
    if not found:
        return ""
    return "Reference facts to review: " + "; ".join(words(record) for record in found) + "."
