/* Deck Lab's page: its start-up and routing. The theme, the "Who are you?" screen and switching profiles, the
hash routing and history, a deck page's reading place and section-nav jumps, and start-up. The navigation,
the avatar menu and the phone's tab bar are shell.js's.

The page's scripts are classic scripts sharing one scope, all deferred. index.html has their exact order
(UI-KIT.md, "Files and load order", explains it): the editor's and matchup scripts first, then core.js, ui.js,
symbols.js, cards-ui.js and card-viewer.js, then the page scripts, then shell.js, settings.js and visibility.js,
and app.js last: start() at its very end needs all the others, and its hashchange and scrolling listeners
call into them.

Routes (hash routing, so the server only ever serves index.html):
    #/library[?all=1&format=casual|commander|product&status=idea|building|built]
    #/wishlist                            the active person's saved card wishlist
    #/shopping                            shared purchases and deliveries
    #/accessories                         sleeves, deck boxes and playmats (accessories.js)
    #/tokens                              physical token and reminder cards (tokens.js)
    #/collection, #/assembly, #/play      the shared collection, packing plan and played games
    #/history?id=<deck id>                a deck's saved versions
    #/activity                            who changed what in Deck Lab's database (activity.js)
    #/receipt?order=<order id>            receiving a delivery (receipts.js)
    #/deck?id=<deck id>&v=target|owned       e.g. id=casual/boros-burn, pairing/cats+vampires
    #/edit?id=<deck id>&v=target|owned       the editor (editor.js)
    #/new[?kind=casual|commander | ?from=<library id>]   a new deck (editor.js)
    #/matchups[?a=<deck id>&av=target|owned]  "Play a matchup" and every saved result (matchups.js)
    #/matchup?a=<id>&av=<v>&b=<id>&bv=<v>     one Forge matchup, or ?key=<key> (matchups.js)
    #/variant?test=<id>                       one test of a change to a deck (variant.js, wave 3)
    #/settings[?part=about]                   simulations, Forge workers and the version: admins (settings.js)
core.js's ROUTES names each of them and says who sees it (the nav, crumbs and tab titles follow it).

Over the tunnel (decklab.example.com) the Cloudflare Access login picks the profile: GET /api/me
says who it is ("remote"), the page goes straight to it with "Signed in as <name>" in the header, and
there's no "Who are you?" screen, switching, or forgetting the profile after a while away. /api/me's
"may" (state.may) says what this visitor may change, so pages hide what the server would refuse.

On the home network the "Who are you?" screen shows at the start of every visit: the profile
chosen is kept in sessionStorage for this visit only, and localStorage only
remembers the last one so it's listed first (plus that profile's theme, so the
next visit doesn't flash the wrong theme). A page that was in the background
for more than AWAY_MINUTES (the shared iPad put down, a tab left open) asks
again when it comes back, or when it's reloaded. A device someone has marked
"This is my device" (the avatar menu, shell.js) opens as them and isn't
forgotten while away. The profile chosen has its own rights, as it would through the tunnel
(/api/me, asked again once it's chosen, answers for it; the server refuses the rest). For automated screenshots,
/?profile=<id>&theme=light|dark picks the profile and theme without asking.

Coming back to a page (Back) returns to the same place in the same part
(readingAnchor), and keepPlace() keeps the reader's place while practice.js's
part changes height.
*/
"use strict";

// ------------------------------------------------------------------- theme

const SYSTEM_DARK = window.matchMedia("(prefers-color-scheme: dark)");
let themeChoice = "system";

/** Show a theme: "light", "dark" or "system" (Auto: the system's, followed as it changes). <html> always gets
 * data-theme="light" or "dark", so the stylesheets write the dark colours once. */
function applyTheme(theme) {
  themeChoice = theme === "light" || theme === "dark" ? theme : "system";
  const shown = themeChoice === "system" ? (SYSTEM_DARK.matches ? "dark" : "light") : themeChoice;
  document.documentElement.setAttribute("data-theme", shown);
  // The browser's own bar colour follows the page (the top bar's --surface).
  const colours = { light: "#ffffff", dark: "#1a1f1d" };
  for (const meta of document.querySelectorAll('meta[name="theme-color"]')) meta.content = colours[shown];
}

SYSTEM_DARK.addEventListener("change", () => { if (themeChoice === "system") applyTheme("system"); });

