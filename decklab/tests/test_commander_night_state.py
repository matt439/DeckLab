"""Household Commander notes on memory and disposable PostgreSQL; never live venue data."""
import concurrent.futures
import copy
import unittest
from datetime import date

from decklab.lib import state
from decklab.lib.state import commander_night as notes
from decklab.lib.state.memory import MemoryStore
from decklab.tests import db_support

MATT = state.Actor("matt", "Matt", "home")
NIGHT = {"name": "Fixture Commander night", "venue": "Fixture shop", "target_bracket": 2,
         "published_min": 1, "published_max": 4, "house_rules": "Ask the table first.\nNotes only.",
         "checked_on": "2026-10-13"}


class NotesValidationTests(unittest.TestCase):
    def test_unknown_facts_remain_unknown_and_text_is_plain(self):
        self.assertEqual(notes.normalize({"name": " Evening <fixture> "}),
                         {"name": "Evening <fixture>", "venue": "", "target_bracket": None,
                          "published_min": None, "published_max": None, "house_rules": "", "checked_on": ""})
        self.assertIsNone(notes.normalize(None))

    def test_brackets_are_explicit_whole_numbers_and_ranges_are_complete(self):
        for fields in ({"target_bracket": True}, {"target_bracket": "2"}, {"target_bracket": 0},
                       {"published_min": 1}, {"published_max": 4},
                       {"published_min": 4, "published_max": 2},
                       {"published_min": 1, "published_max": 6}):
            with self.subTest(fields=fields), self.assertRaises(state.Invalid):
                notes.normalize({"name": "Fixture", **fields})
        for bracket in range(1, 6):
            self.assertEqual(notes.normalize({"name": "Fixture", "target_bracket": bracket})["target_bracket"], bracket)

    def test_checked_date_is_calendar_checked_and_future_check_is_opt_in(self):
        for checked in ("2026-02-29", "2026-1-01", "20261013", "yesterday", "0000-01-01"):
            with self.subTest(checked=checked), self.assertRaises(state.Invalid):
                notes.normalize({**NIGHT, "checked_on": checked})
        self.assertEqual(notes.normalize({**NIGHT, "checked_on": "2028-02-29"})["checked_on"], "2028-02-29")
        with self.assertRaisesRegex(state.Invalid, "future"):
            notes.normalize(NIGHT, today=date(2026, 10, 12))
        self.assertEqual(notes.normalize(NIGHT, today=date(2026, 10, 13)), NIGHT)

    def test_shapes_limits_controls_and_expected_revisions_are_checked(self):
        for value in ([], "Fixture", {}, {"name": " "}, {**NIGHT, "unknown": 2},
                      {**NIGHT, "name": "x" * 121}, {**NIGHT, "venue": "x" * 121},
                      {**NIGHT, "house_rules": "x" * 1501}, {**NIGHT, "house_rules": "x\0"},
                      {**NIGHT, "venue": "x\nY"}, {**NIGHT, "checked_on": None}):
            with self.subTest(value=repr(value)[:100]), self.assertRaises(state.Invalid):
                notes.normalize(value)
        for value in (None, -1, "1", True, 1.0):
            with self.subTest(value=value), self.assertRaises(state.Invalid):
                notes.expectation(value)
        for value in (None, "", " ", "x" * 501, "x\0"):
            with self.subTest(reason=repr(value)[:50]), self.assertRaises(state.Invalid):
                notes.clear_reason(value)


