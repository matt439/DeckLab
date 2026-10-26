"""Server-verified movable-copy preferences are transient guarded packing recipes."""
import unittest

from decklab.tests import test_assembly_overlap_ui as overlap
from decklab.tests.test_workspace_ui import NODE


SETUP = """
  const preferenceMay={...state.may};
  const preferredPlan=(preferred=null)=>{const data=competition();
    Object.assign(data.rows[0],{preference_options:['casual/a','casual/b'],preferred});
    data.selections=data.decks.map(d=>({id:d.id,version:d.version,...(d.id===preferred?{prefer:['Alpha']}: {})}));
    return data;};
  const openPreferences=async(data=preferredPlan())=>{clear(main);location.hash='#/assembly';
    state.profile={id:'matt',space:'home',role:'admin'};state.may={...preferenceMay};
    drawAssembly(data,routeToken);await settle();return packingProgressView;};
  const preferenceSelect=view=>view.results.querySelector('[data-pack-preference]');
  const resetPriorities=view=>view.results.querySelectorAll('button').find(n=>n.textContent==='Reset card priorities');
  const choose=(view,id)=>{const select=preferenceSelect(view);select.value=id;select.fire('change');return select;};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblyPreferenceUiTests(unittest.TestCase):
    def run_js(self, scenario):
        overlap.AssemblyOverlapUiTests.run_js(self, SETUP + scenario)

    def test_only_verified_mapping_adds_native_select_and_preserves_copy_facts(self):
        self.run_js("""
          const data=preferredPlan(),before=JSON.stringify(data),view=await openPreferences(data),select=preferenceSelect(view);
          assert(select);assert.equal(select.tag,'select');assert.equal(select.value,'');
          same(select.querySelectorAll('option').map(n=>[n.value,n.textContent]),
            [['','Default selection order'],['casual/a','Elves (Planned list)'],['casual/b','Burn (Play-now list)']]);
          assert.equal(select.getAttribute('aria-label'),'Give free copies of Alpha first to');
          assert(select.parentNode.textContent.includes('Give free copies of Alpha first to'));
          assert(view.results.querySelector('.pack-overlap').textContent.includes('Checking tasks does not change'));
          assert.equal(JSON.stringify(data),before);assert.equal(resetPriorities(view),undefined);
          assert.equal(view.playableOverlap.rows[0].participants[0].assigned,4);
          assert.equal(view.playableOverlap.rows[0].participants[1].missing,4);
        """)

    def test_absent_malformed_mismatched_and_unmovable_metadata_never_enables_select(self):
        self.run_js("""
          const mutations=[d=>delete d.rows[0].preference_options,d=>delete d.rows[0].preferred,
            d=>d.rows[0].preference_options=null,d=>d.rows[0].preference_options=['casual/a'],
            d=>d.rows[0].preference_options=['casual/a','private/hidden'],
            d=>d.rows[0].preference_options=['casual/a','casual/a'],
            d=>d.rows[0].preference_options=['casual/b','casual/a'],
            d=>d.rows[0].preferred='casual/b',d=>d.rows[0].preferred=false,
            d=>d.selections[1].version='target',d=>d.counts_confirmed=false,
            d=>{d.decks[0].steps[0].keep=4;d.decks[0].steps[0].storage=0;d.rows[0].kept=4;d.rows[0].from_storage=0;},
            d=>d.decks[0].standins.rows=[{for:'Alpha',using:null,qty:1}]];
          for(const mutate of mutations){const data=preferredPlan();mutate(data);const view=await openPreferences(data);
            assert(!preferenceSelect(view),String(mutate));}
          const plain=competition(),view=await openPreferences(plain);assert(!preferenceSelect(view));
          assert(view.results.querySelector('.pack-overlap'));
        """)

    def test_changing_recipient_moves_only_one_name_and_uses_the_existing_fresh_preview(self):
        self.run_js("""
          const data=preferredPlan('casual/a');data.selections[0].prefer.push('Beta');data.selections[1].prefer=['Gamma'];
          const before=JSON.stringify(data),view=await openPreferences(data),calls=[];
          mockApi(async(path,body)=>{calls.push([path,body]);const next=preferredPlan('casual/b');
            next.selections=body.decks;return next;});
          const select=choose(view,'casual/b');assert(view.previewing);
          same(view.selected.map(c=>c.prefer),[['Beta'],['Gamma','Alpha']]);
          assert.equal(JSON.stringify(data),before);assert.equal(calls.length,0);
          await packRun(view);await settle();assert.equal(calls.length,1);
          same(calls,[['/api/assembly/preview',{decks:[{id:'casual/a',version:'target',prefer:['Beta']},
            {id:'casual/b',version:'owned',prefer:['Gamma','Alpha']}]}]]);
          assert.equal(preferenceSelect(view).value,'casual/b');assert(!preferenceSelect(view).disabled);
          assert(!select.isConnected);same(view.selected.map(c=>c.prefer),[['Beta'],['Gamma','Alpha']]);
        """)

    def test_default_clears_only_that_card_and_repeated_pending_events_do_not_change_recipe(self):
        self.run_js("""
          const data=preferredPlan('casual/a');data.selections[0].prefer.push('Beta');
          const view=await openPreferences(data),select=choose(view,'');same(view.selected[0].prefer,['Beta']);
          assert(!('prefer' in view.selected[1]));const after=JSON.stringify(view.selected),seq=view.seq;
          select.value='casual/b';select.fire('change');assert.equal(select.value,'');
          assert.equal(JSON.stringify(view.selected),after);assert.equal(view.seq,seq);
        """)

    def test_choice_copy_and_normalized_response_never_share_preference_arrays(self):
        self.run_js("""
          const source={id:'casual/a',version:'target',sideboard:{Beta:1},prefer:['Alpha']},copy=packSelectedChoice(source);
          copy.prefer.push('Beta');copy.sideboard.Beta=2;same(source.prefer,['Alpha']);same(source.sideboard,{Beta:1});
          const data=preferredPlan('casual/a'),view=await openPreferences(data);
          assert.notEqual(view.selected[0].prefer,data.selections[0].prefer);
          view.selected[0].prefer.push('Beta');same(data.selections[0].prefer,['Alpha']);
          same(packSelectedChoice({id:'casual/a',version:'owned'}),{id:'casual/a',version:'owned'});
        """)

    def test_changed_version_or_sideboard_clears_that_choice_only(self):
        self.run_js("""
          const make=()=>{const data=preferredPlan('casual/a');data.selections[1].prefer=['Beta'];
            data.choices[0].sideboards={target:[{name:'Gamma',quantity:2}],owned:[{name:'Gamma',quantity:1}]};return data;};
          let view=await openPreferences(make()),picked=view.selected[0];
          packChooseVersion(view,picked,'target');same(picked.prefer,['Alpha']);
          view.picks.querySelectorAll('button').find(n=>n.textContent==='Play-now list').click();
          assert(!('prefer' in picked));same(view.selected[1].prefer,['Beta']);
          for(const mode of ['main','custom','all']){view=await openPreferences(make());
            if(mode==='all'){view.selected[0].sideboard={};drawPackPicks(view);}
            const scope=view.picks.querySelector('.pack-sideboard-choice').querySelector('select');scope.value=mode;scope.fire('change');
            assert(!('prefer' in view.selected[0]),mode);same(view.selected[1].prefer,['Beta']);}
          const data=make();data.selections[0].sideboard={Gamma:2};view=await openPreferences(data);
          const input=view.picks.querySelector('.pack-sideboard-quantities').querySelector('input');input.value='1';input.fire('change');
          same(view.selected[0].sideboard,{Gamma:1});assert(!('prefer' in view.selected[0]));same(view.selected[1].prefer,['Beta']);
        """)

    def test_removing_recipient_drops_its_recipe_without_changing_other_preferences(self):
        self.run_js("""
          const data=preferredPlan('casual/b');data.selections[0].prefer=['Beta'];const view=await openPreferences(data);
          const box=view.picks.querySelectorAll('input').find(n=>n.getAttribute('data-pack-id')==='casual/b');
          box.checked=false;box.fire('change');same(view.selected,[{id:'casual/a',version:'target',prefer:['Beta']}]);
        """)

    def test_busy_and_modal_refusals_restore_accepted_native_value(self):
        self.run_js("""
          for(const mode of ['previewing','saving','reviewing','modal']){const view=await openPreferences(preferredPlan('casual/a'));
            let dialog;if(mode==='modal'){dialog=el('dialog',{open:true});main.append(dialog);}else view[mode]=true;
            const seq=view.seq,select=choose(view,'casual/b');assert.equal(select.value,'casual/a',mode);
            same(view.selected.map(c=>c.prefer),[['Alpha'],null]);assert.equal(view.seq,seq);
            dialog?.remove();}
        """)

    def test_stale_profile_route_hash_root_data_recipe_and_detached_controls_cannot_choose(self):
        self.run_js("""
          const mutations=[v=>state.profile={id:'user1',space:'home'},v=>++routeToken,
            v=>location.hash='#/assembly?deck=casual/other',v=>v.root.remove(),v=>v.data=clone(v.data),
            v=>v.playableOverlap={...v.playableOverlap},v=>v.selected[0].sideboard={},
            v=>preferenceSelect(v).remove(),v=>state.may={...state.may,see_home_records:false}];
          for(const mutate of mutations){const view=await openPreferences(preferredPlan('casual/a')),select=preferenceSelect(view);
            const before=JSON.stringify(view.selected),seq=view.seq;mutate(view);const current=JSON.stringify(view.selected);
            select.value='casual/b';select.fire('change');assert.equal(view.seq,seq,String(mutate));
            assert.equal(JSON.stringify(view.selected),current);assert.equal(select.value,'casual/a');}
          const view=await openPreferences();const select=choose(view,'forged/recipient');assert.equal(select.value,'');
          assert(!view.previewing);assert(!view.selected.some(c=>c.prefer));
        """)

    def test_harmless_hidden_preferences_keep_guarded_generic_reset_without_overlap(self):
        self.run_js("""
          let data=preferredPlan('casual/a');data.decks[1].steps[0].missing=0;data.decks[1].steps[0].keep=4;
          data.rows[0].kept=4;data.rows[0].missing=0;data.totals.missing=0;
          let view=await openPreferences(data);assert(!preferenceSelect(view));assert(resetPriorities(view));
          assert(view.results.querySelector('.pack-overlap').textContent.includes('Reset them to retry in selection order'));
          resetPriorities(view).click();assert(view.previewing);assert(!view.selected.some(c=>c.prefer));
          data=preferredPlan();const third=participant('casual/c',[demand(4,{keep:4})]);
          data=response([...data.decks,third]);Object.assign(data.rows[0],{preference_options:['casual/a','casual/b'],preferred:'casual/c'});
          data.selections=data.decks.map(d=>({id:d.id,version:d.version,...(d.id==='casual/c'?{prefer:['Alpha']}: {})}));
          view=await openPreferences(data);assert(!preferenceSelect(view));assert(resetPriorities(view));
          assert.deepEqual(view.selected[2].prefer,['Alpha']);
        """)

    def test_failed_preview_can_reset_priorities_and_retry_same_decks(self):
        self.run_js("""
          const view=await openPreferences(),calls=[];choose(view,'casual/b');
          mockApi(async(path,body)=>{calls.push([path,body]);throw new Error('Card markers changed.');});
          await packRun(view);await settle();assert.equal(view.data,null);assert(!preferenceSelect(view));
          const reset=resetPriorities(view);assert(reset);assert(view.message.textContent.includes('Card markers changed'));
          reset.click();assert(view.previewing);assert(!view.selected.some(c=>c.prefer));
          same(view.selected.map(c=>[c.id,c.version]),[['casual/a','target'],['casual/b','owned']]);
          mockApi(async(path,body)=>{calls.push([path,body]);return preferredPlan();});await packRun(view);await settle();
          assert.equal(calls.length,2);assert(calls.every(([path])=>path==='/api/assembly/preview'));
          assert(preferenceSelect(view));reset.click();assert.equal(calls.length,2);
        """)

    def test_generic_reset_rejects_busy_stale_and_detached_recipe_controls(self):
        self.run_js("""
          const mutations=[v=>v.previewing=true,v=>v.reviewing=true,v=>v.saving=true,v=>++routeToken,
            v=>location.hash='#/assembly?version=owned',v=>v.data=clone(v.data),v=>v.selected[0].sideboard={},
            v=>resetPriorities(v).remove(),v=>v.root.remove(),v=>state.profile={id:'user1',space:'home'}];
          for(const mutate of mutations){const view=await openPreferences(preferredPlan('casual/a')),reset=resetPriorities(view);
            mutate(view);const before=JSON.stringify(view.selected),seq=view.seq;reset.click();
            assert.equal(JSON.stringify(view.selected),before);assert.equal(view.seq,seq);}
        """)

    def test_standin_save_and_following_preview_carry_the_selected_preferences(self):
        self.run_js("""
          const data=plan();data.selections=[{id:'casual/a',version:'target',prefer:['Alpha']}];
          data.decks[0].standins={rows:[],choices:[],retired:[],version:'target',editable:true,sha256:'s'.repeat(64),
            needs:[{for:'Beta',qty:1,suggestion:null}],candidates:[],warnings:[]};const calls=[];
          mockApi(async(path,body)=>{calls.push([path,body]);return path.endsWith('/preview')?data:{saved:true};});
          const view=await openPreferences(data);view.results.querySelectorAll('button').find(n=>n.textContent==='Choose stand-ins').click();
          const sheet=[...assemblySheets][0];assert(sheet);document.querySelectorAll('dialog[open]')[0].querySelectorAll('button').find(n=>n.textContent==='Save stand-ins').click();
          await settle();assert.equal(calls[0][0],'/api/assembly/standins');same(calls[0][1].decks,data.selections);
          assert.equal(calls[1][0],'/api/assembly/preview');same(calls[1][1].decks,data.selections);
        """)

    def test_actual_build_review_version_change_clears_its_priorities_only(self):
        self.run_js("""
          const data=plan([item('casual/a'),item('casual/b','owned')]);data.completion.review=true;
          data.completion.decks.forEach(d=>d.versions=['target','owned']);
          data.selections=[{id:'casual/a',version:'target',prefer:['Alpha']},{id:'casual/b',version:'owned',prefer:['Beta']}];
          const view=await openPreferences(data);checkCards();await settle();builtButton().click();await settle();
          const sheet=[...assemblySheets][0],select=sheet.body.querySelectorAll('select').find(n=>n.getAttribute('aria-label')==='Elves: built list');
          assert(select);select.value='owned';select.fire('change');await settle();
          assert.equal(view.selected[0].version,'owned');assert(!('prefer' in view.selected[0]));same(view.selected[1].prefer,['Beta']);
          assert.equal(assemblySheets.size,0);assert(view.previewing);
        """)

    def test_current_owned_preference_focus_returns_to_the_fresh_control(self):
        self.run_js("""
          const view=await openPreferences(),select=preferenceSelect(view);select.focus();choose(view,'casual/b');
          mockApi(async()=>preferredPlan('casual/b'));await packRun(view);await settle();
          assert.notEqual(preferenceSelect(view),select);assert.equal(document.activeElement,preferenceSelect(view));
          assert.equal(preferenceSelect(view).value,'casual/b');
          const reset=resetPriorities(view);reset.focus();reset.click();mockApi(async()=>preferredPlan());await packRun(view);await settle();
          assert.equal(document.activeElement,view.results.querySelector('.pack-overlap').querySelector('h2'));
        """)

    def test_preference_focus_falls_back_after_error_and_never_steals_moved_focus(self):
        self.run_js("""
          let view=await openPreferences(),select=preferenceSelect(view);select.focus();choose(view,'casual/b');
          mockApi(async()=>{throw new Error('Changed plan');});await packRun(view);await settle();
          assert.equal(document.activeElement,resetPriorities(view));
          view=await openPreferences();select=preferenceSelect(view);select.focus();choose(view,'casual/b');
          const elsewhere=el('button',{text:'Elsewhere'});main.append(elsewhere);elsewhere.focus();
          mockApi(async()=>preferredPlan('casual/b'));await packRun(view);await settle();assert.equal(document.activeElement,elsewhere);
          view=await openPreferences();select=preferenceSelect(view);select.focus();packPreferenceBeforeRender(view);
          clear(view.results);view.data=preferredPlan();packOverlapStart(view,view.data);const notice=packOverlapNotice(view);view.results.append(notice);
          location.hash='#/deck?id=other';await settle();assert.notEqual(document.activeElement,preferenceSelect(view));
        """)

    def test_reset_to_ready_without_overlap_focuses_attached_casual_or_lab_chooser(self):
        self.run_js("""
          for(const wide of [false,true]){window.matchMedia('(min-width: 1000px)').matches=wide;
            const data=plan();data.selections=[{id:'casual/a',version:'target',prefer:['Alpha']}];
            const view=await openPreferences(data),reset=resetPriorities(view);reset.focus();reset.click();
            mockApi(async()=>plan());await packRun(view);await settle();assert(!view.results.querySelector('.pack-overlap'));
            assert.equal(document.activeElement,wide?view.chooserHeading:view.chooserLaunch);
            assert(document.activeElement.isConnected);}
        """)

    def test_built_payload_preserves_preferences_and_reset_does_not_mutate_response(self):
        self.run_js("""
          const data=plan();data.selections=[{id:'casual/a',version:'target',prefer:['Alpha']}];
          const before=JSON.stringify(data),view=await openPreferences(data),calls=[];
          mockApi(async(path,body)=>{calls.push([path,body]);return {saved:true,built:data.completion.decks,
            plan:completed(data),warnings:[],tables:{}};});
          checkCards();await settle();builtButton().click();await settle();
          assert.equal(calls[0][0],'/api/assembly/built');same(calls[0][1].decks,data.selections);
          assert.equal(JSON.stringify(data),before);
        """)
