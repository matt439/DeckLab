"""Waking and staying awake on a Linux server PC, as fixtures on any OS: schedule wake-timer's
printed commands, schedule status's wake-timer warning, the nightly run's wait for the database,
and homenet status's Linux Sleep and Wake lines (lib/homenet/linux_power.py). No real systemctl,
systemd-inhibit, ethtool, database or /sys is touched: every reader is a fake."""
import io
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from decklab.db import __main__ as cli, conn as db, nightly, schedule, systemd_units
from decklab.lib.homenet import linux_power as lp
from decklab.lib.homenet.common import OK, WARN


class WakeTimerCommandTests(unittest.TestCase):

    def setUp(self):
        for target, name in ((subprocess, "run"), (subprocess, "Popen"), (schedule, "_homenet")):
            patcher = mock.patch.object(target, name, side_effect=AssertionError("must not call " + name))
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_prints_the_units_as_sudo_commands_without_installing(self):
        code, out, err = self.run_cli(["schedule", "wake-timer"])
        self.assertEqual((code, err), (0, ""))
        for command in systemd_units.wake_install_commands():
            self.assertIn(command + "\n", out)
        self.assertIn("at 03:29", out)
        self.assertIn("sudo systemctl disable --now decklab-wake.timer", out)

    def test_at_moves_the_wake_and_bad_values_print_nothing(self):
        code, out, _ = self.run_cli(["schedule", "wake-timer", "--at", "00:00"])
        self.assertEqual(code, 0)
        self.assertIn("OnCalendar=*-*-* 23:59:00\n", out)
        code, out, err = self.run_cli(["schedule", "wake-timer", "--at", "25:00"])
        self.assertEqual((code, out), (1, ""))
        self.assertIn("--at", err)

    def test_preview_only_options_are_refused(self):
        for option, value in (("--unit", "timer"), ("--python", "/usr/bin/python3"), ("--workdir", "/srv")):
            with self.subTest(option=option):
                code, out, err = self.run_cli(["schedule", "wake-timer", option, value])
                self.assertEqual((code, out), (1, ""))
                self.assertIn("only for schedule preview-systemd", err)


class WakeTimerStatusTests(unittest.TestCase):

    def test_lines(self):
        missing = schedule.wake_timer_lines({"LoadState": "not-found", "ActiveState": "inactive"})
        self.assertIn("WARNING", missing[0])
        self.assertIn("schedule wake-timer", missing[0])
        inactive = schedule.wake_timer_lines({"LoadState": "loaded", "ActiveState": "inactive"})
        self.assertIn("sudo systemctl enable --now decklab-wake.timer", inactive[0])
        self.assertNotIn("WARNING", schedule.wake_timer_lines({"LoadState": "loaded", "ActiveState": "active"})[0])
        self.assertIn("can't say", schedule.wake_timer_lines(None)[0])

    def test_system_unit_state_asks_the_system_manager(self):
        calls = []

        def run(args, timeout=None):
            calls.append(args)
            return 0, "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n", ""
        with mock.patch.object(schedule._systemd(), "_run", run):
            self.assertEqual(schedule.system_unit_state("decklab-wake.timer")["ActiveState"], "active")
        self.assertEqual(calls[0][:3], ["systemctl", "show", "decklab-wake.timer"])
        self.assertNotIn("--user", calls[0])
        with mock.patch.object(schedule._systemd(), "_run", lambda args, timeout=None: (1, "", "no bus")):
            self.assertIsNone(schedule.system_unit_state("decklab-wake.timer"))

    def test_status_passes_wake_to_the_systemd_status(self):
        with mock.patch.object(schedule._systemd(), "supported", return_value=True), \
                mock.patch.object(schedule, "wake_wanted", return_value=True), \
                mock.patch.object(schedule, "status_systemd", return_value=["x"]) as status:
            self.assertEqual(schedule.status(), ["x"])
        status.assert_called_once_with(wake=True)


