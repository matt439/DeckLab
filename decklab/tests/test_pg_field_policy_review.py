"""The PostgreSQL field-choice preview's proof (pg_field_policy.review) over fake SQL (E3-S23).

It reuses test_pg_field_policy's fake connection and boundaries: no PostgreSQL, private
configuration, card cache or default inventory is used. Run through scripts/test_fixtures.py.
"""
import unittest

from decklab.lib.state import Invalid, Unavailable, pg_field_policy
from decklab.tests import test_pg_field_policy as base
from decklab.tests.test_pg_field_policy import ID, TEXT, Connection


class ReviewConnection(Connection):
    """Also answers the read-only repeatable-read reader's settings, and never writes."""

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        if flat == "set transaction isolation level repeatable read, read only":
            self.events.append((flat, params))
            self.isolation, self.read_only = "repeatable read", True
            return self
        if flat in ("show transaction_isolation", "show transaction_read_only"):
            self.events.append((flat, params))
            self.rows = [(self.isolation,)] if flat.endswith("isolation") else \
                [("on" if getattr(self, "read_only", False) else "off",)]
            return self
        if flat.startswith(("insert", "update", "delete", "select pg_advisory")):
            raise AssertionError(f"A review must not write or lock: {flat}")
        return super().execute(sql, params)


class PgFieldPolicyReviewTests(unittest.TestCase):
    setUp = base.PgFieldPolicyTests.setUp      # borrowed, so the store tests aren't collected twice
    proof = base.PgFieldPolicyTests.proof

    def load(self, *, conn):
        self.assertIs(conn, self.conn)
        self.assertEqual(conn.info.transaction_status, 2)
        self.assertEqual((conn.isolation, conn.read_only), ("repeatable read", True))
        return conn.visible()[0]

    def review(self, version="target", deck_id=ID, fmt="Constructed"):
        return self.store.field_policy_review(fmt, deck_id, version)

    def test_review_reads_one_read_only_snapshot_and_gives_the_proof_save_rechecks(self):
        self.conn.__class__ = ReviewConnection
        self.assertEqual(self.review(), self.expected)
        self.backend.load.assert_called_once_with(conn=self.conn)
        self.assertEqual(self.conn.events[0], "begin")
        self.assertEqual(self.conn.events[-1], "commit")
        self.assertEqual(self.conn.audit, [])
        self.assertEqual(self.conn.policy, {})
        # The table isn't read: a preview works before migration 0017.
        self.assertFalse(any(isinstance(event, tuple) and "field_policy" in event[0] for event in self.conn.events))
        self.conn.schema = False
        self.assertEqual(self.review(), self.expected)

    def test_missing_unproved_or_wrong_format_lists_are_unavailable_with_fixed_words(self):
        self.conn.__class__ = ReviewConnection
        for case in ("missing-owned", "changed-latest", "wrong-format"):
            with self.subTest(case=case):
                if case == "changed-latest":
                    self.conn.latest = (ID, 1, TEXT + "\nOther private fixture text.\n")
                with self.assertRaises(Unavailable) as caught:
                    self.review(version="owned" if case == "missing-owned" else "target",
                                fmt="Commander" if case == "wrong-format" else "Constructed")
                self.assertEqual(str(caught.exception), pg_field_policy.UNAVAILABLE)
                self.assertNotIn("private", str(caught.exception))
        self.assertEqual(self.conn.audit, [])

    def test_non_home_ids_and_batches_are_refused_before_any_connection(self):
        for deck_id in ("user2/casual/fixture", "product/fixture", ""):
            with self.subTest(deck_id=deck_id), self.assertRaises(Invalid):
                self.review(deck_id=deck_id)
        self.store._call.assert_not_called()
        self.store._batch = lambda: object()
        with self.assertRaises(Invalid):
            self.review()
        self.store._call.assert_not_called()

    def test_a_busy_connection_is_refused_without_a_nested_transaction(self):
        self.conn.__class__ = ReviewConnection
        self.conn.info.transaction_status = 2
        with self.assertRaises(Invalid):
            self.review()
        self.backend.load.assert_not_called()
