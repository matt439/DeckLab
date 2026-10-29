"""Tests for Deck Lab's Forge matchup answers in decklab.lib.api (Milestone 5):
matchups(), matchup(), run_matchup() and stop_matchup() (GET /api/matchups,
GET /api/matchup, POST /api/matchup/run and /stop), and the deck page's
"matchups".

They run in test_api's Sandbox, whose FakeForge stands in for
decklab.lib.forge: the contract's functions over results kept in memory, and
a run that plays four quarter "batches" (side 0, the smaller card_sha, wins
3 games in 5) and, after the first, keeps reporting until its gate opens. A
test clears the gate to look at a run while it plays; the Sandbox opens it
and waits for every job at the end. The Sandbox gives each test a fresh
FORGE_JOBS runner, so no Forge process ever starts.

Run from the repo root: python scripts/test_fixtures.py
Execution integration, adaptive runs and runner scheduling live in test_matchups_runs.py;
shared fixtures and request/view checks remain here.
"""
import json
import os
import sys
import threading
import time
import types
import unittest
from unittest import mock

from decklab.lib import api, cards, decks, inventory, jobs
from decklab.lib import forge as real_forge         # RealForgeTests put it in FakeForge's place
from decklab.tests import test_forge
from decklab.tests.test_api import GRUUL, ApiTestCase, _write

GRUUL_ID, ELVES, PRECON = "casual/gruul-test", "commander/elf-commander", "product/fdc-test-precon"
WAIT = 5


def body(**data):
    return json.dumps(data).encode("utf-8")


def one_at_a_time():
    """A matchup runner like the server's (api._forge_runner) that plays one matchup at a
    time, for tests that need one waiting behind another (the server's plays 4 at once)."""
    return jobs.Runner(max_running=1, max_queued=10, log=lambda text: None, describe=api.forge_runs._matchup_error,
                       name="matchup")


class MatchupTestCase(ApiTestCase):

    def setUp(self):
        super().setUp()
        self.forge = self.box.forge

    def play(self, a=GRUUL_ID, av="target", b=GRUUL_ID, bv="owned", profile="matt", **extra):
        """POST /api/matchup/run: the owned-only Gruul list against its target list by default, a set
        number of games unless the test asks for a mode (wave 3: a profile's default mode is "assess")."""
        extra.setdefault("mode", "fixed")
        return api.run_matchup(body(profile=profile, a=a, av=av, b=b, bv=bv, **extra))

    def stop(self, key, profile="user1", **extra):
        return api.stop_matchup(body(profile=profile, key=key, **extra))

    def refused(self, status, call, *args, contains=None, **kwargs):
        """assertApiError for a call with keyword arguments."""
        return self.assertApiError(status, lambda: call(*args, **kwargs), contains=contains)

    def sha(self, deck_id, version="target"):
        return self.forge.entry(deck_id, version, "", "constructed", decks.load_deck(deck_id, version))["card_sha"]

    def a_first(self, a=(GRUUL_ID, "target"), b=(GRUUL_ID, "owned")):
        """True when a is the FakeForge's side 0 (the smaller card_sha), so it won 3 games in 5."""
        return self.sha(*a) < self.sha(*b)

    def playing(self):
        """Hold runs after their first batch until finish()."""
        self.forge.gate.clear()
        self.forge.started.clear()

    def finish(self):
        self.box.wait_for_jobs()

    def split(self, games, a_won_more):
        more, less = games * 3 // 5, games - games * 3 // 5
        return [more, less] if a_won_more else [less, more]


