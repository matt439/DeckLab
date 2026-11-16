"""Four-seat recovery receipts over synthetic pod checkpoints; no Forge processes."""
import contextlib
import copy
import types
from unittest import mock

from decklab.lib import access, api, decks, jobs
from decklab.lib.api import forge_pods, forge_runs, run_recovery as recovery
from decklab.lib.forge import run_journal
from decklab.tests.test_api import ApiTestCase, _write
from decklab.tests.test_field_api import ELVES
from decklab.tests.test_forge_pods_api import DECK, IDS, FakePods, body, seats


class PodRecoveryTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.forge = self.box.forge
        self.profile = {"id": "matt", "name": "Matt", "space": "home", "role": "admin"}
        sections = decks.load_deck(ELVES, "target")
        self.sides = [self.forge.entry(deck_id, "target", f"Pod fixture {index}", "commander", sections)
                      for index, deck_id in enumerate([ELVES, "commander/pod-two", "commander/pod-three", "commander/pod-four"])]
        self.key = "a" * 64
        self.pod_engine = {"jar_sha": "b" * 64}
        self.pods = types.SimpleNamespace(engine_identity=mock.Mock(return_value=self.pod_engine),
                                          plan=mock.Mock(return_value={"key": self.key, "remaining": 12}))
        self.run = types.SimpleNamespace(entry=self.sides[0], sides=self.sides, chosen=self.sides[1:],
                                         games=16, key=self.key, pods=self.pods)

    @contextlib.contextmanager
    def who(self, name="matt"):
        with access.using({"profile": name, "email": "", "remote": True}), \
                access.viewing(None), access.answering(False):
            yield

    def prepare(self):
        with self.who():
            return recovery._prepare(self.forge, "pods", self.run, self.profile, {"ignored": "not retained"})

    def interrupted(self):
        prepared = self.prepare()
        journal = run_journal.store()
        record = journal.create("matt", "pods", prepared["request"], prepared["manifest"])
        journal.transition("matt", record["id"], "interrupted")
        return journal.get("matt", record["id"]), prepared

    def test_canonical_request_keeps_the_accepted_four_seats_and_versions_in_order(self):
        self.sides[2]["version"] = "owned"
        incoming = {"profile": "user1", "decks": [{"id": "casual/changed"}], "games": 128,
                    "expected_key": "c" * 64, "note": "Do not retain arbitrary metadata"}
        expected = {"profile": "matt", "decks": [{"id": side["id"], "version": side["version"]}
                                                   for side in self.sides],
                    "games": 16, "expected_key": self.key}
        result = recovery._canonical("pods", incoming, self.run, self.profile)
        self.assertEqual(result, expected)
        self.sides.reverse()
        incoming["games"] = 64
        self.assertEqual(result, expected, "caller mutation cannot rewrite a captured recovery request")

    def test_checkpoint_remaining_changes_work_only_and_manifest_binds_all_four_lists(self):
        partial = self.prepare()
        self.pods.plan.assert_called_once_with(self.sides, 16, eng=self.pod_engine)
        self.assertEqual(partial["remaining"], 12)
        self.assertEqual(partial["planned_work"], {"games": 12, "approximate": False})
        self.assertEqual({ref["id"] for ref in partial["manifest"]["refs"]}, {side["id"] for side in self.sides})
        self.assertEqual((partial["manifest"]["pod_key"], partial["manifest"]["target"]), (self.key, 16))
        self.pods.plan.return_value["remaining"] = 0
        complete = self.prepare()
        self.assertEqual(complete["remaining"], 0)
        self.assertEqual(complete["manifest"]["signature"], partial["manifest"]["signature"])
        self.assertEqual(complete["planned_work"], {"games": 0, "approximate": False})

    def test_changed_pod_identity_refuses_before_submitting_any_work(self):
        self.pods.plan.return_value["key"] = "c" * 64
        with self.who(), mock.patch.object(api.forge_runs.COORD_JOBS, "submit", side_effect=AssertionError("No stale work")):
            with self.assertRaises(api.ApiError) as caught:
                recovery.submit(self.forge, "pods", self.run, self.profile, {}, "pods:" + self.key)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(run_journal.store().records("matt"), [])

    def test_changed_fourth_list_or_ai_profile_changes_recovery_signature(self):
        original = self.prepare()["manifest"]["signature"]
        self.sides[3]["card_sha"] = "d" * 64
        self.assertNotEqual(self.prepare()["manifest"]["signature"], original)
        self.sides[3]["card_sha"] = self.sides[0]["card_sha"]
        engine = self.forge.engine.today()
        changed = {**engine, "ai_sha": {"Default": "e" * 64}}
        with mock.patch.object(self.forge.engine, "today", return_value=changed):
            self.assertNotEqual(self.prepare()["manifest"]["signature"], original)

    def test_pod_journal_claim_preserves_exact_request_and_current_checkpoint(self):
        record, prepared = self.interrupted()
        self.pods.plan.return_value["remaining"] = 8
        current = self.prepare()
        claimed = run_journal.store().claim("matt", record["id"], current["manifest"])
        self.assertEqual(claimed["request"], prepared["request"])
        self.assertEqual(claimed["kind"], "pods")
        self.assertEqual(claimed["state"], "queued")
        self.assertFalse(run_journal.store().inactive(claimed))

    def test_partial_offer_links_to_pod_results_and_finished_checkpoint_is_retired_without_queueing(self):
        record, prepared = self.interrupted()
        with self.who(), mock.patch.object(recovery, "_preview", return_value=prepared), \
                mock.patch.object(api.forge_runs.COORD_JOBS, "submit", side_effect=AssertionError("Read never queues")):
            offer = recovery._offer(record, self.profile)
            self.assertTrue(offer["may_resume"])
            self.assertEqual(offer["kind"], "pods")
            self.assertIn("four-player pod run", offer["title"])
            self.assertEqual(offer["link"], "#/forge-pods?key=" + self.key)
            self.assertNotIn("request", offer)
            self.assertNotIn("decks", offer)
            finished = copy.deepcopy(prepared)
            finished["remaining"] = 0
            with mock.patch.object(recovery, "_preview", return_value=finished):
                self.assertIsNone(recovery._offer(record, self.profile))
        self.assertEqual(run_journal.store().records("matt"), [])

    def test_revoked_fourth_participant_hides_offer_before_preview_without_admin_override(self):
        record, _ = self.interrupted()
        refs = copy.deepcopy(record["manifest"]["refs"])
        refs[-1]["id"] = "user2/commander/private-pod-fixture"
        record["manifest"]["refs"] = refs
        with self.who(), mock.patch.object(recovery, "_preview", side_effect=AssertionError("No hidden preview")):
            self.assertIsNone(recovery._offer(record, self.profile))

    def test_unverified_pod_key_never_becomes_a_recovery_link(self):
        record, prepared = self.interrupted()
        for key in (None, "", "../unverified", "A" * 64, {"key": self.key}):
            with self.subTest(key=key), self.who(), mock.patch.object(recovery, "_preview", return_value=prepared):
                altered = copy.deepcopy(record)
                altered["manifest"]["pod_key"] = key
                self.assertIsNone(recovery._offer(altered, self.profile)["link"])

    def test_server_interruption_is_explicitly_resumed_through_the_real_pod_handler_and_journal(self):
        for index, deck_id in enumerate(IDS):
            _write(self.box.magic / "decks" / "commander" / (deck_id.rsplit("/", 1)[1] + ".md"),
                   DECK.format(title=f"Recovery pod {index + 1}", count=20 + index, bracket=2))
        pods = FakePods()
        self.forge.pods = pods
        self.addCleanup(lambda: delattr(self.forge, "pods"))
        original_plan = pods.plan

        def checkpoint_plan(entries, games=16, eng=None):
            plan = original_plan(entries, games, eng=eng)
            completed = pods.saved.get(plan["key"], {}).get("completed", 0)
            return {**plan, "completed": completed, "remaining": max(0, games - completed)}

        self.enterContext(mock.patch.object(pods, "plan", side_effect=checkpoint_plan))

        def runner():
            created = jobs.Runner(max_running=1, max_queued=4, log=lambda text: None,
                                  describe=forge_runs._matchup_error, name="synthetic pod recovery")
            self.enterContext(mock.patch.object(forge_runs, "COORD_JOBS", created))
            self.addCleanup(lambda: (pods.gate.set(), created.stop(), self.assertTrue(created.join(5))))
            return created

        initial = runner()
        pods.gate.clear()
        selected = seats([IDS[2], IDS[0], IDS[3], IDS[1]])
        with self.who():
            reviewed = forge_pods.plan_pods(body(decks=selected, games=16))
            forge_pods.run_pods(body("matt", decks=selected, games=16, expected_key=reviewed["key"]))
        self.assertTrue(pods.started.wait(5))
        job_key = "pods:" + reviewed["key"]
        initial.stop()
        self.assertTrue(initial.get(job_key).wait(5))
        record, = run_journal.store().records("matt")
        self.assertEqual(record["state"], "interrupted")
        self.assertEqual(record["request"], {"profile": "matt", "decks": selected,
                                             "games": 16, "expected_key": reviewed["key"]})
        self.assertEqual(pods.saved[reviewed["key"]]["completed"], 4)

        resumed = runner()
        with self.who():
            offer, = recovery.view()["unfinished"]
            self.assertTrue(offer["may_resume"])
            self.assertEqual(resumed.active(), [], "checking an offer starts no work")
            self.assertEqual(len(pods.runs), 1)
            pods.gate.set()
            result = recovery.resume(body("matt", id=record["id"]))
        self.assertEqual(result, {"resumed": True, "complete": False})
        self.assertTrue(resumed.get(job_key).wait(5))
        self.assertEqual(resumed.get(job_key)._planned_work, {"games": 12, "approximate": False})
        self.assertEqual(pods.saved[reviewed["key"]]["completed"], 16)
        self.assertEqual([run[0] for run in pods.runs], [[seat["id"] for seat in selected]] * 2)
        self.assertEqual(run_journal.store().records("matt"), [])
