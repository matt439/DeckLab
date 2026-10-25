"""Forge pool service tests; shared fixtures remain in test_forge_pool."""
import unittest
import io
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from unittest import mock
from decklab.lib import api, config, forge
from decklab.lib.forge import pool, slots
from decklab.tests.test_forge import GREEN, RED, entry
from decklab.tests.test_forge_slots import wait_for
from decklab.tests.test_forge_pool import (
    PoolCase, setUpModule, tearDownModule,
)


class ServiceTests(PoolCase):
    """A pool and its service in this process, as the server has them; runs here find it
    through its file in the slots folder and play there (pool "remote")."""

    def service(self, **kwargs):
        own = self.pool_(**kwargs)
        own.service = pool._Service(own)
        self.addCleanup(own.service.close)
        return own

    def test_a_command_line_run_plays_in_the_servers_pool(self):
        own = self.service(name="server")
        self.fake("delay=0.05")
        state = json.loads((slots.folder() / f"forge-pool-{os.getpid()}.json").read_text(encoding="utf-8"))
        self.assertEqual((state["pid"], state["port"], state["checkout"], state["protocol"]),
                         (os.getpid(), own.service.port, str(config.REPO), pool.SERVICE_PROTOCOL))
        calls = []
        result = self.run_matchup(100, exact=True, progress=lambda done, total, detail: calls.append(done))
        run = result["runs"][0]
        self.assertEqual((run["pool"], run["played"], run["xmx"]), ("remote", 100, "1024m"))
        self.assertGreater(len(set(calls)), 2)                  # live progress, game by game
        self.assertEqual(own.status()["idle"], len(own.status()["workers"]))      # its workers stay warm
        local = self.run_matchup(100, exact=True, local=True, results_dir=self.tmp / "local")
        self.assertEqual(local["runs"][0]["pool"], "local")
        strip = lambda r: [{k: v for k, v in g.items() if k != "ms"} for g in r["batches"][0]["games"]]  # noqa: E731
        self.assertEqual(strip(local), strip(result))
        self.assertEqual(result["batches"][0]["cards"], local["batches"][0]["cards"])
        # Its status, through the service (the pool and status commands).
        self.assertEqual(pool.service_status(pool.services()[0])["name"], "server")

    def test_a_server_with_other_settings_is_passed_over_with_one_line(self):
        self.service()
        real = pool.identity

        def identity(setup, eng):           # the server's heap is another
            found = real(setup, eng)
            return dict(found, xmx="2048m") if threading.current_thread() is not threading.main_thread() else found

        logged = []
        with mock.patch.object(pool, "identity", identity), mock.patch.object(forge.common, "_log", logged.append):
            result = self.run_matchup(50, exact=True)
        self.assertEqual(result["runs"][0]["pool"], "local")
        self.assertEqual(logged, [pool.OTHER_SETTINGS.format(what="the Java heap (forge_xmx)")])

    def test_a_dead_servers_file_is_skipped_and_tidied(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        stale = slots.folder() / f"forge-pool-{dead.pid}.json"
        slots.folder().mkdir(parents=True, exist_ok=True)
        stale.write_text(json.dumps({"pid": dead.pid, "port": 1, "token": "x"}), encoding="utf-8")
        self.assertEqual(pool.services(), [])
        self.assertEqual(self.run_matchup(50, exact=True)["runs"][0]["pool"], "local")
        self.service()
        self.assertFalse(stale.exists())                        # the next service deleted it
        self.assertEqual(len(pool.services()), 1)

    def connect(self, own, job):
        found = pool.services()[0]
        connection = socket.create_connection(("127.0.0.1", found["port"]), timeout=10)
        self.addCleanup(connection.close)
        stream = connection.makefile("rwb")
        pool._send_line(stream, {"token": found["token"], "op": "submit",
                                 "identity": pool.identity(job["setup"], job["engine"]), "job": pool._wire(job)})
        answer = json.loads(stream.readline())
        self.assertEqual(answer["what"], "accepted", answer)
        return connection, stream

    def test_a_closed_connection_cancels_its_chunks(self):
        self.fake("delay=0.3")
        own = self.service(workers=2)
        connection, stream = self.connect(own, self.job(100))
        self.assertTrue(wait_for(lambda: own.status()["busy"] == 2, 10))
        connection.shutdown(socket.SHUT_RDWR)                   # the command line was killed
        stream.close()
        connection.close()
        self.assertTrue(wait_for(lambda: own.status()["busy"] == 0 and not own.status()["runs"], 10))
        self.assertEqual(own.status()["queued_games"], 0)

    def test_no_heartbeat_cancels_its_chunks(self):
        self.fake("delay=0.3")
        with mock.patch.object(pool, "HEARTBEAT_TIMEOUT_S", 1):
            own = self.service(workers=2)
            connection, stream = self.connect(own, self.job(100))
            self.assertTrue(wait_for(lambda: own.status()["busy"] == 2, 10))
            self.assertTrue(wait_for(lambda: not own.status()["runs"], 10))     # nothing heard for a second

    def test_a_stop_on_the_command_line_keeps_the_games_the_service_read(self):
        self.fake("delay=0.2")
        own = self.service(workers=2)
        placement = pool.place(self.job(100, batch=5))
        self.addCleanup(placement.close, 0)
        self.assertEqual(placement.where, "remote")
        ticket, events = placement.ticket, []
        while sum(1 for e in events if e[0] == "game") < 4:
            events.append(ticket.events.get(timeout=30))
        ticket.stop()
        while True:                         # what _play_v2 reads after its stop()
            try:
                events.append(ticket.events.get_nowait())
            except queue.Empty:
                break
        self.assertEqual(events[-1], ("done", "stopped"))
        self.assertNotIn("lost", [e[0] for e in events])
        # Every chunk that started ended, with the games it read.
        self.assertEqual({e[1] for e in events if e[0] == "start"}, {e[1] for e in events if e[0] == "end"})
        kept = sum(e[2]["kept"] for e in events if e[0] == "end")
        self.assertEqual(kept, sum(1 for e in events if e[0] == "game"))
        self.assertTrue(wait_for(lambda: not own.status()["runs"], 10))

    def test_the_service_sends_a_heartbeat_while_it_has_nothing_to_say(self):
        self.hold(4, 4)                                         # nothing can play
        with mock.patch.object(pool, "HEARTBEAT_S", 0.2):
            own = self.service()
            connection, stream = self.connect(own, self.job(20))
            said = [json.loads(stream.readline())["what"] for _ in range(4)]
        self.assertIn("heartbeat", said)

    def test_a_server_that_says_nothing_is_lost(self):
        with mock.patch.object(pool, "HEARTBEAT_TIMEOUT_S", 0.5), mock.patch.object(pool, "HEARTBEAT_S", 0.1):
            mine, theirs = socket.socketpair()
            self.addCleanup(theirs.close)
            ticket = pool._RemoteTicket(mine, mine.makefile("rwb"))
            self.addCleanup(ticket._close)
            end = time.monotonic() + 1.5
            while time.monotonic() < end:                       # its heartbeat keeps it
                theirs.sendall(b'{"what":"heartbeat"}\n')
                time.sleep(0.1)
            self.assertTrue(ticket.events.empty())
            begun = time.monotonic()
            self.assertEqual(ticket.events.get(timeout=5)[0], "lost")      # then silence
        self.assertLess(time.monotonic() - begun, 2)

    def test_the_server_going_away_mid_run_finishes_locally(self):
        self.fake("delay=0.02")
        own = self.service(name="server", workers=2)
        logged = []

        def progress(done, total, detail):
            if done >= 30 and own.service is not None:
                service, own.service = own.service, None
                service.close()
                own.close(0)                                    # the server stops

        with mock.patch.object(forge.common, "_log", logged.append):
            result = self.run_matchup(100, batch=5, progress=progress)
        self.assertIn(pool.LOST, logged)
        self.assertEqual(sorted(g["g"] for g in result["batches"][0]["games"]), list(range(100)))
        self.assertEqual((result["runs"][0]["pool"], result["runs"][0]["played"]), ("remote", 100))

    def test_bad_tokens_and_jobs_are_refused(self):
        own = self.service()
        found = pool.services()[0]
        for message in ({"token": "nope", "op": "status"}, {"op": "status"}):
            with socket.create_connection(("127.0.0.1", found["port"]), timeout=5) as connection:
                stream = connection.makefile("rwb")
                pool._send_line(stream, message)
                self.assertEqual(stream.readline(), b"")        # closed without a word
        job = self.job(10)
        with socket.create_connection(("127.0.0.1", found["port"]), timeout=5) as connection:
            stream = connection.makefile("rwb")
            wire = dict(pool._wire(job), dck=["../../etc.dck", "x.dck"])
            pool._send_line(stream, {"token": found["token"], "op": "submit",
                                     "identity": pool.identity(job["setup"], job["engine"]), "job": wire})
            answer = json.loads(stream.readline())
        self.assertEqual(answer["what"], "refused")
        self.assertFalse(own.status()["runs"])



class ServerPoolTests(PoolCase):

    def setUp(self):
        super().setUp()
        self.addCleanup(pool.stop_server_pool, 0)

    def test_the_server_starts_and_stops_its_pool_and_service(self):
        self.assertIsNone(pool.server_pool())
        own = pool.start_server_pool()
        self.assertIs(pool.start_server_pool(), own)
        self.assertIs(pool.server_pool(), own)
        self.assertEqual(forge.status()["pool"]["name"], "server")
        path = slots.folder() / f"forge-pool-{os.getpid()}.json"
        self.assertTrue(path.exists())
        result = self.run_matchup(50, exact=True)               # in the server: its pool, directly
        self.assertEqual(result["runs"][0]["pool"], "server")
        self.assertTrue(own.status()["workers"])                # warm until idle_s
        pool.stop_server_pool(0)
        self.assertIsNone(pool.server_pool())
        self.assertIsNone(forge.status()["pool"])
        self.assertFalse(path.exists())
        self.assertTrue(self.all_dead())

    def test_stopping_the_server_saves_its_runs_then_stops_the_pool(self):
        # server_run._serve's order: api.stop_jobs(), the matchups save (_wait_for_matchup), then the pool.
        from decklab import server  # noqa: F401 (runs build.start() before the server modules load)
        from decklab.lib import server_http, server_run
        self.fake("delay=1")
        pool.start_server_pool()
        runner_ = api._forge_runner()
        started = threading.Event()
        with mock.patch.object(api.forge_runs, "FORGE_JOBS", runner_), \
                mock.patch.object(api.practice, "JOBS", api._job_runner()), mock.patch.object(server_http, "log") as log:
            def run(progress):
                def report(done, total, detail):
                    if done:
                        started.set()
                    progress(done, total, detail)
                return self.run_matchup(40, batch=5, progress=report)

            job = runner_.submit("m", run)
            self.assertTrue(started.wait(30))
            begun = time.monotonic()
            api.stop_jobs()
            server_run._wait_for_matchup(10)
            self.assertTrue(job.wait(0))
            log.assert_called_once_with("Stopping the Forge matchups that are playing...")
            self.assertLess(time.monotonic() - begun, 3)         # saved without waiting for the workers
            server_run._stop_pool(0.5)
        run = self.saved()["runs"][0]
        self.assertTrue(run["stopped"])
        self.assertGreater(run["played"], 0)
        self.assertIsNone(pool.server_pool())
        self.assertTrue(self.all_dead())                         # no worker left alive

    def test_the_close_handler_kills_the_pools_workers_at_once(self):
        from decklab import server  # noqa: F401 (runs build.start() before the server modules load)
        from decklab.lib import server_run
        own = pool.start_server_pool()
        self.drain(own.submit(self.job(40)))
        self.assertTrue(own.status()["workers"])
        with mock.patch.object(api.forge_runs, "FORGE_JOBS", api._forge_runner()), \
                mock.patch.object(api.practice, "JOBS", api._job_runner()):
            self.assertIs(server_run._console_handler()(2), True)    # the window closing
        self.assertIsNone(pool.server_pool())
        self.assertTrue(self.all_dead())



class CommandLineTests(PoolCase):

    def run_main(self, *argv):
        """(exit code, stdout, stderr) of the command line."""
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n")
        err = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = forge.cli.main(list(argv))
            out.flush()
        return code, out.buffer.getvalue().decode("utf-8"), err.getvalue()

    def test_play_says_warm_workers_and_where(self):
        green = self.tmp / "green.dck"
        red = self.tmp / "red.dck"
        green.write_text(entry(GREEN)["dck"], encoding="utf-8")
        red.write_text(entry(RED)["dck"], encoding="utf-8")
        with pool.session(local=True) as s:
            with mock.patch.object(forge.cli, "run", lambda *a, **k: forge.run(*a, **dict(k, pool=s))):
                code, out, err = self.run_main("play", str(green), str(red), "--games", "200",
                                               "--results-dir", str(self.results))
                self.assertEqual(code, 0, err)
                self.assertIn(", in a pool of its own, slowest start-up ", out)
                code, out, err = self.run_main("play", str(green), str(red), "--games", "200",
                                               "--results-dir", str(self.results))
        self.assertEqual(code, 0, err)
        self.assertIn(", in a pool of its own, warm workers, 0 failed chunks;", out)
        self.assertNotIn("None", out)

    def test_play_local_and_the_fallback_said_once(self):
        self.fake("servefail")
        with mock.patch.object(forge.common, "_log"):
            code, out, err = self.run_main("play", str(self.dck(GREEN, "g")), str(self.dck(RED, "r")), "--games", "200",
                                           "--results-dir", str(self.results), "--local")
        self.assertEqual(code, 0, err)
        sentence = pool.FALLBACK.format(why=pool.FALLBACK_FAILED)
        self.assertEqual(err.count(sentence), 1)
        self.assertIn(f"  ! {sentence}", out)
        self.assertIn(", in a pool of its own, slowest start-up ", out)     # the one-shot processes'

        # One-shot processes none of which got as far as its header aren't warm workers.
        def run(*args, **kwargs):
            result = forge.run(*args, **kwargs)
            result["runs"][-1]["startup_s"] = None
            return result

        with mock.patch.object(forge.common, "_log"), mock.patch.object(forge.cli, "run", run):
            code, out, err = self.run_main("play", str(self.dck(GREEN, "g")), str(self.dck(RED, "r")), "--games", "200",
                                           "--results-dir", str(self.tmp / "again"), "--local")
        self.assertEqual(code, 0, err)
        self.assertIn(", in a pool of its own, cold processes, ", out)

    def dck(self, text, name):
        path = self.tmp / f"{name}.dck"
        path.write_text(entry(text)["dck"], encoding="utf-8")
        return path

    def test_the_pool_command(self):
        self.assertEqual(self.run_main("pool"), (0, forge.cli.NO_POOL + "\n", ""))
        self.assertEqual(self.run_main("pool", "--json"), (0, "[]\n", ""))
        own = pool.Pool(None, name="server", idle_s=30, workers=2)
        self.addCleanup(own.close, 0)
        own.service = pool._Service(own)
        self.addCleanup(own.service.close)
        own.submit(self.job(40))
        self.assertTrue(wait_for(lambda: own.status()["idle"] == 2, 20))
        code, out, _ = self.run_main("pool")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], f"The server's warm pool (process {os.getpid()}, checkout {config.REPO}):")
        self.assertEqual(lines[1], "  2 of 2 workers (0 playing, 2 idle, 0 starting)")
        self.assertRegex(lines[2], r"^  process \d+: idle, [\d,]+ games, heap 64 MB, idle \d+ s$")
        code, out, _ = self.run_main("pool", "--json")
        self.assertEqual(json.loads(out)[0]["status"]["name"], "server")
        self.assertTrue(forge.cli._pool_line().startswith(f"the server's (process {os.getpid()}): 2 of 2 workers"))



if __name__ == "__main__":
    unittest.main()
