"""Precon token opt-in, conflict recovery and scoped receipts over fixture APIs only."""
import unittest

from decklab.tests import test_collection_guards_ui as collection_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class PreconTokensUiTests(unittest.TestCase):
    def run_js(self, scenario):
        collection_ui.CollectionGuardsUiTests.run_js(self, r'''
          const offer=extra=>({ready:true,editable:true,rows:[
            {front:'Dog',quantity:2,source_row:1,notes:'Unconfirmed printing, finish and reverse face'},
            {front:'The Monarch',quantity:1,source_row:2,notes:'Unconfirmed printing, finish and reverse face'}],
            cards:3,sha256:'a'.repeat(64),source_sha256:'c'.repeat(64),problems:[],...extra});
          const preview=extra=>({ready:true,editable:true,sha256:'collection-first',title:'Fixture deck',kind:'casual',
            deck:{file:'Fixture_TST',name:'Fixture precon',code:'tst',set_name:'Fixture set',type:'Casual deck'},
            counts:{Deck:24},adds:{rows:1,cards:4},left_out:{},tokens:[{count:99,name:'Source suggestion'}],
            lists:{Deck:[{qty:4,name:'Llanowar Elves',set:'fdn',number:'227',finish:'nonfoil',card:alpha}]},
            token_import:offer(),...extra});
          const added=extra=>({collection:{added:{rows:1,cards:4}},deck:{id:'casual/fixture',title:'Fixture deck',created:true},
            tokens:{cards:3,rows:2},...extra});
          const open=async(p=preview())=>{
            colCloseSheets();clear(main);state.saved=null;as('matt',MAY.admin);location.hash='#/collection';
            const made=await make();made.ctx.sheet.close();
            api=async path=>{if(path.startsWith('/api/precons/preview?'))return p;if(path.startsWith('/api/precons?'))return {decks:[]};throw Error(path);};
            const ctx=openPreconSheet(made.cv);await flush();await previewPrecon(ctx,p.deck);return ctx;
          };
          const choose=ctx=>{const node=ctx.tokenChoice.node;node.checked=true;node.fire('change');return node;};
          const addButton=ctx=>ctx.sheet.foot.querySelectorAll('button').find(node=>node.getAttribute('data-action')==='add');
          const textButton=(ctx,text)=>ctx.sheet.foot.querySelectorAll('button').find(node=>node.textContent===text);
        ''' + scenario)

    def test_older_api_keeps_original_opt_out_request_and_checked_tokens_link(self):
        self.run_js(r'''
          const p=preview();delete p.token_import;const ctx=await open(p),calls=[];
          assert.equal(ctx.tokenChoice,null);assert(ctx.area.textContent.includes("aren't added"));
          apiWrite=async(path,body)=>{calls.push([path,body]);return added();};await addPrecon(ctx);
          same(calls,[['/api/precons/add',{space:'home',file:'Fixture_TST',title:'Fixture deck',sha256:'collection-first'}]]);
          assert(!('tokens' in state.saved.answer.precon));
        ''')

    def test_eligible_offer_is_native_unchecked_and_explicit_about_uncertain_details(self):
        self.run_js(r'''
          const ctx=await open(),node=ctx.tokenChoice.node;
          assert.equal(node.getAttribute('type'),'checkbox');assert(!node.checked);assert.equal(node.parentNode.tag,'label');
          for(const words of ['3 cards','2 x Dog','1 x The Monarch','Printing, finish and reverse face stay unconfirmed','check the physical cards afterward'])
            assert(ctx.area.textContent.includes(words),words);
          assert(!ctx.area.textContent.includes('99 Source suggestion'));assert(!node.disabled);
        ''')

    def test_normal_unchecked_offer_omits_all_token_request_fields(self):
        self.run_js(r'''
          const ctx=await open();let body;apiWrite=async(path,payload)=>{body=payload;return added();};await addPrecon(ctx);
          assert(!Object.hasOwn(body,'add_tokens'));assert(!Object.hasOwn(body,'tokens_sha256'));assert(!Object.hasOwn(body,'tokens_source_sha256'));
          assert(!('tokens' in state.saved.answer.precon));
        ''')

    def test_opt_in_preserves_custom_title_exact_full_sha_and_duplicate_save_guard(self):
        self.run_js(r'''
          const ctx=await open(),node=choose(ctx);ctx.titleInput.value='My custom precon';const calls=[];let resolve;
          apiWrite=(path,body)=>{calls.push([path,body]);return new Promise(done=>resolve=done);};
          const pending=addPrecon(ctx);addPrecon(ctx);await flush();assert.equal(calls.length,1);assert(node.disabled);
          same(calls[0],['/api/precons/add',{space:'home',file:'Fixture_TST',title:'My custom precon',sha256:'collection-first',
            add_tokens:true,tokens_sha256:'a'.repeat(64),tokens_source_sha256:'c'.repeat(64)}]);resolve(added());await pending;
          assert.equal(state.saved.answer.precon.tokens,3);assert.equal(state.saved.profile,'matt');
        ''')

    def test_empty_token_sheet_sha_is_sent_as_explicit_null(self):
        self.run_js(r'''
          const ctx=await open(preview({token_import:offer({sha256:null})}));choose(ctx);let body;
          apiWrite=async(path,payload)=>{body=payload;return added();};await addPrecon(ctx);
          assert.equal(body.add_tokens,true);assert(Object.hasOwn(body,'tokens_sha256'));assert.equal(body.tokens_sha256,null);
          assert.equal(body.tokens_source_sha256,'c'.repeat(64));
        ''')

    def test_malformed_or_unauthorized_offers_never_gain_an_opt_in_control(self):
        self.run_js(r'''
          for(const extra of [{ready:false},{editable:false},{rows:[]},{cards:4},{cards:1.5},{sha256:'short'},
            {source_sha256:null},{source_sha256:'short'},
            {rows:[{front:'Dog',quantity:0,source_row:1}],cards:0},{rows:[{front:'',quantity:3,source_row:1}]},
            {rows:[{front:'Dog',quantity:3,source_row:0}]}])assert.equal(preconTokenOffer(preview({token_import:offer(extra)})),null);
          const ctx=await open(preview({token_import:offer({ready:false,problems:[{line:2,message:'Source quantity is not recorded.'}]})}));
          assert.equal(ctx.tokenChoice,null);assert(ctx.area.textContent.includes('Source quantity is not recorded.'));
          const blocked=await open(preview({editable:false}));assert.equal(blocked.tokenChoice,null);assert(!addButton(blocked));
        ''')

    def test_invalid_source_rows_and_problem_reports_cannot_be_treated_as_ready_evidence(self):
        self.run_js(r'''
          for(const extra of [{problems:[{line:1,message:'Unknown source count'}]},{problems:'malformed'},
            {rows:[{front:'Dog'+String.fromCharCode(10)+'hidden',quantity:3,source_row:1,notes:'Unknown'}]},
            {rows:[{front:'Dog',quantity:2,source_row:1,notes:'Unknown'},{front:'The Monarch',quantity:1,source_row:1,notes:'Unknown'}]}])
            assert.equal(preconTokenOffer(preview({token_import:offer(extra)})),null);
        ''')

    def test_checkbox_rejected_changes_roll_back_for_busy_stale_preview_profile_and_detached_controls(self):
        self.run_js(r'''
          for(const mode of ['busy','preview','profile','detached','closed']){
            const ctx=await open(),node=ctx.tokenChoice.node;
            if(mode==='busy')ctx.busy=true;if(mode==='preview')ctx.preview={...ctx.preview};
            if(mode==='profile')state.profile=PROFILES[1];if(mode==='detached')node.remove();if(mode==='closed')ctx.sheet.close();
            node.checked=true;node.fire('change');assert.equal(node.checked,false,mode);
          }
        ''')

    def test_token_conflict_requires_a_fresh_unchecked_preview_and_keeps_custom_title(self):
        self.run_js(r'''
          const ctx=await open();ctx.titleInput.value='Kept custom title';choose(ctx);const old=addButton(ctx),writes=[],reads=[];
          apiWrite=async(path,body)=>{writes.push(body);throw new ApiError(409,'Token list changed',{token_conflict:true});};
          await addPrecon(ctx);assert(ctx.tokenPreviewStale);assert(!addButton(ctx));assert(textButton(ctx,'Preview again'));
          old.fire('click');await flush();assert.equal(writes.length,1);
          api=async path=>{reads.push(path);return preview({title:'Server default title',token_import:offer({sha256:'b'.repeat(64),source_sha256:'d'.repeat(64)})});};
          textButton(ctx,'Preview again').click();await flush();assert.equal(reads.length,1);
          assert(reads[0].startsWith('/api/precons/preview?'));assert.equal(ctx.titleInput.value,'Kept custom title');
          assert(!ctx.tokenChoice.node.checked);assert(!ctx.tokenPreviewStale);
          choose(ctx);apiWrite=async(path,body)=>{writes.push(body);return added();};await addPrecon(ctx);
          assert.equal(writes.length,2);assert.equal(writes[1].tokens_sha256,'b'.repeat(64));assert.equal(writes[1].tokens_source_sha256,'d'.repeat(64));
          assert.equal(writes[1].title,'Kept custom title');
        ''')

    def test_opted_in_collection_conflict_also_requires_fresh_token_review(self):
        self.run_js(r'''
          const ctx=await open();choose(ctx);apiWrite=async()=>{throw new ApiError(409,'Collection changed',{sha256:'collection-later',rows:[]});};
          await addPrecon(ctx);assert(textButton(ctx,'Preview again'));assert(!textButton(ctx,'Add to the latest list'));
          assert(ctx.tokenPreviewStale);assert(ctx.tokenChoice.node.disabled);
        ''')

    def test_source_digest_conflict_uses_fresh_review_without_resubmitting_the_old_source(self):
        self.run_js(r'''
          const ctx=await open();choose(ctx);const writes=[];ctx.titleInput.value='Source-reviewed custom title';
          apiWrite=async(path,body)=>{writes.push(body);throw new ApiError(409,'Source token counts changed',{token_conflict:true,token_source_conflict:true});};
          await addPrecon(ctx);assert(textButton(ctx,'Preview again'));assert.equal(writes.length,1);
          assert.equal(writes[0].tokens_source_sha256,'c'.repeat(64));await addPrecon(ctx);assert.equal(writes.length,1);
          api=async()=>preview({token_import:offer({source_sha256:'e'.repeat(64)})});textButton(ctx,'Preview again').click();await flush();
          assert.equal(ctx.titleInput.value,'Source-reviewed custom title');assert(!ctx.tokenChoice.node.checked);
        ''')

    def test_unconfirmed_source_details_are_not_inferred_or_copied_into_the_write(self):
        self.run_js(r'''
          const tokens=offer();tokens.rows[0]={...tokens.rows[0],set:'unverified-set',finish:'foil',back:'Unverified reverse'};
          const ctx=await open(preview({token_import:tokens}));assert(!ctx.area.textContent.includes('Unverified reverse'));
          assert(!ctx.area.textContent.includes('unverified-set'));assert(ctx.area.textContent.includes('stay unconfirmed'));choose(ctx);
          let body;apiWrite=async(path,payload)=>{body=payload;return added();};await addPrecon(ctx);
          assert(!Object.hasOwn(body,'rows'));assert(!Object.hasOwn(body,'set'));assert(!Object.hasOwn(body,'finish'));assert(!Object.hasOwn(body,'back'));
          assert.equal(body.tokens_source_sha256,'c'.repeat(64));
        ''')

    def test_ordinary_collection_conflict_retains_existing_add_to_latest_behavior_without_tokens(self):
        self.run_js(r'''
          const ctx=await open();ctx.titleInput.value='Custom deck';const writes=[];
          apiWrite=async(path,body)=>{writes.push(body);if(writes.length===1)throw new ApiError(409,'Collection changed',{sha256:'collection-later',rows:[]});return added();};
          await addPrecon(ctx);assert(!textButton(ctx,'Preview again'));assert(textButton(ctx,'Add to the latest list'));
          textButton(ctx,'Add to the latest list').click();await flush();assert.equal(writes.length,2);
          assert.equal(writes[1].sha256,'collection-later');assert.equal(writes[1].title,'Custom deck');assert(!('add_tokens' in writes[1]));
        ''')

    def test_opt_in_unknown_outcome_latches_no_retry_or_repeated_add(self):
        self.run_js(r'''
          const ctx=await open();choose(ctx);const old=addButton(ctx),writes=[];apiWrite=async(path,body)=>{writes.push(body);throw Error('Lost response');};
          await addPrecon(ctx);assert(ctx.message.textContent.includes("isn't known"));assert(ctx.message.textContent.includes('Tokens page'));
          assert(textButton(ctx,'Close'));assert(!textButton(ctx,'Preview again'));assert(!addButton(ctx));
          old.fire('click');await addPrecon(ctx);await flush();assert.equal(writes.length,1);
        ''')

    def test_late_success_cannot_navigate_or_create_a_receipt_for_a_new_profile_route_or_page(self):
        self.run_js(r'''
          for(const mode of ['profile','route','page']){
            const ctx=await open();choose(ctx);let resolve;apiWrite=()=>new Promise(done=>resolve=done);const pending=addPrecon(ctx);
            if(mode==='profile')state.profile=PROFILES[1];if(mode==='route')routeToken++;if(mode==='page')ctx.cv.root.remove();
            resolve(added());await pending;assert.equal(state.saved,null,mode);assert.equal(location.hash,'#/collection',mode);
          }
        ''')

    def test_late_preview_does_not_install_token_choices_into_another_profile_or_replaced_preview(self):
        self.run_js(r'''
          const ctx=await open();let resolve;api=()=>new Promise(done=>resolve=done);const pending=previewPrecon(ctx,ctx.preview.deck);
          state.profile=PROFILES[1];resolve(preview());await pending;assert.equal(ctx.preview,null);assert(!ctx.area.querySelector('.precon-tokens'));
        ''')

    def test_receipt_uses_confirmed_counts_and_never_crosses_profile_or_address(self):
        self.run_js(r'''
          const ctx=await open();choose(ctx);apiWrite=async()=>added();await addPrecon(ctx);const hash=location.hash;
          let box=savedBox('casual/fixture');assert(box.textContent.includes('3 token cards also added as unconfirmed rows'));
          assert(!box.textContent.includes('99 token'));state.profile=PROFILES[1];assert.equal(savedBox('casual/fixture'),null);
          state.profile=PROFILES[0];location.hash='#/deck?id=casual/another';assert.equal(savedBox('casual/fixture'),null);location.hash=hash;
          assert(savedBox('casual/fixture'));
        ''')

    def test_inconsistent_or_missing_saved_token_counters_show_uncertain_receipt(self):
        self.run_js(r'''
          for(const tokens of [undefined,{cards:-1,rows:2},{cards:2.5,rows:2},{cards:999,rows:0}]){
            const ctx=await open();choose(ctx);apiWrite=async()=>added({tokens});await addPrecon(ctx);
            const box=savedBox('casual/fixture');assert(box.textContent.includes('token addition count was not confirmed'));
            assert(!box.textContent.includes('999 token cards'));
          }
        ''')
