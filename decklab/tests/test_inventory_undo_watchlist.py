"""Restoring 1-50 purchase-queue rows' updated values together, with fake audit rows and a disposable queue only.

database_apply stands in for PgInventory.apply: it records an UPDATE audit row (full database
images, ids and positions included) for every queue row the undo changed, then runs the
transaction-local proof (undo_watchlist.confirm) before "committing". No PostgreSQL, household
data, retailer or card cache is read or changed.
"""
import copy
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import changes, model, undo, undo_watchlist as queue
from decklab.lib.inventory.model import QUEUE_FIELDS
from decklab.lib.state import Invalid
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests import test_inventory_undo_token_restore as restore_fixture

FIRST = 7


def row(name, **extra):
    out = {field: "" for field in QUEUE_FIELDS}
    out.update(name=name, quantity="2", printing="any", state="ready")
    out.update(extra)
    return out


def image(values, rid, position):
    """A watchlist_item audit image: database columns, an int quantity, the id and position."""
    out = {queue.COLUMN[field]: int(values[field]) if field == "quantity" else values[field] for field in QUEUE_FIELDS}
    out.update(id=rid, position=position)
    return out


def pairs(count=2):
    """(current, recorded) values of count rows one change updated."""
    made = []
    for index in range(count):
        current = row(f"Fixture card {index + 1}", quantity="1", state="waiting_for_stock", listed_aud="0.50",
                      listed_at="Fixture shop", in_stock="no", checked="2026-10-20", notes="Current queue note")
        recorded = {**current, "quantity": "3", "state": "ready", "in_stock": "yes", "checked": "2026-10-01",
                    "notes": "Recorded queue note"}
        made.append((current, recorded))
    return made


