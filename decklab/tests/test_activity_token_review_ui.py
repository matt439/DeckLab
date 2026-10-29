"""Deleted-token eligibility over fake APIs and a Node DOM; no inverse or configured-host writes."""
import unittest

from decklab.tests import test_activity_ui as activity_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ActivityTokenReviewUiTests(unittest.TestCase):
    def run_js(self, scenario):
        activity_ui.ActivityInteractionTests.run_js(self, r'''
          const reads=[],writes=[];
          const hint=()=>({review:true,kind:'tokens',action:'token_restore_review',read_only:true});
          const historical=extra=>({front:'Treasure',back:'Food',set:'tst',front_collector_number:'1',back_collector_number:'2',
            finish:'nonfoil',quantity:2,front_details:'Artifact - Treasure; tap and sacrifice: add one mana.',
            back_details:'Artifact - Food; gain 3 life.',notes:'Physical card pair note',...extra});
          const review=extra=>({available:true,id:42,expect:'a'.repeat(64),kind:'tokens',space:'home',label:'Treasure / Food',
            action:'token_restore_review',read_only:true,current:null,restored:historical(),
            identity_policy:'fresh_id_on_future_add',physical_confirmation_required:true,packing_restored:false,...extra});
          const candidate=(id=42,extra={})=>change(id,{headline:'User1 removed a token card',kinds:['tokens'],undo:hint(),
            message:'DO NOT RELAY AUDIT MESSAGE',reason:'DO NOT RELAY REMOVAL REASON',
            rows:[{table:'token_card',op:'DELETE',summary:'Displayed token summary',
              before:{front:'DISPLAYED WRONG CARD',quantity:999},after:null}],...extra});
          const mount=(changes=[candidate()],filter={kind:null,actor:null},profile=state.profiles[0])=>{
            routeToken++;colCloseSheets();clear(main);state.profile=profile;state.may=null;location.hash=activityHref(filter);
            const view=activityDraw(page(changes),routeToken,filter);
            return{view,trigger:view.days.querySelector('.activity-token-review')};
          };
          const button=(root,text)=>root.querySelectorAll('button').find(node=>node.textContent===text);
          const refresh=sheet=>button(sheet.foot,'Try again')||button(sheet.foot,'Refresh eligibility');
          const openReview=async(value=review())=>{const made=mount();api=async path=>{reads.push(path);return value;};
            made.trigger.click();await settle();return{...made,sheet:[...colSheets].at(-1)};};
          const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
          const failed=sheet=>sheet.body.textContent.includes('not available for review');
          apiWrite=async(...args)=>{writes.push(args);throw Error('No writes allowed');};
        ''' + scenario)

    def test_distinct_hint_only_and_no_initial_request_or_ordinary_undo_action(self):
        self.run_js(r'''
          const made=mount([candidate(40,{undo:undefined}),candidate(41,{undo:{review:true,kind:'tokens'}}),candidate()]);
          assert.equal(reads.length,0);assert.equal(made.view.days.querySelectorAll('.activity-token-review').length,1);
          assert.equal(made.trigger.textContent,'Review deleted token card');
          assert.equal(made.view.days.querySelectorAll('.activity-review-undo').length,1);
          api=async path=>{reads.push(path);return review();};made.trigger.click();await settle();
          same(reads,['/api/activity/undo?id=42']);assert.equal(writes.length,0);
        ''')

    def test_complete_historical_row_is_literal_and_pair_counts_physical_cards_once(self):
        self.run_js(r'''
          const {sheet}=await openReview(),text=sheet.body.textContent;
          for(const word of ['Eligibility review only','2 physical token cards','Each front/back pair is one physical card',
            'Historical token-card row','Treasure','Food','tst','front collector number','back collector number','nonfoil',
            'front details','back details','Artifact - Treasure','Artifact - Food','Physical card pair note'])assert(text.includes(word),word);
          assert(!text.includes('4 physical token cards'));assert.equal(sheet.body.querySelectorAll('dt').length,10);
          assert.equal(sheet.body.querySelectorAll('dd').length,10);assert(!text.includes('DO NOT RELAY'));
          assert(!text.includes('DISPLAYED WRONG CARD'));assert(!text.includes('999'));assert(!text.includes('a'.repeat(64)));
          assert.equal(sheet.body.querySelectorAll('input').length,0);assert.equal(sheet.body.querySelectorAll('form').length,0);
          same(sheet.foot.querySelectorAll('button').map(node=>node.textContent),['Close','Refresh eligibility']);
          assert(!button(sheet.dialog,'Save Undo'));assert.equal(writes.length,0);
        ''')

    def test_future_add_identity_and_whole_quantity_guidance_is_not_apply_authority(self):
        self.run_js(r'''
          const {sheet}=await openReview(),text=sheet.body.textContent;
          for(const word of ['ordinary Add','new token-card record','Earlier packing will not reconnect automatically',
            'physically have the whole recorded quantity','fewer cards','Packing is not restored','Nothing has been restored'])assert(text.includes(word),word);
          assert.equal(sheet.dialog.querySelectorAll('input').length,0);assert.equal(sheet.dialog.querySelectorAll('a').length,0);
          assert.equal(writes.length,0);
        ''')

    def test_single_sided_unknown_optional_fields_stay_blank_without_inferred_faces_or_counts(self):
        self.run_js(r'''
          const value=review({label:'Treasure',restored:historical({back:'',back_details:'',back_collector_number:'',set:'',finish:'',quantity:1})});
          const {sheet}=await openReview(value),text=sheet.body.textContent;
          assert(text.includes('1 physical token card was recorded'));assert(text.includes('Not recorded'));
          assert(!text.includes('Food'));assert(!text.includes('front/back pair'));assert(!text.includes('single-sided verified'));
          assert(!failed(sheet));assert.equal(writes.length,0);
        ''')

    def test_malformed_readonly_packet_or_apply_flags_never_show_historical_row_or_save(self):
        self.run_js(r'''
          const invalid=[{read_only:false},{read_only:undefined},{action:'add'},{action:'remove'},{kind:'collection'},{space:'user2'},
            {id:41},{expect:'short'},{identity_policy:'reuse_id'},{packing_restored:true},{physical_confirmation_required:false},
            {current:{}},{label:'Different label'},{token_row_id:555},{position:4},{confirm_restore:true},{confirm_physical:true},
            {reason:'PRIVATE REASON'},{fields:[]},{message:'PRIVATE MESSAGE'}];
          for(const extra of invalid){const {sheet}=await openReview(review(extra));assert(failed(sheet),JSON.stringify(extra));
            assert(!sheet.body.textContent.includes('Historical token-card row'));assert(!button(sheet.dialog,'Save Undo'));
            assert.equal(sheet.dialog.querySelectorAll('input').length,0);sheet.close();}
          assert.equal(writes.length,0);
        ''')

    def test_malformed_or_oversized_historical_row_fails_closed_without_partial_metadata(self):
        self.run_js(r'''
          const invalid=[{quantity:0},{quantity:'2'},{quantity:10000},{quantity:1.5},{quantity:true},{front:''},
            {front:'x'.repeat(81)},{back:'x'.repeat(81)},{set:'x'.repeat(17)},{front_collector_number:'x'.repeat(17)},
            {front_details:'x'.repeat(301)},{notes:'x'.repeat(501)},{notes:'bad\nline'},{notes:'bad\u0000note'},
            {front:'bad\ud800'},{finish:'glossy'},{private_sql_id:456},{back_details:null}];
          for(const fields of invalid){const {sheet}=await openReview(review({restored:historical(fields)}));
            assert(failed(sheet),JSON.stringify(fields));assert(!sheet.body.textContent.includes('Historical token-card row'));sheet.close();}
          assert.equal(writes.length,0);
        ''')

    def test_generic_inverse_evidence_rejects_all_new_readonly_flags_even_on_old_valid_update(self):
        self.run_js(r'''
          const old={available:true,id:42,expect:'a'.repeat(64),kind:'tokens',space:'home',label:'Treasure / Food',
            current:historical(),restored:historical({quantity:1}),fields:[{field:'quantity',before:2,after:1}]};
          assert(activityUndoEvidence(old,42,'home'));
          for(const extra of [{action:'token_restore_review'},{read_only:true},{read_only:false},
            {identity_policy:'fresh_id_on_future_add'},{packing_restored:false}])assert.equal(activityUndoEvidence({...old,...extra},42,'home'),null);
          assert.equal(activityUndoEvidence(review(),42,'home'),null);assert.equal(writes.length,0);
        ''')

    def test_hint_requires_exact_keys_values_and_safe_source_id(self):
        self.run_js(r'''
          const invalid=[{review:false},{kind:'collection'},{action:'add'},{read_only:false},{read_only:undefined},
            {expect:'a'.repeat(64)},{token_row_id:555},{reason:'PRIVATE'}];
          for(const extra of invalid){const made=mount([candidate(42,{undo:{...hint(),...extra}})]);assert.equal(made.trigger,null);
            assert.equal(made.view.days.querySelectorAll('.activity-review-undo').length,0);}
          for(const id of [0,-1,'42',1.5,Number.MAX_SAFE_INTEGER+1]){const made=mount([candidate(id)]);assert.equal(made.trigger,null);}
          assert.equal(reads.length,0);assert.equal(writes.length,0);
        ''')

    def test_unavailable_or_failed_read_uses_generic_wording_and_explicit_same_sheet_retry(self):
        self.run_js(r'''
          for(const value of [{available:false,id:42,reason:'PRIVATE PACKING DETAIL'},Error('PRIVATE SERVER PATH')]){
            const made=mount();let n=0;api=async path=>{reads.push(path);n++;if(n>1)return review();if(value instanceof Error)throw value;return value;};
            made.trigger.click();await settle();const sheet=[...colSheets].at(-1);assert(failed(sheet));assert(!sheet.body.textContent.includes('PRIVATE'));
            assert(!sheet.body.textContent.includes('Treasure'));const control=refresh(sheet);control.focus();control.click();await settle();
            assert(!failed(sheet));assert.equal(document.activeElement,control);assert.equal(n,2);sheet.close();}
          assert.equal(writes.length,0);
        ''')

    def test_late_read_after_profile_object_replacement_id_or_space_change_is_ignored(self):
        self.run_js(r'''
          for(const change of [()=>state.profile={...state.profile},()=>state.profile.id='user2',()=>state.profile.space='user2']){
            const made=mount(undefined,undefined,{id:'user1',name:'User1',space:'home'}),waiting=deferred();api=()=>waiting.promise;
            made.trigger.click();const sheet=[...colSheets].at(-1);change();waiting.resolve(review());await settle();
            assert(sheet.body.textContent.includes('Checking the deleted'));assert(!sheet.body.textContent.includes('Treasure'));sheet.close();}
          assert.equal(writes.length,0);
        ''')

    def test_late_read_after_route_filter_sequence_or_root_changes_is_ignored(self):
        self.run_js(r'''
          for(const change of [made=>routeToken++,made=>location.hash='#/library',made=>made.view.filter.kind='collection',
            made=>made.view.seq++,made=>made.view.days.remove(),made=>made.view.days=el('div')]){
            const made=mount(),waiting=deferred();api=()=>waiting.promise;made.trigger.click();const sheet=[...colSheets].at(-1);
            change(made);waiting.resolve(review());await settle();assert(!sheet.body.textContent.includes('Treasure'));sheet.close();}
          assert.equal(writes.length,0);
        ''')

    def test_closed_review_releases_busy_and_late_answer_cannot_replace_reopened_review(self):
        self.run_js(r'''
          const made=mount(),pending=[];api=()=>{const waiting=deferred();pending.push(waiting);return waiting.promise;};
          made.trigger.click();const first=[...colSheets].at(-1),old=refresh(first);first.close();assert(!made.view.undoBusy);assert.equal(made.view.undoCtx,null);
          made.trigger.click();const second=[...colSheets].at(-1);assert(first!==second);pending[0].resolve(review());await settle();
          assert(second.body.textContent.includes('Checking the deleted'));old.click();assert.equal(pending.length,2);
          pending[1].resolve(review());await settle();assert(second.body.textContent.includes('Treasure'));assert.equal(writes.length,0);
        ''')

    def test_detached_original_action_or_sheet_footer_prevents_late_display_and_retry(self):
        self.run_js(r'''
          for(const change of [(made,sheet)=>made.trigger.remove(),(made,sheet)=>refresh(sheet).remove(),
            (made,sheet)=>sheet.foot.replaceChildren(el('button',{text:'Replacement'})),(made,sheet)=>sheet.body.remove(),
            (made,sheet)=>{const wrapper=el('div');document.body.append(wrapper);wrapper.append(sheet.dialog);}]){
            const made=mount(),waiting=deferred();let count=0;api=()=>{count++;return waiting.promise;};made.trigger.click();
            const sheet=[...colSheets].at(-1),control=refresh(sheet);change(made,sheet);waiting.resolve(review());await settle();
            assert(!sheet.body.textContent.includes('Treasure'));control.click();assert.equal(count,1);sheet.close();}
          assert.equal(writes.length,0);
        ''')

    def test_current_changed_source_hint_or_id_cannot_reuse_action_or_pending_review(self):
        self.run_js(r'''
          for(const update of [saved=>saved.id=43,saved=>saved.undo={...hint(),read_only:false}]){
            const saved=candidate(),made=mount([saved]),waiting=deferred();api=()=>waiting.promise;made.trigger.click();
            const sheet=[...colSheets].at(-1);update(saved);waiting.resolve(review());await settle();assert(!sheet.body.textContent.includes('Treasure'));sheet.close();}
          const saved=candidate(),made=mount([saved]);saved.id=43;let count=0;api=async()=>{count++;return review({id:43});};
          made.trigger.click();await settle();assert.equal(count,0);
        ''')

    def test_top_modal_and_existing_activity_operation_block_readonly_controls(self):
        self.run_js(r'''
          const made=mount();let count=0;api=async()=>{count++;return review();};
          made.view.undoBusy=true;made.trigger.click();assert.equal(count,0);made.view.undoBusy=false;
          const overlay=openSheet('Other');made.trigger.click();assert.equal(count,0);overlay.close();made.trigger.click();await settle();
          const sheet=[...colSheets].at(-1),other=openSheet('Another');refresh(sheet).click();assert.equal(count,1);
          button(sheet.foot,'Close').click();assert(!sheet.closed);other.close();button(sheet.foot,'Close').click();assert(sheet.closed);
          assert(!made.view.undoBusy);assert.equal(writes.length,0);
        ''')

    def test_pending_retry_is_coalesced_and_never_fetches_activity_or_writes_on_close(self):
        self.run_js(r'''
          const {view,sheet}=await openReview();const waiting=deferred();api=path=>{reads.push(path);return waiting.promise;};
          const control=refresh(sheet);control.click();control.fire('click');assert.equal(reads.length,2);waiting.resolve(review());await settle();
          button(sheet.foot,'Close').click();await settle();same(reads,['/api/activity/undo?id=42','/api/activity/undo?id=42']);
          assert(!view.undoBusy);assert.equal(writes.length,0);
        ''')

    def test_member_review_requires_own_space_packet_without_admin_or_public_override(self):
        self.run_js(r'''
          const made=mount(undefined,undefined,{id:'user2',name:'User2',space:'user2',role:'member'});
          api=async()=>review({space:'home'});made.trigger.click();await settle();let sheet=[...colSheets].at(-1);assert(failed(sheet));sheet.close();
          const own=mount(undefined,undefined,{id:'user2',name:'User2',space:'user2',role:'member'});
          api=async()=>review({space:'user2'});own.trigger.click();await settle();sheet=[...colSheets].at(-1);assert(!failed(sheet));
          assert(sheet.body.textContent.includes('Treasure'));assert.equal(writes.length,0);
        ''')

    def test_historical_html_links_and_notes_are_text_only_without_enrichment_or_normalization(self):
        self.run_js(r'''
          const raw='<img src=x onerror=alert(1)> https://example.com/token',value=review({restored:historical({notes:raw,
            front_details:'  Literal details  ',back_details:'<svg onload=bad>'})});
          const {sheet}=await openReview(value);assert(sheet.body.textContent.includes(raw));
          assert(sheet.body.textContent.includes('  Literal details  '));assert(sheet.body.textContent.includes('<svg onload=bad>'));
          assert.equal(sheet.body.querySelectorAll('img').length,0);assert.equal(sheet.body.querySelectorAll('a').length,0);
          assert.equal(sheet.body.querySelectorAll('svg').length,0);assert.equal(writes.length,0);
          value.restored.notes='MUTATED AFTER RESPONSE';assert(!sheet.body.textContent.includes('MUTATED'));
        ''')
