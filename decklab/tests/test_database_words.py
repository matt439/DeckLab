"""Tests for E11-S12's database words: messages from database-backed readers and commands name the
inventory as the database holds it ("Row 2 of the home collection", "Product x's status",
"Order x's cards"), never an old file and line. HISTORY.md, "Database words in row problems and
product and order messages".

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_database_words
"""
import contextlib
import io
import json
import unittest
from unittest import mock

from decklab.lib import inventory, pool, purchases
from decklab.lib.api import guard, library, saving
from decklab.lib.inventory import files, paths
from decklab.lib.inventory.model import Order
from decklab.lib.state import Invalid
from decklab.tests import test_inventory_contract as contract, test_inventory_orders as orders_fixture
from decklab.tests.test_pool import PoolTestCase

CARD_HEADER = "name,set,collector_number,finish,quantity,condition,language,notes\n"
TOKEN_HEADER = "front,back,set,front_collector_number,back_collector_number,finish,quantity,front_details," \
               "back_details,notes\n"


class PathWordsTests(unittest.TestCase):
    """paths.describe, row_of, place and title: the one place the words come from."""

    def test_each_source_in_the_databases_words(self):
        for rel, words in [
                ("magic/collection.csv", "the home collection"),
                ("magic/people/user2/collection.csv", "user2's collection"),
                ("magic/tokens.csv", "the home token cards"),
                ("magic/people/user5/tokens.csv", "user5's token cards"),
                ("magic/people/user2/locations.csv", "user2's storage locations"),
                ("magic/watchlist.csv", "the purchase queue"),
                ("magic/products/status.csv", "the products' status list"),
                ("magic/products/fdc-wretched-ranks.csv", "product fdc-wretched-ranks's card list"),
                ("magic/orders/records/2026-10-07-shop-a.json", "order 2026-10-07-shop-a's record"),
                ("magic/orders/2026-10-07-shop-a.csv", "order 2026-10-07-shop-a's cards"),
                ("magic/orders/received/2026-10-07-shop-a.csv", "order 2026-10-07-shop-a's received cards"),
                ("magic/orders/tokens/2026-10-07-shop-a.csv", "order 2026-10-07-shop-a's token cards"),
                ("magic/orders/tokens/cancelled/x.csv", "order x's cancelled token cards"),
                ("magic/decks/casual/gruul-ramp.md", "casual/gruul-ramp"),
                ("magic/people/user2/decks/casual/elves.md", "user2/casual/elves")]:
            with self.subTest(rel):
                self.assertEqual(paths.describe(rel), words)
                self.assertNotIn(".csv", words)

    def test_a_file_the_user_handed_in_is_named_as_it_is(self):
        for rel in ("scratch/cards.csv", "C:/Users/someone/cards.csv", "casual/gruul-ramp", ""):
            self.assertEqual(paths.describe(rel), rel)

    def test_rows_titles_and_places(self):
        self.assertEqual(paths.row_of("magic/collection.csv", 2), "Row 2 of the home collection")
        self.assertEqual(paths.title("the products' status list"), "The products' status list")
        self.assertEqual(paths.place("magic/products/precon.csv"), "Product precon's card list")
        # A deck summary's source is its id (phase 5): kept as it is, never capitalised.
        self.assertEqual(paths.place("casual/broken"), "casual/broken")
        self.assertEqual(paths.place("user2/commander/lathliss"), "user2/commander/lathliss")

    def test_a_payload_is_named_by_the_order_and_component_holding_it(self):
        # A split's payload is x-additions.csv and a merge keeps the other order's file, so the
        # file name isn't its order's id: the record that names it says whose it is.
        split = "magic/orders/2026-10-12-mtgmate-additions.csv"
        merged = "magic/orders/tokens/received/2026-10-13-mtgmate.csv"
        record = Order.build("2026-10-12-mtgmate", components=[
            {"id": "cards", "kind": "cards", "path": "magic/orders/2026-10-12-mtgmate.csv"},
            {"id": "additions", "kind": "cards", "path": split},
            {"id": "tokens", "kind": "tokens", "path": merged},
            {"id": "kit", "kind": "product", "path": "magic/products/kit.csv"}])
        owners = paths.payload_owners([record])
        self.assertNotIn("magic/products/kit.csv", owners)
        self.assertEqual(paths.describe(split, owners), "order 2026-10-12-mtgmate's additions")
        self.assertEqual(paths.describe(merged, owners), "order 2026-10-12-mtgmate's received token cards")
        self.assertEqual(paths.row_of(split, 2, owners), "Row 2 of order 2026-10-12-mtgmate's additions")
        self.assertEqual(paths.place(split, owners), "Order 2026-10-12-mtgmate's additions")
        # No record names it (the "missing order record" warning): by its file's stem.
        self.assertEqual(paths.describe(split), "order 2026-10-12-mtgmate-additions's cards")
        self.assertEqual(paths.component_words("x", "tokens", "tokens", "cancelled"), "order x's cancelled token cards")


