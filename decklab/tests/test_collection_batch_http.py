"""Unregistered candidate adapter over the real loopback HTTP guards and staged DB.

Only this fixture supplies a dispatch shim. Normal production feature tables stay
unchanged. Tunnel identity tests inject an already verified identity, not a fake JWT.
"""
import copy
import http.client
import json
import tempfile
import threading
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest import mock

from decklab.lib import access, feature_routes, inventory, server_http, state
from decklab.lib.api import collection_batches as api
from decklab.lib.api.common import ApiError
from decklab.lib.state import pg_collection_batches as batches
from decklab.tests.test_collection_batch_inventory import VALUE, InventoryFixture

ROUTE = "/api/collection/batches"


class ClosedRouteTests(unittest.TestCase):
    def test_default_feature_tables_have_no_batch_route(self):
        gets, posts = feature_routes.route_tables()
        self.assertNotIn(("collection", "batches"), gets)
        self.assertNotIn(("collection", "batches"), posts)
        self.assertNotIn(("GET", "collection/batches"), feature_routes.ACCESS)
        self.assertNotIn(("POST", "collection/batches"), feature_routes.ACCESS)

    def test_fixture_browser_assets_are_not_in_normal_static_allowlist(self):
        assets = server_http.static_files()
        self.assertNotIn("/batch.js", assets)
        self.assertNotIn("/batch.css", assets)
        self.assertNotIn("/scanner.html", assets)
        self.assertNotIn("/native-source.js", assets)
        self.assertNotIn("/design/batch-browser/index.html", assets)

    def test_anonymous_adapter_request_never_opens_backend(self):
        with mock.patch.object(api.guard, "viewer", return_value=None), mock.patch.object(api, "_backend") as backend:
            with self.assertRaises(ApiError) as error:
                api.view("home")
            self.assertEqual(error.exception.status, 403)
            backend.assert_not_called()


class HttpFixture(InventoryFixture):
    def setUp(self):
        super().setUp()
        from decklab.lib.state.pg import PgStore
        self.enterContext(inventory.use(self.backend))
        self.enterContext(state.use(PgStore(dbname=self.dbname)))
        self.original_dispatch = feature_routes.dispatch
        def staged_dispatch(handler, route, query):
            if tuple(route) != ("collection", "batches"):
                return self.original_dispatch(handler, route, query)
            if handler.command in ("GET", "HEAD"):
                handler._allow("GET", "HEAD")
                answer = api.view(**handler._query(query, ("space", "batch_id")))
            else:
                handler._allow("POST")
                handler._no_query(query)
                answer = api.change(handler._write_body(api.MAX_BODY))
            handler._send_json(200, answer)
            return True
        self.enterContext(mock.patch.object(feature_routes, "dispatch", side_effect=staged_dispatch))
        self.logs = []
        self.enterContext(mock.patch.object(server_http, "log", side_effect=self.logs.append))
        web = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="decklab-batch-http-")))
        self.httpd = server_http.make_server("127.0.0.1", 0, web_dir=web)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)

    def request(self, method="GET", data=None, viewer="user1", path=None, headers=None):
        sent = {"X-Deck-Lab": "1", "Content-Type": "application/json"}
        if viewer is not None:
            sent["X-Deck-Lab-Viewer"] = viewer
        sent.update(headers or {})
        body = json.dumps(data).encode() if data is not None else None
        with closing(http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)) as c:
            c.request(method, path or ROUTE, body=body, headers=sent)
            response = c.getresponse()
            return response.status, dict(response.headers), json.loads(response.read())

    def post(self, action, **fields):
        return self.request("POST", {"profile": "user1", "space": "home", "batch_id": self.bid,
                                     "action": action, **fields})


