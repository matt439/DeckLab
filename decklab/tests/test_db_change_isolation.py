"""Audited transaction isolation over explicit fakes; never connects to PostgreSQL.

Run through scripts/test_fixtures.py to install guards before imports.
"""
from contextlib import contextmanager
import sys
import types
import unittest
from unittest import mock

from decklab.db import conn as db
from decklab.db import space_members
from decklab.lib.state import Actor
from decklab.lib.state.pg import PgStore


class Connection:
    def __init__(self):
        self.info = types.SimpleNamespace(transaction_status=0)
        self.events = []
        self.rows = []
        self.closed = False

    @contextmanager
    def transaction(self):
        self.events.append("begin")
        self.info.transaction_status = 2
        before = list(self.rows)
        try:
            yield
        except BaseException:
            self.rows = before
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")
        finally:
            self.info.transaction_status = 0

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=None):
        self.events.append((sql, params))
        if sql.startswith("insert into audit.change_set"):
            self.rows.append(params)
        return self

    def fetchone(self):
        return (17,)

    def close(self):
        self.closed = True


class ChangeIsolationTests(unittest.TestCase):
    def setUp(self):
        self.conn = Connection()
        pq = types.ModuleType("psycopg.pq")
        pq.TransactionStatus = types.SimpleNamespace(IDLE=0)
        patcher = mock.patch.dict(sys.modules, {"psycopg.pq": pq})
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(db, "connect", side_effect=AssertionError("No configured connector"))
        self.connect = patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_sql_and_via_omission_are_unchanged(self):
        with db.change(" test ", "test", " Message ", conn=self.conn) as (cur, change_id):
            self.assertIs(cur, self.conn)
            self.assertEqual(change_id, 17)
        self.assertEqual(self.conn.events, [
            "begin", ("insert into audit.change_set (actor, source, message, reason) "
                      "values (%s, %s, %s, %s) returning id", ("test", "test", "Message", None)),
            ("select set_config('decklab.change_set', %s, true)", ("17",)), "commit"])
        self.assertFalse(self.conn.closed)
        self.connect.assert_not_called()

    def test_read_committed_is_literal_before_first_audit_insert(self):
        with db.change("test", "test", "Message", conn=self.conn, via="home", isolation="read committed"):
            pass
        self.assertEqual(self.conn.events[1], ("set transaction isolation level read committed", None))
        self.assertTrue(self.conn.events[2][0].startswith("insert into audit.change_set"))
        self.assertIn("via", self.conn.events[2][0])
        for event in self.conn.events:
            if isinstance(event, tuple):
                self.assertNotIn("default_transaction", event[0])
                self.assertNotIn("alter ", event[0])
        self.assertEqual(len(self.conn.rows), 1)

    def test_explicit_none_retains_default_sql(self):
        with db.change("test", "test", "Message", conn=self.conn, isolation=None):
            pass
        self.assertFalse(any(isinstance(e, tuple) and "isolation" in e[0] for e in self.conn.events))

    def test_invalid_isolation_rejects_before_any_connection_or_transaction(self):
        for value in ("repeatable read", "READ COMMITTED", "read committed; delete", "", True, 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                with db.change("test", "test", "Message", isolation=value):
                    self.fail("Invalid isolation entered")
        self.connect.assert_not_called()
        self.assertEqual(self.conn.events, [])

    def test_existing_transaction_rejects_without_nested_begin_or_connect(self):
        self.conn.info.transaction_status = 2
        with self.assertRaises(ValueError):
            with db.change("test", "test", "Message", conn=self.conn, isolation="read committed"):
                pass
        self.assertEqual(self.conn.events, [])
        self.connect.assert_not_called()

    def test_failure_rolls_back_audit_instead_of_committing_empty_change(self):
        with self.assertRaisesRegex(RuntimeError, "fixture"):
            with db.change("test", "test", "Message", conn=self.conn, isolation="read committed"):
                raise RuntimeError("fixture")
        self.assertEqual(self.conn.rows, [])
        self.assertEqual(self.conn.events[-1], "rollback")

    def test_owned_fake_connection_still_closes_and_uses_existing_default_call(self):
        self.connect.side_effect = None
        self.connect.return_value = self.conn
        with db.change("test", "test", "Message", isolation="read committed"):
            pass
        self.connect.assert_called_once_with("app")
        self.assertTrue(self.conn.closed)

    def test_store_omits_new_keyword_unless_requested(self):
        store = PgStore()
        actor = Actor("test", "Fixture", None, "test")

        @contextmanager
        def changed(*args, **kwargs):
            yield self.conn, 17

        with mock.patch.object(db, "change", side_effect=changed) as change, \
                mock.patch.object(space_members, "admit"):
            with store._change(self.conn, actor, "Message"):
                pass
            self.assertNotIn("isolation", change.call_args.kwargs)
            with store._change(self.conn, actor, "Message", isolation="read committed"):
                pass
            self.assertEqual(change.call_args.kwargs["isolation"], "read committed")

    def test_store_rejects_isolation_inside_batch_before_any_nested_work(self):
        store = PgStore()
        store._local.batch = object()
        with mock.patch.object(db, "change") as change, self.assertRaises(ValueError):
            with store._change(self.conn, Actor("test", "Fixture", None, "test"), "Message",
                               isolation="read committed"):
                pass
        change.assert_not_called()
        self.assertEqual(self.conn.events, [])


if __name__ == "__main__":
    raise SystemExit("Use scripts/test_fixtures.py for protected fixture checks.")
