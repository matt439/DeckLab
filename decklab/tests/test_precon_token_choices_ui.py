"""Explicit physical counts/face choices over fixture precon previews, never real inventory writes."""
import unittest

from decklab.tests import test_precon_tokens_ui as precon_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class PreconTokenChoicesUiTests(unittest.TestCase):
    def run_js(self, scenario):
        precon_ui.PreconTokensUiTests.run_js(self, r'''
          const physical=extra=>offer({ready:false,rows:[],cards:0,problems:[{line:1,message:'Source count unknown'}],
            choices_ready:true,choice_problems:[],options:[{source_row:1,source_name:'Dog',fronts:['Dog'],quantity:null},
              {source_row:2,source_name:'Goblin // Zombie Knight',fronts:['Goblin','Zombie Knight'],quantity:2},
              {source_row:3,source_name:'The Monarch',fronts:['The Monarch'],quantity:1}],...extra});
          const openChoices=extra=>open(preview({token_import:physical(extra)}));
          const controls=ctx=>ctx.tokenChoice.options;
          const qty=(ctx,index,value)=>{const input=controls(ctx)[index].quantity;input.value=value;input.fire('input');return input;};
          const face=(ctx,index,value)=>{const input=controls(ctx)[index].front;input.value=value;input.fire('change');return input;};
          const fill=ctx=>{choose(ctx);qty(ctx,0,'3');qty(ctx,1,'0');return ctx;};
          const confirmed=extra=>added({tokens:{cards:4,rows:2},...extra});
        ''' + scenario)

    def test_unknown_blank_known_declared_counts_and_unchecked_native_offer(self):
        self.run_js(r'''
          const ctx=await openChoices(),choice=ctx.tokenChoice;assert(choice);assert(!choice.node.checked);
          same(controls(ctx).map(row=>row.quantity.value),['','2','1']);assert(controls(ctx).every(row=>row.quantity.disabled));
          assert.equal(controls(ctx)[1].front.value,'');assert(controls(ctx)[1].front.disabled);
          for(const row of controls(ctx)){
            assert.equal(row.quantity.getAttribute('type'),'number');assert.equal(row.quantity.getAttribute('min'),'0');
            assert.equal(row.quantity.getAttribute('step'),'1');assert.equal(row.quantity.parentNode.getAttribute('for'),row.quantity.id);
          }
          for(const words of ['Source entries may describe two faces of the same physical card','Count that card once',
            'set the other entry to 0','does not pair entries or merge them automatically','Review every entry',
            'Printing, finish and reverse face stay unknown','Source declares 2','does not declare a physical quantity'])
            assert(ctx.area.textContent.includes(words),words);
          choose(ctx);assert(controls(ctx).every(row=>!row.quantity.disabled));assert(!controls(ctx)[1].front.disabled);
        ''')

    def test_every_option_in_exact_request_and_positive_receipt_counts_not_legacy_zero(self):
        self.run_js(r'''
          const ctx=fill(await openChoices());ctx.titleInput.value='Physical review deck';const calls=[];
          apiWrite=async(path,body)=>{calls.push([path,body]);return confirmed();};await addPrecon(ctx);
          same(calls,[['/api/precons/add',{space:'home',file:'Fixture_TST',title:'Physical review deck',sha256:'collection-first',
            add_tokens:true,tokens_sha256:'a'.repeat(64),tokens_source_sha256:'c'.repeat(64),tokens_choices:[
              {source_row:1,front:'Dog',quantity:3},{source_row:2,front:'',quantity:0},{source_row:3,front:'The Monarch',quantity:1}]}]]);
          assert.equal(state.saved.answer.precon.tokens,4);assert.equal(state.saved.profile,'matt');
          assert(savedBox('casual/fixture').textContent.includes('4 token cards also added as unconfirmed rows'));
        ''')

    def test_unchecked_new_offer_omits_all_token_fields_even_with_unknown_entries(self):
        self.run_js(r'''
          const ctx=await openChoices();let body;apiWrite=async(path,payload)=>{body=payload;return added();};await addPrecon(ctx);
          for(const field of ['add_tokens','tokens_sha256','tokens_source_sha256','tokens_choices'])assert(!Object.hasOwn(body,field),field);
          assert(!Object.hasOwn(state.saved.answer.precon,'tokens'));
        ''')

    def test_missing_invalid_or_out_of_bound_quantity_blocks_add_and_focuses_owned_input(self):
        self.run_js(r'''
          for(const value of ['','-1','1.5','251','NaN','Infinity','1e2','  ']){
            const ctx=await openChoices();choose(ctx);const input=qty(ctx,0,value);qty(ctx,1,'0');let writes=0;
            apiWrite=async()=>{writes++;return confirmed();};await addPrecon(ctx);assert.equal(writes,0,value);
            assert.equal(document.activeElement,input);assert(ctx.tokenChoice.message.textContent.includes('Use 0 to skip'));
          }
        ''')

    def test_ambiguous_positive_quantity_requires_canonical_face_and_zero_can_skip_without_face(self):
        self.run_js(r'''
          const ctx=await openChoices();choose(ctx);qty(ctx,0,'0');let body,writes=0;
          apiWrite=async(path,payload)=>{writes++;body=payload;return confirmed({tokens:{cards:3,rows:2}});};
          await addPrecon(ctx);assert.equal(writes,0);assert.equal(document.activeElement,controls(ctx)[1].front);
          assert(ctx.tokenChoice.message.textContent.includes('Choose the face to record for entry 2'));
          face(ctx,1,'Zombie Knight');await addPrecon(ctx);assert.equal(writes,1);
          same(body.tokens_choices,[{source_row:1,front:'Dog',quantity:0},{source_row:2,front:'Zombie Knight',quantity:2},
            {source_row:3,front:'The Monarch',quantity:1}]);
        ''')

    def test_zero_for_every_entry_requires_explicit_opt_out_instead_of_silent_no_tokens(self):
        self.run_js(r'''
          const ctx=await openChoices();choose(ctx);for(let i=0;i<3;i++)qty(ctx,i,'0');let writes=0,body;
          apiWrite=async(path,payload)=>{writes++;body=payload;return added();};await addPrecon(ctx);assert.equal(writes,0);
          assert(ctx.tokenChoice.message.textContent.includes('untick Add its token cards too'));assert.equal(document.activeElement,ctx.tokenChoice.node);
          ctx.tokenChoice.node.checked=false;ctx.tokenChoice.node.fire('change');await addPrecon(ctx);assert.equal(writes,1);
          assert(!Object.hasOwn(body,'tokens_choices'));assert(!Object.hasOwn(body,'add_tokens'));
        ''')

    def test_duplicate_canonical_faces_stay_separate_and_counts_track_positive_entries(self):
        self.run_js(r'''
          const ctx=await openChoices({options:[{source_row:7,source_name:'Dog A',fronts:['Dog'],quantity:2},
            {source_row:9,source_name:'Dog B',fronts:['Dog'],quantity:3}]});choose(ctx);let body;
          apiWrite=async(path,payload)=>{body=payload;return confirmed({tokens:{cards:5,rows:2}});};await addPrecon(ctx);
          same(body.tokens_choices,[{source_row:7,front:'Dog',quantity:2},{source_row:9,front:'Dog',quantity:3}]);
          assert.equal(state.saved.answer.precon.tokens,5);
        ''')

    def test_malformed_new_options_never_fall_back_to_a_valid_legacy_offer(self):
        self.run_js(r'''
          const bad=[{options:null},{options:[]},{choices_ready:false},{choice_problems:null},{choice_problems:[{message:'Unavailable'}]},
            {sha256:'short'},{source_sha256:null},{editable:false},
            {options:[{source_row:1,source_name:'Dog',fronts:['Dog'],quantity:0}]},
            {options:[{source_row:1,source_name:'Dog',fronts:['Dog'],quantity:251}]},
            {options:[{source_row:1,source_name:'Dog',fronts:[],quantity:null}]},
            {options:[{source_row:1,source_name:'Dog',fronts:['Dog','Dog'],quantity:null}]},
            {options:[{source_row:1,source_name:'Dog',fronts:['Dog','Cat','Rabbit'],quantity:null}]},
            {options:[{source_row:1,source_name:'Dog',fronts:['Dog'],quantity:null},{source_row:1,source_name:'Cat',fronts:['Cat'],quantity:1}]},
            {options:[{source_row:0,source_name:'Dog',fronts:['Dog'],quantity:null}]},
            {options:[{source_row:1,source_name:'Dog'+String.fromCharCode(10)+'bad',fronts:['Dog'],quantity:null}]}];
          for(const extra of bad){const raw=physical({...offer(),...extra});assert.equal(preconTokenOffer(preview({token_import:raw})),null);
            const ctx=await open(preview({token_import:raw}));assert.equal(ctx.tokenChoice,null);}
        ''')

    def test_unresolvable_source_explains_static_problem_without_blocking_playable_precon(self):
        self.run_js(r'''
          const ctx=await openChoices({choices_ready:false,choice_problems:[{message:'Token names cannot be checked yet.'}]});
          assert.equal(ctx.tokenChoice,null);assert(ctx.area.textContent.includes('Token names cannot be checked yet.'));
          assert(addButton(ctx));let body;apiWrite=async(path,payload)=>{body=payload;return added();};await addPrecon(ctx);assert(!body.add_tokens);
        ''')

    def test_busy_fields_and_checkbox_roll_back_programmatic_changes_and_duplicate_add_is_guarded(self):
        self.run_js(r'''
          const ctx=fill(await openChoices());let resolve,writes=0;apiWrite=()=>{writes++;return new Promise(r=>resolve=r);};
          const pending=addPrecon(ctx);assert(ctx.tokenChoice.node.disabled);assert(ctx.tokenChoice.inputs.every(input=>input.disabled));
          qty(ctx,0,'99');face(ctx,1,'Goblin');ctx.tokenChoice.node.checked=false;ctx.tokenChoice.node.fire('change');
          assert.equal(controls(ctx)[0].quantity.value,'3');assert.equal(controls(ctx)[1].front.value,'');assert(ctx.tokenChoice.node.checked);
          addButton(ctx).fire('click');await addPrecon(ctx);assert.equal(writes,1);resolve(confirmed());await pending;
        ''')

    def test_stale_review_inputs_and_opted_in_write_check_profile_route_preview_scope_and_both_hashes(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','seq','preview','space','tokenSha','sourceSha','option','file','collectionSha','closed','root','permission']){
            const ctx=fill(await openChoices()),choice=ctx.tokenChoice;let writes=0;apiWrite=async()=>{writes++;return confirmed();};
            if(mode==='profile')state.profile=PROFILES[1];if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/tokens';
            if(mode==='seq')ctx.seq++;if(mode==='preview')ctx.preview={...ctx.preview};if(mode==='space')ctx.cv.space='user2';
            if(mode==='tokenSha')choice.offer.sha256='b'.repeat(64);if(mode==='sourceSha')choice.offer.source_sha256='d'.repeat(64);
            if(mode==='option')choice.offer.options[0].fronts=['Cat'];if(mode==='file')ctx.preview.deck.file='Different_TST';
            if(mode==='collectionSha')ctx.preview.sha256='changed';if(mode==='closed')ctx.sheet.close();
            if(mode==='root'){const root=el('div');main.append(root);ctx.cv.root=root;}if(mode==='permission')state.may={spaces:[]};
            qty(ctx,0,'99');assert.equal(controls(ctx)[0].quantity.value,'3',mode);await addPrecon(ctx);assert.equal(writes,0,mode);
          }
        ''')

    def test_detached_quantity_or_face_control_cannot_supply_a_hidden_unreviewed_write(self):
        self.run_js(r'''
          for(const which of ['quantity','face']){const ctx=fill(await openChoices());const row=controls(ctx)[which==='quantity'?0:1];
            const input=which==='quantity'?row.quantity:row.front;input.remove();input.value=which==='quantity'?'99':'Goblin';input.fire('change');
            assert.equal(input.value,which==='quantity'?'3':'');let writes=0;apiWrite=async()=>{writes++;return confirmed();};
            await addPrecon(ctx);assert.equal(writes,0);}
        ''')

    def test_unchecked_review_fields_are_hidden_disabled_and_reject_late_field_events(self):
        self.run_js(r'''
          const ctx=fill(await openChoices());ctx.tokenChoice.node.checked=false;ctx.tokenChoice.node.fire('change');
          assert(ctx.tokenChoice.inputs.every(input=>input.disabled));qty(ctx,0,'99');face(ctx,1,'Goblin');
          assert.equal(controls(ctx)[0].quantity.value,'3');assert.equal(controls(ctx)[1].front.value,'');
          choose(ctx);assert.equal(controls(ctx)[0].quantity.value,'3');assert(!controls(ctx)[0].quantity.disabled);
        ''')

    def test_conflict_requires_fresh_unchecked_review_and_preserves_custom_title(self):
        self.run_js(r'''
          const ctx=fill(await openChoices());ctx.titleInput.value='Keep my title';let writes=0,reads=0;const old=addButton(ctx);
          apiWrite=async()=>{writes++;throw new ApiError(409,'Source changed',{token_conflict:true});};await addPrecon(ctx);
          assert.equal(writes,1);assert(ctx.tokenPreviewStale);assert(ctx.tokenChoice.inputs.every(input=>input.disabled));
          old.fire('click');assert.equal(writes,1);api=async()=>{reads++;return preview({token_import:physical({sha256:'b'.repeat(64),source_sha256:'d'.repeat(64)})});};
          textButton(ctx,'Preview again').click();await flush();assert.equal(reads,1);assert.equal(ctx.titleInput.value,'Keep my title');
          assert(!ctx.tokenChoice.node.checked);same(controls(ctx).map(row=>row.quantity.value),['','2','1']);
          fill(ctx);let body;apiWrite=async(path,payload)=>{writes++;body=payload;return confirmed();};await addPrecon(ctx);
          assert.equal(writes,2);assert.equal(body.tokens_sha256,'b'.repeat(64));assert.equal(body.tokens_source_sha256,'d'.repeat(64));
        ''')

    def test_opted_in_collection_revision_conflict_cannot_reuse_old_physical_review(self):
        self.run_js(r'''
          const ctx=fill(await openChoices());apiWrite=async()=>{throw new ApiError(409,'Collection changed',{sha256:'latest'});};await addPrecon(ctx);
          assert(textButton(ctx,'Preview again'));assert(!textButton(ctx,'Add to the latest list'));assert(ctx.tokenPreviewStale);
          assert(ctx.tokenChoice.inputs.every(input=>input.disabled));
        ''')

    def test_unknown_outcome_has_no_automatic_retry_or_repreview_and_disables_all_physical_controls(self):
        self.run_js(r'''
          const ctx=fill(await openChoices()),old=addButton(ctx);let writes=0,reads=0;
          api=async()=>{reads++;return preview();};apiWrite=async()=>{writes++;throw Error('Lost response');};await addPrecon(ctx);
          assert.equal(writes,1);assert.equal(reads,0);assert(textButton(ctx,'Close'));assert(!textButton(ctx,'Preview again'));
          assert(ctx.message.textContent.includes('Tokens page'));assert(ctx.tokenChoice.inputs.every(input=>input.disabled));
          old.fire('click');await addPrecon(ctx);assert.equal(writes,1);
        ''')

    def test_late_known_success_cannot_navigate_or_record_receipt_for_changed_review_or_page(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','page','preview','tokenSha','sourceSha','option']){
            const ctx=fill(await openChoices());let resolve;apiWrite=()=>new Promise(r=>resolve=r);const pending=addPrecon(ctx);
            if(mode==='profile')state.profile=PROFILES[1];if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/tokens';
            if(mode==='page')ctx.cv.root.remove();if(mode==='preview')ctx.preview={...ctx.preview};
            if(mode==='tokenSha')ctx.tokenChoice.offer.sha256='b'.repeat(64);if(mode==='sourceSha')ctx.tokenChoice.offer.source_sha256='d'.repeat(64);
            if(mode==='option')ctx.tokenChoice.offer.options[0].fronts=['Cat'];const hash=location.hash;
            resolve(confirmed());await pending;assert.equal(state.saved,null,mode);assert.equal(location.hash,hash,mode);
          }
        ''')

    def test_exact_positive_row_and_card_receipt_required_for_confirmed_count(self):
        self.run_js(r'''
          for(const tokens of [undefined,{cards:4,rows:3},{cards:3,rows:2},{cards:4,rows:1},{cards:4,rows:true}]){
            const ctx=fill(await openChoices());apiWrite=async()=>confirmed({tokens});await addPrecon(ctx);
            assert.equal(state.saved.answer.precon.tokens,null);assert(state.saved.answer.precon.tokens_uncertain);
            assert(savedBox('casual/fixture').textContent.includes('token addition count was not confirmed'));
          }
        ''')

    def test_explicit_null_token_list_receipt_and_unknown_printing_fields_stay_exact(self):
        self.run_js(r'''
          const ctx=fill(await openChoices({sha256:null}));let body;apiWrite=async(path,payload)=>{body=payload;return confirmed();};await addPrecon(ctx);
          assert(Object.hasOwn(body,'tokens_sha256'));assert.equal(body.tokens_sha256,null);
          assert(body.tokens_choices.every(row=>Object.keys(row).sort().join(',')==='front,quantity,source_row'));
          const box=savedBox('casual/fixture');assert(box);state.profile=PROFILES[1];assert.equal(savedBox('casual/fixture'),null);
        ''')

    def test_legacy_offer_without_options_keeps_its_existing_exact_request_shape(self):
        self.run_js(r'''
          const ctx=await open();choose(ctx);let body;apiWrite=async(path,payload)=>{body=payload;return added();};await addPrecon(ctx);
          assert.equal(body.add_tokens,true);assert(!Object.hasOwn(body,'tokens_choices'));assert.equal(state.saved.answer.precon.tokens,3);
        ''')

    def test_upper_quantity_bound_is_a_local_explicit_choice_without_using_source_count(self):
        self.run_js(r'''
          const ctx=fill(await openChoices());qty(ctx,0,'250');let body;apiWrite=async(path,payload)=>{body=payload;return confirmed({tokens:{cards:251,rows:2}});};
          await addPrecon(ctx);assert.equal(body.tokens_choices[0].quantity,250);assert.equal(state.saved.answer.precon.tokens,251);
        ''')

    def test_second_modal_blocks_physical_input_changes_and_opted_in_activation(self):
        self.run_js(r'''
          const ctx=fill(await openChoices());const other=openSheet('Other review');qty(ctx,0,'99');face(ctx,1,'Goblin');
          assert.equal(controls(ctx)[0].quantity.value,'3');assert.equal(controls(ctx)[1].front.value,'');let writes=0;
          apiWrite=async()=>{writes++;return confirmed();};await addPrecon(ctx);assert.equal(writes,0);other.close();
        ''')

    def test_retired_add_button_cannot_save_a_new_preview_even_if_reattached(self):
        self.run_js(r'''
          for(const reattach of [false,true]){
            const ctx=await openChoices(),old=addButton(ctx);ctx.preview=preview({title:'A newer preview',token_import:physical()});drawPreconPreview(ctx);
            if(reattach)ctx.sheet.foot.append(old);let writes=0;apiWrite=async()=>{writes++;return confirmed();};
            old.fire('click');await flush();assert.equal(writes,0,String(reattach));
          }
        ''')

    def test_retired_add_to_latest_button_cannot_write_new_preview_and_top_modal_guards_opt_out(self):
        self.run_js(r'''
          const ctx=await openChoices();apiWrite=async()=>{throw new ApiError(409,'Collection changed',{sha256:'latest'});};await addPrecon(ctx);
          const old=textButton(ctx,'Add to the latest list');assert(old);ctx.preview=preview({title:'New preview',token_import:physical()});drawPreconPreview(ctx);
          ctx.sheet.foot.append(old);let writes=0;apiWrite=async()=>{writes++;return added();};old.fire('click');await flush();assert.equal(writes,0);
          const other=openSheet('Other review');addButton(ctx).fire('click');await flush();assert.equal(writes,0);other.close();
        ''')

    def test_known_success_after_closed_or_replaced_review_invalidates_old_cache_without_navigation(self):
        self.run_js(r'''
          for(const mode of ['closed','preview','profile']){
            const ctx=fill(await openChoices());state.library={decks:['cached']};assert(ctx.cv.rows);let resolve;
            apiWrite=()=>new Promise(r=>resolve=r);const pending=addPrecon(ctx);
            if(mode==='closed')ctx.sheet.close();if(mode==='preview')ctx.preview={...ctx.preview};if(mode==='profile')state.profile=PROFILES[1];
            resolve(confirmed());await pending;assert.equal(ctx.cv.rows,null,mode);assert.equal(state.library,null,mode);
            assert.equal(state.saved,null);assert.equal(location.hash,'#/collection');
          }
        ''')

    def test_unaccepted_hidden_checkbox_change_cannot_submit_prefilled_physical_choices(self):
        self.run_js(r'''
          const ctx=await openChoices({options:[{source_row:1,source_name:'Dog',fronts:['Dog'],quantity:2}]});
          ctx.tokenChoice.node.checked=true;let writes=0;apiWrite=async()=>{writes++;return confirmed({tokens:{cards:2,rows:1}});};
          await addPrecon(ctx);assert.equal(writes,0);assert(ctx.tokenChoice.fields.hidden);
          ctx.tokenChoice.node.fire('change');await addPrecon(ctx);assert.equal(writes,1);
        ''')

    def test_json_proxy_server_error_is_uncertain_and_cannot_retry(self):
        self.run_js(r'''
          const ctx=fill(await openChoices());let writes=0;const old=addButton(ctx);
          apiWrite=async()=>{writes++;throw new ApiError(502,'Upstream response unavailable',{error:'Gateway failed'});};await addPrecon(ctx);
          assert(ctx.tokenPreviewStale);assert(textButton(ctx,'Close'));assert(!addButton(ctx));old.fire('click');await addPrecon(ctx);
          assert.equal(writes,1);assert(ctx.message.textContent.includes("isn't known"));
        ''')


if __name__ == "__main__":
    unittest.main()
