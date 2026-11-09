"""Private saved-list crosschecks over disposable inventory and a controllable fake engine.

These are API and job-lifecycle checks. No simulator, private configuration or database is used.
"""
import contextlib
from copy import deepcopy
import hashlib
import json
import threading
import unittest
from unittest import mock

from decklab.lib import access, api, decks, feature_routes, jobs
from decklab.lib.api import crosscheck_page as page, guard, simulations
from decklab.lib.api.library import _deck_sections
from decklab.lib import server_run
from decklab.tests.test_api import _write
from decklab.tests.test_api_permissions import PermissionTestCase
from decklab.tests.test_server import ServerTestCase, WRITE

BASE, OTHER, MEMBER = "casual/gruul-test", "casual/mono-test", "user2/casual/r-elves"
WAIT = 5


def body(**data):
    return json.dumps({"profile": "matt", **data}).encode()


class FakeCrosscheck:
    def __init__(self, forge):
        self.forge = forge
        self.ready, self.status_reads, self.runs = True, 0, []
        self.saved = {}
        self.started, self.gate = threading.Event(), threading.Event()
        self.gate.set()

    def status(self):
        self.status_reads += 1
        return {"engines": {name: {"ready": self.ready, "version": "test-1", "identity": name,
                 "problem": "C:\\private\\user\\bridge failed"} for name in page.ENGINES}}

    def deck_entry(self, deck_id, version="target"):
        summary, sections = _deck_sections(deck_id, version)
        return self.forge.entry(deck_id, version, summary["title"], decks.engine_kind(summary), sections)

    def plan(self, base, opponent, **options):
        if base["kind"] != opponent["kind"]:
            raise ValueError("Choose decks of the same format.")
        frozen = {"schema": 1, "decks": {"baseline": deepcopy(base), "opponent": deepcopy(opponent)}, **options}
        frozen["id"] = hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()
        return frozen

    def assert_current(self, planned, base, opponent):
        if planned["decks"]["baseline"]["card_sha"] != base["card_sha"]:
            raise ValueError("Changed list")

    def add_result(self, planned, status="completed"):
        result_id = hashlib.sha256(f"receipt-{len(self.saved)}".encode()).hexdigest()
        counts = {"asked": 10, "completed": 8, "wins": 5, "losses": 2, "draws": 1,
                  "failed": 1, "timeouts": 1, "cancelled": 0, "win_rate": 62.5}
        summary = {"id": result_id, "plan_id": planned["id"], "format": "casual", "mode": "one-on-one",
            "games_per_arm": 10, "has_variant": False, "status": status,
            "decks": deepcopy(planned["decks"]), "agreement": {"status": "separate", "text": "Scores stay separate."},
            "engines": {name: {"status": "partial", "version": "test-1", "identity": name,
                "baseline": deepcopy(counts), "variant": None, "problem": "C:\\private\\user\\traceback"}
                for name in page.ENGINES}}
        self.saved[result_id] = {"id": result_id, "plan": deepcopy(planned), "view": summary}
        return self.saved[result_id]

    def run(self, planned, *, by, progress):
        self.runs.append(planned)
        self.started.set()
        try:
            while not self.gate.wait(0.005):
                progress(1, 20, {"raw": "private runtime detail"})
            progress(20, 20)
        except jobs.Stopped as error:
            error.receipt_id = self.add_result(planned, "cancelled")["id"]
            raise
        return self.add_result(planned)

    def load(self, receipt_id):
        return deepcopy(self.saved.get(receipt_id))

    def view(self, receipt):
        return deepcopy(receipt["view"])

    def results_for(self, deck_id, limit=20):
        return [self.view(row) for row in reversed(list(self.saved.values()))
                if row["plan"]["decks"]["baseline"]["id"] == deck_id][:limit]


