"""Basket/plan order hand-off conserves counted copies and never carries market prices."""
import unittest

from decklab.tests import test_shopping_ui as fixture
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingBasketOrderTests(unittest.TestCase):
    run_js = fixture.ShoppingInteractionTests.run_js

    def seed_js(self, scenario):
        self.run_js("""
          state.profile = {id: 'matt', role: 'admin', space: 'home'};
          state.may = {admin: true, orders: true, see_inventory: ['home']};
          const queued = row('Alpha', {queue_row: 1, quantity: 5, notes: 'Keep queue note', buy_under_aud: '9.00'});
          const listing = (copies, extra = {}) => ({set: 'fdn', collector_number: '227', finish: 'nonfoil', copies,
            price_aud: '2.50', stock: copies, condition: 'Near Mint', language: 'English', url: 'https://example.com/listing', ...extra});
          const item = {queue_row: 1, name: 'Alpha', quantity: '5', state: 'ready', status: 'in_stock', copies: 4,
            carried: false, is_token: false, add_on: false, listing: listing(1), more: [listing(3, {set: 'm19', collector_number: '314'})]};
          const basket = {key: 'mtgmate', shop: 'MTGMate', read: true, rows: [item], add_ons: [{name: 'Later', copies: 3}]};
          const root = el('div'); main.append(root);
          const view = {root, token: routeToken, profile: state.profile.id, busy: false, stale: false,
            data: {...empty, queue_revision: 'q1', to_buy: [queued], baskets: {queue_revision: 'q1', shops: [basket]}}};
        """ + scenario)

    def test_basket_preserves_every_listing_count_and_seeds_no_market_or_quality_fields(self):
        self.seed_js("""
          const before = JSON.stringify(view.data), seed = shopBasketOrderSeed(view, basket, basket);
          same(seed, {expect: 'q1', seller: 'MTGMate', ordered_on: shopOrderToday(), cards: [
            {name: 'Alpha', set: 'fdn', collector_number: '227', finish: 'nonfoil', quantity: 1, condition: '', language: '', notes: ''},
            {name: 'Alpha', set: 'm19', collector_number: '314', finish: 'nonfoil', quantity: 3, condition: '', language: '', notes: ''}],
            fulfils: [{row: 1, quantity: 4}]});
          assert.equal(JSON.stringify(view.data), before);
          for (const word of ['price_aud', 'buy_under', 'condition":"Near', 'https:', 'Keep queue note', 'Later']) assert(!JSON.stringify(seed).includes(word));
        """)

    def test_plan_takes_only_its_prefix_and_same_printing_variants_merge_without_guessing_quality(self):
        self.seed_js("""
          const selected = {key: 'mtgmate', shop: 'MTGMate', rows: [{queue_row: 1, name: 'Alpha', state: 'ready', copies: 2}]};
          view.data.baskets.plan = {recommended: {shops: [selected]}};
          let seed = shopBasketOrderSeed(view, selected, basket);
          same(seed.cards.map(card => [card.set, card.quantity]), [['fdn', 1], ['m19', 1]]);
          same(seed.fulfils, [{row: 1, quantity: 2}]);
          item.more = [listing(3, {condition: 'Lightly Played', language: 'Japanese'})];
          seed = shopBasketOrderSeed(view, selected, basket);
          assert.equal(seed.cards.length, 1); assert.equal(seed.cards[0].quantity, 2);
          assert.equal(seed.cards[0].condition, ''); assert.equal(seed.cards[0].language, '');
          item.more = []; delete item.listing.copies;
          seed = shopBasketOrderSeed(view, selected, basket); assert.equal(seed.cards[0].quantity, 2);
        """)

    def test_stale_private_or_uncertain_input_has_no_handoff_and_never_partially_seeds(self):
        self.seed_js("""
          for (const patch of [{read: false}, {rows: [{...item, carried: true}]}, {rows: [{...item, copies: 6}]},
              {rows: [{...item, more: [listing(2)]}]}, {rows: [{...item, listing: {...item.listing, finish: ''}}]},
              {rows: [item, item]}, {rows: [{...item, state: 'long_term'}]}, {rows: [{...item, is_token: true}]}]) {
            const old = {...basket}; Object.assign(basket, patch); assert.equal(shopBasketOrderSeed(view, basket, basket), null); Object.assign(basket, old);
          }
          view.data.queue_revision = 'q2'; assert.equal(shopBasketOrderButton(view, basket), null); view.data.queue_revision = 'q1';
          for (const may of [{...state.may, admin: false, orders: false}, {...state.may, see_home_records: false}]) {
            const previous = state.may; state.may = may; assert.equal(shopBasketOrderButton(view, basket), null); state.may = previous;
          }
          state.profile.role = 'member'; assert.equal(shopBasketOrderButton(view, basket), null); state.profile.role = 'admin';
          view.stale = true; assert.equal(shopBasketOrderButton(view, basket), null);
        """)

    def test_button_revalidates_current_queue_source_person_and_connected_control_without_any_write(self):
        self.seed_js("""
          const calls = []; shopOrderSheet = (...args) => calls.push(args);
          apiWrite = () => {throw new Error('Opening must not save');};
          const button = shopBasketOrderButton(view, basket); root.append(button);
          view.data.queue_revision = 'q2'; button.click(); assert.equal(calls.length, 0); view.data.queue_revision = 'q1';
          state.profile = {id: 'user1', role: 'member', space: 'home'}; button.click(); assert.equal(calls.length, 0);
          state.profile = {id: 'matt', role: 'admin', space: 'home'};
          const nested = openSheet({title: 'Another action'}); button.click(); assert.equal(calls.length, 0); nested.close();
          button.remove(); button.click(); assert.equal(calls.length, 0); root.append(button);
          button.click(); assert.equal(calls.length, 1); assert.equal(calls[0][0], view); assert.equal(calls[0][1].cards.length, 2);
        """)

    def test_seeded_sheet_uses_normal_preview_and_token_save_with_exact_copies_and_unchecked_addons(self):
        self.seed_js("""
          const writes = [], messages = []; let routes = 0;
          toast = words => messages.push(words); route = () => {routes += 1;};
          apiWrite = async (path, body) => {writes.push([path, body]); return path.endsWith('/preview')
            ? {preview: 'normal-order-review', tables: {written: [], skipped: []}} : {saved: true};};
          view.data.to_buy.push(row('Later', {queue_row: 2, quantity: 3, state: 'long_term'}));
          const before = JSON.stringify(view.data), seed = shopBasketOrderSeed(view, basket, basket);
          const sheet = shopOrderSheet(view, seed), field = key => sheet.body.querySelector(`[data-order-field=${key}]`);
          const action = text => sheet.foot.querySelectorAll('button').find(item => item.textContent === text);
          const tick = async () => {for (let n = 0; n < 10; n++) await null;};
          assert.equal(field('seller').value, 'MTGMate'); assert.equal(field('ordered_on').value, shopOrderToday());
          assert.equal(field('id').value, `${shopOrderToday()}-mtgmate`);
          assert.equal(sheet.body.querySelector('[data-order-fulfils=1]').checked, true);
          assert.equal(sheet.body.querySelector('[data-order-fulfils-quantity=1]').value, '4');
          assert(!sheet.body.querySelector('[data-order-fulfils=2]').checked);
          assert(sheet.body.querySelector('.shop-order-seed').textContent.includes('need checking'));
          same(writes, []); action('Preview order').click(); await tick();
          assert.equal(writes[0][0], '/api/shopping/order/preview');
          same(writes[0][1].cards, {rows: seed.cards, checks: []}); same(writes[0][1].fulfils, [{row: 1, quantity: 4}]);
          assert.equal(writes[0][1].expect, 'q1');
          for (const value of ['price_aud', 'buy_under', 'Near Mint', 'English', 'Keep queue note', 'Later']) assert(!JSON.stringify(writes[0][1]).includes(value));
          assert.equal(JSON.stringify(view.data), before);
          action('Save order').click(); await tick();
          same(writes[1], ['/api/shopping/order/apply', {preview: 'normal-order-review'}]);
          assert.equal(sheet.closed, true); assert.equal(routes, 1); same(messages, ['Order recorded under On the way.']);
        """)

    def test_seed_does_not_follow_a_new_queue_revision_and_manual_printing_edits_still_need_normal_preview(self):
        self.seed_js("""
          const writes = []; apiWrite = async (path, body) => {writes.push([path, body]); return {preview: 'normal', tables: {}};};
          const seed = shopBasketOrderSeed(view, basket, basket), sheet = shopOrderSheet(view, seed);
          const action = text => sheet.foot.querySelectorAll('button').find(item => item.textContent === text);
          const tick = async () => {for (let n = 0; n < 10; n++) await null;};
          pickPrinting = async () => ({set: 'cmm', number: '2', finish: 'foil'});
          sheet.body.querySelectorAll('button').find(item => item.textContent === 'Printing…').click(); await tick();
          action('Preview order').click(); await tick();
          same(writes[0][1].cards.rows[0], {name: 'Alpha', set: 'cmm', collector_number: '2', finish: 'foil', quantity: 1,
            condition: '', language: '', notes: ''});
          action('Edit order').click(); view.data.queue_revision = 'q2'; action('Preview order').click(); await tick();
          assert.equal(writes.length, 1); assert.equal(view.stale, true); assert(sheet.orderError.textContent.includes('queue changed'));
          assert.equal(action('Preview order').disabled, true);
          assert.equal(shopOrderSheet({...view, stale: false}, seed), null);
        """)

    def test_same_printing_across_queue_rows_merges_cards_but_keeps_each_fulfilment_count(self):
        self.seed_js("""
          item.more = []; item.copies = 2; item.listing = listing(2);
          const other = {...queued, queue_row: 2, for: 'Another deck', quantity: 3}; view.data.to_buy.push(other);
          basket.rows.push({...item, queue_row: 2, quantity: '3', copies: 3, listing: listing(3)});
          const seed = shopBasketOrderSeed(view, basket, basket);
          assert.equal(seed.cards.length, 1); assert.equal(seed.cards[0].quantity, 5);
          same(seed.fulfils, [{row: 1, quantity: 2}, {row: 2, quantity: 3}]);
        """)
