"""A purchase-queue change that mixed updated, added and removed rows is reviewed and undone whole; every value literal text."""
import unittest

from decklab.tests import test_activity_undo_ui as updates
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoWatchlistMixedUiTests(unittest.TestCase):
    def run_js(self, scenario):
        updates.ActivityUndoUiTests.run_js(self, r'''
          const queueRow=(name,extra)=>({name,set:'',collector_number:'',finish:'',quantity:'1',for:'Fixture deck',printing:'any',
            listed_aud:'0.50',listed_at:'Fixture shop',in_stock:'no',checked:'2026-10-20',notes:'Queue note',state:'waiting_for_stock',source:'',...extra});
          const strip=p=>{delete p.fields;delete p.current;delete p.restored;return p;};
          const updatedRow=id=>({change:'updated',label:'Updated card '+id,watch_row_id:id,current:queueRow('Updated card '+id),
            restored:queueRow('Updated card '+id,{quantity:'3',notes:'Recorded note'}),
            fields:[{field:'quantity',before:'1',after:'3'},{field:'notes',before:'Queue note',after:'Recorded note'}]});
          const addedRow=id=>({change:'added',label:'Added card '+id,watch_row_id:id,current:queueRow('Added card '+id)});
          const removedRow=id=>({change:'removed',label:'Removed card '+id,restored:queueRow('Removed card '+id)});
          const mixedPreview=(counts={updated:1,added:1,removed:1},extra={})=>{
            const rows=[...Array.from({length:counts.updated},(_,i)=>updatedRow(7+i)),...Array.from({length:counts.added},(_,i)=>addedRow(100+i)),
              ...Array.from({length:counts.removed},(_,i)=>removedRow(200+i))],total=rows.length;
            return strip(preview({kind:'watchlist',action:'watchlist_mixed',label:'Changes to '+total+' purchase-queue rows',row_count:total,counts,rows,
              ...(counts.added?{reason_required:true}:{}),...extra}));
          };
          const done=(p=mixedPreview(),extra={})=>{const a=accepted(p,{action:'watchlist_mixed',row_count:p.row_count,
            restored_rows:p.rows.filter(item=>item.change==='updated').map(item=>({watch_row_id:item.watch_row_id,row:{...item.restored}})),
            removed_watch_row_ids:p.rows.filter(item=>item.change==='added').map(item=>item.watch_row_id),
            new_rows:p.rows.filter(item=>item.change==='removed').map((item,index)=>({watch_row_id:500+index,row:{...item.restored}})),
            summary:'Undo change #42: undo Changes to 3 purchase-queue rows',...extra});if(!Object.hasOwn(extra,'restored'))delete a.restored;return a;};
          const reason=sheet=>sheet.body.querySelector('input');
          const giveReason=(sheet,value='Shop check mistake')=>{const input=reason(sheet);input.value=value;input.fire('input');return input;};
        ''' + scenario)

    def test_every_row_is_shown_by_its_effect_before_a_required_reason(self):
        self.run_js(r'''
          const {sheet}=await open(mixedPreview());const text=sheet.body.textContent;
          for(const words of ['Undo reverses this whole change together: it restores the recorded values of the row it updated; it removes the row it added; it adds the row it removed back to the queue as a new row, near where it was.',
            'Review all 3 purchase-queue rows below. There is no partial selection.','original change stays in Activity','Nothing is ordered, bought or cancelled',
            'Updated row: recorded values to restore','Added row to remove','Removed row to add back','Updated card 7','Added card 100','Removed card 200',
            'Recorded note','Reference price (AUD)','Reason for removing this added purchase-queue row (required)','Enter why this row should come off the purchase queue.'])assert(text.includes(words),words);
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,3);assert.equal(sheet.body.querySelectorAll('input').length,1);
          assert(save(sheet).disabled);giveReason(sheet,'  ');assert(save(sheet).disabled);giveReason(sheet);assert(!save(sheet).disabled);
        ''')

    def test_plural_groups_and_a_mix_without_additions_has_no_reason(self):
        self.run_js(r'''
          let text=(await open(mixedPreview({updated:2,added:2,removed:2}))).sheet.body.textContent;
          for(const words of ['restores the recorded values of all 2 rows it updated','removes all 2 rows it added',
            'adds all 2 rows it removed back to the queue, each as a new row near where it was','Updated rows: recorded values to restore',
            'Added rows to remove','Removed rows to add back','Reason for removing all these added purchase-queue rows (required)','Enter why these rows should come off'])assert(text.includes(words),words);
          const {sheet}=await open(mixedPreview({updated:1,added:0,removed:1}));text=sheet.body.textContent;
          assert.equal(sheet.body.querySelectorAll('input').length,0);assert(!save(sheet).disabled);
          for(const words of ['removes','Added row','Reason'])assert(!text.includes(words),words);
        ''')

    def test_fifty_rows_are_reviewed_while_any_other_packet_fails(self):
        self.run_js(r'''
          assert(save((await open(mixedPreview({updated:20,added:20,removed:10}))).sheet));
          const good=mixedPreview(),rows=good.rows;
          for(const extra of [{row_count:4},{label:'Changes to 3 rows'},{counts:{updated:1,added:1,removed:2}},{counts:{updated:3,added:0,removed:0},reason_required:undefined},
            {reason_required:false},{space:'user2'},{proof:{}},{rows:[rows[1],rows[0],rows[2]]},{rows:[rows[0],{...rows[1],watch_row_id:7},rows[2]]},
            {rows:[{...rows[0],fields:[]},rows[1],rows[2]]},{rows:[rows[0],{...rows[1],extra:1},rows[2]]},{rows:[rows[0],rows[1],{...rows[2],watch_row_id:9}]},
            {rows:[rows[0],{...rows[1],current:{...rows[1].current,quantity:'0'}},rows[2]]},{rows:[rows[0],rows[1],{...rows[2],label:' '}]},
            {rows:[rows[0],{...rows[1],change:'removed'},rows[2]]}]){
            const p=mixedPreview(undefined,extra);if(extra.reason_required===undefined&&Object.hasOwn(extra,'reason_required'))delete p.reason_required;
            const made=await open(p);assert(!save(made.sheet),JSON.stringify(extra));assert.equal(reason(made.sheet),null);
          }
          const noAdds=mixedPreview({updated:1,added:0,removed:1},{reason_required:true});assert(!save((await open(noAdds)).sheet));
        ''')

    def test_save_posts_the_normalized_reason_and_checks_every_part_of_the_receipt(self):
        self.run_js(r'''
          const {sheet,p}=await open(mixedPreview());giveReason(sheet,'  Shop   check mistake ');const sent=[];
          apiWrite=async(path,body)=>{sent.push([path,body]);return done(p);};save(sheet).click();await settle();
          same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64),reason:'Shop check mistake'}]]);assert(button(sheet.dialog,'Done'));
          const base=done(p);
          for(const extra of [{removed_watch_row_ids:[]},{removed_watch_row_ids:[7]},{restored_rows:[]},
            {restored_rows:[{...base.restored_rows[0],row:{...base.restored_rows[0].row,notes:'Other'}}]},{restored_rows:[{...base.restored_rows[0],watch_row_id:8}]},
            {new_rows:[]},{new_rows:[{...base.new_rows[0],watch_row_id:100}]},{new_rows:[{...base.new_rows[0],watch_row_id:7}]},
            {new_rows:[{...base.new_rows[0],row:{...base.new_rows[0].row,quantity:'2'}}]},
            {action:'watchlist_update'},{row_count:2},{restored:null},{sha256:'bad'},{summary:''},{space:'user2'}]){
            const {sheet,p}=await open(mixedPreview());giveReason(sheet);apiWrite=async()=>done(p,extra);save(sheet).click();await settle();
            assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));
          }
        ''')

    def test_a_mix_without_additions_posts_only_the_receipt(self):
        self.run_js(r'''
          const {sheet,p}=await open(mixedPreview({updated:1,added:0,removed:1}));const sent=[];
          apiWrite=async(path,body)=>{sent.push([path,body]);return done(p);};save(sheet).click();await settle();
          same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64)}]]);assert(button(sheet.dialog,'Done'));
        ''')

    def test_values_are_plain_local_text(self):
        self.run_js(r'''
          const raw='<img src=x onerror=alert(1)>',p=mixedPreview();p.rows[0].label=raw;p.rows[1].current.notes=raw;p.rows[2].restored.source=raw;
          const {sheet}=await open(p),hash=location.hash;
          assert(sheet.body.textContent.includes(raw));assert.equal(sheet.body.querySelector('img'),null);assert.equal(location.hash,hash);
        ''')


if __name__ == "__main__":
    unittest.main()
