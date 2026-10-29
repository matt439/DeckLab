"""The inventory foundation (decklab/lib/inventory): FileInventory reads every inventory file
without raising and renders today's files back byte for byte (the real repo's, read from git's
blobs at the golden commit golden_dump.GOLDEN_REV, so these tests still hold now that the
cutover removed the files, and fixtures for the header styles the repo doesn't have); its problems carry today's
readers' texts; apply writes only what an operation changed, settled and checked as the database
backend does (changes.prepare), as plain files and with no commit; and the package's backend
choice, use(), pinned() and the operation registry behave as documented.

The old names (tokens.rows; collection_edit.csv_bytes) are the same objects as inventory.rules'."""
import contextlib
import csv
import dataclasses
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.tests import golden_dump as gate
from decklab.lib import config, inventory, pool, state, tokens
from decklab.lib.inventory import files, model, paths, rules
from decklab.lib.inventory.files import FileInventory
from decklab.tests import test_pool
from decklab.tests.test_api import Sandbox

ACTOR = state.Actor("test", "Test", source="test")
CARD_HEADER = ",".join(rules.FIELDS) + "\n"
TOKEN_HEADER = ",".join(rules.TOKEN_FIELDS) + "\n"


def _write(root, rel, data):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


def _has_commit(sha):
    """Whether this checkout's git history has that commit (a copy without the old history hasn't)."""
    try:
        done = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=Path(__file__).resolve().parent,
                              capture_output=True)
    except OSError:
        return False
    return done.returncode == 0


class TempRoot(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, rel, data):
        return _write(self.root, rel, data)

    def load(self):
        return FileInventory(self.root).load()


class RealRepoRoundTripTests(unittest.TestCase):
    """The golden commit's blobs: load, then render, gives every file back byte for byte."""

    @classmethod
    def setUpClass(cls):
        if not _has_commit(gate.GOLDEN_REV):
            raise unittest.SkipTest(f"this checkout's history has no golden commit {gate.GOLDEN_REV[:7]}")
        cls.sha, cls.blobs = files.git_files(gate.GOLDEN_REV)
        cls.inv = files.build(cls.blobs)

    def test_every_inventory_file_renders_byte_for_byte(self):
        rendered = files.render(self.inv)
        expected = {rel: data for rel, data in self.blobs.items() if paths.classify(rel)[0] != "import"}
        self.assertEqual(sorted(rendered), sorted(expected))
        for rel, data in expected.items():
            with self.subTest(rel=rel):
                self.assertEqual(rendered[rel], data)

    def test_the_real_data_loads_cleanly(self):
        inv = self.inv
        self.assertEqual(inv.unreadable, {})
        self.assertTrue(inv.orders and inv.products and inv.payloads and inv.watchlist.rows)
        self.assertEqual(inv.spaces()[0], "home")
        self.assertEqual(inv.loose_payloads, [])
        self.assertEqual(inv.token_set().problems, ())
        self.assertTrue(inv.token_set().sorted)
        for sheet in inv.collections.values():
            self.assertEqual((sheet.problems, sheet.strict_error), ((), None), sheet.path)
        # Every product header style there is now (deck, section, plain, in_play_boosters).
        styles = {p.columns[0] if p.columns[0] in ("deck", "section") else
                  ("in_play_boosters" if "in_play_boosters" in p.columns else "plain") for p in inv.products}
        self.assertEqual(styles, {"deck", "section", "plain", "in_play_boosters"})
        for order in inv.orders:
            self.assertIsNone(order.error, order.file)
            self.assertEqual(list(order.data)[:7], ["version", "id", "seller", "ordered_on", "sources", "notes",
                                                    "components"])

    def test_records_and_products_match_todays_readers(self):
        from decklab.lib import purchases
        with tempfile.TemporaryDirectory() as temp:
            for rel, data in self.blobs.items():
                _write(temp, rel, data)
            for rel in {s for o in self.inv.orders for s in o.sources}:
                _write(temp, rel, b"")                       # read_records checks they exist
            records = purchases.read_records(temp)
        self.assertEqual([o.record() for o in self.inv.orders], records)
        for product in self.inv.products:
            info = files.PRODUCT_NAMES.get(product.stem)
            self.assertEqual((product.name, product.format), info or (None, None))

    def test_a_working_tree_and_crlf_files_load_the_same(self):
        # A checkout with core.autocrlf: records and CSVs alike may be CRLF on disk. Imports keep
        # their blob bytes here (their size counts in the revision; a checkout that rewrote them
        # would change it, as it would their content).
        with tempfile.TemporaryDirectory() as temp:
            for rel, data in self.blobs.items():
                crlf = paths.classify(rel)[0] != "import"
                _write(temp, rel, data.replace(b"\n", b"\r\n") if crlf else data)
            tree = FileInventory(temp).load()
        self.assertEqual(tree.revision, self.inv.revision)
        self.assertEqual(tree, self.inv)


