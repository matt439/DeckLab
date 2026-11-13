"""A release's changelog (E11-S84): scripts/release_notes.py drafts it from decklab/HISTORY.md.

Pure functions over made-up HISTORY.md texts, and draft() over a stubbed git; nothing is tagged,
published or fetched.
"""
import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("release_notes", REPO / "scripts" / "release_notes.py")
release_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_notes)

OLD = """# Deck Lab: history

Intro words.

## Older feature (2026-11-01; E1-S01)

Built it.
"""
NEW = """# Deck Lab: history

Intro words.

## Newest feature (2026-11-13; E11-S84)

It reads [README.md](README.md) and [the guide](../SELF-HOSTING.md#updating), not [web](https://example.com/x).

### A detail

```
## not a heading inside a fence
```

## Middle feature (2026-11-05; E2-S02)

Second.

## Older feature (2026-11-01; E1-S01)

Built it, now with an edit (an edited entry isn't new).
"""


class EntriesTests(unittest.TestCase):
    def test_sections_in_file_order_with_fences_skipped(self):
        found = release_notes.entries(NEW)
        self.assertEqual([heading for heading, _ in found],
                         ["Newest feature (2026-11-13; E11-S84)", "Middle feature (2026-11-05; E2-S02)",
                          "Older feature (2026-11-01; E1-S01)"])
        self.assertIn("## not a heading inside a fence", found[0][1])

    def test_added_is_by_heading_newest_first(self):
        self.assertEqual([h for h, _ in release_notes.added(OLD, NEW)],
                         ["Newest feature (2026-11-13; E11-S84)", "Middle feature (2026-11-05; E2-S02)"])
        self.assertEqual(release_notes.added(NEW, NEW), [])


class PreviousTagTests(unittest.TestCase):
    def test_a_stable_release_follows_the_last_stable_one(self):
        tags = ["v1.0.0", "v1.2.0", "v1.3.0-rc1", "v1.3.0", "v1.10.0", "not-a-version"]
        self.assertEqual(release_notes.previous_tag("1.3.0", tags), "v1.2.0")
        self.assertEqual(release_notes.previous_tag("1.11.0", tags), "v1.10.0")
        self.assertEqual(release_notes.previous_tag("1.4.0-rc1", tags), "v1.3.0")
        self.assertEqual(release_notes.previous_tag("1.3.0-rc2", tags), "v1.3.0-rc1")
        self.assertIsNone(release_notes.previous_tag("1.0.0", tags))


class NotesTests(unittest.TestCase):
    def test_the_entries_follow_the_download_words(self):
        text = release_notes.notes("1.3.0", release_notes.added(OLD, NEW), "v1.2.0", repo="owner/repo",
                                   commit="c" * 40)
        self.assertTrue(text.startswith("Deck Lab 1.3.0. Download decklab-1.3.0.zip and check it against "
                                        "decklab-1.3.0.zip.sha256."))
        self.assertIn("gh attestation verify decklab-1.3.0.zip --repo owner/repo", text)
        self.assertIn("## What's new since v1.2.0", text)
        self.assertIn("\n### Newest feature (2026-11-13; E11-S84)\n", text)
        self.assertIn("\n#### A detail\n", text)                          # demoted a level
        self.assertIn("## not a heading inside a fence", text)            # fenced text untouched
        self.assertNotIn("Older feature", text)
        self.assertLess(text.index("Newest feature"), text.index("Middle feature"))
        base = "https://github.com/owner/repo/blob/" + "c" * 40
        self.assertIn(f"[README.md]({base}/decklab/README.md)", text)
        self.assertIn(f"[the guide]({base}/SELF-HOSTING.md#updating)", text)
        self.assertIn("[web](https://example.com/x)", text)

    def test_first_release_and_nothing_new(self):
        self.assertIn("The first release", release_notes.notes("1.0.0", [], None))
        self.assertIn("No new entries in decklab/HISTORY.md since v1.2.0", release_notes.notes("1.2.1", [], "v1.2.0"))

    def test_too_long_keeps_headings_then_counts_the_rest(self):
        new = [(f"Feature {i}", "words " * 400) for i in range(40)]
        text = release_notes.notes("2.0.0", new, "v1.0.0", limit=900)
        self.assertLessEqual(len(text), 900)
        self.assertIn("only their headings are here", text)
        self.assertIn("- Feature 0\n", text)
        self.assertRegex(text, r"- and \d+ more entries in decklab/HISTORY.md")
        self.assertNotIn("words words", text)


class DraftTests(unittest.TestCase):
    def git(self, *args, check=True):
        if args[0] == "rev-parse":
            return "c" * 40 + "\n"
        if args[0] == "tag":
            return "v1.1.0\nv1.2.0\nv1.3.0\n"
        if args == ("show", "v1.2.0:decklab/HISTORY.md"):
            return OLD
        if args == ("show", f"{'c' * 40}:decklab/HISTORY.md"):
            return NEW
        raise AssertionError(args)

    def test_draft_reads_history_at_the_previous_tag_and_the_release(self):
        with mock.patch.object(release_notes, "_git", side_effect=self.git):
            text = release_notes.draft("v1.3.0", repo="owner/repo")
        self.assertIn("What's new since v1.2.0", text)
        self.assertIn("Middle feature", text)
        self.assertNotIn("Older feature", text)

    def test_a_bad_version_is_refused(self):
        with mock.patch.object(release_notes, "_git", side_effect=self.git):
            with self.assertRaises(ValueError):
                release_notes.draft("one")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(release_notes.main(["one"]), 1)

    @unittest.skipUnless((REPO / ".github").is_dir(), "no .github here (a release zip leaves it out)")
    def test_the_release_workflow_uses_it(self):
        text = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("python scripts/release_notes.py", text)
        self.assertIn('--notes-file "$RUNNER_TEMP/release-notes.md"', text)
        self.assertNotIn("--out dist/release", text)          # dist/ is all attached to the release


if __name__ == "__main__":
    unittest.main()
