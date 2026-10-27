"""Linux's background running (E11-S33): lib/systemd.py, the nightly timer (db/schedule.py)
and homenet's systemd user service (homenet/service.py), with a fake systemctl and a unit
folder of the test's own; and the server's SIGTERM stop (control.py), with a real process
on Linux."""
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from decklab.db import schedule, systemd_units
from decklab.lib import config, control, systemd
from decklab.lib.homenet import commands, service
from decklab.tests.homenet_support import FakeTime, Guarded, Quiet, running_state

LINUX = sys.platform.startswith("linux")


class FakeSystemctl:
    """systemctl --user for the tests: daemon-reload reads the unit folder, and enable,
    disable, start, stop, restart and show act on what it read. calls holds every call."""

    def __init__(self, folder):
        self.folder, self.calls, self.loaded = folder, [], set()
        self.enabled, self.active, self.fail = set(), set(), {}
        self.after = None                   # after(args, result): what the call did to the server

    def __call__(self, *args, timeout=None):
        result = self._call(*args)
        if self.after:
            self.after(args, result)
        return result

    def _call(self, *args):
        self.calls.append(args)
        verb, rest = args[0], list(args[1:])
        if verb in self.fail:
            return 1, "", self.fail[verb]
        if verb == "daemon-reload":
            self.loaded = {p.name for p in self.folder.glob("*.service")} | {p.name for p in self.folder.glob("*.timer")}
            return 0, "", ""
        now = "--now" in rest
        units = [u for u in rest if not u.startswith("-")]
        if verb == "show":
            unit = units[0]
            if unit not in self.loaded:
                return 0, "LoadState=not-found\nUnitFileState=\nActiveState=inactive\n", ""
            values = {"LoadState": "loaded", "UnitFileState": "enabled" if unit in self.enabled else "disabled",
                      "ActiveState": "active" if unit in self.active else "inactive",
                      "SubState": "running" if unit in self.active else "dead", "Result": "success",
                      "ExecMainStatus": "0", "NRestarts": "0",
                      "NextElapseUSecRealtime": "Tue 2026-10-27 03:30:00 AEDT" if unit in self.active else "",
                      "LastTriggerUSec": "n/a"}
            return 0, "".join(f"{k}={v}\n" for k, v in values.items()), ""
        for unit in units:
            if unit not in self.loaded:
                return 5, "", f"Failed to {verb} {unit}: Unit {unit} not found."
            if verb == "enable":
                self.enabled.add(unit)
            elif verb == "disable":
                self.enabled.discard(unit)
            if verb in ("start", "restart") or (verb == "enable" and now):
                self.active.add(unit)
            if verb == "stop" or (verb == "disable" and now):
                self.active.discard(unit)
        return 0, "", ""


