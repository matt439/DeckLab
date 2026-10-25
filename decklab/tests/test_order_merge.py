"""Combining orders that shipped together, on both disposable backends and through the CLI.

Run: python -m unittest decklab.tests.test_order_merge
"""
import json
import unittest

from decklab.lib import inventory, purchases
from decklab.lib.inventory import files, order_fulfilment, rules
from decklab.lib.inventory.files import FileInventory
from decklab.tests import db_support, test_inventory_contract as contract
from decklab.tests import test_inventory_orders as fixture

OID = "2026-10-07-shop-a"
EXTRA = "2026-10-08-shop-a"


def merge_tree(tree):
    """orders_tree plus a second pending MTGMate order with a cards component of its own."""
    fixture.orders_tree(tree)
    tree.write(f"orders/{EXTRA}.csv", fixture.CARD_HEADER + "Sol Ring,c21,263,nonfoil,1,,,\n")
    tree.write(f"orders/records/{EXTRA}.json", fixture.record_json(
        EXTRA, "MTGMate", "2026-10-08", [fixture.component("cards", "cards", f"magic/orders/{EXTRA}.csv",
                                                            checks=["Check the Sol Ring"])]))
    path = tree.magic / f"orders/records/{EXTRA}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["notes"] = "Added to the same parcel."
    record["sources"] = ["magic/buylists/2026-10-12-plan.md"]
    record["audit_notes"] = "Extra copies of owned printings: cards. Imported by hand."
    path.write_bytes(rules.json_bytes(record))


class MergeOps:
    start = fixture.OrderOps.start
    op = fixture.OrderOps.op
    load = fixture.OrderOps.load
    refused = fixture.OrderOps.refused
    queue = fixture.OrderOps.queue

    def merge(self, **changes):
        params = {"order": OID, "others": [EXTRA], "repo": str(self.root),
                  "renames": [{"order": EXTRA, "component": "cards", "id": "additions"}]}
        params.update(changes)
        return self.op("order.merge", **params)

    def test_components_move_with_their_rows_checks_and_acknowledgements(self):
        before = self.load()
        after, summary = self.merge()
        self.assertIsNone(after.order(EXTRA))
        merged = after.order(OID)
        self.assertEqual([c.id for c in merged.components], ["cards", "tokens", "additions"])
        moved = merged.components[2]
        self.assertEqual((moved.path, moved.checks), (f"magic/orders/{EXTRA}.csv", ["Check the Sol Ring"]))
        self.assertEqual(files.render(after)[moved.path], files.render(before)[moved.path])
        self.assertEqual(merged.sources, ["magic/buylists/2026-10-12-plan.md"])
        self.assertEqual(merged.notes, "Added to the same parcel.")
        self.assertEqual(rules.extra_copies(merged.audit_notes), ("additions",))
        self.assertIn(f"Merged in order {EXTRA} (ordered 2026-10-08), its cards as additions. "
                      "Its audit notes: Imported by hand.", merged.audit_notes)
        self.assertEqual(summary.counts, {"orders": 1, "components": 1})
        self.assertEqual(after.collection("home").rows, before.collection("home").rows)
        with inventory.pinned(after):
            self.assertIn(OID, [r["id"] for r in purchases._read_records(self.root)])

    def test_fulfilment_history_follows_the_renamed_component(self):
        self.op("order.add", **fixture.OrderOps.add_params(
            self, record={"id": "2026-10-12-goodgames", "seller": "MTGMate", "ordered_on": "2026-10-12"},
            cards={"rows": [fixture.card("Elvish Mystic", "cmm", 648, 2)]}, fulfils=[{"select": "Elvish Mystic", "quantity": 2}]))
        target = "2026-10-12-goodgames"
        theirs = order_fulfilment.read(self.load().order(target))
        self.assertTrue(theirs["claims"])
        # The order merged into needs a ledger of its own too.
        self.op("order.add", **fixture.OrderOps.add_params(
            self, record={"id": "2026-10-13-mtgmate", "seller": "MTGMate", "ordered_on": "2026-10-13"},
            cards={"rows": [fixture.card("Pick Your Poison", "mkm", 170, 1)]}))
        after, _ = self.op("order.merge", order="2026-10-13-mtgmate", others=[target], repo=str(self.root),
                           renames=[{"order": target, "component": "cards", "id": "first"}])
        ledger = order_fulfilment.read(after.order("2026-10-13-mtgmate"))
        self.assertEqual({c["component"] for c in ledger["claims"]}, {"first"})
        self.assertEqual(sum(c["quantity"] for c in ledger["claims"]), sum(c["quantity"] for c in theirs["claims"]))
        mystic = [r for r in self.queue() if r["name"] == "Elvish Mystic"]
        self.assertEqual([r["quantity"] for r in mystic], ["1"])
        self.op("order.cancel", order="2026-10-13-mtgmate", component="first", reason="Out of stock",
                restore_queue=True)
        self.assertEqual([r["quantity"] for r in self.queue() if r["name"] == "Elvish Mystic"], ["3"])

    def test_refusals_change_nothing(self):
        self.refused("already has a component 'cards'", "order.merge", order=OID, others=[EXTRA],
                     repo=str(self.root))
        self.refused("not 'MTGMate'", "order.merge", order=OID, others=["2026-10-02-precon"], repo=str(self.root))
        self.refused("received component", "order.merge", order="2026-10-01-shop", others=["2026-10-02-precon"],
                     repo=str(self.root))
        self.refused("no order", "order.merge", order=OID, others=["nope"], repo=str(self.root))
        self.refused("once", "order.merge", order=OID, others=[OID], repo=str(self.root))
        self.refused("no component 'tokens'", "order.merge", order=OID, others=[EXTRA], repo=str(self.root),
                     renames=[{"order": EXTRA, "component": "cards", "id": "additions"},
                              {"order": EXTRA, "component": "tokens", "id": "more"}])

    def test_mixed_fulfilment_history_is_refused(self):
        self.op("order.add", **fixture.OrderOps.add_params(
            self, record={"id": "2026-10-13-mtgmate", "seller": "MTGMate", "ordered_on": "2026-10-13"},
            cards={"rows": [fixture.card("Pick Your Poison", "mkm", 170, 1)]}))
        self.refused("fulfilment history", "order.merge", order="2026-10-13-mtgmate", others=[OID],
                     repo=str(self.root))


