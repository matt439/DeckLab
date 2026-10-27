"""Executable sibling paths with injected lexical semantics and no OS operations.

These fixtures exercise POSIX path handling on Windows; they do not claim that
Linux itself, a service manager or a running server was tested.
"""
import unittest
from pathlib import PurePosixPath, PureWindowsPath
from unittest import mock

from decklab.lib import gitops
from decklab.lib.homenet import commands


class ExecutableSiblingTests(unittest.TestCase):
    def check_paths(self, source, python, pythonw, factory):
        with mock.patch.object(commands, "Path", factory):
            self.assertEqual(commands.pythonw_path(source), factory(pythonw))
            self.assertEqual(commands.this_pythons(source), [factory(python), factory(pythonw)])

    def test_windows_drive_unc_rooted_relative_and_mixed_paths_on_both_flavours(self):
        cases = [
            (r"C:\Python Folder\python.exe", r"C:\Python Folder\python.exe", r"C:\Python Folder\pythonw.exe"),
            ("C:/Python Folder/python3.exe", r"C:\Python Folder\python.exe", r"C:\Python Folder\pythonw.exe"),
            (r"C:/Program Files\Python/bin/python.exe", r"C:\Program Files\Python\bin\python.exe", r"C:\Program Files\Python\bin\pythonw.exe"),
            (r"\\server\Python share\bin\python.exe", r"\\server\Python share\bin\python.exe", r"\\server\Python share\bin\pythonw.exe"),
            ("//server/Python share/bin/python.exe", r"\\server\Python share\bin\python.exe", r"\\server\Python share\bin\pythonw.exe"),
            (r"\Python\python.exe", r"\Python\python.exe", r"\Python\pythonw.exe"),
            (r"relative\Python\python.exe", r"relative\Python\python.exe", r"relative\Python\pythonw.exe"),
            ("C:python.exe", "C:python.exe", "C:pythonw.exe"),
        ]
        for factory in (PurePosixPath, PureWindowsPath):
            for source, python, pythonw in cases:
                with self.subTest(flavour=factory.__name__, source=source):
                    self.check_paths(source, python, pythonw, factory)

    def test_native_posix_paths_keep_directories_and_literal_backslashes(self):
        for source, folder in (("/usr/bin/python3.14", "/usr/bin"), ("/opt/Deck Lab/python3", "/opt/Deck Lab"),
                               ("/opt/back\\slash/python3", "/opt/back\\slash"), ("relative/bin/python3", "relative/bin")):
            with self.subTest(source=source):
                self.check_paths(source, folder + "/python.exe", folder + "/pythonw.exe", PurePosixPath)

    def test_bare_names_remain_bare_on_both_flavours(self):
        for factory in (PurePosixPath, PureWindowsPath):
            for source in ("python", "python3", "python.exe", "pythonw.exe"):
                with self.subTest(flavour=factory.__name__, source=source):
                    self.check_paths(source, "python.exe", "pythonw.exe", factory)

    def test_default_interpreter_and_pathlike_inputs_use_the_same_rules(self):
        class Interpreter:
            def __fspath__(self):
                return r"C:\Python Folder\python.exe"
        for source in (Interpreter(), PureWindowsPath(r"C:\Python Folder\python.exe")):
            self.check_paths(source, r"C:\Python Folder\python.exe", r"C:\Python Folder\pythonw.exe", PurePosixPath)
        self.check_paths(PurePosixPath("/opt/python/bin/python3"), "/opt/python/bin/python.exe", "/opt/python/bin/pythonw.exe", PurePosixPath)
        for executable in (r"C:\Python Folder\python.exe", "/opt/python/bin/python3", "python3"):
            with self.subTest(default=executable), mock.patch.object(commands.sys, "executable", executable), \
                    mock.patch.object(commands, "Path", PurePosixPath):
                self.assertEqual(commands.pythonw_path(), commands.pythonw_path(executable))
                self.assertEqual(commands.this_pythons(), commands.this_pythons(executable))

    def test_typed_posix_relative_pathlike_and_default_keep_backslash_and_colon_components(self):
        class PosixInterpreter(PurePosixPath):
            pass
        for factory in (PurePosixPath, PosixInterpreter):
            for text in ("relative/back\\slash/python3", "c:folder/python3", "C:/folder/python3"):
                source = factory(text)
                expected = [source.with_name("python.exe"), source.with_name("pythonw.exe")]
                for host in (PurePosixPath, PureWindowsPath):
                    with self.subTest(pathlike=factory.__name__, host=host.__name__, text=text), mock.patch.object(commands, "Path", host):
                        self.assertEqual(commands.pythonw_path(source), expected[1])
                        self.assertEqual(commands.this_pythons(source), expected)
                        with mock.patch.object(commands.sys, "executable", source):
                            self.assertEqual(commands.pythonw_path(), expected[1])
                            self.assertEqual(commands.this_pythons(), expected)

    def test_a_root_without_an_executable_is_not_silently_reinterpreted(self):
        with mock.patch.object(commands, "Path", PurePosixPath):
            for root in ("/", "C:\\", "\\\\server\\share\\"):
                with self.subTest(root=root):
                    with self.assertRaises(ValueError):
                        commands.pythonw_path(root)
                    with self.assertRaises(ValueError):
                        commands.this_pythons(root)

    def test_windows_git_diagnostic_fixture_uses_lexical_windows_forms(self):
        root = PureWindowsPath(r"C:\Users\someone\TradingCardCollection")
        text = (r"C:\Users\someone\TradingCardCollection\magic\decks x c:/users/someone/tradingcardcollection/magic "
                "/c/Users/someone/TradingCardCollection/decks C:/Users/someone/TradingCardCollection "
                "C:/Users/someone/TradingCardCollection2/x")
        self.assertEqual(gitops._relative_paths(text, root),
                         r"magic\decks x magic decks the repo folder C:/Users/someone/TradingCardCollection2/x")
