"""Phase 3's export and Activity for the inventory (area F): export.py's magic/ folder and
`inventory export`, the Activity rules for the inventory's rows (filtered, counted and capped in
SQL) and dbstatus's inventory part. (Phase 5b retired the import, the backend switch and the
gate these tests also covered.) A fixture repo's inventory files go into the database with
pg.write_model, in one change set as the import made it.

The database tests need the local PostgreSQL server and skip without it (db_support.py); each
class works in its own throwaway database and temporary folders.

Run from the repo root: .venv\\Scripts\\python -m unittest decklab.tests.test_inventory_ops
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from decklab.db import conn as db
from decklab.db import export, inv_inventory
from decklab.lib import config, dbstatus, permissions
from decklab.lib.api import activity
from decklab.lib.inventory import files, paths
from decklab.lib.inventory.model import CardRow
from decklab.lib.state import Actor, rules
from decklab.tests import db_support
from decklab.tests import test_inventory_contract as contract

SYSTEM = Actor("system", "System", None, "migration")
DECK = "magic/decks/casual/gruul.md"
GIT_ENV = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def _every_kind(t):
    """A fixture tree with something of each kind: orders in every state (cards, tokens, a
    product), person spaces with tokens and a raw import, special basics and a watchlist."""
    contract.recorded_orders(t)
    contract.person_spaces(t)
    contract.special_basics(t)


def tree_files(extra_cards=0):
    """{path: bytes} of a canonical inventory (the database can hold it exactly), raw imports
    included; extra_cards more home collection rows (Card 1 ... in set tst)."""
    case = contract.build_tree(_every_kind, adapted=True)
    try:
        found = files.tree_files(case.inventory.root, import_bytes=True)
    finally:
        case.doCleanups()
    inv = files.build(found)
    if extra_cards:
        rows = list(inv.collection("home").rows) + [
            CardRow.make(name=f"Card {i}", set="tst", collector_number=str(i), finish="nonfoil", quantity="1")
            for i in range(1, extra_cards + 1)]
        inv = inv.with_collection("home", rows)
    out = files.render(inv)
    out.update({rel: data for rel, data in found.items() if paths.classify(rel)[0] == "import"})
    return out


def make_repo(test, extra_cards=0):
    """A temporary git repo holding tree_files() and a deck file, committed. Returns (repo, its
    inventory files)."""
    repo = Path(tempfile.mkdtemp(prefix="decklab-inv-repo-"))
    test.addCleanup(shutil.rmtree, repo, True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "core.autocrlf", "false")
    found = tree_files(extra_cards)
    for rel, data in found.items():
        _write(repo / rel, data)
    _write(repo / DECK, "# Gruul\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "inventory")
    return repo, found


def _sync(dbname):
    from decklab.db import profiles_sync
    return lambda: profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=dbname)


class _InventoryDb(db_support.DbTestCase):
    """A throwaway database with the fixture profiles, its inventory and trail emptied per test."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _sync(cls.dbname)()

    def setUp(self):
        super().setUp()
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        with self.connect("owner") as c:
            c.execute("delete from ops.backup_run")
        self.tmp = Path(tempfile.mkdtemp(prefix="decklab-inv-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        log = mock.patch.object(db, "LOG_FILE", self.tmp / "db.log")
        log.start()
        self.addCleanup(log.stop)

    def import_repo(self, repo):
        """Put repo's inventory files into the database as one change set (system, migration,
        "Import the inventory files"), as the import did until phase 5b."""
        from decklab.lib.inventory.pg import write_model
        _sync(self.dbname)()
        write_model(files.build(files.tree_files(repo, import_bytes=True)), SYSTEM, "Import the inventory files",
                    contents=contract.import_contents(repo), dbname=self.dbname)

@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class ExportTests(_InventoryDb):

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, GIT_ENV)
        env.start()
        self.addCleanup(env.stop)
        self.repo, self.files = make_repo(self)
        self.out = self.tmp / "export"

    def test_magic_is_rebuilt_from_the_database(self):
        export.write_tables(self.out)
        self.assertFalse((self.out / "magic").exists())          # nothing imported yet: left alone
        self.assertIn("public.collection_card.csv", os.listdir(self.out / "tables"))
        self.import_repo(self.repo)
        _write(self.out / "magic/orders/stale.csv", "old\n")
        _write(self.out / "magic/orders/tokens/cancelled/old/deep.csv", "old\n")
        export.write_tables(self.out)
        written = {p.relative_to(self.out).as_posix(): p.read_bytes()
                   for p in (self.out / "magic").rglob("*") if p.is_file()}
        self.assertEqual(written, self.files)
        self.assertFalse((self.out / "magic/orders/tokens/cancelled").exists())   # emptied folders go
        table = (self.out / "tables/public.collection_card.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(table[0], "space_id,set_code,collector_number,finish,name,quantity,condition,language,notes,"
                                   "location")                          # migration 0016's storage location
        self.assertTrue(export._is_export_repo(self.out))       # no commits yet, magic/ allowed

    def test_inventory_export_command(self):
        self.import_repo(self.repo)
        target = self.tmp / "copy"
        self.assertEqual(inv_inventory.export_to(target, dbname=self.dbname), len(self.files))
        written = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
        self.assertEqual(written, self.files)
        with self.assertRaisesRegex(ValueError, "aren't inventory files"):
            inv_inventory.export_to(self.repo, dbname=self.dbname)       # the deck file would go
        self.assertTrue((self.repo / DECK).exists())


def _row(table, op, before=None, after=None, key=None):
    return {"table": table, "op": op, "key": key or {}, "before": before, "after": after}


def _card(space, name, number, qty=1, finish="nonfoil"):
    return {"space_id": space, "name": name, "set_code": "fdn", "collector_number": str(number), "finish": finish,
            "quantity": qty, "condition": "", "language": "", "notes": "private words"}


PROFILES = {p["id"]: p for p in contract.FIXTURE_PROFILES}
USER1 = {"space": "home", "profile": "user1"}
USER2 = {"space": "user2", "profile": "user2"}


class ActivityRuleTests(unittest.TestCase):
    """The inventory rows through rules.inventory_rows (the memory store's way; the database does
    the same in SQL) and visible_change."""

    def change(self, rows, spec_scope, actor="system", source="migration"):
        raw = {"id": 1, "at": "2026-10-12T00:00:00+00:00", "actor": actor, "source": source, "via": None,
               "message": "Import the inventory files", "reason": None, "rows": rows}
        spec = activity.inventory_spec(activity.scope_spaces(spec_scope))
        return rules.inventory_rows(raw, rules.inventory_scope(spec))

    def show(self, rows, scope, me=None, **kw):
        return activity.visible_change(self.change(rows, scope, **kw), scope, PROFILES, me=me)

    def test_each_space_to_its_people_and_admins(self):
        rows = [_row("collection_card", "INSERT", after=_card("home", "Llanowar Elves", 227, 2)),
                _row("collection_card", "INSERT", after=_card("user2", "Shock", 156, 3, "foil")),
                _row("collection_card", "INSERT", after=_card("zed", "Opt", 60)),
                _row("purchase_order", "INSERT", after={"id": "2026-10-08-shop-a", "seller": "MTGMate",
                                                       "audit_notes": "from git"})]
        everything = [r["summary"] for r in self.show(rows, "all", me="matt")["rows"]]
        self.assertEqual(everything, ["Added 2 × Llanowar Elves (FDN 227) to the home collection",
                                      "Added 3 × Shock (FDN 156, foil) to User2's collection",
                                      "Added 1 × Opt (FDN 60) to zed's collection",
                                      "Added the order 2026-10-08-shop-a from MTGMate"])
        user1 = self.show(rows, USER1)
        self.assertEqual([r["summary"] for r in user1["rows"]],
                         [everything[0], everything[3]])
        self.assertIsNone(user1["message"])                    # a command line's words: rows only
        user2 = self.show(rows, USER2)
        self.assertEqual([r["summary"] for r in user2["rows"]],
                         ["Added 3 × Shock (FDN 156, foil) to your collection"])     # his own, as he reads it
        shown = json.dumps(self.show(rows, "all", me="matt"))
        self.assertNotIn("private words", shown)                 # notes aren't sent
        self.assertNotIn("from git", shown)                      # nor an order's audit notes
        # An admin's role opens no other space's inventory (E10-S29): the page passes his spaces.
        matt = {"id": "matt", "role": "admin", "space": "home"}
        self.assertFalse(permissions.sees_inventory(matt, "zed"))
        self.assertFalse(permissions.sees_inventory(matt, "user2"))
        named = activity.visible_change(self.change(rows, USER1), "all", PROFILES, me="matt",
                                        spaces=permissions.inventory_spaces(matt))
        self.assertEqual([r["summary"] for r in named["rows"]], [everything[0], everything[3]])
        self.assertFalse(permissions.sees_inventory({"id": "user1", "role": "member", "space": "home"}, "user2"))
        self.assertTrue(permissions.sees_inventory(None, "home", script=True))
        self.assertFalse(permissions.sees_inventory(None, "home"))

    def test_rows_past_the_cap_are_counted_and_items_are_grouped(self):
        rows = [_row("collection_card", "INSERT", after=_card("home", f"Card {i}", i)) for i in range(60)]
        rows += [_row("collection_card", "INSERT", after=_card("user2", f"Card {i}", i)) for i in range(5)]
        rows += [_row("product_item", "INSERT", after={"cells": ["x"]}, key={"product_stem": "fdn-box", "position": i})
                 for i in range(616)]
        rows += [_row("order_card_item", "DELETE", before={"name": "Opt"},
                      key={"order_id": "o1", "component_id": "cards", "position": 0})]
        admin = self.show(rows, "all", me="matt")["rows"]
        self.assertEqual(len(admin), activity.ROW_CAP + 3)
        self.assertEqual([r["summary"] for r in admin[-3:]],
                         ["Added 616 card rows to the product fdn-box's list", "Removed 1 card row from order o1 (cards)",
                          "and 15 more"])
        user2 = self.show(rows, USER2)["rows"]
        self.assertEqual(len(user2), 5)                       # home's size isn't counted for him
        user1 = self.show(rows, USER1)["rows"]
        self.assertEqual(user1[-1]["summary"], "and 10 more")
        # The copies of the rows past the cap are counted, so the headline's total is exact.
        self.assertEqual(self.change(rows, USER1)["past"], {"collection_card": {"added": 10, "removed": 0, "unknown": 0}})
        self.assertIn("added 60 cards to the collection", self.show(rows, USER1)["headline"])
        self.assertNotIn("at least", self.show(rows, USER1)["headline"])

    def test_moves_are_left_out_and_changes_said_plainly(self):
        token = {"space_id": "home", "front": "Dog", "back": "Beast", "quantity": 1, "position": 1024}
        rows = [_row("token_card", "UPDATE", before=token, after=dict(token, position=2048)),
                _row("token_card", "UPDATE", before=token, after=dict(token, quantity=2)),
                _row("order_component", "UPDATE", before={"order_id": "o1", "id": "cards", "status": "pending"},
                     after={"order_id": "o1", "id": "cards", "status": "received", "received_on": "2026-10-09"}),
                _row("watchlist_item", "UPDATE", before={"name": "Opt", "quantity": 2, "listed_aud": "0.50"},
                     after={"name": "Opt", "quantity": 1, "listed_aud": "0.40"}),
                _row("collection_import", "INSERT", after={"space_id": "user2", "file_name": "a.csv", "size": 9})]
        summaries = [r["summary"] for r in self.show(rows, "all", me="matt")["rows"]]
        # The receipt's own row is left out: the headline says it and links the order.
        shown = self.show(rows, "all", me="matt")
        self.assertEqual(shown["link"], {"order": "o1"})
        self.assertEqual(summaries, ["Changed Dog // Beast in the home token cards: quantity 1 → 2",
                                     "Changed Opt on the watchlist: quantity 2 → 1, price or stock",
                                     "Kept the raw import a.csv for User2's collection"])

    def test_a_kit_change_shows_its_words_only_to_who_made_it(self):
        before = {"file": "box.csv", "status": "owned", "intact": "yes", "sleeves": "", "deck_box": ""}
        rows = [_row("product_status", "UPDATE", before=before, after=dict(before, sleeves="dragon-shield-black"))]
        for scope, me, seen in (("all", "matt", False), (USER1, None, True), ("all", None, True)):
            with self.subTest(scope=scope, me=me):
                shown = self.show(rows, scope, me=me, actor="user1", source="web")
                self.assertEqual(shown["message"] is not None, seen)
                self.assertEqual(shown["rows"][0]["summary"], "The product box: sleeves")

    def test_a_kit_change_past_the_cap_still_hides_the_words(self):
        before = {"file": "box.csv", "status": "owned", "intact": "yes", "sleeves": "", "deck_box": ""}
        rows = [_row("collection_card", "INSERT", after=_card("home", f"Card {i}", i)) for i in range(60)]
        rows.append(_row("product_status", "UPDATE", before=before, after=dict(before, deck_box="boulder")))
        shown = self.show(rows, "all", me="matt", actor="user1", source="web")
        self.assertNotIn("product_status", [r["table"] for r in shown["rows"]])     # past the cap
        self.assertIsNone(shown["message"])
        # A status row added or removed (an import, a replace) isn't a kit change.
        added = [_row("product_status", "INSERT", after=dict(before, sleeves="dragon-shield-black"))]
        self.assertEqual(self.show(added, "all", me="matt")["message"], "Import the inventory files")

    def test_a_wishlist_rule_counts_rows_the_database_left_out(self):
        rows = [_row("wishlist_entry", "INSERT", after={"profile_id": "user2", "name": "Opt"}),
                _row("collection_card", "INSERT", after=_card("home", "Opt", 60))]
        shown = self.show(rows, USER2, source="web")
        self.assertEqual(len(shown["rows"]), 1)
        self.assertIsNone(shown["message"])                     # he doesn't see every row of it


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class ActivityDbTests(_InventoryDb):
    """The same rules from the database: an import's change set, filtered and capped in SQL."""

    def test_the_import_change_set_as_each_viewer_gets_it(self):
        from decklab.lib.state import pg as state_pg
        repo, _ = make_repo(self, extra_cards=70)
        self.import_repo(repo)
        store = state_pg.PgStore(breaker=state_pg.Breaker())

        def page(scope, me=None):
            return store.activity(limit=10, inventory=activity.inventory_spec(activity.scope_spaces(scope)),
                                  visible=lambda c: activity.visible_change(c, scope, PROFILES, me=me))["changes"]
        admin = page("all", "matt")
        imported = [c for c in admin if c["message"] == "Import the inventory files"][0]
        summaries = [r["summary"] for r in imported["rows"]]
        listed = [r for r in imported["rows"] if r["table"] in activity.INVENTORY_FIELDS]
        self.assertEqual(len(listed), activity.ROW_CAP)
        self.assertIn("Added 1 card row to the product precon's list", summaries)
        with self.connect("ro") as c:
            total = c.execute("select count(*) from audit.row_change where change_set_id = %s and not table_name = "
                              "any(%s)", (imported["id"], list(activity.ITEM_TABLES))).fetchone()[0]
        self.assertEqual(summaries[-1], f"and {total - activity.ROW_CAP} more")
        user2 = [c for c in page(USER2) if c["id"] == imported["id"]][0]
        self.assertEqual([r["summary"] for r in user2["rows"]],
                         ["Added 3 × Shock (M19 156) to your collection",
                          "Added 2 × Goblin to your token cards",
                          "Kept the raw import 2026-10-10-precon.csv for your collection"])
        # The memory store's way gives the same rows.
        with self.connect("ro") as c:
            raw = c.execute("select table_name, op, row_key, before, after from audit.row_change "
                            "where change_set_id = %s order by id", (imported["id"],)).fetchall()
        change = {"id": imported["id"], "at": imported["at"], "actor": "system", "source": "migration", "via": None,
                  "message": "m", "reason": None,
                  "rows": [{"table": t, "op": o, "key": k, "before": b, "after": a} for t, o, k, b, a in raw]}
        spec = rules.inventory_scope(activity.inventory_spec(None))
        mine = activity.visible_change(rules.inventory_rows(change, spec), "all", PROFILES, me="matt")
        self.assertEqual(mine["rows"], imported["rows"])
        # ... and the same headline: the copies past the cap counted the same way in SQL.
        self.assertEqual(mine["headline"], imported["headline"])
        self.assertNotIn("at least", imported["headline"])


# ------------------------------------------------------------------ dbstatus

class StatusTests(unittest.TestCase):
    def snapshot(self, **changes):
        out = {"ok": True, "usable": True, "error": None, "detail": None, "pending_migrations": 0,
               "last_backup": None, "backup_stale": None, "stale_hours": 36.0,
               "inventory": {"tables": True, "revision": "7", "imported_at": "2026-10-12T09:00:00+10:00"}}
        out.update(changes)
        return out

    def test_imported_and_staleness(self):
        self.assertEqual(dbstatus.inventory_view(self.snapshot()),
                         {"imported": True, "revision": "7", "imported_at": "2026-10-12T09:00:00+10:00",
                          "stale": False, "not_imported": False})
        down = dbstatus.inventory_view(self.snapshot(ok=False, usable=False, error=dbstatus.NOT_REACHABLE,
                                                     inventory=None))
        self.assertEqual((down["stale"], down["imported"]), (True, None))
        empty = dbstatus.inventory_view(self.snapshot(inventory={"tables": True, "revision": None,
                                                                 "imported_at": None}))
        self.assertEqual((empty["stale"], empty["not_imported"]), (False, True))
        unmigrated = dbstatus.inventory_view(self.snapshot(ok=False, error=dbstatus.MIGRATIONS_PENDING, inventory={
            "tables": False, "revision": None, "imported_at": None}))
        self.assertEqual((unmigrated["stale"], unmigrated["not_imported"]), (True, False))
        with mock.patch.object(dbstatus, "_snapshot", self.snapshot()):
            self.assertNotIn("inventory", dbstatus.view({"id": "user1", "role": "member"}))
            self.assertIn("inventory", dbstatus.view({"id": "matt", "role": "admin"}))


if __name__ == "__main__":
    unittest.main()
