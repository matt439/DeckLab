"""Tests of saved sideboard plans (decklab/lib/api/sideboard_test.py, E4-S16): POST
/api/play/sideboard-test starts a paired variant test of the plan's post-board list after the
preview's checks and the simulations setting, and GET /api/play/sideboard-tests lists the plan's
tests with their verdicts and older-list marks.

They use test_variant_api's real forge package over a Sandbox with forge.variants.run_test replaced
by its stand-in (no Forge game is played), and a MemoryStore for the plans and the setting.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_sideboard_test
"""
import json
from unittest import mock

from decklab.lib import api, feature_routes, inventory, state
from decklab.lib.api import guard, play_records as play, sideboard_preview as preview, sideboard_test as sbt
from decklab.lib.forge import variants
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state.memory import MemoryStore
from decklab.tests import test_forge
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_privacy_readers import _as
from decklab.tests.test_field_membership_api import FixtureHandler
from decklab.tests.test_matchups_api import deck_file
from decklab.tests.test_variant_api import GREEN_ID, RED_ID, SWAPPED, VariantApiCase, body, editor_list


class SideboardTestCase(VariantApiCase):
    mode = "everyone"

    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(ROLES))
        self.addCleanup(inventory.use(FileInventory(self.box.root)))
        self.store = MemoryStore(mode=self.mode)
        self.addCleanup(state.use(self.store))
        patch = mock.patch.object(play, "_play_today", return_value="2026-10-29")
        patch.start()
        self.addCleanup(patch.stop)
        self.saved = self.save_plan()

    def save_plan(self, out=(("Giant Growth", 2),), into=(("Lightning Bolt", 2),), who="matt"):
        with _as(who):
            a, b = play._snapshot(GREEN_ID, "target"), play._snapshot(RED_ID, "target")
            data = {"profile": who, "id": None, "sha256": None, "preview": True,
                    "deck": {key: a[key] for key in ("id", "version", "sha256")},
                    "opponent": {key: b[key] for key in ("id", "version", "sha256")},
                    "out": [{"name": n, "qty": q} for n, q in out], "in": [{"name": n, "qty": q} for n, q in into],
                    "notes": "Against burn."}
            checked = play.save_sideboard(body(**data))
            return play.save_sideboard(body(**{**data, "id": checked["id"], "preview": False,
                                               "review_sha256": checked["review_sha256"]}))

    def begin(self, who="matt", mode=None, saved=None):
        saved = saved or self.saved
        data = {"profile": who, "id": saved["record"]["id"], "sha256": saved["sha256"]}
        if mode is not None:
            data["mode"] = mode
        with _as(who):
            return sbt.start_sideboard_test(body(**data))

    def listed(self, who="matt", saved=None):
        saved = saved or self.saved
        with _as(who):
            return sbt.sideboard_tests(saved["record"]["id"], saved["sha256"])

    def finish(self, test):
        job = api.forge_runs.COORD_JOBS.get(f"variant:{test}")
        self.assertTrue(job.wait(5))


