"""The app shell (decklab/UI-REVIEW.md 2.2, WP4): the routes table, the top bar's navigation and the phone's tab
bar for each kind of profile, the avatar menu ("This is my device", Settings for admins), crumbs, the page head's
More menu, the Settings page and the footer's one line.

Loads every page script in its real order into the event/DOM double (fixtures/workspace_ui_runner.js), with the
API stubbed: no browser, server, database write or Forge run.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = r"""
  editor = null;
  // The shell's fixed parts in index.html.
  for (const [tag, id] of [["nav", "main-nav"], ["nav", "tabbar"], ["ul", "more-list"], ["span", "avatar-initial"],
      ["button", "avatar-button"], ["div", "avatar-menu"], ["span", "menu-name"], ["button", "my-device"],
      ["button", "menu-reload"], ["button", "switch-profile"], ["span", "profile-name"], ["span", "signed-in"], ["div", "topbar-actions"],
      ["a", "topbar-back"], ["span", "topbar-back-label"], ["span", "topbar-title"], ["header", "topbar"],
      ["div", "admin-sep"], ["a", "menu-settings"], ["a", "menu-about"], ["p", "toast"], ["p", "footer-data"]]) {
    document.body.append(el(tag, { id }));
  }
  document.body.append(el("a", { class: "skip" }));
  setUpDialog = () => {}; setUpPeek = () => {}; startVersionMonitor = () => {};
  const store = (data = {}) => ({ getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v); },
    removeItem: (k) => { delete data[k]; }, data });
  window.localStorage = store(); window.sessionStorage = store();
  const PROFILES = [
    { id: "matt", name: "Matt", plays_as: "user", role: "admin", space: "home" },
    { id: "user1", name: "User1", plays_as: "wife", role: "member", space: "home" },
    { id: "user2", name: "User2", role: "member", space: "user2" }];
  const MAY = {
    matt: { admin: true, see_accessories: true, see_inventory: null },
    user1: { admin: false, see_accessories: true, see_inventory: ["home"] },
    user2: { admin: false, see_accessories: false, see_inventory: ["user2"] },
  };
  state.profiles = PROFILES;
  function as(id, remote = true) {
    state.profile = PROFILES.find((p) => p.id === id);
    state.may = MAY[id];
    state.remote = remote;
    clear(main);
  }
  async function flush(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); }
  const labels = (root) => root.querySelectorAll("[data-route]").map((a) => a.querySelector("span").textContent);
  const current = () => document.querySelectorAll("[aria-current]").map((a) => a.getAttribute("data-route"));
  api = async (path) => {
    if (path === "/api/shopping") return { orders: [{ components: [{ status: "pending" }] },
      { components: [{ status: "received" }, { status: "pending" }] }, { components: [{ status: "received" }] }] };
    if (path.endsWith("/settings")) return { theme: "system" };
    if (path === "/api/decks") return { warnings: [], halves: [], decks: [] };
    if (path === "/api/simulations") return { mode: "admins", may_start: true, may_edit: true, max_workers: 8, workers: null };
    throw new Error("unexpected " + path);
  };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShellUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_reload_is_available_to_members_from_the_avatar_menu(self):
        self.run_js("""
          let reloads = 0;
          reloadDeckLab = () => { reloads += 1; };
          as("user1", false);
          setUpShell(); drawShell();
          assert.equal(byId("menu-reload").hidden, false);
          byId("menu-reload").fire("click");
          assert.equal(reloads, 1);
        """)

    def test_one_name_per_page_from_the_routes_table(self):
        self.run_js("""
          const names = Object.fromEntries(ROUTES.map((r) => [r.path, r.label]));
          same(names, { library: "Decks", collection: "Collection", shopping: "Shopping", matchups: "Matchups",
            tokens: "Tokens", accessories: "Sleeves & boxes", assembly: "Build decks", play: "Game log",
            wishlist: "Wishlist", activity: "Activity", visibility: "Who sees what", settings: "Settings", deck: "Deck", edit: "Edit deck",
            new: "New deck", history: "History", variant: "Test of a change", receipt: "Receive delivery",
            matchup: "Matchup" });
          for (const r of ROUTES) assert(r.nav || r.parent, r.path);
          // A child page sits under its parent's place in the nav.
          assert.equal(routeSection("deck").path, "library");
          assert.equal(routeSection("history").path, "library");
          assert.equal(routeSection("receipt").path, "shopping");
          assert.equal(routeSection("matchup").path, "matchups");
          assert.equal(routeSection("nowhere").path, "library");
          // The lists' names (decision 2), for every page.
          same(LIST_NAME, { target: "Planned list", owned: "Play-now list" });
          assert.equal(listName("owned"), "Play-now list");
          assert.equal(listName("target", true), "planned list");
          assert.equal(listName("anything"), "Planned list");
          setTitle("Gruul Ramp");
          assert.equal(document.title, "Gruul Ramp – Deck Lab");
          assert.equal(document.getElementById("topbar-title").textContent, "Gruul Ramp");
        """)

    def test_the_nav_and_tab_bar_follow_who_is_looking(self):
        self.run_js("""
          as("matt", false);
          location.hash = "#/library";
          drawShell(); await flush();
          const nav = document.getElementById("main-nav"), bar = document.getElementById("tabbar");
          same(labels(nav), ["Decks", "Collection", "Shopping", "Matchups", "Tokens", "Sleeves & boxes", "Build decks",
            "Game log", "Wishlist", "Activity"]);
          same(labels(bar), ["Decks", "Collection", "Shopping", "Matchups"]);
          assert(bar.textContent.includes("More"));
          same(labels(document.getElementById("more-list")), ["Tokens", "Sleeves & boxes", "Build decks",
            "Game log", "Wishlist", "Activity", "Settings"]);
          assert(document.body.classList.contains("has-shell"));
          // The deliveries waiting: orders with a part still pending.
          const badge = nav.querySelector("[data-deliveries]");
          assert.equal(badge.hidden, false);
          assert.equal(badge.textContent, "2");
          // The badge is aria-hidden; its words are in the link's name, which starts with the visible word.
          assert.equal(badge.getAttribute("aria-hidden"), "true");
          assert.equal(badge.getAttribute("aria-label"), null);
          assert.equal(badge.closest("a").getAttribute("aria-label"), "Shopping, 2 deliveries waiting");
          assert.equal(bar.querySelector("[data-deliveries]").closest("a").getAttribute("aria-label"), "Shopping, 2 deliveries waiting");
          // Settings and About are an admin's.
          assert.equal(document.getElementById("menu-settings").hidden, false);
          assert.equal(document.getElementById("avatar-initial").textContent, "M");

          // A page marks its section: a deck page is under Decks, a token page under More.
          syncShell("deck");
          assert(current().every((path) => path === "library") && current().length >= 2);
          syncShell("tokens");
          assert(current().every((path) => path === "tokens"));
          assert(nav.querySelector(".nav-more").classList.contains("is-current"));
          assert(bar.querySelector(".tab-more").classList.contains("is-current"));

          // User1 (a member at home): no Settings, the rest as Matt.
          as("user1");
          drawShell(); await flush();
          assert.equal(document.getElementById("menu-settings").hidden, true);
          assert(!labels(document.getElementById("more-list")).includes("Settings"));
          assert(labels(nav).includes("Shopping"));
          // User2 (his own space): nothing of home's shopping, packing plan or sleeves; Matchups is the third tab.
          as("user2");
          drawShell(); await flush();
          same(labels(nav), ["Decks", "Collection", "Matchups", "Tokens", "Game log", "Wishlist", "Activity"]);
          same(labels(bar), ["Decks", "Collection", "Matchups"]);
          assert.equal(document.getElementById("my-device").hidden, true);       // over the tunnel: the login is him
          hideShell();
          assert.equal(document.getElementById("main-nav").hidden, true);
          assert.equal(document.getElementById("tabbar").hidden, true);
          assert(!document.body.classList.contains("has-shell"));
        """)

    def test_the_matchups_tab_has_a_dot_while_forge_plays(self):
        # E11-S30 slice 7: the casual tab bar's Matchups tab gets an 8 px dot while a run plays or waits; the
        # header's activity icon has the words.
        self.run_js("""
          document.body.append(el("div", { id: "shell-status" }));
          as("matt");
          location.hash = "#/library";
          drawShell(); await flush();
          const route = (root) => root.querySelectorAll("[data-route]").find((a) => a.getAttribute("data-route") === "matchups");
          const tab = route(document.getElementById("tabbar"));
          assert(tab && !tab.classList.contains("has-run"));
          noteRuns([{ status: "running", sides: [{ title: "A" }, { title: "B" }], done: 3, games: 10 }]);
          assert(tab.classList.contains("has-run"));
          assert(!route(document.getElementById("main-nav")).classList.contains("has-run"));
          noteRuns([]);
          assert(!tab.classList.contains("has-run"));
          stopRunsPill();
        """)

    def test_this_is_my_device_skips_who_and_the_away_timeout(self):
        self.run_js("""
          as("matt", false);
          drawShell(); await flush();
          assert.equal(isMyDevice(), false);
          toggleMyDevice();
          assert.equal(local.get("myDevice"), "matt");
          assert.equal(document.getElementById("my-device").getAttribute("aria-pressed"), "true");
          // Away for an hour: still Matt.
          session.set("hiddenAt", String(Date.now() - 60 * 60 * 1000));
          backFromAway();
          assert.equal(state.profile.id, "matt");
          // Opening Deck Lab again: no "Who are you?".
          state.profile = null; session.remove("profile");
          api = async (path) => {
            if (path === "/api/profiles") return { profiles: PROFILES };
            if (path === "/api/me") return { profile: null, name: null, remote: false, may: MAY.matt };
            if (path.endsWith("/settings")) return { theme: "system" };
            if (path === "/api/decks") return { warnings: [], halves: [], decks: [] };
            if (path === "/api/shopping") return { orders: [] };
            throw new Error("unexpected " + path);
          };
          await start(); await flush();
          assert.equal(state.profile.id, "matt");
          assert(!main.textContent.includes("Who are you?"));
          // Turned off: the shared iPad asks again after a while away.
          toggleMyDevice();
          assert.equal(local.get("myDevice"), null);
          session.set("hiddenAt", String(Date.now() - 60 * 60 * 1000));
          backFromAway(); await flush();
          assert.equal(state.profile, null);
          assert(main.textContent.includes("Who are you?"));
          // Someone else's device: User1 choosing on Matt's device doesn't make it hers.
          local.set("myDevice", "matt");
          await chooseProfile(PROFILES[1]); await flush();
          assert.equal(isMyDevice(), false);
        """)

    def test_crumbs_page_heads_and_menus(self):
        self.run_js("""
          as("matt", false);
          location.hash = "#/receipt?order=x";
          let chosen = 0;
          const head = pageHead({ crumb: ["#/shopping", "Shopping"], title: "Receive delivery", description: "MTGMate",
            primary: el("button", { class: "btn btn-primary", text: "Preview" }),
            more: [{ label: "Print", onclick: () => { chosen += 1; } }, "sep", { label: "Shopping", href: "#/shopping" }, null] });
          main.append(...head.filter(Boolean));
          same(state.crumb, { href: "#/shopping", label: "Shopping" });
          assert.equal(main.querySelector(".crumbs").textContent, "← Shopping");
          assert.equal(main.querySelector("h1").textContent, "Receive delivery");
          // The phone's top bar shows the same way back.
          const back = document.getElementById("topbar-back");
          assert.equal(back.hidden, false);
          assert.equal(back.getAttribute("href"), "#/shopping");
          assert.equal(document.getElementById("topbar-back-label").textContent, "Shopping");
          // One primary, the rest under More: it opens, closes on Esc, and a choice runs and closes it.
          const button = main.querySelector(".menu-button"), menu = main.querySelector(".menu");
          assert.equal(button.getAttribute("aria-haspopup"), "menu");
          assert.equal(menu.hidden, true);
          button.click();
          assert.equal(menu.hidden, false);
          assert.equal(button.getAttribute("aria-expanded"), "true");
          assert.equal(menu.querySelectorAll("[role=menuitem]").length, 2);
          menu.fire("keydown", { key: "Escape" });
          assert.equal(menu.hidden, true);
          assert.equal(button.getAttribute("aria-expanded"), "false");
          button.click();
          menu.querySelector("button").click();
          assert.equal(chosen, 1);
          assert.equal(menu.hidden, true);
          // A click elsewhere closes it, even on something that opens a dialog (a card row opening the viewer
          // has aria-haspopup); a click on its own button is left to the button.
          button.click();
          document.fire("click", { target: button });
          assert.equal(menu.hidden, false);
          const row = el("button", { "aria-haspopup": "dialog" });
          main.append(row);
          document.fire("click", { target: row });
          assert.equal(menu.hidden, true);
          assert.equal(button.getAttribute("aria-expanded"), "false");
          // A child page without a crumb of its own goes back to its parent route; a top page has the logo.
          state.crumb = null; location.hash = "#/matchup?key=k"; syncShellBack();
          assert.equal(back.getAttribute("href"), "#/matchups");
          location.hash = "#/collection"; syncShellBack();
          assert.equal(back.hidden, true);
        """)

    def test_settings_are_an_admins_and_the_footer_is_one_line(self):
        self.run_js("""
          showFooter = () => {};          // the version check is version.js's (test_version_ui)
          as("user1");
          showSettings(new URLSearchParams(), routeToken);
          assert(main.textContent.includes("settings are for admins"));
          assert.equal(main.querySelector("#sim-mode"), null);
          as("matt", false);
          showSettings(new URLSearchParams(), routeToken); await flush();
          assert.equal(document.title, "Settings – Deck Lab");
          for (const id of ["sim-mode", "sim-workers", "build-version", "build-check", "build-checked"]) {
            assert(main.querySelector("#" + id), id);
          }
          renderSimulations({ mode: "paused", may_start: false, may_edit: true, max_workers: 8, workers: 4, why_not: "paused" });
          same(main.querySelectorAll("[data-mode]").map((b) => [b.dataset.mode, b.getAttribute("aria-pressed")]),
            [["admins", "false"], ["everyone", "false"], ["paused", "true"]]);
          assert.equal(main.querySelector("#sim-settings").hidden, false);
          // The footer: the prices' date and the rate, nothing else.
          assert.equal(footerLine({ cards: { ready: true, price_date: "2026-10-12" }, fx: { rate: 1.4237, date: "2026-10-09" } }),
            "Prices 2026-10-12 · 1 USD = 1.4237 AUD");
          assert.equal(footerLine({ cards: { ready: false }, updating: true }), "Card data is downloading from Scryfall");
          // The address works for everyone through route(), and its nav place is an admin's only.
          assert.equal(navRoutes("account", PROFILES[1], MAY.user1).length, 0);
          assert.equal(navRoutes("account", PROFILES[0], MAY.matt)[0].path, "settings");
        """)

    def test_back_closes_a_sheet_and_the_tap_that_closes_a_menu_does_nothing_else(self):
        self.run_js("""
          const log = [];
          history.state = { pos: 0 }; history.length = 1;
          history.pushState = (s) => { log.push(["push", s]); history.state = s; history.length += 1; };
          history.replaceState = (s) => { log.push(["replace", s]); history.state = s; };
          history.back = () => { log.push(["back"]); history.state = { pos: 0 }; window.fire("popstate"); };
          const backs = () => log.filter((e) => e[0] === "back").length;
          // A sheet gets an entry at the next place; Back (onto place 0) closes it, and nothing steps back again.
          let closed = 0;
          const a = openSheet("A", { onClose: () => { closed += 1; } });
          same(log, [["push", { pos: 1, sheet: 1 }]]);
          history.state = { pos: 0 }; window.fire("popstate");
          assert(a.closed); assert.equal(closed, 1);
          flushTimers(); assert.equal(backs(), 0);
          // Closed with its button: Back steps off its entry, once.
          const b = openSheet("B"); b.close(); flushTimers();
          same(log.slice(-2), [["push", { pos: 1, sheet: 2 }], ["back"]]);
          // One closed and another opened at once (the receipt's Next card): the new one takes the old entry.
          const c = openSheet("C"), d = openSheet("D");
          d.close(); const e = openSheet("E"); flushTimers();
          same(history.state, { pos: 2, sheet: 5 }); assert.equal(backs(), 1);
          // Back closes only the sheets opened after the place it lands on.
          history.state = { pos: 1, sheet: 3 }; window.fire("popstate");
          assert(e.closed && !c.closed);
          c.close(); flushTimers(); assert.equal(backs(), 2);
          // The editor's "Leave without saving?" opens while the browser moves through history: no entry.
          const n = log.length; const f = openSheet("F", { history: false }); f.close(); flushTimers();
          assert.equal(log.length, n);

          // A tap outside an open menu closes it and does nothing else on a touch screen; a mouse click goes on.
          let coarse = true;
          window.matchMedia = (q) => ({ matches: q === "(pointer: coarse)" && coarse });
          const button = el("button", { "aria-controls": "test-menu" }), menu = el("div", { id: "test-menu", role: "menu" });
          const tile = el("button");
          document.body.append(button, menu, tile);
          menu.hidden = true; wireMenu(button, menu);
          const tap = () => document.fire("click", { target: tile, stopPropagation() { this.stopped = true; } });
          button.click(); assert.equal(menu.hidden, false);
          let ev = tap();
          assert(menu.hidden && ev.defaultPrevented && ev.stopped);
          ev = tap(); assert(!ev.defaultPrevented && !ev.stopped);           // no menu open: an ordinary tap
          coarse = false; button.click(); ev = tap();
          assert(menu.hidden && !ev.defaultPrevented && !ev.stopped);
        """)

    def test_the_same_space_order_everywhere(self):
        self.run_js("""
          state.profiles = [...PROFILES, { id: "user3", name: "User3", role: "member", space: "user3" },
            { id: "anna", name: "anna", role: "member", space: "anna" }];
          same(spaceList().map((s) => s.id), ["home", "anna", "user2", "user3"]);
          same(sortSpaces([{ id: "user2", name: "User2" }, { id: "home", name: "Home" }, { id: "anna", name: "anna" }])
            .map((s) => s.id), ["home", "anna", "user2"]);
        """)


if __name__ == "__main__":
    unittest.main()
