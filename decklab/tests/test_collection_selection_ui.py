"""Exact-printing selection for the Card list's existing condition/language review."""
import json
import subprocess
import unittest

from decklab.tests.test_collection_bulk_ui import FIXTURE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = FIXTURE + """
  const checks = key => main.querySelectorAll('.col-bulk-check').filter(input => input.getAttribute('data-bulk-key') === key);
  const pick = (key, on = true, index = 0) => { const input = checks(key)[index]; input.checked = on; input.fire('change'); return input; };
  const selectedButton = () => main.querySelector('.col-bulk-selected');
  const selectedCount = () => main.querySelector('.col-bulk-selection-count').textContent;
  const openSelected = () => { selectedButton().click(); const handle = [...colSheets].pop(), sheet = handle.dialog;
    return {handle, sheet, language: sheet.querySelector('select'), blank: sheet.querySelector('input[type="checkbox"]'),
      condition: text => button(sheet, text).click()}; };
  const selectedKeys = sheet => sheet.querySelectorAll('[data-selected-key]').map(node => node.getAttribute('data-selected-key'));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionSelectionUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_native_checks_share_one_set_without_selecting_the_inspector(self):
        self.run_js("""
          const cv = draw(), key = colKey(rows[0]);
          assert.equal(selectedCount(), '0 of 4 shown rows selected.');
          assert(selectedButton().hidden); assert.equal(checks(key).length, 2);
          const native = checks(key)[0]; native.focus(); pick(key);
          assert(checks(key).every(input => input.checked));
          assert.equal(cv.selectedKey, null); assert.equal(document.activeElement, native);
          assert(native.isConnected); assert.equal(native.parentNode.tag, 'label');
          assert.equal(native.closest('button'), null);
          assert(native.getAttribute('aria-label').includes('FDN 227'));
          assert.equal(selectedCount(), '1 of 4 shown rows selected.');
          pick(key, false, 1);
          assert(checks(key).every(input => !input.checked));
          assert(selectedButton().hidden);
        """)

    def test_two_finishes_are_separate_printing_keys_and_rows_not_copies(self):
        self.run_js("""
          const foil = {...rows[0], finish: 'foil', quantity: 9};
          const cv = draw({rows: [...rows, foil]});
          pick(colKey(foil));
          assert(!checks(colKey(rows[0]))[0].checked);
          assert.equal(selectedCount(), '1 of 5 shown rows selected.');
          const s = openSelected();
          same(selectedKeys(s.sheet), ['fdn|227|foil']);
          assert(s.sheet.textContent.includes('9 copies'));
          assert(s.sheet.textContent.includes('For the 1 selected row listed below'));
          assert(s.sheet.textContent.includes('Foil'));
        """)

    def test_whole_filter_review_stays_available_beside_the_subset(self):
        self.run_js("""
          draw(); pick(colKey(rows[0]));
          const all = open();
          assert(all.sheet.textContent.includes('For the 4 rows shown'));
          all.handle.close();
          const selected = openSelected();
          same(selectedKeys(selected.sheet), [colKey(rows[0])]);
          assert(selected.sheet.textContent.includes('Only fill in blanks'));
        """)

    def test_subset_save_sends_only_changing_selected_keys_and_keeps_notes(self):
        self.run_js("""
          const cv = draw(); pick(colKey(rows[0])); pick(colKey(rows[2]));
          const s = openSelected(), calls = [];
          choose(s.language, 'en');
          const after = rows.map(row => row === rows[0] ? {...row, language: 'en'} : row);
          apiWrite = async (path, body) => { calls.push([path, body]); return {ok:true, sha256:'s2', rows:after, changed:1}; };
          button(s.sheet, 'Save 1 row').click(); await flush();
          same(calls, [['/api/collection/bulk', {space:'home', sha256:'s1', language:'en', only_blank:true,
            keys:[{set:'fdn', collector_number:'227', finish:'nonfoil'}]}]]);
          assert.equal(cv.rows[2].notes, rows[2].notes);
          assert.equal(cv.bulkSelected.size, 0); assert(s.handle.closed);
          assert.equal(selectedCount(), '0 of 4 shown rows selected.');
        """)

    def test_subset_overwrite_and_condition_use_the_original_one_change_contract(self):
        self.run_js("""
          draw(); pick(colKey(rows[1])); pick(colKey(rows[2]));
          const s = openSelected(), calls = []; choose(s.language, 'en'); s.condition('NM');
          s.blank.checked = false; s.blank.fire('change');
          apiWrite = async (path, body) => { calls.push(body); return {ok:true, sha256:'s2', rows, changed:2}; };
          button(s.sheet, 'Save 2 rows').click(); await flush();
          assert.equal(calls.length, 1); assert.equal(calls[0].only_blank, false);
          assert.equal(calls[0].condition, 'NM'); assert.equal(calls[0].language, 'en');
          same(calls[0].keys.map(key => key.set).sort(), ['lea','sld']);
          assert(!Object.hasOwn(calls[0], 'rows'));
        """)

    def test_filter_changes_drop_selections_and_clearing_the_filter_never_restores_them(self):
        self.run_js("""
          const cv = draw(); pick(colKey(rows[0])); pick(colKey(rows[1]));
          const search = main.querySelector('#col-row-search'); search.value = 'elves'; search.fire('input');
          same([...cv.bulkSelected], [colKey(rows[0])]);
          assert(selectedCount().includes('1 selection cleared'));
          search.value = ''; search.fire('input');
          same([...cv.bulkSelected], [colKey(rows[0])]);
          assert(!checks(colKey(rows[1]))[0].checked);
          const s = openSelected(); same(selectedKeys(s.sheet), [colKey(rows[0])]);
        """)

    def test_sort_and_page_changes_preserve_exact_keys(self):
        self.run_js("""
          const many = Array.from({length:105}, (_,i) => row('Card '+String(i).padStart(3,'0'), 'fdn', String(i)));
          const cv = draw({rows:many}); pick(colKey(many[0]));
          cv.page = 2; drawColRowList(cv);
          pick(colKey(many[104]));
          cv.sort = {key:'quantity',dir:-1}; drawColRowList(cv);
          same([...cv.bulkSelected].sort(), [colKey(many[0]),colKey(many[104])].sort());
          const s = openSelected();
          same(selectedKeys(s.sheet).sort(), [colKey(many[0]),colKey(many[104])].sort());
          assert.equal(cv.selectedKey, null);
        """)

    def test_clear_selection_keeps_the_whole_filter_action_and_its_focus(self):
        self.run_js("""
          const cv = draw(); pick(colKey(rows[0]));
          main.querySelector('.col-bulk-clear').click();
          assert.equal(cv.bulkSelected.size, 0); assert(checks(colKey(rows[0])).every(input => !input.checked));
          assert.equal(document.activeElement, opener()); assert(!opener().hidden);
          assert(selectedButton().hidden);
        """)

    def test_read_only_views_have_no_subset_checks_or_actions(self):
        self.run_js("""
          draw({editable:false});
          assert.equal(main.querySelector('.col-bulk-check'), null);
          assert.equal(selectedButton(), null); assert.equal(opener(), null);
          assert.equal(main.querySelector('.col-bulk-selection-tools'), null);
        """)

    def test_busy_modal_changed_profile_and_detached_controls_roll_back_native_changes(self):
        self.run_js("""
          const cv = draw(), key = colKey(rows[0]), input = pick(key);
          cv.busy = true; input.checked = false; input.fire('change'); assert(input.checked);
          cv.busy = false;
          const s = openSelected(); input.checked = false; input.fire('change'); assert(input.checked);
          s.handle.close();
          state.profile = {id:'user2'}; input.checked = false; input.fire('change'); assert(input.checked);
          state.profile = {id:cv.profile};
          drawColRowList(cv); input.checked = false; input.fire('change'); assert(input.checked);
          same([...cv.bulkSelected], [key]);
        """)

    def test_stale_revision_or_row_snapshot_controls_cannot_add_a_selection(self):
        self.run_js("""
          const cv = draw(), key = colKey(rows[0]), input = checks(key)[0];
          cv.sha256 = 's9'; input.checked = true; input.fire('change'); assert(!input.checked);
          drawColRowList(cv); const fresh = checks(key)[0];
          cv.rows = cv.rows.map(row => ({...row})); fresh.checked = true; fresh.fire('change');
          assert(!fresh.checked); assert.equal(cv.bulkSelected.size, 0);
        """)

    def test_checkbox_keyboard_events_never_move_or_open_the_inspector(self):
        self.run_js("""
          const cv = draw(), input = checks(colKey(rows[0]))[0]; input.focus();
          const table = main.querySelector('.table-wrap');
          table.fire('keydown', {target:input, key:'j'}); table.fire('keydown', {target:input, key:'Enter'});
          assert.equal(cv.selectedKey, null); assert.equal(colSheets.size, 0);
          assert.equal(document.activeElement, input);
        """)

    def test_conflict_rebases_only_selected_keys_and_never_adds_new_printings(self):
        self.run_js("""
          const cv = draw(); pick(colKey(rows[0])); pick(colKey(rows[2]));
          const s = openSelected(); choose(s.language, 'en'); s.blank.checked = false; s.blank.fire('change');
          const latest = [...rows.slice(1), {...rows[0], set:'rtr', collector_number:'9'}];
          apiWrite = async () => { throw new ApiError(409, 'Changed', {sha256:'s9', rows:latest}); };
          button(s.sheet, 'Save 2 rows').click(); await flush();
          same(selectedKeys(s.sheet), [colKey(rows[2])]);
          assert(s.sheet.textContent.includes('1 selected row no longer shown was left out'));
          assert(s.sheet.textContent.includes('Nothing was saved'));
          const calls = []; apiWrite = async (path,body) => {calls.push(body);return {ok:true,sha256:'s10',rows:latest,changed:1};};
          button(s.sheet, 'Save 1 row').click(); await flush();
          assert.equal(calls[0].sha256, 's9');
          same(calls[0].keys, [{set:'lea',collector_number:'232',finish:'nonfoil'}]);
        """)

    def test_a_conflict_that_removes_every_selected_row_has_only_close(self):
        self.run_js("""
          draw(); pick(colKey(rows[0])); const s = openSelected(); choose(s.language, 'en');
          apiWrite = async () => { throw new ApiError(409, 'Changed', {sha256:'s9',rows:rows.slice(1)}); };
          button(s.sheet, 'Save 1 row').click(); await flush();
          assert(s.sheet.textContent.includes('None of the selected rows are still shown'));
          assert.equal(selectedKeys(s.sheet).length, 0);
          assert(button(s.sheet, 'Close'));
          assert.equal(s.sheet.querySelectorAll('button').filter(node => node.textContent.startsWith('Save')).length, 0);
        """)

    def test_a_revision_change_requires_review_before_any_request(self):
        self.run_js("""
          const cv = draw(); pick(colKey(rows[0])); const s = openSelected(); choose(s.language, 'en');
          cv.sha256 = 's9'; cv.rows = [...rows, row('Opt','dmu','60')];
          const calls = []; apiWrite = async (path,body) => {calls.push(body);return {ok:true,sha256:'s10',rows:cv.rows,changed:1};};
          button(s.sheet, 'Save 1 row').click(); await flush();
          assert.equal(calls.length, 0); assert(s.sheet.textContent.includes('Nothing was saved'));
          same(selectedKeys(s.sheet), [colKey(rows[0])]);
          button(s.sheet, 'Save 1 row').click(); await flush();
          assert.equal(calls[0].sha256, 's9'); assert.equal(calls[0].keys.length, 1);
        """)

    def test_filter_narrowing_then_broadening_behind_review_does_not_restore_removed_keys(self):
        self.run_js("""
          const cv = draw(); pick(colKey(rows[0])); pick(colKey(rows[1])); const s = openSelected(); choose(s.language,'en');
          cv.search = 'elves'; drawColRowList(cv); cv.search = ''; drawColRowList(cv);
          const calls = []; apiWrite = async (path,body) => {calls.push(body);return {ok:true,sha256:'s2',rows,changed:1};};
          button(s.sheet,'Save 2 rows').click(); await flush();
          assert.equal(calls.length, 0); same(selectedKeys(s.sheet), [colKey(rows[0])]);
          button(s.sheet,'Save 1 row').click(); await flush();
          same(calls[0].keys, [{set:'fdn',collector_number:'227',finish:'nonfoil'}]);
        """)

    def test_success_moves_focus_from_hidden_subset_opener_to_whole_filter_action(self):
        self.run_js("""
          draw(); pick(colKey(rows[0])); selectedButton().focus();
          const s = openSelected(); choose(s.language, 'en');
          apiWrite = async () => ({ok:true,sha256:'s2',rows,changed:1});
          button(s.sheet,'Save 1 row').click(); await flush();
          assert(selectedButton().hidden); assert(!opener().hidden);
          assert.equal(document.activeElement, opener());
        """)

    def test_a_closed_pending_review_blocks_native_changes_until_success(self):
        self.run_js("""
          const cv = draw(), a = colKey(rows[0]), b = colKey(rows[1]); pick(a);
          const s = openSelected(); choose(s.language,'en'); let finish;
          apiWrite = () => new Promise(resolve => {finish=resolve;});
          button(s.sheet,'Save 1 row').click(); s.handle.close();
          assert(cv.busy); assert(checks(a)[0].disabled);
          const before = [...cv.bulkSelected]; pick(a,false); pick(b);
          same([...cv.bulkSelected],before); assert(checks(a)[0].checked); assert(!checks(b)[0].checked);
          finish({ok:true,sha256:'s2',rows,changed:1}); await flush();
          assert(!cv.busy); assert.equal(cv.bulkSelected.size,0);
          pick(b); assert(cv.bulkSelected.has(b));
        """)

    def test_a_closed_failed_review_releases_pending_controls_without_a_late_message(self):
        self.run_js("""
          const cv = draw(), a = colKey(rows[0]); pick(a);
          const s = openSelected(); choose(s.language,'en'); let fail;
          apiWrite = () => new Promise((resolve,reject) => {fail=reject;});
          button(s.sheet,'Save 1 row').click(); s.handle.close();
          fail(new Error('offline')); await flush();
          assert(!cv.busy); assert(!checks(a)[0].disabled);
          assert.equal(colSheets.size,0); assert(!main.textContent.includes('offline'));
          pick(a,false); assert.equal(cv.bulkSelected.size,0);
        """)

    def test_current_inventory_and_edit_permissions_gate_the_new_controls_and_save(self):
        self.run_js("""
          const cv = draw(), key = colKey(rows[0]); pick(key);
          const s = openSelected(); choose(s.language,'en'); const calls=[];
          apiWrite = async (path,body) => {calls.push(body);return {};};
          state.may = {...MAY.admin,see_inventory:[]};
          button(s.sheet,'Save 1 row').click(); await flush(); assert.equal(calls.length,0);
          s.handle.close();
          const input=checks(key)[0]; input.checked=false; input.fire('change'); assert(input.checked);
          clear(main); const hidden=drawCollectionRows({space:'home',sha256:'s1',rows,editable:true},'home');
          assert.equal(main.querySelector('.col-bulk-check'),null); assert.equal(selectedButton(),null);
          assert.equal(main.querySelector('.col-row-name-choice'),null);
          assert.equal(main.querySelector('.has-bulk-choice'),null);
          state.may={...MAY.admin,spaces:[]}; clear(main);
          drawCollectionRows({space:'home',sha256:'s1',rows,editable:true},'home');
          assert.equal(main.querySelector('.col-bulk-check'),null); assert.equal(selectedButton(),null);
        """)

    def test_a_late_closed_review_preserves_newer_connected_focus(self):
        self.run_js("""
          const cv=draw(); pick(colKey(rows[0])); selectedButton().focus();
          const s=openSelected(); choose(s.language,'en'); let finish;
          apiWrite=()=>new Promise(resolve=>{finish=resolve;});
          button(s.sheet,'Save 1 row').click(); s.handle.close();
          cv.search='nothing matches'; drawColRowList(cv);
          cv.storageBox.focus(); const newer=document.activeElement;
          finish({ok:true,sha256:'s2',rows,changed:1}); await flush();
          assert.equal(document.activeElement,newer);
          assert(!cv.busy);
        """)

    def test_late_success_does_not_steal_focus_from_another_sheet(self):
        self.run_js("""
          const cv=draw(); pick(colKey(rows[0])); selectedButton().focus();
          const s=openSelected(); choose(s.language,'en'); let finish;
          apiWrite=()=>new Promise(resolve=>{finish=resolve;});
          button(s.sheet,'Save 1 row').click(); s.handle.close();
          const next=colOpenSheet('Another task'); const field=el('input'); next.body.append(field); field.focus();
          finish({ok:true,sha256:'s2',rows,changed:1}); await flush();
          assert.equal(document.activeElement,field); assert(!next.closed); assert(!cv.busy);
        """)

    def test_late_failure_after_profile_change_releases_only_the_old_view(self):
        self.run_js("""
          const cv=draw(); pick(colKey(rows[0])); const s=openSelected(); choose(s.language,'en'); let fail;
          apiWrite=()=>new Promise((resolve,reject)=>{fail=reject;});
          button(s.sheet,'Save 1 row').click(); s.handle.close();
          state.profile={id:'user2'}; const field=el('input'); document.body.append(field); field.focus();
          fail(new Error('private old failure')); await flush();
          assert(!cv.busy); assert.equal(document.activeElement,field);
          assert(!main.textContent.includes('private old failure')); assert.equal(colSheets.size,0);
        """)

    def test_bounded_selected_rows_remain_keyboard_focusable_and_named(self):
        self.run_js("""
          draw(); pick(colKey(rows[0])); const s=openSelected();
          const list=s.sheet.querySelector('.col-bulk-selected-list');
          assert.equal(list.tag,'ul'); assert.equal(list.getAttribute('tabindex'),'0');
          assert.equal(list.getAttribute('aria-label'),'Selected printing rows');
          list.focus(); assert.equal(document.activeElement,list);
        """)

    def test_revoked_permissions_remove_checks_and_clear_old_selection_on_redraw(self):
        self.run_js("""
          const cv=draw(); pick(colKey(rows[0]));
          state.may={...MAY.admin,spaces:[]}; drawColRowList(cv);
          assert.equal(cv.bulkSelected.size,0); assert(selectedButton().hidden);
          assert(main.querySelector('.col-bulk-selection-count').hidden);
          assert.equal(main.querySelector('.col-bulk-check'),null);
          assert.equal(main.querySelector('.col-row-name-choice'),null);
          assert.equal(main.querySelector('.has-bulk-choice'),null);
        """)
