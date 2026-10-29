"""Tests for decklab.lib.pool: owned vs needed and the shared card pool.

Each test builds a small magic/ tree in a temp folder (collection.csv, orders,
products with status.csv, deck files) and points pool.py and decks at it.
Names resolve against the fixture card index test_cards.py uses
(fixtures/default_cards.jsonl), and the exchange rate is mocked, so nothing
needs the network or the real data cache. The last tests check the real
magic/products/status.csv.

Run from the repo root: python scripts/test_fixtures.py
"""
import contextlib
import csv
import io
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import cards, decks, inventory, pool
from decklab.lib.inventory import rules
from decklab.lib.inventory.files import FileInventory
from decklab.tests import deck_files, pre_db

FIXTURES = Path(__file__).parent / "fixtures"


def assert_page_list_names(case, warnings):
    """Warnings reach the page (Collection, the packing plan), which names the lists Planned and Play-now: the old
    names may appear only as a Built version field's literal value."""
    for text in warnings:
        bare = re.sub(r"'Built version: [^']*'(, which isn't target or owned-only)?", "", text)
        case.assertNotRegex(bare, r"(?i)owned-only|target list|target version", text)


CARD_COLUMNS = ["name", "set", "collector_number", "finish", "quantity", "condition", "language", "notes"]
RATE = (2.0, "2026-09-28")      # 1 USD = 2 AUD keeps the expected prices exact
BB = "Foundations Beginner Box"

_tmp = None


def setUpModule():
    global _tmp
    _tmp = Path(tempfile.mkdtemp())
    index = cards.build_index(FIXTURES / "default_cards.jsonl", FIXTURES / "oracle_tags.jsonl",
                              {"default_cards": "2026-09-28T21:05:39+00:00"}, log=lambda *a: None)
    cards.write_index(index, _tmp / "index.json.gz")
    cards.load(_tmp / "index.json.gz")


def tearDownModule():
    cards._index = None
    shutil.rmtree(_tmp, ignore_errors=True)


def deck_md(title, status, target, owned=None, table="", built_version=None, note=""):
    """A minimal deck file; target/owned are decklist text ending in a newline."""
    built = f"- **Built version:** {built_version}\n" if built_version else ""
    text = (f"# {title}\n\n- **Format:** Casual 60-card, 1v1\n- **Played by:** either\n"
            f"- **Status:** {status}\n{built}\n## Decklist\n\n```\n{target}```\n")
    if table:
        note = f"{note}\n\n" if note else ""
        text += f"\n## Owned vs needed\n\n{note}{decks.TABLE_HEADER}\n{decks.TABLE_RULE}\n{table}"
    if owned is not None:
        text += f"\n## Substitutes\n\n### Owned-only version\n\n```\n{owned}```\n"
    return text


class PoolTestCase(unittest.TestCase):
    """A temp magic/ tree with an empty collection and an empty status.csv, installed as the
    inventory backend (self.inventory, a FileInventory over it)."""

    def setUp(self):
        root = Path(tempfile.mkdtemp()).resolve()       # long form, as golden_dump.pointed() resolves it
        self.addCleanup(shutil.rmtree, root, True)
        self.magic = root / "magic"
        for sub in ("orders/received", "products", "decks/casual", "decks/commander"):
            (self.magic / sub).mkdir(parents=True)
        for target, name, value in (
                # The pool and the product decks read the inventory (below).
                (decks, "DECKS_DIR", self.magic / "decks"),
                (cards, "usd_to_aud", mock.Mock(return_value=RATE))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # The inventory backend reads this tree (decklab/lib/inventory), never the live repo's.
        self.inventory = FileInventory(root)
        self.addCleanup(inventory.use(self.inventory))
        self.cards_csv("collection.csv")
        self.status()

    def write(self, rel, text):
        (self.magic / rel).write_text(text, encoding="utf-8", newline="\n")   # LF, like the repo

    def cards_csv(self, rel, *rows):
        """Write a collection-style CSV; rows are (name, set, number, finish, quantity)."""
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(CARD_COLUMNS)
        for name, set_code, number, finish, qty in rows:
            w.writerow([name, set_code, number, finish, qty, "NM", "en", ""])
        self.write(rel, out.getvalue())

    def product(self, file, *rows, column="deck"):
        """Write a product CSV; rows are (deck or section, name, quantity)."""
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow([column, "name", "set", "collector_number", "finish", "quantity", "rarity", "notes"])
        for group, name, qty in rows:
            w.writerow([group, name, "tst", "1", "nonfoil", qty, "common", ""])
        self.write(f"products/{file}", out.getvalue())

    def status(self, *rows):
        """Write products/status.csv; rows are (file, status, intact)."""
        self.write("products/status.csv", "file,status,intact,notes\n"
                   + "".join(f"{f},{s},{i},\n" for f, s, i in rows))

    def deck(self, slug, *args, kind="casual", **kwargs):
        self.write(f"decks/{kind}/{slug}.md", deck_md(*args, **kwargs))

    def check(self, deck_id, version="target", prices=False):
        """owned_vs_needed with its rows keyed by card name."""
        result = pool.owned_vs_needed(deck_id, version, prices=prices)
        return result, {r["name"]: r for r in result["rows"]}

    def beginner_box(self):
        """Three intact Beginner Box halves that share Llanowar Elves."""
        self.product("fdn-beginner-box.csv",
                     ("Elves", "Llanowar Elves", 1), ("Elves", "Elvish Mystic", 1), ("Elves", "Forest", 7),
                     ("Cats", "Llanowar Elves", 1), ("Cats", "Pick Your Poison", 1), ("Cats", "Plains", 7),
                     ("Goblins", "Aerie Mystics", 1), ("Goblins", "Mountain", 7))
        self.status(("fdn-beginner-box.csv", "owned", "yes"))
        self.cards_csv("collection.csv", ("Aerie Mystics", "con", "1", "nonfoil", 1),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 1),
                       ("Llanowar Elves", "fdn", "227", "nonfoil", 2),
                       ("Pick Your Poison", "mkm", "170", "nonfoil", 1))


