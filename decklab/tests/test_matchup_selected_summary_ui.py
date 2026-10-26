"""Selected-list field summaries on Matchups: exact context, read-only cache and late-answer isolation."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class MatchupSelectedSummaryUiTests(unittest.TestCase):
    def run_js(self, scenario):
        setup = r"""
          clear(main);editor=null;state.profile={id:'matt',name:'Matt'};state.may=null;
          const library={decks_revision:'library-one',halves:[],decks:[
            {id:'casual/a',title:'Alpha',kind:'casual',status:'idea',revision:'a-one',versions:['target','owned']},
            {id:'casual/b',title:'Beta',kind:'casual',status:'built',revision:'b-one',versions:['target']}]};
          const data={running:[],results:[]};
          const makeView=()=>({mode:'matchups',format:'Constructed',deck:'casual/a',token:routeToken,
            profile:state.profile.id});
          let view=makeView();
          const field=(id='casual/a',version='target',extra={})=>({
            deck:{id,version,title:id==='casual/a'?'Alpha':'Beta'},format:'Constructed',
            opponents:[{id:'casual/b',version:'target',title:'Beta',games:400,
              rate:{value:.64,low:.60,high:.68},residual:{flag:'strong',r:.12}}],
            average:{value:.64,low:.60,high:.68,partial:true,counted:1,of:2},
            rating:{rank:1,of:2,h_points:7},last_run:{when:'2026-10-24'},...extra});
          const swap=(extra={})=>({test:'newest-test',changes:{remove:[[1,'Elf']],add:[[1,'Bolt']]},
            against:'field',delta:.02,low:-.01,high:.05,verdict:'slightly_better',when:'2026-10-24',...extra});
          const params=url=>new URL(url,'https://fixture.invalid').searchParams;
          const isField=url=>url.startsWith('/api/field?');
          const isSwap=url=>url.startsWith('/api/variants?');
          const settle=async()=>{for(let n=0;n<30;n++)await Promise.resolve();};
          const held=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
          const mount=()=>{clear(main);const summary=library.decks.find(d=>d.id===view.deck);
            const node=muSelectedSummary(view,library,data,summary||{id:view.deck,title:'Pairing',kind:'pairing'});
            main.append(node);return node;};
          const button=(host,text='Try again')=>host.querySelectorAll('button').find(node=>node.textContent===text);
          let writes=0;apiWrite=async()=>{writes++;throw new Error('Summaries must never write');};
        """
        done = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + scenario, True]),
                              capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "ok")

    def test_field_and_latest_swap_use_server_figures_for_the_explicit_list(self):
        self.run_js(r"""
          const calls=[];api=async(url)=>{calls.push(url);return isField(url)?field():{tests:[swap(),swap({test:'older-test',changes:{add:[[1,'Older']]}})]};};
          data.results=[{format:'Constructed',winrate:{value:.99},games:10000}];
          const host=mount();await muRefreshSelectedSummary(view);await settle();
          assert.equal(calls.length,2);assert(calls.some(isField));assert(calls.some(isSwap));
          assert(calls.every(url=>params(url).get('id')==='casual/a'&&params(url).get('version')==='target'));
          assert(host.textContent.includes('Planned list'));assert(host.textContent.includes('64'));
          assert(host.textContent.includes('Based on 1 of 2 decks'));assert(host.textContent.includes('Going first is worth about 7 points'));
          assert(host.querySelector('.flag-strong'));assert(host.querySelector('.swap-result'));
          assert(host.textContent.includes('not proven'));assert(host.textContent.includes('Bolt'));
          assert(host.textContent.includes('Recorded tests keep the cards they tested. Open the test for its exact cards.'));
          assert(!host.textContent.includes('Older'));assert(!host.textContent.includes('99%'));
          const links=host.querySelectorAll('a').map(node=>node.getAttribute('href'));
          assert(links.some(href=>href.includes('newest-test')));assert(!links.some(href=>href.includes('older-test')));
          assert(links.some(href=>href.includes('v=target')&&href.includes('part=field')));
          assert.equal(host.querySelectorAll('[data-run]').length,0);assert.equal(writes,0);
        """)

    def test_built_play_now_context_requires_an_available_owned_list(self):
        self.run_js(r"""
          for(const [status,built,versions,expected,words] of [
            ['built','owned',['target','owned'],'owned','Play-now list'],
            ['built','owned',['target'],'target','Planned list'],
            ['idea','owned',['target','owned'],'target','Planned list'],
            ['built','target',['target','owned'],'target','Planned list']]){
            Object.assign(library.decks[0],{status,built_version:built,versions});view=makeView();const calls=[];
            api=async url=>{calls.push(url);return isField(url)?field('casual/a',expected):{tests:[]};};
            const host=mount();await muRefreshSelectedSummary(view);await settle();
            assert.equal(calls.length,2);assert(calls.every(url=>params(url).get('version')===expected));
            assert(host.textContent.includes(words));assert(host.textContent.includes('No tests of this list yet'));
          }
          assert.equal(writes,0);
        """)

    def test_same_signature_reuses_reads_across_progress_redraws_and_invalidates_saved_evidence(self):
        self.run_js(r"""
          const calls=[];api=async url=>{calls.push(url);return isField(url)?field('casual/a',params(url).get('version')):{tests:[]};};
          mount();await muRefreshSelectedSummary(view);await settle();assert.equal(calls.length,2);
          data.running=[{key:'running',status:'running',done:10,total:400}];
          let host=mount();await muRefreshSelectedSummary(view);await settle();
          data.running[0].done=20;host=mount();await muRefreshSelectedSummary(view);await settle();
          assert.equal(calls.length,2);assert(host.textContent.includes('64'));
          data.results=[{format:'Constructed',key:'saved',games:200}];
          mount();await muRefreshSelectedSummary(view);await settle();assert.equal(calls.length,4);
          library.decks[0].revision='a-two';mount();await muRefreshSelectedSummary(view);await settle();assert.equal(calls.length,6);
          library.decks_revision='library-two';mount();await muRefreshSelectedSummary(view);await settle();assert.equal(calls.length,8);
          Object.assign(library.decks[0],{status:'built',built_version:'owned'});
          host=mount();await muRefreshSelectedSummary(view);await settle();assert.equal(calls.length,10);
          assert(calls.slice(-2).every(url=>params(url).get('version')==='owned'));assert(host.textContent.includes('Play-now list'));
        """)

    def test_pending_read_is_reused_by_a_same_context_redraw(self):
        self.run_js(r"""
          const pending=[];api=(url,options={})=>{const read=held();pending.push({url,signal:options.signal,...read});return read.promise;};
          const first=mount();muRefreshSelectedSummary(view);await settle();assert.equal(pending.length,2);
          const before=first.textContent;const current=mount();muRefreshSelectedSummary(view);await settle();
          assert.equal(pending.length,2);assert(pending.every(read=>!read.signal.aborted));
          for(const read of pending)read.resolve(isField(read.url)?field():{tests:[swap()]});
          await settle();assert(current.textContent.includes('64'));assert(current.textContent.includes('Bolt'));
          assert.equal(first.textContent,before);assert.equal(writes,0);
        """)

    def test_late_answers_cannot_cross_attachment_route_profile_deck_format_or_mode(self):
        self.run_js(r"""
          for(const change of ['detached','route','profile','deck','format','mode']){
            state.profile={id:'matt'};view=makeView();const pending=[];
            api=(url,options={})=>{const read=held();pending.push({url,...read});return read.promise;};
            const host=mount();muRefreshSelectedSummary(view);await settle();const before=host.textContent;
            if(change==='detached')clear(main);if(change==='route')routeToken++;
            if(change==='profile')state.profile={id:'user1'};if(change==='deck')view.deck='casual/b';
            if(change==='format')view.format='Commander';if(change==='mode')view.mode='rankings';
            for(const read of pending)read.resolve(isField(read.url)?field():{tests:[swap()]});
            await settle();assert.equal(host.textContent,before,change);
          }
          assert.equal(writes,0);
        """)

    def test_field_response_must_echo_exact_deck_list_and_format(self):
        self.run_js(r"""
          for(const extra of [{deck:{id:'casual/b',version:'target'}},{deck:{id:'casual/a',version:'owned'}},
            {format:'Commander'},{deck:null},{deck:{id:'casual/a'}}]){
            view=makeView();api=async url=>isField(url)?field('casual/a','target',{...extra,average:{value:.99}}):{tests:[swap()]};
            const host=mount();await muRefreshSelectedSummary(view);await settle();
            assert(!host.textContent.includes('99%'));assert(button(host));assert(host.textContent.includes('Bolt'));
          }
        """)

    def test_failed_field_can_retry_without_refetching_a_successful_swap(self):
        self.run_js(r"""
          let failed=true;const calls=[];api=async url=>{calls.push(url);if(isSwap(url))return {tests:[swap()]};
            if(failed)throw new Error('offline');return field();};
          const host=mount();await muRefreshSelectedSummary(view);await settle();
          assert(button(host));assert(host.textContent.includes('Bolt'));assert(!host.textContent.includes('64'));
          failed=false;button(host).click();await settle();
          assert(host.textContent.includes('64'));assert(!button(host));
          assert.equal(calls.filter(isField).length,2);assert.equal(calls.filter(isSwap).length,1);assert.equal(writes,0);
        """)

    def test_variant_identity_when_supplied_cannot_cross_the_requested_list(self):
        self.run_js(r"""
          api=async url=>isField(url)?field():{deck:{id:'casual/a',version:'owned'},tests:[swap({changes:{add:[[1,'Wrong-list card']]}})]};
          const host=mount();await muRefreshSelectedSummary(view);await settle();
          assert(host.textContent.includes('64'));assert(!host.textContent.includes('Wrong-list card'));assert(button(host));
        """)

    def test_running_and_inconclusive_latest_swaps_keep_the_shared_result_words(self):
        self.run_js(r"""
          for(const latest of [swap({running:true,done:25,total:100}),swap({delta:null,low:null,high:null,verdict:'not_settled'})]){
            view=makeView();api=async url=>isField(url)?field():{tests:[latest]};
            const host=mount();await muRefreshSelectedSummary(view);await settle();
            assert(host.textContent.includes('Bolt'));assert(host.querySelectorAll('a').some(a=>(a.getAttribute('href')||'').includes('newest-test')));
            assert(latest.running?host.textContent.includes('Testing:'):host.textContent.includes('not settled'));
          }
        """)

    def test_read_only_products_and_pairings_never_request_swap_history(self):
        self.run_js(r"""
          for(const summary of [
            {...library.decks[0],read_only:true},
            {id:'product/precon',title:'Precon',kind:'product',versions:['target']},
            {id:'pairing/a+b',title:'Pairing',kind:'pairing',versions:['target']}]){
            library.decks=[summary];view=makeView();view.deck=summary.id;const calls=[];
            api=async url=>{calls.push(url);return field(summary.id);};
            const host=mount();await muRefreshSelectedSummary(view);await settle();
            assert.equal(calls.filter(isSwap).length,0);assert.equal(calls.filter(isField).length,1);assert(host.textContent.includes('Planned list'));
          }
        """)

    def test_aborted_a_to_b_to_a_reads_cannot_poison_the_current_cached_answer(self):
        self.run_js(r"""
          const pending=[];api=(url,options={})=>{const read=held();pending.push({url,signal:options.signal,...read});return read.promise;};
          mount();muRefreshSelectedSummary(view);await settle();const first=pending.slice();muCancelSelectedSummary(view);
          view.deck='casual/b';mount();muRefreshSelectedSummary(view);await settle();const middle=pending.slice(2);muCancelSelectedSummary(view);
          view.deck='casual/a';const host=mount();muRefreshSelectedSummary(view);await settle();const current=pending.slice(4);
          assert.equal(current.length,2);assert(first.every(read=>read.signal.aborted));assert(middle.every(read=>read.signal.aborted));
          for(const read of first)read.resolve(isField(read.url)?field('casual/a','target',{average:{value:.99}}):{tests:[swap({changes:{add:[[1,'Stale A']]}})]});
          for(const read of middle)read.resolve(isField(read.url)?field('casual/b','target',{average:{value:.98}}):{tests:[swap({changes:{add:[[1,'Stale B']]}})]});
          await settle();assert(!host.textContent.includes('99%'));assert(!host.textContent.includes('Stale'));
          for(const read of current)read.resolve(isField(read.url)?field('casual/a','target',{average:{value:.72,low:.70,high:.74}}):{tests:[swap()]});
          await settle();assert(host.textContent.includes('72'));assert(!host.textContent.includes('Stale'));
          const redraw=mount();await muRefreshSelectedSummary(view);await settle();
          assert.equal(pending.length,6);assert(redraw.textContent.includes('72'));assert(!redraw.textContent.includes('99%'));
        """)

    def test_cache_is_bounded_and_field_empty_state_does_not_invent_statistics(self):
        self.run_js(r"""
          api=async url=>isField(url)?field('casual/a','target',{opponents:[],average:null,rating:null}):{tests:[]};
          for(let n=0;n<MU_SELECTED_CACHE_KEEP+4;n++){
            library.decks[0].revision='revision-'+n;const host=mount();await muRefreshSelectedSummary(view);await settle();
            assert(host.textContent.includes('No other decks'));assert(!host.textContent.includes('Going first'));
          }
          assert(view.selectedCache.size<=MU_SELECTED_CACHE_KEEP);assert.equal(writes,0);
        """)

    def test_timeout_releases_reads_and_retry_uses_a_fresh_request(self):
        self.run_js(r"""
          const pending=[];api=(url,options={})=>{const read=held();pending.push({url,signal:options.signal,...read});return read.promise;};
          const host=mount();muRefreshSelectedSummary(view);await settle();assert.equal(pending.length,2);
          flushTimers();await settle();assert(pending.every(read=>read.signal.aborted));
          assert.equal(host.querySelectorAll('button').filter(b=>b.textContent==='Try again').length,2);
          button(host).click();await settle();assert.equal(pending.length,3);
          const retry=pending[2];assert(isField(retry.url));assert(!retry.signal.aborted);assert.notEqual(retry.signal,pending[0].signal);
          retry.resolve(field('casual/a','target',{average:{value:.73,low:.71,high:.75}}));await settle();
          assert(host.textContent.includes('73'));assert.equal(host.querySelectorAll('button').filter(b=>b.textContent==='Try again').length,1);
          for(const read of pending.slice(0,2))read.resolve(isField(read.url)?field('casual/a','target',{average:{value:.99}}):{tests:[swap({changes:{add:[[1,'Too late']]}})]});
          await settle();assert(!host.textContent.includes('99%'));assert(!host.textContent.includes('Too late'));assert.equal(writes,0);
        """)

    def test_hidden_pause_aborts_pending_reads_and_resumes_the_same_context(self):
        self.run_js(r"""
          const pending=[];api=(url,options={})=>{const read=held();pending.push({url,signal:options.signal,...read});return read.promise;};
          const host=mount();muRefreshSelectedSummary(view);await settle();const before=host.textContent;
          document.visibilityState='hidden';muCancelSelectedSummary(view);assert(pending.every(read=>read.signal.aborted));
          for(const read of pending.slice())read.resolve(isField(read.url)?field():{tests:[swap()]});await settle();
          assert.equal(host.textContent,before);await muRefreshSelectedSummary(view);assert.equal(pending.length,2);
          document.visibilityState='visible';muRefreshSelectedSummary(view);await settle();assert.equal(pending.length,4);
          for(const read of pending.slice(2))read.resolve(isField(read.url)?field():{tests:[swap()]});await settle();
          assert(host.textContent.includes('64'));assert(host.textContent.includes('Bolt'));assert(!button(host));assert.equal(writes,0);
        """)

    def test_home_mounts_the_list_summary_and_cancels_it_when_rankings_is_selected(self):
        self.run_js(r"""
          const pending=[];api=(url,options={})=>{
            if(url.startsWith('/api/rankings?'))return Promise.resolve({format:'Constructed',rows:[],groups:[],notes:[],error:null});
            const read=held();pending.push({url,signal:options.signal,...read});return read.promise;
          };
          const host=el('div');main.append(host);drawHome(host,data,library,view);
          assert(host.querySelector('.mu-selected-summary'));assert(host.querySelector('.mu-opponents'));
          assert(host.textContent.includes('Saved matchup rows below may use different lists or earlier engines'));
          assert(host.textContent.includes('Planned list'));muRefreshSelectedSummary(view);await settle();assert.equal(pending.length,2);
          button(host,'Rankings').click();await settle();assert(pending.every(read=>read.signal.aborted));
          assert(host.querySelector('.mu-rankings'));assert(!host.querySelector('.mu-selected-summary'));
          for(const read of pending)read.resolve(isField(read.url)?field():{tests:[swap()]});await settle();
          assert(!host.textContent.includes('Bolt'));assert(!host.textContent.includes('64'));assert.equal(writes,0);
        """)

    def test_field_completion_keeps_an_independent_swap_link_and_its_focus(self):
        self.run_js(r"""
          const pendingField=held();api=url=>isField(url)?pendingField.promise:Promise.resolve({tests:[swap()]});
          const host=mount();muRefreshSelectedSummary(view);await settle();
          const findSwap=()=>host.querySelectorAll('a').find(node=>(node.getAttribute('href')||'').includes('newest-test'));
          const link=findSwap();assert(link);link.focus();assert.equal(document.activeElement,link);
          pendingField.resolve(field());await settle();assert(host.textContent.includes('64'));
          assert.equal(findSwap(),link);assert.equal(document.activeElement,link);assert.equal(writes,0);
        """)


    def test_foreground_swap_expiry_refreshes_only_history_and_retains_it_while_loading(self):
        self.run_js(r"""
          let clock=1000000;Date.now=()=>clock;const calls=[];
          api=async url=>{calls.push(url);return isField(url)?field():{tests:[swap()]};};
          const host=mount();await muRefreshSelectedSummary(view);await settle();
          assert.equal(calls.filter(isField).length,1);assert.equal(calls.filter(isSwap).length,1);
          clock+=MU_SELECTED_SWAP_TTL_MS-1;await muRefreshSelectedSummary(view);await settle();
          assert.equal(calls.length,2);assert(host.textContent.includes('Bolt'));
          const next=held();api=url=>{calls.push(url);return isField(url)?Promise.resolve(field()):next.promise;};
          clock++;const refreshed=muRefreshSelectedSummary(view);await settle();
          assert.equal(calls.filter(isField).length,1);assert.equal(calls.filter(isSwap).length,2);
          assert(host.textContent.includes('Bolt'));muRefreshSelectedSummary(view);await settle();assert.equal(calls.length,3);
          next.resolve({tests:[swap({test:'updated-test',changes:{remove:[[1,'Elf']],add:[[1,'Second Spell']]}})]});
          await refreshed;await settle();assert(host.textContent.includes('Second Spell'));assert(!host.textContent.includes('Bolt'));
          assert(host.querySelectorAll('a').some(node=>(node.getAttribute('href')||'').includes('updated-test')));
          clock+=MU_SELECTED_SWAP_TTL_MS-1;await muRefreshSelectedSummary(view);await settle();
          assert.equal(calls.length,3);assert.equal(writes,0);
        """)

    def test_cached_queued_field_is_saved_evidence_without_a_live_progress_claim(self):
        self.run_js(r"""
          let status='queued';const calls=[];
          api=async url=>{calls.push(url);return isField(url)?field('casual/a','target',{status}):{tests:[]};};
          data.running=[{key:'field-job',kind:'field',status:'queued',done:0,total:400}];
          let host=mount();await muRefreshSelectedSummary(view);await settle();
          assert(host.textContent.includes('64'));assert(!host.textContent.includes('A field run is in progress'));
          // A run can stop without saving a game; the field cache then legitimately has the same evidence.
          status='done';data.running=[];host=mount();await muRefreshSelectedSummary(view);await settle();
          assert.equal(calls.filter(isField).length,1);assert(host.textContent.includes('64'));
          assert(!host.textContent.includes('A field run is in progress'));
        """)

    def test_malformed_field_opponents_are_not_cached_and_retry_can_recover(self):
        self.run_js(r"""
          for(const opponents of [undefined,null,{},[null],[false],['opponent'],[[]]]){
            view=makeView();let fail=true,fieldReads=0;
            api=async url=>{if(!isField(url))return {tests:[]};fieldReads++;
              return fail?field('casual/a','target',{opponents}):field();};
            const host=mount();await muRefreshSelectedSummary(view);await settle();
            const panel=view.selectedCache.get(view.selectedSummary.key).panels.field;
            assert.equal(panel.answer,null);assert(panel.error);assert(host.textContent.includes('field opponents'));
            fail=false;button(host).click();await settle();
            assert.equal(fieldReads,2);assert(panel.answer);assert.equal(panel.error,null);
            assert(host.textContent.includes('64'));assert.equal(writes,0);
          }
        """)
