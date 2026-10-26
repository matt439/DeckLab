"""CI change selection against disposable Git history, without network or live data."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import ci_changes


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci_changes.py"


class DocumentationPathsTests(unittest.TestCase):
    def test_only_known_documentation_paths_are_allowed(self):
        for name in (
            "README.md", "TODO.md", "AGENTS.md", "CLAUDE.md", "SELF-HOSTING.md",
            "decklab/HISTORY.md", "decklab/design/stories.md",
            "decklab/design/packing-chooser.svg", "decklab/forge-trial/logs.md",
            "decklab/safari/EVIDENCE.md", "decklab/fonts-licences/README.md",
            "decklab/lib/forge/overrides/README.md", "decklab/design/notes.rst",
        ):
            with self.subTest(name=name):
                self.assertTrue(ci_changes.is_documentation(name))
        for name in (
            "decklab/tests/fixtures/decks/casual/sample.md",
            "decklab/tests/fixtures/hand-edited-deck.md",
            "decklab/tests/fixtures/forge/cardlog-README.md",
            "decklab/design/fixtures/sample.md", "decklab/design/tests/README.md",
            "decklab/requirements.txt", "decklab/lib/forge/overrides/etb/sample.txt",
            "decklab/fonts-licences/figtree-OFL.txt", "LICENSE",
            "decklab/safari/card.jpg", "decklab/web/index.html",
            "decklab/web/icons/icon-32.png", "decklab/web/base.css",
            "decklab/web/README.md", "decklab/config.example.json",
            ".github/workflows/tests.yml", "scripts/ci_changes.py", "unknown/data.bin",
        ):
            with self.subTest(name=name):
                self.assertFalse(ci_changes.is_documentation(name))


@unittest.skipUnless(shutil.which("git"), "Git is required for isolated history tests")
class ChangeHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "CI Test")
        self.git("config", "user.email", "ci@example.com")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "commit.gpgsign", "false")
        self.write("README.md", "Initial documentation\n")
        self.first = self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.PIPE).decode().strip()

    def write(self, name, text="Changed\n"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", "Test changes")
        return self.git("rev-parse", "HEAD")

    def push(self, before, after):
        return {"before": before, "after": after}

    def run_selection(self, event_name, event=None, raw=None, missing=False):
        # Event/output files stay outside the test repository and its changed-file set.
        event_path = Path(self.temp.name) / "event.json"
        output_path = Path(self.temp.name) / "output.txt"
        if not missing:
            event_path.write_text(json.dumps(event) if raw is None else raw, encoding="utf-8")
        elif event_path.exists():
            event_path.unlink()
        output_path.write_text("existing=value\n", encoding="utf-8")
        env = dict(os.environ, GITHUB_EVENT_NAME=event_name,
                   GITHUB_EVENT_PATH=str(event_path), GITHUB_OUTPUT=str(output_path))
        result = subprocess.run([sys.executable, str(SCRIPT)], cwd=self.root, env=env,
                                text=True, capture_output=True, check=True)
        output = output_path.read_text(encoding="utf-8")
        self.assertIn(output, ("existing=value\nrun_tests=true\n", "existing=value\nrun_tests=false\n"))
        self.assertEqual(result.stderr, "")
        self.assertTrue(result.stdout.strip())
        return output.endswith("run_tests=true\n")

    def test_documentation_only_push_skips_suite_and_appends_cli_output(self):
        self.write("decklab/design/stories.md")
        self.write("README.md", "Updated documentation\n")
        self.assertFalse(self.run_selection("push", self.push(self.first, self.commit())))

    def test_pull_request_uses_merge_base_instead_of_target_branch_tip(self):
        self.git("checkout", "-q", "-b", "feature")
        self.write("TODO.md")
        feature = self.commit()
        self.git("checkout", "-q", "--detach", self.first)
        self.write("decklab/server.py", "VERSION = 2\n")
        target = self.commit()
        event = {"pull_request": {"base": {"sha": target}, "head": {"sha": feature}}}
        self.assertFalse(self.run_selection("pull_request", event))
        self.assertTrue(self.run_selection("push", self.push(target, feature)))

    def test_push_checks_all_commits_in_the_pushed_range(self):
        self.write("decklab/server.py", "VERSION = 2\n")
        code_commit = self.commit()
        self.write("TODO.md")
        latest = self.commit()
        self.assertFalse(self.run_selection("push", self.push(code_commit, latest)))
        self.assertTrue(self.run_selection("push", self.push(self.first, latest)))

    def test_deletions_and_rename_keep_the_original_functional_path(self):
        fixture = "decklab/tests/fixtures/decks/casual/sample.md"
        self.write(fixture, "A functional Markdown fixture\n")
        base = self.commit()
        (self.root / "README.md").unlink()
        docs_deleted = self.commit()
        self.assertFalse(self.run_selection("push", self.push(base, docs_deleted)))
        self.git("mv", fixture, "moved.md")
        renamed = self.commit()
        self.assertTrue(self.run_selection("push", self.push(docs_deleted, renamed)))
        self.git("mv", "moved.md", fixture)
        moved_back = self.commit()
        self.assertTrue(self.run_selection("push", self.push(renamed, moved_back)))
        (self.root / fixture).unlink()
        self.assertTrue(self.run_selection("push", self.push(moved_back, self.commit())))

    def test_functional_text_assets_workflow_and_unknown_paths_run_suite(self):
        before = self.first
        for name in (
            "decklab/requirements.txt", "decklab/lib/forge/overrides/etb/sample.txt",
            "decklab/tests/fixtures/hand-edited-deck.md", "decklab/safari/card.jpg",
            "decklab/web/base.css", ".github/workflows/tests.yml", "new-folder/unknown.md",
        ):
            with self.subTest(name=name):
                self.write(name)
                after = self.commit()
                self.assertTrue(self.run_selection("push", self.push(before, after)))
                before = after

    def test_missing_zero_invalid_and_unavailable_history_run_suite(self):
        for event in (
            {}, None, [], {"before": self.first},
            self.push("0" * 40, self.first), self.push(self.first, "0" * 40),
            self.push("not-a-revision", self.first), self.push(self.first, 123),
            self.push("f" * 40, self.first), self.push(self.first, "f" * 40),
        ):
            with self.subTest(event=event):
                self.assertTrue(self.run_selection("push", event))
        self.assertTrue(self.run_selection("pull_request", {"pull_request": {"base": {"sha": self.first}}}))

    def test_empty_comparison_runs_suite_even_with_a_new_commit(self):
        self.assertTrue(self.run_selection("push", self.push(self.first, self.first)))
        self.assertTrue(self.run_selection("push", self.push(self.first, self.commit())))

    def test_more_than_300_changed_paths_do_not_hide_code(self):
        for number in range(305):
            self.write(f"note-{number:03}.md")
        docs = self.commit()
        self.assertFalse(self.run_selection("push", self.push(self.first, docs)))
        self.write("decklab/server.py", "VERSION = 2\n")
        self.assertTrue(self.run_selection("push", self.push(self.first, self.commit())))

    def test_schedule_manual_and_unknown_events_always_run_suite(self):
        for event_name in ("schedule", "workflow_dispatch", "unknown", ""):
            with self.subTest(event_name=event_name):
                self.assertTrue(self.run_selection(event_name, missing=True))

    def test_unreadable_or_malformed_event_payload_runs_suite(self):
        self.assertTrue(self.run_selection("push", missing=True))
        for raw in ("{broken", "null", "[]", '"unexpected"'):
            with self.subTest(raw=raw):
                self.assertTrue(self.run_selection("push", raw=raw))


if __name__ == "__main__":
    unittest.main()
