"""Removal deployment checks are read-only and fail closed, with no real probes."""
import os
import unittest
from unittest import mock

from decklab.db import space_runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        # No root resolution, filesystem claims, process inventory or HTTP request.
        self.current = {"version": 1, "root": "fixture-root"}
        self.status = {"forge_lifecycle": dict(self.current, pid=50001),
                       "build": {"running_dirty": False, "latest_dirty": False, "restart_required": False}}
        patch = mock.patch("decklab.lib.forge.lifecycle.capability", return_value=self.current)
        patch.start()
        self.addCleanup(patch.stop)

    def checked(self, status, processes):
        with mock.patch.object(space_runtime, "_status", return_value=status), \
                mock.patch.object(space_runtime, "_processes", return_value=processes):
            return space_runtime.require_ready("unused-fixture")

    def test_stopped_or_cooperative_clean_server_allows_only_known_interpreters(self):
        self.assertEqual(self.checked(None, {os.getpid(): 40001}), self.current)
        self.assertEqual(self.checked(self.status, {os.getpid(): 1, 50001: 1}), self.current)

    def test_an_ancestor_interpreter_is_not_assumed_to_be_a_harmless_launcher(self):
        for processes in ({os.getpid(): 40001, 40001: 1}, {os.getpid(): 1, 50001: 50002, 50002: 1}):
            with self.subTest(processes=processes), self.assertRaisesRegex(ValueError, "Other Python"):
                self.checked(self.status, processes)

    def test_legacy_wrong_root_missing_pid_dirty_or_unknown_build_refuses(self):
        cases = [{}, {"forge_lifecycle": self.current}, dict(self.status, forge_lifecycle={
            **self.status["forge_lifecycle"], "root": "other-root"}), dict(self.status, forge_lifecycle={
            **self.status["forge_lifecycle"], "version": True})]
        for key in ("running_dirty", "latest_dirty", "restart_required"):
            for value in (True, None, 0):
                cases.append(dict(self.status, build={**self.status["build"], key: value}))
        for status in cases:
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.checked(status, {os.getpid(): 1})

    def test_unknown_coordinator_or_unreadable_process_inventory_refuses(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.checked(None, {})
        with self.assertRaisesRegex(ValueError, "Other Python"):
            self.checked(self.status, {os.getpid(): 1, 50001: 1, 60001: 1})
        with mock.patch.object(space_runtime, "_status", return_value=None), \
                mock.patch.object(space_runtime, "_processes", side_effect=ValueError("unreadable")), \
                self.assertRaisesRegex(ValueError, "unreadable"):
            space_runtime.require_ready()

    def test_only_refused_connection_counts_as_stopped_and_no_redirect_is_followed(self):
        for error in (TimeoutError(), PermissionError()):
            with mock.patch.object(space_runtime.config, "load", return_value={"port": 12345}), \
                    mock.patch.object(space_runtime.http.client, "HTTPConnection") as connection:
                connection.return_value.request.side_effect = error
                with self.assertRaisesRegex(ValueError, "cannot be verified"):
                    space_runtime._status()
        with mock.patch.object(space_runtime.config, "load", return_value={"port": 12345}), \
                mock.patch.object(space_runtime.http.client, "HTTPConnection") as connection:
            connection.return_value.request.side_effect = ConnectionRefusedError()
            self.assertIsNone(space_runtime._status())
            connection.return_value.close.assert_called_once()
        with mock.patch.object(space_runtime.config, "load", return_value={"port": 12345}), \
                mock.patch.object(space_runtime.http.client, "HTTPConnection") as connection:
            connection.return_value.getresponse.return_value.status = 302
            connection.return_value.getresponse.return_value.read.return_value = b"{}"
            with self.assertRaisesRegex(ValueError, "cannot be verified"):
                space_runtime._status()


from decklab.tests.test_server import ServerTestCase  # noqa: E402


class RuntimeCapabilityHttpTests(ServerTestCase):
    def test_only_loopback_scripts_receive_managed_paths_and_capability(self):
        capability = {"version": 1, "root": "private-managed-root", "pid": 50001}
        with mock.patch.object(space_runtime, "capability", return_value=capability) as read:
            code, _, body = self.request("GET", "/api/status")
            self.assertEqual(code, 200)
            self.assertEqual(space_runtime.json.loads(body)["forge_lifecycle"], capability)
            read.assert_called_once_with()
        for headers in ({}, {"X-Deck-Lab-Viewer": "matt"}, {"X-Deck-Lab-Viewer": "user1"}):
            with self.subTest(headers=headers), mock.patch.object(space_runtime, "capability") as read:
                code, _, body = self.request("GET", "/api/status", headers=headers, script=False)
                self.assertEqual(code, 200)
                self.assertNotIn("forge_lifecycle", space_runtime.json.loads(body))
                self.assertNotIn(b"private-managed-root", body)
                read.assert_not_called()
