"""A resumed fake gauntlet keeps its saved sample and tops up, without redrawing or real games."""
from unittest import mock

from decklab.lib import api, jobs
from decklab.lib.api import gauntlet_page, run_recovery as recovery
from decklab.lib.forge import run_journal
from decklab.tests.test_gauntlet_api import GRUUL, WAIT, GauntletApiTestCase, body


class RecoveryGauntletTests(GauntletApiTestCase):
    def test_resume_uses_original_sample_budget_and_only_the_synthetic_checkpoint_remainder(self):
        self.g.gate.clear()
        with self.as_("matt"):
            gauntlet_page.run_gauntlet(body("matt", id=GRUUL, budget="fixed:200"))
        self.assertTrue(self.g.started.wait(WAIT))
        runner = api.forge_runs.COORD_JOBS
        job = runner.active()[0]
        runner.stop()
        self.assertTrue(job.wait(WAIT))
        record, = run_journal.store().records("matt")
        sample = record["request"]["sample"]
        replacement = jobs.Runner(max_running=1, log=lambda text: None, describe=api.forge_runs._matchup_error)
        self.enterContext(mock.patch.object(api.forge_runs, "COORD_JOBS", replacement))
        self.addCleanup(lambda: (replacement.stop(), replacement.join(WAIT)))
        original = self.g.plan
        for ref in record["manifest"]["refs"]:
            if recovery._is_sparring(ref["id"]):
                self.g.have[ref["id"]] = 65
        def checkpoint(entry, chosen, budget):
            plan = original(entry, chosen, budget)
            for pair in plan["pairs"]:
                pair["games"] = max(0, plan["per_opponent"] - self.g.have.get(pair["opponent"]["id"], 0))
            plan["new_games"] = sum(pair["games"] for pair in plan["pairs"])
            return plan
        asked = []
        def finish(entry, chosen, budget, **options):
            plan = checkpoint(entry, chosen, budget)
            asked.append((chosen["id"], budget, [(pair["have"], pair["games"]) for pair in plan["pairs"]]))
            for pair in plan["pairs"]:
                self.g.have[pair["opponent"]["id"]] = plan["per_opponent"]
            return {"played": plan["new_games"]}
        with mock.patch.object(self.g, "plan", side_effect=checkpoint), mock.patch.object(self.g, "run", side_effect=finish), \
                mock.patch.object(self.g, "draw", wraps=self.g.draw) as draw, mock.patch.object(self.g, "sample", wraps=self.g.sample) as load_sample:
            with self.as_("matt"):
                self.assertTrue(recovery.view()["unfinished"][0]["may_resume"])
                self.assertTrue(recovery.resume(body("matt", id=record["id"]))["resumed"])
            self.assertTrue(replacement.get(next(iter(replacement._jobs))).wait(WAIT))
        self.assertTrue(load_sample.called)
        self.assertTrue(all(call.args == (sample,) for call in load_sample.call_args_list))
        self.assertTrue(all(call.kwargs.get("save") is False for call in draw.call_args_list),
                        "a standard-sample comparison may be read, but no new run sample is drawn/saved")
        self.assertEqual(asked[0][:2], (sample, "fixed:200"))
        self.assertTrue(all(have == 65 and rest == 135 for have, rest in asked[0][2]))
        self.assertEqual(run_journal.store().records("matt"), [])
