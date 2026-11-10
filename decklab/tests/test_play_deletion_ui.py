"""Reasoned deletion belongs to the connected, unchanged record and original viewer."""
import unittest

from decklab.tests import test_play_pods_ui as pod_ui
from decklab.tests.test_workspace_ui import NODE

SETUP = r'''
  const deletable=()=>entry({can:{edit:true,delete:true}});
  const openDelete=()=>{const saved=deletable(),data=packet({pods:[saved]});const section=mount(data);
    const source=buttonText(section,'Delete this game');assert(source);source.click();return{saved,data,source,sheet:sheets.at(-1)};};
  const deletionReason=sheet=>sheet.body.querySelector('textarea');
'''


@unittest.skipUnless(NODE, "Node.js is not installed")
class PlayDeletionUiTests(unittest.TestCase):
    def run_js(self, scenario):
        pod_ui.PodUiTests.run_js(self, SETUP + scenario)

    def test_requires_a_reason_and_confirmation_then_sends_only_one_scoped_delete(self):
        self.run_js(r'''
          let resolve;apiWrite=(path,body)=>{writes.push([path,body]);return new Promise(done=>resolve=done);};
          const {sheet,saved}=openDelete(),confirm=buttonText(sheet.foot,'Delete game');
          confirm.click();await settle();assert.equal(writes.length,0);assert(sheet.body.textContent.includes('Give a reason'));
          deletionReason(sheet).value='Duplicate fixture';confirm.click();confirm.click();assert.equal(writes.length,1);
          same(writes[0],['/api/play/game/delete',{id:saved.record.id,sha256:saved.sha256,reason:'Duplicate fixture',confirmed:true}]);
          resolve({deleted:true,id:saved.record.id});await settle();assert(sheet.closed);assert.equal(routes.length,1);
        ''')

    def test_cancel_or_missing_positive_delete_right_never_sends_a_request(self):
        self.run_js(r'''
          for(const can of [{edit:true},{edit:true,delete:false},{edit:false,delete:'true'}]){
            clear(main);const saved=entry({can});const data=packet({pods:[saved]});const section=mount(data);
            assert.equal(buttonText(section,'Delete this game'),undefined);
          }
          const {sheet}=openDelete();buttonText(sheet.foot,'Keep game').click();assert(sheet.closed);assert.equal(writes.length,0);
        ''')

    def test_owner_or_record_drift_or_moved_reason_controls_prevent_deletion(self):
        self.run_js(r'''
          const cases=[ctx=>state.profile={...state.profile},ctx=>routeToken++,ctx=>location.hash='#/library',
            ctx=>ctx.saved.sha256='f'.repeat(64),ctx=>ctx.saved.record.notes='Changed record',ctx=>ctx.source.remove(),
            ctx=>ctx.sheet.body.append(deletionReason(ctx.sheet)),ctx=>ctx.saved.can.delete=false];
          for(const change of cases){
            for(const sheet of sheets)if(!sheet.closed)sheet.close();clear(main);location.hash='#/play';
            const ctx=openDelete();deletionReason(ctx.sheet).value='Duplicate';change(ctx);
            buttonText(ctx.sheet.foot,'Delete game').click();await settle();assert.equal(writes.length,0);
          }
        ''')

    def test_stale_reply_preserves_the_reason_and_late_success_never_refreshes_another_page(self):
        self.run_js(r'''
          apiWrite=async()=>{const error=Error('Game changed; review its current record.');error.status=409;throw error;};
          let ctx=openDelete();deletionReason(ctx.sheet).value='Keep this reason';buttonText(ctx.sheet.foot,'Delete game').click();await settle();
          assert.equal(deletionReason(ctx.sheet).value,'Keep this reason');assert(!ctx.sheet.closed);assert.equal(routes.length,0);
          ctx.sheet.close();let resolve;apiWrite=()=>new Promise(done=>resolve=done);
          ctx=openDelete();deletionReason(ctx.sheet).value='Duplicate';buttonText(ctx.sheet.foot,'Delete game').click();
          state.profile={...state.profile};resolve({deleted:true,id:ctx.saved.record.id});await settle();
          assert.equal(routes.length,0);assert.equal(messages.length,0);
        ''')
