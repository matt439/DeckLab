"""Reprint hints are dated source observations; a manual check makes no data write."""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ReprintInteractionTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_reprint_js(self, scenario):
        self.run_js("""
          state.may = {admin: true, orders: true, see_inventory: ["home"]};
          const printing = (extra = {}) => ({set: "new", set_name: "New Set", released_at: "2026-11-10",
            source_url: "https://scryfall.com/card/new/7/alpha", ...extra});
          const reprints = (extra = {}) => ({ready: true, as_of: "2026-10-16", data_date: "2026-10-15",
            coverage: "Cached paper printings may be incomplete; scheduled dates may change.",
            upcoming: [printing()], upcoming_more: 0, released: [], released_more: 0,
            price_check: {offered: false, reason: null, checked: "2026-09-30"},
            notes: ["A reprint does not guarantee a lower price or shop stock."],
            source_url: "https://scryfall.com/search?q=Alpha+game%3Apaper", ...extra});
          const queueRow = (extra = {}) => row("Alpha", {state: "waiting_for_reprint", queue_row: 1,
            checked: "2026-09-30", listed_aud: "3.50", listed_at: "Recorded shop", reprints: reprints(), ...extra});
          const queueData = rows => ({...empty, to_buy: rows, queue_revision: "q1"});
          const dueInfo = (extra = {}) => reprints({upcoming: [],
            released: [printing({released_at: "2026-10-10"})],
            price_check: {offered: true, reason: "release_due", checked: "2026-09-30"}, ...extra});
          const checkButton = () => main.querySelector(".reprint-check");
          const latestSheet = () => [...reprintSheets].at(-1);
          const action = (sheet, text) => sheet.dialog.querySelectorAll("button").find(button => button.textContent === text);
          const settle = async () => {await Promise.resolve(); await Promise.resolve(); await Promise.resolve();};
          apiWrite = async () => {throw new Error("A reprint source or manual check must not write");};
          toast = () => {};
        """ + scenario)

    def test_upcoming_printing_keeps_set_iso_date_and_dated_source_outside_viewer(self):
        self.run_reprint_js("""
          const card = {name: "Alpha", type_line: "Creature", img: "/img/new/7/normal", img_small: "/img/new/7/small"};
          const view = drawShopping(queueData([queueRow({card})]));
          const hint = main.querySelector(".reprint-info");
          assert(hint.textContent.includes("New Set (NEW)"));
          assert(hint.textContent.includes("scheduled 2026-11-10"));
          assert(hint.textContent.includes("Card data: 2026-10-15"));
          assert(hint.textContent.includes("Dates compared as of 2026-10-16"));
          assert(hint.textContent.includes("may be incomplete"));
          assert(hint.textContent.includes("does not guarantee a lower price or shop stock"));
          assert.equal(hint.closest("button"), null);
          const source = hint.querySelector("a");
          assert.equal(source.getAttribute("href"), "https://scryfall.com/card/new/7/alpha");
          assert.equal(source.getAttribute("target"), "_blank");
          assert.equal(source.getAttribute("rel"), "noopener noreferrer");
          assert.equal(checkButton(), null);
          main.querySelector(".card-row").click();
          assert.equal(inspections.at(-1).card.name, "Alpha");
          assert.equal(view.data.to_buy[0].state, "waiting_for_reprint");
          assert(main.textContent.includes("Reference price A$3.50 at Recorded shop"));
        """)

    def test_combined_missing_and_deck_price_rows_share_the_information_without_picture(self):
        self.run_reprint_js("""
          const missing = {name: "Alpha", missing: 2, reprints: reprints(), decks: [{id: "casual/alpha", title: "Alpha deck", missing: 2}]};
          drawShopping({...queueData([]), missing_cards: {ready: true, rows: [missing], errors: [], warnings: []}});
          const article = main.querySelector(".shop-missing-card");
          assert(article.textContent.includes("New Set (NEW)"));
          assert.equal(article.querySelector("img"), null);
          const priceRow = ownedRow({name: "Alpha", need: 2, available: 0, missing: 2, reprints: reprints()}, 0);
          main.append(priceRow);
          assert.equal(priceRow.querySelector(".reprint-row").querySelector("td").getAttribute("colspan"), "5");
          assert(priceRow.textContent.includes("scheduled 2026-11-10"));
          const present = ownedRow({name: "Alpha", need: 2, available: 2, missing: 0, reprints: reprints()}, 2);
          assert.equal(present.querySelector(".reprint-info"), null);
          assert.equal(ownedSection({summary: {id: "casual/alpha"}}), null, "No owned projection exposes no reprint row");
        """)

    def test_ordinary_absent_projection_is_quiet_and_waiting_row_has_qualified_empty_answer(self):
        self.run_reprint_js("""
          drawShopping(queueData([queueRow({reprints: null, state: "ready"})]));
          assert.equal(main.querySelector(".reprint-info"), null);
          clear(main);
          drawShopping(queueData([queueRow({reprints: reprints({upcoming: []})})]));
          const hint = main.querySelector(".reprint-info");
          assert(hint.textContent.includes("No upcoming paper printing found in this card-data snapshot"));
          assert(hint.textContent.includes("may be incomplete"));
          assert.equal(checkButton(), null);
        """)

    def test_due_offer_opens_manual_sources_and_preserves_category_prices_and_exact_specification(self):
        self.run_reprint_js("""
          const card = queueRow({printing: "exact", set: "old", collector_number: "2", finish: "foil", reprints: dueInfo()});
          const before = JSON.stringify(card), view = drawShopping(queueData([card]));
          assert(main.textContent.includes("release date has passed since the recorded price check"));
          checkButton().click();
          const sheet = latestSheet();
          assert(sheet.body.textContent.includes("New Set (NEW)"));
          assert(sheet.body.textContent.includes("release date 2026-10-10"));
          assert(sheet.body.textContent.includes("Recorded price check: 2026-09-30"));
          assert(sheet.body.textContent.includes("Reference price A$3.50 at Recorded shop"));
          assert(sheet.body.textContent.includes("Exact: OLD 2 foil"));
          assert(sheet.body.textContent.includes("Scryfall (USD prices)"));
          assert(sheet.body.textContent.includes("does not confirm that a shop has copies"));
          assert(sheet.body.textContent.includes("purchase-queue category and recorded price stay as they are"));
          assert.equal(action(sheet, "Save"), undefined);
          action(sheet, "Close").click();
          assert(sheet.closed);
          assert.equal(JSON.stringify(card), before);
          assert.equal(view.data.queue_revision, "q1");
        """)

    def test_unknown_date_and_unavailable_data_never_invent_a_released_printing(self):
        self.run_reprint_js("""
          for (const [reason, checked, ready] of [["check_date_unknown", "2035-01-01", true],
            ["check_date_unknown", "", true], ["data_unavailable", "2026-09-30", false]]) {
            clear(main);
            drawShopping(queueData([queueRow({checked, reprints: reprints({ready, upcoming: [], released: [],
              price_check: {offered: true, reason, checked}})})]));
            checkButton().click();
            const sheet = latestSheet();
            assert(!sheet.body.textContent.includes("release date 2026-10-10"));
            assert(!sheet.body.textContent.includes("release date after the recorded price check"));
            assert(sheet.body.textContent.includes(checked || "date not recorded"));
            if (!ready) assert(sheet.body.textContent.includes("Reprint data is unavailable"));
            else assert(sheet.body.textContent.includes("reliable last price-check date is not recorded"));
            sheet.close();
          }
        """)

    def test_sources_are_text_when_their_url_is_not_the_catalogs_https_origin(self):
        self.run_reprint_js("""
          for (const source_url of ["javascript:alert(1)", "https://scryfall.com.evil.example/card/a", "http://scryfall.com/card/a",
            "https://scryfall.com@evil.example/card/a", "//scryfall.com/card/a"]) {
            clear(main);
            const info = dueInfo({source_url, released: [printing({source_url, set_name: "<img onerror=bad>"})]});
            drawShopping(queueData([queueRow({reprints: info})]));
            checkButton().click();
            const sheet = latestSheet();
            assert.equal(sheet.body.querySelector("a"), null);
            assert.equal(sheet.body.querySelector("img"), null);
            assert(sheet.body.textContent.includes("<img onerror=bad>"));
            sheet.close();
          }
        """)

    def test_copy_name_is_manual_and_clipboard_failure_keeps_a_selectable_exact_name(self):
        self.run_reprint_js("""
          drawShopping(queueData([queueRow({reprints: dueInfo()})]));
          checkButton().click();
          let sheet = latestSheet(), copied = [];
          navigator.clipboard = {writeText: async text => copied.push(text)};
          action(sheet, "Copy card name").click(); await settle();
          same(copied, ["Alpha"]);
          assert(sheet.body.textContent.includes("Card name copied"));
          navigator.clipboard.writeText = async () => {throw new Error("Clipboard denied");};
          action(sheet, "Copy card name").click(); await settle();
          assert(sheet.body.textContent.includes("Select and copy the card name below"));
          assert.equal(document.activeElement, sheet.body.querySelector("input"));
          assert.equal(document.activeElement.value, "Alpha");
          assert.equal(document.activeElement.getAttribute("readonly"), "");
        """)

    def test_route_person_and_away_lock_cleanup_close_the_manual_sheet(self):
        self.run_reprint_js("""
          drawShell = () => {}; loadSimulations = () => {}; noteVisit = () => {};
          showWishlist = async () => {clear(main).append(el("p", {text: "Next page"}));};
          api = async () => ({theme: "system"});
          closeEditor = () => {};
          for (const leave of ["route", "person", "away"]) {
            state.profile = state.profiles[0]; location.hash = "#/shopping"; clear(main);
            drawShopping(queueData([queueRow({reprints: dueInfo()})]));
            checkButton().click();
            const sheet = latestSheet();
            location.hash = "#/wishlist";
            if (leave === "route") await route();
            else if (leave === "person") await chooseProfile(state.profiles[1]);
            else drawWho();
            assert(sheet.closed, leave);
            assert.equal(reprintSheets.size, 0);
            assert.equal(document.body.querySelectorAll(".sheet").length, 0);
          }
        """)

    def test_disconnected_or_old_person_controls_and_late_clipboard_cannot_open_or_change_sheets(self):
        self.run_reprint_js("""
          drawShopping(queueData([queueRow({reprints: dueInfo()})]));
          const old = checkButton();
          clear(main); old.click();
          assert.equal(reprintSheets.size, 0);
          drawShopping(queueData([queueRow({reprints: dueInfo()})]));
          state.profile = state.profiles[1];
          checkButton().click();
          assert.equal(reprintSheets.size, 0);
          state.profile = state.profiles[0];
          checkButton().click();
          const sheet = latestSheet();
          let finish;
          navigator.clipboard = {writeText: () => new Promise(resolve => {finish = resolve;})};
          action(sheet, "Copy card name").click();
          state.profile = state.profiles[1]; closeReprintSheets();
          finish(); await settle();
          assert(sheet.closed);
          assert(!sheet.body.textContent.includes("Card name copied"));
          assert.equal(reprintSheets.size, 0);
        """)

    def test_source_more_counts_remain_explicit(self):
        self.run_reprint_js("""
          drawShopping(queueData([queueRow({reprints: dueInfo({upcoming: [printing()], upcoming_more: 4, released_more: 3})})]));
          assert(main.textContent.includes("4 more scheduled printings in the source"));
          checkButton().click();
          assert(latestSheet().body.textContent.includes("3 more qualifying printings in the source"));
        """)

    def test_queue_move_replaces_or_clears_enrichment_and_an_old_answer_preserves_it(self):
        self.run_reprint_js("""
          for (const result of [{reprints: null}, {reprints: dueInfo()}, {}]) {
            clear(main);
            const card = queueRow(), original = card.reprints, view = drawShopping(queueData([card]));
            apiWrite = async () => ({saved: true, state: "ready", revision: "q2", ...result});
            const error = el("div"); main.append(error);
            await shopMoveQueue(card, "ready", view, error);
            assert.equal(card.state, "ready");
            assert.equal(card.reprints, Object.hasOwn(result, "reprints") ? result.reprints : original);
            assert.equal(view.data.queue_revision, "q2");
          }
        """)

    def test_queue_add_and_edit_accept_enriched_answer_and_null_removal(self):
        self.run_reprint_js("""
          let view = drawShopping(queueData([]));
          let sheet = shopQueueSheet(view), error = sheet.queueError;
          const added = queueRow({queue_row: undefined});
          apiWrite = async () => ({saved: true, item: added, revision: "q2", reprints: dueInfo()});
          assert(await shopSaveQueue(view, sheet, error, {action: "add", values: {name: "Alpha"}}, null));
          assert.equal(view.data.to_buy[0].reprints.price_check.reason, "release_due");
          const card = view.data.to_buy[0];
          sheet = shopQueueSheet(view, card); error = sheet.queueError;
          apiWrite = async () => ({saved: true, item: {...added, notes: "Keep waiting"}, revision: "q3", reprints: null});
          assert(await shopSaveQueue(view, sheet, error, {action: "edit", row: 1, values: {notes: "Keep waiting"}}, card));
          assert.equal(card.reprints, null);
          assert.equal(main.querySelector(".reprint-info"), null);
          assert.equal(view.data.queue_revision, "q3");
        """)


if __name__ == "__main__":
    unittest.main()
