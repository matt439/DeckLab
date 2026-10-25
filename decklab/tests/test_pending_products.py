"""Pending-product corrections on disposable file and PostgreSQL inventories.

Run: python -m unittest decklab.tests.test_pending_products
"""
import dataclasses
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import changes, files, product_ops, refresh
from decklab.lib.inventory.files import FileInventory
from decklab.lib.inventory.model import Order
from decklab.lib.state import Conflict, Invalid
from decklab.tests import db_support, test_inventory_contract as contract, test_pool
from decklab.tests import test_inventory_orders as fixture

STEM = "precon"
ORDER = "2026-10-02-precon"
COLUMNS = ["section", "deck", "name", "set", "collector_number", "finish", "quantity", "rarity", "notes"]
ROWS = [{"section": "Deck", "deck": "New deck", "name": "Sol Ring", "set": "ecc", "collector_number": "57",
         "finish": "nonfoil", "quantity": "3", "rarity": "uncommon", "notes": "Published correction"}]


def product_tree(tree):
    fixture.orders_tree(tree)
    tree.write("decks/casual/product-edit.md", test_pool.deck_md(
        "Product edit", "idea", "Deck\n2 Sol Ring (ECC) 57\n58 Forest\n",
        table="| Sol Ring | 2 | 0 | **2** | | | keep this note |\n"))


