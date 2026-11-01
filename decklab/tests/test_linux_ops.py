"""Server-PC operations on Linux (and Windows alike): the household's time zone (lib/hometime.py,
the nightly timer's OnCalendar, the doctor's and smoke test's checks), keep-awake's capability
trial, the smoke test's wording and backup_dir check, update's interpreter check and its
psycopg stop, the POSIX launcher, and space_runtime's own-user process scan. Every tool,
clock and file is injected, so these run on any OS with nothing installed."""
import os
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from decklab import smoke, update
from decklab.db import schedule, space_runtime, systemd_units
from decklab.lib import hometime, keepawake, preflight
from decklab.lib.preflight_local import Local

REPO = Path(__file__).resolve().parents[2]
PLUS_11 = timezone(timedelta(hours=11))


def _localtime(offset):
    """A time.localtime stand-in whose tm_gmtoff is offset seconds."""
    return lambda moment=None: types.SimpleNamespace(tm_gmtoff=offset)


class HomeTimeTests(unittest.TestCase):
    def test_zone_names(self):
        for name in ("UTC", "Australia/Sydney", "America/Argentina/Salta", "Etc/GMT+10"):
            self.assertTrue(hometime.valid_name(name), name)
        for name in ("", "Australia/Sydney extra", "/etc/localtime", "../x", "A%b", 'A"b', None, 10, "x" * 65):
            self.assertFalse(hometime.valid_name(name), name)

    def test_setting(self):
        self.assertEqual(hometime.setting({}), (None, None))
        self.assertEqual(hometime.setting({"timezone": ""}), (None, None))
        self.assertEqual(hometime.setting({"timezone": "Australia/Sydney"}), ("Australia/Sydney", None))
        name, problem = hometime.setting({"timezone": "Sydney time"})
        self.assertIsNone(name)
        self.assertIn("Australia/Sydney", problem)
        self.assertIsNone(hometime.configured({"timezone": 5}))

    def test_household_today_falls_back_to_utc_plus_10(self):
        late = datetime(2026, 10, 31, 14, 30, tzinfo=timezone.utc)      # 00:30 on Nov 1 at UTC+10
        self.assertEqual(hometime.household_today({}, now=late), "2026-11-01")
        with mock.patch.object(hometime, "zone", return_value=None):
            self.assertEqual(hometime.household_today({"timezone": "Nowhere/Here"}, now=late), "2026-11-01")
        early = datetime(2026, 10, 31, 13, 30, tzinfo=timezone.utc)     # 23:30 at UTC+10
        self.assertEqual(hometime.household_today({}, now=early), "2026-10-31")

    def test_household_today_uses_the_configured_zone(self):
        at = datetime(2026, 10, 31, 13, 30, tzinfo=timezone.utc)        # 23:30 at +10, 00:30 at +11
        with mock.patch.object(hometime, "zone", return_value=PLUS_11):
            self.assertEqual(hometime.household_today({"timezone": "Australia/Sydney"}, now=at), "2026-11-01")

    def test_household_today_never_raises(self):
        with mock.patch.object(hometime, "configured", side_effect=RuntimeError("broken")):
            self.assertRegex(hometime.household_today({}), r"^\d{4}-\d{2}-\d{2}$")

    def test_host_mismatch(self):
        with mock.patch.object(hometime, "zone", return_value=PLUS_11):
            self.assertIsNone(hometime.host_mismatch("Australia/Sydney", now=0, localtime=_localtime(11 * 3600)))
            why = hometime.host_mismatch("Australia/Sydney", now=0, localtime=_localtime(0), platform="linux")
            self.assertIn("UTC+00:00", why)
            self.assertIn("UTC+11:00", why)
            self.assertIn("sudo timedatectl set-timezone Australia/Sydney", why)
            why = hometime.host_mismatch("Australia/Sydney", now=0, localtime=_localtime(0), platform="win32")
            self.assertIn("Time & language", why)
        with mock.patch.object(hometime, "zone", return_value=None), self.assertRaises(LookupError):
            hometime.host_mismatch("Australia/Sydney")

    def test_host_mismatch_checks_half_a_year_on(self):
        # The same offset now, another one in half a year (another daylight saving rule).
        seen = []

        def localtime(moment):
            seen.append(moment)
            return types.SimpleNamespace(tm_gmtoff=11 * 3600 if moment == 0 else 10 * 3600)
        with mock.patch.object(hometime, "zone", return_value=PLUS_11):
            self.assertIn("UTC+10:00", hometime.host_mismatch("Australia/Sydney", now=0, localtime=localtime))
        self.assertEqual(seen, [0, hometime.HALF_YEAR])

    @unittest.skipUnless(hometime.zone("UTC") is not None, "this Python has no time zone data (Windows without tzdata)")
    def test_real_zone_data(self):
        self.assertIsNone(hometime.host_mismatch("UTC", localtime=_localtime(0)))
        self.assertIsNotNone(hometime.host_mismatch("UTC", localtime=_localtime(3600)))


