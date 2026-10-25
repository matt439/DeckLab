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
          const shopRadio = choice => main.querySelectorAll('.shop-store-radio')
            .find(input => input.getAttribute('data-shop-choice') === choice);
          const selectedShop = () => main.querySelectorAll('.shop-store-radio').find(input => input.checked)?.value;
          const chooseShop = choice => {
            const radio = shopRadio(choice); assert(radio, 'shop radio must exist: ' + choice);
            // The DOM double does not implement a native radio group's checked/default action.
            main.querySelectorAll('.shop-store-radio').forEach(input => { input.checked = input === radio; });
            radio.focus(); radio.fire('change'); return radio;
          };
          const sameNodes = (actual, expected) => { assert.equal(actual.length,expected.length);
            actual.forEach((node,index)=>assert.equal(node,expected[index])); };
          const canonicalQueue = () => main.querySelectorAll('[data-shop-queue]');
          const canonicalRow = name => canonicalQueue().find(node =>
            node.querySelector('.card-row')?.querySelector('.name')?.textContent.startsWith(name));
          const matchedQueue = () => canonicalQueue().filter(node => node.getAttribute('data-shop-match') === 'true');
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
          assert.equal(canonicalQueue().length, 2);
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

    def test_shop_choices_count_canonical_rows_across_states_without_duplicate_research(self):
        self.run_buying_js(r"""
          const queue=SHOP_QUEUE_STATES.map((state,i)=>row('Intent '+i,{queue_row:i+1,state,quantity:i+1,
            listed_at:'  Store A  ',in_stock:i===0?'yes':i===1?'no':''}));
          queue.push(row('Token intent',{queue_row:6,is_token:true,quantity:8,listed_at:'   '}));
          const original=queue.map(item=>({...item}));let reads=0,writes=0;
          api=async()=>{reads++;throw new Error('Shop choices must not read');};
          apiWrite=async()=>{writes++;throw new Error('Shop choices must not write');};
          drawShopping(shoppingData(queue));
          const section=shopSectionNode(),fieldset=section.querySelector('.shop-store-choices');
          assert.equal(fieldset.tag,'fieldset');assert.equal(section.querySelector('select'),null);
          assert.equal(section.querySelector('details'),null);assert.equal(section.querySelector('.card-row'),null);
          same(section.querySelectorAll('.shop-store-radio').map(input=>[input.getAttribute('type'),input.value]),
            [['radio','all'],['radio','shop:Store A'],['radio','unchecked']]);
          const label=choice=>shopRadio(choice).closest('label').textContent;
          assert(label('all').includes('6 rows'));assert(label('all').includes('23 cards'));
          assert(label('shop:Store A').includes('5 rows'));assert(label('shop:Store A').includes('15 cards'));
          assert(/1 row/.test(label('unchecked')));assert(label('unchecked').includes('8 cards'));
          assert.equal(canonicalQueue().length,6);assert.equal(selectedShop(),'all');
          assert(canonicalRow('Intent 0').textContent.includes('In stock when checked'));
          assert(canonicalRow('Intent 1').textContent.includes('Out of stock when checked'));
          assert(canonicalRow('Intent 2').textContent.includes('Stock not recorded'));
          chooseShop('shop:Store A');assert.equal(matchedQueue().length,5);
          assert.equal(canonicalQueue().length,6);assert.equal(reads,0);assert.equal(writes,0);
          same(queue,original);assert(section.textContent.includes('check the shop before ordering'));
        """)

    def test_shop_radio_marks_without_replacing_or_filtering_canonical_rows_and_clear_keeps_focus(self):
        self.run_buying_js(r"""
          let reads=0,writes=0;
          api=async()=>{reads++;throw new Error('Marking must not read');};
          apiWrite=async()=>{writes++;throw new Error('Marking must not write');};
          const alpha=row('Alpha',{queue_row:1,listed_at:'Store A',checked:'2026-10-13',listed_aud:'1.25',card:cardData('Alpha')});
          const beta=row('Beta',{queue_row:2,listed_at:'Store B'});
          drawShopping(shoppingData([alpha,beta,row('Gamma',{queue_row:3})]));
          const before=canonicalQueue(),viewer=canonicalRow('Alpha').querySelector('.card-row');
          const controls=main.querySelectorAll('.shop-queue-write'),group=viewer.getAttribute('data-viewer');
          const radio=chooseShop('shop:Store B');
          sameNodes(canonicalQueue(),before);sameNodes(main.querySelectorAll('.shop-queue-write'),controls);
          assert.equal(document.activeElement,radio);assert.equal(matchedQueue().length,1);
          assert.equal(matchedQueue()[0],canonicalRow('Beta'));
          assert.equal(canonicalRow('Alpha').querySelector('.card-row'),viewer);
          assert.equal(viewer.getAttribute('data-viewer'),group);
          assert(main.querySelector('.shop-match-slot').textContent.includes('Marking Store B rows'));
          chooseShop('unchecked');assert.equal(matchedQueue()[0],canonicalRow('Gamma'));
          assert(main.querySelector('.shop-match-slot').textContent.includes('Marking rows not checked at any shop'));
          const clearMatch=main.querySelector('.shop-clear-match');clearMatch.focus();clearMatch.click();
          assert.equal(selectedShop(),'all');assert.equal(matchedQueue().length,0);
          assert.equal(document.activeElement,shopRadio('all'));sameNodes(canonicalQueue(),before);
          viewer.click();assert.equal(inspections.at(-1).card.name,'Alpha');
          assert.equal(reads,0);assert.equal(writes,0);assert.equal(alpha.listed_aud,'1.25');assert.equal(alpha.checked,'2026-10-13');
        """)

    def test_canonical_reference_price_and_check_date_are_visible_without_card_data_or_image(self):
        self.run_buying_js("""
          drawShopping(shoppingData([
            row("Zero", {listed_at: "Store", listed_aud: "0", checked: "2026-10-14"}),
            row("Undated", {listed_at: "Store", listed_aud: "1.10"}),
            row("Unpriced", {listed_at: "Store", checked: "2026-10-12"}),
            row("Unrecorded", {listed_at: "Store"})]));
          assert(canonicalQueue().every(node=>node.querySelector('img')===null));
          assert(canonicalRow('Zero').textContent.includes('Reference price A$0.00 at Store'));
          assert(canonicalRow('Zero').textContent.includes('Checked 2026-10-14'));
          assert(canonicalRow('Undated').textContent.includes('Check date not recorded'));
          assert.equal(canonicalRow('Unpriced').querySelector('time').getAttribute('datetime'),'2026-10-12');
          assert(canonicalRow('Unpriced').textContent.includes('Reference price not recorded'));
          assert(canonicalRow('Unrecorded').textContent.includes('Check date not recorded'));
          assert(canonicalRow('Unrecorded').textContent.includes('Reference price not recorded'));
          assert.equal(shopSectionNode().querySelector('.card-row'),null);
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
          assert(canonicalRow("Alpha"));
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
          assert.equal(selectedShop(), "shop:Store A");
          assert.equal(matchedQueue().length, 1);
          assert(canonicalRow("Alpha").textContent.includes("Reference price A$0.50 at Store A"));
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
          assert.equal(canonicalQueue().length, 1);
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
          canonicalRow("Goblin").querySelector(".card-row").click();
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
          assert(canonicalRow("Alpha").closest("section").textContent.includes("Long-term plan"));
          assert.equal(matchedQueue().length, 1);
          assert.equal(selectedShop(), "shop:Store");
        """)

    def test_shop_selection_and_marks_survive_saved_edits_and_moves_and_clear(self):
        self.run_buying_js("""
          const queued = row("Alpha", {queue_row: 1, listed_at: "Store", quantity: 1});
          apiWrite = async (path, body) => ({revision: body.state ? "q3" : "q2", item: {...queued, ...body.values}});
          const view = drawShopping(shoppingData([queued]));
          chooseShop("shop:Store");
          const sheet = shopQueueSheet(view, queued);
          field(sheet, "quantity").value = "2";
          sheetButton(sheet, "Save").click(); await null; await null;
          assert.equal(selectedShop(), "shop:Store");assert.equal(matchedQueue().length,1);
          assert(shopRadio('shop:Store').closest('label').textContent.includes('2 cards'));
          await shopMoveQueue(queued, "long_term", view, el("div"));
          assert.equal(selectedShop(), "shop:Store");assert.equal(matchedQueue().length,1);
          assert.equal(main.querySelector('#shop-to-buy'),null);assert(canonicalRow('Alpha').closest('section').textContent.includes('Long-term plan'));
          main.querySelector('.shop-clear-match').click();assert.equal(selectedShop(),'all');assert.equal(matchedQueue().length,0);
          assert.equal(shopSectionNode().querySelector('select'),null);assert.equal(shopSectionNode().querySelector('details'),null);
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
          assert.equal(selectedShop(), "all");
          assert(!shopSectionNode().textContent.includes("Only alpha"));
          same(view.data.to_buy.map(item => [item.name, item.queue_row]), [["Beta", 1]]);
          assert.equal(editControl(2), undefined);
          editControl(1).click();
          const last = [...shopQueueSheets].at(-1);
          assert.equal(last.heading.textContent, "Beta");
          same(writes, [{action: "remove", row: 1, reason: "Changed plan", expect: "q1"}]);
        """)

    def test_read_only_views_keep_canonical_research_links_and_viewers_without_write_controls(self):
        self.run_buying_js("""
          state.may = {admin: false, orders: false, see_inventory: ["home"]};
          apiWrite = async () => {throw new Error("A read-only buying view must not write");};
          drawShopping(shoppingData([row("Alpha", {queue_row: 1, listed_at: "Store", card: cardData("Alpha"),
            deck: {id: "casual/otters", title: "Otters"}})], [missingRow("Alpha", {card: cardData("Alpha")})]));
          assert.equal(main.querySelector(".shop-queue-write"), null);
          chooseShop("shop:Store");
          const canonical=canonicalRow('Alpha'),link=canonical.querySelector('.shop-queue-deck');
          assert.equal(link.getAttribute('href'),'#/deck?id=casual%2Fotters&v=target');assert.equal(link.closest('button'),null);
          canonical.querySelector('.card-row').click();assert.equal(inspections.at(-1).card.name,'Alpha');
          assert.equal(canonical.querySelector('.shop-category-move'),null);assert.equal(shopSectionNode().querySelector('.card-row'),null);
          assert.equal(matchedQueue().length,1);assert(main.querySelector('.shop-clear-match'));
        """)

    def test_stale_shop_radios_clear_chip_and_missing_refresh_ignore_replaced_nodes_profile_and_route(self):
        self.run_buying_js(r"""
          let refreshes=0,writes=0;route=()=>{refreshes++;};apiWrite=async()=>{writes++;throw new Error('Must not write');};
          const replacedView=drawShopping(shoppingData([row('Alpha',{listed_at:'Store'})]));
          const replacedRadio=shopRadio('shop:Store');chooseShop('shop:Store');
          const replacedClear=main.querySelector('.shop-clear-match');replacedView.redraw();
          replacedRadio.checked=true;replacedRadio.fire('change');replacedClear.click();
          assert.equal(replacedView.shopChoice,'shop:Store');assert.equal(selectedShop(),'shop:Store');assert.equal(matchedQueue().length,1);
          for(const departure of ['profile','route']){
            clear(main);state.profile=state.profiles[0];
            const view=drawShopping(shoppingData([row('Alpha',{listed_at:'Store'})],[],
              {missing_cards:{ready:false,rows:[],errors:[],warnings:[]}}));
            chooseShop('shop:Store');const radio=shopRadio('all'),clearButton=main.querySelector('.shop-clear-match');
            const refresh=missingSection().querySelector('button');
            if(departure==='profile')state.profile=state.profiles[1];else routeToken++;
            radio.checked=true;radio.fire('change');clearButton.click();refresh.click();
            assert.equal(view.shopChoice,'shop:Store');assert.equal(matchedQueue().length,1);
          }
          assert.equal(refreshes,0);assert.equal(writes,0);
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
          assert.equal(selectedShop(), "shop:Store");
          assert(sheet.queueError.textContent.includes("Shopping changed meanwhile"));
          assert.equal(view.stale, true);
          assert.equal(editControl(1).disabled, true);
        """)



    def test_shop_marks_reveal_all_matching_long_term_groups_and_clear_keeps_them_expanded(self):
        self.run_buying_js(r"""
          const queue=[];
          for(const [slug,title] of [['a','Deck A'],['b','Deck B']]){
            for(let n=0;n<14;n++)queue.push(row(title+' '+n,{queue_row:queue.length+1,state:'long_term',
              listed_at:n===13?'Match shop':'Other',deck:{id:'casual/'+slug,title},card:cardData(title+' '+n)}));
          }
          let writes=0;apiWrite=async()=>{writes++;throw new Error('Reveal must not write');};
          const view=drawShopping(shoppingData(queue)),before=canonicalQueue();
          assert.equal(before.length,24);const first=before[0],viewer=first.querySelector('.card-row');
          const controls=first.querySelectorAll('.shop-queue-write'),group=viewer.getAttribute('data-viewer');
          const radio=chooseShop('shop:Match shop');
          assert.equal(canonicalQueue().length,28);assert.equal(matchedQueue().length,2);
          assert(canonicalRow('Deck A 13'));assert(canonicalRow('Deck B 13'));
          assert(canonicalQueue()[0]===first,'revealing keeps the existing first row');assert(first.querySelector('.card-row')===viewer);
          sameNodes(first.querySelectorAll('.shop-queue-write'),controls);assert.equal(viewer.getAttribute('data-viewer'),group);
          assert.equal(document.activeElement,radio);assert(view.expanded.has('casual/a'));assert(view.expanded.has('casual/b'));
          main.querySelector('.shop-clear-match').click();assert.equal(matchedQueue().length,0);
          assert.equal(canonicalQueue().length,28);assert(view.expanded.has('casual/a'));assert(view.expanded.has('casual/b'));
          assert.equal(writes,0);
        """)

    def test_newly_revealed_rows_inherit_busy_and_conflict_write_control_gates(self):
        self.run_buying_js(r"""
          for(const phase of ['busy','stale']){
            clear(main);let writes=0,finish;
            const moving=row('Moving',{queue_row:1,state:'ready'});
            const later=Array.from({length:14},(_,i)=>row('Later '+i,{queue_row:i+2,state:'long_term',
              listed_at:i===13?'Reveal shop':'Other',deck:{id:'casual/later',title:'Later deck'}}));
            const view=drawShopping(shoppingData([moving,...later]));
            apiWrite=()=>{writes++;return phase==='busy'?new Promise(resolve=>{finish=resolve;})
              :Promise.reject(new ApiError(409,'Shopping changed meanwhile'));};
            const pending=shopMoveQueue(moving,'waiting_for_stock',view,el('div'));
            if(phase==='stale')await pending;
            assert.equal(canonicalQueue().length,13);
            chooseShop('shop:Reveal shop');assert.equal(canonicalQueue().length,15);
            const revealed=canonicalRow('Later 13');assert(revealed);
            assert(revealed.querySelectorAll('.shop-queue-write').every(node=>node.disabled));
            assert(main.querySelectorAll('.shop-queue-write').every(node=>node.disabled));
            assert.equal(writes,1,'shop matching never issues a write');
            if(phase==='busy'){finish({revision:'q2'});await pending;}
          }
        """)

    def test_immediate_groups_preserve_waiting_reasons_and_deferred_intent_without_state_chips(self):
        self.run_buying_js(r"""
          const queue=[row('Ready item',{queue_row:1,state:'ready'}),row('Stock item',{queue_row:2,state:'waiting_for_stock'}),
            row('Reprint item',{queue_row:3,state:'waiting_for_reprint'}),row('Deferred item',{queue_row:4,state:'deferred'})];
          const original=queue.map(item=>[item.name,item.state,item.queue_row]);
          drawShopping(shoppingData(queue));const section=main.querySelector('#shop-to-buy').closest('section');
          assert(section.textContent.includes('Ready'));assert(section.textContent.includes('Waiting'));assert(section.textContent.includes('Deferred'));
          assert(canonicalRow('Stock item').textContent.includes('Waiting for stock'));
          assert(canonicalRow('Reprint item').textContent.includes('Waiting for reprint'));
          for(const node of canonicalQueue())for(const chip of node.querySelectorAll('.status'))
            assert(!['Waiting for stock','Waiting for reprint','Deferred','Ready to buy'].includes(chip.textContent));
          same(queue.map(item=>[item.name,item.state,item.queue_row]),original);assert.equal(canonicalQueue().length,4);
        """)


if __name__ == "__main__":
    unittest.main()
