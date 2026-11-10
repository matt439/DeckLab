"""Nullable numeric target/legacy audit parity and fresh reviewed target Undo context."""
import copy
from unittest import mock

from decklab.lib import inventory, shop_reference_source
from decklab.lib.inventory import undo_queue_schema
from decklab.tests import test_inventory_undo_watchlist as fixture
from decklab.tests import test_activity_undo_api as source_fixture


class QueueTargetUndoTests(fixture.WatchlistUndoFixture):
    def target_pair(self):
        current, recorded = fixture.pairs(1)[0]
        return ({**current, "buy_under_aud": "1.25"}, {**recorded, "buy_under_aud": "2.50"})

    def test_legacy_audit_images_restore_with_current_nullable_column_without_any_market_read(self):
        original = copy.deepcopy(self.store.audit[source_fixture.CHANGE_ID])
        for row in self.store.audit[source_fixture.CHANGE_ID]:
            row["before"].pop("buy_under_aud")
            row["after"].pop("buy_under_aud")
        with mock.patch.object(shop_reference_source, "context", side_effect=AssertionError("Unchanged target needs no source")):
            plan = self.review()
            self.run_undo(plan["expect"])
        self.assertEqual(len(self.store.writes), 1)
        self.assertTrue(all(row.buy_under_aud == "" for row in self.store.snapshot.watchlist.rows))
        self.assertTrue(undo_queue_schema.same(original[0]["before"], {key: value for key, value in original[0]["before"].items() if key != "buy_under_aud"}))

    def test_target_restore_binds_fresh_current_policy_and_source_then_restores_canonical_cents(self):
        self.seed([self.target_pair()])
        source = {"preference": None, "data": {}, "adapters": {}}
        with mock.patch.object(shop_reference_source, "context", side_effect=lambda **kwargs: source):
            shown = self.review()
            self.assertIn("buy_under_aud", [field["field"] for field in shown["rows"][0]["fields"]])
            before = self.store.snapshot
            source["preference"] = {"minimum_condition": "NM", "english_only": True}
            with self.assertRaises(inventory.Conflict):
                self.run_undo(shown["expect"])
            self.assertEqual(self.store.snapshot, before)
            source["preference"] = None
            self.run_undo(shown["expect"])
        self.assertEqual(self.store.snapshot.watchlist.rows[-1].buy_under_aud, "2.50")
        self.assertEqual(len(self.store.writes), 1)

    def test_malformed_numeric_audit_targets_refuse_before_writes_without_quoting_the_value(self):
        for value in ("2.50", True, float("nan"), 1.005):
            self.seed([self.target_pair()])
            self.store.audit[source_fixture.CHANGE_ID][0]["before"]["buy_under_aud"] = value
            with self.subTest(value=repr(value)):
                self.assertIn("audit record can't be checked", self.refusal())
        self.assertEqual(self.store.writes, [])

    def test_transaction_confirmation_cannot_lose_or_change_the_restored_target(self):
        self.seed([self.target_pair()])
        source = {"preference": None, "data": {}, "adapters": {}}
        def lose_target(after, actual):
            actual[0]["after"]["buy_under_aud"] = None
            return after, actual
        self.mutate = lose_target
        before = self.store.snapshot
        with mock.patch.object(shop_reference_source, "context", return_value=source), self.assertRaises(inventory.Conflict):
            self.run_undo()
        self.assertEqual(self.store.snapshot, before)
        self.assertEqual(self.store.writes, [])
