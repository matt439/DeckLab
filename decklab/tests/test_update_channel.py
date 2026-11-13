"""The update channel (E11-S84): lib/update_channel.py and update.py's release channel, over a fake git.

A fake repository (commits, their parents, tags, HEAD and origin/main) answers the git commands
the channel asks; nothing runs real git, fetches or changes a checkout.
"""
import os
import subprocess
import tempfile
import types
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest import mock

from decklab import update
from decklab.lib import update_channel


class FakeGit:
    """A repository of commits c0..cN (each a child of the one before unless parents says otherwise)."""

    def __init__(self, count, head, upstream, tags=(), parents=None, upstream_name="origin/main"):
        self.order = [f"c{i}" for i in range(count)]
        self.parents = {c: ([self.order[i - 1]] if i else []) for i, c in enumerate(self.order)}
        self.parents.update(parents or {})
        self.head, self.upstream, self.upstream_name = head, upstream, upstream_name
        self.tags = dict(tags)
        self.calls, self.merged_to = [], None
        self.fetch_head = None

    def ancestors(self, commit):
        seen, todo = set(), [commit]
        while todo:
            c = todo.pop()
            if c not in seen:
                seen.add(c)
                todo.extend(self.parents[c])
        return seen

    def resolve(self, ref):
        ref = ref.removesuffix("^{commit}")
        if ref == "HEAD":
            return self.head
        if ref in ("@{upstream}", self.upstream_name):
            return self.upstream
        if ref in self.tags:
            return self.tags[ref]
        if ref in self.parents:
            return ref
        raise update.Failed(f"unknown revision {ref}")

    def merged_tags(self, ref):
        held = self.ancestors(self.resolve(ref))
        return {tag for tag, commit in self.tags.items() if commit in held}

    def __call__(self, *args, check=True, timeout=None):
        self.calls.append(args)
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return self.upstream_name if "--symbolic-full-name" in args else "main"
        if args[:2] == ("rev-parse", "--git-path"):
            return str(self.fetch_head or "no-such-fetch-head")
        if args[0] == "rev-parse":
            return self.resolve(args[-1])
        if args[0] == "tag":
            tags = self.merged_tags(args[args.index("--merged") + 1])
            if "--no-merged" in args:
                tags -= self.merged_tags(args[args.index("--no-merged") + 1])
            return "\n".join(sorted(t for t in tags if t.startswith("v")))
        if args[0] == "merge-base":
            common = self.ancestors(self.resolve(args[1])) & self.ancestors(self.resolve(args[2]))
            return max(common, key=self.order.index)
        if args[:2] == ("rev-list", "--count"):
            old, new = args[2].split("..")
            return str(len(self.ancestors(self.resolve(new)) - self.ancestors(self.resolve(old))))
        if args[0] == "log":
            old, new = args[-1].split("..")
            return "\n".join(f"{c} commit" for c in self.ancestors(self.resolve(new)) - self.ancestors(self.resolve(old)))
        if args[0] == "merge":
            self.merged_to = self.resolve(args[-1])
            self.head = self.merged_to
            return ""
        if args[0] in ("status", "fetch", "diff", "show"):
            return ""
        raise AssertionError(f"unexpected git {args}")


class ChannelSettingTests(unittest.TestCase):
    def test_main_is_the_default_and_the_flag_overrides_the_config(self):
        self.assertEqual(update_channel.configured({}), "main")
        self.assertEqual(update_channel.configured({"update": {}}), "main")
        self.assertEqual(update_channel.configured({"update": {"channel": "release"}}), "release")
        self.assertEqual(update_channel.choose(None, {"update": {"channel": "release"}}), "release")
        self.assertEqual(update_channel.choose("main", {"update": {"channel": "release"}}), "main")
        self.assertEqual(update_channel.choose("release", {}), "release")

    def test_a_malformed_setting_is_refused(self):
        for settings in ({"update": "release"}, {"update": {"channel": "stable"}}, {"update": {"channel": None}}):
            with self.subTest(settings=settings), self.assertRaises(update_channel.ChannelError):
                update_channel.configured(settings)
        with self.assertRaises(update_channel.ChannelError):
            update_channel.choose("nightly", {})

    def test_only_plain_version_tags_are_releases(self):
        self.assertEqual(update_channel.stable_key("v1.10.2"), (1, 10, 2))
        for name in ("1.2.0", "v1.2", "v1.2.0-rc1", "v1.2.0+build", "release-1.2.0", None):
            self.assertIsNone(update_channel.stable_key(name))
        self.assertEqual(update_channel._stable("v1.2.0\nv1.10.0\nv1.3.0-rc1\nv1.9.9\n"), ["v1.10.0", "v1.9.9", "v1.2.0"])


