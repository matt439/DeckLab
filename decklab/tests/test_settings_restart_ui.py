"""Restart Deck Lab on the Settings page (settings-restart.js) and the warning box's link to it.

Real page functions over deterministic DOM/API promises; no server, restart or data writes.
"""
import json
import subprocess
import unittest

from decklab.tests.test_shell_ui import SETUP as SHELL
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = SHELL + r'''
  let view={may_restart:true,why_not:null,busy:[],restarting:false}, reads=[], writes=[], answer=null;
  api=async(path)=>{reads.push(path);if(path==='/api/server/restart')return structuredClone(view);
    if(path==='/api/status')return {build:{started_at:'new'}};throw Error('Other panel omitted');};
  apiWrite=async(path,body)=>{writes.push({path,body});if(answer)throw answer;return {restarting:true,started_at:'old'};};
  showFooter=()=>{};loadSimulations=()=>{};settingsSimulations=()=>{};loadCommanderNightSettings=()=>{};loadVisits=()=>{};
  loadSettingsMaintenance=()=>{};loadSettingsMembers=()=>{};
  let reloads=0;reloadDeckLab=()=>{reloads++;};
  const openSettings=async(id='matt')=>{as(id,false);location.hash='#/settings';routeToken++;
    showSettings(new URLSearchParams(),routeToken);await flush();return byId('server-restart');};
  const button=text=>main.querySelectorAll('button').find(node=>node.textContent===text);
  const words=()=>byId('server-restart-words').textContent;
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SettingsRestartUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_confirmed_restart_posts_and_waits_for_a_new_server(self):
        self.run_js(r'''
          const host=await openSettings();assert(host);assert(!host.hidden);same(reads,['/api/server/restart']);
          assert(words().includes("doesn't apply database migrations"));
          button('Restart Deck Lab…').click();assert.equal(writes.length,0);
          assert(button('Cancel'));button('Restart now').click();await flush();
          same(writes,[{path:'/api/server/restart',body:{anyway:false}}]);
          assert(words().includes('restarting'));
          await flush();await flush();assert.equal(reloads,1);
        ''')

    def test_busy_answer_asks_again_and_cancel_goes_back(self):
        self.run_js(r'''
          await openSettings();button('Restart Deck Lab…').click();
          answer=new ApiError(409,'Restarting now would stop 1 Forge matchup playing or waiting.',{busy:['1 Forge matchup playing or waiting']});
          button('Restart now').click();await flush();
          assert(words().includes('1 Forge matchup playing or waiting'));assert(button('Restart anyway'));
          button('Cancel').click();assert(button('Restart Deck Lab…'));
          answer=null;button('Restart Deck Lab…').click();
          same(writes.map(w=>w.body),[{anyway:false}]);
        ''')

    def test_refusal_is_shown_without_a_button(self):
        self.run_js(r'''
          view={may_restart:false,why_not:"Deck Lab's code on the PC has changes that aren't committed.",busy:[],restarting:false};
          await openSettings();assert(words().includes("aren't committed"));assert.equal(button('Restart Deck Lab…'),undefined);
        ''')

    def test_members_and_other_space_admins_get_no_control_or_request(self):
        self.run_js(r'''
          for(const profile of [PROFILES[1],{...PROFILES[2],role:'admin'}]){
            clear(main);reads=[];state.profile=profile;state.may={admin:true};location.hash='#/settings';routeToken++;
            showSettings(new URLSearchParams(),routeToken);await flush();
            assert.equal(byId('server-restart'),null);assert(!reads.includes('/api/server/restart'));
          }
        ''')

    def test_warning_box_links_a_home_admin_to_the_restart(self):
        self.run_js(r'''
          document.body.append(el('div',{id:'build-warning'}));as('matt',false);
          renderVersionStatus({build:{running_commit:'a'.repeat(40),latest_commit:'b'.repeat(40),restart_required:true,
            running_dirty:false,latest_dirty:false,web_revision:null}});
          const link=byId('build-warning').querySelectorAll('a').find(node=>node.textContent==='Restart Deck Lab…');
          assert(link);assert.equal(link.getAttribute('href'),'#/settings?part=about');
          as(PROFILES[1].id,false);
          renderVersionStatus({build:{running_commit:'a'.repeat(40),latest_commit:'b'.repeat(40),restart_required:true,
            running_dirty:false,latest_dirty:false,web_revision:null}});
          assert(!byId('build-warning').querySelectorAll('a').some(node=>node.textContent==='Restart Deck Lab…'));
        ''')


if __name__ == "__main__":
    unittest.main()
