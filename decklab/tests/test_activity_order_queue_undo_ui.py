"""A complete order and queue inverse has one explicit reason/save and no row authority in the request."""
import unittest

from decklab.tests import test_activity_undo_ui as fixture
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class OrderQueueUndoUiTests(unittest.TestCase):
    run_js = fixture.ActivityUndoUiTests.run_js

    def order_js(self, scenario):
        self.run_js(r'''
          state.profiles[0]={id:'matt',name:'Matt',role:'admin',space:'home'};
          const qrow=quantity=>({name:'Llanowar Elves',set:'m19',collector_number:'314',finish:'nonfoil',quantity,for:'Fixture deck',printing:'exact',
            listed_aud:'',listed_at:'',in_stock:'',checked:'',notes:'Current intent',state:'ready',source:'',buy_under_aud:''});
          const queue=()=>({available:true,id:42,expect:'c'.repeat(64),kind:'watchlist',space:'home',action:'watchlist_update',label:'Updates to 1 purchase-queue row',
            row_count:1,rows:[{label:'Llanowar Elves for Fixture deck',watch_row_id:7,current:qrow('1'),restored:qrow('3'),fields:[{field:'quantity',before:'1',after:'3'}]}]});
          const record=()=>({id:'2026-11-11-fixture-order',seller:'Fixture shop',ordered_on:'2026-11-11',sources:['Synthetic offline research'],notes:'Delivery note',audit_notes:'',components:[
            {id:'cards',kind:'cards',status:'pending',received_on:'',checks:['Check the printing'],verified_checks:[],rows:[
              {name:'Llanowar Elves',set:'m19',collector_number:'314',finish:'nonfoil',quantity:'3',condition:'',language:'',notes:'Recorded counted-copy facts'}]}]});
          const orderPreview=()=>({available:true,id:42,expect:'a'.repeat(64),kind:'order_queue',space:'home',action:'order_queue_restore',
            label:'recorded order and its purchase-queue intent',order_id:'2026-11-11-fixture-order',source_action:'added',row_count:4,queue_count:1,
            current:record(),restored:null,queue:queue(),reason_required:true,tables:{written:[],needs_attention:false}});
          const orderSaved=p=>({saved:true,source_id:p.id,expect:p.expect,kind:'order_queue',space:'home',action:p.action,order_id:p.order_id,
            order:p.restored,queue:{saved:true,source_id:p.id,expect:p.queue.expect,kind:'watchlist',space:'home',action:'watchlist_update',row_count:1,
              restored_rows:[{watch_row_id:7,row:p.queue.rows[0].restored}],sha256:'b'.repeat(64),revision:'3',summary:'Queue restored'},
            revision:'3',summary:'Recorded order and queue restored',tables:{written:[],needs_attention:false}});
          const reason=sheet=>sheet.body.querySelector('input');
          const typeReason=sheet=>{reason(sheet).value='Mistaken recorded order';reason(sheet).fire('input');};
        ''' + scenario)

    def test_complete_order_and_queue_are_reviewed_without_guessing_finish_condition_or_selecting_rows(self):
        self.order_js(r'''
          const p=orderPreview(),{sheet}=await open(p),text=sheet.body.textContent;
          for(const value of ['Current order','Restored by Undo','No recorded order','2026-11-11-fixture-order','Fixture shop',
              'Recorded counted-copy facts','Condition: Not recorded','Language: Not recorded','Current queue','Queue restored by Undo',
              'Current deck lists, prose and kit are retained'])assert(text.includes(value),value);
          assert.equal(sheet.body.querySelectorAll('input').length,1);assert.equal(sheet.body.querySelectorAll('input[type=checkbox]').length,0);
          assert(save(sheet).disabled);assert(!text.includes('NM'));assert(!text.includes('English'));assert(!text.includes('999'));
        ''')

    def test_one_reason_and_source_receipt_post_once_with_no_submitted_order_or_queue_rows(self):
        self.order_js(r'''
          const p=orderPreview(),{sheet}=await open(p),writes=[];let finish;
          apiWrite=(path,body)=>{writes.push([path,body]);return new Promise(resolve=>{finish=resolve;});};
          typeReason(sheet);const oldSave=save(sheet);oldSave.click();oldSave.click();
          same(writes,[['/api/activity/undo',{id:42,expect:'a'.repeat(64),reason:'Mistaken recorded order'}]]);
          assert(reason(sheet).disabled);finish(orderSaved(p));await settle();
          assert(!save(sheet));assert(button(sheet.dialog,'Done'));assert(sheet.body.textContent.includes('Undo saved as a new change'));
          oldSave.click();assert.equal(writes.length,1);
        ''')

    def test_malformed_order_nested_queue_or_partial_receipt_never_has_a_save_or_retry_path(self):
        self.order_js(r'''
          for(const mutate of [p=>{p.queue.id=99;},p=>{p.queue.rows[0].restored.quantity='0';},p=>{p.current.components[0].rows[0].paid_price='1.00';},
              p=>{p.source_action='removed';},p=>{p.reason_required=false;},p=>{p.current.components[0].status='unknown';}]){
            const p=orderPreview();mutate(p);const{sheet}=await open(p);assert(!save(sheet));assert(!sheet.body.textContent.includes('Current order'));
          }
          const p=orderPreview(),{sheet}=await open(p);apiWrite=async()=>{const saved=orderSaved(p);saved.queue.revision='different';return saved;};
          typeReason(sheet);save(sheet).click();await settle();assert(!save(sheet));assert(button(sheet.dialog,'Reload Activity'));
          assert(sheet.body.textContent.includes('could not be confirmed'));
        ''')

    def test_detached_reason_or_old_footer_different_profile_and_nested_modal_cannot_submit(self):
        self.order_js(r'''
          const{sheet}=await open(orderPreview());let writes=0;apiWrite=async()=>{writes++;};
          typeReason(sheet);const first=save(sheet),nested=openSheet('Another review');first.click();assert.equal(writes,0);nested.close();
          const who=state.profile;state.profile={id:'user2',space:'user2',role:'member'};first.click();assert.equal(writes,0);state.profile=who;
          first.remove();first.click();assert.equal(writes,0);
          typeReason(sheet);const current=save(sheet);reason(sheet).remove();current.click();assert.equal(writes,0);
        ''')

    def test_unknown_or_conflicted_write_requires_refresh_and_a_late_result_never_moves_new_page(self):
        self.order_js(r'''
          for(const status of [409,500]){
            const{sheet}=await open(orderPreview());let count=0;apiWrite=async()=>{count++;throw new ApiError(status,'Could not save');};
            typeReason(sheet);const old=save(sheet);old.click();await settle();old.click();assert.equal(count,1);assert(!save(sheet));
            assert(button(sheet.dialog,'Reload Activity'));button(sheet.dialog,'Close').click();
          }
          const p=orderPreview(),{sheet}=await open(p);let finish;apiWrite=()=>new Promise(resolve=>{finish=resolve;});typeReason(sheet);save(sheet).click();
          routeToken++;clear(main).append(el('p',{text:'A different page'}));finish(orderSaved(p));await settle();
          assert.equal(main.textContent,'A different page');
        ''')

    def test_read_only_home_member_or_other_space_never_receives_a_checked_order_controller(self):
        self.order_js(r'''
          const p=orderPreview(),mounted=mount();state.profile.role='member';api=async()=>p;mounted.trigger.click();await settle();
          assert(!save([...colSheets].at(-1)));state.profile.role='admin';
          assert.equal(activityUndoOrderQueueEvidence(p,'user2','matt'),false);
        ''')

    def test_standard_product_columns_and_optional_recorded_facts_open_a_literal_complete_review(self):
        self.order_js(r'''
          const p=orderPreview(),part=p.current.components[0];Object.assign(part,{kind:'product',product:'fixture-product',name:'Fixture product',format:'Commander precon',product_status:'preordered'});
          Object.assign(part.rows[0],{section:'extras',deck:'Fixture deck',rarity:'common',in_play_boosters:'no',condition:'LP',language:'ja'});
          const{sheet}=await open(p),text=sheet.body.textContent;assert(save(sheet));
          for(const words of ['Fixture product','preordered','Section: extras','Product deck: Fixture deck','Rarity: common','In play boosters: no',
              'Condition: LP','Language: ja'])assert(text.includes(words),words);
        ''')

    def test_focused_reason_is_revealed_after_footer_update_without_scrolling_an_unfocused_or_stale_control(self):
        self.order_js(r'''
          const{sheet}=await open(orderPreview()),input=reason(sheet);input.focus();typeReason(sheet);
          assert.equal(input.scrolled,1);same(input.scrollOptions,{block:'nearest'});assert.equal(save(sheet).disabled,false);
          document.body.focus();input.value='Changed without focus';input.fire('input');assert.equal(input.scrolled,1);
          input.focus();const profile=state.profile;state.profile={id:'user2',space:'user2',role:'member'};
          input.value='Stale input';input.fire('input');assert.equal(input.scrolled,1);state.profile=profile;
          input.remove();input.fire('input');assert.equal(input.scrolled,1);
        ''')
