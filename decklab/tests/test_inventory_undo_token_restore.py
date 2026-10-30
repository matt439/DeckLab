"""Restoring a deleted token card under a fresh id, with fake audit rows and disposable stock only.

DatabaseLike stands in for PgInventory.apply: it gives the one id-less row the next
serial id and a persisted position, records its INSERT audit row, then runs the same
transaction-local proof (undo_token_delete.confirm) before "committing". No PostgreSQL,
household data or real card cache is read or changed.
"""
import contextlib
import copy
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import changes, model, undo, undo_token_delete as deleted
from decklab.lib.tokens import ops
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests.test_inventory_undo_token_delete import TARGET, TokenDeleteFixture, token

ADD = ops.add
FRESH = 900


class TokenRestoreFixture(TokenDeleteFixture):
    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.object(ops, "add", ADD))
        self.fresh = FRESH
        self.store.apply = self.database_apply

    def database_apply(self, op, actor, message, reason=None, expected_revision=None):
        before = self.store.snapshot
        after, summary = op.run(changes.detach(before))
        after = changes.prepare(before, after, revision=before.revision + "-undo")
        actual, layout = [], copy.deepcopy(self.layout)
        for space in sorted(after.tokens):
            rows, issued = [], {row.id for row in before.token_set(space).rows}
            for row in after.token_set(space).rows:
                if row.id not in issued:
                    row = model.TokenRow.make(row.as_dict(), id=self.fresh)
                    self.fresh += 1
                rows.append(row)
            after = after.with_tokens(space, rows)
            if space != self.space:
                continue
            ids = [row.id for row in after.token_set(space).rows]
            known = {item["id"]: item["position"] for item in layout}
            layout = []
            for index, rid in enumerate(ids):
                if rid not in known:
                    low = layout[-1]["position"] if layout else 0
                    high = next((known[other] for other in ids[index + 1:] if other in known), low + 2048)
                    known[rid] = (low + high) // 2
                    raw = {"set_code" if key == "set" else key: value
                           for key, value in after.token_set(space).rows[index].as_dict().items()}
                    raw.update(quantity=int(raw["quantity"]), space_id=space, id=rid, position=known[rid])
                    actual.append({"id": self.store.latest + 1, "table": "token_card", "op": "INSERT",
                                   "key": {"id": rid}, "before": None, "after": raw})
                layout.append({"id": rid, "position": known[rid]})
        if deleted.restoring(summary):
            summary = self.prove(before, after, summary, actual, layout)
        self.store.snapshot, self.layout = after, layout
        self.store.writes.append((op, actor, message, summary))
        self.store.latest = self.latest = self.store.latest + 1
        return after, summary

    def prove(self, before, after, summary, actual, layout):
        return deleted.confirm(before, after, summary, actual, layout)

    def run_undo(self, expect=None, **extra):
        expect = self.review()["expect"] if expect is None else expect
        params = {"change_id": fixture.CHANGE_ID, "space": self.space, "expect": expect, **extra}
        return inventory.apply(inventory.Op("inventory.undo", params), inventory.Actor("test", "Fixture"), "Fixture undo")

    def zombie(self, rid=80, **extra):
        values = {"quantity": 3, "front_collector_number": "8", "back_collector_number": "9", **extra}
        return model.TokenRow.make(token("Zombie", "Zombie Knight", **values), id=rid)


