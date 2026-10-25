"""Tests for decklab/lib/homenet/ (start at logon, stop, restart, status):
the task, the running server, the commands, the Server and Start at logon
checks, and status from end to end (task.py and commands.py). The other
status checks are tested in test_homenet_checks.py, gathering the facts and
the mDNS lookup in test_homenet_gather.py, and network-setup.ps1 in
test_network_setup.py; the fixtures they share are in homenet_support.py.

Nothing here registers or deletes a real scheduled task, changes the
firewall or the network, touches the real decklab/data/server.json or logs,
or signals port 8642 (where the real Deck Lab server may be running):
schtasks, the PowerShell call, control (the state file and stop requests)
and the server's answer are replaced, and the few real sockets use free
ports on 127.0.0.1.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from decklab.lib import config, homenet
from decklab.lib.homenet import OK, WARN, PROBLEM
from decklab.tests.homenet_support import (
    DECK_LAB_GOOD, PORT, PYTHON, PYTHONW, PYTHONW_RULE, REAL_FACTS, REAL_FACTS_NOON, SCRIPT, WINDOWS, FakeTime,
    Guarded, Quiet, fake_control, free_port, levels, network, rule, running_state, task_definition, texts,
)


# ------------------------------------------------------------ the task

class TaskXmlTests(unittest.TestCase):
    def build(self, **kw):
        args = dict(command=PYTHONW, arguments=homenet.server_arguments(SCRIPT),
                    workdir=r"C:\VSProjects\TradingCardCollection", user="HOMEPC\\player")
        args.update(kw)
        return homenet.task_xml(**args)

    def test_round_trip(self):
        task = homenet.parse_task_xml(self.build(at_logon=True))
        self.assertEqual(task["command"], PYTHONW)
        self.assertEqual(task["arguments"], f'"{SCRIPT}"')
        self.assertEqual(task["workdir"], r"C:\VSProjects\TradingCardCollection")
        self.assertEqual(task["repeats"], [])           # only the watchdog repeats
        self.assertTrue(task["enabled"])
        self.assertEqual(task["time_limit"], "PT0S")
        self.assertEqual(task["priority"], 5)
        self.assertEqual(task["multiple"], "IgnoreNew")
        self.assertEqual(task["logon_users"], ["HOMEPC\\player"])
        self.assertEqual(task["delay"], homenet.TASK_DELAY)
        self.assertEqual(task["logon_type"], "InteractiveToken")
        self.assertEqual(task["run_level"], "LeastPrivilege")

    def test_logon_trigger_off_by_default(self):
        # The trigger is there (Task Scheduler can turn it on) but off; the task still runs on start.
        text = self.build()
        self.assertIn("<LogonTrigger>\n      <Enabled>false</Enabled>", text)
        self.assertIn("<AllowStartOnDemand>true<", text)
        self.assertIn("The logon trigger is off", text)
        task = homenet.parse_task_xml(text)
        self.assertEqual(task["logon_users"], [])
        self.assertTrue(task["enabled"])
        self.assertIn("<LogonTrigger>\n      <Enabled>true</Enabled>", self.build(at_logon=True))

    def test_settings(self):
        text = self.build()
        self.assertTrue(text.startswith('<?xml version="1.0" encoding="UTF-16"?>'))
        for setting in ("<DisallowStartIfOnBatteries>false<", "<StopIfGoingOnBatteries>false<",
                        "<RunOnlyIfNetworkAvailable>false<", "<StartWhenAvailable>false<",
                        "<AllowHardTerminate>true<", "<RunOnlyIfIdle>false<", "<AllowStartOnDemand>true<",
                        "<StopOnIdleEnd>false<", "<Enabled>true</Enabled>", "<URI>\\Deck Lab</URI>"):
            self.assertIn(setting, text)
        self.assertNotIn("<IdleDuration>", text)
        self.assertNotIn("HighestAvailable", text)

    def test_values_are_escaped(self):
        odd = r"C:\Odd & <Folder>\it's"
        text = self.build(command=odd + r"\pythonw.exe", workdir=odd, user="DOM&AIN\\o'<b>",
                          arguments=homenet.server_arguments(odd + r"\decklab\server.py"), at_logon=True)
        task = homenet.parse_task_xml(text)
        self.assertEqual(task["command"], odd + r"\pythonw.exe")
        self.assertEqual(task["workdir"], odd)
        self.assertEqual(task["logon_users"], ["DOM&AIN\\o'<b>"])
        self.assertEqual(homenet.split_args(task["arguments"]), [odd + r"\decklab\server.py"])

    def test_name_goes_into_uri(self):
        self.assertIn("<URI>\\Deck Lab test</URI>", self.build(name="Deck Lab test"))

    def test_parses_what_schtasks_prints(self):
        # schtasks /Query /XML: a UTF-16 declaration, \r\r\n line ends, a newer version.
        text = self.build().replace('version="1.2"', 'version="1.6"').replace("\n", "\r\r\n")
        self.assertEqual(homenet.parse_task_xml(text)["command"], PYTHONW)

    def test_defaults_and_disabled_trigger(self):
        text = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task xmlns="{homenet.TASK_NS}"><Triggers><LogonTrigger><Enabled>false</Enabled><UserId>A\\b</UserId>
</LogonTrigger></Triggers><Actions><Exec><Command>x.exe</Command></Exec></Actions></Task>"""
        task = homenet.parse_task_xml(text)
        self.assertEqual(task["time_limit"], "PT72H")     # Task Scheduler's default
        self.assertEqual(task["priority"], 7)
        self.assertEqual(task["logon_users"], [])
        self.assertEqual(task["arguments"], "")

    def test_not_a_task(self):
        for text in ("", "not xml", "<Other/>", "<Task/>"):
            with self.assertRaises(ValueError):
                homenet.parse_task_xml(text)

    def test_server_arguments(self):
        self.assertEqual(homenet.server_arguments(r"C:\a b\server.py"), r'"C:\a b\server.py"')
        self.assertEqual(homenet.server_arguments(r"C:\a\server.py", port=18642, log_path=r"C:\temp dir\s.log"),
                         r'"C:\a\server.py" --port 18642 --log "C:\temp dir\s.log"')
        self.assertEqual(homenet.server_arguments(r"C:\a\server.py", port=1, host="127.0.0.1"),
                         r'"C:\a\server.py" --host 127.0.0.1 --port 1')

    def test_split_and_quote_round_trip(self):
        for arg in ["plain", "with space", 'quote"inside', "trailing\\", "back\\\\slashes \\", "", 'a\\"b',
                    r"C:\Program Files\x\\"]:
            self.assertEqual(homenet.split_args(homenet.quote_arg(arg)), [arg], arg)
        self.assertEqual(homenet.split_args(r'"C:\a b\server.py" --port 1 x'), [r"C:\a b\server.py", "--port", "1", "x"])
        self.assertEqual(homenet.split_args('  a   "b c"  '), ["a", "b c"])

    def test_task_problem(self):
        there = {PYTHONW.lower(), SCRIPT.lower(), r"c:\repo\decklab\server.py"}
        exists = lambda path: path.lower() in there         # noqa: E731
        self.assertIsNone(homenet.task_problem(task_definition(), exists))
        # After a Python upgrade the task points at a folder that's gone.
        problem = homenet.task_problem(task_definition(command=r"C:\Old\Python313\pythonw.exe"), exists)
        self.assertEqual(problem, r"The task starts C:\Old\Python313\pythonw.exe, which isn't there any more")
        problem = homenet.task_problem(task_definition(arguments=r'"D:\Moved\decklab\server.py"'), exists)
        self.assertIn(r"D:\Moved\decklab\server.py, which isn't there", problem)
        self.assertIn("which script", homenet.task_problem(task_definition(arguments=""), exists))
        self.assertIn("(nothing)", homenet.task_problem(task_definition(command=None), exists))
        # A relative script is found from the task's folder.
        relative = dict(task_definition(arguments=r"decklab\server.py"), workdir=r"C:\Repo")
        self.assertIsNone(homenet.task_problem(relative, exists))

    def test_task_log_file(self):
        with mock.patch("decklab.lib.homenet.commands.control", fake_control()) as control:
            self.assertEqual(homenet.task_log_file(task_definition()), Path(control.LOG_FILE))
            self.assertEqual(homenet.task_log_file(None), Path(control.LOG_FILE))
        args = homenet.server_arguments(SCRIPT, port=18642, log_path=r"C:\temp dir\s.log")
        self.assertEqual(homenet.task_log_file(task_definition(arguments=args)), Path(r"C:\temp dir\s.log"))
        relative = dict(task_definition(arguments=f'"{SCRIPT}" --log=logs\\t.log'), workdir=r"C:\Repo")
        self.assertEqual(homenet.task_log_file(relative), Path(r"C:\Repo\logs\t.log"))

    def test_task_user(self):
        self.assertEqual(homenet.commands.task_user({"USERDOMAIN": "HOMEPC", "USERNAME": "player"}), "HOMEPC\\player")
        self.assertEqual(homenet.commands.task_user({"USERNAME": "player"}), "player")

    def test_pythonw_beside(self):
        self.assertEqual(homenet.commands.pythonw_path(PYTHON), Path(PYTHONW))

    def test_same_user(self):
        self.assertTrue(homenet.same_user("HOMEPC\\player", "homepc\\PLAYER"))
        self.assertTrue(homenet.same_user("player", "HOMEPC\\player"))
        self.assertTrue(homenet.same_user("S-1-5-21-1-2-3-1001", "HOMEPC\\player"))
        self.assertTrue(homenet.same_user(None, "HOMEPC\\player"))
        self.assertFalse(homenet.same_user("HOMEPC\\user1", "HOMEPC\\player"))
        self.assertFalse(homenet.same_user("OTHER\\player", "HOMEPC\\player"))


