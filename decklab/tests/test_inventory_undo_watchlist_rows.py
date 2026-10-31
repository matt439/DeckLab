"""Removing 1-50 added purchase-queue rows, or restoring 1-50 removed ones, with fake audit rows and a disposable queue only.

database_apply stands in for PgInventory.apply: it gives new rows fresh ids and the positions
pg._positions gives them, records a DELETE, INSERT or UPDATE audit row (full database images, ids
and positions included) for every queue row the undo changed, then runs the transaction-local
proof (undo_watchlist_rows.confirm) with the persisted layout before "committing". No PostgreSQL,
household data, retailer or card cache is read or changed.
"""
import copy
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import changes, model, pg, undo, undo_watchlist_rows as rows_undo
from decklab.lib.state import Invalid
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests import test_inventory_undo_token_restore as restore_fixture
from decklab.tests.test_inventory_undo_watchlist import WatchlistUndoFixture, image, row

STEP = 1024
FRESH = 500


def queued(count, prefix="Fixture card"):
    return [row(f"{prefix} {index + 1}", quantity="1", state="waiting_for_stock", listed_aud="0.50",
                listed_at="Fixture shop", in_stock="no", checked="2026-10-20", notes="Queue note")
            for index in range(count)]


class WatchlistRowsFixture(WatchlistUndoFixture):
    proof = rows_undo   # the module whose transaction-local proof database_apply runs

    def setUp(self):
        super().setUp()
        self.store.undo_watchlist_positions = mock.Mock(side_effect=self.layout)
        self.store.undo_watchlist_latest = mock.Mock(side_effect=lambda: max(self.touched.values(), default=None))

    def seed(self, changed=None, survivors=(row("Sol Ring"), row("Arcane Signet")), *, op="INSERT"):
        """op INSERT: changed rows (ids 7, 8, ...) were added after the survivors (ids 1, 2, ...).
        op DELETE: changed rows were removed, each from just after a survivor in turn (or the end)."""
        self.changed = copy.deepcopy(queued(2) if changed is None else changed)
        self.next_id = FRESH
        made = [model.WatchRow.make(values, id=index + 1) for index, values in enumerate(survivors)]
        self.positions = {item.id: (index + 1) * STEP for index, item in enumerate(made)}
        self.touched = {item.id: 50 for item in made}
        audit = []
        for index, values in enumerate(self.changed):
            rid = 7 + index
            if op == "INSERT":
                position = (len(made) + 1) * STEP + index * STEP
                made.append(model.WatchRow.make(values, id=rid))
                self.positions[rid] = position
                audit.append({"id": fixture.ROW_ID + index, "table": rows_undo.TABLE, "op": "INSERT", "key": {"id": rid},
                              "before": None, "after": image(values, rid, position)})
            else:
                after = index + 1 if index < len(survivors) else len(survivors)
                position = after * STEP + 1 + index
                audit.append({"id": fixture.ROW_ID + index, "table": rows_undo.TABLE, "op": "DELETE", "key": {"id": rid},
                              "before": image(values, rid, position), "after": None})
            self.touched[rid] = fixture.ROW_ID + index
        self.store.snapshot = self.store.snapshot.with_watchlist(made)
        self.store.audit[fixture.CHANGE_ID] = audit
        self.store.latest = fixture.ROW_ID + len(self.changed) - 1

    def layout(self):
        return [{"id": item.id, "position": self.positions[item.id]} for item in self.store.snapshot.watchlist.rows]

    def database_apply(self, op, actor, message, reason=None, expected_revision=None):
        before = self.store.snapshot
        after, summary = op.run(changes.detach(before))
        after = changes.prepare(before, after, revision=before.revision + "-undo")
        old = {item.id: item for item in before.watchlist.rows}
        given = after.watchlist.rows
        ids = [item.id if item.id in old else 0 for item in given]
        placed = pg._positions(ids, {rid: self.positions[rid] for rid in old})
        made, positions, actual, audit_id = [], {}, [], self.store.latest + 1
        for item, rid, position in zip(given, ids, placed):
            if not rid:
                rid, self.next_id = self.next_id, self.next_id + 1
                actual.append({"id": audit_id, "table": rows_undo.TABLE, "op": "INSERT", "key": {"id": rid},
                               "before": None, "after": image(item.as_dict(), rid, position)})
                audit_id += 1
            elif item.as_dict() != old[rid].as_dict() or position != self.positions[rid]:
                actual.append({"id": audit_id, "table": rows_undo.TABLE, "op": "UPDATE", "key": {"id": rid},
                               "before": image(old[rid].as_dict(), rid, self.positions[rid]),
                               "after": image(item.as_dict(), rid, position)})
                audit_id += 1
            made.append(model.WatchRow.make(item.as_dict(), id=rid))
            positions[rid] = position
        kept = {item.id for item in made}
        for rid, item in old.items():
            if rid not in kept:
                actual.insert(0, {"id": 0, "table": rows_undo.TABLE, "op": "DELETE", "key": {"id": rid},
                                  "before": image(item.as_dict(), rid, self.positions[rid]), "after": None})
        for index, item in enumerate(actual):
            item["id"] = self.store.latest + 1 + index
        after = after.with_watchlist(made)
        layout = [{"id": rid, "position": positions[rid]} for rid in sorted(positions, key=lambda rid: (positions[rid], rid))]
        if self.proof.restoring(summary):
            if self.mutate is not None:
                after, actual, layout = self.mutate(after, copy.deepcopy(actual), copy.deepcopy(layout))
            summary = self.proof.confirm(before, after, summary, actual, layout)
        self.store.snapshot = after
        self.positions = positions
        self.store.writes.append((op, actor, message, summary, reason))
        self.store.latest += 1 + len(actual)
        for item in actual:
            self.touched[item["key"]["id"]] = item["id"]
        return after, summary

    def refusal(self):
        with self.assertRaises(rows_undo.Refused) as caught:
            self.review()
        return str(caught.exception)

    def names(self):
        return [values["name"] for _, values in self.queue_rows()]


