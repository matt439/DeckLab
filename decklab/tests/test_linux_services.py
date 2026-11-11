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
from decklab.lib.homenet import commands, linux_power, service
from decklab.tests.homenet_support import FakeTime, Guarded, Quiet, running_state

# service._power_lines itself, before a test's patch replaces it (the status tests feed it facts).
REAL_POWER_LINES = service._power_lines

LINUX = sys.platform.startswith("linux")
# What linux_facts.network reads for a PC on the home Wi-Fi's router by cable.
NETWORK = {"interfaces": [{"if_index": 2, "alias": "eth0", "status": "Up", "virtual": False,
                           "mac": "00:11:22:33:44:55",
                           "ipv4": [{"address": "192.168.1.20", "prefix": 24, "origin": "Dhcp"}]}],
           "routes": [{"if_index": 2, "metric": 100, "next_hop": "192.168.1.1"}]}


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


@unittest.skipUnless(LINUX, "the units are written for this Python and repo, as POSIX paths")
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

    def test_a_shell_without_the_user_bus_gets_a_hint(self):
        calls = []

        def run(args, timeout=None, env=None):
            calls.append((args, env))
            return 1, "", "Failed to connect to bus: No medium found\n"
        with mock.patch.object(systemd, "_run", run), mock.patch.object(systemd, "user_environment",
                                                                          return_value=None):
            code, _, err = systemd.systemctl("show", "decklab.service")
        self.assertEqual(code, 1)
        self.assertIn("Failed to connect to bus: No medium found", err)
        self.assertIn("export XDG_RUNTIME_DIR=/run/user/$(id -u)", err)
        self.assertIn("machinectl shell", err)
        self.assertIn("Failed to connect to bus", systemd.said("", err, 1))
        # Another failure is passed on as it is.
        with mock.patch.object(systemd, "_run", lambda args, timeout=None, env=None: (5, "", "Unit x not found.")), \
                mock.patch.object(systemd, "user_environment", return_value=None):
            self.assertEqual(systemd.systemctl("start", "x"), (5, "", "Unit x not found."))

    def test_xdg_runtime_dir_is_given_when_missing_and_ours(self):
        ours = mock.Mock(return_value=mock.Mock(st_uid=1000))
        theirs = mock.Mock(return_value=mock.Mock(st_uid=0))
        missing = mock.Mock(side_effect=FileNotFoundError())
        with mock.patch.object(systemd.os, "getuid", create=True, return_value=1000):
            self.assertEqual(systemd.user_environment({"HOME": "/home/p"}, 1000, ours),
                             {"HOME": "/home/p", "XDG_RUNTIME_DIR": "/run/user/1000"})
            ours.assert_called_once_with("/run/user/1000")
            self.assertIsNone(systemd.user_environment({"XDG_RUNTIME_DIR": "/run/user/1000"}, 1000, ours))
            self.assertIsNone(systemd.user_environment({}, 1000, theirs))
            self.assertIsNone(systemd.user_environment({}, 1000, missing))
        calls = []
        with mock.patch.object(systemd, "user_environment", return_value={"XDG_RUNTIME_DIR": "/run/user/7"}), \
                mock.patch.object(systemd, "_run",
                                  lambda args, timeout=None, env=None: calls.append(env) or (0, "", "")):
            systemd.systemctl("daemon-reload")
        self.assertEqual(calls, [{"XDG_RUNTIME_DIR": "/run/user/7"}])

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
            self.assertIn("launchd/cron job", said[0])
            self.assertIn("launchd/cron job", schedule.status()[0])
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
        # Hardening and a give-up, as the Windows watchdog gives up.
        self.assertIn("UMask=0077\n", text)
        self.assertIn(f"StartLimitIntervalSec={service.GIVE_UP_WITHIN}\nStartLimitBurst=3\n", text)
        self.assertLess(text.index("StartLimitBurst"), text.index("[Service]"))      # [Unit]'s settings
        self.assertNotIn("Environment=", text)
        env = service.environment({"PATH": "/home/p/.local/bin:/usr/bin:/50%", "JAVA_HOME": "/opt/jdk 21",
                                   "HOME": "/home/p", "LANG": "C"})
        self.assertEqual(env, {"PATH": "/home/p/.local/bin:/usr/bin:/50%", "JAVA_HOME": "/opt/jdk 21"})
        self.assertEqual(service.environment({"PATH": "/usr/bin\n", "JAVA_HOME": ""}), {})
        text = service.unit_text("/usr/bin/python3.14", "/srv/Deck Lab", args, env=env)
        self.assertIn('Environment="PATH=/home/p/.local/bin:/usr/bin:/50%%"\n'
                      'Environment="JAVA_HOME=/opt/jdk 21"\nUMask=0077\n', text)
        parts = service.unit_parts(text)
        self.assertEqual(parts, {"program": "/usr/bin/python3.14", "args": args, "workdir": "/srv/Deck Lab",
                                 "env": env})
        self.assertEqual(service.unit_text("/usr/bin/python3.14", "/srv/Deck Lab", parts["args"], env=parts["env"]),
                         text)
        self.assertIsNone(service.unit_parts("[Service]\nExecStart=/usr/bin/python3 x\n"))
        self.assertEqual(service._quote('a"b\\c'), '"a\\"b\\\\c"')
        for bad in (("relative/python", "/srv"), ("/usr/bin/python", "C:\\Deck Lab"), ("/usr/bin/py\nthon", "/srv")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                service.unit_text(*bad, args)
        with self.assertRaises(ValueError):
            service.unit_text("/usr/bin/python", "/srv", ["x\ny"])

    def test_the_log_and_whether_it_can_still_start(self):
        parts = {"program": "/usr/bin/python3", "workdir": "/srv/deck",
                 "args": ["/srv/deck/decklab/server.py", "--background", "--log", "logs/mine.log"], "env": {}}
        self.assertEqual(service.unit_log_file(parts), Path("/srv/deck/logs/mine.log"))
        self.assertEqual(service.unit_log_file({**parts, "args": parts["args"][:2]}), commands.control.LOG_FILE)
        self.assertEqual(service.unit_log_file(None), commands.control.LOG_FILE)
        there = {"/usr/bin/python3", "/srv/deck/decklab/server.py"}
        runnable = there.__contains__
        self.assertIsNone(service.unit_problem(parts, exists=there.__contains__, runnable=runnable))
        problem = service.unit_problem({**parts, "program": "/usr/bin/python3.12"}, there.__contains__, runnable)
        self.assertIn("the Python it runs (/usr/bin/python3.12) isn't there any more", problem)
        self.assertIn("install again", problem)
        problem = service.unit_problem({**parts, "args": ["/old/decklab/server.py"]}, there.__contains__, runnable)
        self.assertIn("the server it runs (/old/decklab/server.py) isn't there any more", problem)
        self.assertIn("doesn't run Deck Lab", service.unit_problem(None))

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
        # status's network reads and the .local lookup (linux_facts and mdns have tests of their own).
        self.facts = {"network": NETWORK, "firewall": {"active": [], "zone": None, "port": None, "mdns": None},
                      "errors": {}}
        self.patch("decklab.lib.homenet.linux_facts.read_facts", side_effect=lambda port: self.facts)
        self.patch("decklab.lib.homenet.mdns.mdns_lookup",
                   return_value={"answered": True, "addresses": ["192.168.1.20"]})
        self.patch("decklab.lib.homenet.commands.pc_name", return_value="decklab-pc.home.arpa")
        # status's sleep and wake reads (linux_power has tests of its own, in test_linux_wake).
        self.power_facts = {"logind": {"IdleAction": "ignore", "files": []}, "suspend_target": "enabled",
                            "inhibit_tool": "/usr/bin/systemd-inhibit"}
        self.power = self.patch("decklab.lib.homenet.service._power_lines", side_effect=lambda settings: REAL_POWER_LINES(
            settings, lambda s: linux_power.status_lines(s, facts=self.power_facts)))
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

    def test_start_and_restart_clear_a_give_up_first(self):
        self.main("install", "--no-start")
        code, text = self.main("start")
        self.assertEqual(code, 0, text)
        calls = self.systemctl.calls
        self.assertLess(calls.index(("reset-failed", "deck-lab-test.service")),
                        calls.index(("start", "deck-lab-test.service")))
        self.systemctl.calls.clear()
        self.main("restart")
        self.assertEqual(self.systemctl.calls[-2:], [("reset-failed", "deck-lab-test.service"),
                                                     ("restart", "deck-lab-test.service")])

    def test_start_and_restart_refuse_when_the_python_has_gone(self):
        self.main("install", "--no-start")
        self.unit.write_text(self.unit.read_text(encoding="utf-8").replace(sys.executable, "/nowhere/python3.9"),
                             encoding="utf-8")
        self.systemctl.calls.clear()
        for verb in ("start", "restart"):
            with self.subTest(verb=verb):
                code, text = self.main(verb)
                text = " ".join(text.split())
                self.assertEqual(code, 1, text)
                self.assertIn("the Python it runs (/nowhere/python3.9) isn't there any more", text)
                self.assertIn("Nothing was stopped or started", text)
        self.assertFalse([c for c in self.systemctl.calls if c[0] in ("start", "restart", "stop")],
                         self.systemctl.calls)
        code, text = self.main("status")
        self.assertIn("isn't there any more", " ".join(text.split()))

    def test_a_start_that_doesnt_answer_shows_the_units_own_log(self):
        log_file = self.home / "elsewhere.log"
        self.main("install", "--no-start", "--log", str(log_file))
        self.systemctl.after = lambda args, result: (args[0] == "start" and log_file.write_text(
            "Traceback: it broke\n", encoding="utf-8"))
        code, text = self.main("start")
        self.assertEqual(code, 1)
        text = " ".join(text.split())
        self.assertIn(f"What it wrote to its log ({log_file}) after the start:", text)
        self.assertIn("Traceback: it broke", text)

    def test_status_has_the_network_firewall_and_addresses(self):
        self.main("install", "--at-logon")
        code, text = self.main("status")
        text = " ".join(text.split())
        self.assertIn("Network: eth0: 192.168.1.20/24 from the router (DHCP).", text)
        self.assertIn("No firewall service is on", text)
        self.assertIn("From a phone or tablet: http://192.168.1.20:18642/", text)
        self.assertIn("http://decklab-pc.local:18642/", text)          # the first label, as avahi says it
        self.assertIn("reserve 192.168.1.20 for this PC in the router (MAC address 00:11:22:33:44:55)", text)
        self.assertIn("the real test is opening the address above", text)
        # Nothing read: say so, and the footer doesn't point at an address that isn't shown.
        self.facts = {"network": None, "firewall": None,
                      "errors": {"network": "ip isn't installed", "firewall": "systemctl isn't installed"}}
        self.patch("decklab.lib.homenet.mdns.mdns_lookup", return_value={"answered": False, "addresses": [],
                                                                         "error": "no answer"})
        code, text = self.main("status")
        text = " ".join(text.split())
        self.assertIn("Couldn't check the network: ip isn't installed", text)
        self.assertIn("Couldn't check the firewall: systemctl isn't installed", text)
        self.assertNotIn("the address above", text)
        self.assertIn("http://decklab-pc.local:18642/ (or the PC's IP address)", text)

    def test_status_checks_the_tunnels_listener(self):
        self.main("install", "--at-logon")
        settings = {"tunnel": {"config": str(self.home / "config.yml"), "hostname": "decklab.example.com"},
                    "access": {"team": "your-team", "aud": "ab" * 32, "port": 18644}}
        self.patch("decklab.lib.config.load", return_value=settings)
        self.patch("decklab.lib.tunnel.settings_of", side_effect=lambda s: {
            "config": self.home / "config.yml", "hostname": "decklab.example.com"} if s.get("tunnel") else None)
        self.patch("decklab.lib.tunnel.check_public", return_value=("login", "https://decklab.example.com answers "
                                                                             "with Cloudflare Access's login"))
        listener = self.patch("decklab.lib.tunnel.check_listener", return_value=(
            "refuses", "The tunnel's listener (127.0.0.1:18644) refuses visits without a Cloudflare Access login"))
        code, text = self.main("status")
        listener.assert_called_once_with(18644, "decklab.example.com", commands.PROBE_TIMEOUT)
        self.assertIn("refuses visits without a Cloudflare Access login", " ".join(text.split()))

    def test_status_has_the_sleep_lines(self):
        self.main("install", "--at-logon")
        code, text = self.main("status")
        self.power.assert_called_once()
        self.assertIn("Nothing here suspends the PC when idle (logind's IdleAction is ignore)", " ".join(text.split()))

    def test_a_broken_sleep_check_is_one_line(self):
        broken = mock.Mock(side_effect=RuntimeError("busctl broke"))
        self.assertIn("Couldn't check sleep and wake: RuntimeError: busctl broke",
                      REAL_POWER_LINES({}, broken)[0]["text"])
        self.power.side_effect = lambda settings: REAL_POWER_LINES(settings, broken)
        self.main("install", "--at-logon")
        code, text = self.main("status")
        self.assertIn("Couldn't check sleep and wake: RuntimeError: busctl broke", " ".join(text.split()))

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
        self.linger = "yes"
        code, text = self.main("status")
        self.assertIn("is installed (starts at boot (lingering)); it's active", " ".join(text.split()))
        self.assertNotIn("not at boot", text)
        self.linger = "no"
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
                                  "started": "2026-10-27T10:00:00", "python": sys.executable,
                                  "start_ticks": control.process_ticks(os.getpid())}}, {str(self.state)!r})
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