/** Show and save the theme chosen in the avatar menu ("system", "light" or "dark") as the profile's. */
async function changeTheme(theme) {
  const profile = state.profile;
  if (!profile) return;
  state.forcedTheme = null;
  applyTheme(theme);
  if (typeof syncThemeChoice === "function") syncThemeChoice(themeChoice);
  local.set(`theme.${profile.id}`, theme);
  try {
    await apiWrite(`/api/profiles/${encodeURIComponent(profile.id)}/settings`, { theme }, "PUT");
    toast(`Theme saved for ${profile.name}.`);
  } catch (e) {
    toast(`The theme couldn't be saved: ${e.message}`);
  }
}


// ---------------------------------------------------------------- profiles

function playerWords(player) {
  if (player === "either") return state.profiles.filter((p) => p.plays_as).map((p) => p.name).join(" or ") || "Either";
  const profile = state.profiles.find((p) => p.plays_as && p.plays_as === player);
  return profile ? profile.name : (player || "Not set");
}

/** Who plays a deck, in words: a person's deck is theirs (it has no Played by of its own unless written). */
function deckPlayerWords(deck) {
  const space = deck.space || deckSpaceOf(deck.id);
  return space !== HOME_SPACE && !deck.player ? spaceName(space) : playerWords(deck.player);
}

/** Keep a GET /api/profiles answer: the profiles this visitor may see and the admins' names (E10-S38). */
function keepRoster(roster) {
  state.profiles = Array.isArray(roster && roster.profiles) ? roster.profiles : [];
  state.admins = Array.isArray(roster && roster.admins) ? roster.admins : [];
}

/** The profiles "Who are you?" offers on the home network: the home's only. Everyone else signs in
 * through decklab.example.com, from the home Wi-Fi too; the server refuses their names here (403). */
function homeProfiles() {
  return state.profiles.filter((p) => (p.space || HOME_SPACE) === HOME_SPACE);
}

async function chooseProfile(profile) {
  shopCloseQueueSheets();
  closeReprintSheets();
  colCloseSheets();
  closeDeckOpponentSheets();
  closeDeckRetirementSheets();
  closeAssemblySheets();
  closeProductStorageSheets();
  closeTokenPlanSheets();
  closeAccessorySheets();
  closeReceiptSheets();
  state.profile = profile;
  session.set("profile", profile.id);
  local.set("lastProfile", profile.id);
  if (!state.remote) {
    // The profile chosen has the same rights here as through the tunnel (the server holds its writes to
    // them, and answers its reads from the X-Deck-Lab-Viewer header): what it may change, the home's
    // sleeves, deck boxes and playmats it sees (its own and the shared ones) and the spaces whose inventory
    // it sees. /api/me, asked again now the header names them, answers for them; deriveMay works the same
    // out only if it can't be had (an older server, or a moment's error).
    state.may = deriveMay(profile, false);
    state.library = null;           // its decks' sleeves are shown only to whoever's they are
    try {
      const me = await loadMe();
      if (state.profile === profile && me.profile === profile.id && me.may) state.may = me.may;
    } catch (e) { /* kept: deriveMay's */ }
    try {
      // The roster this profile may see (its own space's, plus public spaces' by name: E10-S38), now the
      // header names them; before a pick the home network is told only the home profiles.
      const roster = await api("/api/profiles");
      if (state.profile === profile && Array.isArray(roster && roster.profiles)) keepRoster(roster);
    } catch (e) { /* kept: the roster loaded before the pick (so is it after an answer with no roster) */ }
  }
  const name = $("#profile-name");
  if (name) name.textContent = profile.name;
  const switcher = $("#switch-profile");
  if (switcher) switcher.hidden = state.remote;          // over the tunnel the login is the person
  const signedIn = $("#signed-in");
  if (signedIn) {
    signedIn.hidden = !state.remote;
    signedIn.textContent = state.remote ? `Signed in as ${profile.name}` : "";
  }
  const actions = $("#topbar-actions");
  if (actions) actions.hidden = false;
  let theme = local.get(`theme.${profile.id}`) || "system";
  try {
    const settings = await api(`/api/profiles/${encodeURIComponent(profile.id)}/settings`);
    theme = settings.theme;
    local.set(`theme.${profile.id}`, theme);
  } catch (e) {
    toast(`${profile.name}'s settings couldn't be loaded (${e.message}); using the last theme on this device.`);
  }
  // A ?theme= override (screenshots) shows in the menu too, but isn't saved unless it's changed there.
  if (!state.forcedTheme) applyTheme(theme);
  drawShell();                        // shell.js: the nav and the avatar menu for this person
  loadSimulations();                  // who may start runs depends on who's chosen
  route();
}