class RemoveAddedRowsTests(WatchlistRowsFixture):
    def test_review_lists_every_added_row_and_needs_a_reason_without_writing(self):
        before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        plan = self.review()
        self.assertEqual((plan["action"], plan["kind"], plan["space"], plan["row_count"], plan["reason_required"]),
                         (rows_undo.REMOVE, "watchlist", "home", 2, True))
        self.assertEqual(plan["label"], "2 added purchase-queue rows")
        self.assertEqual([item["watch_row_id"] for item in plan["rows"]], [7, 8])
        self.assertEqual([item["current"] for item in plan["rows"]], self.changed)
        self.assertEqual([item["label"] for item in plan["rows"]], ["Fixture card 1", "Fixture card 2"])
        self.assertRegex(plan["expect"], "^[a-f0-9]{64}$")
        self.assertEqual((self.store.snapshot, self.store.audit, self.store.writes), (before, audit, []))
        self.store.undo_watchlist_positions.assert_not_called()

    def test_one_and_fifty_rows_are_reviewed_and_fifty_one_is_refused_naming_how_many(self):
        self.seed(queued(1))
        self.assertEqual((self.review()["row_count"], self.review()["label"]), (1, "1 added purchase-queue row"))
        self.seed(queued(50))
        self.assertEqual(self.review()["row_count"], 50)
        self.seed(queued(51))
        message = self.refusal()
        self.assertIn("added 51 purchase-queue rows", message)
        self.assertIn("at most 50", message)

    def test_a_mixed_or_member_source_is_missing_before_any_row_lookup(self):
        base = self.store.audit[fixture.CHANGE_ID]
        removed = {"id": 902, "table": rows_undo.TABLE, "op": "DELETE", "key": {"id": 31},
                   "before": image(queued(1)[0], 31, 0), "after": None}
        updated = {"id": 903, "table": rows_undo.TABLE, "op": "UPDATE", "key": {"id": 1},
                   "before": image(row("Sol Ring"), 1, 1024), "after": image(row("Sol Ring", quantity="3"), 1, 1024)}
        order = {"id": 904, "table": "order_component", "op": "UPDATE", "key": {"order_id": "x", "component_id": "cards"},
                 "before": {"status": "pending"}, "after": {"status": "received"}}
        half = {**copy.deepcopy(base[0]), "before": copy.deepcopy(base[0]["after"])}
        for audit in ([*base, order], [order, *base], [half, base[1]], [*base, removed, order]):
            with self.subTest(audit=[item["op"] + " " + item["table"] for item in audit]):
                self.store.audit[fixture.CHANGE_ID] = copy.deepcopy(audit)
                self.store.undo_latest.reset_mock()
                with self.assertRaises(undo.UndoMissing):
                    self.review()
                self.store.undo_latest.assert_not_called()
        # Queue rows of several kinds are a mixed queue change, the mixed slice's to review.
        from decklab.lib.inventory import undo_watchlist_mixed
        for audit in ([*base, removed], [*base, updated], [updated, *base]):
            with self.subTest(audit=[item["op"] + " " + item["table"] for item in audit]):
                self.store.audit[fixture.CHANGE_ID] = copy.deepcopy(audit)
                with mock.patch.object(undo_watchlist_mixed, "review", return_value="mixed") as mixed_review:
                    self.assertEqual(self.review(), "mixed")
                mixed_review.assert_called_once()
        self.seed()
        self.store.undo_audit_rows.reset_mock()
        with self.assertRaises(undo.UndoMissing):
            self.review("user2")
        self.store.undo_audit_rows.assert_not_called()

    def test_a_row_edited_moved_or_removed_since_refuses_the_whole_change_naming_only_counts(self):
        self.touched[8] += 10
        message = self.refusal()
        self.assertIn("1 of the 2 added purchase-queue rows can't be removed", message)
        self.assertIn(rows_undo.EDITED + ": 1", message)
        self.assertIn("nothing was removed", message)
        for words in ("Fixture card", "Fixture shop", "Queue note", "0.50"):
            self.assertNotIn(words, message)
        self.seed()
        rows = [item if item.id != 7 else item.replace(notes="Edited without an audit fence") for item in self.store.snapshot.watchlist.rows]
        self.store.snapshot = self.store.snapshot.with_watchlist(rows)
        self.assertIn(rows_undo.EDITED + ": 1", self.refusal())
        self.seed()
        self.store.snapshot = self.store.snapshot.with_watchlist([item for item in self.store.snapshot.watchlist.rows if item.id != 8])
        self.assertIn(rows_undo.EDITED + ": 1", self.refusal())

    def test_a_malformed_audit_image_is_refused_as_unreadable(self):
        for mutate in (lambda item: item["after"].pop("source"), lambda item: item["after"].update(quantity="1"),
                       lambda item: item["after"].update(quantity=0), lambda item: item.update(key={"id": 99}),
                       lambda item: item["after"].update(notes=None), lambda item: item["after"].update(position=-1)):
            with self.subTest(mutate=mutate):
                self.seed()
                mutate(self.store.audit[fixture.CHANGE_ID][0])
                self.assertIn(rows_undo.AUDIT + ": 1", self.refusal())

    def test_a_stale_snapshot_is_a_conflict(self):
        self.store.snapshot = self.store.snapshot.replace(stale="Fixture stale")
        with self.assertRaises(undo.UndoConflict):
            self.review()


