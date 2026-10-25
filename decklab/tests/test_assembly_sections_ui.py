"""Explicit physical sideboard recipes and durable intentions, without live builds."""
import unittest

from decklab.tests import test_assembly_completion_ui as completion_ui
from decklab.tests.test_workspace_ui import NODE


SETUP = """
  const withSections = (data=plan()) => ({...data,
    choices:data.choices.map(c => ({...c,sideboards:{target:[{name:'Beta',quantity:3},{name:'Gamma',quantity:2}],
      owned:[{name:'Beta',quantity:1}]}}))});
  const scopeSelect = () => main.querySelector('.pack-sideboard-choice').querySelector('select');
  const scopeMode = mode => { const select=scopeSelect(); select.value=mode; select.fire('change'); };
  const recipe = () => packingProgressView.selected[0];
  const mainScope = {mode:'main',label:'Main deck only',main_count:60,sideboard_count:0,
    sideboard_intended:5,return_count:0};
  const intention = {section:'Sideboard',name:'Beta',intended:3,assembled:0,remaining:3,missing:2,on_the_way:1};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblySectionsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        completion_ui.AssemblyCompletionUiTests.run_js(self, SETUP + scenario)

    def test_main_only_and_whole_sideboard_are_explicit_reversible_recipes(self):
        self.run_js("""
          drawAssembly(withSections(),routeToken); await settle();
          assert.equal(scopeSelect().value,'all'); assert(!('sideboard' in recipe()));
          scopeMode('main'); same(recipe().sideboard,{});
          assert(main.querySelector('.pack-sideboard-choice').textContent.includes('0 of 5 intended sideboard cards'));
          assert(main.textContent.includes('Packed sideboard cards omitted here will be put back'));
          scopeMode('all'); assert(!('sideboard' in recipe()));
          assert.equal(scopeSelect().value,'all');
        """)

    def test_custom_quantities_are_bounded_and_stale_fields_do_not_change_the_recipe(self):
        self.run_js("""
          drawAssembly(withSections(),routeToken); await settle(); scopeMode('custom');
          same(recipe().sideboard,{Beta:3,Gamma:2});
          const first=main.querySelector('.pack-sideboard-quantities').querySelector('input');
          first.value='1'; first.fire('change'); same(recipe().sideboard,{Beta:1,Gamma:2});
          first.value='3'; first.fire('change'); same(recipe().sideboard,{Beta:1,Gamma:2});
          let current=main.querySelector('.pack-sideboard-quantities').querySelector('input');
          for (const value of ['-1','4','1.5','','not a number']) {
            current.value=value; current.fire('change'); assert.equal(current.value,'1');
            same(recipe().sideboard,{Beta:1,Gamma:2});
          }
          assert(main.querySelector('.form-error').textContent.includes('whole number from 0 to 3'));
          current.value='0'; current.fire('change'); same(recipe().sideboard,{Gamma:2});
          assert.equal(scopeSelect().value,'custom');
        """)

    def test_version_change_discards_counts_from_the_previous_sideboard(self):
        self.run_js("""
          drawAssembly(withSections(),routeToken); await settle(); scopeMode('custom');
          main.querySelector('.pack-version').querySelectorAll('button').find(n => n.textContent==='Play-now list').click();
          assert.equal(recipe().version,'owned'); assert(!('sideboard' in recipe()));
          assert.equal(scopeSelect().value,'all');
          assert(main.querySelector('.pack-sideboard-choice').textContent.includes('1 of 1 intended sideboard cards'));
          assert(!main.querySelector('.pack-sideboard-quantities'));
        """)

    def test_initial_normalized_selection_and_preview_preserve_exact_recipe(self):
        self.run_js("""
          const data=withSections(); data.selections=[{id:'casual/a',version:'target',sideboard:{Beta:1}}];
          drawAssembly(data,routeToken); await settle(); same(recipe().sideboard,{Beta:1});
          assert.equal(scopeSelect().value,'custom');
          const calls=[]; mockApi(async(path,body) => { calls.push([path,body]); return {...data,selections:body.decks}; });
          await packRun(packingProgressView); await settle();
          same(calls,[['/api/assembly/preview',{decks:[{id:'casual/a',version:'target',sideboard:{Beta:1}}]}]]);
          same(recipe().sideboard,{Beta:1});
        """)

    def test_presets_drop_custom_mode_and_use_the_whole_current_sideboard(self):
        self.run_js("""
          drawAssembly(withSections(),routeToken); await settle(); scopeMode('custom');
          main.querySelector('.pack-presets').querySelectorAll('button').find(n => n.textContent==='Built and being built').click();
          assert(!('sideboard' in recipe())); assert.equal(scopeSelect().value,'all');
          assert(main.querySelector('.pack-sideboard-choice').textContent.includes('5 of 5 intended sideboard cards'));
        """)

    def test_scope_controls_ignore_old_viewer_route_and_build_save(self):
        self.run_js("""
          for (const mode of ['saving','reviewing','profile','route']) {
            clear(main); state.profile={id:'matt',space:'home',role:'admin'};
            drawAssembly(withSections(),routeToken); await settle();
            const select=scopeSelect(), view=packingProgressView;
            if (mode==='saving' || mode==='reviewing') view[mode]=true;
            if (mode==='profile') state.profile={id:'user1',space:'home',role:'member'};
            if (mode==='route') ++routeToken;
            select.value='main'; select.fire('change');
            assert(!('sideboard' in view.selected[0]),mode);
          }
        """)

    def test_bulk_scope_and_task_identity_follow_recipe_and_physical_snapshot(self):
        self.run_js("""
          const deck={...item(),assembly_key:'recipe-main-snapshot-1',build_scope:mainScope,remaining_intent:[intention]};
          drawAssembly(withSections(plan([deck])),routeToken); await settle();
          const firstId=packingProgressView.ticks[0].id;
          assert(main.querySelector('.pack-bulk-scope').textContent.includes('Main deck only'));
          assert(!main.querySelector('.pack-bulk-scope').textContent.includes('including any sideboard'));
          main.querySelector('.pack-bulk-tick').click(); await settle(); same(checked(),['true']);
          renderAssemblyPlan(packingProgressView,plan([{...deck,assembly_key:'recipe-main-snapshot-2'}])); await settle();
          assert.notEqual(packingProgressView.ticks[0].id,firstId); same(checked(),['false']);
          assert(main.querySelector('.pack-remaining-intent').textContent.includes('3 x Beta (Sideboard)'));
          assert(main.querySelector('.pack-remaining-intent').textContent.includes('2 to get; 1 on the way'));
        """)

    def test_donor_assembly_changes_require_a_fresh_transfer_confirmation(self):
        self.run_js("""
          const deck={...item(),steps:[{name:'Alpha',keep:0,storage:0,waiting:0,missing:0,
            transfers:[{from:'casual/donor',from_title:'Donor',quantity:2}]}]};
          const data=plan([deck]); data.assembly_keys={'casual/donor':'donor-1'};
          drawAssembly(data,routeToken); await settle(); checkCards(); await settle(); same(checked(),['true']);
          renderAssemblyPlan(packingProgressView,{...data,assembly_keys:{'casual/donor':'donor-2'}}); await settle();
          same(checked(),['false']);
        """)

    def test_main_only_can_finish_with_missing_sideboard_but_put_back_cards_need_checks(self):
        self.run_js("""
          const deck={...item(),build_scope:{...mainScope,return_count:2},remaining_intent:[intention],
            returns:[{name:'Old sideboard',quantity:2}]};
          const data=withSections(plan([deck])); data.selections=[{id:deck.id,version:'target',sideboard:{}}];
          let body=null; mockApi(async(path,value) => { body=value; return {saved:true,built:data.completion.decks,
            plan:completed(data),warnings:[],tables:{}}; });
          drawAssembly(data,routeToken); await settle();
          assert.equal(builtButton().textContent,'Mark main deck built');
          ticks()[0].click(); await settle(); assert(builtButton().disabled);
          assert(main.textContent.includes('Take these out of the deck and put them back in storage'));
          ticks()[1].click(); await settle(); assert(!builtButton().disabled);
          builtButton().click(); await settle(); same(body.decks,[{id:deck.id,version:'target',sideboard:{}}]);
        """)

    def test_final_review_states_physical_scope_removals_and_remaining_intentions(self):
        self.run_js("""
          const deck={...item(),build_scope:{...mainScope,return_count:2},remaining_intent:[intention]};
          const data=withSections(plan([deck])); data.completion.review=true;
          drawAssembly(data,routeToken); await settle(); checkCards(); await settle(); builtButton().click(); await settle();
          const sheet=[...assemblySheets][0]; assert(sheet);
          assert(sheet.body.textContent.includes('Main deck only: 60 main-deck cards + 0 of 5 intended sideboard cards'));
          assert(sheet.body.textContent.includes('Put back 2 cards from the previous assembly'));
          assert(sheet.body.textContent.includes('3 x Beta (Sideboard)'));
          sheet.body.querySelectorAll('button');
          sheet.close(); await settle();
        """)

    def test_saved_build_keeps_checked_evidence_until_a_fresh_plan(self):
        self.run_js("""
          const deck={...item(),assembly_key:'before',build_scope:mainScope,remaining_intent:[intention]};
          const data=withSections(plan([deck]));
          mockApi(async () => { const next=completed(data); next.decks[0].assembly_key='after';
            next.decks[0].remaining_intent=[{...intention,missing:1,on_the_way:2}];
            return {saved:true,built:data.completion.decks,plan:next,warnings:[],tables:{}}; });
          drawAssembly(data,routeToken); await settle(); checkCards(); await settle(); builtButton().click(); await settle();
          same(checked(),['true']); assert.equal(packingProgressView.data.decks[0].assembly_key,'before');
          assert(main.querySelector('.pack-remaining-intent').textContent.includes('1 to get; 2 on the way'));
        """)

    def test_assembled_overview_is_inventory_gated_and_distinguishes_unknown_availability(self):
        self.run_js("""
          const assembled={version:'owned',main_count:60,sideboard_count:1,sideboard_intended:3,changed:true,
            remaining:[{...intention,assembled:1,remaining:2,missing:null,on_the_way:null}]};
          const data={summary:{id:'casual/a',assembled},version:'target'};
          assert.equal(deckAssemblySection(data),null);
          const node=deckAssemblySection({...data,owned:{},assembled});
          assert(node.textContent.includes('60 main-deck cards + 1 of 3 intended sideboard cards'));
          assert(node.textContent.includes('physical assembly differs from the intended list'));
          assert(node.textContent.includes('availability needs checking'));
          assert(!node.textContent.includes('0 to get'));
          assert.equal(node.querySelector('a').getAttribute('href'),'#/assembly?deck=casual%2Fa&version=owned');
        """)

    def test_banner_keeps_intended_missing_cards_separate_from_the_built_main_deck(self):
        self.run_js("""
          const data={summary:{status:'built'},versions:['target'],version:'target',
            owned:{rows:[],totals:{missing:2,aud_missing:1,unpriced:[]}},
            assembled:{main_count:60,sideboard_count:0,sideboard_intended:3,remaining_count:3}};
          const node=availabilityBanner(data,{view:{tab:'overview'}});
          assert(node.querySelector('.deck-avail-head').textContent.includes('Intended list: 2 missing'));
          assert(node.querySelector('.deck-avail-assembled').textContent.includes('60 main-deck cards + 0 of 3 intended sideboard cards'));
          delete data.owned; assert.equal(availabilityBanner(data,{view:{tab:'overview'}}),null);
        """)