class FixtureRoundTripTests(TempRoot):
    """Header styles and record keys the real data doesn't have today."""

    def assertRoundTrip(self, rel, data):
        self.write(rel, data)
        rendered = files.render(self.load())
        self.assertEqual(rendered[rel], data if isinstance(data, bytes) else data.encode("utf-8"))

    def test_legacy_status_header_stays_four_columns(self):
        self.assertRoundTrip("magic/products/status.csv", "file,status,intact,notes\nx.csv,preordered,,soon\n")
        status = self.load().status
        self.assertEqual(status.columns, tuple(rules.LEGACY_STATUS_FIELDS))
        self.assertIsNone(status.rows[0].sleeves)
        self.assertIsNone(status.strict_error)

    def test_six_column_status_and_every_product_style(self):
        self.assertRoundTrip("magic/products/status.csv", "file,status,intact,sleeves,deck_box,notes\n"
                                                          "a.csv,owned,yes,red,box,\n")
        for stem, header in (("a", "deck,name,set,collector_number,finish,quantity,rarity,notes"),
                             ("b", "section,name,set,collector_number,finish,quantity,rarity,notes"),
                             ("c", "name,set,collector_number,finish,quantity,rarity,notes"),
                             ("d", "name,set,collector_number,finish,quantity,rarity,in_play_boosters,notes")):
            first = "Elves," if header.startswith(("deck", "section")) else ""
            self.assertRoundTrip(f"magic/products/{stem}.csv",
                                 f"{header}\n{first}\"Card, With Comma\",tst,1,nonfoil,2,common,{'3,' if stem == 'd' else ''}\n")
        products = {p.stem: p for p in self.load().products}
        self.assertEqual([products[s].is_deck for s in "abcd"], [True, True, False, False])
        self.assertEqual(products["a"].items[0].name, "Card, With Comma")
        self.assertEqual(products["a"].label("deck"), ("A", "Product deck"))
        self.assertEqual(products["a"].label("pool"), "a")

    def test_record_key_order_with_audit_notes_and_verified_checks(self):
        record = {"version": 1, "id": "2026-10-01-shop", "seller": "", "ordered_on": "", "sources": [],
                  "notes": "Ünïcode", "components": [
                      {"id": "cards", "kind": "cards", "path": "magic/orders/received/2026-10-01-shop.csv",
                       "status": "received", "received_on": "", "checks": [], "verified_checks": ["condition"]}],
                  "audit_notes": "from git"}
        data = rules.json_bytes(record)
        self.assertRoundTrip("magic/orders/records/2026-10-01-shop.json", data)
        order = self.load().order("2026-10-01-shop")
        self.assertEqual((order.audit_notes, order.components[0].verified_checks), ("from git", ["condition"]))
        built = model.Order.build("2026-10-01-shop", notes="Ünïcode", audit_notes="from git", components=[
            model.Component.build("cards", "cards", "2026-10-01-shop.csv", "received", verified_checks=["condition"])])
        self.assertEqual(files.render_order(built), data)

    def test_tokens_and_watchlist_round_trip(self):
        self.assertRoundTrip("magic/tokens.csv", TOKEN_HEADER + "Dog,Beast,,,,,1,,3/3,\"a, b\"\n"
                                                                "Zombie,,tdsk,2,,nonfoil,2,2/2,,single-sided verified\n")
        self.assertRoundTrip("magic/watchlist.csv", ",".join(model.QUEUE_FIELDS) + "\n"
                             "Clifftop Retreat,frc,67,nonfoil,2,The Free Peoples,any,0.50,Ronin Games,no,"
                             "2026-10-05,,waiting_for_stock,magic/buylists/x.md\n")
        inv = self.load()
        self.assertEqual([r.id for r in inv.token_set().rows], [1, 2])
        self.assertEqual(inv.watchlist.rows[0].for_deck, "The Free Peoples")
        self.assertEqual(inv.watchlist.rows[0].qty, 2)

    def test_a_bom_and_crlf_come_back_canonical(self):
        self.write("magic/collection.csv", b"\xef\xbb\xbf" + (CARD_HEADER + "Opt,dom,60,nonfoil,1,,,\n")
                   .replace("\n", "\r\n").encode())
        rendered = files.render(self.load())["magic/collection.csv"]
        self.assertEqual(rendered, (CARD_HEADER + "Opt,dom,60,nonfoil,1,,,\n").encode())

    def test_payloads_go_by_folder(self):
        for rel in ("magic/orders/a.csv", "magic/orders/received/b.csv", "magic/orders/cancelled/c.csv"):
            self.write(rel, CARD_HEADER + "Opt,dom,60,nonfoil,1,,,\n")
        self.write("magic/orders/tokens/t.csv", TOKEN_HEADER + "Dog,,,,,,1,,,\n")
        self.write("magic/orders/tokens/u.csv", TOKEN_HEADER + "Dog,,,,,,0,,,\n")
        self.write("magic/orders/records/r.json", rules.json_bytes(model.Order.build("r", components=[
            model.Component.build("cards", "cards", "a.csv")]).data))
        inv = self.load()
        self.assertEqual(sorted(inv.payloads), ["magic/orders/a.csv", "magic/orders/cancelled/c.csv",
                                                "magic/orders/received/b.csv", "magic/orders/tokens/t.csv",
                                                "magic/orders/tokens/u.csv"])
        self.assertIsInstance(inv.payloads["magic/orders/tokens/t.csv"].rows[0], model.TokenRow)
        self.assertEqual(inv.pending_payloads(), ["magic/orders/a.csv"])
        self.assertEqual(inv.loose_payloads, [])
        # receive_order.token_rows' complaint, as tokens.incoming() shows it (paths relative).
        self.assertIsNone(inv.payloads["magic/orders/tokens/t.csv"].strict_error)
        self.assertEqual(inv.payloads["magic/orders/tokens/u.csv"].strict_error,
                         "Row 1 of order u's token cards: tokens need a front name and positive physical quantity")


