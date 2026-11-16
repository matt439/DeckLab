"""Page pod permissions, review binding and cancellation without a Forge process."""
import contextlib
import copy
import hashlib
import json
import threading
from unittest import mock

from decklab.lib import access, api, jobs
from decklab.lib.api import forge_pods, forge_runs, guard, run_recovery
from decklab.lib.forge import pods as real_pods
from decklab.tests.test_api import _write
from decklab.tests.test_api_permissions import PermissionTestCase

IDS = ["commander/pod-" + letter for letter in "abcd"]
OTHER = "user2/commander/pod-member"
DECK = """# {title}

- **Format:** Commander
- **Status:** idea
- **Target bracket:** {bracket}

## Decklist

```
Commander
1 Llanowar Elves
Deck
{count} Forest
```
"""


def body(profile=None, **data):
    return json.dumps({**({"profile": profile} if profile is not None else {}), **data}).encode()


def seats(ids=IDS):
    return [{"id": deck_id, "version": "target"} for deck_id in ids]


class FakePods:
    def __init__(self):
        self.saved, self.runs = {}, []
        self.gate, self.started = threading.Event(), threading.Event()
        self.gate.set()

    def engine_identity(self):
        return {"fixture": True}

    def plan(self, entries, games=16, eng=None):
        key = hashlib.sha256(json.dumps([(entry["id"], entry["card_sha"]) for entry in entries]).encode()).hexdigest()
        return {"key": key, "kind": "pods", "sides": copy.deepcopy(entries), "games": games,
                "planned": games, "completed": 0, "remaining": games, "statistical_only": True,
                "note": "Statistics only; an even pod is 25% per deck."}

    def load(self, key):
        return copy.deepcopy(self.saved.get(key))

    def results(self):
        return [copy.deepcopy(value) for value in self.saved.values()]

    def run(self, entries, games, *, by, progress, expected_key, eng=None):
        self.runs.append(([entry["id"] for entry in entries], games, by))
        detail = {"deck": entries[0], "sides": entries}
        progress(4, games, detail)
        self.started.set()
        try:
            while not self.gate.wait(0.005):
                progress(4, games, detail)
        except jobs.Stopped:
            self._save(entries, games, 4, by, expected_key)
            raise
        return self._save(entries, games, games, by, expected_key)

    def _save(self, entries, games, completed, by, key):
        result = self.plan(entries, games)
        result.update(completed=completed, remaining=games-completed, by=by,
                      summary={"pods": completed, "counted": completed, "draws": 0,
                               "clock_stops": 0, "failed_batches": 0,
                               "by_deck": {entry["id"]: {"wins": completed // 4, "pods": completed,
                                                         "rate": 0.25, "range": [0.1, 0.5]} for entry in entries}})
        self.saved[key] = result
        return result


