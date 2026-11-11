"""Variant recovery replays the exact accepted draft/mode through existing validated handlers."""
import copy
from unittest import mock

from decklab.lib import access, api, jobs
from decklab.lib.api import run_recovery as recovery, variant_page
from decklab.lib.forge import run_journal
from decklab.tests.test_variant_api import VariantApiCase, WAIT, body, real_forge


class RecoveryVariantTests(VariantApiCase):
    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.object(real_forge.engine, "read_only_today", side_effect=self.today))

    def test_changed_ai_profile_or_pilot_is_not_resumed_or_forgotten_even_if_the_new_plan_is_complete(self):
        self.gate.clear()
        with access.using(None), access.viewing("matt"), access.answering(False):
            answer = self.start(mode="quick")
        self.assertTrue(self.started.wait(WAIT))
        test = answer["test"]["test"]
        runner = api.forge_runs.COORD_JOBS
        runner.stop()
        self.assertTrue(runner.get("variant:" + test).wait(WAIT))
        record, = run_journal.store().records("matt")
        engine, original_entry = self.today(), real_forge.entry

        def changed_pilot(*args, **kwargs):
            entry = original_entry(*args, **kwargs)
            return {**entry, "pilot": {"profile": "Cautious", "switches": []}}

        changed_engine = {**engine, "ai_sha": {**engine["ai_sha"], "Default": "1" * 64}}
        for name, patch in (("AI profile bytes", mock.patch.object(real_forge.engine, "read_only_today", return_value=changed_engine)),
                            ("list pilot", mock.patch.object(real_forge, "entry", side_effect=changed_pilot))):
            with self.subTest(changed=name), patch, access.using(None), access.viewing("matt"), access.answering(False), \
                    mock.patch.object(variant_page, "_load_summary", return_value={"looks": [{"games_per_opponent": 10 ** 9}]}), \
                    mock.patch.object(runner, "submit", side_effect=AssertionError("No changed AI/pilot work")):
                offer, = recovery.view()["unfinished"]
                self.assertFalse(offer["may_resume"])
                with self.assertRaises(api.ApiError) as refused:
                    recovery.resume(body(profile="matt", id=record["id"]))
                self.assertEqual(refused.exception.status, 409)
                self.assertIsNotNone(run_journal.store().get("matt", record["id"]))

    def test_stopped_by_person_has_no_offer_but_server_stop_retains_draft_and_rechecks_before_replay(self):
        self.gate.clear()
        with access.using(None), access.viewing("matt"), access.answering(False):
            answer = self.start(mode="quick")
        self.assertTrue(self.started.wait(WAIT))
        test = answer["test"]["test"]
        runner = api.forge_runs.COORD_JOBS
        runner.stop()
        self.assertTrue(runner.get("variant:" + test).wait(WAIT))
        record, = run_journal.store().records("matt")
        original = copy.deepcopy(record["request"])
        self.assertEqual(original["mode"], "quick")
        self.assertIn("list", original)
        replacement = jobs.Runner(max_running=1, log=lambda text: None, describe=api.forge_runs._matchup_error)
        self.enterContext(mock.patch.object(api.forge_runs, "COORD_JOBS", replacement))
        self.addCleanup(lambda: (replacement.stop(), replacement.join(WAIT)))
        with access.using(None), access.viewing("matt"), access.answering(False):
            self.assertTrue(recovery.view()["unfinished"][0]["may_resume"])
            self.gate.set()
            self.assertEqual(recovery.resume(body(profile="matt", id=record["id"])), {"resumed": True, "complete": False})
        self.assertTrue(replacement.get("variant:" + test).wait(WAIT))
        self.assertEqual(run_journal.store().records("matt"), [])
        # A normal Stop is terminal even when a later process could read the same checkpoints.
        self.gate.clear()
        self.started.clear()
        with access.using(None), access.viewing("matt"), access.answering(False):
            self.start(mode="ahead")
        self.assertTrue(self.started.wait(WAIT))
        job = replacement.active()[0]
        replacement.cancel(job.key, by="Matt")
        self.assertTrue(job.wait(WAIT))
        self.assertEqual(run_journal.store().records("matt"), [])
