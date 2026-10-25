"""The Card list's estimated prices and their sort (E7-S27), over the real scripts with fixture answers."""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + """
  const row = (name, set, number, finish = 'nonfoil') => ({name, set, collector_number: number, finish, quantity: 1,
    condition: 'NM', language: 'en', notes: ''});
  const rows = [row('Sol Ring', 'sld', '2539'), row('Llanowar Elves', 'fdn', '227'),
    row('Llanowar Elves', 'fdn', '227', 'foil'), row('Black Lotus', 'lea', '232'), row('Arcane Signet', 'sld', '2538')];
  const prices = {rows: {'sld|2539|nonfoil': {usd: 14.21, aud: 20.2}, 'fdn|227|nonfoil': {usd: .25, aud: .36},
    'fdn|227|foil': {usd: 1.77, aud: 2.52}, 'sld|2538|nonfoil': {usd: 13.41, aud: 19.06}},
    rate: 1.4217, rate_date: '2026-10-21', price_date: '2026-10-19', price_error: null};
  const shown = () => main.querySelectorAll('tr').filter(tr => tr.getAttribute('data-key')).map(tr =>
    `${tr.querySelector('.col-cell-name').textContent} ${tr.querySelector('.col-td-price').querySelector('.cell-unknown') ? 'No price' : tr.querySelector('.col-td-price').textContent}`);
  const heading = () => main.querySelector('.col-th-price');
  const draw = (data = {}) => { clear(main); as('matt', MAY.admin);
    return drawCollectionRows({space: 'home', sha256: 's1', rows, prices, editable: true, ...data}, 'home'); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionPricesUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_price_sorts_most_valuable_first_then_reverses_with_unpriced_last(self):
        self.run_js("""
          draw();
          assert(heading().textContent.includes('~A$ each'));
          heading().querySelector('button').click();
          assert.equal(heading().getAttribute('aria-sort'), 'descending');
          same(shown(), ['Sol Ring 20.20', 'Arcane Signet 19.06', 'Llanowar Elves 2.52', 'Llanowar Elves 0.36', 'Black Lotus No price']);
          heading().querySelector('button').click();
          assert.equal(heading().getAttribute('aria-sort'), 'ascending');
          same(shown(), ['Llanowar Elves 0.36', 'Llanowar Elves 2.52', 'Arcane Signet 19.06', 'Sol Ring 20.20', 'Black Lotus No price']);
          for (const text of ['estimate', "own printing and finish", '1.4217 AUD', '2026-10-21'])
            assert(main.querySelector('.col-price-note').textContent.includes(text), text);
          assert.equal(main.querySelector('.col-price-note').querySelector('.fresh').getAttribute('title'), '2026-10-19');
        """)

    def test_a_save_s_prices_replace_the_old_ones(self):
        self.run_js("""
          const cv = draw();
          colChanged(cv, {sha256: 's2', rows, prices: {...prices, rows: {...prices.rows, 'lea|232|nonfoil': {usd: 1, aud: 1.42}}}}, '');
          assert(shown().includes('Black Lotus 1.42'));
        """)

    def test_a_conflict_s_rows_come_with_their_prices(self):
        # Someone else added a card meanwhile: the 409's rows and prices both replace the old ones.
        self.run_js("""
          const cv = draw(); const added = row('Sheoldred, the Apocalypse', 'dmu', '107');
          colTakeRows(cv, {rows: [...rows, added], prices: {...prices, rows: {...prices.rows, 'dmu|107|nonfoil': {usd: 50, aud: 71.09}}}});
          drawColRowList(cv);
          assert(shown().includes('Sheoldred, the Apocalypse 71.09'));
          colTakeRows(cv, {rows});          // an older server's 409: the rows, the prices kept
          drawColRowList(cv); assert(shown().includes('Sol Ring 20.20'));
        """)

    def test_in_storage_only_hides_rows_whose_copies_are_all_in_decks(self):
        # E7-S28: Sol Ring's one copy is in a deck, one of the two Elves (a guess), Black Lotus none.
        self.run_js("""
          const storage = {rows: {'sld|2539|nonfoil': {held: 1, guess: false}, 'fdn|227|nonfoil': {held: 1, guess: true}},
            error: null};
          const r = (name, n = 1) => ({...row(name, 'fdn', '227'), quantity: n});
          const cv = draw({rows: [...rows.slice(0, 1), r('Llanowar Elves', 2), ...rows.slice(2)], storage});
          const box = main.querySelector('#col-storage'), label = main.querySelector('.col-storage');
          assert(!label.hidden); assert(label.textContent.includes('In storage only (4 rows)'));
          const held = () => main.querySelectorAll('.col-held').map(e => e.textContent);
          same(held(), ['1 in a deck?', 'all in decks']);
          assert(main.querySelector('.col-held-guess').getAttribute('title').includes('cheapest'));
          // The title can't be reached on a phone: the note under the list says it too.
          assert(main.querySelector('.col-price-note').textContent.includes("don't say which of this card's printings"));
          box.checked = true; box.fire('change');
          assert(!shown().some(text => text.startsWith('Sol Ring')));
          assert.equal(shown().length, 4);
          assert(main.querySelector('.col-price-note').textContent.includes('basic lands are always listed'));
          // A save that puts the last copy in storage brings the row back.
          colChanged(cv, {sha256: 's2', rows: cv.rows, storage: {rows: {}, error: null}}, '');
          assert(shown().some(text => text.startsWith('Sol Ring')));
        """)

    def test_in_storage_only_is_offered_only_when_the_decks_could_be_read(self):
        self.run_js("""
          draw({storage: {rows: {}, error: "The copies in decks couldn't be worked out."}});
          assert(main.querySelector('.col-storage').hidden);
          assert(main.querySelector('.col-price-note').textContent.includes("In storage only isn't offered: The copies in decks"));
          draw({storage: undefined});        // an older server
          assert(main.querySelector('.col-storage').hidden);
          assert.equal(main.querySelectorAll('.col-held').length, 0);
        """)

    def test_without_prices_the_note_says_why(self):
        self.run_js("""
          draw({prices: {rows: {}, rate: null, rate_date: null, price_date: null, price_error: 'No USD->AUD rate'}});
          assert(main.querySelector('.col-price-note').textContent.includes('No prices: No USD->AUD rate'));
          assert(shown().every(text => text.endsWith('No price')));
          draw({prices: undefined});        // an older server: no prices at all
          assert(shown().every(text => text.endsWith('No price')));
        """)
