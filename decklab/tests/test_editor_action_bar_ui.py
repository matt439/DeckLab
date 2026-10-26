"""The retained editor bar reports saved intent and owns Undo/Discard across redraws."""
import unittest

from decklab.tests import test_editor_keyboard_ui as keyboard, test_editor_panes_ui as panes
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, 'Node.js is not installed')
class EditorActionBarTests(unittest.TestCase):
    def run_js(self, scenario):
        panes.EditorPanesUiTests.run_js(self, keyboard.FIXTURE + scenario)

    def test_change_groups_and_copy_deltas_keep_printing_fields_notes_and_marker_distinct(self):
        self.run_js(r'''
          const ed=full(),p=ed.dom.barParts,base=JSON.stringify(ed.base);
          assert(p.changes.hidden);assert(p.historyActions.hidden);assert(p.undo.disabled);assert(p.discard.hidden);
          setQty(ed.lists.Deck[0].uid,9);
          same(editorBarChangeSummary(ed),{count:1,added:5,removed:0});
          assert.equal(p.changeCount.textContent,'1 unsaved change');assert.equal(p.added.textContent,'+5');
          assert.equal(p.changeSpoken.textContent,'5 copies added, 0 copies removed.');
          ed.lists.Deck[0].number='228';ed.fields.archetype='New archetype';
          ed.prose.notes+='\n\nNew note.';ed.markCurrent=true;changed({list:false});
          same(editorBarChangeSummary(ed),{count:4,added:5,removed:0});
          assert.equal(p.changeCount.textContent,'4 unsaved changes');
          setQty(ed.lists.Deck[1].uid,54);
          same(editorBarChangeSummary(ed),{count:5,added:5,removed:2});
          assert.equal(p.removed.textContent,'−2');assert(!p.copySeparator.hidden);
          assert.equal(p.changeSpoken.textContent,'5 copies added, 2 copies removed.');
          assert.equal(JSON.stringify(ed.base),base);
        ''')

    def test_printing_only_order_only_split_rows_and_unknown_printing_finish_are_truthful(self):
        self.run_js(r'''
          let ed=full();ed.lists.Deck[0].number='228';changed({list:false});
          same(editorBarChangeSummary(ed),{count:1,added:0,removed:0});assert(ed.dom.barParts.changeCopies.hidden);
          ed=full();ed.lists.Deck.reverse();changed({list:false});
          same(editorBarChangeSummary(ed),{count:1,added:0,removed:0});assert.equal(ed.dom.barParts.changeCount.textContent,'1 unsaved change');
          ed=full();const line=ed.lists.Deck[0];line.qty=2;
          ed.lists.Deck.push(newLine({...line,qty:2}));changed({list:false});
          same(editorBarChangeSummary(ed),{count:1,added:0,removed:0});
          ed=full();ed.lists.Deck[1].finish='foil';changed({list:false});
          assert.equal(ed.lists.Deck[1].set,null); // Exact identity still changes even when printingText says Any printing.
          same(editorBarChangeSummary(ed),{count:1,added:0,removed:0});
        ''')

    def test_bar_parts_and_focus_survive_quantity_checks_notes_and_projection_updates(self):
        self.run_js(r'''
          const ed=full(),p=ed.dom.barParts,parts={...p};setQty(ed.lists.Deck[0].uid,5);p.undo.focus();
          const before=JSON.stringify(draftBody()),history=ed.history.length;
          ed.check={blocks:[],warnings:['Fixture warning'],warning_cards:[[elves.name]]};drawBar();
          width(false);width(true);ed.tab='notes';drawMain();drawBar();ed.tab='cards';drawMain();drawBar();
          assert.equal(ed.dom.barParts,p);for(const key of ['count','changes','changeCount','changeCopies','undo','discard','checks','addCards','save','saveMore','saveGroup'])assert(p[key]===parts[key]);
          assert(p.saveGroup.contains(p.save)&&p.saveGroup.contains(p.saveMore));
          assert.equal(document.activeElement,p.undo);assert.equal(JSON.stringify(draftBody()),before);assert.equal(ed.history.length,history);
          assert(p.save.classList.contains('btn-primary'));assert(!p.undo.classList.contains('btn-primary'));assert(!p.discard.classList.contains('btn-primary'));
        ''')

    def test_undo_uses_the_existing_history_and_recovers_fresh_owned_bar_focus(self):
        self.run_js(r'''
          const ed=full();setQty(ed.lists.Deck[0].uid,5);setQty(ed.lists.Deck[0].uid,6);
          let old=ed.dom.barParts.undo;old.focus();old.click();
          assert.equal(ed.lists.Deck[0].qty,5);assert.equal(ed.history.length,1);
          assert(document.activeElement===ed.dom.barParts.undo);assert(old!==ed.dom.barParts.undo);
          old=ed.dom.barParts.undo;old.click();assert.equal(ed.lists.Deck[0].qty,4);assert.equal(ed.history.length,0);
          assert(ed.dom.barParts.undo.disabled);assert(ed.dom.barParts.historyActions.hidden);
          assert(document.activeElement===document.getElementById('edit-tab-cards'));
        ''')

    def test_saved_discard_asks_once_and_keeps_or_reloads_through_the_existing_path(self):
        self.run_js(r'''
          let asked=[],removed=0,routed=0;
          removeDraft=()=>{removed++;return true;};route=()=>{routed++;};toast=()=>{};
          let ed=full();setQty(ed.lists.Deck[0].uid,5);const payload=JSON.stringify(draftBody());
          ask=async(title,paragraphs,choices)=>{asked.push({title,paragraphs,choices});return 'keep';};
          ed.dom.barParts.discard.click();await settle();assert.equal(asked.length,1);assert.equal(removed,0);assert.equal(routed,0);
          assert.equal(JSON.stringify(draftBody()),payload);assert.equal(asked[0].title,'Discard your changes?');
          assert(asked[0].paragraphs[0].includes("can't be undone"));
          ask=async()=> 'discard';ed.dom.barParts.discard.click();await settle();
          assert.equal(removed,1);assert.equal(routed,1);assert(ed.leaving);
        ''')

    def test_discard_confirmation_cannot_act_after_same_editor_scope_or_page_changes(self):
        self.run_js(r'''
          let removed=0;removeDraft=()=>{removed++;return true;};route=()=>{};toast=()=>{};
          for(const alter of [ed=>{ed.version='owned';},ed=>{ed.space='other';},ed=>{routeToken++;},
            ed=>{state.profile=state.profiles[0];},ed=>{ed.dom.page=el('div');},ed=>{ed.dom.barParts=null;}]) {
            state.profile=state.profiles[1];const ed=full();setQty(ed.lists.Deck[0].uid,5);
            let answer;ask=()=>new Promise(resolve=>answer=resolve);
            ed.dom.barParts.discard.click();assert(answer);alter(ed);answer('discard');await settle();assert.equal(removed,0);
          }
        ''')

    def test_stale_busy_hidden_modal_and_other_profile_actions_do_nothing(self):
        self.run_js(r'''
          const ed=full();setQty(ed.lists.Deck[0].uid,5);const p=ed.dom.barParts;let asks=0;ask=async()=>{asks++;return 'discard';};
          const before=JSON.stringify(draftBody()),history=ed.history.length;
          for(const field of ['saving','asking','leaving']) {ed[field]=true;p.undo.click();p.discard.click();ed[field]=false;}
          const profile=state.profile;state.profile=state.profiles[0];p.undo.click();p.discard.click();state.profile=profile;
          const token=routeToken;routeToken++;p.undo.click();p.discard.click();routeToken=token;
          const dialog=el('dialog',{open:true});main.append(dialog);p.undo.click();p.discard.click();dialog.remove();
          p.undo.remove();p.undo.click();p.discard.remove();p.discard.click();await settle();
          assert.equal(asks,0);assert.equal(JSON.stringify(draftBody()),before);assert.equal(ed.history.length,history);
        ''')

    def test_new_copy_unstarted_and_trial_editors_do_not_claim_a_saved_list_count_or_discard(self):
        self.run_js(r'''
          startEditor({mode:'new',kind:'casual',restoreDraft:false});let ed=editor;ed.fields.title='New';changed({list:false});
          assert.equal(editorBarChangeSummary(ed),null);assert.equal(ed.dom.barParts.changeCount.textContent,'Unsaved deck');assert(ed.dom.barParts.discard.hidden);
          startEditor({mode:'new',from:'casual/source',view:view({new_deck:{kind:'casual',title:'Copy'}}),restoreDraft:false});
          ed=editor;setQty(ed.lists.Deck[0].uid,5);assert.equal(editorBarChangeSummary(ed),null);assert(ed.dom.barParts.discard.hidden);
          ed=full({lists:{target:structuredClone(list),owned:null}},{version:'owned'});
          assert(noOwnedList());assert(ed.dom.barParts.changes.hidden);
          ed.prose.notes+='\n\nOnly shared notes changed.';changed({list:false});
          assert.equal(ed.dom.barParts.changeCount.textContent,'Unsaved changes');startOwned();
          assert.equal(editorBarChangeSummary(ed),null);assert.equal(ed.dom.barParts.changeCount.textContent,'Unsaved play-now list');assert(ed.dom.barParts.changeCopies.hidden);
          ed=full({may_save:false});setQty(ed.lists.Deck[0].uid,5);assert.equal(ed.dom.barParts.changeCount.textContent,'Trial changes');
          assert(ed.dom.barParts.discard.hidden);assert(!ed.dom.barParts.undo.disabled);assert(!ed.dom.barParts.save);
        ''')

    def test_new_deck_legitimate_space_change_rebinds_bar_actions_without_accepting_arbitrary_scope(self):
        self.run_js(r'''
          state.profile=state.profiles[0];state.may={admin:true,home_player:'user',see_inventory:['home'],
            create:[{space:'home',player:'user'},{space:'other',player:null}]};
          startEditor({mode:'new',kind:'casual',restoreDraft:false});const ed=editor;
          ed.fields.title='Before switch';changed({list:false});
          const group=document.getElementById('f-space').parentNode;
          const other=group.querySelectorAll('button').find(button=>button.dataset.space==='other');assert(other);other.click();
          assert.equal(ed.space,'other');assert.equal(ed.dom.barParts.owner.frame,keyboardEditorFrame(ed));
          ed.fields.title='After switch';changed({list:false});const old=ed.dom.barParts.undo;old.focus();old.click();
          assert.equal(ed.fields.title,'Before switch');assert.equal(ed.space,'other');
        ''')