/** Back to "Who are you?". Unsaved changes in the editor: ask first, or (ask false: the shared iPad was
 * put down for a while) keep them as that person's draft without asking the next person. */
async function switchProfile(ask = true) {
  if (state.remote) return;           // the login is the profile: nothing to switch to
  if (!(await leaveEditor(ask))) return;
  // The next person starts in the library, not in the last person's editor (their draft stays theirs).
  const { path } = parseHash();
  if (path === "edit" || path === "new") history.replaceState(history.state, "", "#/library");
  session.remove("profile");
  state.profile = null;
  hideShell();
  route();
}

// The iPad is shared: a page left in the background (a Safari tab, a home-screen app, a
// locked screen) for longer than this asks "Who are you?" again when it comes back, so
// the next person doesn't carry on as the last one. A quick reload keeps the profile.
const AWAY_MINUTES = 30;

/** Note when the page went out of sight; the first time counts (a tab hidden for hours
 * and then reloaded or restored has been away since it was hidden). */
function markAway() { if (!session.get("hiddenAt")) session.set("hiddenAt", String(Date.now())); }

function awayTooLong() {
  const hidden = Number(session.get("hiddenAt"));
  return hidden > 0 && Date.now() - hidden > AWAY_MINUTES * 60 * 1000;
}

function backFromAway() {
  if (state.profile && !state.remote && awayTooLong() && !isMyDevice(state.profile)) switchProfile(false);
  session.remove("hiddenAt");
}

function drawWho() {
  shopCloseQueueSheets();
  closeReprintSheets();
  colCloseSheets();
  closeDeckOpponentSheets();
  closeDeckRetirementSheets();
  closeAssemblySheets();
  closeProductStorageSheets();
  closeTokenPlanSheets();
  closeAccessorySheets();
  closeReceiptSheets();
  stopMatchupRefresh();
  routeToken += 1;
  setTitle("Who are you?");
  hideShell();
  const last = local.get("lastProfile");
  const ordered = homeProfiles().sort((a, b) => (b.id === last) - (a.id === last));
  const main = clear($("#main"));
  main.append(el("section", { class: "who", "aria-labelledby": "who-title" },
    el("h1", { id: "who-title", text: "Who are you?" }),
    el("p", { text: "Pick your name. The library opens on your decks, and your theme comes with you." }),
    el("div", { class: "who-buttons" }, ordered.map((p) => el("button", {
      type: "button", class: "who-button", onclick: () => chooseProfile(p) },
      // Each person keeps one colour (from their place in config.json), whoever was last.
      el("span", { class: `avatar avatar-${state.profiles.indexOf(p) % 4}`, "aria-hidden": "true",
        text: p.name.slice(0, 1).toUpperCase() }),
      el("span", {},
        el("span", { class: "who-name", text: p.name }),
        el("span", { class: "who-sub", text: p.id === last ? "Last time on this device" : "Tap to continue" }))))),
    ordered.length ? null : el("p", { class: "box box-warn",
      text: "There are no profiles in decklab/config.json yet." })));
  afterRender();
}


// ----------------------------------------------------------------- routing

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const q = raw.indexOf("?");
  const path = (q < 0 ? raw : raw.slice(0, q)) || "library";
  return { path, params: new URLSearchParams(q < 0 ? "" : raw.slice(q + 1)) };
}

