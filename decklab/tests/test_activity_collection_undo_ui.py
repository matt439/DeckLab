"""Whole collection recovery uses literal rows, explicit gates and the original sheet owner."""
import unittest

from decklab.tests import test_activity_undo_ui as existing
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class CollectionRecoveryUiTests(unittest.TestCase):
    def run_js(self, scenario):
        existing.ActivityUndoUiTests.run_js(self, r'''
          const old=()=>collectionRow({quantity:2,notes:'Historical <svg onload=private()> literal note'});
          const changed=()=>collectionRow({set:'m19',collector_number:'314',quantity:3,notes:'Present note'});
          const key=row=>({set:row.set,collector_number:row.collector_number,finish:row.finish});
          const label=row=>`${row.name} (${row.set.toUpperCase()} ${row.collector_number}, ${row.finish})`;
          const packet=(extra={})=>{const p=preview({action:'collection_change_restore',label:'Complete collection change (2 rows)',row_count:2,
            rows:[{key:key(old()),label:label(old()),current:null,restored:old()},
              {key:key(changed()),label:label(changed()),current:changed(),restored:null}],reason_required:true,
            physical_confirmation_required:true,location_transfer:{from:key(changed()),to:key(old()),location:'Row 4'},...extra});
            delete p.current;delete p.restored;delete p.fields;return p;};
          const receipt=(p,extra={})=>({saved:true,source_id:p.id,expect:p.expect,kind:'collection',space:p.space,action:p.action,row_count:p.row_count,
            rows:p.rows.map(item=>({key:{...item.key},row:item.restored&&{...item.restored}})),sha256:'c'.repeat(64),locations_sha256:'d'.repeat(64),summary:'Restored the complete collection change.',...extra});
          const reason=sheet=>sheet.body.querySelectorAll('input').find(node=>node.getAttribute('type')==='text');
          const owned=sheet=>sheet.body.querySelectorAll('input').find(node=>node.getAttribute('type')==='checkbox');
          const consent=sheet=>{owned(sheet).checked=true;owned(sheet).fire('change');reason(sheet).value='Wrong printing';reason(sheet).fire('input');};
        ''' + scenario)

    def test_every_literal_row_and_location_policy_are_visible_before_both_explicit_gates(self):
        self.run_js(r'''
          let writes=0;apiWrite=async()=>{writes++;};const {sheet}=await open(packet());
          assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,2);
          assert(sheet.body.textContent.includes('No row'));assert(sheet.body.textContent.includes('no partial selection'));
          assert(sheet.body.textContent.includes('Row 4'));assert(sheet.body.textContent.includes('No historical location is restored'));
          assert(sheet.body.textContent.includes('Historical <svg onload=private()> literal note'));assert.equal(sheet.body.querySelector('svg'),null);
          assert.equal(sheet.body.querySelectorAll('input').length,2);assert.equal(owned(sheet).checked,false);assert(save(sheet).disabled);
          owned(sheet).checked=true;owned(sheet).fire('change');assert(save(sheet).disabled);assert.equal(writes,0);
        ''')

    def test_save_sends_only_original_source_receipt_and_required_reason_confirmation(self):
        self.run_js(r'''
          const {sheet,p}=await open(packet());consent(sheet);const writes=[];apiWrite=async(path,body)=>{writes.push([path,body]);return receipt(p);};
          const saveButton=save(sheet);saveButton.click();saveButton.fire('click');await settle();
          same(writes,[['/api/activity/undo',{id:42,expect:'a'.repeat(64),reason:'Wrong printing',confirm_owned:true}]]);
          assert(sheet.body.textContent.includes('Undo saved as a new change'));assert(saveButton.parentNode===null);
        ''')

    def test_missing_row_wrong_gate_or_wrong_transfer_is_never_a_saveable_preview(self):
        self.run_js(r'''
          for(const extra of [{rows:packet().rows.slice(0,1)},{reason_required:false},{physical_confirmation_required:false},
            {location_transfer:null},{location_transfer:{from:key(old()),to:key(changed()),location:'Row 4'}}]){
            const {sheet}=await open(packet(extra));assert(!save(sheet));
          }
        ''')

    def test_a_partial_or_wrong_saved_receipt_is_unknown_and_has_no_retry_write(self):
        self.run_js(r'''
          const {sheet,p}=await open(packet());consent(sheet);let writes=0;
          apiWrite=async()=>{writes++;return receipt(p,{rows:receipt(p).rows.slice(0,1)});};save(sheet).click();await settle();
          assert(!save(sheet));assert(!sheet.dialog.querySelectorAll('button').some(node=>node.textContent==='Done'));
          assert(sheet.dialog.querySelectorAll('button').some(node=>node.textContent==='Reload Activity'));assert.equal(writes,1);
        ''')

    def test_late_save_cannot_repaint_a_successor_and_detached_controls_cannot_authorize_a_write(self):
        self.run_js(r'''
          let made=await open(packet());consent(made.sheet);const input=reason(made.sheet);input.remove();let writes=0;
          apiWrite=async()=>{writes++;return receipt(made.p);};save(made.sheet).click();await settle();assert.equal(writes,0);
          made=await open(packet());consent(made.sheet);let resolve;apiWrite=()=>{writes++;return new Promise(done=>{resolve=done;});};
          const oldButton=save(made.sheet);oldButton.click();await settle();mount();const marker=el('div',{},'KEEP_SUCCESSOR');main.append(marker);
          resolve(receipt(made.p));await settle();assert.equal(marker.textContent,'KEEP_SUCCESSOR');assert(!main.textContent.includes('Undo saved'));
          oldButton.fire('click');await settle();assert.equal(writes,1);
        ''')

    def test_merge_undo_with_no_restored_identity_has_no_physical_confirmation(self):
        self.run_js(r'''
          const row=old(),p=packet({rows:[{key:key(row),label:label(row),current:{...row,quantity:5},restored:row},packet().rows[1]],
            physical_confirmation_required:false,location_transfer:null});
          const {sheet}=await open(p);assert.equal(owned(sheet),undefined);assert(save(sheet).disabled);
          reason(sheet).value='Wrong merge';reason(sheet).fire('input');assert(!save(sheet).disabled);
          const sent=[];apiWrite=async(path,body)=>{sent.push(body);return receipt(p);};save(sheet).click();await settle();
          same(sent,[{id:42,expect:'a'.repeat(64),reason:'Wrong merge'}]);
        ''')

    def test_card_fact_correction_preserves_location_and_needs_only_the_explicit_save(self):
        self.run_js(r'''
          const row=old(),p=packet({row_count:1,label:'Complete collection change (1 row)',
            rows:[{key:key(row),label:label(row),current:{...row,quantity:5},restored:row}],
            reason_required:false,physical_confirmation_required:false,location_transfer:null});
          const {sheet}=await open(p);assert.equal(sheet.body.querySelectorAll('input').length,0);assert(!save(sheet).disabled);
          const sent=[];apiWrite=async(path,body)=>{sent.push(body);return receipt(p);};assert.equal(sent.length,0);
          save(sheet).click();await settle();same(sent,[{id:42,expect:'a'.repeat(64)}]);
        ''')

    def test_unexpected_error_with_503_is_private_but_real_api_error_keeps_its_actionable_message(self):
        self.run_js(r'''
          let made=await open(packet());consent(made.sheet);
          apiWrite=async()=>{const error=new Error('PRIVATE_CARD_FILENAME');error.status=503;throw error;};
          save(made.sheet).click();await settle();assert(!made.sheet.body.textContent.includes('PRIVATE_CARD_FILENAME'));
          assert(made.sheet.body.textContent.includes('The Undo result could not be confirmed.'));assert(!save(made.sheet));
          made=await open(packet());consent(made.sheet);apiWrite=async()=>{throw new ApiError(503,'The database is unavailable. Check the PC.');};
          save(made.sheet).click();await settle();assert(made.sheet.body.textContent.includes('The database is unavailable. Check the PC.'));
          assert(!save(made.sheet));
        ''')
