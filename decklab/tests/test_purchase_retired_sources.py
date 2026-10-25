"""Retiring a saved deck preserves its recorded purchasing sources without inventing missing decks."""
import dataclasses
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from decklab.lib import inventory, purchases
from decklab.lib.inventory import orders
from decklab.lib.inventory.model import Deck, DeckRevision
from decklab.tests import db_support, test_purchases


SOURCE = "magic/decks/casual/elves.md"
DECK_ID = "casual/elves"
TEXT = "# Elves\n\n- **Status:** idea\n\n## Decklist\n\n```\nDeck\n1 Opt\n```\n"
WHEN = datetime(2026, 10, 15, tzinfo=timezone.utc)


def revision(number, op, text=None):
    return DeckRevision(DECK_ID, number, WHEN, "claude", "Fixture change", op, text=text)


class RetiredPurchaseSourceTests(unittest.TestCase):
    # Reuse only the small purchase fixture's helpers, without rerunning its inherited tests.
    component = test_purchases.PurchasesTests.component
    write = test_purchases.PurchasesTests.write
    write_csv = test_purchases.PurchasesTests.write_csv
    save = test_purchases.PurchasesTests.save

    def setUp(self):
        test_purchases.PurchasesTests.setUp(self)
        self.last = self.enterContext(mock.patch.object(inventory, "last_revision", return_value=revision(2, "D")))
        self.previous = self.enterContext(mock.patch.object(inventory, "deck_revision", return_value=revision(1, "A", TEXT)))

    def snapshot(self):
        return dataclasses.replace(inventory.current(), backend="db")

    def queue(self, **changes):
        return dict.fromkeys(purchases.QUEUE_FIELDS, "") | {"name": "Sol Ring", "quantity": "2",
            "printing": "any", "state": "long_term", "for": "Elves", "source": SOURCE} | changes

    def test_current_deck_is_valid_without_reading_history(self):
        inv = self.snapshot().with_deck(Deck("home", "casual", "elves", TEXT))
        self.assertTrue(purchases.source_exists(self.root, SOURCE, inv=inv))
        self.last.assert_not_called()
        self.previous.assert_not_called()

    def test_retired_home_and_person_sources_require_saved_text_before_latest_deletion(self):
        inv = self.snapshot()
        person = "magic/people/user2/decks/commander/dragons.md"
        self.assertTrue(purchases.source_exists(self.root, SOURCE, inv=inv))
        self.assertTrue(purchases.source_exists(self.root, person, inv=inv))
        self.assertEqual(self.last.call_args_list, [mock.call(DECK_ID), mock.call("user2/commander/dragons")])
        self.assertEqual(self.previous.call_args_list, [mock.call(DECK_ID, 1), mock.call("user2/commander/dragons", 1)])
        self.assertFalse((self.root / SOURCE).exists())

    def test_file_backend_never_queries_another_backends_history(self):
        self.assertFalse(purchases.source_exists(self.root, SOURCE, inv=inventory.current()))
        self.write(SOURCE, TEXT)
        gone = inventory.current().without_deck(DECK_ID)
        self.assertFalse(purchases.source_exists(self.root, SOURCE, inv=gone))
        self.last.assert_not_called()
        self.previous.assert_not_called()

    def test_arbitrary_missing_id_or_history_ending_in_a_live_save_is_not_retired(self):
        inv = self.snapshot()
        for latest in (None, revision(1, "A", TEXT), revision(2, "M", TEXT), revision(3, "A", TEXT)):
            with self.subTest(latest=latest):
                self.last.return_value = latest
                self.assertFalse(purchases.source_exists(self.root, SOURCE, inv=inv))
        self.previous.assert_not_called()

    def test_deletion_without_an_immediately_preceding_saved_text_is_not_a_valid_source(self):
        inv = self.snapshot()
        for latest, before in ((revision(1, "D"), None), (revision(2, "D"), None),
                               (revision(2, "D"), revision(1, "D")),
                               (revision(2, "D"), revision(1, "A"))):
            with self.subTest(latest=latest, before=before):
                self.last.return_value, self.previous.return_value = latest, before
                self.assertFalse(purchases.source_exists(self.root, SOURCE, inv=inv))

    def test_path_validation_precedes_history_and_research_sources_keep_their_disk_rule(self):
        inv = self.snapshot()
        for path in ("../" + SOURCE, "/" + SOURCE, "C:/" + SOURCE, SOURCE.replace("/", "\\"),
                     "magic/decks/../decks/casual/elves.md", "magic//decks/casual/elves.md"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                purchases.source_exists(self.root, path, inv=inv)
        self.assertTrue(purchases.source_exists(self.root, "magic/buylists/research.md", inv=inv))
        self.assertFalse(purchases.source_exists(self.root, "magic/buylists/missing.md", inv=inv))
        self.write("magic/products/reference.csv", "name,quantity\nOpt,1\n")
        self.assertTrue(purchases.source_exists(self.root, "magic/products/reference.csv", inv=inv))
        self.last.assert_not_called()

    def test_unavailable_history_is_not_cached_as_a_missing_or_verified_source(self):
        checked = {}
        self.last.side_effect = inventory.Unavailable("History unavailable")
        with self.assertRaisesRegex(inventory.Unavailable, "History unavailable"):
            purchases.source_exists(self.root, SOURCE, inv=self.snapshot(), retired=checked)
        self.assertEqual(checked, {})
        self.last.side_effect = None
        self.assertTrue(purchases.source_exists(self.root, SOURCE, inv=self.snapshot(), retired=checked))
        self.assertEqual(checked, {DECK_ID: True})

    def test_queue_and_orders_keep_retired_sources_and_purchase_intent_unchanged(self):
        original = self.queue(notes="Still intended, even though the deck was retired")
        self.write_csv("magic/watchlist.csv", purchases.QUEUE_FIELDS, [original])
        self.record["sources"] = [SOURCE]
        self.save()
        inv = self.snapshot()
        with inventory.pinned(inv):
            queued, records = purchases.read_queue(), purchases.read_records()
        self.assertEqual(queued[0], original | {"quantity": 2})
        self.assertEqual(records[0]["sources"], [SOURCE])
        self.assertEqual(orders.queue_row(original, str(self.root), inv), original)
        self.assertEqual(self.record["sources"], [SOURCE])

    def test_repeated_sources_are_checked_once_per_validation_pass_and_never_globally_cached(self):
        self.write_csv("magic/watchlist.csv", purchases.QUEUE_FIELDS,
                       [self.queue(), self.queue(name="Opt") | {"for": "Another deck"}])
        self.record["sources"] = [SOURCE, SOURCE]
        self.save()
        inv = self.snapshot()
        with inventory.pinned(inv):
            self.assertEqual(len(purchases.read_queue()), 2)
            self.assertEqual(self.last.call_count, 1)
            self.assertEqual(self.previous.call_count, 1)
            self.assertEqual(len(purchases.read_records()), 1)
            self.assertEqual(self.last.call_count, 2)
            self.assertEqual(self.previous.call_count, 2)
            self.last.return_value = revision(3, "A", TEXT)
            with self.assertRaisesRegex(ValueError, "source file does not exist"):
                purchases.read_queue()
        self.assertEqual(self.last.call_count, 3)


class RetiredPurchaseSourceDatabaseTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        from decklab.tests.test_inventory_contract import FIXTURE_PROFILES
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def test_real_deletion_and_same_id_reuse_preserve_history_as_a_purchase_source(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import Actor, pg as state_pg
        from decklab.tests.test_deck_history import _snapshot, small_history
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        initial, images = _snapshot(lists=True)
        actor = Actor("claude", "test")
        pg.write_model(initial, actor, "Install isolated source fixture", dbname=self.dbname,
                       decks=True, images=images, history=small_history())
        backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        with tempfile.TemporaryDirectory() as folder, inventory.use(backend):
            root = Path(folder)
            path, deck_id = "magic/decks/casual/alpha.md", "casual/alpha"
            before = inventory.current().deck(deck_id)
            self.assertTrue(purchases.source_exists(root, path))
            inventory.apply(inventory.Op("deck.delete", {"deck_id": deck_id, "base_sha256": before.sha256}),
                            actor, "Retire isolated idea", refresh=False)
            self.assertIsNone(inventory.current().deck(deck_id))
            self.assertEqual(inventory.last_revision(deck_id).op, "D")
            self.assertTrue(purchases.source_exists(root, path))
            self.assertTrue(purchases.source_exists(root, "magic/decks/commander/gone.md"))
            self.assertFalse(purchases.source_exists(root, "magic/decks/casual/never-existed.md"))
            inventory.apply(inventory.Op("deck.create", {"space": "home", "kind": "casual", "slug": "alpha",
                                                          "text": before.text}), actor, "Recreate isolated idea", refresh=False)
            self.assertEqual(inventory.last_revision(deck_id).op, "A")
            with mock.patch.object(backend, "last_revision", side_effect=AssertionError("Current deck needs no history")):
                self.assertTrue(purchases.source_exists(root, path))
            current = inventory.current().deck(deck_id)
            inventory.apply(inventory.Op("deck.delete", {"deck_id": deck_id, "base_sha256": current.sha256}),
                            actor, "Retire isolated idea again", refresh=False)
            self.assertTrue(purchases.source_exists(root, path))
            self.assertEqual([r.op for r in inventory.deck_revisions(deck_id)[:3]], ["D", "A", "D"])


if __name__ == "__main__":
    unittest.main()
