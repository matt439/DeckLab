"""Removing every added token-card row of one change needs one reviewed reason and an exact stable-id receipt."""
import unittest

from decklab.tests import test_activity_undo_ui as updates
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoTokenBatchRemoveUiTests(unittest.TestCase):
    def run_js(self, scenario):
        updates.ActivityUndoUiTests.run_js(self, r'''
          const pairRow=extra=>tokenRow({front:'Angel',back:'The Monarch',set:'tst',front_collector_number:'1',back_collector_number:'2',
            finish:'nonfoil',quantity:2,notes:'Paired faces verified',...extra});
          const treasure=()=>pairRow({front:'Treasure',back:'',front_collector_number:'3',back_collector_number:'',quantity:1,notes:'single-sided verified'});
          const tokenBatch=(extra={})=>{const p=preview({kind:'tokens',action:'token_batch_remove',label:'2 added token-card rows',row_count:2,
            rows:[{label:'Angel / The Monarch',token_row_id:7,current:pairRow()},{label:'Treasure',token_row_id:8,current:treasure()}],cards:3,
            reason_required:true,...extra});
            delete p.fields;delete p.current;delete p.restored;return p;};
          const removed=(p=tokenBatch(),extra={})=>accepted(p,{action:'token_batch_remove',row_count:p.row_count,removed_token_row_ids:[7,8],
            restored:null,summary:'Removed 2 added token-card rows.',...extra});
          const reason=sheet=>sheet.body.querySelector('input');
          const giveReason=(sheet,value='Wrong batch')=>{const input=reason(sheet);input.value=value;input.fire('input');return input;};
        ''' + scenario)

    def test_every_row_and_the_whole_physical_count_are_shown_before_a_required_reason(self):
        self.run_js(r'''
          const {sheet}=await open(tokenBatch());const text=sheet.body.textContent;
          for(const words of ['removes all 3 physical token cards recorded in these 2 added rows','Every added row will be removed together',
            'Each front/back pair is one physical card','Angel / The Monarch','Treasure','single-sided verified','no partial selection',
            'original change stays in Activity','Reason for removing all these added token-card rows (required)'])assert(text.includes(words),words);
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,2);
          assert.equal(sheet.body.querySelectorAll('input').length,1);assert.equal(reason(sheet).getAttribute('type'),'text');assert(save(sheet).disabled);
          giveReason(sheet,'  ');assert(save(sheet).disabled);giveReason(sheet);assert(!save(sheet).disabled);
        ''')

    def test_only_the_exact_batch_packet_is_accepted(self):
        self.run_js(r'''
          for(const extra of [{row_count:3},{row_count:1,rows:[{label:'Treasure',token_row_id:8,current:treasure()}],label:'1 added token-card rows',cards:1},
            {cards:4},{label:'2 added rows'},{reason_required:false},{physical_confirmation_required:true},
            {rows:[{label:'Angel',token_row_id:7,current:pairRow()},{label:'Treasure',token_row_id:8,current:treasure()}]},
            {rows:[{label:'Angel / The Monarch',token_row_id:7,current:pairRow()},{label:'Treasure',token_row_id:7,current:treasure()}]},
            {rows:[{label:'Angel / The Monarch',token_row_id:'7',current:pairRow()},{label:'Treasure',token_row_id:8,current:treasure()}]},
            {rows:[{label:'Angel / The Monarch',token_row_id:7,current:{...pairRow(),id:7}},{label:'Treasure',token_row_id:8,current:treasure()}]},
            {kind:'collection'},{space:'user2'},{extra:'unknown'}]){
            const {sheet}=await open(tokenBatch(extra));assert(!save(sheet),JSON.stringify(extra));assert.equal(reason(sheet),null);
          }
        ''')

    def test_save_posts_only_source_receipt_and_the_normalized_reason(self):
        self.run_js(r'''
          const {sheet,p}=await open(tokenBatch());giveReason(sheet,'  Wrong   batch ');const sent=[];
          apiWrite=async(path,body)=>{sent.push([path,body]);return removed(p);};save(sheet).click();await settle();
          same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64),reason:'Wrong batch'}]]);
          assert(button(sheet.dialog,'Done'));assert(sheet.body.textContent.includes('Removed 2 added token-card rows.'));
        ''')

    def test_receipt_needs_every_reviewed_id_in_order(self):
        self.run_js(r'''
          const base=tokenBatch();
          const invalid=[{removed_token_row_ids:[7]},{removed_token_row_ids:[8,7]},{removed_token_row_ids:[7,'8']},{removed_token_row_ids:[7,9]},
            {restored:pairRow()},{row_count:3},{action:'remove'},{removed_token_row_id:7},{restored_rows:[]},{extra:'unknown'}];
          for(const extra of invalid){const {sheet,p}=await open(tokenBatch());giveReason(sheet);apiWrite=async()=>removed(p,extra);
            save(sheet).click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));}
          assert.equal(activityUndoReceipt(removed(base),base),true);
        ''')

    def test_a_refused_batch_shows_its_reason_and_offers_no_save(self):
        self.run_js(r'''
          const why="1 of the 3 added token-card rows can't be removed (packed in a deck or product line: 1).";
          const {sheet}=await open({available:false,id:42,reason:why});
          assert(sheet.body.textContent.includes(why));assert(!save(sheet));assert.equal(reason(sheet),null);
        ''')


if __name__ == "__main__":
    unittest.main()
