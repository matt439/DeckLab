"""Mine/Shared corrections require explicit access consent, never stock consent."""
import unittest

from decklab.tests import test_activity_accessory_undo_ui as accessories
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class AccessoryOwnerUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        accessories.AccessoryUndoUiTests.run_js(self, r'''
          const ownerPreview=(extra={})=>{const current={...accRow(),quantity:'2'},restored={...current,owner:'shared',notes:'Historical <img src=x onerror=alert(1)>'};
            return{available:true,id:42,expect:'a'.repeat(64),kind:'accessory',action:'accessory_owner_update',label:current.name,current,restored,
              fields:['owner','notes'].map(field=>({field,before:current[field],after:restored[field]})),owner_confirmation_required:true,...extra};};
          const ownerSaved=(p=ownerPreview(),extra={})=>({saved:true,source_id:p.id,expect:p.expect,kind:'accessory',action:'accessory_owner_update',
            restored:{...p.restored},sha256:'b'.repeat(64),revision:'4321',summary:'Restored the recorded accessory owner.',...extra});
          const openOwner=async(p=ownerPreview())=>{const made=mount([accChange()],null,{kind:'sleeves',actor:null});api=async()=>p;
            made.trigger.click();await settle();return{...made,sheet:[...colSheets].at(-1),p};};
          const ownerConsent=sheet=>sheet.body.querySelector('input[type=checkbox]');
          const confirmOwner=(sheet,value=true)=>{const input=ownerConsent(sheet);input.checked=value;input.fire('change');return input;};
        ''' + scenario)

    def test_both_owner_directions_review_access_and_unchanged_count_for_each_kind(self):
        self.run_js(r'''
          for(const kind of ['sleeves','deck_box','playmat'])for(const shared of [true,false])for(const quantity of ['0','1','9999']){
            const p=ownerPreview();p.current.kind=p.restored.kind=kind;p.current.quantity=p.restored.quantity=quantity;
            p.current.owner=shared?state.profiles[0].id:'shared';p.restored.owner=shared?'shared':state.profiles[0].id;
            p.fields[0]={field:'owner',before:p.current.owner,after:p.restored.owner};const {sheet}=await openOwner(p),text=sheet.body.textContent;
            for(const words of ['Current','Restored by Undo','Whose:','Mine ('+state.profile.name+')','Shared (both people at home)',
              'Both people at home can see and change Shared accessories','only you can change Mine',"destination owner's existing Public/Private kit setting",
              'Undo does not change that setting','Recorded quantity stays at '+quantity,'Current photos and kit assignments stay as they are',
              'Only an unused record can change owner here','references are checked again','Historical <img src=x onerror=alert(1)>'])assert(text.includes(words),words);
            assert(text.includes(kind==='sleeves'?'individual sleeve':'item'));assert(!text.includes('still physically owned'));
            assert(!text.includes('whole recorded count, not an additional quantity'));assert(!text.includes('Reason for removing'));
            assert.equal(sheet.body.querySelectorAll('input').length,1);assert.equal(sheet.body.querySelector('input[type=number],input[type=text],textarea,select,img,a'),null);
            assert.equal(ownerConsent(sheet).checked,false);assert(save(sheet).disabled);
          }
        ''')

    def test_owner_protocol_requires_exact_meta11_actual_owner_difference_and_immutable_stock(self):
        self.run_js(r'''
          const p=ownerPreview(),bad=[{owner_confirmation_required:false},{owner_confirmation_required:undefined},{owner_confirmation_required:1},
            {stock_confirmation_required:true},{confirmation_required:true},{reason_required:true},{physical_confirmation_required:true},
            {action:'accessory_update'},{action:'accessory_stock_update'},{action:'accessory_add'},{space:'home'},{profile:state.profiles[0].id},
            {restored:{...p.restored,owner:p.current.owner},fields:[p.fields[1]]},{restored:{...p.restored,quantity:'1'}},
            {restored:{...p.restored,kind:'sleeves'}},{restored:{...p.restored,id:'another-id'}},{restored:{...p.restored,image:'fixture.jpg'}},
            {current:{...p.current,crop:''}},{current:accRow()},{restored:accRow()},{fields:[p.fields[1]]},
            {fields:[...p.fields,p.fields[0]]},{fields:[{field:'owner',before:'Wrong',after:'shared'},p.fields[1]]}];
          for(const extra of bad){const {sheet}=await openOwner(ownerPreview(extra));assert(!save(sheet),JSON.stringify(extra));assert.equal(ownerConsent(sheet),null);}
          const stock=ownerPreview();stock.restored.quantity='1';stock.fields.push({field:'quantity',before:'2',after:'1'});
          assert.equal(activityUndoEvidence(stock,42,'home',state.profiles[0].id),null);
        ''')

    def test_both_owners_must_be_the_viewer_and_shared_with_no_public_or_other_owner_override(self):
        self.run_js(r'''
          const foreign=state.profiles[1].id;
          for(const [current,restored] of [[foreign,'shared'],['shared',foreign],[state.profiles[0].id,foreign],['user2','shared'],['shared','orphan']]){
            const p=ownerPreview();p.current.owner=current;p.restored.owner=restored;p.fields[0]={field:'owner',before:current,after:restored};
            const {sheet}=await openOwner(p);assert(!save(sheet));assert.equal(ownerConsent(sheet),null);assert(!sheet.body.textContent.includes('Historical <img'));
          }
          assert.equal(activityUndoEvidence(ownerPreview(),42,'user2',state.profiles[0].id),null);
          assert.equal(activityUndoEvidence(ownerPreview(),42,'home',null),null);
        ''')

    def test_unchanged_quantity_and_capacity_remain_canonical_on_both_sides(self):
        self.run_js(r'''
          for(const quantity of [0,null,'','00','01','-1','10000','1\n','1\r','1\u2028','1\u2029']){
            const p=ownerPreview();p.current.quantity=p.restored.quantity=quantity;assert.equal(activityUndoEvidence(p,42,'home',state.profiles[0].id),null);}
          for(const side of ['current','restored'])for(const capacity of ['0','0100','100\n','100\r','100\u2028','100\u2029']){
            const p=ownerPreview();p[side].capacity=capacity;p.fields.push({field:'capacity',before:p.current.capacity,after:p.restored.capacity});
            assert.equal(activityUndoEvidence(p,42,'home',state.profiles[0].id),null);}
        ''')

    def test_mixed_details_and_recorded_capacity_are_literal_and_do_not_add_stock_consent(self):
        self.run_js(r'''
          const p=ownerPreview();p.current.capacity='100';p.restored.capacity='40';p.restored.link='https://example.com/<literal>';
          p.fields.push({field:'capacity',before:'100',after:'40'},{field:'link',before:p.current.link,after:p.restored.link});
          const {sheet}=await openOwner(p),text=sheet.body.textContent;assert(text.includes('Box capacity (sleeved cards): 40'));
          assert(text.includes(p.restored.link));assert(text.includes('Fit warnings may change; kit assignments stay as they are'));
          assert.equal(sheet.body.querySelector('img,a'),null);assert.equal(sheet.body.querySelectorAll('input').length,1);assert(!text.includes('still physically owned'));
        ''')

    def test_consent_must_be_explicit_and_is_not_reused_after_uncheck_or_cancel(self):
        self.run_js(r'''
          const {sheet}=await openOwner();let writes=0;apiWrite=async()=>{writes++;return ownerSaved();};save(sheet).fire('click');await settle();assert.equal(writes,0);
          ownerConsent(sheet).checked=true;save(sheet).fire('click');await settle();assert.equal(writes,0);
          confirmOwner(sheet);assert(!save(sheet).disabled);confirmOwner(sheet,false);assert(save(sheet).disabled);confirmOwner(sheet);
          button(sheet.dialog,'Cancel').click();const again=await openOwner();assert.equal(ownerConsent(again.sheet).checked,false);assert(save(again.sheet).disabled);
        ''')

    def test_one_pending_save_sends_only_source_expect_and_owner_confirmation(self):
        self.run_js(r'''
          const {sheet,p}=await openOwner(),input=confirmOwner(sheet),old=save(sheet);let finish;const sent=[];
          apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};state.library={old:true};old.click();old.fire('click');
          same(sent,[['/api/activity/accessory-undo',{id:42,expect:'a'.repeat(64),confirm_owner:true}]]);assert(input.disabled);
          input.checked=false;input.fire('change');assert(input.checked);finish(ownerSaved(p));await settle();assert(button(sheet.dialog,'Done'));
          assert.equal(state.library,null);old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_actual_owner_and_every_unchanged_meta11_fact_must_match_the_exact_receipt(self):
        self.run_js(r'''
          const p=ownerPreview(),missing=ownerSaved(p);delete missing.restored.quantity;
          const bad=[{restored:missing.restored},{restored:{...p.restored,quantity:2}},{restored:{...p.restored,image:''}},
            ...ACTIVITY_UNDO_ACCESSORY_QUANTITY_FIELDS.map(field=>({restored:{...p.restored,[field]:'Wrong'}})),
            {action:'accessory_update'},{action:'accessory_stock_update'},{action:'accessory_add'},{added_id:p.current.id},{removed_id:p.current.id},
            {owner_confirmation_required:true},{profile:state.profiles[0].id},{space:'home'},{saved:false},{source_id:43},
            {expect:'f'.repeat(64)},{sha256:'bad'},{revision:'0'},{revision:'9223372036854775808'},{summary:''}];
          for(const extra of bad){const {sheet}=await openOwner(p);confirmOwner(sheet);let writes=0;apiWrite=async()=>{writes++;return ownerSaved(p,extra);};
            const old=save(sheet);old.click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));
            assert(ownerConsent(sheet).disabled);old.fire('click');assert.equal(writes,1);}
        ''')

    def test_other_action_protocols_cannot_accept_owner_flags_or_receipts_or_change_endpoint(self):
        self.run_js(r'''
          assert.equal(activityUndoReceipt(ownerSaved(),accPreview()),false);assert.equal(activityUndoReceipt(accSaved(),ownerPreview()),false);
          const metadata=accPreview({owner_confirmation_required:true});assert.equal(activityUndoEvidence(metadata,42,'home',state.profiles[0].id),null);
          const stock={...ownerPreview(),action:'accessory_stock_update',stock_confirmation_required:true};delete stock.owner_confirmation_required;
          assert.equal(activityUndoEvidence(stock,42,'home',state.profiles[0].id),null);assert.equal(activityUndoReceipt(ownerSaved(),stock),false);
          const wrong=await open(ownerPreview());assert(!save(wrong.sheet));const made=await openOwner();confirmOwner(made.sheet);made.view.undoCtx.endpoint='/api/activity/undo';
          let writes=0;apiWrite=async()=>{writes++;return ownerSaved();};save(made.sheet).fire('click');await settle();assert.equal(writes,0);
        ''')

    def test_changed_owner_count_context_or_detached_consent_cannot_authorize_save(self):
        self.run_js(r'''
          for(const mode of ['owner','quantity','notes','action','profile','route','filter','detached','unchecked','modal']){
            const {sheet,p,view}=await openOwner();confirmOwner(sheet);const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return ownerSaved(p);};
            if(mode==='owner')p.restored.owner=state.profiles[0].id;if(mode==='quantity')p.restored.quantity='3';if(mode==='notes')p.restored.notes='Later';if(mode==='action')p.action='accessory_update';
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='filter')view.filter.kind='collection';
            if(mode==='detached')ownerConsent(sheet).remove();if(mode==='unchecked')ownerConsent(sheet).checked=false;if(mode==='modal')top=openSheet('Other task');
            old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();}
        ''')

    def test_conflict_lost_reply_and_late_foreign_preview_require_reload_without_retry(self):
        self.run_js(r'''
          for(const failure of [Error('Lost reply'),new ApiError(409,'The accessory references changed.',{})]){
            const {sheet}=await openOwner();confirmOwner(sheet);let writes=0;apiWrite=async()=>{writes++;throw failure;};const old=save(sheet);old.click();await settle();
            assert(button(sheet.dialog,'Reload Activity'));assert(!button(sheet.dialog,'Done'));assert(ownerConsent(sheet).disabled);old.fire('click');assert.equal(writes,1);}
          const made=mount([accChange()]);let finish;api=()=>new Promise(done=>finish=done);made.trigger.click();const sheet=[...colSheets].at(-1);
          state.profile=state.profiles[1];finish(ownerPreview());await settle();assert.equal(ownerConsent(sheet),null);assert(!sheet.body.textContent.includes('Historical <img'));
        ''')

    def test_saved_owner_keeps_original_history_filter_and_loaded_depth(self):
        self.run_js(r'''
          const filter={kind:'sleeves',actor:state.profiles[0].id},{view,trigger}=mount([accChange(42),accChange(41,false)],41,filter);
          api=async()=>page([accChange(40,false),accChange(39,false)],39);view.older.click();await settle();const p=ownerPreview();api=async()=>p;trigger.click();await settle();
          const sheet=[...colSheets].at(-1);confirmOwner(sheet);apiWrite=async()=>ownerSaved(p);save(sheet).click();await settle();const asked=[];
          api=async path=>{asked.push(path);return asked.length===1?page([accChange(43,false),accChange(42,false)],42):page([accChange(41,false),accChange(40,false)],40);};
          button(sheet.dialog,'Done').click();await settle();same(asked,['/api/activity?kind=sleeves&actor='+filter.actor,'/api/activity?before=42&kind=sleeves&actor='+filter.actor]);
          assert.equal(view.loadedPages,2);assert.equal(view.shown,4);assert(view.days.querySelector('[data-activity-id="42"]'));assert.equal(location.hash,activityHref(filter));
        ''')
