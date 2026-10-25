"""Tests for restarting Deck Lab after a crash (E11-S26): the watchdog task's
XML (task.py), its choice (watchdog.decide), the ensure command and its
record and log, what install, remove, stop, start and restart do about the
watchdog and the stop marker (commands.py), and status's "Restart after a
crash" lines (watchdog.check_watchdog). The stop marker itself is tested in
test_control.py, and the server's side of it in test_server_lifecycle.py.

Nothing here registers or deletes a real scheduled task, reads or writes the
real stop marker, record or logs, or starts a server: schtasks, control,
the server's answer and _start_task are replaced (homenet_support.Guarded),
and the record and the log go to the test's own folder.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from decklab.lib import config, homenet
from decklab.lib.homenet import OK, PROBLEM, WARN
from decklab.tests.homenet_support import (
    LOGON, PYTHON, PYTHONW, REAL_FACTS_NOON, SCRIPT, WINDOWS, Guarded, Quiet, levels, running_state,
    task_definition, texts,
)

TASK = "Deck Lab test"
WATCH = "Deck Lab test watchdog"
PORT = 18642
REPO = str(config.REPO)
DOWN = {"answered": False, "listening": False, "error": homenet.NOT_LISTENING}
UP = {"answered": True, "deck_lab": True, "cards_ready": True}


def ago(**kw):
    return (datetime.now().astimezone() - timedelta(**kw)).isoformat(timespec="seconds")


def server_task(**kw):
    """The server task as install --at-logon --port 18642 leaves it (parse_task_xml's dict)."""
    kw.setdefault("arguments", homenet.server_arguments(SCRIPT, port=PORT))
    return task_definition(**kw)


def watchdog_task(**kw):
    task = homenet.parse_task_xml(homenet.watchdog_xml(PYTHONW, homenet.watchdog_arguments(TASK), REPO,
                                                       "HOMEPC\\player", WATCH))
    task.update(kw)
    return task


# ------------------------------------------------------------ the task

class WatchdogXmlTests(unittest.TestCase):
    def build(self, **kw):
        args = dict(command=PYTHONW, arguments=homenet.watchdog_arguments(), workdir=REPO, user="HOMEPC\\player",
                    start=datetime(2026, 10, 20, 9, 41, 7))
        args.update(kw)
        return homenet.watchdog_xml(**args)

    def test_round_trip(self):
        task = homenet.parse_task_xml(self.build())
        self.assertEqual(task["command"], PYTHONW)
        self.assertEqual(homenet.split_args(task["arguments"]),
                         ["-m", "decklab.lib.homenet", "ensure", "--task", "Deck Lab"])
        self.assertEqual(task["workdir"], REPO)
        self.assertEqual(task["repeats"], ["PT5M"])
        self.assertEqual(task["time_limit"], "PT2M")
        self.assertEqual(task["priority"], 7)
        self.assertEqual(task["multiple"], "IgnoreNew")
        self.assertEqual(task["logon_type"], "InteractiveToken")
        self.assertEqual(task["run_level"], "LeastPrivilege")
        self.assertEqual(task["logon_users"], [])
        self.assertTrue(task["enabled"])

    def test_start_boundary_is_local_and_rounded_up(self):
        text = self.build()
        self.assertIn("<StartBoundary>2026-10-20T09:42:00</StartBoundary>", text)    # no zone: local time
        self.assertIn("<StartBoundary>2026-10-20T09:41:00</StartBoundary>",
                      self.build(start=datetime(2026, 10, 20, 9, 41)))
        self.assertIn("<StopAtDurationEnd>false</StopAtDurationEnd>", text)
        self.assertNotIn("<Duration>", text)                   # repeats forever
        self.assertIn("<StartWhenAvailable>false<", text)       # missed runs (asleep, off) are skipped
        self.assertIn("<URI>\\Deck Lab watchdog</URI>", text)
        self.assertIn("install --at-logon", text)

    def test_values_are_escaped(self):
        odd = r"C:\Odd & <Folder>\it's"
        task = homenet.parse_task_xml(self.build(command=odd + r"\pythonw.exe", workdir=odd, user="D&M\\o'<b>",
                                                 arguments=homenet.watchdog_arguments('Odd "name" & <x>'),
                                                 name='Odd "name" & <x> watchdog'))
        self.assertEqual(task["command"], odd + r"\pythonw.exe")
        self.assertEqual(task["workdir"], odd)
        self.assertEqual(homenet.split_args(task["arguments"])[-1], 'Odd "name" & <x>')

    def test_a_disabled_time_trigger_isnt_counted(self):
        text = self.build().replace("<StartBoundary>2026-10-20T09:42:00</StartBoundary>\n      <Enabled>true",
                                    "<StartBoundary>2026-10-20T09:42:00</StartBoundary>\n      <Enabled>false")
        self.assertEqual(homenet.parse_task_xml(text)["repeats"], [])

    def test_the_names(self):
        self.assertEqual(homenet.watchdog_name(), "Deck Lab watchdog")
        self.assertEqual(homenet.watchdog_name(TASK), WATCH)
        task = server_task(arguments=homenet.server_arguments(SCRIPT, port=1, host="127.0.0.1"))
        self.assertEqual((homenet.task_port(task), homenet.task_host(task)), (1, "127.0.0.1"))
        self.assertEqual((homenet.task_port(task_definition()), homenet.task_host(task_definition())), (None, None))


# ------------------------------------------------------------ the choice

class DecideTests(unittest.TestCase):
    NOW = datetime(2026, 10, 20, 12, 0).timestamp()

    def decide(self, stopped=None, answer=DOWN, state=None, problem=None, record=None, since=None):
        return homenet.decide(stopped, answer, state, problem, record or {}, self.NOW, since)

    def test_down_starts_it(self):
        self.assertEqual(self.decide(), ("start", "down"))
        self.assertEqual(self.decide(answer={"answered": False, "listening": None}), ("start", "down"))

    def test_each_reason_to_leave_it(self):
        listening = {"answered": False, "listening": True, "error": "no answer"}
        cases = [(dict(problem="no-task"), "no-task"), (dict(problem="manual-starts"), "manual-starts"),
                 (dict(stopped={"by": "homenet stop"}), "stopped-on-purpose"),
                 (dict(answer=UP, state=running_state(
                     port=PORT, started=datetime(2026, 10, 20, 11, 59).astimezone().isoformat())), "running"),
                 (dict(answer={"answered": True, "deck_lab": False}), "another-program"),
                 (dict(answer=listening), "not-answering"),
                 (dict(state=running_state(port=PORT)), "starting"),
                 (dict(record={"gave_up_at": "2026-10-20T11:00:00+10:00"}), "gave-up")]
        for kwargs, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(self.decide(**kwargs), ("leave", reason))

    def test_the_order(self):
        self.assertEqual(self.decide(problem="task-broken", stopped={"by": "x"}), ("leave", "task-broken"))
        self.assertEqual(self.decide(stopped={"by": "x"}, answer=UP), ("leave", "stopped-on-purpose"))
        self.assertEqual(self.decide(stopped={"by": "unreadable"}), ("leave", "stopped-on-purpose"))
        gave_up = {"gave_up_at": "2026-10-20T11:00:00+10:00", "failures": 3}
        self.assertEqual(self.decide(record=gave_up), ("leave", "gave-up"))
        # A server that answers (started by hand, say) beats having given up, and once it has
        # stayed up its restarts stop counting.
        old = running_state(port=PORT, started=datetime(2026, 10, 20, 11, 40).astimezone().isoformat())
        self.assertEqual(self.decide(answer=UP, state=old, record=gave_up), ("reset", "running"))

    def test_a_logon_or_a_start_moments_ago_is_starting(self):
        # Review finding: a check that landed in the logon trigger's delay, or in a start's
        # first seconds, started the task early and logged a crash that didn't happen.
        grace = homenet.WATCHDOG_GRACE
        self.assertGreaterEqual(grace, 30 + homenet.START_WAIT)        # TASK_DELAY, then START_WAIT
        self.assertEqual(self.decide(since=self.NOW - 10), ("leave", "just-started"))
        self.assertEqual(self.decide(since=self.NOW - grace + 1), ("leave", "just-started"))
        self.assertEqual(self.decide(since=self.NOW - grace), ("start", "down"))
        # Only for "down": what else it finds still comes first.
        self.assertEqual(self.decide(since=self.NOW - 10, stopped={"by": "x"}), ("leave", "stopped-on-purpose"))
        self.assertEqual(self.decide(since=self.NOW - 10, answer=UP), ("leave", "running"))

    def test_a_restarts_marker_doesnt_keep_it_off(self):
        # Review finding: a restart whose stop timed out left "homenet stop", so a server
        # that stopped later stayed off though a restart was asked for.
        restart = {"by": "homenet restart", "restart": True}
        self.assertEqual(self.decide(stopped=restart), ("start", "down"))
        self.assertEqual(self.decide(stopped=restart, answer=UP), ("leave", "running"))

    def test_gives_up_after_three_restarts_in_a_row(self):
        self.assertEqual(self.decide(record={"failures": 2}), ("start", "down"))
        self.assertEqual(self.decide(record={"failures": homenet.WATCHDOG_GIVE_UP}), ("give-up", "gave-up"))

    def test_stable_needs_ten_minutes(self):
        fresh = running_state(port=PORT, started=datetime(2026, 10, 20, 11, 55).astimezone().isoformat())
        self.assertEqual(self.decide(answer=UP, state=fresh), ("leave", "running"))
        # No state (a server from before Milestone 6): the watchdog's own last restart counts.
        restarted = {"restarts": [{"at": datetime(2026, 10, 20, 11, 30).astimezone().isoformat()}]}
        self.assertEqual(self.decide(answer=UP, record=restarted), ("reset", "running"))
        self.assertEqual(self.decide(answer=UP), ("leave", "running"))


# ------------------------------------------------------------ ensure

class FakeTasks:
    """schtasks with the tasks registered by name (their XML)."""

    def __init__(self, test):
        self.test, self.tasks, self.calls, self.on_run = test, {}, [], None

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        name = args[2] if len(args) > 2 else None
        if args[0] == "/Query":
            return (0, self.tasks[name], "") if name in self.tasks else (1, "", "ERROR: not found")
        if args[0] == "/Create":
            self.tasks[name] = Path(args[args.index("/XML") + 1]).read_bytes().decode("utf-16")
        elif args[0] == "/Delete":
            self.tasks.pop(name, None)
        elif args[0] == "/Run" and self.on_run:
            self.on_run()
        return 0, "SUCCESS", ""

    def register(self, name=TASK, arguments=None, at_logon=True):
        self.tasks[name] = homenet.task_xml(PYTHONW, arguments or homenet.server_arguments(SCRIPT, port=PORT),
                                            REPO, "HOMEPC\\player", name, at_logon=at_logon)

    def commands(self):
        return [(c[0], c[2] if len(c) > 2 else None) for c in self.calls]


class EnsureTests(Guarded):
    def setUp(self):
        super().setUp()
        self.tasks = FakeTasks(self)
        self.schtasks.side_effect = self.tasks
        self.tasks.register()
        self.patch("decklab.lib.homenet.commands.file_exists", return_value=True)
        self.answer = self.patch("decklab.lib.homenet.commands.probe", return_value=DOWN)
        self.start = self.patch("decklab.lib.homenet.commands._start_task", return_value=0)

    def ensure(self, times=1, **kw):
        with mock.patch.object(sys, "platform", "win32"), Quiet() as q:
            for _ in range(times):
                self.assertEqual(homenet.cmd_ensure(TASK, **kw), 0, q.text)
        return q.text

    def record(self, port=PORT):
        return homenet.watchdog.load_record(port)

    def log(self):
        path = homenet.watchdog.watchdog_log()
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_down_and_not_stopped_on_purpose_starts_it_once(self):
        self.ensure()
        self.start.assert_called_once_with(TASK, PORT, mock.ANY)
        self.assertEqual(self.start.call_args[0][2]["command"], PYTHONW)
        record = self.record()
        self.assertEqual((record["failures"], record["reason"], record["logon"]), (1, "running", LOGON))
        self.assertEqual([r["answered"] for r in record["restarts"]], [True])
        log = self.log()
        self.assertEqual(log.count("wasn't stopped on purpose: starting it through the \"Deck Lab test\" task "
                                   "(restart 1 of 3"), 1, log)
        self.assertEqual(log.count("It answers again."), 1)
        self.assertEqual(self.log().count("\n"), 2)             # and nothing else
        self.assertEqual(homenet.watchdog.watchdog_log().parent, self.data / "logs")

    def test_stopped_on_purpose_stays_off(self):
        self.control.mark_stopped(PORT, "homenet stop")
        self.ensure(times=3)
        self.start.assert_not_called()
        self.answer.assert_not_called()
        self.assertNotIn("/Run", [c[0] for c in self.tasks.calls])
        self.assertEqual(self.log().count("was stopped on purpose at 2026-10-20 18:02 (homenet stop): leaving it "
                                          "off until"), 1, self.log())

    def test_an_unreadable_marker_counts_as_stopped(self):
        self.control.markers[PORT] = {"by": "unreadable"}
        self.ensure()
        self.start.assert_not_called()
        self.assertIn("stopped-18642.json can't be read, so it counts as stopped on purpose", self.log())

    def test_running_is_left_alone(self):
        self.answer.return_value = UP
        self.control.read_state.return_value = running_state(port=PORT, started=ago(minutes=1))
        self.ensure(times=2)
        self.start.assert_not_called()
        self.assertEqual(self.log().count("Deck Lab is running on port 18642."), 1)

    def test_another_program_is_logged_once(self):
        self.answer.return_value = {"answered": True, "deck_lab": False}
        self.ensure(times=2)
        self.start.assert_not_called()
        self.assertEqual(self.log().count("Another program answers on port 18642"), 1)

    def test_a_stuck_server_isnt_killed_or_doubled(self):
        self.answer.return_value = {"answered": False, "listening": True, "error": "no answer"}
        self.ensure()
        self.control.read_state.return_value = running_state(port=PORT)
        self.answer.return_value = DOWN
        self.ensure()
        self.start.assert_not_called()
        self.control.request_stop.assert_not_called()
        self.assertIn("doesn't answer (a stuck Deck Lab server?)", self.log())
        self.assertIn("A Deck Lab server is recorded (process 4242)", self.log())

    def test_gives_up_after_three_starts_that_dont_answer(self):
        self.start.return_value = 1
        self.ensure(times=5)
        self.assertEqual(self.start.call_count, homenet.WATCHDOG_GIVE_UP)
        record = self.record()
        self.assertTrue(record["gave_up_at"])
        self.assertEqual([r["answered"] for r in record["restarts"]], [False] * 3)
        self.assertEqual(self.log().count("It didn't answer."), 3)
        self.assertEqual(self.log().count("didn't stay up after 3 restarts in a row"), 1)
        # A start that was asked for begins again, once it has had time to answer.
        homenet.watchdog.reset(PORT)
        self.assertEqual((self.record()["failures"], self.record()["gave_up_at"]), (0, None))
        self.ensure()
        self.assertEqual(self.start.call_count, 3)
        self.assertIn("giving it 120 seconds to answer on port 18642", self.log())
        record = self.record()
        record["asked_at"] = ago(minutes=3)
        homenet.watchdog.save_record(record, PORT)
        self.ensure()
        self.assertEqual(self.start.call_count, 4)

    def test_a_check_moments_after_logon_or_a_start_leaves_it(self):
        # Review finding: at logon (the trigger waits 30 seconds) or during homenet start, the
        # check ran the task early and recorded a restart that status showed for 24 hours.
        self.control.logon_time.return_value = ago(seconds=20)
        self.ensure(times=2)
        self.start.assert_not_called()
        self.assertEqual(self.record()["restarts"], [])
        self.assertEqual(self.log().count("was started moments ago"), 1)
        self.control.logon_time.return_value = ago(hours=2)       # a new logon: the record starts again
        homenet.watchdog.reset(PORT)                                # homenet start, a moment ago
        self.ensure()
        self.start.assert_not_called()
        self.control.logon_time.return_value = None                 # unknown: only the start counts
        self.ensure()
        self.start.assert_not_called()

    def test_a_restart_whose_stop_timed_out_starts_once_its_down(self):
        self.control.mark_stopped(PORT, "homenet restart", restart=True)
        self.answer.return_value = UP
        self.control.read_state.return_value = running_state(port=PORT, started=ago(hours=1))
        self.ensure()
        self.start.assert_not_called()                              # the old server is still stopping
        self.answer.return_value = DOWN
        self.control.read_state.return_value = None
        self.ensure()
        self.start.assert_called_once()

    def test_staying_up_stops_the_restarts_counting(self):
        self.start.return_value = 1
        self.ensure(times=2)
        self.assertEqual(self.record()["failures"], 2)
        self.answer.return_value = UP
        self.control.read_state.return_value = running_state(port=PORT, started=ago(minutes=5))
        self.ensure()
        self.assertEqual(self.record()["failures"], 2)          # not yet: up for 5 minutes only
        self.control.read_state.return_value = running_state(port=PORT, started=ago(minutes=11))
        self.ensure()
        self.assertEqual(self.record()["failures"], 0)

    def test_a_new_logon_starts_the_record_again(self):
        homenet.watchdog.save_record({"version": 1, "port": PORT, "logon": "2026-10-17T07:00:00+00:00",
                                      "failures": 3, "gave_up_at": "2026-10-17T09:00:00+10:00", "restarts": []},
                                     PORT)
        self.ensure()
        self.start.assert_called_once()
        self.assertEqual((self.record()["failures"], self.record()["gave_up_at"]), (1, None))

    def test_the_port_and_host_come_from_the_task(self):
        self.tasks.register(arguments=homenet.server_arguments(SCRIPT, port=18650, host="127.0.0.5"))
        self.ensure()
        self.answer.assert_called_once_with(18650, "127.0.0.5")
        self.start.assert_called_once_with(TASK, 18650, mock.ANY)
        self.assertTrue(homenet.watchdog.record_path(18650).exists())
        self.assertEqual(homenet.watchdog.record_path(18650).parent, self.data)
        # Without --port: config.json's port.
        self.tasks.register(arguments=homenet.server_arguments(SCRIPT))
        with mock.patch("decklab.lib.config.load", return_value={"port": 18651}):
            self.ensure()
        self.assertEqual(self.answer.call_args[0], (18651, "127.0.0.1"))

    def test_a_config_that_cant_be_read_is_logged_once(self):
        self.tasks.register(arguments=homenet.server_arguments(SCRIPT))
        with mock.patch("decklab.lib.config.load", side_effect=ValueError("Expecting ','")):
            self.ensure(times=2)
        self.start.assert_not_called()
        self.assertEqual(self.log().count("config.json can't be read (ValueError: Expecting ',')"), 1)

    def test_no_task_or_manual_starts(self):
        self.tasks.tasks.clear()
        self.ensure()
        self.assertIn('The "Deck Lab test" task isn\'t registered', self.log())
        self.tasks.register(at_logon=False)
        self.ensure()
        self.assertIn("starts are manual: leaving it off", self.log())
        self.start.assert_not_called()
        self.answer.assert_not_called()
        self.assertNotIn("/Run", [c[0] for c in self.tasks.calls])

    def test_without_a_console_everything_goes_to_its_log(self):
        def start(*args):
            homenet.say("Deck Lab is running.")                 # what _start_task says
            return 0
        self.start.side_effect = start
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(sys, "stdout", None), \
                mock.patch.object(sys, "stderr", None):
            self.assertEqual(homenet.cmd_ensure(TASK), 0)
            self.assertIsNone(sys.stdout)                       # given back
        log = self.log()
        self.assertIn("starting it through", log)
        self.assertIn("\nDeck Lab is running.\n", log)

    def test_a_failed_check_is_logged_and_exits_1(self):
        self.start.side_effect = RuntimeError("broken")
        with mock.patch.object(sys, "platform", "win32"), Quiet():
            self.assertEqual(homenet.cmd_ensure(TASK), 1)
        self.assertIn("The watchdog's check failed:", self.log())
        self.assertIn("RuntimeError: broken", self.log())

    def test_off_windows_it_does_nothing(self):
        with mock.patch.object(sys, "platform", "linux"), Quiet() as q:
            self.assertEqual(homenet.cmd_ensure(TASK), 0)
        self.assertIn("only works on Windows", q.text)
        self.assertEqual(self.tasks.calls, [])

    def test_main_runs_it_even_with_a_broken_config(self):
        self.tasks.tasks.clear()
        with mock.patch("decklab.lib.config.load", side_effect=ValueError("broken")), \
                mock.patch.object(sys, "platform", "win32"), Quiet():
            self.assertEqual(homenet.main(["ensure", "--task", TASK, "--port", str(PORT)]), 0)
        self.assertIn("isn't registered", self.log())


# ------------------------------------------------------------ the commands

@unittest.skipUnless(WINDOWS, "the commands use Task Scheduler")
class WatchdogCommandTests(Guarded):
    def setUp(self):
        super().setUp()
        self.tasks = FakeTasks(self)
        self.schtasks.side_effect = self.tasks
        self.patch("decklab.lib.homenet.commands.find_server", return_value=(None, {"answered": False}))
        self.patch("decklab.lib.homenet.commands.file_exists", return_value=True)
        self.patch("decklab.lib.homenet.commands.pythonw_path", return_value=Path(sys.executable))
        self.patch("decklab.lib.homenet.commands.task_user", return_value="HOMEPC\\player")
        self.start = self.patch("decklab.lib.homenet.commands._start_task", return_value=0)

    def test_install_at_logon_registers_both_tasks(self):
        with Quiet() as q:
            self.assertEqual(homenet.cmd_install(TASK, PORT, no_start=True, at_logon=True), 0)
        self.assertEqual(sorted(self.tasks.tasks), [TASK, WATCH])
        watch = homenet.parse_task_xml(self.tasks.tasks[WATCH])
        self.assertEqual(Path(watch["command"]), Path(sys.executable))
        self.assertEqual(homenet.split_args(watch["arguments"]), ["-m", "decklab.lib.homenet", "ensure", "--task", TASK])
        self.assertEqual(Path(watch["workdir"]), config.REPO)
        self.assertEqual(watch["repeats"], ["PT5M"])
        self.assertIn(('/Query', WATCH), self.tasks.commands())          # read back
        self.assertIn(f'Registered the "{WATCH}" task: every 5 minutes', q.text)
        self.start.assert_not_called()

    def test_install_no_start_leaves_an_off_deck_lab_off(self):
        # Review finding: --no-start wrote no marker, so the new watchdog took "off" for a
        # crash and started Deck Lab within a minute, though install said "It starts at the
        # next logon".
        with Quiet():
            self.assertEqual(homenet.cmd_install(TASK, PORT, no_start=True, at_logon=True), 0)
        self.assertEqual(self.control.markers[PORT]["by"], "install --no-start")
        # A stop already recorded keeps its name.
        self.control.markers[PORT]["by"] = "homenet stop"
        with Quiet():
            homenet.cmd_install(TASK, PORT, no_start=True, at_logon=True)
        self.assertEqual(self.control.markers[PORT]["by"], "homenet stop")
        # A server that's running (the upgrade) isn't touched, nor is anything on the port.
        for found in ((running_state(port=PORT), {"answered": True, "deck_lab": True}),
                      (None, {"answered": False, "listening": True})):
            self.control.markers.clear()
            with mock.patch("decklab.lib.homenet.commands.find_server", return_value=found), Quiet():
                self.assertEqual(homenet.cmd_install(TASK, PORT, no_start=True, at_logon=True), 0)
            self.assertEqual(self.control.markers, {})
        # Without --at-logon there's no watchdog to keep off.
        with Quiet():
            homenet.cmd_install(TASK, PORT, no_start=True)
        self.assertEqual(self.control.markers, {})

    def test_install_without_at_logon_removes_the_watchdog(self):
        with Quiet():
            homenet.cmd_install(TASK, PORT, no_start=True, at_logon=True)
        with Quiet() as q:
            self.assertEqual(homenet.cmd_install(TASK, PORT, no_start=True), 0)
        self.assertEqual(list(self.tasks.tasks), [TASK])
        self.assertIn(("/Delete", WATCH), self.tasks.commands())
        self.assertIn(f'Removed the "{WATCH}" task', q.text)
        self.tasks.calls.clear()
        with Quiet():
            self.assertEqual(homenet.cmd_install(TASK, PORT, no_start=True), 0)
        self.assertNotIn(("/Delete", WATCH), self.tasks.commands())       # none to remove

    def test_install_that_starts_clears_the_marker(self):
        self.control.mark_stopped(PORT, "homenet stop")
        homenet.watchdog.save_record({"failures": 3, "gave_up_at": "x"}, PORT)
        with Quiet():
            self.assertEqual(homenet.cmd_install(TASK, PORT, at_logon=True), 0)
        self.start.assert_called_once()
        self.assertEqual(self.control.markers, {})
        record = homenet.watchdog.load_record(PORT)
        self.assertEqual((record["failures"], record["gave_up_at"]), (0, None))
        self.assertTrue(record["asked_at"])

    def test_remove_deletes_both(self):
        with Quiet():
            homenet.cmd_install(TASK, PORT, no_start=True, at_logon=True)
            self.assertEqual(homenet.commands.cmd_remove(TASK, PORT), 0)
        self.assertEqual(self.tasks.tasks, {})
        self.assertIn(("/Delete", WATCH), self.tasks.commands())
        self.assertIn(("/Delete", TASK), self.tasks.commands())

    def test_stop_records_the_stop_first(self):
        seen = []
        self.control.request_stop.side_effect = lambda port, wait: seen.append(dict(self.control.markers)) or "stopped"
        with Quiet():
            self.assertEqual(homenet.commands.cmd_stop(PORT), 0)
        self.assertEqual(seen[0][PORT]["by"], "homenet stop")
        # Also when nothing is running (it crashed, or was already stopped).
        self.control.markers.clear()
        self.control.request_stop.side_effect = None
        self.control.request_stop.return_value = "not running"
        with Quiet():
            self.assertEqual(homenet.commands.cmd_stop(PORT), 0)
        self.assertIn(PORT, self.control.markers)
        # A marker that can't be written is said, and the stop goes on.
        self.control.mark_stopped.side_effect = PermissionError(13, "Access is denied")
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_stop(PORT), 0)
        self.assertIn("Couldn't record the stop", q.text)
        self.assertIn("the watchdog may start Deck Lab again", q.text)

    def test_start_and_restart_clear_the_marker_before_the_run(self):
        self.tasks.register()
        seen = []
        self.start.side_effect = lambda *a: seen.append((dict(self.control.markers),
                                                         homenet.watchdog.load_record(PORT).get("failures"))) or 0
        for command in (homenet.commands.cmd_start, homenet.cmd_restart):
            self.control.mark_stopped(PORT, "homenet stop")
            homenet.watchdog.save_record({"failures": 2}, PORT)
            self.control.request_stop.return_value = "stopped"
            with Quiet():
                self.assertEqual(command(TASK, PORT), 0)
        self.assertEqual(seen, [({}, 0), ({}, 0)])
        # restart's stop wrote the marker, and its start cleared it again.
        self.assertEqual([c.args[1] for c in self.control.mark_stopped.call_args_list].count("homenet stop"), 3)

    def test_a_restart_whose_stop_times_out_leaves_a_restarts_marker(self):
        self.tasks.register()
        self.control.request_stop.return_value = "timeout"
        with Quiet() as q:
            self.assertEqual(homenet.cmd_restart(TASK, PORT), 1)
        self.start.assert_not_called()
        self.assertEqual((self.control.markers[PORT]["by"], self.control.markers[PORT].get("restart")),
                         ("homenet restart", True))
        self.assertIn("It wasn't started again. Once it has stopped, python -m decklab.lib.homenet start", q.text)


