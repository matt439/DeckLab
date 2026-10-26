"""Box observations attach after ordinary current and alias draft choices, without changing them."""
import unittest

from decklab.tests import test_box_check_ui as boxes
from decklab.tests.test_box_editor_ui import SETUP
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class BoxEditorDraftUiTests(unittest.TestCase):
    def run_js(self, scenario):
        boxes.BoxCheckUiTests.run_js(self, SETUP + r'''
          const draftText=(view,version='target',quantity=5,extra={})=>JSON.stringify({v:1,saved:1000,sha256:view.sha256,starting:false,
            base:{lists:sendList(view.lists[version]),fields:pickFields(view.fields),prose:proseOf(view)},
            lists:{Deck:view.lists[version].Deck.map(line=>({...line,qty:quantity}))},fields:pickFields(view.fields),prose:proseOf(view),addSection:'Sideboard',...extra});
          const key=(id='casual/a',version='target')=>draftKey({mode:'edit',profile:'matt',id,version});
          const openWithDraft=async(view,version='target')=>{const made=await loadChoices(view);versionButton(made.sheet,version).click();enterChosen(view,version);return made;};
        ''' + scenario)

    def test_existing_current_address_draft_bytes_and_values_are_preserved_for_both_versions(self):
        self.run_js(r'''
          for(const version of ['target','owned']){
            const view=editorView(),raw=draftText(view,version,7);local.set(key('casual/a',version),raw);await openWithDraft(view,version);
            assert(editor);assert.equal(editor.lists.Deck[0].qty,7);assert.equal(editor.addSection,'Sideboard');assert.equal(local.get(key('casual/a',version)),raw);
            assert.equal(editor.notice.kind,'draft');assert(main.querySelector('.box-editor-note'));assert(main.textContent.includes('Unsaved changes from'));
            assert(editor.dirty);assert(!JSON.stringify(editor.fields).includes('Recorded Elf'));assert(!editor.prose.notes.includes('Recorded Elf'));
          }
        ''')

    def test_changed_source_draft_rebases_normally_and_retains_its_normal_warning_separately(self):
        self.run_js(r'''
          const view=editorView(),raw=draftText(view,'target',5,{sha256:'a'.repeat(64)});local.set(key(),raw);await openWithDraft(view);
          assert(editor);assert.equal(editor.lists.Deck[0].qty,5);assert.equal(editor.notice.kind,'draft-changed');assert.equal(local.get(key()),raw);
          assert(main.querySelector('.box-editor-note'));assert(main.textContent.includes('deck changed since then'));assert(!editor.notice.notes.includes('Recorded Elf'));
        ''')

    def test_alias_draft_requires_explicit_choice_then_context_attaches_after_normal_rebase(self):
        self.run_js(r'''
          const view=editorView({aliases:['casual/old-a']}),raw=draftText(view,'target',6,{sha256:'a'.repeat(64)});local.set(key('casual/old-a'),raw);
          await openWithDraft(view);assert.equal(editor,null);assert(main.textContent.includes('Choose a saved draft'));assert.equal(main.querySelector('.box-editor-note'),null);
          assert.equal(local.get(key('casual/old-a')),raw);assert.equal(local.get(key()),null);assert(boxEditorHandoff);
          button(main,'Review draft from casual/old-a').click();const sheet=[...deckRetirementSheets].at(-1);button(sheet.dialog,'Use this draft').click();await settle();
          assert(editor);assert.equal(editor.lists.Deck[0].qty,6);assert.equal(editor.notice.kind,'draft-changed');assert(main.querySelector('.box-editor-note'));
          assert.equal(local.get(key()),raw);assert.equal(local.get(key('casual/old-a')),null);assert.equal(boxEditorHandoff,null);
        ''')

    def test_current_draft_choice_preserves_both_current_and_alias_bytes(self):
        self.run_js(r'''
          const view=editorView({aliases:['casual/old-a']}),current=draftText(view,'target',8),old=draftText(view,'target',6);
          local.set(key(),current);local.set(key('casual/old-a'),old);await openWithDraft(view);assert.equal(editor,null);
          button(main,'Keep current-address draft').click();await settle();assert.equal(editor.lists.Deck[0].qty,8);assert(main.querySelector('.box-editor-note'));
          assert.equal(local.get(key()),current);assert.equal(local.get(key('casual/old-a')),old);assert.equal(editor.notice.kind,'draft');
        ''')

    def test_pending_alias_choice_cannot_transfer_context_or_drafts_after_profile_or_route_change(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash']){
            closeDeckRetirementSheets();editor=null;const view=editorView({aliases:['casual/old-a']}),raw=draftText(view,'target',6);local.remove(key());local.set(key('casual/old-a'),raw);
            await openWithDraft(view);button(main,'Review draft from casual/old-a').click();const sheet=[...deckRetirementSheets].at(-1),use=button(sheet.dialog,'Use this draft');
            if(mode==='profile')state.profile={...state.profile,id:'user1'};if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            use.fire('click');assert.equal(editor,null);assert.equal(local.get(key('casual/old-a')),raw);assert.equal(local.get(key()),null);assert.equal(main.querySelector('.box-editor-note'),null);
            boxEditorHandoff=null;
          }
        ''')

    def test_note_is_excluded_from_normal_draft_serialization_and_api_draft_body(self):
        self.run_js(r'''
          const view=editorView(),raw=draftText(view,'target',7);local.set(key(),raw);await openWithDraft(view);const ed=editor;
          assert(ed.boxObservation);assert(saveDraft(ed));const stored=JSON.parse(local.get(key()));assert.equal(stored.lists.Deck[0].qty,7);
          assert.equal(stored.boxObservation,undefined);assert.equal(stored.observation,undefined);assert(!JSON.stringify(stored).includes('recipe_sha256'));assert(!JSON.stringify(stored).includes('Recorded Elf'));
          assert(!JSON.stringify(draftBody()).includes('recipe_sha256'));assert(!JSON.stringify(draftBody()).includes('Recorded Elf'));
        ''')

    def test_read_only_or_stale_normal_editor_load_does_not_consume_or_overwrite_drafts(self):
        self.run_js(r'''
          const view=editorView(),raw=draftText(view,'target',7);local.set(key(),raw);const made=await loadChoices(view);versionButton(made.sheet,'target').click();
          enterChosen(editorView({may_save:false}));assert.equal(editor,null);assert.equal(local.get(key()),raw);assert.equal(main.querySelector('.box-editor-note'),null);
          assert(main.textContent.includes('Open a fresh box check'));
        ''')

    def test_context_never_attaches_to_other_start_editor_instances_or_new_versions(self):
        self.run_js(r'''
          const view=editorView(),made=await loadChoices(view);versionButton(made.sheet,'target').click();routeToken++;boxEditorRoute('edit',routeToken);clear(main);
          assert(boxEditorGuardView(view,'target',routeToken));startEditor({mode:'edit',view:{...view},version:'target'});
          assert.equal(editor.boxObservation,undefined);assert.equal(main.querySelector('.box-editor-note'),null);assert.equal(boxEditorHandoff,null);
        ''')


if __name__ == "__main__":
    unittest.main()