class RemoveAddedRowsApplyTests(WatchlistRowsFixture):
    def test_undo_removes_every_added_row_keeping_survivors_ids_values_and_positions(self):
        before, positions = self.queue_rows(), dict(self.positions)
        _, summary = self.run_undo(reason="  Added  by mistake ")
        self.assertEqual(self.queue_rows(), before[:2])
        self.assertEqual(self.positions, {1: positions[1], 2: positions[2]})
        self.assertEqual(summary.extra["removed_watch_row_ids"], [7, 8])
        self.assertNotIn("watch_rows", summary.extra)
        self.assertEqual(summary.counts, {"removed_rows": 2, "undo": 1})
        self.assertEqual((summary.extra["action"], summary.extra["undo_reason"]), (rows_undo.REMOVE, "Added by mistake"))
        self.assertEqual(summary.extra["row_change_ids"], [fixture.ROW_ID, fixture.ROW_ID + 1])
        self.assertEqual(self.store.writes[0][4], None)  # The API passes the reason to the change set; see its tests.
        for words in ("Fixture card", "Queue note", "0.50"):
            self.assertNotIn(words, summary.text)

    def test_one_fifty_and_every_row_of_the_queue_can_be_removed(self):
        for count, survivors in ((1, (row("Sol Ring"),)), (50, (row("Sol Ring"),)), (2, ())):
            with self.subTest(count=count, survivors=len(survivors)):
                self.seed(queued(count), survivors)
                _, summary = self.run_undo(reason="Not wanted")
                self.assertEqual(summary.counts["removed_rows"], count)
                self.assertEqual(self.names(), [values["name"] for values in survivors])

    def test_a_reason_is_required_and_a_confirmation_is_refused(self):
        for extra in ({}, {"reason": " "}, {"reason": "x" * 201}, {"reason": "Not wanted", "confirm_owned": True}):
            with self.subTest(extra=extra), self.assertRaises(Invalid):
                self.run_undo(**extra)
        self.assertEqual(self.store.writes, [])

    def test_a_change_after_the_preview_is_a_conflict_without_write(self):
        expect = self.review()["expect"]
        rows = [item if item.id != 1 else item.replace(notes="Survivor edited meanwhile") for item in self.store.snapshot.watchlist.rows]
        self.store.snapshot = self.store.snapshot.with_watchlist(rows)
        before = self.store.snapshot
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect, reason="Not wanted")
        self.assertEqual((self.store.snapshot, self.store.writes), (before, []))

    def test_a_tampered_audit_effect_is_unconfirmed_and_nothing_is_kept(self):
        def extra(after, actual, layout):
            return after, [*actual, {**actual[0], "id": actual[0]["id"] + 99}], layout

        def wrong_id(after, actual, layout):
            actual[0]["key"] = {"id": 1}
            return after, actual, layout

        def changed_before(after, actual, layout):
            actual[1]["before"]["notes"] = "Something else"
            return after, actual, layout

        def moved(after, actual, layout):
            actual[0]["before"]["position"] += 1
            return after, actual, layout

        def missing(after, actual, layout):
            return after, actual[:1], layout

        def survivor(after, actual, layout):
            rows = [item if item.id != 1 else item.replace(quantity="9") for item in after.watchlist.rows]
            return after.with_watchlist(rows), actual, layout

        def reordered(after, actual, layout):
            return after.with_watchlist(list(reversed(after.watchlist.rows))), actual, list(reversed(layout))

        def other_part(after, actual, layout):
            return after.with_collection("home", []), actual, layout

        for mutate in (extra, wrong_id, changed_before, moved, missing, survivor, reordered, other_part):
            with self.subTest(mutate=mutate.__name__):
                self.seed()
                before = self.store.snapshot
                self.mutate = mutate
                with self.assertRaises(undo.UndoConflict) as caught:
                    self.run_undo(reason="Not wanted")
                self.assertEqual(str(caught.exception), rows_undo.UNCONFIRMED)
                self.assertEqual(self.store.snapshot, before)

    def test_a_replay_of_the_same_undo_is_refused(self):
        plan = self.review()
        self.run_undo(plan["expect"], reason="Not wanted")
        saved = self.store.snapshot
        with self.assertRaises(Invalid):
            self.run_undo(plan["expect"], reason="Not wanted")
        self.assertEqual(self.store.snapshot, saved)
        self.assertIn(rows_undo.EDITED + ": 2", self.refusal())


