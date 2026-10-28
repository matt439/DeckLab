"""Tests for the warm pool (decklab/lib/forge/pool.py, simulation wave 2's R05 and R01b) and
the v2 runs that play in it (runner._run_v2): game numbers in chunks of one shared queue,
the same games however they're chunked (as one-shot DeckLabSim v2 processes play them),
seat blocks and the stored flip, re-queues after a taint, a recycle or a dead worker
(at most pool.MAX_REQUEUE times), failing at once, Stop saving at once, the first-use gate,
the one-shot fallback when serve can't start, slots and pinning, idle and capped workers,
sessions (and the replay command in one), the pool service a command line run submits to (and the server going away), the
server's pool and its stop order, and config.json's pool settings.

No Java: the fake Forge's serve mode (fixtures/fake_forge.py) stands in for DeckLabSim's,
with the card log said to be ready (test_forge.CARD_LOG), as test_forge's setUpModule sets up.

Run from the repo root: python -m unittest decklab.tests.test_forge_pool
Service integration tests live in test_forge_pool_service.py; game-number, seed,
logging, pilot and override hooks live in test_forge_pool_hooks.py.
"""
import io
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from decklab.lib import api, config, decks, forge, jobs
from decklab.lib.forge import pool, runner, seeds, slots
from decklab.tests import test_forge
from decklab.tests.test_forge import CARD_LOG, GISA, GREEN, RED, entry, load_json, sections, stored, wait_dead
from decklab.tests.test_forge_slots import SlotFolder, wait_for


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


class PoolCase(SlotFolder, test_forge.ForgeCase):
    """ForgeCase with the card log said to be ready (so runs play the v2 engine in the warm
    pool), a budget of 4 slots in a folder of the test's own, and every process the pool
    starts noted (self.procs) and killed at the end."""

    def setUp(self):
        super().setUp()
        self.settings["forge_workers"] = 4
        self.use_own_slots()
        pool._said.clear()
        self.addCleanup(pool._said.clear)
        self.procs = []
        real_start = forge.processes.start_process

        def start(argv, cwd=None, env=None, stdin=False):
            proc = real_start(argv, cwd=cwd, env=env, stdin=stdin)
            self.procs.append(proc)
            self.addCleanup(forge.processes.kill_process, proc)
            return proc

        # The card log said to be ready to runs (card_log) and to the keys worked out without Java
        # (readiness, which engine.matchup_key's kind follows), so self.saved() finds the v2 result.
        for p in (mock.patch.object(forge.simjar, "card_log", side_effect=lambda *a, **k: dict(CARD_LOG)),
                  mock.patch.object(forge.simjar, "readiness", return_value={"ready": True, "problem": None}),
                  mock.patch.object(forge.processes, "start_process", start)):
            p.start()
            self.addCleanup(p.stop)

    def run_matchup(self, games=200, a=GREEN, b=RED, **kwargs):
        kwargs.setdefault("results_dir", self.results)
        kwargs.setdefault("workers", 4)
        return forge.run(entry(a, "casual/green"), entry(b, "casual/red"), games, by="Matt", **kwargs)

    def saved(self):
        return forge.load(forge.matchup_key(entry(GREEN), entry(RED)), self.results)

    def all_dead(self):
        return all(wait_dead(proc.pid) for proc in self.procs)

    def requests(self):
        """Patch runner.request_line to note every request a worker is sent: [(first, games, deck 1)]."""
        sent = []
        real = runner.request_line

        def request_line(request_id, args):
            first = int(args[args.index("-dlgame") + 2])
            sent.append((first, int(args[args.index("-n") + 1]), args[args.index("-d") + 1]))
            return real(request_id, args)

        p = mock.patch.object(runner, "request_line", request_line)
        p.start()
        self.addCleanup(p.stop)
        return sent

    def setup_(self, **extra):
        """install._setup() with the card log, as a run has it."""
        setup = forge.install._setup()
        setup["card_log"] = dict(CARD_LOG)
        setup.update(extra)
        return setup

    def job(self, games=50, setup=None, low=False, batch=None, workers=4, flip=0, key="f" * 64, a=GREEN, b=RED):
        """A job as runner._run_v2 builds it, for a Pool of the test's own."""
        setup = setup or self.setup_()
        ordered = sorted([entry(a, "casual/green"), entry(b, "casual/red")], key=lambda e: e["card_sha"])
        runner._write_decks(setup["decks_dir"], ordered)
        index = forge.install.script_index()
        names = [forge.install._log_names([n for _, n in forge.lists._list_lines(e)], index) for e in ordered]
        stream = seeds.stream_hex(seeds.stream_of(ordered[0]["card_sha"], ordered[1]["card_sha"]))
        return {"key": key, "setup": setup, "fmt": "Constructed", "dck": [f"{e['card_sha']}.dck" for e in ordered],
                "names": names, "base": 1, "stream": stream, "flip": flip,
                "ranges": forge.lists.plan_v2(games, exact=True)["ranges"], "batch": batch, "workers": workers,
                "low": low, "engine": forge.engine.current(setup, setup["card_log"])}

    def pool_(self, **kwargs):
        kwargs.setdefault("name", "test")
        kwargs.setdefault("idle_s", 30)
        own = pool.Pool(None, **kwargs)
        self.addCleanup(own.close, 0)
        return own

    def drain(self, ticket, seconds=30):
        """Every event of ticket until its "done" (or seconds pass)."""
        events, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                event = ticket.events.get(timeout=0.1)
            except Exception:
                continue
            events.append(event)
            if event[0] == "done":
                return events
        self.fail(f"the ticket never ended: {events[-5:]}")

    def oneshot(self, first, games, flip=0, base=1):
        """Games [first, first + games) of one block as a one-shot DeckLabSim v2 process plays them
        (the fake's sim -dlgame): [game dicts with "g"]."""
        setup = self.setup_()
        ordered = sorted([entry(GREEN, "casual/green"), entry(RED, "casual/red")], key=lambda e: e["card_sha"])
        runner._write_decks(setup["decks_dir"], ordered)
        deck1 = seeds.deck1_side(first, flip)
        dck = [f"{e['card_sha']}.dck" for e in ordered]
        stream = seeds.stream_hex(seeds.stream_of(ordered[0]["card_sha"], ordered[1]["card_sha"]))
        argv = runner.build_command(setup, "Constructed", dck[deck1], dck[1 - deck1], games, base,
                                    v2={"stream": stream, "first": first})
        out = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=60,
                             env=dict(os.environ, APPDATA=str(setup["user_dir"]))).stdout
        index = forge.install.script_index()
        names = [forge.install._log_names([n for _, n in forge.lists._list_lines(e)], index) for e in ordered]
        reader = forge.LogReader(deck1, names, card_log=True)
        for line in out.splitlines():
            reader.feed(line)
        return [dict(game, g=first + i) for i, game in enumerate(reader.games)]


# ============================================================ v2 runs

