"""Compare two decks (E1-S13, first slice): the compare page and the deck page's "Compare with…" chooser.

Loads every page script into the event/DOM double (fixtures/workspace_ui_runner.js) with api() answered by the
scenario: no browser or server, and nothing is written.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + """
  const settle = async () => { for (let i = 0; i < 8; i++) { await null; flushTimers(); } };
  const bucket = (mv, creatures, noncreatures) => ({mv, creatures, noncreatures, total: creatures + noncreatures,
    cards: [{name: 'Elf', qty: creatures}]});
  const curveOf = (totals, average) => ({average_mv: average, creatures: totals.reduce((n, t) => n + t[0], 0),
    noncreatures: totals.reduce((n, t) => n + t[1], 0), outside: [], x_spells: null,
    buckets: ['0', '1', '2', '3', '4', '5', '6', '7+'].map((mv, i) => bucket(mv, ...(totals[i] || [0, 0])))});
  const statsOf = (totals, average, lands, colours, types) => ({curve: curveOf(totals, average),
    lands: {effective: lands, recommended: 23.5, verdict: 'ok'}, colours: {colours}, unresolved: [],
    types: ['creature', 'instant', 'sorcery', 'artifact', 'enchantment', 'planeswalker', 'battle', 'land']
      .map((type) => ({type, count: types[type] || 0, cards: []}))});
  const green = {colours: 'G', name: 'green', ok: true, hardest: {have: 14, needed: 13}};
  const red = {colours: 'R', name: 'red', ok: false, hardest: {have: 6, needed: 9}};
  const deckA = () => { const p = makePage(); p.summary.colors = ['G'];
    p.stats = statsOf([[0, 0], [4, 0], [6, 2]], 1.8, 20, [green], {creature: 10, instant: 2, land: 20}); return p; };
  const deckB = () => { const p = makePage(); Object.assign(p.summary, {id: 'casual/burn', title: 'Burn', colors: ['R']});
    p.versions = ['target']; p.summary.versions = ['target'];
    p.stats = statsOf([[0, 0], [2, 9], [3, 1], [0, 3]], 2.1, 22, [red], {creature: 5, instant: 12, land: 22}); return p; };
  const asked = [];
  let answers = {};
  api = async (path) => {
    asked.push(path);
    for (const [start, answer] of Object.entries(answers)) {
      if (path.startsWith(start)) { if (answer instanceof Error) throw answer; return structuredClone(answer); }
    }
    return {};
  };
  const show = async (hash) => { clear(main); location.hash = hash; setTitle(routeFor("compare").title);
    showCompare(parseHash().params, ++routeToken); await settle(); };
  const rows = (caption) => main.querySelectorAll('table').find((t) => t.querySelector('caption').textContent === caption)
    .querySelector('tbody').children.map((tr) => [tr.querySelector('th').textContent,
      ...tr.querySelectorAll('td').map((td) => td.textContent)]);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CompareUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_child_page_of_decks(self):
        self.run_js("""
          const r = routeFor('compare');
          same([r.path, r.h1, r.parent, r.nav || null], ['compare', 'Compare decks', 'library', null]);
          assert.equal(routeSection('compare').path, 'library');
          assert.equal(compareHref('casual/test', 'user2/casual/elves'), '#/compare?a=casual%2Ftest&b=user2%2Fcasual%2Felves');
          assert.equal(compareHref('casual/test', 'casual/test', 'target', 'owned'), '#/compare?a=casual%2Ftest&b=casual%2Ftest&bv=owned');
        """)

    def test_two_decks_side_by_side(self):
        self.run_js("""
          answers = {'/api/deck?id=casual%2Ftest&': deckA(), '/api/deck?id=casual%2Fburn&': deckB()};
          let tops = [];
          drawCurve = (host, curve, width, pick, top) => tops.push(top);
          Node.prototype.clientWidth = 320;
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          delete Node.prototype.clientWidth;
          // Each deck read as its page reads it, matchups left out.
          same(asked.filter((p) => p.startsWith('/api/deck?')), ['/api/deck?id=casual%2Ftest&version=target&omit=matchups',
            '/api/deck?id=casual%2Fburn&version=target&omit=matchups']);
          assert.equal(main.querySelector('h1').textContent, 'Compare decks');
          assert.equal(document.title, 'Test Deck and Burn – Deck Lab');
          same(main.querySelectorAll('.compare-title').map((a) => [a.textContent, a.getAttribute('href')]),
            [['Test Deck', '#/deck?id=casual%2Ftest&v=target'], ['Burn', '#/deck?id=casual%2Fburn&v=target']]);
          assert(main.querySelector('.compare-facts').textContent.includes('29 cards'));
          same(rows('The two lists in brief'), [['Cards', '29', '29'], ['Average mana value', '1.8', '2.1'],
            ['Lands', '20 formula 23.5', '22 formula 23.5'], ['Creatures', '10', '5'], ['Other spells', '2', '13'],
            ['Colour sources', 'Enough', 'Short: red']]);
          // Both curves on one scale: the larger deck's tallest bar (11 at mana value 1).
          same(tops, [11, 11]);
          same(main.querySelectorAll('.compare-chart').map((c) => c.querySelector('h3').textContent), ['Test Deck', 'Burn']);
          same(rows('Cards at each mana value').slice(0, 4), [['Mana value 0', '0', '0'], ['Mana value 1', '4', '11'],
            ['Mana value 2', '8', '4'], ['Mana value 3', '0', '3']]);
          // Every colour either side needs, a dash (read as None) where a side has none.
          same(rows('Colours and colour sources').map((r) => r[0]), ['Colour identity', 'Green sources', 'Red sources']);
          same(rows('Colours and colour sources')[1], ['Green sources', '14 of 13', '–None']);
          same(rows('Colours and colour sources')[2], ['Red sources', '–None', '6 of 9 Short']);
          // Only the types either deck has.
          same(rows('Copies of each card type'), [['Creature', '10', '5'], ['Instant', '2', '12'], ['Land', '20', '22']]);
          // More: swap the sides, or choose another deck.
          main.querySelector('.menu-wrap').querySelector('button').click();
          const more = main.querySelector('.menu-wrap').querySelectorAll('[role=menuitem]');
          assert.equal(more[0].getAttribute('href'), '#/compare?a=casual%2Fburn&b=casual%2Ftest');
          assert.equal(more[1].textContent, 'Compare with another deck…');
        """)

    def test_a_deck_the_viewer_cant_see_is_missing(self):
        self.run_js("""
          answers = {'/api/deck?id=casual%2Ftest&': deckA(),
            '/api/deck?id=user2%2Fcasual%2Felves&': new ApiError(404, "No deck 'user2/casual/elves'")};
          await show('#/compare?a=casual%2Ftest&b=user2%2Fcasual%2Felves');
          const box = main.querySelector('.box-crit');
          assert.equal(box.querySelector('h2').textContent, "These decks couldn't be compared");
          assert(box.textContent.includes("No deck 'user2/casual/elves' (error 404)"));
          // Nothing of the deck that could be read is shown beside it, and loading it again can't help.
          assert.equal(main.querySelector('table'), null);
          assert(!box.textContent.includes('Test Deck'));
          assert(!box.querySelectorAll('button').some((b) => b.textContent === 'Try again'));
        """)

    def test_a_decks_own_two_lists(self):
        self.run_js("""
          const owned = deckA(); owned.version = 'owned';
          owned.stats = statsOf([[0, 0], [3, 0]], 1.5, 21, [green], {creature: 3, land: 21});
          answers = {'/api/deck?id=casual%2Ftest&version=target': deckA(), '/api/deck?id=casual%2Ftest&version=owned': owned};
          await show('#/compare?a=casual%2Ftest&b=casual%2Ftest&bv=owned');
          assert.equal(document.title, 'Test Deck: its two lists – Deck Lab');
          same(main.querySelectorAll('.compare-title').map((a) => [a.textContent, a.getAttribute('href')]),
            [['Test Deck: Planned list', '#/deck?id=casual%2Ftest&v=target'],
             ['Test Deck: Play-now list', '#/deck?id=casual%2Ftest&v=owned']]);
          same(main.querySelector('thead').querySelectorAll('th').slice(1, 3).map((th) => th.textContent), ['Planned list', 'Play-now list']);
        """)

    def test_missing_stats_say_why(self):
        self.run_js("""
          const b = deckB(); b.stats = null;
          answers = {'/api/deck?id=casual%2Ftest&': deckA(), '/api/deck?id=casual%2Fburn&': b};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          assert(main.querySelector('.box-warn').textContent.includes("Burn's stats couldn't be worked out"));
          same(rows('The two lists in brief')[1], ['Average mana value', '1.8', '–None']);
          assert(main.querySelectorAll('.compare-chart')[1].textContent.includes('No curve'));
        """)

    def test_compare_with_chooses_from_the_visible_decks(self):
        self.run_js("""
          const page = deckA();
          answers = {'/api/decks': {decks: [
            {id: 'casual/test', title: 'Test Deck', colors: ['G']},
            {id: 'casual/zoo', title: 'Zoo', colors: ['R', 'G']},
            {id: 'casual/broken', title: 'Broken', error: 'unreadable'},
            {id: 'casual/burn', title: 'Burn', colors: ['R']}]}};
          const item = deckMoreItems(page).find((i) => i && i.label === 'Compare with…');
          assert(item);
          item.onclick(); await settle();
          const sheet = document.querySelector('.sheet');
          assert.equal(sheet.querySelector('h2').textContent, 'Compare with…');
          // Its own other list first, then the other readable decks by title; never itself or an unreadable one.
          const links = () => sheet.querySelectorAll('.compare-choice').filter((a) => !a.parentNode.hidden);
          same(links().map((a) => [a.textContent, a.getAttribute('href')]), [
            ['Test Deck: its play-now list', '#/compare?a=casual%2Ftest&b=casual%2Ftest&bv=owned'],
            ['Burn', '#/compare?a=casual%2Ftest&b=casual%2Fburn'],
            ['Zoo', '#/compare?a=casual%2Ftest&b=casual%2Fzoo']]);
          const search = sheet.querySelector('.compare-search');
          search.value = 'zo'; search.fire('input');
          same(links().map((a) => a.textContent), ['Zoo']);
          search.value = 'nothing'; search.fire('input');
          assert.equal(links().length, 0);
          assert(sheet.textContent.includes('No deck matches that.'));
        """)

    def test_the_chooser_says_when_the_decks_cant_be_read(self):
        self.run_js("""
          answers = {'/api/decks': new ApiError(503, 'The database is not reachable.')};
          openCompareChooser(deckA()); await settle();
          const sheet = document.querySelector('.sheet');
          assert(sheet.textContent.includes('The database is not reachable.'));
          answers = {'/api/decks': {decks: []}};
          sheet.querySelectorAll('button').find((b) => b.textContent === 'Try again').click(); await settle();
          // Only its own other list is left to choose.
          same(sheet.querySelectorAll('.compare-choice').map((a) => a.textContent), ['Test Deck: its play-now list']);
        """)


if __name__ == "__main__":
    unittest.main()
