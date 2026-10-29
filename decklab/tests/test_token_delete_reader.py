"""Read-only token-review adapter is exercised with fake transactions/cursors only."""
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest import mock

from decklab.db import space_members
from decklab.lib.inventory import pg, undo, undo_token_delete as deleted


class Cursor:
    def __init__(self):
        self.calls = []
        self.active = False
        self.member = (True, True)
        self.last = (101,)

    @contextmanager
    def transaction(self):
        self.calls.append(("transaction", None))
        self.active = True
        try:
            yield
        finally:
            self.active = False
            self.calls.append(("end", None))

    def execute(self, sql, params=None):
        if not self.active:
            raise AssertionError("Every read needs the explicit transaction")
        if not sql.startswith(("select ", "set transaction ")):
            raise AssertionError("No DML, audit change, setup or migration is permitted")
        self.calls.append((sql, params))
        if sql == deleted.READ_ONLY:
            return SimpleNamespace()
        if "from audit.row_change" in sql:
            return SimpleNamespace(fetchone=lambda: self.last)
        if "from space where" in sql:
            return SimpleNamespace(fetchone=lambda: self.member)
        raise AssertionError("Unexpected query")


class TokenDeleteReaderTests(unittest.TestCase):
    def setUp(self):
        self.connection = Cursor()
        self.store = SimpleNamespace(_applying=SimpleNamespace(connection="previous"))
        self.store._call = mock.Mock(side_effect=lambda work: work(self.connection))
        self.store.load = mock.Mock(return_value=SimpleNamespace())
        self.plan = {"action": deleted.ACTION, "read_only": True}
        self.departed = self.enterContext(mock.patch.object(space_members, "departed", return_value=set()))
        self.review = self.enterContext(mock.patch.object(deleted, "review", return_value=self.plan))
        self.lock = mock.Mock(side_effect=lambda connection: connection.calls.append(("inventory claim", None)))

    def test_latest_audit_is_one_scoped_id_without_messages_reasons_or_display_limits(self):
        with self.connection.transaction():
            self.assertEqual(deleted.latest(self.connection, "user2"), 101)
        sql, args = self.connection.calls[1]
        self.assertEqual(args, ("user2", "user2"))
        self.assertIn("before->>'space_id'=%s or after->>'space_id'=%s", sql)
        self.assertIn("order by id desc limit 1", sql)
        self.assertNotIn("message", sql)
        self.assertNotIn("reason", sql)
        self.assertNotIn("change_set_id", sql)

    def test_review_uses_one_readonly_transaction_claim_membership_and_same_connection(self):
        def reviewed(change_id, space, snapshot, store):
            self.assertIs(store._applying.connection, self.connection)
            self.assertTrue(self.connection.active)
            return self.plan
        self.review.side_effect = reviewed
        answer = deleted.read_review(self.store, 17, "user2", self.lock)
        self.assertIs(answer, self.plan)
        self.assertEqual(self.connection.calls[:3], [("transaction", None), (deleted.READ_ONLY, None),
                                                    ("inventory claim", None)])
        self.departed.assert_called_once_with(self.connection, {"user2"})
        self.store.load.assert_called_once_with(conn=self.connection)
        self.assertEqual(self.store._applying.connection, "previous")
        self.assertFalse(self.connection.active)
        self.assertNotIn("for key share", self.connection.calls[3][0].lower())

    def test_malformed_membership_proof_or_invalid_target_never_reaches_snapshot(self):
        for proof in (None, (1, 1), [True, True], (True,), (True, None)):
            self.connection.member = proof
            with self.subTest(proof=proof), self.assertRaises(undo.UndoMissing):
                deleted.read_review(self.store, 17, "user2", self.lock)
        for target in ("../user2", "", None):
            with self.subTest(target=target), self.assertRaises(undo.UndoMissing):
                deleted.read_review(self.store, 17, target, self.lock)
        self.store.load.assert_not_called()
        self.review.assert_not_called()

    def test_departed_or_missing_membership_refuses_before_snapshot_and_historical_facts(self):
        self.departed.return_value = {"user2"}
        with self.assertRaises(undo.UndoMissing):
            deleted.read_review(self.store, 17, "user2", self.lock)
        self.store.load.assert_not_called()
        self.review.assert_not_called()
        self.departed.return_value = set()
        self.connection.member = (True, False)
        with self.assertRaises(undo.UndoMissing):
            deleted.read_review(self.store, 17, "user2", self.lock)
        self.assertEqual(self.store._applying.connection, "previous")

    def test_failure_and_cancellation_restore_connection_without_a_write_or_retry(self):
        for error in (undo.UndoConflict("Fixture conflict"), KeyboardInterrupt()):
            self.review.side_effect = error
            with self.assertRaises(type(error)):
                deleted.read_review(self.store, 17, "home", self.lock)
            self.assertEqual(self.store._applying.connection, "previous")
            self.assertFalse(self.connection.active)
        self.assertEqual(self.store._call.call_count, 2)

    def test_pg_delegates_use_explicit_fake_connection_without_constructing_a_backend(self):
        backend = object.__new__(pg.PgInventory)  # __init__ activates a real venv; never invoke it here.
        backend._applying = SimpleNamespace(connection=self.connection)
        with self.connection.transaction():
            self.assertEqual(backend.undo_token_latest("home"), 101)
        with mock.patch.object(deleted, "read_review", return_value=self.plan) as reader:
            self.assertIs(backend.undo_token_delete_review(17, "home"), self.plan)
        reader.assert_called_once_with(backend, 17, "home", pg._take_lock)
