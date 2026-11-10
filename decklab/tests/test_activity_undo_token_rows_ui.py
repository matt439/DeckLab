"""A single physical row plus internal source moves uses the same explicit batch review."""
import unittest

from decklab.tests import test_activity_undo_token_batch_remove_ui as removes
from decklab.tests import test_activity_undo_token_batch_ui as restores
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class TokenRowsUiTests(unittest.TestCase):
    def test_single_added_target_requires_reason_and_exact_single_id_receipt_without_position_authority(self):
        removes.ActivityUndoTokenBatchRemoveUiTests.run_js(self, r'''
          const packet=tokenBatch({row_count:1,label:'1 added token-card row',cards:1,
            rows:[{label:'Treasure',token_row_id:8,current:treasure()}]});
          const {sheet,p}=await open(packet);assert(save(sheet).disabled);assert.equal(sheet.body.querySelectorAll('.activity-undo-batch-row').length,1);
          giveReason(sheet);const sent=[];apiWrite=async(path,body)=>{sent.push(body);return removed(p,{removed_token_row_ids:[8]});};
          save(sheet).click();await settle();same(sent,[{id:42,expect:'a'.repeat(64),reason:'Wrong batch'}]);
          assert(button(sheet.dialog,'Done'));assert(!JSON.stringify(sent).includes('position'));
        ''')

    def test_single_deleted_target_needs_physical_confirmation_and_exact_fresh_id_receipt(self):
        restores.ActivityUndoTokenBatchUiTests.run_js(self, r'''
          const packet=tokenBatch({row_count:1,label:'1 deleted token-card row',cards:1,
            rows:[{label:'Treasure',restored:treasure()}]});
          const {sheet,p}=await open(packet);assert(save(sheet).disabled);assert.equal(owned(sheet).checked,false);
          confirmOwned(sheet);const sent=[];apiWrite=async(path,body)=>{sent.push(body);return restored(p,{added_token_row_ids:[900]});};
          save(sheet).click();await settle();same(sent,[{id:42,expect:'a'.repeat(64),confirm_owned:true}]);
          assert(button(sheet.dialog,'Done'));assert(!JSON.stringify(sent).includes('position'));
        ''')
