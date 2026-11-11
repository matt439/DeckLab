"""E5-S33 under Node: a shop line that was cut short or wrongly matched says so on Shopping, in Baskets
and in a row's Price history.

Run: python scripts/test_fixtures.py decklab.tests.test_shopping_snapshot_accuracy_ui
"""
import unittest

from decklab.tests import test_shopping_baskets_ui, test_shopping_snapshot_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SnapshotLineAccuracyTests(unittest.TestCase):
    run_js = test_shopping_snapshot_ui.ShoppingSnapshotTests.run_js
    run_snapshot_js = test_shopping_snapshot_ui.ShoppingSnapshotTests.run_snapshot_js

    def test_a_first_page_only_line_says_more_results_were_not_read(self):
        self.run_snapshot_js("""
          const portal = extra => snap({shop: "Games Portal", url: null, ...extra});
          draw([row("Sol Ring", {queue_row: 1, shop_snapshots: [snap(), portal({partial: true})]}),
            row("Rare Thing", {queue_row: 2, shop_snapshots: [portal({status: "not_listed", price_aud: null, set: null, partial: true})]})]);
          const lines = queueRow("Sol Ring").querySelectorAll(".shop-snapshot");
          assert(!lines[0].textContent.includes("first page only"), "MTGMate's whole page has no flag");
          assert(lines[1].textContent.includes("first page only, more results not read"), lines[1].textContent);
          assert(lines[1].querySelector("[data-shop-snapshot-partial]"));
          const unlisted = queueRow("Rare Thing").querySelector(".shop-snapshot");
          assert(unlisted.textContent.includes("Games Portal: not listed"));
          assert(unlisted.textContent.includes("first page only, more results not read"), unlisted.textContent);
          const marker = shopSnapshotMarker({shop_snapshots: [portal({partial: true})]});
          assert(marker.getAttribute("aria-label").includes("first page only, more results not read"));
        """)

    def test_an_exact_row_the_shop_lists_elsewhere_names_the_shops_sets(self):
        self.run_snapshot_js("""
          draw([row("Sol Ring", {queue_row: 1, printing: "exact", set: "ltc", collector_number: "284",
            shop_snapshot: snap({status: "not_matched", price_aud: null, stock: null, set: null, url: null,
              shop_sets: ["c16", "cmm", "<b>", 7]})})]);
          const line = queueRow("Sol Ring").querySelector(".shop-snapshot");
          assert(line.textContent.includes("MTGMate: listed, but not matched to your printing (the shop's sets: C16, CMM)"),
            line.textContent);
          assert(!line.textContent.includes("A$"));
          assert(!line.textContent.includes("not listed"));
          assert.equal(line.getAttribute("data-shop-snapshot"), "not_matched");
        """)

    def test_a_token_row_says_token_cards_arent_checked(self):
        self.run_snapshot_js("""
          draw([row("Treasure", {queue_row: 1, is_token: true,
            shop_snapshot: snap({status: "token", price_aud: null, stock: null, set: null, url: null, fetched_at: null})})]);
          const line = queueRow("Treasure").querySelector(".shop-snapshot");
          assert(line.textContent.includes("MTGMate: token cards aren't checked at this shop"), line.textContent);
          assert(!line.textContent.includes("A$"));
          assert.equal(line.querySelector("time"), null);
          assert.equal(queueRow("Treasure").querySelector(".shop-history-open"), null, "no history is kept for a token");
        """)

    def test_price_history_asks_for_the_row_and_says_whose_printing_it_read(self):
        self.run_snapshot_js("""
          const asked = [], sheets = [], actualOpenSheet = openSheet;
          openSheet = (...args) => {const sheet = actualOpenSheet(...args); sheets.push(sheet); return sheet;};
          const day = (on, extra = {}) => ({on, at: `${on}T03:00:00+10:00`, price: "9.00", stock: 1, in_stock: true,
            set: "ltc", number: "12", finish: "foil", listed: true, elsewhere: false, partial: false, lowest: false, ...extra});
          api = async path => {
            asked.push(path);
            return {name: "Sol Ring", queued: true, scope: "LTC 12 foil", shops: [
              {shop: "Games Portal", counts_stock: false, days: [day("2026-11-01", {lowest: true}),
                day("2026-11-02", {price: null, stock: null, in_stock: false, listed: false, elsewhere: true, set: null,
                  number: null, finish: null}),
                day("2026-11-03", {price: null, stock: null, in_stock: false, listed: false, set: null, number: null,
                  finish: null, partial: true})]}]};
          };
          draw([row("Other", {queue_row: 1, shop_snapshot: null}),
            row("Sol Ring", {queue_row: 2, printing: "exact", set: "ltc", collector_number: "12", finish: "foil",
              shop_snapshot: snap()})]);
          queueRow("Sol Ring").querySelector(".shop-history-open").click(); await null; await null; await null; await null;
          same(asked, ["/api/shopping/price-history?name=Sol%20Ring&row=2"]);
          const body = sheets.at(-1).body;
          assert(body.querySelector("[data-shop-history-scope]").textContent.includes("own printing and finish: LTC 12 foil"),
            body.textContent);
          const days = body.querySelectorAll("tr").map(tr => tr.querySelectorAll("td").map(td => td.textContent)).filter(d => d.length);
          same(days.map(d => d[2]), ["not listed; first page only, more results not read", "listed, but not in this printing",
            "in stock"]);
          const printing = body.querySelectorAll("tr").map(tr => tr.querySelectorAll("td")).filter(cells => cells.length).at(-1)[3];
          assert.equal(printing.querySelector("span").textContent, "LTC 12 foil");
          assert.equal(printing.querySelector("small").textContent, "Condition unknown, language unknown");
        """)

    def test_an_any_printing_history_says_so(self):
        self.run_snapshot_js("""
          const sheets = [], actualOpenSheet = openSheet;
          openSheet = (...args) => {const sheet = actualOpenSheet(...args); sheets.push(sheet); return sheet;};
          api = async () => ({name: "Sol Ring", queued: true, scope: "any printing", shops: []});
          draw([row("Sol Ring", {queue_row: 1, shop_snapshot: snap()})]);
          queueRow("Sol Ring").querySelector(".shop-history-open").click(); await null; await null; await null; await null;
          assert(sheets.at(-1).body.querySelector("[data-shop-history-scope]").textContent.includes("Read as any printing"));
        """)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class MissingCardFirstPageTests(unittest.TestCase):
    run_js = test_shopping_snapshot_ui.ShoppingSnapshotTests.run_js

    def test_a_missing_cards_first_page_only_evidence_says_so_and_an_unknown_never_does(self):
        self.run_js("""
          const snap = (extra = {}) => ({shop: "Games Portal", scope: "nonfoil", status: "in_stock",
            fetched_at: "2026-11-02T03:05:00+11:00", price_aud: "0.25", stock: 1, set: "fdn", collector_number: "100",
            finish: "nonfoil", url: null, in_stock_printings: 1, error: null, back_in_stock: false, newly_in_stock: false,
            carried: false, ...extra});
          const said = extra => shopMissingSnapshotLine({shop_snapshots: [snap(extra)]}, {short: true}).textContent;
          assert(said({partial: true}).includes("first page only, more results not read"), said({partial: true}));
          assert(said({status: "not_listed", price_aud: null, stock: null, set: null, collector_number: null, finish: null,
            partial: true}).includes("Games Portal: no nonfoil listed"));
          assert(said({status: "not_listed", price_aud: null, stock: null, set: null, collector_number: null, finish: null,
            partial: true}).includes("first page only, more results not read"));
          for (const extra of [{}, {partial: false}, {partial: "true"}, {status: "unknown", partial: true}])
            assert(!said(extra).includes("first page only"), JSON.stringify(extra));
        """)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class BasketAccuracyTests(unittest.TestCase):
    run_js = test_shopping_baskets_ui.ShoppingBasketsTests.run_js
    run_baskets_js = test_shopping_baskets_ui.ShoppingBasketsTests.run_baskets_js

    def test_a_first_page_only_row_and_reason_say_so(self):
        self.run_baskets_js(r"""
          drawShopping(answer({shops: [
            basket('mtgmate', 'MTGMate', {rows: [line('Sol Ring', 1)], total_aud: '1.00', priced: 1, cards: 1}),
            basket('gamesportal', 'Games Portal', {rows: [line('Sol Ring', 1, {partial: true,
              listing: {set: 'fdn', collector_number: '1', finish: 'nonfoil', price_aud: '1.00', stock: null, url: null}})],
              unconfirmed: [line('Blank', 3, {status: 'unconfirmed', partial: true})],
              total_aud: '1.00', priced: 1, cards: 1, partial: 2})],
            unavailable: [{queue_row: 2, name: 'Rare Thing', quantity: '1', state: 'ready', shops: [
              {shop: 'MTGMate', status: 'not_matched', shop_sets: ['c16', 'cmm'], partial: false},
              {shop: 'Games Portal', status: 'not_listed', shop_sets: [], partial: true}]},
              {queue_row: 4, name: 'Treasure', quantity: '2', state: 'ready', is_token: true, shops: [
              {shop: 'MTGMate', status: 'token', shop_sets: [], partial: false}]}]}));
          const mtg = shopNode('mtgmate'), gp = shopNode('gamesportal');
          assert(!mtg.textContent.includes('first page only'));
          assert(gp.querySelector('[data-basket-partial]').textContent.includes('first page only, more results not read'));
          assert(gp.querySelector('[data-basket-gap="unconfirmed"]').textContent.includes('Blank (first page only, more results not read)'));
          const gone = section().querySelectorAll('[data-basket-unavailable]');
          assert(gone[0].textContent.includes("MTGMate: listed, but not matched to your printing (the shop's sets: C16, CMM)"),
            gone[0].textContent);
          assert(gone[0].textContent.includes('Games Portal: not listed, first page only, more results not read'), gone[0].textContent);
          assert(gone[1].textContent.includes("MTGMate: token cards aren't checked at this shop"), gone[1].textContent);
        """)


if __name__ == "__main__":
    unittest.main()
