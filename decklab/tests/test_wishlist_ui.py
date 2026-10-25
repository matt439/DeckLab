"""Wishlist interactions with the real browser functions and deterministic API promises."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class WishlistInteractionTests(unittest.TestCase):
    def run_js(self, scenario):
        setup = """
          clear(main);
          document.body.append(el("p", {id: "toast"}));
          state.profiles = [{id: "user1", name: "User1"}, {id: "matt", name: "Matt"}];
          state.profile = state.profiles[0];
          location.hash = "#/wishlist";
          const entry = (card, extra = {}) => ({name: card.name, set: "fdn", number: "1",
            card, have: {owned: 0, on_the_way: 0}, notes: "A useful recommendation.",
            source: "magic/buylists/2026-10-01-user1-suggestions.md", ...extra});
          const saved = (cards, extra = {}) => ({profile: state.profile.id,
            entries: cards.map(card => entry(card)), warnings: [], ...extra});
          const show = (cards = []) => drawWishlist(saved(cards), state.profile, routeToken);
          const flush = async (n = 40) => { for (let i = 0; i < n; i++) await Promise.resolve(); };
          const button = (root, text) => root.querySelectorAll("button").find((b) => b.textContent.trim() === text) || null;
          const openDialog = () => document.querySelectorAll("dialog").pop();
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_phone_route_loads_personal_list_with_context_and_inspector(self):
        self.run_js("""
          assert.equal(canBuildDecks(), false);
          closeEditor = () => {}; stopMatchupRefresh = () => {};
          noteVisit = () => {};          // the router's visits beacon (test_visits) isn't one of the page's reads
          const reads = [];
          const pictured = {...alpha, img_small: "/img/fdn/1/small", img: "/img/fdn/1/normal"};
          api = async path => { reads.push(path); return saved([alpha], {
            entries: [entry(pictured, {have: {owned: 2, on_the_way: 3}})]}); };
          await route();
          same(reads, ["/api/profiles/user1/wishlist"]);
          assert(main.textContent.includes("User1's wishlist"));
          assert(main.textContent.includes("2 owned · 3 on the way"));
          // A tap opens the card's sheet: its notes and source, and Zoom opens the viewer over the whole list.
          const tile = main.querySelector(".card-tile-open");
          assert.equal(tile.getAttribute("data-viewer"), "wishlist");
          tile.click();
          const sheet = openDialog();
          assert.equal(sheet.querySelector("textarea").value, "A useful recommendation.");
          assert(sheet.textContent.includes("Suggested in User1 suggestions · 2026-10-01"));
          sheet.querySelector(".wishlist-sheet-pic").click();
          assert.equal(inspections.length, 1);
          assert.equal(inspections[0].card.name, "Alpha");
          assert.equal(inspections[0].trigger, tile);
          assert.equal(main.querySelector(".desktop-handoff"), null);
        """)

    def test_zero_counts_are_hidden_and_a_deck_source_shows_its_title(self):
        self.run_js("""
          const view = drawWishlist(saved([alpha], {entries: [entry(alpha, {source: "magic/decks/casual/gruul-ramp.md",
            source_deck: {id: "casual/gruul-ramp", title: "Gruul Ramp"}})]}), state.profile, routeToken);
          assert(!view.cards.textContent.includes("0 owned"));
          assert(!view.cards.textContent.includes("0 on the way"));
          const link = view.cards.querySelectorAll("a").find((a) => a.textContent === "Gruul Ramp");
          assert(link); assert.equal(link.getAttribute("href"), deckHref("casual/gruul-ramp"));
          assert(!view.cards.textContent.includes("gruul-ramp.md"));
        """)

    def test_add_and_remove_use_captured_profile_and_render_persisted_answers(self):
        self.run_js("""
          const view = show();
          const card = {...alpha, default: {set: "fdn", number: "1"}};
          view.matches = [card]; drawWishlistSearch(view);
          const writes = [];
          apiWrite = async (path, body) => {
            writes.push([path, body]);
            return saved(body.action === "add" ? [card] : []);
          };
          button(view.searchResults, "Add").click(); await flush();
          same(writes[0], ["/api/profiles/user1/wishlist",
            {profile: "user1", action: "add", name: "Alpha", set: "fdn", number: "1"}]);
          assert.equal(view.cards.querySelectorAll(".card-tile").length, 1);
          const added = view.searchResults.querySelector(".wishlist-mutate");
          assert(added.disabled); assert.equal(added.textContent, "Added");
          await removeWishlist(view, view.data.entries[0]);
          same(writes[1][1], {profile: "user1", action: "remove", name: "Alpha"});
          assert(view.cards.textContent.includes("Your wishlist is empty"));
          assert.equal(view.searchResults.querySelector(".wishlist-mutate").disabled, false);
          assert(view.message.textContent.includes("removed"));
        """)

    def test_remove_has_an_undo_that_puts_the_card_back_as_it_was(self):
        self.run_js("""
          const view = show([beta, alpha]);
          const writes = [];
          apiWrite = async (path, body) => { writes.push(body); return saved(body.action === "add" ? [beta, alpha] : [beta]); };
          // Remove sits at the bottom of the card's sheet.
          view.cards.querySelectorAll(".card-tile-open")[1].click();
          const sheet = openDialog();
          const actions = sheet.querySelector(".sheet-foot").querySelectorAll("button");
          assert.equal(actions[actions.length - 1].textContent, "Remove");
          actions[actions.length - 1].click(); await flush();
          same(writes[0], {profile: "user1", action: "remove", name: "Alpha"});
          const toastBox = document.getElementById("toast-undo");
          assert(toastBox.textContent.includes("Alpha removed from your wishlist."));
          button(toastBox, "Undo").click(); await flush();
          // Back at its old place (the second card), with its printing, notes and source.
          same(writes[1], {profile: "user1", action: "add", name: "Alpha", at: 1, set: "fdn", number: "1",
            notes: "A useful recommendation.", source: "magic/buylists/2026-10-01-user1-suggestions.md"});
          assert.equal(view.data.entries.length, 2);
        """)

    def test_undo_still_puts_the_card_back_after_leaving_the_page(self):
        self.run_js("""
          const view = show([alpha]);
          const writes = [];
          apiWrite = async (path, body) => { writes.push([path, body]); return saved(body.action === "add" ? [alpha] : []); };
          await removeWishlist(view, view.data.entries[0]);
          const toastBox = document.getElementById("toast-undo");
          // The page is left (another route draws) while the Undo toast is still up.
          routeToken += 1; clear(main).append("Deck library");
          button(toastBox, "Undo").click(); await flush();
          same(writes[1], ["/api/profiles/user1/wishlist", {profile: "user1", action: "add", name: "Alpha", at: 0,
            set: "fdn", number: "1", notes: "A useful recommendation.",
            source: "magic/buylists/2026-10-01-user1-suggestions.md"}]);
          assert.equal(main.textContent, "Deck library");
          assert(document.getElementById("toast").textContent.includes("Alpha is back on your wishlist."));
          // A failed Undo says so.
          const again = show([alpha]);
          await removeWishlist(again, again.data.entries[0]);
          apiWrite = async () => { throw new ApiError(0, "Connection lost"); };
          button(document.getElementById("toast-undo"), "Undo").click(); await flush();
          assert(document.getElementById("toast").textContent.includes("couldn't be put back"));
        """)

    def test_the_sheet_says_why_a_save_was_not_sent(self):
        self.run_js("""
          const view = show([alpha]);
          view.cards.querySelector(".card-tile-open").click();
          const sheet = openDialog();
          sheet.querySelector("textarea").value = "Changed";
          view.busy = true;
          sheet.querySelector('[data-action="save"]').click(); await flush();
          assert(sheet.querySelector(".box-crit").textContent.includes("Another change is still being saved"));
        """)

    def test_the_sheet_changes_notes_printing_and_source(self):
        self.run_js("""
          const view = show([alpha]);
          const writes = [];
          apiWrite = async (path, body) => { writes.push(body); return saved([alpha]); };
          view.cards.querySelector(".card-tile-open").click();
          let sheet = openDialog();
          sheet.querySelector("textarea").value = "For the Elves deck";
          sheet.querySelector('[data-action="save"]').click(); await flush();
          same(writes[0], {profile: "user1", action: "set", name: "Alpha", notes: "For the Elves deck"});
          // Nothing changed: Save just closes.
          view.cards.querySelector(".card-tile-open").click();
          sheet = openDialog();
          sheet.querySelector('[data-action="save"]').click(); await flush();
          assert.equal(writes.length, 1);
          // A printing chosen with the picker, and a source cleared.
          view.cards.querySelector(".card-tile-open").click();
          sheet = openDialog();
          pickPrinting = async () => ({set: "m19", number: "314", finish: "nonfoil", set_name: "Core Set 2019"});
          button(sheet, "Choose…").click(); await flush();
          assert(sheet.textContent.includes("M19 314"));
          sheet.querySelectorAll("input").find((i) => i.id.startsWith("wish-source")).value = "";
          sheet.querySelector('[data-action="save"]').click(); await flush();
          same(writes[1], {profile: "user1", action: "set", name: "Alpha", source: "", set: "m19", number: "314"});
        """)

    def test_add_and_remove_confirm_the_save(self):
        self.run_js("""
          const view = show();
          apiWrite = async (path, body) => saved(body.action === "add" ? [alpha] : []);
          await changeWishlist(view, {action: "add", name: "Alpha"}, "Alpha is on your wishlist.");
          assert.equal(view.data.entries.length, 1);
          assert(view.message.textContent.includes("on your wishlist"));
          assert.equal(view.cards.querySelector(".wishlist-mutate").disabled, false);
          await changeWishlist(view, {action: "remove", name: "Alpha"}, "Alpha removed.");
          assert.equal(view.data.entries.length, 0);
          assert.equal(view.warnings.textContent, "");
          assert.equal(view.busy, false);
        """)

    def test_loading_shows_saved_cards_and_says_changes_save(self):
        self.run_js("""
          api = async () => saved([alpha]);
          await showWishlist(routeToken);
          assert(main.textContent.includes("Alpha"));
          assert(main.textContent.includes("changes save at once"));
          assert(!main.textContent.includes("history"));
          assert.equal(main.querySelector(".box-warn"), null);
          assert.equal(main.querySelector(".wishlist-mutate").disabled, false);
        """)

    def test_typing_invalidates_results_and_late_search_cannot_replace_new_query(self):
        self.run_js("""
          const view = show(); const pending = [];
          api = path => new Promise(resolve => pending.push({path, resolve}));
          view.input.value = "al";
          const old = searchWishlist(view);
          view.matches = [alpha]; drawWishlistSearch(view);
          view.input.value = "be"; view.input.fire("input");
          assert.equal(view.matches.length, 0);
          assert.equal(view.searchResults.children.length, 0);
          const current = searchWishlist(view);
          pending[1].resolve({cards: [beta]}); await current;
          pending[0].resolve({cards: [alpha]}); await old;
          assert.equal(view.matches[0].name, "Beta");
          assert(view.searchResults.textContent.includes("Beta"));
          assert(!view.searchResults.textContent.includes("Alpha"));
          assert(pending[1].path.includes("detail=1"));
        """)

    def test_profile_switch_and_navigation_discard_late_reads_searches_and_writes(self):
        self.run_js("""
          let resolveRead;
          api = () => new Promise(resolve => {resolveRead = resolve;});
          const loading = showWishlist(routeToken);
          state.profile = state.profiles[1];
          clear(main); const matt = show();
          resolveRead(saved([alpha])); await loading;
          assert(main.textContent.includes("Matt's wishlist"));
          assert(!main.textContent.includes("Alpha"));

          state.profile = state.profiles[0]; clear(main); const user1 = show([alpha]);
          let resolveSearch, resolveWrite; let request;
          api = () => new Promise(resolve => {resolveSearch = resolve;});
          apiWrite = (path, body) => {request = {path, body}; return new Promise(resolve => {resolveWrite = resolve;});};
          user1.input.value = "be"; const search = searchWishlist(user1);
          const writing = changeWishlist(user1, {action: "remove", name: "Alpha"}, "Alpha removed.");
          state.profile = state.profiles[1]; clear(main); const next = show();
          resolveSearch({cards: [beta]}); resolveWrite(saved([]));
          await search; await writing;
          assert.equal(request.body.profile, "user1");
          assert.equal(next.cards.querySelectorAll(".card-tile").length, 0);
          assert.equal(next.message.textContent, "");
          assert.equal(user1.matches.length, 0);
          assert.equal(user1.data.entries.length, 1);
          const calls = [];
          apiWrite = async () => calls.push(1);
          await changeWishlist(user1, {action: "add", name: "Beta"}, "Beta added.");
          assert.equal(calls.length, 0);

          let resolveNavigation;
          api = () => new Promise(resolve => {resolveNavigation = resolve;});
          const leaving = showWishlist(routeToken);
          routeToken += 1; clear(main).append("Deck library");
          resolveNavigation(saved([alpha])); await leaving;
          assert.equal(main.textContent, "Deck library");
        """)

    def test_failed_write_preserves_cards_reenables_actions_and_allows_retry(self):
        self.run_js("""
          const view = show([alpha]); let rejectWrite, writes = 0;
          apiWrite = () => {writes++; return new Promise((resolve, reject) => {rejectWrite = reject;});};
          const pending = changeWishlist(view, {action: "remove", name: "Alpha"}, "Alpha removed.");
          assert(view.cards.querySelector(".wishlist-mutate").disabled);
          await changeWishlist(view, {action: "remove", name: "Alpha"}, "Alpha removed.");
          assert.equal(writes, 1);
          rejectWrite(new ApiError(0, "Connection lost")); await pending;
          assert.equal(view.data.entries.length, 1);
          assert.equal(view.cards.querySelector(".wishlist-mutate").disabled, false);
          assert(view.message.textContent.includes("Connection lost"));
          apiWrite = async () => saved([]);
          await changeWishlist(view, {action: "remove", name: "Alpha"}, "Alpha removed.");
          assert.equal(view.data.entries.length, 0);
        """)

    def test_offline_cards_can_be_removed(self):
        self.run_js("""
          const data = saved([alpha], {
            entries: [entry(alpha, {card: null, have: {owned: null, on_the_way: null}})]});
          const view = drawWishlist(data, state.profile, routeToken);
          assert(!view.cards.textContent.includes("0 owned"));
          assert(view.cards.textContent.includes("Card details unavailable"));
          let body;
          apiWrite = async (path, value) => {body = value; return saved([]);};
          view.cards.querySelector(".card-tile-open").click();
          button(openDialog(), "Remove").click(); await flush();
          same(body, {profile: "user1", action: "remove", name: "Alpha"});
          assert.equal(view.data.entries.length, 0);
        """)

    def test_removal_moves_focus_to_the_next_card(self):
        self.run_js("""
          const view = show([alpha, beta]);
          apiWrite = async () => saved([beta]);
          document.activeElement = document.body;
          await removeWishlist(view, view.data.entries[0]);
          const next = view.cards.querySelector(".card-tile-open");
          assert.equal(next.disabled, false);
          assert.equal(document.activeElement, next);
          assert.equal(next.focusOptions.preventScroll, true);
        """)

    def test_search_errors_empty_results_and_initial_error_remain_recoverable(self):
        self.run_js("""
          const view = show();
          view.input.value = "al";
          api = async () => {throw new ApiError(503, "Card data loading");};
          await searchWishlist(view);
          assert(view.searchStatus.textContent.includes("Card data loading"));
          assert(view.cards.textContent.includes("Your wishlist is empty"));
          api = async () => ({cards: []});
          await searchWishlist(view);
          assert(view.searchStatus.textContent.includes("No cards found"));
          api = async () => {throw new ApiError(500, "List unreadable");};
          await showWishlist(routeToken);
          assert(main.textContent.includes("Your wishlist couldn't be loaded"));
          assert(main.textContent.includes("Try again"));
        """)


if __name__ == "__main__":
    unittest.main()
