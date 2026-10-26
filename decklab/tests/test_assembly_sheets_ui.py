"""Packing confirmation and stand-in choices through the real UI scripts."""
import json
import subprocess
import unittest

from decklab.tests.test_assembly_completion_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


CHOICES = SETUP + """
  state.may = {admin:true, accessories:true, see_accessories:true, see_inventory:['home']};
  let view;
  const renderPlan = renderAssemblyPlan;
  renderAssemblyPlan = (current, data) => { view = current; renderPlan(current, data); };
  const sheet = () => [...assemblySheets][0];
  const action = text => sheet().foot.querySelectorAll('button').find(button => button.textContent === text);
  const select = label => sheet().body.querySelectorAll('select').find(input => input.getAttribute('aria-label') === label);
  const kitReview = data => {
    data.completion.review = true;
    data.completion.decks.forEach(deck => Object.assign(deck, {versions:['target','owned'],owner:'matt',
      kit:{sleeves:null,deck_box:null,need:75,editable:true}}));
    return data;
  };
  const accessory = (id, kind, quantity=100, owner='matt') => ({id,kind,quantity,owner,label:id,used_by:[],capacity:80});
  api = async path => { assert.equal(path,'/api/accessories'); return {items:[
    accessory('Sleeves','sleeves'),accessory('Shared','sleeves',75,'shared'),
    accessory('Private','sleeves',100,'user1'),accessory('Box','deck_box',1)]}; };
  const withStandins = (data, rows=[], retired=[]) => {
    data.decks[0].standins = {rows,retired,choices:rows,version:'target',editable:true,sha256:'s'.repeat(64),
      needs:[{for:'Beta',qty:1,suggestion:'Alpha'}],candidates:[{name:'Alpha',free:2}],warnings:[]};
    data.cards.Beta = beta;
    return data;
  };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblySheetsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), CHOICES + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_confirmation_saves_kit_with_build_once_and_cancel_writes_nothing(self):
        self.run_js("""
          const data = kitReview(plan()); const posts=[]; let finish;
          mockApi((path,body) => { posts.push([path,body]); return new Promise(resolve => {finish=resolve;}); });
          drawAssembly(data,routeToken); await settle(); checkCards(); await settle();
          builtButton().click(); builtButton().click(); await settle();
          assert.equal(assemblySheets.size,1); assert.equal(posts.length,0);
          assert(!sheet().body.textContent.includes('Private'));
          assert(sheet().body.textContent.includes('25 spare'));
          action('Cancel').click(); await settle(); assert.equal(posts.length,0);
          assert.equal(builtBlocked(),false); same(checked(),['true']);
          builtButton().click(); await settle();
          select('Elves: sleeves').value='Shared'; select('Elves: deck box').value='Box';
          action('Mark as built').click(); await settle(); builtButton().click();
          assert.equal(posts.length,1);
          same(posts[0],['/api/assembly/built',{decks:[{id:'casual/a',version:'target'}],
            fingerprint:'first-plan',confirmed:true,kit:{'casual/a':{sleeves:'Shared',deck_box:'Box'}}}]);
          finish({built:data.completion.decks,plan:completed(data),warnings:[],tables:{}}); await settle();
          same(checked(),['true']); assert.equal(assemblySheets.size,0);
        """)

    def test_sleeves_another_deck_has_are_warned_about_before_marking_built(self):
        # Matt, 2026-10-19: choosing sleeves already in use warns first; Cancel saves nothing.
        self.run_js("""
          const data = kitReview(plan()); const posts=[];
          api = async () => ({items:[{...accessory('Shared','sleeves',100,'shared'),
            used_by:[{holder:'casual/other',title:'Other Deck'}]}]});
          mockApi(async(path,body)=>{posts.push([path,body]);return {built:data.completion.decks,plan:completed(data),warnings:[],tables:{}};});
          drawAssembly(data,routeToken); await settle(); checkCards(); await settle();
          builtButton().click(); await settle();
          const sleeves = select('Elves: sleeves');
          assert(sleeves.querySelectorAll('option').find(o=>o.value==='Shared').textContent.includes('Also used by Other Deck'));
          sleeves.value='Shared'; sleeves.fire('change');
          const ask = () => [...document.body.querySelectorAll('button')].find(b=>b.textContent==='Use them anyway');
          action('Mark as built').click(); await settle();
          assert(ask()); assert(document.body.textContent.includes('Other Deck uses Shared already.'));
          [...document.body.querySelectorAll('button')].filter(b=>b.textContent==='Cancel').pop().click(); await settle();
          assert.equal(posts.length,0); assert.equal(assemblySheets.size,1);
          action('Mark as built').click(); await settle(); ask().click(); await settle();
          assert.equal(posts.length,1);
          same(posts[0][1].kit,{'casual/a':{sleeves:'Shared',deck_box:null}});
        """)

    def test_one_box_cannot_be_chosen_for_two_decks_and_capacity_is_visible(self):
        self.run_js("""
          const data=kitReview(plan([item(),item('casual/b')]));
          api=async()=>({items:[{...accessory('Box','deck_box',1),capacity:60}]});
          drawAssembly(data,routeToken); await settle(); checkCards(); await settle();
          builtButton().click(); await settle();
          assert(sheet().body.textContent.includes('Too small: holds 60, 75 cards here'));
          const first=select('Elves: deck box'), second=select('Burn: deck box');
          first.value='Box'; first.fire('change'); second.value='Box'; second.fire('change');
          assert(action('Mark 2 decks built').disabled);
          assert(sheet().body.textContent.includes('not enough Box deck boxes'));
          second.value=''; second.fire('change'); assert(!action('Mark 2 decks built').disabled);
          action('Cancel').click(); await settle();
        """)

    def test_changing_built_list_returns_to_the_plan_without_a_write(self):
        self.run_js("""
          const data=kitReview(plan()); const posts=[];
          mockApi(async(path,body)=>{posts.push([path,body]);return plan([item('casual/a','owned')]);});
          drawAssembly(data,routeToken); await settle(); checkCards(); await settle();
          builtButton().click(); await settle();
          const input=select('Elves: built list'); input.value='owned'; input.fire('change'); await settle();
          assert.equal(assemblySheets.size,0); assert.equal(posts.length,0);
          assert(builtBlocked()); flushTimers(); await settle();
          same(posts,[['/api/assembly/preview',{decks:[{id:'casual/a',version:'owned'}]}]]);
          same(checked(),['false']);
        """)

    def test_a_selected_holder_can_release_its_box_for_another_selected_deck(self):
        self.run_js("""
          const data=kitReview(plan([item('casual/b'),item()]));
          data.completion.decks[1].kit.deck_box='Box';
          api=async()=>({items:[{...accessory('Box','deck_box',1),used_by:[{holder:'casual/a',title:'Elves'}]},
            {...accessory('Outside','deck_box',1),used_by:[{holder:'casual/other',title:'Other'}]}]});
          drawAssembly(data,routeToken); await settle(); checkCards(); await settle();
          builtButton().click(); await settle();
          const recipient=select('Burn: deck box'), donor=select('Elves: deck box');
          assert(!recipient.querySelectorAll('option').find(option=>option.value==='Box').disabled);
          assert(recipient.querySelectorAll('option').find(option=>option.value==='Outside').disabled);
          recipient.value='Box'; recipient.fire('change'); assert(action('Mark 2 decks built').disabled);
          donor.value=''; donor.fire('change'); assert(!action('Mark 2 decks built').disabled);
          action('Cancel').click(); await settle();
        """)

    def test_late_accessories_and_navigation_do_not_resume_a_confirmation(self):
        self.run_js("""
          const data=kitReview(plan()); let receive; const posts=[];
          api=()=>new Promise(resolve=>{receive=resolve;});
          mockApi(async(...args)=>posts.push(args));
          drawAssembly(data,routeToken); await settle(); checkCards(); await settle();
          builtButton().click(); await settle(); const old=sheet();
          state.profile={id:'user1',space:'home'}; closeAssemblySheets();
          receive({items:[accessory('Private','sleeves')]}); await settle();
          assert(old.closed); assert(!old.body.textContent.includes('Private'));
          assert.equal(posts.length,0); assert.equal(view.reviewing,false);
        """)

    def test_save_standins_is_explicit_and_refreshes_once_with_compare_and_swap(self):
        self.run_js("""
          const data=withStandins(plan()); const posts=[];
          mockApi(async(path,body)=>{posts.push([path,body]);return path.endsWith('preview')?data:{saved:true};});
          drawAssembly(data,routeToken); await settle();
          main.querySelectorAll('button').find(button=>button.textContent==='Choose stand-ins').click();
          assert.equal(posts.length,0,'suggestions are advisory');
          select('Stand-in for Beta, group 1').value='';
          action('Save stand-ins').click(); action('Save stand-ins').click(); await settle();
          same(posts[0],['/api/assembly/standins',{id:'casual/a',version:'target',sha256:'s'.repeat(64),
            decks:[{id:'casual/a',version:'target'}],fingerprint:'first-plan',
            rows:[{for:'Beta',using:null,qty:1}]}]);
          assert.equal(posts.filter(row=>row[0].endsWith('preview')).length,1);
          flushTimers(); await settle();
          assert.equal(posts.filter(row=>row[0].endsWith('preview')).length,1);
        """)

    def test_stale_standin_choices_require_a_new_plan(self):
        self.run_js("""
          const data=withStandins(plan()); const posts=[];
          mockApi(async(path,body)=>{posts.push([path,body]);if(path.endsWith('standins'))
            throw Object.assign(new Error('Deck changed'),{status:409}); return data;});
          drawAssembly(data,routeToken); await settle(); openPackStandins(view,data.decks[0]);
          action('Save stand-ins').click(); await settle();
          assert(!action('Save stand-ins')); assert(select('Stand-in for Beta, group 1').disabled);
          action('Refresh plan').click(); await settle();
          assert.equal(assemblySheets.size,0); assert.equal(posts.length,2);
        """)

    def test_anonymous_markers_require_physical_acknowledgement(self):
        self.run_js("""
          const data=withStandins(plan(),[{for:'Beta',using:null,qty:2}]);
          drawAssembly(data,routeToken); await settle();
          assert(main.textContent.includes('Ready to pack with 2 stand-ins'));
          assert.equal(ticks().length,2); ticks()[0].click(); await settle();
          assert(builtBlocked()); ticks()[1].click(); await settle(); assert(!builtBlocked());
          assert(main.querySelectorAll('.card-tile').some(tile=>tile.textContent.includes('Use any spare card')));
        """)

    def test_removed_recipe_wording_does_not_claim_a_real_card_arrived(self):
        self.run_js("""
          const data=withStandins(plan(),[],[{for:'Beta',using:'Alpha',qty:1,reason:'list_changed'}]);
          drawAssembly(data,routeToken); await settle();
          assert(main.textContent.includes('Alpha will no longer stand for Beta'));
          assert(!main.textContent.includes('Beta is now available'));
          const oldDeck=data.decks[0]; view.data={...data,decks:[]};
          assert.equal(openPackStandins(view,oldDeck),null,'stale buttons cannot open a new editor');
        """)

    def test_late_build_and_preview_responses_are_ignored_after_switching_person(self):
        self.run_js("""
          const data=plan(); let respond;
          mockApi(()=>new Promise(resolve=>{respond=resolve;}));
          drawAssembly(data,routeToken); await settle(); checkCards(); await settle();
          builtButton().click(); await settle();
          state.profile={id:'user1',space:'home'};
          respond({built:data.completion.decks,plan:completed(data),warnings:[],tables:{}}); await settle();
          assert(!main.textContent.includes('Elves is now marked built'));
          assert.equal(view.choices[0].status,'building');
          state.profile={id:'matt',space:'home'}; clear(main); drawAssembly(data,routeToken); await settle();
          view.run(); await settle(); state.profile={id:'user1',space:'home'};
          respond({...data,note:'PRIVATE LATE PLAN'}); await settle();
          assert(!main.textContent.includes('PRIVATE LATE PLAN'));
          assert.equal(openPackStandins(view,data.decks[0]),null);
        """)

    def test_changing_plan_closes_an_open_confirmation(self):
        self.run_js("""
          const data=kitReview(plan()); drawAssembly(data,routeToken); await settle(); checkCards(); await settle();
          builtButton().click(); await settle(); assert.equal(assemblySheets.size,1);
          view.selected=[]; packChanged(view); await settle();
          assert.equal(assemblySheets.size,0); assert.equal(view.reviewing,false);
          assert(builtBlocked());
        """)


if __name__ == "__main__":
    unittest.main()
