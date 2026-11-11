"""Actual PgInventory.apply control flow with fake SQL transport, never a database connection."""
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import changes, model, paths, rules, undo_token_delete
from decklab.tests import test_inventory_undo_token_restore as hooks

REAL_CHANGED = changes.changed
REAL_CHANGED_PATHS = changes.changed_paths


class ChangedSummaryTests(unittest.TestCase):
    def setUp(self):
        self.case = hooks.PgApplyHookTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.store, self.pg = self.case.store, self.case.pg
        self.before = model.Inventory("1", backend="db")
        self.saved = self.before.replace(revision="2")
        self.enterContext(mock.patch.object(self.store, "_join", side_effect=lambda inv, *_: self.before if inv is self.case.stored else self.saved))
        self.enterContext(mock.patch.object(self.store, "load", side_effect=lambda: self.before))
        # The candidate is the harness's opaque 'after'. Only the post-SQL saved
        # snapshot is rendered; deliberately claimed/candidate paths have no authority.
        self.enterContext(mock.patch.object(self.pg.changes, "changed_paths", side_effect=lambda old, new:
            REAL_CHANGED_PATHS(old, new) if new is self.saved else []))

    def diff(self, wanted):
        self.enterContext(mock.patch.object(self.pg.changes, "changed_paths", side_effect=lambda old, new:
            list(wanted) if new is self.saved else []))

    def test_real_success_replaces_false_hints_with_post_sql_paths_and_preserves_other_summary_fields(self):
        self.diff([paths.tokens("home")])
        original = inventory.Summary("Keep the text", {"added_rows": 2}, {"private-false-path": ["claimed"]}, {"keep": "extra"})
        saved, summary = self.case.run_op(original)
        self.assertIs(saved, self.saved)
        self.assertEqual(summary.changed, {paths.tokens("home"): ["changed"]})
        self.assertEqual(summary.text, original.text)
        self.assertIs(summary.counts, original.counts)
        self.assertIs(summary.extra, original.extra)

    def test_unclaimed_token_write_is_derived_from_real_readback_sources(self):
        row = {**dict.fromkeys(rules.TOKEN_FIELDS, ""), "front": "Treasure", "quantity": "2", "notes": "single-sided verified"}
        self.saved = self.before.with_tokens("home", [model.TokenRow.make(row, id=900)]).replace(revision="2")
        _, summary = self.case.run_op(inventory.Summary("Added two physical cards", {"cards": 2}))
        self.assertEqual(summary.changed, {paths.tokens("home"): ["changed"]})

    def test_import_only_sql_commit_has_a_changed_path_even_when_no_file_source_changes(self):
        self.saved = self.before.replace(revision="2", imports={"user2": (model.ImportInfo("only.csv", 6, "a" * 64),)})
        self.assertEqual(REAL_CHANGED(self.before, self.saved), [])
        self.enterContext(mock.patch.object(self.pg, "_diff", return_value=0))
        self.enterContext(mock.patch.object(self.pg, "_add_imports", return_value=1))
        original = inventory.Summary("Keep raw import", {"cards": 0}, extra={"imports": [("user2", "only.csv", b"a,b\n1\n")]})
        _, summary = self.case.run_op(original)
        self.assertEqual(summary.changed, {str(paths.imports_dir("user2")) + "/only.csv": ["changed"]})
        self.assertIs(summary.extra, original.extra)

    def test_claimed_noop_clears_changed_and_never_acknowledges_a_request_write(self):
        original = inventory.Summary("Keep noop text", {"count": 9}, {paths.tokens("home"): ["claimed"]}, {"keep": "noop"})
        self.enterContext(mock.patch.object(self.pg, "_diff", return_value=0))
        self.addCleanup(inventory.use(self.store))
        operation = type("Noop", (), {"kind": "fixture", "run": lambda _, snapshot: ("after", original)})()
        with inventory.pinned():
            self.assertIs(inventory.current(), self.before)
            saved, summary = inventory.apply(operation, inventory.Actor("test", "Fixture"), "Synthetic claimed no-op")
            self.assertIs(saved, self.before)
            self.assertEqual(summary.changed, {})
            self.assertFalse(inventory.pinned_write())
            self.assertIsNone(inventory.pinned_committed_snapshot())
        self.assertEqual((summary.text, summary.counts, summary.extra), (original.text, original.counts, original.extra))
        self.case.cur.execute.assert_not_called()
        self.assertIsNone(self.store._cache)

    def test_nested_real_write_acknowledges_the_sql_readback_not_the_explicit_preview(self):
        self.diff([paths.dice("home")])
        self.addCleanup(inventory.use(self.store))
        operation = type("Write", (), {"kind": "fixture", "run": lambda _, snapshot: ("after", inventory.Summary("Written"))})()
        with inventory.pinned():
            self.assertIs(inventory.current(), self.before)
            with inventory.pinned("explicit preview"):
                saved, summary = inventory.apply(operation, inventory.Actor("test", "Fixture"), "Synthetic SQL write")
                self.assertTrue(summary.changed)
                self.assertTrue(inventory.pinned_write())
                self.assertIs(inventory.pinned_committed_snapshot(), self.saved)
            self.assertIs(saved, self.saved)
            self.assertIs(inventory.current(), self.saved)
            self.assertIs(inventory.pinned_committed_snapshot(), self.saved)

    def test_failed_precommit_proof_never_materializes_changed_or_publishes_a_pin_or_cache(self):
        called = []
        self.enterContext(mock.patch.object(self.pg.changes, "changed_paths", side_effect=lambda old, new: called.append(new) or []))
        self.enterContext(mock.patch.object(undo_token_delete, "confirm_in_transaction", side_effect=inventory.Conflict("Synthetic proof refusal")))
        self.addCleanup(inventory.use(self.store))
        original = self.case.restore_summary()
        operation = type("Write", (), {"kind": "fixture", "run": lambda _, snapshot: ("after", original)})()
        with inventory.pinned():
            self.assertIs(inventory.current(), self.before)
            with self.assertRaises(inventory.Conflict):
                inventory.apply(operation, inventory.Actor("test", "Fixture"), "Refuse synthetic SQL proof")
            self.assertFalse(inventory.pinned_write())
            self.assertIsNone(inventory.pinned_committed_snapshot())
            self.assertIs(inventory.current(), self.before)
        self.assertNotIn(self.saved, called)
        self.assertIsNone(self.store._cache)
