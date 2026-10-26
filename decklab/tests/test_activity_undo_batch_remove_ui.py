"""Unused added-row batches remove every proved printing with one reviewed reason."""
import unittest

from decklab.tests import test_activity_undo_batch_ui as batches
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoBatchRemoveUiTests(unittest.TestCase):
    def run_js(self, scenario):
        batches.ActivityUndoBatchUiTests.run_js(self, r'''
          const insertedRow=(number,quantity=4)=>{const item=batchRow(number);return{key:item.key,label:item.label,
            current:{...item.current,quantity,notes:'Current note\nLiteral <img src=x onerror=alert(1)>'},restored:null};};
          const removeBatch=(extra={})=>batchPreview({action:'batch_remove',reason_required:true,
            rows:[insertedRow(1,4),insertedRow(2,3)],...extra});
          const batchRemoved=(p=removeBatch(),extra={})=>{const result=batchSaved(p);delete result.restored_rows;return{...result,action:'batch_remove',
            summary:'Removed all unused added fixture rows.',removed_keys:p.rows.map(item=>({...item.key})),restored:null,...extra};};
          const reason=sheet=>sheet.body.querySelector('input');
          const giveReason=(sheet,value='Wrong restoration')=>{const input=reason(sheet);input.value=value;input.fire('input');return input;};
        ''' + scenario)

    def test_all_current_rows_and_total_copies_need_one_reason_without_partial_selection(self):
        self.run_js(r'''
          const p=removeBatch(),before=JSON.stringify(p),{sheet}=await open(p),text=sheet.body.textContent;
          for(const word of ['removes all 7 recorded copies across all 2 printings','Every added row will be removed together','Fixture printing 1',
            'Fixture printing 2','Llanowar Elves','NM','en','Literal <img src=x onerror=alert(1)>','no partial selection','Reason for removing all these added rows'])assert(text.includes(word),word);
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,2);assert.equal(sheet.body.querySelectorAll('input').length,1);
          assert.equal(reason(sheet).getAttribute('type'),'text');assert(save(sheet).disabled);assert.equal(sheet.body.querySelector('img'),null);
          assert.equal(sheet.body.querySelector('textarea,select'),null);assert.equal(sheet.body.querySelectorAll('.activity-undo-note').length,2);
          assert.equal(JSON.stringify(p),before);assert(!text.includes('still physically owned'));
        ''')

    def test_fifty_rows_are_reviewed_and_malformed_or_unbounded_packets_refuse(self):
        self.run_js(r'''
          const rows=Array.from({length:50},(_,i)=>insertedRow(i+1,9999)),{sheet}=await open(removeBatch({row_count:50,rows}));
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,50);assert(sheet.body.textContent.includes('499950 recorded copies'));
          assert(sheet.body.textContent.includes('Fixture printing 50'));assert.equal(sheet.body.querySelectorAll('input').length,1);
          const one=insertedRow(1),bad=[{reason_required:false},{reason_required:undefined},{physical_confirmation_required:true},{kind:'tokens'},
            {row_count:1,rows:[one]},{row_count:51,rows:Array.from({length:51},(_,i)=>insertedRow(i+1))},{row_count:'2'},{row_count:3},
            {rows:[one,one]},{rows:[{...one,current:null},insertedRow(2)]},{rows:[{...one,restored:one.current},insertedRow(2)]},
            {rows:[{...one,fields:[]},insertedRow(2)]},{rows:[{...one,key:{...one.key,finish:'foil'}},insertedRow(2)]},
            {rows:[{...one,current:{...one.current,quantity:0}},insertedRow(2)]},{rows:[{...one,current:{...one.current,quantity:'4'}},insertedRow(2)]},
            {current:one.current},{restored:null},{fields:[]},{action:'batch_add'},{action:'batch_update'}];
          for(const extra of bad){const made=await open(removeBatch(extra));assert(!save(made.sheet),JSON.stringify(extra));assert.equal(reason(made.sheet),null);}
          const sparse=Array(2);sparse[0]=one;assert.equal(activityUndoEvidence(removeBatch({rows:sparse}),42,'home'),null);
        ''')

    def test_reason_is_reviewed_normalized_and_required_even_for_stale_disabled_clicks(self):
        self.run_js(r'''
          const {sheet}=await open(removeBatch());let writes=0;apiWrite=async()=>{writes++;return batchRemoved();};const old=save(sheet);
          reason(sheet).value='Unreviewed value';old.fire('click');await settle();assert.equal(writes,0);
          for(const value of ['', ' \t\n ', 'x'.repeat(201), 'Bad\0reason']){giveReason(sheet,value);assert(save(sheet).disabled,JSON.stringify(value));}
          giveReason(sheet,' \u200b Wrong\t restoration  ');assert(sheet.body.textContent.includes('Reason to be saved: Wrong restoration'));assert(!save(sheet).disabled);
        ''')

    def test_save_sends_only_source_receipt_and_one_normalized_reason_and_checks_reordered_keys(self):
        self.run_js(r'''
          const {sheet,p}=await open(removeBatch());giveReason(sheet,' Wrong\t restoration ');let finish;const sent=[];
          apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};const old=save(sheet);old.click();old.fire('click');
          same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64),reason:'Wrong restoration'}]]);assert(reason(sheet).disabled);
          const result=batchRemoved(p);result.removed_keys.reverse();finish(result);await settle();assert(button(sheet.dialog,'Done'));assert(!save(sheet));old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_complete_unique_absence_receipt_is_required_without_retry(self):
        self.run_js(r'''
          const p=removeBatch(),normal=batchRemoved(p),one=normal.removed_keys[0],two=normal.removed_keys[1];
          const bad=[{action:'remove'},{action:'batch_add'},{row_count:1},{removed_keys:[one]},{removed_keys:[one,one]},
            {removed_keys:[one,{...two,finish:'foil'}]},{removed_keys:[one,{...two,extra:true}]},{removed_keys:[one,null]},
            {removed_keys:[one,two,{...two,collector_number:'3'}]},{restored:{}},{restored:undefined},{restored_rows:[]},{added_key:one},{removed_key:one},
            {source_id:43},{expect:'c'.repeat(64)},{space:'user2'},{kind:'tokens'},{saved:false}];
          for(const extra of bad){const made=await open(removeBatch());giveReason(made.sheet);let writes=0;apiWrite=async()=>{writes++;return batchRemoved(made.p,extra);};
            const old=save(made.sheet);old.click();await settle();assert(!button(made.sheet.dialog,'Done'),JSON.stringify(extra));assert(button(made.sheet.dialog,'Reload Activity'));
            assert(reason(made.sheet).disabled);old.fire('click');assert.equal(writes,1);}
        ''')

    def test_mutated_rows_detached_reason_and_changed_scope_cannot_authorize_removal(self):
        self.run_js(r'''
          for(const mode of ['quantity','key','required','subset','reason','detached','profile','route','filter','modal']){
            const {sheet,p,view}=await open(removeBatch());giveReason(sheet);const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return batchRemoved(p);};
            if(mode==='quantity')p.rows[0].current.quantity++;if(mode==='key')p.rows[0].key.finish='foil';if(mode==='required')p.reason_required=false;if(mode==='subset')p.rows.pop();
            if(mode==='reason')reason(sheet).value='Unreviewed different reason';if(mode==='detached')reason(sheet).remove();if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;
            if(mode==='filter')view.filter.kind='tokens';if(mode==='modal')top=openSheet('Other task');old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();
          }
        ''')

    def test_stale_reason_events_rollback_and_uncertain_results_retain_all_rows(self):
        self.run_js(r'''
          const {sheet}=await open(removeBatch());giveReason(sheet);const input=reason(sheet);let finish,writes=0;
          apiWrite=()=>{writes++;return new Promise((done,fail)=>finish=fail);};const old=save(sheet);old.click();input.value='Late change';input.fire('input');assert.equal(input.value,'Wrong restoration');
          finish(Error('Lost response'));await settle();assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,2);assert(input.disabled);
          assert(button(sheet.dialog,'Reload Activity'));assert(!save(sheet));assert(!sheet.body.textContent.includes('Undo saved as a new change'));old.fire('click');assert.equal(writes,1);
        ''')

    def test_late_preview_and_save_never_reveal_or_replace_another_person(self):
        self.run_js(r'''
          const {trigger}=mount();let finish;api=()=>new Promise(done=>finish=done);trigger.click();const pending=[...colSheets].at(-1);
          state.profile=state.profiles[1];finish(removeBatch());await settle();assert.equal(reason(pending),null);assert(!pending.body.textContent.includes('Fixture printing'));
          const {sheet,p}=await open(removeBatch());giveReason(sheet);apiWrite=()=>new Promise(done=>finish=done);save(sheet).click();sheet.close();state.profile=state.profiles[1];routeToken++;
          clear(main);main.append(el('p',{text:'Current person page'}));let reads=0;api=async()=>{reads++;return freshPage();};finish(batchRemoved(p));await settle();assert.equal(reads,0);assert.equal(main.textContent,'Current person page');
        ''')

    def test_new_receipt_cannot_be_accepted_by_any_existing_inverse_protocol(self):
        self.run_js(r'''
          const p=removeBatch(),receipt=batchRemoved(p);for(const before of [preview(),batchPreview(),
            {...p,action:'batch_add',physical_confirmation_required:true,reason_required:undefined},
            {available:true,id:42,expect:p.expect,kind:'collection',space:'home',label:'One row',action:'remove',reason_required:true,current:p.rows[0].current,restored:null}])
            assert.equal(activityUndoReceipt(receipt,before),false);
          const old=batchSaved();old.removed_keys=receipt.removed_keys;assert.equal(activityUndoReceipt(old,batchPreview()),false);
        ''')

    def test_reason_review_keeps_only_the_current_focused_input_in_view(self):
        self.run_js(r'''
          const {sheet}=await open(removeBatch()),input=reason(sheet);let reveals=0;
          input.scrollIntoView=options=>{reveals++;same(options,{block:'nearest'});};input.focus();giveReason(sheet);assert.equal(reveals,1);
          input.fire('change');assert.equal(reveals,1);const other=el('button',{text:'Outside'});main.append(other);other.focus();giveReason(sheet,'Another reason');assert.equal(reveals,1);
          input.focus();const top=openSheet('Other task');input.value='Stale change';input.fire('input');assert.equal(input.value,'Another reason');assert.equal(reveals,1);top.close();
        ''')


if __name__ == "__main__":
    unittest.main()
