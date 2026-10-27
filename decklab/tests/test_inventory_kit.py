"""Tests for decklab/lib/inventory/kit.py: the product.set-kit operation that records an intact
product's sleeves and deck box. Its refusals are checked on snapshots built from status.csv
bytes (the operation only sees a snapshot, whichever backend gave it); its writes through
inventory.apply on both backends, the files one in a temp folder and the database one in a
throwaway database."""
import shutil
import tempfile
import unittest
from pathlib import Path

from decklab.lib import inventory
from decklab.lib.inventory import files
from decklab.lib.inventory import kit
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state import Actor
from decklab.tests import db_support

STATUS_HEADER = "file,status,intact,sleeves,deck_box,notes\n"
STATUS = (STATUS_HEADER + "alpha.csv,owned,yes,black,,\n" + "beta.csv,owned,yes,,,\n"
          + "gamma.csv,preordered,,,,\n")
PRODUCT = "deck,section,name,quantity,finish,set,collector_number\nRed,deck,Lightning Bolt,60,nonfoil,lea,161\n"
MATT = Actor("matt", "Matt", "home")


def snapshot(status):
    """A snapshot whose status.csv is status (bytes, text or an OSError; None: no file)."""
    tree = {}
    if status is not None:
        tree[files.paths.STATUS] = status.encode("utf-8") if isinstance(status, str) else status
    return files.build(tree)


def run(inv, **params):
    return inventory.Op(kit.KIND, params).run(inv)


class RefusalTests(unittest.TestCase):
    """The refusals, in the order and with the HTTP statuses the Accessories page answers with."""

    def refused(self, inv, **params):
        with self.assertRaises(kit.KitRefused) as caught:
            run(inv, **params)
        return caught.exception

    def test_each_refusal_has_its_status(self):
        good = snapshot(STATUS)
        sha = kit.status_sha256(good)
        move = [{"stem": "beta", "field": "sleeves", "value": "red"}]
        cases = (
            ("missing", snapshot(None), {"sha256": sha, "changes": move}, 404, None, "status.csv is missing"),
            ("unreadable", snapshot(OSError("locked")), {"sha256": sha, "changes": move}, 500, None, "locked"),
            ("changed", good, {"sha256": "0" * 64, "changes": move}, 409, "changed", "changed after"),
            ("strict", snapshot(STATUS_HEADER + "alpha.csv,owned,yes,,,,extra\n"), {"changes": move}, 409, None,
             "wrong number of columns"),
            ("no row", good, {"sha256": sha, "changes": [{"stem": "delta", "field": "sleeves", "value": "red"}]},
             404, None, "delta.csv isn't in products/status.csv"),
            ("not intact", good, {"sha256": sha, "changes": [{"stem": "gamma", "field": "sleeves", "value": "red"}],
                                  "hold": "gamma"}, 400, None, kit.CANT_HOLD),
        )
        for name, inv, params, code, reason, words in cases:
            with self.subTest(name):
                e = self.refused(inv, **params)
                self.assertEqual((e.code, e.reason), (code, reason))
                self.assertIn(words, str(e))
                self.assertIsInstance(e, inventory.Conflict)

    def test_the_order_of_the_checks(self):
        # A changed sha is reported before a strict read's complaint, and before a missing row.
        strict = snapshot(STATUS_HEADER + "alpha.csv,owned,yes,,,,extra\n")
        self.assertEqual(self.refused(strict, sha256="0" * 64, changes=[]).reason, "changed")
        e = self.refused(snapshot(STATUS), sha256="0" * 64,
                         changes=[{"stem": "delta", "field": "sleeves", "value": "red"}])
        self.assertEqual((e.code, e.reason), (409, "changed"))
        # Clearing works on a product that isn't intact; only the held one must be.
        stray = snapshot(STATUS_HEADER + "gamma.csv,preordered,,red,,\n")
        after, _ = run(stray, hold="gamma", changes=[{"stem": "gamma", "field": "sleeves", "value": None}])
        self.assertEqual(after.status.rows[0].text("sleeves"), "")

    def test_an_unknown_field_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            run(snapshot(STATUS), changes=[{"stem": "beta", "field": "playmat", "value": "x"}])


