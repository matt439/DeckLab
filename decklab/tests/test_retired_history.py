"""Read retired saved-deck history using fixture revisions; never recreate a deck."""
import json
from datetime import timedelta
from unittest import mock

from decklab.lib import access, inventory, permissions
from decklab.lib.api import history
from decklab.tests.test_api import ApiTestCase, GRUUL
from decklab.tests.test_deck_history import SHA_A, WHEN, install, revision


class RetiredHistoryTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.deck_id = "casual/gruul-test"
        self.path = self.box.magic / "decks/casual/gruul-test.md"
        self.old = GRUUL.replace("- **Played by:** either", "- **Played by:** user")
        self.last = self.old.replace("# Gruul Test", "# Last Retired Title").replace(
            "- **Played by:** user", "- **Played by:** wife")
        self.path.unlink()
        self.backend = install(self.box, {self.deck_id: [
            revision(self.deck_id, 1, self.old, op="A", actor="matt", message="First saved\nprivate body", commit=SHA_A),
            revision(self.deck_id, 2, self.last, actor="user1", message="Last saved", at=WHEN + timedelta(hours=1)),
            revision(self.deck_id, 3, None, op="D", actor="user1", message="Retire deck", at=WHEN + timedelta(hours=2))]})

    def test_retired_history_has_no_current_fingerprint_or_editor_save(self):
        value = history.deck_history(self.deck_id)
        self.assertEqual(value["title"], "Last Retired Title")
        self.assertTrue(value["retired"])
        self.assertTrue(value["may_restore"])
        self.assertFalse(value["may_save"])
        self.assertIsNone(value["sha256"])
        self.assertEqual(value["retired_revision"], 3)
        self.assertEqual([r["revision"] for r in value["revisions"]], [3, 2, 1])
        self.assertEqual(value["revisions"][0]["change"]["kind"], "deleted")
        self.assertEqual(value["revisions"][-1]["subject"], "First saved")
        self.assertFalse(self.path.exists())

    def test_retired_revision_has_no_editor_state_and_keeps_old_commit_links(self):
        with mock.patch.object(history, "edit_view", side_effect=AssertionError("retired deck has no editor")):
            for number in (1, "1", SHA_A):
                value = history.deck_revision(self.deck_id, number)
                self.assertEqual(value["revision"], 1)
                self.assertTrue(value["retired"])
                self.assertIsNone(value["current"])
                self.assertEqual(value["title"], "Gruul Test")
                self.assertEqual(value["sections"]["Deck"][0]["qty"], 4)
        self.assertApiError(404, history.deck_revision, self.deck_id, "3")
        self.assertFalse(self.path.exists())

    def test_retired_record_reads_only_latest_deletion_and_exact_final_text(self):
        calls = []

        def read(deck_id, limit):
            calls.append((deck_id, limit))
            return list(reversed(self.backend.revisions[deck_id]))[:limit]

        self.backend.deck_revisions_with_text = read
        self.backend.deck_revision = mock.Mock(side_effect=AssertionError("per-revision reads"))
        space, kind, slug, final, parsed, deleted = history.retired_record(self.deck_id)
        self.assertEqual((space, kind, slug), ("home", "casual", "gruul-test"))
        self.assertEqual((final.revision, final.text, parsed.player, deleted), (2, self.last, "wife", 3))
        self.assertEqual(calls, [(self.deck_id, 2)])

    def test_just_the_initial_saved_revision_and_deletion_are_sufficient(self):
        self.backend.revisions[self.deck_id] = [revision(self.deck_id, 1, self.old, op="A"),
                                               revision(self.deck_id, 2, None, op="D")]
        self.assertEqual(history.retired_record(self.deck_id)[3].revision, 1)
        value = history.deck_history(self.deck_id)
        self.assertEqual(value["retired_revision"], 2)
        self.assertEqual(len(value["revisions"]), 2)

    def test_restore_permission_uses_final_retired_owner_not_selected_old_revision(self):
        for profile, expected in (({"id": "matt", "role": "member", "space": "home", "plays_as": "user"}, False),
                                  ({"id": "user1", "role": "member", "space": "home", "plays_as": "wife"}, True)):
            with self.subTest(profile=profile["id"]), \
                    mock.patch.object(history.guard, "viewer", return_value=profile), \
                    mock.patch.object(history.guard, "local", return_value=False):
                value = history.deck_history(self.deck_id)
                self.assertEqual(value["may_restore"], expected)
                self.assertFalse(value["may_save"])
                self.assertIsNone(history.deck_revision(self.deck_id, 1)["current"])

    def test_both_edit_and_create_rights_are_required_for_whole_text_restore(self):
        real_reason = permissions.reason

        def reason(profile, action, target=None, **kwargs):
            return "No creating decks" if action == "deck.create" else real_reason(profile, action, target, **kwargs)

        with mock.patch.object(permissions, "reason", side_effect=reason):
            self.assertFalse(history.deck_history(self.deck_id)["may_restore"])

    def test_built_or_kit_holding_retired_text_is_never_offered_for_restore(self):
        for text in (self.last.replace("- **Status:** building", "- **Status:** built"),
                     self.last.replace("- **Status:** building", "- **Status:** building\n- **Sleeves:** old-red"),
                     self.last.replace("- **Status:** building", "- **Status:** building\n- **Deck box:** private-box")):
            with self.subTest(text=text):
                self.backend.revisions[self.deck_id][1] = revision(self.deck_id, 2, text)
                value = history.deck_history(self.deck_id)
                self.assertTrue(value["retired"])
                self.assertFalse(value["may_restore"])

    def test_legacy_slug_that_cannot_be_created_keeps_readable_history_without_restore(self):
        deck_id = "casual/Legacy_Name"
        self.backend.revisions[deck_id] = [revision(deck_id, 1, self.last, op="A"),
                                           revision(deck_id, 2, None, op="D")]
        value = history.deck_history(deck_id)
        self.assertTrue(value["retired"])
        self.assertFalse(value["may_restore"])
        self.assertFalse(value["may_save"])
        self.assertEqual(value["title"], "Last Retired Title")

    def test_reused_id_is_active_and_cannot_resurrect_an_older_retired_identity(self):
        active = self.last.replace("Last Retired Title", "Active Again")
        self.path.write_text(active, encoding="utf-8")
        self.backend.revisions[self.deck_id].append(revision(self.deck_id, 4, active, op="A"))
        value = history.deck_history(self.deck_id)
        self.assertFalse(value["retired"])
        self.assertFalse(value["may_restore"])
        self.assertIsNone(value["retired_revision"])
        self.assertTrue(value["may_save"])
        self.assertEqual(value["title"], "Active Again")
        self.assertIsNotNone(value["sha256"])
        selected = history.deck_revision(self.deck_id, 1)
        self.assertFalse(selected["retired"])
        self.assertEqual(selected["current"]["title"], "Active Again")
        self.assertApiError(409, history.retired_record, self.deck_id)

    def test_missing_or_not_deleted_identity_is_not_a_retired_deck(self):
        for revisions in ([], [revision(self.deck_id, 1, self.old, op="A")]):
            with self.subTest(revisions=revisions):
                self.backend.revisions[self.deck_id] = revisions
                self.assertApiError(404, history.retired_record, self.deck_id)
                self.assertApiError(404, history.deck_history, self.deck_id)
                self.assertApiError(404, history.deck_revision, self.deck_id, "1")

    def test_corrupt_immediate_text_never_falls_back_to_an_older_owner(self):
        for final in (revision(self.deck_id, 2, "not a deck"), revision(self.deck_id, 2, None),
                      revision(self.deck_id, 2, None, op="D"), revision(self.deck_id, 1, self.old)):
            with self.subTest(final=final):
                self.backend.revisions[self.deck_id] = [revision(self.deck_id, 1, self.old, op="A"), final,
                                                       revision(self.deck_id, 3, None, op="D")]
                self.assertApiError(500, history.retired_record, self.deck_id)
                self.assertApiError(500, history.deck_history, self.deck_id)
                self.assertApiError(500, history.deck_revision, self.deck_id, 1)

    def test_retired_kit_fields_diffs_and_actor_messages_keep_their_redactions(self):
        kit = self.last.replace("- **Status:** building", "- **Status:** building\n- **Sleeves:** user1-private")
        older = kit.replace("user1-private", "user1-old")
        self.backend.revisions[self.deck_id] = [
            revision(self.deck_id, 1, older, op="A", actor="user1", kit=True, message="Use user1-old"),
            revision(self.deck_id, 2, kit, actor="user1", kit=True, message="Use user1-private"),
            revision(self.deck_id, 3, None, op="D", actor="user1", kit=True, message="Retire user1-private")]
        for who in ("matt", "user1"):
            with self.subTest(who=who), access.using({"profile": who, "email": "", "remote": True}):
                value = history.deck_history(self.deck_id)
                selected = history.deck_revision(self.deck_id, 2)
                if who == "matt":
                    self.assertNotIn("user1-private", json.dumps(value))
                    self.assertIsNone(selected["fields"]["Sleeves"])
                    self.assertIsNone(selected["history"]["subject"])
                else:
                    self.assertEqual(value["revisions"][0]["subject"], "Retire user1-private")
                    self.assertEqual(selected["fields"]["Sleeves"], "user1-private")

    def test_unknown_actor_is_masked_in_retired_history(self):
        self.backend.revisions[self.deck_id][-1] = revision(self.deck_id, 3, None, op="D", actor="zed")
        with access.using({"profile": "matt", "email": "", "remote": True}):
            value = history.deck_history(self.deck_id)["revisions"][0]
            self.assertIsNone(value["actor"])
            self.assertEqual(value["author"], "someone")

    def test_retired_history_keeps_the_cap_and_one_bulk_read_for_diffs(self):
        self.backend.revisions[self.deck_id] = [revision(self.deck_id, n, self.last) for n in range(1, 107)]
        self.backend.revisions[self.deck_id].append(revision(self.deck_id, 107, None, op="D"))
        calls = []

        def read(deck_id, limit):
            calls.append(limit)
            return list(reversed(self.backend.revisions[deck_id]))[:limit]

        self.backend.deck_revisions_with_text = read
        self.backend.deck_revision = mock.Mock(side_effect=AssertionError("per-revision reads"))
        value = history.deck_history(self.deck_id)
        self.assertTrue(value["truncated"])
        self.assertEqual(len(value["revisions"]), history.MAX_REVISIONS)
        self.assertEqual(value["retired_revision"], 107)
        self.assertEqual(calls, [history.MAX_REVISIONS + 1])

    def test_retired_history_respects_the_deck_visibility_boundary(self):
        with mock.patch.object(history.guard, "sees_deck", return_value=False):
            self.assertApiError(404, history.retired_record, self.deck_id)
            self.assertApiError(404, history.deck_history, self.deck_id)
            self.assertApiError(404, history.deck_revision, self.deck_id, 1)

    def test_product_pairing_and_bad_ids_keep_existing_refusals(self):
        for deck_id in ("product/fdc-test-precon", "pairing/cats+elves", "casual/../other"):
            with self.subTest(deck_id=deck_id):
                self.assertApiError(400, history.retired_record, deck_id)