# ------------------------------------------------------------ status

class CheckWatchdogTests(unittest.TestCase):
    NOW = datetime(2026, 10, 20, 12, 0).astimezone()

    def check(self, task=None, watchdog=None, info=None, record=None, stopped=None, running=True, **kw):
        task = server_task() if task is None else task
        kw.setdefault("now", self.NOW)
        return homenet.check_watchdog(task, watchdog, info or {}, record or {}, stopped, running, name=TASK,
                                      exists=lambda path: "Gone" not in path, log_file="server.log", **kw)

    def test_missing_with_start_at_logon(self):
        out = self.check()
        self.assertEqual(levels(out), [WARN])
        self.assertIn("nothing restarts it if it stops unexpectedly", out[0]["text"])
        self.assertEqual(out[0]["fix"], "python -m decklab.lib.homenet install --at-logon --no-start")
        self.assertEqual(self.check(task=server_task(users=())), [])          # manual starts: none needed
        self.assertEqual(homenet.check_watchdog(None, None, {}, {}, None, False), [])

    def test_good(self):
        out = self.check(watchdog=watchdog_task(), info={"last_run": "2026-10-20T11:55:00", "last_result": 0})
        self.assertEqual(levels(out), [OK], texts(out))
        self.assertIn("Checks every 5 minutes and restarts Deck Lab if it stopped unexpectedly", out[0]["text"])

    def test_settings_that_dont_match_install(self):
        cases = [(dict(command=r"C:\Gone\pythonw.exe"), "which isn't there any more"),
                 (dict(command=PYTHON), "not pythonw.exe, so a console window"),
                 (dict(workdir=r"D:\Other"), "not this repo"),
                 (dict(arguments="-m decklab.lib.homenet ensure"), "doesn't run ensure for the \"Deck Lab test\""),
                 (dict(repeats=["PT1H"]), "doesn't run every 5 minutes (it repeats: PT1H)"),
                 (dict(enabled=False), "turned off (disabled)"),
                 (dict(logon_type="Password"), "logs on as Password")]
        for change, words in cases:
            with self.subTest(change=change):
                out = self.check(watchdog=watchdog_task(**change))
                self.assertEqual(levels(out), [WARN], texts(out))
                self.assertIn(words, out[0]["text"])
                self.assertIn("install --at-logon --no-start", out[0]["fix"])

    def test_left_there_without_start_at_logon(self):
        out = self.check(task=server_task(users=()), watchdog=watchdog_task())
        self.assertEqual(levels(out), [WARN])
        self.assertIn("doesn't start at logon", out[0]["text"])

    def test_gave_up(self):
        out = self.check(watchdog=watchdog_task(), record={"gave_up_at": "2026-10-20T11:15:00+10:00"})
        self.assertEqual(levels(out), [OK, PROBLEM])
        self.assertIn("The watchdog gave up at 2026-10-20 11:15 after 3 restarts in a row", out[1]["text"])
        self.assertIn("watchdog.log", out[1]["fix"])
        self.assertTrue(out[1]["fix"].endswith("then python -m decklab.lib.homenet start"))

    def test_restarts(self):
        recent = {"restarts": [{"at": "2026-10-20T10:00:00+10:00", "answered": True}]}
        out = self.check(watchdog=watchdog_task(), record=recent, now=datetime.fromisoformat("2026-10-20T12:00:00+10:00"))
        self.assertEqual(levels(out), [OK, WARN])
        self.assertIn("restarted Deck Lab at 2026-10-20 10:00 after it stopped unexpectedly.", out[1]["text"])
        self.assertIn("server.log", out[1]["fix"])
        out = self.check(watchdog=watchdog_task(), record=recent, now=datetime.fromisoformat("2026-10-22T12:00:00+10:00"))
        self.assertEqual(levels(out), [OK, OK])

    def test_stopped_on_purpose_shows_only_while_its_off(self):
        stopped = {"by": "homenet stop", "at": "2026-10-20T09:30:00+10:00"}
        out = self.check(watchdog=watchdog_task(), stopped=stopped, running=False)
        self.assertEqual(levels(out), [OK, OK])
        self.assertIn("Stopped on purpose at 2026-10-20 09:30 (homenet stop): the watchdog leaves it off", out[1]["text"])
        self.assertEqual(len(self.check(watchdog=watchdog_task(), stopped=stopped, running=True)), 1)
        out = self.check(watchdog=watchdog_task(), stopped={"by": "unreadable"}, running=False)
        self.assertEqual(levels(out), [OK, WARN])
        out = self.check(watchdog=watchdog_task(), running=False,
                         stopped={"by": "homenet restart", "restart": True, "at": "2026-10-20T09:30:00+10:00"})
        self.assertEqual(levels(out), [OK, OK])
        self.assertIn("A restart's stop didn't finish at 2026-10-20 09:30: the watchdog starts", out[1]["text"])

    def test_last_run(self):
        for result, words in ((homenet.TASK_TERMINATED, "ran for longer than its time limit"),
                              (1, "ended with exit code 1 (0x00000001)")):
            out = self.check(watchdog=watchdog_task(), info={"last_run": "2026-10-20T11:55:00", "last_result": result})
            self.assertEqual(levels(out), [OK, WARN])
            self.assertIn(words, out[1]["text"])
        for info in ({"last_run": "1999-11-30T00:00:00", "last_result": homenet.TASK_NOT_RUN_YET},
                     {"state": "Running", "last_run": "2026-10-20T11:55:00", "last_result": homenet.TASK_RUNNING}):
            self.assertEqual(levels(self.check(watchdog=watchdog_task(), info=info)), [OK])

    def test_a_read_error(self):
        out = self.check(error="Access is denied")
        self.assertEqual(levels(out), [WARN])
        self.assertIn("Couldn't read the watchdog task: Access is denied", out[0]["text"])