class RunTests(PoolCase):

    def test_a_run_plays_its_game_numbers_in_chunks_and_saves_one_batch(self):
        calls = []
        result = self.run_matchup(200, progress=lambda done, total, detail: calls.append((done, total, dict(detail))))
        self.assertTrue(forge.saved._is_result(load_json(self.results / f"{result['key']}.json"), result["key"]))
        [batch] = result["batches"]
        self.assertEqual((batch["n"], batch["first"]), (0, 0))
        self.assertEqual([g["g"] for g in batch["games"]], list(range(200)))
        self.assertNotIn("seed", batch)
        self.assertNotIn("deck1", batch)
        self.assertEqual(batch["cards"]["games"] + batch["cards"]["bad"], 200)
        self.assertEqual(sum(n for n, _ in batch["casts"][0].values()) > 0, True)
        green, red = entry(GREEN)["card_sha"], entry(RED)["card_sha"]
        self.assertEqual(result["seeds"], {"scheme": seeds.SCHEME, "base": 1, "stream": seeds.stream_hex(
            seeds.stream_of(green, red)), "seat_block": 25, "flip": 0})
        self.assertEqual(result["next_game"], 200)
        self.assertEqual(result["settings"], {"clock_s": 120, "ai": ["Default", "Default"], "xmx": "1024m"})
        run = result["runs"][0]
        self.assertEqual((run["asked"], run["played"], run["pool"], run["games_from"], run["games_to"],
                          run["seeds"], run["card_log"], run["engine"], run["failed"], run["error"], run["stopped"],
                          run["recycled"], run["requeued"], run["xmx"]),
                         (200, 200, "local", 0, 200, [0, 199], True, result["key"], 0, None, False, 0, 0, "1024m"))
        self.assertEqual((run["chunks"], run["batches"], run["played_batches"]),
                         (batch["chunks"], batch["chunks"], batch["chunks"]))
        self.assertLessEqual(run["batch_games"], pool.CHUNK_MAX)
        self.assertEqual(run["workers"], run["most_running"])
        self.assertTrue(1 <= run["workers"] <= 4)
        # progress: first and last, a sensible detail.
        self.assertEqual((calls[0][:2], calls[-1][:2]), ((0, 200), (200, 200)))
        detail = calls[-1][2]
        self.assertEqual(sum(detail["wins"]) + detail["other"], 200)
        self.assertEqual((detail["failed_batches"], detail["waiting"], detail["fallback"]), (0, None, None))
        # The run's own pool closed when it ended: its workers are gone, and no slot is held.
        self.assertTrue(self.all_dead())
        self.assertFalse(any(row["held"] for row in slots.status(4)["slots"]))
        # A view reads it as any result.
        v = forge.view(result, green)
        self.assertEqual(v["games"], 200)
        self.assertEqual(v["runs"][0]["pool"], "local")

    def test_the_games_are_one_shot_v2_games_however_they_are_chunked(self):
        sent = self.requests()
        result = self.run_matchup(100, batch=5)
        self.assertTrue(all(n <= 5 for _, n, _ in sent))
        again = self.run_matchup(100, exact=True, results_dir=self.tmp / "again")

        def games(result_):
            return [{k: v for k, v in g.items() if k != "ms"} for g in result_["batches"][0]["games"]]

        self.assertEqual(games(again), games(result))
        # And as one-shot DeckLabSim v2 processes play them, block by block.
        reference = [g for first in range(0, 100, 25) for g in self.oneshot(first, 25)]
        self.assertEqual([{k: v for k, v in g.items() if k != "ms"} for g in reference], games(result))
        self.assertEqual(result["batches"][0]["cards"]["games"], 100)

    def test_more_games_go_on_from_next_game(self):
        first = self.run_matchup(200)
        more = self.run_matchup(200)
        self.assertEqual([(b["n"], b["first"], len(b["games"])) for b in more["batches"]], [(0, 0, 200), (1, 200, 200)])
        self.assertEqual(more["next_game"], 400)
        self.assertEqual([(r["games_from"], r["games_to"]) for r in more["runs"]], [(0, 200), (200, 400)])
        self.assertEqual(forge.view(more, first["sides"][0]["card_sha"])["games"], 400)
        self.assertEqual(more["seeds"], first["seeds"])

    def test_seat_blocks_alternate_and_a_first_sets_a_new_results_flip(self):
        sent = self.requests()
        a, b = entry(GREEN, "casual/green"), entry(RED, "casual/red")
        ordered = sorted([a, b], key=lambda e: e["card_sha"])
        result = forge.run(b, a, 100, by="x", results_dir=self.results, a_first=True, batch=10)
        flip = int(ordered[0]["card_sha"] != b["card_sha"])
        self.assertEqual(result["seeds"]["flip"], flip)
        dck = [f"{e['card_sha']}.dck" for e in ordered]
        for first, games, deck1 in sent:
            self.assertEqual(seeds.block_of(first), seeds.block_of(first + games - 1))     # never two blocks
            self.assertEqual(deck1, dck[seeds.deck1_side(first, flip)])
        self.assertEqual({deck1 for first, _, deck1 in sent if first < 25}, {f"{b['card_sha']}.dck"})
        self.assertEqual({deck1 for first, _, deck1 in sent if 25 <= first < 50}, {f"{a['card_sha']}.dck"})

    def test_a_first_on_an_existing_result_is_said_and_left_as_it_was(self):
        small, large = sorted([entry(GREEN, "casual/green"), entry(RED, "casual/red")], key=lambda e: e["card_sha"])
        forge.run(small, large, 200, by="x", results_dir=self.results)          # flip 0: side 0 first
        logged = []
        with mock.patch.object(forge.common, "_log", logged.append):
            flipped = forge.run(large, small, 200, by="x", results_dir=self.results, a_first=True)
            same = forge.run(small, large, 200, by="x", results_dir=self.results, a_first=True)
        self.assertEqual(logged, [runner.A_FIRST_IGNORED])      # said for the one that would flip it
        self.assertEqual((flipped["seeds"]["flip"], same["seeds"]["flip"]), (0, 0))

    def test_a_seed_base_starts_a_new_result_and_must_be_0_or_more(self):
        result = self.run_matchup(200, seed_base=7)
        self.assertEqual(result["seeds"]["base"], 7)
        more = self.run_matchup(200, seed_base=9)            # the result's own stays
        self.assertEqual(more["seeds"]["base"], 7)
        with self.assertRaises(ValueError):
            self.run_matchup(200, seed_base=-1, results_dir=self.tmp / "negative")
        other = self.run_matchup(200, results_dir=self.tmp / "default")
        self.assertNotEqual([g["w"] for g in other["batches"][0]["games"]],
                            [g["w"] for g in result["batches"][0]["games"]])

    def test_exact_plays_any_number_of_games(self):
        result = self.run_matchup(37, exact=True)
        self.assertEqual([g["g"] for g in result["batches"][0]["games"]], list(range(37)))
        with self.assertRaises(ValueError):
            self.run_matchup(37)
        with self.assertRaises(ValueError):
            self.run_matchup(0, exact=True)
        more = self.run_matchup(3, exact=True)
        self.assertEqual((more["next_game"], more["batches"][1]["first"]), (40, 37))

    def test_progress_comes_after_games_and_at_least_once_a_second(self):
        self.fake("delay=0.01")
        calls = []
        self.run_matchup(200, progress=lambda done, total, detail: calls.append((time.monotonic(), done)))
        gaps = [later[0] - earlier[0] for earlier, later in zip(calls, calls[1:])]
        self.assertTrue(all(gap >= runner.PROGRESS_GAP - 0.01 for gap in gaps[:-1]), gaps)
        self.assertLess(max(gaps), runner.HEARTBEAT + 0.5, gaps)
        self.assertGreater(len({done for _, done in calls}), 3)        # live: not once a chunk
        self.assertEqual(calls[-1][1], 200)

    def test_a_commander_mirror(self):
        a = entry(GISA, "commander/gisa", "commander")
        result = forge.run(a, a, 200, by="Matt", results_dir=self.results)
        self.assertEqual((result["format"], forge.view(result, a["card_sha"])["games"]), ("Commander", 200))

    def test_a_plain_result_isnt_added_to_by_the_v2_engine(self):
        with mock.patch.object(forge.simjar, "card_log", return_value={"ready": False, "problem": "Off."}):
            plain = self.run_matchup(200)
        # The engine id keys the two kinds apart: the v2 run starts a result of its own.
        v2 = self.run_matchup(200)
        self.assertNotEqual(v2["key"], plain["key"])
        self.assertEqual((plain["engine"]["kind"], v2["engine"]["kind"]), ("plain", "decklab"))
        self.assertEqual(forge.load(plain["key"], self.results)["runs"], plain["runs"])
        # Should two engines' keys ever meet, the run still refuses to mix them.
        with mock.patch.object(forge.engine, "key", return_value=plain["key"]), \
                mock.patch.object(forge.common, "_log"), self.assertRaises(forge.ForgeError) as caught:
            self.run_matchup(200)
        self.assertEqual(str(caught.exception), runner.OTHER_ENGINE)


