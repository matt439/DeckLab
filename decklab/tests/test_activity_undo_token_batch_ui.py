"""Restoring every deleted token-card row of one change needs one whole-count confirmation and an exact receipt."""
import unittest

from decklab.tests import test_activity_undo_ui as updates
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoTokenBatchUiTests(unittest.TestCase):
    def run_js(self, scenario):
        updates.ActivityUndoUiTests.run_js(self, r'''
          const pairRow=extra=>tokenRow({front:'Angel',back:'The Monarch',set:'tst',front_collector_number:'1',back_collector_number:'2',
            finish:'nonfoil',quantity:2,notes:'Paired faces verified',...extra});
          const treasure=()=>pairRow({front:'Treasure',back:'',front_collector_number:'3',back_collector_number:'',quantity:1,notes:'single-sided verified'});
          const tokenBatch=(extra={})=>{const p=preview({kind:'tokens',action:'token_batch_add',label:'2 deleted token-card rows',row_count:2,
            rows:[{label:'Angel / The Monarch',restored:pairRow()},{label:'Treasure',restored:treasure()}],cards:3,
            identity_policy:'fresh_id',physical_confirmation_required:true,packing_restored:false,...extra});
            delete p.fields;delete p.current;delete p.restored;return p;};
          const restored=(p=tokenBatch(),extra={})=>{const a=accepted(p,{action:'token_batch_add',row_count:p.row_count,added_token_row_ids:[900,901],
            restored_rows:p.rows.map(item=>({...item.restored})),summary:'Restored 2 deleted token-card rows as new rows.',...extra});
            if(!Object.hasOwn(extra,'restored'))delete a.restored;return a;};
          const owned=sheet=>sheet.body.querySelector('input');
          const confirmOwned=(sheet,checked=true)=>{const input=owned(sheet);input.checked=checked;input.fire('change');return input;};
        ''' + scenario)

    def test_every_row_and_the_whole_physical_count_are_shown_before_an_unchecked_confirmation(self):
        self.run_js(r'''
          const {sheet}=await open(tokenBatch());const text=sheet.body.textContent;
          for(const words of ['restores all 3 physical token cards recorded in these 2 deleted rows','each as a new token-card row',
            'Each front/back pair is one physical card','Angel / The Monarch','Treasure','single-sided verified','no partial selection',
            "Earlier packing isn't reconnected",'original change stays in Activity',
            'I confirm I still physically have all 3 physical token cards recorded in these 2 rows'])assert(text.includes(words),words);
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,2);
          assert.equal(sheet.body.querySelectorAll('input').length,1);assert.equal(owned(sheet).checked,false);assert(save(sheet).disabled);
        ''')

    def test_only_the_exact_batch_packet_is_accepted(self):
        self.run_js(r'''
          for(const extra of [{row_count:3},{row_count:1,rows:[{label:'Treasure',restored:treasure()}],label:'1 deleted token-card rows',cards:1},
            {cards:4},{label:'2 deleted rows'},{identity_policy:'reuse_id'},{packing_restored:true},{physical_confirmation_required:false},
            {rows:[{label:'Angel',restored:pairRow()},{label:'Treasure',restored:treasure()}]},
            {rows:[{label:'Angel / The Monarch',restored:{...pairRow(),id:71}},{label:'Treasure',restored:treasure()}]},
            {rows:[{label:'Angel / The Monarch',restored:pairRow(),id:71},{label:'Treasure',restored:treasure()}]},
            {kind:'collection'},{space:'user2'},{extra:'unknown'}]){
            const {sheet}=await open(tokenBatch(extra));assert(!save(sheet),JSON.stringify(extra));assert.equal(owned(sheet),null);
          }
          for(const extra of [{current:null},{restored:pairRow()}]){
            const {sheet}=await open({...tokenBatch(),...extra});assert(!save(sheet),JSON.stringify(extra));
          }
        ''')

    def test_save_posts_only_source_receipt_and_confirmation_and_checks_every_returned_row(self):
        self.run_js(r'''
          const {sheet,p}=await open(tokenBatch());confirmOwned(sheet);const sent=[];
          apiWrite=async(path,body)=>{sent.push([path,body]);return restored(p);};save(sheet).click();await settle();
          same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64),confirm_owned:true}]]);
          assert(button(sheet.dialog,'Done'));assert(sheet.body.textContent.includes('Restored 2 deleted token-card rows as new rows.'));
        ''')

    def test_receipt_needs_every_new_id_and_every_reviewed_row(self):
        self.run_js(r'''
          const base=tokenBatch();
          const invalid=[{added_token_row_ids:[900]},{added_token_row_ids:[900,900]},{added_token_row_ids:[900,'901']},{added_token_row_ids:[0,901]},
            {restored_rows:[pairRow()]},{restored_rows:[treasure(),pairRow()]},{restored_rows:[pairRow({notes:'Changed'}),treasure()]},
            {row_count:3},{action:'token_add'},{added_token_row_id:900},{restored:null},{extra:'unknown'}];
          for(const extra of invalid){const {sheet,p}=await open(tokenBatch());confirmOwned(sheet);apiWrite=async()=>restored(p,extra);
            save(sheet).click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));}
          assert.equal(activityUndoReceipt(restored(base),base),true);
        ''')

    def test_a_refused_batch_shows_its_reason_and_offers_no_save(self):
        self.run_js(r'''
          const reason="1 of the 3 deleted token-card rows can't be restored (may be claimed by a packed deck or product line: 1).";
          const {sheet}=await open({available:false,id:42,reason});
          assert(sheet.body.textContent.includes(reason));assert(!save(sheet));assert.equal(owned(sheet),null);
        ''')


if __name__ == "__main__":
    unittest.main()