class TokenRestoreTests(TokenRestoreFixture):
    def test_confirmed_restore_adds_one_fresh_row_and_keeps_every_survivor(self):
        self.seed(survivors=(self.zombie(),))
        self.built("1 Zombie // Zombie Knight")
        survivor, layout = self.store.snapshot.token_set("home").rows[0], copy.deepcopy(self.layout)
        after, summary = self.run_undo(confirm_owned=True)
        rows = after.token_set("home").rows
        self.assertEqual(len(rows), 2)
        added = next(row for row in rows if row.id != survivor.id)
        self.assertEqual(added.id, FRESH)
        self.assertNotEqual(added.id, TARGET)
        self.assertEqual({**added.as_dict(), "quantity": int(added.quantity)}, self.old)
        kept = next(row for row in rows if row.id == survivor.id)
        self.assertEqual(kept.as_dict(), survivor.as_dict())
        self.assertEqual([item for item in self.layout if item["id"] != FRESH], layout)
        self.assertEqual(summary.extra["added_token_row_id"], FRESH)
        self.assertNotIn("token_restore", summary.extra)
        self.assertEqual((summary.extra["action"], summary.extra["kind"], summary.extra["confirmed_owned"]),
                         (deleted.ACTION, "tokens", True))
        self.assertEqual((summary.extra["undo_of"], summary.extra["row_change_id"]), (fixture.CHANGE_ID, fixture.ROW_ID))
        self.assertEqual((summary.counts["undo"], summary.counts["added_rows"], summary.counts["cards"]), (1, 1, 5))
        self.assertIn("as a new row", summary.text)
        self.assertEqual(len(self.store.writes), 1)

    def test_restore_into_an_empty_space_creates_its_token_list(self):
        self.seed(token("Treasure", "", notes="single-sided verified", quantity=1))
        after, summary = self.run_undo(confirm_owned=True)
        self.assertEqual([row.id for row in after.token_set("home").rows], [FRESH])
        self.assertEqual(summary.counts["cards"], 1)

    def test_whole_count_confirmation_is_required_and_a_reason_is_refused(self):
        expect = self.review()["expect"]
        for extra in ({}, {"confirm_owned": False}, {"confirm_owned": "true"}, {"confirm_owned": True, "reason": "Fixture"}):
            with self.subTest(extra=extra), self.assertRaises(inventory.Invalid):
                self.run_undo(expect, **extra)
        self.assertEqual(self.store.writes, [])
        self.assertEqual(self.store.snapshot.token_set("home").rows, ())

    def test_stale_receipt_and_any_change_after_the_preview_refuse_without_writing(self):
        self.seed(survivors=(self.zombie(),))
        with self.assertRaises(undo.UndoConflict):
            self.run_undo("0" * 64, confirm_owned=True)
        expect = self.review()["expect"]
        self.store.snapshot = self.store.snapshot.with_tokens("home", [self.zombie(quantity=4)])
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect, confirm_owned=True)
        self.seed(survivors=(self.zombie(),))
        expect = self.review()["expect"]
        self.layout[0]["position"] += 1
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect, confirm_owned=True)
        self.seed(survivors=(self.zombie(),))
        expect = self.review()["expect"]
        self.latest += 1  # Another own-space token change after the preview.
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect, confirm_owned=True)
        self.assertEqual(self.store.writes, [])

    def test_a_saved_restore_consumes_its_source_and_cannot_be_replayed(self):
        expect = self.review()["expect"]
        self.run_undo(expect, confirm_owned=True)
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect, confirm_owned=True)
        self.assertEqual(len(self.store.writes), 1)

    def test_a_packed_line_claiming_the_card_refuses_at_apply_too(self):
        self.seed(survivors=(self.zombie(),))
        expect = self.review()["expect"]
        self.built("1 Angel // The Monarch")
        with self.assertRaises(undo.UndoConflict):
            self.run_undo(expect, confirm_owned=True)
        self.assertEqual(self.store.writes, [])

    def test_members_space_restores_only_there_and_home_stock_is_untouched(self):
        home = self.zombie()
        self.store.snapshot = self.store.snapshot.with_tokens("home", [home])
        self.seed(space="user2")
        after, summary = self.run_undo(confirm_owned=True)
        self.assertEqual([row.id for row in after.token_set("user2").rows], [FRESH])
        self.assertEqual([(row.id, row.as_dict()) for row in after.token_set("home").rows], [(home.id, home.as_dict())])
        self.assertEqual(summary.extra["space"], "user2")
        self.assertNotIn("home", summary.text)

    def test_another_spaces_source_is_missing_to_this_space(self):
        self.seed(space="user2")
        with self.assertRaises(undo.UndoMissing):
            inventory.Op("inventory.undo", {"change_id": fixture.CHANGE_ID, "space": "home", "expect": "0" * 64,
                                            "confirm_owned": True}).run(self.store.snapshot)
        self.assertEqual(self.store.writes, [])


