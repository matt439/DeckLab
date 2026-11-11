"""Optional 0024 loan table; absence never silently discards a new record."""
from decklab.lib.state import Invalid

from . import loan_rules

TABLE = "card_loan"
COLUMNS = ("name", "set_code", "collector_number", "finish", "quantity", "borrower", "lent_on", "returned_on", "notes")


def ready(connection):
    return connection.execute("select to_regclass('public.card_loan') is not null").fetchone()[0]


def rows(connection, found):
    return (connection.execute("select space_id, id, " + ", ".join(COLUMNS) + " from card_loan").fetchall()
            if found else [])


def compatible(tables, found):
    if not found and tables.get(TABLE):
        raise Invalid(loan_rules.REQUIRED)
    return {**tables, TABLE: tables.get(TABLE, {}) if found else {}}