class SchtasksTests(Guarded):
    def test_register_writes_utf16_and_cleans_up(self):
        seen = {}

        def fake(*args, **kwargs):
            path = args[args.index("/XML") + 1]
            seen["args"], seen["path"] = args, path
            seen["bytes"] = Path(path).read_bytes()
            return 0, "SUCCESS", ""
        self.schtasks.side_effect = fake
        xml_text = homenet.task_xml(PYTHONW, '"x.py"', "C:\\", "A\\b", name="Deck Lab test")
        self.assertIsNone(homenet.register_task(xml_text, "Deck Lab test"))
        self.assertEqual(seen["args"][:3], ("/Create", "/TN", "Deck Lab test"))
        self.assertEqual(seen["args"][-1], "/F")
        self.assertTrue(seen["bytes"].startswith(b"\xff\xfe"))
        self.assertEqual(seen["bytes"].decode("utf-16"), xml_text)
        self.assertFalse(Path(seen["path"]).exists())

    def test_register_failure_says_why(self):
        self.schtasks.side_effect = None
        self.schtasks.return_value = (1, "", "ERROR: Access is denied.\r\n")
        self.assertEqual(homenet.register_task("<Task/>", "x"), "ERROR: Access is denied.")

    def test_query(self):
        self.schtasks.side_effect = None
        self.schtasks.return_value = (0, homenet.task_xml(PYTHONW, '"s.py"', "C:\\", "A\\b"), "")
        self.assertEqual(homenet.query_task("Deck Lab")["command"], PYTHONW)
        self.assertEqual(self.schtasks.call_args[0], ("/Query", "/TN", "Deck Lab", "/XML"))
        self.schtasks.return_value = (1, "", "ERROR: The system cannot find the file specified.")
        self.assertIsNone(homenet.query_task("Deck Lab"))

    def test_decode(self):
        self.assertEqual(homenet._decode("<a/>".encode("utf-16")), "<a/>")
        self.assertEqual(homenet._decode(b"\xef\xbb\xbfplain"), "plain")
        self.assertEqual(homenet._decode("Lórien".encode("utf-8")), "Lórien")


# ------------------------------------------------------------ status: the Server and Start at logon lines

class ServerCheckTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("decklab.lib.homenet.commands.control", fake_control())
        patcher.start()
        self.addCleanup(patcher.stop)

    def check(self, state, answer, **kw):
        return homenet.check_server(state, answer, PORT, "server.log", **kw)

    def test_running_in_background(self):
        lines = self.check(running_state(), {"answered": True, "deck_lab": True, "cards_ready": True})
        self.assertEqual(levels(lines), [OK])
        self.assertIn("in the background", lines[0]["text"])
        self.assertIn("process 4242", lines[0]["text"])
        self.assertIn("2026-10-01 18:02", lines[0]["text"])
        self.assertIn("server.log", lines[0]["text"])
        self.assertIn("card data ready. Log:", lines[0]["text"])

    def test_listening_on_this_pc_only(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            lines = self.check(dict(running_state(), host=host),
                               {"answered": True, "deck_lab": True, "cards_ready": True})
            self.assertEqual(levels(lines), [OK, PROBLEM], host)
            self.assertIn("not phones", lines[1]["text"])
        self.assertFalse(homenet.loopback("0.0.0.0"))
        self.assertFalse(homenet.loopback("192.0.2.10"))
        self.assertTrue(homenet.loopback("127.0.0.2"))

    def test_running_in_a_window(self):
        state = dict(running_state(background=False), log=None)
        lines = self.check(state, {"answered": True, "deck_lab": True, "cards_ready": True})
        self.assertIn("in a window", lines[0]["text"])
        self.assertIn("Its log is in its window", lines[0]["text"])

    def test_card_data_downloading_or_broken(self):
        lines = self.check(running_state(), {"answered": True, "deck_lab": True, "cards_ready": False,
                                             "updating": True})
        self.assertEqual(levels(lines), [OK, OK])
        lines = self.check(running_state(), {"answered": True, "deck_lab": True, "cards_ready": False,
                                             "updating": False, "card_error": "no network"})
        self.assertEqual(levels(lines), [OK, WARN])
        self.assertIn("no network", lines[1]["text"])

    def test_code_changed_since_it_started(self):
        started = "2026-10-01T18:02:11"
        later = time.mktime((2026, 10, 1, 19, 0, 0, 0, 0, -1))
        lines = self.check(running_state(started=started), {"answered": True, "deck_lab": True,
                                                            "cards_ready": True}, code_mtime=later)
        self.assertEqual(levels(lines), [OK, WARN])
        self.assertIn("restart", lines[1]["fix"])
        earlier = time.mktime((2026, 10, 1, 17, 0, 0, 0, 0, -1))
        self.assertFalse(homenet.code_changed_since(started, earlier))
        self.assertFalse(homenet.code_changed_since("not a time", later))
        self.assertFalse(homenet.code_changed_since(started, None))

    def test_newest_code_counts_lib_packages(self):
        # Milestone 7 made some lib modules packages (lib/api/...): their files count too.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "lib" / "api").mkdir(parents=True)
            files = {root / "server.py": 1000, root / "lib" / "cards.py": 2000,
                     root / "lib" / "api" / "saving.py": 3000, root / "lib" / "notes.txt": 4000}
            for path, when in files.items():
                path.write_text("", encoding="utf-8")
                os.utime(path, (when, when))
            self.assertEqual(homenet.commands.newest_code_mtime(root), 3000)
            os.utime(root / "server.py", (5000, 5000))
            self.assertEqual(homenet.commands.newest_code_mtime(root), 5000)
            self.assertIsNone(homenet.commands.newest_code_mtime(root / "nothing here"))

    def test_newest_code_counts_the_database_package_but_not_its_migrations(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "lib").mkdir()
            (root / "db" / "migrations").mkdir(parents=True)
            files = {root / "server.py": 1000, root / "lib" / "cards.py": 2000,
                     root / "db" / "conn.py": 3000, root / "db" / "migrations" / "0003_more.sql": 9000}
            for path, when in files.items():
                path.write_text("", encoding="utf-8")
                os.utime(path, (when, when))
            self.assertEqual(homenet.commands.newest_code_mtime(root), 3000)

    def test_recorded_but_not_answering(self):
        lines = self.check(running_state(), {"answered": False, "error": "nothing answered"})
        self.assertEqual(levels(lines), [PROBLEM])
        self.assertIn("restart", lines[0]["fix"])

    def test_old_server_without_state(self):
        lines = self.check(None, {"answered": True, "deck_lab": True, "cards_ready": True})
        self.assertEqual(levels(lines), [WARN])
        self.assertIn("Ctrl+C", lines[0]["fix"])

    def test_another_program_on_the_port(self):
        lines = self.check(None, {"answered": True, "deck_lab": False})
        self.assertEqual(levels(lines), [PROBLEM])
        self.assertIn("config.json", lines[0]["fix"])

    def test_not_running(self):
        lines = self.check(None, {"answered": False, "listening": False, "error": homenet.NOT_LISTENING})
        self.assertEqual(levels(lines), [PROBLEM])
        self.assertEqual(lines[0]["text"], "Deck Lab isn't running on port 8642, so the page can't open "
                                           "(nothing is listening there).")
        self.assertIn("homenet start", lines[0]["fix"])
        lines = self.check(None, {"answered": False}, other_state=running_state(port=18000))
        self.assertIn("port 18000", lines[0]["text"])

    def test_port_held_but_silent(self):
        answer = {"answered": False, "listening": True,
                  "error": "something took the connection but didn't answer within 2 seconds"}
        lines = self.check(None, answer)
        self.assertEqual(levels(lines), [PROBLEM])
        self.assertIn("Something has port 8642 open but doesn't answer", lines[0]["text"])
        self.assertNotIn("isn't running", lines[0]["text"])
        self.assertIn("Task Manager", lines[0]["fix"])


class TaskCheckTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("decklab.lib.homenet.commands.control", fake_control())
        patcher.start()
        self.addCleanup(patcher.stop)

    def check(self, task, info=None, exists=lambda p: True, **kw):
        return homenet.check_task(task, info or {"state": "Ready", "last_run": "2026-10-01T09:00:00",
                                                 "last_result": 0},
                                  SCRIPT, exists=exists, user="HOMEPC\\player", **kw)

    def test_not_registered(self):
        lines = homenet.check_task(None, {}, SCRIPT)
        self.assertEqual(levels(lines), [WARN])
        self.assertIn("start can't start Deck Lab", lines[0]["text"])
        self.assertIn("homenet install", lines[0]["fix"])
        # It names the pythonw.exe install would use (network-setup.ps1 -Pythonw takes it).
        lines = homenet.check_task(None, {}, SCRIPT, pythonw=PYTHONW)
        self.assertIn(f"start {PYTHONW}", lines[0]["fix"])

    def test_settings_changed_in_task_scheduler(self):
        cases = [(dict(logon_type="Password"), "logs on as Password"),
                 (dict(logon_type="S4U"), "another session"),
                 (dict(run_level="HighestAvailable"), "highest privileges"),
                 (dict(priority=7), "priority 7: below normal"),
                 (dict(priority=1), "priority 1: above normal"),
                 (dict(multiple="Parallel"), "set to Parallel, not IgnoreNew"),
                 (dict(multiple="StopExisting"), "StopExisting")]
        for changes, words in cases:
            lines = self.check(task_definition(**changes))
            warned = [item for item in lines if item["level"] == WARN]
            self.assertEqual(len(warned), 1, (changes, texts(lines)))
            self.assertIn(words, warned[0]["text"])
            self.assertIn("install again", warned[0]["fix"])
            self.assertFalse(any(item["text"].startswith("Set up:") for item in lines))
        for changes in (dict(priority=4), dict(priority=6), dict(run_level=None), dict(logon_type=None),
                        dict(logon_type="interactivetoken"), dict(multiple=None)):
            self.assertEqual(levels(self.check(task_definition(**changes))), [OK, OK], changes)

    def test_good_task(self):
        lines = self.check(task_definition())
        self.assertEqual(levels(lines), [OK, OK])
        self.assertTrue(lines[0]["text"].startswith("Set up: at logon, and on start, it starts"))
        self.assertIn("ended normally", lines[1]["text"])

    def test_off_at_logon(self):
        # The default: no enabled logon trigger (install's is off), so only start starts it. Not a warning.
        lines = self.check(task_definition(users=()))
        self.assertEqual(levels(lines), [OK, OK])
        self.assertTrue(lines[0]["text"].startswith("Off: Deck Lab starts only with python -m "
                                                    "decklab.lib.homenet start"))
        self.assertIn("--at-logon", lines[0]["text"])
        lines = self.check(task_definition(users=()), {"last_run": None, "last_result": 267011})
        self.assertIn("start runs it", lines[1]["text"])
        self.assertNotIn("next logon", lines[1]["text"])
        # Something wrong with it still shows: start needs it as much as a logon does.
        lines = self.check(task_definition(users=(), command=r"C:\Old\Python313\pythonw.exe"),
                           exists=lambda p: "Old" not in p)
        self.assertEqual(levels(lines)[0], PROBLEM)
        self.assertFalse(any(item["text"].startswith("Off:") for item in lines))

    def test_missing_pythonw(self):
        # After a Python upgrade the task points at a folder that's gone.
        lines = self.check(task_definition(command=r"C:\Old\Python313\pythonw.exe"),
                           exists=lambda p: "Old" not in p)
        self.assertEqual(levels(lines)[0], PROBLEM)
        self.assertIn("isn't there", lines[0]["text"])
        self.assertIn("install again", lines[0]["fix"])
        self.assertEqual(homenet.exit_code(lines), 1)

    def test_python_with_a_window(self):
        lines = self.check(task_definition(command=PYTHON))
        self.assertEqual(levels(lines)[0], WARN)
        self.assertIn("console window", lines[0]["text"])

    def test_another_repo(self):
        lines = self.check(task_definition(arguments=r'"D:\Other\decklab\server.py"'))
        self.assertEqual(levels(lines)[0], WARN)
        lines = self.check(task_definition(arguments=r'"D:\Gone\decklab\server.py"'),
                           exists=lambda p: "Gone" not in p)
        self.assertEqual(levels(lines)[0], PROBLEM)
        lines = self.check(task_definition(arguments=""))
        self.assertEqual(levels(lines)[0], PROBLEM)

    def test_same_script_written_differently(self):
        lines = self.check(task_definition(arguments=f'"{SCRIPT.lower()}" --port 8642'))
        self.assertEqual(levels(lines), [OK, OK])

    def test_disabled_time_limit_and_trigger(self):
        lines = self.check(task_definition(enabled=False))
        self.assertIn(WARN, levels(lines))
        lines = self.check(task_definition(time_limit="PT72H"))
        self.assertTrue(any("PT72H" in item["text"] for item in lines))
        lines = self.check(task_definition(users=("HOMEPC\\user1",)))
        self.assertTrue(any("user1" in item["text"] for item in lines))

    def test_read_error(self):
        lines = homenet.check_task(None, {}, SCRIPT, error="Access is denied")
        self.assertEqual(levels(lines), [WARN])
        self.assertIn("Access is denied", lines[0]["text"])

    def test_last_run(self):
        line = homenet._last_run_line
        self.assertIn("hasn't run yet", line({"last_run": "1999-11-30T00:00:00", "last_result": 267011})["text"])
        self.assertIn("hasn't run yet", line({"last_run": None, "last_result": 267011})["text"])
        self.assertIn("next logon", line({"last_run": None, "last_result": 267011}, at_logon=True)["text"])
        self.assertIn("running now", line({"state": "Running", "last_run": "2026-10-01T09:00:00",
                                           "last_result": 267009})["text"])
        self.assertEqual(line({"last_run": "2026-10-01T09:00:00", "last_result": 0})["level"], OK)
        self.assertEqual(line({"last_run": "2026-10-01T09:00:00", "last_result": 0x41306})["level"], OK)
        failed = line({"last_run": "2026-10-01T09:00:00", "last_result": 1})
        self.assertEqual(failed["level"], WARN)
        self.assertIn("exit code 1 (0x00000001)", failed["text"])
        self.assertIn("log", failed["fix"])
        negative = line({"last_run": "2026-10-01T09:00:00", "last_result": -1073741510})
        self.assertIn("0xC000013A", negative["text"])


# ------------------------------------------------------------ the server's answer

class FakeStatus(BaseHTTPRequestHandler):
    body = b'{"cards": {"ready": true, "error": null}, "updating": false, "update_error": null}'

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


class ProbeTests(unittest.TestCase):
    def serve(self, body):
        handler = type("Handler", (FakeStatus,), {"body": body})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_deck_lab(self):
        port = self.serve(FakeStatus.body)
        self.assertEqual(homenet.commands.probe(port), {"answered": True, "deck_lab": True, "status": 200,
                                               "cards_ready": True, "updating": False, "card_error": None})

    def test_updating(self):
        port = self.serve(b'{"cards": {"ready": false, "error": null}, "updating": true, "update_error": null}')
        answer = homenet.commands.probe(port)
        self.assertFalse(answer["cards_ready"])
        self.assertTrue(answer["updating"])

    def test_something_else(self):
        port = self.serve(b"<html>hello</html>")
        self.assertEqual(homenet.commands.probe(port), {"answered": True, "deck_lab": False, "status": 200})

    def test_nothing_listening_is_quick(self):
        port = free_port()
        started = time.monotonic()
        answer = homenet.commands.probe(port)
        self.assertFalse(answer["answered"])
        self.assertLess(time.monotonic() - started, 1.8)
        # Windows reports the refused connection as a timeout (TCP_MAXRT), but while connecting.
        self.assertIs(answer["listening"], False)
        self.assertEqual(answer["error"], homenet.NOT_LISTENING)

    def test_listening_but_not_answering(self):
        # Windows takes the connection for a listening socket that never accepts it.
        quiet = socket.socket()
        quiet.bind(("127.0.0.1", 0))
        quiet.listen(1)
        self.addCleanup(quiet.close)
        answer = homenet.commands.probe(quiet.getsockname()[1], timeout=0.5)
        self.assertFalse(answer["answered"])
        self.assertIs(answer["listening"], True)
        self.assertIn("didn't answer within 0.5 seconds", answer["error"])


# ------------------------------------------------------------ commands

class CommandTests(Guarded):
    def setUp(self):
        super().setUp()
        self.schtasks.side_effect = self.fake_schtasks
        self.calls = []
        self.registered = None      # the server task's XML
        self.watchdog = None        # ... and the watchdog task's
        self.find = self.patch("decklab.lib.homenet.commands.find_server", return_value=(None, {"answered": False}))
        self.patch("decklab.lib.homenet.commands.local_ipv4", return_value="192.0.2.10")
        self.clock = self.patch("decklab.lib.homenet.commands.time", FakeTime())
        # The task's pythonw.exe and server.py are there unless a test says otherwise.
        self.exists = self.patch("decklab.lib.homenet.commands.file_exists", return_value=True)
        self.on_run = None          # called on each /Run (a test's stand-in for the server starting)

    def fake_schtasks(self, *args, **kwargs):
        self.calls.append(args)
        which = "watchdog" if args[2].endswith(" watchdog") else "registered"
        if args[0] == "/Query":
            if getattr(self, which) is None:
                return 1, "", "ERROR: not found"
            return 0, getattr(self, which), ""
        if args[0] == "/Create":
            setattr(self, which, Path(args[args.index("/XML") + 1]).read_bytes().decode("utf-16"))
            return 0, "SUCCESS", ""
        if args[0] == "/Delete":
            setattr(self, which, None)
        if args[0] == "/Run" and self.on_run:
            self.on_run()
        return 0, "SUCCESS", ""

    def register(self, command=PYTHONW, arguments=f'"{SCRIPT}"'):
        self.registered = homenet.task_xml(command, arguments, "C:\\", "A\\b", name="Deck Lab test")

    def temp_folder(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return Path(folder.name)

    def commands(self):
        return [c[0] for c in self.calls]

    def test_start_needs_the_task(self):
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_start("Deck Lab test", 18642), 1)
        self.assertIn("run python -m decklab.lib.homenet install first", q.text)
        self.assertNotIn("/Run", self.commands())

    @unittest.skipUnless(WINDOWS, "start uses Task Scheduler")
    def test_start_runs_the_task_and_waits(self):
        self.register()
        answers = iter([{"answered": False}, {"answered": False}, {"answered": True, "deck_lab": True}])
        self.patch("decklab.lib.homenet.commands.probe", side_effect=lambda *a, **k: next(answers))
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_start("Deck Lab test", 18642), 0)
        self.assertIn(("/Run", "/TN", "Deck Lab test"), self.calls)
        self.assertIn("Deck Lab is running.", q.text)
        self.assertIn("http://192.0.2.10:18642/", q.text)
        self.assertIn("http://localhost:18642/", q.text)

    @unittest.skipUnless(WINDOWS, "start uses Task Scheduler")
    def test_start_when_already_running(self):
        self.register()
        self.find.return_value = (running_state(port=18642), {"answered": True, "deck_lab": True})
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_start("Deck Lab test", 18642), 0)
        self.assertIn("already running (process 4242", q.text)
        self.assertNotIn("/Run", self.commands())

    @unittest.skipUnless(WINDOWS, "start uses Task Scheduler")
    def test_start_that_never_answers_shows_the_log(self):
        self.register()
        log = self.temp_folder() / "server.log"
        log.write_text("2026-09-30 18:00 an old run: Serving on http://0.0.0.0:18642\n", encoding="utf-8")
        self.control.LOG_FILE = log

        def server_fails():
            with open(log, "a", encoding="utf-8") as f:
                f.write("2026-10-01 12:00 Can't listen on 0.0.0.0:18642: in use\n")
        self.on_run = server_fails
        self.patch("decklab.lib.homenet.commands.probe", return_value={"answered": False})
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_start("Deck Lab test", 18642), 1)
        self.assertIn("didn't answer on port 18642", q.text)
        self.assertIn("Can't listen on 0.0.0.0:18642", q.text)
        self.assertNotIn("an old run", q.text)                     # only what this start wrote
        self.assertEqual(self.commands().count("/Run"), 2)        # asked once more after RERUN_AFTER

    @unittest.skipUnless(WINDOWS, "start uses Task Scheduler")
    def test_start_that_writes_nothing_says_so(self):
        self.register()
        log = self.temp_folder() / "server.log"
        log.write_text("2026-09-30 18:00 an old run: Serving on http://0.0.0.0:18642\n", encoding="utf-8")
        self.control.LOG_FILE = log
        self.patch("decklab.lib.homenet.commands.probe", return_value={"answered": False})
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_start("Deck Lab test", 18642), 1)
        self.assertIn("It wrote nothing to its log", q.text)
        self.assertIn("homenet status", q.text)
        self.assertNotIn("an old run", q.text)

    def test_log_tail_after_a_rotation(self):
        log = self.temp_folder() / "server.log"
        log.write_text("new file\n", encoding="utf-8")
        self.assertEqual(homenet._log_tail(log, start=5000), ["new file"])     # rotated: shorter than before
        self.assertEqual(homenet._log_tail(log, start=log.stat().st_size), [])
        self.assertEqual(homenet._log_tail(log.with_name("missing.log")), [])

    @unittest.skipUnless(WINDOWS, "start uses Task Scheduler")
    def test_start_watches_the_tasks_own_log(self):
        log = self.temp_folder() / "own.log"
        self.register(arguments=homenet.server_arguments(SCRIPT, port=18642, log_path=log))
        self.on_run = lambda: log.write_text("Card data check failed\n", encoding="utf-8")
        self.patch("decklab.lib.homenet.commands.probe", return_value={"answered": False})
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_start("Deck Lab test", 18642), 1)
        self.assertIn(f"({log})", q.text)
        self.assertIn("Card data check failed", q.text)

    @unittest.skipUnless(WINDOWS, "start uses Task Scheduler")
    def test_start_and_restart_check_the_task_first(self):
        # After a Python upgrade: schtasks /Run says SUCCESS for a pythonw.exe that's gone.
        self.register(command=r"C:\Old\Python313\pythonw.exe")
        self.exists.side_effect = lambda path: "Old" not in path
        self.find.return_value = (running_state(port=18642), {"answered": True, "deck_lab": True})
        for command in (homenet.commands.cmd_start, homenet.cmd_restart):
            with Quiet() as q:
                self.assertEqual(command("Deck Lab test", 18642), 1)
            self.assertIn(r"The task starts C:\Old\Python313\pythonw.exe, which isn't there any more", q.text)
            self.assertIn("install again", q.text)
        self.assertIn("(nothing was stopped)", q.text)
        self.assertNotIn("/Run", self.commands())
        self.control.request_stop.assert_not_called()              # the working server was left alone
        # The repo moved: the script is gone.
        self.register(arguments=r'"D:\Moved\decklab\server.py"')
        self.exists.side_effect = lambda path: "Moved" not in path
        with Quiet() as q:
            self.assertEqual(homenet.cmd_restart("Deck Lab test", 18642), 1)
        self.assertIn(r"D:\Moved\decklab\server.py, which isn't there any more", q.text)
        self.control.request_stop.assert_not_called()

    def test_stop_results(self):
        cases = [("stopped", 0, "Deck Lab stopped."), ("not running", 0, "isn't running"),
                 ("timeout", 1, "still running after")]
        for result, code, words in cases:
            self.control.request_stop.reset_mock()
            self.control.request_stop.return_value = result
            with Quiet() as q:
                self.assertEqual(homenet.commands.cmd_stop(18642), code, result)
            self.assertIn(words, q.text)
            self.control.request_stop.assert_called_once_with(18642, wait=homenet.STOP_WAIT)

    def test_stop_that_cant_signal_the_server(self):
        # On Windows: the server runs as administrator or in another session.
        self.control.request_stop.return_value = "unsupported"
        self.find.return_value = (running_state(port=18642), {"answered": True, "deck_lab": True})
        with mock.patch.object(sys, "platform", "win32"), Quiet() as q:
            self.assertEqual(homenet.commands.cmd_stop(18642), 1)
        self.assertIn("Deck Lab (pythonw.exe, process 4242) can't be signalled from here", q.text)
        self.assertIn("administrator", q.text)
        self.assertIn("end pythonw.exe (process 4242) in Task Manager", q.text)
        self.assertNotIn("only works on Windows", q.text)
        self.find.return_value = (None, {"answered": True, "deck_lab": True})
        with mock.patch.object(sys, "platform", "win32"), Quiet() as q:
            self.assertEqual(homenet.commands.cmd_stop(18642), 1)
        self.assertIn("The Deck Lab server on port 18642 can't be signalled", q.text)
        # Off Windows there's no stop event at all.
        with mock.patch.object(sys, "platform", "linux"), Quiet() as q:
            self.assertEqual(homenet.commands.cmd_stop(18642), 1)
        self.assertIn("only works on Windows", q.text)

    def test_stop_when_an_old_server_answers(self):
        self.find.return_value = (None, {"answered": True, "deck_lab": True})
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_stop(18642), 1)
        self.assertIn("Ctrl+C", q.text)

    def test_stop_when_another_program_has_the_port(self):
        self.find.return_value = (None, {"answered": True, "deck_lab": False})
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_stop(18642), 0)
        self.assertIn("Deck Lab isn't running. (Another program answers on port 18642.)", q.text)

    def test_stop_timeout_names_the_program(self):
        self.find.return_value = (running_state(port=18642, python=PYTHON), {"answered": True, "deck_lab": True})
        self.control.request_stop.return_value = "timeout"
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_stop(18642), 1)
        self.assertIn("(process 4242)", q.text)
        self.assertIn("end python.exe in Task Manager", q.text)

    @unittest.skipUnless(WINDOWS, "install uses Task Scheduler")
    def test_install_registers_and_starts(self):
        self.patch("decklab.lib.homenet.commands.pythonw_path", return_value=Path(sys.executable))
        started = self.patch("decklab.lib.homenet.commands._start_task", return_value=0)
        with Quiet() as q:
            self.assertEqual(homenet.cmd_install("Deck Lab test", 18642, port_given=True,
                                                 log_path=r"C:\temp dir\t.log"), 0)
        task = homenet.parse_task_xml(self.registered)
        self.assertEqual(Path(task["command"]), Path(sys.executable))
        self.assertEqual(homenet.split_args(task["arguments"]),
                         [str(homenet.SERVER_SCRIPT), "--port", "18642", "--log", r"C:\temp dir\t.log"])
        self.assertEqual(Path(task["workdir"]), config.REPO)
        self.assertIn("<URI>\\Deck Lab test</URI>", self.registered)
        started.assert_called_once_with("Deck Lab test", 18642, task)
        self.assertEqual(homenet.task_log_file(task), Path(r"C:\temp dir\t.log"))
        self.assertIn('Registered the "Deck Lab test" task', q.text)
        # Off at logon unless asked for.
        self.assertEqual(task["logon_users"], [])
        self.assertIn("doesn't start at logon", q.text)

    @unittest.skipUnless(WINDOWS, "install uses Task Scheduler")
    def test_install_at_logon(self):
        self.patch("decklab.lib.homenet.commands.pythonw_path", return_value=Path(sys.executable))
        self.patch("decklab.lib.homenet.commands.task_user", return_value="HOMEPC\\player")
        started = self.patch("decklab.lib.homenet.commands._start_task", return_value=0)
        with Quiet() as q:
            self.assertEqual(homenet.cmd_install("Deck Lab test", 18642, no_start=True, at_logon=True), 0)
        started.assert_not_called()
        self.assertEqual(homenet.parse_task_xml(self.registered)["logon_users"], ["HOMEPC\\player"])
        self.assertIn("at each logon (after 30 seconds), and on start", q.text)
        self.assertIn("It starts at the next logon", q.text)
        self.assertNotIn("doesn't start at logon", q.text)
        # main passes --at-logon through; without it, install leaves it off.
        with Quiet():
            self.assertEqual(homenet.main(["install", "--no-start", "--task", "Deck Lab test", "--port", "18642"]), 0)
        self.assertEqual(homenet.parse_task_xml(self.registered)["logon_users"], [])
        with Quiet():
            self.assertEqual(homenet.main(["install", "--at-logon", "--no-start", "--task", "Deck Lab test",
                                           "--port", "18642"]), 0)
        self.assertEqual(homenet.parse_task_xml(self.registered)["logon_users"], ["HOMEPC\\player"])
        started.assert_not_called()

    @unittest.skipUnless(WINDOWS, "install uses Task Scheduler")
    def test_install_when_another_program_has_the_port(self):
        self.patch("decklab.lib.homenet.commands.pythonw_path", return_value=Path(sys.executable))
        started = self.patch("decklab.lib.homenet.commands._start_task", return_value=0)
        self.find.return_value = (None, {"answered": True, "deck_lab": False})
        with Quiet() as q:
            self.assertEqual(homenet.cmd_install("Deck Lab test", 18642), 1)
        started.assert_not_called()
        self.assertIn('Registered the "Deck Lab test" task', q.text)
        self.assertIn("Deck Lab can't start now, though: another program uses port 18642.", q.text)
        self.assertNotIn("a second time", q.text)

    @unittest.skipUnless(WINDOWS, "install uses Task Scheduler")
    def test_install_no_start_and_already_running(self):
        self.patch("decklab.lib.homenet.commands.pythonw_path", return_value=Path(sys.executable))
        started = self.patch("decklab.lib.homenet.commands._start_task", return_value=0)
        with Quiet():
            self.assertEqual(homenet.cmd_install("Deck Lab test", 18642, no_start=True), 0)
        task = homenet.parse_task_xml(self.registered)
        self.assertEqual(homenet.split_args(task["arguments"]), [str(homenet.SERVER_SCRIPT)])
        self.find.return_value = (running_state(port=18642), {"answered": True, "deck_lab": True})
        with Quiet() as q:
            self.assertEqual(homenet.cmd_install("Deck Lab test", 18642), 0)
        started.assert_not_called()
        self.assertIn("wasn't started a second time", q.text)
        self.assertIn("homenet restart", q.text)

    @unittest.skipUnless(WINDOWS, "install uses Task Scheduler")
    def test_install_refuses_without_pythonw(self):
        self.patch("decklab.lib.homenet.commands.pythonw_path",
                   return_value=Path(tempfile.gettempdir()) / "no-pythonw.exe")
        with Quiet() as q:
            self.assertEqual(homenet.cmd_install("Deck Lab test", 18642), 1)
        self.assertIn("pythonw.exe", q.text)
        self.assertEqual(self.calls, [])

    @unittest.skipUnless(WINDOWS, "remove uses Task Scheduler")
    def test_remove(self):
        self.register()
        self.control.request_stop.return_value = "stopped"
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_remove("Deck Lab test", 18642), 0)
        self.assertIn(("/Delete", "/TN", "Deck Lab test", "/F"), self.calls)
        self.assertIn("Removed the \"Deck Lab test\" task: Deck Lab doesn't start at logon", q.text)
        self.control.request_stop.assert_called_once_with(18642, wait=homenet.STOP_WAIT)
        with Quiet() as q:
            self.assertEqual(homenet.commands.cmd_remove("Deck Lab test", 18642), 0)
        self.assertIn("isn't registered", q.text)

    @unittest.skipUnless(WINDOWS, "restart uses Task Scheduler")
    def test_restart(self):
        self.register()
        self.control.request_stop.return_value = "stopped"
        started = self.patch("decklab.lib.homenet.commands._start_task", return_value=0)
        with Quiet():
            self.assertEqual(homenet.cmd_restart("Deck Lab test", 18642), 0)
        started.assert_called_once_with("Deck Lab test", 18642, mock.ANY)
        self.assertEqual(started.call_args[0][2]["command"], PYTHONW)
        self.control.request_stop.return_value = "timeout"
        started.reset_mock()
        with Quiet():
            self.assertEqual(homenet.cmd_restart("Deck Lab test", 18642), 1)
        started.assert_not_called()

    def test_main_options(self):
        status = self.patch("decklab.lib.homenet.commands.cmd_status", return_value=0)
        self.assertEqual(homenet.main(["status", "--task", "Deck Lab test", "--port", "18642"]), 0)
        status.assert_called_once_with("Deck Lab test", 18642)
        status.reset_mock()
        homenet.main(["status"])
        status.assert_called_once_with(homenet.TASK_NAME, config.load().get("port", 8642))

    def test_main_with_a_broken_config(self):
        status = self.patch("decklab.lib.homenet.commands.cmd_status", return_value=0)
        stop = self.patch("decklab.lib.homenet.commands.cmd_stop", return_value=0)
        start = self.patch("decklab.lib.homenet.commands.cmd_start", return_value=0)
        remove = self.patch("decklab.lib.homenet.commands.cmd_remove", return_value=0)
        broken = ValueError("Expecting ',' delimiter: line 3 column 5 (char 20)")
        self.patch("decklab.lib.config.load", side_effect=broken)
        for argv in (["status"], ["stop"], ["start"], ["remove"], ["restart", "--port", "18642"]):
            with Quiet() as q:
                self.assertEqual(homenet.main(argv), 1, argv)
            self.assertIn("decklab/config.json can't be read: ValueError: Expecting ','", q.text)
            self.assertIn("stop --port 8642", q.text)
            self.assertNotIn("Traceback", q.text)
        self.assertIn("or remove, with --port 8642", q.text)
        status.assert_not_called()
        start.assert_not_called()
        remove.assert_not_called()
        # stop, status and remove still work when given the port.
        with Quiet() as q:
            self.assertEqual(homenet.main(["status", "--port", "18642"]), 0)
            self.assertEqual(homenet.main(["stop", "--port", "18642"]), 0)
            self.assertEqual(homenet.main(["remove", "--port", "18642"]), 0)
        status.assert_called_once_with(homenet.TASK_NAME, 18642)
        stop.assert_called_once_with(18642)
        remove.assert_called_once_with(homenet.TASK_NAME, 18642)
        self.assertIn("can't be read", q.err.getvalue())
        self.patch("decklab.lib.config.load", side_effect=PermissionError(13, "Permission denied"))
        with Quiet() as q:
            self.assertEqual(homenet.main(["install"]), 1)
        self.assertIn("Permission denied", q.text)


