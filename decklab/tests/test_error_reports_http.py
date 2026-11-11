"""Loopback-only diagnostic transport bounds, permissions and safe unexpected errors."""
from collections import deque
import json
from unittest import mock

from decklab.lib import api, error_references as refs, server_http
from decklab.tests.test_server import ServerTestCase, WRITE


class ErrorReportsHttpTests(ServerTestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(refs, "_received", deque()))
        self.enterContext(mock.patch.object(refs, "path", return_value=self.box.data / "diagnostics/error-references.json"))
        configured = json.loads((self.box.root / "config.json").read_text(encoding="utf-8"))
        for profile in configured["profiles"]:
            profile["role"] = "admin" if profile["id"] == "matt" else "member"
        (self.box.root / "config.json").write_text(json.dumps(configured), encoding="utf-8")
        refs.path().unlink(missing_ok=True)

    def test_anonymous_same_origin_metadata_exception_grants_no_other_write(self):
        body = json.dumps({"reference": "a" * 32, "page": "deck", "type": "TypeError"}).encode()
        status, _, _ = self.request("POST", "/api/errors/report", body, script=False)
        self.assertEqual(status, 200)
        self.assertEqual(set(refs.read()[0][0]), {"reference", "page", "type", "at"})
        foreign = {**WRITE, "Origin": "https://foreign.example.com"}
        self.assertEqual(self.request("POST", "/api/errors/report", body, foreign, script=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/errors/report", body, {}, script=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/errors/report", b"x" * 2049, script=False)[0], 413)
        self.assertEqual(self.request("POST", "/api/errors/report", json.dumps({"message": "PRIVATE"}).encode(), script=False)[0], 400)
        for headers in ({}, {"X-Deck-Lab-Viewer": "user1"}):
            self.assertEqual(self.request("GET", "/api/settings/errors", headers=headers, script=False)[0], 403)
        status, _, raw = self.request("GET", "/api/settings/errors", headers={"X-Deck-Lab-Viewer": "matt"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["events"][0]["reference"], "a" * 32)
        # The exception changes no inventory permission: an anonymous ordinary write remains refused.
        self.assertEqual(self.request("POST", "/api/deck/save", b"{}", script=False)[0], 403)

    def test_unexpected_failure_has_reference_and_known_operational_errors_keep_their_answers(self):
        with mock.patch.object(api, "decks_index", side_effect=RuntimeError("PRIVATE_MESSAGE")):
            status, _, raw = self.request("GET", "/api/decks")
        self.assertEqual(status, 500)
        answer = json.loads(raw)
        self.assertRegex(answer["reference"], r"^[0-9a-f]{32}$")
        self.assertIn(answer["reference"], answer["error"])
        self.assertNotIn("PRIVATE_MESSAGE", raw.decode())
        self.assertNotIn("PRIVATE_MESSAGE", json.dumps(refs.read()[0]))
        self.assertTrue(any(answer["reference"] in line and "PRIVATE_MESSAGE" in line for line in self.log))
        before = refs.read()[0]
        for code in (400, 403, 404, 409, 503):
            with mock.patch.object(api, "decks_index", side_effect=api.ApiError(code, "Known actionable reason", reason="database")):
                status, _, raw = self.request("GET", "/api/decks")
            self.assertEqual(status, code)
            self.assertEqual(json.loads(raw), {"error": "Known actionable reason", "reason": "database"})
        self.assertEqual(refs.read()[0], before)
