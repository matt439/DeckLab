"""Server lifecycle tests; shared fixtures remain in test_server."""
import unittest
import contextlib
import errno
import http.client
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock
from decklab import server
from decklab.lib import api, config, control, server_http, server_run
from decklab.lib.forge import overrides as forge_overrides
from decklab.lib.forge import pool as forge_pool
from decklab.lib.forge import slots as forge_slots
from decklab.lib.state import EXPLICIT_ENV
from decklab.tests.test_control import NO_WINDOW, WINDOWS, free_port, now_iso, sleeper, wait_until
from decklab.tests.test_server import REAL_LOG

if WINDOWS:
    from decklab.tests.test_control import send_message, user32


class CtrlCTests(unittest.TestCase):

    def test_ctrl_c_stops_the_job_runner_at_once_and_python_goes_on(self):
        # Review finding: the runner only heard of Ctrl+C at serve_forever's next poll, after the
        # workers had died, so it logged the broken run and started the next one.
        calls = []
        handler = server_run.ctrl_handler(lambda: calls.append("stop"), lambda seconds: calls.append(("wait", seconds)),
                                      lambda: calls.append("interrupt"))
        self.assertIs(handler(0), False)                # Ctrl+C: stop, then Python's KeyboardInterrupt
        self.assertEqual(calls, ["stop"])
        self.assertIs(handler(5), False)                # a logoff: not ours
        self.assertIs(handler(7), False)
        self.assertEqual(calls, ["stop"])

    def test_ctrl_break_ends_the_server_like_ctrl_c(self):
        # Review finding API-1: Python has no Ctrl+Break handler, so the C runtime ended the
        # process at once and a matchup playing lost every game. Now it's a KeyboardInterrupt.
        calls = []
        handler = server_run.ctrl_handler(lambda: calls.append("stop"), lambda seconds: calls.append(("wait", seconds)),
                                      lambda: calls.append("interrupt"))
        self.assertIs(handler(1), True)
        self.assertEqual(calls, ["stop", "interrupt"])
        with mock.patch.object(server_run._thread, "interrupt_main") as interrupt, \
                mock.patch.object(api, "stop_jobs") as stop:
            self.assertIs(server_run._console_handler()(1), True)
        stop.assert_called_once_with()
        interrupt.assert_called_once_with()

    def test_closing_the_window_waits_for_the_matchup_to_save(self):
        # Review finding API-1: Windows ends the process as soon as the handler returns after
        # the window closes (or a shutdown), so the handler waits there for the matchup to
        # stop its Forge processes and save its games, up to CLOSE_WAIT seconds.
        self.assertLess(server_run.CLOSE_WAIT, 5)       # Windows' limit after the window closes
        practice, matchups = api._job_runner(), api._forge_runner()
        started, saved = threading.Event(), []

        def forge_run(progress):
            progress(0, 800, {"wins": [0, 0]})
            started.set()
            while True:
                try:
                    progress(100, 800, {"wins": [60, 40]})
                except Exception:
                    time.sleep(0.3)                     # killing Forge and writing the result
                    saved.append("every finished game")
                    raise
                time.sleep(0.01)

        for event in (2, 6):                            # the window closing, a shutdown
            with self.subTest(event=event), mock.patch.object(api.practice, "JOBS", practice), \
                    mock.patch.object(api.forge_runs, "FORGE_JOBS", matchups), \
                    mock.patch.object(server_run._thread, "interrupt_main") as interrupt:
                job = matchups.submit(f"m{event}", forge_run)
                self.assertTrue(started.wait(5))
                self.assertIs(server_run._console_handler()(event), True)
                # It returned only once the run had saved its games.
                self.assertEqual(saved, ["every finished game"])
                self.assertTrue(job.wait(0))
                self.assertEqual(matchups.snapshot(job)["error"], "stopped")
                interrupt.assert_not_called()
                practice, matchups = api._job_runner(), api._forge_runner()
                started.clear()
                saved.clear()

    def test_closing_the_window_kills_the_warm_pools_workers_once_the_matchups_saved(self):
        # Windows ends the process moments after the handler returns: the matchups save first
        # (FORGE_JOBS.join), then the warm pool's workers are killed at once (_stop_pool(0)).
        calls = []

        class Runner:
            def join(self, seconds):
                calls.append(("join", seconds))

        with mock.patch.object(api, "stop_jobs", lambda: calls.append("stop jobs")), \
                mock.patch.object(api.forge_runs, "FORGE_JOBS", Runner()), \
                mock.patch.object(server_run, "_stop_pool", lambda wait=None: calls.append(("stop pool", wait))):
            self.assertIs(server_run._console_handler()(2), True)
            self.assertEqual(calls, ["stop jobs", ("join", server_run.CLOSE_WAIT), ("stop pool", 0)])
            del calls[:]
            self.assertIs(server_run._console_handler()(0), False)  # Ctrl+C: main() stops the pool
            self.assertEqual(calls, ["stop jobs"])

    def test_the_pool_helpers_survive_forge_failing(self):
        logged = []
        with mock.patch.object(server_http, "log", logged.append):
            with mock.patch.dict(sys.modules, {"decklab.lib.forge": None}):
                server_run._start_pool()                # the Forge code can't be loaded: logged
                server_run._stop_pool(0)                # never loaded: nothing to stop
            with mock.patch.object(forge_pool, "stop_server_pool", side_effect=RuntimeError("a bug")):
                server_run._stop_pool(0)
        self.assertEqual(len(logged), 2)
        self.assertIn("The warm pool for Forge matchups couldn't start", logged[0])
        self.assertIn("The warm pool didn't stop cleanly", logged[1])

    def test_a_handler_that_fails_still_waits(self):
        # An exception would leave the ctypes callback returning False at once.
        calls = []

        def stop():
            raise OSError("the console is gone")

        handler = server_run.ctrl_handler(stop, lambda seconds: calls.append(("wait", seconds)), None)
        self.assertIs(handler(2), True)
        self.assertEqual(calls, [("wait", server_run.CLOSE_WAIT)])

    def test_closing_the_window_is_a_stop_on_purpose(self):
        # Review finding (E11-S26): Windows ends the process after the handler, so _serve's
        # finally never wrote the marker, and the watchdog started the background server
        # again. The window's close writes it; a shutdown doesn't (the next logon starts it).
        calls = []
        handler = server_run.ctrl_handler(lambda: calls.append("stop"), lambda seconds: calls.append("wait"),
                                          None, lambda: calls.append("closed"))
        self.assertIs(handler(server_run.CTRL_CLOSE), True)
        self.assertEqual(calls, ["stop", "closed", "wait"])
        calls.clear()
        for event in (server_run.CTRL_SHUTDOWN, server_run.CTRL_C, server_run.CTRL_BREAK):
            handler(event)
        self.assertNotIn("closed", calls)
        with mock.patch.object(api, "stop_jobs"), mock.patch.object(server_run, "_join_runs"), \
                mock.patch.object(server_run, "_stop_pool"), \
                mock.patch.object(control, "mark_stopped") as mark:
            server_run._console_handler(50003)(server_run.CTRL_CLOSE)
            server_run._console_handler(50003)(server_run.CTRL_SHUTDOWN)
            server_run._console_handler()(server_run.CTRL_CLOSE)          # no port: nothing to write
        mark.assert_called_once_with(50003, "window closed", keep=True)

    def test_stopping_stops_both_runners_and_waits_for_the_matchup(self):
        # A matchup kills its Forge processes and saves what it finished at its next report,
        # so the server waits for that before it exits.
        practice, matchups = api._job_runner(), api._forge_runner()
        started, go, saved = threading.Event(), threading.Event(), []

        def forge_run(progress):
            progress(100, 800, {"wins": [60, 40]})
            started.set()
            go.wait(5)
            try:
                progress(200, 800, {"wins": [120, 80]})
            except Exception:
                saved.append("the finished batches")
                raise

        with mock.patch.object(api.practice, "JOBS", practice), \
                mock.patch.object(api.forge_runs, "FORGE_JOBS", matchups), \
                mock.patch.object(server_http, "log", lambda text: None):
            job = matchups.submit("m", forge_run)
            self.assertTrue(started.wait(5))
            api.stop_jobs()
            self.assertTrue(practice._stopping.is_set() and matchups._stopping.is_set())
            threading.Timer(0.1, go.set).start()
            server_run._wait_for_matchup(5)
            self.assertTrue(job.wait(0))
            self.assertEqual(saved, ["the finished batches"])
            server_run._wait_for_matchup(5)             # nothing playing: returns at once



