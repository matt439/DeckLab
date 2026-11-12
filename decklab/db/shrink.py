"""A warning when a key table shrank sharply between two good dumps (E11-S87).

Each good dump's ops.backup_run row keeps the exact row count of every table (backup.dump_detail).
After the nightly backup, compare() looks at the WATCHED tables in the newest good dump's counts
against those of the newest good dump at least MIN_GAP_HOURS older (normally the night before),
so a mistaken bulk removal or a bad import shows the next morning, while the prune (14 dailies)
still keeps the dumps from before it. The earlier dump is chosen by time, not by position: a dump
taken in between (a manual `backup`, or `python -m decklab.update`'s pre-migration backup) already
holds the shrunk counts, and comparing with it would hide the loss.

What it says is whole-table counts only: a table's label, from what count to what, and the
earlier dump's date; never a space, a row or anything a row holds. The lines go to
`python -m decklab.db status` (under Backups) and the nightly's log, and the nightly's operator
heartbeat gets the fixed step name "shrink" as failed (nothing else leaves the PC). A shrink is
a warning, never a failed night: the backup itself worked.

OFF until Matt agrees the watched tables and the thresholds: config.json's "database" block
turns it on with "shrink_warn": true. Off, the nightly runs no check and sends no "shrink" step,
and `status` shows nothing for it.

The watched tables and the thresholds are PROPOSED defaults, waiting on Matt's agreement:
a table counts as shrunk when it lost more than PROPOSED_PERCENT per cent of its rows AND at
least PROPOSED_MIN_ROWS rows (so a small table losing one row doesn't warn). config.json's
"database" block may set "shrink_warn_percent" and "shrink_warn_rows" to change them.
"""
from datetime import timedelta

from decklab.db import backup, conn as db

# label -> schema.table, as backup.count_rows names them. PROPOSED: Matt agrees the list.
WATCHED = (
    ("collection", "public.collection_card"),
    ("decks", "public.deck"),
    ("token cards", "public.token_card"),
    ("orders", "public.purchase_order"),
    ("wishlists", "public.wishlist_entry"),
    ("accessories", "public.accessory"),
)
PROPOSED_PERCENT = 25             # more than this share of a table's rows gone (per cent)
PROPOSED_MIN_ROWS = 5             # and at least this many rows gone
MIN_GAP_HOURS = 20                # the earlier dump is at least this much older than the newest
RECENT = 60                       # dump rows read to find the two good ones with counts
ENABLED_KEY = "shrink_warn"
PERCENT_KEY, ROWS_KEY = "shrink_warn_percent", "shrink_warn_rows"
SHRANK, MISSING = "shrank", "missing"


def enabled(s=None):
    """Whether config.json's "database" block turned the check on ("shrink_warn": true); off by
    default until Matt agrees the watched tables and thresholds."""
    s = s if s is not None else db.settings()
    return s.get(ENABLED_KEY) is True


def thresholds(s=None):
    """(percent, min_rows) from config.json's "database" block, each falling back to the
    proposed default when it isn't set or isn't a sensible number."""
    s = s if s is not None else db.settings()

    def number(key, default, low, high, kind):
        value = s.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        value = kind(value)
        return value if low <= value <= high else default
    return (number(PERCENT_KEY, PROPOSED_PERCENT, 1, 100, float),
            number(ROWS_KEY, PROPOSED_MIN_ROWS, 1, 10_000_000, int))


