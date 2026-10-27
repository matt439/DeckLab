"""CLI-only systemd previews; every host, config, data and process boundary is forbidden."""
import io
import subprocess
import unittest
from argparse import Namespace
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from decklab.db import __main__ as cli, conn as db, schedule, systemd_units
from decklab.lib import config, inventory


class SchedulePreviewTests(unittest.TestCase):
    args = ("schedule", "preview-systemd", "--unit", "service", "--python", "/opt/python3.14/python",
            "--workdir", "/srv/Deck Lab")

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # inventory.pinned() is lazy: parsing/rendering must never request a snapshot.
        for target, names in ((config, ("load",)), (db, ("connect", "settings")),
                              (inventory, ("backend", "current")),
                              (schedule, ("_homenet", "query_task", "psycopg_problem")),
                              (subprocess, ("run", "Popen")), (Path, ("write_text", "write_bytes", "mkdir"))):
            for name in names:
                self.stack.enter_context(mock.patch.object(target, name,
                                         side_effect=AssertionError("preview must not call " + name)))

    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_main_prints_only_selected_service_with_no_reads_or_writes(self):
        code, out, err = self.run_cli(self.args)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, systemd_units.nightly_units("/opt/python3.14/python", "/srv/Deck Lab")
                         [systemd_units.SERVICE])
        self.assertNotIn("[Timer]", out)

    def test_timer_selection_and_explicit_time(self):
        args = list(self.args)
        args[args.index("service")] = "timer"
        code, out, err = self.run_cli(args + ["--at", "23:59"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, systemd_units.nightly_units("/opt/python3.14/python", "/srv/Deck Lab", "23:59")
                         [systemd_units.TIMER])
        self.assertNotIn("ExecStart", out)

    def test_piped_output_preserves_utf8_paths_and_lf_without_replacement(self):
        args = list(self.args)
        args[args.index("--workdir") + 1] = "/srv/Deck Lab/\u96ea"
        raw = io.BytesIO()
        pipe = io.TextIOWrapper(raw, encoding="ascii", errors="replace", newline="\r\n")
        self.addCleanup(pipe.close)
        with redirect_stdout(pipe), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(args), 0)
        pipe.flush()
        self.assertEqual(raw.getvalue(), systemd_units.nightly_units("/opt/python3.14/python", "/srv/Deck Lab/\u96ea")
                         [systemd_units.SERVICE].encode("utf-8"))

    def test_preview_is_available_on_windows_and_linux_without_host_checks(self):
        for platform in ("win32", "linux"):
            said = []
            with self.subTest(platform=platform), mock.patch.object(schedule.sys, "platform", platform):
                self.assertEqual(schedule.preview_systemd("service", "/usr/bin/python3.14", "/srv/DeckLab",
                                                         say=said.append), 0)
            self.assertEqual(said, [systemd_units.nightly_units("/usr/bin/python3.14", "/srv/DeckLab")
                                   [systemd_units.SERVICE].rstrip("\n")])

    def test_wrapper_default_matches_existing_windows_time(self):
        self.assertEqual(schedule.AT, systemd_units.DEFAULT_AT)
        said = []
        self.assertEqual(schedule.preview_systemd("timer", "/usr/bin/python", "/srv/DeckLab", say=said.append), 0)
        self.assertIn("OnCalendar=*-*-* " + schedule.AT + ":00", said[0])

    def test_each_explicit_target_argument_is_required_before_output(self):
        for option in ("--unit", "--python", "--workdir"):
            args = list(self.args)
            index = args.index(option)
            del args[index:index + 2]
            with self.subTest(option=option):
                code, out, err = self.run_cli(args)
                self.assertEqual((code, out), (1, ""))
                self.assertIn(option, err)

    def test_invalid_target_and_time_produce_no_partial_unit(self):
        for option, value in (("--python", r"C:\Python\python.exe"), ("--workdir", "./DeckLab"),
                              ("--at", "03:30\nUnit=unexpected.service")):
            args = list(self.args)
            if option in args:
                args[args.index(option) + 1] = value
            else:
                args.extend((option, value))
            with self.subTest(option=option):
                code, out, err = self.run_cli(args)
                self.assertEqual((code, out), (1, ""))
                self.assertIn(option, err)

    def test_other_actions_refuse_preview_options_before_dispatch(self):
        for action in ("install", "remove", "status"):
            for option, value in (("--unit", "service"), ("--python", "/usr/bin/python"),
                                  ("--workdir", "/srv/DeckLab"), ("--at", "03:30")):
                with self.subTest(action=action, option=option), \
                        mock.patch.object(schedule, action, side_effect=AssertionError("must not dispatch")):
                    code, out, err = self.run_cli(["schedule", action, option, value])
                    self.assertEqual((code, out), (1, ""))
                    self.assertIn("only for schedule preview-systemd", err)

    def test_existing_install_and_remove_dispatch_contract_is_unchanged(self):
        for action in ("install", "remove"):
            with self.subTest(action=action), mock.patch.object(schedule, action, return_value=7) as call:
                self.assertEqual(cli._schedule(Namespace(action=action)), 7)
                call.assert_called_once_with()

    def test_existing_status_dispatch_and_lines_are_unchanged(self):
        out = io.StringIO()
        with mock.patch.object(schedule, "status", return_value=["Nightly task: test", "  daily"]), \
                redirect_stdout(out):
            self.assertEqual(cli._schedule(Namespace(action="status")), 0)
        self.assertEqual(out.getvalue(), "Nightly task: test\n  daily\n")


if __name__ == "__main__":
    unittest.main()
