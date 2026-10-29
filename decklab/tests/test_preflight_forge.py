"""Optional preflight checks inspect an injected filesystem, never installed tools."""
from contextlib import ExitStack
import itertools
from pathlib import Path
import socket
import stat
import subprocess
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.request

from decklab.lib import preflight, preflight_forge as optional


class FakeFiles:
    def __init__(self, root):
        self.root = root
        self.nodes = {}
        self.contents = {}
        self.children = {}
        self.stats = []
        self.reads = []
        self.lists = []
        self.directory(root)

    def directory(self, path):
        for directory in (path, *path.parents):
            self.nodes.setdefault(directory, SimpleNamespace(st_mode=stat.S_IFDIR, st_size=0,
                                                            st_file_attributes=0))

    def file(self, path, data=b"fixture", *, size=None):
        self.directory(path.parent)
        self.nodes[path] = SimpleNamespace(st_mode=stat.S_IFREG,
                                          st_size=len(data) if size is None else size,
                                          st_file_attributes=0)
        self.contents[path] = data

    def stat(self, path):
        self.stats.append(path)
        if path not in self.nodes:
            raise FileNotFoundError("private fixture path")
        return self.nodes[path]

    def read(self, path, limit):
        self.reads.append((path, limit))
        return self.contents[path][:limit]

    def names(self, path):
        self.lists.append(path)
        return iter(self.children.get(path, []))


