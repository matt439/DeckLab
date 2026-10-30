"""Restoring 2-50 deleted token cards of one change together, with fake audit rows and disposable stock only.

DatabaseLike (test_inventory_undo_token_restore's) stands in for PgInventory.apply: it gives each
id-less row the next serial id and a persisted position, records their INSERT audit rows, then
runs the batch's transaction-local proof before "committing". No PostgreSQL, household data or
real card cache is read or changed.
"""
import copy
from types import SimpleNamespace
from unittest import mock

from decklab.lib import cards, inventory
from decklab.lib.inventory import undo, undo_token_batch as batch, undo_token_delete as deleted
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests import test_inventory_undo_token_restore as restore_fixture
from decklab.tests.test_inventory_undo_token_delete import token
from decklab.tests.test_inventory_undo_token_restore import FRESH, TokenRestoreFixture

FIRST_DELETED = 71


def batch_rows(count=3):
    """count distinct, fully known token cards (no two may be the same physical card)."""
    rows = [token(), token("Treasure", "", quantity=1, front_collector_number="3", notes="single-sided verified"),
            token("Beast", "Dog", quantity=3, front_collector_number="4", back_collector_number="5")]
    rows += [token("Spirit", "", quantity=1, front_collector_number=str(100 + n), notes="single-sided verified")
             for n in range(max(0, count - len(rows)))]
    return rows[:count]


class TokenBatchFixture(TokenRestoreFixture):
    def setUp(self):
        super().setUp()
        self.store.undo_audit_rows = mock.Mock(side_effect=lambda change_id: copy.deepcopy(self.store.audit.get(change_id, [])))
        self.store.undo_latest = mock.Mock(side_effect=lambda table, key: self.touched.get(key.get("id")))
        self.seed_batch()

    def seed_batch(self, rows=None, survivors=(), *, space="home"):
        self.space = space
        self.olds = copy.deepcopy(batch_rows() if rows is None else rows)
        self.store.snapshot = self.store.snapshot.with_tokens(space, survivors)
        self.layout = [{"id": row.id, "position": (index + 1) * 1024}
                       for index, row in enumerate(self.store.snapshot.token_set(space).rows)]
        audit, self.touched = [], {}
        for index, old in enumerate(self.olds):
            raw = {"set_code" if key == "set" else key: value for key, value in old.items()}
            raw.update(space_id=space, id=FIRST_DELETED + index, position=500 + index)
            audit.append({"id": fixture.ROW_ID + index, "table": "token_card", "op": "DELETE",
                          "key": {"id": raw["id"]}, "before": raw, "after": None})
            self.touched[raw["id"]] = fixture.ROW_ID + index
        self.store.audit[fixture.CHANGE_ID] = audit
        self.store.latest = self.latest = fixture.ROW_ID + len(self.olds) - 1

    def prove(self, before, after, summary, actual, layout):
        return (batch.confirm if summary.extra.get("action") == batch.ACTION else deleted.confirm)(
            before, after, summary, actual, layout)

    def database_apply(self, op, actor, message, reason=None, expected_revision=None):
        result = super().database_apply(op, actor, message, reason, expected_revision)
        for rid in {row.id for row in self.store.snapshot.token_set(self.space).rows}:
            self.touched.setdefault(rid, self.store.latest)
        return result

    def refusal(self, call=None):
        with self.assertRaises(batch.Refused) as caught:
            (call or self.review)()
        return str(caught.exception)