class CrosscheckApiTests(PermissionTestCase):
    def setUp(self):
        super().setUp()
        _write(self.box.magic / "decks" / "casual" / "mono-test.md", """# Mono Test

- **Format:** Casual 60-card, 1v1
- **Played by:** either
- **Status:** idea

## Decklist

```
Deck
4 Llanowar Elves
20 Forest
```
""")
        self.core = FakeCrosscheck(self.box.forge)
        self.patch = mock.patch.object(page, "_core", return_value=self.core)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.runner = jobs.Runner(max_running=1, max_queued=2, describe=page._describe, log=lambda text: None)
        patcher = mock.patch.object(page, "CROSSCHECK_JOBS", self.runner)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.finish)

    def finish(self):
        self.core.gate.set()
        self.runner.stop()
        self.assertTrue(self.runner.join(WAIT))

    @contextlib.contextmanager
    def as_(self, who="matt"):
        with access.using({"profile": who, "email": "", "remote": True}):
            yield

    def request_body(self, **changes):
        with self.as_():
            base, other = self.core.deck_entry(BASE), self.core.deck_entry(OTHER)
        return body(id=BASE, opponent=OTHER, expected_card_sha=base["card_sha"],
                    expected_opponent_card_sha=other["card_sha"], **changes)

    def error(self, who, fn, *args, **kwargs):
        with self.as_(who), self.assertRaises(api.ApiError) as caught:
            fn(*args, **kwargs)
        return caught.exception

    def saved(self, base=BASE, opponent=OTHER):
        with self.as_():
            a, b = self.core.deck_entry(base), self.core.deck_entry(opponent)
            return self.core.add_result(self.core.plan(a, b, games=10, seed=1, timeout_seconds=120,
                                                       engines=page.ENGINES))

    def test_a_read_offers_visible_same_format_choices_without_running(self):
        with self.as_():
            answer = page.check_view(BASE)
        offered = [row["id"] for row in answer["choices"]]
        self.assertIn(OTHER, offered)
        self.assertNotIn(BASE, offered)
        self.assertNotIn(MEMBER, offered)
        self.assertFalse(any(name.startswith("commander/") for name in offered))
        self.assertEqual(answer["status"], "none")
        self.assertEqual(self.core.runs, [])
        self.assertNotIn("private", json.dumps(answer))

    def test_hidden_decks_are_missing_before_readiness_and_simulation_permissions(self):
        self.core.ready = False
        for fn, args in ((page.check_view, (BASE, "target", MEMBER)),
                         (page.run_check, (body(profile="user1", id=BASE, opponent=MEMBER),))):
            error = self.error("user1", fn, *args)
            self.assertEqual(error.status, 404)
            self.assertNotIn("User2", error.message)
        self.assertEqual(self.core.status_reads, 0)
        self.assertEqual(self.error("user2", page.check_view, BASE).status, 404)

    def test_run_requires_the_simulations_setting_even_when_both_engines_are_ready(self):
        with mock.patch.object(simulations, "mode", return_value="paused"):
            error = self.error("matt", page.run_check, self.request_body())
        self.assertEqual(error.status, 403)
        self.assertFalse(self.runner.active())

    def test_both_fingerprints_are_required_and_checked(self):
        valid = json.loads(self.request_body())
        for field in ("expected_card_sha", "expected_opponent_card_sha"):
            with self.subTest(field=field):
                absent = dict(valid)
                absent.pop(field)
                self.assertEqual(self.error("matt", page.run_check, json.dumps(absent).encode()).status, 400)
                changed = dict(valid, **{field: "0" * 64})
                self.assertEqual(self.error("matt", page.run_check, json.dumps(changed).encode()).status, 409)
        self.assertEqual(self.core.runs, [])

    def test_invalid_game_budget_and_unknown_fields_never_start(self):
        for value in (True, 0, 11, 50000, "10"):
            self.assertEqual(self.error("matt", page.run_check, self.request_body(games=value)).status, 400)
        self.assertEqual(self.error("matt", page.run_check, self.request_body(command="private-executable")).status, 400)
        self.assertFalse(self.runner.active())

    def test_unavailable_bridge_is_reported_without_paths_or_process_start(self):
        self.core.ready = False
        with self.as_():
            answer = page.check_view(BASE, opponent=OTHER)
        self.assertFalse(answer["ready"])
        self.assertIn("bridge", answer["engines"]["xmage"]["problem"])
        self.assertNotIn("private", json.dumps(answer))
        self.assertEqual(self.error("matt", page.run_check, self.request_body()).status, 503)
        self.assertEqual(self.core.runs, [])

    def test_double_start_joins_one_active_check_and_records_immutable_receipt(self):
        self.core.gate.clear()
        with self.as_():
            first = page.run_check(self.request_body())
            self.assertTrue(self.core.started.wait(WAIT))
            again = page.run_check(self.request_body())
            self.assertEqual(first["test"], again["test"])
            self.assertEqual(len(self.core.runs), 1)
            self.core.gate.set()
            self.assertTrue(self.runner.join(WAIT))
            shown = page.check_view(BASE, opponent=OTHER, test=first["test"])
        self.assertEqual(shown["status"], "done")
        self.assertNotEqual(shown["test"], first["test"])
        self.assertEqual(shown["result"]["engines"]["forge"]["baseline"]["completed"], 8)
        self.assertNotIn("private", json.dumps(shown))
        self.assertNotIn('"raw":', json.dumps(shown))

    def test_changed_opponent_marks_history_old_even_without_a_selection(self):
        saved = self.saved()
        original = self.core.deck_entry

        def changed(deck_id, version="target"):
            entry = original(deck_id, version)
            if deck_id == OTHER:
                entry["card_sha"] = "e" * 64
            return entry

        self.core.deck_entry = changed
        with self.as_():
            shown = page.check_view(BASE, test=saved["id"])
        self.assertFalse(shown["result"]["current"])

    def test_safe_coverage_and_uncertainty_survive_the_public_projection(self):
        saved = self.saved()
        engine = saved["view"]["engines"]["xmage"]
        engine.update(reason_code="unsupported_cards", missing_cards=["New Card", "Card // Back"])
        engine["baseline"]["win_rate_interval"] = {"low": 30.0, "high": 90.0, "confidence": 0.95}
        engine["baseline"]["unplayed"] = 2
        with self.as_():
            shown = page.check_view(BASE, test=saved["id"])
        projected = shown["result"]["engines"]["xmage"]
        self.assertEqual(projected["missing_cards"], ["New Card", "Card // Back"])
        self.assertEqual(projected["reason_code"], "unsupported_cards")
        self.assertEqual(projected["baseline"]["unplayed"], 2)
        self.assertEqual(projected["baseline"]["win_rate_interval"], {"low": 30.0, "high": 90.0, "confidence": 0.95})
        self.assertNotIn("private", json.dumps(shown))

    def test_corrupt_optional_numbers_never_become_rates_or_intervals(self):
        saved = self.saved()
        counts = saved["view"]["engines"]["xmage"]["baseline"]
        counts.update(win_rate=float("nan"), completed=True,
                      win_rate_interval={"low": 0, "high": float("inf"), "confidence": 0.95})
        with self.as_():
            shown = page.check_view(BASE, test=saved["id"])
        projected = shown["result"]["engines"]["xmage"]["baseline"]
        self.assertIsNone(projected["win_rate"])
        self.assertIsNone(projected["win_rate_interval"])
        self.assertEqual(projected["completed"], 0)

    def test_a_receipt_for_a_hidden_opponent_is_not_returned_after_visibility_changes(self):
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"user2"})):
            saved = self.saved(opponent=MEMBER)
            with self.as_():
                self.assertIsNotNone(page.check_view(BASE, test=saved["id"])["result"])
        self.assertEqual(self.error("matt", page.check_view, BASE, test=saved["id"]).status, 404)
        with self.as_():
            self.assertIsNone(page.check_view(BASE)["result"])

    def test_home_member_can_stop_home_check_and_partial_receipt_survives(self):
        self.core.gate.clear()
        with self.as_():
            started = page.run_check(self.request_body())
        self.assertTrue(self.core.started.wait(WAIT))
        with self.as_("user1"):
            stopped = page.stop_check(body(profile="user1", test=started["test"]))
            self.assertIn(stopped["status"], ("running", "error"))
        self.assertTrue(self.runner.join(WAIT))
        with self.as_():
            shown = page.check_view(BASE, opponent=OTHER, test=started["test"])
        self.assertEqual(shown["job"]["error"], "stopped")
        self.assertEqual(shown["result"]["status"], "cancelled")

    def test_hidden_job_cannot_be_stopped_by_an_unrelated_member(self):
        self.core.gate.clear()
        with self.as_():
            started = page.run_check(self.request_body())
        self.assertTrue(self.core.started.wait(WAIT))
        error = self.error("user2", page.stop_check, body(profile="user2", test=started["test"]))
        self.assertEqual(error.status, 404)
        self.assertNotIn(BASE, error.message)
        self.assertFalse(self.runner.get(started["test"])._cancelled.is_set())

    def test_admin_stop_of_a_hidden_check_is_anonymous(self):
        self.core.gate.clear()
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"user2"})), self.as_():
            planned = self.core.plan(self.core.deck_entry(MEMBER), self.core.deck_entry(OTHER),
                                     games=10, seed=1, timeout_seconds=120, engines=page.ENGINES)
        run = page._CheckRun(planned, {"id": "user2", "name": "User2", "space": "user2", "role": "member"})
        self.runner.submit(planned["id"], run)
        self.assertTrue(self.core.started.wait(WAIT))
        with self.as_():
            answer = page.stop_check(body(test=planned["id"]))
        self.assertEqual(answer, {"test": planned["id"], "stopped": True, "hidden": True})
        self.assertNotIn(MEMBER, json.dumps(answer))
        self.assertNotIn("User2", json.dumps(answer))