class SystemdCase(unittest.TestCase):
    """A unit folder of the test's own ($XDG_CONFIG_HOME), a fake systemctl, and lingering off."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        self.units = self.home / "systemd" / "user"
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.home), "USER": "player"})
        env.start()
        self.addCleanup(env.stop)
        self.systemctl = FakeSystemctl(self.units)
        for target, value in ((systemd, "systemctl"), (systemd, "_run")):
            patcher = mock.patch.object(target, value, self.systemctl if value == "systemctl" else
                                        mock.Mock(side_effect=self.loginctl))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.linger = "no"

    def loginctl(self, args, timeout=None):
        self.assertEqual(args[:2], ["loginctl", "show-user"])
        return 0, f"{self.linger}\n", ""


class SystemdHelperTests(SystemdCase):

    def test_unit_dir(self):
        self.assertEqual(systemd.unit_dir({"XDG_CONFIG_HOME": "/x/cfg", "HOME": "/home/p"}),
                         Path("/x/cfg/systemd/user"))
        for env in ({"HOME": "/home/p"}, {"XDG_CONFIG_HOME": "relative", "HOME": "/home/p"}):
            self.assertEqual(systemd.unit_dir(env), Path("/home/p/.config/systemd/user"))

    def test_write_show_and_remove(self):
        self.assertIsNone(systemd.write_units({"a.service": "[Service]\nExecStart=/bin/true\n"}))
        self.assertEqual((self.units / "a.service").read_bytes(), b"[Service]\nExecStart=/bin/true\n")
        self.assertEqual(list(self.units.glob(".*")), [])           # no temp file left
        self.assertEqual(systemd.show("a.service", "LoadState")["LoadState"], "loaded")
        self.assertIsNone(systemd.remove_units(["a.service", "never.service"]))
        self.assertFalse((self.units / "a.service").exists())
        self.assertEqual(self.systemctl.calls.count(("daemon-reload",)), 2)
        self.systemctl.fail["daemon-reload"] = "Failed to connect to bus"
        self.assertIn("Failed to connect to bus", systemd.write_units({"b.service": ""}))

    def test_linger(self):
        self.assertIs(systemd.linger(), False)
        self.assertIn("loginctl enable-linger", systemd.linger_note())
        self.linger = "yes"
        self.assertIs(systemd.linger(), True)
        self.assertIsNone(systemd.linger_note())


class RunTests(unittest.TestCase):

    def test_run_says_what_isnt_there(self):
        code, out, err = systemd._run(["decklab-no-such-program-anywhere"])
        self.assertEqual((code, out), (127, ""))
        self.assertIn("isn't installed", err)

    @unittest.skipUnless(LINUX, "a real program")
    def test_run_gives_the_output(self):
        self.assertEqual(systemd._run(["sh", "-c", "echo out; echo err >&2; exit 3"]), (3, "out\n", "err\n"))


class NightlyTimerTests(SystemdCase):

    def setUp(self):
        super().setUp()
        for name in ("psycopg_problem",):
            patcher = mock.patch.object(schedule, name, return_value=None)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(schedule.sys, "platform", "linux")
        patcher.start()
        self.addCleanup(patcher.stop)

    def say(self):
        said = []
        return said, said.append

    def test_install_status_and_remove(self):
        said, say = self.say()
        self.assertEqual(schedule.install(say=say), 0)
        expected = systemd_units.nightly_units(sys.executable, config.REPO.as_posix(), schedule.AT)
        for name, text in expected.items():
            self.assertEqual((self.units / name).read_text(encoding="utf-8"), text)
        self.assertIn(("enable", "--now", systemd_units.TIMER), self.systemctl.calls)
        self.assertIn(systemd_units.TIMER, self.systemctl.active)
        text = "\n".join(said)
        self.assertIn(f"every day at {schedule.AT}", text)
        self.assertIn(f"{sys.executable} -m decklab.db nightly", text)
        self.assertIn("loginctl enable-linger", text)                 # lingering is off

        lines = schedule.status()
        self.assertIn(f"Nightly timer: {systemd_units.TIMER} runs {systemd_units.SERVICE} daily at 03:30", lines[0])
        self.assertIn("  Next run: Tue 2026-10-27 03:30:00 AEDT.", lines)
        self.assertFalse(any("WARNING" in line for line in lines), lines)

        # The repo moved, or Python changed: the units are out of date.
        (self.units / systemd_units.SERVICE).write_text(expected[systemd_units.SERVICE].replace(
            "WorkingDirectory=", "WorkingDirectory=/old"), encoding="utf-8")
        self.assertTrue(any("aren't what install writes now" in line for line in schedule.status()))
        # Disabled by hand.
        self.systemctl.enabled.discard(systemd_units.TIMER)
        self.assertTrue(any("isn't enabled and active" in line for line in schedule.status()))

        said, say = self.say()
        self.assertEqual(schedule.remove(say=say), 0)
        self.assertIn(("disable", "--now", systemd_units.TIMER), self.systemctl.calls)
        self.assertEqual(list(self.units.iterdir()), [])
        self.assertIn("no longer backed up", said[-1])
        said, say = self.say()
        self.assertEqual(schedule.remove(say=say), 0)
        self.assertIn("nothing to remove", said[-1])
        self.assertIn("isn't installed", schedule.status()[0])

    def test_install_refusals(self):
        said, say = self.say()
        with mock.patch.object(schedule, "psycopg_problem", return_value="psycopg can't be imported"):
            self.assertEqual(schedule.install(say=say), 1)
        self.assertEqual(said, ["psycopg can't be imported"])
        self.assertEqual(self.systemctl.calls, [])
        said, say = self.say()
        self.systemctl.fail["enable"] = "Failed to connect to bus: No medium found"
        self.assertEqual(schedule.install(say=say), 1)
        self.assertIn("couldn't be enabled: Failed to connect to bus", said[-1])
        said, say = self.say()
        with mock.patch.object(schedule.sys, "executable", '/opt/py"thon'):
            self.assertEqual(schedule.install(say=say), 1)
        self.assertIn("can't be written for this Python and repo", said[-1])

    def test_status_when_the_manager_cant_be_asked(self):
        self.assertEqual(schedule.install(say=lambda text: None), 0)
        self.systemctl.fail["show"] = "Failed to connect to bus"
        self.assertIn("can't be asked", schedule.status()[1])

    def test_other_systems(self):
        with mock.patch.object(schedule.sys, "platform", "darwin"):
            said, say = self.say()
            self.assertEqual(schedule.install(say=say), 1)
            self.assertIn("from cron", said[0])
            self.assertIn("from cron", schedule.status()[0])
        self.assertEqual(self.systemctl.calls, [])


class ServiceUnitTests(unittest.TestCase):

    def test_unit_text(self):
        args = service.arguments(port=8650, host="127.0.0.1", log_path="/srv/Deck Lab/50%.log",
                                 script="/srv/Deck Lab/decklab/server.py")
        text = service.unit_text("/usr/bin/python3.14", "/srv/Deck Lab", args)
        self.assertIn("WorkingDirectory=/srv/Deck Lab\n", text)
        self.assertIn('ExecStart=":/usr/bin/python3.14" "/srv/Deck Lab/decklab/server.py" "--background" '
                      '"--host" "127.0.0.1" "--port" "8650" "--log" "/srv/Deck Lab/50%%.log"\n', text)
        self.assertIn("Restart=on-failure\n", text)
        self.assertIn("WantedBy=default.target\n", text)
        self.assertEqual(service._quote('a"b\\c'), '"a\\"b\\\\c"')
        for bad in (("relative/python", "/srv"), ("/usr/bin/python", "C:\\Deck Lab"), ("/usr/bin/py\nthon", "/srv")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                service.unit_text(*bad, args)
        with self.assertRaises(ValueError):
            service.unit_text("/usr/bin/python", "/srv", ["x\ny"])

    def test_service_names(self):
        self.assertEqual(service.service_name(), "decklab.service")
        self.assertEqual(service.service_name("Deck Lab test"), "deck-lab-test.service")

    @unittest.skipUnless(LINUX and Path("/usr/bin/systemd-analyze").exists(), "systemd-analyze checks the unit")
    def test_systemd_analyze_accepts_the_units(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder) / "Deck Lab"
            (repo / "decklab").mkdir(parents=True)
            (repo / "decklab" / "server.py").write_text("", encoding="utf-8")
            units = systemd_units.nightly_units(sys.executable, repo.as_posix())
            units[service.SERVICE] = service.unit_text(sys.executable, repo.as_posix(),
                                                       service.arguments(script=repo / "decklab" / "server.py"))
            for name, text in units.items():
                (Path(folder) / name).write_text(text, encoding="utf-8")
            runtime = Path(folder) / "runtime"          # a user manager's runtime folder, for verify only
            runtime.mkdir(mode=0o700)
            done = subprocess.run(["systemd-analyze", "--user", "verify", "--man=no",
                                   *(str(Path(folder) / n) for n in units)],
                                  capture_output=True, text=True, timeout=60,
                                  env={**os.environ, "XDG_RUNTIME_DIR": str(runtime)})
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            # Warnings about a unit (an unknown key, say) name its file; other lines are about the host.
            problems = [line for line in (done.stdout + done.stderr).splitlines() if folder in line]
            self.assertEqual(problems, [], done.stdout + done.stderr)


class ServiceCommandTests(SystemdCase, Guarded):
    """homenet's commands on Linux, through main, with the fake systemctl."""

    def setUp(self):
        SystemdCase.setUp(self)
        Guarded.setUp(self)
        self.patch("decklab.lib.homenet.commands.uses_systemd", return_value=True)
        self.patch("decklab.lib.homenet.commands.time", FakeTime())
        self.answer = {"answered": False, "listening": False, "error": "refused"}
        self.probe = self.patch("decklab.lib.homenet.commands.probe", side_effect=lambda *a, **k: self.answer)
        self.patch("decklab.lib.homenet.commands.local_ipv4", return_value="192.168.1.20")
        self.patch("decklab.lib.homenet.commands.newest_code_mtime", return_value=None)
        self.patch("decklab.lib.profiles.read_checked", return_value=None)
        self.unit = self.units / "deck-lab-test.service"

        def after(args, result):
            # A start or restart: the server answers from then on; a stop: it's gone.
            if args[0] in ("start", "restart") and result[0] == 0:
                self.answer = {"answered": True, "deck_lab": True, "cards_ready": True}
                self.control.read_state.return_value = running_state(port=18642, background=True)
            if args[0] == "stop" and result[0] == 0:
                self.answer = {"answered": False, "listening": False, "error": "refused"}
                self.control.read_state.return_value = None
        self.systemctl.after = after

    def main(self, *argv):
        with Quiet() as q:
            code = commands.main([*argv, "--task", "Deck Lab test", "--port", "18642"])
        return code, q.text

    def test_install_start_restart_stop_and_remove(self):
        code, text = self.main("install", "--no-start")
        self.assertEqual(code, 0, text)
        unit = self.unit.read_text(encoding="utf-8")
        self.assertIn(f'ExecStart=":{sys.executable}" "{commands.SERVER_SCRIPT}" "--background" '
                      '"--port" "18642"\n', unit)
        self.assertIn(f"WorkingDirectory={config.REPO.as_posix()}\n", unit)
        self.assertIn(("disable", "deck-lab-test.service"), self.systemctl.calls)
        self.assertIn("doesn't start at logon", text)
        self.assertNotIn(("start", "deck-lab-test.service"), self.systemctl.calls)

        code, text = self.main("start")
        self.assertEqual(code, 0, text)
        self.assertIn("Deck Lab is running.", text)
        self.assertIn("http://192.168.1.20:18642", text)
        self.control.clear_stopped.assert_called_with(18642)
        code, text = self.main("start")
        self.assertEqual(code, 0, text)
        self.assertIn("already running", text)

        code, text = self.main("restart")
        self.assertEqual(code, 0, text)
        self.assertIn(("restart", "deck-lab-test.service"), self.systemctl.calls)

        code, text = self.main("stop")
        self.assertEqual(code, 0, text)
        self.assertIn(("stop", "deck-lab-test.service"), self.systemctl.calls)
        self.control.mark_stopped.assert_called_with(18642, "homenet stop")
        self.control.request_stop.assert_not_called()

        code, text = self.main("remove")
        self.assertEqual(code, 0, text)
        self.assertFalse(self.unit.exists())
        self.assertIn("Removed the deck-lab-test.service service", text)
        code, text = self.main("remove")
        self.assertIn("nothing to remove", text)

    def test_install_at_logon_starts_it(self):
        code, text = self.main("install", "--at-logon", "--host", "127.0.0.1")
        self.assertEqual(code, 0, text)
        self.assertIn("deck-lab-test.service", self.systemctl.enabled)
        self.assertIn('"--host" "127.0.0.1"', self.unit.read_text(encoding="utf-8"))
        self.assertIn("It starts when you log in.", text)
        self.assertIn("loginctl enable-linger", text)
        self.assertIn("Deck Lab is running.", text)

    def test_install_checks_the_profiles(self):
        self.patch("decklab.lib.profiles.read_checked", side_effect=OSError("unreadable"))
        code, text = self.main("install")
        self.assertEqual(code, 1)
        self.assertIn("Profile configuration could not be checked", text)
        self.assertFalse(self.unit.exists())

    def test_start_needs_the_service(self):
        code, text = self.main("start")
        self.assertEqual(code, 1)
        self.assertIn("isn't installed: run python -m decklab.lib.homenet install first", text)
        self.assertEqual(self.systemctl.calls, [])

    def test_a_start_that_doesnt_answer(self):
        self.main("install", "--no-start")
        self.systemctl.after = None
        self.control.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        code, text = self.main("start")
        self.assertEqual(code, 1)
        self.assertIn("didn't answer on port 18642", text)
        self.assertIn("journalctl --user -u decklab.service", text)

    def test_stop_without_the_service_stops_a_terminals_server(self):
        self.control.request_stop.return_value = "stopped"
        code, text = self.main("stop")
        self.assertEqual(code, 0, text)
        self.control.request_stop.assert_called_once_with(18642, wait=commands.STOP_WAIT)

    def test_status(self):
        self.main("install", "--at-logon")
        code, text = self.main("status")
        self.assertEqual(code, 0, text)
        self.assertIn("Server: Running since", text)
        self.assertIn("in the background", text)
        self.assertIn("Service: deck-lab-test.service is installed (starts at logon); it's active (running).", text)
        self.assertIn("starts when you log in, not at boot", text)
        self.unit.write_text(self.unit.read_text(encoding="utf-8").replace("WorkingDirectory=", "WorkingDirectory=/old"),
                             encoding="utf-8")
        code, text = self.main("status")
        self.assertIn("Its unit isn't what install writes now", text)
        self.main("remove")
        code, text = self.main("status")
        self.assertEqual(code, 1)
        self.assertIn("systemd user service isn't installed, so Deck Lab runs", text)
        self.assertIn("isn't running on port 18642", text)


