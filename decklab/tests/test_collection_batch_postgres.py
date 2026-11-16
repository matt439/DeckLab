"""Real PostgreSQL participant proofs, opt-in via scripts/test_collection_batch_pg.py.

No configured database connection. These tests qualify receipt primitives against
synthetic transactional effects, NOT DeckLab's actual inventory/audit adapter.
"""
import copy
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

from decklab.lib.state import Conflict, Invalid, Unavailable
from decklab.lib.state import pg_collection_batches as batches

RESTART = None
CONNECT = None  # supplied in-process only by the isolated cluster runner
ROW = {"name": "Fixture Card", "set": "tst", "collector_number": "1", "finish": "nonfoil",
       "condition": "NM", "language": "en", "quantity": 3}
VALUE = {"label": "Row 1, small pile", "rows": [ROW], "unresolved": []}


class PostgresBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if CONNECT is None:
            raise unittest.SkipTest("requires the dedicated disposable PostgreSQL batch runner")

    def setUp(self):
        self.bid = str(uuid.uuid4())
        with CONNECT() as c:
            c.execute("truncate collection_batch, synthetic_effect, inventory_revision, space_departure")
            c.execute("update profile set space_id='home' where id='user1'")
            c.execute("insert into inventory_revision values (1)")
        self.call(batches.create, VALUE)

    def call(self, function, *args, profile="user1", space="home"):
        with CONNECT() as c, c.cursor() as cur:
            cur.execute("select 1")  # establish caller transaction
            return function(cur, profile, space, self.bid, *args)

    def token(self):
        return self.call(batches.review, 1)

    @staticmethod
    def apply(cur, value):
        # Stand-in effect deliberately uses the same cursor/transaction as receipt.
        cur.execute("insert into synthetic_effect values (%s)", (value["rows"][0]["quantity"],))
        cur.execute("update inventory_revision set revision=revision+1")
        return {"cards": value["rows"][0]["quantity"]}

    def effects(self):
        with CONNECT() as c:
            return c.execute("select count(*),coalesce(sum(quantity),0) from synthetic_effect").fetchone()

    def test_lost_response_new_connection_matching_retry(self):
        token = self.token()
        self.call(batches.complete, token, self.apply)  # response intentionally ignored
        retry = self.call(batches.complete, token, lambda *_: self.fail("duplicate effect"))
        self.assertEqual(retry["result"], {"cards": 3})
        self.assertEqual(self.effects(), (1, 3))

    def test_receipt_survives_database_crash_restart(self):
        token = self.token()
        first = self.call(batches.complete, token, self.apply)
        RESTART()  # immediate stop forces PostgreSQL WAL recovery, not an in-memory copy
        again = self.call(batches.complete, token, lambda *_: self.fail("duplicate effect"))
        self.assertEqual(first, again)
        self.assertEqual(self.effects(), (1, 3))

    def test_sql_receipt_failure_rolls_back_effect_and_revision(self):
        token = self.token()
        with CONNECT() as c:
            c.execute("create function reject_receipt() returns trigger language plpgsql as $$ "
                      "begin raise exception 'fixture receipt failure'; end $$")
            c.execute("create trigger reject_receipt before update on collection_batch "
                      "for each row when (new.status='committed') execute function reject_receipt()")
        try:
            import psycopg
            with self.assertRaises(psycopg.errors.RaiseException):
                self.call(batches.complete, token, self.apply)
            self.assertEqual(self.effects(), (0, 0))
            self.assertEqual(self.call(batches.read)["status"], "draft")
        finally:
            with CONNECT() as c:
                c.execute("drop trigger reject_receipt on collection_batch")
                c.execute("drop function reject_receipt()")
        self.call(batches.complete, token, self.apply)
        self.assertEqual(self.effects(), (1, 3))

    def test_conflicting_retry_does_not_apply(self):
        token = self.token()
        self.call(batches.complete, token, self.apply)
        token["nonce"] = str(uuid.uuid4())
        with self.assertRaises(Conflict):
            self.call(batches.complete, token, self.apply)
        self.assertEqual(self.effects(), (1, 3))

    def test_concurrent_completion_exactly_one_effect(self):
        token, barrier = self.token(), threading.Barrier(2)
        def worker():
            barrier.wait(timeout=5)
            return self.call(batches.complete, token, self.apply)
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(worker) for _ in range(2)]
            results = [f.result(timeout=10) for f in jobs]
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.effects(), (1, 3))

    def test_failure_after_effect_rolls_back_everything(self):
        token = self.token()
        def fail(cur, value):
            self.apply(cur, value)
            raise RuntimeError("fixture failure")
        with self.assertRaises(RuntimeError):
            self.call(batches.complete, token, fail)
        self.assertEqual(self.effects(), (0, 0))
        self.assertEqual(self.call(batches.read)["status"], "draft")
        self.call(batches.complete, token, self.apply)
        self.assertEqual(self.effects(), (1, 3))

    def test_failure_writing_receipt_rolls_back_effect(self):
        token = self.token()
        def invalid(cur, value):
            self.apply(cur, value)
            return {"too_large": "x" * 20000}
        with self.assertRaises(Invalid):
            self.call(batches.complete, token, invalid)
        self.assertEqual(self.effects(), (0, 0))
        self.assertEqual(self.call(batches.read)["status"], "draft")

    def test_other_profile_and_foreign_space_do_not_read(self):
        with self.assertRaises(Invalid):
            self.call(batches.read, profile="user2", space="user2")
        with self.assertRaises(Invalid):
            self.call(batches.read, profile="user2", space="home")
        with self.assertRaises(Invalid):
            self.call(batches.read, profile="user3", space="home")  # household peer too

    def test_permission_removed_even_receipt_retry_denied(self):
        token = self.token()
        self.call(batches.complete, token, self.apply)
        with CONNECT() as c:
            c.execute("update profile set space_id='user2' where id='user1'")
        with self.assertRaises(Invalid):
            self.call(batches.complete, token, self.apply)
        self.assertEqual(self.effects(), (1, 3))

    def test_departed_member_refused(self):
        self.bid = str(uuid.uuid4())
        self.call(batches.create, VALUE, profile="user2", space="user2")
        with CONNECT() as c:
            c.execute("insert into space_departure values ('user2')")
        with self.assertRaises(Invalid):
            self.call(batches.read, profile="user2", space="user2")

    def test_stale_save_and_old_review_refused(self):
        token = self.token()
        changed = copy.deepcopy(VALUE)
        changed["rows"][0]["quantity"] = 7
        self.call(batches.save, 1, changed)
        with self.assertRaises(Conflict):
            self.call(batches.save, 1, VALUE)
        with self.assertRaises(Conflict):
            self.call(batches.complete, token, self.apply)
        self.assertEqual(self.call(batches.read)["content"]["rows"][0]["quantity"], 7)

    def test_inventory_revision_change_requires_review(self):
        token = self.token()
        with CONNECT() as c:
            c.execute("update inventory_revision set revision=revision+1")
        with self.assertRaises(Conflict):
            self.call(batches.complete, token, self.apply)
        fresh = self.token()
        self.call(batches.complete, fresh, self.apply)
        self.assertEqual(self.effects(), (1, 3))

    def test_consumed_identity_never_reopens_and_identical_new_batch_valid(self):
        self.call(batches.complete, self.token(), self.apply)
        self.assertEqual(self.call(batches.create, VALUE)["status"], "committed")
        self.bid = str(uuid.uuid4())
        self.call(batches.create, VALUE)
        self.call(batches.complete, self.token(), self.apply)
        self.assertEqual(self.effects(), (2, 6))

    def test_discard_is_tombstone(self):
        self.call(batches.discard, 1)
        self.assertEqual(self.call(batches.create, VALUE)["status"], "discarded")
        with self.assertRaises(Conflict):
            self.call(batches.save, 2, VALUE)

    def test_single_active_batch_and_create_retry_conflict(self):
        changed = copy.deepcopy(VALUE)
        changed["label"] = "different physical pile"
        with self.assertRaises(Conflict):
            self.call(batches.create, changed)
        self.bid = str(uuid.uuid4())
        with self.assertRaises(Conflict):
            self.call(batches.create, VALUE)

    def test_ambiguous_or_empty_cannot_complete(self):
        value = copy.deepcopy(VALUE)
        value["unresolved"] = ["check set on card 5"]
        self.call(batches.save, 1, value)
        with self.assertRaises(Invalid):
            self.call(batches.review, 2)

    def test_missing_schema_is_unavailable_without_sql_error(self):
        with CONNECT() as c, c.cursor() as cur:
            cur.execute("alter table collection_batch rename to hidden_batch")
            try:
                with self.assertRaises(Unavailable):
                    batches.read(cur, "user1", "home", self.bid)
            finally:
                cur.execute("alter table hidden_batch rename to collection_batch")

    def test_no_caller_transaction_refused(self):
        with CONNECT() as c:
            c.autocommit = True
            with c.cursor() as cur, self.assertRaises(Invalid):
                batches.read(cur, "user1", "home", self.bid)