class ProblemTextTests(TempRoot):
    """What FileInventory says about a bad file is what today's readers say."""

    def test_collection_problems_are_pools(self):
        text = CARD_HEADER + "Opt,dom,60,nonfoil,x,,,\n,dom,61,nonfoil,1,,,\nShock,m19,156,nonfoil,-1,,,\n"
        path = self.write("magic/collection.csv", text)
        problems = []
        sheet = self.load().collection()
        pool.read_card_csv(sheet, {}, problems)         # the ported pool reads the sheet's rows
        self.assertEqual(list(sheet.problems), problems)
        self.assertEqual(sheet.problems[0], "Row 1 of the home collection: bad quantity 'x'")
        self.assertEqual([r.qty for r in sheet.rows], [None, 1, None])
        with self.assertRaises(rules.InvalidCards) as caught, path.open(newline="", encoding="utf-8-sig") as f:
            rules.parse_cards(f, "the home collection", existing=True, numbered=True)
        self.assertEqual(sheet.strict_error, str(caught.exception))
        self.assertTrue(sheet.strict_error.startswith("Row 1 of the home collection: "), sheet.strict_error)

    def test_a_short_row_and_a_missing_column(self):
        self.write("magic/collection.csv", "name,set\nOpt\n")
        sheet = self.load().collection()
        self.assertEqual(sheet.rows[0].get("set"), None)
        self.assertEqual(sheet.rows[0].get("quantity"), None)
        self.assertEqual(sheet.problems, ("Row 1 of the home collection: bad quantity None",))

    def test_undecodable_files_are_unreadable_not_fatal(self):
        self.write("magic/orders/2026-09-30-broken.csv", b"\xff\xfe not utf-8")
        self.write("magic/orders/records/bad.json", b"{\"id\": 1, \"id\": 2}")
        self.write("magic/collection.csv", CARD_HEADER)
        inv = self.load()
        self.assertIn("can't decode", inv.unreadable["magic/orders/2026-09-30-broken.csv"])
        self.assertEqual(inv.unreadable["magic/orders/records/bad.json"], "duplicate JSON key 'id'")
        self.assertEqual(files.render(inv).keys(), {"magic/collection.csv"})

    def test_status_problems_are_read_status_warnings(self):
        text = ("file,status,intact,notes\nx.csv,preorder,,\ny.csv,owned,maybe,\n")
        self.write("magic/products/status.csv", text)
        warnings = []
        with inventory.use(FileInventory(self.root)):   # the ported pool reads the inventory
            pool.read_status(warnings)
        self.assertEqual(list(self.load().status.problems), warnings)
        missing = FileInventory(self.root / "nothing").load().status
        self.assertEqual(missing.problems,
                         ("The products' status list is missing, so every product counts as owned and not intact",))
        self.assertEqual(warnings, ["Product x's status is 'preorder', not one of owned, preordered, ordered, cancelled; "
                                    "it is left out of every count",
                                    "Product y's status has intact 'maybe', not yes or no; treated as no"])

    def test_token_problems_are_tokens_reads(self):
        cases = {
            "good": TOKEN_HEADER + "Zombie,,,,,,2,,,\nDog,,,,,,1,,,\n",
            "bad rows": TOKEN_HEADER + "Zombie,,,,,,0,,,\nDog,,,,\n\n  ,  \nCat,,BAD,,,,1,,,\n",
            "legacy": "front,back,quantity,front_details,back_details,notes\nDog,Beast,1,,3/3,\n",
            "reordered": "back," + ",".join(f for f in rules.TOKEN_FIELDS if f != "back") + "\n,Dog,,,,,1,,,\n",
            "bad header": "front,back\nDog,\n",
            "bad csv": TOKEN_HEADER + "Dog,\"a\"b,,,,,1,,,\n",
            "not utf-8": b"\xff\xfe",
        }
        # What tokens.read() said of each file when it still read the file itself (lib/tokens at
        # 3b51965), written out: (problems, lines, rows, sorted, the strict read's error).
        must = "The home token cards' columns must be " + ",".join(rules.TOKEN_FIELDS)
        by_hand = "; it can't be changed until that's put right"
        printing = "; fix the header by hand before the Tokens page can save"

        def row(**values):
            return {**{k: "" for k in rules.TOKEN_FIELDS}, **values}
        expected = {
            "good": ([], [2, 3], [row(front="Zombie", quantity="2"), row(front="Dog", quantity="1")], False, None),
            "bad rows": (["A row before row 1 of the home token cards: tokens need a front name and positive "
                          "physical quantity",
                          "A row before row 1 of the home token cards: 5 values, not 10",
                          "A row before row 1 of the home token cards: invalid lowercase token set"], [], [], True,
                         "A row before row 1 of the home token cards: tokens need a front name and positive "
                         "physical quantity" + by_hand),
            "legacy": (["The home token cards lack the printing columns" + printing], [2],
                       [row(front="Dog", back="Beast", quantity="1", back_details="3/3")], True, must + by_hand),
            "reordered": (["The home token cards' columns aren't in the standard order" + printing], [2],
                          [row(front="Dog", quantity="1")], True, must + by_hand),
            "bad header": ([must], [], [], True, must + by_hand),
            "bad csv": ([], [2], [row(front="Dog", back="ab", quantity="1")], True,
                        "A row before row 1 of the home token cards can't be read: ',' expected after '\"'" + by_hand),
            "not utf-8": (["The home token cards aren't UTF-8 text"], [], [], True,
                          "The home token cards aren't UTF-8 text" + by_hand),
        }
        for name, text in cases.items():
            problems, lines, rows, in_order, strict = expected[name]
            with self.subTest(name):
                self.write("magic/tokens.csv", text)
                sheet = self.load().token_set()
                self.assertEqual(list(sheet.problems), problems)
                self.assertEqual(list(sheet.lines), lines)
                self.assertEqual([{k: r.text(k) for k in rules.TOKEN_FIELDS} for r in sheet.rows], rows)
                self.assertEqual(sheet.sorted, in_order)
                self.assertEqual(sheet.strict_error, strict)
                with inventory.use(FileInventory(self.root)):      # tokens.read() reads that sheet
                    today = tokens.read()
                    with self.assertRaises(tokens.TokensError) if strict else contextlib.nullcontext():
                        tokens.read(strict=True)
                self.assertEqual((today.problems, today.lines, today.rows, today.sorted),
                                 (problems, lines, rows, in_order))

    def test_test_fixture_trees_load_without_raising(self):
        box = Sandbox().start()
        self.addCleanup(box.stop)
        inv = inventory.current()
        self.assertEqual(inventory.backend(), box.inventory)
        self.assertEqual({p.stem for p in inv.products}, {"fdn-beginner-box", "fdc-test-precon"})
        self.assertEqual(inv.status.columns, tuple(rules.LEGACY_STATUS_FIELDS))
        self.assertEqual([r.file for r in inv.raw_incoming_status_rows()], ["fdc-test-precon.csv"])
        self.assertTrue(inv.collection().exists)
        self.assertEqual(files.render(inv)["magic/products/status.csv"],
                         (box.magic / "products/status.csv").read_bytes())


