"""The deck page's "Against chosen decks" part (web/field-group.js, E3-S31) through its real renderers over an
isolated Node DOM: the choices (Public decks say so), ticking decks asks for that group, the average and rows,
Play with the chosen decks and the saved list, and a run's progress and Stop. Every answer is a fixture; no live
server, network, configuration, database or simulation is used.

Run with python scripts/test_fixtures.py decklab.tests.test_field_group_ui.
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
  const sha='b'.repeat(64);
  const choices=[{id:'casual/blue-test',version:'target',title:'Blue Test',kind:'casual',public:false},
    {id:'user2/casual/r-elves',version:'owned',title:'Elves',kind:'casual',public:true}];
  const base=(extra={})=>({deck:{id:'casual/test',version:'target',title:'Test Deck',card_sha:sha},format:'Constructed',
    opponents:[],overall:null,played:0,of:0,tally:null,updated:null,games:0,note:null,status:'none',job:null,
    notice:null,error:null,chosen:[],choices,budgets:{},default_budget:'standard',max_opponents:12,forge:{ready:true},
    ...extra});
  const rate=(value)=>({value,low:value-.1,high:value+.1});
  const chosen=()=>base({chosen:[{id:'casual/blue-test',version:'target'}],of:1,note:'This average covers these 1 chosen decks only, not the whole field.',
    opponents:[{id:'casual/blue-test',version:'target',title:'Blue Test',games:0,rate:null,lead:null,verdict:null,
      not_meaningful:false,problem:null,updated:null}],
    budgets:{standard:{games:400,new_games:400,minutes:[3,5]}}});
  const draw=async()=>{const node=groupSection({summary:{id:'casual/test',title:'Test Deck'},version:'target'});
    main.append(node);await settle();return node;};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class GroupUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_choices_then_play_the_chosen_decks(self):
        self.run_js("""
          answers=[base()];
          const node=await draw();
          assert(calls[0].startsWith('/api/field/group?id=casual%2Ftest&version=target'),calls[0]);
          assert(!calls[0].includes('opponents='));
          assert(buttonText(node,'Blue Test'));assert(buttonText(node,'Elves (Public)'));
          assert(!buttonText(node,'Play these decks'));
          answers=[chosen()];
          buttonText(node,'Blue Test').click();await settle();
          assert(calls.at(-1).includes('opponents=casual%2Fblue-test'),calls.at(-1));
          assert.equal(buttonText(node,'Blue Test').getAttribute('aria-pressed'),'true');
          assert(node.textContent.includes('Play 1 chosen deck'));
          const play=buttonText(node,'Play these decks');assert(play&&!play.disabled);
          play.click();await settle();
          assert.equal(writes.length,1);assert.equal(writes[0].path,'/api/field/group/run');
          same(writes[0].body,{id:'casual/test',version:'target',budget:'standard',opponents:['casual/blue-test'],
            expected_card_sha:sha});
        """)

    def test_the_running_lists_link_opens_testing_at_the_group(self):
        self.run_js("""
          answers=[base()];const jumps=[];jumpTo=(id)=>jumps.push(id);
          open('#/deck?id=casual%2Ftest&v=target&part=group');await settle();
          flushTimers();
          assert.equal(panel('matchups').hidden,false);
          assert(panel('matchups').querySelector('#sec-group'));
          assert(jumps.includes('sec-group'),String(jumps));
        """)

    def test_a_public_deck_keeps_its_version_in_the_group(self):
        self.run_js("""
          answers=[base()];
          const node=await draw();
          buttonText(node,'Elves (Public)').click();await settle();
          assert(calls.at(-1).includes('opponents=user2%2Fcasual%2Fr-elves%40owned'),calls.at(-1));
        """)

    def test_results_show_the_groups_average_and_each_deck(self):
        self.run_js("""
          answers=[base({chosen:[{id:'casual/blue-test',version:'target'},{id:'user2/casual/r-elves',version:'owned'}],
            of:2,played:2,games:400,overall:{key:'all',rate:.45,low:.38,high:.52,note:''},
            tally:{ahead:0,even:1,behind:1,unsettled:0},note:'This average covers these 2 chosen decks only, not the whole field.',
            opponents:[{id:'user2/casual/r-elves',version:'owned',title:'Elves',games:200,rate:rate(.3),verdict:'behind',
              not_meaningful:false,problem:null,updated:null},
              {id:'casual/blue-test',version:'target',title:'Blue Test',games:200,rate:rate(.6),verdict:'about even',
              not_meaningful:false,problem:null,updated:null}]})];
          const node=await draw();
          assert(node.textContent.includes('Against 2 chosen decks:'));
          assert(node.textContent.includes('2 chosen decks only, not the whole field'));
          const rows=[...node.querySelectorAll('.gt-name')].map((n)=>n.textContent);
          same(rows,['Elves','Blue Test']);
          assert(node.textContent.includes('Behind'));
        """)

    def test_a_playing_run_shows_progress_and_stop(self):
        self.run_js("""
          answers=[base({status:'running',chosen:[{id:'casual/blue-test',version:'target'}],of:1,
            job:{status:'running',done:50,total:200,ahead:0,by:'Matt',may_stop:true,
              pairs:{k:{opponent:{id:'casual/blue-test',title:'Blue Test'},done:50,total:200,playing:true}}}})];
          const node=await draw();
          assert(node.textContent.includes('Playing the chosen decks'));
          assert(node.textContent.includes('50 of 200 games · Playing: Blue Test'));
          assert.equal(buttonText(node,'Blue Test').disabled,true);
          assert(buttonText(node,'Stop'));
        """)
