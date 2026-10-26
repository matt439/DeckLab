"""Editor row presentation keeps original quantities, actions and section scope."""
import unittest

from decklab.tests import test_editor_ui as editor_ui, test_device_layout_ui as device_ui


class EditorRowStyleTests(unittest.TestCase):
    def test_actual_step_buttons_keep_44px_casual_targets_and_existing_lab_density(self):
        css = (editor_ui.WEB / 'editor.css').read_text(encoding='utf-8')
        lab = device_ui._block(css, '(min-width: 1000px) and (pointer: fine)')
        # The exact boundary includes fractional widths below 1000, with touch
        # targets at all widths. Lab list height inherits the shared token.
        self.assertIn('.edit-stepper { --stepper-h: inherit; }', lab)
        self.assertIn('.edit-tile .edit-stepper { --tap: 32px; --stepper-h: 34px; }', lab)
        self.assertNotIn('@media (pointer: fine) { .edit-row { --tap:', css)
        self.assertRegex(css, r'\.edit-stepper \{[^}]*--stepper-h:\s*46px;')
        self.assertIn('.edit-tile .edit-stepper { --tap: 44px; }', css)
        self.assertRegex(css, r'\.edit-tile \.edit-more \{[^}]*--tap:\s*44px;')
        shared = (editor_ui.WEB / 'components.css').read_text(encoding='utf-8')
        self.assertRegex(shared, r'\.stepper \.step \{[^}]*width:\s*calc\(var\(--stepper-h\) - 2px\);'
                                r'[^}]*height:\s*calc\(var\(--stepper-h\) - 2px\);')
        for width, pointer in ((393, 'fine'), (393, 'coarse'), (999.5, 'fine'),
                               (1000, 'fine'), (1000, 'coarse'), (2560, 'fine')):
            with self.subTest(width=width, pointer=pointer):
                dense = device_ui._matches('(min-width: 1000px) and (pointer: fine)',
                                          device_ui._device(width, 852, pointer))
                root_h = device_ui._tokens_on(device_ui._device(width, 852, pointer))['--stepper-h']
                group = int(root_h.removesuffix('px')) if dense else 46
                tile_group = 34 if dense else 46
                self.assertEqual(group - 2, 26 if dense else 44)
                self.assertEqual(tile_group - 2, 32 if dense else 44)
        self.assertRegex(css, r'\.edit-tile \.card-tile-chips \{[^}]*flex-wrap:\s*wrap;')
        self.assertIn('.edit-tile .card-tile-chips { flex-wrap: nowrap; }', lab)
        self.assertRegex(css, r'\.edit-sideboard \{[^}]*background:\s*var\(--surface-2\)')
        self.assertIn('.edit-sideboard > .section-title { color: var(--ink-2); }', css)