class StatusCommandTests(Guarded):
    """cmd_status from end to end, with canned facts."""

    def run_status(self, facts, state=None, answer=None, mdns=None):
        self.control.read_state.return_value = state
        self.patch("decklab.lib.homenet.gather.gather_facts", return_value=facts)
        self.patch("decklab.lib.homenet.commands.probe",
                   return_value=answer or {"answered": False, "error": "nothing answered"})
        self.patch("decklab.lib.homenet.mdns.mdns_lookup",
                   return_value=mdns or {"answered": True, "addresses": ["192.0.2.10"], "error": None})
        self.patch("decklab.lib.homenet.commands.pc_name", return_value="HomePC")
        self.patch("decklab.lib.homenet.commands.local_ipv4", return_value="192.0.2.10")
        self.patch("decklab.lib.homenet.commands.pythonw_path", return_value=Path(PYTHONW))
        self.patch("decklab.lib.homenet.commands.this_pythons", return_value=[Path(PYTHON), Path(PYTHONW)])
        self.patch("decklab.lib.homenet.commands.newest_code_mtime", return_value=None)
        with Quiet() as q:
            code = homenet.commands.cmd_status("Deck Lab", PORT)
        return code, " ".join(q.out.getvalue().split())     # the report's wrapping undone

    def test_the_real_pc_on_2026_10_01(self):
        code, text = self.run_status(REAL_FACTS)
        self.assertEqual(code, 1)                   # the server isn't running
        self.assertIn("PROBLEM Server: Deck Lab isn't running", text)
        self.assertIn("WARN Start at logon: The task isn't set up", text)
        self.assertIn("OK Network: Ethernet", text)
        self.assertIn("192.0.2.10/24 from the router (DHCP), on a Private network", text)
        self.assertIn("OK Firewall: TCP 8642 is let in on Private networks", text)
        self.assertIn("every kind of network (Domain, Private and Public)", text)
        self.assertEqual(text.count("for python.exe on Private and Public networks"), 2)
        self.assertIn("http://192.0.2.10:8642/", text)
        self.assertIn("http://homepc.local:8642/", text)
        self.assertIn("MAC address 00-00-5E-00-53-01", text)
        self.assertIn("OK Sleep: The PC never sleeps", text)
        self.assertNotIn("pythonw.exe (which runs Deck Lab", text)     # the port rule covers it
        self.assertIn("1 problem, 4 warnings.", text)
        self.assertIn("can't prove a phone gets through", text)

    def test_the_real_pc_at_noon(self):
        self.patch("decklab.lib.homenet.commands.task_user", return_value="HOMEPC\\player")
        self.patch("decklab.lib.homenet.commands.file_exists", return_value=True)
        code, text = self.run_status(REAL_FACTS_NOON, running_state(),
                                     {"answered": True, "deck_lab": True, "cards_ready": True})
        self.assertEqual(code, 0, text)
        self.assertIn("OK Start at logon: Set up: at logon, and on start, it starts", text)
        self.assertIn("OK Start at logon: The task is running now (started 2026-10-01 11:49).", text)
        self.assertIn("OK Firewall: TCP 8642 is let in on Private networks (rule 'pythonw.exe', "
                      "'Deck Lab (TCP 8642)')", text)
        self.assertEqual(text.count("for pythonw.exe on Private and Public networks"), 2)
        self.assertEqual(text.count("for python.exe on Private and Public networks"), 2)
        # Set up then, before the watchdog (E11-S26): status now says so, as a warning.
        self.assertIn("WARN Restart after a crash: Deck Lab starts at logon, but nothing restarts it", text)
        self.assertIn("install --at-logon --no-start", text)
        self.assertIn("0 problems, 6 warnings.", text)

    def test_hard_kill_says_nothing_is_listening(self):
        # After schtasks /End: the state file names a dead process, so read_state() gives None.
        code, text = self.run_status(REAL_FACTS, None, {"answered": False, "listening": False,
                                                        "error": homenet.NOT_LISTENING})
        self.assertEqual(code, 1)
        self.assertIn("PROBLEM Server: Deck Lab isn't running on port 8642, so the page can't open "
                      "(nothing is listening there).", text)

    def test_all_good(self):
        facts = json.loads(json.dumps(REAL_FACTS))
        facts["firewall"]["rules"] = [DECK_LAB_GOOD, PYTHONW_RULE]
        facts["task"] = {"xml": homenet.task_xml(PYTHONW, f'"{homenet.SERVER_SCRIPT}"', config.REPO,
                                                 "HOMEPC\\player"),
                         "state": "Running", "last_run": "2026-10-01T09:00:00", "last_result": 267009}
        self.patch("decklab.lib.homenet.commands.task_user", return_value="HOMEPC\\player")
        self.patch("decklab.lib.homenet.commands.file_exists", return_value=True)
        code, text = self.run_status(facts, running_state(),
                                     {"answered": True, "deck_lab": True, "cards_ready": True})
        self.assertEqual(code, 0, text)
        self.assertIn("OK Start at logon: Off: Deck Lab starts only with python -m decklab.lib.homenet start", text)
        self.assertIn("0 problems, 0 warnings.", text)

    def test_public_network_and_block_rule(self):
        facts = json.loads(json.dumps(REAL_FACTS))
        facts["network"] = network(category="Public")
        facts["firewall"]["rules"].append(rule("pythonw.exe", program=PYTHONW, ports="*", profiles=6, action=0))
        code, text = self.run_status(facts, running_state(),
                                     {"answered": True, "deck_lab": True, "cards_ready": True})
        self.assertEqual(code, 1)
        self.assertIn("PROBLEM Network", text)
        self.assertIn("PROBLEM Firewall: Rule 'pythonw.exe' blocks pythonw.exe", text)

    def test_powershell_failed(self):
        facts = {"errors": [], "error": "PowerShell didn't finish within 30 seconds", "seconds": 30.0}
        code, text = self.run_status(facts)
        self.assertIn("Couldn't read the firewall: PowerShell didn't finish", text)
        self.assertIn("Couldn't check the network", text)
        self.assertIn("Couldn't read the sleep setting", text)


