"""The Collection page's "Add a precon" sheet in its own file (structural only): precon-add.js holds the
sheet, loads right after collection-filing.js, and its functions keep their global names, so collection.js's
More menu, the empty library's ?open=precon and the precon UI tests call them as before.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_precon_add_split
"""
import re
import unittest

from decklab.tests.test_web import NODE, PLAY_SCRIPTS, WEB, _run_page, _text

MOVED = ("openPreconSheet", "backToPrecons", "fromWizards", "searchPrecons", "previewPrecon", "preconLine",
         "drawPreconPreview", "preconAddHere", "addPrecon")


def _defined(script):
    return re.findall(r"^(?:async )?function (\w+)\(", script, re.M)


class PreconAddFileTests(unittest.TestCase):

    def test_the_file_holds_only_the_moved_names(self):
        script = _text("precon-add.js")
        self.assertEqual(sorted(_defined(script)), sorted(MOVED))
        self.assertEqual(re.findall(r"^(?:const|let|var) (\w+)", script, re.M), ["PRECON_SEARCH_MS"])
        collection = _text("collection.js")
        for name in (*MOVED, "PRECON_SEARCH_MS"):
            with self.subTest(name=name):
                self.assertNotRegex(collection, rf"^(?:async )?(?:function|const|let|var) {name}\b")

    def test_it_loads_right_after_the_collection_filing_script(self):
        page = (WEB / "index.html").read_text(encoding="utf-8")
        scripts = re.findall(r'<script src="/([^"]+)"', page)
        self.assertEqual(scripts.count("precon-add.js"), 1)
        self.assertEqual(scripts[scripts.index("collection-filing.js") + 1], "precon-add.js")
        self.assertEqual(PLAY_SCRIPTS[PLAY_SCRIPTS.index("collection-filing.js") + 1], "precon-add.js")

    def test_both_files_stay_under_the_length_guard(self):
        for name in ("collection.js", "precon-add.js"):
            with self.subTest(name=name):
                self.assertLessEqual(len(_text(name).splitlines()), 1200)


@unittest.skipUnless(NODE, "needs Node.js")
class PreconAddGlobalsTests(unittest.TestCase):

    def test_the_moved_functions_are_globals_after_loading(self):
        calls = [f"typeof {name}" for name in MOVED] + ["PRECON_SEARCH_MS"]
        names = ("core.js", "collection.js", "collection-filing.js", "precon-add.js")
        self.assertEqual(_run_page(calls, names), ["function"] * len(MOVED) + ["250"])


if __name__ == "__main__":
    unittest.main()
