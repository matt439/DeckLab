"""Purchase-queue rows a change added are removed with one reviewed reason, and rows it removed come back as new rows; every value literal text."""
import unittest

from decklab.tests import test_activity_undo_ui as updates
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoWatchlistRowsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        updates.ActivityUndoUiTests.run_js(self, r'''
          const queueRow=(name,extra)=>({name,set:'',collector_number:'',finish:'',quantity:'1',for:'Fixture deck',printing:'any',
            listed_aud:'0.50',listed_at:'Fixture shop',in_stock:'no',checked:'2026-10-20',notes:'Queue note',state:'waiting_for_stock',source:'',...extra});
          const strip=p=>{delete p.fields;delete p.current;delete p.restored;return p;};
          const added=(extra={})=>strip(preview({kind:'watchlist',action:'watchlist_remove',label:'2 added purchase-queue rows',row_count:2,reason_required:true,
            rows:[7,8].map(id=>({label:'Fixture card '+id+' for Fixture deck',watch_row_id:id,current:queueRow('Fixture card '+id)})),...extra}));
          const removedRows=(extra={})=>strip(preview({kind:'watchlist',action:'watchlist_add',label:'2 removed purchase-queue rows',row_count:2,
            rows:[7,8].map(id=>({label:'Fixture card '+id+' for Fixture deck',restored:queueRow('Fixture card '+id)})),...extra}));
          const gone=(p=added(),extra={})=>{const a=accepted(p,{action:'watchlist_remove',row_count:p.row_count,removed_watch_row_ids:p.rows.map(item=>item.watch_row_id),
            summary:'Undo change #42: remove 2 added purchase-queue rows',...extra});if(!Object.hasOwn(extra,'restored'))delete a.restored;return a;};
          const back=(p=removedRows(),extra={})=>{const a=accepted(p,{action:'watchlist_add',row_count:p.row_count,
            restored_rows:p.rows.map((item,index)=>({watch_row_id:500+index,row:{...item.restored}})),summary:'Undo change #42: restore 2 removed purchase-queue rows as new rows',...extra});
            if(!Object.hasOwn(extra,'restored'))delete a.restored;return a;};
          const reason=sheet=>sheet.body.querySelector('input');
          const giveReason=(sheet,value='Added by mistake')=>{const input=reason(sheet);input.value=value;input.fire('input');return input;};
        ''' + scenario)

    def test_added_rows_are_shown_whole_before_a_required_reason(self):
        self.run_js(r'''
          const {sheet}=await open(added());const text=sheet.body.textContent;
          for(const words of ['removes all 2 purchase-queue rows this change added','Every added row will be removed together','no partial selection',
            'original change stays in Activity','Fixture card 7 for Fixture deck','Fixture card 8 for Fixture deck','Reference price (AUD)','Queue note',
            'Nothing is ordered, bought or cancelled','Reason for removing all these added purchase-queue rows (required)','come off the purchase queue'])assert(text.includes(words),words);
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,2);assert.equal(sheet.body.querySelectorAll('input').length,1);
          assert(save(sheet).disabled);giveReason(sheet,'  ');assert(save(sheet).disabled);giveReason(sheet);assert(!save(sheet).disabled);
        ''')

    def test_removed_rows_are_shown_whole_with_no_reason_or_confirmation(self):
        self.run_js(r'''
          const {sheet}=await open(removedRows());const text=sheet.body.textContent;
          for(const words of ['adds all 2 purchase-queue rows this change removed back to the queue, each as a new row','Review every recorded row',
            'Fixture card 7 for Fixture deck','Fixture card 8 for Fixture deck','Queue note'])assert(text.includes(words),words);
          assert.equal(sheet.body.querySelectorAll('input').length,0);assert(save(sheet));assert(!save(sheet).disabled);
        ''')

    def test_one_row_is_described_in_the_singular(self):
        self.run_js(r'''
          const one=added({row_count:1,label:'1 added purchase-queue row',rows:added().rows.slice(0,1)});
          let text=(await open(one)).sheet.body.textContent;
          for(const words of ['Undo removes the purchase-queue row this change added.','Review the current row below.',
            'Reason for removing this added purchase-queue row (required)','Enter why this row should come off the purchase queue.'])assert(text.includes(words),words);
          for(const words of ['all 1','Every added row','no partial selection','all these'])assert(!text.includes(words),words);
          text=(await open(removedRows({row_count:1,label:'1 removed purchase-queue row',rows:removedRows().rows.slice(0,1)}))).sheet.body.textContent;
          for(const words of ['Undo adds the purchase-queue row this change removed back to the queue, as a new row','Review the recorded row below.'])assert(text.includes(words),words);
          assert(!text.includes('all 1'));
        ''')

    def test_one_and_fifty_rows_are_reviewed_while_any_other_packet_fails(self):
        self.run_js(r'''
          const many=Array.from({length:50},(_,i)=>({label:'Card '+i,watch_row_id:i+1,current:queueRow('Card '+i)}));
          assert(save((await open(added({row_count:50,label:'50 added purchase-queue rows',rows:many}))).sheet));
          assert(save((await open(added({row_count:1,label:'1 added purchase-queue row',rows:many.slice(0,1)}))).sheet));
          const base=added().rows[0],old=removedRows().rows[0];
          for(const extra of [{row_count:3},{label:'2 added rows'},{reason_required:false},{space:'user2'},{proof:{}},{physical_confirmation_required:true},
            {row_count:51,label:'51 added purchase-queue rows',rows:Array.from({length:51},(_,i)=>({label:'Card '+i,watch_row_id:i+1,current:queueRow('Card '+i)}))},
            {rows:[base,base]},{rows:[{...base,watch_row_id:'7'},added().rows[1]]},{rows:[{...base,extra:1},added().rows[1]]},
            {rows:[{...base,current:{...base.current,quantity:1}},added().rows[1]]},{rows:[{...base,label:' '},added().rows[1]]},
            {rows:[{label:old.label,restored:old.restored},added().rows[1]]}]){
            const made=await open(added(extra));assert(!save(made.sheet),JSON.stringify(extra));assert.equal(reason(made.sheet),null);
          }
          for(const extra of [{reason_required:true},{label:'2 added purchase-queue rows'},{rows:[old,old]},{rows:[{...old,watch_row_id:7},removedRows().rows[1]]},
            {rows:[{...old,restored:{...old.restored,quantity:'0'}},removedRows().rows[1]]},{rows:[{label:old.label,current:old.restored},removedRows().rows[1]]}]){
            const made=await open(removedRows(extra));assert(!save(made.sheet),JSON.stringify(extra));
          }
        ''')

    def test_save_posts_the_normalized_reason_and_checks_the_ids_in_order(self):
        self.run_js(r'''
          const {sheet,p}=await open(added());giveReason(sheet,'  Added   by mistake ');const sent=[];
          apiWrite=async(path,body)=>{sent.push([path,body]);return gone(p);};save(sheet).click();await settle();
          same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64),reason:'Added by mistake'}]]);assert(button(sheet.dialog,'Done'));
          for(const extra of [{removed_watch_row_ids:[7]},{removed_watch_row_ids:[8,7]},{removed_watch_row_ids:[7,'8']},{restored_rows:[]},
            {action:'watchlist_update'},{row_count:3},{restored:null},{sha256:'bad'},{summary:''},{space:'user2'}]){
            const {sheet,p}=await open(added());giveReason(sheet);apiWrite=async()=>gone(p,extra);save(sheet).click();await settle();
            assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));
          }
        ''')

    def test_restore_posts_only_the_receipt_and_needs_fresh_distinct_ids_with_the_recorded_rows(self):
        self.run_js(r'''
          const {sheet,p}=await open(removedRows());const sent=[];apiWrite=async(path,body)=>{sent.push([path,body]);return back(p);};
          save(sheet).click();await settle();same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64)}]]);assert(button(sheet.dialog,'Done'));
          const one=back(p).restored_rows[0],two=back(p).restored_rows[1];
          for(const extra of [{restored_rows:[one]},{restored_rows:[one,{...two,watch_row_id:500}]},{restored_rows:[two,one]},
            {restored_rows:[{...one,watch_row_id:'500'},two]},{restored_rows:[{...one,row:{...one.row,notes:'Other'}},two]},
            {action:'watchlist_update'},{removed_watch_row_ids:[7,8]},{revision:' '}]){
            const {sheet,p}=await open(removedRows());apiWrite=async()=>back(p,extra);save(sheet).click();await settle();
            assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));
          }
        ''')

    def test_values_are_plain_local_text(self):
        self.run_js(r'''
          const raw='<img src=x onerror=alert(1)>',p=added();p.rows[0].label=raw;p.rows[0].current.notes=raw;p.rows[1].current.source=raw;
          const {sheet}=await open(p),hash=location.hash;
          assert(sheet.body.textContent.includes(raw));assert.equal(sheet.body.querySelector('img'),null);assert.equal(location.hash,hash);
          const q=removedRows();q.rows[0].restored.notes=raw;const other=await open(q);assert(other.sheet.body.textContent.includes(raw));
          assert.equal(other.sheet.body.querySelector('img'),null);
        ''')


if __name__ == "__main__":
    unittest.main()