class DatabaseWaitTests(unittest.TestCase):

    def setUp(self):
        self.now, self.slept, self.said = [0.0], [], []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now[0] += seconds

    def wait(self, connect, limit=30, every=10):
        return nightly.wait_for_database(limit, every, connect=connect, sleep=self.sleep,
                                         clock=lambda: self.now[0], log=self.said.append)

    def test_waits_until_it_answers(self):
        tries = []
        connection = mock.Mock()

        def connect():
            tries.append(1)
            if len(tries) < 3:
                raise db.DbUnavailable("can't reach PostgreSQL at localhost:5432: connection refused")
            return connection
        self.assertTrue(self.wait(connect))
        self.assertEqual(self.slept, [10, 10])
        connection.close.assert_called_once_with()
        self.assertIn("waiting up to 30 seconds", self.said[0])
        self.assertIn("answered after 20 seconds", self.said[-1])

    def test_gives_up_after_the_limit(self):
        def connect():
            raise db.DbUnavailable("can't reach PostgreSQL")
        self.assertFalse(self.wait(connect))
        self.assertLessEqual(sum(self.slept), 30)
        self.assertIn("running the steps anyway", self.said[-1])

    def test_answering_at_once_logs_nothing(self):
        self.assertTrue(self.wait(lambda: mock.Mock()))
        self.assertEqual((self.slept, self.said), ([], []))

    def test_psycopg_missing_isnt_waited_for(self):
        with mock.patch.object(db, "_psycopg", side_effect=db.DbUnavailable("psycopg isn't installed")), \
                mock.patch.object(db, "connect", side_effect=AssertionError("must not connect")):
            self.assertFalse(nightly.wait_for_database(sleep=self.sleep, log=self.said.append))
        self.assertEqual(self.slept, [])

    def test_run_waits_only_on_linux(self):
        for platform, waits in (("linux", 1), ("win32", 0)):
            with self.subTest(platform=platform), mock.patch.object(nightly.sys, "platform", platform), \
                    mock.patch.object(nightly, "wait_for_database") as wait, \
                    mock.patch.object(nightly, "_run", return_value=0), \
                    mock.patch("decklab.lib.keepawake.platform_power", lambda: mock.Mock(kind="none")):
                self.assertEqual(nightly.run(), 0)
                self.assertEqual(wait.call_count, waits)


# ------------------------------------------------------------------ homenet status on Linux

ROUTE = ("Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
         "wlan0\t00000000\t0102A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0\n"
         "eno1\t00000000\t0102A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
         "eno1\t0002A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0\n")
ETHTOOL_ROOT = "Settings for eno1:\n\tSupports Wake-on: pumbg\n\tWake-on: g\n\tLink detected: yes\n"
ETHTOOL_USER = "Settings for eno1:\n\tLink detected: yes\n"


class FakeHost:
    """Files, folders, programs and commands for gather()."""

    def __init__(self, files=None, programs=("systemctl", "systemd-inhibit", "ethtool"), runs=None):
        self.files = {"/sys/power/state": "freeze mem disk\n", "/sys/power/mem_sleep": "s2idle [deep]\n",
                      "/proc/net/route": ROUTE, "/sys/class/net/eno1/device/power/wakeup": "enabled\n",
                      **(files or {})}
        self.programs = set(programs)
        self.runs = {"is-enabled": (0, "static\n", ""), "show": (0, "LoadState=loaded\nActiveState=active\n", ""),
                     "inhibit": (0, "", ""), "ethtool": (0, ETHTOOL_ROOT, ""), **(runs or {})}
        self.calls = []

    def read(self, path):
        return self.files.get(path)

    def listdir(self, folder):
        prefix = folder + "/"
        return sorted({p[len(prefix):] for p in self.files if p.startswith(prefix) and "/" not in p[len(prefix):]})

    def exists(self, path):
        return path in self.files

    def which(self, name):
        return f"/usr/bin/{name}" if name in self.programs else None

    def run(self, args, timeout=None):
        self.calls.append(args)
        if args[0] == "systemctl":
            return self.runs[args[1]]
        if args[0].endswith("systemd-inhibit"):
            return self.runs["inhibit"]
        if args[0].endswith("ethtool"):
            return self.runs["ethtool"]
        raise AssertionError(args)

    def gather(self, wake=None, probe=None):
        return lp.gather(wake, read=self.read, listdir=self.listdir, exists=self.exists, which=self.which,
                         run=self.run, probe=probe, user="player")


WAKE = {"idle_minutes": 20, "gate": None}


def levels(lines):
    return [(x["area"], x["level"]) for x in lines]


