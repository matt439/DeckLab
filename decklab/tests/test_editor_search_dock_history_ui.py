"""Separate stale-sheet-mark regression cases for the Dock history prerequisite."""
import unittest

from decklab.tests.test_workspace_ui import NODE
from decklab.tests import test_editor_search_dock_ui as dock_ui


@unittest.skipUnless(NODE, 'Node.js is not installed')
class EditorSearchDockHistoryTests(unittest.TestCase):
    def run_js(self, scenario):
        dock_ui.EditorSearchDockUiTests().run_js(scenario)

    def test_back_to_retired_dock_mark_preserves_saved_view_and_next_open_pushes_a_new_entry(self):
        self.run_js(r'''
          location.hash=editHref('casual/sample','target');const ed=begin(),h=ownHistory();
          history.replaceState({...history.state,unrelated:'preserve'},'');openAddSheet();const token=ed.dom.searchDock.entry.token;
          const review=openSheet('Save fixture');await savedFixture(ed,review);const current=editor,hash=location.hash;
          flushTimers();assert.equal(h.backs,0);assert.equal(entryPos(),2);
          history.back();assert.equal(history.state.sheet,token);window.fire('popstate');
          assert.equal(history.state.sheet,undefined);assert.equal(history.state.unrelated,'preserve');assert.equal(entryPos(),1);
          assert.equal(location.hash,hash);assert.equal(editor,current);assert.equal(current.pos,entryPos());const pushes=h.pushes;
          openAddSheet();assert.equal(h.pushes,pushes+1);assert.equal(editor.dom.searchDock.entry.pos,2);
          closeEditorSearchDock();flushTimers();assert.equal(current.pos,entryPos());
          history.back();window.fire('popstate');assert.equal(entryPos(),0);assert.equal(current.pos,entryPos());
          current.fields.archetype='Unsaved fixture';const steps=[];history.go=n=>steps.push(n);
          history.pushState({pos:1},'','#/library');assert(editorGuard(hash,location.hash));same(steps,[-1]);
        ''')

    def test_live_and_async_closing_overlay_marks_are_not_removed_until_exact_finish(self):
        self.run_js(r'''
          const closes=[];Node.prototype.showModal=function(){this.open=true;this.setAttribute('open','');};
          Node.prototype.close=function(){this.open=false;this.removeAttribute('open');closes.push(()=>this.fire('close'));};
          begin();ownHistory();openAddSheet();const dock=editor.dom.searchDock;
          const sheet=openSheet('Unrelated live sheet'),token=sheet.entry.token,pos=entryPos(),hash=location.hash;
          window.fire('popstate');assert.equal(history.state.sheet,token);assert.equal(entryPos(),pos);assert(dock.open);
          sheet.close();assert(!sheet.dialog.open&&!sheet.closed&&!sheet.entry.done);window.fire('popstate');
          assert.equal(history.state.sheet,token,'Native close has not finished, so the exact entry is still live');
          closes.shift()();assert(sheet.closed&&sheet.entry.done);window.fire('popstate');
          assert.equal(history.state.sheet,undefined);assert.equal(entryPos(),pos);assert.equal(location.hash,hash);assert(dock.open);
        ''')

    def test_immediate_close_to_paste_still_reuses_entry_before_deferred_back(self):
        self.run_js(r'''
          begin();const h=ownHistory();openAddSheet();const dock=editor.dom.searchDock,old=dock.entry.token;
          editorSearchPaste();assert.equal(h.pushes,1);assert.equal(entryPos(),1);assert.notEqual(history.state.sheet,old);
          assert(document.getElementById('paste-text'));assert.equal(sheetEntries.length,1);flushTimers();
          assert.equal(h.backs,0);assert.equal(entryPos(),1);assert(document.getElementById('paste-text'));
        ''')

    def test_stale_back_removes_only_sheet_and_keeps_other_marks_and_history_position(self):
        self.run_js(r'''
          begin();ownHistory();openAddSheet();const dock=editor.dom.searchDock;closeEditorSearchDock(dock);flushTimers();
          const fields={pos:7,sheet:987654,cardViewer:112,unrelated:{keep:true}},hash=location.hash;
          history.replaceState(fields,'');window.fire('popstate');
          same(history.state,{pos:7,cardViewer:112,unrelated:{keep:true}});assert.equal(location.hash,hash);
        ''')

    def test_landed_position_never_adopts_wrong_editor_scope_or_an_active_leave_save_flow(self):
        self.run_js(r'''
          for(const action of ['profile','route','hash','leaving','asking','saving','undo','detached']) {
            state.profile=state.profiles[1];const ed=begin();ownHistory();openAddSheet();closeEditorSearchDock();flushTimers();
            ed.pos=4;history.replaceState({pos:7,sheet:987654},'');
            if(action==='profile')state.profile={id:'other'};else if(action==='route')routeToken++;
            else if(action==='hash')location.hash='#/unrelated';else if(action==='undo')ed.undo={hash:location.hash};
            else if(action==='detached')ed.dom.page.remove();else ed[action]=true;
            window.fire('popstate');assert.equal(ed.pos,4,action);assert.equal(history.state.sheet,undefined);
          }
        ''')


if __name__ == '__main__':
    unittest.main()