class DatesTests(unittest.TestCase):
    def test_household_dates_use_hometime(self):
        from decklab.db import inv_receive
        from decklab.lib.api import play_records, receipts
        with mock.patch.object(hometime, "household_today", return_value="2026-11-01") as today:
            self.assertEqual(inv_receive._today(), "2026-11-01")
            self.assertEqual(play_records._play_today(), "2026-11-01")
            self.assertEqual(receipts._receipt_today(), "2026-11-01")
        self.assertEqual(today.call_count, 3)


class NightlyZoneTests(unittest.TestCase):
    def test_on_calendar_takes_the_zone(self):
        units = systemd_units.nightly_units("/usr/bin/python3.14", "/home/a/DeckLab", "03:30", "Australia/Sydney")
        self.assertIn("OnCalendar=*-*-* 03:30:00 Australia/Sydney\n", units[systemd_units.TIMER])
        for zone in (None, ""):
            units = systemd_units.nightly_units("/usr/bin/python3.14", "/home/a/DeckLab", "03:30", zone)
            self.assertIn("OnCalendar=*-*-* 03:30:00\n", units[systemd_units.TIMER])
        for bad in ("Sydney time", "A%b", "x\ny"):
            with self.assertRaises(ValueError):
                systemd_units.nightly_units("/usr/bin/python3.14", "/home/a/DeckLab", "03:30", bad)

    def test_install_writes_the_configured_zone(self):
        with mock.patch("decklab.lib.config.load", return_value={"timezone": "Australia/Perth"}), \
                mock.patch.object(schedule.sys, "executable", "/usr/bin/python3.14"), \
                mock.patch.object(schedule.config, "REPO", Path("/home/a/DeckLab")):
            units = schedule._units()
            self.assertIn("03:30:00 Australia/Perth\n", units[systemd_units.TIMER])
            self.assertEqual(schedule._at_text(schedule._zone()), "03:30 Australia/Perth time")
        with mock.patch("decklab.lib.config.load", return_value={"timezone": "not a zone"}), \
                mock.patch.object(schedule.sys, "executable", "/usr/bin/python3.14"), \
                mock.patch.object(schedule.config, "REPO", Path("/home/a/DeckLab")):
            self.assertIn("OnCalendar=*-*-* 03:30:00\n", schedule._units()[systemd_units.TIMER])

    def test_preview_reads_no_config(self):
        said = []
        with mock.patch("decklab.lib.config.load", side_effect=AssertionError("read")):
            schedule.preview_systemd("timer", "/usr/bin/python3.14", "/srv/decklab", say=said.append,
                                     zone="Australia/Sydney")
        self.assertIn("03:30:00 Australia/Sydney", said[0])

    def run_cli(self, args):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from decklab.db import __main__ as cli
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_preview_zone_option_matches_install(self):
        args = ["schedule", "preview-systemd", "--unit", "timer", "--python", "/usr/bin/python3.14",
                "--workdir", "/home/a/DeckLab"]
        with mock.patch("decklab.lib.config.load", side_effect=AssertionError("read")):
            code, out, err = self.run_cli(args + ["--zone", "Australia/Perth"])
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(out, systemd_units.nightly_units("/usr/bin/python3.14", "/home/a/DeckLab",
                                                               zone="Australia/Perth")[systemd_units.TIMER])
            code, out, err = self.run_cli(args + ["--zone", "bad zone!"])
            self.assertEqual((code, out), (1, ""))
            self.assertIn("--zone", err)
        code, out, err = self.run_cli(["schedule", "status", "--zone", "UTC"])
        self.assertEqual((code, out), (1, ""))
        self.assertIn("only for schedule preview-systemd", err)

    def test_wake_timer_counts_in_the_configured_zone(self):
        rendered = systemd_units.wake_units("00:00", "Australia/Sydney")[systemd_units.WAKE_TIMER]
        self.assertIn("OnCalendar=*-*-* 23:59:00 Australia/Sydney\n", rendered)
        self.assertIn("OnCalendar=*-*-* 03:29:00\n", systemd_units.wake_units()[systemd_units.WAKE_TIMER])
        self.assertIn("23:59:00 Australia/Sydney", "\n".join(
            systemd_units.wake_install_commands("00:00", "Australia/Sydney")))
        with mock.patch("decklab.lib.config.load", return_value={"timezone": "Australia/Perth"}), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("run")):
            code, out, err = self.run_cli(["schedule", "wake-timer"])
            self.assertEqual((code, err), (0, ""))
            self.assertIn("OnCalendar=*-*-* 03:29:00 Australia/Perth\n", out)
            self.assertIn("03:30 Australia/Perth time", out)
            self.assertIn("at 03:29 Australia/Perth time", out)
            said = []
            schedule.wake_timer(say=said.append, zone="")       # "": the host's own zone
            self.assertIn("OnCalendar=*-*-* 03:29:00", said)
        with mock.patch("decklab.lib.config.load", return_value={}):
            code, out, _ = self.run_cli(["schedule", "wake-timer", "--zone", "UTC"])
            self.assertEqual(code, 0)
            self.assertIn("OnCalendar=*-*-* 03:29:00 UTC\n", out)


