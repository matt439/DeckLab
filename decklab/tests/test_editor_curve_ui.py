"""Editor curves compare only a readable saved version, without changing edits or other Stats."""
import json
import re
import subprocess
import unittest

from decklab.tests import test_editor_panes_ui as panes
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = panes.SETUP + r'''
  toast=()=>{};
  const curve=()=>editor.dom.stats.querySelector('.edit-curve');
  const columns=()=>curve().querySelectorAll('.curve-col');
  const marks=()=>curve().querySelectorAll('.curve-before');
  const deltas=()=>curve().querySelectorAll('.curve-delta').map(node=>node.textContent).filter(Boolean);
  const one=(card,qty=1)=>({qty,name:card?.name||'Unknown fixture',card});
  const statsCopy=()=>{
    const s=listStats();return {curve:s.curve,lands:s.lands,spells:s.spells,total:s.total,average:s.average,
      types:[...s.types],sources:[...s.sources],colours:s.colours,identity:s.identity};
  };
'''


@unittest.skipUnless(NODE, 'Node.js is not installed')
class EditorCurveUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)],
            input=json.dumps([str(WEB), SETUP + scenario, True,
                {'innerWidth': 1000, 'innerHeight': 830, 'coarse': False,
                 'visual': {'width': 1000, 'height': 830}}]),
            capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'ok')

    def test_growth_shrink_and_removed_buckets_share_the_saved_scale_and_spoken_counts(self):
        self.run_js(r'''
          const two={...bolt,name:'Two mana fixture',cmc:2};
          const source={Deck:[one(elves,4),one(two,2),one(forest,9)]};
          const ed=full({lists:{target:source,owned:null}}), before=JSON.stringify(ed.base);
          assert.equal(marks().length,0);same(deltas(),[]);
          setQty(ed.lists.Deck[0].uid,6);removeLine(ed.lists.Deck[1].uid);
          same(deltas(),['+2','−2']);assert.equal(marks().length,2);
          assert(columns()[1].querySelector('.curve-before').matches('.is-grown'));
          assert(columns()[2].querySelector('.curve-before').matches('.is-shrunk'));
          assert.equal(columns()[1].querySelector('.curve-bar').getAttribute('style'),'height: 100.0%');
          assert.equal(columns()[1].querySelector('.curve-before').getAttribute('style'),'bottom: 66.7%');
          assert.equal(columns()[2].querySelector('.curve-before').getAttribute('style'),'bottom: 33.3%');
          assert.equal(columns()[2].querySelector('.curve-bar').getAttribute('style'),'height: 0.0%');
          const words=curve().getAttribute('aria-label');
          assert(words.startsWith('Spells by mana value: 0: 0, 1: 6, 2: 0'));
          assert(words.includes('saved planned list'));assert(words.includes('1: 4 saved, 6 now (2 more)'));
          assert(words.includes('2: 2 saved, 0 now (2 fewer)'));
          assert(columns().every(node=>node.getAttribute('aria-hidden')==='true'));
          assert(!ed.dom.stats.textContent.includes('better'));assert(!ed.dom.stats.textContent.includes('worse'));
          assert.equal(listStats().lands,9);assert.equal(listStats().spells,6);assert.equal(JSON.stringify(ed.base),before);
        ''')

    def test_actual_quantity_undo_and_render_keep_stats_roots_controls_payload_and_history(self):
        self.run_js(r'''
          const ed=full(),host=ed.dom.stats,ac=ed.ac,searchInput=ac.input,uid=ed.lists.Deck[0].uid;
          const plus=ed.dom.lines.querySelector(`[data-focus="plus:row:${uid}"]`),qty=ed.dom.lines.querySelector('.qty-input');
          plus.focus();plus.click();same(deltas(),['+1']);
          assert(ed.dom.stats===host&&ed.ac===ac&&ac.input===searchInput);
          assert(ed.dom.lines.querySelector(`[data-focus="plus:row:${uid}"]`)===plus);
          assert(ed.dom.lines.querySelector('.qty-input')===qty);assert(document.activeElement===plus);
          const payload=JSON.stringify(draftBody()),history=ed.history.length,seq=ed.checkSeq,numbers=JSON.stringify(statsCopy());
          let reads=0,writes=0;api=async()=>{reads++;throw Error('no curve reads')};apiWrite=async()=>{writes++;throw Error('no curve writes')};
          drawStats();drawStats();
          assert.equal(JSON.stringify(draftBody()),payload);assert.equal(ed.history.length,history);assert.equal(ed.checkSeq,seq);
          assert.equal(JSON.stringify(statsCopy()),numbers);assert.equal(document.activeElement,plus);same([reads,writes],[0,0]);
          assert(undoLast());same(deltas(),[]);assert.equal(marks().length,0);assert.equal(ed.lists.Deck[0].qty,4);
          assert(ed.dom.stats.isConnected);assert(ed.ac.input.isConnected);
        ''')

    def test_target_owned_and_readonly_trial_compare_their_own_actual_saved_version(self):
        self.run_js(r'''
          const lists={target:{Deck:[one(elves,7)]},owned:{Deck:[one(bolt,2)]}};
          let ed=full({lists},{version:'owned'});setQty(ed.lists.Deck[0].uid,3);
          assert.equal(ed.base.lists.Deck[0].name,bolt.name);same(deltas(),['+1']);
          assert(curve().getAttribute('aria-label').includes('saved play-now list'));
          assert(curve().getAttribute('aria-label').includes('1: 2 saved, 3 now'));
          assert(!curve().getAttribute('aria-label').includes('7 saved'));
          closeEditor();
          ed=full({lists,may_save:false});assert(ed.readOnly);assert(!main.querySelector('.bar-save'));
          setQty(ed.lists.Deck[0].uid,8);same(deltas(),['+1']);
          assert(curve().getAttribute('aria-label').includes('saved planned list'));
          assert(curve().getAttribute('aria-label').includes('1: 7 saved, 8 now'));
          assert(!main.querySelector('.bar-save'));
        ''')

    def test_new_copied_and_started_missing_playnow_lists_never_claim_a_saved_baseline(self):
        self.run_js(r'''
          const noComparison=()=>{assert(curve());assert.equal(marks().length,0);same(deltas(),[]);
            assert(!curve().getAttribute('aria-label').includes('saved'));assert(!main.querySelector('.curve-comparison'));};
          startEditor({mode:'new',kind:'casual',restoreDraft:false});
          addCard(elves,'Deck');noComparison();closeEditor();
          startEditor({mode:'new',from:'product/fixture',view:view({new_deck:{kind:'casual',title:'Copied fixture'}}),restoreDraft:false});
          setQty(editor.lists.Deck[0].uid,5);noComparison();closeEditor();
          const ed=full({lists:{target:structuredClone(list),owned:null}},{version:'owned'});
          assert(!ed.hasFileList);assert(noOwnedList());startOwned();assert(ed.starting);assert(!ed.hasFileList);
          setQty(ed.lists.Deck[0].uid,5);noComparison();
        ''')

    def test_gradient_uses_current_canonical_identity_with_unknown_distinct_from_colourless(self):
        self.run_js(r'''
          let ed=full();const style=()=>ed.dom.stats.querySelector('.edit-curve-part').getAttribute('style');
          assert(style().includes('linear-gradient(180deg'));assert(style().includes('--stripe-g'));
          assert(!style().includes('--stripe-r')); // Sideboard does not define the gradient.
          const white={...elves,name:'White companion fixture',color_identity:['W']};
          ed.lists.Companion=[newLine(one(white))];drawStats();
          assert(style().indexOf('--stripe-w')<style().indexOf('--stripe-g'));same(deltas(),[]);
          closeEditor();
          ed=full({kind:'commander',sections:['Commander','Deck','Sideboard'],
            lists:{target:{Commander:[one(bolt)],Deck:[one(elves,4)]},owned:null}});
          assert(style().includes('--stripe-r'));assert(!style().includes('--stripe-g'));
          closeEditor();
          const colourless={...elves,name:'Colourless fixture',color_identity:[]};
          ed=full({lists:{target:{Deck:[one(colourless)]},owned:null}});assert(style().includes('--stripe-c'));closeEditor();
          ed=full({lists:{target:{Deck:[one(null)]},owned:null}});assert.equal(style(),'');same(deltas(),[]);
          assert(!style().includes('--stripe-c'));
        ''')

    def test_sideboard_companion_lands_printing_and_writeup_changes_do_not_invent_spell_deltas(self):
        self.run_js(r'''
          const ed=full(),oldCurve=curve().getAttribute('aria-label'),oldStats=JSON.stringify(statsCopy());
          setQty(ed.lists.Sideboard[0].uid,3);same(deltas(),[]);
          assert.equal(curve().getAttribute('aria-label'),oldCurve);assert.equal(JSON.stringify(statsCopy()),oldStats);
          ed.lists.Companion=[newLine(one(bolt))];drawStats();same(deltas(),[]);
          const line=ed.lists.Deck[0];line.set='new';line.number='99';line.finish='foil';ed.prose.notes='Different notes';
          changed({list:false});same(deltas(),[]);assert.equal(curve().getAttribute('aria-label'),oldCurve);
          setQty(ed.lists.Deck.find(line=>line.name===forest.name).uid,55);same(deltas(),[]);
          assert.equal(listStats().lands,55);assert.equal(listStats().spells,4);
        ''')

    def test_missing_card_metadata_suppresses_comparison_until_known_without_zero_guesses(self):
        self.run_js(r'''
          const ed=full();setQty(ed.lists.Deck[0].uid,5);same(deltas(),['+1']);
          ed.base.lists.Deck[0].card=null;drawStats();same(deltas(),['+1']);
          assert.equal(ed.base.lists.Deck[0].card,null); // Metadata reuse never hydrates the saved model itself.
          ed.lists.Deck[0].card=null;drawStats();same(deltas(),[]);assert.equal(marks().length,0);
          const sent={Deck:ed.lists.Deck.map(line=>line.uid)};
          fillCards({lists:{target:{Deck:ed.lists.Deck.map(line=>({...sendLine(line),card:line.card||elves}))}}},sent);
          same(deltas(),['+1']);assert.equal(ed.base.lists.Deck[0].qty,4);assert.equal(ed.lists.Deck[0].qty,5);
          assert.equal(ed.base.lists.Deck[0].card,null);
          assert(curve().getAttribute('aria-label').includes('4 saved, 5 now'));
          ed.base.lists.Deck[0].card={...elves,cmc:2};drawStats();same(deltas(),[]);
          assert.equal(marks().length,0); // Mismatched card-data knowledge is not an unsaved mana-value move.
          ed.base.lists.Deck[0].card=null;ed.base.lists.Deck[0].name='Unknown removed saved name';drawStats();same(deltas(),[]);
        ''')

    def test_empty_current_draft_keeps_removed_saved_buckets_without_invalid_other_stats(self):
        self.run_js(r'''
          const ed=full({lists:{target:{Deck:[one(elves,4)]},owned:null}});
          removeLine(ed.lists.Deck[0].uid);assert.equal(listStats().total,0);
          same(deltas(),['−4']);assert.equal(marks().length,1);
          assert(columns()[1].querySelector('.curve-before').matches('.is-shrunk'));
          assert(columns()[1].querySelector('.curve-before').getAttribute('style').includes('100.0%'));
          assert(curve().getAttribute('aria-label').includes('1: 0'));assert(ed.dom.stats.textContent.includes('No cards in this draft'));
          assert(!ed.dom.stats.textContent.includes('NaN'));assert.equal(ed.dom.stats.querySelector('.stat-line'),null);
          assert(undoLast());same(deltas(),[]);assert(!ed.dom.stats.textContent.includes('No cards in this draft'));
        ''')

    def test_rebase_and_draft_restore_use_the_latest_saved_baseline_instead_of_a_cached_curve(self):
        self.run_js(r'''
          const ed=full();setQty(ed.lists.Deck[0].uid,5);saveDraft(ed);closeEditor();
          const restored=full({}, {restoreDraft:true});same(deltas(),['+1']);
          assert(curve().getAttribute('aria-label').includes('4 saved, 5 now'));
          const latestLists=structuredClone(list);latestLists.Deck[0].qty=8;
          const latest=view({sha256:'b'.repeat(64),lists:{target:latestLists,owned:null}});
          const mine={lists:copyList(restored.lists),fields:{...restored.fields},prose:{...restored.prose},starting:false};
          rebase(restored,latest,mine,restored.base);drawEditor();
          assert.equal(restored.base.lists.Deck[0].qty,8);assert.equal(restored.lists.Deck[0].qty,9);
          same(deltas(),['+1']);assert(curve().getAttribute('aria-label').includes('8 saved, 9 now'));
          assert(!curve().getAttribute('aria-label').includes('4 saved'));
        ''')


class EditorCurveStyleTests(unittest.TestCase):
    def test_delta_ink_is_neutral_and_markers_have_forced_colour_fallbacks(self):
        css = (WEB / 'editor.css').read_text(encoding='utf-8')
        delta = re.search(r'\.curve-delta\s*\{([^}]+)\}', css).group(1)
        self.assertIn('color: var(--ink-3)', delta)
        self.assertNotRegex(delta, r'--(?:accent|strong|weak|good|warn|crit)')
        self.assertIn('background: var(--deck-stripe, var(--ink-3))', css)
        self.assertIn('border-top: 2px dashed var(--ink-4)', css)
        grown = re.search(r'\.curve-before\.is-grown\s*\{([^}]+)\}', css).group(1)
        self.assertIn('border-color: var(--on-scrim)', grown)
        self.assertIn('var(--scrim-edge)', grown)
        self.assertIn('.edit-curve .curve-bar { background: CanvasText; }', css)
        self.assertIn('.curve-before.is-grown { border-color: Canvas; }', css)
