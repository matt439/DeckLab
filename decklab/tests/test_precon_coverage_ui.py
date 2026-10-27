"""The Collection page's "Precons we could build…" (E1-S24, precon-coverage.js), over the real scripts with fixture answers."""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

FIXTURE = SETUP + """
  const deck = (file, name, covered, cards, extra = {}) => ({file, name, code: 'tst', set_name: 'Test Set', type: 'Commander Deck',
    released: '2026-10-02', source: '', kind: 'commander', cards, covered, missing: cards - covered, share: covered / cards, ...extra});
  const RANKED = {space: 'home', date: '2026-10-08', total: 3, types: ['Commander Deck', 'Theme Deck'], may_start: true,
    status: {listed: 3, indexed: 3, updating: false, error: null},
    decks: [deck('Dinos_TST', 'Test Dinos', 4, 5), deck('Elves_TST', 'Elf Theme', 2, 10, {type: 'Theme Deck', kind: 'casual'})]};
  const DETAIL = {deck: deck('Dinos_TST', 'Test Dinos', 4, 5), kind: 'commander', title: 'Ghalta: Test Dinos', cards: 5, covered: 4,
    share: 0.8, missing: [{name: 'Sol Ring', need: 1, free: 0, missing: 1, aud_each: 3.22, aud_missing: 3.22, priced_printing: 'ECC 57',
      card: null}], totals: {missing: 1, aud_missing: 3.22, unpriced: []}, rate: 1.5, rate_date: '2026-10-27',
    price_date: '2026-10-26', price_error: null, problems: [], may_start: true};
  const make = (data = {}) => { as('matt', MAY.admin); location.hash = '#/collection';
    return drawCollectionRows({space: 'home', sha256: 's1', rows: [], editable: true, ...data}, 'home'); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PreconCoverageUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_ranking_filters_detail_and_start(self):
        self.run_js("""
          const cv = make();
          const asked = [];
          api = async (path) => { asked.push(path);
            if (path.startsWith('/api/precons/coverage/deck?')) return DETAIL;
            if (path.startsWith('/api/precons/coverage?')) return RANKED;
            throw new Error('unexpected ' + path); };
          const ctx = openCoverageSheet(cv); await flush();
          same(asked, ['/api/precons/coverage?']);
          const list = ctx.area.textContent;
          assert(list.includes('Test Dinos') && list.includes('80% · 4 of 5 cards') && list.includes('1 card to find'), list);
          assert(list.indexOf('Test Dinos') < list.indexOf('Elf Theme'));
          // The format filter asks again; a kind of deck too.
          button(ctx.formats, 'Commander').click(); await flush();
          assert.equal(asked.at(-1), '/api/precons/coverage?format=commander');
          ctx.typeSelect.value = 'Theme Deck'; ctx.typeSelect.fire('change'); await flush();
          assert.equal(asked.at(-1), '/api/precons/coverage?format=commander&type=Theme+Deck');
          // Opening one: its missing cards and the estimate, with the rate and dates.
          ctx.area.querySelector('.pcov-pick').click(); await flush();
          assert.equal(asked.at(-1), '/api/precons/coverage/deck?file=Dinos_TST');
          const words = ctx.area.textContent;
          assert(words.includes('1 card to find') && words.includes('about A$3.22 to buy'), words);
          assert(words.includes('1 USD = 1.5 AUD (ECB rate of 2026-10-27), prices pulled 2026-10-26'), words);
          assert(words.includes('Sol Ring'), words);
          const calls = [];
          apiWrite = async (path, body) => { calls.push([path, body]);
            return {created: true, id: 'commander/ghalta-test-dinos', title: 'Ghalta: Test Dinos', warnings: [], stale_tables: []}; };
          ctx.sheet.foot.querySelector('[data-action="start"]').click(); await flush();
          same(calls, [['/api/precons/start', {space: 'home', file: 'Dinos_TST', title: 'Ghalta: Test Dinos'}]]);
          assert(ctx.sheet.closed);
          assert.equal(location.hash, '#/deck?id=commander%2Fghalta-test-dinos&v=target');
          assert.equal(state.saved.answer.id, 'commander/ghalta-test-dinos');
        """)

    def test_reading_lists_polls_and_refusals_show(self):
        self.run_js("""
          const cv = make();
          let answer = {...RANKED, decks: [], status: {listed: 3, indexed: 1, updating: true, error: null}};
          api = async () => answer;
          const ctx = openCoverageSheet(cv); await flush();
          assert(ctx.area.textContent.includes("Reading MTGJSON's precon lists: 1 of 3 read so far"), ctx.area.textContent);
          assert(ctx.timer);
          ctx.sheet.close();
          // A viewer who may not start decks sees no Start button; a refusal is shown, nothing navigates.
          const ctx2 = openCoverageSheet(make());
          api = async (path) => path.includes('/deck?') ? {...DETAIL, may_start: false} : RANKED; await rankPrecons(ctx2);
          await openCoveragePrecon(ctx2, RANKED.decks[0]);
          assert.equal(ctx2.sheet.foot.querySelector('[data-action="start"]'), null);
          assert(ctx2.area.textContent.includes("You can't start decks here."));
          api = async (path) => path.includes('/deck?') ? DETAIL : RANKED;
          await openCoveragePrecon(ctx2, RANKED.decks[0]);
          apiWrite = async () => { throw new ApiError(409, "There's already a deck called ghalta-test-dinos.", {conflict: {id: 'commander/ghalta-test-dinos'}}); };
          const before = location.hash;
          await startCoverageDeck(ctx2);
          assert(ctx2.message.textContent.includes("There's already a deck"), ctx2.message.textContent);
          assert.equal(location.hash, before);
          assert(!ctx2.sheet.closed);
        """)
