"""The Stats tab's free dual lands for a short colour (E3-S25, deck-swaps.js shortColourLands) under Node: shown under
the colour sources only when a colour is short, on an ordinary deck whose collection the visitor may see, it asks
GET /api/deck/dual-lands once when opened, lists each land with the basic it would replace, and its Test this swap
saves the swap as the editor's draft and opens the editor's Test this change sheet.

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js; nothing is sent to a server.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + """
  const crag = card('Rootbound Crag', 'Land', 0, ['R', 'G']);
  const summary = (colours, ok) => ({colours, name: COLOUR_WORDS[colours], ok, checks: [], short: ok ? [] : [{}],
    hardest: {colours, cost: '1C', cost_in_colours: '1' + colours, turn: 2, needed: 8, have: ok ? 9 : 5,
      have_lands: ok ? 9 : 5, margin: ok ? 1 : -3, cards: [], notes: []}});
  const statsOf = (short) => ({colours: {table: 60, colours: [summary('R', !short), summary('G', true)], sources: [], rules: []},
    sources: {}});
  const shortPage = () => { const page = makePage(); page.stats = statsOf(true); return page; };
  const lands = {deck_id: 'casual/test', version: 'target', kind: 'casual', colours: ['R', 'G'], checked: true,
    short: [{colour: 'R', name: 'red', have: 5, needed: 8}], basics: 20, warnings: [],
    rate: 1.43, rate_date: '2026-10-12', price_date: '2026-10-12', more: 2,
    lands: [{name: 'Rootbound Crag', card: crag, default: {set: 'xln', number: '256', finish: 'nonfoil', why: 'owned'},
      free: 3, here: 3, max_qty: 2, makes: ['R', 'G'], fixes: ['R'], replaces: {name: 'Forest', qty: 20},
      tapped: 'maybe', basic: false, aud: 0.4,
      note: {severity: 1, words: 'A little weaker', text: 'A little weaker: makes red mana, which the deck is short of.'}}]};
  const editView = {id: 'casual/test', title: 'Test Deck', sha256: 'abc', fields: {status: 'building', player: 'user'},
    lists: {target: {Deck: [{qty: 3, name: 'Bolt', set: 'fdn', number: '3', card: bolt},
      {qty: 20, name: 'Forest', card: forest}]}, owned: null}};
  const stored = {};
  window.localStorage = {getItem: (k) => stored[k] ?? null, setItem: (k, v) => { stored[k] = String(v); },
    removeItem: (k) => { delete stored[k]; }};
  const calls = [];
  let refuse = null, answer = lands;
  api = async (path) => {
    calls.push(path);
    if (path.startsWith('/api/deck/edit')) return editView;
    if (refuse) throw new ApiError(refuse, 'No.');
    return answer;
  };
  const settle = async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); };
  const asked = () => calls.filter((p) => p.startsWith('/api/deck/dual-lands'));
  const openPart = async (part) => { part.open = true; part.fire('toggle'); await settle(); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DualLandsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_a_short_colour_lists_its_free_dual_lands_once(self):
        self.run_js("""
          const page = shortPage();
          const part = shortColourLands(page);
          assert.equal(part.querySelector('summary').textContent, 'Free dual lands for red');
          same(asked(), []);
          await openPart(part);
          same(asked(), ['/api/deck/dual-lands?id=casual%2Ftest&version=target']);
          const text = part.textContent;
          assert(text.includes('Free dual lands:') && text.includes('make red and another of the deck'), text);
          assert(text.includes('Rootbound Crag') && text.includes('3 free · for 2 Forests'), text);
          assert(text.includes('A little weaker: makes red mana, which the deck is short of.'), text);
          assert(text.includes('2 more lands fit; these fix the most.'), text);
          assert(!text.includes('On the way'), text);
          const test = part.querySelectorAll('button').find((b) => b.textContent === 'Test this swap');
          assert.equal(test.getAttribute('aria-label'), 'Test Rootbound Crag for Forest');
          // Closing and opening again doesn't ask again; the Play-now list asks for its own.
          part.open = false; part.fire('toggle'); await openPart(part);
          same(asked().length, 1);
          const owned = shortPage(); owned.version = 'owned';
          await openPart(shortColourLands(owned));
          same(asked().at(-1), '/api/deck/dual-lands?id=casual%2Ftest&version=owned');
          // The colour sources panel carries it.
          assert(colourPanel(page.stats, page).querySelector('.dual-lands-part'));
          assert.equal(colourPanel(page.stats).querySelector('.dual-lands-part'), null);
          // On the way, a Plains, and nothing that fits.
          lands.lands[0].here = 0; lands.lands[0].replaces = {name: 'Plains', qty: 4}; lands.more = 0;
          const again = shortColourLands(shortPage()); await openPart(again);
          assert(again.textContent.includes('On the way') && again.textContent.includes('for 2 Plains'), again.textContent);
          answer = {...lands, lands: []};
          const none = shortColourLands(shortPage()); await openPart(none);
          assert(none.textContent.includes('No free land in the collection makes red and another'), none.textContent);
          answer = {...lands, lands: [], basics: 0};
          const noBasics = shortColourLands(shortPage()); await openPart(noBasics);
          assert(noBasics.textContent.includes('The list has no basic lands to swap out.'), noBasics.textContent);
        """)

    def test_only_with_a_short_colour_and_the_collection(self):
        self.run_js("""
          // No colour short (or no stats): nothing.
          const fine = makePage(); fine.stats = statsOf(false);
          assert.equal(shortColourLands(fine), null);
          assert.equal(shortColourLands(makePage()), null);
          // A visitor who may not see the deck's space's inventory, a product or pairing.
          const hidden = shortPage(); delete hidden.owned;
          assert.equal(shortColourLands(hidden), null);
          state.may = {see_inventory: ['user2'], deck_spaces: ['user2']};
          assert.equal(shortColourLands(shortPage()), null);
          state.may = null;
          for (const id of ['product/fdc-test', 'pairing/a+b']) {
            const other = shortPage(); other.summary.id = id;
            assert.equal(shortColourLands(other), null);
          }
          same(asked(), []);
        """)

    def test_a_refusal_takes_it_away_and_a_failure_offers_try_again(self):
        self.run_js("""
          for (const status of [400, 403, 404]) {
            refuse = status;
            const part = shortColourLands(shortPage());
            main.append(part);
            await openPart(part);
            assert(!part.isConnected, String(status));
          }
          refuse = 500;
          const failed = shortColourLands(shortPage());
          main.append(failed);
          await openPart(failed);
          assert(failed.textContent.includes("Free dual lands couldn't be loaded."), failed.textContent);
          refuse = null;
          buttonText(failed, 'Try again').click(); await settle();
          assert(failed.textContent.includes('Rootbound Crag'), failed.textContent);
          // An answer that comes after the profile changed isn't shown.
          const late = shortColourLands(shortPage()); main.append(late);
          late.open = true; late.fire('toggle');
          state.profile = {id: 'user1', name: 'User1', plays_as: 'wife'};
          await settle();
          assert(!late.isConnected);
        """)

    def test_test_this_swap_saves_the_land_for_its_basic(self):
        self.run_js("""
          location.hash = '#/deck?id=casual%2Ftest&tab=stats';
          const part = shortColourLands(shortPage()); main.append(part);
          await openPart(part);
          part.querySelectorAll('button').find((b) => b.textContent === 'Test this swap').click();
          await settle();
          assert.equal(location.hash, '#/edit?id=casual%2Ftest&v=target&test=change');
          const draft = JSON.parse(local.get('draft.matt.casual/test.target'));
          same(draft.lists.Deck.map((l) => [l.qty, l.name, l.set || null]),
               [[3, 'Bolt', 'fdn'], [18, 'Forest', null], [2, 'Rootbound Crag', 'xln']]);
          same(draft.base.lists, editView.lists.target);
        """)


if __name__ == "__main__":
    unittest.main()
