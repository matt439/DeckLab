"""Who last changed an inventory row, from the database's audit trail (audit.change_set and
audit.row_change): what a page's "this changed after you opened it" answer names once the row
lives in the database instead of a file git knows about (the phase 3 design's amendment Q8).

    change = audit.last_change("product_status", {"file": "test-product.csv"})
    # {"id", "at" (an aware datetime), "actor", "source", "message"}, or None

Only the database backend has a trail: with the files backend (or any backend without one)
last_change gives None, and the pages keep asking git as they always have. psycopg is reached
only through the database backend's own connection (pg.PgInventory._call), inside the call.
"""
import json

from . import backend as active_backend


def last_change(table, key=None, backend=None):
    """The newest change set that touched a row of table (an inventory table of migration 0004)
    whose primary key includes key ({column: value}; any row of the table when key is None), as
    {id, at, actor, source, message}; None when there's none, or when backend (the active one by
    default) keeps no audit trail. state.Unavailable when the database can't be reached."""
    backend = active_backend() if backend is None else backend
    call = getattr(backend, "_call", None)
    if getattr(backend, "name", None) != "db" or call is None:
        return None

    def work(c):
        if key is None:
            row = c.execute("select cs.id, cs.at, cs.actor, cs.source, cs.message from audit.change_set cs "
                            "where exists (select 1 from audit.row_change r where r.change_set_id = cs.id "
                            "and r.table_name = %s) order by cs.id desc limit 1", (table,)).fetchone()
        else:
            row = c.execute("select cs.id, cs.at, cs.actor, cs.source, cs.message from audit.change_set cs "
                            "where exists (select 1 from audit.row_change r where r.change_set_id = cs.id "
                            "and r.table_name = %s and r.row_key @> %s::jsonb) order by cs.id desc limit 1",
                            (table, json.dumps(key))).fetchone()
        return row
    row = call(work)
    if row is None:
        return None
    return {"id": row[0], "at": row[1], "actor": row[2], "source": row[3], "message": row[4]}


def last_owned_change(table, owners, backend=None):
    """The newest change set that touched a row of table (phase 4's accessory) owned, before or
    after, by one of owners (permissions.accessory_owners; None: anyone's), as last_change gives
    it plus "kit": whether any row of that change set may say whose sleeves or deck boxes went
    where (state.rules.kit_changed: its message is then its actor's alone); None when there's
    none or backend keeps no audit trail."""
    from decklab.lib.state import rules
    backend = active_backend() if backend is None else backend
    call = getattr(backend, "_call", None)
    if getattr(backend, "name", None) != "db" or call is None:
        return None
    mine = None if owners is None else sorted(owners)

    def work(c):
        found = c.execute("select cs.id, cs.at, cs.actor, cs.source, cs.message from audit.change_set cs "
                          "where exists (select 1 from audit.row_change r where r.change_set_id = cs.id "
                          "and r.table_name = %s and (%s::text[] is null or r.before->>'owner' = any(%s::text[]) "
                          "or r.after->>'owner' = any(%s::text[]))) order by cs.id desc limit 1",
                          (table, mine, mine, mine)).fetchone()
        if found is None:
            return None, []
        rows = c.execute("select table_name, op, before, after from audit.row_change where change_set_id = %s",
                         (found[0],)).fetchall()
        return found, rows
    row, rows = call(work)
    if row is None:
        return None
    kit = any(rules.kit_changed({"table": t, "op": op, "before": b, "after": a}) for t, op, b, a in rows)
    return {"id": row[0], "at": row[1], "actor": row[2], "source": row[3], "message": row[4], "kit": kit}


def is_kit_change(change_id, backend=None):
    """Whether the change set change_id changed a kit (state.rules.kit_changed: an intact
    product's sleeves or deck box, an accessory row or a deck's kit), so its message is its
    actor's alone; False without an audit trail."""
    from decklab.lib.state import rules
    backend = active_backend() if backend is None else backend
    call = getattr(backend, "_call", None)
    if getattr(backend, "name", None) != "db" or call is None or change_id is None:
        return False
    rows = call(lambda c: c.execute("select table_name, op, before, after from audit.row_change "
                                    "where change_set_id = %s", (change_id,)).fetchall())
    return any(rules.kit_changed({"table": t, "op": op, "before": b, "after": a}) for t, op, b, a in rows)


def change_source(change_id, backend=None):
    """The source of the change set change_id (decklab.db.conn.SOURCES: "web" for the pages, "cli",
    "migration", ...), so a deck revision says "saved it in Deck Lab" only for the pages' changes;
    None without an audit trail or a change set (an imported revision)."""
    backend = active_backend() if backend is None else backend
    call = getattr(backend, "_call", None)
    if getattr(backend, "name", None) != "db" or call is None or change_id is None:
        return None
    row = call(lambda c: c.execute("select source from audit.change_set where id = %s", (change_id,)).fetchone())
    return row[0] if row else None
