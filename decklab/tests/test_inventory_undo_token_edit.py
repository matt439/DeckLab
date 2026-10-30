"""Restoring 1-50 edited token-card rows of one change in place, with fake audit rows and disposable stock only.

DatabaseLike stands in for PgInventory.apply: it records an UPDATE audit row for every token row
the undo changed (with its unchanged persisted position), keeps the layout, then runs the
transaction-local proof before "committing". No PostgreSQL, household data or real card cache
is read or changed.
"""
import copy
from types import SimpleNamespace
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import changes, model, rules, undo, undo_token_edit as edit
from decklab.lib.state import Invalid
from decklab.lib.tokens import names
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests import test_inventory_undo_token_restore as restore_fixture
from decklab.tests.test_inventory_undo_token_batch import batch_rows

FIRST = 7


def raw(row, space, rid, position):
    out = {"set_code" if key == "set" else key: value for key, value in row.items()}
    out.update(space_id=space, id=rid, position=position)
    return out


def recorded(rows):
    """What the edited rows held before the change: a notes and quantity edit, a details edit and a raise."""
    olds = copy.deepcopy(rows)
    olds[0].update(quantity=5, notes="Recorded pairing note")
    if len(olds) > 1:
        olds[1].update(front_details="1/1; colourless")
    if len(olds) > 2:
        olds[2].update(quantity=1)
    for old in olds[3:]:
        old.update(notes="Recorded spirit note")
    return olds


class TokenEditFixture(unittest.TestCase):
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
        self.checked = mock.Mock(side_effect=lambda row: (dict(row), []))
        self.enterContext(mock.patch.object(names, "check_names", self.checked))
        self.store.apply = self.database_apply
        self.mutate = None
        self.seed()

    def seed(self, rows=None, olds=None, survivors=(), *, space="home"):
        """rows (ids 7, 8, ...) now hold rows; one change edited them from olds."""
        self.space = space
        self.rows = copy.deepcopy(batch_rows() if rows is None else rows)
        self.olds = recorded(self.rows) if olds is None else copy.deepcopy(olds)
        made = [model.TokenRow.make(row, id=FIRST + index) for index, row in enumerate(self.rows)]
        self.store.snapshot = self.store.snapshot.with_tokens(space, [*survivors, *made])
        self.layout = [{"id": row.id, "position": (index + 1) * 1024}
                       for index, row in enumerate(self.store.snapshot.token_set(space).rows)]
        positions = {item["id"]: item["position"] for item in self.layout}
        audit, self.touched = [], {row.id: 50 for row in survivors}
        for index, (row, old) in enumerate(zip(self.rows, self.olds)):
            rid = FIRST + index
            audit.append({"id": fixture.ROW_ID + index, "table": "token_card", "op": "UPDATE", "key": {"id": rid},
                          "before": raw(old, space, rid, positions[rid]), "after": raw(row, space, rid, positions[rid])})
            self.touched[rid] = fixture.ROW_ID + index
        self.store.audit[fixture.CHANGE_ID] = audit
        self.store.latest = fixture.ROW_ID + len(self.rows) - 1

    def database_apply(self, op, actor, message, reason=None, expected_revision=None):
        before = self.store.snapshot
        after, summary = op.run(changes.detach(before))
        after = changes.prepare(before, after, revision=before.revision + "-undo")
        positions = {item["id"]: item["position"] for item in self.layout}
        olds = {row.id: row for row in before.token_set(self.space).rows}
        actual = []
        for row in after.token_set(self.space).rows:
            old = olds.get(row.id)
            if old is not None and old.as_dict() != row.as_dict():
                actual.append({"id": self.store.latest + 1 + len(actual), "table": "token_card", "op": "UPDATE", "key": {"id": row.id},
                               "before": raw({**old.as_dict(), "quantity": int(old.quantity)}, self.space, row.id, positions[row.id]),
                               "after": raw({**row.as_dict(), "quantity": int(row.quantity)}, self.space, row.id, positions[row.id])})
        layout = copy.deepcopy(self.layout)
        if edit.restoring(summary):
            if self.mutate is not None:
                after, actual, layout = self.mutate(after, copy.deepcopy(actual), copy.deepcopy(layout))
            summary = edit.confirm(before, after, summary, actual, layout)
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
        with self.assertRaises(edit.Refused) as caught:
            self.review()
        return str(caught.exception)

    def stock(self):
        return [(row.id, {**row.as_dict(), "quantity": int(row.quantity)}) for row in self.store.snapshot.token_set(self.space).rows]

    built = restore_fixture.TokenRestoreFixture.built
    product = restore_fixture.TokenRestoreFixture.product
    zombie = restore_fixture.TokenRestoreFixture.zombie


