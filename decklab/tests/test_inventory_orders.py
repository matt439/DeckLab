"""The orders, products and watchlist operations (decklab/lib/inventory/orders.py) on both
inventory backends, and their command lines (decklab/db/inv_orders.py).

Every operation test runs twice: on the files backend over a temp magic/ tree, and on the
database backend with the same tree imported into a throwaway database (skipped without one:
db_support.py). A last test runs one sequence of operations on both and compares the files each
would leave, byte for byte. The command-line tests run on the files backend, with the deck-table
refresh (inventory/refresh.py, another area's) replaced by a fake, and once more in git mode
(production's backend until the cutover): the commits, a reason in the commit's body, and
outside edits refused.

Run from the repo root: python -m unittest decklab.tests.test_inventory_orders
"""
import contextlib
import dataclasses
import io
import json
import unittest
from unittest import mock

from decklab.lib import cards as card_index
from decklab.lib import inventory
from decklab.lib.inventory import files, orders, refresh, rules
from decklab.lib.inventory.files import FileInventory
from decklab.lib.inventory.model import QUEUE_FIELDS
from decklab.lib.state import Actor, Invalid
from decklab.tests import db_support, test_inventory_contract as contract

CLAUDE = Actor("claude", "Claude", None, "cli")
CARD_HEADER = ",".join(rules.FIELDS) + "\n"
TOKEN_HEADER = ",".join(rules.TOKEN_FIELDS) + "\n"
STATUS_HEADER = ",".join(rules.STATUS_FIELDS) + "\n"
WATCH_HEADER = ",".join(QUEUE_FIELDS) + "\n"
PRODUCT_COLUMNS = ["deck", "name", "set", "collector_number", "finish", "quantity", "rarity", "notes"]


def record_json(order_id, seller, ordered_on, components):
    return rules.json_bytes({"version": 1, "id": order_id, "seller": seller, "ordered_on": ordered_on,
                             "sources": [], "notes": "", "components": components}).decode("utf-8")


def component(cid, kind, path, status="pending", received_on="", checks=()):
    return {"id": cid, "kind": kind, "path": path, "status": status, "received_on": received_on,
            "checks": list(checks)}


def orders_tree(t):
    """A home with a received Beginner Box kept intact, a preordered precon, a pending order with
    cards (two checks) and tokens, a received order, and a watchlist."""
    t.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
    t.product("fdn-beginner-box.csv", ("Elves", "Llanowar Elves", 1))
    t.product("precon.csv", ("Main", "Elvish Mystic", 1), column="section")
    t.write("products/status.csv", STATUS_HEADER + "fdn-beginner-box.csv,owned,yes,black-sleeves,shared-box,\n"
                                                   "precon.csv,preordered,,,,due soon\n")
    t.write("orders/records/product-fdn-beginner-box.json", record_json(
        "product-fdn-beginner-box", "", "", [component("product-fdn-beginner-box", "product",
                                                       "magic/products/fdn-beginner-box.csv", "received")]))
    t.write("orders/records/2026-10-02-precon.json", record_json(
        "2026-10-02-precon", "Shop", "2026-10-02", [component("precon", "product", "magic/products/precon.csv")]))
    t.write("orders/2026-10-07-shop-a.csv", CARD_HEADER + "Elvish Mystic,cmm,648,nonfoil,2,,,\n"
                                                           "Pick Your Poison,mkm,170,nonfoil,1,,,check language\n")
    t.write("orders/tokens/2026-10-07-shop-a.csv", TOKEN_HEADER + "Llanowar Elves,,,,,,2,1/1; green,,\n")
    t.write("orders/records/2026-10-07-shop-a.json", record_json("2026-10-07-shop-a", "MTGMate", "2026-10-07", [
        component("cards", "cards", "magic/orders/2026-10-07-shop-a.csv",
                  checks=["Record conditions", "Check languages"]),
        component("tokens", "tokens", "magic/orders/tokens/2026-10-07-shop-a.csv")]))
    t.write("orders/received/2026-10-01-shop.csv", CARD_HEADER + "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\n")
    t.write("orders/records/2026-10-01-shop.json", record_json("2026-10-01-shop", "Shop", "2026-10-01", [
        component("cards", "cards", "magic/orders/received/2026-10-01-shop.csv", "received", "2026-10-03",
                  ["Photograph the cards"])]))
    t.write("watchlist.csv", WATCH_HEADER
            + "Elvish Mystic,,,,3,Elves,any,,,,,,ready,\n"
              "Pick Your Poison,mkm,170,nonfoil,1,Cats,exact,0.50,MTGMate,yes,2026-10-05,,ready,\n"
              "Sol Ring,,,,1,Commander,any,,,,,,long_term,\n"
              "Sol Ring,,,,1,Other deck,any,,,,,,deferred,\n")
    (t.magic / "buylists").mkdir(exist_ok=True)
    t.write("buylists/2026-10-12-plan.md", "# Plan\n")


def card(name, set_code, number, qty, finish="nonfoil", condition="", language="", notes=""):
    return {"name": name, "set": set_code, "collector_number": number, "finish": finish, "quantity": str(qty),
            "condition": condition, "language": language, "notes": notes}


def token(front, qty, back="", details="", notes=""):
    row = {k: "" for k in rules.TOKEN_FIELDS}
    row.update({"front": front, "back": back, "quantity": str(qty), "front_details": details, "notes": notes})
    return row


def product_rows(*rows):
    return [dict(zip(PRODUCT_COLUMNS, (deck, name, s, n, "nonfoil", str(q), "common", "")))
            for deck, name, s, n, q in rows]


