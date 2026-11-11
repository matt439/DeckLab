"""Exact loose-loan capacity is a conservative physical count, never a printing guess."""
from collections import Counter
from datetime import date
from types import SimpleNamespace
import unittest

from decklab.lib.inventory import loan_rules as loans


def row(**changes):
    return {"id": "a" * 32, "name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil",
            "quantity": "1", "borrower": "User1", "lent_on": "2026-11-11", "returned_on": "", "notes": "", **changes}


KEY = ("Llanowar Elves", "fdn", "227", "nonfoil")
OTHER = ("Llanowar Elves", "m19", "314", "nonfoil")


def holder(count, *, recorded=(), hinted=(), why="built", stale=()):
    return SimpleNamespace(cards=Counter({KEY[0]: count}), recorded=Counter(dict(recorded)),
                           printings=Counter(dict(hinted)), why=why, recorded_stale=list(stale), standin_warnings=[])


class LoanRulesTests(unittest.TestCase):
    def test_clean_record_is_exact_bounded_dated_and_preserves_card_name(self):
        self.assertEqual(loans.clean_row(row()), row())
        self.assertEqual(loans.clean_row(row(name="+2 Mace"))["name"], "+2 Mace")
        for change in ({"quantity": True}, {"quantity": 0}, {"quantity": 10000}, {"quantity": "01"}, {"borrower": ""},
                       {"borrower": "=formula"}, {"borrower": "User1\nUser2"}, {"notes": "x" * 501},
                       {"lent_on": "20261111"}, {"lent_on": "2026-02-30"}, {"returned_on": "2026-11-10"},
                       {"finish": "any"}, {"collector_number": ""}, {"id": "User1"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                loans.clean_row(row(**change))

    def test_open_counts_contain_no_borrower_or_note_and_closed_loans_reserve_nothing(self):
        self.assertEqual(loans.counts([row(quantity="2", notes="PRIVATE NOTE"),
                                       row(id="b" * 32, returned_on="2026-11-11")]), Counter({KEY: 2}))

    def test_unlocated_holds_use_worst_case_instead_of_trusting_recipe_printing_hints(self):
        owned = [row(quantity="3"), row(set="m19", collector_number="314", quantity="2")]
        unlocated = holder(2, hinted=[(OTHER, 2)])
        self.assertEqual(loans.physical_free(owned, [unlocated], [], KEY), 1)
        self.assertEqual(loans.physical_free(owned, [unlocated], [], OTHER), 0)
        self.assertEqual(loans.physical_free(owned, [unlocated], [row()], KEY), 0)

    def test_recorded_printings_and_intact_product_printings_prove_which_copies_are_held(self):
        owned = [row(quantity="3"), row(set="m19", collector_number="314", quantity="2")]
        for physical in (holder(2, recorded=[(OTHER, 2)]), holder(2, hinted=[(OTHER, 2)], why="intact product")):
            self.assertEqual(loans.physical_free(owned, [physical], [], KEY), 3)
            self.assertEqual(loans.physical_free(owned, [physical], [], OTHER), 0)

    def test_unconfirmed_stale_or_impossible_physical_records_refuse_capacity(self):
        for physical in (holder(1, stale=["PRIVATE SOURCE ERROR"]), holder(1, recorded=[(KEY, 2)]),
                         holder(2, recorded=[(OTHER, 2)])):
            with self.subTest(holder=physical), self.assertRaisesRegex(ValueError, "can't be confirmed"):
                loans.physical_free([row(quantity="3")], [physical], [], KEY)

    def test_duplicate_or_noncanonical_source_rows_are_reported_without_private_contents(self):
        problems = loans.problems([row(), row()], lambda number: f"Loan row {number}")
        self.assertEqual(problems, ["Loan row 2: the loan ID is repeated"])
        bad = loans.problems([row(borrower="PRIVATE\nBORROWER")], lambda number: f"Loan row {number}")
        self.assertNotIn("PRIVATE", str(bad))

    def test_database_snapshot_dates_optional_table_and_plain_export_roundtrip_without_a_database(self):
        from decklab.lib.inventory import files, pg_loans, pg_snapshot, table_rows
        from decklab.lib.state import Invalid
        from decklab.tests.test_inventory_pg_snapshot_module import rows
        data = rows()
        data["card_loan"] = [("home", "a" * 32, "Llanowar Elves", "fdn", "227", "nonfoil", 1, "User1",
                              date(2026, 11, 11), None, "PRIVATE NOTE")]
        data["loans_ready"] = True
        snapshot = pg_snapshot.snapshot(data, "loan-fixture")
        actual = snapshot.loan_set().rows[0].as_dict()
        self.assertEqual((actual["lent_on"], actual["returned_on"], actual["quantity"]), ("2026-11-11", "", "1"))
        self.assertEqual(files.build(files.render(snapshot)).loans, snapshot.loans)
        encoded = table_rows.tables(snapshot)
        self.assertEqual(encoded["card_loan"][("home", "a" * 32)],
                         ("Llanowar Elves", "fdn", "227", "nonfoil", 1, "User1", "2026-11-11", None, "PRIVATE NOTE"))
        with self.assertRaisesRegex(Invalid, "migration 0024"):
            pg_loans.compatible(encoded, False)
