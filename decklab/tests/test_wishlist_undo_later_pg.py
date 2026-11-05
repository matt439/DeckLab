"""Undo of a wishlist removal after later list changes, in guarded disposable PostgreSQL (E11-S08)."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import config, state
from decklab.lib.state import pg, pg_wishlist_undo as adapter, wishlist_undo as undo, wishlist_undo_later as later
from decklab.tests import db_support, test_collection_edit as roles

MATT = state.Actor("matt", "Matt", via="tunnel")
WEB = state.Actor("matt", "Matt", source="web", via="tunnel")
NOTE = "Private café note\r\nline two"


def entry(name, notes=""):
    return {"name": name, "set": "", "number": "", "notes": notes, "source": ""}


class WishlistUndoLaterPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        folder = tempfile.TemporaryDirectory(prefix="decklab-wishlist-later-pg-", dir=root)
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(roles.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Wishlist Undo requires a disposable database")

    def setUp(self):
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname, roles.ROLES["profiles"])
        self.store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())
        self.addCleanup(state.use(self.store))

    def sql(self, text, args=()):
        with self.connect("ro") as connection:
            return connection.execute(text, args).fetchall()

    def layout(self):
        return self.sql("select name, position from wishlist_entry where profile_id='matt' order by position")

    def last_change(self):
        return self.sql("select max(id) from audit.change_set")[0][0]

    def remove_forest(self):
        """Opt, Forest, Island, Plains at 0-3, then Forest removed: its change set."""
        for name in ("Opt", "Forest", "Island", "Plains"):
            self.store.wishlist_add("matt", entry(name, NOTE), MATT, "Fixture entry")
        self.store.wishlist_remove("matt", "Forest", MATT, "Fixture removal")
        return self.last_change()

    def test_removal_goes_back_to_its_old_place_after_later_changes_in_one_insert(self):
        source = self.remove_forest()
        self.store.wishlist_add("matt", entry("Swamp"), MATT, "Later addition")
        self.store.wishlist_set("matt", "Plains", MATT, "Later edit", notes="Edited")
        plan = self.store.wishlist_undo_review(source, "matt")
        self.assertEqual((plan["action"], plan["later"], plan["insert_at"]), ("wishlist_add", 2, 1))
        before_latest = plan["latest_owner"]
        result = self.store.wishlist_undo_apply(source, "matt", plan["expect"], WEB, "Undo wishlist change")
        self.assertEqual(result["restored"], entry("Forest", NOTE))
        self.assertEqual(self.layout(), [("Opt", 0), ("Forest", 1), ("Island", 2), ("Plains", 3), ("Swamp", 4)])
        undo_set = self.last_change()
        rows = self.sql("select id, op, (row_key->>'position')::int from audit.row_change where change_set_id=%s order by id", (undo_set,))
        self.assertEqual([row[1:] for row in rows], [("INSERT", 1)])
        self.assertGreater(rows[0][0], before_latest)
        with self.connect("ro") as connection:
            self.assertEqual(result["sha256"], undo.list_sha(adapter.entries(connection.cursor(), "matt")))
        # Its old position has been written since, so the same source can't be put back twice.
        with self.assertRaises(undo.UndoConflict):
            self.store.wishlist_undo_review(source, "matt")

    def test_card_removed_again_since_is_refused_and_writes_nothing(self):
        source = self.remove_forest()
        self.store.wishlist_add("matt", entry("Forest"), MATT, "Added again")
        self.store.wishlist_remove("matt", "Forest", MATT, "Removed again")
        before = self.layout()
        with self.assertRaises(later.Unsupported) as caught:
            self.store.wishlist_undo_review(source, "matt")
        self.assertEqual(str(caught.exception), later.AGAIN)
        self.assertEqual(self.layout(), before)

    def test_other_profiles_and_changes_between_review_and_save_write_nothing(self):
        source = self.remove_forest()
        self.store.wishlist_add("matt", entry("Swamp"), MATT, "Later addition")
        for pid in ("user1", "user2"):
            with self.subTest(pid=pid), self.assertRaises(undo.UndoMissing):
                self.store.wishlist_undo_review(source, pid)
        plan = self.store.wishlist_undo_review(source, "matt")
        self.store.wishlist_set("matt", "Opt", MATT, "Between", notes="Changed")
        before, last = self.layout(), self.last_change()
        with self.assertRaises(undo.UndoConflict):
            self.store.wishlist_undo_apply(source, "matt", plan["expect"], WEB, "Undo wishlist change")
        self.assertEqual((self.layout(), self.last_change()), (before, last))

    def test_a_failed_receipt_rolls_the_insert_back(self):
        source = self.remove_forest()
        self.store.wishlist_add("matt", entry("Swamp"), MATT, "Later addition")
        plan = self.store.wishlist_undo_review(source, "matt")
        before, last = self.layout(), self.last_change()
        with mock.patch.object(undo, "receipt", side_effect=undo.UndoConflict()), self.assertRaises(undo.UndoConflict):
            self.store.wishlist_undo_apply(source, "matt", plan["expect"], WEB, "Undo wishlist change")
        self.assertEqual((self.layout(), self.last_change()), (before, last))
