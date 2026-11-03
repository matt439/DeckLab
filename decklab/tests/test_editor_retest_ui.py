"""An explicit post-save field request, and the popular-decks one (E3-S37), preserve confirmed saves,
later edits and viewer ownership."""
import unittest

from decklab.tests import test_editor_panes_ui as panes
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, 'Node.js is not installed')
class EditorRetestTests(unittest.TestCase):
    def run_js(self, scenario):
        panes.EditorPanesUiTests.run_js(self, r'''
          const oldSha='a'.repeat(64),newSha='b'.repeat(64),writes=[];
          let saveAnswer=null,runResolve=null,runReject=null,popResolve=null,popReject=null,removed=0;
          let catalogue={built:'2026-11-01T00:00:00',standard:{id:'sample:x',size:20,opponents:20}};const catalogueReads=[];
          const store=new Map();window.localStorage={getItem:k=>store.has(k)?store.get(k):null,
            setItem:(k,v)=>{store.set(k,String(v));},removeItem:k=>{store.delete(k);}};
          api=async path=>{if(path.startsWith('/api/deck/draft?'))return {available:false};
            if(path.startsWith('/api/gauntlet/catalogue?')){catalogueReads.push(path);return catalogue;}
            assert.equal(path,'/api/library/forge');return {decks:{},error:null};};
          apiWrite=async(path,body)=>{
            writes.push({path,body});
            if(path==='/api/deck/save')return saveAnswer;
            if(path==='/api/gauntlet/run')return new Promise((resolve,reject)=>{popResolve=resolve;popReject=reject;});
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
          const drain=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
          async function readyPopular(extra={},{field=false}={}) {
            state.simulations={may_start:true};
            const ed=full({forge_lists:{target:oldSha,owned:oldSha},...extra});
            const control=ed.dom.forgeSummary,popular=control.popular;
            assert(popular.choice.hidden);setQty(ed.lists.Deck[0].uid,5);await drain();
            assert(!popular.choice.hidden&&!popular.input.disabled);
            if(!popular.input.checked){popular.input.checked=true;popular.input.fire('change');}
            if(field){control.input.checked=true;control.input.fire('change');}
            saveAnswer={id:ed.id,title:ed.title,changed:true,deck:view({sha256:newSha,kind:ed.kind,
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
            assert(current.dom.banners.textContent.includes('Check Testing before starting another run'));
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

    # ---------------------------------------------------------------- E3-S37: popular decks after saving

    def test_popular_choice_is_offered_after_a_change_with_the_sample_size_and_starts_one_standard_run(self):
        self.run_js(r'''
          const ed=await readyPopular(),profile=ed.profile,popular=ed.dom.forgeSummary.popular;
          same(catalogueReads,['/api/gauntlet/catalogue?format=constructed']);
          assert(popular.words.textContent.includes('Test against popular decks after saving (same 20 opponents)'));
          assert(!snapshot(ed).includes('testPopular'));
          assert.equal(editorPopularReviewLine(ed),'Then tests the saved list against the same 20 popular decks (about 2,000 games).');
          const review=openSheet('Save?');drawReview(review,{blocks:[],warnings:[],changes:{decklist:true,categories:false,considering:false,fields:[],prose:[],marker:false}});
          assert(review.body.textContent.includes('(about 2,000 games)'));review.close();
          await doSave(null,ed.dom.barParts.save);const current=editor;
          same(writes.map(w=>w.path),['/api/deck/save','/api/gauntlet/run']);
          same(writes[1].body,{profile,id:ed.id,version:'target',expected_card_sha:newSha});
          assert(current.dom.banners.textContent.includes('Starting its popular-decks test'));
          assert(!current.dom.banners.textContent.includes('field re-test'));
          setQty(current.lists.Deck[0].uid,6);const later=JSON.stringify(draftBody());
          popResolve({status:'queued'});await drain();
          assert(editor===current);assert.equal(JSON.stringify(draftBody()),later);
          const notice=current.dom.afterSavePopularNotice;
          assert(notice.text.textContent.includes('Popular-decks test requested for the saved list (20 opponents). Its Testing tab shows progress.'));
          assert(!notice.link.hidden);assert(notice.link.getAttribute('href').endsWith('&tab=matchups&part=gauntlet'));
          assert.equal(writes.length,2);
          // Remembered for this profile on this device: the saved deck's editor offers it ticked again.
          assert.equal(store.get(STORE+`editor.testPopular.${profile}`),'1');
          assert(current.dom.forgeSummary.popular.checked);
        ''')

    def test_both_choices_send_two_runs_and_one_notice_with_two_lines(self):
        self.run_js(r'''
          const ed=await readyPopular({},{field:true});await doSave(null,ed.dom.barParts.save);const current=editor;
          same(writes.map(w=>w.path).sort(),['/api/deck/save','/api/field/run','/api/gauntlet/run']);
          runResolve({status:'queued'});popResolve({status:'queued'});await drain();
          const text=current.dom.banners.textContent;
          assert(text.includes('Field re-test requested'));assert(text.includes('Popular-decks test requested'));
          assert.equal(current.dom.banners.querySelectorAll('h2').length,1);
        ''')

    def test_popular_refusals_keep_the_save_say_why_link_testing_and_never_retry(self):
        self.run_js(r'''
          for(const status of [0,403,409,503]) {
            const ed=await readyPopular();await doSave(null,ed.dom.barParts.save);const current=editor;
            setQty(current.lists.Deck[0].uid,7);const later=JSON.stringify(draftBody()),count=writes.length;
            popReject(new ApiError(status,'Fixture popular refusal.'));await drain();
            assert(editor===current);assert.equal(current.sha256,newSha);assert.equal(JSON.stringify(draftBody()),later);
            const text=current.dom.banners.textContent;assert(text.includes('The deck was saved'));
            if(status===0)assert(text.includes("couldn't be confirmed. Check its Testing tab before starting another run."));
            else assert(text.includes("its popular-decks test wasn't started. Fixture popular refusal."));
            assert(current.dom.afterSavePopularNotice.link.getAttribute('href').endsWith('&part=gauntlet'));
            assert(current.dom.afterSavePopularNotice.root.classList.contains('box-warn'));assert.equal(writes.length,count);
          }
        ''')

    def test_a_pause_before_saving_sends_no_run_and_says_why(self):
        self.run_js(r'''
          const ed=await readyPopular();state.simulations={may_start:false,why_not:'Simulations are paused.'};
          await doSave(null,ed.dom.barParts.save);await drain();
          same(writes.map(w=>w.path),['/api/deck/save']);
          assert(editor.dom.banners.textContent.includes("its popular-decks test wasn't started. Simulations are paused."));
          const again=await readyPopular();renderSimulations({may_start:false,why_not:'Only an admin can start simulations right now.'});
          const context=again.dom.forgeSummary;assert(context.popular.input.disabled&&!context.reason.hidden);
          renderSimulations({may_start:true});delete saveAnswer.deck.forge_lists;
          await doSave(null,again.dom.barParts.save);await drain();
          assert(editor.dom.banners.textContent.includes("its list couldn't be confirmed for testing. Start it from its Testing tab."));
        ''')

    def test_popular_choice_is_hidden_without_a_catalogue_or_off_the_saved_planned_full_editor(self):
        self.run_js(r'''
          catalogue={built:null};state.simulations={may_start:true};
          let ed=full({forge_lists:{target:oldSha,owned:oldSha}});setQty(ed.lists.Deck[0].uid,5);await drain();
          assert(ed.dom.forgeSummary.popular.choice.hidden);assert(!editorRetestIntent(ed));
          catalogue={built:'x',standard:null};ed=full({forge_lists:{target:oldSha,owned:oldSha}});
          setQty(ed.lists.Deck[0].uid,5);await drain();assert(ed.dom.forgeSummary.popular.choice.hidden);
          // Looking at a saved deck without changing it reads no catalogue.
          const reads=catalogueReads.length;full({forge_lists:{target:oldSha,owned:oldSha}});await drain();
          assert.equal(catalogueReads.length,reads);
          startEditor({mode:'edit',view:view({forge_lists:{target:oldSha,owned:oldSha}}),version:'owned',restoreDraft:false});
          assert(editor.dom.forgeSummary&&!editor.dom.forgeSummary.popular);
          startEditor({mode:'new',kind:'casual',restoreDraft:false});assert(!editor.dom.forgeSummary);
        ''')

    def test_commander_is_offered_against_its_own_catalogue(self):
        self.run_js(r'''
          const ed=await readyPopular({kind:'commander'});
          same(catalogueReads,['/api/gauntlet/catalogue?format=commander']);
          await doSave(null,ed.dom.barParts.save);
          same(writes.map(w=>w.path),['/api/deck/save','/api/gauntlet/run']);
        ''')

    def test_the_remembered_tick_belongs_to_one_profile_and_stays_outside_the_draft(self):
        self.run_js(r'''
          state.profile=state.profiles[1];const ed=await readyPopular();
          assert(!JSON.stringify(draftBody()).includes('opular'));assert(!snapshot(ed).includes('opular'));
          state.profile=state.profiles[0];const other=full({forge_lists:{target:oldSha,owned:oldSha}});
          setQty(other.lists.Deck[0].uid,5);await drain();const popular=other.dom.forgeSummary.popular;
          assert(!popular.checked&&!popular.input.checked);
          popular.input.checked=true;popular.input.fire('change');popular.input.checked=false;popular.input.fire('change');
          assert.equal(store.get(STORE+`editor.testPopular.${state.profiles[0].id}`),'0');
          assert.equal(store.get(STORE+`editor.testPopular.${state.profiles[1].id}`),'1');
        ''')

    def test_save_and_view_box_shows_the_popular_line_with_its_link(self):
        self.run_js(r'''
          const ed=await readyPopular();await doSave(null,ed.dom.barParts.save,{viewAfter:true});
          location.hash=state.saved.hash;const box=savedBox(ed.id);main.append(box);
          assert(box.textContent.includes('Starting its popular-decks test'));
          assert([...box.querySelectorAll('a')].some(a=>a.getAttribute('href').endsWith('&tab=matchups&part=gauntlet')));
          popResolve({status:'queued'});await drain();assert(box.textContent.includes('Popular-decks test requested'));
          state.profile=state.profiles[0];assert.equal(savedBox(ed.id),null);
        ''')
