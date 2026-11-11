"""macOS foreground contracts are emulated; no launchd/service/real backup is run."""
from contextlib import nullcontext, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from decklab import smoke, update
from decklab.db import backup, nightly, schedule
from decklab.db.__main__ import _schedule
from decklab.lib import keepawake
from decklab.lib import preflight
from decklab.tests.test_doctor import Codes
from decklab.lib.forge import install
from decklab.lib.homenet import commands, darwin
from decklab.tests import db_support


class ForegroundContracts(unittest.TestCase):
    def test_homenet_never_calls_windows_or_linux_management(self):
        for name in ("start", "stop", "restart", "install", "remove", "ensure", "status"):
            with self.subTest(name=name), mock.patch.object(commands, "sys", SimpleNamespace(platform="darwin")), \
                    mock.patch.object(commands.config, "load", return_value={}), \
                    mock.patch.object(commands, "say") as say, \
                    mock.patch.object(commands, "uses_systemd", side_effect=AssertionError("no systemd")), \
                    mock.patch.object(commands, "cmd_status", side_effect=AssertionError("no Windows status")):
                self.assertEqual(commands.main([name]), 0 if name == "status" else 1)
                message = " ".join(call.args[0] for call in say.call_args_list)
                self.assertIn("macOS", message)
                self.assertNotIn("schtasks", message)
                self.assertNotIn("systemctl", message)

    def test_schedule_status_is_explicitly_unsupported_and_nonzero(self):
        with mock.patch.object(schedule, "sys", SimpleNamespace(platform="darwin")), \
                mock.patch.object(schedule, "_systemd", return_value=SimpleNamespace(supported=lambda: False)), \
                mock.patch.object(schedule, "query_task", side_effect=AssertionError("no native task")), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(_schedule(SimpleNamespace(action="status")), 2)
        self.assertIn("unsupported", output.getvalue())
        self.assertNotIn("is installed", output.getvalue())

    def test_updater_explains_manual_work_before_fetch_or_restart(self):
        with mock.patch.object(update, "sys", SimpleNamespace(platform="darwin")), \
                mock.patch.object(update, "say") as say, mock.patch.object(update, "before_pull") as pull, \
                mock.patch.object(update, "after_pull") as after:
            self.assertEqual(update.main([]), 1)
            self.assertEqual(update.main(["--after-pull", "a" * 40]), 1)
        pull.assert_not_called()
        after.assert_not_called()
        self.assertIn("Nothing was fetched", say.call_args.args[0])

    def test_smoke_does_not_claim_a_scheduler_from_successful_informational_text(self):
        notes = []
        with mock.patch.object(smoke, "sys", SimpleNamespace(platform="darwin")), \
                mock.patch.object(smoke, "_run", side_effect=AssertionError("no native commands")):
            smoke.step_services(SimpleNamespace(note=lambda *row: notes.append(row)), {"doctor": {}})
        self.assertTrue(notes)
        self.assertTrue(all(level == smoke.WARN for level, _ in notes))
        self.assertTrue(any("no macOS scheduler is installed by Deck Lab" in text for _, text in notes))

    def test_only_recent_successful_whole_nightly_is_positive_evidence(self):
        now = datetime(2026, 11, 11, tzinfo=timezone.utc)
        self.assertEqual(smoke.nightly_receipt_finding(None, now)[0], smoke.WARN)
        for elapsed, ok, wanted in ((1, True, smoke.PASS), (40, True, smoke.WARN),
                                     (1, False, smoke.WARN), (-1, True, smoke.WARN)):
            with self.subTest(elapsed=elapsed, ok=ok):
                result = smoke.nightly_receipt_finding({"ok": ok, "finished_at": now - timedelta(hours=elapsed)}, now)
                self.assertEqual(result[0], wanted)
                if wanted == smoke.PASS:
                    self.assertIn("operator-managed", result[1])

    def test_macos_database_guidance_does_not_offer_linux_or_windows_commands(self):
        result = preflight.report(Codes({"database": "database_no_answer"}), platform_name=lambda: "darwin")
        text = preflight.text(result)
        self.assertIn("brew services", text)
        self.assertNotIn("systemctl", text)
        self.assertNotIn("Get-Service", text)

    def test_nightly_receipt_is_whole_job_metadata_not_a_backup_execution(self):
        for result in (0, 1):
            with self.subTest(result=result), mock.patch.object(nightly, "sys", SimpleNamespace(platform="darwin")), \
                    mock.patch.object(keepawake, "hold_while", return_value=nullcontext()), \
                    mock.patch.object(nightly, "_run", return_value=result) as steps, \
                    mock.patch.object(backup, "record") as record:
                self.assertEqual(nightly.run(), result)
            steps.assert_called_once_with()
            self.assertEqual(record.call_args.args[0], "nightly")
            self.assertIs(record.call_args.args[2], result == 0)
        with mock.patch.object(nightly.db, "log") as log, \
                mock.patch.object(backup, "record", side_effect=RuntimeError("old migration")):
            nightly._receipt(datetime.now(timezone.utc), True)
        self.assertIn("0023", log.call_args.args[0])

    def test_macos_jdk_layouts_are_discovered_without_running_a_program(self):
        roots = {(path.as_posix(), pattern) for path, pattern in install._posix_java_roots()}
        self.assertIn(("/Library/Java/JavaVirtualMachines", "*/Contents/Home"), roots)
        self.assertIn(("/opt/homebrew/opt", "openjdk*/libexec/openjdk.jdk/Contents/Home"), roots)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "temurin-21.jdk" / "Contents" / "Home"
            (home / "bin").mkdir(parents=True)
            (home / "bin" / "java").write_text("not executed", encoding="utf-8")
            (home / "bin" / "javac").write_text("not executed", encoding="utf-8")
            (home / "release").write_text('JAVA_VERSION="21.0.1"\n', encoding="utf-8")
            with mock.patch.object(install, "_windows", return_value=False), \
                    mock.patch.object(install, "_posix_java_roots", return_value=((root, "*/Contents/Home"),)), \
                    mock.patch.object(install.shutil, "which", return_value=None), \
                    mock.patch.dict(os.environ, JAVA_HOME=""):
                self.assertEqual(install.find_java(), home / "bin" / "java")


