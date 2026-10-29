"""Location filters and exact-printing batch reviews over real UI scripts and disposable Node fixtures."""
import json
import subprocess
import unittest

from decklab.tests.test_collection_bulk_ui import FIXTURE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = FIXTURE + """
  const locationSha = 'a'.repeat(64), nextSha = 'b'.repeat(64);
  const locations = {'fdn|227|nonfoil': 'Row 2', 'sld|2539|nonfoil': 'Binder', 'lea|232|nonfoil': 'Row 2'};
  const drawLoc = (data = {}) => draw({locations: {ready: true, sha256: locationSha, rows: locations}, ...data});
  const places = cv => cv.root.querySelector('.col-location-filter');
  const filter = (cv, value) => choose(places(cv), value);
  const batch = (cv, selected = false) => openLocationBatch(cv, selected,
    selected ? cv.locationSelectedButton : cv.locationShownButton);
  const assign = (ctx, text) => { ctx.input.value = text; ctx.input.fire('input'); };
  const pick = (cv, key, index = 0) => {
    const input = cv.list.querySelectorAll('.col-bulk-check').filter(node => node.getAttribute('data-bulk-key') === key)[index];
    input.checked = true; input.fire('change'); return input;
  };
  const keys = ctx => ctx.list.querySelectorAll('[data-location-key]').map(node => node.getAttribute('data-location-key'));
  const saveButton = ctx => ctx.sheet.foot.querySelectorAll('button').find(node => node.textContent.startsWith('Save'));
  const save = async ctx => { saveButton(ctx).click(); await flush(); };
  const success = (cv, body, extra = {}) => ({ok: true, sha256: cv.sha256, rows: cv.rows, changed: body.keys.length,
    locations: {ready: true, sha256: nextSha, rows: {...cv.locations.rows,
      ...Object.fromEntries(body.keys.map(key => [colKey(key), body.location]))}}, ...extra});
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionLocationBulkUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_location_filter_composes_with_search_and_existing_filters(self):
        self.run_js("""
          const cv = drawLoc({storage: {rows: {'sld|2539|nonfoil': {held: 1}}, error: null}});
          filter(cv, 'none'); same(colShownRows(cv).map(row => row.name), ['Arcane Signet']);
          filter(cv, 'place:Binder'); same(colShownRows(cv).map(row => row.name), ['Sol Ring']);
          cv.unrecorded.checked = true; cv.unrecorded.fire('change'); assert.equal(colShownRows(cv).length, 1);
          cv.rowSearch.value = 'Sol'; cv.rowSearch.fire('input'); assert.equal(colShownRows(cv).length, 1);
          cv.storageBox.checked = true; cv.storageBox.fire('change'); assert.equal(colShownRows(cv).length, 0);
          button(cv.list, 'Clear the search and filters').click();
          assert.equal(cv.locationFilter, 'all'); assert.equal(colShownRows(cv).length, 4);
          assert.equal(places(cv).value, 'all');
        """)

    def test_exact_filter_retains_zero_matches_and_never_confuses_a_literal_none(self):
        self.run_js("""
          const cv = drawLoc(); filter(cv, 'place:Binder');
          cv.locations = {...cv.locations, sha256: nextSha, rows: {...locations, 'sld|2539|nonfoil': 'none'}};
          drawColRowList(cv);
          assert.equal(cv.locationFilter, 'place:Binder'); assert.equal(colShownRows(cv).length, 0);
          assert(places(cv).querySelectorAll('option').some(option => option.value === 'place:Binder'));
          filter(cv, 'place:none'); same(colShownRows(cv).map(row => row.name), ['Sol Ring']);
          filter(cv, 'none'); same(colShownRows(cv).map(row => row.name), ['Arcane Signet']);
        """)

    def test_casual_sheet_uses_same_filter_and_refused_native_changes_roll_back(self):
        self.run_js("""
          const cv = drawLoc(); colRowFilters(cv); const handle = [...colSheets].pop();
          const select = handle.dialog.querySelector('.col-location-filter'); select.focus(); choose(select, 'place:Row 2');
          assert.equal(cv.locationFilter, 'place:Row 2'); assert.equal(places(cv).value, 'place:Row 2');
          assert.equal(colShownRows(cv).length, 2); assert.equal(document.activeElement, select);
          setCollectionBusy(cv, true); choose(select, 'none'); assert.equal(select.value, 'place:Row 2');
          setCollectionBusy(cv, false); handle.close(); choose(select, 'all'); assert.equal(select.value, 'place:Row 2');
          assert.equal(cv.locationFilter, 'place:Row 2');
        """)

    def test_unavailable_or_unchecked_locations_cannot_filter_or_offer_a_write(self):
        self.run_js("""
          for (const locations of [{ready: false, sha256: locationSha, rows: {}}, {ready: true, rows: {}},
              {ready: true, sha256: null, rows: {}, error: 'Recorded locations could not be read.'},
              {ready: true, sha256: locationSha, rows: {}, error: 'Recorded locations could not be read.'}]) {
            const cv = drawLoc({locations});
            assert(places(cv).disabled); assert(cv.locationShownButton.disabled);
            assert(!cv.locationBatchNote.hidden); assert(cv.locationBatchNote.textContent);
            assert.equal(batch(cv), null); choose(places(cv), 'none'); assert.equal(cv.locationFilter, 'all');
            setCollectionBusy(cv, true); setCollectionBusy(cv, false);
            assert(places(cv).disabled); assert(cv.locationShownButton.disabled);
          }
        """)

    def test_read_only_view_can_filter_but_has_no_batch_actions_or_selection_checks(self):
        self.run_js("""
          const cv = drawLoc({editable: false}); filter(cv, 'place:Binder');
          assert.equal(colShownRows(cv).length, 1); assert.equal(batch(cv), null);
          assert.equal(main.querySelectorAll('.col-location-shown').length, 0);
          assert.equal(main.querySelectorAll('.col-location-selected').length, 0);
          assert.equal(main.querySelectorAll('.col-bulk-check').length, 0);
        """)

    def test_shown_review_lists_each_old_new_location_and_counts_rows_not_copies(self):
        self.run_js("""
          const cv = drawLoc({rows: rows.map(row => ({...row, quantity: 20}))}); filter(cv, 'place:Row 2');
          const ctx = batch(cv); assert.equal(ctx.rows.length, 2); assert(saveButton(ctx).disabled);
          assert(ctx.list.textContent.includes('20 copies')); assert(ctx.list.textContent.includes('FDN 227'));
          assign(ctx, ' Row 3,   C ');
          assert.equal(ctx.action, 'assign'); assert.equal(ctx.summary.textContent, 'Assigns the location to 2 rows in one change.');
          assert(ctx.list.textContent.includes('Row 2 \\u2192 Row 3, C'));
          assert(ctx.scope.textContent.includes('copies, condition, language, notes and deck lists stay'));
        """)

    def test_selected_review_reuses_the_one_native_subset_without_the_inspector(self):
        self.run_js("""
          const foil = {...rows[0], finish: 'foil', quantity: 8}; const cv = drawLoc({rows: [...rows, foil]});
          const input = pick(cv, colKey(foil), 1); assert.equal(document.activeElement, null);
          assert.equal(cv.selectedKey, null); assert.equal(cv.bulkSelected.size, 1);
          assert(!cv.locationSelectedButton.hidden); assert(cv.locationSelectedButton.textContent.includes('1 selected'));
          const ctx = batch(cv, true); same(keys(ctx), [colKey(foil)]); assert(ctx.list.textContent.includes('8 copies'));
          assert(ctx.list.textContent.includes('No location recorded')); assert(ctx.list.textContent.includes('Foil'));
          assert(input.getAttribute('aria-label').includes('batch changes'));
        """)

    def test_selected_save_sends_only_frozen_keys_and_both_hashes(self):
        self.run_js("""
          const cv = drawLoc(); pick(cv, colKey(rows[0])); pick(cv, colKey(rows[1]));
          const ctx = batch(cv, true), calls = []; assign(ctx, 'Row 4');
          apiWrite = async (path, body) => { calls.push([path, body]); return success(cv, body); };
          await save(ctx);
          same(calls, [['/api/collection/locations/bulk', {space: 'home', sha256: 's1', locations_sha256: locationSha,
            keys: [{set: 'fdn', collector_number: '227', finish: 'nonfoil'},
              {set: 'sld', collector_number: '2539', finish: 'nonfoil'}], location: 'Row 4'}]]);
          assert(ctx.sheet.closed); assert.equal(cv.bulkSelected.size, 0);
          assert.equal(cv.selectedKey, null); assert.equal(colLocationOf(cv, rows[0]), 'Row 4');
          same(cv.rows, rows); assert.equal(cv.sha256, 's1'); assert.equal(cv.locations.sha256, nextSha);
        """)

    def test_clearing_is_explicit_and_an_unchanged_assignment_cannot_save(self):
        self.run_js("""
          const cv = drawLoc(); filter(cv, 'place:Row 2'); const ctx = batch(cv), calls = [];
          assign(ctx, 'Row 2'); assert(saveButton(ctx).disabled); assert(ctx.summary.textContent.includes('Nothing to change'));
          assign(ctx, '   '); assert(saveButton(ctx).disabled); assert(ctx.summary.textContent.includes('choose Clear recorded locations'));
          choose(ctx.mode, 'clear'); assert(ctx.input.disabled); assert(ctx.summary.textContent.includes('Clears the location from 2 rows'));
          apiWrite = async (path, body) => { calls.push(body); return success(cv, body); }; await save(ctx);
          assert.equal(calls[0].location, ''); assert.equal(calls[0].keys.length, 2);
          assert.equal(cv.locationFilter, 'place:Row 2'); assert.equal(colShownRows(cv).length, 0);
          assert.equal(document.activeElement, cv.rowSearch);
        """)

    def test_invalid_location_text_never_posts(self):
        self.run_js("""
          const cv = drawLoc(), ctx = batch(cv); let writes = 0;
          apiWrite = async () => { writes++; throw Error('must not post'); };
          for (const text of ['=1+1', '@home', 'x'.repeat(41), 'Row\\n2', '\\u0085']) {
            assign(ctx, text); assert(saveButton(ctx).disabled, text); await saveLocationBatch(ctx);
          }
          assert.equal(writes, 0);
        """)

    def test_location_only_change_requires_new_review_even_with_same_collection_hash(self):
        self.run_js("""
          const cv = drawLoc(); pick(cv, colKey(rows[0])); const ctx = batch(cv, true); assign(ctx, 'Binder');
          let writes = 0; apiWrite = async (path, body) => { writes++; return success(cv, body); };
          cv.locations = {...cv.locations, sha256: nextSha, rows: {...locations, 'fdn|227|nonfoil': 'Row 3'}};
          await save(ctx); assert.equal(writes, 0); assert.equal(ctx.reviewSha, 's1');
          assert.equal(ctx.locationsSha, nextSha); assert(ctx.list.textContent.includes('Row 3 \\u2192 Binder'));
          assert(ctx.message.textContent.includes('Nothing was saved')); await save(ctx); assert.equal(writes, 1);
        """)

    def test_server_conflict_rebases_selected_keys_and_never_adds_a_new_printing(self):
        self.run_js("""
          const cv = drawLoc(); pick(cv, colKey(rows[0])); pick(cv, colKey(rows[1]));
          const ctx = batch(cv, true); assign(ctx, 'Row 4'); const calls = [];
          const added = row('Added', 'fdn', '1'), latest = [rows[0], rows[2], rows[3], added];
          apiWrite = async (path, body) => { calls.push(body);
            if (calls.length === 1) throw Object.assign(Error('Locations changed.'), {status: 409,
              data: {sha256: 's2', rows: latest, locations: {ready: true, sha256: nextSha,
                rows: {'fdn|227|nonfoil': 'Row 3'}}}});
            return success(cv, body); };
          await save(ctx); assert(!ctx.sheet.closed); same(keys(ctx), [colKey(rows[0])]);
          assert(ctx.message.textContent.includes('1 reviewed row no longer shown was left out'));
          assert(ctx.message.textContent.includes('No other rows were added')); assert(ctx.list.textContent.includes('Row 3'));
          await save(ctx); assert.equal(calls.length, 2); assert.equal(calls[1].sha256, 's2');
          assert.equal(calls[1].locations_sha256, nextSha); assert.equal(calls[1].keys.length, 1);
        """)

    def test_shown_scope_never_expands_after_filter_narrowing_or_conflict(self):
        self.run_js("""
          const cv = drawLoc(); filter(cv, 'place:Row 2'); const ctx = batch(cv); assign(ctx, 'Binder');
          cv.locationFilter = 'all'; cv.sha256 = 's2'; let calls = 0;
          apiWrite = async (path, body) => { calls++; assert.equal(body.keys.length, 2); return success(cv, body); };
          await save(ctx); assert.equal(calls, 0); assert.equal(ctx.rows.length, 2);
          cv.search = 'Llanowar'; await save(ctx); assert.equal(calls, 0); assert.equal(ctx.rows.length, 1);
          cv.search = ''; await save(ctx); assert.equal(calls, 1); // pruned keys never return
        """)

    def test_removed_scope_or_lost_capability_has_close_only_without_widening(self):
        self.run_js("""
          const cv = drawLoc(); filter(cv, 'place:Binder'); const ctx = batch(cv); assign(ctx, 'Row 4');
          apiWrite = async () => { throw Object.assign(Error('Review again.'), {status: 409,
            data: {sha256: 's1', rows, locations: {ready: true, sha256: nextSha, rows: {}}}}); };
          await save(ctx); assert.equal(ctx.rows.length, 0); assert.equal(saveButton(ctx), undefined);
          assert(button(ctx.sheet.dialog, 'Close')); assert.equal(cv.locationFilter, 'place:Binder');
          ctx.sheet.close(); cv.locationFilter = 'all'; drawColRowList(cv);
          const next = batch(cv); assign(next, 'Row 4');
          cv.locations = {ready: false, sha256: nextSha, rows: {}}; setCollectionBusy(cv, false);
          await saveLocationBatch(next); assert(cv.locationShownButton.disabled); assert(places(cv).disabled);
        """)

    def test_pending_closed_sheet_blocks_changes_and_late_success_preserves_newer_focus(self):
        self.run_js("""
          const cv = drawLoc(), ctx = batch(cv); assign(ctx, 'Row 4'); let resolve;
          apiWrite = (path, body) => new Promise(done => { resolve = () => done(success(cv, body)); });
          saveButton(ctx).click(); assert(cv.busy); assert(ctx.mode.disabled); assert(places(cv).disabled);
          ctx.sheet.close(); const input = cv.list.querySelector('.col-bulk-check');
          input.checked = true; input.fire('change'); assert(!input.checked); assert.equal(cv.bulkSelected.size, 0);
          const newer = el('button', {text: 'Keep focus'}); main.append(newer); newer.focus();
          resolve(); await flush(); assert(!cv.busy); assert.equal(document.activeElement, newer);
        """)

    def test_pending_failure_after_profile_change_releases_only_the_old_view(self):
        self.run_js("""
          const cv = drawLoc(), ctx = batch(cv); assign(ctx, 'Row 4'); let reject;
          apiWrite = () => new Promise((done, fail) => { reject = fail; }); saveButton(ctx).click();
          ctx.sheet.close(); as('user2', MAY.user2); const fresh = el('button', {text: 'Other view'}); main.append(fresh); fresh.focus();
          reject(Error('Late failure')); await flush(); assert(!cv.busy); assert.equal(document.activeElement, fresh);
          assert(!cv.message.textContent.includes('Late failure'));
        """)

    def test_revoked_permissions_detached_actions_and_stale_save_buttons_cannot_write(self):
        self.run_js("""
          const cv = drawLoc(), old = cv.locationShownButton; let calls = 0;
          const ctx = batch(cv); assign(ctx, 'Row 4'); const stale = saveButton(ctx); assign(ctx, 'Row 3');
          apiWrite = async (path, body) => { calls++; return success(cv, body); };
          stale.click(); await flush(); assert.equal(calls, 0);
          state.may = {...MAY.admin, spaces: []}; await saveLocationBatch(ctx); assert.equal(calls, 0);
          drawLocationBatch(ctx); assert.equal(saveButton(ctx), undefined); assert(ctx.list.hidden);
          assert(ctx.summary.textContent.includes('can no longer change'));
          ctx.sheet.close(); old.remove(); old.click(); assert.equal(colSheets.size, 0);
          drawColRowList(cv); assert(cv.locationSelectedButton.hidden); assert(cv.locationShownButton.hidden);
        """)

    def test_oversized_key_scope_is_explained_before_any_review_or_request(self):
        self.run_js("""
          const cv = drawLoc(); cv.rows = Array.from({length: STORAGE_LOCATION_BATCH_MAX + 1}, (_, i) => ({...rows[0], collector_number: String(i)}));
          let calls = 0; apiWrite = async () => { calls++; };
          assert.equal(batch(cv), null); assert.equal(colSheets.size, 0); assert.equal(calls, 0);
          assert(cv.message.textContent.includes('at most 50000 rows'));
          assert.equal(colLocationBodySize({place: '\\u00e9'}), 14);
        """)

    def test_oversized_body_is_explained_without_truncating_or_sending(self):
        self.run_js("""
          const cv = drawLoc({rows: [{...rows[0], collector_number: '1'.repeat(STORAGE_LOCATION_BODY_MAX)}]});
          const ctx = batch(cv); assign(ctx, 'Row 4'); let calls = 0;
          apiWrite = async () => { calls++; }; await save(ctx);
          assert.equal(calls, 0); assert.equal(ctx.rows.length, 1); assert(!ctx.sheet.closed);
          assert(ctx.message.textContent.includes('too large to send in one change'));
          assert(ctx.message.textContent.includes('narrow the search or selection'));
        """)

    def test_body_preflight_includes_the_profile_that_apiwrite_adds(self):
        self.run_js("""
          const body = {space: 'home', sha256: 's1', locations_sha256: locationSha,
            keys: [{set: 'fdn', collector_number: '', finish: 'nonfoil'}], location: 'Row 4'};
          const size = STORAGE_LOCATION_BODY_MAX - colLocationBodySize(body) - 5;
          body.keys[0].collector_number = '1'.repeat(size);
          assert(colLocationBodySize(body) <= STORAGE_LOCATION_BODY_MAX);
          assert(colLocationBodySize({profile: 'matt', ...body}) > STORAGE_LOCATION_BODY_MAX);
          const cv = drawLoc({rows: [{...rows[0], collector_number: body.keys[0].collector_number}]});
          const ctx = batch(cv); assign(ctx, 'Row 4'); let calls = 0;
          apiWrite = async () => { calls++; }; await save(ctx);
          assert.equal(calls, 0); assert(ctx.message.textContent.includes('too large to send'));
        """)


if __name__ == "__main__":
    unittest.main()