class SheetWordsTests(unittest.TestCase):
    """The snapshot's problems, as both backends give them (the database renders its rows and reads
    them back through files.build)."""

    def build(self, contents):
        return files.build({rel: text.encode("utf-8") for rel, text in contents.items()})

    def test_a_persons_collection_row_names_their_space_and_the_row(self):
        inv = self.build({"magic/people/user2/collection.csv": CARD_HEADER + "Opt,dom,60,nonfoil,1,,,\n"
                                                                             "Shock,m19,156,nonfoil,lots,,,\n"})
        sheet = inv.collection("user2")
        self.assertEqual(sheet.problems, ("Row 2 of user2's collection: bad quantity 'lots'",))
        self.assertTrue(sheet.strict_error.startswith("Row 2 of user2's collection: "), sheet.strict_error)

    def test_a_status_row_names_its_product(self):
        inv = self.build({"magic/products/status.csv": "file,status,intact,notes\nbox.csv,owned,maybe,\n"
                                                      ",owned,,\n"})
        self.assertEqual(inv.status.problems, ("Product box's status has intact 'maybe', not yes or no; treated as no",))
        self.assertEqual(files.status_owner(""), "A status row with no product")
        self.assertEqual(files.status_sheet(None).problems, (files.MISSING_STATUS,))

    def test_a_token_row_left_out_is_named_by_the_listed_row_before_it(self):
        # tokens list numbers only the rows it reads, so a row it leaves out can't have a number
        # of its own: naming it "Row 2" would point at a different card in the listing.
        inv = self.build({"magic/people/user5/tokens.csv": TOKEN_HEADER + "Dog,,,,,,1,,,\n,Beast,,,,,1,,,\n"
                                                                            "Elf,,,,,,1,,,\n"})
        sheet = inv.token_set("user5")
        self.assertEqual([r.text("front") for r in sheet.rows], ["Dog", "Elf"])
        self.assertEqual(sheet.problems, ("A row after row 1 of user5's token cards: tokens need a front name and "
                                          "positive physical quantity",))

    def test_an_order_payload_row_is_named_by_its_order(self):
        inv = self.build({"magic/orders/tokens/2026-10-07-shop-a.csv": TOKEN_HEADER + "Dog,,,,,shiny,1,,,\n",
                          "magic/orders/2026-10-07-shop-a.csv": CARD_HEADER + "Opt,dom,60,nonfoil,x,,,\n"})
        self.assertEqual(inv.payloads["magic/orders/tokens/2026-10-07-shop-a.csv"].strict_error,
                         "Row 1 of order 2026-10-07-shop-a's token cards: invalid token finish")
        self.assertEqual(inv.payloads["magic/orders/2026-10-07-shop-a.csv"].problems,
                         ("Row 1 of order 2026-10-07-shop-a's cards: bad quantity 'x'",))

    def test_a_split_off_payloads_rows_name_the_order_that_holds_them(self):
        split = "magic/orders/2026-10-07-shop-a-additions.csv"
        record = orders_fixture.record_json("2026-10-07-shop-a", "Shop", "2026-10-07", [
            orders_fixture.component("additions", "cards", split)])
        inv = self.build({split: CARD_HEADER + "Opt,dom,60,nonfoil,x,,,\n",
                          "magic/orders/records/2026-10-07-shop-a.json": record})
        self.assertEqual(inv.payloads[split].problems, ("Row 1 of order 2026-10-07-shop-a's additions: bad quantity 'x'",))
        self.assertEqual(inv.describe(split), "order 2026-10-07-shop-a's additions")


