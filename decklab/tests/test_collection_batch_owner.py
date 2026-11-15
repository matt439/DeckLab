"""Owner policy transaction tests; only the isolated PG runner may provide connections."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from decklab.db import collection_batch_transition as owner
from decklab.lib.state import Conflict, Invalid
from decklab.lib.state import pg_collection_batches as batches
from decklab.tests.test_collection_batch_admission import POLICY_SQL
from decklab.tests.test_collection_batch_inventory import InventoryFixture


class OwnerTransitionTests(InventoryFixture, unittest.TestCase):
    def install(self):
        with self.connection('owner') as c:
            c.execute(POLICY_SQL)

    def invoke(self, fn, role='owner', **intent):
        with self.connection(role) as c, c.cursor() as cur:
            cur.execute('select 1')
            result = fn(cur, **intent)
        return result

    def test_missing_schema_permissions_validation_and_noop(self):
        intent = dict(contract=1,epoch=1,enabled=True)
        with self.assertRaises(Invalid):
            self.invoke(owner.transition, **intent)
        self.install()
        for role in ('app','ro'):
            with self.assertRaises(Invalid):
                self.invoke(owner.transition, role=role, **intent)
        for bad in (dict(epoch=True),dict(epoch=0),dict(contract=2),dict(enabled=1),dict(epoch=owner.MAX_EPOCH)):
            with self.assertRaises(Invalid):
                self.invoke(owner.transition, **(intent|bad))
        with self.assertRaises(Invalid):
            self.invoke(owner.transition, **(intent|dict(enabled=False)))
        self.assertEqual(self.invoke(owner.recover, **intent)['outcome'], 'unchanged')

    def test_same_intent_retry_and_stale_attempt_never_retoggle(self):
        self.install()
        intent = dict(contract=1,epoch=1,enabled=True)
        self.assertEqual(self.invoke(owner.transition, **intent)['outcome'], 'transitioned')
        self.assertEqual(self.invoke(owner.transition, **intent)['outcome'], 'target_confirmed')
        self.invoke(owner.transition, contract=1,epoch=2,enabled=False)
        with self.assertRaises(Conflict):
            self.invoke(owner.transition, **intent)
        self.assertEqual(self.invoke(owner.recover, **intent)['outcome'], 'conflict')

    def test_pause_preserves_existing_receipt_and_retry(self):
        token = self.call(batches.review, 1)
        self.complete(token)
        row, counts = self.call(batches.read), self.counts()
        self.install()
        self.invoke(owner.transition, contract=1,epoch=1,enabled=True)
        self.invoke(owner.transition, contract=1,epoch=2,enabled=False)
        self.complete(token)
        self.assertEqual(self.call(batches.read), row)
        self.assertEqual(self.counts(), counts)

    def test_lost_ack_recovery_waits_for_committing_transition(self):
        import time
        self.install()
        intent = dict(contract=1,epoch=1,enabled=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.connection('owner') as c, c.cursor() as cur:
                cur.execute('select 1')
                owner.transition(cur, **intent)
                recovery = pool.submit(self.invoke, owner.recover, **intent)
                deadline = time.monotonic()+3
                waiting = False
                while time.monotonic() < deadline:
                    waiting = c.execute("select exists(select 1 from pg_locks where locktype='advisory' and not granted "
                        "and database=(select oid from pg_database where datname=current_database()))").fetchone()[0]
                    if waiting:
                        break
                    time.sleep(.01)
                self.assertTrue(waiting)
            self.assertEqual(recovery.result(timeout=6)['outcome'], 'target_confirmed')
        self.assertEqual(self.invoke(owner.transition, **intent)['policy']['epoch'], 2)

    def test_rollback_before_commit_leaves_same_intent_retryable(self):
        self.install()
        intent = dict(contract=1,epoch=1,enabled=True)
        with self.assertRaises(RuntimeError):
            with self.connection('owner') as c, c.cursor() as cur:
                cur.execute('select 1')
                owner.transition(cur, **intent)
                raise RuntimeError('synthetic precommit failure')
        self.assertEqual(self.invoke(owner.recover, **intent)['outcome'], 'unchanged')
        self.assertEqual(self.invoke(owner.transition, **intent)['policy']['epoch'], 2)

    def test_explicit_module_command_on_disposable_database(self):
        import contextlib
        import io
        import json
        self.install()
        args = ['--dbname', self.dbname, '--contract', '1', '--epoch', '1', '--target', 'enabled']
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(owner.main(args), 0)
        self.assertEqual(json.loads(output.getvalue())['policy']['epoch'], 2)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(owner.main(args+['--recover']), 0)
        self.assertEqual(json.loads(output.getvalue())['outcome'], 'target_confirmed')

    def test_command_lost_commit_ack_is_unknown_then_same_intent_recovers(self):
        import contextlib
        import io
        from unittest import mock
        from decklab.db import conn as db
        self.install()
        args = ['--dbname', self.dbname, '--contract', '1', '--epoch', '1', '--target', 'enabled']
        @contextlib.contextmanager
        def lost_ack(*pos, **kw):
            with self.connection(*pos, **kw) as c:
                yield c
            raise OSError('synthetic lost commit acknowledgement')
        output = io.StringIO()
        with mock.patch.object(db, 'connect', side_effect=lost_ack), contextlib.redirect_stdout(output):
            self.assertEqual(owner.main(args), 2)
        self.assertIn('Outcome unconfirmed', output.getvalue())
        self.assertNotIn('transitioned', output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(owner.main(args+['--recover']), 0)
        self.assertEqual(self.invoke(owner.transition, contract=1,epoch=1,enabled=True)['policy']['epoch'], 2)

    def test_concurrent_identical_attempts_advance_only_once(self):
        self.install()
        intent = dict(contract=1,epoch=1,enabled=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [pool.submit(self.invoke, owner.transition, **intent) for _ in range(2)]
            results = [attempt.result(timeout=8) for attempt in attempts]
        self.assertEqual({result['outcome'] for result in results}, {'transitioned','target_confirmed'})
        self.assertEqual({result['policy']['epoch'] for result in results}, {2})
