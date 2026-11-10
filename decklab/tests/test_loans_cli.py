"""Collection lend/return/loans use isolated snapshots and explicit audited writes."""
import argparse
import contextlib
import csv
import io
import json

from decklab.db import inv_collection
from decklab.lib import inventory, pool
from decklab.lib.inventory import files
from decklab.tests import test_pool as support

setUpModule = support.setUpModule
tearDownModule = support.tearDownModule


class LoanCliTests(support.PoolTestCase):
    def setUp(self):
        super().setUp()
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.parser = argparse.ArgumentParser()
        inv_collection.register(self.parser.add_subparsers())

    def command(self, *words):
        output, errors = io.StringIO(), io.StringIO()
        args = self.parser.parse_args(["collection", *words])
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), inventory.pinned():
            self.assertEqual(args.func(args), 0)
        return output.getvalue(), errors.getvalue()

    def test_explicit_dry_run_then_lend_list_return_leave_collection_bytes_unchanged(self):
        before = files.render(self.inventory.load())
        options = ("lend", "FDN", "227", "nonfoil", "2", "--borrower", "User1", "--date", "2026-11-11", "-m", "Lend fixture copies")
        output, _ = self.command(*options, "--dry-run")
        self.assertIn("Would: Lent 2 Llanowar Elves", output)
        self.assertEqual(files.render(self.inventory.load()), before)
        self.command(*options)
        output, notice = self.command("loans", "--json")
        self.assertIn("private to that space", notice)
        loan = json.loads(output)[0]
        self.assertEqual((loan["borrower"], loan["quantity"]), ("User1", "2"))
        self.assertEqual(files.render_sheet(self.inventory.load().collection()), before["magic/collection.csv"])
        output, _ = self.command("return", loan["id"], "--date", "2026-11-12", "-m", "Returned fixture copies")
        self.assertIn("Returned 2 Llanowar Elves", output)
        output, _ = self.command("loans")
        self.assertEqual(list(csv.DictReader(io.StringIO(output))), [])
        output, _ = self.command("loans", "--all", "--json")
        self.assertEqual(json.loads(output)[0]["returned_on"], "2026-11-12")
        self.assertEqual(pool.free_copies(pool.load_pool())["Llanowar Elves"], 4)

    def test_refused_capacity_and_blank_audit_message_do_not_create_any_loan(self):
        before = files.render(self.inventory.load())
        for quantity, message, problem in (("5", "Too many fixture copies", "confirmed free"), ("1", "  ", "needs a message")):
            with self.subTest(quantity=quantity), self.assertRaisesRegex((ValueError, inventory.Invalid), problem):
                self.command("lend", "fdn", "227", "nonfoil", quantity, "--borrower", "User1", "--date", "2026-11-11", "-m", message)
            self.assertEqual(files.render(self.inventory.load()), before)
