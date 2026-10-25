"""Selected-list export, physical availability filters, and guide card links."""
import json
import unittest
from decklab.tests.test_web import NODE, _run_page


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckToolsTests(unittest.TestCase):
    def run_js(self, expression):
        return _run_page([expression], names=("core.js", "deck-tools.js", "guide.js"))[0]

    def test_readiness_does_not_treat_incoming_or_unknown_as_ready(self):
        result = self.run_js("JSON.stringify(["
            "matchesReadiness({missing:{target:0},on_the_way:{target:0}},'ready'),"
            "matchesReadiness({missing:{target:0},on_the_way:{target:2}},'ready'),"
            "matchesReadiness({missing:{target:0},on_the_way:{target:2}},'waiting'),"
            "matchesReadiness({missing:{target:2},on_the_way:{target:2}},'missing'),"
            "matchesReadiness({missing:{target:0}},'ready'),"
            "matchesReadiness({error:'broken',missing:{target:0},on_the_way:{target:0}},'unknown'),"
            "matchesReadiness({missing:{target:0},on_the_way:{target:0},availability_confirmed:{target:false}},'ready')])")
        self.assertEqual(json.loads(result), [True, False, True, True, False, True, False])

    def test_export_preserves_selected_cards_faces_sections_and_printing(self):
        value = {"sections": {"Commander": [{"qty": 1, "name": "Gisa", "set": "cmm", "number": "42"}],
                              "Deck": [{"qty": 20, "name": "Swamp"}, {"qty": 1, "name": "Fire // Ice", "set": "apc", "number": "128"}],
                              "Sideboard": [{"qty": 2, "name": "Opt"}]}}
        text = self.run_js(f"exportedDeck({json.dumps(value)})")
        self.assertEqual(text, "Commander\n1 Gisa (CMM) 42\n\nDeck\n20 Swamp\n1 Fire // Ice (APC) 128\n\nSideboard\n2 Opt\n")

    def test_guide_links_exact_known_names_with_boundaries_and_keeps_safe_text(self):
        value = self.run_js("(() => { state.cards = new Map([['Opt', {}], ['Fire // Ice', {}]]); "
            "globalThis.cardLink = entry => el('button', {text:entry.name}); "
            "return JSON.stringify(guideInline('Options: **Opt** or Fire // Ice. <script>')); })()")
        tree = json.loads(value)
        self.assertIn("Options: ", value)
        self.assertIn("<script>", value)
        self.assertEqual(sum('button' in json.dumps(item) for item in tree), 2)
