"""Explicit reference/market-target reviews keep their original person, row and page."""
import unittest

from decklab.tests import test_shopping_ui as fixture
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShopReferenceUiTests(unittest.TestCase):
    run_js = fixture.ShoppingInteractionTests.run_js

    def review_js(self, scenario):
        self.run_js("""
          state.profile = state.profiles[1];
          state.may = {admin: true, orders: true, see_inventory: ['home']};
          const card = row('Alpha', {queue_row: 1, quantity: 3, notes: 'Keep the note', listed_aud: '0.50',
            listed_at: 'Old shop', in_stock: 'no', checked: '2026-11-01'});
          const snap = {shop: 'MTGMate', shop_key: 'mtgmate', status: 'in_stock', price_aud: '3.00', stock: 3,
            set: 'fdn', collector_number: '227', finish: 'nonfoil', condition: 'Near Mint', language: 'English',
            fetched_at: '2026-11-11T12:00:00Z', reference_receipt: 'a'.repeat(64)};
          card.shop_snapshots = [snap];
          const root = el('div'); main.append(root);
          let redraws = 0;
          const view = {root, token: routeToken, profile: state.profile.id, busy: false, stale: false,
            data: {...empty, queue_revision: 'q1', to_buy: [card]}, expanded: new Set(['long_term']),
            shop: 'mtgmate', queueOrder: 'name', redraw: () => {redraws += 1;}};
          const button = (ctx, text) => ctx.sheet.foot.querySelectorAll('button').find(item => item.textContent === text);
          const tick = async () => {for (let n = 0; n < 8; n++) await null;};
          const change = {row: 1, name: 'Alpha', old: {listed_aud: '0.50', listed_at: 'Old shop', in_stock: 'no', checked: '2026-11-01'},
            new: {listed_aud: '3.00', listed_at: 'MTGMate', in_stock: 'yes', checked: '2026-11-11'}};
        """ + scenario)

    def test_four_field_review_requires_confirmation_then_refreshes_without_losing_view_state(self):
        self.review_js("""
          const writes = [], reads = [], messages = [], queue = view.data.to_buy;
          toast = words => messages.push(words);
          apiWrite = async (path, body) => {writes.push([path, body]);
            return body.action.endsWith('_preview') ? {preview: 'p1', changed: 1, changes: [change]}
              : {saved: true, revision: 'q2', changes: [change]};};
          api = async path => {reads.push(path); return {...empty, queue_revision: 'q2', to_buy: [{...card, ...change.new}]};};
          const ctx = shopPriceReview(view, 'reference', [{card, snap}]);
          same(writes, []); assert.equal(ctx.selections[0].box.checked, true);
          button(ctx, 'Preview').click(); await tick();
          same(writes, [['/api/shopping/queue', {action: 'reference_preview', expect: 'q1',
            requests: [{row: 1, shop: 'mtgmate', receipt: 'a'.repeat(64)}]}]]);
          for (const text of ['Old shop', 'MTGMate', '0.50', '3.00', '2026-11-01', '2026-11-11']) assert(ctx.review.textContent.includes(text));
          assert.equal(card.listed_aud, '0.50'); same(reads, []);
          button(ctx, 'Save references').click(); await tick();
          same(writes[1], ['/api/shopping/queue', {action: 'reference_apply', preview: 'p1'}]);
          same(reads, ['/api/shopping']); assert.equal(redraws, 1); assert.equal(ctx.sheet.closed, true);
          assert.equal(view.data.to_buy, queue); assert.equal(view.data.queue_revision, 'q2');
          assert.equal(view.data.to_buy[0].notes, 'Keep the note'); assert.equal(view.data.to_buy[0].quantity, 3);
          assert(view.expanded.has('long_term')); assert.equal(view.shop, 'mtgmate'); assert.equal(view.queueOrder, 'name');
          same(messages, ['Reference observations saved.']);
        """)

    def test_bulk_starts_unchecked_and_only_selected_ready_rows_are_reviewed(self):
        self.review_js("""
          const second = row('Beta', {queue_row: 2, shop_snapshots: [snap]}), later = row('Later', {queue_row: 3, state: 'long_term', shop_snapshots: [snap]});
          view.data.to_buy.push(second, later);
          const basket = {key: 'mtgmate', shop: 'MTGMate', read: true, rows: [{queue_row: 1}, {queue_row: 2}], addons: [{queue_row: 3}]};
          view.data.baskets = {queue_revision: 'q1', shops: [basket]};
          const writes = []; apiWrite = async (path, body) => {writes.push(body); return {preview: null, changed: 0, changes: []};};
          const open = shopReferenceBulkButton(view, basket); root.append(open); open.click();
          const sheet = [...shopQueueSheets].at(-1), boxes = sheet.body.querySelectorAll('input');
          assert.equal(boxes.length, 2); assert(boxes.every(box => !box.checked)); assert(!sheet.body.textContent.includes('Later'));
          sheet.foot.querySelectorAll('button').find(item => item.textContent === 'Preview').click(); await tick();
          same(writes, []); boxes[1].checked = true;
          sheet.foot.querySelectorAll('button').find(item => item.textContent === 'Preview').click(); await tick();
          same(writes[0].requests, [{row: 2, shop: 'mtgmate', receipt: 'a'.repeat(64)}]);
          assert.equal(sheet.foot.querySelectorAll('button').find(item => item.textContent === 'Save references').disabled, true);
        """)

    def test_target_is_optional_explicit_aud_and_has_a_separate_preview_and_apply(self):
        self.review_js("""
          const writes = [];
          apiWrite = async (path, body) => {writes.push(body); return {preview: 'target1', changed: 1,
            changes: [{row: 1, name: 'Alpha', old: {buy_under_aud: ''}, new: {buy_under_aud: '2.50'}}]};};
          const ctx = shopPriceReview(view, 'target', [{card}]);
          assert.equal(ctx.target.value, ''); assert(ctx.sheet.body.textContent.includes('AUD market price per copy'));
          ctx.target.value = ' 2.50 '; button(ctx, 'Preview').click(); await tick();
          same(writes, [{action: 'target_preview', expect: 'q1', requests: [{row: 1, value: '2.50'}]}]);
          assert(ctx.review.textContent.includes('Market target')); assert.equal(card.buy_under_aud, undefined);
          button(ctx, 'Back').click(); assert.equal(ctx.target.value, ' 2.50 ');
          ctx.target.value = ''; button(ctx, 'Preview').click(); await tick();
          same(writes[1].requests, [{row: 1, value: null}]);
          assert(shopMarketTargetLabel({...card, buy_under_aud: '2.50'}).textContent.includes('AUD market target: A$2.50 each'));
        """)

    def test_conflict_or_unknown_save_removes_retry_and_never_refreshes_automatically(self):
        self.review_js("""
          let reads = 0; api = async () => {reads += 1;};
          for (const status of [409, 500]) {
            view.stale = false; const writes = [];
            apiWrite = async (path, body) => {writes.push(body); if (body.action.endsWith('_apply')) throw new ApiError(status, 'Changed');
              return {preview: 'p1', changed: 1, changes: [change]};};
            const ctx = shopPriceReview(view, 'reference', [{card, snap}]);
            button(ctx, 'Preview').click(); await tick(); const oldSave = button(ctx, 'Save references');
            oldSave.click(); await tick(); oldSave.click(); await tick();
            assert.equal(writes.length, 2); assert.equal(button(ctx, 'Save references'), undefined);
            assert.equal(view.stale, status === 409); assert.equal(ctx.unknown, status === 500);
            assert(ctx.message.textContent.includes(status === 500 ? "couldn't be confirmed" : 'Nothing saved'));
            assert.equal(card.listed_aud, '0.50'); ctx.sheet.close();
          }
          assert.equal(reads, 0);
        """)

    def test_wrong_person_stale_queue_detached_or_nested_controls_cannot_write(self):
        self.review_js("""
          const writes = []; apiWrite = async (path, body) => {writes.push(body); return {preview: 'p1', changed: 1, changes: [change]};};
          const ctx = shopPriceReview(view, 'reference', [{card, snap}]), preview = button(ctx, 'Preview');
          const nested = openSheet({title: 'Another sheet'}); preview.click(); await tick(); same(writes, []); nested.close();
          state.profile = state.profiles[0]; preview.click(); await tick(); same(writes, []); state.profile = state.profiles[1];
          view.data.queue_revision = 'newer'; preview.click(); await tick(); same(writes, []); view.data.queue_revision = 'q1';
          preview.remove(); preview.click(); await tick(); same(writes, []);
          ctx.sheet.close(); view.stale = true;
          assert.equal(shopMarketTargetButton(card, view), null); assert.equal(shopReferenceButton(card, snap, view), null);
          view.stale = false;
          assert.equal(shopReferenceButton(card, {...snap, carried: true}, view), null);
          assert.equal(shopReferenceButton(card, {...snap, reference_receipt: null}, view), null);
          state.may = {...state.may, admin: false}; assert.equal(shopMarketTargetButton(card, view), null);
        """)

    def test_late_success_stays_with_original_page_and_low_and_target_markers_are_read_only(self):
        self.review_js("""
          let finish; const writes = []; apiWrite = (path, body) => {writes.push(body); return new Promise(resolve => {finish = resolve;});};
          const ctx = shopPriceReview(view, 'reference', [{card, snap}]); button(ctx, 'Preview').click();
          routeToken += 1; root.remove(); finish({preview: 'p1', changed: 1, changes: [change]}); await tick();
          assert.equal(ctx.preview, null); assert.equal(card.listed_aud, '0.50'); assert.equal(redraws, 0);
          const marked = {...snap, lowest_kept: {days: 90, readings: 3}, target_comparison: {at_or_below: true, amount_aud: '3.00'}};
          const line = shopSnapshotOne(marked, card);
          assert(line.textContent.includes('90 days')); assert(line.textContent.includes('A$3.00 target')); assert(!line.textContent.includes('NaN'));
          assert.equal(line.querySelector('button'), null); assert.equal(writes.length, 1);
        """)