@unittest.skipUnless(LINUX, "SIGTERM and /proc are Linux's")
class SigtermStopTests(unittest.TestCase):
    """A real server-like process: control.listen_for_stop's SIGTERM handler, and request_stop's
    SIGTERM to the process the state file names."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.state = self.folder / "server.json"

    def start_server(self):
        script = self.folder / "server.py"           # _is_server knows a server by its script's name
        script.write_text(textwrap.dedent(f"""
            import os, sys, threading
            sys.path.insert(0, {str(config.REPO)!r})
            from decklab.lib import control
            stopped = threading.Event()
            listener = control.listen_for_stop(18999, stopped.set)
            control.write_state({{"version": 1, "pid": os.getpid(), "port": 18999, "host": "127.0.0.1",
                                  "started": "2026-10-27T10:00:00", "python": sys.executable}}, {str(self.state)!r})
            print("ready", flush=True)
            stopped.wait(30)
            listener.close()
            print("clean", flush=True)
        """), encoding="utf-8")
        child = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(child.stdout.close)
        self.addCleanup(lambda: (child.poll() is None and child.kill(), child.wait()))
        self.assertEqual(child.stdout.readline().strip(), "ready")
        return child

    def test_request_stop_sends_sigterm_and_waits(self):
        child = self.start_server()
        with mock.patch.object(control.sys, "platform", "linux"):
            self.assertEqual(control.request_stop(18999, wait=10, path=self.state), "stopped")
        self.assertEqual(child.wait(5), 0)                 # it stopped on its own, cleanly
        self.assertEqual(child.stdout.read().strip(), "clean")

    def test_nothing_is_signalled_without_a_server(self):
        self.assertEqual(control.request_stop(18999, wait=0, path=self.state), "not running")
        # A state file naming a process that isn't a server (a reused process id): left alone.
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(lambda: (sleeper.kill(), sleeper.wait()))
        control.write_state({"version": 1, "pid": sleeper.pid, "port": 18999, "started": "2026-10-27T10:00:00"},
                            self.state)
        self.assertEqual(control.request_stop(18999, wait=0, path=self.state), "not running")
        self.assertIsNone(sleeper.poll())
        # Another port's server isn't this one.
        self.assertEqual(control.request_stop(18998, wait=0, path=self.state), "not running")

    def test_the_handler_only_from_the_main_thread_and_close_restores(self):
        before = signal.getsignal(signal.SIGTERM)
        found = []
        thread = threading.Thread(target=lambda: found.append(control.listen_for_stop(1, lambda: None)))
        thread.start()
        thread.join()
        self.assertIsInstance(found[0], control._NoListener)
        stops = []
        listener = control.listen_for_stop(1, lambda: stops.append(1))
        self.assertIsNot(signal.getsignal(signal.SIGTERM), before)
        os.kill(os.getpid(), signal.SIGTERM)
        os.kill(os.getpid(), signal.SIGTERM)                # heard once
        deadline = time.monotonic() + 5
        while not stops and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.05)
        self.assertEqual(stops, [1])
        listener.close()
        self.assertIs(signal.getsignal(signal.SIGTERM), before)


if __name__ == "__main__":
    unittest.main()
