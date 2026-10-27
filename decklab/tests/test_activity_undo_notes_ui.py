"""Notes join the complete metadata review without adding stock or partial writes."""
import unittest

from decklab.tests import test_activity_undo_batch_ui as batches
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoNotesUiTests(unittest.TestCase):
    def run_js(self, scenario):
        batches.ActivityUndoBatchUiTests.run_js(self, r'''
          const noteRow=(number,before,after)=>{
            const item=batchRow(number);item.current.notes=before;item.restored={...item.current,notes:after};
            item.fields=[{field:'notes',before,after}];return item;
          };
        ''' + scenario)

    def test_notes_only_and_mixed_metadata_are_complete_plain_text_with_explicit_blanks(self):
        self.run_js(r'''
          const raw='<img src=x onerror=alert(1)> & original note',current='Entered by mistake\nSecond source line',one=noteRow(1,current,''),two=noteRow(2,'',raw);
          two.restored.condition='';two.fields.unshift({field:'condition',before:'NM',after:''});
          const p=batchPreview({rows:[one,two]}),before=JSON.stringify(p),{sheet}=await open(p);
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,2);
          for(const text of ['Notes:','Entered by mistake','Not recorded',raw,'Condition: NM','restored together'])assert(sheet.body.textContent.includes(text),text);
          assert.equal(sheet.body.querySelector('img'),null);assert.equal(sheet.body.querySelectorAll('input,textarea,select').length,0);
          assert.equal(sheet.body.querySelectorAll('.activity-undo-note').length,4);assert.equal(sheet.body.querySelector('.activity-undo-note').textContent,current);
          assert(!sheet.body.textContent.includes('Quantity:'));assert(!save(sheet).disabled);assert.equal(JSON.stringify(p),before);
        ''')

    def test_fifty_notes_are_all_reviewed_without_exposing_unchanged_metadata(self):
        self.run_js(r'''
          const rows=Array.from({length:50},(_,i)=>noteRow(i+1,'Current note '+(i+1),'Historical note '+(i+1))),p=batchPreview({row_count:50,rows});
          const {sheet}=await open(p);assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,50);
          for(const text of ['Current note 1','Historical note 1','Current note 50','Historical note 50'])assert(sheet.body.textContent.includes(text));
          assert(!sheet.body.textContent.includes('Condition:'));assert(!sheet.body.textContent.includes('Language:'));assert(save(sheet));
        ''')

    def test_notes_never_make_quantity_identity_or_incomplete_field_changes_eligible(self):
        self.run_js(r'''
          for(const mode of ['quantity','name','finish','missing-note','wrong-note','noop']){
            const one=noteRow(1,'Current','Historical');
            if(mode==='quantity'){one.restored.quantity--;one.fields.push({field:'quantity',before:one.current.quantity,after:one.restored.quantity});}
            if(mode==='name')one.restored.name='Different card';if(mode==='finish')one.restored.finish='foil';
            if(mode==='missing-note')one.fields=[];if(mode==='wrong-note')one.fields[0].after='Unproved';
            if(mode==='noop'){one.restored.notes=one.current.notes;one.fields[0].after=one.current.notes;}
            const {sheet}=await open(batchPreview({rows:[one,noteRow(2,'Other current','Other historical')]}));assert(!save(sheet),mode);
          }
        ''')

    def test_note_save_is_one_request_and_every_saved_note_must_match_by_printing_key(self):
        self.run_js(r'''
          const rows=[noteRow(1,'Current','Historical'),noteRow(2,'Other','')];
          const {sheet,p}=await open(batchPreview({rows}));let writes=0,body;
          apiWrite=async(path,request)=>{writes++;body=request;const reply=batchSaved(p);reply.restored_rows.reverse();return reply;};
          const old=save(sheet);old.click();old.fire('click');await settle();assert(button(sheet.dialog,'Done'));assert.equal(writes,1);
          same(body,{id:42,expect:'a'.repeat(64)});assert(!Object.hasOwn(body,'notes'));assert(!Object.hasOwn(body,'rows'));
          for(const wrong of ['notes','quantity']){
            const made=await open(batchPreview({rows}));let attempts=0;
            apiWrite=async()=>{attempts++;const reply=batchSaved(made.p);reply.restored_rows[0].row[wrong]=wrong==='notes'?'Not restored':99;return reply;};
            const trigger=save(made.sheet);trigger.click();await settle();assert(!button(made.sheet.dialog,'Done'));assert(button(made.sheet.dialog,'Reload Activity'));
            trigger.fire('click');assert.equal(attempts,1);
          }
        ''')

    def test_a_changed_note_preview_cannot_save_even_with_matching_tampered_field_evidence(self):
        self.run_js(r'''
          const {sheet,p}=await open(batchPreview({rows:[noteRow(1,'Current','Historical'),noteRow(2,'Other','')]}));let writes=0;
          apiWrite=async()=>{writes++;return batchSaved(p);};const trigger=save(sheet);
          p.rows[0].restored.notes='Changed after review';p.rows[0].fields[0].after='Changed after review';
          trigger.fire('click');await settle();assert.equal(writes,0);assert(!button(sheet.dialog,'Done'));
        ''')


if __name__ == "__main__":
    unittest.main()
