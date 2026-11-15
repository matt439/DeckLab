"""Signed normal dispatch to receipt-only candidate, installed only by this PG fixture."""
import http.client
import json
import tempfile
import threading
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest import mock

from decklab.db import collection_batch_transition as owner
from decklab.lib import access, feature_routes, inventory, server_http, state
from decklab.lib.api import collection_batch_receipt as receipt
from decklab.lib.state import pg_collection_batches as batches
from decklab.tests import test_access as signed
from decklab.tests.test_collection_batch_admission import POLICY_SQL
from decklab.tests.test_collection_batch_inventory import InventoryFixture

ROUTE = '/api/collection/batch-receipt'


class ClosureTests(unittest.TestCase):
    def test_no_normal_registration_or_anonymous_backend(self):
        from decklab.lib.api.common import ApiError
        gets, posts = feature_routes.route_tables()
        self.assertNotIn(('collection','batch-receipt'), gets)
        self.assertNotIn(('collection','batch-receipt'), posts)
        with mock.patch.object(receipt.private.guard, 'viewer', return_value=None), mock.patch.object(receipt.private, '_backend') as backend:
            with self.assertRaises(ApiError):
                receipt.view('home', str(uuid.uuid4()))
            backend.assert_not_called()


class ReceiptRuntimeTests(InventoryFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from decklab.lib.state.pg import PgStore
        self.enterContext(inventory.use(self.backend))
        self.enterContext(state.use(PgStore(dbname=self.dbname)))
        original = feature_routes.route_tables
        def routes():
            gets, posts = original()
            return {**gets, ('collection','batch-receipt'): (receipt.view, ('space','batch_id'))}, posts
        self.enterContext(mock.patch.object(feature_routes, 'route_tables', side_effect=routes))
        self.enterContext(mock.patch.object(feature_routes, 'ACCESS', {
            **feature_routes.ACCESS, ('GET','collection/batch-receipt'): 'collection'}))
        profiles = [{'id': name, 'name': name, 'emails':[name+'@example.com'], 'role':'admin',
                     'space':'home', 'plays_as':'user'} for name in ('user1','matt')]
        verifier = access.Verifier(signed.TEAM, signed.AUD, fetch=signed.Fetcher(),
                                   clock=signed.Clock(), profiles=lambda:profiles)
        web = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='decklab-receipt-http-')))
        self.httpd = server_http.make_server('127.0.0.1', 0, web_dir=web, access=verifier, tunnel_hosts=('127.0.0.1',))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)

    def request(self, who='user1', batch_id=None, method='GET'):
        headers = {'Cf-Access-Jwt-Assertion':signed.token(signed.claims(email=who+'@example.com'))} if who else {}
        with closing(http.client.HTTPConnection('127.0.0.1', self.httpd.server_address[1], timeout=10)) as c:
            c.request(method, ROUTE+'?space=home&batch_id='+(batch_id or self.bid), headers=headers)
            r = c.getresponse()
            return r.status, dict(r.headers), json.loads(r.read())

    def test_paused_original_receipt_signed_recovery_and_retry_no_effects(self):
        token = self.call(batches.review, 1)
        self.complete(token)
        row, counts = self.call(batches.read), self.counts()
        with self.connection('owner') as c, c.cursor() as cur:
            cur.execute(POLICY_SQL)
            owner.transition(cur, contract=1,epoch=1,enabled=True)
        with self.connection('owner') as c, c.cursor() as cur:
            cur.execute('select 1')
            owner.transition(cur, contract=1,epoch=2,enabled=False)
        for _ in range(2):
            code, headers, body = self.request()
            self.assertEqual(code, 200, body)
            self.assertIn('no-store', headers['Cache-Control'])
            self.assertEqual(body, dict(batch_id=self.bid,space='home',state='committed',receipt=row['receipt']))
        self.complete(token)
        self.assertEqual(self.counts(), counts)
        self.assertEqual(self.call(batches.read), row)

    def test_foreign_missing_and_retired_identity_share_unavailable_response(self):
        peer = self.request('matt')
        missing = self.request(batch_id=str(uuid.uuid4()))
        self.assertEqual(peer[0], 404)
        self.assertEqual(peer[2], missing[2])
        with self.connection('owner') as c:
            c.execute('delete from collection_batch where batch_id=%s', (self.bid,))
        retired = self.request()
        self.assertEqual(retired[0], 404)
        self.assertEqual(retired[2], missing[2])
        self.assertNotIn('draft', json.dumps(retired[2]))

    def test_pending_discarded_unavailable_are_never_success_or_content(self):
        row, counts = self.call(batches.read), self.counts()
        code, _, body = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(body['state'], 'unconfirmed')
        self.assertFalse({'draft','review','receipt','label','evidence'} & body.keys())
        self.assertEqual(self.call(batches.read), row)
        self.call(batches.discard, 1)
        self.assertEqual(self.request()[2]['state'], 'discarded')
        with mock.patch.object(receipt.private, '_backend', side_effect=state.Unavailable('synthetic DB unavailable')):
            code, _, body = self.request()
            self.assertEqual(code, 503)
            self.assertEqual(body['code'], 'batch_unconfirmed')
        self.assertEqual(self.counts(), counts)

    def test_missing_schema_and_post_do_not_enable_write_path(self):
        with self.connection('owner') as c:
            c.execute('drop table collection_batch')
        code, _, body = self.request()
        self.assertEqual(code, 503)
        self.assertEqual(body['code'], 'batch_not_installed')
        self.assertIn(self.request(method='POST')[0], (404,405))
        self.assertIn(self.request(who=None)[0], (401,403))

    def test_signed_removed_profile_cannot_recover_using_stale_config(self):
        from decklab.db import conn as db
        with self.connection('owner', autocommit=True) as c, db.change(
                'system', 'cli', 'Remove synthetic profile', conn=c) as (cur, _):
            cur.execute("delete from profile where id='user1'")
        code, _, body = self.request()
        self.assertEqual(code, 403, body)
        self.assertFalse({'draft','review','receipt','label','evidence'} & body.keys())
