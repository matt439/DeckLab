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
  const red = {id: 'red', label: 'Red creatures', container: 'Storage box', place: 'Row 1',
    quantity: 2, colour: 'red', audit: null};
  const unknown = {id: 'unfiled', label: 'No storage location', quantity: 2, auditable: false, audit: null};
  const rows = [
    {key: 'fdn|1|nonfoil', name: 'Alpha', set: 'fdn', collector_number: '1', finish: 'nonfoil', quantity: 3, location: 'Row 1 B'},
    {key: 'fdn|1|foil', name: 'Alpha', set: 'fdn', collector_number: '1', finish: 'foil', quantity: 2, estimated: true},
  ];
  const render = (patch = {}) => drawCollectionStorageMap({space: 'home', ready: true, editable: true,
    containers: [{name: 'Storage box', sections: ['Row 1', 'Row 2', 'Row 3', 'Row 4']}],
    sections: [white, red, black, empty, unknown],
    excluded: [{label: 'Uncounted basic lands', quantity: 3}, {label: 'Token availability unknown', quantity: null}],
    ...patch}, 'home');
  const detail = (patch = {}) => ({space: 'home', ready: true, editable: true, section: white, expect: 'proof', rows, ...patch});
  const chooseSection = id => main.querySelector('.col-map-section[data-section="' + id + '"]');
  const physicalRows = () => main.querySelectorAll('.col-map-row');
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

    def test_expected_loose_cards_match_physical_rows_including_empty_rows(self):
        self.run_js("""
          render();
          same(physicalRows().map(node => node.querySelector('.col-map-section-name').textContent), ['Row 1', 'Row 2', 'Row 3', 'Row 4']);
          same(physicalRows().map(node => node.querySelector('.col-map-section-count').textContent), ['7 cards', '1 card', '0 cards', '0 cards']);
          same(physicalRows().map(node => node.querySelector('.col-map-row-bar').style['--col-map-share']), ['70%', '10%', '0%', '0%']);
          same(physicalRows()[0].querySelectorAll('.col-map-section').map(node => node.dataset.section), ['white', 'red']);
          assert(!chooseSection('unfiled').closest('.col-map-row'));
          assert(main.textContent.includes('Uncounted basic lands (3 cards)'));
          assert(main.textContent.includes('Token availability unknown'));
          assert(!main.textContent.includes('Token availability unknown (0 cards)'));
          assert.equal(chooseSection('green').getAttribute('tabindex'), null);
          assert(chooseSection('green').closest('details').textContent.includes('Empty sections (1)'));
          assert(chooseSection('white').getAttribute('aria-label').includes('Row 1, White creatures, 5 cards'));
          api = async path => {
            assert.equal(path, '/api/collection/storage-map?section=white');
            return detail();
          };
          physicalRows()[0].setAttribute('open', '');
          chooseSection('white').click(); await flush();
          assert(openDialog().textContent.includes('This section has never been audited.'));
          const count = action('Count by hand');
          assert.equal(document.getElementById(count.getAttribute('aria-describedby')).textContent,
            'Review your counts and save a dated audit with any differences.');
          action('Close').click(); assert.equal(document.activeElement, chooseSection('white'));
        """)

    def test_custom_containers_keep_section_order_and_separate_unassigned_counts(self):
        self.run_js("""
          const binder = {id: 'binder', label: 'Binder', container: 'Binder', quantity: 4};
          const unassigned = {...black, place: null};
          render({containers: [{name: 'Storage box', sections: ['Row 2', 'Row 1']}, {name: 'Binder', sections: []}],
            sections: [white, unassigned, binder]});
          same(physicalRows().map(node => node.querySelector('.col-map-section-name').textContent), ['Row 2', 'Row 1', 'Binder']);
          same(physicalRows().map(node => node.querySelector('.col-map-section-count').textContent), ['0 cards', '5 cards', '4 cards']);
          assert(!chooseSection('black').closest('.col-map-row'));
          assert(main.textContent.includes('Storage box · No section assigned'));
        """)

    def test_count_review_payload_and_saved_differences_are_section_scoped(self):
        self.run_js("""
          render(); const writes = [];
          physicalRows()[0].setAttribute('open', '');
          api = async () => detail();
          apiWrite = async (path, body) => {
            writes.push([path, body]);
            return {section: {...white, audit: {audited_at: '2026-11-21T03:00:00Z', current: true,
              expected: 5, observed: 3, mismatch_rows: 1, extra: 1, missing: 3, surplus: 0,
              differences: [{...rows[0], expected: 3, observed: 0}]}}};
          };
          chooseSection('white').click(); await flush();
          action('Count by hand').click();
          assert(openDialog().textContent.includes('2 expected (estimate)'));
          assert(openDialog().textContent.includes('Row 1 B'));
          const describedBy = countInput(foil).getAttribute('aria-describedby');
          assert.equal(document.getElementById(describedBy).textContent, '2 expected (estimate)');
          action('Review count').click(); assert.equal(document.activeElement, countInput(nonfoil));
          countInput(nonfoil).value = '-1'; action('Review count').click();
          assert.equal(writes.length, 0);
          countInput(nonfoil).value = '0'; countInput('Unidentified copies').value = '1';
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
          assert(chooseSection('white').textContent.includes('Needs review'));
          assert(physicalRows()[0].querySelector('summary').textContent.includes('Needs review · 1 section'));
          assert(chooseSection('black').textContent.includes('Never audited'));
          assert.equal(physicalRows()[0].getAttribute('open'), '');
          action('Keep for later').click();
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
          assert.equal(action('Count by hand'), null);
          assert(openDialog().querySelectorAll('button').every(button => button.textContent.trim()));
          action('Close').click();
          chooseSection('white').click(); await flush();
          action('Count by hand').click(); action('Unentered counts match').click();
          action('Review count').click();
          assert(openDialog().textContent.includes('The count matched the estimates shown.'));
          assert(!openDialog().textContent.includes('null'));
          action('Save audit').click(); await flush();
          assert.equal(writes, 1); assert.equal(reads, 2);
          assert(openDialog().textContent.includes('This section changed.'));
          assert.equal(action('Save audit'), null);
          action('Reload section').click(); await flush();
          assert.equal(reads, 3); assert(action('Count by hand')); assert.equal(writes, 1);
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
          assert(!loading.textContent.includes('Count by hand'));
          old.click(); assert.equal(reads, 1);
          colCloseSheets(); chooseSection('white').click(); assert.equal(reads, 2);
        """)

    def test_saved_manual_audit_keeps_named_extras_and_can_be_rechecked(self):
        self.run_js("""
          const named = {name: 'Beta', set: 'fdn', collector_number: '2', finish: 'etched', quantity: 1};
          const difference = {...named, key: 'fdn|2|etched', expected: 0, observed: 1};
          const recorded = {...white, audit: {current: false, needs_review: true, expected: 5, observed: 6,
            mismatch_rows: 1, extra: 1, unidentified_extra: 0, differences: [difference]}};
          render();
          api = async () => detail({excluded_names: ['Island']});
          let picker; const writes = [];
          globalThis.openStorageAuditUnlisted = options => { picker = options; };
          apiWrite = async (path, body) => {
            writes.push(body);
            return writes.length === 1 ? {section: recorded, expect: 'next-proof'} :
              {section: {...white, audit: {current: true, needs_review: false, expected: 5, observed: 5,
                mismatch_rows: 0, extra: 0, differences: []}}, expect: 'latest-proof'};
          };
          physicalRows()[0].setAttribute('open', '');
          chooseSection('white').click(); await flush();
          action('Count by hand').click();
          action('Identify unlisted printings').click();
          same(picker.excludedNames, ['Island']); assert(picker.current());
          picker.finish([named]);
          assert(openDialog().textContent.includes('Beta'));
          action('Unentered counts match').click(); action('Review count').click();
          assert(openDialog().textContent.includes('0 expected · 1 counted')); assert.equal(writes.length, 0);
          action('Save audit').click(); await flush();
          same(writes[0].unlisted, [{set: 'fdn', collector_number: '2', finish: 'etched', quantity: 1}]);
          assert.equal(writes[0].extra, 0);
          assert(chooseSection('white').textContent.includes('Needs review'));
          assert(chooseSection('white').textContent.includes('Changed since audit'));
          assert(action('Keep for later')); assert(action('Review collection copies'));
          action('Count by hand').click(); action('Unentered counts match').click();
          action('Review count').click(); action('Save audit').click(); await flush();
          assert.equal(writes[1].expect, 'next-proof'); assert(!writes[1].unlisted);
          assert(chooseSection('white').textContent.includes('Count matched'));
          assert(!physicalRows()[0].querySelector('summary').textContent.includes('Needs review'));
        """)

    def test_stale_reload_refreshes_the_collapsed_rows_follow_up_status(self):
        self.run_js("""
          const reviewed = {...white, audit: {current:false, mismatch_rows:1, extra:0, needs_review:true,
            expected:5, observed:3, missing:2, differences:[{...rows[1], expected:2, observed:0}]}};
          const matching = {...white, audit: {current:true, mismatch_rows:0, extra:0, needs_review:false,
            expected:5, observed:5, differences:[]}};
          render({sections:[reviewed, red, black, empty, unknown]});
          let reads = 0;
          api = async () => detail({section:++reads === 1 ? reviewed : matching});
          apiWrite = async () => { throw new ApiError(409, "An audit was saved elsewhere."); };
          physicalRows()[0].setAttribute('open', '');
          chooseSection('white').click(); await flush();
          assert(physicalRows()[0].querySelector('summary').textContent.includes('Needs review'));
          action('Count by hand').click(); action('Unentered counts match').click();
          action('Review count').click(); action('Save audit').click(); await flush();
          action('Reload section').click(); await flush();
          assert(openDialog().textContent.includes('The count matched.'));
          action('Close').click();
          assert.equal(document.activeElement, chooseSection('white'));
          assert(chooseSection('white').textContent.includes('Count matched'));
          assert(!physicalRows()[0].querySelector('summary').textContent.includes('Needs review'));
        """)
