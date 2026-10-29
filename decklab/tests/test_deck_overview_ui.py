"""P1 Overview summaries: saved Forge results, displayed-list curve and late-answer isolation."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, WEB, RUNNER


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckOverviewUiTests(unittest.TestCase):
    def run_js(self, code):
        done = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), PAGE + code, True]),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_field_and_latest_swap_without_opening_matchups(self):
        self.run_js("""
          const calls = [];
          const field = {format: 'casual', deck: {id: 'casual/test', version: 'target'},
            opponents: [{id: 'casual/other', title: 'Other', games: 400,
              rate: {value: .64, low: .60, high: .68}, residual: {flag: 'strong', r: .12}}],
            average: {value: .64, low: .60, high: .68, partial: true, counted: 1, of: 2},
            rating: {value: 1600, rank: 1, of: 3, h_points: 5}, last_run: {when: '2026-10-24'}};
          const test = {test: 'test-one', changes: {remove: [[1, 'Elf']], add: [[1, 'Bolt']]},
            against: 'field', delta: .02, low: -.01, high: .05, verdict: 'slightly_better', when: '2026-10-24'};
          api = async (url) => { calls.push(url); return url.startsWith('/api/field') ? field : {tests: [test]}; };
          open('#/deck?id=casual%2Ftest&v=target');
          await Promise.resolve(); await Promise.resolve();
          const overview = panel('overview');
          assert(overview.querySelector('.deck-overview-forge').textContent.includes('64'));
          assert(overview.textContent.includes('Based on 1 of 2 decks'));
          assert(overview.textContent.includes('Going first is worth about 5 points'));
          assert(overview.textContent.includes('Does better than expected'));
          assert(overview.querySelector('.deck-overview-swap').textContent.includes('not proven'));
          assert.equal(panel('matchups').children.length, 0);
          const summaries = calls.filter((url) => url.startsWith('/api/field?') || url.startsWith('/api/variants?'));
          assert.equal(summaries.length, 2);
          assert(summaries.every((url) => url.includes('version=target')));
          assert.equal(main.querySelector('#sec-field'), null);
          overview.querySelector('.deck-overview-forge').querySelector('button').click();
          assert.equal(tab('matchups').getAttribute('aria-selected'), 'true');
          assert.equal(main.querySelectorAll('#h-overview-forge').length, 1);
          assert.equal(main.querySelectorAll('#sec-field').length, 1);
        """)

    def test_empty_unavailable_and_retry_states(self):
        self.run_js("""
          let fail = true;
          api = async (url) => {
            if (url.startsWith('/api/variants')) return {tests: []};
            if (fail) throw new Error('offline');
            return {format: 'casual', opponents: []};
          };
          open('#/deck?id=casual%2Ftest&v=target');
          await Promise.resolve(); await Promise.resolve();
          const forge = panel('overview').querySelector('.deck-overview-forge');
          assert(forge.textContent.includes("couldn't be loaded"));
          assert(panel('overview').textContent.includes('No swap tests yet.'));
          fail = false; buttonText(forge, 'Try again').click();
          await Promise.resolve(); await Promise.resolve();
          assert(forge.textContent.includes('No other decks'));
          assert(!forge.textContent.includes('Try again'));
        """)

    def test_late_reads_ignore_route_profile_and_replacement_screen(self):
        self.run_js("""
          for (const change of ['route', 'profile', 'screen', 'detached']) {
            state.profile = {id: 'matt', plays_as: 'user'};
            const pending = [];
            api = (url) => new Promise((resolve, reject) => pending.push({resolve, reject}));
            open('#/deck?id=casual%2Ftest&v=target');
            const overview = panel('overview');
            const before = overview.textContent;
            if (change === 'route') routeToken += 1;
            if (change === 'profile') state.profile = {id: 'user1'};
            if (change === 'screen') deckScreen = {...deckScreen};
            if (change === 'detached') clear(main);
            pending[0].resolve({format: 'casual', opponents: []});
            pending[1].reject(new Error('offline'));
            await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
            assert.equal(overview.textContent, before, change);
          }
        """)

    def test_poor_ai_caveat_follows_the_displayed_list(self):
        self.run_js("""
          const field = (pilot) => ({format: 'casual', deck: {id: 'casual/test', version: 'target'},
            opponents: [{id: 'casual/other', title: 'Other', games: 400, rate: {value: .64, low: .60, high: .68}}],
            average: {value: .64, low: .60, high: .68, counted: 1, of: 1}, pilot});
          const poor = {poor: true, why: 'share', cards: [{name: 'Elf', qty: 6, why: ['flash']}]};
          // As the app's route does on a list switch: a new route token, and the page drawn for that list.
          const openList = (version) => { clear(main); location.hash = `#/deck?id=casual%2Ftest&v=${version}`;
            routeToken += 1; drawDeck({...makePage(), version}, deckViewOf(parseHash().params)); };
          const settle = async () => { for (let i = 0; i < 4; i++) await Promise.resolve(); };
          const caveat = () => panel('overview').querySelector('.deck-overview-forge').querySelector('.deck-overview-pilot');
          let answers = {}; const calls = [];
          api = async (url) => { calls.push(url);
            if (!url.startsWith('/api/field?')) return {tests: []};
            return answers[new URLSearchParams(url.split('?')[1]).get('version')]; };
          // Poor: Matchups' own words, beside the field line.
          answers = {target: field(poor)};
          open('#/deck?id=casual%2Ftest&v=target'); await settle();
          assert(caveat().textContent.includes('Forge pilots this deck poorly'));
          assert(caveat().textContent.includes(pilotReason(poor)));
          assert(calls.some((url) => url.startsWith('/api/field?') && url.includes('version=target')
            && url.includes('pilot=1')));
          // Normal, and unknown (null or left out): nothing extra, and no all-clear either.
          for (const pilot of [{poor: false, why: null, cards: []}, null, undefined]) {
            answers = {target: field(pilot)};
            open('#/deck?id=casual%2Ftest&v=target'); await settle();
            assert.equal(caveat(), null, JSON.stringify(pilot));
            assert(!panel('overview').textContent.includes('pilots'), JSON.stringify(pilot));
            assert(panel('overview').querySelector('.deck-overview-forge').textContent.includes('64'));
          }
          // Switching lists: the Play-now list's own answer decides.
          answers = {target: field(poor), owned: field({poor: false, cards: []})};
          openList('target'); await settle();
          assert(caveat());
          openList('owned'); await settle();
          assert.equal(caveat(), null);
          assert(calls.some((url) => url.startsWith('/api/field?') && url.includes('version=owned')));
        """)

    def test_a_late_poor_answer_for_the_other_list_draws_nothing(self):
        self.run_js("""
          const pending = [];
          api = (url) => url.startsWith('/api/field?')
            ? new Promise((resolve) => pending.push({url, resolve})) : Promise.resolve({tests: []});
          const answer = (pilot) => ({format: 'casual', deck: {id: 'casual/test'},
            opponents: [{id: 'casual/other', title: 'Other', games: 400, rate: {value: .5, low: .4, high: .6}}],
            average: {value: .5, low: .4, high: .6, counted: 1, of: 1}, pilot});
          // As the app's route does on a list switch: a new route token, and the page drawn for that list.
          const openList = (version) => { clear(main); location.hash = `#/deck?id=casual%2Ftest&v=${version}`;
            routeToken += 1; drawDeck({...makePage(), version}, deckViewOf(parseHash().params)); };
          openList('target');
          openList('owned');
          const owned = pending.find((p) => p.url.includes('version=owned'));
          const target = pending.find((p) => p.url.includes('version=target'));
          owned.resolve(answer({poor: false, cards: []}));
          for (let i = 0; i < 4; i++) await Promise.resolve();
          target.resolve(answer({poor: true, why: 'commander', cards: []}));
          for (let i = 0; i < 4; i++) await Promise.resolve();
          assert(!main.textContent.includes('pilots this deck poorly'));
          assert(main.querySelector('.deck-overview-forge').textContent.includes('50'));
        """)

    def test_curve_has_words_and_no_inventory_dependency(self):
        self.run_js("""
          const page = makePage(); delete page.owned;
          page.stats = {curve: {buckets: [{mv: '0', total: 0}, {mv: '1', total: 4}, {mv: '2', total: 2}]}};
          const curve = deckOverviewCurve(page);
          assert(curve.querySelector('[role=img]').getAttribute('aria-label').includes('1: 4, 2: 2'));
          assert(curve.getAttribute('style').includes('180deg'));
          assert(!curve.textContent.includes('owned'));
          page.stats = null; assert.equal(deckOverviewCurve(page), null);
          page.summary.read_only = true; assert.equal(deckOverviewSwap(page), null);
          page.summary.id = BOX_PREFIX + 'test'; assert.equal(deckOverviewForge(page), null);
        """)

    def test_member_deck_can_reach_all_tests(self):
        self.run_js("""
          api = async () => ({tests: []});
          const page = makePage(); page.summary.id = 'user2/casual/test';
          const tests = variantTestsSection(page); main.append(tests);
          assert.equal(tests.getAttribute('id'), 'sec-tests');
          await Promise.resolve();
          assert(tests.textContent.includes('No tests of changes yet'));
          page.summary.read_only = true; assert.equal(variantTestsSection(page), null);
        """)

    def test_incoming_all_tests_link_jumps_only_while_its_deck_remains(self):
        self.run_js("""
          api = async () => ({tests: []});
          const jumped = []; jumpTo = (id) => jumped.push(id);
          location.hash = '#/deck?id=casual%2Ftest&v=target&tab=matchups&part=tests';
          main.append(variantTestsSection(makePage())); flushTimers();
          same(jumped, ['sec-tests']);
          main.append(variantTestsSection(makePage())); routeToken++; flushTimers();
          same(jumped, ['sec-tests']);
          variantTestsSection(makePage()); flushTimers();
          same(jumped, ['sec-tests']);
        """)

    def test_late_field_growth_keeps_the_jump_until_the_reader_scrolls(self):
        self.run_js("""
          let release, fieldContext;
          api = (url) => url.startsWith('/api/field?') ? new Promise((resolve) => release = resolve)
            : Promise.resolve(url === '/api/decks' ? {decks: []} : url.startsWith('/api/deck?')
              ? {...makePage(), matchups: null} : {tests: []});
          const actualDraw = fvDraw;
          fvDraw = (ctx, answer) => { fieldContext = ctx; actualDraw(ctx, answer);
            target.box.top += 300; target.box.bottom += 300; };
          const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
          open('#/deck?id=casual%2Ftest&v=target&tab=matchups'); await settle();
          const target = main.querySelector('#sec-tests'); target.box = {top: 200, bottom: 400, left: 0, right: 800};
          const scrolls = []; window.scrollBy = (x, y) => scrolls.push(y);
          jumpTo('sec-tests'); release({format: 'casual', opponents: []}); await settle();
          assert(scrolls.includes(300), 'late content keeps the destination at its prior screen line');
          window.fire('wheel'); const before = scrolls.length;
          const refreshing = fvRefresh(fieldContext); release({format: 'casual', opponents: []}); await refreshing;
          assert.equal(scrolls.length, before, 'manual scrolling releases the jump anchor');
        """)

    def test_late_opponent_library_keeps_the_tests_jump_in_place(self):
        self.run_js("""
          clear(main); state.library = null;
          let release, target = null;
          api = (url) => url === '/api/decks' ? new Promise((resolve) => release = resolve)
            : Promise.resolve({tests: []});
          const actualDraw = drawDeckMatchups;
          drawDeckMatchups = (host, data, matchups) => {
            actualDraw(host, data, matchups);
            if (target && state.library) { target.box.top += 240; target.box.bottom += 240; }
          };
          const data = {...makePage(), matchups: {results: [], running: []}};
          main.append(deckMatchupsPart(data), variantTestsSection(data));
          target = main.querySelector('#sec-tests');
          target.box = {top: 200, bottom: 400, left: 0, right: 800};
          const scrolls = []; window.scrollBy = (x, y) => scrolls.push(y);
          jumpTo('sec-tests');
          release({decks: [data.summary, {id: 'casual/other', title: 'Other', kind: 'casual'}]});
          for (let i = 0; i < 8; i++) await Promise.resolve();
          assert(main.querySelector('#sec-matchups').textContent.includes('Not played yet against: Other.'));
          assert(scrolls.includes(240), 'late opponent names keep the tests heading at its prior screen line');
          assert.equal(document.activeElement, target);
        """)
