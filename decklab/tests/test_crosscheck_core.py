"""Exact-list second opinions, separated rates and immutable partial evidence."""
import json
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

from decklab.lib import crosscheck, jobs
from decklab.lib.crosscheck import adapters, model, store
from decklab.lib.forge import lists


def entry(deck_id="casual/white", creature="Elite Vanguard", revision=1):
    cards = {"Commander": [], "Main": [[56, "Plains"], [4, creature]]}
    found = lists.entry_from_cards(deck_id, deck_id, "constructed", cards,
                                   {"deck": deck_id, "revision": revision})
    found["pilot"] = {"profile": "Default", "switches": []}
    return found


def readiness():
    return {"schema": 1, "engines": {name: {"ready": True, "version": "fixture-1", "identity": ("f" if name == "forge" else "a") * 64,
                                             "problem": None} for name in model.ENGINES}}


def details(name):
    return readiness()["engines"][name]


def response(request, name="xmage", state="completed", winner="subject"):
    role = request["decks"][0]["id"]
    identity_key = "identity_sha256" if name == "xmage" else "engine_sha256"
    return {"schema": 1, "engine": name, "version": "fixture-1", identity_key: ("f" if name == "forge" else "a") * 64,
            "request_sha256": model.digest(request), "format": request["format"], "seed": request["seed"],
            "reproducible": name == "forge", "status": state,
            "coverage": [{"deck_id": d["id"], "status": "supported", "missing": []} for d in request["decks"]],
            "games": [{"arm": role, "number": request["game_number"], "seed": request["seed"],
                       "starting_player": request.get("starting_player", request.get("seat_assignment")), "status": state,
                       "winner": winner if state == "completed" else None, "turns": 8}]}


def fake_play(name, request, identity, folder, tick):
    tick()
    data = response(request, name)
    game, coverage = adapters.validate_response(data, name, request, identity)
    return {"game": game, "coverage": coverage, "response_sha256": model.digest(data),
            "version": "fixture-1", "provenance": {"fixture": True}}


class CrosscheckCoreTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = entry(), entry("casual/lions", "Savannah Lions")
        self.ready = mock.patch.object(crosscheck, "status", side_effect=readiness)
        self.ready.start()
        self.addCleanup(self.ready.stop)

    def plan(self, **kwargs):
        return crosscheck.plan(self.a, self.b, games=kwargs.pop("games", 2), **kwargs)

    def run_plan(self, captured, folder, play=fake_play, **kwargs):
        with mock.patch.object(adapters, "details", side_effect=details), mock.patch.object(adapters, "play", side_effect=play):
            return crosscheck.run(captured, results_dir=folder, **kwargs)

    def test_plan_is_content_addressed_exact_and_does_not_mutate_entries(self):
        before = deepcopy(self.a)
        captured = self.plan()
        self.assertEqual(captured, self.plan())
        self.assertEqual(captured["mode"], "one-on-one")
        self.assertEqual(captured["decks"]["baseline"]["cards"], model.listed(self.a["cards"]))
        self.assertEqual(self.a, before)
        altered = deepcopy(captured)
        altered["decks"]["baseline"]["cards"]["Main"][0][0] += 1
        with self.assertRaises(crosscheck.CrosscheckError):
            model.validate_plan(altered)

    def test_swaps_keep_commander_opponent_pilot_and_card_count_unchanged(self):
        captured = self.plan(remove=["1 Elite Vanguard"], add=["1 Grizzly Bears"])
        self.assertEqual(captured["decks"]["variant"]["card_count"], 60)
        self.assertEqual(captured["decks"]["variant"]["pilot"], captured["decks"]["baseline"]["pilot"])
        self.assertEqual(captured["decks"]["opponent"]["cards"], model.listed(self.b["cards"]))
        self.assertIn([1, "Grizzly Bears"], captured["decks"]["variant"]["cards"]["Main"])
        self.assertIn([3, "Elite Vanguard"], captured["decks"]["variant"]["cards"]["Main"])

    def test_invalid_bounds_changes_and_untrusted_engine_types_fail_closed(self):
        invalid = [{"games": True}, {"games": 201}, {"seed": -1}, {"seed": 1 << 31},
                   {"timeout_seconds": float("nan")}, {"engines": [["forge"]]},
                   {"engines": ["forge", "forge"]}, {"engines": "forge"},
                   {"remove": ["1 Elite Vanguard"]}, {"remove": ["5 Elite Vanguard"], "add": ["5 Grizzly Bears"]},
                   {"remove": ["1 Elite Vanguard"], "add": ["1 Elite Vanguard"]}]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(crosscheck.CrosscheckError):
                self.plan(**kwargs)
        bad_schema = self.plan()
        bad_schema["schema"] = True
        bad_schema.pop("id")
        bad_schema["id"] = model.digest(bad_schema)
        with self.assertRaises(crosscheck.CrosscheckError):
            model.validate_plan(bad_schema)

    def test_current_revision_is_checked_even_when_cards_have_not_changed(self):
        captured = self.plan()
        self.assertEqual(crosscheck.assert_current(captured, self.a, self.b), captured)
        with self.assertRaises(crosscheck.CrosscheckError):
            crosscheck.assert_current(captured, entry(revision=2), self.b)

    def test_complete_runs_are_separate_immutable_receipts_without_forge_files(self):
        with tempfile.TemporaryDirectory() as folder:
            captured = self.plan()
            first = self.run_plan(captured, folder)
            second = self.run_plan(captured, folder)
            self.assertNotEqual(first["id"], second["id"])
            self.assertNotEqual(first["id"], captured["id"])
            self.assertEqual(crosscheck.load(first["id"], folder), first)
            self.assertEqual(first["status"], "completed")
            visible = crosscheck.view(first)
            self.assertEqual(visible["engines"]["forge"]["baseline"]["completed"], 2)
            self.assertEqual(visible["engines"]["xmage"]["baseline"]["win_rate"], 100)
            self.assertIsNone(visible["engines"]["forge"]["variant"])
            self.assertNotIn("win_rate", visible)
            self.assertNotIn("combined", visible)
            self.assertEqual(len(crosscheck.results_for(self.a["id"], results_dir=folder)), 2)
            self.assertEqual(list((Path(folder) / "work").iterdir()), [])
            self.assertEqual({p.parent.name for p in Path(folder).rglob("*.json")}, {"results"})

    def test_failed_games_and_timeouts_never_become_losses_or_draws(self):
        def play(name, request, identity, folder, tick):
            data = response(request, name)
            state = ("completed", "timeout", "completed", "failed")[request["game_number"] - 1]
            data["games"][0].update(status=state, winner="draw" if request["game_number"] == 3 else
                                     "subject" if state == "completed" else None)
            game, coverage = adapters.validate_response(data, name, request, identity)
            return {"game": game, "coverage": coverage, "response_sha256": model.digest(data),
                    "version": "fixture-1", "provenance": {}}
        with tempfile.TemporaryDirectory() as folder:
            receipt = self.run_plan(self.plan(games=4), folder, play=play)
            self.assertEqual(receipt["status"], "partial")
            counts = crosscheck.view(receipt)["engines"]["forge"]["baseline"]
            self.assertEqual((counts["wins"], counts["losses"], counts["draws"], counts["completed"]), (1, 0, 1, 2))
            self.assertEqual((counts["timeouts"], counts["failed"], counts["win_rate"]), (1, 1, 50))
            self.assertLess(counts["win_rate_interval"]["low"], 10)
            self.assertGreater(counts["win_rate_interval"]["high"], 90)

    def test_opposite_swap_results_are_shown_as_disagreement_not_averaged(self):
        def play(name, request, identity, folder, tick):
            found = fake_play(name, request, identity, folder, tick)
            found["game"]["winner"] = ("subject" if (request["decks"][0]["id"] == "variant") == (name == "forge")
                                        else "opponent")
            return found
        with tempfile.TemporaryDirectory() as folder:
            captured = self.plan(remove=["1 Elite Vanguard"], add=["1 Grizzly Bears"])
            result = crosscheck.view(self.run_plan(captured, folder, play=play))
            self.assertEqual(result["engines"]["forge"]["delta_percentage_points"], 100)
            self.assertEqual(result["engines"]["xmage"]["delta_percentage_points"], -100)
            self.assertEqual(result["agreement"]["status"], "different-direction")

    def test_unsupported_cards_stop_that_engine_without_substituting_anything(self):
        calls = []
        def play(name, request, identity, folder, tick):
            calls.append((name, deepcopy(request)))
            if name == "forge":
                return fake_play(name, request, identity, folder, tick)
            return {"game": None, "coverage": [{"deck_id": "baseline", "status": "unsupported", "missing": ["Elite Vanguard"]},
                                               {"deck_id": "opponent", "status": "supported", "missing": []}],
                    "response_sha256": "e" * 64, "version": "fixture-1", "provenance": {}}
        with tempfile.TemporaryDirectory() as folder:
            captured = self.plan()
            result = crosscheck.view(self.run_plan(captured, folder, play=play))
            xmage = result["engines"]["xmage"]
            self.assertEqual(xmage["status"], "unsupported")
            self.assertEqual(xmage["missing_cards"], ["Elite Vanguard"])
            self.assertIsNone(xmage["baseline"]["win_rate"])
            self.assertEqual(xmage["baseline"]["unplayed"], 2)
            self.assertEqual(sum(n == "xmage" for n, _ in calls), 1)
            self.assertEqual(captured, self.plan())

    def test_engine_changed_since_plan_never_launches_a_game(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(adapters, "details", return_value={"identity": "e" * 64}), mock.patch.object(adapters, "play") as launch:
            receipt = crosscheck.run(self.plan(), results_dir=folder)
            launch.assert_not_called()
            self.assertEqual(receipt["status"], "partial")
            self.assertEqual(receipt["engines"]["forge"]["reason_code"], "engine_changed")

    def test_job_stop_preserves_completed_games_and_attaches_receipt_id(self):
        def progress(done, total, detail):
            if done == 1:
                raise jobs.Stopped()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(jobs.Stopped) as caught:
                self.run_plan(self.plan(), folder, progress=progress)
            receipt = crosscheck.load(caught.exception.receipt_id, folder)
            self.assertEqual(receipt["status"], "cancelled")
            self.assertEqual(len(receipt["engines"]["forge"]["games"]), 1)
            self.assertEqual(crosscheck.view(receipt)["engines"]["forge"]["baseline"]["completed"], 1)

    def test_explicit_stop_is_not_swallowed_as_an_adapter_failure(self):
        event = threading.Event()
        event.set()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(crosscheck.CrosscheckStopped) as caught:
                self.run_plan(self.plan(), folder, stop=event)
            self.assertEqual(crosscheck.load(caught.exception.receipt_id, folder)["status"], "cancelled")

    def test_unexpected_exception_is_preserved_as_error_not_user_cancellation(self):
        def progress(done, total, detail):
            if done == 1:
                raise RuntimeError("fixture exception")
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RuntimeError) as caught:
                self.run_plan(self.plan(), folder, progress=progress)
            receipt = crosscheck.load(caught.exception.receipt_id, folder)
            self.assertEqual(receipt["status"], "error")
            self.assertEqual(receipt["engines"]["forge"]["reason_code"], "internal_error")

    def test_tampered_receipt_and_digest_valid_semantic_forgery_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt = self.run_plan(self.plan(), folder)
            path = Path(folder) / "results" / (receipt["id"] + ".json")
            corrupt = deepcopy(receipt)
            corrupt["engines"]["forge"]["games"][0]["winner"] = "opponent"
            path.write_text(json.dumps(corrupt), encoding="utf-8")
            self.assertIsNone(crosscheck.load(receipt["id"], folder))
            for mutate in (
                lambda r: r.update(status="fake"),
                lambda r: r["engines"]["forge"]["games"][0].update(seed=99),
                lambda r: r["engines"]["forge"]["games"][0].update(starting_player=True),
                lambda r: r["engines"]["forge"]["games"][0].update(request_sha256="a" * 64),
                lambda r: r["engines"]["forge"]["games"][0].update(response_sha256=None),
                lambda r: r.update(finished="2000-01-01T00:00:00+00:00"),
            ):
                forged = deepcopy(receipt)
                mutate(forged)
                forged.pop("id")
                forged["id"] = model.digest(forged)
                with self.subTest(mutate=mutate), self.assertRaises(crosscheck.CrosscheckError):
                    store.validate_receipt(forged)


