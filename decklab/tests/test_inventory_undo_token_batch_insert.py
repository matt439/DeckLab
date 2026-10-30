"""Removing 2-50 added token cards of one change together, with fake audit rows and disposable stock only.

DatabaseLike stands in for PgInventory.apply: it records a DELETE audit row for every token row
the undo removed (with its persisted position), drops those positions from the layout, then
runs the batch's transaction-local proof before "committing". No PostgreSQL, household data or
real card cache is read or changed.
"""
import copy
from types import SimpleNamespace
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import changes, model, rules, undo, undo_token_batch_remove as batch
from decklab.lib.inventory import undo_token_delete as deleted
from decklab.lib.state import Invalid
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests import test_inventory_undo_token_restore as restore_fixture
from decklab.tests.test_inventory_undo_token_batch import batch_rows

REASON = "Correct an accidental token-card batch."
FIRST_ADDED = 7


def raw(row, space, rid, position):
    out = {"set_code" if key == "set" else key: value for key, value in row.items()}
    out.update(space_id=space, id=rid, position=position)
    return out


class TokenBatchInsertFixture(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ActivityUndoApiTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.store = self.case.backend
        self.products = self.store.snapshot.products
        self.store.snapshot = self.store.snapshot.replace(decks={}, products=(), tokens={},
            status=model.Sheet("magic/products/status.csv", tuple(rules.STATUS_FIELDS), (), True))
        self.store.undo_token_positions = mock.Mock(side_effect=lambda space: copy.deepcopy(self.layout if space == self.space else []))
        self.store.undo_audit_rows = mock.Mock(side_effect=lambda change_id: copy.deepcopy(self.store.audit.get(change_id, [])))
        self.store.undo_latest = mock.Mock(side_effect=lambda table, key: self.touched.get(key.get("id")))
        self.store.apply = self.database_apply
        self.mutate = None
        self.seed()

    def seed(self, rows=None, survivors=(), *, space="home"):
        """rows added in one change (ids 7, 8, ...), beside survivors added earlier."""
        self.space = space
        self.added = copy.deepcopy(batch_rows() if rows is None else rows)
        made = [model.TokenRow.make(row, id=FIRST_ADDED + index) for index, row in enumerate(self.added)]
        self.store.snapshot = self.store.snapshot.with_tokens(space, [*survivors, *made])
        self.layout = [{"id": row.id, "position": (index + 1) * 1024}
                       for index, row in enumerate(self.store.snapshot.token_set(space).rows)]
        positions = {item["id"]: item["position"] for item in self.layout}
        audit, self.touched = [], {row.id: 50 for row in survivors}
        for index, row in enumerate(self.added):
            rid = FIRST_ADDED + index
            audit.append({"id": fixture.ROW_ID + index, "table": "token_card", "op": "INSERT", "key": {"id": rid},
                          "before": None, "after": raw(row, space, rid, positions[rid])})
            self.touched[rid] = fixture.ROW_ID + index
        self.store.audit[fixture.CHANGE_ID] = audit
        self.store.latest = fixture.ROW_ID + len(self.added) - 1

    def database_apply(self, op, actor, message, reason=None, expected_revision=None):
        before = self.store.snapshot
        after, summary = op.run(changes.detach(before))
        after = changes.prepare(before, after, revision=before.revision + "-undo")
        kept = {row.id for row in after.token_set(self.space).rows}
        positions = {item["id"]: item["position"] for item in self.layout}
        actual = [{"id": self.store.latest + 1 + index, "table": "token_card", "op": "DELETE", "key": {"id": row.id},
                   "before": raw({**row.as_dict(), "quantity": int(row.quantity)}, self.space, row.id, positions[row.id]),
                   "after": None}
                  for index, row in enumerate(before.token_set(self.space).rows) if row.id not in kept]
        layout = [item for item in self.layout if item["id"] in kept]
        if deleted.restoring(summary):
            if self.mutate is not None:
                after, actual, layout = self.mutate(after, copy.deepcopy(actual), copy.deepcopy(layout))
            summary = batch.confirm(before, after, summary, actual, layout)
        self.store.snapshot, self.layout = after, layout
        self.store.writes.append((op, actor, message, summary, reason))
        self.store.latest += 1 + len(actual)
        for item in actual:
            self.touched[item["key"]["id"]] = item["id"]
        return after, summary

    def review(self):
        return inventory.undo_review(fixture.CHANGE_ID, self.space, self.store.snapshot)

    def run_undo(self, expect=None, **extra):
        expect = self.review()["expect"] if expect is None else expect
        params = {"change_id": fixture.CHANGE_ID, "space": self.space, "expect": expect, **extra}
        return inventory.apply(inventory.Op("inventory.undo", params), inventory.Actor("test", "Fixture"), "Fixture undo")

    def refusal(self):
        with self.assertRaises(batch.Refused) as caught:
            self.review()
        return str(caught.exception)

    built = restore_fixture.TokenRestoreFixture.built
    product = restore_fixture.TokenRestoreFixture.product
    zombie = restore_fixture.TokenRestoreFixture.zombie


class TokenBatchInsertReviewTests(TokenBatchInsertFixture):
    def test_review_lists_every_row_and_the_whole_physical_count_without_writing(self):
        before, audit, layout = self.store.snapshot, copy.deepcopy(self.store.audit), copy.deepcopy(self.layout)
        plan = self.review()
        self.assertEqual((plan["action"], plan["kind"], plan["row_count"], plan["cards"]), (batch.ACTION, "tokens", 3, 6))
        self.assertEqual([item["current"] for item in plan["rows"]], self.added)
        self.assertEqual([item["label"] for item in plan["rows"]], ["Angel / The Monarch", "Treasure", "Beast / Dog"])
        self.assertEqual([item["token_row_id"] for item in plan["rows"]], [7, 8, 9])
        self.assertEqual([item["row_change_id"] for item in plan["rows"]], [fixture.ROW_ID, fixture.ROW_ID + 1, fixture.ROW_ID + 2])
        self.assertEqual((plan["label"], plan["reason_required"]), ("3 added token-card rows", True))
        self.assertRegex(plan["expect"], "^[a-f0-9]{64}$")
        self.assertEqual((self.store.snapshot, self.store.audit, self.layout, self.store.writes), (before, audit, layout, []))

    def test_more_than_fifty_rows_are_refused_naming_how_many(self):
        self.seed(batch_rows(51))
        message = self.refusal()
        self.assertIn("51 token-card rows", message)
        self.assertIn("at most 50", message)
        self.seed(batch_rows(50))
        self.assertEqual(self.review()["row_count"], 50)

    def test_an_edited_or_removed_row_refuses_the_whole_batch_naming_only_counts_and_reasons(self):
        self.touched[8] += 10  # Edited after the change.
        message = self.refusal()
        self.assertIn("1 of the 3 added token-card rows can't be removed", message)
        self.assertIn(batch.EDITED + ": 1", message)
        self.assertIn("nothing was removed", message)
        for name in ("Angel", "Treasure", "Beast", "tst"):
            self.assertNotIn(name, message)
        self.seed()
        rows = [row for row in self.store.snapshot.token_set("home").rows if row.id != 9]
        self.store.snapshot = self.store.snapshot.with_tokens("home", [*rows, model.TokenRow.make(
            {**self.added[2], "notes": "Edited without an audit fence"}, id=9)])
        self.assertIn(batch.EDITED + ": 1", self.refusal())
        self.seed()
        self.layout[0]["position"] += 1
        self.assertIn(batch.EDITED + ": 1", self.refusal())
        self.seed()
        self.store.snapshot = self.store.snapshot.with_tokens("home", self.store.snapshot.token_set("home").rows[1:])
        self.layout = self.layout[1:]
        self.assertIn(batch.EDITED + ": 1", self.refusal())

    def test_rows_packed_in_a_deck_or_product_line_are_counted(self):
        self.built("1 Treasure; 1 Beast // Dog")
        message = self.refusal()
        self.assertIn("2 of the 3", message)
        self.assertIn(batch.PACKED + ": 2", message)
        self.assertNotIn("Treasure", message)
        self.store.snapshot = self.store.snapshot.replace(decks={})
        self.product("1 Angel // The Monarch")
        self.assertIn(batch.PACKED + ": 1", self.refusal())

    def test_unverified_pairing_and_ambiguous_identities_are_counted(self):
        rows = batch_rows()
        rows[1] = {**rows[1], "notes": ""}  # A blank reverse without "single-sided verified".
        self.seed(rows)
        self.assertIn(batch.UNVERIFIED + ": 1", self.refusal())
        self.seed(survivors=(model.TokenRow.make({**batch_rows()[0], "quantity": 1}, id=80),))
        self.assertIn(batch.AMBIGUOUS + ": 1", self.refusal())

    def test_a_hidden_or_other_row_makes_the_whole_change_missing_before_any_fact_is_checked(self):
        for mutate in (lambda rows: rows[2]["after"].update(space_id="user2"),
                       lambda rows: rows[1].update(table="collection_card"),
                       lambda rows: rows[0].update(op="UPDATE", before={}),
                       lambda rows: rows.append({"id": 999, "table": "token_card", "op": "DELETE", "key": {"id": 5},
                                                 "before": {"space_id": "home"}, "after": None})):
            self.seed()
            mutate(self.store.audit[fixture.CHANGE_ID])
            with self.subTest(mutate=mutate), \
                    mock.patch.object(batch, "_source", side_effect=AssertionError("Not an owned source")), \
                    self.assertRaises(undo.UndoMissing):
                self.review()
        self.store.undo_token_positions.reset_mock()
        self.seed(space="user2")
        with self.assertRaises(undo.UndoMissing):
            inventory.undo_review(fixture.CHANGE_ID, "home", self.store.snapshot)
        self.store.undo_token_positions.assert_not_called()

    def test_another_spaces_batch_is_missing_to_home_even_when_too_large(self):
        self.seed(batch_rows(51), space="user2")
        with self.assertRaises(undo.UndoMissing):
            inventory.undo_review(fixture.CHANGE_ID, "home", self.store.snapshot)

    def test_a_row_named_twice_or_no_complete_audit_reader_refuses(self):
        self.store.audit[fixture.CHANGE_ID][2]["after"]["id"] = 7
        self.store.audit[fixture.CHANGE_ID][2]["key"] = {"id": 7}
        with self.assertRaises(undo.UndoUnsupported):
            self.review()
        self.seed()
        self.store.undo_audit_rows = None
        with self.assertRaises(undo.UndoUnsupported):
            self.review()


class TokenBatchInsertRemoveTests(TokenBatchInsertFixture):
    def test_reasoned_removal_deletes_exactly_those_rows_and_keeps_a_packed_survivor(self):
        self.seed(survivors=(self.zombie(),))
        self.built("1 Zombie // Zombie Knight")
        survivor = next(row for row in self.store.snapshot.token_set("home").rows if row.id == 80)
        layout = [item for item in self.layout if item["id"] == 80]
        after, summary = self.run_undo(reason=REASON)
        self.assertEqual([(row.id, row.as_dict()) for row in after.token_set("home").rows], [(80, survivor.as_dict())])
        self.assertEqual(self.layout, layout)
        self.assertEqual(summary.extra["removed_token_row_ids"], [7, 8, 9])
        self.assertNotIn("token_remove", summary.extra)
        self.assertEqual((summary.extra["action"], summary.extra["row_count"], summary.extra["undo_reason"]),
                         (batch.ACTION, 3, REASON))
        self.assertEqual(summary.extra["row_change_ids"], [fixture.ROW_ID, fixture.ROW_ID + 1, fixture.ROW_ID + 2])
        # "cards" is the space's total after the save (the survivor's 3); the message names the 6 removed.
        self.assertEqual((summary.counts["undo"], summary.counts["removed_rows"], summary.counts["cards"],
                          summary.counts["removed_cards"]), (1, 3, 3, 6))
        self.assertIn("remove 3 added token-card rows (6 physical cards)", summary.text)
        self.assertNotIn("Angel", summary.text)
        self.assertEqual(len(self.store.writes), 1)

    def test_the_last_rows_can_go_and_the_reason_is_required_and_a_replay_refused(self):
        expect = self.review()["expect"]
        for extra in ({}, {"reason": "   "}, {"reason": "x" * 201}, {"reason": REASON, "confirm_owned": True}):
            with self.subTest(extra=extra), self.assertRaises(Invalid):
                self.run_undo(expect, **extra)
        self.assertEqual(self.store.writes, [])
        after, summary = self.run_undo(expect, reason=REASON)
        self.assertEqual(after.token_set("home").rows, ())
        self.assertEqual(summary.counts["cards"], 0)
        with self.assertRaises(inventory.Invalid):  # Its source rows are now touched by the undo.
            self.run_undo(expect, reason=REASON)
        self.assertEqual(len(self.store.writes), 1)

    def test_changes_after_the_preview_refuse_without_writing(self):
        self.seed(survivors=(self.zombie(),))
        expect = self.review()["expect"]
        self.store.snapshot = self.store.snapshot.with_tokens("home", [
            *(row for row in self.store.snapshot.token_set("home").rows if row.id != 80), self.zombie(quantity=4)])
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect, reason=REASON)
        self.seed()
        expect = self.review()["expect"]
        self.built("1 Treasure")  # A packed line now holds one of them.
        with self.assertRaises(batch.Refused):
            self.run_undo(expect, reason=REASON)
        self.assertEqual(self.store.writes, [])

    def test_a_members_batch_is_removed_only_there(self):
        home = self.zombie()
        self.store.snapshot = self.store.snapshot.with_tokens("home", [home])
        self.seed(space="user2")
        after, summary = self.run_undo(reason=REASON)
        self.assertEqual(after.token_set("user2").rows, ())
        self.assertEqual([(row.id, row.as_dict()) for row in after.token_set("home").rows], [(home.id, home.as_dict())])
        self.assertEqual(summary.extra["space"], "user2")


