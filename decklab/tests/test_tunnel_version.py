"""E11-S88: cloudflared's installed version and its age against Cloudflare's support window
(decklab/lib/tunnel.py's parse_version, cloudflared_version, judge_version, upgrade_hint and
version_check), and the Tunnel line homenet status shows for it. Nothing here runs cloudflared:
each answer is a canned Windows or Linux output.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_tunnel_version
"""
import subprocess
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from decklab.lib import tunnel
from decklab.lib.homenet import OK, WARN
from decklab.lib.homenet.commands import check_tunnel

WINDOWS_OUT = "cloudflared.exe version 2025.8.1 (built 2025-08-21-1528 UTC)\r\n"
LINUX_OUT = "cloudflared version 2024.6.1 (built 2024-06-12-1340 UTC)\n"
SETTINGS = {"tunnel": {"config": "~/.cloudflared/config.yml", "hostname": "decklab.example.com"},
            "access": {"team": "your-team", "aud": "ab" * 32, "port": 8644}}


def runner(stdout="", stderr="", code=0, raises=None):
    """A stand-in for subprocess.run, recording its argv."""
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if raises is not None:
            raise raises
        return types.SimpleNamespace(stdout=stdout, stderr=stderr, returncode=code)
    run.calls = calls
    return run


class ParseTests(unittest.TestCase):
    def test_windows_and_linux_outputs(self):
        self.assertEqual(tunnel.parse_version(WINDOWS_OUT),
                         {"version": "2025.8.1", "released": date(2025, 8, 1), "built": "2025-08-21"})
        self.assertEqual(tunnel.parse_version(LINUX_OUT),
                         {"version": "2024.6.1", "released": date(2024, 6, 1), "built": "2024-06-12"})

    def test_without_a_build_date_and_with_leading_zeroes(self):
        self.assertEqual(tunnel.parse_version("cloudflared version 2023.02.2\n"),
                         {"version": "2023.2.2", "released": date(2023, 2, 1), "built": None})

    def test_unreadable_outputs(self):
        for text in ("", None, "cloudflared version DEV (built unknown)", "command not found",
                     "cloudflared version 2025.13.0", "version 2025.8.1"):
            with self.subTest(text=text):
                self.assertIsNone(tunnel.parse_version(text))


class AskTests(unittest.TestCase):
    def test_asks_with_version_and_a_timeout(self):
        run = runner(WINDOWS_OUT)
        kind, found = tunnel.cloudflared_version(Path("cloudflared.exe"), run)
        self.assertEqual((kind, found["version"]), ("ok", "2025.8.1"))
        argv, kwargs = run.calls[0]
        self.assertEqual(argv, ["cloudflared.exe", "--version"])
        self.assertEqual(kwargs["timeout"], tunnel.VERSION_TIMEOUT)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)

    def test_the_answer_may_come_on_stderr(self):
        self.assertEqual(tunnel.cloudflared_version("c", runner(stderr=LINUX_OUT))[0], "ok")

    def test_timeout_failure_and_unreadable_answers_are_unknown(self):
        cases = ((runner(raises=subprocess.TimeoutExpired("c", 10)), "didn't answer within 10 seconds"),
                 (runner(raises=FileNotFoundError("gone")), "couldn't be run"),
                 (runner("garbage"), "couldn't be read"),
                 (runner("", "boom", 3), "exited with code 3"))
        for run, words in cases:
            with self.subTest(words=words):
                kind, why = tunnel.cloudflared_version("c", run)
                self.assertEqual(kind, "unknown")
                self.assertIn(words, why)


