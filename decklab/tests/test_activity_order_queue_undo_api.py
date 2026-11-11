"""Home-only complete order/queue reviews use source receipts, not submitted row authority."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import activity_undo as api, activity_order_queue_undo as order_api
from decklab.lib.inventory import changes, model, orders, refresh, undo_order_queue_verify as verify
from decklab.tests import test_undo_order_queue as facts


class OrderQueueUndoApiTests(unittest.TestCase):
    def setUp(self):
        case = facts.OrderQueueUndoTests()
        self.addCleanup(case.doCleanups)
        case.setUp()
        self.case = case
        self.install()

    def install(self):
        self.store = self.case.store
        self.writes = []
        self.store.load = lambda: self.store.snapshot
        self.store.undo_audit = lambda identity: copy.deepcopy(self.store.raw[:2])
        self.store.saves_decks = lambda: True
        self.store.apply = self.database_apply
        self.addCleanup(inventory.use(self.store))

    def database_apply(self, operation, actor, message, reason=None, expected_revision=None):
        before = self.store.snapshot
        after, summary = operation.run(changes.detach(before))
        after = changes.prepare(before, after, revision=before.revision + "-committed")
        fresh = max([row.id for row in before.watchlist.rows] + [100])
        rows = []
        for row in after.watchlist.rows:
            if row.id <= 0:
                fresh += 1
                row = model.WatchRow.make(row.as_dict(), id=fresh)
            rows.append(row)
        after = after.with_watchlist(rows)
        summary = verify.prepare(before, after, summary)
        actual, positions = facts.recorded(before, after, self.store.positions,
                                           first_audit=max(row["id"] for row in self.store.raw) + 1)
        layout = [{"id": row.id, "position": positions[row.id]} for row in after.watchlist.rows]
        summary = verify.confirm(before, after, summary, actual, layout, reason)
        self.store.snapshot, self.store.positions = after, positions
        self.writes.append((operation, actor, message, reason, summary))
        return after, summary

    def get(self, who="matt"):
        with self.case.as_(who):
            return api.undo_view(id=str(facts.CHANGE))

    def post(self, shown, who="matt", **values):
        with self.case.as_(who):
            return self.case.call(api.apply_undo, who, id=facts.CHANGE, expect=shown["expect"], reason=facts.REASON, **values)

    def error(self, code, call, *args, **kwargs):
        self.case.assertApiError(code, call, *args, **kwargs)

    def test_preview_is_read_only_and_one_confirmed_inverse_returns_whole_order_and_queue_receipts(self):
        before = self.store.snapshot
        shown = self.get()
        self.assertEqual(shown["kind"], "order_queue")
        self.assertEqual(shown["current"]["components"][0]["rows"], [facts.card()])
        self.assertIsNone(shown["restored"])
        self.assertEqual(shown["queue"]["rows"][0]["restored"]["quantity"], "3")
        self.assertNotIn("proof", json.dumps(shown))
        self.assertNotIn("[[Deck Lab fulfilment", json.dumps(shown))
        self.assertEqual(self.store.snapshot, before)
        self.assertEqual(self.writes, [])
        saved = self.post(shown)
        self.assertTrue(saved["saved"])
        self.assertIsNone(saved["order"])
        self.assertEqual(saved["queue"]["restored_rows"][0]["row"], facts.queued())
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.writes[0][0].kind, "inventory.undo_order_queue")
        self.error(409, self.post, shown)
        self.assertEqual(len(self.writes), 1)

    def test_home_reader_has_no_write_review_and_other_spaces_do_not_read_complete_source(self):
        self.error(403, self.get, "user1")
        with mock.patch.object(self.store, "undo_audit_rows", side_effect=AssertionError("Private complete order source read")):
            self.error(404, self.get, "user2")
            self.error(404, self.get, "user3")
        self.assertEqual(self.writes, [])

    def test_member_or_private_home_kit_changes_leave_both_visible_preview_and_nested_receipt_identical(self):
        deck = model.Deck("home", "casual", "queue-fixture", facts.pg_facts.TEXT)
        self.store.snapshot = self.store.snapshot.with_deck(deck)
        shown = self.get()
        self.store.snapshot = self.store.snapshot.with_collection("user2", [{**facts.card(4), "notes": "Private member fixture"}]).with_deck(deck.replace(
            text=deck.text.replace("private-legacy-sleeves", "changed-private-sleeves"))).replace(revision="private-global-update", decks_revision="private-global-deck-update")
        self.assertEqual(self.get(), shown)
        self.assertNotIn("private-legacy", json.dumps(shown))
        self.assertNotIn("changed-private", json.dumps(shown))

    def test_changed_source_or_missing_reason_refuses_without_any_order_or_queue_write(self):
        shown = self.get()
        with self.case.as_("matt"):
            self.error(400, self.case.call, api.apply_undo, "matt", id=facts.CHANGE, expect=shown["expect"])
        self.store.order_latest += 1
        self.error(409, self.post, shown)
        self.assertEqual(self.writes, [])

    def test_order_cancellation_that_inserted_a_queue_row_undoes_with_one_actual_reason(self):
        complete, _ = orders.add_order(self.case.initial, record={"id": "2026-11-12-all"}, cards={"rows": [facts.card()]},
                                      fulfils=[{"select": "#1", "quantity": 3}])
        cancelled, _ = orders.cancel_order(complete, order="2026-11-12-all", component="cards", reason="Not sent", restore_queue=True)
        self.case.source(complete, cancelled)
        self.install()
        shown = self.get()
        self.assertEqual(shown["queue"]["action"], "watchlist_remove")
        saved = self.post(shown)
        self.assertEqual(saved["order"]["components"][0]["status"], "pending")
        self.assertEqual(saved["queue"]["removed_watch_row_ids"], [cancelled.watchlist.rows[0].id] if cancelled.watchlist.rows[0].id else [101])
        self.assertEqual(self.writes[0][3], facts.REASON)

    def test_candidate_hint_is_advisory_for_only_home_order_editors(self):
        change = {"id": facts.CHANGE, "rows": self.store.raw, "total": len(self.store.raw)}
        with self.case.as_("matt"):
            hint = order_api.hint(change, {"id": facts.CHANGE}, api.guard.viewer())
        self.assertEqual(hint, {"review": True, "kind": "order_queue"})
        with self.case.as_("user1"):
            self.assertIsNone(order_api.hint(change, {"id": facts.CHANGE}, api.guard.viewer()))

    def test_preview_also_refuses_a_refresher_that_would_erase_authored_text(self):
        deck = model.Deck("home", "casual", "queue-fixture", facts.pg_facts.TEXT + "\n### Substitute version private tactical notes\n")
        self.store.snapshot = self.store.snapshot.with_deck(deck)
        def tampered(before, after, summary):
            return after.with_deck(deck.replace(text=deck.text.replace("private tactical notes", "ERASED authored heading"))), summary
        with mock.patch.object(refresh, "in_op", side_effect=tampered):
            self.error(409, self.get)
        self.assertEqual(self.writes, [])