class PodApiTests(PermissionTestCase):
    def setUp(self):
        super().setUp()
        for index, deck_id in enumerate(IDS):
            _write(self.box.magic / "decks" / "commander" / (deck_id.rsplit("/", 1)[1] + ".md"),
                   DECK.format(title=f"Pod {index + 1}", count=20+index, bracket=2))
        _write(self.box.magic / "people" / "user2" / "decks" / "commander" / "pod-member.md",
               DECK.format(title="Member pod deck", count=25, bracket=2))
        self.pods = FakePods()
        self.box.forge.pods = self.pods
        self.addCleanup(lambda: delattr(self.box.forge, "pods"))
        self.runner = jobs.Runner(max_running=2, max_queued=4, log=lambda text: None,
                                  describe=forge_runs._matchup_error, name="coordinator")
        patcher = mock.patch.object(forge_runs, "COORD_JOBS", self.runner)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Recovery's persisted-snapshot and journal rules have their own tests.
        # This suite exercises the same asynchronous runner without a database.
        submit = mock.patch.object(run_recovery, "submit", side_effect=lambda forge, kind, run, profile, request, key,
                                  rerun=True: self.runner.submit(key, run, rerun=rerun))
        submit.start()
        self.addCleanup(submit.stop)
        self.addCleanup(self.finish)

    def finish(self):
        self.pods.gate.set()
        self.runner.stop()
        self.assertTrue(self.runner.join(5))

    @contextlib.contextmanager
    def as_(self, who):
        with access.using({"profile": who, "email": "", "remote": True}):
            yield

    def call(self, who, function, *args):
        with self.as_(who):
            return function(*args)

    def error(self, who, function, *args):
        with self.as_(who), self.assertRaises(api.ApiError) as caught:
            function(*args)
        return caught.exception

    def plan(self, who="matt", selected=None):
        return self.call(who, forge_pods.plan_pods, body(decks=selected or seats(), games=16))

    def start(self, who="matt", selected=None, key=None):
        chosen = selected or seats()
        key = key or self.plan(who, chosen)["key"]
        return self.call(who, forge_pods.run_pods, body(who, decks=chosen, games=16, expected_key=key))

    def test_choices_are_only_visible_commander_decks_and_no_private_kit(self):
        answer = self.call("matt", forge_pods.pods_view)
        choices = answer["choices"]
        self.assertTrue(set(IDS).issubset({choice["id"] for choice in choices}))
        self.assertNotIn(OTHER, {choice["id"] for choice in choices})
        self.assertNotIn("casual/gruul-test", {choice["id"] for choice in choices})
        self.assertEqual(set(choices[0]), {"id", "version", "title", "target_bracket", "public"})
        self.assertTrue(answer["simulations"]["may_start"])
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"user2"})):
            public = self.call("matt", forge_pods.pods_view)
        self.assertTrue(next(choice for choice in public["choices"] if choice["id"] == OTHER)["public"])

    def test_review_has_no_recipe_and_does_not_start_a_job(self):
        answer = self.plan()
        self.assertEqual((answer["status"], answer["plan"]["games"]), ("none", 16))
        self.assertEqual([side["id"] for side in answer["sides"]], IDS)
        self.assertEqual(self.pods.runs, [])
        self.assertEqual(self.runner.active(), [])
        self.assertNotIn("dck", json.dumps(answer))
        json.dumps(answer, allow_nan=False)

    def test_real_core_plan_contract_has_four_win_ranges_without_starting_forge(self):
        self.box.forge.pods = real_pods
        with mock.patch.object(real_pods, "engine_identity", return_value={"fixture": True}), \
                mock.patch.object(real_pods, "_root", return_value=self.box.data / "pod-contract"):
            answer = self.plan()
        self.assertEqual((answer["plan"]["completed"], answer["plan"]["remaining"]), (0, 16))
        self.assertTrue(answer["plan"]["statistical_only"])
        self.assertEqual(set(answer["plan"]["summary"]["by_deck"]), set(IDS))
        for row in answer["plan"]["summary"]["by_deck"].values():
            self.assertEqual((row["wins"], row["pods"], row["rate"]), (0, 0, None))
        self.assertNotIn("dck", json.dumps(answer))

    def test_hidden_seat_is_missing_before_simulations_refusal(self):
        selected = seats([*IDS[:3], OTHER])
        error = self.error("user1", forge_pods.run_pods, body("user1", decks=selected, expected_key="a"*64))
        self.assertEqual(error.status, 404)
        self.assertNotIn("Member pod deck", error.message)
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"user2"})):
            reviewed = self.plan(selected=selected)
        self.assertEqual(reviewed["sides"][-1]["id"], OTHER)

    def test_four_distinct_commander_seats_and_similar_known_brackets(self):
        _write(self.box.magic / "decks" / "commander" / "pod-unknown.md",
               DECK.format(title="Unknown bracket", count=29, bracket=""))
        for selected, message in ((seats(IDS[:3]), "exactly four"), (seats([IDS[0]]*4), "different"),
                                  (seats([*IDS[:3], "casual/gruul-test"]), "Commander"),
                                  (seats([*IDS[:3], "commander/pod-unknown"]), "target bracket")):
            error = self.error("matt", forge_pods.plan_pods, body(decks=selected))
            self.assertEqual(error.status, 400)
            self.assertIn(message, error.message)
        path = self.box.magic / "decks" / "commander" / "pod-d.md"
        _write(path, DECK.format(title="Pod 4", count=23, bracket=4))
        error = self.error("matt", forge_pods.plan_pods, body(decks=seats()))
        self.assertEqual((error.status, error.message), (400, forge_pods.BRACKETS_APART))
        _write(path, DECK.format(title="Pod 4", count=23, bracket=3))
        self.assertEqual(self.plan()["plan"]["games"], 16)

    def test_review_binding_and_game_bounds(self):
        error = self.error("matt", forge_pods.run_pods, body("matt", decks=seats(), games=16, expected_key="f"*64))
        self.assertEqual((error.status, error.message), (409, forge_pods.CHANGED))
        for games in (True, 1, 17, 256):
            self.assertEqual(self.error("matt", forge_pods.plan_pods, body(decks=seats(), games=games)).status, 400)
        self.assertEqual(self.pods.runs, [])

    def test_denied_start_explains_why_without_admin_names(self):
        answer = self.plan("user1")
        self.assertFalse(answer["simulations"]["may_start"])
        self.assertIn("admin", answer["simulations"]["why_not"])
        self.assertNotIn("Matt", json.dumps(answer["simulations"]))
        error = self.error("user1", forge_pods.run_pods,
                           body("user1", decks=seats(), games=16, expected_key=answer["key"]))
        self.assertEqual(error.status, 403)

    def test_start_join_progress_stop_and_partial_result(self):
        self.pods.gate.clear()
        reviewed = self.plan()
        answer = self.start(key=reviewed["key"])
        self.assertTrue(self.pods.started.wait(5))
        self.assertIn(answer["status"], ("queued", "running"))
        again = self.start(key=reviewed["key"])
        self.assertEqual(len(self.pods.runs), 1)
        self.assertEqual(again["job"]["total"], 16)
        self.assertTrue(again["job"]["may_stop"])
        job = self.runner.active()[0]
        self.assertEqual([side["id"] for side in job.fn.sides], IDS)
        self.assertEqual(job.fn.by_id, "matt")
        stopped = self.call("user1", forge_pods.stop_pods, body("user1", key=reviewed["key"]))
        self.assertEqual(stopped["result"]["summary"]["pods"], 4)
        self.assertIn("stopped", stopped["notice"])
        self.assertNotIn("dck", json.dumps(stopped))

    def test_privacy_change_hides_saved_and_running_runs_and_masks_names(self):
        selected = seats([*IDS[:3], OTHER])
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"user2"})):
            reviewed = self.plan(selected=selected)
            self.start(selected=selected, key=reviewed["key"])
            job = self.runner.get("pods:" + reviewed["key"])
            self.assertTrue(job.wait(5))
            shown = self.call("matt", forge_pods.pods_view, reviewed["key"])
            self.assertEqual(shown["status"], "done")
        self.assertEqual(self.error("matt", forge_pods.pods_view, reviewed["key"]).status, 404)
        self.assertEqual(self.call("matt", forge_pods.pods_view)["results"], [])
        self.assertEqual(self.error("matt", forge_pods.pods_view, "e"*64).message, forge_pods.MISSING)
        # A public deck's starter is never a private member's display name.
        stored = self.pods.saved[reviewed["key"]]
        stored["by"] = "User2"
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"user2"})):
            shown = self.call("matt", forge_pods.pods_view, reviewed["key"])
        self.assertEqual(shown["result"]["by"], "someone")

    def test_privacy_change_hides_an_active_run_before_its_first_saved_result(self):
        self.pods.gate.clear()
        selected = seats([*IDS[:3], OTHER])
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"user2"})):
            reviewed = self.plan(selected=selected)
            self.start(selected=selected, key=reviewed["key"])
            self.assertTrue(self.pods.started.wait(5))
        self.assertEqual(self.error("matt", forge_pods.pods_view, reviewed["key"]).status, 404)
        self.assertEqual(self.call("matt", forge_pods.pods_view)["running"], [])
        stopped = self.call("matt", forge_pods.stop_pods, body("matt", key=reviewed["key"]))
        self.assertEqual(stopped, {"key": reviewed["key"], "stopped": True, "hidden": True})

    def test_corrupt_saved_addresses_answer_exactly_as_missing_ones(self):
        missing = self.error("matt", forge_pods.pods_view, "a"*64)
        with mock.patch.object(self.pods, "load", side_effect=ValueError("private file contents")):
            corrupt = self.error("matt", forge_pods.pods_view, "b"*64)
            stopped = self.error("matt", forge_pods.stop_pods, body("matt", key="b"*64))
        self.assertEqual((corrupt.status, corrupt.message), (missing.status, missing.message))
        self.assertEqual((stopped.status, stopped.message), (missing.status, missing.message))

    def test_stopped_and_failed_partial_guidance_survives_job_expiry(self):
        reviewed = self.plan()
        self.start(key=reviewed["key"])
        self.assertTrue(self.runner.get("pods:" + reviewed["key"]).wait(5))
        stored = self.pods.saved[reviewed["key"]]
        self.runner._jobs.clear()
        stored.update(state="stopped", remaining=12, completed=4)
        stopped = self.call("matt", forge_pods.pods_view, reviewed["key"])
        self.assertEqual(stopped["result"]["state"], "stopped")
        self.assertIn("stopped", stopped["notice"])
        stored["state"] = "error"
        failed = self.call("matt", forge_pods.pods_view, reviewed["key"])
        self.assertEqual((failed["status"], failed["error"]), ("error", forge_pods.FAILED))
        self.assertIsNotNone(failed["result"])