# ============================================================ re-queues, recycling and failing

class RecycleTests(PoolCase):

    def test_a_game_with_an_ai_timeout_python_sees_kills_its_worker(self):
        clean = self.run_matchup(100, exact=True, results_dir=self.tmp / "clean")
        # Java doesn't see it (as when Deck Lab's AiController copy doesn't fit): Python's taint.
        self.fake("aitimeoutunseen#7")
        sent = self.requests()
        result = self.run_matchup(100, batch=10)
        games = result["batches"][0]["games"]
        self.assertEqual([g["g"] for g in games], list(range(100)))
        self.assertEqual(games[7]["ai_to"], 2)                  # the tainted game counts
        run = result["runs"][0]
        self.assertEqual((run["recycled"], run["requeued"], run["partial"]), (1, 2, 1))
        self.assertEqual([(f, n) for f, n, _ in sent if f == 8], [(8, 2)])       # 8-9 went back
        # The same games as without the AI timeout lines (apart from them).
        strip = lambda r: [{k: v for k, v in g.items() if k not in ("ms", "ai_to")}  # noqa: E731
                           for g in r["batches"][0]["games"]]
        self.assertEqual(strip(result), strip(clean))
        self.assertTrue(self.all_dead())

    def test_java_recycles_after_a_clock_stop_an_ai_timeout_or_a_crash(self):
        self.fake("timeout#3;aitimeout#30;exception#60")
        result = self.run_matchup(100, batch=10)
        v = forge.view(result, result["sides"][0]["card_sha"])
        self.assertEqual((v["games"], v["timeouts"], v["errors"], v["ai_timeouts"]), (100, 1, 1, 2))
        self.assertEqual([g["g"] for g in result["batches"][0]["games"]], list(range(100)))
        self.assertEqual(result["runs"][0]["recycled"], 3)
        self.assertEqual(result["failed"], [])

    def test_a_game_that_keeps_killing_its_worker_fails_after_two_requeues(self):
        self.fake("crash#40")
        sent = self.requests()
        result = self.run_matchup(100, batch=5)
        self.assertEqual(sum(1 for first, n, _ in sent if first <= 40 < first + n), pool.MAX_REQUEUE + 1)
        self.assertEqual(result["failed"], [{"n": 0, "first": 40, "games": 5, "error": pool.PART_WAY}])
        self.assertEqual([g["g"] for g in result["batches"][0]["games"]], [g for g in range(100) if not 40 <= g < 45])
        run = result["runs"][0]
        self.assertEqual((run["played"], run["failed"], run["failure"], run["requeued"]), (95, 1, pool.PART_WAY, 10))
        self.assertTrue(list((forge.common.DATA_DIR / "logs").glob("*-g40.log")))

    def test_the_watchdog_kills_a_worker_that_stops_printing(self):
        self.settings["forge_clock_s"] = 1
        self.fake("hang#5")
        with mock.patch.object(runner, "GAME_GRACE", 0.5):
            started = time.monotonic()
            result = self.run_matchup(20, batch=10, exact=True)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(result["failed"], [{"n": 0, "first": 5, "games": 5, "error": pool.NOT_RESPONDING}])
        self.assertEqual(result["runs"][0]["played"], 15)
        self.assertTrue(self.all_dead())


class FailTests(PoolCase):

    def test_a_java_error_fails_the_run_at_once(self):
        self.fake("throw#40")
        sent = self.requests()
        with mock.patch.object(forge.common, "_log"):
            result = self.run_matchup(200, batch=5, workers=1)
        self.assertEqual(result["failed"], [{"n": 0, "first": 40, "games": 5, "error": pool.FORGE_ERROR}])
        self.assertEqual(max(first for first, _, _ in sent), 40)       # nothing after it was asked for
        run = result["runs"][0]
        self.assertEqual((run["played"], run["failure"], run["error"]), (40, pool.FORGE_ERROR, None))
        self.assertEqual(result["next_game"], 200)      # the numbers it didn't play aren't played later

    def test_arguments_that_cant_be_read_fail_the_run_at_once(self):
        self.fake("badargs")
        with mock.patch.object(forge.common, "_log"), self.assertRaises(forge.ForgeError) as caught:
            self.run_matchup(200)
        self.assertEqual(str(caught.exception), f"No games could be played: {pool.FORGE_ERROR}.")
        self.assertEqual(self.saved()["runs"][0]["error"], pool.FORGE_ERROR)

    def test_unknown_cards_and_decks_fail_at_once(self):
        for mode, why in (("unsupported", "Forge doesn't know these cards: Totally Fake Card"),
                          ("noload", "Forge couldn't load one of the decks")):
            with self.subTest(mode=mode):
                self.fake(mode)
                with mock.patch.object(forge.common, "_log"), self.assertRaises(forge.ForgeError) as caught:
                    self.run_matchup(200, results_dir=self.tmp / mode)
                self.assertEqual(str(caught.exception), f"No games could be played: {why}.")

    def test_a_chunk_played_with_another_engine_fails_at_once(self):
        # (check_echo's sentences end with a full stop; the run's message has one.)
        with mock.patch.object(forge.engine, "check_echo", return_value="It was played with game patches off."), \
                self.assertRaises(forge.ForgeError) as caught:
            self.run_matchup(200)
        self.assertEqual(str(caught.exception), "No games could be played: It was played with game patches off.")
        self.assertEqual(self.saved()["batches"], [])

    def test_a_worker_that_cant_be_started(self):
        def start(argv, cwd=None, env=None, stdin=False):
            raise FileNotFoundError(2, "The system cannot find the file specified", "C:\\nowhere\\java.exe")

        with mock.patch.object(forge.processes, "start_process", start), mock.patch.object(forge.common, "_log"), \
                self.assertRaises(forge.ForgeError) as caught:
            self.run_matchup(200)
        self.assertEqual(str(caught.exception), "No games could be played: Forge couldn't be started (the system "
                                                "cannot find the file specified).")


