"""Forge execution tests; shared fixtures remain in test_forge."""
import unittest
import os
import signal
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from unittest import mock
from decklab.lib import config, decks, forge, jobs
from decklab.tests.test_forge import (
    CARD_LOG, ForgeCase, GISA, GREEN, NO_JDK,
    RED, _real_build_command, alive, entry, load_json,
    make_forge, sections, setUpModule, stored, tearDownModule,
    wait_dead,
)


class RunTests(ForgeCase):

    def run_matchup(self, games=200, a=GREEN, b=RED, **kwargs):
        kwargs.setdefault("results_dir", self.results)
        return forge.run(entry(a, "casual/green"), entry(b, "casual/red"), games, by="Matt", **kwargs)

    def test_a_run_plays_parallel_batches_and_saves_them(self):
        calls = []
        result = self.run_matchup(400, workers=16, progress=lambda d, t, detail: calls.append((d, t, detail)))
        self.assertEqual(len(result["batches"]), 16)        # 16 x 25 (lists._batch_count)
        self.assertEqual([(b["n"], b["seed"], b["deck1"], len(b["games"])) for b in result["batches"]],
                         [(n, n + 1, n % 2, 25) for n in range(16)])
        run = result["runs"][0]
        self.assertEqual((run["asked"], run["played"], run["workers"], run["batch_games"], run["seeds"], run["by"],
                          run["stopped"], run["error"], run["failed"]), (400, 400, 16, 25, [1, 16], "Matt", False, None, 0))
        self.assertEqual(len({pid for pid, _, _ in self.starts()}), 16)
        self.assertEqual(load_json(self.results / f"{result['key']}.json"), result)
        # progress: the first and last calls, a sensible detail, never more than asked.
        self.assertEqual(calls[0][:2], (0, 400))
        self.assertEqual(calls[-1][:2], (400, 400))
        detail = calls[-1][2]
        self.assertEqual(sum(detail["wins"]) + detail["other"], 400)
        self.assertEqual(detail["failed_batches"], 0)
        self.assertTrue(all(d <= t for d, t, _ in calls))
        # The sides are stored in card_sha order; both lists are noted as they were played.
        shas = [s["card_sha"] for s in result["sides"]]
        self.assertEqual(shas, sorted(shas))
        self.assertEqual({s["seen_as"][0]["id"] for s in result["sides"]}, {"casual/green", "casual/red"})
        # The run notes which list was asked for first, and a list shows that one first.
        green = entry(GREEN, "casual/green")["card_sha"]
        self.assertEqual(run["a"], green)
        self.assertEqual(forge.list_item(result)["sides"][0]["id"], "casual/green")
        # Casts: Fiery Annihilation is never cast; what the fake logs as Swift End counts for Murderous Rider.
        v = forge.view(result, entry(GREEN)["card_sha"])
        self.assertEqual(sum(v["wins"]) + v["draws"] + v["timeouts"] + v["errors"], 400)
        green = {c["name"]: c for c in v["casts"][0]}
        self.assertEqual(green["Fiery Annihilation"]["casts"], 0)
        self.assertGreater(green["Overrun"]["casts"], 0)
        self.assertNotIn("Forest", green)
        # The .dck files are content-addressed.
        for side in result["sides"]:
            path = forge.common.DATA_DIR / "decks" / f"{side['card_sha']}.dck"
            self.assertEqual(path.read_text(encoding="utf-8"), side["dck"])

    def test_the_first_run_replays_and_more_games_go_on(self):
        first = self.run_matchup(200)
        again = self.run_matchup(200, results_dir=self.tmp / "other")
        self.assertEqual([b["games"] for b in again["batches"]], [b["games"] for b in first["batches"]])
        more = self.run_matchup(200)
        self.assertEqual([(b["n"], b["seed"], b["deck1"]) for b in more["batches"]],
                         [(0, 1, 0), (1, 2, 1), (2, 3, 0), (3, 4, 1)])
        self.assertEqual(len(more["runs"]), 2)
        self.assertEqual(forge.view(more, first["sides"][0]["card_sha"])["games"], 400)

    def test_a_first_puts_a_in_seat_1_on_even_batches(self):
        a, b = entry(GREEN, "casual/green"), entry(RED, "casual/red")
        result = forge.run(b, a, 200, by="x", results_dir=self.results, a_first=True)
        b_side = [s["card_sha"] for s in result["sides"]].index(b["card_sha"])
        self.assertEqual(result["batches"][0]["deck1"], b_side)
        self.assertEqual(result["batches"][1]["deck1"], 1 - b_side)

    def test_one_failed_batch_isnt_counted(self):
        self.fake("crash@2#50")
        result = self.run_matchup(200)
        self.assertEqual([b["seed"] for b in result["batches"]], [1])
        self.assertEqual(result["failed"], [{"n": 1, "seed": 2, "deck1": 1,
                                             "error": "Forge stopped with an error (exit code 1)"}])
        self.assertEqual((result["runs"][0]["played"], result["runs"][0]["failed"], result["runs"][0]["failure"]),
                         (100, 1, "Forge stopped with an error (exit code 1)"))
        self.assertEqual(forge.view(result, result["sides"][0]["card_sha"])["games"], 100)
        self.assertTrue(list((forge.common.DATA_DIR / "logs").glob("*-seed2.log")))
        # Its seed isn't used again.
        more = self.run_matchup(200)
        self.assertEqual([b["seed"] for b in more["batches"]], [1, 3, 4])

    def test_timeouts_and_errors_count_as_games_but_not_wins(self):
        self.fake("timeout#3;exception#4;aitimeout#5")
        result = self.run_matchup(200)
        v = forge.view(result, result["sides"][0]["card_sha"])
        self.assertEqual((v["games"], v["timeouts"], v["errors"], v["ai_timeouts"]), (200, 2, 2, 4))
        self.assertEqual(sum(v["wins"]), 196)

    def test_when_every_batch_fails_nothing_is_counted(self):
        self.fake("noload")
        with self.assertRaises(forge.ForgeError) as caught:
            self.run_matchup(200)
        self.assertEqual(str(caught.exception), "No games could be played: Forge couldn't load one of the decks.")
        key = forge.matchup_key(entry(GREEN), entry(RED))
        saved = forge.load(key, self.results)
        self.assertEqual((saved["batches"], len(saved["failed"])), ([], 2))
        self.assertEqual(saved["runs"][0]["error"], "Forge couldn't load one of the decks")
        self.assertEqual(forge.results(self.results), [])

    def test_an_unsupported_card_fails_the_batch(self):
        self.fake("unsupported@1")
        result = self.run_matchup(200)
        self.assertEqual(result["failed"][0]["error"], "Forge doesn't know these cards: Totally Fake Card")

    def test_unknown_names_stop_the_run_before_forge_starts(self):
        with self.assertRaises(forge.ForgeError) as caught:
            self.run_matchup(200, b=RED + "2 Totally Fake Card\n1 Grizzly Bearz\n")
        self.assertEqual(str(caught.exception), "Forge doesn't know these cards, so the matchup can't be played: "
                                                "Totally Fake Card, Grizzly Bearz.")
        self.assertEqual(self.starts(), [])
        self.assertFalse(self.results.exists())

    def saved(self):
        return forge.load(forge.matchup_key(entry(GREEN), entry(RED)), self.results)

    def kept(self, result):
        """[(seed, games, partial?)] of a result's counted batches."""
        return [(b["seed"], len(b["games"]), b.get("partial", False)) for b in result["batches"]]

    def test_stop_keeps_every_game_that_finished(self):
        # Seed 2's process hangs before its 11th game ends: its 10 games are kept as a partial batch.
        self.fake("hang@2#11")
        reached = []

        def progress(done, total, detail):
            if done >= 110:
                reached.append(time.monotonic())
                if time.monotonic() - reached[0] > 0.3:
                    stop = jobs.Stopped("Stopped by User1")
                    stop.by = "User1"
                    raise stop

        with self.assertRaises(jobs.Stopped):
            self.run_matchup(200, progress=progress)
        saved = self.saved()
        self.assertEqual(self.kept(saved), [(1, 100, False), (2, 10, True)])
        self.assertEqual(saved["failed"], [])
        run = saved["runs"][0]
        self.assertEqual((run["asked"], run["played"], run["batches"], run["played_batches"], run["partial"],
                          run["seeds"], run["stopped"], run["stopped_by"], run["error"]),
                         (200, 110, 2, 2, 1, [1, 2], True, "User1", None))
        v = forge.view(saved, saved["sides"][0]["card_sha"])
        self.assertEqual((v["games"], v["runs"][0]["played"], v["runs"][0]["partial"]), (110, 110, 1))
        self.assertEqual(sum(v["wins"]) + v["draws"] + v["timeouts"] + v["errors"], 110)
        self.assertEqual(forge.list_item(saved)["games"], 110)
        self.assertEqual(forge.results(self.results)[0]["games"], 110)
        self.assertTrue(all(wait_dead(pid) for pid, _, _ in self.starts()))
        # The next run goes on after the partial batch's seed.
        self.assertEqual([(b["n"], b["seed"]) for b in forge.plan(200, saved, workers=4)],
                         [(2, 3), (3, 4), (4, 5), (5, 6)])

    def test_a_stop_keeps_only_the_batches_that_started(self):
        # Two processes at a time, each stuck after 10 games: batches 3 and 4 never start.
        self.fake("hang#11")

        def progress(done, total, detail):
            if done >= 20:
                raise jobs.Stopped("stop")

        with self.assertRaises(jobs.Stopped):
            self.run_matchup(400, batch=100, workers=2, progress=progress)
        saved = self.saved()
        self.assertEqual(self.kept(saved), [(1, 10, True), (2, 10, True)])
        run = saved["runs"][0]
        self.assertEqual((run["asked"], run["played"], run["batches"], run["played_batches"], run["partial"],
                          run["seeds"], run["stopped_by"]), (400, 20, 4, 2, 2, [1, 2], None))
        self.assertEqual(forge.plan(400, saved, batch=100)[0]["seed"], 3)
        self.assertTrue(all(wait_dead(pid) for pid, _, _ in self.starts()))

    def test_a_stopped_batch_forge_couldnt_play_still_fails(self):
        self.fake("unsupported@2;hang#11")

        def progress(done, total, detail):
            if done >= 20:
                raise jobs.Stopped("stop")

        with self.assertRaises(jobs.Stopped):
            self.run_matchup(200, progress=progress)
        saved = self.saved()
        self.assertEqual(self.kept(saved), [(1, 10, True)])
        self.assertEqual(saved["failed"], [{"n": 1, "seed": 2, "deck1": 1,
                                            "error": "Forge doesn't know these cards: Totally Fake Card"}])
        self.assertEqual(saved["runs"][0]["played"], 10)

    def test_a_batch_that_ended_as_the_stop_came_is_kept_whole(self):
        # The stop comes with the last game, before its process's end has been read.
        def progress(done, total, detail):
            if done == total:
                raise jobs.Stopped("stop")

        with mock.patch.object(forge.runner, "PROGRESS_GAP", 0), self.assertRaises(jobs.Stopped):
            self.run_matchup(400, workers=4, progress=progress)
        saved = self.saved()
        self.assertEqual(self.kept(saved), [(1, 100, False), (2, 100, False), (3, 100, False), (4, 100, False)])
        self.assertEqual((saved["runs"][0]["played"], saved["runs"][0]["partial"]), (400, 0))

    def test_ctrl_c_stops_too(self):
        self.fake("hang#20")

        def progress(done, total, detail):
            if done >= 38:
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self.run_matchup(200, progress=progress)
        self.assertTrue(all(wait_dead(pid) for pid, _, _ in self.starts()))
        saved = self.saved()
        self.assertEqual(self.kept(saved), [(1, 19, True), (2, 19, True)])
        self.assertEqual((saved["runs"][0]["played"], saved["runs"][0]["stopped"]), (38, True))

    def test_a_second_ctrl_c_while_stopping_still_saves(self):
        self.fake("hang#20")
        real_join = threading.Thread.join
        pressed = []

        def join(thread, timeout=None):
            if thread.name.startswith("forge-") and not pressed:
                pressed.append(thread.name)
                signal.raise_signal(signal.SIGINT)      # Ctrl+C again, while the stop waits
            return real_join(thread, timeout)

        def progress(done, total, detail):
            if done >= 38:
                raise KeyboardInterrupt

        with mock.patch.object(threading.Thread, "join", join), self.assertRaises(KeyboardInterrupt):
            self.run_matchup(200, progress=progress)
        self.assertEqual(len(pressed), 1)
        self.assertIs(signal.getsignal(signal.SIGINT), signal.default_int_handler)
        self.assertEqual(self.kept(self.saved()), [(1, 19, True), (2, 19, True)])
        self.assertTrue(all(wait_dead(pid) for pid, _, _ in self.starts()))

    def test_ctrl_c_as_a_process_starts_still_kills_it(self):
        self.fake("hang#20")
        real_start = forge.processes.start_process
        started = []

        def start(argv, cwd=None, env=None):
            proc = real_start(argv, cwd=cwd, env=env)
            started.append(proc)
            self.addCleanup(forge.kill_process, proc)
            if argv[argv.index("-s") + 1] == "2":
                signal.raise_signal(signal.SIGINT)      # before the batch has been noted
            return proc

        with mock.patch.object(forge.processes, "start_process", start), self.assertRaises(KeyboardInterrupt):
            self.run_matchup(200)
        self.assertEqual(len(started), 2)
        self.assertTrue(all(wait_dead(proc.pid) for proc in started))
        self.assertTrue(self.saved()["runs"][0]["stopped"])

    def test_ctrl_c_once_the_games_are_over_still_saves_them(self):
        real_tidy = forge.runner._tidy_user_dir

        def tidy(user_dir):
            signal.raise_signal(signal.SIGINT)
            sum(range(1000))
            real_tidy(user_dir)

        with mock.patch.object(forge.runner, "_tidy_user_dir", tidy), self.assertRaises(KeyboardInterrupt):
            self.run_matchup(200)
        saved = self.saved()
        self.assertEqual(self.kept(saved), [(1, 100, False), (2, 100, False)])
        self.assertEqual((saved["runs"][0]["played"], saved["runs"][0]["stopped"]), (200, False))

    def test_ctrl_c_is_held_back_while_it_must_be(self):
        reached, notes = [], []
        with self.assertRaises(KeyboardInterrupt):
            with forge._interrupts_held():
                signal.raise_signal(signal.SIGINT)
                sum(range(1000))
                reached.append(True)
        self.assertEqual(reached, [True])
        with forge._interrupts_held(note=lambda: notes.append(True)):
            signal.raise_signal(signal.SIGINT)
            sum(range(1000))
        self.assertEqual(notes, [True])
        self.assertIs(signal.getsignal(signal.SIGINT), signal.default_int_handler)

    def test_an_error_while_playing_isnt_a_stop(self):
        self.fake("hang#20")

        def progress(done, total, detail):
            if done >= 38:
                raise TypeError("a bug")

        with self.assertRaises(TypeError):
            self.run_matchup(200, progress=progress)
        run = self.saved()["runs"][0]
        self.assertEqual((run["stopped"], run["stopped_by"], run["error"], run["played"]),
                         (False, None, "The run stopped because of an error in Deck Lab (TypeError).", 38))
        self.assertTrue(all(wait_dead(pid) for pid, _, _ in self.starts()))

    def test_one_list_under_two_ids(self):
        x, y = entry(GREEN, "casual/x", title="X"), entry(GREEN, "casual/y", title="Y")
        result = forge.run(x, y, 200, by="Matt", results_dir=self.results)
        self.assertEqual([s["title"] for s in forge.list_item(result)["sides"]], ["X", "Y"])
        self.assertEqual([[s["id"] for s in side["seen_as"]] for side in result["sides"]], [["casual/x"], ["casual/y"]])
        again = forge.run(y, x, 200, by="Matt", results_dir=self.results)
        self.assertEqual([s["title"] for s in forge.list_item(again)["sides"]], ["Y", "X"])

    def test_a_results_folder_that_cant_be_written(self):
        blocker = self.tmp / "a-file.txt"
        blocker.write_text("x", encoding="utf-8")
        with mock.patch.object(forge.common, "_log") as log, self.assertRaises(forge.ForgeError) as caught:
            self.run_matchup(200, results_dir=blocker / "results")
        from decklab.lib.forge import lifecycle
        self.assertEqual(str(caught.exception), lifecycle.UNSAFE)
        self.assertEqual(self.starts(), [])         # found out before Forge started
        self.assertIn("a-file.txt", log.call_args[0][0])     # the details go to the server window

    def test_a_save_that_fails(self):
        real_write = forge.common._write_atomic

        def write(path, text):
            if path.parent == self.results and path.suffix == ".json":
                raise PermissionError(13, "Access is denied", str(path))
            return real_write(path, text)

        with mock.patch.object(forge.common, "_write_atomic", write), mock.patch.object(forge.common, "_log"):
            with self.assertRaises(forge.ForgeError) as caught:
                self.run_matchup(200)
            self.assertEqual(str(caught.exception), "Deck Lab couldn't save the matchup's games.")

            def progress(done, total, detail):
                if done >= 10:
                    raise jobs.Stopped("stop")

            with self.assertRaises(jobs.Stopped):           # a stop is still a stop
                self.run_matchup(200, progress=progress)

    def test_the_same_matchup_cant_be_played_twice_at_once(self):
        self.fake("delay=0.02")
        started, out = threading.Event(), {}

        def first():
            try:
                out["first"] = self.run_matchup(20, batch=10, workers=2, progress=lambda *a: started.set())
            except BaseException as e:
                out["first"] = e

        thread = threading.Thread(target=first)
        thread.start()
        self.assertTrue(started.wait(20))
        with self.assertRaises(forge.ForgeError) as caught:
            self.run_matchup(20, batch=10, workers=2)
        self.assertEqual(str(caught.exception), "This matchup is already being played.")
        thread.join(60)
        self.assertEqual(self.kept(out["first"]), [(1, 10, False), (2, 10, False)])
        # Free again once it's done; the second run goes on from the first's seeds.
        more = self.run_matchup(20, batch=10, workers=2)
        self.assertEqual([b["seed"] for b in more["batches"]], [1, 2, 3, 4])
        self.assertEqual(len(more["runs"]), 2)
        if sys.platform == "win32":
            self.assertEqual(list(self.results.glob("*.lock")), [])

    def test_a_lock_file_nobody_holds_doesnt_stop_a_run(self):
        self.results.mkdir()
        key = forge.matchup_key(entry(GREEN), entry(RED))
        (self.results / f"{key}.lock").write_text("", encoding="utf-8")     # left by a hard kill
        self.assertEqual(len(self.run_matchup(200)["batches"]), 2)

    def test_the_watchdog_kills_a_process_that_stops_printing(self):
        self.settings["forge_clock_s"] = 1
        with mock.patch.object(forge.runner, "GAME_GRACE", 1):
            self.fake("hang@2#5")
            started = time.monotonic()
            result = self.run_matchup(200)
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(result["failed"], [{"n": 1, "seed": 2, "deck1": 1, "error": "Forge stopped responding"}])
        self.assertEqual(len(result["batches"]), 1)
        self.assertTrue(all(wait_dead(pid) for pid, _, _ in self.starts()))

    def test_the_watchdog_kills_a_process_with_no_header(self):
        with mock.patch.object(forge.runner, "HEADER_TIMEOUT", 1):
            self.fake("slowstart=60@1")
            result = self.run_matchup(200)
        self.assertEqual(result["failed"][0]["error"], "Forge stopped responding")
        self.assertEqual([b["seed"] for b in result["batches"]], [2])

    def test_the_first_use_of_the_user_folder_starts_one_process_alone(self):
        self.settings["forge_workers"] = 4      # the PC's budget (slots.py): room for all 4 at once
        self.fake("slowstart=0.6")
        # When Deck Lab starts each process, not when its Python is up (4 at once on a small CI runner
        # can take over a second between them).
        times = []
        real_start = forge.processes.start_process

        def start(argv, cwd=None, env=None, stdin=False):
            times.append(time.monotonic())
            return real_start(argv, cwd=cwd, env=env, stdin=stdin)

        with mock.patch.object(forge.processes, "start_process", start):
            self.run_matchup(200, batch=50, workers=4)
            self.assertEqual(len(times), 4)
            self.assertGreaterEqual(times[1] - times[0], 0.5)       # the rest waited for the first header
            del times[:]
            self.run_matchup(200, batch=50, workers=4, results_dir=self.tmp / "second")
        self.assertLess(times[-1] - times[0], 0.5)                   # then all together

    def test_the_user_folder(self):
        user = self.tmp / "user"
        (user / "Forge").mkdir(parents=True)
        for name in ("forge.20260929-152058.log", "forge.20260929-141702.1.log", "forge.log"):
            (user / "Forge" / name).write_text("x", encoding="utf-8")
        env = forge._prepare_user_dir(user)
        self.assertEqual(sorted(p.name for p in (user / "Forge").glob("*.log")), ["forge.log"])
        prefs = user / "Forge" / "preferences" / "forge.preferences"
        self.assertEqual(prefs.read_text(encoding="utf-8"), "LOAD_CARD_SCRIPTS_LAZILY=true\nPERFORMANCE_MODE=true\n")
        self.assertEqual((env["APPDATA"], env["LOCALAPPDATA"]), (str(user), str(user)))
        # After a run, the copies the processes left go too.
        (user / "Forge" / "forge7.log").write_text("x", encoding="utf-8")
        forge.runner._tidy_user_dir(user)
        self.assertEqual(list((user / "Forge").glob("*.log")), [])
        self.assertTrue(prefs.exists())

    def test_a_run_tidies_the_user_folder(self):
        folder = forge.common.DATA_DIR / "user" / "Forge"
        folder.mkdir(parents=True)
        (folder / "forge3.log").write_text("x", encoding="utf-8")
        self.run_matchup(200)
        self.assertEqual(list(folder.glob("*.log")), [])

    def test_the_command(self):
        setup = {"java": "C:/jdk/bin/java.exe", "xmx": "1024m", "jar": "forge-gui-desktop-2.0.15-jar-with-dependencies.jar",
                 "decks_dir": Path("D:/decks"), "clock_s": 120}
        jvm = ["C:/jdk/bin/java.exe", "-Xmx1024m", "-XX:+DisableExplicitGC", "-XX:ActiveProcessorCount=2",
               "-Dio.netty.tryReflectionSetAccessible=true", "-Dfile.encoding=UTF-8"]
        sim = ["sim", "-D", str(Path("D:/decks")), "-d", "a.dck", "b.dck", "-n", "200", "-s", "7", "-f", "Commander",
               "-c", "120", "-a", "Default", "Default"]
        # Plain Forge plays the fork's game-changing changes as Forge's own code.
        plain = jvm + [forge.simjar.GAME_PATCHES_OFF, "-jar", "forge-gui-desktop-2.0.15-jar-with-dependencies.jar"] + sim
        self.assertEqual(_real_build_command(setup, "Commander", "a.dck", "b.dck", 200, 7), plain)
        # The card log off (it can't be used): Forge's own sim, exactly as before.
        off = dict(setup, card_log={"ready": False, "problem": NO_JDK})
        self.assertEqual(_real_build_command(off, "Commander", "a.dck", "b.dck", 200, 7), plain)
        # On: DeckLabSim from the class path, the card-log jar first, with the manifest's
        # --add-opens, and the same arguments.
        on = dict(setup, card_log=CARD_LOG)
        self.assertEqual(_real_build_command(on, "Commander", "a.dck", "b.dck", 200, 7),
                         jvm + ["--add-opens", "java.desktop/java.beans=ALL-UNNAMED", "-cp",
                                CARD_LOG["jar"] + os.pathsep
                                + "forge-gui-desktop-2.0.15-jar-with-dependencies.jar", "decklab.DeckLabSim"] + sim)

    def test_a_run_with_the_card_log_keeps_its_card_records(self):
        calls = []

        def card_log(*args, **kwargs):
            calls.append(args)
            return dict(CARD_LOG)

        with mock.patch.object(forge.simjar, "card_log", card_log):
            result = self.run_matchup(200)
        setup = forge.install._setup()
        self.assertEqual(calls, [(setup["java"], setup["forge_dir"], setup["jar"], "2.0.15")])
        run = result["runs"][0]
        self.assertTrue(run["card_log"])
        self.assertNotIn("card_log_problem", run)
        # The v2 engine (wave 2): game numbers 0-199 in the warm pool, one merged batch with one card record.
        self.assertEqual(run["pool"], "local")
        [batch] = result["batches"]
        self.assertEqual((batch["n"], batch["first"], [g["g"] for g in batch["games"]]), (0, 0, list(range(200))))
        cards = batch["cards"]
        self.assertEqual((cards["v"], cards["games"] + cards["bad"]), (forge.cardlog.RECORD_VERSION, 200))
        self.assertGreater(cards["games"], 0)
        self.assertEqual(len(cards["rows"]), 2)
        self.assertEqual(load_json(self.results / f"{result['key']}.json"), result)
        # Without the card log: plain Forge's cold batches, as before.
        plain = self.run_matchup(200, results_dir=self.tmp / "plain")
        self.assertEqual([(b["seed"], len(b["games"])) for b in plain["batches"]], [(1, 100), (2, 100)])
        self.assertNotIn("seeds", plain)

    def test_a_run_without_the_card_log_says_why(self):
        # The tests' Java is this Python: no javac or jar beside it, so no card log.
        result = self.run_matchup(200)
        run = result["runs"][0]
        self.assertEqual((run["card_log"], run["card_log_problem"]), (False, NO_JDK))
        self.assertTrue(all("cards" not in b for b in result["batches"]))
        with mock.patch.object(forge.simjar, "card_log", return_value={"ready": False, "problem": "Not today."}):
            more = self.run_matchup(200)
        self.assertEqual(more["runs"][1]["card_log_problem"], "Not today.")

    def test_a_batch_whose_card_logs_fail_their_checks_logs_why(self):
        # The v2 engine's games are numbered in the result: badcardlog#G is game number G.
        self.fake("badcardlog#1;badcardlog#2;badcardlog#3;badcardlog#4")
        with mock.patch.object(forge.simjar, "card_log", return_value=dict(CARD_LOG)), \
                mock.patch.object(forge.common, "_log") as log:
            result = self.run_matchup(400, workers=2)
        lines = [c.args[0] for c in log.call_args_list if "failed its checks" in c.args[0]]
        [batch] = result["batches"]
        self.assertEqual(batch["cards"]["bad"], 4)
        self.assertEqual(len(lines), 1)                     # one line a run
        self.assertRegex(lines[0], r"^Games 0-399: the card log of 4 of 400 games failed its checks \(game 1: .+; "
                                   r"game 2: .+; game 3: .+; \.\.\.\)\.$")
        self.assertNotIn("game 4:", lines[0])

    def test_a_failure_log_keeps_forges_lines_not_the_card_logs(self):
        # Game 3 always crashes its worker: after going back to the queue twice it fails (pool.MAX_REQUEUE).
        self.fake("crash#3")
        with mock.patch.object(forge.simjar, "card_log", return_value=dict(CARD_LOG)):
            result = self.run_matchup(200, batch=5)
        self.assertEqual([(f["first"], f["games"]) for f in result["failed"]], [(3, 2)])
        text = next((forge.common.DATA_DIR / "logs").glob("*-g3.log")).read_text(encoding="utf-8")
        self.assertTrue(text.startswith(forge.pool.PART_WAY + "\n\n"))
        self.assertIn("java.lang.OutOfMemoryError", text)
        self.assertNotIn("DL|", text)

    def test_forge_must_be_ready(self):
        self.settings["forge_dir"] = str(self.tmp / "nowhere")
        with self.assertRaises(forge.ForgeError) as caught:
            self.run_matchup(200)
        self.assertEqual(str(caught.exception), "Forge isn't installed at the folder config.json names.")

    def test_a_commander_mirror(self):
        a = entry(GISA, "commander/gisa", "commander")
        result = forge.run(a, a, 200, by="Matt", results_dir=self.results)
        self.assertEqual(result["format"], "Commander")
        self.assertEqual(result["sides"][0]["card_sha"], result["sides"][1]["card_sha"])
        v = forge.view(result, a["card_sha"])
        self.assertEqual(v["games"], 200)
        self.assertTrue(v["not_meaningful"])            # the AI never casts Ghoulcaller Gisa

    def test_progress_comes_at_most_4_and_at_least_once_a_second(self):
        # Fast games (many a second), after a slow start-up in which none finish.
        self.fake("slowstart=1.5;delay=0.005")
        calls = []
        self.run_matchup(200, progress=lambda done, total, detail: calls.append((time.monotonic(), done)))
        gaps = [later[0] - earlier[0] for earlier, later in zip(calls, calls[1:])]
        self.assertTrue(all(gap >= forge.runner.PROGRESS_GAP - 0.01 for gap in gaps[:-1]), gaps)     # the last is the final
        self.assertLess(max(gaps), forge.HEARTBEAT + 0.5, gaps)
        self.assertGreaterEqual(sum(1 for _, done in calls if done == 0), 2)       # heartbeats while starting
        self.assertEqual(calls[-1][1], 200)

    def test_workers_must_be_one_or_more(self):
        for workers in (0, -1):
            with self.assertRaises(ValueError):
                forge.plan(200, workers=workers)
            with self.assertRaises(ValueError):
                self.run_matchup(200, workers=workers)
        self.assertEqual(self.starts(), [])
        self.settings["forge_workers"] = 0
        self.assertEqual(forge.status(refresh=True)["problem"],
                         "config.json's forge_workers must be a whole number of 1 or more.")
        with self.assertRaises(forge.ForgeError):
            self.run_matchup(200)
        self.assertEqual(self.starts(), [])

    def test_forge_batch_games_no_longer_has_to_be_a_number(self):
        # It no longer changes anything (lists._batch_count), so it can't stop a run either.
        for value in (0, "lots", None):
            self.settings["forge_batch_games"] = value
            self.assertIsNone(forge.status(refresh=True)["problem"], value)
        result = self.run_matchup(200)
        self.assertEqual([len(b["games"]) for b in result["batches"]], [100, 100])     # 2 workers: 2 x 100

    def test_a_process_that_cant_be_started_fails_its_batch(self):
        def start(argv, cwd=None, env=None):
            raise FileNotFoundError(2, "The system cannot find the file specified", "C:\\nowhere\\java.exe")

        with mock.patch.object(forge.processes, "start_process", start), mock.patch.object(forge.common, "_log") as log, \
                self.assertRaises(forge.ForgeError) as caught:
            self.run_matchup(200)
        reason = "Forge couldn't be started (the system cannot find the file specified)"
        self.assertEqual(str(caught.exception), f"No games could be played: {reason}.")
        self.assertEqual([f["error"] for f in self.saved()["failed"]], [reason, reason])
        self.assertIn("nowhere", log.call_args_list[0][0][0])        # the path goes to the server window only
        self.assertEqual(forge._os_reason(OSError("the process couldn't be started")),
                         "the process couldn't be started")
        self.assertEqual(forge._os_reason(OSError()), "OSError")

    @unittest.skipUnless(sys.platform == "win32", "the Job Object is Windows-only")
    def test_a_process_windows_wont_resume_fails_its_batch(self):
        class NtDll:
            @staticmethod
            def NtResumeProcess(handle):
                return 1                # not STATUS_SUCCESS

        with mock.patch.object(forge.processes, "_ntdll", NtDll()), mock.patch.object(forge.common, "_log"), \
                self.assertRaises(forge.ForgeError) as caught:
            self.run_matchup(200)
        self.assertEqual(str(caught.exception),
                         "No games could be played: Forge couldn't be started (Windows wouldn't let it run).")
        self.assertEqual(self.starts(), [])             # killed before it ran a line

    def test_a_deck_file_with_the_same_cards_isnt_written_again(self):
        first = self.run_matchup(200)
        path = forge.common.DATA_DIR / "decks" / f"{first['sides'][0]['card_sha']}.dck"
        os.utime(path, (1_000_000, 1_000_000))
        self.run_matchup(200)
        self.assertEqual(path.stat().st_mtime, 1_000_000)
        path.write_text("[metadata]\nName=broken\n", encoding="utf-8")       # not what its name says
        self.run_matchup(200)
        self.assertEqual(path.read_text(encoding="utf-8"), first["sides"][0]["dck"])

    def test_saved_games_that_cant_be_read_arent_played_over(self):
        self.results.mkdir()
        path = self.results / f"{forge.matchup_key(entry(GREEN), entry(RED))}.json"
        for text in ("[]", '{"x": 1}', "{"):
            path.write_text(text, encoding="utf-8")
            with mock.patch.object(forge.common, "_log"), self.assertRaises(forge.ForgeError) as caught:
                self.run_matchup(200)
            self.assertEqual(str(caught.exception), forge.UNREADABLE)
            self.assertEqual(path.read_text(encoding="utf-8"), text)
        self.assertEqual(self.starts(), [])
        self.assertEqual(len(self.run_matchup(200, save=False)["batches"]), 2)     # nothing to lose

    def test_a_stopped_run_says_how_many_games_were_saved(self):
        self.fake("hang#11")

        def progress(done, total, detail):
            if done >= 20:
                raise jobs.Stopped("stop")

        with self.assertRaises(jobs.Stopped) as caught:
            self.run_matchup(200, progress=progress)
        self.assertEqual(caught.exception.saved_games, 20)
        with self.assertRaises(jobs.Stopped) as caught:
            self.run_matchup(200, progress=progress, save=False)
        self.assertIsNone(caught.exception.saved_games)



