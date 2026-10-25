"""Running-version tests use isolated checkouts; they never edit this repo."""

import os
import shutil
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from decklab.lib import build


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout.decode().strip()


@unittest.skipUnless(shutil.which("git"), "Git is required for isolated checkout tests")
class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Build Test")
        git(self.root, "config", "user.email", "build@example.invalid")
        git(self.root, "config", "core.autocrlf", "false")
        self.write("decklab/server.py", "SERVER = 1\n")
        self.write("decklab/lib/api.py", "API = 1\n")
        self.write("decklab/lib/forge/java/DeckLabSim.java", "class DeckLabSim {}\n")
        self.write("decklab/config.json", '{"port": 8642}\n')
        self.write("decklab/web/index.html", "<h1>Deck Lab</h1>\n")
        self.write("decklab/web/app.js", "const version = 1;\n")
        self.write("magic/collection.csv", "name,quantity\n")
        self.first = self.commit()
        for name, value in {"_root": None, "_running": None, "_latest": None,
                            "_started_at": None, "_checked_at": 0.0, "CACHE_SECONDS": 0.0}.items():
            patch = mock.patch.object(build, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())

    def commit(self):
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "test changes")
        return git(self.root, "rev-parse", "HEAD")

    def test_status_before_start_does_not_capture_checkout(self):
        with mock.patch.object(build, "_snapshot") as snapshot:
            result = build.status()
        snapshot.assert_not_called()
        self.assertIsNone(result["running_commit"])
        self.assertIsNone(result["restart_required"])
        self.assertIn("startup", result["error"])

    def test_clean_start_and_repeated_start_keep_baseline(self):
        build.start(self.root)
        original = build.status()
        self.assertEqual(original["running_commit"], self.first)
        self.assertEqual(original["latest_commit"], self.first)
        self.assertIs(original["running_dirty"], False)
        self.assertIs(original["code_changed"], False)
        self.write("decklab/lib/api.py", "API = 2\n")
        latest = self.commit()
        build.start(self.root)
        result = build.status()
        self.assertEqual(result["running_commit"], self.first)
        self.assertEqual(result["latest_commit"], latest)
        self.assertEqual(result["started_at"], original["started_at"])
        self.assertIs(result["restart_required"], True)
        self.assertIs(result["assets_changed"], False)

    def test_data_docs_tests_and_cache_commits_do_not_require_restart(self):
        build.start(self.root)
        for path in ("magic/collection.csv", "magic/decks/casual/my-deck.md", "magic/orders/order.csv",
                     "decklab/README.md", "decklab/tests/test_server.py", "decklab/data/cache.json",
                     "decklab/lib/docs/notes.md", "decklab/web/README.md"):
            self.write(path, "new data\n")
        latest = self.commit()
        result = build.status()
        self.assertNotEqual(result["running_commit"], latest)
        self.assertEqual(result["latest_commit"], latest)
        self.assertIs(result["latest_dirty"], False)
        self.assertIs(result["restart_required"], False)
        self.assertIs(result["code_changed"], False)

    def test_dirty_start_stays_immutable_when_same_changes_are_committed(self):
        self.write("decklab/server.py", "SERVER = 2\n")
        build.start(self.root)
        latest = self.commit()
        result = build.status()
        self.assertEqual(result["running_commit"], self.first)
        self.assertEqual(result["latest_commit"], latest)
        self.assertIs(result["running_dirty"], True)
        self.assertIs(result["latest_dirty"], False)
        self.assertIs(result["code_changed"], False)

    def test_uncommitted_runtime_change_and_revert(self):
        build.start(self.root)
        self.write("decklab/lib/api.py", "API = 2\n")
        result = build.status()
        self.assertEqual(result["latest_commit"], self.first)
        self.assertIs(result["latest_dirty"], True)
        self.assertIs(result["restart_required"], True)
        self.write("decklab/lib/api.py", "API = 1\n")
        self.assertIs(build.status()["restart_required"], False)

    def test_untracked_runtime_and_deleted_runtime_are_detected(self):
        build.start(self.root)
        self.write("decklab/lib/new.py", "NEW = True\n")
        self.assertIs(build.status()["restart_required"], True)
        self.assertIs(build.status()["latest_dirty"], True)
        (self.root / "decklab/lib/new.py").unlink()
        (self.root / "decklab/lib/api.py").unlink()
        self.assertIs(build.status()["restart_required"], True)
        self.assertIs(build.status()["latest_dirty"], True)

    def test_gitignored_config_is_not_dirty_but_still_needs_restart(self):
        git(self.root, "rm", "-q", "--cached", "decklab/config.json")
        self.write(".gitignore", "decklab/config.json\n")
        self.commit()
        build.start(self.root)
        result = build.status()
        self.assertIs(result["running_dirty"], False)
        self.assertIs(result["latest_dirty"], False)
        self.write("decklab/config.json", '{"port": 8643}\n')
        result = build.status()
        self.assertIs(result["latest_dirty"], False)
        self.assertIs(result["restart_required"], True)
        self.write("decklab/lib/new.py", "NEW = True\n")
        self.assertIs(build.status()["latest_dirty"], True)

    def test_config_and_java_dependencies_are_detected(self):
        build.start(self.root)
        for path, original in (("decklab/config.json", '{"port": 8642}\n'),
                               ("decklab/lib/forge/java/DeckLabSim.java", "class DeckLabSim {}\n")):
            with self.subTest(path=path):
                self.write(path, original + "\n")
                self.assertIs(build.status()["restart_required"], True)
                self.write(path, original)
                self.assertIs(build.status()["restart_required"], False)

    def test_database_code_counts_but_its_migrations_dont(self):
        # The server imports decklab.db (the state store and dbstatus); a migration is applied
        # by `python -m decklab.db migrate`, never by a restart.
        self.write("decklab/db/conn.py", "CONN = 1\n")
        self.write("decklab/db/migrations/0001_foundation.sql", "select 1;\n")
        self.commit()
        build.start(self.root)
        self.assertIs(build.status()["restart_required"], False)
        self.write("decklab/db/migrations/0002_more.sql", "select 2;\n")
        self.assertIs(build.status()["restart_required"], False)
        self.assertIs(build.status()["latest_dirty"], False)
        self.write("decklab/db/conn.py", "CONN = 2\n")
        self.assertIs(build.status()["restart_required"], True)
        self.assertIs(build.status()["latest_dirty"], True)

    def test_web_change_is_refresh_only_and_direct_marker_bypasses_cache(self):
        build.start(self.root)
        original = build.status()
        with mock.patch.object(build, "CACHE_SECONDS", 1000):
            self.write("decklab/web/app.js", "const version = 2;\n")
            with mock.patch.object(build, "_git", side_effect=AssertionError("Web marker must not run Git")):
                fresh_marker = build.web_revision()
                cached_runtime = build.status()
            self.assertNotEqual(fresh_marker, original["web_revision"])
            self.assertEqual(cached_runtime["web_revision"], fresh_marker)
            self.assertIs(cached_runtime["assets_changed"], True)
            self.assertIs(cached_runtime["code_changed"], True)
            self.assertIs(cached_runtime["restart_required"], False)
        result = build.status()
        self.assertIs(result["restart_required"], False)
        self.assertIs(result["assets_changed"], True)
        self.assertIs(result["code_changed"], True)
        self.assertEqual(result["web_revision"], fresh_marker)
        self.assertEqual(result["running_web_revision"], original["web_revision"])

    def test_added_and_removed_web_assets_change_revision(self):
        build.start(self.root)
        initial = build.web_revision()
        self.write("decklab/web/new.js", "newFunction();\n")
        self.assertNotEqual(build.web_revision(), initial)
        self.assertIs(build.status()["assets_changed"], True)
        (self.root / "decklab/web/new.js").unlink()
        (self.root / "decklab/web/app.js").unlink()
        self.assertNotEqual(build.web_revision(), initial)

    def test_missing_git_is_unknown_not_current_and_start_cannot_recapture(self):
        with mock.patch.object(build.subprocess, "run", side_effect=FileNotFoundError):
            build.start(self.root)
            result = build.status()
        self.assertIsNone(result["running_commit"])
        self.assertIsNone(result["code_changed"])
        self.assertIsNone(result["restart_required"])
        self.assertIn("Git", result["error"])
        build.start(self.root)
        result = build.status()
        self.assertEqual(result["latest_commit"], self.first)
        self.assertIsNone(result["running_commit"])
        self.assertIsNone(result["restart_required"])

    def test_git_error_after_start_never_reports_cached_current(self):
        build.start(self.root)
        with mock.patch.object(build.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 2)):
            result = build.status()
        self.assertEqual(result["running_commit"], self.first)
        self.assertIsNone(result["latest_commit"])
        self.assertIsNone(result["restart_required"])
        self.assertIn("too long", result["error"])

    def test_cache_is_shared_between_concurrent_readers_and_returns_copies(self):
        build.start(self.root)
        with mock.patch.object(build, "CACHE_SECONDS", 5), mock.patch.object(build, "_checked_at", -100), \
                mock.patch.object(build, "_snapshot", wraps=build._snapshot) as snapshot:
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(lambda _: build.status(), range(16)))
        self.assertEqual(snapshot.call_count, 1)
        results[0]["running_commit"] = "changed by caller"
        self.assertEqual(results[1]["running_commit"], self.first)

    def test_source_read_failure_is_unknown(self):
        build.start(self.root)
        with mock.patch.object(build, "_fingerprints", side_effect=PermissionError("private local path")):
            result = build.status()
            self.assertIsNone(build.web_revision())
        self.assertIsNone(result["restart_required"])
        self.assertNotIn("private local path", result["error"])

    def test_web_read_failure_does_not_claim_current_from_status_cache(self):
        build.start(self.root)
        with mock.patch.object(build, "CACHE_SECONDS", 1000), \
                mock.patch.object(build, "_fingerprints", side_effect=PermissionError("private local path")):
            result = build.status()
        self.assertIsNone(result["web_revision"])
        self.assertIsNone(result["assets_changed"])
        self.assertIsNone(result["code_changed"])
        self.assertIs(result["restart_required"], False)
        self.assertIn("Web assets", result["error"])

    def test_git_reads_disable_locks_and_hide_windows_console(self):
        with mock.patch.object(build.subprocess, "run", wraps=build.subprocess.run) as run:
            build.start(self.root)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")
            self.assertEqual(call.kwargs["timeout"], build.GIT_TIMEOUT)
            self.assertEqual(call.kwargs["stdin"], subprocess.DEVNULL)
            if os.name == "nt":
                self.assertEqual(call.kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    unittest.main()
