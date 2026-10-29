"""Collection's lab preview and casual list over isolated DOM/API fixtures."""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + """
  const row = (name, number, extra = {}) => ({name, set: 'fdn', collector_number: String(number),
    finish: 'nonfoil', quantity: 1, condition: 'NM', language: 'en', notes: '', ...extra});
  const rows = [row('Alpha', 1, {quantity: 4}), row('Alpha', 1, {finish: 'foil', quantity: 2,
    condition: 'LP', language: 'ja'}), row('Beta', 2, {condition: '', language: ''}), row('Forest', 3, {quantity: 3})];
  const picture = (name, number, extra = {}) => ({name, type_line: name === 'Forest' ? 'Basic Land - Forest' : 'Creature - Elf',
    cmc: name === 'Forest' ? 0 : 1, mana_cost: name === 'Forest' ? '' : '{G}', color_identity: ['G'],
    colors: name === 'Forest' ? [] : ['G'], oracle_text: '', img: '/img/fdn/' + number + '/normal',
    img_small: '/img/fdn/' + number + '/small', exact: true, ...extra});
  const pictures = {'fdn|1|nonfoil': picture('Alpha', 1), 'fdn|1|foil': picture('Alpha', 1,
    {exact: false, oracle_text: '{T}: Add {G}.'}),
    'fdn|2|nonfoil': picture('Beta', 2), 'fdn|3|nonfoil': picture('Forest', 3)};
  const prices = {rows: {'fdn|1|nonfoil': {usd: .88, aud: 1.25}, 'fdn|1|foil': {usd: 3.16, aud: 4.5}},
    rate: 1.4217, rate_date: '2026-10-21', price_date: '2026-10-24', price_error: null};
  const storage = {rows: {'fdn|1|nonfoil': {held: 2, guess: true}, 'fdn|3|nonfoil': {held: null, guess: false}}, error: null};
  const draw = (data = {}) => { as('matt', MAY.admin); clear(main);
    return drawCollectionRows({space: 'home', sha256: 's1', rows, pictures, prices, storage, editable: true, ...data}, 'home'); };
  const tableRows = () => main.querySelectorAll('tr').filter(tr => tr.getAttribute('data-key'));
  const tableRow = key => tableRows().find(tr => tr.getAttribute('data-key') === key);
  const preview = () => main.querySelector('.col-preview');
  const casualRows = () => main.querySelectorAll('.col-casual-row');
  const search = text => { const input = main.querySelector('#col-row-search'); input.value = text; input.fire('input'); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionLayoutUiTests(unittest.TestCase):
    def run_js(self, scenario):
        done = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + scenario, True]),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "ok")

    def test_lab_selection_uses_the_printing_and_finish_key_and_keeps_the_picture_viewer(self):
        self.run_js("""
          const cv = draw(); assert.equal(cv.selectedKey, null);
          assert(preview().textContent.includes('Pick a card to see its copies'));
          assert(main.querySelector('.col-row-layout').contains(cv.list));
          assert(main.querySelector('.col-row-layout').contains(cv.preview));
          const key = 'fdn|1|foil', chosen = tableRow(key);
          chosen.querySelector('.col-open').click();
          assert.equal(cv.selectedKey, key); assert.notEqual(tableRow(key).getAttribute('data-selected'), null);
          assert.equal(tableRow(key).querySelector('.col-open').getAttribute('aria-current'), 'true');
          assert.equal(tableRow('fdn|1|nonfoil').getAttribute('data-selected'), null);
          const text = preview().textContent;
          for (const word of ['Alpha', 'FDN 1', 'Foil', 'Lightly Played', 'Japanese', '4.50']) assert(text.includes(word), word);
          assert(/2 cop(?:y|ies)/.test(text)); assert(!text.includes('9.00'));
          assert(/another printing|different printing|example/i.test(text));
          assert.equal(preview().querySelector('.col-preview-rules').querySelectorAll('.sym').length, 2);
          assert(!preview().textContent.includes('{T}')); assert(!preview().textContent.includes('{G}'));
          assert.equal(colSheets.size, 0); assert.equal(inspections.length, 0);
          tableRow(key).querySelector('.col-thumb').click();
          assert.equal(inspections.length, 1); assert.equal(inspections[0].card.name, 'Alpha');
        """)

    def test_preview_edit_resolves_the_current_row_and_rejects_stale_context(self):
        self.run_js("""
          const cv = draw(), key = 'fdn|1|foil'; colSelectRow(cv, key);
          const edit = preview().querySelector('.col-preview-edit'), opened = [];
          assert.equal(edit.textContent, 'Edit copies');
          openCollectionSheet = (view, record) => opened.push([view, record]);
          cv.rows = rows.map(r => colKey(r) === key ? {...r, quantity: 7} : r);
          edit.click(); assert.equal(opened.length, 1); assert.equal(opened[0][1].quantity, 7);
          state.profile = PROFILES.find(p => p.id === 'user2');
          edit.click(); colSelectRow(cv, 'fdn|2|nonfoil');
          assert.equal(opened.length, 1); assert.equal(cv.selectedKey, key);
          state.profile = PROFILES[0]; routeToken++;
          edit.click(); assert.equal(opened.length, 1);
        """)

    def test_selection_tracks_sorts_and_saves_and_clears_when_filtered_or_removed(self):
        self.run_js("""
          const cv = draw(), key = 'fdn|1|foil'; colSelectRow(cv, key);
          main.querySelector('.col-th-price').querySelector('button').click();
          assert.equal(cv.selectedKey, key); assert.equal(tableRow(key).querySelector('.col-open').getAttribute('aria-current'), 'true');
          colChanged(cv, {sha256: 's2', rows: rows.map(r => colKey(r) === key ? {...r, quantity: 8} : r),
            prices: {...prices, rows: {...prices.rows, [key]: {usd: 4, aud: 5.69}}}}, '');
          assert.equal(cv.selectedKey, key); assert(/8 cop(?:y|ies)/.test(preview().textContent));
          assert(preview().textContent.includes('5.69'));
          search('Beta'); assert.equal(cv.selectedKey, null);
          assert(preview().textContent.includes('Pick a card to see its copies')); assert(!preview().textContent.includes('5.69'));
          search(''); colSelectRow(cv, key);
          colChanged(cv, {sha256: 's3', rows: rows.filter(r => colKey(r) !== key)}, '');
          assert.equal(cv.selectedKey, null); assert(preview().textContent.includes('Pick a card to see its copies'));
        """)

    def test_casual_rows_use_a_separate_semantic_list_and_viewer_group(self):
        self.run_js("""
          draw(); const casual = main.querySelector('.col-row-casual'), list = casual.querySelector('.col-casual-list');
          assert.equal(list.tag, 'ul'); assert.equal(casual.querySelector('table'), null);
          assert(casualRows().every(node => node.tag === 'li' && !['row', 'cell'].includes(node.getAttribute('role'))));
          same(casualRows().map(node => node.getAttribute('data-key')), rows.map(colKey));
          const open = casualRows()[0].querySelector('.col-casual-open');
          assert.equal(open.getAttribute('data-viewer'), 'collection-casual-rows');
          assert(open.getAttribute('aria-label').includes('Alpha'));
          assert(open.getAttribute('aria-label').length < 160);
          open.click(); assert.equal(inspections.length, 1); assert.equal(inspections[0].card.name, 'Alpha');
          const group = viewerGroup(open); assert.equal(group.items.length, 4);
          assert(group.items[group.index].caption.textContent.includes('Edit copies'));
          assert(casualRows()[0].textContent.includes('1.25')); assert(!casualRows()[0].textContent.includes('5.00'));
          assert(casualRows()[2].textContent.includes('Condition not recorded'));
          assert(casualRows()[2].textContent.includes('Language not recorded'));
        """)

    def test_read_only_casual_notes_and_alternate_printing_warning_remain_readable(self):
        self.run_js("""
          const notes = ('Keep <script> & compare the handwritten note. ' + 'detail '.repeat(80)).slice(0, 500);
          assert.equal(notes.length, 500);
          const recorded = {...rows[1], notes};
          draw({rows: [recorded], editable: false});
          const item = casualRows()[0], open = item.querySelector('.col-casual-open');
          const note = item.querySelector('.col-casual-note');
          assert.equal(note.textContent, notes); assert(!open.contains(note));
          assert.equal(item.querySelector('script'), null);
          const caption = viewerGroup(open).items[0].caption;
          assert(caption.textContent.includes(notes));
          assert(caption.textContent.includes('Picture of another printing'));
          assert.equal(caption.querySelector('script'), null);
          assert(!caption.textContent.includes('Edit copies'));
          assert(open.getAttribute('aria-label').length < 160);
          open.click(); assert.equal(inspections.length, 1);
          draw({rows: [recorded], pictures: {}, editable: false});
          const unpictured = casualRows()[0];
          assert.equal(unpictured.querySelector('.col-casual-note').textContent, notes);
          assert.equal(unpictured.querySelector('.col-casual-open').tag, 'div');
          assert.equal(unpictured.querySelector('button'), null);
          draw({rows: [rows[0]], editable: false});
          assert.equal(casualRows()[0].querySelector('.col-casual-note'), null);
          assert(!viewerGroup(casualRows()[0].querySelector('.col-casual-open')).items[0].caption.textContent.includes('Picture of another printing'));
        """)

    def test_show_more_appends_without_duplicates_and_resets_with_filters_or_sort(self):
        self.run_js("""
          const many = Array.from({length: 105}, (_, i) => row('Card ' + String(i).padStart(3, '0'), i,
            {condition: i % 2 ? 'NM' : '', language: 'en'}));
          const cv = draw({rows: many, pictures: {}, prices: undefined, storage: undefined});
          assert.equal(cv.casualLimit, 24); assert.equal(casualRows().length, 24);
          main.querySelector('.col-show-more').click(); assert.equal(casualRows().length, 48);
          for (let i = 0; i < 3; i++) main.querySelector('.col-show-more').click();
          assert.equal(casualRows().length, 105);
          assert.equal(new Set(casualRows().map(node => node.getAttribute('data-key'))).size, 105);
          assert.equal(colShownRows(cv).length, 105);
          assert(main.querySelector('.col-bulk-open').textContent.includes('105 rows shown'));
          const more = main.querySelector('.col-show-more'); assert(!more || more.hidden || more.disabled);
          search('Card 10'); assert.equal(cv.casualLimit, 24); assert.equal(casualRows().length, 5);
          assert(main.querySelector('.col-bulk-open').textContent.includes('5 rows shown'));
          search(''); main.querySelector('.col-show-more').click(); assert.equal(casualRows().length, 48);
          main.querySelector('.col-th-name').querySelector('button').click();
          assert.equal(cv.casualLimit, 24); assert.equal(casualRows().length, 24);
          assert(casualRows()[0].textContent.includes('Card 104'));
          const unrecorded = main.querySelector('#col-unrecorded'); unrecorded.checked = true; unrecorded.fire('change');
          assert.equal(cv.casualLimit, 24); assert.equal(casualRows().length, 24); assert.equal(colShownRows(cv).length, 53);
          assert(main.querySelector('.col-bulk-open').textContent.includes('53 rows shown'));
        """)

    def test_preview_keeps_storage_uncertainty_basics_and_unknowns_explicit(self):
        self.run_js("""
          state.library = {decks: [{id: 'user2/casual/private', title: 'Private deck name'}]};
          const cv = draw(); colSelectRow(cv, 'fdn|1|nonfoil');
          let text = preview().textContent;
          assert(/2 free/.test(text)); assert(/guess|uncertain|[?]/i.test(text));
          assert(!main.textContent.includes('Private deck name')); assert(!main.textContent.includes('user2/casual/private'));
          colSelectRow(cv, 'fdn|3|nonfoil'); assert(/not tracked/i.test(preview().textContent));
          colChanged(cv, {sha256: 's2', rows, storage: {rows: {}, error: 'Counts unavailable.'}}, '');
          colSelectRow(cv, 'fdn|1|nonfoil'); text = preview().textContent;
          assert(/not known|unavailable|not recorded|cannot|can't/i.test(text));
          assert(!/4 free/.test(text)); assert(!/all in storage/i.test(text));
          const unknown = draw({pictures: {}, storage: undefined, prices: undefined});
          colSelectRow(unknown, 'fdn|2|nonfoil'); text = preview().textContent;
          assert(text.includes('Beta')); assert(text.includes('Condition not recorded')); assert(text.includes('Language not recorded'));
          assert(/not known|unavailable|not recorded|cannot|can't/i.test(text));
          const price = tableRow('fdn|2|nonfoil').querySelector('.col-td-price');
          assert.equal(price.querySelector('.cell-unknown').getAttribute('aria-hidden'), 'true');
          assert(price.querySelector('.sr-only').textContent.includes('No price'));
        """)

    def test_read_only_preview_and_casual_viewers_offer_no_edit_action(self):
        self.run_js("""
          const cv = draw({editable: false}); colSelectRow(cv, 'fdn|1|nonfoil');
          assert.equal(preview().querySelector('.col-preview-edit'), null);
          assert(!main.querySelectorAll('button').some(node => /^(Edit copies|Remove)/.test(node.textContent)));
          const open = casualRows()[0].querySelector('.col-casual-open'), group = viewerGroup(open);
          assert(!group.items[group.index].caption.textContent.includes('Edit copies'));
          open.click(); assert.equal(inspections.length, 1);
          const unknown = draw({pictures: {}, editable: true}), opened = [];
          openCollectionSheet = (view, record) => opened.push(record);
          casualRows()[2].querySelector('.col-casual-open').click();
          assert.equal(opened.length, 1); assert.equal(colKey(opened[0]), 'fdn|2|nonfoil');
          assert.equal(unknown.selectedKey, null);
        """)

    def test_casual_filter_button_uses_the_tracked_sheet_and_preserves_search_control(self):
        self.run_js("""
          const cv = draw({storage: {rows: {'fdn|1|nonfoil': {held: 4, guess: false}}, error: null}});
          const input = main.querySelector('#col-row-search');
          assert(main.querySelector('.col-row-tools').contains(input));
          assert(main.querySelector('.col-row-filter-options'));
          main.querySelector('.col-row-filter-toggle').click();
          assert.equal(colSheets.size, 1); const sheet = openDialog();
          assert(sheet.querySelectorAll('input').some(node => node.getAttribute('type') === 'checkbox'));
          const stored = sheet.querySelectorAll('label').find(node => node.textContent.includes('In storage only')).querySelector('input');
          stored.checked = true; stored.fire('change');
          assert.equal(cv.storageOnly, true); assert.equal(main.querySelector('#col-storage').checked, true);
          assert.equal(casualRows().length, 3);
          const sort = sheet.querySelector('select[aria-label="Sort card list"]'); sort.value = 'quantity:-1'; sort.fire('change');
          assert.equal(cv.sort.key, 'quantity'); assert.equal(cv.sort.dir, -1);
          assert(casualRows()[0].textContent.includes('Forest'));
          colCloseSheets(); assert.equal(colSheets.size, 0);
          search('Beta'); assert.equal(main.querySelector('#col-row-search'), input);
          assert.equal(casualRows().length, 1); assert.equal(colShownRows(cv).length, 1);
          cv.busy = true; main.querySelector('.col-row-filter-toggle').click(); assert.equal(colSheets.size, 0);
          const unavailable = draw({storage: {rows: {}, error: 'Unavailable'}});
          main.querySelector('.col-row-filter-toggle').click();
          const disabled = openDialog().querySelectorAll('label').find(node => node.textContent.includes('In storage only')).querySelector('input');
          assert.equal(disabled.disabled, true); assert.equal(unavailable.storageOnly, false);
          const filters = openDialog().querySelectorAll('input');
          state.profile = PROFILES.find(p => p.id === 'user2');
          filters[0].checked = true; filters[0].fire('change'); assert.equal(unavailable.unrecordedOnly, false);
        """)
