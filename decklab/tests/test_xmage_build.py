"""Bridge discovery is read-only and rejects changed engine/source/artifacts (no Java)."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.xmage import build as compile_bridge, describe
import importlib

bridge = importlib.import_module("decklab.xmage.build")


class XMageJavaSelectionTests(unittest.TestCase):
    def test_configured_forge_jdk_is_used_when_no_override_is_supplied(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder) / "java"
            with mock.patch("decklab.lib.config.load", return_value={"forge_java": str(runtime)}), \
                    mock.patch("decklab.lib.forge.install.find_java", return_value=runtime) as find:
                self.assertEqual(bridge._java(), runtime.resolve())
            find.assert_called_once_with(str(runtime))

    def test_explicit_java_override_takes_precedence_over_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder) / "java"
            with mock.patch("decklab.lib.config.load", side_effect=AssertionError("explicit override")), \
                    mock.patch("decklab.lib.forge.install.find_java", return_value=runtime) as find:
                self.assertEqual(bridge._java(str(runtime)), runtime.resolve())
            find.assert_called_once_with(str(runtime))


class XMageBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.java = self.root / "jdk" / "bin" / "java"
        self.java.parent.mkdir(parents=True)
        self.java.write_bytes(b"fixture java")
        (self.java.parent.parent / "release").write_bytes(b"fixture Java release")
        self.home = self.root / "release" / "xmage" / "mage-server"
        (self.home / "lib").mkdir(parents=True)
        (self.home / "plugins").mkdir()
        (self.home / "lib" / "mage-1.4.63.jar").write_bytes(b"fixture engine")
        self.output = self.root / "bridge"
        self.output.mkdir()
        (self.output / "decklab-xmage.jar").write_bytes(b"fixture bridge")
        self.engine_sha = bridge._engine_sha(self.home)
        self.metadata = {"schema": 1, "home": str(self.home.resolve()),
                         "engine_sha256": self.engine_sha,
                         "source_sha256": bridge._sha(bridge.JAVA_SOURCE),
                         "bridge_sha256": bridge._sha(self.output / "decklab-xmage.jar")}
        self._write_metadata()
        self.pinned = mock.patch.object(bridge, "ENGINE_SHA256", self.engine_sha)
        self.pinned.start()
        self.addCleanup(self.pinned.stop)
        self.runtime = mock.patch.object(bridge, "_java", return_value=self.java)
        self.runtime.start()
        self.addCleanup(self.runtime.stop)

    def _write_metadata(self):
        (self.output / "command.json").write_text(json.dumps(self.metadata), encoding="utf-8")

    def test_unconfigured_never_builds_or_starts_a_process(self):
        with mock.patch("decklab.lib.config.load", return_value={"xmage_dir": None}), \
                mock.patch.object(bridge, "_build_dir", side_effect=AssertionError("no build")), \
                mock.patch.object(bridge.subprocess, "run", side_effect=AssertionError("no process")):
            result = describe()
        self.assertFalse(result["ready"])
        self.assertNotIn("command", result)

    def test_default_uses_configured_release_without_launching(self):
        with mock.patch("decklab.lib.config.load", return_value={"xmage_dir": str(self.home)}), \
                mock.patch.object(bridge.subprocess, "run", side_effect=AssertionError("no process")):
            self.assertTrue(describe(build_dir=self.output)["ready"])

    def test_installed_identity_builds_a_direct_bounded_headless_command(self):
        with mock.patch.object(bridge.subprocess, "run", side_effect=AssertionError("no process")):
            result = describe(self.root / "release", build_dir=self.output)
        self.assertTrue(result["ready"])
        self.assertEqual(result["engine_sha256"], self.engine_sha)
        self.assertIn("-Xmx1024m", result["command"])
        self.assertIn("-Djava.awt.headless=true", result["command"])
        self.assertEqual(result["command"][-1], "decklab.xmage.Bridge")
        self.assertFalse(result["reproducible"])

    def test_runtime_identity_changes_with_jdk_bytes_and_rules(self):
        before = describe(self.home, build_dir=self.output)
        self.java.write_bytes(b"another Java build")
        after = describe(self.home, build_dir=self.output)
        self.assertNotEqual(before["identity_sha256"], after["identity_sha256"])
        self.assertEqual(before["engine_sha256"], after["engine_sha256"])
        with mock.patch.object(bridge, "RUNTIME_POLICY", "changed rules"):
            changed = describe(self.home, build_dir=self.output)
        self.assertNotEqual(after["identity_sha256"], changed["identity_sha256"])

    def test_boolean_metadata_schema_is_refused(self):
        self.metadata["schema"] = True
        self._write_metadata()
        self.assertFalse(describe(self.home, build_dir=self.output)["ready"])

    def test_changed_engine_and_extra_jar_are_refused(self):
        for kind in ("changed", "extra", "extra-uppercase"):
            with self.subTest(kind=kind):
                name = "mage-1.4.63.jar" if kind == "changed" else "extra.JAR" if kind == "extra-uppercase" else "extra.jar"
                target = self.home / "lib" / name
                before = target.read_bytes() if target.exists() else None
                target.write_bytes(b"unexpected")
                self.assertFalse(describe(self.home, build_dir=self.output)["ready"])
                if before is None:
                    target.unlink()
                else:
                    target.write_bytes(before)

    def test_changed_bridge_source_or_artifact_is_refused_without_rebuild(self):
        original = bridge._sha
        with mock.patch.object(bridge, "_sha", wraps=original) as digest:
            digest.side_effect = lambda path: ("0" * 64 if path == bridge.JAVA_SOURCE else original(path))
            self.assertFalse(describe(self.home, build_dir=self.output)["ready"])
        (self.output / "decklab-xmage.jar").write_bytes(b"tampered")
        self.assertFalse(describe(self.home, build_dir=self.output)["ready"])

    def test_metadata_cannot_supply_an_arbitrary_launch_command(self):
        self.metadata["command"] = ["unexpected-executable"]
        self._write_metadata()
        result = describe(self.home, build_dir=self.output)
        self.assertTrue(result["ready"])
        self.assertNotIn("unexpected-executable", result["command"])

    def test_wrong_home_and_invalid_metadata_fail_closed(self):
        self.metadata["home"] = "elsewhere"
        self._write_metadata()
        self.assertFalse(describe(self.home, build_dir=self.output)["ready"])
        (self.output / "command.json").write_text("[]", encoding="utf-8")
        self.assertFalse(describe(self.home, build_dir=self.output)["ready"])

    def test_build_rejects_unpinned_engine_before_spawning_compiler(self):
        (self.home / "lib" / "mage-1.4.63.jar").write_bytes(b"changed")
        with mock.patch.object(bridge.subprocess, "run", side_effect=AssertionError("no compiler")):
            with self.assertRaises(ValueError):
                compile_bridge(self.home, build_dir=self.output)

    def test_engine_fingerprint_is_sorted_and_contains_names_and_bytes(self):
        expected = hashlib.sha256(("lib/mage-1.4.63.jar\0" + hashlib.sha256(b"fixture engine").hexdigest()
                                   + "\n").encode()).hexdigest()
        self.assertEqual(bridge._engine_sha(self.home), expected)


if __name__ == "__main__":
    unittest.main()
