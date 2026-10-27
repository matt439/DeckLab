"""Whole deleted collection batches need one explicit physical-ownership review."""
import unittest

from decklab.tests import test_activity_undo_batch_ui as batches
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoBatchAddUiTests(unittest.TestCase):
    def run_js(self, scenario):
        batches.ActivityUndoBatchUiTests.run_js(self, r'''
          const deletedRow=(number,quantity=4)=>{const item=batchRow(number);return{key:item.key,label:item.label,current:null,
            restored:{...item.current,quantity,notes:'Historical note\nLiteral <img src=x onerror=alert(1)>'}};};
          const restoreBatch=(extra={})=>batchPreview({action:'batch_add',physical_confirmation_required:true,
            rows:[deletedRow(1,4),deletedRow(2,3)],...extra});
          const batchAdded=(p=restoreBatch(),extra={})=>batchSaved(p,{action:'batch_add',summary:'Restored all deleted fixture rows.',...extra});
          const owned=sheet=>sheet.body.querySelector('input');
          const confirmOwned=(sheet,checked=true)=>{const input=owned(sheet);input.checked=checked;input.fire('change');return input;};
        ''' + scenario)

    def test_all_historical_rows_and_total_copies_need_one_explicit_confirmation(self):
        self.run_js(r'''
          const p=restoreBatch(),before=JSON.stringify(p),{sheet}=await open(p),text=sheet.body.textContent;
          for(const word of ['restores all 7 recorded copies across all 2 printings','Fixture printing 1','Fixture printing 2','Llanowar Elves',
            'NM','en','Historical note','Literal <img src=x onerror=alert(1)>','no partial selection','own fewer copies, cancel and use Collection'])assert(text.includes(word),word);
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,2);assert.equal(sheet.body.querySelectorAll('input').length,1);
          assert.equal(owned(sheet).getAttribute('type'),'checkbox');assert.equal(owned(sheet).checked,false);assert(save(sheet).disabled);
          assert.equal(sheet.body.querySelector('img'),null);assert.equal(sheet.body.querySelector('textarea,select'),null);
          assert.equal(sheet.body.querySelectorAll('.activity-undo-note').length,2);assert.equal(JSON.stringify(p),before);
          confirmOwned(sheet);assert(!save(sheet).disabled);confirmOwned(sheet,false);assert(save(sheet).disabled);
        ''')

    def test_fifty_complete_rows_are_shown_without_per_row_selection(self):
        self.run_js(r'''
          const rows=Array.from({length:50},(_,i)=>deletedRow(i+1,9999)),{sheet}=await open(restoreBatch({row_count:50,rows}));
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,50);assert(sheet.body.textContent.includes('499950 recorded copies'));
          assert(sheet.body.textContent.includes('Fixture printing 50'));assert.equal(sheet.body.querySelectorAll('input').length,1);
          assert(save(sheet).disabled);confirmOwned(sheet);assert(!save(sheet).disabled);
        ''')

    def test_malformed_scope_counts_confirmation_and_row_packets_never_offer_save(self):
        self.run_js(r'''
          const one=deletedRow(1),bad=[{physical_confirmation_required:false},{physical_confirmation_required:undefined},{kind:'tokens'},
            {row_count:1,rows:[one]},{row_count:51,rows:Array.from({length:51},(_,i)=>deletedRow(i+1))},{row_count:3},{row_count:'2'},
            {rows:[one,one]},{rows:[{...one,current:one.restored},deletedRow(2)]},{rows:[{...one,fields:[]},deletedRow(2)]},
            {rows:[{...one,key:{...one.key,finish:'foil'}},deletedRow(2)]},{rows:[{...one,restored:{...one.restored,quantity:0}},deletedRow(2)]},
            {rows:[{...one,restored:{...one.restored,quantity:'4'}},deletedRow(2)]},{rows:[{...one,restored:{...one.restored,private_id:4}},deletedRow(2)]},
            {current:null},{restored:one.restored},{reason_required:true},{fields:[]},{action:'batch_update'},{action:'batch_metadata'}];
          for(const extra of bad){const {sheet}=await open(restoreBatch(extra));assert(!save(sheet),JSON.stringify(extra));assert.equal(owned(sheet),null);}
          const sparse=Array(2);sparse[0]=one;assert.equal(activityUndoEvidence(restoreBatch({rows:sparse}),42,'home'),null);
        ''')

    def test_confirmation_requires_a_live_change_and_resets_after_reopening(self):
        self.run_js(r'''
          let writes=0;apiWrite=async()=>{writes++;return batchAdded();};const {sheet}=await open(restoreBatch()),old=save(sheet);
          owned(sheet).checked=true;old.fire('click');await settle();assert.equal(writes,0);assert(sheet.body.textContent.includes('Confirm that every recorded copy'));
          confirmOwned(sheet);button(sheet.dialog,'Cancel').click();const reopened=await open(restoreBatch());assert.equal(owned(reopened.sheet).checked,false);assert(save(reopened.sheet).disabled);
        ''')

    def test_save_posts_only_exact_source_receipt_and_true_confirmation_once(self):
        self.run_js(r'''
          const {sheet,p}=await open(restoreBatch());confirmOwned(sheet);let finish;const sent=[];
          apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};const old=save(sheet);old.click();old.fire('click');
          same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64),confirm_owned:true}]]);assert(owned(sheet).disabled);
          const result=batchAdded(p);result.restored_rows.reverse();finish(result);await settle();assert(button(sheet.dialog,'Done'));assert(!save(sheet));
          old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_malformed_actual_receipts_require_reload_without_retry(self):
        self.run_js(r'''
          const p=restoreBatch(),normal=batchAdded(p),one=normal.restored_rows[0],two=normal.restored_rows[1];
          const bad=[{action:'batch_update'},{action:'add'},{row_count:1},{restored_rows:[one]},{restored_rows:[one,one]},
            {restored_rows:[{...one,key:{...one.key,finish:'foil'}},two]},{restored_rows:[{...one,row:{...one.row,quantity:3}},two]},
            {restored_rows:[{...one,row:{...one.row,notes:'Different'}},two]},{restored:one.row},{added_key:one.key},{removed_key:one.key},
            {source_id:43},{expect:'c'.repeat(64)},{space:'user2'},{saved:false}];
          for(const extra of bad){const {sheet,p}=await open(restoreBatch());confirmOwned(sheet);let writes=0;apiWrite=async()=>{writes++;return batchAdded(p,extra);};
            const old=save(sheet);old.click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));
            assert(owned(sheet).disabled);old.fire('click');assert.equal(writes,1);}
        ''')

    def test_mutated_evidence_detached_confirmation_or_changed_owner_cannot_write(self):
        self.run_js(r'''
          for(const mode of ['quantity','key','required','subset','detached','profile','route','filter','modal']){
            const {sheet,p,view}=await open(restoreBatch());confirmOwned(sheet);const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return batchAdded(p);};
            if(mode==='quantity')p.rows[0].restored.quantity++;if(mode==='key')p.rows[0].key.finish='foil';if(mode==='required')p.physical_confirmation_required=false;
            if(mode==='subset')p.rows.pop();if(mode==='detached')owned(sheet).remove();if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;
            if(mode==='filter')view.filter.kind='tokens';if(mode==='modal')top=openSheet('Other task');old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();
          }
        ''')

    def test_stale_confirmation_events_rollback_and_unknown_save_keeps_every_row(self):
        self.run_js(r'''
          const {sheet}=await open(restoreBatch());confirmOwned(sheet);const input=owned(sheet);let finish,writes=0;
          apiWrite=()=>{writes++;return new Promise((done,fail)=>finish=fail);};const old=save(sheet);old.click();input.checked=false;input.fire('change');assert.equal(input.checked,true);
          finish(Error('Lost response'));await settle();assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,2);
          assert(button(sheet.dialog,'Reload Activity'));assert(!save(sheet));assert(input.disabled);old.fire('click');assert.equal(writes,1);
        ''')

    def test_late_preview_and_save_cannot_reveal_or_replace_another_profile(self):
        self.run_js(r'''
          const {trigger}=mount();let finish;api=()=>new Promise(done=>finish=done);trigger.click();const pending=[...colSheets].at(-1);
          state.profile=state.profiles[1];finish(restoreBatch());await settle();assert.equal(owned(pending),null);assert(!pending.body.textContent.includes('Fixture printing'));
          const {sheet,p}=await open(restoreBatch());confirmOwned(sheet);apiWrite=()=>new Promise(done=>finish=done);save(sheet).click();sheet.close();state.profile=state.profiles[1];routeToken++;
          clear(main);main.append(el('p',{text:'Current person page'}));let reads=0;api=async()=>{reads++;return freshPage();};finish(batchAdded(p));await settle();
          assert.equal(reads,0);assert.equal(main.textContent,'Current person page');
        ''')

    def test_protocol_does_not_bleed_into_single_add_or_metadata_quantity_batches(self):
        self.run_js(r'''
          const batch=restoreBatch(),receipt=batchAdded(batch);for(const p of [preview(),batchPreview(),
            batchPreview({action:'batch_update',rows:[{...batchRow(1),restored:{...batchRow(1).restored,quantity:2},fields:[...batchRow(1).fields,{field:'quantity',before:6,after:2}]},batchRow(2)]})])
            assert.equal(activityUndoReceipt(receipt,p),false);
          const single={available:true,id:42,expect:batch.expect,kind:'collection',space:'home',label:'One row',action:'add',physical_confirmation_required:true,current:null,restored:batch.rows[0].restored};
          assert.equal(activityUndoReceipt(receipt,single),false);
        ''')


if __name__ == "__main__":
    unittest.main()
