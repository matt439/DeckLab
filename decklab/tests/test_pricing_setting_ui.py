"""Settings' Prices part (settings-pricing.js, E11-S53): a home admin's currency and price-check shops.

Real page functions over deterministic DOM/API promises; no server, database or config.json write.
Run: python scripts/test_fixtures.py decklab.tests.test_pricing_setting_ui
"""
import json
import subprocess
import unittest

from decklab.tests.test_shell_ui import SETUP as SHELL
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = SHELL + r'''
  const answer = (over = {}) => ({revision: 0,
    currency: {saved: null, config: null, effective: 'AUD', symbol: 'A$', source: 'default'},
    shops: {saved: null, config: null, effective: ['mtgmate', 'gamesportal'], source: 'default',
      choices: [{key: 'mtgmate', name: 'MTGMate', site: 'https://shop.example'},
                {key: 'gamesportal', name: 'Games Portal', site: 'https://games.example'}]},
    currencies: [{code: 'AUD', symbol: 'A$'}, {code: 'EUR', symbol: '€'}, {code: 'SEK', symbol: 'SEK '}],
    can_edit: true, ...over});
  let view = answer(), reads = [], writes = [], failure = null, footers = 0, hold = null;
  api = async (path) => { reads.push(path); if (path !== '/api/pricing-setting') throw Error('Other panel omitted');
    if (hold) await hold; if (failure) throw failure; return structuredClone(view); };
  apiWrite = async (path, body, method) => { writes.push({path, body, method});
    return answer({revision: 1, currency: {saved: body.currency, config: null, effective: body.currency || 'AUD',
      symbol: '€', source: body.currency ? 'saved' : 'default'},
      shops: {...answer().shops, saved: body.shops, effective: body.shops || ['mtgmate', 'gamesportal'],
        source: body.shops ? 'saved' : 'default'}}); };
  showFooter = () => { footers++; }; loadSimulations = () => {}; settingsSimulations = () => {};
  loadCommanderNightSettings = () => {}; loadPostageSettings = () => {}; loadVisits = () => {}; loadReferenceFacts = () => {};
  loadSettingsMaintenance = () => {}; loadSettingsMembers = () => {}; loadServerRestart = () => {};
  const openSettings = async (id = 'matt') => { as(id, false); location.hash = '#/settings'; routeToken++;
    showSettings(new URLSearchParams(), routeToken); await flush(); return byId('settings-prices'); };
  const button = text => main.querySelectorAll('button').find(node => node.textContent === text);
  const save = async () => { byId('pricing-currency').closest('form').fire('submit'); await flush(); };
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PricingSettingUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_a_home_admin_sees_the_choices_and_the_restart_words(self):
        self.run_js(r'''
          const panel = await openSettings();
          assert(panel && !panel.hidden);
          same(reads, ['/api/pricing-setting']);
          const select = byId('pricing-currency');
          same(select.querySelectorAll('option').map(o => o.textContent),
               ["Use config.json's (AUD, the default)", 'AUD (A$)', 'EUR (€)', 'SEK']);
          assert(byId('pricing-shops-config').checked);
          assert(byId('pricing-shop-mtgmate').checked && byId('pricing-shop-mtgmate').disabled);
          const text = panel.textContent;
          for (const words of ['No restart needed', 'Deck tables keep their old currency until', 'Shops\' own prices and postage stay in A$'])
            assert(text.includes(words), words);
          assert(byId('pricing-source').textContent.includes('estimates in AUD (the default)'));
        ''')

    def test_a_save_sends_the_choice_and_refreshes_the_status(self):
        self.run_js(r'''
          await openSettings();
          const before = footers;
          byId('pricing-currency').value = 'EUR';
          byId('pricing-shops-config').checked = false; byId('pricing-shops-config').fire('change');
          byId('pricing-shop-gamesportal').checked = false; byId('pricing-shop-gamesportal').fire('change');
          await save();
          same(writes, [{path: '/api/pricing-setting', method: 'PUT',
            body: {profile: 'matt', expect: 0, currency: 'EUR', shops: ['mtgmate']}}]);
          assert.equal(footers, before + 1);
          assert(byId('settings-prices').textContent.includes('Price settings saved.'));
          assert(byId('pricing-source').textContent.includes('estimates in EUR (set here)'));
        ''')

    def test_a_status_read_already_in_flight_is_followed_by_a_fresh_one(self):
        self.run_js(r'''
          await openSettings();
          let release; versionRequest = new Promise(resolve => { release = resolve; });
          const before = footers;
          byId('pricing-currency').value = 'EUR';
          await save();
          assert(byId('settings-prices').textContent.includes('Price settings saved.'));
          assert.equal(footers, before);          // the old read began before the save: not reused as the answer
          versionRequest = null; release(); await flush();
          assert.equal(footers, before + 1);      // a new /api/status read starts after it
        ''')

    def test_config_json_sends_null_and_no_shop_turns_the_check_off(self):
        self.run_js(r'''
          view = answer({currency: {saved: 'EUR', config: 'GBP', effective: 'EUR', symbol: '€', source: 'saved'}});
          await openSettings();
          assert.equal(byId('pricing-currency').querySelectorAll('option')[0].textContent, "Use config.json's (GBP)");
          byId('pricing-currency').value = '';
          byId('pricing-shops-config').checked = false; byId('pricing-shops-config').fire('change');
          for (const key of ['mtgmate', 'gamesportal']) { byId(`pricing-shop-${key}`).checked = false; byId(`pricing-shop-${key}`).fire('change'); }
          assert(byId('pricing-shops-off').textContent.includes('nightly shop check is off'));
          await save();
          same(writes.map(w => w.body), [{profile: 'matt', expect: 0, currency: null, shops: []}]);
        ''')

    def test_read_only_answer_and_a_refusal(self):
        self.run_js(r'''
          view = answer({can_edit: false});
          let panel = await openSettings();
          assert(!byId('pricing-currency'));
          assert(panel.textContent.includes('No restart needed'));
          failure = new ApiError(403, 'The price settings are private to home.');
          panel = await openSettings();
          assert(panel.hidden);
          assert.equal(writes.length, 0);
        ''')

    def test_postage_stays_in_aud_under_another_currency(self):
        self.run_js(r'''
          as('matt', false);
          state.status = null;
          assert(!settingsPostagePanel().textContent.includes('Australian dollars'));
          state.status = {pricing: {currency: 'EUR', symbol: '€', currency_default: false, shops: []}};
          const text = settingsPostagePanel().textContent;
          assert(text.includes('in A$') && text.includes('The shops charge in Australian dollars, so these stay in A$.'), text);
          state.status = null;
        ''')

    def test_members_and_other_spaces_get_no_panel(self):
        self.run_js(r'''
          for (const id of ['user1', 'user2']) { assert.equal(await openSettings(id), null); }
          same(reads, []);
        ''')

    def test_listing_controls_default_to_every_copy_and_save_explicit_independent_restrictions(self):
        self.run_js(r'''
          view = answer({listing_preferences: {saved: null, effective: null,
            conditions: [{code: 'NM', label: 'Near Mint'}, {code: 'LP', label: 'Lightly Played'}]}});
          await openSettings();
          assert.equal(byId('pricing-minimum-condition').value, ''); assert(!byId('pricing-english-only').checked);
          byId('pricing-minimum-condition').value = 'LP'; byId('pricing-english-only').checked = true;
          await save();
          same(writes[0].body.listing_preferences, {minimum_condition: 'LP', english_only: true});
          assert.equal(writes[0].body.currency, null); assert.equal(writes[0].body.shops, null);
        ''')

    def test_listing_choices_remain_after_stale_refusal_until_explicit_reload(self):
        self.run_js(r'''
          view = answer({listing_preferences: {saved: null, effective: null,
            conditions: [{code: 'NM', label: 'Near Mint'}, {code: 'LP', label: 'Lightly Played'}]}});
          await openSettings();
          byId('pricing-minimum-condition').value = 'LP'; byId('pricing-english-only').checked = true;
          apiWrite = async () => { throw new ApiError(409, 'Changed'); };
          await save();
          assert.equal(byId('pricing-minimum-condition').value, 'LP'); assert(byId('pricing-english-only').checked);
          assert(button('Save price settings').disabled);
          assert(!button('Load the saved price settings').hidden);
        ''')

    def test_a_stale_answer_after_leaving_is_dropped(self):
        self.run_js(r'''
          let release; hold = new Promise(resolve => { release = resolve; });
          const panel = await openSettings();
          routeToken++;
          release(); await flush();
          assert(!byId('pricing-currency'));
          assert(panel.textContent.includes('Loading the price settings'));
        ''')


if __name__ == "__main__":
    unittest.main()