class PrivateFilesTests(unittest.TestCase):
    def test_backups_and_exports_are_private_off_windows_only(self):
        from argparse import Namespace
        from decklab.db import __main__ as cli
        private = (cli._backup, cli._export, cli._restore_check, cli._restore, cli._nightly)
        for func in private + (cli._prune, cli._sql, cli._schedule):
            for windows in (True, False):
                calls = []
                cli._private_files(Namespace(func=func), windows=windows, umask=calls.append)
                with self.subTest(func=func.__name__, windows=windows):
                    self.assertEqual(calls, [0o077] if func in private and not windows else [])
        cli._private_files(Namespace(), windows=False, umask=self.fail)     # no command: nothing


class DoctorZoneTests(unittest.TestCase):
    def local(self, settings, check=None):
        found = Local(root=REPO, zone_check=check)
        found._settings = settings
        return found

    def test_codes(self):
        self.assertEqual(self.local({}).probe("timezone"), "timezone_not_set")
        self.assertEqual(self.local({"timezone": "bad name!"}).probe("timezone"), "timezone_invalid")
        self.assertEqual(self.local({"timezone": "Australia/Sydney"}, lambda name: None).probe("timezone"),
                         "timezone_matches")
        self.assertEqual(self.local({"timezone": "Australia/Sydney"}, lambda name: "differs").probe("timezone"),
                         "timezone_differs")

        def unknown(name):
            raise LookupError(name)
        self.assertEqual(self.local({"timezone": "Australia/Sydney"}, unknown).probe("timezone"), "timezone_unknown")

    def test_catalog(self):
        for code in preflight.ALLOWED["timezone"]:
            status, message, _ = preflight.OUTCOMES[code]
            self.assertNotIn("Australia", message)
        self.assertEqual(preflight.OUTCOMES["timezone_differs"][0], "needs_setup")
        self.assertIn("timedatectl", preflight.OUTCOMES["timezone_differs"][2])
        row = next(c for c in preflight.CHECKS if c[0] == "timezone")
        self.assertEqual((row[2], row[3]), ("optional", ("config",)))


