"""The deck page's stand-ins for missing cards (E2-S07, deck-swaps.js) under Node: the Missing filter's
"Owned stand-ins" box (only with the collection, asked for once), its sheet and the way into the editor
for whoever may change the deck, and the Play-now list's swaps with their notes.

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js; nothing is sent to a server.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + """
  const shock = card('Shock', 'Instant', 1, ['R']);
  const swapsAnswer = {deck_id: 'casual/test', version: 'target', kind: 'casual', colours: ['G', 'R'], warnings: [],
    rate: 1.43, rate_date: '2026-10-12', price_date: '2026-10-12', cards: [
      {name: 'Bolt', section: 'Deck', missing: 3, aud_each: 1.25, card: bolt, type: 'instant', colours: ['R'], mv: 1,
       in_list: 3, list_missing: 3, more: 0, candidates: [{name: 'Shock', card: shock, default: null, free: 2, here: 0, max_qty: 2,
         basic: false, aud: 0.2, note: {severity: 0, words: 'Close to even', text: 'Close to even: the same job.'}}]},
      {name: 'Ghost', section: 'Deck', missing: 1, aud_each: 9, card: null, type: 'creature', colours: ['G'], mv: 2,
       in_list: 0, list_missing: 1, more: 0, candidates: []}]};
  const calls = [];
  api = async (path) => { calls.push(path); return swapsAnswer; };
  const settle = async () => { for (let i = 0; i < 6; i += 1) await Promise.resolve(); };
  const finder = () => main.querySelector('.deck-swap-finder');
  const showMissing = (page) => { clear(main); location.hash = '#/deck?id=casual%2Ftest&tab=cards&filter=missing';
    drawDeck(page, deckViewOf(parseHash().params)); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckSwapsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_the_missing_filters_box(self):
        self.run_js("""
          showMissing(makePage());
          assert(finder(), 'the Missing filter has the box');
          await settle();
          same(calls, ['/api/deck/swaps?id=casual%2Ftest&version=target']);
          const text = finder().textContent;
          assert(text.includes('3 missing · 1 could stand in'));
          assert(text.includes('1 missing · no close stand-in: worth buying first'));
          // Asked for once: back to All and Missing again uses the same answer.
          buttonText(main, 'All').click(); assert.equal(finder(), null);
          main.querySelectorAll('button').find((b) => b.textContent.startsWith('Missing')).click();
          await settle();
          same(calls.length, 1);
          // See them: the stand-ins, with the way into the editor's Play-now list.
          buttonText(finder(), 'See them').click();
          const sheet = document.body.querySelectorAll('dialog').pop();
          assert(sheet.textContent.includes('Close to even: the same job.'));
          assert(sheet.textContent.includes('On the way'));
          const link = sheet.querySelectorAll('a').find((a) => a.textContent === 'Swap into the play-now list');
          assert.equal(link.getAttribute('href'), '#/edit?id=casual%2Ftest&v=owned&swap=Bolt');
        """)

    def test_no_swap_when_the_play_now_list_covers_it(self):
        self.run_js("""
          // The Planned list is short of Bolt, but the Play-now list plays the copies owned and something else.
          swapsAnswer.cards[0].in_list = 2; swapsAnswer.cards[0].list_missing = 0;
          showMissing(makePage()); await settle();
          buttonText(finder(), 'See them').click();
          const sheet = document.body.querySelectorAll('dialog').pop();
          assert.equal(sheet.querySelectorAll('a').length, 0);
          assert(sheet.textContent.includes("isn't short of it"));
        """)

    def test_a_long_list_folds(self):
        self.run_js("""
          const more = Array.from({length: 7}, (_, i) => ({...swapsAnswer.cards[1], name: `Card ${i}`}));
          swapsAnswer.cards = more;
          showMissing(makePage()); await settle();
          same(finder().querySelectorAll('li').length, 5);
          buttonText(finder(), 'Show all 7').click();
          same(finder().querySelectorAll('li').length, 7);
          assert(!finder().textContent.includes('Show all'));
        """)

    def test_read_only_and_no_collection(self):
        self.run_js("""
          const page = makePage(); page.summary.read_only = true;
          showMissing(page); await settle();
          buttonText(finder(), 'See them').click();
          const sheet = document.body.querySelectorAll('dialog').pop();
          assert.equal(sheet.querySelectorAll('a').length, 0);         // read-only: the list, no swap
          // A visitor who may not see the collection gets no owned rows, so neither the filter nor the box.
          calls.length = 0;
          const hidden = makePage(); delete hidden.owned;
          showMissing(hidden); await settle();
          assert.equal(finder(), null); same(calls, []);
          // A product has no Play-now list.
          const product = makePage(); product.summary.id = 'product/fdc-test';
          showMissing(product); await settle();
          assert.equal(finder(), null);
        """)

    def test_the_play_now_lists_swaps(self):
        self.run_js("""
          const page = makePage(); page.version = 'owned';
          page.swaps = {swaps: [
            {for: 'Bolt', out_qty: 3, using: [{name: 'Shock', qty: 2, card: shock}], note: 'Close to even.', note_line: '', card: bolt},
            {for: 'Ghost', out_qty: 1, using: [], note: null, note_line: null, card: null}],
            unpaired: [{name: 'Elf', qty: 1, card: elf}]};
          page.owned.rows.push(row('Shock', 2, 0, [['order x', 2]])); page.owned.rows.at(-1).on_the_way = 2;
          clear(main); drawDeck(page);
          const section = main.querySelector('.deck-swaps');
          assert(section, 'the Overview has the swaps');
          const text = section.textContent;
          assert(text.includes('Swaps from the planned list'));
          assert(text.includes('2 Shock for 3 Bolt'));
          assert(text.includes('Close to even.'));
          assert(text.includes('1 Ghost out'));
          assert(text.includes('No note yet in Substitutes'));
          assert(text.includes('Also in the play-now list: 1 Elf.'));
          assert(text.includes('On the way'));
          assert.equal(section.querySelector('a').getAttribute('href'), '#/edit?id=casual%2Ftest&v=owned&tab=notes');
          // The Planned list doesn't show them; a read-only visitor gets no Edit notes.
          assert.equal(deckSwapsSection({...page, version: 'target'}), null);
          page.summary.read_only = true;
          assert.equal(deckSwapsSection(page).querySelectorAll('a').length, 0);
          assert.equal(deckSwapsSection({...page, swaps: null}), null);
        """)