class TokenBatchInsertProofTests(TokenBatchInsertFixture):
    """The transaction-local proof refuses anything but exactly the reviewed N DELETEs."""

    def setUp(self):
        super().setUp()
        self.seed(survivors=(self.zombie(),))
        self.built("1 Zombie // Zombie Knight")

    def refused(self, mutate):
        self.mutate = mutate
        expect = self.review()["expect"]
        with self.assertRaises(undo.UndoConflict) as caught:
            self.run_undo(expect, reason=REASON)
        self.assertEqual(str(caught.exception), batch.UNCONFIRMED)
        self.assertEqual(self.store.writes, [])

    def test_missing_extra_other_duplicated_or_changed_rows_are_refused(self):
        survivor = {"id": 999, "table": "token_card", "op": "DELETE", "key": {"id": 80}, "after": None,
                    "before": raw({**self.zombie().as_dict(), "quantity": 3}, "home", 80, 1024)}
        mutations = [
            lambda a: a.pop(),
            lambda a: a.append(copy.deepcopy(a[0])),
            lambda a: a.__setitem__(0, survivor),
            lambda a: a.__setitem__(1, copy.deepcopy(a[0])),
            lambda a: a[1].update(op="UPDATE"),
            lambda a: a[1].update(after={}),
            lambda a: a[2]["before"].update(notes="Changed in the database"),
            lambda a: a[2]["before"].update(position=1),
            lambda a: a[2]["before"].update(space_id="user2"),
            lambda a: a[0].update(key={"id": 1}),
        ]
        for change in mutations:
            def mutate(after, actual, layout, change=change):
                change(actual)
                return after, actual, layout
            with self.subTest(change=change):
                self.refused(mutate)

    def test_moved_positions_changed_survivors_other_spaces_and_packing_are_refused(self):
        def moved(after, actual, layout):
            layout[0]["position"] += 1
            return after, actual, layout
        def kept_target(after, actual, layout):
            return after, actual, [*layout, {"id": 9, "position": 9000}]
        def survivor(after, actual, layout):
            rows = [row.replace(notes="Edited meanwhile") if row.id == 80 else row for row in after.token_set("home").rows]
            return after.with_tokens("home", rows), actual, layout
        def other_space(after, actual, layout):
            return after.with_tokens("user2", [self.zombie(rid=81)]), actual, layout
        def packing(after, actual, layout):
            text = next(iter(after.decks.values())).text.replace("1 Zombie // Zombie Knight", "")
            return after.with_deck(model.Deck("home", "casual", "fixture", text)), actual, layout
        for mutate in (moved, kept_target, survivor, other_space, packing):
            with self.subTest(mutate=mutate.__name__):
                self.refused(mutate)

    def test_transaction_hook_reads_one_more_row_than_the_batch_and_the_own_space_layout(self):
        calls = []
        def execute(sql, params):
            calls.append((sql, params))
            return SimpleNamespace(fetchall=lambda: [])
        summary = inventory.Summary("text", {}, {}, {"action": batch.ACTION, "kind": "tokens", "space": "user2",
                                                    "token_remove": {"removed": [{}, {}, {}], "label": "x"}})
        self.assertTrue(deleted.restoring(summary))
        self.assertFalse(deleted.restoring(inventory.Summary("text", {}, {}, {"action": batch.ACTION, "kind": "tokens"})))
        with mock.patch.object(batch, "confirm", return_value="proved") as proved:
            self.assertEqual(deleted.confirm_in_transaction(SimpleNamespace(execute=execute), 55, "before", "saved", summary), "proved")
        self.assertEqual([params for _, params in calls], [(55, 4), ("user2",)])
        self.assertTrue(all(sql.startswith("select ") for sql, _ in calls))
        self.assertIn("change_set_id=%s", calls[0][0])
        self.assertEqual(proved.call_args.args[3:], ([], []))


class PgApplyBatchRemoveHookTests(restore_fixture.PgApplyHookTests):
    """PgInventory.apply proves a batch removal on the write cursor too, and rolls a refused one back."""

    def restore_summary(self):
        return inventory.Summary("text", {}, {}, {"action": batch.ACTION, "kind": "tokens", "space": "home",
                                                 "token_remove": {"removed": [{}, {}], "label": "x"}})

    def test_a_batch_removal_goes_to_the_batch_removal_proof(self):
        summary, proved = self.restore_summary(), inventory.Summary("proved", {}, {}, {})
        with mock.patch.object(batch, "confirm_in_transaction", return_value=proved) as hook:
            self.assertEqual(self.run_op(summary), (self.saved, proved))
        hook.assert_called_once_with(self.cur, 55, self.before, self.saved, summary)
        self.assertEqual(self.rolled_back, [])

