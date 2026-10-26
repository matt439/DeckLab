"""Take-apart review uses recorded physical evidence and one existing save, with no live writes."""
import unittest

from decklab.tests import test_assembly_completion_ui as completion
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class AssemblyTakeApartUiTests(unittest.TestCase):
    def run_js(self, scenario):
        completion.AssemblyCompletionUiTests.run_js(self, r'''
          const button=(root,text)=>root.querySelectorAll('button').find(node=>node.textContent===text);
          document.body.append(el('div',{id:'toast'}));
          const real=(name,quantity,basic=false)=>({kind:'card',name,quantity,basic,for:null});
          const marker=(name,quantity,target)=>({kind:'marker',name,quantity,basic:name===null?null:false,for:target});
          const contents=extra=>({available:true,reason:null,can_take_apart:true,why_not:null,sha256:'b'.repeat(64),
            source:'assembled',version:'owned',sections:{Commander:[real('Recorded commander',1)],Companion:[real('Recorded companion',1)],
              Deck:[real('Recorded Elf',2),real('Forest',20,true),marker('Named physical marker',1,'Represented spell'),marker(null,1,'Missing spell')],
              Sideboard:[real('Packed sideboard card',3)]},card_count:29,tokens_recorded:true,
            tokens:[{quantity:2,front:'Dog',back:'Beast',set:'tfdn',number:'12'},
              {quantity:1,front:'The Monarch',back:'',set:'',number:''}],token_count:3,
            kit:{sleeves:{state:'linked',id:'fixture-sleeves',label:'Recorded sleeves'},
              deck_box:{state:'text',value:'Recorded older box',label:'Recorded older box'}},kit_reason:null,...extra});
          const selected=()=>[{id:'casual/a',version:'target',sideboard:{Beta:1}},
            {id:'casual/b',version:'owned',sideboard:{},prefer:['Alpha']}];
          const takePlan=(info=contents())=>{const a=item(),b=item('casual/b','owned');
            a.take_apart=info;a.completion={...a.completion,status:'built',already_built:true};
            const data=plan([a,b]);data.selections=selected();return data;};
          const takeButton=view=>view.results.querySelector('.pack-take-apart');
          const localChecks=sheet=>sheet.body.querySelectorAll('input').filter(input=>input.getAttribute('type')==='checkbox');
          const checkLocal=(sheet,except=-1)=>localChecks(sheet).forEach((input,index)=>{input.checked=index!==except;input.fire('change');});
          const saveButton=sheet=>button(sheet.dialog,'Mark deck taken apart');
          const openTake=async(info=contents())=>{const data=takePlan(info),view=drawAssembly(data,routeToken);await settle();
            takeButton(view).click();return {data,view,sheet:[...assemblySheets].at(-1)};};
          const capture=handler=>{const calls=[];mockApi((path,body)=>{calls.push([path,body]);return handler(path,body);});return calls;};
          const accepted=()=>({saved:true,id:'casual/a',stale_tables:[]});
          const closeHeader=sheet=>sheet.dialog.querySelector('.sheet-close');
          const reset=()=>{closeAssemblySheets();clear(main);state.profile={id:'matt',name:'Matt',plays_as:'user',role:'admin',space:'home'};location.hash='#/assembly';};
        ''' + scenario)

    def test_all_recorded_sections_basics_markers_tokens_and_kit_are_shown(self):
        self.run_js(r'''
          const {sheet}=await openTake();const text=sheet.body.textContent;
          for(const words of ['Commander','Companion','Deck','Sideboard','1 x Recorded commander','1 x Recorded companion',
            '2 x Recorded Elf','20 x Forest','3 x Packed sideboard card','1 x Named physical marker (marked for Represented spell)',
            '1 x spare card (marked for Missing spell)','Return 2 x Dog // Beast (TFDN 12) to the token pile',
            'Recorded sleeves','Recorded older box','29 physical cards','not confirmed printing assignments'])assert(text.includes(words),words);
          assert(!text.includes('2 x Alpha'));assert.equal(localChecks(sheet).length,12);assert(saveButton(sheet).disabled);
        ''')

    def test_local_ticks_and_cancel_do_not_post_and_reopening_resets_checks(self):
        self.run_js(r'''
          const calls=capture(()=>{throw Error('Local review must not write');}),{sheet,view}=await openTake();
          checkLocal(sheet);assert(!saveButton(sheet).disabled);assert.equal(calls.length,0);
          button(sheet.dialog,'Cancel').click();assert(!view.reviewing);takeButton(view).click();
          const fresh=[...assemblySheets].at(-1);assert(fresh!==sheet);assert(localChecks(fresh).every(input=>!input.checked));
          assert(saveButton(fresh).disabled);assert.equal(calls.length,0);
        ''')

    def test_every_check_is_required_before_the_final_action(self):
        self.run_js(r'''
          const calls=capture(()=>new Promise(()=>{})),{sheet}=await openTake();
          for(let index=0;index<localChecks(sheet).length;index++){
            checkLocal(sheet,index);assert(saveButton(sheet).disabled,index);saveButton(sheet).click();assert.equal(calls.length,0);
          }
          checkLocal(sheet);assert(!saveButton(sheet).disabled);
        ''')

    def test_exact_sha_status_only_payload_and_duplicate_click_guard(self):
        self.run_js(r'''
          let resolve;const calls=capture(()=>new Promise(done=>resolve=done)),{sheet,view}=await openTake();
          checkLocal(sheet);const old=saveButton(sheet);old.focus();old.click();old.click();
          same(calls,[['/api/deck/save',{id:'casual/a',sha256:'b'.repeat(64),fields:{status:'building'}}]]);
          assert(view.saving);assert(localChecks(sheet).every(input=>input.disabled));
          resolve(accepted());await settle();assert(!view.saving);assert(button(sheet.dialog,'Done'));
          old.click();assert.equal(calls.length,1);assert(sheet.body.textContent.includes('intended lists are kept'));
        ''')

    def test_malformed_or_unavailable_metadata_has_no_save_or_intended_list_fallback(self):
        self.run_js(r'''
          const valid=contents();for(const extra of [{available:false,reason:'Fixture physical evidence unreadable'},
            {sha256:'bad'},{card_count:28},{sections:{Deck:[]}},{sections:{Deck:[real('A',1)],Unknown:[real('B',1)]}},
            {token_count:4},{tokens_recorded:false},{tokens:[{quantity:0,front:'Dog'}]},{can_take_apart:'yes'},
            {sections:{Deck:[marker(null,29,'')]}},{sections:{Deck:[real('Bad'+String.fromCharCode(10)+'name',29)]}},
            {sections:{Deck:[{...real('A',29),for:'Wrong target'}]}},{sections:{Deck:[{...real('A',29),basic:null}]}},
            {sections:{Deck:[{...marker(null,29,'A'),basic:false}]}}]){
            assert.equal(packTakeApartContents({...valid,...extra}),null);
          }
          const calls=capture(()=>{throw Error('Unavailable evidence must not save');}),{sheet}=await openTake(contents({available:false,reason:'Fixture physical evidence unreadable'}));
          assert(sheet.body.textContent.includes('Fixture physical evidence unreadable'));assert.equal(localChecks(sheet).length,0);
          assert(!saveButton(sheet));assert(!sheet.body.textContent.includes('Alpha'));assert(button(sheet.dialog,'Close'));assert.equal(calls.length,0);
        ''')

    def test_read_only_review_never_saves_even_after_checking_everything(self):
        self.run_js(r'''
          const calls=capture(()=>{throw Error('Read only');}),{sheet}=await openTake(contents({can_take_apart:false,why_not:'Fixture viewer cannot edit this deck.'}));
          assert(sheet.body.textContent.includes('Fixture viewer cannot edit this deck.'));checkLocal(sheet);
          assert(saveButton(sheet).disabled);saveButton(sheet).fire('click');assert.equal(calls.length,0);
        ''')

    def test_stale_or_busy_plan_buttons_cannot_open_the_review(self):
        self.run_js(r'''
          for(const mode of ['node','data','recipe','profile','route','hash','previewing','reviewing','saving','dialog']){
            reset();const data=takePlan(),view=drawAssembly(data,routeToken);await settle();const old=takeButton(view);let dialog;
            if(mode==='node')renderAssemblyPlan(view,data);if(mode==='data')view.data={...data};if(mode==='recipe')view.selected[0].version='owned';
            if(mode==='profile')state.profile={id:'other'};if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(['previewing','reviewing','saving'].includes(mode))view[mode]=true;if(mode==='dialog')dialog=openSheet('Other modal');
            old.click();assert.equal(assemblySheets.size,0,mode);dialog?.close();
          }
        ''')

    def test_unsettled_progress_blocks_review_with_visible_guidance(self):
        self.run_js(r'''
          const view=drawAssembly(takePlan(),routeToken);await settle();const p=view.progress;
          for(const mode of ['loaded','busy','pending','error']){
            if(mode==='loaded')p.loaded=false;if(mode==='busy')p.busy=true;if(mode==='pending')p.pending.set('fixture',{done:true});if(mode==='error')p.error='Fixture outage';
            takeButton(view).click();assert.equal(assemblySheets.size,0,mode);assert(view.message.textContent.includes('shared packing ticks'));
            p.loaded=true;p.busy=false;p.pending.clear();p.error=null;
          }
        ''')

    def test_open_review_cannot_save_after_profile_route_hash_plan_recipe_or_top_modal_changes(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','plan','recipe','modal']){
            reset();const calls=capture(()=>{throw Error('Stale review must not save');}),{sheet,view}=await openTake();checkLocal(sheet);const old=saveButton(sheet);let modal;
            if(mode==='profile')state.profile={id:'other'};if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='plan')view.data={...view.data};if(mode==='recipe')view.selected[0].version='owned';if(mode==='modal')modal=openSheet('Top modal');
            old.fire('click');assert.equal(calls.length,0,mode);modal?.close();
          }
        ''')

    def test_late_success_cannot_change_a_new_profile_route_or_retired_page(self):
        self.run_js(r'''
          for(const mode of ['profile','route','page']){
            reset();let resolve;const calls=capture(()=>new Promise(done=>resolve=done)),{sheet,view}=await openTake();checkLocal(sheet);saveButton(sheet).click();
            if(mode==='profile')state.profile={id:'other'};if(mode==='route')routeToken++;if(mode==='page'){view.root.remove();main.append(el('p',{text:'New page'}));}
            const before=JSON.stringify(view.selected);resolve(accepted());await settle();assert.equal(calls.length,1,mode);
            assert.equal(JSON.stringify(view.selected),before,mode);assert(!button(sheet.dialog,'Done'),mode);
            if(mode==='page')assert.equal(main.textContent,'New page');
          }
        ''')

    def test_conflict_and_uncertain_network_failure_require_refresh_without_retrying_save(self):
        self.run_js(r'''
          for(const failure of [Object.assign(Error('Fixture deck changed'),{status:409}),Error('Fixture connection lost')]){
            reset();const calls=capture((path,body)=>{if(path==='/api/deck/save')throw failure;assert.equal(path,'/api/assembly/preview');return takePlan();});
            const {sheet,view}=await openTake();checkLocal(sheet);const old=saveButton(sheet);old.focus();old.click();await settle();
            assert(!saveButton(sheet));assert(button(sheet.dialog,'Refresh plan'));assert(sheet.body.textContent.includes('Refresh the plan before trying again'));
            old.fire('click');assert.equal(calls.length,1);button(sheet.dialog,'Refresh plan').click();await settle();
            same(calls.map(([path])=>path),['/api/deck/save','/api/assembly/preview']);same(calls[1][1],{decks:selected()});assert(!view.reviewing);
          }
        ''')

    def test_success_done_removes_only_taken_deck_and_preserves_other_exact_recipe(self):
        self.run_js(r'''
          const calls=capture((path,body)=>{if(path==='/api/deck/save')return accepted();assert.equal(path,'/api/assembly/preview');return plan([item('casual/b','owned')]);});
          const {sheet,view}=await openTake();view.buildKit={'casual/a':{sleeves:'a'},'casual/b':{sleeves:'b'}};
          checkLocal(sheet);saveButton(sheet).click();await settle();assert.equal(calls.length,1);assert.equal(view.selected.length,2);
          button(sheet.dialog,'Done').click();await settle();assert.equal(calls.length,2);
          same(calls[1],['/api/assembly/preview',{decks:[selected()[1]]}]);same(view.selected,[selected()[1]]);
          assert.equal(view.choices.find(choice=>choice.id==='casual/a').status,'building');assert(!view.buildKit['casual/a']);assert(view.buildKit['casual/b']);
          assert(!view.reviewing);assert(!view.saving);
        ''')

    def test_header_close_during_pending_success_reconciles_same_view_only(self):
        self.run_js(r'''
          let resolve;const calls=capture((path,body)=>{if(path==='/api/deck/save')return new Promise(done=>resolve=done);
            assert.equal(path,'/api/assembly/preview');return plan([item('casual/b','owned')]);});
          const {sheet,view}=await openTake();checkLocal(sheet);saveButton(sheet).click();closeHeader(sheet).click();assert(sheet.closed);assert(view.saving);
          resolve(accepted());await settle();same(calls.map(([path])=>path),['/api/deck/save','/api/assembly/preview']);
          same(calls[1][1],{decks:[selected()[1]]});assert(!view.saving);assert(!view.reviewing);
        ''')

    def test_focus_follows_owned_result_but_preserves_later_user_focus(self):
        self.run_js(r'''
          for(const moved of [false,true])for(const failed of [false,true]){
            reset();let resolve,reject;capture(()=>new Promise((done,no)=>{resolve=done;reject=no;}));const {sheet}=await openTake();checkLocal(sheet);
            const trigger=saveButton(sheet);trigger.focus();trigger.click();const close=closeHeader(sheet);if(moved)close.focus();
            if(failed)reject(Object.assign(Error('Fixture changed'),{status:409}));else resolve(accepted());await settle();
            if(moved)assert.equal(document.activeElement,close);
            else {assert(sheet.body.contains(document.activeElement));assert.equal(document.activeElement.getAttribute('role'),failed?'alert':'status');}
          }
        ''')

    def test_absent_vs_explicit_empty_tokens_and_private_kit_are_honest(self):
        self.run_js(r'''
          for(const recorded of [false,true]){
            reset();const {sheet}=await openTake(contents({tokens_recorded:recorded,tokens:[],token_count:0,kit:null,kit_reason:'Kit details are private.'}));
            assert(sheet.body.textContent.includes(recorded?'Check the box for any other token or reminder cards':'none are recorded as packed'));
            assert(sheet.body.textContent.includes('Kit details are private.'));assert(sheet.body.textContent.includes('details not visible'));
            assert(!sheet.body.textContent.includes('Recorded sleeves'));assert(!sheet.body.textContent.includes('Recorded older box'));
          }
        ''')

    def test_checkbox_changes_roll_back_when_covered_stale_or_pending(self):
        self.run_js(r'''
          for(const mode of ['modal','profile','route','recipe','pending']){
            reset();capture(()=>new Promise(()=>{}));const {sheet,view}=await openTake();let other;
            if(mode==='pending'){checkLocal(sheet);saveButton(sheet).click();}
            if(mode==='modal')other=openSheet('Top modal');if(mode==='profile')state.profile={id:'other'};
            if(mode==='route')routeToken++;if(mode==='recipe')view.selected[0].version='owned';
            const input=localChecks(sheet)[0],was=Boolean(input.checked);input.checked=!was;input.fire('change');
            assert.equal(input.checked,was,mode);other?.close();
          }
        ''')

    def test_failure_under_a_later_modal_preserves_focus_and_restores_refresh_actions(self):
        self.run_js(r'''
          let reject;const calls=capture(()=>new Promise((done,no)=>reject=no)),{sheet}=await openTake();checkLocal(sheet);
          saveButton(sheet).focus();saveButton(sheet).click();const top=openSheet('Other current task');
          const focus=el('button',{text:'Current modal control'});top.body.append(focus);focus.focus();
          reject(Object.assign(Error('Fixture changed'),{status:409}));await settle();
          assert.equal(document.activeElement,focus);assert(!saveButton(sheet));
          assert(button(sheet.dialog,'Refresh plan'));assert(!button(sheet.dialog,'Refresh plan').disabled);
          assert(!button(sheet.dialog,'Cancel').disabled);assert.equal(calls.length,1);top.close();
          assert(button(sheet.dialog,'Refresh plan'));assert.equal(calls.length,1);
        ''')

    def test_known_success_header_close_finishes_once_and_retired_done_cannot_repeat_preview(self):
        self.run_js(r'''
          const calls=capture((path,body)=>path==='/api/deck/save'?accepted():plan([item('casual/b','owned')]));
          const {sheet,view}=await openTake();checkLocal(sheet);saveButton(sheet).click();await settle();
          const done=button(sheet.dialog,'Done');assert(done);closeHeader(sheet).click();await settle();
          same(calls.map(([path])=>path),['/api/deck/save','/api/assembly/preview']);same(view.selected,[selected()[1]]);
          done.fire('click');sheet.close();await settle();assert.equal(calls.length,2);
        ''')

    def test_closed_sheet_with_uncertain_result_only_refreshes_same_recipe_without_retrying_save(self):
        self.run_js(r'''
          let reject;const calls=capture((path,body)=>{if(path==='/api/deck/save')return new Promise((done,no)=>reject=no);
            assert.equal(path,'/api/assembly/preview');return takePlan();});
          const {sheet,view}=await openTake();checkLocal(sheet);saveButton(sheet).click();closeHeader(sheet).click();
          reject(Error('Fixture lost response'));await settle();
          same(calls.map(([path])=>path),['/api/deck/save','/api/assembly/preview']);same(calls[1][1],{decks:selected()});
          same(view.selected,selected());assert(!view.saving);assert(!view.reviewing);
        ''')
