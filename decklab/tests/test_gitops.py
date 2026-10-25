"""Tests for decklab.lib.gitops: the read-only git queries a .dck file's Forge provenance uses.

Every test runs git in a repository of its own, made with git init in a temp
folder (gitops is always given that folder, so the real repo is never
touched). A few tests stand in for git itself to make it missing or slow.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import gitops


def git(root, *args):
    """Run git in root for the test itself (not through gitops); stdout as text."""
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)
    return done.stdout.decode("utf-8")


_template = None


def setUpModule():
    global _template
    _template = _new_repo()


def tearDownModule():
    shutil.rmtree(_template, True)


def make_repo():
    """A copy of the module's template repo: one commit of decks/a.md and
    decks/b.md (copying is quicker than git init)."""
    root = Path(tempfile.mkdtemp())
    shutil.copytree(_template, root, dirs_exist_ok=True)
    return root


def _new_repo():
    root = Path(tempfile.mkdtemp())
    git(root, "init", "-q")
    git(root, "config", "user.name", "Test Person")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "core.autocrlf", "false")
    (root / "decks").mkdir()
    for name in ("a.md", "b.md"):
        (root / "decks" / name).write_bytes(f"{name}\n".encode())
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "first")
    return root


class GitTestCase(unittest.TestCase):

    def setUp(self):
        self.root = make_repo()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.a, self.b = self.root / "decks" / "a.md", self.root / "decks" / "b.md"

    def assertGitError(self, kind, call, *args, contains=None):
        with self.assertRaises(gitops.GitError) as caught:
            call(*args)
        self.assertEqual(caught.exception.kind, kind, str(caught.exception))
        if contains:
            self.assertIn(contains, str(caught.exception))
        return caught.exception


class StatusTests(GitTestCase):

    def test_clean_modified_staged_and_untracked(self):
        new = self.root / "decks" / "new.md"
        new.write_bytes(b"new\n")
        self.b.write_bytes(b"b staged\n")
        git(self.root, "add", "decks/b.md")
        self.assertEqual(gitops.status([self.a, self.b, new], self.root),
                         {"decks/b.md": "M ", "decks/new.md": "??"})
        self.a.write_bytes(b"a changed\n")
        self.assertEqual(gitops.status([self.a], self.root), {"decks/a.md": " M"})

    def test_relative(self):
        self.assertEqual(gitops.relative(self.a, self.root), "decks/a.md")
        self.assertEqual(gitops.relative("decks/b.md", self.root), "decks/b.md")

    def test_run_reads_the_last_commit(self):
        done = gitops.run(["log", "-1", "--format=%H", "--", "decks/a.md"], self.root, check=False)
        self.assertEqual((done.returncode, done.stdout.strip()),
                         (0, git(self.root, "rev-parse", "HEAD").strip()))


class FailureTests(GitTestCase):

    def test_not_a_repository(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "x.md").write_bytes(b"x\n")
        self.assertGitError("not_repo", gitops.status, [root / "x.md"], root)

    def test_a_missing_folder(self):
        self.assertGitError("not_repo", gitops.run, ["status"], self.root / "no-such-folder")

    def test_a_path_outside_the_repo(self):
        self.assertGitError("outside", gitops.status, [self.root.parent / "elsewhere.md"], self.root)

    def test_git_missing(self):
        with mock.patch.object(gitops.subprocess, "Popen", side_effect=FileNotFoundError("git")):
            error = self.assertGitError("missing", gitops.status, [self.a], self.root)
        self.assertIn("isn't installed", str(error))

    def test_a_failed_command_quotes_git(self):
        error = self.assertGitError("failed", gitops.run, ["log", "no-such-rev"], self.root)
        self.assertTrue(str(error).startswith("git log failed: "), str(error))
        self.assertFalse(str(error).endswith("."))
        done = gitops.run(["log", "no-such-rev"], self.root, check=False)
        self.assertNotEqual(done.returncode, 0)

    def test_git_runs_without_a_prompt_from_the_repo_root(self):
        calls = []
        real = subprocess.Popen

        def spy(args, **kwargs):
            calls.append((args, kwargs))
            return real(args, **kwargs)

        with mock.patch.object(gitops.subprocess, "Popen", side_effect=spy):
            gitops.status([self.a], self.root)
        self.assertTrue(calls)
        for args, kwargs in calls:
            self.assertEqual(Path(kwargs["cwd"]), self.root.resolve())
            self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")
            self.assertEqual(kwargs["env"]["GIT_LITERAL_PATHSPECS"], "1")
            self.assertEqual(kwargs["env"]["GIT_CEILING_DIRECTORIES"], str(self.root.resolve().parent))
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertIn("decks/a.md", args)                                 # relative paths


class TimeoutTests(GitTestCase):
    """A git command that runs over TIMEOUT is stopped, so a stuck git can't
    hold a page or a Forge request up."""

    def test_a_slow_git_is_stopped(self):
        slow = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (slow.kill(), slow.wait()))
        with mock.patch.object(gitops, "TIMEOUT", 0.5), \
                mock.patch.object(gitops.subprocess, "Popen", return_value=slow), \
                mock.patch.object(gitops, "_stop", side_effect=lambda proc: (proc.kill(), proc.wait())) as stop:
            error = self.assertGitError("timeout", gitops.status, [self.a], self.root)
        stop.assert_called_once_with(slow)
        self.assertIn("didn't finish within", str(error))


class ErrorTextTests(GitTestCase):
    """What a failed command says: without line-ending warnings or the repo's
    folder, and with no final full stop."""

    def test_locked(self):
        done = subprocess.CompletedProcess(["git", "status"], 128, "",
                                           "fatal: Unable to create '.git/index.lock': File exists.\n")
        self.assertEqual(gitops._describe(done, self.root.resolve()).kind, "locked")

    def test_noise_and_the_repo_folder_are_left_out(self):
        root = self.root.resolve()
        done = subprocess.CompletedProcess(
            ["git", "status"], 1, "",
            f"warning: in the working copy of 'decks/a.md', LF will be replaced by CRLF\n"
            f"hint: try again\nfatal: something odd in {root.as_posix()}/decks.\n")
        error = gitops._describe(done, root)
        self.assertEqual((error.kind, str(error)), ("failed", "git status failed: fatal: something odd in decks"))

    def test_repo_paths_in_every_form(self):
        root = Path(r"C:\Users\someone\TradingCardCollection")
        text = (r"C:\Users\someone\TradingCardCollection\magic\decks x c:/users/someone/tradingcardcollection/magic "
                "/c/Users/someone/TradingCardCollection/decks C:/Users/someone/TradingCardCollection "
                "C:/Users/someone/TradingCardCollection2/x")
        self.assertEqual(gitops._relative_paths(text, root),
                         r"magic\decks x magic decks the repo folder C:/Users/someone/TradingCardCollection2/x")


if __name__ == "__main__":
    unittest.main()
