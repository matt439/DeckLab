"""A new Commander deck started from a commander (E9-S28's New deck from it: editor-import.js's
startFromCommander, #/new?kind=commander&commander=<name>), over the real editor scripts with invented cards.
The commander goes in as one change titled with its name; a new-deck draft already holding cards is kept;
an unknown name adds nothing."""
import unittest

from decklab.tests import test_editor_keyboard_ui as keyboard, test_editor_panes_ui as panes
from decklab.tests.test_workspace_ui import NODE

SETUP = r'''
  const ghaltaCard = {name: 'Ghalta, Primal Hunger', mana_cost: '{10}{G}{G}', type_line: 'Legendary Creature — Elder Dinosaur',
    cmc: 12, color_identity: ['G'], img_small: null, default: {set: 'rix', number: '130', finish: 'nonfoil'}};
  const searched = [];
  api = async (path) => { if (!path.startsWith('/api/cards/')) return {}; searched.push(path); return {names: ['Ghalta, Primal Hunger'], did_you_mean: [], cards: [ghaltaCard]}; };
  const toasts = []; toast = (words) => toasts.push(words);
'''


@unittest.skipUnless(NODE, 'Node.js is not installed')
class CommanderStartTests(unittest.TestCase):
    def run_js(self, scenario):
        panes.EditorPanesUiTests.run_js(self, keyboard.FIXTURE + SETUP + scenario)

    def test_the_commander_goes_in_as_one_change(self):
        self.run_js(r'''
          location.hash = '#/new?kind=commander&commander=Ghalta%2C+Primal+Hunger';
          startEditor({mode: 'new', kind: 'commander', restoreDraft: false});
          const ed = editor, before = ed.history.length;
          assert.equal(await startFromCommander('Ghalta, Primal Hunger'), true);
          same(searched, ['/api/cards/search?q=Ghalta%2C%20Primal%20Hunger&limit=20&detail=1']);
          same(ed.lists.Commander.map((l) => [l.qty, l.name, l.set, l.number]), [[1, 'Ghalta, Primal Hunger', 'rix', '130']]);
          assert.equal(ed.fields.title, 'Ghalta, Primal Hunger');
          assert.equal(ed.fields.kind, 'commander');
          assert.equal(ed.addSection, 'Deck');
          assert.equal(ed.history.length, before + 1);
          assert(ed.dirty);
        ''')

    def test_a_draft_with_cards_is_kept_and_an_unknown_name_adds_nothing(self):
        self.run_js(r'''
          startEditor({mode: 'new', kind: 'commander', restoreDraft: false});
          let ed = editor;
          ed.lists.Deck = [newLine({qty: 1, name: elves.name, card: elves})];
          assert.equal(await startFromCommander('Ghalta, Primal Hunger'), false);
          same(searched, []);
          assert(!ed.lists.Commander || !ed.lists.Commander.length);
          assert(toasts.some((t) => t.includes("Ghalta, Primal Hunger wasn't added")), toasts.join('|'));
          startEditor({mode: 'new', kind: 'commander', restoreDraft: false});
          ed = editor;
          assert.equal(await startFromCommander('Nobody At All'), false);
          assert(!ed.lists.Commander || !ed.lists.Commander.length);
          assert(toasts.some((t) => t.includes("Nobody At All isn't a card Deck Lab knows")), toasts.join('|'));
        ''')


if __name__ == '__main__':
    unittest.main()
