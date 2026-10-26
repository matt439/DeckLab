"""Shared progress contract on memory and disposable PostgreSQL, never household data."""
import concurrent.futures
from datetime import datetime, timedelta
import hashlib
import unittest

from decklab.lib import state
from decklab.lib.state.memory import MemoryStore
from decklab.tests import db_support

MATT = state.Actor("matt", "Matt", "home")
USER1 = state.Actor("user1", "User1", "tunnel")
TASKS = [hashlib.sha256(f"task-{i}".encode()).hexdigest() for i in range(16)]


class PackingContract:
    def test_activity_waits_for_batch_commit_even_when_own_tick_is_visible(self):
        a = TASKS[0]
        with self.store.batch(MATT, "Packing transaction"):
            self.store.packing_ticks_put({a: True}, MATT, "Tick")
            self.assertEqual(self.store.packing_ticks([a]), [a])
            self.assertIsNone(self.store.packing_activity([a]))
        saved = self.store.packing_activity([a])
        self.assertEqual(saved["actor"], "matt")
        with self.store.batch(USER1, "Clear packing transaction"):
            self.store.packing_ticks_put({a: False}, USER1, "Untick")
            self.assertEqual(self.store.packing_activity([a]), saved)
        self.assertEqual(self.store.packing_activity([a])["actor"], "user1")

    def test_recorded_activity_is_scoped_and_returns_no_private_rows_or_prose(self):
        a, b, private = TASKS[:3]
        self.assertIsNone(self.store.packing_activity([]))
        self.assertIsNone(self.store.packing_activity([a, b]))
        self.store.packing_ticks_put({a: True, private: True}, MATT, "Private fixture detail")
        change = self.store.activity()["changes"][0]
        expected = {"actor": "matt", "at": change["at"], "checks": 1}
        self.assertEqual(self.store.packing_activity([a, b]), expected)
        self.assertEqual(self.store.packing_activity([a, a]), expected)
        self.assertEqual(self.store.packing_activity([a, private]), dict(expected, checks=2))
        self.assertEqual(datetime.fromisoformat(expected["at"]).utcoffset(), timedelta(0))
        self.store.packing_ticks_put({private: False}, USER1, "Private fixture cleared")
        self.assertEqual(self.store.packing_activity([a]), expected)
        self.assertEqual(self.store.packing_activity([private])["actor"], "user1")

    def test_activity_reads_noops_and_unrelated_writes_do_not_create_a_heartbeat(self):
        a, b = TASKS[:2]
        self.store.packing_ticks_put({a: True}, MATT, "Pull a card")
        expected = self.store.packing_activity([a, b])
        before = self.store.activity()
        self.assertEqual(self.store.packing_activity([a, b]), expected)
        self.assertEqual(self.store.activity(), before)
        self.store.packing_ticks_put({a: True, b: False}, USER1, "Already as recorded")
        self.assertEqual(self.store.activity(), before)
        self.store.settings_put("user1", {"theme": "dark"}, USER1, "Unrelated setting")
        self.assertEqual(self.store.packing_activity([a, b]), expected)
        self.assertIsNone(self.store.packing_activity([TASKS[4]]))

    def test_activity_includes_unticks_even_after_all_checks_are_cleared(self):
        a, b = TASKS[:2]
        self.store.packing_ticks_put({a: True, b: True}, MATT, "Pull cards")
        self.store.packing_ticks_put({a: False, b: False}, USER1, "Clear cards")
        change = self.store.activity()["changes"][0]
        self.assertEqual(self.store.packing_ticks([a, b]), [])
        self.assertEqual(self.store.packing_activity([a, b]),
                         {"actor": "user1", "at": change["at"], "checks": 2})
        self.assertEqual(self.store.packing_activity([a])["checks"], 1)

    def test_activity_counts_only_matching_rows_of_a_mixed_batch_and_rolls_back(self):
        a, b, private = TASKS[:3]
        with self.store.batch(USER1, "Mixed packing batch"):
            self.store.packing_ticks_put({a: True, private: True}, MATT, "Pull")
            self.store.settings_put("matt", {"theme": "dark"}, MATT, "Unrelated setting")
        expected = self.store.packing_activity([a, b])
        self.assertEqual(expected["actor"], "user1")
        self.assertEqual(expected["checks"], 1)
        before = self.store.activity()
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with self.store.batch(MATT, "Interrupted packing"):
                self.store.packing_ticks_put({a: False, b: True}, MATT, "Change checks")
                raise RuntimeError("rollback")
        self.assertEqual(self.store.activity(), before)
        self.assertEqual(self.store.packing_activity([a, b]), expected)
        self.assertEqual(self.store.packing_ticks([a, b]), [a])

    def test_activity_scope_validation_precedes_reading(self):
        for ids in (None, "bad", {}, ["not-a-hash"], [TASKS[0]] * 2001):
            with self.subTest(ids=ids), self.assertRaises(state.Invalid):
                self.store.packing_activity(ids)
        self.assertIsNone(self.store.packing_activity((TASKS[0],)))
        self.assertEqual(self.store.activity()["changes"], [])

    def test_patches_are_shared_scoped_and_idempotent(self):
        a, b, private = TASKS[:3]
        self.assertEqual(self.store.packing_ticks([a, b]), [])
        self.store.packing_ticks_put({a: True, private: True}, MATT, "Pull cards")
        # User1 started with an empty view; her patch keeps Matt's independent tick.
        self.assertEqual(self.store.packing_ticks_put({b: True}, USER1, "Pack box", ids=[b, a]), sorted([a, b]))
        self.assertEqual(self.store.packing_ticks([a]), [a])
        before = self.store.activity()
        self.store.packing_ticks_put({a: True}, MATT, "Already pulled")
        self.assertEqual(self.store.activity(), before)
        # Clear exactly this view; a hidden task and tasks in other selections survive.
        self.assertEqual(self.store.packing_ticks_put({a: False}, USER1, "Clear ticks", ids=[a, b]), [b])
        self.assertEqual(self.store.packing_ticks([private]), [private])
        # Adding/removing decks changes scope, not a surviving task's identity.
        self.assertEqual(self.store.packing_ticks([b, TASKS[3]]), [b])

    def test_concurrent_independent_tasks_are_not_lost(self):
        def tick(task):
            self.store.packing_ticks_put({task: True}, MATT, "Pull a card")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(tick, TASKS[:8]))
        self.assertEqual(self.store.packing_ticks(TASKS), sorted(TASKS[:8]))

    def test_batch_rolls_packing_progress_back_with_other_state(self):
        with self.assertRaisesRegex(RuntimeError, "undo"):
            with self.store.batch(MATT, "Interrupted packing"):
                self.store.packing_ticks_put({TASKS[0]: True}, MATT, "Tick")
                self.store.settings_put("matt", {"theme": "dark"}, MATT, "Settings")
                raise RuntimeError("undo")
        self.assertEqual(self.store.packing_ticks(TASKS), [])
        self.assertEqual(self.store.settings("matt"), {})
        self.assertEqual(self.store.activity()["changes"], [])
        self.assertIsNone(self.store.packing_activity(TASKS))

    def test_bad_patches_never_change_progress(self):
        for patch in ({"not-a-hash": True}, {TASKS[0]: 1}, {TASKS[0]: None}, []):
            with self.subTest(patch=patch), self.assertRaises(state.Invalid):
                self.store.packing_ticks_put(patch, MATT, "Bad patch")
        with self.assertRaises(state.Invalid):
            self.store.packing_ticks_put({TASKS[0]: True}, MATT, "Outside scope", ids=[TASKS[1]])
        with self.assertRaises(state.Invalid):
            self.store.packing_ticks([TASKS[0]] * 2001)
        self.assertEqual(self.store.packing_ticks(TASKS), [])
        self.assertEqual(self.store.activity()["changes"], [])

    def test_audit_has_only_hashes_and_one_change_set_for_a_patch(self):
        self.store.packing_ticks_put(dict.fromkeys(TASKS[:2], True), USER1, "Update packing ticks")
        change, = self.store.activity()["changes"]
        self.assertEqual((change["actor"], change["via"]), ("user1", "tunnel"))
        self.assertEqual([row["table"] for row in change["rows"]], ["packing_tick"] * 2)
        self.assertEqual([row["after"] for row in change["rows"]], [{"id": k} for k in sorted(TASKS[:2])])