class PlanReleaseTests(unittest.TestCase):
    def plan(self, git):
        return update_channel.plan_release(git, "origin/main")

    def test_moves_to_the_newest_tag_not_to_mains_tip(self):
        git = FakeGit(8, head="c2", upstream="c7", tags={"v1.0.0": "c1", "v1.1.0": "c4", "v1.2.0-rc1": "c6"})
        self.assertEqual(self.plan(git), {"tag": "v1.1.0", "target": "c4", "move": True, "note": None})

    def test_newest_by_version_not_by_tag_order(self):
        git = FakeGit(8, head="c0", upstream="c7", tags={"v1.10.0": "c5", "v1.9.0": "c3"})
        self.assertEqual(self.plan(git)["tag"], "v1.10.0")

    def test_no_release_yet_moves_nothing(self):
        git = FakeGit(5, head="c2", upstream="c4")
        plan = self.plan(git)
        self.assertFalse(plan["move"])
        self.assertEqual(plan["target"], "c2")
        self.assertIn("no release", plan["note"])

    def test_at_the_newest_release_already(self):
        git = FakeGit(5, head="c3", upstream="c4", tags={"v1.0.0": "c3"})
        self.assertEqual(self.plan(git), {"tag": "v1.0.0", "target": "c3", "move": False,
                                          "note": "Already at the newest release, v1.0.0."})

    def test_past_the_newest_release_never_goes_back(self):
        # A checkout that followed main past v1.1.0 stays put: a downgrade is refused.
        git = FakeGit(8, head="c6", upstream="c7", tags={"v1.0.0": "c1", "v1.1.0": "c4"})
        plan = self.plan(git)
        self.assertFalse(plan["move"])
        self.assertEqual(plan["target"], "c6")
        self.assertIn("never goes back", plan["note"])

    def test_a_later_lower_version_tag_is_never_a_downgrade_target(self):
        # v1.0.1 tagged after v1.1.0 on main: the checkout holding v1.1.0 doesn't move to it.
        git = FakeGit(8, head="c4", upstream="c7", tags={"v1.1.0": "c4", "v1.0.1": "c6"})
        plan = self.plan(git)
        self.assertEqual(plan["tag"], "v1.1.0")
        self.assertFalse(plan["move"])

    def test_tags_off_main_are_ignored(self):
        # c9 is on a side branch (child of c3); its tag isn't on origin/main.
        git = FakeGit(10, head="c3", upstream="c8", tags={"v1.0.0": "c3", "v2.0.0": "c9"}, parents={"c9": ["c3"]})
        plan = self.plan(git)
        self.assertEqual(plan["tag"], "v1.0.0")
        self.assertFalse(plan["move"])

    def test_a_tag_neither_ahead_nor_behind_is_refused(self):
        git = FakeGit(10, head="c9", upstream="c8", tags={"v1.0.0": "c8"}, parents={"c9": ["c3"]})
        with self.assertRaises(ValueError):
            self.plan(git)


class WaitingTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="decklab-update-channel-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_main_counts_commits_upstream_has(self):
        git = FakeGit(8, head="c3", upstream="c7")
        found = update_channel.waiting(git, self.root, {})
        self.assertEqual(found, {"channel": "main", "count": 4, "newest": None, "upstream": "origin/main",
                                 "fetched_on": None, "problem": None})
        self.assertFalse(any(call[0] == "fetch" for call in git.calls))       # never fetched for the page

    def test_release_counts_newer_stable_releases(self):
        git = FakeGit(9, head="c2", upstream="c8",
                      tags={"v1.0.0": "c1", "v1.1.0": "c4", "v1.2.0-rc1": "c5", "v1.2.0": "c6"})
        found = update_channel.waiting(git, self.root, {"update": {"channel": "release"}})
        self.assertEqual((found["count"], found["newest"]), (2, "v1.2.0"))
        git.head = "c6"
        found = update_channel.waiting(git, self.root, {"update": {"channel": "release"}})
        self.assertEqual((found["count"], found["newest"]), (0, None))

    def test_the_last_fetch_dates_the_count(self):
        path = self.root / "FETCH_HEAD"
        path.write_text("x", encoding="utf-8")
        os.utime(path, (1_700_000_000, 1_700_000_000))
        git = FakeGit(2, head="c1", upstream="c1")
        git.fetch_head = path
        # 2023-11-14 22:13 UTC is the 15th in a UTC+10 household zone.
        with mock.patch("decklab.lib.hometime.zone", return_value=timezone(timedelta(hours=10))):
            self.assertEqual(update_channel.waiting(git, self.root, {"timezone": "Etc/GMT-10"})["fetched_on"],
                             "2023-11-15")
        # Without a zone (or with one this PC has no data for), the PC's own zone dates it.
        with mock.patch("decklab.lib.hometime._local", side_effect=lambda now: now.astimezone(
                timezone(timedelta(hours=10)))):
            self.assertEqual(update_channel.waiting(git, self.root, {})["fetched_on"], "2023-11-15")
            with mock.patch("decklab.lib.hometime.zone", return_value=None):
                self.assertEqual(update_channel.waiting(git, self.root, {"timezone": "Nowhere/Else"})["fetched_on"],
                                 "2023-11-15")

    def test_problems_are_fixed_words(self):
        found = update_channel.waiting(FakeGit(2, "c1", "c1"), self.root, {"update": {"channel": "x"}})
        self.assertEqual((found["count"], found["problem"]), (None, "config.json's update channel isn't main or release."))

        def broken(*args):
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return "origin/main"
            raise RuntimeError("fatal: secret path /home/someone")
        found = update_channel.waiting(broken, self.root, {})
        self.assertEqual(found["problem"], "Git couldn't count the updates waiting.")
        self.assertNotIn("secret", repr(found))

        def no_upstream(*args):
            raise RuntimeError("no upstream")
        self.assertEqual(update_channel.waiting(no_upstream, self.root, {})["problem"],
                         "This checkout's branch has no upstream to compare with.")

    def test_an_unreadable_config_says_so(self):
        (self.root / ".git").mkdir()
        from decklab.lib import build, config
        with mock.patch.object(build, "is_release", return_value=False),                 mock.patch.object(config, "load", side_effect=ValueError("bad json at /secret/path")):
            found = update_channel.view(self.root)
        self.assertEqual(found["problem"], "config.json can't be read, so the update channel is unknown.")
        self.assertIsNone(found["count"])
        self.assertNotIn("secret", repr(found))

    def test_a_release_install_has_no_updates_line(self):
        from decklab.lib import build
        with mock.patch.object(build, "is_release", return_value=True):
            self.assertIsNone(update_channel.view(self.root))
        self.assertIsNone(update_channel.view(self.root))       # no .git either


def _git_works():
    try:
        return subprocess.run(["git", "--version"], capture_output=True).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(_git_works(), "git isn't installed")
class RealGitTests(unittest.TestCase):
    """The same answers from real git, in a throwaway upstream and its clone (no network)."""

    def run_git(self, cwd, *args):
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args], cwd=cwd,
                       check=True, capture_output=True)

    def test_counts_and_plan_from_a_real_clone(self):
        from decklab.lib import build
        folder = tempfile.TemporaryDirectory(prefix="decklab-update-channel-git-")
        self.addCleanup(folder.cleanup)
        up, down = Path(folder.name) / "up", Path(folder.name) / "down"
        up.mkdir()
        self.run_git(up, "init", "-q", "-b", "main")
        for number in range(1, 6):
            (up / "f.txt").write_text(str(number), encoding="utf-8")
            self.run_git(up, "add", "f.txt")
            self.run_git(up, "commit", "-q", "-m", f"c{number}")
            if number == 2:
                self.run_git(up, "tag", "v1.0.0")
            if number == 4:
                self.run_git(up, "tag", "-a", "v1.1.0", "-m", "release")      # annotated, as gh makes
        self.run_git(folder.name, "clone", "-q", str(up), str(down))
        self.run_git(down, "reset", "-q", "--hard", "HEAD~4")

        def git(*args):
            return build._git(down, *args).strip()

        self.assertEqual(update_channel.waiting(git, down, {})["count"], 4)
        found = update_channel.waiting(git, down, {"update": {"channel": "release"}})
        self.assertEqual((found["count"], found["newest"], found["problem"]), (2, "v1.1.0", None))
        self.assertIsNone(found["fetched_on"])                      # a clone leaves no FETCH_HEAD
        self.run_git(down, "fetch", "-q")                           # from the folder: no network
        self.assertIsNotNone(update_channel.waiting(git, down, {})["fetched_on"])
        plan = update_channel.plan_release(git, "origin/main")
        self.assertEqual((plan["tag"], plan["move"]), ("v1.1.0", True))
        self.assertEqual(plan["target"], git("rev-parse", "origin/main~1"))


