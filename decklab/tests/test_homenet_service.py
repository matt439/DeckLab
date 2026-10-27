"""Tests for homenet's systemd user service off Windows (lib/homenet/service.py, E11-S33) and the
nightly systemd timer (db/schedule.py's install_systemd, remove_systemd and status_systemd).

Nothing here reaches a real systemd: systemctl is replaced by a fake that records its calls and
keeps what's enabled and active, and the units go in a folder of the test's own (Guarded). The
commands run as they do on Linux (sys.platform is "linux" in each command test). When
systemd-analyze is installed, the units written are also checked with systemd-analyze verify.

Run from the repo root: python -m unittest decklab.tests.test_homenet_service
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.db import schedule, systemd_units
from decklab.lib import config, homenet
from decklab.lib.homenet import OK, PROBLEM, WARN, service
from decklab.tests.homenet_support import FakeTime, Guarded, Quiet, running_state

POSIX_PYTHON = "/opt/python 3.14/bin/python3.14"
REPO = "/srv/Deck Lab"
ANALYZE = shutil.which("systemd-analyze")
WINDOWS = sys.platform == "win32"


class FakeSystemd:
    """systemctl --user's stand-in: daemon-reload, enable, disable, start, stop, reset-failed and
    show, over a dict of units. fail names a verb that fails."""

    def __init__(self, fail=None):
        self.calls, self.enabled, self.active, self.fail = [], set(), set(), fail
        self.on_start = None

    def __call__(self, *args, timeout=None):
        self.calls.append(args)
        verb = args[0]
        if verb == self.fail:
            return 1, "", f"Failed to {verb}: Access denied"
        units = [a for a in args[1:] if not a.startswith("-")]
        if verb == "enable":
            self.enabled.update(units)
            if "--now" in args:
                self.active.update(units)
        elif verb == "disable":
            self.enabled.difference_update(units)
            if "--now" in args:
                self.active.difference_update(units)
        elif verb == "start":
            self.active.update(units)
            if self.on_start:
                self.on_start()
        elif verb == "stop":
            self.active.difference_update(units)
        elif verb == "show":
            unit = units[0]
            return 0, (f"LoadState=loaded\nActiveState={'active' if unit in self.active else 'inactive'}\n"
                       f"SubState=running\nUnitFileState={'enabled' if unit in self.enabled else 'disabled'}\n"
                       "ExecMainStatus=0\nNRestarts=0\n"), ""
        return 0, "", ""

    def verbs(self):
        return [c[0] for c in self.calls]


class UnitTextTests(unittest.TestCase):

    def test_round_trip_keeps_spaces_quotes_backslashes_and_percent(self):
        argv = service.server_argv("/srv/Deck Lab/decklab/server.py", 8643, '/var/log/deck "lab"\\100%.log',
                                   "127.0.0.1")
        text = service.service_unit(POSIX_PYTHON, argv, "/srv/Deck 100% Lab")
        self.assertIn("WorkingDirectory=/srv/Deck 100%% Lab", text)
        self.assertIn('"/var/log/deck \\"lab\\"\\\\100%%.log"', text)
        parsed = service.parse_unit(text)
        self.assertEqual(parsed, {"python": POSIX_PYTHON, "argv": argv, "workdir": "/srv/Deck 100% Lab"})
        self.assertEqual(argv[:2], ["/srv/Deck Lab/decklab/server.py", "--background"])

    def test_it_restarts_after_a_crash_and_not_after_a_stop(self):
        text = service.service_unit(POSIX_PYTHON, service.server_argv("/x/server.py", log_path="/x/l"), REPO)
        for directive in ("Type=simple", "Restart=on-failure", "KillMode=mixed", "WantedBy=default.target",
                          "StartLimitBurst=5"):
            self.assertIn(directive, text)
        self.assertTrue(text.endswith("\n") and "\r" not in text)

    def test_paths_it_cant_write(self):
        for python, workdir in (("python3", REPO), (POSIX_PYTHON, "relative"), (POSIX_PYTHON, "/a\nb"),
                                (POSIX_PYTHON, "/ends\\")):
            with self.subTest(python=python, workdir=workdir), self.assertRaises(ValueError):
                service.service_unit(python, ["/x/server.py"], workdir)
        with self.assertRaises(ValueError):
            service.service_unit(POSIX_PYTHON, ["/x/server.py", "a\tb"], REPO)

    def test_unit_names(self):
        self.assertEqual(service.unit_name(homenet.TASK_NAME), "decklab.service")
        self.assertEqual(service.unit_name("Deck Lab test"), "decklab-deck-lab-test.service")

    def test_unit_folder_follows_xdg(self):
        with mock.patch.object(service, "UNIT_DIR", None):
            self.assertEqual(service.unit_dir({"XDG_CONFIG_HOME": "/c", "HOME": "/h"}), Path("/c/systemd/user"))
            self.assertEqual(service.unit_dir({"HOME": "/h"}), Path("/h/.config/systemd/user"))

    @unittest.skipUnless(ANALYZE and not WINDOWS, "systemd-analyze isn't installed")
    def test_systemd_accepts_the_units(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            argv = service.server_argv(str(config.DECKLAB / "server.py"), 8642, "/tmp/deck 100% lab.log", "0.0.0.0")
            (folder / "decklab.service").write_text(service.service_unit(sys.executable, argv, str(config.REPO),
                                                                         True), encoding="utf-8")
            for name, text in systemd_units.nightly_units(sys.executable, str(config.REPO)).items():
                (folder / name).write_text(text, encoding="utf-8")
            done = subprocess.run([ANALYZE, "verify", "--man=no", *sorted(str(p) for p in folder.iterdir())],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


@unittest.skipIf(WINDOWS, "the units name this Python and repo, which need POSIX paths")
class ServiceCommandTests(Guarded):
    """homenet install, start, restart, remove and status as on Linux."""

    def setUp(self):
        super().setUp()
        self.systemd = FakeSystemd()
        self.systemctl.side_effect = self.systemd
        self.patch("decklab.lib.homenet.commands.sys.platform", "linux")
        self.find = self.patch("decklab.lib.homenet.commands.find_server", return_value=(None, {"answered": False}))
        self.patch("decklab.lib.homenet.commands.local_ipv4", return_value="192.0.2.10")
        self.patch("decklab.lib.homenet.commands.time", FakeTime())
        self.patch("decklab.lib.homenet.commands.file_exists", return_value=True)
        self.probe = self.patch("decklab.lib.homenet.commands.probe",
                                return_value={"answered": True, "deck_lab": True})
        self.patch("decklab.lib.profiles.read_checked", return_value=[])
        self.folder = self.data / "systemd-user"

    def unit(self, name="decklab-deck-lab-test.service"):
        return (self.folder / name).read_text(encoding="utf-8")

    def test_install_writes_the_unit_reloads_and_starts_it(self):
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_install("Deck Lab test", 18642, port_given=True), 0)
        parsed = service.parse_unit(self.unit())
        self.assertEqual(parsed["python"], sys.executable)
        self.assertEqual(parsed["workdir"], str(config.REPO))
        self.assertEqual(parsed["argv"], [str(homenet.SERVER_SCRIPT), "--background", "--port", "18642",
                                          "--log", str(self.control.LOG_FILE)])
        self.assertEqual(self.systemd.verbs(), ["daemon-reload", "disable", "reset-failed", "start"])
        self.assertIn("python -m decklab.lib.homenet start runs it", q.text)
        self.assertIn("doesn't start at logon", q.text)
        self.assertIn("Deck Lab is running.", q.text)
        self.schtasks.assert_not_called()

    def test_install_at_logon_enables_it_and_no_start_leaves_it_off(self):
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_install("Deck Lab test", 18642, no_start=True, at_logon=True), 0)
        self.assertEqual(self.systemd.verbs(), ["daemon-reload", "enable"])
        self.assertIn("decklab-deck-lab-test.service", self.systemd.enabled)
        self.assertIn("loginctl enable-linger", q.text)
        self.assertIn("It starts at the next logon, or now with", q.text)
        self.assertIn("--at-logon", self.unit())

    def test_install_without_a_systemd_session(self):
        self.systemd.fail = "daemon-reload"
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_install("Deck Lab test", 18642), 1)
        self.assertIn("systemd couldn't reload its units", q.text)
        self.assertIn("systemd user session", q.text)

    def test_install_leaves_a_running_server_alone(self):
        self.find.return_value = (running_state(port=18642), {"answered": True, "deck_lab": True})
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_install("Deck Lab test", 18642, no_start=False), 0)
        self.assertNotIn("start", self.systemd.verbs())
        self.assertIn("It wasn't started a second time", q.text)

    def test_start_needs_the_unit(self):
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_start("Deck Lab test", 18642), 1)
        self.assertIn("isn't installed: run python -m decklab.lib.homenet install first", q.text)
        self.assertEqual(self.systemd.calls, [])

    def test_start_a_unit_whose_python_has_gone(self):
        with Quiet():
            homenet.commands.cmd_install("Deck Lab test", 18642, no_start=True)
        self.patch("decklab.lib.homenet.commands.file_exists", side_effect=lambda p: p != sys.executable)
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_start("Deck Lab test", 18642), 1)
        self.assertIn(f"The service starts {sys.executable}, which isn't there any more", q.text)
        self.assertIn("install again", q.text)

    def test_start_that_doesnt_answer_shows_the_log_and_journal(self):
        with Quiet():
            homenet.commands.cmd_install("Deck Lab test", 18642, no_start=True)
        self.probe.return_value = {"answered": False}
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_start("Deck Lab test", 18642), 1)
        self.assertIn("didn't answer on port 18642", q.text)
        self.assertIn("systemctl --user status decklab-deck-lab-test.service shows why", q.text)
        self.assertEqual(self.systemd.verbs().count("start"), 1)        # systemd isn't asked twice

    def test_start_systemd_refuses(self):
        with Quiet():
            homenet.commands.cmd_install("Deck Lab test", 18642, no_start=True)
        self.systemd.fail = "start"
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_start("Deck Lab test", 18642), 1)
        self.assertIn("systemd couldn't start decklab-deck-lab-test.service: Failed to start", q.text)

    def test_restart_stops_then_starts(self):
        with Quiet():
            homenet.commands.cmd_install("Deck Lab test", 18642, no_start=True)
        self.control.request_stop.return_value = "stopped"
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_restart("Deck Lab test", 18642), 0)
        self.assertIn("Deck Lab stopped.", q.text)
        self.assertEqual(self.systemd.verbs()[-1], "start")
        self.control.request_stop.return_value = "timeout"
        self.find.return_value = (running_state(port=18642), {"answered": True, "deck_lab": True})
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_restart("Deck Lab test", 18642), 1)
        self.assertIn("It wasn't started again", q.text)

    def test_remove_disables_and_deletes_the_unit(self):
        with Quiet():
            homenet.commands.cmd_install("Deck Lab test", 18642, no_start=True, at_logon=True)
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_remove("Deck Lab test", 18642), 0)
        self.assertFalse((self.folder / "decklab-deck-lab-test.service").exists())
        self.assertEqual(self.systemd.verbs()[-3:], ["stop", "disable", "daemon-reload"])
        self.assertEqual(self.systemd.enabled, set())
        self.assertIn("Removed the decklab-deck-lab-test.service service", q.text)
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_remove("Deck Lab test", 18642), 0)
        self.assertIn("isn't installed, so there was nothing to remove", q.text)

    def status(self, running=False, systemd=None, name="Deck Lab test"):
        return service.status_lines(name, 18642, running, exists=lambda p: True, systemd=systemd)

    def test_status_lines(self):
        lines = self.status()
        self.assertEqual([(l["level"], l["area"]) for l in lines], [(WARN, "Start at logon")])
        self.assertIn("isn't installed", lines[0]["text"])
        with Quiet():
            homenet.commands.cmd_install("Deck Lab test", 18642, no_start=True)
        lines = self.status()
        self.assertEqual([l["level"] for l in lines], [OK, OK])
        self.assertIn("doesn't start at logon", lines[0]["text"])
        self.assertIn("systemd restarts Deck Lab after a crash", lines[1]["text"])
        self.systemd.enabled.add("decklab-deck-lab-test.service")
        self.assertIn("starts Deck Lab with your systemd user session", self.status()[0]["text"])
        # Running, but not as the service (say, in a terminal).
        self.assertEqual(self.status(running=True)[1]["level"], WARN)
        failed = {"LoadState": "loaded", "ActiveState": "failed", "UnitFileState": "enabled", "ExecMainStatus": "1"}
        lines = self.status(systemd=failed)
        self.assertEqual(lines[1]["level"], PROBLEM)
        self.assertIn("journalctl --user -u decklab-deck-lab-test.service", lines[1]["fix"])
        self.assertEqual(self.status(systemd={})[0]["level"], WARN)          # systemctl couldn't say

    def test_status_command_off_windows(self):
        with Quiet():
            homenet.commands.cmd_install("Deck Lab", 18642, no_start=True)
        self.control.read_state.return_value = None
        self.patch("decklab.lib.homenet.gather.gather_facts", return_value={"errors": [], "error": "Windows only"})
        self.patch("decklab.lib.homenet.mdns.mdns_lookup",
                   return_value={"answered": True, "addresses": ["192.0.2.10"], "error": None})
        self.patch("decklab.lib.homenet.commands.pc_name", return_value="HomePC")
        self.patch("decklab.lib.homenet.commands.newest_code_mtime", return_value=None)
        self.probe.return_value = {"answered": False, "error": "nothing answered"}
        with Quiet() as q:
            homenet.commands.cmd_status("Deck Lab", 18642)
        text = " ".join(q.text.split())
        self.assertIn("OK Start at logon: The decklab.service service is installed", text)
        self.assertIn("OK Network: Not checked off Windows", text)
        self.assertNotIn("PowerShell", text)
        self.assertNotIn("Firewall", text)
        self.assertNotIn("Sleep", text)


@unittest.skipIf(WINDOWS, "the units name this Python and repo, which need POSIX paths")
class NightlyTimerTests(Guarded):

    def setUp(self):
        super().setUp()
        self.systemd = FakeSystemd()
        self.systemctl.side_effect = self.systemd
        self.patch("decklab.db.schedule.sys.platform", "linux")
        self.patch("decklab.db.schedule.psycopg_problem", return_value=None)
        self.folder = self.data / "systemd-user"
        self.said = []

    def test_install_writes_both_units_and_enables_the_timer(self):
        self.assertEqual(schedule.install(say=self.said.append), 0)
        units = systemd_units.nightly_units(sys.executable, str(config.REPO))
        for name, text in units.items():
            self.assertEqual((self.folder / name).read_text(encoding="utf-8"), text)
        self.assertEqual(self.systemd.calls, [("daemon-reload",), ("enable", "--now", systemd_units.TIMER)])
        self.assertIn("every day at 03:30", self.said[0])
        lines = schedule.status()
        self.assertEqual(lines[0], f"Nightly task: {systemd_units.TIMER} runs {sys.executable} -m decklab.db nightly")
        self.assertIn("daily at 03:30", lines[1])
        self.assertEqual(len(lines), 2, lines)

    def test_status_warns_about_a_disabled_timer_and_a_missing_python(self):
        self.assertEqual(schedule.install(say=self.said.append), 0)
        self.systemd.active.clear()
        lines = schedule.status_systemd(exists=lambda p: False)
        self.assertTrue(any("isn't enabled and active" in l for l in lines), lines)
        self.assertTrue(any("isn't there any more" in l for l in lines), lines)

    def test_remove(self):
        self.assertEqual(schedule.install(say=self.said.append), 0)
        self.assertEqual(schedule.remove(say=self.said.append), 0)
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertEqual(self.systemd.enabled | self.systemd.active, set())
        self.assertIn("isn't installed", schedule.status()[0])
        self.assertEqual(schedule.remove(say=self.said.append), 0)
        self.assertIn("nothing to remove", self.said[-1])

    def test_install_refuses_without_psycopg_or_systemd(self):
        with mock.patch.object(schedule, "psycopg_problem", return_value=r"Install them (.venv\Scripts\python)"):
            self.assertEqual(schedule.install(say=self.said.append), 1)
        self.assertIn(".venv/bin/python", self.said[-1])
        self.systemd.fail = "enable"
        self.assertEqual(schedule.install(say=self.said.append), 1)
        self.assertIn("systemd user session", self.said[-1])


if __name__ == "__main__":
    unittest.main()
