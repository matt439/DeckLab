"""Buying views use current purchase intent and never turn incomplete counts into an empty list."""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingBuyingInteractionTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_buying_js(self, scenario):
        self.run_js("""
          state.may = {admin: true, orders: true, see_inventory: ["home"]};
          const cardData = name => ({name, type_line: "Creature", mana_cost: "",
            img_small: "/img/fdn/1/small", img: "/img/fdn/1/normal"});
          const deckData = (id, title, missing = 1) => ({id: `casual/${id}`, title, missing});
          const missingRow = (name, extra = {}) => ({name, missing: 2,
            decks: [deckData("otters", "Otters", 2)], queue: [], card: null, ...extra});
          const shoppingData = (queue = [], missing = [], extra = {}) => ({...empty,
            queue_revision: "q1", to_buy: queue, queue_decks: [],
            missing_cards: {ready: true, rows: missing, errors: [], warnings: [], totals: {}}, ...extra});
          const missingSection = () => main.querySelector("#shop-missing-cards")?.closest("section");
          const shopSectionNode = () => main.querySelector("#shop-by-shop")?.closest("section");
          const chooseShop = choice => {
            const select = main.querySelector("#shop-buying-store");
            const fold = select.closest("details");
            if (fold) {fold.setAttribute("open", ""); fold.open = true; fold.fire("toggle");}
            select.value = choice; select.fire("change");
            return select;
          };
          const missingArticle = name => main.querySelectorAll(".shop-missing-card")
            .find(article => article.getAttribute("data-missing-card") === name);
          const editControl = n => main.querySelectorAll(".shop-queue-edit")
            .find(button => Number(button.dataset.queueRow) === n);
          const field = (sheet, name) => sheet.dialog.querySelector(`[data-queue-field=${name}]`);
          const sheetButton = (sheet, name) => sheet.dialog.querySelectorAll("button")
            .find(button => button.textContent === name);
          toast = () => {};
        """ + scenario)

    def test_combined_card_is_once_with_each_decks_shortfall_and_separate_navigation(self):
        self.run_buying_js("""
          drawShopping(shoppingData([], [missingRow("Alpha", {missing: 5, card: cardData("Alpha"),
            decks: [deckData("otters", "Otters", 2), deckData("elves", "Elves", 3)]})]));
          const section = missingSection(), rows = section.querySelectorAll(".shop-missing-card");
          assert.equal(rows.length, 1);
          assert(rows[0].textContent.includes("5 copies missing across 2 decks"));
          same(rows[0].querySelector(".shop-missing-decks").querySelectorAll("li").map(li => li.textContent),
            ["Otters: 2", "Elves: 3"]);
          const links = rows[0].querySelectorAll("a");
          same(links.map(link => link.getAttribute("href")), [
            "#/deck?id=casual%2Fotters&v=target&tab=cards&filter=missing",
            "#/deck?id=casual%2Felves&v=target&tab=cards&filter=missing"]);
          assert(links.every(link => link.closest("button") === null));
          assert.equal(rows[0].querySelector(".card-row").querySelector("a"), null);
          rows[0].querySelector(".card-row").click();
          assert.equal(inspections.at(-1).card.name, "Alpha");
          assert(section.textContent.includes("Shared collection copies may count for more than one deck"));
        """)

    def test_all_queue_categories_annotate_shortfalls_without_suggesting_duplicates(self):
        self.run_buying_js("""
          const queue = SHOP_QUEUE_STATES.map((state, i) => row("Alpha", {queue_row: i + 1,
            state, quantity: i + 1, for: `Deck ${i}`, printing: "exact", set: "fdn", collector_number: "7",
            finish: "foil", listed_at: "Card shop", listed_aud: "0.50", checked: "2026-10-14", in_stock: "no"}));
          drawShopping(shoppingData(queue, [missingRow("Alpha", {queue: queue.map(item => ({...item}))})]));
          const article = missingArticle("Alpha"), intent = article.querySelector(".shop-missing-queue");
          assert.equal(intent.querySelectorAll("li").length, 5);
          for (const label of ["Ready to buy", "Waiting for stock", "Waiting for reprint", "Deferred", "Long-term plan"])
            assert(intent.textContent.includes(label));
          assert(intent.textContent.includes("5 queued"));
          assert(intent.textContent.includes("Exact: FDN 7 foil"));
          assert(intent.textContent.includes("Reference price A$0.50 at Card shop"));
          assert(intent.textContent.includes("Checked 2026-10-14"));
          assert(intent.textContent.includes("Out of stock when checked"));
          assert(!article.textContent.includes("Not in the purchase queue"));
          assert.equal(article.querySelectorAll("button").length, 0);
          assert.equal(article.querySelector("img"), null);
        """)

    def test_same_name_token_never_annotates_a_playable_shortfall_even_after_redraw(self):
        self.run_buying_js("""
          const token = row("Goblin", {queue_row: 1, is_token: true, quantity: 8, listed_at: "Store"});
          const historical = row("GOBLIN", {quantity: 2});
          const view = drawShopping(shoppingData([token], [missingRow("Goblin", {queue: [historical]})]));
          assert(missingArticle("Goblin").textContent.includes("Not in the purchase queue"));
          assert.equal(missingArticle("Goblin").querySelector(".shop-missing-queue"), null);
          view.data.to_buy.push(row("goblin", {queue_row: 2, quantity: 3, listed_at: "Store"}));
          view.redraw();
          const intent = missingArticle("Goblin").querySelector(".shop-missing-queue");
          assert.equal(intent.querySelectorAll("li").length, 1);
          assert(intent.textContent.includes("3 queued"));
          assert(!intent.textContent.includes("8 queued"));
          assert.equal(shopSectionNode().querySelectorAll(".shop-store-row").length, 2);
        """)

    def test_unavailable_counts_show_a_retry_and_never_claim_nothing_to_buy(self):
        self.run_buying_js("""
          let refreshes = 0;
          route = () => {refreshes += 1;};
          apiWrite = async () => {throw new Error("A count refresh must not write");};
          drawShopping(shoppingData([], [], {missing_cards: {ready: false, rows: [], errors: [], warnings: []}}));
          const section = missingSection();
          assert(section.textContent.includes("Missing cards could not be counted"));
          assert.equal(main.querySelector(".shop-empty").hidden, true);
          assert.equal(section.querySelector("[role=status]").querySelector("button").textContent, "Refresh missing cards");
          section.querySelector("[role=status]").querySelector("button").click();
          assert.equal(refreshes, 1);
        """)

    def test_partial_counts_preserve_successes_errors_and_review_warnings(self):
        self.run_buying_js("""
          drawShopping(shoppingData([], [], {missing_cards: {ready: false,
            rows: [missingRow("Alpha")], errors: [{id: "casual/broken", title: "Broken deck", message: "Unknown card"},
              {message: "Collection not available"}], warnings: ["One deck has no Planned list"]}}));
          const section = missingSection();
          assert(section.textContent.includes("Missing-card counts are incomplete"));
          assert.equal(section.querySelectorAll(".shop-missing-card").length, 1);
          const errors = section.querySelector(".shop-count-errors");
          assert(errors.textContent.includes("Broken deck: Unknown card"));
          assert(errors.textContent.includes("Collection not available"));
          assert.equal(errors.querySelector("a").getAttribute("href"), "#/deck?id=casual%2Fbroken&v=target");
          assert(section.textContent.includes("One deck has no Planned list"));
          assert.equal(main.querySelector(".shop-empty").hidden, true);
        """)

    def test_ready_answer_with_only_errors_is_not_hidden_or_a_false_empty_state(self):
        self.run_buying_js("""
          drawShopping(shoppingData([], [], {missing_cards: {ready: true, rows: [],
            errors: [{message: "A deck could not be counted"}], warnings: []}}));
          assert(missingSection().textContent.includes("A deck could not be counted"));
          assert.equal(main.querySelector(".shop-empty").hidden, true);
          clear(main);
          drawShopping(shoppingData());
          assert.equal(missingSection(), undefined);
          assert.equal(main.querySelector(".shop-empty").hidden, false);
          assert.equal(shopSectionNode(), undefined);
        """)

    def test_shop_groups_include_long_term_and_keep_stock_yes_no_unknown_separate(self):
        self.run_buying_js("""
          drawShopping(shoppingData([
            row("In stock", {listed_at: "Beta", in_stock: "yes"}),
            row("Out of stock", {listed_at: "Beta", in_stock: "no"}),
            row("Unknown", {listed_at: "Beta", in_stock: ""}),
            row("Later", {listed_at: "Alpha", in_stock: "yes", state: "long_term"}),
            row("Unresearched", {listed_at: "   ", in_stock: ""})]));
          const section = shopSectionNode(), groups = section.querySelectorAll(".shop-store-group");
          same(groups.map(group => group.querySelector("h3").textContent), ["Alpha", "Beta", "Not checked at any shop"]);
          assert(groups[0].textContent.includes("Later"));
          assert(groups[0].textContent.includes("Long-term plan"));
          same(groups[1].querySelectorAll("h4").map(heading => heading.textContent),
            ["In stock when checked", "Out of stock when checked", "Stock not recorded"]);
          assert.equal(groups[1].querySelectorAll(".shop-store-row").length, 3);
          assert(groups[2].textContent.includes("Unresearched"));
          assert(section.textContent.includes("check the shop before ordering"));
        """)

    def test_shop_selection_filters_recorded_research_without_writing(self):
        self.run_buying_js("""
          apiWrite = async () => {throw new Error("Selecting a shop must not write");};
          const alpha = row("Alpha", {listed_at: "Store A", checked: "2026-10-13", listed_aud: "1.25"});
          drawShopping(shoppingData([alpha, row("Beta", {listed_at: "Store B"}), row("Gamma")]));
          chooseShop("shop:Store B");
          assert.equal(shopSectionNode().querySelectorAll(".shop-store-group").length, 1);
          assert(shopSectionNode().querySelector(".shop-store-results").textContent.includes("Beta"));
          assert(!shopSectionNode().querySelector(".shop-store-results").textContent.includes("Alpha"));
          chooseShop("unchecked");
          assert(shopSectionNode().querySelector(".shop-store-results").textContent.includes("Gamma"));
          chooseShop("all");
          assert.equal(shopSectionNode().querySelectorAll(".shop-store-row").length, 3);
          assert.equal(alpha.listed_aud, "1.25");
          assert.equal(alpha.checked, "2026-10-13");
        """)

    def test_reference_price_and_check_date_are_visible_without_card_data_or_image(self):
        self.run_buying_js("""
          drawShopping(shoppingData([
            row("Zero", {listed_at: "Store", listed_aud: "0", checked: "2026-10-14"}),
            row("Undated", {listed_at: "Store", listed_aud: "1.10"}),
            row("Unpriced", {listed_at: "Store", checked: "2026-10-12"}),
            row("Unrecorded", {listed_at: "Store"})]));
          const research = shopSectionNode();
          assert.equal(research.querySelector("img"), null);
          assert(research.textContent.includes("Reference price A$0.00 at Store"));
          assert(research.textContent.includes("Checked 2026-10-14"));
          assert(research.textContent.includes("Check date not recorded"));
          assert(research.textContent.includes("Checked 2026-10-12; reference price not recorded"));
          assert(research.textContent.includes("Check date and reference price not recorded"));
          const queue = main.querySelector("#shop-to-buy").closest("section");
          assert(queue.textContent.includes("Checked 2026-10-14"));
          assert(queue.textContent.includes("Reference price A$0.00 at Store"));
        """)

    def test_untrusted_names_decks_shops_errors_and_notes_remain_text(self):
        self.run_buying_js("""
          const bad = "<img src=x onerror=alert(1)>";
          drawShopping(shoppingData([row(bad, {for: "<b>For deck</b>", listed_at: "<script>shop</script>",
            listed_aud: "1.00", checked: "<b>date</b>", notes: "<button>Do not run</button>",
            deck: {id: "casual/safe", title: "<b>Queue deck</b>"}})],
            [missingRow(bad, {decks: [deckData("safe", "<b>Deck</b>")]})],
            {missing_cards: {ready: false, rows: [missingRow(bad, {decks: [deckData("safe", "<b>Deck</b>")]})],
              errors: [{message: "<b>Error</b>"}],
              warnings: ["<b>Warning</b>"]}}));
          assert(main.textContent.includes(bad));
          assert(main.textContent.includes("<script>shop</script>"));
          assert(main.textContent.includes("<b>Error</b>"));
          assert(main.textContent.includes("<b>Warning</b>"));
          assert(main.textContent.includes("<b>Deck</b>"));
          assert(main.textContent.includes("<b>Queue deck</b>"));
          assert.equal(main.querySelector("script"), null);
          assert.equal(main.querySelector("img"), null);
          assert.equal(main.querySelector("b"), null);
        """)

    def test_adding_a_card_redraws_missing_annotations_from_saved_current_rows(self):
        self.run_buying_js("""
          const writes = [];
          apiWrite = async (path, body) => {writes.push([path, body]); return {revision: "q2",
            item: row("Alpha", {...body.values})};};
          const view = drawShopping(shoppingData([], [missingRow("Alpha")]));
          assert(missingArticle("Alpha").textContent.includes("Not in the purchase queue"));
          const sheet = shopQueueSheet(view);
          field(sheet, "name").value = "Alpha"; field(sheet, "quantity").value = "3";
          sheetButton(sheet, "Add card").click(); await null; await null;
          assert(missingArticle("Alpha").textContent.includes("3 queued"));
          assert(!missingArticle("Alpha").textContent.includes("Not in the purchase queue"));
          assert.equal(view.data.missing_cards.rows[0].queue.length, 0);
          assert.equal(view.data.to_buy[0].queue_row, 1);
          assert.equal(view.data.queue_revision, "q2");
          assert.equal(writes[0][0], "/api/shopping/queue");
          assert.equal(writes[0][1].expect, "q1");
          assert(shopSectionNode().textContent.includes("Alpha"));
        """)

    def test_edit_redraws_quantities_and_references_but_preserves_chosen_shop(self):
        self.run_buying_js("""
          const queued = row("Alpha", {queue_row: 1, quantity: 1, listed_at: "Store A", listed_aud: "0.50",
            checked: "2026-10-14"});
          const old = {...queued};
          apiWrite = async (path, body) => ({revision: "q2", item: {...queued, ...body.values}});
          const view = drawShopping(shoppingData([queued, row("Beta", {queue_row: 2, listed_at: "Store B"})],
            [missingRow("Alpha", {queue: [old]})]));
          chooseShop("shop:Store A");
          const sheet = shopQueueSheet(view, queued);
          field(sheet, "quantity").value = "4";
          sheetButton(sheet, "Save").click(); await null; await null;
          assert(missingArticle("Alpha").textContent.includes("4 queued"));
          assert(!missingArticle("Alpha").textContent.includes("1 queued"));
          assert.equal(main.querySelector("#shop-buying-store").value, "shop:Store A");
          assert.equal(shopSectionNode().querySelectorAll(".shop-store-row").length, 1);
          assert(shopSectionNode().textContent.includes("Reference price A$0.50 at Store A"));
          assert.equal(old.quantity, 1);
        """)

    def test_metadata_edit_keeps_positive_token_evidence_when_card_cache_is_unavailable(self):
        self.run_buying_js("""
          const queued = row("Goblin", {queue_row: 1, is_token: true, quantity: 1, printing: "exact",
            set: "tfdn", collector_number: "1", finish: "nonfoil", listed_at: "Store", card: null});
          apiWrite = async (path, body) => {
            const item = {...queued, ...body.values, card: null};
            delete item.is_token;   // An unavailable index supplies no new classification evidence.
            return {revision: "q2", item};
          };
          const view = drawShopping(shoppingData([queued], [missingRow("Goblin")]));
          const sheet = shopQueueSheet(view, queued);
          field(sheet, "quantity").value = "4";
          field(sheet, "notes").value = "Keep this paired token printing";
          sheetButton(sheet, "Save").click(); await null; await null;
          assert.equal(queued.quantity, 4);
          assert.equal(queued.is_token, true);
          assert.equal(queued.notes, "Keep this paired token printing");
          assert.equal(view.data.queue_revision, "q2");
          assert(missingArticle("Goblin").textContent.includes("Not in the purchase queue"));
          assert.equal(missingArticle("Goblin").querySelector(".shop-missing-queue"), null);
          assert.equal(shopSectionNode().querySelectorAll(".shop-store-row").length, 1);
        """)

    def test_corrected_playable_identity_clears_old_token_evidence_before_redrawing_shortfalls(self):
        self.run_buying_js("""
          const queued = row("Goblin", {queue_row: 1, is_token: true, quantity: 2, printing: "exact",
            set: "tfdn", collector_number: "1", finish: "nonfoil", listed_at: "Store", card: null});
          const writes = [];
          apiWrite = async (path, body) => {
            writes.push(body);
            const item = {...queued, ...body.values, card: cardData("Goblin")};
            delete item.is_token;   // A positively identified playable card has no token marker.
            return {revision: "q2", item};
          };
          const view = drawShopping(shoppingData([queued], [missingRow("Goblin")]));
          assert(missingArticle("Goblin").textContent.includes("Not in the purchase queue"));
          const sheet = shopQueueSheet(view, queued);
          const saved = await shopSaveQueue(view, sheet, sheet.queueError, {action: "edit", row: 1,
            values: {set: "fdn", collector_number: "124", finish: "nonfoil", quantity: 3}}, queued);
          assert.equal(saved, true);
          assert.equal(queued.is_token, undefined);
          assert.equal(queued.set, "fdn");
          assert.equal(queued.collector_number, "124");
          assert(missingArticle("Goblin").textContent.includes("3 queued"));
          assert(!missingArticle("Goblin").textContent.includes("Not in the purchase queue"));
          assert.equal(view.data.queue_revision, "q2");
          assert.equal(writes[0].expect, "q1");
          shopSectionNode().querySelector(".card-row").click();
          assert.equal(inspections.at(-1).card.name, "Goblin");
        """)

    def test_move_redraws_missing_state_and_includes_long_term_at_the_selected_shop(self):
        self.run_buying_js("""
          const queued = row("Alpha", {queue_row: 1, listed_at: "Store", listed_aud: "1.00"});
          apiWrite = async () => ({revision: "q2"});
          const view = drawShopping(shoppingData([queued], [missingRow("Alpha", {queue: [{...queued}]})]));
          chooseShop("shop:Store");
          await shopMoveQueue(queued, "long_term", view, el("div"));
          assert.equal(main.querySelector("#shop-to-buy"), null);
          assert(missingArticle("Alpha").textContent.includes("Long-term plan"));
          assert(!missingArticle("Alpha").textContent.includes("Ready to buy"));
          assert(shopSectionNode().querySelector(".shop-store-results").textContent.includes("Alpha"));
          assert(shopSectionNode().querySelector(".shop-store-results").textContent.includes("Long-term plan"));
          assert.equal(main.querySelector("#shop-buying-store").value, "shop:Store");
        """)

    def test_shop_fold_and_selection_survive_saved_edits_and_moves_but_respect_explicit_close(self):
        self.run_buying_js("""
          const queued = row("Alpha", {queue_row: 1, listed_at: "Store", quantity: 1});
          apiWrite = async (path, body) => ({revision: body.state ? "q3" : "q2",
            item: {...queued, ...body.values}});
          const view = drawShopping(shoppingData([queued]));
          chooseShop("shop:Store");
          const sheet = shopQueueSheet(view, queued);
          field(sheet, "quantity").value = "2";
          sheetButton(sheet, "Save").click(); await null; await null;
          assert.equal(main.querySelector("#shop-buying-store").value, "shop:Store");
          assert.equal(shopSectionNode().querySelector("details").getAttribute("open"), "");
          await shopMoveQueue(queued, "long_term", view, el("div"));
          assert.equal(main.querySelector("#shop-buying-store").value, "shop:Store");
          const fold = shopSectionNode().querySelector("details");
          assert.equal(fold.getAttribute("open"), "");
          fold.removeAttribute("open"); fold.open = false; fold.fire("toggle");
          view.redraw();
          assert.equal(shopSectionNode().querySelector("details").getAttribute("open"), null);
          assert.equal(main.querySelector("#shop-buying-store").value, "shop:Store");
        """)

    def test_remove_drops_old_annotations_resets_missing_shop_and_renumbers_current_edit_ids(self):
        self.run_buying_js("""
          const first = row("Alpha", {queue_row: 1, listed_at: "Only alpha", quantity: 3});
          const second = row("Beta", {queue_row: 2, listed_at: "Other"});
          const writes = [];
          apiWrite = async (path, body) => {writes.push(body); return {revision: "q2"};};
          const view = drawShopping(shoppingData([first, second], [missingRow("Alpha", {queue: [{...first}]})]));
          chooseShop("shop:Only alpha");
          const parent = shopQueueSheet(view, first), sheet = shopRemoveQueueSheet(view, first, parent);
          field(sheet, "reason").value = "Changed plan";
          sheetButton(sheet, "Remove card").click(); await null; await null; await null;
          assert(missingArticle("Alpha").textContent.includes("Not in the purchase queue"));
          assert(!missingArticle("Alpha").textContent.includes("3 queued"));
          assert.equal(main.querySelector("#shop-buying-store").value, "all");
          assert(!shopSectionNode().textContent.includes("Only alpha"));
          same(view.data.to_buy.map(item => [item.name, item.queue_row]), [["Beta", 1]]);
          assert.equal(editControl(2), undefined);
          editControl(1).click();
          const last = [...shopQueueSheets].at(-1);
          assert.equal(last.heading.textContent, "Beta");
          same(writes, [{action: "remove", row: 1, reason: "Changed plan", expect: "q1"}]);
        """)

    def test_read_only_views_keep_research_deck_links_and_viewers_without_write_controls(self):
        self.run_buying_js("""
          state.may = {admin: false, orders: false, see_inventory: ["home"]};
          apiWrite = async () => {throw new Error("A read-only buying view must not write");};
          drawShopping(shoppingData([row("Alpha", {queue_row: 1, listed_at: "Store", card: cardData("Alpha"),
            deck: {id: "casual/otters", title: "Otters"}})], [missingRow("Alpha", {card: cardData("Alpha")})]));
          assert.equal(main.querySelector(".shop-queue-write"), null);
          chooseShop("shop:Store");
          const research = shopSectionNode(), link = research.querySelector(".shop-queue-deck");
          assert.equal(link.getAttribute("href"), "#/deck?id=casual%2Fotters&v=target");
          assert.equal(link.closest("button"), null);
          research.querySelector(".card-row").click();
          assert.equal(inspections.at(-1).card.name, "Alpha");
          assert.equal(research.querySelectorAll("button").length, 1);
          assert.equal(research.querySelector(".shop-category-move"), null);
        """)

    def test_stale_shop_selector_and_missing_refresh_ignore_changed_profile_and_route(self):
        self.run_buying_js("""
          let refreshes = 0;
          route = () => {refreshes += 1;};
          const replacedView = drawShopping(shoppingData([row("Alpha", {listed_at: "Store"})]));
          const replacedSelect = main.querySelector("#shop-buying-store");
          replacedView.redraw();
          replacedSelect.value = "shop:Store"; replacedSelect.fire("change");
          assert.equal(replacedView.shopChoice, "all");
          assert.equal(main.querySelector("#shop-buying-store").value, "all");
          for (const departure of ["profile", "route"]) {
            clear(main); state.profile = state.profiles[0];
            const view = drawShopping(shoppingData([row("Alpha", {listed_at: "Store"})], [],
              {missing_cards: {ready: false, rows: [], errors: [], warnings: []}}));
            const select = main.querySelector("#shop-buying-store");
            const refresh = missingSection().querySelector("button");
            if (departure === "profile") state.profile = state.profiles[1];
            else routeToken += 1;
            select.value = "shop:Store"; select.fire("change"); refresh.click();
            assert.equal(view.shopChoice, "all");
          }
          assert.equal(refreshes, 0);
        """)

    def test_failed_queue_write_leaves_combined_and_shop_rows_at_the_saved_revision(self):
        self.run_buying_js("""
          const queued = row("Alpha", {queue_row: 1, listed_at: "Store", quantity: 2});
          apiWrite = async () => {throw new ApiError(409, "Shopping changed meanwhile");};
          const view = drawShopping(shoppingData([queued], [missingRow("Alpha")]));
          chooseShop("shop:Store");
          const sheet = shopQueueSheet(view, queued);
          field(sheet, "quantity").value = "9";
          sheetButton(sheet, "Save").click(); await null; await null;
          assert(missingArticle("Alpha").textContent.includes("2 queued"));
          assert(!missingArticle("Alpha").textContent.includes("9 queued"));
          assert.equal(view.data.queue_revision, "q1");
          assert.equal(main.querySelector("#shop-buying-store").value, "shop:Store");
          assert(sheet.queueError.textContent.includes("Shopping changed meanwhile"));
          assert.equal(view.stale, true);
          assert.equal(editControl(1).disabled, true);
        """)


if __name__ == "__main__":
    unittest.main()