class ParsingTests(unittest.TestCase):

    def test_logind(self):
        texts = ["[Login]\n#IdleAction=suspend\nIdleAction=ignore\n[Other]\nIdleAction=suspend\n",
                 "; a drop-in\n[Login]\nIdleAction = suspend\nIdleActionSec=10min\n"]
        self.assertEqual(lp.parse_logind(texts), {"IdleAction": "suspend", "IdleActionSec": "10min"})
        self.assertEqual(lp.parse_logind([]), {})

    def test_logind_files_in_order(self):
        host = FakeHost({"/etc/systemd/logind.conf": "[Login]\nIdleAction=suspend\n",
                         "/usr/lib/systemd/logind.conf": "[Login]\nIdleAction=lock\n",
                         "/usr/lib/systemd/logind.conf.d/10-x.conf": "[Login]\nIdleActionSec=5min\n",
                         "/etc/systemd/logind.conf.d/10-x.conf": "[Login]\nIdleActionSec=15min\n",
                         "/run/systemd/logind.conf.d/20-y.conf": "[Login]\nIdleAction=ignore\n",
                         "/etc/systemd/logind.conf.d/notes.txt": "[Login]\nIdleAction=poweroff\n"})
        found = lp.logind_settings(host.read, host.listdir)
        self.assertEqual((found["IdleAction"], found["IdleActionSec"]), ("ignore", "15min"))
        self.assertEqual(found["files"], ["/etc/systemd/logind.conf", "/etc/systemd/logind.conf.d/10-x.conf",
                                          "/run/systemd/logind.conf.d/20-y.conf"])
        self.assertEqual(lp.logind_settings(lambda p: None, lambda f: []),
                         {"IdleAction": "ignore", "IdleActionSec": "30min", "files": []})

    def test_mem_sleep_route_and_ethtool(self):
        self.assertEqual(lp.selected_mem_sleep("s2idle [deep]\n"), ("deep", ["s2idle", "deep"]))
        self.assertEqual(lp.selected_mem_sleep("[s2idle]"), ("s2idle", ["s2idle"]))
        self.assertEqual(lp.selected_mem_sleep(None), (None, []))
        self.assertEqual(lp.default_route_interface(ROUTE), "eno1")
        self.assertIsNone(lp.default_route_interface(ROUTE.splitlines()[0]))
        self.assertIsNone(lp.default_route_interface(None))
        self.assertEqual(lp.parse_ethtool(ETHTOOL_ROOT), {"supports": "pumbg", "wake_on": "g", "error": None})
        denied = lp.parse_ethtool(ETHTOOL_USER, "netlink error: Operation not permitted\n"
                                  "Cannot get wake-on-lan settings: Operation not permitted\n")
        self.assertIsNone(denied["wake_on"])
        self.assertIn("Operation not permitted", denied["error"])
        self.assertIn("needs root", lp.parse_ethtool(ETHTOOL_USER)["error"])


class GatherTests(unittest.TestCase):

    def test_without_wake_reads_only_the_sleep_facts(self):
        host = FakeHost()
        facts = host.gather()
        self.assertEqual(facts["suspend_target"], "static")
        self.assertNotIn("interface", facts)
        self.assertEqual([c[:2] for c in host.calls], [["systemctl", "is-enabled"]])

    def test_with_wake_and_a_gate(self):
        host = FakeHost()
        probed = []
        facts = host.gather({"idle_minutes": 20, "gate": "http://192.0.2.5:8650"},
                            probe=lambda gate: probed.append(gate) or {"answered": True, "awake": True})
        self.assertEqual(probed, ["http://192.0.2.5:8650"])
        self.assertEqual((facts["interface"], facts["wireless"], facts["nic_wakeup"]), ("eno1", False, "enabled"))
        self.assertEqual(facts["ethtool"]["wake_on"], "g")
        self.assertEqual(facts["inhibit"], {"ok": True, "error": None})
        self.assertEqual(facts["wake_timer"]["LoadState"], "loaded")
        trial = next(c for c in host.calls if c[0].endswith("systemd-inhibit"))
        self.assertEqual((trial[1], trial[-2], trial[-1]), ("--what=sleep:idle", "--mode=block", "true"))

    def test_missing_tools_and_files(self):
        host = FakeHost(files={"/proc/net/route": None}, programs=())
        host.files = {}
        facts = host.gather(WAKE)
        self.assertEqual(host.calls, [])
        self.assertIsNone(facts["interface"])
        self.assertIsNone(facts["inhibit_tool"])
        self.assertNotIn("wake_timer", facts)