class CapabilityTests(unittest.TestCase):
    def test_linux_trial(self):
        runs = []

        def run(argv):
            runs.append(argv)
            return 0, ""
        found = keepawake.capability("linux", which=lambda name: "/usr/bin/" + name, run=run)
        self.assertEqual(found, {"kind": "systemd-inhibit", "ok": True, "why": None})
        self.assertEqual(runs[0][0], "/usr/bin/systemd-inhibit")
        self.assertEqual(runs[0][-1], "true")           # ends at once: nothing is left held
        self.assertIn("--mode=block", runs[0])

    def test_linux_refused_and_missing(self):
        found = keepawake.capability("linux", which=lambda name: "/usr/bin/" + name,
                                     run=lambda argv: (1, "Access denied"))
        self.assertEqual((found["ok"], found["why"]), (False, "Access denied"))
        found = keepawake.capability("linux", which=lambda name: "/usr/bin/" + name, run=lambda argv: (None, ""))
        self.assertEqual((found["ok"], found["why"]), (False, "it couldn't run"))
        found = keepawake.capability("linux", which=lambda name: None, run=None)
        self.assertEqual((found["kind"], found["ok"]), ("none", False))
        self.assertIn("isn't installed", found["why"])

    def test_windows_holds_and_lets_go(self):
        class Power:
            held = False
            calls = []

            def hold(self):
                self.calls.append("hold")
                self.held = True

            def release(self):
                self.calls.append("release")
                self.held = False
        power = Power()
        self.assertTrue(keepawake.capability("win32", power=power)["ok"])
        self.assertEqual(power.calls, ["hold", "release"])

        class Refuses(Power):
            def hold(self):
                raise OSError("no")
        refuses = Refuses()
        found = keepawake.capability("win32", power=refuses)
        self.assertEqual((found["ok"], found["why"]), (False, "no"))
        self.assertIn("release", refuses.calls)

    def test_elsewhere_nothing_is_tried(self):
        self.assertIsNone(keepawake.capability("darwin")["ok"])

    def test_trial_run_handles_failures(self):
        with mock.patch.object(keepawake.subprocess, "run", side_effect=OSError("gone")):
            self.assertEqual(keepawake._trial_run(["x"]), (None, "gone"))
        with mock.patch.object(keepawake.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 10)):
            self.assertEqual(keepawake._trial_run(["x"])[0], None)
        done = types.SimpleNamespace(returncode=1, stderr="\nFailed to inhibit: Access denied\n", stdout="")
        with mock.patch.object(keepawake.subprocess, "run", return_value=done):
            self.assertEqual(keepawake._trial_run(["x"]), (1, "Failed to inhibit: Access denied"))


