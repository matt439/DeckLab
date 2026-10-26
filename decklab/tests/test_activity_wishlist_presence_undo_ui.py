"""Wishlist entry recovery is profile-owned desire data, without stock controls."""
import unittest

from decklab.tests import test_activity_wishlist_undo_ui as preferences
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class WishlistPresenceUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        preferences.WishlistUndoUiTests.run_js(self, r'''
          const presencePreview=(action='wishlist_remove',extra={})=>{const p=wishPreview(),row=action==='wishlist_add'?p.restored:p.current;
            const result={...p,action,current:action==='wishlist_add'?null:row,restored:action==='wishlist_add'?row:null,...extra};delete result.fields;
            if(Object.hasOwn(extra,'fields'))result.fields=extra.fields;return result;};
          const presenceSaved=(p=presencePreview(),extra={})=>({...wishSaved(p),action:p.action,
            restored:p.action==='wishlist_remove'?null:{...p.restored},...(p.action==='wishlist_remove'?{removed_name:p.current.name}:{}),...extra});
        ''' + scenario)

    def test_both_entry_actions_show_full_plain_entry_without_physical_or_edit_controls(self):
        self.run_js(r'''
          for(const action of ['wishlist_add','wishlist_remove']){const p=presencePreview(action),before=JSON.stringify(p),{sheet}=await openWish(p),text=sheet.body.textContent;
            assert(text.includes(action==='wishlist_add'?'Save Undo restores this entry to your wishlist.':'Save Undo removes this entry from your wishlist.'));
            assert(text.includes(action==='wishlist_add'?'Historical wishlist entry to restore':'Current wishlist entry to remove'));
            for(const word of ['Llanowar Elves','fdn','227','collector number','notes','source','one new audited change','original change stays in Activity'])assert(text.includes(word),word);
            for(const word of ['Quantity:','Condition:','physically owned','Reason for removing','Restored by Undo'])assert(!text.includes(word),word);
            assert.equal(sheet.body.querySelector('input,textarea,select,img,a'),null);assert.equal(sheet.body.querySelectorAll('.activity-undo-note').length,2);
            assert(save(sheet));assert(!save(sheet).disabled);assert.equal(JSON.stringify(p),before);
          }
        ''')

    def test_presence_evidence_is_exact_nullable_action_specific_and_owner_bound(self):
        self.run_js(r'''
          for(const action of ['wishlist_add','wishlist_remove']){const p=presencePreview(action),row=p.current||p.restored;
            const bad=[{action:'add'},{action:'remove'},{action:'wishlist_update'},{profile:state.profiles[1].id},{space:'home'},
              {fields:[]},{reason_required:true},{physical_confirmation_required:true},{row_count:1},{rows:[]},
              action==='wishlist_add'?{current:row}:{restored:row},action==='wishlist_add'?{restored:null}:{current:null},
              action==='wishlist_add'?{restored:{...row,quantity:1}}:{current:{...row,quantity:1}},
              action==='wishlist_add'?{restored:{...row,set:'',number:'227'}}:{current:{...row,set:'',number:'227'}}];
            for(const extra of bad){const {sheet}=await openWish(presencePreview(action,extra));assert(!save(sheet),action+JSON.stringify(extra));assert(!sheet.body.textContent.includes('wishlist entry to'));}
          }
        ''')

    def test_each_save_posts_only_source_receipt_once_without_confirmation_or_reason(self):
        self.run_js(r'''
          for(const action of ['wishlist_add','wishlist_remove']){const {sheet,p}=await openWish(presencePreview(action)),cached=state.library={sentinel:true};let finish;const sent=[];
            apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};const old=save(sheet);old.click();old.fire('click');
            same(sent,[['/api/activity/wishlist-undo',{id:42,expect:'a'.repeat(64)}]]);finish(presenceSaved(p));await settle();assert(button(sheet.dialog,'Done'));
            assert.equal(state.library,cached);old.fire('click');assert.equal(sent.length,1);
          }
        ''')

    def test_remove_receipt_proves_exact_name_absence_and_cannot_look_like_an_update(self):
        self.run_js(r'''
          const bad=[{restored:{}},{restored:undefined},{removed_name:'Different'},{removed_name:'llanowar elves'},{removed_name:null},{removed_name:undefined},
            {action:'wishlist_update'},{action:'wishlist_add'},{space:'home'},{fields:[]},{removed_key:{}},{profile:state.profiles[1].id},
            {sha256:'bad'},{revision:'0'},{revision:'9223372036854775808'},{saved:false}];
          for(const extra of bad){const {sheet,p}=await openWish(presencePreview());let writes=0;apiWrite=async()=>{writes++;return presenceSaved(p,extra);};
            const old=save(sheet);old.click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));old.fire('click');assert.equal(writes,1);}
        ''')

    def test_add_receipt_requires_every_historical_cell_and_no_removal_facts(self):
        self.run_js(r'''
          const p=presencePreview('wishlist_add'),bad=[{restored:null},{restored:{...p.restored,name:'Different'}},{restored:{...p.restored,number:'228'}},
            {restored:{...p.restored,notes:'Changed'}},{restored:{...p.restored,source:'Changed'}},{restored:{...p.restored,position:0}},
            {removed_name:p.restored.name},{action:'wishlist_remove'},{action:'wishlist_update'},{profile:state.profiles[1].id},{revision:'0'}];
          for(const extra of bad){const made=await openWish(p);let writes=0;apiWrite=async()=>{writes++;return presenceSaved(made.p,extra);};
            const old=save(made.sheet);old.click();await settle();assert(!button(made.sheet.dialog,'Done'),JSON.stringify(extra));assert(button(made.sheet.dialog,'Reload Activity'));old.fire('click');assert.equal(writes,1);}
        ''')

    def test_all_wishlist_actions_and_inventory_protocols_remain_separate(self):
        self.run_js(r'''
          const update=wishPreview(),add=presencePreview('wishlist_add'),remove=presencePreview();
          for(const [before,answer] of [[update,presenceSaved(add)],[update,presenceSaved(remove)],[add,wishSaved(update)],[remove,wishSaved(update)],
            [add,presenceSaved(remove)],[remove,presenceSaved(add)],[preview(),presenceSaved(remove)],[add,accepted()]])assert.equal(activityUndoReceipt(answer,before),false);
          assert(!save((await open(add)).sheet));assert(!save((await open(remove)).sheet));
        ''')

    def test_stale_context_endpoint_or_mutated_entry_never_writes(self):
        self.run_js(r'''
          for(const action of ['wishlist_add','wishlist_remove'])for(const mode of ['profile','route','filter','entry','endpoint','modal']){
            const {sheet,p,view}=await openWish(presencePreview(action));const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return presenceSaved(p);};
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='filter')view.filter.kind='collection';
            if(mode==='entry')(p.current||p.restored).notes='Changed after review';if(mode==='endpoint')view.undoCtx.endpoint='/api/activity/undo';if(mode==='modal')top=openSheet('Other task');
            old.fire('click');await settle();assert.equal(writes,0,action+mode);top?.close();
          }
        ''')

    def test_late_owner_or_unknown_save_keeps_privacy_and_requires_reload_without_retry(self):
        self.run_js(r'''
          for(const action of ['wishlist_add','wishlist_remove']){
            const made=mount([wishChange()]);let finish;api=()=>new Promise(done=>finish=done);made.trigger.click();const pending=[...colSheets].at(-1);
            state.profile=state.profiles[1];finish(presencePreview(action));await settle();assert(!save(pending));assert(!pending.body.textContent.includes('Llanowar Elves'));
            const {sheet,p}=await openWish(presencePreview(action));let writes=0;apiWrite=async()=>{writes++;throw Error('Lost reply');};const old=save(sheet);old.click();await settle();
            assert(button(sheet.dialog,'Reload Activity'));assert(!save(sheet));assert(sheet.body.textContent.includes('Llanowar Elves'));assert(!sheet.body.textContent.includes('Undo saved as a new change'));old.fire('click');assert.equal(writes,1);
          }
        ''')

    def test_done_preserves_owner_filters_loaded_depth_and_original_change(self):
        self.run_js(r'''
          const filter={kind:'wishlist',actor:state.profiles[0].id},{view,trigger}=mount([wishChange(42),wishChange(41,false)],41,filter);
          api=async()=>page([wishChange(40,false),wishChange(39,false)],39);view.older.click();await settle();const p=presencePreview();api=async()=>p;trigger.click();await settle();
          const sheet=[...colSheets].at(-1);apiWrite=async()=>presenceSaved(p);save(sheet).click();await settle();const asked=[];
          api=async path=>{asked.push(path);return asked.length===1?page([wishChange(43,false),wishChange(42,false)],42):page([wishChange(41,false),wishChange(40,false)],40);};
          button(sheet.dialog,'Done').click();await settle();same(asked,['/api/activity?kind=wishlist&actor='+filter.actor,'/api/activity?before=42&kind=wishlist&actor='+filter.actor]);
          assert.equal(view.loadedPages,2);assert.equal(view.shown,4);assert.equal(location.hash,activityHref(filter));assert(view.days.querySelector('[data-activity-id="42"]'));
        ''')


if __name__ == "__main__":
    unittest.main()