class TokenRestoreProofTests(TokenRestoreFixture):
    """The transaction-local proof refuses anything but one exact fresh INSERT."""

    def setUp(self):
        super().setUp()
        self.seed(survivors=(self.zombie(),))
        self.built("1 Zombie // Zombie Knight")
        self.mutate = None

    def prove(self, before, after, summary, actual, layout):
        if self.mutate is not None:
            after, actual, layout = self.mutate(after, copy.deepcopy(actual), copy.deepcopy(layout))
        return deleted.confirm(before, after, summary, actual, layout)

    def refused(self, mutate):
        self.mutate, self.fresh = mutate, FRESH
        expect = self.review()["expect"]
        with self.assertRaises(undo.UndoConflict) as caught:
            self.run_undo(expect, confirm_owned=True)
        self.assertEqual(str(caught.exception), deleted.UNCONFIRMED)
        self.assertEqual(self.store.writes, [])

    def test_reused_deleted_id_is_refused(self):
        def reuse(after, actual, layout):
            actual[0]["after"]["id"] = TARGET
            actual[0]["key"] = {"id": TARGET}
            return after, actual, layout
        self.refused(reuse)

    def test_survivor_id_extra_audit_rows_other_ops_and_changed_facts_are_refused(self):
        mutations = [
            lambda a: (a[0]["after"].update(id=80), a[0].update(key={"id": 80})),
            lambda a: a.append(copy.deepcopy(a[0])),
            lambda a: a.clear(),
            lambda a: a[0].update(op="UPDATE"),
            lambda a: a[0].update(before={}),
            lambda a: a[0].update(key={"id": FRESH + 1}),
            lambda a: a[0]["after"].update(notes="Changed in the database"),
            lambda a: a[0]["after"].update(space_id="user2"),
            lambda a: a[0]["after"].update(extra="column"),
            lambda a: a[0]["after"].update(id=True),
        ]
        for change in mutations:
            def mutate(after, actual, layout, change=change):
                change(actual)
                return after, actual, layout
            with self.subTest(change=change):
                self.store.writes.clear()
                self.refused(mutate)

    def test_moved_survivor_or_missing_new_position_is_refused(self):
        for change in (lambda layout: layout[0].update(position=layout[0]["position"] + 1),
                       lambda layout: layout.reverse(),
                       lambda layout: layout.pop(next(i for i, item in enumerate(layout) if item["id"] == FRESH)),
                       lambda layout: [item.update(position=item["position"] + 5) for item in layout if item["id"] == FRESH]):
            def mutate(after, actual, layout, change=change):
                change(layout)
                return after, actual, layout
            with self.subTest(change=change):
                self.refused(mutate)

    def test_changed_survivor_other_space_or_packing_in_the_saved_snapshot_is_refused(self):
        def survivor(after, actual, layout):
            rows = [row.replace(notes="Edited meanwhile") if row.id == 80 else row for row in after.token_set("home").rows]
            return after.with_tokens("home", rows), actual, layout
        def other_space(after, actual, layout):
            return after.with_tokens("user2", [self.zombie(rid=81)]), actual, layout
        def packing(after, actual, layout):
            text = next(iter(after.decks.values())).text.replace("1 Zombie // Zombie Knight", "1 Angel // The Monarch")
            return after.with_deck(model.Deck("home", "casual", "fixture", text)), actual, layout
        for mutate in (survivor, other_space, packing):
            with self.subTest(mutate=mutate.__name__):
                self.refused(mutate)

    def test_transaction_hook_reads_only_this_change_sets_rows_and_own_space_layout(self):
        calls = []
        def execute(sql, params):
            calls.append((sql, params))
            return SimpleNamespace(fetchall=lambda: [])
        summary = inventory.Summary("text", {}, {}, {"action": deleted.ACTION, "kind": "tokens", "space": "user2",
                                                    "token_restore": {"restore": {}, "label": "x"}})
        with mock.patch.object(deleted, "confirm", return_value="proved") as proved:
            self.assertEqual(deleted.confirm_in_transaction(SimpleNamespace(execute=execute), 55, "before", "saved", summary), "proved")
        self.assertEqual([params for _, params in calls], [(55,), ("user2",)])
        self.assertTrue(all(sql.startswith("select ") for sql, _ in calls))
        self.assertIn("change_set_id=%s", calls[0][0])
        self.assertIn("where space_id=%s", calls[1][0])
        self.assertEqual(proved.call_args.args[3:], ([], []))
        self.assertTrue(deleted.restoring(summary))
        self.assertFalse(deleted.restoring(inventory.Summary("text", {}, {}, {"action": "add", "kind": "tokens"})))


