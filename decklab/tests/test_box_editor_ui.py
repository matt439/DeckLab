"""A named box observation accompanies an explicit existing intended-list editor only."""
import unittest

from decklab.tests import test_box_check_ui as boxes
from decklab.tests.test_workspace_ui import NODE


SETUP = r'''
  editor=null;scheduleCheck=()=>{};
  const editorView=(extra={})=>({id:'casual/a',space:'home',kind:'casual',title:'Elves',sha256:'b'.repeat(64),editable:true,may_save:true,
    sections:['Deck','Sideboard'],fields:{title:'Elves',status:'built',player:'either',built_version:'owned'},field_text:{},editable_fields:[],
    lists:{target:{Deck:[{qty:2,name:'Alpha',card:alpha}]},owned:{Deck:[{qty:3,name:'Beta',card:beta}]}},prose:{notes:'Existing notes.',substitutes:''},aliases:[],...extra});
  const listActions=sheet=>sheet.body.querySelectorAll('.box-editor-open');
  const versionButton=(sheet,version)=>sheet.body.querySelectorAll('.box-editor-version').find(node=>node.dataset.version===version);
  const observation=(extra={})=>({id:'casual/a',title:'Elves',deck_sha256:'b'.repeat(64),recipe_sha256:'d'.repeat(64),section:'Deck',kind:'card',
    name:'Recorded Elf',for:null,direction:'missing',quantity:1,...extra});
  const listReview=async()=>{const made=await openBox();allFound(made.sheet);found(made.sheet,2,'1');reviewButton(made.sheet).click();return made;};
  const loadChoices=async(view=editorView())=>{const made=await listReview();const reads=[];api=async path=>{reads.push(path);return view;};
    listActions(made.sheet)[0].click();await settle();return{...made,reads,view};};
  const enterChosen=(view,version='target')=>{routeToken++;boxEditorRoute('edit',routeToken);clear(main);editor=null;
    if(boxEditorGuardView(view,version,routeToken))openSavedDeckEditor(view,version);return editor;};
'''