class NotPlayedTests(MatchupTestCase):

    def test_a_matchup_nobody_has_played(self):
        answer = api.matchup(GRUUL_ID, "target", GRUUL_ID, "owned")
        self.assertEqual(set(answer), {"key", "format", "sides", "status", "job", "result", "notice", "error",
                                       "choices", "default_games", "default_mode", "workers", "batch_games", "forge",
                                       "earlier", "estimates", "real_games"})
        self.assertRegex(answer["key"], r"^[0-9a-f]{64}$")
        # No results of an earlier engine, and no auto-profile known before any game.
        self.assertEqual(answer["earlier"], [])
        self.assertEqual([s["auto_profile"] for s in answer["sides"]], [None, None])
        self.assertEqual((answer["status"], answer["job"], answer["result"], answer["notice"], answer["error"]),
                         ("none", None, None, None, None))
        self.assertEqual((answer["format"], answer["choices"], answer["default_games"]),
                         ("Constructed", [200, 400, 800, 1600, 3200], 800))
        # config.json's forge_workers and forge_batch_games (the sandbox's has neither: the defaults); the page
        # uses only workers.
        self.assertEqual((answer["workers"], answer["batch_games"]), (16, 200))
        self.assertEqual(answer["forge"], {"ready": True, "version": "2.0.15", "problem": None})
        a, b = answer["sides"]
        self.assertEqual({k: a[k] for k in ("id", "version", "title", "kind", "card_count", "current")},
                         {"id": GRUUL_ID, "version": "target", "title": "Gruul Test", "kind": "casual",
                          "card_count": 23, "current": True})
        self.assertEqual((b["version"], b["card_count"], b["card_sha"]), ("owned", 4, self.sha(GRUUL_ID, "owned")))
        # Nothing played: the AI limits come from the lists themselves.
        self.assertEqual(a["ai"]["cannot_play"], [{"name": "Black Lotus", "qty": 1, "why": "script"}])
        self.assertEqual(b["ai"]["cannot_play"], [])
        self.assertEqual(self.forge.runs, [])
        json.dumps(answer, allow_nan=False)

    def test_either_order_is_one_key_and_versions_default_to_target(self):
        one = api.matchup(GRUUL_ID, "owned", GRUUL_ID, "target")["key"]
        self.assertEqual(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["key"], one)
        self.assertEqual(api.matchup("pairing/cats+elves", None, "pairing/elves+cats", None)["key"],
                         api.matchup("pairing/elves+cats", "target", "pairing/cats+elves", "target")["key"])

    def test_commander_decks_play_commander_decks(self):
        answer = api.matchup(ELVES, "target", PRECON, "target")
        self.assertEqual((answer["format"], [s["kind"] for s in answer["sides"]]),
                         ("Commander", ["commander", "product"]))
        pairing = api.matchup("pairing/cats+elves", None, "pairing/cats+goblins", None)
        self.assertEqual([s["kind"] for s in pairing["sides"]], ["pairing", "pairing"])
        self.assertEqual(pairing["sides"][0]["title"], "Elves + Cats (Beginner Box)")

    def test_a_mirror_match_is_allowed(self):
        answer = api.matchup(GRUUL_ID, "target", GRUUL_ID, "target")
        self.assertEqual(answer["sides"][0]["card_sha"], answer["sides"][1]["card_sha"])
        self.play(bv="target")
        self.finish()
        done = api.matchup(GRUUL_ID, "target", GRUUL_ID, "target")
        self.assertEqual((done["status"], done["result"]["wins"]), ("done", [480, 320]))
        self.assertEqual([s["ai"]["for"] for s in done["sides"]], [answer["sides"][0]["card_sha"]] * 2)

    def test_the_profile_picks_the_default_games(self):
        api.put_settings("user1", b'{"matchup_games": "1600"}')
        self.assertEqual(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned", profile="user1")["default_games"], 1600)
        self.assertEqual(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned", profile="matt")["default_games"], 800)
        self.assertEqual(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["default_games"], 800)
        self.assertApiError(404, api.matchup, GRUUL_ID, None, GRUUL_ID, "owned", None, "nobody")
        self.assertApiError(404, api.matchup, GRUUL_ID, None, GRUUL_ID, "owned", None, "../matt")

    def test_the_profile_picks_the_default_mode(self):
        # The page's first run mode on a matchup page opened directly (matchups.js startingMode).
        api.put_settings("user1", b'{"matchup_mode": "ahead"}')
        self.assertEqual(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned", profile="user1")["default_mode"], "ahead")
        self.assertEqual(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned", profile="matt")["default_mode"], "assess")
        self.assertIsNone(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["default_mode"])

    def test_the_defaults_with_the_database_down(self):
        # The matchup page still answers: the settings last known, else the defaults.
        api.put_settings("user1", b'{"matchup_games": "1600", "matchup_mode": "ahead"}')
        self.box.state.down = True
        user1 = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned", profile="user1")
        self.assertEqual((user1["default_games"], user1["default_mode"]), (1600, "ahead"))
        matt = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned", profile="matt")
        self.assertEqual((matt["default_games"], matt["default_mode"]), (800, "assess"))

    def test_the_rough_time_follows_config_json(self):
        # QUALITY-9: the page works out a run's rough time from forge_workers. forge_batch_games is still
        # sent as "batch_games" for older clients, though the page no longer uses it.
        from decklab.tests.test_api import CONFIG
        config_file = self.box.root / "config.json"
        config_file.write_text(json.dumps({**CONFIG, "forge_workers": 8, "forge_batch_games": "100"}),
                               encoding="utf-8")
        key = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["key"]
        answers = {"matchups": api.matchups(), "matchup": api.matchup(GRUUL_ID, None, GRUUL_ID, "owned"),
                   "run": self.play(games=200)}
        self.finish()
        answers["by key"] = api.matchup(key=key)
        answers["stop"] = self.stop(key)
        for name, answer in answers.items():
            with self.subTest(answer=name):
                self.assertEqual((answer["workers"], answer["batch_games"]), (8, 100))
        # Numbers forge.status() refuses, or a config.json that can't be read: the page's own defaults.
        for bad in ({**CONFIG, "forge_workers": 0, "forge_batch_games": "lots"},
                    {**CONFIG, "forge_workers": None, "forge_batch_games": [200]}):
            config_file.write_text(json.dumps(bad), encoding="utf-8")
            with self.subTest(config=bad):
                self.assertEqual({k: api.matchups()[k] for k in ("workers", "batch_games")},
                                 {"workers": None, "batch_games": None})
        config_file.write_text("{not json", encoding="utf-8")
        answer = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")
        self.assertEqual((answer["workers"], answer["batch_games"], answer["status"]), (None, None, "done"))
        json.dumps(answer, allow_nan=False)

    def test_bad_requests(self):
        m = api.matchup
        self.assertApiError(400, m, None, None, GRUUL_ID, None, contains="a and b")
        self.assertApiError(400, m, GRUUL_ID, None, None, None)
        self.assertApiError(400, m, "../../CLAUDE", None, GRUUL_ID, None)
        self.assertApiError(400, m, GRUUL_ID, "Owned", GRUUL_ID, None)
        self.assertApiError(404, m, "casual/nope", None, GRUUL_ID, None)
        self.assertApiError(404, m, GRUUL_ID, None, ELVES, "owned")
        self.assertApiError(500, m, "casual/broken", None, GRUUL_ID, None, contains="casual/broken can't be read")
        # A half only plays in a pairing, as with practice hands.
        error = self.assertApiError(400, m, "product/fdn-beginner-box/cats", None, GRUUL_ID, None)
        self.assertIn("Cats is half of a Beginner Box deck", error.message)
        self.assertApiError(400, m, "pairing/cats+elves", None, "product/fdn-beginner-box/elves", None)
        # A 60-card deck can't play a Commander deck, in either order.
        error = self.assertApiError(400, m, GRUUL_ID, None, ELVES, None)
        self.assertEqual(error.message, "Elf Commander is a Commander deck and Gruul Test isn't: a Commander deck "
                                        "only plays another Commander deck.")
        self.assertApiError(400, m, PRECON, None, "pairing/cats+elves", None, contains="Commander deck")
        with self.box.no_index():
            self.assertApiError(503, m, GRUUL_ID, None, GRUUL_ID, "owned")

    def test_no_matchup_module(self):
        with mock.patch.dict(sys.modules, {"decklab.lib.forge": None}):
            self.assertApiError(500, api.matchup, GRUUL_ID, None, GRUUL_ID, "owned", contains="aren't available")
            self.assertApiError(500, api.matchups, contains="aren't available")
            self.assertApiError(500, self.play, contains="aren't available")
        self.assertTrue(any("Forge matchups can't be loaded" in line and "Traceback" in line
                            for line in self.box.logs))


class RunTests(MatchupTestCase):

    def test_a_run_plays_in_the_background_then_the_result_answers(self):
        self.playing()
        answer = self.play(games=400)
        self.assertIn(answer["status"], ("queued", "running"))
        self.assertTrue(self.forge.started.wait(WAIT))
        a_first = self.a_first()
        answer = api.matchup(GRUUL_ID, "target", GRUUL_ID, "owned")
        self.assertEqual(answer["status"], "running")
        self.assertIsNone(answer["result"])
        job = answer["job"]
        self.assertEqual({k: job[k] for k in ("status", "ahead", "done", "total", "other", "games_per_min", "by")},
                         {"status": "running", "ahead": 0, "done": 100, "total": 400, "other": 0,
                          "games_per_min": 600.0, "by": "Matt"})
        self.assertEqual(job["wins"], self.split(100, a_first))           # from a's point of view
        rate = job["range"]
        self.assertEqual(rate["value"], job["wins"][0] / 100)
        self.assertLess(rate["low"], rate["value"])
        self.assertGreater(rate["high"], rate["value"])
        self.assertIsInstance(job["seconds"], float)
        self.assertIn("eta_s", job)
        self.assertIsNone(job["waiting"])           # it has a slot of the PC's budget
        # forge.run got the lists as asked, the games and who asked.
        self.assertEqual(self.forge.runs, [(GRUUL_ID, GRUUL_ID, 400, "Matt")])
        self.finish()
        done = api.matchup(GRUUL_ID, "target", GRUUL_ID, "owned")
        self.assertEqual((done["status"], done["job"], done["notice"], done["error"]), ("done", None, None, None))
        self.assertEqual((done["result"]["games"], done["result"]["wins"]), (400, self.split(400, a_first)))
        self.assertEqual(done["result"]["runs"][0]["by"], "Matt")
        json.dumps(done, allow_nan=False)

    def test_live_ranges_keep_adaptive_data_and_count_non_wins_from_either_side(self):
        job = types.SimpleNamespace(fn=types.SimpleNamespace(games=200, by="Matt", mode="fixed"))
        snap = {"detail": {"wins": [30, 18], "other": 2}, "status": jobs.RUNNING,
                "ahead": 0, "progress": {"done": 50, "total": 200}, "seconds": 1.0}
        first = api.forge_runs._job_json(job, snap, False)["range"]
        other = api.forge_runs._job_json(job, snap, True)["range"]
        self.assertEqual((first["value"], other["value"]), (0.6, 0.36))
        self.assertNotAlmostEqual(first["value"] + other["value"], 1)
        self.assertLess(first["low"], first["value"])
        self.assertGreater(first["high"], first["value"])
        # Adaptive ranges also cover games saved before this run; prefer them to this run's score.
        ranges = [{"value": 0.52, "low": 0.42, "high": 0.62},
                  {"value": 0.45, "low": 0.35, "high": 0.55}]
        snap["detail"]["range"] = ranges
        for flip in (False, True):
            self.assertEqual(api.forge_runs._job_json(job, snap, flip)["range"], ranges[int(flip)])
        snap["detail"] = {}
        snap["status"] = jobs.QUEUED
        self.assertIsNone(api.forge_runs._job_json(job, snap, False)["range"])

    def test_the_other_way_round_everything_flips(self):
        self.playing()
        self.play(games=800)
        self.assertTrue(self.forge.started.wait(WAIT))
        a_first = self.a_first()
        there = api.matchup(GRUUL_ID, "target", GRUUL_ID, "owned")
        back = api.matchup(GRUUL_ID, "owned", GRUUL_ID, "target")
        self.assertEqual(there["key"], back["key"])
        self.assertEqual(back["job"]["wins"], list(reversed(there["job"]["wins"])))
        self.assertEqual([s["version"] for s in back["sides"]], ["owned", "target"])
        self.finish()
        there = api.matchup(GRUUL_ID, "target", GRUUL_ID, "owned")
        back = api.matchup(GRUUL_ID, "owned", GRUUL_ID, "target")
        self.assertEqual(there["result"]["wins"], self.split(800, a_first))
        self.assertEqual(back["result"]["wins"], self.split(800, not a_first))
        # Each side's AI limits are that side's, whichever way round it's asked.
        for answer in (there, back):
            self.assertEqual([s["ai"]["for"] for s in answer["sides"]], [s["card_sha"] for s in answer["sides"]])

    def test_a_run_waiting_for_other_runs_on_the_pc_says_so(self):
        # forge's progress says "waiting" (slots.WAITING) while other runs hold every slot of the PC's
        # budget, or the warm pool's sentence while other matchups' games hold its workers; the job and
        # the Running item pass it to the page.
        for waiting in ("Waiting for other Forge runs on this PC to finish.",
                        "Waiting for other matchups ahead in the queue."):
            with self.subTest(waiting=waiting):
                self.forge.waiting = waiting
                self.playing()
                self.play(games=400)
                self.assertTrue(self.forge.started.wait(WAIT))
                answer = api.matchup(GRUUL_ID, "target", GRUUL_ID, "owned")
                self.assertEqual((answer["status"], answer["job"]["waiting"]), ("running", waiting))
                self.assertEqual([r["waiting"] for r in api.matchups()["running"]], [waiting])
                self.finish()
        self.assertEqual(self.forge.waiting, real_forge.pool.QUEUED)

    def test_a_run_whose_warm_workers_cant_start_says_so(self):
        # forge's progress has "fallback" when the warm pool's workers couldn't start (pool.FALLBACK);
        # the job passes it to the page (None otherwise).
        self.playing()
        self.play(games=400)
        self.assertTrue(self.forge.started.wait(WAIT))
        self.assertIsNone(api.matchup(GRUUL_ID, "target", GRUUL_ID, "owned")["job"]["fallback"])
        self.finish()
        self.forge.fallback = real_forge.pool.FALLBACK.format(why=real_forge.pool.FALLBACK_DIED)
        self.playing()
        self.play(games=400)
        self.assertTrue(self.forge.started.wait(WAIT))
        self.assertEqual(api.matchup(GRUUL_ID, "target", GRUUL_ID, "owned")["job"]["fallback"], self.forge.fallback)
        self.finish()

    def test_matchups_play_four_at_once(self):
        # The server's matchups share its warm pool's queue, so up to 4 play at once; the 5th waits.
        self.playing()
        pairs = [("pairing/cats+elves", "pairing/cats+goblins"), (GRUUL_ID, GRUUL_ID), (ELVES, ELVES),
                 ("pairing/cats+elves", "pairing/cats+elves"), (PRECON, PRECON)]
        answers = [self.play(a=a, av=None, b=b, bv=None) for a, b in pairs]
        self.assertTrue(self.forge.started.wait(WAIT))
        statuses = [api.matchup(key=answer["key"])["status"] for answer in answers]
        self.assertEqual(statuses, ["running"] * 4 + ["queued"])
        self.finish()

    def test_asking_again_joins_the_run(self):
        self.playing()
        first = self.play(games=400)
        self.assertTrue(self.forge.started.wait(WAIT))
        # User1 asks for the same lists the other way round, with other games: one run.
        joined = self.play(a=GRUUL_ID, av="owned", b=GRUUL_ID, bv="target", games=3200, profile="user1")
        self.assertEqual((joined["key"], joined["status"]), (first["key"], "running"))
        self.assertEqual((joined["job"]["total"], joined["job"]["by"]), (400, "Matt"))
        self.finish()
        self.assertEqual(len(self.forge.runs), 1)
        # Once it's over, another request plays more games of the same matchup.
        again = self.play(games=200, profile="user1")
        self.finish()
        self.assertEqual(len(self.forge.runs), 2)
        done = api.matchup(GRUUL_ID, "target", GRUUL_ID, "owned")
        self.assertEqual(done["result"]["games"], 600)
        self.assertEqual([r["by"] for r in done["result"]["runs"]], ["Matt", "User1"])
        self.assertEqual(again["key"], first["key"])

    def test_games_come_from_the_profile_unless_asked(self):
        api.put_settings("user1", b'{"matchup_games": "200"}')
        answer = api.run_matchup(body(profile="user1", a=GRUUL_ID, b=GRUUL_ID, bv="owned", mode="fixed"))
        self.assertEqual(answer["default_games"], 200)
        self.finish()
        self.assertEqual(self.forge.runs[-1][2:], (200, "User1"))
        self.play(games="1600")         # digits are fine too
        self.finish()
        self.assertEqual(self.forge.runs[-1][2], 1600)

    def test_bad_runs_are_refused_and_nothing_plays(self):
        for games in (100, 0, 801, -800, "800x", "", True, 800.0, None, [800]):
            with self.subTest(games=games):
                self.refused(400, self.play, games=games, contains="games must be one of")
        self.refused(400, self.play, a="product/fdn-beginner-box/cats", contains="half of a Beginner Box")
        self.refused(400, self.play, b=ELVES, bv="target", contains="Commander deck")
        self.refused(400, self.play, av="foil")
        self.refused(404, self.play, a="casual/nope")
        self.assertApiError(403, api.run_matchup, body(a=GRUUL_ID, b=GRUUL_ID), contains="Choose who you are")
        self.refused(403, self.play, profile="nobody", contains="Choose who you are")
        self.assertApiError(400, api.run_matchup, body(profile="matt", a=GRUUL_ID), contains="needs b")
        self.assertApiError(400, api.run_matchup, body(profile="matt", a=GRUUL_ID, b=GRUUL_ID, seed=1),
                            contains="Unknown key 'seed'")
        self.assertApiError(400, api.run_matchup, b"not json")
        self.assertApiError(413, api.run_matchup, body(profile="matt", a=GRUUL_ID, b=GRUUL_ID, x="y" * 5000))
        with self.box.no_index():
            self.assertApiError(503, self.play)
        self.assertEqual(self.forge.runs, [])

    def test_forge_not_ready_is_503_with_its_reason(self):
        self.forge.ready, self.forge.problem = False, "Java wasn't found."
        self.assertApiError(503, self.play, contains="Java wasn't found.")
        self.assertEqual(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["forge"]["ready"], False)
        self.assertEqual(self.forge.runs, [])

    def test_ten_waiting_is_busy(self):
        runner = api._forge_runner()
        # 4 at once (wave 2: they share the warm pool's queue), at most 10 waiting.
        self.assertEqual((runner.max_running, runner.max_queued), (4, 10))
        self.assertIsNot(runner, api.practice.JOBS)
        with mock.patch.object(api.forge_runs, "FORGE_JOBS", api.jobs.Runner(max_running=1, max_queued=1)):
            self.playing()
            self.play()
            self.assertTrue(self.forge.started.wait(WAIT))
            self.play(av="owned", bv="owned")                           # waits
            self.refused(503, self.play, bv="target", contains="10 matchups are already waiting")
            self.play()                                                 # joining still works
            self.finish()
            for job in api.forge_runs.FORGE_JOBS._jobs.values():
                self.assertTrue(job.wait(WAIT))

    def test_while_the_server_stops_no_run_starts_and_it_says_why(self):
        # Review finding API-4: it said 10 matchups were waiting.
        api.forge_runs.FORGE_JOBS.stop()
        error = self.refused(503, self.play)
        self.assertEqual(error.message, "Deck Lab is stopping on the PC, so no new matchup can start.")
        self.assertEqual(self.forge.runs, [])

    def test_practice_hands_dont_wait_behind_a_matchup(self):
        self.playing()
        self.play()
        self.assertTrue(self.forge.started.wait(WAIT))
        answer = api.goldfish(GRUUL_ID)
        self.assertIn(answer["status"], ("running", "done"))
        self.box.goldfish.gate.set()
        for job in list(api.practice.JOBS._jobs.values()):
            self.assertTrue(job.wait(WAIT))
        self.assertEqual(api.goldfish(GRUUL_ID)["status"], "done")
        self.assertEqual(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["status"], "running")

    def test_a_forge_error_is_shown_as_it_is(self):
        self.forge.error = self.forge.ForgeError("Forge doesn't know this card, so the matchup can't be played: "
                                                 "Black Lotus.")
        self.play()
        self.finish()
        answer = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")
        self.assertEqual((answer["status"], answer["result"]), ("error", None))     # the record played nothing
        self.assertEqual(answer["error"], "Forge doesn't know this card, so the matchup can't be played: Black Lotus.")
        # It's still said after the job itself is forgotten (the server restarted), from the saved run record.
        with mock.patch.object(api.forge_runs, "FORGE_JOBS", api._forge_runner()):
            self.assertEqual(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["error"], answer["error"])
        # A run that works afterwards clears it.
        self.forge.error = None
        self.play()
        self.finish()
        answer = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")
        self.assertEqual((answer["status"], answer["error"], answer["result"]["games"]), ("done", None, 800))

    def test_any_other_failure_is_a_plain_sentence_and_the_traceback_is_logged(self):
        self.play()
        self.finish()
        self.forge.error = OSError(13, "Permission denied", str(self.box.data / "forge" / "results" / "x.json"))
        self.play()
        self.finish()
        answer = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")
        # The earlier result still shows; the error says the last run failed.
        self.assertEqual((answer["status"], answer["error"]), ("done", api.MATCHUP_FAILED))
        self.assertEqual(answer["result"]["games"], 800)
        self.assertNotIn(str(self.box.root), json.dumps(answer))
        self.assertTrue(any("matchup" in line and "Traceback" in line and "Permission denied" in line
                            for line in self.box.logs))

    def test_failed_batches_are_noticed(self):
        self.forge.failed_batches = 2
        self.play()
        self.finish()
        answer = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")
        self.assertEqual(answer["notice"], "2 of 4 batches failed: Forge stopped responding. "
                                           "Their games aren't counted.")
        self.assertEqual(answer["result"]["games"], 400)


class StopTests(MatchupTestCase):

    def test_stopping_a_run_keeps_the_games_it_finished(self):
        self.playing()
        key = self.play(games=800)["key"]
        self.assertTrue(self.forge.started.wait(WAIT))
        answer = self.stop(key, a=GRUUL_ID, av="target", b=GRUUL_ID, bv="owned")
        self.assertEqual(answer["status"], "done")
        self.assertEqual(answer["notice"], "Stopped by User1 after 200 of 800 games.")
        self.assertEqual((answer["result"]["games"], answer["result"]["runs"][0]["stopped"]), (200, True))
        self.assertEqual([s["version"] for s in answer["sides"]], ["target", "owned"])
        self.assertEqual(answer["error"], None)
        # The page asking later sees the same, even once the job is forgotten.
        self.assertEqual(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["notice"], answer["notice"])
        with mock.patch.object(api.forge_runs, "FORGE_JOBS", api._forge_runner()):
            self.assertEqual(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["notice"], answer["notice"])
        self.assertEqual([line for line in self.box.logs if "Traceback" in line], [])

    def test_stopping_a_waiting_run_takes_it_off_the_queue(self):
        runner = mock.patch.object(api.forge_runs, "FORGE_JOBS", one_at_a_time())
        runner.start()
        self.addCleanup(runner.stop)
        self.playing()
        first = self.play()["key"]
        self.assertTrue(self.forge.started.wait(WAIT))
        waiting = self.play(a="pairing/cats+elves", av=None, b="pairing/cats+goblins", bv=None, profile="user1")
        self.assertEqual((waiting["status"], waiting["job"]["ahead"]), ("queued", 1))
        answer = self.stop(waiting["key"], profile="matt")
        self.assertEqual((answer["status"], answer["notice"], answer["result"]), ("none", "Stopped by Matt before it started.", None))
        self.assertEqual([item["key"] for item in api.matchups()["running"]], [first])
        self.finish()
        self.assertEqual([r[0] for r in self.forge.runs], [GRUUL_ID])      # the waiting one never played

    def test_stopping_what_isnt_playing_changes_nothing(self):
        self.play()
        self.finish()
        key = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["key"]
        answer = self.stop(key)
        self.assertEqual((answer["status"], answer["notice"], answer["result"]["games"]), ("done", None, 800))
        self.assertEqual(len(self.forge.runs), 1)
        self.assertApiError(404, self.stop, "0" * 64)
        self.assertApiError(400, self.stop, "not a key")
        self.refused(403, self.stop, key, profile=None)
        self.refused(400, self.stop, key, a=GRUUL_ID, b=GRUUL_ID, bv="target", contains="aren't the ones")
        self.refused(400, api.stop_matchup, body(profile="matt", key=key, games=800))
        # Review finding API-6: one deck alone, or a version alone, says what's missing.
        for extra in ({"a": GRUUL_ID}, {"b": GRUUL_ID, "bv": "owned"}, {"av": "owned"}, {"bv": "target"}):
            with self.subTest(**extra):
                error = self.refused(400, self.stop, key, **extra)
                self.assertEqual(error.message, "Give both decks (a and b) with the key, or neither.")
        self.assertEqual(len(self.forge.runs), 1)

    def test_a_stop_before_any_game_finished_says_so(self):
        # Review finding PAGE-8: "Stopped by User1 after 0 of 800 games."
        self.forge.slow_start = True
        self.playing()
        key = self.play()["key"]
        self.assertTrue(self.forge.started.wait(WAIT))
        answer = self.stop(key, a=GRUUL_ID, av="target", b=GRUUL_ID, bv="owned")
        self.assertEqual((answer["status"], answer["result"], answer["error"]), ("none", None, None))
        self.assertEqual(answer["notice"], "Stopped by User1 before any game finished.")
        self.assertEqual(api.matchups()["results"], [])
        # When no one was named (the server stopping), it says so without a name.
        self.forge.slow_start = False
        self.playing()
        self.forge.slow_start = True
        self.play()
        self.assertTrue(self.forge.started.wait(WAIT))
        api.stop_jobs()
        self.assertTrue(api.forge_runs.FORGE_JOBS.join(WAIT))
        self.assertEqual(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["notice"], "Stopped before any game finished.")

    def test_a_stop_waits_for_the_run_to_save_but_not_for_ever(self):
        # stop_matchup waits up to STOP_WAIT seconds for the run to save its games: past that it
        # answers with the run still going, and the notice comes with a later answer.
        self.forge.stop_delay = 0.5
        self.playing()
        key = self.play()["key"]
        self.assertTrue(self.forge.started.wait(WAIT))
        with mock.patch.object(api.forge_runs, "STOP_WAIT", 0.05):
            answer = self.stop(key)
        self.assertEqual((answer["status"], answer["notice"]), ("running", None))
        self.assertEqual(answer["job"]["by"], "Matt")
        self.finish()
        self.assertEqual(api.matchup(key=key)["notice"], "Stopped by User1 after 200 of 800 games.")
        # A second press, by someone else, doesn't rename who stopped it.
        self.playing()
        self.play()
        self.assertTrue(self.forge.started.wait(WAIT))
        with mock.patch.object(api.forge_runs, "STOP_WAIT", 0.05):
            self.stop(key, profile="user1")
            self.stop(key, profile="matt")
        self.finish()
        self.assertEqual(api.matchup(key=key)["notice"], "Stopped by User1 after 200 of 800 games.")

    def test_a_failure_after_stop_is_shown_and_logged(self):
        # Review finding API-3: a real failure after Stop was taken for the stop and never logged.
        self.playing()
        key = self.play()["key"]
        self.assertTrue(self.forge.started.wait(WAIT))
        # Saving the stopped run's games fails.
        with mock.patch.object(self.forge, "_save", side_effect=OSError(28, "No space left on device")):
            answer = self.stop(key)
        self.assertEqual((answer["status"], answer["error"], answer["notice"]), ("error", api.MATCHUP_FAILED, None))
        self.assertTrue(any("matchup" in line and "Traceback" in line and "No space left" in line
                            for line in self.box.logs))

    def test_the_server_stopping_stops_the_run_too(self):
        runner = mock.patch.object(api.forge_runs, "FORGE_JOBS", one_at_a_time())
        runner.start()
        self.addCleanup(runner.stop)
        self.playing()
        self.play()
        self.assertTrue(self.forge.started.wait(WAIT))
        self.play(av="owned")                                           # waiting
        api.stop_jobs()
        self.assertTrue(api.forge_runs.FORGE_JOBS.join(WAIT))
        self.assertTrue(api.practice.JOBS._stopping.is_set())
        stopped = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")
        self.assertEqual((stopped["status"], stopped["notice"]), ("done", "Stopped after 200 of 800 games."))
        self.assertEqual(len(self.forge.runs), 1)
        self.assertEqual([line for line in self.box.logs if "Traceback" in line], [])


class KeyTests(MatchupTestCase):

    def test_a_result_by_its_key(self):
        self.play(games=400)
        self.finish()
        key = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["key"]
        answer = api.matchup(key=key)
        self.assertEqual((answer["status"], answer["result"]["games"]), ("done", 400))
        # In the order the last run asked for them, named as they were last played, and both still current.
        shas = [self.sha(GRUUL_ID, "target"), self.sha(GRUUL_ID, "owned")]
        self.assertEqual([s["card_sha"] for s in answer["sides"]], shas)
        self.assertEqual({(s["id"], s["version"], s["title"], s["kind"], s["current"]) for s in answer["sides"]},
                         {(GRUUL_ID, "target", "Gruul Test", "casual", True),
                          (GRUUL_ID, "owned", "Gruul Test", "casual", True)})
        self.assertEqual(answer["result"]["wins"], [240, 160])          # the first side's point of view
        self.assertEqual(api.matchup(key=key, profile="user1")["default_games"], 800)

    def test_an_older_list_isnt_current(self):
        self.play()
        self.finish()
        key = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["key"]
        _write(self.box.magic / "decks" / "casual" / "gruul-test.md",
               GRUUL.replace("4 Llanowar Elves (FDN) 227\n```", "3 Llanowar Elves (FDN) 227\n```"))
        answer = api.matchup(key=key)
        current = {s["version"]: s["current"] for s in answer["sides"]}
        self.assertEqual(current, {"target": True, "owned": False})
        listed = api.matchups()["results"][0]["sides"]
        self.assertEqual({s["version"]: s["current"] for s in listed}, {"target": True, "owned": False})
        # The target list's page still lists it, marked with its opponent's older list.
        on_page = api.deck_view(GRUUL_ID)["matchups"]["results"][0]["sides"]
        self.assertEqual([(s["version"], s["current"]) for s in on_page], [("target", True), ("owned", False)])
        # Asked for by the decks, it's a new matchup now.
        self.assertEqual(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["status"], "none")

    def test_a_renamed_deck_shows_its_title_today(self):
        # UI review MU-15: results listed a renamed deck under its old title ("Izzet Prowess" beside "Izzet
        # Otters"); the sides of saved results now carry the deck's title today.
        self.play()
        self.finish()
        key = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["key"]
        _write(self.box.magic / "decks" / "casual" / "gruul-test.md", GRUUL.replace("# Gruul Test", "# Gruul Renamed"))
        self.assertEqual({s["title"] for s in api.matchups()["results"][0]["sides"]}, {"Gruul Renamed"})
        self.assertEqual({s["title"] for s in api.matchup(key=key)["sides"]}, {"Gruul Renamed"})

    def test_running_only_reads_no_saved_result(self):
        # ?running=1 (the top bar's "Forge playing" pill asks on every page): the runs waiting or playing and
        # Forge's state, without reading the saved results.
        self.play(games=200)
        self.finish()
        self.assertEqual(api.matchups(running=True), {"running": [], "forge": self.forge.status()})
        self.playing()
        self.play(games=400)
        self.assertTrue(self.forge.started.wait(WAIT))
        with mock.patch.object(self.forge, "load", side_effect=AssertionError("read a result")),                 mock.patch.object(self.forge, "results", side_effect=AssertionError("read the results")):
            answer = api.matchups(running=True)
        self.assertEqual(set(answer), {"running", "forge"})
        self.assertEqual([(r["status"], r["by"], r["total"]) for r in answer["running"]], [("running", "Matt", 400)])
        self.finish()

    def test_a_deck_page_keeps_its_earlier_lists_results(self):
        # Review finding E2E-4: once a list changed, its own page dropped the results of the old one.
        self.play(a="pairing/cats+elves", av=None, b=GRUUL_ID, bv="owned")     # owned vs a pairing
        self.finish()
        self.play(a=GRUUL_ID, av="owned", b=GRUUL_ID, bv="target", games=200)   # owned vs target
        self.finish()
        old = self.sha(GRUUL_ID, "owned")
        before = api.deck_view(GRUUL_ID, "owned")["matchups"]["results"]
        self.assertEqual([[s["current"] for s in item["sides"]] for item in before], [[True, True], [True, True]])
        _write(self.box.magic / "decks" / "casual" / "gruul-test.md",
               GRUUL.replace("4 Llanowar Elves (FDN) 227\n```", "3 Llanowar Elves (FDN) 227\n```"))
        self.assertNotEqual(self.sha(GRUUL_ID, "owned"), old)
        after = api.deck_view(GRUUL_ID, "owned")["matchups"]["results"]
        # Both still show, newest first, with the earlier owned-only list first and marked as older.
        self.assertEqual([item["key"] for item in after], [item["key"] for item in before])
        for item in after:
            self.assertEqual((item["sides"][0]["card_sha"], item["sides"][0]["version"], item["sides"][0]["current"]),
                             (old, "owned", False))
        self.assertEqual([item["sides"][1]["id"] for item in after], [GRUUL_ID, "pairing/elves+cats"])
        self.assertEqual(after[1]["winrate"], before[1]["winrate"])    # from the owned-only list's side
        # A new result of today's list comes before the earlier lists' ones.
        self.play(a=GRUUL_ID, av="owned", b="pairing/cats+goblins", bv=None, games=200)
        self.finish()
        now = api.deck_view(GRUUL_ID, "owned")["matchups"]["results"]
        self.assertEqual([item["sides"][0]["current"] for item in now], [True, False, False])
        # The target list's page shows only its own list's results (its list didn't change).
        target = api.deck_view(GRUUL_ID)["matchups"]["results"]
        self.assertEqual([(item["sides"][0]["version"], item["sides"][0]["current"]) for item in target],
                         [("target", True)])

    def test_results_of_an_earlier_engine(self):
        # Wave 2's engine id: a result of another engine than today's keeps its key, and a run of its lists
        # starts today's (here the stand-in's engine changes with its run version).
        self.play(games=400)
        self.finish()
        old = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["key"]
        self.assertEqual(api.matchup(key=old)["result"]["engine"], self.forge.TODAYS_ENGINE)
        self.assertEqual(api.matchup(key=old)["earlier"], [])
        # The times for Play: today's engine's result is added to, so they're for the games after its 400.
        seen = []

        def estimate(entry_a, entry_b, games, p=0, results_dir=None, choices=()):
            seen.append(len(games))
            return {"assess": [1, 2]}

        def estimated():
            with mock.patch.object(self.forge, "estimate", types.SimpleNamespace(matchup=estimate), create=True),                     mock.patch.object(self.forge, "views", types.SimpleNamespace(
                        _games=lambda stored: [None] * stored["games"]), create=True):
                api.matchup(key=old)

        estimated()
        self.assertEqual(seen.pop(), 400)
        earlier = {"kind": "v1", "run_version": 1, "current": False, "words": "Played with Deck Lab's first engine."}
        self.forge.saved[old]["engine"] = earlier
        self.forge.FORGE_RUN_VERSION = 3
        # By the decks: today's engine hasn't played them, and the page can link to the earlier result.
        answer = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")
        self.assertNotEqual(answer["key"], old)
        self.assertEqual((answer["status"], answer["result"], answer["earlier"]), ("none", None, [old]))
        # By its key: shown as it is, labelled.
        by_key = api.matchup(key=old)
        self.assertEqual((by_key["status"], by_key["result"]["engine"], by_key["earlier"]), ("done", earlier, []))
        # Its Play starts a new result with today's engine, so its times are a new result's, from no games.
        estimated()
        self.assertEqual(seen, [0])
        self.assertEqual([item["engine"] for item in api.matchups()["results"]], [earlier])
        self.assertEqual([item["engine"] for item in api.deck_view(GRUUL_ID)["matchups"]["results"]], [earlier])
        # Playing more of the lists answers with today's key (the page follows it), and the earlier result stays.
        run = self.play(games=200)
        self.assertEqual(run["key"], answer["key"])
        self.finish()
        self.assertEqual(self.forge.saved[old]["games"], 400)
        self.assertEqual(api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["earlier"], [old])
        self.assertEqual(api.matchup(key=old)["earlier"], [])           # today's isn't an earlier engine's
        self.assertEqual([item["engine"]["current"] for item in api.matchups()["results"]], [True, False])

    def test_the_auto_profile_of_each_side(self):
        self.play(games=200)
        self.finish()
        key = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["key"]
        owned = self.sha(GRUUL_ID, "owned")
        for side in self.forge.saved[key]["sides"]:
            side["auto_profile"] = {"flag": side["card_sha"] == owned, "avg_cmc": 4 if side["card_sha"] == owned else 2}
        by_decks = api.matchup(GRUUL_ID, None, GRUUL_ID, "owned")["sides"]
        self.assertEqual([(s["version"], s["auto_profile"]) for s in by_decks], [("target", False), ("owned", True)])
        by_key = api.matchup(key=key)["sides"]
        self.assertEqual({(s["version"], s["auto_profile"]) for s in by_key}, {("target", False), ("owned", True)})
        listed = api.matchups()["results"][0]["sides"]
        self.assertEqual({(s["version"], s["auto_profile"]) for s in listed}, {("target", False), ("owned", True)})

    def test_a_run_waiting_or_playing_by_its_key(self):
        self.playing()
        key = self.play(games=400, a=GRUUL_ID, av="owned", b=GRUUL_ID, bv="target")["key"]
        self.assertTrue(self.forge.started.wait(WAIT))
        answer = api.matchup(key=key)
        self.assertEqual((answer["status"], [s["version"] for s in answer["sides"]]), ("running", ["owned", "target"]))
        self.assertIsNone(answer["result"])
        self.finish()

    def test_bad_keys(self):
        # Plain sentences, since the page shows them for a bad #/matchup?key= link (review finding PAGE-10).
        error = self.refused(404, api.matchup, key="0" * 64)
        self.assertEqual(error.message, "There's no saved matchup at that link.")
        for key in ("0" * 63, "A" * 64, "../" + "0" * 61, "", "0" * 65, "zzz"):
            with self.subTest(key=key):
                error = self.refused(400, api.matchup, key=key)
                self.assertEqual(error.message, "That link isn't a matchup's address.")
        self.assertApiError(400, api.matchup, GRUUL_ID, None, None, None, "0" * 64, contains="not both")


class ListTests(MatchupTestCase):

    def test_saved_results_and_runs_going(self):
        runner = mock.patch.object(api.forge_runs, "FORGE_JOBS", one_at_a_time())    # a run waits behind another
        runner.start()
        self.addCleanup(runner.stop)
        empty = api.matchups()
        self.assertEqual(empty, {"results": [], "running": [], "choices": [200, 400, 800, 1600, 3200],
                                 "default_games": 800, "workers": 16, "batch_games": 200,
                                 # the viewer's, as GET /api/decks gives it (E10-S30)
                                 "decks_revision": api.decks_index()["decks_revision"],
                                 "forge": {"ready": True, "version": "2.0.15",
                                                                 "problem": None}})
        self.play(games=200)
        self.finish()
        self.playing()
        self.play(a="pairing/cats+elves", av=None, b="pairing/cats+goblins", bv=None, profile="user1")
        self.assertTrue(self.forge.started.wait(WAIT))
        self.play(a=ELVES, av=None, b=PRECON, bv=None)
        held = self.forge.held
        listed = api.matchups()
        self.assertEqual(self.forge.held, held + 1)         # today's engine worked out once for the list
        self.assertEqual(len(listed["results"]), 1)
        item = listed["results"][0]
        self.assertEqual((item["games"], item["by"], item["format"]), (200, "Matt", "Constructed"))
        self.assertEqual(item["engine"], self.forge.TODAYS_ENGINE)
        self.assertEqual([s["current"] for s in item["sides"]], [True, True])
        running = listed["running"]
        self.assertEqual([r["status"] for r in running], ["running", "queued"])
        self.assertEqual(set(running[0]), {"key", "sides", "status", "ahead", "done", "total", "wins", "by",
                                       "waiting", "kind", "title", "link", "mode", "plan", "eta_s", "may_stop"})
        self.assertEqual((running[0]["by"], running[0]["done"], running[0]["total"]), ("User1", 200, 800))
        self.assertEqual([s["id"] for s in running[0]["sides"]], ["pairing/elves+cats", "pairing/cats+goblins"])
        self.assertEqual([s["kind"] for s in running[1]["sides"]], ["commander", "product"])
        self.assertEqual((running[1]["ahead"], running[1]["done"], running[1]["wins"]), (1, 0, [0, 0]))
        a_first = self.a_first(("pairing/cats+elves", "target"), ("pairing/cats+goblins", "target"))
        self.assertEqual(running[0]["wins"], self.split(200, a_first))
        json.dumps(listed, allow_nan=False)
        self.finish()
        self.assertEqual(len(api.matchups()["results"]), 3)

    def test_revision_is_explicitly_unavailable_without_affecting_lightweight_running_poll(self):
        with mock.patch.object(inventory, "current", side_effect=inventory.Unavailable("Fixture outage")):
            self.assertApiError(503, api.matchups, contains="database")
            self.assertEqual(set(api.matchups(running=True)), {"running", "forge"})

    def test_results_with_no_games_are_left_out(self):
        self.forge.error = self.forge.ForgeError("No games could be played: Forge stopped responding.")
        self.play()
        self.finish()
        self.assertEqual(api.matchups()["results"], [])

    def test_a_result_that_cant_be_shown_doesnt_hide_the_others(self):
        # Review finding API-5 (the api's part; forge/saved.py leaves out files that aren't results).
        self.play()
        self.finish()
        good = self.forge.results()
        with mock.patch.object(self.forge, "results", return_value=[{"key": "x" * 64}, *good]):
            listed = api.matchups()
        self.assertEqual([item["key"] for item in listed["results"]], [good[0]["key"]])
        self.assertTrue(any("A matchup result can't be listed" in line and "KeyError" in line
                            for line in self.box.logs))


class DeckViewTests(MatchupTestCase):

    def test_the_deck_page_has_its_matchups(self):
        view = api.deck_view(GRUUL_ID)
        self.assertEqual(view["matchups"], {
            "ai": {"cannot_play": [{"name": "Black Lotus", "qty": 1, "why": "script"}], "commander_unplayable": False,
                   "team_pump": None, "unknown": [], "problem": None, "games": 0},
            "results": [], "running": [], "forge": {"ready": True, "version": "2.0.15", "problem": None},
            "cards": None})
        self.play(a=GRUUL_ID, av="owned", b=GRUUL_ID, bv="target")
        self.finish()
        # The AI limits are judged by every saved game this list played (forge.list_ai).
        played = self.forge.runs[0][2]
        self.assertEqual(api.deck_view(GRUUL_ID)["matchups"]["ai"]["games"], played)
        self.playing()
        self.play(a="pairing/cats+elves", av=None, b=GRUUL_ID, bv="target")
        self.assertTrue(self.forge.started.wait(WAIT))
        matchups = api.deck_view(GRUUL_ID)["matchups"]
        sha = self.sha(GRUUL_ID)
        # This list first, in both.
        self.assertEqual([item["sides"][0]["card_sha"] for item in matchups["results"]], [sha])
        self.assertEqual(matchups["results"][0]["sides"][1]["version"], "owned")
        self.assertEqual(matchups["results"][0]["engine"], self.forge.TODAYS_ENGINE)
        self.assertEqual(matchups["results"][0]["sides"][0]["current"], True)
        self.assertEqual([item["sides"][0]["card_sha"] for item in matchups["running"]], [sha])
        self.assertEqual(matchups["running"][0]["sides"][1]["id"], "pairing/elves+cats")
        a_first = self.a_first((GRUUL_ID, "target"), ("pairing/cats+elves", "target"))
        self.assertEqual(matchups["running"][0]["wins"], self.split(200, a_first))
        # The owned-only list has its own; the other list's page doesn't show this run.
        owned = api.deck_view(GRUUL_ID, "owned")["matchups"]
        self.assertEqual(owned["results"][0]["sides"][0]["version"], "owned")
        self.assertEqual(owned["running"], [])
        self.finish()
        self.assertEqual(len(self.forge.runs), 2)       # the pages never started one

    def test_a_half_has_none_and_the_page_survives_without_forge(self):
        self.assertIsNone(api.deck_view("product/fdn-beginner-box/cats")["matchups"])
        self.assertIsNotNone(api.deck_view("pairing/cats+elves")["matchups"])
        with mock.patch.dict(sys.modules, {"decklab.lib.forge": None}):
            view = api.deck_view(GRUUL_ID)
        self.assertIsNone(view["matchups"])
        self.assertEqual(view["summary"]["id"], GRUUL_ID)
        self.forge.fail = RuntimeError("results folder unreadable")
        view = api.deck_view(GRUUL_ID)
        self.assertIsNone(view["matchups"])
        self.assertIsNotNone(view["stats"])
        self.assertTrue(any("matchups of casual/gruul-test can't be looked up" in line and "unreadable" in line
                            for line in self.box.logs))
        self.assertEqual(self.forge.runs, [])

    def test_the_deck_page_has_its_card_stats(self):
        # None until a game of this list has card data (forge.list_cards).
        self.forge.card_log = False
        self.play(a=GRUUL_ID, av="owned", b=GRUUL_ID, bv="target")
        self.finish()
        before = self.forge.runs[0][2]
        self.assertIsNone(api.deck_view(GRUUL_ID)["matchups"]["cards"])
        self.assertEqual(api.matchup(GRUUL_ID, "owned", GRUUL_ID, "target")["result"]["cards"], [None, None])
        # Then pooled over every saved result of the list: "from 800 of 1,600 games".
        self.forge.card_log = True
        self.play(a=GRUUL_ID, av="owned", b=GRUUL_ID, bv="target")
        self.finish()
        played = self.forge.runs[1][2]
        cards = api.deck_view(GRUUL_ID)["matchups"]["cards"]
        self.assertEqual({k: cards[k] for k in ("games", "old", "of", "matchups", "enough", "min_games", "min_split")},
                         {"games": played, "old": 0, "of": before + played, "matchups": 1, "enough": True,
                          "min_games": 100, "min_split": 30})
        self.assertEqual(api.deck_view(GRUUL_ID, "owned")["matchups"]["cards"]["games"], played)
        self.assertIsNone(api.deck_view(ELVES)["matchups"]["cards"])
        # The matchup page has each side's, in the page's order.
        answer = api.matchup(GRUUL_ID, "owned", GRUUL_ID, "target")
        self.assertEqual([c["for"] for c in answer["result"]["cards"]], [s["card_sha"] for s in answer["sides"]])
        self.assertEqual([(r["card_log"], r["card_log_problem"]) for r in answer["result"]["runs"]],
                         [(False, "The card log is off."), (True, None)])
        json.dumps([cards, answer], allow_nan=False)

    def test_card_stats_that_fail_leave_the_rest_of_the_part(self):
        self.play(a=GRUUL_ID, av="owned", b=GRUUL_ID, bv="target")
        self.finish()
        played = self.forge.runs[0][2]
        self.forge.cards_fail = KeyError("a shape nobody thought of")
        matchups = api.deck_view(GRUUL_ID)["matchups"]
        self.assertIsNone(matchups["cards"])
        self.assertEqual((len(matchups["results"]), matchups["ai"]["games"], matchups["forge"]["ready"]),
                         (1, played, True))
        self.assertTrue(any("card stats of casual/gruul-test can't be worked out" in line and "KeyError" in line
                            and "Traceback" in line for line in self.box.logs))
        # The matchup page doesn't use them.
        self.assertEqual(api.matchup(GRUUL_ID, "owned", GRUUL_ID, "target")["result"]["games"], played)

    def test_commander_decks_too(self):
        matchups = api.deck_view(ELVES)["matchups"]
        self.assertEqual(matchups["results"], [])
        self.play(a=ELVES, av=None, b=PRECON, bv=None)
        self.finish()
        self.assertEqual(len(api.deck_view(PRECON)["matchups"]["results"]), 1)


def deck_file(title, decklist):
    return (f"# {title}\n\n- **Format:** Casual 60-card, 1v1\n- **Played by:** either\n- **Status:** building\n\n"
            f"## Decklist\n\n```\n{decklist}```\n")


if __name__ == "__main__":
    unittest.main()
