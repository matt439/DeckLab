"""PostgreSQL evidence for wishlist_undo_later, on pg_wishlist_undo's admitted, locked
connection (E11-S08). Never opens a connection or retries."""
from . import pg_wishlist_undo as base, wishlist_undo_later as later_undo

_SIDES = "(row_key->>'profile_id'=%s or before->>'profile_id'=%s or after->>'profile_id'=%s)"


def later(cur, pid, after_id):
    """Every audit row of pid's wishlist after after_id, in order: up to MAX_LATER + 1 of them,
    so a longer history is refused by its bound rather than silently cut short."""
    rows = cur.execute("select id,change_set_id,table_name,op,row_key,before,after from audit.row_change "
                       "where table_name='wishlist_entry' and id>%s and " + _SIDES + " order by id limit %s",
                       (after_id, pid, pid, pid, later_undo.MAX_LATER + 1)).fetchall()
    return [dict(zip(("id", "change", "table", "op", "key", "before", "after"), row)) for row in rows]


def plan(cur, change_id, pid, raw):
    """The review of a single-row source (already checked as pid's own DELETE by the caller)."""
    old = raw[0]["before"]
    return later_undo.review(change_id, pid, raw, later(cur, pid, raw[0]["id"]), base.entries(cur, pid),
                             base.latest(cur, pid, old.get("position")), base.latest(cur, pid))
