"""Wishlist Undo's admitted, same-connection PostgreSQL adapter; no retry loop."""
from decklab.db import space_members

from . import Invalid, rules, wishlist_undo as undo

RAW_COLUMNS = "profile_id,position,name,set_code,collector_number,notes,source"
RAW_NAMES = RAW_COLUMNS.split(",")


def source(cur, change_id):
    rows = cur.execute("select id,table_name,op,row_key,before,after from audit.row_change "
                       "where change_set_id=%s order by id limit 2", (change_id,)).fetchall()
    return [dict(zip(("id", "table", "op", "key", "before", "after"), row)) for row in rows]


def entries(cur, pid):
    return [dict(zip(RAW_NAMES, row)) for row in cur.execute(
        "select " + RAW_COLUMNS + " from wishlist_entry where profile_id=%s order by position", (pid,)).fetchall()]


def latest(cur, pid, position=None):
    sides = "(row_key->>'profile_id'=%s or before->>'profile_id'=%s or after->>'profile_id'=%s)"
    args = [pid, pid, pid]
    if position is not None:
        sides = "(" + " or ".join(f"({side}->>'profile_id'=%s and {side}->>'position'=%s)" for side in ("row_key", "before", "after")) + ")"
        args = [value for _ in range(3) for value in (pid, str(position))]
    row = cur.execute("select id from audit.row_change where table_name='wishlist_entry' and " + sides + " order by id desc limit 1", args).fetchone()
    return row[0] if row else None


def _plan(store, cur, change_id, pid):
    raw = source(cur, change_id)
    # Private scope is decided before even deriving a position from another row.
    if len(raw) != 1 or raw[0]["table"] != "wishlist_entry" or raw[0]["op"] != "UPDATE" \
            or not isinstance(raw[0]["before"], dict) or not isinstance(raw[0]["after"], dict) \
            or raw[0]["before"].get("profile_id") != pid or raw[0]["after"].get("profile_id") != pid:
        raise undo.UndoMissing()
    position = raw[0]["after"].get("position")
    return undo.review(change_id, pid, raw, entries(cur, pid), latest(cur, pid, position), latest(cur, pid))


def _allowed(store, pid, actor=None):
    rules.profile_id(pid)
    if store._batch() is not None:
        raise undo.UndoUnsupported("Wishlist Undo must be saved as its own change.")
    if actor is not None and (actor.id != pid or actor.source != "web"):
        raise undo.UndoMissing()


def preview(store, change_id, pid):
    _allowed(store, pid)
    def work(c):
        # _call's connections are autocommit; an explicit read transaction keeps
        # every admission/key lock until all evidence has been collected.
        with c.transaction(), c.cursor() as cur:
            try:
                space_members.admit(cur, profile_ids=(pid,))
            except Invalid:
                raise undo.UndoMissing() from None
            store._lock(cur, f"wishlist:{pid}")
            return _plan(store, cur, change_id, pid)
    return store._call(work)


def apply(store, change_id, pid, expect, actor, message):
    rules.check_write(actor, message)
    _allowed(store, pid, actor)
    def work(c):
        try:
            with store._change(c, actor, message, profile_ids=(pid,)) as (cur, change_set):
                store._lock(cur, f"wishlist:{pid}")
                plan = _plan(store, cur, change_id, pid)
                if not isinstance(expect, str) or not undo.SHA.fullmatch(expect):
                    raise undo.UndoUnsupported("Review this wishlist Undo before saving it.")
                if expect != plan["expect"]:
                    raise undo.UndoConflict()
                current, positions = store._entries(cur, pid)
                changed, _ = store._wishlist_set_at(cur, pid, current, positions, plan["current"]["name"],
                                                   notes=plan["restored"]["notes"], source=plan["restored"]["source"])
                if changed is not True:
                    raise undo.UndoConflict()
                saved = undo.receipt(plan, entries(cur, pid), source(cur, change_set), latest(cur, pid))
                return {"review": plan, **saved}
        except Invalid as error:
            if str(error) == space_members.REFUSED:
                raise undo.UndoMissing() from None
            raise
    return store._call(work)
