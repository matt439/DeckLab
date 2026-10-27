"""Optional arrival-check metadata on schemas before and after migration 0015."""
from decklab.lib.state import Invalid

from .table_rows import COMPONENT_COLUMNS

REQUIRED = "Targeted arrival checks require migration 0015. Run the database migrations first."


def columns(connection):
    ready = connection.execute("select exists(select 1 from pg_catalog.pg_attribute "
        "where attrelid=to_regclass('public.order_component') and attname='check_links' and not attisdropped)").fetchone()[0]
    return COMPONENT_COLUMNS if ready else COMPONENT_COLUMNS[:-1]


def select(connection):
    found = columns(connection)
    fields = [name if name in found else "null::jsonb as check_links" for name in COMPONENT_COLUMNS]
    return "select order_id,id," + ",".join(fields) + " from order_component"


def compatible(tables, found):
    """Refuse unsupported metadata before DML; general schema13/14 writes stay usable."""
    ready = "check_links" in found
    rows = {}
    for key, value in tables["order_component"].items():
        core = value[:len(COMPONENT_COLUMNS) - 1]
        metadata = value[-1] if len(value) == len(COMPONENT_COLUMNS) else None
        if not ready and metadata is not None:
            raise Invalid(REQUIRED)
        rows[key] = (*core, metadata) if ready else core
    return {**tables, "order_component": rows}
