"""Signals over a real disposable loopback server; synthetic records, no live database."""
import json
from unittest import mock

from decklab.lib import api, inventory, state
from decklab.lib.api import changes
from decklab.lib.api import product_tokens
from decklab.lib.inventory import ops_products, rules
from decklab.tests.test_api import _write
from decklab.tests.test_product_tokens import TOKEN_ROWS
from decklab.tests.test_server import ServerTestCase


class ChangeSignalHttpTests(ServerTestCase):
    def test_actual_nested_product_token_write_acknowledges_the_committed_snapshot(self):
        _write(self.box.magic / "tokens.csv", ",".join(rules.TOKEN_FIELDS) + "\n" + TOKEN_ROWS)
        snapshot = inventory.current()
        viewer = {"X-Deck-Lab-Viewer": "matt"}
        _, _, raw = self.request("GET", "/api/changes", headers=viewer)
        before = json.loads(raw)
        body = {"profile": "matt", "stem": "fdn-beginner-box", "expect": product_tokens.status_sha256(snapshot),
                "tokens_sha256": ops_products.token_sha256(snapshot), "cards": [{"row": 0, "quantity": 2}]}
        status, headers, raw = self.request("POST", "/api/product/token-cards", json.dumps(body).encode(), {
            **viewer, "X-Deck-Lab": "1", "Content-Type": "application/json"})
        self.assertEqual(status, 200, raw[:200])
        self.assertTrue(json.loads(raw)["saved"])
        self.assertEqual(headers.get(changes.WRITE_HEADER), "1")
        committed = json.loads(headers[changes.HEADER])
        self.assertNotEqual(committed["inventory"], before["inventory"])
        _, _, raw = self.request("GET", "/api/changes", headers=viewer)
        self.assertEqual(json.loads(raw), committed)

    def test_unnamed_requests_even_scripts_get_no_signal_and_no_inventory_read(self):
        with mock.patch.object(inventory.backend(), "load", side_effect=AssertionError("No unnamed read")):
            for script in (True, False):
                status, headers, body = self.request("GET", "/api/changes", script=script)
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body), {})
                self.assertIsNone(headers.get(changes.HEADER))

    def test_loaded_successful_reads_and_writes_carry_the_same_safe_baseline_without_body_changes(self):
        viewer = {"X-Deck-Lab-Viewer": "matt"}
        status, headers, body = self.request("GET", "/api/decks", headers=viewer)
        self.assertEqual(status, 200, body[:200])
        baseline = json.loads(headers[changes.HEADER])
        self.assertEqual(set(baseline), {"ready", "inventory", "decks", "library"})
        self.assertTrue(baseline["ready"])
        self.assertNotIn("matt", json.dumps(baseline))
        status, _, body = self.request("GET", "/api/changes", headers=viewer)
        self.assertEqual(json.loads(body), baseline)
        def saved(body):
            inventory.current()
            return {"saved": True}
        with mock.patch.object(api, "save_deck", side_effect=saved):
            status, headers, body = self.request("POST", "/api/deck/save", b"{}", {
                **viewer, "X-Deck-Lab": "1", "Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"saved": True})
        self.assertEqual(json.loads(headers[changes.HEADER]), baseline)
        self.assertIsNone(headers.get(changes.WRITE_HEADER), "a preview/draft/check is not proof of a saved inventory change")
        with mock.patch.object(api, "save_deck", side_effect=saved), mock.patch.object(inventory, "pinned_write", return_value=True):
            status, headers, _ = self.request("POST", "/api/deck/save", b"{}", {
                **viewer, "X-Deck-Lab": "1", "Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get(changes.WRITE_HEADER), "1")

    def test_unknown_freshness_is_explicit_and_noninventory_answers_or_known_failures_do_not_read_signal_sources(self):
        viewer = {"X-Deck-Lab-Viewer": "matt"}
        with mock.patch.object(self.box.state, "visibility", side_effect=state.Unavailable("PRIVATE_ERROR")):
            status, _, body = self.request("GET", "/api/changes", headers=viewer)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ready": False})
        with mock.patch.object(changes, "current", side_effect=AssertionError("No extra source read")):
            status, headers, _ = self.request("GET", "/api/profiles", headers=viewer)
            self.assertEqual(status, 200)
            self.assertIsNone(headers.get(changes.HEADER))
            with mock.patch.object(api, "decks_index", side_effect=api.ApiError(503, "Known setup guidance", reason="database")):
                status, headers, body = self.request("GET", "/api/decks", headers=viewer)
            self.assertEqual(status, 503)
            self.assertEqual(json.loads(body), {"error": "Known setup guidance", "reason": "database"})
            self.assertIsNone(headers.get(changes.HEADER))
