"""P1 Overview summaries: saved Forge results, displayed-list curve and late-answer isolation."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, WEB, RUNNER

# A fixed 2 Nov of this year at noon UTC: 2 Nov in every time zone the PC and CI run in, and no year shown.
DAY = "const day=`${new Date().getFullYear()}-11-02T12:00:00Z`;const hasClass=(n,c)=>!!n&&(n.getAttribute('class')||'').split(' ').includes(c);"


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

    def test_last_played_and_what_changed_since(self):
        self.run_js("""
          api = async (url) => url.startsWith('/api/field') ? {format: 'casual', opponents: []} : {tests: []};
          const draw = (played, summary = {}) => {
            clear(main); location.hash = '#/deck?id=casual%2Ftest&v=target';
            const page = makePage();
            drawDeck({...page, summary: {...page.summary, ...summary}, played}, deckViewOf(parseHash().params));
            return panel('overview').querySelector('.deck-overview-played');
          };
          // Games that couldn't be read: no line at all, never "not played".
          assert.equal(draw(null), null);
          assert.equal(draw(undefined), null);
          const empty = draw({last: null, games: 0, since: null});
          assert.equal(empty.querySelector('.deck-played').textContent, 'Not played at home yet');
          assert.equal(empty.querySelector('h2'), null);
          // The Game log narrowed to the deck, in plain sight (E11-S61).
          assert.equal(empty.querySelector('.deck-played-log').textContent, 'Record a game');
          assert.equal(empty.querySelector('.deck-played-log').getAttribute('href'), '#/play?id=casual%2Ftest');
          let part = draw({last: '2026-10-20', games: 3, since: {version: 'target', changes: [], more: 0}});
          assert.equal(part.querySelector('.deck-played').textContent, 'Last played 2026-10-20 · 3 games');
          assert.equal(part.querySelector('h2').textContent, 'Played at home');
          const log = part.querySelector('.deck-played-log');
          assert(log.closest('.deck-section-head'));
          assert.equal(log.textContent, 'Open the Game log');
          assert.equal(log.getAttribute('href'), '#/play?id=casual%2Ftest');
          assert(part.textContent.includes("Its list hasn't changed since that game."));
          part = draw({last: '2026-10-20', games: 1, since: null});
          assert(part.textContent.includes('1 game'));
          assert(!part.textContent.includes('changed'));
          part = draw({last: '2026-10-20', games: 2, since: {version: 'owned', more: 2, changes: [
            {section: 'Deck', name: 'Sol Ring', delta: 1, printing: false},
            {section: 'Deck', name: 'Elvish Mystic', delta: -2, printing: true},
            {section: 'Sideboard', name: 'Pick Your Poison', delta: 0, printing: true}]}});
          same(part.querySelectorAll('li').map((li) => li.textContent), ['Added 1 Sol Ring',
            'Took out 2 Elvish Mystic, another printing', 'Changed the printing of Pick Your Poison (sideboard)']);
          assert(part.textContent.includes('Its Play-now list has changed since that game:'));
          assert(part.textContent.includes('And 2 more changes; its History has them all.'));
          assert.equal(part.querySelector('.deck-played-since').querySelector('a').getAttribute('href'), '#/history?id=casual%2Ftest&v=owned');
          // A read-only (product or pairing) page has no History link, but keeps its Game log.
          part = draw({last: '2026-10-20', games: 2, since: {version: 'target', more: 1, changes: []}}, {read_only: true});
          assert.equal(part.querySelector('.deck-played-since').querySelector('a'), null);
          same(part.querySelectorAll('a').map((a) => a.textContent), ['Open the Game log']);
          assert(part.textContent.includes('And 1 more change.'));
        """)

    # ------------------------------------------------------------------ E3-S33: Against popular decks

    GAUNTLET = """
      const calls = [], writes = [];
      let summary = null;
      apiWrite = async (path, body) => { writes.push(path); return {}; };
      api = async (url) => { calls.push(url);
        if (url.startsWith('/api/gauntlet/summary?')) return structuredClone(summary);
        if (url.startsWith('/api/field')) return {format: 'casual', opponents: []};
        return {tests: []}; };
      const settle = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
      const commanderPage = () => { const page = makePage();
        page.summary = {...page.summary, id: 'commander/test', kind: 'commander'}; return page; };
      const show = async (page = makePage()) => { clear(main);
        location.hash = `#/deck?id=${encodeURIComponent(page.summary.id)}&v=target`;
        drawDeck(page, deckViewOf(parseHash().params)); await settle();
        return panel('overview').querySelector('.deck-overview-gauntlet'); };
      const now = new Date().toISOString();
      const done = (extra = {}) => ({deck: {id: 'commander/test', version: 'target'}, format: 'commander',
        state: 'done', playing: null, overall: {key: 'all', label: 'All these opponents', opponents: 20, games: 2000,
          rate: .47, low: .39, high: .55}, played: 20, of: 20, games: 2000,
        tally: {ahead: 3, even: 14, behind: 3, unsettled: 0},
        hardest: [{title: 'Krenko, Mob Boss', tier: 'core', style: 'aggro', rate: .31, low: .22, high: .41,
          verdict: 'behind', source: {kind: 'edhrec'}}], updated: now,
        sample: {id: 'sample:40d5bec2d5ad', size: 20, tiers: ['core', 'upgraded']}, note: null, notes: [],
        build_command: null, ...extra});
    """

    def test_popular_decks_lead_a_commander_overview_and_follow_the_field_for_60_card(self):
        self.run_js(self.GAUNTLET + """
          summary = done();
          await show(commanderPage());
          const order = () => panel('overview').querySelector('.deck-overview-sims').children
            .map((n) => n.getAttribute('class').split(' ').find((c) => c.startsWith('deck-overview-')));
          same(order(), ['deck-overview-gauntlet', 'deck-overview-forge']);
          summary = done({format: 'constructed'});
          await show();
          same(order(), ['deck-overview-forge', 'deck-overview-gauntlet']);
          const page = makePage(); page.summary.id = BOX_PREFIX + 'cats';
          assert.equal(deckOverviewGauntlet(page), null); assert.equal(deckOverviewStrength(page), null);
        """)

    def test_a_tested_deck_shows_its_headline_hardest_and_caveat_from_one_read(self):
        self.run_js(self.GAUNTLET + """
          summary = done();
          const part = await show(commanderPage());
          const head = part.querySelector('.gt-headline-panel');
          assert(head.textContent.includes('Against 20 popular Commander decks:'), head.textContent);
          assert(head.textContent.includes('47')); assert(head.textContent.includes('2,000 games'));
          assert(head.querySelector('.fresh'));
          assert.equal(head.querySelector('.gt-tally').textContent, 'Ahead of 3 · even with 14 · behind 3');
          assert(part.textContent.includes('Hardest here:'));
          assert(part.querySelector('.deck-overview-hardest').textContent.includes('Krenko, Mob Boss'));
          assert(part.querySelector('.deck-overview-hardest').textContent.includes(', behind'));
          assert(part.textContent.includes("These 20 sampled opponents only, not every deck of that colour or style. " +
            "Forge's AI, best of one, 1v1."));
          // Figures in ink: no strong or weak colours, no flags.
          assert(!part.querySelector('.flag')); assert(!part.querySelector('.is-good'));
          // One read, with the list and the viewer; no timer, no write.
          const reads = calls.filter((u) => u.startsWith('/api/gauntlet'));
          same(reads, ['/api/gauntlet/summary?id=commander%2Ftest&version=target&profile=matt']);
          flushTimers(); await settle();
          assert.equal(calls.filter((u) => u.startsWith('/api/gauntlet')).length, 1);
          assert.equal(writes.length, 0);
          // Its button opens Matchups at the part, and starts nothing.
          const button = buttonText(part, 'Popular decks'); assert(button && !button.hidden);
          button.click(); await settle();
          assert.equal(tab('matchups').getAttribute('aria-selected'), 'true');
          assert(main.querySelector('#sec-gauntlet'));
          assert.equal(writes.length, 0);
        """)

    def test_each_state_of_the_popular_decks_panel(self):
        self.run_js(self.GAUNTLET + """
          summary = done({state: 'partial', played: 5, tally: {ahead: 1, even: 3, behind: 1, unsettled: 0}});
          let part = await show(commanderPage());
          assert(part.textContent.includes('5 of 20 opponents tested so far.'));
          assert(buttonText(part, 'Popular decks'));
          summary = done({state: 'untested', overall: null, played: 0, games: 0, hardest: [], updated: null,
            tally: {ahead: 0, even: 0, behind: 0, unsettled: 0}});
          part = await show(commanderPage());
          assert(part.textContent.includes('Not tested against popular decks yet.'));
          assert(!part.querySelector('.gt-headline-panel'));
          const choose = buttonText(part, 'Choose opponents'); assert(choose);
          summary = done({state: 'untested', overall: null, played: 0, games: 0, hardest: [],
            playing: {status: 'running', done: 40, total: 2000, standard: true}});
          part = await show(commanderPage());
          assert(part.textContent.includes('A popular-decks run is in progress.'));
          assert(!part.textContent.includes('Matt'));
          // No catalogue: a member sees only that; an admin also gets the command that builds it.
          summary = done({state: 'no_catalogue', overall: null, played: 0, of: 0, sample: null, hardest: []});
          part = await show(commanderPage());
          assert(part.textContent.includes("Popular decks aren't set up on this PC yet."));
          assert.equal(part.querySelector('code'), null);
          assert.equal(buttonText(part, 'Popular decks').hidden, true);
          summary = done({state: 'no_catalogue', overall: null, played: 0, of: 0, sample: null, hardest: [],
            build_command: 'python -m decklab.lib.forge gauntlet build --format commander'});
          part = await show(commanderPage());
          assert.equal(part.querySelector('code').textContent, 'python -m decklab.lib.forge gauntlet build --format commander');
        """)

    def test_a_late_popular_decks_read_draws_nothing_on_another_page(self):
        self.run_js(self.GAUNTLET + """
          let release;
          api = (url) => url.startsWith('/api/gauntlet/summary?') ? new Promise((resolve) => { release = resolve; })
            : Promise.resolve(url.startsWith('/api/field') ? {format: 'casual', opponents: []} : {tests: []});
          clear(main); location.hash = '#/deck?id=commander%2Ftest&v=target';
          drawDeck(commanderPage(), deckViewOf(parseHash().params));
          const part = panel('overview').querySelector('.deck-overview-gauntlet');
          const before = part.textContent;
          routeToken += 1; release(done()); await settle();
          assert.equal(part.textContent, before);
        """)

    # ------------------------------------------------------------------ E3-S34: kept through a change

    def test_a_changed_list_shows_its_old_figure_and_test_the_new_list_starts_nothing(self):
        self.run_js(DAY + self.GAUNTLET + """
          summary = done({state: 'stale_list', overall: null, played: 0, games: 0, hardest: [], updated: null,
            tally: {ahead: 0, even: 0, behind: 0, unsettled: 0},
            before: {rate: .41, low: .33, high: .49, played: 20, of: 20, games: 2000, updated: day},
            compare: null, older: null});
          const part = await show(commanderPage());
          assert.equal(part.querySelector('.gt-before').querySelector('p').textContent,
            'The list changed since its last test (2 Nov). Before: 41% (33–49).');
          assert(hasClass(part.querySelector('.range-bar'),'is-muted')); assert(hasClass(part.querySelector('.fresh'),'is-stale'));
          assert(!part.querySelector('.gt-headline-panel'));
          assert(!part.textContent.includes('Not tested against popular decks yet.'));
          const button = buttonText(part, 'Test the new list'); assert(button && !button.hidden);
          flushTimers(); await settle(); assert.equal(writes.length, 0);
          button.click(); await settle();
          assert.equal(tab('matchups').getAttribute('aria-selected'), 'true');
          assert(main.querySelector('#sec-gauntlet'));
          assert.equal(writes.length, 0);
        """)

    def test_the_compare_line_and_older_results_on_the_overview(self):
        self.run_js(DAY + self.GAUNTLET + """
          summary = done({before: {rate: .41, low: .33, high: .49, played: 20, of: 20, games: 2000, updated: now},
            compare: {same: 20, before: {rate: .41, low: .33, high: .49}, now: {rate: .47, low: .39, high: .55}, moved: 0},
            older: {reason: 'forge', opponents: 20, of: 20, updated: now, overall: null}});
          let part = await show(commanderPage());
          assert.equal(part.querySelector('.gt-before').textContent,
            'Before this change 41% (33–49) · Now 47% (39–55), same 20 opponents.');
          assert(part.querySelector('.gt-headline-panel'));
          assert.equal(part.querySelector('.gt-older').textContent, "Results from an older Forge aren't shown.");
          assert(buttonText(part, 'Popular decks'));
          summary = done({state: 'stale_older', overall: null, played: 0, games: 0, hardest: [], updated: null,
            before: null, compare: null,
            older: {reason: 'forge', opponents: 18, of: 20, updated: day,
              overall: {rate: .41, low: .33, high: .49}}});
          part = await show(commanderPage());
          assert(part.textContent.includes("Results from an older Forge aren't shown."));
          assert(part.textContent.includes('With the older Forge: 41% (33–49), 18 of 20 opponents (2 Nov).'));
          assert(buttonText(part, 'Test it again'));
          assert(!part.textContent.includes("aren't set up on this PC"));
          // An earlier list's older results: the list changed too, so the button tests the new list.
          summary = done({state: 'stale_older', overall: null, played: 0, games: 0, hardest: [], updated: null,
            before: null, compare: null,
            older: {reason: 'forge', opponents: 18, of: 20, updated: day, earlier: true,
              overall: {rate: .41, low: .33, high: .49}}});
          part = await show(commanderPage());
          assert(part.textContent.includes("The list changed since its last test. Results from an older Forge"));
          assert(buttonText(part, 'Test the new list'));
          assert.equal(writes.length, 0);
        """)