class RestoreRemovedRowsTests(WatchlistRowsFixture):
    def setUp(self):
        super().setUp()
        self.seed(op="DELETE")

    def test_review_lists_every_recorded_row_and_needs_no_reason_without_writing(self):
        before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        plan = self.review()
        self.assertEqual((plan["action"], plan["kind"], plan["space"], plan["row_count"]), (rows_undo.ADD, "watchlist", "home", 2))
        self.assertNotIn("reason_required", plan)
        self.assertEqual(plan["label"], "2 removed purchase-queue rows")
        self.assertEqual([item["restore"] for item in plan["rows"]], self.changed)
        self.assertEqual([item["label"] for item in plan["rows"]], ["Fixture card 1", "Fixture card 2"])
        self.assertEqual((self.store.snapshot, self.store.audit, self.store.writes), (before, audit, []))

    def test_one_and_fifty_rows_are_reviewed_and_fifty_one_is_refused_naming_how_many(self):
        self.seed(queued(1), op="DELETE")
        self.assertEqual(self.review()["label"], "1 removed purchase-queue row")
        self.seed(queued(50), op="DELETE")
        self.assertEqual(self.review()["row_count"], 50)
        self.seed(queued(51), op="DELETE")
        message = self.refusal()
        self.assertIn("removed 51 purchase-queue rows", message)
        self.assertIn("at most 50", message)

    def test_recorded_values_that_are_not_a_valid_queue_row_now_refuse_the_whole_change(self):
        for bad in ({"state": "bogus"}, {"checked": "last week"}, {"source": "magic/buylists/0000-00-00-missing-fixture.md"},
                    {"listed_at": ""}, {"printing": "exact"}):
            with self.subTest(bad=bad):
                changed = queued(2)
                changed[1].update(bad)
                self.seed(changed, op="DELETE")
                message = self.refusal()
                self.assertIn("1 of the 2 removed purchase-queue rows can't be restored", message)
                self.assertIn(rows_undo.INVALID + ": 1", message)
                self.assertNotIn("missing-fixture", message)

    def test_a_row_that_would_repeat_a_current_or_another_restored_row_is_refused(self):
        self.seed([row("Sol Ring", quantity="4"), *queued(1)], op="DELETE")
        message = self.refusal()
        self.assertIn(rows_undo.DUPLICATE + ": 1", message)
        self.assertNotIn("Sol Ring", message)
        self.seed([*queued(1), *queued(1)], op="DELETE")
        self.assertIn(rows_undo.DUPLICATE + ": 2", self.refusal())

    def test_a_reused_id_or_a_later_audit_row_of_the_old_id_is_unreadable(self):
        self.touched[8] += 10
        self.assertIn(rows_undo.AUDIT + ": 1", self.refusal())
        self.seed(op="DELETE")
        self.store.snapshot = self.store.snapshot.with_watchlist([*self.store.snapshot.watchlist.rows, model.WatchRow.make(row("Other"), id=7)])
        self.positions[7] = 99999
        self.assertIn(rows_undo.AUDIT + ": 1", self.refusal())

    def test_a_later_queue_change_is_a_conflict_and_restored_rows_removed_again_are_not_restored_twice(self):
        self.touched[1] = max(self.touched.values()) + 1
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review()
        self.assertEqual(str(caught.exception), rows_undo.CHANGED)
        self.seed(op="DELETE")
        self.run_undo()
        restored = [rid for rid, _ in self.queue_rows() if rid >= FRESH]
        self.store.snapshot = self.store.snapshot.with_watchlist(
            [item for item in self.store.snapshot.watchlist.rows if item.id not in restored])
        for rid in restored:
            self.store.latest += 1
            self.touched[rid] = self.store.latest
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review()
        self.assertEqual(str(caught.exception), rows_undo.CHANGED)

    def test_without_the_queue_audit_fence_it_is_unsupported(self):
        del self.store.undo_watchlist_latest
        with self.assertRaises(undo.UndoUnsupported):
            self.review()

    def test_without_the_persisted_layout_it_is_unsupported(self):
        del self.store.undo_watchlist_positions
        with self.assertRaises(undo.UndoUnsupported):
            self.review()

    def test_a_placement_that_would_renumber_a_current_row_is_a_conflict(self):
        self.positions[2] = self.positions[1] + 1
        self.store.audit[fixture.CHANGE_ID][0]["before"]["position"] = self.positions[1]
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review()
        self.assertEqual(str(caught.exception), rows_undo.UNSAFE)


