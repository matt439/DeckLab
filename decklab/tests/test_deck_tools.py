"""Selected-list export, physical availability filters, and guide card links."""
import json
import unittest
from decklab.lib import decks
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

    def test_copy_with_categories_round_trips_every_finish_tag_section_and_bare_set(self):
        value = {"sections": {"Commander": [{"qty": 1, "name": "Gisa", "set": "cmm", "number": "42", "finish": "foil", "category": "Leader"}],
            "Deck": [{"qty": 2, "name": "Sol Ring", "set": "cmm", "number": "410", "finish": "etched", "category": "Ramp"},
                     {"qty": 1, "name": "Elvish Mystic", "set": "cmm", "category": "Card draw"},
                     {"qty": 1, "name": "Fire // Ice", "set": "apc", "number": "128", "finish": "foil", "category": "R&D"}],
            "Sideboard": [{"qty": 3, "name": "Opt", "finish": "foil", "category": "Draw"}]}}
        text = self.run_js(f"exportedDeck({json.dumps(value)}, {{categories:true}})")
        parsed = decks.parse_decklist(text)
        for section, lines in value["sections"].items():
            self.assertEqual([(line.quantity, line.name, line.set, line.number, line.finish, line.category) for line in parsed[section]],
                [(line["qty"], line["name"], line.get("set"), line.get("number"), line.get("finish", "nonfoil"), line.get("category")) for line in lines])
        normal = self.run_js(f"exportedDeck({json.dumps(value)})")
        self.assertIn("*F*", normal)
        self.assertIn("*E*", normal)
        self.assertNotIn("#Ramp", normal)

    def test_guide_links_exact_known_names_with_boundaries_and_keeps_safe_text(self):
        value = self.run_js("(() => { state.cards = new Map([['Opt', {}], ['Fire // Ice', {}]]); "
            "globalThis.cardLink = entry => el('button', {text:entry.name}); "
            "return JSON.stringify(guideInline('Options: **Opt** or Fire // Ice. <script>')); })()")
        tree = json.loads(value)
        self.assertIn("Options: ", value)
        self.assertIn("<script>", value)
        self.assertEqual(sum('button' in json.dumps(item) for item in tree), 2)
