"""Published participants are rechecked; admin roles never inherit another starter's request."""
from unittest import mock

from decklab.lib import api, jobs, state
from decklab.lib.api import field_group, run_recovery as recovery
from decklab.lib.forge import run_journal
from decklab.tests.test_field_group_api import GRUUL, R_ELVES, WAIT, GroupApiTestCase, body


class RecoveryPrivacyTests(GroupApiTestCase):
    def test_revoked_public_participant_hides_the_whole_offer_before_engine_or_request_preview(self):
        actor = state.Actor("test", "Fixture", source="test")
        self.box.state.visibility_set("user2", "decks", True, actor, "Publish fixture")
        self.g.gate.clear()
        self.call("matt", field_group.run_group, body("matt", id=GRUUL, opponents=[R_ELVES], budget="quick"))
        self.assertTrue(self.g.started.wait(WAIT))
        runner = api.forge_runs.COORD_JOBS
        job = runner.active()[0]
        runner.stop()
        self.assertTrue(job.wait(WAIT))
        record, = run_journal.store().records("matt")
        replacement = jobs.Runner(max_running=1, log=lambda text: None)
        self.enterContext(mock.patch.object(api.forge_runs, "COORD_JOBS", replacement))
        self.addCleanup(lambda: (replacement.stop(), replacement.join(WAIT)))
        with self.as_("matt"):
            self.assertTrue(recovery.view()["unfinished"][0]["may_resume"])
        self.box.state.visibility_set("user2", "decks", False, actor, "Unpublish fixture")
        with self.as_("matt"), mock.patch.object(recovery, "_preview", side_effect=AssertionError("No hidden preview")):
            self.assertEqual(recovery.view(), {"available": True, "unfinished": []})
            for function in (recovery.resume, recovery.dismiss):
                with self.assertRaises(api.ApiError) as denied:
                    function(body("matt", id=record["id"]))
                self.assertEqual(denied.exception.status, 404)
        with self.as_("user2"):
            self.assertEqual(recovery.view(), {"available": True, "unfinished": []})
            with self.assertRaises(api.ApiError) as denied:
                recovery.resume(body("user2", id=record["id"]))
            self.assertEqual(denied.exception.status, 404)
        self.assertEqual(replacement.active(), [])
