"""Rename reviews, concurrent confirmations and authorization in isolated storage."""
import json
import unittest
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import rename
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import ops_rename
from decklab.tests import db_support, test_deck_retirement as fixture, test_inventory_contract as contract


class _RenameFixture(fixture._Fixture):
    def request(self, **changes):
        current = self.backend.load().deck(fixture.DECK_ID)
        data = {"profile": "matt", "id": current.id, "title": "A better name", "sha256": current.sha256,
                "revision": max(1, current.revision)}
        data.update(changes)
        return data

    def preview(self, **changes):
        return rename.preview_rename(json.dumps(self.request(**changes)).encode())

    def confirm(self, proposal=None, **changes):
        proposal = proposal or self.preview()
        data = {key: proposal[key] for key in ("id", "title", "sha256", "revision", "new_id", "decks_revision")}
        data["profile"] = "matt"
        data.update(changes)
        return rename.rename_deck(json.dumps(data).encode())


class FileRenameTests(_RenameFixture, unittest.TestCase):
    def test_missing_migration_disables_only_rename_with_explicit_reason(self):
        before = self.backend.load()
        view = rename.rename_view(fixture.DECK_ID)
        self.assertFalse(view["may_rename"])
        self.assertEqual(view["why_not"], ops_rename.MIGRATE)
        error = self.assert_api_error(503, self.preview)
        self.assertEqual(error.extra, {"reason": "migration"})
        self.assert_unchanged(before)

    def test_write_permission_precedes_preview_details(self):
        before = self.backend.load()
        with mock.patch.object(access, "viewer", return_value="user1"):
            self.assertFalse(rename.rename_view(fixture.DECK_ID)["may_rename"])
            self.assert_api_error(403, self.preview, profile="user1", title="Invalid\nTitle")
        self.assert_unchanged(before)

    def test_strict_body_title_and_revision_validation_does_not_write(self):
        before = self.backend.load()
        for change in ({"title": " "}, {"title": 42}, {"title": "a" * 101}, {"title": "a\nb"},
                       {"title": "con"}, {"title": "!!!"}, {"sha256": "no"}, {"revision": True},
                       {"revision": 0}, {"unexpected": True}):
            with self.subTest(change=change):
                self.assert_api_error(400, self.preview, **change)
        self.assert_unchanged(before)


