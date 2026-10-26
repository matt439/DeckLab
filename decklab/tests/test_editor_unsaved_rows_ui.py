"""Saved-list row differences keep the original controls and exact printing context."""
import re
import unittest

from decklab.tests import test_editor_ui as editor_ui, test_quick_editor_ui as quick


REAL_CHANGED = re.search(r'(?ms)^function changed\(.*?^\}',
    (editor_ui.WEB / 'editor-screen.js').read_text(encoding='utf-8')).group(0)
SETUP = '\nchanged = ' + REAL_CHANGED + r''';
  function mountRows(ed) {
    clear(main);ed.dom.lines=el('div');main.append(ed.dom.lines);drawLines();return ed;
  }
  const rowFor = (ed,line) => ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`);
  const changedRow = row => row.classList.contains('is-unsaved');
'''


class UnsavedEditorRowSourceTests(unittest.TestCase):
    def test_scoped_dot_prior_count_and_removed_styles_preserve_both_widths(self):
        css = (editor_ui.WEB / 'editor.css').read_text(encoding='utf-8')
        self.assertRegex(css, r'\.edit-unsaved-dot \{[^}]*width: 8px;[^}]*height: 8px;'
                              r'[^}]*background: var\(--accent\);')
        self.assertRegex(css, r'\.edit-was \{[^}]*color: var\(--ink-2\);')
        self.assertIn('.edit-unsaved-dot[hidden], .edit-was[hidden] { display: none; }', css)
        self.assertIn('.removed-line { text-decoration: line-through; }', css)
        self.assertRegex(css, r'\.edit-removed \{[^}]*background: var\(--surface-2\);')
        self.assertRegex(css, r'@media \(min-width: 1000px\) \{\s*'
                              r':is\(\.edit-list, \.edit-stacks\) > \.edit-removed \{ '
                              r'background: transparent; border: 1px dashed var\(--border-strong\);')
        shared = (editor_ui.WEB / 'components.css').read_text(encoding='utf-8')
        self.assertIn('.stepper:is(.is-changed, [data-changed="true"]) { border-color: var(--accent); }', shared)
        self.assertIn('.edit-tile .card-tile-open > .edit-was { margin: 0; padding: 0 2px; }', css)
        cards = (editor_ui.WEB / 'cards-ui.css').read_text(encoding='utf-8')
        self.assertRegex(cards, r'\.card-tile-name \{[^}]*overflow: hidden;[^}]*-webkit-line-clamp: 2;')