class TokenEditReviewTests(TokenEditFixture):
    def test_review_lists_every_row_and_its_changed_fields_without_writing(self):
        before, audit, layout = self.store.snapshot, copy.deepcopy(self.store.audit), copy.deepcopy(self.layout)
        plan = self.review()
        self.assertEqual((plan["action"], plan["kind"], plan["row_count"], plan["label"]),
                         (edit.ACTION, "tokens", 3, "Updates to 3 token-card rows"))
        self.assertEqual([item["current"] for item in plan["rows"]], self.rows)
        self.assertEqual([item["restore"] for item in plan["rows"]], self.olds)
        self.assertEqual([item["token_row_id"] for item in plan["rows"]], [7, 8, 9])
        self.assertEqual([item["label"] for item in plan["rows"]], ["Angel / The Monarch", "Treasure", "Beast / Dog"])
        self.assertEqual([[field["field"] for field in item["fields"]] for item in plan["rows"]],
                         [["quantity", "notes"], ["front_details"], ["quantity"]])
        self.assertNotIn("reason_required", plan)
        self.assertRegex(plan["expect"], "^[a-f0-9]{64}$")
        self.assertEqual((self.store.snapshot, self.store.audit, self.layout, self.store.writes), (before, audit, layout, []))
        self.checked.assert_not_called()    # No face or printing changes: the names it holds now stay.

    def test_one_row_beyond_quantity_and_notes_is_reviewed_here_with_singular_words(self):
        self.seed(batch_rows(1), [{**batch_rows(1)[0], "front_details": "4/4; white; flying"}])
        plan = self.review()
        self.assertEqual((plan["action"], plan["row_count"], plan["label"]), (edit.ACTION, 1, "Updates to 1 token-card row"))
        self.store.audit[fixture.CHANGE_ID][0]["before"]["position"] += 1
        message = self.refusal()
        self.assertIn("1 of the 1 updated token-card row can't be restored", message)
        self.assertIn(edit.MOVED + ": 1", message)

    def test_a_single_quantity_or_notes_edit_keeps_the_older_single_row_inverse(self):
        self.seed(batch_rows(1))
        self.assertFalse(edit.looks_like(self.store.audit[fixture.CHANGE_ID]))
        plan = self.review()
        self.assertNotIn("action", plan)
        self.assertEqual([field["field"] for field in plan["fields"]], ["quantity", "notes"])

    def test_more_than_fifty_rows_are_refused_naming_how_many(self):
        self.seed(batch_rows(51))
        message = self.refusal()
        self.assertIn("51 token-card rows", message)
        self.assertIn("at most 50", message)
        self.seed(batch_rows(50))
        self.assertEqual(self.review()["row_count"], 50)

    def test_an_edited_moved_or_removed_row_refuses_the_whole_change_naming_only_counts_and_reasons(self):
        self.touched[8] += 10  # Edited after the change.
        message = self.refusal()
        self.assertIn("1 of the 3 updated token-card rows can't be restored", message)
        self.assertIn(edit.EDITED + ": 1", message)
        self.assertIn("nothing was restored", message)
        for name in ("Angel", "Treasure", "Beast", "tst", "Recorded"):
            self.assertNotIn(name, message)
        self.seed()
        rows = [row for row in self.store.snapshot.token_set("home").rows if row.id != 9]
        self.store.snapshot = self.store.snapshot.with_tokens("home", [*rows, model.TokenRow.make(
            {**self.rows[2], "notes": "Edited without an audit fence"}, id=9)])
        self.assertIn(edit.EDITED + ": 1", self.refusal())
        self.seed()
        self.layout[0]["position"] += 1
        self.assertIn(edit.EDITED + ": 1", self.refusal())
        self.seed()
        self.store.snapshot = self.store.snapshot.with_tokens("home", self.store.snapshot.token_set("home").rows[1:])
        self.layout = self.layout[1:]
        self.assertIn(edit.EDITED + ": 1", self.refusal())
        self.seed()
        self.store.audit[fixture.CHANGE_ID][1]["before"]["position"] = 1
        self.assertIn(edit.MOVED + ": 1", self.refusal())

    def test_invalid_or_unchecked_recorded_values_are_counted(self):
        olds = recorded(batch_rows())
        olds[0]["notes"] = "x" * 501
        self.seed(olds=olds)
        self.assertIn("1 of the 3 updated token-card rows can't be restored (" + edit.INVALID + ": 1)", self.refusal())
        olds = recorded(batch_rows())
        olds[0]["front"], olds[1]["front"] = "Angel Map", "Treasure Map"
        self.seed(olds=olds)
        self.checked.side_effect = ValueError("'Treasure Map' isn't a token")
        message = self.refusal()
        self.assertIn("2 of the 3", message)
        self.assertIn(edit.INVALID + ": 2", message)
        self.assertNotIn("Treasure", message)
        self.checked.side_effect = lambda row: (dict(row), [names.NAMES_UNCHECKED])
        self.assertIn(edit.CARD_DATA + ": 2", self.refusal())
        self.checked.side_effect = lambda row: ({**row, "front": "Treasure"}, [])
        self.assertIn(edit.INVALID + ": 2", self.refusal())
        self.assertEqual(self.checked.call_count, 6)    # Only the two rows whose faces change are checked.

    def test_a_restore_naming_another_fully_known_card_or_moving_in_the_list_is_counted(self):
        olds = recorded(batch_rows())
        olds[1] = {**self.rows[0], "quantity": 1}   # Treasure was recorded as another Angel / The Monarch.
        self.seed(olds=olds)
        message = self.refusal()
        self.assertIn(edit.DUPLICATE + ": 1", message)
        olds[1] = {**olds[1], "notes": "pairing unconfirmed"}   # Not fully known: kept apart, as --separate.
        self.seed(olds=olds)
        self.assertEqual(self.review()["row_count"], 3)
        olds = recorded(batch_rows())
        olds[1] = {**olds[1], "front_collector_number": "9"}
        self.seed(olds=olds)
        message = self.refusal()
        self.assertIn(edit.ORDER + ": ", message)
        self.assertNotIn(edit.DUPLICATE, message)

    def test_packed_lines_that_would_lose_cards_or_change_are_counted_and_a_raise_is_not(self):
        self.built("2 Beast // Dog")
        message = self.refusal()        # Beast / Dog would go back to 1 card while 2 are packed.
        self.assertIn("1 of the 3", message)
        self.assertIn(edit.PACKED + ": 1", message)
        self.assertNotIn("Beast", message)
        olds = recorded(batch_rows())
        olds[2]["quantity"] = 5
        self.seed(olds=olds)
        self.built("2 Beast // Dog")
        self.assertEqual(self.review()["row_count"], 3)
        self.seed()
        self.built(None)                # Unknown packing can't be checked for a reduction or details change.
        with self.assertRaises(undo.UndoConflict):
            self.review()
        notes_only = [{**row, "notes": "Older note"} for row in batch_rows()]
        self.seed(olds=notes_only)
        self.built(None)                # ...but a notes edit never changes what a line holds.
        self.assertEqual(self.review()["row_count"], 3)

    def test_a_hidden_or_other_row_makes_the_whole_change_missing_before_any_fact_is_checked(self):
        for mutate in (lambda rows: rows[2]["after"].update(space_id="user2"),
                       lambda rows: rows[1]["before"].update(space_id="user2"),
                       lambda rows: rows[1].update(table="collection_card"),
                       lambda rows: rows[0].update(op="DELETE", after=None),
                       lambda rows: rows.append({"id": 999, "table": "token_card", "op": "INSERT", "key": {"id": 5},
                                                 "before": None, "after": {"space_id": "home"}})):
            self.seed()
            mutate(self.store.audit[fixture.CHANGE_ID])
            with self.subTest(mutate=mutate), \
                    mock.patch.object(edit, "_parse", side_effect=AssertionError("Not an owned source")), \
                    self.assertRaises(undo.UndoMissing):
                self.review()
        self.store.undo_token_positions.reset_mock()
        self.seed(space="user2")
        with self.assertRaises(undo.UndoMissing):
            inventory.undo_review(fixture.CHANGE_ID, "home", self.store.snapshot)
        self.store.undo_token_positions.assert_not_called()
        self.seed(batch_rows(51), space="user2")
        with self.assertRaises(undo.UndoMissing):
            inventory.undo_review(fixture.CHANGE_ID, "home", self.store.snapshot)

    def test_a_row_named_twice_or_no_complete_audit_reader_refuses(self):
        self.store.audit[fixture.CHANGE_ID][2]["after"]["id"] = 7
        self.store.audit[fixture.CHANGE_ID][2]["before"]["id"] = 7
        self.store.audit[fixture.CHANGE_ID][2]["key"] = {"id": 7}
        with self.assertRaises(undo.UndoUnsupported):
            self.review()
        self.seed()
        self.store.undo_audit_rows = None
        with self.assertRaises(undo.UndoUnsupported):
            self.review()


