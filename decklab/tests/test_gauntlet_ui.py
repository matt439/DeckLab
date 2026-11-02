"""The deck page's "Against popular decks" part (web/gauntlet.js) through its real renderers over an isolated
Node DOM: the missing catalogue's command, the empty state's Play, the choices, the groups and opponents, and a
run's poll and Stop. Every answer is a fixture; no live server, network, configuration, database or simulation
is used.

Run with python scripts/test_fixtures.py decklab.tests.test_gauntlet_ui.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = PAGE + """
  clear(main);editor=null;state.profile={id:'matt',name:'Matt'};state.may=null;
  const calls=[],writes=[];let answers=[];
  api=async path=>{calls.push(path);const next=answers.length>1?answers.shift():answers[0];
    if(next instanceof Error)throw next;return structuredClone(next);};
  apiWrite=async(path,body)=>{writes.push({path,body});return structuredClone(answers[0]);};
  toast=()=>{};
  const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
  const sha='a'.repeat(64);
  const base=(extra={})=>({deck:{id:'casual/test',version:'target',title:'Test Deck',card_sha:sha},format:'constructed',
    build_command:'python -m decklab.lib.forge gauntlet build --format constructed',credit:'Average decks from EDHREC.',
    options:{sizes:[12,24,36],colours:'WUBRG',styles:['aggro','midrange','control','combo','ramp'],
      tiers:['precon','easy','medium','hard','very hard'],budgets:['fixed:50','fixed:100','fixed:200']},
    default_budget:'fixed:100',default_size:24,forge:{ready:true},catalogue:{playable:3},
    sample:{id:'sample:0123456789ab',size:24,filters:{colours:null,styles:null,tiers:['hard','medium']},decks:3},
    opponents:[],groups:{},games:0,note:null,notes:[],status:'none',job:null,notice:null,error:null,
    budgets:{'fixed:100':{games:100,new_games:300,minutes:[3,5]}},...extra});
  const rate=(value)=>({value,low:value-.1,high:value+.1});
  const opponent=(id,title,value,source)=>({id,title,tier:'medium',identity:'R',style:'aggro',games:100,rate:rate(value),
    lead:null,not_meaningful:false,problem:null,source});
  const played=()=>base({games:300,note:'Each range covers these 3 sampled opponents only, not every deck of that colour.',
    opponents:[opponent('gauntlet:edhrec/krenko-core','Krenko, Mob Boss',.3,{kind:'edhrec',url:'https://edhrec.com/average-decks/krenko/core',rank:4,decks:12000}),
      opponent('gauntlet:precon/x','Some Precon',.5,{kind:'mtgjson',url:null}),
      opponent('gauntlet:forge/duels/y','Some Duel',.7,{kind:'forge'})],
    groups:{colour:[{key:'R',label:'Red',opponents:3,games:300,rate:.5,low:.4,high:.6,spread:[.3,.7],note:'overlapping'}],
      style:[{key:'aggro',label:'Aggro',opponents:1,games:100,rate:.3,low:.2,high:.4,spread:[.3,.3],note:'one opponent, not a group'}],
      identity_size:[],tier:[]}});
  const draw=async()=>{const node=gauntletSection({summary:{id:'casual/test',title:'Test Deck'},version:'target'});
    main.append(node);await settle();return node;};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class GauntletUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_a_missing_catalogue_shows_the_command_and_no_play(self):
        self.run_js("""
          answers=[base({catalogue:null,sample:null,budgets:{}})];
          const node=await draw();
          assert(node.textContent.includes('There are no popular 60-card decks on the PC yet.'));
          assert.equal(node.querySelector('code').textContent,'python -m decklab.lib.forge gauntlet build --format constructed');
          assert(!buttonText(node,'Play them'));
          assert.equal(calls.length,1);assert(calls[0].startsWith('/api/gauntlet?id=casual%2Ftest&version=target'));
          assert.equal(writes.length,0);
        """)

    def test_the_empty_state_plays_its_choices_with_the_saved_list(self):
        self.run_js("""
          answers=[base()];
          const node=await draw();
          assert(node.textContent.includes('No games against popular decks yet.'));
          assert(node.textContent.includes('About 100 games a deck, about 3–5 minutes.'));
          const play=buttonText(node,'Play them');assert(play&&!play.disabled);
          play.click();await settle();
          assert.equal(writes.length,1);assert.equal(writes[0].path,'/api/gauntlet/run');
          same(writes[0].body,{id:'casual/test',version:'target',budget:'fixed:100',size:24,colours:'',styles:'',
            tiers:'hard,medium',expected_card_sha:sha});
        """)

    def test_choices_draw_the_sample_again_without_playing(self):
        self.run_js("""
          answers=[base()];
          const node=await draw();
          const summary=node.querySelector('.gt-choices').querySelector('summary');
          assert.equal(summary.textContent,'3 opponents · Hard, Medium · any colours · any style');
          buttonText(node,'Control').click();await settle();
          assert(calls.at(-1).includes('styles=control'));assert(calls.at(-1).includes('size=24'));
          buttonText(node,'Red').click();await settle();
          assert(calls.at(-1).includes('colours=R'));
          buttonText(node,'12').click();await settle();
          assert(calls.at(-1).includes('size=12'));
          assert.equal(writes.length,0);
        """)

    def test_results_by_group_with_the_caveat_and_each_opponent_hardest_first(self):
        self.run_js("""
          answers=[played()];
          const node=await draw();
          const groups=node.querySelector('.gt-groups');
          assert(groups.textContent.includes('Red'));assert(groups.textContent.includes('3 opponents · 300 games'));
          assert(groups.textContent.includes('from 30% to 70% by opponent'));
          assert(node.textContent.includes('Each range covers these 3 sampled opponents only'));
          buttonText(node,'Style').click();
          assert(node.querySelector('.gt-groups').textContent.includes('one opponent, not a group'));
          assert.equal(node.querySelector('.gt-groups').querySelector('.gt-muted').querySelector('.gt-name').textContent,'Aggro');
          const names=node.querySelector('.gt-rows').querySelectorAll('.gt-name').map(n=>n.textContent);
          same(names,['Krenko, Mob Boss','Some Precon','Some Duel']);
          const link=node.querySelector('.gt-rows').querySelector('a');
          assert.equal(link.getAttribute('href'),'https://edhrec.com/average-decks/krenko/core');
          assert.equal(link.getAttribute('rel'),'noopener noreferrer');
          assert(node.textContent.includes('Average deck from EDHREC (rank 4, 12,000 decks)'));
          assert(node.textContent.includes('Wizards precon, from MTGJSON'));
          assert(node.textContent.includes('A deck bundled with Forge'));
          assert(node.textContent.includes('Average decks from EDHREC.'));
        """)

    def test_a_run_polls_and_stops_after_asking(self):
        self.run_js("""
          const job={status:'running',done:50,total:200,by:'someone',may_stop:true,ahead:0,
            pairs:{k:{opponent:{id:'gauntlet:forge/duels/y',title:'Some Duel'},done:50,total:200,playing:true}}};
          answers=[base({status:'running',job,budgets:{}})];
          const node=await draw();
          assert(node.textContent.includes('Playing: Some Duel'));assert(node.textContent.includes('Started by someone'));
          const before=calls.length;flushTimers();await settle();assert.equal(calls.length,before+1);
          let asked=0;ask=async()=>{asked++;return 'stop';};
          answers=[base()];
          buttonText(node,'Stop').click();await settle();
          assert.equal(asked,1);assert.equal(writes.at(-1).path,'/api/gauntlet/stop');
          same(writes.at(-1).body,{id:'casual/test',version:'target'});
          assert(buttonText(node,'Play them'));
        """)

    def test_no_stop_without_the_right_and_late_answers_leave_another_page_alone(self):
        self.run_js("""
          answers=[base({status:'queued',job:{status:'queued',done:0,total:300,ahead:2,may_stop:false,pairs:{}},budgets:{}})];
          const node=await draw();
          assert(node.textContent.includes('Waiting: 2 runs ahead of it'));assert(!buttonText(node,'Stop'));
          let release;api=()=>new Promise(r=>{release=r;});
          flushTimers();routeToken++;release(played());await settle();
          assert(node.textContent.includes('Waiting: 2 runs ahead of it'));
        """)
