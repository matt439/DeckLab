"""An exact reverse rename retains the editor's existing byte-based save contract.

Ordinary deck saves compare the current exact ID and text SHA. A rename review
also binds the numbered revision, so returning to earlier bytes cannot revive
an earlier rename confirmation. All writes below use disposable PostgreSQL.
"""
from decklab.lib import inventory
from decklab.lib.inventory import ops_decks, pg
from decklab.lib.inventory.model import QUEUE_FIELDS, Sheet
from decklab.lib.inventory import paths, rules
from decklab.tests import db_support
from decklab.tests.test_inventory_contract import CLAUDE, FIXTURE_PROFILES, MATT
from decklab.tests.test_inventory_rename import NEW, OLD, TEXT, operation, snapshot


class ReverseRenameSaveContractTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        super().setUp()
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        fixture = snapshot().replace(status=Sheet(paths.STATUS, tuple(rules.STATUS_FIELDS), (), True),
                                     watchlist=Sheet(paths.WATCHLIST, QUEUE_FIELDS, (), True))
        pg.write_model(fixture, CLAUDE, "Import reverse-rename fixture", dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname)

    def test_identical_current_id_and_bytes_allow_a_save_but_not_an_old_rename_review(self):
        original = self.backend.load()
        old = original.deck(OLD)
        stale_rename = operation(original)
        moved, _ = self.backend.apply(stale_rename, MATT, "Rename fixture")
        reversed_, _ = self.backend.apply(operation(moved, "Old title", NEW), MATT, "Reverse fixture rename")
        self.assertEqual(reversed_.deck(OLD).sha256, old.sha256)
        self.assertEqual(reversed_.deck(OLD).text, TEXT)
        self.assertGreater(reversed_.deck(OLD).revision, old.revision)

        with self.assertRaises(ops_decks.DeckRefused):
            self.backend.apply(stale_rename, MATT, "Refuse obsolete rename review")
        self.assertEqual(self.backend.load(), reversed_)

        intended = old.text + "A note based on these same saved bytes.\n"
        saved, _ = self.backend.apply(inventory.Op("deck.save", {
            "deck_id": OLD, "text": intended, "base_sha256": old.sha256,
        }), MATT, "Save exact-byte editor changes after reverse rename")
        self.assertEqual(saved.deck(OLD).text, intended)
        self.assertEqual(saved.deck(OLD).revision, reversed_.deck(OLD).revision + 1)
        self.assertEqual(dict(saved.deck_aliases), {NEW: OLD})
        self.assertEqual([row.revision for row in self.backend.deck_revisions(OLD)], [4, 3, 2, 1])