# ============================================================ stopping

class StopTests(PoolCase):

    def test_stop_saves_at_once_while_games_are_playing(self):
        self.fake("delay=3")                # every game takes 3 seconds
        stopped_at = []

        def progress(done, total, detail):
            if done >= 2:
                stopped_at.append(time.monotonic())
                stop = jobs.Stopped("Stopped by User1")
                stop.by = "User1"
                raise stop

        with self.assertRaises(jobs.Stopped) as caught:
            self.run_matchup(20, batch=5, workers=2, progress=progress)
        self.assertLess(time.monotonic() - stopped_at[0], 2)        # saved without waiting for the workers
        self.assertEqual(caught.exception.saved_games, 2)
        saved = self.saved()
        run = saved["runs"][0]
        self.assertEqual((run["played"], run["stopped"], run["stopped_by"], run["partial"], run["error"]),
                         (2, True, "User1", 2, None))
        self.assertEqual(sorted(g["g"] for g in saved["batches"][0]["games"]), [0, 5])
        self.assertEqual(saved["next_game"], 20)
        self.assertTrue(self.all_dead())
        self.assertFalse(any(row["held"] for row in slots.status(4)["slots"]))

    def test_ctrl_c_stops_and_saves(self):
        self.fake("hang#20")

        def progress(done, total, detail):
            if done >= 15:
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self.run_matchup(40, batch=10, workers=2, progress=progress)
        run = self.saved()["runs"][0]
        self.assertTrue(run["stopped"])
        self.assertGreaterEqual(run["played"], 15)
        self.assertTrue(self.all_dead())

    def test_an_error_while_playing_isnt_a_stop(self):
        self.fake("hang#20")

        def progress(done, total, detail):
            if done >= 15:
                raise TypeError("a bug")

        with self.assertRaises(TypeError):
            self.run_matchup(40, batch=10, workers=2, progress=progress)
        run = self.saved()["runs"][0]
        self.assertEqual((run["stopped"], run["error"]),
                         (False, "The run stopped because of an error in Deck Lab (TypeError)."))

    def test_a_stop_while_every_slot_is_taken(self):
        self.hold(4, 4)
        details = []

        def progress(done, total, detail):
            details.append(detail)
            if detail["waiting"]:
                raise jobs.Stopped("stop")

        with self.assertRaises(jobs.Stopped):
            self.run_matchup(200, progress=progress)
        self.assertEqual(details[-1]["waiting"], slots.WAITING)
        self.assertEqual(self.procs, [])
        run = self.saved()["runs"][0]
        self.assertEqual((run["played"], run["stopped"], run["chunks"]), (0, True, 0))


# ============================================================ starting workers

