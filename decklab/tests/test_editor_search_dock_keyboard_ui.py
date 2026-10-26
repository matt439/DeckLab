"""Nonmodal Dock keyboard ownership over invented, isolated UI fixtures."""
import unittest

from decklab.tests import test_editor_search_dock_ui as dock_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, 'Node.js is not installed')
class EditorSearchDockKeyboardTests(unittest.TestCase):
    run_js = dock_ui.EditorSearchDockUiTests.run_js

    def test_escape_yields_to_composition_handled_modifiers_repeat_and_shared_menu(self):
        self.run_js(r'''
          const ed=begin();openAddSheet();const dock=ed.dom.searchDock,dockSearchInput=ed.ac.input;dockSearchInput.focus();
          const press=extra=>dock.root.fire('keydown',{key:'Escape',target:dockSearchInput,...extra});
          for(const extra of [{defaultPrevented:true},{isComposing:true},{keyCode:229},{repeat:true},
            {ctrlKey:true},{metaKey:true},{altKey:true},{shiftKey:true},{getModifierState:key=>key==='AltGraph'}]) {
            const event=press(extra);assert(dock.open);assert.equal(event.defaultPrevented,Boolean(extra.defaultPrevented));
            assert.equal(document.activeElement,dockSearchInput);
          }
          dockSearchInput.editorComposing=true;assert(!press({}).defaultPrevented);assert(dock.open);dockSearchInput.editorComposing=false;
          const menu=openMenu(dock.close,[{text:'Existing action'}]);dock.close.focus();
          const owned=dock.root.fire('keydown',{key:'Escape',target:dock.close});assert(!owned.defaultPrevented);
          assert(dock.open&&menu.node.isConnected);menu.close();dockSearchInput.focus();
          const event=press({});assert(event.defaultPrevented);assert(!dock.open);
        ''')

    def test_nontext_dock_undo_uses_live_launcher_and_leaves_text_undo_native(self):
        self.run_js(r'''
          document.body.append(el('p',{id:'toast',role:'status'}));
          const ed=begin(),line=ed.lists.Deck[0];setQty(line.uid,5);
          // The shared runner stubs changed(); seed its real history side effect explicitly.
          recordHistory(ed);assert(ed.history.length>0);ownHistory();openAddSheet();
          const dock=ed.dom.searchDock,dockSearchInput=ed.ac.input,before=ed.history.length;dockSearchInput.focus();
          const text=document.fire('keydown',{key:'z',ctrlKey:true,target:dockSearchInput});assert(!text.defaultPrevented);
          assert.equal(line.qty,5);assert.equal(ed.history.length,before);assert(dock.open);
          for(const flag of ['saving','asking']) {
            ed[flag]=true;dock.close.focus();const event=document.fire('keydown',{key:'z',ctrlKey:true,target:dock.close});
            assert(event.defaultPrevented);assert.equal(line.qty,5);assert.equal(ed.history.length,before);ed[flag]=false;
          }
          dock.close.focus();const event=document.fire('keydown',{key:'z',metaKey:true,target:dock.close});
          assert(event.defaultPrevented);assert.equal(ed.lists.Deck[0].qty,4);assert(dock.disposed);
          assert.equal(document.activeElement,ed.dom.barParts.addCards);assert(document.activeElement.isConnected);
        ''')

    def test_dock_undo_focus_descriptor_never_reclaims_new_or_stale_owned_focus(self):
        self.run_js(r'''
          const ed=begin();openAddSheet();const dock=ed.dom.searchDock;dock.close.focus();
          const dockSavedValue=editorUndoFocus(ed);assert(dockSavedValue&&dockSavedValue.bar==='addCards');
          const outside=el('button');document.body.append(outside);outside.focus();
          restoreEditorUndoFocus(ed,dockSavedValue);assert.equal(document.activeElement,outside);
          dock.close.focus();routeToken++;restoreEditorUndoFocus(ed,dockSavedValue);assert.equal(document.activeElement,dock.close);
          routeToken--;const profile=state.profile;state.profile={id:'other'};
          restoreEditorUndoFocus(ed,dockSavedValue);assert.equal(document.activeElement,dock.close);state.profile=profile;
          const space=ed.space;ed.space='other';restoreEditorUndoFocus(ed,dockSavedValue);assert.equal(document.activeElement,dock.close);ed.space=space;
          dock.root.remove();assert.equal(editorUndoFocus(ed),null);
        ''')

    def test_ctrl_s_from_dock_runs_existing_save_now_and_takeover_with_mocked_write(self):
        self.run_js(r'''
          location.hash=editHref('casual/sample','target');const ed=begin();setQty(ed.lists.Deck[0].uid,5);ownHistory();openAddSheet();
          const dock=ed.dom.searchDock,dockSearchInput=ed.ac.input,expected=JSON.stringify(draftBody()),calls=[];
          const dockSavedValue=view({id:ed.id,title:ed.title,fields:{...ed.fields},sha256:'b'.repeat(64),
            lists:{target:structuredClone(ed.lists),owned:ed.view?.lists?.owned||null}});
          runCheck=async()=>({blocks:[],warnings:[],changes:{decklist:true,fields:[],prose:[]}});
          apiWrite=async(path,body)=>{calls.push({path,body});return {id:ed.id,title:ed.title,deck:dockSavedValue,changed:true,stale_tables:[]};};
          const realSave=saveNow;let pending;saveNow=options=>(pending=realSave(options));
          const modal=el('dialog',{open:''});document.body.append(modal);dockSearchInput.focus();
          assert(document.fire('keydown',{key:'s',ctrlKey:true,target:dockSearchInput}).defaultPrevented);assert.equal(calls.length,0);modal.remove();
          const event=document.fire('keydown',{key:'s',ctrlKey:true,target:dockSearchInput});assert(event.defaultPrevented);assert(pending);
          assert(document.fire('keydown',{key:'s',ctrlKey:true,target:dockSearchInput,repeat:true}).defaultPrevented);
          await pending;assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/deck/save');
          assert.equal(JSON.stringify(calls[0].body),expected);assert.notEqual(editor,ed);assert(dock.disposed);
          assert.equal(editor.lists.Deck[0].qty,5);assert.equal(history.state.sheet,undefined);assert.equal(keyboardDialog(),null);
        ''')