class WatchlistUndoFixture(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ActivityUndoApiTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.store = self.case.backend
        self.store.undo_audit_rows = mock.Mock(side_effect=lambda change_id: copy.deepcopy(self.store.audit.get(change_id, [])))
        self.store.undo_latest = mock.Mock(side_effect=lambda table, key: self.touched.get(key.get("id")))
        self.store.apply = self.database_apply
        self.mutate = None
        self.seed()

    def seed(self, changed=None, survivors=(row("Sol Ring"),), *, position_moved=False):
        """changed: [(current, recorded)] updated in one change (ids 7, 8, ...), after survivors (ids 1, 2, ...)."""
        self.changed = copy.deepcopy(pairs() if changed is None else changed)
        made = [model.WatchRow.make(values, id=index + 1) for index, values in enumerate(survivors)]
        made += [model.WatchRow.make(current, id=FIRST + index) for index, (current, _) in enumerate(self.changed)]
        self.store.snapshot = self.store.snapshot.with_watchlist(made)
        self.positions = {item.id: (index + 1) * 1024 for index, item in enumerate(made)}
        self.touched = {item.id: 50 for item in made[:len(survivors)]}
        audit = []
        for index, (current, recorded) in enumerate(self.changed):
            rid, position = FIRST + index, self.positions[FIRST + index]
            audit.append({"id": fixture.ROW_ID + index, "table": queue.TABLE, "op": "UPDATE", "key": {"id": rid},
                          "before": image(recorded, rid, position + (1 if position_moved else 0)),
                          "after": image(current, rid, position)})
            self.touched[rid] = fixture.ROW_ID + index
        self.store.audit[fixture.CHANGE_ID] = audit
        self.store.latest = fixture.ROW_ID + len(self.changed) - 1

    def database_apply(self, op, actor, message, reason=None, expected_revision=None):
        before = self.store.snapshot
        after, summary = op.run(changes.detach(before))
        after = changes.prepare(before, after, revision=before.revision + "-undo")
        now = {item.id: item for item in after.watchlist.rows}
        actual = [{"id": self.store.latest + 1 + index, "table": queue.TABLE, "op": "UPDATE", "key": {"id": item.id},
                   "before": image(item.as_dict(), item.id, self.positions[item.id]),
                   "after": image(now[item.id].as_dict(), item.id, self.positions[item.id])}
                  for index, item in enumerate(before.watchlist.rows) if now[item.id].as_dict() != item.as_dict()]
        if queue.restoring(summary):
            if self.mutate is not None:
                after, actual = self.mutate(after, copy.deepcopy(actual))
            summary = queue.confirm(before, after, summary, actual)
        self.store.snapshot = after
        self.store.writes.append((op, actor, message, summary, reason))
        self.store.latest += 1 + len(actual)
        for item in actual:
            self.touched[item["key"]["id"]] = item["id"]
        return after, summary

    def review(self, space="home"):
        return inventory.undo_review(fixture.CHANGE_ID, space, self.store.snapshot)

    def run_undo(self, expect=None, **extra):
        expect = self.review()["expect"] if expect is None else expect
        params = {"change_id": fixture.CHANGE_ID, "space": "home", "expect": expect, **extra}
        return inventory.apply(inventory.Op("inventory.undo", params), inventory.Actor("test", "Fixture"), "Fixture undo")

    def refusal(self):
        with self.assertRaises(queue.Refused) as caught:
            self.review()
        return str(caught.exception)

    def queue_rows(self, snapshot=None):
        return [(item.id, item.as_dict()) for item in (snapshot or self.store.snapshot).watchlist.rows]


class WatchlistUndoReviewTests(WatchlistUndoFixture):
    def test_review_lists_every_row_and_its_changed_fields_without_writing(self):
        before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        plan = self.review()
        self.assertEqual((plan["action"], plan["kind"], plan["space"], plan["row_count"]), (queue.ACTION, "watchlist", "home", 2))
        self.assertEqual(plan["label"], "Updates to 2 purchase-queue rows")
        self.assertEqual([item["watch_row_id"] for item in plan["rows"]], [7, 8])
        self.assertEqual([item["label"] for item in plan["rows"]], ["Fixture card 1", "Fixture card 2"])
        self.assertEqual([(item["current"], item["restore"]) for item in plan["rows"]], self.changed)
        self.assertEqual([field["field"] for field in plan["rows"][0]["fields"]], ["quantity", "in_stock", "checked", "notes", "state"])
        self.assertRegex(plan["expect"], "^[a-f0-9]{64}$")
        self.assertEqual((self.store.snapshot, self.store.audit, self.store.writes), (before, audit, []))

    def test_one_row_and_fifty_rows_are_reviewed_and_fifty_one_is_refused_naming_how_many(self):
        self.seed(pairs(1))
        plan = self.review()
        self.assertEqual((plan["row_count"], plan["label"]), (1, "Updates to 1 purchase-queue row"))
        self.seed(pairs(50))
        self.assertEqual(self.review()["row_count"], 50)
        self.seed(pairs(51))
        message = self.refusal()
        self.assertIn("51 purchase-queue rows", message)
        self.assertIn("at most 50", message)

    def test_a_mixed_inserting_or_deleting_or_member_source_is_missing_before_any_row_lookup(self):
        current, recorded = pairs(1)[0]
        order = {"id": 900, "table": "order_component", "op": "UPDATE", "key": {"order_id": "x", "component_id": "cards"},
                 "before": {"status": "pending"}, "after": {"status": "received"}}
        added = {"id": 901, "table": queue.TABLE, "op": "INSERT", "key": {"id": 30}, "before": None, "after": image(current, 30, 0)}
        removed = {"id": 902, "table": queue.TABLE, "op": "DELETE", "key": {"id": 31}, "before": image(recorded, 31, 0), "after": None}
        base = self.store.audit[fixture.CHANGE_ID]
        for rows in ([*base, order], [order, *base], [base[0], added], [base[0], removed], [*base, added]):
            with self.subTest(rows=[item["op"] + " " + item["table"] for item in rows]):
                self.store.audit[fixture.CHANGE_ID] = copy.deepcopy(rows)
                self.store.undo_latest.reset_mock()
                with self.assertRaises(undo.UndoMissing):
                    self.review()
                self.store.undo_latest.assert_not_called()
        self.seed()
        self.store.undo_audit_rows.reset_mock()
        with self.assertRaises(undo.UndoMissing):
            self.review("user2")
        self.store.undo_audit_rows.assert_not_called()
        self.store.undo_latest.assert_not_called()

    def test_a_moved_or_position_only_row_is_refused_with_counts_only(self):
        self.seed(position_moved=True)
        message = self.refusal()
        self.assertIn("2 of the 2 updated purchase-queue rows can't be restored", message)
        self.assertIn(queue.MOVED + ": 2", message)
        self.seed()
        same = self.store.audit[fixture.CHANGE_ID][1]
        same["before"] = {**copy.deepcopy(same["after"]), "position": same["after"]["position"] + 5}
        self.assertIn(queue.MOVED + ": 1", self.refusal())

    def test_a_later_touch_changed_or_missing_row_refuses_the_whole_change_naming_only_counts(self):
        self.touched[8] += 10
        message = self.refusal()
        self.assertIn("1 of the 2 updated purchase-queue rows can't be restored", message)
        self.assertIn(queue.EDITED + ": 1", message)
        self.assertIn("nothing was restored", message)
        for words in ("Fixture card", "Fixture shop", "queue note", "0.50"):
            self.assertNotIn(words, message)
        self.seed()
        rows = [item if item.id != 7 else item.replace(notes="Edited without an audit fence") for item in self.store.snapshot.watchlist.rows]
        self.store.snapshot = self.store.snapshot.with_watchlist(rows)
        self.assertIn(queue.EDITED + ": 1", self.refusal())
        self.seed()
        self.store.snapshot = self.store.snapshot.with_watchlist([item for item in self.store.snapshot.watchlist.rows if item.id != 8])
        self.assertIn(queue.EDITED + ": 1", self.refusal())

    def test_recorded_values_that_are_not_a_valid_queue_row_now_refuse_the_whole_change(self):
        for bad in ({"state": "bogus"}, {"checked": "last week"}, {"source": "magic/buylists/0000-00-00-missing-fixture.md"},
                    {"listed_at": ""}, {"printing": "exact"}):
            with self.subTest(bad=bad):
                changed = pairs()
                changed[1] = (changed[1][0], {**changed[1][1], **bad})
                self.seed(changed)
                message = self.refusal()
                self.assertIn(queue.INVALID + ": 1", message)
                self.assertNotIn("missing-fixture", message)

    def test_a_restored_row_that_would_repeat_another_queue_row_is_refused(self):
        changed = pairs()
        changed[0] = (changed[0][0], {**row("Sol Ring"), "quantity": "4"})
        self.seed(changed)
        message = self.refusal()
        self.assertIn(queue.DUPLICATE + ": 1", message)
        self.assertNotIn("Sol Ring", message)

    def test_a_malformed_audit_image_is_refused_as_unreadable(self):
        for mutate in (lambda item: item["before"].pop("source"), lambda item: item["before"].update(quantity="3"),
                       lambda item: item["after"].update(quantity=0), lambda item: item.update(key={"id": 99}),
                       lambda item: item["before"].update(id=99), lambda item: item["before"].update(notes=None),
                       lambda item: item.update(before=copy.deepcopy(item["after"]))):
            with self.subTest(mutate=mutate):
                self.seed()
                mutate(self.store.audit[fixture.CHANGE_ID][0])
                self.assertIn(queue.AUDIT + ": 1", self.refusal())

    def test_a_stale_snapshot_is_a_conflict(self):
        self.store.snapshot = self.store.snapshot.replace(stale="Fixture stale")
        with self.assertRaises(undo.UndoConflict):
            self.review()


class WatchlistUndoApplyTests(WatchlistUndoFixture):
    def test_undo_restores_every_row_in_place_keeping_ids_order_and_survivors(self):
        before = self.queue_rows()
        _, summary = self.run_undo()
        self.assertEqual(summary.extra["restored_watch_row_ids"], [7, 8])
        self.assertNotIn("watch_restore", summary.extra)
        self.assertEqual(summary.counts, {"edited": 2, "undo": 1})
        self.assertEqual((summary.extra["action"], summary.extra["kind"], summary.extra["row_count"]), (queue.ACTION, "watchlist", 2))
        self.assertEqual(summary.extra["row_change_ids"], [fixture.ROW_ID, fixture.ROW_ID + 1])
        for words in ("queue note", "0.50", "Fixture shop"):
            self.assertNotIn(words, summary.text)
        self.assertEqual(self.queue_rows(), [before[0], (7, self.changed[0][1]), (8, self.changed[1][1])])

    def test_one_and_fifty_row_changes_apply(self):
        for count in (1, 50):
            with self.subTest(count=count):
                self.seed(pairs(count))
                _, summary = self.run_undo()
                self.assertEqual(summary.counts["edited"], count)
                self.assertEqual([values for _, values in self.queue_rows()[1:]], [recorded for _, recorded in self.changed])

    def test_a_change_after_the_preview_is_a_conflict_without_write(self):
        expect = self.review()["expect"]
        rows = [item if item.id != 1 else item.replace(notes="Survivor edited meanwhile") for item in self.store.snapshot.watchlist.rows]
        self.store.snapshot = self.store.snapshot.with_watchlist(rows)
        before = self.store.snapshot
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect)
        self.assertEqual((self.store.snapshot, self.store.writes), (before, []))

    def test_a_reason_or_physical_confirmation_is_refused(self):
        for extra in ({"reason": "Not wanted"}, {"confirm_owned": True}):
            with self.subTest(extra=extra), self.assertRaises(Invalid):
                self.run_undo(**extra)
        self.assertEqual(self.store.writes, [])

    def test_a_tampered_audit_effect_is_unconfirmed_and_nothing_is_kept(self):
        def extra(after, actual):
            return after, [*actual, {**actual[0], "id": actual[0]["id"] + 99}]

        def wrong_id(after, actual):
            actual[0]["key"] = {"id": 1}
            return after, actual

        def changed_after(after, actual):
            actual[1]["after"]["notes"] = "Something else"
            return after, actual

        def moved(after, actual):
            actual[0]["after"]["position"] += 1
            actual[0]["before"]["position"] += 1
            return after, actual

        def missing(after, actual):
            return after, actual[:1]

        def survivor(after, actual):
            rows = [item if item.id != 1 else item.replace(quantity="9") for item in after.watchlist.rows]
            return after.with_watchlist(rows), actual

        def reordered(after, actual):
            return after.with_watchlist(list(reversed(after.watchlist.rows))), actual

        def other_part(after, actual):
            return after.with_collection("home", []), actual

        for mutate in (extra, wrong_id, changed_after, moved, missing, survivor, reordered, other_part):
            with self.subTest(mutate=mutate.__name__):
                self.seed()
                before = self.store.snapshot
                self.mutate = mutate
                with self.assertRaises(undo.UndoConflict) as caught:
                    self.run_undo()
                self.assertEqual(str(caught.exception), queue.UNCONFIRMED)
                self.assertEqual(self.store.snapshot, before)

    def test_a_replay_of_the_same_undo_is_refused(self):
        plan = self.review()
        self.run_undo(plan["expect"])
        saved = self.store.snapshot
        with self.assertRaises(Invalid):
            self.run_undo(plan["expect"])
        self.assertEqual(self.store.snapshot, saved)
        self.assertIn(queue.EDITED + ": 2", self.refusal())