class TokenBatchReviewTests(TokenBatchFixture):
    def test_review_lists_every_row_and_the_whole_physical_count_without_writing(self):
        before, audit = self.store.snapshot, copy.deepcopy(self.store.audit)
        plan = self.review()
        self.assertEqual((plan["action"], plan["kind"], plan["row_count"], plan["cards"]), (batch.ACTION, "tokens", 3, 6))
        self.assertEqual([item["restore"] for item in plan["rows"]], self.olds)
        self.assertEqual([item["label"] for item in plan["rows"]], ["Angel / The Monarch", "Treasure", "Beast / Dog"])
        self.assertEqual([item["row_change_id"] for item in plan["rows"]], [fixture.ROW_ID, fixture.ROW_ID + 1, fixture.ROW_ID + 2])
        self.assertEqual((plan["identity_policy"], plan["physical_confirmation_required"], plan["packing_restored"]),
                         ("fresh_id", True, False))
        self.assertEqual(plan["label"], "3 deleted token-card rows")
        self.assertRegex(plan["expect"], "^[a-f0-9]{64}$")
        self.assertEqual(plan["proof"]["deleted_ids"], [71, 72, 73])
        self.assertEqual((self.store.snapshot, self.store.audit, self.store.writes), (before, audit, []))

    def test_more_than_fifty_rows_are_refused_naming_how_many(self):
        self.seed_batch(batch_rows(51))
        message = self.refusal()
        self.assertIn("51 token-card rows", message)
        self.assertIn("at most 50", message)
        self.seed_batch(batch_rows(50))
        self.assertEqual(self.review()["row_count"], 50)

    def test_any_ineligible_row_refuses_the_whole_batch_naming_how_many_and_why(self):
        rows = batch_rows()
        rows[1] = {**rows[1], "front_collector_number": ""}  # printing not verified
        self.seed_batch(rows)
        message = self.refusal()
        self.assertIn("1 of the 3 deleted token-card rows can't be restored", message)
        self.assertIn(batch.UNVERIFIED + ": 1", message)
        self.assertIn("nothing was restored", message)
        for name in ("Angel", "Treasure", "Beast", "tst"):
            self.assertNotIn(name, message)

    def test_two_rows_that_may_be_one_card_survivor_collisions_and_packed_claims_are_counted(self):
        rows = batch_rows()
        rows[2] = {**rows[0], "quantity": 5}
        self.seed_batch(rows)
        self.assertIn(batch.TWIN + ": 2", self.refusal())
        self.seed_batch(survivors=(self.zombie(),))
        self.built("1 Treasure")
        message = self.refusal()
        self.assertIn("1 of the 3", message)
        self.assertIn(batch.PACKED + ": 1", message)
        self.seed_batch(survivors=(self.zombie(rid=90, front_collector_number="4", back_collector_number="5"),))
        self.store.snapshot = self.store.snapshot.replace(decks={})
        self.assertIn(batch.RECORDED + ": 1", self.refusal())

    def test_current_card_data_is_checked_for_every_row(self):
        calls = []
        def printing(set_code, number):
            calls.append(number)
            return None if number == "4" else {"digital": False, "games": ["paper"], "finishes": ["nonfoil"]}
        with mock.patch.object(cards, "printing", side_effect=printing):
            self.assertIn(batch.CARD_DATA + ": 1", self.refusal())
        self.assertIn("1", calls)

    def test_a_hidden_or_other_row_makes_the_whole_change_missing_before_any_fact_is_checked(self):
        for mutate in (lambda rows: rows[2]["before"].update(space_id="user2"),
                       lambda rows: rows[1].update(table="collection_card"),
                       lambda rows: rows[0].update(op="UPDATE", after={}),
                       lambda rows: rows.append({"id": 999, "table": "token_card", "op": "INSERT", "key": {"id": 5},
                                                 "before": None, "after": {"space_id": "home"}})):
            self.seed_batch()
            mutate(self.store.audit[fixture.CHANGE_ID])
            with self.subTest(mutate=mutate), \
                    mock.patch.object(deleted, "_verified_printing", side_effect=AssertionError("Not an owned source")), \
                    self.assertRaises(undo.UndoMissing):
                self.review()
        self.store.undo_token_latest.reset_mock()
        self.seed_batch()
        self.store.audit[fixture.CHANGE_ID][1]["before"]["space_id"] = "user2"
        with self.assertRaises(undo.UndoMissing):
            self.review()
        self.store.undo_token_latest.assert_not_called()

    def test_another_spaces_batch_is_missing_to_home_even_when_too_large(self):
        self.seed_batch(batch_rows(51), space="user2")
        with self.assertRaises(undo.UndoMissing):
            inventory.undo_review(fixture.CHANGE_ID, "home", self.store.snapshot)

    def test_a_later_touch_or_a_reused_row_id_refuses(self):
        self.latest += 1
        with self.assertRaises(undo.UndoConflict):
            self.review()
        self.seed_batch()
        self.touched[72] += 10
        with self.assertRaises(undo.UndoConflict):
            self.review()
        self.seed_batch()
        self.store.audit[fixture.CHANGE_ID][2]["before"]["id"] = 71
        self.store.audit[fixture.CHANGE_ID][2]["key"] = {"id": 71}
        with self.assertRaises(undo.UndoUnsupported):
            self.review()

    def test_without_the_complete_audit_reader_nothing_is_reviewed(self):
        self.store.undo_audit_rows = None
        with self.assertRaises(undo.UndoUnsupported):
            self.review()


