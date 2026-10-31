"""Restoring edited token-card rows reviews every row's changed values as literal text and verifies its receipt by stable id."""
import unittest

from decklab.tests import test_activity_undo_ui as updates
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoTokenEditUiTests(unittest.TestCase):
    def run_js(self, scenario):
        updates.ActivityUndoUiTests.run_js(self, r'''
          const pairRow=extra=>tokenRow({front:'Angel',back:'The Monarch',set:'tst',front_collector_number:'1',back_collector_number:'2',
            finish:'nonfoil',quantity:2,notes:'Paired faces verified',...extra});
          const editItem=(id=7,extra={})=>{const current=pairRow({front:'Angel '+id}),restored={...current,quantity:5,front_details:'4/4; white; flying',notes:'Recorded pairing note'};
            const fields=['quantity','front_details','notes'].map(field=>({field,before:current[field],after:restored[field]}));
            return{label:current.front+' / The Monarch',token_row_id:id,current,restored,fields,...extra};};
          const editPreview=(extra={})=>{const p=preview({kind:'tokens',action:'token_batch_update',label:'Updates to 2 token-card rows',
            row_count:2,rows:[editItem(7),editItem(8)],...extra});delete p.fields;delete p.current;delete p.restored;return p;};
          const editSaved=(p=editPreview(),extra={})=>{const a=accepted(p,{action:'token_batch_update',row_count:p.row_count,
            restored_rows:p.rows.map(item=>({token_row_id:item.token_row_id,row:{...item.restored}})),summary:'Undo change #42: restore Updates to 2 token-card rows',...extra});
            if(!Object.hasOwn(extra,'restored'))delete a.restored;return a;};
        ''' + scenario)

    def test_reviews_every_row_and_changed_value_without_controls(self):
        self.run_js(r'''
          const p=editPreview(),before=JSON.stringify(p),{sheet}=await open(p);const text=sheet.body.textContent;
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,2);
          for(const words of ['Review all 2 token-card rows','restored together, in place, in one new audited change','original change stays in Activity',
            'no partial selection','Each row is checked again when you save','No token card is added or removed',
            'Angel 7 / The Monarch','Angel 8 / The Monarch','TST 1/2 · nonfoil · 2 physical cards',
            'Quantity (physical cards): 2 → 5','Front details: Not recorded → 4/4; white; flying','Notes: Paired faces verified → Recorded pairing note'])assert(text.includes(words),words);
          assert.equal(sheet.body.querySelectorAll('input').length,0);assert.equal(sheet.body.querySelector('textarea'),null);
          assert(sheet.body.querySelectorAll('.activity-undo-note').length>=4);assert(save(sheet));assert(!save(sheet).disabled);assert.equal(JSON.stringify(p),before);
        ''')

    def test_one_row_uses_singular_words_and_fifty_rows_are_reviewed_while_any_other_packet_fails(self):
        self.run_js(r'''
          const one=await open(editPreview({row_count:1,rows:[editItem(7)],label:'Updates to 1 token-card row'}));assert(save(one.sheet));
          const words=one.sheet.body.textContent;assert(words.includes('Review the token-card row below'));assert(words.includes('The row is checked again'));
          assert(!words.includes('rows'));
          const many=await open(editPreview({row_count:50,label:'Updates to 50 token-card rows',rows:Array.from({length:50},(_,i)=>editItem(i+1))}));
          assert.equal(many.sheet.body.querySelectorAll('.activity-undo-batch-row').length,50);assert(save(many.sheet));
          const base=editItem(7);
          for(const extra of [{row_count:3},{row_count:0,rows:[]},{row_count:51,label:'Updates to 51 token-card rows',rows:Array.from({length:51},(_,i)=>editItem(i+1))},
            {label:'Updates to 2 rows'},{label:'Updates to 2 token-card row'},{space:'user2'},{action:'batch_update'},{kind:'collection'},{proof:{}},{reason_required:true},
            {physical_confirmation_required:true},{identity_policy:'fresh_id'},
            {rows:[editItem(7),editItem(7)]},{rows:[{...base,token_row_id:'7'},editItem(8)]},{rows:[{...base,extra:1},editItem(8)]},
            {rows:[{...base,label:'Angel'},editItem(8)]},{rows:[{...base,restored:{...base.restored,quantity:'5'}},editItem(8)]},
            {rows:[{...base,restored:{...base.restored,quantity:0}},editItem(8)]},{rows:[{...base,current:{...base.current,id:7}},editItem(8)]},
            {rows:[{...base,fields:base.fields.slice(1)},editItem(8)]},{rows:[{...base,fields:[...base.fields].reverse()},editItem(8)]},
            {rows:[{...base,fields:[{...base.fields[0],after:9},...base.fields.slice(1)]},editItem(8)]},
            {rows:[{...base,restored:{...base.current},fields:[]},editItem(8)]}]){
            const made=await open(editPreview(extra));assert(!save(made.sheet),JSON.stringify(extra));assert.equal(made.sheet.body.querySelectorAll('.activity-undo-batch-row').length,0);
          }
        ''')

    def test_unavailable_reason_is_shown_without_save(self):
        self.run_js(r'''
          const why="1 of the 2 updated token-card rows can't be restored (would change or exceed packed token cards: 1).";
          const {sheet}=await open({available:false,id:42,reason:why});assert(!save(sheet));assert(sheet.body.textContent.includes(why));
        ''')

    def test_save_sends_only_the_source_and_receipt_and_accepts_a_reordered_exact_receipt(self):
        self.run_js(r'''
          const {sheet,p}=await open(editPreview());let finish;const sent=[];apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};
          const old=save(sheet);old.click();old.fire('click');same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64)}]]);
          const result=editSaved(p);result.restored_rows.reverse();finish(result);await settle();assert(button(sheet.dialog,'Done'));assert(!save(sheet));
          assert(sheet.body.textContent.includes('Undo saved as a new change'));old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_receipts_reject_any_missing_extra_or_changed_part(self):
        self.run_js(r'''
          const p=editPreview(),normal=editSaved(p),one=normal.restored_rows[0],two=normal.restored_rows[1];
          const invalid=[{action:'batch_update'},{row_count:1},{restored_rows:[one]},{restored_rows:[one,one]},{restored_rows:[one,two,two]},
            {restored_rows:[{...one,token_row_id:9},two]},{restored_rows:[{...one,row:{...one.row,notes:'Other'}},two]},
            {restored_rows:[{...one,row:{...one.row,quantity:'5'}},two]},{restored_rows:[{...one,extra:1},two]},{restored_rows:[null,two]},
            {restored:one.row},{saved:false},{source_id:43},{expect:'c'.repeat(64)},{space:'user2'},{kind:'collection'},{sha256:'bad'},
            {revision:4},{revision:' '},{summary:''},{added_token_row_ids:[7,8]}];
          for(const extra of invalid){const {sheet,p}=await open(editPreview());let writes=0;apiWrite=async()=>{writes++;return editSaved(p,extra);};
            const old=save(sheet);old.click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));old.fire('click');assert.equal(writes,1);}
          const missing=editSaved(p);delete missing.restored_rows;assert.equal(activityUndoReceipt(missing,p),false);
          assert.equal(activityUndoReceipt(editSaved(p),p),true);
        ''')

    def test_values_are_plain_local_text(self):
        self.run_js(r'''
          const hostile='<img src=x onerror=alert(1)>';const base=editItem(7);
          const restored={...base.restored,notes:hostile,back_details:'https://example.com/x'};
          const item={...base,restored,fields:['quantity','front_details','back_details','notes'].map(field=>({field,before:base.current[field],after:restored[field]}))};
          const {sheet}=await open(editPreview({rows:[item,editItem(8)]}));
          assert(sheet.body.textContent.includes(hostile));assert.equal(sheet.body.querySelectorAll('img').length,0);assert.equal(sheet.body.querySelectorAll('a').length,0);
        ''')


if __name__ == "__main__":
    unittest.main()
