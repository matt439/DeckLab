"""Explicit recovery over fake coordinators and synthetic checkpoints, never a Forge game."""
import contextlib
import json
from unittest import mock

from decklab.lib import access, api, jobs, state
from decklab.lib.api import field_page, run_recovery as recovery
from decklab.lib.forge import run_journal
from decklab.tests.test_field_api import ELVES, WAIT, FieldApiTestCase, body
from decklab.tests.test_api import _write


class RecoveryTests(FieldApiTestCase):
    @contextlib.contextmanager
    def who(self, name):
        with access.using({"profile": name, "email": "", "remote": True} if name else None), \
                access.viewing(None), access.answering(False):
            yield

    def interrupted(self, starter="matt"):
        self.field.gate.clear()
        with self.who(starter):
            field_page.run_field(body(profile=starter, id=ELVES, budget="quick"))
        self.assertTrue(self.field.started.wait(WAIT))
        runner = api.forge_runs.COORD_JOBS
        job = runner.active()[0]
        runner.stop()
        self.assertTrue(job.wait(WAIT))
        record, = run_journal.store().records(starter)
        self.assertEqual(record["state"], "interrupted")
        replacement = jobs.Runner(max_running=1, max_queued=4, log=lambda text: None,
                                  describe=api.forge_runs._matchup_error, name="synthetic recovery")
        self.enterContext(mock.patch.object(api.forge_runs, "COORD_JOBS", replacement))
        self.addCleanup(lambda: (replacement.stop(), replacement.join(WAIT)))
        return record, replacement

    def test_offer_is_only_for_its_named_starter_no_admin_override_or_anonymous_script_and_view_never_queues(self):
        record, runner = self.interrupted("user1")
        with self.who("matt"):
            self.assertEqual(recovery.view(), {"available": True, "unfinished": []})
            with self.assertRaises(api.ApiError) as denied:
                recovery.resume(body(profile="matt", id=record["id"]))
            self.assertEqual(denied.exception.status, 404)
        with access.using(None), access.viewing(None), access.answering(True), \
                mock.patch.object(run_journal.store(), "records", side_effect=AssertionError("No unnamed read")):
            self.assertEqual(recovery.view(), {})
            with self.assertRaises(api.ApiError) as denied:
                recovery.resume(body(profile="user1", id=record["id"]))
            self.assertEqual(denied.exception.status, 403)
        with self.who("user1"), mock.patch.object(runner, "submit", side_effect=AssertionError("GET never starts work")):
            found = recovery.view()
        self.assertTrue(found["available"])
        self.assertEqual(found["unfinished"][0]["id"], record["id"])
        self.assertTrue(found["unfinished"][0]["may_resume"])
        self.assertNotIn("request", found["unfinished"][0])

    def test_empty_journal_is_neutral_without_reading_optional_engine_or_database_visibility(self):
        with self.who("matt"), \
                mock.patch.object(self.box.state, "visibility", side_effect=AssertionError("No empty-journal database read")), \
                mock.patch.object(self.forge.engine, "read_only_today", side_effect=AssertionError("No optional Forge read")):
            self.assertEqual(recovery.view(), {"available": True, "unfinished": []})

    def test_unknown_original_server_ownership_disables_resume_but_allows_own_explicit_dismiss(self):
        record, runner = self.interrupted()
        journal = run_journal.store()
        with self.who("matt"), mock.patch.object(journal, "inactive", return_value=None), \
                mock.patch.object(runner, "submit", side_effect=AssertionError("No unverified work")), \
                mock.patch.object(recovery, "_preview", side_effect=AssertionError("Unknown lease precedes replanning")):
            offer, = recovery.view()["unfinished"]
            self.assertFalse(offer["may_resume"])
            self.assertIn("ownership cannot be verified", offer["why_not"])
            with self.assertRaises(api.ApiError) as refused:
                recovery.resume(body(profile="matt", id=record["id"]))
            self.assertEqual(refused.exception.status, 503)
            self.assertEqual(recovery.dismiss(body(profile="matt", id=record["id"])), {"dismissed": True})
        self.assertEqual(journal.records("matt"), [])

    def test_resume_replans_from_fake_saved_games_with_original_resolved_budget_and_keeps_all_saved_work(self):
        record, runner = self.interrupted()
        self.field.games = 75                 # synthetic checkpoint, not a real played game
        original = self.field.plan
        def checkpoint_plan(entry, budget, **options):
            plan = original(entry, budget, **options)
            target = plan["per_opponent"]
            for pair in plan["pairs"]:
                pair.update(have=self.field.games, floor=max(0, target - self.field.games),
                            games=max(0, target - self.field.games))
            plan["new_games"] = sum(pair["games"] for pair in plan["pairs"])
            return plan
        asked = []
        def finish(entry, budget, *, by, progress, **options):
            plan = checkpoint_plan(entry, budget, **options)
            asked.append((budget, self.field.games, plan["new_games"]))
            progress(0, plan["new_games"])
            self.field.games += plan["new_games"]
            return {"played": plan["new_games"]}
        with mock.patch.object(self.field, "plan", side_effect=checkpoint_plan), \
                mock.patch.object(self.field, "run_field", side_effect=finish), \
                mock.patch.object(field_page, "_field_budget", return_value="thorough"):
            with self.who("matt"):
                self.assertEqual(recovery.resume(body(profile="matt", id=record["id"])), {"resumed": True, "complete": False})
            self.assertTrue(runner.get(next(iter(runner._jobs))).wait(WAIT))
        self.assertEqual(asked, [("quick", 75, 125)])
        self.assertEqual(self.field.games, 200)
        self.assertEqual(run_journal.store().records("matt"), [])

    def test_list_or_engine_change_refuses_before_work_and_current_simulation_policy_is_rechecked(self):
        record, runner = self.interrupted()
        engine = self.forge.engine.today()
        with mock.patch.object(self.forge.engine, "read_only_today", return_value={**engine, "forge": "changed fixture"}), \
                self.who("matt"), mock.patch.object(runner, "submit", side_effect=AssertionError("No changed-engine work")):
            self.assertFalse(recovery.view()["unfinished"][0]["may_resume"])
            with self.assertRaises(api.ApiError) as refused:
                recovery.resume(body(profile="matt", id=record["id"]))
            self.assertEqual(refused.exception.status, 409)
        with self.who("matt"):
            api.change_simulations(body(profile="matt", mode="paused"))
            with self.assertRaises(api.ApiError) as refused:
                recovery.resume(body(profile="matt", id=record["id"]))
            self.assertEqual(refused.exception.status, 403)
            api.change_simulations(body(profile="matt", mode="everyone"))
        path = self.box.magic / "decks/commander/elf-commander.md"
        text = path.read_text(encoding="utf-8")
        _write(path, text.replace("Llanowar Elves", "Elvish Mystic"))
        with self.who("matt"), mock.patch.object(runner, "submit", side_effect=AssertionError("No changed-list work")):
            with self.assertRaises(api.ApiError) as refused:
                recovery.resume(body(profile="matt", id=record["id"]))
            self.assertEqual(refused.exception.status, 409)

    def test_finished_checkpoint_is_not_offered_dismiss_starts_nothing_and_unreadable_visibility_is_unknown(self):
        record, runner = self.interrupted()
        original = self.field.plan
        def complete(entry, budget, **options):
            return {**original(entry, budget, **options), "new_games": 0}
        with self.who("matt"), mock.patch.object(self.field, "plan", side_effect=complete), \
                mock.patch.object(runner, "submit", side_effect=AssertionError("No finished replay")):
            self.assertEqual(recovery.view(), {"available": True, "unfinished": []})
        self.assertEqual(run_journal.store().records("matt"), [])
        record = run_journal.store().create("matt", "field", record["request"], record["manifest"])
        run_journal.store().transition("matt", record["id"], "interrupted")
        with self.who("matt"), mock.patch.object(self.box.state, "visibility", side_effect=state.Unavailable("PRIVATE_ERROR")), \
                mock.patch.object(self.box.state, "visibility_cached", side_effect=AssertionError("No cached grant")):
            self.assertFalse(recovery.view()["available"])
            with self.assertRaises(api.ApiError) as refused:
                recovery.resume(body(profile="matt", id=record["id"]))
            self.assertEqual(refused.exception.status, 503)
        with self.who("matt"), mock.patch.object(runner, "submit", side_effect=AssertionError("Dismiss starts no work")):
            self.assertEqual(recovery.dismiss(body(profile="matt", id=record["id"])), {"dismissed": True})
        self.assertEqual(run_journal.store().records("matt"), [])