class CountingTests(PoolTestCase):

    def test_sums_across_printings_and_finishes(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2),
                       ("Llanowar Elves", "fdn", "227", "foil", 1),
                       ("Llanowar Elves", "m19", "314", "nonfoil", 1))
        self.deck("a", "A", "idea", "Deck\n4 Llanowar Elves (FDN) 227\n")
        result, rows = self.check("casual/a")
        row = rows["Llanowar Elves"]
        self.assertEqual((row["need"], row["owned"], row["on_the_way"], row["available"], row["missing"]),
                         (4, 4, 0, 4, 0))
        self.assertEqual(result["totals"]["missing"], 0)

    def test_names_resolve_to_scryfall_names(self):
        self.cards_csv("collection.csv", ("Fire // Ice", "apc", "128", "nonfoil", 1),
                       ("Lim-Dûl's Vault", "all", "107", "nonfoil", 1))
        # Two lines of the same card in different sections add up.
        self.deck("a", "A", "idea", "Deck\n2 Fire\n1 Lim-Dul's Vault\n\nSideboard\n1 Fire // Ice (APC) 128\n")
        result, rows = self.check("casual/a")
        self.assertEqual(set(rows), {"Fire // Ice", "Lim-Dûl's Vault"})
        self.assertEqual((rows["Fire // Ice"]["need"], rows["Fire // Ice"]["owned"],
                          rows["Fire // Ice"]["missing"]), (3, 1, 2))
        self.assertEqual(rows["Lim-Dûl's Vault"]["missing"], 0)
        self.assertEqual(result["unresolved"], [])

    def test_unresolved_names_are_reported_and_counted_as_written(self):
        self.cards_csv("collection.csv", ("Llanowar Elfs", "fdn", "227", "nonfoil", 2),
                       ("Mystery Card", "tst", "1", "nonfoil", 1))
        self.deck("a", "A", "idea", "Deck\n2 Mystery Card\n")
        result, rows = self.check("casual/a", prices=True)
        where = "magic/collection.csv"              # derived: the same on both backends
        self.assertEqual(result["unresolved"], sorted([("Llanowar Elfs", where), ("Mystery Card", "decklist"),
                                                       ("Mystery Card", where)]))
        row = rows["Mystery Card"]
        self.assertEqual((row["owned"], row["missing"], row["aud_each"]), (1, 1, None))
        self.assertEqual(result["totals"]["unpriced"], ["Mystery Card"])

    def test_a_lowercase_set_left_in_the_name_still_matches(self):
        # "(fdn)" with no collector number stays in the name when parsed
        # (decks.LINE_RE), so the name is tried without it.
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.deck("a", "A", "idea", "Deck\n4 Llanowar Elves (fdn)\n1 Hazmat Suit (Used)\n")
        result, rows = self.check("casual/a")
        self.assertEqual(decks.parse_line("4 Llanowar Elves (fdn)").name, "Llanowar Elves (fdn)")
        self.assertEqual((rows["Llanowar Elves"]["owned"], rows["Llanowar Elves"]["missing"]), (4, 0))
        self.assertEqual(result["unresolved"], [("Hazmat Suit (Used)", "decklist")])   # not in the fixtures
        deck = decks.read_deck_file(self.magic / "decks" / "casual" / "a.md")
        decks.set_table(deck, *pool.deck_table(deck, prices=False))     # the rows still match the list
        self.assertEqual([r.card for r in deck.rows], ["Hazmat Suit (Used)", "Llanowar Elves"])

    def test_basic_lands_are_left_out_everywhere(self):
        self.cards_csv("collection.csv", ("Forest", "blb", "", "foil", 11),
                       ("Snow-Covered Island", "khm", "281", "nonfoil", 4),
                       ("Sol Ring", "ecc", "57", "nonfoil", 1))
        self.cards_csv("orders/2026-10-01-lands.csv", ("Plains", "fdn", "", "nonfoil", 20))
        self.product("precon.csv", ("deck", "Swamp", 30), ("deck", "Sol Ring", 1), column="section")
        self.status(("precon.csv", "preordered", ""))
        self.deck("a", "A", "idea", "Deck\n1 Sol Ring\n17 Forest\n4 Snow-Covered Island (KHM) 281\n1 Wastes\n")
        result, rows = self.check("casual/a")
        self.assertEqual(list(rows), ["Sol Ring"])
        self.assertEqual(result["totals"]["need"], 1)
        loaded = pool.load_pool()
        self.assertEqual(dict(loaded.owned), {"Sol Ring": 2})
        self.assertEqual(result["unresolved"], [])

    def test_bad_quantity_raises(self):
        self.write("collection.csv", ",".join(CARD_COLUMNS) + "\nSol Ring,ecc,57,nonfoil,lots,NM,en,\n")
        with self.assertRaisesRegex(ValueError, "line 2: bad quantity"):
            pool.load_pool()

    def test_nonpositive_inventory_quantity_raises(self):
        for quantity in (0, -3):
            with self.subTest(quantity=quantity):
                self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", quantity))
                with self.assertRaisesRegex(ValueError, "line 2: bad quantity"):
                    pool.load_pool()
                self.assertEqual(pool.read_printings(inventory.current().collection()), {})
                self.assertEqual(pool.printing_counts(), {})

    def test_blank_name_raises(self):
        self.write("collection.csv", ",".join(CARD_COLUMNS) + "\nSol Ring,ecc,57,nonfoil,1,NM,en,\n"
                   " ,ecc,58,nonfoil,1,NM,en,\n")
        with self.assertRaisesRegex(ValueError, "line 3: no card name"):
            pool.load_pool()