class OptionalFilesTests(unittest.TestCase):
    def setUp(self):
        # Only lexical Path operations use this name: every filesystem operation is
        # supplied below, including all ancestors. No actual folder is read/created.
        self.root = Path.cwd() / "optional-preflight-fixture"
        self.fs = FakeFiles(self.root)
        self.settings = {}
        self.provider = mock.Mock(side_effect=lambda: self.settings)
        self.selected_java = mock.Mock(return_value=None)
        stack = self.enterContext(ExitStack())
        for target in ("pathlib.Path.open", "pathlib.Path.lstat", "os.scandir",
                       "subprocess.run", "subprocess.Popen", "os.system",
                       "socket.create_connection", "urllib.request.urlopen"):
            stack.enter_context(mock.patch(target, side_effect=AssertionError("Host operation forbidden")))
        self.adapter = self.make_adapter()

    def make_adapter(self, **options):
        return optional.ForgeFiles(self.provider, self.root, stat_path=self.fs.stat,
                                   list_names=self.fs.names, read_bytes=self.fs.read,
                                   java_path=self.selected_java, **options)

    def java(self, version='21.0.4'):
        path = self.root / "jdk" / "bin" / "java"
        self.fs.file(path)
        self.release = path.parent.parent / "release"
        self.fs.file(self.release, f'JAVA_VERSION="{version}"\n'.encode())
        self.settings["forge_java"] = str(path)
        return path

    def forge(self, version="2.0.15-decklab-fixture"):
        path = self.root / "forge"
        self.jar = path / f"forge-gui-desktop-{version}-jar-with-dependencies.jar"
        self.scripts = path / "res" / "cardsfolder" / "cardsfolder.zip"
        self.fs.file(self.jar, b"PK\x03\x04fixture")
        self.fs.file(self.scripts, b"PK\x03\x04fixture")
        self.fs.children[path] = [self.jar.name]
        self.settings["forge_dir"] = str(path)
        return path

    def test_creation_is_inert_and_configuration_is_captured_once(self):
        self.provider.assert_not_called()
        self.assertFalse(self.fs.stats)
        self.assertEqual("java_unavailable", self.adapter.probe("java"))
        self.assertEqual("forge_missing", self.adapter.probe("forge"))
        self.provider.assert_called_once_with()
        self.assertFalse(self.fs.stats)
        self.assertFalse(self.fs.lists)
        self.assertFalse(self.fs.reads)

    def test_no_java_auto_discovery_or_execution(self):
        self.assertEqual("java_unavailable", self.adapter.probe("java"))
        self.selected_java.assert_called_once_with()
        self.assertFalse(self.fs.stats)

    def test_explicit_java_files_and_release_do_not_require_compiler_or_execute(self):
        path = self.java()
        self.assertEqual("java_files_ready", self.adapter.probe("java"))
        self.selected_java.assert_not_called()
        self.assertEqual([(self.release, optional.MAX_RELEASE)], self.fs.reads)
        self.assertIn(path, self.fs.stats)
        self.assertFalse(any(p.name in ("javac", "jar") for p in self.fs.stats))

    def test_injected_selected_java_is_supported_without_search(self):
        path = self.java()
        del self.settings["forge_java"]
        self.selected_java.return_value = path
        self.assertEqual("java_files_ready", self.adapter.probe("java"))
        self.selected_java.assert_called_once_with()

    def test_java_version_rejects_old_unknown_and_duplicate_metadata(self):
        self.java()
        cases = [(b'JAVA_VERSION="17.0.9"\n', "java_version_unsupported"),
                 (b'JAVA_VERSION="1.8.0_202"\n', "java_version_unsupported"),
                 (b'JAVA_VERSION="21-ea"\n', "java_files_ready"),
                 (b'JAVA_VERSION="25.0.1+8"\n', "java_files_ready"),
                 (b'JAVA_VERSION="private-invalid"\n', "java_version_unknown"),
                 (b'JAVA_VERSION="21"\nJAVA_VERSION="17"\n', "java_version_unknown"),
                 (b'JAVA_VERSION="21garbage"\n', "java_version_unknown"),
                 (b'OTHER="21"\n', "java_version_unknown"),
                 (b'\xff', "java_version_unknown")]
        for data, expected in cases:
            with self.subTest(data=data):
                self.fs.file(self.release, data)
                self.assertEqual(expected, self.adapter.probe("java"))

    def test_java_missing_empty_directory_and_missing_release_are_distinct(self):
        path = self.java()
        del self.fs.nodes[path]
        self.assertEqual("java_missing", self.adapter.probe("java"))
        self.fs.file(path, b"")
        self.assertEqual("java_incomplete", self.adapter.probe("java"))
        self.fs.nodes[path].st_mode = stat.S_IFDIR
        self.assertEqual("java_incomplete", self.adapter.probe("java"))
        self.fs.file(path)
        del self.fs.nodes[self.release]
        self.assertEqual("java_version_unknown", self.adapter.probe("java"))

    def test_java_release_read_has_byte_and_consistency_limits(self):
        self.java()
        for size in (0, optional.MAX_RELEASE, optional.MAX_RELEASE + 1):
            with self.subTest(size=size):
                self.fs.nodes[self.release].st_size = size
                self.fs.reads.clear()
                self.assertEqual("java_version_unknown", self.adapter.probe("java"))
                self.assertFalse(self.fs.reads)
        self.fs.nodes[self.release].st_size = 100
        self.assertEqual("java_version_unknown", self.adapter.probe("java"))
        self.assertEqual([(self.release, optional.MAX_RELEASE)], self.fs.reads)

    def test_forge_file_facts_use_only_four_byte_prefixes(self):
        self.forge()
        self.assertEqual("forge_files_ready", self.adapter.probe("forge"))
        self.assertEqual([(self.jar, 4), (self.scripts, 4)], self.fs.reads)
        self.assertEqual([self.jar.parent], self.fs.lists)

    def test_relative_install_paths_are_scoped_to_explicit_root(self):
        folder = self.forge()
        path = self.java()
        self.settings.update(forge_dir="forge", forge_java=str(path.relative_to(self.root)))
        self.assertEqual("forge_files_ready", self.adapter.probe("forge"))
        self.assertEqual("java_files_ready", self.adapter.probe("java"))
        self.assertIn(folder, self.fs.stats)

    def test_forge_selects_newest_bounded_candidate_without_reading_others(self):
        folder = self.forge("2.0.9")
        newest = folder / "forge-gui-desktop-2.0.15-decklab-fixture-jar-with-dependencies.jar"
        self.fs.file(newest, b"PK\x03\x04fixture")
        self.fs.children[folder] += [newest.name, "readme.txt", "unrelated.jar"]
        self.assertEqual("forge_files_ready", self.adapter.probe("forge"))
        self.assertEqual([(newest, 4), (self.scripts, 4)], self.fs.reads)

    def test_forge_missing_folder_jar_and_not_directory(self):
        folder = self.forge()
        del self.fs.nodes[folder]
        self.assertEqual("forge_missing", self.adapter.probe("forge"))
        self.fs.file(folder)
        self.assertEqual("forge_incomplete", self.adapter.probe("forge"))
        self.fs.nodes[folder].st_mode = stat.S_IFDIR
        self.fs.children[folder] = []
        self.assertEqual("forge_missing", self.adapter.probe("forge"))

    def test_forge_empty_missing_and_nonarchive_files_are_not_ready(self):
        self.forge()
        for path in (self.jar, self.scripts):
            with self.subTest(path=path):
                self.fs.file(path, b"")
                self.assertEqual("forge_incomplete", self.adapter.probe("forge"))
                self.fs.file(path, b"no archive")
                self.assertEqual("forge_invalid", self.adapter.probe("forge"))
                self.fs.file(path, b"PK\x03\x04fixture")
                del self.fs.nodes[path]
                self.assertEqual("forge_incomplete", self.adapter.probe("forge"))
                self.fs.file(path, b"PK\x03\x04fixture")

    def test_forge_listing_is_bounded_even_with_infinite_provider(self):
        folder = self.forge()
        names = mock.Mock(side_effect=lambda path: itertools.repeat(self.jar.name))
        adapter = optional.ForgeFiles(self.provider, self.root, stat_path=self.fs.stat,
                                      list_names=names, read_bytes=self.fs.read)
        self.assertEqual("forge_unavailable", adapter.probe("forge"))
        names.assert_called_once_with(folder)
        self.assertFalse(self.fs.reads)

    def test_unsafe_configured_paths_stop_before_any_filesystem_call(self):
        for value in ("\\\\host\\share\\private", "//host/share/private", "file:///private",
                      "https://example.com/private", "\\\\?\\C:\\private", "../private",
                      " bad", "bad ", "bad\x00file", "bad\nfile", "x" * 4097, b"bytes"):
            for ident, setting in (("java", "forge_java"), ("forge", "forge_dir")):
                with self.subTest(value=value, ident=ident):
                    self.provider.return_value = None
                    self.settings = {setting: value}
                    self.fs.stats.clear()
                    self.assertEqual(ident + "_unavailable", self.make_adapter().probe(ident))
                    self.assertFalse(self.fs.stats)

    def test_windows_device_paths_are_refused_before_any_filesystem_call(self):
        for value in ("NUL", "con.txt", "folder/COM1", "LPT9.log", "aux "):
            with self.subTest(value=value):
                self.settings = {"forge_dir": value}
                self.assertEqual("forge_unavailable", self.make_adapter(platform="nt").probe("forge"))
                self.assertFalse(self.fs.stats)

    def test_deep_configured_paths_are_bounded_before_stat(self):
        self.settings = {"forge_dir": str(Path(*(["nested"] * optional.MAX_PARTS)))}
        self.assertEqual("forge_unavailable", self.adapter.probe("forge"))
        self.assertFalse(self.fs.stats)

    def test_symlink_parents_and_leaves_are_never_read_or_listed(self):
        folder = self.forge()
        for path in (folder, folder.parent, self.jar, self.scripts.parent, self.scripts):
            with self.subTest(path=path):
                node = self.fs.nodes[path]
                old_mode = node.st_mode
                node.st_mode = stat.S_IFLNK
                self.fs.reads.clear()
                self.fs.lists.clear()
                self.assertEqual("forge_unavailable", self.adapter.probe("forge"))
                self.assertNotIn(path, [p for p, limit in self.fs.reads])
                if path in (folder, folder.parent):
                    self.assertFalse(self.fs.lists)
                    self.assertFalse(self.fs.reads)
                node.st_mode = old_mode

    def test_windows_reparse_parents_and_leaves_are_not_followed(self):
        folder = self.forge()
        for path in (folder, folder.parent, self.jar, self.scripts.parent, self.scripts):
            with self.subTest(path=path):
                self.fs.nodes[path].st_file_attributes = 0x400
                self.fs.reads.clear()
                self.assertEqual("forge_unavailable", self.make_adapter(platform="nt").probe("forge"))
                self.assertNotIn(path, [p for p, limit in self.fs.reads])
                self.fs.nodes[path].st_file_attributes = 0

    def test_java_runtime_and_release_links_never_read_target(self):
        runtime = self.java()
        for path in (runtime, runtime.parent, self.release):
            with self.subTest(path=path):
                node = self.fs.nodes[path]
                old_mode = node.st_mode
                node.st_mode = stat.S_IFLNK
                self.fs.reads.clear()
                expected = "java_version_unknown" if path == self.release else "java_unavailable"
                self.assertEqual(expected, self.adapter.probe("java"))
                self.assertFalse(self.fs.reads)
                node.st_mode = old_mode

    def test_generated_candidate_paths_reject_controls_before_read(self):
        folder = self.forge()
        self.fs.children[folder] = ["forge-gui-desktop-2.0.15\x00secret-jar-with-dependencies.jar"]
        self.assertEqual("forge_unavailable", self.adapter.probe("forge"))
        self.assertFalse(self.fs.reads)

    def test_provider_failures_are_fixed_codes_and_not_retried(self):
        self.provider.side_effect = OSError("private configured path user1@example.com")
        self.assertEqual("java_unavailable", self.adapter.probe("java"))
        self.assertEqual("forge_unavailable", self.adapter.probe("forge"))
        self.provider.assert_called_once_with()
        self.assertFalse(self.fs.stats)

    def test_nonmapping_config_is_unavailable_without_io(self):
        for value in (None, [], "private", 42):
            with self.subTest(value=value):
                self.provider.side_effect = None
                self.provider.return_value = value
                self.assertEqual("forge_unavailable", self.make_adapter().probe("forge"))
                self.assertFalse(self.fs.stats)

    def test_file_errors_stay_fixed_codes_and_interruptions_propagate(self):
        self.forge()
        self.fs.stat = mock.Mock(side_effect=PermissionError("private raw error"))
        adapter = self.make_adapter()
        self.assertEqual("forge_unavailable", adapter.probe("forge"))
        self.fs.stat.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            adapter.probe("forge")
        self.fs.stat.side_effect = SystemExit(73)
        with self.assertRaisesRegex(SystemExit, "73"):
            adapter.probe("forge")

    def test_unknown_check_id_is_rejected_without_io(self):
        with self.assertRaisesRegex(ValueError, "Unknown optional"):
            self.adapter.probe("private")
        self.provider.assert_not_called()
        self.assertFalse(self.fs.stats)

    def test_every_adapter_outcome_belongs_to_public_optional_catalog(self):
        self.java()
        self.forge()
        for ident in ("java", "forge"):
            code = self.adapter.probe(ident)
            self.assertIn(code, preflight.ALLOWED[ident])
        self.assertNotIn("simulation_execution", self.settings)


if __name__ == "__main__":
    unittest.main()