function route() {
  shopCloseQueueSheets();
  closeReprintSheets();
  colCloseSheets();
  closeDeckOpponentSheets();
  closeDeckRetirementSheets();
  closeAssemblySheets();
  closeProductStorageSheets();
  closeTokenPlanSheets();
  closeAccessorySheets();
  closeReceiptSheets();
  stopMatchupRefresh();
  const token = ++routeToken;
  const { path, params } = parseHash();
  boxCollectionRoute(path, token);
  boxEditorRoute(path, token);
  closeEditor(path);                // editor.js: the editor on screen is left (its draft stays)
  if (!state.profile) return drawWho();
  noteVisit(path, params);
  // The routes table names the page until it names its subject (a deck's title); the nav marks its section.
  state.crumb = null;
  closeMenus();
  const sheet = $("#more-sheet");
  if (sheet && sheet.open) sheet.close();
  setTitle(routeFor(path).title);
  syncShell(path);
  if (path === "wishlist") return showWishlist(token);
  if (path === "shopping") return seesHomeInventory(state.may) ? showShopping(token) : showNoInventory(routeH1("shopping"));
  if (path === "accessories") return mayDo("see_accessories") ? showAccessories(token) : showNoAccessories();
  if (path === "tokens") return showTokens(token, params);
  if (path === "collection") return showCollection(params, token);
  if (path === "assembly") return seesHomeInventory(state.may) ? showAssembly(params, token) : showNoInventory(routeH1("assembly"));
  if (path === "play") return showPlay(params, token);
  if (path === "history" && params.get("id")) return showHistory(params, token);
  if (path === "activity") return showActivity(params, token);
  if (path === "receipt" && params.get("order")) {
    return seesHomeInventory(state.may) ? showReceipt(params, token) : showNoInventory(routeH1("receipt"));
  }
  if (path === "settings") return showSettings(params, token);
  if (path === "visibility") return showVisibility(params, token);
  if ((path === "edit" || path === "new") && !canBuildDecks()) return showDesktopHandoff(params);
  if (path === "deck" && params.get("id")) return showDeck(params, token);
  if (path === "edit" && params.get("id")) return showEditor(params, token);
  if (path === "new") return showNewDeck(params, token);
  if (path === "matchups") return showMatchups(params, token);
  if (path === "matchup" && (params.get("key") || (params.get("a") && params.get("b")))) {
    return showMatchup(params, token);
  }
  if (path === "variant" && params.get("test")) return showVariant(params, token);
  return showLibrary(params, token);
}

/* The page's beacon (POST /api/visit, lib/visits.py): which page the visitor opened, so an admin can see on the
Settings page who uses Deck Lab and what they look at. Only the route's path, and a deck's id on a deck's pages;
nothing else of the address (no search text, no filters). The server records it for the requester's own profile
(the login, or the profile chosen here); it's never waited for, and a failure is ignored. The same page drawn
again within VISIT_REPEAT_MS (Try again, a redraw) isn't sent twice. */
const VISIT_DECK_ROUTES = ["deck", "edit", "history"];
const VISIT_REPEAT_MS = 2000;
let lastVisit = { key: "", at: 0 };

function noteVisit(path, params) {
  const page = ROUTES.some((r) => r.path === path) ? path : "library";
  const deck = VISIT_DECK_ROUTES.includes(page) ? params.get("id") : null;
  const key = `${page} ${deck || ""}`;
  const now = Date.now();
  if (key === lastVisit.key && now - lastVisit.at < VISIT_REPEAT_MS) return;
  lastVisit = { key, at: now };
  try {
    apiWrite("/api/visit", deck ? { route: page, deck } : { route: page }).catch(() => {});
  } catch (e) { /* nothing to note it with */ }
}

function afterRender() {
  const remembered = state.scroll.get(location.hash);
  if (!state.firstRender) {
    window.scrollTo(0, remembered ? remembered.y : 0);
    // On a deck page, go back to the same place in the same part, even if a part above it is a
    // different height now (Practice hands drawn, or not yet).
    if (remembered && remembered.anchor) restoreAnchor(remembered.anchor);
    $("#main").focus({ preventScroll: true });
  }
  state.firstRender = false;
}

/** This history entry's place in the tab's history (history.state.pos), stamped on it the first time
 * the page sees it. A new entry is always the last one, so its place is history.length - 1; Back and
 * Forward return to entries that have one, which tells the editor's guard (editor.js) which way the
 * browser went, so it can step back the other way instead of writing over an entry. */
function entryPos() {
  const s = history.state;
  if (s && typeof s.pos === "number") return s.pos;
  const pos = history.length - 1;
  history.replaceState({ ...(s && typeof s === "object" ? s : {}), pos }, "");
  return pos;
}