@unittest.skipUnless(sys.platform == "win32", "the Job Object is Windows-only")
class JobObjectTests(ForgeCase):

    def test_processes_go_in_the_job(self):
        proc = forge.processes.start_process([sys.executable, "-c", "import time; print('hi', flush=True); time.sleep(30)"])
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.kill)
        self.assertEqual(proc.stdout.readline().strip(), "hi")     # it was resumed
        self.assertTrue(forge.in_job(proc.pid))
        proc.kill()
        proc.wait()

    def test_a_warm_worker_gets_its_input_on_a_pipe(self):
        # pool.py's workers read their requests on stdin (UTF-8 text, a line at a time).
        code = "import sys; [print('got', line.strip(), flush=True) for line in sys.stdin]"
        proc = forge.processes.start_process([sys.executable, "-c", code], stdin=True)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(forge.kill_process, proc)
        self.assertTrue(forge.in_job(proc.pid))
        proc.stdin.write("play\tc1\tsim — é\n")
        proc.stdin.flush()
        self.assertEqual(proc.stdout.readline().strip(), "got play\tc1\tsim — é")
        proc.stdin.close()
        proc.wait(10)
        other = forge.processes.start_process([sys.executable, "-c", "pass"])
        self.assertIsNone(other.stdin)
        other.wait(10)
        other.stdout.close()

    def test_alive(self):
        proc = forge.processes.start_process([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(proc.stdout.close)
        self.addCleanup(forge.kill_process, proc)
        self.assertTrue(forge.processes.alive(proc.pid))
        self.assertTrue(forge.processes.alive(os.getpid()))
        forge.kill_process(proc)
        proc.wait()
        self.assertTrue(wait_dead(proc.pid))
        self.assertFalse(forge.processes.alive(proc.pid))
        for odd in (0, -1, None, "x"):
            self.assertFalse(forge.processes.alive(odd))

    def test_a_kill_ends_what_the_process_started(self):
        # Like the java.exe on the PATH, which runs the real Java as its child.
        code = ("import subprocess, sys, time;"
                "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
                "print(c.pid, flush=True); time.sleep(60)")
        proc = forge.processes.start_process([sys.executable, "-c", code])
        self.addCleanup(proc.stdout.close)
        self.addCleanup(forge.kill_process, proc)
        child = int(proc.stdout.readline())
        self.assertTrue(alive(child))
        self.assertTrue(forge.in_job(child))
        forge.kill_process(proc)
        proc.wait()
        self.assertTrue(wait_dead(child, 10))
        forge._end_process(proc)
        forge.kill_process(proc)            # harmless once it's over

    def test_a_hard_kill_of_this_process_kills_forge_too(self):
        # A helper Python starts a "Forge" through start_process and waits; killing the helper
        # alone (TerminateProcess, as taskkill /F without /T does) must end its child too.
        helper = subprocess.Popen(
            [sys.executable, "-c",
             "import sys, time; from decklab.lib import forge;"
             "p = forge.processes.start_process([sys.executable, '-c', 'import time; time.sleep(60)']);"
             "print(p.pid, flush=True); time.sleep(60)"],
            cwd=config.REPO, stdout=subprocess.PIPE, text=True)
        self.addCleanup(helper.stdout.close)
        self.addCleanup(helper.kill)
        child = int(helper.stdout.readline())
        self.assertTrue(alive(child))
        helper.kill()
        helper.wait()
        self.assertTrue(wait_dead(child, 10))



class AiLimitsTests(ForgeCase):

    def test_script_flags_and_team_pump(self):
        limits = forge.ai_limits(sections(GREEN), "constructed")
        # Fiery Annihilation's script isn't flagged: it's only found out by playing.
        self.assertEqual(limits["cannot_play"], [])
        self.assertEqual(limits["team_pump"], {"copies": 3, "cards": [{"name": "Overrun", "qty": 2},
                                                                      {"name": "Rabbit Response", "qty": 1}]})
        self.assertEqual((limits["unknown"], limits["problem"], limits["commander_unplayable"]), ([], None, False))
        red = forge.ai_limits(sections(RED), "constructed")
        self.assertEqual(red["cannot_play"], [{"name": "Devout Decree", "qty": 1, "why": "script"}])
        self.assertIsNone(red["team_pump"])

    def test_two_pump_spells_arent_flagged(self):
        limits = forge.ai_limits(sections(GREEN.replace("2 Overrun", "1 Overrun")), "constructed")
        self.assertIsNone(limits["team_pump"])

    def test_the_commander(self):
        limits = forge.ai_limits(sections(GISA), "commander")
        self.assertEqual(limits["cannot_play"], [{"name": "Ghoulcaller Gisa", "qty": 1, "why": "script"}])
        self.assertTrue(limits["commander_unplayable"])

    def test_a_script_in_a_main_folder_beats_one_in_upcoming(self):
        # upcoming/grizzly_bears.txt (made up) is flagged; the real g/grizzly_bears.txt isn't.
        index = forge.install.script_index()
        self.assertEqual(index["names"]["grizzly bears"], "Grizzly Bears")
        self.assertNotIn("Grizzly Bears", index["remove_all"])
        self.assertEqual(index["names"]["swift end"], "Murderous Rider")
        self.assertEqual(index["names"]["fire"], "Fire // Ice")
        self.assertTrue((forge.common.DATA_DIR / "cardscripts-2.0.15.json").exists())

    def test_unknown_names(self):
        limits = forge.ai_limits(sections(RED + "2 Totally Fake Card\n"), "constructed")
        self.assertEqual(limits["unknown"], [{"name": "Totally Fake Card", "qty": 2}])

    def test_without_forge(self):
        self.settings["forge_dir"] = str(self.tmp / "nowhere")
        limits = forge.ai_limits(sections(GREEN), "constructed")
        self.assertEqual(limits["cannot_play"], [])
        self.assertEqual(limits["problem"], "Forge isn't installed at the folder config.json names, "
                                            "so the cards its AI can't play aren't known.")
        self.assertEqual(limits["team_pump"]["copies"], 3)

    def test_without_tags(self):
        with mock.patch.object(forge.ai, "TAG_FILE", self.tmp / "no-tags.jsonl"):
            limits = forge.ai_limits(sections(GREEN), "constructed")
        self.assertIsNone(limits["team_pump"])
        self.assertIn("oracle tags", limits["problem"])

    def test_never_cast_after_enough_games(self):
        a, b = entry(GREEN, "casual/green"), entry(RED, "casual/red")
        result = forge.run(a, b, 200, by="x", results_dir=self.results)
        side = [s["card_sha"] for s in result["sides"]].index(a["card_sha"])
        limits = forge.side_ai(result, side)
        self.assertEqual(limits["cannot_play"], [{"name": "Fiery Annihilation", "qty": 1, "why": "never_cast"}])
        other = forge.side_ai(result, 1 - side)
        self.assertEqual(other["cannot_play"], [{"name": "Devout Decree", "qty": 1, "why": "script"}])
        self.assertEqual(limits["games"], 200)
        # Under MIN_GAMES_NEVER_CAST games it isn't judged yet.
        result["batches"] = result["batches"][:1]
        with mock.patch.object(forge.ai, "MIN_GAMES_NEVER_CAST", 101):
            self.assertEqual(forge.side_ai(result, side)["cannot_play"], [])
        # The deck page's list_ai judges by the saved result's games too; a list with none has "games" 0.
        listed = forge.list_ai(sections(GREEN), "constructed", self.results)
        self.assertEqual((listed["cannot_play"], listed["games"]),
                         ([{"name": "Fiery Annihilation", "qty": 1, "why": "never_cast"}], 200))
        self.assertEqual(forge.ai_limits(sections(GREEN), "constructed")["games"], 0)
        alone = forge.list_ai(sections(GREEN.replace("4 Grizzly Bears", "3 Grizzly Bears")), "constructed", self.results)
        self.assertEqual((alone["cannot_play"], alone["games"]), ([], 0))

    def pooled(self, *results):
        """ai_limits() of GREEN over hand-made results."""
        return forge.ai_limits(sections(GREEN), "constructed", list(results))

    def green_result(self, games, casts, other_casts=None, sides=("green", "other"), key="c"):
        """A stored result (test_forge.stored) of games games with GREEN on the sides named "green", and
        no land plays: a land is left out for being one."""
        result = stored([(0, "win", i % 2) for i in range(games)], casts=[casts, other_casts or {}])
        result["batches"][0]["lands"] = [{}, {}]
        sha = forge.card_sha(sections(GREEN), "constructed")
        for side, who in zip(result["sides"], sides):
            side["card_sha"] = sha if who == "green" else "d" * 64
        result["key"] = key * 64
        return result

    def test_never_cast_is_judged_by_all_of_a_lists_games(self):
        spells = {"Llanowar Elves": [9, 5], "Grizzly Bears": [9, 6], "Overrun": [2, 2], "Rabbit Response": [1, 1],
                  "Glorious Anthem": [2, 2]}
        first = self.green_result(60, spells)
        # Under MIN_GAMES_NEVER_CAST games: nothing is judged never cast, and "games" says how many there are.
        limits = self.pooled(first)
        self.assertEqual((limits["cannot_play"], limits["games"]), ([], 60))
        # Two results add up (green is side 1 in this one); Giant Growth, cast only here, isn't flagged,
        # and Forest (a land, never cast) never is.
        second = self.green_result(50, {}, {"Giant Growth": [1, 1]}, sides=("other", "green"), key="e")
        limits = self.pooled(first, second)
        self.assertEqual(limits["cannot_play"], [{"name": "Fiery Annihilation", "qty": 1, "why": "never_cast"}])
        self.assertEqual(limits["games"], 110)
        # A result without this list adds nothing.
        elsewhere = self.green_result(500, {}, sides=("other", "other"), key="f")
        self.assertEqual(self.pooled(first, elsewhere)["games"], 60)
        # A card cast in any result isn't never cast.
        cast_once = self.green_result(1, {"Fiery Annihilation": [1, 1]}, key="9")
        limits = self.pooled(first, second, cast_once)
        self.assertEqual((limits["cannot_play"], limits["games"]), ([], 111))
        # No results: the card scripts only.
        self.assertEqual(self.pooled()["games"], 0)

    def test_a_mirror_counts_each_side_once(self):
        # 50 games of green against itself are 100 of green's games; casts on either side count.
        mirror = self.green_result(50, {"Llanowar Elves": [9, 5], "Grizzly Bears": [9, 6], "Overrun": [2, 2]},
                                   {"Rabbit Response": [1, 1], "Glorious Anthem": [2, 2], "Giant Growth": [1, 1]},
                                   sides=("green", "green"))
        limits = self.pooled(mirror)
        self.assertEqual(limits["games"], 100)
        self.assertEqual(limits["cannot_play"], [{"name": "Fiery Annihilation", "qty": 1, "why": "never_cast"}])
        with mock.patch.object(forge.ai, "MIN_GAMES_NEVER_CAST", 101):
            self.assertEqual(self.pooled(mirror)["cannot_play"], [])

    def test_the_card_script_index_is_rebuilt_when_forge_changes(self):
        folder = self.tmp / "forge"
        make_forge(folder)
        self.settings["forge_dir"] = str(folder)
        first = forge.install.script_index()
        cache = forge.common.DATA_DIR / "cardscripts-2.0.15.json"
        self.assertTrue(cache.exists())
        self.assertNotIn("totally new card", first["names"])
        builds = []
        real_build = forge.install._build_index

        def build(zip_path):
            builds.append(zip_path)
            return real_build(zip_path)

        with mock.patch.object(forge.install, "_build_index", build):
            forge.install._scripts.clear()              # a new process: read from the cache file
            self.assertEqual(forge.install.script_index()["names"], first["names"])
            self.assertEqual(builds, [])
            # Forge's update brings a new card script: cardsfolder.zip changes size and time.
            with zipfile.ZipFile(folder / forge.SCRIPTS_ZIP, "a") as z:
                z.writestr("t/totally_new_card.txt", "Name:Totally New Card\nManaCost:G\nTypes:Creature Bear\n"
                                                     "PT:2/2\nAI:RemoveDeck:All\n")
            index = forge.install.script_index()
            self.assertEqual(len(builds), 1)
            self.assertEqual(index["names"]["totally new card"], "Totally New Card")
            self.assertIn("Totally New Card", index["remove_all_set"])
            self.assertIn("Totally New Card", load_json(cache)["remove_all"])
            # Only its time changes: read again too.
            zip_path = folder / forge.SCRIPTS_ZIP
            stat = zip_path.stat()
            os.utime(zip_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
            forge.install.script_index()
            self.assertEqual(len(builds), 2)
            # A new Forge version gets an index of its own.
            (folder / "forge-gui-desktop-2.0.16-jar-with-dependencies.jar").write_bytes(b"")
            self.assertEqual(forge.install.script_index()["version"], "2.0.16")
            self.assertEqual(len(builds), 3)
        self.assertTrue((forge.common.DATA_DIR / "cardscripts-2.0.16.json").exists())



class HousekeepingTests(ForgeCase):

    def test_only_the_newest_failure_logs_are_kept(self):
        folder = forge.common.DATA_DIR / "logs"
        folder.mkdir(parents=True)
        extra = 5
        for i in range(forge.KEEP_FAILURE_LOGS + extra):
            path = folder / f"old{i:02}-seed{i}.log"
            path.write_text("x", encoding="utf-8")
            os.utime(path, (1_000_000 + i, 1_000_000 + i))
        batch = forge._Batch({"n": 0, "seed": 99, "deck1": 0, "games": 100})
        batch.error = "Forge stopped responding"
        batch.tail.extend(["line 1\n", "line 2\n"])
        forge._save_failure_log("k" * 64, batch)
        names = {p.name for p in folder.glob("*.log")}
        self.assertEqual(len(names), forge.KEEP_FAILURE_LOGS)
        oldest = {f"old{i:02}-seed{i}.log" for i in range(extra + 1)}       # 55 old + 1 new: 6 go
        self.assertEqual(names & oldest, set())
        self.assertIn(f"old{extra + 1:02}-seed{extra + 1}.log", names)
        self.assertEqual((folder / "kkkkkkkkkkkk-seed99.log").read_text(encoding="utf-8"),
                         "Forge stopped responding\n\nline 1\nline 2\n")

    def test_a_file_open_elsewhere_is_replaced_once_it_closes(self):
        path = self.tmp / "result.json"
        real_replace, tries = os.replace, []

        def replace(src, dst):
            tries.append(dst)
            if len(tries) < 3:
                raise PermissionError(13, "Access is denied")
            return real_replace(src, dst)

        with mock.patch.object(forge.common.os, "replace", replace), mock.patch.object(forge.common.time, "sleep") as sleep:
            forge.common._write_atomic(path, "new")
        self.assertEqual((path.read_text(encoding="utf-8"), len(tries), sleep.call_count), ("new", 3, 2))
        # Open the whole time: PermissionError, and no temporary file left behind.
        with mock.patch.object(forge.common.os, "replace", side_effect=PermissionError(13, "Access is denied")), \
                mock.patch.object(forge.common.time, "sleep") as sleep, self.assertRaises(PermissionError):
            forge.common._write_atomic(path, "newer")
        self.assertEqual(sleep.call_count, len(decks.REPLACE_WAITS))
        self.assertEqual((path.read_text(encoding="utf-8"), [p.name for p in self.tmp.glob("*.tmp")]), ("new", []))



if __name__ == "__main__":
    unittest.main()
