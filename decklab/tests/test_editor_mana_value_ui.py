"""Mana-value presentation sorts retained rows without changing draft or request order."""
import unittest

from decklab.tests import test_editor_ui as editor_ui


@unittest.skipUnless(editor_ui.NODE, 'Node.js is not installed')
class EditorManaValueTests(unittest.TestCase):
    def run_js(self, scenario):
        editor_ui.EditorPageTests.run_js(self, r'''
          function mountManaRows() {
            const ed=edit();
            ed.lists=copyList({Deck:[
              {qty:1,name:'Large',card:{...elves,name:'Large',cmc:9,mana_cost:'{7}{G}{G}'}},
              {qty:2,name:'Zero',card:{...elves,name:'Zero',cmc:0}},
              {qty:3,name:'Fraction',card:{...elves,name:'Fraction',cmc:0.5}},
              {qty:1,name:'Unknown',card:{...elves,name:'Unknown',cmc:null}},
              {qty:1,name:'Also zero',card:{...elves,name:'Also zero',cmc:0}}],
              Sideboard:[{qty:2,name:'Side',card:{...bolt,name:'Side',cmc:2}}]});
            drawEditor();return ed;
          }
          const rowsOf=ed=>[...ed.dom.lines.querySelector('.edit-list').children];
          const namesOf=ed=>rowsOf(ed).map(row=>row.editorChange?.line.name
            || ed.removed.find(g=>String(g.uid)===row.dataset.removed).line.name);
        ''' + scenario)

    def test_numeric_values_unknowns_and_cost_are_distinct_and_sort_within_groups(self):
        self.run_js(r'''
          const ed=mountManaRows();
          same(namesOf(ed),['Also zero','Zero','Fraction','Large','Unknown']);
          const large=rowsOf(ed).find(row=>row.editorChange.line.name==='Large');
          assert(large.querySelector('.cost'));assert.equal(large.querySelector('.edit-mv').textContent,'9Mana value 9');
          assert(rowsOf(ed).at(-1).querySelector('.edit-mv').textContent.includes('Mana value not recorded'));
          assert.equal(ed.dom.mvSort.textContent,'MV ↑');assert(ed.dom.mvSort.getAttribute('aria-label').startsWith('MV: mana value'));
          ed.dom.mvSort.click();same(namesOf(ed),['Large','Fraction','Also zero','Zero','Unknown']);
          assert.equal(ed.dom.mvSort.textContent,'MV ↓');
          assert.equal(ed.dom.lines.querySelector('[data-section="Sideboard"]').querySelector('.nm-text').textContent,'Side');
          for(const value of [null,undefined,'2',NaN,Infinity,-1]) {
            assert.equal(editorManaValue({card:{cmc:value}}),null);
            assert(compareEditorLines({name:'Unknown',card:{cmc:value}},{name:'Large',card:{cmc:100}})>0);
          }
          assert.equal(editorManaValue({card:{cmc:0}}),0);assert.equal(editorManaValue({card:{cmc:0.5}}),0.5);
        ''')

    def test_sort_keeps_original_controls_metadata_pending_input_and_payload(self):
        self.run_js(r'''
          const ed=mountManaRows(),original=rowsOf(ed),line=ed.lists.Deck[0];
          const row=original.find(node=>node.editorChange.line===line),input=row.querySelector('.qty-input');
          const trigger=row.querySelector('.edit-card'),meta=viewerCards.get(trigger),before=JSON.stringify(draftBody());
          const lists=JSON.stringify(ed.lists),base=JSON.stringify(ed.base),history=ed.history.length,removed=ed.removed;
          const sections=[...ed.dom.lines.children];ed.sent={Deck:ed.lists.Deck.map(line=>line.uid)};
          const sent=JSON.stringify(ed.sent);input.focus();input.value='0';
          // Fail if the active row is ever detached, before any final focus repair.
          const append=row.parentNode.append.bind(row.parentNode),insert=row.parentNode.insertBefore.bind(row.parentNode);
          row.parentNode.append=(...nodes)=>{assert(!nodes.includes(row));append(...nodes);};
          row.parentNode.insertBefore=(node,at)=>{assert.notEqual(node,row);return insert(node,at);};
          ed.mvDescending=true;sortEditorRows(ed);
          same(namesOf(ed),['Large','Fraction','Also zero','Zero','Unknown']);
          assert.equal(document.activeElement,input);assert.equal(input.value,'0');
          for(const node of original)assert(rowsOf(ed).includes(node));
          assert.equal(row.querySelector('.edit-card'),trigger);assert.equal(viewerCards.get(trigger),meta);
          assert.equal(JSON.stringify(ed.lists),lists);assert.equal(JSON.stringify(ed.base),base);
          assert.equal(JSON.stringify(draftBody()),before);assert.equal(JSON.stringify(ed.sent),sent);
          assert.equal(ed.history.length,history);assert.equal(ed.removed,removed);
          assert(sections.every((node,i)=>ed.dom.lines.children[i]===node));
        ''')

    def test_removed_stub_sorts_and_undo_restores_the_exact_current_printing(self):
        self.run_js(r'''
          const ed=mountManaRows(),line=ed.lists.Deck[0];line.set='fdn';line.number='227';line.finish='foil';
          const key=lineKey(line);removeLine(line.uid);
          const stub=ed.dom.lines.querySelector('.edit-removed'),undo=stub.querySelector('.undo-btn');
          ed.dom.mvSort.click();assert.equal(rowsOf(ed)[0],stub);assert.equal(stub.querySelector('.undo-btn'),undo);
          undo.click();assert.equal(ed.lists.Deck.find(l=>l.uid===line.uid),line);assert.equal(lineKey(line),key);
          assert.equal(rowsOf(ed)[0].editorChange.line,line);assert.equal(ed.removed.length,0);
          drawEditor();assert.equal(ed.dom.mvSort.textContent,'MV ↓');assert.equal(rowsOf(ed)[0].editorChange.line,line);
        ''')

    def test_sort_control_is_list_only_and_retired_or_wrong_context_callbacks_do_nothing(self):
        self.run_js(r'''
          let ed=mountManaRows(),button=ed.dom.mvSort;
          for(const field of ['saving','asking','leaving']) {
            ed[field]=true;button.click();assert(!ed.mvDescending);ed[field]=false;
          }
          const profile=state.profile;state.profile={id:'other'};button.click();assert(!ed.mvDescending);state.profile=profile;
          const token=routeToken;routeToken++;button.click();assert(!ed.mvDescending);routeToken=token;
          button.remove();button.click();assert(!ed.mvDescending);
          drawEditor();button=ed.dom.mvSort;
          ed.look='visual';drawLookSwitch();drawLines();assert(button.hidden);button.click();assert(!ed.mvDescending);
          assert.equal(ed.dom.lines.querySelector('.edit-mv'),null);
          ed.look='list';ed.tab='notes';drawMain();assert(button.hidden);button.click();assert(!ed.mvDescending);
          ed.tab='cards';drawMain();assert(!button.hidden);
          ed.quick=true;drawEditor();assert.equal(ed.dom.mvSort,undefined);assert.equal(ed.dom.lines.querySelector('.edit-mv'),null);
        ''')

    def test_warning_request_indexes_stay_correct_after_visual_sort(self):
        self.run_js(r'''
          const ed=mountManaRows(),first=ed.lists.Deck[0],last=ed.lists.Deck[4];
          ed.sent={Deck:ed.lists.Deck.map(l=>l.uid)};
          ed.check={blocks:[{list:'target',section:'Deck',index:0,problem:'Blocked original first'}],
            warnings:['Warning original last'],warning_cards:[[last.name]]};
          ed.dom.mvSort.click();markRows();
          assert(ed.dom.lines.querySelector(`[data-uid="${first.uid}"]`).classList.contains('is-blocked'));
          assert(ed.dom.lines.querySelector(`[data-uid="${last.uid}"]`).classList.contains('is-warned'));
          assert.equal(ed.sent.Deck[0],first.uid);assert.equal(ed.sent.Deck[4],last.uid);
        ''')
