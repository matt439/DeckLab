"""Collection warning and reason interactions over the real scripts, with fixture APIs."""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + """
  const original = {name: 'Llanowar Elves', set: 'fdn', collector_number: '227', finish: 'nonfoil', quantity: 4,
    condition: 'NM', language: 'en', notes: ''};
  const warnings = [{name: 'Llanowar Elves', before: 4, after: 2, in_use: 4, shortage: 2,
    holders: [{id: 'casual/elves', title: 'Built Elves', qty: 4}]}];
  const make = async () => {
    as('matt', MAY.admin);
    const cv = drawCollectionRows({space: 'home', sha256: 's1', rows: [original], editable: true}, 'home');
    api = async () => ({name: original.name, printings: [{set: 'fdn', set_name: 'Foundations',
      collector_number: '227', finishes: ['nonfoil'], released: '2024'}]});
    const ctx = openCollectionSheet(cv, original); await flush();
    return {cv, ctx};
  };
  const saved = (row = original) => ({ok: true, sha256: 's2', rows: [row]});
  const useWarning = () => new ApiError(409, 'These copies may be in use.', {in_use: warnings, confirm_in_use: 'review-token'});
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionGuardsUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_reduction_quick_pick_and_optional_blank_reason(self):
        self.run_js("""
          for (const reason of ['sold', '']) {
            const {ctx} = await make(); ctx.inputs.quantity.value = '2';
            const calls = []; apiWrite = async (path, body) => { calls.push(body); return saved({...original, quantity: 2}); };
            const pending = saveCollectionSheet(ctx); await flush();
            assert.equal(calls.length, 0); const why = openDialog(); assert(why.textContent.includes('Why (optional)'));
            if (reason) button(why, 'Sold').click();
            button(why, 'Save reduction').click(); await pending;
            assert.equal(calls.length, 1); assert.equal(calls[0].reason, reason); assert.equal(calls[0].row.quantity, 2);
          }
        """)

    def test_cancel_reduction_keeps_the_form_and_metadata_changes_need_no_reason(self):
        self.run_js("""
          const {ctx} = await make(); ctx.inputs.quantity.value = '2'; let writes = 0;
          apiWrite = async path => { if (path === '/api/collection/save') writes++; return saved(); };
          const pending = saveCollectionSheet(ctx); await flush(); button(openDialog(), 'Keep it').click(); await pending;
          assert.equal(writes, 0); assert(!ctx.sheet.closed); assert.equal(ctx.inputs.quantity.value, '2');
          ctx.inputs.quantity.value = '4'; ctx.inputs.notes.value = 'Corrected note';
          await saveCollectionSheet(ctx); assert.equal(writes, 1); assert.equal(document.querySelectorAll('dialog').length, 0);
        """)

    def test_in_use_warning_names_decks_and_requires_an_explicit_override(self):
        self.run_js("""
          const {ctx} = await make(); ctx.inputs.quantity.value = '2'; const calls = [];
          apiWrite = async (path, body) => { calls.push(body); if (calls.length === 1) throw useWarning(); return saved(); };
          const pending = saveCollectionSheet(ctx); await flush(); button(openDialog(), 'Traded').click();
          button(openDialog(), 'Save reduction').click(); await flush();
          const warning = openDialog(); assert(warning.textContent.includes('2 owned after this change; 4 in use (2 short)'));
          assert(warning.textContent.includes('Take these cards out of the deck'));
          assert.equal(warning.querySelector('a').getAttribute('href'), deckHref('casual/elves'));
          assert.equal(warning.querySelector('a').textContent, 'Built Elves'); assert.equal(calls.length, 1);
          button(warning, 'Save anyway').click(); await pending;
          assert.equal(calls.length, 2); assert.equal(calls[1].confirm_in_use, 'review-token'); assert.equal(calls[1].reason, 'traded');
        """)

    def test_remove_quick_pick_and_cancel_or_confirm_in_use(self):
        self.run_js("""
          for (const proceed of [false, true]) {
            const {cv, ctx} = await make(); ctx.sheet.close(); const calls = [];
            apiWrite = async (path, body) => { calls.push(body); if (calls.length === 1) throw useWarning(); return {ok: true, sha256: 's2', rows: []}; };
            const pending = removeCollectionRow(cv, original); await flush(); button(openDialog(), 'Sold').click();
            button(openDialog(), 'Remove').click(); await flush();
            button(openDialog(), proceed ? 'Remove anyway' : 'Keep the collection').click(); await pending;
            assert.equal(calls.length, proceed ? 2 : 1); assert.equal(cv.busy, false);
            if (proceed) { assert.equal(calls[1].reason, 'sold'); assert.equal(calls[1].confirm_in_use, 'review-token'); }
            else assert.equal(cv.rows[0].quantity, 4);
          }
        """)

    def test_rebase_preserves_reason_and_reviews_held_demand_again(self):
        self.run_js("""
          const {ctx} = await make(); ctx.inputs.quantity.value = '2'; const calls = [];
          const theirs = {...original, notes: 'Changed elsewhere'};
          apiWrite = async (path, body) => {
            calls.push(body);
            if (calls.length === 1) throw new ApiError(409, 'Changed', {sha256: 's9', rows: [theirs]});
            if (calls.length === 2) throw useWarning();
            return saved({...theirs, quantity: 2});
          };
          const pending = saveCollectionSheet(ctx); await flush(); button(openDialog(), 'Traded').click();
          button(openDialog(), 'Save reduction').click(); await pending;
          button(openDialog(), 'Load the latest and re-apply my changes').click(); await flush();
          assert.equal(openDialog().querySelector('h2').textContent, 'Copies in use');
          button(openDialog(), 'Save anyway').click(); await flush();
          assert.equal(calls.length, 3); assert(calls.every(body => body.reason === 'traded'));
          assert.equal(calls[1].sha256, 's9'); assert.equal(calls[1].row.notes, 'Changed elsewhere');
          assert.equal(calls[1].confirm_in_use, undefined); assert.equal(calls[2].confirm_in_use, 'review-token');
        """)

    def test_late_warning_after_profile_switch_is_not_shown_or_confirmed(self):
        self.run_js("""
          const {ctx} = await make(); let reject;
          apiWrite = () => new Promise((resolve, fail) => { reject = fail; });
          ctx.inputs.notes.value = 'Edit'; const pending = saveCollectionSheet(ctx); await flush();
          state.profile = PROFILES.find(profile => profile.id === 'user2'); reject(useWarning()); await pending;
          assert(!document.body.textContent.includes('Built Elves')); assert(!button(document.body, 'Save anyway'));
        """)

    def test_late_rows_after_navigation_do_not_open_a_new_reduction_prompt(self):
        self.run_js("""
          const {cv, ctx} = await make(); ctx.inputs.quantity.value = '2'; let rows; let writes = 0;
          cv.sha256 = null; cv.rows = null;
          api = () => new Promise(resolve => { rows = resolve; });
          apiWrite = async () => { writes++; return saved(); };
          const pending = saveCollectionSheet(ctx); await flush();
          location.hash = '#/wishlist'; showWishlist = () => {}; noteVisit = () => {}; route();
          rows({sha256: 'latest', rows: [original]}); await pending;
          assert.equal(document.querySelectorAll('dialog').length, 0, document.body.textContent); assert.equal(colSheets.size, 0);
          assert.equal(writes, 0);
        """)

    def test_late_save_and_import_success_do_not_notify_another_profile(self):
        self.run_js("""
          const {cv, ctx: edit} = await make(); edit.sheet.close(); const said = []; toast = words => said.push(words);
          const ctx = openImportSheet(cv); ctx.preview = {token: 'reviewed'}; let finish;
          apiWrite = () => new Promise(resolve => { finish = resolve; });
          const pending = applyImport(ctx, false); await flush();
          colCloseSheets(); state.profile = PROFILES[2];
          finish({sha256: 's2', added: {rows: 1, cards: 4}}); await pending;
          colChanged(cv, saved(), 'Llanowar Elves saved.'); same(said, []);
        """)

    def test_late_precon_success_does_not_navigate_or_carry_saved_metadata(self):
        self.run_js("""
          const {cv, ctx: edit} = await make(); edit.sheet.close(); location.hash = '#/collection';
          const sheet = colOpenSheet('Add a precon'); const titleInput = el('input', {value: 'Private title'});
          const ctx = {cv, sheet, titleInput, titleNote: el('p'), message: el('div'), whose: 'the home collection', busy: false,
            preview: {ready: true, editable: true, sha256: 's1', deck: {file: 'test.json', name: 'Fixture precon'}}};
          let finish; apiWrite = () => new Promise(resolve => { finish = resolve; }); state.saved = null;
          const pending = addPrecon(ctx); await flush(); colCloseSheets(); state.profile = PROFILES[2];
          finish({collection: {added: {cards: 60}}, deck: {id: 'casual/private-title', title: 'Private title'}}); await pending;
          assert.equal(state.saved, null); assert.equal(location.hash, '#/collection');
        """)

    def test_nested_printing_picker_closes_with_its_collection_sheet(self):
        self.run_js("""
          const {ctx} = await make(); let reply;
          api = () => new Promise(resolve => { reply = resolve; });
          const pending = colPickBig(ctx, original.name); await flush();
          assert.equal(colSheets.size, 2); assert.equal(document.querySelectorAll('dialog').length, 2);
          drawWho(); reply({printings: []}); await pending; await flush();
          assert.equal(colSheets.size, 0); assert.equal(document.querySelectorAll('dialog').length, 0);
          assert(!document.body.textContent.includes('Looking up its printings'));
        """)

    def test_repeat_import_metadata_and_concurrent_import_require_a_new_preview(self):
        self.run_js("""
          const {cv, ctx: edit} = await make(); edit.sheet.close(); let previews = 0, applies = 0;
          route = () => {}; const ctx = openImportSheet(cv);
          apiWrite = async (path, body) => {
            if (path.endsWith('/preview')) {
              previews++; assert.equal(body.filename, 'copy.csv'); assert.equal(body.text, 'original content');
              return {token: 't' + previews, adds: {rows: 1, cards: 2}, rows: [], problems: [],
                repeat_imports: previews === 1 ? [] : [{name: 'earlier.csv', imported_at: '2026-10-14', imported_by: 'Matt'},
                  {name: 'historic.csv', imported_at: null, imported_by: null}]};
            }
            applies++; if (applies === 1) throw new ApiError(409, 'Imports changed; preview again.', {repreview_required: true});
            assert.equal(body.token, 't2'); return {sha256: 's2', added: {rows: 1, cards: 2}};
          };
          await previewImport(ctx, 'copy.csv', 'original content'); await applyImport(ctx, false);
          assert.equal(ctx.preview, null); assert(!button(ctx.sheet.dialog, 'Import 2 cards'));
          button(ctx.sheet.dialog, 'Preview again').click(); await flush();
          assert(ctx.area.textContent.includes('This file was already imported'));
          assert(ctx.area.textContent.includes('earlier.csv: imported on 2026-10-14; by Matt'));
          assert(ctx.area.textContent.includes('import date not recorded; importer not recorded'));
          assert(ctx.area.textContent.includes('adds these copies again'));
          assert.equal(applies, 1); button(ctx.sheet.dialog, 'Import 2 cards').click(); await flush(); assert.equal(applies, 2);
        """)

    def test_file_selection_invalidates_old_previews_and_late_file_reads(self):
        self.run_js("""
          const {cv, ctx: edit} = await make(); edit.sheet.close(); const ctx = openImportSheet(cv);
          const files = []; let first;
          apiWrite = async (path, body) => { files.push(body.filename); return {token: 't', adds: {rows: 1, cards: 2}, rows: [], problems: []}; };
          ctx.input.files = [{name: 'old.csv', size: 10, text: () => new Promise(resolve => { first = resolve; })}];
          ctx.input.fire('change'); await flush();
          ctx.input.files = [{name: 'new.csv', size: 10, text: async () => 'new'}]; ctx.input.fire('change'); await flush();
          first('old'); await flush(); same(files, ['new.csv']);
          assert(button(ctx.sheet.dialog, 'Import 2 cards'));
          ctx.input.files = [{name: 'huge.csv', size: COL_IMPORT_MAX + 1}]; ctx.input.fire('change'); await flush();
          assert.equal(ctx.preview, null); assert(!button(ctx.sheet.dialog, 'Import 2 cards'));
        """)

    def test_import_waiting_for_rows_keeps_the_reviewed_file_and_disables_selection(self):
        self.run_js("""
          const {cv, ctx: edit} = await make(); edit.sheet.close(); const ctx = openImportSheet(cv);
          const calls = [];
          apiWrite = async (path, body) => {
            calls.push([path, body]);
            return path.endsWith('/preview') ? {token: 'reviewed-token', adds: {rows: 1, cards: 2}, rows: [], problems: []}
              : {sha256: 's2', added: {rows: 1, cards: 2}};
          };
          await previewImport(ctx, 'reviewed.csv', 'reviewed content');
          cv.rows = null; cv.sha256 = null; let rows;
          api = () => new Promise(resolve => { rows = resolve; });
          route = () => {};
          const pending = applyImport(ctx, false); await flush(); assert.equal(ctx.input.disabled, true);
          ctx.input.files = [{name: 'not-reviewed.csv', size: 1, text: async () => 'unseen content'}];
          ctx.input.fire('change'); await flush();
          rows({sha256: 'latest', rows: [original]}); await pending;
          assert.equal(calls.length, 2); assert.equal(calls[1][1].token, 'reviewed-token');
          assert.equal(calls[0][1].filename, 'reviewed.csv');
        """)

    def test_collection_sheets_close_on_navigation_profile_switch_and_away_lock(self):
        self.run_js("""
          for (const change of ['route', 'profile', 'lock']) {
            const {cv, ctx: edit} = await make();
            const ctx = openImportSheet(cv); ctx.preview = {adds: {rows: 1, cards: 2}, rows: [], problems: [],
              repeat_imports: [{name: 'private-import.csv', imported_at: '2026-10-14', imported_by: 'Matt'}]};
            drawImportPreview(ctx); const pending = askCollectionInUse(warnings, 'edit');
            assert(document.body.textContent.includes('private-import.csv'));
            if (change === 'route') { location.hash = '#/wishlist'; showWishlist = () => {}; route(); }
            if (change === 'profile') { api = async () => ({}); await chooseProfile(PROFILES[2]); }
            if (change === 'lock') drawWho();
            assert.equal(await pending, false); assert.equal(colSheets.size, 0);
            assert(ctx.sheet.closed && edit.sheet.closed); assert(!document.body.textContent.includes('private-import.csv'));
            assert(!document.body.textContent.includes('Built Elves'));
          }
        """)

    def test_remove_conflict_confirmation_belongs_to_the_original_viewer(self):
        self.run_js("""
          const {cv, ctx} = await make(); ctx.sheet.close(); let writes = 0;
          apiWrite = async () => { writes++; throw new ApiError(409, 'Changed', {sha256: 's9', rows: [{...original, quantity: 5}]}); };
          const pending = removeCollectionRow(cv, original); await flush();
          button(openDialog(), 'Remove').click(); await flush();
          assert(openDialog().textContent.includes('changed after you opened it'));
          drawWho(); await pending;
          assert.equal(document.querySelectorAll('dialog').length, 0); assert.equal(colSheets.size, 0);
          assert.equal(writes, 1);
        """)


if __name__ == "__main__":
    unittest.main()
