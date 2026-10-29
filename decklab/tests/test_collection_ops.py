"""The collections' operations (decklab/lib/inventory/ops_collection.py) on both inventory
backends: the same tree, the same operations, the same results and refusals from a
FileInventory over a temporary folder and from a PgInventory of a throwaway database the tree
was imported into. Also the Collection page's API on the database backend (its sha256, its
409s and the raw import kept in collection_import), "Add a precon" on the database, and
`python -m decklab.db collection`'s name check and list, and its merge on the files backend.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_collection_ops.
The protected default skips PostgreSQL integration; that needs separate explicit qualification.
"""
import argparse
import contextlib
import csv
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from decklab.db import inv_collection, read_notices
from decklab.lib import cards, inventory
from decklab.lib.inventory import Op, ops_collection as ops, rules
from decklab.lib.inventory.files import FileInventory
from decklab.lib.inventory.model import QUEUE_FIELDS
from decklab.lib.state import Actor
from decklab.tests import db_support
from decklab.tests import test_collection_edit as tce
from decklab.tests import test_precons as tp
from decklab.tests.test_inventory_contract import CLAUDE, FIXTURE_PROFILES, adapt, import_contents

FIXTURES = Path(__file__).parent / "fixtures"
HEADER = ",".join(rules.FIELDS) + "\n"
HOME = HEADER + "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\nBlack Lotus,lea,232,nonfoil,1,NM,en,\n"
USER2 = HEADER + "Elvish Mystic,cmm,648,nonfoil,1,,,Reign of Dragons precon\n"
OLD_IMPORT = "x" * 900
MATT = Actor("matt", "Matt", "home")
EMPTY = hashlib.sha256(b"").hexdigest()          # a space with no cards


def _private_visibility():
    """Legacy CLI fixtures read a fresh fake switch snapshot, never a configured PgStore."""
    store = mock.Mock(visibility=mock.Mock(return_value={}))
    return mock.patch.object(read_notices.pg, "PgStore", return_value=store)


def _listing_sha(case, stderr):
    """Require the separate privacy notice and the exact, authoritative final SHA line."""
    lines = stderr.splitlines(keepends=True)
    case.assertEqual(len(lines), 2, stderr)
    case.assertEqual(lines[0], "Privacy: collection in space user2 is Private to that space. "
                              "Do not relay it outside that space.\n")
    case.assertRegex(lines[-1], r"\Asha [0-9a-f]{64} \(give it to collection edit or apply as --expect\)\n\Z")
    return lines[-1].split()[1]


def elves(**changes):
    row = dict(zip(rules.FIELDS, ["Llanowar Elves", "fdn", "227", "nonfoil", "1", "NM", "en", ""]))
    row.update(changes)
    return row


def write_tree(root):
    magic = root / "magic"
    (magic / "people" / "user2" / "imports").mkdir(parents=True)
    (magic / "products").mkdir(exist_ok=True)
    (magic / "collection.csv").write_text(HOME, encoding="utf-8", newline="")
    # The database always has a status list and a watchlist (a sandbox already has its status.csv).
    if not (magic / "products" / "status.csv").exists():
        (magic / "products" / "status.csv").write_text(",".join(rules.STATUS_FIELDS) + "\n", encoding="utf-8",
                                                       newline="")
    (magic / "watchlist.csv").write_text(",".join(QUEUE_FIELDS) + "\n", encoding="utf-8", newline="")
    (magic / "people" / "user2" / "collection.csv").write_text(USER2, encoding="utf-8", newline="")
    (magic / "people" / "user2" / "imports" / "2026-10-01-old.csv").write_text(OLD_IMPORT, encoding="utf-8")


