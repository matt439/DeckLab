"""Undoing a purchase-queue change that mixed updated, added and removed rows, with fake audit rows and a disposable queue only.

database_apply (the added/removed slice's) stands in for PgInventory.apply: it gives new rows
fresh ids and the positions pg._positions gives them, records an UPDATE, DELETE or INSERT audit
row for every queue row the undo changed, then runs this module's transaction-local proof
(undo_watchlist_mixed.confirm) with the persisted layout before "committing". No PostgreSQL,
household data, retailer or card cache is read or changed.
"""
import copy
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import model, undo, undo_watchlist as queue, undo_watchlist_mixed as mixed
from decklab.lib.state import Invalid
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests import test_inventory_undo_token_restore as restore_fixture
from decklab.tests.test_inventory_undo_watchlist import image, pairs, row
from decklab.tests.test_inventory_undo_watchlist_rows import FRESH, STEP, WatchlistRowsFixture, queued


class WatchlistMixedFixture(WatchlistRowsFixture):
    proof = mixed

    def setUp(self):
        super().setUp()
        self.mix()

    def mix(self, updated=1, added=1, removed=1, survivors=(row("Sol Ring"), row("Arcane Signet"))):
        """One change that updated rows 7.. (after the first survivor), added rows 100.. (at the end)
        and removed rows 200.. (each recorded just after the first survivor)."""
        self.updates = pairs(updated)
        self.added = queued(added, "Added card")
        self.removed = queued(removed, "Removed card")
        self.next_id = FRESH
        order = [(1, survivors[0])] if survivors else []
        order += [(7 + n, current) for n, (current, _) in enumerate(self.updates)]
        order += [(index + 2, values) for index, values in enumerate(survivors[1:])]
        order += [(100 + n, values) for n, values in enumerate(self.added)]
        made = [model.WatchRow.make(values, id=rid) for rid, values in order]
        self.positions = {rid: (index + 1) * STEP for index, (rid, _) in enumerate(order)}
        self.touched = {rid: 50 for rid, _ in order}
        audit, number = [], fixture.ROW_ID
        for n, (current, recorded) in enumerate(self.updates):
            rid = 7 + n
            audit.append({"id": number, "table": queue.TABLE, "op": "UPDATE", "key": {"id": rid},
                          "before": image(recorded, rid, self.positions[rid]), "after": image(current, rid, self.positions[rid])})
            number += 1
        for n, values in enumerate(self.added):
            rid = 100 + n
            audit.append({"id": number, "table": queue.TABLE, "op": "INSERT", "key": {"id": rid},
                          "before": None, "after": image(values, rid, self.positions[rid])})
            number += 1
        first = self.positions[1] if survivors else 0
        for n, values in enumerate(self.removed):
            rid = 200 + n
            audit.append({"id": number, "table": queue.TABLE, "op": "DELETE", "key": {"id": rid},
                          "before": image(values, rid, first + 1 + n), "after": None})
            number += 1
        for item in audit:
            self.touched[item["key"]["id"]] = item["id"]
        self.store.snapshot = self.store.snapshot.with_watchlist(made)
        self.store.audit[fixture.CHANGE_ID] = audit
        self.store.latest = number - 1


