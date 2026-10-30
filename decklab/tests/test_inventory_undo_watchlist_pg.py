"""Restoring purchase-queue rows' updated values writes only to a guarded disposable PostgreSQL database.

These run the real PgInventory.apply, so the queue Undo's pre-commit proof
(undo_watchlist.confirm_in_transaction) reads this change set's own audit rows. No card cache,
retailer or household data is read."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import config, inventory
from decklab.lib.inventory import Op, undo, undo_watchlist as queue
from decklab.tests import db_support, test_inventory_undo_pg as existing
from decklab.tests import test_collection_edit as collection_fixture
from decklab.tests.test_inventory_undo_watchlist import row


class WatchlistUndoPgTests(db_support.DbTestCase):
    setUp = existing.UndoPgTests.setUp
    fresh = existing.UndoPgTests.fresh
    sql = existing.UndoPgTests.sql
    persisted = existing.UndoPgTests.persisted
    source = existing.UndoPgTests.source

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        temporary = tempfile.TemporaryDirectory(prefix="decklab-undo-watchlist-pg-", dir=root)
        cls.addClassCleanup(temporary.cleanup)
        path = Path(temporary.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Purchase-queue Undo requires a disposable database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def seed(self):
        """Sol Ring, Fixture card 1 and 2 queued; then a shop check changing only the two cards' values: that change."""
        first = [row("Sol Ring"), row("Fixture card 1", quantity="3", notes="Recorded queue note"),
                 row("Fixture card 2", quantity="2", state="waiting_for_stock")]
        inventory.apply(Op("watchlist.replace", {"rows": first, "repo": str(config.REPO)}), existing.ACTOR, "Fixture queue")
        checked = [first[0], {**first[1], "quantity": "1", "notes": "Current queue note"},
                   {**first[2], "state": "ready", "listed_aud": "0.50", "listed_at": "Fixture shop", "in_stock": "yes",
                    "checked": "2026-10-20"}]
        inventory.apply(Op("watchlist.replace", {"rows": checked, "repo": str(config.REPO)}), existing.ACTOR, "Fixture shop check")
        source = self.source("watchlist_item")
        self.assertEqual(self.sql("select table_name,op from audit.row_change where change_set_id=%s", (source,)),
                         [("watchlist_item", "UPDATE")] * 2)
        return source, first

    def apply(self, source, plan=None):
        plan = inventory.undo_review(source, "home") if plan is None else plan
        return inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"]}),
                               existing.ACTOR, "Undo fixture shop check")

    def test_undo_is_exactly_two_updates_with_positions_and_history_kept(self):
        source, first = self.seed()
        plan = inventory.undo_review(source, "home")
        self.assertEqual((plan["action"], plan["row_count"]), (queue.ACTION, 2))
        ids = [item["watch_row_id"] for item in plan["rows"]]
        layout = self.sql("select id,position from watchlist_item order by position,id")
        original = self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,))
        before = self.persisted()
        with mock.patch.object(queue, "confirm_in_transaction", wraps=queue.confirm_in_transaction) as hook:
            after, summary = self.apply(source, plan)
        hook.assert_called_once()
        self.assertEqual(summary.extra["restored_watch_row_ids"], ids)
        made = self.sql("select table_name,op,row_key from audit.row_change where change_set_id=(select max(id) from audit.change_set)")
        self.assertEqual(sorted(made, key=lambda item: item[2]["id"]), [("watchlist_item", "UPDATE", {"id": rid}) for rid in sorted(ids)])
        self.assertEqual(self.sql("select id,position from watchlist_item order by position,id"), layout)
        self.assertEqual(self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,)), original)
        self.assertEqual([item.as_dict() for item in after.watchlist.rows], first)
        saved = self.persisted()
        self.assertEqual(len(saved["audit.row_change"]), len(before["audit.row_change"]) + 2)
        for table in ("collection_card", "token_card", "deck", "deck_text", "deck_line", "deck_revision", "decks_revision"):
            self.assertEqual(saved[table], before[table], table)
        with self.assertRaises(inventory.Invalid):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), saved)

    def test_a_single_row_set_is_undone_in_place(self):
        source, first = self.seed()
        inventory.apply(Op("watchlist.set", {"select": "Sol Ring", "values": {"notes": "Changed by set"}, "repo": str(config.REPO)}),
                        existing.ACTOR, "Fixture queue set")
        single = self.source("watchlist_item")
        self.assertNotEqual(single, source)
        after, summary = self.apply(single)
        self.assertEqual(summary.counts, {"edited": 1, "undo": 1})
        self.assertEqual(after.watchlist.rows[0].as_dict(), first[0])

    def test_a_later_touch_refuses_and_a_tampered_proof_rolls_back(self):
        source, _ = self.seed()
        plan = inventory.undo_review(source, "home")
        before = self.persisted()
        real = queue.confirm
        def tampered(before_inv, saved, summary, actual):
            return real(before_inv, saved, summary, actual[:-1])  # As if one row were kept.
        with mock.patch.object(queue, "confirm", side_effect=tampered), self.assertRaises(undo.UndoConflict) as caught:
            self.apply(source, plan)
        self.assertEqual(str(caught.exception), queue.UNCONFIRMED)
        self.assertEqual(self.persisted(), before)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))
        inventory.apply(Op("watchlist.set", {"select": "Fixture card 2", "values": {"notes": "Later touch"}, "repo": str(config.REPO)}),
                        existing.ACTOR, "Fixture later touch")
        with self.assertRaises(queue.Refused) as refused:
            inventory.undo_review(source, "home")
        self.assertIn(queue.EDITED + ": 1", str(refused.exception))
