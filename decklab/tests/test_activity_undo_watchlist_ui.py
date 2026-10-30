"""Purchase-queue Undo reviews every row's recorded values as literal text and verifies its receipt by stable id."""
import unittest

from decklab.tests import test_activity_undo_ui as updates
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoWatchlistUiTests(unittest.TestCase):
    def run_js(self, scenario):
        updates.ActivityUndoUiTests.run_js(self, r'''
          const queueRow=extra=>({name:'Fixture card',set:'',collector_number:'',finish:'',quantity:'1',for:'Fixture deck',printing:'any',
            listed_aud:'0.50',listed_at:'Fixture shop',in_stock:'no',checked:'2026-10-20',notes:'Current queue note',state:'waiting_for_stock',source:'',...extra});
          const queueItem=(id=7,extra={})=>{const current=queueRow({name:'Fixture card '+id}),restored={...current,quantity:'3',notes:'Recorded queue note',state:'ready'};
            const fields=['quantity','notes','state'].map(field=>({field,before:current[field],after:restored[field]}));
            return{label:current.name+' for Fixture deck',watch_row_id:id,current,restored,fields,...extra};};
          const queuePreview=(extra={})=>{const p=preview({kind:'watchlist',action:'watchlist_update',label:'Updates to 2 purchase-queue rows',
            row_count:2,rows:[queueItem(7),queueItem(8)],...extra});delete p.fields;delete p.current;delete p.restored;return p;};
          const queueSaved=(p=queuePreview(),extra={})=>{const a=accepted(p,{action:'watchlist_update',row_count:p.row_count,
            restored_rows:p.rows.map(item=>({watch_row_id:item.watch_row_id,row:{...item.restored}})),summary:'Undo change #42: restore Updates to 2 purchase-queue rows',...extra});
            if(!Object.hasOwn(extra,'restored'))delete a.restored;return a;};
        ''' + scenario)

    def test_reviews_every_row_and_changed_value_without_controls(self):
        self.run_js(r'''
          const p=queuePreview(),before=JSON.stringify(p),{sheet}=await open(p);const text=sheet.body.textContent;
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,2);
          for(const words of ['Review all 2 purchase-queue rows','restored together in one new audited change','original change stays in Activity',
            'Fixture card 7 for Fixture deck','Fixture card 8 for Fixture deck','Printing any · for Fixture deck · waiting_for_stock',
            'Quantity: 1 → 3','Notes: Current queue note → Recorded queue note','Purchase state: waiting_for_stock → ready'])assert(text.includes(words),words);
          assert(!text.includes('Reference price'));assert.equal(sheet.body.querySelectorAll('input').length,0);assert.equal(sheet.body.querySelector('textarea'),null);
          assert(sheet.body.querySelectorAll('.activity-undo-note').length>=4);assert(save(sheet));assert(!save(sheet).disabled);assert.equal(JSON.stringify(p),before);
        ''')

    def test_one_and_fifty_rows_are_reviewed_while_any_other_packet_fails(self):
        self.run_js(r'''
          const one=await open(queuePreview({row_count:1,rows:[queueItem(7)],label:'Updates to 1 purchase-queue row'}));assert(save(one.sheet));
          const many=await open(queuePreview({row_count:50,label:'Updates to 50 purchase-queue rows',rows:Array.from({length:50},(_,i)=>queueItem(i+1))}));
          assert.equal(many.sheet.body.querySelectorAll('.activity-undo-batch-row').length,50);assert(save(many.sheet));
          const base=queueItem(7);
          for(const extra of [{row_count:3},{row_count:0,rows:[]},{row_count:51,label:'Updates to 51 purchase-queue rows',rows:Array.from({length:51},(_,i)=>queueItem(i+1))},
            {label:'Updates to 2 rows'},{space:'user2'},{action:'batch_update'},{kind:'collection'},{proof:{}},{reason_required:true},
            {rows:[queueItem(7),queueItem(7)]},{rows:[{...base,watch_row_id:'7'},queueItem(8)]},{rows:[{...base,extra:1},queueItem(8)]},
            {rows:[{...base,restored:{...base.restored,quantity:3}},queueItem(8)]},{rows:[{...base,restored:{...base.restored,quantity:'0'}},queueItem(8)]},
            {rows:[{...base,current:{...base.current,hidden:'x'}},queueItem(8)]},{rows:[{...base,fields:base.fields.slice(1)},queueItem(8)]},
            {rows:[{...base,fields:[...base.fields].reverse()},queueItem(8)]},{rows:[{...base,fields:[{...base.fields[0],after:'9'},...base.fields.slice(1)]},queueItem(8)]},
            {rows:[{...base,restored:{...base.current},fields:[]},queueItem(8)]},{rows:[{...base,label:''},queueItem(8)]}]){
            const made=await open(queuePreview(extra));assert(!save(made.sheet),JSON.stringify(extra));assert.equal(made.sheet.body.querySelectorAll('.activity-undo-batch-row').length,0);
          }
        ''')

    def test_unavailable_reason_is_shown_without_save(self):
        self.run_js(r'''
          const {sheet}=await open({available:false,id:42,reason:'1 of the 2 updated purchase-queue rows can\'t be restored (edited or removed since: 1).'});
          assert(!save(sheet));assert(sheet.body.textContent.includes('edited or removed since: 1'));
        ''')

    def test_save_sends_only_the_source_and_receipt_and_accepts_a_reordered_exact_receipt(self):
        self.run_js(r'''
          const {sheet,p}=await open(queuePreview());let finish;const sent=[];apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};
          const old=save(sheet);old.click();old.fire('click');same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64)}]]);
          const result=queueSaved(p);result.restored_rows.reverse();finish(result);await settle();assert(button(sheet.dialog,'Done'));assert(!save(sheet));
          assert(sheet.body.textContent.includes('Undo saved as a new change'));old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_receipts_reject_any_missing_extra_or_changed_part(self):
        self.run_js(r'''
          const p=queuePreview(),normal=queueSaved(p),one=normal.restored_rows[0],two=normal.restored_rows[1];
          const invalid=[{action:'batch_update'},{row_count:1},{restored_rows:[one]},{restored_rows:[one,one]},{restored_rows:[one,two,two]},
            {restored_rows:[{...one,watch_row_id:9},two]},{restored_rows:[{...one,row:{...one.row,notes:'Other'}},two]},
            {restored_rows:[{...one,row:{...one.row,quantity:3}},two]},{restored_rows:[{...one,extra:1},two]},{restored_rows:[null,two]},
            {restored:one.row},{saved:false},{source_id:43},{expect:'c'.repeat(64)},{space:'user2'},{kind:'collection'},{sha256:'bad'},
            {revision:4},{revision:' '},{summary:''}];
          for(const extra of invalid){const {sheet,p}=await open(queuePreview());let writes=0;apiWrite=async()=>{writes++;return queueSaved(p,extra);};
            const old=save(sheet);old.click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));old.fire('click');assert.equal(writes,1);}
          const missing=queueSaved(p);delete missing.restored_rows;assert.equal(activityUndoReceipt(missing,p),false);
        ''')

    def test_values_are_plain_local_text(self):
        self.run_js(r'''
          const raw='<img src=x onerror=alert(1)>',item=queueItem(7,{label:raw});item.current.notes=raw;item.fields[1].before=raw;
          const p=queuePreview({rows:[item,queueItem(8)]}),{sheet}=await open(p),hash=location.hash;
          assert(sheet.body.textContent.includes(raw));assert.equal(sheet.body.querySelector('img'),null);assert.equal(location.hash,hash);assert(save(sheet));
        ''')


if __name__ == "__main__":
    unittest.main()
