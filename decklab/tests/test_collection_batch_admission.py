"""Compatibility floor on isolated PostgreSQL only; no install or public activation."""
import threading
import unittest
import uuid
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory.batch_import import BatchImport
from decklab.lib.state import Actor, Conflict, Invalid
from decklab.lib.state import pg_collection_batches as batches
from decklab.tests.test_collection_batch_inventory import InventoryFixture, VALUE

POLICY_SQL = """
create table public.collection_batch_admission (
 singleton integer primary key check(singleton=1), contract integer not null check(contract=1),
 epoch bigint not null check(epoch>0), enabled boolean not null);
insert into public.collection_batch_admission values (1,1,1,false);
revoke all on public.collection_batch_admission from public, decklab_app, decklab_ro;
grant select on public.collection_batch_admission to decklab_app, decklab_ro;
"""


class AdmissionTests(InventoryFixture, unittest.TestCase):
    def install_admission(self):
        with self.connection('owner') as c:
            c.execute("select pg_advisory_xact_lock(hashtext('inventory'))")
            c.execute(POLICY_SQL)
            c.execute('update collection_batch_admission set enabled=true')
        return {'contract': 1, 'epoch': 1}

    def transition_admission(self, enabled):
        with self.connection('owner') as c:
            c.execute("select pg_advisory_xact_lock(hashtext('inventory'))")
            epoch = c.execute('update collection_batch_admission set enabled=%s,epoch=epoch+1 returning epoch', (enabled,)).fetchone()[0]
        return {'contract': 1, 'epoch': epoch}

    def test_pause_commits_before_waiting_old_epoch_completion(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        from decklab.lib.inventory.batch_import import BatchImport
        from decklab.lib.state import Actor, Conflict, Invalid
        offered = self.install_admission()
        with self.connection() as c, c.cursor() as cur:
            cur.execute('select 1')
            token = batches.review(cur, self.profile, self.space, self.bid, 1, admission=offered)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.connection('owner') as c:
                c.execute("select pg_advisory_xact_lock(hashtext('inventory'))")
                c.execute('update collection_batch_admission set enabled=false,epoch=epoch+1')
                future = pool.submit(self.backend.apply, BatchImport('home',self.bid,token,offered),
                    Actor('user1','Fixture user','home'), 'Delayed old epoch completion')
                deadline = time.monotonic()+5
                waiting = False
                while time.monotonic()<deadline:
                    waiting = c.execute("select exists(select 1 from pg_locks where locktype='advisory' and not granted "
                        "and database=(select oid from pg_database where datname=current_database()))").fetchone()[0]
                    if waiting:
                        break
                    time.sleep(.01)
                self.assertTrue(waiting, 'completion never reached the inventory lock')
            with self.assertRaises(Conflict):
                future.result(timeout=10)
        self.assertEqual(self.counts()[:3], (0,0,0))
        self.assertEqual(self.call(batches.read)['status'], 'draft')
    def test_admission_rejects_bad_capabilities_and_rolls_back_failed_receipt(self):
        from decklab.lib.inventory import batch_import
        from decklab.lib.state import Actor, Conflict, Invalid
        legacy_token = self.call(batches.review, 1)
        offered = self.install_admission()
        with self.assertRaises(Conflict):
            self.backend.apply(batch_import.BatchImport('home', self.bid, legacy_token, offered),
                               Actor('user1','Fixture user','home'), 'Old review cannot acquire a new epoch')
        with self.connection() as c, c.cursor() as cur:
            cur.execute('select 1')
            token = batches.review(cur, self.profile, self.space, self.bid, 1, admission=offered)
        before, row = self.counts(), self.call(batches.read)
        actor = Actor('user1','Fixture user','home')
        for bad in (None, {}, {'contract':0,'epoch':1}, {'contract':2,'epoch':1},
                    {'contract':1,'epoch':0}, {'contract':True,'epoch':1},
                    {'contract':1,'epoch':True}, {'contract':1,'epoch':1,'extra':1}):
            with self.assertRaises(Conflict):
                self.backend.apply(batch_import.BatchImport('home',self.bid,token,bad), actor, 'Bad capability')
            self.assertEqual(self.counts(), before)
        with mock.patch.object(batch_import, 'finish', side_effect=Invalid('synthetic receipt failure')):
            with self.assertRaises(Invalid):
                self.backend.apply(batch_import.BatchImport('home',self.bid,token,offered), actor, 'Rollback admitted write')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.call(batches.read), row)
        import psycopg
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.connection() as c:
                c.execute('update collection_batch_admission set enabled=false')

    def test_admitted_completion_commits_before_waiting_pause(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        from decklab.lib.inventory import batch_import
        from decklab.lib.state import Actor
        offered = self.install_admission()
        with self.connection() as c, c.cursor() as cur:
            cur.execute('select 1')
            token = batches.review(cur, self.profile, self.space, self.bid, 1, admission=offered)
        admitted, release = threading.Event(), threading.Event()
        original = batch_import.run
        def delayed(*args):
            admitted.set()
            if not release.wait(8):
                raise AssertionError('completion release timed out')
            return original(*args)
        with ThreadPoolExecutor(max_workers=2) as pool, mock.patch.object(batch_import, 'run', side_effect=delayed):
            completion = pool.submit(self.backend.apply, batch_import.BatchImport('home',self.bid,token,offered),
                                     Actor('user1','Fixture user','home'), 'Admitted completion')
            try:
                self.assertTrue(admitted.wait(5))
                pause = pool.submit(self.transition_admission, False)
                deadline = time.monotonic()+5
                waiting = False
                with self.connection('ro') as c:
                    while time.monotonic()<deadline:
                        waiting = c.execute("select exists(select 1 from pg_locks where locktype='advisory' and not granted "
                            "and database=(select oid from pg_database where datname=current_database()))").fetchone()[0]
                        if waiting:
                            break
                        time.sleep(.01)
                self.assertTrue(waiting, 'pause never waited behind admitted completion')
            finally:
                release.set()
            _, summary = completion.result(timeout=10)
            self.assertEqual(pause.result(timeout=10), {'contract':1,'epoch':2})
        before = self.counts()
        self.assertEqual(before[:3], (3,1,1))
        _, replay = self.complete(token)
        self.assertEqual(replay.extra['collection_batch'], summary.extra['collection_batch'])
        self.assertEqual(self.counts(), before)

    def test_absent_policy_and_paused_receipt_only_rollback(self):
        # Existing callers work without a policy table; no policy is created by runtime calls.
        token = self.call(batches.review, 1)
        self.complete(token)
        receipt = self.call(batches.read)
        before = self.counts()
        self.install_admission()
        self.transition_admission(False)
        _, replay = self.complete(token)
        self.assertEqual(replay.extra['collection_batch'], receipt['receipt'])
        self.assertEqual(self.call(batches.read), receipt)
        self.assertEqual(self.counts(), before)
        with self.connection() as c, c.cursor() as cur:
            cur.execute('select 1')
            with self.assertRaises(Invalid):
                batches.read(cur, 'matt', self.space, self.bid)
        self.assertEqual(self.counts(), before)

    def test_paused_mutations_refused_but_ordinary_import_and_add_unchanged(self):
        token = self.call(batches.review, 1)
        offered = self.install_admission()
        self.transition_admission(False)
        before, row = self.counts(), self.call(batches.read)
        actions = [
            lambda cur: batches.create(cur, self.profile, self.space, str(uuid.uuid4()), VALUE, admission=offered),
            lambda cur: batches.save(cur, self.profile, self.space, self.bid, 1, VALUE, admission=offered),
            lambda cur: batches.review(cur, self.profile, self.space, self.bid, 1, admission=offered),
            lambda cur: batches.discard(cur, self.profile, self.space, self.bid, 1, admission=offered),
            lambda cur: batches.complete(cur, self.profile, self.space, self.bid, token,
                lambda *args: self.fail('paused callback executed'), admission=offered),
        ]
        for action in actions:
            with self.assertRaises(Conflict):
                with self.connection() as c, c.cursor() as cur:
                    cur.execute('select 1')
                    action(cur)
            self.assertEqual(self.call(batches.read), row)
            self.assertEqual(self.counts(), before)
        # Exact original creation retry is only a read, even while paused.
        self.assertEqual(self.call(batches.create, VALUE), row)
        with self.assertRaises(Conflict):
            self.complete(token)
        actor = Actor('user1', 'Fixture user', 'home')
        card = {'name':'Elvish Mystic','set':'cmm','collector_number':'648','finish':'nonfoil',
                'quantity':'1','condition':'','language':'','notes':''}
        self.backend.apply(inventory.Op('collection.add', {'space':'home','row':card}), actor, 'Ordinary addition')
        imported = {**VALUE['rows'][0], 'quantity':'2', 'notes':''}
        self.backend.apply(inventory.Op('collection.import', {'space':'home','sources':[('ordinary CSV',[imported])],
            'uploads':[('ordinary CSV','name,set,collector_number,finish,quantity\nLlanowar Elves,fdn,227,nonfoil,2\n')]}), actor, 'Ordinary CSV')
        self.assertEqual(self.counts()[:3], (3, 1, 1))
        self.assertEqual(self.call(batches.read), row)
    def test_reopened_epoch_requires_new_review_not_just_fresh_capability(self):
        first = self.install_admission()
        with self.connection() as c, c.cursor() as cur:
            cur.execute('select 1')
            old = batches.review(cur, self.profile, self.space, self.bid, 1, admission=first)
        self.assertEqual(self.transition_admission(False), {'contract': 1, 'epoch': 2})
        fresh = self.transition_admission(True)
        self.assertEqual(fresh, {'contract': 1, 'epoch': 3})
        before, row = self.counts(), self.call(batches.read)
        actor = Actor('user1', 'Fixture user', 'home')
        with self.assertRaises(Conflict):
            self.backend.apply(BatchImport('home', self.bid, old, fresh), actor, 'Old review with new capability')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.call(batches.read), row)
        with self.connection() as c, c.cursor() as cur:
            cur.execute('select 1')
            renewed = batches.review(cur, self.profile, self.space, self.bid, 1, admission=fresh)
        self.backend.apply(BatchImport('home', self.bid, renewed, fresh), actor, 'Freshly reviewed intent')
        self.assertEqual(self.counts()[:3], (3, 1, 1))