class OpsContract:
    """The tests both backends run: self.backend is the installed backend over write_tree's tree."""

    def apply(self, kind, **params):
        return inventory.apply(Op(kind, params), MATT, "test change")

    def rows(self, space="home"):
        return ops.rows_of(inventory.current().collection(space))

    def sha(self, space="home"):
        return ops.sha256_of(inventory.current().collection(space))

    def test_add_a_new_printing(self):
        inv, summary = self.apply("collection.add", space="home", sha256=self.sha(),
                                  row=elves(set="m19", collector_number="314", condition="", language=""))
        self.assertEqual(summary.text, "add card Llanowar Elves (M19 314) in the home collection")
        self.assertEqual(summary.counts["merged"], False)
        self.assertEqual([(r["set"], r["quantity"]) for r in self.rows()], [("fdn", "2"), ("lea", "1"), ("m19", "1")])

    def test_add_a_listed_printing_adds_to_it_and_blanks_what_differs(self):
        _, summary = self.apply("collection.add", space="home", row=elves(language="ja", notes="from Japan"))
        self.assertTrue(summary.counts["merged"])
        row = self.rows()[0]
        self.assertEqual((row["quantity"], row["condition"], row["language"]), ("3", "NM", ""))
        self.assertEqual(row["notes"], "from Japan; Merged copies have differing or unreported language")

    def test_ordinary_basics_only_when_tracked(self):
        forest = elves(name="Forest", collector_number="280")
        with self.assertRaises(inventory.Invalid) as caught:
            self.apply("collection.add", space="home", row=forest)
        self.assertEqual(str(caught.exception), ops.BASIC_REFUSED)
        self.apply("collection.add", space="home", row=dict(forest, notes="full art"))
        self.apply("collection.add", space="home", row=forest)      # that printing is tracked now
        self.assertEqual(next(r for r in self.rows() if r["name"] == "Forest")["quantity"], "2")

    def test_a_stale_sha_is_refused_and_nothing_changes(self):
        before = self.rows()
        with self.assertRaises(ops.Stale) as caught:
            self.apply("collection.add", space="home", sha256="0" * 64, row=elves())
        self.assertEqual(str(caught.exception),
                         "The home collection has changed since the page loaded it; look at it again and retry.")
        self.assertEqual(self.rows(), before)

    def test_a_space_with_no_cards_has_the_sha_of_nothing_and_gets_one_on_its_first_card(self):
        self.assertEqual((self.rows("user3"), self.sha("user3")), ([], EMPTY))
        self.apply("collection.add", space="user3", sha256=EMPTY, row=elves(), whose="User3's collection")
        self.assertEqual([r["name"] for r in self.rows("user3")], ["Llanowar Elves"])
        self.assertEqual(self.sha("user3"),
                         hashlib.sha256((HEADER + "Llanowar Elves,fdn,227,nonfoil,1,NM,en,\n")
                                                      .encode()).hexdigest())

    def test_edit_replaces_the_row(self):
        _, summary = self.apply("collection.edit", space="home", original=["fdn", "227", "nonfoil"],
                                row=elves(set="m19", collector_number="314", quantity="2", notes="moved"))
        self.assertEqual(summary.extra["body"], ["Was Llanowar Elves (FDN 227, nonfoil)."])
        self.assertEqual([(r["set"], r["notes"]) for r in self.rows()], [("lea", ""), ("m19", "moved")])

    def test_edit_refusals(self):
        with self.assertRaises(inventory.Invalid) as caught:
            self.apply("collection.edit", space="home", original=["fdn", "227", "nonfoil"],
                       row=elves(name="Black Lotus", set="lea", collector_number="232"))
        self.assertIn("is already listed: change that row's quantity instead", str(caught.exception))
        with self.assertRaises(ops.Missing):
            self.apply("collection.edit", space="home", original=["fdn", "999", "nonfoil"], row=elves())

    def test_apply_edits_and_removes_rows_in_one_change(self):
        _, summary = self.apply("collection.apply", space="home", sha256=self.sha(),
                                edits=[[["fdn", "227", "nonfoil"], elves(quantity="3", notes="sealed")]],
                                removals=[["lea", "232", "nonfoil"]])
        self.assertEqual(summary.text, "edit 1 row and remove 1 row in the home collection")
        self.assertEqual(summary.counts, {"edited": 1, "removed": 1})
        self.assertEqual(summary.extra["body"], ["Changed Llanowar Elves (FDN 227).",
                                                 "Removed Black Lotus (LEA 232) (1 copy)."])
        self.assertEqual([(r["set"], r["quantity"], r["notes"]) for r in self.rows()], [("fdn", "3", "sealed")])

    def test_apply_refuses_every_row_when_one_is_refused(self):
        before = self.rows()
        for params, error in (({"edits": [[["fdn", "227", "nonfoil"], elves(quantity="3")]],
                                "removals": [["fdn", "999", "nonfoil"]]}, ops.Missing),
                              ({"edits": [[["fdn", "227", "nonfoil"], elves(quantity="3")],
                                          [["fdn", "999", "nonfoil"], elves()]]}, ops.Missing),
                              ({"edits": [[["fdn", "227", "nonfoil"], elves(quantity="3")],
                                          [["lea", "232", "nonfoil"], elves()]]}, inventory.Invalid),
                              ({"edits": [[["fdn", "227", "nonfoil"], elves(quantity="3")]],
                                "sha256": "0" * 64}, ops.Stale)):
            with self.subTest(params=params), self.assertRaises(error):
                self.apply("collection.apply", space="home", **params)
            self.assertEqual(self.rows(), before)

    def test_removing_the_last_card_leaves_no_collection(self):
        _, summary = self.apply("collection.remove", space="user2", original=["cmm", "648", "nonfoil"],
                                whose="User2's collection")
        self.assertEqual(summary.text, "remove card Elvish Mystic (CMM 648) in User2's collection")
        self.assertFalse(inventory.current().collection("user2").exists)
        self.assertEqual(self.sha("user2"), EMPTY)

    def test_import_merges_and_keeps_the_raw_file(self):
        text = HEADER + "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\n"
        params = dict(space="user2", whose="User2's collection", sha256=self.sha("user2"),
                      sources=[["my.csv", [elves(quantity="2")]]], uploads=[["2026-10-10-my", text]],
                      message="import {cards} cards into User2's collection from my.csv", fmt="collection",
                      problems=[{"line": 3, "message": "no such card"}], dropped_basics=4)
        inv, summary = self.apply("collection.import", **params)
        self.assertEqual(summary.text, "import 2 cards into User2's collection from my.csv")
        self.assertEqual(summary.extra["raw"], ["magic/people/user2/imports/2026-10-10-my.csv"])
        self.assertEqual(summary.extra["body"], [
            "1 new rows, 0 rows added to; the upload is magic/people/user2/imports/2026-10-10-my.csv (collection).",
            "Left out 1 rows with problems: line 3: no such card", "Left out 4 ordinary basic lands."])
        self.assertEqual(sorted(i.name for i in inv.imports["user2"]), ["2026-10-01-old.csv", "2026-10-10-my.csv"])
        self.assertEqual(self.imported("user2", "2026-10-10-my.csv"), text.encode())
        # The same name again gets -2; the collection moved on, so the old sha is refused.
        with self.assertRaises(ops.Stale):
            self.apply("collection.import", **params)
        params["sha256"] = self.sha("user2")
        _, summary = self.apply("collection.import", **params)
        self.assertEqual(summary.extra["raw"], ["magic/people/user2/imports/2026-10-10-my-2.csv"])
        self.assertEqual(next(r for r in self.rows("user2") if r["set"] == "fdn")["quantity"], "4")

    def test_the_raw_imports_are_capped(self):
        before = self.rows("user2")
        with self.assertRaises(ops.TooLarge) as caught:
            self.apply("collection.import", space="user2", sources=[["a.csv", [elves()]]],
                       uploads=[["2026-10-10-a", "y" * 200]], limit=1000)
        self.assertEqual((caught.exception.held, caught.exception.size, caught.exception.limit), (900, 200, 1000))
        self.assertEqual(self.rows("user2"), before)

    def test_repeat_imports_match_exact_content_within_one_space_and_guard_the_reviewed_set(self):
        text = "raw export\r\n"
        self.apply("collection.import", space="home", sources=[], uploads=[["first", text]])
        snapshot = inventory.current()
        matches = ops.repeat_imports(snapshot, "home", [["renamed", text]])
        self.assertEqual([r["name"] for r in matches], ["first.csv"])
        self.assertEqual(set(matches[0]), {"name", "imported_at", "imported_by"})
        self.assertEqual(ops.repeat_imports(snapshot, "user2", [["renamed", text]]), [])
        self.assertEqual(ops.repeat_imports(snapshot, "home", [["first", "raw export\n"]]), [])
        before = self.rows()
        with self.assertRaises(ops.RepeatsChanged):
            self.apply("collection.import", space="home", sha256=self.sha(), sources=[["new.csv", [elves()]]],
                       uploads=[["new", text]], expected_repeats=[])
        self.assertEqual(self.rows(), before)
        self.assertEqual([i.name for i in inventory.current().imports["home"]], ["first.csv"])
        params = {"space": "home", "sha256": self.sha(), "sources": [["new.csv", [elves()]]],
                  "uploads": [["renamed", text]], "expected_repeats": ["first.csv"]}
        audit_message = ops.message(inventory.current(), "collection.import", params)
        _, summary = self.apply("collection.import", **params)
        self.assertEqual(audit_message, summary.text)
        self.assertIn("intentional repeat import", audit_message)
        self.assertEqual(next(r["quantity"] for r in self.rows() if r["set"] == "fdn"), "3")
        self.assertEqual(self.imported("home", "renamed.csv"), text.encode("utf-8"))

    def test_a_name_clash_is_refused(self):
        with self.assertRaises(inventory.Conflict) as caught:
            self.apply("collection.import", space="home", sources=[["x.csv", [elves(name="Sol Ring")]]])
        self.assertIn("The import can't be merged: x.csv:", str(caught.exception))

    def test_a_quantity_that_isnt_a_positive_whole_number_is_invalid(self):
        before = self.rows()
        for kind, params in (("collection.add", {"row": elves(quantity="lots")}),
                             ("collection.edit", {"original": ["fdn", "227", "nonfoil"], "row": elves(quantity="0")}),
                             ("collection.import", {"sources": [["x.csv", [elves(quantity="-1")]]]})):
            with self.subTest(kind=kind), self.assertRaises(inventory.Invalid) as caught:
                self.apply(kind, space="home", **params)
            self.assertIn("quantity must be a positive whole number", str(caught.exception))
        self.assertEqual(self.rows(), before)

    def test_message_words_the_summary_text_beforehand(self):
        for kind, params in (
                ("collection.add", {"row": elves(set="m19", collector_number="314")}),
                ("collection.edit", {"original": ["fdn", "227", "nonfoil"], "row": elves(quantity="3")}),
                ("collection.import", {"sources": [["x.csv", [elves(quantity="2"), elves(name="Forest",
                                                                                         collector_number="280")]]],
                                       "message": "import {cards} cards from x.csv"}),
                ("collection.remove", {"original": ["lea", "232", "nonfoil"]}),
                ("collection.apply", {"edits": [[["fdn", "227", "nonfoil"], elves(quantity="3")]]})):
            params = {"space": "home", "sha256": self.sha(), **params}
            with self.subTest(kind=kind):
                text = ops.message(inventory.current(), kind, params)
                _, summary = self.apply(kind, **params)
                self.assertEqual(text, summary.text)
        self.assertEqual(ops.message(inventory.current(), "collection.remove",
                                     {"space": "home", "original": ["lea", "232", "nonfoil"]}),
                         "change the home collection")             # gone: apply refuses it

    def test_a_collection_that_breaks_the_rules_is_never_written(self):
        self.break_home()
        with self.assertRaises(ops.Unreadable) as caught:
            self.apply("collection.add", space="home", row=elves())
        self.assertIn("magic/collection.csv can't be read: ", str(caught.exception))
        self.assertIn("Fix it on the PC first.", str(caught.exception))