class MixedReviewTests(WatchlistMixedFixture):
    def test_review_lists_every_row_by_its_effect_and_needs_a_reason_without_writing(self):
        before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        plan = self.review()
        self.assertEqual((plan["action"], plan["kind"], plan["space"], plan["row_count"], plan["reason_required"]),
                         (mixed.ACTION, "watchlist", "home", 3, True))
        self.assertEqual(plan["label"], "Changes to 3 purchase-queue rows")
        self.assertEqual(plan["counts"], {"updated": 1, "added": 1, "removed": 1})
        self.assertEqual([item["change"] for item in plan["rows"]], ["updated", "added", "removed"])
        self.assertEqual((plan["rows"][0]["watch_row_id"], plan["rows"][0]["current"], plan["rows"][0]["restore"]), (7, *self.updates[0]))
        self.assertEqual([field["field"] for field in plan["rows"][0]["fields"]], ["quantity", "in_stock", "checked", "notes", "state"])
        self.assertEqual((plan["rows"][1]["watch_row_id"], plan["rows"][1]["current"]), (100, self.added[0]))
        self.assertEqual(plan["rows"][2]["restore"], self.removed[0])
        self.assertNotIn("watch_row_id", plan["rows"][2])
        self.assertRegex(plan["expect"], "^[a-f0-9]{64}$")
        self.assertEqual((self.store.snapshot, self.store.audit, self.store.writes), (before, audit, []))

    def test_every_mix_of_two_kinds_is_reviewed_and_only_one_that_removes_a_row_needs_a_reason(self):
        for counts, reason in (((1, 1, 0), True), ((1, 0, 1), False), ((0, 1, 1), True), ((2, 2, 2), True)):
            with self.subTest(counts=counts):
                self.mix(*counts)
                plan = self.review()
                self.assertEqual((plan["action"], plan["row_count"]), (mixed.ACTION, sum(counts)))
                self.assertEqual(plan.get("reason_required", False), reason)

    def test_fifty_rows_are_reviewed_and_fifty_one_are_refused_naming_how_many(self):
        self.mix(20, 20, 10)
        self.assertEqual(self.review()["row_count"], 50)
        self.mix(20, 20, 11)
        message = self.refusal()
        self.assertIn("touched 51 purchase-queue rows", message)
        self.assertIn("at most 50", message)

    def test_a_source_with_another_table_or_a_member_space_is_missing_before_any_row_lookup(self):
        base = self.store.audit[fixture.CHANGE_ID]
        order = {"id": 904, "table": "order_component", "op": "UPDATE", "key": {"order_id": "x", "component_id": "cards"},
                 "before": {"status": "pending"}, "after": {"status": "received"}}
        half = {**copy.deepcopy(base[1]), "before": copy.deepcopy(base[1]["after"])}
        gone = {**copy.deepcopy(base[2]), "after": copy.deepcopy(base[2]["before"])}
        for audit in ([*base, order], [order, *base], [base[0], half, base[2]], [base[0], base[1], gone]):
            with self.subTest(audit=[item["op"] + " " + item["table"] for item in audit]):
                self.store.audit[fixture.CHANGE_ID] = copy.deepcopy(audit)
                self.store.undo_latest.reset_mock()
                with self.assertRaises(undo.UndoMissing):
                    self.review()
                self.store.undo_latest.assert_not_called()
        self.mix()
        self.store.undo_audit_rows.reset_mock()
        with self.assertRaises(undo.UndoMissing):
            self.review("user2")
        self.store.undo_audit_rows.assert_not_called()

    def test_first_rows_of_one_kind_are_routed_by_the_complete_change(self):
        self.mix(2, 1, 0)   # The first two audit rows are both UPDATEs.
        self.assertEqual(self.review()["action"], mixed.ACTION)
        self.mix(0, 2, 1)   # The first two are INSERTs.
        self.assertEqual(self.review()["action"], mixed.ACTION)
        del self.store.undo_audit_rows
        with self.assertRaises(undo.UndoUnsupported):
            self.review()

    def test_rows_touched_moved_or_unreadable_refuse_the_whole_change_naming_only_counts(self):
        self.touched[7] += 10
        self.touched[100] += 10
        message = self.refusal()
        self.assertIn("2 of the 3 purchase-queue rows that change touched can't be undone", message)
        self.assertIn(queue.EDITED + ": 2", message)
        self.assertIn("nothing was changed", message)
        for words in ("Fixture card", "Added card", "Removed card", "Fixture shop", "Queue note", "queue note", "0.50"):
            self.assertNotIn(words, message)
        self.mix()
        self.store.audit[fixture.CHANGE_ID][0]["before"]["position"] += 1
        self.assertIn(queue.MOVED + ": 1", self.refusal())
        self.mix()
        self.store.audit[fixture.CHANGE_ID][2]["before"].pop("source")
        self.assertIn(queue.AUDIT + ": 1", self.refusal())
        self.mix()
        self.touched[200] += 10
        self.assertIn(queue.AUDIT + ": 1", self.refusal())
        self.mix()
        rows = [item if item.id != 100 else item.replace(notes="Edited without a fence") for item in self.store.snapshot.watchlist.rows]
        self.store.snapshot = self.store.snapshot.with_watchlist(rows)
        self.assertIn(queue.EDITED + ": 1", self.refusal())

    def test_invalid_or_repeating_restored_values_refuse_the_whole_change(self):
        self.mix()
        self.store.audit[fixture.CHANGE_ID][2]["before"]["state"] = "bogus"
        self.assertIn(queue.INVALID + ": 1", self.refusal())
        self.mix()
        self.store.audit[fixture.CHANGE_ID][0]["before"]["name"] = "Sol Ring"
        message = self.refusal()
        self.assertIn(queue.DUPLICATE + ": 1", message)
        self.assertNotIn("Sol Ring", message)

    def test_a_restored_row_may_take_back_an_added_rows_purchase_key(self):
        self.mix(0, 1, 1)
        self.store.audit[fixture.CHANGE_ID][1]["before"]["name"] = "Added card 1"
        self.assertEqual(self.review()["counts"], {"updated": 0, "added": 1, "removed": 1})

    def test_a_later_queue_change_fences_a_change_that_removed_rows(self):
        self.touched[1] = max(self.touched.values()) + 1
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review()
        self.assertEqual(str(caught.exception), mixed.CHANGED)
        self.mix(1, 1, 0)
        self.touched[1] = max(self.touched.values()) + 1
        self.assertEqual(self.review()["row_count"], 2)   # Nothing to restore, so no fence.
        self.mix()
        del self.store.undo_watchlist_latest
        with self.assertRaises(undo.UndoUnsupported):
            self.review()

    def test_without_the_persisted_layout_or_with_a_renumbering_placement_it_is_not_offered(self):
        del self.store.undo_watchlist_positions
        with self.assertRaises(undo.UndoUnsupported):
            self.review()
        self.store.undo_watchlist_positions = mock.Mock(side_effect=self.layout)
        self.mix()
        self.positions[7] = self.positions[1] + 1
        self.store.audit[fixture.CHANGE_ID][0]["before"]["position"] = self.positions[7]
        self.store.audit[fixture.CHANGE_ID][0]["after"]["position"] = self.positions[7]
        self.store.audit[fixture.CHANGE_ID][2]["before"]["position"] = self.positions[1]
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review()
        self.assertEqual(str(caught.exception), mixed.UNSAFE)

    def test_a_stale_snapshot_is_a_conflict(self):
        self.store.snapshot = self.store.snapshot.replace(stale="Fixture stale")
        with self.assertRaises(undo.UndoConflict):
            self.review()