class PgApplyHookTests(unittest.TestCase):
    """PgInventory.apply itself runs the proof inside the write, with no database at all.

    The fixtures above stand in for apply, so this pins its call site: removing the hook,
    or a summary it no longer recognises, fails here rather than only on PostgreSQL."""

    def setUp(self):
        from decklab.lib.inventory import pg
        self.pg = pg
        self.store = pg.PgInventory.__new__(pg.PgInventory)
        self.store._lock, self.store._applying = threading.Lock(), threading.local()
        self.store._cache = self.store._decks = None
        self.cur, self.connection = SimpleNamespace(execute=mock.Mock()), object()
        self.before, self.saved, self.stored = object(), object(), object()
        self.rolled_back = []

        @contextlib.contextmanager
        def change(actor, source, message, reason=None, conn=None, via=None):
            try:
                yield self.cur, 55
            except BaseException:
                self.rolled_back.append(True)
                raise

        joined = {self.stored: self.before, "saved inventory": self.saved}
        for target, name, value in (
                (pg.db, "change", change), (pg, "_take_lock", mock.Mock()), (pg.space_members, "admit", mock.Mock()),
                (pg.changes, "detach", lambda inv: inv), (pg.changes, "prepare", lambda before, after: after),
                (pg.changes, "changed", lambda before, after: []), (pg.changes, "changed_paths", lambda before, after: []),
                (pg.pg_decks, "without_deck_parts", lambda inv: inv), (pg, "tables", lambda inv: {"new": 1}),
                (pg, "_diff", lambda cur, old, new: 1), (pg, "_add_imports", lambda cur, imports: 0),
                (pg, "_select", lambda c: "rows"), (pg, "snapshot", lambda rows, revision: "saved inventory"),
                (self.store, "_call", lambda work: work(self.connection)),
                (self.store, "_read", lambda c: self.stored), (self.store, "_read_decks", lambda c: (None, None)),
                (self.store, "_join", lambda inv, key, part: joined[inv]), (self.store, "_tables", lambda inv: {"old": 1}),
                (self.store, "_key", lambda c: (1, 1, "2"))):
            self.enterContext(mock.patch.object(target, name, value))

    def run_op(self, summary):
        op = SimpleNamespace(kind="fixture", run=lambda snapshot: ("after", summary))
        return self.store.apply(op, inventory.Actor("test", "Fixture"), "Fixture restore")

    def restore_summary(self):
        return inventory.Summary("text", {}, {}, {"action": deleted.ACTION, "kind": "tokens", "space": "home",
                                                 "token_restore": {"restore": {}, "label": "x"}})

    def test_a_restore_is_proved_on_the_write_cursor_before_it_returns(self):
        summary, proved = self.restore_summary(), inventory.Summary("proved", {}, {}, {})
        with mock.patch.object(deleted, "confirm_in_transaction", return_value=proved) as hook:
            self.assertEqual(self.run_op(summary), (self.saved, proved))
        hook.assert_called_once_with(self.cur, 55, self.before, self.saved, summary)
        self.assertEqual(self.rolled_back, [])

    def test_a_failed_proof_raises_inside_the_change_so_it_rolls_back(self):
        refused = undo.UndoConflict(deleted.UNCONFIRMED, "x")
        with mock.patch.object(deleted, "confirm_in_transaction", side_effect=refused), \
                self.assertRaises(undo.UndoConflict):
            self.run_op(self.restore_summary())
        self.assertEqual(self.rolled_back, [True])

    def test_an_ordinary_token_write_is_not_proved(self):
        summary = inventory.Summary("text", {}, {}, {"action": "add", "kind": "tokens"})
        with mock.patch.object(deleted, "confirm_in_transaction") as hook:
            self.assertEqual(self.run_op(summary), (self.saved, summary))
        hook.assert_not_called()
