"""Collection's P1 metadata and filter scope over isolated DOM/API fixtures."""
import ast
import json
import os
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + """
  const row = (name, number, extra = {}) => ({name, set: 'fdn', collector_number: String(number),
    finish: 'nonfoil', quantity: 1, condition: '', language: '', notes: '', ...extra});
  const rows = [row('Alpha', 1, {quantity: 4}), row('Beta', 2, {condition: 'LP', language: 'ja', finish: 'foil'}),
    row('Gamma', 3, {condition: 'NM', language: 'en', finish: 'etched'})];
  const prices = {rows: {'fdn|1|nonfoil': {usd: 14.21, aud: 20.2}},
    rate: 1.4217, rate_date: '2026-10-21', price_date: '2026-10-24', price_error: null};
  const storage = {rows: {'fdn|1|nonfoil': {held: 4, guess: false}}, error: null};
  const draw = (data = {}) => { as('matt', MAY.admin); clear(main);
    return drawCollectionRows({space: 'home', sha256: 's1', rows, pictures: {}, prices, storage,
      editable: true, ...data}, 'home'); };
  const listed = () => main.querySelectorAll('tr').filter(tr => tr.getAttribute('data-key'));
  const setBox = (id, checked) => { const input = main.querySelector(id); input.checked = checked; input.fire('change'); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionMetadataUiTests(unittest.TestCase):
    def run_js(self, scenario, timezone=None):
        done = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + scenario, True]),
                              capture_output=True, text=True, encoding="utf-8", timeout=30,
                              env={**os.environ, "TZ": timezone} if timezone else None)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "ok")

    def test_unknown_details_have_spoken_words_beside_a_decorative_dash(self):
        self.run_js("""
          draw(); const first = listed()[0];
          for (const [selector, words] of [['.col-td-condition', 'Condition not recorded'],
                                           ['.col-td-language', 'Language not recorded']]) {
            const cell = first.querySelector(selector), dash = cell.querySelector('.cell-unknown');
            assert(dash); assert.equal(dash.textContent, '\u2014');
            assert.equal(dash.getAttribute('aria-hidden'), 'true');
            assert.equal(dash.getAttribute('aria-label'), null);
            assert(cell.querySelector('.sr-only').textContent.includes(words));
            assert(!cell.querySelectorAll('span').some(node => node.getAttribute('aria-label')));
          }
          const meta = first.querySelector('.col-cell-meta').textContent;
          assert(meta.includes('Condition not recorded')); assert(meta.includes('Language not recorded'));
        """)

    def test_recorded_details_keep_codes_and_words_without_assuming_unknowns(self):
        self.run_js("""
          draw(); const beta = listed()[1], gamma = listed()[2];
          const condition = beta.querySelector('.col-td-condition');
          assert.equal(condition.querySelector('.col-detail-code').textContent, 'LP');
          assert.equal(condition.querySelector('.col-detail-word').textContent, 'Lightly Played');
          const language = beta.querySelector('.col-td-language');
          assert.equal(language.querySelector('.col-detail-code').textContent, 'ja');
          assert.equal(language.querySelector('.col-detail-word').textContent, 'Japanese');
          const meta = beta.querySelector('.col-cell-meta').textContent;
          assert(meta.includes('Lightly Played')); assert(meta.includes('Japanese'));
          const usual = gamma.querySelector('.col-cell-meta').textContent;
          assert(!usual.includes('Near Mint')); assert(!usual.includes('English'));
          const unknown = colDetail('', 'condition');
          assert(!unknown.textContent.includes('NM')); assert(!unknown.textContent.includes('Near Mint'));
        """)

    def test_finish_labels_use_the_shared_neutral_chip_only_for_special_finishes(self):
        self.run_js("""
          draw(); const cells = listed().map(tr => tr.querySelector('.col-td-finish'));
          assert(cells[0].textContent.includes('Non-foil'));
          assert.equal(cells[0].querySelector('.chip-foil'), null);
          for (const [index, words] of [[1, 'Foil'], [2, 'Etched']]) {
            const finish = cells[index].querySelector('.chip-foil'); assert(finish);
            assert(finish.textContent.includes(words));
            assert(!finish.getAttribute('class').split(' ').includes('chip-good'));
            assert(!finish.getAttribute('class').split(' ').includes('chip-warn'));
            const meta = listed()[index].querySelector('.col-cell-meta').textContent;
            assert.equal(meta.split(words).length - 1, 1);
          }
        """)

    def test_missing_details_notice_filters_and_clears_after_details_are_recorded(self):
        self.run_js("""
          const cv = draw(), notice = main.querySelector('.col-unrecorded');
          assert(notice.getAttribute('class').split(' ').includes('box-info'));
          assert(notice.textContent.includes('Condition or language not recorded: 1 row'));
          const choice = notice.querySelector('.filter-chip');
          assert(choice.textContent.includes('Show only these'));
          assert(choice.querySelector('#col-unrecorded'));
          setBox('#col-unrecorded', true);
          same(listed().map(tr => tr.getAttribute('data-key')), ['fdn|1|nonfoil']);
          colChanged(cv, {sha256: 's2', rows: rows.map(r => ({...r, condition: r.condition || 'NM',
            language: r.language || 'en'}))}, '');
          assert.equal(notice.hidden, true); assert.equal(cv.unrecordedOnly, false);
          assert.equal(main.querySelector('#col-unrecorded').checked, false); assert.equal(listed().length, 3);
        """)

    def test_storage_chip_retains_native_filter_semantics_and_unavailable_fallback(self):
        self.run_js("""
          const cv = draw(), choice = main.querySelector('.col-storage');
          assert(choice.getAttribute('class').split(' ').includes('filter-chip')); assert(choice.querySelector('#col-storage'));
          assert(choice.textContent.includes('In storage only (2 rows)'));
          setBox('#col-storage', true);
          same(listed().map(tr => tr.getAttribute('data-key')), ['fdn|2|foil', 'fdn|3|etched']);
          assert.equal(cv.storageOnly, true);
          colChanged(cv, {sha256: 's2', rows, storage: {rows: {}, error: 'Counts unavailable.'}}, '');
          assert.equal(choice.hidden, true); assert.equal(cv.storageOnly, false);
          assert.equal(main.querySelector('#col-storage').checked, false); assert.equal(listed().length, 3);
          assert(main.querySelector('.col-price-note').textContent.includes('Counts unavailable.'));
        """)

    def test_visible_bulk_scope_includes_every_filtered_row_across_pages(self):
        self.run_js("""
          const many = Array.from({length: 105}, (_, i) => row('Card ' + String(i).padStart(3, '0'), i));
          const cv = draw({rows: many, prices: undefined, storage: undefined});
          assert.equal(listed().length, 100);
          const opener = main.querySelector('.col-bulk-open');
          assert(opener.textContent.includes('105 rows shown'));
          assert(opener.getAttribute('aria-label').includes('105 rows shown'));
          opener.click(); const sheet = openDialog();
          assert(sheet.textContent.includes('For the 105 rows shown'));
          const language = sheet.querySelector('select'); language.value = 'en'; language.fire('change');
          const writes = []; apiWrite = async (path, body) => { writes.push([path, body]);
            return {ok: true, sha256: 's2', rows: many.map(r => ({...r, language: 'en'})), changed: 105}; };
          button(sheet, 'Save 105 rows').click(); await flush();
          assert.equal(writes.length, 1); assert.equal(writes[0][0], '/api/collection/bulk');
          assert.equal(writes[0][1].keys.length, 105);
          const search = main.querySelector('#col-row-search'); search.value = 'Card 10'; search.fire('input');
          assert(main.querySelector('.col-bulk-open').textContent.includes('5 rows shown'));
          assert.equal(colShownRows(cv).length, 5);
        """)

    def test_price_metadata_keeps_per_copy_estimates_one_rate_and_honest_dates(self):
        self.run_js("""
          draw(); const note = main.querySelector('.col-price-note');
          assert.equal(listed()[0].querySelector('.col-td-price').textContent, '20.20');
          assert(!main.textContent.includes('80.80'));
          assert(note.textContent.includes('~A$ each')); assert(note.textContent.includes('estimate'));
          assert.equal(note.textContent.split('1 USD = 1.4217 AUD').length - 1, 1);
          assert(note.textContent.includes('ECB rate of 2026-10-21'));
          const fresh = note.querySelector('.fresh'); assert(fresh);
          assert.equal(fresh.getAttribute('title'), '2026-10-24');
          assert.equal(fresh.getAttribute('role'), 'img');
          assert(fresh.getAttribute('aria-label').includes('24 October 2026'));
          for (const invalid of [null, 'bad date', '2026-02-30', '2026-13-01']) assert.equal(colPriceStamp(invalid), null);
          draw({prices: {...prices, price_date: null}});
          assert.equal(main.querySelector('.col-price-note').querySelector('.fresh'), null);
          assert(main.querySelector('.col-price-note').textContent.includes('Price date not recorded.'));
          draw({prices: {rows: {}, rate: null, rate_date: null, price_date: null, price_error: 'No cached rate'}});
          assert(main.querySelector('.col-price-note').textContent.includes('No prices: No cached rate'));
          assert.equal(main.querySelector('.col-price-note').querySelector('.fresh'), null);
        """, timezone="America/Los_Angeles")

    def test_language_choices_cover_the_backend_codes_and_preserve_blank_unknown(self):
        source = WEB.parent / "lib" / "api" / "collection_edit.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        languages = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                         and any(isinstance(target, ast.Name) and target.id == "LANGUAGES" for target in node.targets))
        self.run_js("""
          const supported = """ + json.dumps(sorted(languages)) + """;
          same(COL_LANGUAGES.filter(([code]) => code).map(([code]) => code).sort(), supported);
          assert.equal(COL_LANGUAGES.filter(([code]) => code === '').length, 1);
          const verify = select => {
            const options = select.querySelectorAll('option');
            same(options.filter(option => option.getAttribute('value')).map(option => option.getAttribute('value')).sort(), supported);
            for (const option of options.filter(option => option.getAttribute('value'))) {
              assert(option.textContent.includes('(' + option.getAttribute('value') + ')'));
            }
            assert.equal(select.value, '');
          };
          const cv = draw(); main.querySelector('.col-bulk-open').click();
          verify(openDialog().querySelector('select'));
          colCloseSheets();
          verify(openCollectionSheet(cv).inputs.language);
        """)