class PgApplyWatchlistHookTests(unittest.TestCase):
    """PgInventory.apply itself runs the queue proof inside the write, with no database at all."""

    setUp = restore_fixture.PgApplyHookTests.setUp
    run_op = restore_fixture.PgApplyHookTests.run_op

    def restore_summary(self):
        return inventory.Summary("text", {}, {}, {"action": queue.ACTION, "kind": "watchlist", "space": "home",
                                                 "watch_restore": {"rows": [{}, {}], "label": "x"}})

    def test_a_queue_restore_is_proved_on_the_write_cursor_before_it_returns(self):
        summary, proved = self.restore_summary(), inventory.Summary("proved", {}, {}, {})
        with mock.patch.object(queue, "confirm_in_transaction", return_value=proved) as hook:
            self.assertEqual(self.run_op(summary), (self.saved, proved))
        hook.assert_called_once_with(self.cur, 55, self.before, self.saved, summary)
        self.assertEqual(self.rolled_back, [])

    def test_a_failed_proof_rolls_the_change_back(self):
        with mock.patch.object(queue, "confirm_in_transaction", side_effect=undo.UndoConflict(queue.UNCONFIRMED, "x")), \
                self.assertRaises(undo.UndoConflict):
            self.run_op(self.restore_summary())
        self.assertEqual(self.rolled_back, [True])

    def test_an_ordinary_queue_write_is_not_proved(self):
        summary = inventory.Summary("text", {}, {}, {"action": "set", "kind": "watchlist"})
        with mock.patch.object(queue, "confirm_in_transaction") as hook:
            self.assertEqual(self.run_op(summary), (self.saved, summary))
        hook.assert_not_called()

    def test_the_hook_reads_one_more_audit_row_than_it_reviewed(self):
        cur = SimpleNamespace(execute=mock.Mock(return_value=SimpleNamespace(fetchall=lambda: [])))
        with mock.patch.object(queue, "confirm", return_value="proved") as proof:
            self.assertEqual(queue.confirm_in_transaction(cur, 55, "before", "saved", self.restore_summary()), "proved")
        sql, params = cur.execute.call_args.args
        self.assertIn("limit %s", sql)
        self.assertEqual(params, (55, 3))
        proof.assert_called_once()
        self.assertEqual(proof.call_args.args[:2] + proof.call_args.args[3:], ("before", "saved", []))



if __name__ == "__main__":
    unittest.main()