class PoolAndShoppingWordsTests(PoolTestCase):
    """The pool's and Shopping's messages, and who may read them (E10-S29's visible_warnings: home's
    orders and products only to home's record readers, whatever the words)."""

    def broken_home(self):
        self.cards_csv("orders/2026-09-29-x.csv", ("Opt", "dom", "60", "nonfoil", "lots"))
        self.write("products/kit.csv", "deck,name,set,collector_number,finish,quantity\nElves,Sol Ring,ecc,57,,1\n")
        self.status(("kit.csv", "owned", "yes"), ("typo.csv", "preorder", ""))

    def test_no_pool_warning_names_an_old_file(self):
        self.broken_home()
        warnings = pool.load_pool().warnings
        for expected in ("Row 1 of order 2026-09-29-x's cards: bad quantity 'lots'; that row isn't counted as on "
                         "the way",
                         "Product kit's card list can't be read: Row 1 of product kit's card list: bad finish ''",
                         "Product typo's status is 'preorder', not one of owned, preordered, ordered, cancelled; it "
                         "is left out of every count",
                         "Product typo has a status but no card list, so it isn't counted"):
            self.assertIn(expected, warnings)
        text = "\n".join(warnings)
        for old in ("magic/", ".csv", " line "):
            self.assertNotIn(old, text)

    def test_home_record_warnings_stay_home_only_in_their_new_words(self):
        self.broken_home()
        p = pool.load_pool()
        with mock.patch.object(guard, "deck_reader", lambda profile=False: (lambda d: False)), \
                mock.patch.object(guard, "sees_home_records", lambda profile=False: False):
            self.assertEqual(library.visible_warnings(p), [])        # a member sees none of them
        # The Tables out of date list's held spaces decide by a warning's first word (a deck id, or
        # home's records): none of the new words reads as a deck id.
        for text in p.warnings:
            self.assertFalse(saving._seen_warning(text, "home", lambda d: True, False), text)
            self.assertTrue(saving._seen_warning(text, "home", lambda d: False, True), text)
        with mock.patch.object(guard, "deck_reader", lambda profile=False: (lambda d: True)), \
                mock.patch.object(guard, "sees_home_records", lambda profile=False: True):
            self.assertEqual(library.visible_warnings(p), p.warnings)

    def test_unknown_card_places_go_by_path_for_privacy_and_show_in_words(self):
        # visible_place keeps home's orders and products from a member by their paths, so the pool
        # keeps an unknown card's place as the path it classifies by; only what's shown is reworded.
        self.cards_csv("orders/2026-09-29-x.csv", ("Grizly Bears", "dom", "60", "nonfoil", 1))
        p = pool.load_pool()
        self.assertEqual(p.unresolved, {"Grizly Bears": {"magic/orders/2026-09-29-x.csv"}})
        with mock.patch.object(guard, "sees_home_records", lambda profile=False: False):
            self.assertEqual(library.visible_unresolved(p.unresolved, sees=lambda d: True), {})
        # A reader who may see the place is told it in the database's words.
        self.assertEqual(library.visible_unresolved(p.unresolved, sees=lambda d: True, records=True),
                         {"Grizly Bears": ["order 2026-09-29-x's cards"]})

    def test_shopping_names_unrecorded_payloads_and_products_by_order_and_stem(self):
        self.cards_csv("orders/2026-09-29-x.csv", ("Opt", "dom", "60", "nonfoil", 1))
        (self.magic / "orders" / "tokens").mkdir(parents=True, exist_ok=True)
        self.write("orders/tokens/2026-09-30-y.csv", TOKEN_HEADER + "Dog,,,,,,1,,,single-sided verified\n")
        self.product("kit.csv", ("Elves", "Sol Ring", 1))
        self.status(("kit.csv", "owned", "no"))
        with inventory.pinned():
            records = purchases.read_records()
            warnings = purchases._coverage(records)
        self.assertEqual(warnings, ["Order 2026-09-29-x's cards: missing order record",
                                    "Order 2026-09-30-y's token cards: missing order record",
                                    "Product kit: missing order record"])
        with self.assertRaises(ValueError) as caught:
            purchases.overview()
        self.assertNotIn("magic/", str(caught.exception))
        self.assertNotIn("magic/", json.dumps(warnings))


