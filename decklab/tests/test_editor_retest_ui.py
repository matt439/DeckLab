"""An explicit post-save field request preserves confirmed saves, later edits and viewer ownership."""
import unittest

from decklab.tests import test_editor_panes_ui as panes
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, 'Node.js is not installed')
class EditorRetestTests(unittest.TestCase):
    def run_js(self, scenario):
        panes.EditorPanesUiTests.run_js(self, r'''
          const oldSha='a'.repeat(64),newSha='b'.repeat(64),writes=[];
          let saveAnswer=null,runResolve=null,runReject=null,removed=0;
          api=async path=>{if(path.startsWith('/api/deck/draft?'))return {available:false};assert.equal(path,'/api/library/forge');return {decks:{},error:null};};
          apiWrite=async(path,body)=>{
            writes.push({path,body});
            if(path==='/api/deck/save')return saveAnswer;
            assert.equal(path,'/api/field/run');return new Promise((resolve,reject)=>{runResolve=resolve;runReject=reject;});
          };
          removeDraft=()=>{removed++;return true;};showToast=()=>{};toast=()=>{};
          function readyRetest(extra={}) {
            state.simulations={may_start:true};
            const ed=full({forge_lists:{target:oldSha,owned:oldSha},...extra});
            setQty(ed.lists.Deck[0].uid,5);
            const control=ed.dom.forgeSummary;
            assert(!control.choice.hidden&&!control.input.checked&&!control.input.disabled);
            control.input.checked=true;control.input.fire('change');assert(ed.retestAfterSave);
            saveAnswer={id:ed.id,title:ed.title,changed:true,deck:view({sha256:newSha,
              forge_lists:{target:newSha,owned:oldSha},lists:{target:structuredClone(ed.lists),owned:structuredClone(list)}})};
            return ed;
          }
        ''' + scenario)

    def test_confirmed_save_is_shown_before_the_single_field_request_finishes(self):
        self.run_js(r'''
          const ed=readyRetest(),profile=ed.profile,oldSnapshot=snapshot(ed);
          assert(!oldSnapshot.includes('retestAfterSave'));await doSave(null,ed.dom.barParts.save);
          const current=editor;
          assert(current!==ed&&!current.dirty);assert.equal(current.sha256,newSha);assert.equal(removed,1);
          assert(current.dom.banners.textContent.includes('Requesting its field re-test'));
          same(writes.map(w=>w.path),['/api/deck/save','/api/field/run']);
          same(writes[1].body,{profile,id:ed.id,version:'target',expected_card_sha:newSha});
          const notice=current.dom.afterSaveTestNotice,plus=current.dom.lines.querySelector('.step-plus');
          setQty(current.lists.Deck[0].uid,6);current.prose.notes+='\n\nLater note.';changed({list:false});
          const later=JSON.stringify(draftBody()),history=current.history.length;plus.focus();
          runResolve({status:'queued'});await settle();
          assert(editor===current&&document.activeElement===plus);
          assert.equal(JSON.stringify(draftBody()),later);assert.equal(current.history.length,history);
          assert(current.dom.afterSaveTestNotice===notice);assert(notice.text.textContent.includes('Field re-test requested'));
          assert.equal(writes.length,2);assert.equal(removed,1);assert(!current.retestAfterSave);
        ''')

    def test_failed_or_uncertain_queue_keeps_the_save_and_later_draft_without_a_retry(self):
        self.run_js(r'''
          for(const status of [0,403,409,503]) {
            const ed=readyRetest();await doSave(null,ed.dom.barParts.save);const current=editor;
            setQty(current.lists.Deck[0].uid,7);const later=JSON.stringify(draftBody()),count=writes.length;
            runReject(new ApiError(status,'Fixture field refusal'));await settle();
            assert(editor===current);assert.equal(current.sha256,newSha);assert.equal(JSON.stringify(draftBody()),later);
            assert(current.dom.banners.textContent.includes('The deck was saved'));
            assert(current.dom.banners.textContent.includes('could not be confirmed'));
            assert(current.dom.banners.textContent.includes('Check Matchups before starting another run'));
            assert.equal(writes.length,count);
          }
        ''')

    def test_late_run_resolve_or_reject_cannot_replace_another_page_or_person(self):
        self.run_js(r'''
          for(const change of [()=>{routeToken++;},()=>{state.profile=state.profiles[0];},()=>{full();}]) {
            for(const fails of [false,true]) {
              state.profile=state.profiles[1];const ed=readyRetest();await doSave(null,ed.dom.barParts.save);
              const current=editor,notice=current.dom.afterSaveTestNotice,resolve=runResolve,reject=runReject;
              change();const owner=editor,before=JSON.stringify(draftBody()),count=removed;
              if(fails)reject(new ApiError(0,'Lost response'));else resolve({status:'queued'});await settle();
              assert(editor===owner);assert.equal(JSON.stringify(draftBody()),before);assert.equal(removed,count);
              assert(notice.text.textContent.includes('Requesting its field re-test'));
            }
          }
        ''')

    def test_stale_save_response_is_recorded_without_a_run_or_current_page_takeover(self):
        self.run_js(r'''
          const ed=readyRetest();let release;
          apiWrite=async(path,body)=>{writes.push({path,body});return new Promise(resolve=>release=resolve);};
          const pending=doSave(null,ed.dom.barParts.save);full();const current=editor,before=JSON.stringify(draftBody());
          release(saveAnswer);await pending;
          assert(editor===current);assert.equal(JSON.stringify(draftBody()),before);assert.equal(removed,0);
          assert.equal(writes.length,1);assert(ed.confirmedSave===saveAnswer);
        ''')

    def test_checkbox_tracks_refreshed_permission_and_its_choice_stays_outside_draft_history(self):
        self.run_js(r'''
          const ed=readyRetest(),context=ed.dom.forgeSummary,before=JSON.stringify(draftBody()),history=ed.history.length;
          renderSimulations({may_start:false,why_not:'Simulations are paused.'});
          assert(context.input.disabled&&!context.reason.hidden);assert.equal(context.reason.textContent,'Simulations are paused.');
          renderSimulations({may_start:true});assert(!context.input.disabled&&context.reason.hidden&&context.input.checked);
          assert.equal(JSON.stringify(draftBody()),before);assert.equal(ed.history.length,history);
          for(const off of [()=>{ed.saving=true;},()=>{ed.asking=true;},()=>{ed.dirty=false;drawBar();}]) {
            off();context.input.checked=false;context.input.fire('change');assert(ed.retestAfterSave);
            ed.saving=false;ed.asking=false;ed.dirty=true;drawBar();
          }
        ''')

    def test_missing_returned_identity_or_new_pause_keeps_success_without_a_run(self):
        self.run_js(r'''
          let ed=readyRetest();delete saveAnswer.deck.forge_lists;await doSave(null,ed.dom.barParts.save);await settle();
          assert.equal(writes.length,1);assert(editor.dom.banners.textContent.includes('could not be confirmed for re-testing'));
          ed=readyRetest();state.simulations={may_start:false,why_not:'Paused now.'};
          const count=writes.length;await doSave(null,ed.dom.barParts.save);await settle();
          assert.equal(writes.length,count+1);assert(editor.dom.banners.textContent.includes('Paused now.'));
        ''')

    def test_failed_save_or_unchecked_choice_never_submits_a_field_request(self):
        self.run_js(r'''
          let ed=readyRetest();ed.retestAfterSave=false;drawBar();await doSave(null,ed.dom.barParts.save);
          assert.equal(writes.length,1);assert(!editor.afterSaveTest);
          ed=readyRetest();apiWrite=async(path,body)=>{writes.push({path,body});throw new ApiError(409,'Fixture save conflict');};
          let conflict=0;showConflict=()=>{conflict++;};const count=writes.length;
          await doSave(null,ed.dom.barParts.save);assert.equal(conflict,1);assert.equal(writes.length,count+1);
          assert(editor===ed);assert(!runResolve);
        ''')

    def test_save_and_view_owns_its_result_message_and_never_exposes_it_to_another_profile(self):
        self.run_js(r'''
          const ed=readyRetest();await doSave(null,ed.dom.barParts.save,{viewAfter:true});
          const receipt=state.saved;assert.equal(receipt.profile,ed.profile);
          location.hash=receipt.hash;const box=savedBox(ed.id);main.append(box);
          assert(box.textContent.includes('Requesting its field re-test'));
          runResolve({status:'queued'});await settle();assert(box.textContent.includes('Field re-test requested'));
          state.profile=state.profiles[0];assert.equal(savedBox(ed.id),null);
        ''')

    def test_commander_has_the_explicit_choice_without_a_constructed_summary(self):
        self.run_js(r'''
          const ed=readyRetest({kind:'commander'});assert(ed.dom.forgeSummary.input);
          assert(ed.dom.forgeSummary.root.hidden);assert(!ed.dom.forgeSummary.choice.hidden);
          startEditor({mode:'new',kind:'casual',restoreDraft:false});assert(!editor.dom.forgeSummary);
          full({may_save:false,forge_lists:{target:oldSha}});assert(!editor.dom.forgeSummary.input);
        ''')
