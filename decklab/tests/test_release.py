"""Release zips and installs without git (E11-S49): scripts/make_release.py and build.py's manifest.

Every install is a temporary folder; the zip test packages this checkout's HEAD with git archive,
into a temporary folder. Nothing is published and no network is used.
"""
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from decklab.lib import build

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("make_release", REPO / "scripts" / "make_release.py")
make_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_release)
COMMIT = "a" * 40
FILES = {"decklab/server.py": (b"print('server')\n", 0o644), "decklab/lib/thing.py": (b"X = 1\n", 0o644),
         "decklab/web/app.js": (b"'use strict';\n", 0o644), "decklab/db/migrations/0001_first.sql": (b"select 1;\n", 0o644),
         "README.md": (b"# Deck Lab\n", 0o644), ".github/workflows/tests.yml": (b"name: tests\n", 0o644)}


def _git_works():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True).returncode == 0
    except OSError:
        return False


class ReleaseInstallTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="decklab-release-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name, (data, _) in FILES.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.info = make_release.manifest("1.2.0", COMMIT, FILES, "2026-11-04T00:00:00+00:00")
        (self.root / build.MANIFEST).write_text(json.dumps(self.info), encoding="utf-8")

    def test_the_manifest_lists_version_commit_migrations_and_fingerprints(self):
        self.assertEqual(set(self.info), build.MANIFEST_KEYS)
        self.assertEqual((self.info["version"], self.info["commit"], self.info["migrations"]),
                         ("1.2.0", COMMIT, ["0001_first.sql"]))
        self.assertEqual({"runtime": self.info["runtime"], "web": self.info["web"]}, build._fingerprints(self.root)[0])

    def test_an_unchanged_release_reads_its_version_without_git(self):
        self.assertTrue(build.is_release(self.root))
        found = build._snapshot(self.root)
        self.assertEqual((found.version, found.commit, found.dirty, found.error), ("1.2.0", COMMIT, False, None))

    def test_a_changed_file_counts_as_a_local_change(self):
        (self.root / "decklab" / "lib" / "thing.py").write_bytes(b"X = 2\n")
        found = build._snapshot(self.root)
        self.assertEqual((found.version, found.dirty), ("1.2.0", True))
        (self.root / "decklab" / "lib" / "thing.py").write_bytes(b"X = 1\r\n")     # CRLF is the same source
        self.assertFalse(build._snapshot(self.root).dirty)

    def test_a_bad_or_missing_manifest_is_unverified(self):
        for text in ("not json", json.dumps({**self.info, "version": "one"}), json.dumps({**self.info, "extra": 1}),
                     json.dumps({**self.info, "web": "x"})):
            with self.subTest(text=text):
                (self.root / build.MANIFEST).write_text(text, encoding="utf-8")
                found = build._snapshot(self.root)
                self.assertIsNone(found.dirty)
                self.assertIn("release.json", found.error)
        (self.root / build.MANIFEST).unlink()
        self.assertFalse(build.is_release(self.root))

    def test_a_git_checkout_never_reads_the_manifest(self):
        (self.root / ".git").mkdir()
        self.assertFalse(build.is_release(self.root))
        self.assertIsNone(build._snapshot(self.root).version)

    def test_the_zip_puts_everything_under_its_folder_with_the_manifest(self):
        path = self.root / "out.zip"
        make_release.write_zip(path, "1.2.0", {k: v for k, v in FILES.items() if not k.startswith(".github/")},
                               self.info, make_release.datetime(2026, 11, 4, tzinfo=make_release.timezone.utc))
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            self.assertTrue(all(name.startswith("decklab-1.2.0/") for name in names))
            self.assertIn("decklab-1.2.0/decklab/release.json", names)
            self.assertEqual(json.loads(archive.read("decklab-1.2.0/decklab/release.json")), self.info)
            self.assertEqual({item.date_time for item in archive.infolist()}, {(2026, 11, 4, 0, 0, 0)})

    def test_bad_versions_are_refused(self):
        for version in ("1.2", "one", "1.2.0 beta", "1.2.0/x"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                make_release.make(version, out=self.root)


@unittest.skipUnless(_git_works() and shutil.which("git"), "needs this checkout's git")
class MakeReleaseTests(unittest.TestCase):
    def test_head_makes_a_matching_zip_sha_and_manifest_twice_the_same(self):
        with tempfile.TemporaryDirectory(prefix="decklab-release-out-") as folder:
            first = make_release.make("v0.0.1", out=Path(folder) / "a")
            second = make_release.make("0.0.1", out=Path(folder) / "b")
            archive, checksum, listed = first
            self.assertEqual([p.name for p in first], ["decklab-0.0.1.zip", "decklab-0.0.1.zip.sha256", "decklab-0.0.1.json"])
            self.assertEqual(archive.read_bytes(), second[0].read_bytes())
            digest = make_release.hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual(checksum.read_text(encoding="utf-8"), f"{digest}  decklab-0.0.1.zip\n")
            info = json.loads(listed.read_text(encoding="utf-8"))
            self.assertEqual(info["commit"], make_release._git("rev-parse", "HEAD"))
            with zipfile.ZipFile(archive) as opened:
                names = set(opened.namelist())
                self.assertEqual(json.loads(opened.read("decklab-0.0.1/decklab/release.json")), info)
                self.assertFalse({n for n in names if "/.github/" in n or n.endswith("/decklab/config.json")})
                self.assertIn("decklab-0.0.1/decklab/config.example.json", names)
                install = Path(folder) / "install"
                opened.extractall(install)
            found = build._snapshot(install / "decklab-0.0.1")
            self.assertEqual((found.version, found.commit, found.dirty, found.error), ("0.0.1", info["commit"], False, None))


if __name__ == "__main__":
    unittest.main()
