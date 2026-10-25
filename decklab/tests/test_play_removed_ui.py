"""Removed-deck game and sideboard forms over the real scripts and DOM double."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, WEB, RUNNER
from decklab.tests.test_deck_sideboard_ui import FIXTURE


SETUP = """
  state.profile={id:'matt',name:'Matt',space:'home'};state.profiles=[state.profile];
  const removed={removed:true,title:'a removed deck'};
  const survivor={id:'casual/a',version:'target',sha256:'a',title:'Surviving deck',player:'Matt',mulligans:1,
    sections:{Deck:[{name:'Llanowar Elves',qty:4},{name:'Forest',qty:56}],Sideboard:[{name:'Pick Your Poison',qty:2}]}};
  const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class RemovedPlayUiTests(unittest.TestCase):
    def run_js(self, code, setup=SETUP):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_both_game_seats_render_without_a_list_or_former_player(self):
        self.run_js("""
          for(const sides of [[removed,survivor],[survivor,removed]]){
            const record={id:'r',date:'2026-10-08',result:sides[0].removed?'a':'b',notes:'',sides};
            const entry={record,sha256:'s',can:{sides:sides.map(s=>!s.removed),result:false}};
            const card=playGameCard(entry,{lists:[survivor]});
            assert(card.textContent.includes('a removed deck won'));
            assert(!card.textContent.includes('undefined'));assert(!card.textContent.includes('null'));
            assert.equal(card.querySelectorAll('h4').length,1);
            assert.equal(playMatchupSummaries([entry]).length,1);
            assert(!playSummarySection([entry]).textContent.includes('undefined'));
          }
        """)

    def test_correct_game_echoes_exact_removed_marker_and_only_edits_survivor(self):
        self.run_js("""
          const entry={sha256:'s',can:{sides:[false,true],result:false},record:{id:'r',date:'2026-10-08',result:'a',
            notes:'',sides:[removed,survivor]}};
          const requests=[];apiWrite=async(path,payload)=>{requests.push(payload);throw new Error('Stop preview');};
          playGameForm({lists:[survivor],sideboards:[],today:'2026-10-08'},'',entry);
          const form=document.body.querySelector('.play-form');
          assert(!form.textContent.includes('undefined'));
          assert.equal(form.querySelector('textarea').disabled,true);
          const numbers=form.querySelectorAll('input').filter(i=>i.getAttribute('type')==='number');
          assert.equal(numbers.length,1);numbers[0].value='2';
          form.fire('submit');await settle();
          same(requests[0].sides[0],removed);assert.equal(requests[0].sides[1].mulligans,2);
          assert.equal(requests[0].result,'a');assert.equal(requests[0].notes,'');
        """)

    def test_retained_plan_echoes_removed_opponent_instead_of_choosing_a_deck(self):
        self.run_js("""
          const record={id:'p',revision:2,updated_by:'someone',notes:'Kept plan',deck:survivor,opponent:removed,
            out:[{name:'Llanowar Elves',qty:1}],in:[{name:'Pick Your Poison',qty:1}],after:survivor.sections};
          const entry={record,sha256:'s',editable:true},data={lists:[survivor],sideboards:[]};
          const card=playPlanCard(entry,data);assert(card.textContent.includes('against a removed deck'));
          assert(!card.textContent.includes('undefined'));
          const requests=[];apiWrite=async(path,payload)=>{requests.push(payload);throw new Error('Stop preview');};
          playPlanForm(data,'',entry);
          const form=document.body.querySelector('.play-form');assert.equal(form.querySelectorAll('select').length,1);
          form.fire('submit');await settle();same(requests[0].opponent,removed);
        """)

    def test_deck_sideboard_keeps_each_removed_opponent_plan_separate(self):
        self.run_js("""
          const gone={removed:true,title:'a removed deck'};
          const a=answer();a.lists=[own];a.sideboards=[planEntry('first',own,gone),planEntry('second',own,gone)];
          a.sideboards[0].record.notes='First retained plan';a.sideboards[1].record.notes='Second retained plan';
          await mount(a);
          const options=section().querySelector('select').querySelectorAll('option');
          assert.equal(options.length,3);assert(options[1].textContent.includes('a removed deck'));
          choose('0');assert(section().textContent.includes('First retained plan'));
          choose('1');assert(section().textContent.includes('Second retained plan'));
          assert(!section().textContent.includes('undefined'));
          assert(!section().querySelectorAll('button').some(b=>b.textContent==='Make a sideboard plan'));
          assert(section().querySelectorAll('button').some(b=>b.textContent==='Revise this plan'));
        """, setup=FIXTURE)


if __name__ == "__main__":
    unittest.main()
