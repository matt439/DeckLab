"""The Testing page's Popular decks view (E3-S35, gauntlet-board.js) through the real page scripts, with isolated
DOM and API fixtures: the default view, the address, the rows, Details, each row's Play and late answers."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class GauntletBoardUiTests(unittest.TestCase):
    def run_js(self, scenario):
        setup = """
          clear(main);editor=null;state.profile={id:'matt',name:'Matt'};state.may=null;
          const storage=new Map();window.localStorage={getItem:k=>storage.get(k)??null,
            setItem:(k,v)=>storage.set(k,String(v)),removeItem:k=>storage.delete(k)};
          const replaced=[];history.replaceState=(s,t,url)=>replaced.push(url);
          const library={halves:[],decks:[
            {id:'commander/c',title:'Commander C',kind:'commander',versions:['target']},
            {id:'commander/d',title:'Commander D',kind:'commander',versions:['target']}]};
          const data={running:[],results:[]};
          const deck=(id,title,sha=id)=>({id,title,kind:'commander',version:'target',card_sha:sha});
          const row=(id,title,extra={})=>({deck:deck(id,title),state:'untested',problem:null,overall:null,played:0,
            of:20,games:0,updated:null,hardest:null,before:null,older:null,playing:null,...extra});
          const tested=(id,title,rate,extra={})=>row(id,title,{state:'done',overall:{rate,low:rate-.08,high:rate+.08},
            played:20,games:2000,updated:new Date().toISOString(),hardest:{title:'Atraxa (core)',tier:'core',style:'combo',
            rate:.22,low:.15,high:.3,verdict:'weak',source:'edhrec'},...extra});
          const board=(format='commander',rows=[],extra={})=>({format,state:'ok',build_command:null,
            sample:{id:'sample:abcdefabcdef',size:20,tiers:['core']},default_budget:'fixed:100',note:null,notes:[],rows,...extra});
          const button=(scope,text)=>scope.querySelectorAll('button').find(b=>b.textContent===text);
          const settle=async()=>{for(let i=0;i<10;i++)await Promise.resolve();};
          const writes=[];apiWrite=async(path,body)=>{writes.push([path,body]);return {};};
          const toasts=[];toast=m=>toasts.push(m);syncRunsPill=()=>{};
          runGate=()=>({may:true,why:null});
          const open=(params='')=>{location.hash='#/matchups'+(params?'?'+params:'');
            drawMatchups(library,data,new URLSearchParams(params),routeToken);};
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_the_page_opens_on_popular_decks_and_the_address_wins_over_storage(self):
        self.run_js("""
          assert.equal(gbInitialView(new URLSearchParams()),'popular');
          storage.set('decklab.testing.view','rankings');
          assert.equal(gbInitialView(new URLSearchParams()),'rankings');
          assert.equal(gbInitialView(new URLSearchParams('view=matchups')),'matchups');
          assert.equal(gbInitialView(new URLSearchParams('view=nope')),'rankings');
          // The old key isn't read: everyone opens on Popular decks once.
          storage.clear();storage.set('decklab.matchups.view','rankings');
          assert.equal(gbInitialView(new URLSearchParams()),'popular');
          const calls=[];api=async url=>{calls.push(url);return board('commander',[]);};
          open();await settle();
          assert.equal(main.querySelector('h1').textContent,'Testing');
          const views=main.querySelector('.mu-view').querySelectorAll('button').map(b=>b.textContent);
          same(views,['Popular decks','Matchups','Rankings']);
          assert.equal(button(main,'Popular decks').getAttribute('aria-pressed'),'true');
          same(calls,['/api/gauntlet/board?format=commander']);
          const formats=main.querySelector('.gb-format').querySelectorAll('button').map(b=>b.textContent);
          same(formats,['Commander','60-card']);
          assert(main.textContent.includes('No Commander decks to test yet.'));
          assert(!main.querySelector('.mu-opponents'));assert(!main.querySelector('.mu-rankings'));
        """)

    def test_a_view_change_rewrites_the_address_without_the_play_sheet_and_cancels_the_board(self):
        self.run_js("""
          const pending=[];api=(url,opts)=>new Promise(resolve=>pending.push({url,resolve,signal:opts&&opts.signal}));
          runGate=()=>({may:false,why:'Simulations are paused.'});
          open('view=popular&a=commander/c&av=target');
          assert.equal(pending.length,1);assert(pending[0].url.startsWith('/api/gauntlet/board'));
          button(main,'Matchups').click();
          same(replaced,['#/matchups?view=matchups']);assert.equal(storage.get('decklab.testing.view'),'matchups');
          assert(pending[0].signal.aborted);
          pending[0].resolve(board('commander',[tested('commander/c','Late answer',.5)]));await settle();
          assert(!main.textContent.includes('Late answer'));assert(!main.textContent.includes('cancelled'));
          button(main,'Popular decks').click();
          same(replaced,['#/matchups?view=matchups','#/matchups?view=popular']);
          assert.equal(pending.length,2);
        """)

    def test_pairing_leads_only_on_matchups_and_historical_evidence_keeps_its_scope(self):
        self.run_js("""
          api=async()=>board('commander',[
            tested('commander/c','Current',.61),
            row('commander/s','Changed',{state:'stale_list',before:{rate:.41,low:.33,high:.49,updated:'2026-11-01T00:00:00Z'}}),
            row('commander/o','Older',{state:'stale_older',older:{reason:'forge',overall:{rate:.45,low:.4,high:.5},
              updated:'2026-10-30T00:00:00Z',earlier:false,opponents:20,of:20}})]);
          open();await settle();
          const pairing=button(main,'Play a matchup');
          assert(pairing.classList.contains('btn-quiet'));assert(!pairing.classList.contains('btn-primary'));
          assert(main.querySelector('.gb-scope').textContent.includes('Commander · 1v1 · 20 sampled opponents'));
          assert.equal(main.querySelector('.gb-help').querySelector('summary').textContent,'About these results');
          const rows=main.querySelectorAll('.gb-row');
          assert(rows[0].querySelector('.gb-score').querySelector('.wr'));
          assert(rows[1].querySelector('.gb-score-historical').textContent.includes('Before: 41%'));
          assert(rows[2].querySelector('.gb-score-historical').textContent.includes('older Forge'));
          assert(!rows[1].querySelector('.wr'));assert(!rows[2].querySelector('.wr'));
          button(main,'Matchups').click();
          assert(pairing.classList.contains('btn-primary'));assert(!pairing.classList.contains('btn-quiet'));
          button(main,'Rankings').click();
          assert(!pairing.classList.contains('btn-primary'));assert(pairing.classList.contains('btn-quiet'));
          assert.equal(writes.length,0);
        """)

    def test_rows_show_the_standing_details_and_play_and_never_play_all(self):
        self.run_js("""
          const rows=[tested('commander/c','Commander C',.61),
            row('commander/p','Partial',{state:'partial',overall:{rate:.5,low:.3,high:.7},played:3,games:300,
              updated:new Date().toISOString()}),
            row('commander/s','Changed',{state:'stale_list',before:{rate:.41,low:.33,high:.49,updated:'2026-11-01T00:00:00Z'}}),
            row('commander/o','Older',{state:'stale_older',older:{reason:'forge',overall:{rate:.45,low:.4,high:.5},
              updated:'2026-10-30T00:00:00Z',earlier:false,opponents:20,of:20}}),
            row('commander/u','Untested'),
            row('commander/x','Broken',{state:'unreadable',problem:"Forge can't read this list.",deck:{...deck('commander/x','Broken'),card_sha:null}})];
          api=async()=>board('commander',rows,{notes:["Some lists' earlier results are still being looked at."]});
          open();await settle();
          const items=main.querySelectorAll('.gb-row');
          same(items.map(n=>n.dataset.deck),['commander/c','commander/p','commander/s','commander/o','commander/u','commander/x']);
          const first=items[0];
          assert(first.querySelector('.wr'));assert(first.querySelector('.range-bar'));assert(first.querySelector('.fresh'));
          assert(first.textContent.includes('61%'));
          assert(first.textContent.includes('20 of 20 opponents'));assert(first.textContent.includes('2,000 games'));
          assert(first.textContent.includes('Hardest: Atraxa (core) 22%'));
          const details=first.querySelectorAll('a').find(a=>a.textContent==='Details');
          assert.equal(details.getAttribute('href'),'#/deck?id=commander%2Fc&v=target&tab=matchups&part=gauntlet');
          assert(button(first,'Play'));
          assert(items[1].textContent.includes('Partly tested'));assert(items[1].textContent.includes('3 of 20 opponents'));
          assert(items[2].textContent.includes('The list changed since its last test'));
          assert(items[3].textContent.includes('older Forge'));
          assert(items[4].textContent.includes('Not tested against popular decks yet.'));assert(button(items[4],'Play'));
          assert(items[5].textContent.includes("Forge can't read this list."));assert(!button(items[5],'Play'));
          assert(main.textContent.includes('not a rating. Rankings are separate.'));
          assert(main.textContent.includes('the same 20 popular Commander decks'));
          assert(main.textContent.includes("Some lists' earlier results are still being looked at."));
          assert(!/play all/i.test(main.textContent));
          assert(!main.textContent.includes('null'));assert(!main.textContent.includes('undefined'));
          assert.equal(writes.length,0);
        """)

    def test_play_asks_then_sends_the_list_on_screen_and_shows_the_servers_refusal(self):
        self.run_js("""
          const calls=[];api=async url=>{calls.push(url);return board('commander',[tested('commander/c','Commander C',.6)]);};
          const asked=[];ask=async(title,paragraphs,choices)=>{asked.push([title,paragraphs,choices.map(c=>c.text)]);return 'play';};
          open();await settle();
          button(main.querySelector('.gb-row'),'Play').click();await settle();
          assert.equal(asked[0][0],'Play Commander C against popular decks?');
          assert(asked[0][1][0].includes('20 popular decks, about 100 games each'));
          assert(asked[0][1][0].includes("The deck's Testing tab says how long."));
          same(asked[0][2],['Play','Cancel']);
          same(writes,[['/api/gauntlet/run',{id:'commander/c',version:'target',expected_card_sha:'commander/c'}]]);
          assert.equal(calls.length,2);
          apiWrite=async()=>{const e=new Error('4 popular-deck runs are already waiting. Try again when one has finished.');e.status=503;throw e;};
          button(main.querySelector('.gb-row'),'Play').click();await settle();
          same(toasts,['4 popular-deck runs are already waiting. Try again when one has finished.']);
          assert.equal(calls.length,3);
          // Cancel writes nothing.
          ask=async()=>'cancel';const before=writes.length;
          button(main.querySelector('.gb-row'),'Play').click();await settle();assert.equal(writes.length,before);
        """)

    def test_no_play_when_the_gate_refuses_or_a_run_already_waits_or_plays(self):
        self.run_js("""
          runGate=()=>({may:false,why:'Only an admin can start Forge runs.'});
          api=async()=>board('commander',[tested('commander/c','Commander C',.6)]);
          open();await settle();
          assert(!button(main.querySelector('.gb-row'),'Play'));
          assert(main.textContent.includes('Only an admin can start Forge runs.'));
          runGate=()=>({may:true,why:null});
          const host=el('div');main.append(host);const view={mode:'popular',token:routeToken,profile:'matt'};
          const playing=gbRow(view,tested('commander/c','C',.6,{playing:{status:'running',done:40,total:2000,standard:true}}));
          assert(playing.textContent.includes('Playing: 40 of 2,000 games'));assert(!button(playing,'Play'));
          const waiting=gbRow(view,row('commander/c','C',{playing:{status:'queued',done:0,total:2000,standard:true}}));
          assert(waiting.textContent.includes('Waiting to play'));assert(!button(waiting,'Play'));
          const other=gbRow(view,row('commander/c','C',{playing:{status:'running',done:1,total:9,standard:false}}));
          assert(other.textContent.includes('Playing another sample'));assert(!button(other,'Play'));
          assert(!other.textContent.includes('started by'));
        """)

    def test_format_switch_reads_that_format_and_late_answers_after_a_profile_change_are_dropped(self):
        self.run_js("""
          const pending=[];api=(url,opts)=>new Promise(resolve=>pending.push({url,resolve}));
          open();
          pending[0].resolve(board('commander',[tested('commander/c','Commander C',.6)]));await settle();
          button(main,'60-card').click();
          assert.equal(pending[1].url,'/api/gauntlet/board?format=constructed');
          assert.equal(storage.get('decklab.testing.popularFormat'),'constructed');
          assert.equal(button(main,'60-card').getAttribute('aria-pressed'),'true');
          state.profile={id:'user1',name:'User1'};
          pending[1].resolve(board('constructed',[tested('casual/a','Someone else',.7)]));await settle();
          assert(!main.textContent.includes('Someone else'));
        """)

    def test_a_failed_read_says_why_with_try_again_and_no_catalogue_shows_the_admins_command(self):
        self.run_js("""
          let fail=true;api=async()=>{if(fail){const e=new Error('The PC is busy.');e.status=500;throw e;}
            return board('commander',[],{state:'no_catalogue',sample:null,build_command:'python -m decklab.lib.forge gauntlet build'});};
          open();await settle();
          assert(main.textContent.includes("Popular decks couldn't be loaded. The PC is busy."));
          fail=false;button(main,'Try again').click();await settle();
          assert(main.textContent.includes("Popular decks aren't set up on this PC yet."));
          assert.equal(main.querySelector('.gb-command').textContent,'python -m decklab.lib.forge gauntlet build');
        """)

    def test_older_counts_and_row_notes_show(self):
        self.run_js("""
          api=async()=>board('commander',[
            row('commander/o','Older',{state:'stale_older',older:{reason:'forge',opponents:12,of:20,
              overall:{rate:.41,low:.33,high:.49},updated:'2026-11-02T00:00:00Z',earlier:false}}),
            row('commander/k','Rebuilt',{state:'stale_older',older:{reason:'catalogue',opponents:12,of:20,overall:null,
              updated:null,earlier:false}}),
            row('commander/u','Unread',{notes:["The list's earlier versions can't be read now."]})]);
          open();await settle();
          const items=main.querySelectorAll('.gb-row');
          assert(items[0].textContent.includes('12 of 20 opponents'),items[0].textContent);
          assert(items[1].textContent.includes("12 opponents' lists changed"));
          assert(items[2].textContent.includes("The list's earlier versions can't be read now."));
          assert(items[2].textContent.includes('Not tested against popular decks yet.'));
        """)

    def test_a_redraw_keeps_the_focus_on_the_same_rows_control(self):
        self.run_js("""
          let playing=null;const calls=[];
          api=async url=>{calls.push(url);return board('commander',[tested('commander/c','Commander C',.6,{playing}),
            tested('commander/d','Commander D',.5)]);};
          open();await settle();
          const view={mode:'popular',token:routeToken,profile:'matt',gbEntries:new Map(),gbFormat:'commander',
            gbHost:main.querySelector('.gb')};
          view.gbEntries.set('commander',{answer:board('commander',[tested('commander/c','Commander C',.6),
            tested('commander/d','Commander D',.5)]),error:null,asked:1});
          gbDrawEntry(view,view.gbEntries.get('commander'));
          const second=main.querySelectorAll('.gb-row')[1];
          const details=second.querySelectorAll('a').find(a=>a.textContent==='Details');details.focus();
          const pending=[];api=(url)=>new Promise(resolve=>pending.push(resolve));
          gbRefresh(view,null,{force:true});
          assert.equal(main.querySelectorAll('.gb-row')[1],second);     // a read starting doesn't redraw
          pending[0](board('commander',[tested('commander/c','Commander C',.6),tested('commander/d','Commander D',.5)]));
          await settle();
          assert.notEqual(main.querySelectorAll('.gb-row')[1],second);
          assert.equal(document.activeElement.dataset.focus,'details:commander/d');
          assert(main.contains(document.activeElement));
          // Play focused, then the row plays: the focus goes to its Details.
          button(main.querySelectorAll('.gb-row')[0],'Play').focus();
          api=async()=>board('commander',[tested('commander/c','Commander C',.6,
            {playing:{status:'queued',done:0,total:2000,standard:true}}),tested('commander/d','Commander D',.5)]);
          gbRefresh(view,null,{force:true});await settle();
          assert.equal(document.activeElement.dataset.focus,'details:commander/c');
          assert(main.contains(document.activeElement));
          clearTimeout(view.gbTimer);
        """)

    def test_a_run_starting_or_ending_reads_the_board_again(self):
        self.run_js("""
          const calls=[];api=async url=>{calls.push(url);return board('commander',[tested('commander/c','Commander C',.6)]);};
          open();await settle();assert.equal(calls.length,1);
          const view={mode:'popular',token:routeToken,profile:'matt',gbEntries:new Map(),gbFormat:'commander',
            gbHost:main.querySelector('.gb')};
          gbRefresh(view,{running:[]});await settle();assert.equal(calls.length,2);
          gbRefresh(view,{running:[]});await settle();assert.equal(calls.length,2);
          gbRefresh(view,{running:[{id:'j1',status:'queued'}]});await settle();assert.equal(calls.length,3);
          gbRefresh(view,{running:[{id:'j1',status:'queued'}]});await settle();assert.equal(calls.length,3);
        """)


if __name__ == "__main__":
    unittest.main()
