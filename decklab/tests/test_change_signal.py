"""Fresh per-viewer signals over synthetic files/memory: no real records, switches or database."""
import json
from unittest import mock

from decklab.lib import access, decks, inventory, state
from decklab.lib.api import changes, guard, library
from decklab.tests.test_api import _write
from decklab.tests.test_api_permissions import PermissionTestCase, R_DECK

ACTOR = state.Actor("test", "Fixture", source="test")


class ChangeSignalTests(PermissionTestCase):
    def test_only_completed_inventory_changes_mark_a_write_not_a_noop_or_plain_read(self):
        snapshot = inventory.current()
        with inventory.pinned(snapshot), mock.patch.object(inventory.backend(), "apply", return_value=(snapshot, inventory.Summary())) as apply:
            self.assertFalse(inventory.pinned_write())
            self.assertIs(inventory.pinned_snapshot(), snapshot)
            operation = inventory.Op("fixture.no-execution", {})
            inventory.apply(operation, ACTOR, "Synthetic no-op")
            self.assertFalse(inventory.pinned_write())
            apply.return_value = (snapshot, inventory.Summary(changed={"magic/collection.csv": ["synthetic"]}))
            inventory.apply(operation, ACTOR, "Synthetic committed change")
            self.assertTrue(inventory.pinned_write())
        self.assertIsNone(inventory.pinned_snapshot())

    def test_nested_commit_propagates_but_preview_noop_and_explicit_parent_view_remain_distinct(self):
        before = inventory.current()
        after = before.replace(revision="synthetic-committed")
        preview = before.replace(revision=before.revision + "~preview")
        operation = inventory.Op("fixture.no-execution", {})
        with inventory.pinned() as outer, mock.patch.object(inventory.backend(), "apply", return_value=(after, inventory.Summary())) as apply:
            outer()
            with inventory.pinned(preview):
                self.assertIs(inventory.current(), preview)
            self.assertFalse(inventory.pinned_write())
            with inventory.pinned():
                inventory.apply(operation, ACTOR, "Synthetic no-op")
            self.assertFalse(inventory.pinned_write())
            apply.return_value = (after, inventory.Summary(changed={"magic/collection.csv": ["synthetic"]}))
            with inventory.pinned():
                inventory.apply(operation, ACTOR, "Synthetic committed change")
            self.assertTrue(inventory.pinned_write())
            self.assertIs(inventory.current(), after)
            self.assertIs(inventory.pinned_committed_snapshot(), after)
        with inventory.pinned(before), mock.patch.object(inventory.backend(), "apply", return_value=(after, inventory.Summary(changed={"own": ["synthetic"]}))):
            with inventory.pinned():
                inventory.apply(operation, ACTOR, "Synthetic nested commit")
            self.assertIs(inventory.current(), before, "an explicitly given parent read/preview stays fixed")
            self.assertTrue(inventory.pinned_write())
            self.assertIs(inventory.pinned_committed_snapshot(), after)

    def answer(self, who, *, script=False):
        with access.using(None), access.viewing(who), access.answering(script):
            return changes.view()

    def test_unnamed_even_script_gets_nothing_before_any_data_read_and_named_answer_has_no_ids_or_counts(self):
        with mock.patch.object(inventory, "current", side_effect=AssertionError("No unnamed read")):
            self.assertEqual(self.answer(None), {})
            self.assertEqual(self.answer(None, script=True), {})
        answer = self.answer("user2")
        self.assertEqual(set(answer), {"ready", "inventory", "decks", "library"})
        self.assertTrue(answer["ready"])
        for name in ("inventory", "decks", "library"):
            self.assertRegex(answer[name], r"^[0-9a-f]{64}$")
        self.assertNotIn("user2", json.dumps(answer))

    def test_hidden_space_and_its_public_collection_changes_do_not_move_another_members_counters(self):
        before = self.answer("matt")
        _write(self.box.magic / "people/user2/decks/casual/r-elves.md", "PRIVATE_UNREADABLE_TEXT")
        _write(self.box.magic / "people/user2/collection.csv", "name,set,collector_number,finish,quantity,condition,language,notes\n"
               "PRIVATE_CARD,tst,1,nonfoil,999,NM,en,PRIVATE_NOTES\n")
        self.assertEqual(self.answer("matt"), before)
        self.box.state.visibility_set("user2", "collection", True, ACTOR, "Publish fixture collection")
        self.assertEqual(self.answer("matt"), before, "other Public collections retain explicit manual refresh")

    def test_global_revisions_other_space_aliases_and_other_spaces_home_records_do_not_move_member_signal(self):
        before = self.answer("user2")
        snapshot = inventory.current()
        moved = snapshot.replace(revision="999999", decks_revision="999999",
                                 deck_aliases={**snapshot.deck_aliases, "casual/private-old": "casual/gruul-test"})
        with mock.patch.object(inventory.backend(), "load", return_value=moved):
            self.assertEqual(self.answer("user2"), before)
        _write(self.box.magic / "decks/casual/gruul-test.md", "PRIVATE_HOME_BROKEN")
        self.assertEqual(self.answer("user2"), before)

    def test_other_home_owners_private_kit_and_unscoped_row_diagnostics_do_not_move_a_home_viewer(self):
        private_deck = R_DECK.replace("- **Status:** idea", "- **Played by:** wife\n- **Status:** built\n- **Sleeves:** private-a")
        _write(self.box.magic / "decks/casual/other-home.md", private_deck)
        _write(self.box.magic / "accessories.csv", "id,kind,owner,name,quantity,image\nprivate-a,sleeves,user1,PRIVATE_A,100,private.jpg\n")
        before = self.answer("matt")
        owner_before = self.answer("user1")
        with access.using(None), access.viewing("matt"), access.answering(False):
            legacy = library.viewer_decks_revision(guard.visible_decks(decks.list_decks()))
        _write(self.box.magic / "decks/casual/other-home.md", private_deck.replace("private-a", "private-b"))
        _write(self.box.magic / "accessories.csv", "id,kind,owner,name,quantity,image\nprivate-b,sleeves,user1,PRIVATE_B,700,new-private.jpg\n")
        self.assertEqual(self.answer("matt"), before)
        owner_after = self.answer("user1")
        self.assertNotEqual(owner_before["inventory"], owner_after["inventory"])
        self.assertNotEqual(owner_before["decks"], owner_after["decks"])
        with access.using(None), access.viewing("matt"), access.answering(False):
            self.assertEqual(library.viewer_decks_revision(guard.visible_decks(decks.list_decks())), legacy)
        snapshot = inventory.current()
        sheet = snapshot.accessories
        moved = snapshot.replace(accessories=type(sheet)(**{**sheet.__dict__, "problems": ("PRIVATE_OWNER_ROW",), "strict_error": "PRIVATE_OWNER_ROW"}))
        with mock.patch.object(inventory.backend(), "load", return_value=moved):
            self.assertEqual(self.answer("matt"), before)

    def test_own_inventory_and_deck_changes_move_only_the_relevant_own_signals(self):
        before = self.answer("user2")
        _write(self.box.magic / "people/user2/collection.csv", "name,set,collector_number,finish,quantity,condition,language,notes\n"
               "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\n")
        after = self.answer("user2")
        self.assertNotEqual(before["inventory"], after["inventory"])
        self.assertEqual(before["decks"], after["decks"])
        _write(self.box.magic / "people/user2/decks/casual/r-elves.md", R_DECK.replace("4 Llanowar", "3 Llanowar"))
        edited = self.answer("user2")
        self.assertNotEqual(edited["decks"], after["decks"])
        self.assertNotEqual(edited["library"], after["library"])
        self.assertEqual(edited["inventory"], after["inventory"])

    def test_unmapped_home_player_slot_never_becomes_shared_kit_in_either_digest(self):
        path = self.box.root / "config.json"
        configured = json.loads(path.read_text(encoding="utf-8"))
        configured["profiles"] = [person for person in configured["profiles"] if person["id"] != "user1"]
        _write(path, json.dumps(configured))
        text = R_DECK.replace("- **Status:** idea", "- **Played by:** wife\n- **Status:** built\n- **Sleeves:** private-a")
        deck = self.box.magic / "decks/casual/unmapped-slot.md"
        _write(deck, text)
        _write(self.box.magic / "accessories.csv", "id,kind,owner,name,quantity,image\nprivate-a,sleeves,user1,PRIVATE_A,100,private.jpg\n")
        before = self.answer("matt")
        with access.using(None), access.viewing("matt"), access.answering(False):
            legacy = library.viewer_decks_revision(guard.visible_decks(decks.list_decks()))
        _write(deck, text.replace("private-a", "private-b"))
        _write(self.box.magic / "accessories.csv", "id,kind,owner,name,quantity,image\nprivate-b,sleeves,user1,PRIVATE_B,400,new-private.jpg\n")
        self.assertEqual(self.answer("matt"), before)
        with access.using(None), access.viewing("matt"), access.answering(False):
            self.assertEqual(library.viewer_decks_revision(guard.visible_decks(decks.list_decks())), legacy)

    def test_public_deck_updates_move_visible_library_only_and_private_tables_or_kit_do_not(self):
        path = self.box.magic / "people/user2/decks/casual/r-elves.md"
        public_deck = R_DECK + "\n## Owned vs needed\n\nPRIVATE_TABLE_A\n"
        _write(path, public_deck)
        self.box.state.visibility_set("user2", "decks", True, ACTOR, "Publish fixture deck")
        before = self.answer("matt")
        _write(path, public_deck.replace("PRIVATE_TABLE_A", "PRIVATE_TABLE_B"))
        self.assertEqual(self.answer("matt"), before)
        _write(path, public_deck.replace("4 Llanowar", "3 Llanowar"))
        after = self.answer("matt")
        self.assertNotEqual(before["library"], after["library"])
        self.assertEqual(before["inventory"], after["inventory"])
        self.assertEqual(before["decks"], after["decks"])
        self.box.state.visibility_set("user2", "decks", False, ACTOR, "Unpublish fixture deck")
        self.assertNotEqual(after["library"], self.answer("matt")["library"])

    def test_stale_inventory_and_failed_fresh_visibility_are_unknown_without_cached_public_fallback(self):
        snapshot = inventory.current()
        with mock.patch.object(inventory.backend(), "load", return_value=snapshot.replace(stale="OLD_PRIVATE_ERROR")):
            self.assertEqual(self.answer("user2"), {"ready": False})
        with mock.patch.object(inventory.backend(), "load", return_value=snapshot.replace(backend="db", loans_ready=False)):
            self.assertEqual(self.answer("user2"), {"ready": False})
        with mock.patch.object(self.box.state, "visibility", side_effect=state.Unavailable("PRIVATE_ERROR")), \
                mock.patch.object(self.box.state, "visibility_cached", side_effect=AssertionError("No cached grant")) as cached:
            self.assertEqual(self.answer("user2"), {"ready": False})
        cached.assert_not_called()
        self.assertTrue(self.answer("user2")["ready"])

    def test_optional_profile_resolution_failure_is_unverified_before_any_inventory_read(self):
        from decklab.lib.api import guard
        with mock.patch.object(guard, "viewer", side_effect=RuntimeError("PRIVATE_PROFILE_ERROR")), \
                mock.patch.object(inventory.backend(), "load", side_effect=AssertionError("No inventory read")) as load:
            self.assertEqual(changes.current(), {"ready": False})
        load.assert_not_called()
