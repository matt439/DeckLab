"""Explicit arrival-check targets bind original Shopping rows and preview receipts.

Node DOM/API doubles only; no real order, browser or database writes.
"""
import unittest

from decklab.tests import test_shopping_order_edit_ui as support
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingCheckTargetsUiTests(unittest.TestCase):
    run_js = support.ShoppingOrderEditInteractionTests.run_js

    def target_js(self, scenario):
        support.ShoppingOrderEditInteractionTests.edit_js(self, r'''
          const payloadHash='a'.repeat(64), rowHashes=['b'.repeat(64),'c'.repeat(64)];
          const targetCardRow=(extra={})=>({name:'Fixture Card',set:'fdn',collector_number:'227',finish:'nonfoil',
            quantity:'2',condition:'',language:'',notes:'',...extra});
          const cardPart=(extra={})=>component({checks:['Confirm the art','Check the reverse'],
            edit_rows:[targetCardRow(),targetCardRow({set:'tst',collector_number:'9',finish:'foil',quantity:'1'})],
            check_targeting:{available:true,payload_sha256:payloadHash,row_sha256s:[...rowHashes]},...extra});
          const openCheck=(part=cardPart(),number=null)=>{
            clear(main);
            const targetOrder={...pending,components:[part]},view=drawShopping({...data,orders:[targetOrder]});
            const parent=shopOrderEditSheet(targetOrder,view);
            assert(parent,'Target order editor opens');
            if(number===null)button(parent.body,'Add check\u2026').click();
            else parent.body.querySelectorAll('button').filter(node=>node.textContent==='Withdraw\u2026')[number-1].click();
            return{sheet:latest(),part,parent,view};
          };
          const chooseTarget=(sheet,value,event=true)=>{const select=field(sheet,'check_target');select.value=value;if(event)select.fire('change');return select;};
          const hasSave=sheet=>sheet.foot.querySelectorAll('button').some(node=>node.textContent==='Save change');
          const targetAnswer=(body,extra={})=>({...previewAnswer,checks:[{component:body.component,
            checks:['Confirm the art','Check the reverse',...(body.add||[])]}],targeted_check:body.target?{
            component:body.component,check:3,text:body.add[0],row:body.target.row,
            row_sha256:rowHashes[body.target.row-1],payload_sha256:body.target.payload_sha256}:null,...extra});
          const prepare=(sheet,value='2')=>{type(sheet,'check','Inspect the exact printing');chooseTarget(sheet,value);};
          const resetOwner=()=>{state.profile={id:'matt',name:'Matt',role:'admin',space:'home'};
            state.may={admin:true,orders:true,see_inventory:['home']};clear(main);};
        ''' + scenario)

    def test_numbered_options_distinguish_duplicate_names_and_start_with_general(self):
        self.target_js(r'''
          const {sheet}=openCheck(),select=field(sheet,'check_target'),options=select.querySelectorAll('option');
          assert.equal(select.value,'');assert.equal(options.length,3);assert(options[0].textContent.includes('General'));
          assert(options[1].textContent.includes('Row 1: 2 x Fixture Card'));assert(options[1].textContent.includes('FDN 227'));
          assert(options[1].textContent.includes('nonfoil'));assert(options[2].textContent.includes('Row 2: 1 x Fixture Card'));
          assert(options[2].textContent.includes('TST 9'));assert(options[2].textContent.includes('foil'));
          assert(sheet.body.querySelectorAll('label').some(node=>node.getAttribute('for')===select.id));
          assert(sheet.body.textContent.includes('whole delivery part'));assert(!hasSave(sheet));
        ''')

    def test_general_check_request_omits_target_and_keeps_existing_preview_flow(self):
        self.target_js(r'''
          const {sheet}=openCheck(),writes=[];apiWrite=async(path,body)=>{writes.push([path,body]);return previewAnswer;};
          type(sheet,'check','A general inspection');action(sheet,'Preview change').click();await settle();
          same(writes,[['/api/shopping/order/change/preview',{expect:'revision-1',order:pending.id,action:'checks',component:'cards',add:['A general inspection']}]]);
          assert(hasSave(sheet));assert.equal(sheet.body.querySelector('.shop-order-check-target'),null);
        ''')

    def test_general_text_blur_keeps_the_pointer_down_preview_button_and_previews_once(self):
        self.target_js(r'''
          const {sheet}=openCheck(),writes=[];apiWrite=async(path,body)=>{writes.push([path,body]);return previewAnswer;};
          type(sheet,'check','A general inspection');
          const preview=action(sheet,'Preview change');preview.fire('pointerdown');
          field(sheet,'check').fire('change');
          assert.equal(action(sheet,'Preview change'),preview);assert(preview.isConnected);
          preview.fire('pointerup');preview.click();await settle();
          assert.equal(writes.length,1);assert.equal(writes[0][1].target,undefined);assert(hasSave(sheet));
        ''')

    def test_targeted_text_and_select_duplicate_events_keep_same_preview_button(self):
        self.target_js(r'''
          const {sheet}=openCheck(),writes=[];apiWrite=async(path,body)=>{writes.push([path,body]);return targetAnswer(body);};
          prepare(sheet);const preview=action(sheet,'Preview change');preview.fire('pointerdown');
          field(sheet,'check').fire('change');field(sheet,'check_target').fire('input');field(sheet,'check_target').fire('change');
          assert.equal(action(sheet,'Preview change'),preview);assert(preview.isConnected);
          preview.fire('pointerup');preview.click();await settle();
          assert.equal(writes.length,1);same(writes[0][1].target,{row:2,payload_sha256:payloadHash});assert(hasSave(sheet));
        ''')

    def test_common_checkbox_uses_checked_state_and_duplicate_change_keeps_current_actions(self):
        self.target_js(r'''
          const targetOrder={...pending,components:[cardPart()]},view=drawShopping({...data,orders:[targetOrder]});
          const form=el('form'),check=el('input',{type:'checkbox',value:'constant'});form.append(check);
          const edit=shopOrderChangeSheet(targetOrder,view,'Checkbox change',form,()=>({action:'record',values:{notes:check.checked?'yes':'no'}}));
          edit.bind();edit.bind();const sheet=edit.sheet,writes=[];
          apiWrite=async(path,body)=>{writes.push([path,body]);return previewAnswer;};
          const initial=action(sheet,'Preview change');check.checked=true;check.fire('input');
          const updated=action(sheet,'Preview change');assert.notEqual(updated,initial);
          check.fire('change');assert.equal(action(sheet,'Preview change'),updated);
          updated.click();await settle();assert(hasSave(sheet));assert.equal(writes[0][1].values.notes,'yes');
          const saved=action(sheet,'Save change');check.fire('input');check.fire('change');
          assert.equal(action(sheet,'Save change'),saved);
          check.checked=false;check.fire('change');assert(!hasSave(sheet));assert.equal(writes.length,1);
        ''')

    def test_explicit_target_sends_original_payload_receipt_and_reviews_exact_row(self):
        self.target_js(r'''
          const {sheet}=openCheck(),writes=[];let refreshes=0;route=()=>{refreshes++;};
          let reviewedBody;apiWrite=async(path,body)=>{writes.push([path,body]);if(path.endsWith('/preview')){reviewedBody=body;return targetAnswer(body);}
            return{...targetAnswer(reviewedBody),saved:true};};
          prepare(sheet);action(sheet,'Preview change').click();await settle();
          same(writes[0],['/api/shopping/order/change/preview',{expect:'revision-1',order:pending.id,action:'checks',component:'cards',
            add:['Inspect the exact printing'],target:{row:2,payload_sha256:payloadHash}}]);
          const proof=sheet.body.querySelector('.shop-order-check-target');assert(proof);assert(proof.textContent.includes('Row 2: 1 x Fixture Card'));
          assert(proof.textContent.includes('TST 9'));assert(proof.textContent.includes('foil'));assert(proof.textContent.includes('Inspect the exact printing'));
          assert(proof.textContent.includes('whole delivery part'));action(sheet,'Save change').click();action(sheet,'Saving…').click();await settle();
          same(writes[1],['/api/shopping/order/change/apply',{preview:'signed-change'}]);assert.equal(writes.length,2);assert.equal(refreshes,1);
          assert.equal(writes[0][1].target.row_sha256,undefined);assert.equal(writes[0][1].target.name,undefined);
        ''')

    def test_token_options_identify_paired_faces_printing_and_physical_quantity(self):
        self.target_js(r'''
          const token=(extra={})=>({front:'Dog',back:'Beast',set:'tst',front_collector_number:'1',back_collector_number:'2',finish:'foil',quantity:'3',
            front_details:'',back_details:'',notes:'',...extra});
          const {sheet}=openCheck(cardPart({id:'tokens',kind:'tokens',edit_rows:[token(),token({front:'Treasure',back:'',front_collector_number:'4',back_collector_number:'',finish:'nonfoil',quantity:'1'})]}));
          const labels=field(sheet,'check_target').querySelectorAll('option').map(node=>node.textContent);
          assert(labels[1].includes('Row 1: 3 x Dog // Beast'));assert(labels[1].includes('TST 1/2'));assert(labels[1].includes('foil'));
          assert(labels[2].includes('Row 2: 1 x Treasure'));assert(labels[2].includes('TST 4'));assert(!labels[2].includes('Treasure //'));
          const writes=[];apiWrite=async(path,body)=>{writes.push(body);return targetAnswer(body);};prepare(sheet,'1');action(sheet,'Preview change').click();await settle();
          assert.equal(writes[0].component,'tokens');same(writes[0].target,{row:1,payload_sha256:payloadHash});assert(hasSave(sheet));
        ''')

    def test_legacy_product_or_unavailable_targeting_has_no_selector_and_stays_general(self):
        self.target_js(r'''
          const variants=[{check_targeting:undefined},{check_targeting:null},{check_targeting:{available:false,payload_sha256:payloadHash,row_sha256s:rowHashes}},
            {kind:'product'},{edit_rows:undefined},{edit_rows:[]},{edit_rows:null}];
          for(const extra of variants){resetOwner();const {sheet}=openCheck(cardPart(extra));assert.equal(sheet.body.querySelector('[data-order-change-field=check_target]'),null);
            const writes=[];apiWrite=async(path,body)=>{writes.push(body);return previewAnswer;};type(sheet,'check','General only');action(sheet,'Preview change').click();await settle();
            assert.equal(writes.length,1);assert.equal(writes[0].target,undefined);assert(hasSave(sheet));sheet.close();}
        ''')

    def test_malformed_capability_hash_arrays_or_original_rows_never_offer_target_selection(self):
        self.target_js(r'''
          const sparse=Array(2);sparse[0]=rowHashes[0];const sparseRows=Array(2);sparseRows[0]=targetCardRow();
          const variants=[{check_targeting:{available:true,payload_sha256:'bad',row_sha256s:rowHashes}},
            {check_targeting:{available:true,payload_sha256:payloadHash}},{check_targeting:{available:true,payload_sha256:payloadHash,row_sha256s:null}},
            {check_targeting:{available:true,payload_sha256:payloadHash,row_sha256s:[rowHashes[0]]}},
            {check_targeting:{available:true,payload_sha256:payloadHash,row_sha256s:[rowHashes[0],'bad']}},
            {check_targeting:{available:true,payload_sha256:payloadHash,row_sha256s:sparse}},
            {edit_rows:[null,targetCardRow()]},{edit_rows:[[],targetCardRow()]},{edit_rows:sparseRows}];
          for(const extra of variants){resetOwner();const {sheet}=openCheck(cardPart(extra));assert.equal(sheet.body.querySelector('[data-order-change-field=check_target]'),null);
            assert(!hasSave(sheet));sheet.close();}
        ''')

    def test_invalid_or_out_of_range_target_selection_is_refused_before_preview_request(self):
        self.target_js(r'''
          for(const value of ['0','-1','1.5','01','3','1e0','9007199254740993']){resetOwner();const {sheet}=openCheck(),writes=[];
            apiWrite=async(path,body)=>{writes.push(body);return targetAnswer(body);};prepare(sheet,value);action(sheet,'Preview change').click();await settle();
            assert.equal(writes.length,0,value);assert(!hasSave(sheet));assert(sheet.body.textContent.includes('original order rows changed'));sheet.close();}
        ''')

    def test_changed_payload_hash_or_original_rows_cannot_reuse_open_target_choices(self):
        self.target_js(r'''
          for(const mode of ['payload','rows']){resetOwner();const {sheet,part}=openCheck(),writes=[];
            apiWrite=async(path,body)=>{writes.push(body);return targetAnswer(body);};prepare(sheet);
            if(mode==='payload')part.check_targeting.payload_sha256='d'.repeat(64);else part.edit_rows[1].collector_number='10';
            action(sheet,'Preview change').click();await settle();assert.equal(writes.length,0);assert(!hasSave(sheet));
            assert(sheet.body.textContent.includes('Refresh Shopping'));sheet.close();}
        ''')

    def test_target_preview_must_match_selected_row_payload_and_original_row_hash(self):
        self.target_js(r'''
          const changes=[()=>undefined,()=>null,target=>({...target,component:'tokens'}),target=>({...target,text:'Different inspection'}),
            target=>({...target,row:1}),target=>({...target,row:'2'}),target=>({...target,payload_sha256:'d'.repeat(64)}),
            target=>({...target,row_sha256:'bad'}),target=>({...target,row_sha256:rowHashes[0]}),target=>({...target,check:0}),target=>({...target,check:4}),target=>({...target,check:'3'})];
          for(const alter of changes){resetOwner();const {sheet}=openCheck();let writes=0;apiWrite=async(path,body)=>{writes++;
              const answer=targetAnswer(body);return{...answer,targeted_check:alter(answer.targeted_check)};};
            prepare(sheet);action(sheet,'Preview change').click();await settle();assert.equal(writes,1);assert(!hasSave(sheet));
            assert.equal(sheet.body.querySelector('.shop-order-check-target'),null);assert(sheet.body.textContent.includes('could not be confirmed'));sheet.close();}
        ''')

    def test_target_preview_requires_unique_component_check_entry_and_exact_new_check_text(self):
        self.target_js(r'''
          const changes=[answer=>({...answer,checks:undefined}),answer=>({...answer,checks:[]}),
            answer=>({...answer,checks:[{component:'tokens',checks:answer.checks[0].checks}]}),
            answer=>({...answer,checks:[answer.checks[0],answer.checks[0]]}),
            answer=>({...answer,checks:[{component:'cards',checks:['Confirm the art','Check the reverse']}]}),
            answer=>({...answer,checks:[{component:'cards',checks:['Confirm the art','Check the reverse','Different text']}]}),
            answer=>({...answer,checks:[{component:'cards',checks:['Confirm the art','Inspect the exact printing','Check the reverse']} ]})];
          for(const alter of changes){resetOwner();const {sheet}=openCheck();apiWrite=async(path,body)=>alter(targetAnswer(body));
            prepare(sheet);action(sheet,'Preview change').click();await settle();assert(!hasSave(sheet));
            assert.equal(sheet.body.querySelector('.shop-order-check-target'),null);sheet.close();}
        ''')

    def test_general_preview_cannot_silently_acquire_a_row_association(self):
        self.target_js(r'''
          const {sheet}=openCheck();apiWrite=async(path,body)=>targetAnswer({...body,target:{row:1,payload_sha256:payloadHash}});
          type(sheet,'check','General only');action(sheet,'Preview change').click();await settle();assert(!hasSave(sheet));
          assert(sheet.body.textContent.includes('association was unexpected'));assert.equal(sheet.body.querySelector('.shop-order-check-target'),null);
        ''')

    def test_select_change_invalidates_preview_and_new_review_uses_new_original_row(self):
        self.target_js(r'''
          const {sheet}=openCheck(),writes=[];apiWrite=async(path,body)=>{writes.push([path,body]);return targetAnswer(body);};
          prepare(sheet);action(sheet,'Preview change').click();await settle();assert(hasSave(sheet));
          chooseTarget(sheet,'1');assert(!hasSave(sheet));assert(sheet.body.querySelector('.shop-order-preview').hidden);
          action(sheet,'Preview change').click();await settle();assert.equal(writes.length,2);assert.equal(writes[1][1].target.row,1);
          assert(sheet.body.querySelector('.shop-order-check-target').textContent.includes('FDN 227'));assert(hasSave(sheet));
        ''')

    def test_eventless_target_change_cannot_apply_previously_signed_preview(self):
        self.target_js(r'''
          const {sheet}=openCheck(),writes=[];apiWrite=async(path,body)=>{writes.push([path,body]);return targetAnswer(body);};
          prepare(sheet);action(sheet,'Preview change').click();await settle();chooseTarget(sheet,'1',false);
          action(sheet,'Save change').click();await settle();assert.equal(writes.length,1);assert(!hasSave(sheet));
          assert(sheet.body.textContent.includes('Preview it again'));assert.equal(field(sheet,'check_target').value,'1');
        ''')

    def test_late_target_preview_after_profile_route_close_or_page_drop_cannot_enable_save(self):
        self.target_js(r'''
          for(const mode of ['profile','route','close','drop']){resetOwner();const {sheet}=openCheck();let finish,request;
            apiWrite=(path,body)=>{request=body;return new Promise(done=>finish=done);};prepare(sheet);action(sheet,'Preview change').click();
            if(mode==='profile')state.profile={id:'user1',role:'member',space:'home'};if(mode==='route')routeToken++;
            if(mode==='close')sheet.close();if(mode==='drop')clear(main);finish(targetAnswer(request));await settle();
            assert(!hasSave(sheet),mode);assert.equal(sheet.body.querySelector('.shop-order-check-target'),null);sheet.close();}
        ''')

    def test_changed_target_during_pending_preview_cannot_enable_save_for_old_selection(self):
        self.target_js(r'''
          const {sheet}=openCheck();let finish,request;apiWrite=(path,body)=>{request=body;return new Promise(done=>finish=done);};
          prepare(sheet);action(sheet,'Preview change').click();chooseTarget(sheet,'1',false);finish(targetAnswer(request));await settle();
          assert(!hasSave(sheet));assert.equal(field(sheet,'check_target').value,'1');assert.equal(sheet.body.querySelector('.shop-order-check-target'),null);
        ''')

    def test_numbered_withdraw_keeps_its_original_payload_without_target_or_selector(self):
        self.target_js(r'''
          const {sheet}=openCheck(cardPart(),2),writes=[];apiWrite=async(path,body)=>{writes.push(body);return previewAnswer;};
          assert.equal(sheet.body.querySelector('[data-order-change-field=check_target]'),null);
          assert.equal(sheet.body.querySelector('[data-order-change-field=check]'),null);action(sheet,'Preview change').click();await settle();
          same(writes,[{expect:'revision-1',order:pending.id,action:'checks',component:'cards',withdraw:[2]}]);assert(hasSave(sheet));
        ''')

    def test_missing_or_mismatched_saved_target_receipt_requires_refresh_without_another_apply(self):
        self.target_js(r'''
          for(const mode of ['missing','wrong-row','wrong-hash']){resetOwner();const {sheet,view}=openCheck(),writes=[];let reviewedBody;
            apiWrite=async(path,body)=>{writes.push([path,body]);if(path.endsWith('/preview')){reviewedBody=body;return targetAnswer(body);}
              if(mode==='missing')return{saved:true};const answer={...targetAnswer(reviewedBody),saved:true};
              if(mode==='wrong-row')answer.targeted_check.row=1;else answer.targeted_check.row_sha256=rowHashes[0];return answer;};
            prepare(sheet);action(sheet,'Preview change').click();await settle();const old=action(sheet,'Save change');old.click();await settle();
            same(reviewedBody.target,{row:2,payload_sha256:payloadHash});assert.equal(view.stale,true);assert(!sheet.closed);assert(!hasSave(sheet));
            assert(sheet.body.textContent.includes("saved row association couldn't be confirmed"));assert(button(sheet.body,'Refresh Shopping'));
            assert(action(sheet,'Preview change').disabled);old.fire('click');action(sheet,'Preview change').click();await settle();assert.equal(writes.length,2);
            same(writes[1],['/api/shopping/order/change/apply',{preview:'signed-change'}]);sheet.close();}
        ''')

    def test_uncertain_target_apply_stops_until_refresh_while_known_refusal_can_be_reviewed_again(self):
        self.target_js(r'''
          for(const failure of [Error('Lost response'),new ApiError(500,'Internal detail'),new ApiError(503,'Unavailable'),new ApiError(400,'Refused')]){
            resetOwner();const {sheet,view}=openCheck(),writes=[];apiWrite=async(path,body)=>{writes.push([path,body]);if(path.endsWith('/preview'))return targetAnswer(body);throw failure;};
            prepare(sheet);action(sheet,'Preview change').click();await settle();action(sheet,'Save change').click();await settle();
            const uncertain=failure.status!==400;assert.equal(view.stale,uncertain);assert(!hasSave(sheet));assert.equal(writes.length,2);
            assert.equal(action(sheet,'Preview change').disabled,uncertain);
            if(uncertain){assert(button(sheet.body,'Refresh Shopping'));assert(sheet.body.textContent.includes("saved row association couldn't be confirmed"));
              action(sheet,'Preview change').click();await settle();assert.equal(writes.length,2);}
            else{assert(sheet.body.textContent.includes('couldn\'t be saved'));action(sheet,'Preview change').click();await settle();assert.equal(writes.length,3);assert(hasSave(sheet));}
            assert.equal(writes.filter(item=>item[0].endsWith('/apply')).length,1);sheet.close();}
        ''')


if __name__ == "__main__":
    unittest.main()
