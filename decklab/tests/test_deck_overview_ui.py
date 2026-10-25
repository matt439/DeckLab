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
          assert(panel('overview').textContent.includes('No tests yet'));
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
          assert(tests.textContent.includes('No tests yet'));
          page.summary.read_only = true; assert.equal(variantTestsSection(page), null);
        """)
