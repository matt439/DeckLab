"""Retirement routing and HTTP write guards over a temporary local server."""
import json
from unittest import mock

from decklab.lib.api import retirement
from decklab.lib.api.common import ApiError
from decklab.tests import test_server as support


class RetirementHttpTests(support.ServerTestCase):
    def setUp(self):
        self.answer = {"id": "casual/fixture", "title": "Fixture", "may_retire": True,
                       "sha256": "a" * 64, "revision": 7, "status": "idea", "why_not": None}
        self.mocks = {}
        for name in ("retirement_view", "retire_deck", "restore_deck"):
            patcher = mock.patch.object(retirement, name, return_value=self.answer)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)

    def test_get_and_head_read_retirement_metadata_without_mutating(self):
        path = "/api/deck/retire?id=casual%2Ffixture"
        self.assertEqual(self.get_json(path), self.answer)
        self.mocks["retirement_view"].assert_called_once_with(deck_id="casual/fixture")
        code, headers, body = self.request("HEAD", path)
        self.assertEqual((code, body), (200, b""))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertGreater(int(headers["Content-Length"]), 0)
        self.mocks["retire_deck"].assert_not_called()
        self.mocks["restore_deck"].assert_not_called()

    def test_both_posts_route_the_exact_guarded_request_body(self):
        requests = (("retire", {"profile": "matt", "id": "casual/fixture", "sha256": "a" * 64,
                                "revision": 7, "reason": "No longer in the plan."}),
                    ("restore", {"profile": "matt", "id": "casual/fixture", "retired_revision": 8}))
        for action, data in requests:
            with self.subTest(action=action):
                self.assertEqual(self.get_json(f"/api/deck/{action}", method="POST",
                                               body=json.dumps(data).encode()), self.answer)
                called = self.mocks[f"{action}_deck"]
                called.assert_called_once()
                self.assertEqual(json.loads(called.call_args.args[0]), data)
        self.mocks["retirement_view"].assert_not_called()

    def test_same_origin_write_headers_and_json_are_required_before_mutation(self):
        for action in ("retire", "restore"):
            for headers, status in (({}, 403), ({"Content-Type": "application/json"}, 403),
                                    ({"Content-Type": "text/plain", "X-Deck-Lab": "1"}, 415),
                                    (dict(support.WRITE, Origin="http://evil.example"), 403)):
                with self.subTest(action=action, headers=headers):
                    code, _, _ = self.request("POST", f"/api/deck/{action}", b"{}", headers)
                    self.assertEqual(code, status)
            self.mocks[f"{action}_deck"].assert_not_called()

    def test_queries_and_unsupported_methods_cannot_reach_mutators(self):
        for query in ("id=casual%2Ffixture&x=1", "id=casual%2Ffixture&id=casual%2Fother"):
            self.assertError("/api/deck/retire?" + query, 400)
        for action in ("retire", "restore"):
            self.assertError(f"/api/deck/{action}?id=casual%2Ffixture", 400, "POST", b"{}")
            for method in ("PUT", "DELETE"):
                code, _, _ = self.request(method, f"/api/deck/{action}", b"{}")
                self.assertEqual(code, 405)
            self.mocks[f"{action}_deck"].assert_not_called()
        self.assertError("/api/deck/restore", 405)
        self.mocks["retirement_view"].assert_not_called()

    def test_conflicts_and_database_failures_remain_explicit(self):
        for action in ("retire", "restore"):
            for status in (403, 409, 503):
                with self.subTest(action=action, status=status):
                    self.mocks[f"{action}_deck"].side_effect = ApiError(status, "Fixture refusal")
                    self.assertEqual(self.assertError(f"/api/deck/{action}", status, "POST", b"{}"),
                                     "Fixture refusal")