class IncomingTests(PoolTestCase):

    def test_nonpositive_order_and_product_rows_warn_and_do_not_reduce_available_stock(self):
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 2))
        self.cards_csv("orders/test.csv", ("Sol Ring", "ecc", "57", "nonfoil", -3),
                       ("Wrath of God", "8ed", "58", "nonfoil", 0))
        self.product("precon.csv", ("deck", "Sol Ring", -4), ("deck", "Wrath of God", 0),
                     column="section")
        self.status(("precon.csv", "preordered", ""))
        loaded = pool.load_pool()
        self.assertEqual(dict(loaded.owned), {"Sol Ring": 2})
        self.assertEqual(loaded.on_the_way, {})
        self.assertEqual(len(loaded.warnings), 4)
        self.assertTrue(all("bad quantity" in warning for warning in loaded.warnings))
        self.assertEqual(pool.printing_counts(),
                         {("ecc", "57", "nonfoil"): {"owned": 2, "on_the_way": 0}})

    def test_orders_count_as_owned_and_on_the_way(self):
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 1))
        self.cards_csv("orders/2026-09-29-test.csv", ("Sol Ring", "ecc", "57", "nonfoil", 1))
        self.deck("a", "A", "idea", "Deck\n3 Sol Ring\n")
        _, rows = self.check("casual/a")
        row = rows["Sol Ring"]
        self.assertEqual((row["owned"], row["on_the_way"], row["missing"]), (2, 1, 1))
        self.assertEqual(row["on_the_way_from"], [("order 2026-09-29-test", 1)])

    def test_on_the_way_counts_copies_not_sources(self):
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 1))
        self.cards_csv("orders/2026-09-29-test.csv", ("Sol Ring", "ecc", "57", "nonfoil", 3),
                       ("Sol Ring", "cmm", "400", "nonfoil", 1))
        self.product("precon.csv", ("deck", "Sol Ring", 2), column="section")
        self.status(("precon.csv", "preordered", ""))
        self.deck("a", "A", "idea", "Deck\n8 Sol Ring\n")
        _, rows = self.check("casual/a")
        row = rows["Sol Ring"]
        self.assertEqual((row["owned"], row["on_the_way"], row["missing"]), (7, 6, 1))
        self.assertEqual(row["on_the_way_from"], [("order 2026-09-29-test", 4), ("precon, preordered", 2)])

    def test_an_order_or_product_already_in_the_collection_is_a_warning(self):
        # Added to the collection without receiving the order or the
        # product: its cards would count twice.
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 2),
                       ("Wrath of God", "8ed", "58", "nonfoil", 1))
        self.cards_csv("orders/2026-09-29-merged.csv", ("Sol Ring", "ecc", "57", "nonfoil", 2))
        self.cards_csv("orders/2026-09-30-coming.csv", ("Sol Ring", "ecc", "57", "nonfoil", 1),
                       ("Wrath of God", "8ed", "58", "foil", 1))           # the foil isn't here yet
        self.write("products/precon.csv", "section,name,set,collector_number,finish,quantity\n"
                   "deck,Wrath of God,8ed,58,nonfoil,1\ndeck,Swamp,tst,,nonfoil,30\n")
        self.status(("precon.csv", "preordered", ""))
        warnings = "\n".join(pool.load_pool().warnings)
        self.assertIn("2026-09-29-merged.csv (order 2026-09-29-merged) is already in the collection", warnings)
        self.assertIn("precon.csv (precon, preordered) is already in the collection", warnings)
        self.assertEqual(warnings.count(pool.RECEIVE_IT), 2)
        self.assertNotIn("orders/received/", warnings)
        self.assertNotIn("coming", warnings)

    def test_a_component_marked_as_extra_copies_isnt_warned_about(self):
        # A real order for a second copy of an owned printing looks like one merged early; once
        # its record's audit_notes says so (order extra-copies), it's counted with no warning.
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 1),
                       ("Wrath of God", "8ed", "58", "nonfoil", 1))
        self.cards_csv("orders/2026-10-05-extra.csv", ("Sol Ring", "ecc", "57", "nonfoil", 1))
        self.write("products/precon.csv", "section,name,set,collector_number,finish,quantity\n"
                   "deck,Wrath of God,8ed,58,nonfoil,1\n")
        self.status(("precon.csv", "preordered", ""))

        def record(order_id, audit_notes, *parts):
            data = {"version": 1, "id": order_id, "seller": "", "ordered_on": "", "sources": [], "notes": "",
                    "components": [{"id": cid, "kind": kind, "path": path, "status": "pending",
                                    "received_on": "", "checks": []} for cid, kind, path in parts]}
            if audit_notes is not None:
                data["audit_notes"] = audit_notes
            (self.magic / "orders" / "records").mkdir(exist_ok=True)
            self.write(f"orders/records/{order_id}.json", rules.json_bytes(data).decode("utf-8"))

        cards_part = ("cards", "cards", "magic/orders/2026-10-05-extra.csv")
        precon_part = ("precon", "product", "magic/products/precon.csv")
        record("2026-10-05-extra", "Bought from eBay.", cards_part)
        record("2026-10-06-precon", None, precon_part)
        warnings = "\n".join(pool.load_pool().warnings)
        self.assertIn("2026-10-05-extra.csv (order 2026-10-05-extra) is already in the collection", warnings)
        self.assertIn("precon.csv (precon, preordered) is already in the collection", warnings)

        record("2026-10-05-extra", "Bought from eBay. Extra copies of owned printings: cards.", cards_part)
        record("2026-10-06-precon", "Extra copies of owned printings: precon.", precon_part)
        loaded = pool.load_pool()
        self.assertEqual(loaded.warnings, [])
        self.assertEqual(dict(loaded.owned), {"Sol Ring": 2, "Wrath of God": 2})     # still on the way
        self.assertEqual(loaded.on_the_way["Sol Ring"], [("order 2026-10-05-extra", 1)])

        # Only a marker naming that component, in the exact sentence, counts.
        record("2026-10-05-extra", "Extra copies of owned printings: tokens.", cards_part)
        record("2026-10-06-precon", "extra copies of owned printings: precon.", precon_part)
        self.assertEqual(len(pool.load_pool().warnings), 2)

    def test_a_bad_row_in_an_order_or_incoming_product_is_a_warning(self):
        # One typo mustn't stop every owned-vs-needed check; collection.csv
        # still raises (CountingTests).
        self.write("orders/2026-09-29-test.csv", ",".join(CARD_COLUMNS) + "\n"
                   "Sol Ring,ecc,57,nonfoil,1,NM,en,\nOpt,fdn,512,nonfoil,x,NM,en,\n")
        self.write("products/precon.csv", "section,name,set,collector_number,finish,quantity\n"
                   "deck,Wrath of God,8ed,58,nonfoil,1\ndeck,,8ed,59,nonfoil,1\ndeck,Opt,fdn,512,nonfoil,one\n")
        (self.magic / "orders" / "2026-09-30-broken.csv").write_bytes(b"name,quantity\n\xff\xfe,1\n")
        self.status(("precon.csv", "preordered", ""))
        loaded = pool.load_pool()
        self.assertEqual(dict(loaded.owned), {"Sol Ring": 1, "Wrath of God": 1})
        warnings = "\n".join(loaded.warnings)
        for expected in ("2026-09-29-test.csv line 3: bad quantity 'x'; that row isn't counted",
                         "precon.csv line 3: no card name", "precon.csv line 4: bad quantity 'one'",
                         "2026-09-30-broken.csv can't be read, so its cards aren't counted"):
            self.assertIn(expected, warnings)
        self.deck("a", "A", "idea", "Deck\n1 Sol Ring\n")
        self.assertEqual(self.check("casual/a")[1]["Sol Ring"]["missing"], 0)

    def test_received_orders_are_ignored(self):
        # They're already merged into collection.csv, which here has none.
        self.cards_csv("orders/received/2026-09-26-shop-h.csv", ("Sol Ring", "ecc", "57", "nonfoil", 3))
        self.deck("a", "A", "idea", "Deck\n1 Sol Ring\n")
        _, rows = self.check("casual/a")
        self.assertEqual((rows["Sol Ring"]["owned"], rows["Sol Ring"]["missing"]), (0, 1))

    def test_preordered_and_ordered_products_are_on_the_way(self):
        self.product("precon.csv", ("commander", "Ghalta, Primal Hunger", 1), ("deck", "Sol Ring", 1),
                     column="section")
        self.product("fdc-calling-all-angels.csv", ("deck", "Sol Ring", 1), ("deck", "Wrath of God", 1),
                     column="section")
        self.status(("fdc-calling-all-angels.csv", "preordered", ""), ("precon.csv", "ordered", ""))
        self.deck("a", "A", "idea", "Deck\n2 Sol Ring\n1 Ghalta, Primal Hunger\n")
        _, rows = self.check("casual/a")
        self.assertEqual((rows["Sol Ring"]["owned"], rows["Sol Ring"]["on_the_way"],
                          rows["Sol Ring"]["missing"]), (2, 2, 0))
        self.assertEqual(rows["Sol Ring"]["on_the_way_from"],
                         [("Calling All Angels, preordered", 1), ("precon, ordered", 1)])
        self.assertEqual(rows["Ghalta, Primal Hunger"]["on_the_way_from"], [("precon, ordered", 1)])

    def test_owned_products_are_not_counted_twice(self):
        # An owned product is already in collection.csv, intact or not.
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 1))
        self.product("box.csv", ("deck", "Sol Ring", 1), column="section")
        self.product("loose.csv", ("deck", "Sol Ring", 1), column="section")
        self.status(("box.csv", "owned", "no"), ("loose.csv", "owned", ""))
        self.deck("a", "A", "idea", "Deck\n1 Sol Ring\n")
        _, rows = self.check("casual/a")
        self.assertEqual((rows["Sol Ring"]["owned"], rows["Sol Ring"]["on_the_way"]), (1, 0))

    def test_status_problems_are_warnings(self):
        for file in ("unlisted.csv", "typo.csv", "early.csv"):
            self.product(file, ("deck", "Sol Ring", 1), column="section")
        self.status(("early.csv", "ordered", "yes"), ("gone.csv", "owned", "no"),
                    ("typo.csv", "preorder", "maybe"))
        loaded = pool.load_pool()
        text = "\n".join(loaded.warnings)
        for expected in ("Product unlisted has no status", "Product gone has a status but no card list",
                         "typo.csv has status 'preorder'", "typo.csv has intact 'maybe'",
                         "early.csv is ordered: intact only counts once it's owned"):
            self.assertIn(expected, text)
        self.assertEqual(loaded.owned["Sol Ring"], 1)     # only early.csv counts
        self.assertEqual(loaded.in_use, [])

    def test_status_kit_columns_are_read_and_flagged_unless_intact(self):
        self.write("products/status.csv", "file,status,intact,sleeves,deck_box,notes\n"
                   "kept.csv,owned,yes,dragon-shield-matte-black,red box,whole\n"
                   "loose.csv,owned,no,blue,,\n")
        warnings = []
        statuses = pool.read_status(warnings)
        kept = statuses["kept.csv"]
        self.assertEqual((kept.intact, kept.notes, kept.sleeves, kept.deck_box),
                         (True, "whole", "dragon-shield-matte-black", "red box"))
        self.assertEqual(statuses["loose.csv"].sleeves, "blue")
        self.assertEqual(len(warnings), 1)
        self.assertIn("loose.csv has sleeves or a deck box but isn't owned and kept intact", warnings[0])

    def test_legacy_status_file_has_blank_kit_columns(self):
        self.status(("box.csv", "owned", "yes"))
        warnings = []
        status = pool.read_status(warnings)["box.csv"]
        self.assertEqual((status.sleeves, status.deck_box, warnings), ("", "", []))
        self.assertEqual(pool.ProductStatus("x.csv", "owned", True, "n").sleeves, "")

    def test_missing_status_file_is_a_warning(self):
        (self.magic / "products" / "status.csv").unlink()
        self.product("box.csv", ("Elves", "Sol Ring", 1))
        loaded = pool.load_pool()
        self.assertIn("status.csv is missing", loaded.warnings[0])
        self.assertEqual((dict(loaded.owned), loaded.in_use), ({}, []))