class PoolFixtureTests(test_pool.PoolTestCase):
    """PoolTestCase's tree is the installed backend, and its malformed cases load."""

    def test_installed_and_reads_the_tree(self):
        self.assertIs(inventory.backend(), self.inventory)
        self.cards_csv("orders/2026-09-29-x.csv", ("Opt", "dom", "60", "nonfoil", "lots"))
        self.status(("gone.csv", "preorder", "maybe"))
        self.product("unlisted.csv", ("Elves", "Llanowar Elves", "one"))
        inv = inventory.current()
        self.assertEqual(inv.loose_payloads, ["magic/orders/2026-09-29-x.csv"])
        self.assertEqual(inv.payloads["magic/orders/2026-09-29-x.csv"].problems,
                         ("Row 1 of order 2026-09-29-x's cards: bad quantity 'lots'",))
        self.assertEqual([r.file for r in inv.status_rows], ["gone.csv"])
        self.assertIsNone(inv.product("gone"))
        self.assertEqual(inv.product("unlisted").problems,
                         ("Row 1 of product unlisted's card list: bad quantity 'one'",))
        self.assertEqual(len(inv.status.problems), 2)


# ------------------------------------------------------------------ writing

def _set_quantity(inv, *, space="home", index=0, quantity="3"):
    sheet = inv.collection(space)
    rows = list(sheet.rows)
    rows[index] = rows[index].replace(quantity=quantity)
    new = model.Sheet(sheet.path, sheet.columns, tuple(rows), True)
    return inv.replace(collections={**inv.collections, space: new}), inventory.Summary("set", {"rows": 1})


def _keep_import(inv, *, name):
    return inv, inventory.Summary("import", extra={"imports": [("user2", name, b"raw")]})


def _drop_payload(inv, *, path):
    return inv.replace(payloads={k: v for k, v in inv.payloads.items() if k != path}), inventory.Summary()


class ApplyTests(TempRoot):
    def setUp(self):
        super().setUp()
        for kind, fn in (("test.set_quantity", _set_quantity), ("test.keep_import", _keep_import),
                         ("test.drop_payload", _drop_payload)):
            inventory.register(kind)(fn)
            self.addCleanup(inventory.unregister, kind)
        self.addCleanup(inventory.use(FileInventory(self.root)))
        self.write("magic/collection.csv", CARD_HEADER + "Opt,dom,60,nonfoil,1,,,\n")
        self.write("magic/orders/a.csv", CARD_HEADER + "Opt,dom,60,nonfoil,1,,,\n")
        self.bom = self.write("magic/watchlist.csv", b"\xef\xbb\xbfname\nx\n")
        self.broken = self.write("magic/orders/broken.csv", b"\xff")

    def test_apply_writes_only_what_changed(self):
        before = inventory.current()
        after, summary = inventory.apply(inventory.Op("test.set_quantity"), ACTOR, "Set a quantity")
        self.assertEqual(summary.counts, {"rows": 1})
        self.assertEqual((self.root / "magic/collection.csv").read_text(), CARD_HEADER + "Opt,dom,60,nonfoil,3,,,\n")
        self.assertEqual(self.bom.read_bytes(), b"\xef\xbb\xbfname\nx\n")        # untouched, BOM and all
        self.assertEqual(self.broken.read_bytes(), b"\xff")
        self.assertNotEqual(after.revision, before.revision)
        self.assertEqual(after, inventory.current())

    def test_expected_revision_and_preview(self):
        before = inventory.current()
        preview, _ = inventory.preview(inventory.Op("test.set_quantity", {"quantity": "9"}))
        self.assertEqual(preview.collection().rows[0].quantity, "9")
        self.assertEqual(inventory.current(), before)                           # nothing written
        with self.assertRaises(state.Conflict):
            inventory.apply(inventory.Op("test.set_quantity"), ACTOR, "x", expected_revision="0" * 64)
        inventory.apply(inventory.Op("test.set_quantity"), ACTOR, "x", expected_revision=before.revision)

    def test_removed_sources_are_deleted_and_imports_kept(self):
        inventory.apply(inventory.Op("test.drop_payload", {"path": "magic/orders/a.csv"}), ACTOR, "Drop")
        self.assertFalse((self.root / "magic/orders/a.csv").exists())
        inventory.apply(inventory.Op("test.keep_import", {"name": "x.csv"}), ACTOR, "Import")
        self.assertEqual((self.root / "magic/people/user2/imports/x.csv").read_bytes(), b"raw")
        self.assertEqual(inventory.current().imports["user2"], (model.ImportInfo("x.csv", 3),))
        with self.assertRaises(ValueError):
            inventory.apply(inventory.Op("test.keep_import", {"name": "x.csv"}), ACTOR, "Import")

    def test_unknown_kinds_and_bad_arguments(self):
        with self.assertRaises(state.Invalid):
            inventory.apply(inventory.Op("no.such"), ACTOR, "x")
        with self.assertRaises(TypeError):
            inventory.apply(inventory.Op("test.set_quantity"), "matt", "x")
        with self.assertRaises(ValueError):
            inventory.apply(inventory.Op("test.set_quantity"), ACTOR, " ")
        with self.assertRaises(ValueError):
            inventory.register("test.set_quantity")(_keep_import)
        self.assertIn("test.set_quantity", inventory.kinds())


