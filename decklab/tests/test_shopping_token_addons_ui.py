"""Shopping's token add-ons under Node (E5-S38): each read basket's collapsed note of the token cards
the built decks make but have none of, with how many decks want each and Copy names.

Run: python scripts/test_fixtures.py decklab.tests.test_shopping_token_addons_ui
Nothing is read or written: the answer is supplied and the clipboard is a fake.
"""
import unittest

from decklab.tests import test_shopping_baskets_ui, test_shopping_ui
from decklab.tests.test_workspace_ui import NODE

TOKENS = r"""
  const TOKENS = [{name: 'Treasure', kind: 'token', decks: 2}, {name: 'The Monarch', kind: 'reminder', decks: 1}];
  const READY = basket('mtgmate', 'MTGMate', {rows: [line('Ready', 1)], total_aud: '1.00', priced: 1, cards: 1});
  const note = key => shopNode(key)?.querySelector('[data-basket-tokens]') || null;
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingTokenAddonsTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js
    run_baskets_js = test_shopping_baskets_ui.ShoppingBasketsTests.run_baskets_js

    def run_tokens_js(self, scenario):
        self.run_baskets_js(TOKENS + scenario)

    def test_each_read_basket_has_a_collapsed_note_naming_the_tokens_and_their_decks(self):
        self.run_tokens_js(r"""
          drawShopping(answer({shops: [READY, basket('gamesportal', 'Games Portal'),
            basket('other', 'Unread shop', {read: false, fetched_at: null})]}, {token_addons: TOKENS}));
          for (const key of ['mtgmate', 'gamesportal']) {
            const details = note(key);
            assert(details, key);
            assert.equal(details.tag, 'details');
            assert.equal(details.getAttribute('open') ?? null, null); assert(!details.open);
            assert.equal(details.querySelector('summary').textContent,
              "Token cards your decks make but you don't have (not checked at this shop) (2)");
            const items = details.querySelectorAll('[data-token-addon]');
            same(items.map(item => item.getAttribute('data-token-addon')), ['Treasure', 'The Monarch']);
            assert(items[0].textContent.includes('wanted by 2 built decks'), items[0].textContent);
            assert(items[1].textContent.includes('reminder; wanted by 1 built deck'), items[1].textContent);
            assert(details.textContent.includes('no price or stock is claimed'));
            assert(!/A\$/.test(details.textContent));
          }
          assert.equal(note('other'), null);
        """)

    def test_copy_names_copies_the_names_only_and_writes_nothing(self):
        self.run_tokens_js(r"""
          drawShopping(answer({shops: [READY]}, {token_addons: TOKENS}));
          const button = note('mtgmate').querySelector('.shop-basket-token-copy');
          assert.equal(button.textContent, 'Copy names');
          assert.equal(button.getAttribute('aria-label'), 'Copy the token card names for MTGMate');
          button.click(); await settle();
          same(copies, ['Treasure\nThe Monarch\n']);
          same(messages, ['2 token names copied.']);
          // Nothing joins the basket's own copy or its rows.
          main.querySelectorAll('.shop-basket-copy')[0].click(); await settle();
          same(copies, ['Treasure\nThe Monarch\n', '1 Ready\n']);
        """)

    def test_without_a_clipboard_the_names_open_in_a_sheet(self):
        self.run_tokens_js(r"""
          navigator.clipboard = {writeText: async () => { throw new Error('denied'); }};
          const sheets = [], realSheet = openSheet;
          openSheet = (...args) => {const sheet = realSheet(...args); sheets.push(sheet); return sheet;};
          drawShopping(answer({shops: [READY]}, {token_addons: TOKENS}));
          note('mtgmate').querySelector('.shop-basket-token-copy').click(); await settle();
          assert.equal(sheets.length, 1);
          const area = sheets[0].body.querySelector('textarea');
          assert(area);
          assert.equal(area.value, 'Treasure\nThe Monarch\n');
          same(messages, []);
        """)

    def test_no_note_without_tokens_for_bad_entries_or_outside_home_records(self):
        self.run_tokens_js(r"""
          drawShopping(answer({shops: [READY]}));
          assert.equal(note('mtgmate'), null);
          clear(main);
          drawShopping(answer({shops: [READY]}, {token_addons: []}));
          assert.equal(note('mtgmate'), null);
          clear(main);
          drawShopping(answer({shops: [READY]}, {token_addons: [{name: '', decks: 1}, {name: 'Bad\u0007', decks: 1},
            {name: 'Zero', decks: 0}, {name: 'Odd', decks: '2'}, null, {name: 'Clue', kind: 'token', decks: 1}]}));
          same(note('mtgmate').querySelectorAll('[data-token-addon]').map(item => item.getAttribute('data-token-addon')), ['Clue']);
          clear(main);
          state.may = {admin: true, orders: true, see_inventory: ['home'], see_home_records: false};
          assert.equal(shopTokenAddons({data: {token_addons: TOKENS}}).length, 0);
          assert.equal(shopBasketTokenAddons({data: {token_addons: TOKENS}}, READY), null);
        """)


if __name__ == "__main__":
    unittest.main()
