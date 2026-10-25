"""The inventory's own command in `python -m decklab.db` (registered by __main__.py from this
module's register()), and the status command's lines for the inventory and the decks:

  inventory export DIR            write the database's inventory as today's files into DIR/magic

inventory export writes exactly the files the repo's magic/ folder held before the database
(collection.csv, tokens.csv, watchlist.csv, products/, orders/, people/<id>/..., each space's raw
imports, and the deck files, accessories.csv and its pictures), byte for byte, from one snapshot,
for reading them. DIR/magic ends up holding exactly those files, so it refuses a DIR/magic that
holds anything else: never export over the repo's own magic/.

Exit codes as the other commands: 0 done, 1 refused, 2 the database can't be reached.
"""
from pathlib import Path

from decklab.db import conn as db


def register(sub):
    """Add the inventory command to python -m decklab.db's parser."""
    p = sub.add_parser("inventory", help="Export the inventory as files.",
                       description="The inventory: export it as today's files.")
    actions = p.add_subparsers(dest="action", required=True, metavar="action")
    sp = actions.add_parser("export", help="Write the database's inventory as today's files into DIR/magic.",
                            description="Write the database's inventory as today's files into DIR/magic.")
    sp.add_argument("dir", metavar="DIR", help="the folder to write magic/ into")
    sp.add_argument("--dbname", help="the database to use instead of the settings' one (tests)")
    sp.set_defaults(func=_export)


# ------------------------------------------------------------------ export

def export_to(folder, dbname=None):
    """Write the database's inventory into folder/magic (see the module docstring). Returns how
    many files. ValueError when folder/magic holds files that aren't inventory files, or there's
    no inventory in the database."""
    from decklab.db import export
    from decklab.lib.inventory import paths
    folder = Path(folder)
    magic = folder / export.MAGIC
    found = database_files(dbname)
    decks = any(paths.is_deck_part(rel) for rel in found)       # the database holds the decks (phase 4)
    if magic.is_dir():
        others = sorted(rel for rel in (p.relative_to(folder).as_posix() for p in magic.rglob("*") if p.is_file())
                        if not paths.is_inventory(rel) and not (decks and paths.is_deck_part(rel)))
        if others:
            raise ValueError(f"{magic} holds files that aren't inventory files ({', '.join(others[:3])}"
                             f"{' and more' if len(others) > 3 else ''}), which the export would delete: "
                             "export into another folder")
    export.write_inventory(magic, found)
    return len(found)


def database_files(dbname=None):
    """The database's inventory as files ({path: bytes}, export.inventory_files) from one
    snapshot. ValueError when it holds none."""
    from psycopg import IsolationLevel

    from decklab.db import export
    with db.connect("ro", dbname=dbname) as c:
        c.isolation_level = IsolationLevel.REPEATABLE_READ
        c.read_only = True
        found = export.inventory_files(c)
        c.rollback()
    if found is None:
        raise ValueError("the database holds no inventory: restore the newest backup first "
                         "(a decklab-*.dump from the NAS or decklab/data/backups/, with pg_restore)")
    return found


def _export(args):
    count = export_to(args.dir, dbname=args.dbname)
    print(f"Wrote {count} inventory files into {Path(args.dir) / 'magic'}.")
    return 0


# ------------------------------------------------------------------ status

def status_line(dbname=None):
    """python -m decklab.db status's line for the inventory: what the database holds of it."""
    try:
        held = inventory_held(dbname)
    except ValueError:
        return "Inventory: not in the database yet (migration 0004 is pending)."
    if held is None:
        what = "nothing imported"
    elif held["revision"] is None:
        what = "rows but no revision row"
    else:
        when = held["imported_at"]
        what = f"revision {held['revision']}" + (f", imported {when.astimezone():%Y-%m-%d %H:%M}" if when else "")
    return f"Inventory: the database holds {what}."


def decks_line(dbname=None):
    """python -m decklab.db status's line for the decks (phase 4): what the database holds of them."""
    try:
        decks = decks_held(dbname)
    except ValueError:
        return "Decks: not in the database yet (migration 0006 is pending)."
    if decks is None or decks["revision"] is None:
        return ("Decks: the database holds none (restore the newest backup: a decklab-*.dump from the NAS or "
                "decklab/data/backups/, with pg_restore).")
    with db.connect("ro", dbname=dbname, autocommit=True) as c:
        count, revisions = c.execute("select (select count(*) from deck), (select count(*) from deck_revision)"
                                     ).fetchone()
    return f"Decks: {count} deck(s), {revisions} saved revision(s); decks revision {decks['revision']}."


def inventory_held(dbname=None, conn=None):
    """What the database holds of an inventory: None when nothing, else {"revision" (text or
    None), "imported_at" (a datetime or None), "rows" (bool: any inventory row)}. ValueError
    when migration 0004 isn't applied; conn.DbUnavailable when it can't be reached."""
    from decklab.lib.inventory.pg import INVENTORY_TABLES

    def read(c):
        if c.execute("select to_regclass('public.inventory_revision') is null").fetchone()[0]:
            raise ValueError("the database has no inventory tables yet: run python -m decklab.db migrate "
                             "(migration 0004) first")
        row = c.execute("select revision, imported_at from inventory_revision").fetchone()
        rows = c.execute("select " + " or ".join(f"exists (select 1 from {t})" for t in INVENTORY_TABLES)
                         ).fetchone()[0]
        if row is None and not rows:
            return None
        return {"revision": str(row[0]) if row else None, "imported_at": row[1] if row else None, "rows": rows}
    if conn is not None:
        return read(conn)
    with db.connect("ro", dbname=dbname, autocommit=True) as c:
        return read(c)


def decks_held(dbname=None, conn=None):
    """What the database holds of the decks: None when nothing, else {"revision" (text or None),
    "imported_at", "rows" (bool)}. ValueError when migration 0006 isn't applied."""

    def read(c):
        if c.execute("select to_regclass('public.decks_revision') is null").fetchone()[0]:
            raise ValueError("the database has no tables for the decks yet: run python -m decklab.db migrate "
                             "(migration 0006) first")
        row = c.execute("select revision, imported_at from decks_revision").fetchone()
        rows = c.execute("select exists (select 1 from deck) or exists (select 1 from accessory) or exists "
                         "(select 1 from accessory_image) or exists (select 1 from deck_revision)").fetchone()[0]
        if row is None and not rows:
            return None
        return {"revision": str(row[0]) if row else None, "imported_at": row[1] if row else None, "rows": rows}
    if conn is not None:
        return read(conn)
    with db.connect("ro", dbname=dbname, autocommit=True) as c:
        return read(c)