class TokenBatchRestoreTests(TokenBatchFixture):
    def test_confirmed_restore_adds_every_row_under_fresh_ids_and_keeps_survivors(self):
        self.seed_batch(survivors=(self.zombie(),))
        self.built("1 Zombie // Zombie Knight")
        survivor, layout = self.store.snapshot.token_set("home").rows[0], copy.deepcopy(self.layout)
        after, summary = self.run_undo(confirm_owned=True)
        rows = {row.id: row for row in after.token_set("home").rows}
        ids = summary.extra["added_token_row_ids"]
        self.assertEqual(len(ids), 3)
        self.assertEqual(set(rows), {80, *ids})
        self.assertTrue(set(ids).isdisjoint({71, 72, 73, 80}))
        self.assertEqual([{**rows[rid].as_dict(), "quantity": int(rows[rid].quantity)} for rid in ids], self.olds)
        self.assertEqual(rows[80].as_dict(), survivor.as_dict())
        self.assertEqual([item for item in self.layout if item["id"] == 80], layout)
        self.assertNotIn("token_restore", summary.extra)
        self.assertEqual((summary.extra["action"], summary.extra["row_count"], summary.extra["confirmed_owned"]),
                         (batch.ACTION, 3, True))
        self.assertEqual(summary.extra["row_change_ids"], [fixture.ROW_ID, fixture.ROW_ID + 1, fixture.ROW_ID + 2])
        # "cards" is the space's total after the save (the survivor's 3 too); the message names only the 6 restored.
        self.assertEqual((summary.counts["undo"], summary.counts["added_rows"], summary.counts["cards"],
                          summary.counts["restored_cards"]), (1, 3, 9, 6))
        self.assertIn("restore 3 deleted token-card rows (6 physical cards) as new rows", summary.text)
        self.assertNotIn("9 physical cards", summary.text)
        self.assertNotIn("Angel", summary.text)
        self.assertEqual(len(self.store.writes), 1)

    def test_confirmation_is_required_a_reason_is_refused_and_a_replay_is_refused(self):
        expect = self.review()["expect"]
        for extra in ({}, {"confirm_owned": False}, {"confirm_owned": True, "reason": "Fixture"}):
            with self.subTest(extra=extra), self.assertRaises(inventory.Invalid):
                self.run_undo(expect, **extra)
        self.assertEqual(self.store.writes, [])
        self.run_undo(expect, confirm_owned=True)
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect, confirm_owned=True)
        self.assertEqual(len(self.store.writes), 1)

    def test_changes_after_the_preview_refuse_without_writing(self):
        self.seed_batch(survivors=(self.zombie(),))
        expect = self.review()["expect"]
        self.store.snapshot = self.store.snapshot.with_tokens("home", [self.zombie(quantity=4)])
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect, confirm_owned=True)
        self.seed_batch(survivors=(self.zombie(),))
        expect = self.review()["expect"]
        self.layout[0]["position"] += 1
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect, confirm_owned=True)
        self.seed_batch()
        expect = self.review()["expect"]
        self.built("1 Beast // Dog")    # a packed line that now claims one of them
        with self.assertRaises(batch.Refused):
            self.run_undo(expect, confirm_owned=True)
        self.assertEqual(self.store.writes, [])

    def test_a_members_batch_restores_only_there(self):
        home = self.zombie()
        self.store.snapshot = self.store.snapshot.with_tokens("home", [home])
        self.seed_batch(space="user2")
        after, summary = self.run_undo(confirm_owned=True)
        self.assertEqual(len(after.token_set("user2").rows), 3)
        self.assertEqual([(row.id, row.as_dict()) for row in after.token_set("home").rows], [(home.id, home.as_dict())])
        self.assertEqual(summary.extra["space"], "user2")


