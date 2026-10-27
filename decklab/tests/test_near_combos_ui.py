"""The Stats tab's Commander rules list combos one card away (E9-S25) over the real page
scripts and DOM double: the card to add, where it stands, and the bracket it would raise.

No network, server, database or simulation is needed.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = """
  const st = {
    commander: {ok: true, size: {ok: true, cards: 100, expected: 100}, commanders: ['Finneas, Ace Archer'],
      eligibility: {ok: true}, singleton: {ok: true, duplicates: [], allowed: []},
      identity: {ok: true, outside: []}, legality: {ok: true, banned: [], banned_as_companion: [], not_legal: []},
      bracket: {minimum: 1, combos: {checked: true, list_date: '2026-10-14T03:14:00+00:00', matches: []}}}
  };
  const near = (matches, changes = {}) => ({checked: true, list_date: '2026-10-14T03:14:00+00:00', version: '7.3.0',
    total: matches.length, matches, ...changes});
  const match = (held, missing, changes = {}) => ({names: [held, missing], held, missing,
    results: ['Infinite damage', 'Infinite lifegain', 'Infinite storm count'], class: 'infinite', standalone: true,
    floor: 3, raises_to: 3, url: 'https://commanderspellbook.com/combo/1-2/', ...changes});
  const item = (panel) => panel.querySelector('.checks').children.find((li) =>
    li.querySelector('.what').textContent.startsWith('One card away'));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class NearCombosUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_lists_the_card_to_add_its_availability_and_bracket(self):
        self.run_js("""
          const node = item(commanderPanel(st, {target_bracket: 2}, near([
            match('Serra Angel', 'Pelakka Wurm', {availability: {state: 'free', free: 1, on_the_way: 0, in_use: 0}}),
            match('Rampant Growth', 'Myriad Landscape', {class: 'lock', standalone: false, floor: 1, raises_to: null,
              results: ['Lock'], availability: {state: 'buy', free: 0, on_the_way: 0, in_use: 0}})], {total: 5})));
          assert.equal(node.querySelector('.what').textContent, 'One card away: 5');
          const rows = node.querySelector('.commander-combos').children;
          assert.equal(rows.length, 2);
          assert.equal(rows[0].querySelector('.status').textContent, 'Free');
          assert(rows[0].textContent.includes('Add Pelakka Wurm (with Serra Angel): Infinite damage, Infinite lifegain, …. ' +
            'Would raise the minimum bracket to 3, above the target Bracket 2.'));
          assert.equal(rows[1].querySelector('.status').textContent, 'To buy');
          assert(rows[1].textContent.includes('Add Myriad Landscape (with Rampant Growth): Lock. Commander Spellbook'));
          assert(!rows[1].textContent.includes('raise'));
          assert.equal(rows[0].querySelector('a[target="_blank"]').getAttribute('href'), 'https://commanderspellbook.com/combo/1-2/');
          assert(node.textContent.includes('free cards first'));
          assert(node.textContent.includes('The first 2 of 5'));
        """)

    def test_without_the_inventory_there_are_no_chips(self):
        self.run_js("""
          const node = item(commanderPanel(st, {}, near([match('Serra Angel', 'Pelakka Wurm')])));
          assert.equal(node.querySelector('.commander-combos').querySelectorAll('.status').length, 0);
          assert(node.textContent.includes('Would raise the minimum bracket to 3.'));
          assert(!node.textContent.includes('free cards first'));
          assert(!node.textContent.includes('The first'));
        """)

    def test_none_not_checked_and_absent(self):
        self.run_js("""
          assert(item(commanderPanel(st, {}, near([]))).textContent.includes(
            "No two-card combo in Commander Spellbook's list (of 2026-10-14) is one card in the commander's colours away."));
          const unread = item(commanderPanel(st, {}, {checked: false, reason: 'The list is missing.'}));
          assert.equal(unread.querySelector('.what').textContent, 'One card away: not checked');
          assert(unread.textContent.includes('The list is missing.'));
          assert.equal(item(commanderPanel(st, {})), undefined);
        """)


if __name__ == "__main__":
    unittest.main()
