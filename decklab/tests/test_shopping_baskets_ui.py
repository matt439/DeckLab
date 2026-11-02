"""Shopping's Baskets under Node (E5-S27, first slice): one basket a shop from the saved checks.

Run: python scripts/test_fixtures.py decklab.tests.test_shopping_baskets_ui
Nothing is read or written: the answer is supplied and the clipboard is a fake.
"""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingBasketsTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_baskets_js(self, scenario):
        self.run_js(r"""
          state.may = {admin: false, orders: false, see_inventory: ['home'], see_home_records: true};
          api = () => { throw new Error('Baskets must not read'); };
          apiWrite = () => { throw new Error('Baskets must not write'); };
          const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
          const messages = [], copies = [];
          toast = text => messages.push(text);
          navigator.clipboard = {writeText: async text => copies.push(text)};
          const AT = '2026-11-01T02:00:00+11:00';
          const line = (name, number, extra = {}) => ({queue_row: number, name, quantity: '1', state: 'ready', for: 'Otters',
            printing: 'any', set: '', collector_number: '', finish: '', is_token: false, status: 'in_stock', fetched_at: AT,
            carried: false, add_on: false, copies: 1, short: false, line_aud: '1.00',
            listing: {set: 'fdn', collector_number: '1', finish: 'nonfoil', price_aud: '1.00', stock: 3,
              url: 'https://www.mtgmate.com.au/cards/X/FDN/1'}, ...extra});
          const basket = (key, shop, extra = {}) => ({key, shop, site: '', read: true, counts_stock: key === 'mtgmate',
            fetched_at: AT, started_at: AT, rows: [], add_ons: [], unconfirmed: [], unknown: [], not_checked: [],
            total_aud: null, priced: 0, unpriced: 0, cards: 0,
            add_ons_totals: {total_aud: null, priced: 0, unpriced: 0, cards: 0}, ...extra});
          const answer = (baskets, extra = {}) => ({...empty, queue_revision: 'q1',
            to_buy: [row('Sol Ring', 1, {queue_row: 1})], baskets: {queue_revision: 'q1', unavailable: [], ...baskets}, ...extra});
          const section = () => main.querySelector('#shop-baskets')?.closest('section') || null;
          const shopNode = key => section().querySelectorAll('[data-basket]').find(node => node.getAttribute('data-basket') === key);
          const copyButton = shop => main.querySelectorAll('.shop-basket-copy').find(button => button.dataset.copyShop === shop);
        """ + scenario)

    def test_each_shop_lists_its_rows_prices_fetch_time_and_total(self):
        self.run_baskets_js(r"""
          drawShopping(answer({shops: [
            basket('mtgmate', 'MTGMate', {rows: [line('Sol Ring', 1, {copies: 2, quantity: '2', line_aud: '5.00',
              listing: {set: 'fdn', collector_number: '1', finish: 'nonfoil', price_aud: '2.50', stock: 4, url: 'https://www.mtgmate.com.au/cards/X/FDN/1'}})],
              total_aud: '5.00', priced: 1, unpriced: 0, cards: 2}),
            basket('gamesportal', 'Games Portal', {rows: [line('Sol Ring', 1, {line_aud: null,
              listing: {set: 'fdn', collector_number: '1', finish: 'nonfoil', price_aud: null, stock: null, url: null}}),
              line('Elves', 2, {line_aud: '0.50', listing: {set: 'm19', collector_number: '2', finish: 'nonfoil', price_aud: '0.50', stock: null, url: null}})],
              total_aud: '0.50', priced: 1, unpriced: 1, cards: 2})]}));
          const mtg = shopNode('mtgmate'), gp = shopNode('gamesportal');
          assert(mtg.textContent.includes('2 × Sol Ring'));
          assert(mtg.textContent.includes('A$2.50 each'));
          assert(mtg.textContent.includes('4 in stock'));
          assert(mtg.querySelector('.shop-basket-total').textContent.includes('Total A$5.00 for 1 priced row'));
          assert(mtg.querySelector('time'));
          assert(gp.textContent.includes('price not shown'));
          assert(gp.textContent.includes('in stock (count not shown)'));
          assert.equal(gp.querySelector('.shop-basket-total').textContent, 'Total A$0.50 for 1 priced row; 1 row without a price');
          assert(main.querySelector('.shop-jumps').querySelectorAll('a').some(link => link.getAttribute('href') === '#shop-baskets'));
        """)

    def test_an_unread_shop_and_unchecked_rows_claim_no_stock(self):
        self.run_baskets_js(r"""
          drawShopping(answer({shops: [basket('mtgmate', 'MTGMate', {not_checked: [line('Late', 3, {status: 'not_checked'})],
              unknown: [line('Broken', 4, {status: 'unknown'})], unconfirmed: [line('Exact', 5, {status: 'unconfirmed'})]}),
            basket('gamesportal', 'Games Portal', {read: false, fetched_at: null})],
            unavailable: [{queue_row: 3, name: 'Late', quantity: '1', shops: [{shop: 'MTGMate', status: 'not_checked'},
              {shop: 'Games Portal', status: 'unread'}]}]}));
          const mtg = shopNode('mtgmate'), gp = shopNode('gamesportal');
          assert(mtg.textContent.includes('No ready rows in stock here.'));
          assert(mtg.textContent.includes("Not in this shop's last check: Late"));
          assert(mtg.textContent.includes("Couldn't be read here: Broken"));
          assert(mtg.textContent.includes('Printing not confirmed here, so no stock is claimed: Exact'));
          assert.equal(mtg.querySelector('.shop-basket-copy'), null);
          assert(gp.textContent.includes("couldn't be read, so no stock is claimed there"));
          assert.equal(gp.querySelector('.shop-basket-rows'), null);
          const missing = section().querySelector('[data-basket-unavailable]');
          assert.equal(missing.getAttribute('data-basket-unavailable'), 'Late');
          assert(missing.textContent.includes('MTGMate: not checked'));
          assert(missing.textContent.includes('Games Portal: no saved check'));
        """)

    def test_add_ons_are_marked_and_not_copied(self):
        self.run_baskets_js(r"""
          drawShopping(answer({shops: [basket('mtgmate', 'MTGMate', {rows: [line('Ready', 1)], total_aud: '1.00', priced: 1, cards: 1,
            add_ons: [line('Later', 2, {state: 'long_term', add_on: true})],
            add_ons_totals: {total_aud: '1.00', priced: 1, unpriced: 0, cards: 1}})]}));
          const mtg = shopNode('mtgmate'), addOns = mtg.querySelector('.shop-basket-addons');
          assert(addOns.textContent.includes('Add-ons in stock here'));
          assert(addOns.querySelector('.status').textContent.includes('Add-on'));
          assert(!mtg.querySelector('.shop-basket-rows').textContent.includes('Add-on'));
          copyButton('MTGMate').click(); await settle();
          same(copies, ['1 Ready\n']); same(messages, ['1 card copied for MTGMate.']);
        """)

    def test_copy_takes_exactly_the_baskets_rows_with_exact_printings_and_counted_copies(self):
        self.run_baskets_js(r"""
          const view = drawShopping(answer({shops: [basket('mtgmate', 'MTGMate', {rows: [
            line('Fire // Ice', 1, {quantity: '4', copies: 2, short: true, printing: 'exact', set: 'mh2', collector_number: '290', finish: 'nonfoil'}),
            line('Elves', 2, {quantity: '3', copies: 3})]})]}));
          const button = copyButton('MTGMate');
          assert.equal(button.getAttribute('aria-label'), "Copy this shop's list for MTGMate");
          assert(shopNode('mtgmate').textContent.includes('only 3 of 4 in stock'));
          button.click(); await settle();
          same(copies, ['2 Fire // Ice (MH2) 290 [nonfoil]\n3 Elves\n']);
          same(messages, ['5 cards copied for MTGMate.']);
          assert.equal(main.querySelectorAll('.shop-queue-write').length, 0);
        """)

    def test_an_any_row_filled_from_several_printings_names_each_and_copies_every_copy(self):
        self.run_baskets_js(r"""
          drawShopping(answer({shops: [basket('mtgmate', 'MTGMate', {rows: [
            line('Elves', 1, {quantity: '4', copies: 4, stock: 4, line_aud: '1.90',
              listing: {set: 'fdn', collector_number: '227', finish: 'nonfoil', price_aud: '0.40', stock: 1, copies: 1,
                url: 'https://www.mtgmate.com.au/cards/X/FDN/227'},
              more: [{set: 'm19', collector_number: '314', finish: 'nonfoil', price_aud: '0.50', stock: 3, copies: 3,
                url: 'https://www.mtgmate.com.au/cards/X/M19/314'}]})], total_aud: '1.90', priced: 1, cards: 4})]}));
          const text = shopNode('mtgmate').textContent;
          assert(text.includes('4 × Elves'), text);
          assert(text.includes('1 × FDN 227'), text);
          assert(text.includes('4 in stock across 2 printings'), text);
          assert(text.includes('also 3 × M19 314 A$0.50 each'), text);
          assert(text.includes('A$1.90'), text);
          assert(!text.includes('only'), text);
          copyButton('MTGMate').click(); await settle();
          same(copies, ['4 Elves\n']);
        """)

    def test_a_changed_queue_disables_copy_until_shopping_is_refreshed(self):
        self.run_baskets_js(r"""
          const view = drawShopping(answer({shops: [basket('mtgmate', 'MTGMate', {rows: [line('Ready', 1)]})]}));
          view.data.queue_revision = 'q2'; view.redraw();
          assert(section().textContent.includes('The queue changed since these baskets were worked out'));
          const button = copyButton('MTGMate'); assert(button.disabled);
          button.click(); await settle();
          same(copies, []);
        """)

    def test_no_baskets_without_a_snapshot_or_for_a_viewer_outside_home_records(self):
        self.run_baskets_js(r"""
          drawShopping({...empty, queue_revision: 'q1', to_buy: [row('Sol Ring', 1, {queue_row: 1})]});
          assert.equal(main.querySelector('#shop-baskets'), null);
          clear(main);
          state.may = {admin: true, orders: true, see_inventory: ['home'], see_home_records: false};
          drawShopping(answer({shops: [basket('mtgmate', 'MTGMate', {rows: [line('Ready', 1)]})]}));
          assert.equal(main.querySelector('#shop-baskets'), null);
          assert.equal(main.querySelector('.shop-basket-copy'), null);
        """)


if __name__ == "__main__":
    unittest.main()
