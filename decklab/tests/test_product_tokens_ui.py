"""Producer-authenticated whole-product packed-token editing over fixture APIs only."""
import unittest

from decklab.tests import test_accounts_ui as accounts
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ProductTokensUiTests(unittest.TestCase):
    def run_js(self, scenario):
        accounts.AccountsUiTests.run_js(self, r'''
          const settle=async()=>{for(let i=0;i<32;i++)await null;};
          const packed=extra=>({written:true,editable:true,product:{stem:'verified-holder',status_sha256:'b'.repeat(64)},
            expect:'ignored-deck-hash',tokens_sha256:'a'.repeat(64),lines:[{text:'2 Zombie // Zombie Knight (TST) 3; 1 Dog',rows:[]}],
            choices:[{row:3,front:'Zombie',back:'Zombie Knight',set:'tst',number:'3',quantity:8,free:6,packed:2},
              {row:5,front:'Dog',back:'',set:'',number:'',quantity:2,free:2,packed:1}],...extra});
          const answer=extra=>({saved:true,stem:'verified-holder',token_cards:'2 Zombie // Zombie Knight (TST) 3; 1 Dog',
            status_sha256:'c'.repeat(64),tokens_sha256:'a'.repeat(64),...extra});
          let routed=0;route=()=>{routed++;routeToken++;clear(main);};
          const mount=(extra={})=>{
            closeProductStorageSheets();clear(main);as('matt',MAY.admin);location.hash='#/deck?id=product%2Fstarter%2Fgreen&tab=cards';
            const data={summary:{id:'product/starter/green',space:'home',read_only:true,player:null},
              tokens:{needs:[],copies:[],unlisted:[],packed:packed(extra)}};
            deckScreen={data};const section=tokensSection(data);main.append(section);
            const root=section.querySelector('.product-tokens'),trigger=root?.querySelector('button');return {data,root,trigger};
          };
          const currentSheet=()=>[...productStorageSheets].at(-1);
          const open=(extra={})=>{const view=mount(extra);view.trigger.click();return {...view,sheet:currentSheet()};};
          const act=(sheet,text)=>button(sheet.dialog,text);
          const counts=sheet=>sheet.body.querySelectorAll('input');
        ''' + scenario)

    def test_whole_product_record_shows_even_when_current_subdeck_has_no_token_needs(self):
        self.run_js(r'''
          const {root,trigger}=mount();assert(root);assert(trigger);assert(root.textContent.includes('whole product'));
          assert(root.textContent.includes('including all its decks'));assert(root.textContent.includes('2 Zombie // Zombie Knight'));
          assert(!root.textContent.includes('side only'));assert(!root.textContent.includes('can be sleeved'));
          trigger.click();const sheet=currentSheet();assert(sheet.body.textContent.includes('whole product'));
          same(counts(sheet).map(input=>input.value),['2','1']);assert(sheet.body.textContent.includes('2 in other holders'));
        ''')

    def test_legacy_record_is_unknown_and_does_not_prefill_estimates_as_verified_quantities(self):
        self.run_js(r'''
          const {root,sheet}=open({written:false,lines:[]});assert(root.textContent.includes('not recorded'));
          assert(root.textContent.includes('shared-card warning assumes one card per token row it uses'));
          same(counts(sheet).map(input=>input.value),['0','0']);
          assert(sheet.body.textContent.includes('leaves its packed quantities unknown'));
          assert(sheet.body.textContent.includes('does not record that the product packs no token cards'));
        ''')

    def test_exact_status_and_token_hashes_and_producer_stem_are_used_once(self):
        self.run_js(r'''
          const {sheet}=open();const calls=[];let resolve;apiWrite=(path,body)=>{calls.push([path,body]);return new Promise(done=>resolve=done);};
          const old=act(sheet,'Save');old.focus();old.click();old.click();
          same(calls,[['/api/product/token-cards',{stem:'verified-holder',expect:'b'.repeat(64),tokens_sha256:'a'.repeat(64),
            cards:[{row:3,quantity:2},{row:5,quantity:1}]}]]);
          assert(counts(sheet).every(input=>input.disabled));resolve(answer());await settle();assert(act(sheet,'Done'));
          assert(sheet.body.textContent.includes('recorded for the whole product'));old.fire('click');assert.equal(calls.length,1);
        ''')

    def test_clear_sends_empty_cards_with_explicit_nullable_token_hash_and_restores_unknown_words(self):
        self.run_js(r'''
          const {sheet}=open({tokens_sha256:null,choices:[]});const calls=[];
          apiWrite=async(path,body)=>{calls.push([path,body]);return answer({token_cards:'',tokens_sha256:null});};
          assert(act(sheet,'Save').disabled);act(sheet,'Clear packed record').click();await settle();
          same(calls,[['/api/product/token-cards',{stem:'verified-holder',expect:'b'.repeat(64),tokens_sha256:null,cards:[]}]]);
          assert(sheet.body.textContent.includes('packed quantities are unknown until recorded again'));
          assert(!sheet.body.textContent.includes('packs no tokens'));
        ''')

    def test_quantity_validation_preserves_overcommit_instead_of_clamping_it(self):
        self.run_js(r'''
          const p=packed();p.choices[0].packed=7;const {sheet}=open(p);assert.equal(counts(sheet)[0].value,'7');const calls=[];
          apiWrite=async(path,body)=>{calls.push(body);return answer();};
          for(const value of ['7','', '-1','1.5','NaN']){counts(sheet)[0].value=value;act(sheet,'Save').click();assert.equal(calls.length,0,value);}
          counts(sheet)[0].value='2';act(sheet,'Save').click();await settle();assert.equal(calls.length,1);
        ''')

    def test_no_product_id_prefix_or_representative_subdeck_infers_a_writable_holder(self):
        self.run_js(r'''
          let view=mount({product:undefined});assert(!view.root);
          for(const product of [null,[],{}, {stem:'../escape',status_sha256:'b'.repeat(64)},{stem:'verified-holder',status_sha256:'short'}]){
            assert.equal(productTokenEvidence({...packed(),product}),null);
          }
          view=mount({product:{stem:'verified-holder',status_sha256:'short'}});assert(!view.trigger);
          assert(view.root.textContent.includes('cannot be checked'));
        ''')

    def test_home_inventory_and_product_edit_permissions_control_physical_metadata_and_writes(self):
        self.run_js(r'''
          const view=mount({editable:false,why_not:'Only an admin changes products.'});assert(!view.trigger);assert(view.root.textContent.includes('Only an admin'));
          const p=packed();as('user2',MAY.user2);assert.equal(productPackedTokens({tokens:{packed:p}}),null);
          as('matt',MAY.admin);state.may={...MAY.admin,see_home_records:false};assert.equal(productPackedTokens({tokens:{packed:p}}),null);
          as('user1',MAY.user1);const root=productPackedTokens({tokens:{packed:p}});assert(root);assert(!root.querySelector('button'));
        ''')

    def test_stale_trigger_or_review_cannot_write_after_route_profile_screen_or_evidence_changes(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','screen','data','metadata','permission','detached']){
            const {sheet,data,root}=open();const calls=[];apiWrite=async()=>{calls.push(1);return answer();};
            if(mode==='profile')state.profile=PROFILES[1];if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='screen')deckScreen={};if(mode==='data')data.tokens.packed={...data.tokens.packed};
            if(mode==='metadata')data.tokens.packed.product.status_sha256='d'.repeat(64);
            if(mode==='permission')state.may={...MAY.user1};if(mode==='detached')root.remove();
            act(sheet,'Save').fire('click');assert.equal(calls.length,0,mode);
          }
        ''')

    def test_unknown_or_conflict_failure_latches_reload_and_retired_save_cannot_retry(self):
        self.run_js(r'''
          for(const failure of [Error('Lost response'),new ApiError(409,'Token list changed',{})]){
            const {sheet}=open();let calls=0;apiWrite=async()=>{calls++;throw failure;};const old=act(sheet,'Save');old.focus();old.click();await settle();
            assert(act(sheet,'Reload product'));assert(!act(sheet,'Save'));assert(sheet.body.textContent.includes('Reload the product before saving again'));
            old.fire('click');await settle();assert.equal(calls,1);assert.equal(document.activeElement.getAttribute('role'),'alert');
          }
        ''')

    def test_mismatched_nonempty_receipt_is_uncertain_instead_of_confirmed(self):
        self.run_js(r'''
          const {sheet}=open();let calls=0;apiWrite=async()=>{calls++;return answer({token_cards:'99 Different token'});};
          act(sheet,'Save').click();await settle();assert(!act(sheet,'Done'));assert(act(sheet,'Reload product'));
          assert(sheet.body.textContent.includes('could not be confirmed'));assert.equal(calls,1);
        ''')

    def test_receipt_text_merges_identical_faces_and_printing_in_first_selected_order(self):
        self.run_js(r'''
          const choices=packed().choices;choices.push({...choices[0],row:9,number:'3',set:'TST'});
          assert.equal(productTokenText(choices,[{row:3,quantity:2},{row:9,quantity:1},{row:5,quantity:1}]),
            '3 Zombie // Zombie Knight (TST) 3; 1 Dog');
          choices[0].number='';assert.equal(productTokenText(choices,[{row:3,quantity:2}]),'2 Zombie // Zombie Knight');
          assert.equal(productTokenText(choices,[]),'');
        ''')

    def test_late_result_never_refreshes_or_shows_private_receipt_on_another_page_or_profile(self):
        self.run_js(r'''
          for(const mode of ['profile','route','page']){
            const {sheet,root}=open();let resolve;apiWrite=()=>new Promise(done=>resolve=done);act(sheet,'Save').click();
            if(mode==='profile')state.profile=PROFILES[1];if(mode==='route')routeToken++;if(mode==='page')root.remove();
            const before=routed;resolve(answer());await settle();assert(!act(sheet,'Done'));assert.equal(routed,before,mode);
          }
        ''')

    def test_closed_pending_sheet_cannot_reopen_or_repeat_before_confirmed_refresh(self):
        self.run_js(r'''
          const {sheet,trigger}=open();let resolve;let calls=0;apiWrite=()=>{calls++;return new Promise(done=>resolve=done);};
          act(sheet,'Save').click();sheet.close();trigger.click();assert.equal(productStorageSheets.size,0);assert.equal(calls,1);
          const before=routed;resolve(answer());await settle();assert.equal(routed,before+1);trigger.click();assert.equal(calls,1);
        ''')

    def test_focus_preserves_later_modal_and_exposes_its_owned_reload_footer(self):
        self.run_js(r'''
          const {sheet}=open();let reject;apiWrite=()=>new Promise((done,no)=>reject=no);act(sheet,'Save').focus();act(sheet,'Save').click();
          const top=openSheet('Current modal'),focus=el('button',{text:'Current action'});top.body.append(focus);focus.focus();
          reject(Error('Lost response'));await settle();assert.equal(document.activeElement,focus);assert(act(sheet,'Reload product'));top.close();
          assert(!act(sheet,'Reload product').disabled);
        ''')

    def test_shared_product_sheet_lifecycle_closes_without_writing(self):
        self.run_js(r'''
          const {sheet}=open();let writes=0;apiWrite=async()=>{writes++;return answer();};
          assert(productStorageSheets.has(sheet));closeProductStorageSheets();assert(sheet.closed);assert.equal(productStorageSheets.size,0);assert.equal(writes,0);
        ''')
    
    def test_refresh_waits_for_sheet_history_back_and_does_not_rewrite_a_new_destination(self):
        self.run_js(r'''
          history.state={pos:4};history.length=5;const base=location.hash;let pendingBack;
          history.pushState=(value)=>{history.state=value;history.length++;};history.replaceState=(value)=>{history.state=value;};
          history.back=()=>{pendingBack=()=>{history.state={pos:4};window.fire('popstate');};};
          const {sheet}=open();apiWrite=async()=>answer();act(sheet,'Save').click();await settle();const before=routed;
          act(sheet,'Done').click();assert.equal(routed,before);flushTimers();assert(pendingBack);assert.equal(routed,before);
          pendingBack();assert.equal(routed,before+1);
        ''')
