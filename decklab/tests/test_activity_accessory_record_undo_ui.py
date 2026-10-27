"""Combined recorded facts restore together after one complete explicit review."""
import unittest

from decklab.tests import test_activity_accessory_undo_ui as accessories
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class AccessoryRecordUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        accessories.AccessoryUndoUiTests.run_js(self, r'''
          const recordPreview=(categories=['kind','quantity'],extra={})=>{const current={...accRow(),capacity:'100',quantity:'2'},restored={...current,notes:'Historical <img src=x onerror=alert(1)>'};
            for(const field of categories)restored[field]=({kind:'sleeves',owner:'shared',quantity:'100'})[field];
            if(restored.kind!=='deck_box')restored.capacity='';
            return{available:true,id:42,expect:'a'.repeat(64),kind:'accessory',action:'accessory_record_update',label:current.name,current,restored,
              fields:ACTIVITY_UNDO_ACCESSORY_QUANTITY_FIELDS.filter(field=>current[field]!==restored[field]).map(field=>({field,before:current[field],after:restored[field]})),record_confirmation_required:true,...extra};};
          const recordFields=p=>{p.fields=ACTIVITY_UNDO_ACCESSORY_QUANTITY_FIELDS.filter(field=>p.current[field]!==p.restored[field]).map(field=>({field,before:p.current[field],after:p.restored[field]}));return p;};
          const recordSaved=(p=recordPreview(),extra={})=>({saved:true,source_id:p.id,expect:p.expect,kind:'accessory',action:'accessory_record_update',
            restored:{...p.restored},sha256:'b'.repeat(64),revision:'4321',summary:'Restored the complete recorded accessory correction.',...extra});
          const openRecord=async(p=recordPreview())=>{const made=mount([accChange()],null,{kind:'sleeves',actor:null});api=async()=>p;
            made.trigger.click();await settle();return{...made,sheet:[...colSheets].at(-1),p};};
          const recordConsent=sheet=>sheet.body.querySelector('input[type=checkbox]');
          const confirmRecord=(sheet,value=true)=>{const input=recordConsent(sheet);input.checked=value;input.fire('change');return input;};
        ''' + scenario)

    def test_all_four_category_sets_review_both_complete_records_units_and_conditional_sharing(self):
        self.run_js(r'''
          for(const categories of [['owner','kind'],['owner','quantity'],['kind','quantity'],['owner','kind','quantity']]){
            const p=recordPreview(categories),{sheet}=await openRecord(p),text=sheet.body.textContent,panels=sheet.body.querySelector('.panels').querySelectorAll('.panel');
            assert.equal(panels.length,2);for(const panel of panels){assert.equal(panel.querySelectorAll('dt').length,11);assert.equal(panel.querySelectorAll('dd').length,11);}
            for(const words of ['Current','Restored by Undo','Accessory kind','Whose','Recorded quantity','2 items',
              p.restored.kind==='sleeves'?'individual sleeves':'items','Undo restores this whole recorded correction together',
              "restored quantity replaces this record's current total",'Current photos, crop and kit assignments stay as they are','Only an unused record',
              'references are checked again','still physically owned','loose ones included','Historical <img src=x onerror=alert(1)>'])assert(text.includes(words),words);
            assert.equal(text.includes('Both people at home can see and change Shared accessories'),categories.includes('owner'));
            assert.equal(text.includes("destination owner's existing Public/Private kit setting"),categories.includes('owner'));
            assert.equal(sheet.body.querySelectorAll('input').length,1);assert.equal(sheet.body.querySelector('input[type=number],input[type=text],select,textarea,img,a'),null);
            assert.equal(recordConsent(sheet).checked,false);assert(save(sheet).disabled);assert(!text.includes('Reason for removing'));
          }
        ''')

    def test_zero_restored_count_confirms_reference_kind_and_owner_without_owned_stock_claim(self):
        self.run_js(r'''
          const p=recordPreview(['owner','kind','quantity']);p.restored.quantity='0';recordFields(p);const {sheet}=await openRecord(p),text=sheet.body.textContent;
          for(const words of ['zero-quantity reference record','No owned items are added','should be Sleeves and Shared (both people at home)'])assert(text.includes(words),words);
          assert(!text.includes('still physically owned'));assert(save(sheet).disabled);let writes=0;apiWrite=async()=>{writes++;return recordSaved(p);};
          save(sheet).fire('click');await settle();assert.equal(writes,0);confirmRecord(sheet);save(sheet).click();await settle();assert.equal(writes,1);assert(button(sheet.dialog,'Done'));
        ''')

    def test_record_protocol_requires_two_categories_and_its_own_exact_confirmation_flag(self):
        self.run_js(r'''
          for(const categories of [[],['owner'],['kind'],['quantity']])assert.equal(activityUndoEvidence(recordPreview(categories),42,'home',state.profiles[0].id),null);
          const p=recordPreview(),bad=[{record_confirmation_required:false},{record_confirmation_required:undefined},{record_confirmation_required:1},
            {owner_confirmation_required:true},{kind_confirmation_required:true},{stock_confirmation_required:true},{confirmation_required:true},{reason_required:true},
            {action:'accessory_update'},{action:'accessory_stock_update'},{action:'accessory_owner_update'},{action:'accessory_kind_update'},{action:'accessory_add'},
            {space:'home'},{profile:state.profiles[0].id},{restored:{...p.restored,id:'another-id'}},{restored:{...p.restored,image:'fixture.jpg'}},
            {current:{...p.current,crop:''}},{current:accRow()},{restored:accRow()},{fields:p.fields.slice(1)},{fields:[...p.fields,p.fields[0]]}];
          for(const extra of bad){const {sheet}=await openRecord(recordPreview(undefined,extra));assert(!save(sheet),JSON.stringify(extra));assert.equal(recordConsent(sheet),null);}
        ''')

    def test_both_kind_owner_count_and_capacity_facts_remain_canonical_without_hidden_owner_override(self):
        self.run_js(r'''
          for(const side of ['current','restored'])for(const [field,value] of [['kind','box'],['kind','deck_box\n'],['owner',state.profiles[1].id],['owner','user2'],
            ['quantity',0],['quantity','00'],['quantity','10000'],['quantity','1\n'],['quantity','1\r'],['quantity','1\u2028'],['quantity','1\u2029']]){
            const p=recordPreview(['owner','kind','quantity']);p[side][field]=value;recordFields(p);assert.equal(activityUndoEvidence(p,42,'home',state.profiles[0].id),null,side+field+value);}
          for(const capacity of ['0','0100','100\n','100\r','100\u2028','100\u2029']){const p=recordPreview(['owner','quantity']);p.restored.capacity=capacity;recordFields(p);
            assert.equal(activityUndoEvidence(p,42,'home',state.profiles[0].id),null);}
          const nonbox=recordPreview();nonbox.restored.capacity='100';recordFields(nonbox);assert.equal(activityUndoEvidence(nonbox,42,'home',state.profiles[0].id),null);
        ''')

    def test_full_metadata_is_literal_and_whole_record_cannot_be_partially_selected(self):
        self.run_js(r'''
          const p=recordPreview(['owner','kind','quantity']);p.restored.link='https://example.com/<literal>';p.restored.image_source='HTTPS://example.com/picture/<literal>';
          p.restored.name='Historical <b>literal</b> name';recordFields(p);const {sheet}=await openRecord(p),text=sheet.body.textContent;
          for(const value of [p.restored.name,p.restored.link,p.restored.image_source])assert(text.includes(value),value);
          assert.equal(sheet.body.querySelector('img,a'),null);assert.equal(sheet.body.querySelectorAll('input').length,1);
          confirmRecord(sheet);let sent;apiWrite=async(path,body)=>{sent=[path,body];return recordSaved(p);};save(sheet).click();await settle();
          same(sent,['/api/activity/accessory-undo',{id:42,expect:'a'.repeat(64),confirm_record:true}]);assert(button(sheet.dialog,'Done'));
        ''')

    def test_combined_consent_is_explicit_and_resets_after_uncheck_and_cancel(self):
        self.run_js(r'''
          const {sheet}=await openRecord();let writes=0;apiWrite=async()=>{writes++;return recordSaved();};save(sheet).fire('click');await settle();assert.equal(writes,0);
          recordConsent(sheet).checked=true;save(sheet).fire('click');await settle();assert.equal(writes,0);confirmRecord(sheet);assert(!save(sheet).disabled);
          confirmRecord(sheet,false);assert(save(sheet).disabled);confirmRecord(sheet);button(sheet.dialog,'Cancel').click();const again=await openRecord();
          assert.equal(recordConsent(again.sheet).checked,false);assert(save(again.sheet).disabled);
        ''')

    def test_one_pending_save_sends_only_source_expect_and_complete_record_confirmation(self):
        self.run_js(r'''
          const {sheet,p}=await openRecord(),input=confirmRecord(sheet),old=save(sheet);let finish;const sent=[];
          apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};state.library={old:true};old.click();old.fire('click');
          same(sent,[['/api/activity/accessory-undo',{id:42,expect:'a'.repeat(64),confirm_record:true}]]);assert(input.disabled);
          input.checked=false;input.fire('change');assert(input.checked);finish(recordSaved(p));await settle();assert(button(sheet.dialog,'Done'));
          assert.equal(state.library,null);old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_every_actual_meta11_fact_and_exact_combined_action_must_confirm_the_receipt(self):
        self.run_js(r'''
          const p=recordPreview(['owner','kind','quantity']),missing=recordSaved(p);delete missing.restored.quantity;
          const bad=[{restored:missing.restored},{restored:{...p.restored,quantity:100}},{restored:{...p.restored,image:''}},
            ...ACTIVITY_UNDO_ACCESSORY_QUANTITY_FIELDS.map(field=>({restored:{...p.restored,[field]:'Wrong'}})),
            {action:'accessory_update'},{action:'accessory_stock_update'},{action:'accessory_owner_update'},{action:'accessory_kind_update'},{added_id:p.current.id},{removed_id:p.current.id},
            {record_confirmation_required:true},{profile:state.profiles[0].id},{space:'home'},{saved:false},{source_id:43},
            {expect:'f'.repeat(64)},{sha256:'bad'},{revision:'0'},{revision:'9223372036854775808'},{summary:''}];
          for(const extra of bad){const {sheet}=await openRecord(p);confirmRecord(sheet);let writes=0;apiWrite=async()=>{writes++;return recordSaved(p,extra);};
            const old=save(sheet);old.click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));
            assert(recordConsent(sheet).disabled);old.fire('click');assert.equal(writes,1);}
        ''')

    def test_other_actions_and_endpoints_cannot_reuse_combined_consent_or_receipts(self):
        self.run_js(r'''
          assert.equal(activityUndoReceipt(recordSaved(),accPreview()),false);assert.equal(activityUndoReceipt(accSaved(),recordPreview()),false);
          assert.equal(activityUndoEvidence(accPreview({record_confirmation_required:true}),42,'home',state.profiles[0].id),null);
          const foreign=recordPreview(['owner','kind']);foreign.current.owner=state.profiles[1].id;recordFields(foreign);const hidden=await openRecord(foreign);
          assert(!save(hidden.sheet));assert.equal(recordConsent(hidden.sheet),null);assert(!hidden.sheet.body.textContent.includes('Historical <img'));
          const wrong=await open(recordPreview());assert(!save(wrong.sheet));const made=await openRecord();confirmRecord(made.sheet);made.view.undoCtx.endpoint='/api/activity/undo';
          let writes=0;apiWrite=async()=>{writes++;return recordSaved();};save(made.sheet).fire('click');await settle();assert.equal(writes,0);
        ''')

    def test_changed_category_metadata_or_context_cannot_authorize_stale_save(self):
        self.run_js(r'''
          for(const mode of ['kind','quantity','owner','notes','action','profile','route','filter','detached','unchecked','modal']){
            const {sheet,p,view}=await openRecord();confirmRecord(sheet);const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return recordSaved(p);};
            if(mode==='kind')p.restored.kind='playmat';if(mode==='quantity')p.restored.quantity='3';if(mode==='owner')p.restored.owner='shared';if(mode==='notes')p.restored.notes='Later';if(mode==='action')p.action='accessory_update';
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='filter')view.filter.kind='collection';
            if(mode==='detached')recordConsent(sheet).remove();if(mode==='unchecked')recordConsent(sheet).checked=false;if(mode==='modal')top=openSheet('Other task');
            old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();}
        ''')

    def test_unknown_reply_conflict_and_late_foreign_preview_require_reload_without_retry(self):
        self.run_js(r'''
          for(const failure of [Error('Lost reply'),new ApiError(409,'The accessory references changed.',{})]){
            const {sheet}=await openRecord();confirmRecord(sheet);let writes=0;apiWrite=async()=>{writes++;throw failure;};const old=save(sheet);old.click();await settle();
            assert(button(sheet.dialog,'Reload Activity'));assert(!button(sheet.dialog,'Done'));assert(recordConsent(sheet).disabled);old.fire('click');assert.equal(writes,1);}
          const made=mount([accChange()]);let finish;api=()=>new Promise(done=>finish=done);made.trigger.click();const sheet=[...colSheets].at(-1);
          state.profile=state.profiles[1];finish(recordPreview());await settle();assert.equal(recordConsent(sheet),null);assert(!sheet.body.textContent.includes('Historical <img'));
        ''')

    def test_saved_record_keeps_original_activity_filter_and_loaded_page_depth(self):
        self.run_js(r'''
          const filter={kind:'sleeves',actor:state.profiles[0].id},{view,trigger}=mount([accChange(42),accChange(41,false)],41,filter);
          api=async()=>page([accChange(40,false),accChange(39,false)],39);view.older.click();await settle();const p=recordPreview();api=async()=>p;trigger.click();await settle();
          const sheet=[...colSheets].at(-1);confirmRecord(sheet);apiWrite=async()=>recordSaved(p);save(sheet).click();await settle();const asked=[];
          api=async path=>{asked.push(path);return asked.length===1?page([accChange(43,false),accChange(42,false)],42):page([accChange(41,false),accChange(40,false)],40);};
          button(sheet.dialog,'Done').click();await settle();same(asked,['/api/activity?kind=sleeves&actor='+filter.actor,'/api/activity?before=42&kind=sleeves&actor='+filter.actor]);
          assert.equal(view.loadedPages,2);assert.equal(view.shown,4);assert(view.days.querySelector('[data-activity-id="42"]'));assert.equal(location.hash,activityHref(filter));
        ''')