class JudgeTests(unittest.TestCase):
    def found(self, text):
        return "ok", tunnel.parse_version(text)

    def test_inside_the_window_is_current(self):
        judged = tunnel.judge_version(self.found(WINDOWS_OUT), date(2026, 7, 1), "C:/cf/cloudflared.exe", "win32")
        self.assertEqual(judged["state"], "current")
        self.assertEqual(judged["version"], "2025.8.1")
        self.assertIsNone(judged["fix"])
        self.assertEqual(judged["text"], "cloudflared 2025.8.1 (at C:/cf/cloudflared.exe; built 2025-08-21), "
                                         "within Cloudflare's 365-day support.")

    def test_the_limit_is_support_days_after_the_versions_month(self):
        start = date(2025, 8, 1)
        last = date.fromordinal(start.toordinal() + tunnel.SUPPORT_DAYS)
        self.assertEqual(tunnel.judge_version(self.found(WINDOWS_OUT), last)["state"], "current")
        later = date.fromordinal(last.toordinal() + 1)
        judged = tunnel.judge_version(self.found(WINDOWS_OUT), later, None, "win32")
        self.assertEqual(judged["state"], "old")
        self.assertEqual(judged["age_days"], tunnel.SUPPORT_DAYS + 1)
        self.assertIn("is from August 2025", judged["text"])
        self.assertIn("never updates itself", judged["text"])
        self.assertIn("winget upgrade Cloudflare.cloudflared", judged["fix"])

    def test_a_wrong_clock_is_current(self):
        judged = tunnel.judge_version(self.found(WINDOWS_OUT), date(2020, 1, 1))
        self.assertEqual((judged["state"], judged["age_days"]), ("current", 0))

    def test_unknown_says_why(self):
        judged = tunnel.judge_version(("unknown", "it didn't answer within 10 seconds"), date(2026, 11, 12), "cf")
        self.assertEqual(judged["state"], "unknown")
        self.assertEqual(judged["text"], "cloudflared's version is unknown (at cf): it didn't answer within 10 "
                                         "seconds.")
        self.assertIsNone(judged["fix"])

    def test_upgrade_commands_follow_the_platform_and_install(self):
        cases = (("C:/Program Files/cloudflared/cloudflared.exe", "win32", "winget upgrade Cloudflare.cloudflared"),
                 ("/usr/bin/cloudflared", "linux", "apt-get install --only-upgrade cloudflared"),
                 ("/snap/bin/cloudflared", "linux", "sudo snap refresh cloudflared"),
                 ("/opt/cloudflared/cloudflared", "linux", "replace /opt/cloudflared/cloudflared with the newest"),
                 ("/opt/homebrew/bin/cloudflared", "darwin", "brew upgrade cloudflared"))
        for path, platform, words in cases:
            with self.subTest(platform=platform, path=path):
                hint = tunnel.upgrade_hint(path, platform)
                self.assertIn(words, hint)
                self.assertTrue(hint.endswith("then python -m decklab.lib.homenet restart."))


class VersionCheckTests(unittest.TestCase):
    def test_nothing_without_a_tunnel_or_cloudflared(self):
        run = runner(WINDOWS_OUT)
        self.assertIsNone(tunnel.version_check({}, date(2026, 1, 1), run))
        with mock.patch.object(tunnel, "find_cloudflared", return_value=None):
            self.assertIsNone(tunnel.version_check(SETTINGS, date(2026, 1, 1), run))
        self.assertEqual(run.calls, [])

    def test_asks_the_configured_program(self):
        with tempfile.TemporaryDirectory() as folder:
            program = Path(folder) / "cloudflared"
            program.write_text("", encoding="utf-8")
            run = runner(LINUX_OUT)
            judged = tunnel.version_check({**SETTINGS, "cloudflared": str(program)}, date(2026, 11, 12), run,
                                          "linux")
        self.assertEqual(run.calls[0][0], [str(program), "--version"])
        self.assertEqual(judged["state"], "old")
        self.assertIn("replace", judged["fix"])


class StatusLineTests(unittest.TestCase):
    def test_no_line_without_a_tunnel_or_an_answer(self):
        self.assertEqual(check_tunnel({}, None, version={"state": "old", "text": "x", "fix": "y"}), [])
        texts = [l["text"] for l in check_tunnel(SETTINGS, ("login", "x"), [])]
        self.assertFalse([t for t in texts if t.startswith("cloudflared")], texts)

    def test_current_old_and_unknown(self):
        today = date(2026, 7, 1)
        current = tunnel.judge_version(("ok", tunnel.parse_version(WINDOWS_OUT)), today, "cf", "win32")
        old = tunnel.judge_version(("ok", tunnel.parse_version(LINUX_OUT)), today, "/usr/bin/cloudflared", "linux")
        unknown = tunnel.judge_version(("unknown", "its answer couldn't be read"), today, "cf")
        for judged, level, fix in ((current, OK, None), (old, WARN, old["fix"]), (unknown, WARN, None)):
            with self.subTest(state=judged["state"]):
                first = check_tunnel(SETTINGS, ("login", "x"), [], None, None, judged)[0]
                self.assertEqual((first["level"], first["area"], first["text"], first["fix"]),
                                 (level, "Tunnel", judged["text"], fix))
        self.assertIn("apt-get install --only-upgrade cloudflared", old["fix"])
        self.assertIn("unknown", unknown["text"])


if __name__ == "__main__":
    unittest.main()