class InUseTests(PoolTestCase):

    def setUp(self):
        super().setUp()
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 2),
                       ("Wrath of God", "8ed", "58", "nonfoil", 2))
        self.deck("a", "A", "idea", "Deck\n2 Sol Ring\n1 Wrath of God\n")

    def test_built_deck_holds_its_owned_only_list_sideboard_included(self):
        self.deck("b", "Deck B", "built", "Deck\n3 Sol Ring\n",
                  owned="Deck\n1 Sol Ring\n\nSideboard\n2 Wrath of God\n", built_version="owned-only")
        result, rows = self.check("casual/a")
        self.assertEqual(rows["Sol Ring"]["in_use_elsewhere"], [("Deck B", 1)])
        self.assertEqual((rows["Sol Ring"]["available"], rows["Sol Ring"]["missing"]), (1, 1))
        self.assertEqual(rows["Wrath of God"]["in_use_elsewhere"], [("Deck B", 2)])
        self.assertEqual((rows["Wrath of God"]["available"], rows["Wrath of God"]["missing"]), (0, 1))
        self.assertEqual([(c["name"], c["short"], c["decks"]) for c in result["conflicts"]],
                         [("Sol Ring", 1, [("Deck B", 1)]), ("Wrath of God", 1, [("Deck B", 2)])])
        self.assertEqual(result["warnings"], [])

    def test_built_version_target_holds_the_target_list(self):
        # Once the upgrades are in, the target list is what's sleeved up.
        self.deck("b", "Deck B", "built", "Deck\n2 Wrath of God\n", owned="Deck\n2 Sol Ring\n",
                  built_version="target")
        result, rows = self.check("casual/a")
        self.assertEqual((rows["Sol Ring"]["in_use_elsewhere"], rows["Sol Ring"]["missing"]), ([], 0))
        self.assertEqual((rows["Wrath of God"]["in_use_elsewhere"], rows["Wrath of God"]["missing"]),
                         ([("Deck B", 2)], 1))
        self.assertEqual(result["warnings"], [])

    def test_built_without_a_built_version_holds_the_owned_only_list_and_warns(self):
        self.deck("b", "Deck B", "built", "Deck\n2 Wrath of God\n", owned="Deck\n2 Sol Ring\n")
        result, rows = self.check("casual/a")
        self.assertEqual(rows["Sol Ring"]["in_use_elsewhere"], [("Deck B", 2)])
        self.assertEqual(rows["Wrath of God"]["in_use_elsewhere"], [])
        self.assertIn("casual/b is built but has no 'Built version' field", "\n".join(result["warnings"]))
        self.assertIn("counting its Play-now list as in use", "\n".join(result["warnings"]))
        assert_page_list_names(self, result["warnings"])

    def test_a_built_version_that_isnt_target_or_owned_only_says_so(self):
        # The field is there, so the warning mustn't say it's missing.
        self.deck("b", "Deck B", "built", "Deck\n2 Wrath of God\n", owned="Deck\n2 Sol Ring\n",
                  built_version="the full list")
        result, rows = self.check("casual/a")
        self.assertEqual(rows["Sol Ring"]["in_use_elsewhere"], [("Deck B", 2)])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("casual/b is built but has 'Built version: the full list', which isn't target or owned-only",
                      result["warnings"][0])
        # Backticks, as AGENTS.md typesets the values, are fine.
        self.deck("b", "Deck B", "built", "Deck\n2 Wrath of God\n", owned="Deck\n2 Sol Ring\n",
                  built_version="`target`")
        result, rows = self.check("casual/a")
        self.assertEqual((rows["Wrath of God"]["in_use_elsewhere"], result["warnings"]), ([("Deck B", 2)], []))

    def test_a_built_deck_with_no_decklist_block_is_a_warning_not_an_empty_deck(self):
        self.write("decks/casual/b.md", deck_md("Deck B", "built", "Deck\n2 Sol Ring\n")
                   .replace("## Decklist", "## Deck list"))
        result, rows = self.check("casual/a")
        self.assertEqual(rows["Sol Ring"]["in_use_elsewhere"], [])
        self.assertIn("casual/b can't be read: no fenced decklist block under a '## Decklist' heading",
                      "\n".join(result["warnings"]))
        with self.assertRaises(decks.DeckFileError):
            pool.owned_vs_needed("casual/b")

    def test_built_deck_without_owned_only_list_holds_its_target_list(self):
        self.deck("b", "Deck B", "built", "Deck\n1 Sol Ring\n", kind="commander")
        self.deck("c", "Deck C", "built", "Deck\n1 Wrath of God\n", built_version="owned-only")
        result, rows = self.check("casual/a")
        self.assertEqual(rows["Sol Ring"]["in_use_elsewhere"], [("Deck B", 1)])
        self.assertEqual(rows["Wrath of God"]["in_use_elsewhere"], [("Deck C", 1)])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("casual/c has 'Built version: owned-only' but no Play-now list; counting its Planned list",
                      result["warnings"][0])
        assert_page_list_names(self, result["warnings"])

    def test_a_hand_named_built_deck_file_still_counts(self):
        self.deck("Deck_B_old", "Deck B (old)", "built", "Deck\n1 Sol Ring\n")
        loaded = pool.load_pool()
        self.assertEqual([(d.id, dict(d.cards)) for d in loaded.in_use], [("casual/Deck_B_old", {"Sol Ring": 1})])
        _, rows = self.check("casual/a")
        self.assertEqual(rows["Sol Ring"]["in_use_elsewhere"], [("Deck B (old)", 1)])

    def test_an_unreadable_product_is_a_warning(self):
        self.write("products/box.csv", "deck,name,set,collector_number,finish,quantity\n"
                   "Elves,Sol Ring,ecc,57,,1\n")
        self.status(("box.csv", "owned", "yes"))
        loaded = pool.load_pool()
        self.assertEqual(loaded.in_use, [])
        self.assertEqual(len(loaded.warnings), 1)
        self.assertIn("box.csv can't be read: box.csv line 2: bad finish ''", loaded.warnings[0])

    def test_idea_and_building_decks_hold_nothing(self):
        self.deck("b", "Deck B", "building", "Deck\n2 Sol Ring\n")
        self.deck("c", "Deck C", "idea", "Deck\n2 Sol Ring\n")
        result, rows = self.check("casual/a")
        self.assertEqual((rows["Sol Ring"]["in_use_elsewhere"], rows["Sol Ring"]["missing"]), ([], 0))
        self.assertEqual(result["conflicts"], [])

    def test_intact_product_decks_hold_their_cards(self):
        self.beginner_box()
        self.deck("a", "A", "idea", "Deck\n2 Llanowar Elves\n1 Elvish Mystic\n")
        result, rows = self.check("casual/a")
        self.assertEqual(rows["Llanowar Elves"]["in_use_elsewhere"],
                         [(f"Elves ({BB})", 1), (f"Cats ({BB})", 1)])
        self.assertEqual((rows["Llanowar Elves"]["available"], rows["Llanowar Elves"]["missing"]), (0, 2))
        self.assertEqual(rows["Elvish Mystic"]["missing"], 1)
        self.assertEqual({c["name"]: c["short"] for c in result["conflicts"]},
                         {"Llanowar Elves": 2, "Elvish Mystic": 1})

    def test_short_counts_only_the_copies_other_decks_take(self):
        # 1 owned and held by Deck B; A needs 3: 3 missing, but only 1 because of Deck B.
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 1))
        self.deck("b", "Deck B", "built", "Deck\n1 Sol Ring\n")
        self.deck("a", "A", "idea", "Deck\n3 Sol Ring\n")
        result, rows = self.check("casual/a")
        self.assertEqual(rows["Sol Ring"]["missing"], 3)
        self.assertEqual([(c["name"], c["short"]) for c in result["conflicts"]], [("Sol Ring", 1)])

    def test_conflict_that_leaves_enough_copies_is_not_short(self):
        self.beginner_box()
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 6))
        self.deck("a", "A", "idea", "Deck\n4 Llanowar Elves\n")
        result, rows = self.check("casual/a")
        self.assertEqual((rows["Llanowar Elves"]["available"], rows["Llanowar Elves"]["missing"]), (4, 0))
        self.assertEqual(result["conflicts"][0]["short"], 0)

    def test_products_not_kept_intact_hold_nothing(self):
        self.beginner_box()
        self.status(("fdn-beginner-box.csv", "owned", "no"))
        self.deck("a", "A", "idea", "Deck\n2 Llanowar Elves\n")
        _, rows = self.check("casual/a")
        self.assertEqual((rows["Llanowar Elves"]["in_use_elsewhere"], rows["Llanowar Elves"]["missing"]),
                         ([], 0))

    def test_pool_lists_what_is_in_use(self):
        self.beginner_box()
        self.deck("b", "Deck B", "built", "Deck\n1 Sol Ring\n17 Forest\n")
        loaded = pool.load_pool()
        self.assertEqual([(d.id, d.why, dict(d.cards)) for d in loaded.in_use], [
            ("casual/b", "built", {"Sol Ring": 1}),
            ("product/fdn-beginner-box/elves", "intact product", {"Llanowar Elves": 1, "Elvish Mystic": 1}),
            ("product/fdn-beginner-box/cats", "intact product", {"Llanowar Elves": 1, "Pick Your Poison": 1}),
            ("product/fdn-beginner-box/goblins", "intact product", {"Aerie Mystics": 1}),
        ])