# ------------------------------------------------------------ where tests patch

class PatchTargetTests(unittest.TestCase):
    """Each name a test replaces lives in one of homenet's modules, the one
    whose code looks it up, and the package itself doesn't offer it: a patch
    left on decklab.lib.homenet then fails instead of quietly reaching
    nothing (and letting the real schtasks, PowerShell, stop requests or
    multicast through)."""

    MODULES = ("common", "task", "commands", "gather", "mdns", "checks", "watchdog")
    REPLACED = {
        "commands": ("control", "_schtasks", "_start_task", "find_server", "probe", "local_ipv4", "file_exists",
                     "pythonw_path", "task_user", "pc_name", "this_pythons", "newest_code_mtime", "cmd_status",
                     "cmd_stop", "cmd_start", "cmd_remove", "time"),
        "gather": ("run_powershell", "gather_facts"),
        "mdns": ("MDNS_GROUP", "mdns_lookup"),
    }

    def test_each_has_one_home(self):
        for home, names in self.REPLACED.items():
            for name in names:
                found = [m for m in self.MODULES if name in vars(getattr(homenet, m))]
                if name == "time":
                    # The time module: only commands' code gets FakeTime (start's wait); gather and
                    # mdns keep the real clock.
                    found = [m for m in found if m not in ("gather", "mdns")]
                self.assertEqual(found, [home], name)
                self.assertNotIn(name, vars(homenet), name)

    def test_patches_aim_at_those_homes(self):
        replaced = {(home, name) for home, names in self.REPLACED.items() for name in names}
        targets = []
        for path in sorted(Path(__file__).parent.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            targets += re.findall(r'"decklab\.lib\.homenet\.(\w+)\.(\w+)"', text)
            targets += re.findall(r'patch\.object\(homenet\.(\w+), "(\w+)"', text)
            self.assertNotRegex(text, r'"decklab\.lib\.homenet\.\w+"', path.name)    # the package itself
            self.assertNotRegex(text, r"patch\.object\(homenet, ", path.name)
        self.assertGreater(len(targets), 20)
        for target in targets:
            self.assertIn(target, replaced)


if __name__ == "__main__":
    unittest.main()
