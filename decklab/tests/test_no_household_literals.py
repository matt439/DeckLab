"""Canonical product/format choices stay in their owners, without reading household records."""
import ast
from contextlib import redirect_stdout
import io
from pathlib import Path
import unittest
from unittest import mock

from decklab.db import space_forge
from decklab.lib import decks
from decklab.lib.goldfish import cli
from decklab.tests.test_js_globals import audit, NODE
from decklab.tests.test_web import _run_page, WEB

ROOT = Path(__file__).resolve().parents[2]


def python_product_literals(source, stem, *, canonical=False):
    tree = ast.parse(source)
    ignored = set()
    if canonical:
        definition = next((node for node in tree.body if isinstance(node, ast.Assign)
                           and any(isinstance(name, ast.Name) and name.id == "BEGINNER_BOX" for name in node.targets)), None)
        if definition is not None:
            ignored.add(id(definition.value))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body \
                and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) \
                and isinstance(node.body[0].value.value, str):
            ignored.add(id(node.body[0].value))
    return [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and stem in node.value and id(node) not in ignored]


class PythonHouseholdLiteralTests(unittest.TestCase):
    def test_product_stem_is_not_duplicated_in_runtime_code(self):
        found = []
        paths = [path for parent in (ROOT / "decklab" / "lib", ROOT / "decklab" / "db", ROOT / "scripts")
                 for path in parent.rglob("*.py")]
        paths += list((ROOT / "decklab").glob("*.py"))
        for path in paths:
            canonical = path == ROOT / "decklab" / "lib" / "decks" / "__init__.py"
            found.extend(f"{path.relative_to(ROOT)}:{line}" for line in
                         python_product_literals(path.read_text(encoding="utf-8"), decks.BEGINNER_BOX,
                                                 canonical=canonical))
        self.assertEqual(found, [])

    def test_guard_ignores_docstrings_but_detects_executable_duplicates(self):
        source = '"""fixture-box in a docstring"""\n# fixture-box in a comment\nx = "product/fixture-box/cats"\n'
        self.assertEqual(python_product_literals(source, "fixture-box"), [3])
        self.assertEqual(python_product_literals('BEGINNER_BOX = "fixture-box"', "fixture-box", canonical=True), [])
        self.assertEqual(python_product_literals('BEGINNER_BOX = "fixture-box"\nBEGINNER_BOX = "fixture-box"',
                                                "fixture-box", canonical=True), [2])

    def test_anonymous_product_hash_query_uses_the_canonical_parameter(self):
        cursor = mock.Mock()
        cursor.execute.return_value = []
        with mock.patch.object(decks, "BEGINNER_BOX", "fixture-box"):
            self.assertEqual(space_forge.other_list_hashes(cursor, "user2"), frozenset())
        self.assertEqual(cursor.execute.call_args.args[1], ("fixture-box",))
        self.assertNotIn("fixture-box", cursor.execute.call_args.args[0])

    def test_goldfish_halves_filter_uses_the_canonical_stem_without_running_games(self):
        class Output(io.StringIO):
            def reconfigure(self, **kwargs):
                pass
        summaries = [{"id": "product/fixture-box/cats", "versions": ["target"]},
                     {"id": "casual/fixture", "versions": ["target"]}]
        headline = {"setup": "play", **{name: 0 for name in ("mulligan_rate", "land_3_by_3", "land_4_by_4",
                                                          "colour_screw", "flood_turns", "big_by_4")}}
        with mock.patch.object(decks, "BEGINNER_BOX", "fixture-box"), \
                mock.patch.object(decks, "list_decks", return_value=summaries), \
                mock.patch.object(decks, "engine_kind", return_value="constructed"), \
                mock.patch.object(decks, "load_deck", return_value={}) as load, \
                mock.patch.object(cli.runs, "get_or_simulate", return_value={"seconds": 0}), \
                mock.patch.object(cli, "headline", return_value=headline), redirect_stdout(Output()):
            self.assertEqual(cli.main(["--all"]), 0)
            self.assertEqual(load.call_args_list, [mock.call("casual/fixture", "target")])
            load.reset_mock()
            self.assertEqual(cli.main(["--all", "--halves"]), 0)
            self.assertEqual(len(load.call_args_list), 2)


@unittest.skipUnless(NODE, "Node.js is needed for shared page locale checks")
class JavaScriptHouseholdLiteralTests(unittest.TestCase):
    def test_the_page_has_one_stem_prefix_and_one_locale_with_no_raw_formatting_calls(self):
        result = audit([(path.name, path.read_text(encoding="utf-8")) for path in WEB.glob("*.js")],
                       tracked_literals=(decks.BEGINNER_BOX, "en-AU"))
        self.assertEqual(result["issues"], [])
        for value in (decks.BEGINNER_BOX, "en-AU"):
            uses = [row for row in result["literalUses"] if row["value"] == value]
            self.assertEqual([row["file"] for row in uses], ["core.js"])
        self.assertGreater(len(result["localeCalls"]), 10)
        self.assertEqual([f"{row['file']}:{row['line']}: {row['method']}" for row in result["localeCalls"] if not row["shared"]], [])

    def test_guard_detects_new_literals_and_local_shadowing_without_reading_comments(self):
        source = ('const LOCALE="en-AU"; // fixture-box\n'
                  'function good(d) { return d.toLocaleString(LOCALE); }\n'
                  'function bad(d) { return d.toLocaleString("fr-FR"); }\n'
                  'function shadow(d, LOCALE) { return d.toLocaleString(LOCALE); }\n'
                  'const prefix=`product/fixture-box/`;')
        result = audit([("sample.js", source)], tracked_literals=("fixture-box",))
        self.assertEqual([row["shared"] for row in result["localeCalls"]], [True, False, False])
        self.assertEqual([row["line"] for row in result["literalUses"]], [5])

    def test_existing_number_and_date_formats_are_preserved(self):
        self.assertEqual(_run_page(["LOCALE", "thousands(10000)",
            "thousands(12.5, {minimumFractionDigits:2, maximumFractionDigits:2})",
            "String(new Date('2026-11-11T12:00:00Z').toLocaleDateString(LOCALE, {month:'short',day:'numeric'}) "
            "=== new Date('2026-11-11T12:00:00Z').toLocaleDateString('en-AU', {month:'short',day:'numeric'}))"],
            names=("core.js",)), ["en-AU", "10,000", "12.50", "true"])