class TokenEditRestoreTests(TokenEditFixture):
    def test_restore_writes_every_recorded_value_back_in_place_and_keeps_a_packed_survivor(self):
        self.seed(survivors=(self.zombie(),))
        self.built("1 Zombie // Zombie Knight")
        layout = copy.deepcopy(self.layout)
        after, summary = self.run_undo()
        stock = dict(self.stock())
        self.assertEqual([stock[FIRST + index] for index in range(3)], self.olds)
        self.assertEqual(stock[80]["quantity"], 3)
        self.assertEqual([row.id for row in after.token_set("home").rows], [7, 8, 9, 80])
        self.assertEqual(self.layout, layout)
        self.assertEqual(summary.extra["restored_token_row_ids"], [7, 8, 9])
        self.assertNotIn("token_edit", summary.extra)
        self.assertEqual((summary.extra["action"], summary.extra["row_count"], summary.extra["kind"]), (edit.ACTION, 3, "tokens"))
        self.assertEqual(summary.extra["row_change_ids"], [fixture.ROW_ID, fixture.ROW_ID + 1, fixture.ROW_ID + 2])
        self.assertEqual(summary.counts, {"edited": 3, "cards": 3 + 5 + 1 + 1, "undo": 1})
        self.assertEqual(summary.text, f"Undo change #{fixture.CHANGE_ID}: restore Updates to 3 token-card rows")
        self.assertEqual(list(summary.changed.values()), [["front_details", "notes", "quantity"]])
        self.assertEqual(len(self.store.writes), 1)

    def test_a_reason_or_confirmation_is_refused_and_a_replay_too(self):
        expect = self.review()["expect"]
        for extra in ({"reason": "Because"}, {"confirm_owned": True}):
            with self.subTest(extra=extra), self.assertRaises(Invalid):
                self.run_undo(expect, **extra)
        self.assertEqual(self.store.writes, [])
        self.run_undo(expect)
        with self.assertRaises(inventory.Invalid):  # Its source rows are now touched by the undo.
            self.run_undo(expect)
        self.assertEqual(len(self.store.writes), 1)

    def test_changes_after_the_preview_refuse_without_writing(self):
        self.seed(survivors=(self.zombie(),))
        expect = self.review()["expect"]
        self.store.snapshot = self.store.snapshot.with_tokens("home", [
            *(row for row in self.store.snapshot.token_set("home").rows if row.id != 80), self.zombie(quantity=4)])
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect)
        self.seed()
        expect = self.review()["expect"]
        self.built("2 Beast // Dog")
        with self.assertRaises(edit.Refused):
            self.run_undo(expect)
        self.seed()
        self.store.snapshot = self.store.snapshot.replace(decks={})
        expect = self.review()["expect"]
        self.store.snapshot = self.store.snapshot.replace(decks_revision="changed")
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect)
        self.assertEqual(self.store.writes, [])

    def test_a_members_change_is_restored_only_there(self):
        home = self.zombie()
        self.store.snapshot = self.store.snapshot.with_tokens("home", [home])
        self.seed(space="user2")
        after, summary = self.run_undo()
        self.assertEqual([dict(self.stock())[FIRST + index] for index in range(3)], self.olds)
        self.assertEqual([(row.id, row.as_dict()) for row in after.token_set("home").rows], [(home.id, home.as_dict())])
        self.assertEqual(summary.extra["space"], "user2")


