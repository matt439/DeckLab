"""All-or-nothing metadata Undo reviews bounded complete rows and verifies receipts by key."""
import unittest

from decklab.tests import test_activity_undo_ui as updates
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoBatchUiTests(unittest.TestCase):
    def run_js(self, scenario):
        updates.ActivityUndoUiTests.run_js(self, r'''
          const batchRow=(number=1,extra={})=>{const current=collectionRow({collector_number:String(number),notes:'Unchanged long note '.repeat(30)}),
            restored={...current,condition:'',language:''};return{key:{set:current.set,collector_number:current.collector_number,finish:current.finish},
              label:'Fixture printing '+number,current,restored,fields:[{field:'condition',before:'NM',after:''},{field:'language',before:'en',after:''}],...extra};};
          const batchPreview=(extra={})=>({available:true,id:42,expect:'a'.repeat(64),kind:'collection',space:'home',label:'Restore metadata for 2 printings',
            action:'batch_metadata',row_count:2,rows:[batchRow(1),batchRow(2)],...extra});
          const batchSaved=(p=batchPreview(),extra={})=>({saved:true,source_id:p.id,expect:p.expect,kind:p.kind,space:p.space,sha256:'b'.repeat(64),
            revision:'4',summary:'Restored condition and language for the fixture printings.',action:'batch_metadata',row_count:p.row_count,
            restored_rows:p.rows.map(item=>({key:{...item.key},row:{...item.restored}})),...extra});
        ''' + scenario)

    def test_reviews_every_printing_and_changed_field_without_selection_or_repeated_unchanged_notes(self):
        self.run_js(r'''
          const p=batchPreview(),before=JSON.stringify(p),{sheet}=await open(p);const rows=sheet.body.querySelectorAll('.activity-undo-batch-row');assert.equal(rows.length,2);
          for(const text of ['Review all 2 printings','restored together','original change stays in Activity','Fixture printing 1','Fixture printing 2','FDN 1','FDN 2','Condition: NM → Not recorded','Language: en → Not recorded'])
            assert(sheet.body.textContent.includes(text),text);
          assert(!sheet.body.textContent.includes('Unchanged long note'));assert(!sheet.body.textContent.includes('Quantity:'));assert.equal(sheet.body.querySelectorAll('input').length,0);
          assert.equal(sheet.body.querySelector('textarea'),null);assert(save(sheet));assert(!save(sheet).disabled);assert.equal(JSON.stringify(p),before);
        ''')

    def test_all_fifty_printings_are_reviewed_while_fifty_one_and_unbounded_packets_fail(self):
        self.run_js(r'''
          const p=batchPreview({row_count:50,rows:Array.from({length:50},(_,index)=>batchRow(index+1))}),{sheet}=await open(p);
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,50);assert(sheet.body.textContent.includes('Fixture printing 50'));
          for(const extra of [{row_count:1,rows:[batchRow()]},{row_count:0,rows:[]},{row_count:51,rows:Array.from({length:51},(_,i)=>batchRow(i+1))},
            {row_count:'2'},{row_count:2.5},{row_count:3},{rows:null},{rows:[]},{kind:'tokens'},{action:'batch'},
            {current:null},{restored:null},{reason_required:true},{physical_confirmation_required:true},{fields:[]}]){
            const made=await open(batchPreview(extra));assert(!save(made.sheet),JSON.stringify(extra));assert.equal(made.sheet.body.querySelectorAll('.activity-undo-batch-row').length,0);
          }
        ''')

    def test_malformed_mixed_or_duplicate_rows_and_fields_fail_before_any_save(self):
        self.run_js(r'''
          const base=batchRow(),bad=[null,{...base,label:''},{...base,key:{...base.key,collector_number:'wrong'}},{...base,key:{...base.key,extra:'no'}},
            {...base,current:{...base.current,quantity:7}},{...base,restored:{...base.restored,notes:'Changed note'}},{...base,restored:{...base.restored,name:'Different'}},
            {...base,restored:{...base.restored,quantity:0}},{...base,fields:[]},{...base,fields:[{field:'condition',before:'Wrong',after:''}]},
            {...base,fields:[{field:'condition',before:'NM',after:''},{field:'condition',before:'NM',after:''}]},
            {...base,fields:[{field:'notes',before:base.current.notes,after:'Other'}]},{...base,action:'remove'},
            {...base,restored:{...base.restored,private_id:4}},{...base,restored:{...base.current},fields:[{field:'condition',before:'NM',after:'NM'}]}];
          for(const row of bad){const {sheet}=await open(batchPreview({rows:[row,batchRow(2)]}));assert(!save(sheet),JSON.stringify(row));}
          const duplicate=await open(batchPreview({rows:[batchRow(1),batchRow(1)]}));assert(!save(duplicate.sheet));
          const sparseRows=Array(2);sparseRows[0]=batchRow();assert(!activityUndoEvidence(batchPreview({rows:sparseRows}),42,'home'));
          const sparseFields=Array(1),single=batchRow(1,{restored:{...base.current,condition:''},fields:sparseFields});
          assert(!activityUndoEvidence(batchPreview({rows:[single,batchRow(2)]}),42,'home'));
        ''')

    def test_save_is_one_source_bound_request_and_accepts_complete_reordered_receipt_by_key(self):
        self.run_js(r'''
          const {sheet,p}=await open(batchPreview());let finish;const sent=[];apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};
          const old=save(sheet);old.click();old.fire('click');same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64)}]]);
          const result=batchSaved(p);result.restored_rows.reverse();finish(result);await settle();assert(button(sheet.dialog,'Done'));assert(!save(sheet));
          assert(sheet.body.textContent.includes('Restored condition and language'));old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_receipts_reject_missing_duplicate_extra_mixed_or_changed_rows(self):
        self.run_js(r'''
          const p=batchPreview(),normal=batchSaved(p),one=normal.restored_rows[0],two=normal.restored_rows[1];
          const invalid=[{action:undefined},{action:'add'},{row_count:1},{row_count:'2'},{restored_rows:null},{restored_rows:[one]},
            {restored_rows:[one,one]},{restored_rows:[one,two,{...two,key:{...two.key,collector_number:'3'}}]},
            {restored_rows:[{...one,key:{...one.key,collector_number:'3'}},two]},{restored_rows:[{...one,key:{...one.key,finish:'foil'}},two]},
            {restored_rows:[{...one,key:{...one.key,extra:true}},two]},{restored_rows:[{...one,row:{...one.row,notes:'Different'}},two]},
            {restored_rows:[{...one,row:{...one.row,quantity:7}},two]},{restored_rows:[{...one,row:{...one.row,condition:'NM'}},two]},
            {restored_rows:[{...one,row:{...one.row,language:'en'}},two]},{restored_rows:[{...one,row:{...one.row,hidden:7}},two]},
            {restored_rows:[{...one,row:{...one.row,quantity:'6'}},two]},{restored_rows:[null,two]},{restored:one.row},
            {added_key:one.key},{removed_key:one.key},{saved:false},{source_id:43},{expect:'c'.repeat(64)},{space:'user2'},{kind:'tokens'},{sha256:'bad'},{revision:4},{summary:''}];
          for(const extra of invalid){const {sheet,p}=await open(batchPreview());let writes=0;apiWrite=async()=>{writes++;return batchSaved(p,extra);};
            const old=save(sheet);old.click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));old.fire('click');assert.equal(writes,1);}
          const sparse=Array(2);sparse[0]=one;assert.equal(activityUndoReceipt(batchSaved(p,{restored_rows:sparse}),p),false);
        ''')

    def test_condition_only_and_language_only_rows_preserve_unknown_values_and_field_order(self):
        self.run_js(r'''
          const one=batchRow(1),two=batchRow(2);one.restored.language='en';one.fields=[one.fields[0]];two.restored.condition='NM';two.fields=[two.fields[1]];
          const p=batchPreview({rows:[one,two]}),{sheet}=await open(p);assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,2);
          apiWrite=async()=>batchSaved(p);save(sheet).click();await settle();assert(button(sheet.dialog,'Done'));
        ''')

    def test_batch_protocol_does_not_bleed_into_single_update_or_add_remove_receipts(self):
        self.run_js(r'''
          for(const extra of [{row_count:2},{rows:batchPreview().rows}]){const {sheet}=await open(preview(extra));assert(!save(sheet));}
          const p=preview();assert.equal(activityUndoReceipt(accepted(p,{row_count:2,restored_rows:batchSaved().restored_rows}),p),false);
          const add={available:true,id:42,expect:p.expect,kind:'collection',space:'home',label:p.label,action:'add',physical_confirmation_required:true,current:null,restored:p.restored};
          assert.equal(activityUndoReceipt(batchSaved(),add),false);
          const {sheet}=await open();let sent;apiWrite=async(path,body)=>{sent=body;return accepted();};save(sheet).click();await settle();same(sent,{id:42,expect:'a'.repeat(64)});
        ''')

    def test_changed_preview_or_owner_filter_and_top_modal_cannot_save_any_subset(self):
        self.run_js(r'''
          for(const mode of ['count','quantity','metadata','fields','key','action','profile','route','hash','root','seq','filter','modal']){
            const {sheet,p,view}=await open(batchPreview());const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return batchSaved(p);};
            if(mode==='count')p.row_count=3;if(mode==='quantity')p.rows[0].restored.quantity=8;if(mode==='metadata')p.rows[0].restored.notes='Changed';
            if(mode==='fields')p.rows[0].fields[0].after='LP';if(mode==='key')p.rows[0].key.finish='foil';if(mode==='action')p.action='add';
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';if(mode==='root')view.days.remove();
            if(mode==='seq')view.seq++;if(mode==='filter')view.filter.kind='tokens';if(mode==='modal')top=openSheet('Other task');old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();
          }
        ''')

    def test_conflict_or_unknown_result_keeps_full_review_but_never_offers_partial_retry(self):
        self.run_js(r'''
          for(const failure of [Error('Lost response'),new ApiError(409,'One row changed meanwhile.',{})]){
            const {sheet}=await open(batchPreview());let writes=0;apiWrite=async()=>{writes++;throw failure;};const old=save(sheet);old.click();await settle();
            assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,2);assert(button(sheet.dialog,'Reload Activity'));assert(!save(sheet));
            assert(!sheet.body.textContent.includes('Undo saved as a new change'));old.fire('click');assert.equal(writes,1);assert.equal(sheet.body.querySelectorAll('input').length,0);
          }
        ''')

    def test_late_batch_preview_or_result_cannot_reveal_or_replace_a_new_owner(self):
        self.run_js(r'''
          const {trigger}=mount();let finish;api=()=>new Promise(done=>finish=done);trigger.click();const pending=[...colSheets].at(-1);state.profile=state.profiles[1];finish(batchPreview());await settle();
          assert.equal(pending.body.querySelectorAll('.activity-undo-batch-row').length,0);
          const {sheet,p}=await open(batchPreview());apiWrite=()=>new Promise(done=>finish=done);save(sheet).click();sheet.close();state.profile=state.profiles[1];routeToken++;
          clear(main);main.append(el('p',{text:'Current person page'}));let reads=0;api=async()=>{reads++;return freshPage();};finish(batchSaved(p));await settle();assert.equal(reads,0);assert.equal(main.textContent,'Current person page');
        ''')

    def test_done_keeps_original_audit_filter_and_loaded_page_depth(self):
        self.run_js(r'''
          const filter={kind:'collection',actor:'user1'},{view,trigger}=mount([candidate(),candidate(41,{undo:undefined})],41,filter);api=async()=>page([candidate(40,{undo:undefined}),candidate(39,{undo:undefined})],39);
          view.older.click();await settle();const p=batchPreview();api=async()=>p;trigger.click();await settle();const sheet=[...colSheets].at(-1);apiWrite=async()=>batchSaved(p);save(sheet).click();await settle();
          const asked=[];api=async path=>{asked.push(path);return asked.length===1?page([candidate(43,{undo:undefined}),candidate(42,{undo:undefined})],42):page([candidate(41,{undo:undefined}),candidate(40,{undo:undefined})],40);};
          button(sheet.dialog,'Done').click();await settle();same(asked,['/api/activity?kind=collection&actor=user1','/api/activity?before=42&kind=collection&actor=user1']);
          assert.equal(view.loadedPages,2);assert.equal(view.shown,4);assert.equal(location.hash,activityHref(filter));assert(view.days.querySelector('[data-activity-id="42"]'));assert(!view.undoBusy);
        ''')

    def test_labels_and_values_are_plain_local_text_without_edit_controls(self):
        self.run_js(r'''
          const raw='<img src=x onerror=alert(1)>',one=batchRow(1,{label:raw});one.current.condition=raw;one.fields[0].before=raw;
          const p=batchPreview({rows:[one,batchRow(2)]}),{sheet}=await open(p),hash=location.hash,prior=JSON.stringify(state);
          assert(sheet.body.textContent.includes(raw));assert.equal(sheet.body.querySelector('img'),null);assert.equal(sheet.body.querySelectorAll('input').length,0);
          assert.equal(location.hash,hash);assert.equal(JSON.stringify(state),prior);assert(save(sheet));
        ''')


if __name__ == "__main__":
    unittest.main()