class SelfExclusionTests(PoolTestCase):

    def test_a_built_deck_file_does_not_hold_cards_against_itself(self):
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 1))
        self.deck("b", "Deck B", "built", "Deck\n1 Sol Ring\n", owned="Deck\n1 Sol Ring\n")
        for version in ("target", "owned"):
            _, rows = self.check("casual/b", version)
            self.assertEqual((rows["Sol Ring"]["in_use_elsewhere"], rows["Sol Ring"]["missing"]), ([], 0))

    def test_a_product_half_does_not_hold_cards_against_itself(self):
        self.beginner_box()
        _, rows = self.check("product/fdn-beginner-box/elves")
        # Cats still holds its own Llanowar Elves; Elves' copy is this deck's.
        self.assertEqual(rows["Llanowar Elves"]["in_use_elsewhere"], [(f"Cats ({BB})", 1)])
        self.assertEqual((rows["Llanowar Elves"]["available"], rows["Llanowar Elves"]["missing"]), (1, 0))
        self.assertEqual(rows["Elvish Mystic"]["in_use_elsewhere"], [])

    def test_a_pairing_excludes_both_halves(self):
        self.beginner_box()
        for deck_id in ("pairing/cats+elves", "pairing/elves+cats"):
            result, rows = self.check(deck_id)
            self.assertEqual(rows["Llanowar Elves"]["need"], 2)
            self.assertEqual((rows["Llanowar Elves"]["in_use_elsewhere"], rows["Llanowar Elves"]["missing"]),
                             ([], 0))
            self.assertEqual(result["conflicts"], [])

    def test_a_pairing_still_counts_the_other_halves(self):
        self.beginner_box()
        self.product("fdn-beginner-box.csv",
                     ("Elves", "Llanowar Elves", 1), ("Cats", "Pick Your Poison", 1),
                     ("Goblins", "Llanowar Elves", 1))
        _, rows = self.check("pairing/elves+cats")
        self.assertEqual(rows["Llanowar Elves"]["in_use_elsewhere"], [(f"Goblins ({BB})", 1)])
        self.assertEqual(rows["Llanowar Elves"]["available"], 1)

    def test_self_ids(self):
        self.beginner_box()
        self.assertEqual(pool.self_ids("casual/a"), {"casual/a"})
        self.assertEqual(pool.self_ids("pairing/goblins+cats"),
                         {"pairing/goblins+cats", "product/fdn-beginner-box/cats",
                          "product/fdn-beginner-box/goblins"})
        self.assertEqual(pool.self_ids("pairing/nope+cats"), {"pairing/nope+cats"})


class MathAndPriceTests(PoolTestCase):

    def test_missing_and_available_never_go_negative(self):
        # Two built decks claim 4 Sol Rings between them, but only 3 exist.
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 3),
                       ("Wrath of God", "8ed", "58", "nonfoil", 9))
        self.deck("b", "Deck B", "built", "Deck\n2 Sol Ring\n")
        self.deck("c", "Deck C", "built", "Deck\n2 Sol Ring\n")
        self.deck("a", "A", "idea", "Deck\n2 Sol Ring\n2 Wrath of God\n")
        _, rows = self.check("casual/a")
        self.assertEqual((rows["Sol Ring"]["available"], rows["Sol Ring"]["missing"]), (0, 2))
        self.assertEqual((rows["Wrath of God"]["owned"], rows["Wrath of God"]["missing"]), (9, 0))
        rows_out, _, prices = pool.table_rows(pool.owned_vs_needed("casual/a", prices=False))
        self.assertIsNone(prices)
        self.assertEqual([(r.card, r.need, r.owned, r.missing) for r in rows_out],
                         [("Sol Ring", 2, 0, 2), ("Wrath of God", 2, 2, 0)])

    def test_rows_put_missing_cards_first_then_go_by_name(self):
        self.cards_csv("collection.csv", ("Wrath of God", "8ed", "58", "nonfoil", 2))
        self.deck("a", "A", "idea", "Deck\n2 Wrath of God\n1 Sol Ring\n1 Black Lotus\n")
        result, _ = self.check("casual/a")
        self.assertEqual([r["name"] for r in result["rows"]], ["Black Lotus", "Sol Ring", "Wrath of God"])

    def test_prices_for_missing_copies(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 1))
        self.deck("a", "A", "idea", "Deck\n3 Llanowar Elves\n1 Black Lotus\n")
        result, rows = self.check("casual/a", prices=True)
        # Cheapest non-foil paper Llanowar Elves in the fixtures: m19 at US$0.20.
        row = rows["Llanowar Elves"]
        self.assertEqual((row["aud_each"], row["aud_missing"], row["priced_printing"]), (0.4, 0.8, "M19 314"))
        self.assertIsNone(rows["Black Lotus"]["aud_each"])      # no usable paper price
        self.assertEqual(result["totals"], {"cards": 2, "need": 4, "missing": 3,
                                            "aud_missing": 0.8, "unpriced": ["Black Lotus"]})
        self.assertEqual((result["rate"], result["rate_date"], result["price_date"], result["price_error"]),
                         (2.0, "2026-09-28", "2026-09-28", None))

    def test_no_exchange_rate_means_no_prices(self):
        self.deck("a", "A", "idea", "Deck\n1 Sol Ring\n")
        with mock.patch.object(cards, "usd_to_aud", side_effect=RuntimeError("offline, nothing cached")):
            result, rows = self.check("casual/a", prices=True)
        self.assertEqual(result["price_error"], "offline, nothing cached")
        self.assertIsNone(rows["Sol Ring"]["aud_each"])
        self.assertIsNone(result["totals"]["aud_missing"])
        rows_out, total, prices = pool.table_rows(result)
        # None: no price was worked out (set_table keeps old cells that still apply).
        self.assertEqual((rows_out[0].aud_each, total, prices), (None, decks.TotalRow(1, None), None))

    def test_an_index_without_a_price_date_means_no_prices(self):
        # cards.update() records "unknown" when bulk.json is missing; a stamp
        # "pulled unknown" wouldn't read back, and AGENTS.md wants the date.
        self.deck("a", "A", "idea", "Deck\n1 Sol Ring\n")
        for bad in ("unknown", ""):
            with self.subTest(bad), mock.patch.object(cards, "price_date", return_value=bad):
                result, rows = self.check("casual/a", prices=True)
                self.assertIn("doesn't say when Scryfall's prices were pulled", result["price_error"])
                self.assertEqual((result["rate"], result["price_date"], rows["Sol Ring"]["aud_each"]),
                                 (None, None, None))
                self.assertIsNone(pool.table_rows(result)[2])

    def test_a_card_with_only_foil_or_etched_prices_says_so(self):
        self.deck("a", "A", "idea", "Deck\n2 Abaddon the Despoiler\n")
        result, rows = self.check("casual/a", prices=True)
        self.assertEqual((rows["Abaddon the Despoiler"]["aud_each"], rows["Abaddon the Despoiler"]["priced_printing"]),
                         (0.84, "40K 319 etched"))
        self.assertEqual(decks.format_table_row(pool.table_rows(result)[0][0]),
                         "| Abaddon the Despoiler | 2 | 0 | **2** | ~$0.84 (etched) | ~$1.68 |  |")
        # The command line says so too.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pool._print_result(result)
        line = next(l for l in out.getvalue().splitlines() if l.startswith("Abaddon"))
        self.assertTrue(line.endswith("0.84        1.68  (etched price)"), line)

    def test_unknown_deck(self):
        with self.assertRaises(decks.DeckNotFound):
            pool.owned_vs_needed("casual/nope")
        self.deck("a", "A", "idea", "Deck\n1 Sol Ring\n")
        with self.assertRaises(decks.DeckNotFound):
            pool.owned_vs_needed("casual/a", "owned")

    def test_compare_takes_an_unsaved_list(self):
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 1))
        self.deck("b", "Deck B", "built", "Deck\n1 Sol Ring\n")
        sections = decks.parse_decklist("Deck\n1 Sol Ring\n")
        loaded = pool.load_pool()
        self.assertEqual(pool.compare(sections, loaded, prices=False)["rows"][0]["missing"], 1)
        self.assertEqual(pool.compare(sections, loaded, {"casual/b"}, prices=False)["rows"][0]["missing"], 0)


