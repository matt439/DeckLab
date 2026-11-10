"""Optional simulated timing/category/land controls retain their original page and viewer."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + r'''
  state.profile={id:'matt',space:'home'};location.hash='#/deck?id=casual/test&tab=practice';
  const data=makePage(),result={kind:'commander',games:100,turns:4,seed:77,cache_key:'a'.repeat(40),
    land_trials:{cuts:['Elf','Forest'],colours:['G','R'],tapped_cut:'Synthetic tapped land',max_games:20000}};
  const metrics={commanders:[{name:'Leader A',average_turn:2.5,never:.2,by_turn:[{turn:1,chance:0},{turn:4,chance:.8}]},
    {name:'Leader B',average_turn:3,never:.4,by_turn:[{turn:1,chance:0},{turn:4,chance:.6}]}],
    castability:[{name:'Bolt',blocked_share:.5,blocked_turns:10,enough_mana_turns:20,games_waited:5,average_wait:2}],
    categories:[{name:'Ramp',cards:2,spells:2,checked:true,by_turn:[1,2,3,4].map(turn=>({turn,at_least:[.8,.3]}))},
      {name:'Unknown',cards:1,spells:0,checked:false,by_turn:null}]};
  const values={stuck:.2,colour_screw:.1,colour_waste:.05,flood:.3,mana_used:.6};
  const completed=()=>({status:'done',result:{settings:{games:100,turns:4,seed:77},threshold:.01,note:'At least 1 percentage point, with bounded regressions.',warnings:[],
    baseline:{play:values},best:{play:null},variants:[{id:'0',cut:'Elf',add:'Forest',tapped_land:false,metrics:{play:values},deltas:{play:{stuck:-.005,colour_screw:0,colour_waste:0,flood:.002,mana_used:.01}}}]}});
  const requests=[];apiWrite=async(path,body,method,options)=>{requests.push({path,body,method,options});return completed();};
  const show=()=>{const root=practiceLandTrials(result,data,'play');clear(main).append(root);return root;};
  const flush=async()=>{for(let i=0;i<30;i++)await null;};
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PracticeInsightUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pair_timing_and_colour_wait_denominators_are_explicit(self):
        self.run_js(r'''
          const timing=practiceCommanderPanel(result,metrics);assert(timing.textContent.includes('Leader A'));assert(timing.textContent.includes('Leader B'));
          assert(timing.textContent.includes('earliest affordable'));assert(timing.textContent.includes('among games with a cast'));
          assert(timing.textContent.includes('20.0%'));assert(timing.textContent.includes('80.0%'));
          const waits=practiceCastability(metrics);assert(waits.textContent.includes('50.0%'));assert(waits.textContent.includes('10 of 20 turns'));
          assert(waits.textContent.includes('2 blocked turns on average in 5 games'));assert(waits.textContent.includes('Simulation estimate'));
        ''')

    def test_category_count_and_turn_reuse_saved_histogram_and_unknown_is_not_zero(self):
        self.run_js(r'''
          const root=practiceCategoryPanel(result,metrics,data);clear(main).append(root);const [category,count,turn]=root.querySelectorAll('select');
          assert(root.textContent.includes('80.0% of games'));count.value='2';turn.value='3';count.fire('change');
          assert(root.textContent.includes('30.0% of games cast at least 2 Ramp cards by turn 3'));same(requests,[]);
          category.value='1';category.fire('change');assert(root.textContent.includes("wasn't checked"));
          assert(!root.querySelector('[role=status]').textContent.includes('0%'));
        ''')

    def test_explicit_one_basic_request_and_no_best_below_screen_never_mutates_deck(self):
        self.run_js(r'''
          const before=JSON.stringify(data),root=show();buttonText(root,'Run land trials').click();await flush();
          assert.equal(requests.length,1);same(requests[0].body,{id:'casual/test',version:'target',cut:'Elf',cache_key:'a'.repeat(40)});
          assert.equal(requests[0].path,'/api/goldfish/what-if');assert.equal(JSON.stringify(data),before);
          assert(root.textContent.includes('No best change'));assert(root.textContent.includes('-0.5 pp'));assert(root.textContent.includes('Mana used'));
          assert(root.textContent.includes('Synthetic tapped land'));assert(root.textContent.includes('seed 77'));
        ''')

    def test_late_profile_route_and_cut_replies_are_ignored(self):
        self.run_js(r'''
          for(const drift of ['profile','route','cut']){
            state.profile={id:'matt',space:'home'};location.hash='#/deck?id=casual/test&tab=practice';
            let done;apiWrite=()=>new Promise(resolve=>done=resolve);const root=show();buttonText(root,'Run land trials').click();
            if(drift==='profile')state.profile={...state.profile};else if(drift==='route')routeToken++;else{const select=root.querySelector('select');select.value='Forest';select.fire('change');}
            done(completed());await flush();assert(!root.textContent.includes('No best change'));
          }
        ''')

    def test_stale_controls_cannot_start_and_same_deck_tab_address_remains_usable(self):
        self.run_js(r'''
          const root=show();location.hash='#/deck?id=casual%2Ftest&tab=cards';buttonText(root,'Run land trials').click();await flush();assert.equal(requests.length,1);
          state.profile={...state.profile};buttonText(root,'Run land trials').click();await flush();assert.equal(requests.length,1);
          state.profile.id='user2';buttonText(root,'Run land trials').click();assert.equal(requests.length,1);
        ''')

    def test_failed_trials_need_explicit_retry_and_stale_baseline_never_retries_automatically(self):
        self.run_js(r'''
          let calls=0;apiWrite=async(path,body)=>{requests.push(body);return ++calls===1?{status:'error',error:'Generic simulation failure'}:completed();};
          const root=show();buttonText(root,'Run land trials').click();await flush();assert(root.textContent.includes('Generic simulation failure'));
          assert.equal(requests.length,1);buttonText(root,'Retry land trials').click();await flush();assert.equal(requests[1].retry,true);
          apiWrite=async()=>{calls++;throw new ApiError(409,'Changed result');};const stale=show();buttonText(stale,'Run land trials').click();await flush();
          assert(stale.textContent.includes('Reload this deck'));assert.equal(calls,3);
        ''')
