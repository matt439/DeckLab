"""The compact To buy table (E5-S26): Ref AUD holds the price and one snapshot marker, the full
MTGMate snapshot sits in the row's extra row, and unknowns are short spoken dashes."""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingQueueCompactTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_compact_js(self, scenario):
        self.run_js("""
          state.may = {admin: true, orders: true, see_inventory: ['home']};
          const snap = (extra = {}) => ({shop: 'MTGMate', status: 'in_stock', fetched_at: '2026-10-28T03:05:00+11:00',
            price_aud: '4.50', stock: 2, set: '40k', collector_number: '249', finish: 'nonfoil',
            url: 'https://www.mtgmate.com.au/cards/Sol_Ring/40K/249', in_stock_printings: 2, error: null,
            back_in_stock: false, newly_in_stock: false, ...extra});
          const density = lab => {const query=window.matchMedia(SHOP_QUEUE_LAB); query.matches=lab; query.fire('change');};
          const draw = queue => drawShopping({...empty, queue_revision: 'q1', to_buy: queue, queue_decks: []});
          const entry = n => main.querySelectorAll('[data-shop-queue]').find(node=>Number(node.getAttribute('data-shop-queue'))===n);
          const extraOf = n => main.querySelectorAll('.shop-q-extra').find(node=>node.id===entry(n).querySelector('.shop-q-more')?.getAttribute('aria-controls'));
          toast=()=>{};
        """ + scenario)

    def test_snapshot_row_keeps_price_and_marker_and_moves_the_full_snapshot_to_the_extra_row(self):
        self.run_compact_js("""
          density(true);
          draw([row('Sol Ring', {queue_row: 1, listed_aud: '6.00', listed_at: 'Card shop', checked: '2026-10-01',
            in_stock: 'yes', shop_snapshot: snap()})]);
          const price = entry(1).querySelector('.shop-q-price'), mark = price.querySelector('.shop-q-snap');
          assert(mark, 'one snapshot marker in the price cell');
          assert.equal(price.querySelectorAll('.shop-q-snap').length, 1);
          assert.equal(price.querySelector('.shop-snapshot'), null, 'the full snapshot is not in the price cell');
          assert.equal(price.textContent, '6.00\\u2022');
          assert.equal(mark.getAttribute('role'), 'img');
          assert.equal(mark.getAttribute('aria-label'), 'MTGMate: A$4.50, 2 in stock (40K 249)');
          assert.equal(mark.getAttribute('title'), mark.getAttribute('aria-label'));
          const more = entry(1).querySelector('.shop-q-more');
          assert(more, 'a row with only a snapshot still offers the extra row');
          assert.equal(more.getAttribute('aria-label'), 'Show shop snapshot for Sol Ring');
          const extra = extraOf(1); assert(extra); assert.equal(extra.hidden, true);
          const full = extra.querySelector('.shop-snapshot');
          assert(full.textContent.includes('MTGMate: A$4.50, 2 in stock'));
          assert.equal(full.querySelector('time').getAttribute('datetime'), '2026-10-28T03:05:00+11:00');
          assert.equal(full.querySelector('a').getAttribute('href'), 'https://www.mtgmate.com.au/cards/Sol_Ring/40K/249');
          more.click(); assert.equal(extra.hidden, false); assert.equal(more.getAttribute('aria-expanded'), 'true');
          assert.equal(main.querySelectorAll('.shop-snapshot').length, 1, 'the snapshot is moved, never cloned');
        """)

    def test_notes_and_snapshot_name_both_in_the_disclosure(self):
        self.run_compact_js("""
          density(true);
          draw([row('Sol Ring', {queue_row: 1, notes: 'Keep me', shop_snapshot: snap()})]);
          assert.equal(entry(1).querySelector('.shop-q-more').getAttribute('aria-label'), 'Show shop snapshot and notes for Sol Ring');
          const body = extraOf(1).querySelector('.shop-q-extra-body');
          assert(body.textContent.includes('Keep me')); assert(body.querySelector('.shop-snapshot'));
        """)

    def test_unknown_row_uses_short_spoken_dashes_and_no_marker_or_extra_row(self):
        self.run_compact_js("""
          density(true);
          draw([row('Gamma', {queue_row: 1, shop_snapshot: null})]);
          for (const [cls, words] of [['price', 'Reference price not recorded'], ['shop', 'Shop not recorded'],
              ['stock', 'Stock not recorded'], ['checked', 'Check date not recorded']]) {
            const cell = entry(1).querySelector(`.shop-q-${cls}`), mark = cell.querySelector('.cell-unknown');
            assert.equal(cell.textContent, '\\u2014', cls);
            assert.equal(mark.getAttribute('aria-label'), words); assert.equal(mark.getAttribute('title'), words);
            assert.equal(mark.getAttribute('role'), 'img');
          }
          assert.equal(entry(1).querySelector('.shop-q-snap'), null);
          assert.equal(entry(1).querySelector('.shop-q-more'), null);
        """)

    def test_unknown_snapshot_marker_never_shows_a_price_or_the_raw_error(self):
        self.run_compact_js("""
          density(true);
          draw([row('Alpha', {queue_row: 1, shop_snapshot: snap({status: 'unknown', price_aud: null, stock: null,
            set: null, url: null, error: 'SECRET raw error'})})]);
          const mark = entry(1).querySelector('.shop-q-snap');
          assert.equal(mark.getAttribute('aria-label'), "MTGMate: price unknown, the shop couldn't be read");
          assert(!mark.getAttribute('aria-label').includes('A$')); assert(!mark.getAttribute('title').includes('SECRET'));
          assert.equal(entry(1).querySelector('.shop-q-price').querySelector('.cell-unknown').getAttribute('aria-label'), 'Reference price not recorded');
        """)

    def test_back_in_stock_stays_visible_at_a_glance(self):
        self.run_compact_js("""
          density(true);
          draw([row('Sol Ring', {queue_row: 1, state: 'waiting_for_stock', in_stock: 'no', listed_aud: '5.00',
            shop_snapshot: snap({back_in_stock: true, newly_in_stock: true})})]);
          const node = entry(1), mark = node.querySelector('.shop-q-price').querySelector('.shop-q-snap');
          assert(node.getAttribute('class').includes('shop-queue-back'));
          assert.equal(mark.textContent, 'Back');
          assert(mark.getAttribute('class').includes('shop-q-snap-back'));
          assert(mark.getAttribute('aria-label').startsWith('Back in stock. MTGMate: A$4.50, 2 in stock'));
          assert(extraOf(1).querySelector('.shop-snapshot').textContent.includes('Back in stock'));
        """)

    def test_casual_layout_keeps_the_full_snapshot_in_the_card(self):
        self.run_compact_js("""
          density(false);
          draw([row('Sol Ring', {queue_row: 1, listed_aud: '6.00', listed_at: 'Card shop', shop_snapshot: snap({back_in_stock: true})})]);
          assert.equal(main.querySelector('.shop-queue-table'), null);
          const card = entry(1);
          assert.equal(card.querySelector('.shop-snapshot').parentNode, card, 'the snapshot line sits under the card');
          assert(card.querySelector('.shop-snapshot').textContent.includes('Back in stock'));
          assert.equal(main.querySelector('.shop-q-snap'), null);
          assert.equal(main.querySelector('.shop-q-more'), null);
          density(true); assert(entry(1).querySelector('.shop-q-snap'));
          density(false);
          assert.equal(entry(1).querySelector('.shop-snapshot').parentNode, entry(1), 'the snapshot returns to the card');
        """)


if __name__ == "__main__":
    unittest.main()
