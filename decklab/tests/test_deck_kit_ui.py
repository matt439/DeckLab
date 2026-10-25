"""The unbuilt deck's kit guidance and sleeve choices in the real UI scripts."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = PAGE + """
  state.profile = {id: 'matt', name: 'Matt', role: 'admin', space: 'home', plays_as: 'user'};
  state.profiles = [state.profile];
  state.may = {admin: true, see_accessories: true, accessories: true, see_inventory: ['home'], spaces: ['home'], deck_spaces: ['home']};
  const withKit = () => {
    const page = makePage();
    page.summary.kit = {sleeves: null, deck_box: null, need: 29, short: 0, spare: 0, warnings: []};
    return page;
  };
  const settle = async () => { for (let index = 0; index < 8; index++) await Promise.resolve(); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckKitUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)],
                                input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_an_unbuilt_overview_explains_when_and_where_kit_is_chosen(self):
        self.run_js("""
          api = async () => ({lists: [], sideboards: [], games: [], warnings: [], decks: {}});
          const page = withKit(); page.version = 'owned';
          clear(main); drawDeck(page);
          const kit = panel('overview').querySelector('.deck-kit');
          assert(kit.textContent.includes('Choose sleeves and a deck box when you mark this deck built'));
          assert.equal(kit.querySelector('a').getAttribute('href'), '#/assembly?deck=casual%2Ftest&version=owned');
          assert.equal(kit.querySelectorAll('button').length, 0, 'the hint does not choose kit early');
          assert.equal(kit.querySelectorAll('.deck-kit-tile').length, 0);
        """)

    def test_the_hint_respects_space_visibility_and_edit_rights(self):
        self.run_js("""
          const page = withKit();
          page.summary.kit = null;
          assert.equal(deckKit(page), null, 'hidden or unavailable kit is not inferred');
          page.summary.kit = withKit().summary.kit;
          state.may.see_accessories = false;
          assert.equal(deckKit(page), null);
          state.may.see_accessories = true;
          page.summary.space = 'user2'; page.summary.id = 'user2/casual/test';
          assert.equal(deckKit(page), null, 'a personal deck never receives home kit guidance');
          delete page.summary.space;
          assert.equal(deckKit(page), null, 'old summaries use the deck id to check space');
          page.summary = withKit().summary;
          state.may = {see_accessories: true, deck_spaces: [], home_player: 'wife'};
          assert.equal(deckKit(page), null, 'someone unable to mark this deck built gets no action hint');
          state.may.home_player = 'user';
          assert(deckKit(page));
          page.summary.read_only = true;
          assert.equal(deckKit(page), null);
        """)

    def test_a_built_deck_keeps_its_existing_tiles(self):
        self.run_js("""
          const page = withKit(); page.summary.status = 'built';
          const kit = deckKit(page);
          assert.equal(kit.querySelectorAll('.deck-kit-tile').length, 2);
          assert(!kit.textContent.includes('when you mark this deck built'));
        """)

    def test_shared_sleeves_are_named_plainly_on_the_tile(self):
        # Matt, 2026-10-19: the picker warns when they're chosen; afterwards the tile only says so.
        self.run_js("""
          const page = withKit(); page.summary.status = 'built';
          page.summary.kit.sleeves = {state: 'linked', id: 'ds', label: 'Dragon Shield Matte (black)', quantity: 100};
          page.summary.kit.spare = 71;
          page.summary.kit.shared_with = ['Izzet Otters', "one of User1's decks"];
          let kit = deckKit(page);
          const shared = kit.querySelector('.deck-kit-shared');
          assert.equal(shared.textContent, "Also sleeves Izzet Otters, one of User1's decks");
          assert.equal(kit.querySelectorAll('.box-warn').length, 0, 'sharing is not a warning');
          page.summary.kit.shared_with = [];
          kit = deckKit(page);
          assert.equal(kit.querySelector('.deck-kit-shared'), null);
        """)

    def test_the_sleeve_picker_shows_spare_zero_and_short_after_this_decks_need(self):
        self.run_js("""
          const sleeve = (id, quantity) => ({id, kind: 'sleeves', owner: 'matt', label: id,
            quantity, image: '', crop: '', used_by: []});
          api = async () => ({items: [sleeve('Roomy', 100), sleeve('Exact', 75), sleeve('Short', 60)],
            holders_options: [{id: 'casual/test', owner: 'matt', need: 75, sleeves: null}]});
          const sheet = kitPicker({holder: 'casual/test', field: 'sleeves', need: 75});
          await settle();
          const options = sheet.body.querySelectorAll('.acc-pick-tile');
          const textFor = name => options.find(option => option.querySelector('strong')?.textContent === name).textContent;
          assert(textFor('Roomy').includes('75 needed') && textFor('Roomy').includes('100 owned')
            && textFor('Roomy').includes('25 spare'));
          assert(textFor('Exact').includes('75 owned') && textFor('Exact').includes('0 spare'));
          assert(textFor('Short').includes('75 needed') && textFor('Short').includes('60 owned')
            && textFor('Short').includes('15 sleeves short'));
          assert(!textFor('Short').includes('-15 spare'));
          sheet.close();
        """)


if __name__ == "__main__":
    unittest.main()
