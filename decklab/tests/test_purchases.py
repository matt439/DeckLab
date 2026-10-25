"""Shopping records never turn recommendations or unknown facts into inventory."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import config, inventory, purchases
from decklab.lib.inventory.files import FileInventory


class PurchasesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # The inventory is this tree's (decklab/lib/inventory); buylist sources are checked under it.
        self.addCleanup(inventory.use(FileInventory(self.root)))
        patcher = mock.patch.object(config, "REPO", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write_csv("magic/watchlist.csv", purchases.QUEUE_FIELDS, [])
        self.write_csv("magic/products/status.csv", ["file", "status", "intact", "notes"], [])
        self.write("magic/buylists/research.md", "# Historical research\n")
        self.record = {"version": 1, "id": "test-order", "seller": "Test shop",
                       "ordered_on": "2026-10-07", "sources": ["magic/buylists/research.md"],
                       "notes": "", "components": [self.component()]}
        self.write_csv("magic/orders/test.csv", ["name", "quantity"], [{"name": "Sol Ring", "quantity": "2"}])
        self.save()

    def component(self, **changes):
        component = {"id": "cards", "kind": "cards", "path": "magic/orders/test.csv",
                     "status": "pending", "received_on": "", "checks": ["Condition unconfirmed"]}
        return component | changes

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return path

    def write_csv(self, name, fields, rows):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def save(self):
        return self.write("magic/orders/records/test-order.json", json.dumps(self.record))

    def overview(self):
        return purchases.overview()

    def test_current_view_does_not_promote_wishlists_or_research_to_orders(self):
        data = self.overview()
        self.assertEqual(data["to_buy"], [])
        self.assertEqual(len(data["orders"]), 1)
        self.assertEqual(data["orders"][0]["components"][0]["quantity"], 2)
        self.assertEqual(data["checks"][0]["text"], "Condition unconfirmed")

    def test_partial_shipment_and_physical_token_counts(self):
        original = self.root / "magic/orders/test.csv"
        archive = self.root / "magic/orders/received/test.csv"
        archive.parent.mkdir()
        original.rename(archive)
        self.record["components"][0].update(path="magic/orders/received/test.csv", status="received", received_on="2026-10-08", checks=[])
        self.write_csv("magic/orders/tokens/test.csv", ["front", "back", "quantity"],
                       [{"front": "Rabbit", "back": "Rabbit", "quantity": "2"}])
        self.record["components"].append(self.component(id="tokens", kind="tokens", path="magic/orders/tokens/test.csv", checks=["Verify pairing"]))
        self.save()
        data = self.overview()
        self.assertEqual(data["orders"][0]["status"], "partial")
        self.assertEqual(data["orders"][0]["components"][1]["quantity"], 2)
        self.assertEqual(len(data["checks"]), 1)

    def test_cancelled_order_not_waiting_or_needing_inspection(self):
        archive = self.root / "magic/orders/cancelled/test.csv"
        archive.parent.mkdir()
        (self.root / "magic/orders/test.csv").rename(archive)
        self.record["components"][0].update(path="magic/orders/cancelled/test.csv", status="cancelled")
        self.save()
        self.assertEqual(self.overview()["orders"][0]["status"], "cancelled")
        self.assertEqual(self.overview()["checks"], [])

    def test_unrecorded_delivery_fails_visibly(self):
        self.write_csv("magic/orders/missing.csv", ["name", "quantity"], [{"name": "Forest", "quantity": "1"}])
        with self.assertRaisesRegex(ValueError, "missing order record"):
            self.overview()

    def test_manifest_rejects_duplicate_component_path_and_status_location_mismatch(self):
        self.record["components"].append(self.component(id="other"))
        self.save()
        with self.assertRaisesRegex(ValueError, "more than one order"):
            self.overview()
        self.record["components"] = [self.component(status="received")]
        self.save()
        with self.assertRaisesRegex(ValueError, "location conflicts"):
            self.overview()

    def test_path_escape_and_impossible_dates_rejected(self):
        for changes, message in [({"path": "../other.csv"}, "relative repository"),
                                 ({"received_on": "2026-10-08"}, "receipt date conflicts"),
                                 ({"received_on": "2026-02-30"}, "YYYY-MM-DD")]:
            with self.subTest(changes=changes):
                self.record["components"] = [self.component(**changes)]
                self.save()
                with self.assertRaisesRegex(ValueError, message):
                    self.overview()

    def test_product_receipt_status_must_agree(self):
        self.write_csv("magic/products/test.csv", ["name", "quantity"], [{"name": "Forest", "quantity": "20"}])
        self.write_csv("magic/products/status.csv", ["file", "status", "intact", "notes"],
                       [{"file": "test.csv", "status": "owned", "intact": "no", "notes": ""}])
        self.record["components"].append(self.component(id="product", kind="product", path="magic/products/test.csv"))
        self.save()
        with self.assertRaisesRegex(ValueError, "statuses disagree"):
            self.overview()
        self.record["components"][1].update(status="received", received_on="2026-10-08")
        self.save()
        self.assertEqual(self.overview()["orders"][0]["status"], "partial")
        self.write_csv("magic/products/status.csv", ["file", "status", "intact", "notes"],
                       [{"file": "test.csv", "status": "ordered", "intact": "", "notes": ""}])
        self.record["components"][1].update(status="cancelled", received_on="")
        self.save()
        with self.assertRaisesRegex(ValueError, "statuses disagree"):
            self.overview()

    def test_product_status_with_kit_columns_is_read_like_the_legacy_file(self):
        self.write_csv("magic/products/test.csv", ["name", "quantity"], [{"name": "Forest", "quantity": "20"}])
        self.write_csv("magic/products/status.csv", ["file", "status", "intact", "sleeves", "deck_box", "notes"],
                       [{"file": "test.csv", "status": "owned", "intact": "yes", "sleeves": "red",
                         "deck_box": "", "notes": ""}])
        self.record["components"].append(self.component(id="product", kind="product", path="magic/products/test.csv",
                                                         status="received", received_on="2026-10-08"))
        self.save()
        self.assertEqual(self.overview()["orders"][0]["status"], "partial")

    def test_queue_has_explicit_state_and_dated_reference_price(self):
        row = dict.fromkeys(purchases.QUEUE_FIELDS, "") | {"name": "Sol Ring", "quantity": "1", "printing": "any",
                "state": "waiting_for_stock", "listed_aud": "1.50", "listed_at": "Test shop", "in_stock": "no",
                "checked": "2026-10-07", "source": "magic/buylists/research.md"}
        self.write_csv("magic/watchlist.csv", purchases.QUEUE_FIELDS, [row])
        self.assertEqual(self.overview()["to_buy"][0]["quantity"], 1)
        self.write_csv("magic/watchlist.csv", purchases.QUEUE_FIELDS, [row | {"state": "long_term"}])
        self.assertEqual(self.overview()["to_buy"][0]["state"], "long_term")
        for changes, message in [({"printing": "exact"}, "exact printing needs"),
                                 ({"quantity": "-1"}, "positive integer"),
                                 ({"listed_aud": "NaN"}, "AUD reference price"),
                                 ({"checked": ""}, "retailer and checked date"),
                                 ({"state": "ordered"}, "invalid purchase state")]:
            with self.subTest(changes=changes):
                self.write_csv("magic/watchlist.csv", purchases.QUEUE_FIELDS, [row | changes])
                with self.assertRaisesRegex(ValueError, message):
                    self.overview()

    def test_a_source_naming_a_deck_is_looked_for_among_the_snapshots_decks(self):
        # The phase 4 design's R9: the string stays a deck file's path, but whether that deck is
        # there is the inventory snapshot's answer (the decks leave the tree at the cutover).
        from decklab.lib.inventory import orders
        from decklab.lib.inventory.model import Deck
        self.write("magic/decks/casual/elves.md", "# Elves\n")
        self.write("magic/people/user2/decks/commander/goblins.md", "# Goblins\n")
        row = dict.fromkeys(purchases.QUEUE_FIELDS, "") | {"name": "Sol Ring", "quantity": "1", "printing": "any",
                                                            "state": "long_term"}
        sources = ("magic/decks/casual/elves.md", "magic/people/user2/decks/commander/goblins.md")
        self.write_csv("magic/watchlist.csv", purchases.QUEUE_FIELDS,
                       [row | {"source": source, "for": source} for source in sources])
        self.record["sources"] = ["magic/buylists/research.md", sources[0]]
        self.save()
        data = self.overview()
        self.assertEqual([r["source"] for r in data["to_buy"]], list(sources))
        self.assertEqual(data["orders"][0]["sources"], self.record["sources"])
        inv = inventory.current()
        gone = inv.without_deck("casual/elves")
        self.assertTrue((self.root / sources[0]).is_file())     # on disk, but not in the snapshot
        with inventory.pinned(gone):
            with self.assertRaisesRegex(ValueError, "source magic/decks/casual/elves.md does not exist"):
                purchases.read_records()
            with self.assertRaisesRegex(ValueError, "watchlist: Sol Ring: source file does not exist"):
                purchases.read_queue()
        with self.assertRaisesRegex(inventory.Invalid, "source file does not exist"):
            orders.queue_row(row | {"source": sources[0]}, str(self.root), gone)
        self.assertEqual(orders.queue_row(row | {"source": sources[0]}, str(self.root), inv)["source"], sources[0])
        # A deck the snapshot has and the tree doesn't (the database's) is there.
        only = gone.with_deck(Deck("home", "casual", "elves", "# Elves\n", None))
        (self.root / sources[0]).unlink()
        with inventory.pinned(only):
            self.assertEqual(len(purchases.read_records()), 1)
            self.assertEqual(len(purchases.read_queue()), 2)
        self.assertTrue(purchases.source_exists(self.root, sources[0], inv=only))
        self.assertFalse(purchases.source_exists(self.root, "magic/decks/casual/nope.md", inv=only))
        self.assertTrue(purchases.source_exists(self.root, "magic/buylists/research.md", inv=gone))
        with self.assertRaisesRegex(ValueError, "relative repository path"):
            purchases.source_exists(self.root, "../magic/decks/casual/elves.md", inv=only)


if __name__ == "__main__":
    unittest.main()
