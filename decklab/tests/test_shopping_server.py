"""Shopping reads without the Scryfall card cache (its one write, a check marked done, is in
test_shopping_checks)."""
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import shopping
from decklab.lib.inventory.model import Inventory
from decklab.tests.test_server import ServerTestCase


class ShoppingServerTests(ServerTestCase):
    def test_get_head_and_offline(self):
        answer = {"to_buy": [], "orders": [], "checks": [], "warnings": []}
        with mock.patch.object(shopping.purchases, "overview", return_value=dict(answer)), self.box.no_index():
            # Records still show; the buying view explicitly explains unavailable counts.
            result = self.get_json("/api/shopping")
            self.assertEqual(result.pop("queue_decks"), [
                {"id": "casual/gruul-test", "title": "Gruul Test"},
                {"id": "commander/elf-commander", "title": "Elf Commander"}])
            missing = result.pop("missing_cards")
            self.assertFalse(missing["ready"])
            self.assertEqual(missing["rows"], [])
            self.assertTrue(any("card data" in item["message"] for item in missing["errors"]))
            self.assertEqual(result, {**answer, "decks_missing": [], "queue_revision": inventory.current().revision})
            self.assertEqual(self.request("HEAD", "/api/shopping")[2], b"")

    def test_query_and_mutation_methods_are_refused(self):
        self.assertError("/api/shopping?profile=user1", 400)
        for method in ("POST", "PUT", "DELETE", "OPTIONS"):
            self.assertError("/api/shopping", 405, method=method)
        # Its one write is a sub-route, and refuses reads.
        for method in ("GET", "HEAD", "PUT", "DELETE"):
            self.assertEqual(self.request(method, "/api/shopping/check")[0], 405)

    def test_malformed_and_unreadable_records_report_sanitized_errors(self):
        for error in (ValueError(r"Bad record C:\Users\private\orders.json"),
                      OSError(13, "Permission denied", r"C:\Users\private\orders.json")):
            with self.subTest(error=error), mock.patch.object(shopping.purchases, "overview", side_effect=error), \
                    mock.patch.object(shopping.common, "_log"):
                message = self.assertError("/api/shopping", 500)
                self.assertIn("shopping records couldn't be read", message)
                self.assertIn("orders.json", message)
                self.assertNotIn("private", message)

    def test_warning_paths_are_sanitized(self):
        answer = {"to_buy": [], "orders": [], "checks": [],
                  "warnings": [r"Check C:\Users\private\order.json"]}
        with mock.patch.object(shopping.purchases, "overview", return_value=answer):
            self.assertEqual(self.get_json("/api/shopping")["warnings"], ["Check order.json"])


class ShoppingAnswerTests(unittest.TestCase):
    """What the overview adds to purchases.overview(): deck links, pictures, decks still missing cards."""

    DECKS = [{"id": "commander/alela-faeries", "title": "Alela Faeries", "status": "idea", "versions": ["target"]},
             {"id": "casual/otters", "title": "Izzet Otters", "status": "building", "versions": ["target", "owned"]},
             {"id": "casual/gruul", "title": "Gruul", "status": "built", "versions": ["target"]},
             {"id": "casual/ideas", "title": "Ideas", "status": "idea", "versions": ["target"]}]

    def setUp(self):
        # Pure projections still resolve source aliases through the request's snapshot.
        self.enterContext(inventory.pinned(Inventory("shopping-answer-fixture")))

    def test_queued_cards_link_their_deck_by_source_or_title(self):
        queue = [{"name": "A", "source": "magic/decks/commander/alela-faeries.md", "for": "Something else"},
                 {"name": "B", "source": "magic/buylists/x.md", "for": "izzet otters"},
                 {"name": "C", "source": "magic/people/user2/decks/casual/otters.md", "for": ""},
                 {"name": "D", "source": "", "for": "A deck that isn't there"}]
        shopping._link_decks(queue, self.DECKS)
        self.assertEqual([row["deck"] for row in queue], [
            {"id": "commander/alela-faeries", "title": "Alela Faeries"},
            {"id": "casual/otters", "title": "Izzet Otters"}, None, None])

    def test_pictures_only_for_orders_on_the_way_from_their_own_rows(self):
        answer = {"to_buy": [{"name": "Q", "set": "fdn", "collector_number": "1"}], "orders": [
            {"id": "on-the-way", "components": [
                {"id": "cards", "kind": "cards", "status": "pending", "path": "p.csv",
                 "items": [{"name": "A", "quantity": 1}, {"name": "B", "quantity": 2}]},
                {"id": "tokens", "kind": "tokens", "status": "received", "path": "t.csv",
                 "items": [{"name": "Rabbit // Rabbit", "quantity": 1}]}]},
            {"id": "old", "components": [{"id": "cards", "kind": "cards", "status": "received", "path": "o.csv",
                                          "items": [{"name": "Z", "quantity": 1}]}]}]}
        rows = {"p.csv": [{"name": "A", "set": "fdn", "collector_number": "5", "finish": "foil"},
                          {"name": "B", "set": "", "collector_number": "", "finish": "nonfoil"}],
                "t.csv": [{"front": "Rabbit", "back": "Rabbit", "set": "tblb", "front_collector_number": "8"}]}
        with mock.patch.object(shopping.purchases, "_csv", lambda path, required: rows[path]),                 mock.patch.object(shopping, "_card_for",
                                  lambda name, s="", n="", cache=None: {"name": name, "at": (s, n)}),                 mock.patch.object(shopping, "_token_for", lambda row: {"name": row["front"]}):
            shopping._add_pictures(answer)
        cards, tokens = answer["orders"][0]["components"]
        self.assertEqual(cards["items"][0], {"name": "A", "quantity": 1, "set": "fdn", "collector_number": "5",
                                             "finish": "foil", "card": {"name": "A", "at": ("fdn", "5")}})
        self.assertEqual(cards["items"][1]["card"], {"name": "B", "at": ("", "")})
        self.assertEqual(tokens["items"][0]["card"], {"name": "Rabbit"})
        self.assertNotIn("card", answer["orders"][1]["components"][0]["items"][0])
        self.assertEqual(answer["to_buy"][0]["card"], {"name": "Q", "at": ("fdn", "1")})

    def test_current_gather_retains_legacy_deck_order_and_omits_complete_decks(self):
        missing = {"commander/alela-faeries": 62, "casual/otters": 4, "casual/gruul": 0, "casual/ideas": 8}

        def owned(deck_id, version, pool=None, prices=True):
            self.assertEqual((version, prices), ("target", False))
            quantity = missing[deck_id]
            return {"rows": [{"name": "Shared card", "missing": quantity, "need": quantity,
                              "owned": 0, "on_the_way": 0, "on_the_way_from": [], "in_use_elsewhere": []}]}
        supply = mock.Mock(warnings=[], unresolved={})
        with mock.patch.object(shopping.shopping_missing.pool, "load_pool", return_value=supply), \
                mock.patch.object(shopping.shopping_missing.pool, "owned_vs_needed", owned), \
                mock.patch.object(shopping.shopping_missing, "_canonical", side_effect=lambda name: name):
            gathered, found = shopping.shopping_missing.gather(self.DECKS, [], lambda name: None)
        self.assertEqual([(d["id"], d["missing"]) for d in found],
                         [("casual/otters", 4), ("casual/ideas", 8), ("commander/alela-faeries", 62)])
        self.assertTrue(gathered["ready"])
        self.assertEqual(gathered["totals"], {"cards": 1, "copies": 74})
        self.assertNotIn("casual/gruul", [deck["id"] for deck in gathered["rows"][0]["decks"]])