window.addEventListener("hashchange", (event) => {
  const old = event.oldURL ? new URL(event.oldURL).hash : "";
  entryPos();
  // Leaving the editor with unsaved changes asks first (editor.js puts the old address back meanwhile).
  if (editorGuard(old, location.hash)) return;
  state.scroll.set(old, { y: window.scrollY, anchor: readingAnchor() });     // the page left is still drawn
  jump = null;
  if (location.hash === "" || location.hash.startsWith("#/")) route();
});

/** Where the reader is on a deck page: the part (a .deck-section) at a line (by default a third of
 * the way down the screen), and how far into that part the line is; null on other pages. */
function readingAnchor(line = Math.min(window.innerHeight / 3, 300)) {
  for (const part of document.querySelectorAll(".deck-section")) {
    const box = part.getBoundingClientRect();
    if (box.bottom > line) return { id: part.id, line, offset: line - box.top };
  }
  return null;
}

/** Scroll so that readingAnchor()'s place is back at its line. False if its part isn't on the page. */
function restoreAnchor(anchor) {
  const part = anchor && document.getElementById(anchor.id);
  if (!part) return false;
  window.scrollBy(0, part.getBoundingClientRect().top - (anchor.line - anchor.offset));
  return true;
}

/** Change a deck page's Practice hands part (change() does it) without moving what the reader is
 * looking at: iOS Safari has no scroll anchoring, and Chrome's can anchor on the part itself. After
 * a section-nav jump (until the reader scrolls by hand), that's the part jumped to (Practice hands
 * too: it grows below its heading). Otherwise it's the part in the middle of the screen below the
 * nav: a part below Practice hands (Owned vs needed) stays where it is even while Practice's small
 * running box is still on screen above it, so the part grows up out of sight; a part above it isn't
 * moved anyway; and Practice hands itself simply grows down, so its new content shows where the
 * reader is looking. */
function keepPlace(change) {
  const target = jump ? document.getElementById(jump.id) : null;
  const middle = NAV_SPACE + (window.innerHeight - NAV_SPACE) / 2;
  const anchor = target ? { id: target.id, line: target.getBoundingClientRect().top, offset: 0 }
    : readingAnchor(middle);
  change();
  if (anchor && (target || anchor.id !== "sec-practice")) restoreAnchor(anchor);
}

// The deck page part the section nav last jumped to ({id}), for keepPlace(). Scrolling by hand
// ends it, and so does going to another page; waiting doesn't (a run that finishes long after a tap on
// Practice still grows down from its heading). The jump itself isn't smooth: a smooth scroll aims at
// where its part was when it began, so Practice hands growing on the way (the run it starts as it
// passes) would leave it short.
let jump = null;

function jumpTo(id) {
  const section = document.getElementById(id);
  if (!section) return;
  jump = { id };
  section.setAttribute("tabindex", "-1");
  section.focus({ preventScroll: true });
  section.scrollIntoView();
  updateSectionNavigation(id);
}

/** Scroll navigation has a current location, including when the reader scrolls by hand. */
function updateSectionNavigation(selected) {
  const nav = document.querySelector(".section-nav");
  if (!nav) return;
  const buttons = [...nav.querySelectorAll("[data-section]")];
  if (!selected) {
    const edge = nav.getBoundingClientRect().bottom + 24;
    selected = buttons[0] && buttons[0].dataset.section;
    for (const button of buttons) {
      const section = document.getElementById(button.dataset.section);
      if (section && section.getBoundingClientRect().top <= edge) selected = section.id;
    }
  }
  for (const button of buttons) {
    if (button.dataset.section === selected) {
      const changed = button.getAttribute("aria-current") !== "location";
      button.setAttribute("aria-current", "location");
      if (changed) {
        const bounds = nav.getBoundingClientRect(), item = button.getBoundingClientRect();
        if (item.left < bounds.left) nav.scrollLeft -= bounds.left - item.left;
        else if (item.right > bounds.right) nav.scrollLeft += item.right - bounds.right;
      }
    }
    else button.removeAttribute("aria-current");
  }
}

let sectionFrame = 0;
window.addEventListener("scroll", () => {
  if (sectionFrame) return;
  sectionFrame = requestAnimationFrame(() => { sectionFrame = 0; updateSectionNavigation(); });
}, { passive: true });
window.addEventListener("resize", () => updateSectionNavigation(), { passive: true });

