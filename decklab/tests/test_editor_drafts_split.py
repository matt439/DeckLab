"""The editor's drafts and rebase in their own file (E11-S46, structural only): editor-drafts.js holds
re-applying an edit onto a newer file and the drafts kept on this device, loads right after editor.js,
and the functions keep their global names, so the other editor scripts call them as before.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_editor_drafts_split
"""
import re
import unittest

from decklab.tests.test_web import NODE, WEB, _run_page, _text

MOVED = ("reapplyList", "reapplyFields", "rebase", "draftKey", "queueDraft", "saveDraft", "draftStored",
         "readDraft", "removeDraft", "timeWords")
ADDED = ("draftRecord",)        # E2-S16: saveDraft's draft object, shared with the drafts kept for later


def _defined(script):
    return re.findall(r"^(?:async )?function (\w+)\(", script, re.M)


class DraftsFileTests(unittest.TestCase):

    def test_the_drafts_file_holds_only_the_moved_functions(self):
        defined = _defined(_text("editor-drafts.js"))
        self.assertEqual(sorted(defined), sorted(MOVED + ADDED))
        editor = _defined(_text("editor.js"))
        for name in MOVED:
            with self.subTest(name=name):
                self.assertNotIn(name, editor)

    def test_it_loads_right_after_the_editor(self):
        page = (WEB / "index.html").read_text(encoding="utf-8")
        scripts = re.findall(r'<script src="/([^"]+)"', page)
        self.assertEqual(scripts[scripts.index("editor.js") + 1], "editor-drafts.js")

    def test_both_files_stay_under_the_length_guard(self):
        for name in ("editor.js", "editor-drafts.js"):
            with self.subTest(name=name):
                self.assertLessEqual(len(_text(name).splitlines()), 1200)


@unittest.skipUnless(NODE, "needs Node.js")
class DraftsGlobalsTests(unittest.TestCase):

    def test_the_moved_functions_are_globals_after_loading(self):
        calls = [f"typeof {name}" for name in MOVED]
        self.assertEqual(_run_page(calls, ("core.js", "editor.js", "editor-drafts.js")), ["function"] * len(MOVED))

    def test_draft_keys_are_unchanged(self):
        calls = ['draftKey({mode: "edit", profile: "matt", id: "casual/elves", version: "target"})',
                 'draftKey({mode: "new", profile: "matt", space: HOME_SPACE})',
                 'draftKey({mode: "new", profile: "user5", space: "user5", from: "product/x"})']
        self.assertEqual(_run_page(calls, ("core.js", "editor.js", "editor-drafts.js")),
                         ["draft.matt.casual/elves.target", "draft.matt.new.scratch", "draft.user5.new.user5.product/x"])


if __name__ == "__main__":
    unittest.main()
