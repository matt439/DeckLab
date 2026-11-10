"""Optional queue market targets before/after0026; never discard a chosen amount."""
from decklab.lib.state import Invalid

from .table_rows import WATCH_COLUMNS
from .watchlist_targets import MIGRATE


def ready(connection):
    return connection.execute("select exists(select 1 from pg_catalog.pg_attribute "
                              "where attrelid=to_regclass('public.watchlist_item') and attname='buy_under_aud' "
                              "and not attisdropped)").fetchone()[0]


def columns(found):
    return WATCH_COLUMNS if found else WATCH_COLUMNS[:-1]


def select(connection, found=None):
    found = ready(connection) if found is None else found
    target = "coalesce(buy_under_aud::text, '') as buy_under_aud" if found else "''::text as buy_under_aud"
    return f"select id, position, {', '.join(WATCH_COLUMNS[:-1])}, {target} from watchlist_item"


def compatible(tables, found):
    if found:
        return tables
    rows = []
    for row in tables["watchlist_item"]:
        if len(row) == len(WATCH_COLUMNS) + 1:
            if row[-1] not in (None, ""):
                raise Invalid(MIGRATE)
            row = row[:-1]
        rows.append(row)
    return {**tables, "watchlist_item": rows}