class ProductOps:
    start = fixture.OrderOps.start
    op = fixture.OrderOps.op
    load = fixture.OrderOps.load
    refused = fixture.OrderOps.refused

    def test_replacement_changes_names_and_counts_but_preserves_component_and_other_data(self):
        before = self.load()
        after, summary = self.op("product.edit", stem=STEM, columns=COLUMNS, rows=ROWS,
                                 values={"status": "ordered", "notes": "Release confirmed"})
        product = after.product(STEM)
        self.assertEqual(product.columns, tuple(COLUMNS))
        self.assertEqual([row.as_dict() for row in product.items], ROWS)
        status = next(row for row in after.status.rows if row.file == f"{STEM}.csv")
        self.assertEqual((status.status, status.notes), ("ordered", "Release confirmed"))
        self.assertEqual(after.order(ORDER), before.order(ORDER))
        self.assertEqual(after.collection(), before.collection())
        self.assertEqual(after.tokens, before.tokens)
        self.assertEqual(after.watchlist, before.watchlist)
        self.assertEqual(summary.counts, {"product": 3})
        self.assertIsNone(summary.extra["tables"]["error"])
        self.assertEqual(summary.extra["tables"]["written"], [{"id": "casual/product-edit", "title": "Product edit"}])
        self.assertNotEqual(after.deck("casual/product-edit").text, before.deck("casual/product-edit").text)
        self.assertIn("2 on the way", after.deck("casual/product-edit").text)
        self.assertIn("keep this note", after.deck("casual/product-edit").text)

    def test_preview_metadata_is_lossless_and_writes_nothing(self):
        before = self.load()
        product = before.product(STEM)
        op = inventory.Op("product.edit", {"stem": STEM, "values": {"name": "Correct display name",
                                                                      "format": "Commander"}})
        with mock.patch.object(product_ops, "check_card_rows", side_effect=AssertionError("no new list")):
            after, _ = inventory.preview(op)
        self.assertEqual((after.product(STEM).name, after.product(STEM).format),
                         ("Correct display name", "Commander"))
        self.assertEqual(after.product(STEM).items, product.items)
        self.assertEqual(after.status, before.status)
        self.assertEqual(files.render(self.load()), files.render(before))
        self.assertFalse(after.persisted)

    def test_name_only_correction_is_visible_in_preview_and_refreshes_product_labels(self):
        self.op("product.edit", stem=STEM, columns=COLUMNS, rows=ROWS)
        before = self.load()
        op = inventory.Op("product.edit", {"stem": STEM, "values": {"name": "Renamed precon"}})
        after, summary = inventory.preview(op)
        self.assertIn("magic/products/precon.csv", changes.changed_paths(before, after))
        self.assertIn("Product Renamed precon", changes.changed_labels(before, after))
        self.assertIsNone(summary.extra["tables"]["error"])
        self.assertEqual(summary.extra["tables"]["written"], [{"id": "casual/product-edit", "title": "Product edit"}])
        self.assertIn("Renamed precon", after.deck("casual/product-edit").text)
        self.assertNotIn("Renamed precon", before.deck("casual/product-edit").text)
        self.assertEqual(files.render(self.load()), files.render(before))

    def test_only_supplied_fields_change_and_empty_text_clears(self):
        before = self.load()
        after, _ = self.op("product.edit", stem=STEM, values={"notes": ""})
        self.assertEqual(after.product(STEM), before.product(STEM))
        old_status = next(row for row in before.status.rows if row.file == f"{STEM}.csv")
        new_status = next(row for row in after.status.rows if row.file == f"{STEM}.csv")
        self.assertEqual(new_status.as_dict(), old_status.as_dict() | {"notes": ""})
        custom = before.with_product(dataclasses.replace(before.product(STEM), name="Custom", format="Casual"))
        cleared, _ = inventory.Op("product.edit", {"stem": STEM, "values": {"name": "", "format": ""}}).run(custom)
        self.assertEqual((cleared.product(STEM).name, cleared.product(STEM).format), (None, None))

    def test_pending_guard_validation_and_no_mutation_on_refusal(self):
        self.refused("only a pending product", "product.edit", stem="fdn-beginner-box", values={"notes": "x"})
        self.refused("There's no product", "product.edit", stem="missing", values={"notes": "x"})
        self.refused("ordered or preordered", "product.edit", stem=STEM, values={"status": "owned"})
        self.refused("fields to correct", "product.edit", stem=STEM)
        self.refused("Set only", "product.edit", stem=STEM, values={"stem": "other"})
        self.refused("single-line text", "product.edit", stem=STEM, values={"name": "two\nlines"})
        self.refused("both columns and rows", "product.edit", stem=STEM, rows=ROWS)
        self.refused("each row needs exactly its columns", "product.edit", stem=STEM, columns=COLUMNS, rows=[])
        self.refused("duplicate column", "product.edit", stem=STEM, columns=COLUMNS + ["name"], rows=ROWS)
        self.refused("positive integer", "product.edit", stem=STEM, columns=COLUMNS,
                     rows=[ROWS[0] | {"quantity": "0"}])
        self.refused("not a card name", "product.edit", stem=STEM, columns=COLUMNS,
                     rows=[ROWS[0] | {"name": "Sol Rung"}])
        self.refused("unknown section", "product.edit", stem=STEM, columns=COLUMNS,
                     rows=[ROWS[0] | {"section": "odd section"}])
        for status in ("received", "cancelled"):
            with self.subTest(component_status=status):
                before = self.load()
                record = before.order(ORDER).record()
                record["components"][0]["status"] = status
                changed = before.with_order(Order(before.order(ORDER).file, record))
                with self.assertRaisesRegex(Invalid, "only a pending product"):
                    inventory.Op("product.edit", {"stem": STEM, "values": {"notes": "x"}}).run(changed)

    def test_stale_preview_is_refused_before_any_product_write(self):
        before = self.load()
        op = inventory.Op("product.edit", {"stem": STEM, "columns": COLUMNS, "rows": ROWS})
        inventory.preview(op)
        self.op("order.checks", order=ORDER, component=STEM, add="Inspect token pairing")
        latest = self.load()
        with self.assertRaises(Conflict):
            inventory.apply(op, fixture.CLAUDE, "Correct product", expected_revision=before.revision)
        self.assertEqual(self.load(), latest)

    def test_noop_does_not_refresh_tables_or_create_a_revision(self):
        before = self.load()
        with mock.patch.object(refresh, "plan_refresh", side_effect=AssertionError("no-op")):
            after, summary = self.op("product.edit", stem=STEM, values={"status": "preordered"})
        self.assertEqual(after.revision, before.revision)
        self.assertNotIn("tables", summary.extra or {})
        self.assertIn("nothing to change", summary.text)