class TokenBatchProofTests(TokenBatchFixture):
    """The transaction-local proof refuses anything but exactly N fresh INSERTs of the reviewed facts."""

    def setUp(self):
        super().setUp()
        self.seed_batch(survivors=(self.zombie(),))
        self.built("1 Zombie // Zombie Knight")
        self.mutate = None

    def prove(self, before, after, summary, actual, layout):
        if self.mutate is not None:
            after, actual, layout = self.mutate(after, copy.deepcopy(actual), copy.deepcopy(layout))
        return batch.confirm(before, after, summary, actual, layout)

    def refused(self, mutate):
        self.mutate, self.fresh = mutate, FRESH
        expect = self.review()["expect"]
        with self.assertRaises(undo.UndoConflict) as caught:
            self.run_undo(expect, confirm_owned=True)
        self.assertEqual(str(caught.exception), batch.UNCONFIRMED)
        self.assertEqual(self.store.writes, [])

    def test_missing_extra_reused_duplicated_or_changed_rows_are_refused(self):
        mutations = [
            lambda a: a.pop(),
            lambda a: a.append(copy.deepcopy(a[0])),
            lambda a: (a[0]["after"].update(id=71), a[0].update(key={"id": 71})),
            lambda a: (a[0]["after"].update(id=80), a[0].update(key={"id": 80})),
            lambda a: (a[1]["after"].update(id=a[0]["after"]["id"]), a[1].update(key={"id": a[0]["after"]["id"]})),
            lambda a: a[1].update(op="UPDATE"),
            lambda a: a[2]["after"].update(notes="Changed in the database"),
            lambda a: a[2]["after"].update(space_id="user2"),
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
        def reversed_layout(after, actual, layout):
            return after, actual, layout[::-1]
        def survivor(after, actual, layout):
            rows = [row.replace(notes="Edited meanwhile") if row.id == 80 else row for row in after.token_set("home").rows]
            return after.with_tokens("home", rows), actual, layout
        def other_space(after, actual, layout):
            return after.with_tokens("user2", [self.zombie(rid=81)]), actual, layout
        def packing(after, actual, layout):
            from decklab.lib.inventory import model
            text = next(iter(after.decks.values())).text.replace("1 Zombie // Zombie Knight", "1 Angel // The Monarch")
            return after.with_deck(model.Deck("home", "casual", "fixture", text)), actual, layout
        for mutate in (moved, reversed_layout, survivor, other_space, packing):
            with self.subTest(mutate=mutate.__name__):
                self.refused(mutate)

    def test_transaction_hook_reads_one_more_row_than_the_batch_and_the_own_space_layout(self):
        calls = []
        def execute(sql, params):
            calls.append((sql, params))
            return SimpleNamespace(fetchall=lambda: [])
        summary = inventory.Summary("text", {}, {}, {"action": batch.ACTION, "kind": "tokens", "space": "user2",
                                                    "token_restore": {"restore": [{}, {}, {}], "label": "x"}})
        self.assertTrue(deleted.restoring(summary))
        with mock.patch.object(batch, "confirm", return_value="proved") as proved:
            # The single restore's hook (PgInventory.apply's call site) hands a batch on.
            self.assertEqual(deleted.confirm_in_transaction(SimpleNamespace(execute=execute), 55, "before", "saved", summary), "proved")
        self.assertEqual([params for _, params in calls], [(55, 4), ("user2",)])
        self.assertTrue(all(sql.startswith("select ") for sql, _ in calls))
        self.assertIn("change_set_id=%s", calls[0][0])
        self.assertEqual(proved.call_args.args[3:], ([], []))


class PgApplyBatchHookTests(restore_fixture.PgApplyHookTests):
    """PgInventory.apply proves a batch on the write cursor too, and rolls a refused one back."""

    def restore_summary(self):
        return inventory.Summary("text", {}, {}, {"action": batch.ACTION, "kind": "tokens", "space": "home",
                                                 "token_restore": {"restore": [{}, {}], "label": "x"}})

    def test_a_batch_restore_goes_to_the_batch_proof(self):
        summary, proved = self.restore_summary(), inventory.Summary("proved", {}, {}, {})
        with mock.patch.object(batch, "confirm_in_transaction", return_value=proved) as hook:
            self.assertEqual(self.run_op(summary), (self.saved, proved))
        hook.assert_called_once_with(self.cur, 55, self.before, self.saved, summary)
        self.assertEqual(self.rolled_back, [])