class TableRowTests(PoolTestCase):

    TABLE = ("| Llanowar Elves | 4 | 4 | 0 | | | keep these |\n"
             "| Sol Ring | 1 | 0 | **1** | ~$9.99 | ~$9.99 |  |\n"
             "| **Total to buy** | | | **1** | | **~$9.99** | |\n")

    def setUp(self):
        super().setUp()
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 1),
                       ("Sol Ring", "ecc", "57", "nonfoil", 5),
                       ("Wrath of God", "8ed", "58", "nonfoil", 1))
        self.deck("a", "A", "idea",
                  "Deck\n4 Llanowar Elves\n1 Sol Ring\n2 Wrath of God\n10 Forest\n\nSideboard\n1 Black Lotus\n",
                  table=self.TABLE)

    STAMP = decks.PriceStamp(2.0, "2026-09-28", "2026-09-28")
    NOTE = ("Prices are **estimates in AUD**: Scryfall's cheapest paper non-foil printing (USD), "
            "converted at 1 USD = 2.0 AUD (ECB rate of 2026-09-28), pulled 2026-09-28.")

    def test_rows_in_the_files_order_and_format(self):
        rows, total, prices = pool.table_rows(pool.owned_vs_needed("casual/a"))
        self.assertEqual([decks.format_table_row(r) for r in rows] + [decks.format_total_row(total)], [
            "| Black Lotus | 1 | 0 | **1** | no price | |  |",
            "| Llanowar Elves | 4 | 1 | **3** | ~$0.40 | ~$1.20 |  |",
            "| Wrath of God | 2 | 1 | **1** | ~$9.60 | ~$9.60 |  |",
            "| Sol Ring | 1 | 1 | 0 | | |  |",      # 5 owned, capped at Need
            # The total says what it leaves out.
            "| **Total to buy** | | | **5** | | **~$10.80** | not counted, no price: Black Lotus |",
        ])
        self.assertEqual(prices, self.STAMP)

    def test_rows_go_into_the_deck_file_keeping_notes(self):
        deck = decks.read_deck_file(self.magic / "decks" / "casual" / "a.md")
        decks.set_table(deck, *pool.table_rows(pool.owned_vs_needed("casual/a")))
        # Only the table changes, and the rate it was priced at goes above it;
        # Llanowar Elves keeps its note.
        self.assertEqual(decks.render_deck_file(deck), deck.text.replace(
            decks.TABLE_HEADER, f"{self.NOTE}\n\n{decks.TABLE_HEADER}").replace(self.TABLE, (
                "| Black Lotus | 1 | 0 | **1** | no price | |  |\n"
                "| Llanowar Elves | 4 | 1 | **3** | ~$0.40 | ~$1.20 | keep these |\n"
                "| Wrath of God | 2 | 1 | **1** | ~$9.60 | ~$9.60 |  |\n"
                "| Sol Ring | 1 | 1 | 0 | | |  |\n"
                "| **Total to buy** | | | **5** | | **~$10.80** | not counted, no price: Black Lotus |\n")))

    def test_an_old_rate_above_the_table_is_replaced(self):
        old = "Prices converted at 1 USD = 1.4224 AUD (ECB rate of 2026-09-25), pulled 2026-09-26; see buylist."
        self.deck("a", "A", "idea", "Deck\n1 Sol Ring\n", table=self.TABLE, note=old)
        deck = decks.read_deck_file(self.magic / "decks" / "casual" / "a.md")
        decks.set_table(deck, *pool.table_rows(pool.owned_vs_needed("casual/a")))
        text = decks.render_deck_file(deck)
        self.assertIn("\nPrices converted at 1 USD = 2.0 AUD (ECB rate of 2026-09-28), pulled 2026-09-28; "
                      "see buylist.\n\n| Card |", text)
        self.assertEqual(decks.parse_deck(text.encode(), "a", "casual").prices, self.STAMP)

    def test_labels_for_cards_on_the_way_and_cards_other_decks_hold(self):
        # AGENTS.md: label on-the-way cards, and flag conflicts with other decks.
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 1),
                       ("Wrath of God", "8ed", "58", "nonfoil", 1))
        self.cards_csv("orders/2026-10-01-test.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        self.deck("b", "Deck B", "built", "Deck\n1 Wrath of God\n")
        self.deck("a", "A", "idea", "Deck\n2 Llanowar Elves\n1 Sol Ring\n1 Wrath of God\n", table=(
            "| Llanowar Elves | 2 | 0 | **2** | | | on the way (Old precon); keep these |\n"
            "| Sol Ring | 1 | 1 | 0 | | | on the way (Old precon) |\n"
            "| **Total to buy** | | | **2** | | | |\n"))
        deck = decks.read_deck_file(self.magic / "decks" / "casual" / "a.md")
        decks.set_table(deck, *pool.table_rows(pool.owned_vs_needed("casual/a")))
        rows = {r.card: r.notes for r in decks.parse_deck(decks.render_deck_file(deck).encode(), "a", "casual").rows}
        self.assertEqual(rows, {
            "Llanowar Elves": "2 on the way (order 2026-10-01-test); keep these",
            "Sol Ring": "",                                     # arrived: the old label goes
            "Wrath of God": "1 in use in Deck B",
        })

    def test_on_the_way_labels_count_only_the_copies_this_deck_uses(self):
        self.cards_csv("orders/2026-10-01-test.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 1),
                       ("Sol Ring", "ecc", "57", "nonfoil", 1))
        self.product("angels.csv", ("deck", "Sol Ring", 1), column="section")
        self.product("zombies.csv", ("deck", "Sol Ring", 1), column="section")
        self.status(("angels.csv", "preordered", ""), ("zombies.csv", "preordered", ""))
        self.cards_csv("collection.csv", ("Wrath of God", "8ed", "58", "nonfoil", 1))
        self.deck("a", "A", "idea", "Deck\n3 Llanowar Elves\n2 Sol Ring\n1 Wrath of God\n")
        rows, _, _ = pool.table_rows(pool.owned_vs_needed("casual/a"))
        self.assertEqual([(r.card, r.owned, r.missing, r.labels) for r in rows], [
            # 1 of the 3 is coming; the other 2 still have to be bought.
            ("Llanowar Elves", 1, 2, ("1 on the way (order 2026-10-01-test)",)),
            # 3 are coming and 2 are needed: the order's, then the first precon's.
            ("Sol Ring", 2, 0, ("1 on the way (order 2026-10-01-test)", "1 on the way (angels, preordered)")),
            ("Wrath of God", 1, 0, ()),
        ])
        # row_labels is the same as data, for the page.
        result = {r["name"]: pool.row_labels(r) for r in pool.owned_vs_needed("casual/a")["rows"]}
        self.assertEqual(result, {
            "Llanowar Elves": {"on_the_way": [("order 2026-10-01-test", 1)], "in_use": []},
            "Sol Ring": {"on_the_way": [("order 2026-10-01-test", 1), ("angels, preordered", 1)],
                         "in_use": []},
            "Wrath of God": {"on_the_way": [], "in_use": []}})

    def test_labels_name_each_deck_even_with_separators_in_its_title(self):
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 2))
        self.deck("b", "Gruul Ramp; big creatures", "built", "Deck\n1 Sol Ring\n")
        self.deck("c", "Finneas, Ace Archer: Rabbits | Tokens", "built", "Deck\n1 Sol Ring\n")
        self.deck("a", "A", "idea", "Deck\n1 Sol Ring\n", table="| **Total to buy** | | | **0** | | | |\n")
        path = self.magic / "decks" / "casual" / "a.md"
        loaded = pool.load_pool()
        for _ in range(3):                       # every save gives the same cell
            deck = decks.read_deck_file(path)
            decks.set_table(deck, *pool.deck_table(deck, loaded, prices=False))
            deck_files.write_deck_file(path, decks.render_deck_file(deck), deck.sha256)
        self.assertEqual(decks.read_deck_file(path).rows[0].notes,
                         "1 in use in Gruul Ramp, big creatures; 1 in use in Finneas, Ace Archer: Rabbits / Tokens")

    def test_the_table_always_describes_the_target_list(self):
        self.deck("a", "A", "idea", "Deck\n4 Llanowar Elves\n1 Sol Ring\n", owned="Deck\n1 Llanowar Elves\n",
                  table=self.TABLE)
        with self.assertRaisesRegex(ValueError, "describes its target list"):
            pool.table_rows(pool.owned_vs_needed("casual/a", "owned"))
        # Rows for any other list (here the owned-only one) are refused too.
        deck = decks.read_deck_file(self.magic / "decks" / "casual" / "a.md")
        rows = pool.table_rows(pool.compare(deck.owned, pool.load_pool(), prices=False))
        with self.assertRaisesRegex(ValueError, r"Llanowar Elves \(list 4, table 1\), Sol Ring \(list 1, table 0\)"):
            decks.set_table(deck, *rows)

    def test_deck_table_counts_an_edit_that_isnt_saved(self):
        # The decks package docstring's usage: edit the list, then work the table out from it.
        path = self.magic / "decks" / "casual" / "a.md"
        deck = decks.read_deck_file(path)
        deck.target["Deck"][0].quantity = 3                      # 4 -> 3 Llanowar Elves
        with self.assertRaisesRegex(ValueError, r"Llanowar Elves \(list 3, table 4\)"):
            decks.set_table(deck, *pool.table_rows(pool.owned_vs_needed("casual/a")))   # the list on disk
        decks.set_table(deck, *pool.deck_table(deck))
        again = decks.parse_deck(decks.render_deck_file(deck).encode(), "a", "casual")
        self.assertEqual(next(r for r in again.rows if r.card == "Llanowar Elves").need, 3)
        self.assertEqual(again.target["Deck"][0].quantity, 3)

    def test_a_rewrite_without_prices_keeps_the_prices_that_still_apply(self):
        path = self.magic / "decks" / "casual" / "a.md"
        deck = decks.read_deck_file(path)
        decks.set_table(deck, *pool.deck_table(deck))
        deck_files.write_deck_file(path, decks.render_deck_file(deck), deck.sha256)
        priced = path.read_text(encoding="utf-8")
        # No prices and nothing changed: the file stays as it is.
        deck = decks.read_deck_file(path)
        decks.set_table(deck, *pool.deck_table(deck, prices=False))
        self.assertEqual(decks.render_deck_file(deck), priced)
        # A card's counts change: its cells and the total go blank, the rest
        # keep the prices the rate line above them describes.
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2),
                       ("Sol Ring", "ecc", "57", "nonfoil", 5), ("Wrath of God", "8ed", "58", "nonfoil", 1))
        with mock.patch.object(cards, "usd_to_aud", side_effect=RuntimeError("offline, nothing cached")):
            decks.set_table(deck, *pool.deck_table(deck))
        self.assertEqual(decks.render_deck_file(deck), priced.replace(
            "| Llanowar Elves | 4 | 1 | **3** | ~$0.40 | ~$1.20 | keep these |",
            "| Llanowar Elves | 4 | 2 | **2** | | | keep these |").replace(
            "| **Total to buy** | | | **5** | | **~$10.80** |", "| **Total to buy** | | | **4** | | |"))
        self.assertIn(self.NOTE, priced)

    def test_a_row_named_by_its_front_face_keeps_its_notes(self):
        self.cards_csv("collection.csv", ("Fire // Ice", "apc", "128", "nonfoil", 1))
        self.deck("a", "A", "idea", "Deck\n1 Fire\n", table="| Fire | 1 | 1 | 0 | | | the foil one |\n")
        deck = decks.read_deck_file(self.magic / "decks" / "casual" / "a.md")
        decks.set_table(deck, *pool.deck_table(deck, prices=False))
        self.assertEqual([(r.card, r.notes) for r in deck.rows], [("Fire // Ice", "the foil one")])

    def test_no_label_when_arrived_copies_are_enough(self):
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 1),
                       ("Wrath of God", "8ed", "58", "nonfoil", 3))
        self.cards_csv("orders/2026-10-01-test.csv", ("Sol Ring", "ecc", "57", "nonfoil", 1))
        self.deck("b", "Deck B", "built", "Deck\n1 Wrath of God\n")
        self.deck("a", "A", "idea", "Deck\n1 Sol Ring\n2 Wrath of God\n")
        rows, _, _ = pool.table_rows(pool.owned_vs_needed("casual/a"))
        self.assertEqual([(r.card, r.labels) for r in rows], [("Sol Ring", ()), ("Wrath of God", ())])


