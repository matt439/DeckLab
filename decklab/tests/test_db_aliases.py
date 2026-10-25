"""Rename metadata in nightly exports/checks, using disposable databases and temporary files."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.db import backup, check, conn as db, export, migrate, profiles_sync, setup
from decklab.lib.inventory import Op, files, ops_rename  # noqa: F401 (registers rename)
from decklab.lib.inventory import pg
from decklab.lib.state import Unavailable
from decklab.tests import db_support
from decklab.tests.test_inventory_contract import CLAUDE, FIXTURE_PROFILES, MATT
from decklab.tests.test_inventory_pg_decks import DECK, _Db


class AliasMaintenanceTests(_Db):

    def rename(self, backend, title, deck_id="casual/test"):
        held = backend.load().deck(deck_id)
        from decklab.lib import decks
        return self.apply(backend, "deck.rename", deck_id=deck_id, new_slug=decks.title_slug(title),
                          title=title, base_sha256=held.sha256, revision=held.revision)[0]

    def invariant(self, name="aliases"):
        with self.connect("ro") as c:
            return getattr(check, f"_deck_{name}")(c)()

    def test_export_retains_aliases_and_original_revisions_across_a_reverse_rename(self):
        _, backend = self.import_tree()
        old = self.rows("select deck_id, revision, at, actor, message, text from deck_revision order by deck_id")
        with self.connect("ro") as c:
            empty_digest = backup.digest_rows(c)["public.deck_alias"]
        self.rename(backend, "Renamed")
        self.rename(backend, "Test", "casual/renamed")
        current = backend.load()
        self.assertEqual(dict(current.deck_aliases), {"casual/renamed": "casual/test"})
        self.assertEqual(self.rows("select deck_id, revision, at, actor, message, text from deck_revision "
                                   "where revision = 1 order by deck_id"), old)
        self.assertTrue(self.invariant()[0])
        self.assertTrue(self.invariant("revisions")[0])
        self.assertTrue(self.invariant("texts")[0])
        folder = Path(tempfile.mkdtemp(prefix="decklab-alias-export-"))
        self.addCleanup(shutil.rmtree, folder)
        export.write_tables(folder, dbname=self.dbname)
        self.assertEqual((folder / "tables/public.deck_alias.csv").read_bytes(),
                         b"alias_id,deck_id\ncasual/renamed,casual/test\n")
        self.assertEqual((folder / "magic/decks/casual/test.md").read_bytes(), current.deck("casual/test").data)
        self.assertFalse((folder / "magic/decks/casual/renamed.md").exists())
        with self.connect("ro") as c:
            self.assertEqual(backup.count_rows(c)["public.deck_alias"], 1)
            self.assertNotEqual(backup.digest_rows(c)["public.deck_alias"], empty_digest)
            self.assertTrue(check._round_trip(c, current)()[0])
            # Reading only the old file format would lose aliases; the nightly round trip
            # also verifies their serialized table, rather than borrowing the loaded map.
            with mock.patch.object(export, "table_csv", return_value=b"alias_id,deck_id\n"):
                ok, _, detail = check._round_trip(c, current)()
        self.assertFalse(ok)
        self.assertIn("deck_aliases[casual/renamed]", detail)

    def test_retiring_a_renamed_deck_keeps_a_valid_reserved_lineage(self):
        _, backend = self.import_tree()
        after = self.rename(backend, "Renamed")
        self.apply(backend, "deck.delete", deck_id="casual/renamed",
                   base_sha256=after.deck("casual/renamed").sha256)
        self.assertTrue(self.invariant()[0])
        self.assertEqual(dict(backend.load().deck_aliases), {"casual/test": "casual/renamed"})

    def test_alias_chains_missing_history_and_active_aliases_fail_the_invariant(self):
        self.import_tree()
        with self.connect("owner") as c:
            with db.change("test", "test", "break aliases for the check", conn=c) as (cur, _):
                cur.execute("insert into deck_alias (alias_id, deck_id) values "
                            "('casual/older', 'casual/test'), ('casual/test', 'casual/missing')")
        ok, _, detail = self.invariant()
        self.assertFalse(ok)
        self.assertIn("points to another alias", detail)
        self.assertIn("both an alias and a current deck", detail)
        self.assertIn("has no deck history", detail)

    def test_lineage_checks_detect_a_revision_saved_under_an_old_id(self):
        _, backend = self.import_tree()
        after = self.rename(backend, "Renamed")
        with self.connect("owner") as c:
            c.execute("insert into deck_revision (deck_id, revision, at, actor, message, op, text) "
                      "values ('casual/test', 3, now(), 'test', 'invalid stale-ID save', 'M', %s)", (DECK,))
        self.assertTrue(self.invariant()[0])       # no collisions, but the current deck is behind
        ok, _, detail = self.invariant("revisions")
        self.assertFalse(ok)
        self.assertIn("casual/renamed is at revision 2, its newest is 3", detail)
        self.assertFalse(self.invariant("texts")[0])
        with self.connect("owner") as c:
            c.execute("insert into deck_revision (deck_id, revision, at, actor, message, op, text) "
                      "values ('casual/renamed', 1, now(), 'test', 'invalid duplicate', 'M', %s)",
                      (after.deck("casual/renamed").text,))
        ok, _, detail = self.invariant()
        self.assertFalse(ok)
        self.assertIn("casual/renamed has revision 1 under several IDs", detail)

    def test_a_missing_current_deck_requires_a_retirement_revision(self):
        _, backend = self.import_tree()
        self.rename(backend, "Renamed")
        with self.connect("owner") as c:
            with db.change("test", "test", "remove current row without a tombstone", conn=c) as (cur, _):
                cur.execute("delete from deck where id = 'casual/renamed'")
        ok, _, detail = self.invariant()
        self.assertFalse(ok)
        self.assertIn("missing its current deck without a retirement", detail)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class BeforeAliasMigrationTests(unittest.TestCase):

    def test_export_and_checks_keep_working_before_rename_migration(self):
        name = db_support.create_empty_database("pre_alias")
        self.addCleanup(db_support.drop_database, name)
        early = Path(tempfile.mkdtemp(prefix="decklab-pre-alias-"))
        self.addCleanup(shutil.rmtree, early)
        for migration in migrate.available():
            if migration["version"] < 10:
                shutil.copy(migration["path"], early / Path(migration["path"]).name)
        migrate.apply(dbname=name, directory=early)
        setup.secure_database(name)
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=name)
        inv = files.build({"magic/decks/casual/test.md": DECK.encode()}).with_status_rows([]).with_watchlist([])
        pg.write_model(inv, CLAUDE, "Import test deck", dbname=name, decks=True)
        backend = pg.PgInventory(dbname=name)
        before = backend.load()
        self.assertFalse(before.aliases_ready)
        with self.assertRaises(Unavailable):
            backend.apply(Op("deck.rename", {"deck_id": "casual/test", "new_slug": "renamed", "title": "Renamed",
                                             "base_sha256": before.deck("casual/test").sha256, "revision": 1}),
                          MATT, "Rename unavailable")
        tables = early / "export/tables"
        tables.mkdir(parents=True)
        preserved = tables / "public.deck_alias.csv"
        preserved.write_bytes(b"old export preserved\n")
        export.write_tables(early / "export", dbname=name)
        self.assertEqual(preserved.read_bytes(), b"old export preserved\n")
        self.assertTrue((early / "export/magic/decks/casual/test.md").is_file())
        with db.connect("ro", dbname=name) as c:
            self.assertEqual(check._deck_aliases(c)(), (True, False, "rename aliases unavailable until migration 0010"))
            self.assertTrue(check._deck_revisions(c)()[0])
            self.assertTrue(check._deck_texts(c)()[0])
            self.assertTrue(check._round_trip(c, before)()[0])


if __name__ == "__main__":
    unittest.main()