class OrderOps:
    """The operation tests; a subclass gives the backend (setUp sets self.backend, self.root)."""

    def start(self, case):
        """Common set-up once the subclass has its tree (case) and backend."""
        self.root = case.inventory.root
        stack = contextlib.ExitStack()
        stack.enter_context(contract.fixture_world())
        stack.enter_context(inventory.use(self.backend))
        self.addCleanup(stack.close)

    def op(self, kind, **params):
        return inventory.apply(inventory.Op(kind, params), CLAUDE, f"test {kind}")

    def load(self):
        return self.backend.load()

    def refused(self, text, kind, **params):
        before = self.load()
        with self.assertRaisesRegex(Invalid, text):
            self.op(kind, **params)
        self.assertEqual(files.render(self.load()), files.render(before))

    def queue(self):
        return [{k: r.text(k) for k in QUEUE_FIELDS} for r in self.load().watchlist.rows]

    def add_params(self, **changes):
        params = {"record": {"id": "2026-10-12-goodgames", "seller": "Good Games", "ordered_on": "2026-10-12",
                             "sources": ["magic/buylists/2026-10-12-plan.md"], "notes": "shop order 1"},
                  "cards": {"rows": [card("Elvish Mystic", "cmm", 648, 2), card("Pick Your Poison", "mkm", 170, 1)],
                            "checks": ["Record conditions"]},
                  "repo": str(self.root)}
        params.update(changes)
        return params

    # -------------------------------------------------------- order.add

    def test_adding_an_order_records_everything_in_one_change(self):
        params = self.add_params(
            tokens={"rows": [token("Llanowar Elves", 1, notes="single-sided verified")]},
            product={"stem": "alpha-deck", "columns": PRODUCT_COLUMNS, "name": "Alpha Deck", "format": "Casual",
                     "rows": product_rows(("Elves", "Llanowar Elves", "fdn", "227", 2)), "notes": "preorder"},
            fulfils=[{"select": "Elvish Mystic", "quantity": 2}, {"select": "Pick Your Poison", "quantity": None}])
        before = self.load()
        after, summary = self.op("order.add", **params)
        self.assertNotEqual(after.revision, before.revision)
        self.assertEqual(summary.counts, {"cards": 3, "tokens": 1, "product": 2, "watchlist_reduced": 3})
        order = after.order("2026-10-12-goodgames")
        self.assertEqual(list(order.data), ["version", "id", "seller", "ordered_on", "sources", "notes",
                                            "components", "audit_notes"])
        from decklab.lib.inventory import order_fulfilment
        self.assertIsNotNone(order_fulfilment.read(order))
        self.assertEqual(order.data["sources"], ["magic/buylists/2026-10-12-plan.md"])
        self.assertEqual([c.record() for c in order.components], [
            component("cards", "cards", "magic/orders/2026-10-12-goodgames.csv", checks=["Record conditions"]),
            component("tokens", "tokens", "magic/orders/tokens/2026-10-12-goodgames.csv"),
            component("alpha-deck", "product", "magic/products/alpha-deck.csv")])
        rendered = files.render(after)
        self.assertEqual(rendered["magic/orders/2026-10-12-goodgames.csv"].decode(),
                         CARD_HEADER + "Elvish Mystic,cmm,648,nonfoil,2,,,\nPick Your Poison,mkm,170,nonfoil,1,,,\n")
        self.assertEqual(rendered["magic/products/alpha-deck.csv"].decode(),
                         ",".join(PRODUCT_COLUMNS) + "\nElves,Llanowar Elves,fdn,227,nonfoil,2,common,\n")
        self.assertEqual([r.text("file") for r in after.status.rows],
                         ["alpha-deck.csv", "fdn-beginner-box.csv", "precon.csv"])
        self.assertEqual(after.status.rows[0].as_dict(), {"file": "alpha-deck.csv", "status": "ordered",
                                                          "intact": "", "sleeves": "", "deck_box": "",
                                                          "notes": "preorder"})
        queue = self.queue()
        self.assertEqual([(r["name"], r["quantity"]) for r in queue],
                         [("Elvish Mystic", "1"), ("Sol Ring", "1"), ("Sol Ring", "1")])
        self.assertEqual(orders.pairing_problems(after), [])
        if after.backend == "db":
            self.assertEqual(after.product("alpha-deck").name, "Alpha Deck")

    def test_adding_an_order_refuses_what_shopping_would(self):
        self.refused("already exists", "order.add", **self.add_params(record={"id": "2026-10-07-shop-a"}))
        self.refused("invalid order id", "order.add", **self.add_params(record={"id": "Bad Id"}))
        self.refused("ordered_on: expected YYYY-MM-DD", "order.add",
                     **self.add_params(record={"id": "2026-10-12-x", "ordered_on": "12/10/2026"}))
        self.refused("seller: expected single-line text", "order.add",
                     **self.add_params(record={"id": "2026-10-12-x", "seller": "two\nlines"}))
        self.refused("source magic/buylists/missing.md does not exist", "order.add",
                     **self.add_params(record={"id": "2026-10-12-x", "sources": ["magic/buylists/missing.md"]}))
        self.refused("order needs components", "order.add", **self.add_params(cards=None))
        self.refused("not a card name", "order.add",
                     **self.add_params(cards={"rows": [card("Elvish Mystik", "cmm", 648, 1)]}))
        self.refused("printing does not match", "order.add",
                     **self.add_params(cards={"rows": [card("Elvish Mystic", "mkm", 170, 1)]}))
        self.refused("finish is not available", "order.add",
                     **self.add_params(cards={"rows": [card("Pick Your Poison", "mkm", 170, 1, "etched")]}))
        self.refused("quantity must be a positive integer", "order.add",
                     **self.add_params(cards={"rows": [card("Elvish Mystic", "cmm", 648, 0)]}))
        self.refused("tokens need a front name", "order.add", **self.add_params(tokens={"rows": [token("", 1)]}))
        self.refused("isn't a token, emblem or reminder name", "order.add",
                     **self.add_params(tokens={"rows": [token("Goblin Kin", 1)]}))
        self.refused("exact printing", "order.add",
                     **self.add_params(cards={"rows": [card("Pick Your Poison", "mkm", 170, 1, "foil")]},
                                       fulfils=[{"select": "Pick Your Poison", "quantity": 1}]))
        self.refused("more than one watchlist row", "order.add",
                     **self.add_params(cards={"rows": [card("Sol Ring", "ecc", 57, 1)]},
                                       fulfils=[{"select": "Sol Ring", "quantity": 1}]))
        self.refused("the order has 2 of it, not 3", "order.add",
                     **self.add_params(fulfils=[{"select": "Elvish Mystic", "quantity": 3}]))
        self.refused("No watchlist row matches", "order.add",
                     **self.add_params(fulfils=[{"select": "Elvish Mystic@Goblins", "quantity": 1}]))
        self.refused("is already a product", "order.add", **self.add_params(
            product={"stem": "precon", "columns": PRODUCT_COLUMNS,
                     "rows": product_rows(("Main", "Sol Ring", "ecc", "57", 1))}))
        self.refused("a new product is ordered or preordered", "order.add", **self.add_params(
            product={"stem": "beta", "columns": PRODUCT_COLUMNS, "status": "owned",
                     "rows": product_rows(("Main", "Sol Ring", "ecc", "57", 1))}))

    def test_names_are_checked_even_without_the_printing_checks(self):
        self.refused("Sol Rung: not a card name", "order.add", check_cards=False,
                     **self.add_params(cards={"rows": [card("Sol Rung", "ecc", 57, 1)]}))
        after, _ = self.op("order.add", check_cards=False,
                           **self.add_params(cards={"rows": [card("Sol Ring", "mkm", 170, 1, "etched")]}))
        self.assertIn("magic/orders/2026-10-12-goodgames.csv", after.payloads)

    def test_without_a_card_index_only_no_check_records_unchecked(self):
        with mock.patch.object(card_index, "INDEX_FILE", self.root / "missing.json.gz"), \
                mock.patch.object(card_index, "_index", None):
            self.refused("The card index isn't built", "order.add", **self.add_params())
            _, summary = self.op("order.add", check_cards=False, **self.add_params(
                cards={"rows": [card("Sol Rung", "ecc", 57, 1)]}))
        self.assertEqual(summary.extra["warnings"], [orders.NAMES_UNCHECKED])

    def test_fulfilling_by_row_number_and_for(self):
        params = self.add_params(cards={"rows": [card("Sol Ring", "ecc", 57, 2)]},
                                 fulfils=[{"select": "Sol Ring@Other deck", "quantity": 1},
                                          {"select": "#3", "quantity": None}])
        self.op("order.add", **params)
        self.assertEqual([r["name"] for r in self.queue()], ["Elvish Mystic", "Pick Your Poison"])

    # -------------------------------------------------------- order.edit

    def test_editing_a_pending_component(self):
        rows = [card("Pick Your Poison", "mkm", 170, 1, condition="NM", language="en"),
                card("Elvish Mystic", "cmm", 648, 2, "foil", "LP", "en")]
        after, _ = self.op("order.edit", order="2026-10-07-shop-a", component="cards", rows=rows)
        self.assertEqual(files.render(after)["magic/orders/2026-10-07-shop-a.csv"].decode(),
                         CARD_HEADER + "Elvish Mystic,cmm,648,foil,2,LP,en,\n"
                                       "Pick Your Poison,mkm,170,nonfoil,1,NM,en,\n")
        self.refused("Receive a whole component", "order.edit", order="2026-10-07-shop-a", component="cards",
                     rows=[card("Elvish Mystic", "cmm", 648, 1), card("Pick Your Poison", "mkm", 170, 1)])
        self.refused("Card names and total copies must match", "order.edit", order="2026-10-07-shop-a",
                     component="cards", rows=[card("Elvish Mystic", "cmm", 648, 3)])
        self.refused("printing does not match", "order.edit", order="2026-10-07-shop-a", component="cards",
                     rows=[card("Elvish Mystic", "mkm", 170, 2), card("Pick Your Poison", "mkm", 170, 1)])
        self.refused("exactly the component's CSV fields", "order.edit", order="2026-10-07-shop-a",
                     component="cards", rows=[{"name": "Elvish Mystic", "quantity": "3"}])
        self.refused("already received", "order.edit", order="2026-10-01-shop", component="cards",
                     rows=[card("Llanowar Elves", "fdn", 227, 2)])
        self.refused("is a product", "order.edit", order="2026-10-02-precon", component="precon", rows=[])
        after, _ = self.op("order.edit", order="2026-10-07-shop-a", component="tokens",
                           rows=[token("Llanowar Elves", 2, details="1/1; green", notes="single-sided verified")])
        self.assertIn(b"single-sided verified", files.render(after)["magic/orders/tokens/2026-10-07-shop-a.csv"])

    # -------------------------------------------------------- order.checks

    def test_checks_are_added_resolved_and_cleared(self):
        after, _ = self.op("order.checks", order="2026-10-07-shop-a", component="tokens", add="Verify the back")
        self.assertEqual(after.order("2026-10-07-shop-a").components[1].checks, ["Verify the back"])
        # A pending component's checks are verified at its receipt, never resolved before it.
        self.refused(r"hasn't arrived yet: its checks are verified when it's received \(receive --verified cards\)",
                     "order.checks", order="2026-10-07-shop-a", component="cards", resolve=2)
        self.refused("hasn't arrived yet", "order.checks", order="2026-10-07-shop-a", component="cards", clear=True)
        after, _ = self.op("order.checks", order="2026-10-07-shop-a", component="cards", withdraw=2)
        cards_part = after.order("2026-10-07-shop-a").components[0]
        self.assertEqual((cards_part.checks, cards_part.verified_checks), (["Record conditions"], None))
        after, _ = self.op("order.checks", order="2026-10-01-shop", component="cards", resolve=1)
        shop = after.order("2026-10-01-shop").components[0]
        self.assertEqual((shop.checks, shop.verified_checks), ([], ["Photograph the cards"]))
        self.assertEqual(list(shop.data)[-1], "verified_checks")
        self.op("order.checks", order="2026-10-01-shop", component="cards", add="Sleeve them")
        self.op("order.checks", order="2026-10-01-shop", component="cards", add="Count them")
        after, _ = self.op("order.checks", order="2026-10-01-shop", component="cards", clear=True)
        shop = after.order("2026-10-01-shop").components[0]
        self.assertEqual((shop.checks, shop.verified_checks),
                         ([], ["Photograph the cards", "Sleeve them", "Count them"]))
        self.refused("has no check 3", "order.checks", order="2026-10-07-shop-a", component="tokens", withdraw=3)
        self.refused("has no checks", "order.checks", order="2026-10-01-shop", component="cards", clear=True)
        self.refused("must not be blank", "order.checks", order="2026-10-07-shop-a", component="cards", add=" ")
        self.refused("Give one of", "order.checks", order="2026-10-07-shop-a", component="cards")
        self.refused("no component", "order.checks", order="2026-10-07-shop-a", component="nope", add="x")

    # -------------------------------------------------------- order.split

    def test_splitting_a_component_keeps_the_totals(self):
        after, summary = self.op("order.split", order="2026-10-07-shop-a", component="cards", new_id="late",
                                 take=[{"row": 1, "quantity": 1}, {"row": 2, "quantity": None}],
                                 move_checks=[2], copy_checks=[1])
        self.assertEqual(summary.extra["file_name"], "2026-10-07-shop-a-late.csv")
        parts = after.order("2026-10-07-shop-a").components
        self.assertEqual([(c.id, c.path, c.checks) for c in parts], [
            ("cards", "magic/orders/2026-10-07-shop-a.csv", ["Record conditions"]),
            ("late", "magic/orders/2026-10-07-shop-a-late.csv", ["Record conditions", "Check languages"]),
            ("tokens", "magic/orders/tokens/2026-10-07-shop-a.csv", [])])
        rendered = files.render(after)
        self.assertEqual(rendered["magic/orders/2026-10-07-shop-a.csv"].decode(),
                         CARD_HEADER + "Elvish Mystic,cmm,648,nonfoil,1,,,\n")
        self.assertEqual(rendered["magic/orders/2026-10-07-shop-a-late.csv"].decode(),
                         CARD_HEADER + "Elvish Mystic,cmm,648,nonfoil,1,,,\n"
                                       "Pick Your Poison,mkm,170,nonfoil,1,,,check language\n")
        self.assertEqual(orders.pairing_problems(after), [])
        after, _ = self.op("order.split", order="2026-10-07-shop-a", component="late", new_id="later",
                           take=[{"row": 1, "quantity": 1}], keep_checks=[2])
        parts = after.order("2026-10-07-shop-a").components
        self.assertEqual([(c.id, c.checks) for c in parts[1:3]], [
            ("late", ["Record conditions", "Check languages"]), ("later", ["Record conditions"])])
        self.refused("Nothing would be left", "order.split", order="2026-10-07-shop-a", component="cards",
                     new_id="all", take=[{"row": 1}])
        self.refused("invalid or repeated component id", "order.split", order="2026-10-07-shop-a",
                     component="cards", new_id="late", take=[{"row": 1, "quantity": 1}])
        self.refused("has no row 5", "order.split", order="2026-10-07-shop-a", component="tokens",
                     new_id="more", take=[{"row": 5, "quantity": 1}])
        self.refused("has 2, not 3", "order.split", order="2026-10-07-shop-a", component="tokens",
                     new_id="more", take=[{"row": 1, "quantity": 3}])
        self.refused("is a product", "order.split", order="2026-10-02-precon", component="precon",
                     new_id="half", take=[{"row": 1, "quantity": 1}])

    # -------------------------------------------------------- order.cancel

    def test_cancelling_a_component(self):
        after, _ = self.op("order.cancel", order="2026-10-07-shop-a", component="tokens",
                           reason="Out of stock; refunded")
        self.assertEqual(after.order("2026-10-07-shop-a").audit_notes,
                         "Component tokens cancelled: Out of stock; refunded.")
        self.assertEqual(list(after.order("2026-10-07-shop-a").data)[-1], "audit_notes")
        part = after.order("2026-10-07-shop-a").components[1]
        self.assertEqual((part.status, part.path, part.received_on),
                         ("cancelled", "magic/orders/tokens/cancelled/2026-10-07-shop-a.csv", ""))
        self.assertIn("magic/orders/tokens/cancelled/2026-10-07-shop-a.csv", after.payloads)
        self.assertNotIn("magic/orders/tokens/2026-10-07-shop-a.csv", after.payloads)
        product, summary = self.op("order.cancel", order="2026-10-02-precon", component="precon",
                                   reason="Recorded by mistake")
        self.assertEqual(product.order("2026-10-02-precon").components[0].status, "cancelled")
        self.assertEqual(next(row for row in product.status.rows if row.text("file") == "precon.csv")
                         .text("status"), "cancelled")
        self.refused("already received", "order.cancel", order="2026-10-01-shop", component="cards")
        self.refused("already cancelled", "order.cancel", order="2026-10-07-shop-a", component="tokens")
        self.refused("There's no order", "order.cancel", order="2026-01-01-nothing", component="cards")

    # -------------------------------------------------------- order.extra_copies

    def test_marking_a_component_as_extra_copies(self):
        oid = "2026-10-07-shop-a"
        self.op("order.cancel", order=oid, component="tokens", reason="Out of stock")
        before = self.load().order(oid).record()
        after, summary = self.op("order.extra_copies", order=oid, component="cards")
        self.assertIn("marked as extra copies of owned printings", summary.text)
        o = after.order(oid)
        self.assertEqual(o.audit_notes, "Component tokens cancelled: Out of stock. "
                                        "Extra copies of owned printings: cards.")
        self.assertEqual(rules.extra_copies(o.audit_notes), ("cards",))
        self.assertEqual({k: v for k, v in o.record().items() if k != "audit_notes"},
                         {k: v for k, v in before.items() if k != "audit_notes"})
        # Marking it again changes nothing; a product is marked in the same sentence.
        _, summary = self.op("order.extra_copies", order=oid, component="cards")
        self.assertIn("is already marked", summary.text)
        after, _ = self.op("order.extra_copies", order="2026-10-02-precon", component="precon")
        self.assertEqual(after.order("2026-10-02-precon").audit_notes, "Extra copies of owned printings: precon.")
        # --undo takes only the mark off, leaving the rest of audit_notes as it was.
        after, summary = self.op("order.extra_copies", order=oid, component="cards", undo=True)
        self.assertIn("no longer marked", summary.text)
        self.assertEqual(after.order(oid).audit_notes, "Component tokens cancelled: Out of stock.")
        after, _ = self.op("order.extra_copies", order="2026-10-02-precon", component="precon", undo=True)
        self.assertNotIn("audit_notes", after.order("2026-10-02-precon").record())
        _, summary = self.op("order.extra_copies", order=oid, component="cards", undo=True)
        self.assertIn("isn't marked", summary.text)
        self.refused("already received", "order.extra_copies", order="2026-10-01-shop", component="cards")
        self.refused("is a tokens component", "order.extra_copies", order=oid, component="tokens")
        self.refused("no component", "order.extra_copies", order=oid, component="nope")
        self.refused("There's no order", "order.extra_copies", order="2026-01-01-nothing", component="cards")

    def test_an_order_added_with_extra_copies_marked(self):
        after, _ = self.op("order.add", **self.add_params(
            record={"id": "2026-10-12-goodgames", "seller": "Good Games", "ordered_on": "2026-10-12",
                    "sources": [], "notes": "", "audit_notes": "From the shop."}, extra_copies=["cards"]))
        self.assertTrue(after.order("2026-10-12-goodgames").audit_notes.endswith(
            "From the shop. Extra copies of owned printings: cards."))
        from decklab.lib.inventory import order_fulfilment
        self.assertIsNotNone(order_fulfilment.read(after.order("2026-10-12-goodgames")))
        self.refused("isn't a cards or product component", "order.add",
                     **self.add_params(record={"id": "2026-10-13-other", "seller": "", "ordered_on": "",
                                               "sources": [], "notes": ""}, extra_copies=["tokens"]))

    # -------------------------------------------------------- products

    def test_adding_a_product_to_an_order(self):
        after, _ = self.op("product.add", order="2026-10-07-shop-a", product={
            "stem": "zeta-kit", "columns": PRODUCT_COLUMNS, "status": "preordered",
            "rows": product_rows(("Main", "Sol Ring", "ecc", "57", 1))})
        self.assertEqual([c.id for c in after.order("2026-10-07-shop-a").components], ["cards", "tokens", "zeta-kit"])
        self.assertEqual([r.text("file") for r in after.status.rows],
                         ["fdn-beginner-box.csv", "precon.csv", "zeta-kit.csv"])
        self.assertIsNotNone(after.product("zeta-kit"))
        self.assertEqual(orders.pairing_problems(after), [])
        self.refused("not a card name", "product.add", order="2026-10-07-shop-a", product={
            "stem": "eta-kit", "columns": PRODUCT_COLUMNS, "rows": product_rows(("Main", "Sol Rung", "ecc", "57", 1))})
        self.refused("There's no order", "product.add", order="2026-10-08-none", product={
            "stem": "eta-kit", "columns": PRODUCT_COLUMNS, "rows": product_rows(("Main", "Sol Ring", "ecc", "57", 1))})

    def test_a_product_list_the_pool_cant_read_as_decks_is_refused(self):
        # decks._product_lines' rules: the pool would list it with an error, and an incomplete pool
        # refuses every deck table refresh and receipt (and nothing could change it on the database).
        columns = ["section", *PRODUCT_COLUMNS[1:]]
        for section, said in (("maindeck", "line 2: unknown section 'maindeck'"), ("Deck", None)):
            row = dict(zip(columns, (section, "Sol Ring", "ecc", "57", "nonfoil", "1", "uncommon", "")))
            params = {"order": "2026-10-07-shop-a", "product": {"stem": "theta-kit", "columns": columns,
                                                                 "rows": [row]}}
            if said:
                self.refused(f"magic/products/theta-kit.csv: {said}", "product.add", **params)
                self.refused(said, "order.add", **self.add_params(product=params["product"]))
            else:
                after, _ = self.op("product.add", **params)
                self.assertIsNotNone(after.product("theta-kit"))

    def test_an_exact_token_row_is_fulfilled_by_a_token_order(self):
        self.op("watchlist.set", add=True, repo=str(self.root),
                values={"name": "Llanowar Elves", "set": "tltc", "collector_number": "1", "finish": "nonfoil",
                        "printing": "exact", "quantity": "3", "state": "ready", "for": "Tokens"})
        row = token("Llanowar Elves", 2, notes="single-sided verified")
        row.update({"set": "tltc", "front_collector_number": "1", "finish": "nonfoil"})
        with mock.patch.object(orders, "check_token_names", lambda rows: (rows, [])):
            self.refused("the order doesn't have 3 of the exact printing tltc 1 nonfoil", "order.add",
                         **self.add_params(cards=None, tokens={"rows": [row]},
                                           fulfils=[{"select": "Llanowar Elves@Tokens", "quantity": 3}]))
            after, summary = self.op("order.add", **self.add_params(
                cards=None, tokens={"rows": [row]}, fulfils=[{"select": "Llanowar Elves@Tokens", "quantity": 2}]))
        self.assertEqual(summary.counts["watchlist_reduced"], 2)
        self.assertEqual([r["quantity"] for r in self.queue() if r["for"] == "Tokens"], ["1"])

    def test_keeping_a_product_intact_or_breaking_it_up(self):
        after, _ = self.op("product.set_intact", stem="fdn-beginner-box", intact="no")
        self.assertEqual(after.status.rows[0].as_dict(), {"file": "fdn-beginner-box.csv", "status": "owned",
                                                          "intact": "no", "sleeves": "", "deck_box": "", "notes": ""})
        after, _ = self.op("product.set_intact", stem="fdn-beginner-box", intact="yes")
        self.assertEqual(after.status.rows[0].text("intact"), "yes")
        self.refused("only an owned product", "product.set_intact", stem="precon", intact="yes")
        self.refused("has no row for", "product.set_intact", stem="nothing", intact="yes")

    # -------------------------------------------------------- the watchlist

    def test_changing_adding_and_removing_watchlist_rows(self):
        ids = [r.id for r in self.load().watchlist.rows]
        after, _ = self.op("watchlist.set", select="Elvish Mystic", repo=str(self.root),
                           values={"listed_aud": "0.40", "listed_at": "MTGMate", "in_stock": "yes",
                                   "checked": "2026-10-12"})
        self.assertEqual([r.id for r in after.watchlist.rows], ids)
        self.assertEqual(after.watchlist.rows[0].text("listed_aud"), "0.40")
        after, _ = self.op("watchlist.set", add=True, repo=str(self.root),
                           values={"name": "Wrath of God", "state": "long_term", "for": "Control",
                                   "source": "magic/buylists/2026-10-12-plan.md"})
        self.assertEqual(self.queue()[-1]["name"], "Wrath of God")
        self.assertEqual(self.queue()[-1]["printing"], "any")
        self.refused("duplicate purchase request", "watchlist.set", add=True, repo=str(self.root),
                     values={"name": "Wrath of God", "state": "ready", "for": "Control"})
        self.refused("invalid purchase state", "watchlist.set", select="#1", repo=str(self.root),
                     values={"state": "soon"})
        self.refused("reference price needs retailer and checked date", "watchlist.set", select="#3",
                     repo=str(self.root), values={"listed_aud": "1.00"})
        self.refused("exact printing needs set", "watchlist.set", select="#1", repo=str(self.root),
                     values={"printing": "exact"})
        self.refused("source file does not exist", "watchlist.set", select="#1", repo=str(self.root),
                     values={"source": "magic/buylists/none.md"})
        after, _ = self.op("watchlist.remove", select="Sol Ring@Other deck")
        self.assertEqual([r["for"] for r in self.queue()], ["Elves", "Cats", "Commander", "Control"])
        self.assertEqual([r.id for r in after.watchlist.rows][:3], ids[:3])

    def test_replacing_the_watchlist_keeps_row_identities(self):
        rows = self.queue()
        ids = [r.id for r in self.load().watchlist.rows]
        rows[0]["quantity"] = "4"
        rows.insert(0, {**rows[2], "name": "Wrath of God", "for": "Control"})
        del rows[4]
        after, summary = self.op("watchlist.replace", rows=rows, repo=str(self.root))
        self.assertEqual(summary.counts, {"added": 1, "removed": 1, "changed": 1})
        self.assertEqual(self.queue(), rows)
        if after.backend == "db":           # the files backend's ids are the rows' positions
            self.assertEqual([r.id for r in after.watchlist.rows][1:4], ids[:3])
        rows[1]["state"] = "maybe"
        self.refused("invalid purchase state", "watchlist.replace", rows=rows, repo=str(self.root))

    # -------------------------------------------------------- pairing

    def test_the_product_pairing_is_kept(self):
        inv = self.load()
        broken = inv.with_status_rows([{**{k: r.text(k) for k in rules.STATUS_FIELDS}, "status": "owned"}
                                       for r in inv.status.rows])
        self.assertEqual(orders.pairing_problems(broken),
                         ["magic/products/precon.csv: product and order receipt statuses disagree"])
        with self.assertRaisesRegex(Invalid, "Shopping records need attention: magic/products/precon.csv"):
            orders.keep_pairing(inv, broken)
        orders.keep_pairing(broken, broken)          # a problem already there doesn't stop a change


