"""Removing added purchase-queue rows, or restoring removed ones, writes only to a guarded disposable PostgreSQL database.

These run the real PgInventory.apply, so the queue Undo's pre-commit proof
(undo_watchlist_rows.confirm_in_transaction) reads this change set's own audit rows and the
queue's persisted positions. No card cache, retailer or household data is read."""
from unittest import mock

from decklab.lib import config, inventory
from decklab.lib.inventory import Op, undo, undo_watchlist_rows as rows_undo
from decklab.tests import test_inventory_undo_pg as existing
from decklab.tests.test_inventory_undo_watchlist import row
from decklab.tests import test_inventory_undo_watchlist_pg as update_pg


class WatchlistRowsUndoPgTests(update_pg.WatchlistUndoPgTests):
    # Only this class's cases run here; the update slice's run in their own module.
    test_undo_is_exactly_two_updates_with_positions_and_history_kept = None
    test_a_single_row_set_is_undone_in_place = None
    test_a_later_touch_refuses_and_a_tampered_proof_rolls_back = None

    def queue(self, rows, message):
        inventory.apply(Op("watchlist.replace", {"rows": rows, "repo": str(config.REPO)}), existing.ACTOR, message)
        return self.source("watchlist_item")

    def first(self):
        return [row("Sol Ring"), row("Fixture card 1", notes="Recorded queue note"), row("Arcane Signet"),
                row("Fixture card 2", state="waiting_for_stock")]

    def undo(self, source, plan=None, reason=None):
        plan = inventory.undo_review(source, "home") if plan is None else plan
        params = {"change_id": source, "space": "home", "expect": plan["expect"], **({"reason": reason} if reason else {})}
        return inventory.apply(Op("inventory.undo", params), existing.ACTOR, "Undo fixture queue change",
                               **({"reason": reason} if reason else {}))

    def layout(self):
        return self.sql("select id,position from watchlist_item order by position,id")

    def made(self):
        return self.sql("select table_name,op,row_key from audit.row_change where change_set_id=(select max(id) from audit.change_set) order by id")

    def test_added_rows_are_removed_as_exactly_their_deletes_with_survivors_unmoved(self):
        first = self.first()
        self.queue([first[0], first[2]], "Fixture queue")
        layout = self.layout()
        source = self.queue(first, "Fixture shop check adding two rows")
        self.assertEqual(self.sql("select op from audit.row_change where change_set_id=%s", (source,)), [("INSERT",)] * 2)
        plan = inventory.undo_review(source, "home")
        self.assertEqual((plan["action"], plan["row_count"]), (rows_undo.REMOVE, 2))
        before = self.persisted()
        with mock.patch.object(rows_undo, "confirm_in_transaction", wraps=rows_undo.confirm_in_transaction) as hook:
            after, summary = self.undo(source, plan, reason="Added by mistake")
        hook.assert_called_once()
        ids = [item["watch_row_id"] for item in plan["rows"]]
        self.assertEqual(summary.extra["removed_watch_row_ids"], ids)
        self.assertEqual(self.made(), [("watchlist_item", "DELETE", {"id": rid}) for rid in sorted(ids)])
        self.assertEqual(self.layout(), layout)
        self.assertEqual([item.as_dict() for item in after.watchlist.rows], [first[0], first[2]])
        self.assertEqual(self.sql("select reason from audit.change_set where id=(select max(id) from audit.change_set)"),
                         [("Added by mistake",)])
        saved = self.persisted()
        for table in ("collection_card", "token_card", "deck", "deck_text", "deck_line", "decks_revision"):
            self.assertEqual(saved[table], before[table], table)
        with self.assertRaises(inventory.Invalid):
            self.undo(source, plan, reason="Again")
        self.assertEqual(self.persisted(), saved)

    def test_removed_rows_come_back_as_exactly_their_inserts_under_fresh_ids_where_they_were(self):
        first = self.first()
        self.queue(first, "Fixture queue")
        layout = self.layout()
        source = self.queue([first[0], first[2]], "Fixture shop check removing two rows")
        self.assertEqual(self.sql("select op from audit.row_change where change_set_id=%s", (source,)), [("DELETE",)] * 2)
        plan = inventory.undo_review(source, "home")
        self.assertEqual((plan["action"], plan["row_count"]), (rows_undo.ADD, 2))
        after, summary = self.undo(source, plan)
        new = summary.extra["restored_watch_row_ids"]
        self.assertEqual(self.made(), [("watchlist_item", "INSERT", {"id": rid}) for rid in new])
        self.assertTrue(set(new).isdisjoint(rid for rid, _ in layout))
        self.assertEqual([item.as_dict() for item in after.watchlist.rows], first)
        kept = dict(layout)
        self.assertEqual([(rid, position) for rid, position in self.layout() if rid in kept],
                         [(rid, kept[rid]) for rid in (layout[0][0], layout[2][0])])
        saved = self.persisted()
        with self.assertRaises(inventory.Invalid):
            self.undo(source, plan)
        self.assertEqual(self.persisted(), saved)
        with self.assertRaises(rows_undo.Refused) as refused:
            inventory.undo_review(source, "home")
        self.assertIn(rows_undo.DUPLICATE + ": 2", str(refused.exception))

    def test_single_set_add_and_remove_are_undone_and_a_tampered_proof_rolls_back(self):
        self.queue(self.first()[:1], "Fixture queue")
        inventory.apply(Op("watchlist.set", {"add": True, "values": row("Fixture card 3"), "repo": str(config.REPO)}),
                        existing.ACTOR, "Fixture queue add")
        added = self.source("watchlist_item")
        before = self.persisted()
        real = rows_undo.confirm
        def tampered(before_inv, saved, summary, actual, layout):
            return real(before_inv, saved, summary, actual, layout[:-1])  # As if a survivor had moved.
        with mock.patch.object(rows_undo, "confirm", side_effect=tampered), self.assertRaises(undo.UndoConflict) as caught:
            self.undo(added, reason="Not wanted")
        self.assertEqual(str(caught.exception), rows_undo.UNCONFIRMED)
        self.assertEqual(self.persisted(), before)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))
        inventory.apply(Op("watchlist.set", {"select": "Fixture card 3", "values": {"notes": "Later touch"}, "repo": str(config.REPO)}),
                        existing.ACTOR, "Fixture later touch")
        with self.assertRaises(rows_undo.Refused) as refused:
            inventory.undo_review(added, "home")
        self.assertIn(rows_undo.EDITED + ": 1", str(refused.exception))
        inventory.apply(Op("watchlist.remove", {"select": "Fixture card 3"}), existing.ACTOR, "Fixture queue remove")
        removed = self.source("watchlist_item")
        after, summary = self.undo(removed)
        self.assertEqual(summary.counts, {"added_rows": 1, "undo": 1})
        self.assertEqual([item.name for item in after.watchlist.rows], ["Sol Ring", "Fixture card 3"])