class FileOpsTests(OpsContract, unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        write_tree(self.root)
        self.backend = FileInventory(self.root)
        self.addCleanup(inventory.use(self.backend))

    def imported(self, space, name):
        return (self.root / ("magic" if space == "home" else f"magic/people/{space}") / "imports" / name).read_bytes()

    def break_home(self):
        (self.root / "magic" / "collection.csv").write_text(HOME + "Opt,fdn,512,nonfoil,lots,,,\n", encoding="utf-8")


class PgOpsTests(OpsContract, db_support.DbTestCase):

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
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def imported(self, space, name):
        with self.connect() as c:
            return bytes(c.execute("select c.content from collection_import i join collection_import_content c "
                                   "on c.import_id = i.id where i.space_id = %s and i.file_name = %s",
                                   (space, name)).fetchone()[0])

    def break_home(self):
        self.skipTest("the database can't hold a collection that breaks the rules (a file-only case)")

    def trail(self):
        with self.connect() as c:
            return c.execute("select actor, source, message, reason from audit.change_set order by id").fetchall()

    def test_each_change_is_one_change_set_with_its_message_and_actor(self):
        inventory.apply(Op("collection.remove", {"space": "home", "original": ["lea", "232", "nonfoil"]}),
                        MATT, "remove card Black Lotus (LEA 232) in the home collection", reason="Traded")
        self.assertEqual(self.trail()[-1], ("matt", "web", "remove card Black Lotus (LEA 232) in the home collection",
                                            "Traded"))
        count = len(self.trail())
        with self.assertRaises(ops.Stale):
            self.apply("collection.add", space="home", sha256="0" * 64, row=elves())
        self.assertEqual(len(self.trail()), count)                  # a refusal writes nothing


class PgCollectionApiTests(db_support.DbTestCase):
    """The Collection page's API with the database backend: the same answers as with files."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.api import collection_edit as ce
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        from decklab.tests.test_api import Sandbox, _write
        from decklab.tests.test_collection_edit import ROLES
        self.ce = ce
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        self.box = Sandbox().start()
        self.addCleanup(self.box.stop)
        _write(self.box.root / "config.json", json.dumps(ROLES))
        write_tree(self.box.root)
        pg.write_model(adapt(FileInventory(self.box.root).load()), CLAUDE, "Import the test inventory",
                       contents=import_contents(self.box.root), dbname=self.dbname)
        shutil.rmtree(self.box.magic / "people")                    # the database is all there is
        (self.box.magic / "collection.csv").unlink()
        self.addCleanup(inventory.use(pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())))
        for name, value in (("IMPORTS_DIR", self.box.data / "collection-imports"),
                            ("_upload_date", lambda: "2026-10-10")):
            patcher = mock.patch.object(ce, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def call(self, function, **data):
        # A space's own person writes it (E10-S29: Matt, an admin, no longer writes User2's).
        space = data.get("space") or "home"
        return function(json.dumps({"profile": "matt" if space == "home" else space, **data}).encode("utf-8"))

    def test_save_and_import_through_the_database(self):
        ce = self.ce
        view = ce.rows_view("user2")
        self.assertEqual(view["sha256"], hashlib.sha256(USER2.encode()).hexdigest())
        self.assertNotIn("commit_pending", view)
        answer = self.call(ce.save_card, space="user2", sha256=view["sha256"], action="add",
                           row={"name": "Llanowar Elves", "set": "fdn", "collector_number": "227",
                                "finish": "nonfoil", "quantity": 1})
        self.assertEqual((answer["merged"], "commit" in answer), (False, False))
        self.assertEqual(answer["sha256"], ce.rows_view("user2")["sha256"])
        with self.assertRaises(ce.ApiError) as caught:
            self.call(ce.save_card, space="user2", sha256=view["sha256"], action="remove",
                      original={"set": "fdn", "collector_number": "227", "finish": "nonfoil"})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.extra["sha256"], answer["sha256"])
        preview = self.call(ce.import_preview, space="user2", filename="More.csv",
                            text=HEADER + "Black Lotus,lea,232,nonfoil,1,NM,en,\n")
        applied = self.call(ce.import_apply, space="user2", token=preview["token"], sha256=answer["sha256"])
        self.assertEqual(applied["raw"], "magic/people/user2/imports/2026-10-10-more.csv")
        self.assertEqual(applied["added"], {"rows": 1, "cards": 1})
        with self.connect() as c:
            messages = [r[0] for r in c.execute("select message from audit.change_set order by id")]
            names = [r[0] for r in c.execute("select file_name from collection_import where space_id = 'user2' "
                                             "order by file_name")]
        self.assertEqual(messages[-2:], ["add card Llanowar Elves (FDN 227) in User2's collection",
                                         "import 1 cards into User2's collection from More.csv"])
        self.assertEqual(names, ["2026-10-01-old.csv", "2026-10-10-more.csv"])
        self.assertFalse((self.box.magic / "people").exists())      # nothing went to files

    def test_repeat_preview_uses_the_original_import_actor_and_date_without_exposing_the_upload(self):
        ce = self.ce
        text = (tce.HEADER.rstrip("\n") + ",Purchase price\n"
                "Aerie Mystics,con,1,foil,3,LP,en,from a trade,987.65\n")
        first = self.call(ce.import_preview, profile="user2", space="user2", filename="First.csv", text=text)
        self.assertEqual(first["repeat_imports"], [])
        saved = self.call(ce.import_apply, profile="user2", space="user2", token=first["token"],
                          sha256=first["sha256"])
        with self.connect() as c:
            stored_at = c.execute("select imported_at from collection_import where space_id = 'user2' "
                                  "and file_name = '2026-10-10-first.csv'").fetchone()[0]
        again = self.call(ce.import_preview, space="user2", filename="Renamed.csv", text=text)
        self.assertEqual(again["repeat_imports"], [{"name": "2026-10-10-first.csv",
                                                   "imported_at": stored_at.isoformat(), "imported_by": "User2"}])
        self.assertNotIn("987.65", json.dumps(again))
        self.call(ce.import_apply, space="user2", token=again["token"], sha256=saved["sha256"])
        with self.connect() as c:
            message = c.execute("select message from audit.change_set order by id desc limit 1").fetchone()[0]
            contents = [bytes(r[0]) for r in c.execute(
                "select content from collection_import_content c join collection_import i on i.id = c.import_id "
                "where i.space_id = 'user2' and i.file_name != '2026-10-01-old.csv'")]
        self.assertIn("intentional repeat import", message)
        self.assertIn("2026-10-10-first.csv", message)
        self.assertNotIn("987.65", message)
        self.assertEqual(contents, [text.encode("utf-8"), text.encode("utf-8")])


class CollectionCliTests(unittest.TestCase):
    """python -m decklab.db collection: list, and merge's card-name check (the fixture index)."""

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        index = cards.build_index(FIXTURES / "default_cards.jsonl", FIXTURES / "oracle_tags.jsonl",
                                  {"default_cards": "2026-09-28T21:05:39+00:00"}, log=lambda *a: None)
        cards.write_index(index, tmp / "index.json.gz")
        for name, value in (("INDEX_FILE", tmp / "index.json.gz"), ("_index", None)):
            patcher = mock.patch.object(cards, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = tmp / "tree"
        write_tree(self.root)
        self.addCleanup(inventory.use(FileInventory(self.root)))

    def run_cli(self, func, **args):
        out = io.StringIO()
        with _private_visibility(), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()), inventory.pinned():
            self.assertEqual(func(argparse.Namespace(space="home", **args)), 0)
        return out.getvalue()

    def test_list_prints_the_collection(self):
        self.assertEqual(self.run_cli(inv_collection._list), HOME)

    def test_merge_refuses_a_name_that_isnt_scryfalls(self):
        path = self.root / "in.csv"
        path.write_text(HEADER + "llanowar elves,fdn,227,nonfoil,1,,,\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "isn't a card's exact Scryfall name \\(Scryfall calls it "
                                                "'Llanowar Elves'\\)"):
            self.run_cli(inv_collection._merge, files=[str(path)], message="x")
        self.assertEqual((self.root / "magic" / "collection.csv").read_text(encoding="utf-8"), HOME)
        path.write_text(HEADER + "Llanowar Elves,fdn,227,nonfoil,1,,,\n", encoding="utf-8")
        output = self.run_cli(inv_collection._merge, files=[str(path)], message="x")
        self.assertIn("1 cards merged: 0 new rows, 1 existing rows increased.", output)
        self.assertIn("The home collection now has 2 rows, 4 cards.", output)

    def test_the_command_is_registered(self):
        from decklab.db import __main__ as cli
        args = cli.parser().parse_args(["collection", "merge", "a.csv", "--space", "user2", "-m", "Add"])
        self.assertEqual((args.func, args.files, args.space, args.message), (inv_collection._merge, ["a.csv"],
                                                                             "user2", "Add"))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.parser().parse_args(["collection", "merge", "a.csv"])          # -m is required


class CollectionCliSandboxTests(tce.CollectionEditTestCase):
    """collection merge on the files backend in test_collection_edit's sandbox: one write by
    Claude with the -m message, and a recorded order's file refused."""

    def merge(self, *paths, message="Add the trade binder"):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), inventory.pinned():
            self.assertEqual(inv_collection._merge(argparse.Namespace(space="user2", files=[str(p) for p in paths],
                                                                      message=message)), 0)
        return out.getvalue()

    def test_merge_writes_as_claude(self):
        path = self.box.root / "trade.csv"
        path.write_text(tce.HEADER + "Black Lotus,lea,232,nonfoil,1,NM,en,\n", encoding="utf-8")
        output = self.merge(path)
        self.assertIn("1 cards merged: 1 new rows, 0 existing rows increased.", output)
        self.assertEqual(self.last_write(), ("Add the trade binder", "Claude"))
        self.assertTrue((self.box.magic / "people/user2/imports" / f"{date.today().isoformat()}-trade.csv").is_file())

    def test_merge_warns_before_an_intentional_repeat_and_audits_it(self):
        path = self.box.root / "trade.csv"
        path.write_bytes((tce.HEADER + "Black Lotus,lea,232,nonfoil,1,NM,en,\n").encode("utf-8"))
        self.merge(path)
        renamed = path.with_name("renamed.csv")
        renamed.write_bytes(path.read_bytes())
        warning = io.StringIO()
        with contextlib.redirect_stderr(warning):
            self.merge(renamed, message="Add the second physical batch")
        self.assertIn("identical content was already imported into this space", warning.getvalue())
        self.assertIn("date: unknown; by: unknown", warning.getvalue())
        self.assertIn("intentional repeat import", self.last_write()[0])
        self.assertTrue(self.last_write()[0].startswith("Add the second physical batch;"))
        lotus = next(r for r in self.rows("user2")["rows"] if r["name"] == "Black Lotus")
        self.assertEqual(lotus["quantity"], "2")

    def test_merge_warns_and_audits_duplicate_content_within_the_supplied_batch(self):
        path = self.box.root / "trade.csv"
        path.write_bytes((tce.HEADER + "Black Lotus,lea,232,nonfoil,1,NM,en,\n").encode("utf-8"))
        warning = io.StringIO()
        with contextlib.redirect_stderr(warning):
            self.merge(path, path)
        self.assertIn("more than once in the supplied files", warning.getvalue())
        self.assertIn("intentional repeat import within supplied files", self.last_write()[0])
        lotus = next(r for r in self.rows("user2")["rows"] if r["name"] == "Black Lotus")
        self.assertEqual(lotus["quantity"], "2")

    def test_merge_names_the_space_s_decks_whose_tables_are_now_out_of_date(self):
        deck = ("# R Table\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** idea\n\n## Decklist\n\n"
                "```\nDeck\n4 Llanowar Elves (FDN) 227\n```\n\n## Owned vs needed\n\n"
                "| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |\n|---|---|---|---|---|---|---|\n"
                "| Llanowar Elves | 4 | 2 | **2** | | | |\n| **Total to buy** | | | **2** | | | |\n")
        path = self.box.magic / "people" / "user2" / "decks" / "casual" / "r-table.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(deck, encoding="utf-8")
        trade = self.box.root / "trade.csv"
        trade.write_text(tce.HEADER + "Llanowar Elves,fdn,227,nonfoil,1,NM,en,\n", encoding="utf-8")
        output = self.merge(trade)
        self.assertIn("1 deck's owned-vs-needed table is now out of date: user2/casual/r-table (R Table).", output)
        # deck tables --apply plans every space, so the sandbox's home decks (one without a decklist,
        # some without a table) are named instead of the command (test_inv_decks has the command).
        self.assertIn("deck tables --apply would refuse until this is fixed:", output)
        self.assertIn("casual/broken (Broken) has no decklist", output)
        self.assertNotIn("Update it:", output)
        # A deck of the space's own that would make it refuse is named too.
        path.with_name("r-bad.md").write_text(
            deck.replace("R Table", "R Bad").replace("Llanowar Elves", "Not A Real Card Name"), encoding="utf-8")
        output = self.merge(trade, message="Another")
        self.assertIn("deck tables --apply would refuse until this is fixed:", output)
        self.assertIn("user2/casual/r-bad (R Bad) has card names Scryfall doesn't know in its target list: "
                      "Not A Real Card Name.", output)
        self.assertNotIn("Update it:", output)

    def test_merge_says_nothing_of_tables_when_none_is_stale_and_never_fails_on_them(self):
        trade = self.box.root / "trade.csv"
        trade.write_text(tce.HEADER + "Black Lotus,lea,232,nonfoil,1,NM,en,\n", encoding="utf-8")
        self.assertNotIn("out of date", self.merge(trade))
        with mock.patch("decklab.lib.pool.stale_tables", side_effect=RuntimeError("no card data")):
            output = self.merge(trade, message="Again")
        self.assertIn("Whether other decks' tables are out of date couldn't be worked out (no card data).", output)

    def test_merge_refuses_recorded_orders(self):
        order = self.box.magic / "orders" / "2026-10-10-x.csv"
        order.parent.mkdir(parents=True, exist_ok=True)
        order.write_text(tce.HEADER + "Black Lotus,lea,232,nonfoil,1,NM,en,\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Recorded orders/products must use"):
            self.merge(order)


class CollectionEditCliTests(tce.CollectionEditTestCase):
    """collection edit (E7-S25) in test_collection_edit's sandbox: User2's Llanowar Elves (FDN 227,
    nonfoil, 2, NM, en). Only the fields given change, as one write by Claude with the -m message;
    --quantity 0 removes the row and needs --reason; --expect is collection list's sha."""

    BUILT = ("# R Elves\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** built\n\n## Decklist\n\n"
             "```\nDeck\n2 Llanowar Elves (FDN) 227\n```\n\n## Owned vs needed\n\n"
             "| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |\n|---|---|---|---|---|---|---|\n"
             "| Llanowar Elves | 2 | 2 | 0 | | | |\n| **Total to buy** | | | 0 | | | |\n")

    def sha(self):
        err = io.StringIO()
        with _private_visibility(), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err), inventory.pinned():
            inv_collection._list(argparse.Namespace(space="user2"))
        return _listing_sha(self, err.getvalue())

    def edit(self, *, code=0, expect=None, message="Fix the elves", **options):
        args = dict(space="user2", set="fdn", number="227", finish="nonfoil", quantity=None, condition=None,
                    language=None, notes=None, reason=None, allow_in_use=False, dry_run=False, message=message)
        args.update(options)
        args["expect"] = (self.sha() if expect is None else expect)[:12]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), inventory.pinned():
            self.assertEqual(inv_collection._edit(argparse.Namespace(**args)), code)
        return out.getvalue() + err.getvalue()

    def elves(self):
        return next((r for r in self.rows("user2")["rows"] if r["name"] == "Llanowar Elves"), None)

    def test_only_the_given_fields_change_in_one_write_by_claude(self):
        output = self.edit(condition="lp", notes="From the trade binder")
        self.assertIn("Changed Llanowar Elves (FDN 227, nonfoil) in User2's collection: condition NM -> LP, "
                      "notes (blank) -> From the trade binder.", output)
        self.assertEqual(self.elves(), {**tce_row(), "condition": "LP", "notes": "From the trade binder"})
        self.assertEqual(self.last_write(), ("Fix the elves", "Claude"))
        self.edit(language="", quantity=3)          # "" clears a field
        self.assertEqual((self.elves()["language"], self.elves()["quantity"]), ("", "3"))
        self.assertIn("Nothing to change", self.edit(quantity=3))
        self.assertEqual(len(self.writes), 2)

    def test_quantity_0_removes_the_row_with_its_reason(self):
        with self.assertRaisesRegex(ValueError, "give --reason"):
            self.edit(quantity=0)
        output = self.edit(quantity=0, reason="Traded to User3")
        self.assertIn("Removed Llanowar Elves (FDN 227, nonfoil) (2 copies) from User2's collection.", output)
        self.assertIsNone(self.elves())
        self.assertEqual(self.reason(), "Traded to User3")

    def test_a_dry_run_saves_nothing(self):
        output = self.edit(quantity=1, dry_run=True)
        self.assertIn("Would change Llanowar Elves (FDN 227, nonfoil) in User2's collection: quantity 2 -> 1.",
                      output)
        self.assertIn("Nothing saved (--dry-run).", output)
        self.assertEqual((self.writes, self.elves()["quantity"]), ([], "2"))

    def test_refusals(self):
        sha = self.sha()
        for options, error, words in (
                ({}, ValueError, "Give at least one of"),
                ({"condition": "Mint"}, ValueError, "--condition must be NM, LP, MP, HP, DMG"),
                ({"language": "English"}, ValueError, "--language must be one of Scryfall's codes"),
                ({"notes": "=SUM(A1)"}, ValueError, "can't start with = \\+ - or @"),
                ({"notes": "two\nlines"}, ValueError, "--notes: notes must be one line"),
                ({"quantity": 10000}, ValueError, "from 0 to 9999"),
                ({"quantity": 1, "message": " "}, ValueError, "-m needs a message"),
                ({"quantity": 1, "number": "1"}, ValueError, "User2's collection has no FDN 1 nonfoil row"),
                ({"quantity": 1, "expect": "abc"}, ValueError, "--expect needs the sha collection list printed"),
                ({"quantity": 1, "expect": "0" * 12}, inventory.Conflict, "has changed since that listing")):
            with self.subTest(options=options), self.assertRaisesRegex(error, words):
                self.edit(**{"expect": sha, **options})
        self.assertEqual(self.writes, [])

    def test_a_reduction_below_what_built_decks_hold_needs_allow_in_use(self):
        path = self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.BUILT, encoding="utf-8")
        output = self.edit(quantity=1, dry_run=True)
        self.assertIn("In use: Llanowar Elves: 2 -> 1 copies, but 2 are held (2 in R Elves)", output)
        self.assertIn("Would leave 1 deck's owned-vs-needed table out of date: user2/casual/r-elves (R Elves).",
                      output)
        output = self.edit(quantity=1, code=1)
        self.assertIn("Not saved: fewer copies would be left than built decks or intact products hold", output)
        self.assertEqual((self.writes, self.elves()["quantity"]), ([], "2"))
        output = self.edit(quantity=1, allow_in_use=True)
        self.assertIn("1 deck's owned-vs-needed table is now out of date: user2/casual/r-elves (R Elves).", output)
        self.assertEqual(self.elves()["quantity"], "1")

    def test_the_command_is_registered(self):
        from decklab.db import __main__ as cli
        args = cli.parser().parse_args(["collection", "edit", "fdn", "227", "nonfoil", "--condition", "NM",
                                        "--expect", "a" * 12, "-m", "Fix"])
        self.assertEqual((args.func, args.set, args.number, args.finish, args.condition, args.space),
                         (inv_collection._edit, "fdn", "227", "nonfoil", "NM", "home"))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.parser().parse_args(["collection", "edit", "fdn", "227", "nonfoil", "-m", "Fix"])    # --expect