class ResponseTests(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(crosscheck, "status", side_effect=readiness):
            self.plan = crosscheck.plan(entry(), entry("casual/lions", "Savannah Lions"), games=1)
        self.request = model.request(self.plan, "baseline", 1)
        self.response = response(self.request)

    def test_exact_response_is_accepted(self):
        game, coverage = adapters.validate_response(self.response, "xmage", self.request, "a" * 64)
        self.assertEqual(game["winner"], "subject")
        self.assertFalse(game["reproducible"])

    def test_wrong_request_identity_number_arm_seed_and_duplicate_games_are_refused(self):
        for mutate in (
            lambda v: v.update(request_sha256="f" * 64), lambda v: v.update(schema=True),
            lambda v: v.update(identity_sha256="f" * 64), lambda v: v.update(seed=True),
            lambda v: v["games"][0].update(number=2), lambda v: v["games"][0].update(arm="variant"),
            lambda v: v["games"][0].update(seed=2), lambda v: v["games"][0].update(starting_player=False),
            lambda v: v["games"][0].update(starting_player=1),
            lambda v: v["games"].append(deepcopy(v["games"][0])),
            lambda v: v["games"][0].update(status="failed", winner="subject"),
            lambda v: v.update(duration_seconds=float("nan")),
        ):
            value = deepcopy(self.response)
            mutate(value)
            with self.subTest(mutate=mutate), self.assertRaises(crosscheck.CrosscheckError):
                adapters.validate_response(value, "xmage", self.request, "a" * 64)

    def test_no_silent_missing_card_replacements_or_unknown_coverage(self):
        value = deepcopy(self.response)
        value["coverage"][0].update(status="unsupported", missing=["Elite Vanguard"])
        with self.assertRaises(crosscheck.CrosscheckError):
            adapters.validate_response(value, "xmage", self.request, "a" * 64)
        value["games"] = []
        self.assertIsNone(adapters.validate_response(value, "xmage", self.request, "a" * 64)[0])
        value["coverage"][0]["missing"] = ["A card outside the unchanged list"]
        with self.assertRaises(crosscheck.CrosscheckError):
            adapters.validate_response(value, "xmage", self.request, "a" * 64)


class ProcessBoundaryTests(unittest.TestCase):
    def test_cancel_callback_always_terminates_worker_and_strips_external_java_options(self):
        process = mock.Mock()
        process.poll.return_value = None
        def cancel():
            raise jobs.Stopped()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "game"
            with mock.patch.object(adapters.subprocess, "Popen", return_value=process) as launch, mock.patch.object(adapters, "_terminate") as terminate, mock.patch.dict(adapters.os.environ, {
                "JAVA_TOOL_OPTIONS": "fixture", "_JAVA_OPTIONS": "fixture", "JDK_JAVA_OPTIONS": "fixture", "CLASSPATH": "fixture"
            }):
                with self.assertRaises(jobs.Stopped):
                    adapters._execute(["fixture-java"], {"schema": 1}, target, 5, cancel)
                terminate.assert_called_once_with(process)
                environment = launch.call_args.kwargs["env"]
                self.assertFalse(set(environment) & {"JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH"})
                self.assertEqual(launch.call_args.kwargs["cwd"], target)
                self.assertEqual((target / "request.json").read_bytes(), b'{"schema":1}')

    def test_process_watchdog_is_not_counted_as_a_completed_draw(self):
        process = mock.Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(adapters.subprocess, "Popen", return_value=process), mock.patch.object(adapters, "_terminate") as terminate, mock.patch.object(adapters.time, "monotonic", side_effect=[0, 1000]):
            with self.assertRaisesRegex(crosscheck.CrosscheckError, "process-timeout"):
                adapters._execute(["fixture-java"], {"schema": 1}, Path(folder) / "game", 5, lambda: None)
            terminate.assert_called_once_with(process)
if __name__ == "__main__":
    unittest.main()