@unittest.skipUnless(editor_ui.NODE, "Node.js isn't installed")
class EditorRowInteractionTests(unittest.TestCase):
    def run_js(self, scenario):
        editor_ui.EditorPageTests().run_js(scenario)

    def test_sideboard_caption_uses_deck_kind_and_never_changes_main_count_or_companion(self):
        self.run_js(r"""
          const ed=edit();
          ed.lists.Sideboard=copyList({Sideboard:[{qty:3,name:'Lightning Bolt',card:bolt}]}).Sideboard;
          ed.lists.Companion=copyList({Companion:[{qty:1,name:'Ravenous Giant',card:giant}]}).Companion;
          ed.sections=['Deck','Sideboard','Companion'];
          ed.dom.lines=el('div');main.append(ed.dom.lines);
          const before=JSON.stringify(ed.lists), mainCopies=mainCount(ed.lists,'casual');
          drawLines();
          const side=ed.dom.lines.querySelector('[data-section="Sideboard"]');
          assert(side.matches('.edit-sideboard'));
          assert.equal(side.querySelector('.edit-sideboard-note').textContent,'Not counted in the 60.');
          assert.equal(side.querySelector('.count').textContent,'3');
          assert.equal(ed.dom.lines.querySelector('[data-section="Companion"]').querySelector('.edit-sideboard-note'),null);
          assert.equal(mainCount(ed.lists,'casual'),mainCopies);assert.equal(JSON.stringify(ed.lists),before);
          ed.kind='commander';ed.quick=true;drawLines();
          assert.equal(ed.dom.lines.querySelector('.edit-sideboard-note').textContent,'Not counted in the 100.');
          assert(!ed.dom.lines.textContent.includes('the 60'));
          ed.kind='unrecognised';drawLines();assert.equal(ed.dom.lines.querySelector('.edit-sideboard-note'),null);
        """)

    def test_removed_only_sideboard_keeps_band_zero_suppression_and_exact_undo_in_both_looks(self):
        self.run_js(r"""
          changed=()=>{};
          for (const look of ['list','visual']) {
            clear(main);const ed=edit();ed.look=look;
            ed.lists.Sideboard=copyList({Sideboard:[{qty:1,name:'Lightning Bolt',set:'abc',number:'7',finish:'foil',card:bolt}]}).Sideboard;
            const line=ed.lists.Sideboard[0], key=lineKey(line);ed.dom.lines=el('div');main.append(ed.dom.lines);drawLines();
            const side=ed.dom.lines.querySelector('[data-section="Sideboard"]');
            side.querySelector('.step-minus').focus();side.querySelector('.step-minus').click();
            assert.equal(ed.lists.Sideboard.length,0);assert.equal(ed.removed.length,1);
            drawLines();const removedSide=ed.dom.lines.querySelector('[data-section="Sideboard"]');
            assert(removedSide.matches('.edit-sideboard'));
            assert.equal(removedSide.querySelector('.count').textContent,'');
            assert.equal(removedSide.querySelector('.edit-sideboard-note').textContent,'Not counted in the 60.');
            const undo=removedSide.querySelector('.undo-btn');undo.focus();undo.click();
            assert.equal(ed.lists.Sideboard[0],line);assert.equal(lineKey(line),key);assert.equal(line.qty,1);
            assert.equal(ed.removed.length,0);assert.equal(document.activeElement.dataset.focus,`plus:${look==='visual'?'tile':'row'}:${line.uid}`);
          }
        """)

    def test_reordered_menu_preserves_all_moves_and_resolves_the_current_line(self):
        self.run_js(r"""
          const ed=edit();ed.kind='commander';ed.sections=['Commander','Deck','Sideboard','Companion'];
          const line=ed.lists.Deck[0], before=JSON.stringify(ed.lists), calls=[];
          let items;openMenu=(anchor,list)=>{items=list.filter(Boolean);};
          let offered=true;swapsAvailableFor=()=>offered;
          openSwapSheet=uid=>calls.push(['swap',uid]);openPrintings=uid=>calls.push(['print',uid]);
          moveLine=(uid,section)=>calls.push(['move',uid,section]);removeLine=uid=>calls.push(['remove',uid]);
          const button=rowMenuButton(line);button.click();
          same(items.filter(item=>typeof item==='object').map(item=>item.text.replace(/\u2026/g,'.')),
            ['Stand-ins.','Change printing.','Move to the Commander section','Move to the sideboard','Move to the companion','Remove']);
          for (const item of items) if(typeof item==='object') item.onclick();
          same(calls,[['swap',line.uid],['print',line.uid],['move',line.uid,'Commander'],
            ['move',line.uid,'Sideboard'],['move',line.uid,'Companion'],['remove',line.uid]]);
          assert.equal(JSON.stringify(ed.lists),before);
          // Existing menu buttons resolve the live section, rather than captured placement.
          ed.lists.Deck.shift();ed.lists.Sideboard=[line];offered=false;button.click();
          const labels=items.filter(item=>typeof item==='object').map(item=>item.text);
          assert(!labels.some(label=>label.startsWith('Stand-ins')));
          assert(!labels.includes('Move to the sideboard'));assert(labels.includes('Move to the 99'));
          assert.equal(items.at(-1).text,'Remove');assert.equal(items.at(-1).danger,true);
          ed.lists.Sideboard=[];const previous=items;button.click();assert.equal(items,previous);
        """)

    def test_row_and_picture_keep_quantity_limits_and_exact_viewer_metadata_without_requests(self):
        self.run_js(r"""
          changed=()=>{};let reads=0,writes=0;
          api=async()=>{reads++;throw Error('unexpected read');};apiWrite=async()=>{writes++;throw Error('unexpected write');};
          for (const look of ['list','visual']) {
            clear(main);const ed=edit();ed.look=look;ed.dom.lines=el('div');main.append(ed.dom.lines);drawLines();
            const line=ed.lists.Deck[0], row=ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`);
            const plus=row.querySelector('.step-plus'), minus=row.querySelector('.step-minus'), qty=row.querySelector('.qty-input');
            const trigger=row.querySelector('[data-viewer="editor"]'), metadata=viewerCards.get(trigger);
            assert.equal(metadata.card,line.card);assert.equal(metadata.caption,lineCaption(line,'Deck'));
            plus.click();assert.equal(line.qty,5);minus.click();assert.equal(line.qty,4);
            assert.equal(ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`),row);
            qty.value='99';qty.fire('input');assert.equal(line.qty,MAX_COPIES);
            assert.equal(row.querySelector('[data-viewer="editor"]'),trigger);
            if(look==='visual')assert.equal(row.getAttribute('data-copies'),'4');
          }
          assert.equal(reads,0);assert.equal(writes,0);
        """)
