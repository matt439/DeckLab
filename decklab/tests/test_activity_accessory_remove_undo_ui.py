"""Unused accessory insertion recovery reviews the whole record and a reason."""
import unittest

from decklab.tests import test_activity_accessory_undo_ui as accessories
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class AccessoryRemoveUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        accessories.AccessoryUndoUiTests.run_js(self, r'''
          const rmPreview=(extra={})=>{const current={...accRow(),quantity:'2',capacity:'100',image:'',crop:''};
            return{available:true,id:42,expect:'a'.repeat(64),kind:'accessory',action:'accessory_remove',label:current.name,
              current,restored:null,reason_required:true,...extra};};
          const rmSaved=(p=rmPreview(),extra={})=>({saved:true,source_id:p.id,expect:p.expect,kind:'accessory',action:'accessory_remove',
            restored:null,removed_id:p.current.id,sha256:'b'.repeat(64),revision:'4321',summary:'Removed the unused added accessory record.',...extra});
          const rmChange=(id=42,hint=true)=>({...accChange(id,hint),rows:[{table:'accessory',op:'INSERT',summary:'Added fixture accessory'}]});
          const openRm=async(p=rmPreview())=>{const made=mount([rmChange()],null,{kind:'sleeves',actor:null});api=async()=>p;
            made.trigger.click();await settle();return{...made,sheet:[...colSheets].at(-1),p};};
          const rmReason=sheet=>sheet.body.querySelector('input');
          const enterRmReason=(sheet,value)=>{const input=rmReason(sheet);input.value=value;input.fire('input');return input;};
        ''' + scenario)

    def test_entire_raw_record_stock_capacity_and_plain_urls_are_reviewed_before_removal(self):
        self.run_js(r'''
          const {sheet,p}=await openRm(),text=sheet.body.textContent;
          for(const word of ['entire accessory record','recorded quantity of 2','Current accessory record to remove','Deck box','Current fixture box',
            '100',p.current.link,p.current.image_source,'Only an unused added record without a photo','references are checked again',
            'kit and photos stay as they are','Reason for removing this added accessory record (required)','Sleeves & boxes'])assert(text.includes(word),word);
          assert(!text.includes('Restored by Undo'));assert(!text.includes('collection.'));assert(!text.includes('physically owned'));
          assert.equal(sheet.body.querySelectorAll('input').length,1);assert.equal(sheet.body.querySelector('a,img,select,textarea'),null);
          assert.equal(rmReason(sheet).value,'');assert(save(sheet).disabled);assert.equal(rmReason(sheet).getAttribute('type'),'text');
        ''')

    def test_zero_and_individual_sleeve_stock_and_unknown_box_capacity_are_explicit(self):
        self.run_js(r'''
          for(const [kind,quantity,capacity] of [['sleeves','100',''],['playmat','0',''],['deck_box','1','']]){
            const p=rmPreview();Object.assign(p.current,{kind,quantity,capacity});const {sheet}=await openRm(p);
            assert(save(sheet));assert(sheet.body.textContent.includes('recorded quantity of '+quantity));
            if(kind==='sleeves')assert(sheet.body.textContent.includes('individual sleeves'));
            assert.equal(sheet.body.querySelector('input[type=number],input[type=checkbox]'),null);
          }
        ''')

    def test_exact_full13_text_stock_and_action_specific_preview_are_required(self):
        self.run_js(r'''
          const base=rmPreview(),bad=[{reason_required:false},{reason_required:undefined},{fields:[]},{restored:{}},{restored:base.current},
            {profile:state.profiles[0].id},{space:'home'},{action:'remove'},{action:'accessory_update'},{current:accRow()},
            ...[2,'-1','10000','02','2.0',' 2','2\n'].map(quantity=>({current:{...base.current,quantity}})),
            ...['0','0100','10000',' 100'].map(capacity=>({current:{...base.current,capacity}})),
            {current:{...base.current,kind:'sleeves',capacity:'100'}},{current:{...base.current,image:'fixture-box.jpg'}},
            {current:{...base.current,crop:'0,0,1,1'}},{current:{...base.current,capacity:null}},{current:{...base.current,extra:''}},
            {current:{...base.current,link:'javascript:alert(1)'}},{current:{...base.current,owner:state.profiles[1].id}},{label:'Wrong label'}];
          for(const extra of bad){const {sheet}=await openRm(rmPreview(extra));assert(!save(sheet),JSON.stringify(extra));assert.equal(rmReason(sheet),null);}
        ''')

    def test_reason_is_explicit_normalized_bounded_and_reset_on_cancel(self):
        self.run_js(r'''
          const {sheet}=await openRm();let writes=0;apiWrite=async()=>{writes++;return rmSaved();};
          for(const value of ['', ' \n\t ', '\u200b\u202e','x'.repeat(201),'bad\0reason']){enterRmReason(sheet,value);assert(save(sheet).disabled);save(sheet).fire('click');await settle();}
          assert.equal(writes,0);enterRmReason(sheet,'  Wrong\u200b  record\n entered\t twice ');assert(!save(sheet).disabled);
          assert(sheet.body.textContent.includes('Reason to be saved: Wrong record entered twice'));button(sheet.dialog,'Cancel').click();
          const again=await openRm();assert.equal(rmReason(again.sheet).value,'');assert(save(again.sheet).disabled);
        ''')

    def test_one_dedicated_source_only_save_sends_accepted_reason_and_exact_absence_receipt(self):
        self.run_js(r'''
          const {sheet,p}=await openRm();const input=enterRmReason(sheet,' Entered\u0085 twice '),old=save(sheet);let finish;const sent=[];
          apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};state.library={sentinel:true};old.click();old.fire('click');
          same(sent,[['/api/activity/accessory-undo',{id:42,expect:'a'.repeat(64),reason:'Entered twice'}]]);assert(input.disabled);
          input.value='Changed during save';input.fire('input');assert.equal(input.value,' Entered\u0085 twice ');finish(rmSaved(p));await settle();
          assert(button(sheet.dialog,'Done'));assert.equal(state.library,null);assert(!save(sheet));old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_only_exact_removed_id_null_new_audit_and_full_receipt_can_confirm_success(self):
        self.run_js(r'''
          const p=rmPreview(),bad=[{removed_id:'another'},{removed_id:undefined},{removed_id:42},{restored:{}},{restored:p.current},
            {action:'accessory_update'},{kind:'collection'},{space:'home'},{profile:state.profiles[0].id},{fields:[]},{saved:false},
            {source_id:43},{expect:'f'.repeat(64)},{sha256:'bad'},{revision:'0'},{revision:'9223372036854775808'},{summary:''}];
          for(const extra of bad){const {sheet}=await openRm(p);enterRmReason(sheet,'Entered twice');let writes=0;
            apiWrite=async()=>{writes++;return rmSaved(p,extra);};const old=save(sheet);old.click();await settle();
            assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));assert(rmReason(sheet).disabled);old.fire('click');assert.equal(writes,1);}
        ''')

    def test_update_and_removal_receipts_and_review_protocols_cannot_cross(self):
        self.run_js(r'''
          assert.equal(activityUndoReceipt(rmSaved(),accPreview()),false);assert.equal(activityUndoReceipt(accSaved(),rmPreview()),false);
          const wrong=await open(rmPreview());assert(!save(wrong.sheet));const made=await openRm();enterRmReason(made.sheet,'Entered twice');
          made.view.undoCtx.endpoint='/api/activity/undo';let writes=0;apiWrite=async()=>{writes++;return rmSaved();};save(made.sheet).fire('click');await settle();assert.equal(writes,0);
        ''')

    def test_stale_stock_owner_context_or_unaccepted_reason_cannot_authorize_save(self):
        self.run_js(r'''
          for(const mode of ['quantity','capacity','owner','photo','action','profile','route','filter','detached','unaccepted','modal']){
            const {sheet,p,view}=await openRm();enterRmReason(sheet,'Entered twice');const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return rmSaved(p);};
            if(mode==='quantity')p.current.quantity='3';if(mode==='capacity')p.current.capacity='80';if(mode==='owner')p.current.owner='shared';if(mode==='photo')p.current.image='fixture-box.jpg';if(mode==='action')p.action='accessory_update';
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='filter')view.filter.kind='collection';if(mode==='detached')rmReason(sheet).remove();if(mode==='unaccepted')rmReason(sheet).value='Not accepted';if(mode==='modal')top=openSheet('Other task');
            old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();
          }
        ''')

    def test_conflict_lost_reply_and_late_owner_require_reload_without_retry_or_private_reveal(self):
        self.run_js(r'''
          for(const failure of [Error('Lost reply'),new ApiError(409,'The accessory is now referenced.',{})]){
            const {sheet}=await openRm();enterRmReason(sheet,'Entered twice');let writes=0;apiWrite=async()=>{writes++;throw failure;};const old=save(sheet);old.click();await settle();
            assert(button(sheet.dialog,'Reload Activity'));assert(!button(sheet.dialog,'Done'));assert(rmReason(sheet).disabled);old.fire('click');assert.equal(writes,1);
          }
          const made=mount([rmChange()]);let finish;api=()=>new Promise(done=>finish=done);made.trigger.click();const sheet=[...colSheets].at(-1);state.profile=state.profiles[1];finish(rmPreview());await settle();
          assert.equal(rmReason(sheet),null);assert(!sheet.body.textContent.includes('Current fixture box'));
        ''')

    def test_done_keeps_loaded_activity_filter_depth_and_original_change(self):
        self.run_js(r'''
          const filter={kind:'sleeves',actor:state.profiles[0].id},{view,trigger}=mount([rmChange(42),rmChange(41,false)],41,filter);
          api=async()=>page([rmChange(40,false),rmChange(39,false)],39);view.older.click();await settle();const p=rmPreview();api=async()=>p;trigger.click();await settle();
          const sheet=[...colSheets].at(-1);enterRmReason(sheet,'Entered twice');apiWrite=async()=>rmSaved(p);save(sheet).click();await settle();const asked=[];
          api=async path=>{asked.push(path);return asked.length===1?page([rmChange(43,false),rmChange(42,false)],42):page([rmChange(41,false),rmChange(40,false)],40);};
          button(sheet.dialog,'Done').click();await settle();same(asked,['/api/activity?kind=sleeves&actor='+filter.actor,'/api/activity?before=42&kind=sleeves&actor='+filter.actor]);
          assert.equal(view.loadedPages,2);assert.equal(view.shown,4);assert(view.days.querySelector('[data-activity-id="42"]'));assert.equal(location.hash,activityHref(filter));
        ''')