class StatusTests(Guarded):
    """cmd_status with the watchdog in the facts."""

    def run_status(self, facts):
        self.patch("decklab.lib.homenet.gather.gather_facts", return_value=facts)
        self.patch("decklab.lib.homenet.commands.probe", return_value=UP)
        self.patch("decklab.lib.homenet.mdns.mdns_lookup",
                   return_value={"answered": True, "addresses": ["192.0.2.10"], "error": None})
        self.patch("decklab.lib.homenet.commands.pc_name", return_value="HomePC")
        self.patch("decklab.lib.homenet.commands.local_ipv4", return_value="192.0.2.10")
        self.patch("decklab.lib.homenet.commands.pythonw_path", return_value=Path(PYTHONW))
        self.patch("decklab.lib.homenet.commands.this_pythons", return_value=[Path(PYTHON), Path(PYTHONW)])
        self.patch("decklab.lib.homenet.commands.newest_code_mtime", return_value=None)
        self.patch("decklab.lib.homenet.commands.task_user", return_value="HOMEPC\\player")
        self.patch("decklab.lib.homenet.commands.file_exists", return_value=True)
        self.control.read_state.return_value = running_state()
        with Quiet() as q:
            code = homenet.commands.cmd_status("Deck Lab", 8642)
        return code, " ".join(q.out.getvalue().split())

    def facts(self):
        facts = json.loads(json.dumps(REAL_FACTS_NOON))
        facts["watchdog"] = {"xml": homenet.watchdog_xml(PYTHONW, homenet.watchdog_arguments(), config.REPO,
                                                         "HOMEPC\\player"),
                             "state": "Ready", "last_run": "2026-10-20T11:55:00", "last_result": 0}
        return facts

    def test_with_the_watchdog(self):
        code, text = self.run_status(self.facts())
        self.assertEqual(code, 0, text)
        self.assertIn("OK Restart after a crash: Checks every 5 minutes", text)
        self.assertIn("0 problems, 5 warnings.", text)              # as at noon on 2026-10-01

    def test_a_watchdog_that_gave_up_is_a_problem(self):
        homenet.watchdog.save_record({"gave_up_at": "2026-10-20T11:15:00+10:00"}, 8642)
        code, text = self.run_status(self.facts())
        self.assertEqual(code, 1)
        self.assertIn("PROBLEM Restart after a crash: The watchdog gave up at 2026-10-20 11:15", text)


if __name__ == "__main__":
    unittest.main()
