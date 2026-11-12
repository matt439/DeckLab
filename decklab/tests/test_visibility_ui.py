"""Who sees what real page scripts over deterministic DOM and API responses."""
import json
import subprocess
import unittest

from decklab.tests.test_shell_ui import SETUP as SHELL
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = SHELL + r"""
  let switches = [{owner:'home',thing:'decks',public:false},{owner:'shared',thing:'accessories',public:false}];
  let sent = [], refreshes = [], previews = [], failSave = false, failRefresh = false, failPreview = false;
  let previewAnswer = {available:true,counts:{decks:3},mentions:[{id:'casual/shop',title:'Shop Deck'}],more_mentions:0};
  const otherApi = api;
  api = async (path) => {
    if (path === '/api/visibility') return {switches};
    if (path.startsWith('/api/visibility/preview?')) {previews.push(path); if(failPreview) throw new Error('preview down');
      return previewAnswer;}
    if (path === '/api/me') {refreshes.push(path); if(failRefresh) throw new Error('refresh down');
      return {profile:state.profile.id,may:{...state.may,visibility:switches}};}
    if (path === '/api/profiles') {refreshes.push(path); return {profiles:PROFILES,admins:['Admin']};}
    return otherApi(path);
  };
  apiWrite = async (path,body,method) => {
    sent.push({path,body,method}); if(failSave) throw new Error('database down');
    switches = switches.map(row => row.owner===body.owner && row.thing===body.thing ? {...row,public:body.public} : row);
    return {switches};
  };
  const openVisibility = async (rows=switches) => {
    as('matt',false); switches=rows; state.may={...state.may,visibility:rows}; location.hash='#/visibility';
    await showVisibility(new URLSearchParams(),routeToken); await flush();
  };
  const sheet = () => document.querySelectorAll('dialog').at(-1);
  const answer = async (action) => { sheet().querySelector(`[data-action=${action}]`).click(); await flush(); };
  const row = (owner,thing) => main.querySelectorAll('[data-visibility-owner]').find(
    node => node.dataset.visibilityOwner===owner && node.dataset.visibilityThing===thing);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class VisibilityUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_page_explains_public_readonly_deck_text_and_defaults_private(self):
        self.run_js(r"""
          await openVisibility();
          assert(main.textContent.includes('read-only to everyone signed in'));
          assert(main.textContent.includes('Nothing becomes public on the internet'));
          assert(main.textContent.includes('Play-now list hints'));
          assert(main.textContent.includes('write-up as written'));
          assert(main.textContent.includes('Shared sleeves'));
          for(const node of main.querySelectorAll('[data-visibility-owner]')) {
            assert.equal(node.querySelector('[data-public=false]').getAttribute('aria-pressed'),'true');
            assert.equal(node.querySelector('[data-public=true]').getAttribute('aria-pressed'),'false');
          }
          assert.equal(sent.length,0);
        """)

    def test_flip_is_one_put_then_me_and_roster_refresh_and_current_value_changes(self):
        self.run_js(r"""
          await openVisibility(); state.library={old:true};
          row('home','decks').querySelector('[data-public=true]').fire('click'); await flush();
          assert.equal(sent.length,0,'nothing changes until Confirm'); await answer('confirm');
          same(sent,[{path:'/api/visibility',body:{profile:'matt',owner:'home',thing:'decks',public:true},method:'PUT'}]);
          same(refreshes.sort(),['/api/me','/api/profiles']);
          assert.equal(state.library,null);
          assert.equal(row('home','decks').querySelector('[data-public=true]').getAttribute('aria-pressed'),'true');
          assert.equal(row('shared','accessories').querySelector('[data-public=false]').getAttribute('aria-pressed'),'true');
          assert.equal(state.may.visibility[0].public,true);
          row('home','decks').querySelector('[data-public=true]').fire('click'); await flush();
          assert.equal(sent.length,1,'clicking selected state writes nothing');
        """)

    def test_failure_keeps_previous_state_and_allows_retry(self):
        self.run_js(r"""
          await openVisibility(); failSave=true;
          const node=row('home','decks'); node.querySelector('[data-public=true]').fire('click'); await flush();
          await answer('confirm');
          assert(node.textContent.includes("Couldn't save: database down"));
          assert.equal(node.querySelector('[data-public=false]').getAttribute('aria-pressed'),'true');
          assert(node.querySelectorAll('button').every(button=>!button.disabled));
          assert.equal(refreshes.length,0);
          failSave=false; failRefresh=true;
          node.querySelector('[data-public=true]').fire('click'); await flush(); await answer('confirm');
          assert.equal(row('home','decks').querySelector('[data-public=true]').getAttribute('aria-pressed'),'true');
          assert(!main.textContent.includes("Couldn't save"),'a failed me refresh cannot misreport the saved flip');
        """)

    def test_public_asks_with_own_counts_and_purchase_mentions_before_one_put(self):
        self.run_js(r"""
          await openVisibility();
          row('home','decks').querySelector('[data-public=true]').fire('click'); await flush();
          same(previews,['/api/visibility/preview?owner=home&thing=decks']);
          const text = sheet().textContent;
          assert(text.includes('Make decks Public?'));
          assert(text.includes('3 decks'));
          assert(text.includes('mention orders or purchases: Shop Deck'));
          assert(text.includes('Nothing changes until you confirm'));
          assert.equal(sent.length,0);
          await answer('cancel');
          assert.equal(sent.length,0,'Keep private writes nothing');
          assert.equal(row('home','decks').querySelector('[data-public=false]').getAttribute('aria-pressed'),'true');
          assert(row('home','decks').querySelectorAll('button').every(button=>!button.disabled));
          previewAnswer={available:true,counts:{kit_rows:2,kit_pictures:1},mentions:[],more_mentions:0};
          row('shared','accessories').querySelector('[data-public=true]').fire('click'); await flush();
          assert(sheet().textContent.includes('2 sleeve, deck box and playmat rows, 1 with pictures'));
          assert(sheet().textContent.includes('Make shared sleeves'));
          await answer('confirm');
          same(sent.map(s=>[s.body.owner,s.body.thing,s.body.public]),[['shared','accessories',true]]);
        """)

    def test_failed_preview_still_offers_confirm_and_private_is_one_tap(self):
        self.run_js(r"""
          await openVisibility(); failPreview=true;
          row('home','decks').querySelector('[data-public=true]').fire('click'); await flush();
          assert(sheet().textContent.includes("couldn't work out what this would show"));
          await answer('confirm');
          assert.equal(sent.length,1);
          assert.equal(row('home','decks').querySelector('[data-public=true]').getAttribute('aria-pressed'),'true');
          const opened = previews.length;
          previewAnswer={available:false,message:'Server says unknown.'}; failPreview=false;
          row('home','decks').querySelector('[data-public=false]').fire('click'); await flush();
          assert.equal(previews.length,opened,'turning Private asks nothing');
          assert.equal(document.querySelectorAll('dialog').length,0);
          same(sent.at(-1).body,{profile:'matt',owner:'home',thing:'decks',public:false});
          row('home','decks').querySelector('[data-public=true]').fire('click'); await flush();
          assert(sheet().textContent.includes('Server says unknown.'));
          await answer('cancel');
          assert.equal(sent.length,2);
        """)

    def test_only_server_offered_controls_appear_and_empty_ready_list_has_no_buttons(self):
        self.run_js(r"""
          await openVisibility([{owner:'home',thing:'collection',public:false}]);
          assert.equal(main.querySelectorAll('[data-visibility-owner]').length,1);
          assert(main.textContent.includes('Collection and tokens'));
          assert.equal(row('home','decks'),undefined);
          await openVisibility([]);
          assert(main.textContent.includes('No Public switches yet'));
          assert.equal(main.querySelectorAll('[data-public]').length,0);
          assert.equal(routeVisible(routeFor('visibility')),false);
        """)

    def test_avatar_and_phone_account_navigation_use_server_owned_controls(self):
        self.run_js(r"""
          document.body.append(el('a',{id:'menu-visibility'}));
          await openVisibility(); syncAccountMenu();
          assert.equal(byId('menu-visibility').hidden,false);
          assert(navRoutes('account').some(route=>route.path==='visibility'));
          state.may={...state.may,visibility:[]}; syncAccountMenu();
          assert.equal(byId('menu-visibility').hidden,true);
          assert(!navRoutes('account').some(route=>route.path==='visibility'));
        """)


if __name__ == "__main__":
    unittest.main()
