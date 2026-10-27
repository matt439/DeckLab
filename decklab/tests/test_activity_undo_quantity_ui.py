"""Positive-quantity batch Undo keeps separate evidence and complete keyed receipts."""
import unittest

from decklab.tests import test_activity_undo_batch_ui as batches
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoQuantityUiTests(unittest.TestCase):
    def run_js(self, scenario):
        batches.ActivityUndoBatchUiTests.run_js(self, r'''
          const quantityRow=(number,before=6,after=4)=>{
            const item=batchRow(number);item.current.quantity=before;item.restored={...item.current,quantity:after};
            item.fields=[{field:'quantity',before,after}];return item;
          };
          const quantityPreview=(extra={})=>batchPreview({action:'batch_update',rows:[quantityRow(1),quantityRow(2,2,5)],...extra});
          const quantitySaved=(p=quantityPreview(),extra={})=>batchSaved(p,{action:'batch_update',...extra});
        ''' + scenario)

    def test_complete_quantities_and_mixed_metadata_are_reviewed_without_stock_inputs(self):
        self.run_js(r'''
          const one=quantityRow(1),two=quantityRow(2,2,5);two.restored.notes='Historical note';two.fields.push({field:'notes',before:two.current.notes,after:'Historical note'});
          const p=quantityPreview({rows:[one,two]}),before=JSON.stringify(p),{sheet}=await open(p);
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,2);
          for(const text of ['current and restored copy counts','cards in use','Quantity:','Notes:','Historical note','restored together'])assert(sheet.body.textContent.includes(text),text);
          assert.equal(sheet.body.querySelectorAll('input,textarea,select').length,0);assert(save(sheet));assert.equal(JSON.stringify(p),before);
        ''')

    def test_quantities_stay_positive_bounded_integers_and_metadata_action_cannot_hide_them(self):
        self.run_js(r'''
          for(const value of [0,-1,10000,1.5,'4',true,null]){
            const one=quantityRow(1,6,value);const {sheet}=await open(quantityPreview({rows:[one,quantityRow(2)]}));assert(!save(sheet),String(value));
          }
          assert(save((await open(quantityPreview({rows:[quantityRow(1,9999,1),quantityRow(2,1,9999)]}))).sheet));
          assert(!save((await open(quantityPreview({action:'batch_metadata'}))).sheet));
          assert(!save((await open(quantityPreview({rows:batchPreview().rows}))).sheet));
          for(const field of ['name','finish','set','collector_number']){
            const one=quantityRow(1);one.restored[field]='Changed identity';const {sheet}=await open(quantityPreview({rows:[one,quantityRow(2)]}));assert(!save(sheet),field);
          }
        ''')

    def test_fifty_quantities_are_reviewed_together_without_a_partial_selection(self):
        self.run_js(r'''
          const p=quantityPreview({row_count:50,rows:Array.from({length:50},(_,i)=>quantityRow(i+1,2,1))}),{sheet}=await open(p);
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,50);assert(sheet.body.textContent.includes('Fixture printing 50'));
          assert.equal(sheet.body.querySelectorAll('input').length,0);assert(save(sheet));
          const invalid=quantityPreview({row_count:51,rows:Array.from({length:51},(_,i)=>quantityRow(i+1,2,1))});assert(!save((await open(invalid)).sheet));
        ''')

    def test_save_sends_one_source_receipt_and_matches_reordered_actual_rows_including_quantities(self):
        self.run_js(r'''
          const {sheet,p}=await open(quantityPreview());let writes=0,body;
          apiWrite=async(path,request)=>{writes++;body=request;const result=quantitySaved(p);result.restored_rows.reverse();return result;};
          const trigger=save(sheet);trigger.click();trigger.fire('click');await settle();assert(button(sheet.dialog,'Done'));assert.equal(writes,1);
          same(body,{id:42,expect:'a'.repeat(64)});assert(!Object.hasOwn(body,'quantity'));assert(!Object.hasOwn(body,'rows'));
          for(const mode of ['quantity','action','key','missing']){
            const made=await open(quantityPreview());let attempts=0;
            apiWrite=async()=>{attempts++;const result=quantitySaved(made.p);if(mode==='quantity')result.restored_rows[0].row.quantity++;
              if(mode==='action')result.action='batch_metadata';if(mode==='key')result.restored_rows[0].key.finish='foil';if(mode==='missing')result.restored_rows.pop();return result;};
            const old=save(made.sheet);old.click();await settle();assert(!button(made.sheet.dialog,'Done'),mode);assert(button(made.sheet.dialog,'Reload Activity'));old.fire('click');assert.equal(attempts,1);
          }
        ''')

    def test_mutated_quantity_evidence_or_foreign_owner_cannot_write_after_review(self):
        self.run_js(r'''
          for(const mode of ['quantity','profile','filter']){
            const {sheet,p,view}=await open(quantityPreview());let writes=0;apiWrite=async()=>{writes++;return quantitySaved(p);};const old=save(sheet);
            if(mode==='quantity'){p.rows[0].restored.quantity=3;p.rows[0].fields[0].after=3;}
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='filter')view.filter.kind='tokens';
            old.fire('click');await settle();assert.equal(writes,0,mode);
          }
        ''')


if __name__ == "__main__":
    unittest.main()
