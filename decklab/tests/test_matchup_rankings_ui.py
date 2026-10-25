"""Saved field rankings through the real UI with isolated DOM and API fixtures."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class MatchupRankingsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        setup = """
          clear(main);editor=null;state.profile={id:'matt',name:'Matt'};state.may=null;
          const storage=new Map();window.localStorage={getItem:k=>storage.get(k)??null,
            setItem:(k,v)=>storage.set(k,String(v)),removeItem:k=>storage.delete(k)};
          const host=el('div');main.append(host);
          const library={halves:[],decks:[
            {id:'casual/a',title:'Alpha',kind:'casual',versions:['target','owned']},
            {id:'casual/b',title:'Beta',kind:'casual',versions:['target']},
            {id:'commander/c',title:'Commander C',kind:'commander',versions:['target']},
            {id:'commander/d',title:'Commander D',kind:'commander',versions:['target']}]};
          const data={running:[],results:[]};
          const view={mode:'rankings',format:'Constructed',deck:'casual/b',token:routeToken,
            profile:state.profile.id,rankings:new Map()};
          const row=(id,title,extra={})=>({id,title,kind:'casual',version:'target',card_sha:id,
            versions:['target'],in_field:true,exclusion:null,group:null,rating:null,games:0,
            unsettled:true,reasons:['No usable saved games yet.'],...extra});
          const rating=(value,rank=1,of=2)=>({value,low:value-.2,high:value+.2,rank,
            rank_low:1,rank_high:of,of,h_points:0});
          const answer=(format='Constructed',extra={})=>({format,rows:[],groups:[],notes:[],error:null,...extra});
          const button=(scope,text)=>scope.querySelectorAll('button').find(b=>b.textContent===text);
          const names=scope=>scope.querySelectorAll('.mu-ranking-row').map(n=>n.getAttribute('data-deck'));
          const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
          let writes=0;apiWrite=async()=>{writes++;throw new Error('Rankings must never write');};
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_rankings_switch_fetches_saved_data_without_starting_games(self):
        self.run_js("""
          const calls=[];api=async url=>{calls.push(url);return answer('Constructed',{
            rows:[row('casual/a','Alpha')]});};
          view.mode='matchups';drawHome(host,data,library,view);
          assert(host.querySelector('.mu-matrix-part'));assert.equal(calls.length,0);
          button(host,'Rankings').click();await settle();
          same(calls,['/api/rankings?format=Constructed']);assert.equal(writes,0);
          assert.equal(button(host,'Rankings').getAttribute('aria-pressed'),'true');
          assert.equal(button(host,'Matchups').getAttribute('aria-pressed'),'false');
          assert(host.querySelector('.mu-rankings'));assert(!host.querySelector('.mu-matrix-part'));
          assert.equal(storage.get('decklab.matchups.view'),'rankings');
          assert(!host.querySelector('[data-run]'));
        """)

    def test_every_current_list_remains_visible_with_uncertainty_reasons_and_notes(self):
        self.run_js("""
          const rows=[row('casual/a','Alpha',{group:'g',rating:rating(.8),games:1200,
              versions:['target','owned'],reasons:['Not enough precision.']}),
            row('casual/b','Beta',{group:'g',rating:rating(.2,2),games:800,unsettled:false,reasons:[]}),
            row('casual/new','New list'),row('casual/excluded','Incomplete list',{
              in_field:false,games:900,exclusion:'Only 58 cards.',reasons:['Only 58 cards.','The list is incomplete.']})];
          muDrawRankings(host,{answer:answer('Constructed',{rows,groups:[{id:'g',lists:2,players:2}],
            notes:['Only current lists and the current engine count.','Same cards and pilot share one rating.']})},'Constructed');
          assert.equal(host.querySelectorAll('.mu-ranking-row').length,4);
          assert(host.textContent.includes('Rank 1 of 2'));assert(/Likely rank 1[^0-9]+2/.test(host.textContent));
          assert(host.textContent.includes('Rating 80%'));assert(/95% range 60%[^0-9]+100%/.test(host.textContent));
          assert(host.textContent.includes('1,200 games'));assert(host.textContent.includes('Unsettled'));
          assert(host.textContent.includes('Not enough precision.'));assert(host.textContent.includes('No rating yet'));
          const excluded=host.querySelectorAll('.mu-ranking-row').find(n=>n.dataset.deck==='casual/excluded');
          assert(excluded.textContent.includes('Outside the field'));assert(excluded.textContent.includes('The list is incomplete.'));
          assert(!excluded.textContent.includes('900 games'));assert(!excluded.textContent.includes('0 games'));
          assert.equal(excluded.textContent.split('Only 58 cards.').length-1,1);
          assert(host.textContent.includes('How rankings are worked out'));
          assert(host.textContent.includes('Only current lists and the current engine count.'));
          assert(host.textContent.includes('average current field list in the same group'));
          assert(host.textContent.includes('balanced for who starts'));assert(host.textContent.includes('promise about a real game'));
          assert(!host.textContent.includes('null'));assert.equal(writes,0);
        """)

    def test_disconnected_groups_sort_only_within_each_group(self):
        self.run_js("""
          const rows=[row('casual/low','Low',{group:'first',rating:rating(.1,2),games:30}),
            row('casual/huge','Huge',{group:'second',rating:rating(.9),games:50}),
            row('casual/high','High',{group:'first',rating:rating(.2),games:30}),
            row('casual/small','Small',{group:'second',rating:rating(.8,2),games:50})];
          muDrawRankings(host,{answer:answer('Constructed',{rows,groups:[
            {id:'first',lists:2,players:2},{id:'second',lists:2,players:2}]})},'Constructed');
          const groups=host.querySelectorAll('.mu-ranking-group');assert.equal(groups.length,2);
          same(names(groups[0]),['casual/high','casual/low']);same(names(groups[1]),['casual/huge','casual/small']);
          assert(host.textContent.includes('there is no ranking between groups'));
          assert(groups.every(g=>g.textContent.includes('Rank 1 of 2')));
          assert(!host.textContent.includes('Rank 1 of 4'));assert(!host.textContent.includes('Rank 3'));
        """)

    def test_aliases_share_one_row_and_owned_only_links_keep_the_version(self):
        self.run_js("""
          const merged=muRankingRow(row('casual/a','Alpha',{versions:['target','owned']}));
          const owned=muRankingRow(row('casual/b','Beta',{version:'owned',versions:['owned']}));
          host.append(merged,owned);assert.equal(host.querySelectorAll('.mu-ranking-row').length,2);
          assert(merged.textContent.includes('Planned and play-now lists (same cards and pilot)'));
          assert.equal(merged.querySelector('a').getAttribute('href'),deckHref('casual/a','target'));
          assert.equal(owned.querySelector('a').getAttribute('href'),deckHref('casual/b','owned'));
          assert(owned.textContent.toLowerCase().includes('play-now'));
        """)

    def test_unknown_nonfinite_and_partial_ratings_do_not_invent_ranks(self):
        self.run_js("""
          for(const value of [null,undefined,NaN,Infinity,'1.5']){
            const node=muRankingRow(row('casual/a','Alpha',{rating:value==null?null:{value},games:0}));
            assert(node.textContent.includes('No rating yet'));assert(!node.textContent.includes('Rating NaN'));
            assert(!node.textContent.includes('Rank undefined'));assert(!node.textContent.includes('Rank null'));
          }
          const partial=muRankingRow(row('casual/a','Alpha',{rating:{value:.625},games:5}));
          assert(partial.textContent.includes('No rating yet'));assert(partial.textContent.includes('Rank range unavailable'));
          assert(partial.textContent.includes('Rating 63%'));assert(partial.textContent.includes('5 games'));
          const precise=muRankingRow(row('casual/a','Alpha',{rating:{...rating(1),rank_low:1,rank_high:1}}));
          assert(precise.textContent.includes('Likely rank 1'));assert(!precise.textContent.includes('Likely rank 1-1'));
        """)

    def test_zero_or_one_list_still_offers_rankings_for_both_formats(self):
        self.run_js("""
          let single=false;api=async url=>answer(url.includes('Commander')?'Commander':'Constructed',{
            rows:single?[row('casual/a','Only list')]:[]});
          drawHome(host,data,{decks:[],halves:[]},view);await settle();
          assert(host.textContent.includes('There are no current lists of this format to rank.'));
          assert(button(host,'60-card'));assert(button(host,'Commander'));assert(!host.textContent.includes('There are no two decks'));
          single=true;view.rankingsForce=true;await muRefreshRankings(view,data);
          assert.equal(host.querySelectorAll('.mu-ranking-row').length,1);
          assert(host.textContent.includes('Only list'));assert(host.textContent.includes('No rating yet'));
          assert(!host.textContent.includes('There are no current lists'));assert.equal(writes,0);
        """)

    def test_refresh_keeps_selected_mode_format_and_phone_deck(self):
        self.run_js("""
          view.format='Commander';view.deck='commander/d';let calls=0;
          api=async()=>{calls++;return answer('Commander',{rows:[row('commander/c','Commander C')]});};
          drawHome(host,data,library,view);await settle();drawHome(host,{running:[],results:[]},library,view);await settle();
          assert.equal(view.mode,'rankings');assert.equal(view.format,'Commander');assert.equal(view.deck,'commander/d');
          assert.equal(calls,1);assert.equal(button(host,'Commander').getAttribute('aria-pressed'),'true');
          button(host,'Matchups').click();assert.equal(view.deck,'commander/d');
          assert.equal(view.format,'Commander');assert(host.querySelector('.mu-phone-part'));
          button(host,'Rankings').click();await settle();assert.equal(view.deck,'commander/d');assert.equal(writes,0);
        """)

    def test_format_changes_are_single_flight_and_only_latest_choice_is_queued(self):
        self.run_js("""
          const pending=[],calls=[];api=url=>{calls.push(url);return new Promise(resolve=>pending.push(resolve));};
          drawHome(host,data,library,view);assert.equal(calls.length,1);
          button(host,'Commander').click();button(host,'60-card').click();button(host,'Commander').click();
          assert.equal(calls.length,1);assert.equal(view.format,'Commander');
          pending.shift()(answer('Constructed',{rows:[row('casual/a','Old format')]}));await settle();
          same(calls,['/api/rankings?format=Constructed','/api/rankings?format=Commander']);
          assert(!host.textContent.includes('Old format'));
          pending.shift()(answer('Commander',{rows:[row('commander/c','Latest format')]}));await settle();
          assert(host.textContent.includes('Latest format'));assert(!host.textContent.includes('Old format'));
          assert.equal(view.rankingsRequest,null);assert.equal(view.rankingsHost.getAttribute('aria-busy'),'false');
        """)

    def test_saved_results_changed_during_a_read_are_queried_again_once(self):
        self.run_js("""
          const pending=[];let calls=0;api=()=>{calls++;return new Promise(resolve=>pending.push(resolve));};
          drawHome(host,data,library,view);
          const fresh={running:[],results:[{format:'Constructed',games:400,updated:'new'}]};
          await muRefreshRankings(view,fresh);await muRefreshRankings(view,fresh);assert.equal(calls,1);
          pending.shift()(answer('Constructed',{rows:[row('casual/a','Before new games')]}));await settle();
          assert.equal(calls,2);pending.shift()(answer('Constructed',{rows:[row('casual/a','After new games')]}));await settle();
          assert.equal(calls,2);assert(host.textContent.includes('After new games'));
          assert(!host.textContent.includes('Before new games'));assert.equal(writes,0);
        """)

    def test_route_change_discards_late_response_and_old_switch_callbacks(self):
        self.run_js("""
          let resolve,calls=0;api=()=>{calls++;return new Promise(r=>resolve=r);};
          drawHome(host,data,library,view);const oldSwitch=button(host,'Commander');
          routeToken++;host.replaceChildren(el('p',{text:'Another route'}));
          resolve(answer('Constructed',{rows:[row('casual/a','Late private list')]}));await settle();
          assert.equal(host.textContent,'Another route');assert.equal(view.rankings.get('Constructed').answer,null);
          oldSwitch.click();assert.equal(view.format,'Constructed');assert.equal(calls,1);
          assert.equal(view.rankingsRequest,null);
        """)

    def test_profile_change_discards_late_success_and_failure(self):
        self.run_js("""
          let resolve;api=()=>new Promise(r=>resolve=r);drawHome(host,data,library,view);
          const oldSwitch=button(host,'Commander');state.profile={id:'user1',name:'User1'};
          host.replaceChildren(el('p',{text:'User1’s page'}));
          resolve(answer('Constructed',{rows:[row('casual/a','Matt’s late list')]}));await settle();
          assert.equal(host.textContent,'User1’s page');assert.equal(view.rankings.get('Constructed').answer,null);
          oldSwitch.click();assert.equal(view.format,'Constructed');
          state.profile={id:'matt'};view.rankingsForce=true;let reject;api=()=>new Promise((r,no)=>reject=no);
          drawHome(host,data,library,view);state.profile={id:'user1'};host.replaceChildren(el('p',{text:'Still User1'}));
          reject(new Error('Late Matt failure'));await settle();assert.equal(host.textContent,'Still User1');
          assert.equal(view.rankings.get('Constructed').error,null);
        """)

    def test_rankings_are_readable_when_new_simulations_are_not_allowed(self):
        self.run_js("""
          state.may={simulations:false};runsAllowed=()=>false;
          api=async()=>answer('Constructed',{rows:[row('casual/a','Saved Alpha')]});
          drawHome(host,data,library,view);await settle();
          assert(host.textContent.includes('Saved Alpha'));assert(button(host,'Rankings'));
          assert.equal(writes,0);assert(!host.querySelector('[data-run]'));
        """)

    def test_errors_are_distinct_from_empty_and_preserve_cached_rows(self):
        self.run_js("""
          api=async()=>answer('Constructed',{rows:[row('casual/a','Cached Alpha')]});
          drawHome(host,data,library,view);await settle();
          view.rankingsForce=true;api=async()=>{throw new Error('Temporary database failure');};
          await muRefreshRankings(view,data);
          assert(host.textContent.includes("Rankings aren't available"));assert(host.textContent.includes('Temporary database failure'));
          assert(host.textContent.includes('Trying again automatically.'));assert(host.textContent.includes('Cached Alpha'));
          assert(host.textContent.includes('saved display below may be out of date'));
          muDrawRankings(host,{answer:answer('Commander',{error:'Unable to fit rankings'})},'Commander');
          assert(host.textContent.includes('Unable to fit rankings'));assert(!host.textContent.includes('There are no current lists'));
          view.rankingsHost=host;view.rankingsForce=true;api=async()=>answer('Commander');await muRefreshRankings(view,data);
          assert(host.textContent.includes('different format'));assert(!host.textContent.includes('There are no current lists'));
        """)

    def test_unchanged_data_is_throttled_but_new_games_and_idle_expiry_refresh(self):
        self.run_js("""
          let now=100000,calls=0;Date.now=()=>now;api=async()=>{calls++;return answer('Constructed',{
            rows:[row('casual/a','Alpha')],notes:['Only saved current games count.']});};
          drawHome(host,data,library,view);await settle();assert.equal(calls,1);
          const keptRow=view.rankingsHost.querySelector('.mu-ranking-row'),keptLink=keptRow.querySelector('a');
          const detail=view.rankingsHost.querySelector('details');detail.open=true;keptLink.focus();
          await muRefreshRankings(view,{running:[],results:[]});assert.equal(calls,1);
          assert.equal(view.rankingsHost.querySelector('.mu-ranking-row'),keptRow);
          assert.equal(view.rankingsHost.querySelector('.mu-ranking-row').querySelector('a'),keptLink);
          assert.equal(document.activeElement,keptLink);assert.equal(view.rankingsHost.querySelector('details'),detail);assert(detail.open);
          await muRefreshRankings(view,{running:[],results:[{format:'Commander',games:300}]});assert.equal(calls,1);
          assert.equal(view.rankingsHost.querySelector('.mu-ranking-row'),keptRow);assert.equal(document.activeElement,keptLink);
          const changed={running:[],results:[{format:'Constructed',games:500,updated:'later'}]};
          await muRefreshRankings(view,changed);assert.equal(calls,2);
          now+=IDLE_MATCHUP_POLL_MS-1;await muRefreshRankings(view,changed);assert.equal(calls,2);
          now++;await muRefreshRankings(view,changed);assert.equal(calls,3);
          assert.equal(writes,0);
        """)

    def test_timeout_releases_single_flight_even_when_the_api_ignores_abort(self):
        self.run_js("""
          const pending=[];api=(url,opts)=>new Promise(resolve=>pending.push({url,resolve,signal:opts.signal}));
          drawHome(host,data,library,view);assert.equal(pending.length,1);
          flushTimers();await settle();assert(pending[0].signal.aborted);
          assert.equal(view.rankingsRequest,null);assert.equal(view.rankingsHost.getAttribute('aria-busy'),'false');
          assert(host.textContent.includes('took too long to answer the rankings'));
          assert(!host.textContent.includes('There are no current lists'));
          view.rankings.get('Constructed').asked=Date.now()-IDLE_MATCHUP_POLL_MS-1;
          const retry=muRefreshRankings(view,data);assert.equal(pending.length,2);
          pending[1].resolve(answer('Constructed',{rows:[row('casual/a','Fresh retry')]}));await retry;
          pending[0].resolve(answer('Constructed',{rows:[row('casual/a','Expired answer')]}));await settle();
          assert(host.textContent.includes('Fresh retry'));assert(!host.textContent.includes('Expired answer'));
          assert(!host.textContent.includes('took too long'));assert.equal(writes,0);
        """)

    def test_timeout_starts_the_latest_queued_format_and_detached_answers_do_not_render(self):
        self.run_js("""
          const pending=[];api=(url,opts)=>new Promise(resolve=>pending.push({url,resolve,signal:opts.signal}));
          drawHome(host,data,library,view);button(host,'Commander').click();assert.equal(pending.length,1);
          flushTimers();await settle();assert.equal(pending.length,2);assert(pending[0].signal.aborted);
          assert(pending[1].url.includes('Commander'));assert.equal(view.rankingsRequest.format,'Commander');
          host.remove();const before=host.textContent;
          pending[1].resolve(answer('Commander',{rows:[row('commander/c','Detached answer')]}));await settle();
          pending[0].resolve(answer('Constructed',{rows:[row('casual/a','Expired answer')]}));await settle();
          assert.equal(host.textContent,before);assert(!host.textContent.includes('Detached answer'));
          assert.equal(view.rankingsRequest,null);assert.equal(writes,0);
        """)

    def test_leaving_rankings_aborts_the_read_and_returning_fetches_immediately(self):
        self.run_js("""
          const pending=[];api=(url,opts)=>new Promise(resolve=>pending.push({url,resolve,signal:opts.signal}));
          drawHome(host,data,library,view);button(host,'Matchups').click();await settle();
          assert(pending[0].signal.aborted);assert.equal(view.rankingsRequest,null);
          assert(host.querySelector('.mu-phone-part'));assert(!host.querySelector('.mu-rankings'));
          button(host,'Rankings').click();assert.equal(pending.length,2);
          pending[1].resolve(answer('Constructed',{rows:[row('casual/a','New visit')]}));await settle();
          pending[0].resolve(answer('Constructed',{rows:[row('casual/a','Cancelled visit')]}));await settle();
          assert(host.textContent.includes('New visit'));assert(!host.textContent.includes('Cancelled visit'));
          assert(!host.textContent.includes('Rankings read cancelled'));assert.equal(writes,0);
        """)

    def test_real_page_hidden_pagehide_and_stop_cancel_rankings_without_errors(self):
        self.run_js("""
          clear(main);local.set(HOME_VIEW_KEY,'rankings');document.visibilityState='visible';
          runGate=()=>({may:false,why:'Simulations are paused.'});const pending=[];
          api=(url,opts)=>new Promise(resolve=>pending.push({url,resolve,signal:opts.signal}));
          drawMatchups(library,data,new URLSearchParams(),routeToken);
          assert.equal(pending.length,1);assert(pending[0].url.includes('/api/rankings'));
          document.visibilityState='hidden';document.fire('visibilitychange');await settle();
          assert(pending[0].signal.aborted);assert.equal(pending.length,1);
          pending[0].resolve(answer('Constructed',{rows:[row('casual/a','Hidden answer')]}));await settle();
          assert(!main.textContent.includes('Hidden answer'));assert(!main.textContent.includes('Rankings read cancelled'));
          document.visibilityState='visible';document.fire('visibilitychange');assert.equal(pending.length,2);
          assert.equal(pending[1].url,'/api/matchups');pending[1].resolve(data);await settle();
          assert.equal(pending.length,3);assert(pending[2].url.includes('/api/rankings'));
          window.fire('pagehide');await settle();assert(pending[2].signal.aborted);
          pending[2].resolve(answer('Constructed',{rows:[row('casual/a','Pagehide answer')]}));await settle();
          assert(!main.textContent.includes('Pagehide answer'));
          window.fire('pageshow');assert.equal(pending.length,4);pending[3].resolve(data);await settle();
          assert.equal(pending.length,5);stopMatchupRefresh();await settle();assert(pending[4].signal.aborted);
          const before=main.textContent;pending[4].resolve(answer('Constructed',{rows:[row('casual/a','Stopped answer')]}));await settle();
          assert.equal(main.textContent,before);assert(!main.textContent.includes('Stopped answer'));
          assert(!main.textContent.includes('Rankings read cancelled'));assert.equal(writes,0);
        """)


if __name__ == "__main__":
    unittest.main()