# ------------------------------------------------------------------ the package

class BackendTests(TempRoot):
    def test_explicit_mode_refuses_without_a_backend(self):
        self.assertTrue(os.environ.get(inventory.EXPLICIT_ENV))
        with self.assertRaises(RuntimeError):
            inventory.current()

    def test_the_default_backend_is_the_database(self):
        with mock.patch.dict(os.environ, {inventory.EXPLICIT_ENV: ""}),                 mock.patch.object(config, "REPO", self.root), mock.patch.dict(inventory._defaults, clear=True):
            with mock.patch.dict("sys.modules", {"decklab.lib.inventory.pg": None}):
                with self.assertRaises(state.Unavailable):
                    inventory.backend()
            from decklab.lib.inventory.pg import PgInventory
            self.assertIsInstance(inventory.backend(), PgInventory)

    def test_use_nests_and_pinned_keeps_one_snapshot(self):
        outer, inner = FileInventory(self.root), FileInventory(self.root / "x")
        with inventory.use(outer):
            restore = inventory.use(inner)
            self.assertIs(inventory.backend(), inner)
            restore()
            restore()
            self.assertIs(inventory.backend(), outer)
            self.write("magic/collection.csv", CARD_HEADER)
            with inventory.pinned():
                first = inventory.current()
                self.write("magic/collection.csv", CARD_HEADER + "Opt,dom,60,nonfoil,1,,,\n")
                self.assertIs(inventory.current(), first)
                self.assertTrue(inventory.is_pinned())
            self.assertNotEqual(inventory.current(), first)
            fake = model.Inventory("r", stale="inventory as of noon")
            with inventory.pinned(fake):
                self.assertIs(inventory.current(), fake)
                self.assertEqual(inventory.stale_warning(), "inventory as of noon")
                self.assertEqual(inventory.pinned_stale(), "inventory as of noon")     # what server_http adds
            with inventory.pinned():
                self.assertIsNone(inventory.pinned_stale())         # nothing loaded, nothing loaded for it
            self.assertFalse(inventory.is_pinned())
            self.assertIsNone(inventory.pinned_stale())


class PathsTests(unittest.TestCase):
    def test_derived_paths_and_classify(self):
        self.assertEqual(paths.collection("user2"), "magic/people/user2/collection.csv")
        self.assertEqual(paths.payload("tokens", "received", "x.csv"), "magic/orders/tokens/received/x.csv")
        self.assertEqual(paths.payload("product", "received", "x.csv"), "magic/products/x.csv")
        for rel, expected in (
                ("magic/collection.csv", ("collection", "home")),
                ("magic/people/user4/tokens.csv", ("tokens", "user4")),
                ("magic/people/user4/imports/a.csv", ("import", ("user4", "a.csv"))),
                ("magic/orders/cancelled/x.csv", ("payload", ("cards", "cancelled", "x.csv"))),
                ("magic/orders/tokens/x.csv", ("payload", ("tokens", "pending", "x.csv"))),
                ("magic/orders/records/x.json", ("record", "x")),
                ("magic/products/status.csv", ("status", None)),
                ("magic/orders/records/x.csv", None), ("magic/decks/x.md", None),
                ("magic/decks/casual/.x.md", None)):
            self.assertEqual(paths.classify(rel), expected, rel)
        # Phase 4's deck parts have kinds of their own, but aren't inventory files.
        for rel, expected in (
                ("magic/decks/casual/x.md", ("deck", ("home", "casual", "x"))),
                ("magic/people/user4/decks/commander/Odd_Name.md", ("deck", ("user4", "commander", "Odd_Name"))),
                ("magic/accessories.csv", ("accessories", None)),
                ("magic/accessories/images/a.jpg", ("image", "a.jpg"))):
            self.assertEqual(paths.classify(rel), expected, rel)
            self.assertFalse(paths.is_inventory(rel), rel)
            self.assertTrue(paths.is_deck_part(rel), rel)
        with self.assertRaises(ValueError):
            paths.collection("../x")


