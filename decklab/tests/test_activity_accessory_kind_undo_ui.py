"""Unused accessory classification recovery reviews kind and both count units."""
import unittest

from decklab.tests import test_activity_accessory_undo_ui as accessories
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class AccessoryKindUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        accessories.AccessoryUndoUiTests.run_js(self, r'''
          const kindPreview=(extra={})=>{const current={...accRow(),kind:'sleeves',capacity:'',quantity:'100'},restored={...current,kind:'deck_box',capacity:'100',notes:'Historical <img src=x onerror=alert(1)>'};
            return{available:true,id:42,expect:'a'.repeat(64),kind:'accessory',action:'accessory_kind_update',label:current.name,current,restored,
              fields:['kind','notes','capacity'].map(field=>({field,before:current[field],after:restored[field]})),kind_confirmation_required:true,...extra};};
          const setKinds=(p,current,restored,quantity='100')=>{Object.assign(p.current,{kind:current,quantity,capacity:current==='deck_box'?'100':''});
            Object.assign(p.restored,{kind:restored,quantity,capacity:restored==='deck_box'?'40':''});
            p.fields=['kind','notes','capacity'].filter(field=>p.current[field]!==p.restored[field]).map(field=>({field,before:p.current[field],after:p.restored[field]}));return p;};
          const kindSaved=(p=kindPreview(),extra={})=>({saved:true,source_id:p.id,expect:p.expect,kind:'accessory',action:'accessory_kind_update',
            restored:{...p.restored},sha256:'b'.repeat(64),revision:'4321',summary:'Restored the recorded accessory kind.',...extra});
          const openKind=async(p=kindPreview())=>{const made=mount([accChange()],null,{kind:'sleeves',actor:null});api=async()=>p;
            made.trigger.click();await settle();return{...made,sheet:[...colSheets].at(-1),p};};
          const kindConsent=sheet=>sheet.body.querySelector('input[type=checkbox]');
          const confirmKind=(sheet,value=true)=>{const input=kindConsent(sheet);input.checked=value;input.fire('change');return input;};
        ''' + scenario)

    def test_all_six_kind_directions_show_friendly_labels_and_each_sides_unchanged_count_units(self):
        self.run_js(r'''
          const labels={sleeves:'Sleeves',deck_box:'Deck box',playmat:'Playmat'};
          for(const current of Object.keys(labels))for(const restored of Object.keys(labels))if(current!==restored)for(const quantity of ['1','100','9999']){
            const p=setKinds(kindPreview(),current,restored,quantity),{sheet}=await openKind(p),text=sheet.body.textContent;
            const units=kind=>kind==='sleeves'?(quantity==='1'?'individual sleeve':'individual sleeves'):(quantity==='1'?'item':'items');
            for(const words of ['Accessory kind: '+labels[current],'Accessory kind: '+labels[restored],
              'Recorded quantity: '+quantity+' '+units(current),'Recorded quantity: '+quantity+' '+units(restored),
              'The number stays '+quantity,'review its units on both sides','Current photos and kit assignments stay as they are',
              'Only an unused record can change kind here','references are checked again','Confirm the kind and whole count',
              'loose ones included','still physically owned','Historical <img src=x onerror=alert(1)>'])assert(text.includes(words),words);
            assert.equal(sheet.body.querySelectorAll('input').length,1);assert.equal(sheet.body.querySelector('input[type=number],input[type=text],select,textarea,img,a'),null);
            assert.equal(kindConsent(sheet).checked,false);assert(save(sheet).disabled);assert(!text.includes('in addition to the quantities already recorded'));
            assert(!text.includes('Reason for removing'));assert(!text.includes('Both people at home can see and change Shared accessories'));
          }
        ''')

    def test_zero_count_keeps_reference_intent_without_claiming_owned_stock(self):
        self.run_js(r'''
          const p=setKinds(kindPreview(),'deck_box','sleeves','0'),{sheet}=await openKind(p),text=sheet.body.textContent;
          for(const words of ['Recorded quantity: 0 items','Recorded quantity: 0 individual sleeves','zero-quantity reference record','No owned items are added',
            'I confirm this zero-quantity reference record should be classified as Sleeves'])assert(text.includes(words),words);
          assert(!text.includes('still physically owned'));assert(save(sheet).disabled);let writes=0;apiWrite=async()=>{writes++;return kindSaved(p);};
          save(sheet).fire('click');await settle();assert.equal(writes,0);confirmKind(sheet);save(sheet).click();await settle();assert.equal(writes,1);assert(button(sheet.dialog,'Done'));
        ''')

    def test_distinct_exact_meta11_protocol_requires_actual_kind_difference_and_no_stock_or_owner_change(self):
        self.run_js(r'''
          const p=kindPreview(),bad=[{kind_confirmation_required:false},{kind_confirmation_required:undefined},{kind_confirmation_required:1},
            {owner_confirmation_required:true},{stock_confirmation_required:true},{confirmation_required:true},{reason_required:true},
            {action:'accessory_update'},{action:'accessory_stock_update'},{action:'accessory_owner_update'},{action:'accessory_add'},
            {space:'home'},{profile:state.profiles[0].id},{restored:{...p.restored,id:'another-id'}},{restored:{...p.restored,owner:'shared'}},
            {restored:{...p.restored,quantity:'40'}},{restored:{...p.restored,image:'fixture.jpg'}},{current:{...p.current,crop:''}},
            {current:accRow()},{restored:accRow()},{fields:[p.fields[1],p.fields[2]]},{fields:[...p.fields,p.fields[0]]}];
          for(const extra of bad){const {sheet}=await openKind(kindPreview(extra));assert(!save(sheet),JSON.stringify(extra));assert.equal(kindConsent(sheet),null);}
          const sameKind=setKinds(kindPreview(),'sleeves','sleeves');assert.equal(activityUndoEvidence(sameKind,42,'home',state.profiles[0].id),null);
          for(const [field,after] of [['quantity','40'],['owner','shared']]){const q=kindPreview();q.restored[field]=after;q.fields.push({field,before:q.current[field],after});
            assert.equal(activityUndoEvidence(q,42,'home',state.profiles[0].id),null);}
        ''')

    def test_kind_count_and_box_capacity_are_canonical_on_both_sides(self):
        self.run_js(r'''
          for(const side of ['current','restored'])for(const kind of ['','box','deck_box\n','Sleeves','__proto__',null]){
            const p=kindPreview();p[side].kind=kind;p.fields[0]={field:'kind',before:p.current.kind,after:p.restored.kind};
            assert.equal(activityUndoEvidence(p,42,'home',state.profiles[0].id),null);}
          for(const quantity of [0,null,'','00','01','-1','10000','1\n','1\r','1\u2028','1\u2029']){const p=kindPreview();p.current.quantity=p.restored.quantity=quantity;
            assert.equal(activityUndoEvidence(p,42,'home',state.profiles[0].id),null);}
          for(const capacity of ['0','0100','100\n','100\r','100\u2028','100\u2029']){const p=kindPreview();p.restored.capacity=capacity;p.fields.at(-1).after=capacity;
            assert.equal(activityUndoEvidence(p,42,'home',state.profiles[0].id),null);}
          const nonbox=kindPreview();nonbox.current.capacity='100';nonbox.fields.at(-1).before='100';assert.equal(activityUndoEvidence(nonbox,42,'home',state.profiles[0].id),null);
        ''')

    def test_mixed_details_box_capacity_and_plain_urls_do_not_add_other_consent_controls(self):
        self.run_js(r'''
          const p=kindPreview();p.restored.link='https://example.com/<literal>';p.fields.push({field:'link',before:p.current.link,after:p.restored.link});
          const {sheet}=await openKind(p),text=sheet.body.textContent;assert(text.includes('Box capacity (sleeved cards): 100'));assert(text.includes(p.restored.link));
          assert(text.includes('A restored image-source URL is not checked against the current photo'));assert.equal(sheet.body.querySelector('img,a'),null);
          assert.equal(sheet.body.querySelectorAll('input').length,1);assert(!text.includes('whole recorded count, not an additional quantity'));
        ''')

    def test_explicit_kind_consent_must_be_reviewed_and_resets_after_cancel(self):
        self.run_js(r'''
          const {sheet}=await openKind();let writes=0;apiWrite=async()=>{writes++;return kindSaved();};save(sheet).fire('click');await settle();assert.equal(writes,0);
          kindConsent(sheet).checked=true;save(sheet).fire('click');await settle();assert.equal(writes,0);confirmKind(sheet);assert(!save(sheet).disabled);
          confirmKind(sheet,false);assert(save(sheet).disabled);confirmKind(sheet);button(sheet.dialog,'Cancel').click();const again=await openKind();
          assert.equal(kindConsent(again.sheet).checked,false);assert(save(again.sheet).disabled);
        ''')

    def test_one_pending_request_sends_source_expect_and_only_kind_confirmation(self):
        self.run_js(r'''
          const {sheet,p}=await openKind(),input=confirmKind(sheet),old=save(sheet);let finish;const sent=[];
          apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};state.library={old:true};old.click();old.fire('click');
          same(sent,[['/api/activity/accessory-undo',{id:42,expect:'a'.repeat(64),confirm_kind:true}]]);assert(input.disabled);
          input.checked=false;input.fire('change');assert(input.checked);finish(kindSaved(p));await settle();assert(button(sheet.dialog,'Done'));
          assert.equal(state.library,null);old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_actual_kind_and_every_other_meta11_fact_must_match_the_saved_receipt(self):
        self.run_js(r'''
          const p=kindPreview(),missing=kindSaved(p);delete missing.restored.quantity;
          const bad=[{restored:missing.restored},{restored:{...p.restored,quantity:100}},{restored:{...p.restored,image:''}},
            ...ACTIVITY_UNDO_ACCESSORY_QUANTITY_FIELDS.map(field=>({restored:{...p.restored,[field]:'Wrong'}})),
            {action:'accessory_update'},{action:'accessory_stock_update'},{action:'accessory_owner_update'},{added_id:p.current.id},{removed_id:p.current.id},
            {kind_confirmation_required:true},{profile:state.profiles[0].id},{space:'home'},{saved:false},{source_id:43},
            {expect:'f'.repeat(64)},{sha256:'bad'},{revision:'0'},{revision:'9223372036854775808'},{summary:''}];
          for(const extra of bad){const {sheet}=await openKind(p);confirmKind(sheet);let writes=0;apiWrite=async()=>{writes++;return kindSaved(p,extra);};
            const old=save(sheet);old.click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));
            assert(kindConsent(sheet).disabled);old.fire('click');assert.equal(writes,1);}
        ''')

    def test_other_actions_foreign_owners_and_endpoints_cannot_reuse_kind_consent_or_receipts(self):
        self.run_js(r'''
          assert.equal(activityUndoReceipt(kindSaved(),accPreview()),false);assert.equal(activityUndoReceipt(accSaved(),kindPreview()),false);
          assert.equal(activityUndoEvidence(accPreview({kind_confirmation_required:true}),42,'home',state.profiles[0].id),null);
          const foreign=kindPreview();foreign.current.owner=foreign.restored.owner=state.profiles[1].id;const hidden=await openKind(foreign);
          assert(!save(hidden.sheet));assert.equal(kindConsent(hidden.sheet),null);assert(!hidden.sheet.body.textContent.includes('Historical <img'));
          const wrong=await open(kindPreview());assert(!save(wrong.sheet));const made=await openKind();confirmKind(made.sheet);made.view.undoCtx.endpoint='/api/activity/undo';
          let writes=0;apiWrite=async()=>{writes++;return kindSaved();};save(made.sheet).fire('click');await settle();assert.equal(writes,0);
        ''')

    def test_changed_kind_stock_or_context_cannot_authorize_save(self):
        self.run_js(r'''
          for(const mode of ['kind','quantity','owner','notes','action','profile','route','filter','detached','unchecked','modal']){
            const {sheet,p,view}=await openKind();confirmKind(sheet);const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return kindSaved(p);};
            if(mode==='kind')p.restored.kind='playmat';if(mode==='quantity')p.restored.quantity='3';if(mode==='owner')p.restored.owner='shared';if(mode==='notes')p.restored.notes='Later';if(mode==='action')p.action='accessory_update';
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='filter')view.filter.kind='collection';
            if(mode==='detached')kindConsent(sheet).remove();if(mode==='unchecked')kindConsent(sheet).checked=false;if(mode==='modal')top=openSheet('Other task');
            old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();}
        ''')

    def test_unknown_reply_conflict_and_late_foreign_preview_require_reload_without_retry(self):
        self.run_js(r'''
          for(const failure of [Error('Lost reply'),new ApiError(409,'The accessory references changed.',{})]){
            const {sheet}=await openKind();confirmKind(sheet);let writes=0;apiWrite=async()=>{writes++;throw failure;};const old=save(sheet);old.click();await settle();
            assert(button(sheet.dialog,'Reload Activity'));assert(!button(sheet.dialog,'Done'));assert(kindConsent(sheet).disabled);old.fire('click');assert.equal(writes,1);}
          const made=mount([accChange()]);let finish;api=()=>new Promise(done=>finish=done);made.trigger.click();const sheet=[...colSheets].at(-1);
          state.profile=state.profiles[1];finish(kindPreview());await settle();assert.equal(kindConsent(sheet),null);assert(!sheet.body.textContent.includes('Historical <img'));
        ''')

    def test_saved_kind_keeps_original_activity_filter_and_loaded_depth(self):
        self.run_js(r'''
          const filter={kind:'sleeves',actor:state.profiles[0].id},{view,trigger}=mount([accChange(42),accChange(41,false)],41,filter);
          api=async()=>page([accChange(40,false),accChange(39,false)],39);view.older.click();await settle();const p=kindPreview();api=async()=>p;trigger.click();await settle();
          const sheet=[...colSheets].at(-1);confirmKind(sheet);apiWrite=async()=>kindSaved(p);save(sheet).click();await settle();const asked=[];
          api=async path=>{asked.push(path);return asked.length===1?page([accChange(43,false),accChange(42,false)],42):page([accChange(41,false),accChange(40,false)],40);};
          button(sheet.dialog,'Done').click();await settle();same(asked,['/api/activity?kind=sleeves&actor='+filter.actor,'/api/activity?before=42&kind=sleeves&actor='+filter.actor]);
          assert.equal(view.loadedPages,2);assert.equal(view.shown,4);assert(view.days.querySelector('[data-activity-id="42"]'));assert.equal(location.hash,activityHref(filter));
        ''')
