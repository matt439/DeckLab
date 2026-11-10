"""Deleted-token restoration writes only to a guarded disposable PostgreSQL database.

These run the real PgInventory.apply, so its pre-commit proof (undo_token_delete's
confirm_in_transaction) reads this change set's own audit rows and token layout."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab import db
from decklab.lib import cards, config, inventory
from decklab.lib.inventory import Op, files, undo, undo_token_delete as deleted
from decklab.lib.tokens import names
from decklab.tests import db_support, test_inventory_undo_pg as existing
from decklab.tests import test_collection_edit as collection_fixture
from decklab.tests import test_inventory_undo_token_insert_pg as insert_pg


class TokenRestoreUndoPgTests(db_support.DbTestCase):
    fresh = existing.UndoPgTests.fresh
    sql = existing.UndoPgTests.sql
    persisted = existing.UndoPgTests.persisted
    source = existing.UndoPgTests.source
    NUMBERS = {"Beast": "1", "Angel": "3", "Zombie": "7"}

    @classmethod
    def row(cls, front="Angel", back="The Monarch", quantity="2"):
        """A fully known printing: restoration needs the removed card's printing and pairing checked."""
        number = cls.NUMBERS[front]
        return {**insert_pg.TokenInsertUndoPgTests.row(front, back, quantity), "set": "tst", "finish": "nonfoil",
                "front_collector_number": number, "back_collector_number": str(int(number) + 1) if back else ""}

    def setUp(self):
        existing.UndoPgTests.setUp(self)
        # As test_inventory_undo_token_batch_pg: the fixture printing "tst" isn't in the card data.
        self.enterContext(mock.patch.object(names, "check_names", side_effect=lambda row: (dict(row), [])))
        self.enterContext(mock.patch.object(cards, "printing", return_value={"digital": False, "games": ["paper"],
                                                                           "finishes": ["nonfoil"]}))

    add = insert_pg.TokenInsertUndoPgTests.add
    packed = insert_pg.TokenInsertUndoPgTests.packed

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        temporary = tempfile.TemporaryDirectory(prefix="decklab-undo-token-restore-pg-", dir=root)
        cls.addClassCleanup(temporary.cleanup)
        path = Path(temporary.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Deleted-token restoration requires a disposable database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def seed(self):
        """Beast, Angel // The Monarch and Zombie, then Angel deleted: (its change, its id)."""
        self.add(self.row("Beast", "", "4"))
        self.add(self.row())
        self.add(self.row("Zombie", "", "5"))
        sheet = self.fresh().token_set("home")
        base = next(row for row in sheet.rows if row.front == "Angel")
        inventory.apply(Op("tokens.remove", {"space": "home", "sha256": files.rendered_sha256(sheet), "base": base.as_dict()}),
                        existing.ACTOR, "Fixture token deletion", reason="Fixture deletion")
        source = self.source("token_card")
        self.assertEqual(self.sql("select table_name,op from audit.row_change where change_set_id=%s", (source,)), [("token_card", "DELETE")])
        return source, base.id

    def apply(self, source, plan=None):
        plan = inventory.undo_review(source, "home") if plan is None else plan
        return inventory.apply(Op("inventory.undo", {"change_id": source, "space": "home", "expect": plan["expect"],
                                                     "confirm_owned": True}), existing.ACTOR, "Undo fixture token deletion")

    def test_restore_is_one_fresh_insert_with_survivors_positions_and_history_kept(self):
        source, deleted_id = self.seed()
        self.packed("1 Beast")
        plan = inventory.undo_review(source, "home")
        self.assertEqual(plan["action"], deleted.ACTION)
        before = self.persisted()
        layout = self.sql("select id,position from token_card order by position,id")
        original = self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,))
        with mock.patch.object(deleted, "confirm_in_transaction", wraps=deleted.confirm_in_transaction) as hook:
            after, summary = self.apply(source, plan)
        hook.assert_called_once()
        rid = summary.extra["added_token_row_id"]
        self.assertNotIn("token_restore", summary.extra)
        self.assertNotEqual(rid, deleted_id)
        self.assertNotIn(rid, [item[0] for item in layout])
        self.assertEqual(summary.counts["cards"], 11)  # Two physical paired cards back, not four faces.
        changes = self.sql("select table_name,op,row_key,before from audit.row_change where change_set_id=(select max(id) from audit.change_set)")
        self.assertEqual(changes, [("token_card", "INSERT", {"id": rid}, None)])
        self.assertEqual([row for row in self.sql("select id,position from token_card order by position,id") if row[0] != rid], layout)
        restored = next(row for row in after.token_set("home").rows if row.id == rid)
        self.assertEqual((restored.front, restored.back, str(restored.quantity)), ("Angel", "The Monarch", "2"))
        self.assertEqual(self.sql("select id,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,)), original)
        saved = self.persisted()
        self.assertEqual(len(saved["audit.row_change"]), len(before["audit.row_change"]) + 1)
        for table in ("collection_card", "collection_import", "collection_import_content", "deck", "deck_text", "deck_line", "deck_revision", "decks_revision"):
            self.assertEqual(saved[table], before[table], table)
        with self.assertRaises(undo.UndoConflict):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), saved)

    def _positioned_delete(self, positions):
        for front, back in (("Beast", ""), ("Angel", "The Monarch"), ("Zombie", "")):
            self.add(self.row(front, back))
        with self.connect("owner") as connection:
            with db.change("claude", "cli", "Seed disposable ordering", conn=connection) as (cur, _):
                for front, position in positions.items():
                    cur.execute("update token_card set position=%s where space_id='home' and front=%s", (position, front))
                cur.execute("update inventory_revision set revision=revision+1")
        sheet = self.fresh().token_set("home")
        target = next(row for row in sheet.rows if row.front == "Angel")
        inventory.apply(Op("tokens.remove", {"space": "home", "sha256": files.rendered_sha256(sheet), "base": target.as_dict()}),
                        existing.ACTOR, "Delete disposable token row", reason="Fixture deletion")
        return self.source("token_card"), target.id

    def test_single_delete_restore_accepts_only_predicted_inverse_survivor_renumbering(self):
        source, old_id = self._positioned_delete({"Beast": 0, "Zombie": 1, "Angel": 2})
        self.assertEqual(self.sql("select op from audit.row_change where change_set_id=%s", (source,)), [("DELETE",)])
        self.assertEqual(inventory.undo_review(source, "home")["action"], deleted.ACTION)
        after, summary = self.apply(source)
        self.assertNotEqual(summary.extra["added_token_row_id"], old_id)
        self.assertEqual(sorted(row[0] for row in self.sql("select op from audit.row_change where change_set_id=(select max(id) from audit.change_set)")),
                         ["INSERT", "UPDATE", "UPDATE"])
        self.assertEqual([row.front for row in after.token_set("home").rows], ["Beast", "Angel", "Zombie"])

    def test_delete_with_position_only_survivors_restores_one_row_through_the_batch_proof(self):
        source, old_id = self._positioned_delete({"Angel": 0, "Zombie": 1024, "Beast": 2048})
        self.assertEqual(sorted(row[0] for row in self.sql("select op from audit.row_change where change_set_id=%s", (source,))),
                         ["DELETE", "UPDATE"])
        plan = inventory.undo_review(source, "home")
        self.assertEqual((plan["action"], plan["row_count"]), ("token_batch_add", 1))
        after, summary = self.apply(source, plan)
        new_id, = summary.extra["added_token_row_ids"]
        self.assertNotEqual(new_id, old_id)
        self.assertEqual([row.front for row in after.token_set("home").rows], ["Beast", "Angel", "Zombie"])

    def test_a_tampered_proof_rolls_the_insert_back(self):
        source, _ = self.seed()
        plan = inventory.undo_review(source, "home")
        before = self.persisted()
        real = deleted.confirm
        def tampered(before_inv, saved, summary, actual, layout):
            return real(before_inv, saved, summary, actual + actual, layout)  # As if a second row changed.
        with mock.patch.object(deleted, "confirm", side_effect=tampered), self.assertRaises(undo.UndoConflict) as caught:
            self.apply(source, plan)
        self.assertEqual(str(caught.exception), deleted.UNCONFIRMED)
        self.assertEqual(self.persisted(), before)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))

    def test_a_packed_line_claiming_the_card_refuses_without_write(self):
        source, _ = self.seed()
        plan = inventory.undo_review(source, "home")
        self.packed("1 Angel // The Monarch")
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            self.apply(source, plan)
        self.assertEqual(self.persisted(), before)
