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
  const queueButton = () => main.querySelectorAll('button').find((b) => b.textContent === 'Queue missing cards…');
  const sheet = () => document.body.querySelectorAll('dialog').pop();
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckQueueMissingUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_offered_only_to_a_home_admin_under_missing(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          showMissing(makePage());
          assert(queueButton(), 'a home admin sees it under Missing');
          buttonText(main, 'All').click();
          assert.equal(queueButton(), undefined);
          // User1 (a home member who may not edit orders), an unknown answer, a product deck: never.
          state.may = {...admin, admin: false, orders: false}; state.profile.role = 'member';
          showMissing(makePage()); assert.equal(queueButton(), undefined);
          state.may = null; state.profile.role = 'admin';
          showMissing(makePage()); assert.equal(queueButton(), undefined);
          state.may = admin;
          const product = makePage(); product.summary.id = 'product/fdn-beginner-box/elves';
          showMissing(product); assert.equal(queueButton(), undefined);
          const theirs = makePage(); theirs.summary.id = 'user2/casual/test'; theirs.summary.space = 'user2';
          showMissing(theirs); assert.equal(queueButton(), undefined);
          same(calls, []);
        """)

    def test_review_then_one_save_with_the_chosen_state(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          showMissing(makePage());
          queueButton().click(); await settle();
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

    def test_copies_joining_a_row_in_another_state_are_named_and_sent_back(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          review.rows[0].joins = 'waiting_for_stock';
          showMissing(makePage());
          queueButton().click(); await settle();
          const text = sheet().textContent;
          assert(text.includes('added to the existing Waiting for stock row'), text);
          const warn = () => sheet().querySelector('.queue-missing-joins');
          assert(warn() && warn().textContent.includes('Bolt (Waiting for stock)'), text);
          assert(warn().textContent.includes('not To buy'));
          buttonText(sheet(), 'Queue 2 copies (To buy)').click(); await settle();
          same(calls[1][1].cards, [{name: 'Bolt', copies: 2, joins: 'waiting_for_stock'}]);
        """)

    def test_no_warning_when_the_joined_row_is_in_the_chosen_state(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          review.rows[0].joins = 'long_term';
          showMissing(makePage());
          queueButton().click(); await settle();
          assert(sheet().querySelector('.queue-missing-joins'), 'To buy is chosen first');
          buttonText(sheet(), 'Long-term').click();
          assert.equal(sheet().querySelector('.queue-missing-joins'), null);
          assert(sheet().textContent.includes('added to the existing Long-term row'));
        """)

    def test_a_stale_review_asks_for_a_new_one(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          saveAnswer = new ApiError(409, 'The deck, the collection or the purchase queue changed since this review. Review the missing cards again.');
          showMissing(makePage());
          queueButton().click(); await settle();
          buttonText(sheet(), 'Queue 2 copies (To buy)').click(); await settle();
          assert(sheet().textContent.includes('changed since this review'));
          buttonText(sheet(), 'Review again').click(); await settle();
          same(calls.map((c) => c[0]), ['/api/shopping/queue/missing', '/api/shopping/queue', '/api/shopping/queue/missing']);
        """)

    def test_nothing_left_to_queue_and_an_uncountable_deck(self):
        self.run_js("""
          state.may = admin; state.profile.role = 'admin';
          review.rows = [review.rows[1]]; review.totals = {cards: 0, copies: 0};
          showMissing(makePage());
          queueButton().click(); await settle();
          assert(sheet().textContent.includes('Every missing card is already on the purchase queue for this deck.'));
          assert.equal(sheet().querySelectorAll('button').find((b) => b.textContent.startsWith('Queue ')), undefined);
          sheet().querySelector('.sheet-close').click(); await settle();
          review.ready = false; review.reason = 'Missing cards cannot be counted until the home card pool is complete.';
          queueButton().click(); await settle();
          assert(sheet().textContent.includes('cannot be counted'));
        """)
