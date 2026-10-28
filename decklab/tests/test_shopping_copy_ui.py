"""Copy a named shop's current queue without writes or real clipboard access (E5-S24)."""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingCopyInteractionTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_copy_js(self, scenario):
        self.run_js(r"""
          state.may = {admin: false, orders: false, see_inventory: ['home'], see_home_records: true};
          api = () => { throw new Error('Copy must not read'); };
          apiWrite = () => { throw new Error('Copy must not write'); };
          const queued = (name, number, extra = {}) => row(name, {queue_row: number, listed_at: 'Shop', ...extra});
          const shopping = (queue, extra = {}) => ({...empty, queue_revision: 'q1', to_buy: queue, ...extra});
          const copyButton = shop => main.querySelectorAll('.shop-store-copy').find(button => button.dataset.copyShop === shop);
          const copySheet = () => [...shopQueueSheets].find(sheet => sheet.shopCopy && !sheet.closed);
          const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
          const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
            return {promise, resolve, reject}; };
          const messages = [], copies = [];
          toast = text => messages.push(text);
          navigator.clipboard = {writeText: async text => copies.push(text)};
          const cardData = name => ({name, type_line: 'Creature', mana_cost: '', img: '/img/fdn/1/normal', img_small: '/img/fdn/1/small'});
        """ + scenario)

    def test_one_copy_per_named_shop_is_a_sibling_of_the_original_radio_label(self):
        self.run_copy_js(r"""
          const queue = [queued('Alpha', 1, {listed_at: ' A ', card: cardData('Alpha')}),
            queued('Beta', 2, {listed_at: 'B'}), queued('Unchecked', 3, {listed_at: ''})];
          const view = drawShopping(shopping(queue));
          const radios = main.querySelectorAll('.shop-store-radio'), original = main.querySelectorAll('[data-shop-queue]');
          same(main.querySelectorAll('.shop-store-copy').map(button => button.dataset.copyShop), ['A', 'B']);
          same(radios.map(radio => radio.value), ['all', 'shop:A', 'shop:B', 'unchecked']);
          assert(main.querySelectorAll('.shop-store-copy').every(button => button.closest('label') === null));
          const button = copyButton('A');
          assert.equal(button.getAttribute('aria-label'), "Copy this shop's list for A");
          assert.equal(button.parentNode.querySelector('label').getAttribute('for'), radios[1].id);
          button.click(); await settle();
          same(copies, ['1 Alpha\n']); same(messages, ['1 card copied for A.']);
          assert.equal(view.shopChoice, 'all');
          assert.equal(main.querySelectorAll('.shop-queue-write').length, 0);
          main.querySelectorAll('[data-shop-queue]').forEach((node, index) => assert(node === original[index]));
          assert(main.querySelectorAll('.shop-store-radio').every((radio, index) => radio === radios[index]));
        """)

    def test_copy_includes_all_queue_states_and_hidden_long_term_rows_but_no_orders_or_missing_demand(self):
        self.run_copy_js(r"""
          const queue = [queued('Ready', 1, {quantity: 2}), queued('Waiting', 2, {state: 'waiting_for_stock', quantity: 3}),
            queued('Reprint', 3, {state: 'waiting_for_reprint', quantity: 4}), queued('Deferred', 4, {state: 'deferred', quantity: 5}),
            ...Array.from({length: 14}, (_, index) => queued('Later', index + 5, {state: 'long_term', quantity: 1})),
            queued('Other shop', 19, {listed_at: 'Other', quantity: 99})];
          const before = JSON.stringify(queue);
          drawShopping(shopping(queue, {orders: [order({components: [component({items: [{name: 'Already ordered', quantity: 8}]})]}),
            { ...order({id: 'received', status: 'received'}), components: [component({status: 'received'})]}],
            missing_cards: {ready: true, rows: [{name: 'Unqueued missing demand', missing: 20, decks: []}], errors: [], warnings: []}}));
          const long = main.querySelector('#shop-long-term').closest('section');
          assert.equal(long.querySelectorAll('[data-shop-queue]').length, 12);
          copyButton('Shop').click(); await settle();
          same(copies, ['2 Ready\n3 Waiting\n4 Reprint\n5 Deferred\n14 Later\n']);
          same(messages, ['28 cards copied for Shop.']);
          assert.equal(long.querySelectorAll('[data-shop-queue]').length, 12);
          assert.equal(JSON.stringify(queue), before);
        """)

    def test_exact_printings_and_requested_finishes_are_preserved_using_declared_rows(self):
        self.run_copy_js(r"""
          const queue = [queued('Fire', 1, {quantity: 2, printing: 'exact', set: 'mh2', collector_number: '290', finish: 'nonfoil',
              card: {...cardData('Fire // Ice'), set: 'apc', number: '128'}}),
            queued('Foil', 2, {printing: 'exact', set: 'fdn', collector_number: '7', finish: 'foil'}),
            queued('Etched', 3, {printing: 'exact', set: 'cmm', collector_number: '1a', finish: 'etched'}),
            queued('Any foil', 4, {finish: 'foil'}), queued('Any etched', 5, {finish: 'etched'}),
            queued('Any nonfoil', 6, {finish: 'nonfoil'}), queued('Any finish', 7)];
          drawShopping(shopping(queue)); copyButton('Shop').click(); await settle();
          same(copies, ['2 Fire // Ice (MH2) 290 [nonfoil]\n1 Foil (FDN) 7 [foil]\n1 Etched (CMM) 1a [etched]\n'
            + '1 Any foil [foil]\n1 Any etched [etched]\n1 Any nonfoil [nonfoil]\n1 Any finish\n']);
          same(messages, ['8 cards copied for Shop.']);
          assert(!copies[0].includes('APC'));
        """)

    def test_only_identical_requests_coalesce_and_tokens_stay_distinct(self):
        self.run_copy_js(r"""
          const exact = {printing: 'exact', set: 'fdn', collector_number: '7', finish: 'nonfoil'};
          drawShopping(shopping([queued('Alpha', 1, {quantity: 2, for: 'Deck A'}), queued('Alpha', 2, {quantity: 3, for: 'Deck B'}),
            queued('Alpha', 3, {...exact}), queued('Alpha', 4, {...exact, quantity: 2}),
            queued('Alpha', 5, {...exact, collector_number: '8'}), queued('Alpha', 6, {...exact, finish: 'foil'}),
            queued('Alpha', 7, {is_token: true, quantity: 4})]));
          copyButton('Shop').click(); await settle();
          same(copies, ['5 Alpha\n3 Alpha (FDN) 7 [nonfoil]\n1 Alpha (FDN) 8 [nonfoil]\n1 Alpha (FDN) 7 [foil]\n4 Alpha\n']);
          same(messages, ['14 cards copied for Shop.']);
        """)

    def test_any_printing_blank_finish_and_explicit_nonfoil_requests_stay_distinct(self):
        self.run_copy_js(r"""
          drawShopping(shopping([queued('Alpha', 1, {quantity: 2, finish: ''}),
            queued('Alpha', 2, {quantity: 3, finish: 'nonfoil'}), queued('Alpha', 3, {quantity: 1, finish: 'nonfoil'})]));
          copyButton('Shop').click(); await settle();
          same(copies, ['2 Alpha\n4 Alpha [nonfoil]\n']); same(messages, ['6 cards copied for Shop.']);
        """)

    def test_clipboard_absence_opens_the_same_selectable_text_and_close_returns_to_its_trigger(self):
        self.run_copy_js(r"""
          delete navigator.clipboard;
          drawShopping(shopping([queued('Alpha', 1, {quantity: 3})]));
          const button = copyButton('Shop'); button.focus(); button.click(); await settle();
          const sheet = copySheet(), area = sheet.body.querySelector('textarea');
          assert.equal(area.value, '3 Alpha\n'); assert.equal(area.getAttribute('readonly'), '');
          assert.equal(area.getAttribute('aria-label'), 'List for Shop');
          assert(area.selected && document.activeElement === area); assert(!button.disabled);
          assert(sheet.body.textContent.includes('3 cards from all queue categories, including long-term plans'));
          sheet.foot.querySelector('button').click();
          assert(sheet.closed && document.activeElement === button); assert.equal(copySheet(), undefined);
          same(messages, []); same(copies, []);
        """)

    def test_rejected_clipboard_preserves_every_exact_request_in_the_fallback(self):
        self.run_copy_js(r"""
          navigator.clipboard.writeText = async text => {copies.push(text); throw new Error('Permission denied');};
          drawShopping(shopping([queued('Alpha', 1, {quantity: 2, printing: 'exact', set: 'fdn', collector_number: '7', finish: 'foil'})]));
          copyButton('Shop').click(); await settle();
          const sheet = copySheet();
          same(copies, ['2 Alpha (FDN) 7 [foil]\n']); same(messages, []);
          assert.equal(sheet.body.querySelector('textarea').value, copies[0]);
          assert(sheet.body.textContent.includes('Exact printing requests include the set, collector number and finish.'));
        """)

    def test_repeated_copy_is_blocked_until_the_current_clipboard_request_finishes(self):
        self.run_copy_js(r"""
          const pending = deferred(); navigator.clipboard.writeText = text => {copies.push(text); return pending.promise;};
          drawShopping(shopping([queued('Alpha', 1)]));
          const button = copyButton('Shop'); button.click(); button.click();
          assert(button.disabled); same(copies, ['1 Alpha\n']);
          pending.resolve(); await settle(); assert(!button.disabled); same(messages, ['1 card copied for Shop.']);
        """)

    def test_old_controls_and_unavailable_queues_cannot_start_a_clipboard_request(self):
        self.run_copy_js(r"""
          for (const departure of ['detach', 'redraw', 'profile', 'route', 'permission', 'busy', 'stale']) {
            clear(main); state.profile = state.profiles[0]; state.may.see_home_records = true;
            const view = drawShopping(shopping([queued('Alpha', 1)])), button = copyButton('Shop');
            if (departure === 'detach') clear(main);
            if (departure === 'redraw') view.redraw();
            if (departure === 'profile') state.profile = state.profiles[1];
            if (departure === 'route') routeToken++;
            if (departure === 'permission') state.may.see_home_records = false;
            if (departure === 'busy') view.busy = true;
            if (departure === 'stale') view.stale = true;
            button.click(); await settle();
          }
          same(copies, []); same(messages, []); assert.equal(copySheet(), undefined);
        """)

    def test_late_clipboard_success_or_failure_cannot_notify_or_open_a_stale_fallback(self):
        self.run_copy_js(r"""
          for (const outcome of ['resolve', 'reject']) for (const departure of ['detach', 'redraw', 'profile', 'route', 'revision', 'rows', 'permission']) {
            clear(main); state.profile = state.profiles[0]; state.may.see_home_records = true;
            const view = drawShopping(shopping([queued('Alpha', 1)])), button = copyButton('Shop'), pending = deferred();
            navigator.clipboard.writeText = () => pending.promise; button.click();
            if (departure === 'detach') clear(main);
            if (departure === 'redraw') view.redraw();
            if (departure === 'profile') state.profile = state.profiles[1];
            if (departure === 'route') routeToken++;
            if (departure === 'revision') view.data.queue_revision = 'q2';
            if (departure === 'rows') view.data.to_buy[0].quantity = 2;
            if (departure === 'permission') state.may.see_home_records = false;
            pending[outcome](outcome === 'reject' ? new Error('Denied') : undefined); await settle();
            assert.equal(copySheet(), undefined); same(messages, []);
          }
        """)

    def test_a_fresh_control_copies_current_edited_added_and_removed_queue_rows(self):
        self.run_copy_js(r"""
          const view = drawShopping(shopping([queued('Alpha', 1), queued('Removed', 2)])), old = copyButton('Shop');
          view.data.to_buy.splice(1, 1); view.data.to_buy[0].quantity = 4;
          view.data.to_buy.push(queued('Added', 2, {printing: 'exact', set: 'fdn', collector_number: '8', finish: 'etched'}));
          view.data.queue_revision = 'q2'; view.redraw(); old.click();
          copyButton('Shop').click(); await settle();
          same(copies, ['4 Alpha\n1 Added (FDN) 8 [etched]\n']); same(messages, ['5 cards copied for Shop.']);
        """)

    def test_copy_fallback_is_closed_on_redraw_busy_or_existing_route_cleanup(self):
        self.run_copy_js(r"""
          delete navigator.clipboard;
          for (const departure of ['redraw', 'busy', 'cleanup']) {
            clear(main); const view = drawShopping(shopping([queued('Alpha', 1)]));
            copyButton('Shop').click(); await settle(); const sheet = copySheet(); assert(sheet);
            if (departure === 'redraw') view.redraw();
            if (departure === 'busy') shopQueueBusy(view, true);
            if (departure === 'cleanup') {state.profile = state.profiles[1]; shopCloseQueueSheets();}
            assert(sheet.closed); assert.equal(copySheet(), undefined);
            state.profile = state.profiles[0];
          }
        """)

    def test_redraw_returns_fallback_focus_to_current_shop_without_stealing_another_fields_focus(self):
        self.run_copy_js(r"""
          delete navigator.clipboard;
          const view = drawShopping(shopping([queued('Alpha', 1)]));
          const original = copyButton('Shop'); original.click(); await settle();
          const first = copySheet(); assert(first.dialog.contains(document.activeElement));
          view.redraw(); await settle();
          const current = copyButton('Shop'); assert(current !== original);
          assert(first.closed); assert(document.activeElement === current);
          current.click(); await settle(); const second = copySheet();
          view.redraw(); const other = main.querySelector('.shop-store-radio'); other.focus(); await settle();
          assert(second.closed); assert(document.activeElement === other);
        """)

    def test_hidden_home_records_have_no_by_shop_or_copy_even_for_an_admin_elsewhere(self):
        self.run_copy_js(r"""
          state.may = {admin: true, orders: true, see_inventory: ['home'], see_home_records: false};
          drawShopping(shopping([queued('Alpha', 1)]));
          assert.equal(main.querySelector('#shop-by-shop'), null);
          assert.equal(main.querySelector('.shop-store-copy'), null);
          same(copies, []);
        """)

    def test_invalid_or_incomplete_exact_requests_are_never_partially_copied(self):
        self.run_copy_js(r"""
          for (const broken of [{printing: 'exact', set: 'fdn', collector_number: '7', finish: ''},
            {printing: 'exact', set: '', collector_number: '7', finish: 'foil'}, {quantity: 0},
            {quantity: 1.5}, {finish: 'unknown'}, {name: 'Alpha\nInjected'}]) {
            clear(main); drawShopping(shopping([queued('Good', 1), queued('Alpha', 2, broken)]));
            copyButton('Shop').click(); await settle();
          }
          same(copies, []); assert.equal(copySheet(), undefined);
          assert.equal(messages.length, 6); assert(messages.every(text => text.includes('check its rows')));
        """)

    def test_grouping_density_and_shop_matching_do_not_duplicate_copy_controls_or_change_scope(self):
        self.run_copy_js(r"""
          const view = drawShopping(shopping([queued('Alpha', 1), queued('Later', 2, {state: 'long_term'})]));
          const button = copyButton('Shop');
          const choose = main.querySelectorAll('.shop-store-radio').find(radio => radio.value === 'shop:Shop');
          choose.checked = true; choose.fire('change');
          view.queueOrder = 'shop'; shopSyncQueueControls(view);
          window.matchMedia(SHOP_QUEUE_LAB).matches = true; window.matchMedia(SHOP_QUEUE_LAB).fire('change');
          assert(copyButton('Shop') === button); assert.equal(main.querySelectorAll('.shop-store-copy').length, 1);
          button.click(); await settle(); same(copies, ['1 Alpha\n1 Later\n']);
        """)
