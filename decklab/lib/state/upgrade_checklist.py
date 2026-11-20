"""One private working checklist per profile, with one decision per physical copy."""
import re

from . import Conflict, Invalid, Unavailable, rules

MAX_ROWS = 200
MAX_REVISION = 2 ** 53 - 1  # the browser uses a JavaScript number
CHOICES = ("check", "set_aside", "buy")
CHANGED = "This checklist changed on another device. Reload it before saving."
# A pasted line must stay one line in a shop list. PostgreSQL's UTF-8 excludes surrogates.
INVALID_TEXT = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff]")


class MissingSchema(Unavailable):
    """A server running new code against a database that still needs migration 0029."""


def empty():
    return {"revision": 0, "title": "", "rows": []}


def _text(value):
    return isinstance(value, str) and len(value) <= rules.MAX_NAME and not INVALID_TEXT.search(value)


def normalize(title, rows, expect):
    if type(expect) is not int or not 0 <= expect <= MAX_REVISION:
        raise Invalid("Use the revision from the saved checklist.")
    if not _text(title):
        raise Invalid("Use a single-line checklist title of up to 150 characters.")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise Invalid(f"Keep the checklist to {MAX_ROWS} copies.")
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or row.keys() != {"name", "choice"}:
            raise Invalid("Each copy needs a card name and a choice.")
        if not _text(row["name"]) or not row["name"].strip():
            raise Invalid("Use a single-line card name of 1 to 150 characters.")
        if row["choice"] not in CHOICES:
            raise Invalid("Choose Check at home, Set aside or Buy for each copy.")
        normalized.append({"name": row["name"].strip(), "choice": row["choice"]})
    return title.strip(), normalized


def transition(before, title, rows, expect):
    if before["revision"] != expect:
        raise Conflict(CHANGED)
    if before["title"] == title and before["rows"] == rows:
        return before
    if expect == MAX_REVISION:
        raise Invalid("This checklist has reached its revision limit.")
    return {"revision": expect + 1, "title": title, "rows": rows}


def _read(cur, profile_id):
    if not cur.execute("select to_regclass('public.upgrade_checklist') is not null").fetchone()[0]:
        raise MissingSchema("The deck checklist needs the database migration.")
    row = cur.execute("select revision, title, rows from public.upgrade_checklist where profile_id = %s",
                      (profile_id,)).fetchone()
    return {"revision": row[0], "title": row[1], "rows": row[2]} if row else empty()


def pg_get(store, profile_id):
    pid = rules.profile_id(profile_id)

    def work(c):
        with c.cursor() as cur:
            return _read(cur, pid)

    return store._call(work)


def pg_put(store, profile_id, title, rows, expect):
    from decklab.db import space_members
    pid = rules.profile_id(profile_id)
    title, rows = normalize(title, rows, expect)
    if store._batch() is not None:
        raise Invalid("Save the checklist separately from an inventory or deck change.")

    def work(c):
        from psycopg.types.json import Jsonb
        with c.transaction(), c.cursor() as cur:
            space_members.admit(cur, profile_ids=(pid,))
            store._lock(cur, "upgrade-checklist:" + pid)
            before = _read(cur, pid)
            after = transition(before, title, rows, expect)
            if after is not before:
                cur.execute("insert into public.upgrade_checklist (profile_id, revision, title, rows) "
                            "values (%s, %s, %s, %s) on conflict (profile_id) do update set "
                            "revision = excluded.revision, title = excluded.title, rows = excluded.rows",
                            (pid, after["revision"], title, Jsonb(rows)))
            return after

    return store._call(work)
