"""The page's side of accounts and member collections (HISTORY.md, "Accounts and member collections"):
remote start-up, controls hidden by /api/me's "may", the library grouped by space, and the Collection
page's editing wiring.

Loads every page script in its real order into the event/DOM double (fixtures/workspace_ui_runner.js),
with the API stubbed: no browser, server, inventory write or Forge run.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = r"""
  editor = null;
  for (const id of ["switch-profile", "profile-name", "signed-in", "topbar-actions", "theme-select", "toast"]) {
    document.body.append(el(id === "theme-select" ? "select" : "span", { id }));
  }
  document.body.append(el("a", { class: "skip" }));
  setUpDialog = () => {}; setUpPeek = () => {}; startVersionMonitor = () => {};
  const PROFILES = [
    { id: "matt", name: "Matt", plays_as: "user", role: "admin", space: "home" },
    { id: "user1", name: "User1", plays_as: "wife", role: "member", space: "home" },
    { id: "user2", name: "User2", role: "member", space: "user2" },
    { id: "user4", name: "User4", role: "member", space: "user4" }];
  const IDS = ["home", "user2", "user4"];
  const MAY = {
    // Matt's: an admin's rights are his own space's only (E10-S29); User1 changes home's collection (E10-S43).
    admin: { admin: true, runs: true, accessories: true, receipts: true, products: true, orders: true, see_accessories: true,
      spaces: ["home"], deck_spaces: ["home"], home_player: null, create: [{ space: "home", player: null }] },
    user1: { admin: false, runs: true, accessories: false, receipts: false, products: false, orders: false, see_accessories: true,
      spaces: ["home"], deck_spaces: [], home_player: "wife", create: [{ space: "home", player: "wife" }] },
    user2: { admin: false, runs: true, accessories: false, receipts: false, products: false, orders: false, see_accessories: false,
      spaces: ["user2"], deck_spaces: ["user2"], home_player: null, create: [{ space: "user2", player: null }] },
  };
  state.profiles = PROFILES;
  function as(id, may) {
    state.profile = PROFILES.find((p) => p.id === id);
    state.may = may;
    state.remote = id !== "matt";
    clear(main);
  }
  async function flush(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); }
  function button(root, text) {
    return root.querySelectorAll("button").find((b) => b.textContent.trim() === text) || null;
  }
  function openDialog() { return document.querySelectorAll("dialog").pop(); }
  window.matchMedia("(min-width: 600px)").matches = true;     // a tablet or bigger: the full editor (editor.js canBuildDecks)
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AccountsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    # ------------------------------------------------------------------ start-up

    def test_remote_start_skips_the_chooser_and_keeps_the_profile(self):
        self.run_js("""
          const asked = [];
          api = async (path) => {
            asked.push(path);
            if (path === "/api/profiles") return { profiles: PROFILES };
            if (path === "/api/me") return { profile: "user2", name: "User2", remote: true, may: MAY.user2 };
            if (path.endsWith("/settings")) return { theme: "system" };
            if (path === "/api/decks") return { warnings: [], halves: [], decks: [] };
            throw new Error("unexpected " + path);
          };
          location.search = "?profile=matt";          // ignored over the tunnel: the login is the profile
          await start(); await flush();
          assert.equal(state.profile.id, "user2");
          assert.equal(state.remote, true);
          same(state.may.spaces, ["user2"]);
          assert(!main.textContent.includes("Who are you?"));
          assert(main.textContent.includes("Decks"));
          assert.equal(document.getElementById("signed-in").textContent, "Signed in as User2");
          assert.equal(document.getElementById("signed-in").hidden, false);
          assert.equal(document.getElementById("switch-profile").hidden, true);
          await switchProfile(); backFromAway();
          assert.equal(state.profile.id, "user2");
          assert(asked.includes("/api/me"));
        """)

    def test_local_start_still_asks_who_you_are_and_the_profile_chosen_has_its_own_rights(self):
        self.run_js("""
          api = async (path) => {
            if (path === "/api/profiles") return { profiles: PROFILES };
            if (path === "/api/me") return { profile: null, name: null, remote: false, may: MAY.admin };
            if (path.endsWith("/settings")) return { theme: "system" };
            if (path === "/api/decks") return { warnings: [], halves: [], decks: [] };
            throw new Error("unexpected " + path);
          };
          await start(); await flush();
          assert.equal(state.profile, null);
          assert(main.textContent.includes("Who are you?"));
          // E10-S35: only the home's profiles are offered; members sign in through decklab.example.com.
          for (const name of ["Matt", "User1"]) assert(main.textContent.includes(name), name);
          for (const name of ["User2", "User4"]) assert(!main.textContent.includes(name), name);
          chooseProfile(PROFILES[2]); await flush();      // a person profile (as the tunnel's login would)
          assert.equal(state.profile.id, "user2");
          // E10-S03: User2 (here only as a person profile; E10-S35's chooser never offers him) has only his
          // own rights, as through the tunnel, so the page hides what the server would refuse.
          assert.equal(state.may.admin, false);
          same(state.may.spaces, ["user2"]);
          same(state.may.see_inventory, ["user2"]);
          assert.equal(canEditSpace("home"), false);
          assert.equal(canEditDeck({ id: "casual/house", space: "home", player: "either" }), false);
          assert.equal(canEditDeck({ id: "user2/casual/elves" }), true);
          assert.equal(mayDo("receipts"), false);
          assert.equal(isAdminProfile(), false);
          assert.equal(document.getElementById("switch-profile").hidden, false);
          assert.equal(document.getElementById("signed-in").hidden, true);
          chooseProfile(PROFILES[1]); await flush();      // User1: her own decks, and home's collection (E10-S43)
          assert.equal(state.may.admin, false);
          assert.equal(state.may.home_player, "wife");
          assert.equal(canEditSpace("home"), true);
          assert.equal(canEditSpace("user2"), false);
          assert.equal(canEditDeck({ id: "casual/hers", space: "home", player: "wife" }), true);
          assert.equal(canEditDeck({ id: "casual/his", space: "home", player: "user" }), false);
          assert.equal(mayDo("orders"), false);
          chooseProfile(PROFILES[0]); await flush();      // Matt: an admin by role, in his own space only (E10-S29)
          assert.equal(state.may.admin, true);
          assert.equal(canEditSpace("home"), true);
          assert.equal(canEditSpace("user2"), false);
          assert.equal(canEditDeck({ id: "user2/casual/elves" }), false);
          same(state.may.see_inventory, ["home"]);
        """)

    def test_at_home_me_is_asked_again_for_the_profile_chosen(self):
        # E10-S35: once someone is chosen, /api/me (now sent with their viewer header) answers for them,
        # and its "may" is used; an answer for someone else, or none at all, leaves deriveMay's.
        self.run_js("""
          const asked = [];
          let answer = (viewer) => ({ profile: viewer, name: viewer, remote: false,
            may: viewer === "user1" ? { ...MAY.user1, from: "server" } : null });
          api = async (path) => {
            if (path === "/api/profiles") return { profiles: PROFILES };
            if (path === "/api/me") {
              const viewer = state.profile ? state.profile.id : null;
              asked.push(viewer);
              return viewer ? answer(viewer) : { profile: null, name: null, remote: false, may: null };
            }
            if (path.endsWith("/settings")) return { theme: "system" };
            if (path === "/api/decks") return { warnings: [], halves: [], decks: [] };
            throw new Error("unexpected " + path);
          };
          await start(); await flush();
          await chooseProfile(PROFILES[1]); await flush();
          same(asked, [null, "user1"]);
          assert.equal(state.may.from, "server");             // the server's answer, not deriveMay's
          await chooseProfile(PROFILES[0]); await flush();     // an answer without "may": deriveMay's
          assert.equal(state.may.admin, true);
          answer = () => ({ profile: "user1", remote: false, may: MAY.user1 });
          await chooseProfile(PROFILES[0]); await flush();     // an answer for someone else is ignored
          assert.equal(state.may.admin, true);
          answer = () => { throw new ApiError(500, "down"); };
          await chooseProfile(PROFILES[1]); await flush();     // none at all: deriveMay's
          assert.equal(state.may.from, undefined);
          assert.equal(state.may.home_player, "wife");
        """)

    def test_the_home_chooser_never_picks_a_member(self):
        # E10-S35: at home ?profile= (or this visit's or this device's profile) picks only a home profile;
        # a member's name falls back to "Who are you?", which offers Matt and User1.
        self.run_js("""
          api = async (path) => {
            if (path === "/api/profiles") return { profiles: PROFILES };
            if (path === "/api/me") return { profile: null, name: null, remote: false, may: MAY.admin };
            if (path.endsWith("/settings")) return { theme: "system" };
            if (path === "/api/decks") return { warnings: [], halves: [], decks: [] };
            throw new Error("unexpected " + path);
          };
          location.search = "?profile=user2";
          await start(); await flush();
          assert.equal(state.profile, null);
          assert(main.textContent.includes("Who are you?"));
          same(homeProfiles().map((p) => p.id), ["matt", "user1"]);
          assert(!main.textContent.includes("User2"));
          location.search = "?profile=user1";
          await start(); await flush();
          assert.equal(state.profile.id, "user1");
        """)

    def test_an_older_server_without_may_falls_back_to_the_same_rules(self):
        self.run_js("""
          same(deriveMay(PROFILES[2], true).deck_spaces, ["user2"]);
          same(deriveMay(PROFILES[1], true).create, [{ space: "home", player: "wife" }]);
          // A profile chosen on the home network has its own rights there too (E10-S03), and nobody chosen
          // has nothing anywhere, as the server answers a request that isn't a script's (E10-S35).
          assert.equal(deriveMay(PROFILES[1], false).admin, false);
          same(deriveMay(PROFILES[1], false), deriveMay(PROFILES[1], true));
          same(deriveMay(PROFILES[2], false), deriveMay(PROFILES[2], true));
          assert.equal(deriveMay(PROFILES[0], false).admin, true);
          for (const remote of [false, true]) {
            const nobody = deriveMay(null, remote);
            same([nobody.admin, nobody.accessories, nobody.see_accessories, nobody.see_inventory, nobody.spaces,
                  nobody.create], [false, false, false, [], [], []]);
          }
          assert.equal(deriveMay(PROFILES[0], true).accessories, true);
        """)

    # ------------------------------------------------------------ hidden controls

    def test_deck_page_offers_edit_only_on_decks_the_visitor_may_change(self):
        self.run_js("""
          const page = (summary) => ({ summary: { read_only: false, ...summary }, versions: ["target"], version: "target" });
          const words = (node) => node ? node.textContent : "";
          as("user1", MAY.user1);
          assert(words(deckActions(page({ id: "casual/hers", space: "home", player: "wife" }))).includes("Edit"));
          const theirs = words(deckActions(page({ id: "casual/house", space: "home", player: "either" })));
          assert(theirs.includes("Try a change") && !theirs.includes("Edit"));
          as("user2", MAY.user2);
          assert(words(deckActions(page({ id: "user2/casual/elves", space: "user2", player: null }))).includes("Edit"));
          assert(words(deckActions(page({ id: "casual/hers", space: "home", player: "wife" }))).includes("Try a change"));
          // A product deck is saved as a new deck only by someone who may add decks, into their own space.
          const product = deckActions({ summary: { id: "product/x/a", read_only: true }, versions: ["target"], version: "target" });
          assert.equal(product.querySelector("a").getAttribute("href"), "#/new?from=product%2Fx%2Fa&space=user2");
          // On a phone: Edit (the Quick edit) and Save as a new deck stay; Try a change needs a tablet or bigger.
          window.matchMedia("(min-width: 600px)").matches = false;
          assert(words(deckActions(page({ id: "user2/casual/elves", space: "user2", player: null }))).includes("Edit"));
          assert.equal(deckActions(page({ id: "casual/hers", space: "home", player: "wife" })), null);
          assert(words(deckActions({ summary: { id: "product/x/a", read_only: true }, versions: ["target"], version: "target" }))
            .includes("Save as a new deck"));
          window.matchMedia("(min-width: 600px)").matches = true;
          as("user4", { ...MAY.user2, spaces: [], deck_spaces: [], create: [] });
          assert.equal(deckActions({ summary: { id: "product/x/a", read_only: true }, versions: ["target"], version: "target" }), null);
          // The editor opens someone else's deck for trying changes, without Save.
          as("user1", MAY.user1);
          assert.equal(canEditDeck({ id: "casual/house", space: "home", player: "either" }), false);
          assert.equal(canEditDeck({ id: "user2/casual/elves" }), false);
          as("matt", MAY.admin);                  // an admin edits only his own space's decks (E10-S29)
          assert.equal(canEditDeck({ id: "user2/casual/elves" }), false);
          assert.equal(canEditDeck({ id: "casual/house", space: "home", player: "either" }), true);
        """)

    def test_accessories_and_receipts_are_read_only_for_members(self):
        self.run_js("""
          const data = { items: [{ id: "ds-black", kind: "sleeves", name: "Matte", brand: "Dragon Shield", quantity: 100,
            used_by: [] }], products: [] };
          as("user1", MAY.user1);
          drawAccessories(data, routeToken);
          assert(main.textContent.includes("Matte"));
          // Click to edit: a tile opens its sheet (Remove is at its bottom) only for someone who may change them.
          const edits = () => main.querySelectorAll("button").filter((b) => (b.getAttribute("aria-label") || "").startsWith("Edit "));
          for (const text of ["Add", "Edit", "Remove"]) assert.equal(button(main, text), null, text);
          assert.equal(edits().length, 0);
          assert(main.textContent.includes("Read only"));
          as("matt", MAY.admin);
          drawAccessories(data, routeToken);
          assert(button(main, "Add"));
          assert.equal(edits().length, 1);
          assert.equal(button(main, "Remove"), null);
          const delivery = { order: "o1", seller: "Shop", notes: "", components: [{ id: "cards", kind: "cards",
            status: "pending", checks: ["Check finish"], fields: ["name", "quantity"], rows: [{ name: "Alpha", quantity: "2" }] }] };
          as("user2", MAY.user2);
          drawReceipt(delivery, routeToken);
          // The Receipts board read only: the tile, no ticks and no Preview.
          assert(main.textContent.includes("Alpha"));
          assert(main.textContent.includes("read only"));
          assert.equal(main.querySelector(".rcpt-tick"), null);
          assert.equal(button(main, "Preview"), null);
          as("matt", MAY.admin);
          drawReceipt(delivery, routeToken);
          assert(main.querySelector(".rcpt-tick"));
          assert(button(main, "Preview"));
        """)

    def test_accessories_are_hidden_from_person_spaces(self):
        # The sleeves, deck boxes and playmats are the home's: User2 (his own space) sees none of them, through
        # the tunnel ("may" says so) or chosen on the home network (app.js says so); User1 and Matt do.
        self.run_js("""
          const kit = { sleeves: { name: "Black Matte", label: "Black Matte", state: "linked", quantity: 100, image_url: null },
            deck_box: null, short: 0, need: 60, warnings: ["Too few sleeves"] };
          const deck = { id: "casual/gruul", space: "home", player: "user", kind: "casual", title: "Gruul", status: "built",
            versions: ["target"], missing: { target: 0 }, on_the_way: { target: 0 }, kit, sleeves: "black-matte" };
          const data = { warnings: [], halves: [], decks: [deck] };
          const page = { summary: { ...deck, read_only: false, card_count: 60, sideboard_count: 0, holder_sha256: "s" },
            versions: ["target"], version: "target", warnings: ["Too few sleeves", "Other"], info: [] };
          const links = () => main.querySelectorAll("a").map((a) => a.getAttribute("href"));
          for (const [who, sees] of [["matt", true], ["user1", true], ["user2", false]]) {
            as(who, MAY[who === "matt" ? "admin" : who]);
            assert.equal(mayDo("see_accessories"), sees, who);
            drawLibrary(data, libraryFilters(new URLSearchParams("all=1")));
            assert.equal(navRoutes("more").some((r) => r.path === "accessories"), sees, who);     // the shell's nav
            assert.equal(main.textContent.includes("Black Matte"), sees, who);
            assert.equal(deckKit(page) !== null, sees, who);
            same(deckWarnings(page), sees ? ["Too few sleeves", "Other"] : ["Other"]);
            const assembly = assemblyKit({ kit, sleeves: "Black Matte" }, 60);
            assert.equal(assembly !== null, sees, who);
            editor = { mode: "edit", space: "home", fields: { status: "built" }, base: { fields: { status: "built" } } };
            assert.equal(fieldOffered("sleeves"), sees, who);
            assert.equal(fieldOffered("deck_box"), sees, who);
            editor = null;
          }
          // The page itself says why, and never asks the server for the list.
          as("user2", MAY.user2);
          api = async (path) => { throw new Error("unexpected " + path); };
          location.hash = "#/accessories"; route(); await flush();
          // Its words name no space (E10-S38).
          assert(main.textContent.includes("The sleeves, deck boxes and playmats are private."));
          assert(!main.textContent.includes("home"));
          location.hash = "#/library";
          // On the home network a server whose /api/me answers for nobody (an older one): deriveMay decides.
          state.remote = false; state.me = { profile: null, remote: false, may: MAY.admin };
          api = async (path) => {
            if (path.endsWith("/settings")) return { theme: "system" };
            if (path === "/api/decks") return data;
            throw new Error("unexpected " + path);
          };
          for (const [i, sees] of [[0, true], [1, true], [2, false], [3, false]]) {
            await chooseProfile(PROFILES[i]); await flush();
            assert.equal(state.may.admin, i === 0, PROFILES[i].id);      // by role (E10-S03)
            assert.equal(mayDo("see_accessories"), sees, PROFILES[i].id);
            assert.equal(mayDo("accessories"), sees, PROFILES[i].id);
          }
          // An older server's "may" without the key: worked out the same way.
          assert.equal(deriveMay(PROFILES[2], true).see_accessories, false);
          assert.equal(deriveMay(PROFILES[1], true).see_accessories, true);
          state.may = { admin: true }; assert.equal(mayDo("see_accessories"), true);
        """)

    def test_accessory_pictures_name_the_viewer_on_the_home_network(self):
        # An <img> sends no X-Deck-Lab-Viewer header, so at home its address names the profile chosen
        # (the server answers for it); through the tunnel the login decides, and the crop stays out of it.
        self.run_js("""
          const url = "/accessory-img/black.png?v=0123abcd#crop=0.1,0.2,0.5,0.5";
          state.remote = false; state.profile = PROFILES[2];
          assert.equal(accImgSrc(url), "/accessory-img/black.png?v=0123abcd&viewer=user2");
          assert.equal(accImgSrc("/accessory-img/staged/" + "a".repeat(32) + ".png"),
            "/accessory-img/staged/" + "a".repeat(32) + ".png?viewer=user2");
          const img = accessoryThumb({ label: "Matte", image_url: url }, 96).querySelector("img");
          assert.equal(img.getAttribute("src"), "/accessory-img/black.png?v=0123abcd&viewer=user2");
          assert.equal(accWithCrop(url), "/accessory-img/black.png?v=0123abcd");    // comparisons unaffected
          state.profile = null;
          assert.equal(accImgSrc(url), "/accessory-img/black.png?v=0123abcd");
          state.remote = true; state.profile = PROFILES[1];
          assert.equal(accImgSrc(url), "/accessory-img/black.png?v=0123abcd");
        """)

    def test_tokens_page_edits_only_editable_spaces_and_sends_the_space(self):
        self.run_js("""
          const row = { key: "r0", front: "Elf Warrior", back: "", set: "", front_collector_number: "",
            back_collector_number: "", finish: "", quantity: 2, front_details: "", back_details: "", notes: "", uses: [] };
          const data = { space: "user2", sha256: "t1", rows: [row], missing: [], incoming: [], face_names: [] };
          as("user1", MAY.user1);
          let view = drawTokens(data, routeToken, "user2");
          assert(main.textContent.includes("User2's tokens"));
          assert.equal(button(main, "Add a token card"), null);
          const edit = () => main.querySelectorAll("button").find((b) => b.getAttribute("aria-label") === "Edit Elf Warrior");
          assert.equal(edit(), undefined);
          const picker = main.querySelector(".tok-spaces");
          same(picker.querySelectorAll("a").map((a) => a.textContent), ["Home", "User2", "User4"]);
          as("user2", MAY.user2);
          view = drawTokens(data, routeToken, "user2");
          assert(button(main, "Add a token card") && edit());
          same(tokBody(view, { action: "add" }), { action: "add", space: "user2" });   // every write names the space
          // A server that doesn't know spaces yet (no "space" in its answer) shows nothing for a person.
          clear(main); drawTokens({ ...data, space: undefined }, routeToken, "user2");
          assert(main.textContent.includes("can't be shown until"));
          assert.equal(button(main, "Add a token card"), null);
        """)

    def test_new_deck_goes_where_the_visitor_may_add_decks(self):
        self.run_js("""
          const decks = { warnings: [], halves: [], decks: [] };
          const newHref = () => main.querySelectorAll("a").find((a) => a.textContent === "New deck");
          as("user1", MAY.user1); drawLibrary(decks, libraryFilters(new URLSearchParams()));
          assert.equal(newHref().getAttribute("href"), "#/new");
          as("user2", MAY.user2); drawLibrary(decks, libraryFilters(new URLSearchParams()));
          assert.equal(newHref().getAttribute("href"), "#/new?space=user2");
          as("user4", { ...MAY.user2, create: [] }); drawLibrary(decks, libraryFilters(new URLSearchParams()));
          assert.equal(newHref(), undefined);
          // Where a new deck goes, and its Played by.
          as("user1", MAY.user1);
          assert.equal(newDeckSpace("user2"), "home");
          assert.equal(newDeckPlayer("home"), "wife");
          same(allowedPlayers().map(([v]) => v), ["wife"]);
          as("matt", MAY.admin);                  // only in his own space (E10-S30, E10-S29)
          assert.equal(newDeckSpace("user2"), "home");
          assert.equal(newDeckPlayer("user2"), null);
          same(allowedPlayers().map(([v]) => v), ["user", "wife", "either"]);
        """)

    # ----------------------------------------------------------------- library

    def test_library_groups_decks_by_space_and_mine_follows_the_space(self):
        self.run_js("""
          const deck = (id, space, player, kind = "casual") => ({ id, space, player, kind, title: id, status: "idea",
            versions: ["target"], missing: { target: 0 }, on_the_way: { target: 0 } });
          const data = { warnings: [], halves: [], decks: [deck("casual/gruul", "home", "user"),
            deck("casual/angels", "home", "wife"), deck("user4/commander/dragons", "user4", null, "commander"),
            deck("user2/casual/elves", "user2", null)] };
          as("matt", MAY.admin);
          drawLibrary(data, libraryFilters(new URLSearchParams("all=1")));
          const parts = main.querySelectorAll("[data-space]").map((p) => p.dataset.space);
          same(parts, ["home", "user2", "user4"]);             // home first, then people by name
          const user2 = main.querySelector('[data-space="user2"]');
          assert.equal(user2.tag, "details");
          assert(user2.textContent.includes("User2's decks") && user2.textContent.includes("user2/casual/elves"));
          assert(main.querySelector('[data-space="user4"]').textContent.includes("Commander decks"));
          // Matt's own: the home decks Played by him (no people's parts).
          clear(main); drawLibrary(data, libraryFilters(new URLSearchParams()));
          assert.equal(main.querySelector('[data-space="user2"]'), null);
          assert(main.textContent.includes("casual/gruul") && !main.textContent.includes("casual/angels"));
          // User2's own: the decks in his space.
          as("user2", MAY.user2);
          clear(main); drawLibrary(data, libraryFilters(new URLSearchParams()));
          assert(main.textContent.includes("user2/casual/elves"));
          assert(!main.textContent.includes("casual/gruul"));
          assert(main.textContent.includes("3 decks of other people are hidden"));
          // A deck summary without "space" is placed by its id.
          assert.equal(isMyDeck({ id: "user2/casual/old" }), true);
        """)

    # -------------------------------------------------------------- collection

    def test_collection_controls_follow_editable_and_the_space_picker(self):
        self.run_js("""
          const row = { name: "Llanowar Elves", set: "fdn", collector_number: "227", finish: "nonfoil", quantity: 2,
            condition: "NM", language: "en", notes: "" };
          const spaces = [{ id: "home", name: "Home" }, { id: "user2", name: "User2" }];
          as("user1", MAY.user1);
          drawCollectionRows({ space: "user2", sha256: "s1", rows: [row], editable: false, spaces }, "user2");
          assert(main.textContent.includes("User2's collection") && main.textContent.includes("Llanowar Elves"));
          const edits = () => main.querySelectorAll("button").filter((b) => (b.getAttribute("aria-label") || "").startsWith("Edit "));
          for (const text of ["Add card", "Import cards…", "Add a precon…", "Edit", "Remove"]) assert.equal(button(main, text), null, text);
          assert.equal(edits().length, 0);
          assert(main.textContent.includes("Read only"));
          same(main.querySelector(".col-spaces").querySelectorAll("a").map((a) => a.getAttribute("href")),
            ["#/collection?view=rows", "#/collection?space=user2&view=rows"]);
          as("user2", MAY.user2);
          drawCollectionRows({ space: "user2", sha256: "s1", rows: [row], editable: true, spaces }, "user2");
          for (const text of ["Add card", "Import cards…", "Add a precon…"]) assert(button(main, text), text);
          // Click to edit: the row's name opens its sheet; there's no Edit and Remove pair on each row.
          same(edits().map((b) => b.getAttribute("aria-label")), ["Edit Llanowar Elves (FDN 227)"]);
          assert.equal(button(main, "Remove"), null);
          same(main.querySelector(".col-spaces").querySelectorAll("a").map((a) => a.getAttribute("href")),
            ["#/collection?space=home&view=rows", "#/collection?space=user2&view=rows"]);
          // The Find cards view takes the space too.
          drawCollection({ space: "user2", spaces, editable: true, types: [], roles: [], total: 0, page: 1, pages: 1,
            note: "", warnings: [], cards: [] }, new URLSearchParams(), "user2");
          assert(button(main, "Add card") && button(main, "Import cards…"));
          assert.equal(colPath("/api/collection", "user2", new URLSearchParams("q=elf")), "/api/collection?q=elf&space=user2");
          assert.equal(colPath("/api/collection/rows", "home"), "/api/collection/rows");
        """)

    def test_download_saves_the_spaces_collection_for_whoever_sees_it(self):
        # E7-S30: in More for anyone the collection page answers, read only too; the server names the file.
        self.run_js("""
          const row = { name: "Llanowar Elves", set: "fdn", collector_number: "227", finish: "nonfoil", quantity: 2,
            condition: "NM", language: "en", notes: "" };
          as("user2", MAY.user2);
          const cv = drawCollectionRows({ space: "user2", sha256: "s1", rows: [row], editable: false }, "user2");
          assert(button(main, "Download collection (CSV)"));
          const paths = [], saved = [];
          api = async (path) => { paths.push(path);
            return { space: "user2", filename: "user2-collection-2026-10-25.csv", csv: "name,set\\n" }; };
          globalThis.Blob = class { constructor(parts, options) { this.parts = parts; this.type = options.type; } };
          globalThis.URL = { createObjectURL: (blob) => { saved.push(blob); return "blob:1"; }, revokeObjectURL: () => {} };
          const append = document.body.append;
          let link = null;
          document.body.append = (node) => { link = node; node.click = () => {}; };
          await downloadCollection(cv);
          document.body.append = append;
          same(paths, ["/api/collection/download?space=user2"]);
          assert.equal(link.getAttribute("download"), "user2-collection-2026-10-25.csv");
          assert.equal(link.getAttribute("href"), "blob:1");
          same(saved[0].parts, ["name,set\\n"]);
          assert.equal(saved[0].type, "text/csv;charset=utf-8");
          // A refusal is said on the page, and nothing is saved.
          api = async () => { throw new ApiError(403, "That collection isn't public."); };
          await downloadCollection(cv);
          assert(main.textContent.includes("The collection couldn't be downloaded: That collection isn't public."));
          assert.equal(saved.length, 1);
        """)

    def test_add_card_sheet_picks_a_printing_and_saves_to_the_space(self):
        self.run_js("""
          as("user2", MAY.user2);
          const cv = drawCollectionRows({ space: "user2", sha256: "s1", rows: [], editable: true }, "user2");
          api = async (path) => {
            assert.equal(path, "/api/printings?name=llanowar%20elves");
            return { name: "Llanowar Elves", printings: [
              { set: "fdn", set_name: "Foundations", collector_number: "227", finishes: ["nonfoil", "foil"], released: "2024-11-15" },
              { set: "m19", set_name: "Core Set 2019", collector_number: "314", finishes: ["nonfoil"], released: "2018-07-13" }] };
          };
          const ctx = openCollectionSheet(cv);
          ctx.inputs.name.value = "llanowar elves";
          await loadColPrintings(ctx, ctx.inputs.name.value);
          assert.equal(ctx.inputs.name.value, "Llanowar Elves");      // Scryfall's exact name
          // The printing strip: a tile per printing; the chosen one's finishes, then the condition, as segments.
          const strip = ctx.strip.querySelectorAll(".col-strip-tile");
          same(strip.map((b) => b.getAttribute("aria-label")), ["FDN 227, Foundations, 2024", "M19 314, Core Set 2019, 2018"]);
          strip[0].click();
          assert.equal(ctx.chosen, 0);
          button(ctx.finishBox, "Foil").click();
          ctx.inputs.quantity.value = "3";
          button(ctx.inputs.condition, "NM").click();
          const calls = [];
          const saved = { name: "Llanowar Elves", set: "fdn", collector_number: "227", finish: "foil", quantity: 3,
            condition: "NM", language: "", notes: "" };
          apiWrite = async (path, body) => { calls.push([path, body]); return { ok: true, sha256: "s2", rows: [saved] }; };
          await saveCollectionSheet(ctx);
          same(calls, [["/api/collection/save", { space: "user2", sha256: "s1", action: "add", row: saved }]]);
          assert.equal(cv.sha256, "s2");
          assert(main.textContent.includes("Llanowar Elves") && main.textContent.includes("FDN 227 · Foil"));
          assert(main.textContent.includes("Llanowar Elves (FDN 227 · Foil) added."));
          assert.equal(button(main, "Retry saving history"), null);
        """)

    def test_a_conflicting_edit_is_put_back_on_top_of_the_latest_rows(self):
        self.run_js("""
          as("user2", MAY.user2);
          const row = { name: "Llanowar Elves", set: "fdn", collector_number: "227", finish: "nonfoil", quantity: 2,
            condition: "NM", language: "en", notes: "" };
          const cv = drawCollectionRows({ space: "user2", sha256: "s1", rows: [row], editable: true }, "user2");
          api = async () => ({ name: "Llanowar Elves", printings: [
            { set: "fdn", set_name: "Foundations", collector_number: "227", finishes: ["nonfoil"], released: "2024" }] });
          const ctx = openCollectionSheet(cv, row); await flush();
          assert.equal(ctx.chosen, 0);
          ctx.inputs.quantity.value = "4";
          const theirs = { ...row, notes: "binder page 3" };
          const calls = [];
          apiWrite = async (path, body) => {
            calls.push(body);
            if (calls.length === 1) throw new ApiError(409, "Someone changed the collection.", { sha256: "s9", rows: [theirs] });
            return { ok: true, sha256: "s10", rows: [{ ...theirs, quantity: 4 }], commit: { ok: true } };
          };
          await saveCollectionSheet(ctx);
          const dialog = openDialog();
          assert(dialog.textContent.includes("Notes (blank) → binder page 3"));
          button(dialog, "Load the latest and re-apply my changes").click(); await flush();
          assert.equal(calls.length, 2);
          assert.equal(calls[1].sha256, "s9");
          same(calls[1].original, { set: "fdn", collector_number: "227", finish: "nonfoil" });
          assert.equal(calls[1].row.quantity, 4);
          assert.equal(calls[1].row.notes, "binder page 3");
          assert.equal(cv.sha256, "s10");
        """)

    def test_import_previews_problems_then_applies_skipping_them(self):
        self.run_js("""
          as("user2", MAY.user2);
          const cv = drawCollectionRows({ space: "user2", sha256: "s1", rows: [], editable: true }, "user2");
          let routed = 0; route = () => { routed += 1; };
          const calls = [];
          apiWrite = async (path, body) => {
            calls.push([path, body]);
            if (path.endsWith("/preview")) return { token: "tok1", format: "ManaBox", dropped_basics: 2,
              adds: { rows: 2, cards: 5 }, problems: [{ line: 4, message: "No card named Llanowar Elfs" }],
              rows: [{ line: 2, name: "Llanowar Elves", set: "fdn", collector_number: "227", finish: "nonfoil", quantity: 4,
                condition: "", language: "", notes: "" },
                { line: 4, name: "Llanowar Elfs", set: "", collector_number: "", finish: "nonfoil", quantity: 1,
                  condition: "", language: "", notes: "" }] };
            return { ok: true, sha256: "s2", added: { rows: 2, cards: 5 }, skipped: 1, commit: { ok: true } };
          };
          const ctx = openImportSheet(cv);
          await previewImport(ctx, "cards.csv", "Name,Quantity\\n...");
          same(calls[0], ["/api/collection/import/preview", { space: "user2", filename: "cards.csv", text: "Name,Quantity\\n..." }]);
          const dialog = openDialog();
          assert(dialog.textContent.includes("Line 4: No card named Llanowar Elfs"));
          assert(dialog.textContent.includes("2 plain basic lands left out"));
          assert.equal(dialog.querySelectorAll(".col-problem").length, 1);
          assert.equal(button(dialog, "Import 5 cards"), null);
          button(dialog, "Skip 1 row with problems and import 5 cards").click(); await flush();
          same(calls[1], ["/api/collection/import/apply", { space: "user2", token: "tok1", sha256: "s1", skip_problems: true }]);
          assert.equal(routed, 1);
          assert(state.colNotice.words.includes("Imported 5 cards (2 rows). 1 row with problems skipped."));
        """)


    # ------------------------------------------------------------------ stopping runs

    def test_only_an_admin_is_shown_stop(self):
        # E10-S30's interim rule ("run.stop"): the server refuses anyone else, so the page offers Stop only to
        # an admin, on a field run (fvLive), as on a matchup and a test of a change.
        self.run_js(r"""
          const live = { status: "running", job: { done: 1, total: 4, pairs: {} } };
          const stopShown = () => fvLive({}, live).some((node) => node && node.querySelectorAll &&
            node.querySelectorAll("button").some((b) => b.textContent.trim() === "Stop"));
          as("matt", MAY.admin);
          assert.equal(mayStopRuns(), true);
          assert.equal(stopShown(), true);
          as("user1", MAY.user1);
          assert.equal(mayStopRuns(), false);
          assert.equal(stopShown(), false);
          as("user2", MAY.user2);
          assert.equal(mayStopRuns(), false);
          state.profile = null;
          assert.equal(mayStopRuns(), false);
        """)


if __name__ == "__main__":
    unittest.main()
