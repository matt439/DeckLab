"""Saved physical stand-ins on the real Overview and printed play sheet.

The deterministic DOM fixture drives the real scripts; no server, collection or
Forge run is touched. The exported logical list must remain unchanged.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_assembly_completion_ui import SETUP as PACKING
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = PAGE + """
  state.may = {see_inventory: ['home']};
  elf.oracle_text = 'When Elf enters, draw a card.';
  const withStandins = () => ({...makePage(), standins: {version: 'target', rows: [
    {for: 'Elf', using: 'Physical marker', qty: 2, card: elf},
    {for: 'Bolt', using: null, qty: 1, card: bolt}], warnings: []}});
  api = async () => ({lists: [], sideboards: [], games: [], warnings: [], decks: {}});
  let printed = 0; window.print = () => { printed += 1; };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckStandinsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)],
                                input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_overview_names_the_markers_and_taps_the_represented_rules(self):
        self.run_js("""
          const page = withStandins();
          page.usual_opponents = [{id: 'casual/other', title: 'Other deck'}];
          clear(main); drawDeck(page);
          const overview = panel('overview'), section = overview.querySelector('#sec-standins');
          assert(section, 'stand-ins belong on the Overview');
          assert(section.textContent.includes('Physical marker stands for Elf'));
          assert(section.textContent.includes('Any card stands for Bolt'));
          same(section.querySelectorAll('.qty').map(node => node.textContent), ['2', '1']);
          const ids = overview.querySelectorAll('section').map(node => node.id);
          assert(ids.indexOf('sec-standins') < ids.indexOf('sec-opponents'));
          assert(ids.indexOf('sec-standins') < ids.indexOf('sec-sideboard'));
          const rows = section.querySelectorAll('.card-row');
          rows[0].click();
          assert.equal(inspections[0].card, elf);
          assert.equal(inspections[0].card.oracle_text, 'When Elf enters, draw a card.');
          assert.equal(inspections[0].trigger, rows[0]);
          const group = viewerGroup(rows[0]);
          same(group.items.map(item => item.card.name), ['Elf', 'Bolt']);
          assert.equal(group.items[0].caption, '2 x Physical marker stands for Elf');
          assert.equal(section.querySelectorAll('.chip').length, 0);
        """)

    def test_missing_card_data_keeps_the_mapping_without_a_false_viewer(self):
        self.run_js("""
          const page = withStandins();
          page.standins.rows = [{for: 'Unavailable rules card', using: null, qty: 3, card: null}];
          const section = deckStandinsSection(page);
          main.append(section);
          assert(section.textContent.includes('Any card stands for Unavailable rules card'));
          assert(section.textContent.includes('Picture and rules unavailable'));
          assert.equal(section.querySelector('.qty').textContent, '3');
          assert.equal(section.querySelectorAll('button').length, 0);
          assert.equal(section.querySelectorAll('[data-viewer]').length, 0);
        """)

    def test_direct_packing_opens_the_represented_card_without_a_prior_deck_page(self):
        self.run_js(PACKING + """
          state.cards = new Map();
          const data = plan();
          data.cards.Alpha.oracle_text = 'The represented card has these rules.';
          data.decks[0].standins = {version: 'target', rows: [
            {for: 'Alpha', using: 'Physical marker', qty: 2}], needs: [], retired: [], warnings: [], editable: false};
          drawAssembly(data, routeToken); await settle();
          const standins = main.querySelector('.pack-standins');
          const link = standins.querySelector('.card-link');
          assert.equal(link.tag, 'button', 'the supplied picture is enough to open the rules');
          link.click();
          assert.equal(inspections.at(-1).card, data.cards.Alpha);
          assert.equal(inspections.at(-1).card.oracle_text, 'The represented card has these rules.');
          assert.equal(state.cards.size, 0, 'Packing does not depend on a previous deck page cache');
        """)

    def test_only_the_displayed_versions_projection_is_used(self):
        self.run_js("""
          const page = withStandins();
          page.version = 'owned';
          assert.equal(deckStandinsSection(page), null);
          printDeck(page);
          assert(!document.querySelector('.print-sheet').textContent.includes('Physical marker'));
          window.fire('afterprint');
          page.standins.version = 'owned';
          assert(deckStandinsSection(page).textContent.includes('Physical marker stands for Elf'));
          printDeck(page);
          assert(document.querySelector('.print-sheet').textContent.includes('Physical marker stands for Elf'));
          assert.equal(printed, 2);
        """)

    def test_absent_empty_and_warning_only_projections(self):
        self.run_js("""
          const page = makePage();
          assert.equal(deckStandinsSection(page), null);
          page.standins = {version: 'target', rows: [], warnings: []};
          assert.equal(deckStandinsSection(page), null);
          printDeck(page);
          assert.equal(document.querySelector('.print-sheet').querySelectorAll('h2').length, 0);
          window.fire('afterprint');
          page.standins.warnings = ['The saved marker is no longer free.'];
          const section = deckStandinsSection(page);
          assert(section.textContent.includes('The saved marker is no longer free.'));
          assert.equal(section.querySelectorAll('.card-row').length, 0);
          printDeck(page);
          assert(document.querySelector('.print-sheet').textContent.includes('The saved marker is no longer free.'));
        """)

    def test_a_profile_switch_cannot_print_an_earlier_viewers_inventory(self):
        self.run_js("""
          const page = withStandins();
          page.standins.warnings = ['Physical marker is held elsewhere.'];
          assert(deckStandinsSection(page));
          state.profile = {id: 'user2', space: 'user2'};
          state.may = {see_inventory: ['user2']};
          assert.equal(deckStandinsSection(page), null);
          printDeck(page);
          let sheet = document.querySelector('.print-sheet');
          assert(!sheet.textContent.includes('Physical marker'));
          assert(!sheet.textContent.includes('Stand-ins'));
          window.fire('afterprint');
          // The id is the authoritative fallback when an older summary omits space.
          delete page.summary.space;
          page.summary.id = 'user2/casual/test';
          assert(deckStandinsSection(page));
          state.may = {see_inventory: ['home']};
          assert.equal(deckStandinsSection(page), null);
          printDeck(page);
          sheet = document.querySelector('.print-sheet');
          assert(!sheet.textContent.includes('Physical marker'));
        """)

    def test_print_mapping_does_not_replace_the_logical_list_or_guide(self):
        self.run_js("""
          const page = withStandins();
          page.standins.warnings = ['Check that the two markers are still sleeved.'];
          page.guide = {changed_on: '2026-10-14', sections: [{title: 'Opening turns', markdown: 'Keep two lands.'}]};
          const before = JSON.stringify(page), logical = exportedDeck(page);
          printDeck(page);
          const sheet = document.querySelector('.print-sheet');
          assert.equal(sheet.querySelector('pre').textContent, logical);
          assert(!logical.includes('Physical marker'));
          assert(logical.includes('4 Elf (FDN) 1') && logical.includes('2 Elf (M21) 2'));
          assert(sheet.textContent.includes('2 x Physical marker stands for Elf'));
          assert(sheet.textContent.includes('1 x Any card stands for Bolt'));
          assert(sheet.textContent.includes('Check that the two markers are still sleeved.'));
          assert(sheet.textContent.includes('Guide needs review: the list changed on 2026-10-14.'));
          assert(sheet.textContent.includes('Opening turns') && sheet.textContent.includes('Keep two lands.'));
          assert.equal(JSON.stringify(page), before, 'printing must not mutate a deck or mapping');
          assert.equal(exportedDeck(page), logical);
          assert.equal(printed, 1);
          window.fire('afterprint');
          assert.equal(document.querySelector('.print-sheet'), null);
        """)

    def test_mapping_names_and_warnings_are_text(self):
        self.run_js("""
          const page = withStandins();
          page.standins.rows = [{for: '<b>Elf</b>', using: '<script>marker</script>', qty: 1, card: null}];
          page.standins.warnings = ['<img src=x onerror=bad()>'];
          const section = deckStandinsSection(page);
          assert(section.textContent.includes('<script>marker</script> stands for <b>Elf</b>'));
          assert.equal(section.querySelectorAll('script').length, 0);
          assert.equal(section.querySelectorAll('img').length, 0);
          printDeck(page);
          const sheet = document.querySelector('.print-sheet');
          assert(sheet.textContent.includes('<img src=x onerror=bad()>'));
          assert.equal(sheet.querySelectorAll('script').length, 0);
          assert.equal(sheet.querySelectorAll('img').length, 0);
        """)

if __name__ == "__main__":
    unittest.main()
