"""MTGMate's daily snapshot beside the queue's recorded reference (E5-S08) and the back-in-stock mark (E5-S19)."""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingSnapshotTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_snapshot_js(self, scenario):
        self.run_js("""
          state.may = {admin: true, orders: true, see_inventory: ["home"]};
          const snap = (extra = {}) => ({shop: "MTGMate", status: "in_stock", fetched_at: "2026-10-28T03:05:00+11:00",
            price_aud: "4.50", stock: 2, set: "40k", collector_number: "249", finish: "nonfoil",
            url: "https://www.mtgmate.com.au/cards/Sol_Ring/40K/249", in_stock_printings: 2, error: null,
            back_in_stock: false, newly_in_stock: false, ...extra});
          const draw = queue => drawShopping({...empty, queue_revision: "q1", to_buy: queue, queue_decks: [],
            missing_cards: {ready: true, rows: [], errors: [], warnings: [], totals: {}},
            shop_snapshot: {shop: "MTGMate", fetched_at: "2026-10-28T03:40:00+11:00"}});
          const queueRow = name => main.querySelectorAll("[data-shop-queue]").find(node =>
            node.querySelector(".card-row")?.querySelector(".name")?.textContent.startsWith(name));
          toast = () => {};
        """ + scenario)

    def test_snapshot_sits_beside_the_reference_with_its_fetch_time(self):
        self.run_snapshot_js("""
          draw([row("Sol Ring", {queue_row: 1, listed_aud: "6.00", listed_at: "Card shop", checked: "2026-10-01",
            shop_snapshot: snap()})]);
          const node = queueRow("Sol Ring");
          assert(node.textContent.includes("Reference price A$6.00 at Card shop"));
          const line = node.querySelector(".shop-snapshot");
          assert(line, "the snapshot line is shown");
          assert(line.textContent.includes("MTGMate: A$4.50, 2 in stock"));
          assert.equal(line.querySelector("time").getAttribute("datetime"), "2026-10-28T03:05:00+11:00");
          assert.equal(line.querySelector("a").getAttribute("href"), "https://www.mtgmate.com.au/cards/Sol_Ring/40K/249");
          assert(!node.getAttribute("class").includes("shop-queue-back"));
        """)

    def test_unknown_and_unlisted_never_show_a_price(self):
        self.run_snapshot_js("""
          draw([row("Alpha", {queue_row: 1, shop_snapshot: snap({status: "unknown", price_aud: null, stock: null,
              set: null, url: null, error: "MTGMate couldn't be reached"})}),
            row("Beta", {queue_row: 2, shop_snapshot: snap({status: "not_listed", price_aud: null, set: null, url: null})}),
            row("Gamma", {queue_row: 3, shop_snapshot: null})]);
          assert(queueRow("Alpha").querySelector(".shop-snapshot").textContent.includes("price unknown"));
          assert(!queueRow("Alpha").querySelector(".shop-snapshot").textContent.includes("A$"));
          assert(queueRow("Beta").querySelector(".shop-snapshot").textContent.includes("not listed"));
          assert.equal(queueRow("Gamma").querySelector(".shop-snapshot"), null);
        """)

    def test_a_waiting_row_back_in_stock_is_marked(self):
        self.run_snapshot_js("""
          draw([row("Sol Ring", {queue_row: 1, state: "waiting_for_stock", in_stock: "no",
            shop_snapshot: snap({back_in_stock: true, newly_in_stock: true})})]);
          const node = queueRow("Sol Ring");
          assert(node.getAttribute("class").includes("shop-queue-back"));
          assert(node.querySelector(".shop-snapshot").textContent.includes("Back in stock"));
        """)

    def test_an_unexpected_link_is_not_followed(self):
        self.run_snapshot_js("""
          draw([row("Sol Ring", {queue_row: 1, shop_snapshot: snap({url: "https://example.com/x"})})]);
          assert.equal(queueRow("Sol Ring").querySelector(".shop-snapshot a"), null);
        """)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingPriceHistoryTests(unittest.TestCase):
    """E5-S29: a queued row's Price history (shopping-history.js), asked only when opened."""
    run_snapshot_js = ShoppingSnapshotTests.run_snapshot_js
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def test_price_history_opens_a_sheet_with_the_lowest_first_and_the_days_newest_first(self):
        self.run_snapshot_js("""
          const asked = [], sheets = [], actualOpenSheet = openSheet;
          openSheet = (...args) => {const sheet = actualOpenSheet(...args); sheets.push(sheet); return sheet;};
          const day = (on, price, extra = {}) => ({on, at: `${on}T03:00:00+10:00`, price, stock: 2, in_stock: true,
            set: "40k", number: "249", finish: "nonfoil", listed: true, lowest: false, ...extra});
          api = async path => {
            asked.push(path);
            return {name: "Sol Ring", queued: true, shops: [
              {shop: "MTGMate", counts_stock: true, days: [day("2026-11-01", "4.00"), day("2026-11-02", "3.50", {lowest: true}),
                day("2026-11-03", "3.00", {in_stock: false, stock: 0})]},
              {shop: "Games Portal", counts_stock: false, days: []}]};
          };
          draw([row("Sol Ring", {queue_row: 1, shop_snapshot: snap()}), row("Gamma", {queue_row: 2, shop_snapshot: null})]);
          assert.equal(queueRow("Gamma").querySelector(".shop-history-open"), null, "no snapshot, no history button");
          const button = queueRow("Sol Ring").querySelector(".shop-history-open");
          assert(button, "a row with a snapshot has Price history");
          assert.equal(asked.length, 0, "nothing is asked until it's opened");
          button.click(); await null; await null; await null; await null;
          same(asked, ["/api/shopping/price-history?name=Sol%20Ring"]);
          const sheet = sheets.at(-1);
          const mate = sheet.body.querySelector('[data-shop-history="MTGMate"]');
          assert(mate.querySelector(".shop-history-lowest").textContent.includes("Lowest in stock: A$3.50 on 2 Nov"),
            mate.textContent);
          const days = mate.querySelectorAll("tr").map(tr => tr.querySelectorAll("td").map(td => td.textContent)).filter(d => d.length);
          same(days.map(d => d[0]), ["3 Nov", "2 Nov", "1 Nov"], "newest first");
          assert.equal(days[0][2], "out of stock");
          assert.equal(days[1][2], "2 in stock");
          const portal = sheet.body.querySelector('[data-shop-history="Games Portal"]');
          assert(portal.textContent.includes("No earlier readings"), portal.textContent);
        """)