class MixedApplyTests(WatchlistMixedFixture):
    def test_one_inverse_restores_removes_and_adds_back_keeping_every_survivor(self):
        positions = dict(self.positions)
        _, summary = self.run_undo(reason="  Shop check  mistake ")
        self.assertEqual(self.names(), ["Sol Ring", "Removed card 1", "Fixture card 1", "Arcane Signet"])
        rows = dict(self.queue_rows())
        self.assertEqual((rows[7], rows[FRESH]), (self.updates[0][1], self.removed[0]))
        self.assertNotIn(100, rows)
        self.assertEqual({rid: self.positions[rid] for rid in (1, 7, 2)}, {rid: positions[rid] for rid in (1, 7, 2)})
        self.assertEqual((summary.extra["restored_watch_row_ids"], summary.extra["removed_watch_row_ids"],
                          summary.extra["added_watch_row_ids"]), ([7], [100], [FRESH]))
        self.assertNotIn("watch_mixed", summary.extra)
        self.assertEqual(summary.counts, {"edited": 1, "removed_rows": 1, "added_rows": 1, "undo": 1})
        self.assertEqual((summary.extra["action"], summary.extra["undo_reason"]), (mixed.ACTION, "Shop check mistake"))
        self.assertEqual(summary.text, f"Undo change #{fixture.CHANGE_ID}: undo Changes to 3 purchase-queue rows "
                                       "(1 restored in place, 1 removed, 1 restored as a new row)")
        self.assertEqual(summary.extra["row_change_ids"], [fixture.ROW_ID, fixture.ROW_ID + 1, fixture.ROW_ID + 2])

    def test_updates_with_additions_or_removals_alone_and_fifty_rows(self):
        for counts, extra in (((2, 1, 0), {"reason": "Not wanted"}), ((1, 0, 2), {}), ((20, 20, 10), {"reason": "Not wanted"})):
            with self.subTest(counts=counts):
                self.mix(*counts)
                _, summary = self.run_undo(**extra)
                self.assertEqual(len(summary.extra["restored_watch_row_ids"]), counts[0])
                self.assertEqual(len(summary.extra["added_watch_row_ids"]), counts[2])
                rows = dict(self.queue_rows())
                self.assertEqual([rows[7 + n] for n in range(counts[0])], [recorded for _, recorded in self.updates])
                self.assertFalse(any(100 + n in rows for n in range(counts[1])))
                self.assertEqual(self.names()[1:1 + counts[2]], [values["name"] for values in self.removed])
                self.assertEqual(summary.text.count("restored as new rows" if counts[2] > 1 else "restored as a new row"),
                                 1 if counts[2] else 0)

    def test_reason_rules_follow_whether_any_row_is_removed(self):
        for extra in ({}, {"reason": " "}, {"reason": "x" * 201}, {"reason": "Not wanted", "confirm_owned": True}):
            with self.subTest(extra=extra), self.assertRaises(Invalid):
                self.run_undo(**extra)
        self.mix(1, 0, 1)
        for extra in ({"reason": "Not wanted"}, {"confirm_owned": True}):
            with self.subTest(extra=extra), self.assertRaises(Invalid):
                self.run_undo(**extra)
        self.assertEqual(self.store.writes, [])

    def test_a_change_after_the_preview_is_a_conflict_without_write(self):
        expect = self.review()["expect"]
        rows = [item if item.id != 2 else item.replace(notes="Survivor edited meanwhile") for item in self.store.snapshot.watchlist.rows]
        self.store.snapshot = self.store.snapshot.with_watchlist(rows)
        before = self.store.snapshot
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect, reason="Not wanted")
        self.assertEqual((self.store.snapshot, self.store.writes), (before, []))

    def test_a_tampered_audit_effect_is_unconfirmed_and_nothing_is_kept(self):
        def find(actual, op):
            return next(item for item in actual if item["op"] == op)

        def extra(after, actual, layout):
            return after, [*actual, {**actual[0], "id": actual[0]["id"] + 99}], layout

        def missing_update(after, actual, layout):
            return after, [item for item in actual if item["op"] != "UPDATE"], layout

        def missing_delete(after, actual, layout):
            return after, [item for item in actual if item["op"] != "DELETE"], layout

        def update_as_other(after, actual, layout):
            find(actual, "UPDATE")["after"]["notes"] = "Something else"
            return after, actual, layout

        def delete_of_survivor(after, actual, layout):
            item = find(actual, "DELETE")
            item["key"], item["before"]["id"] = {"id": 1}, 1
            return after, actual, layout

        def reused_id(after, actual, layout):
            item = find(actual, "INSERT")
            item["key"], item["after"]["id"] = {"id": 200}, 200
            return after, actual, layout

        def position(after, actual, layout):
            find(actual, "INSERT")["after"]["position"] += 1
            return after, actual, layout

        def moved_layout(after, actual, layout):
            layout[-1]["position"] += 1
            return after, actual, layout

        def other_table(after, actual, layout):
            find(actual, "UPDATE")["table"] = "token_card"
            return after, actual, layout

        def survivor(after, actual, layout):
            rows = [item if item.id != 2 else item.replace(quantity="9") for item in after.watchlist.rows]
            return after.with_watchlist(rows), actual, layout

        def other_part(after, actual, layout):
            return after.with_collection("home", []), actual, layout

        for mutate in (extra, missing_update, missing_delete, update_as_other, delete_of_survivor, reused_id, position,
                       moved_layout, other_table, survivor, other_part):
            with self.subTest(mutate=mutate.__name__):
                self.mix()
                before = self.store.snapshot
                self.mutate = mutate
                with self.assertRaises(undo.UndoConflict) as caught:
                    self.run_undo(reason="Not wanted")
                self.assertEqual(str(caught.exception), mixed.UNCONFIRMED)
                self.assertEqual(self.store.snapshot, before)

    def test_a_replay_is_refused_and_the_change_is_no_longer_offered(self):
        plan = self.review()
        self.run_undo(plan["expect"], reason="Not wanted")
        saved = self.store.snapshot
        with self.assertRaises((undo.UndoConflict, mixed.Refused)):
            self.run_undo(plan["expect"], reason="Not wanted")
        self.assertEqual(self.store.snapshot, saved)