class FileProductTests(ProductOps, unittest.TestCase):
    def setUp(self):
        case = contract.build_tree(product_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        self.backend = FileInventory(case.inventory.root)
        self.start(case)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class PgProductTests(ProductOps, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = contract.build_tree(product_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        pg.write_model(case.inventory.load(), fixture.CLAUDE, "Import", dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.start(case)

    def test_metadata_list_and_status_persist_as_one_audited_change(self):
        before = self.load()
        with self.connect() as c:
            count = c.execute("select count(*) from audit.change_set").fetchone()[0]
        values = {"name": "Correct product", "format": "Commander", "status": "ordered", "notes": "Corrected"}
        self.op("product.edit", stem=STEM, values=values, columns=COLUMNS, rows=ROWS)
        after = self.load()
        self.assertEqual((after.product(STEM).name, after.product(STEM).format), (values["name"], values["format"]))
        self.assertEqual(after.order(ORDER), before.order(ORDER))
        self.assertEqual(after.deck("casual/product-edit").revision, before.deck("casual/product-edit").revision + 1)
        with self.connect() as c:
            sets = c.execute("select id, message from audit.change_set order by id").fetchall()
            rows = c.execute("select table_name from audit.row_change where change_set_id = %s", (sets[-1][0],)).fetchall()
        self.assertEqual(len(sets), count + 1)
        self.assertEqual(sets[-1][1], "test product.edit")
        self.assertEqual({row[0] for row in rows},
                         {"product", "product_item", "product_status", "deck"})

    def test_name_only_correction_saves_label_and_table_together(self):
        self.op("product.edit", stem=STEM, columns=COLUMNS, rows=ROWS)
        before = self.load()
        self.op("product.edit", stem=STEM, values={"name": "Renamed precon"})
        after = self.load()
        self.assertEqual(after.product(STEM).name, "Renamed precon")
        self.assertEqual(after.product(STEM).items, before.product(STEM).items)
        self.assertIn("Renamed precon", after.deck("casual/product-edit").text)
        self.assertEqual(after.deck("casual/product-edit").revision, before.deck("casual/product-edit").revision + 1)


class ProductCommandTests(unittest.TestCase):
    setUp = fixture.CommandLineTests.setUp
    run_cli = fixture.CommandLineTests.run_cli
    file = fixture.CommandLineTests.file

    def test_dry_run_then_save_preserves_columns_and_refreshes_tables(self):
        before = self.backend.load()
        csv = self.file("product.csv", ",".join(COLUMNS) + "\n" + ",".join(ROWS[0][key] for key in COLUMNS) + "\n")
        args = ("product", "edit", STEM, "--csv", csv, "--status", "ordered", "--notes", "Confirmed", "-m", "Correct list")
        code, out, err = self.run_cli(*args, "--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Dry run: nothing saved", out)
        self.assertEqual(self.backend.load(), before)
        code, out, err = self.run_cli(*args)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Deck tables refreshed: Elves", out)
        product = self.backend.load().product(STEM)
        self.assertEqual((product.columns, [row.as_dict() for row in product.items]), (tuple(COLUMNS), ROWS))
        self.assertEqual(self.backend.load().order(ORDER), before.order(ORDER))

    def test_cli_validation_refuses_owned_and_empty_corrections(self):
        before = self.backend.load()
        for args in (("fdn-beginner-box", "--notes", "x"), (STEM,)):
            with self.subTest(args=args):
                code, _, err = self.run_cli("product", "edit", *args, "-m", "Correct")
                self.assertEqual(code, 1)
                self.assertTrue(err)
        self.assertEqual(self.backend.load(), before)