class MemoryPackingTests(PackingContract, unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()

    def test_unavailable_does_not_change_ticks(self):
        self.store.down = True
        with self.assertRaises(state.Unavailable):
            self.store.packing_ticks(TASKS)
        with self.assertRaises(state.Unavailable):
            self.store.packing_activity(TASKS)
        self.assertIsNone(self.store.packing_activity([]))
        with self.assertRaises(state.Unavailable):
            self.store.packing_ticks_put({TASKS[0]: True}, MATT, "Tick")
        self.store.down = False
        self.assertEqual(self.store.packing_ticks(TASKS), [])


class PgPackingTests(PackingContract, db_support.DbTestCase):
    def setUp(self):
        from decklab.lib.state.pg import PgStore
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname)
        self.store = PgStore(dbname=self.dbname)

    def test_activity_follows_packing_write_order_not_change_set_creation_order(self):
        from decklab.lib.state.pg import PgStore
        other = PgStore(dbname=self.dbname)
        task = TASKS[0]
        # This transaction allocates its audit change set first, but takes the packing lock last.
        with self.store.batch(MATT, "Started first, packed last"):
            other.packing_ticks_put({task: True}, USER1, "Packed first")
            self.store.packing_ticks_put({task: False}, MATT, "Cleared last")
        self.assertEqual(self.store.packing_ticks([task]), [])
        self.assertEqual(self.store.packing_activity([task])["actor"], "matt")
        self.assertEqual(self.store.packing_activity([task])["checks"], 1)

    def test_schema_guards_and_privileges_cover_the_new_table(self):
        import psycopg
        from decklab.db import conn
        with conn.connect("app", dbname=self.dbname, autocommit=True) as c:
            with self.assertRaisesRegex(psycopg.Error, "every write needs a change set"):
                c.execute("insert into packing_tick (id) values (%s)", (TASKS[0],))
        with conn.connect("ro", dbname=self.dbname, autocommit=True) as c:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                c.execute("insert into packing_tick (id) values (%s)", (TASKS[0],))
        with conn.connect("owner", dbname=self.dbname, autocommit=True) as c:
            with self.assertRaisesRegex(psycopg.Error, "truncate isn't audited"):
                c.execute("truncate packing_tick")
            with self.assertRaises(psycopg.errors.CheckViolation):
                with conn.change("test", "test", "Invalid task hash", conn=c) as (cur, _):
                    cur.execute("insert into packing_tick (id) values ('private box label')")

    def test_progress_survives_a_new_store_and_is_exported_and_backed_up(self):
        from decklab.db import backup, conn, export
        from decklab.lib.state.pg import PgStore
        self.store.packing_ticks_put({TASKS[0]: True}, MATT, "Tick")
        self.assertEqual(PgStore(dbname=self.dbname).packing_ticks(TASKS), [TASKS[0]])
        self.assertIn(("public.packing_tick", ("id",)), export.TABLES)
        with conn.connect("ro", dbname=self.dbname, autocommit=True) as c:
            self.assertEqual(export.table_csv(c, "public.packing_tick", ("id",)), f"id\n{TASKS[0]}\n".encode())
            self.assertEqual(backup.count_rows(c)["public.packing_tick"], 1)
            self.assertIn("public.packing_tick", backup.digest_rows(c))


if __name__ == "__main__":
    unittest.main()
