"""Queue missing cards… (E5-S25, deck-queue-missing.js) under Node: the button under the Cards tab's Missing
filter only for a home admin, the review sheet, the state choice, one add_many save of the reviewed cards
with the review's revision, and a stale review asking for a new one.

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js; nothing is sent to a server.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + """
  const review = {ready: true, deck: {id: 'casual/test', title: 'Test Deck'}, revision: 'rev-1',
    states: ['ready', 'long_term'], totals: {cards: 1, copies: 2},
    rows: [{name: 'Bolt', missing: 3, queued: 1, copies: 2, joins: null, card: bolt},
           {name: 'Elf', missing: 1, queued: 1, copies: 0, joins: null, card: elf}]};
  const calls = [], toasts = [];
  toast = (message) => toasts.push(message);
  let saveAnswer = {saved: true, action: 'add_many', revision: 'rev-2', cards: 1, copies: 2};
  api = async (path, options = {}) => {
    if (path === '/api/decks') return {decks: []};
    if (path.startsWith('/api/deck/swaps')) return {cards: []};
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push([path, body]);
    if (path === '/api/shopping/queue/missing') return JSON.parse(JSON.stringify(review));
    if (path === '/api/shopping/queue') {
      if (saveAnswer instanceof ApiError) throw saveAnswer;
      return saveAnswer;
    }
    throw new Error('unexpected ' + path);
  };
  const settle = async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); };
  const admin = {admin: true, orders: true, see_home_records: true, see_inventory: ['home'], spaces: ['home'],
    deck_spaces: ['home'], home_player: null, create: []};
  const showMissing = (page) => { clear(main); location.hash = '#/deck?id=casual%2Ftest&tab=cards&filter=missing';
    drawDeck(page, deckViewOf(parseHash().params)); };
  const sheet = () => document.body.querySelectorAll('dialog').pop();
  const buying = () => buttonText(main, 'Find and buy cards');
  const openRecorded = () => {
    buying()?.click();
    if (sheet()) buttonText(sheet(), 'Use recorded collection')?.click();
  };
  const queueButton = () => sheet() && buttonText(sheet(), 'Review Planned list for the shared queue');
  const reviewQueue = () => {
    openRecorded();
    queueButton().click();
  };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckQueueMissingUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_offer_the_queue_review_only_for_a_home_admin(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          showMissing(makePage());
          assert(buying());
          openRecorded();
          assert(queueButton(), 'a home admin can review Planned shortages');
          sheet().querySelector('.sheet-close').click();
          buttonText(main, 'All').click();
          openRecorded();
          assert(queueButton(), 'the review is reachable independent of the card filter');
          sheet().querySelector('.sheet-close').click();
          const hidden = makePage(); hidden.summary.id = 'user2/casual/test'; hidden.summary.space = 'user2';
          const product = makePage(); product.summary.id = 'product/fdn-beginner-box/elves';
          for (const [page, may] of [[makePage(), {...admin, admin:false, orders:false}], [makePage(), null],
              [product, admin], [hidden, admin]]) {
            showMissing(page); state.may = may; openRecorded();
            assert(!queueButton());
            sheet()?.querySelector('.sheet-close').click();
          }
          same(calls, []);
        """)

    def test_review_then_one_save_with_the_chosen_state(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          showMissing(makePage());
          reviewQueue(); await settle();
          same(calls, [['/api/shopping/queue/missing', {profile: 'matt', deck: 'casual/test'}]]);
          const text = sheet().textContent;
          assert(text.includes('2 copies to queue · 3 missing · 1 already queued for this deck'), text);
          assert(text.includes('Already queued (1)'));
          buttonText(sheet(), 'Long-term').click();
          const save = buttonText(sheet(), 'Queue 2 copies (Long-term)');
          assert(save, 'Save names the copies and the state');
          save.click(); await settle();
          same(calls[1], ['/api/shopping/queue', {profile: 'matt', action: 'add_many', expect: 'rev-1', deck: 'casual/test',
            state: 'long_term', cards: [{name: 'Bolt', copies: 2, joins: null}]}]);
          same(calls.length, 2);
          same(toasts, ['Queued 2 copies of 1 card for Test Deck.']);
        """)

    def test_play_now_exports_its_shortfall_and_labels_the_planned_review_before_opening(self):
        self.run_js(r"""
          state.may = admin; state.profile.role = 'admin';
          const page = makePage(), copied = [];
          const opt = card('Opt', 'Instant', 1, ['U']);
          page.version = 'owned';
          page.sections.Deck = [{qty: 4, name: 'Opt', card: opt}, {qty: 6, name: 'Elf', card: elf}];
          page.owned.rows = [row('Opt', 4, 1, [['Incoming', 1]]), row('Elf', 6, 0)];
          page.owned.totals.missing = 1;
          navigator.clipboard = {writeText: async (text) => copied.push(text)};
          showMissing(page); openRecorded();
          const planned = queueButton(); assert(planned);
          assert(sheet().textContent.includes('Alternative list'));
          assert(sheet().textContent.includes('1 on the way'));
          buttonText(sheet(), 'Copy missing for this list').click(); await settle();
          same(copied, ['1 Opt\n']); same(calls, []);
          planned.click(); await settle();
          assert(sheet().textContent.includes('Bolt')); assert(!sheet().textContent.includes('Opt'));
          same(calls[0][1], {profile: 'matt', deck: 'casual/test'});
        """)

    def test_copy_missing_on_a_members_own_deck_and_no_export_for_hidden_inventory(self):
        self.run_js(r"""
          state.profile = {id: 'user2', space: 'user2', role: 'member'};
          state.may = {...admin, orders: false, see_inventory: ['user2']};
          const page = makePage();
          page.summary = {...page.summary, id: 'user2/casual/test', space: 'user2'};
          showMissing(page); openRecorded(); assert(!queueButton());
          navigator.clipboard = {writeText: async () => { throw Error('Unavailable'); }};
          buttonText(sheet(), 'Copy missing for this list').click(); await settle();
          assert.equal(sheet().querySelector('textarea').value, '3 Bolt\n');
          assert(sheet().textContent.includes('Planned list'));
          shopCloseQueueSheets(); colCloseSheets(); assert(!sheet());
          const hidden = makePage(); delete hidden.owned; showMissing(hidden);
          assert(!buying()); same(calls, []);
        """)

    def test_unconfirmed_availability_cannot_be_copied_even_when_rows_are_present(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          const page = makePage(); page.owned.availability_confirmed = false;
          showMissing(page); openRecorded();
          assert(sheet().textContent.includes('Availability needs checking'));
          assert(!sheet().textContent.includes('3 × Bolt'));
          assert(!buttonText(sheet(), 'Copy missing for this list'));
          assert(buttonText(sheet(), 'Check copies at home'));
          same(calls, []);
        """)

    def test_old_sheet_cannot_submit_as_another_profile_or_after_its_deck_redraws(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          for (const change of ['profile','route','deck']) {
            showMissing(makePage()); reviewQueue(); await settle();
            const button = buttonText(sheet(), 'Queue 2 copies (Ready to buy)');
            const before = calls.length;
            if (change === 'profile') state.profile = {...state.profile, id:'user2'};
            if (change === 'route') routeToken++;
            if (change === 'deck') showMissing(makePage());
            button.click(); await settle(); assert.equal(calls.length,before);
            shopCloseQueueSheets(); assert(!sheet());
            state.profile = {...state.profile, id:'matt'};
          }
        """)

    def test_selective_queue_totals_state_and_choices_survive_a_fresh_review(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          review.rows[1] = {...review.rows[1], queued: 0, copies: 1, joins: 'long_term'};
          showMissing(makePage()); reviewQueue(); await settle();
          const check = (name, checked) => {
            const input = sheet().querySelector('[aria-label="Queue ' + name + '"]');
            input.checked = checked; input.fire('change');
          };
          check('Elf', false);
          assert(!sheet().querySelector('.queue-missing-joins'));
          check('Bolt', false);
          assert(buttonText(sheet(), 'Queue 0 copies (Ready to buy)').disabled);
          check('Bolt', true);
          buttonText(sheet(), 'Long-term').click();
          saveAnswer = new ApiError(409, 'Review again.');
          buttonText(sheet(), 'Queue 2 copies (Long-term)').click(); await settle();
          same(calls[1][1].selected, ['Bolt']); assert.equal(calls[1][1].cards.length, 2);
          review.rows.push({name: 'Opt', copies: 1, missing: 1, queued: 0, joins: null});
          buttonText(sheet(), 'Review again').click(); await settle();
          assert(!sheet().querySelector('[aria-label="Queue Opt"]').checked);
          assert(!sheet().querySelector('[aria-label="Queue Elf"]').checked);
          assert(buttonText(sheet(), 'Queue 2 copies (Long-term)'));
        """)

    def test_copies_joining_a_row_in_another_state_are_named_and_sent_back(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          review.rows[0].joins = 'waiting_for_stock';
          showMissing(makePage());
          reviewQueue(); await settle();
          const text = sheet().textContent;
          assert(text.includes('added to the existing Waiting for stock row'), text);
          const warn = () => sheet().querySelector('.queue-missing-joins');
          assert(warn() && warn().textContent.includes('Bolt (Waiting for stock)'), text);
          assert(warn().textContent.includes('keeping that state'));
          buttonText(sheet(), 'Queue 2 copies (Ready to buy)').click(); await settle();
          same(calls[1][1].cards, [{name: 'Bolt', copies: 2, joins: 'waiting_for_stock'}]);
        """)

    def test_no_warning_when_the_joined_row_is_in_the_chosen_state(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          review.rows[0].joins = 'long_term';
          showMissing(makePage());
          reviewQueue(); await settle();
          assert(sheet().querySelector('.queue-missing-joins'), 'Ready to buy is chosen first');
          buttonText(sheet(), 'Long-term').click();
          assert.equal(sheet().querySelector('.queue-missing-joins'), null);
          assert(sheet().textContent.includes('added to the existing Long-term row'));
        """)

    def test_a_stale_review_asks_for_a_new_one(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          saveAnswer = new ApiError(409, 'The deck, the collection or the purchase queue changed since this review. Review the missing cards again.');
          showMissing(makePage());
          reviewQueue(); await settle();
          buttonText(sheet(), 'Queue 2 copies (Ready to buy)').click(); await settle();
          assert(sheet().textContent.includes('changed since this review'));
          buttonText(sheet(), 'Review again').click(); await settle();
          same(calls.map((c) => c[0]), ['/api/shopping/queue/missing', '/api/shopping/queue', '/api/shopping/queue/missing']);
        """)

    def test_nothing_left_to_queue_and_an_uncountable_deck(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          review.rows = [review.rows[1]]; review.totals = {cards: 0, copies: 0};
          showMissing(makePage());
          reviewQueue(); await settle();
          assert(sheet().textContent.includes('Every missing card is already on the purchase queue for this deck.'));
          assert.equal(sheet().querySelectorAll('button').find((b) => b.textContent.startsWith('Queue ')), undefined);
          sheet().querySelector('.sheet-close').click(); await settle();
          review.ready = false; review.reason = 'Missing cards cannot be counted until the home card pool is complete.';
          reviewQueue(); await settle();
          assert(sheet().textContent.includes('cannot be counted'));
        """)