class TokenEditProofTests(TokenEditFixture):
    """The transaction-local proof refuses anything but exactly the reviewed N UPDATEs."""

    def setUp(self):
        super().setUp()
        self.seed(survivors=(self.zombie(),))
        self.built("1 Zombie // Zombie Knight")

    def refused(self, mutate):
        self.mutate = mutate
        expect = self.review()["expect"]
        with self.assertRaises(undo.UndoConflict) as caught:
            self.run_undo(expect)
        self.assertEqual(str(caught.exception), edit.UNCONFIRMED)
        self.assertEqual(self.store.writes, [])

    def test_missing_extra_other_duplicated_or_changed_rows_are_refused(self):
        survivor = {"id": 999, "table": "token_card", "op": "UPDATE", "key": {"id": 80},
                    "before": raw({**self.zombie().as_dict(), "quantity": 3}, "home", 80, 1024),
                    "after": raw({**self.zombie().as_dict(), "quantity": 4}, "home", 80, 1024)}
        mutations = [
            lambda a: a.pop(),
            lambda a: a.append(copy.deepcopy(a[0])),
            lambda a: a.__setitem__(0, survivor),
            lambda a: a.__setitem__(1, copy.deepcopy(a[0])),
            lambda a: a[1].update(op="DELETE"),
            lambda a: a[1].update(table="collection_card"),
            lambda a: a[2]["after"].update(notes="Changed in the database"),
            lambda a: a[2]["after"].update(position=1),
            lambda a: a[2]["before"].update(quantity=2),
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
            layout[1]["position"] += 1
            return after, actual, layout
        def survivor(after, actual, layout):
            rows = [row.replace(notes="Edited meanwhile") if row.id == 80 else row for row in after.token_set("home").rows]
            return after.with_tokens("home", rows), actual, layout
        def restored(after, actual, layout):
            rows = [row.replace(notes="Not the recorded note") if row.id == 7 else row for row in after.token_set("home").rows]
            return after.with_tokens("home", rows), actual, layout
        def other_space(after, actual, layout):
            return after.with_tokens("user2", [self.zombie(rid=81)]), actual, layout
        def collection(after, actual, layout):
            return after.with_collection("home", []), actual, layout
        def packing(after, actual, layout):
            text = next(iter(after.decks.values())).text.replace("1 Zombie // Zombie Knight", "")
            return after.with_deck(model.Deck("home", "casual", "fixture", text)), actual, layout
        for mutate in (moved, survivor, restored, other_space, collection, packing):
            with self.subTest(mutate=mutate.__name__):
                self.refused(mutate)

    def test_transaction_hook_reads_one_more_row_than_the_change_and_the_own_space_layout(self):
        calls = []
        def execute(sql, params):
            calls.append((sql, params))
            return SimpleNamespace(fetchall=lambda: [])
        summary = inventory.Summary("text", {}, {}, {"action": edit.ACTION, "kind": "tokens", "space": "user2",
                                                    "token_edit": {"rows": [{}, {}, {}], "label": "x"}})
        self.assertTrue(edit.restoring(summary))
        self.assertFalse(edit.restoring(inventory.Summary("text", {}, {}, {"action": edit.ACTION, "kind": "tokens"})))
        with mock.patch.object(edit, "confirm", return_value="proved") as proved:
            self.assertEqual(edit.confirm_in_transaction(SimpleNamespace(execute=execute), 55, "before", "saved", summary), "proved")
        self.assertEqual([params for _, params in calls], [(55, 4), ("user2",)])
        self.assertTrue(all(sql.startswith("select ") for sql, _ in calls))
        self.assertEqual(proved.call_args.args[3:], ([], []))


class PgApplyTokenEditHookTests(restore_fixture.PgApplyHookTests):
    """PgInventory.apply proves a token-card edit restore on the write cursor too, and rolls a refused one back."""

    def restore_summary(self):
        return inventory.Summary("text", {}, {}, {"action": edit.ACTION, "kind": "tokens", "space": "home",
                                                 "token_edit": {"rows": [{}], "label": "x"}})

    def test_a_restore_is_proved_on_the_write_cursor_before_it_returns(self):
        summary, proved = self.restore_summary(), inventory.Summary("proved", {}, {}, {})
        with mock.patch.object(edit, "confirm_in_transaction", return_value=proved) as hook:
            self.assertEqual(self.run_op(summary), (self.saved, proved))
        hook.assert_called_once_with(self.cur, 55, self.before, self.saved, summary)
        self.assertEqual(self.rolled_back, [])

    def test_a_failed_proof_raises_inside_the_change_so_it_rolls_back(self):
        refused = undo.UndoConflict(edit.UNCONFIRMED, "x")
        with mock.patch.object(edit, "confirm_in_transaction", side_effect=refused), \
                self.assertRaises(undo.UndoConflict):
            self.run_op(self.restore_summary())
        self.assertEqual(self.rolled_back, [True])

    def test_an_ordinary_token_write_is_not_proved(self):
        summary = inventory.Summary("text", {}, {}, {"action": "edit", "kind": "tokens"})
        with mock.patch.object(edit, "confirm_in_transaction") as hook:
            self.assertEqual(self.run_op(summary), (self.saved, summary))
        hook.assert_not_called()