class SmokeStepTests(unittest.TestCase):
    def result(self):
        return smoke.Result("x", "X")

    def test_awake_steps(self):
        r = self.result()
        smoke.step_awake(r, {}, check=lambda: {"kind": "systemd-inhibit", "ok": True, "why": None})
        self.assertEqual(r.status, smoke.PASS)
        self.assertIn("systemd-inhibit", r.lines[0][1])
        r = self.result()
        smoke.step_awake(r, {}, check=lambda: {"kind": "systemd-inhibit", "ok": False, "why": "Access denied"},
                         user="decklab")
        self.assertEqual(r.status, smoke.WARN)
        self.assertIn("Access denied", r.lines[0][1])
        self.assertIn("50-decklab-inhibit.rules", r.lines[0][1])
        self.assertIn('s.user == "decklab"', r.lines[0][1])
        r = self.result()
        smoke.step_awake(r, {}, check=lambda: {"kind": "none", "ok": False, "why": "systemd-inhibit isn't installed"})
        self.assertEqual(r.status, smoke.WARN)
        with self.assertRaises(smoke.Skip):
            smoke.step_awake(self.result(), {}, check=lambda: {"kind": "none", "ok": None, "why": "not here"})

    def test_time_step(self):
        with self.assertRaises(smoke.Skip):
            smoke.step_time(self.result(), {}, settings={})
        r = self.result()
        smoke.step_time(r, {}, settings={"timezone": "bad name!"})
        self.assertEqual(r.status, smoke.WARN)
        r = self.result()
        smoke.step_time(r, {}, settings={"timezone": "Australia/Sydney"}, mismatch=lambda name: None)
        self.assertEqual(r.status, smoke.PASS)
        r = self.result()
        smoke.step_time(r, {}, settings={"timezone": "Australia/Sydney"}, mismatch=lambda name: "This PC keeps ...")
        self.assertEqual((r.status, r.lines[0][1]), (smoke.WARN, "This PC keeps ..."))

        def unknown(name):
            raise LookupError(name)
        r = self.result()
        smoke.step_time(r, {}, settings={"timezone": "Australia/Sydney"}, mismatch=unknown)
        self.assertEqual(r.status, smoke.WARN)
        self.assertIn("no time zone data", r.lines[0][1])

    def test_time_step_needs_the_config(self):
        with self.assertRaises(smoke.Skip):
            smoke.step_time(self.result(), {"doctor": {"config": "needs_setup"}})

    def test_steps_are_listed(self):
        ids = [ident for ident, _, _ in smoke.STEPS]
        self.assertLess(ids.index("wake"), ids.index("awake"))
        self.assertIn("time", ids)

    def test_wording_follows_the_platform(self):
        self.assertEqual(smoke._task_word("linux"), "timer")
        self.assertEqual(smoke._task_word("win32"), "task")
        self.assertIn("systemd", smoke._start_words("linux"))
        self.assertIn("logon", smoke._start_words("win32"))
        with mock.patch.object(smoke.sys, "platform", "linux"):
            self.assertIn("nightly backup timer", smoke.schedule_finding(1, ""))
        with mock.patch.object(smoke.sys, "platform", "win32"):
            self.assertIn("nightly backup task", smoke.schedule_finding(1, ""))

    def test_backup_dir_needs_its_parent(self):
        from decklab.db import backup, conn
        with tempfile.TemporaryDirectory() as tmp:
            staging, missing = Path(tmp) / "staging", Path(tmp) / "share" / "DeckLab"
            staging.mkdir()
            paths = {"staging_dir": str(staging), "backup_dir": str(missing)}
            r = self.result()
            with mock.patch.object(conn, "pg_bin", side_effect=FileNotFoundError("not here")), \
                    mock.patch.object(conn, "settings", return_value={}), \
                    mock.patch.object(conn, "path_setting", side_effect=lambda key, s: paths[key]), \
                    mock.patch.object(backup, "same_device_problem", return_value=None), \
                    mock.patch.object(backup, "last_ok", return_value={}):
                smoke.step_backups(r, {"doctor": {"database": "ready"}})
                texts = [text for status, text in r.lines if status == smoke.FAIL]
                self.assertTrue(any("parent folder" in text and "share" in text for text in texts), r.lines)
                self.assertFalse(missing.parent.exists())
                missing.parent.mkdir()
                r = self.result()
                smoke.step_backups(r, {"doctor": {"database": "ready"}})
                self.assertIn((smoke.PASS, f"backup_dir {missing} is writable (made on the first backup)"), r.lines)


