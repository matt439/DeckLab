"""Authoritative Undo reviews over fixture APIs, never actual database writes."""
import unittest

from decklab.tests import test_activity_ui as activity_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        activity_ui.ActivityInteractionTests.run_js(self, r'''
          const collectionRow=extra=>({name:'Llanowar Elves',set:'fdn',collector_number:'227',finish:'nonfoil',quantity:6,
            condition:'NM',language:'en',notes:'Present note',...extra});
          const tokenRow=extra=>({front:'Dog',back:'Beast',set:'',front_collector_number:'',back_collector_number:'',finish:'',quantity:4,
            front_details:'',back_details:'',notes:'Present token note',...extra});
          const preview=extra=>({available:true,id:42,expect:'a'.repeat(64),kind:'collection',space:'home',label:'Llanowar Elves (FDN 227 nonfoil)',
            fields:[{field:'quantity',before:6,after:4}],current:collectionRow(),restored:collectionRow({quantity:4}),...extra});
          const tokenPreview=()=>preview({kind:'tokens',label:'Dog / Beast',current:tokenRow(),restored:tokenRow({quantity:3,notes:'Previous token note'}),
            fields:[{field:'quantity',before:4,after:3},{field:'notes',before:'Present token note',after:'Previous token note'}]});
          const accepted=(p=preview(),extra={})=>({saved:true,source_id:p.id,expect:p.expect,kind:p.kind,space:p.space,
            sha256:'b'.repeat(64),revision:'3',summary:'Restored the fixture row.',restored:{...p.restored},...extra});
          const candidate=(id=42,extra={})=>change(id,{headline:'User1 edited a fixture row',kinds:['collection'],undo:{review:true},
            rows:[{table:'collection_card',op:'UPDATE',summary:'A displayed audit row',
              before:{name:'Displayed old name',quantity:999},after:{name:'Displayed current name',quantity:888}}],...extra});
          const mount=(changes=[candidate()],next=null,filter={kind:null,actor:null})=>{
            routeToken++;colCloseSheets();clear(main);state.profile=state.profiles[0];state.may=null;location.hash=activityHref(filter);
            const view=activityDraw(page(changes,next),routeToken,filter);return{view,trigger:view.days.querySelector('.activity-review-undo')};
          };
          const open=async(p=preview())=>{const made=mount();api=async()=>p;made.trigger.click();await settle();return{...made,sheet:[...colSheets].at(-1),p};};
          const button=(root,text)=>root.querySelectorAll('button').find(node=>node.textContent===text);
          const save=sheet=>button(sheet.dialog,'Save Undo');
          const freshPage=()=>page([candidate(43,{undo:undefined}),candidate(42,{undo:undefined})]);
        ''' + scenario)

    def test_only_server_candidate_hint_offers_review_without_inferring_displayed_rows(self):
        self.run_js(r'''
          let made=mount([candidate(1,{undo:undefined}),candidate(2,{undo:{review:false}}),candidate(3)]);
          assert.equal(made.view.days.querySelectorAll('.activity-review-undo').length,1);
          const asked=[];api=async path=>{asked.push(path);return preview({id:3});};made.trigger.click();await settle();
          same(asked,['/api/activity/undo?id=3']);assert(save([...colSheets].at(-1)));
        ''')

    def test_authoritative_current_to_restored_values_and_identity_are_reviewed_before_save(self):
        self.run_js(r'''
          const {sheet}=await open();const text=sheet.body.textContent;
          for(const words of ['Llanowar Elves','fdn','227','nonfoil','Current','Restored by Undo','Quantity: 6','Quantity: 4',
            'one new audited change','original change stays in Activity'])assert(text.includes(words),words);
          assert(!text.includes('999'));assert(!text.includes('888'));assert(!text.includes('Displayed old name'));assert(save(sheet));
        ''')

    def test_token_identity_notes_and_blank_unknown_fields_stay_separate(self):
        self.run_js(r'''
          const {sheet}=await open(tokenPreview());const text=sheet.body.textContent;
          for(const words of ['Dog / Beast','Dog','Beast','Not recorded','Quantity: 4','Quantity: 3','Present token note','Previous token note'])
            assert(text.includes(words),words);
          assert(!text.includes('single-sided verified'));assert(!text.includes('Near Mint'));
        ''')

    def test_open_cancel_and_reopen_are_read_only_and_never_reuse_a_preview(self):
        self.run_js(r'''
          const {view,trigger}=mount();let reads=0,writes=0;api=async()=>{reads++;return preview();};apiWrite=async()=>{writes++;};
          trigger.click();await settle();const first=[...colSheets].at(-1);button(first.dialog,'Cancel').click();assert(!view.undoBusy);
          trigger.click();await settle();const second=[...colSheets].at(-1);assert(first!==second);assert.equal(reads,2);assert.equal(writes,0);
        ''')

    def test_unsupported_reason_and_hidden_read_refusal_have_no_save_or_row_fallback(self):
        self.run_js(r'''
          const {sheet}=await open({available:false,id:42,reason:'Only a single simple edit can be undone.'});assert(!save(sheet));
          assert(sheet.body.textContent.includes('Only a single simple edit'));assert(!sheet.body.textContent.includes('Displayed current name'));
          const {trigger}=mount();api=async()=>{throw new ApiError(404,'No such change',{});};trigger.click();await settle();
          const failed=[...colSheets].at(-1);assert(!save(failed));assert(failed.body.textContent.includes("couldn't be loaded"));
        ''')

    def test_malformed_preview_or_changed_identity_fails_closed(self):
        self.run_js(r'''
          const invalid=[{id:41},{space:'user2'},{expect:'short'},{kind:'decks'},{kind:'__proto__'},{label:''},{fields:[]},
            {restored:collectionRow({quantity:4,name:'Different identity'})},{current:collectionRow({quantity:'6'})},{current:collectionRow({quantity:10000})},
            {fields:[{field:'quantity',before:888,after:4}]},{fields:[{field:'name',before:'A',after:'B'}]},
            {restored:{...collectionRow({quantity:4}),private_sql_id:7}},
            {fields:[{field:'quantity',before:6,after:4},{field:'quantity',before:6,after:4}]}];
          for(const extra of invalid){const {sheet}=await open(preview(extra));assert(!save(sheet),JSON.stringify(extra));assert(!sheet.body.textContent.includes('Restored by Undo'));}
        ''')

    def test_save_posts_only_source_and_exact_review_receipt_and_blocks_duplicate_clicks(self):
        self.run_js(r'''
          const {sheet,p}=await open();let resolve;const sent=[];apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(r=>resolve=r);};
          const old=save(sheet);old.focus();old.click();old.fire('click');same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64)}]]);
          resolve(accepted(p));await settle();assert(button(sheet.dialog,'Done'));assert(!save(sheet));assert(sheet.body.textContent.includes('Undo saved as a new change'));
          assert(sheet.body.textContent.includes('Current'));old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_saved_receipt_must_match_restored_row_and_all_source_scope_fields(self):
        self.run_js(r'''
          const invalid=[{saved:false},{source_id:43},{expect:'c'.repeat(64)},{kind:'tokens'},{space:'user2'},{sha256:'short'},
            {revision:3},{revision:''},{summary:''},{restored:collectionRow({quantity:5})},{restored:undefined}];
          for(const extra of invalid){const {sheet,p}=await open();let writes=0;apiWrite=async()=>{writes++;return accepted(p,extra);};
            const old=save(sheet);old.click();await settle();assert(!button(sheet.dialog,'Done'));assert(button(sheet.dialog,'Reload Activity'));
            assert(sheet.body.textContent.includes('could not be confirmed'));old.fire('click');assert.equal(writes,1);}
        ''')

    def test_conflict_and_unknown_save_retain_preview_but_require_reload_without_retry(self):
        self.run_js(r'''
          for(const failure of [Error('Lost response'),new ApiError(409,'Cannot undo Llanowar Elves: the row changed.',{}),new ApiError(403,'You cannot change this row.',{})]){
            const {sheet}=await open();let writes=0;apiWrite=async()=>{writes++;throw failure;};const old=save(sheet);old.focus();old.click();await settle();
            assert(!save(sheet));assert(button(sheet.dialog,'Reload Activity'));assert(sheet.body.textContent.includes('Reload Activity before reviewing another Undo'));
            assert(sheet.body.textContent.includes('Restored by Undo'));assert.equal(document.activeElement.getAttribute('role'),'alert');old.fire('click');assert.equal(writes,1);
          }
        ''')

    def test_stale_trigger_cannot_open_after_profile_route_root_or_controller_change(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','root','rootref','seqbusy','modal','detached']){
            const {view,trigger}=mount();let reads=0;api=async()=>{reads++;return preview();};let top;
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='root')view.days.remove();if(mode==='rootref')view.days=el('div');if(mode==='seqbusy')view.undoBusy=true;
            if(mode==='modal')top=openSheet('Other');if(mode==='detached')trigger.remove();trigger.fire('click');await settle();assert.equal(reads,0,mode);top?.close();
          }
        ''')

    def test_pending_older_read_blocks_review_and_does_not_steal_later_focus(self):
        self.run_js(r'''
          const {view,trigger}=mount([candidate()],42);let resolve;const reads=[];api=path=>{reads.push(path);return new Promise(r=>resolve=r);};
          view.older.focus();view.older.click();assert(view.older.disabled);trigger.focus();trigger.click();assert.equal(colSheets.size,0);assert.equal(reads.length,1);
          resolve(page([candidate(41,{undo:undefined})]));await settle();assert.equal(document.activeElement,trigger);
          api=async path=>{reads.push(path);return preview();};trigger.click();await settle();assert.equal(reads.length,2);assert(save([...colSheets].at(-1)));
        ''')

    def test_late_preview_cannot_reveal_row_for_new_profile_route_page_or_sequence(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','root','seq','closed']){
            const {view,trigger}=mount();let resolve;api=()=>new Promise(r=>resolve=r);trigger.click();const sheet=[...colSheets].at(-1);
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='root')view.days.remove();if(mode==='seq')view.seq++;if(mode==='closed')sheet.close();resolve(preview());await settle();
            assert(!sheet.body.textContent.includes('Llanowar Elves'),mode);assert(!save(sheet));
          }
        ''')

    def test_stale_or_mutated_preview_and_top_modal_cannot_save(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','root','seq','preview','modal','detached','filter']){
            const {view,sheet,p}=await open();let writes=0;apiWrite=async()=>{writes++;return accepted(p);};let top;const old=save(sheet);
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='root')view.days.remove();if(mode==='seq')view.seq++;if(mode==='preview')p.restored.quantity=99;
            if(mode==='filter')view.filter.kind='tokens';
            if(mode==='modal')top=openSheet('Other');if(mode==='detached')old.remove();old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();
          }
        ''')

    def test_done_refreshes_same_filters_and_loaded_page_depth_atomically(self):
        self.run_js(r'''
          const filter={kind:'collection',actor:'user1'},made=mount([candidate(),candidate(41,{undo:undefined})],41,filter),{view,trigger}=made;
          api=async()=>page([candidate(40,{undo:undefined}),candidate(39,{undo:undefined})],39);view.older.click();await settle();assert.equal(view.loadedPages,2);
          api=async()=>preview();trigger.click();await settle();const sheet=[...colSheets].at(-1);apiWrite=async()=>accepted();save(sheet).click();await settle();
          const oldRoot=view.days,asked=[];let finish;api=async path=>{asked.push(path);if(asked.length===1)return page([candidate(43,{undo:undefined}),candidate()],42);
            return new Promise(r=>finish=r);};button(sheet.dialog,'Done').click();await settle();assert.equal(view.days,oldRoot);assert.equal(view.shown,4);
          finish(page([candidate(41,{undo:undefined}),candidate(40,{undo:undefined})],40));await settle();assert(view.days!==oldRoot);assert.equal(view.loadedPages,2);
          same(asked,['/api/activity?kind=collection&actor=user1','/api/activity?before=42&kind=collection&actor=user1']);assert.equal(view.shown,4);
          assert.equal(view.next,40);assert.equal(location.hash,activityHref(filter));assert(!view.undoBusy);assert(!view.undoCtx);
        ''')

    def test_refresh_failure_retains_prior_days_and_depth_and_offers_explicit_reload(self):
        self.run_js(r'''
          const {sheet,view}=await open();apiWrite=async()=>accepted();save(sheet).click();await settle();const root=view.days;
          api=async()=>{throw Error('Read unavailable');};button(sheet.dialog,'Done').click();await settle();assert.equal(view.days,root);assert.equal(view.loadedPages,1);
          const reload=button(view.note,'Reload Activity');assert(reload);let writes=0;apiWrite=async()=>{writes++;};api=async()=>freshPage();reload.click();await settle();
          assert(view.days!==root);assert.equal(writes,0);assert.equal(view.loadedPages,1);
        ''')

    def test_refresh_waits_for_exact_sheet_history_landing_and_runs_only_once(self):
        self.run_js(r'''
          const {sheet,view}=await open();sheet.entry={token:850,pos:3,done:false,fromHistory:false};history.state={sheet:850,pos:3};
          apiWrite=async()=>accepted();save(sheet).click();await settle();let reads=0;api=async()=>{reads++;return freshPage();};button(sheet.dialog,'Done').click();
          assert.equal(reads,0);history.state={pos:2};window.fire('popstate');await settle();assert.equal(reads,1);window.fire('popstate');assert.equal(reads,1);
        ''')

    def test_late_pending_success_or_refresh_cannot_replace_new_view_or_profile(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','root','seq']){
            const {sheet,view,p}=await open();let resolve;apiWrite=()=>new Promise(r=>resolve=r);save(sheet).click();sheet.close();let reads=0;api=async()=>{reads++;return freshPage();};
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='root')view.days.remove();if(mode==='seq')view.seq++;resolve(accepted(p));await settle();assert.equal(reads,0,mode);
          }
        ''')

    def test_closed_pending_success_refreshes_original_activity_without_repeating_save(self):
        self.run_js(r'''
          const {sheet,view,p}=await open();let resolve,writes=0,reads=0;apiWrite=()=>{writes++;return new Promise(r=>resolve=r);};
          save(sheet).click();sheet.close();api=async()=>{reads++;return freshPage();};resolve(accepted(p));await settle();assert.equal(writes,1);assert.equal(reads,1);
          assert(!view.undoBusy);assert(!view.undoCtx);
        ''')

    def test_confirmation_error_and_refresh_preserve_later_user_focus(self):
        self.run_js(r'''
          for(const failed of [false,true]){
            const {sheet,p}=await open();let resolve,reject;apiWrite=()=>new Promise((r,no)=>{resolve=r;reject=no;});save(sheet).focus();save(sheet).click();
            const close=sheet.dialog.querySelector('.sheet-close');close.focus();if(failed)reject(Error('Lost response'));else resolve(accepted(p));await settle();assert.equal(document.activeElement,close);
          }
        ''')

    def test_private_notes_and_names_are_text_only_not_html(self):
        self.run_js(r'''
          const raw='<img src=x onerror=alert(1)>',p=preview({label:raw,current:collectionRow({notes:raw}),restored:collectionRow({notes:'Restored note'}),
            fields:[{field:'notes',before:raw,after:'Restored note'}]});const {sheet}=await open(p);
          assert(sheet.body.textContent.includes(raw));assert.equal(sheet.body.querySelectorAll('img').length,0);assert(save(sheet));
        ''')

    def test_modal_opened_during_refresh_leaves_tree_until_manual_reload_without_focus_takeover(self):
        self.run_js(r'''
          const {sheet,view}=await open();apiWrite=async()=>accepted();save(sheet).click();await settle();const root=view.days;let resolve;
          api=()=>new Promise(r=>resolve=r);button(sheet.dialog,'Done').click();await settle();const other=openSheet('Another task');const control=el('button',{text:'Keep focus'});other.body.append(control);control.focus();
          resolve(freshPage());await settle();assert.equal(view.days,root);assert.equal(document.activeElement,control);other.close();
          api=async()=>freshPage();button(view.note,'Reload Activity').click();await settle();assert(view.days!==root);
        ''')

    def test_long_authoritative_notes_remain_complete_in_review_without_new_inputs(self):
        self.run_js(r'''
          const note='A checked note '.repeat(100),p=preview({current:collectionRow({notes:note}),restored:collectionRow({notes:''}),
            fields:[{field:'notes',before:note,after:''}]});const {sheet}=await open(p);assert(sheet.body.textContent.includes(note));
          assert(sheet.body.textContent.includes('Not recorded'));assert.equal(sheet.body.querySelectorAll('input').length,0);assert.equal(sheet.body.querySelectorAll('textarea').length,0);
        ''')


if __name__ == "__main__":
    unittest.main()
