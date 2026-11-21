"""Shared contract for the memory and disposable PostgreSQL checklist stores."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from decklab.db import conn as db, migrate
from decklab.lib.state import Conflict, Invalid, Unavailable
from decklab.lib.state import memory, pg, upgrade_checklist
from decklab.tests import db_support


DECK = "casual/linked-checklist"
OTHER_DECK = "commander/other-checklist"
RENAMED = "casual/renamed-checklist"


class ChecklistContract:
    def test_copies_round_trip_in_order_and_remain_private_to_the_owner(self):
        rows = [{"name": "Arcane Signet", "choice": choice} for choice in ("set_aside", "check", "buy")]
        saved = self.store.checklist_put("user2", " My deck ", rows, 0)
        self.assertEqual(saved, {"revision": 1, "title": "My deck", "rows": rows})
        saved["rows"].pop()
        rows[0]["name"] = "Changed locally"
        after = self.store.checklist("user2")
        self.assertEqual(len(after["rows"]), 3)
        self.assertEqual(after["rows"][0], {"name": "Arcane Signet", "choice": "set_aside"})
        self.assertEqual(self.store.checklist("user1"), upgrade_checklist.empty())
        self.assertEqual(self.store.checklist_put("user2", after["title"], after["rows"], 1), after)

    def test_linked_checklists_scope_by_profile_and_deck_independently_of_the_standalone_list(self):
        saved = self.store.checklist_put("matt", "Linked", [], 0, deck_id=DECK)
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(self.store.checklist("matt", deck_id=DECK), saved)
        for profile, deck in (("matt", OTHER_DECK), ("user1", DECK), ("matt", None)):
            with self.subTest(profile=profile, deck=deck):
                self.assertEqual(self.store.checklist(profile, deck_id=deck), upgrade_checklist.empty())
                self.assertEqual(self.store.checklist_put(profile, "Separate", [], 0, deck_id=deck)["revision"], 1)
        self.assertEqual(self.store.checklist("matt", deck_id=DECK), saved)

    def _simultaneous_changes(self, profile, deck_id=None):
        start = threading.Barrier(2)

        def save(title):
            start.wait(timeout=5)
            try:
                return self.store.checklist_put(profile, title, [], 0, deck_id=deck_id)
            except Conflict:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(save, ["First", "Second"]))
        saved, = [result for result in outcomes if result is not None]
        self.assertIn(saved["title"], ["First", "Second"])
        self.assertEqual(self.store.checklist(profile, deck_id=deck_id), saved)
        self.assertEqual(self.store.checklist_put(profile, "", [], 1, deck_id=deck_id),
                         {"revision": 2, "title": "", "rows": []})
        with self.assertRaises(Conflict):
            self.store.checklist_put(profile, "A stale copy", [], 0, deck_id=deck_id)

    def test_two_simultaneous_changes_do_not_lose_an_update(self):
        self._simultaneous_changes("user2")

    def test_two_simultaneous_linked_changes_do_not_lose_an_update(self):
        self._simultaneous_changes("matt", DECK)


class MemoryChecklistTests(ChecklistContract, unittest.TestCase):
    def setUp(self):
        self.store = memory.MemoryStore()

    def test_invalid_input_preserves_prior_content(self):
        row = {"name": "Valid", "choice": "buy"}
        first = self.store.checklist_put("user1", "", [row], 0)
        for title, rows, revision in (
            ("", [row] * 201, 1), ("", [{**row, "other": 3}], 1), ("", [{"name": "X"}], 1),
            ("", [{**row, "name": "  "}], 1), ("", [{**row, "name": "\ud800"}], 1),
            ("", [{**row, "name": "X\u2029Y"}], 1), ("", [{**row, "choice": []}], 1),
            ("X" * 151, [], 1), ("Bad\nTitle", [], 1), ("", [], True), ("", [], 2 ** 53),
        ):
            with self.subTest(title=title, rows=len(rows), revision=revision), self.assertRaises(Invalid):
                self.store.checklist_put("user1", title, rows, revision)
        self.assertEqual(self.store.checklist("user1"), first)


class DatabaseChecklistTests(ChecklistContract, db_support.DbTestCase):
    def setUp(self):
        db_support.reset(self.dbname)
        with self.connect("owner") as c:
            with db.change("test", "test", "Saved decks for checklist tests", conn=c) as (cur, _):
                for deck_id in (DECK, OTHER_DECK):
                    kind, slug = deck_id.split("/")
                    cur.execute("insert into deck (id, space_id, kind, slug, revision) "
                                "values (%s, 'home', %s, %s, 1) on conflict do nothing", (deck_id, kind, slug))
        db_support.seed_membership(self.dbname)
        self.store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())

    def test_profile_admission_and_no_card_or_title_in_activity(self):
        with self.assertRaises(Invalid):
            self.store.checklist_put("missing-profile", "My list", [], 0)
        rows = [{"name": "Plains", "choice": "buy"}]
        self.store.checklist_put("user1", "My list", rows, 0)
        self.store.checklist_put("user1", "Linked list", rows, 0, deck_id=DECK)
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select revision from public.deck_upgrade_checklist").fetchall(), [(1,)])
            self.assertFalse(c.execute(
                "select has_table_privilege('public.deck_upgrade_checklist', 'insert')").fetchone()[0])
            self.assertEqual(c.execute("select count(*) from audit.row_change").fetchone(), (0,))
            self.assertEqual(c.execute("select count(*) from audit.change_set").fetchone(), (0,))

    def test_rename_carries_the_list_delete_clears_it_and_other_spaces_cannot_write(self):
        with self.assertRaises(Conflict):
            self.store.checklist_put("user2", "Another space", [], 0, deck_id=DECK)
        saved = self.store.checklist_put("user1", "Working choice", [], 0, deck_id=DECK)
        with self.connect("owner") as c:
            with db.change("test", "test", "Rename deck fixture", conn=c) as (cur, _):
                cur.execute("update deck set id = %s, slug = %s where id = %s", (RENAMED, RENAMED.split("/")[1], DECK))
        self.assertEqual(self.store.checklist("user1", deck_id=RENAMED), saved)
        with self.assertRaises(Conflict):
            self.store.checklist_put("user1", "Stale after rename", [], saved["revision"], deck_id=DECK)
        with self.connect("owner") as c:
            with db.change("test", "test", "Delete deck fixture", conn=c) as (cur, _):
                cur.execute("delete from deck where id = %s", (RENAMED,))
        self.assertEqual(self.store.checklist("user1", deck_id=RENAMED), upgrade_checklist.empty())
        with self.assertRaises(Conflict):
            self.store.checklist_put("user1", "Stale after delete", [], 1, deck_id=RENAMED)
        self.assertTrue(self.store.reachable())

    def test_before_linked_migration_only_standalone_is_available(self):
        with self.connect("owner") as c:
            db_support.roll_back_schema(c, 29)
        self.addCleanup(migrate.apply, dbname=self.dbname)
        self.assertEqual(self.store.checklist_put("user1", "Still works", [], 0)["revision"], 1)
        for action in (lambda: self.store.checklist("user1", deck_id=DECK),
                       lambda: self.store.checklist_put("user1", "Linked", [], 0, deck_id=DECK)):
            with self.assertRaises(upgrade_checklist.MissingSchema):
                action()
            self.assertTrue(self.store.reachable())

    def test_before_migration_checklist_unavailable_without_tripping_shared_breaker(self):
        with self.connect("owner") as c:
            db_support.roll_back_schema(c, 28)
        self.addCleanup(migrate.apply, dbname=self.dbname)
        for action in (lambda: self.store.checklist("user1"), lambda: self.store.checklist_put("user1", "", [], 0)):
            with self.assertRaises(Unavailable):
                action()
            self.assertTrue(self.store.reachable())