@unittest.skipUnless(os.name == "posix" and shutil.which("sh"), "needs a POSIX shell")
class ForegroundLauncher(unittest.TestCase):
    def test_darwin_launcher_runs_the_server_in_foreground(self):
        source = Path(__file__).resolve().parents[2] / "scripts" / "decklab"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "scripts").mkdir()
            (root / "bin").mkdir()
            script = root / "scripts" / "decklab"
            script.write_bytes(source.read_bytes())
            program = root / "bin" / "fake-python"
            program.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE"\n', encoding="utf-8")
            program.chmod(0o700)
            uname = root / "bin" / "uname"
            uname.write_text('#!/bin/sh\nprintf "Darwin\\n"\n', encoding="utf-8")
            uname.chmod(0o700)
            capture = root / "args"
            env = dict(os.environ, DECKLAB_PYTHON=str(program), CAPTURE=str(capture),
                       PATH=str(root / "bin") + os.pathsep + os.environ["PATH"])
            subprocess.run([shutil.which("sh"), str(script), "start", "--port", "12345"],
                           env=env, check=True, capture_output=True)
            self.assertEqual(capture.read_text().splitlines(), ["decklab/server.py", "--port", "12345"])


class WholeNightlyDatabase(db_support.DbTestCase):
    def test_current_schema_accepts_and_reads_a_whole_run_receipt(self):
        started = datetime.now(timezone.utc)
        backup.record("nightly", started, True, detail="Synthetic whole-run proof", dbname=self.dbname)
        found = backup.latest(("nightly",), dbname=self.dbname)["nightly"]
        self.assertTrue(found["ok"])
        self.assertEqual(smoke.nightly_receipt_finding(found)[0], smoke.PASS)
