"""A deck builder's own card categories (E2-S24): the " #Ramp" suffix on decklist lines.

The line format (parse_line, format_line, a whole block), what ignores it (equality, the Assembled
snapshot), the editor's saves through api.save_deck in test_api's Sandbox (the files backend), and the
deck page's grouping, Stats counts, Chance to draw ticks and the editor's Category… sheet under Node.

Run from the repo root: python -m unittest decklab.tests.test_deck_categories
"""
import json
import subprocess
import unittest

from decklab.lib import api, decks
from decklab.lib.decks import assembled
from decklab.tests.test_editor import TODAY, EditorTestCase
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


class LineTests(unittest.TestCase):

    def test_a_category_is_read_and_written_back(self):
        line = decks.parse_line("4 Llanowar Elves (FDN) 227 *F* #Ramp")
        self.assertEqual((line.quantity, line.name, line.set, line.number, line.finish, line.category),
                         (4, "Llanowar Elves", "fdn", "227", "foil", "Ramp"))
        self.assertEqual(decks.format_line(line), "4 Llanowar Elves (FDN) 227 *F* #Ramp")
        self.assertEqual(decks.format_line(line, category=False), "4 Llanowar Elves (FDN) 227 *F*")
        for text, category in (("1 Sol Ring #Win condition", "Win condition"), ("1 Sol Ring #!Ramp", "Ramp"),
                               ("1 Sol Ring  #ramp  ", "ramp"), ("1 Sol Ring (CMM) #R&D", "R&D"),
                               ("1 Hazmat Suit (Used) #Jokes", "Jokes"), ("2 Opt", None)):
            self.assertEqual(decks.parse_line(text).category, category, text)
        self.assertEqual(decks.parse_line("1 Hazmat Suit (Used) #Jokes").name, "Hazmat Suit (Used)")

    def test_moxfields_several_tags_keep_the_first(self):
        # Moxfield exports a card with several tags as " #Ramp #Mana Rock": one category per line, the first.
        for text in ("1 Sol Ring (CMM) 410 #Ramp #Mana Rock", "1 Sol Ring (CMM) 410 #!Ramp #!Draw",
                     "1 Sol Ring (CMM) 410 #Ramp #" + "x" * 40):
            line = decks.parse_line(text)
            self.assertEqual((line.name, line.set, line.number, line.category), ("Sol Ring", "cmm", "410", "Ramp"), text)
            self.assertEqual(decks.tag_count(text), 2, text)
        self.assertEqual(decks.format_line(decks.parse_line("1 Sol Ring #Ramp #Draw")), "1 Sol Ring #Ramp")
        self.assertEqual([decks.tag_count(t) for t in ("1 Sol Ring", "1 Sol Ring #Ramp")], [0, 1])

    def test_the_category_is_not_part_of_the_cards_identity(self):
        plain, tagged = decks.parse_line("4 Opt (FDN) 512"), decks.parse_line("4 Opt (FDN) 512 #Draw")
        self.assertEqual(plain, tagged)
        self.assertNotEqual(decks.categories({"Deck": [plain]}), decks.categories({"Deck": [tagged]}))

    def test_lines_a_category_cant_be_read_from(self):
        for text in ("1 Sol Ring #-ramp #draw", "1 Sol Ring #ramp (CMM) 410", "1 Sol Ring #", "1 Sol#Ring",
                     "1 Sol Ring #-ramp", "1 Sol Ring #" + "x" * 31):
            with self.assertRaises(decks.DecklistError, msg=text):
                decks.parse_line(text)
        for bad in ("two\nlines", "x" * 31, "-dash", "a#b"):
            with self.assertRaises(ValueError, msg=bad):
                decks.format_line(decks.DeckLine(1, "Opt", category=bad))
        self.assertEqual(decks.clean_category("  #Card   draw "), "Card draw")
        self.assertIsNone(decks.clean_category("  "))

    def test_a_block_round_trips(self):
        text = "Commander\n1 Lathril, Blade of the Elves (KHM) 221\n\nDeck\n1 Sol Ring (CMM) 410 #Ramp\n" \
               "1 Llanowar Elves #Ramp\n30 Forest\n\nSideboard\n1 Naturalize #Removal\n"
        sections = decks.parse_decklist(text)
        self.assertEqual(decks.format_decklist(sections), text)
        self.assertEqual(decks.categories(sections),
                         {"Commander": [None], "Deck": ["Ramp", "Ramp", None], "Sideboard": ["Removal"]})
        self.assertEqual(decks.card_count(sections), 33)

    def test_the_assembled_snapshot_holds_cards_not_categories(self):
        deck = decks.parse_deck(DECK.encode("utf-8"), "cats", "casual")
        self.assertEqual(deck.target["Deck"][0].category, "Ramp")
        assembled.install(deck, "target", deck.target)
        self.assertNotIn("#Ramp", assembled._value("target", deck.target))
        # The snapshot is the same cards as the list, so nothing is waiting to be installed.
        self.assertFalse(assembled.needs_install(
            decks.parse_deck(decks.render_deck_file(deck).encode("utf-8"), "cats", "casual"), "target", deck.target))


