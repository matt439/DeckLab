"""New feature routes through real loopback HTTP, over a temporary repository.

Mutation handlers are mocked: even valid receipt/game requests never touch user
data. Collection and assembly reads use the sandbox's real inventory and cards.
"""
from contextlib import ExitStack
import json
from unittest import mock

from decklab.lib import config, pool
from decklab.lib.api import (accessories, activity, assembly, assembly_completion, assembly_ticks, collection, cover, editor, history, play_records,
                             receipts, shopping, shopping_order_changes, shopping_orders, shopping_queue, tokens)
from decklab.tests.test_server import ServerTestCase, WRITE


GETS = (
    ("/api/collection", collection, "collection_view", "q=elves&color=G&limit=3", {"q": "elves", "color": "G", "limit": "3"}),
    ("/api/assembly", assembly, "assembly_view", "deck=casual%2Fgruul-test&version=owned",
     {"deck": "casual/gruul-test", "version": "owned"}),
    ("/api/play", play_records, "play_overview", "id=casual%2Fgruul-test", {"deck_id": "casual/gruul-test"}),
    ("/api/deck/history", history, "deck_history", "id=casual%2Fgruul-test", {"deck_id": "casual/gruul-test"}),
    ("/api/deck/revision", history, "deck_revision", "id=casual%2Fgruul-test&version=owned&revision=" + "a" * 40,
     {"deck_id": "casual/gruul-test", "version": "owned", "revision": "a" * 40}),
    # Two deck reads with near names: the picture picker's cards and the editor's card finder.
    ("/api/deck/cards", cover, "cover_cards", "id=casual%2Fgruul-test", {"deck_id": "casual/gruul-test"}),
    ("/api/deck/find", editor, "find_cards", "q=bolt&scope=all", {"q": "bolt", "scope": "all", "deck_id": None}),
    ("/api/receipt", receipts, "receipt_view", "order=fixture-order", {"order": "fixture-order"}),
    ("/api/accessories", accessories, "accessories_view", "", {}),
    ("/api/tokens", tokens, "tokens_view", "", {}),
    ("/api/activity", activity, "activity_view", "before=10&limit=50&kind=decks&actor=matt",
     {"before": "10", "limit": "50", "kind": "decks", "actor": "matt"}),
)
POSTS = (
    ("/api/assembly/preview", assembly, "assembly_preview"),
    ("/api/assembly/built", assembly_completion, "mark_built"),
    ("/api/assembly/ticks", assembly_ticks, "packing_ticks"),
    ("/api/play/game", play_records, "save_game"),
    ("/api/play/sideboard", play_records, "save_sideboard"),
    ("/api/receipt/preview", receipts, "preview_receipt"),
    ("/api/receipt/apply", receipts, "apply_receipt"),
    ("/api/shopping/check", shopping, "resolve_check"),
    ("/api/shopping/queue", shopping_queue, "save_queue_state"),
    ("/api/shopping/order/preview", shopping_orders, "preview_order"),
    ("/api/shopping/order/apply", shopping_orders, "apply_order"),
    ("/api/shopping/order/change/preview", shopping_order_changes, "preview_order_change"),
    ("/api/shopping/order/change/apply", shopping_order_changes, "apply_order_change"),
    ("/api/accessories/fetch", accessories, "fetch_picture"),
    ("/api/accessories/save", accessories, "save_accessory"),
    ("/api/accessories/assign", accessories, "assign_accessory"),
    ("/api/tokens/save", tokens, "save_token"),
)