class CollectionApplyCliTests(tce.CollectionEditTestCase):
    """collection apply (E7-S26) in test_collection_edit's sandbox, with User2's collection three
    rows: an edited copy of collection list's output becomes the collection as one write by Claude
    with the -m message; rows left out (or at quantity 0) are removed and need --reason; new keys,
    changed names and repeated keys are refused, and the listing as printed changes nothing."""

    ROWS = (tce.HEADER + "Elvish Mystic,cmm,648,nonfoil,1,,,Reign of Dragons precon\n"
            "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\nBlack Lotus,lea,232,nonfoil,1,,,\n")

    def setUp(self):
        super().setUp()
        (self.box.magic / "people" / "user2" / "collection.csv").write_text(self.ROWS, encoding="utf-8",
                                                                              newline="")

    def listing(self):
        """(collection list's CSV, its sha) for User2's space."""
        out, err = io.StringIO(), io.StringIO()
        with _private_visibility(), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), inventory.pinned():
            inv_collection._list(argparse.Namespace(space="user2"))
        return out.getvalue(), _listing_sha(self, err.getvalue())

    def file(self, text, name="cards.csv", data=None):
        path = self.box.root / name
        path.write_bytes(data if data is not None else text.encode("utf-8"))
        return path

    def run_apply(self, path, *, code=0, expect=None, message="Fix User2's cards", **options):
        args = dict(space="user2", file=str(path), reason=None, allow_in_use=False, remove_missing=False,
                    dry_run=False, message=message)
        args.update(options)
        args["expect"] = (self.listing()[1] if expect is None else expect)[:12]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), inventory.pinned():
            self.assertEqual(inv_collection._apply(argparse.Namespace(**args)), code)
        return out.getvalue() + err.getvalue()

    def edited(self, *changes):
        """collection list's CSV with each (old line, new line) replaced."""
        text = self.listing()[0]
        for old, new in changes:
            self.assertIn(old, text)
            text = text.replace(old, new)
        return text

    def by_key(self):
        return {(r["set"], r["collector_number"]): r for r in self.rows("user2")["rows"]}

    def test_the_listing_as_printed_changes_nothing(self):
        output = self.run_apply(self.file(self.listing()[0]))
        self.assertIn("Nothing to change: User2's collection already matches", output)
        self.assertIn("(3 rows)", output)
        self.assertEqual(self.writes, [])

    def test_several_rows_change_in_one_write_by_claude(self):
        text = self.edited(("Elvish Mystic,cmm,648,nonfoil,1,,,", "Elvish Mystic,cmm,648,nonfoil,1,nm,EN,"),
                           ("Black Lotus,lea,232,nonfoil,1,,,", "Black Lotus,lea,232,nonfoil,3,LP,en,Sealed"))
        output = self.run_apply(self.file(text))
        self.assertIn("Made User2's collection match", output)
        self.assertIn("2 rows changed, 0 removed, 1 unchanged.", output)
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.last_write(), ("Fix User2's cards", "Claude"))
        self.assertEqual(self.writes[-1][3].text, "edit 2 rows in User2's collection")
        rows = self.by_key()
        self.assertEqual((rows["cmm", "648"]["condition"], rows["cmm", "648"]["language"],
                          rows["cmm", "648"]["notes"]), ("NM", "en", "Reign of Dragons precon"))
        self.assertEqual({k: rows["lea", "232"][k] for k in ("quantity", "condition", "language", "notes")},
                         {"quantity": "3", "condition": "LP", "language": "en", "notes": "Sealed"})
        self.assertEqual(rows["fdn", "227"], tce_row())

    def test_removals_need_a_reason(self):
        text = self.edited(("Black Lotus,lea,232,nonfoil,1,", "Black Lotus,lea,232,nonfoil,0,"),
                           ("Llanowar Elves,fdn,227,nonfoil,2,", "Llanowar Elves,fdn,227,nonfoil,0,"))
        with self.assertRaisesRegex(ValueError, r"2 rows would be removed \(2 at quantity 0\): give --reason"):
            self.run_apply(self.file(text))
        self.assertEqual(self.writes, [])
        output = self.run_apply(self.file(text), reason="Traded to User3")
        self.assertIn("0 rows changed, 2 removed, 1 unchanged", output)
        self.assertEqual(set(self.by_key()), {("cmm", "648")})
        self.assertEqual((len(self.writes), self.reason()), (1, "Traded to User3"))

    def test_rows_left_out_are_refused_even_with_a_reason(self):
        lines = self.listing()[0].splitlines(keepends=True)
        filtered = self.edited(("Elvish Mystic,cmm,648,nonfoil,1,,,", "Elvish Mystic,cmm,648,nonfoil,1,NM,en,"))
        filtered = "".join(line for line in filtered.splitlines(keepends=True) if ",cmm," in line or "name," in line)
        for name, text, left_out, listed in (
                ("cut off", "".join(lines[:3]), "1 row of User2's collection is", "2 rows"),
                ("header only", lines[0], "3 rows of User2's collection are", "0 rows"),
                ("filtered", filtered, "2 rows of User2's collection are", "1 row")):
            for dry_run in (False, True):
                with self.subTest(name=name, dry_run=dry_run), self.assertRaisesRegex(
                        ValueError, f"{left_out} left out of .*cards.csv \\(it lists {listed}\\): set a row's "
                                    "quantity to 0 to remove it, or give --remove-missing"):
                    self.run_apply(self.file(text), reason="Sold", allow_in_use=True, dry_run=dry_run)
        self.assertEqual((self.writes, len(self.by_key())), ([], 3))

    def test_remove_missing_removes_the_rows_left_out(self):
        text = self.edited(("Black Lotus,lea,232,nonfoil,1,,,\n", ""),
                           ("Llanowar Elves,fdn,227,nonfoil,2,", "Llanowar Elves,fdn,227,nonfoil,0,"))
        with self.assertRaisesRegex(ValueError, r"2 rows would be removed \(1 at quantity 0, 1 left out of the "
                                                r"file \(--remove-missing\)\): give --reason"):
            self.run_apply(self.file(text), remove_missing=True)
        output = self.run_apply(self.file(text), remove_missing=True, dry_run=True)
        self.assertIn("0 rows changed, 2 removed, 1 unchanged", output)
        self.assertIn("Would remove Black Lotus (LEA 232, nonfoil) (1 copy).", output)
        output = self.run_apply(self.file(text), remove_missing=True, reason="Traded to User3")
        self.assertIn("0 rows changed, 2 removed, 1 unchanged", output)
        self.assertEqual(set(self.by_key()), {("cmm", "648")})
        self.assertEqual((len(self.writes), self.reason()), (1, "Traded to User3"))

    def test_the_columns_may_come_in_any_order(self):
        rows = list(csv.DictReader(io.StringIO(self.listing()[0])))

        def reordered():
            out = io.StringIO()
            writer = csv.DictWriter(out, list(reversed(rules.FIELDS)), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            return out.getvalue()
        self.assertIn("Nothing to change", self.run_apply(self.file(reordered())))
        rows[2]["condition"] = "LP"
        self.assertIn("1 row changed, 0 removed, 2 unchanged", self.run_apply(self.file(reordered())))
        self.assertEqual(self.by_key()[rows[2]["set"], rows[2]["collector_number"]]["condition"], "LP")

    def test_a_row_the_card_check_refuses_saves_nothing(self):
        from decklab.lib.api import collection_edit as page
        text = self.edited(("Black Lotus,lea,232,nonfoil,1,,,", "Black Lotus,lea,232,nonfoil,1,NM,,"))
        with mock.patch.object(page, "match", side_effect=lambda row: (row, "no such printing")), \
                self.assertRaisesRegex(ValueError, r"cards.csv: Black Lotus \(LEA 232, nonfoil\): The card can't "
                                                   "be saved: no such printing"):
            self.run_apply(self.file(text))
        self.assertEqual(self.writes, [])

    def test_windows_line_endings_and_a_byte_order_mark(self):
        text = self.edited(("Black Lotus,lea,232,nonfoil,1,,,", "Black Lotus,lea,232,nonfoil,1,NM,,"))
        data = b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8")
        self.assertIn("1 row changed, 0 removed, 2 unchanged", self.run_apply(self.file("", data=data)))
        self.assertEqual(self.by_key()["lea", "232"]["condition"], "NM")
        self.assertIn("Nothing to change",
                      self.run_apply(self.file("", data=b"\xef\xbb\xbf" + self.listing()[0].replace(
                          "\n", "\r\n").encode("utf-8"))))

    def test_a_listing_redirected_to_a_file_is_utf_8_and_applies_unchanged(self):
        (self.box.magic / "people" / "user2" / "collection.csv").write_text(
            self.ROWS.replace("Reign of Dragons precon", "Ōkami trade 日本"), encoding="utf-8", newline="")
        raw = io.BytesIO()
        stdout = io.TextIOWrapper(raw, encoding="cp1252", errors="replace")    # a Windows pipe's code page
        with _private_visibility(), contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(io.StringIO()), inventory.pinned():
            inv_collection._list(argparse.Namespace(space="user2"))
        self.assertIn("Ōkami trade 日本".encode("utf-8"), raw.getvalue())
        self.assertIn("Nothing to change", self.run_apply(self.file("", data=raw.getvalue())))

    def test_refusals(self):
        listing, sha = self.listing()
        for text, error, words in (
                (listing + "Sol Ring,ecc,57,nonfoil,1,,,\n", ValueError, "has no ECC 57 nonfoil row.*collection merge"),
                (listing.replace("Black Lotus,", "Mox Pearl,"), ValueError, "'Black Lotus' in the collection, not "
                                                                            "'Mox Pearl'"),
                (listing + "Black Lotus,lea,232,nonfoil,1,,,\n", ValueError, "line 5: LEA 232 nonfoil is listed twice"),
                ("name,set\nBlack Lotus,lea\n", ValueError, "needs collection list's columns"),
                (listing + "Black Lotus,lea,232\n", ValueError, "line 5: 3 columns, not 8"),
                (listing.replace("232,nonfoil,1,,", "232,shiny,1,,"), ValueError, "finish must be"),
                (listing.replace("232,nonfoil,1,,", "232,nonfoil,-1,,"), ValueError, "quantity must be a whole number"),
                (listing.replace("232,nonfoil,1,,", "232,nonfoil,10000,,"), ValueError, "from 0 to 9999"),
                (listing.replace("232,nonfoil,1,,", "232,nonfoil,1,Mint,"), ValueError, "condition must be NM"),
                (listing.replace("232,nonfoil,1,,,", "232,nonfoil,1,,English,"), ValueError, "Scryfall's codes"),
                (listing.replace("232,nonfoil,1,,,", "232,nonfoil,1,,,=SUM(A1)"), ValueError,
                 "can't start with = \\+ - or @"),
                (listing.replace("232,nonfoil,1,,,", '232,nonfoil,1,,,"two\rlines"'), ValueError,
                 "notes must be one line")):
            with self.subTest(text=text[-40:]), self.assertRaisesRegex(error, words):
                self.run_apply(self.file(text), expect=sha)
        changed = listing.replace("232,nonfoil,1,,", "232,nonfoil,1,NM,")
        with self.assertRaisesRegex(inventory.Conflict, "has changed since that listing"):
            self.run_apply(self.file(changed), expect="0" * 12)
        with self.assertRaisesRegex(ValueError, "--expect needs the sha"):
            self.run_apply(self.file(changed), expect="abc")
        with self.assertRaisesRegex(ValueError, "-m needs a message"):
            self.run_apply(self.file(changed), message=" ")
        self.assertEqual(self.writes, [])

    def test_a_stale_listing_is_refused(self):
        listing, sha = self.listing()
        self.run_apply(self.file(listing.replace("232,nonfoil,1,,", "232,nonfoil,1,NM,")))
        with self.assertRaisesRegex(inventory.Conflict, "has changed since that listing"):
            self.run_apply(self.file(listing.replace("227,nonfoil,2,", "227,nonfoil,3,")), expect=sha)
        self.assertEqual(len(self.writes), 1)

    def test_a_dry_run_saves_nothing(self):
        text = self.edited(("Black Lotus,lea,232,nonfoil,1,", "Black Lotus,lea,232,nonfoil,0,"),
                           ("Llanowar Elves,fdn,227,nonfoil,2,NM,", "Llanowar Elves,fdn,227,nonfoil,1,LP,"))
        output = self.run_apply(self.file(text), dry_run=True)
        self.assertIn("Would make User2's collection match", output)
        self.assertIn("1 row changed, 1 removed, 1 unchanged.", output)
        self.assertIn("Would change Llanowar Elves (FDN 227, nonfoil): quantity 2 -> 1, condition NM -> LP.", output)
        self.assertIn("Would remove Black Lotus (LEA 232, nonfoil) (1 copy).", output)
        self.assertIn("Saving it needs --reason", output)       # a dry run says so rather than refusing
        self.assertIn("Nothing saved (--dry-run).", output)
        self.assertEqual((self.writes, self.by_key()["fdn", "227"]["quantity"]), ([], "2"))

    def test_reductions_below_what_built_decks_hold_need_allow_in_use(self):
        path = self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CollectionEditCliTests.BUILT, encoding="utf-8")
        text = self.edited(("Llanowar Elves,fdn,227,nonfoil,2,", "Llanowar Elves,fdn,227,nonfoil,1,"),
                           ("Black Lotus,lea,232,nonfoil,1,,,", "Black Lotus,lea,232,nonfoil,1,NM,,"))
        output = self.run_apply(self.file(text), dry_run=True)
        self.assertIn("In use: Llanowar Elves: 2 -> 1 copies, but 2 are held (2 in R Elves)", output)
        self.assertIn("Saving it needs --allow-in-use.", output)
        output = self.run_apply(self.file(text), code=1)
        self.assertIn("Not saved: fewer copies would be left than built decks or intact products hold", output)
        self.assertEqual(self.writes, [])
        output = self.run_apply(self.file(text), allow_in_use=True)
        self.assertIn("2 rows changed, 0 removed, 1 unchanged", output)
        self.assertIn("1 deck's owned-vs-needed table is now out of date: user2/casual/r-elves (R Elves).", output)
        self.assertEqual((self.by_key()["fdn", "227"]["quantity"], len(self.writes)), ("1", 1))

    def test_the_command_is_registered(self):
        from decklab.db import __main__ as cli
        args = cli.parser().parse_args(["collection", "apply", "cards.csv", "--space", "user2",
                                        "--expect", "a" * 12, "-m", "Fix", "--dry-run"])
        self.assertEqual((args.func, args.file, args.space, args.dry_run, args.allow_in_use, args.remove_missing),
                         (inv_collection._apply, "cards.csv", "user2", True, False, False))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.parser().parse_args(["collection", "apply", "cards.csv", "-m", "Fix"])    # --expect