class StartTests(PoolCase):

    def test_the_first_use_of_the_user_folder_starts_one_worker_alone(self):
        self.fake("slowstart=0.6")
        started = []
        real_start = forge.processes.start_process

        def start(argv, cwd=None, env=None, stdin=False):
            started.append(time.monotonic())
            return real_start(argv, cwd=cwd, env=env, stdin=stdin)

        with mock.patch.object(forge.processes, "start_process", start):
            self.run_matchup(200)
            self.assertEqual(len(started), 4)
            self.assertGreaterEqual(started[1] - started[0], 0.5)   # the rest waited for the first's ready
            self.assertTrue(forge.runner._first_use_marker(forge.common.DATA_DIR / "user", "2.0.15").exists())
            del started[:]
            self.run_matchup(200, results_dir=self.tmp / "second")
        self.assertLess(started[-1] - started[0], 0.5)              # then all together

    def test_serve_that_cant_start_falls_back_to_one_shot_processes(self):
        self.fake("servefail")
        details = []
        with mock.patch.object(forge.common, "_log") as log:
            result = self.run_matchup(100, batch=25, progress=lambda done, total, detail: details.append(detail))
        sentence = pool.FALLBACK.format(why=pool.FALLBACK_FAILED)
        self.assertEqual(result["runs"][0]["fallback"], sentence)
        self.assertEqual(details[-1]["fallback"], sentence)
        self.assertEqual([c.args[0] for c in log.call_args_list].count(sentence), 1)       # said once
        self.assertEqual([g["g"] for g in result["batches"][0]["games"]], list(range(100)))
        # The same games as warm workers play.
        self.fake("")
        warm = self.run_matchup(100, batch=25, results_dir=self.tmp / "warm")
        self.assertNotIn("fallback", warm["runs"][0])               # the next run tries serve again
        self.assertEqual([g["w"] for g in warm["batches"][0]["games"]], [g["w"] for g in result["batches"][0]["games"]])

    def test_two_workers_dying_before_they_are_ready_fall_back(self):
        quick_exit = [sys.executable, "-c", "raise SystemExit(2)"]
        with mock.patch.object(runner, "serve_command", lambda setup: quick_exit), \
                mock.patch.object(forge.common, "_log"):
            result = self.run_matchup(50, exact=True)
        self.assertEqual(result["runs"][0]["fallback"], pool.FALLBACK.format(why=pool.FALLBACK_DIED))
        self.assertEqual(result["runs"][0]["played"], 50)

    def test_a_worker_not_ready_in_time_falls_back(self):
        sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
        with mock.patch.object(runner, "serve_command", lambda setup: sleeper), \
                mock.patch.object(runner, "HEADER_TIMEOUT", 1), mock.patch.object(forge.common, "_log"):
            result = self.run_matchup(50, exact=True)
        self.assertEqual(result["runs"][0]["fallback"], pool.FALLBACK.format(why=pool.FALLBACK_SLOW.format(seconds=1)))
        self.assertEqual(result["runs"][0]["played"], 50)
        self.assertTrue(self.all_dead())

    def test_a_one_shot_processs_slow_start_isnt_counted_against_its_first_game(self):
        # The first game's clock (1 s, plus a grace of 1 s here) starts at the header line, so
        # a cold process that takes 2 s to get there isn't killed as not responding; and its
        # start-up is the run's.
        self.settings["forge_clock_s"] = 1
        self.fake("slowstart=2;delay=0.8")
        cant_serve = [sys.executable, "-c", "raise SystemExit(3)"]
        with mock.patch.object(runner, "serve_command", lambda setup: cant_serve), \
                mock.patch.object(runner, "GAME_GRACE", 1.0), mock.patch.object(forge.common, "_log"):
            result = self.run_matchup(3, workers=1, exact=True)
        run = result["runs"][0]
        self.assertEqual(run["fallback"], pool.FALLBACK.format(why=pool.FALLBACK_FAILED))
        self.assertEqual((run["played"], run["failed"], run["requeued"]), (3, 0, 0))
        self.assertGreaterEqual(run["startup_s"], 2)
        self.assertTrue(self.all_dead())

    def test_a_worker_holds_a_slot_only_while_it_computes_and_is_pinned_to_its_core(self):
        self.fake("delay=0.02")
        pinned, held = [], []
        with mock.patch.object(forge.cores, "pin", side_effect=lambda pid, slot: pinned.append((pid, slot)) or True):
            own = self.pool_(idle_s=60)
            ticket = own.submit(self.job(100))
            while ticket.events.get(timeout=30)[0] != "done":
                held.append(self.held_by(4, "warm worker (test pool)"))
            status = own.status()
        self.assertTrue(1 <= max(held) <= 4)
        self.assertEqual(status["idle"], 4)
        self.assertTrue(all(w["slot"] is None for w in status["workers"]))
        self.assertEqual(self.held_by(4, "warm worker"), 0)          # idle warm workers hold none
        pids = {proc.pid for proc in self.procs}
        self.assertEqual({pid for pid, _ in pinned}, pids)
        self.assertTrue({slot for _, slot in pinned} <= {0, 1, 2, 3})
        # status() briefly locks free slots; this observer can make a worker take another.
        # The deterministic claim test below checks reuse when the preferred slot is free.

    def test_a_worker_prefers_its_last_slot_but_can_use_another_when_busy(self):
        # Exercise the pool's allocator boundary without workers or a polling observer.
        own = SimpleNamespace(budget=4, _what="fixture claim", _holding=lambda: False)
        worker = SimpleNamespace(lease=None, last_slot=2)
        with pool.Pool._claim(own, worker) as preferred:
            self.assertEqual(preferred.ids, [2])
            with pool.Pool._claim(own, worker) as fallback:
                self.assertEqual(fallback.ids, [0])
        with pool.Pool._claim(own, worker) as preferred_again:
            self.assertEqual(preferred_again.ids, [2])

    def test_pinning_is_off_with_forge_pin_false(self):
        if len(forge.cores.core_masks()) < 4:
            self.skipTest("this PC has no core of its own for each of the 4 workers")
        own = self.pool_()
        self.drain(own.submit(self.job(40)))
        self.assertTrue(all(w["pinned"] for w in own.status()["workers"]))
        self.settings["forge_pin"] = False
        own = self.pool_()
        self.drain(own.submit(self.job(40)))
        self.assertFalse(any(w["pinned"] for w in own.status()["workers"]))


# ============================================================ the pool itself