class HttpBatchTests(HttpFixture, unittest.TestCase):
    def test_normal_startup_route_tables_do_not_register_candidate(self):
        gets, posts = feature_routes.route_tables()
        self.assertNotIn(("collection", "batches"), gets)
        self.assertNotIn(("collection", "batches"), posts)
        with mock.patch.object(feature_routes, "dispatch", side_effect=self.original_dispatch):
            self.assertEqual(self.request()[0], 404)

    def test_own_get_is_private_peer_and_foreign_space_are_denied(self):
        path = ROUTE + "?space=home&batch_id=" + self.bid
        code, headers, result = self.request(path=path)
        self.assertEqual(code, 200, result)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertEqual(result["draft"], VALUE)
        self.assertEqual(self.request(viewer="matt", path=path)[0], 404)
        self.assertEqual(self.request(viewer="user2", path=path)[0], 403)
        missing = self.request(path=ROUTE + "?batch_id=" + str(uuid.uuid4()))
        self.assertEqual(missing[0], 404)
        self.assertNotIn(VALUE["label"], json.dumps(missing[2]))

    def test_anonymous_or_mismatched_writer_is_refused(self):
        self.assertEqual(self.request(viewer=None)[0], 403)
        data = {"profile": "user1", "space": "home", "batch_id": self.bid, "action": "review", "expect": 1}
        self.assertEqual(self.request("POST", data, viewer=None)[0], 403)
        self.assertEqual(self.request("POST", data, viewer="matt")[0], 403)
        self.assertEqual(self.call(batches.read)["review"], None)

    def test_tunnel_identity_cannot_claim_another_profile_or_space(self):
        data = {"profile": "user1", "space": "home", "batch_id": self.bid, "action": "review", "expect": 1}
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            with self.assertRaises(ApiError) as error:
                api.change(json.dumps(data).encode())
            self.assertEqual(error.exception.status, 403)
            with self.assertRaises(ApiError) as error:
                api.view("home", self.bid)
            self.assertEqual(error.exception.status, 403)

    def test_stale_tabs_do_not_overwrite_and_edit_invalidates_review(self):
        code, _, reviewed = self.post("review", expect=1)
        self.assertEqual(code, 200, reviewed)
        value = copy.deepcopy(VALUE)
        value["rows"][0]["quantity"] = 7
        self.assertEqual(self.post("save", expect=1, draft=value)[0], 200)
        code, _, conflict = self.post("save", expect=1, draft=VALUE)
        self.assertEqual(code, 409, conflict)
        self.assertTrue(conflict["reload"])
        self.assertEqual(self.post("complete", review=reviewed["review"])[0], 409)
        self.assertEqual(self.call(batches.read)["content"]["rows"][0]["quantity"], 7)

    def test_review_then_safe_repeat_returns_original_receipt_once(self):
        before = self.counts()
        code, _, reviewed = self.post("review", expect=1)
        self.assertEqual(code, 200, reviewed)
        self.assertEqual(reviewed["summary"]["cards"], 3)
        code, _, saved = self.post("complete", review=reviewed["review"])
        self.assertEqual(code, 200, saved)
        code, _, retry = self.post("complete", review=reviewed["review"])
        self.assertEqual(code, 200, retry)
        self.assertEqual(saved["receipt"], retry["receipt"])
        malformed = {**reviewed["review"], "revision": True}
        self.assertEqual(self.post("complete", review=malformed)[0], 409)
        self.assertEqual(self.counts()[:4], (3, 1, 1, before[3] + 1))
        self.assertEqual(self.request()[2]["batches"][0]["status"], "committed")

    def test_lost_database_ack_says_unconfirmed_then_same_batch_retry_recovers(self):
        token = self.post("review", expect=1)[2]["review"]
        apply = self.backend.apply
        def lost(*args, **kwargs):
            apply(*args, **kwargs)
            raise state.Unavailable("private fixture database path must not be exposed")
        with mock.patch.object(self.backend, "apply", side_effect=lost):
            code, _, uncertain = self.post("complete", review=token)
        self.assertEqual(code, 503, uncertain)
        self.assertEqual(uncertain["retry"], "same_batch")
        self.assertNotIn("private fixture", json.dumps(uncertain))
        self.assertNotIn("nothing was saved", json.dumps(uncertain).lower())
        before = self.counts()
        self.assertEqual(self.post("complete", review=token)[0], 200)
        self.assertEqual(self.counts(), before)

    def test_normal_http_write_guards_and_method_rules_are_retained(self):
        data = {"profile": "user1", "space": "home", "batch_id": self.bid, "action": "review", "expect": 1}
        self.assertEqual(self.request("POST", data, headers={"Origin": "https://foreign.example.com"})[0], 403)
        self.assertEqual(self.request("POST", data, headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", data, headers={"X-Deck-Lab": "0"})[0], 403)
        self.assertEqual(self.request("DELETE", data)[0], 405)
        self.assertIsNone(self.call(batches.read)["review"])

    def test_unknown_owner_keys_and_oversize_requests_are_refused(self):
        self.assertEqual(self.post("review", expect=1, owner="matt")[0], 400)
        self.assertEqual(self.post("save", expect=1, draft={"label": "x" * api.MAX_BODY})[0], 413)
        self.assertEqual(self.call(batches.read)["revision"], 1)

    def test_invalid_printing_review_never_issues_a_token(self):
        value = copy.deepcopy(VALUE)
        value["rows"][0]["collector_number"] = "999999"
        self.assertEqual(self.post("save", expect=1, draft=value)[0], 200)
        self.assertEqual(self.post("review", expect=2)[0], 400)
        self.assertIsNone(self.call(batches.read)["review"])
        self.assertEqual(self.counts()[:3], (0, 0, 0))

    def test_missing_schema_is_disabled_not_an_unsaved_success(self):
        with self.connection("owner") as c:
            c.execute("drop table collection_batch")
        code, _, result = self.request()
        self.assertEqual(code, 503, result)
        self.assertEqual(result["code"], "batch_not_installed")
        self.assertIs(result["available"], False)

    def test_recovery_index_is_bounded_and_never_lists_a_household_peer(self):
        for _ in range(12):
            self.call(batches.discard, 1)
            self.bid = str(uuid.uuid4())
            self.call(batches.create, VALUE)
        code, _, index = self.request()
        self.assertEqual(code, 200, index)
        self.assertEqual(len(index["batches"]), 10)
        self.assertTrue(index["has_more"])
        self.assertEqual(index["batches"][0]["batch_id"], self.bid)
        self.assertEqual(self.request(viewer="matt")[2]["batches"], [])

    def test_second_review_replaces_token_without_changing_draft_revision(self):
        first = self.post("review", expect=1)[2]["review"]
        second = self.post("review", expect=1)[2]["review"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.post("complete", review=first)[0], 409)
        self.assertEqual(self.call(batches.read)["revision"], 1)
        self.assertEqual(self.post("complete", review=second)[0], 200)

    def test_create_retry_is_same_identity_not_a_second_pile(self):
        self.assertEqual(self.post("create", draft=VALUE)[0], 200)
        value = copy.deepcopy(VALUE)
        value["rows"][0]["quantity"] = 4
        self.assertEqual(self.post("create", draft=value)[0], 409)
        self.assertEqual(self.call(batches.read)["content"], VALUE)
        self.assertEqual(len(self.request()[2]["batches"]), 1)

    def test_stale_member_session_is_rechecked_against_database_membership(self):
        from decklab.db import conn as db
        bid = str(uuid.uuid4())
        data = {"profile": "user2", "space": "user2", "batch_id": bid, "action": "create", "draft": VALUE}
        verifier = mock.Mock()
        verifier.identify.return_value = {"profile": "user2", "email": "user2@example.com", "remote": True}
        headers = {"Host": "batch.example.com", "Cf-Access-Jwt-Assertion": "fixture-already-verified"}
        # Member spaces use the existing tunnel listener, not home's household-only chooser.
        with mock.patch.multiple(self.httpd, remote=True, access=verifier, tunnel_hosts=frozenset({"batch.example.com"})):
            code, _, result = self.request("POST", data, viewer=None, headers=headers)
            self.assertEqual(code, 200, result)
            # Normal tunnel transport replaces a spoofed body actor with the verified login.
            self.assertEqual(self.request("POST", {**data, "profile": "user1"}, viewer=None, headers=headers)[0], 200)
            self.assertEqual(self.request("POST", {**data, "profile": "user1", "space": "home"},
                                          viewer=None, headers=headers)[0], 403)
            with self.connection("owner", autocommit=True) as c, db.change(
                    "system", "cli", "Remove fixture profile", conn=c) as (cur, _):
                cur.execute("delete from profile where id='user2'")
            # Config still lists user2; database membership is the final authority.
            code, _, result = self.request(viewer=None, headers=headers, path=ROUTE + "?space=user2&batch_id=" + bid)
            self.assertEqual(code, 403, result)
            self.assertNotIn("draft", result)