class RestoreRemovedRowsApplyTests(WatchlistRowsFixture):
    def setUp(self):
        super().setUp()
        self.seed(op="DELETE")

    def test_undo_restores_every_row_as_a_new_row_where_it_was_keeping_survivors(self):
        positions = dict(self.positions)
        _, summary = self.run_undo()
        self.assertEqual(self.names(), ["Sol Ring", "Fixture card 1", "Arcane Signet", "Fixture card 2"])
        self.assertEqual(summary.extra["restored_watch_row_ids"], [FRESH, FRESH + 1])
        self.assertEqual([values for rid, values in self.queue_rows() if rid >= FRESH], self.changed)
        self.assertEqual({rid: self.positions[rid] for rid in (1, 2)}, positions)
        self.assertNotIn("watch_rows", summary.extra)
        self.assertEqual(summary.counts, {"added_rows": 2, "undo": 1})
        self.assertEqual((summary.extra["action"], summary.extra["row_count"]), (rows_undo.ADD, 2))
        for words in ("Fixture card", "Queue note", "0.50"):
            self.assertNotIn(words, summary.text)

    def test_rows_removed_from_the_end_or_an_empty_queue_come_back_in_order(self):
        self.seed(queued(3), (row("Sol Ring"),), op="DELETE")
        self.run_undo()
        self.assertEqual(self.names(), ["Sol Ring", "Fixture card 1", "Fixture card 2", "Fixture card 3"])
        self.seed(queued(50), (), op="DELETE")
        self.run_undo()
        self.assertEqual(self.names(), [values["name"] for values in queued(50)])

    def test_a_reason_or_confirmation_is_refused(self):
        for extra in ({"reason": "Not wanted"}, {"confirm_owned": True}):
            with self.subTest(extra=extra), self.assertRaises(Invalid):
                self.run_undo(**extra)
        self.assertEqual(self.store.writes, [])

    def test_a_change_after_the_preview_is_a_conflict_without_write(self):
        expect = self.review()["expect"]
        self.positions[2] += 1
        before = self.store.snapshot
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect)
        self.assertEqual((self.store.snapshot, self.store.writes), (before, []))

    def test_a_tampered_audit_effect_is_unconfirmed_and_nothing_is_kept(self):
        def extra(after, actual, layout):
            return after, [*actual, {**actual[0], "id": actual[0]["id"] + 99}], layout

        def reused(after, actual, layout):
            actual[0]["after"]["id"], actual[0]["key"] = 7, {"id": 7}
            return after, actual, layout

        def survivor_id(after, actual, layout):
            actual[0]["after"]["id"], actual[0]["key"] = 1, {"id": 1}
            return after, actual, layout

        def changed_after(after, actual, layout):
            actual[1]["after"]["notes"] = "Something else"
            return after, actual, layout

        def position(after, actual, layout):
            actual[0]["after"]["position"] += 1
            return after, actual, layout

        def missing(after, actual, layout):
            return after, actual[:1], layout

        def moved_layout(after, actual, layout):
            layout[0]["position"] -= 1
            return after, actual, layout

        def survivor(after, actual, layout):
            rows = [item if item.id != 1 else item.replace(quantity="9") for item in after.watchlist.rows]
            return after.with_watchlist(rows), actual, layout

        def reordered(after, actual, layout):
            return after.with_watchlist(list(reversed(after.watchlist.rows))), actual, layout

        def other_part(after, actual, layout):
            return after.with_collection("home", []), actual, layout

        for mutate in (extra, reused, survivor_id, changed_after, position, missing, moved_layout, survivor, reordered, other_part):
            with self.subTest(mutate=mutate.__name__):
                self.seed(op="DELETE")
                before = self.store.snapshot
                self.mutate = mutate
                with self.assertRaises(undo.UndoConflict) as caught:
                    self.run_undo()
                self.assertEqual(str(caught.exception), rows_undo.UNCONFIRMED)
                self.assertEqual(self.store.snapshot, before)

    def test_a_replay_of_the_same_undo_is_refused_once_the_queue_changed(self):
        plan = self.review()
        self.run_undo(plan["expect"])
        saved = self.store.snapshot
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(plan["expect"])
        self.assertEqual(self.store.snapshot, saved)
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review()
        self.assertEqual(str(caught.exception), rows_undo.CHANGED)


