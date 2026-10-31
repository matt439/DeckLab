"""Owned dice and counters (E7-S24) on schemas before and after migration 0020: the dice_counter
table. Before it, every space reads as having none and a write that would record one is refused
(dice_rules.DICE_REQUIRED, state.Invalid), so the rest of the inventory keeps working; once it's
applied the rows are read and written as token_card's are (by id, positions STEP apart within a
space: pg._diff)."""
from decklab.lib.state import Invalid

from .dice_rules import DICE_REQUIRED
from .table_rows import DICE_COLUMNS

TABLE = "dice_counter"
SELECT = f"select id, space_id, position, {', '.join(DICE_COLUMNS)} from {TABLE}"


def ready(connection):
    """Whether the dice_counter table is there (migration 0020), probed every time so a migration
    applied meanwhile is seen."""
    return connection.execute(f"select to_regclass('public.{TABLE}') is not null").fetchone()[0]


def rows(connection, found):
    """dice_counter's rows (id, space, position, *DICE_COLUMNS), none before migration 0020
    (found: ready())."""
    return connection.execute(SELECT).fetchall() if found else []


def compatible(tables, found):
    """tables (table_rows.tables()' shape) as the schema can hold them: before migration 0020 no
    dice_counter rows, and a row to record refuses (Invalid) before any DML."""
    if found:
        return tables
    if tables.get(TABLE):
        raise Invalid(DICE_REQUIRED)
    return {**tables, TABLE: []}
