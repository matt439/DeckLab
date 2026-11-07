"""Public variant reads and owner-only changes; every job and result is a fixture."""
import json
from unittest import mock

from decklab.lib import api, inventory, jobs, state
from decklab.lib.api import forge_runs, guard, variant_page
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state.memory import MemoryStore
from decklab.tests import test_forge
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_privacy_readers import R_DECK_ID, _as
from decklab.tests.test_matchups_api import deck_file
from decklab.tests.test_variant_api import VariantApiCase, GREEN_ID, RED_ID, SWAPPED, body, editor_list
from decklab.lib.forge import variants


class VariantPrivacyTests(VariantApiCase):
    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(ROLES))
        _write(self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md",
               deck_file("User2 private sentinel", test_forge.RED))
        self.addCleanup(inventory.use(FileInventory(self.box.root)))
        self.addCleanup(state.use(MemoryStore(mode="everyone")))

    def test_result_editor_capability_is_current_for_owner_and_public_readonly_viewer(self):
        # Generate a disposable result through the ordinary run/view path (the existing fake game runner).
        with _as("matt"):
            test = self.start()["test"]["test"]
            self.assertTrue(self.wait_done(test)["may_edit"])
        with mock.patch.object(guard, "public_deck_spaces", return_value={"home"}), _as("user2"):
            answer = api.variant_view(test)
            self.assertFalse(answer["may_edit"])
            self.assertEqual(answer["test"]["base"]["id"], GREEN_ID)
            self.assertFalse(api.edit_view(GREEN_ID)["may_save"])
        # Home membership alone does not allow an either-player deck edit.
        with _as("user1"):
            self.assertFalse(api.variant_view(test)["may_edit"])
        path = self.box.magic / "decks" / "casual" / "green-test.md"
        _write(path, path.read_text(encoding="utf-8").replace("Played by:** either", "Played by:** wife"))
        with _as("user1"):
            self.assertTrue(api.variant_view(test)["may_edit"])
        with _as("user2"):
            self.assertApiError(404, api.variant_view, test)

    def test_member_result_has_editor_handoff_through_production_view(self):
        # Seed a real member deck/list and use the normal API visibility and capability path.
        _write(self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md",
               deck_file("Member example", test_forge.GREEN))
        with mock.patch.object(guard, "public_deck_spaces", return_value={"home"}), _as("user2"):
            answer = api.run_variant(body(profile="user2", id=R_DECK_ID, version="target", list=editor_list(SWAPPED),
                                          against={"id": RED_ID, "version": "target"}))
            done = self.wait_done(answer["test"]["test"])
            self.assertEqual(done["test"]["base"]["id"], R_DECK_ID)
            self.assertTrue(done["may_edit"])
            self.assertTrue(api.edit_view(R_DECK_ID)["may_save"])

    def test_handoff_capability_rejects_generated_missing_and_unreadable_decks(self):
        with _as("matt"):
            for deck_id in (None, "casual/not-there", "product/fdc-test-precon", "pairing/cats+elves"):
                self.assertFalse(variant_page._may_edit(deck_id))
            for summary in ({"id": GREEN_ID, "error": "unreadable"}, {"id": GREEN_ID, "read_only": True}):
                with mock.patch.object(variant_page.decks, "find_summary", return_value=summary):
                    self.assertFalse(variant_page._may_edit(GREEN_ID))
            with mock.patch.object(variant_page.decks, "find_summary", side_effect=inventory.StateError("unreadable")):
                self.assertFalse(variant_page._may_edit(GREEN_ID))

    def test_public_draft_test_requires_the_bases_own_space(self):
        data = body(profile="user1", id=R_DECK_ID, version="target", list=editor_list(SWAPPED),
                    against={"id": RED_ID, "version": "target"})
        with mock.patch.object(guard, "public_deck_spaces", return_value={"user2"}), _as("user1"):
            self.assertApiError(403, api.run_variant, data, contains="own collection")
            self.assertEqual(api.matchup(R_DECK_ID, "target", RED_ID, "target")["status"], "none")
        self.assertEqual(self.calls, [])

    def test_hidden_field_opponent_also_hides_old_job_errors(self):
        with mock.patch.object(guard, "public_deck_spaces", return_value={"user2"}), _as("matt"):
            test = self.start(against={"id": R_DECK_ID, "version": "target"})["test"]["test"]
            self.wait_done(test)
        summary = variants.load_summary(test)
        summary["against"] = "field:home:Constructed"
        variants._write_summary(summary, None)
        job = forge_runs.COORD_JOBS.get("variant:" + test)
        snap = {"status": jobs.ERROR, "detail": {"pairs": {}}, "error": "User2 private sentinel failed",
                "ahead": 0, "progress": {"done": 0, "total": 100}, "seconds": 2}
        with mock.patch.object(forge_runs.COORD_JOBS, "snapshot", return_value=snap), _as("matt"):
            answer = api.variant_view(test)
            listed = api.variant_tests(GREEN_ID)
        self.assertIsNotNone(job)
        self.assertIsNone(answer["error"])
        self.assertEqual(answer["opponents"], [])
        self.assertIsNone(answer["words"])
        self.assertNotIn("User2 private sentinel", json.dumps((answer, listed)))
        self.assertNotIn(R_DECK_ID, json.dumps((answer, listed)))
