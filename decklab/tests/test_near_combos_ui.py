"""The Stats tab's "One card away" panel (E9-S25, deck-near-combos.js) under Node: the combos a Commander deck
is one card away from, free pieces first, each missing card's availability only when the server sent it, what
it would do to the bracket against the deck's aim, and Add to Considering (POST /api/deck/considering) for
whoever may change the deck.

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js; nothing is sent to a server.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + """
  const near = (missing, extra = {}) => Object.assign({names: ['Elf', missing], missing, results: ['Infinite mana'],
    class: 'infinite', standalone: true, floor: 3, url: 'https://commanderspellbook.com/combo/1-2/', minimum_with: 3,
    raises_minimum: true, aud: 1.5, considering: false}, extra);
  const withNear = (matches, extra = {}) => { const page = makePage();
    page.summary.kind = 'commander'; page.summary.target_bracket = 2;
    page.considering = {sha256: 'a'.repeat(64), lines: []};
    page.stats = {commander: {bracket: {near_combos: Object.assign({checked: true, total: matches.length, matches,
      prices: {rate: 1.5, rate_date: '2026-10-27', price_date: '2026-10-26'}}, extra)}}};
    return page; };
  const writes = [];
  api = async (path, opts) => { writes.push([path, JSON.parse(opts.body)]); return {saved: true}; };
  route = () => {}; toast = () => {};
  const settle = async () => { for (let i = 0; i < 6; i += 1) await Promise.resolve(); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class NearCombosUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_free_pieces_first_with_price_and_bracket(self):
        self.run_js("""
          const part = nearCombosPanel(withNear([
            near('Buy Me', {availability: 'to_buy'}),
            near('Spare', {availability: 'free', raises_minimum: false, minimum_with: 1}),
            near('Coming', {availability: 'on_the_way'})]));
          assert.equal(part.querySelector('h3').textContent, 'One card away: 3');
          const items = part.querySelectorAll('.near-combo');
          assert.equal(items.length, 3);
          assert(items[0].textContent.startsWith('Add Spare: with Elf, Infinite mana.'), items[0].textContent);
          assert(items[0].textContent.includes('Free in the pool'));
          assert(!items[0].textContent.includes('Bracket'), items[0].textContent);
          assert(items[1].textContent.includes('On the way'));
          assert(items[2].textContent.includes('To buy'));
          assert(items[2].textContent.includes('About A$1.50.'));
          assert(items[2].textContent.includes('Adding it puts the deck at Bracket 3 or higher, above the Bracket 2 it aims for.'),
            items[2].textContent);
          assert(part.textContent.includes('1 USD = 1.5 AUD'));
        """)

    def test_no_availability_without_the_collection_and_no_button_for_a_reader(self):
        self.run_js("""
          const page = withNear([near('Spare'), near('Listed', {considering: true})]);
          page.summary.read_only = true;
          const part = nearCombosPanel(page);
          const text = part.textContent;
          assert(!text.includes('Free in the pool') && !text.includes('To buy'), text);
          assert.equal(part.querySelectorAll('button').length, 0);
          assert(text.includes('On the Considering list.'));
          // No answer (an older server, a deck without a commander): no panel.
          const none = makePage(); none.stats = {commander: {bracket: {}}};
          assert.equal(nearCombosPanel(none), null);
        """)

    def test_add_to_considering_is_a_save_and_long_lists_fold(self):
        self.run_js("""
            const many = Array.from({length: 10}, (_, i) => near(`Card ${i}`));
            const part = nearCombosPanel(withNear(many, {total: 140}));
            assert.equal(part.querySelectorAll('.near-combo').length, 8);
            assert(part.textContent.includes('Showing the 10 most serious of 140.'));
            buttonText(part, 'Show all 10').click();
            assert.equal(part.querySelectorAll('.near-combo').length, 10);
            buttonText(part, 'Add to Considering').click();
            await settle();
            assert.equal(writes.length, 1);
            assert.equal(writes[0][0], '/api/deck/considering');
            assert.deepEqual({action: writes[0][1].action, line: writes[0][1].line, sha256: writes[0][1].sha256},
              {action: 'add', line: {name: 'Card 0', qty: 1}, sha256: 'a'.repeat(64)});
        """)

    def test_a_refused_add_turns_the_button_back_on(self):
        self.run_js("""
            const toasts = [];
            toast = (text) => toasts.push(text);
            api = async () => { throw new ApiError(409, "The deck was saved since."); };
            const part = nearCombosPanel(withNear([near('Spare')]));
            const button = buttonText(part, 'Add to Considering');
            button.click();
            assert.equal(button.disabled, true);
            await settle();
            assert.equal(button.disabled, false);
            assert.deepEqual(toasts, ['The deck was saved since.']);
            // A save that went through leaves it off (the deck is drawn again from the saved deck).
            api = async () => ({saved: true});
            button.click();
            await settle();
            assert.equal(button.disabled, true);
        """)


if __name__ == "__main__":
    unittest.main()