class PgApplyWatchlistMixedHookTests(unittest.TestCase):
    """PgInventory.apply itself runs the mixed queue proof inside the write, with no database at all."""

    setUp = restore_fixture.PgApplyHookTests.setUp
    run_op = restore_fixture.PgApplyHookTests.run_op

    def mixed_summary(self):
        return inventory.Summary("text", {}, {}, {"action": mixed.ACTION, "kind": "watchlist", "space": "home", "row_count": 3,
                                                 "watch_mixed": {"label": "x"}})

    def test_a_mixed_queue_undo_is_proved_on_the_write_cursor_before_it_returns(self):
        summary, proved = self.mixed_summary(), inventory.Summary("proved", {}, {}, {})
        with mock.patch.object(mixed, "confirm_in_transaction", return_value=proved) as hook:
            self.assertEqual(self.run_op(summary), (self.saved, proved))
        hook.assert_called_once_with(self.cur, 55, self.before, self.saved, summary)
        self.assertEqual(self.rolled_back, [])

    def test_a_failed_proof_rolls_the_change_back(self):
        with mock.patch.object(mixed, "confirm_in_transaction", side_effect=undo.UndoConflict(mixed.UNCONFIRMED, "x")), \
                self.assertRaises(undo.UndoConflict):
            self.run_op(self.mixed_summary())
        self.assertEqual(self.rolled_back, [True])

    def test_the_hook_reads_one_more_audit_row_than_it_reviewed_and_the_layout(self):
        cur = SimpleNamespace(execute=mock.Mock(return_value=SimpleNamespace(fetchall=lambda: [])))
        with mock.patch.object(mixed, "confirm", return_value="proved") as proof:
            self.assertEqual(mixed.confirm_in_transaction(cur, 55, "before", "saved", self.mixed_summary()), "proved")
        (audit_sql, params), (layout_sql,) = cur.execute.call_args_list[0].args, cur.execute.call_args_list[1].args
        self.assertIn("limit %s", audit_sql)
        self.assertEqual(params, (55, 4))
        self.assertIn("from watchlist_item order by position,id", layout_sql)
        self.assertEqual(proof.call_args.args[:2] + proof.call_args.args[3:], ("before", "saved", [], []))


if __name__ == "__main__":
    unittest.main()
