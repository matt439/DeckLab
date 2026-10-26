"""The existing Forge test action has one retained home outside replaceable Stats numbers."""
import unittest

from decklab.tests import test_editor_panes_ui as panes
from decklab.tests.test_workspace_ui import NODE


SETUP = r'''
  const presentationRequests=[];
  api=async path=>{presentationRequests.push(path);throw Error('Unexpected presentation read: '+path);};
  apiWrite=async path=>{presentationRequests.push(path);throw Error('Unexpected presentation write: '+path);};
  function swapDraft(ed) {
    ed.lists.Deck[0].qty-=1;ed.lists.Deck[1].qty+=1;
    drawLines();drawStats();drawBar();
  }
  function repaintDraft(ed,sections) {
    ed.lists=copyList(sections);drawLines();drawStats();drawBar();
  }
'''


@unittest.skipUnless(NODE, 'Node.js is not installed')
class EditorForgePanelTests(unittest.TestCase):
    def run_js(self, scenario):
        panes.EditorPanesUiTests.run_js(self, SETUP + scenario)

    def test_only_the_original_secondary_action_is_in_the_labelled_forge_panel(self):
        self.run_js(r'''
          const ed=full(),panel=ed.dom.forge,row=ed.dom.forgeTest,action=row.vt.button,reason=row.vt.why;
          assert(panel.isConnected&&ed.dom.panes.panels.stats.contains(panel));
          assert(panel.contains(row)&&row.contains(action)&&row.contains(reason));
          assert.equal(panel.getAttribute('aria-labelledby'),'h-editor-forge');
          assert.equal(panel.querySelector('#h-editor-forge').textContent,'Forge');
          assert(panel.hidden&&row.hidden);assert(!ed.dom.bar.contains(row));
          assert.equal(main.querySelectorAll('.vt-test-row').length,1);
          assert.equal(main.querySelectorAll('.vt-test-btn').length,1);
          assert(!action.classList.contains('btn-primary'));assert(ed.dom.barParts.save.classList.contains('btn-primary')===false);
          assert(!panel.querySelector('.wr')&&!panel.querySelector('.range-bar')&&!panel.querySelector('.fresh'));
          assert(!panel.textContent.includes('win rate'));assert.equal(presentationRequests.length,0);
        ''')

    def test_saved_list_eligibility_and_original_visible_reasons_are_unchanged(self):
        self.run_js(r'''
          const ed=full(),panel=ed.dom.forge,row=ed.dom.forgeTest,action=row.vt.button,reason=row.vt.why;
          const original=copyList(ed.base.lists);
          let draft=copyList(original);draft.Deck[0].set='other';repaintDraft(ed,draft);
          assert(panel.hidden&&row.hidden,'printing alone is not a playable-name change');
          draft=copyList(original);draft.Sideboard[0].qty+=1;repaintDraft(ed,draft);
          assert(!panel.hidden&&!row.hidden&&action.disabled);assert.equal(reason.textContent,VT_SIDEBOARD);assert(!reason.hidden);
          assert.equal(action.getAttribute('aria-describedby'),reason.id);
          draft=copyList(original);draft.Deck[0].qty-=1;repaintDraft(ed,draft);
          assert(!panel.hidden&&action.disabled);assert.equal(reason.textContent,VT_SIZE);assert(!reason.hidden);
          draft=copyList(original);draft.Deck[0].qty-=1;draft.Deck[1].qty+=1;repaintDraft(ed,draft);
          assert(!panel.hidden&&!row.hidden&&!action.disabled&&reason.hidden);
          assert(ed.dom.forge===panel&&ed.dom.forgeTest===row&&row.vt.button===action&&row.vt.why===reason);
          repaintDraft(ed,original);assert(panel.hidden&&row.hidden);
          assert.equal(presentationRequests.length,0);
        ''')

    def test_stats_check_and_density_updates_keep_the_same_focused_action_attached(self):
        self.run_js(r'''
          const ed=full(),ac=ed.ac,panel=ed.dom.forge,row=ed.dom.forgeTest,action=row.vt.button,reason=row.vt.why;
          swapDraft(ed);setSide('stats');action.focus();const body=JSON.stringify(draftBody()),history=ed.history.length;
          for(const refresh of [()=>drawStats(),()=>drawCheck(),()=>drawBar(),
            ()=>changed({list:false,history:false}),()=>width(false),()=>width(true)]) {
            refresh();assert(action.isConnected&&panel.contains(action)&&panel.contains(reason));
            assert(ed.dom.forge===panel&&ed.dom.forgeTest===row&&ed.ac===ac);
            assert(document.activeElement===action);assert.equal(ed.dom.barParts.test,row);
            assert.equal(main.querySelectorAll('.vt-test-row').length,1);assert(!ed.dom.bar.contains(row));
          }
          assert.equal(JSON.stringify(draftBody()),body);assert.equal(ed.history.length,history);
          const sheet=openSheet('Fixture overlay'),current=el('button',{type:'button',text:'Current modal action'});
          sheet.body.append(current);current.focus();drawStats();drawBar();assert(document.activeElement===current);
          sheet.close();assert.equal(presentationRequests.length,0);
        ''')

    def test_empty_stats_and_rejected_changes_keep_the_original_reason_without_new_results(self):
        self.run_js(r'''
          const ed=full(),panel=ed.dom.forge,row=ed.dom.forgeTest,reason=row.vt.why;
          repaintDraft(ed,{});assert(ed.dom.stats.textContent.includes('No cards in this draft'));
          assert(panel.isConnected&&!panel.hidden&&row.isConnected&&row.vt.why===reason);
          assert(row.vt.button.disabled&&!reason.hidden);assert.equal(reason.textContent,VT_SIZE);
          assert(!panel.querySelector('.fresh')&&!panel.querySelector('.wr'));
          assert.equal(presentationRequests.length,0);
        ''')

    def test_trial_versions_new_copy_quick_and_unstarted_modes_keep_the_original_scope(self):
        self.run_js(r'''
          for(const version of ['target','owned']) {
            const ed=full({may_save:false},{version});assert(ed.readOnly);swapDraft(ed);
            assert(ed.dom.forge.isConnected&&!ed.dom.forge.hidden&&!ed.dom.forgeTest.vt.button.disabled);
            assert(!ed.dom.barParts.save);assert.equal(main.querySelectorAll('.vt-test-btn').length,1);
          }
          startEditor({mode:'new',kind:'casual',restoreDraft:false});assert(editor.dom.forge.hidden&&editor.dom.forgeTest.hidden);
          startEditor({mode:'new',kind:'casual',from:'casual/source',view:view({new_deck:{kind:'casual',title:'Copied fixture'}}),restoreDraft:false});
          assert(editor.dom.forge.hidden&&editor.dom.forgeTest.hidden);
          const ed=full({lists:{target:structuredClone(list),owned:null}},{version:'owned'});
          assert(noOwnedList());assert(!ed.dom.forge&&!ed.dom.forgeTest&&!ed.dom.barParts.test);
          window.matchMedia('(min-width: 600px)').matches=false;begin({}, {restoreDraft:false});
          assert(editor.quick&&!editor.dom.forge&&!editor.dom.forgeTest&&!editor.dom.barParts.test);
          assert.equal(presentationRequests.length,0);
        ''')

    def test_action_keeps_its_existing_callback_and_presentation_never_starts_a_request(self):
        self.run_js(r'''
          const ed=full(),row=ed.dom.forgeTest,action=row.vt.button;swapDraft(ed);
          const body=JSON.stringify(draftBody()),history=ed.history.length,ac=ed.ac,seq=ac.seq;let opened=0;
          vtOpenTestSheet=()=>{opened++;};action.click();assert.equal(opened,1);
          for(let n=0;n<3;n++){drawStats();drawBar();}
          assert(row.vt.button===action&&ed.dom.forgeTest===row);action.click();assert.equal(opened,2);
          assert.equal(JSON.stringify(draftBody()),body);assert.equal(ed.history.length,history);assert.equal(ac.seq,seq);
          assert.equal(presentationRequests.length,0);
        ''')
