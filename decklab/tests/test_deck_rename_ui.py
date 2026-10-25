"""Reviewed rename and old-address browser-draft recovery over synthetic UI responses only."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = PAGE + r"""
  clear(main); editor=null;
  const matt={id:'matt',name:'Matt',role:'admin',space:'home',plays_as:'user'};
  state.profile=matt;state.profiles=[matt];state.may={admin:true,see_inventory:['home'],spaces:['home'],deck_spaces:['home']};
  history.replaceState=(s,t,hash)=>{history.state=s;if(hash!==undefined){hashes.push(hash);location.hash=hash;}};
  const metadata=(extra={})=>({id:'casual/test',title:'Test Deck',sha256:'a'.repeat(64),revision:7,
    may_rename:true,why_not:null,...extra});
  const preview=(extra={})=>({id:'casual/test',old_title:'Test Deck',title:'New Deck',new_id:'casual/new-deck',
    sha256:'a'.repeat(64),revision:7,decks_revision:'d'.repeat(64),changed:true,notes:[],...extra});
  const editView=(extra={})=>({id:'casual/new-deck',space:'home',kind:'casual',title:'New Deck',
    sha256:'b'.repeat(64),editable:true,may_save:true,why_not:null,sections:['Deck','Sideboard'],
    fields:{status:'building',player:'user'},field_text:{},changed_on:null,aliases:['casual/test'],
    lists:{target:makePage().sections,owned:null},prose:{notes:'Keep the plan.',substitutes:''},...extra});
  const oldDraft=(extra={})=>JSON.stringify({v:1,saved:1000,sha256:'a'.repeat(64),starting:false,
    base:{lists:sendList(makePage().sections),fields:{status:'building',player:'user'},prose:{notes:'Keep the plan.',substitutes:''}},
    lists:{Deck:[{qty:1,name:'Elf',card:elf}]},fields:{status:'building',player:'user'},...extra});
  const requests=[],reads=[],messages=[],sheets=[],stored=new Map();
  local.get=key=>stored.get(key)||null;local.set=(key,value)=>{stored.set(key,value);return true;};
  local.remove=key=>{stored.delete(key);return true;};
  const realSheet=openSheet;openSheet=(...args)=>{const sheet=realSheet(...args);sheets.push(sheet);return sheet;};
  const settle=async()=>{for(let n=0;n<35;n++)await Promise.resolve();};
  const held=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
  const button=(root,text)=>{const found=root.querySelectorAll('button').find(node=>node.textContent===text);assert(found,`Button ${text}`);return found;};
  const action=(ctx,text)=>button(ctx.sheet.foot,text);
  const typeTitle=(ctx,text)=>{ctx.input.value=text;ctx.input.fire('input');};
  const acknowledge=ctx=>{ctx.confirm.checked=true;ctx.confirm.fire('change');};
  const mount=(data=makePage())=>{clear(main);location.hash='#/deck?id='+encodeURIComponent(data.summary.id)+'&v=owned&tab=cards&filter=missing';
    drawDeck(data,deckViewOf(parseHash().params));return data;};
  const openRename=async(data=makePage())=>{mount(data);const ctx=openRenameDeck(data);assert(ctx);await settle();return ctx;};
  const ready=async()=>{const ctx=await openRename();typeTitle(ctx,'New Deck');action(ctx,'Preview rename').click();await settle();return ctx;};
  const latest=()=>sheets.at(-1);
  let answerRead=async()=>metadata(),answerWrite=async path=>path.endsWith('/preview')?preview():{id:'casual/new-deck',title:'New Deck'};
  api=async path=>{reads.push(path);return answerRead(path);};
  apiWrite=async(path,body)=>{requests.push([path,body]);return answerWrite(path,body);};
  toast=words=>messages.push(words);scheduleCheck=()=>{};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckRenameUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_menu_accepts_built_and_personal_editable_decks_but_not_products(self):
        self.run_js(r"""
          for(const status of ['idea','building','built']) {
            const data=makePage();data.summary.status=status;assert(canRenameDeck(data));
            assert(deckMoreItems(data).some(item=>item&&item.label==='Rename deck…'));
          }
          for(const extra of [{read_only:true},{error:'Unreadable'},{id:'product/starter/green'},
              {id:'pairing/test'},{id:'casual/../bad'},{id:''}]) {
            const data=makePage();Object.assign(data.summary,extra);assert(!canRenameDeck(data));
          }
          state.may={admin:false,deck_spaces:['user2'],home_player:null};
          assert.equal(openRenameDeck(makePage()),null);same(reads,[]);
          const personal=makePage();Object.assign(personal.summary,{id:'user2/casual/test',space:'user2',player:null});
          assert(canRenameDeck(personal));
        """)

    def test_metadata_is_fresh_and_invalid_metadata_fails_closed(self):
        self.run_js(r"""
          for(const extra of [{id:'casual/other'},{revision:0},{revision:'7'},{sha256:'a'.repeat(40)},
              {may_rename:false,why_not:'Run the database migration first.'}]) {
            answerRead=async()=>metadata(extra);const ctx=await openRename();
            assert(!ctx.sheet.foot.querySelector('[data-action=preview]'));await sendRenameDeck(ctx);same(requests,[]);ctx.sheet.close();
          }
          answerRead=async()=>metadata();const ctx=await openRename();
          assert.equal(reads.at(-1),'/api/deck/rename?id=casual%2Ftest');assert.equal(ctx.input.value,'Test Deck');
        """)

    def test_preview_shows_exact_from_to_and_requires_an_additional_confirmation(self):
        self.run_js(r"""
          const ctx=await ready();same(requests,[['/api/deck/rename/preview',{profile:'matt',id:'casual/test',title:'New Deck',sha256:'a'.repeat(64),revision:7}]]);
          assert(ctx.reviewBox.textContent.includes('Test Deck'));assert(ctx.reviewBox.textContent.includes('casual/test'));
          assert(ctx.reviewBox.textContent.includes('New Deck'));assert(ctx.reviewBox.textContent.includes('casual/new-deck'));
          assert(action(ctx,'Rename deck').disabled);await sendRenameDeck(ctx);assert.equal(requests.length,1);
          acknowledge(ctx);assert(!action(ctx,'Rename deck').disabled);
        """)

    def test_title_edit_drops_the_old_review_and_confirmation(self):
        self.run_js(r"""
          const ctx=await ready();acknowledge(ctx);typeTitle(ctx,'Another Deck');
          assert.equal(ctx.review,null);assert(!ctx.sheet.body.querySelector('input[type=checkbox]'));
          assert(action(ctx,'Preview rename'));await sendRenameDeck(ctx);assert.equal(requests.length,1);
        """)

    def test_normalized_title_and_control_character_validation_precede_preview(self):
        self.run_js(r"""
          const ctx=await openRename();
          for(const title of ['  ','One'+String.fromCharCode(10)+'Two','x'.repeat(101)]) {
            typeTitle(ctx,title);await previewRenameDeck(ctx);same(requests,[]);
          }
          assert.equal(renameTitle('  New'+String.fromCharCode(0x200b)+'   Deck  '),'New Deck');
          typeTitle(ctx,'  New   Deck  ');action(ctx,'Preview rename').click();await settle();assert.equal(requests[0][1].title,'New Deck');
        """)

    def test_rename_posts_the_reviewed_destination_and_preserves_the_current_view(self):
        self.run_js(r"""
          const ctx=await ready();acknowledge(ctx);state.library={decks:['stale']};action(ctx,'Rename deck').click();await settle();
          same(requests[1],['/api/deck/rename',{profile:'matt',id:'casual/test',title:'New Deck',new_id:'casual/new-deck',
            sha256:'a'.repeat(64),revision:7,decks_revision:'d'.repeat(64)}]);
          assert.equal(state.library,null);assert(ctx.sheet.closed);
          const params=parseHash().params;assert.equal(params.get('id'),'casual/new-deck');assert.equal(params.get('v'),'owned');
          assert.equal(params.get('tab'),'cards');assert.equal(params.get('filter'),'missing');
        """)

    def test_preview_and_save_each_allow_only_one_request_in_flight(self):
        self.run_js(r"""
          const wait=held();answerWrite=()=>wait.promise;const ctx=await openRename();typeTitle(ctx,'New Deck');
          action(ctx,'Preview rename').click();await previewRenameDeck(ctx);assert.equal(requests.length,1);assert(ctx.input.disabled);
          wait.resolve(preview());await settle();const save=held();answerWrite=()=>save.promise;acknowledge(ctx);
          const submit=action(ctx,'Rename deck');submit.click();submit.click();await sendRenameDeck(ctx);
          assert.equal(requests.length,2);assert(ctx.input.disabled);assert(ctx.confirm.disabled);
          save.resolve({id:'casual/new-deck',title:'New Deck'});await settle();assert(ctx.done);
        """)

    def test_untrusted_preview_can_never_enable_a_rename(self):
        self.run_js(r"""
          for(const extra of [{id:'casual/other'},{new_id:'user2/casual/new-deck'},{title:'Wrong title'},{old_title:'Changed title'},
              {sha256:'b'.repeat(64)},{revision:8},{decks_revision:''},{changed:'yes'}]) {
            answerWrite=async()=>preview(extra);const ctx=await openRename();typeTitle(ctx,'New Deck');
            action(ctx,'Preview rename').click();await settle();assert.equal(ctx.review,null);
            assert(!ctx.sheet.foot.querySelector('[data-action=rename]'));ctx.sheet.close();
          }
        """)

    def test_unchanged_preview_is_readable_but_has_no_write_action(self):
        self.run_js(r"""
          answerRead=async()=>metadata({title:'Test'});
          answerWrite=async()=>preview({old_title:'Test',title:'Test',new_id:'casual/test',changed:false});
          const ctx=await openRename();action(ctx,'Preview rename').click();await settle();
          assert(ctx.reviewBox.textContent.includes('Nothing needs changing'));assert(action(ctx,'Done'));
          assert(!ctx.sheet.foot.querySelector('[data-action=rename]'));assert.equal(requests.length,1);
        """)

    def test_conflict_reread_preserves_typed_title_and_resets_confirmation(self):
        self.run_js(r"""
          const ctx=await ready();acknowledge(ctx);answerWrite=async()=>{throw new ApiError(409,'Changed elsewhere');};
          action(ctx,'Rename deck').click();await settle();assert(ctx.conflict);await sendRenameDeck(ctx);assert.equal(requests.length,2);
          answerRead=async()=>metadata({sha256:'b'.repeat(64),revision:9});action(ctx,'Review latest deck').click();await settle();
          assert.equal(ctx.input.value,'New Deck');assert.equal(ctx.review,null);assert(!ctx.sheet.body.querySelector('input[type=checkbox]'));
          answerWrite=async()=>preview({sha256:'b'.repeat(64),revision:9});action(ctx,'Preview rename').click();await settle();
          assert(action(ctx,'Rename deck').disabled);assert.equal(ctx.review.revision,9);
        """)

    def test_uncertain_failure_requires_review_and_invalidates_the_library(self):
        self.run_js(r"""
          const ctx=await ready();acknowledge(ctx);answerWrite=async()=>{throw new ApiError(503,'Database unavailable');};
          state.library={decks:['stale']};action(ctx,'Rename deck').click();await settle();assert.equal(state.library,null);
          assert(ctx.error.textContent.includes('unsure'));assert(ctx.conflict);assert(action(ctx,'Review latest deck'));
          await sendRenameDeck(ctx);assert.equal(requests.length,2);
        """)

    def test_metadata_and_preview_results_cannot_reopen_a_closed_or_changed_context(self):
        self.run_js(r"""
          for(const leave of [ctx=>ctx.sheet.close(),()=>{state.profile={id:'user1'};},()=>{routeToken++;},()=>{location.hash='#/activity';}]) {
            state.profile=matt;const wait=held();answerRead=()=>wait.promise;mount();const ctx=openRenameDeck(makePage());leave(ctx);
            wait.resolve(metadata());await settle();assert(!ctx.sheet.body.querySelector('input'));closeDeckRetirementSheets();
          }
          state.profile=matt;answerRead=async()=>metadata();const ctx=await openRename();typeTitle(ctx,'New Deck');
          const wait=held();answerWrite=()=>wait.promise;action(ctx,'Preview rename').click();ctx.sheet.close();wait.resolve(preview());await settle();
          assert.equal(ctx.review,null);
        """)

    def test_late_success_refreshes_cache_without_touching_another_page_or_person(self):
        self.run_js(r"""
          for(const leave of [()=>{state.profile={id:'user1'};},()=>{routeToken++;},()=>{location.hash='#/activity';}]) {
            state.profile=matt;answerWrite=async()=>preview();const ctx=await ready();acknowledge(ctx);const wait=held();answerWrite=()=>wait.promise;
            action(ctx,'Rename deck').click();await settle();leave();clear(main).append(el('p',{text:'Other page'}));state.library={decks:['stale']};
            const hash=location.hash;wait.resolve({id:'casual/new-deck',title:'New Deck'});await settle();
            assert.equal(state.library,null);assert.equal(main.textContent,'Other page');assert.equal(location.hash,hash);closeDeckRetirementSheets();
          }
        """)

    def test_duplicate_open_and_existing_route_profile_away_cleanup_share_the_sheet_tracker(self):
        self.run_js(r"""
          const data=mount(),ctx=openRenameDeck(data);assert.equal(openRenameDeck(data),ctx);await settle();
          drawWho();assert(ctx.sheet.closed);state.profile=matt;const another=await openRename();state.remote=false;
          awayTooLong=()=>true;isMyDevice=()=>false;backFromAway();await settle();assert(another.sheet.closed);
        """)

    def test_canonical_addresses_keep_all_other_query_parameters(self):
        self.run_js(r"""
          for(const route of ['deck','history','edit']) {
            location.hash=`#/${route}?id=casual%2Ftest&v=owned&tab=cards&filter=missing&revision=4`;
            canonicalDeckAddress('casual/new-deck');assert.equal(parseHash().params.get('id'),'casual/new-deck');
            for(const [key,value] of [['v','owned'],['tab','cards'],['filter','missing'],['revision','4']]) assert.equal(parseHash().params.get(key),value);
          }
          location.hash='#/play?id=casual%2Ftest';canonicalDeckAddress('casual/new-deck');assert.equal(parseHash().params.get('id'),'casual/test');
        """)

    def test_old_and_current_drafts_are_a_choice_and_neither_changes_without_confirmation(self):
        self.run_js(r"""
          const oldKey='draft.matt.casual/test.target',currentKey='draft.matt.casual/new-deck.target';
          const old=oldDraft(),current=oldDraft({saved:2000});stored.set(oldKey,old);stored.set(currentKey,current);
          location.hash='#/edit?id=casual%2Ftest&v=target';openSavedDeckEditor(editView({requested_id:'casual/test'}),'target');
          assert.equal(editor,null);assert(main.textContent.includes('Choose a saved draft'));assert(main.textContent.includes('Keep current-address draft'));
          button(main,'Review draft from casual/test').click();assert(latest().body.textContent.includes('replaces the current-address draft'));
          button(latest().foot,'Cancel').click();assert.equal(stored.get(oldKey),old);assert.equal(stored.get(currentKey),current);
        """)

    def test_explicit_recovery_moves_the_draft_only_after_safe_copy_and_reapplies_it(self):
        self.run_js(r"""
          const oldKey='draft.matt.casual/test.target',key='draft.matt.casual/new-deck.target',raw=oldDraft();stored.set(oldKey,raw);
          location.hash='#/edit?id=casual%2Fnew-deck';openSavedDeckEditor(editView(),'target');button(main,'Review draft from casual/test').click();
          button(latest().foot,'Use this draft').click();assert(editor);assert.equal(editor.id,'casual/new-deck');
          assert.equal(editor.notice.kind,'draft-changed');assert.equal(stored.get(key),raw);assert(!stored.has(oldKey));
          assert.equal(editor.title,'New Deck');same(requests,[]);
        """)

    def test_failed_copy_or_concurrent_draft_change_never_removes_either_copy(self):
        self.run_js(r"""
          const oldKey='draft.matt.casual/test.target',key='draft.matt.casual/new-deck.target',raw=oldDraft();stored.set(oldKey,raw);
          location.hash='#/edit?id=casual%2Fnew-deck';openSavedDeckEditor(editView(),'target');button(main,'Review draft from casual/test').click();
          local.set=()=>false;button(latest().foot,'Use this draft').click();assert.equal(editor,null);assert.equal(stored.get(oldKey),raw);assert(!stored.has(key));
          assert(main.textContent.includes('could not be copied'));button(main,'Review draft from casual/test').click();
          stored.set(key,'another tab draft');button(latest().foot,'Use this draft').click();assert(main.textContent.includes('draft changed'));
          assert.equal(stored.get(oldKey),raw);assert.equal(stored.get(key),'another tab draft');
        """)

    def test_other_profiles_and_read_only_decks_do_not_offer_a_persons_old_draft(self):
        self.run_js(r"""
          stored.set('draft.user1.casual/test.target',oldDraft());location.hash='#/edit?id=casual%2Fnew-deck';
          openSavedDeckEditor(editView(),'target');assert(editor);assert(!main.textContent.includes('Choose a saved draft'));
          editor=null;stored.set('draft.matt.casual/test.target',oldDraft());openSavedDeckEditor(editView({may_save:false}),'target');
          assert(editor);assert(!main.textContent.includes('Choose a saved draft'));
        """)

    def test_stale_editor_write_has_an_explicit_recovery_link_and_keeps_its_original_id(self):
        self.run_js(r"""
          location.hash='#/edit?id=casual%2Ftest';startEditor({mode:'edit',view:editView({id:'casual/test',aliases:[]}),version:'target'});
          editor.lists.Deck[0].qty=5;const old=editor,err=new ApiError(409,'Renamed elsewhere',
            {canonical_id:'casual/new-deck',conflict:{reason:'renamed'}}),sheet=openDeckRetirementSheet({title:'Save'});
          assert(renamedEditorConflict(sheet,err));assert.equal(old.id,'casual/test');
          button(sheet.foot,'Keep draft and open current deck').click();assert(stored.has('draft.matt.casual/test.target'));
          assert.equal(parseHash().params.get('id'),'casual/new-deck');same(requests,[]);
        """)

    def test_no_rename_happens_after_cancel_or_a_permission_change(self):
        self.run_js(r"""
          let ctx=await ready();acknowledge(ctx);action(ctx,'Cancel').click();await sendRenameDeck(ctx);assert.equal(requests.length,1);
          ctx=await ready();acknowledge(ctx);state.may={admin:false,deck_spaces:['user2'],home_player:null};
          await sendRenameDeck(ctx);assert.equal(requests.length,2);
        """)

    def test_closing_a_confirmed_save_still_opens_its_new_address_after_success(self):
        self.run_js(r"""
          const ctx=await ready();acknowledge(ctx);const wait=held();answerWrite=()=>wait.promise;
          action(ctx,'Rename deck').click();await settle();ctx.sheet.close();wait.resolve({id:'casual/new-deck',title:'New Deck'});await settle();
          assert.equal(parseHash().params.get('id'),'casual/new-deck');assert.equal(parseHash().params.get('v'),'owned');assert.equal(state.library,null);
        """)

    def test_deck_and_history_entry_points_draw_canonical_links_and_keep_requested_tabs(self):
        self.run_js(r"""
          location.hash='#/deck?id=casual%2Ftest&v=owned&tab=cards&filter=missing';
          answerRead=async()=>{const data=makePage();data.summary.id='casual/new-deck';data.requested_id='casual/test';return data;};
          showDeck(parseHash().params,routeToken);await settle();assert.equal(parseHash().params.get('id'),'casual/new-deck');
          assert.equal(parseHash().params.get('tab'),'cards');assert.equal(deckScreen.data.summary.id,'casual/new-deck');
          location.hash='#/history?id=casual%2Ftest&v=owned';answerRead=async()=>({id:'casual/new-deck',title:'New Deck',
            retired:true,may_save:false,may_restore:true,retired_revision:9,revisions:[]});
          showHistory(parseHash().params,routeToken);await settle();assert.equal(parseHash().params.get('id'),'casual/new-deck');
          assert.equal(parseHash().params.get('v'),'owned');button(main,'Restore deck').click();assert.equal(latest().retirementContext.id,'casual/new-deck');
        """)

    def test_profile_change_closes_rename_conflicts_created_from_generic_save_sheets(self):
        self.run_js(r"""
          location.hash='#/edit?id=casual%2Ftest';startEditor({mode:'edit',view:editView({id:'casual/test',aliases:[]}),version:'target'});
          const old=openSheet('Save');showConflict(old,new ApiError(409,'Renamed',{canonical_id:'casual/new-deck',conflict:{reason:'renamed'}}));
          assert(old.closed);const tracked=latest();assert(deckRetirementSheets.has(tracked));drawWho();assert(tracked.closed);
        """)

    def test_reloading_after_a_race_cannot_silently_rebase_onto_a_different_id(self):
        self.run_js(r"""
          location.hash='#/edit?id=casual%2Ftest';startEditor({mode:'edit',view:editView({id:'casual/test',aliases:[]}),version:'target'});
          const old=editor;old.lists.Deck[0].qty=5;answerRead=async()=>editView();const sheet=openDeckRetirementSheet({title:'Save'});
          await reapplyLatest(sheet,null,null);assert.equal(editor,old);assert.equal(editor.id,'casual/test');
          assert(latest().body.textContent.includes('Nothing was saved'));same(requests,[]);
        """)

    def test_old_draft_choices_cannot_act_after_switching_person_or_navigating(self):
        self.run_js(r"""
          const raw=oldDraft(),key='draft.matt.casual/test.target';stored.set(key,raw);location.hash='#/edit?id=casual%2Fnew-deck';
          openSavedDeckEditor(editView(),'target');button(main,'Review draft from casual/test').click();const use=button(latest().foot,'Use this draft');
          state.profile={id:'user1'};use.click();assert.equal(editor,null);assert.equal(stored.get(key),raw);assert(!stored.has('draft.matt.casual/new-deck.target'));
          closeDeckRetirementSheets();
        """)
