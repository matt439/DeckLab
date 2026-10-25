"""A renamed deck updates Matchups' live axes and saved phone preference without changing results."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = r"""
  clear(main);editor=null;state.profile={id:'matt',name:'Matt'};
  const stored=new Map();local.get=key=>stored.get(key)||null;local.set=(key,value)=>{stored.set(key,value);return true;};
  const requests=[],pending=[];let writes=0;
  const deck=(id,title,extra={})=>({id,title,kind:'casual',space:'home',versions:['target'],...extra});
  const library=(revision='before',renamed=false)=>({decks_revision:revision,halves:[],decks:[
    deck(renamed?'casual/new':'casual/old',renamed?'Gamma':'Alpha',renamed?{aliases:['casual/old']}:{}),
    deck('casual/opponent','Beta') ]});
  const result=(renamed=false)=>({key:'a'.repeat(64),format:'Constructed',updated:'2026-10-16T12:00:00',games:200,
    engine:{kind:'decklab',current:true},winrate:{value:.6,low:.5,high:.7},sides:[
      {id:renamed?'casual/new':'casual/old',title:renamed?'Gamma':'Alpha',version:'target',kind:'casual',current:true},
      {id:'casual/opponent',title:'Beta',version:'target',kind:'casual',current:true}]});
  const answer=(revision='before',renamed=false)=>({decks_revision:revision,running:[],results:[result(renamed)],forge:{ready:false,problem:'Fixture only'}});
  const settle=async()=>{for(let n=0;n<30;n++)await Promise.resolve();};
  const held=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
  let read=async url=>url==='/api/decks'?library('after',true):answer('after',true);
  api=async(url,options={})=>{requests.push({url,signal:options.signal});return read(url,options);};
  apiWrite=async()=>{writes++;throw new Error('Read-only fixture');};
  runGate=()=>({may:false,why:'Fixture only'});runsAllowed=()=>false;noteRuns=()=>{};
  const selected=()=>main.querySelector('#mu-deck-pick').querySelectorAll('option').find(option=>option.getAttribute('selected')!==null)?.getAttribute('value');
  const played=()=>main.querySelectorAll('td').filter(cell=>(cell.getAttribute('class')||'').includes('mu-h-')).length;
  const open=(lib=library(),data=answer())=>{location.hash='#/matchups';drawMatchups(lib,data,new URLSearchParams(),routeToken);};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class MatchupRenameUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_other_device_rename_refreshes_axes_before_applying_canonical_results(self):
        self.run_js(r"""
          stored.set(HOME_DECK_KEY,'casual/old');const lib=library(),data=answer(),original=JSON.stringify(data);open(lib,data);
          assert.equal(selected(),'casual/old');assert.equal(played(),2);
          const wait=held();read=async url=>url==='/api/decks'?wait.promise:answer('after',true);
          const refresh=matchupRefresh.refresh();await settle();same(requests.map(item=>item.url),['/api/matchups','/api/decks']);
          assert.equal(selected(),'casual/old');assert.equal(played(),2,'old coherent display stays while new names load');
          wait.resolve(library('after',true));await refresh;await settle();
          assert.equal(selected(),'casual/new');assert.equal(stored.get(HOME_DECK_KEY),'casual/new');assert.equal(played(),2);
          assert(main.textContent.includes('Gamma'));assert(!main.querySelectorAll('th').some(cell=>cell.getAttribute('title')==='Alpha'));
          assert.equal(state.library.decks_revision,'after');assert.equal(JSON.stringify(data),original);assert.equal(lib.decks[0].id,'casual/old');assert.equal(writes,0);
        """)

    def test_fresh_page_canonicalizes_saved_home_preference_instead_of_picking_first_axis(self):
        self.run_js(r"""
          stored.set(HOME_DECK_KEY,'casual/old');open(library('after',true),{...answer('after',true),results:[]});
          assert.equal(selected(),'casual/new','Beta sorts first, but the saved Gamma preference must survive');
          assert.equal(stored.get(HOME_DECK_KEY),'casual/new');same(requests,[]);assert.equal(writes,0);
        """)

    def test_failed_library_refresh_keeps_coherent_results_and_retries_automatically(self):
        self.run_js(r"""
          stored.set(HOME_DECK_KEY,'casual/old');open();read=async url=>{if(url==='/api/decks')throw new Error('Database unavailable');return answer('after',true);};
          await matchupRefresh.refresh();assert.equal(selected(),'casual/old');assert.equal(played(),2);
          assert(main.textContent.includes('Matchup updates aren'));assert(main.textContent.includes('Database unavailable'));
          read=async url=>url==='/api/decks'?library('after',true):answer('after',true);await matchupRefresh.refresh();
          assert.equal(selected(),'casual/new');assert.equal(played(),2);assert(main.textContent.includes('Connected again'));
          same(requests.map(item=>item.url),['/api/matchups','/api/decks','/api/matchups','/api/decks']);
        """)

    def test_library_and_results_must_describe_the_same_snapshot(self):
        self.run_js(r"""
          open();read=async url=>url==='/api/decks'?library('even-later',true):answer('after',true);
          await matchupRefresh.refresh();assert.equal(selected(),'casual/old');assert.equal(played(),2);
          assert(main.textContent.includes('changed while their names were loading'));assert.equal(state.library?.decks_revision,undefined);
          read=async url=>url==='/api/decks'?library('even-later',true):answer('even-later',true);
          await matchupRefresh.refresh();assert.equal(played(),2);assert.equal(selected(),'casual/new');
        """)

    def test_refresh_is_single_flight_and_late_library_responses_cannot_cross_a_profile_or_route(self):
        self.run_js(r"""
          for(const leave of [()=>{state.profile={id:'user1'};},()=>{routeToken++;},()=>{stopMatchupRefresh();}]) {
            state.profile={id:'matt'};clear(main);open();const wait=held();read=async url=>url==='/api/decks'?wait.promise:answer('after',true);
            const watcher=matchupRefresh,one=watcher.refresh();await settle();const count=requests.length;
            watcher.refresh();window.fire('focus');assert.equal(requests.length,count);
            leave();clear(main).append(el('p',{text:'Another page'}));state.library={sentinel:true};wait.resolve(library('after',true));await one;await settle();
            assert.equal(main.textContent,'Another page');assert(state.library.sentinel);stopMatchupRefresh();
          }
        """)

    def test_library_refresh_shares_the_poll_abort_when_hidden(self):
        self.run_js(r"""
          open();const wait=held();read=async url=>url==='/api/decks'?wait.promise:answer('after',true);
          const refresh=matchupRefresh.refresh();await settle();assert.equal(requests.length,2);
          document.visibilityState='hidden';document.fire('visibilitychange');assert(requests[0].signal.aborted);assert(requests[1].signal.aborted);
          wait.resolve(library('after',true));await refresh;assert.equal(selected(),'casual/old');assert.equal(played(),2);
          document.visibilityState='visible';read=async url=>url==='/api/decks'?library('after',true):answer('after',true);
          document.fire('visibilitychange');await settle();assert.equal(selected(),'casual/new');assert.equal(played(),2);
        """)

    def test_initial_race_waits_for_a_matching_library_even_with_unchanged_results(self):
        self.run_js(r"""
          const wait=held();read=async url=>url==='/api/decks'?wait.promise:answer('after',true);
          open(library(),answer('after',true));assert(main.textContent.includes('Updating the decks'));await settle();
          wait.resolve(library('after',true));await settle();assert(main.querySelector('.mu-matrix-part'));assert.equal(played(),2);
          assert.equal(selected(),'casual/opponent');assert(main.textContent.includes('Gamma'));
        """)

    def test_unchanged_revision_does_not_add_library_fetches_or_redraw_focused_links(self):
        self.run_js(r"""
          open();const link=main.querySelector('.mu-cell-link');link.focus();read=async()=>answer();
          await matchupRefresh.refresh();same(requests.map(item=>item.url),['/api/matchups']);
          assert.equal(main.querySelector('.mu-cell-link'),link);assert.equal(document.activeElement,link);assert.equal(writes,0);
        """)

    def test_old_play_link_picks_both_renamed_decks_and_preserves_play_now_versions(self):
        self.run_js(r"""
          // Supply native select option/value behavior, absent from the small DOM double.
          const create=document.createElement;document.createElement=tag=>{
            const node=create(tag);
            if(tag==='select'){
              let chosen='';Object.defineProperty(node,'options',{get:()=>node.querySelectorAll('option')});
              Object.defineProperty(node,'value',{get:()=>node.options.some(option=>option.value===chosen)?chosen
                :(node.options.find(option=>option.getAttribute('selected')!==null)||node.options[0])?.value||'',
                set:value=>{chosen=String(value);}});
            }
            return node;
          };
          const lib={halves:[],decks:[deck('casual/first','First deck'),
            deck('casual/new','Renamed Gamma',{aliases:['casual/old'],versions:['target','owned']}),
            deck('casual/second','Renamed second',{aliases:['casual/second-old'],versions:['target','owned']})]};
          const sheet=openPlaySheet(lib,()=>answer('after',true),routeToken,
            {a:'casual/old',av:'owned',b:'casual/second-old',bv:'owned'});
          assert.equal(sheet.body.querySelector('#pick-1').value,'casual/new');
          assert.equal(sheet.body.querySelector('#pick-2').value,'casual/second');
          for(const picker of sheet.body.querySelectorAll('.mu-pick')){
            const owned=picker.querySelectorAll('button').find(button=>button.textContent===listName('owned'));
            assert.equal(owned.getAttribute('aria-pressed'),'true');
          }
          same(requests,[]);assert.equal(writes,0);
        """)