@unittest.skipUnless(WINDOWS, "SO_EXCLUSIVEADDRUSE is a Windows option")
class ExclusivePortTests(unittest.TestCase):
    """Two servers can't share a port on different addresses (the logon
    server on 0.0.0.0, a second one started by hand with --host 127.0.0.1).
    The 0.0.0.0 sockets here are bound but never listen (server_activate is
    skipped), so Windows Firewall never asks about python.exe."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def bound(self, host, port):
        """A Server bound to (host, port) that never listens."""
        with mock.patch.object(server_http.Server, "server_activate", lambda httpd: None):
            httpd = server_http.Server((host, port), self.dir)
        self.addCleanup(httpd.server_close)
        return httpd

    def listening(self, port=0):
        httpd = server_http.make_server("127.0.0.1", port, web_dir=self.dir)
        self.addCleanup(httpd.server_close)
        return httpd

    def test_the_port_is_taken_for_exclusive_use(self):
        httpd = self.listening()
        self.assertEqual(httpd.socket.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE), 1)

    def test_all_interfaces_first_then_one_address(self):
        port = free_port()
        self.bound("0.0.0.0", port)
        with self.assertRaises(OSError) as caught:
            self.listening(port)
        self.assertEqual(caught.exception.winerror, 10013)
        self.assertTrue(server_run._port_in_use(caught.exception))

    def test_one_address_first_then_all_interfaces(self):
        port = self.listening().server_address[1]
        with self.assertRaises(OSError) as caught:
            self.bound("0.0.0.0", port)
        self.assertEqual(caught.exception.winerror, 10048)
        self.assertTrue(server_run._port_in_use(caught.exception))

    def test_a_restart_gets_the_port_back_with_connections_in_time_wait(self):
        httpd = self.listening()
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        with mock.patch.object(server_http, "log", lambda text: None):
            for _ in range(3):                  # the server closes these, so they wait on its port
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                conn.request("GET", "/nope", headers={"Connection": "close"})
                conn.getresponse().read()
                conn.close()
            httpd.shutdown()
        thread.join(5)
        httpd.server_close()
        self.assertEqual(self.listening(port).server_address[1], port)



class PortInUseTests(unittest.TestCase):

    def test_only_a_port_in_use_counts(self):
        if WINDOWS:
            for winerror, in_use in ((10048, True), (10013, True), (10049, False), (10022, False)):
                with self.subTest(winerror=winerror):
                    self.assertIs(server_run._port_in_use(OSError(0, "bind", None, winerror)), in_use)
            self.assertFalse(server_run._port_in_use(OSError(13, "not a socket's error")))
        with mock.patch.object(server_run.sys, "platform", "linux"):
            self.assertTrue(server_run._port_in_use(OSError(errno.EADDRINUSE, "in use")))
            self.assertTrue(server_run._port_in_use(OSError(errno.EACCES, "denied")))
            self.assertFalse(server_run._port_in_use(OSError(errno.EADDRNOTAVAIL, "no such address")))
        self.assertFalse(server_run._port_in_use(OverflowError("port must be 0-65535")))



class MainTests(unittest.TestCase):
    """main() itself, in a thread: started, stopped through its stop event,
    logging to a file, a port in use, --stop. The state and log files, the
    config and both job runners are temp ones; the card data isn't loaded."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.state_file = self.dir / "server.json"
        self.config_file = self.dir / "config.json"
        self.config_file.write_text('{"profiles": []}', encoding="utf-8")
        self.log = []
        self.database_check = mock.Mock()
        self.loaded = threading.Event()
        for target, name, value in (
                (control, "STATE_FILE", self.state_file),
                (control, "LOG_FILE", self.dir / "logs" / "server.log"),
                (config, "CONFIG_FILE", self.config_file),
                (server_http, "log", self.log.append),
                (server_run, "_load_index", self.loaded.set),
                (server_run, "_update_loop", self.loaded.set),
                (server_run, "_database_check", self.database_check),
                (server_run, "_stop_jobs_on_ctrl_c", lambda port=None: None),
                # _start_pool deploys the adopted card-script overrides into the real data folder.
                (forge_overrides, "ensure_deployed", lambda user_dir: None),
                (api.practice, "JOBS", api._job_runner()),
                (api.forge_runs, "FORGE_JOBS", api._forge_runner())):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def run_main(self, *argv):
        """main(argv) in a thread: (thread, {"code": its exit code once it returns})."""
        result = {}
        thread = threading.Thread(target=lambda: result.setdefault("code", server.main(list(argv))), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        return thread, result

    def wait_for_state(self):
        self.assertTrue(wait_until(lambda: control.read_state(self.state_file) is not None), self.log)
        return control.read_state(self.state_file)

    def get(self, port, path):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_the_server_is_closed_when_serving_fails(self):
        httpd = mock.Mock(server_address=("127.0.0.1", 12345))
        httpd.serve_forever.side_effect = RuntimeError("serving failed")
        with mock.patch.object(server_http, "make_server", return_value=httpd), \
                mock.patch.object(server_run, "_start", return_value=None), \
                mock.patch.object(control, "clear_state") as clear_state:
            self.assertEqual(server.main(["--host", "127.0.0.1", "--port", "12345", "--no-update"]), 1)
        httpd.server_close.assert_called_once_with()
        clear_state.assert_called_once_with(os.getpid())

    @unittest.skipUnless(WINDOWS, "stopping without a window is Windows only")
    def test_a_stop_request_ends_main_and_clears_the_state_file(self):
        thread, result = self.run_main("--host", "127.0.0.1", "--port", "0", "--no-update")
        state = self.wait_for_state()
        port = state["port"]
        self.assertEqual({k: v for k, v in state.items() if k != "started"},
                         {"version": 1, "pid": os.getpid(), "host": "127.0.0.1", "port": port,
                          "python": sys.executable, "log": None, "background": False})
        self.assertLessEqual(abs(control._timestamp(state["started"]) - time.time()), 60)
        self.assertTrue(self.loaded.wait(5))                # --no-update: only the index is loaded
        self.assertEqual(self.get(port, "/api/nope")[0], 404)
        self.assertRegex(self.log[0], rf"^\d{{4}}-\d\d-\d\d \d\d:\d\d:\d\d Deck Lab: http://127\.0\.0\.1:{port}/  "
                                      rf"\(listening on 127\.0\.0\.1:{port}; Ctrl\+C stops it\)$")
        self.assertEqual(control.request_stop(port, wait=20), "stopped")
        thread.join(10)
        self.assertEqual(result, {"code": 0})
        self.assertFalse(self.state_file.exists())
        self.assertTrue(any(line.endswith(" Stop requested.") for line in self.log), self.log)
        self.assertTrue(self.log[-1].endswith(" Deck Lab has stopped."), self.log)
        self.assertEqual(control.request_stop(port, wait=1), "not running")
        self.assertTrue(api.practice.JOBS.stopping and api.forge_runs.FORGE_JOBS.stopping)

    @unittest.skipUnless(WINDOWS, "stopping without a window is Windows only")
    def test_listening_clears_the_stop_marker_and_a_stop_request_leaves_one(self):
        # E11-S26: running again ends an earlier stop on purpose (the logon trigger's start, say),
        # and a stop request leaves a marker, so the watchdog keeps it off.
        port = free_port()
        control.mark_stopped(port, "homenet stop")
        thread, result = self.run_main("--host", "127.0.0.1", "--port", str(port), "--no-update")
        self.wait_for_state()
        self.assertTrue(wait_until(lambda: control.read_stopped(port) is None), self.log)
        self.assertEqual(control.request_stop(port, wait=20), "stopped")
        thread.join(10)
        self.assertEqual(result, {"code": 0})
        self.assertEqual(control.read_stopped(port)["by"], "stop request")
        self.assertEqual(control.stop_marker_path(port).parent, self.dir)       # beside the temp state file

    @unittest.skipUnless(WINDOWS, "stopping without a window is Windows only")
    def test_the_warm_pool_starts_with_the_server_and_stops_after_its_matchups(self):
        # Its pool and service start with the server; when it stops, the matchups stop and save
        # first (_wait_for_matchup), and only then does the pool stop.
        calls = []
        real_start, real_stop = server_run._start_pool, server_run._stop_pool

        def stop_pool(wait=server_run.POOL_STOP_WAIT):
            calls.append(("stop pool", wait, forge_pool.server_pool() is not None))
            real_stop(wait)

        with mock.patch.object(server_run, "_start_pool", lambda: (calls.append("start pool"), real_start())), \
                mock.patch.object(server_run, "_wait_for_matchup", lambda wait=None: calls.append("matchups saved")), \
                mock.patch.object(server_run, "_stop_pool", stop_pool):
            thread, result = self.run_main("--host", "127.0.0.1", "--port", "0", "--no-update")
            state = self.wait_for_state()
            self.assertTrue(wait_until(lambda: forge_pool.server_pool() is not None))
            service = forge_slots.folder() / f"forge-pool-{os.getpid()}.json"
            self.assertTrue(service.exists())
            self.assertEqual(forge_pool.service_status(forge_pool.services()[0])["name"], "server")
            self.assertEqual(control.request_stop(state["port"], wait=20), "stopped")
            thread.join(10)
        self.assertEqual(result, {"code": 0})
        self.assertEqual(calls, ["start pool", "matchups saved", ("stop pool", server_run.POOL_STOP_WAIT, True)])
        self.assertIsNone(forge_pool.server_pool())
        self.assertFalse(service.exists())

    @unittest.skipUnless(WINDOWS, "stopping without a window is Windows only")
    def test_another_running_server_keeps_its_state_file(self):
        child = sleeper(self)
        theirs = {"version": 1, "pid": child.pid, "host": "0.0.0.0", "port": 1, "started": now_iso()}
        control.write_state(theirs, self.state_file)
        thread, result = self.run_main("--host", "127.0.0.1", "--port", "0", "--no-update")
        self.assertTrue(wait_until(lambda: any("isn't recorded" in line for line in self.log)), self.log)
        port = int(re.search(r"http://127\.0\.0\.1:(\d+)/", self.log[0])[1])
        self.assertEqual(control.request_stop(port, wait=20), "stopped")
        thread.join(10)
        self.assertEqual(result, {"code": 0})
        self.assertEqual(json.loads(self.state_file.read_text(encoding="utf-8")), theirs)

    def test_a_port_in_use(self):
        httpd = server_http.make_server("127.0.0.1", 0, web_dir=self.dir)
        self.addCleanup(httpd.server_close)
        port = httpd.server_address[1]
        argv = ["--host", "127.0.0.1", "--port", str(port), "--no-update"]
        self.assertEqual(server.main(argv), 1)
        self.assertTrue(self.log[-1].startswith(f"Can't listen on 127.0.0.1:{port}: "), self.log)
        # The state file says a Deck Lab server is there: say which, and how to stop it.
        control.write_state({"version": 1, "pid": os.getpid(), "port": port, "started": now_iso()},
                            self.state_file)
        self.assertEqual(server.main(argv), 1)
        self.assertRegex(self.log[-1], rf"^Deck Lab is already running \(process {os.getpid()}, started "
                                       rf"\d{{4}}-\d\d-\d\d \d\d:\d\d\)\. Stop it with: "
                                       rf"python decklab/server\.py --port {port} --stop$")
        # On the configured port, homenet stops it.
        self.config_file.write_text(json.dumps({"port": port}), encoding="utf-8")
        self.assertEqual(server.main(argv[:2] + ["--no-update"]), 1)
        self.assertTrue(self.log[-1].endswith("Stop it with: python -m decklab.lib.homenet stop"), self.log[-1])
        # A state file for another port isn't this one.
        control.write_state({"version": 1, "pid": os.getpid(), "port": port + 1, "started": now_iso()},
                            self.state_file)
        self.assertEqual(server.main(argv), 1)
        self.assertTrue(self.log[-1].startswith("Can't listen on"), self.log[-1])
        self.assertTrue(self.state_file.exists())           # never removed by a server that didn't start

    def test_a_bad_address_isnt_taken_for_a_running_server(self):
        # A server is recorded on the port, but this bind failed for another
        # reason (an address this PC doesn't have): say so, not "already running".
        port = free_port()
        control.write_state({"version": 1, "pid": os.getpid(), "port": port, "started": now_iso()},
                            self.state_file)
        self.assertEqual(server.main(["--host", "10.255.255.1", "--port", str(port), "--no-update"]), 1)
        self.assertTrue(self.log[-1].startswith(f"Can't listen on 10.255.255.1:{port}: "), self.log)
        self.assertNotIn("already running", self.log[-1])

    @unittest.skipUnless(WINDOWS, "stopping without a window is Windows only")
    def test_it_can_be_stopped_before_the_state_file_names_it(self):
        # Whatever sees the state file can stop the server at once: its stop
        # event and session-end window already exist when the file is written.
        order, real = [], (control.listen_for_stop, control.watch_session_end, control.write_state)

        def listen(port, on_stop):
            order.append("stop event")
            return real[0](port, on_stop)

        def watch(*args):
            watcher = real[1](*args)
            order.append("window")
            self.titles.append(watcher.title)
            return watcher

        def write(state, path=None):
            order.append(("state file", control._event_exists(control.stop_event_name(state["port"])),
                          bool(self.titles and user32.FindWindowW(control.WINDOW_CLASS, self.titles[-1]))))
            return real[2](state, path)

        self.titles = []
        with mock.patch.object(control, "listen_for_stop", listen), \
                mock.patch.object(control, "watch_session_end", watch), \
                mock.patch.object(control, "write_state", write):
            thread, result = self.run_main("--host", "127.0.0.1", "--port", "0", "--no-update")
            state = self.wait_for_state()
            self.assertEqual(order, ["stop event", "window", ("state file", True, True)])
            self.assertEqual(control.request_stop(state["port"], wait=20), "stopped")
            thread.join(10)
        self.assertEqual(result, {"code": 0})

    @unittest.skipUnless(WINDOWS, "the session-end window is Windows only")
    def test_asked_to_close_it_stops_as_for_a_stop_request(self):
        # taskkill /PID without /F: WM_CLOSE to the hidden window.
        watchers, watch = [], control.watch_session_end

        def remember(*args):
            watchers.append(watch(*args))
            return watchers[-1]

        with mock.patch.object(control, "watch_session_end", remember):
            thread, result = self.run_main("--host", "127.0.0.1", "--port", "0", "--no-update")
            state = self.wait_for_state()
        self.assertEqual(send_message(watchers[0].hwnd, 0x0010, 0), 0)          # WM_CLOSE
        thread.join(20)
        self.assertEqual(result, {"code": 0})
        self.assertTrue(any(line.endswith(" Asked to close (taskkill): stopping.") for line in self.log), self.log)
        self.assertTrue(self.log[-1].endswith(" Deck Lab has stopped."), self.log)
        self.assertFalse(self.state_file.exists())
        self.assertFalse(user32.FindWindowW(control.WINDOW_CLASS, watchers[0].title))     # closed on the way out
        self.assertEqual(control.request_stop(state["port"], wait=1), "not running")
        self.assertEqual(control.read_stopped(state["port"])["by"], "taskkill")      # on purpose (E11-S26)

    def test_stop_option(self):
        for result, code, words in (("stopped", 0, "Deck Lab (port 9) has stopped."),
                                    ("not running", 0, "Deck Lab isn't running on port 9."),
                                    ("timeout", 1, "still running after 30 seconds"),
                                    ("unsupported", 1, "can't be stopped from here" if WINDOWS else "Ctrl+C")):
            with self.subTest(result=result), \
                    mock.patch.object(control, "request_stop", return_value=result) as request, \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(server.main(["--port", "9", "--stop"]), code)
                request.assert_called_once_with(9)
                self.assertIn(words, out.getvalue())
        # The port comes from config.json when --port isn't given.
        self.config_file.write_text('{"port": 9}', encoding="utf-8")
        with mock.patch.object(control, "request_stop", return_value="stopped") as request, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(server.main(["--stop"]), 0)
        request.assert_called_once_with(9)

    def test_stop_option_with_a_config_that_cant_be_read(self):
        # A typo made in config.json while the server runs mustn't keep it from being stopped.
        for text in ("{nope", "[1]", '"text"'):
            with self.subTest(config=text), \
                    mock.patch.object(control, "request_stop", return_value="stopped") as request, \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                self.config_file.write_text(text, encoding="utf-8")
                self.assertEqual(server.main(["--port", "9", "--stop"]), 0)        # --port: config isn't needed
                request.assert_called_once_with(9)
                self.assertEqual(out.getvalue(), "Deck Lab (port 9) has stopped.\n")
                request.reset_mock()
                del self.log[:]
                self.assertEqual(server.main(["--stop"]), 1)
                request.assert_not_called()
                self.assertEqual(len(self.log), 1, self.log)
                self.assertTrue(self.log[0].startswith("decklab/config.json can't be read ("), self.log)
                self.assertIn("Pass it with --port: python decklab/server.py --port 8642 --stop", self.log[0])
                self.assertNotIn("Traceback", self.log[0])

    @unittest.skipUnless(WINDOWS, "the stop event is Windows only")
    def test_stop_option_with_nothing_running(self):
        port = free_port()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(server.main(["--port", str(port), "--stop"]), 0)
        self.assertEqual(out.getvalue(), f"Deck Lab isn't running on port {port}.\n")

    @unittest.skipUnless(WINDOWS, "stopping without a window is Windows only")
    def test_log_option_takes_everything_and_gives_the_console_back(self):
        log_file = self.dir / "out" / "deck.log"
        console = sys.stderr

        def crash():
            raise RuntimeError("card data thread boom")

        with mock.patch.object(server_http, "log", REAL_LOG), mock.patch.object(server_run, "_load_index", crash), \
                contextlib.redirect_stderr(io.StringIO()) as before:
            thread, result = self.run_main("--host", "127.0.0.1", "--port", "0", "--no-update",
                                           "--log", str(log_file))
            state = self.wait_for_state()
            self.assertEqual(before.getvalue(), f"Deck Lab's log: {log_file}\n")    # said once, on the console
            self.assertEqual((state["log"], state["background"]), (str(log_file), False))

            def logged(words):
                return wait_until(lambda: log_file.exists() and words in log_file.read_text(encoding="utf-8"))

            self.assertTrue(logged(f"Deck Lab: http://127.0.0.1:{state['port']}/"))
            # An exception in a thread (threading.excepthook writes to sys.stderr: the file).
            self.assertTrue(logged("RuntimeError: card data thread boom"))
            self.assertEqual(self.get(state["port"], "/api/nope")[0], 404)
            self.assertTrue(logged("GET /api/nope 404"))
            self.assertEqual(control.request_stop(state["port"], wait=20), "stopped")
            thread.join(10)
            self.assertEqual(result, {"code": 0})
            self.assertIs(sys.stderr, before)                   # the console's stream is back
        self.assertIs(sys.stderr, console)
        self.assertTrue(log_file.read_text(encoding="utf-8").rstrip().endswith("Deck Lab has stopped."))

    def test_a_crash_at_start_up_without_a_console_is_logged(self):
        # pythonw: no sys.stderr, so main() logs to control.LOG_FILE and leaves it there.
        with mock.patch.object(sys, "stderr", None), mock.patch.object(sys, "stdout", None), \
                mock.patch.object(server_http, "log", REAL_LOG), \
                mock.patch.object(server_http, "make_server", side_effect=RuntimeError("start-up boom")):
            code = server.main(["--host", "127.0.0.1", "--port", "0", "--no-update"])
            stream = sys.stderr
        stream.close()
        self.assertEqual(code, 1)
        self.assertIsInstance(stream, control.LogFile)
        text = (self.dir / "logs" / "server.log").read_text(encoding="utf-8")
        self.assertIn(" Deck Lab stopped with an error:\nTraceback", text)
        self.assertIn("RuntimeError: start-up boom", text)

    def test_a_bad_config_without_a_console_is_logged(self):
        self.config_file.write_text("{nope", encoding="utf-8")
        with mock.patch.object(sys, "stderr", None), mock.patch.object(sys, "stdout", None), \
                mock.patch.object(server_http, "log", REAL_LOG):
            code = server.main(["--port", "0"])
            stream = sys.stderr
        stream.close()
        self.assertEqual(code, 1)
        self.assertIn("JSONDecodeError", (self.dir / "logs" / "server.log").read_text(encoding="utf-8"))

    def test_the_stop_handler(self):
        fake = mock.Mock()
        with mock.patch.object(api, "stop_jobs") as stop:
            server_run._stop_handler(fake)()
        stop.assert_called_once_with()
        fake.shutdown.assert_called_once_with()
        self.assertTrue(self.log[-1].endswith(" Stop requested."))
        with mock.patch.object(api, "stop_jobs") as stop:
            server_run._stop_handler(fake, "Asked to close (taskkill): stopping.")()
        stop.assert_called_once_with()
        self.assertTrue(self.log[-1].endswith(" Asked to close (taskkill): stopping."))

    def test_the_session_end_handler_waits_for_the_matchup_then_for_main(self):
        # Windows ends the process soon after on_end returns, so it waits for the
        # matchup to save its games (as closing the window does), then for main().
        started, saved, finished = threading.Event(), [], threading.Event()

        def forge_run(progress):
            progress(0, 800, {"wins": [0, 0]})
            started.set()
            while True:
                try:
                    progress(100, 800, {"wins": [60, 40]})
                except Exception:
                    time.sleep(0.3)                     # killing Forge and writing the result
                    saved.append("every finished game")
                    raise
                time.sleep(0.01)

        fake = mock.Mock()
        fake.shutdown.side_effect = lambda: threading.Timer(0.2, finished.set).start()     # main() finishing
        job = api.forge_runs.FORGE_JOBS.submit("m", forge_run)
        self.assertTrue(started.wait(5))
        begun = time.monotonic()
        stops = []
        real_stop = server_run._stop_pool

        def stop_pool(wait=None):
            stops.append((wait, list(saved)))       # the warm pool goes once the matchup has saved
            real_stop(wait)

        with mock.patch.object(server_run, "_stop_pool", stop_pool):
            server_run._session_end_handler(fake, finished)()
        self.assertEqual(stops, [(0, ["every finished game"])])
        self.assertLess(time.monotonic() - begun, server_run.CLOSE_WAIT)
        self.assertEqual(saved, ["every finished game"])
        self.assertTrue(job.wait(0))
        fake.shutdown.assert_called_once_with()
        self.assertTrue(finished.is_set())
        self.assertTrue(api.practice.JOBS.stopping)
        self.assertIn("logging off or shutting down", self.log[-1])
        # It never waits past CLOSE_WAIT, even if main() never finishes.
        with mock.patch.object(server_run, "CLOSE_WAIT", 0.3):
            begun = time.monotonic()
            server_run._session_end_handler(mock.Mock(), threading.Event())()
            self.assertLess(time.monotonic() - begun, 1.5)

    def test_the_database_check_runs_between_the_url_line_and_has_stopped(self):
        # Started after the URL line (with background False: this server has a console) and
        # stopped first thing on the way out (before the server closes, so its first check
        # can't sync profiles after that), whether serving ends normally or fails.
        for failure in (KeyboardInterrupt(), RuntimeError("serving failed")):
            with self.subTest(failure=type(failure).__name__):
                self.log.clear()
                seen = {}

                def stopped():
                    seen["at stop"] = list(self.log)
                    seen["closed at stop"] = httpd.server_close.called
                stop = mock.Mock(side_effect=stopped)

                def check(background):
                    seen["at start"] = list(self.log)
                    return stop
                self.database_check.reset_mock()
                self.database_check.side_effect = check
                httpd = mock.Mock(server_address=("127.0.0.1", 12345))
                httpd.serve_forever.side_effect = failure
                with mock.patch.object(server_http, "make_server", return_value=httpd), \
                        mock.patch.object(server_run, "_start", return_value=None), \
                        mock.patch.object(control, "clear_state"):
                    server.main(["--host", "127.0.0.1", "--port", "12345", "--no-update"])
                self.database_check.assert_called_once_with(False)
                stop.assert_called_once_with()
                self.assertIn(" Deck Lab: http://127.0.0.1:12345/", seen["at start"][-1])
                self.assertFalse(any("has stopped" in line for line in seen["at stop"]), seen["at stop"])
                self.assertFalse(seen["closed at stop"])

    def test_the_database_check_stops_even_when_shutting_down_fails(self):
        stop = mock.Mock()
        self.database_check.reset_mock()
        self.database_check.side_effect = lambda background: stop
        httpd = mock.Mock(server_address=("127.0.0.1", 12345))
        httpd.serve_forever.side_effect = KeyboardInterrupt()
        with mock.patch.object(server_http, "make_server", return_value=httpd), \
                mock.patch.object(server_run, "_start", return_value=None), \
                mock.patch.object(server_run, "_stop_pool", side_effect=RuntimeError("pool stuck")) as pool, \
                mock.patch.object(control, "clear_state"):
            try:
                server.main(["--host", "127.0.0.1", "--port", "12345", "--no-update"])
            except RuntimeError:
                pass                                # however main() reports it
        pool.assert_called_once_with()
        stop.assert_called_once_with()


class DatabaseCheckTests(unittest.TestCase):
    """server_run._database_check with dbstatus's checker replaced: what it logs, and when it
    syncs the profiles (the background server only, and only when the database answered)."""

    def setUp(self):
        self.log = []
        self.first = None
        self.sync = mock.Mock(return_value={"added": ["matt"], "changed": [], "removed": []})
        self.stop = mock.Mock()
        from decklab.db import profiles_sync
        for target, name, value in ((server_http, "log", self.log.append),
                                    (server_run.dbstatus, "start", lambda first: setattr(self, "first", first)),
                                    (server_run.dbstatus, "stop", self.stop),
                                    (server_run.venv, "reason", lambda: None),
                                    (profiles_sync, "sync", self.sync)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def snapshot(self, error=None, pending=0):
        return {"ok": error is None, "error": error, "detail": None, "pending_migrations": pending,
                "last_backup": None, "backup_stale": True}

    def lines(self):
        return [line[20:] for line in self.log]                # without the time stamp

    def test_the_background_server_syncs_profiles_after_the_first_check(self):
        stop = server_run._database_check(True)
        self.assertEqual(self.log, [])                         # nothing until the first check
        self.first(self.snapshot())
        self.assertEqual(self.lines(), ["Database: reachable.", "Database: profiles added matt; changed none; "
                                                                "removed none."])
        from decklab.lib.state import pg
        self.sync.assert_called_once_with(timeout=pg.REQUEST_TIMEOUT, options=pg.REQUEST_OPTIONS)
        stop()
        self.stop.assert_called_once_with()

    def test_a_console_server_never_syncs(self):
        server_run._database_check(False)
        self.first(self.snapshot(server_run.dbstatus.MIGRATIONS_PENDING, 1))
        self.assertEqual(self.lines(), ["Database: reachable, 1 migration pending (python -m decklab.db migrate)."])
        self.sync.assert_not_called()

    def test_an_unreachable_database_is_one_line_and_no_sync(self):
        server_run._database_check(True)
        self.first(self.snapshot(server_run.dbstatus.NOT_REACHABLE))
        self.assertEqual(self.lines(), ["Database: not reachable."])
        self.sync.assert_not_called()

    def test_a_failed_sync_is_one_line(self):
        self.sync.side_effect = ValueError("profile id home is kept for the audit trail\nsecond line")
        server_run._database_check(True)
        self.first(self.snapshot())
        self.assertEqual(self.lines(), ["Database: reachable.",
                                        "Database: profiles not synced: profile id home is kept for the audit trail"])

    def test_the_venv_reason_is_logged_at_once(self):
        with mock.patch.object(server_run.venv, "reason", lambda: "there's no .venv in the repo"):
            server_run._database_check(False)
        self.assertEqual(self.lines(), ["Database: .venv's packages aren't in use (there's no .venv in the repo)."])

    def test_nothing_is_logged_once_stopped(self):
        stop = server_run._database_check(True)
        stop()
        self.first(self.snapshot())
        self.assertEqual(self.log, [])



@unittest.skipUnless(WINDOWS and Path(sys.executable).with_name("pythonw.exe").exists(),
                     "needs Windows and pythonw.exe")
class BackgroundServerTests(unittest.TestCase):
    """pythonw.exe decklab/server.py as Task Scheduler runs it (no window, no
    console), on a free port on 127.0.0.1 (so Windows Firewall never asks
    about pythonw), with temp state and log files (DECKLAB_STATE_FILE)."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.state_file = self.dir / "server.json"
        self.log_file = self.dir / "logs" / "server.log"
        self.env = dict(os.environ, DECKLAB_STATE_FILE=str(self.state_file))
        self.env.pop("PYTHONPATH", None)
        # A real server makes its own store: a PgStore on the tests' database that doesn't
        # exist (DECKLAB_DB_NAME stays), so a database route answers 503 rather than the
        # RuntimeError the test package's explicit-store setting would give.
        self.env.pop(EXPLICIT_ENV, None)
        self.port = free_port()

    def start(self):
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        # These lifecycle probes must never write the adopted card-script overrides into the
        # real data folder.
        bootstrap = ("from decklab.lib.forge import overrides\n"
                     "overrides.ensure_deployed = lambda user_dir: None\n"
                     "from decklab import server\n"
                     "raise SystemExit(server.main())\n")
        proc = subprocess.Popen([str(pythonw), "-c", bootstrap, "--host", "127.0.0.1",
                                 "--port", str(self.port), "--no-update", "--log", str(self.log_file)],
                                cwd=config.REPO, env=self.env)

        def kill():
            if proc.poll() is None:
                proc.kill()
            proc.wait(10)

        self.addCleanup(kill)
        ok = wait_until(lambda: proc.poll() is not None or control.read_state(self.state_file) is not None, 60)
        self.assertTrue(ok and proc.poll() is None, self.log_text())
        return proc

    def window(self, proc):
        """The server's hidden session-end window (made before the state file is written)."""
        title = f"Deck Lab server (process {proc.pid})"
        self.assertTrue(wait_until(lambda: user32.FindWindowW("DeckLabServer", title)), self.log_text())
        return user32.FindWindowW("DeckLabServer", title)

    def log_text(self):
        return self.log_file.read_text(encoding="utf-8") if self.log_file.exists() else "(no log)"

    def marker(self):
        """The server's stop marker (beside the temp state file), or None."""
        path = control.stop_marker_path(self.port, self.state_file)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def logged(self, words, timeout=20):
        return wait_until(lambda: words in self.log_text(), timeout)

    def python(self, *args):
        return subprocess.run([sys.executable, str(Path("decklab") / "server.py"), *args], cwd=config.REPO,
                              env=self.env, capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)

    def test_logs_to_its_file_and_stops_with_the_stop_option(self):
        proc = self.start()
        state = control.read_state(self.state_file)
        self.assertEqual((state["pid"], state["port"], state["host"], state["background"], state["log"]),
                         (proc.pid, self.port, "127.0.0.1", True, str(self.log_file)))
        self.assertTrue(state["python"].lower().endswith("pythonw.exe"), state)
        self.assertTrue(self.logged(f"Deck Lab: http://127.0.0.1:{self.port}/  (listening on 127.0.0.1:{self.port}; "
                                    f"stop it with: python decklab/server.py --port {self.port} --stop)"),
                        self.log_text())
        self.window(proc)                                   # its hidden session-end window
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", "/api/profiles")
            self.assertEqual(conn.getresponse().status, 200)
        finally:
            conn.close()
        self.assertTrue(self.logged("GET /api/profiles 200"), self.log_text())
        # A second server on that port says the first is running, and how to stop it.
        second = self.python("--host", "127.0.0.1", "--port", str(self.port), "--no-update")
        self.assertEqual(second.returncode, 1, second.stderr)
        self.assertIn(f"Deck Lab is already running (process {proc.pid}, started ", second.stderr)
        stop = self.python("--port", str(self.port), "--stop")
        self.assertEqual((stop.returncode, stop.stdout), (0, f"Deck Lab (port {self.port}) has stopped.\n"),
                         stop.stderr)
        self.assertEqual(proc.wait(5), 0)                   # it had already ended
        self.assertFalse(self.state_file.exists())
        self.assertEqual(self.marker()["by"], "server.py --stop")     # written first, and kept (E11-S26)
        text = self.log_text()
        self.assertIn(" Stop requested.", text)
        self.assertTrue(text.rstrip().endswith(" Deck Lab has stopped."), text)
        self.assertNotIn("Traceback", text)

    def test_stops_when_windows_ends_the_session(self):
        proc = self.start()
        hwnd = self.window(proc)
        self.assertEqual(send_message(hwnd, 0x0011, 0), 1)      # WM_QUERYENDSESSION: it may end
        self.assertEqual(send_message(hwnd, 0x0016, 1), 0)      # WM_ENDSESSION: it's ending
        self.assertEqual(proc.wait(10), 0)
        self.assertFalse(self.state_file.exists())
        self.assertIsNone(self.marker())                    # not on purpose: the next logon starts it anyway
        text = self.log_text()
        self.assertIn("Windows is logging off or shutting down: stopping.", text)
        self.assertTrue(text.rstrip().endswith(" Deck Lab has stopped."), text)

    def test_a_hard_kill_leaves_no_stop_marker(self):
        # Task Manager or taskkill /F: unexpected, so the watchdog would start it again (E11-S26).
        proc = self.start()
        proc.kill()
        proc.wait(10)
        self.assertIsNone(self.marker())

    def test_taskkill_without_f_stops_it_like_the_stop_option(self):
        # taskkill /PID (no /F) sends WM_CLOSE to the process's windows. Only
        # this test's own process is named, never pythonw.exe as a whole.
        proc = self.start()
        self.window(proc)                                   # what taskkill sends WM_CLOSE to
        kill = subprocess.run(["taskkill", "/PID", str(proc.pid)], capture_output=True, text=True, timeout=60,
                              creationflags=NO_WINDOW)
        self.assertEqual(kill.returncode, 0, kill.stdout + kill.stderr)
        self.assertEqual(proc.wait(20), 0)
        self.assertFalse(user32.FindWindowW("DeckLabServer", f"Deck Lab server (process {proc.pid})"))
        self.assertFalse(self.state_file.exists())
        text = self.log_text()
        self.assertIn(" Asked to close (taskkill): stopping.", text)
        self.assertTrue(text.rstrip().endswith(" Deck Lab has stopped."), text)
        self.assertNotIn("Traceback", text)



class ScriptTests(unittest.TestCase):

    def test_runs_as_a_script_from_the_repo_root(self):
        repo = config.REPO
        result = subprocess.run([sys.executable, str(Path("decklab") / "server.py"), "--help"],
                                cwd=repo, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        for option in ("--no-update", "--log FILE", "--stop"):
            self.assertIn(option, result.stdout)



class ModuleSplitTests(unittest.TestCase):
    """decklab/server.py is the script; lib/server_http.py and lib/server_run.py
    hold its code. Each name the tests patch has one binding, in the module
    whose code reads it, and none in decklab.server, so a patch left on the
    script fails instead of doing nothing. The public names the script still
    offers are the owner modules' own objects."""

    PATCHED = {"log": "server_http", "make_server": "server_http", "CLOSE_WAIT": "server_run",
               "_start": "server_run", "_start_pool": "server_run", "_stop_pool": "server_run",
               "_wait_for_matchup": "server_run", "_record_state": "server_run",
               "_stop_jobs_on_ctrl_c": "server_run", "_load_index": "server_run", "_update_loop": "server_run",
               "_serve": "server_run", "_start_remote": "server_run", "_console_handler": "server_run",
               "_stop_handler": "server_run", "_session_end_handler": "server_run", "_port_in_use": "server_run",
               "_database_check": "server_run"}
    REEXPORTED = {
        "server_http": ("WEB_DIR", "STATIC_TYPES", "STATIC_NAME_RE", "STATIC_FOLDERS", "PAGE_PARAMS", "HOME_SUFFIXES",
                        "IMAGE_MAX_AGE", "JSON_TYPE", "DRAIN_BYTES", "DRAIN_SECONDS", "GET", "COORD_WAITING",
                        "WRITE_HEADER", "WRITE_SITES", "static_files", "host_name", "host_allowed", "NotAllowed",
                        "Refused", "TUNNEL_ONLY", "Handler", "Server"),
        "server_run": ("UPDATE_EVERY", "RETRY_AFTER", "FORGE_STOP_WAIT", "POOL_STOP_WAIT", "CTRL_C", "CTRL_BREAK",
                       "CTRL_CLOSE", "CTRL_SHUTDOWN", "ctrl_handler"),
    }

    def test_each_patched_name_has_one_binding(self):
        modules = {"server_http": server_http, "server_run": server_run}
        for name, owner in self.PATCHED.items():
            with self.subTest(name=name):
                self.assertEqual([part for part, module in sorted(modules.items()) if name in vars(module)], [owner])
                self.assertNotIn(name, vars(server))
                with self.assertRaises(AttributeError), mock.patch.object(server, name, None):
                    pass

    def test_the_scripts_public_names_are_the_owners(self):
        modules = {"server_http": server_http, "server_run": server_run}
        for owner, names in self.REEXPORTED.items():
            for name in names:
                with self.subTest(name=name):
                    self.assertIs(getattr(server, name), getattr(modules[owner], name))

    def test_the_server_modules_never_import_the_script(self):
        # Run as a script, decklab/server.py is __main__: importing decklab.server
        # from lib would load a second copy, with a log and state of its own.
        for module in (server_http, server_run):
            with self.subTest(module=module.__name__):
                source = Path(module.__file__).read_text(encoding="utf-8")
                self.assertNotRegex(source, r"decklab\.server\b|from decklab import [^\n]*\bserver\b")


if __name__ == "__main__":
    unittest.main()
