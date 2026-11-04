"""Shopping's Baskets with postage and the fewest-shops plan, and Settings' Shops' postage, under Node (E5-S27).

Run: python scripts/test_fixtures.py decklab.tests.test_shopping_plan_ui
Nothing is read or written: answers are supplied, writes are recorded fakes.
"""
import json
import subprocess
import unittest

from decklab.tests import test_shopping_baskets_ui, test_shopping_ui
from decklab.tests.test_shell_ui import SETUP as SHELL
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

PLAN = r"""
  const planShop = (key, shop, rows, extra = {}) => ({key, shop, rows, subtotal_aud: '3.70', unpriced: 0,
    cards: rows.reduce((n, r) => n + r.copies, 0), postage: {postage_aud: '8.00', free_over_aud: null, charged_aud: '8.00',
    free: false, short_by_aud: null, at_least: false, known: true}, ...extra});
  const planRow = (name, number, copies = 1, line_aud = '1.00') => ({queue_row: number, name, quantity: String(copies),
    state: 'ready', for: 'Otters', printing: 'any', set: '', collector_number: '', finish: '', copies, line_aud});
  const option = (shops, extra = {}) => ({shops, keys: shops.map(s => s.key), cards: 3, uncovered: [], cards_aud: '3.70',
    unpriced: 0, postage_aud: '8.00', postage_unknown: [], total_aud: '11.70', ...extra});
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingPlanTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js
    run_baskets_js = test_shopping_baskets_ui.ShoppingBasketsTests.run_baskets_js

    def test_plan_names_the_fewest_shops_and_the_card_by_card_way(self):
        self.run_baskets_js(PLAN + r"""
          const mtgRows = [planRow('Sol Ring', 1), planRow('Llanowar Elves', 2), planRow('Counterspell', 3)];
          const best = option([planShop('mtgmate', 'MTGMate', mtgRows)]);
          const split = option([planShop('mtgmate', 'MTGMate', [planRow('Counterspell', 3)]),
            planShop('gamesportal', 'Games Portal', [planRow('Sol Ring', 1), planRow('Llanowar Elves', 2)])],
            {cards_aud: '3.40', postage_aud: '15.00', total_aud: '18.40'});
          drawShopping(answer({shops: [basket('mtgmate', 'MTGMate', {rows: [line('Sol Ring', 1)], total_aud: '1.00', priced: 1})],
            plan: {recommended: best, by_price: split, options: [best, split], wanted: 3, weighed: true, saves_aud: '6.70'}}));
          const plan = main.querySelector('.shop-plan');
          assert(plan.textContent.includes('Buy from MTGMate: A$3.70 cards + A$8.00 postage = A$11.70, for 3 of 3 cards in stock.'));
          assert(plan.textContent.includes("That's A$6.70 less than buying each card where it's cheapest (MTGMate and Games Portal: A$3.40 cards + A$15.00 postage = A$18.40)."));
          assert(plan.querySelector('[data-plan-row="Counterspell"]'));
          assert(plan.querySelector('.shop-plan-others').textContent.includes('Other ways (1)'));
          assert(!plan.querySelector('[data-plan-unweighed]'));
          plan.querySelector('.shop-plan-copy').click(); await settle();
          assert.equal(copies.length, 1);
          assert.equal(copies[0], '1 Sol Ring\n1 Llanowar Elves\n1 Counterspell\n');
        """)

    def test_unknown_postage_says_it_was_not_weighed(self):
        self.run_baskets_js(PLAN + r"""
          const shop = planShop('mtgmate', 'MTGMate', [planRow('Sol Ring', 1)], {postage: {postage_aud: null, free_over_aud: null,
            charged_aud: null, free: false, short_by_aud: null, at_least: false, known: false}});
          const best = option([shop], {postage_aud: '0.00', postage_unknown: ['MTGMate'], total_aud: '1.00', cards_aud: '1.00', cards: 1});
          drawShopping(answer({shops: [basket('mtgmate', 'MTGMate', {rows: [line('Sol Ring', 1)], total_aud: '1.00', priced: 1})],
            plan: {recommended: best, by_price: best, options: [best], wanted: 1, weighed: false, saves_aud: null}}));
          const plan = main.querySelector('.shop-plan');
          assert(plan.querySelector('[data-plan-unweighed]').textContent.includes("postage isn't set"));
          assert(plan.textContent.includes('plus postage not known at MTGMate'));
          assert(plan.textContent.includes('Postage not known.'));
          assert(!plan.querySelector('.shop-plan-others'));
        """)

    def test_basket_postage_and_add_ons_that_reach_free_postage(self):
        self.run_baskets_js(r"""
          drawShopping(answer({shops: [basket('mtgmate', 'MTGMate', {rows: [line('Sol Ring', 1, {line_aud: '40.00'})],
            total_aud: '40.00', priced: 1,
            postage: {postage_aud: '8.50', free_over_aud: '50.00', charged_aud: '8.50', free: false, short_by_aud: '10.00', at_least: false, known: true},
            reach: {rows: [2], total_aud: '11.00', reaches: true},
            add_ons: [line('Arcane Signet', 2, {state: 'long_term', add_on: true, lifts: true, line_aud: '11.00'}),
              line('Swords', 3, {state: 'long_term', add_on: true, lifts: false})],
            add_ons_totals: {total_aud: '12.00', priced: 2, unpriced: 0, cards: 2}})]}));
          const mtg = shopNode('mtgmate');
          assert.equal(mtg.querySelector('.shop-basket-postage').textContent, 'Postage A$8.50; free over A$50.00, A$10.00 more.');
          const lifted = mtg.querySelectorAll('[data-basket-row]').filter(node => node.textContent.includes('Reaches free postage'));
          assert.equal(lifted.length, 1); assert(lifted[0].textContent.includes('Arcane Signet'));
          assert(mtg.querySelector('[data-basket-reach]').textContent.includes('(A$11.00) gets this order free postage, saving A$8.50'));
          assert(!main.querySelector('#shop-baskets').closest('section').textContent.includes("Postage isn't counted"));
        """)

    def test_free_and_unset_postage_words(self):
        self.run_baskets_js(r"""
          const words = postage => shopBasketPostageWords(postage);
          assert.equal(words({postage_aud: '8.50', free_over_aud: '50.00', charged_aud: '0.00', free: true}), 'Free postage: over A$50.00.');
          assert.equal(words({postage_aud: '0.00', free_over_aud: null, charged_aud: '0.00', free: true}), 'Posts free.');
          assert.equal(words({postage_aud: null, free_over_aud: '50.00', charged_aud: null, free: false, short_by_aud: '5.00', at_least: true}),
            'Postage not known; free over A$50.00, A$5.00 more (some rows have no price).');
          assert.equal(words(null), null);
        """)


SETTINGS = SHELL + r"""
  const plainApi = api;
  let reply = {revision: 2, can_edit: true, shops: [
    {key: 'mtgmate', shop: 'MTGMate', site: '', postage_aud: '8.50', free_over_aud: '100.00'},
    {key: 'gamesportal', shop: 'Games Portal', site: '', postage_aud: null, free_over_aud: null}]}, sent = [], fail = null;
  api = async (path) => path === '/api/shop-postage' ? structuredClone(reply) : plainApi(path);
  apiWrite = async (path, body, method) => { sent.push({path, body, method}); if (fail) throw fail;
    return {...reply, revision: body.expect + 1}; };
  showFooter = () => {}; loadServerRestart = () => {}; settingsSimulations = () => {}; loadCommanderNightSettings = () => {};
  loadSettingsMembers = () => {}; loadSettingsMaintenance = () => {}; loadVisits = () => {};
  const openPostage = async (who = 'matt') => { as(who, false); location.hash = '#/settings';
    showSettings(new URLSearchParams(), routeToken); await flush(); return main.querySelector('.postage-form'); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PostageSettingsTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETTINGS + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_home_admin_saves_each_shops_postage_with_blank_as_unknown(self):
        self.run_js(r"""
          const form = await openPostage();
          assert(form);
          assert.equal(byId('postage-mtgmate').value, '8.50');
          assert.equal(byId('postage-free-gamesportal').value, '');
          byId('postage-gamesportal').value = '7'; byId('postage-free-mtgmate').value = 'A$120';
          form.fire('submit'); await flush();
          assert.equal(sent.length, 1);
          assert.equal(sent[0].path, '/api/shop-postage'); assert.equal(sent[0].method, 'PUT');
          assert.equal(sent[0].body.expect, 2);
          assert.deepEqual(sent[0].body.shops, {mtgmate: {postage_aud: '8.50', free_over_aud: '120'},
            gamesportal: {postage_aud: '7', free_over_aud: null}});
          assert(main.querySelector('.postage-form').textContent.includes('Postage saved.'));
        """)

    def test_bad_amounts_and_conflicts_never_lose_entries(self):
        self.run_js(r"""
          let form = await openPostage();
          byId('postage-mtgmate').value = '8.505'; form.fire('submit'); await flush();
          assert.equal(sent.length, 0);
          assert(form.querySelector('.form-error').textContent.includes("MTGMate's postage must be an amount"));
          byId('postage-mtgmate').value = '9'; fail = new ApiError(409, 'changed'); form.fire('submit'); await flush();
          assert.equal(sent.length, 1);
          assert(form.querySelector('.form-error').textContent.includes('changed while this form was open'));
          assert.equal(byId('postage-mtgmate').value, '9');
        """)

    def test_members_and_other_spaces_never_see_or_read_it(self):
        self.run_js(r"""
          let reads = 0; api = async (path) => { if (path === '/api/shop-postage') reads += 1; return plainApi(path); };
          for (const who of ['user1', 'user2']) { await openPostage(who); assert.equal(byId('settings-postage'), null); }
          assert.equal(reads, 0);
        """)


if __name__ == "__main__":
    unittest.main()