class CommanderNightContract:
    def save(self, night=NIGHT, expect=0, **kwargs):
        return self.store.commander_night_put(night, expect, MATT, "Save fixture Commander notes", **kwargs)

    def test_a_new_store_has_no_seeded_night_or_audit(self):
        self.assertEqual(self.store.commander_night(), {"night": None, "revision": 0})
        self.assertEqual(self.store.activity()["changes"], [])

    def test_whole_notes_are_saved_as_one_audited_change_and_copies_are_detached(self):
        supplied = copy.deepcopy(NIGHT)
        saved = self.save(supplied)
        supplied["house_rules"] = "Changed outside the store"
        saved["night"]["name"] = "Changed returned copy"
        self.assertEqual(self.store.commander_night(), {"night": NIGHT, "revision": 1})
        change, = self.store.activity()["changes"]
        self.assertEqual((change["actor"], change["via"]), ("matt", "home"))
        row, = change["rows"]
        self.assertEqual((row["table"], row["op"], row["key"]), ("commander_night", "INSERT", {"id": True}))
        self.assertEqual(row["after"], {"id": True, "revision": 1, "content": NIGHT})

    def test_noop_saves_are_quiet_but_stale_identical_content_is_refused(self):
        saved = self.save()
        before = self.store.activity()
        self.assertEqual(self.save(expect=1), saved)
        self.assertEqual(self.store.activity(), before)
        with self.assertRaisesRegex(state.Conflict, "changed"):
            self.save(expect=0)
        self.assertEqual(self.store.activity(), before)

    def test_clear_keeps_revision_and_reason_and_recreate_rejects_stale_editor(self):
        self.save()
        cleared = self.save(None, 1, reason="Fixture event retired")
        self.assertEqual(cleared, {"night": None, "revision": 2})
        change = self.store.activity()["changes"][0]
        self.assertEqual(change["reason"], "Fixture event retired")
        self.assertEqual(change["rows"][0]["op"], "UPDATE")
        self.assertEqual(change["rows"][0]["after"], {"id": True, "revision": 2, "content": None})
        self.assertEqual(self.save(expect=2), {"night": NIGHT, "revision": 3})
        with self.assertRaises(state.Conflict):
            self.save({**NIGHT, "venue": "Stale edit"}, 1)
        self.assertEqual(self.store.commander_night(), {"night": NIGHT, "revision": 3})

    def test_clear_noop_and_validation_never_add_empty_audit_sets(self):
        self.assertEqual(self.save(None, 0, reason="No fixture saved"), {"night": None, "revision": 0})
        for kwargs in ({"night": None}, {"night": {"name": ""}}, {"expect": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(state.Invalid):
                self.save(**kwargs)
        self.assertEqual(self.store.activity()["changes"], [])

    def test_simultaneous_edits_have_one_winner_and_one_conflict(self):
        self.save()
        def edit(name):
            try:
                self.save({**NIGHT, "name": name}, 1)
                return "saved"
            except state.Conflict:
                return "conflict"
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(edit, ("First fixture", "Second fixture")))
        self.assertCountEqual(results, ["saved", "conflict"])
        self.assertEqual(self.store.commander_night()["revision"], 2)
        self.assertEqual(len(self.store.activity()["changes"]), 2)

    def test_batch_rolls_notes_back_with_other_state(self):
        with self.assertRaisesRegex(RuntimeError, "undo"):
            with self.store.batch(MATT, "Interrupted fixture edit"):
                self.save()
                self.store.settings_put("matt", {"theme": "dark"}, MATT, "Settings")
                raise RuntimeError("undo")
        self.assertEqual(self.store.commander_night(), {"night": None, "revision": 0})
        self.assertEqual(self.store.settings("matt"), {})
        self.assertEqual(self.store.activity()["changes"], [])


class MemoryCommanderNightTests(CommanderNightContract, unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()

    def test_unavailable_does_not_change_saved_notes(self):
        self.save()
        self.store.down = True
        with self.assertRaises(state.Unavailable):
            self.store.commander_night()
        with self.assertRaises(state.Unavailable):
            self.save({**NIGHT, "venue": "Other fixture"}, 1)
        self.store.down = False
        self.assertEqual(self.store.commander_night(), {"night": NIGHT, "revision": 1})


class PgCommanderNightTests(CommanderNightContract, db_support.DbTestCase):
    def setUp(self):
        from decklab.lib.state.pg import PgStore
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname)
        self.store = PgStore(dbname=self.dbname)

    def test_a_separate_store_sees_the_latest_edit_without_cache_delay(self):
        from decklab.lib.state.pg import PgStore
        other = PgStore(dbname=self.dbname)
        self.assertEqual(other.commander_night(), {"night": None, "revision": 0})
        self.save()
        self.assertEqual(other.commander_night(), {"night": NIGHT, "revision": 1})
        other.commander_night_put(None, 1, MATT, "Clear fixture", reason="Fixture retired")
        self.assertEqual(self.store.commander_night(), {"night": None, "revision": 2})


if __name__ == "__main__":
    unittest.main()
