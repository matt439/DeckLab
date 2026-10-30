"""The printed play sheet's At the table (E9-S27): a Commander deck's pregame facts on paper.

Real page scripts over the event/DOM double; fixture cards only, no server, writes or fetches.
"""
import json
import subprocess
import unittest

from decklab.tests.test_commander_readiness_ui import SETUP as READINESS
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = READINESS + """
  let printed = 0; window.print = () => { printed += 1; };
  let fetched = 0; api = async () => { fetched += 1; return {}; };
  const printSheet = (data) => {
    document.querySelector('.print-sheet')?.remove();
    printDeck(data);
    return document.querySelector('.print-sheet');
  };
  // The sheet's At the table part: everything from its heading to the guide's notes line.
  const tablePart = (sheet) => {
    const text = sheet.textContent, from = text.indexOf('At the table');
    return from < 0 ? '' : text.slice(from, text.indexOf('Guide notes may discuss both lists'));
  };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CommanderPrintUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_the_sentence_effects_combos_and_data_dates_print_as_text(self):
        self.run_js("""
          const data = listed(4, [combo(['Elf','Bolt']), combo(['Bolt','Wurm'], {floor:4, class:'mass_land_denial'})],
            {cards_minimum:3, game_changers:[{name:'Elf',qty:1},{name:'Elf',qty:1}], extra_turns:[{name:'Wurm',qty:1}]});
          const before = JSON.stringify(data);
          let sheet = printSheet(data);
          const part = tablePart(sheet);
          const headings = sheet.querySelectorAll('h2').map((h) => h.textContent);
          assert(headings.includes('At the table'));
          // The page's own sentence, word for word, with the names as plain text.
          const page = showReadiness(data).querySelector('.commander-table-summary').textContent;
          fetched = 0;                     // drawing the deck page fetches; printing again mustn't
          printSheet(data);
          sheet = document.querySelector('.print-sheet');
          assert.equal(sheet.querySelector('.commander-table-summary').textContent, page);
          assert(page.startsWith('Aims for Bracket 2; the cards found require at least Bracket 3, and the two-card combos'));
          assert(part.includes('Game Changers: Elf.'));
          assert(part.includes('Mass land denial: none found in the checked cards.'));
          assert(part.includes('Extra turns: Wurm.'));
          assert(part.includes("Two-card combos: the list holds both pieces of these 2 combos " +
            "(Commander Spellbook's two-card combos, list of 2026-10-14)."));
          const items = sheet.querySelector('.commander-combos').children.map((li) => li.textContent);
          same(items, ['Elf + Bolt: Infinite damage, Infinite lifegain, …. None in Brackets 1-2.',
            'Bolt + Wurm: Infinite damage, Infinite lifegain, …. Counts as mass land denial.']);
          assert(part.includes("Scryfall card data (Game Changers and ban list): 2026-10-14."));
          assert(part.includes("Commander Spellbook's two-card combos: 2026-10-14."));
          assert(part.includes("these card checks alone don't establish a bracket"));
          // Paper has no viewer: no card links, buttons or Spellbook links in the part.
          const at = sheet.children.findIndex((n) => n.textContent === 'At the table');
          for (const node of sheet.children.slice(at)) {
            assert.equal(node.querySelectorAll('[role=button]').length, 0);
            assert(!node.querySelectorAll('a').some((a) => (a.getAttribute('href') || '').includes('commanderspellbook')));
          }
          assert.equal(JSON.stringify(data), before, 'printing must not change the page data');
          assert.equal(printed, 2);
          assert.equal(fetched, 0, 'the sheet prints only what the page already loaded');
        """)

    def test_a_clean_deck_and_an_unchecked_combo_list_say_so(self):
        self.run_js("""
          let part = tablePart(printSheet(readinessPage()));
          assert(part.includes('Aims for Bracket 2: no Game Changers, extra turns, mass land denial or two-card combos found.'));
          assert(part.includes("Two-card combos: none found in Commander Spellbook's two-card combos (list of 2026-10-14)."));
          assert(part.includes('Game Changers: none found in the checked cards.'));
          part = tablePart(printSheet(readinessPage({combos:{checked:false}, mass_land_denial:null, unknown_cards:['Mystery Card']})));
          assert(part.includes('Aims for Bracket 2: the card checks are incomplete.'));
          assert(part.includes('Two-card combos: not checked (combo list unavailable).'));
          assert(part.includes('Mass land denial: not checked (effect data unavailable).'));
          assert(part.includes('Cards without data: Mystery Card. The checks are incomplete.'));
          assert(!part.includes('none found in Commander'));
          const broken = readinessPage(); broken.stats.commander.ok = false;
          assert(tablePart(printSheet(broken)).includes('Deck rules need attention before this list can be played.'));
          const stale = readinessPage({data:{cards_date:null, combos_date:'2026-10-14', dates_stale:true, max_age_days:7}});
          part = tablePart(printSheet(stale));
          assert(part.includes('Scryfall card data (Game Changers and ban list): date unknown.'));
          assert(part.includes('These checks may be out of date.'));
        """)

    def test_facts_not_loaded_print_that_rather_than_a_guess(self):
        self.run_js("""
          for (const strip of [(d) => { d.stats = null; }, (d) => { delete d.stats; },
                               (d) => { d.stats = {}; }, (d) => { delete d.stats.commander.bracket; }]) {
            const data = readinessPage(); strip(data);
            const sheet = printSheet(data), part = tablePart(sheet);
            assert(part.includes("The Commander checks weren't loaded, so this sheet can't say what opponents will face."), part);
            assert(!part.includes('Aims for Bracket'));
            assert(!part.includes('none found'));
            assert.equal(sheet.querySelectorAll('.commander-table-summary').length, 0);
          }
          assert.equal(fetched, 0);
        """)

    def test_a_casual_deck_prints_no_commander_part(self):
        self.run_js("""
          const data = readinessPage();
          data.summary = {...data.summary, id:'casual/test', kind:'casual', target_bracket:null};
          const sheet = printSheet(data);
          assert(!sheet.querySelectorAll('h2').some((h) => h.textContent === 'At the table'));
          assert(!sheet.textContent.includes('Game Changers'));
          assert(!sheet.textContent.includes('Bracket'));
          const plain = makePage();
          assert(!printSheet(plain).textContent.includes('At the table'));
        """)

    def test_another_viewer_prints_no_inventory_or_household_night(self):
        self.run_js("""
          // A member sees only the list's own facts: never the one-card-away pieces' availability or prices,
          // nor the household's recorded Commander night, even when an earlier page left them in the data.
          const data = listed(3, [combo(['Elf','Bolt'])]);
          data.stats.commander.bracket.near_combos = {total:1, matches:[{names:['Elf','Secret Piece'], missing:'Secret Piece',
            aud:12.5, availability:{free:1, in_use:['Gruul Ramp']}, considering:false}]};
          data.commander_night = {night:{name:'Household night', venue:'Private venue', target_bracket:2}};
          for (const profile of [{id:'user1', space:'home'}, {id:'user2', space:'user2'}]) {
            state.profile = profile;
            state.may = {see_inventory: [profile.space]};
            const part = tablePart(printSheet(data));
            assert(part.includes('Elf + Bolt'));
            for (const hidden of ['Secret Piece', 'Gruul Ramp', '12.5', 'Household night', 'Private venue', 'One card away'])
              assert(!part.includes(hidden), hidden);
          }
        """)


if __name__ == "__main__":
    unittest.main()