@unittest.skipUnless(editor_ui.NODE, 'Node.js is not installed')
class UnsavedEditorRowInteractionTests(unittest.TestCase):
    def run_js(self, scenario):
        editor_ui.EditorPageTests.run_js(self, SETUP + scenario)

    def test_quantity_changes_update_retained_list_quick_and_picture_nodes_and_descriptions(self):
        self.run_js(r'''
          let reads=0,writes=0;api=async()=>{reads++;throw Error('unexpected read');};
          apiWrite=async()=>{writes++;throw Error('unexpected write');};
          for(const [look,compact] of [['list',false],['list',true],['visual',false]]) {
            const ed=edit();ed.look=look;ed.quick=compact;mountRows(ed);
            const line=ed.lists.Deck[0],row=rowFor(ed,line),p=row.editorChange;
            const trigger=p.trigger,input=row.querySelector('.qty-input'),plus=row.querySelector('.step-plus');
            const more=row.querySelector('.edit-more'),print=row.querySelector('.edit-print');
            const metadata=viewerCards.get(trigger),before=JSON.stringify(ed.base),history=ed.history.length;
            trigger.setAttribute('aria-describedby','existing-description');input.setAttribute('aria-describedby','existing-quantity');
            input.focus();plus.click();
            assert.equal(line.qty,5);assert.equal(rowFor(ed,line),row);assert(changedRow(row));
            assert(row.querySelector('.edit-stepper').classList.contains('is-changed'));
            assert(!p.dot.hidden);assert.equal(p.was.textContent,'was 4');assert(!p.was.hidden);
            assert.equal(p.description.textContent,'Unsaved change. Saved Deck: 4 copies of this printing.');
            assert.equal(trigger.getAttribute('aria-describedby'),`existing-description ${p.description.id}`);
            assert.equal(input.getAttribute('aria-describedby'),`existing-quantity ${p.description.id}`);
            assert.equal(row.editorChange,p);assert.equal(row.editorChange.trigger,trigger);
            assert.equal(row.querySelector('.qty-input'),input);assert.equal(row.querySelector('.step-plus'),plus);
            assert.equal(row.querySelector('.edit-more'),more);assert.equal(row.querySelector('.edit-print'),print);
            assert.equal(viewerCards.get(trigger),metadata);assert.equal(document.activeElement,input);
            assert.equal(JSON.stringify(ed.base),before);assert.equal(ed.history.length,history+1);
            row.querySelector('.step-minus').click();assert.equal(line.qty,4);assert(!changedRow(row));
            assert(p.dot.hidden&&p.was.hidden&&p.description.hidden);assert.equal(p.was.textContent,'');
            assert(!row.querySelector('.edit-stepper').classList.contains('is-changed'));
            assert.equal(trigger.getAttribute('aria-describedby'),'existing-description');
            assert.equal(input.getAttribute('aria-describedby'),'existing-quantity');
          }
          assert.equal(reads,0);assert.equal(writes,0);
        ''')

    def test_exact_section_set_number_and_finish_never_borrow_another_rows_prior_quantity(self):
        self.run_js(r'''
          const ed=edit();
          ed.base.lists=copyList({Deck:[
            {qty:4,name:elves.name,set:'fdn',number:'227',card:elves},
            {qty:2,name:elves.name,set:'m19',number:'314',finish:'foil',card:elves},
            {qty:1,name:elves.name,set:'m19',number:'314',finish:'etched',card:elves}],
            Sideboard:[{qty:3,name:elves.name,set:'fdn',number:'227',card:elves}]});
          ed.lists=copyList(ed.base.lists);mountRows(ed);
          const [normal,foil,etched]=ed.lists.Deck,side=ed.lists.Sideboard[0];
          setQty(foil.uid,3);assert(changedRow(rowFor(ed,foil)));
          assert.equal(rowFor(ed,foil).editorChange.was.textContent,'was 2');
          for(const line of [normal,etched,side])assert(!changedRow(rowFor(ed,line)));
          normal.number='228';changed();
          assert.equal(rowFor(ed,normal).editorChange.was.textContent,'was 0');
          assert(rowFor(ed,normal).editorChange.description.textContent.includes('0 copies of this printing'));
          ed.lists.Deck.splice(ed.lists.Deck.indexOf(etched),1);ed.lists.Sideboard.push(etched);changed();
          assert.equal(rowFor(ed,etched).editorChange.was.textContent,'was 0');
          assert(rowFor(ed,etched).editorChange.description.textContent.includes('Saved Sideboard'));
          assert(!changedRow(rowFor(ed,side)));
          // Explicit nonfoil and its omitted default are the existing same printing key.
          const savedNormal=ed.base.lists.Deck[0];normal.number=savedNormal.number;normal.finish='nonfoil';changed();
          assert(!changedRow(rowFor(ed,normal)));
        ''')

    def test_long_picture_name_keeps_prior_count_outside_clamp_and_retains_original_trigger(self):
        self.run_js(r'''
          const name='Invented Unindexed Fixture Card';
          for(const card of [null,{...elves,name}]) {
            const ed=edit();ed.look='visual';
            ed.base.lists=copyList({Deck:[{qty:4,name,set:'fixture',number:'44',card}]});
            ed.lists=copyList(ed.base.lists);mountRows(ed);
            const line=ed.lists.Deck[0],tile=rowFor(ed,line),p=tile.editorChange,trigger=p.trigger;
            const label=tile.querySelector('.card-tile-name'),meta=tile.querySelector('.card-tile-meta');
            const registered=viewerCards.get(trigger),input=tile.querySelector('.qty-input');input.focus();
            setQty(line.uid,5);
            assert(label.contains(p.dot));assert(!label.contains(p.was));assert(p.was.parentNode===trigger);
            assert(trigger.children.indexOf(p.was)>trigger.children.indexOf(label));
            assert(trigger.children.indexOf(p.was)>trigger.children.indexOf(meta));
            assert.equal(label.textContent,name);assert.equal(p.was.textContent,'was 4');assert(!p.was.hidden);
            assert(tile.editorChange.trigger===trigger&&tile.editorChange.was===p.was);
            assert(tile.querySelector('.qty-input')===input&&document.activeElement===input);
            assert.equal(trigger.getAttribute('aria-describedby'),p.description.id);
            assert.equal(p.was.getAttribute('aria-hidden'),'true');assert(viewerCards.get(trigger)===registered);
            if(card)assert.equal(registered.caption,lineCaption({...line,qty:4},'Deck'));
            else assert.equal(registered,undefined);
            setQty(line.uid,4);assert(p.was.hidden&&p.was.parentNode===trigger);assert.equal(label.textContent,name);
          }
        ''')

    def test_duplicate_exact_keys_use_aggregate_truth_and_suppress_ambiguous_was_labels(self):
        self.run_js(r'''
          const ed=edit(),raw={name:elves.name,set:'fdn',number:'227',card:elves};
          ed.base.lists=copyList({Deck:[{...raw,qty:2},{...raw,qty:3}]});
          ed.lists=copyList(ed.base.lists);mountRows(ed);
          const [a,b]=ed.lists.Deck;a.qty=1;b.qty=4;changed({list:false});
          assert(!changedRow(rowFor(ed,a)));assert(!changedRow(rowFor(ed,b)));
          setQty(a.uid,2);
          for(const line of [a,b]) {
            const p=rowFor(ed,line).editorChange;assert(changedRow(rowFor(ed,line)));
            assert(p.was.hidden);assert.equal(p.was.textContent,'');
            assert.equal(p.description.textContent,'Unsaved change. Saved Deck: 5 copies of this printing.');
          }
          // A unique current line still cannot claim a particular saved duplicate "was N".
          ed.lists=copyList({Deck:[{...raw,qty:6}]});changed();
          let p=rowFor(ed,ed.lists.Deck[0]).editorChange;assert(p.was.hidden);assert(!p.dot.hidden);
          // Nor can two current rows each claim the one saved line's old quantity.
          ed.base.lists=copyList({Deck:[{...raw,qty:5}]});
          ed.lists=copyList({Deck:[{...raw,qty:3},{...raw,qty:3}]});changed();
          for(const line of ed.lists.Deck)assert(rowFor(ed,line).editorChange.was.hidden);
        ''')

    def test_new_copy_and_unstarted_lists_never_claim_a_saved_baseline_but_trial_edits_can(self):
        self.run_js(r'''
          for(const changes of [{mode:'new'},{mode:'new',from:'product/illustrative'},
            {hasFileList:false},{starting:true},{version:'owned'},{view:{lists:{target:null}}}]) {
            const ed=Object.assign(edit(),changes);mountRows(ed);const line=ed.lists.Deck[0];
            line.qty=5;syncEditorRowChanges(ed);const p=rowFor(ed,line).editorChange;
            assert(!changedRow(rowFor(ed,line)));assert(p.dot.hidden&&p.was.hidden&&p.description.hidden);
            assert.equal(rowFor(ed,line).querySelector('.qty-input').getAttribute('aria-describedby'),null);
          }
          const ed=edit();ed.readOnly=true;ed.version='owned';ed.view.lists.owned=sendList(ed.base.lists);
          mountRows(ed);setQty(ed.lists.Deck[0].uid,5);
          assert.equal(rowFor(ed,ed.lists.Deck[0]).editorChange.was.textContent,'was 4');
          assert(changedRow(rowFor(ed,ed.lists.Deck[0])));
        ''')

    def test_fields_notes_and_unchanged_hydration_do_not_mark_rows_or_replace_controls(self):
        self.run_js(r'''
          const ed=edit();mountRows(ed);const line=ed.lists.Deck[0],row=rowFor(ed,line),trigger=row.editorChange.trigger;
          ed.fields.archetype='Illustrative new archetype';ed.prose.notes='A changed plan.';ed.markCurrent=true;
          changed({list:false});assert(!changedRow(row));assert.equal(rowFor(ed,line),row);
          syncEditorRowChanges(ed);syncEditorRowChanges(ed);
          assert.equal(row.querySelectorAll('.edit-unsaved-dot').length,1);
          assert.equal(row.querySelectorAll('.edit-was').length,1);assert.equal(row.editorChange.trigger,trigger);
          assert.equal(trigger.getAttribute('aria-describedby'),null);
          line.card={...line.card,img_small:'illustrative-art'};syncEditorRowChanges(ed);assert(!changedRow(row));
        ''')

    def test_order_only_dirty_state_remains_global_without_a_false_printing_quantity_change(self):
        self.run_js(r'''
          const ed=edit();mountRows(ed);ed.lists.Deck.reverse();
          const order=ed.lists.Deck.map(line=>line.uid);changed({list:false});
          assert(ed.dirty);assert(isDirty());same(ed.lists.Deck.map(line=>line.uid),order);
          for(const line of ed.lists.Deck) {
            const row=rowFor(ed,line);assert(!changedRow(row));assert(row.editorChange.dot.hidden);
          }
          syncEditorRowChanges(ed);assert(ed.dirty);assert(isDirty());
          same(ed.lists.Deck.map(line=>line.uid),order);
        ''')

    def test_original_remove_and_undo_preserve_the_prior_diff_and_exact_callbacks_in_both_looks(self):
        self.run_js(r'''
          for(const look of ['list','visual']) {
            const ed=edit();ed.look=look;mountRows(ed);const line=ed.lists.Deck[0],key=lineKey(line);
            setQty(line.uid,5);const row=rowFor(ed,line);
            // This DOM double doesn't reflect classList.add() into its selector attribute map.
            if(look==='visual')row.setAttribute('class',`${row.getAttribute('class')} edit-row edit-tile`);
            row.querySelector('.step-minus').focus();removeLine(line.uid);
            const stub=ed.dom.lines.querySelector(`[data-removed="${line.uid}"]`),undo=stub.querySelector('.undo-btn');
            assert.equal(stub.querySelector('.removed-line').textContent,`5 ${line.name} (${printingText(line)})`);
            assert.equal(stub.querySelector('.removed-word').textContent,'Removed');
            assert(document.activeElement===undo,'original removal focuses its retained Undo');
            assert.equal(stub.style.minHeight,'44px');undo.click();
            assert.equal(ed.lists.Deck.find(item=>item.uid===line.uid),line);assert.equal(lineKey(line),key);
            const again=rowFor(ed,line);assert(changedRow(again));assert.equal(again.editorChange.was.textContent,'was 4');
            assert.equal(viewerCards.get(again.editorChange.trigger).caption,lineCaption(line,'Deck'));
            assert(document.activeElement===again.querySelector('.step-plus'),'original Undo restores quantity focus');
            setQty(line.uid,4);assert(!changedRow(again));assert.equal(ed.removed.length,0);
          }
        ''')

    def test_unknown_card_keeps_original_nonviewer_name_and_truthful_saved_printing_diff(self):
        self.run_js(r'''
          const ed=edit(),raw={qty:2,name:'An unreadable illustrative card',set:'fixture',number:'9'};
          ed.base.lists=copyList({Deck:[raw]});ed.lists=copyList(ed.base.lists);mountRows(ed);
          const line=ed.lists.Deck[0],row=rowFor(ed,line),trigger=row.editorChange.trigger;
          assert.equal(viewerCards.get(trigger),undefined);setQty(line.uid,3);
          assert.equal(row.editorChange.was.textContent,'was 2');assert(!row.editorChange.dot.hidden);
          assert.equal(row.querySelector('.nm-text').textContent,line.name);
          assert(row.querySelector('.edit-problem').textContent.includes('kept as written'));
          assert.equal(viewerCards.get(trigger),undefined);
        ''')

    def test_draft_restore_rebase_and_undo_use_the_latest_real_saved_baseline(self):
        quick.QuickEditorUiTests.run_js(self, '\nchanged = ' + REAL_CHANGED + r''';
          const original=view();let ed=begin({}, {restoreDraft:false}),line=ed.lists.Deck[0];
          setQty(line.uid,5);assert(saveDraft(ed));
          startEditor({mode:'edit',view:original,version:'target'});ed=editor;line=ed.lists.Deck[0];
          let row=ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`);
          assert.equal(row.editorChange.was.textContent,'was 4');assert(!row.editorChange.dot.hidden);
          const mine=JSON.parse(snapshot(ed)),oldBase=ed.base,latest=view();latest.lists.target.Deck[0].qty=3;
          rebase(ed,latest,mine,oldBase);drawLines();line=ed.lists.Deck[0];row=ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`);
          assert.equal(line.qty,4);assert.equal(row.editorChange.was.textContent,'was 3');
          assert.equal(ed.base.lists.Deck[0].qty,3);
          // Undo rebuilds fresh uids; decoration is recomputed rather than retained from the prior row.
          ed.history=[];ed.snap=snapshot(ed);setQty(line.uid,5);undoLast();line=editor.lists.Deck[0];
          row=editor.dom.lines.querySelector(`[data-uid="${line.uid}"]`);assert.equal(line.qty,4);
          assert.equal(row.editorChange.was.textContent,'was 3');
          const old=editor,oldRow=row;startEditor({mode:'edit',view:original,version:'target',restoreDraft:false});
          const previous=oldRow.editorChange.was.textContent;old.lists.Deck[0].qty=70;syncEditorRowChanges(old);
          assert.equal(oldRow.editorChange.was.textContent,previous);
          assert(editor.dom.lines.querySelectorAll('.edit-unsaved-dot').every(dot=>dot.hidden));
        ''')