class StartTests(SideboardTestCase):

    def test_a_plan_plays_its_post_board_main_list_on_the_base_games_and_gives_a_verdict(self):
        answer = self.begin(mode="quick")
        self.assertEqual(set(answer), {"version", "plan", "test", "link", "status", "verdict", "words"})
        self.assertEqual(answer["plan"], {"id": self.saved["record"]["id"], "sha256": self.saved["sha256"]})
        self.assertEqual(answer["link"], f"#/variant?test={answer['test']}")
        self.finish(answer["test"])
        self.assertEqual(self.calls, [{"base": GREEN_ID, "against": RED_ID, "mode": "quick", "by": "Matt",
                                       "extend": None}])
        summary = variants.load_summary(answer["test"])
        self.assertEqual(summary["base"]["id"], GREEN_ID)
        self.assertEqual(summary["against"]["id"], RED_ID)
        self.assertEqual(summary["variant"]["changes"], {"remove": [[2, "Giant Growth"]], "add": [[2, "Lightning Bolt"]]})
        main = {name: qty for qty, name in summary["variant"]["cards"]["Main"]}
        self.assertEqual((main.get("Giant Growth"), main["Lightning Bolt"]), (None, 2))
        with _as("matt"):
            view = api.variant_view(answer["test"])
        self.assertEqual((view["verdict"], view["words"]), ("better", "Better against Red Test: +2.4 points of win "
                                                                       "rate (+0.6 to +4.2)"))
        self.assertEqual(self.store.play_get("sideboards", self.saved["record"]["id"]), self.saved["record"])

    def test_the_default_mode_is_ahead_and_an_unknown_mode_is_refused_before_any_read(self):
        with mock.patch.object(preview, "preview_sideboard") as read:
            self.assertApiError(400, self.begin, "matt", "forever")
            read.assert_not_called()
        self.finish(self.begin()["test"])
        self.assertEqual(self.calls[0]["mode"], "ahead")

    def test_a_list_changed_since_the_plan_refuses_without_a_game(self):
        path = self.box.magic / "decks" / "casual" / "red-test.md"
        path.write_text(deck_file("Red Test", test_forge.RED.replace("5 Swamp", "4 Swamp\n1 Mountain")),
                        encoding="utf-8")
        error = self.assertApiError(409, self.begin)
        self.assertEqual(error.message, preview.LISTS_CHANGED)
        self.assertEqual(self.calls, [])

    def test_a_list_saved_after_the_preview_pin_is_still_caught(self):
        real = variants.lists._list_text
        with mock.patch.object(sbt, "_card_sha", side_effect=lambda forge, sections, kind: "0" * 64):
            self.assertApiError(409, self.begin)
        self.assertIs(variants.lists._list_text, real)
        self.assertEqual(self.calls, [])

    def test_a_changed_record_and_a_stale_hash_refuse(self):
        stale = {**self.saved, "sha256": "0" * 64}
        error = self.assertApiError(409, self.begin, "matt", None, stale)
        self.assertEqual(error.message, preview.PLAN_CHANGED)
        self.assertEqual(self.calls, [])

    def test_mixed_formats_have_no_test(self):
        answer = {"game_plan": {"status": "unavailable"}}
        with mock.patch.object(preview, "preview_sideboard", return_value=answer):
            self.assertEqual(self.assertApiError(409, self.begin).message, sbt.FORMAT)
        self.assertEqual(self.calls, [])

    def test_forge_without_deck_order_refuses_with_its_reason(self):
        self.patches = ["attack-requirements-in-order-1"]
        self.assertEqual(self.assertApiError(503, self.begin).message, variants.NO_DECK_ORDER)
        self.assertEqual(self.calls, [])

    def test_the_same_plan_twice_joins_one_test(self):
        self.gate.clear()
        first = self.begin()
        self.assertTrue(self.started.wait(5))
        second = self.begin()
        self.assertEqual(first["test"], second["test"])
        self.assertIn(second["status"], ("queued", "running"))
        self.gate.set()
        self.finish(first["test"])
        self.assertEqual(len(self.calls), 1)

    def test_a_job_is_titled_for_the_plan(self):
        self.gate.clear()
        answer = self.begin()
        self.assertTrue(self.started.wait(5))
        job = api.forge_runs.COORD_JOBS.get(f"variant:{answer['test']}")
        self.assertEqual(job.fn.title, "Test of a sideboard plan for Green Test")
        self.assertEqual(job.fn.link, answer["link"])

    def test_the_route_is_a_post_with_no_query(self):
        handler = FixtureHandler("POST")
        handler._no_query = lambda query: self.assertEqual(query, {})
        handler._write_body = lambda limit: body(profile="matt", id=self.saved["record"]["id"],
                                                 sha256=self.saved["sha256"])
        with _as("matt"):
            self.assertTrue(feature_routes.dispatch(handler, ["play", "sideboard-test"], {}))
        self.assertEqual(handler.sent[0], 200)
        self.finish(handler.sent[1]["test"])


class AdminsOnlyTests(SideboardTestCase):
    mode = "admins"

    def test_a_member_sees_the_settings_reason_and_starts_nothing(self):
        error = self.assertApiError(403, self.begin, "user1")
        self.assertIn("admin", error.message)
        self.assertNotIn("Matt", error.message)
        self.assertEqual(self.calls, [])
        with _as("user1"):
            self.assertEqual(sbt.sideboard_tests(self.saved["record"]["id"], self.saved["sha256"])["tests"], [])

    def test_a_hidden_plan_answers_as_missing_before_the_setting(self):
        error = self.assertApiError(404, self.begin, "user2")
        self.assertEqual(error.message, preview.NO_PLAN)
        self.assertEqual(self.calls, [])


