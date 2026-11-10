"""Static JS calls use real lexical scopes, without executing page scripts or making requests."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "decklab" / "web"
NODE = shutil.which("node")


def audit(files):
    result = subprocess.run([NODE, str(ROOT / "scripts" / "js_globals.js")],
                            input=json.dumps({"files": [{"name": name, "source": source} for name, source in files]}),
                            text=True, encoding="utf-8", capture_output=True, timeout=30)
    if result.returncode:
        raise AssertionError("JS audit needs pinned dependencies: npm ci --ignore-scripts --prefix decklab/ui_review\n"
                             + result.stderr)
    return json.loads(result.stdout)


@unittest.skipUnless(NODE, "Node.js is needed for static JavaScript scope checks")
class JavaScriptGlobalsTests(unittest.TestCase):
    def test_every_page_script_resolves_its_bare_calls(self):
        from decklab.tests.test_web import _References
        page = _References()
        page.feed((WEB / "index.html").read_text(encoding="utf-8"))
        urls = [url for tag, url in page.refs if tag == "script"]
        for url in urls:
            self.assertRegex(url, r"^/[A-Za-z0-9_-]+\.js$")
        names = [url[1:] for url in urls]
        self.assertGreater(len(names), 100)
        found = audit([(name, (WEB / name).read_text(encoding="utf-8")) for name in names])
        self.assertEqual(found["issues"], [], "\n".join(f"{row['file']}:{row['line']}:{row['column']}: "
                         f"{row['message']} {row['name']}" for row in found["issues"]))

    def test_cross_script_globals_locals_destructuring_and_browser_calls_are_resolved(self):
        found = audit([("a.js", "function helper() {} const later = () => {}; class Thing {}"),
                       ("b.js", """helper(); later(); new Thing(); fetch('/example'); new URL('/example', location);
function caller(arg, {nested: renamed}, ...rest) { arg(); renamed(); rest[0](); }
const lambda = (local = helper) => local();
try { helper(); } catch (caught) { caught(); }
""")])
        self.assertEqual(found["issues"], [])

    def test_scope_mistakes_and_missing_helpers_name_the_actual_source_location(self):
        found = audit([("defs.js", "function other() { const sibling = () => {}; sibling(); }"),
                       ("calls.js", "function use() { sibling(); }\nremovedHelper();\nconst value = `${insideTemplate()}`;")])
        self.assertEqual([(row["file"], row["line"], row["name"]) for row in found["issues"]],
                         [("calls.js", 1, "sibling"), ("calls.js", 2, "removedHelper"),
                          ("calls.js", 3, "insideTemplate")])

    def test_typeof_guards_cover_only_calls_on_the_protected_path(self):
        good = """
if (typeof optional === 'function') optional();
typeof other !== 'undefined' && other();
const result = typeof third === 'function' ? third() : null;
function early() { if (typeof later !== 'function') return; later(); }
function compound() { if (typeof final !== 'function' || false) return; final(); }
"""
        self.assertEqual(audit([("guards.js", good)])["issues"], [])
        bad = """
typeof loose; loose();
if (typeof backward !== 'function') backward();
if (typeof maybe === 'function' || true) maybe();
bareOptional?.();
"""
        self.assertEqual([row["name"] for row in audit([("unsafe.js", bad)])["issues"]],
                         ["loose", "backward", "maybe", "bareOptional"])

    def test_comments_strings_member_calls_and_typeof_checks_are_not_bare_calls(self):
        source = "// noSuchHelper()\nconst words = 'alsoMissing()'; obj.method(); typeof notDeclared;"
        self.assertEqual(audit([("text.js", source)])["issues"], [])

    def test_a_new_sheet_family_is_visible_to_the_closer_inventory(self):
        source = ("function closeAllSheets() { closeCurrentSheets(); }\nfunction closeCurrentSheets() {}\n"
                  "function closeNewSheets() {}\nconst closeArrowSheets = () => {};")
        result = audit([("sheets.js", source)])
        self.assertEqual({row["name"] for row in result["sheetClosers"]} - {"closeAllSheets"} - set(result["closeCalls"]),
                         {"closeNewSheets", "closeArrowSheets"})
