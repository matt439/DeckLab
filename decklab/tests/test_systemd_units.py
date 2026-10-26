"""Lexical unit previews only: no Linux manager, task, database or filesystem actions."""
import unittest
from pathlib import PurePosixPath, PureWindowsPath

from decklab.db import systemd_units as units


class NightlyUnitsTests(unittest.TestCase):
    python = "/opt/python3.14/bin/python"
    workdir = "/srv/Deck Lab"

    def render(self, **values):
        return units.nightly_units(values.get("python", self.python), values.get("workdir", self.workdir),
                                   values.get("at", "03:30"))

    def test_fixed_filenames_and_complete_service(self):
        rendered = self.render()
        self.assertEqual(set(rendered), {"decklab-nightly.service", "decklab-nightly.timer"})
        self.assertEqual(rendered[units.SERVICE], '''[Unit]
Description=Deck Lab nightly maintenance

[Service]
Type=oneshot
WorkingDirectory=/srv/Deck Lab
ExecStart=":/opt/python3.14/bin/python" -m decklab.db nightly
TimeoutStartSec=2h
Restart=no
RemainAfterExit=no
''')

    def test_daily_local_calendar_catchup_and_explicit_target(self):
        self.assertEqual(self.render(at="04:07")[units.TIMER], '''[Unit]
Description=Deck Lab nightly maintenance schedule

[Timer]
OnCalendar=*-*-* 04:07:00
Persistent=true
Unit=decklab-nightly.service

[Install]
WantedBy=timers.target
''')
        self.assertIn("OnCalendar=*-*-* 03:30:00\n", self.render()[units.TIMER])

    def test_percent_specifiers_are_literal_in_both_paths(self):
        text = self.render(python="/opt/%h/%/python", workdir="/srv/%u/100% Deck Lab")[units.SERVICE]
        self.assertIn('ExecStart=":/opt/%%h/%%/python" -m decklab.db nightly\n', text)
        self.assertIn("WorkingDirectory=/srv/%%u/100%% Deck Lab\n", text)

    def test_dollars_are_not_doubled_in_executable_lookup(self):
        text = self.render(python="/opt/$USER/${HOME}/python", workdir="/srv/$HOME/Deck Lab")[units.SERVICE]
        self.assertIn('ExecStart=":/opt/$USER/${HOME}/python" -m decklab.db nightly\n', text)
        self.assertIn("WorkingDirectory=/srv/$HOME/Deck Lab\n", text)
        self.assertNotIn("$$", text)

    def test_spaces_utf8_and_shell_metacharacters_stay_in_one_exec_token(self):
        text = self.render(python="/opt/Python Tools/écho;$(touch x)/python")[units.SERVICE]
        self.assertIn('ExecStart=":/opt/Python Tools/écho;$(touch x)/python" -m decklab.db nightly\n', text)
        self.assertNotIn("/bin/sh", text)

    def test_workdir_is_raw_without_c_unquoting(self):
        directory = '/srv/Deck "Lab"/User1\'s\\cards'
        text = self.render(workdir=directory)[units.SERVICE]
        self.assertIn("WorkingDirectory=" + directory + "\n", text)
        self.assertNotIn('WorkingDirectory="', text)
        self.assertNotIn("\\\\cards", text)

    def test_typed_posix_paths_are_supported_on_any_host(self):
        self.assertEqual(self.render(python=PurePosixPath(self.python), workdir=PurePosixPath(self.workdir)),
                         self.render())

    def test_relative_windows_unc_and_wrong_types_are_refused(self):
        bad = (None, True, b"/srv/DeckLab", "", "python", "./python", "../python", "~/python",
               "C:/Python/python.exe", r"C:\Python\python.exe", r"\\server\share", "//srv/python",
               PureWindowsPath("C:/Python/python.exe"), 314)
        for field in ("python", "workdir"):
            for value in bad:
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "POSIX"):
                    self.render(**{field: value})

    def test_parent_components_and_edge_whitespace_are_refused(self):
        for field in ("python", "workdir"):
            for value in ("/srv/../python", "/../python", "/srv/python/..", "/srv/python ",
                          " /srv/python", "/srv/python\u00a0"):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.render(**{field: value})

    def test_all_c0_c1_and_del_controls_are_refused(self):
        for code in (*range(32), *range(127, 160)):
            for field in ("python", "workdir"):
                with self.subTest(field=field, code=code), self.assertRaises(ValueError):
                    self.render(**{field: "/srv/x" + chr(code) + "y"})

    def test_unencodable_surrogates_are_refused(self):
        for field in ("python", "workdir"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "UTF-8"):
                self.render(**{field: "/srv/\ud800/python"})

    def test_unsafe_executable_names_are_refused_instead_of_claiming_c_escaping_works(self):
        for value in ("/", "/opt/python/", '/opt/py"thon', "/opt/py'thon", r"/opt/py\thon"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "executable"):
                self.render(python=value)

    def test_raw_workdir_cannot_continue_the_next_unit_line(self):
        with self.assertRaisesRegex(ValueError, "backslash"):
            self.render(workdir="/srv/DeckLab\\")

    def test_root_workdir_is_valid_and_does_not_become_a_home_specifier(self):
        self.assertIn("WorkingDirectory=/\n", self.render(workdir="/")[units.SERVICE])

    def test_calendar_input_is_strict_and_does_not_accept_unit_injection(self):
        for at in (None, True, 330, "3:30", "03:3", "24:00", "00:60", "-1:00", "03:30 ", "daily",
                   "０３:３０", "03:30\nUnit=other.service", "03:30 UTC", "03:30:00", "03:30\x00"):
            with self.subTest(at=at), self.assertRaisesRegex(ValueError, "HH:MM"):
                self.render(at=at)
        for at in ("00:00", "23:59"):
            self.assertIn("OnCalendar=*-*-* " + at + ":00\n", self.render(at=at)[units.TIMER])


if __name__ == "__main__":
    unittest.main()
