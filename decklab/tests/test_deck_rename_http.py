"""Rename routing uses the standard HTTP method, body and same-origin guards."""
import json
from unittest import mock

from decklab.lib.api import rename
from decklab.lib.api.common import ApiError
from decklab.tests import test_server as support


class RenameHttpTests(support.ServerTestCase):
    def setUp(self):
        self.answer = {"id": "casual/fixture", "title": "Fixture", "may_rename": True,
                       "sha256": "a" * 64, "revision": 7, "why_not": None}
        self.mocks = {}
        for name in ("rename_view", "preview_rename", "rename_deck"):
            patcher = mock.patch.object(rename, name, return_value=self.answer)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)

    def test_get_and_head_read_metadata_without_mutating(self):
        path = "/api/deck/rename?id=casual%2Ffixture"
        self.assertEqual(self.get_json(path), self.answer)
        self.mocks["rename_view"].assert_called_once_with(deck_id="casual/fixture")
        code, headers, body = self.request("HEAD", path)
        self.assertEqual((code, body), (200, b""))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.mocks["rename_deck"].assert_not_called()

    def test_preview_and_confirmation_receive_the_exact_guarded_body(self):
        data = {"profile": "matt", "id": "casual/fixture", "title": "Changed title", "sha256": "a" * 64,
                "revision": 7}
        for suffix, name in (("/preview", "preview_rename"), ("", "rename_deck")):
            self.assertEqual(self.get_json("/api/deck/rename" + suffix, method="POST",
                                           body=json.dumps(data).encode()), self.answer)
            self.assertEqual(json.loads(self.mocks[name].call_args.args[0]), data)

    def test_same_origin_json_and_supported_methods_are_required(self):
        for suffix, name in (("/preview", "preview_rename"), ("", "rename_deck")):
            for headers, status in (({}, 403), ({"Content-Type": "application/json"}, 403),
                                    ({"Content-Type": "text/plain", "X-Deck-Lab": "1"}, 415),
                                    (dict(support.WRITE, Origin="http://evil.example"), 403)):
                code, _, _ = self.request("POST", "/api/deck/rename" + suffix, b"{}", headers)
                self.assertEqual(code, status)
            self.assertError("/api/deck/rename" + suffix + "?id=casual%2Ffixture", 400, "POST", b"{}")
            for method in ("PUT", "DELETE"):
                code, _, _ = self.request(method, "/api/deck/rename" + suffix, b"{}")
                self.assertEqual(code, 405)
            self.mocks[name].assert_not_called()
        self.assertError("/api/deck/rename/preview", 405)
        for query in ("id=casual%2Ffixture&extra=1", "id=casual%2Ffixture&id=casual%2Fother"):
            self.assertError("/api/deck/rename?" + query, 400)

    def test_refusals_retain_status_and_canonical_recovery_link(self):
        for status in (403, 409, 503):
            self.mocks["rename_deck"].side_effect = ApiError(status, "Fixture refusal", canonical_id="casual/new")
            code, _, body = self.request("POST", "/api/deck/rename", b"{}", support.WRITE)
            self.assertEqual(code, status)
            self.assertEqual(json.loads(body)["canonical_id"], "casual/new")
