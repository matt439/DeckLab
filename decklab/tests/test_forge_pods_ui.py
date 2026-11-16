"""Four-player Forge pods through the actual page functions and isolated Node DOM.

All choices, plans and results are fixtures. No server, private records, network,
database or Forge process is used.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = r"""
  clear(main); editor=null;
  state.profile={id:'matt',name:'Matt'}; state.profiles=[state.profile]; state.may=null;
  location.hash='#/forge-pods';
  history.replaceState=(saved,title,hash)=>{location.hash=hash;};
  const calls=[],writes=[];let readAnswer=null,writeAnswers=[];
  api=async(path,options)=>{calls.push({path,options});
    if(readAnswer instanceof Error)throw readAnswer;
    return typeof readAnswer==='function'?readAnswer(path,options):structuredClone(readAnswer);};
  apiWrite=async(path,body)=>{writes.push({path,body});const answer=writeAnswers.length>1?writeAnswers.shift():writeAnswers[0];
    if(answer instanceof Error)throw answer;return typeof answer==='function'?answer(path,body):structuredClone(answer);};
  toast=()=>{}; syncRunsPill=()=>{};
  const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
  const poll=async()=>{flushTimers();await settle();flushTimers();await settle();};
  const key='a'.repeat(64),otherKey='b'.repeat(64);
  const choices=['a','b','c','d','e'].map((letter)=>({id:'commander/'+letter,version:'target',
    title:'Deck '+letter.toUpperCase(),target_bracket:2,public:false}));
  const packet=(extra={})=>({choices,results:[],forge:{ready:true,problem:null},
    simulations:{may_start:true,why_not:null},status:'none',key:null,sides:[],job:null,result:null,
    notice:null,error:null,game_choices:[16,32,64,128],default_games:16,...extra});
  const planned=(extra={})=>packet({key,sides:choices.slice(0,4),plan:{key,games:16},...extra});
  const button=(text)=>main.querySelectorAll('button').find((node)=>node.textContent===text);
  const blocked=(node)=>!node||node.disabled||node.getAttribute('aria-disabled')==='true';
  const choose=(seat,index)=>{const select=main.querySelectorAll('.fp-deck')[seat];
    const option=select.querySelectorAll('option').find((node)=>node.textContent.includes(choices[index].title));
    assert(option,'available deck choice');select.value=option.getAttribute('value');select.fire('change');};
  const chooseFour=()=>{for(let seat=0;seat<4;seat++)choose(seat,seat);};
  const draw=async(extra={})=>{readAnswer=packet(extra);await showForgePods(new URLSearchParams(),routeToken);await settle();};
  const summary={pods:13,counted:10,wins:8,draws:2,clock_stops:3,failed_batches:1,
    by_deck:Object.fromEntries(choices.slice(0,4).map((deck,i)=>[deck.id,{wins:[4,2,1,1][i],pods:10,
      rate:[.4,.2,.1,.1][i],range:[[.17,.69],[.06,.51],[.02,.4],[.02,.4]][i]}]))};
  const result={key,sides:choices.slice(0,4),games:16,planned:16,completed:13,remaining:3,
    summary,statistical_only:true,note:'Statistics only: four-player games do not replay exactly.'};