DECK = """# Cats

- **Format:** Casual 60-card, 1v1
- **Archetype:** Cats
- **Played by:** user
- **Status:** built

## Decklist

```
Deck
4 Llanowar Elves (FDN) 227 #Ramp
20 Forest
```
"""


class SaveTests(EditorTestCase):

    def test_setting_a_category_saves_it_without_a_marker_or_a_new_table(self):
        view = api.edit_view("casual/table-test")
        lists = self.edit_lists(view)
        lists["target"]["Deck"][0]["category"] = "  Ramp "
        lists["target"]["Deck"][1]["category"] = "#Ramp"
        before = self.text("casual/table-test")
        answer = self.save("casual/table-test", lists)
        self.assertEqual((answer["saved"], answer["changed"], answer["marked"]), (True, True, None))
        self.assertEqual(answer["table"]["rewritten"], False)
        text = self.text("casual/table-test")
        self.assertIn("4 Llanowar Elves (FDN) 227 #Ramp\n1 Elvish Mystic (CMM) 648 #Ramp\n1 Black Lotus (LEA) 232\n",
                      text)
        self.assertNotIn("Decklist changed", text)
        # Only the decklist block changed; the table and prose are as they were.
        self.assertEqual(text.replace(" #Ramp", ""), before)
        # The page gets the categories back, and only on lines that have one.
        lines = api.edit_view("casual/table-test")["lists"]["target"]["Deck"]
        self.assertEqual([line.get("category") for line in lines], ["Ramp", "Ramp", None, None])
        self.assertNotIn("category", lines[2])

        # Saving the same lists again changes nothing; clearing one writes it out.
        again = self.edit_lists(api.edit_view("casual/table-test"))
        self.assertFalse(self.save("casual/table-test", again)["changed"])
        again["target"]["Deck"][1].pop("category")
        self.assertTrue(self.save("casual/table-test", again)["changed"])
        self.assertIn("1 Elvish Mystic (CMM) 648\n", self.text("casual/table-test"))

    def test_a_card_change_with_categories_marks_the_list_as_usual(self):
        lists = self.edit_lists(api.edit_view("casual/table-test"))
        lists["target"]["Deck"][0].update(qty=3, category="Ramp")
        answer = self.save("casual/table-test", lists)
        self.assertEqual((answer["marked"], answer["table"]["rewritten"]), (TODAY, True))
        text = self.text("casual/table-test")
        self.assertIn("3 Llanowar Elves (FDN) 227 #Ramp\n", text)
        self.assertIn("| Llanowar Elves | 3 | 3 | 0 |", text)

    def test_a_category_a_line_cant_hold_blocks_the_save(self):
        lists = self.edit_lists(api.edit_view("casual/table-test"))
        lists["target"]["Deck"][0]["category"] = "ramp #draw"
        before = self.text("casual/table-test")
        with self.assertRaises(api.ApiError) as caught:
            self.save("casual/table-test", lists)
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("a category is 1-30", json.dumps(caught.exception.extra))
        self.assertEqual(self.text("casual/table-test"), before)

    def test_a_pasted_moxfield_tag_is_kept(self):
        answer = api.parse_list(self.body(text="4 Llanowar Elves (FDN) 227 #Ramp\n2 Elvish Mystic #!Ramp\n12 Forest\n"))
        self.assertEqual(answer["errors"], [])
        self.assertEqual([line.get("category") for line in answer["sections"]["Deck"]], ["Ramp", "Ramp", None])

    def test_a_pasted_card_with_several_moxfield_tags_keeps_its_first(self):
        answer = api.parse_list(self.body(text="4 Llanowar Elves (FDN) 227 #Ramp #Mana Dork\n12 Forest\n"))
        self.assertEqual(answer["errors"], [])
        self.assertEqual([(line["name"], line.get("category")) for line in answer["sections"]["Deck"]],
                         [("Llanowar Elves", "Ramp"), ("Forest", None)])
        self.assertTrue(any("kept its first category, Ramp" in w for w in answer["warnings"]), answer["warnings"])


