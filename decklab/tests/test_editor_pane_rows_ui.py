"""Narrow lab list rows preserve the original facts and action nodes."""
import re
import unittest

from decklab.tests import test_editor_panes_ui as panes
from decklab.tests.test_workspace_ui import NODE, WEB


class NarrowEditorRowSourceTests(unittest.TestCase):
    def test_actual_list_container_reflows_original_rows_without_hiding_facts_or_shrinking_targets(self):
        css=(WEB/'editor.css').read_text(encoding='utf-8')
        self.assertIn('.edit-page.has-editor-panes .edit-main { container-type: inline-size; container-name: editor-cards; }',css)
        compact=re.search(r'(?s)@container editor-cards \(max-width: 600px\) \{(.*?)\n\}',css).group(1)
        self.assertIn('.edit-list > .edit-row:not(.edit-removed)',compact)
        self.assertIn('grid-template-areas: "step card card card more" "step mv print badge more";',compact)
        for element,area in (('edit-stepper','step'),('edit-card','card'),('edit-print','print'),
                             ('edit-badge-slot','badge'),('edit-more','more'),('edit-mv','mv')):
            self.assertRegex(compact,rf'\.edit-row > \.{element} \{{[^}}]*grid-area: {area};')
        self.assertIn('.edit-card .nm { flex-wrap: wrap; }',compact)
        self.assertIn('.edit-card .nm-text { white-space: normal; overflow-wrap: anywhere; }',compact)
        for forbidden in ('display: none','visibility: hidden','font-size:','--tap:','--stepper-h:',
                          '.edit-stacks','.is-quick','line-clamp:'):
            self.assertNotIn(forbidden,compact)


@unittest.skipUnless(NODE,'Node.js is not installed')
class NarrowEditorRowInteractionTests(unittest.TestCase):
    def test_long_name_cost_printing_availability_and_original_controls_survive_responsive_projection(self):
        panes.EditorPanesUiTests.run_js(self,r'''
          const longName='A deliberately long visible card name kept in the original row';
          const longCard={...elves,name:longName,mana_cost:'{2}{G}{G}'};
          const ed=full();ed.lists=copyList({Deck:[{qty:2,name:longName,set:'fixture',number:'123a',finish:'foil',card:longCard}]});
          drawLines();showRowAvailability({rows:[{name:longName,missing:5,owned:0,on_the_way:0,
            in_use_elsewhere:[['Visible saved holder',5]]}]});
          const line=ed.lists.Deck[0],row=ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`);
          const card=row.querySelector('.edit-card'),qty=row.querySelector('.qty-input'),printing=row.querySelector('.edit-print');
          const badge=row.querySelector('.edit-availability'),more=row.querySelector('.edit-more'),caption=viewerCards.get(card).caption;
          assert.equal(row.querySelector('.nm-text').textContent,longName);assert(card.querySelector('.cost'));
          assert.equal(printing.textContent.startsWith(printingText(line)),true);assert(badge.textContent.includes('5 in other decks'));
          qty.select=()=>{}; // Native input selection is outside this minimal DOM double.
          const before=JSON.stringify(draftBody()),history=ed.history.length;qty.focus();width(false);width(true);
          assert(ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`)===row);
          assert(row.querySelector('.edit-card')===card&&row.querySelector('.qty-input')===qty);
          assert(row.querySelector('.edit-print')===printing&&row.querySelector('.edit-more')===more);
          assert(row.querySelector('.edit-availability')===badge);assert.equal(viewerCards.get(card).caption,caption);
          assert(document.activeElement===qty);assert.equal(JSON.stringify(draftBody()),before);assert.equal(ed.history.length,history);
        ''')
