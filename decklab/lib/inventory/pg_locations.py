"""Storage locations (E8-S22) on schemas before and after migration 0016: collection_card's
location column. Before it, every location reads as blank and a write that would save one is
refused (rules.LOCATION_REQUIRED), so the rest of the inventory keeps working."""
from decklab.lib.state import Invalid

from .rules import LOCATION_REQUIRED

VALUES = ("name", "quantity", "condition", "language", "notes", "location")


def ready(connection):
    """Whether collection_card has its location column (migration 0016), probed every time so a
    migration applied meanwhile is seen."""
    return connection.execute("select exists(select 1 from pg_catalog.pg_attribute "
                              "where attrelid=to_regclass('public.collection_card') and attname='location' "
                              "and not attisdropped)").fetchone()[0]


def select(connection):
    """collection_card's rows (space, set, number, finish, name, quantity, condition, language,
    notes, location), the location blank before migration 0016."""
    location = "location" if ready(connection) else "''::text as location"
    return ("select space_id, set_code, collector_number, finish, name, quantity, condition, language, notes, "
            f"{location} from collection_card")


def values(found):
    """collection_card's value columns the schema has (found: ready())."""
    return VALUES if found else VALUES[:-1]


def compatible(tables, found):
    """tables (table_rows.tables()' shape) as the schema can hold them: before migration 0016 the
    location is left out, and a location that isn't blank refuses (Invalid) before any DML."""
    if found:
        return tables
    rows = {}
    for key, value in tables["collection_card"].items():
        if len(value) > len(VALUES) - 1 and value[len(VALUES) - 1]:
            raise Invalid(LOCATION_REQUIRED)
        rows[key] = value[:len(VALUES) - 1]
    return {**tables, "collection_card": rows}
