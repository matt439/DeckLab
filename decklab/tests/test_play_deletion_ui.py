"""Reasoned deletion belongs to the connected, unchanged record and original viewer."""
import unittest

from decklab.tests import test_play_pods_ui as pod_ui
from decklab.tests.test_workspace_ui import NODE

SETUP = r'''
  editor=null;  // The Game log has no open deck editor.
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

    def test_background_conflict_returns_to_review_then_requires_a_new_explicit_confirmation(self):
        self.run_js(r'''
          const write=deferred(),read=deferred(),{sheet,saved}=openDelete();
          const confirm=buttonText(sheet.foot,'Delete game'),cancel=buttonText(sheet.foot,'Keep game');
          const reads=[];
          apiWrite=(path,body)=>{writes.push(body);return write.promise;};
          api=(path,options)=>{reads.push(path);assert.equal(options.wakeHop,false);return read.promise;};
          deletionReason(sheet).value='Duplicate after checking';confirm.click();
          document.visibilityState='hidden';document.fire('visibilitychange');
          write.reject(Error('The game changed.'));await settle();
          assert(cancel.disabled);assert(confirm.disabled);assert.equal(reads.length,0);
          document.visibilityState='visible';document.fire('visibilitychange');
          assert(!cancel.disabled);assert(!confirm.disabled);assert.equal(confirm.textContent,'Review current game');
          assert(sheet.body.textContent.includes('The game changed.'));assert.equal(deletionReason(sheet).value,'Duplicate after checking');
          confirm.click();confirm.click();same(reads,['/api/play']);assert.equal(writes.length,1);
          document.visibilityState='hidden';
          const current=entry({record:{...saved.record,notes:'Freshly corrected pod'},sha256:shaB,can:{delete:true}});
          read.resolve(packet({pods:[current]}));await settle();assert(!sheet.body.textContent.includes('Freshly corrected pod'));
          document.visibilityState='visible';document.fire('visibilitychange');
          assert(sheet.body.textContent.includes('Freshly corrected pod'));assert.equal(confirm.textContent,'Delete game');
          apiWrite=async(path,body)=>{writes.push(body);return {deleted:true,id:podId};};
          confirm.click();await settle();assert(sheet.closed);
          same(writes.map(w=>[w.sha256,w.reason]),[[shaR,'Duplicate after checking'],[shaB,'Duplicate after checking']]);
        ''')

    def test_background_success_refreshes_only_the_same_open_sheet_and_profile_once(self):
        self.run_js(r'''
          for(const abandon of ['closed','profile','route','none']){
            const response=deferred(),{sheet}=openDelete();apiWrite=()=>response.promise;
            deletionReason(sheet).value='Duplicate';buttonText(sheet.foot,'Delete game').click();
            document.visibilityState='hidden';response.resolve({deleted:true,id:podId});await settle();
            assert.equal(routes.length,0);assert.equal(messages.length,0);
            if(abandon==='closed')closeAllSheets();
            if(abandon==='profile')state.profile={...state.profile};
            if(abandon==='route')routeToken++;
            document.visibilityState='visible';document.fire('visibilitychange');document.fire('visibilitychange');
            if(abandon==='none'){assert(sheet.closed);same(routes,['#/play']);same(messages,['Game deleted.']);}
            else {assert.equal(routes.length,0);assert.equal(messages.length,0);sheet.close();}
          }
        ''')

    def test_route_and_profile_cleanup_remove_the_private_record_review(self):
        self.run_js(r'''
          const {sheet,saved}=openDelete();
          deletionReason(sheet).value='Private reason';
          apiWrite=async()=>{throw Error('Record changed');};
          buttonText(sheet.foot,'Delete game').click();await settle();
          api=async()=>packet({pods:[{...saved,record:{...saved.record,notes:'Private corrected note'}}]});
          buttonText(sheet.foot,'Review current game').click();await settle();
          assert(document.body.textContent.includes('Private corrected note'));
          closeAllSheets();
          assert(sheet.closed);assert(!sheet.dialog.isConnected);assert.equal(playDeleteSheet,null);
          assert(!document.body.textContent.includes('Private corrected note'));
        ''')

    def test_failed_refresh_and_missing_or_revoked_game_cannot_retry_the_write(self):
        self.run_js(r'''
          for(const missing of [true,false]){
            const {sheet}=openDelete(),confirm=buttonText(sheet.foot,'Delete game');
            apiWrite=async(path,body)=>{writes.push(body);throw Error('Connection lost');};
            deletionReason(sheet).value='Duplicate';confirm.click();await settle();
            api=async()=>{throw Error('Still offline');};confirm.click();await settle();
            assert(sheet.body.textContent.includes('Still offline'));assert.equal(confirm.textContent,'Review current game');
            api=async()=>packet({pods:missing?[]:[entry({can:{delete:false}})]});
            confirm.click();await settle();assert(confirm.disabled);assert(sheet.body.textContent.includes('no longer available'));
            assert.equal(deletionReason(sheet).value,'Duplicate');sheet.body.querySelector('form').fire('submit');await settle();
            buttonText(sheet.foot,'Keep game').click();assert(sheet.closed);
          }
          assert.equal(writes.length,2);
        ''')
