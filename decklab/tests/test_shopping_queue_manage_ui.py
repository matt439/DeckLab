"""Shopping queue add, quantity/notes edits and reasoned removals.

These are runtime interaction checks using the shared DOM double, not device
or browser layout testing. They exercise the page's controls and save results.
"""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingQueueManagementInteractionTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_queue_js(self, scenario):
        self.run_js("""
          state.may = {admin: true, orders: true, see_inventory: ["home"]};
          toast = () => {};
          const queueRow = (n, extra = {}) => row(`Card ${n}`, {queue_row: n, source: "", ...extra});
          const queueData = rows => ({...empty, queue_revision: "queue-v1", to_buy: rows,
            queue_decks: [{id: "casual/otters", title: "Izzet Otters"}]});
          const sheets = [], actualOpenSheet = openSheet;
          openSheet = (...args) => {const sheet = actualOpenSheet(...args); sheets.push(sheet); return sheet;};
          const latestSheet = () => sheets.at(-1);
          const field = (sheet, key) => {
            const input = sheet.body.querySelector(`[data-queue-field=${key}]`);
            assert(input, `Queue ${key} field`);
            return input;
          };
          const type = (sheet, key, value) => {const input = field(sheet, key); input.value = value; input.fire("input");};
          const action = (sheet, text) => {
            const button = sheet.foot.querySelectorAll("button").find(item => item.textContent === text);
            assert(button, `Sheet action ${text}`);
            return button;
          };
          const settle = async () => {await null; await null; await null; await null;};
          const details = n => main.querySelectorAll(".shop-queue-edit")
            .find(button => Number(button.dataset.queueRow) === n);
          const openDetails = n => {const button = details(n); assert(button, `Details for row ${n}`); button.click(); return latestSheet();};
          const openAdd = () => {const button = main.querySelector(".shop-queue-add"); assert(button); button.click(); return latestSheet();};
          const raw = card => Object.fromEntries(["name", "set", "collector_number", "finish", "quantity", "for", "printing",
            "listed_aud", "listed_at", "in_stock", "checked", "notes", "state", "source"].map(key => [key, card[key] ?? ""]));
          const saved = (body, item, revision = "queue-v2") => ({saved: true, action: body.action,
            row: body.row || 1, revision, ...(item ? {item: raw(item)} : {})});
        """ + scenario)

    def test_add_and_details_follow_queue_permissions_and_revision(self):
        self.run_queue_js("""
          apiWrite = async () => {throw new Error("Must not write");};
          for (const may of [{admin: false, orders: false}, {admin: false, orders: true}, {admin: true, orders: false}]) {
            clear(main);
            state.may = may;
            drawShopping(queueData([queueRow(1), queueRow(2, {state: "long_term"})]));
            assert.equal(Boolean(main.querySelector(".shop-queue-add")), Boolean(may.admin || may.orders));
            assert.equal(main.querySelectorAll(".shop-queue-edit").length, may.admin || may.orders ? 2 : 0);
            assert.equal(main.querySelector("#shop-to-buy").closest("section").querySelectorAll(".card-row").length, 1);
            assert.equal(main.querySelector("#shop-long-term").closest("section").querySelectorAll(".card-row").length, 1);
            assert.equal(main.querySelector("#shop-by-shop").closest("section").querySelectorAll(".shop-queue-edit").length, 0);
          }
          clear(main);
          drawShopping({...empty, to_buy: [queueRow(1)]});
          assert.equal(main.querySelector(".shop-queue-add"), null);
          assert.equal(main.querySelector(".shop-queue-edit"), null);
          clear(main);
          drawShopping(queueData([row("Not a queue row")]));
          assert.equal(main.querySelector(".shop-queue-edit"), null);
          clear(main);
          drawShopping(queueData([]));
          assert(main.querySelector(".shop-queue-add"), "An empty queue can receive its first card");
        """)

    def test_first_card_add_uses_chosen_deck_and_updates_long_term_plan(self):
        self.run_queue_js("""
          const writes = [], messages = [];
          toast = text => messages.push(text);
          apiWrite = async (path, body) => {
            writes.push([path, body]);
            return saved(body, row("Alpha", {...body.values, name: "Alpha", quantity: 3}));
          };
          drawShopping(queueData([]));
          const sheet = openAdd();
          assert.equal(field(sheet, "quantity").value, "1");
          type(sheet, "name", "Alpha");
          type(sheet, "quantity", "3");
          field(sheet, "state").value = "long_term";
          field(sheet, "deck").value = "casual/otters";
          field(sheet, "deck").fire("change");
          type(sheet, "notes", "Buy together with the next order");
          action(sheet, "Add card").click(); await settle();
          assert.equal(writes.length, 1);
          assert.equal(writes[0][0], "/api/shopping/queue");
          const body = writes[0][1];
          assert.equal(body.action, "add");
          assert.equal(body.expect, "queue-v1");
          same(body.values, {name: "Alpha", state: "long_term", quantity: 3, for: "Izzet Otters",
            source: "magic/decks/casual/otters.md", printing: "any", set: "", collector_number: "", finish: "nonfoil",
            notes: "Buy together with the next order"});
          assert(sheet.closed);
          assert.equal(main.querySelector("#shop-to-buy"), null);
          const plan = main.querySelector("#shop-long-term").closest("section");
          assert(plan.textContent.includes("Alpha"));
          assert(plan.textContent.includes("3 cards"));
          assert(plan.textContent.includes("Izzet Otters"));
          assert(main.querySelector(".shop-empty").hidden);
          assert(details(1));
          assert.equal(messages.length, 1);
        """)

    def test_details_edit_keeps_printing_price_source_and_card_viewer_separate(self):
        self.run_queue_js("""
          const writes = [];
          const card = queueRow(1, {name: "Alpha", quantity: 2, printing: "exact", set: "fdn", collector_number: "2",
            finish: "foil", listed_aud: "0.50", listed_at: "Card shop", in_stock: "no", checked: "2026-10-08",
            notes: "Original note", source: "magic/buylists/research.md",
            card: {...alpha, img_small: "/img/fdn/2/small"}, deck: {id: "casual/otters", title: "Izzet Otters"}});
          const original = raw(card);
          apiWrite = async (path, body) => {writes.push([path, body]); return saved(body, {...card, ...body.values});};
          drawShopping(queueData([card]));
          const button = details(1), viewer = main.querySelector(".card-row");
          assert.equal(button.closest(".card-row"), null);
          viewer.click();
          assert.equal(inspections.length, 1);
          const sheet = openDetails(1);
          assert.equal(inspections.length, 1, "Details must not open the card viewer");
          assert.equal(field(sheet, "quantity").value, "2");
          assert.equal(field(sheet, "notes").value, "Original note");
          type(sheet, "quantity", "4");
          type(sheet, "notes", "<b>Check the art</b>");
          action(sheet, "Save").click(); await settle();
          same(writes, [["/api/shopping/queue", {action: "edit", row: 1, values: {quantity: 4, notes: "<b>Check the art</b>"},
            expect: "queue-v1"}]]);
          assert(sheet.closed);
          same(raw(card), {...original, quantity: 4, notes: "<b>Check the art</b>"});
          assert.equal(main.querySelector("b"), null);
          assert(main.textContent.includes("Exact: FDN 2 foil"));
          assert(main.textContent.includes("A$0.50 at Card shop"));
          assert(main.textContent.includes("Izzet Otters"));
          assert.equal(document.activeElement, details(1));
        """)

    def test_add_exact_printing_and_name_change_returns_to_nonfoil_default(self):
        self.run_queue_js("""
          for (const rename of [false, true]) {
            clear(main);
            const writes = [], pickedFor = [];
            pickPrinting = async name => {pickedFor.push(name); return {set: "fdn", number: "2", finish: "foil"};};
            apiWrite = async (path, body) => {writes.push(body); return saved(body, row(body.values.name, body.values));};
            drawShopping(queueData([]));
            const sheet = openAdd();
            type(sheet, "name", "Alpha");
            const choose = sheet.body.querySelectorAll("button").find(button => button.textContent.startsWith("Choose exact printing"));
            assert(choose); choose.click(); await settle();
            same(pickedFor, ["Alpha"]);
            assert(sheet.body.textContent.includes("Exact: FDN 2 foil"));
            if (rename) {
              type(sheet, "name", "Beta");
              assert(sheet.body.textContent.includes("Any printing, nonfoil"));
            }
            action(sheet, "Add card").click(); await settle();
            assert.equal(writes.length, 1);
            same({name: writes[0].values.name, printing: writes[0].values.printing, set: writes[0].values.set,
              collector_number: writes[0].values.collector_number, finish: writes[0].values.finish},
              rename ? {name: "Beta", printing: "any", set: "", collector_number: "", finish: "nonfoil"}
                : {name: "Alpha", printing: "exact", set: "fdn", collector_number: "2", finish: "foil"});
            assert.equal(writes[0].values.source, "");
            assert.equal(writes[0].values.for, "");
            assert(sheet.closed);
          }
        """)

    def test_late_printing_choice_for_an_old_name_is_ignored(self):
        self.run_queue_js("""
          let finish;
          const writes = [];
          pickPrinting = () => new Promise(resolve => {finish = resolve;});
          apiWrite = async (path, body) => {writes.push(body); return saved(body, row(body.values.name, body.values));};
          drawShopping(queueData([]));
          const sheet = openAdd();
          type(sheet, "name", "Alpha");
          sheet.body.querySelectorAll("button").find(button => button.textContent.startsWith("Choose exact printing")).click();
          type(sheet, "name", "Beta");
          finish({set: "fdn", number: "2", finish: "foil"}); await settle();
          assert(sheet.body.textContent.includes("Any printing, nonfoil"));
          action(sheet, "Add card").click(); await settle();
          assert.equal(writes.length, 1);
          assert.equal(writes[0].values.name, "Beta");
          assert.equal(writes[0].values.printing, "any");
          assert.equal(writes[0].values.finish, "nonfoil");
        """)

    def test_invalid_names_and_quantities_do_not_write_or_discard_input(self):
        self.run_queue_js("""
          const writes = [];
          apiWrite = async (path, body) => {writes.push(body); return saved(body, row(body.values.name, body.values));};
          drawShopping(queueData([]));
          const sheet = openAdd();
          type(sheet, "notes", "Keep this note while fixing the fields");
          action(sheet, "Add card").click(); await settle();
          assert.equal(writes.length, 0);
          assert.equal(document.activeElement, field(sheet, "name"));
          type(sheet, "name", "Alpha");
          for (const quantity of ["", "0", "-1", "1.5", "10000", "not a number"]) {
            type(sheet, "quantity", quantity);
            action(sheet, "Add card").click(); await settle();
            assert.equal(writes.length, 0);
            assert.equal(sheet.closed, false);
            assert.equal(field(sheet, "notes").value, "Keep this note while fixing the fields");
            assert.equal(document.activeElement, field(sheet, "quantity"));
          }
          type(sheet, "quantity", "2");
          action(sheet, "Add card").click(); await settle();
          assert.equal(writes.length, 1);
          assert.equal(writes[0].values.quantity, 2);
          assert.equal(writes[0].values.notes, "Keep this note while fixing the fields");
          assert(sheet.closed);
        """)

    def test_remove_requires_a_reason_and_reindexes_the_remaining_rows(self):
        self.run_queue_js("""
          const writes = [], cards = [queueRow(1), queueRow(2), queueRow(3)], third = cards[2];
          apiWrite = async (path, body) => {
            writes.push([path, body]);
            return saved(body, body.action === "edit" ? {...third, ...body.values} : null,
              `queue-v${writes.length + 1}`);
          };
          drawShopping(queueData(cards));
          const parent = openDetails(2);
          action(parent, "Remove…").click();
          const confirm = latestSheet();
          assert.notEqual(confirm, parent);
          action(confirm, "Remove card").click(); await settle();
          assert.equal(writes.length, 0, "Removal needs the user's reason");
          type(confirm, "reason", "No longer building this deck");
          action(confirm, "Remove card").click(); await settle();
          same(writes[0], ["/api/shopping/queue", {action: "remove", row: 2, reason: "No longer building this deck", expect: "queue-v1"}]);
          assert(confirm.closed);
          assert(parent.closed);
          assert.equal(main.querySelectorAll(".shop-queue-edit").length, 2);
          assert(details(2).closest(".shop-queue-row").textContent.includes("Card 3"));
          assert(!main.textContent.includes("Card 2"));
          const next = openDetails(2);
          type(next, "quantity", "5");
          action(next, "Save").click(); await settle();
          assert.equal(writes[1][1].row, 2);
          assert.equal(writes[1][1].expect, "queue-v2");
          assert.equal(writes[1][1].values.quantity, 5);
        """)

    def test_failed_save_keeps_typed_fields_and_conflict_blocks_all_writes(self):
        self.run_queue_js("""
          let refreshes = 0; route = async () => {refreshes += 1;};
          for (const code of [500, 409]) {
            clear(main);
            const writes = [], card = queueRow(1, {notes: "Before"});
            apiWrite = async (path, body) => {writes.push(body); throw new ApiError(code, "The queue changed elsewhere.");};
            drawShopping(queueData([card]));
            const sheet = openDetails(1);
            type(sheet, "quantity", "7");
            type(sheet, "notes", "Typed and still here");
            action(sheet, "Save").click(); await settle();
            assert.equal(sheet.closed, false);
            assert.equal(field(sheet, "quantity").value, "7");
            assert.equal(field(sheet, "notes").value, "Typed and still here");
            assert(sheet.body.textContent.includes("The queue changed elsewhere."));
            assert.equal(card.quantity, 1);
            assert.equal(card.notes, "Before");
            assert.equal(action(sheet, "Save").disabled, code === 409);
            assert.equal(main.querySelector(".shop-queue-add").disabled, code === 409);
            assert.equal(details(1).disabled, code === 409);
            assert.equal(main.querySelector(".shop-category-move").disabled, code === 409);
            if (code === 409) {
              action(sheet, "Save").click(); main.querySelector(".shop-queue-add").click(); details(1).click();
              assert.equal(writes.length, 1);
              const refresh = sheet.body.querySelectorAll("button").find(button => button.textContent === "Refresh Shopping");
              assert(refresh); refresh.click();
            } else {
              apiWrite = async (path, body) => {writes.push(body); return saved(body, {...card, ...body.values});};
              action(sheet, "Save").click(); await settle();
              assert(sheet.closed);
              assert.equal(writes.length, 2);
              assert.equal(card.quantity, 7);
              assert.equal(card.notes, "Typed and still here");
            }
            sheet.close();
          }
          assert.equal(refreshes, 1);
        """)

    def test_failed_removal_keeps_reason_and_parent_values_and_can_be_retried(self):
        self.run_queue_js("""
          for (const code of [500, 409]) {
            clear(main);
            const writes = [], card = queueRow(1, {quantity: 2, notes: "Saved note"});
            apiWrite = async (path, body) => {writes.push(body); throw new ApiError(code, "The removal failed.");};
            drawShopping(queueData([card]));
            const parent = openDetails(1);
            type(parent, "quantity", "3");
            type(parent, "notes", "Unsent parent note");
            action(parent, "Remove…").click();
            const confirm = latestSheet();
            type(confirm, "reason", "Changed plans");
            action(confirm, "Remove card").click(); await settle();
            assert.equal(card.quantity, 2);
            assert.equal(card.notes, "Saved note");
            assert.equal(confirm.closed, false);
            assert.equal(parent.closed, false);
            assert.equal(field(confirm, "reason").value, "Changed plans");
            assert.equal(field(parent, "quantity").value, "3");
            assert.equal(field(parent, "notes").value, "Unsent parent note");
            assert(confirm.body.textContent.includes("The removal failed."));
            assert.equal(action(confirm, "Remove card").disabled, code === 409);
            if (code === 500) {
              apiWrite = async (path, body) => {writes.push(body); return saved(body, null);};
              action(confirm, "Remove card").click(); await settle();
              assert.equal(writes.length, 2);
              assert.equal(writes[1].reason, "Changed plans");
              assert(confirm.closed);
              assert(parent.closed);
            } else {
              action(confirm, "Cancel").click();
              assert(confirm.closed);
              assert.equal(action(parent, "Save").disabled, true);
              action(parent, "Save").click();
              assert.equal(writes.length, 1);
            }
            confirm.close(); parent.close();
          }
        """)

    def test_removing_the_final_card_restores_the_empty_queue(self):
        self.run_queue_js("""
          for (const category of ["ready", "long_term"]) {
            clear(main);
            const writes = [];
            apiWrite = async (path, body) => {writes.push(body); return saved(body, null);};
            drawShopping(queueData([queueRow(1, {state: category})]));
            const parent = openDetails(1);
            action(parent, "Remove…").click();
            const confirm = latestSheet();
            type(confirm, "reason", "No longer needed");
            action(confirm, "Remove card").click(); await settle();
            assert.equal(writes.length, 1);
            assert.equal(main.querySelectorAll(".card-row").length, 0);
            assert.equal(main.querySelector("#shop-to-buy"), null);
            assert.equal(main.querySelector("#shop-long-term"), null);
            assert.equal(main.querySelector(".shop-empty").hidden, false);
            assert.equal(main.querySelector(".shop-layout"), null);
            assert(main.querySelector(".shop-queue-add"));
            assert.equal(document.activeElement, main.querySelector(".shop-queue-add"));
          }
        """)

    def test_removal_conflict_refresh_closes_parent_and_confirmation(self):
        self.run_queue_js("""
          let refreshes = 0;
          route = async () => {refreshes += 1;};
          apiWrite = async () => {throw new ApiError(409, "The queue changed elsewhere.");};
          drawShopping(queueData([queueRow(1)]));
          const parent = openDetails(1);
          action(parent, "Remove…").click();
          const confirm = latestSheet();
          type(confirm, "reason", "No longer needed");
          action(confirm, "Remove card").click(); await settle();
          const refresh = confirm.body.querySelectorAll("button").find(button => button.textContent === "Refresh Shopping");
          assert(refresh);
          assert(parent.body.textContent.includes("The queue changed elsewhere."));
          refresh.click(); await settle();
          assert(confirm.closed);
          assert(parent.closed);
          assert.equal(document.body.querySelectorAll(".sheet").length, 0);
          assert.equal(refreshes, 1);
        """)

    def test_navigation_and_profile_change_close_queue_and_printing_picker(self):
        self.run_queue_js("""
          drawShell = () => {};
          loadSimulations = () => {};
          noteVisit = () => {};
          showWishlist = async () => {clear(main).append(el("p", {text: "The next page"}));};
          api = async path => path.endsWith("/settings") ? {theme: "system"} : {printings: [], total: 0};
          apiWrite = async () => {throw new Error("No queue save should be sent");};
          for (const leave of ["route", "who", "profile"]) {
            state.profile = state.profiles[0];
            state.may = {admin: true, orders: true, see_inventory: ["home"]};
            location.hash = "#/shopping";
            clear(main);
            drawShopping(queueData([]));
            const parent = openAdd();
            type(parent, "name", "Alpha");
            parent.body.querySelectorAll("button").find(button => button.textContent.startsWith("Choose exact printing")).click();
            await settle();
            const picker = latestSheet();
            assert.notEqual(picker, parent);
            assert.equal(document.body.querySelectorAll(".sheet").length, 2);
            location.hash = "#/wishlist";
            if (leave === "route") await route();
            else if (leave === "who") drawWho();
            else await chooseProfile(state.profiles[1]);
            await settle();
            assert(parent.closed, `Queue sheet closed by ${leave}`);
            assert(picker.closed, `Printing picker closed by ${leave}`);
            assert.equal(document.body.querySelectorAll(".sheet").length, 0);
            if (leave === "who") assert(main.textContent.includes("Who are you?"));
            else assert.equal(main.textContent, "The next page");
          }
        """)

    def test_pending_save_serializes_add_edit_move_and_repeated_save(self):
        self.run_queue_js("""
          const writes = [];
          let finish;
          const card = queueRow(1);
          apiWrite = (path, body) => {writes.push(body); return new Promise(resolve => {finish = resolve;});};
          drawShopping(queueData([card, queueRow(2)]));
          const sheet = openDetails(1);
          type(sheet, "quantity", "4");
          const save = action(sheet, "Save");
          save.click();
          assert(save.disabled);
          assert(main.querySelector(".shop-queue-add").disabled);
          assert(main.querySelectorAll(".shop-queue-edit").every(button => button.disabled));
          assert(main.querySelectorAll(".shop-category-move").every(button => button.disabled));
          save.click(); details(2).click(); main.querySelector(".shop-queue-add").click();
          assert.equal(writes.length, 1);
          assert.equal(sheets.length, 1);
          assert.equal(card.quantity, 1);
          finish(saved(writes[0], {...card, quantity: 4})); await settle();
          assert(sheet.closed);
          assert.equal(card.quantity, 4);
          assert(!main.querySelector(".shop-queue-add").disabled);
          assert(main.querySelectorAll(".shop-queue-edit").every(button => !button.disabled));
          assert(main.querySelectorAll(".shop-category-move").every(button => !button.disabled));
        """)

    def test_queue_changes_keep_followup_undo_and_history_nodes(self):
        self.run_queue_js("""
          const writes = [];
          const card = queueRow(1);
          apiWrite = async (path, body) => {writes.push([path, body]); return saved(body, {...card, ...body.values});};
          drawShopping({...queueData([card]),
            orders: [order({id: "old", status: "received", components: [component({status: "received"})]})],
            checks: [{order_id: "old", component_id: "cards", status: "received", text: "Check the token"}]});
          const followup = main.querySelector(".shop-followup"), history = main.querySelector(".shop-history");
          history.setAttribute("open", "");
          followup.querySelector("button").click();
          const undo = document.getElementById("toast-undo").querySelector("button");
          const sheet = openDetails(1);
          type(sheet, "quantity", "2");
          action(sheet, "Save").click(); await settle();
          assert.equal(main.querySelector(".shop-followup"), followup);
          assert.equal(followup.hidden, true);
          assert.equal(main.querySelector(".shop-history"), history);
          assert.equal(history.getAttribute("open"), "");
          assert.equal(document.getElementById("toast-undo").querySelector("button"), undo);
          undo.click();
          assert.equal(followup.hidden, false);
          flushTimers(); await settle();
          assert.equal(writes.length, 1);
          assert.equal(writes[0][0], "/api/shopping/queue");
        """)

    def test_late_save_success_and_failure_leave_new_page_alone(self):
        self.run_queue_js("""
          const messages = []; toast = text => messages.push(text);
          for (const fail of [false, true]) {
            clear(main);
            let finish, reject, body;
            const card = queueRow(1);
            apiWrite = (path, value) => {body = value; return new Promise((resolve, failure) => {finish = resolve; reject = failure;});};
            drawShopping(queueData([card]));
            const sheet = openDetails(1);
            type(sheet, "quantity", "9");
            action(sheet, "Save").click();
            routeToken += 1;
            clear(main).append(el("p", {text: "Another page"}));
            if (fail) reject(new ApiError(409, "Changed elsewhere"));
            else finish(saved(body, {...card, quantity: 9}));
            await settle();
            assert.equal(main.textContent, "Another page");
            assert.equal(card.quantity, 1);
            sheet.close();
          }
          same(messages, []);
        """)

    def test_late_old_save_leaves_new_queue_form_and_its_save_state_alone(self):
        self.run_queue_js("""
          for (const lateFailure of [true, false]) {
            for (const nextStatus of ["typing", "pending", "stale"]) {
              clear(main);
              const requests = [], oldCard = queueRow(1);
              apiWrite = (path, body) => new Promise((resolve, reject) => {requests.push({body, resolve, reject});});
              drawShopping(queueData([oldCard]));
              const oldSheet = openDetails(1);
              type(oldSheet, "quantity", "9");
              action(oldSheet, "Save").click();
              assert.equal(requests.length, 1);
              shopCloseQueueSheets();
              routeToken += 1;
              clear(main);
              drawShopping({...queueData([queueRow(1, {name: "Current card"})]), queue_revision: "queue-new"});
              const nextSheet = openAdd();
              type(nextSheet, "name", "Beta");
              type(nextSheet, "quantity", "3");
              type(nextSheet, "notes", "Keep my new Shopping work");
              if (nextStatus !== "typing") {
                action(nextSheet, "Add card").click();
                assert.equal(requests.length, 2);
                assert.equal(requests[1].body.expect, "queue-new");
                if (nextStatus === "stale") {
                  requests[1].reject(new ApiError(409, "The current queue is stale."));
                  await settle();
                }
              }
              const buttons = [...nextSheet.dialog.querySelectorAll("button"),
                ...main.querySelectorAll(".shop-queue-write")];
              const disabled = buttons.map(button => button.disabled);
              const contents = nextSheet.body.textContent, focused = document.activeElement;
              if (lateFailure) requests[0].reject(new ApiError(409, "The old page's queue changed."));
              else requests[0].resolve(saved(requests[0].body, {...oldCard, quantity: 9}));
              await settle();
              assert.equal(oldSheet.closed, true);
              assert.equal(oldCard.quantity, 1);
              assert.equal(nextSheet.closed, false, `New ${nextStatus} sheet survives late old save`);
              assert.equal(field(nextSheet, "name").value, "Beta");
              assert.equal(field(nextSheet, "quantity").value, "3");
              assert.equal(field(nextSheet, "notes").value, "Keep my new Shopping work");
              assert.equal(nextSheet.body.textContent, contents);
              same(buttons.map(button => button.disabled), disabled);
              assert.equal(document.activeElement, focused);
              if (nextStatus === "pending") {
                assert(action(nextSheet, "Saving…").disabled);
                requests[1].resolve(saved(requests[1].body, row("Beta", requests[1].body.values), "queue-new-2"));
                await settle();
                assert(nextSheet.closed);
                assert(main.textContent.includes("Beta"));
              } else nextSheet.close();
            }
          }
        """)


if __name__ == "__main__":
    unittest.main()
