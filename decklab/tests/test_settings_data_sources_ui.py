"""E11-S85: Settings' Data sources panel over mocked Node API promises; no server, fetch or database."""
import json
import subprocess
import unittest

from decklab.tests.test_shell_ui import SETUP as SHELL
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = SHELL + r'''
  showFooter=()=>{};loadServerRestart=()=>{};settingsSimulations=()=>{};loadCommanderNightSettings=()=>{};loadPostageSettings=()=>{};
  loadPricingSettings=()=>{};loadSettingsMembers=()=>{};loadVisits=()=>{};loadReferenceFacts=()=>{};loadSettingsMaintenance=()=>{};
  state.status=null;state.simulations=null;
  let reads=[],writes=0,fetches=0;
  apiWrite=()=>{writes++;throw Error('Writes are forbidden');};
  fetch=()=>{fetches++;throw Error('Network is forbidden');};
  const KEYS=['scryfall','fx','rulings','spellbook','mtgjson','edhrec','gauntlet'];
  const sources=()=>({readable:true,card_data:{stale:false,warning:null},sources:KEYS.map(key=>({key,label:'Source '+key,
    last_ok:'2026-11-11T03:00:00+00:00',last_failure:null,state:'ok'}))});
  let answer=sources();
  api=async(path)=>{reads.push(path);if(path!=='/api/settings/data-sources')throw Error('Unexpected read');return structuredClone(answer);};
  const open=async(who='matt')=>{as(who,false);location.hash='#/settings';routeToken++;showSettings(new URLSearchParams(),routeToken);await flush();};
  const show=async()=>{byId('settings-data-sources-show').click();await flush();return byId('settings-data-sources');};
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SettingsDataSourcesUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([
            str(WEB), SETUP + scenario + "\nassert.equal(writes,0);assert.equal(fetches,0);", True]),
            capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_an_admin_reads_it_only_when_asked_and_sees_each_source(self):
        self.run_js("""
          await open();
          assert.equal(reads.length,0);
          const panel=await show();
          same(reads,['/api/settings/data-sources']);
          assert.equal(panel.querySelectorAll('[data-source]').length,7);
          assert(panel.textContent.includes('Source edhrec'));
          assert(panel.textContent.includes('Working'));
          assert(panel.textContent.includes('Last failure: none recorded'));
          assert.equal(byId('settings-data-sources-show').textContent,'Refresh');
        """)

    def test_failing_stale_and_the_card_data_sentence_show(self):
        self.run_js("""
          answer.sources[5]={...answer.sources[5],last_failure:'2026-11-12T03:00:00+00:00',state:'failing'};
          answer.sources[0]={...answer.sources[0],state:'stale'};
          answer.card_data={stale:true,warning:'Card data may have stopped refreshing: the card data is 20 days old; on the server PC run python -m decklab.lib.cards update.'};
          await open();const panel=await show();
          assert(panel.textContent.includes('Last try failed'));
          assert(panel.textContent.includes('Not refreshing'));
          assert(panel.textContent.includes('python -m decklab.lib.cards update'));
        """)

    def test_malformed_unreadable_or_failed_answers_show_nothing_healthy(self):
        self.run_js("""
          answer={...sources(),sources:sources().sources.slice(1)};
          await open();let panel=await show();
          assert(panel.textContent.includes("couldn't be read"));assert(!panel.textContent.includes('Working'));
          answer={...sources(),sources:sources().sources.map(row=>({...row,state:'great'}))};
          byId('settings-data-sources-show').click();await flush();
          assert(panel.textContent.includes("couldn't be read"));
          answer={...sources(),readable:false,sources:sources().sources.map(row=>({...row,last_ok:null,state:'never'}))};
          byId('settings-data-sources-show').click();await flush();
          assert(panel.textContent.includes("can't be read, so no fetch is shown"));
          api=async path=>{reads.push(path);throw new ApiError(503,'C:/private/path secret');};
          byId('settings-data-sources-show').click();await flush();
          assert(!panel.textContent.includes('Working'));
        """)

    def test_a_member_gets_no_panel_and_no_read(self):
        self.run_js("""
          await open('user1');
          assert.equal(byId('settings-data-sources'),null);
          assert.equal(reads.length,0);
        """)


if __name__ == "__main__":
    unittest.main()