class BeforePullChannelTests(unittest.TestCase):
    """update.before_pull on each channel: what it merges, with everything outside git stubbed."""

    def run_update(self, git, settings=None, channel=None, dry_run=False):
        args = types.SimpleNamespace(dry_run=dry_run, no_forge=True, no_restart=True, no_smoke=True, force=False,
                                     channel=channel)
        from decklab.lib import build, config
        with mock.patch.object(build, "is_release", return_value=False), \
                mock.patch.object(update, "interpreter_problem", return_value=None), \
                mock.patch.object(update, "git", side_effect=git), \
                mock.patch.object(config, "load", return_value=settings or {}), \
                mock.patch.object(update.subprocess, "run", return_value=types.SimpleNamespace(returncode=0)) as rest, \
                mock.patch.object(update, "say") as say:
            code = update.before_pull(args)
        return code, rest, " ".join(str(c.args[0]) for c in say.call_args_list if c.args)

    def test_main_channel_still_follows_the_upstream_tip(self):
        git = FakeGit(8, head="c2", upstream="c7", tags={"v1.0.0": "c4"})
        code, rest, _ = self.run_update(git)
        self.assertEqual(code, 0)
        self.assertEqual(git.head, "c7")
        self.assertNotIn(("fetch", "--tags"), git.calls)
        self.assertEqual(rest.call_args.args[0][3:5], ["--after-pull", "c2"])

    def test_release_channel_from_config_moves_only_to_the_tag(self):
        git = FakeGit(8, head="c2", upstream="c7", tags={"v1.0.0": "c4"})
        code, _, said = self.run_update(git, settings={"update": {"channel": "release"}})
        self.assertEqual(code, 0)
        self.assertEqual(git.head, "c4")
        self.assertIn(("fetch", "--tags"), git.calls)
        self.assertIn("moving to v1.0.0", said)

    def test_the_flag_overrides_the_config(self):
        git = FakeGit(8, head="c2", upstream="c7", tags={"v1.0.0": "c4"})
        self.run_update(git, settings={"update": {"channel": "release"}}, channel="main")
        self.assertEqual(git.head, "c7")

    def test_release_channel_past_the_newest_tag_merges_nothing(self):
        git = FakeGit(8, head="c6", upstream="c7", tags={"v1.0.0": "c4"})
        code, rest, said = self.run_update(git, channel="release")
        self.assertEqual(code, 0)
        self.assertEqual(git.head, "c6")
        self.assertFalse(any(call[0] == "merge" for call in git.calls))
        self.assertIn("never goes back", said)
        self.assertEqual(rest.call_args.args[0][3:5], ["--after-pull", "c6"])    # the rest still runs

    def test_dry_run_merges_nothing(self):
        git = FakeGit(8, head="c2", upstream="c7", tags={"v1.0.0": "c4"})
        code, rest, said = self.run_update(git, channel="release", dry_run=True)
        self.assertEqual((code, git.head), (0, "c2"))
        rest.assert_not_called()
        self.assertIn("Dry run", said)

    def test_local_commits_are_still_refused_first(self):
        git = FakeGit(10, head="c9", upstream="c8", tags={"v1.0.0": "c8"}, parents={"c9": ["c3"]})
        with self.assertRaisesRegex(update.Failed, "commits that origin/main hasn't"):
            self.run_update(git, channel="release")
        self.assertEqual(git.head, "c9")

    def test_a_malformed_channel_is_refused_before_fetching(self):
        git = FakeGit(3, head="c0", upstream="c2")
        with self.assertRaisesRegex(update.Failed, "Nothing was fetched"):
            self.run_update(git, settings={"update": {"channel": "nightly"}})
        self.assertFalse(any(call[0] == "fetch" for call in git.calls))

    def test_the_documents_name_the_channel(self):
        root = Path(update.__file__).resolve().parents[1]
        hosting = (root / "SELF-HOSTING.md").read_text(encoding="utf-8")
        self.assertIn('"update": {"channel": "release"}', hosting)
        self.assertIn("--channel release", hosting)
        readme = (root / "decklab" / "README.md").read_text(encoding="utf-8")
        self.assertIn("--channel release", readme)


if __name__ == "__main__":
    unittest.main()