for (const type of ["wheel", "touchstart", "pointerdown", "keydown"]) {
  window.addEventListener(type, () => { jump = null; }, { passive: true, capture: true });
}


// ------------------------------------------------------------------ start

async function start() {
  entryPos();
  setUpDialog();
  setUpPeek();
  setUpShell();
  startVersionMonitor();
  const switcher = $("#switch-profile");
  if (switcher) switcher.addEventListener("click", () => { closeMenus(); switchProfile(); });
  document.querySelector(".skip").addEventListener("click", (e) => {
    e.preventDefault();
    $("#main").focus();
  });

  const params = new URLSearchParams(location.search);
  const theme = params.get("theme");
  if (theme === "light" || theme === "dark") {
    state.forcedTheme = theme;
    applyTheme(theme);
  }
  const main = $("#main");
  let me;
  for (;;) {
    try {
      let roster;
      [roster, me] = await Promise.all([api("/api/profiles"), loadMe()]);
      keepRoster(roster);
      break;
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      // Retry on the button, or by itself after a while (the server may still be starting).
      await new Promise((resolve) => {
        clear(main).append(errorBox("Deck Lab couldn't start", e, resolve));
        setTimeout(resolve, RETRY_SECONDS * 1000);
      });
      clear(main).append(loadingBox("Loading Deck Lab..."));
    }
  }
  state.me = me;
  state.remote = Boolean(me.remote);
  if (state.remote) {
    // The login picked the profile: no "Who are you?", no ?profile=, never forgotten while away.
    const profile = state.profiles.find((p) => p.id === me.profile)
      || (me.profile ? { id: me.profile, name: me.name || me.profile } : null);
    if (!profile) {
      clear(main).append(el("div", { class: "box box-crit" }, el("h1", { text: "Your login has no Deck Lab profile" }),
        el("p", { text: `Ask ${adminWords()} to add your email address to Deck Lab's profiles.` })));
      return;
    }
    state.may = me.may || deriveMay(profile, true);
    session.remove("hiddenAt");
    chooseProfile(profile);
    return;
  }
  // ?profile= (screenshots) always picks; this visit's profile only if the page wasn't
  // away too long (a tab restored after hours starts at "Who are you?"); else the person whose device this is.
  const mine = myDeviceId();
  if (awayTooLong() && session.get("profile") !== mine) session.remove("profile");
  session.remove("hiddenAt");
  const wanted = params.get("profile") || session.get("profile") || mine;
  const profile = homeProfiles().find((p) => p.id === wanted);
  if (profile) chooseProfile(profile);
  else drawWho();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") markAway();
    else backFromAway();
  });
  window.addEventListener("pagehide", markAway);
  window.addEventListener("pageshow", (event) => { if (event.persisted) backFromAway(); });
}

/** #/accessories for someone who may not see the sleeves, deck boxes and playmats (they're the home's; the words
 * name no space, as the server's 403 doesn't: E10-S38). */
function showNoAccessories() {
  // The page's usual head, then the shared empty state: one line and the one way on.
  clear($("#main")).append(...pageHead({ title: routeH1("accessories") }).filter(Boolean), el("div", { class: "empty" },
    el("p", { text: "The sleeves, deck boxes and playmats are private." }),
    el("a", { class: "btn btn-secondary", href: "#/library", text: "Back to the decks" })));
  afterRender();
}

/** #/shopping, #/receipt and #/assembly for someone outside the home: the shopping list, deliveries and the
 * packing plan are the home's (the server answers 403 too). Their own collection and tokens are still theirs. */
function showNoInventory(title) {
  // A child page's way back (a receipt's is Shopping) would lead to another page they can't see: Decks instead.
  const back = routeFor(parseHash().path).parent ? ["#/library", routeFor("library").label] : null;
  // The page's usual head, then the shared empty state: one line and the one way on (their own collection).
  clear($("#main")).append(...pageHead({ crumb: back, title }).filter(Boolean), el("div", { class: "empty" },
    el("p", { text: "The shopping list, deliveries and packing plan are private." }),
    el("a", { class: "btn btn-secondary", href: "#/collection", text: "Your collection" })));
  afterRender();
}

/** GET /api/me: who is asking. A server without it (404) is on the home network as before. */
async function loadMe() {
  try {
    return await api("/api/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return { profile: null, name: null, remote: false, may: null };
    throw e;
  }
}

start();
