"""Both shops' snapshots on Shopping and deck Prices (E5-S08, decided 2026-10-31), over a disposable DOM.

Run with python scripts/test_fixtures.py decklab.tests.test_shops_two_shops_ui.
No live browser, shop, server, snapshot or database is accessed.
"""
import unittest

from decklab.tests import test_deck_shop_prices_ui, test_shopping_ui
from decklab.tests.test_workspace_ui import NODE

SNAPS = """
  const mtg=(extra={})=>({shop:'MTGMate',status:'in_stock',fetched_at:'2026-10-31T03:05:00+11:00',
    price_aud:'4.50',stock:2,set:'40k',collector_number:'249',finish:'nonfoil',
    url:'https://www.mtgmate.com.au/cards/Sol_Ring/40K/249',in_stock_printings:2,error:null,
    back_in_stock:false,newly_in_stock:false,...extra});
  const gp=(extra={})=>({...mtg(),shop:'Games Portal',fetched_at:'2026-10-31T03:20:00+11:00',price_aud:'3.00',stock:1,
    set:'cmm',collector_number:'410',url:'https://gamesportal.com.au/products/sol-ring-cmm?variant=9021',...extra});
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class TwoShopQueueTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_queue_js(self, scenario):
        self.run_js("""
          state.may = {admin: true, orders: true, see_inventory: ["home"]};
        """ + SNAPS + """
          const draw = queue => drawShopping({...empty, queue_revision: "q1", to_buy: queue, queue_decks: [],
            missing_cards: {ready: true, rows: [], errors: [], warnings: [], totals: {}},
            shop_snapshot: {shop: "MTGMate", fetched_at: "2026-10-31T03:40:00+11:00"},
            shop_snapshots: [{shop: "MTGMate", fetched_at: "2026-10-31T03:40:00+11:00"},
                             {shop: "Games Portal", fetched_at: "2026-10-31T03:41:00+11:00"}]});
          const queueRow = name => main.querySelectorAll("[data-shop-queue]").find(node =>
            node.querySelector(".card-row")?.querySelector(".name")?.textContent.startsWith(name));
          toast = () => {};
        """ + scenario)

    def test_each_shop_has_its_own_line_price_link_and_fetch_time(self):
        self.run_queue_js("""
          draw([row("Sol Ring", {queue_row: 1, listed_aud: "6.00", listed_at: "Card shop",
            shop_snapshot: mtg(), shop_snapshots: [mtg(), gp()]})]);
          const node = queueRow("Sol Ring");
          const lines = node.querySelectorAll(".shop-snapshot");
          assert.equal(lines.length, 2);
          assert.equal(lines[0].getAttribute("data-shop-snapshot-shop"), "MTGMate");
          assert(lines[0].textContent.includes("MTGMate: A$4.50, 2 in stock"));
          assert.equal(lines[1].getAttribute("data-shop-snapshot-shop"), "Games Portal");
          assert(lines[1].textContent.includes("Games Portal: A$3.00, in stock"), "available only, never a count");
          assert(!lines[1].textContent.includes("1 in stock"));
          assert.equal(lines[0].querySelector("time").getAttribute("datetime"), "2026-10-31T03:05:00+11:00");
          assert.equal(lines[1].querySelector("time").getAttribute("datetime"), "2026-10-31T03:20:00+11:00");
          assert.equal(lines[1].querySelector("a").getAttribute("href"), "https://gamesportal.com.au/products/sol-ring-cmm?variant=9021");
        """)

    def test_one_shop_unknown_beside_the_others_price(self):
        self.run_queue_js("""
          draw([row("Sol Ring", {queue_row: 1, shop_snapshot: mtg(),
            shop_snapshots: [mtg(), gp({status: "unknown", price_aud: null, stock: null, set: null, url: null,
              error: "Games Portal couldn't be reached"})]})]);
          const lines = queueRow("Sol Ring").querySelectorAll(".shop-snapshot");
          assert(lines[0].textContent.includes("A$4.50"));
          assert(lines[1].textContent.includes("Games Portal: price unknown"));
          assert(!lines[1].textContent.includes("A$"));
        """)

    def test_back_in_stock_at_either_shop_marks_the_row_and_its_link_stays_with_its_shop(self):
        self.run_queue_js("""
          draw([row("Sol Ring", {queue_row: 1, state: "waiting_for_stock", in_stock: "no",
            shop_snapshot: mtg({status: "out_of_stock", stock: 0}),
            shop_snapshots: [mtg({status: "out_of_stock", stock: 0}), gp({back_in_stock: true})]}),
            row("Other", {queue_row: 2, shop_snapshots: [gp({url: "https://www.mtgmate.com.au/cards/x"})]})]);
          assert(queueRow("Sol Ring").getAttribute("class").includes("shop-queue-back"));
          assert(queueRow("Sol Ring").textContent.includes("Back in stock"));
          assert.equal(queueRow("Other").querySelector(".shop-snapshot a"), null, "another shop's link is never Games Portal's");
        """)

    def test_the_lab_marker_speaks_for_both_shops(self):
        self.run_queue_js("""
          const card = row("Sol Ring", {shop_snapshot: mtg({status: "out_of_stock", stock: 0}),
            shop_snapshots: [mtg({status: "out_of_stock", stock: 0}), gp()]});
          const marker = shopSnapshotMarker(card);
          assert.equal(marker.getAttribute("data-shop-snapshot-marker"), "in_stock");
          assert(marker.getAttribute("aria-label").includes("MTGMate: out of stock"));
          assert(marker.getAttribute("aria-label").includes("Games Portal: A$3.00, in stock"));
          const single = shopSnapshotMarker(row("Sol Ring", {shop_snapshot: mtg()}));
          assert.equal(single.getAttribute("aria-label"), "MTGMate: A$4.50, 2 in stock (40K 249)");
        """)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class TwoShopMissingTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def test_missing_rows_show_every_shops_nonfoil_line(self):
        self.run_js(SNAPS + """
          const nonfoil=snap=>({...snap,scope:'nonfoil'});
          const item={name:'Sol Ring',missing:2,shop_snapshot:nonfoil(mtg()),
            shop_snapshots:[nonfoil(mtg()),nonfoil(gp())]};
          const node=shopMissingSnapshotLine(item,{short:true});
          const lines=node.querySelectorAll('.shop-missing-snapshot');
          assert.equal(lines.length,2);
          assert(lines[0].textContent.includes('MTGMate A$4.50 each, 2 in stock'));
          assert(lines[1].textContent.includes('Games Portal A$3.00 each, in stock'));
          assert.equal(lines[1].querySelector('a').getAttribute('href'),'https://gamesportal.com.au/products/sol-ring-cmm?variant=9021');
          const long=shopMissingSnapshotLine(item).querySelectorAll('.shop-missing-snapshot');
          assert(long[1].textContent.includes('Games Portal: A$3.00 each; this printing in stock when fetched.'));
          // one shop's malformed entry is unknown on its own line; a shop not checked says so
          const odd=shopMissingSnapshotLine({...item,shop_snapshots:[nonfoil(mtg()),
            {shop:'Games Portal',scope:'nonfoil',status:'not_checked',fetched_at:null}]},{short:true});
          const two=odd.querySelectorAll('.shop-missing-snapshot');
          assert(two[0].textContent.includes('MTGMate A$4.50'));
          assert(two[1].textContent.includes('Games Portal: not checked'));
          const bad=shopMissingSnapshotLine({...item,shop_snapshots:[nonfoil(mtg()),nonfoil(gp({stock:-1}))]},{short:true});
          assert(bad.querySelectorAll('.shop-missing-snapshot')[1].textContent.includes('Games Portal: price unknown'));
        """)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class TwoShopDeckPricesTests(unittest.TestCase):
    run_js = test_deck_shop_prices_ui.DeckShopPricesUiTests.run_js

    def test_deck_prices_show_both_shops_under_a_missing_card(self):
        self.run_js(SNAPS + r"""
          const owned=withShop(savedShop());
          owned.rows.find(row=>row.name==='Alpha').shop_snapshots=[savedShop(),
            savedShop({shop:'Games Portal',price_aud:'8.50',url:'https://gamesportal.com.au/products/alpha?variant=1'})];
          const table=showPrices(owned),shopRow=evidence(table);
          const lines=shopRow.querySelectorAll('.shop-missing-snapshot');
          assert.equal(lines.length,2);
          assert(lines[0].textContent.includes('MTGMate: A$9.75 each'));
          assert(lines[1].textContent.includes('Games Portal: A$8.50 each; this printing in stock when fetched.'));
          assert(shopRow.textContent.includes('each shop with its own fetch time'));
          noEffects();
        """)


if __name__ == "__main__":
    unittest.main()
