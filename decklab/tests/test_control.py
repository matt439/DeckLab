"""Tests for decklab/lib/control.py: the state file, stopping a server
through its named event, the hidden session-end window and the rotating log.

Everything runs in temp folders with temp state files, on free ports (never
8642, where the real Deck Lab server may be running at the same time), so
the real decklab/data/server.json and logs are never touched and the real
server is never signalled. The Windows tests use the real Windows API:
named events, a hidden window found by its class, real processes.

Run from the repo root: python scripts/test_fixtures.py
The fixture runner disables configured PostgreSQL and real Forge; named native
runtime cases also need separate qualification (see AGENTS.md, Tests).
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from decklab import server  # noqa: F401 (runs build.start() before the server modules load)
from decklab.lib import config, control, server_http

WINDOWS = sys.platform == "win32"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if WINDOWS else 0


def free_port():
    """A port nothing listens on (never 8642: the OS hands out high ports)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def now_iso(seconds=0):
    return (datetime.now().astimezone() + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def sleeper(test, seconds=120):
    """A child Python process that sleeps; killed when the test ends."""
    proc = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=NO_WINDOW)
    test.addCleanup(lambda: (proc.kill(), proc.wait(10)))
    return proc


def wait_until(condition, timeout=10, step=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(step)
    return condition()


if WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    for _name, _restype, _argtypes in (
            ("FindWindowW", wintypes.HWND, [wintypes.LPCWSTR, wintypes.LPCWSTR]),
            ("SendMessageTimeoutW", ctypes.c_ssize_t, [wintypes.HWND, wintypes.UINT, ctypes.c_size_t,
                                                       ctypes.c_ssize_t, wintypes.UINT, wintypes.UINT,
                                                       ctypes.POINTER(ctypes.c_size_t)]),
            ("IsWindowVisible", wintypes.BOOL, [wintypes.HWND]),
            ("GetAncestor", wintypes.HWND, [wintypes.HWND, wintypes.UINT]),
            ("GetDesktopWindow", wintypes.HWND, [])):
        getattr(user32, _name).restype = _restype
        getattr(user32, _name).argtypes = _argtypes

    def send_message(hwnd, message, wparam, timeout_ms=15000):
        """SendMessage with a time limit (a broken window can't hang the tests):
        the window procedure's answer, or None if it didn't answer."""
        result = ctypes.c_size_t()
        if not user32.SendMessageTimeoutW(hwnd, message, wparam, 0, 0x0002, timeout_ms, ctypes.byref(result)):
            return None
        return result.value


class TempCase(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.state_file = self.dir / "state" / "server.json"
        self.logged = []
        patch = mock.patch.object(control, "_log", self.logged.append)
        patch.start()
        self.addCleanup(patch.stop)


class StateTests(TempCase):

    def state(self, **changes):
        return {"version": 1, "pid": os.getpid(), "host": "127.0.0.1", "port": 50001, "started": now_iso(),
                "python": sys.executable, "log": None, "background": False, **changes}

    def test_round_trip_atomic_and_in_a_new_folder(self):
        state = self.state()
        control.write_state(state, self.state_file)
        self.assertEqual(control.read_state(self.state_file), state)
        control.write_state(self.state(port=50002), self.state_file)
        self.assertEqual(control.read_state(self.state_file)["port"], 50002)
        self.assertEqual(os.listdir(self.state_file.parent), ["server.json"])     # no temp file left

    def test_the_default_path_is_the_state_file(self):
        with mock.patch.object(control, "STATE_FILE", self.state_file):
            control.write_state(self.state())
            self.assertEqual(control.read_state()["pid"], os.getpid())
            self.assertTrue(control.clear_state(os.getpid()))
            self.assertIsNone(control.read_state())

    def test_missing_or_bad_files_read_as_none_and_are_kept(self):
        self.assertIsNone(control.read_state(self.state_file))
        self.state_file.parent.mkdir(parents=True)
        for content in (b"{nope", b"[]", b"\xff\xfe{", b'{"pid": "12"}', b'{"pid": true}', b'{"pid": 0}',
                        b'{"pid": -5}', b'{"pid": 99999999999}', b'{"port": 8642}', b""):
            with self.subTest(content=content):
                self.state_file.write_bytes(content)
                self.assertIsNone(control.read_state(self.state_file))
                self.assertEqual(self.state_file.read_bytes(), content)

    def test_a_process_that_has_ended(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"], creationflags=NO_WINDOW)
        child.wait(30)
        # Popen still holds a handle, so the process can be opened: its exit code says it ended.
        self.assertFalse(control.process_alive(child.pid))
        control.write_state(self.state(pid=child.pid), self.state_file)
        self.assertIsNone(control.read_state(self.state_file))
        self.assertTrue(self.state_file.exists())

    @unittest.skipUnless(WINDOWS, "process start times are only checked on Windows")
    def test_a_process_id_reused_by_a_newer_process(self):
        # This process started after 2000, so it can't be the server that wrote this.
        control.write_state(self.state(started="2000-01-01T00:00:00+00:00"), self.state_file)
        self.assertIsNone(control.read_state(self.state_file))
        # A running process this user can't look into (the System process, 4,
        # unless the tests run elevated) is no server of theirs. Mocked, so
        # the answer doesn't depend on whether the prompt is elevated.
        self.assertTrue(control.process_alive(4))
        control.write_state(self.state(), self.state_file)
        with mock.patch.object(control, "process_started", return_value=None) as started:
            self.assertIsNone(control.read_state(self.state_file))
        started.assert_called_once_with(os.getpid())
        for started in (now_iso(), datetime.now().isoformat(timespec="seconds"), None, "not a time"):
            with self.subTest(started=started):
                control.write_state(self.state(started=started), self.state_file)
                self.assertEqual(control.read_state(self.state_file)["pid"], os.getpid())

    def test_clear_state_removes_only_its_own(self):
        control.write_state(self.state(), self.state_file)
        self.assertFalse(control.clear_state(os.getpid() + 1, self.state_file))
        self.assertTrue(self.state_file.exists())
        self.assertTrue(control.clear_state(os.getpid(), self.state_file))
        self.assertFalse(self.state_file.exists())
        self.assertFalse(control.clear_state(os.getpid(), self.state_file))     # already gone: no error
        self.assertFalse(control.clear_state(None, self.state_file))
        self.state_file.write_text("{nope", encoding="utf-8")
        self.assertFalse(control.clear_state(os.getpid(), self.state_file))
        self.assertTrue(control.clear_state(path=self.state_file))             # no pid: whatever it says

    def test_decklab_state_file_moves_it_for_tests(self):
        code = "from decklab.lib import control; print(control.STATE_FILE)"
        env = dict(os.environ, DECKLAB_STATE_FILE=str(self.state_file))
        moved = subprocess.run([sys.executable, "-c", code], cwd=config.REPO, env=env, capture_output=True,
                               text=True, timeout=60, creationflags=NO_WINDOW)
        self.assertEqual(moved.stdout.strip(), str(self.state_file), moved.stderr)
        env.pop("DECKLAB_STATE_FILE")
        default = subprocess.run([sys.executable, "-c", code], cwd=config.REPO, env=env, capture_output=True,
                                 text=True, timeout=60, creationflags=NO_WINDOW)
        self.assertEqual(default.stdout.strip(), str(config.DATA / "server.json"), default.stderr)
        self.assertEqual(control.LOG_FILE, config.DATA / "logs" / "server.log")


class StopMarkerTests(TempCase):
    """The stop marker (E11-S26): stopped on purpose, so the watchdog leaves the server off."""

    LOGON = "2026-10-20T07:58:12+00:00"
    real_logon_time = staticmethod(control.logon_time)      # before setUp replaces it

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(control, "logon_time", return_value=self.LOGON)
        patch.start()
        self.addCleanup(patch.stop)

    def test_mark_read_and_clear(self):
        self.assertIsNone(control.read_stopped(50001, self.state_file))
        self.assertTrue(control.mark_stopped(50001, "homenet stop", self.state_file))
        marker = control.stop_marker_path(50001, self.state_file)
        self.assertEqual(marker, self.state_file.with_name("stopped-50001.json"))
        found = control.read_stopped(50001, self.state_file)
        self.assertEqual({k: found[k] for k in ("version", "port", "by", "logon")},
                         {"version": 1, "port": 50001, "by": "homenet stop", "logon": self.LOGON})
        self.assertLessEqual(abs(control._timestamp(found["at"]) - time.time()), 60)
        self.assertEqual(sorted(os.listdir(self.state_file.parent)), ["stopped-50001.json"])     # no temp file
        self.assertTrue(control.clear_stopped(50001, self.state_file))
        self.assertIsNone(control.read_stopped(50001, self.state_file))
        self.assertFalse(control.clear_stopped(50001, self.state_file))      # already gone: no error

    def test_a_restarts_marker(self):
        control.mark_stopped(50001, "homenet stop", self.state_file)
        self.assertNotIn("restart", control.read_stopped(50001, self.state_file))
        self.assertTrue(control.mark_stopped(50001, "homenet restart", self.state_file, restart=True))
        self.assertIs(control.read_stopped(50001, self.state_file)["restart"], True)
        # A server stopping later keeps it (keep), so the watchdog still starts it again.
        self.assertFalse(control.mark_stopped(50001, "stop request", self.state_file, keep=True))
        self.assertEqual(control.read_stopped(50001, self.state_file)["by"], "homenet restart")

    def test_one_per_port_beside_the_state_file(self):
        control.mark_stopped(50001, "homenet stop", self.state_file)
        self.assertIsNone(control.read_stopped(50002, self.state_file))
        with mock.patch.object(control, "STATE_FILE", self.state_file):
            self.assertEqual(control.read_stopped(50001)["by"], "homenet stop")
            self.assertEqual(control.stop_marker_path(8642), self.state_file.with_name("stopped-8642.json"))

    def test_keep_leaves_the_first_stop_named(self):
        control.mark_stopped(50001, "homenet stop", self.state_file)
        self.assertFalse(control.mark_stopped(50001, "stop request", self.state_file, keep=True))
        self.assertEqual(control.read_stopped(50001, self.state_file)["by"], "homenet stop")
        self.assertTrue(control.mark_stopped(50001, "taskkill", self.state_file))
        self.assertEqual(control.read_stopped(50001, self.state_file)["by"], "taskkill")

    def test_a_marker_from_another_logon_doesnt_count(self):
        control.mark_stopped(50001, "homenet stop", self.state_file)
        self.assertIsNone(control.read_stopped(50001, self.state_file, logon="2026-10-21T07:00:00+00:00"))
        # The same instant written another way is the same logon.
        self.assertIsNotNone(control.read_stopped(50001, self.state_file, logon="2026-10-20T17:58:12+10:00"))
        # A logon time that isn't known, now or then: it counts (staying off is the safe side).
        with mock.patch.object(control, "logon_time", return_value=None):
            self.assertIsNotNone(control.read_stopped(50001, self.state_file))
            control.mark_stopped(50002, "homenet stop", self.state_file)
        self.assertIsNotNone(control.read_stopped(50002, self.state_file, logon="2026-10-21T07:00:00+00:00"))

    def test_an_unreadable_marker_counts(self):
        marker = control.stop_marker_path(50001, self.state_file)
        marker.parent.mkdir(parents=True)
        for content in (b"{nope", b"[]", b"\xff\xfe{"):
            with self.subTest(content=content):
                marker.write_bytes(content)
                self.assertEqual(control.read_stopped(50001, self.state_file), {"by": "unreadable"})

    def test_logon_time(self):
        logon = self.real_logon_time()
        if WINDOWS:
            self.assertIsNotNone(logon)
            self.assertLess(control._timestamp(logon), time.time())
            self.assertTrue(logon.endswith("+00:00"), logon)
            self.assertEqual(self.real_logon_time(), logon)
        with mock.patch.object(sys, "platform", "linux"):
            self.assertIsNone(self.real_logon_time())


class ProcessTests(unittest.TestCase):

    def test_process_alive(self):
        self.assertTrue(control.process_alive(os.getpid()))
        for pid in (None, 0, -1, "1", True, 2 ** 40, 1.5):
            with self.subTest(pid=pid):
                self.assertFalse(control.process_alive(pid))

    @unittest.skipUnless(WINDOWS, "Windows only")
    def test_process_started(self):
        started = control.process_started(os.getpid())
        self.assertLessEqual(started, time.time())
        self.assertGreater(started, time.time() - 24 * 3600)
        self.assertIsNone(control.process_started(None))
        self.assertIsNone(control.process_started(2 ** 31))


@unittest.skipUnless(WINDOWS, "the stop event is Windows only")
class StopTests(TempCase):

    def test_event_name(self):
        self.assertEqual(control.stop_event_name(8642), "Local\\DeckLab-stop-8642")
        self.assertEqual(control.stop_event_name("50001"), "Local\\DeckLab-stop-50001")

    def test_nothing_listening(self):
        started = time.monotonic()
        self.assertEqual(control.request_stop(free_port(), wait=5, path=self.state_file), "not running")
        self.assertLess(time.monotonic() - started, 2)

    def test_stopping_a_real_server(self):
        log = []
        with mock.patch.object(server_http, "log", log.append):
            httpd = server_http.make_server("127.0.0.1", 0, web_dir=self.dir)
            port = httpd.server_address[1]
            stops = []

            def on_stop():
                stops.append(threading.current_thread().name)
                httpd.shutdown()

            listener = control.listen_for_stop(port, on_stop)
            served = threading.Event()

            def run():
                try:
                    httpd.serve_forever()
                finally:
                    served.set()
                    httpd.server_close()
                    listener.close()

            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            self.addCleanup(lambda: (httpd.shutdown(), thread.join(5)) if thread.is_alive() else None)
            with socket.create_connection(("127.0.0.1", port), timeout=5):
                pass
            self.assertEqual(control.request_stop(port, wait=10, path=self.state_file), "stopped")
            self.assertTrue(served.is_set())            # serve_forever() returned
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(stops, [f"stop-listener-{port}"])
            # Nothing listens any more.
            self.assertEqual(control.request_stop(port, wait=1, path=self.state_file), "not running")

    def test_waits_for_the_process_the_state_file_names(self):
        port, child = free_port(), sleeper(self)
        control.write_state({"version": 1, "pid": child.pid, "port": port, "started": now_iso()}, self.state_file)
        listener = control.listen_for_stop(port, child.kill)
        self.addCleanup(listener.close)
        # The listener stays open (the event still exists), so only the process ending can say "stopped".
        self.assertEqual(control.request_stop(port, wait=10, path=self.state_file), "stopped")
        self.assertIsNotNone(child.poll())

    def test_timeout(self):
        port, child = free_port(), sleeper(self)
        control.write_state({"version": 1, "pid": child.pid, "port": port, "started": now_iso()}, self.state_file)
        stops = []
        listener = control.listen_for_stop(port, lambda: stops.append(1))
        self.addCleanup(listener.close)
        started = time.monotonic()
        self.assertEqual(control.request_stop(port, wait=0.5, path=self.state_file), "timeout")
        self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(wait_until(lambda: stops == [1]))
        self.assertIsNone(child.poll())
        # With no state file, the event still being there means it's still running.
        other = free_port()
        listener2 = control.listen_for_stop(other, lambda: None)
        self.addCleanup(listener2.close)
        self.assertEqual(control.request_stop(other, wait=0.3, path=self.dir / "none.json"), "timeout")

    def test_a_stop_meant_for_an_earlier_server_is_cleared(self):
        # An earlier server on this port, still saving a matchup, holds the event, already set.
        win, port = control._win(), free_port()
        old = win.k32.CreateEventW(None, False, True, control.stop_event_name(port))
        self.assertTrue(old)
        self.addCleanup(win.k32.CloseHandle, old)
        stops = []
        listener = control.listen_for_stop(port, lambda: stops.append(1))
        self.addCleanup(listener.close)
        time.sleep(0.3)
        self.assertEqual(stops, [])
        self.assertEqual(control.request_stop(port, wait=0.2, path=self.state_file), "timeout")
        self.assertTrue(wait_until(lambda: stops == [1]))

    def test_a_failing_on_stop_is_logged(self):
        port = free_port()

        def on_stop():
            raise RuntimeError("boom")

        listener = control.listen_for_stop(port, on_stop)
        self.addCleanup(listener.close)
        self.assertEqual(control.request_stop(port, wait=0.2, path=self.state_file), "timeout")
        self.assertTrue(wait_until(lambda: any("RuntimeError: boom" in line for line in self.logged)))
        self.assertIn("Stopping failed", self.logged[0])

    def test_close_without_a_stop(self):
        port, stops = free_port(), []
        listener = control.listen_for_stop(port, lambda: stops.append(1))
        listener.close()
        listener.close()                                # twice is fine
        self.assertFalse(listener._thread.is_alive())
        self.assertEqual(control.request_stop(port, wait=1, path=self.state_file), "not running")
        self.assertEqual(stops, [])


class OffWindowsTests(unittest.TestCase):

    def test_no_ops_off_windows_and_linux(self):
        with mock.patch.object(control.sys, "platform", "darwin"):
            self.assertEqual(control.request_stop(50001, wait=0), "unsupported")
            listener = control.listen_for_stop(50001, lambda: None)
            listener.close()
            watcher = control.watch_session_end(lambda: None, on_close=lambda: None)
            self.assertIsNone(watcher.hwnd)
            watcher.close()
            self.assertIsNone(control.process_started(os.getpid()))


@unittest.skipUnless(WINDOWS, "the session-end window is Windows only")
class SessionEndTests(TempCase):

    WM_CLOSE, WM_QUERYENDSESSION, WM_ENDSESSION, GA_PARENT = 0x0010, 0x0011, 0x0016, 1

    def watch(self, on_end, title=None, on_close=None):
        watcher = control.watch_session_end(on_end, title, on_close)
        self.addCleanup(watcher.close)
        return watcher

    def exists(self, watcher):
        return user32.FindWindowW(control.WINDOW_CLASS, watcher.title) == watcher.hwnd

    def test_wm_close_from_another_program_calls_on_close_and_the_window_stays(self):
        # taskkill /PID without /F sends WM_CLOSE to the process's windows: a
        # stop request, not a destroyed window and a server deaf to logging off.
        closed, ended = [], []
        watcher = self.watch(lambda: ended.append(1), on_close=lambda: closed.append(threading.current_thread().name))
        self.assertEqual(send_message(watcher.hwnd, self.WM_CLOSE, 0), 0)
        self.assertTrue(wait_until(lambda: closed == ["close-request"]), closed)
        self.assertTrue(self.exists(watcher))
        self.assertEqual(send_message(watcher.hwnd, self.WM_CLOSE, 0), 0)     # once only
        time.sleep(0.2)
        self.assertEqual(closed, ["close-request"])
        self.assertEqual(send_message(watcher.hwnd, self.WM_ENDSESSION, 1), 0)  # still hears the session's end
        self.assertEqual(ended, [1])
        watcher.close()
        self.assertFalse(user32.FindWindowW(control.WINDOW_CLASS, watcher.title))
        self.assertFalse(watcher._thread.is_alive())
        self.assertEqual(closed, ["close-request"])         # close() isn't taken for a request

    def test_wm_close_without_on_close_is_ignored_and_only_close_destroys(self):
        watcher = self.watch(lambda: None)
        self.assertEqual(send_message(watcher.hwnd, self.WM_CLOSE, 0), 0)
        self.assertTrue(self.exists(watcher))
        # close()'s own message, sent by another program, does nothing either.
        self.assertEqual(send_message(watcher.hwnd, control.WM_DESTROY_WATCHER, 0), 0)
        self.assertTrue(self.exists(watcher))
        self.assertTrue(watcher._thread.is_alive())
        watcher.close()
        self.assertFalse(user32.FindWindowW(control.WINDOW_CLASS, watcher.title))
        self.assertFalse(watcher._thread.is_alive())

    def test_a_failing_on_close_is_logged(self):
        def failing():
            raise RuntimeError("close boom")

        watcher = self.watch(lambda: None, on_close=failing)
        self.assertEqual(send_message(watcher.hwnd, self.WM_CLOSE, 0), 0)
        self.assertTrue(wait_until(lambda: any("RuntimeError: close boom" in line for line in self.logged)),
                        self.logged)
        self.assertIn("Stopping when asked to close failed", self.logged[0])
        self.assertTrue(self.exists(watcher))

    def test_the_hidden_window_answers_and_calls_on_end_once(self):
        ended = []
        watcher = self.watch(lambda: ended.append(threading.current_thread().name))
        hwnd = user32.FindWindowW(control.WINDOW_CLASS, watcher.title)
        self.assertEqual(hwnd, watcher.hwnd)
        self.assertIn(f"(process {os.getpid()})", watcher.title)
        self.assertFalse(user32.IsWindowVisible(hwnd))
        # A top-level window (the desktop is its parent), not a message-only one.
        self.assertEqual(user32.GetAncestor(hwnd, self.GA_PARENT), user32.GetDesktopWindow())
        self.assertEqual(send_message(hwnd, self.WM_QUERYENDSESSION, 0), 1)
        self.assertEqual(ended, [])
        self.assertEqual(send_message(hwnd, self.WM_ENDSESSION, 0), 0)        # cancelled: not ending
        self.assertEqual(ended, [])
        self.assertEqual(send_message(hwnd, self.WM_ENDSESSION, 1), 0)
        self.assertEqual(ended, ["session-end"])
        self.assertEqual(send_message(hwnd, self.WM_ENDSESSION, 1), 0)
        self.assertEqual(len(ended), 1)
        watcher.close()
        self.assertFalse(user32.FindWindowW(control.WINDOW_CLASS, watcher.title))
        self.assertFalse(watcher._thread.is_alive())

    def test_two_windows_and_a_failing_on_end(self):
        calls = []

        def failing():
            calls.append("failing")
            raise RuntimeError("session boom")

        first = self.watch(failing, title="Deck Lab test window A")
        second = self.watch(lambda: calls.append("second"), title="Deck Lab test window B")
        self.assertNotEqual(first.hwnd, second.hwnd)
        self.assertEqual(user32.FindWindowW(control.WINDOW_CLASS, "Deck Lab test window B"), second.hwnd)
        self.assertEqual(send_message(first.hwnd, self.WM_ENDSESSION, 1), 0)
        self.assertEqual(calls, ["failing"])
        self.assertTrue(any("RuntimeError: session boom" in line for line in self.logged), self.logged)
        self.assertEqual(send_message(second.hwnd, self.WM_QUERYENDSESSION, 0), 1)
        self.assertEqual(send_message(second.hwnd, self.WM_ENDSESSION, 1), 0)
        self.assertEqual(calls, ["failing", "second"])


class LogTests(TempCase):

    def setUp(self):
        super().setUp()
        self.path = self.dir / "logs" / "server.log"

    def files(self):
        """The log's files, oldest first."""
        return [p for p in (self.path.with_name(f"server.log.{n}") for n in (3, 2, 1)) if p.exists()] + \
            ([self.path] if self.path.exists() else [])

    def test_appends_and_every_write_is_in_the_file_at_once(self):
        stream = control.open_log(self.path)
        self.addCleanup(stream.close)
        self.assertEqual((stream.encoding, stream.isatty(), stream.writable()), ("utf-8", False, True))
        self.assertFalse(self.path.parent.exists())            # nothing until the first write
        print("first line", file=stream)
        self.assertEqual(self.path.read_bytes(), b"first line\n")
        self.assertEqual(stream.write("second \u2713 \ud800\n"), 11)
        stream.flush()
        self.assertEqual(self.path.read_bytes(), b"first line\nsecond \xe2\x9c\x93 \\ud800\n")
        try:
            raise ValueError("boom")
        except ValueError:
            traceback.print_exc(file=stream)
        self.assertIn("ValueError: boom", self.path.read_text(encoding="utf-8"))
        # The next server appends to the same file.
        other = control.open_log(self.path)
        other.write("third\n")
        other.close()
        self.assertTrue(self.path.read_text(encoding="utf-8").endswith("third\n"))
        self.assertEqual(stream.write(""), 0)

    def test_the_default_path(self):
        with mock.patch.object(control, "LOG_FILE", self.path):
            stream = control.open_log()
            stream.write("x\n")
            stream.close()
        self.assertEqual(self.path.read_text(encoding="utf-8"), "x\n")
        self.assertEqual((control.LOG_MAX_BYTES, control.LOG_BACKUPS), (2_000_000, 3))

    def test_rotates_and_keeps_three_old_files(self):
        stream = control.open_log(self.path, max_bytes=1000, backups=3)
        lines = [f"line {n:04d} {'x' * 40}\n" for n in range(200)]         # 51 bytes each
        for line in lines:
            stream.write(line)
        stream.close()
        self.assertEqual(sorted(os.listdir(self.path.parent)),
                         ["server.log", "server.log.1", "server.log.2", "server.log.3"])
        for path in self.files():
            self.assertLessEqual(path.stat().st_size, 1000)
        kept = "".join(p.read_text(encoding="utf-8") for p in self.files())
        # 19 lines fill a file; the newest 3 x 19 + 10 lines are kept, in order.
        self.assertEqual(kept, "".join(lines[-67:]))

    def test_a_full_log_rotates_on_the_first_write(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"o" * 995)
        stream = control.open_log(self.path, max_bytes=1000, backups=3)
        stream.write("new line\n")
        stream.close()
        self.assertEqual(self.path.with_name("server.log.1").read_bytes(), b"o" * 995)
        self.assertEqual(self.path.read_bytes(), b"new line\n")

    def test_no_backups_starts_over(self):
        stream = control.open_log(self.path, max_bytes=100, backups=0)
        for n in range(10):
            stream.write(f"{n:02d} {'z' * 30}\n")                         # 34 bytes
        stream.close()
        self.assertEqual(os.listdir(self.path.parent), ["server.log"])
        # Two lines fit; the third starts the file over.
        self.assertEqual(self.path.read_text(encoding="utf-8"), f"08 {'z' * 30}\n09 {'z' * 30}\n")

    def test_concurrent_writers(self):
        # 8 x 300 lines of 39 bytes: three full files of 30,000 bytes and a fourth, none lost.
        stream = control.open_log(self.path, max_bytes=30_000, backups=3)
        writers, each = 8, 300

        def write(n):
            for i in range(each):
                stream.write(f"writer {n} line {i:03d} {'y' * 20}\n")

        threads = [threading.Thread(target=write, args=(n,)) for n in range(writers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        stream.close()
        files = self.files()
        self.assertEqual(len(files), 4)
        for path in files:
            self.assertLessEqual(path.stat().st_size, 30_000)
        lines = "".join(p.read_text(encoding="utf-8") for p in files).splitlines()
        self.assertEqual(len(lines), writers * each)
        seen = {n: [] for n in range(writers)}
        for line in lines:
            match = re.fullmatch(r"writer (\d) line (\d{3}) y{20}", line)
            self.assertIsNotNone(match, line)
            seen[int(match[1])].append(int(match[2]))
        for n in range(writers):
            self.assertEqual(seen[n], list(range(each)))                   # every line, in order

    def test_write_never_raises(self):
        blocker = self.dir / "a-file"
        blocker.write_text("x", encoding="utf-8")
        for path in (blocker / "logs" / "server.log", self.dir):           # no folder can be made; a folder
            with self.subTest(path=path):
                stream = control.open_log(path)
                self.assertEqual(stream.write("lost\n"), 5)
                stream.flush()
                stream.close()
        stream = control.open_log(self.path)
        stream.close()
        self.assertEqual(stream.write("after close\n"), 12)
        self.assertFalse(self.path.exists())

    def test_a_rotation_that_fails_keeps_appending(self):
        # Another program holding a log file open makes renaming it fail on Windows.
        stream = control.open_log(self.path, max_bytes=200, backups=3)
        lines = [f"{n:03d} {'w' * 46}\n" for n in range(20)]               # 51 bytes each
        with mock.patch.object(control, "LOG_RETRY", 300), \
                mock.patch.object(control.os, "replace", side_effect=PermissionError("in use")) as replace:
            for line in lines:
                stream.write(line)
        stream.close()
        self.assertEqual(self.path.read_text(encoding="utf-8"), "".join(lines))
        # Tried at 200 bytes, then only every LOG_RETRY bytes, not at every write.
        self.assertGreater(replace.call_count, 1)
        self.assertLess(replace.call_count, 6)

    def old_files(self, *contents):
        """server.log.1, .2, ... holding contents (newest first)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for number, content in enumerate(contents, 1):
            self.path.with_name(f"server.log.{number}").write_text(content, encoding="utf-8")

    def contents(self):
        """{file name: its text} for every file in the log's folder."""
        return {p.name: p.read_text(encoding="utf-8") for p in sorted(self.path.parent.iterdir())}

    @unittest.skipUnless(WINDOWS, "only Windows refuses to rename a file another program has open")
    def test_a_log_held_open_keeps_the_old_files(self):
        # An editor (or Get-Content -Wait) showing server.log: every rotation
        # fails, and the old files must not shift at each try.
        self.old_files("B1", "B2", "B3")
        self.path.write_text("", encoding="utf-8")
        stream = control.open_log(self.path, max_bytes=1000, backups=3)
        self.addCleanup(stream.close)
        lines = [f"line {n:03d} {'h' * 40}\n" for n in range(100)]          # 50 bytes each
        with open(self.path, "rb"), mock.patch.object(control, "LOG_RETRY", 1000):
            for line in lines:
                stream.write(line)
        self.assertEqual(self.contents(), {"server.log": "".join(lines), "server.log.1": "B1",
                                           "server.log.2": "B2", "server.log.3": "B3"})
        stream.write("after\n")                             # let go of: it rotates now
        stream.close()
        self.assertEqual(self.contents(), {"server.log": "after\n", "server.log.1": "".join(lines),
                                           "server.log.2": "B1", "server.log.3": "B2"})

    def test_an_old_file_that_cant_move_puts_the_live_log_back(self):
        self.old_files("B1", "B2")
        held = self.path.with_name("server.log.1")
        replace = os.replace

        def refuse_the_first_old_file(source, target):
            if Path(source) == held:
                raise PermissionError("in use")
            replace(source, target)

        stream = control.open_log(self.path, max_bytes=100, backups=3)
        lines = [f"{n:02d} {'r' * 30}\n" for n in range(4)]                # 34 bytes each
        with mock.patch.object(control, "LOG_RETRY", 0), \
                mock.patch.object(control.os, "replace", side_effect=refuse_the_first_old_file):
            for line in lines:                                  # tries at the third line and the fourth
                stream.write(line)
        # .2 had moved to .3 (it was due to), .1 couldn't move: the live log is back, nothing lost.
        self.assertEqual(self.contents(), {"server.log": "".join(lines), "server.log.1": "B1",
                                           "server.log.3": "B2"})
        stream.write("next\n")
        stream.close()
        self.assertEqual(self.contents(), {"server.log": "next\n", "server.log.1": "".join(lines),
                                           "server.log.2": "B1", "server.log.3": "B2"})

    def test_a_log_left_rotating_goes_in_first(self):
        # A rotation that couldn't put the live log back left server.log.rotating.
        self.old_files("B1")
        self.path.with_name("server.log.rotating").write_text("R", encoding="utf-8")
        self.path.write_text("L" * 99 + "\n", encoding="utf-8")
        stream = control.open_log(self.path, max_bytes=100, backups=3)
        stream.write("one\n")
        stream.write("two\n")
        stream.close()
        # "one" went into the live log while .rotating took .1; "two" rotated it.
        self.assertEqual(self.contents(), {"server.log": "two\n", "server.log.1": "L" * 99 + "\none\n",
                                           "server.log.2": "R", "server.log.3": "B1"})

    def test_a_write_from_inside_a_write_neither_hangs_nor_is_lost(self):
        # Python reporting something (an exception in a __del__, a warning) to
        # sys.stderr, which is this stream, while a write holds its lock.
        stream = control.open_log(self.path)      # not closed in a cleanup: close() would hang on a hung lock
        outer = stream._write

        def write_and_report(data):
            outer(data)
            if data == b"outer\n":
                stream.write("nested\n")
                stream.write("nested again\n")

        stream._write = write_and_report
        thread = threading.Thread(target=stream.write, args=("outer\n",), daemon=True)
        thread.start()
        thread.join(10)
        self.assertFalse(thread.is_alive(), "a nested write hung the log")
        stream.write("later\n")                             # and another thread can still log
        stream.close()
        self.assertEqual(self.path.read_text(encoding="utf-8"), "outer\nnested\nnested again\nlater\n")


if __name__ == "__main__":
    unittest.main()
