"""The Tokens page's Dice and counters panel and the deck page's covered marks (E7-S24), in the complete
page's real script order with test_feature_ui_tokens' data and an API double: no browser, no writes.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_dice_counters_ui
"""
import unittest

from decklab.tests import test_feature_ui as feature_ui
from decklab.tests import test_feature_ui_tokens as token_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DiceUiTests(unittest.TestCase):
    run_js = feature_ui.FeatureUiTests.run_js

    DICE = token_ui.TokensUiTests.TOKENS + """
      const d20 = {key: 'd0', index: 0, type: 'die', size: 'd20', kind: '', design: 'red', quantity: 2, notes: '',
        label: 'd20 (red)'};
      const poison = {key: 'd1', index: 1, type: 'counter', size: '', kind: 'poison', design: '', quantity: 5,
        notes: 'in the green box', label: 'poison counter'};
      const diceData = {space: 'home', ready: true, sha256: 'c'.repeat(64), rows: [d20, poison], items: 7, problems: [],
        types: ['die', 'counter'], sizes: ['d4', 'd6', 'd8', 'd10', 'd12', 'd20', 'spindown'], note: null};
      const calls = [];
      let diceAnswer = diceData;
      api = async (path) => { calls.push(path); if (path.startsWith('/api/dice')) return diceAnswer; return tokensData; };
      local.get = () => null; local.set = () => true;
    """

    def test_the_panel_lists_adds_and_edits_for_the_spaces_editors(self):
        self.run_js(self.DICE + """
          clear(main);
          drawTokens(tokensData, routeToken);
          await settle();
          assert(calls.includes('/api/dice'));
          const panel = main.querySelector('.dice-panel');
          const text = panel.textContent;
          for (const words of ['Dice and counters', 'd20, red', '×2', 'poison counter', 'in the green box',
                               '2 kinds, 7 items']) assert(text.includes(words), words);
          assert(labelled(panel, 'Edit d20, red'));
          // Add: a die's size, a counter's kind; the write names the list's sha and the row.
          const posted = [];
          apiWrite = async (path, body) => { posted.push([path, body]);
            return {saved: true, index: 0, data: {...diceData, rows: [d20], items: 2}}; };
          button(panel, 'Add a die or counter').click();
          const sheet = sheets()[sheets().length - 1];
          const type = sheet.querySelector('select');
          type.value = 'counter'; type.fire('change');
          sheet.querySelectorAll('input')[0].value = '+1/+1';
          sheet.querySelectorAll('input')[2].value = '12';
          button(sheet, 'Save').click();
          await settle();
          assert.equal(posted[0][0], '/api/dice/save');
          assert.deepEqual(JSON.parse(JSON.stringify(posted[0][1])), {action: 'add', sha256: 'c'.repeat(64),
            row: {type: 'counter', size: '', kind: '+1/+1', design: '', quantity: '12', notes: ''}});
          assert(!main.querySelector('.dice-panel').textContent.includes('poison counter'));    // the answer's list
          // Edit sends the row's six values as the base.
          labelled(main.querySelector('.dice-panel'), 'Edit d20, red').click();
          const edit = sheets()[sheets().length - 1];
          button(edit, 'Save').click();
          await settle();
          assert.deepEqual(JSON.parse(JSON.stringify(posted[1][1].base)),
            {type: 'die', size: 'd20', kind: '', design: 'red', quantity: '2', notes: ''});
        """)

    def test_read_only_and_before_the_migration(self):
        self.run_js(self.DICE + """
          clear(main);
          state.may = {spaces: []};
          drawTokens(tokensData, routeToken);
          await settle();
          let panel = main.querySelector('.dice-panel');
          assert(panel.textContent.includes('poison counter'));
          assert(!button(panel, 'Add a die or counter')); assert(!labelled(panel, 'Edit d20, red'));
          state.may = null;
          diceAnswer = {...diceData, ready: false, rows: [], items: 0, sha256: null, note: 'migration'};
          clear(main);
          drawTokens(tokensData, routeToken);
          await settle();
          panel = main.querySelector('.dice-panel');
          assert(panel.textContent.includes("can't be recorded yet"));
          assert(button(panel, 'Add a die or counter').disabled);
          // The token cards are drawn as before.
          assert(main.textContent.includes('3 kinds, 10 physical cards'));
        """)

    def test_the_deck_page_says_whether_each_need_is_covered(self):
        self.run_js(self.DICE + """
          clear(main);
          const used = [{name: 'A', quantity: 1, section: 'Deck'}];
          const counters = {note: 'Read from the cards.', owned: {ready: true, words: 'You have 2 dice and 5 counters; 2 stand for any kind.'},
            needs: [
              {key: 'poison', name: 'Poison counters', group: 'player', made_by: used, sideboard_only: false,
               cover: {state: 'named', words: 'You have 5 poison counters'}},
              {key: '+1/+1', name: '+1/+1 counters', group: 'permanent', made_by: used, sideboard_only: false,
               cover: {state: 'generic', words: 'A die or generic counter stands in'}},
              {key: 'd6', name: 'd6', group: 'die', made_by: used, sideboard_only: false,
               cover: {state: 'none', words: 'No d6 recorded'}}]};
          const section = tokensSection({tokens: {...deckTokensResult, needs: [], counters}});
          main.append(section);
          const items = [...section.querySelectorAll('.token-counter')];
          assert.deepEqual(items.map((i) => i.querySelector('.dice-cover').textContent),
            ['Covered', 'Any-kind stands in', 'Not covered']);
          assert(items[2].querySelector('.status-warn'));
          assert.equal(items[0].querySelector('.token-need-cover').textContent, 'You have 5 poison counters');
          assert(section.textContent.includes('You have 2 dice and 5 counters'));
        """)
