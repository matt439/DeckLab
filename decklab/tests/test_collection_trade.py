"""collection trade (E7-S22): the collection.trade operation on both inventory backends, and
`python -m decklab.db collection trade` in test_collection_edit's sandbox (User2's collection:
Elvish Mystic, 2 Llanowar Elves and Black Lotus). Both sides save as one change with a message
naming them and the who-with note, and a "Traded" reason; copies built decks hold are named and
refused without --allow-in-use; stale tables are named afterwards, as collection merge names them.

Run from the repo root: python -m unittest decklab.tests.test_collection_trade
(the database half skips without PostgreSQL; see db_support).
"""
import argparse
import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from decklab.db import collection_trade
from decklab.lib import inventory
from decklab.lib.inventory import Op, ops_collection as ops
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state import Invalid
from decklab.tests import db_support
from decklab.tests import test_collection_edit as tce
from decklab.tests.test_collection_ops import MATT, elves, write_tree
from decklab.tests.test_inventory_contract import CLAUDE, FIXTURE_PROFILES, import_contents


class TradeContract:
    """Run by both backends over test_collection_ops' tree (home: 2 Llanowar Elves, Black Lotus)."""

    def trade(self, gave, got, **params):
        return inventory.apply(Op("collection.trade", {"space": "home", "gave": gave, "got": got, **params}),
                               MATT, "trade", reason="Traded")

    def rows(self):
        return {(r["set"], r["collector_number"]): r for r in ops.rows_of(inventory.current().collection("home"))}

    def test_both_sides_in_one_change(self):
        sha = ops.sha256_of(inventory.current().collection("home"))
        got = [elves(set="m19", collector_number="314", quantity="3", condition="", language="")]
        _, summary = self.trade([["fdn", "227", "nonfoil", 1], ["lea", "232", "nonfoil", 1]], got, sha256=sha)
        self.assertEqual(summary.text, "trade in the home collection: gave 2 cards, got 3")
        self.assertEqual((summary.counts["gave"], summary.counts["removed"], summary.counts["added_rows"]), (2, 1, 1))
        rows = self.rows()
        self.assertEqual(set(rows), {("fdn", "227"), ("m19", "314")})
        self.assertEqual((rows["fdn", "227"]["quantity"], rows["m19", "314"]["quantity"]), ("1", "3"))

    def test_refusals_change_nothing(self):
        before = self.rows()
        got = [elves(set="m19", collector_number="314")]
        for gave, got_, error, words in (
                ([], got, Invalid, "needs both"),
                ([["fdn", "227", "nonfoil", 1]], [], Invalid, "needs both"),
                ([["fdn", "227", "nonfoil", 3]], got, Invalid, "has 2 copies, so 3 can't be given"),
                ([["fdn", "227", "nonfoil", 1]] * 2, got, Invalid, "given twice"),
                ([["fdn", "227", "nonfoil", 0]], got, Invalid, "positive whole number"),
                ([["fdn", "1", "nonfoil", 1]], got, ops.Missing, "isn't in the collection"),
                ([["fdn", "227", "nonfoil", 1]], [elves()], Invalid, "both given and got")):
            with self.subTest(gave=gave, got=got_), self.assertRaisesRegex(error, words):
                self.trade(gave, got_)
        with self.assertRaises(ops.Stale):
            self.trade([["fdn", "227", "nonfoil", 1]], got, sha256="0" * 64)
        self.assertEqual(self.rows(), before)


class FileTradeTests(TradeContract, unittest.TestCase):

    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        write_tree(root)
        self.addCleanup(inventory.use(FileInventory(root)))