class ConsideringTests(EditorTestCase):
    """A Considering line (E2-S23) holds a category as the lists' lines do, and its saves keep them."""

    def setUp(self):
        super().setUp()
        from decklab.tests.test_api import _write
        from decklab.tests.test_deck_considering import CONSIDERING_DECK
        deck = CONSIDERING_DECK.replace("1 Black Lotus (LEA) 232\n2 Elvish", "1 Black Lotus (LEA) 232 #Power\n2 Elvish")
        deck = deck.replace("4 Llanowar Elves (FDN) 227\n", "4 Llanowar Elves (FDN) 227 #Ramp\n", 1)
        _write(self.box.magic / "decks" / "casual" / "table-test.md", deck)

    def deck(self):
        return decks.parse_deck(self.text("casual/table-test").encode(), "table-test", "casual")

    def test_a_category_only_change_to_a_considering_line_is_saved(self):
        deck = self.deck()
        self.assertEqual([l.category for l in deck.considering], ["Power", None])
        lines = [decks.DeckLine(l.quantity, l.name, l.set, l.number, l.finish, l.category) for l in deck.considering]
        lines[1].category = "Draw"
        self.assertEqual(decks.apply_edit(deck, considering=lines)["considering"], True)
        self.assertIn("2 Elvish Mystic (CMM) 648 #Draw\n", decks.render_deck_file(deck))
        # Through the editor's save too.
        view = api.edit_view("casual/table-test")
        sent = view["lists"]["considering"]
        self.assertEqual(sent[0].get("category"), "Power")
        sent[1]["category"] = "Draw"
        self.assertTrue(self.save("casual/table-test", {"considering": sent})["changed"])
        self.assertEqual([l.category for l in self.deck().considering], ["Power", "Draw"])

    def test_the_considering_actions_keep_every_category(self):
        from decklab.lib.api import considering as considering_api
        body = lambda **data: self.body(id="casual/table-test", sha256=self.sha("casual/table-test"), **data)  # noqa: E731
        considering_api.save_considering(body(action="add", line={"name": "Llanowar Elves", "qty": 1}))
        deck = self.deck()
        self.assertEqual([l.category for l in deck.considering], ["Power", None, None])
        self.assertEqual(deck.target["Deck"][0].category, "Ramp")
        # A move rebuilds the Planned list from its lines: their categories, and the moved line's, stay.
        considering_api.save_considering(body(action="move", index=0, qty=1, section="Sideboard"))
        deck = self.deck()
        self.assertEqual(deck.target["Deck"][0].category, "Ramp")
        self.assertEqual([(l.name, l.category) for l in deck.target["Sideboard"]], [("Black Lotus", "Power")])
        self.assertEqual([l.category for l in deck.considering], [None, None])