def _count(counts, table):
    value = counts.get(table) if isinstance(counts, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def compare(previous, current, *, watched=WATCHED, percent=PROPOSED_PERCENT, min_rows=PROPOSED_MIN_ROWS):
    """The watched tables that shrank sharply or couldn't be compared between two dumps' recorded
    counts ({schema.table: count}), in watched's order: each {"label", "table", "kind" (SHRANK or
    MISSING), "before", "after"} (None for a count a dump lacks). A table shrank when it lost
    at least min_rows rows and more than percent per cent of them. Pure."""
    out = []
    for label, table in watched:
        before, after = _count(previous, table), _count(current, table)
        if before is None or after is None:
            out.append({"label": label, "table": table, "kind": MISSING, "before": before, "after": after})
            continue
        lost = before - after
        if lost >= min_rows and lost * 100 > percent * before:
            out.append({"label": label, "table": table, "kind": SHRANK, "before": before, "after": after})
    return out


def pair(rows, min_gap_hours=MIN_GAP_HOURS):
    """The two dumps to compare, from ops.backup_run dump rows newest first (each (ok, started_at,
    detail)): (previous, current), each {"started_at", "counts"}, or None when the newest dump
    didn't work or has no counts, or no good dump with counts is at least min_gap_hours older.
    The earlier one is the newest good dump that old, skipping any taken in between (a manual
    backup, an update's pre-migration backup), which would already hold a loss. Pure."""
    current = None
    for index, (ok, started, detail) in enumerate(rows):
        counts = backup.parse_dump_detail(detail) if ok else None
        if index == 0:
            if counts is None:
                return None               # the newest dump failed: that's the news, not a shrink
            current = {"started_at": started, "counts": counts}
            continue
        if counts is not None and current["started_at"] - started >= timedelta(hours=min_gap_hours):
            return {"started_at": started, "counts": counts}, current
    return None


def lines(findings, earlier):
    """Plain-English lines for findings (compare's), naming the earlier dump's date (a datetime).
    Whole-table counts only."""
    when = f"{earlier.astimezone():%Y-%m-%d %H:%M}"
    out = []
    for f in findings:
        if f["kind"] == SHRANK:
            out.append(f"the {f['label']} table ({f['table']}) shrank from {f['before']:,} rows to "
                       f"{f['after']:,} since the dump of {when}")
        else:
            side = "the earlier dump" if f["before"] is None else "the newest dump"
            if f["before"] is None and f["after"] is None:
                side = "either dump"
            out.append(f"the {f['label']} table ({f['table']}) couldn't be compared with the dump of {when}: "
                       f"{side} has no count for it")
    return out


def read_rows(dbname=None):
    """The newest RECENT dump rows (ok, started_at, detail), newest first, read-only."""
    with db.connect("ro", dbname=dbname, autocommit=True) as c:
        return c.execute("select ok, started_at, detail from ops.backup_run where kind = 'dump' "
                         "order by id desc limit %s", (RECENT,)).fetchall()


def judge(rows, s=None):
    """(findings, earlier started_at) for rows (read_rows'), or ([], None) when there's nothing
    to compare."""
    found = pair(rows)
    if found is None:
        return [], None
    previous, current = found
    percent, min_rows = thresholds(s)
    return compare(previous["counts"], current["counts"], percent=percent, min_rows=min_rows), previous["started_at"]


def status_lines(dbname=None, rows=None, s=None):
    """The `status` lines: a WARNING per finding, nothing when all is well, there's nothing
    to compare or the check is off. Never raises: a read that fails is one line saying so."""
    try:
        s = s if s is not None else db.settings()
        if not enabled(s):
            return []
        rows = read_rows(dbname) if rows is None else rows
        findings, earlier = judge(rows, s)
    except Exception as e:            # noqa: BLE001 (status keeps going)
        return [f"  Shrink check: couldn't be read ({type(e).__name__})."]
    return [f"  WARNING: {line}." for line in lines(findings, earlier)] if findings else []


def nightly(log=None, rows=None, s=None):
    """The nightly's check after the backup: logs each finding and returns True when nothing
    shrank and every watched table was compared, False when something did or couldn't be, and
    None when it couldn't be read or is off (nothing is sent for it then; off, nothing is logged)."""
    log = log or db.log
    try:
        s = s if s is not None else db.settings()
        if not enabled(s):
            return None
        rows = read_rows() if rows is None else rows
        findings, earlier = judge(rows, s)
    except Exception as e:            # noqa: BLE001 (the night goes on)
        log(f"Nightly: the shrink check couldn't be read: {type(e).__name__}.")
        return None
    if earlier is None:
        log("Nightly: no shrink check tonight (no good dump with counts at least "
            f"{MIN_GAP_HOURS} hours older to compare with).")
        return True
    for line in lines(findings, earlier):
        log(f"Nightly: WARNING: {line}.")
    if not findings:
        log(f"Nightly: shrink check: no watched table shrank sharply since the dump of {earlier.astimezone():%Y-%m-%d %H:%M}.")
    return not findings