class FeatureRouteTests(ServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.paths = ExitStack()
        for module in (config, pool):
            cls.paths.enter_context(mock.patch.object(module, "REPO", cls.box.root))
        cls.paths.enter_context(mock.patch.object(config, "MAGIC", cls.box.magic))
        cls.paths.enter_context(mock.patch.object(config, "DATA", cls.box.data))

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            cls.paths.close()

    def test_get_and_head_dispatch_expected_arguments(self):
        for path, module, name, query, expected in GETS:
            with self.subTest(path=path), mock.patch.object(module, name, return_value={"route": path}) as handler:
                self.assertEqual(self.get_json(path + "?" + query), {"route": path})
                handler.assert_called_once_with(**expected)
                handler.reset_mock()
                code, headers, body = self.request("HEAD", path + "?" + query)
                self.assertEqual((code, body), (200, b""))
                self.assertGreater(int(headers["Content-Length"]), 0)
                handler.assert_called_once_with(**expected)

    def test_post_dispatch_preserves_browser_profile_envelope(self):
        body = b'{"profile":"matt","fixture":"read-only test"}'
        for path, module, name in POSTS:
            with self.subTest(path=path), mock.patch.object(module, name, return_value={"route": path}) as handler:
                result = self.get_json(path, method="POST", body=body,
                                       headers=dict(WRITE, Origin=f"http://127.0.0.1:{self.port}"))
                self.assertEqual(result, {"route": path})
                handler.assert_called_once_with(body)

    def test_read_routes_reject_mutation_methods_unknown_and_duplicate_queries(self):
        for path, module, name, query, expected in GETS:
            with self.subTest(path=path), mock.patch.object(module, name) as handler:
                self.assertError(path + "?unrecognised=yes", 400)
                for parameter in list(expected)[:1]:        # a route with no parameters has none to repeat
                    parameter = "id" if parameter == "deck_id" else parameter
                    self.assertError(path + f"?{parameter}=one&{parameter}=two", 400)
                for method in ("POST", "PUT", "DELETE", "OPTIONS"):
                    self.assertError(path + "?" + query, 405, method=method, body=b"{}" if method == "POST" else None)
                handler.assert_not_called()

    def test_write_routes_reject_reads_queries_and_preflight(self):
        for path, module, name in POSTS:
            with self.subTest(path=path), mock.patch.object(module, name) as handler:
                for method in ("GET", "HEAD", "PUT", "DELETE", "OPTIONS"):
                    code, headers, body = self.request(method, path)
                    self.assertEqual(code, 405)
                    self.assertFalse([key for key in headers if key.lower().startswith("access-control-")])
                self.assertError(path + "?profile=matt", 400, method="POST", body=b"{}")
                handler.assert_not_called()

    def test_every_post_uses_same_origin_custom_header_and_json_guards(self):
        own = f"http://127.0.0.1:{self.port}"
        refused = (
            ({"Content-Type": "application/json"}, 403),
            ({"X-Deck-Lab": "1"}, 415),
            (dict(WRITE, Origin="http://untrusted.example"), 403),
            (dict(WRITE, Origin="null"), 403),
            (dict(WRITE, Origin=f"http://127.0.0.1:{self.port + 1}"), 403),
            ({**WRITE, "Origin": own, "Sec-Fetch-Site": "cross-site"}, 403),
        )
        for path, module, name in POSTS:
            with self.subTest(path=path), mock.patch.object(module, name) as handler:
                for headers, status in refused:
                    self.assertError(path, status, method="POST", body=b"{}", headers=headers)
                handler.assert_not_called()

    def test_the_git_commit_retries_are_gone(self):
        # Phase 4: the inventory is the database's, so nothing is left to commit or retry.
        for path in ("/api/tokens/commit", "/api/collection/commit", "/api/accessories/commit"):
            with self.subTest(path=path):
                self.assertError(path, 404, method="POST", body=b'{"profile":"matt"}',
                                 headers=dict(WRITE, Origin=f"http://127.0.0.1:{self.port}"))

    def test_id_routes_normalize_pairing_plus_but_refuse_traversal(self):
        with mock.patch.object(play_records, "play_overview", return_value={}) as handler:
            self.get_json("/api/play?id=pairing/cats+elves")
            handler.assert_called_once_with(deck_id="pairing/cats+elves")
        for path in ("/api/play", "/api/deck/history", "/api/deck/revision"):
            self.assertError(path + "?id=casual%2F..%2Foutside", 400)

    def test_real_collection_and_assembly_reads_only_the_sandbox(self):
        before = {path.relative_to(self.box.magic).as_posix(): path.read_bytes()
                  for path in self.box.magic.rglob("*") if path.is_file()}
        found = self.get_json("/api/collection?q=Llanowar%20Elves&availability=all")
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["cards"][0]["name"], "Llanowar Elves")
        self.assertEqual(found["cards"][0]["owned"], 5)
        plan = self.get_json("/api/assembly?deck=casual%2Fgruul-test&version=owned")
        self.assertEqual(plan["decks"][0]["id"], "casual/gruul-test")
        self.assertEqual(plan["decks"][0]["version"], "owned")
        self.assertEqual(plan["totals"]["need"], 4)
        body = json.dumps({"profile": "matt", "decks": [{"id": "casual/gruul-test", "version": "owned"}]}).encode()
        preview = self.get_json("/api/assembly/preview", method="POST", body=body)
        self.assertEqual(plan["usual_opponents"], {})
        self.assertEqual(preview, {key: value for key, value in plan.items() if key not in ("choices", "usual_opponents")})
        after = {path.relative_to(self.box.magic).as_posix(): path.read_bytes()
                 for path in self.box.magic.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        self.assertEqual(self.box.state.play_list("games"), [])
        self.assertEqual(self.box.state.changes(), [])
