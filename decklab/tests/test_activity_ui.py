"""The Activity page: changes newest first, grouped by day, headlines, rows folded past the first few, filter
chips by kind and person, links and the card viewer, "Load older", and late answers dropped."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ActivityInteractionTests(unittest.TestCase):
    def run_js(self, scenario):
        setup = """
          clear(main);
          state.profiles = [{id: "user1", name: "User1"}, {id: "matt", name: "Matt"}];
          state.profile = state.profiles[0];
          location.hash = "#/activity";
          closeEditor = () => {}; stopMatchupRefresh = () => {};
          const now = new Date();
          const today = (h) => new Date(now.getFullYear(), now.getMonth(), now.getDate(), h, 5).toISOString();
          const change = (id, extra = {}) => ({id, at: today(9), actor: "user1", actor_name: "User1",
            source: "web", via: "home", message: `Change ${id}`, reason: null,
            headline: `User1 set the theme to dark ${id}`, kinds: ["settings"], link: null,
            rows: [{table: "profile_setting", op: "UPDATE", summary: `User1's theme: light → dark ${id}`,
                    before: {key: "theme", value: "light"}, after: {key: "theme", value: "dark"}}], ...extra});
          const page = (changes, next = null, cards = {}) => ({changes, next, everything: false, cards});
          const chips = (label) => [...main.querySelectorAll("a")].filter(a => a.getAttribute("class") === "filter-chip"
            && main.querySelector(`nav[aria-label=${label}]`)?.contains(a));
          const olderButton = () => [...main.querySelectorAll("button")].find(b => b.textContent === "Load older");
          const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_the_route_draws_changes_by_day_and_loads_older_ones(self):
        self.run_js("""
          const reads = [];
          const answers = {
            "/api/activity": page([change(9, {via: "tunnel", at: today(11)}),
                                   change(8, {actor: "claude", actor_name: "Claude", source: "cli", via: null,
                                              reason: "bought it"})], 8),
            "/api/activity?before=8": page([change(7), change(6, {at: "2026-01-05T02:00:00Z"})], 6),
            "/api/activity?before=6": page([change(5, {at: "2026-01-05T01:00:00Z"})]),
          };
          api = async path => { reads.push(path); return answers[path]; };
          apiWrite = async () => { throw new Error("Must not write"); };
          await route();
          same(reads, ["/api/activity"]);
          assert.equal(document.title, "Activity – Deck Lab");
          assert.equal(main.querySelector("h1").textContent, "Activity");
          let days = main.querySelectorAll(".activity-day");
          assert.equal(days.length, 1);
          assert.equal(days[0].querySelector(".activity-day-head").textContent, "Today");
          const cards = main.querySelectorAll(".activity-change");
          assert.equal(cards.length, 2);
          assert.equal(cards[0].querySelector(".activity-headline").textContent, "User1 set the theme to dark 9");
          assert.equal(cards[0].querySelector(".activity-where").textContent, "away");
          assert(cards[0].querySelector(".activity-when").textContent.includes("11:05"));
          // Deck Lab's own words for a page's save repeat the headline; one row that only repeats it is left out.
          assert.equal(cards[0].querySelector(".activity-message"), null);
          assert.equal(cards[0].querySelector(".activity-rows"), null);
          assert.equal(cards[1].querySelector(".activity-where").textContent, "from the command line");
          assert.equal(cards[1].querySelector(".activity-message").textContent, "“Change 8”");
          assert.equal(cards[1].querySelector(".activity-reason").textContent, "Why: bought it");
          const older = olderButton();
          assert.equal(older.hidden, false);
          older.click(); await settle();
          same(reads, ["/api/activity", "/api/activity?before=8"]);
          days = main.querySelectorAll(".activity-day");
          assert.equal(days.length, 2);           // change 7 continues today; change 6 starts its own day
          assert.equal(days[0].querySelectorAll(".activity-change").length, 3);
          assert(days[1].querySelector(".activity-day-head").textContent.includes("January 2026"));
          older.click(); await settle();
          assert.equal(main.querySelectorAll(".activity-day").length, 2);
          assert.equal(main.querySelectorAll(".activity-change").length, 5);
          assert.equal(older.hidden, true);
          assert.equal(main.querySelector(".activity-empty"), null);
        """)

    def test_filter_chips_by_kind_and_person_follow_the_address(self):
        self.run_js("""
          const reads = [];
          noteVisit = () => {};          // the router's visits beacon (test_visits) isn't one of the page's reads
          api = async path => { reads.push(path);
            return page([change(9), change(8, {actor: "matt", actor_name: "Matt", headline: "Matt saved Gruul"})], 8); };
          location.hash = "#/activity?kind=decks";
          await route();
          same(reads, ["/api/activity?kind=decks"]);
          const kinds = chips('"Kind of change"');
          assert.equal(kinds[0].textContent, "All");
          assert.equal(kinds[0].getAttribute("href"), "#/activity");
          const decks = kinds.find(a => a.textContent === "Decks");
          assert.equal(decks.getAttribute("aria-current"), "page");
          assert.equal(kinds.filter(a => a.getAttribute("aria-current")).length, 1);
          // People: everyone among the changes shown, each chip keeping the kind chosen.
          const people = chips('"Whose changes"');
          same(people.map(a => a.textContent), ["Everyone", "User1", "Matt"]);
          assert.equal(people[2].getAttribute("href"), "#/activity?kind=decks&actor=matt");
          assert.equal(people[0].getAttribute("aria-current"), "page");
          // Load older asks for the same filter.
          [...main.querySelectorAll("button")].find(b => b.textContent === "Load older").click(); await settle();
          same(reads, ["/api/activity?kind=decks", "/api/activity?before=8&kind=decks"]);
          // A person filtered by keeps their chip even with no change of theirs shown yet.
          reads.length = 0;
          api = async path => { reads.push(path); return page([], null); };
          location.hash = "#/activity?actor=user1&kind=nonsense";
          await route();
          same(reads, ["/api/activity?actor=user1"]);
          same(chips('"Whose changes"').map(a => a.textContent), ["Everyone", "User1"]);
          assert.equal(main.querySelector(".activity-empty").textContent, "No changes like these.Show every change");
          assert.equal(main.querySelector(".activity-empty").querySelector("a").getAttribute("href"), "#/activity");
        """)

    def test_kinds_a_viewer_cannot_have_are_not_offered(self):
        self.run_js("""
          state.profile = {id: "user2", name: "User2", space: "user2", role: "member"};
          state.may = {see_inventory: ["user2"]};
          api = async () => page([change(1, {actor: "user2", actor_name: "User2"})]);
          await route();
          const labels = chips('"Kind of change"').map(a => a.textContent);
          assert(!labels.includes("Shopping")); assert(!labels.includes("Sleeves & boxes"));
          assert(labels.includes("Decks")); assert(labels.includes("Wishlist"));
          // One person only: no person chips.
          assert.equal(chips('"Whose changes"').length, 0);
        """)

    def test_rows_fold_past_the_first_few_and_link_decks_cards_and_orders(self):
        self.run_js("""
          state.may = null;
          const elves = {name: "Llanowar Elves", type_line: "Creature — Elf Druid", mana_cost: "{G}", img_small: "/img/fdn/227/small"};
          const rows = [
            {table: "order_component", op: "UPDATE", summary: "Received order o-1 (cards) on 2026-10-12",
             before: {order_id: "o-1", id: "cards", status: "pending"}, after: {order_id: "o-1", id: "cards", status: "received"}},
            ...Array.from({length: 5}, (_, i) => ({table: "collection_card", op: "INSERT",
              summary: `Added 1 × Card ${i} to the home collection`, before: null,
              after: {space_id: "home", name: i === 0 ? "Llanowar Elves" : `Card ${i}`, set_code: "fdn", collector_number: "227"}})),
            {table: "deck", op: "UPDATE", summary: "Changed the deck Gruul", before: {id: "casual/gruul", title: "Gruul"},
             after: {id: "casual/gruul", title: "Gruul"}},
            {table: null, op: null, summary: "and 3 more"}];
          const receipt = change(5, {headline: "Matt received the Ronin Games order: 16 cards", link: {order: "o-1"},
            source: "receipt", message: "receive o-1", rows});
          const four = {name: "Card 4", type_line: "Instant", mana_cost: "{U}", img_small: "/img/fdn/4/small"};
          api = async () => page([receipt], null, {"Llanowar Elves|fdn|227": elves, "Card 4|fdn|227": four});
          let viewed = null;
          openCardViewer = (list, start, opts) => { viewed = {list, start, opts}; };
          await route();
          const card = main.querySelector(".activity-change");
          const head = card.querySelector(".activity-headline").querySelector("a");
          assert.equal(head.getAttribute("href"), "#/receipt?order=o-1");
          assert.equal(card.querySelector(".activity-message"), null);      // a receipt's own words
          const items = card.querySelector(".activity-rows").querySelectorAll("li");
          assert.equal(items.length, 8);
          assert.equal(items.filter(li => li.hidden).length, 4);
          assert.equal(items[0].querySelector("a").getAttribute("href"), "#/receipt?order=o-1");
          const elf = items[1].querySelector("button");
          assert.equal(elf.getAttribute("data-viewer"), "activity-5");
          elf.click();
          // The viewer swipes through every card of the change, the folded ones too.
          same(viewed.list.map(item => item.card.name), ["Llanowar Elves", "Card 4"]);
          assert.equal(viewed.start, 0);
          assert.equal(viewed.opts.trigger, elf);
          assert.equal(items[5].hidden, true);
          items[5].querySelector("button").click();
          assert.equal(viewed.start, 1);
          assert.equal(items[2].querySelector("button"), null);             // no card data sent: words only
          assert.equal(items[6].querySelector("a").getAttribute("href"), "#/deck?id=casual%2Fgruul&v=target");
          const all = card.querySelector(".activity-all");
          assert.equal(all.textContent, "Show all");
          all.click();
          assert.equal(items.filter(li => li.hidden).length, 0);
          assert.equal(all.getAttribute("aria-expanded"), "true");
          assert.equal(all.textContent, "Show fewer");
          all.click();
          assert.equal(items.filter(li => li.hidden).length, 4);
          // Someone who doesn't see home's inventory gets no receipt links.
          state.may = {see_inventory: ["user2"]};
          await route();
          assert.equal(main.querySelector(".activity-headline").querySelector("a"), null);
        """)

    def test_focus_moves_when_load_older_goes(self):
        self.run_js("""
          const answers = {"/api/activity": page([change(9)], 9), "/api/activity?before=9": page([change(8)], 8),
                           "/api/activity?before=8": page([change(7), change(6)], null)};
          api = async path => answers[path];
          await route();
          const older = olderButton();
          const note = main.querySelector(".activity-note");
          older.focus(); older.click(); await settle();
          assert.equal(document.activeElement, older);            // more to come: it stays on the button
          assert.equal(note.textContent, "");
          older.click(); await settle();
          assert.equal(older.hidden, true);
          const cards = main.querySelectorAll(".activity-change");
          assert.equal(document.activeElement, cards[2]);         // the first change the last page added
          assert.equal(cards[2].getAttribute("tabindex"), "-1");
          assert.equal(note.textContent, "That's every change.");
          // An empty last page: the note, which says so.
          answers["/api/activity"] = page([change(9)], 9); answers["/api/activity?before=9"] = page([], null);
          await route();
          olderButton().focus(); olderButton().click(); await settle();
          assert.equal(document.activeElement, main.querySelector(".activity-note"));
          assert.equal(document.activeElement.textContent, "There are no older changes.");
        """)

    def test_empty_replaced_messages_and_text_safety(self):
        self.run_js("""
          api = async () => page([]);
          await route();
          assert.equal(main.querySelector(".activity-empty").textContent, "Nothing you can see has changed yet.");
          assert.equal(olderButton().hidden, true);
          api = async () => ({changes: [], next: null, everything: true});
          await route();
          assert.equal(main.querySelector(".activity-empty").textContent, "Nothing has changed yet.");
          clear(main);
          activityDraw(page([change(1, {message: "User1's theme: light → dark 1", actor_name: "someone", source: "cli",
            rows: [{table: "x", op: "INSERT", summary: "User1's theme: light → dark 1"}]}),
            change(2, {message: "<b>Bold</b>", source: "migration", via: null})]), routeToken);
          const cards = main.querySelectorAll(".activity-change");
          assert.equal(cards[0].querySelector(".activity-message"), null);      // the summaries say it already
          assert.equal(cards[0].querySelector(".activity-headline").textContent, "User1 set the theme to dark 1");
          assert.equal(cards[1].querySelector(".activity-message").textContent, "“<b>Bold</b>”");
          assert.equal(cards[1].querySelector(".activity-where").textContent, "by an import");
          assert.equal(main.querySelector("b"), null);
        """)

    def test_only_a_command_and_an_id_is_hidden_never_a_short_note(self):
        self.run_js("""
          const cli = (id, message) => change(id, {source: "cli", via: null, message});
          api = async () => page([cli(1, "receive 2026-10-05-shop-c"), cli(2, "deck tables casual/gruul"),
                                  cli(3, "fix typo"), cli(4, "tuned sideboard plan"), cli(5, "swap shock")]);
          await route();
          const said = main.querySelectorAll(".activity-change").map(c => c.querySelector(".activity-message")?.textContent ?? null);
          same(said, [null, null, "“fix typo”", "“tuned sideboard plan”", "“swap shock”"]);
          assert.equal(activityCommandOnly("receive 2026-10-05-shop-c"), true);
          assert.equal(activityCommandOnly("Fix typo"), false);
        """)

    def test_an_empty_first_page_with_more_beyond_it(self):
        # The server scans only so many change sets per answer, so nothing visible isn't the end.
        self.run_js("""
          const answers = {"/api/activity": page([], 5), "/api/activity?before=5": page([], 3),
                           "/api/activity?before=3": page([change(2)], null)};
          api = async path => answers[path];
          await route();
          const empty = () => main.querySelector(".activity-empty");
          assert.equal(empty().textContent, "None you can see among the latest changes: Load older looks further back.");
          assert(!main.textContent.includes("Nothing has changed yet."));
          const older = olderButton();
          assert.equal(older.hidden, false);
          older.click(); await settle();
          assert(empty());
          older.click(); await settle();
          assert.equal(empty(), null);
          assert.equal(main.querySelectorAll(".activity-change").length, 1);
          assert.equal(older.hidden, true);
          // Reaching the end with nothing found says so in place of "Load older looks further back".
          answers["/api/activity"] = page([], 5); answers["/api/activity?before=5"] = page([], null);
          await route();
          olderButton().click(); await settle();
          assert.equal(empty().textContent, "Nothing you can see has changed yet.");
          assert.equal(olderButton().hidden, true);
        """)

    def test_late_older_answers_are_dropped(self):
        self.run_js("""
          api = async () => page([change(3)], 3);
          await route();
          const older = olderButton();
          const pending = [];
          api = () => new Promise(resolve => pending.push(resolve));
          older.click(); older.disabled = false; older.click();     // a second click supersedes the first
          pending[1](page([change(2)], null)); await settle();
          pending[0](page([change(1)], 1)); await settle();
          assert.equal(main.querySelectorAll(".activity-change").length, 2);
          assert(!main.textContent.includes("Change 1"));
          assert.equal(older.hidden, true);
          // An answer for a page that was left is dropped too.
          older.hidden = false; older.disabled = false; older.click();
          routeToken += 1;
          pending[2](page([change(0)], null)); await settle();
          assert(!main.textContent.includes("Change 0"));
        """)

    # The other area's change to core.js load() (a 503 with reason "database" shows the error box,
    # never the card-data wait) makes this run; until it's merged, load() waits for card data.
    @unittest.skipUnless('"database"' in (WEB / "core.js").read_text(encoding="utf-8"),
                         "core.js load() doesn't handle the database's 503 yet")
    def test_a_database_that_is_down_shows_an_error_with_retry(self):
        self.run_js("""
          api = async () => { throw new ApiError(503, "Deck Lab's database isn't reachable right now. Try again in a minute.",
                                                 {reason: "database"}); };
          await showActivity(new URLSearchParams(), routeToken);
          assert(main.textContent.includes("Activity couldn't be loaded"));
          assert(main.textContent.includes("database isn't reachable"));
          assert(main.textContent.includes("Try again"));
          assert(!main.textContent.includes("card data"));
        """)

    def test_failures_are_visible_with_retry(self):
        self.run_js("""
          api = async () => { throw new ApiError(500, "The audit trail couldn't be read."); };
          await showActivity(new URLSearchParams(), routeToken);
          assert(main.textContent.includes("Activity couldn't be loaded"));
          assert(main.textContent.includes("The audit trail couldn't be read."));
          assert(main.textContent.includes("Try again"));
          api = async () => page([change(3)], 3);
          await route();
          api = async () => { throw new ApiError(0, "The Deck Lab server can't be reached."); };
          olderButton().click(); await settle();
          assert(main.querySelector(".activity-note").textContent.includes("can't be reached"));
          assert.equal(olderButton().disabled, false);
        """)


if __name__ == "__main__":
    unittest.main()
