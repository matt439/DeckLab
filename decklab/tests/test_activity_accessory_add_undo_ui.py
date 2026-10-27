"""Exact historical accessory restoration needs explicit whole-record consent."""
import unittest

from decklab.tests import test_activity_accessory_undo_ui as accessories
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class AccessoryAddUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        accessories.AccessoryUndoUiTests.run_js(self, r'''
          const addPreview=(extra={})=>{const restored={...accRow({name:'Historical fixture box',notes:'Historical <img src=x onerror=alert(1)>'}),quantity:'2',capacity:'100',image:'',crop:''};
            return{available:true,id:42,expect:'a'.repeat(64),kind:'accessory',action:'accessory_add',label:restored.name,
              current:null,restored,confirmation_required:true,...extra};};
          const addSaved=(p=addPreview(),extra={})=>({saved:true,source_id:p.id,expect:p.expect,kind:'accessory',action:'accessory_add',
            restored:{...p.restored},added_id:p.restored.id,sha256:'b'.repeat(64),revision:'4321',summary:'Restored the historical accessory record.',...extra});
          const addChange=(id=42,hint=true)=>({...accChange(id,hint),rows:[{table:'accessory',op:'DELETE',summary:'Removed fixture accessory'}]});
          const openAdd=async(p=addPreview())=>{const made=mount([addChange()],null,{kind:'sleeves',actor:null});api=async()=>p;
            made.trigger.click();await settle();return{...made,sheet:[...colSheets].at(-1),p};};
          const consent=sheet=>sheet.body.querySelector('input[type=checkbox]');
          const agree=(sheet,value=true)=>{const input=consent(sheet);input.checked=value;input.fire('change');return input;};
        ''' + scenario)

    def test_positive_stock_reviews_full_history_and_additive_physical_ownership_without_photo_or_kit_recovery(self):
        self.run_js(r'''
          const {sheet,p}=await openAdd(),text=sheet.body.textContent;
          for(const word of ['all 2 items','in addition to the quantities already recorded','Historical accessory record to restore','Historical fixture box',
            p.restored.id,'Deck box','Box capacity','100',p.restored.link,p.restored.image_source,'No photo or kit assignments are restored',
            'no photo is recovered','If you own fewer','Historical <img src=x onerror=alert(1)>'])assert(text.includes(word),word);
          assert.equal(sheet.body.querySelectorAll('input').length,1);assert.equal(sheet.body.querySelector('input[type=number],input[type=text],a,img,textarea,select'),null);
          assert.equal(consent(sheet).checked,false);assert(save(sheet).disabled);assert(!text.includes('Reason for removing'));assert(!text.includes('Current row to remove'));
        ''')

    def test_zero_quantity_confirms_reference_record_intent_without_owned_stock_increase_claim(self):
        self.run_js(r'''
          const p=addPreview();Object.assign(p.restored,{kind:'playmat',quantity:'0',capacity:''});const {sheet}=await openAdd(p),text=sheet.body.textContent;
          for(const word of ['zero-quantity reference record','No owned items are added','I confirm this zero-quantity accessory record should be restored','Playmat'])assert(text.includes(word),word);
          assert(!text.includes('all 0'));assert(!text.includes('physically owned'));assert(save(sheet).disabled);let writes=0;apiWrite=async()=>{writes++;return addSaved(p);};
          save(sheet).fire('click');await settle();assert.equal(writes,0);assert(sheet.body.textContent.includes('Review and confirm this historical accessory record'));
          assert(!sheet.body.textContent.includes('physically owned'));agree(sheet);assert(!save(sheet).disabled);
        ''')

    def test_exact_add_protocol_and_full13_canonical_history_are_required_before_consent_is_shown(self):
        self.run_js(r'''
          const p=addPreview(),bad=[{confirmation_required:false},{confirmation_required:undefined},{physical_confirmation_required:true},{reason_required:true},{fields:[]},
            {current:{}},{current:p.restored},{restored:accRow()},{space:'home'},{profile:state.profiles[0].id},{action:'add'},{action:'accessory_update'},
            ...[2,'-1','02','10000',' 2','2\n'].map(quantity=>({restored:{...p.restored,quantity}})),
            {restored:{...p.restored,capacity:'0'}},{restored:{...p.restored,kind:'sleeves',capacity:'100'}},{restored:{...p.restored,image:'fixture.jpg'}},
            {restored:{...p.restored,crop:'0,0,1,1'}},{restored:{...p.restored,owner:state.profiles[1].id}},{restored:{...p.restored,link:'javascript:alert(1)'}}];
          for(const extra of bad){const {sheet}=await openAdd(addPreview(extra));assert(!save(sheet),JSON.stringify(extra));assert.equal(consent(sheet),null);}
        ''')

    def test_consent_check_uncheck_and_cancel_reopen_never_authorize_an_implicit_restore(self):
        self.run_js(r'''
          const {sheet}=await openAdd();let writes=0;apiWrite=async()=>{writes++;return addSaved();};save(sheet).fire('click');await settle();assert.equal(writes,0);
          agree(sheet);assert(!save(sheet).disabled);agree(sheet,false);assert(save(sheet).disabled);consent(sheet).checked=true;save(sheet).fire('click');await settle();assert.equal(writes,0);
          agree(sheet);button(sheet.dialog,'Cancel').click();const again=await openAdd();assert.equal(consent(again.sheet).checked,false);assert(save(again.sheet).disabled);
        ''')

    def test_positive_and_zero_restore_send_only_one_explicit_source_confirmation(self):
        self.run_js(r'''
          for(const quantity of ['2','0']){const p=addPreview();p.restored.quantity=quantity;const {sheet}=await openAdd(p);const input=agree(sheet),old=save(sheet);let finish;const sent=[];
            apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};state.library={sentinel:true};old.click();old.fire('click');
            same(sent,[['/api/activity/accessory-undo',{id:42,expect:'a'.repeat(64),confirm_restore:true}]]);assert(input.disabled);input.checked=false;input.fire('change');assert(input.checked);
            finish(addSaved(p));await settle();assert(button(sheet.dialog,'Done'));assert.equal(state.library,null);old.fire('click');assert.equal(sent.length,1);}
        ''')

    def test_actual_added_id_and_every_historical_raw_cell_must_match_exact_receipt(self):
        self.run_js(r'''
          const p=addPreview(),bad=[{added_id:'another-id'},{added_id:undefined},{removed_id:p.restored.id},{restored:null},{restored:accRow()},
            ...['id','owner','name','quantity','capacity','link','image_source','notes','image','crop'].map(field=>({restored:{...p.restored,[field]:'Wrong'}})),
            {action:'accessory_remove'},{action:'accessory_update'},{profile:state.profiles[0].id},{space:'home'},{saved:false},{source_id:43},
            {expect:'f'.repeat(64)},{sha256:'bad'},{revision:'0'},{revision:'9223372036854775808'},{summary:''}];
          for(const extra of bad){const {sheet}=await openAdd(p);agree(sheet);let writes=0;apiWrite=async()=>{writes++;return addSaved(p,extra);};const old=save(sheet);old.click();await settle();
            assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));assert(consent(sheet).disabled);old.fire('click');assert.equal(writes,1);}
        ''')

    def test_other_protocols_cannot_accept_add_receipts_or_redirect_the_save(self):
        self.run_js(r'''
          assert.equal(activityUndoReceipt(addSaved(),accPreview()),false);assert.equal(activityUndoReceipt(accSaved(),addPreview()),false);
          const wrong=await open(addPreview());assert(!save(wrong.sheet));const made=await openAdd();agree(made.sheet);made.view.undoCtx.endpoint='/api/activity/undo';let writes=0;
          apiWrite=async()=>{writes++;return addSaved();};save(made.sheet).fire('click');await settle();assert.equal(writes,0);
        ''')

    def test_stale_history_consent_context_and_modal_cannot_authorize_save(self):
        self.run_js(r'''
          for(const mode of ['quantity','id','owner','link','action','profile','route','filter','detached','unchecked','modal']){
            const {sheet,p,view}=await openAdd();agree(sheet);const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return addSaved(p);};
            if(mode==='quantity')p.restored.quantity='3';if(mode==='id')p.restored.id='another-id';if(mode==='owner')p.restored.owner='shared';if(mode==='link')p.restored.link+='/later';if(mode==='action')p.action='accessory_remove';
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='filter')view.filter.kind='collection';if(mode==='detached')consent(sheet).remove();if(mode==='unchecked')consent(sheet).checked=false;if(mode==='modal')top=openSheet('Other task');
            old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();
          }
        ''')

    def test_conflict_unknown_reply_and_late_owner_cannot_confirm_retry_or_reveal_history(self):
        self.run_js(r'''
          for(const failure of [Error('Lost reply'),new ApiError(409,'This historical record cannot be restored exactly.',{})]){
            const {sheet}=await openAdd();agree(sheet);let writes=0;apiWrite=async()=>{writes++;throw failure;};const old=save(sheet);old.click();await settle();
            assert(button(sheet.dialog,'Reload Activity'));assert(!button(sheet.dialog,'Done'));assert(consent(sheet).disabled);old.fire('click');assert.equal(writes,1);}
          const made=mount([addChange()]);let finish;api=()=>new Promise(done=>finish=done);made.trigger.click();const sheet=[...colSheets].at(-1);state.profile=state.profiles[1];finish(addPreview());await settle();
          assert.equal(consent(sheet),null);assert(!sheet.body.textContent.includes('Historical fixture box'));
        ''')

    def test_done_keeps_filter_loaded_depth_and_original_deletion_history(self):
        self.run_js(r'''
          const filter={kind:'sleeves',actor:state.profiles[0].id},{view,trigger}=mount([addChange(42),addChange(41,false)],41,filter);
          api=async()=>page([addChange(40,false),addChange(39,false)],39);view.older.click();await settle();const p=addPreview();api=async()=>p;trigger.click();await settle();
          const sheet=[...colSheets].at(-1);agree(sheet);apiWrite=async()=>addSaved(p);save(sheet).click();await settle();const asked=[];
          api=async path=>{asked.push(path);return asked.length===1?page([addChange(43,false),addChange(42,false)],42):page([addChange(41,false),addChange(40,false)],40);};
          button(sheet.dialog,'Done').click();await settle();same(asked,['/api/activity?kind=sleeves&actor='+filter.actor,'/api/activity?before=42&kind=sleeves&actor='+filter.actor]);
          assert.equal(view.loadedPages,2);assert.equal(view.shown,4);assert(view.days.querySelector('[data-activity-id="42"]'));assert.equal(location.hash,activityHref(filter));
        ''')
