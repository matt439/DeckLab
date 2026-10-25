"""Sort inventory-visible deck price rows through the real scripts, without network or writes."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


PRICES = r"""
  const priceRow = (name, missing, each, cost, extra = {}) => ({name, need: missing + 1, missing,
    owned: 1, available: 1, aud_each: each, aud_missing: cost,
    labels: {on_the_way: [], in_use: []}, ...extra});
  const priceRows = [priceRow('Alpha', 4, 2, 8), priceRow('Beta', 1, 12, 12),
    priceRow('Gamma', 8, .5, 4), priceRow('Delta', 1, 4, 4), priceRow('Unknown', 2, null, null),
    priceRow('Zero', 1, 0, 0),
    priceRow('Coming', 0, 100, 0, {labels: {on_the_way: [['order test-order', 1]], in_use: []}}),
    priceRow('Held', 0, 1, 0, {labels: {on_the_way: [], in_use: [['Other Deck', 2]]}}),
    priceRow('Already here', 0, 5, 0, {need: 5, available: 9})];
  const makePrices = (rows = priceRows) => ({rows,
    totals: {cards: rows.length, need: rows.reduce((n, r) => n + r.need, 0),
      missing: rows.reduce((n, r) => n + r.missing, 0), aud_missing: 28, unpriced: ['Unknown']},
    price_error: null, price_date: '2026-10-14', rate: 1.43, rate_date: '2026-10-13',
    conflicts: [], unresolved: [], warnings: []});
  const names = table => table.querySelectorAll('tbody').map(body => body.querySelector('.card-link').textContent);
  const bodies = table => new Map(table.querySelectorAll('tbody').map(body => [body.querySelector('.card-link').textContent, body]));
  const sortButton = (table, key) => table.querySelector(`[data-owned-sort=${key}]`);
  const sortedHeading = table => table.querySelectorAll('thead')[0].querySelectorAll('[aria-sort]');
  const showPrices = (owned = makePrices()) => {
    clear(main); state.cards = new Map(owned.rows.map(row => [row.name, card(row.name, 'Creature', 1)]));
    const section = ownedSection({owned, table: null, summary: makePage().summary}); main.append(section);
    return section.querySelector('table');
  };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckPriceSortUiTests(unittest.TestCase):
    def run_js(self, code, *, phone=False):
        viewport = {"innerWidth": 390, "innerHeight": 844, "coarse": True,
                    "visual": {"width": 390, "height": 844}} if phone else None
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), PAGE + PRICES + code, True, viewport]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_cost_sorts_extended_estimates_highest_first_then_reverses_with_unknown_last(self):
        self.run_js(r"""
          const owned = makePrices(), before = JSON.stringify(owned), table = showPrices(owned);
          assert.equal(names(table)[0], 'Gamma'); // existing missing-first presentation
          sortButton(table, 'cost').click();
          same(names(table), ['Beta', 'Alpha', 'Delta', 'Gamma', 'Coming', 'Held', 'Zero', 'Unknown']);
          assert.equal(bodies(table).get('Beta').querySelectorAll('td')[3].textContent, '12.00');
          assert.equal(bodies(table).get('Gamma').querySelectorAll('td')[3].textContent, '4.00');
          assert(bodies(table).get('Gamma').textContent.includes('A$0.50 each (estimate)'));
          sortButton(table, 'cost').click();
          same(names(table), ['Coming', 'Held', 'Zero', 'Delta', 'Gamma', 'Alpha', 'Beta', 'Unknown']);
          assert.equal(JSON.stringify(owned), before); assert(!table.textContent.includes('Already here'));
          for (const text of ['cheapest non-foil', '2026-10-14', '1.43 AUD', '2026-10-13', 'No price for: Unknown.'])
            assert(main.textContent.includes(text), text);
        """)

    def test_card_and_missing_headings_toggle_independently_and_keep_stable_ties(self):
        self.run_js(r"""
          const table = showPrices();
          sortButton(table, 'name').click();
          same(names(table), ['Alpha', 'Beta', 'Coming', 'Delta', 'Gamma', 'Held', 'Unknown', 'Zero']);
          sortButton(table, 'name').click();
          same(names(table), ['Zero', 'Unknown', 'Held', 'Gamma', 'Delta', 'Coming', 'Beta', 'Alpha']);
          sortButton(table, 'missing').click();
          same(names(table), ['Gamma', 'Alpha', 'Unknown', 'Beta', 'Delta', 'Zero', 'Coming', 'Held']);
          sortButton(table, 'missing').click();
          same(names(table), ['Coming', 'Held', 'Beta', 'Delta', 'Zero', 'Unknown', 'Alpha', 'Gamma']);
          sortButton(table, 'cost').click();
          assert.equal(sortedHeading(table)[0].getAttribute('aria-sort'), 'descending');
        """)

    def test_unknown_nonfinite_and_nonnumeric_costs_never_become_free_estimates(self):
        self.run_js(r"""
          const bad = [null, NaN, Infinity, -Infinity, '9', -1];
          const rows = [priceRow('Free', 1, 0, 0), priceRow('Known', 1, 1, 1),
            ...bad.map((cost, n) => priceRow('Unknown ' + n, 1, 1, cost))];
          const table = showPrices(makePrices(rows));
          for (const expected of [['Known', 'Free'], ['Free', 'Known']]) {
            sortButton(table, 'cost').click();
            same(names(table).slice(0, 2), expected);
            same(names(table).slice(2), bad.map((_, n) => 'Unknown ' + n));
            for (const body of table.querySelectorAll('tbody').slice(2)) assert.equal(body.querySelectorAll('td')[3].textContent, '-');
          }
          assert.equal(ownedMissingPrice({aud_each: 1.25, missing: 3}), 3.75);
          assert.equal(ownedMissingPrice({aud_each: .333, missing: 3, aud_missing: 1}), 1);
          assert.equal(ownedMissingPrice({aud_each: 1.25, aud_missing: null, missing: 3}), null);
          assert.equal(ownedMissingPrice({aud_each: Infinity, missing: 3}), null);
        """)

    def test_sort_moves_whole_card_bodies_preserving_labels_viewer_and_final_totals(self):
        self.run_js(r"""
          priceRows[0].priced_finish = 'foil';
          const table = showPrices(), originalBodies = bodies(table), foot = table.querySelector('tfoot');
          const total = foot.textContent;
          same(foot.querySelectorAll('tr')[0].querySelectorAll('td').map(cell => cell.textContent), ['30', '13', '17', '']);
          for (const key of ['cost', 'name', 'missing']) {
            sortButton(table, key).click();
            assert.equal(table.children.at(-1), foot); assert.equal(foot.textContent, total);
            for (const [name, body] of bodies(table)) assert.equal(body, originalBodies.get(name));
          }
          assert(originalBodies.get('Alpha').textContent.includes('foil price'));
          assert(originalBodies.get('Coming').textContent.includes('test-order'));
          assert(originalBodies.get('Held').textContent.includes('2 in use in Other Deck'));
          const link = originalBodies.get('Gamma').querySelector('.card-link'); link.click();
          assert.equal(inspections.at(-1).card.name, 'Gamma');
          assert.equal(JSON.stringify(viewerGroup(link).items.map(item => item.card.name)), JSON.stringify(names(table)));
          assert(total.includes('All 9 cards')); assert(total.includes('A$28.00'));
        """)

    def test_native_header_buttons_expose_one_aria_sort_and_keep_keyboard_focus(self):
        self.run_js(r"""
          const table = showPrices();
          assert.equal(table.querySelectorAll('thead')[0].querySelectorAll('th').length, 5);
          assert.equal(table.querySelectorAll('.th-sort').length, 3); assert.equal(sortedHeading(table).length, 0);
          for (const [key, direction] of [['name', 'ascending'], ['cost', 'descending'], ['missing', 'descending']]) {
            const button = sortButton(table, key); assert.equal(button.tag, 'button');
            assert.equal(button.getAttribute('type'), 'button'); button.focus(); button.click();
            assert.equal(document.activeElement, button); assert.equal(sortedHeading(table).length, 1);
            assert.equal(button.parentNode.getAttribute('aria-sort'), direction);
            button.click(); assert.equal(button.parentNode.getAttribute('aria-sort'), direction === 'ascending' ? 'descending' : 'ascending');
          }
        """)

    def test_compact_phone_table_uses_the_same_cost_and_missing_controls(self):
        self.run_js(r"""
          assert.equal(window.innerWidth, 390); const table = showPrices();
          assert.equal(table.querySelector('colgroup').children.length, 5);
          assert.equal(sortButton(table, 'cost').textContent, '~AUD missing');
          sortButton(table, 'cost').click(); assert.equal(names(table)[0], 'Beta');
          sortButton(table, 'cost').click(); assert.equal(names(table)[0], 'Coming');
          sortButton(table, 'missing').click(); assert.equal(names(table)[0], 'Gamma');
        """, phone=True)

    def test_filter_picture_and_tab_toggles_preserve_this_table_sort(self):
        self.run_js(r"""
          const page = makePage(); page.owned = makePrices();
          page.sections = {Deck: priceRows.map(row => ({name: row.name, qty: row.need, set: null, number: null,
            finish: 'nonfoil', card: card(row.name, 'Creature', 1)}))};
          clear(main); location.hash = '#/deck?id=casual%2Ftest&tab=cards';
          drawDeck(page, deckViewOf(parseHash().params));
          const table = main.querySelector('.owned-table'); sortButton(table, 'cost').click();
          const sorted = names(table);
          main.querySelector('.deck-filter').querySelectorAll('button').find(button => button.textContent.startsWith('Missing')).click();
          buttonText(main.querySelector('.deck-cards-bar'), 'Pictures').click();
          tab('overview').click(); tab('cards').click();
          assert.equal(main.querySelector('.owned-table'), table); assert.equal(JSON.stringify(names(table)), JSON.stringify(sorted));
          assert.equal(sortButton(table, 'cost').parentNode.getAttribute('aria-sort'), 'descending');
          assert.equal(page.owned.rows[0].name, 'Alpha');
        """)

    def test_hidden_failed_and_unpriced_inventory_remain_distinct_and_sort_fetches_nothing(self):
        self.run_js(r"""
          const reads = [], writes = []; api = (...args) => {reads.push(args); throw new Error('No reads');};
          apiWrite = (...args) => {writes.push(args); throw new Error('No writes');};
          assert.equal(ownedSection({}), null);
          const failed = ownedSection({owned: null}); assert.equal(failed.querySelector('table'), null);
          assert(failed.textContent.includes("couldn't be worked out"));
          const owned = makePrices(); owned.price_error = 'Rate unavailable';
          const table = showPrices(owned); sortButton(table, 'cost').click();
          for (const body of table.querySelectorAll('tbody')) {
            assert.equal(body.querySelectorAll('td')[3].textContent, '-'); assert(body.textContent.includes('No estimate'));
          }
          assert(main.textContent.includes('No A$ estimates: Rate unavailable'));
          same(reads, []); same(writes, []);
          const page = makePage(); delete page.owned; delete page.tokens; delete page.table;
          clear(main); location.hash = '#/deck?id=casual%2Ftest&tab=cards';
          drawDeck(page, deckViewOf(parseHash().params));
          assert.equal(main.querySelector('#sec-owned'), null); assert.equal(main.querySelector('[data-owned-sort]'), null);
        """)

    def test_stale_header_handlers_do_not_sort_after_profile_route_or_detachment(self):
        self.run_js(r"""
          for (const leave of [() => {state.profile = {id: 'user1'};}, () => {routeToken++;}, table => table.remove()]) {
            state.profile = {id: 'matt'}; const table = showPrices(), before = names(table);
            leave(table); sortButton(table, 'cost').click(); assert.equal(JSON.stringify(names(table)), JSON.stringify(before));
            assert.equal(sortedHeading(table).length, 0);
          }
        """)


if __name__ == "__main__":
    unittest.main()