class FileOrderOpsTests(OrderOps, unittest.TestCase):
    """The operations on the files backend."""

    def setUp(self):
        case = contract.build_tree(orders_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        self.backend = FileInventory(case.inventory.root)
        self.start(case)

    def test_a_file_name_another_payload_has_is_refused(self):
        (self.root / "magic/orders/cancelled/2026-10-12-goodgames.csv").write_text(
            CARD_HEADER + "Sol Ring,ecc,57,nonfoil,1,,,\n", encoding="utf-8", newline="\n")
        with self.assertRaisesRegex(Invalid, "component file occurs in more than one order"):
            self.op("order.add", **self.add_params())

    def test_a_malformed_watchlist_quantity_is_refused_in_read_queues_words(self):
        path = self.root / "magic/watchlist.csv"
        path.write_text(path.read_text(encoding="utf-8").replace("Elvish Mystic,,,,3,", "Elvish Mystic,,,,three,"),
                        encoding="utf-8", newline="\n")
        with self.assertRaisesRegex(Invalid, "watchlist: Elvish Mystic: quantity must be a positive integer"):
            self.op("order.add", **self.add_params(fulfils=[{"select": "Elvish Mystic", "quantity": 1}]))

    def test_a_product_with_no_deck_lists_isnt_kept_intact(self):
        # pool.load_pool's "marked intact but has no deck lists" would stop every refresh and receipt.
        (self.root / "magic/products/loose.csv").write_text(
            "name,set,collector_number,finish,quantity,rarity,notes\nSol Ring,ecc,57,nonfoil,1,uncommon,\n",
            encoding="utf-8", newline="\n")
        (self.root / "magic/products/status.csv").write_text(
            STATUS_HEADER + "fdn-beginner-box.csv,owned,yes,black-sleeves,shared-box,\nloose.csv,owned,no,,,\n"
                            "precon.csv,preordered,,,,due soon\n", encoding="utf-8", newline="\n")
        (self.root / "magic/orders/records/product-loose.json").write_text(record_json(
            "product-loose", "", "", [component("product-loose", "product", "magic/products/loose.csv", "received")]),
            encoding="utf-8", newline="\n")
        self.refused("loose.csv has no deck lists, so keeping it intact would hold nothing", "product.set_intact",
                     stem="loose", intact="yes")
        _, summary = self.op("product.set_intact", stem="loose", intact="no")
        self.assertIn("already broken up", summary.text)

    def test_a_problem_already_there_doesnt_stop_an_unrelated_change(self):
        (self.root / "magic/products/status.csv").write_text(
            STATUS_HEADER + "fdn-beginner-box.csv,owned,yes,,,\nlost.csv,owned,no,,,\nprecon.csv,preordered,,,,\n",
            encoding="utf-8", newline="\n")
        self.op("watchlist.remove", select="#4")
        self.assertEqual(len(self.queue()), 3)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class PgOrderOpsTests(OrderOps, db_support.DbTestCase):
    """The operations on the database backend, the same tree imported."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = contract.build_tree(orders_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        pg.write_model(case.inventory.load(), CLAUDE, "Import", contents=contract.import_contents(case.inventory.root),
                       dbname=self.dbname)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.start(case)

    def test_each_write_is_one_change_set_and_both_backends_agree(self):
        steps = [("order.add", self.add_params(fulfils=[{"select": "Elvish Mystic", "quantity": 1}])),
                 ("order.split", {"order": "2026-10-12-goodgames", "component": "cards", "new_id": "late",
                                  "take": [{"row": 2, "quantity": 1}], "move_checks": [1]}),
                 ("order.cancel", {"order": "2026-10-12-goodgames", "component": "late", "reason": "Not supplied"}),
                 ("order.checks", {"order": "2026-10-01-shop", "component": "cards", "clear": True}),
                 ("product.set_intact", {"stem": "fdn-beginner-box", "intact": "no"}),
                 ("watchlist.set", {"select": "#2", "values": {"quantity": "2"}, "repo": str(self.root)})]
        with self.connect() as c:
            sets = c.execute("select count(*) from audit.change_set").fetchone()[0]
        for kind, params in steps:
            self.op(kind, **params)
        with self.connect() as c:
            messages = [r[0] for r in c.execute("select message from audit.change_set order by id").fetchall()]
        self.assertEqual(messages[sets:], [f"test {kind}" for kind, _ in steps])
        mirror = contract.build_tree(orders_tree, adapted=True)
        self.addCleanup(mirror.doCleanups)
        twin = FileInventory(mirror.inventory.root)
        with inventory.use(twin):
            for kind, params in steps:
                inventory.apply(inventory.Op(kind, params), CLAUDE, f"test {kind}")
        self.assertEqual(files.render(self.load()), files.render(twin.load()))


# ------------------------------------------------------------------ the command lines

def fake_refresh(stack, tables, plan):
    """Stand in for the deck tables' refresh inside a refreshing operation: refresh.in_op puts
    tables() (a Mock's answer: {written, skipped, commit, error}) in the Summary, and
    refresh.plan_refresh (the refusal's check of the inventory as it is) is plan."""
    def in_op(before, after, summary):
        return after, dataclasses.replace(summary, extra={**(summary.extra or {}), "tables": tables()})
    stack.enter_context(mock.patch.object(refresh, "in_op", in_op))
    stack.enter_context(mock.patch.object(refresh, "preload", lambda: None))
    stack.enter_context(mock.patch.object(refresh, "plan_refresh", plan))


def tables_answer(written=(), skipped=(), error=None):
    return {"written": list(written), "skipped": list(skipped), "error": error}


ELVES = {"id": "casual/elves", "title": "Elves"}


class CommandLineTests(unittest.TestCase):
    """python -m decklab.db order / product / watchlist on the files backend. A refreshing write
    runs its refresh twice: in the preview its refusal check makes, then in the apply."""

    def setUp(self):
        case = contract.build_tree(orders_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        self.root = case.inventory.root
        self.backend = FileInventory(self.root)
        self.refresh = mock.Mock(return_value=tables_answer([ELVES]))
        self.plan = mock.Mock(return_value=[])
        stack = contextlib.ExitStack()
        stack.enter_context(contract.fixture_world())
        stack.enter_context(inventory.use(self.backend))
        fake_refresh(stack, self.refresh, self.plan)
        from decklab.lib import config
        stack.enter_context(mock.patch.object(config, "REPO", self.root))
        self.addCleanup(stack.close)

    def run_cli(self, *argv):
        from decklab.db import __main__ as cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def file(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8", newline="\n")
        return str(path)

    def test_order_add_from_a_record_file_with_a_product_and_the_watchlist(self):
        record = self.file("record.json", json.dumps({
            "version": 1, "id": "2026-10-12-goodgames", "seller": "Good Games", "ordered_on": "2026-10-12",
            "sources": ["magic/buylists/2026-10-12-plan.md"], "notes": "",
            "components": [{"id": "cards", "kind": "cards", "checks": ["Record conditions"]}]}))
        cards = self.file("cards.csv", CARD_HEADER + "Elvish Mystic,cmm,648,nonfoil,2,,,\n")
        product = self.file("kit.csv", ",".join(PRODUCT_COLUMNS) + "\nMain,Sol Ring,ecc,57,nonfoil,1,uncommon,\n")
        code, out, err = self.run_cli("order", "add", "--record", record, "--cards", cards, "--product", "kit",
                                      "--product-csv", product, "--check", "kit=Count the tokens",
                                      "--fulfils", "Elvish Mystic=2", "-m", "Order from Good Games")
        self.assertEqual(code, 0, err)
        self.assertIn("Recorded order 2026-10-12-goodgames: 2 cards, the product kit (1 card)", out)
        self.assertIn("Deck tables refreshed: Elves", out)
        self.assertEqual(self.refresh.call_count, 2)        # the refusal check's preview, then the apply
        inv = self.backend.load()
        self.assertEqual([(c.id, c.checks) for c in inv.order("2026-10-12-goodgames").components],
                         [("cards", ["Record conditions"]), ("kit", ["Count the tokens"])])
        self.assertEqual([r.text("name") for r in inv.watchlist.rows],
                         ["Elvish Mystic", "Pick Your Poison", "Sol Ring", "Sol Ring"])
        self.assertEqual(inv.watchlist.rows[0].text("quantity"), "1")

    def test_a_refused_order_says_why_and_writes_nothing(self):
        before = files.tree_files(self.root)
        cards = self.file("cards.csv", CARD_HEADER + "Elvish Mystic,cmm,648,nonfoil,2,,,\n")
        code, _, err = self.run_cli("order", "add", "--id", "2026-10-07-shop-a", "--cards", cards, "-m", "Again")
        self.assertEqual((code, err.strip()), (1, "magic/orders/records/2026-10-07-shop-a.json already exists"))
        bad = self.file("bad.csv", "name,quantity\nOpt,1\n")
        code, _, err = self.run_cli("order", "add", "--id", "2026-10-12-x", "--cards", bad, "-m", "Bad")
        self.assertEqual(code, 1)
        self.assertIn("missing columns", err)
        self.assertEqual(files.tree_files(self.root), before)
        self.refresh.assert_not_called()

    def test_dry_run_saves_nothing(self):
        before = files.tree_files(self.root)
        cards = self.file("cards.csv", CARD_HEADER + "Elvish Mystic,cmm,648,nonfoil,2,,,\n")
        code, out, _ = self.run_cli("order", "add", "--id", "2026-10-12-x", "--cards", cards, "-m", "Try",
                                    "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Dry run: nothing saved. It would change:\n  Order 2026-10-12-x\n", out)
        self.assertNotIn("magic/", out)
        self.assertNotIn("Deck tables refreshed", out)
        self.assertEqual(files.tree_files(self.root), before)

    def test_the_receipt_round_trip_show_edit_then_receive(self):
        code, out, _ = self.run_cli("order", "show", "2026-10-07-shop-a")
        self.assertEqual(code, 0)
        self.assertIn("check 2: Check languages", out)
        self.assertIn("1. 2 x Elvish Mystic (CMM 648, nonfoil)", out)
        code, out, _ = self.run_cli("order", "show", "2026-10-07-shop-a", "--csv", "cards")
        edited = self.file("edit.csv", out.replace("Elvish Mystic,cmm,648,nonfoil,2,,,",
                                                   "Elvish Mystic,cmm,648,nonfoil,2,NM,en,"))
        code, out, err = self.run_cli("order", "edit", "2026-10-07-shop-a", "cards", "--csv", edited,
                                      "-m", "Conditions")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.refresh.call_count, 2)
        code, _, err = self.run_cli("order", "checks", "2026-10-07-shop-a", "cards", "--resolve", "1",
                                    "-m", "Recorded")
        self.assertEqual(code, 1)                           # the receipt verifies them: receive --verified
        self.assertIn("receive --verified cards", err)
        code, _, err = self.run_cli("order", "checks", "2026-10-07-shop-a", "cards", "--withdraw", "2",
                                    "-m", "Added by mistake")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.refresh.call_count, 2)        # checks change no deck table
        part = self.backend.load().order("2026-10-07-shop-a").components[0]
        self.assertEqual(part.checks, ["Record conditions"])
        self.assertIn(b"NM,en", files.render(self.backend.load())["magic/orders/2026-10-07-shop-a.csv"])

    def test_order_extra_copies(self):
        oid = "2026-10-07-shop-a"
        before = files.render(self.backend.load())
        code, out, err = self.run_cli("order", "extra-copies", oid, "cards", "-m", "A second copy", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("Dry run: nothing saved.", out)
        self.assertEqual(files.render(self.backend.load()), before)
        self.refresh.reset_mock()
        code, out, err = self.run_cli("order", "extra-copies", oid, "cards", "-m", "A second copy")
        self.assertEqual(code, 0, err)
        self.assertIn(f"Order {oid} cards: marked as extra copies of owned printings", out)
        self.assertIn("Deck tables refreshed: Elves", out)
        self.assertEqual(self.refresh.call_count, 2)        # the refusal check's preview, then the apply
        self.assertEqual(self.backend.load().order(oid).audit_notes, "Extra copies of owned printings: cards.")
        code, out, err = self.run_cli("order", "extra-copies", oid, "cards", "--undo", "-m", "Not extra after all")
        self.assertEqual(code, 0, err)
        self.assertIn("no longer marked", out)
        self.assertNotIn("audit_notes", self.backend.load().order(oid).record())
        code, _, err = self.run_cli("order", "extra-copies", "2026-10-01-shop", "cards", "-m", "Too late")
        self.assertEqual(code, 1)
        self.assertIn("already received", err)
        # order add --extra-copies marks one in the same change.
        cards = self.file("cards.csv", CARD_HEADER + "Elvish Mystic,cmm,648,nonfoil,1,,,\n")
        code, out, err = self.run_cli("order", "add", "--id", "2026-10-13-ebay", "--cards", cards,
                                      "--extra-copies", "cards", "-m", "A second Elvish Mystic")
        self.assertEqual(code, 0, err)
        order = self.backend.load().order("2026-10-13-ebay")
        self.assertEqual(rules.extra_copies(order.audit_notes), ("cards",))
        from decklab.lib.inventory import order_fulfilment
        self.assertIsNotNone(order_fulfilment.read(order))

    def test_split_cancel_and_product_commands(self):
        code, out, err = self.run_cli("order", "split", "2026-10-07-shop-a", "cards", "--new-id", "late",
                                      "--take", "2", "--move-check", "2", "-m", "Part of it is late")
        self.assertEqual(code, 0, err)
        self.assertIn("into late (2026-10-07-shop-a-late.csv)", out)
        self.file("magic/buylists/2026-10-07-order.md", "[late](../orders/2026-10-07-shop-a-late.csv)\n")
        code, _, err = self.run_cli("order", "cancel", "2026-10-07-shop-a", "late", "-m", "Refunded",
                                    "--reason", "out of stock")
        self.assertEqual(code, 0, err)
        self.assertIn("Review the queue manually", err)
        self.assertIn("magic/buylists/2026-10-07-order.md links to magic/orders/2026-10-07-shop-a-late.csv", err)
        code, _, err = self.run_cli("order", "cancel", "2026-10-02-precon", "precon", "-m", "No", "--reason", "x")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.backend.load().order("2026-10-02-precon").components[0].status, "cancelled")
        self.assertIsNotNone(self.backend.load().product("precon"))
        code, _, err = self.run_cli("product", "set-intact", "fdn-beginner-box", "no", "-m", "Broken up")
        self.assertEqual(code, 0, err)
        kit = self.file("kit.csv", ",".join(PRODUCT_COLUMNS) + "\nMain,Sol Ring,ecc,57,nonfoil,1,uncommon,\n")
        code, _, err = self.run_cli("product", "add", "kit", "--order", "2026-10-07-shop-a", "--csv", kit,
                                    "-m", "Add the kit")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.refresh.call_count, 10)       # five saved writes, each previewed then applied
        code, out, _ = self.run_cli("order", "list", "--pending")
        self.assertIn("2026-10-07-shop-a  pending  MTGMate", out)
        self.assertNotIn("2026-10-01-shop", out)

    def test_watchlist_commands(self):
        code, out, _ = self.run_cli("watchlist", "list")
        self.assertIn("#2  1 x Pick Your Poison (exact: MKM 170 nonfoil) for Cats  ready  A$0.50 at MTGMate, "
                      "in stock, 2026-10-05", out)
        code, _, err = self.run_cli("watchlist", "set", "Sol Ring", "--quantity", "2", "-m", "More")
        self.assertEqual(code, 1)
        self.assertIn("more than one watchlist row", err)
        code, _, err = self.run_cli("watchlist", "set", "Sol Ring@Commander", "--quantity", "2", "-m", "More")
        self.assertEqual(code, 0, err)
        code, _, err = self.run_cli("watchlist", "set", "--add", "--name", "Wrath of God", "--state", "long_term",
                                    "--for", "Control", "-m", "Plan")
        self.assertEqual(code, 0, err)
        code, out, _ = self.run_cli("watchlist", "list", "--csv")
        edited = self.file("queue.csv", out.replace("Elvish Mystic,,,,3,", "Elvish Mystic,,,,5,"))
        code, out, err = self.run_cli("watchlist", "apply", "--csv", edited, "-m", "Shop check")
        self.assertEqual(code, 0, err)
        self.assertIn("Watchlist: 0 added, 1 changed, 0 removed (5 rows)", out)
        code, _, err = self.run_cli("watchlist", "remove", "#5", "-m", "Not needed", "--reason", "changed plan")
        self.assertEqual(code, 0, err)
        self.refresh.assert_not_called()
        self.assertEqual([r.text("quantity") for r in self.backend.load().watchlist.rows], ["5", "1", "2", "1"])

    def test_a_refresh_failure_leaves_the_change_and_says_so(self):
        # The preview plans fine; the refresh inside the apply fails: the change is saved anyway.
        self.refresh.side_effect = [tables_answer([ELVES]),
                                    tables_answer(error="Cannot refresh from an incomplete card pool")]
        code, _, err = self.run_cli("product", "set-intact", "fdn-beginner-box", "no", "-m", "Broken up")
        self.assertEqual(code, 3)                   # saved, but the follow-up didn't finish (as receive's)
        self.assertIn("the deck tables weren't refreshed: Cannot refresh", err)
        self.assertEqual(self.backend.load().status.rows[0].text("intact"), "no")
        # A deck skipped by the refresh is only a note.
        self.refresh.side_effect = None
        self.refresh.return_value = tables_answer(skipped=[dict(ELVES, why="kit")])
        code, _, err = self.run_cli("product", "set-intact", "fdn-beginner-box", "yes", "-m", "Kept")
        self.assertEqual(code, 0, err)
        self.assertIn("Elves's table wasn't refreshed (its Sleeves or Deck box would change)", err)

    def test_a_change_that_would_stop_the_refresh_is_refused_unless_forced(self):
        # The refresh is planned now (fine) and inside the change's preview (refused): nothing is saved.
        self.refresh.return_value = tables_answer(error="Cannot refresh from an incomplete card pool: every card "
                                                        "in magic/orders/2026-10-07-shop-a-late.csv is already "
                                                        "in the collection")
        argv = ("order", "split", "2026-10-07-shop-a", "cards", "--new-id", "late", "--take", "2", "-m", "Late")
        before = files.render(self.backend.load())
        code, _, err = self.run_cli(*argv)
        self.assertEqual(code, 1)
        self.assertIn("Refused: after this change the deck tables couldn't be refreshed", err)
        self.assertIn("is already in the collection", err)
        self.assertIn("--force", err)
        self.assertEqual(files.render(self.backend.load()), before)
        self.assertEqual(self.refresh.call_count, 1)        # the preview's only: nothing was applied
        code, _, err = self.run_cli(*argv, "--dry-run")
        self.assertEqual(code, 1)
        self.assertEqual(files.render(self.backend.load()), before)
        # --force saves it anyway, with the refresh skipped (neither planned nor run).
        self.refresh.reset_mock()
        self.plan.reset_mock()
        code, out, err = self.run_cli(*argv, "--force", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("--force: the deck tables wouldn't be refreshed", err)
        self.assertEqual(files.render(self.backend.load()), before)
        code, out, err = self.run_cli(*argv, "--force")
        self.assertEqual(code, 0, err)
        self.assertIn("into late", out)
        self.assertIn("--force: the deck tables weren't refreshed, so some may be stale", err)
        self.assertIn("deck tables --apply", err)
        self.plan.assert_not_called()
        self.refresh.assert_not_called()
        # A refresh that already fails before the change (in the spaces it touches) doesn't stop
        # it: it's saved, and the failed refresh is said (exit 3).
        self.refresh.reset_mock()
        self.plan.side_effect = ValueError("Cannot refresh from an incomplete card pool")
        self.refresh.return_value = tables_answer(error="Cannot refresh from an incomplete card pool")
        code, _, err = self.run_cli("order", "cancel", "2026-10-07-shop-a", "late", "-m", "Refunded",
                                    "--reason", "out of stock")
        self.assertEqual(code, 3, err)
        self.assertEqual(self.plan.call_count, 1)
        self.assertEqual(self.plan.call_args.args, ({"home"},))     # only the spaces the change touches
        self.assertEqual(self.refresh.call_count, 2)        # the refusal check's preview, then the apply
        self.plan.side_effect = None
        # A write that doesn't refresh the tables never plans them.
        self.plan.reset_mock()
        self.refresh.reset_mock()
        code, _, err = self.run_cli("watchlist", "remove", "#4", "-m", "Not needed", "--reason", "changed plan")
        self.assertEqual(code, 0, err)
        self.plan.assert_not_called()
        self.refresh.assert_not_called()

    def test_while_deck_saves_are_paused_a_change_goes_ahead_and_exits_3(self):
        self.refresh.return_value = tables_answer(error=inventory.DECK_SAVES_PAUSED)
        argv = ("product", "set-intact", "fdn-beginner-box", "no", "-m", "Broken up")
        code, out, err = self.run_cli(*argv, "--dry-run")
        self.assertEqual(code, 0, err)                      # not refused: a change can't make it worse
        self.assertIn(f"the deck tables wouldn't be refreshed: {inventory.DECK_SAVES_PAUSED}", err)
        self.plan.assert_not_called()
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 3)                           # saved, the tables left stale
        self.assertIn(f"the deck tables weren't refreshed: {inventory.DECK_SAVES_PAUSED}", err)
        self.assertEqual(self.backend.load().status.rows[0].text("intact"), "no")

    def test_the_refreshing_kinds_are_registered_with_refresh(self):
        from decklab.lib.inventory import receive
        mine = [kind for kind in inventory.kinds() if kind.split(".")[0] in ("order", "product", "receipt",
                                                                                "watchlist")]
        self.assertEqual({kind for kind in mine if inventory.refreshes(kind)},
                         {"order.add", "order.edit", "order.split", "order.cancel", "order.remove", "order.extra_copies",
                          "product.add", "product.edit", "product.set_intact", receive.KIND})
        self.assertIn("order.checks", mine)                 # checks and the watchlist change no table


class TableFollowUpWordingTests(unittest.TestCase):
    """The order, product and receive commands' follow-up lines name the Decks page's real list."""

    def said(self, call, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = call(*args)
        return result, out.getvalue() + err.getvalue()

    def test_they_point_at_the_tables_out_of_date_list(self):
        from decklab.db import inv_orders, inv_receive
        listed = "Update all on the Decks page's Tables out of date list (or python -m decklab.db deck tables --apply)"
        result, text = self.said(inv_orders.say_tables, {"error": "an unknown card"})
        self.assertFalse(result)
        self.assertIn(listed, text)
        self.assertIn(listed, self.said(inv_orders._say_forced, True)[1])
        result, text = self.said(inv_receive._say_tables, dict(inv_receive.NO_TABLES, error="an unknown card"))
        self.assertFalse(result)
        self.assertIn(listed, text)
        _, text = self.said(inv_orders.say_tables, {"skipped": [{"id": "casual/x", "title": "X", "why": "kit"}]})
        self.assertIn("X's table wasn't refreshed (its Sleeves or Deck box would change); the Decks page's "
                      "Tables out of date list has it.", text)
        for words in (text, inv_orders.say_tables.__doc__, inv_receive.__doc__):
            self.assertNotIn("Library", words)


if __name__ == "__main__":
    unittest.main()