class PgRenameApiTests(_RenameFixture, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        super().setUp()
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(contract.adapt(self.backend.load()), contract.CLAUDE, "Import rename API fixture",
                       contents={}, dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def count(self):
        with self.connect() as connection:
            return connection.execute("select count(*) from audit.change_set").fetchone()[0]

    def test_preview_changes_no_data_and_confirmation_returns_saved_revision(self):
        before, count = self.backend.load(), self.count()
        proposal = self.preview(title="  A\u200b better   name  ")
        self.assertEqual((proposal["title"], proposal["new_id"]), ("A better name", "casual/a-better-name"))
        self.assertTrue(proposal["changed"])
        self.assertEqual(proposal["decks_revision"], before.decks_revision)
        self.assert_unchanged(before)
        self.assertEqual(self.count(), count)
        answer = self.confirm(proposal)
        saved = self.backend.load().deck(answer["id"])
        self.assertTrue(answer["renamed"])
        self.assertEqual(answer["previous_id"], fixture.DECK_ID)
        self.assertEqual((answer["sha256"], answer["revision"]), (saved.sha256, saved.revision))
        self.assertGreater(saved.revision, before.deck(fixture.DECK_ID).revision)
        self.assertEqual(saved.text, before.deck(fixture.DECK_ID).text.replace("# Retirement fixture", "# A better name", 1))
        self.assertEqual(self.backend.load().revision, before.revision)
        self.assertEqual(self.count(), count + 1)

    def test_old_read_metadata_resolves_but_stale_write_requires_reload(self):
        proposal = self.preview()
        saved = self.confirm(proposal)
        view = rename.rename_view(fixture.DECK_ID)
        self.assertEqual((view["id"], view["requested_id"]), (saved["id"], fixture.DECK_ID))
        self.assertEqual(view["aliases"], [fixture.DECK_ID])
        count = self.count()
        error = self.assert_api_error(409, self.confirm, proposal)
        self.assertEqual(error.extra["canonical_id"], saved["id"])
        self.assertEqual(self.count(), count)
        with mock.patch.object(access, "viewer", return_value="user1"):
            self.assert_api_error(403, self.confirm, proposal, profile="user1")

    def test_changed_title_hash_revision_or_reviewed_id_refuses_without_write(self):
        before, count = self.backend.load(), self.count()
        proposal = self.preview()
        for changes in ({"sha256": "0" * 64}, {"revision": proposal["revision"] + 1},
                        {"title": "Another name"}, {"new_id": "commander/a-better-name"},
                        {"decks_revision": "obsolete"}):
            with self.subTest(changes=changes):
                self.assert_api_error(409, self.confirm, proposal, **changes)
                self.assert_unchanged(before)
                self.assertEqual(self.count(), count)

    def test_another_deck_edit_invalidates_review(self):
        proposal = self.preview()
        other = self.backend.load().deck("casual/building")
        inventory.apply(inventory.Op("deck.save", {"deck_id": other.id, "base_sha256": other.sha256,
                                                   "text": other.text + "\nAnother editor's note.\n"}),
                        contract.CLAUDE, "Edit another fixture deck")
        before, count = self.backend.load(), self.count()
        self.assert_api_error(409, self.confirm, proposal)
        self.assert_unchanged(before)
        self.assertEqual(self.count(), count)

    def test_confirmation_rechecks_permissions_inside_the_transaction(self):
        proposal = self.preview()
        original = inventory.apply

        def permission_change(operation, *args, **kwargs):
            from decklab.lib.api import guard
            with mock.patch.object(guard, "require", side_effect=ApiError(403, "Permissions changed")):
                return original(operation, *args, **kwargs)

        before, count = self.backend.load(), self.count()
        with mock.patch.object(inventory, "apply", side_effect=permission_change):
            self.assert_api_error(403, self.confirm, proposal)
        self.assert_unchanged(before)
        self.assertEqual(self.count(), count)

    def test_confirmation_rechecks_library_revision_inside_the_transaction(self):
        proposal = self.preview()
        original = inventory.apply

        def another_writer(operation, *args, **kwargs):
            held = self.backend.load().deck("casual/building")
            original(inventory.Op("deck.save", {"deck_id": held.id, "base_sha256": held.sha256,
                                                "text": held.text + "\nChanged under the lock.\n"}),
                     contract.CLAUDE, "Concurrent fixture edit")
            return original(operation, *args, **kwargs)

        with mock.patch.object(inventory, "apply", side_effect=another_writer):
            self.assert_api_error(409, self.confirm, proposal)
        after = self.backend.load()
        self.assertIsNotNone(after.deck(fixture.DECK_ID))
        self.assertIsNone(after.deck(proposal["new_id"]))

    def test_built_deck_can_keep_exact_kit_without_requiring_kit_ownership(self):
        text = fixture.deck_text("User1 built", "built", "wife").replace(
            "- **Status:** built\n", "- **Status:** built\n- **Sleeves:** private old blue\n- **Deck box:** private old box\n")
        inventory.apply(inventory.Op("deck.create", {"space": "home", "kind": "casual", "slug": "user1-built",
                                                    "text": text, "owners": None}),
                        contract.CLAUDE, "Create private kit fixture")
        held = self.backend.load().deck("casual/user1-built")
        from decklab.lib.api import guard
        with mock.patch.object(guard, "require_kit_choice", side_effect=AssertionError("No kit move")):
            proposal = self.preview(id=held.id, sha256=held.sha256, revision=held.revision, title="Built renamed")
            answer = self.confirm(proposal)
        saved = self.backend.load().deck(answer["id"])
        self.assertEqual(saved.text, held.text.replace("# User1 built", "# Built renamed", 1))
        self.assertNotIn("private old", json.dumps(proposal))
        self.assertNotIn("private old", json.dumps(answer))

    def test_unchanged_title_and_id_do_not_add_audit_or_revision(self):
        # Existing title differs from its slug, so first make them agree.
        first = self.confirm(self.preview(title="Retire me"))
        held = self.backend.load().deck(first["id"])
        proposal = self.preview(id=held.id, sha256=held.sha256, revision=held.revision, title="Retire me")
        self.assertFalse(proposal["changed"])
        before, count = self.backend.load(), self.count()
        self.assertFalse(self.confirm(proposal)["renamed"])
        self.assert_unchanged(before)
        self.assertEqual(self.count(), count)
