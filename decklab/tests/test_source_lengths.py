"""The source-length guard against disposable Git repositories, without app data."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import audit_source_lengths


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit_source_lengths.py"


@unittest.skipUnless(shutil.which("git"), "Git is required for isolated source-inventory tests")
class SourceLengthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.PIPE)

    def write(self, name, lines=1201, *, trailing_newline=True, encoding="utf-8"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join("// Source line" for _ in range(lines))
        path.write_text(text + ("\n" if trailing_newline else ""), encoding=encoding)
        return path

    def inventory(self):
        with patch.object(audit_source_lengths, "ROOT", self.root):
            return audit_source_lengths.inventory()

    def run_audit(self, *args):
        script = self.root / "scripts" / "audit_source_lengths.py"
        script.parent.mkdir(exist_ok=True)
        script.write_bytes(SCRIPT.read_bytes())
        # ROOT comes from the script's location, not the caller's working directory.
        return subprocess.run([sys.executable, str(script), *args], cwd=self.temp.name,
                              text=True, capture_output=True)

    def test_check_accepts_1200_lines_and_rejects_1201(self):
        self.write("boundary.js", 1200, trailing_newline=False, encoding="utf-8-sig")
        accepted = self.run_audit("--check")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("0 exceed 1,200 lines.", accepted.stdout)
        self.write("boundary.js", 1201, trailing_newline=False, encoding="utf-8-sig")
        refused = self.run_audit("--check")
        self.assertEqual(refused.returncode, 1, refused.stderr)
        self.assertIn("1 exceed 1,200 lines.", refused.stdout)
        self.assertIn("1201  boundary.js", refused.stdout)

    def test_report_only_lists_excess_without_failing(self):
        self.write("long.py")
        result = self.run_audit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 exceed 1,200 lines.", result.stdout)
        self.assertIn("1201  long.py", result.stdout)

    def test_tracked_and_untracked_sources_use_current_contents_once(self):
        self.write("tracked.py", 1)
        self.git("add", "tracked.py")
        self.write("tracked.py", 1201)
        self.write("untracked.js", 1200)
        owned, upstream = self.inventory()
        self.assertEqual(owned, [(1201, "tracked.py"), (1200, "untracked.js")])
        self.assertEqual(upstream, [])

    def test_ignored_untracked_cache_is_skipped_but_tracked_source_is_kept(self):
        self.write("tracked.py")
        self.git("add", "tracked.py")
        (self.root / ".gitignore").write_text("cache/\ntracked.py\n", encoding="utf-8")
        self.write("cache/download.js", 3000)
        owned, upstream = self.inventory()
        self.assertEqual(owned, [(1201, "tracked.py")])
        self.assertEqual(upstream, [])

    def test_only_pinned_upstream_directory_is_excluded_from_failure(self):
        upstream_name = "decklab/lib/forge/java/forge/AiController.java"
        self.write(upstream_name, 3000)
        owned, upstream = self.inventory()
        self.assertEqual(owned, [])
        self.assertEqual(upstream, [(3000, upstream_name)])
        result = self.run_audit("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Excluded pinned upstream Forge copies:", result.stdout)
        self.assertIn(upstream_name, result.stdout)
        neighbour = "decklab/lib/forge/java/forge-extra/AiController.java"
        self.write(neighbour)
        result = self.run_audit("--check")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("1 exceed 1,200 lines.", result.stdout)
        self.assertIn(neighbour, result.stdout)

    def test_all_owned_source_types_are_included(self):
        names = ["module.py", "page.js", "style.css", "index.html", "Main.java", "helper.ps1"]
        for name in names:
            self.write(name, 1201)
        owned, upstream = self.inventory()
        self.assertEqual(sorted(owned), [(1201, name) for name in sorted(names)])
        self.assertEqual(upstream, [])

    def test_non_sources_and_deleted_tracked_files_are_skipped(self):
        removed = self.write("removed.py")
        self.git("add", "removed.py")
        removed.unlink()
        for name in ("notes.md", "records.csv", "config.json", "image.png"):
            self.write(name, 3000)
        self.assertEqual(self.inventory(), ([], []))


if __name__ == "__main__":
    unittest.main()
