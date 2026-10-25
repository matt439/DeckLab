"""Public variant reads and owner-only changes; every job and result is a fixture."""
import json
from unittest import mock

from decklab.lib import api, inventory, jobs, state
from decklab.lib.api import forge_runs, guard
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
