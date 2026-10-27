"""Recorded accessory count corrections require explicit whole-count consent."""
import unittest

from decklab.tests import test_activity_accessory_undo_ui as accessories
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class AccessoryQuantityUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        accessories.AccessoryUndoUiTests.run_js(self, r'''
          const stockPreview=(extra={})=>{const current={...accRow(),quantity:'100'},restored={...current,quantity:'40',notes:'Historical <img src=x onerror=alert(1)>'};
            return{available:true,id:42,expect:'a'.repeat(64),kind:'accessory',action:'accessory_stock_update',label:current.name,current,restored,
              fields:['notes','quantity'].map(field=>({field,before:current[field],after:restored[field]})),stock_confirmation_required:true,...extra};};
          const stockSaved=(p=stockPreview(),extra={})=>({saved:true,source_id:p.id,expect:p.expect,kind:'accessory',action:'accessory_stock_update',
            restored:{...p.restored},sha256:'b'.repeat(64),revision:'4321',summary:'Restored the recorded accessory quantity.',...extra});
          const openStock=async(p=stockPreview())=>{const made=mount([accChange()],null,{kind:'sleeves',actor:null});api=async()=>p;
            made.trigger.click();await settle();return{...made,sheet:[...colSheets].at(-1),p};};
          const stockConsent=sheet=>sheet.body.querySelector('input[type=checkbox]');
          const confirmStock=(sheet,value=true)=>{const input=stockConsent(sheet);input.checked=value;input.fire('change');return input;};
        ''' + scenario)

    def test_review_replaces_the_whole_count_with_kind_units_and_keeps_photo_and_kit(self):
        self.run_js(r'''
          for(const kind of ['sleeves','deck_box','playmat'])for(const quantity of ['1','40','9999']){
            const p=stockPreview();p.current.kind=p.restored.kind=kind;p.restored.quantity=quantity;p.fields.at(-1).after=quantity;
            const {sheet}=await openStock(p),text=sheet.body.textContent,units=kind==='sleeves'?'individual sleeves':'items';
            for(const words of ['Current','Restored by Undo','Recorded quantity ('+units+'):',quantity,'whole recorded count, not an additional quantity',
              'Sleeve shortages and box availability warnings may change','photos and kit assignments stay as they are','retains the current photo and kit',
              'still physically owned','loose ones included','If the count differs','Historical <img src=x onerror=alert(1)>'])assert(text.includes(words),words);
            assert.equal(sheet.body.querySelectorAll('input').length,1);assert.equal(sheet.body.querySelector('input[type=number],input[type=text],textarea,select,img,a'),null);
            assert.equal(stockConsent(sheet).checked,false);assert(save(sheet).disabled);assert(!text.includes('in addition to the quantities already recorded'));
            assert(!text.includes('Reason for removing'));assert(!text.includes('No photo or kit assignments are restored'));
          }
        ''')

    def test_zero_keeps_a_reference_record_and_requires_explicit_zero_count_confirmation(self):
        self.run_js(r'''
          const p=stockPreview();p.restored.quantity='0';p.fields.at(-1).after='0';const {sheet}=await openStock(p),text=sheet.body.textContent;
          for(const words of ['zero-quantity reference record is kept','No owned items are added','I confirm this accessory record should show zero owned items'])assert(text.includes(words),words);
          assert(!text.includes('all 0'));assert(!text.includes('still physically owned'));assert(save(sheet).disabled);let writes=0;
          apiWrite=async()=>{writes++;return stockSaved(p);};save(sheet).fire('click');await settle();assert.equal(writes,0);
          confirmStock(sheet);save(sheet).click();await settle();assert.equal(writes,1);assert(button(sheet.dialog,'Done'));
        ''')

    def test_exact_meta11_and_action_specific_confirmation_require_a_real_quantity_change(self):
        self.run_js(r'''
          const p=stockPreview(),bad=[{stock_confirmation_required:false},{stock_confirmation_required:null},{stock_confirmation_required:1},
            {stock_confirmation_required:undefined},{confirmation_required:true},{reason_required:true},{physical_confirmation_required:true},
            {action:'accessory_update'},{action:'accessory_add'},{action:'accessory_remove'},{space:'home'},{profile:state.profiles[0].id},
            {restored:{...p.restored,image:'fixture.jpg'}},{current:{...p.current,crop:''}},{restored:accRow()},
            {restored:{...p.restored,id:'another-id'}},{restored:{...p.restored,owner:'shared'}},{restored:{...p.restored,kind:'sleeves'}},
            {restored:{...p.restored,quantity:p.current.quantity},fields:[p.fields[0]]},
            {fields:[p.fields[0]]},{fields:[...p.fields,p.fields[1]]},{fields:[p.fields[0],{field:'quantity',before:'999',after:'40'}]}];
          for(const extra of bad){const {sheet}=await openStock(stockPreview(extra));assert(!save(sheet),JSON.stringify(extra));assert.equal(stockConsent(sheet),null);}
        ''')

    def test_quantities_require_canonical_text_on_both_sides_including_true_string_end(self):
        self.run_js(r'''
          for(const side of ['current','restored'])for(const quantity of ['0','1','9999']){
            const p=stockPreview();p[side].quantity=quantity;p.fields[p.fields.length-1]={field:'quantity',before:p.current.quantity,after:p.restored.quantity};
            assert(activityUndoEvidence(p,42,'home',state.profiles[0].id));}
          for(const side of ['current','restored'])for(const quantity of [0,1,null,'','00','01','-1','1.0',' 1','1 ','10000','1\n','1\r','1\r\n','1\u2028','1\u2029']){
            const p=stockPreview();p[side].quantity=quantity;p.fields[p.fields.length-1]={field:'quantity',before:p.current.quantity,after:p.restored.quantity};
            assert.equal(activityUndoEvidence(p,42,'home',state.profiles[0].id),null,side+':'+quantity);
            const row={...accRow(),quantity,capacity:'100',image:'',crop:''};assert.equal(activityUndoAccessoryStock(row),false);}
          for(const capacity of ['100\n','100\r','100\u2028','100\u2029']){const p=stockPreview();p.current.capacity=p.restored.capacity=capacity;
            assert.equal(activityUndoEvidence(p,42,'home',state.profiles[0].id),null);}
        ''')

    def test_mixed_details_and_capacity_remain_literal_with_only_one_count_confirmation(self):
        self.run_js(r'''
          const p=stockPreview();p.current.capacity='100';p.restored.capacity='40';p.restored.link='https://example.com/<literal>';
          p.fields.push({field:'capacity',before:'100',after:'40'},{field:'link',before:p.current.link,after:p.restored.link});
          const {sheet}=await openStock(p),text=sheet.body.textContent;assert(text.includes('Box capacity (sleeved cards): 40'));
          assert(text.includes(p.restored.link));assert(text.includes('Fit warnings may change; kit assignments stay as they are'));
          assert.equal(sheet.body.querySelector('a,img'),null);assert.equal(sheet.body.querySelectorAll('input[type=checkbox]').length,1);
          confirmStock(sheet);let sent;apiWrite=async(path,body)=>{sent=[path,body];return stockSaved(p);};save(sheet).click();await settle();
          same(sent,['/api/activity/accessory-undo',{id:42,expect:'a'.repeat(64),confirm_stock:true}]);assert(button(sheet.dialog,'Done'));
        ''')

    def test_consent_cannot_be_inferred_from_checkbox_state_and_resets_after_cancel(self):
        self.run_js(r'''
          const {sheet}=await openStock();let writes=0;apiWrite=async()=>{writes++;return stockSaved();};save(sheet).fire('click');await settle();assert.equal(writes,0);
          stockConsent(sheet).checked=true;save(sheet).fire('click');await settle();assert.equal(writes,0);
          confirmStock(sheet);assert(!save(sheet).disabled);confirmStock(sheet,false);assert(save(sheet).disabled);confirmStock(sheet);
          button(sheet.dialog,'Cancel').click();const again=await openStock();assert.equal(stockConsent(again.sheet).checked,false);assert(save(again.sheet).disabled);
        ''')

    def test_one_pending_source_request_never_sends_count_or_metadata_or_other_action_flags(self):
        self.run_js(r'''
          for(const quantity of ['40','0']){const p=stockPreview();p.restored.quantity=quantity;p.fields.at(-1).after=quantity;
            const {sheet}=await openStock(p),input=confirmStock(sheet),old=save(sheet);let finish;const sent=[];
            apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};state.library={old:true};old.click();old.fire('click');
            same(sent,[['/api/activity/accessory-undo',{id:42,expect:'a'.repeat(64),confirm_stock:true}]]);assert(input.disabled);
            input.checked=false;input.fire('change');assert(input.checked);finish(stockSaved(p));await settle();assert(button(sheet.dialog,'Done'));
            assert.equal(state.library,null);old.fire('click');assert.equal(sent.length,1);}
        ''')

    def test_every_meta11_cell_and_exact_action_receipt_must_confirm_the_saved_count(self):
        self.run_js(r'''
          const p=stockPreview(),missing=stockSaved(p);delete missing.restored.quantity;
          const bad=[{restored:missing.restored},{restored:{...p.restored,quantity:40}},{restored:{...p.restored,image:''}},
            ...ACTIVITY_UNDO_ACCESSORY_QUANTITY_FIELDS.map(field=>({restored:{...p.restored,[field]:'Wrong'}})),
            {action:'accessory_update'},{action:'accessory_add'},{action:'accessory_remove'},{added_id:p.current.id},{removed_id:p.current.id},
            {stock_confirmation_required:true},{profile:state.profiles[0].id},{space:'home'},{saved:false},{source_id:43},
            {expect:'f'.repeat(64)},{sha256:'bad'},{revision:'0'},{revision:'9223372036854775808'},{summary:''}];
          for(const extra of bad){const {sheet}=await openStock(p);confirmStock(sheet);let writes=0;apiWrite=async()=>{writes++;return stockSaved(p,extra);};
            const old=save(sheet);old.click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));
            assert(stockConsent(sheet).disabled);old.fire('click');assert.equal(writes,1);}
        ''')

    def test_other_protocols_owners_and_endpoints_cannot_reuse_stock_consent_or_receipts(self):
        self.run_js(r'''
          assert.equal(activityUndoReceipt(stockSaved(),accPreview()),false);assert.equal(activityUndoReceipt(accSaved(),stockPreview()),false);
          const metadata=accPreview({stock_confirmation_required:true});assert.equal(activityUndoEvidence(metadata,42,'home',state.profiles[0].id),null);
          const foreign=stockPreview();foreign.current.owner=foreign.restored.owner=state.profiles[1].id;const hidden=await openStock(foreign);
          assert(!save(hidden.sheet));assert.equal(stockConsent(hidden.sheet),null);assert(!hidden.sheet.body.textContent.includes('Historical <img'));
          const wrong=await open(stockPreview());assert(!save(wrong.sheet));const made=await openStock();confirmStock(made.sheet);made.view.undoCtx.endpoint='/api/activity/undo';
          let writes=0;apiWrite=async()=>{writes++;return stockSaved();};save(made.sheet).fire('click');await settle();assert.equal(writes,0);
        ''')

    def test_changed_preview_owner_filter_route_or_detached_consent_cannot_save(self):
        self.run_js(r'''
          for(const mode of ['quantity','id','notes','action','profile','route','filter','detached','unchecked','modal']){
            const {sheet,p,view}=await openStock();confirmStock(sheet);const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return stockSaved(p);};
            if(mode==='quantity')p.restored.quantity='3';if(mode==='id')p.restored.id='another-id';if(mode==='notes')p.restored.notes='Later';if(mode==='action')p.action='accessory_update';
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='filter')view.filter.kind='collection';
            if(mode==='detached')stockConsent(sheet).remove();if(mode==='unchecked')stockConsent(sheet).checked=false;if(mode==='modal')top=openSheet('Other task');
            old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();}
        ''')

    def test_unknown_reply_blocks_retry_and_late_foreign_preview_does_not_reveal_history(self):
        self.run_js(r'''
          for(const failure of [Error('Lost reply'),new ApiError(409,'The accessory changed.',{})]){
            const {sheet}=await openStock();confirmStock(sheet);let writes=0;apiWrite=async()=>{writes++;throw failure;};const old=save(sheet);old.click();await settle();
            assert(button(sheet.dialog,'Reload Activity'));assert(!button(sheet.dialog,'Done'));assert(stockConsent(sheet).disabled);old.fire('click');assert.equal(writes,1);}
          const made=mount([accChange()]);let finish;api=()=>new Promise(done=>finish=done);made.trigger.click();const sheet=[...colSheets].at(-1);
          state.profile=state.profiles[1];finish(stockPreview());await settle();assert.equal(stockConsent(sheet),null);assert(!sheet.body.textContent.includes('Historical <img'));
        ''')

    def test_saved_count_keeps_the_original_audit_filter_and_loaded_page_depth(self):
        self.run_js(r'''
          const filter={kind:'sleeves',actor:state.profiles[0].id},{view,trigger}=mount([accChange(42),accChange(41,false)],41,filter);
          api=async()=>page([accChange(40,false),accChange(39,false)],39);view.older.click();await settle();const p=stockPreview();api=async()=>p;trigger.click();await settle();
          const sheet=[...colSheets].at(-1);confirmStock(sheet);apiWrite=async()=>stockSaved(p);save(sheet).click();await settle();const asked=[];
          api=async path=>{asked.push(path);return asked.length===1?page([accChange(43,false),accChange(42,false)],42):page([accChange(41,false),accChange(40,false)],40);};
          button(sheet.dialog,'Done').click();await settle();same(asked,['/api/activity?kind=sleeves&actor='+filter.actor,'/api/activity?before=42&kind=sleeves&actor='+filter.actor]);
          assert.equal(view.loadedPages,2);assert.equal(view.shown,4);assert(view.days.querySelector('[data-activity-id="42"]'));assert.equal(location.hash,activityHref(filter));
        ''')
