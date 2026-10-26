"""Unused token-row insertion Undo uses stable row proof and physical-card quantities."""
import unittest

from decklab.tests import test_activity_undo_ui as updates
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoTokenRemoveUiTests(unittest.TestCase):
    def run_js(self, scenario):
        updates.ActivityUndoUiTests.run_js(self, r'''
          const physicalRow=extra=>tokenRow({front:'Treasure',back:'Food',set:'tst',front_collector_number:'1',back_collector_number:'2',finish:'nonfoil',
            quantity:2,front_details:'Artifact — Treasure; tap and sacrifice: add one mana.',back_details:'Artifact — Food; gain 3 life.',notes:'Physical card pair note',...extra});
          const removalPreview=(extra={})=>{const p=preview({kind:'tokens',label:'Treasure // Food (TST 1 / 2)',action:'remove',token_row_id:456789,
            reason_required:true,current:physicalRow(),restored:null,...extra});delete p.fields;if(Object.hasOwn(extra,'fields'))p.fields=extra.fields;return p;};
          const removedToken=(p=removalPreview(),extra={})=>({saved:true,source_id:p.id,expect:p.expect,kind:p.kind,space:p.space,sha256:'b'.repeat(64),revision:'4',
            summary:'Removed the added physical token-card row.',action:'remove',removed_token_row_id:p.token_row_id,restored:null,...extra});
          const removalReason=sheet=>sheet.body.querySelector('input');
          const enterRemovalReason=(sheet,value='Entered twice')=>{const input=removalReason(sheet);input.value=value;input.fire('input');return input;};
        ''' + scenario)

    def test_paired_faces_are_two_physical_cards_not_four_and_every_recorded_field_is_reviewed(self):
        self.run_js(r'''
          const {sheet}=await open(removalPreview()),text=sheet.body.textContent;
          for(const word of ['2 physical token cards','Each front/back pair is one physical card','Current token-card row to remove','Treasure','Food','tst',
            'front collector number','back collector number','nonfoil','Artifact — Treasure','Artifact — Food','Physical card pair note','Reason for removing this added token-card row (required)'])assert(text.includes(word),word);
          assert(!text.includes('4 physical token cards'));assert(!text.includes('456789'));assert(!text.includes('Restored by Undo'));assert(!text.includes('Quantity: 0'));
          assert.equal(sheet.body.querySelectorAll('input').length,1);assert.equal(removalReason(sheet).getAttribute('type'),'text');assert.equal(removalReason(sheet).value,'');assert(save(sheet).disabled);
        ''')

    def test_single_sided_unknown_printing_fields_stay_unknown_without_inferred_back_face(self):
        self.run_js(r'''
          const {sheet}=await open(removalPreview({label:'Treasure (printing not recorded)',current:physicalRow({back:'',back_details:'',back_collector_number:'',set:'',finish:'',quantity:1})}));
          assert(sheet.body.textContent.includes('1 physical token card'));assert(sheet.body.textContent.includes('Not recorded'));assert(!sheet.body.textContent.includes('front/back pair'));
          assert(!sheet.body.textContent.includes('Food'));assert(!sheet.body.textContent.includes('single-sided verified'));assert.equal(removalReason(sheet).value,'');
        ''')

    def test_token_removal_requires_exact_packet_stable_id_and_complete_token_row(self):
        self.run_js(r'''
          const bad=[{token_row_id:undefined},{token_row_id:0},{token_row_id:-1},{token_row_id:'456789'},{token_row_id:1.5},{token_row_id:Number.MAX_SAFE_INTEGER+1},
            {action:'add'},{reason_required:false},{restored:{}},{restored:physicalRow({quantity:0})},{fields:[]},{physical_confirmation_required:true},
            {current:physicalRow({quantity:'2'})},{current:physicalRow({quantity:0})},{current:{...physicalRow(),private_id:4}},{current:{...physicalRow(),front_details:null}},
            {kind:'collection'},{removed_key:{set:'tst',collector_number:'1',finish:'nonfoil'}}];
          for(const extra of bad){const {sheet}=await open(removalPreview(extra));assert(!save(sheet),JSON.stringify(extra));assert.equal(removalReason(sheet),null);assert(!sheet.body.textContent.includes('Current token-card row to remove'));}
        ''')

    def test_reason_is_required_and_save_posts_only_source_receipt_and_normalized_reason_once(self):
        self.run_js(r'''
          const {sheet,p}=await open(removalPreview());const input=enterRemovalReason(sheet,'  Wrong\u200b  import\n file  '),old=save(sheet);input.fire('change');assert.equal(save(sheet),old);
          let finish;const sent=[];apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};old.click();old.fire('click');
          same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64),reason:'Wrong import file'}]]);assert(input.disabled);finish(removedToken(p));await settle();
          assert(button(sheet.dialog,'Done'));assert(!save(sheet));assert(sheet.body.textContent.includes('Removed the added physical token-card row.'));old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_empty_overlong_or_control_reasons_never_authorize_a_token_removal(self):
        self.run_js(r'''
          const {sheet,p}=await open(removalPreview());let writes=0;apiWrite=async()=>{writes++;return removedToken(p);};
          for(const value of ['', ' \n ', '\u200b', 'x'.repeat(201), 'Bad\u0000reason']){enterRemovalReason(sheet,value);assert(save(sheet).disabled);save(sheet).fire('click');await settle();assert.equal(writes,0);}
          enterRemovalReason(sheet,'🦊'.repeat(200));assert(!save(sheet).disabled);save(sheet).click();await settle();assert.equal(writes,1);
        ''')

    def test_receipt_needs_matching_stable_token_id_and_null_row_without_printing_key_fallback(self):
        self.run_js(r'''
          const invalid=[{removed_token_row_id:undefined},{removed_token_row_id:null},{removed_token_row_id:456788},{removed_token_row_id:'456789'},
            {removed_token_row_id:0},{removed_token_row_id:Number.MAX_SAFE_INTEGER+1},{removed_key:{set:'tst',collector_number:'1',finish:'nonfoil'}},
            {removed_key:null},{added_key:{}},{restored:{}},{restored:physicalRow({quantity:0})},{action:'add'},{action:undefined},
            {source_id:43},{expect:'f'.repeat(64)},{kind:'collection'},{space:'user2'},{saved:false},{sha256:'bad'},{revision:4},{summary:''},
            {row_count:2},{restored_rows:[]}];
          for(const extra of invalid){const {sheet,p}=await open(removalPreview());enterRemovalReason(sheet);let writes=0;apiWrite=async()=>{writes++;return removedToken(p,extra);};
            const old=save(sheet);old.click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));assert(removalReason(sheet).disabled);old.fire('click');assert.equal(writes,1);}
        ''')

    def test_collection_receipts_and_legacy_token_updates_cannot_use_token_removal_proof(self):
        self.run_js(r'''
          const collectionRemove={...preview(),action:'remove',reason_required:true,restored:null};delete collectionRemove.fields;
          assert.equal(activityUndoReceipt(removedToken(),collectionRemove),false);assert.equal(activityUndoEvidence(preview({token_row_id:456789}),42,'home'),null);
          const p=tokenPreview(),{sheet}=await open(p);let body;apiWrite=async(path,sent)=>{body=sent;return accepted(p);};save(sheet).click();await settle();
          same(body,{id:42,expect:'a'.repeat(64)});assert(button(sheet.dialog,'Done'));assert.equal(activityUndoReceipt(accepted(p,{removed_token_row_id:456789}),p),false);
        ''')

    def test_stale_packet_source_id_reason_or_current_owner_cannot_save(self):
        self.run_js(r'''
          for(const mode of ['token-id','quantity','metadata','reason','detached','profile','route','hash','root','seq','modal']){
            const {sheet,p,view}=await open(removalPreview());enterRemovalReason(sheet);const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return removedToken(p);};
            if(mode==='token-id')p.token_row_id++;if(mode==='quantity')p.current.quantity=3;if(mode==='metadata')p.current.back_details='Changed';
            if(mode==='reason')removalReason(sheet).value='Unaccepted change';if(mode==='detached')removalReason(sheet).remove();if(mode==='profile')state.profile=state.profiles[1];
            if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';if(mode==='root')view.days.remove();if(mode==='seq')view.seq++;if(mode==='modal')top=openSheet('Other task');
            old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();
          }
        ''')

    def test_hold_conflict_or_unknown_result_retains_row_and_requires_reload_without_reallocation_override(self):
        self.run_js(r'''
          for(const failure of [Error('Lost response'),new ApiError(409,'A packed token allocation changed.',{})]){
            const {sheet}=await open(removalPreview());enterRemovalReason(sheet);let writes=0;apiWrite=async()=>{writes++;throw failure;};const old=save(sheet);old.click();await settle();
            assert(sheet.body.textContent.includes('Current token-card row to remove'));assert.equal(removalReason(sheet).value,'Entered twice');assert(removalReason(sheet).disabled);
            assert(button(sheet.dialog,'Reload Activity'));assert(!save(sheet));assert.equal(button(sheet.dialog,'Remove anyway'),undefined);old.fire('click');assert.equal(writes,1);
          }
        ''')

    def test_late_preview_and_result_do_not_reveal_or_replace_another_owner(self):
        self.run_js(r'''
          const {trigger}=mount();let finish;api=()=>new Promise(done=>finish=done);trigger.click();const pending=[...colSheets].at(-1);state.profile=state.profiles[1];finish(removalPreview());await settle();
          assert.equal(removalReason(pending),null);assert(!pending.body.textContent.includes('Treasure'));
          const {sheet,p}=await open(removalPreview());enterRemovalReason(sheet);apiWrite=()=>new Promise(done=>finish=done);save(sheet).click();sheet.close();state.profile=state.profiles[1];routeToken++;
          clear(main);main.append(el('p',{text:'New owner page'}));let reads=0;api=async()=>{reads++;return freshPage();};finish(removedToken(p));await settle();assert.equal(reads,0);assert.equal(main.textContent,'New owner page');
        ''')

    def test_done_preserves_filter_depth_and_original_audit_without_repeating_save(self):
        self.run_js(r'''
          const filter={kind:'tokens',actor:'user1'},{view,trigger}=mount([candidate(),candidate(41,{undo:undefined})],41,filter);api=async()=>page([candidate(40,{undo:undefined}),candidate(39,{undo:undefined})],39);
          view.older.click();await settle();const p=removalPreview();api=async()=>p;trigger.click();await settle();const sheet=[...colSheets].at(-1);enterRemovalReason(sheet);let writes=0;apiWrite=async()=>{writes++;return removedToken(p);};save(sheet).click();await settle();
          const asked=[];api=async path=>{asked.push(path);return asked.length===1?page([candidate(43,{undo:undefined}),candidate(42,{undo:undefined})],42):page([candidate(41,{undo:undefined}),candidate(40,{undo:undefined})],40);};
          button(sheet.dialog,'Done').click();await settle();same(asked,['/api/activity?kind=tokens&actor=user1','/api/activity?before=42&kind=tokens&actor=user1']);
          assert.equal(writes,1);assert.equal(view.loadedPages,2);assert.equal(view.shown,4);assert.equal(location.hash,activityHref(filter));assert(view.days.querySelector('[data-activity-id="42"]'));assert(!view.undoBusy);
        ''')

    def test_face_details_and_reason_are_plain_local_text_and_internal_id_stays_out_of_wording(self):
        self.run_js(r'''
          const raw='<img src=x onerror=alert(1)>',{sheet}=await open(removalPreview({current:physicalRow({front_details:raw})})),hash=location.hash,prior=JSON.stringify(state);
          enterRemovalReason(sheet,raw);assert(sheet.body.textContent.includes(raw));assert.equal(sheet.body.querySelector('img'),null);assert(!sheet.body.textContent.includes('456789'));
          assert.equal(location.hash,hash);assert.equal(JSON.stringify(state),prior);
        ''')


if __name__ == "__main__":
    unittest.main()
