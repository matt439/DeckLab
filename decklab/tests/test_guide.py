"""The playing guide uses existing deck notes, preserving scope and safe text."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from decklab.lib import api, decks, inventory
from decklab.lib.api.guide import playing_guide
from decklab.tests import pre_db
from decklab.tests.test_api import ApiTestCase, GRUUL
from decklab.tests.test_web import NODE_RUNNER


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "decklab" / "web"


def guide(text):
    return playing_guide(decks.parse_deck((GRUUL + "\n" + text).encode(), kind="casual", slug="guide-test"))


class ExtractionTests(unittest.TestCase):
    def test_legacy_inline_headings_preserve_opening_sentence_and_lists(self):
        answer = guide("""## Notes

**Game plan.** Play cheap creatures.
- First turn.
  - Nested advice.

**Opening hand and mulligan.**
Keep two lands.

**Sideboard: against bigger decks.** Swap one-for-one.

### Head-to-head results
Historical numbers do not belong in the guide.
#### Opening hand and mulligan
Neither does a nested heading inside an excluded section.
### Further upgrades
Buy something.
""")
        parts = answer["sections"]
        self.assertEqual([x["title"] for x in parts],
                         ["Game plan", "Opening hand and mulligan", "Sideboard: against bigger decks"])
        self.assertEqual(parts[0]["markdown"], "Play cheap creatures.\n- First turn.\n  - Nested advice.")
        self.assertEqual(parts[2]["markdown"], "Swap one-for-one.")
        self.assertNotIn("Historical", json.dumps(answer))
        self.assertNotIn("Neither", json.dumps(answer))

    def test_fenced_headings_and_other_top_level_sections_do_not_leak(self):
        answer = guide("""```md
## Notes
### Game plan
Fake notes.
```
## Notes
### Game plan
Real notes.
~~~md
### Sideboard
Fake sideboard.
~~~
### Jargon used below
Real explanations.
## Other material
### Sideboard
Not in Notes.
""")
        self.assertEqual(answer["sections"], [
            {"title": "Game plan", "markdown": "Real notes."},
            {"title": "Jargon used below", "markdown": "Real explanations."}])

    def test_stale_marker_survives_and_empty_guide_stays_empty(self):
        text = GRUUL.replace("## Decklist", "*Decklist changed in Deck Lab on 2026-10-01; prose sections may be out of date.*\n\n## Decklist")
        deck = decks.parse_deck(text.encode(), kind="casual", slug="guide-test")
        self.assertEqual(playing_guide(deck), {"sections": [], "changed_on": "2026-10-01"})
        self.assertIsNone(playing_guide(None))

    def test_existing_decks_expose_gameplay_without_upgrade_recommendations(self):
        installed = pre_db.decks_inventory()       # the deck files as the pre-db-decks tag holds them
        self.addCleanup(inventory.use(installed))
        found = sorted((d for d in installed.load().decks.values() if d.space == "home" and d.error is None),
                       key=lambda d: d.id)
        if not found:
            self.skipTest(f"the repo has no {pre_db.DECKS_REV} tag (the last commit with the deck files)")
        for deck in found:
            with self.subTest(deck=deck.slug):
                answer = playing_guide(decks.parse_deck(deck.text.encode(), deck.slug, deck.kind))
                titles = [part["title"].lower() for part in answer["sections"]]
                self.assertTrue(any("game plan" in t or "how the deck wins" in t for t in titles))
                self.assertTrue(any("mulligan" in t or "opening hand" in t for t in titles))
                self.assertFalse(any("upgrades" in t or "head-to-head" in t for t in titles))


class GuideApiTests(ApiTestCase):
    def test_guide_is_shared_between_versions_and_absent_for_products(self):
        path = self.box.magic / "decks" / "casual" / "gruul-test.md"
        path.write_text(GRUUL + "\n## Notes\n\n### Game plan\nUse the existing written plan.\n", encoding="utf-8")
        target = api.deck_view("casual/gruul-test")["guide"]
        owned = api.deck_view("casual/gruul-test", "owned")["guide"]
        self.assertEqual(target, owned)
        self.assertEqual(target["sections"][0]["markdown"], "Use the existing written plan.")
        self.assertIsNone(api.deck_view("pairing/cats+elves")["guide"])
        self.assertIsNone(api.deck_view("product/fdc-test-precon")["guide"])


@unittest.skipUnless(shutil.which("node"), "Node.js isn't installed")
class GuideRenderingTests(unittest.TestCase):
    def run_js(self, expression):
        inputs = [[str(WEB / "core.js"), str(WEB / "editor.js"), str(WEB / "deck-tools.js"), str(WEB / "guide.js")], [expression]]
        done = subprocess.run([shutil.which("node"), "-e", NODE_RUNNER], input=json.dumps(inputs),
                              capture_output=True, text=True, encoding="utf-8", check=True)
        return json.loads(done.stdout)[0]

    def test_nested_lists_preserve_order_and_emphasis(self):
        text = "1. **Keep:** two lands.\n   - Both colours.\n     - A cheap spell.\n2. Mulligan otherwise."
        tree = json.loads(self.run_js(f"JSON.stringify(guideMarkdown({json.dumps(text)}))"))
        first_list = tree["children"][0]
        self.assertEqual(first_list["tag"], "ol")
        self.assertEqual(len(first_list["children"]), 2)
        first = first_list["children"][0]
        self.assertEqual(first["children"][0]["tag"], "strong")
        nested = first["children"][-1]
        self.assertEqual(nested["tag"], "ul")
        self.assertEqual(nested["children"][0]["children"][-1]["tag"], "ul")

    def test_html_and_unsafe_links_stay_text(self):
        text = '<img src=x onerror=alert(1)> [bad](javascript:alert) [read](https://example.test/guide)'
        tree = json.loads(self.run_js(f"JSON.stringify(guideMarkdown({json.dumps(text)}))"))
        children = tree["children"][0]["children"]
        self.assertFalse(any(node["tag"] == "img" for node in children))
        links = [node for node in children if node["tag"] == "a"]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["attrs"]["href"], "https://example.test/guide")
        self.assertIn("<img", children[0]["data"])

    def test_stale_warning_and_product_empty_state(self):
        page = {"summary": {"id": "casual/test", "read_only": False}, "version": "target",
                "guide": {"sections": [], "changed_on": "2026-10-01"}}
        rendered = self.run_js(f"guideSection({json.dumps(page)})")
        self.assertIn("may be out of date", rendered)
        self.assertIn("2026-10-01", rendered)
        # Whoever may edit the deck is offered the editor's Notes to write one.
        self.assertIn("No play guide yet.", rendered)
        self.assertIn("Write a game plan", rendered)
        rendered = self.run_js('guideSection({summary: {read_only: true}, guide: null})')
        self.assertIn("No play guide is recorded", rendered)


if __name__ == "__main__":
    unittest.main()