class PrivacyTests(SideboardTestCase):

    def test_another_space_never_starts_or_lists_a_plans_tests(self):
        self.finish(self.begin()["test"])
        for who in ("user2", "user3"):
            with self.subTest(who=who):
                self.assertEqual(self.assertApiError(404, self.begin, who).message, preview.NO_PLAN)
                self.assertEqual(self.assertApiError(404, self.listed, who).message, preview.NO_PLAN)
        with mock.patch.object(guard, "public_deck_spaces", return_value={"home"}):
            self.assertApiError(404, self.listed, "user2")      # public decks never publish private plans
        self.assertEqual(len(self.calls), 1)

    def test_a_home_member_sees_home_plan_tests_and_their_verdicts_without_a_starters_name(self):
        self.finish(self.begin()["test"])
        tests = self.listed("user1")["tests"]
        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0]["verdict"], "better")
        self.assertFalse(set(tests[0]) & {"by", "stopped_by", "cancelled_by"})
        self.assertNotIn("Matt", json.dumps(tests))

    def test_the_answer_passes_through_the_viewers_name_masking(self):
        self.finish(self.begin()["test"])
        with mock.patch.object(api.forge_runs._Seen, "mask", autospec=True,
                               side_effect=lambda seen, value: {**value, "masked": seen.everything}) as mask:
            answer = self.listed("user1")
        mask.assert_called_once()
        self.assertIs(answer["masked"], False)

    def test_a_hidden_opponent_refuses_without_naming_it(self):
        _write(self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md",
               deck_file("User2 private sentinel", test_forge.RED))
        record = json.loads(json.dumps(self.saved["record"]))
        record["opponent"]["id"] = "user2/casual/r-elves"
        with mock.patch.object(self.store, "play_get", return_value=record):
            for call in (self.begin, self.listed):
                error = self.assertApiError(409, call)
                self.assertEqual(error.message, preview.PAIR_UNAVAILABLE)
                self.assertNotIn("user2", error.message)
        self.assertEqual(self.calls, [])


class ListTests(SideboardTestCase):

    def test_a_plans_tests_carry_their_verdict_and_ignore_other_changes(self):
        test = self.begin()["test"]
        self.finish(test)
        with _as("matt"):
            other = api.run_variant(body(profile="matt", id=GREEN_ID, version="target", list=editor_list(SWAPPED),
                                         against={"id": RED_ID, "version": "target"}))["test"]["test"]
        self.finish(other)
        answer = self.listed()
        self.assertEqual(set(answer), {"version", "plan", "current", "tests"})
        self.assertTrue(answer["current"])
        self.assertEqual([item["test"] for item in answer["tests"]], [test])
        item = answer["tests"][0]
        self.assertEqual((item["verdict"], item["older_list"], item["link"], item["running"]),
                         ("better", False, f"#/variant?test={test}", False))
        self.assertIn("Better against Red Test", item["words"])
        self.assertNotIn("saved", item)

    def test_a_running_test_is_listed_first_without_words(self):
        self.gate.clear()
        test = self.begin()["test"]
        self.assertTrue(self.started.wait(5))
        item = self.listed()["tests"][0]
        self.assertEqual((item["test"], item["running"], item["words"]), (test, True, None))

    def test_a_test_on_an_older_list_is_marked(self):
        test = self.begin()["test"]
        self.finish(test)
        path = self.box.magic / "decks" / "casual" / "red-test.md"
        path.write_text(deck_file("Red Test", test_forge.RED.replace("5 Swamp", "4 Swamp\n1 Mountain")),
                        encoding="utf-8")
        answer = self.listed()
        self.assertFalse(answer["current"])
        self.assertEqual([(item["test"], item["older_list"]) for item in answer["tests"]], [(test, True)])
        self.assertApiError(409, self.begin)        # the old plan can't start a new test

    def test_a_printing_only_change_keeps_the_games_but_marks_the_plan_older(self):
        test = self.begin()["test"]
        self.finish(test)
        path = self.box.magic / "decks" / "casual" / "green-test.md"
        path.write_text(deck_file("Green Test", test_forge.GREEN.replace("2 Llanowar Elves (M19) 314",
                                                                         "2 Llanowar Elves")), encoding="utf-8")
        answer = self.listed()
        self.assertEqual((answer["current"], answer["tests"][0]["older_list"]), (False, True))

    def test_bad_requests_and_routes(self):
        for ident, sha in ((None, None), ("x", "a" * 64), (self.saved["record"]["id"], "A" * 64)):
            with self.subTest(ident=ident), mock.patch.object(state, "store") as store:
                self.assertApiError(400, sbt.sideboard_tests, ident, sha)
                store.assert_not_called()
        self.assertEqual(self.assertApiError(409, sbt.sideboard_tests, self.saved["record"]["id"],
                                             "0" * 64).message, preview.PLAN_CHANGED)
        handler = FixtureHandler("GET")
        query = {"id": [self.saved["record"]["id"]], "sha256": [self.saved["sha256"]]}
        with _as("matt"):
            self.assertTrue(feature_routes.dispatch(handler, ["play", "sideboard-tests"], query))
        self.assertEqual(handler.sent, (200, {"version": 1, "plan": {"id": self.saved["record"]["id"],
                                                                     "sha256": self.saved["sha256"]},
                                              "current": True, "tests": []}))