class ChangedLabelsTests(unittest.TestCase):
    """changed_labels: what a receipt's preview and the order commands' dry runs show, in plain
    words (no paths), one label per part in a fixed order."""

    def test_every_kind_of_part(self):
        from types import SimpleNamespace as NS

        from decklab.lib import spaces
        from decklab.lib.inventory import changes

        component = NS(path="magic/orders/a.csv")
        products = {"fdc-test": NS(label=lambda where: "Test Precon")}
        decks_ = {"casual/gruul": NS(text="﻿# Gruul Ramp\n- **Format:** casual\n"),
                  "user2/commander/x": NS(text="no title line\n")}
        inv = NS(components=lambda: [(NS(id="2026-10-05-ronin"), component)],
                 product=products.get, deck=decks_.get)
        names = {"home": "Home", "user2": "User2"}

        def get(space, listed=None):
            if space not in names:
                raise spaces.SpaceNotFound(space)
            return NS(name=names[space])

        rels = ["magic/accessories/images/a.jpg", "magic/accessories.csv", "magic/people/user2/decks/commander/x.md",
                "magic/decks/casual/gruul.md", "magic/decks/casual/gone.md", "magic/watchlist.csv",
                "magic/products/status.csv", "magic/products/fdc-other.csv", "magic/products/fdc-test.csv",
                "magic/orders/tokens/received/b.csv", "magic/orders/a.csv", "magic/orders/records/2026-10-05-ronin.json",
                "magic/people/user2/imports/r.csv", "magic/imports/h.csv", "magic/people/zed/tokens.csv",
                "magic/people/user2/tokens.csv", "magic/tokens.csv", "magic/people/user2/collection.csv",
                "magic/collection.csv", "magic/notes.txt"]
        with mock.patch.object(spaces, "get", get):
            labels = changes.changed_labels(inv, inv, rels=rels)
        self.assertEqual(labels, [
            "Home's collection", "User2's collection",
            "Home's token cards", "User2's token cards", "zed's token cards",
            "Home's raw imports: h.csv", "User2's raw imports: r.csv",
            "A received order's token cards", "Order 2026-10-05-ronin",   # its record and its cards: one label
            "Product Test Precon", "Product fdc-other",
            "The products' status", "The purchase queue",
            "Deck Gruul Ramp (casual/gruul)", "Deck casual/gone", "Deck user2/commander/x",
            "The accessories", "An accessory's picture (a.jpg)",
            "magic/notes.txt"])


class ReexportTests(unittest.TestCase):
    def test_old_names_are_the_rules(self):
        from decklab.lib.api import collection_edit
        from decklab.lib.tokens import rows
        self.assertIs(rows.validate_row, rules.token_page_row)
        self.assertIs(collection_edit.csv_bytes, rules.collection_csv_bytes)
        self.assertEqual(files.rendered_sha256(model.Sheet("magic/collection.csv")),
                         hashlib.sha256(b"").hexdigest())


# ------------------------------------------------------------------ the foundation review's fixes

def _mutate_record(inv):
    """An op that changes a record's dict in place and returns the snapshot it was given."""
    inv.orders[0].data["notes"] = "changed in place"
    return inv, inventory.Summary("in place")


def _assign_mapping(inv):
    inv.collections["home"] = inv.collection()
    return inv, inventory.Summary()


def _rows_op(inv, *, space="home", rows=()):
    return inv.with_collection(space, [dict(zip(rules.FIELDS, r)) for r in rows]), inventory.Summary("rows")


def _raw_rows_op(inv, *, rows=()):
    """Rows put straight into a Sheet, unsorted, as an op that forgets the helpers might."""
    made = tuple(model.CardRow.make(dict(zip(rules.FIELDS, r))) for r in rows)
    sheet = model.Sheet("magic/collection.csv", tuple(rules.FIELDS), made, True)
    return inv.replace(collections={**inv.collections, "home": sheet}), inventory.Summary()


def _new_payload(inv):
    path = "magic/orders/2026-10-12-loose.csv"
    sheet = model.Sheet(path, tuple(rules.FIELDS), (model.CardRow.make(name="Opt", set="dom", collector_number="60",
                                                                     finish="nonfoil", quantity="1"),), True)
    return inv.replace(payloads={**inv.payloads, path: sheet}), inventory.Summary()


def _tokens_op(inv, *, rows=()):
    return inv.with_tokens("home", [dict(zip(rules.TOKEN_FIELDS, r)) for r in rows]), inventory.Summary()


def _tokens_raw(inv):
    sheet = inv.token_set()
    return inv.replace(tokens={**inv.tokens, "home": dataclasses.replace(sheet, rows=sheet.rows[:1])}), \
        inventory.Summary()


def _receive_op(inv, *, order_id, component_id):
    return inv.move_component(order_id, component_id, "received", "2026-10-12"), inventory.Summary()


REVIEW_OPS = {"review.mutate_record": _mutate_record, "review.assign_mapping": _assign_mapping,
              "review.rows": _rows_op, "review.raw_rows": _raw_rows_op, "review.new_payload": _new_payload,
              "review.tokens": _tokens_op, "review.tokens_raw": _tokens_raw, "review.receive": _receive_op}


