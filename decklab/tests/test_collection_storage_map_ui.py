"""Storage-map proportions, section access, counting and stale review handling."""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + """
  as('matt', MAY.admin);
  location.hash = '#/collection?view=map';
  const white = {id: 'white', label: 'White creatures', container: 'Storage box', place: 'Row 1',
    quantity: 5, colour: 'white', audit: null};
  const black = {id: 'black', label: 'Black spells', container: 'Storage box', place: 'Row 2',
    quantity: 1, colour: 'black', audit: null};
  const empty = {id: 'green', label: 'Green spells', container: 'Storage box', place: 'Row 2',
    quantity: 0, colour: 'green', audit: null};
  const unknown = {id: 'unfiled', label: 'No storage location', quantity: 2, auditable: false, audit: null};
  const rows = [
    {key: 'fdn|1|nonfoil', name: 'Alpha', set: 'fdn', collector_number: '1', finish: 'nonfoil', quantity: 3, location: 'Row 1 B'},
    {key: 'fdn|1|foil', name: 'Alpha', set: 'fdn', collector_number: '1', finish: 'foil', quantity: 2, estimated: true},
  ];
  const render = (patch = {}) => drawCollectionStorageMap({space: 'home', ready: true, editable: true,
    sections: [white, black, empty, unknown],
    excluded: [{label: 'Uncounted basic lands', quantity: 3}, {label: 'Token availability unknown', quantity: null}],
    ...patch}, 'home');
  const detail = (patch = {}) => ({space: 'home', ready: true, editable: true, section: white, expect: 'proof', rows, ...patch});
  const chooseSection = id => main.querySelector('.col-map-section[data-section="' + id + '"]');
  const chooseVisual = id => main.querySelector('.col-map-segment[data-section="' + id + '"]');
  const action = words => button(openDialog(), words);
  const countInput = words => openDialog().querySelector('input[aria-label="' + words + '"]');
  const nonfoil = 'Counted for Alpha, FDN 1 · Non-foil';
  const foil = 'Counted for Alpha, FDN 1 · Foil';
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class StorageMapUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_section_area_reflects_expected_copies_with_full_size_controls(self):
        self.run_js("""
          render();
          same(main.querySelectorAll('.col-map-segment').map(node => node.style.flexGrow), [5, 1, 2]);
          same(main.querySelectorAll('.col-map-section').map(node => node.dataset.section), ['white', 'black', 'green', 'unfiled']);
          assert(main.textContent.includes('Uncounted basic lands (3 cards)'));
          assert(main.textContent.includes('Token availability unknown'));
          assert(!main.textContent.includes('Token availability unknown (0 cards)'));
          assert.equal(chooseVisual('white').getAttribute('tabindex'), '-1');
          assert.equal(chooseSection('green').getAttribute('tabindex'), null);
          assert(chooseSection('green').closest('details').textContent.includes('Empty sections (1)'));
          assert(chooseSection('white').getAttribute('aria-label').includes('Row 1, White creatures, 5 cards'));
          api = async path => {
            assert.equal(path, '/api/collection/storage-map?section=white');
            return detail();
          };
          chooseVisual('white').click(); await flush();
          assert(openDialog().textContent.includes('This section has never been audited.'));
          assert(action('Start audit'));
          action('Close').click(); assert.equal(document.activeElement, chooseVisual('white'));
        """)

    def test_count_review_payload_and_saved_differences_are_section_scoped(self):
        self.run_js("""
          render(); const writes = [];
          api = async () => detail();
          apiWrite = async (path, body) => {
            writes.push([path, body]);
            return {section: {...white, audit: {audited_at: '2026-11-21T03:00:00Z', current: true,
              expected: 5, observed: 3, mismatch_rows: 1, extra: 1, missing: 3, surplus: 0,
              differences: [{...rows[0], expected: 3, observed: 0}]}}};
          };
          chooseSection('white').click(); await flush();
          action('Start audit').click();
          assert(openDialog().textContent.includes('2 expected (estimate)'));
          assert(openDialog().textContent.includes('Row 1 B'));
          const describedBy = countInput(foil).getAttribute('aria-describedby');
          assert.equal(document.getElementById(describedBy).textContent, '2 expected (estimate)');
          action('Review count').click(); assert.equal(document.activeElement, countInput(nonfoil));
          countInput(nonfoil).value = '-1'; action('Review count').click();
          assert.equal(writes.length, 0);
          countInput(nonfoil).value = '0'; countInput('Unlisted cards counted').value = '1';
          action('Unentered counts match').click();
          assert.equal(countInput(nonfoil).value, '0');
          assert.equal(countInput(foil).value, '2');
          action('Review count').click();
          assert(openDialog().textContent.includes('3 cards missing'));
          assert(openDialog().textContent.includes('1 card unlisted'));
          assert(openDialog().textContent.includes('3 expected · 0 counted'));
          assert(!openDialog().textContent.includes('FDN 1 · Foil'));
          assert.equal(writes.length, 0);
          action('Edit count').click();
          assert.equal(countInput(nonfoil).value, '0');
          action('Review count').click(); action('Save audit').click(); await flush();
          same(writes, [['/api/collection/storage-map', {space: 'home', section: 'white', expect: 'proof',
            counts: {'fdn|1|nonfoil': 0, 'fdn|1|foil': 2}, extra: 1}]]);
          assert(openDialog().textContent.includes('Audit saved.'));
          assert(openDialog().textContent.includes('Last audited'));
          assert(openDialog().textContent.includes('3 expected · 0 counted'));
          assert(chooseSection('white').textContent.includes('Differences found'));
          assert(chooseSection('black').textContent.includes('Never audited'));
          action('Close').click();
          assert.equal(document.activeElement, chooseSection('white'));
        """)

    def test_stale_and_unplaced_sections_require_new_proof_or_a_location(self):
        self.run_js("""
          render(); let reads = 0, writes = 0;
          api = async path => {
            reads++;
            if (path.endsWith('unfiled')) return detail({section: unknown, editable: false,
              message: 'Assign a storage location before starting an audit.'});
            return detail({expect: 'proof-' + reads});
          };
          apiWrite = async () => { writes++; throw new ApiError(409, 'This section changed.'); };
          chooseSection('unfiled').click(); await flush();
          assert(openDialog().textContent.includes('Assign a storage location'));
          assert(openDialog().textContent.includes('Expected cards'));
          assert(openDialog().textContent.includes('FDN 1 · Non-foil'));
          assert.equal(action('Start audit'), null);
          assert(openDialog().querySelectorAll('button').every(button => button.textContent.trim()));
          action('Close').click();
          chooseSection('white').click(); await flush();
          action('Start audit').click(); action('Unentered counts match').click();
          action('Review count').click();
          assert(openDialog().textContent.includes('The count matched.'));
          assert(!openDialog().textContent.includes('null'));
          action('Save audit').click(); await flush();
          assert.equal(writes, 1); assert.equal(reads, 2);
          assert(openDialog().textContent.includes('This section changed.'));
          assert.equal(action('Save audit'), null);
          action('Reload section').click(); await flush();
          assert.equal(reads, 3); assert(action('Start audit')); assert.equal(writes, 1);
        """)

    def test_late_section_read_and_detached_controls_stay_with_the_original_profile(self):
        self.run_js("""
          render();
          let resolveRead, reads = 0;
          api = () => { reads++; return new Promise(resolve => { resolveRead = resolve; }); };
          const old = chooseSection('white');
          old.click(); const loading = openDialog();
          as('user1', MAY.user1);
          render(); resolveRead(detail()); await flush();
          assert(!loading.textContent.includes('Start audit'));
          old.click(); assert.equal(reads, 1);
          colCloseSheets(); chooseSection('white').click(); assert.equal(reads, 2);
        """)