@unittest.skipUnless(NODE, "Node.js is not installed")
class BoxEditorUiTests(unittest.TestCase):
    def run_js(self, scenario):
        boxes.BoxCheckUiTests.run_js(self, SETUP + scenario)

    def test_only_named_physical_differences_offer_list_review_without_anonymous_target_lookup(self):
        self.run_js(r'''
          const {sheet}=await openBox();allFound(sheet);found(sheet,2,'1');found(sheet,4,'0');found(sheet,5,'0');reviewButton(sheet).click();
          same(listActions(sheet).map(node=>node.getAttribute('aria-label')),['Review a deck list: Recorded Elf (Deck, missing)',
            'Review a deck list: Named physical marker (Deck, missing)']);assert(sheet.body.textContent.includes('Identify this physical stand-in first'));
          assert(!listActions(sheet).some(node=>node.getAttribute('aria-label').includes('Missing spell')));
          assert.equal(boxEditorObservation({id:'casual/a',title:'Elves'},{meta:boxMeta()},{section:'Deck',kind:'marker',name:null,for:'Target',quantity:1},'missing'),null);
        ''')

    def test_fresh_source_offers_both_existing_versions_without_default_destination_or_write(self):
        self.run_js(r'''
          const {sheet,reads}=await loadChoices();let writes=0;apiWrite=async()=>{writes++;};same(reads,['/api/deck/edit?id=casual%2Fa']);
          assert(versionButton(sheet,'target'));assert(versionButton(sheet,'owned'));assert(sheet.body.textContent.includes('discards its local counts and extras'));
          assert(sheet.body.textContent.includes('A check date is saved only with Save check date'));assert.equal(location.hash,'#/assembly');assert.equal(boxEditorHandoff,null);assert.equal(writes,0);
        ''')

    def test_missing_owned_version_is_not_created_or_offered(self):
        self.run_js(r'''
          const view=editorView({lists:{target:editorView().lists.target,owned:null}}),{sheet}=await loadChoices(view);
          assert(versionButton(sheet,'target'));assert.equal(versionButton(sheet,'owned'),undefined);assert.equal(sheet.body.querySelectorAll('.box-editor-version').length,1);
          assert.equal(boxEditorExistingVersion(view,'owned'),false);
        ''')

    def test_wrong_source_permission_or_unreadable_lists_leave_counts_in_place_without_navigation(self):
        self.run_js(r'''
          for(const extra of [{id:'casual/other'},{sha256:'c'.repeat(64)},{title:'Different'},{editable:false},{may_save:false},{may_save:'true'},
            {space:'user2'},{kind:'commander'},{lists:{target:null,owned:null}}]){
            const {sheet}=await loadChoices(editorView(extra));assert.equal(sheet.body.querySelectorAll('.box-editor-version').length,0,JSON.stringify(extra));
            assert(!sheet.closed);assert.equal(location.hash,'#/assembly');assert.equal(nums(sheet)[2].value,'1');
          }
          const {sheet}=await listReview();api=async()=>{throw new ApiError(503,'Unavailable');};listActions(sheet)[0].click();await settle();
          assert.equal(sheet.body.querySelectorAll('.box-editor-version').length,0);assert(!sheet.closed);assert(dateButton(sheet));
        ''')

    def test_deck_edit_permission_is_separate_from_collection_permission(self):
        self.run_js(r'''
          const {sheet}=await listReview();state.may={admin:false,spaces:['home'],see_inventory:['home'],see_home_records:true,deck_spaces:[],home_player:'wife'};
          api=async()=>editorView({fields:{status:'built',player:'user'}});listActions(sheet)[0].click();await settle();assert.equal(sheet.body.querySelectorAll('.box-editor-version').length,0);
          assert.equal(location.hash,'#/assembly');assert(sheet.body.querySelector('.box-collection-open'));
        ''')

    def test_choice_carries_one_frozen_observation_and_preserves_recipe_kit_ticks_and_date(self):
        self.run_js(r'''
          const {sheet,view,data}=await loadChoices(),recipe=JSON.stringify(view.selected),kit=view.buildKit={fixture:'keep'},keptTicks=JSON.stringify([...serverTicks]);let writes=0;
          apiWrite=async()=>{writes++;};versionButton(sheet,'owned').click();assert(sheet.closed);assert.equal(location.hash,editHref('casual/a','owned'));
          same(boxEditorHandoff.observation,observation());assert(Object.isFrozen(boxEditorHandoff.observation));assert.equal(boxEditorHandoff.version,'owned');
          assert.equal(JSON.stringify(view.selected),recipe);assert.equal(view.buildKit,kit);assert.equal(JSON.stringify([...serverTicks]),keptTicks);assert.equal(data.decks[0].box_check.checked_on,null);
          assert.equal(writes,0);assert(!location.hash.includes('Recorded'));assert(!location.hash.includes('missing'));
        ''')

    def test_normal_editor_load_and_banner_do_not_alter_lists_quantities_sections_prose_or_dirty_state(self):
        self.run_js(r'''
          const view=editorView(),before=JSON.stringify(view),{sheet}=await loadChoices(view);versionButton(sheet,'target').click();const ed=enterChosen(view);
          assert(ed);assert.equal(ed.version,'target');assert.equal(ed.lists.Deck[0].qty,2);assert.equal(ed.addSection,'Deck');assert.equal(ed.prose.notes,'Existing notes.');assert(!ed.dirty);
          const note=main.querySelector('.box-editor-note');assert(note);assert(note.textContent.includes('Deck; missing 1 x Recorded Elf'));
          assert(note.textContent.includes('You chose the Planned list'));assert(note.textContent.includes('saved Assembled contents as recorded'));assert.equal(JSON.stringify(view),before);assert.equal(boxEditorHandoff,null);
        ''')

    def test_ordinary_editor_read_rejects_stale_source_missing_version_and_permission_before_drafts(self):
        self.run_js(r'''
          for(const extra of [{sha256:'c'.repeat(64)},{may_save:false},{lists:{target:null,owned:null}}]){
            const {sheet}=await loadChoices();versionButton(sheet,'target').click();const ed=enterChosen(editorView(extra));assert.equal(ed,null);
            assert(main.textContent.includes('Open a fresh box check'));assert.equal(main.querySelector('.box-editor-note'),null);assert.equal(boxEditorHandoff,null);
          }
        ''')

    def test_late_preflight_and_changed_counts_profile_route_or_modal_cannot_navigate(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','counts','modal','closed']){
            const {sheet}=await listReview();let finish,top;api=()=>new Promise(done=>finish=done);listActions(sheet)[0].click();
            assert(dateButton(sheet).disabled);if(mode==='profile')state.profile={...state.profile,id:'user1'};if(mode==='route')routeToken++;
            if(mode==='hash')location.hash='#/library';if(mode==='counts')nums(sheet)[2].value='2';if(mode==='modal')top=openSheet('Other task');if(mode==='closed')sheet.close();
            finish(editorView());await settle();assert.equal(sheet.body.querySelectorAll('.box-editor-version').length,0,mode);assert.equal(boxEditorHandoff,null);top?.close();
          }
        ''')

    def test_old_version_buttons_cannot_choose_after_context_source_or_owner_changes(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','counts','detached']){
            const {sheet}=await loadChoices();const open=versionButton(sheet,'target');if(mode==='profile')state.profile={...state.profile,id:'user1'};
            if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';if(mode==='counts')nums(sheet)[2].value='2';if(mode==='detached')open.remove();
            open.fire('click');assert.equal(boxEditorHandoff,null);assert(!sheet.closed);
          }
        ''')

    def test_back_to_counts_discards_old_choices_and_new_review_uses_current_observation(self):
        self.run_js(r'''
          const {sheet}=await loadChoices(),old=versionButton(sheet,'target');button(sheet.dialog,'Back to counts').click();found(sheet,2,'0');reviewButton(sheet).click();
          old.fire('click');assert.equal(boxEditorHandoff,null);assert(!old.isConnected);assert.equal(sheet.body.querySelectorAll('.box-editor-version').length,0);
          api=async()=>editorView();listActions(sheet)[0].click();await settle();versionButton(sheet,'owned').click();assert.equal(boxEditorHandoff.observation.quantity,2);
        ''')

    def test_ignored_preflight_after_nested_modal_still_releases_original_busy_controls_for_retry(self):
        self.run_js(r'''
          const {sheet}=await listReview();let finish;api=()=>new Promise(done=>finish=done);listActions(sheet)[0].click();assert(dateButton(sheet).disabled);
          const top=openSheet('Other task');finish(editorView());await settle();assert.equal(sheet.body.querySelectorAll('.box-editor-version').length,0);top.close();
          assert(!dateButton(sheet).disabled);assert(!listActions(sheet)[0].disabled);api=async()=>editorView();listActions(sheet)[0].click();await settle();assert(versionButton(sheet,'target'));
        ''')

    def test_arrival_and_context_expire_after_another_profile_route_or_editor_source(self):
        self.run_js(r'''
          const {sheet}=await loadChoices();versionButton(sheet,'target').click();const ed=enterChosen(editorView());assert(main.querySelector('.box-editor-note'));
          for(const mode of ['sha','viewsha','changed','gone']){
            const oldSha=ed.sha256,oldViewSha=ed.view.sha256;ed.check=null;ed.gone=null;ed.sha256=oldSha;ed.view.sha256=oldViewSha;
            if(mode==='sha')ed.sha256='c'.repeat(64);if(mode==='viewsha')ed.view.sha256='c'.repeat(64);if(mode==='changed')ed.check={file_changed:true};if(mode==='gone')ed.gone={message:'Gone'};
            assert.equal(boxEditorContextBanner(ed),null);ed.sha256=oldSha;ed.view.sha256=oldViewSha;ed.check=null;ed.gone=null;
          }
          const raw=JSON.stringify(sendList(ed.lists));button(main,'Dismiss box observation').click();assert.equal(main.querySelector('.box-editor-note'),null);assert.equal(JSON.stringify(sendList(ed.lists)),raw);assert(!ed.dirty);
          boxEditorNavigate(Object.freeze(observation()),'target');location.hash='#/library';boxEditorRoute('library',++routeToken);assert.equal(boxEditorHandoff,null);
        ''')

    def test_named_marker_is_context_only_and_unknown_extra_never_autofills_editor_search(self):
        self.run_js(r'''
          const {sheet}=await openBox();allFound(sheet);found(sheet,4,'0');reviewButton(sheet).click();api=async()=>editorView();listActions(sheet)[0].click();await settle();
          versionButton(sheet,'target').click();const ed=enterChosen(editorView());assert(main.querySelector('.box-editor-note').textContent.includes('Named physical marker (marked for Represented spell)'));
          assert.equal(ed.lists.Deck[0].name,'Alpha');assert.equal(ed.lists.Deck[0].qty,2);assert.equal(ed.addSection,'Deck');assert(!ed.dirty);
        ''')

    def test_check_date_save_invalidates_old_choices_and_new_read_uses_returned_current_sha(self):
        self.run_js(r'''
          const {sheet}=await loadChoices(),old=versionButton(sheet,'target');apiWrite=async()=>boxAnswer({found_cards:28,
            missing:[{section:'Deck',kind:'card',name:'Recorded Elf',for:null,quantity:1}]});dateButton(sheet).click();await settle();
          assert(button(sheet.dialog,'Done'));old.fire('click');assert.equal(boxEditorHandoff,null);assert.equal(location.hash,'#/assembly');
          api=async()=>editorView({sha256:'c'.repeat(64)});listActions(sheet)[0].click();await settle();versionButton(sheet,'owned').click();
          assert.equal(boxEditorHandoff.observation.deck_sha256,'c'.repeat(64));assert.equal(boxEditorHandoff.version,'owned');
        ''')


if __name__ == "__main__":
    unittest.main()