class RefusalWordsTests(unittest.TestCase):
    """Refusals of order and product commands name products and orders, never their old files."""

    def setUp(self):
        case = contract.build_tree(orders_fixture.orders_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        stack = contextlib.ExitStack()
        stack.enter_context(contract.fixture_world())
        stack.enter_context(inventory.use(files.FileInventory(case.inventory.root)))
        self.addCleanup(stack.close)
        self.inv = inventory.current()

    def refused(self, inv, message, kind, **params):
        with self.assertRaises(Invalid) as caught:
            inventory.Op(kind, params).run(inv)
        self.assertEqual(str(caught.exception), message)
        for old in ("magic/", ".csv", ".json"):
            self.assertNotIn(old, str(caught.exception))

    def with_precon(self, **values):
        return self.inv.with_status_rows([row.replace(**values) if row.text("file") == "precon.csv" else row
                                          for row in self.inv.status.rows])

    def test_product_refusals_name_the_product(self):
        self.refused(self.with_precon(intact="yes"), "Product precon is kept intact; its order cannot be removed.",
                     "order.remove", order="2026-10-02-precon", reason="Wrong")
        owned = self.with_precon(status="owned")
        self.refused(owned, "Product precon is owned or not pending; its order cannot be removed or cancelled.",
                     "order.remove", order="2026-10-02-precon", reason="Wrong")
        self.refused(owned, "Product precon is owned; only a pending product can be corrected",
                     "product.edit", stem="precon", values={"name": "Renamed"})
        record = self.inv.order("2026-10-02-precon").record()
        record["id"] = "duplicate-product"
        self.refused(self.inv.with_order(Order("duplicate-product.json", record)),
                     "Product precon is referenced by another order component; correct its records first.",
                     "order.remove", order="2026-10-02-precon", reason="Wrong")

    def test_a_record_correction_names_the_order_and_component(self):
        self.refused(self.inv, "Order 2026-10-01-shop's cards: receipt date conflicts with status or order date",
                     "order.record", order="2026-10-01-shop", values={"ordered_on": "2026-10-05"}, repo=".")


class DatabaseDownTests(unittest.TestCase):
    """Criterion 3: with the database down, each inventory command exits 2 with one line saying so."""

    def test_each_inventory_read_exits_2_with_one_line(self):
        from decklab.db import __main__ as cli
        down = inventory.Unavailable("the database can't be reached")
        for argv in (["collection", "list"], ["tokens", "list"], ["order", "list"], ["watchlist", "list"],
                     ["deck", "list"], ["accessories", "list"], ["tokens", "check"], ["accessories", "check"]):
            with self.subTest(argv), mock.patch.object(inventory, "current", side_effect=down):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = cli.main(argv)
                self.assertEqual(code, 2, err.getvalue())
                self.assertEqual(err.getvalue().splitlines(),
                                 ["The database isn't available: the database can't be reached"])
                self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