class PgTradeTests(TradeContract, db_support.DbTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        write_tree(root)
        pg.write_model(FileInventory(root).load(), CLAUDE, "Import the test inventory",
                       contents=import_contents(root), dbname=self.dbname)
        self.addCleanup(inventory.use(pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())))

    def test_one_change_set_holds_both_sides_and_no_raw_import(self):
        with self.connect() as c:
            first = c.execute("select max(id) from audit.change_set").fetchone()[0]
            imports = c.execute("select count(*) from collection_import").fetchone()[0]
        self.trade([["lea", "232", "nonfoil", 1]], [elves(set="m19", collector_number="314")])
        with self.connect() as c:
            sets = c.execute("select id, message, reason from audit.change_set where id > %s", (first,)).fetchall()
            ops_ = c.execute("select table_name, op from audit.row_change where change_set_id = %s order by id",
                             (sets[0][0],)).fetchall()
            self.assertEqual(c.execute("select count(*) from collection_import").fetchone()[0], imports)
        self.assertEqual([(m, r) for _, m, r in sets], [("trade", "Traded")])
        self.assertEqual(sorted(ops_), [("collection_card", "DELETE"), ("collection_card", "INSERT")])

    def test_activity_undo_offers_no_partial_reversal_of_a_trade(self):
        # A trade lowers and adds rows in one change: neither the row Undo nor the import/receipt
        # Undo may reverse part of it (a trade's own Undo is later work in E7-S22).
        from decklab.lib.inventory import undo
        self.trade([["fdn", "227", "nonfoil", 1], ["lea", "232", "nonfoil", 1]],
                   [elves(set="m19", collector_number="314")])
        with self.connect() as c:
            change = c.execute("select max(id) from audit.change_set").fetchone()[0]
        for review in (inventory.undo_review, inventory.undo_mixed_review):
            with self.subTest(review=review.__name__), self.assertRaises((undo.UndoMissing, undo.UndoUnsupported, undo.UndoConflict)):
                review(change, "home")


