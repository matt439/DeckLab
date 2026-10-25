"""Order record corrections on both disposable backends and through the CLI.

Run: python -m unittest decklab.tests.test_order_records
"""
import contextlib
import io
import json
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import files, order_records, refresh, rules
from decklab.lib.inventory.files import FileInventory
from decklab.lib.inventory.model import Deck, Order
from decklab.lib.state import Invalid
from decklab.tests import db_support, test_inventory_contract as contract
from decklab.tests import test_inventory_orders as fixture

OID = "2026-10-07-shop-a"
SOURCE = "magic/buylists/2026-10-12-plan.md"


def record_tree(tree):
    fixture.orders_tree(tree)
    path = tree.magic / f"orders/records/{OID}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["audit_notes"] = "Extra copies of owned printings: cards. Imported from a receipt."
    record["components"][0]["verified_checks"] = ["Seller confirmed quantities"]
    path.write_bytes(rules.json_bytes(record))


class RecordOps:
    start = fixture.OrderOps.start
    op = fixture.OrderOps.op
    load = fixture.OrderOps.load
    refused = fixture.OrderOps.refused

    def test_metadata_correction_preserves_components_provenance_and_inventory(self):
        before = self.load()
        values = {"seller": "Correct shop", "ordered_on": "2026-10-08", "notes": "Order reference 42",
                  "sources": [SOURCE]}
        op = inventory.Op("order.record", {"order": OID, "values": values, "repo": str(self.root)})
        with mock.patch.object(refresh, "in_op", side_effect=AssertionError("must not refresh tables")), \
                mock.patch.object(refresh, "preload", side_effect=AssertionError("must not load cards")):
            preview, summary = inventory.preview(op)
            self.assertFalse(preview.persisted)
            self.assertEqual(files.render(before), files.render(self.load()))
            after, saved = inventory.apply(op, fixture.CLAUDE, "Fix order record")
        self.assertEqual(saved.text, summary.text)
        self.assertEqual(inventory.changed_paths(before, after), [f"magic/orders/records/{OID}.json"])
        self.assertEqual(after.order(OID).record(), before.order(OID).record() | values)
        self.assertEqual(after.order(OID).audit_notes, before.order(OID).audit_notes)
        self.assertEqual(after.order(OID).components, before.order(OID).components)
        self.assertNotIn("tables", saved.extra)

    def test_unspecified_fields_stay_and_blank_fields_are_allowed(self):
        before = self.load().order(OID).record()
        after, _ = self.op("order.record", order=OID, values={"notes": "Delivery instructions"}, repo=str(self.root))
        self.assertEqual(after.order(OID).record(), before | {"notes": "Delivery instructions"})
        after, _ = self.op("order.record", order=OID, values={"seller": "", "ordered_on": "", "notes": "",
                                                             "sources": []}, repo=str(self.root))
        self.assertEqual(after.order(OID).seller, "")
        self.assertEqual(after.order(OID).ordered_on, "")
        self.assertEqual(after.order(OID).sources, [])

    def test_received_cancelled_and_product_orders_can_be_corrected(self):
        self.op("order.cancel", order=OID, component="tokens", reason="Not shipping")
        for oid in (OID, "2026-10-01-shop", "2026-10-02-precon", "product-fdn-beginner-box"):
            before = self.load().order(oid).record()
            after, _ = self.op("order.record", order=oid, values={"notes": "Correct reference"}, repo=str(self.root))
            self.assertEqual(after.order(oid).record(), before | {"notes": "Correct reference"})

    def test_invalid_values_are_refused_without_a_write(self):
        for values, message in (
                ({}, "record fields"), ({"id": "different"}, "record fields"),
                ({"components": []}, "record fields"), ({"audit_notes": "erase"}, "record fields"),
                ({"seller": "Shop\nOther"}, "expected single-line text"),
                ({"notes": None}, "expected single-line text"),
                ({"ordered_on": "2026-02-30"}, "expected YYYY-MM-DD"),
                ({"ordered_on": "2026-1-01"}, "expected YYYY-MM-DD"),
                ({"sources": SOURCE}, "expected a list"), ({"sources": [""]}, "must not be blank"),
                ({"sources": ["../outside.md"]}, "relative repository path"),
                ({"sources": ["magic/buylists/missing.md"]}, "does not exist")):
            with self.subTest(values=values):
                self.refused(message, "order.record", order=OID, values=values, repo=str(self.root))
        self.refused("There's no order", "order.record", order="missing", values={"notes": "Fix"}, repo=str(self.root))

    def test_unchanged_values_are_a_no_op(self):
        before = self.load()
        after, summary = self.op("order.record", order=OID, values={"seller": before.order(OID).seller},
                                 repo=str(self.root))
        self.assertEqual(before.revision, after.revision)
        self.assertEqual(inventory.changed_paths(before, after), [])
        self.assertIn("nothing to change", summary.text)

    def test_order_date_must_not_follow_a_receipt(self):
        self.refused("cards: receipt date conflicts with status or order date", "order.record",
                     order="2026-10-01-shop", values={"ordered_on": "2026-10-04"}, repo=str(self.root))
        after, _ = self.op("order.record", order="2026-10-01-shop", values={"ordered_on": "2026-10-03"},
                           repo=str(self.root))
        self.assertEqual(after.order("2026-10-01-shop").ordered_on, "2026-10-03")