class EditorHelperTests(PoolTestCase):
    """printing_counts (the printing picker) and the stale-table check."""

    TABLE = "| Llanowar Elves | 4 | 4 | 0 | | | mine |\n| **Total to buy** | | | **0** | | | |\n"

    def test_printing_counts(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2),
                       ("Llanowar Elves", "FDN", "227", "nonfoil", 1), ("Forest", "fdn", "291", "foil", 3),
                       ("Sol Ring", "ecc", "57", "nonfoil", "x"))
        self.cards_csv("orders/2026-10-01-shop.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.cards_csv("orders/received/old.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 50))
        self.product("fdc-precon.csv", ("deck", "Sol Ring", 1), column="section")
        self.product("owned-box.csv", ("deck", "Opt", 1), column="section")
        self.status(("fdc-precon.csv", "preordered", ""), ("owned-box.csv", "owned", "no"))
        counts = pool.printing_counts()
        self.assertEqual(counts[("fdn", "227", "nonfoil")], {"owned": 3, "on_the_way": 4})
        self.assertEqual(counts[("fdn", "291", "foil")], {"owned": 3, "on_the_way": 0})     # special basics count
        self.assertEqual(counts[("tst", "1", "nonfoil")], {"owned": 0, "on_the_way": 1})    # the preordered precon
        self.assertNotIn(("ecc", "57", "nonfoil"), counts)                                  # a bad row is skipped

    def test_stale_tables(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.deck("a", "A", "building", "Deck\n4 Llanowar Elves\n", table=self.TABLE)
        self.deck("b", "B", "idea", "Deck\n2 Llanowar Elves\n")                 # no table: never stale
        self.deck("Bad_Name", "C", "idea", "Deck\n1 Llanowar Elves\n", table=self.TABLE)
        self.assertEqual(pool.stale_tables(), [])
        self.deck("b", "B", "built", "Deck\n2 Llanowar Elves\n")                 # now B holds two
        stale = pool.stale_tables()
        self.assertEqual([(s["id"], s["title"], s["count"]) for s in stale], [("casual/a", "A", 1)])
        self.assertEqual(stale[0]["sha256"], decks.read_deck_file(self.magic / "decks/casual/a.md").sha256)
        self.assertEqual(stale[0]["changes"], [{"card": "Llanowar Elves",
                                                "was": {"need": 4, "owned": 4, "missing": 0, "labels": []},
                                                "now": {"need": 4, "owned": 2, "missing": 2,
                                                        "labels": ["2 in use in B"]}}])
        self.assertEqual(pool.stale_tables(exclude={"casual/a"}), [])
        # Rewriting the table (as update_tables does) brings it up to date.
        deck = decks.read_deck_file(self.magic / "decks/casual/a.md")
        decks.set_table(deck, *pool.deck_table(deck, prices=False))
        (self.magic / "decks/casual/a.md").write_text(decks.render_deck_file(deck), encoding="utf-8", newline="")
        self.assertEqual(pool.stale_tables(), [])
        self.assertIn("| Llanowar Elves | 4 | 2 | **2** | | | 2 in use in B; mine |", decks.render_deck_file(deck))

    def test_stale_tables_of_some_spaces_and_a_pool_that_cant_be_read(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.deck("a", "A", "building", "Deck\n4 Llanowar Elves\n", table=self.TABLE)
        self.deck("b", "B", "built", "Deck\n2 Llanowar Elves\n")
        self.assertEqual([s["id"] for s in pool.stale_tables(only={"home"})], ["casual/a"])
        self.assertEqual(pool.stale_tables(only={"user2"}), [])
        # A space whose pool can't be loaded leaves out only its decks (table_blockers names it).
        with mock.patch.object(pool, "for_space", side_effect=ValueError("bad row")):
            self.assertEqual(pool.stale_tables(), [])
            found = pool.table_blockers()
        self.assertEqual(found["spaces"], [])       # table_blockers loads with load_pool, not for_space
        with mock.patch.object(pool, "load_pool", side_effect=ValueError("bad row")):
            found = pool.table_blockers()
        self.assertEqual(found["spaces"], [{"space": "home", "warnings": [], "unknown": [],
                                            "why": "home's card pool can't be read: bad row"}])


class CommandLineTests(PoolTestCase):

    def run_main(self, *argv):
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")     # main() reconfigures stdout
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pool.main(list(argv))
        out.flush()
        return code, out.buffer.getvalue().decode("utf-8"), err.getvalue()

    def test_problems_are_reported_without_a_traceback(self):
        self.deck("a", "A", "idea", "Deck\n1 Sol Ring\n")
        self.assertEqual(self.run_main("casual/a", "--no-prices")[0], 0)
        # No card index yet (a fresh clone, or the cache deleted).
        with mock.patch.object(cards, "_index", None), \
                mock.patch.object(cards, "INDEX_FILE", self.magic / "no-index.json.gz"):
            code, out, err = self.run_main("casual/a", "--no-prices")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("Run: python -m decklab.lib.cards update", err)
        # A bad row in collection.csv, and a deck file with no decklist block.
        self.write("decks/casual/b.md", "# B\n\n- **Status:** idea\n\nNo list yet.\n")
        code, _, err = self.run_main("casual/b")
        self.assertEqual(code, 1)
        self.assertIn("no fenced decklist block", err)
        self.write("collection.csv", ",".join(CARD_COLUMNS) + "\nSol Ring,ecc,57,nonfoil,lots,NM,en,\n")
        code, _, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("line 2: bad quantity 'lots'", err)


class ListNameMessageTests(unittest.TestCase):
    """The messages a deck's list problems raise reach the page too (the library tile, the editor, a save's
    error), so they name the lists Planned and Play-now as well."""

    def test_a_deck_without_a_decklist_names_the_planned_list(self):
        self.assertIn("Planned list", decks.NO_DECKLIST)
        assert_page_list_names(self, [decks.NO_DECKLIST])

    def test_a_table_that_doesnt_match_the_list_names_the_planned_list(self):
        text = ("# Red Burn\n\n## Decklist\n\n```\nDeck\n4 Lightning Bolt\n```\n\n## Owned vs needed\n\n"
                "| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |\n"
                "|---|---|---|---|---|---|---|\n")
        deck = decks.parse_deck(text.encode("utf-8"), "red-burn", "casual")
        with self.assertRaises(ValueError) as caught:
            decks.set_table(deck, [decks.TableRow("Lightning Bolt", 3, 1, 2)], decks.TotalRow(2))
        self.assertIn("must describe the Planned list as it is now", str(caught.exception))
        assert_page_list_names(self, [str(caught.exception)])


class RealStatusFileTests(unittest.TestCase):
    """The real magic/products/status.csv (no card data needed), as tag pre-db-inventory holds it
    (the database holds the inventory since the cutover), read through the files backend."""

    def setUp(self):
        self.addCleanup(inventory.use(pre_db.inventory()))

    def test_every_product_is_listed_once_with_valid_values(self):
        path = pre_db.tree() / "magic" / "products" / pool.STATUS_NAME
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(reader.fieldnames, rules.STATUS_FIELDS)
        files = [r["file"] for r in rows]
        self.assertEqual(files, sorted(files))
        self.assertEqual(files, sorted(p.name for p in path.parent.glob("*.csv") if p != path))
        for r in rows:
            self.assertIn(r["status"], pool.PRODUCT_STATUSES, r["file"])
            self.assertIn(r["intact"], ("yes", "no", ""), r["file"])
            if not (r["status"] == "owned" and r["intact"] == "yes"):
                self.assertEqual((r["sleeves"], r["deck_box"]), ("", ""), r["file"])
        warnings = []
        pool.read_status(warnings)
        self.assertEqual(warnings, [])

    def test_the_deck_library_skips_status_csv(self):
        ids = [d["id"] for d in decks.list_decks()]
        self.assertFalse([i for i in ids if "status" in i])


if __name__ == "__main__":
    unittest.main()
