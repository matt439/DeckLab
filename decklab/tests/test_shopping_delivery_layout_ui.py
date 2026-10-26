"""Shopping's native delivery disclosures retain existing receipt and queue boundaries."""
import re
import unittest

from decklab.tests import test_shopping_ui, test_shopping_queue_manage_ui
from decklab.tests.test_workspace_ui import NODE, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingDeliveryLayoutUiTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js
    run_queue_js = test_shopping_queue_manage_ui.ShoppingQueueManagementInteractionTests.run_queue_js

    def test_native_disclosure_summary_contains_only_the_order_identity_state_and_pending_count(self):
        self.run_js(r"""
          let reads = 0, writes = 0;
          api = async () => { reads++; throw new Error('expanding must not read'); };
          apiWrite = async () => { writes++; throw new Error('expanding must not write'); };
          state.may = {admin: true, orders: true, receipts: true, see_inventory: ['home']};
          state.profile = {id: 'matt', role: 'admin', space: 'home'};
          const view = drawShopping({...empty, queue_revision: 'q1', orders: [order({status: 'partial', notes: 'Keep this note', components: [
            component({quantity: 20, status: 'received', received_on: '2026-10-01'}),
            component({id: 'pending', quantity: 3}), component({id: 'cancelled', quantity: 4, status: 'cancelled'})]})]});
          const delivery = main.querySelector('.shop-delivery'), summary = delivery.querySelector('.shop-delivery-summary');
          const body = delivery.querySelector('.shop-delivery-body');
          assert.equal(delivery.tag, 'details'); assert.equal(delivery.getAttribute('open'), null);
          assert.equal(delivery.children[0], summary); assert.equal(summary.tag, 'summary');
          assert(summary.textContent.includes('Card shop')); assert(summary.textContent.includes('Ordered 8 Oct'));
          assert(summary.textContent.includes('3 cards')); assert(!summary.textContent.includes('27 cards'));
          assert(summary.textContent.includes('Part received')); assert(summary.querySelector('.status-outline'));
          for (const tag of ['button', 'a', 'input', 'details']) assert.equal(summary.querySelector(tag), null);
          assert(!summary.textContent.includes('Keep this note'));
          assert(body.textContent.includes('Keep this note')); assert(body.textContent.includes('arrived 1 Oct'));
          assert(body.textContent.includes('cancelled')); assert(body.textContent.includes('Receive delivery'));
          assert(body.querySelector('.shop-order-edit')); assert.equal(summary.querySelector('.btn-primary'), null);
          delivery.setAttribute('open', ''); summary.focus(); view.redraw();
          assert.equal(main.querySelector('.shop-delivery'), delivery); assert.equal(delivery.getAttribute('open'), '');
          assert.equal(delivery.querySelector('.shop-delivery-body'), body); assert.equal(document.activeElement, summary);
          assert.equal(reads, 0); assert.equal(writes, 0); assert.equal(inspections.length, 0);
          assert.equal(main.querySelectorAll('.btn-primary').length, 1);
          assert.equal(main.querySelector('.btn-primary').textContent, 'New order');
        """)

    def test_part_received_preorder_token_and_unknown_date_words_stay_distinct(self):
        self.run_js(r"""
          const product = component({kind: 'product', label: 'Fixture deck', product_status: 'preordered'});
          drawShopping({...empty, orders: [
            order({id: 'partial', status: 'partial', components: [product]}),
            order({id: 'preorder', components: [product]}),
            order({id: 'tokens', ordered_on: '', components: [component({kind: 'tokens', quantity: 7})]})]});
          const rows = main.querySelectorAll('.shop-delivery');
          assert(rows[0].querySelector('summary').textContent.includes('Part received'));
          assert(!rows[0].querySelector('summary').textContent.includes('Preordered'));
          assert(rows[1].querySelector('summary').textContent.includes('Preordered'));
          assert(rows[2].querySelector('summary').textContent.includes('7 token cards'));
          assert(rows[2].querySelector('summary').textContent.includes('Order date not recorded'));
          assert(rows.every(node => node.getAttribute('open') === null));
        """)

    def test_strip_thresholds_still_count_hidden_copies_and_full_contents_include_received_parts(self):
        self.run_js(r"""
          const card = name => ({name, type_line: 'Creature', img_small: null});
          const expected = {6: [], 7: ['+4'], 8: ['+5'], 9: ['+6', '+4']};
          for (const n of [6, 7, 8, 9]) {
            clear(main);
            const items = Array.from({length: n}, (_, i) => ({name: 'Pending ' + i, quantity: i === 0 ? 2 : i === n - 1 ? 3 : 1,
              card: card('Pending ' + i)}));
            const current = order({components: [component({quantity: n + 3, items}),
              component({id: 'received', status: 'received', quantity: 1, items: [{name: 'Already arrived', quantity: 1, card: null}]})]});
            drawShopping({...empty, orders: [current]});
            const delivery = main.querySelector('.shop-delivery'), strip = delivery.querySelector('.shop-strip');
            same(strip.querySelectorAll('.shop-thumb-more').map(node => node.textContent), expected[n]);
            assert(!strip.textContent.includes('Already arrived'));
            assert(strip.querySelector('.shop-thumb-text').textContent.includes('Pending 0'));
            assert.equal(strip.querySelector('img'), null);
            const more = strip.querySelector('.shop-thumb-more');
            if (more) {
              assert.equal(more.getAttribute('aria-label'), 'Show all ' + (n + 3) + ' cards'); more.click();
              const all = document.body.querySelectorAll('.shop-contents').at(-1);
              assert(all.textContent.includes('Already arrived'));
            }
            strip.querySelector('.shop-thumb').click(); assert.equal(inspections.at(-1).card.name, 'Pending 0');
          }
        """)

    def test_arrival_checks_remain_bound_to_pending_checks_of_their_own_delivery(self):
        self.run_js(r"""
          drawShopping({...empty, orders: [order({id: 'first'}), order({id: 'second'})], checks: [
            {order_id: 'first', status: 'pending', text: 'Check first'},
            {order_id: 'second', status: 'pending', text: 'Check second'},
            {order_id: 'first', status: 'received', text: 'Follow up separately'}]});
          const deliveries = main.querySelectorAll('.shop-delivery');
          for (const [index, name] of ['first', 'second'].entries()) {
            const summary = deliveries[index].querySelector('.shop-delivery-summary');
            const checks = deliveries[index].querySelector('.shop-delivery-body').querySelector('.shop-checks');
            assert.equal(summary.querySelector('.shop-checks'), null);
            assert(checks.textContent.includes('Check ' + name));
            assert(!checks.textContent.includes('Check ' + (name === 'first' ? 'second' : 'first')));
            assert(!checks.textContent.includes('Follow up separately'));
          }
          assert(main.querySelector('.shop-followups').textContent.includes('Follow up separately'));
        """)

    def test_read_only_receipt_and_edit_gates_do_not_move_into_the_summary_or_reveal_source_paths(self):
        self.run_js(r"""
          const inputs = [
            [{admin: false, orders: false, receipts: false, see_inventory: ['home']}, false, false],
            [{admin: false, orders: true, receipts: false, see_inventory: ['home']}, false, true],
            [{admin: true, orders: true, receipts: true, see_inventory: ['user2']}, true, false]
          ];
          state.profile = {id: 'matt', role: 'admin', space: 'home'};
          for (const [may, receives, edits] of inputs) {
            clear(main); state.may = may;
            drawShopping({...empty, queue_revision: 'q1', orders: [order({seller: '<script>shop</script>', sources: ['magic/private.md'],
              notes: 'Plain <b>note</b>', components: [component({path: 'magic/orders/private.csv'})]})]});
            const delivery = main.querySelector('.shop-delivery'), summary = delivery.querySelector('summary'), body = delivery.querySelector('.shop-delivery-body');
            assert.equal(summary.querySelector('a'), null); assert.equal(summary.querySelector('button'), null);
            const link = body.querySelector('.actions').querySelector('a');
            assert.equal(link.textContent, receives ? 'Receive delivery' : 'Delivery details');
            assert.equal(link.getAttribute('href'), '#/receipt?order=2026-10-08-order');
            assert.equal(!!body.querySelector('.shop-order-edit'), edits);
            assert(summary.textContent.includes('<script>shop</script>')); assert(body.textContent.includes('Plain <b>note</b>'));
            assert.equal(delivery.querySelector('script'), null); assert.equal(delivery.querySelector('b'), null);
            assert(!delivery.textContent.includes('private.csv')); assert(!delivery.textContent.includes('magic/private.md'));
          }
          clear(main); state.may = {admin: true, orders: true, receipts: true, see_inventory: ['home']};
          drawShopping({...empty, orders: [order()]}); assert.equal(main.querySelector('.shop-order-edit'), null, 'missing revision remains guarded');
        """)

    def test_actual_queue_save_retains_the_open_delivery_body_checks_and_viewer_nodes(self):
        self.run_queue_js(r"""
          const queued = queueRow(1), writes = [];
          apiWrite = async (path, body) => { writes.push(path); return saved(body, {...queued, ...body.values}); };
          const deliveryCard = {name: 'On the way', type_line: 'Creature', img_small: null};
          const view = drawShopping({...queueData([queued]), orders: [order({components: [component({items: [
            {name: 'On the way', quantity: 3, card: deliveryCard}]})]})],
            checks: [{order_id: '2026-10-08-order', status: 'pending', text: 'Check delivery'}]});
          const delivery = main.querySelector('.shop-delivery'), summary = delivery.querySelector('summary');
          const body = delivery.querySelector('.shop-delivery-body'), checks = body.querySelector('.shop-checks'), thumb = body.querySelector('.shop-thumb');
          delivery.setAttribute('open', ''); checks.removeAttribute('open');
          const sheet = openDetails(1); type(sheet, 'quantity', '2'); action(sheet, 'Save').click(); await settle();
          assert.equal(main.querySelector('.shop-delivery'), delivery); assert.equal(delivery.querySelector('summary'), summary);
          assert.equal(delivery.getAttribute('open'), ''); assert.equal(delivery.querySelector('.shop-delivery-body'), body);
          assert.equal(body.querySelector('.shop-checks'), checks); assert.equal(checks.getAttribute('open'), null);
          assert.equal(body.querySelector('.shop-thumb'), thumb); assert(thumb.isConnected);
          thumb.click(); assert.equal(inspections.at(-1).trigger, thumb); assert.equal(inspections.at(-1).card, deliveryCard);
          same(writes, ['/api/shopping/queue']); assert.equal(view.data.queue_revision, 'queue-v2');
        """)


