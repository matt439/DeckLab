"""Wishlist metadata Undo keeps its owner and audit version separate from inventory."""
import unittest

from decklab.tests import test_activity_undo_ui as updates
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class WishlistUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        updates.ActivityUndoUiTests.run_js(self, r'''
          const wishRow=extra=>({name:'Llanowar Elves',set:'fdn',number:'227',notes:'Current wishlist note',source:'Current source',...extra});
          const wishPreview=(extra={})=>({available:true,id:42,expect:'a'.repeat(64),kind:'wishlist',action:'wishlist_update',profile:state.profiles[0].id,
            label:'Llanowar Elves',current:wishRow(),restored:wishRow({notes:'Historical note\nLiteral <img src=x onerror=alert(1)>',source:'magic/buylists/old-fixture.md'}),
            fields:[{field:'notes',before:'Current wishlist note',after:'Historical note\nLiteral <img src=x onerror=alert(1)>'},
              {field:'source',before:'Current source',after:'magic/buylists/old-fixture.md'}],...extra});
          const wishSaved=(p=wishPreview(),extra={})=>({saved:true,source_id:p.id,expect:p.expect,kind:'wishlist',action:'wishlist_update',profile:p.profile,
            restored:{...p.restored},sha256:'b'.repeat(64),revision:'1234',summary:'Restored wishlist notes and source.',...extra});
          const wishChange=(id=42,hint=true)=>candidate(id,{kinds:['wishlist'],undo:hint?{review:true,kind:'wishlist'}:undefined,
            rows:[{table:'wishlist_entry',op:'UPDATE',summary:'Displayed wishlist metadata'}]});
          const openWish=async(p=wishPreview())=>{const made=mount([wishChange()],null,{kind:'wishlist',actor:null});
            api=async()=>p;made.trigger.click();await settle();return{...made,sheet:[...colSheets].at(-1),p};};
        ''' + scenario)

    def test_wishlist_hint_uses_only_the_separate_hardcoded_endpoint(self):
        self.run_js(r'''
          const {trigger}=mount([wishChange()]);const reads=[];api=async path=>{reads.push(path);return wishPreview();};trigger.click();await settle();
          same(reads,['/api/activity/wishlist-undo?id=42']);assert(save([...colSheets].at(-1)));
          const made=mount([wishChange(43)]);made.view.days.querySelector('.activity-review-undo').remove();
          const unknown=mount([candidate(44,{undo:{review:true,kind:'/api/elsewhere'}})]);api=async path=>{reads.push(path);return preview({id:44});};unknown.trigger.click();await settle();
          assert.equal(reads.at(-1),'/api/activity/undo?id=44');assert(save([...colSheets].at(-1)));
        ''')

    def test_metadata_is_plain_wrapping_text_without_stock_edit_or_link_controls(self):
        self.run_js(r'''
          const p=wishPreview(),before=JSON.stringify(p),{sheet}=await openWish(p),text=sheet.body.textContent;
          for(const word of ['Llanowar Elves','fdn','227','Current','Restored by Undo','Notes:','Source:','Current wishlist note','Historical note',
            '<img src=x onerror=alert(1)>','magic/buylists/old-fixture.md','one new audited change'])assert(text.includes(word),word);
          assert.equal(sheet.body.querySelectorAll('.activity-undo-note').length,4);assert.equal(sheet.body.querySelector('img,a,input,textarea,select'),null);
          for(const word of ['Quantity:','Condition:','physically owned','Reason for removing'])assert(!text.includes(word),word);
          assert(save(sheet));assert.equal(JSON.stringify(p),before);
        ''')

    def test_exact_owner_profile_and_distinct_protocol_reject_space_or_inventory_facts(self):
        self.run_js(r'''
          const p=wishPreview(),bad=[{profile:state.profiles[1].id},{profile:undefined},{space:'home'},{kind:'collection'},{action:undefined},{action:'batch_update'},
            {physical_confirmation_required:true},{reason_required:true},{row_count:1},{rows:[]},{current:{...p.current,quantity:4}},
            {restored:{...p.restored,private_id:1}},{restored:{...p.restored,name:'Different'}},{restored:{...p.restored,set:'m19'}},
            {restored:{...p.restored,number:'314'}},{label:'Different'},{fields:[]},
            {fields:[p.fields[0],p.fields[0]]},{fields:[{field:'notes',before:'Wrong',after:p.restored.notes}]},
            {fields:[...p.fields,{field:'name',before:p.current.name,after:p.current.name}]}];
          for(const extra of bad){const {sheet}=await openWish(wishPreview(extra));assert(!save(sheet),JSON.stringify(extra));assert(!sheet.body.textContent.includes('Restored by Undo'));}
          const sparse=Array(2);sparse[0]=p.fields[0];assert.equal(activityUndoEvidence(wishPreview({fields:sparse}),42,'home',state.profiles[0].id),null);
        ''')

    def test_each_metadata_field_or_unknown_printing_can_be_reviewed_without_a_card_lookup(self):
        self.run_js(r'''
          for(const field of ['notes','source']){
            const p=wishPreview();for(const other of ['notes','source'])if(other!==field)p.restored[other]=p.current[other];
            p.fields=p.fields.filter(item=>item.field===field);p.current.set=p.restored.set='';p.current.number=p.restored.number='';
            const {sheet}=await openWish(p);assert(save(sheet));assert(sheet.body.textContent.includes('Not recorded'));
          }
        ''')

    def test_save_posts_only_source_receipt_once_and_preserves_inventory_cache(self):
        self.run_js(r'''
          const {sheet,p}=await openWish(),cached=state.library={sentinel:true};let finish;const sent=[];
          apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};const old=save(sheet);old.click();old.fire('click');
          same(sent,[['/api/activity/wishlist-undo',{id:42,expect:'a'.repeat(64)}]]);finish(wishSaved(p));await settle();
          assert(button(sheet.dialog,'Done'));assert.equal(state.library,cached);old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_saved_receipt_requires_exact_owner_actual_row_digest_and_audit_version(self):
        self.run_js(r'''
          const p=wishPreview(),bad=[{profile:state.profiles[1].id},{profile:undefined},{kind:'collection'},{action:'update'},{space:'home'},
            {revision:'0'},{revision:''},{revision:'inventory-3'},{revision:1234},{revision:'9223372036854775808'},{sha256:'bad'},
            {restored:{...p.restored,notes:'Different'}},{restored:{...p.restored,source:'Different'}},{restored:{...p.restored,number:'228'}},
            {restored:{...p.restored,private_id:7}},{restored_rows:[]},{removed_key:{}},{source_id:43},{expect:'c'.repeat(64)},{summary:''},{saved:false}];
          for(const extra of bad){const made=await openWish();let writes=0;apiWrite=async()=>{writes++;return wishSaved(made.p,extra);};
            const old=save(made.sheet);old.click();await settle();assert(!button(made.sheet.dialog,'Done'),JSON.stringify(extra));assert(button(made.sheet.dialog,'Reload Activity'));
            old.fire('click');assert.equal(writes,1);}
          assert.equal(activityUndoReceipt(wishSaved(p,{revision:'9223372036854775807'}),p),true);
        ''')

    def test_endpoint_and_response_kind_cannot_cross_existing_inventory_protocols(self):
        self.run_js(r'''
          const wrong=await open(wishPreview());assert(!save(wrong.sheet));const opposite=await openWish(preview());assert(!save(opposite.sheet));
          assert.equal(activityUndoReceipt(wishSaved(),preview()),false);assert.equal(activityUndoReceipt(accepted(),wishPreview()),false);
          const made=await openWish();let writes=0;apiWrite=async()=>{writes++;return wishSaved(made.p);};made.view.undoCtx.endpoint='/api/activity/undo';save(made.sheet).fire('click');await settle();assert.equal(writes,0);
        ''')

    def test_changed_profile_even_in_same_space_or_stale_proof_cannot_write(self):
        self.run_js(r'''
          for(const mode of ['profile','route','filter','metadata','field','owner','modal']){
            const {sheet,p,view}=await openWish();const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return wishSaved(p);};
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='filter')view.filter.kind='collection';
            if(mode==='metadata'){p.restored.notes='Changed';p.fields[0].after='Changed';}if(mode==='field')p.fields[0].field='source';if(mode==='owner')p.profile=state.profiles[1].id;
            if(mode==='modal')top=openSheet('Other task');old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();
          }
        ''')

    def test_late_preview_and_result_never_reveal_or_replace_another_owner(self):
        self.run_js(r'''
          const made=mount([wishChange()]);let finish;api=()=>new Promise(done=>finish=done);made.trigger.click();const pending=[...colSheets].at(-1);
          state.profile=state.profiles[1];finish(wishPreview());await settle();assert(!save(pending));assert(!pending.body.textContent.includes('Llanowar Elves'));
          const {sheet,p}=await openWish();apiWrite=()=>new Promise(done=>finish=done);save(sheet).click();sheet.close();state.profile=state.profiles[1];routeToken++;
          clear(main);main.append(el('p',{text:'Current person page'}));let reads=0;api=async()=>{reads++;return freshPage();};finish(wishSaved(p));await settle();assert.equal(reads,0);assert.equal(main.textContent,'Current person page');
        ''')

    def test_conflict_or_lost_result_keeps_review_and_requires_reload_without_retry(self):
        self.run_js(r'''
          for(const failure of [Error('Lost reply'),new ApiError(409,'The wishlist changed.',{})]){
            const {sheet}=await openWish(),cached=state.library={sentinel:true};let writes=0;apiWrite=async()=>{writes++;throw failure;};const old=save(sheet);old.click();await settle();
            assert(button(sheet.dialog,'Reload Activity'));assert(!save(sheet));assert(sheet.body.textContent.includes('Historical note'));assert.equal(state.library,cached);old.fire('click');assert.equal(writes,1);
          }
        ''')

    def test_done_retains_wishlist_filters_loaded_depth_and_original_change(self):
        self.run_js(r'''
          const filter={kind:'wishlist',actor:state.profiles[0].id},{view,trigger}=mount([wishChange(42),wishChange(41,false)],41,filter);
          api=async()=>page([wishChange(40,false),wishChange(39,false)],39);view.older.click();await settle();const p=wishPreview();api=async()=>p;trigger.click();await settle();
          const sheet=[...colSheets].at(-1);apiWrite=async()=>wishSaved(p);save(sheet).click();await settle();const asked=[];
          api=async path=>{asked.push(path);return asked.length===1?page([wishChange(43,false),wishChange(42,false)],42):page([wishChange(41,false),wishChange(40,false)],40);};
          button(sheet.dialog,'Done').click();await settle();same(asked,['/api/activity?kind=wishlist&actor='+filter.actor,'/api/activity?before=42&kind=wishlist&actor='+filter.actor]);
          assert.equal(view.loadedPages,2);assert.equal(view.shown,4);assert.equal(location.hash,activityHref(filter));assert(view.days.querySelector('[data-activity-id="42"]'));assert(!view.undoBusy);
        ''')


if __name__ == "__main__":
    unittest.main()
