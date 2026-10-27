"""The deck header's neighbouring visible decks and actual last-edited metadata, with no live reads."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, WEB, RUNNER

FIXTURE = PAGE + """
  const shelfDeck = (id, title, extra = {}) => ({...makePage().summary, id, title, versions: ['target'],
    ...extra});
  const shelves = [shelfDeck('casual/a', 'Alpha'), shelfDeck('casual/test', 'Test Deck'),
    shelfDeck('casual/z', 'Zulu', {versions: ['target', 'owned']})];
  const settle = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
  const navigation = () => main.querySelector('.deck-neighbours');
  const links = () => navigation().querySelectorAll('a');
  const shelfApi = (decks = shelves) => { api = async (url) => url === '/api/decks' ? {decks} : {tests: [], opponents: []}; };
  state.libraryHash = '#/library?all=1&sort=name';
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckHeaderUiTests(unittest.TestCase):
    def run_js(self, code):
        done = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_neighbours_keep_tab_filter_and_available_list(self):
        self.run_js("""
          shelfApi(); const page = makePage(); page.version = 'owned';
          clear(main); location.hash = '#/deck?id=casual%2Ftest&v=owned&tab=cards&filter=held';
          drawDeck(page, deckViewOf(parseHash().params)); await settle();
          assert.equal(navigation().hidden, false);
          same(links().map((link) => link.getAttribute('aria-label')), ['Previous deck: Alpha', 'Next deck: Zulu']);
          assert(links()[0].getAttribute('href').includes('v=target&tab=cards&filter=held'));
          assert(links()[1].getAttribute('href').includes('v=owned&tab=cards&filter=held'));
          assert(navigation().textContent.includes('2 of 3'));
          tab('stats').click();
          assert(links().every((link) => link.getAttribute('href').endsWith('&tab=stats')));
          links()[1].click();
          assert(state.libraryHash.includes('deck=casual%2Fz'));
          assert(state.libraryHash.includes('sort=name'));
        """)

    def test_filtered_order_and_bounds_with_no_wrap(self):
        self.run_js("""
          const decks = [...shelves, shelfDeck('commander/hidden-by-filter', 'Other format', {kind: 'commander'}),
            shelfDeck('casual/broken', 'Broken', {error: 'unreadable'})];
          state.libraryHash = '#/library?all=1&format=casual&sort=name';
          shelfApi(decks); open('#/deck?id=casual%2Ftest&v=target'); await settle();
          assert(navigation().textContent.includes('2 of 3'));
          assert(!navigation().textContent.includes('Other format'));
          shelfApi([shelves[1], shelves[2]]); open('#/deck?id=casual%2Ftest&v=target'); await settle();
          assert.equal(navigation().querySelector('button').disabled, true);
          assert.equal(links().length, 1); assert(links()[0].getAttribute('aria-label').startsWith('Next'));
          shelfApi([shelves[0], shelves[1]]); open('#/deck?id=casual%2Ftest&v=target'); await settle();
          assert.equal(links().length, 1); assert(links()[0].getAttribute('aria-label').startsWith('Previous'));
        """)

    def test_direct_link_outside_filters_uses_only_fresh_visible_decks(self):
        self.run_js("""
          state.library = {decks: [shelfDeck('user2/casual/private', 'Old private name')]};
          state.libraryHash = '#/library?all=1&format=commander';
          shelfApi([shelves[1], shelves[2]]); open('#/deck?id=casual%2Ftest&v=target'); await settle();
          assert(navigation().textContent.includes('1 of 2'));
          assert(!main.textContent.includes('Old private name'));
          assert(!links().some((link) => link.getAttribute('href').includes('private')));
          shelfApi([shelves[2]]); open('#/deck?id=casual%2Ftest&v=target'); await settle();
          assert.equal(navigation().hidden, true);
        """)

    def test_late_navigation_cannot_cross_person_route_screen_or_attachment(self):
        self.run_js("""
          for (const change of ['person', 'route', 'screen', 'attachment']) {
            state.profile = {id: 'matt', plays_as: 'user'}; let resolve;
            api = (url) => url === '/api/decks' ? new Promise((r) => resolve = r) : Promise.resolve({tests: [], opponents: []});
            open('#/deck?id=casual%2Ftest&v=target'); const nav = navigation();
            if (change === 'person') state.profile = {id: 'user1'};
            if (change === 'route') routeToken++;
            if (change === 'screen') deckScreen = {...deckScreen};
            if (change === 'attachment') clear(main);
            resolve({decks: shelves}); await settle();
            assert.equal(nav.hidden, true, change); assert.equal(nav.children.length, 0);
          }
        """)

    def test_failure_can_retry_and_recorded_dates_stay_honest(self):
        self.run_js("""
          api = async (url) => { if (url === '/api/decks') throw new Error('offline'); return {}; };
          open('#/deck?id=casual%2Ftest&v=target'); await settle();
          assert(navigation().textContent.includes("couldn't be loaded"));
          shelfApi(); buttonText(navigation(), 'Try again').click(); await settle();
          assert(navigation().textContent.includes('2 of 3'));
          assert.equal(deckChangedDate(null), null); assert.equal(deckChangedDate('bad date'), null);
          const date = deckChangedDate('2026-01-02T03:04:00+10:00');
          assert.equal(date.getAttribute('datetime'), '2026-01-01T17:04:00.000Z');
          assert(date.textContent.startsWith('Last changed '));
          assert(date.getAttribute('title').includes('Last changed'));
          const page = makePage(); page.summary.edited = '2026-01-02T03:04:00+10:00';
          assert(deckHeader(page).querySelector('time').textContent.startsWith('Last changed'));
          page.summary.read_only = true; assert.equal(deckNeighbours(page), null);
        """)

    def test_a_newer_retry_wins_over_an_older_answer(self):
        self.run_js("""
          api = async (url) => { if (url === '/api/decks') throw new Error('offline'); return {}; };
          open('#/deck?id=casual%2Ftest&v=target'); await settle();
          const pending = [];
          api = () => new Promise((resolve) => pending.push(resolve));
          const retry = buttonText(navigation(), 'Try again'); retry.click(); retry.click();
          pending[1]({decks: [shelves[1], shelves[2]]}); await settle();
          assert(navigation().textContent.includes('1 of 2'));
          pending[0]({decks: shelves}); await settle();
          assert(navigation().textContent.includes('1 of 2'));
          assert(!navigation().textContent.includes('2 of 3'));
        """)