class FileRecordTests(RecordOps, unittest.TestCase):
    def setUp(self):
        case = contract.build_tree(record_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        self.backend = FileInventory(case.inventory.root)
        self.start(case)

    def test_unknown_metadata_is_retained_by_the_operation(self):
        before = self.load()
        original = before.order(OID)
        record = original.record() | {"origin": {"reference": ["keep", 3]}}
        record["components"][0]["origin"] = {"inspection": "keep"}
        inv = before.with_order(Order(original.file, record))
        after, _ = inventory.Op("order.record", {"order": OID, "values": {"notes": "Fix"},
                                                  "repo": str(self.root)}).run(inv)
        self.assertEqual(after.order(OID).record(), record | {"notes": "Fix"})
        self.assertEqual(inv.order(OID).record(), record)

    def test_deck_sources_are_checked_in_the_snapshot_and_keep_their_path(self):
        inv = self.load().with_deck(Deck("home", "casual", "elves", "# Elves\n", None))
        source = "magic/decks/casual/elves.md"
        op = inventory.Op("order.record", {"order": OID, "values": {"sources": (source, SOURCE)},
                                             "repo": str(self.root)})
        after, _ = op.run(inv)
        self.assertEqual(after.order(OID).sources, [source, SOURCE])
        fake = self.root / source
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_text("# Stale file\n", encoding="utf-8")
        with self.assertRaisesRegex(Invalid, "does not exist"):
            op.run(inv.without_deck("casual/elves"))


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class PgRecordTests(RecordOps, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = contract.build_tree(record_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        pg.write_model(case.inventory.load(), fixture.CLAUDE, "Import", contents=contract.import_contents(case.inventory.root),
                       dbname=self.dbname)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.start(case)

    def test_correction_has_one_audit_change_and_no_component_or_card_changes(self):
        with self.connect() as c:
            count = c.execute("select count(*) from audit.change_set").fetchone()[0]
        self.op("order.record", order=OID, values={"seller": "Correct shop", "sources": [SOURCE]}, repo=str(self.root))
        with self.connect() as c:
            sets = c.execute("select id, message from audit.change_set order by id").fetchall()
            rows = c.execute("select table_name, op from audit.row_change where change_set_id = %s",
                             (sets[-1][0],)).fetchall()
        self.assertEqual(len(sets), count + 1)
        self.assertEqual(sets[-1][1], "test order.record")
        self.assertEqual(rows, [("purchase_order", "UPDATE")])
        self.op("order.record", order=OID, values={"seller": "Correct shop"}, repo=str(self.root))
        with self.connect() as c:
            self.assertEqual(c.execute("select count(*) from audit.change_set").fetchone()[0], count + 1)


class RecordCommandTests(unittest.TestCase):
    setUp = fixture.CommandLineTests.setUp
    run_cli = fixture.CommandLineTests.run_cli

    def test_record_dry_run_then_save_only_supplied_fields(self):
        before = self.backend.load()
        args = ("order", "record", OID, "--seller", "Correct shop", "--ordered-on", "2026-10-08",
                "--notes", "Reference 42", "--source", SOURCE, "-m", "Fix record")
        code, out, err = self.run_cli(*args, "--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Dry run: nothing saved", out)
        self.assertEqual(files.render(before), files.render(self.backend.load()))
        code, out, err = self.run_cli(*args)
        self.assertEqual((code, err), (0, ""))
        after = self.backend.load()
        self.assertEqual(after.order(OID).record(), before.order(OID).record() | {
            "seller": "Correct shop", "ordered_on": "2026-10-08", "notes": "Reference 42", "sources": [SOURCE]})
        self.refresh.assert_not_called()
        self.plan.assert_not_called()

    def test_sources_replace_in_the_given_order_and_can_be_cleared(self):
        source2 = "magic/reports/order-correction.md"
        report = self.root / source2
        report.parent.mkdir(exist_ok=True)
        report.write_text("# Receipt\n", encoding="utf-8")
        code, _, err = self.run_cli("order", "record", OID, "--source", source2, "--source", SOURCE, "-m", "Sources")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.backend.load().order(OID).sources, [source2, SOURCE])
        code, _, err = self.run_cli("order", "record", OID, "--clear-sources", "--seller", "", "--ordered-on", "",
                                  "--notes", "", "-m", "Unknown details")
        self.assertEqual((code, err), (0, ""))
        order = self.backend.load().order(OID)
        self.assertEqual((order.seller, order.ordered_on, order.notes, order.sources), ("", "", "", []))

    def test_missing_fields_invalid_dates_and_blank_messages_are_refused(self):
        before = files.render(self.backend.load())
        for flags, text in (((), "record fields"), (("--ordered-on", "yesterday"), "expected YYYY-MM-DD"),
                            (("--source", "magic/buylists/missing.md"), "does not exist")):
            with self.subTest(flags=flags):
                code, _, err = self.run_cli("order", "record", OID, *flags, "-m", "Fix record")
                self.assertEqual(code, 1)
                self.assertIn(text, err)
                self.assertEqual(before, files.render(self.backend.load()))
        code, _, err = self.run_cli("order", "record", OID, "--seller", "Shop", "-m", " ")
        self.assertEqual(code, 1)
        self.assertIn("message", err)
        self.assertEqual(before, files.render(self.backend.load()))

    def test_sources_and_clear_sources_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit) as error, contextlib.redirect_stderr(io.StringIO()):
            self.run_cli("order", "record", OID, "--source", SOURCE, "--clear-sources", "-m", "Fix")
        self.assertEqual(error.exception.code, 2)

    def test_actor_is_forwarded_to_the_inventory_write(self):
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            code, _, err = self.run_cli("order", "record", OID, "--notes", "Reference 42", "--actor", "matt",
                                      "-m", "Correct details")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(apply.call_args.args[1].id, "matt")


if __name__ == "__main__":
    unittest.main()
