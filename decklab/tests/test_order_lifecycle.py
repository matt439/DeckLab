"""Order retirement over isolated snapshots and disposable PostgreSQL databases."""
import unittest
from unittest import mock

from decklab.lib import decks, inventory, pool, purchases
from decklab.lib.inventory import files, order_fulfilment, orders
from decklab.lib.inventory.model import Order
from decklab.lib.state import Invalid
from decklab.tests import db_support, test_inventory_contract as contract
from decklab.tests import test_inventory_orders as existing

OID = "2026-10-12-goodgames"


def tree(case):
    existing.orders_tree(case)
    case.product("precon.csv", ("deck", "Elvish Mystic", 1), column="section")


def add_deck(case):
    case.deck("queue", "Queue deck", "idea", "Deck\n4 Elvish Mystic\n20 Forest\n",
              table="| Elvish Mystic | 4 | 0 | 3 | | | Keep this note |\n")


class _Lifecycle:
    start = existing.OrderOps.start
    op = existing.OrderOps.op
    load = existing.OrderOps.load
    refused = existing.OrderOps.refused
    queue = existing.OrderOps.queue
    add_params = existing.OrderOps.add_params

    def add(self, **changes):
        params = self.add_params(fulfils=[{"select": "Elvish Mystic", "quantity": 2},
                                        {"select": "Pick Your Poison", "quantity": 1}])
        params.update(changes)
        return self.op("order.add", **params)

    def test_cancel_product_retains_history_but_leaves_pool_library_and_packing(self):
        before = self.load()
        with inventory.pinned(before):
            self.assertTrue(any(row["id"].startswith("product/precon") for row in decks.list_decks()))
            incoming = sum(qty for _, qty in pool.load_pool().on_the_way["Elvish Mystic"])
        after, summary = self.op("order.cancel", order="2026-10-02-precon", component="precon",
                                 reason="Shop could not supply it", restore_queue=True)
        self.assertEqual(after.order("2026-10-02-precon").components[0].status, "cancelled")
        row = next(row for row in after.status.rows if row.text("file") == "precon.csv")
        self.assertEqual(tuple(row.text(key) for key in ("status", "intact", "sleeves", "deck_box", "notes")),
                         ("cancelled", "", "", "", "due soon"))
        self.assertEqual(after.product("precon"), before.product("precon"))
        self.assertFalse(summary.extra["queue"]["known"])
        self.assertTrue(summary.extra["queue"]["warnings"])
        self.assertIsNone(summary.extra["tables"]["error"])
        with inventory.pinned(after):
            supply = pool.load_pool()
            self.assertEqual(sum(qty for _, qty in supply.on_the_way["Elvish Mystic"]), incoming - 1)
            self.assertFalse(supply.warnings)
            self.assertFalse(any(row["id"].startswith("product/precon") for row in decks.list_decks()))
            self.assertFalse(orders.pairing_problems(after))
            with mock.patch.object(purchases.config, "REPO", self.root):
                self.assertFalse(purchases.overview()["warnings"])

    def test_tracked_split_cancel_and_remove_restore_each_copy_once(self):
        self.add()
        self.op("order.split", order=OID, component="cards", new_id="late", take=[{"row": 1, "quantity": 1}])
        after, summary = self.op("order.cancel", order=OID, component="late", reason="Not sent", restore_queue=True)
        self.assertTrue(summary.extra["queue"]["known"])
        self.assertEqual([(row["name"], row["quantity"], row["for"]) for row in summary.extra["queue"]["restored"]],
                         [("Elvish Mystic", "1", "Elves")])
        self.assertEqual(next(row for row in after.watchlist.rows if row.text("name") == "Elvish Mystic").qty, 2)
        after, summary = self.op("order.remove", order=OID, reason="Mistaken remaining order")
        self.assertIsNone(after.order(OID))
        self.assertEqual(sum(int(row["quantity"]) for row in summary.extra["queue"]["restored"]), 2)
        self.assertEqual([(row["name"], row["quantity"]) for row in self.queue()],
                         [("Elvish Mystic", "3"), ("Sol Ring", "1"), ("Sol Ring", "1"), ("Pick Your Poison", "1")])

    def test_declined_offer_is_consumed_before_later_removal(self):
        self.add()
        after, summary = self.op("order.cancel", order=OID, component="cards", reason="No longer wanted")
        self.assertEqual(sum(int(row["quantity"]) for row in summary.extra["queue"]["offered"]), 3)
        self.assertEqual(summary.extra["queue"]["restored"], [])
        after, summary = self.op("order.remove", order=OID, reason="Clear mistaken cancelled record")
        self.assertEqual(summary.extra["queue"]["restored"], [])
        self.assertEqual(next(row for row in after.watchlist.rows if row.text("name") == "Elvish Mystic").qty, 1)

    def test_remove_mixed_order_deletes_only_exclusive_unreceived_sources(self):
        before = self.load()
        self.add(tokens={"rows": [existing.token("Llanowar Elves", 1, notes="single-sided verified")]},
                 product={"stem": "alpha-deck", "columns": existing.PRODUCT_COLUMNS,
                          "rows": existing.product_rows(("Elves", "Llanowar Elves", "fdn", "227", 2))},
                 extra_copies=["alpha-deck"])
        after, summary = self.op("order.remove", order=OID, reason="Duplicate entry")
        self.assertIsNone(after.order(OID))
        self.assertIsNone(after.product("alpha-deck"))
        self.assertFalse(any(row.text("file") == "alpha-deck.csv" for row in after.status.rows))
        self.assertFalse(any(OID in path for path in after.payloads))
        self.assertEqual(after.collection("home"), before.collection("home"))
        self.assertEqual(after.token_set("home"), before.token_set("home"))
        self.assertIsNotNone(after.order("2026-10-01-shop"))
        self.assertIn("casual/queue", [row["id"] for row in summary.extra["tables"]["written"]])
        self.assertIsNone(summary.extra["tables"]["error"])
        with inventory.pinned(after):
            with mock.patch.object(purchases.config, "REPO", self.root):
                self.assertFalse(purchases.overview()["warnings"])

    def test_historical_order_never_guesses_queue_rows(self):
        before = self.queue()
        _, summary = self.op("order.remove", order="2026-10-07-shop-a", reason="Wrong historic order")
        self.assertEqual(self.queue(), before)
        self.assertEqual(summary.extra["queue"]["known"], False)
        self.assertEqual(summary.extra["queue"]["offered"], [])
        self.assertEqual(summary.extra["queue"]["restored"], [])
        self.assertTrue(summary.extra["queue"]["warnings"])

    def test_removal_refuses_any_received_part_owned_intact_or_shared_product(self):
        self.refused("any component has been received", "order.remove", order="2026-10-01-shop", reason="Wrong")
        self.add()
        inv = self.load()
        altered = inv.update_component(OID, "cards", status="received", received_on="2026-10-13")
        with self.assertRaisesRegex(Invalid, "any component has been received"):
            inventory.Op("order.remove", {"order": OID, "reason": "Wrong"}).run(altered)
        product_order = inv.order("2026-10-02-precon")
        for values, message in (({"status": "owned"}, "owned or not pending"),
                                ({"intact": "yes"}, "kept intact")):
            changed = inv.with_status_rows([row.replace(**values) if row.text("file") == "precon.csv" else row
                                           for row in inv.status.rows])
            with self.assertRaisesRegex(Invalid, message):
                inventory.Op("order.remove", {"order": product_order.id, "reason": "Wrong"}).run(changed)
        record = product_order.record()
        record["id"] = "duplicate-product"
        duplicate = inv.with_order(Order("duplicate-product.json", record))
        with self.assertRaisesRegex(Invalid, "another order component"):
            inventory.Op("order.remove", {"order": product_order.id, "reason": "Wrong"}).run(duplicate)

    def test_reason_and_explicit_boolean_rules_and_corrupt_ledger_refuse_without_writes(self):
        self.refused("reason", "order.remove", order="2026-10-07-shop-a", reason=" ")
        self.refused("cannot be skipped", "order.remove", order="2026-10-07-shop-a", reason="Wrong", restore_queue=False)
        self.refused("Choose whether", "order.cancel", order="2026-10-07-shop-a", component="cards",
                     reason="Wrong", restore_queue=1)
        self.add()
        before = self.load()
        self.refused("reserved fulfilment marker", "order.cancel", order=OID, component="cards",
                     reason="Shop said [[Deck Lab fulfilment something", restore_queue=True)
        self.refused("reserved fulfilment marker", "order.remove", order=OID,
                     reason="Duplicate [[Deck Lab fulfilment record")
        record = before.order(OID).record()
        record["audit_notes"] = '[[Deck Lab fulfilment v1: {"claims":"broken"}]]'
        bad = before.with_order(Order(f"{OID}.json", record))
        with self.assertRaises(Invalid):
            inventory.Op("order.cancel", {"order": OID, "component": "cards", "reason": "Wrong"}).run(bad)
        self.assertEqual(files.render(self.load()), files.render(before))


