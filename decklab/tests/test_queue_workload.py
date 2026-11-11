"""Anonymous game-work summaries for queued Forge jobs; fixtures only."""
import json
import threading
import types
import unittest
from unittest import mock

from decklab.lib import api, inventory, jobs, state
from decklab.lib.api import field_group, field_page, forge_runs, gauntlet_page, run_recovery, variant_page
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state.memory import MemoryStore
from decklab.tests.test_api import GRUUL, _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_privacy_readers import R_DECK_ID, _as
from decklab.tests.test_matchups_api import ELVES, PRECON, MatchupTestCase

WAIT = 5


class Gate:
    def __init__(self, done=0, total=None, detail=None):
        self.done, self.total, self.detail = done, total, detail
        self.started, self.go = threading.Event(), threading.Event()

    def __call__(self, *, progress):
        progress(self.done, self.total, self.detail)
        self.started.set()
        if not self.go.wait(WAIT):
            raise TimeoutError("fixture gate was not released")


class WorkloadTests(unittest.TestCase):
    def setUp(self):
        self.runners, self.gates = [], []

    def tearDown(self):
        for runner in self.runners:
            runner.stop()
        for gate in self.gates:
            gate.go.set()
        for runner in self.runners:
            self.assertTrue(runner.join(WAIT))

    def runner(self, **options):
        runner = jobs.Runner(max_running=1, max_queued=20, log=lambda _: None, **options)
        self.runners.append(runner)
        return runner

    def gate(self, **options):
        gate = Gate(**options)
        self.gates.append(gate)
        return gate

    def start(self, runner, **options):
        gate = self.gate(**options)
        job = runner.submit("running-private-key", gate)
        self.assertTrue(gate.started.wait(WAIT))
        return job

    def queued(self, runner, key, games=None, approximate=False):
        work = {"games": games, "approximate": approximate} if games is not None else None
        return runner.submit(key, self.gate(), planned_work=work)

    def test_remaining_games_follow_progress_and_cancellation_without_self_or_later_work(self):
        runner = self.runner(track_game_work=True)
        running = self.start(runner, done=100, total=400, detail={"by": "Private starter", "wins": [80, 20]})
        earlier = self.queued(runner, "private-earlier", 800)
        target = self.queued(runner, "own-visible", 1600)
        self.queued(runner, "later-private", 10000)
        snap = runner.snapshot(target)
        self.assertEqual(snap["ahead"], 2)
        self.assertEqual(snap["ahead_work"], {"games": 1100, "unknown": 0, "approximate": False})
        self.assertEqual(set(snap["ahead_work"]), {"games", "unknown", "approximate"})
        self.assertTrue(runner.cancel(earlier.key))
        running.report(200, 400)
        self.assertEqual(runner.snapshot(target)["ahead_work"]["games"], 200)
        self.assertTrue(runner.cancel(running.key))  # not yet finished, but no remaining requested work
        self.assertEqual(runner.snapshot(target)["ahead_work"], {"games": 0, "unknown": 0, "approximate": False})

    def test_unreported_sizes_are_unknown_and_never_invented_as_zero(self):
        runner = self.runner(track_game_work=True)
        self.start(runner)
        self.queued(runner, "no-plan")
        for i, invalid in enumerate((True, -1, 0.5, "400", None)):
            runner.submit(f"invalid-{i}", self.gate(), planned_work={"games": invalid, "approximate": False})
        self.queued(runner, "known-zero", 0)
        target = self.queued(runner, "target", 200)
        self.assertEqual(runner.snapshot(target)["ahead_work"], {"games": 0, "unknown": 7, "approximate": False})

    def test_adaptive_max_uses_session_origin_and_not_the_current_stage(self):
        runner = self.runner(track_game_work=True)
        running = self.start(runner, done=200, total=400,
                             detail={"plan": {"max": 3200, "games_before": 800, "planned": 1200}})
        self.queued(runner, "adaptive-unstarted", 3200, approximate=True)
        target = self.queued(runner, "target", 200)
        self.assertEqual(runner.snapshot(target)["ahead_work"], {"games": 5400, "unknown": 0, "approximate": True})
        running.report(300, 400, {"plan": {"max": 3200, "games_before": 1600, "planned": 2000}})
        self.assertEqual(runner.snapshot(target)["ahead_work"]["games"], 4500)
        running.report(100, 200, {"plan": {"max": 3200}})
        self.assertEqual(runner.snapshot(target)["ahead_work"], {"games": 3200, "unknown": 1, "approximate": True})

    def test_running_coordinator_total_replaces_its_initial_cached_upper_bound(self):
        runner = self.runner(track_game_work=True)
        gate = self.gate(done=100, total=500)
        running = runner.submit("variant:private", gate, planned_work={"games": 6400, "approximate": True})
        self.assertTrue(gate.started.wait(WAIT))
        target = self.queued(runner, "target")
        self.assertEqual(runner.snapshot(target)["ahead_work"], {"games": 400, "unknown": 0, "approximate": True})
        gate.go.set()
        self.assertTrue(running.wait(WAIT))
        self.assertTrue(target.fn.started.wait(WAIT))
        self.assertNotIn("ahead_work", runner.snapshot(running))
        self.assertNotIn("ahead_work", runner.snapshot(target))

    def test_game_work_is_opt_in_and_queued_only(self):
        for enabled in (False, True):
            runner = self.runner(track_game_work=enabled)
            running = self.start(runner, done=3, total=10)
            target = self.queued(runner, "queued", 20)
            self.assertNotIn("ahead_work", runner.snapshot(running))
            self.assertEqual("ahead_work" in runner.snapshot(target), enabled)
            runner.cancel(target.key)
            self.assertNotIn("ahead_work", runner.snapshot(target))

    def test_joining_a_job_preserves_its_original_numeric_plan_copy(self):
        runner = self.runner(track_game_work=True)
        self.start(runner, total=0)
        plan = {"games": 400, "approximate": False, "private": "discarded"}
        earlier = runner.submit("earlier", self.gate(), planned_work=plan)
        plan["games"] = 99999
        self.assertIs(runner.submit("earlier", self.gate(), planned_work={"games": 900, "approximate": True}), earlier)
        target = self.queued(runner, "target")
        self.assertEqual(runner.snapshot(target)["ahead_work"], {"games": 400, "unknown": 0, "approximate": False})