class ReviewFixTests(TempRoot):
    """Snapshots can't be changed in place, one place normalises and refuses for both backends,
    tokens with bad rows aren't rewritten, loading survives OS errors, previews aren't revisions."""

    def setUp(self):
        super().setUp()
        for kind, fn in REVIEW_OPS.items():
            inventory.register(kind)(fn)
            self.addCleanup(inventory.unregister, kind)
        self.addCleanup(inventory.use(FileInventory(self.root)))
        self.write("magic/collection.csv", CARD_HEADER + "Opt,dom,60,nonfoil,1,,,\n")
        self.write("magic/orders/a.csv", CARD_HEADER + "Opt,dom,60,nonfoil,2,,,\n")
        self.write("magic/orders/records/a.json", rules.json_bytes(model.Order.build("a", "Shop", components=[
            model.Component.build("cards", "cards", "a.csv")]).data))

    def test_an_op_changing_a_record_in_place_changes_only_its_copy(self):
        before = inventory.current()
        after, _ = inventory.apply(inventory.Op("review.mutate_record"), ACTOR, "Notes")
        self.assertEqual(after.order("a").notes, "changed in place")         # saved, not lost
        self.assertEqual(before.order("a").notes, "")                        # the snapshot read is untouched
        preview, _ = inventory.preview(inventory.Op("review.mutate_record"))
        current = inventory.current()
        self.assertEqual(preview.order("a").notes, "changed in place")
        with self.assertRaises(TypeError):
            inventory.apply(inventory.Op("review.assign_mapping"), ACTOR, "x")
        with self.assertRaises(TypeError):
            current.payloads["x"] = None
        current.order("a").components[0].data["status"] = "received"      # a copy
        self.assertEqual(current.order("a").components[0].status, "pending")

    def test_a_preview_is_settled_and_never_a_revision(self):
        before = inventory.current()
        self.assertTrue(before.persisted)
        preview, _ = inventory.preview(inventory.Op("review.rows", {"rows": [
            ("Shock", "m19", "156", "nonfoil", "1", "", "", ""), ("Opt", "dom", "60", "nonfoil", "1", "", "", "")]}))
        self.assertEqual(preview.revision, before.revision + inventory.PREVIEW)
        self.assertFalse(preview.persisted)
        self.assertEqual([(r.set, r.line) for r in preview.collection().rows], [("dom", 2), ("m19", 3)])

    def test_no_rows_means_no_file_and_rows_are_sorted(self):
        inventory.apply(inventory.Op("review.raw_rows", {"rows": [("Shock", "m19", "156", "nonfoil", "1", "", "", ""),
                                                                 ("Opt", "dom", "60", "nonfoil", "1", "", "", "")]}),
                        ACTOR, "Two")
        self.assertEqual((self.root / "magic/collection.csv").read_text(encoding="utf-8"),
                         CARD_HEADER + "Opt,dom,60,nonfoil,1,,,\nShock,m19,156,nonfoil,1,,,\n")
        after, _ = inventory.apply(inventory.Op("review.raw_rows"), ACTOR, "None")
        self.assertFalse((self.root / "magic/collection.csv").exists())
        self.assertFalse(after.collection().exists)
        self.assertEqual(files.rendered_sha256(after.collection()), hashlib.sha256(b"").hexdigest())

    def test_the_same_refusals_as_the_database(self):
        with self.assertRaisesRegex(state.Invalid, r"can't be saved like that: Row 1 of the home collection: .*'x'"):
            inventory.apply(inventory.Op("review.rows", {"rows": [("Opt", "dom", "60", "nonfoil", "x", "", "", "")]}),
                            ACTOR, "x")
        with self.assertRaisesRegex(state.Invalid, "2026-10-12-loose.csv: no order record names it"):
            inventory.apply(inventory.Op("review.new_payload"), ACTOR, "x")
        # A loose payload that was there already doesn't block an unrelated change.
        self.write("magic/orders/b.csv", CARD_HEADER + "Opt,dom,60,nonfoil,1,,,\n")
        inventory.apply(inventory.Op("review.rows", {"rows": [("Opt", "dom", "60", "nonfoil", "3", "", "", "")]}),
                        ACTOR, "Three")
        self.assertEqual(inventory.current().collection().rows[0].quantity, "3")

    def test_tokens_with_rows_left_out_are_never_rewritten(self):
        self.write("magic/tokens.csv", TOKEN_HEADER + "Zombie,,,,,,2,,,\nDog,,,,,,0,,,\nCat,,,,,,1,,,\n")
        sheet = inventory.current().token_set()
        self.assertEqual(len(sheet.rows), 2)                     # Dog (quantity 0) is only a problem
        for op in (inventory.Op("review.tokens", {"rows": [("Elf", "", "", "", "", "", "1", "", "", "")]}),
                   inventory.Op("review.tokens_raw")):
            with self.assertRaisesRegex(state.Conflict, "put right"):
                inventory.apply(op, ACTOR, "x")
        self.assertIn("Dog,,,,,,0", (self.root / "magic/tokens.csv").read_text(encoding="utf-8"))
        self.write("magic/tokens.csv", TOKEN_HEADER + "Zombie,,,,,,2,,,\n")
        with self.assertRaisesRegex(state.Invalid, "can't be saved like that"):
            inventory.apply(inventory.Op("review.tokens", {"rows": [("Elf", "", "BAD", "", "", "", "1", "", "", "")]}),
                            ACTOR, "x")
        after, _ = inventory.apply(inventory.Op("review.tokens", {"rows": [
            ("Zombie", "", "", "", "", "", "2", "", "", ""), ("Elf", "", "", "", "", "", "1", "", "", "")]}), ACTOR, "Elf")
        self.assertEqual([r.front for r in after.token_set().rows], ["Elf", "Zombie"])      # TOKEN_SORT order

    def test_move_component_moves_the_payload_with_the_record(self):
        after, _ = inventory.apply(inventory.Op("review.receive", {"order_id": "a", "component_id": "cards"}),
                                   ACTOR, "Receive a")
        component = after.order("a").components[0]
        self.assertEqual((component.status, component.received_on, component.path),
                         ("received", "2026-10-12", "magic/orders/received/a.csv"))
        self.assertTrue((self.root / "magic/orders/received/a.csv").exists())
        self.assertFalse((self.root / "magic/orders/a.csv").exists())
        self.assertEqual(list(after.payloads), ["magic/orders/received/a.csv"])

    def test_write_helpers(self):
        inv = inventory.current()
        legacy = files.build({"magic/products/status.csv": b"file,status,intact,notes\nx.csv,preordered,,soon\n"})
        made = legacy.with_status_rows(legacy.status.rows)
        self.assertEqual(files.render(made)["magic/products/status.csv"],
                         b"file,status,intact,sleeves,deck_box,notes,token_cards\nx.csv,preordered,,,,soon,\n")
        older = files.build({"magic/collection.csv": b"name,set,collector_number,finish,quantity\nOpt,dom,60,nonfoil,1\n"})
        grown = older.with_collection("home", [*older.collection().rows,
                                               model.CardRow.make(name="Shock", set="m19", collector_number="156",
                                                                  finish="nonfoil", quantity="1", notes="kept")])
        self.assertEqual(files.render(grown)["magic/collection.csv"],
                         (CARD_HEADER + "Opt,dom,60,nonfoil,1,,,\nShock,m19,156,nonfoil,1,,,kept\n").encode())
        rows = inv.set_component_rows("a", "cards", [{"name": "Shock", "set": "m19", "collector_number": "156",
                                                      "finish": "nonfoil", "quantity": "2"}])
        self.assertEqual(rows.payloads["magic/orders/a.csv"].rows[0].quantity, "2")
        checked = inv.update_component("a", "cards", verified_checks=["condition"], checks=[])
        self.assertEqual(list(checked.order("a").record()["components"][0]),
                         ["id", "kind", "path", "status", "received_on", "checks", "verified_checks"])
        with self.assertRaises(ValueError):
            inv.update_component("a", "nope", status="received")
        self.assertEqual(inventory.changed_paths(inv, rows), ["magic/orders/a.csv"])
        moved = inv.move_component("a", "cards", "cancelled")
        self.assertEqual(inventory.changed_paths(inv, moved), ["magic/orders/a.csv", "magic/orders/cancelled/a.csv",
                                                              "magic/orders/records/a.json"])
        self.assertEqual(inventory.changed_paths(inv, inv), [])

    def test_a_file_the_os_wont_read_is_unreadable_not_fatal(self):
        real = Path.read_bytes

        def locked(path):
            if path.name == "collection.csv":
                raise PermissionError(13, "The process cannot access the file", str(path))
            return real(path)
        with mock.patch.object(Path, "read_bytes", locked):
            inv = FileInventory(self.root).load()
        self.assertIn("cannot access", inv.collection().error)
        self.assertIn("magic/collection.csv", inv.unreadable)
        self.assertEqual(len(inv.orders), 1)
        self.assertEqual(files.render(inv).keys(), {"magic/orders/a.csv", "magic/orders/records/a.json"})

    def test_imports_count_by_size_and_keep_a_streamed_hash(self):
        self.write("magic/imports/x.csv", "Name,Quantity\nOpt,1\n")
        found = files.tree_files(self.root)
        self.assertIsInstance(found["magic/imports/x.csv"], files.ImportSize)
        with_bytes = files.tree_files(self.root, import_bytes=True)
        self.assertEqual(with_bytes["magic/imports/x.csv"], b"Name,Quantity\nOpt,1\n")
        self.assertEqual(files.revision_of(found), files.revision_of(with_bytes))
        self.assertEqual(files.build(found).imports, files.build(with_bytes).imports)
        info = files.build(found).imports["home"][0]
        self.assertEqual(info.sha256, hashlib.sha256(with_bytes["magic/imports/x.csv"]).hexdigest())
        self.assertEqual((info.imported_at, info.imported_by), (None, None))

    def test_unreadable_products_csv_errors_and_name_order(self):
        self.write("magic/products/B.csv", "deck,name\nElves,\"x\"y\n")
        self.write("magic/products/a.csv", b"\xff")
        inv = inventory.current()
        self.assertEqual([p.file for p in inv.products], ["a.csv", "B.csv"])
        self.assertIsNone(inv.product("a").is_deck)
        self.assertTrue(inv.product("B").is_deck)
        self.assertIsNotNone(inv.product("B").csv_error)
        self.assertIsNone(inv.collection().csv_error)

    def test_legacy_token_rows_have_every_column(self):
        data = "front,back,quantity,front_details,back_details,notes\nDog,Beast,1,,3/3,\n"
        self.write("magic/tokens.csv", data)
        inv = inventory.current()
        self.assertEqual(inv.token_set().rows[0].get("set"), "")
        self.assertEqual(files.render(inv)["magic/tokens.csv"], data.encode())