class FileLifecycleTests(_Lifecycle, unittest.TestCase):
    def setUp(self):
        case = contract.build_tree(tree, adapted=True)
        self.addCleanup(case.doCleanups)
        add_deck(case)
        self.backend = files.FileInventory(case.inventory.root)
        self.start(case)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class PgLifecycleTests(_Lifecycle, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = contract.build_tree(tree, adapted=True)
        self.addCleanup(case.doCleanups)
        add_deck(case)
        pg.write_model(case.inventory.load(), existing.CLAUDE, "Import fixture",
                       contents=contract.import_contents(case.inventory.root), dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.start(case)

    def test_persisted_ledger_removal_is_one_audit_with_tables_and_queue_and_rolls_back_together(self):
        from decklab.lib.inventory import pg
        self.add()
        before = self.load()
        self.assertIsNotNone(order_fulfilment.read(before.order(OID)))
        with self.connect() as connection:
            count = connection.execute("select count(*) from audit.change_set").fetchone()[0]
        actual = pg._diff

        def fail_after_diff(*args):
            actual(*args)
            raise RuntimeError("simulated database refusal")

        with mock.patch.object(pg, "_diff", side_effect=fail_after_diff):
            with self.assertRaisesRegex(Exception, "simulated database refusal"):
                self.op("order.remove", order=OID, reason="Duplicate")
        self.assertEqual(files.render(self.load(), decks=True), files.render(before, decks=True))
        after, summary = self.op("order.remove", order=OID, reason="Duplicate")
        self.assertIsNone(after.order(OID))
        self.assertEqual(after.decks["casual/queue"].revision, before.decks["casual/queue"].revision + 1)
        with self.connect() as connection:
            self.assertEqual(connection.execute("select count(*) from audit.change_set").fetchone()[0], count + 1)
            changed = {row[0] for row in connection.execute(
                "select table_name from audit.row_change where change_set_id = (select max(id) from audit.change_set)")}
        self.assertTrue({"purchase_order", "order_component", "order_card_item", "watchlist_item", "deck"} <= changed,
                        changed)
        self.assertIsNone(summary.extra["tables"]["error"])


if __name__ == "__main__":
    unittest.main()