"""


@unittest.skipUnless(NODE, "Node.js is not installed")
class ForgePodsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_choosing_and_checking_never_starts_games_before_explicit_start(self):
        self.run_js(r"""
          await draw();assert.equal(main.querySelectorAll('.fp-deck').length,4,main.textContent);
          assert(main.textContent.includes('target bracket 2'));
          chooseFour();assert.equal(writes.length,0);
          writeAnswers=[planned(),planned({status:'queued',job:{status:'queued',done:0,total:16,may_stop:true}})];
          button('Check this pod').click();await settle();
          assert.equal(writes.length,1);assert.equal(writes[0].path,'/api/forge/pods/plan');
          same(writes[0].body,{decks:choices.slice(0,4).map(({id,version})=>({id,version})),games:16});
          const start=button('Start');assert(!blocked(start));start.click();start.click();await settle();
          assert.equal(writes.length,2);assert.equal(writes[1].path,'/api/forge/pods/run');
          same(writes[1].body,{decks:choices.slice(0,4).map(({id,version})=>({id,version})),games:16,expected_key:key});
          assert(main.querySelector('.fp-live'));
        """)

    def test_changing_a_checked_pod_requires_another_check_before_start(self):
        self.run_js(r"""
          await draw();chooseFour();writeAnswers=[planned()];
          button('Check this pod').click();await settle();assert(!blocked(button('Start')));
          choose(3,4);assert(blocked(button('Start')));
          if(button('Start'))button('Start').click();await settle();
          assert.equal(writes.length,1,'an obsolete plan cannot start new choices');
        """)

    def test_simulation_refusal_explains_start_without_any_run_write(self):
        self.run_js(r"""
          const simulations={may_start:false,why_not:'Simulations are paused. Ask an admin to enable them.'};
          await draw({simulations});chooseFour();writeAnswers=[planned({simulations})];
          const check=button('Check this pod');if(check&&!blocked(check)){check.click();await settle();}
          assert(main.textContent.includes(simulations.why_not));
          const start=button('Start');assert(blocked(start));
          if(start){assert.equal(start.getAttribute('aria-describedby'),'fp-start-reason');
            assert(main.querySelector('#fp-start-reason').textContent.includes(simulations.why_not));start.click();}
          await settle();
          assert(!writes.some(({path})=>path.endsWith('/run')));
        """)

    def test_results_name_each_deck_range_draws_and_statistics_only_caveat(self):
        self.run_js(r"""
          clear(main);main.append(fpResultPart(packet({key,result,sides:result.sides,status:'done'})));
          for(const deck of result.sides)assert(main.textContent.includes(deck.title));
          assert(main.textContent.includes('40%'));assert(main.textContent.includes('17–69%'));
          assert(main.textContent.includes('95%'));
          assert(main.textContent.includes('25%'));
          assert(main.textContent.includes('10 counted pod games'));
          assert(main.textContent.includes('4 wins in 10 counted pods'));
          assert(/draw/i.test(main.textContent));assert(/clock/i.test(main.textContent));assert(/failed/i.test(main.textContent));
          assert(/statistics only/i.test(main.textContent));assert(/do not replay exactly|don't replay exactly/i.test(main.textContent));
          assert.equal(writes.length,0);assert.equal(calls.length,0);
        """)

    def test_stop_requires_confirmation_and_keeps_finished_result(self):
        self.run_js(r"""
          await draw({key,sides:result.sides,result,status:'running',
            job:{key,status:'running',done:3,total:16,may_stop:true}});
          assert(main.querySelector('.fp-live').textContent.includes('3'));
          let asked=0;ask=async()=>{asked++;return 'keep';};
          button('Stop').click();await settle();assert.equal(asked,1);assert.equal(writes.length,0);
          ask=async()=>{asked++;return 'stop';};writeAnswers=[packet({key,result,sides:result.sides,status:'done',notice:'Stopped.'})];
          button('Stop').click();await settle();assert.equal(asked,2);
          assert.equal(writes.length,1);same(writes[0],{path:'/api/forge/pods/stop',body:{key}});
          assert(main.textContent.includes('Deck A'));assert(main.textContent.includes('40%'));
        """)

    def test_late_initial_read_cannot_replace_another_profiles_page(self):
        self.run_js(r"""
          let release;readAnswer=()=>new Promise(resolve=>{release=resolve;});
          const waiting=showForgePods(new URLSearchParams(),routeToken);await settle();
          state.profile={id:'user2',name:'User2'};
          clear(main).append(el('p',{text:'The other profile is here'}));
          release(packet({result,sides:result.sides,key,status:'done'}));await waiting;await settle();
          assert.equal(main.textContent,'The other profile is here');assert.equal(writes.length,0);
        """)

    def test_late_checked_plan_cannot_write_or_reveal_after_profile_switch(self):
        self.run_js(r"""
          await draw();chooseFour();let release;
          writeAnswers=[()=>new Promise(resolve=>{release=resolve;})];
          button('Check this pod').click();await settle();assert.equal(writes.length,1);
          state.profile={id:'user2',name:'User2'};routeToken++;
          clear(main).append(el('p',{text:'New profile'}));
          release(planned());await settle();assert.equal(main.textContent,'New profile');
          assert.equal(writes.length,1);
        """)

    def test_unknown_or_distant_brackets_and_duplicate_deck_versions_cannot_be_checked(self):
        self.run_js(r"""
          await draw({choices:choices.map((deck,index)=>({...deck,target_bracket:index===3?null:2}))});
          chooseFour();assert(blocked(button('Check this pod')));
          assert(main.textContent.includes('Set a target bracket'));
          await draw({choices:choices.map((deck,index)=>({...deck,target_bracket:index===3?4:2}))});
          chooseFour();assert(blocked(button('Check this pod')));
          assert(main.textContent.includes('at most one apart'));
          await draw({choices:[...choices,{...choices[0],version:'owned'}]});chooseFour();
          const fourth=main.querySelectorAll('.fp-deck')[3];
          fourth.value=fourth.querySelectorAll('option').find(node=>node.textContent.includes('play-now list')).getAttribute('value');
          fourth.fire('change');assert(blocked(button('Check this pod')));
          assert(main.textContent.includes('four different decks'));assert.equal(writes.length,0);
        """)

    def test_fresh_choices_invalidate_review_and_remove_a_deck_no_longer_visible(self):
        self.run_js(r"""
          await draw();chooseFour();writeAnswers=[planned()];
          button('Check this pod').click();await settle();assert(!blocked(button('Start')));
          readAnswer=packet({choices:choices.filter(deck=>deck.id!=='commander/d')});await poll();
          assert(blocked(button('Start')));assert(blocked(button('Check this pod')));
          assert.equal(main.querySelectorAll('.fp-deck')[3].value,'');
          assert(!main.querySelector('.fp-chooser').textContent.includes('Deck D'));
          assert.equal(writes.length,1);
        """)

    def test_polling_privacy_refusal_removes_previously_visible_pod_contents(self):
        self.run_js(r"""
          await draw({key,sides:result.sides,result,status:'running',
            job:{key,status:'running',done:3,total:16,may_stop:true}});
          assert(main.textContent.includes('Deck A'));
          readAnswer=new ApiError(404,'No pod is available at this address.');await poll();
          assert(!main.textContent.includes('Deck A'));assert(!main.textContent.includes('40%'));
          assert(!main.querySelector('.fp-chooser'));assert.equal(writes.length,0);
        """)

    def test_uncertain_start_preserves_choices_and_requires_explicit_refresh_before_retry(self):
        self.run_js(r"""
          await draw();chooseFour();writeAnswers=[planned(),new Error('The connection ended.')];
          button('Check this pod').click();await settle();button('Start').click();await settle();
          assert.equal(writes.length,2);assert(blocked(button('Start')));assert(blocked(button('Check this pod')));
          assert(main.textContent.includes('did not confirm whether the run started'));
          const selected=main.querySelectorAll('.fp-deck').map(node=>node.value);
          assert(selected.every(Boolean));button('Start').click();await settle();assert.equal(writes.length,2);
          const readsBefore=calls.length;
          readAnswer=path=>{if(path==='/api/forge/pods?key='+key)throw new ApiError(404,'No saved pod run.');return packet();};
          button('Refresh').click();await settle();
          same(calls.slice(readsBefore).map(({path})=>path),['/api/forge/pods?key='+key,'/api/forge/pods']);
          assert.equal(JSON.stringify(main.querySelectorAll('.fp-deck').map(node=>node.value)),JSON.stringify(selected));
          assert(!blocked(button('Check this pod')));assert(blocked(button('Start')));
          assert.equal(writes.length,2);
        """)

    def test_saved_run_bookmark_reads_its_key_and_history_links_saved_statistics(self):
        self.run_js(r"""
          readAnswer=packet({key,result,sides:result.sides,status:'done',results:[{...result,key:otherKey}]});
          location.hash='#/forge-pods?key='+key;
          await showForgePods(new URLSearchParams('key='+key),routeToken);await settle();
          assert(calls[0].path.includes('key='+key));assert(main.textContent.includes('40%'));
          const link=main.querySelector('.fp-history').querySelector('a');
          assert.equal(link.getAttribute('href'),'#/forge-pods?key='+otherKey);
          for(const deck of result.sides)assert(link.textContent.includes(deck.title));
          assert.equal(writes.length,0);
        """)

    def test_saved_larger_sample_initializes_its_size_and_resumes_only_remaining_games(self):
        self.run_js(r"""
          readAnswer=packet({key,sides:result.sides,status:'done',
            result:{...result,games:32,planned:32,completed:9,remaining:23}});
          location.hash='#/forge-pods?key='+key;
          await showForgePods(new URLSearchParams('key='+key),routeToken);await settle();
          assert.equal(main.querySelector('.fp-games').value,'32');
          writeAnswers=[planned({plan:{key,games:32,completed:9,remaining:23}}),
            planned({status:'queued',job:{status:'queued',done:9,total:32,may_stop:true}})];
          button('Check this pod').click();await settle();
          assert.equal(writes[0].body.games,32);
          assert(main.querySelector('.fp-plan').textContent.includes('9 of 32 planned pod games are already saved'));
          assert(main.querySelector('.fp-plan').textContent.includes('resumes the 23 remaining games'));
          button('Start').click();await settle();assert.equal(writes.length,2);
          assert.equal(writes[1].path,'/api/forge/pods/run');
          assert.equal(writes[1].body.games,32);assert.equal(writes[1].body.expected_key,key);
          assert(main.querySelector('.fp-live').textContent.includes('9 of 32'));
        """)

    def test_complete_checked_sample_has_no_start_write(self):
        self.run_js(r"""
          await draw();chooseFour();writeAnswers=[planned({plan:{key,games:16,completed:16,remaining:0}})];
          button('Check this pod').click();await settle();
          assert(main.querySelector('.fp-plan').textContent.includes('All 16 planned pod games are already saved'));
          assert(blocked(button('Start')));button('Start').click();await settle();
          assert.equal(writes.length,1);assert(!writes.some(({path})=>path.endsWith('/run')));
          assert(main.querySelector('#fp-start-reason').textContent.includes('all its planned games'));
        """)

    def test_saved_partial_and_stopped_results_keep_actual_completion_and_draw_denominator(self):
        self.run_js(r"""
          for(const state of ['stopped','failed','error']){
            clear(main);main.append(fpResultPart(packet({key,result:{...result,state},sides:result.sides,status:'done'})));
            assert(main.textContent.includes('13 of 16 planned pod games completed; 3 remain'));
            assert(main.textContent.includes('Completed games are kept'));
            assert(main.textContent.includes('10 counted pod games'));assert(main.textContent.includes('2 draws recorded'));
            assert(main.textContent.includes('4 wins in 10 counted pods'));assert(main.textContent.includes('3 clock stops excluded'));
            assert(!main.textContent.includes('16 counted pod games'));
          }
          assert.equal(calls.length,0);assert.equal(writes.length,0);
        """)

    def test_landing_lists_visible_pods_running_now_with_exact_run_links_and_progress(self):
        self.run_js(r"""
          await draw({running:[{key:'pods:'+key,status:'running',title:'The visible pod',done:9,total:32},
            {key:'pods:'+otherKey,status:'running',hidden:true,title:'Hidden pod must stay hidden',done:1,total:16},
            {key:'pods:missing',status:'running',title:'Invalid key must not link',done:2,total:16}]});
          const link=main.querySelector('.fp-live').querySelector('a');assert(link);
          assert.equal(link.getAttribute('href'),'#/forge-pods?key='+key);
          assert(link.textContent.includes('The visible pod'));assert(link.textContent.includes('9 of 32 pod games completed'));
          assert(!main.textContent.includes('Hidden pod must stay hidden'));
          assert(!main.textContent.includes('Invalid key must not link'));assert.equal(writes.length,0);
        """)

    def test_unconfirmed_start_refresh_finds_exact_run_without_repeating_start(self):
        self.run_js(r"""
          await draw();chooseFour();writeAnswers=[planned(),new Error('Start response was lost.')];
          button('Check this pod').click();await settle();button('Start').click();await settle();
          const before=calls.length;readAnswer=packet({key,sides:result.sides,status:'running',
            job:{key,status:'running',done:5,total:16,may_stop:true}});
          button('Refresh').click();await settle();
          same(calls.slice(before).map(({path})=>path),['/api/forge/pods?key='+key]);
          assert.equal(location.hash,'#/forge-pods?key='+key);
          assert(main.querySelector('.fp-live').textContent.includes('5 of 16'));
          assert(blocked(button('Start')));assert.equal(writes.length,2);
          assert.equal(writes.filter(({path})=>path.endsWith('/run')).length,1);
        """)