class TradeCliTests(tce.CollectionEditTestCase):

    ROWS = (tce.HEADER + "Elvish Mystic,cmm,648,nonfoil,1,,,Reign of Dragons precon\n"
            "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\nBlack Lotus,lea,232,nonfoil,1,,,\n")

    def setUp(self):
        super().setUp()
        (self.box.magic / "people" / "user2" / "collection.csv").write_text(self.ROWS, encoding="utf-8",
                                                                              newline="")

    def file(self, text, name):
        path = self.box.root / name
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def run_trade(self, gave, got, *, code=0, message="Swap at the shop", **options):
        args = dict(space="user2", gave=str(self.file(gave, "out.csv")), got=str(self.file(got, "in.csv")),
                    with_=None, allow_in_use=False, dry_run=False, message=message)
        args.update(options)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), inventory.pinned():
            self.assertEqual(collection_trade.trade(argparse.Namespace(**args)), code)
        return out.getvalue() + err.getvalue()

    def by_key(self):
        return {(r["set"], r["collector_number"]): r for r in self.rows("user2")["rows"]}

    GAVE = "name,set,collector_number,finish,quantity\nLlanowar Elves,fdn,227,nonfoil,1\nBlack Lotus,lea,232,nonfoil,1\n"
    GOT = tce.HEADER + "Sol Ring,ecc,57,nonfoil,1,LP,ja,\nForest,fdn,280,nonfoil,4,,,\n"

    def test_a_trade_is_one_write_naming_both_sides(self):
        output = self.run_trade(self.GAVE, self.GOT, with_="User3")
        self.assertIn("Recorded the trade in User2's collection with User3: gave 2 cards, got 1.", output)
        self.assertIn("Gave 1 copy of Llanowar Elves (FDN 227, nonfoil): 2 -> 1", output)
        self.assertIn("Got 1 copy of Sol Ring (ECC 57, nonfoil)", output)
        self.assertIn("4 ordinary basic lands got aren't tracked", output)
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.last_write(), (
            "Swap at the shop. Trade with User3: gave 1 Llanowar Elves (FDN 227), 1 Black Lotus (LEA 232); "
            "got 1 Sol Ring (ECC 57)", "Claude"))
        self.assertEqual(self.reason(), "Traded with User3")
        rows = self.by_key()
        self.assertEqual((rows["fdn", "227"]["quantity"], ("lea", "232") in rows, rows["ecc", "57"]["condition"]),
                         ("1", False, "LP"))
        self.assertEqual(list((self.box.magic / "people" / "user2").glob("imports/*")), [])

    def test_a_dry_run_saves_nothing(self):
        output = self.run_trade(self.GAVE, self.GOT, dry_run=True)
        self.assertIn("Would record a trade in User2's collection: gave 2 cards, got 1.", output)
        self.assertIn("Nothing saved (--dry-run).", output)
        self.assertEqual((self.writes, self.by_key()["fdn", "227"]["quantity"]), ([], "2"))

    def test_cards_built_decks_hold_are_named_and_need_allow_in_use(self):
        path = self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        from decklab.tests.test_collection_ops import CollectionEditCliTests
        path.write_text(CollectionEditCliTests.BUILT, encoding="utf-8")
        output = self.run_trade(self.GAVE, self.GOT, dry_run=True)
        self.assertIn("In use: Llanowar Elves: 2 -> 1 copies, but 2 are held (2 in R Elves)", output)
        self.assertIn("Would leave 1 deck's owned-vs-needed table out of date: user2/casual/r-elves (R Elves).",
                      output)
        self.assertIn("Not saved: fewer copies would be left", self.run_trade(self.GAVE, self.GOT, code=1))
        self.assertEqual(self.writes, [])
        output = self.run_trade(self.GAVE, self.GOT, allow_in_use=True)
        self.assertIn("1 deck's owned-vs-needed table is now out of date: user2/casual/r-elves (R Elves).", output)
        self.assertEqual(self.by_key()["fdn", "227"]["quantity"], "1")

    def test_refusals(self):
        for gave, got, options, words in (
                (self.GAVE.replace(",1\nBlack", ",3\nBlack"), self.GOT, {}, "has 2 copies of Llanowar Elves .*, not 3"),
                (self.GAVE.replace(",1\nBlack", ",0\nBlack"), self.GOT, {}, "the copies given, at least 1"),
                (self.GAVE.replace("Black Lotus,lea", "Mox Pearl,lea"), self.GOT, {}, "'Black Lotus' in the "
                                                                                     "collection, not 'Mox Pearl'"),
                (self.GAVE + "Black Lotus,lea,232,nonfoil,1\n", self.GOT, {}, "listed twice"),
                (self.GAVE.replace("lea,232", "lea,233"), self.GOT, {}, "no LEA 233 nonfoil row"),
                ("name,set\n", self.GOT, {}, "needs the columns"),
                ("name,set,collector_number,finish,quantity\n", self.GOT, {}, "lists no cards"),
                (self.GAVE, tce.HEADER + "sol ring,ecc,57,nonfoil,1,,,\n", {}, "isn't a card's exact Scryfall name"),
                (self.GAVE, tce.HEADER + "Llanowar Elves,fdn,227,nonfoil,1,,,\n", {}, "both given and got"),
                (self.GAVE, self.GOT, {"with_": "two\nlines"}, "--with must be one line"),
                (self.GAVE, self.GOT, {"message": " "}, "-m needs a message")):
            with self.subTest(words=words), self.assertRaisesRegex(ValueError, words):
                self.run_trade(gave, got, **options)
        self.assertEqual(self.writes, [])

    def test_the_command_is_registered(self):
        from decklab.db import __main__ as cli
        args = cli.parser().parse_args(["collection", "trade", "--out", "a.csv", "--in", "b.csv", "--with", "User3",
                                        "-m", "Swap"])
        self.assertEqual((args.func, args.gave, args.got, args.with_, args.space),
                         (collection_trade.trade, "a.csv", "b.csv", "User3", "home"))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.parser().parse_args(["collection", "trade", "--out", "a.csv", "-m", "Swap"])     # --in


if __name__ == "__main__":
    unittest.main()
