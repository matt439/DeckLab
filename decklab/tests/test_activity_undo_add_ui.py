"""Restoring a deleted collection row requires explicit physical ownership confirmation."""
import unittest

from decklab.tests import test_activity_undo_ui as updates
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoAddUiTests(unittest.TestCase):
    def run_js(self, scenario):
        updates.ActivityUndoUiTests.run_js(self, r'''
          const addPreview=(extra={})=>{const p=preview({action:'add',physical_confirmation_required:true,current:null,restored:collectionRow({quantity:4}),...extra});
            delete p.fields;if(Object.hasOwn(extra,'fields'))p.fields=extra.fields;return p;};
          const added=(p=addPreview(),extra={})=>accepted(p,{action:'add',summary:'Restored the deleted fixture row.',
            added_key:{set:p.restored.set,collector_number:p.restored.collector_number,finish:p.restored.finish},...extra});
          const owned=sheet=>sheet.body.querySelector('input');
          const confirmOwned=(sheet,checked=true)=>{const input=owned(sheet);input.checked=checked;input.fire('change');return input;};
        ''' + scenario)

    def test_full_historical_row_and_all_copy_confirmation_have_no_invented_current_or_editable_counts(self):
        self.run_js(r'''
          const {sheet}=await open(addPreview());const text=sheet.body.textContent;
          for(const word of ['restores all 4 recorded copies','Historical row to restore','Llanowar Elves','fdn','227','nonfoil','NM','en','Present note',
            'still physically own the entire recorded quantity','own fewer copies, cancel and use Collection','original change stays in Activity'])assert(text.includes(word),word);
          assert(!text.includes('Current row'));assert(!text.includes('Quantity: 0'));assert(!text.includes('Reason for removing'));
          assert.equal(sheet.body.querySelectorAll('input').length,1);assert.equal(owned(sheet).getAttribute('type'),'checkbox');assert.equal(owned(sheet).checked,false);assert(save(sheet).disabled);
          assert(sheet.body.querySelectorAll('label').some(label=>label.getAttribute('for')===owned(sheet).id));
        ''')

    def test_only_exact_explicit_collection_restore_packet_is_accepted(self):
        self.run_js(r'''
          for(const extra of [{action:undefined},{action:'restore'},{kind:'tokens'},{physical_confirmation_required:false},{physical_confirmation_required:undefined},
            {current:{}},{current:collectionRow({quantity:0})},{restored:null},{restored:collectionRow({quantity:0})},{restored:collectionRow({quantity:'4'})},
            {fields:[]},{fields:[{field:'quantity',before:0,after:4}]},{reason_required:true},{extra:'unknown'}]){
            const {sheet}=await open(addPreview(extra));assert(!save(sheet),JSON.stringify(extra));assert.equal(owned(sheet),null);assert(!sheet.body.textContent.includes('Historical row to restore'));
          }
        ''')

    def test_save_posts_only_exact_source_receipt_and_true_confirmation_once(self):
        self.run_js(r'''
          const {sheet,p}=await open(addPreview());const input=confirmOwned(sheet);assert(!save(sheet).disabled);let finish;const sent=[];
          apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};const old=save(sheet);old.focus();old.click();old.fire('click');
          same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64),confirm_owned:true}]]);assert(input.disabled);finish(added(p));await settle();
          assert(button(sheet.dialog,'Done'));assert(!save(sheet));assert(owned(sheet).disabled);assert(sheet.body.textContent.includes('Restored the deleted fixture row.'));old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_uncheck_or_unaccepted_programmatic_confirmation_cannot_save(self):
        self.run_js(r'''
          const {sheet,p}=await open(addPreview());let writes=0;apiWrite=async()=>{writes++;return added(p);};owned(sheet).checked=true;save(sheet).fire('click');await settle();assert.equal(writes,0);
          confirmOwned(sheet);const old=save(sheet);owned(sheet).checked=false;old.fire('click');await settle();assert.equal(writes,0);
          confirmOwned(sheet,false);assert(save(sheet).disabled);confirmOwned(sheet,'true');assert(save(sheet).disabled);assert.equal(owned(sheet).checked,false);
        ''')

    def test_cancel_and_fresh_preview_never_reuse_a_previous_ownership_confirmation(self):
        self.run_js(r'''
          const {sheet,view,trigger}=await open(addPreview());confirmOwned(sheet);let writes=0;apiWrite=async()=>{writes++;};button(sheet.dialog,'Cancel').click();assert(!view.undoBusy);
          api=async()=>addPreview();trigger.click();await settle();const fresh=[...colSheets].at(-1);assert(fresh!==sheet);assert.equal(owned(fresh).checked,false);assert(save(fresh).disabled);assert.equal(writes,0);
        ''')

    def test_pending_checkbox_events_cannot_revoke_or_replace_the_sent_confirmation(self):
        self.run_js(r'''
          const {sheet,p}=await open(addPreview());const input=confirmOwned(sheet);let finish,body;apiWrite=(path,sent)=>{body=sent;return new Promise(done=>finish=done);};save(sheet).click();
          input.checked=false;input.fire('change');assert.equal(input.checked,true);assert(input.disabled);finish(added(p));await settle();assert.equal(body.confirm_owned,true);assert.equal(body.reason,undefined);
        ''')

    def test_receipt_requires_exact_added_key_full_historical_row_and_original_scope(self):
        self.run_js(r'''
          const invalid=[{action:undefined},{action:'remove'},{added_key:null},{added_key:[]},{added_key:{set:'fdn',collector_number:'227'}},
            {added_key:{set:'tst',collector_number:'227',finish:'nonfoil'}},{added_key:{set:'fdn',collector_number:'228',finish:'nonfoil'}},
            {added_key:{set:'fdn',collector_number:'227',finish:'foil'}},{added_key:{set:'fdn',collector_number:'227',finish:'nonfoil',quantity:4}},
            {removed_key:{set:'fdn',collector_number:'227',finish:'nonfoil'}},{restored:null},{restored:collectionRow({quantity:3})},
            {restored:collectionRow({quantity:4,notes:'Changed note'})},{restored:collectionRow({quantity:4,condition:''})},
            {restored:{...collectionRow({quantity:4}),private_sql_id:9}},{source_id:43},{expect:'c'.repeat(64)},{space:'user2'},{kind:'tokens'},
            {saved:false},{sha256:'bad'},{revision:3},{summary:''}];
          for(const extra of invalid){const {sheet,p}=await open(addPreview());confirmOwned(sheet);let writes=0;apiWrite=async()=>{writes++;return added(p,extra);};
            const old=save(sheet);old.click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));
            assert(sheet.body.textContent.includes('could not be confirmed'));assert(owned(sheet).disabled);old.fire('click');assert.equal(writes,1);}
        ''')

    def test_update_and_remove_receipts_cannot_claim_addition_and_update_payload_stays_unchanged(self):
        self.run_js(r'''
          const {sheet,p}=await open();let body;apiWrite=async(path,sent)=>{body=sent;return added();};save(sheet).click();await settle();same(body,{id:42,expect:'a'.repeat(64)});
          assert(button(sheet.dialog,'Reload Activity'));assert(!button(sheet.dialog,'Done'));
          const remove={...preview(),action:'remove',reason_required:true,current:collectionRow(),restored:null};delete remove.fields;
          assert.equal(activityUndoReceipt(added(),remove),false);assert.equal(activityUndoReceipt(accepted(p,{added_key:{set:'fdn',collector_number:'227',finish:'nonfoil'}}),p),false);
        ''')

    def test_update_cannot_ignore_an_unclassified_physical_confirmation_requirement(self):
        self.run_js(r'''
          const {sheet}=await open(preview({physical_confirmation_required:true}));assert(!save(sheet));assert.equal(owned(sheet),null);
          assert(!sheet.body.textContent.includes('Restored by Undo'));
        ''')

    def test_mutated_confirmation_preview_or_scope_cannot_authorize_a_save(self):
        self.run_js(r'''
          for(const mode of ['action','quantity','metadata','required','detached','profile','route','hash','root','seq','modal']){
            const {sheet,p,view}=await open(addPreview());confirmOwned(sheet);const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return added(p);};
            if(mode==='action')p.action='remove';if(mode==='quantity')p.restored.quantity=8;if(mode==='metadata')p.restored.notes='Different';if(mode==='required')p.physical_confirmation_required=false;
            if(mode==='detached')owned(sheet).remove();if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='root')view.days.remove();if(mode==='seq')view.seq++;if(mode==='modal')top=openSheet('Other task');old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();
          }
        ''')

    def test_stale_or_unknown_result_retains_historical_row_and_requires_reload_without_retry(self):
        self.run_js(r'''
          for(const failure of [Error('Lost reply'),new ApiError(409,'That printing was added meanwhile.',{}),new ApiError(400,'This row cannot be restored.',{})]){
            const {sheet}=await open(addPreview());confirmOwned(sheet);let writes=0;apiWrite=async()=>{writes++;throw failure;};const old=save(sheet);old.click();await settle();
            assert(sheet.body.textContent.includes('Historical row to restore'));assert.equal(owned(sheet).checked,true);assert(owned(sheet).disabled);assert(!save(sheet));
            assert(button(sheet.dialog,'Reload Activity'));old.fire('click');assert.equal(writes,1);assert(!sheet.body.textContent.includes('Undo saved as a new change'));
          }
        ''')

    def test_late_restore_preview_or_result_cannot_reveal_or_replace_a_new_owner(self):
        self.run_js(r'''
          const {trigger}=mount();let finish;api=()=>new Promise(done=>finish=done);trigger.click();const pending=[...colSheets].at(-1);state.profile=state.profiles[1];finish(addPreview());await settle();
          assert.equal(owned(pending),null);assert(!pending.body.textContent.includes('Llanowar Elves'));
          const {sheet,p}=await open(addPreview());confirmOwned(sheet);apiWrite=()=>new Promise(done=>finish=done);save(sheet).click();sheet.close();state.profile=state.profiles[1];routeToken++;
          clear(main);main.append(el('p',{text:'Current person page'}));let reads=0;api=async()=>{reads++;return freshPage();};finish(added(p));await settle();assert.equal(reads,0);assert.equal(main.textContent,'Current person page');
        ''')

    def test_done_keeps_same_filter_loaded_depth_and_original_audit_row(self):
        self.run_js(r'''
          const filter={kind:'collection',actor:'user1'},{view,trigger}=mount([candidate(),candidate(41,{undo:undefined})],41,filter);
          api=async()=>page([candidate(40,{undo:undefined}),candidate(39,{undo:undefined})],39);view.older.click();await settle();const p=addPreview();api=async()=>p;trigger.click();await settle();
          const sheet=[...colSheets].at(-1);confirmOwned(sheet);apiWrite=async()=>added(p);save(sheet).click();await settle();const asked=[];
          api=async path=>{asked.push(path);return asked.length===1?page([candidate(43,{undo:undefined}),candidate(42,{undo:undefined})],42):page([candidate(41,{undo:undefined}),candidate(40,{undo:undefined})],40);};
          button(sheet.dialog,'Done').click();await settle();same(asked,['/api/activity?kind=collection&actor=user1','/api/activity?before=42&kind=collection&actor=user1']);
          assert.equal(view.loadedPages,2);assert.equal(view.shown,4);assert.equal(location.hash,activityHref(filter));assert(view.days.querySelector('[data-activity-id="42"]'));assert(!view.undoBusy);assert.equal(view.undoCtx,null);
        ''')

    def test_confirmation_is_local_and_metadata_is_plain_text_without_edit_controls(self):
        self.run_js(r'''
          const raw='<img src=x onerror=alert(1)>',p=addPreview({restored:collectionRow({quantity:4,notes:raw})});const {sheet}=await open(p),hash=location.hash,prior=JSON.stringify(state);
          confirmOwned(sheet);assert(sheet.body.textContent.includes(raw));assert.equal(sheet.body.querySelector('img'),null);assert.equal(sheet.body.querySelectorAll('input').length,1);
          assert.equal(sheet.body.querySelector('textarea'),null);assert.equal(location.hash,hash);assert.equal(JSON.stringify(state),prior);
        ''')


if __name__ == "__main__":
    unittest.main()
