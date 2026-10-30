"""Restarting Deck Lab from the page (api/server_restart.py): who may, when it's refused, and the
helper it starts; nothing is started or stopped (the helper's launch is replaced)."""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from decklab.lib import build, control, permissions, tunnel
from decklab.lib.api import guard, server_restart
from decklab.lib.api.common import ApiError
from decklab.tests import test_permissions as people

STARTED = "2026-10-30T01:00:00+00:00"
CLEAN = {"started_at": STARTED, "latest_dirty": False, "error": None}


class _Proc:
    def __init__(self, code=None):
        self.code = code

    def wait(self, timeout=None):
        if self.code is None:
            raise subprocess.TimeoutExpired("homenet", timeout)
        return self.code


class ServerRestartTests(unittest.TestCase):
    def setUp(self):
        self.viewer = mock.patch.object(guard, "viewer", return_value=people.MATT).start()
        mock.patch.object(guard, "script", return_value=False).start()
        self.state = mock.patch.object(control, "read_state", return_value={
            "pid": os.getpid(), "port": 8642, "background": True}).start()
        mock.patch.object(tunnel, "usual_server", side_effect=lambda port, configured: port == 8642).start()
        self.build = mock.patch.object(build, "status", return_value=dict(CLEAN)).start()
        self.supervisor = mock.patch.object(server_restart, "_supervisor_problem", return_value=None).start()
        self.busy = mock.patch.object(server_restart, "_busy", return_value=[]).start()
        self.launch = mock.patch.object(server_restart, "_launch", return_value=_Proc()).start()
        mock.patch.object(server_restart, "_asked_at", None).start()
        self.addCleanup(mock.patch.stopall)

    def refused(self, status, call, *args):
        with self.assertRaises(ApiError) as caught:
            call(*args)
        self.assertEqual(caught.exception.status, status)
        return caught.exception

    def post(self, **body):
        return server_restart.restart(json.dumps({"profile": "matt", **body}).encode())

    def test_only_a_named_home_admin_even_for_an_unnamed_script(self):
        for viewer in (None, people.USER1, people.USER2, {**people.USER2, "role": "admin"}):
            for script in (False, True):
                with self.subTest(viewer=viewer, script=script), mock.patch.object(guard, "script", return_value=script):
                    self.viewer.return_value = viewer
                    self.refused(403, server_restart.view)
                    self.refused(403, server_restart.restart, b"not even json")
        self.launch.assert_not_called()
        self.assertIsNone(permissions.reason(people.MATT, "server.restart", script=False))
        self.assertIsNotNone(permissions.reason(None, "server.restart", script=True))

    def test_view_says_it_may_and_what_it_would_stop(self):
        self.busy.return_value = ["1 Forge matchup playing or waiting"]
        self.assertEqual(server_restart.view(), {"may_restart": True, "why_not": None,
                                                 "busy": ["1 Forge matchup playing or waiting"], "restarting": False})

    def test_restart_starts_the_helper_on_this_servers_port(self):
        self.assertEqual(self.post(), {"restarting": True, "started_at": STARTED})
        self.launch.assert_called_once_with(8642)
        again = self.refused(409, self.post)
        self.assertEqual(again.message, "Deck Lab is already restarting.")
        self.assertEqual(self.launch.call_count, 1)

    def test_uncommitted_or_unknown_code_is_refused(self):
        for found, words in (({**CLEAN, "latest_dirty": True}, "aren't committed"),
                             ({**CLEAN, "latest_dirty": None}, "couldn't check"),
                             ({**CLEAN, "error": "Git is unavailable"}, "couldn't check")):
            with self.subTest(found=found):
                self.build.return_value = found
                self.assertIn(words, self.refused(409, self.post).message)
                self.assertFalse(server_restart.view()["may_restart"])
        self.launch.assert_not_called()

    def test_only_the_background_server_on_its_usual_port(self):
        for found in (None, {"pid": os.getpid() + 1, "port": 8642, "background": True},
                      {"pid": os.getpid(), "port": 8642, "background": False},
                      {"pid": os.getpid(), "port": 8643, "background": True}):
            with self.subTest(found=found):
                self.state.return_value = found
                self.assertIn("wasn't started in the background", self.refused(409, self.post).message)
        self.launch.assert_not_called()

    def test_nothing_to_start_it_again_is_refused(self):
        self.supervisor.return_value = "Deck Lab isn't set up to start in the background, so it can't be restarted from here."
        self.assertIn("isn't set up", self.refused(409, self.post).message)
        self.launch.assert_not_called()

    def test_busy_needs_anyway(self):
        self.busy.return_value = ["2 Forge matchups playing or waiting"]
        refused = self.refused(409, self.post)
        self.assertEqual(refused.extra, {"busy": ["2 Forge matchups playing or waiting"]})
        self.launch.assert_not_called()
        self.assertTrue(self.post(anyway=True)["restarting"])

    def test_bad_bodies(self):
        self.refused(400, server_restart.restart, json.dumps({"profile": "matt", "anyway": "yes"}).encode())
        self.refused(400, server_restart.restart, json.dumps({"profile": "matt", "migrate": True}).encode())
        self.refused(403, server_restart.restart, json.dumps({"profile": "user1"}).encode())
        self.refused(413, server_restart.restart, b"{" + b" " * server_restart.MAX_BODY + b"}")
        self.launch.assert_not_called()

    def test_a_helper_that_gives_up_at_once_is_reported_and_may_be_tried_again(self):
        self.launch.return_value = _Proc(1)
        self.assertIn("restart.log", self.refused(500, self.post).message)
        self.launch.return_value = _Proc()
        self.assertTrue(self.post()["restarting"])

    def test_launch_failure(self):
        self.launch.side_effect = OSError("no")
        self.assertEqual(self.refused(500, self.post).message, "Deck Lab couldn't start its restart. Restart it on the PC.")


class HelperCommandTests(unittest.TestCase):
    def test_windows_runs_homenet_restart_with_the_port(self):
        with mock.patch.object(sys, "platform", "win32"):
            self.assertEqual(server_restart._command(8642)[1:],
                             ["-m", "decklab.lib.homenet", "restart", "--port", "8642", "--after", "3"])

    def test_linux_runs_it_in_a_unit_of_its_own(self):
        with mock.patch.object(sys, "platform", "linux"):
            command = server_restart._command(8642)
        self.assertEqual(command[:4], ["systemd-run", "--user", "--collect", "--quiet"])
        self.assertIn(f"--property=StandardOutput=append:{server_restart.LOG_FILE}", command)
        self.assertEqual(command[-7:], ["-m", "decklab.lib.homenet", "restart", "--port", "8642", "--after", "3"])

    def test_busy_counts_running_jobs(self):
        from decklab.lib.api import forge_runs, practice
        with mock.patch.object(forge_runs.FORGE_JOBS, "active", return_value=[1, 2]), \
                mock.patch.object(forge_runs.COORD_JOBS, "active", return_value=[]), \
                mock.patch.object(practice.JOBS, "active", return_value=[1]):
            self.assertEqual(server_restart._busy(), ["2 Forge matchups playing or waiting", "1 practice-hand run"])


if __name__ == "__main__":
    unittest.main()