class FileMergeTests(MergeOps, unittest.TestCase):
    def setUp(self):
        case = contract.build_tree(merge_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        self.backend = FileInventory(case.inventory.root)
        self.start(case)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class PgMergeTests(MergeOps, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = contract.build_tree(merge_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        pg.write_model(case.inventory.load(), fixture.CLAUDE, "Import",
                       contents=contract.import_contents(case.inventory.root), dbname=self.dbname)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.start(case)

    def test_the_moved_rows_are_stored_under_the_merged_order(self):
        self.merge()
        with self.connect() as c:
            rows = c.execute("select order_id, component_id, name from order_card_item where name = 'Sol Ring'"
                             ).fetchall()
            gone = c.execute("select count(*) from purchase_order where id = %s", (EXTRA,)).fetchone()[0]
        self.assertEqual(rows, [(OID, "additions", "Sol Ring")])
        self.assertEqual(gone, 0)


class MergeCommandTests(unittest.TestCase):
    setUp = fixture.CommandLineTests.setUp
    run_cli = fixture.CommandLineTests.run_cli

    def test_refusals_are_reported(self):
        args = ("order", "merge", OID, "2026-10-02-precon", "-m", "One parcel")
        code, _, err = self.run_cli(*args)
        self.assertEqual(code, 1)
        self.assertIn("not 'MTGMate'", err)
        code, _, err = self.run_cli("order", "merge", OID, "x", "--rename", "bad", "-m", "One parcel")
        self.assertEqual(code, 1)
        self.assertIn("OTHER:COMPONENT=NEW", err)


if __name__ == "__main__":
    unittest.main()
