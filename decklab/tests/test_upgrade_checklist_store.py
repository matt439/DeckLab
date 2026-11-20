"""Shared contract for the memory and disposable PostgreSQL checklist stores."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from decklab.lib.state import Conflict, Invalid, Unavailable
from decklab.lib.state import memory, pg, upgrade_checklist
from decklab.tests import db_support


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

    def test_two_simultaneous_changes_do_not_lose_an_update(self):
        start = threading.Barrier(2)

        def save(title):
            start.wait(timeout=5)
            try:
                return self.store.checklist_put("user2", title, [], 0)
            except Conflict:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(save, ["First", "Second"]))
        saved, = [result for result in outcomes if result is not None]
        self.assertIn(saved["title"], ["First", "Second"])
        self.assertEqual(self.store.checklist("user2"), saved)
        self.assertEqual(self.store.checklist_put("user2", "", [], 1), {"revision": 2, "title": "", "rows": []})
        with self.assertRaises(Conflict):
            self.store.checklist_put("user2", "A stale copy", [], 0)


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
        db_support.seed_membership(self.dbname)
        self.store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())

    def test_profile_admission_and_no_card_or_title_in_activity(self):
        with self.assertRaises(Invalid):
            self.store.checklist_put("missing-profile", "My list", [], 0)
        self.store.checklist_put("user1", "My list", [{"name": "Plains", "choice": "buy"}], 0)
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select count(*) from audit.row_change").fetchone(), (0,))
            self.assertEqual(c.execute("select count(*) from audit.change_set").fetchone(), (0,))

    def test_before_migration_checklist_unavailable_without_tripping_shared_breaker(self):
        from decklab.db import migrate
        with self.connect("owner") as c:
            db_support.roll_back_schema(c, 28)
        self.addCleanup(migrate.apply, dbname=self.dbname)
        for action in (lambda: self.store.checklist("user1"), lambda: self.store.checklist_put("user1", "", [], 0)):
            with self.assertRaises(Unavailable):
                action()
            self.assertTrue(self.store.reachable())
