"""The disposable reset covers optional inventory tables without requiring a server."""
import unittest
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest import mock

from decklab.db import conn
from decklab.lib.inventory import pg, pg_dice, pg_loans
from decklab.tests import db_support


class ResetTests(unittest.TestCase):
    def test_every_persisted_inventory_family_is_in_the_disposable_reset(self):
        expected = set(pg.INVENTORY_TABLES) | set(db_support.DECK_TABLES) | {pg_dice.TABLE, pg_loans.TABLE}
        self.assertLessEqual(expected, set(db_support.INVENTORY_TABLES))

    def reset(self, present):
        queries = []
        class Connection:
            def execute(self, statement, params=()):
                text = statement if isinstance(statement, str) else statement.as_string()
                queries.append((text, params))
                exists = bool(params and params[0] in present) if text == "select to_regclass(%s) is not null" else None
                return SimpleNamespace(fetchone=lambda: (exists,))
        connection = Connection()
        @contextmanager
        def change(*args, **kwargs):
            yield connection, 1
        with mock.patch.object(conn, "connect", return_value=nullcontext(connection)) as connect, \
                mock.patch.object(conn, "change", side_effect=change):
            db_support.reset(db_support.PREFIX + "fixture_reset", (pg_dice.TABLE, pg_loans.TABLE))
        connect.assert_called_once_with("owner", dbname=db_support.PREFIX + "fixture_reset", autocommit=True)
        return queries

    def test_present_optional_dice_and_loan_rows_are_deleted_before_reseeding(self):
        queries = self.reset({"public.dice_counter", "public.card_loan"})
        statements = [query for query, _ in queries]
        self.assertIn('delete from "dice_counter"', statements)
        self.assertIn('delete from "card_loan"', statements)
        self.assertIn("delete from inventory_revision", statements)

    def test_older_schema_with_no_optional_tables_is_not_given_a_missing_table_delete(self):
        queries = self.reset(set())
        statements = [query for query, _ in queries]
        self.assertNotIn('delete from "dice_counter"', statements)
        self.assertNotIn('delete from "card_loan"', statements)
        self.assertIn("delete from inventory_revision", statements)
