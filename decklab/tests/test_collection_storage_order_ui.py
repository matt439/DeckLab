"""Card list filing order from a space's storage setup, with fixture-only rows and saves."""
import json
import subprocess
import unittest

from decklab.tests.test_collection_layout_ui import FIXTURE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = FIXTURE + """
  const savedPrefs = new Map();
  window.localStorage = {getItem: key => savedPrefs.get(key), setItem: (key, value) => savedPrefs.set(key, value)};
  const box = {id: 'box', name: 'Box', kind: 'box', cards: 4, capacity: null, order: 'colour-type',
    sections: ['First', 'Second'], holds: {First: 'lands', Second: 'creatures'}};
  const binder = {id: 'binder', name: 'Binder', kind: 'binder', cards: 1, capacity: 360, order: 'set', sections: []};
  const filing = {source: 'saved', default: 'box', suggestions: [], containers: [binder, box],
    placements: {'Binder': ['binder', null], 'First, B': ['box', 'First'], Desk: [null, null]}};
  const locations = {ready: true, sha256: 'a'.repeat(64),
    rows: {'fdn|1|foil': 'Binder', 'fdn|2|nonfoil': 'First, B', 'fdn|1|nonfoil': 'Desk'}};
  const keys = () => tableRows().map(tr => tr.getAttribute('data-key'));
  const options = () => { button(main, 'Filter and sort').click();
    return openDialog().querySelector('select[aria-label="Sort card list"]'); };
  const chooseStorage = () => {
    const select = options(); assert(select.querySelector('option[value="storage:1"]'));
    select.value = 'storage:1'; select.fire('change'); colCloseSheets();
  };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionStorageOrderUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_member_exact_printing_placement_and_section_sequence(self):
        self.run_js("""
          as('user2', MAY.user2);
          const original = rows.map(colKey);
          const cv = drawCollectionRows({space: 'user2', sha256: 's1', editable: true,
            rows, pictures, locations, storage_setup: filing}, 'user2');
          chooseStorage();
          // Same-name foil in the first binder. Beta is explicitly filed alongside Forest in First.
          same(keys(), ['fdn|1|foil', 'fdn|2|nonfoil', 'fdn|3|nonfoil', 'fdn|1|nonfoil']);
          same(casualRows().map(r => r.querySelector('.col-casual-name').textContent), ['Alpha', 'Beta', 'Forest', 'Alpha']);
          assert(cv.count.textContent.includes('Storage order'));
          search('Alpha'); same(keys(), ['fdn|1|foil', 'fdn|1|nonfoil']);
          const saved = options(); assert.equal(saved.value, 'storage:1'); colCloseSheets();
          assert.equal(local.get('collection.rowsSort'), 'storage:1');
          same(cv.rows.map(colKey), original);
        """)

    def test_saved_sort_uses_full_list_before_paging_and_falls_back_for_missing_or_invalid_setup(self):
        self.run_js("""
          const many = Array.from({length: 102}, (_, i) => row('Card ' + (102 - i), i + 1));
          const setup = {...filing, containers: [binder], default: 'binder', placements: {}};
          const cv = draw({rows: many, pictures: {}, locations: {ready: true, rows: {}}, storage_setup: setup});
          chooseStorage();
          same(keys(), many.slice(0, COL_ROWS_PAGE).map(colKey));
          assert.equal(casualRows().length, COL_CASUAL_ROWS);
          button(main, 'Show more').click(); assert(casualRows()[COL_CASUAL_ROWS].textContent.includes('Card 78'));
          cv.page = 2; drawColRowList(cv); same(keys(), many.slice(COL_ROWS_PAGE).map(colKey));
          for (const data of [{}, {storage_setup: {...setup, placements: null}}, {storage_setup: {...setup, placements: {Desk: 4}}},
              {storage_setup: {...setup, containers: [{...binder, sections: null}]}},
              {storage_setup: setup, locations: {ready: false, rows: {}}}]) {
            const unavailable = draw({locations, ...data});
            assert(!unavailable.count.textContent.includes('Storage order'));
            const select = options(); assert.equal(select.value, 'name:1');
            assert.equal(select.querySelector('option[value="storage:1"]'), null); colCloseSheets();
          }
          const alphabetical = draw({locations, storage_setup: {...setup, containers: [{...binder, order: 'name'}]}});
          assert(alphabetical.count.textContent.includes('Storage order'));
          colChanged(alphabetical, {rows, sha256: 'new'}, '');
          assert(!alphabetical.count.textContent.includes('Storage order'));
        """)

    def test_filing_guide_tracks_storage_sort_and_survives_redraw(self):
        self.run_js("""
          const cv = draw({storage_setup: filing, locations});
          const guides = () => main.querySelectorAll('.storage-filing-guide').filter(node => !node.hidden);
          assert.equal(guides().length, 0);
          chooseStorage();
          assert.equal(guides().length, 1);
          const [guide] = guides();
          assert(guide.matches('details')); assert(!cv.list.contains(guide));
          assert.equal(guide.querySelector('summary').textContent, 'Colour order and where artifacts go');
          guide.open = true;
          search('Alpha');
          assert.equal(guides()[0], guide); assert(guide.isConnected && guide.open);
          const select = options(); select.value = 'name:1'; select.fire('change'); colCloseSheets();
          assert.equal(guides().length, 0);
          chooseStorage(); assert.equal(guides().length, 1);
          colChanged(cv, {rows, sha256: 's2', locations,
            storage_setup: {...filing, default: 'binder', containers: [binder], placements: {}}}, '');
          assert(cv.count.textContent.includes('Storage order')); assert.equal(guides().length, 0);
          colChanged(cv, {rows, sha256: 's3', locations, storage_setup: filing}, '');
          assert.equal(guides().length, 1);
          colChanged(cv, {rows, sha256: 's4'}, '');
          assert(!cv.count.textContent.includes('Storage order')); assert.equal(guides().length, 0);
        """)

    def test_older_refresh_cannot_override_a_newer_write_and_open_sort_options_follow_fresh_rows(self):
        self.run_js("""
          const cv = draw({storage_setup: filing, locations});
          chooseStorage();
          let finish;
          api = () => new Promise(resolve => { finish = resolve; });
          const pending = colEnsureRows(cv, {refresh: true});
          const select = options();
          colChanged(cv, {rows, sha256: 'new'}, '');
          assert.equal(select.querySelector('option[value="storage:1"]'), null);
          assert.equal(select.value, 'name:1');
          finish({rows: [], sha256: 'old', storage_setup: filing, locations}); await pending;
          assert.equal(cv.sha256, 'new'); assert.equal(cv.rows.length, 4);
          colChanged(cv, {rows, sha256: 'current', storage_setup: filing, locations}, '');
          assert.equal(select.value, 'storage:1'); assert(select.querySelector('option[value="storage:1"]'));
          colCloseSheets();
        """)

    def test_setup_save_refreshes_active_sort_and_keeps_a_successful_write_on_a_failed_refresh(self):
        self.run_js("""
          const setup = {...filing, default: 'binder', containers: [binder], placements: {}};
          const data = {sha256: 's1', storage_setup: setup, locations: {ready: true, rows: {}},
            rows: [row('Zebra', 9), row('Apple', 10)]};
          const view = record => ({space: 'home', revision: 1, source: 'saved', ready: true,
            can_edit: true, storage: record});
          const record = {default: 'binder', containers: [binder]};
          const next = {default: 'binder', containers: [{...binder, order: 'name'}]};
          for (const fails of [false, true]) {
            const cv = draw(data); chooseStorage();
            same(keys(), ['fdn|9|nonfoil', 'fdn|10|nonfoil']);
            const read = [], write = [];
            api = async path => { read.push(path);
              if (path.startsWith('/api/storage?')) return view(record);
              if (fails) throw Error('offline');
              return {...data, storage_setup: {...setup, containers: next.containers}};
            };
            apiWrite = async (path, body) => { write.push(path);
              if (path === '/api/storage/preview') return {storage: next,
                after: {...setup, containers: next.containers, placements: undefined}, moves: []};
              assert.equal(body.storage.containers[0].order, 'name'); return view(next);
            };
            const editor = await openStorageSetup(cv);
            const order = editor.edit.querySelectorAll('select').find(s => s.querySelector('option[value="colour-type"]'));
            order.value = 'name'; order.fire('change');
            button(editor.sheet.foot, 'Preview').click(); await flush();
            button(editor.sheet.foot, 'Save storage setup').click(); await flush();
            same(write, ['/api/storage/preview', '/api/storage']);
            assert.equal(read.length, 2); assert(read[1].startsWith('/api/collection/rows'));
            same(keys(), ['fdn|10|nonfoil', 'fdn|9|nonfoil']);
            assert.equal(cv.count.textContent.includes('Storage order'), !fails);
            assert(cv.message.textContent.includes('Storage setup saved.'));
            assert.equal(cv.message.textContent.includes('Reload the Card list'), fails);
          }
        """)


if __name__ == "__main__":
    unittest.main()
