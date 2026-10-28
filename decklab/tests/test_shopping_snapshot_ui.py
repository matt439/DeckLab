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
