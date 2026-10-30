"""The Receipts page's API and `python -m decklab.db receive`, over disposable temp folders
with the files backend, and over a throwaway database: the receipt and the deck
tables it refreshes are one change (the receipt kind is registered with refresh=True), and the
preview lists the deck files from the same in-change plan."""
import contextlib
import hashlib
import io
import json
import unittest
from unittest import mock

from decklab.lib import cards, config, inventory, pool
from decklab.lib.api import receipts
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, receive, refresh, rules
from decklab.lib.inventory.files import FileInventory
from decklab.tests import db_support, test_pool as base
from decklab.tests import test_receive_order as support

setUpModule = support.setUpModule
tearDownModule = support.tearDownModule


class FilesReceiptCase(base.PoolTestCase):
    """support.receipt_tree's order, deck and buylist in a temp folder, the files backend over it,
    and Deck Lab's records pointed at it."""

    def setUp(self):
        super().setUp()
        self.root = self.magic.parent
        support.receipt_tree(self)
        index = self.root / "fixture-index.json.gz"
        cards.write_index(cards._get().data, index)
        for module, key, value in ((config, "REPO", self.root), (config, "DATA", self.root / "decklab/data"),
                                   (cards, "INDEX_FILE", index),
                                   (receipts, "_receipt_today", lambda: "2026-10-08"),
                                   # An admin (receipts are an admin's, by role on the home network too).
                                   (receipts, "_writer", lambda data: {"id": data.get("profile"), "name": "Tester",
                                                                       "role": "admin"})):
            patcher = mock.patch.object(module, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.inventory = FileInventory(self.root)
        self.addCleanup(inventory.use(self.inventory))


class WebReceiptTests(FilesReceiptCase):

    def request_data(self, component_ids=("cards",), **overrides):
        view = receipts.receipt_view("test")
        chosen = []
        for item in view["components"]:
            if item["id"] in component_ids:
                made = {"id": item["id"], "verified": True}
                if item["kind"] == "product":
                    made["intact"] = "no"
                else:
                    made["rows"] = item["rows"]
                chosen.append(made)
        return {"profile": "matt", "order": "test", "fingerprint": view["fingerprint"],
                "received_on": "2026-10-08", "components": chosen, **overrides}

    def prepare(self, data=None):
        return receipts.preview_receipt(json.dumps(data or self.request_data()))

    def record_web(self, result, profile="matt"):
        return receipts.apply_receipt(json.dumps({"profile": profile, "preview": result["preview"]}))

    def owned(self, name):
        return sum(int(r["quantity"]) for r in support.cards_in(self.magic / "collection.csv", existing=True)
                   if r["name"] == name)

    def test_the_view_shows_the_delivery_with_the_revisions_fingerprint(self):
        view = receipts.receipt_view("test")
        self.assertEqual(view["fingerprint"], hashlib.sha256(self.inventory.revision().encode()).hexdigest())
        self.assertNotIn("pending_commit", view)
        self.assertEqual([c["id"] for c in view["components"]], ["cards", "tokens", "kit"])
        self.assertEqual(view["components"][2]["rows"], [])
        with self.assertRaises(ApiError) as caught:
            receipts.receipt_view()
        self.assertEqual(caught.exception.status, 400)
        self.write("orders/test.csv", "name,quantity\nLlanowar Elves,2\n")
        with self.assertRaises(ApiError) as caught:
            receipts.receipt_view("test")
        self.assertEqual(caught.exception.status, 409)

    def test_the_view_brings_the_boards_pictures_decks_items_and_today(self):
        view = receipts.receipt_view("test")
        self.assertEqual(view["today"], "2026-10-08")
        cards_part, tokens_part, kit = view["components"]
        # Pictures and decks are aligned with the rows but never inside them: the rows go back as they are.
        self.assertEqual(set(cards_part["rows"][0]), set(cards_part["fields"]))
        self.assertEqual(len(cards_part["pictures"]), len(cards_part["rows"]))
        picture = cards_part["pictures"][0]
        self.assertTrue(picture["exact"])
        self.assertIsNone(picture["why"])
        self.assertEqual(picture["card"]["name"], "Llanowar Elves")
        self.assertEqual(picture["card"]["img_small"], "/img/fdn/227/small")
        self.assertIn("nonfoil", picture["finishes"])
        # The deck that counts on these two copies from this order.
        self.assertEqual(cards_part["decks"], [[{"id": "casual/test", "title": "Test", "status": "idea", "uses": 2,
                                                "waiting": 2, "colors": ["G"]}]])
        self.assertEqual(view["kits"], {})
        self.assertEqual(len(tokens_part["pictures"]), 1)
        self.assertIsNone(tokens_part["decks"])
        self.assertTrue(view["face_names"])
        # A product's card list, with its pictures and decks aligned with it.
        self.assertEqual([item["name"] for item in kit["items"]], ["Pick Your Poison", "Forest"])
        self.assertEqual(kit["items"][0]["quantity"], "1")
        self.assertEqual(len(kit["pictures"]), 2)
        self.assertIsNone(kit["pictures"][1])           # Forest isn't in the fixture's card data: a text tile
        self.assertEqual(kit["decks"][0], [])
        self.assertIsNone(kit["decks"][1])              # Forest's logical name isn't in this fixture index

    def test_unresolved_names_have_no_destination_confidence_without_changing_known_rows(self):
        from decklab.lib import decks
        self.cards_csv("orders/test.csv", ("Unknown fixture card", "tst", "1", "nonfoil", 2),
                       ("Pick Your Poison", "mkm", "170", "nonfoil", 1),
                       ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        before = files.tree_files(self.root)
        canonical = receive.delivery(inventory.current(), "test")["components"][0]["rows"]
        revision = self.inventory.revision()
        with mock.patch.object(decks, "list_decks", wraps=decks.list_decks) as listed, \
                mock.patch.object(pool, "load_pool", wraps=pool.load_pool) as loaded:
            view = receipts.receipt_view("test")
        part = view["components"][0]
        self.assertEqual(part["rows"], canonical)
        self.assertEqual([set(row) for row in part["rows"]], [set(part["fields"])] * 3)
        self.assertEqual([row["quantity"] for row in part["rows"]], ["2", "1", "2"])
        self.assertIsNone(part["decks"][0])
        self.assertEqual(part["decks"][1], [])
        self.assertEqual(part["decks"][2], [{"id": "casual/test", "title": "Test", "status": "idea",
                                              "uses": 2, "waiting": 2, "colors": ["G"]}])
        self.assertIsNone(part["pictures"][0])
        self.assertEqual(view["fingerprint"], receipts.fingerprint(revision))
        self.assertEqual(files.tree_files(self.root), before)
        self.assertEqual(listed.call_count, 2)           # the summaries and the one shared pool's deck scan
        loaded.assert_called_once_with()

    def test_known_cards_keep_destination_confidence_when_their_pictures_are_unavailable(self):
        self.cards_csv("orders/test.csv", ("Pick Your Poison", "mkm", "9999", "nonfoil", 1),
                       ("Llanowar Elves", "fdn", "9999", "nonfoil", 2))
        with mock.patch.object(receipts, "_pictures", side_effect=lambda kind, rows: [None] * len(rows)):
            part = receipts.receipt_view("test")["components"][0]
        self.assertEqual(part["pictures"], [None, None])
        self.assertEqual(part["decks"][0], [])
        self.assertEqual(part["decks"][1], [{"id": "casual/test", "title": "Test", "status": "idea",
                                              "uses": 2, "waiting": 2, "colors": ["G"]}])

    def test_all_unresolved_card_and_product_names_need_no_deck_or_pool_lookup(self):
        from decklab.lib import decks
        from decklab.lib.api import common
        self.cards_csv("orders/test.csv", ("Unknown fixture card", "tst", "1", "nonfoil", 2))
        self.cards_csv("products/kit.csv", ("Unknown fixture product card", "tst", "2", "nonfoil", 3))
        with mock.patch.object(decks, "list_decks") as listed, \
                mock.patch.object(pool, "load_pool") as loaded, \
                mock.patch.object(common, "_log") as logged:
            view = receipts.receipt_view("test")
        cards_part, tokens_part, product = view["components"]
        self.assertEqual(cards_part["decks"], [None])
        self.assertEqual(product["decks"], [None])
        self.assertEqual(cards_part["rows"][0]["quantity"], "2")
        self.assertEqual(product["items"][0]["quantity"], "3")
        self.assertIsNone(tokens_part["decks"])
        self.assertEqual(view["kits"], {})
        listed.assert_not_called()
        loaded.assert_not_called()
        logged.assert_not_called()

    def test_a_printing_the_card_data_lacks_gets_the_usual_picture_and_says_why(self):
        self.cards_csv("orders/test.csv", ("Llanowar Elves", "fdn", "9999", "nonfoil", 2))
        picture = receipts.receipt_view("test")["components"][0]["pictures"][0]
        self.assertFalse(picture["exact"])
        self.assertEqual(picture["why"], "not in card data")
        self.assertEqual(picture["finishes"], [])
        self.assertEqual(picture["card"]["name"], "Llanowar Elves")
        hints = receipts.receipt_view("test")["components"][0]["decks"][0]
        self.assertEqual([(deck["id"], deck["waiting"]) for deck in hints], [("casual/test", 2)])

    def test_without_the_card_data_the_view_still_shows_with_no_pictures(self):
        with mock.patch.object(receipts, "_index_info", return_value=(None, "no card data")):
            view = receipts.receipt_view("test")
        self.assertTrue(all(c["pictures"] is None and c["decks"] is None for c in view["components"]))
        self.assertEqual(view["face_names"], [])
        self.assertEqual(view["components"][0]["rows"][0]["name"], "Llanowar Elves")

    def test_the_decks_failing_leaves_the_board_working(self):
        from decklab.lib import decks
        from decklab.lib.api import common
        with mock.patch.object(decks, "list_decks", side_effect=RuntimeError("Fixture failure")), \
                mock.patch.object(common, "_log") as logged:
            view = receipts.receipt_view("test")
        self.assertIsNone(view["components"][0]["decks"])
        self.assertTrue(view["components"][0]["pictures"])
        self.assertIn("Fixture failure", logged.call_args[0][0])

    def test_sleeves_show_only_for_built_decks_whose_kit_the_viewer_sees(self):
        from decklab.lib.api import deck_page, guard
        self.deck("test", "Test", "built", "Deck\n2 Llanowar Elves (FDN) 227\n58 Forest\n",
                  table="| Llanowar Elves | 2 | 0 | **2** | | | |\n| **Total** | | | **2** | | | |\n")
        kit = {"sleeves": {"name": "Black matte", "image_url": None, "state": "ok"}, "deck_box": None, "short": 0}
        kits = mock.patch.object(deck_page, "_index_kits", return_value=lambda summary: kit)
        with mock.patch.object(guard, "accessory_readers", return_value=None), \
                mock.patch.object(guard, "sees_kit", return_value=True), kits:
            self.assertEqual(receipts.receipt_view("test")["kits"], {"casual/test": {"sleeves": "Black matte"}})
        with mock.patch.object(guard, "accessory_readers", return_value=None), \
                mock.patch.object(guard, "sees_kit", return_value=False), kits:
            self.assertEqual(receipts.receipt_view("test")["kits"], {})
        # A viewer with no readable accessories never gets a sleeve or triggers a kit lookup.
        with mock.patch.object(guard, "accessory_readers", return_value=frozenset()), kits as indexed:
            self.assertEqual(receipts.receipt_view("test")["kits"], {})
            indexed.assert_not_called()

    def test_the_view_is_home_records_only(self):
        from decklab.lib.api import guard
        with mock.patch.object(guard, "sees_home_records", return_value=False), \
                mock.patch.object(inventory, "current") as loaded:     # E10-S29, before any source read
            with self.assertRaises(ApiError) as caught:
                receipts.receipt_view("test")
        self.assertEqual(caught.exception.status, 403)
        loaded.assert_not_called()

    def test_a_preview_writes_nothing_then_the_receipt_and_the_tables_follow(self):
        before = files.tree_files(self.root)
        preview = self.prepare()
        self.assertTrue(preview["ready"])
        self.assertEqual(files.tree_files(self.root), before)
        self.assertFalse((self.root / "decklab/data/receipts").exists())
        # The parts it changes in plain words, not the old files' paths: the order once, for its
        # record and its cards alike.
        self.assertEqual(preview["changes"], ["Home's collection", "Order test", "Deck Test (casual/test)"])
        result = self.record_web(preview)
        self.assertTrue(result["received"])
        self.assertNotIn("commit", result)
        self.assertEqual(result["totals"][0][0], "playable cards")
        self.assertEqual(result["tables"], {"written": [{"id": "casual/test", "title": "Test"}], "skipped": [],
                                            "error": None})
        # One change: the receipt and the deck table it refreshed.
        self.assertEqual(self.owned("Llanowar Elves"), 2)
        deck = (self.magic / "decks/casual/test.md").read_text(encoding="utf-8")
        self.assertIn("keep hand note", deck)
        self.assertNotIn("on the way (order test)", deck)

    def test_apply_says_how_ready_each_refreshed_deck_is_after_the_receipt(self):
        # E6-S26: the refreshed tables' Planned counts in the saved snapshot.
        self.deck("short", "Short", "building", "Deck\n2 Llanowar Elves (FDN) 227\n3 Elvish Mystic (CMM) 648\n55 Forest\n",
                  table="| Elvish Mystic | 3 | 1 | **2** | | | |\n| Llanowar Elves | 2 | 0 | **2** | | | |\n"
                        "| **Total** | | | **4** | | | |\n")
        result = self.record_web(self.prepare())
        self.assertEqual({d["id"] for d in result["tables"]["written"]}, {"casual/test", "casual/short"})
        readiness = result["readiness"]
        # Neither deck is built, so neither holds copies: both count the two Elves just received.
        self.assertEqual(readiness["casual/test"], {"missing": 0, "coming": 0})
        self.assertEqual(readiness["casual/short"], {"missing": 2, "coming": 0})

    def test_readiness_counts_the_copies_still_on_the_way_in_a_part_not_received(self):
        # Only the cards arrive: the ordered product, with its Pick Your Poison, is still on the way.
        self.deck("short", "Short", "building",
                  "Deck\n2 Llanowar Elves (FDN) 227\n1 Pick Your Poison (MKM) 170\n3 Elvish Mystic (CMM) 648\n"
                  "54 Forest\n",
                  table="| Elvish Mystic | 3 | 1 | **2** | | | |\n| Llanowar Elves | 2 | 0 | **2** | | | |\n"
                        "| Pick Your Poison | 1 | 0 | **1** | | | |\n| **Total** | | | **5** | | | |\n")
        result = self.record_web(self.prepare())
        self.assertIn("casual/short", {d["id"] for d in result["tables"]["written"]})
        found = pool.owned_vs_needed("casual/short", "target", prices=False)
        labelled = sum(qty for r in found["rows"] for _, qty in pool.row_labels(r)["on_the_way"])
        self.assertEqual(labelled, 1)
        # Missing leaves out the copy on the way: the two Mystics still to get, and the one coming.
        self.assertEqual(result["readiness"]["casual/short"], {"missing": 2, "coming": labelled})

    def test_readiness_is_only_for_viewers_who_see_homes_inventory_and_the_deck(self):
        from decklab.lib.api import guard
        preview = self.prepare()
        with mock.patch.object(guard, "sees_inventory", return_value=False) as sees, \
                mock.patch.object(receipts.guard, "deck_reader") as reader:
            result = self.record_web(preview)
        self.assertTrue(result["received"])
        self.assertEqual(result["readiness"], {})
        self.assertEqual(sees.call_args.args[0], "home")
        reader.assert_not_called()          # refused before any deck or pool is read

    def test_a_hidden_deck_or_a_failure_leaves_readiness_out_and_the_receipt_saved(self):
        from decklab.lib.api import guard
        with mock.patch.object(guard, "deck_reader", return_value=lambda target: False):
            self.assertEqual(self.record_web(self.prepare())["readiness"], {})
        self.assertEqual(self.owned("Llanowar Elves"), 2)
        tables = {"written": [{"id": "casual/test", "title": "Test"}, {"id": "product/kit"}, "bad"],
                  "skipped": [], "error": None}
        profile = {"id": "matt", "name": "Tester", "role": "admin"}
        with mock.patch.object(pool, "load_pool", side_effect=RuntimeError("fixture")), \
                mock.patch.object(receipts.common, "_log"):
            self.assertEqual(receipts._readiness(inventory.current(), tables, profile), {})
        self.assertEqual(list(receipts._readiness(inventory.current(), tables, profile)), ["casual/test"])

    def test_the_preview_names_the_deck_files_its_receipt_changes(self):
        preview = self.prepare()
        self.assertIn("Deck Test (casual/test)", preview["changes"])
        self.assertEqual(preview["tables"], {"written": [{"id": "casual/test", "title": "Test"}], "skipped": [],
                                             "error": None})

    def test_the_preview_and_the_receipt_plan_the_tables_once_each_inside_the_change(self):
        real, calls = refresh.plan_texts, []

        def plan(only=None):
            calls.append(inventory.current().revision)
            return real(only)
        with mock.patch.object(refresh, "plan_texts", plan):
            self.record_web(self.prepare())
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(revision.endswith(inventory.PREVIEW) for revision in calls))

    def test_the_inventory_apply_holds_the_deck_save_lock_with_the_files_backend(self):
        from decklab.lib.api import saving
        seen, real = [], inventory.apply

        def apply(*args, **kwargs):
            seen.append(saving._save_lock.locked())
            return real(*args, **kwargs)
        with mock.patch.object(inventory, "apply", apply):
            self.record_web(self.prepare())
        self.assertEqual(seen, [True])

    def test_a_refresh_that_fails_at_apply_leaves_the_receipt_saved_and_the_decks_alone(self):
        deck = (self.magic / "decks/casual/test.md").read_bytes()
        preview = self.prepare()
        with mock.patch.object(refresh, "plan_texts", side_effect=ValueError("Fixture plan failure")):
            result = self.record_web(preview)
        self.assertTrue(result["received"])
        self.assertEqual(result["tables"], {"written": [], "skipped": [], "error": "Fixture plan failure"})
        self.assertEqual((self.magic / "decks/casual/test.md").read_bytes(), deck)
        self.assertEqual(self.owned("Llanowar Elves"), 2)
        self.assertEqual([s["id"] for s in pool.stale_tables()], ["casual/test"])

    def test_a_stale_form_and_a_stale_preview_are_refused(self):
        data = self.request_data()
        self.cards_csv("collection.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 2))
        with self.assertRaises(ApiError) as caught:
            self.prepare(data)
        self.assertEqual(caught.exception.status, 409)
        preview = self.prepare()
        self.cards_csv("collection.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 3))
        with self.assertRaises(ApiError) as caught:
            self.record_web(preview)
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("changed since this preview", str(caught.exception))
        self.assertEqual(self.owned("Llanowar Elves"), 0)

    def test_an_edited_condition_is_kept_and_never_assumed(self):
        data = self.request_data()
        data["components"][0]["rows"][0]["condition"] = ""
        self.record_web(self.prepare(data))
        row = next(r for r in support.cards_in(self.magic / "collection.csv", existing=True)
                   if r["name"] == "Llanowar Elves")
        self.assertEqual(row["condition"], "")

    def test_a_wrong_printing_or_a_changed_quantity_or_name_is_a_client_error(self):
        for field, value in (("collector_number", "99999"), ("quantity", "1"), ("name", "Elvish Mystic")):
            data = self.request_data()
            data["components"][0]["rows"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ApiError) as caught:
                self.prepare(data)
            self.assertEqual(caught.exception.status, 400)
        self.assertEqual(self.owned("Llanowar Elves"), 0)

    def test_components_arrive_separately(self):
        self.record_web(self.prepare())
        record = json.loads((self.magic / "orders/records/test.json").read_bytes())
        self.assertEqual([item["status"] for item in record["components"]], ["received", "pending", "pending"])
        self.record_web(self.prepare(self.request_data(("tokens",))))
        self.assertEqual(sum(r.qty for r in inventory.current().token_set().rows), 2)
        record = json.loads((self.magic / "orders/records/test.json").read_bytes())
        self.assertEqual(record["components"][1]["verified_checks"], ["Check physical pairs"])

    def test_an_unverified_or_unresolved_token_reverse_is_refused(self):
        support.write_tokens(self, "orders/tokens/test.csv", back="", back_collector_number="", back_details="",
                             notes="reverse face unconfirmed")
        data = self.request_data(("tokens",))
        with self.assertRaises(ApiError) as caught:
            self.prepare(data)
        self.assertEqual(caught.exception.status, 400)
        data["components"][0]["rows"][0]["notes"] = "single-sided verified"
        data["components"][0]["verified"] = False
        blocked = self.prepare(data)
        self.assertEqual((blocked["ready"], blocked["blockers"]),
                         (False, ["tokens: inspect it, record the actual received facts, then confirm you did"]))
        data["components"][0]["verified"] = True
        self.assertTrue(self.prepare(data)["ready"])

    def test_a_preview_is_used_once_by_the_profile_that_made_it(self):
        preview = self.prepare()
        with self.assertRaises(ApiError) as caught:
            self.record_web(preview, "user1")
        self.assertEqual(caught.exception.status, 409)
        self.record_web(preview)
        with self.assertRaises(ApiError):
            self.record_web(preview)
        for token in ("0", "z" * 32):
            with self.subTest(token=token), self.assertRaises(ApiError) as caught:
                self.record_web({"preview": token})
            self.assertEqual(caught.exception.status, 400)

    def test_products_have_their_own_intact_choices_and_keep_their_token_checks(self):
        self.product("product-two.csv", ("Deck", "Llanowar Elves", 1), column="section")
        record = json.loads((self.magic / "orders/records/test.json").read_bytes())
        record["components"].append({"id": "two", "kind": "product", "path": "magic/products/product-two.csv",
                                     "status": "pending", "received_on": "", "checks": ["Inspect the token pairs"]})
        (self.magic / "orders/records/test.json").write_bytes(rules.json_bytes(record))
        self.write("products/status.csv", "file,status,intact,sleeves,deck_box,notes\n"
                                          "kit.csv,ordered,,,,\nproduct-two.csv,preordered,,,,\n")
        data = self.request_data()
        data["components"] = [{"id": "kit", "verified": False}, {"id": "two", "verified": False, "intact": "yes"}]
        self.assertFalse(self.prepare(data)["ready"])
        # kit.csv has no deck lists, so kept intact it would hold nothing: the preview, which plans
        # the deck tables from the inventory after the receipt, refuses that pool.
        data["components"][0]["intact"] = "no"
        self.record_web(self.prepare(data))
        rows = [r.as_dict() for r in inventory.current().status_rows]
        self.assertEqual([(r["status"], r["intact"], r["notes"]) for r in rows],
                         [("owned", "no", "Received 2026-10-08"), ("owned", "yes", "Received 2026-10-08")])
        record = json.loads((self.magic / "orders/records/test.json").read_bytes())
        self.assertEqual([c["status"] for c in record["components"]], ["pending", "pending", "received", "received"])
        self.assertEqual(record["components"][3]["checks"], ["Inspect the token pairs"])
        self.assertFalse((self.magic / "tokens.csv").exists())

    def test_future_or_wrong_dates_and_bad_requests_are_client_errors(self):
        for value in ("2026-10-09", "2026-02-30", None, ["2026-10-08"]):
            data = self.request_data(received_on=value)
            with self.subTest(value=value), self.assertRaises(ApiError) as caught:
                self.prepare(data)
            self.assertEqual(caught.exception.status, 400)
        for fingerprint in ("a" * 63, 5):
            with self.subTest(fingerprint=fingerprint), self.assertRaises(ApiError) as caught:
                self.prepare(self.request_data(fingerprint=fingerprint))
            self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(ApiError) as caught:
            self.prepare(self.request_data(components=[{"id": "nope", "verified": True}]))
        self.assertEqual(caught.exception.status, 400)

    def test_while_deck_saves_are_paused_the_preview_goes_ahead_and_the_decks_stay(self):
        deck = (self.magic / "decks/casual/test.md").read_bytes()
        paused = {"written": [], "skipped": [], "error": inventory.DECK_SAVES_PAUSED}
        with mock.patch.object(self.inventory, "saves_decks", lambda: False):
            preview = self.prepare()
            self.assertTrue(preview["ready"])
            self.assertEqual(preview["tables"], paused)
            self.assertNotIn("Deck Test (casual/test)", preview["changes"])
            result = self.record_web(preview)
        self.assertTrue(result["received"])
        self.assertEqual(result["tables"], paused)
        self.assertEqual((self.magic / "decks/casual/test.md").read_bytes(), deck)
        self.assertEqual(self.owned("Llanowar Elves"), 2)

    def test_a_tables_refresh_that_cant_be_planned_refuses_the_preview(self):
        self.deck("unknown", "Unknown", "idea", "Deck\n4 Not A Real Card\n")
        with self.assertRaises(ApiError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("unknown cards in target list", str(caught.exception))


class CommandLineReceiptTests(FilesReceiptCase):
    """`python -m decklab.db receive` over the same repository."""

    def run_cli(self, *args):
        from decklab.db import __main__ as cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["receive", *args])
        return code, out.getvalue(), err.getvalue()

    def test_a_preview_is_read_only_and_names_what_it_needs(self):
        before = files.tree_files(self.root)
        code, out, _ = self.run_cli("--order", "test")
        self.assertEqual(code, 0)
        self.assertIn("Preview test: cards, tokens, kit", out)
        self.assertIn("Required: tokens: resolve checks/edit received facts, then --verified tokens", out)
        self.assertIn("Required: kit: specify --intact yes or --intact no", out)
        code, out, _ = self.run_cli("--order", "test", "--component", "cards", "--verified", "cards")
        self.assertEqual(code, 0)
        self.assertIn("2 playable cards; 1 new rows; 0 existing rows increased", out)
        self.assertIn("  Home's collection\n", out)
        self.assertIn("Preview only", out)
        self.assertEqual(files.tree_files(self.root), before)
        self.assertEqual(self.run_cli("--order", "test", "--apply")[0], 1)          # no --date
        self.assertEqual(self.run_cli("--order", "test", "--verified", "nope")[0], 1)
        self.assertEqual(files.tree_files(self.root), before)

    def test_apply_receives_and_refreshes_the_tables(self):
        code, out, err = self.run_cli("--order", "test", "--component", "cards", "--component", "kit",
                                      "--verified", "cards", "--intact", "no", "--date", "2026-10-08", "--apply")
        self.assertEqual(code, 0, err)
        self.assertIn("Received.", out)
        self.assertIn("Refreshed: casual/test", out)
        self.assertIn("  Deck Test (casual/test)\n", out)        # the preview's list, from the same plan
        record = json.loads((self.magic / "orders/records/test.json").read_bytes())
        self.assertEqual([c["status"] for c in record["components"]], ["received", "pending", "received"])

    def test_while_deck_saves_are_paused_the_preview_says_so_and_the_receipt_exits_3(self):
        deck = (self.magic / "decks/casual/test.md").read_bytes()
        with mock.patch.object(self.inventory, "saves_decks", lambda: False):
            argv = ("--order", "test", "--component", "cards", "--verified", "cards")
            code, out, err = self.run_cli(*argv)
            self.assertEqual(code, 0, err)
            self.assertIn("Preview only", out)
            self.assertIn(f"Deck tables won't be refreshed: {inventory.DECK_SAVES_PAUSED}", err)
            code, out, err = self.run_cli(*argv, "--date", "2026-10-08", "--apply")
        self.assertEqual(code, 3)
        self.assertIn("Received.", out)
        self.assertIn(f"Deck tables not refreshed: {inventory.DECK_SAVES_PAUSED}", err)
        self.assertEqual((self.magic / "decks/casual/test.md").read_bytes(), deck)

    def test_rows_from_a_file_replace_the_recorded_ones(self):
        fixed = self.root / "fixed.csv"
        fixed.write_bytes(rules.csv_bytes([dict(support.TOKEN_ROW, notes="pairs checked")], rules.TOKEN_FIELDS))
        code, out, err = self.run_cli("--order", "test", "--component", "tokens", "--verified", "tokens",
                                      "--rows", f"tokens={fixed}", "--date", "2026-10-08", "--apply")
        self.assertEqual(code, 0, err)
        self.assertEqual(inventory.current().token_set().rows[0].notes, "pairs checked")
        code, _, err = self.run_cli("--order", "test", "--rows", "cards")
        self.assertEqual(code, 1)

    def test_a_refresh_that_fails_after_the_receipt_exits_3(self):
        real, calls = refresh.plan_texts, []

        def plan(only=None):                     # the preview plans; the apply's plan fails
            calls.append(None)
            if len(calls) > 1:
                raise ValueError("Fixture plan failure")
            return real(only)
        with mock.patch.object(refresh, "plan_texts", plan):
            code, out, err = self.run_cli("--order", "test", "--component", "kit", "--intact", "no",
                                          "--date", "2026-10-08", "--apply")
        self.assertEqual(code, 3)
        self.assertIn("Received.", out)
        self.assertIn("Deck tables not refreshed: Fixture plan failure", err)

    def test_a_tables_refresh_that_cant_be_planned_refuses_the_preview(self):
        self.deck("unknown", "Unknown", "idea", "Deck\n4 Not A Real Card\n")
        before = files.tree_files(self.root)
        code, _, err = self.run_cli("--order", "test", "--component", "cards", "--verified", "cards",
                                    "--date", "2026-10-08", "--apply")
        self.assertEqual(code, 1)
        self.assertIn("unknown cards in target list", err)
        self.assertEqual(files.tree_files(self.root), before)

    def owned_cli(self, name):
        return sum(int(r["quantity"]) for r in support.cards_in(self.magic / "collection.csv", existing=True)
                   if r["name"] == name)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class DatabaseReceiptTests(db_support.DbTestCase):
    """The Receipts page and `python -m decklab.db receive` with the database backend: the
    fingerprint is the database revision's, nothing in magic/ is written, there is no inventory
    commit, the deck-save lock isn't held while the database works, and the deck tables are
    refreshed in the database in the same change (the decks are imported), as an order command's
    are; a source naming a deck is looked for among the database's decks."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        from decklab.tests import test_inventory_contract as contract
        cls.contract = contract
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = self.case = FilesReceiptCase()
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.contract._rewrite_adapted(case)
        self.import_tree()
        self.db = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.db))
        self.web = WebReceiptTests("test_components_arrive_separately")
        self.web.magic, self.web.root, self.web.inventory = case.magic, case.root, self.db

    def import_tree(self):
        """Import the case's tree, its decks too, into the (reset) throwaway database."""
        from decklab.lib.inventory import pg
        pg.write_model(self.case.inventory.load(), self.contract.CLAUDE, "Import the inventory",
                       contents=self.contract.import_contents(self.case.inventory.root), dbname=self.dbname,
                       decks=True)

    def magic_files(self):
        return {rel: data for rel, data in files.tree_files(self.case.root).items()}

    def test_a_home_receipt_never_rewrites_a_persons_stale_deck(self):
        # User2's deck has a stale table (his collection was edited, which refreshes nothing):
        # the home receipt refreshes only home's decks, so his deck gets no row in its change set
        # (nor so its History or his Activity), and his pool isn't even planned.
        import os
        temp = self.case.root / "fixture-config.json"
        temp.write_text(json.dumps({"profiles": self.contract.FIXTURE_PROFILES}), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", temp),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            self.addCleanup(patcher.stop)
        people = self.case.magic / "people/user2"
        (people / "decks/casual").mkdir(parents=True)
        self.case.cards_csv("people/user2/collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.case.write("people/user2/decks/casual/elves.md", base.deck_md(
            "Elves", "idea", "Deck\n4 Llanowar Elves (FDN) 227\n56 Forest\n",
            table="| Llanowar Elves | 4 | 0 | **4** | | | |\n| **Total** | | | **4** | | | |\n"))
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        self.import_tree()
        with inventory.pinned():
            self.assertIn("user2/casual/elves", [d for d, *_ in refresh.plan_texts()])     # stale
        theirs = self.db.load().deck("user2/casual/elves")
        preview = self.web.prepare()
        self.assertEqual(preview["tables"]["written"], [{"id": "casual/test", "title": "Test"}])
        self.assertFalse([words for words in preview["changes"] if "user2/" in words], preview["changes"])
        with mock.patch.object(refresh, "_supply", wraps=refresh._supply) as supply:
            result = self.web.record_web(preview)
        self.assertEqual({call.args[0] for call in supply.call_args_list}, {"home"})
        self.assertEqual(result["tables"]["written"], [{"id": "casual/test", "title": "Test"}])
        after = self.db.load().deck("user2/casual/elves")
        self.assertEqual((after.text, after.revision), (theirs.text, theirs.revision))
        with self.connect() as c:
            keys = c.execute("select row_key from audit.row_change where table_name = 'deck' and change_set_id = "
                             "(select max(id) from audit.change_set)").fetchall()
        self.assertEqual([repr(k) for (k,) in keys if "user2" in repr(k)], [])
        self.assertEqual(len(keys), 1)                      # home's Test only

    def test_preview_then_apply_through_the_page(self):
        view = receipts.receipt_view("test")
        self.assertEqual(view["fingerprint"], hashlib.sha256(self.db.revision().encode()).hexdigest())
        before = self.magic_files()
        preview = self.web.prepare()
        self.assertTrue(preview["ready"])
        self.assertIn("Home's collection", preview["changes"])
        self.assertIn("Deck Test (casual/test)", preview["changes"])
        self.assertEqual(preview["tables"]["written"], [{"id": "casual/test", "title": "Test"}])
        deck_before = self.db.load().deck("casual/test")
        decks_revision = self.db.decks_revision()
        from decklab.lib.api import saving
        seen, real = [], inventory.apply

        def apply(*args, **kwargs):
            seen.append(saving._save_lock.locked())
            return real(*args, **kwargs)
        with mock.patch.object(inventory, "apply", apply):
            result = self.web.record_web(preview)
        self.assertEqual(seen, [False])
        self.assertTrue(result["received"])
        self.assertNotIn("commit", result)
        self.assertEqual(result["tables"], {"written": [{"id": "casual/test", "title": "Test"}], "skipped": [],
                                            "error": None})
        self.assertEqual(self.magic_files(), before)
        deck = self.db.load().deck("casual/test")
        self.assertNotEqual(deck.text, deck_before.text)
        self.assertNotIn("on the way (order test)", deck.text)
        self.assertIn("keep hand note", deck.text)
        self.assertEqual(deck.revision, deck_before.revision + 1)
        self.assertNotEqual(self.db.decks_revision(), decks_revision)
        self.assertEqual(inventory.deck_revisions("casual/test")[0].message, "receive test")
        owned = sum(r.qty for r in self.db.load().collection().rows if r.name == "Llanowar Elves")
        self.assertEqual(owned, 2)
        record = next(o for o in self.db.load().orders if o.id == "test")
        self.assertEqual([c.status for c in record.components], ["received", "pending", "pending"])

    def test_a_stale_snapshot_refuses_the_preview_and_the_apply(self):
        data = self.web.request_data()
        preview = self.web.prepare()
        inventory.apply(receive.op("test", [{"id": "kit", "verified": False, "intact": "yes"}], "2026-10-08"),
                        inventory.Actor("matt", "Matt", "home", "receipt"), "receive the kit")
        for attempt in (lambda: self.web.prepare(data), lambda: self.web.record_web(preview)):
            with self.subTest(attempt=attempt), self.assertRaises(ApiError) as caught:
                attempt()
            self.assertEqual(caught.exception.status, 409)
        owned = sum(r.qty for r in self.db.load().collection().rows if r.name == "Llanowar Elves")
        self.assertEqual(owned, 0)

    def test_the_command_line_receives_into_the_database(self):
        cli = CommandLineReceiptTests("test_a_preview_is_read_only_and_names_what_it_needs")
        before = self.magic_files()
        code, out, err = cli.run_cli("--order", "test", "--component", "cards", "--verified", "cards")
        self.assertEqual(code, 0, err)
        self.assertIn("Preview only", out)
        code, out, err = cli.run_cli("--order", "test", "--component", "cards", "--verified", "cards",
                                     "--date", "2026-10-08", "--apply")
        self.assertEqual(code, 0, err)
        self.assertIn("Received.", out)
        self.assertIn("Refreshed: casual/test", out)
        self.assertNotIn("Committed", out)
        self.assertEqual(self.magic_files(), before)
        self.assertNotIn("on the way (order test)", self.db.load().deck("casual/test").text)
        owned = sum(r.qty for r in self.db.load().collection().rows if r.name == "Llanowar Elves")
        self.assertEqual(owned, 2)

    def test_a_watchlist_source_naming_a_deck_is_checked_against_the_databases_decks(self):
        from decklab.db import __main__ as cli
        from decklab.lib import purchases
        (self.case.magic / "decks/casual/test.md").unlink()        # the database holds it; the tree doesn't

        def run(*argv):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                return cli.main(list(argv)), err.getvalue()
        code, err = run("watchlist", "set", "--add", "--name", "Sol Ring", "--state", "long_term",
                        "--source", "magic/decks/casual/test.md", "-m", "Plan")
        self.assertEqual(code, 0, err)
        code, err = run("watchlist", "set", "--add", "--name", "Opt", "--state", "long_term",
                        "--source", "magic/decks/casual/nope.md", "-m", "Plan")
        self.assertEqual(code, 1)
        self.assertIn("source file does not exist", err)
        with inventory.pinned():
            self.assertEqual([r["source"] for r in purchases.read_queue()], ["magic/decks/casual/test.md"])

    def test_an_order_command_refreshes_the_tables_in_the_same_change(self):
        from decklab.db import __main__ as cli
        before = self.magic_files()
        self.assertNotIn("on the way (order test)", self.db.load().deck("casual/test").text)      # stale
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["order", "split", "test", "cards", "--new-id", "late", "--take", "1:1", "-m", "Late"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("Deck tables refreshed: Test", out.getvalue())
        self.assertEqual(self.magic_files(), before)
        self.assertIn("1 on the way (order test-late); 1 on the way (order test)",
                      self.db.load().deck("casual/test").text)
        with self.connect() as c:
            sets = c.execute("select message from audit.change_set order by id desc limit 1").fetchall()
        self.assertEqual(sets, [("Late",)])
        self.assertEqual(inventory.deck_revisions("casual/test")[0].message, "Late")