class CrosscheckRouteTests(ServerTestCase):
    def test_read_route_arguments_and_202_status(self):
        answer = {"status": "running"}
        with mock.patch.object(page, "check_view", return_value=answer) as handler:
            found = self.get_json("/api/crosscheck?id=casual%2Ftest&version=owned&opponent=casual%2Fother&opponent_version=target", status=202)
        self.assertEqual(found, answer)
        handler.assert_called_once_with(deck_id="casual/test", version="owned", opponent="casual/other", opponent_version="target")
        self.assertEqual(feature_routes._status(("crosscheck",), answer), 202)

    def test_write_routes_use_existing_same_origin_and_json_guards(self):
        for action, name in (("run", "run_check"), ("stop", "stop_check")):
            route = f"/api/crosscheck/{action}"
            with mock.patch.object(page, name, return_value={"status": "none"}) as handler:
                self.assertError(route, 403, method="POST", body=b"{}", headers={"Content-Type": "application/json"})
                handler.assert_not_called()
                self.get_json(route, method="POST", body=b'{"profile":"matt"}',
                              headers=dict(WRITE, Origin=f"http://127.0.0.1:{self.port}"))
                handler.assert_called_once_with(b'{"profile":"matt"}')


class CrosscheckLifecycleTests(unittest.TestCase):
    def test_server_shutdown_stops_all_runners_including_the_crosscheck(self):
        practice, forge, coord, check = (mock.Mock() for _ in range(4))
        with mock.patch.object(api.practice, "JOBS", practice), mock.patch.object(api.forge_runs, "FORGE_JOBS", forge), \
                mock.patch.object(api.forge_runs, "COORD_JOBS", coord), mock.patch.object(page, "CROSSCHECK_JOBS", check):
            api.forge_runs.stop_jobs()
        for runner in (practice, forge, coord, check):
            runner.stop.assert_called_once_with()

    def test_join_waits_for_crosscheck_even_when_another_runner_is_not_finished(self):
        forge, coord, check = (mock.Mock() for _ in range(3))
        forge.join.return_value = False
        coord.join.return_value = check.join.return_value = True
        with mock.patch.object(api.forge_runs, "FORGE_JOBS", forge), mock.patch.object(api.forge_runs, "COORD_JOBS", coord), \
                mock.patch.object(page, "CROSSCHECK_JOBS", check):
            self.assertFalse(server_run._join_runs(3))
        self.assertEqual(forge.join.call_count, 1)
        self.assertEqual(coord.join.call_count, 1)
        self.assertEqual(check.join.call_count, 1)
        self.assertGreaterEqual(check.join.call_args.args[0], 0)

    def test_queued_or_running_checks_keep_the_server_awake(self):
        with mock.patch.object(api.forge_runs.FORGE_JOBS, "active", return_value=[]), \
                mock.patch.object(api.forge_runs.COORD_JOBS, "active", return_value=[]), \
                mock.patch.object(page.CROSSCHECK_JOBS, "active", return_value=[object()]):
            self.assertEqual(server_run._forge_runs_busy(), "a simulator check is going")