class UpdateInterpreterTests(unittest.TestCase):
    def test_base_python_from_pyvenv(self):
        values = {"home": "/home/a/.local/share/uv/python/cpython-3.14.0-linux/bin", "version": "3.14.0"}
        self.assertEqual(update.venv_base_python(values, windows=False),
                         "/home/a/.local/share/uv/python/cpython-3.14.0-linux/bin/python3.14")
        self.assertEqual(update.venv_base_python({"home": "/usr/bin", "version_info": "3.14.1.final.0"}, windows=False),
                         "/usr/bin/python3.14")
        self.assertEqual(update.venv_base_python({"home": r"C:\Python314"}, windows=True),
                         str(Path(r"C:\Python314") / "python.exe"))
        self.assertIsNone(update.venv_base_python({}, windows=False))

    def test_venv_config_reads_pyvenv(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(update._venv_config(tmp))
            (Path(tmp) / ".venv").mkdir()
            (Path(tmp) / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\nVersion = 3.14.0\n", encoding="utf-8")
            self.assertEqual(update._venv_config(tmp), {"home": "/usr/bin", "version": "3.14.0"})

    def test_a_venv_from_another_python_is_refused(self):
        values = {"home": "/opt/py/bin", "version": "3.14.0"}
        problem = update.interpreter_problem("/usr/bin/python3", activate=lambda: ".venv was made from another Python",
                                             venv=values, units=[], platform="linux")
        self.assertIn("/opt/py/bin/python3.14 -m decklab.update", problem)
        self.assertIn("Nothing was fetched", problem)
        self.assertIsNone(update.interpreter_problem("/opt/py/bin/python3.14", activate=lambda: None,
                                                     venv=values, units=[], platform="linux"))

    def test_no_venv_is_left_to_the_smoke_test(self):
        self.assertIsNone(update.interpreter_problem("/usr/bin/python3",
                                                     activate=mock.Mock(side_effect=AssertionError("asked")),
                                                     venv={}, units=[], platform="linux"))

    def test_units_running_another_python_are_refused_on_linux_only(self):
        units = [("The background service", "/usr/bin/python3.12", "-m decklab.lib.homenet install")]
        problem = update.interpreter_problem("/opt/py/bin/python3.14", activate=lambda: None, venv={},
                                             units=units, platform="linux")
        self.assertIn("The background service runs /usr/bin/python3.12", problem)
        self.assertIn("/opt/py/bin/python3.14 -m decklab.lib.homenet install", problem)
        self.assertIsNone(update.interpreter_problem("/usr/bin/python3.12", activate=lambda: None, venv={},
                                                     units=units, platform="linux"))
        self.assertIsNone(update.interpreter_problem("/opt/py/bin/python3.14", activate=lambda: None, venv={},
                                                     units=mock.Mock(side_effect=AssertionError("read")),
                                                     platform="win32"))

    def test_installed_units_reads_both_unit_files(self):
        from decklab.lib.homenet import service
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "decklab.service").write_text(service.unit_text("/opt/py/bin/python3.14", "/srv/decklab",
                                                                      ["decklab/server.py"]), encoding="utf-8")
            (folder / "decklab-nightly.service").write_text(
                systemd_units.nightly_units("/usr/bin/python3.12", "/srv/decklab")["decklab-nightly.service"],
                encoding="utf-8")
            with mock.patch("decklab.lib.systemd.unit_dir", return_value=folder):
                found = update._installed_units()
        self.assertEqual([(what, program) for what, program, _ in found],
                         [("The background service", "/opt/py/bin/python3.14"),
                          ("The nightly timer", "/usr/bin/python3.12")])

    def test_before_pull_stops_before_fetching(self):
        with mock.patch.object(update, "interpreter_problem", return_value="wrong Python"), \
                mock.patch.object(update, "git", side_effect=AssertionError("git ran")), \
                self.assertRaises(update.Failed):
            update.before_pull(types.SimpleNamespace(dry_run=True, no_forge=True, no_restart=True, no_smoke=True))


class UpdatePsycopgTests(unittest.TestCase):
    def run_after_pull(self, needs_stop):
        steps = []
        args = types.SimpleNamespace(no_forge=True, no_restart=True, no_smoke=True)
        with mock.patch.object(update, "PIP_NEEDS_STOP", needs_stop), \
                mock.patch.object(update, "changed_files", return_value=[update.REQUIREMENTS]), \
                mock.patch.object(update, "git", return_value="abc"), \
                mock.patch.object(update, "server_answers", return_value=True), \
                mock.patch.object(update, "venv_python", return_value=Path("/srv/.venv/bin/python")), \
                mock.patch.object(update, "step", side_effect=lambda argv, what, timeout=None: steps.append(what)), \
                mock.patch("decklab.lib.venv.activate", return_value=None), \
                mock.patch("decklab.db.migrate.pending", return_value=[]), \
                mock.patch.object(update, "say"):
            update._after_pull(args, "abc", set())
        return steps

    def test_linux_keeps_the_server_running_while_pip_replaces_psycopg(self):
        self.assertEqual(self.run_after_pull(False), ["Reinstall psycopg"])

    def test_windows_stops_it_first(self):
        self.assertEqual(self.run_after_pull(True), ["Stop Deck Lab to replace psycopg", "Reinstall psycopg"])


class LauncherTests(unittest.TestCase):
    PATH = REPO / "scripts" / "decklab"

    def test_it_is_lf_and_runs_homenet(self):
        data = self.PATH.read_bytes()
        self.assertNotIn(b"\r", data)
        self.assertTrue(data.startswith(b"#!/bin/sh\n"))
        self.assertIn(b"-m decklab.lib.homenet start", data)
        self.assertIn(b'-m decklab.lib.homenet "$@"', data)
        self.assertIn(b".venv/pyvenv.cfg", data)

    def test_git_keeps_it_lf_and_executable(self):
        attributes = (REPO / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("scripts/decklab text eol=lf", attributes)
        self.assertIn("*.sh text eol=lf", attributes)
        try:
            out = subprocess.run(["git", "ls-files", "-s", "scripts/decklab"], cwd=REPO, capture_output=True,
                                 text=True, timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired):
            self.skipTest("git isn't available")
        if not out.strip():
            self.skipTest("not a git checkout")
        self.assertTrue(out.startswith("100755 "), out)

    @unittest.skipUnless(os.name == "posix" and Path("/bin/sh").exists(), "needs a POSIX shell")
    def test_it_picks_the_venv_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            launcher = root / "scripts" / "decklab"
            launcher.write_bytes(self.PATH.read_bytes())
            launcher.chmod(0o755)
            home = root / "base" / "bin"
            home.mkdir(parents=True)
            fake = home / "python3.14"
            fake.write_text('#!/bin/sh\necho "$0 $*"\n', encoding="utf-8")
            fake.chmod(0o755)
            (root / ".venv").mkdir()
            (root / ".venv" / "pyvenv.cfg").write_text(f"home = {home}\nversion = 3.14.0\n", encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k != "DECKLAB_PYTHON"}
            out = subprocess.run(["/bin/sh", str(launcher)], capture_output=True, text=True, env=env,
                                 cwd="/", timeout=30).stdout
            self.assertEqual(out.strip(), f"{fake} -m decklab.lib.homenet start")
            out = subprocess.run(["/bin/sh", str(launcher), "status", "--port", "1"], capture_output=True,
                                 text=True, env=env, cwd="/", timeout=30).stdout
            self.assertEqual(out.strip(), f"{fake} -m decklab.lib.homenet status --port 1")
            # Through a symlink in another folder (~/.local/bin/decklab), absolute and relative,
            # and a link to that link: the repo is still the script's own.
            bin_dir = root / "home" / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "decklab").symlink_to(launcher)
            (bin_dir / "relative").symlink_to(os.path.relpath(launcher, bin_dir))
            (bin_dir / "chained").symlink_to("relative")
            for name in ("decklab", "relative", "chained"):
                with self.subTest(link=name):
                    out = subprocess.run(["/bin/sh", str(bin_dir / name), "status"], capture_output=True,
                                         text=True, env=env, cwd="/", timeout=30).stdout
                    self.assertEqual(out.strip(), f"{fake} -m decklab.lib.homenet status")


class OwnProcessesTests(unittest.TestCase):
    def tree(self, root, pid, comm, parent):
        folder = root / str(pid)
        folder.mkdir()
        (folder / "comm").write_text(comm + "\n", encoding="utf-8")
        (folder / "stat").write_text(f"{pid} ({comm} odd) S {parent} 1 1\n", encoding="utf-8")

    def test_only_this_users_interpreters_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.tree(root, 10, "python3.14", 1)
            self.tree(root, 11, "bash", 1)
            (root / "self").mkdir()
            ours = (root / "10").stat().st_uid
            self.assertEqual(space_runtime._linux_processes(root, uid=ours), {10: 1})
            self.assertEqual(space_runtime._linux_processes(root, uid=ours + 1), {})

    def test_an_unreadable_proc_is_refused(self):
        with self.assertRaises(ValueError):
            space_runtime._linux_processes(Path(tempfile.gettempdir()) / "no-such-proc-folder", uid=0)


if __name__ == "__main__":
    unittest.main()