class WriteSafetyTests(unittest.TestCase):
    """FileInventory writes plain files, refusing the whole write when a file changed since the
    load, and commits nothing: phase 4 deleted its git mode (and phase 5 its lock and journal),
    and config.json's "files" is refused."""

    def setUp(self):
        self.box = Sandbox().start()
        self.addCleanup(self.box.stop)
        inventory.register("review.rows")(_rows_op)
        self.addCleanup(inventory.unregister, "review.rows")
        self.backend = FileInventory(self.box.root)
        self.addCleanup(inventory.use(self.backend))
        self.rows = [tuple(r.text(k) for k in rules.FIELDS) for r in inventory.current().collection().rows]

    def test_a_write_commits_nothing(self):
        rows = self.rows[1:]
        after, summary = inventory.apply(inventory.Op("review.rows", {"rows": rows}), ACTOR, "Remove a card")
        self.assertNotIn("commit", summary.extra or {})
        self.assertEqual(len(after.collection().rows), len(rows))
        self.assertFalse((self.box.root / "decklab/data/receipts").exists())     # no journal, no lock
        self.assertFalse((self.box.root / "decklab/data/inventory-pending.json").exists())

    def test_a_file_changed_since_the_load_refuses_the_whole_write(self):
        magic = self.box.root / "magic"
        collection = (magic / "collection.csv").read_bytes()
        writes = {"magic/collection.csv": (collection, b"first\n"),
                  "magic/tokens.csv": (b"what the load read\n", b"second\n")}
        tokens_now = (magic / "tokens.csv").read_bytes() if (magic / "tokens.csv").exists() else None
        with self.assertRaisesRegex(state.Conflict, "Changed while preparing the write: magic/tokens.csv"):
            self.backend._write_plain("x", writes)
        self.assertEqual((magic / "collection.csv").read_bytes(), collection)      # nothing written
        self.assertEqual((magic / "tokens.csv").read_bytes() if (magic / "tokens.csv").exists() else None,
                         tokens_now)

    def test_there_is_no_git_mode(self):
        with self.assertRaises(TypeError):
            FileInventory(self.box.root, git=True)

if __name__ == "__main__":
    unittest.main()
