"""Saved-deck Considering stays outside playable lists through local editing and saves.

Runs the actual page scripts against disposable cards and the Node DOM double.
These interaction fixtures do not drive a browser, contact a server or run Forge.
"""
import json
import subprocess
import unittest

from decklab.tests import test_quick_editor_ui as quick
from decklab.tests import test_editor_panes_ui as panes
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = quick.SETUP + '\nchanged = ' + panes.REAL_CHANGED + r""";
  // Card arrays may originate in the runner's native structuredClone realm.
  same = (actual, expected) => assert.deepEqual(JSON.parse(JSON.stringify(actual)),JSON.parse(JSON.stringify(expected)));
  toast=()=>{};showToast=()=>{};
  const candidates = [
    {qty:2,name:bolt.name,set:'m11',number:'146',finish:'foil',category:'Try first',card:bolt},
    {qty:1,name:bolt.name,set:'m11',number:'146',finish:'foil',category:'Later',card:bolt},
    {qty:3,name:'Old unknown card',category:'Keep this note',card:null}];
  const plainConsidering = ed => (ed.considering || []).map(sendLine);
  function consideringView(extra = {}, rows = candidates) {
    const v = view(extra);
    v.lists = {...v.lists,considering:structuredClone(rows)};
    return v;
  }
  function openConsidering(extra = {}, opts = {}, isQuick = true, rows = candidates) {
    window.matchMedia('(min-width: 600px)').matches = !isQuick;
    startEditor({mode:'edit',view:consideringView(extra,rows),version:'target',restoreDraft:false,...opts});
    assert.equal(editor.quick,isQuick);
    return editor;
  }
  function quantity(ed, index, value) {
    const line = ed.considering[index];
    const field = main.querySelector(`.editor-considering-qty[data-considering-uid="${line.uid}"]`);
    assert(field,'Considering quantity field');
    field.value=String(value);field.fire('change');
    return field;
  }
  function mine(ed) {
    return {...JSON.parse(snapshot(ed)),considering:editorConsideringSnapshot(ed).considering};
  }
  function consideringCheck(extra = {}) {
    return {blocks:[],warnings:[],file_changed:false,
      changes:{decklist:false,categories:false,considering:true,fields:[],prose:[],marker:false},
      counts:{target:{main:60,sideboard:1}},...extra};
  }
  function addLocal(name, qty) {
    main.querySelector('.editor-considering-add').click();
    const sheet=document.querySelector('dialog');assert(sheet);
    const nameInput=sheet.querySelector('.editor-considering-name');
    const copiesInput=sheet.querySelector('.editor-considering-copies');
    assert(nameInput&&copiesInput);
    nameInput.value=name;nameInput.fire('input');
    copiesInput.value=String(qty);copiesInput.fire('input');
    const add=sheet.querySelector('[data-action="add"]');assert(add);add.click();
    return sheet;
  }
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class EditorConsideringUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run(
            [NODE, str(RUNNER)],
            input=json.dumps([str(WEB), SETUP + scenario, True,
                              {"innerWidth": 393, "innerHeight": 852, "coarse": True,
                               "visual": {"width": 393, "height": 852}}]),
            capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_initial_rows_are_independent_and_keep_printing_categories_and_unknowns(self):
        self.run_js(r"""
          const ed=openConsidering(),source=structuredClone(ed.view.lists.considering);
          same(plainConsidering(ed),source.map(sendLine));
          assert(ed.considering!==ed.view.lists.considering);
          assert(ed.considering!==ed.base.considering);
          assert(ed.considering[0]!==ed.base.considering[0]);
          assert(ed.considering[0].uid!==ed.considering[1].uid);
          assert.equal(ed.considering[2].card,null);
          assert.equal(editorConsideringChanged(ed),false);
          assert.equal(listChanged(),false);assert.equal(isDirty(),false);
          assert.equal(mainCount(ed.lists,'casual'),60);assert.equal(kitNeed(),61);
          assert.equal(ed.lists.Considering,undefined);
          assert.equal(draftBody().lists,undefined);
          quantity(ed,0,7);
          same(ed.view.lists.considering,source);
          same(ed.base.considering.map(sendLine),source.map(sendLine));
          assert.equal(mainCount(ed.lists,'casual'),60);assert.equal(kitNeed(),61);
          assert.equal(listChanged(),false);assert.equal(isDirty(),true);
        """)

    def test_exact_dirty_signature_retains_order_duplicates_printing_and_category(self):
        self.run_js(r"""
          for(const mutate of [
            rows=>{rows.reverse();},rows=>{rows[0].category='Different';},
            rows=>{rows[0].finish='etched';},rows=>{rows[0].number='147';},
            rows=>{rows[0].qty++;rows[1].qty--;},rows=>{rows.pop();}]) {
            const ed=openConsidering();mutate(ed.considering);
            assert(editorConsideringChanged(ed));assert(isDirty());assert(!listChanged());
            same(draftBody().lists.considering,plainConsidering(ed));
            assert.equal(draftBody().lists.target,undefined);
          }
        """)

    def test_local_add_change_and_remove_work_in_full_and_quick_without_a_request(self):
        self.run_js(r"""
          let requests=0;apiWrite=async()=>{requests++;throw new Error('No immediate write');};
          for(const isQuick of [true,false]) {
            const ed=openConsidering({}, {}, isQuick),playable=listSignature(ed.lists);
            assert(main.querySelector('.edit-considering'));
            assert.equal(main.querySelectorAll('.editor-considering-qty').length,3);
            assert(!main.querySelector('.editor-considering-promote'));
            const sheet=addLocal(elves.name,4);
            assert(!sheet.isConnected);
            same(plainConsidering(ed).at(-1),{qty:4,name:elves.name});
            quantity(ed,0,5);
            assert.equal(ed.considering[0].qty,5);
            main.querySelectorAll('.editor-considering-remove')[1].click();
            assert.equal(ed.considering.length,3);
            assert.equal(ed.considering[1].name,'Old unknown card');
            assert.equal(listSignature(ed.lists),playable);
            assert.equal(ed.starting,false);assert(ed.history.length>=3);
            same(draftBody().lists.considering,plainConsidering(ed));
          }
          assert.equal(requests,0);
        """)

    def test_missing_api_list_and_new_or_copy_editor_offer_no_considering_write(self):
        self.run_js(r"""
          for(const value of [undefined,null]) {
            const v=view();if(value!==undefined)v.lists.considering=value;
            startEditor({mode:'edit',view:v,version:'target',restoreDraft:false});
            assert(!main.querySelector('.editor-considering-add'));
            assert.equal(editorConsideringChanged(editor),false);
            assert.equal(draftBody().lists,undefined);
            restoreEditorConsidering(editor,{considering:[]});
            assert.equal(draftBody().lists,undefined);
          }
          for(const opts of [{mode:'new',kind:'casual'},
            {mode:'new',from:'casual/sample',view:consideringView({new_deck:{kind:'casual',title:'Copy'}})}]) {
            startEditor({...opts,restoreDraft:false});
            assert(!main.querySelector('.editor-considering-add'));
            assert.equal(draftBody().lists.considering,undefined);
          }
        """)

    def test_draft_and_snapshot_keep_considering_separate_and_explicit_empty_clears(self):
        self.run_js(r"""
          let ed=openConsidering(),playable=sendList(ed.lists);
          quantity(ed,0,9);assert(saveDraft(ed));
          let stored=JSON.parse(local.get(draftKey(ed))),snap=JSON.parse(snapshot(ed));
          same(stored.considering.map(sendLine),plainConsidering(ed));
          same(stored.base.considering,candidates.map(sendLine));
          same(snap.considering.map(sendLine),plainConsidering(ed));
          same(stored.lists,keepList(ed.lists));assert(!stored.lists.Considering);
          startEditor({mode:'edit',view:consideringView(),version:'target'});ed=editor;
          assert.equal(ed.notice.kind,'draft');assert.equal(ed.considering[0].qty,9);
          same(sendList(ed.lists),playable);
          ed.considering=[];changed({list:false});assert(saveDraft(ed));
          startEditor({mode:'edit',view:consideringView(),version:'target'});ed=editor;
          same(ed.considering,[]);same(draftBody().lists,{considering:[]});
          same(ed.base.considering.map(sendLine),candidates.map(sendLine));
        """)

    def test_add_and_quantity_validation_leave_invalid_input_out_of_the_draft(self):
        self.run_js(r"""
          const ed=openConsidering(),before=plainConsidering(ed);
          main.querySelector('.editor-considering-add').click();const sheet=document.querySelector('dialog');
          const name=sheet.querySelector('.editor-considering-name'),qty=sheet.querySelector('.editor-considering-copies');
          const add=sheet.querySelector('[data-action="add"]');
          for(const [n,q] of [['',1],[bolt.name,0],[bolt.name,100],[bolt.name,1.5],[bolt.name,'']]) {
            name.value=n;qty.value=String(q);add.click();
            same(plainConsidering(ed),before);assert(sheet.isConnected);
            assert(sheet.querySelector('.form-error').textContent);
          }
          button(sheet,'Cancel').click();
          for(const invalid of [0,100,1.5,'']) {
            quantity(ed,0,invalid);same(plainConsidering(ed),before);
          }
          assert.equal(ed.history.length,0);assert(!isDirty());
          quantity(ed,0,99);assert.equal(ed.considering[0].qty,99);
          const field=main.querySelector('.editor-considering-qty');
          field.fire('compositionstart');field.value='4';field.fire('change');
          assert.equal(ed.considering[0].qty,99);field.fire('compositionend');
          assert.equal(ed.considering[0].qty,4);
        """)

    def test_missing_api_during_draft_resume_keeps_local_alternatives_and_refuses_save(self):
        self.run_js(r"""
          for(const changedSha of [false,true]) {
            const ed=openConsidering();quantity(ed,0,9);assert(saveDraft(ed));
            const rows=plainConsidering(ed),key=draftKey(ed),latest=view(changedSha?{sha256:'b'.repeat(64)}:{});
            startEditor({mode:'edit',view:latest,version:'target'});
            same(plainConsidering(editor),rows);assert(editor.consideringUnavailable);
            assert(!editorConsideringSupported(editor));
            assert(!main.querySelector('.editor-considering-add'));
            assert(main.textContent.includes('kept on this device'));
            assert(editor.dom.barParts.save.disabled);
            assert.equal(draftBody().lists,undefined);
            let requests=0;apiWrite=async()=>{requests++;throw new Error('Unavailable alternatives must not save');};
            await saveNow();assert.equal(requests,0);
            assert(saveDraft(editor));
            same(JSON.parse(local.get(key)).considering.map(sendLine),rows);
          }
        """)

    def test_unchanged_modern_alternatives_do_not_block_independent_field_save_when_api_omits_them(self):
        self.run_js(r"""
          const first=openConsidering(),original=structuredClone(first.view.lists.considering);
          first.fields.archetype='Independent field change';changed({list:false});assert(saveDraft(first));
          const key=draftKey(first),stored=JSON.parse(local.get(key));
          same(stored.considering.map(sendLine),stored.base.considering);
          startEditor({mode:'edit',view:view(),version:'target'});const resumed=editor;
          assert.equal(resumed.notice.kind,'draft');assert(!resumed.consideringUnavailable);
          assert(!editorConsideringSupported(resumed));assert(!editorConsideringChanged(resumed));
          assert(!main.querySelector('.edit-considering'));assert(!main.querySelector('.editor-considering-add'));
          assert(!resumed.dom.barParts.save.disabled);same(plainConsidering(resumed),original.map(sendLine));
          same(draftBody(),{id:first.id,sha256:'a'.repeat(64),fields:{archetype:'Independent field change'}});
          const requests=[],serverRows=structuredClone(original);
          runCheck=async()=>consideringCheck({changes:{decklist:false,categories:false,considering:false,
            fields:['archetype'],prose:[],marker:false}});
          apiWrite=async(path,body)=>{requests.push([path,body]);
            assert.equal(body.lists,undefined);
            return {id:first.id,title:first.title,changed:true,deck:view({sha256:'b'.repeat(64),
              fields:{...resumed.view.fields,archetype:body.fields.archetype}})};};
          await saveNow();
          same(requests,[['/api/deck/save',{id:first.id,sha256:'a'.repeat(64),
            fields:{archetype:'Independent field change'}}]]);
          same(serverRows,original);same(first.view.lists.considering,original);
          assert(editor!==resumed);assert(!isDirty());assert.equal(editor.fields.archetype,'Independent field change');
          assert.equal(local.get(key),null);assert(!main.querySelector('.edit-considering'));
        """)

    def test_explicit_empty_with_unknown_baseline_stays_unknown_until_a_real_list_is_fetched(self):
        self.run_js(r"""
          const seed=openConsidering();seed.considering=[];changed({list:false});assert(saveDraft(seed));
          const key=draftKey(seed),stored=JSON.parse(local.get(key));delete stored.base.considering;
          local.set(key,JSON.stringify(stored));
          for(let resume=0;resume<3;resume++) {
            startEditor({mode:'edit',view:view(),version:'target'});
            same(editor.considering,[]);assert(isDirty());assert(editorConsideringChanged(editor));
            assert(editor.consideringUnavailable);assert(!Object.hasOwn(editor.base,'considering'));
            assert.equal(draftBody().lists,undefined);same(JSON.parse(snapshot(editor)).considering,[]);
            assert(saveDraft(editor));const again=JSON.parse(local.get(key));
            same(again.considering,[]);assert(!Object.hasOwn(again.base,'considering'));
          }
          startEditor({mode:'edit',view:view({sha256:'b'.repeat(64)}),version:'target'});
          assert.equal(editor.notice.kind,'draft-changed');same(editor.considering,[]);
          assert(editor.consideringUnavailable);assert(isDirty());assert(!Object.hasOwn(editor.base,'considering'));
          assert(editor.notice.notes.some(note=>/Considering could not be loaded/.test(note)));
          assert(saveDraft(editor));assert(!Object.hasOwn(JSON.parse(local.get(key)).base,'considering'));
          startEditor({mode:'edit',view:consideringView({sha256:'c'.repeat(64)},[candidates[0]]),version:'target'});
          same(editor.considering,[]);same(editor.base.considering.map(sendLine),[sendLine(candidates[0])]);
          assert(!editor.consideringUnavailable);assert(isDirty());same(draftBody().lists,{considering:[]});
          assert(saveDraft(editor));
          startEditor({mode:'edit',view:consideringView({sha256:'d'.repeat(64)},[]),version:'target'});
          same(editor.considering,[]);same(editor.base.considering,[]);
          assert(editorConsideringSupported(editor));assert(!editor.consideringUnavailable);assert(!isDirty());
          assert.equal(draftBody().lists,undefined);assert(saveDraft(editor));assert.equal(local.get(key),null);
        """)

    def test_legacy_draft_without_considering_preserves_latest_on_same_and_new_sha(self):
        self.run_js(r"""
          for(const changedSha of [false,true]) {
            const ed=openConsidering();ed.fields.archetype='Local field edit';changed({list:false});
            assert(saveDraft(ed));const key=draftKey(ed),old=JSON.parse(local.get(key));
            delete old.considering;delete old.base.considering;local.set(key,JSON.stringify(old));
            const latest=[{...candidates[0],qty:8,category:'Saved elsewhere'}];
            startEditor({mode:'edit',view:consideringView(changedSha?{sha256:'b'.repeat(64)}:{},latest),version:'target'});
            same(plainConsidering(editor),latest.map(sendLine));
            same(editor.base.considering.map(sendLine),latest.map(sendLine));
            assert.equal(editor.fields.archetype,'Local field edit');
            assert.equal(draftBody().lists,undefined);
            assert.equal(editorConsideringChanged(editor),false);
          }
        """)

    def test_three_way_rebase_takes_latest_if_local_unchanged_and_keeps_local_if_latest_unchanged(self):
        self.run_js(r"""
          let ed=openConsidering(),base=ed.base;
          let latest=[{...candidates[0],qty:8,category:'Latest category'},candidates[2]];
          rebase(ed,consideringView({sha256:'b'.repeat(64)},latest),mine(ed),base);
          same(plainConsidering(ed),latest.map(sendLine));assert(!editorConsideringChanged(ed));
          ed=openConsidering();base=ed.base;quantity(ed,0,7);ed.considering[1].category='My category';
          const localRows=plainConsidering(ed),notes=rebase(ed,consideringView({sha256:'c'.repeat(64)}),mine(ed),base);
          same(plainConsidering(ed),localRows);assert(editorConsideringChanged(ed));
          assert(!notes.some(note=>/Considering.*latest/i.test(note)));
          same(ed.base.considering.map(sendLine),candidates.map(sendLine));
        """)

    def test_conflicting_rebase_keeps_exact_local_rows_and_names_review_without_additive_merge(self):
        self.run_js(r"""
          const ed=openConsidering(),base=ed.base;
          quantity(ed,0,5);ed.considering[1].category='My category';ed.considering.reverse();
          const localRows=plainConsidering(ed),latest=[{...candidates[0],qty:10,category:'Their category'}];
          const notes=rebase(ed,consideringView({sha256:'b'.repeat(64)},latest),mine(ed),base);
          same(plainConsidering(ed),localRows);
          same(ed.base.considering.map(sendLine),latest.map(sendLine));
          assert(notes.some(note=>/Considering/i.test(note)&&/kept|review/i.test(note)));
          same(draftBody().lists.considering,localRows);
          assert.equal(listChanged(),false);
        """)

    def test_stale_draft_explicit_empty_survives_a_concurrent_saved_change(self):
        self.run_js(r"""
          const ed=openConsidering();ed.considering=[];changed({list:false});assert(saveDraft(ed));
          const latest=[{...candidates[0],qty:12,category:'Saved elsewhere'}];
          startEditor({mode:'edit',view:consideringView({sha256:'b'.repeat(64)},latest),version:'target'});
          assert.equal(editor.notice.kind,'draft-changed');same(editor.considering,[]);
          same(editor.base.considering.map(sendLine),latest.map(sendLine));
          same(draftBody().lists,{considering:[]});
          assert(editor.notice.notes.some(note=>/Considering/i.test(note)&&/kept|review/i.test(note)));
        """)

    def test_load_latest_carries_considering_through_the_real_conflict_action(self):
        self.run_js(r"""
          const ed=openConsidering();quantity(ed,0,7);ed.considering[1].category='My later idea';
          const rows=plainConsidering(ed),latestRows=[{...candidates[0],qty:11,category:'Their idea'}],reads=[];
          api=async path=>{reads.push(path);return consideringView({sha256:'b'.repeat(64)},latestRows);};
          await reapplyLatest(null,{message:'Fixture stale save'},null);
          same(reads,['/api/deck/edit?id=casual%2Fsample']);
          same(plainConsidering(editor),rows);
          same(editor.base.considering.map(sendLine),latestRows.map(sendLine));
          assert.equal(editor.sha256,'b'.repeat(64));assert.equal(editor.notice.kind,'reapplied');
          assert(editor.notice.notes.some(note=>/Considering/i.test(note)&&/kept|review/i.test(note)));
          same(draftBody().lists,{considering:rows});
          const stored=JSON.parse(local.get(draftKey(editor)));
          assert.equal(stored.sha256,'b'.repeat(64));same(stored.considering.map(sendLine),rows);
        """)

    def test_late_conflict_reload_cannot_replace_alternatives_after_its_owner_changes(self):
        self.run_js(r"""
          for(const invalidate of [(ed,sheet)=>{routeToken++;},
            (ed,sheet)=>{state.profile=state.profiles[0];},(ed,sheet)=>sheet.close(),
            (ed,sheet)=>{ed.version='owned';}]) {
            state.profile=state.profiles[1];const ed=openConsidering();quantity(ed,0,7);
            const before=snapshot(ed),base=ed.base,rows=plainConsidering(ed);
            const sheet=openSheet('Fixture conflict');let resolve,reads=0;
            api=()=>{reads++;return new Promise(done=>{resolve=done;});};
            const pending=reapplyLatest(sheet,{message:'Fixture stale save'},null);
            assert.equal(reads,1);invalidate(ed,sheet);
            resolve(consideringView({sha256:'b'.repeat(64)},[{...candidates[0],qty:20}]));await pending;
            assert(editor===ed);assert.equal(ed.sha256,'a'.repeat(64));
            assert.equal(snapshot(ed),before);assert.equal(ed.base,base);same(plainConsidering(ed),rows);
            assert.equal(ed.notice,null);if(!sheet.closed)sheet.close();
          }
        """)

    def test_undo_restores_each_considering_change_without_touching_playable_or_owned_flags(self):
        self.run_js(r"""
          const ed=openConsidering({lists:{target:structuredClone(list),owned:null}},{version:'owned'});
          const playable=listSignature(ed.lists),original=plainConsidering(ed);
          quantity(ed,0,8);main.querySelectorAll('.editor-considering-remove')[1].click();
          assert.equal(ed.considering.length,2);assert.equal(ed.history.length,2);
          assert(undoLast());assert.equal(ed.considering.length,3);assert.equal(ed.considering[0].qty,8);
          assert(undoLast());same(plainConsidering(ed),original);
          assert.equal(isDirty(),false);assert.equal(ed.dirty,false);
          assert.equal(listSignature(ed.lists),playable);
          assert.equal(ed.starting,false);assert.equal(ed.hasFileList,false);assert(noOwnedList());
          assert.equal(draftBody().lists,undefined);
          assert.equal(local.get(draftKey(ed)),null);
        """)

    def test_undo_recovers_quantity_focus_on_the_correct_identical_duplicate(self):
        self.run_js(r"""
          const duplicates=[{...candidates[0],qty:2,category:'Same idea'},
            {...candidates[0],qty:2,category:'Same idea'},{...candidates[0],qty:2,category:'Another idea'}];
          for(const isQuick of [true,false]) {
            const ed=openConsidering({}, {}, isQuick, duplicates),playable=listSignature(ed.lists);
            const oldField=main.querySelectorAll('.editor-considering-qty')[1],uid=ed.considering[1].uid;
            oldField.focus();oldField.value='8';oldField.fire('input');
            assert.equal(ed.considering[1].qty,8);assert.equal(ed.considering[0].qty,2);
            assert(undoLast());
            const fields=main.querySelectorAll('.editor-considering-qty');
            assert(ed.considering[1].uid!==uid);assert(!oldField.isConnected);
            assert.equal(document.activeElement,fields[1]);assert(fields[1].isConnected);
            assert.equal(fields[1].value,'2');assert.equal(fields[1].focusOptions.preventScroll,true);
            same(plainConsidering(ed),duplicates.map(sendLine));
            assert.equal(listSignature(ed.lists),playable);assert(!isDirty());
          }
        """)

    def test_unstarted_play_now_enables_considering_save_without_creating_owned(self):
        self.run_js(r"""
          for(const isQuick of [true,false]) {
            const ed=openConsidering({lists:{target:structuredClone(list),owned:null}},{version:'owned'},isQuick);
            assert(noOwnedList());assert(main.querySelector('.editor-considering-add'));
            quantity(ed,0,4);
            assert.equal(ed.starting,false);assert.equal(ed.hasFileList,false);assert(noOwnedList());
            same(sendList(ed.lists),{});assert(!listChanged());
            same(draftBody().lists,{considering:plainConsidering(ed)});
            assert.equal(draftBody().lists.owned,undefined);
            assert(!ed.dom.barParts.save.disabled);
            assert.equal(ed.view.lists.owned,null);
          }
        """)

    def test_considering_only_save_now_saves_in_place_and_reloads_exact_saved_baseline(self):
        self.run_js(r"""
          const ed=openConsidering(),requests=[];quantity(ed,0,6);assert(saveDraft(ed));
          const rows=plainConsidering(ed),oldKey=draftKey(ed);
          runCheck=async()=>consideringCheck();
          apiWrite=async(path,body)=>{
            requests.push([path,body]);assert.equal(path,'/api/deck/save');
            return {id:ed.id,title:ed.title,changed:true,
              deck:consideringView({sha256:'b'.repeat(64)},ed.considering)};
          };
          await saveNow();
          same(requests,[['/api/deck/save',{id:ed.id,sha256:'a'.repeat(64),lists:{considering:rows}}]]);
          assert(editor!==ed);assert.equal(editor.sha256,'b'.repeat(64));
          same(plainConsidering(editor),rows);assert(!isDirty());assert(!editorConsideringChanged(editor));
          assert.equal(local.get(oldKey),null);assert.equal(draftBody().lists,undefined);
          assert.equal(document.querySelector('dialog'),null);
        """)

    def test_confirm_empty_left_after_playable_undo_does_not_leak_into_considering_only_save(self):
        self.run_js(r"""
          const ed=openConsidering(),playable=sendList(ed.lists);ed.lists={};changed();ed.confirmEmpty=true;
          assert.equal(draftBody().confirm_empty,true);assert(undoLast());
          same(sendList(ed.lists),playable);assert(!listChanged());assert.equal(ed.confirmEmpty,true);
          quantity(ed,0,7);const rows=plainConsidering(ed);
          same(draftBody(),{id:ed.id,sha256:'a'.repeat(64),lists:{considering:rows}});
          const requests=[];
          apiWrite=async(path,body)=>{requests.push([path,body]);
            assert.equal(body.confirm_empty,undefined);assert.equal(body.lists.target,undefined);
            if(path==='/api/deck/check')return consideringCheck({lists:{considering:ed.considering}});
            assert.equal(path,'/api/deck/save');return {id:ed.id,title:ed.title,changed:true,
              deck:consideringView({sha256:'b'.repeat(64)},ed.considering)};};
          await saveNow();
          same(requests.map(([path])=>path),['/api/deck/check','/api/deck/save']);
          for(const [,body] of requests)same(body.lists,{considering:rows});
          assert(editor!==ed);assert(!isDirty());same(sendList(editor.lists),playable);
          same(plainConsidering(editor),rows);
        """)

    def test_considering_only_save_and_view_keeps_the_normal_navigation_contract(self):
        self.run_js(r"""
          const ed=openConsidering(),requests=[];quantity(ed,0,6);
          runCheck=async()=>consideringCheck();
          apiWrite=async(path,body)=>{requests.push([path,body]);return {id:ed.id,title:ed.title,changed:true,
            deck:consideringView({sha256:'b'.repeat(64)},ed.considering)};};
          await saveNow({viewAfter:true});
          assert.equal(requests.length,1);assert.equal(requests[0][0],'/api/deck/save');
          assert.equal(location.hash,deckHref(ed.id,'target'));assert(ed.leaving);
          assert.equal(state.saved.profile,ed.profile);assert.equal(state.saved.mode,'edit');
          same(state.saved.answer.deck.lists.considering.map(sendLine),plainConsidering(ed));
        """)

    def test_review_shows_considering_change_without_claiming_playable_change_or_nothing(self):
        self.run_js(r"""
          const ed=openConsidering();quantity(ed,0,6);
          const sheet=openSheet('Fixture review');drawReview(sheet,consideringCheck());
          assert(/Considering/i.test(sheet.body.textContent));
          assert(!sheet.body.textContent.includes('Nothing to save'));
          assert(!sheet.body.textContent.includes('Changes to the planned list:'));
          assert(!sheet.body.textContent.includes('Changes to the play-now list:'));
          assert(!sheet.body.textContent.includes('Adds a line saying the list changed'));
          assert.equal(button(sheet.foot,'Save').disabled,false);
          sheet.close();
          const blocked=openSheet('Blocked review');
          drawReview(blocked,consideringCheck({blocks:[{list:'considering',index:2,problem:'Unknown new card'}]}));
          assert(blocked.body.textContent.includes('Unknown new card'));
          assert.equal(button(blocked.foot,'Save').disabled,true);
        """)

    def test_review_displays_canonical_checked_rows_without_mutating_proposed_alternatives(self):
        self.run_js(r"""
          const proposed=[{...candidates[0],qty:1,name:'lightning bolt',card:null},
            {...candidates[0],qty:2,name:'lightning bolt',card:null},
            {qty:4,name:'llanowar elves',set:'fdn',number:'227',category:'Ramp',card:null}];
          const ed=openConsidering({}, {}, true, proposed),before=snapshot(ed);
          const normalized=[{...candidates[0],qty:3},
            {qty:4,name:elves.name,set:'fdn',number:'227',category:'Ramp',card:elves}];
          const sheet=openSheet('Canonical review');drawReview(sheet,consideringCheck({lists:{considering:normalized}}));
          const rows=sheet.body.querySelector('.review-list').querySelectorAll('li').map(row=>row.textContent);
          assert.equal(rows.length,2);
          assert.match(rows[0],/^3 Lightning Bolt \(M11 146 . foil\) . Try first$/u);
          assert.match(rows[1],/^4 Llanowar Elves \(FDN 227\) . Ramp$/u);
          assert.equal(snapshot(ed),before);same(plainConsidering(ed),proposed.map(sendLine));sheet.close();
          const blocked=openSheet('Proposed review');drawReview(blocked,consideringCheck({lists:{considering:normalized},
            blocks:[{list:'considering',index:0,problem:'Alternative still needs review'}]}));
          const localRows=blocked.body.querySelector('.review-list').querySelectorAll('li').map(row=>row.textContent);
          assert.equal(localRows.length,3);assert(localRows[0].startsWith('1 lightning bolt (M11 146'));
          assert(localRows[1].startsWith('2 lightning bolt (M11 146'));
          assert.equal(snapshot(ed),before);same(plainConsidering(ed),proposed.map(sendLine));
        """)

    def test_retained_save_button_from_a_closed_review_sheet_cannot_start_a_write(self):
        self.run_js(r"""
          const ed=openConsidering();quantity(ed,0,7);const before=snapshot(ed);
          const sheet=openSheet('Fixture review');drawReview(sheet,consideringCheck());
          const save=button(sheet.foot,'Save');sheet.close();assert(!save.isConnected);
          let writes=0;apiWrite=async()=>{writes++;return {id:ed.id,title:ed.title,changed:true,
            deck:consideringView({sha256:'b'.repeat(64)},ed.considering)};};
          save.click();await settle();
          assert.equal(writes,0);assert(editor===ed);assert.equal(snapshot(ed),before);
          assert.equal(ed.sha256,'a'.repeat(64));assert(!ed.leaving);
        """)

    def test_discard_removes_considering_draft_then_reloads_without_mutating_saved_view(self):
        self.run_js(r"""
          const ed=openConsidering(),original=structuredClone(ed.view.lists.considering);
          quantity(ed,0,8);assert(saveDraft(ed));const key=draftKey(ed);assert(local.get(key));
          let reloads=0;route=()=>{reloads++;};discardChanges(null);
          assert.equal(reloads,1);assert.equal(local.get(key),null);assert(ed.leaving);
          same(ed.view.lists.considering,original);
        """)

    def test_retained_controls_refuse_pending_read_only_and_other_profile_or_editor(self):
        self.run_js(r"""
          for(const invalidate of [ed=>{ed.saving=true;},ed=>{ed.asking=true;},
            ed=>{ed.readOnly=true;},ed=>{ed.leaving=true;},
            ed=>{state.profile=state.profiles[0];},ed=>{routeToken++;},
            ed=>{openConsidering();}]) {
            state.profile=state.profiles[1];
            const ed=openConsidering(),before=plainConsidering(ed);
            const field=main.querySelector('.editor-considering-qty'),remove=main.querySelector('.editor-considering-remove');
            invalidate(ed);field.value='9';field.fire('change');remove.click();
            same(plainConsidering(ed),before);
          }
          state.profile=state.profiles[1];const readOnly=openConsidering({may_save:false});
          assert(readOnly.readOnly);
          for(const control of main.querySelectorAll('.editor-considering-add, .editor-considering-qty, .editor-considering-remove')) {
            assert(control.disabled||control.hidden,'Read-only Considering controls cannot edit');
          }
        """)

    def test_retained_section_controls_cannot_edit_after_redraw_or_leaving_cards_tab(self):
        self.run_js(r"""
          for(const isQuick of [true,false]) {
            for(const replace of [()=>drawEditorConsidering(),()=>document.getElementById('edit-tab-notes').click()]) {
              const ed=openConsidering({}, {}, isQuick),before=plainConsidering(ed),history=ed.history.length;
              const field=main.querySelector('.editor-considering-qty'),remove=main.querySelector('.editor-considering-remove');
              const row=field.closest('.editor-considering-row'),steps=row.querySelectorAll('.step');
              const add=main.querySelector('.editor-considering-add');replace();
              assert(!field.isConnected);assert(!add.isConnected);
              field.value='9';field.fire('input');field.fire('change');
              field.fire('compositionstart');field.value='4';field.fire('compositionend');
              for(const step of steps)step.click();remove.click();add.click();
              same(plainConsidering(ed),before);assert.equal(ed.history.length,history);
              assert.equal(document.querySelector('dialog'),null);assert(!isDirty());
            }
          }
        """)

    def test_add_sheet_confirmation_refuses_a_replaced_launching_section(self):
        self.run_js(r"""
          for(const isQuick of [true,false]) {
            const ed=openConsidering({}, {}, isQuick),before=plainConsidering(ed);
            const launcher=main.querySelector('.editor-considering-add');launcher.click();
            const sheet=document.querySelector('dialog');assert(sheet);
            sheet.querySelector('.editor-considering-name').value=elves.name;
            sheet.querySelector('.editor-considering-copies').value='4';
            const confirm=sheet.querySelector('[data-action="add"]');drawEditorConsidering();
            assert(!launcher.isConnected);confirm.click();
            same(plainConsidering(ed),before);assert.equal(ed.history.length,0);assert(!isDirty());
            if(sheet.isConnected)button(sheet,'Cancel').click();
          }
        """)

    def test_typed_quantity_and_composition_end_reach_save_body_without_blurring(self):
        self.run_js(r"""
          const ed=openConsidering(),field=main.querySelector('.editor-considering-qty');field.focus();
          field.value='7';field.fire('input');
          assert.equal(ed.considering[0].qty,7);assert.equal(draftBody().lists.considering[0].qty,7);
          assert.equal(document.activeElement,field);assert(field.isConnected);
          const count=ed.history.length;
          field.fire('compositionstart');field.value='8';field.fire('input');
          assert.equal(ed.considering[0].qty,7);assert.equal(ed.history.length,count);
          field.fire('compositionend');
          assert.equal(ed.considering[0].qty,8);assert.equal(draftBody().lists.considering[0].qty,8);
          assert.equal(ed.history.length,count+1);assert.equal(document.activeElement,field);
          const posts=[];runCheck=async()=>consideringCheck();
          doSave=async()=>posts.push(draftBody());await saveNow();
          assert.equal(posts.length,1);assert.equal(posts[0].lists.considering[0].qty,8);
          assert.equal(posts[0].lists.target,undefined);
        """)

    def test_open_add_sheet_refuses_late_confirmation_after_ownership_or_pending_changes(self):
        self.run_js(r"""
          for(const invalidate of [ed=>{ed.saving=true;},ed=>{ed.readOnly=true;},
            ed=>{state.profile=state.profiles[0];},ed=>{routeToken++;},ed=>{openConsidering();}]) {
            state.profile=state.profiles[1];const ed=openConsidering(),before=plainConsidering(ed);
            main.querySelector('.editor-considering-add').click();const sheet=document.querySelector('dialog');
            assert(sheet);sheet.querySelector('.editor-considering-name').value=elves.name;
            sheet.querySelector('.editor-considering-copies').value='3';
            const add=sheet.querySelector('[data-action="add"]');invalidate(ed);add.click();
            same(plainConsidering(ed),before);
            if(sheet.isConnected)button(sheet,'Cancel').click();
          }
        """)

    def test_late_save_check_cannot_send_alternatives_after_profile_read_only_or_editor_change(self):
        self.run_js(r"""
          for(const invalidate of [ed=>{state.profile=state.profiles[0];},
            ed=>{ed.readOnly=true;},ed=>{openConsidering();}]) {
            state.profile=state.profiles[1];const ed=openConsidering();quantity(ed,0,7);
            const requests=[];let resolve;
            apiWrite=(path,body)=>{requests.push([path,body]);return new Promise(done=>{resolve=done;});};
            const saving=saveNow();assert(ed.saving);assert.equal(requests.length,1);
            assert.equal(requests[0][0],'/api/deck/check');
            invalidate(ed);resolve(consideringCheck());await saving;
            assert.equal(requests.length,1);assert.equal(ed.considering[0].qty,7);assert(!ed.saving);
            assert.equal(document.querySelector('dialog'),null);
          }
        """)

    def test_check_metadata_hydrates_only_current_considering_rows_without_overwriting_local_fields(self):
        self.run_js(r"""
          const ed=openConsidering({}, {}, true, [{qty:2,name:bolt.name,category:'My note',card:null}]);
          quantity(ed,0,3);let resolve;apiWrite=()=>new Promise(done=>{resolve=done;});
          const qtyField=main.querySelector('.editor-considering-qty');qtyField.focus();
          const current=runCheck(ed);
          resolve(consideringCheck({lists:{considering:[{qty:99,name:bolt.name,category:'Server note',card:bolt}]}}));
          await current;
          assert.equal(ed.considering[0].card.name,bolt.name);assert.equal(ed.considering[0].qty,3);
          assert.equal(ed.considering[0].category,'My note');
          assert(qtyField.isConnected);assert.equal(document.activeElement,qtyField);assert.equal(qtyField.value,'3');
          ed.considering[0].card=null;quantity(ed,0,4);
          const late=runCheck(ed),oldResolve=resolve;ed.checkSeq++;
          oldResolve(consideringCheck({lists:{considering:[{qty:4,name:bolt.name,card:bolt}]}}));await late;
          assert.equal(ed.considering[0].card,null);
          const wrong=runCheck(ed);
          resolve(consideringCheck({lists:{considering:[{qty:4,name:elves.name,card:elves}]}}));await wrong;
          assert.equal(ed.considering[0].card,null);assert.equal(ed.considering[0].name,bolt.name);
        """)

    def test_considering_validation_marks_its_own_flat_row_and_leaves_playable_rows_unmarked(self):
        self.run_js(r"""
          const ed=openConsidering();quantity(ed,0,6);
          apiWrite=async()=>consideringCheck({blocks:[{list:'considering',index:1,problem:'Fixture alternative problem'}],
            lists:{considering:ed.considering.map(line=>({...sendLine(line),card:line.card}))}});
          await runCheck(ed);
          const rows=main.querySelectorAll('.editor-considering-row');
          assert(!rows[0].classList.contains('is-blocked'));assert(rows[1].classList.contains('is-blocked'));
          assert(rows[1].textContent.includes('Fixture alternative problem'));
          assert.equal(ed.dom.lines.querySelector('.is-blocked'),null);
          assert.equal(listChanged(),false);
        """)
