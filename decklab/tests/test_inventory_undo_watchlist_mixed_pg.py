"""Undoing a mixed purchase-queue change writes only to a guarded disposable PostgreSQL database.

These run the real PgInventory.apply, so the mixed queue Undo's pre-commit proof
(undo_watchlist_mixed.confirm_in_transaction) reads this change set's own audit rows and the
queue's persisted positions. No card cache, retailer or household data is read."""
from unittest import mock

from decklab.lib import config, inventory
from decklab.lib.inventory import Op, undo, undo_watchlist_mixed as mixed
from decklab.tests import test_inventory_undo_pg as existing
from decklab.tests import test_inventory_undo_watchlist_rows_pg as rows_pg
from decklab.tests.test_inventory_undo_watchlist import row


class WatchlistMixedUndoPgTests(rows_pg.WatchlistRowsUndoPgTests):
    # Only this class's cases run here; the other slices' run in their own modules.
    test_added_rows_are_removed_as_exactly_their_deletes_with_survivors_unmoved = None
    test_removed_rows_come_back_as_exactly_their_inserts_under_fresh_ids_where_they_were = None
    test_single_set_add_and_remove_are_undone_and_a_tampered_proof_rolls_back = None

    def ops(self, source):
        return sorted(op for op, in self.sql("select op from audit.row_change where change_set_id=%s", (source,)))

    def test_a_shop_check_that_edited_added_and_removed_rows_is_undone_by_exactly_its_inverse(self):
        first = self.first()
        self.queue(first, "Fixture queue")
        layout = dict(self.layout())
        checked = [first[0], {**first[1], "notes": "Checked queue note"}, first[2], row("Fixture card 3")]
        source = self.queue(checked, "Fixture shop check editing, adding and removing")
        self.assertEqual(self.ops(source), ["DELETE", "INSERT", "UPDATE"])
        plan = inventory.undo_review(source, "home")
        self.assertEqual((plan["action"], plan["row_count"], plan["counts"]), (mixed.ACTION, 3, {"updated": 1, "added": 1, "removed": 1}))
        before = self.persisted()
        with mock.patch.object(mixed, "confirm_in_transaction", wraps=mixed.confirm_in_transaction) as hook:
            after, summary = self.undo(source, plan, reason="Shop check mistake")
        hook.assert_called_once()
        self.assertEqual(sorted(op for _, op, _ in self.made()), ["DELETE", "INSERT", "UPDATE"])
        self.assertEqual([item.as_dict() for item in after.watchlist.rows], first)
        new = summary.extra["added_watch_row_ids"]
        self.assertTrue(set(new).isdisjoint(layout))
        now = dict(self.layout())
        survivors = [rid for rid in layout if rid in now]
        self.assertEqual(len(survivors), 3)
        self.assertEqual({rid: now[rid] for rid in survivors}, {rid: layout[rid] for rid in survivors})
        self.assertEqual(self.sql("select reason from audit.change_set where id=(select max(id) from audit.change_set)"),
                         [("Shop check mistake",)])
        saved = self.persisted()
        for table in ("collection_card", "token_card", "deck", "deck_text", "deck_line", "decks_revision"):
            self.assertEqual(saved[table], before[table], table)
        with self.assertRaises((inventory.Invalid, inventory.Conflict)):
            self.undo(source, plan, reason="Again")
        self.assertEqual(self.persisted(), saved)

    def test_add_many_that_added_and_raised_is_undone_and_a_tampered_proof_rolls_back(self):
        self.queue(self.first()[:2], "Fixture queue")
        inventory.apply(Op("watchlist.add_many", {"rows": [{"name": "Sol Ring", "quantity": "1"}, {"name": "Fixture card 3"}],
                                                   "repo": str(config.REPO)}), existing.ACTOR, "Fixture add many")
        source = self.source("watchlist_item")
        self.assertEqual(self.ops(source), ["INSERT", "UPDATE"])
        before = self.persisted()
        real = mixed.confirm
        def tampered(before_inv, saved, summary, actual, layout):
            return real(before_inv, saved, summary, actual, layout[:-1])   # As if a survivor had moved.
        with mock.patch.object(mixed, "confirm", side_effect=tampered), self.assertRaises(undo.UndoConflict) as caught:
            self.undo(source, reason="Not wanted")
        self.assertEqual(str(caught.exception), mixed.UNCONFIRMED)
        self.assertEqual(self.persisted(), before)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))
        after, summary = self.undo(source, reason="Not wanted")
        self.assertEqual(summary.counts, {"edited": 1, "removed_rows": 1, "undo": 1})
        self.assertEqual([item.as_dict() for item in after.watchlist.rows], self.first()[:2])
