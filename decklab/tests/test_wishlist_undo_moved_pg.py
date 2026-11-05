"""Undo of a wishlist addition that moved other entries along, in guarded disposable PostgreSQL."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import config, state
from decklab.lib.state import pg, pg_wishlist_undo as adapter, wishlist_undo as undo
from decklab.tests import db_support, test_collection_edit as roles

MATT = state.Actor("matt", "Matt", via="tunnel")
WEB = state.Actor("matt", "Matt", source="web", via="tunnel")


def entry(name, notes=""):
    return {"name": name, "set": "", "number": "", "notes": notes, "source": ""}


class WishlistUndoMovedPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        folder = tempfile.TemporaryDirectory(prefix="decklab-wishlist-moved-pg-", dir=root)
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

    def seed(self):
        for name in ("Opt", "Forest", "Island"):
            self.store.wishlist_add("matt", entry(name, "Private café note"), MATT, "Fixture entry")
        self.store.wishlist_add("matt", entry("Llanowar Elves"), MATT, "Fixture put back", at=1)
        return self.sql("select max(change_set_id) from audit.row_change where table_name='wishlist_entry'")[0][0]

    def test_inverse_deletes_the_entry_and_moves_each_entry_back_in_one_change(self):
        source = self.seed()
        self.assertEqual(self.sql("select op from audit.row_change where change_set_id=%s order by id", (source,)),
                         [("UPDATE",), ("UPDATE",), ("INSERT",)])
        plan = self.store.wishlist_undo_review(source, "matt")
        self.assertEqual((plan["action"], plan["moved"]), ("wishlist_remove", 2))
        result = self.store.wishlist_undo_apply(source, "matt", plan["expect"], WEB, "Undo wishlist change")
        self.assertEqual(result["removed_name"], "Llanowar Elves")
        self.assertEqual(self.layout(), [("Opt", 0), ("Forest", 1), ("Island", 2)])
        undo_set = self.sql("select max(id) from audit.change_set")[0][0]
        self.assertEqual(self.sql("select op, (row_key->>'position')::int from audit.row_change where change_set_id=%s order by id", (undo_set,)),
                         [("DELETE", 1), ("UPDATE", 1), ("UPDATE", 2)])
        with self.connect("ro") as connection:
            self.assertEqual(result["sha256"], undo.list_sha(adapter.entries(connection.cursor(), "matt")))
        with self.assertRaises(undo.UndoConflict):
            self.store.wishlist_undo_review(source, "matt")

    def test_other_profiles_and_later_changes_write_nothing(self):
        source = self.seed()
        for pid in ("user1", "user2"):
            with self.subTest(pid=pid), self.assertRaises(undo.UndoMissing):
                self.store.wishlist_undo_review(source, pid)
        plan = self.store.wishlist_undo_review(source, "matt")
        self.store.wishlist_set("matt", "Forest", MATT, "Later edit", notes="Changed")
        before = self.layout()
        with self.assertRaises(undo.UndoConflict):
            self.store.wishlist_undo_apply(source, "matt", plan["expect"], WEB, "Undo wishlist change")
        self.assertEqual(self.layout(), before)
