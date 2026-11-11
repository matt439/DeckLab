"""Counted minimum plans use local choices, private replacement gates and fresh owner controls."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + r'''
  state.profile={id:'matt',space:'home'};state.may={deck_spaces:['home'],see_inventory:['home']};
  location.hash='#/deck?id=commander/test';
  const data=makePage();Object.assign(data.summary,{id:'commander/test',kind:'commander',space:'home',target_bracket:3});
  data.stats={commander:{bracket:{fixes:{checked:true,target:3,current_minimum:4,cuts:1,receipt:'a'.repeat(64),
    note:'These counts do not name the deck bracket.',plans:[{fixed:[],choose:{count:1,names:['A','B','C','D']},after_minimum:3}]}}}};
  const show=()=>{const root=bracketFixesPart(data);clear(main).append(root);return root;};
  const flush=async()=>{for(let i=0;i<20;i++)await null;};
  const choose=(root,n,on=true)=>{const field=root.querySelectorAll('input')[n];field.checked=on;field.fire('change');};
  const requests=[];let answer={note:'After all selected cuts and one replacement.',candidates:[]};
  apiWrite=async(path,body)=>{requests.push({path,body});return answer;};
  const free=(root,n=0)=>root.querySelectorAll('.bracket-cut-row')[n].querySelectorAll('button').find(button=>button.textContent==='Free replacements');
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class BracketFixUiTests(unittest.TestCase):
    def run_js(self, scenario):
        done = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_any_one_choice_starts_unticked_and_checks_exactly_one_without_writing(self):
        self.run_js(r'''
          const root=show();assert(root.textContent.includes('Any 1 of these 4 Game Changers'));
          assert(root.querySelectorAll('input').every(field=>!field.checked));assert(free(root).disabled);
          choose(root,0);assert(!free(root).disabled);assert(free(root,1).disabled);choose(root,1);assert(free(root).disabled);
          choose(root,1,false);free(root).click();await flush();assert.equal(requests.length,1);
          assert.equal(requests[0].path,'/api/deck/bracket-replacements');same(requests[0].body.cuts,['A']);
          assert.equal(requests[0].body.sha256,'a'.repeat(64));assert(root.textContent.includes("does not name the deck's bracket"));
        ''')

    def test_unsafe_and_unknown_replacements_are_marked_and_cannot_be_tested(self):
        self.run_js(r'''
          const candidate=(name,fit,minimum)=>({name,fit,after_minimum:minimum,one_swap_legal:true,
            card:card(name,'Creature',2),free:1,here:1,max_qty:1,note:{text:'Same slot'},fit_note:'Counted minimum '+minimum});
          answer.candidates=[candidate('Safe','safe',3),candidate('Raises','unsafe',4),candidate('Unchecked','unknown',null)];
          const root=show();choose(root,0);free(root).click();await flush();
          assert(root.textContent.includes('Would raise the counted minimum again'));assert(root.textContent.includes('Counted minimum unknown'));
          const tests=root.querySelectorAll('button').filter(button=>button.textContent==='Test this swap');
          same(tests.map(button=>button.disabled),[false,true,true]);let tested=0;
          testReplacementSwap=(...args)=>{tested++;assert(args[4]());};tests[0].click();assert.equal(tested,1);
        ''')

    def test_public_read_only_projection_keeps_intrinsic_choices_without_inventory_controls(self):
        self.run_js(r'''
          data.stats.commander.bracket.fixes.receipt=null;state.may={deck_spaces:[],see_inventory:[]};
          const root=show();assert(root.textContent.includes('Any 1'));assert(!root.textContent.includes('Free replacements'));
          choose(root,0);assert.equal(requests.length,0);assert(root.textContent.includes('counted minimum would be Bracket 3'));
        ''')

    def test_missing_data_is_not_an_all_clear_and_no_needed_cuts_adds_no_prompt(self):
        self.run_js(r'''
          data.stats.commander.bracket.fixes={checked:false,reason:'Tag and combo data unavailable.'};const root=show();
          assert(root.textContent.includes('unavailable'));assert.equal(root.querySelectorAll('button').length,0);
          data.stats.commander.bracket.fixes={checked:true,cuts:0};assert.equal(bracketFixesPart(data),null);
        ''')

    def test_choice_or_profile_drift_ignores_late_replacements_and_old_controls(self):
        self.run_js(r'''
          let done;apiWrite=()=>new Promise(resolve=>done=resolve);const root=show();choose(root,0);free(root).click();
          choose(root,0,false);choose(root,1);done({candidates:[{name:'Stale secret replacement'}]});await flush();
          assert(!root.textContent.includes('Stale secret replacement'));
          state.profile={...state.profile};free(root,1).click();assert.equal(requests.length,0);
        ''')

    def test_canonical_address_and_same_deck_tab_switch_keep_current_controls_usable(self):
        self.run_js(r'''
          const root=show();location.hash='#/deck?id=commander%2Ftest&tab=stats';choose(root,0);assert(!free(root).disabled);
          free(root).click();await flush();assert.equal(requests.length,1);
          location.hash='#/deck?id=commander%2Fother&tab=stats';choose(root,1);assert(!root.querySelectorAll('input')[1].checked);
        ''')

    def test_checked_identity_swap_changes_only_the_selected_section(self):
        self.run_js(r'''
          const sections={Commander:[{name:'Old leader',qty:1,set:'tst',number:'1',finish:'foil',category:'Leader'}],
            Deck:[{name:'Keep spell',qty:1,category:'Plan'}],Companion:[{name:'Keep companion',qty:1}]};
          const before=JSON.stringify(sections),changed=replacementSwapList(sections,'Old leader',
            {name:'New leader',section:'Commander',max_qty:1,default:{set:'tst',number:'2',finish:'nonfoil'}});
          assert.equal(changed.Commander[0].name,'New leader');same(changed.Deck,sections.Deck);same(changed.Companion,sections.Companion);
          assert.equal(JSON.stringify(sections),before);assert.equal(replacementSwapList(sections,'Old leader',{name:'No',section:'Unknown'}),null);
        ''')

    def test_changed_receipt_offers_an_explicit_scoped_reload_instead_of_retrying_stale_choices(self):
        self.run_js(r'''
          apiWrite=async()=>{throw new ApiError(409,'Changed');};const root=show();choose(root,0);free(root).click();await flush();
          const refresh=root.querySelectorAll('button').find(button=>button.textContent==='Reload deck counts');assert(refresh);
          let reloads=0;route=()=>reloads++;state.profile={...state.profile};refresh.click();assert.equal(reloads,0);
        ''')

    def test_a_second_deck_change_before_test_cannot_write_or_replace_a_local_draft(self):
        self.run_js(r'''
          const before=location.hash,writes=[],notices=[];local.set=(...args)=>{writes.push(args);return true;};toast=text=>notices.push(text);
          api=async()=>({id:'commander/test',sha256:'b'.repeat(64)});
          await testReplacementSwap(data,{name:'A'},{name:'Replacement',max_qty:1,expected_sha256:'a'.repeat(64)});
          assert.equal(writes.length,0);assert.equal(location.hash,before);assert(notices.some(text=>text.includes('deck changed')));
        ''')