class PoolTests(PoolCase):

    def order(self, own, *jobs_):
        """Submit jobs_ (name, job) to own at once: the order their chunks start in, by name."""
        order, lock = [], threading.Lock()
        with own._lock:                         # queued together, before the pool looks
            tickets = [(name, own.submit(job)) for name, job in jobs_]

        def watch(name, ticket):
            while True:
                event = ticket.events.get(timeout=60)
                if event[0] == "start":
                    with lock:
                        order.append(name)
                if event[0] == "done":
                    return

        threads = [threading.Thread(target=watch, args=pair) for pair in tickets]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        return order

    def settled_tries(self, own, what):
        """Make every try for a slot by claims whose what is what (slots._take) wait until own has
        looked for slots (its loop's _dispatch) since it last freed one (_release), and make it
        holding own's lock, so own neither frees nor takes a slot during it. So a try never
        lands in the moment between own freeing a slot at a chunk's end and taking it back for
        its next chunk. (A claim polling every slots.POLL_S landed there often enough that the
        tests below passed about half the time with the handoff off, pool.HANDOFF_S 0.) Now,
        with the handoff off, a try finds every slot own freed taken back while own has games
        queued; with it on, a try finds the slot own left it. A try still unsettled after 10 s is made
        anyway, so the claim isn't stuck, but the test then fails: that try could have landed in the
        moment this rules out."""
        counts = {"freed": 0, "looked": 0, "unsettled": 0}   # slots own freed; how many looked since; late tries
        changed = threading.Condition()
        real_release, real_dispatch, real_take = own._release, own._dispatch, slots._take

        def release(worker):
            held = bool(worker.lease)
            real_release(worker)
            if held:
                with changed:
                    counts["freed"] += 1

        def dispatch(now):
            with changed:
                freed = counts["freed"]
            real_dispatch(now)
            with changed:
                counts["looked"] = freed
                changed.notify_all()

        def settled():
            return counts["looked"] == counts["freed"]

        def take(where, budget, n, asked, prefer=None):
            if asked != what:
                return real_take(where, budget, n, asked, prefer)
            end = time.monotonic() + 10            # (own's loop looks every pool.TICK_S at the latest)
            while True:
                with own._lock:                     # (own's releases and dispatches run under it)
                    with changed:
                        ready = settled()
                    if ready or time.monotonic() >= end:
                        if not ready:
                            with changed:
                                counts["unsettled"] += 1
                        return real_take(where, budget, n, asked, prefer)
                with changed:
                    changed.wait_for(settled, max(0.0, end - time.monotonic()))

        for p in (mock.patch.object(own, "_release", release), mock.patch.object(own, "_dispatch", dispatch),
                  mock.patch.object(slots, "_take", take)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: self.assertEqual(counts["unsettled"], 0, "tries made before own had looked"))

    def test_the_oldest_run_first_and_replay_runs_only_when_no_other_waits(self):
        own = self.pool_(workers=1)
        self.assertEqual(self.order(own, ("first", self.job(20, batch=5, key="a" * 64)),
                                    ("second", self.job(20, batch=5, key="b" * 64))),
                         ["first"] * 4 + ["second"] * 4)
        self.assertEqual(self.order(own, ("replay", self.job(20, low=True, batch=5, key="c" * 64)),
                                    ("page", self.job(20, batch=5, key="d" * 64))),
                         ["page"] * 4 + ["replay"] * 4)

    def test_a_runs_workers_cap_its_chunks_playing_at_once(self):
        self.fake("delay=0.05")
        own = self.pool_(workers=4)
        ticket = own.submit(self.job(40, batch=5, workers=2))
        most = 0
        while ticket.events.get(timeout=30)[0] != "done":
            most = max(most, own.status()["busy"])
        self.assertEqual(most, 2)

    def test_a_runs_own_pool_has_the_runs_workers(self):
        for asked, limit in ((1, 1), (2, 2), (99, 4)):          # (up to the budget, forge_workers 4)
            own = pool._own_pool(self.job(10, workers=asked))
            self.addCleanup(own.close, 0)
            self.assertEqual(own.limit, limit)
        # So a run of 1 worker gets 25-game chunks, not ones cut for forge_workers (ceil(100 / 8)).
        sent = self.requests()
        self.run_matchup(100, workers=1, exact=True)
        self.assertEqual(sent[0][1], 25)

    def test_chunk_sizes_follow_the_queue(self):
        own = self.pool_(workers=4)
        ticket = pool.Ticket(own, self.job(200), 1)
        sizes = []
        queued = 200
        while ticket.queued:
            chunk = own._cut(ticket, queued)
            sizes.append((chunk.first, chunk.games))
            queued -= chunk.games
        self.assertEqual(sizes[0], (0, 25))
        self.assertTrue(all(seeds.block_of(f) == seeds.block_of(f + n - 1) for f, n in sizes))
        self.assertEqual(sum(n for _, n in sizes), 200)
        self.assertEqual(sizes[-1][1], 5)                       # CHUNK_MIN at the tail
        capped = pool.Ticket(own, self.job(20, batch=3), 2)
        self.assertEqual(own._cut(capped, 1000).games, 3)        # the run's batch caps it
        rest = pool.Ticket(own, self.job(28), 3)
        rest.queued[0] = [22, 25]
        self.assertEqual(own._cut(rest, 1000).games, 3)          # the block's rest

    def test_idle_workers_quit_after_idle_s(self):
        own = self.pool_(idle_s=0.5)
        self.drain(own.submit(self.job(40)))
        self.assertTrue(wait_for(lambda: not own.status()["workers"], 10))
        self.assertTrue(self.all_dead())
        self.drain(own.submit(self.job(20)))                    # the pool stays: new workers start
        self.assertGreater(len(self.procs), 4)

    def test_a_new_launch_retires_idle_workers_of_the_old_one(self):
        own = self.pool_(workers=2)
        self.drain(own.submit(self.job(40)))
        old = [proc.pid for proc in self.procs]
        # A new card-log jar with a game patch built in (engine.check_echo fails a game-patches-off chunk, so
        # that's no longer a launch a run can play).
        newer = self.setup_(card_log=dict(CARD_LOG, game_patches=["attack-requirements-in-order-1"]))
        events = self.drain(own.submit(self.job(40, setup=newer)))
        self.assertEqual(len([e for e in events if e[0] == "game"]), 40)
        self.assertTrue(all(wait_dead(pid) for pid in old))
        new = [proc for proc in self.procs if proc.pid not in old]
        self.assertTrue(new)
        self.assertTrue(all("--game-patch-ids=attack-requirements-in-order-1" in proc.args for proc in new))

    def test_the_live_jvm_cap_quits_idle_workers_beside_other_runs_slots(self):
        own = self.pool_(workers=4)
        self.drain(own.submit(self.job(100)))
        self.assertEqual(own.status()["idle"], 4)
        self.hold(3, 4)                                         # another run computes in 3 slots
        with own._lock:
            own._cap_at = 0.0
            own._wake.notify_all()
        self.assertTrue(wait_for(lambda: len(own.status()["workers"]) == 1, 10))

    def test_a_slot_freed_while_another_process_waits_is_left_to_it(self):
        # A worker frees its slot at each chunk's end; taking it back at once, the pool kept every slot until
        # its queue was empty, so a claim polling every slots.POLL_S (cardlog-check, serve-check) waited for all
        # of it. Now the waiter has one at a chunk's end, and the pool takes every slot again once it's gone.
        # (Its tries are made only once the pool has looked for slots after freeing one: settled_tries.)
        self.fake("delay=0.05")
        own = self.pool_(workers=4)
        self.settled_tries(own, "a check")
        ticket = own.submit(self.job(400, batch=10))
        self.assertTrue(wait_for(lambda: self.held_by(4, "warm worker (test pool)") == 4, 20))
        stop = threading.Event()
        timer = threading.Timer(30, stop.set)
        timer.start()
        self.addCleanup(timer.cancel)
        lease = slots.claim(1, 4, cancel=stop, what="a check")         # Cancelled (an error) after 30 s
        self.assertEqual(len(lease.ids), 1)
        self.assertGreater(own.status()["queued_games"], 0)
        # Nobody waits now: the pool takes the other slots again (any freed meanwhile were left for a moment).
        self.assertTrue(wait_for(lambda: self.held_by(4, "warm worker (test pool)") == 3, 20))
        lease.release()
        self.assertTrue(wait_for(lambda: self.held_by(4, "warm worker (test pool)") == 4, 20))
        self.assertEqual(self.drain(ticket, 60)[-1], ("done", None))
        self.assertEqual((slots.waiting(), list(self.slots_dir.glob(slots.WANT_GLOB))), (0, []))

    def test_two_pools_share_the_slots(self):
        # A command line run's own pool (play --local) beside the server's busy one: before, it got its first
        # slot only once the busy pool's queue was empty; now each pool leaves the other the slots it frees.
        # (The other pool tries for a slot only once the busy one has looked for slots after freeing one:
        # settled_tries.)
        self.fake("delay=0.05")
        busy, other = self.pool_(workers=4, name="busy"), self.pool_(workers=4, name="other")
        self.settled_tries(busy, "warm worker (other pool)")
        first = busy.submit(self.job(800, batch=10))
        self.assertTrue(wait_for(lambda: self.held_by(4, "warm worker (busy pool)") == 4, 20))
        second = other.submit(self.job(40, batch=10, key="e" * 64))
        self.assertTrue(wait_for(lambda: slots.waiting() == 1, 10))   # the other pool says it waits
        self.assertEqual(self.drain(second, 60)[-1], ("done", None))
        self.assertGreater(busy.status()["queued_games"], 0)          # done long before the busy one's queue
        self.assertTrue(wait_for(lambda: self.held_by(4, "warm worker (busy pool)") == 4, 20))
        first.stop()
        self.assertEqual(slots.waiting(), 0)

    def test_a_worker_quits_after_its_games_or_when_its_heap_is_full(self):
        with mock.patch.object(pool, "WORKER_MAX_GAMES", 10):
            own = self.pool_(workers=1)
            self.drain(own.submit(self.job(30, batch=10)))
        self.assertGreaterEqual(len(self.procs), 3)
        before = len(self.procs)
        own = self.pool_(workers=1)
        self.drain(own.submit(self.job(30, batch=10, setup=self.setup_(xmx="80m"))))     # 64 MB > 75 % of 80
        self.assertGreaterEqual(len(self.procs) - before, 3)

    def test_close_stops_runs_and_kills_whats_left(self):
        self.fake("delay=1")
        own = pool.Pool(None, name="test", idle_s=30, workers=2)
        ticket = own.submit(self.job(40))
        self.assertTrue(wait_for(lambda: own.status()["busy"] == 2, 10))
        begun = time.monotonic()
        own.close(0.2)
        self.assertLess(time.monotonic() - begun, 5)
        self.assertTrue(self.all_dead())
        events = []
        while not ticket.events.empty():
            events.append(ticket.events.get())
        self.assertIn(("done", "closed"), events)
        with self.assertRaises(pool.PoolClosed):
            own.submit(self.job(10))

    def test_close_at_once_waits_only_a_moment_for_the_killed_workers(self):
        own = pool.Pool(None, name="test", idle_s=30, workers=2)
        self.drain(own.submit(self.job(20)))
        with mock.patch.object(forge.processes, "kill_process"):       # kills that haven't landed yet
            begun = time.monotonic()
            own.close(0)
            took = time.monotonic() - begun
        self.assertLess(took, pool.KILLED_WAIT + 1.5)                    # not runner.KILL_WAIT (10 s)
        self.assertGreaterEqual(took, pool.KILLED_WAIT - 0.1)

    def test_status_says_what_each_worker_does(self):
        self.fake("delay=0.5")
        own = self.pool_(workers=2)
        ticket = own.submit(self.job(50, batch=5))
        self.assertTrue(wait_for(lambda: own.status()["busy"] == 2, 10))
        status = own.status()
        self.assertEqual((status["name"], status["limit"], status["busy"], status["service"]), ("test", 2, 2, None))
        self.assertEqual(status["runs"], [{"key": "f" * 12, "queued_games": 40, "playing": 2, "low": False,
                                           "fallback": False}])
        worker = status["workers"][0]
        self.assertEqual((worker["state"], worker["oneshot"], worker["playing"]["key"]), ("busy", False, "f" * 12))
        self.assertIn(worker["slot"], range(4))
        json.dumps(status)
        ticket.stop()


