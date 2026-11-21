"""Private working checklists, with one decision per physical copy."""
import re

from decklab.lib import spaces

from . import Conflict, Invalid, Unavailable, rules

MAX_ROWS = 200
MAX_REVISION = 2 ** 53 - 1  # the browser uses a JavaScript number
CHOICES = ("check", "set_aside", "buy")
CHANGED = "This checklist changed on another device. Reload it before saving."
DECK_CHANGED = "This deck moved or is no longer available. Reopen the deck before saving."
# A pasted line must stay one line in a shop list. PostgreSQL's UTF-8 excludes surrogates.
INVALID_TEXT = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff]")


class MissingSchema(Unavailable):
    """A database that still needs the migration for this type of checklist."""


def key(profile_id, deck_id):
    pid = rules.profile_id(profile_id)
    if deck_id is not None:
        try:
            _, kind, slug = spaces.split_deck_id(deck_id)
        except ValueError:
            raise Invalid("Use a saved deck's ID for its checklist.") from None
        if kind not in spaces.DECK_KINDS or "/" in slug or len(deck_id) > 200 or INVALID_TEXT.search(deck_id):
            raise Invalid("Use a saved deck's ID for its checklist.")
    return pid, deck_id


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


# Table and column names are fixed here, and key values are always parameters.
_STANDALONE = ("public.upgrade_checklist", ("profile_id",))
_LINKED = ("public.deck_upgrade_checklist", ("profile_id", "deck_id"))


def _scope(profile_id, deck_id):
    pid, deck_id = key(profile_id, deck_id)
    return (_STANDALONE, (pid,)) if deck_id is None else (_LINKED, (pid, deck_id))


def _read(cur, spec, values):
    table, columns = spec
    if not cur.execute("select to_regclass(%s) is not null", (table,)).fetchone()[0]:
        raise MissingSchema("The deck checklist needs the database migration.")
    where = " and ".join(f"{column} = %s" for column in columns)
    row = cur.execute(f"select revision, title, rows from {table} where {where}", values).fetchone()
    return {"revision": row[0], "title": row[1], "rows": row[2]} if row else empty()


def pg_get(store, profile_id, *, deck_id=None):
    spec, values = _scope(profile_id, deck_id)

    def work(c):
        with c.cursor() as cur:
            return _read(cur, spec, values)

    return store._call(work)


def pg_put(store, profile_id, title, rows, expect, *, deck_id=None):
    from decklab.db import space_members
    spec, values = _scope(profile_id, deck_id)
    table, columns = spec
    title, rows = normalize(title, rows, expect)
    if store._batch() is not None:
        raise Invalid("Save the checklist separately from an inventory or deck change.")
    names = ", ".join(columns)
    placeholders = ", ".join(["%s"] * (len(columns) + 3))

    def work(c):
        from psycopg.types.json import Jsonb
        with c.transaction(), c.cursor() as cur:
            space_members.admit(cur, profile_ids=(values[0],))
            store._lock(cur, "upgrade-checklist:" + "\n".join(values))
            before = _read(cur, spec, values)
            if deck_id is not None:
                found = cur.execute(
                    "select 1 from public.deck d join public.profile p on p.space_id = d.space_id "
                    "where p.id = %s and d.id = %s for key share of d", values).fetchone()
                if found is None:
                    raise Conflict(DECK_CHANGED)
            after = transition(before, title, rows, expect)
            if after is not before:
                cur.execute(f"insert into {table} as checklist ({names}, revision, title, rows) "
                            f"values ({placeholders}) on conflict ({names}) do update set "
                            "revision = excluded.revision, title = excluded.title, rows = excluded.rows "
                            "where checklist.revision = %s",
                            (*values, after["revision"], title, Jsonb(rows), expect))
                if cur.rowcount != 1:
                    raise Conflict(CHANGED)
            return after

    return store._call(work)