class QueuePrivacyTests(MatchupTestCase):
    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(ROLES))
        member = self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md"
        _write(member, GRUUL.split("## Substitutes")[0].replace("# Gruul Test", "# User2 Copy"))
        _write(self.box.magic / "people" / "user2" / "collection.csv",
               "name,set,collector_number,finish,quantity,condition,language,notes\n")
        self.addCleanup(inventory.use(FileInventory(self.box.root)))
        self.addCleanup(state.use(MemoryStore(mode="everyone")))
        runner = forge_runs._forge_runner()
        runner.max_running = 1
        self.box.stack.enter_context(mock.patch.object(forge_runs, "FORGE_JOBS", runner))

    def test_members_visible_queued_run_reports_hidden_work_without_predecessor_details(self):
        self.playing()
        hidden = self.play(a=ELVES, b=ELVES, av="target", bv="target", games=800)["key"]
        self.assertTrue(self.forge.started.wait(WAIT))
        hidden_queued = self.play(a=PRECON, b=PRECON, av="target", bv="target", games=400)["key"]
        with _as("user2"):
            own = self.play(a=R_DECK_ID, b=R_DECK_ID, av="target", bv="target", profile="user2", games=200)
            answer = api.matchup(key=own["key"])
            running = api.matchups(running=True)["running"]
            self.assertApiError(404, lambda: api.matchup(key=hidden))
        self.assertEqual(answer["status"], "queued")
        self.assertEqual(answer["job"]["ahead"], 2)
        self.assertEqual(answer["job"]["ahead_work"], {"games": 1000, "unknown": 0, "approximate": False})
        self.assertEqual([item["key"] for item in running], [own["key"]])
        self.assertEqual(running[0]["ahead_work"], answer["job"]["ahead_work"])
        shown = json.dumps((answer, running))
        for private in (hidden, hidden_queued, ELVES, PRECON, "Elf Commander", "Matt"):
            self.assertNotIn(private, shown)
        self.finish()


class SerializationTests(unittest.TestCase):
    def test_all_forge_job_serializers_carry_only_the_queued_numeric_summary(self):
        work = {"games": 1234, "unknown": 2, "approximate": True}
        snap = {"status": "queued", "ahead": 3, "ahead_work": work, "progress": {"done": 0, "total": None},
                "detail": {}, "seconds": None}
        run = types.SimpleNamespace(by="User2", games=200, sides=[{"card_sha": "a"}, {"card_sha": "b"}],
                                    sample={"id": "sample"}, budget="quick", started=None)
        job = types.SimpleNamespace(key="matchup:key", fn=run)
        seen = types.SimpleNamespace(can_stop=lambda _: False)
        serializers = [lambda: forge_runs._job_json(job, snap, False),
                       lambda: forge_runs._pair_json(job, snap, "pair"),
                       lambda: field_page._job_json(job, snap),
                       lambda: field_group._progress(job, snap, seen),
                       lambda: gauntlet_page._progress(job, snap, seen),
                       lambda: variant_page._job_json(run, snap, None)]
        with mock.patch.object(forge_runs.FORGE_JOBS, "snapshot", return_value=snap), \
                mock.patch.object(forge_runs.COORD_JOBS, "snapshot", return_value=snap):
            serializers.append(lambda: forge_runs._running_json(job))
            coord = types.SimpleNamespace(key="field:key", fn=run)
            serializers.append(lambda: forge_runs._running_json(coord))
            for status in ("queued", "running", "done"):
                snap["status"] = status
                for serialize in serializers:
                    with self.subTest(status=status, serializer=serialize):
                        value = serialize()
                        if value is None:
                            self.assertEqual(status, "done")
                        elif status == "queued":
                            self.assertEqual(value["ahead_work"], work)
                        else:
                            self.assertNotIn("ahead_work", value)

    def test_variant_queued_bound_refines_saved_session_work_and_fails_conservatively(self):
        v = types.SimpleNamespace(_keys_today=lambda *args: True, variant_entry=lambda *args: {},
                                  _planned=lambda *args: 75)
        run = types.SimpleNamespace(forge=types.SimpleNamespace(variants=v), base={}, cards={}, test="test")
        with mock.patch.object(variant_page, "_results_of", return_value="fixture"):
            self.assertEqual(run_recovery._variant_work(run, [{}, {}], {}, [200, 1600], False),
                             {"games": 75, "approximate": True})
            self.assertEqual(run_recovery._variant_work(run, [{}, {}], {}, [200, 1600], True),
                             {"games": 0, "approximate": True})
            v._keys_today = lambda *args: False
            self.assertEqual(run_recovery._variant_work(run, [{}, {}], {}, [200, 1600], False),
                             {"games": 6400, "approximate": True})
            self.assertEqual(run_recovery._variant_work(run, [{}, {}], None, [200, 1600], True),
                             {"games": 6400, "approximate": True})
            self.assertEqual(run_recovery._variant_work(run, [{}, {}], {}, [200, 1600], True),
                             {"games": 6400, "approximate": True})
