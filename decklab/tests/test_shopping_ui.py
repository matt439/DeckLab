"""The Shopping page: deliveries on the way (seller · topic, a pictures strip, their arrival checks, Receive
delivery), follow-ups with Done, the queue, the decks still missing cards and the long-term plan."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingInteractionTests(unittest.TestCase):
    def run_js(self, scenario):
        setup = """
          clear(main);
          state.profiles = [{id: "user1", name: "User1", plays_as: "wife"}, {id: "matt", name: "Matt", plays_as: "user"}];
          state.profile = state.profiles[0];
          location.hash = "#/shopping";
          closeEditor = () => {}; stopMatchupRefresh = () => {};
          const empty = {to_buy: [], orders: [], checks: [], warnings: []};
          const component = (extra = {}) => ({id: "cards", kind: "cards", status: "pending",
            quantity: 3, rows: 2, path: "magic/orders/private.csv", ...extra});
          const order = (extra = {}) => ({id: "2026-10-08-order", seller: "Card shop",
            ordered_on: "2026-10-08", status: "pending", components: [component()], ...extra});
          const row = (name, extra = {}) => ({name, quantity: 1, state: "ready", for: "Otters", printing: "any",
            set: "", collector_number: "", finish: "", listed_aud: "", listed_at: "", in_stock: "", checked: "",
            notes: "", card: null, deck: null, ...extra});
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_shared_route_and_one_empty_state(self):
        self.run_js("""
          assert.equal(canBuildDecks(), false);
          const reads = [];
          api = async path => {reads.push(path); return empty;};
          apiWrite = async () => {throw new Error("Must not write");};
          await route();
          same(reads, ["/api/shopping"]);
          // Nothing at all: one line and the one action, no empty columns.
          assert(main.textContent.includes("Nothing to buy, and nothing on the way."));
          assert.equal(main.querySelectorAll(".shop-section").length, 0);
          assert.equal(main.querySelector(".empty").querySelector("a").getAttribute("href"), "#/wishlist");
          assert.equal(main.querySelector(".desktop-handoff"), null);
          state.profile = state.profiles[1];
          await route();
          same(reads, ["/api/shopping", "/api/shopping"]);
        """)

    def test_deliveries_are_titled_by_seller_and_topic_with_pictures_checks_and_receive(self):
        self.run_js("""
          const card = name => ({name, type_line: "Creature", mana_cost: "", img: `/img/x/${name}/normal`,
            img_small: `/img/x/${name}/small`});
          const items = n => Array.from({length: n}, (_, i) => ({name: `Card ${i}`, quantity: i ? 1 : 2, card: card(`c${i}`)}));
          drawShopping({...empty, orders: [
            order({id: "2026-10-05-ebay-goblins", seller: "eBay", components: [component({quantity: 1, items: items(1)})]}),
            order({id: "2026-10-08-examplegames", seller: "Example Games", components: [component({quantity: 15, items: items(13)})]}),
            order({id: "2026-10-05-ebay-a-walk-in-the-woods", seller: "eBay", status: "partial", components: [
              component({status: "received", received_on: "2026-10-08", items: []}),
              component({id: "tokens", kind: "tokens", quantity: 2, items: [{name: "Rabbit // Rabbit", quantity: 2, card: null}]})]}),
            order({id: "old", status: "received", components: [component({status: "received"})]})],
            checks: [{order_id: "2026-10-08-examplegames", component_id: "cards", status: "pending", text: "Look at the conditions."}]});
          const cards = main.querySelectorAll(".shop-delivery");
          same(cards.map(c => c.querySelector(".shop-delivery-title").textContent), ["eBay · Goblins", "Example Games", "eBay · A Walk in the Woods"]);
          // "On the way" once: the section says it, the cards don't.
          assert.equal(main.textContent.split("On the way").length - 1, 1);
          // A strip of 8 pictures at most (7 and "+N" past 8), 6 on a phone (5 and "+N" past 6), chosen by CSS; each
          // "+N" counts the copies not shown, and each picture opens the viewer over the strip.
          const strip = cards[1].querySelectorAll(".shop-thumb");
          assert.equal(strip.length, 9);
          const lis = cards[1].querySelector(".shop-strip").children;
          same(lis.map(li => li.getAttribute("class")), [null, null, null, null, null, "shop-wide-only", "shop-wide-only",
            "shop-narrow-only", "shop-wide-only"]);
          assert.equal(strip[7].textContent, "+8");
          assert.equal(strip[8].textContent, "+6");
          assert.equal(strip[8].getAttribute("aria-label"), "Show all 14 cards");
          assert.equal(strip[0].getAttribute("data-viewer"), "delivery-2026-10-08-examplegames");
          strip[0].click();
          assert.equal(inspections.at(-1).card.name, "c0");
          // Seven or eight printings: every picture on a wide screen, "+N" only on a phone.
          const eight = cards[0].querySelectorAll(".shop-thumb");
          assert.equal(eight.length, 1);
          // "+N" opens every card of the delivery, as rows in one viewer group.
          strip[8].click();
          const sheet = document.body.querySelectorAll(".shop-contents")[0];
          const rows = sheet.querySelectorAll(".card-row");
          assert.equal(rows.length, 13);
          assert.equal(rows[12].getAttribute("data-viewer"), "contents-2026-10-08-examplegames");
          // A payload's file path never shows, on the page or in the sheet.
          assert(!sheet.textContent.includes("private.csv"));
          // The arrival checks are inside their delivery, and Receive delivery is its action (outlined: up to
          // eight deliveries share the screen, and a view has one filled button at most).
          assert(cards[1].querySelector(".shop-checks").textContent.includes("Look at the conditions."));
          assert.equal(cards[0].querySelector(".shop-checks"), null);
          // A delivery picture names its card under the picture, so one still loading is never an empty box.
          assert.equal(strip[0].querySelector(".shop-thumb-text").textContent, "Card 0");
          // One part only (nothing to buy, no follow-ups): no row of links.
          assert.equal(main.querySelector(".shop-jumps"), null);
          const receive = cards[1].querySelectorAll("a").find((a) => a.textContent === "Receive delivery");
          assert.equal(cards[1].querySelector(".btn-primary"), null);
          assert.equal(receive.textContent, "Receive delivery");
          assert.equal(receive.getAttribute("href"), "#/receipt?order=2026-10-08-examplegames");
          // A part-received order says so, and lists its parts.
          assert(cards[2].textContent.includes("Part received"));
          assert(cards[2].textContent.includes("2 token cards"));
          assert(cards[2].textContent.includes("arrived 8 Oct"));
          // The history is folded, and no file path shows anywhere.
          const history = main.querySelector(".shop-history");
          assert.equal(history.getAttribute("open"), null);
          assert.equal(history.querySelectorAll(".shop-past").length, 1);
          assert(!main.textContent.includes("magic/orders"));
          assert(!main.textContent.includes("private.csv"));
          // Nothing queued: no To buy section.
          assert.equal(main.querySelector("#shop-to-buy"), null);
        """)

    def test_a_member_sees_delivery_details_not_receive_or_done(self):
        self.run_js("""
          state.may = {admin: false, receipts: false, orders: false, see_inventory: ["home"]};
          drawShopping({...empty, orders: [order({components: [component({items: []})]})],
            checks: [{order_id: "2026-10-08-order", component_id: "cards", status: "received", text: "Follow up"}]});
          assert.equal(main.querySelector(".btn-primary"), null);
          assert(main.textContent.includes("Delivery details"));
          // A follow-up shows, but only an admin can mark it done.
          assert(main.querySelector(".shop-followup").textContent.includes("Follow up"));
          assert.equal(main.querySelector(".shop-followup").querySelector("button"), null);
        """)

    def test_queue_prices_and_text_safety(self):
        self.run_js("""
          drawShopping({...empty, to_buy: [row("<b>Alpha</b>", {quantity: 2, state: "waiting_for_stock",
            printing: "exact", set: "fdn", collector_number: "2", finish: "foil", listed_aud: "0.50",
            listed_at: "Card shop", in_stock: "no", checked: "2026-10-08"}), row("Beta")]});
          const toBuy = main.querySelector("#shop-to-buy").closest("section");
          assert(toBuy.textContent.includes("<b>Alpha</b>"));
          assert.equal(main.querySelector("b"), null);
          assert(toBuy.textContent.includes("Waiting for stock"));
          assert(toBuy.textContent.includes("Exact: FDN 2 foil"));
          assert(toBuy.textContent.includes("A$0.50 at Card shop"));
          assert(toBuy.textContent.includes("Out of stock when checked"));
          // "Ready" is the normal case: no chip for it.
          assert(!toBuy.textContent.includes("Ready to buy"));
          assert(!main.textContent.includes("A$1.00"));
        """)

    def test_queue_links_deck_titles_without_interfering_with_the_card_viewer(self):
        self.run_js("""
          const card = {name: "Alpha", type_line: "Creature", mana_cost: "", img_small: "/img/fdn/1/small"};
          drawShopping({...empty, to_buy: [
            row("Alpha", {card, for: "Older title", deck: {id: "casual/otters", title: "Izzet Otters"}}),
            row("Beta", {for: "", deck: {id: "commander/alela", title: "<b>Alela</b>"}}),
            row("Gamma", {for: "Another project"})]});
          const queue = main.querySelector("#shop-to-buy").closest("section");
          const links = queue.querySelectorAll(".shop-queue-deck");
          same(links.map(a => [a.textContent, a.getAttribute("href")]), [
            ["Izzet Otters", "#/deck?id=casual%2Fotters&v=target"],
            ["<b>Alela</b>", "#/deck?id=commander%2Falela&v=target"]]);
          assert.equal(queue.querySelector("b"), null);
          assert(!queue.textContent.includes("Older title"));
          assert(queue.textContent.includes("Another project"));
          // Deck navigation is separate from the button opening the card viewer, with or without card data.
          const rows = queue.querySelectorAll(".card-row");
          assert.equal(rows[0].querySelector("a"), null);
          assert.equal(links[0].closest("button"), null);
          assert.equal(links[1].closest("button"), null);
          assert.equal(rows[0].getAttribute("data-viewer"), "to-buy");
          rows[0].click();
          assert.equal(inspections.at(-1).card.name, "Alpha");
          assert(rows.every(r => r.textContent.includes("Any printing")));
        """)

    def test_decks_still_missing_cards_and_the_long_term_plan(self):
        self.run_js("""
          drawShopping({...empty, decks_missing: [
            {id: "commander/alela", title: "Alela", kind: "commander", player: "user", status: "idea", missing: 62, on_the_way: 0},
            {id: "casual/otters", title: "Otters", kind: "casual", player: "either", status: "building", missing: 3, on_the_way: 2}]});
          // Built and being built first, then the ideas, each group under its heading.
          same(main.querySelectorAll(".shop-deck-group").map(g => g.querySelector("h3").textContent),
            ["Built and being built", "Ideas"]);
          // Each deck links to its missing cards (the deck page's Cards tab, filtered); zero on the way says nothing.
          const decks = main.querySelectorAll(".shop-deck");
          same(decks.map(a => a.getAttribute("href")), [
            "#/deck?id=casual%2Fotters&v=target&tab=cards&filter=missing",
            "#/deck?id=commander%2Falela&v=target&tab=cards&filter=missing"]);
          // How many are missing is words, not an alarm: no chip for it, and none for the deck being an idea.
          assert(decks[1].querySelector("small").textContent.includes("62 cards missing"));
          assert(decks[1].textContent.includes("Matt"));
          assert.equal(decks[1].querySelector(".chips"), null);
          assert(!decks[1].textContent.includes("on the way"));
          assert.equal(decks[0].querySelector(".chips").textContent, "2 on the way");
          assert(decks[0].textContent.includes("Either of you"));
          assert.equal(main.querySelectorAll(".status-crit").length, 0);
          // The long-term plan is a visible section, grouped by deck, 12 rows then "Show all".
          clear(main);
          const plan = Array.from({length: 14}, (_, i) => row(`Card ${i}`, {state: "long_term",
            deck: {id: "commander/alela", title: "Alela"}}));
          drawShopping({...empty, to_buy: [...plan, row("Lonely", {state: "long_term", for: "Later"})],
            decks_missing: [{id: "commander/alela", title: "Alela", kind: "commander", player: "user", status: "idea",
              missing: 62, on_the_way: 0}]});
          assert.equal(main.querySelector("#shop-to-buy"), null);
          assert.equal(main.querySelector(".shop-long-slot").querySelector("details"), null);
          const groups = main.querySelectorAll(".shop-group");
          assert.equal(groups.length, 2);
          assert.equal(groups[0].querySelector("a").getAttribute("href"), "#/deck?id=commander%2Falela&v=target");
          assert(groups[0].textContent.includes("14 cards"));
          assert.equal(groups[0].querySelectorAll(".card-row").length, 12);
          groups[0].querySelector(".btn-quiet").click();
          assert.equal(groups[0].querySelectorAll(".card-row").length, 14);
          assert(groups[1].textContent.includes("Later"));
          assert(main.querySelector(".shop-deck").textContent.includes("14 in the long-term plan"));
          // A row of links to the parts at the top (a phone's way to what to buy without scrolling past every
          // delivery): each part shown, with its count; the long-term plan without one.
          const jumps = main.querySelector(".shop-jumps");
          same(jumps.querySelectorAll("a").map((a) => [a.getAttribute("href"), a.textContent]),
            [["#shop-decks", "Decks missing cards"], ["#shop-by-shop", "By shop"], ["#shop-long-term", "Long-term plan"]]);
        """)

    def test_done_marks_a_follow_up_after_its_undo_time(self):
        self.run_js("""
          const writes = [];
          apiWrite = async (path, body) => { writes.push([path, body]); return {resolved: true}; };
          drawShopping({...empty, orders: [order({id: "2026-09-29-exampleshop", seller: "Example Shop", status: "received",
            components: [component({status: "received", received_on: "2026-10-02"})]})],
            checks: [{order_id: "2026-09-29-exampleshop", component_id: "cards", status: "received", text: "Check the set symbol"},
                     {order_id: "2026-09-29-exampleshop", component_id: "cards", status: "received", text: "Check the condition"}]});
          const rows = main.querySelectorAll(".shop-followup");
          assert(rows[0].textContent.includes("arrived 2 Oct"));
          // Undo puts it back and nothing is written.
          rows[0].querySelector("button").click();
          assert.equal(rows[0].hidden, true);
          document.body.querySelector("#toast-undo").querySelector("button").click();
          assert.equal(rows[0].hidden, false);
          flushTimers(); await null;
          same(writes, []);
          assert.equal(document.activeElement, rows[0].querySelector("button"));
          // Without Undo the check is marked done once the toast's time is up. One row left: no count.
          rows[1].querySelector("button").click();
          assert.equal(main.querySelector(".shop-count").hidden, true);
          // The focus moves to the next follow-up's Done, not the top of the page.
          assert.equal(document.activeElement, rows[0].querySelector("button"));
          flushTimers(); await null; await null;
          same(writes, [["/api/shopping/check", {order: "2026-09-29-exampleshop", component: "cards", check: "Check the condition"}]]);
          assert.equal(rows[1].isConnected, false);
          // A refusal puts the row back and says why.
          apiWrite = async () => { throw new ApiError(409, "Shopping changed meanwhile."); };
          let said = ""; toast = text => { said = text; };
          rows[0].querySelector("button").click();
          flushTimers(); await null; await null;
          assert.equal(rows[0].hidden, false);
          assert(said.includes("Shopping changed meanwhile."));
        """)

    def test_late_result_and_late_error_do_not_overwrite_navigation(self):
        self.run_js("""
          let finish;
          api = () => new Promise(resolve => {finish = resolve;});
          const loading = showShopping(routeToken);
          routeToken += 1;
          clear(main).append(el("p", {text: "Another page"}));
          finish(empty); await loading;
          assert.equal(main.textContent, "Another page");
          let reject;
          api = () => new Promise((resolve, failure) => {reject = failure;});
          const failing = showShopping(routeToken);
          routeToken += 1;
          clear(main).append(el("p", {text: "Another page"}));
          reject(new ApiError(500, "Bad record")); await failing;
          assert.equal(main.textContent, "Another page");
        """)

    def test_load_failure_is_visible_and_has_retry(self):
        self.run_js("""
          api = async () => {throw new ApiError(500, "The shopping records couldn't be read.");};
          await showShopping(routeToken);
          assert(main.textContent.includes("Shopping couldn't be loaded"));
          assert(main.textContent.includes("The shopping records couldn't be read."));
          assert(main.textContent.includes("Try again"));
        """)

    def test_two_dones_share_one_toast_and_one_undo(self):
        self.run_js("""
          const writes = [];
          apiWrite = async (path, body) => { writes.push(body.check); return {resolved: true}; };
          const checks = ["One", "Two", "Three"].map(text => ({order_id: "2026-09-29-exampleshop", component_id: "cards",
            status: "received", text}));
          drawShopping({...empty, orders: [order({id: "2026-09-29-exampleshop", seller: "Example Shop", status: "received",
            components: [component({status: "received", received_on: "2026-10-02"})]})], checks});
          const rows = main.querySelectorAll(".shop-followup");
          assert.equal(main.querySelector(".shop-count").textContent, "3");
          rows[0].querySelector("button").click();
          rows[1].querySelector("button").click();
          const box = document.body.querySelector("#toast-undo");
          assert(box.textContent.includes("2 checks marked done."));
          // Undo puts both back, and nothing is written.
          box.querySelector("button").click();
          assert(rows.every(r => !r.hidden));
          assert.equal(main.querySelector(".shop-count").hidden, false);
          assert.equal(main.querySelector(".shop-count").textContent, "3");
          assert.equal(document.activeElement, rows[0].querySelector("button"));
          flushTimers(); await null; await null;
          same(writes, []);
          // Two Dones without Undo: both are sent when the shared time is up.
          rows[0].querySelector("button").click();
          rows[2].querySelector("button").click();
          flushTimers(); await null; await null;
          same(writes, ["One", "Three"]);
          // The last one done: the section goes, and the focus is on the toast's Undo.
          rows[1].querySelector("button").click();
          assert.equal(main.querySelector("#shop-follow-ups").closest("section").hidden, true);
          assert.equal(document.activeElement, document.body.querySelector("#toast-undo").querySelector("button"));
        """)
