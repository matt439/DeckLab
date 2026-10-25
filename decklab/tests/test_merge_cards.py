"""Card files merged into a collection validate everything before anything is written:
`python -m decklab.db collection merge` (decklab/db/inv_collection.py), which replaced
scripts/merge_cards.py, through the operation collection.import on a FileInventory over a
temporary tree. The card-name check against the card index is the CLI's own (tested in
test_collection_ops); here it's switched off, as these files name cards the fixture index lacks.
The real product lists are committed copies (fixtures/product_lists/, from the golden commit).

These tests never write the real inventory or mark real orders received.
"""
import argparse
import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.db import inv_collection
from decklab.lib import config, inventory
from decklab.lib.inventory import rules
from decklab.lib.inventory.files import FileInventory

PRODUCTS = Path(__file__).resolve().parent / "fixtures" / "product_lists"
REJECTED = (ValueError, inventory.StateError)


def card(**changes):
    row = dict(zip(rules.FIELDS, ["Llanowar Elves", "fdn", "227", "nonfoil", "2", "NM", "en", ""]))
    row.update(changes)
    return row


class MergeCardsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "magic").mkdir()
        self.collection = self.root / "magic" / "collection.csv"
        self.input = self.root / "incoming.csv"
        self.addCleanup(inventory.use(FileInventory(self.root)))
        patcher = mock.patch.object(inv_collection, "_check_names", lambda rows, where: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write(self.collection, [card()])

    def write(self, path, rows, fields=None):
        with path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fields or rules.FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def merge(self, *paths):
        output = io.StringIO()
        args = argparse.Namespace(files=[str(p) for p in paths or [self.input]], space="home",
                                  message="Merge test cards")
        with contextlib.redirect_stdout(output), inventory.pinned():
            self.assertEqual(inv_collection._merge(args), 0)
        return output.getvalue()

    def rows(self):
        with self.collection.open(newline="", encoding="utf-8-sig") as f:
            return rules.parse_cards(f, self.collection, existing=True)

    def assert_rejected_without_changes(self, error=""):
        before = self.collection.read_bytes() if self.collection.exists() else None
        with self.assertRaisesRegex(REJECTED, error):
            self.merge()
        self.assertEqual(self.collection.read_bytes() if self.collection.exists() else None, before)
        self.assertFalse((self.root / "magic" / "imports").exists())

    def test_merges_duplicate_incoming_identities_and_keeps_finishes_distinct(self):
        self.write(self.input, [card(quantity="1"), card(quantity="3"), card(finish="foil", quantity="1")])
        self.merge()
        rows = self.rows()
        self.assertEqual({r["finish"]: r["quantity"] for r in rows}, {"nonfoil": "6", "foil": "1"})
        self.assertEqual(rows, sorted(rows, key=rules.sort_key))

    def test_keeps_the_file_as_a_raw_import(self):
        self.write(self.input, [card(quantity="1")])
        data = self.input.read_bytes()
        output = self.merge()
        kept = sorted((self.root / "magic" / "imports").iterdir())
        self.assertEqual(len(kept), 1)
        self.assertRegex(kept[0].name, r"^\d{4}-\d{2}-\d{2}-incoming\.csv$")
        self.assertEqual(kept[0].read_bytes(), data)
        self.assertIn(f"Kept magic/imports/{kept[0].name}.", output)
        self.merge()                                    # the same file again: a second name
        self.assertEqual(len(list((self.root / "magic" / "imports").iterdir())), 2)

    def test_rejects_nonpositive_or_noninteger_quantities_before_any_write(self):
        for quantity in ("-3", "0", "1.5", "lots", "", "1_000"):
            with self.subTest(quantity=quantity):
                self.write(self.input, [card(quantity="1"), card(quantity=quantity)])
                self.assert_rejected_without_changes("positive integer")

    def test_rejects_missing_duplicate_unknown_or_misaligned_columns(self):
        header = ",".join(rules.FIELDS)
        valid = "Llanowar Elves,fdn,227,nonfoil,1,NM,en,"
        for text, message in (
                ("name,quantity\nLlanowar Elves,1\n", "missing columns"),
                (header + ",quantity\n" + valid + ",1\n", "duplicate column"),
                (header + ",unexpected\n" + valid + ",x\n", "unknown columns"),
                (header + "\n" + valid + ",extra\n", "wrong number"),
                (header + "\nLlanowar Elves,fdn,227,nonfoil,1\n", "wrong number")):
            with self.subTest(message=message):
                self.input.write_text(text, encoding="utf-8")
                self.assert_rejected_without_changes(message)

    def test_rejects_blank_or_invalid_identity_fields(self):
        for change in ({"name": ""}, {"name": " Llanowar Elves"}, {"set": "FDN"},
                       {"set": ""}, {"collector_number": ""}, {"collector_number": "227 extra"},
                       {"finish": "shiny"}):
            with self.subTest(change=change):
                self.write(self.input, [card(**change)])
                self.assert_rejected_without_changes()

    def test_rejects_name_conflict_without_losing_existing_stock(self):
        self.write(self.input, [card(name="Sol Ring")])
        self.assert_rejected_without_changes("not 'Sol Ring'")

    def test_later_invalid_input_does_not_publish_an_earlier_valid_merge(self):
        first = self.root / "first.csv"
        self.write(first, [card(quantity="1")])
        self.write(self.input, [card(quantity="-1")])
        before = self.collection.read_bytes()
        with self.assertRaisesRegex(REJECTED, "positive integer"):
            self.merge(first, self.input)
        self.assertEqual(self.collection.read_bytes(), before)

    def test_rejects_invalid_existing_inventory_instead_of_repairing_or_deleting_it(self):
        self.write(self.input, [card(quantity="1")])
        for rows in ([card(quantity="-1")], [card(quantity="0")], [card(), card()],
                     [card(collector_number="")]):
            with self.subTest(rows=rows):
                self.write(self.collection, rows)
                self.assert_rejected_without_changes("Fix it on the PC first")

    def test_skips_ordinary_basics_but_keeps_foil_etched_and_marked_special_basics(self):
        self.write(self.input, [
            card(name="Plains", collector_number="", quantity="32"),
            card(name="Swamp", collector_number="", quantity="33"),
            card(name="Forest", collector_number="279", quantity="10"),
            card(name="Plains", collector_number="272", finish="foil", quantity="1"),
            card(name="Island", collector_number="284", notes="full art", quantity="1"),
            card(name="Swamp", collector_number="286", notes="full-art", quantity="1"),
            card(name="Forest", collector_number="290", notes="special basic", quantity="1"),
            card(name="Mountain", collector_number="288", finish="etched", quantity="1"),
        ])
        output = self.merge()
        rows = self.rows()
        self.assertEqual(sum(int(r["quantity"]) for r in rows), 7)
        self.assertEqual(len(rows), 6)
        self.assertIn("75 ordinary basic lands omitted", output)
        self.assertTrue(all(r["collector_number"] for r in rows))

    def test_never_filters_existing_basics(self):
        self.write(self.collection, [card(name="Forest", collector_number="279", quantity="7")])
        self.write(self.input, [card(quantity="1")])
        self.merge()
        self.assertEqual({r["name"]: r["quantity"] for r in self.rows()}, {"Forest": "7", "Llanowar Elves": "1"})

    def test_already_tracked_special_basic_keeps_new_copies_without_repeated_notes(self):
        self.write(self.collection, [card(name="Plains", collector_number="282", notes="full art")])
        self.write(self.input, [card(name="Plains", collector_number="282", quantity="1"),
                                card(name="Plains", collector_number="272", quantity="10")])
        self.merge()
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["quantity"], rows[0]["notes"]), ("3", "full art"))

    def test_special_basics_need_printing_identity(self):
        for change in ({"finish": "foil"}, {"notes": "full art"}):
            with self.subTest(change=change):
                self.write(self.input, [card(name="Plains", collector_number="", **change)])
                self.assert_rejected_without_changes("no collector_number")

    def test_both_actual_commander_products_merge_without_basic_land_collision(self):
        self.collection.unlink()                       # a space with no cards yet
        output = self.merge(PRODUCTS / "fdc-calling-all-angels.csv", PRODUCTS / "fdc-wretched-ranks.csv")
        rows = self.rows()
        self.assertEqual(sum(int(r["quantity"]) for r in rows), 135)
        self.assertFalse(any(r["name"] in rules.BASIC_LANDS for r in rows))
        self.assertIn("65 ordinary basic lands omitted", output)
        # Shared printings (e.g. mana rocks) combine across product lists.
        self.assertEqual(len({rules.ident(r) for r in rows}), len(rows))

    def test_actual_starter_collection_retains_its_ten_full_art_basics(self):
        self.collection.unlink()
        self.merge(PRODUCTS / "fdn-starter-collection.csv")
        rows = self.rows()
        self.assertEqual(sum(int(r["quantity"]) for r in rows if r["name"] in rules.BASIC_LANDS), 10)

    def test_bom_and_optional_product_metadata_are_normalized(self):
        self.input.write_text("﻿section,name,set,collector_number,finish,quantity,rarity,notes\n"
                              "deck,Sol Ring,fdc,2,nonfoil,1,uncommon,keep this note\n", encoding="utf-8")
        self.merge()
        row = next(r for r in self.rows() if r["name"] == "Sol Ring")
        self.assertEqual((row["condition"], row["language"], row["notes"]), ("", "", "keep this note"))

    def test_unknown_condition_and_language_are_not_invented(self):
        self.write(self.input, [card(finish="foil", condition="", language="")])
        self.merge()
        row = next(r for r in self.rows() if r["finish"] == "foil")
        self.assertEqual((row["condition"], row["language"]), ("", ""))

    def test_mixed_copy_attributes_do_not_claim_all_copies_have_old_condition(self):
        self.write(self.input, [card(condition="", language="", quantity="1")])
        self.merge()
        row = self.rows()[0]
        self.assertEqual((row["quantity"], row["condition"], row["language"]), ("3", "", ""))
        self.assertIn("differing or unreported condition", row["notes"])

    def test_existing_identity_preserves_and_deduplicates_incoming_card_notes(self):
        self.write(self.collection, [card(notes="Original copy; signed by artist")])
        note = "signed by artist; new copy has corner wear"
        self.write(self.input, [card(condition="LP", language="", quantity="1", notes=note),
                                card(condition="LP", language="", quantity="1", notes=note)])
        self.merge()
        row = self.rows()[0]
        self.assertEqual(row["quantity"], "4")
        self.assertEqual(row["notes"], "Original copy; signed by artist; new copy has corner wear; "
                         "Merged copies have differing or unreported condition; "
                         "Merged copies have differing or unreported language")

    def test_note_deduplication_compares_whole_observations_not_substrings(self):
        self.write(self.collection, [card(notes="Unsigned copy")])
        self.write(self.input, [card(quantity="1", notes="signed copy")])
        self.merge()
        self.assertEqual(self.rows()[0]["notes"], "Unsigned copy; signed copy")

    def test_recorded_orders_and_products_are_refused_before_reading(self):
        for folder in ("magic/products", "magic/orders"):
            with self.subTest(folder=folder):
                with self.assertRaisesRegex(ValueError, "decklab.db receive"):
                    self.merge(Path(config.REPO) / folder / "never-read.csv")

if __name__ == "__main__":
    unittest.main()
