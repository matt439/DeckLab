"""Process ownership contracts without native child processes or real simulators."""
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.lib.crosscheck import processes


class CrosscheckProcessTests(unittest.TestCase):
    def setUp(self):
        self.process = mock.Mock(pid=1234)
        self.process.poll.return_value = None
        self.process.wait.return_value = 0
        self.kernel = mock.Mock()
        self.kernel.OpenProcess.return_value = 12
        self.kernel.AssignProcessToJobObject.return_value = True
        self.native = mock.Mock()
        self.native.NtResumeProcess.return_value = 0
        self.forge = SimpleNamespace(_k32=self.kernel, _ntdll=self.native, _new_job=mock.Mock(return_value=11),
                                     _SPAWN_FLAGS=32, _SUSPENDED=4, PROCESS_SET_QUOTA=1,
                                     PROCESS_TERMINATE=2, PROCESS_SUSPEND_RESUME=8,
                                     _niced=lambda args: ["nice", "-n", "10", *args],
                                     start_process=mock.Mock())
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(processes.signal, "SIGKILL", 9, create=True).start()
        mock.patch.object(processes, "_forge_processes", return_value=self.forge).start()
        self.popen = mock.patch.object(processes.subprocess, "Popen", return_value=self.process).start()
        self.finalize = mock.patch.object(processes.weakref, "finalize").start()
        self.output, self.error = object(), object()

    def spawn(self):
        return processes.spawn(["worker", "argument"], cwd="isolated", env={"FIXTURE": "1"},
                               stdout=self.output, stderr=self.error)

    def test_windows_assigns_ownership_before_resuming_with_separate_channels(self):
        mock.patch.object(processes, "_windows", return_value=True).start()
        events = []
        self.kernel.AssignProcessToJobObject.side_effect = lambda *args: events.append("assign") or True
        self.native.NtResumeProcess.side_effect = lambda *args: events.append("resume") or 0
        self.assertIs(self.spawn(), self.process)
        self.assertEqual(events, ["assign", "resume"])
        options = self.popen.call_args.kwargs
        self.assertEqual(options["creationflags"], 36)
        self.assertIs(options["stdout"], self.output)
        self.assertIs(options["stderr"], self.error)
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertEqual(self.process._crosscheck_job, [11])
        self.kernel.CloseHandle.assert_called_once_with(12)

    def test_windows_ownership_failure_never_resumes_and_closes_every_handle(self):
        mock.patch.object(processes, "_windows", return_value=True).start()
        self.kernel.AssignProcessToJobObject.return_value = False
        with self.assertRaises(OSError):
            self.spawn()
        self.native.NtResumeProcess.assert_not_called()
        self.process.kill.assert_called_once()
        self.kernel.TerminateJobObject.assert_called_once_with(11, 1)
        self.assertCountEqual([c.args[0] for c in self.kernel.CloseHandle.call_args_list], [11, 12])

    def test_windows_resume_failure_terminates_the_owned_job(self):
        mock.patch.object(processes, "_windows", return_value=True).start()
        self.native.NtResumeProcess.return_value = 1
        with self.assertRaises(OSError):
            self.spawn()
        self.kernel.TerminateJobObject.assert_called_once_with(11, 1)
        self.assertEqual(self.process._crosscheck_job, [])

    def test_windows_spawn_failure_closes_created_job(self):
        mock.patch.object(processes, "_windows", return_value=True).start()
        self.popen.side_effect = OSError("fixture spawn failure")
        with self.assertRaises(OSError):
            self.spawn()
        self.kernel.CloseHandle.assert_called_once_with(11)

    def test_windows_job_creation_failure_starts_nothing(self):
        mock.patch.object(processes, "_windows", return_value=True).start()
        self.forge._new_job.side_effect = OSError("fixture job failure")
        with self.assertRaises(OSError):
            self.spawn()
        self.popen.assert_not_called()

    def test_windows_terminate_owns_descendants_after_parent_already_exited(self):
        mock.patch.object(processes, "_windows", return_value=True).start()
        self.process.poll.return_value = 0
        self.process._crosscheck_job = [11]
        processes.terminate(self.process)
        self.kernel.TerminateJobObject.assert_called_once_with(11, 1)
        self.kernel.CloseHandle.assert_called_once_with(11)
        self.assertEqual(self.process._crosscheck_job, [])
        self.process.kill.assert_not_called()

    def test_job_handle_always_closes_when_wait_fails(self):
        mock.patch.object(processes, "_windows", return_value=True).start()
        self.process._crosscheck_job = [11]
        self.process.wait.side_effect = OSError("fixture wait failure")
        with self.assertRaises(OSError):
            processes.terminate(self.process)
        self.kernel.CloseHandle.assert_called_once_with(11)

    def test_posix_starts_a_niced_private_session(self):
        mock.patch.object(processes, "_windows", return_value=False).start()
        self.assertIs(self.spawn(), self.process)
        self.assertEqual(self.popen.call_args.args[0], ["nice", "-n", "10", "worker", "argument"])
        self.assertTrue(self.popen.call_args.kwargs["start_new_session"])

    def test_posix_kills_group_even_when_its_leader_has_exited(self):
        mock.patch.object(processes, "_windows", return_value=False).start()
        self.process.poll.return_value = 0
        self.process._crosscheck_job = None
        with mock.patch.object(processes.os, "killpg", create=True) as kill:
            processes.terminate(self.process)
        kill.assert_called_once_with(1234, processes.signal.SIGKILL)

    def test_posix_missing_group_is_already_stopped(self):
        mock.patch.object(processes, "_windows", return_value=False).start()
        self.process.poll.return_value = 0
        self.process._crosscheck_job = None
        with mock.patch.object(processes.os, "killpg", side_effect=ProcessLookupError, create=True):
            processes.terminate(self.process)
        self.process.wait.assert_called_once()

    def test_posix_forge_child_inherits_outer_group_and_launcher_is_restored(self):
        mock.patch.object(processes, "_windows", return_value=False).start()
        original = self.forge.start_process
        with mock.patch.object(processes.os, "getpid", return_value=1234), \
                mock.patch.object(processes.os, "getpgrp", return_value=1234, create=True), \
                mock.patch.object(processes.os, "getsid", return_value=1234, create=True):
            with processes.install_inherited_group_launch():
                self.forge.start_process(["java"], cwd="fixture", stdin=True)
                self.assertNotIn("start_new_session", self.popen.call_args.kwargs)
                self.assertEqual(self.popen.call_args.kwargs["stdin"], subprocess.PIPE)
            self.assertIs(self.forge.start_process, original)

    def test_posix_inheritance_refuses_a_shared_process_group(self):
        mock.patch.object(processes, "_windows", return_value=False).start()
        with mock.patch.object(processes.os, "getpid", return_value=1234), \
                mock.patch.object(processes.os, "getpgrp", return_value=1, create=True), \
                mock.patch.object(processes.os, "getsid", return_value=1, create=True):
            with self.assertRaises(RuntimeError):
                with processes.install_inherited_group_launch():
                    self.fail("must refuse before entering")

    def test_merged_or_inherited_output_channels_are_refused(self):
        for output, error in ((None, self.error), (self.output, None), (self.output, self.output),
                              (self.output, subprocess.STDOUT), (subprocess.PIPE, self.error)):
            with self.subTest(output=output, error=error):
                with self.assertRaises(ValueError):
                    processes.spawn(["worker"], cwd="isolated", env={}, stdout=output, stderr=error)
        self.popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
