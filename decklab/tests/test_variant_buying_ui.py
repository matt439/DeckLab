"""Saved-variant buying facts and response ownership, using real scripts and disposable Node DOM."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = """
  state.profile = {id: 'matt', name: 'Matt', role: 'admin', space: 'home'};
  state.may = deriveMay(state.profile, false); routeToken = 9;
  let writes = 0;
  apiWrite = () => { writes += 1; throw new Error('Buying facts must be read-only'); };
  const buying = (extra = {}) => ({ready: true, availability_ready: true, queue_ready: true,
    availability_problem: null, queue_problem: null, basic_added: [], omitted: {},
    basis: 'Saved tested list; current home supply.', rows: [{name: 'New Card', added: 3,
      ready_added: 1, incoming_added: 1, missing_added: 1, references: [], estimate: null, queued: []}], ...extra});
  const answer = (facts = buying()) => ({status: 'done', test: {test: 'a'.repeat(64),
    base: {id: 'casual/example', title: 'Example', version: 'target'}, variant: {changes: {add: [[3, 'New Card']], remove: []}}},
    opponents: [], field: null, verdict: 'better', words: 'Better', buying: facts});
  const makePage = (data = answer()) => {
    const page = {token: routeToken, test: 'a'.repeat(64), profile: state.profile.id, timer: 0, refreshSeq: 0,
      host: el('div', {class: 'vt-page'}), problem: el('p'), data};
    main.append(page.problem, page.host); return page;
  };
  const mount = data => {
    const page = makePage(data), section = vtBuyingSection(page, data);
    if (section) page.host.append(section); return {page, section};
  };
  vtVerdictPanel = () => el('section', {class: 'vt-panel', text: 'Saved verdict'});
  vtRows = () => el('div');
  const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve = a; reject = b;});
    return {promise, resolve, reject}; };
  const newerAnswer = name => { const data = answer(); data.buying.rows[0].name = name; return data; };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class VariantBuyingUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_stock_incoming_and_queue_are_distinct_with_zero_aud_reference(self):
        self.run_js("""
          const data = answer();
          data.buying.rows[0].references = [{aud: 0, shop: 'Example shop', checked: '2026-10-28',
            printing: 'exact', set: 'tst', collector_number: '2', finish: 'nonfoil'}];
          data.buying.rows[0].queued = [{quantity: 5, state: 'long_term', purpose: 'another deck',
            printing: 'exact', set: 'tst', collector_number: '9', finish: 'foil'}];
          const {section} = mount(data), text = section.textContent;
          assert(text.includes('1 ready from the collection; 1 on the way; 1 still to find'));
          assert(text.includes('A$0.00 each at Example shop')); assert(text.includes('checked 2026-10-28'));
          assert(text.includes('TST 2, nonfoil')); assert(text.includes('5 copies: Long term for another deck; TST 9, foil'));
          assert(text.includes('shown separately')); assert(!text.includes('Nothing to buy'));
          assert.equal(section.querySelectorAll('button').length, 0); assert.equal(writes, 0);
        """)

    def test_partial_facts_keep_prices_and_show_each_problem_once(self):
        self.run_js("""
          const data = answer(buying({ready: false, availability_ready: false, queue_ready: false,
            availability_problem: 'Saved recipe changed.', queue_problem: 'Queue unavailable.',
            reason: 'Saved recipe changed. Queue unavailable.'}));
          Object.assign(data.buying.rows[0], {ready_added: null, incoming_added: null, missing_added: null,
            estimate: {aud: 1.2, rate: 1.5, price_date: '2026-10-27', rate_date: '2026-10-26',
              set: 'tst', collector_number: '3', finish: 'foil'}});
          const {section} = mount(data), text = section.textContent;
          assert(text.includes('Availability unknown')); assert(text.includes('Cached Scryfall estimate: A$1.20'));
          assert(text.includes('1 USD = 1.5 AUD (2026-10-26)')); assert(text.includes('Prices 2026-10-27'));
          assert.equal(text.split('Saved recipe changed.').length - 1, 1);
          assert.equal(text.split('Queue unavailable.').length - 1, 1);
          assert(text.includes('Existing queue requests could not be checked'));
          assert(!text.includes('No existing queue request')); assert(!text.includes('Nothing to buy'));
        """)

    def test_omissions_and_basic_names_do_not_claim_all_additions_are_in_shopping(self):
        self.run_js("""
          const data = answer(buying({basic_added: [{name: 'Forest', added: 2}],
            omitted: {rows: 4, basic_added: 2, queued: 3, references: 5}}));
          const {section} = mount(data), text = section.textContent;
          assert(text.includes('2 Forest')); assert(text.includes('Plain basic lands are assumed available'));
          for (const words of ['4 additional added card names', '2 additional basic land names',
            '3 additional queue requests', '5 additional recorded price references']) assert(text.includes(words));
          assert(!text.includes('are in Shopping')); assert(text.includes('No dated price available'));
        """)

    def test_home_record_gate_rejects_member_and_anonymous_even_with_public_inventory(self):
        self.run_js("""
          for (const profile of [{id: 'user2', role: 'member', space: 'user2'}, null]) {
            state.profile = profile; state.may = {see_inventory: null, see_home_records: false};
            assert.equal(vtBuyingSection({token: routeToken}, answer()), null);
          }
          state.profile = {id: 'user1', role: 'member', space: 'home'};
          state.may = deriveMay(state.profile, false); assert(vtBuyingSection({}, answer()));
        """)

    def test_legacy_live_and_malformed_numeric_facts_never_make_buying_claims(self):
        self.run_js("""
          assert.equal(vtBuyingSection({}, {status: 'done'}), null);
          assert.equal(vtBuyingSection({}, {...answer(), status: 'running'}), null);
          const data = answer(); Object.assign(data.buying.rows[0], {ready_added: 99, references: null,
            estimate: {aud: NaN, rate: 1.5, price_date: 'bad', rate_date: 'bad'}});
          const {section} = mount(data), text = section.textContent;
          assert(text.includes('Availability unknown')); assert(text.includes('No dated price available'));
          for (const word of ['NaN', 'Infinity', 'undefined', 'Nothing to buy']) assert(!text.includes(word));
        """)

    def test_older_success_cannot_replace_newer_same_page_evidence(self):
        self.run_js("""
          const page = makePage(), a = deferred(), b = deferred(); let reads = 0;
          api = () => (++reads === 1 ? a.promise : b.promise);
          const old = vtRefresh(page), fresh = vtRefresh(page), latest = newerAnswer('Newer card');
          b.resolve(latest); await fresh; a.resolve(newerAnswer('Older card')); await old;
          assert.equal(page.data, latest); assert(page.host.textContent.includes('Newer card'));
          assert(!page.host.textContent.includes('Older card')); assert.equal(writes, 0);
        """)

    def test_older_failure_cannot_replace_success_or_schedule_an_old_retry(self):
        self.run_js("""
          const page = makePage(), a = deferred(), b = deferred(); let reads = 0;
          api = () => (++reads === 1 ? a.promise : b.promise);
          const old = vtRefresh(page), fresh = vtRefresh(page), latest = newerAnswer('Newest');
          b.resolve(latest); await fresh; a.reject(new ApiError(503, 'old failure')); await old;
          assert.equal(page.data, latest); assert.equal(page.problem.textContent, ''); assert.equal(page.timer, 0);
        """)

    def test_explicit_new_draw_invalidates_a_pending_get(self):
        self.run_js("""
          const page = makePage(), a = deferred(); api = () => a.promise;
          const old = vtRefresh(page), latest = newerAnswer('Action result');
          vtDraw(page, latest); a.resolve(newerAnswer('Old poll')); await old;
          assert.equal(page.data, latest); assert(!page.host.textContent.includes('Old poll'));
        """)

    def test_profile_or_route_changes_discard_late_success_and_failure(self):
        self.run_js("""
          for (const fail of [false, true]) {
            state.profile = {id: 'matt', role: 'admin', space: 'home'}; state.may = deriveMay(state.profile, false);
            const page = makePage(), previous = page.data, pending = deferred(); api = () => pending.promise;
            const read = vtRefresh(page);
            state.profile = {id: 'user2', role: 'member', space: 'user2'}; state.may = deriveMay(state.profile, true);
            if (fail) pending.reject(new ApiError(503, 'old private error')); else pending.resolve(newerAnswer('Private late row'));
            await read; assert.equal(page.data, previous); assert.equal(page.problem.textContent, '');
            assert(!page.host.textContent.includes('Private late row'));
          }
          state.profile = {id: 'matt', role: 'admin', space: 'home'};
          const page = makePage(), pending = deferred(), previous = page.data; api = () => pending.promise;
          const read = vtRefresh(page); routeToken += 1; pending.resolve(newerAnswer('Wrong route')); await read;
          assert.equal(page.data, previous);
        """)

    def test_refresh_clears_scheduled_timer_and_detached_retry_does_nothing(self):
        self.run_js("""
          const data = answer(buying({ready: false, availability_ready: false, availability_problem: 'Try later.'}));
          const {page, section} = mount(data), retry = section.querySelector('button');
          const cleared = []; clearTimeout = value => cleared.push(value); page.timer = 42;
          let reads = 0; api = async () => {reads += 1; return answer();};
          await vtRefresh(page); assert(cleared.includes(42)); assert.equal(reads, 1);
          retry.fire('click'); await Promise.resolve(); assert.equal(reads, 1); assert.equal(writes, 0);
        """)

    def test_initial_load_answer_belongs_to_the_starting_profile(self):
        self.run_js("""
          let respond; load = (path, token, ready) => {respond = ready;};
          showVariant(new URLSearchParams({test: 'a'.repeat(64)}), routeToken);
          state.profile = {id: 'user2', role: 'member', space: 'user2'}; state.may = deriveMay(state.profile, true);
          respond(newerAnswer('Late private buying')); assert(!main.textContent.includes('Late private buying'));
        """)
