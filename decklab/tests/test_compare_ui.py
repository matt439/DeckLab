"""Compare two decks (E1-S13, E1-S26): the compare page and the deck page's "Compare with…" chooser.

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
  const statsOf = (totals, average, lands, colours, types, roles = {}) => ({curve: curveOf(totals, average),
    lands: {effective: lands, recommended: 23.5, verdict: 'ok'}, colours: {colours}, unresolved: [],
    types: ['creature', 'instant', 'sorcery', 'artifact', 'enchantment', 'planeswalker', 'battle', 'land']
      .map((type) => ({type, count: types[type] || 0, cards: []})),
    roles: Object.entries(roles).map(([role, count]) => ({role, count, cards: []}))});
  const green = {colours: 'G', name: 'green', ok: true, hardest: {have: 14, needed: 13}};
  const red = {colours: 'R', name: 'red', ok: false, hardest: {have: 6, needed: 9}};
  const deckA = () => { const p = makePage(); p.summary.colors = ['G'];
    p.stats = statsOf([[0, 0], [4, 0], [6, 2]], 1.8, 20, [green], {creature: 10, instant: 2, land: 20},
      {ramp: 4, removal: 0}); return p; };
  const deckB = () => { const p = makePage(); Object.assign(p.summary, {id: 'casual/burn', title: 'Burn', colors: ['R']});
    p.versions = ['target']; p.summary.versions = ['target'];
    p.stats = statsOf([[0, 0], [2, 9], [3, 1], [0, 3]], 2.1, 22, [red], {creature: 5, instant: 12, land: 22},
      {burn: 9, removal: 6}); return p; };
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
          // Each deck read as its page reads it, matchups left out; then the first deck's matchups, as its
          // Matchups tab gets them, for Head to head.
          same(asked.filter((p) => p.startsWith('/api/deck?')), ['/api/deck?id=casual%2Ftest&version=target&omit=matchups',
            '/api/deck?id=casual%2Fburn&version=target&omit=matchups', '/api/deck?id=casual%2Ftest&version=target']);
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
          // Every colour either side needs, in WUBRG order, a dash (read as None) where a side has none, and by
          // how many a side falls short.
          same(rows('Colours and colour sources').map((r) => r[0]), ['Colour identity', 'Red sources', 'Green sources']);
          same(rows('Colours and colour sources')[1], ['Red sources', '–None', '6 of 9 Short by 3']);
          same(rows('Colours and colour sources')[2], ['Green sources', '14 of 13', '–None']);
          // Only the types either deck has; then the roles either has (none of a role on both isn't a row).
          same(rows('Copies of each card type'), [['Creature', '10', '5'], ['Instant', '2', '12'], ['Land', '20', '22']]);
          same(rows('Copies with each role'), [['Removal', '0', '6'], ['Ramp', '4', '0'], ['Burn', '0', '9']]);
          // More: swap the sides, or choose another deck.
          main.querySelector('.menu-wrap').querySelector('button').click();
          const more = main.querySelector('.menu-wrap').querySelectorAll('[role=menuitem]');
          assert.equal(more[0].getAttribute('href'), '#/compare?a=casual%2Fburn&b=casual%2Ftest');
          assert.equal(more[1].textContent, 'Compare with another deck…');
        """)

    def test_lands_off_the_formula_say_so(self):
        self.run_js("""
          const b = deckB(); b.stats.lands.verdict = 'slightly low';
          answers = {'/api/deck?id=casual%2Ftest&': deckA(), '/api/deck?id=casual%2Fburn&': b};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          // The Stats tab's verdict beside a count off the formula; nothing beside one on it.
          same(rows('The two lists in brief')[2], ['Lands', '20 formula 23.5', '22 formula 23.5 Slightly low']);
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
          assert.equal(main.querySelector('.compare-difference-section'), null);
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

    def test_each_sides_bar_cards_are_their_own_viewer_group(self):
        self.run_js("""
          answers = {'/api/deck?id=casual%2Ftest&': deckA(), '/api/deck?id=casual%2Fburn&': deckB()};
          const picks = [];
          drawCurve = (host, curve, width, pick) => picks.push(pick);
          Node.prototype.clientWidth = 320;
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          delete Node.prototype.clientWidth;
          picks[0](2); picks[1](2);
          // A swipe through deck A's cards never runs on into deck B's.
          same(main.querySelectorAll('.chart-detail').map((d) =>
            d.querySelectorAll('[data-viewer]').map((n) => n.getAttribute('data-viewer'))), [['compare-0'], ['compare-1']]);
        """)

    def test_one_list_against_itself_or_a_pairing_either_way(self):
        self.run_js("""
          answers = {'/api/deck?id=casual%2Ftest&': deckA()};
          await show('#/compare?a=casual%2Ftest&b=casual%2Ftest');
          // The same list twice isn't "its two lists": the sides keep the deck's title.
          assert.equal(document.title, 'Test Deck and Test Deck – Deck Lab');
          same(main.querySelector('thead').querySelectorAll('th').slice(1, 3).map((th) => th.textContent), ['Test Deck', 'Test Deck']);
          const pairing = (id) => { const p = deckA(); Object.assign(p.summary, {id, title: 'Cats + Vampires'}); return p; };
          const owned = pairing('pairing/vampires+cats'); owned.version = 'owned';
          answers = {'/api/deck?id=pairing%2Fcats%2Bvampires&': pairing('pairing/cats+vampires'),
            '/api/deck?id=pairing%2Fvampires%2Bcats&': owned};
          clear(main); asked.length = 0;
          await show('#/compare?a=pairing%2Fcats%2Bvampires&b=pairing%2Fvampires%2Bcats&bv=owned');
          // A pairing's halves in either order are one deck, so these are its two lists.
          assert.equal(document.title, 'Cats + Vampires: its two lists – Deck Lab');
          same(main.querySelector('thead').querySelectorAll('th').slice(1, 3).map((th) => th.textContent), ['Planned list', 'Play-now list']);
        """)

    def test_missing_stats_say_why(self):
        self.run_js("""
          const b = deckB(); b.stats = null;
          answers = {'/api/deck?id=casual%2Ftest&': deckA(), '/api/deck?id=casual%2Fburn&': b};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          assert(main.querySelector('.box-warn').textContent.includes("Burn's stats couldn't be worked out"));
          same(rows('The two lists in brief')[1], ['Average mana value', '1.8', '–None']);
          same(rows('Copies with each role'), [['Ramp', '4', '–None']]);
          assert(main.querySelectorAll('.compare-chart')[1].textContent.includes('No curve'));
        """)

    def test_the_cards_both_use_with_the_pools_cover(self):
        self.run_js("""
          answers = {'/api/compare/shared?': {together: true, counts: true, why_no_counts: null, warnings: [], cards: [
              {name: 'Elf', a: 4, b: 2, need: 6, owned: 5, on_the_way: 1, free: 3, short: 3},
              {name: 'Sol Ring', a: 1, b: 1, need: 2, owned: 2, on_the_way: 0, free: 2, short: 0}]},
            '/api/deck?id=casual%2Ftest&': deckA(), '/api/deck?id=casual%2Fburn&': deckB()};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          assert(asked.includes('/api/compare/shared?a=casual%2Ftest&av=target&b=casual%2Fburn&bv=target'));
          const part = main.querySelector('.compare-shared');
          same(part.querySelector('thead').querySelectorAll('th').map((th) => th.textContent), ['Card', 'Test Deck', 'Burn', 'Free']);
          same(rows('Cards both lists use'), [['Elf', '4', '2', '3 of 6 3 short 1 on the way'], ['Sol Ring', '1', '1', '2 of 2']]);
          assert(part.querySelector('.compare-verdict').textContent.includes('1 card short for both at once'));
          assert(part.textContent.includes('against what both lists need at once'));
          // Each name opens the card viewer, in its own group.
          assert.equal(part.querySelector('tbody').querySelector('[data-viewer]').getAttribute('data-viewer'), 'compare-shared');
        """)

    def test_the_cards_both_use_without_counts(self):
        self.run_js("""
          // A viewer who may not see the space's collection: names and each list's copies only.
          answers = {'/api/compare/shared?': {together: true, counts: false, why_no_counts: null, warnings: [],
              cards: [{name: 'Sol Ring', a: 1, b: 1, need: 2}]},
            '/api/deck?id=casual%2Ftest&': deckA(), '/api/deck?id=casual%2Fburn&': deckB()};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          const part = main.querySelector('.compare-shared');
          same(part.querySelector('thead').querySelectorAll('th').map((th) => th.textContent), ['Card', 'Test Deck', 'Burn']);
          same(rows('Cards both lists use'), [['Sol Ring', '1', '1']]);
          assert.equal(part.querySelector('.compare-verdict'), null);
          assert(!part.textContent.includes('Free'));
          // None at all, and one deck's two lists: the larger count, said so.
          answers['/api/compare/shared?'] = {together: false, counts: true, cards: []};
          clear(main); await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          assert(main.querySelector('.compare-shared').textContent.includes('No card is in both lists'));
        """)

    def test_the_cards_both_use_can_be_fetched_again(self):
        self.run_js("""
          answers = {'/api/compare/shared?': new ApiError(503, 'The database is not reachable.'),
            '/api/deck?id=casual%2Ftest&': deckA(), '/api/deck?id=casual%2Fburn&': deckB()};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          const part = main.querySelector('.compare-shared');
          assert(part.textContent.includes("The cards both lists use couldn't be loaded. The database is not reachable."));
          // The stats still show.
          assert(rows('The two lists in brief').length);
          answers['/api/compare/shared?'] = {together: true, counts: true, cards: [{name: 'Opt', a: 1, b: 1, need: 2, free: 2, short: 0}]};
          part.querySelectorAll('button').find((b) => b.textContent === 'Try again').click(); await settle();
          same(rows('Cards both lists use'), [['Opt', '1', '1', '2 of 2']]);
          assert(main.querySelector('.compare-verdict').textContent.includes('Enough of every card for both at once'));
        """)

    def test_head_to_head_from_forge_and_the_game_log(self):
        self.run_js("""
          const side = (id, version, title, current = true) => ({id, version, title, current});
          const result = (b, updated, value) => ({key: updated, games: 20, updated, winrate: {value, low: value - 0.1, high: value + 0.1},
            sides: [side('casual/test', 'target', 'Test Deck'), b]});
          const full = deckA();
          full.matchups = {results: [result(side('casual/zoo', 'target', 'Zoo'), '2026-10-27T00:00:00Z', 0.5),
            result(side('casual/burn', 'target', 'Burn', false), '2026-10-01T00:00:00Z', 0.4),
            result(side('casual/burn', 'target', 'Burn'), '2026-10-20T00:00:00Z', 0.7),
            result(side('casual/burn', 'owned', 'Burn'), '2026-10-26T00:00:00Z', 0.2)]};
          const game = (x, y, result) => ({record: {sides: [x, y], result, date: '2026-10-2' + result.length}});
          const T = {id: 'casual/test', version: 'target', title: 'Test Deck'}, B = {id: 'casual/burn', version: 'target', title: 'Burn'};
          answers = {'/api/deck?id=casual%2Ftest&version=target&omit': deckA(), '/api/deck?id=casual%2Ftest&version=target': full,
            '/api/deck?id=casual%2Fburn&': deckB(),
            '/api/play?id=casual%2Ftest': {games: [game(T, B, 'a'), game(B, T, 'a'), game(B, T, 'b'), game(T, B, 'draw'),
              game(T, {id: 'casual/zoo', version: 'target', title: 'Zoo'}, 'a'), game(T, {hidden: true, title: 'one of the home decks'}, 'b')]}};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          assert(asked.includes('/api/play?id=casual%2Ftest'));
          // The newest result against Burn's Planned list: not Zoo's, not its Play-now list's.
          const rowsShown = main.querySelector('.compare-forge').querySelectorAll('.mu-row');
          assert.equal(rowsShown.length, 1);
          assert.equal(rowsShown[0].getAttribute('href'), '#/matchup?a=casual%2Ftest&av=target&b=casual%2Fburn&bv=target');
          assert(rowsShown[0].textContent.includes('70%'));
          // The Game log: Test Deck won 2 (once as the second side), Burn 1, 1 draw; the others aren't counted.
          assert.equal(main.querySelector('.compare-games-count').textContent, '4 games: Test Deck 2 wins, Burn 1 win, 1 draw.');
          const log = main.querySelector('.compare-games').querySelector('a');
          same([log.textContent, log.getAttribute('href')], ['Open the Game log', '#/play?id=casual%2Ftest']);
        """)

    def test_head_to_heads_game_log_counts_games_saved_before_a_rename(self):
        self.run_js("""
          // Play records keep the id they were saved under; both decks were renamed since (their old ids are aliases).
          const a = deckA(); a.aliases = ['casual/old-test'];
          const b = deckB(); b.aliases = ['casual/old-burn', 'casual/older-burn'];
          const full = deckA(); full.aliases = a.aliases; full.matchups = {results: []};
          const T = {id: 'casual/old-test', version: 'target'}, B = {id: 'casual/older-burn', version: 'target'};
          answers = {'/api/deck?id=casual%2Ftest&version=target&omit': a, '/api/deck?id=casual%2Ftest&version=target': full,
            '/api/deck?id=casual%2Fburn&': b,
            '/api/play?': {games: [{record: {sides: [T, B], result: 'a'}},
              {record: {sides: [{id: 'casual/old-burn', version: 'target'}, {id: 'casual/test', version: 'target'}], result: 'a'}},
              {record: {sides: [T, {id: 'casual/old-burn', version: 'owned'}], result: 'b'}},
              {record: {sides: [T, {id: 'casual/old-zoo', version: 'target'}], result: 'b'}}]}};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          // The two games between these lists count, whichever id they were saved under; another list or deck doesn't.
          assert.equal(main.querySelector('.compare-games-count').textContent, '2 games: Test Deck 1 win, Burn 1 win.');
        """)

    def test_head_to_head_with_nothing_yet(self):
        self.run_js("""
          const full = deckA(); full.matchups = {results: []};
          answers = {'/api/deck?id=casual%2Ftest&version=target&omit': deckA(), '/api/deck?id=casual%2Ftest&version=target': full,
            '/api/deck?id=casual%2Fburn&': deckB(), '/api/play?': {games: []}};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          const forge = main.querySelector('.compare-forge');
          assert(forge.textContent.includes("Forge hasn't played these two lists against each other yet."));
          const play = forge.querySelector('a');
          same([play.textContent, play.getAttribute('href')], ['Play a matchup', '#/matchup?a=casual%2Ftest&av=target&b=casual%2Fburn&bv=target']);
          const games = main.querySelector('.compare-games');
          assert(games.textContent.includes('No games between these two lists have been recorded.'));
          same([games.querySelector('a').textContent, games.querySelector('a').getAttribute('href')], ['Record a game', '#/play?id=casual%2Ftest']);
          // Matchups that couldn't be worked out (null) say so; a Game log that can't be had offers Try again.
          full.matchups = null;
          answers['/api/play?'] = new ApiError(503, 'The database is not reachable.');
          clear(main); await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          assert(main.querySelector('.compare-forge').textContent.includes("Forge's results couldn't be worked out"));
          assert(main.querySelector('.compare-games').textContent.includes("The Game log couldn't be loaded."));
        """)

    def test_a_decks_two_lists_head_to_head(self):
        self.run_js("""
          const owned = deckA(); owned.version = 'owned';
          const T = {id: 'casual/test', version: 'target', title: 'Test Deck'}, O = {id: 'casual/test', version: 'owned', title: 'Test Deck'};
          answers = {'/api/deck?id=casual%2Ftest&version=target': deckA(), '/api/deck?id=casual%2Ftest&version=owned': owned,
            '/api/play?': {games: [{record: {sides: [O, T], result: 'a'}}, {record: {sides: [T, T], result: 'a'}}]}};
          await show('#/compare?a=casual%2Ftest&b=casual%2Ftest&bv=owned');
          // Named by list; a game of the Planned list against itself isn't one of theirs.
          assert.equal(main.querySelector('.compare-games-count').textContent, '1 game: Planned list 0 wins, Play-now list 1 win.');
        """)

    def test_differences_show_unique_cards_and_quantity_changes(self):
        self.run_js("""
          const a = deckA(), b = deckB();
          a.sections = {Deck: [{name: 'Elf', qty: 4}, {name: 'Forest', qty: 8}, {name: 'Only A', qty: 2}]};
          b.sections = {Deck: [{name: 'Elf', qty: 2}, {name: 'Forest', qty: 10}, {name: 'Only B', qty: 3}]};
          answers = {'/api/deck?id=casual%2Ftest&': a, '/api/deck?id=casual%2Fburn&': b};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          same(rows('Main deck: Only in Test Deck'), [['Only A', '2', '0']]);
          same(rows('Main deck: Only in Burn'), [['Only B', '0', '3']]);
          same(rows('Main deck: Quantity changed'), [['Elf', '4', '2'], ['Forest', '8', '10']]);
          assert.equal(main.querySelectorAll('.compare-difference-printing').length, 0);
          assert(main.textContent.includes('Copies are counted by card name within each section.'));
          assert.equal(asked.length, 5); // The panel uses the existing two deck answers; no extra API.
        """)

    def test_differences_keep_commander_main_and_sideboard_apart(self):
        self.run_js("""
          const a = deckA(), b = deckB();
          a.sections = {Commander: [{name: 'Leader', qty: 1}], Deck: [{name: 'Elf', qty: 4}],
            Sideboard: [{name: 'Elf', qty: 1}]};
          b.sections = {Commander: [{name: 'Other Leader', qty: 1}], Deck: [{name: 'Elf', qty: 2}],
            Sideboard: [{name: 'Elf', qty: 3}]};
          answers = {'/api/deck?id=casual%2Ftest&': a, '/api/deck?id=casual%2Fburn&': b};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          same(main.querySelectorAll('.compare-difference-section').map((p) => p.querySelector('h3').textContent),
            ['Commander', 'Main deck', 'Sideboard']);
          same(rows('Commander: Only in Test Deck'), [['Leader', '1', '0']]);
          same(rows('Commander: Only in Burn'), [['Other Leader', '0', '1']]);
          same(rows('Main deck: Quantity changed'), [['Elf', '4', '2']]);
          same(rows('Sideboard: Quantity changed'), [['Elf', '1', '3']]);
        """)

    def test_a_card_moved_between_sections_is_not_cancelled_out(self):
        self.run_js("""
          const a = deckA(), b = deckB();
          a.sections = {Deck: [{name: 'Opt', qty: 2}]};
          b.sections = {Sideboard: [{name: 'Opt', qty: 2}]};
          answers = {'/api/deck?id=casual%2Ftest&': a, '/api/deck?id=casual%2Fburn&': b};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          same(rows('Main deck: Only in Test Deck'), [['Opt', '2', '0']]);
          same(rows('Sideboard: Only in Burn'), [['Opt', '0', '2']]);
        """)

    def test_differences_sum_duplicate_printings_by_canonical_card_name(self):
        self.run_js("""
          const a = deckA(), b = deckB(), canonical = {name: 'Canonical Elf'};
          a.sections = {Deck: [{name: 'Elf', qty: 2, set: 'fdn', number: '227', card: canonical},
            {name: 'Canonical Elf', qty: 1, set: 'cmm', number: '1', card: canonical}]};
          b.sections = {Deck: [{name: 'Canonical Elf', qty: 5, set: 'fdn', number: '227', card: canonical}]};
          answers = {'/api/deck?id=casual%2Ftest&': a, '/api/deck?id=casual%2Fburn&': b};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          const changed = rows('Main deck: Quantity changed');
          assert.equal(changed.length, 1); assert.equal(changed[0][0], 'Canonical Elf');
          same(changed[0].slice(1), ['3 Listed printings: 1 CMM 1; 2 FDN 227', '5 Listed printings: 5 FDN 227']);
          assert.equal(main.querySelectorAll('.compare-difference-group').length, 1);
          const trigger = main.querySelector('.compare-difference-table').querySelector('[data-viewer]');
          assert(trigger); assert.equal(trigger.getAttribute('data-viewer'), 'compare-difference-Deck-quantity');
        """)

    def test_printing_only_changes_do_not_become_different_card_choices(self):
        self.run_js("""
          const a = deckA(), b = deckB();
          a.sections = {Deck: [{name: 'Elf', qty: 2, set: 'fdn', number: '227'}]};
          b.sections = {Deck: [{name: 'Elf', qty: 2, set: 'fdn', number: '227', finish: 'foil'}]};
          answers = {'/api/deck?id=casual%2Ftest&': a, '/api/deck?id=casual%2Fburn&': b};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          same(rows('Main deck: Printing only'), [['Elf', '2 Listed printings: 2 FDN 227', '2 Listed printings: 2 FDN 227 · foil']]);
          same(main.querySelectorAll('.compare-difference-group').map((p) => p.dataset.kind), ['printing']);
        """)

    def test_printing_distribution_is_compared_after_coalescing_duplicate_rows(self):
        self.run_js("""
          const a = deckA(), b = deckB();
          a.sections = {Deck: [{name: 'Elf', qty: 1, set: 'fdn', number: '227'},
            {name: 'Elf', qty: 1, set: 'FDN', number: '227'}, {name: 'Elf', qty: 1, set: 'cmm', number: '1'}]};
          b.sections = {Deck: [{name: 'Elf', qty: 1, set: 'fdn', number: '227'},
            {name: 'Elf', qty: 2, set: 'cmm', number: '1'}]};
          answers = {'/api/deck?id=casual%2Ftest&': a, '/api/deck?id=casual%2Fburn&': b};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          same(rows('Main deck: Printing only'), [['Elf', '3 Listed printings: 1 CMM 1; 2 FDN 227',
            '3 Listed printings: 2 CMM 1; 1 FDN 227']]);
          b.sections.Deck = [{name: 'Elf', qty: 1, set: 'cmm', number: '1'}, {name: 'Elf', qty: 2, set: 'FDN', number: '227'}];
          answers['/api/deck?id=casual%2Fburn&'] = b;
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          assert(main.textContent.includes('The lists have the same cards, quantities and listed printings.'));
        """)

    def test_quantity_and_printing_redistribution_are_both_shown(self):
        self.run_js("""
          const a = deckA(), b = deckB();
          a.sections = {Deck: [{name: 'Elf', qty: 2, set: 'fdn', number: '227'},
            {name: 'Elf', qty: 1, set: 'cmm', number: '1'}]};
          b.sections = {Deck: [{name: 'Elf', qty: 1, set: 'fdn', number: '227'},
            {name: 'Elf', qty: 3, set: 'cmm', number: '1'}]};
          answers = {'/api/deck?id=casual%2Ftest&': a, '/api/deck?id=casual%2Fburn&': b};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          same(rows('Main deck: Quantity changed'), [['Elf', '3 Listed printings: 1 CMM 1; 2 FDN 227',
            '4 Listed printings: 3 CMM 1; 1 FDN 227']]);
          same(main.querySelectorAll('.compare-difference-group').map((p) => p.dataset.kind), ['quantity']);
        """)

    def test_unspecified_printings_never_use_the_representative_image(self):
        self.run_js("""
          const a = deckA(), b = deckB();
          a.sections = {Deck: [{name: 'Forest', qty: 8, card: {name: 'Forest', set: 'fdn', number: '280'}}]};
          b.sections = {Deck: [{name: 'Forest', qty: 8, card: {name: 'Forest', set: 'cmm', number: '420'}}]};
          answers = {'/api/deck?id=casual%2Ftest&': a, '/api/deck?id=casual%2Fburn&': b};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          assert(main.textContent.includes('The lists have the same cards, quantities and listed printings.'));
          b.sections.Deck[0].set = 'fdn'; b.sections.Deck[0].number = '280';
          answers['/api/deck?id=casual%2Fburn&'] = b;
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          same(rows('Main deck: Printing only'), [['Forest', '8 Listed printings: 8 Any printing', '8 Listed printings: 8 FDN 280']]);
        """)

    def test_differences_reverse_when_sides_are_swapped(self):
        self.run_js("""
          const a = deckA(), b = deckB();
          a.sections = {Deck: [{name: 'Alpha', qty: 1}, {name: 'Elf', qty: 4}]};
          b.sections = {Deck: [{name: 'Beta', qty: 3}, {name: 'Elf', qty: 2}]};
          answers = {'/api/deck?id=casual%2Ftest&': a, '/api/deck?id=casual%2Fburn&': b};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          await show(compareHref(b.summary.id, a.summary.id, b.version, a.version));
          same(rows('Main deck: Only in Burn'), [['Beta', '3', '0']]);
          same(rows('Main deck: Only in Test Deck'), [['Alpha', '0', '1']]);
          same(rows('Main deck: Quantity changed'), [['Elf', '2', '4']]);
        """)

    def test_identical_lists_and_empty_lists_have_one_difference_empty_state(self):
        self.run_js("""
          const a = deckA();
          a.sections = {Deck: [{name: 'Elf', qty: 2}]};
          answers = {'/api/deck?id=casual%2Ftest&': a};
          await show('#/compare?a=casual%2Ftest&b=casual%2Ftest');
          assert.equal(main.querySelectorAll('.compare-difference-section').length, 0);
          assert(main.textContent.includes('The lists have the same cards, quantities and listed printings.'));
          a.sections = {}; answers['/api/deck?id=casual%2Ftest&'] = a;
          await show('#/compare?a=casual%2Ftest&b=casual%2Ftest');
          assert(main.textContent.includes('The lists have the same cards, quantities and listed printings.'));
        """)

    def test_differences_work_without_stats_or_collection_visibility(self):
        self.run_js("""
          const a = deckA(), b = deckB();
          for (const d of [a, b]) { d.stats = null; d.owned = null; d.availability = null; }
          a.sections = {Deck: [{name: 'Unknown card name', qty: 1, card: null}]};
          b.sections = {Deck: [{name: 'Unknown card name', qty: 3, card: null}]};
          answers = {'/api/deck?id=casual%2Ftest&': a, '/api/deck?id=casual%2Fburn&': b};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          same(rows('Main deck: Quantity changed'), [['Unknown card name', '1', '3']]);
          const differencePanel = main.querySelectorAll('.compare-part').find((p) => p.querySelector('h2').textContent === 'List differences');
          assert(!differencePanel.textContent.includes('Free')); assert(!differencePanel.querySelector('[data-viewer]'));
        """)

    def test_differences_use_the_selected_planned_and_play_now_lists(self):
        self.run_js("""
          const target = deckA(), owned = deckA(); owned.version = 'owned';
          target.sections = {Deck: [{name: 'Elf', qty: 4}]};
          owned.sections = {Deck: [{name: 'Elf', qty: 2}, {name: 'Opt', qty: 2}]};
          answers = {'/api/deck?id=casual%2Ftest&version=target': target,
            '/api/deck?id=casual%2Ftest&version=owned': owned};
          await show('#/compare?a=casual%2Ftest&b=casual%2Ftest&bv=owned');
          same(rows('Main deck: Quantity changed'), [['Elf', '4', '2']]);
          same(rows('Main deck: Only in Play-now list'), [['Opt', '0', '2']]);
          const table = main.querySelector('.compare-difference-table');
          same(table.querySelector('thead').querySelectorAll('th').map((th) => th.textContent),
            ['Card', 'Planned list', 'Play-now list']);
        """)

    def test_a_hidden_first_deck_reveals_no_difference_cards_from_either_list(self):
        self.run_js("""
          answers = {'/api/deck?id=user2%2Fcasual%2Felves&': new ApiError(404, "No deck 'user2/casual/elves'"),
            '/api/deck?id=casual%2Ftest&': deckA()};
          await show('#/compare?a=user2%2Fcasual%2Felves&b=casual%2Ftest');
          assert.equal(main.querySelector('.compare-difference-section'), null);
          assert.equal(main.querySelector('table'), null);
          assert(!main.textContent.includes('Test Deck')); assert(!main.textContent.includes('Elf'));
        """)

    def test_a_companion_is_kept_in_its_own_difference_section(self):
        self.run_js("""
          const a = deckA(), b = deckB();
          a.sections = {Companion: [{name: 'Companion card', qty: 1}]}; b.sections = {};
          answers = {'/api/deck?id=casual%2Ftest&': a, '/api/deck?id=casual%2Fburn&': b};
          await show('#/compare?a=casual%2Ftest&b=casual%2Fburn');
          same(rows('Companion: Only in Test Deck'), [['Companion card', '1', '0']]);
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

    def test_two_decks_chosen_from_the_library(self):
        self.run_js("""
          const decks = [{id: 'casual/zoo', title: 'Zoo', colors: ['R', 'G'], versions: ['target']},
            {id: 'casual/test', title: 'Test Deck', colors: ['G'], versions: ['target', 'owned']},
            {id: 'casual/broken', title: 'Broken', error: 'unreadable'}];
          openCompareFirst(decks); await settle();
          let sheet = document.querySelector('.sheet');
          assert.equal(sheet.querySelector('h2').textContent, 'Compare two decks');
          const firsts = sheet.querySelectorAll('.compare-choice');
          same(firsts.map((b) => b.textContent), ['Test Deck', 'Zoo']);
          firsts[0].click(); await settle();
          // The second from the same decks (nothing fetched again), with the first's own other list.
          assert(!asked.includes('/api/decks'));
          sheet = document.querySelectorAll('.sheet').find((s) => s.querySelector('h2').textContent === 'Compare with…');
          same(sheet.querySelectorAll('.compare-choice').map((a) => [a.textContent, a.getAttribute('href')]), [
            ['Test Deck: its play-now list', '#/compare?a=casual%2Ftest&b=casual%2Ftest&bv=owned'],
            ['Zoo', '#/compare?a=casual%2Ftest&b=casual%2Fzoo']]);
          // One deck isn't two.
          openCompareFirst(decks.slice(0, 1)); await settle();
          assert(document.querySelectorAll('.sheet').at(-1).textContent.includes("There aren't two decks to compare yet."));
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
