"""PostgreSQL evidence and inverse for wishlist_undo_moved, on pg_wishlist_undo's admitted,
locked connection (E11-S08). Never opens a connection or retries."""
from . import pg_wishlist_undo as base, wishlist_undo_moved as moved

_OWN = ("table_name='wishlist_entry' and op in ('UPDATE','INSERT') and after->>'profile_id'=%s "
        "and (before is null or before->>'profile_id'=%s)")


def source(cur, change_id, pid):
    """(rows, total): up to MAX_MOVED + 2 rows in audit order and the change's row count, or
    ([], 0) when any row of it isn't pid's wishlist (decided before any value is read)."""
    total, own = cur.execute("select count(*), count(*) filter (where " + _OWN + ") from audit.row_change "
                             "where change_set_id=%s", (pid, pid, change_id)).fetchone()
    if total != own:
        return [], 0
    rows = cur.execute("select id,table_name,op,row_key,before,after from audit.row_change where change_set_id=%s "
                       "order by id limit %s", (change_id, moved.MAX_MOVED + 2)).fetchall()
    return [dict(zip(("id", "table", "op", "key", "before", "after"), row)) for row in rows], total


def plan(cur, change_id, pid):
    rows, total = source(cur, change_id, pid)
    if not rows:
        raise moved.undo.UndoMissing()
    return moved.review(change_id, pid, rows, base.entries(cur, pid), base.latest(cur, pid), total)


def inverse(cur, pid, review):
    """Delete the added entry, then move each moved entry back, lowest first (each into the
    slot the one before it just left, so the primary key holds throughout)."""
    added = review["raw_current"]
    cur.execute("delete from wishlist_entry where profile_id=%s and position=%s and name=%s", (pid, added["position"], added["name"]))
    if cur.rowcount != 1:
        raise moved.undo.UndoConflict()
    for after, before in review["raw_moves"]:
        cur.execute("update wishlist_entry set position=%s where profile_id=%s and position=%s and name=%s",
                    (before["position"], pid, after["position"], after["name"]))
        if cur.rowcount != 1:
            raise moved.undo.UndoConflict()


def receipt(cur, review, change_set, pid):
    rows = cur.execute("select id,table_name,op,row_key,before,after from audit.row_change where change_set_id=%s "
                       "order by id limit %s", (change_set, moved.MAX_MOVED + 2)).fetchall()
    rows = [dict(zip(("id", "table", "op", "key", "before", "after"), row)) for row in rows]
    return moved.receipt(review, base.entries(cur, pid), rows, base.latest(cur, pid))