class ChangeTests(unittest.TestCase):
    """What the operation changes, on a snapshot."""

    def rows(self, inv):
        return [(r.text("file"), r.text("sleeves"), r.text("deck_box")) for r in inv.status.rows]

    def test_a_product_to_product_move(self):
        before = snapshot(STATUS)
        after, summary = run(before, sha256=kit.status_sha256(before), hold="beta", changes=[
            {"stem": "beta", "field": "sleeves", "value": "black"},
            {"stem": "alpha", "field": "sleeves", "value": None, "expect": "black"}])
        self.assertEqual(self.rows(after), [("alpha.csv", "", ""), ("beta.csv", "black", ""),
                                            ("gamma.csv", "", "")])
        self.assertEqual(summary.text, "Set the sleeves of beta, sleeves of alpha")

    def test_expect_skips_a_row_that_no_longer_holds_the_value(self):
        after, summary = run(snapshot(STATUS), hold="beta", changes=[
            {"stem": "beta", "field": "sleeves", "value": "red"},
            {"stem": "alpha", "field": "sleeves", "value": None, "expect": "red"}])
        self.assertEqual(self.rows(after)[:2], [("alpha.csv", "black", ""), ("beta.csv", "red", "")])
        self.assertEqual(summary.text, "Set the sleeves of beta")

    def test_nothing_to_change(self):
        before = snapshot(STATUS)
        after, summary = run(before, changes=[{"stem": "alpha", "field": "deck_box", "value": "x", "expect": "y"}])
        self.assertIs(after, before)
        self.assertEqual(summary.text, "Nothing to change")

    def test_a_hand_written_yes_holds(self):
        inv = snapshot(STATUS_HEADER + "alpha.csv, Owned ,Yes,,,\n")
        after, _ = run(inv, hold="alpha", changes=[{"stem": "alpha", "field": "deck_box", "value": "box"}])
        self.assertEqual(self.rows(after), [("alpha.csv", "", "box")])


class BackendCases:
    """The operation through inventory.apply on a backend (self.backend), from STATUS."""

    def status_rows(self):
        return [(r.text("file"), r.text("sleeves"), r.text("deck_box")) for r in self.backend.load().status.rows]

    def apply(self, message="move sleeves", **params):
        return self.backend.apply(inventory.Op(kit.KIND, params), MATT, message)

    def test_a_product_to_product_move(self):
        sha = kit.status_sha256(self.backend.load())
        self.apply(sha256=sha, hold="beta", changes=[
            {"stem": "beta", "field": "sleeves", "value": "black"},
            {"stem": "alpha", "field": "sleeves", "value": None, "expect": "black"}])
        self.assertEqual(self.status_rows(), [("alpha.csv", "", ""), ("beta.csv", "black", ""),
                                              ("gamma.csv", "", "")])

    def test_refusals_change_nothing(self):
        before = self.status_rows()
        for params, code in (({"sha256": "0" * 64, "changes": []}, 409),
                             ({"changes": [{"stem": "gamma", "field": "sleeves", "value": "red"}], "hold": "gamma"},
                              400),
                             ({"changes": [{"stem": "delta", "field": "sleeves", "value": "red"}]}, 404)):
            with self.subTest(code=code), self.assertRaises(kit.KitRefused) as caught:
                self.apply(**params)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.status_rows(), before)

    def test_nothing_to_change_writes_nothing(self):
        revision = self.backend.revision()
        _, summary = self.apply(changes=[{"stem": "alpha", "field": "sleeves", "value": None, "expect": "red"}])
        self.assertEqual(summary.text, "Nothing to change")
        self.assertEqual(self.backend.revision(), revision)


class FileBackendTests(BackendCases, unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        products = self.root / "magic" / "products"
        products.mkdir(parents=True)
        for stem in ("alpha", "beta", "gamma"):
            (products / f"{stem}.csv").write_text(PRODUCT, encoding="utf-8")
        (products / "status.csv").write_bytes(STATUS.encode("utf-8"))
        self.backend = FileInventory(self.root)

    def test_the_file_is_rendered_with_the_move(self):
        self.test_a_product_to_product_move()
        self.assertEqual((self.root / "magic/products/status.csv").read_text(encoding="utf-8"),
                         "file,status,intact,sleeves,deck_box,notes,token_cards\n"
                         "alpha.csv,owned,yes,,,,\nbeta.csv,owned,yes,black,,,\n"
                         "gamma.csv,preordered,,,,,\n")


class DatabaseBackendTests(BackendCases, db_support.DbTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        from decklab.tests.test_inventory_contract import FIXTURE_PROFILES
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        from decklab.tests.test_inventory_contract import CLAUDE, adapt
        FileBackendTests.setUp(self)
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(adapt(FileInventory(self.root).load()), CLAUDE, "Import the inventory", contents={},
                       dbname=self.dbname)
        shutil.rmtree(self.root / "magic")
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())

    def test_the_change_set_names_the_message(self):
        self.apply(message="set sleeves for beta", hold="beta",
                   changes=[{"stem": "beta", "field": "sleeves", "value": "red"}])
        with self.connect() as c:
            rows = c.execute("select cs.message, r.table_name from audit.change_set cs join audit.row_change r "
                             "on r.change_set_id = cs.id where cs.source = 'web'").fetchall()
        self.assertEqual(rows, [("set sleeves for beta", "product_status")])


if __name__ == "__main__":
    unittest.main()
