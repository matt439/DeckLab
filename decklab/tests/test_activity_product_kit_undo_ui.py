"""Complete product-kit review, untouched unchecked consent and ownership/unknown-save fences."""
import unittest

from decklab.tests import test_activity_undo_ui as base
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ProductKitUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        base.ActivityUndoUiTests.run_js(self, r'''
          const productPreview=(extra={})=>({available:true,id:42,expect:'a'.repeat(64),kind:'product_kit',action:'product_kit_restore',label:'Complete product-kit change',row_count:2,
            kit_confirmation_required:true,rows:[{file:'alpha.csv',title:'Alpha <img> product',current:{sleeves:'shared-sleeves-b',deck_box:'shared-box-b'},restored:{sleeves:'shared-sleeves-a',deck_box:'shared-box-a'}},
              {file:'beta.csv',title:'Beta product',current:{sleeves:'shared-sleeves-a',deck_box:'shared-box-a'},restored:{sleeves:'shared-sleeves-b',deck_box:'shared-box-b'}}],...extra});
          const productSaved=(p,extra={})=>({saved:true,source_id:42,expect:p.expect,kind:p.kind,action:p.action,row_count:p.row_count,rows:structuredClone(p.rows),sha256:'b'.repeat(64),revision:'4321',summary:'Restored every product kit.',...extra});
          const kitChange=()=>candidate(42,{kinds:['products'],undo:{review:true,kind:'product_kit'}});
          const openKit=async(p=productPreview())=>{const made=mount([kitChange()],null,{kind:'products',actor:null});api=async()=>p;made.trigger.click();await settle();return {...made,p,sheet:[...colSheets].at(-1)};};
          const consent=sheet=>sheet.body.querySelector('input[type=checkbox]');
          const confirmKit=(sheet,on=true)=>{const field=consent(sheet);field.checked=on;field.fire('change');};
        ''' + scenario)

    def test_all_products_current_restored_shared_ids_and_one_unchecked_confirmation(self):
        self.run_js(r'''
          const {sheet}=await openKit();assert(save(sheet).disabled);assert(!consent(sheet).checked);assert.equal(sheet.body.querySelectorAll('input').length,1);
          for(const word of ['Alpha <img> product','Beta product','shared-box-a','shared-box-b','Current kit','Restored by Undo','There is no partial selection','Deck History'])assert(sheet.body.textContent.includes(word),word);
          assert.equal(sheet.body.querySelectorAll('a,img').length,0);confirmKit(sheet);assert(!save(sheet).disabled);confirmKit(sheet,false);assert(save(sheet).disabled);
        ''')

    def test_exact_complete_shape_rejects_missing_extra_legacy_duplicate_or_unchanged_rows(self):
        self.run_js(r'''
          const p=productPreview(),bad=[{row_count:1},{row_count:51},{kit_confirmation_required:false},{rows:p.rows.slice(1)},{rows:[p.rows[0],p.rows[0]]},
            {rows:[{...p.rows[0],restored:{...p.rows[0].restored,sleeves:'old red sleeves'}},p.rows[1]]},{rows:[{...p.rows[0],restored:p.rows[0].current},p.rows[1]]},
            {rows:[{...p.rows[0],notes:'private'},p.rows[1]]},{reason_required:true},{space:'home'},{action:'accessory_record_update'}];
          for(const extra of bad){const {sheet}=await openKit(productPreview(extra));assert(!save(sheet),JSON.stringify(extra));}
          assert.equal(activityUndoEvidence(p,42,'user2',state.profiles[0].id),null);
        ''')

    def test_event_confirmation_sends_only_source_receipt_and_one_kit_flag_once(self):
        self.run_js(r'''
          const made=await openKit();let finish;const sent=[];apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};
          consent(made.sheet).checked=true;save(made.sheet).fire('click');assert.equal(sent.length,0);confirmKit(made.sheet);const old=save(made.sheet);old.click();old.fire('click');
          same(sent,[['/api/activity/product-kit-undo',{id:42,expect:'a'.repeat(64),confirm_kit:true}]]);assert(consent(made.sheet).disabled);
          finish(productSaved(made.p));await settle();assert(button(made.sheet.dialog,'Done'));old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_cancel_resets_and_stale_profile_route_preview_sheet_or_consent_cannot_save(self):
        self.run_js(r'''
          const first=await openKit();confirmKit(first.sheet);button(first.sheet.dialog,'Cancel').click();const fresh=await openKit();assert(!consent(fresh.sheet).checked);fresh.sheet.close();
          for(const mode of ['profile','same-profile','route','preview','detached','modal']){state.profile=state.profiles[0];location.hash='#/activity';let writes=0;
            const made=await openKit();confirmKit(made.sheet);const old=save(made.sheet);let top;apiWrite=async()=>{writes++;return productSaved(made.p);};
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='same-profile')state.profile={...state.profile};if(mode==='route')routeToken++;
            if(mode==='preview')made.p.rows[0].restored.deck_box='different-box';if(mode==='detached')consent(made.sheet).remove();if(mode==='modal')top=openSheet('Other task');
            old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();made.sheet.close();}
        ''')

    def test_unconfirmed_or_failed_save_requires_reload_and_never_echoes_unexpected_private_errors(self):
        self.run_js(r'''
          for(const mode of ['partial','changed','extra','error','private']){state.profile=state.profiles[0];const made=await openKit();confirmKit(made.sheet);let writes=0;
            apiWrite=async()=>{writes++;if(mode==='error')throw new ApiError(409,'Kit changed');if(mode==='private')throw Object.assign(Error('PRIVATE path'),{status:503});
              const result=productSaved(made.p);if(mode==='partial')result.rows.pop();if(mode==='changed')result.rows[0].restored.sleeves='different';if(mode==='extra')result.PRIVATE='Unexpected';return result;};
            const old=save(made.sheet);old.click();await settle();assert(button(made.sheet.dialog,'Reload Activity'));assert(!button(made.sheet.dialog,'Done'));
            assert(!made.sheet.body.textContent.includes('PRIVATE'));old.fire('click');assert.equal(writes,1);made.sheet.close();}
        ''')

    def test_pending_close_refreshes_only_after_confirmed_result_and_does_not_repeat_save(self):
        self.run_js(r'''
          const made=await openKit();confirmKit(made.sheet);let finish;let writes=0;apiWrite=()=>{writes++;return new Promise(done=>finish=done);};const old=save(made.sheet);old.click();made.sheet.close();
          api=async()=>freshPage();finish(productSaved(made.p));await settle();old.fire('click');assert.equal(writes,1);
        ''')
