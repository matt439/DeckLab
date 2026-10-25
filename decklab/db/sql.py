"""Read-only queries: `python -m decklab.db sql "select ..."` (or the query on stdin).

It connects as decklab_ro, the role that can only read, and makes every transaction read
only as well, with a 30-second statement timeout, so a query typed here can never change
anything or hold the database up for long. Results print as an aligned text table, or as CSV
with --csv.
"""
import csv
import io
import sys

from decklab.db import conn as db

TIMEOUT = "30s"


def query(text, dbname=None):
    """Run one read-only statement. Returns (column names, rows); a statement that returns no
    rows (a SET, say) gives ([], [])."""
    with db.connect("ro", dbname=dbname, autocommit=True) as c:
        c.execute("set default_transaction_read_only = on")
        c.execute(f"set statement_timeout = '{TIMEOUT}'")
        with c.transaction():
            cur = c.execute(text)
            if cur.description is None:
                return [], []
            return [d.name for d in cur.description], cur.fetchall()


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "t" if value else "f"
    return str(value)


def as_table(columns, rows):
    """An aligned text table: a header, a rule, the rows (NULL shows blank), and a row count."""
    if not columns:
        return "(no result)\n"
    cells = [[_cell(v) for v in row] for row in rows]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(columns)]
    lines = [" | ".join(c.ljust(w) for c, w in zip(columns, widths)).rstrip(),
             "-+-".join("-" * w for w in widths)]
    lines += [" | ".join(v.ljust(w) for v, w in zip(r, widths)).rstrip() for r in cells]
    lines.append(f"({len(rows)} row{'' if len(rows) == 1 else 's'})")
    return "\n".join(lines) + "\n"


def as_csv(columns, rows):
    """The result as CSV: a header row, then the rows (NULL as an empty field), LF endings."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    if columns:
        w.writerow(columns)
    w.writerows([[_cell(v) for v in row] for row in rows])
    return out.getvalue()


def run(text=None, csv_out=False, dbname=None, out=None):
    """The `sql` command: run text (or stdin when it's None or "-") and print the result.
    Returns 0, or 1 when the query fails (the database's message is printed)."""
    out = out or sys.stdout
    if out is sys.stdout and hasattr(out, "reconfigure") and not out.isatty():
        # A pipe or file on Windows defaults to cp1252, which can't hold every card name or
        # arrow in a message: write UTF-8 there, so CSV sent to a file isn't lossy either.
        out.reconfigure(encoding="utf-8", errors="replace")
    if text is None or text == "-":
        text = sys.stdin.read()
    if not text.strip():
        print("Give a query, as an argument or on stdin.", file=sys.stderr)
        return 1
    psycopg = db._psycopg()
    try:
        columns, rows = query(text, dbname=dbname)
    except psycopg.Error as e:
        print(f"The query failed: {str(e).strip()}", file=sys.stderr)
        return 1
    out.write(as_csv(columns, rows) if csv_out else as_table(columns, rows))
    return 0
