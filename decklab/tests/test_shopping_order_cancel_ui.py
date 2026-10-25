"""Cancel order components and remove mistaken orders through reviewed synthetic UI changes.

Loads real index-order scripts with stubbed API responses; no orders or database are changed.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = r"""
  clear(main); editor = null;
  // A native checkbox reflects its checked attribute until the user changes the property.
  Object.defineProperty(Node.prototype, 'checked', {configurable: true,
    get() {return this._checked === undefined ? this.getAttribute('checked') !== null : this._checked;},
    set(value) {this._checked = Boolean(value);}});
  const matt = {id: 'matt', name: 'Matt', role: 'admin', space: 'home'};
  state.profiles = [matt]; state.profile = matt;
  state.may = {admin: true, orders: true, see_inventory: ['home']};
  location.hash = '#/shopping';
  const component = (extra = {}) => ({id: 'cards', kind: 'cards', status: 'pending', quantity: 3, rows: 2,
    checks: ['Confirm the printing'], ...extra});
  const order = (extra = {}) => ({id: '2026-10-08-order', seller: 'Card shop', ordered_on: '2026-10-08',
    status: 'pending', notes: 'Keep this delivery note', sources: ['magic/buylists/old.md'],
    components: [component()], ...extra});
  const pending = order({components: [component(), component({id: 'tokens', kind: 'tokens'}),
    component({id: 'precon', kind: 'product', title: 'Test Precon'})]});
  const empty = {to_buy: [], orders: [], checks: [], warnings: []};
  const data = {...empty, queue_revision: 'revision-1', orders: [pending]};
  const queueRow = {name: 'Opt', set: 'dom', collector_number: '60', finish: 'nonfoil', quantity: '2',
    for: 'Otters', printing: 'exact', listed_aud: '', listed_at: '', in_stock: '', checked: '',
    notes: 'Recorded queue note', state: 'waiting_for_stock', source: 'magic/buylists/old.md'};
  const previewAnswer = {preview: 'signed-cancel', revision: 'revision-1', order: pending.id, action: 'cancel',
    component: {id: 'cards', kind: 'cards', status: 'cancelled'},
    summary: 'Cancel cards', changes: ['Mark cards cancelled'], record: {seller: pending.seller,
      ordered_on: pending.ordered_on, notes: pending.notes, sources: pending.sources}, checks: [],
    queue_restoration: {known: true, offered: [queueRow], restored: [queueRow], warnings: []},
    tables: {written: [{id: 'casual/otters', title: 'Otters'}], skipped: [], error: null}, warnings: []};
  const requests = [], messages = [], sheets = [];
  let refreshes = 0;
  route = () => {refreshes++;}; toast = words => messages.push(words);
  const realSheet = openSheet;
  openSheet = (...args) => {const sheet = realSheet(...args); sheets.push(sheet); return sheet;};
  const latest = () => sheets.at(-1);
  const settle = async () => {for (let n = 0; n < 12; n++) await Promise.resolve();};
  const held = () => {let resolve, reject; const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
    return {promise, resolve, reject};};
  let respond = async path => path.endsWith('/preview') ? previewAnswer : {...previewAnswer, saved: true};
  api = async (path, options = {}) => {const body = options.body ? JSON.parse(options.body) : null;
    requests.push([path, body]); return respond(path, body);};
  const field = (sheet, key) => {const found = sheet.body.querySelector(`[data-order-change-field=${key}]`);
    assert(found, `Order field ${key}`); return found;};
  const type = (sheet, key, value) => {const input = field(sheet, key); input.value = value; input.fire('input');};
  const button = (node, text) => {const found = node.querySelectorAll('button').find(item => item.textContent.replace(/\u2026$/, '.') === text);
    assert(found, `Button ${text}`); return found;};
  const action = (sheet, text) => button(sheet.foot, text);
  const openEdit = (other = data) => {clear(main); drawShopping(other); const edit = main.querySelector('.shop-order-edit');
    assert(edit, 'Order edit control'); edit.click(); return latest();};
  const openCancel = (id = 'cards', other = data) => {const edit = openEdit(other);
    const part = edit.body.querySelector(`[data-order-check-component=${id}]`);
    assert(part, `Component ${id}`); button(part, 'Cancel part.').click(); return latest();};
  const openRemove = (other = data) => {const edit = openEdit(other); button(edit.body, 'Remove order.').click(); return latest();};
  const applyRequests = () => requests.filter(([path]) => path.endsWith('/apply'));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingOrderCancelInteractionTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_actions_require_admin_home_inventory_revision_and_pending_components(self):
        self.run_js(r"""
          for (const may of [{admin: false, orders: false, see_inventory: ['home']},
              {admin: true, orders: true, see_inventory: ['user2']}]) {
            state.may = may; clear(main); drawShopping(data); assert.equal(main.querySelector('.shop-order-edit'), null);
          }
          state.may = {admin: true, orders: true, see_inventory: ['home']};
          clear(main); drawShopping({...data, queue_revision: null}); assert.equal(main.querySelector('.shop-order-edit'), null);
          const mixed = order({status: 'partial', components: [component(), component({id: 'received', status: 'received'}),
            component({id: 'cancelled', status: 'cancelled'}), component({id: 'tokens', kind: 'tokens'}),
            component({id: 'precon', kind: 'product'})]});
          const edit = openEdit({...data, orders: [mixed]});
          assert.equal(edit.body.querySelectorAll('button').filter(item => /^Cancel part /.test(item.getAttribute('aria-label') || '')).length, 3);
          const remove = button(edit.body, 'Remove order.'); assert(remove.disabled);
          assert(edit.body.textContent.toLowerCase().includes('received'));
          const count = sheets.length; remove.click(); assert.equal(sheets.length, count); assert.equal(requests.length, 0);
        """)

    def test_each_pending_kind_requires_reason_and_sends_explicit_queue_choice(self):
        self.run_js(r"""
          for (const id of ['cards', 'tokens', 'precon']) {
            const sheet = openCancel(id); assert.equal(field(sheet, 'restore_queue').checked, true);
            assert.equal(field(sheet, 'reason').tag, 'input');
            assert.equal(field(sheet, 'reason').getAttribute('type'), 'text');
            type(sheet, 'reason', '   '); action(sheet, 'Preview change').click(); await settle();
            assert.equal(requests.length, 0); assert(sheet.body.textContent.toLowerCase().includes('reason'));
            type(sheet, 'reason', 'Seller cancelled this part');
            field(sheet, 'restore_queue').checked = false; field(sheet, 'restore_queue').fire('change');
            action(sheet, 'Preview change').click(); await settle();
            same(requests.at(-1), ['/api/shopping/order/change/preview', {profile: 'matt', expect: 'revision-1',
              order: pending.id, action: 'cancel', component: id, reason: 'Seller cancelled this part', restore_queue: false}]);
            assert.equal(applyRequests().length, 0); shopCloseQueueSheets(); requests.length = 0;
          }
        """)

    def test_remove_requires_reason_restores_without_opt_out_and_applies_only_token(self):
        self.run_js(r"""
          respond = async path => ({...previewAnswer, component: undefined, action: 'remove', removed: true,
            summary: 'Remove mistaken order', saved: !path.endsWith('/preview'), warnings: ['Keep this saved warning'],
            tables: {...previewAnswer.tables, error: 'One deck table needs review'}});
          const sheet = openRemove();
          assert.equal(sheet.body.querySelector('[data-order-change-field=restore_queue]'), null);
          action(sheet, 'Preview change').click(); await settle(); assert.equal(requests.length, 0);
          type(sheet, 'reason', 'Accidental duplicate order'); action(sheet, 'Preview change').click(); await settle();
          same(requests[0][1], {profile: 'matt', expect: 'revision-1', order: pending.id, action: 'remove',
            reason: 'Accidental duplicate order'});
          action(sheet, 'Remove order').click(); action(sheet, 'Remove order').click(); await settle();
          same(applyRequests()[0], ['/api/shopping/order/change/apply', {profile: 'matt', preview: 'signed-cancel'}]);
          assert.equal(applyRequests().length, 1); assert(!sheet.closed); assert.equal(refreshes, 0);
          assert(sheet.body.textContent.includes('Opt')); assert(sheet.body.textContent.includes('Keep this saved warning'));
          assert(sheet.body.querySelectorAll('a').some(link => link.textContent === 'Tables out of date'));
          action(sheet, 'Done').click(); await settle(); flushTimers(); await settle();
          assert(sheet.closed); assert.equal(refreshes, 1);
        """)

    def test_cancel_preview_shows_exact_restored_rows_warnings_and_table_effects(self):
        self.run_js(r"""
          respond = async () => ({...previewAnswer, queue_restoration: {...previewAnswer.queue_restoration,
            warnings: ['Review this recorded queue restoration']}, warnings: ['Check delivery status first']});
          const sheet = openCancel(); type(sheet, 'reason', 'Shop cannot supply it');
          action(sheet, 'Preview change').click(); await settle();
          const preview = sheet.body.querySelector('.shop-order-preview').textContent;
          for (const text of ['2 x Opt for Otters', 'Exact: DOM 60', 'Waiting for stock', 'Part cards: cancelled',
                              'Review this recorded queue restoration', 'Check delivery status first'])
            assert(preview.includes(text), text);
          assert(sheet.body.querySelectorAll('a').some(link => link.getAttribute('href') === deckHref('casual/otters')));
          assert.equal(applyRequests().length, 0); assert(action(sheet, 'Cancel part'));
        """)

    def test_unknown_history_warns_without_guessing_queue_rows(self):
        self.run_js(r"""
          respond = async () => ({...previewAnswer, queue_restoration: {known: false, offered: [], restored: [],
            warnings: ['Restoration history is unavailable. Review the queue manually.']}});
          const sheet = openCancel(); type(sheet, 'reason', 'Old order cancelled');
          action(sheet, 'Preview change').click(); await settle();
          const preview = sheet.body.querySelector('.shop-order-preview').textContent;
          assert(preview.includes('Review the queue manually')); assert(!preview.includes('Opt'));
          assert.equal(applyRequests().length, 0);
        """)

    def test_opt_out_keeps_offered_rows_distinct_from_restored_rows(self):
        self.run_js(r"""
          respond = async () => ({...previewAnswer, queue_restoration: {...previewAnswer.queue_restoration, restored: []}});
          const sheet = openCancel(); type(sheet, 'reason', 'No longer wanted');
          field(sheet, 'restore_queue').checked = false; field(sheet, 'restore_queue').fire('change');
          action(sheet, 'Preview change').click(); await settle();
          assert.equal(requests[0][1].restore_queue, false);
          const preview = sheet.body.querySelector('.shop-order-preview').textContent;
          assert(preview.includes('Opt')); assert(preview.includes('No queue quantities will be returned with this choice'));
          assert.equal(applyRequests().length, 0);
        """)

    def test_reason_and_queue_choice_changes_invalidate_cancel_preview(self):
        self.run_js(r"""
          const sheet = openCancel(); type(sheet, 'reason', 'First reason');
          action(sheet, 'Preview change').click(); await settle();
          action(sheet, 'Back to edit').click();
          assert.equal(sheet.foot.querySelectorAll('button').some(item => item.textContent === 'Cancel part'), false);
          type(sheet, 'reason', 'New reason'); action(sheet, 'Preview change').click(); await settle();
          field(sheet, 'restore_queue').checked = false;
          action(sheet, 'Cancel part').click(); await settle();
          assert.equal(applyRequests().length, 0); assert(sheet.body.textContent.includes('Preview it again'));
          assert.equal(field(sheet, 'reason').value, 'New reason');
        """)

    def test_eventless_remove_reason_edit_cannot_reuse_a_preview(self):
        self.run_js(r"""
          const sheet = openRemove(); type(sheet, 'reason', 'Mistaken order');
          action(sheet, 'Preview change').click(); await settle();
          field(sheet, 'reason').value = 'Changed without input event';
          action(sheet, 'Remove order').click(); await settle();
          assert.equal(applyRequests().length, 0); assert(sheet.body.textContent.includes('Preview it again'));
          assert.equal(field(sheet, 'reason').value, 'Changed without input event');
        """)

    def test_preview_and_cancel_apply_are_single_flight_and_done_refreshes_once(self):
        self.run_js(r"""
          const preview = held(); respond = () => preview.promise;
          const sheet = openCancel(); type(sheet, 'reason', 'Unavailable');
          action(sheet, 'Preview change').click(); action(sheet, 'Preview change').click();
          assert.equal(requests.length, 1); assert(main.querySelector('.shop-order-edit').disabled);
          preview.resolve(previewAnswer); await settle();
          const applied = held(); respond = () => applied.promise;
          action(sheet, 'Cancel part').click(); action(sheet, 'Cancel part').click();
          assert.equal(applyRequests().length, 1);
          applied.resolve({...previewAnswer, saved: true}); await settle();
          assert(!sheet.closed); assert.equal(refreshes, 0); assert(sheet.body.textContent.includes('Opt'));
          const done = action(sheet, 'Done'); done.click(); done.click(); await settle(); flushTimers(); await settle();
          assert.equal(refreshes, 1); assert(sheet.closed);
        """)

    def test_preview_failure_preserves_reason_and_restore_choice(self):
        self.run_js(r"""
          respond = async () => {throw new ApiError(503, 'Database unavailable');};
          const sheet = openCancel(); type(sheet, 'reason', 'Keep this reason');
          field(sheet, 'restore_queue').checked = false; field(sheet, 'restore_queue').fire('change');
          action(sheet, 'Preview change').click(); await settle();
          assert.equal(field(sheet, 'reason').value, 'Keep this reason');
          assert.equal(field(sheet, 'restore_queue').checked, false);
          assert(sheet.body.textContent.includes("couldn't be previewed"));
          assert(!action(sheet, 'Preview change').disabled); assert.equal(applyRequests().length, 0);
        """)

    def test_apply_failure_retains_the_draft_and_requires_a_new_preview(self):
        self.run_js(r"""
          respond = async path => {if (path.endsWith('/preview')) return previewAnswer;
            throw new ApiError(503, 'Database unavailable');};
          const sheet = openCancel(); type(sheet, 'reason', 'Keep my cancellation');
          action(sheet, 'Preview change').click(); await settle(); action(sheet, 'Cancel part').click(); await settle();
          assert(!sheet.closed); assert.equal(field(sheet, 'reason').value, 'Keep my cancellation');
          assert.equal(field(sheet, 'restore_queue').checked, true);
          assert(sheet.body.textContent.includes("couldn't be saved")); assert(action(sheet, 'Preview change'));
          assert.equal(sheet.foot.querySelectorAll('button').some(item => item.textContent === 'Cancel part'), false);
          assert(!main.querySelector('.shop-order-edit').disabled); assert.equal(refreshes, 0);
        """)

    def test_conflict_keeps_draft_and_blocks_other_order_writes_until_refresh(self):
        self.run_js(r"""
          respond = async path => {if (path.endsWith('/preview')) return previewAnswer;
            throw new ApiError(409, 'Inventory changed');};
          const sheet = openRemove(); type(sheet, 'reason', 'Duplicate entry');
          action(sheet, 'Preview change').click(); await settle(); action(sheet, 'Remove order').click(); await settle();
          assert.equal(field(sheet, 'reason').value, 'Duplicate entry'); assert(action(sheet, 'Preview change').disabled);
          assert(main.querySelector('.shop-order-edit').disabled); assert(button(sheet.body, 'Refresh Shopping'));
          assert.equal(applyRequests().length, 1); assert.equal(refreshes, 0);
        """)

    def test_late_preview_cannot_enable_cancel_after_profile_route_or_close(self):
        self.run_js(r"""
          for (const leave of [sheet => {state.profile = {id: 'user1', role: 'member', space: 'home'};},
              sheet => {routeToken++;}, sheet => sheet.close()]) {
            state.profile = matt; shopCloseQueueSheets();
            const answer = held(); respond = () => answer.promise;
            const sheet = openCancel(); type(sheet, 'reason', 'Unavailable'); action(sheet, 'Preview change').click();
            leave(sheet); answer.resolve(previewAnswer); await settle();
            assert.equal(sheet.foot.querySelectorAll('button').some(item => item.textContent === 'Cancel part'), false);
            assert.equal(applyRequests().length, 0);
          }
        """)

    def test_late_apply_does_not_show_results_toast_or_refresh_another_view(self):
        self.run_js(r"""
          const answer = held(); respond = async path => path.endsWith('/preview') ? previewAnswer : answer.promise;
          const sheet = openCancel(); type(sheet, 'reason', 'Unavailable'); action(sheet, 'Preview change').click(); await settle();
          state.library = {decks: ['old availability']};
          action(sheet, 'Cancel part').click(); state.profile = {id: 'user1', role: 'member', space: 'home'}; routeToken++;
          answer.resolve({...previewAnswer, saved: true}); await settle();
          assert.equal(state.library, null);
          assert.equal(sheet.foot.querySelectorAll('button').some(item => item.textContent === 'Done'), false);
          assert.equal(messages.length, 0); assert.equal(refreshes, 0);
        """)

    def test_closing_a_confirmed_apply_refreshes_the_same_view_after_success(self):
        self.run_js(r"""
          const answer = held(); respond = async path => path.endsWith('/preview') ? previewAnswer : answer.promise;
          const sheet = openRemove(); type(sheet, 'reason', 'Accidental duplicate');
          action(sheet, 'Preview change').click(); await settle();
          state.library = {decks: ['old availability']};
          action(sheet, 'Remove order').click(); sheet.close();
          assert.equal(refreshes, 0); assert.equal(applyRequests().length, 1);
          answer.resolve({...previewAnswer, action: 'remove', removed: true, saved: true}); await settle();
          assert.equal(state.library, null); assert(sheets.every(item => item.closed));
          assert.equal(refreshes, 1); assert.equal(messages.length, 0);
          flushTimers(); await settle(); assert.equal(refreshes, 1);
        """)

    def test_cancel_and_remove_cannot_discard_dirty_record_edits(self):
        self.run_js(r"""
          const edit = openEdit(); type(edit, 'notes', 'Unsaved delivery correction');
          for (const label of ['Cancel part.', 'Remove order.']) {
            button(edit.body, label).click(); assert.equal(sheets.length, 1);
            assert.equal(field(edit, 'notes').value, 'Unsaved delivery correction');
            assert(edit.body.textContent.includes('Save or undo'));
          }
          assert.equal(requests.length, 0);
          type(edit, 'notes', pending.notes); button(edit.body, 'Cancel part.').click();
          assert.equal(sheets.length, 2); assert(field(latest(), 'reason'));
        """)


if __name__ == "__main__":
    unittest.main()