class ShoppingDeliveryStyleTests(unittest.TestCase):
    def test_summary_keeps_the_compact_touch_floor_without_hiding_full_names_or_focus(self):
        css = (WEB / 'shopping.css').read_text(encoding='utf-8')
        summary = re.search(r'\.shop-delivery-summary\s*\{([^}]+)\}', css).group(1)
        self.assertIn('min-height: 54px', summary)
        self.assertNotIn('height: 54px;', summary.replace('min-height: 54px;', ''))
        self.assertIn('list-style: none', summary)
        self.assertRegex(css, r'\.shop-delivery-summary::before\s*\{[^}]*content:\s*none;[^}]*display:\s*none')
        self.assertRegex(css, r'\.shop-delivery:not\(\[open\]\) > \.shop-delivery-body\s*\{[^}]*display:\s*none')
        self.assertRegex(css, r'\.shop-delivery-summary:focus-visible\s*\{[^}]*outline-offset:\s*-3px')
        self.assertRegex(css, r'\.shop-delivery-title\s*\{[^}]*overflow-wrap:\s*anywhere')
        self.assertRegex(css, r'\.shop-delivery-summary:active\s*\{[^}]*var\(--accent-soft\)')

    def test_strip_uses_44px_cards_and_preserves_both_responsive_more_buttons(self):
        css = (WEB / 'shopping.css').read_text(encoding='utf-8')
        self.assertRegex(css, r'\.shop-strip li\s*\{[^}]*flex:\s*0 0 44px')
        self.assertRegex(css, r'\.shop-strip\s*\{[^}]*overflow-x:\s*auto')
        self.assertRegex(css, r'\.shop-thumb:focus-visible\s*\{[^}]*outline-offset:\s*-3px')
        self.assertRegex(css, r'@media \(max-width: 599px\)\s*\{\s*\.shop-strip \.shop-wide-only\s*\{\s*display:\s*none')
        self.assertRegex(css, r'@media \(min-width: 600px\)\s*\{\s*\.shop-strip \.shop-narrow-only\s*\{\s*display:\s*none')