class SessionTests(PoolCase):

    def test_runs_in_a_session_share_its_pool(self):
        with pool.session(local=True) as s:
            first = self.run_matchup(100, exact=True, pool=s)
            pids = {proc.pid for proc in self.procs}
            second = self.run_matchup(100, exact=True, pool=s, results_dir=self.tmp / "second")
            self.assertEqual({proc.pid for proc in self.procs}, pids)       # the same warm workers
            self.assertTrue(all(test_forge.alive(pid) for pid in pids))
        self.assertEqual((first["runs"][0]["pool"], second["runs"][0]["pool"]), ("local", "local"))
        self.assertIsNone(second["runs"][0]["startup_s"])                   # warm workers
        self.assertTrue(self.all_dead())

    def test_a_pool_given_to_a_run(self):
        own = self.pool_()
        result = self.run_matchup(50, exact=True, pool=own)
        self.assertEqual(result["runs"][0]["pool"], "local")
        self.assertTrue(own.status()["workers"])                # it's the pool's to close


class ReplayTests(PoolCase):
    """The replay command (cli._cmd_replay) in the real pool.session(), with the fake's serve
    mode (the contract's "Cross-package tests"; test_forge_replay tests replay itself against a
    stand-in session)."""

    LISTS = {"casual/green": GREEN, "casual/red": RED, "commander/gisa": GISA}

    def setUp(self):
        super().setUp()
        summaries = {deck_id: {"id": deck_id, "title": deck_id.split("/")[1].title(), "kind": deck_id.split("/")[0],
                               "versions": ["target"]} for deck_id in self.LISTS}
        for p in (mock.patch.object(decks, "find_summary", side_effect=summaries.get),
                  mock.patch.object(decks, "load_deck",
                                    side_effect=lambda deck_id, version: sections(self.LISTS[deck_id]))):
            p.start()
            self.addCleanup(p.stop)
        self.results.mkdir(parents=True, exist_ok=True)

    def run_main(self, *argv):
        from decklab.tests.test_forge_pool_service import CommandLineTests
        return CommandLineTests.run_main(self, *argv)

    def entry_(self, deck_id):
        kind = "commander" if deck_id.startswith("commander/") else "constructed"
        return entry(self.LISTS[deck_id], deck_id, kind, title=deck_id.split("/")[1].title())

    def save_v1(self, key, a, b, games, fmt="Constructed"):
        """A result of a and b (deck ids) saved before wave 2, with games counted games."""
        result = stored([(0, "win", i % 2) for i in range(games)])
        result.update(key=key, format=fmt)
        found = sorted((self.entry_(deck_id)["card_sha"], deck_id) for deck_id in (a, b))
        for side, (sha, deck_id) in zip(result["sides"], found):        # side 0: the smaller card_sha
            e = self.entry_(deck_id)
            side.update(card_sha=sha, kind=e["kind"], cards=e["cards"],
                        seen_as=[{"id": deck_id, "version": "target", "title": e["title"], "source": None,
                                  "when": "2026-10-01T10:00:00"}])
        (self.results / f"{key}.json").write_text(json.dumps(result), encoding="utf-8")

    def test_replay_plays_every_matchup_in_one_session_and_only_once(self):
        self.save_v1("1" * 64, "casual/green", "casual/red", 60)
        self.save_v1("2" * 64, "commander/gisa", "commander/gisa", 30, fmt="Commander")
        pools, lows = set(), []
        real_submit = pool.Pool.submit

        def submit(own, job):
            pools.add(id(own))
            lows.append(job["low"])
            return real_submit(own, job)

        with mock.patch.object(pool.Pool, "submit", submit):
            code, out, err = self.run_main("replay", "--results-dir", str(self.results), "--local")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "Replayed 2 of 2 matchups: 90 games.\n")
        # Both matchups' runs in the one session's pool, as replay runs (low priority), on its warm
        # workers, which closed with the session.
        self.assertEqual((len(pools), lows), (1, [True, True]))
        self.assertTrue(self.procs)
        self.assertTrue(all("serve" in proc.args for proc in self.procs))
        self.assertTrue(self.all_dead())
        for a, b, games in (("casual/green", "casual/red", 60), ("commander/gisa", "commander/gisa", 30)):
            result = forge.load(forge.matchup_key(self.entry_(a), self.entry_(b)), self.results)
            self.assertEqual(forge.saved._counted(result), games)
            self.assertEqual([(r["by"], r["pool"]) for r in result["runs"]], [("replay", "local")])
            self.assertEqual([g["g"] for g in result["batches"][0]["games"]], list(range(games)))
        # Again: nothing is missing, so nothing plays.
        before = len(self.procs)
        code, out, err = self.run_main("replay", "--results-dir", str(self.results), "--local")
        self.assertEqual((code, out), (0, "Nothing to replay: every current matchup has as many games with "
                                          "today's engine.\n"), err)
        self.assertEqual(len(self.procs), before)