FIXTURE = """
  const land = {type_line: 'Basic Land — Forest', cmc: 0};
  const elf = {type_line: 'Creature — Elf Druid', cmc: 1};
  const rock = {type_line: 'Artifact', cmc: 1};
  const data = {summary: {id: 'commander/elves', kind: 'commander'}, version: 'target', versions: ['target'], sections: {
    Commander: [{qty: 1, name: 'Lathril, Blade of the Elves', card: elf, category: 'Win condition'}],
    Deck: [{qty: 1, name: 'Sol Ring', card: rock, category: 'Ramp'}, {qty: 1, name: 'Llanowar Elves', card: elf, category: 'ramp'},
      {qty: 1, name: 'Elvish Mystic', card: elf}, {qty: 1, name: 'Elvish Mystic', set: 'cmm', card: elf, category: 'Draw'},
      {qty: 95, name: 'Forest', card: land}],
    Sideboard: [{qty: 1, name: 'Naturalize', card: rock, category: 'Removal'}]}};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PageTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_the_list_grouped_by_category_with_uncategorised_last(self):
        self.run_js("""
          const groups = deckGroups(data, 'category');
          same(groups.map((g) => [g.section, g.title, g.lines.map((l) => l.name)]), [
            ['Commander', 'Commander', ['Lathril, Blade of the Elves']],
            ['Deck', 'Draw', ['Elvish Mystic']],
            ['Deck', 'Ramp', ['Llanowar Elves', 'Sol Ring']],
            ['Deck', 'Uncategorised', ['Forest', 'Elvish Mystic']],
            ['Sideboard', 'Sideboard', ['Naturalize']]]);
          // By type it's as before.
          assert(deckGroups(data).some((g) => g.title === 'Creatures'));
          assert(!deckGroups(data).some((g) => g.title === 'Ramp'));
          assert.equal(cardsGroupingToggle({sections: {Deck: [{qty: 1, name: 'Opt'}]}}, () => {}), null);
          const toggle = cardsGroupingToggle(data, () => {});
          same(toggle.querySelectorAll('button').map((b) => b.textContent), ['Type', 'Category']);
        """)

    def test_stats_count_each_category_and_the_odds_tick_one(self):
        self.run_js("""
          same(categoryCounts(data.sections).map((c) => [c.category, c.count]),
            [['Draw', 1], ['Ramp', 2], ['Win condition', 1], ['Uncategorised', 96]]);
          // A card with copies in two categories counts each copy once, under its own line's category.
          const split = {sections: {Deck: [{qty: 2, name: 'Llanowar Elves', set: 'fdn', card: elf, category: 'Ramp'},
            {qty: 2, name: 'Llanowar Elves', set: 'm19', card: elf, category: 'Draw'}, {qty: 1, name: 'Llanowar Elves', card: elf}]}};
          same(categoryCounts(split.sections).map((c) => [c.category, c.count]),
            [['Draw', 2], ['Ramp', 2], ['Uncategorised', 1]]);
          const panel = categoriesPanel(data);
          assert(panel.textContent.includes('Your categories'));
          assert.equal(categoriesPanel({sections: {Deck: [{qty: 60, name: 'Forest', card: land}]}}), null);
          const odds = drawOddsPanel(data);
          const ramp = odds.querySelectorAll('button').find((b) => b.textContent === 'Ramp');
          ramp.click();
          const ticked = odds.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'checkbox' && i.checked);
          same(ticked.map((i) => i.value).sort(), ['Llanowar Elves', 'Sol Ring']);
          assert(odds.textContent.includes('the 2 cards ticked'));
          // Elvish Mystic has a copy given Draw, so Draw ticks the card (all its copies count, as a card's tick does).
          odds.querySelectorAll('button').find((b) => b.textContent === 'Draw').click();
          same(odds.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'checkbox' && i.checked)
            .map((i) => i.value), ['Elvish Mystic']);
        """)

    def test_the_editors_review_names_category_changes(self):
        self.run_js("""
          const base = {Deck: [{qty: 1, name: 'Sol Ring', set: 'cmm', number: '410', finish: 'nonfoil', category: 'Ramp'},
            {qty: 1, name: 'Opt', finish: 'nonfoil'}, {qty: 1, name: 'Shock', finish: 'nonfoil', category: 'Removal'}]};
          const now = {Deck: [{qty: 1, name: 'Sol Ring', set: 'cmm', number: '410', finish: 'nonfoil', category: 'Mana'},
            {qty: 1, name: 'Opt', finish: 'nonfoil', category: 'Draw'}, {qty: 1, name: 'Shock', finish: 'nonfoil'},
            {qty: 1, name: 'Duress', finish: 'nonfoil', category: 'Disruption'}]};
          same(categoryChanges(base, now).map(categoryChangeWords),
            ['Sol Ring: Ramp → Mana', 'Opt: Draw', 'Shock: no category (was Removal)']);
          same(listChanges(base, now).map((c) => c.name), ['Duress']);   // a new line is a card change, not a category one
          same(categoryChanges(base, base), []);
        """)

    def test_category_text_as_a_line_holds_it(self):
        self.run_js("""
          same(['  #Card   draw ', '', 'Ramp'].map(cleanCategory), ['Card draw', '', 'Ramp']);
          same(['Ramp', '', 'R&D', 'Win condition', '-x', 'a#b', 'x'.repeat(31)].map(validCategory),
            [true, true, true, true, false, false, false]);
        """)


if __name__ == "__main__":
    unittest.main()