class JudgingTests(unittest.TestCase):

    def lines(self, host, wake=WAKE, gate=None):
        settings = {"wake": {"gate": gate}} if wake else {}
        return lp.status_lines(settings, facts=host.gather(wake and {"idle_minutes": 20, "gate": gate},
                                                           probe=lambda g: {"answered": False, "error": "timed out"}))

    def test_all_good_with_wake(self):
        host = FakeHost({"/etc/systemd/logind.conf.d/decklab.conf": "[Login]\nIdleAction=suspend\nIdleActionSec=10min\n"})
        lines = self.lines(host)
        self.assertEqual(levels(lines), [("Sleep", OK), ("Sleep", OK), ("Wake", OK), ("Wake", OK), ("Wake", OK)])
        self.assertIn("suspends after 10min idle", lines[0]["text"])

    def test_wake_without_an_idle_suspend(self):
        lines = self.lines(FakeHost())
        self.assertEqual(lines[0]["level"], WARN)
        self.assertIn("nothing here suspends", lines[0]["text"])
        self.assertIn("IdleAction=suspend", lines[0]["fix"])

    def test_masked_suspend_with_wake(self):
        host = FakeHost({"/etc/systemd/logind.conf": "[Login]\nIdleAction=suspend\n"},
                        runs={"is-enabled": (1, "masked\n", "")})
        self.assertIn("masked", self.lines(host)[0]["text"])

    def test_without_wake(self):
        quiet = self.lines(FakeHost(), wake=None)
        self.assertEqual(levels(quiet), [("Sleep", OK)])
        host = FakeHost({"/etc/systemd/logind.conf": "[Login]\nIdleAction=suspend\n"})
        lines = self.lines(host, wake=None)
        self.assertEqual(levels(lines), [("Sleep", WARN)])
        self.assertIn("/etc/systemd/logind.conf", lines[0]["fix"])

    def test_inhibit_refused_or_missing(self):
        host = FakeHost(runs={"inhibit": (1, "", "Failed to inhibit: Access denied\n")})
        refused = self.lines(host)[1]
        self.assertEqual(refused["level"], WARN)
        self.assertIn("Access denied", refused["text"])
        self.assertIn('s.user == "player"', refused["fix"])
        missing = self.lines(FakeHost(programs=("systemctl", "ethtool")))[1]
        self.assertIn("systemd-inhibit isn't installed", missing["text"])

    def test_s2idle_and_no_suspend_to_ram(self):
        wake = [x for x in self.lines(FakeHost({"/sys/power/mem_sleep": "[s2idle] deep\n"})) if x["area"] == "Wake"]
        self.assertEqual(wake[0]["level"], WARN)
        self.assertIn("mem_sleep_default=deep", wake[0]["fix"])
        only = [x for x in self.lines(FakeHost({"/sys/power/mem_sleep": "[s2idle]\n"})) if x["area"] == "Wake"]
        self.assertIn("no deep (S3)", only[0]["fix"])
        none = [x for x in self.lines(FakeHost({"/sys/power/state": "freeze\n"})) if x["area"] == "Wake"]
        self.assertIn("no suspend to RAM", none[0]["text"])

    def test_adapter_lines(self):
        def adapter(**options):
            return [x for x in self.lines(FakeHost(**options)) if x["area"] == "Wake"][1]
        self.assertIn("isn't set to wake", adapter(runs={"ethtool": (0, "\tSupports Wake-on: pumbg\n\tWake-on: d\n", "")})["text"])
        self.assertIn("802-3-ethernet.wake-on-lan magic",
                      adapter(runs={"ethtool": (0, "\tSupports Wake-on: pumbg\n\tWake-on: d\n", "")})["fix"])
        self.assertIn("can't wake", adapter(runs={"ethtool": (0, "\tSupports Wake-on: d\n\tWake-on: d\n", "")})["text"])
        denied = adapter(runs={"ethtool": (75, ETHTOOL_USER, "Cannot get wake-on-lan settings: Operation not permitted")})
        self.assertEqual(denied["level"], OK)       # power/wakeup is enabled
        self.assertIn("Operation not permitted", denied["text"])
        off = adapter(files={"/sys/class/net/eno1/device/power/wakeup": "disabled\n"}, programs=("systemctl",))
        self.assertEqual(off["level"], WARN)
        self.assertIn("disabled", off["text"])
        wifi = adapter(files={"/sys/class/net/eno1/wireless": ""})
        self.assertIn("Wi-Fi", wifi["text"])
        no_route = adapter(files={"/proc/net/route": ROUTE.splitlines()[0]})
        self.assertIn("no default route", no_route["text"])

    def test_wake_timer_and_gate_lines(self):
        def wake(gate=None, **options):
            return [x for x in self.lines(FakeHost(**options), gate=gate) if x["area"] == "Wake"]
        missing = wake(runs={"show": (0, "LoadState=not-found\nActiveState=inactive\n", "")})[2]
        self.assertEqual(missing["level"], WARN)
        self.assertIn("schedule wake-timer", missing["fix"])
        self.assertIn("enable --now", wake(runs={"show": (0, "LoadState=loaded\nActiveState=inactive\n", "")})[2]["fix"])
        self.assertIn("Couldn't ask", wake(runs={"show": (1, "", "Failed to connect to bus")})[2]["text"])
        gate = wake(gate="http://192.0.2.5:8650")[3]
        self.assertEqual(gate["level"], WARN)
        self.assertIn("doesn't answer (timed out)", gate["text"])


if __name__ == "__main__":
    unittest.main()