class SettingsTests(unittest.TestCase):

    def setUp(self):
        pool._said.clear()
        self.addCleanup(pool._said.clear)

    def test_forge_pool_idle_s_must_be_an_int_of_0_or_more(self):
        logged = []
        with mock.patch.object(forge.common, "_log", logged.append):
            self.assertEqual(pool.idle_setting({"forge_pool_idle_s": 0}), 0)
            self.assertEqual(pool.idle_setting({"forge_pool_idle_s": 60}), 60)
            self.assertEqual(pool.idle_setting({}), 900)
            for value in ("900", True, -1, 1.5, None):
                self.assertEqual(pool.idle_setting({"forge_pool_idle_s": value}), 900, value)
            self.assertEqual(pool.idle_setting({"forge_pool_idle_s": "900"}), 900)     # said once
        self.assertEqual(len(logged), 5)
        self.assertEqual(logged[0], "config.json's forge_pool_idle_s must be a whole number of 0 or more, not '900', "
                                    "so warm workers quit after 900 s idle.")
        with mock.patch.object(forge.common, "_settings", return_value={"forge_pool_idle_s": 5, "forge_workers": 2}):
            own = pool.Pool(None, name="t")
        self.addCleanup(own.close, 0)
        self.assertEqual((own.idle_s, own.limit), (5, 2))

    def test_xmx_sizes(self):
        self.assertEqual([pool._xmx_mb(x) for x in ("1024m", "2g", "2G", "512k", str(1 << 30), "lots", None)],
                         [1024, 2048, 2048, 0.5, 1024, None, None])


# ============================================================ wave 3's run-loop hooks (package R)
# sim-wave3-contract.md section 8. Where E3's pieces aren't built yet (a pilot's -a and -dlpilot in
# runner.request_args, the override sets' user folders and deploys), the tests stand in for them,
# so they hold before and after E3 merges.

_w2_request_args = runner.request_args


def _pilot(profile="Default", switches=()):
    return {"profile": profile, "switches": sorted(switches)}


def _e3_request_args_built():
    """Does runner.request_args take pilots (E3's)?"""
    try:
        runner.request_args({"decks_dir": "d", "clock_s": 1}, "Constructed", "a.dck", "b.dck", 1, 1,
                            pilots=[_pilot(), _pilot("Reckless")])
    except NotImplementedError:
        return False
    return True


def _standin_request_args(setup, fmt, deck1, deck2, games, seed, v2=None, pilots=None):
    """runner.request_args as E3 builds it, for these tests while it isn't: each seat's profile
    after -a, and its switches after -dlpilot (v2)."""
    args = _w2_request_args(setup, fmt, deck1, deck2, games, seed, v2)
    if pilots is not None:
        at = args.index("-a")
        args[at + 1:at + 3] = [p["profile"] for p in pilots]
        if v2 is not None and any(p["switches"] for p in pilots):
            args += ["-dlpilot", *("+".join(p["switches"]) or "-" for p in pilots)]
    return args


def _gz_lines(path):
    import gzip
    return gzip.decompress(path.read_bytes()).decode("utf-8").splitlines()


class RunHookCase(PoolCase):

    def setUp(self):
        super().setUp()
        runner._said.clear()
        self.addCleanup(runner._said.clear)
        for name in (runner.SEED_BASE_ENV, runner.STOP_FILE_ENV, forge.cores.PIN_MODE_ENV):
            p = mock.patch.dict(os.environ)
            p.start()
            self.addCleanup(p.stop)
            os.environ.pop(name, None)
        if not _e3_request_args_built():
            p = mock.patch.object(runner, "request_args", _standin_request_args)
            p.start()
            self.addCleanup(p.stop)

    def games_of(self, result):
        return [g for batch in result["batches"] for g in batch["games"]]

    def asked(self):
        """Patch runner.request_line to note every request: [(first, games, -a's two profiles, the args)]."""
        sent = []
        real = runner.request_line

        def request_line(request_id, args):
            at = args.index("-a")
            sent.append((int(args[args.index("-dlgame") + 2]), int(args[args.index("-n") + 1]),
                         tuple(args[at + 1:at + 3]), list(args)))
            return real(request_id, args)

        p = mock.patch.object(runner, "request_line", request_line)
        p.start()
        self.addCleanup(p.stop)
        return sent

    def paired_extra(self):
        return {"paired": {"base_key": "b" * 64, "base_side": 0, "variant_side": 1,
                           "variant": {"card_sha": entry(GREEN)["card_sha"], "dck_sha": "c" * 64}}}


class PinModeTests(unittest.TestCase):

    def setUp(self):
        forge.cores._said.clear()
        self.addCleanup(forge.cores._said.clear)
        p = mock.patch.dict(os.environ)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop(forge.cores.PIN_MODE_ENV, None)

    def masks(self, mode):
        if mode is None:
            os.environ.pop(forge.cores.PIN_MODE_ENV, None)
        else:
            os.environ[forge.cores.PIN_MODE_ENV] = mode
        return [forge.cores.mask_for(slot) for slot in range(-1, 11)]

    def test_each_mode_gives_its_masks(self):
        from decklab.tests.test_forge_cores import two_ccds
        cores_ = forge.cores
        with mock.patch.object(cores_, "_masks", None), mock.patch.object(cores_, "_ccds", None), \
                mock.patch.object(cores_, "sys", mock.Mock(platform="win32")), \
                mock.patch.object(cores_, "_read_topology", return_value=two_ccds(vcache_first=False)):
            own = [0b11 << (2 * i) for i in (4, 5, 6, 7, 0, 1, 2, 3)]
            ccd1, ccd0 = 0xFF << 8, 0xFF
            self.assertEqual(self.masks(None), [None] + own + [None, None, None])
            self.assertEqual(self.masks("core"), [None] + own + [None, None, None])
            self.assertEqual(self.masks("none"), [None] * 12)
            self.assertEqual(self.masks("ccd"), [None] + [ccd1] * 4 + [ccd0] * 4 + [None, None, None])
            self.assertEqual(self.masks("core-wrap"), [None] + own + own[:3])
            logged = []
            with mock.patch.object(forge.common, "_log", logged.append):
                self.assertEqual(self.masks("socket"), [None] + own + [None, None, None])
                self.assertEqual(cores_.pin_mode(), "core")
            self.assertEqual(len(logged), 1)
            self.assertIn("DECKLAB_PIN_MODE", logged[0])

    def test_mode_none_never_pins(self):
        os.environ[forge.cores.PIN_MODE_ENV] = "none"
        logged = []
        with mock.patch.object(forge.cores, "core_masks", return_value=[0b11, 0b1100]), \
                mock.patch.object(forge.common, "_settings", return_value={"forge_pin": True}), \
                mock.patch.object(forge.common, "_log", logged.append):
            self.assertFalse(forge.cores.pin(os.getpid() + 1, 0))
        self.assertEqual(logged, [])


if __name__ == "__main__":
    unittest.main()
