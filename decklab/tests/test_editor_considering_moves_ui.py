"""Considering promotions validate and change both draft lists as one operation.

Uses the real page scripts with frozen cards, local storage and controlled API
promises. No browser, server, database or Forge runtime is involved.
"""
import json
import subprocess
import unittest

from decklab.tests import test_editor_considering_ui as considering
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = considering.SETUP + r"""
  const moveRows = [candidates[0],candidates[1],
    {qty:3,name:elves.name,set:'fdn',number:'227',category:'Ramp',card:elves}];
  const movedPlanned = ed => ed.version==='target' ? ed.lists : ed.planned;
  const plannedPlain = ed => sendList(movedPlanned(ed) || {});
  const settleMoves = async () => {for(let pass=0;pass<8;pass++)await Promise.resolve();};
  function beginMove(extra={},opts={},isQuick=true,rows=moveRows) {
    return openConsidering(extra,opts,isQuick,rows);
  }
  function moveControl(ed,index=0,section='Deck') {
    const uid=ed.considering[index].uid;
    const row=main.querySelector(`.editor-considering-row[data-considering-uid="${uid}"]`);assert(row);
    const control=row.querySelector(section==='Deck'?'.editor-considering-move-main':'.editor-considering-move-side');
    assert(control,`Move to ${section} control`);return control;
  }
  function cardFor(name) {return [elves,forest,bolt].find(card=>card.name.toLowerCase()===name.toLowerCase())||null;}
  function checkedSections(sections) {
    return Object.fromEntries(Object.entries(sections||{}).map(([section,lines])=>
      [section,lines.map(line=>({...line,card:cardFor(line.name)}))]));
  }
  function checkedMove(body,extra={}) {
    return consideringCheck({changes:{decklist:true,categories:false,considering:true,fields:[],prose:[],marker:false},
      lists:{target:checkedSections(body.lists?.target),considering:(body.lists?.considering||[])
        .map(line=>({...line,card:cardFor(line.name)}))},...extra});
  }
  function acceptMoveChecks(calls=[]) {
    apiWrite=async(path,body)=>{calls.push([path,body]);assert.equal(path,'/api/deck/check');return checkedMove(body);};
    return calls;
  }
  const exactCopies = (sections,line) => Object.values(sections||{}).flat()
    .filter(other=>lineKey(other)===lineKey(line)&&(other.category||'')===(line.category||''))
    .reduce((total,other)=>total+other.qty,0);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class EditorConsideringMovesUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run(
            [NODE, str(RUNNER)],
            input=json.dumps([str(WEB), SETUP + scenario, True,
                              {"innerWidth": 393, "innerHeight": 852, "coarse": True,
                               "visual": {"width": 393, "height": 852}}]),
            capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_moves_whole_exact_source_into_planned_or_sideboard_in_both_densities(self):
        self.run_js(r"""
          for(const isQuick of [true,false])for(const section of ['Deck','Sideboard']) {
            const ed=beginMove({}, {}, isQuick),original=structuredClone(ed.view.lists),source=sendLine(ed.considering[0]);
            const before=exactCopies(ed.lists,source),calls=acceptMoveChecks(),owned=structuredClone(ed.view.lists.owned);
            const remainingUids=ed.considering.slice(1).map(line=>line.uid);
            moveControl(ed,0,section).click();await settleMoves();
            assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/deck/check');
            assert.equal(exactCopies(ed.lists,source),before+source.qty);
            const destination=ed.lists[section].find(line=>lineKey(line)===lineKey(source)&&line.category===source.category);
            same(sendLine(destination),source);
            same(plainConsidering(ed),moveRows.slice(1).map(sendLine));assert.equal(ed.history.length,1);
            same(ed.considering.map(line=>line.uid),remainingUids);
            same(ed.view.lists,original);same(ed.view.lists.owned,owned);
            same(calls[0][1].lists,{target:sendList(ed.lists),considering:plainConsidering(ed)});
            assert.equal(calls[0][1].lists.owned,undefined);assert.equal(ed.starting,false);
          }
        """)

    def test_preflight_does_not_mutate_either_list_until_the_check_succeeds(self):
        self.run_js(r"""
          const ed=beginMove(),before=snapshot(ed),calls=[];let resolve;
          apiWrite=(path,body)=>{calls.push([path,body]);return new Promise(done=>{resolve=done;});};
          const move=moveControl(ed);move.click();assert.equal(calls.length,1);
          assert.equal(snapshot(ed),before);assert.equal(ed.history.length,0);
          const proposed=calls[0][1];assert.equal(proposed.lists.considering.length,moveRows.length-1);
          assert.equal(exactCopies(proposed.lists.target,moveRows[0]),moveRows[0].qty);
          move.click();assert.equal(calls.length,1);
          resolve(checkedMove(proposed));await settleMoves();
          assert.equal(ed.history.length,1);assert.equal(ed.considering.length,moveRows.length-1);
        """)

    def test_matching_group_can_reach_99_and_keeps_other_categories_and_printings(self):
        self.run_js(r"""
          const source=moveRows[0],differentCategory={...source,qty:4,category:'Other purpose'};
          const differentPrinting={...source,qty:5,set:'m10',number:'146',finish:'nonfoil'};
          const ed=beginMove({lists:{target:{Deck:[{...source,qty:97},differentCategory,differentPrinting]},
            owned:structuredClone(list)}},{},true,[source]);
          const calls=acceptMoveChecks();moveControl(ed).click();await settleMoves();
          assert.equal(calls.length,1);assert.equal(exactCopies(ed.lists,source),99);
          assert.equal(exactCopies(ed.lists,differentCategory),4);
          assert.equal(exactCopies(ed.lists,differentPrinting),5);
          same(ed.considering,[]);assert.equal(ed.history.length,1);
        """)

    def test_unknown_or_other_blocked_move_keeps_source_and_playable_lists_intact(self):
        self.run_js(r"""
          const unknown={qty:2,name:'A new unknown candidate',category:'Try later',card:null};
          const ed=beginMove({}, {}, true, [unknown]),before=snapshot(ed),calls=[];
          apiWrite=async(path,body)=>{calls.push([path,body]);return checkedMove(body,
            {blocks:[{list:'target',section:'Deck',index:2,problem:'Unknown new card'}]});};
          moveControl(ed).click();await settleMoves();
          assert.equal(calls.length,1);assert.equal(snapshot(ed),before);
          same(plainConsidering(ed),[sendLine(unknown)]);assert.equal(ed.history.length,0);assert(!isDirty());
        """)

    def test_preflight_cannot_merge_categories_change_supplied_printing_or_drop_copies(self):
        self.run_js(r"""
          const source=moveRows[0],existing={...source,qty:1,category:'Other purpose'};
          for(const alter of [
            answer=>{answer.lists.target.Deck=[{...existing,qty:3,card:bolt}];},
            answer=>{answer.lists.target.Deck.at(-1).finish='etched';},
            answer=>{answer.lists.target.Deck.at(-1).set='m10';},
            answer=>{answer.lists.target.Deck.at(-1).qty=1;}]) {
            const ed=beginMove({lists:{target:{Deck:[existing]},owned:structuredClone(list)}},{},true,[source]);
            const before=snapshot(ed);let calls=0;
            apiWrite=async(path,body)=>{calls++;const answer=checkedMove(body);alter(answer);return answer;};
            moveControl(ed).click();await settleMoves();
            assert.equal(calls,1);assert.equal(snapshot(ed),before);assert.equal(ed.history.length,0);
            same(plainConsidering(ed),[sendLine(source)]);assert(!isDirty());
          }
        """)

    def test_failed_or_stale_preflight_keeps_both_drafts_and_records_no_history(self):
        self.run_js(r"""
          for(const failure of ['offline','stale']) {
            const ed=beginMove(),before=snapshot(ed);let calls=0;
            apiWrite=async(path,body)=>{calls++;if(failure==='offline')throw new ApiError(503,'Fixture unavailable');
              return checkedMove(body,{file_changed:true});};
            moveControl(ed).click();await settleMoves();
            assert.equal(calls,1);assert.equal(snapshot(ed),before);assert.equal(ed.history.length,0);
          }
        """)

    def test_invalid_source_quantity_is_refused_before_preflight(self):
        self.run_js(r"""
          for(const qty of [100,0,1.5]) {
            const ed=beginMove({}, {}, true, [{...moveRows[0],qty}]);
            const before=snapshot(ed);let calls=0;apiWrite=async()=>{calls++;throw new Error('Invalid source must be local');};
            moveControl(ed).click();await settleMoves();
            assert.equal(calls,0);assert.equal(snapshot(ed),before);assert.equal(ed.history.length,0);
          }
        """)

    def test_known_saved_99_copy_line_accepts_a_separate_one_copy_line_without_clamping(self):
        self.run_js(r"""
          const source={...moveRows[0],qty:1},existing={...source,qty:99};
          const ed=beginMove({lists:{target:{Deck:[existing]},owned:structuredClone(list)}},{},true,[source]);
          const calls=acceptMoveChecks();moveControl(ed).click();await settleMoves();
          assert.equal(calls.length,1);same(ed.lists.Deck.map(sendLine),[sendLine(existing),sendLine(source)]);
          assert.equal(exactCopies(ed.lists,source),100);same(ed.considering,[]);assert.equal(ed.history.length,1);
        """)

    def test_new_printing_duplicate_overflow_is_preflighted_without_losing_the_second_source(self):
        self.run_js(r"""
          const source={...moveRows[0],qty:60},ed=beginMove({}, {}, true, [source,{...source}]),calls=[];
          apiWrite=async(path,body)=>{calls.push([path,body]);return checkedMove(body,
            exactCopies(body.lists.target,source)>99
              ?{blocks:[{list:'target',section:'Deck',index:2,problem:'New printing exceeds 99 copies'}]}:{});};
          moveControl(ed).click();await settleMoves();assert.equal(ed.considering.length,1);
          const before=snapshot(ed);assert.equal(ed.history.length,1);
          moveControl(ed).click();await settleMoves();
          assert.equal(calls.length,2);assert.equal(exactCopies(calls[1][1].lists.target,source),120);
          assert.equal(snapshot(ed),before);assert.equal(ed.history.length,1);
          same(plainConsidering(ed),[sendLine(source)]);assert.equal(exactCopies(ed.lists,source),60);
        """)

    def test_success_is_one_undo_step_and_restores_both_lists_and_move_tracking(self):
        self.run_js(r"""
          const ed=beginMove(),planned=sendList(ed.lists),alternatives=plainConsidering(ed),calls=acceptMoveChecks();
          moveControl(ed,0,'Sideboard').click();await settleMoves();
          assert.equal(calls.length,1);assert.equal(ed.history.length,1);assert(ed.consideringMoves?.length);
          assert(undoLast());same(sendList(ed.lists),planned);same(plainConsidering(ed),alternatives);
          assert(!ed.consideringMoves?.length);assert.equal(ed.history.length,0);assert(!isDirty());
          assert.equal(draftBody().lists,undefined);
        """)

    def test_draft_resume_preserves_the_paired_move_and_tracking(self):
        self.run_js(r"""
          const ed=beginMove(),calls=acceptMoveChecks();moveControl(ed).click();await settleMoves();
          const target=sendList(ed.lists),alternatives=plainConsidering(ed),moves=structuredClone(ed.consideringMoves);
          assert(saveDraft(ed));const stored=JSON.parse(local.get(draftKey(ed)));
          same(stored.consideringMoves,moves);same(stored.considering.map(sendLine),alternatives);
          startEditor({mode:'edit',view:consideringView({},moveRows),version:'target'});
          same(sendList(editor.lists),target);same(plainConsidering(editor),alternatives);
          same(editor.consideringMoves,moves);assert(isDirty());
          same(draftBody().lists,{target,considering:alternatives});
          assert.equal(calls.length,1);
        """)

    def test_owned_and_unstarted_owned_move_to_separate_planned_without_starting_play_now(self):
        self.run_js(r"""
          for(const isQuick of [true,false])for(const owned of [structuredClone(list),null]) {
            const ed=beginMove({lists:{target:structuredClone(list),owned}},{version:'owned'},isQuick);
            const own=sendList(ed.lists),calls=acceptMoveChecks();moveControl(ed,0,'Sideboard').click();await settleMoves();
            same(sendList(ed.lists),own);assert.equal(ed.starting,false);assert.equal(ed.hasFileList,owned!==null);
            assert(ed.planned&&ed.planned!==ed.lists);assert(ed.base.planned);
            assert.equal(exactCopies(ed.planned,moveRows[0]),moveRows[0].qty);
            same(ed.view.lists.target,list);assert.equal(calls.length,1);
            same(draftBody().lists,{target:sendList(ed.planned),considering:plainConsidering(ed)});
            assert.equal(draftBody().lists.owned,undefined);
            if(owned===null){assert(noOwnedList());assert(!ed.dom.barParts.save.disabled);}
          }
        """)

    def test_owned_move_undo_and_draft_resume_preserve_planned_and_play_now_separately(self):
        self.run_js(r"""
          const extra={lists:{target:structuredClone(list),owned:null}},ed=beginMove(extra,{version:'owned'});
          const own=sendList(ed.lists);acceptMoveChecks();moveControl(ed).click();await settleMoves();
          assert(undoLast());assert.equal(draftBody().lists,undefined);same(sendList(ed.lists),own);
          same(plainConsidering(ed),moveRows.map(sendLine));assert(!isDirty());assert(noOwnedList());
          moveControl(ed,0,'Sideboard').click();await settleMoves();const target=sendList(ed.planned),alternatives=plainConsidering(ed);
          assert(saveDraft(ed));const storedDraft=JSON.parse(local.get(draftKey(ed)));
          same(sendList(storedDraft.planned),target);same(sendList(storedDraft.base.planned),sendList(list));
          startEditor({mode:'edit',view:consideringView(extra,moveRows),version:'owned'});
          same(sendList(editor.lists),own);same(sendList(editor.planned),target);same(plainConsidering(editor),alternatives);
          same(draftBody().lists,{target,considering:alternatives});assert(noOwnedList());
          assert.equal(editor.starting,false);assert.equal(editor.hasFileList,false);
        """)

    def test_missing_pair_capability_roundtrip_preserves_private_draft_then_recovers_with_review(self):
        self.run_js(r"""
          for(const missing of ['target','considering','both']) {
            const ed=beginMove({lists:{target:structuredClone(list),owned:null}},{version:'owned'});
            acceptMoveChecks();moveControl(ed).click();await settleMoves();
            const target=sendList(ed.planned),alternatives=plainConsidering(ed),moves=structuredClone(ed.consideringMoves);
            assert(saveDraft(ed));const key=draftKey(ed);
            const unavailable=view({sha256:'b'.repeat(64),lists:{
              target:missing==='considering'?structuredClone(list):null,owned:null,
              ...(missing==='target'?{considering:structuredClone(moveRows)}:{})}});
            api=async()=>unavailable;await reapplyLatest(null,{message:'Fixture optional lists unavailable'},null);
            assert(editor.promotionUnavailable);assert(isDirty());
            assert(editor.notice.notes.some(note=>note.includes('linked Planned and Considering move')));
            let writes=0;apiWrite=async()=>{writes++;throw new Error('Unavailable pair must remain private');};
            for(let pass=0;pass<2;pass++) {
              same(sendList(editor.planned),target);same(plainConsidering(editor),alternatives);
              same(editor.consideringMoves,moves);assert(editor.promotionUnavailable);assert(isDirty());
              assert(main.textContent.includes('kept on this device'));assert(saveDraft(editor));
              const stored=JSON.parse(local.get(key));same(sendList(stored.planned),target);
              same(stored.considering.map(sendLine),alternatives);same(stored.consideringMoves,moves);
              assert(stored.promotionUnavailable);await saveNow();assert.equal(writes,0);
              startEditor({mode:'edit',view:structuredClone(unavailable),version:'owned'});
            }
            assert(saveDraft(editor));
            startEditor({mode:'edit',view:consideringView({sha256:'b'.repeat(64),
              lists:{target:structuredClone(list),owned:null}},moveRows),version:'owned'});
            same(sendList(editor.planned),target);same(plainConsidering(editor),alternatives);
            same(editor.consideringMoves,moves);assert(!editor.promotionUnavailable);assert(!editor.consideringUnavailable);
            assert(editor.promotionReview);assert(editorPromotionReviewNeeded(editor));assert(isDirty());
            await doSave(null,editor.dom.barParts.save);assert.equal(writes,0);
            const review=openSheet('Recovered complete pair');drawReview(review,checkedMove(draftBody()));
            const ack=review.body.querySelector('.editor-promotion-ack');assert(ack&&!ack.checked);
            assert(review.foot.querySelector('[data-action="save"]').disabled);
            ack.checked=true;ack.fire('change');assert(!editorPromotionReviewNeeded(editor));review.close();
            assert(saveDraft(editor));
            api=async()=>consideringView({sha256:'c'.repeat(64),lists:{target:checkedSections(target),owned:null}},
              editor.considering);
            await reapplyLatest(null,{message:'Fixture pair already applied'},null);
            same(sendList(editor.planned),target);same(plainConsidering(editor),alternatives);
            assert(!editor.promotionUnavailable);assert(!editor.consideringUnavailable);assert(!editor.promotionReview);
            assert(!editor.consideringMoves.length);assert(!isDirty());assert.equal(draftBody().lists,undefined);
            assert(noOwnedList());assert.equal(editor.starting,false);assert.equal(local.get(key),null);
            same(editor.notice.notes,[]);assert.equal(writes,0);
          }
        """)

    def test_added_local_alternative_can_leave_only_hidden_planned_dirty_and_save_enabled(self):
        self.run_js(r"""
          const ed=beginMove({lists:{target:structuredClone(list),owned:null}},{version:'owned'},true,[]);
          addLocal(elves.name,2);acceptMoveChecks();moveControl(ed).click();await settleMoves();
          same(ed.considering,[]);assert(!editorConsideringChanged(ed));assert(editorPromotionChanged(ed));
          assert(isDirty());assert(noOwnedList());assert.equal(ed.dom.barParts.changeCount.textContent,'Unsaved Planned changes');
          assert(!ed.dom.barParts.save.disabled);const target=sendList(ed.planned);
          same(draftBody().lists,{target});assert.equal(ed.starting,false);assert.equal(ed.hasFileList,false);
          const calls=[];apiWrite=async(path,body)=>{calls.push([path,body]);
            assert.equal(body.lists.considering,undefined);assert.equal(body.lists.owned,undefined);
            if(path==='/api/deck/check')return checkedMove({...body,lists:{...body.lists,considering:[]}},
              {changes:{decklist:true,categories:false,considering:false,fields:[],prose:[],marker:false}});
            return {id:ed.id,title:ed.title,changed:true,
              deck:consideringView({sha256:'b'.repeat(64),lists:{target:checkedSections(target),owned:null}},[])};};
          await saveNow();same(calls.map(([path])=>path),['/api/deck/check','/api/deck/save']);
          for(const [,body]of calls)same(body.lists,{target});
          assert(editor!==ed);assert(!isDirty());assert(noOwnedList());assert.equal(editor.view.lists.owned,null);
        """)

    def test_read_only_and_absent_api_have_no_move_controls_or_requests(self):
        self.run_js(r"""
          let calls=0;apiWrite=async()=>{calls++;throw new Error('No allowed move');};
          beginMove({may_save:false});assert(!main.querySelector('.editor-considering-move-main'));
          assert(!main.querySelector('.editor-considering-move-side'));
          startEditor({mode:'edit',view:view(),version:'target',restoreDraft:false});
          assert(!main.querySelector('.editor-considering-move-main'));assert.equal(calls,0);
        """)

    def test_target_validation_from_owned_editor_marks_only_the_separate_planned_rows(self):
        self.run_js(r"""
          const ed=beginMove({}, {version:'owned'}),own=sendList(ed.lists);acceptMoveChecks();
          moveControl(ed).click();await settleMoves();
          apiWrite=async(path,body)=>checkedMove(body,{blocks:[{list:'target',section:'Deck',index:0,
            problem:'Fixture Planned-only problem'}]});
          await runCheck(ed);
          const planned=ed.dom.considering.querySelector(`[data-planned-uid="${ed.planned.Deck[0].uid}"]`);
          assert(planned);assert(planned.querySelector('.edit-block').textContent.includes('Fixture Planned-only problem'));
          assert.equal(ed.dom.lines.querySelector('.edit-block'),null);
          assert.equal(ed.dom.lines.querySelector('.is-blocked'),null);same(sendList(ed.lists),own);
          assert.equal(ed.starting,false);
        """)

    def test_late_preflight_cannot_promote_after_owner_or_proposal_changes(self):
        self.run_js(r"""
          for(const invalidate of [ed=>{state.profile=state.profiles[0];},ed=>{routeToken++;},
            ed=>{ed.readOnly=true;},ed=>{drawEditorConsidering();},ed=>{ed.considering[0].qty=7;},
            ed=>{beginMove();}]) {
            state.profile=state.profiles[1];const ed=beginMove();let resolve,body;
            apiWrite=(path,sent)=>{body=sent;return new Promise(done=>{resolve=done;});};
            moveControl(ed).click();invalidate(ed);const after=snapshot(ed),history=ed.history.length;
            resolve(checkedMove(body));await settleMoves();
            assert.equal(snapshot(ed),after);assert.equal(ed.history.length,history);
            assert.equal(ed.considering.length,moveRows.length);
          }
        """)

    def test_pending_preflight_refuses_a_changed_sha_or_a_new_modal_without_mutation(self):
        self.run_js(r"""
          for(const change of ['sha','modal']) {
            const ed=beginMove(),before=snapshot(ed);let resolve,body,sheet=null,calls=0;
            apiWrite=(path,sent)=>{calls++;body=sent;return new Promise(done=>{resolve=done;});};
            moveControl(ed).click();assert.equal(calls,1);
            if(change==='sha')ed.sha256='b'.repeat(64);else sheet=openSheet('Another local action');
            resolve(checkedMove(body));await settleMoves();
            assert.equal(snapshot(ed),before);assert.equal(ed.history.length,0);assert.equal(calls,1);
            same(plainConsidering(ed),moveRows.map(sendLine));assert(!ed.promoting);
            if(sheet){assert(sheet.dialog.isConnected);sheet.close();}else assert.equal(ed.sha256,'b'.repeat(64));
          }
        """)

    def test_successful_move_hydrates_only_missing_card_metadata_from_the_checked_name(self):
        self.run_js(r"""
          const source={...moveRows[0],name:'lightning bolt',card:null},ed=beginMove({}, {}, true, [source]);
          const original=structuredClone(ed.view.lists.considering);
          apiWrite=async(path,body)=>{const answer=checkedMove(body),checked=answer.lists.target.Deck.at(-1);
            checked.name=bolt.name;checked.card=bolt;return answer;};
          moveControl(ed).click();await settleMoves();
          const promoted=ed.lists.Deck.at(-1);same(sendLine(promoted),{...sendLine(source),name:bolt.name});
          assert.equal(promoted.card.name,bolt.name);same(ed.considering,[]);
          same(ed.view.lists.considering,original);assert.equal(ed.history.length,1);
        """)

    def test_moved_pair_is_sent_in_one_normal_check_and_save(self):
        self.run_js(r"""
          const ed=beginMove(),requests=acceptMoveChecks();moveControl(ed).click();await settleMoves();
          const paired={target:sendList(ed.lists),considering:plainConsidering(ed)};
          apiWrite=async(path,body)=>{requests.push([path,body]);
            if(path==='/api/deck/check')return checkedMove(body);
            assert.equal(path,'/api/deck/save');return {id:ed.id,title:ed.title,changed:true,
              deck:consideringView({sha256:'b'.repeat(64),lists:{target:checkedSections(paired.target),owned:structuredClone(list)}},
                ed.considering)};};
          await saveNow();
          same(requests.map(([path])=>path),['/api/deck/check','/api/deck/check','/api/deck/save']);
          for(const [,body]of requests)same(body.lists,paired);
          assert(editor!==ed);assert(!isDirty());same(sendList(editor.lists),paired.target);
          same(plainConsidering(editor),paired.considering);
        """)

    def test_checked_default_printing_is_pinned_before_later_inventory_defaults_change(self):
        self.run_js(r"""
          const source={qty:2,name:bolt.name,category:'Try first',card:null},ed=beginMove({}, {}, true, [source]);
          const original=structuredClone(ed.view.lists.considering),requests=[];
          let defaultPrinting={set:'m11',number:'146',finish:'nonfoil'};
          apiWrite=async(path,body)=>{requests.push([path,body]);
            if(requests.length>1){
              const sent=body.lists.target.Deck.find(line=>line.name===bolt.name);
              assert.equal(sent.set,'m11');assert.equal(sent.number,'146');assert.equal(sent.finish||'nonfoil','nonfoil');
            }
            if(path==='/api/deck/check'){
              const answer=checkedMove(body);
              for(const line of answer.lists.target.Deck)if(line.name===bolt.name&&!line.set)
                Object.assign(line,defaultPrinting,{card:bolt});
              return answer;
            }
            assert.equal(path,'/api/deck/save');return {id:ed.id,title:ed.title,changed:true,
              deck:consideringView({sha256:'b'.repeat(64),lists:{target:checkedSections(body.lists.target),owned:structuredClone(list)}},[])};
          };
          moveControl(ed).click();await settleMoves();
          assert.equal(requests[0][1].lists.target.Deck.at(-1).set,undefined);
          const moved=ed.lists.Deck.find(line=>line.name===bolt.name);
          assert.equal(moved.set,'m11');assert.equal(moved.number,'146');assert.equal(moved.finish,'nonfoil');
          defaultPrinting={set:'m10',number:'146',finish:'foil'};await saveNow();
          same(requests.map(([path])=>path),['/api/deck/check','/api/deck/check','/api/deck/save']);
          const savedLine=editor.lists.Deck.find(line=>line.name===bolt.name);
          assert.equal(savedLine.set,'m11');assert.equal(savedLine.number,'146');assert.equal(savedLine.finish,'nonfoil');
          assert.equal(savedLine.category,'Try first');assert.equal(savedLine.qty,2);
          same(ed.view.lists.considering,original);assert(!isDirty());
        """)

    def test_unstarted_play_now_can_save_the_paired_move_without_creating_owned(self):
        self.run_js(r"""
          const ed=beginMove({lists:{target:structuredClone(list),owned:null}},{version:'owned'});
          acceptMoveChecks();moveControl(ed,0,'Sideboard').click();await settleMoves();
          const target=sendList(ed.planned),alternatives=plainConsidering(ed),calls=[];
          apiWrite=async(path,body)=>{calls.push([path,body]);assert.equal(body.lists.owned,undefined);
            if(path==='/api/deck/check')return checkedMove(body);
            return {id:ed.id,title:ed.title,changed:true,
              deck:consideringView({sha256:'b'.repeat(64),lists:{target:checkedSections(target),owned:null}},ed.considering)};};
          await saveNow();same(calls.map(([path])=>path),['/api/deck/check','/api/deck/save']);
          for(const [,body]of calls)same(body.lists,{target,considering:alternatives});
          assert(editor!==ed);assert.equal(editor.version,'owned');assert(noOwnedList());
          assert.equal(editor.starting,false);assert.equal(editor.hasFileList,false);assert(!isDirty());
        """)

    def test_rebase_against_unchanged_pair_keeps_move_once_without_additive_reapplication(self):
        self.run_js(r"""
          const ed=beginMove();acceptMoveChecks();moveControl(ed).click();await settleMoves();
          const target=sendList(ed.lists),alternatives=plainConsidering(ed);
          api=async()=>consideringView({sha256:'b'.repeat(64)},moveRows);
          await reapplyLatest(null,{message:'Fixture conflict'},null);
          same(sendList(ed.lists),target);same(plainConsidering(ed),alternatives);
          assert(!ed.promotionReview);assert.equal(exactCopies(ed.lists,moveRows[0]),moveRows[0].qty);
          same(draftBody().lists,{target,considering:alternatives});
        """)

    def test_rebase_already_saved_pair_adopts_clean_and_never_promotes_twice(self):
        self.run_js(r"""
          const ed=beginMove();acceptMoveChecks();moveControl(ed).click();await settleMoves();
          const target=sendList(ed.lists),alternatives=plainConsidering(ed);
          api=async()=>consideringView({sha256:'b'.repeat(64),lists:{target:checkedSections(target),owned:structuredClone(list)}},
            ed.considering);
          await reapplyLatest(null,{message:'Fixture already saved'},null);
          same(sendList(ed.lists),target);same(plainConsidering(ed),alternatives);
          assert(!isDirty());assert(!ed.promotionReview);assert.equal(draftBody().lists,undefined);
          same(ed.notice.notes,[]);
          assert.equal(exactCopies(ed.lists,moveRows[0]),moveRows[0].qty);
        """)

    def test_already_saved_canonical_default_printing_pair_adopts_clean_without_double_add(self):
        self.run_js(r"""
          const source={qty:2,name:'lightning bolt',category:'Try first',card:bolt},ed=beginMove({}, {}, true, [source]);
          let normalized;
          apiWrite=async(path,body)=>{const answer=checkedMove(body),line=answer.lists.target.Deck.at(-1);
            Object.assign(line,{name:bolt.name,set:'m11',number:'146',finish:'nonfoil',card:bolt});
            normalized=structuredClone(answer.lists.target);return answer;};
          moveControl(ed).click();await settleMoves();assert(ed.promotionAccepted);
          const local=ed.lists.Deck.at(-1);assert.equal(local.name,bolt.name);assert.equal(local.set,'m11');
          assert.equal(local.number,'146');assert.equal(local.finish,'nonfoil');assert.equal(local.category,'Try first');
          assert.equal(ed.view.lists.considering[0].name,'lightning bolt');
          assert.equal(ed.view.lists.considering[0].set,undefined);
          api=async()=>consideringView({sha256:'b'.repeat(64),lists:{target:normalized,owned:structuredClone(list)}},[]);
          await reapplyLatest(null,{message:'Fixture normalized pair already saved'},null);
          same(sendList(ed.lists),sendList(normalized));same(ed.considering,[]);assert(!isDirty());
          assert(!ed.promotionReview);assert(!ed.consideringMoves.length);assert.equal(draftBody().lists,undefined);
          same(ed.notice.notes,[]);
          assert.equal(exactCopies(ed.lists,{...source,name:bolt.name,set:'m11',number:'146',finish:'nonfoil'}),2);
        """)

    def test_already_applied_pair_rebase_preserves_independent_owned_field_and_prose_edits(self):
        self.run_js(r"""
          const ed=beginMove({}, {version:'owned'});setQty(ed.lists.Deck[0].uid,5);
          ed.fields.archetype='My archetype';ed.prose.notes='My independent notes';changed({list:false});
          acceptMoveChecks();moveControl(ed).click();await settleMoves();
          const target=sendList(ed.planned),alternatives=plainConsidering(ed),latestOwn=structuredClone(list);
          latestOwn.Deck[0].qty=6;
          api=async()=>consideringView({sha256:'b'.repeat(64),lists:{target:checkedSections(target),owned:latestOwn},
            fields:{...view().fields,archetype:'Their archetype'},
            prose:{notes:'Their independent notes',substitutes:'Existing substitutes.'}},ed.considering);
          await reapplyLatest(null,{message:'The linked move was saved elsewhere'},null);
          same(sendList(ed.planned),target);same(plainConsidering(ed),alternatives);
          assert(!ed.consideringMoves.length);assert(!editorPromotionChanged(ed));assert(!editorConsideringChanged(ed));
          assert(!ed.promotionReview);assert.equal(ed.lists.Deck[0].qty,7);
          assert.equal(ed.base.lists.Deck[0].qty,6);assert.equal(ed.fields.archetype,'My archetype');
          assert.equal(ed.prose.notes,'My independent notes');assert(isDirty());
          const body=draftBody();same(body.lists,{owned:sendList(ed.lists)});
          same(body.fields,{archetype:'My archetype'});same(body.prose,{notes:'My independent notes'});
          assert.equal(exactCopies(ed.planned,moveRows[0]),moveRows[0].qty);
        """)

    def test_divergent_pair_requires_explicit_review_before_the_atomic_save(self):
        self.run_js(r"""
          const ed=beginMove();acceptMoveChecks();moveControl(ed).click();await settleMoves();
          const target=sendList(ed.lists),alternatives=plainConsidering(ed);
          const theirs=structuredClone(list);theirs.Deck[0].qty=5;
          api=async()=>consideringView({sha256:'b'.repeat(64),lists:{target:theirs,owned:structuredClone(list)}},moveRows);
          await reapplyLatest(null,{message:'Fixture divergent move'},null);
          same(sendList(ed.lists),target);same(plainConsidering(ed),alternatives);assert(ed.promotionReview);
          const calls=[];apiWrite=async(path,body)=>{calls.push([path,body]);
            if(path==='/api/deck/check')return checkedMove(body);
            assert.equal(path,'/api/deck/save');return {id:ed.id,title:ed.title,changed:true,
              deck:consideringView({sha256:'c'.repeat(64),lists:{target:checkedSections(target),owned:structuredClone(list)}},
                ed.considering)};};
          await saveNow();const sheet=document.querySelector('dialog');assert(sheet);
          const acknowledgment=sheet.querySelector('.editor-promotion-ack'),save=sheet.querySelector('[data-action="save"]');
          assert(acknowledgment);assert(!acknowledgment.checked);assert(save.disabled);
          assert.equal(calls.filter(([path])=>path==='/api/deck/save').length,0);
          await doSave(null,ed.dom.barParts.save);assert.equal(calls.filter(([path])=>path==='/api/deck/save').length,0);
          acknowledgment.checked=true;acknowledgment.fire('change');assert(!save.disabled);
          save.click();await settleMoves();
          const saves=calls.filter(([path])=>path==='/api/deck/save');assert.equal(saves.length,1);
          same(saves[0][1].lists,{target,considering:alternatives});assert(!isDirty());
        """)

    def test_acknowledgment_is_invalidated_by_pair_changes_or_any_repeated_baseline_rebase(self):
        self.run_js(r"""
          for(const invalidate of ['pair','new-baseline','repeat-baseline']) {
            const ed=beginMove();acceptMoveChecks();moveControl(ed).click();await settleMoves();
            const theirs=structuredClone(list);theirs.Deck[0].qty=5;let sha='b'.repeat(64);
            api=async()=>consideringView({sha256:sha,lists:{target:theirs,owned:structuredClone(list)}},moveRows);
            await reapplyLatest(null,{message:'Fixture divergent pair'},null);assert(ed.promotionReview);
            const sheet=openSheet('Review the complete pair');drawReview(sheet,checkedMove(draftBody()));
            const checkbox=sheet.body.querySelector('.editor-promotion-ack');checkbox.checked=true;checkbox.fire('change');
            assert(!editorPromotionReviewNeeded(ed));sheet.close();
            if(invalidate==='pair')quantity(ed,0,7);
            else {if(invalidate==='new-baseline')sha='c'.repeat(64);
              await reapplyLatest(null,{message:'Fixture latest pair again'},null);}
            assert(editorPromotionReviewNeeded(ed));let writes=0;
            apiWrite=async()=>{writes++;throw new Error('An old acknowledgment cannot authorize this pair');};
            await doSave(null,ed.dom.barParts.save);assert.equal(writes,0);
            const review=openSheet('Review the changed pair');drawReview(review,checkedMove(draftBody()));
            const fresh=review.body.querySelector('.editor-promotion-ack');assert(!fresh.checked);
            assert(review.foot.querySelector('[data-action="save"]').disabled);
            checkbox.checked=true;checkbox.fire('change');assert(editorPromotionReviewNeeded(ed));
            assert(!fresh.checked);review.close();
          }
        """)

    def test_replaced_checkbox_in_same_review_sheet_cannot_acknowledge_or_enable_redrawn_save(self):
        self.run_js(r"""
          const ed=beginMove();acceptMoveChecks();moveControl(ed).click();await settleMoves();
          const theirs=structuredClone(list);theirs.Deck[0].qty=5;
          api=async()=>consideringView({sha256:'b'.repeat(64),lists:{target:theirs,owned:structuredClone(list)}},moveRows);
          await reapplyLatest(null,{message:'Fixture divergent linked pair'},null);assert(ed.promotionReview);
          for(const blocked of [false,true]) {
            const sheet=openSheet('The same complete linked review'),answer=checkedMove(draftBody());
            drawReview(sheet,answer);const old=sheet.body.querySelector('.editor-promotion-ack');
            assert(old&&!old.checked);assert(sheet.foot.querySelector('[data-action="save"]').disabled);
            const redrawn=blocked?{...answer,blocks:[{list:'target',section:'Deck',index:0,
              problem:'Newly discovered Planned problem'}]}:answer;
            drawReview(sheet,redrawn);const fresh=sheet.body.querySelector('.editor-promotion-ack');
            const save=sheet.foot.querySelector('[data-action="save"]');
            assert(fresh!==old);assert(!old.isConnected);assert(fresh.isConnected);assert(!fresh.checked);assert(save.disabled);
            old.checked=true;old.fire('change');
            assert(!ed.promotionAcknowledged);assert(editorPromotionReviewNeeded(ed));assert(!fresh.checked);assert(save.disabled);
            let writes=0;apiWrite=async()=>{writes++;throw new Error('A detached acknowledgment cannot save');};
            await doSave(sheet,save);assert.equal(writes,0);sheet.close();
          }
        """)

    def test_full_planned_review_explicitly_names_an_empty_replacement(self):
        self.run_js(r"""
          const ed=beginMove({}, {version:'owned'});acceptMoveChecks();moveControl(ed).click();await settleMoves();
          ed.planned={};ed.promotionReview=true;changed({list:false});const before=snapshot(ed);
          const sheet=openSheet('An empty full Planned draft');drawReview(sheet,checkedMove(draftBody()));
          assert(sheet.body.textContent.includes('Planned will be saved as:'));
          assert(sheet.body.textContent.includes('No cards: clears Planned.'));
          assert(sheet.body.querySelector('.editor-promotion-ack'));
          assert(sheet.foot.querySelector('[data-action="save"]').disabled);
          assert.equal(snapshot(ed),before);
        """)