class PgCollectionApplyTests(db_support.DbTestCase, tce.CollectionEditTestCase):
    """collection apply with the database backend: many rows changed and removed as one audited
    change set, with the -m message and the reason."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        super().setUp()
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        (self.box.magic / "people" / "user2" / "collection.csv").write_text(
            CollectionApplyCliTests.ROWS, encoding="utf-8", newline="")
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(adapt(FileInventory(self.box.root).load()), CLAUDE, "Import the test inventory",
                       contents=import_contents(self.box.root), dbname=self.dbname)
        self.addCleanup(inventory.use(pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())))

    def test_many_rows_are_one_change_set(self):
        cli = CollectionApplyCliTests.listing
        listing, sha = cli(self)
        text = (listing.replace("648,nonfoil,1,,,", "648,nonfoil,1,NM,en,")
                .replace("232,nonfoil,1,,,", "232,nonfoil,1,NM,en,")
                .replace("227,nonfoil,2,NM,en,", "227,nonfoil,0,NM,en,"))
        path = self.box.root / "cards.csv"
        path.write_text(text, encoding="utf-8")
        with self.connect() as c:
            before = c.execute("select count(*) from audit.change_set").fetchone()[0]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()), inventory.pinned():
            self.assertEqual(inv_collection._apply(argparse.Namespace(
                space="user2", file=str(path), expect=sha[:12], message="Sealed cards are NM", reason="Sold",
                allow_in_use=False, remove_missing=False, dry_run=False)), 0)
        self.assertIn("2 rows changed, 1 removed, 0 unchanged", out.getvalue())
        with self.connect() as c:
            rows = c.execute("select message, reason from audit.change_set order by id").fetchall()
        self.assertEqual((len(rows) - before, rows[-1]), (1, ("Sealed cards are NM", "Sold")))
        found = {(r["set"], r["condition"], r["language"]) for r in ops.rows_of(inventory.current().collection("user2"))}
        self.assertEqual(found, {("cmm", "NM", "en"), ("lea", "NM", "en")})


def tce_row():
    return dict(zip(rules.FIELDS, ["Llanowar Elves", "fdn", "227", "nonfoil", "2", "NM", "en", ""]))


class PgPreconTests(db_support.DbTestCase, tp.PreconTestCase):
    """"Add a precon" with the database backend: the cards and the deck go in as one change set
    (precon.add; none of them to files). While the database holds no decks it's refused as a
    whole, so no card goes in either."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        super().setUp()
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        decks = self._testMethodName != "test_refused_while_the_decks_arent_in_the_database"
        pg.write_model(adapt(FileInventory(self.box.root).load()), CLAUDE, "Import the test inventory",
                       contents=import_contents(self.box.root), dbname=self.dbname, decks=decks)
        self.addCleanup(inventory.use(pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())))

    def test_adds_the_cards_and_the_deck_in_one_change_set(self):
        on_disk = (self.box.magic / "people" / "user2" / "collection.csv").read_bytes()
        answer = self.add()
        self.assertEqual(answer["collection"]["added"], {"rows": 3, "cards": 5})
        self.assertEqual(answer["deck"]["id"], "user2/commander/ghalta-test-dinos")
        self.assertFalse((self.box.magic / "people" / "user2" / "decks").exists())
        with self.connect() as c:
            message = c.execute("select message from audit.change_set order by id desc limit 1").fetchone()[0]
        self.assertEqual(message, "import 5 cards into User2's collection from the Test Dinos precon; new deck "
                                  "Ghalta: Test Dinos")
        self.assertIsNotNone(inventory.current().deck("user2/commander/ghalta-test-dinos"))
        rows = {(r["set"], r["collector_number"]): r for r in self.rows("user2")["rows"]}
        self.assertEqual(rows[("fdn", "227")]["quantity"], "4")
        self.assertEqual((self.box.magic / "people" / "user2" / "collection.csv").read_bytes(), on_disk)
        self.assertFalse((self.box.magic / "people" / "user2" / "imports").exists())
        # The same title again: refused before any card goes in.
        before = self.rows("user2")["rows"]
        self.assertApiError(409, self.add, title=answer["deck"]["title"])
        self.assertEqual(self.rows("user2")["rows"], before)

    def test_refused_while_the_decks_arent_in_the_database(self):
        before = self.rows("user2")["rows"]
        self.assertApiError(503, self.add, contains="the database holds no decks")
        self.assertEqual(self.rows("user2")["rows"], before)
        self.assertFalse((self.box.magic / "people" / "user2" / "decks").exists())


if __name__ == "__main__":
    unittest.main()