class PgApplyWatchlistRowsHookTests(unittest.TestCase):
    """PgInventory.apply itself runs the added/removed rows' proof inside the write, with no database at all."""

    setUp = restore_fixture.PgApplyHookTests.setUp
    run_op = restore_fixture.PgApplyHookTests.run_op

    def rows_summary(self, action=rows_undo.REMOVE):
        return inventory.Summary("text", {}, {}, {"action": action, "kind": "watchlist", "space": "home", "row_count": 2,
                                                 "watch_rows": {"label": "x"}})

    def test_a_queue_rows_undo_is_proved_on_the_write_cursor_before_it_returns(self):
        for action in (rows_undo.REMOVE, rows_undo.ADD):
            with self.subTest(action=action):
                summary, proved = self.rows_summary(action), inventory.Summary("proved", {}, {}, {})
                with mock.patch.object(rows_undo, "confirm_in_transaction", return_value=proved) as hook:
                    self.assertEqual(self.run_op(summary), (self.saved, proved))
                hook.assert_called_once_with(self.cur, 55, self.before, self.saved, summary)
        self.assertEqual(self.rolled_back, [])

    def test_a_failed_proof_rolls_the_change_back(self):
        with mock.patch.object(rows_undo, "confirm_in_transaction", side_effect=undo.UndoConflict(rows_undo.UNCONFIRMED, "x")), \
                self.assertRaises(undo.UndoConflict):
            self.run_op(self.rows_summary())
        self.assertEqual(self.rolled_back, [True])

    def test_an_ordinary_queue_write_is_not_proved(self):
        summary = inventory.Summary("text", {}, {}, {"action": "remove", "kind": "watchlist"})
        with mock.patch.object(rows_undo, "confirm_in_transaction") as hook:
            self.assertEqual(self.run_op(summary), (self.saved, summary))
        hook.assert_not_called()

    def test_the_hook_reads_one_more_audit_row_than_it_reviewed_and_the_layout(self):
        cur = SimpleNamespace(execute=mock.Mock(return_value=SimpleNamespace(fetchall=lambda: [])))
        with mock.patch.object(rows_undo, "confirm", return_value="proved") as proof:
            self.assertEqual(rows_undo.confirm_in_transaction(cur, 55, "before", "saved", self.rows_summary()), "proved")
        (audit_sql, params), (layout_sql,) = cur.execute.call_args_list[0].args, cur.execute.call_args_list[1].args
        self.assertIn("limit %s", audit_sql)
        self.assertEqual(params, (55, 3))
        self.assertIn("from watchlist_item order by position,id", layout_sql)
        self.assertEqual(proof.call_args.args[:2] + proof.call_args.args[3:], ("before", "saved", [], []))


if __name__ == "__main__":
    unittest.main()
