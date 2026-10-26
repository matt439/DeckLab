"""Undo of one eligible collection insertion explicitly reviews removal and its reason."""
import unittest

from decklab.tests import test_activity_undo_ui as updates
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoRemoveUiTests(unittest.TestCase):
    def run_js(self, scenario):
        updates.ActivityUndoUiTests.run_js(self, r'''
          const removePreview=(extra={})=>{const p=preview({action:'remove',reason_required:true,restored:null,...extra});
            delete p.fields;if(Object.hasOwn(extra,'fields'))p.fields=extra.fields;return p;};
          const removed=(p=removePreview(),extra={})=>accepted(p,{action:'remove',restored:null,
            summary:'Removed the added fixture row.',removed_key:{set:p.current.set,collector_number:p.current.collector_number,finish:p.current.finish},...extra});
          const reason=sheet=>sheet.body.querySelector('input');
          const enterReason=(sheet,value)=>{const input=reason(sheet);input.value=value;input.fire('input');return input;};
        ''' + scenario)

    def test_removal_reviews_entire_current_row_and_all_copies_without_a_restored_or_zero_row(self):
        self.run_js(r'''
          const {sheet}=await open(removePreview());const text=sheet.body.textContent;
          for(const word of ['removes all 6 recorded copies','entire added row','Current row to remove','Llanowar Elves','fdn','227','nonfoil','NM','en','Present note',
            'original change stays in Activity','Reason for removing this added row (required)'])assert(text.includes(word),word);
          assert(!text.includes('Restored by Undo'));assert(!text.includes('Quantity: 0'));assert(!text.includes('888'));assert.equal(reason(sheet).value,'');
          assert(save(sheet).disabled);assert.equal(reason(sheet).getAttribute('maxlength'),'400');assert.equal(reason(sheet).getAttribute('autocomplete'),'off');
        ''')

    def test_removal_requires_exact_explicit_collection_packet_without_update_fields(self):
        self.run_js(r'''
          for(const extra of [{action:undefined},{action:'restore'},{kind:'tokens'},{reason_required:false},{reason_required:undefined},{restored:{}},{restored:collectionRow({quantity:0})},
            {fields:[]},{fields:[{field:'quantity',before:6,after:0}]},{current:collectionRow({quantity:0})},{extra:'unknown'}]){
            const {sheet}=await open(removePreview(extra));assert(!save(sheet),JSON.stringify(extra));assert.equal(reason(sheet),null);assert(!sheet.body.textContent.includes('Current row to remove'));
          }
        ''')

    def test_reason_is_required_bounded_normalized_and_has_no_implicit_default(self):
        self.run_js(r'''
          const {sheet}=await open(removePreview());let writes=0;apiWrite=async()=>{writes++;return removed();};
          for(const value of ['', '  \n\t ', '\u200b\u202e', 'a'.repeat(201), 'a'.repeat(200)+'\u200b', 'Nul\u0000reason', 'Del\u007freason']){
            enterReason(sheet,value);assert(save(sheet).disabled,JSON.stringify(value));save(sheet).fire('click');await settle();assert.equal(writes,0);
          }
          enterReason(sheet,'Entered twice');assert(!save(sheet).disabled);assert(sheet.body.textContent.includes('Reason to be saved: Entered twice'));assert.equal(writes,0);
        ''')

    def test_save_carries_only_source_receipt_and_normalized_reason_once(self):
        self.run_js(r'''
          const {sheet,p}=await open(removePreview());const input=enterReason(sheet,'  Entered\u200b  twice\n in\t error  '),old=save(sheet);
          input.fire('change');assert.equal(save(sheet),old);assert(sheet.body.textContent.includes('Reason to be saved: Entered twice in error'));
          let finish;const sent=[];apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};old.focus();old.click();old.fire('click');
          same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64),reason:'Entered twice in error'}]]);assert(input.disabled);finish(removed(p));await settle();
          assert(button(sheet.dialog,'Done'));assert(sheet.body.textContent.includes('Removed the added fixture row.'));assert(!save(sheet));assert(reason(sheet).disabled);old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_unicode_character_limit_matches_server_without_truncating_the_reason(self):
        self.run_js(r'''
          const {sheet,p}=await open(removePreview());enterReason(sheet,'🦊'.repeat(201));assert(save(sheet).disabled);enterReason(sheet,'🦊'.repeat(200));assert(!save(sheet).disabled);
          const sent=[];apiWrite=async(path,body)=>{sent.push(body);return removed(p);};save(sheet).click();await settle();assert.equal(sent[0].reason,'🦊'.repeat(200));assert(button(sheet.dialog,'Done'));
        ''')

    def test_python_whitespace_and_format_normalization_is_shown_before_save(self):
        self.run_js(r'''
          const {sheet,p}=await open(removePreview());enterReason(sheet,' \u200bWrong\u0085 import\u001c file\u202e ');
          assert(sheet.body.textContent.includes('Reason to be saved: Wrong import file'));let sent;apiWrite=async(path,body)=>{sent=body;return removed(p);};
          save(sheet).click();await settle();assert.equal(sent.reason,'Wrong import file');
        ''')

    def test_wrong_removal_receipt_key_null_action_or_source_requires_reload(self):
        self.run_js(r'''
          const invalid=[{action:undefined},{action:'restore'},{restored:{}},{restored:collectionRow({quantity:0})},{restored:undefined},
            {removed_key:null},{removed_key:[]},{removed_key:{set:'fdn',collector_number:'228',finish:'nonfoil'}},
            {removed_key:{set:'tst',collector_number:'227',finish:'nonfoil'}},{removed_key:{set:'fdn',collector_number:'227',finish:'foil'}},
            {removed_key:{set:'fdn',collector_number:'227'}},{removed_key:{set:'fdn',collector_number:'227',finish:'nonfoil',quantity:6}},
            {source_id:43},{expect:'f'.repeat(64)},{kind:'tokens'},{space:'user2'},{saved:false},{sha256:'bad'},{revision:3},{summary:''}];
          for(const extra of invalid){const {sheet,p}=await open(removePreview());enterReason(sheet,'Wrong import');let writes=0;apiWrite=async()=>{writes++;return removed(p,extra);};
            const old=save(sheet);old.click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));
            assert(sheet.body.textContent.includes('could not be confirmed'));assert.equal(reason(sheet).value,'Wrong import');assert(reason(sheet).disabled);old.fire('click');assert.equal(writes,1);}
        ''')

    def test_updates_never_accept_removal_shaped_receipts_or_send_reasons(self):
        self.run_js(r'''
          const {sheet,p}=await open();let body;apiWrite=async(path,sent)=>{body=sent;return removed(removePreview());};save(sheet).click();await settle();
          same(body,{id:42,expect:'a'.repeat(64)});assert(button(sheet.dialog,'Reload Activity'));assert(!button(sheet.dialog,'Done'));assert.equal(reason(sheet),null);
        ''')

    def test_mutated_packet_detached_or_unaccepted_reason_cannot_save(self):
        self.run_js(r'''
          for(const mode of ['action','quantity','required','detached','unaccepted','profile','route','hash','root','modal']){
            const {sheet,p,view}=await open(removePreview());enterReason(sheet,'Wrong import');const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return removed(p);};
            if(mode==='action')p.action='restore';if(mode==='quantity')p.current.quantity=8;if(mode==='required')p.reason_required=false;
            if(mode==='detached')reason(sheet).remove();if(mode==='unaccepted')reason(sheet).value='Different without input';
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='root')view.days.remove();if(mode==='modal')top=openSheet('Another task');old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();
          }
        ''')

    def test_pending_reason_change_is_rejected_and_original_reason_stays_the_one_sent(self):
        self.run_js(r'''
          const {sheet,p}=await open(removePreview());const input=enterReason(sheet,'Entered twice');let finish,body;apiWrite=(path,sent)=>{body=sent;return new Promise(done=>finish=done);};
          save(sheet).click();input.value='Changed during save';input.fire('input');assert.equal(input.value,'Entered twice');assert(input.disabled);
          finish(removed(p));await settle();assert.equal(body.reason,'Entered twice');assert(button(sheet.dialog,'Done'));
        ''')

    def test_refused_or_unknown_result_retains_row_and_reason_with_no_retry(self):
        self.run_js(r'''
          for(const failure of [Error('Lost response'),new ApiError(409,'This printing is now in a physical deck.',{}),new ApiError(400,'This row cannot be removed.',{})]){
            const {sheet}=await open(removePreview());enterReason(sheet,'Wrong import');let writes=0;apiWrite=async()=>{writes++;throw failure;};const old=save(sheet);old.click();await settle();
            assert(sheet.body.textContent.includes('Current row to remove'));assert.equal(reason(sheet).value,'Wrong import');assert(reason(sheet).disabled);
            assert(button(sheet.dialog,'Reload Activity'));assert(!save(sheet));old.fire('click');assert.equal(writes,1);assert(!sheet.body.textContent.includes('Undo saved as a new change'));
          }
        ''')

    def test_late_removal_previews_and_results_do_not_reveal_or_replace_another_owner(self):
        self.run_js(r'''
          const {trigger}=mount();let finish;api=()=>new Promise(done=>finish=done);trigger.click();const pending=[...colSheets].at(-1);state.profile=state.profiles[1];
          finish(removePreview());await settle();assert.equal(reason(pending),null);assert(!pending.body.textContent.includes('Llanowar Elves'));
          const {sheet,p,view}=await open(removePreview());enterReason(sheet,'Wrong import');apiWrite=()=>new Promise(done=>finish=done);save(sheet).click();sheet.close();
          state.profile=state.profiles[1];routeToken++;clear(main);main.append(el('p',{text:'New person page'}));let reads=0;api=async()=>{reads++;return freshPage();};finish(removed(p));await settle();
          assert.equal(main.textContent,'New person page');assert.equal(reads,0);
        ''')

    def test_done_preserves_filter_page_depth_and_original_history_on_bounded_refresh(self):
        self.run_js(r'''
          const filter={kind:'collection',actor:'user1'},{view,trigger}=mount([candidate(),candidate(41,{undo:undefined})],41,filter);
          api=async()=>page([candidate(40,{undo:undefined}),candidate(39,{undo:undefined})],39);view.older.click();await settle();assert.equal(view.loadedPages,2);
          const p=removePreview();api=async()=>p;trigger.click();await settle();const sheet=[...colSheets].at(-1);enterReason(sheet,'Wrong import');apiWrite=async()=>removed(p);save(sheet).click();await settle();
          const asked=[];api=async path=>{asked.push(path);return asked.length===1?page([candidate(43,{undo:undefined}),candidate(42,{undo:undefined})],42):page([candidate(41,{undo:undefined}),candidate(40,{undo:undefined})],40);};
          button(sheet.dialog,'Done').click();await settle();assert.equal(view.loadedPages,2);assert.equal(view.shown,4);assert.equal(view.next,40);
          same(asked,['/api/activity?kind=collection&actor=user1','/api/activity?before=42&kind=collection&actor=user1']);assert(view.days.querySelector('[data-activity-id="42"]'));
          assert.equal(location.hash,activityHref(filter));assert(!view.undoBusy);assert.equal(view.undoCtx,null);
        ''')

    def test_reason_remains_plain_local_text_without_storage_or_url_mutations(self):
        self.run_js(r'''
          const {sheet}=await open(removePreview()),hash=location.hash,prior=JSON.stringify(state);const raw='<img src=x onerror=alert(1)>';
          enterReason(sheet,raw);assert(sheet.body.textContent.includes('Reason to be saved: '+raw));assert.equal(sheet.body.querySelector('img'),null);
          assert.equal(location.hash,hash);assert.equal(JSON.stringify(state),prior);assert(!JSON.stringify(state).includes(raw));
        ''')


if __name__ == "__main__":
    unittest.main()
