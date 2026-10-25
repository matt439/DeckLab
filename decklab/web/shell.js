/* Deck Lab's page: the app shell (decklab/UI-REVIEW.md 2.2, WP4). The top bar's navigation and avatar menu,
the phone's top bar and bottom tab bar with its More sheet, the shopping badge, and the "This is my device"
choice. core.js's routes table (ROUTES) says what each page is called, where it sits and who sees it.

  From 1000 px (the lab, and a phone on its side): a sticky 56 px top bar: the logo, round nav pills
  Decks · Collection · Shopping (a count of deliveries waiting) · Matchups · More ▾ (the rest), the page's
  section marked with aria-current on --accent-soft; a slot for the run activity (#shell-status: Forge's
  turning ring while a run plays), then the avatar.
  Under 1000 px (casual: the phone, and the iPad in portrait; design/visual-design.md section 6 decision 5):
  a 56 px header (the way back, or the logo; the page's title once its heading has scrolled away; the run
  activity; the avatar) and a tab bar fixed to the bottom (Decks, Collection, Shopping, Matchups, More)
  above the safe-area inset, under every page's own bar. More opens a sheet with the rest.
  The avatar menu: Theme (Auto, Light, Dark), Switch person and "This is my device" (on the home network
  only: over the tunnel the login is the person), and Settings and About for an admin.

"This is my device" is a localStorage flag holding the profile's id: that profile is chosen without the
"Who are you?" screen when Deck Lab opens, and isn't forgotten after AWAY_MINUTES in the background
(app.js). The shared iPad leaves it off.

Loaded after core.js and before app.js, which calls setUpShell() at start, drawShell() when a profile is
chosen, syncShell() on every route and hideShell() on the "Who are you?" screen. Nothing here runs at load.
*/
"use strict";

// 24 px line icons (stroked, no fill), one per route and for More.
const ICONS = {
  decks: "M8 3h10a2 2 0 0 1 2 2v13M6 6h9a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z",
  collection: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  shopping: "M5 8h14l-1.2 11.1a2 2 0 0 1-2 1.9H8.2a2 2 0 0 1-2-1.9zM9 8V7a3 3 0 0 1 6 0v1",
  matchups: "M4 8h14m-4-4 4 4-4 4M20 16H6m4-4-4 4 4 4",
  tokens: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
  sleeves: "M7 3h10a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM6 7h12",
  plan: "M9 6h11M9 12h11M9 18h11M4 5.5l1 1 1.8-2M4 11.5l1 1 1.8-2M4 17.5l1 1 1.8-2",
  log: "M6 3h11a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM8 8h6M8 12h6",
  wishlist: "M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z",
  activity: "M3 12h4l3-7 4 14 3-7h4",
  settings: "M4 7h10M18 7h2M4 17h2M10 17h10M16 5v4M8 15v4",
  more: "M5 12h.01M12 12h.01M19 12h.01",
};
const TAB_COUNT = 4;                    // the tab bar's pages before More: Decks, Collection, Shopping, Matchups
const MY_DEVICE = "myDevice";           // local storage: the id of the profile whose device this is
const DELIVERIES_MS = 60000;            // how long a count of deliveries waiting is good for
let shellDeliveries = { at: 0, count: 0, request: null };
let titleFrame = 0;

/** A route's icon (ICONS), drawn in currentColor. */
function shellIcon(name) {
  return svgEl("svg", { class: `icon icon-${name}`, viewBox: "0 0 24 24", width: 24, height: 24, "aria-hidden": "true",
    focusable: "false" }, svgEl("path", { d: ICONS[name] || ICONS.more }));
}

function byId(id) { return document.getElementById(id); }

/** The profile whose device this is ("This is my device"), or null. */
function myDeviceId() { return local.get(MY_DEVICE); }

/** True when this device is the profile's own: it skips "Who are you?" and isn't forgotten while away. */
function isMyDevice(profile = state.profile) {
  return Boolean(profile) && !state.remote && myDeviceId() === profile.id;
}

/** Turn "This is my device" on or off for the profile chosen. */
function toggleMyDevice() {
  const profile = state.profile;
  if (!profile || state.remote) return;
  const on = !isMyDevice(profile);
  const saved = on ? local.set(MY_DEVICE, profile.id) : local.remove(MY_DEVICE);
  if (!saved) toast("This browser won't keep settings, so Deck Lab can't remember this device.");
  else toast(on ? `Deck Lab opens as ${profile.name} on this device, without asking who you are.`
    : "Deck Lab asks who you are again when it opens on this device.");
  syncAccountMenu();
}

// ------------------------------------------------------------------ set up

/** Wire the shell's fixed parts in index.html once, at start. */
function setUpShell() {
  const avatar = byId("avatar-button"), menu = byId("avatar-menu");
  if (avatar && menu) wireMenu(avatar, menu);
  for (const button of document.querySelectorAll("[data-theme-choice]")) {
    button.addEventListener("click", () => changeTheme(button.dataset.themeChoice));
  }
  const device = byId("my-device");
  if (device) device.addEventListener("click", toggleMyDevice);
  const reload = byId("menu-reload");
  if (reload) reload.addEventListener("click", reloadDeckLab);
  const sheet = byId("more-sheet");
  if (sheet) {
    sheet.addEventListener("click", (event) => {
      // A tap on the backdrop (the dialog itself, outside its inner box) or on a link closes it; a link's page
      // takes over the sheet's history entry (core.js sheetLinkClick).
      if (event.target === sheet) { sheet.close(); return; }
      sheetLinkClick(event, moreEntry, () => sheet.close());
      if (event.target.closest && event.target.closest("a") && sheet.open) sheet.close();
    });
    sheet.addEventListener("close", () => { releaseSheetEntry(moreEntry); moreEntry = null; });
    const close = sheet.querySelector(".sheet-close");
    if (close) close.addEventListener("click", () => sheet.close());
  }
  window.addEventListener("scroll", () => {
    if (titleFrame) return;
    titleFrame = requestAnimationFrame(() => { titleFrame = 0; syncShellTitle(); });
  }, { passive: true });
}

// ------------------------------------------------------------------- draw

/** Draw the navigation for the profile chosen (who sees which page), then mark the page on screen. */
function drawShell() {
  const profile = state.profile;
  if (!profile) return hideShell();
  document.body.classList.add("has-shell");
  const main = navRoutes("main"), more = navRoutes("more"), account = navRoutes("account");

  const nav = byId("main-nav");
  if (nav) {
    nav.hidden = false;
    const moreMenu = el("div", { class: "menu nav-more-menu", id: "nav-more-menu", role: "menu", hidden: true },
      more.map((r) => el("a", { role: "menuitem", href: `#/${r.path}`, "data-route": r.path, onclick: () => closeMenus() },
        shellIcon(r.icon), el("span", { text: r.label }))));
    const moreButton = el("button", { type: "button", class: "nav-item nav-more", "aria-haspopup": "menu",
      "aria-expanded": "false", "aria-controls": "nav-more-menu", "data-route-group": "more" },
      "More", el("span", { class: "menu-caret", "aria-hidden": "true" }));
    clear(nav).append(el("ul", { class: "nav-items" },
      main.map((r) => el("li", {}, navLink(r, "nav-item"))),
      more.length ? el("li", { class: "menu-wrap" }, wireMenu(moreButton, moreMenu), moreMenu) : null));
  }

  // The casual tab bar (under 1000 px): the first four main pages, then More (the rest, in a sheet).
  const tabs = main.slice(0, TAB_COUNT), sheetRoutes = [...main.slice(TAB_COUNT), ...more, ...account];
  const bar = byId("tabbar");
  if (bar) {
    add(clear(bar), [tabs.map((r) => navLink(r, "tab", true)),
      sheetRoutes.length ? el("button", { type: "button", class: "tab tab-more", "data-route-group": "sheet",
        "aria-haspopup": "dialog", "aria-controls": "more-sheet", onclick: openMoreSheet },
        shellIcon("more"), el("span", { class: "tab-label", text: "More" })) : null]);
    bar.hidden = false;
  }
  const list = byId("more-list");
  if (list) {
    clear(list).append(...sheetRoutes.map((r) => el("li", {},
      el("a", { href: `#/${r.path}`, "data-route": r.path }, shellIcon(r.icon), el("span", { text: r.label })))));
  }
  syncAccountMenu();
  syncShell();
  loadDeliveries();
}

/** A nav link to a route: the Shopping link carries the deliveries badge. The badge is a picture of the count
 * (aria-hidden); the words are in the link's name (showDeliveries), as screen readers skip a span's label. */
function navLink(route, cls, icon = false) {
  return el("a", { class: cls, href: `#/${route.path}`, "data-route": route.path },
    icon ? shellIcon(route.icon) : null,
    el("span", { class: icon ? "tab-label" : null, text: route.label }),
    route.path === "shopping" ? el("span", { class: "nav-badge", "data-deliveries": "", "aria-hidden": "true", hidden: true }) : null);
}

/** The "Who are you?" screen: no navigation, no avatar. */
function hideShell() {
  document.body.classList.remove("has-shell");
  for (const id of ["main-nav", "tabbar", "topbar-actions", "topbar-back"]) {
    const node = byId(id);
    if (node) node.hidden = true;
  }
  const sheet = byId("more-sheet");
  if (sheet && sheet.open) sheet.close();
  state.crumb = null;
  closeMenus();
  if (typeof stopRunsPill === "function") stopRunsPill();
}

/** The avatar and its menu for the profile chosen. */
function syncAccountMenu() {
  const profile = state.profile;
  if (!profile) return;
  const index = Math.max(0, state.profiles.findIndex((p) => p.id === profile.id));
  const initial = byId("avatar-initial");
  if (initial) {
    initial.textContent = profile.name.slice(0, 1).toUpperCase();
    initial.setAttribute("class", `avatar avatar-${index % 4}`);
  }
  const button = byId("avatar-button");
  if (button) button.setAttribute("aria-label", `${profile.name}: theme, ${state.remote ? "" : "switch person, "}settings`);
  const name = byId("menu-name");
  if (name) name.textContent = profile.name;
  const device = byId("my-device");
  if (device) {
    device.hidden = state.remote;
    device.setAttribute("aria-pressed", String(isMyDevice(profile)));
  }
  const admin = isAdminProfile();
  const visibility = byId("menu-visibility");
  if (visibility) visibility.hidden = !routeVisible(routeFor("visibility"));
  for (const id of ["menu-settings", "menu-about", "admin-sep"]) {
    const node = byId(id);
    if (node) node.hidden = !admin;
  }
  syncThemeChoice(state.forcedTheme || themeChoice);
}

/** Mark the theme chosen in the avatar menu's Auto / Light / Dark. */
function syncThemeChoice(theme) {
  for (const button of document.querySelectorAll("[data-theme-choice]")) {
    button.setAttribute("aria-pressed", String(button.dataset.themeChoice === theme));
  }
}

/** Mark the page on screen in the navigation (its section: a deck page is under Decks), its way back and its
 * title on the phone. Called by route() before the page draws. */
function syncShell(path = parseHash().path) {
  const section = routeSection(path);
  for (const link of document.querySelectorAll("[data-route]")) {
    if (link.dataset.route === section.path) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  for (const group of document.querySelectorAll("[data-route-group]")) {
    const inside = group.dataset.routeGroup === "more" ? section.nav === "more"
      : !navRoutes("main").slice(0, TAB_COUNT).some((r) => r.path === section.path);
    group.classList.toggle("is-current", inside);
  }
  syncShellBack();
  syncShellTitle();
  if (typeof syncRunsPill === "function") syncRunsPill();      // runs-pill.js: the run activity
}

/** The phone's way back: the page's crumb() if it drew one, else its route's parent; the logo on a top page. */
function syncShellBack() {
  const back = byId("topbar-back");
  if (!back) return;
  const route = routeFor(parseHash().path);
  let target = state.crumb;
  if (!target && route.parent) {
    const parent = routeFor(route.parent);
    target = parent.path === "library" ? { href: state.libraryHash || "#/library", label: parent.label }
      : parent.path === "deck" ? null : { href: `#/${parent.path}`, label: parent.label };
  }
  back.hidden = !target || !state.profile;
  if (!target) return;
  back.setAttribute("href", target.href);
  back.setAttribute("aria-label", `Back to ${target.label}`);
  const label = byId("topbar-back-label");
  if (label) label.textContent = target.label;
}

/** On the phone, the page's title shows in the top bar once its heading has scrolled up under it. */
function syncShellTitle() {
  const bar = byId("topbar");
  if (!bar) return;
  const heading = document.querySelector("#main h1");
  const edge = bar.getBoundingClientRect().bottom;
  bar.classList.toggle("show-title", Boolean(heading) && heading.getBoundingClientRect().bottom < edge);
}

// The More sheet's history entry while it's open (core.js pushSheetEntry): a phone's Back closes it.
let moreEntry = null;

function openMoreSheet() {
  const sheet = byId("more-sheet");
  if (!sheet || sheet.open) return;
  syncShell();
  if (typeof sheet.showModal === "function") sheet.showModal();
  moreEntry = pushSheetEntry(() => sheet.close());
}

// ----------------------------------------------------------- deliveries

/** The count of deliveries waiting (orders with a part still on the way), on the Shopping link: asked when a
 * profile is chosen (at most once a minute), and only for a visitor who may see home's shopping; the Shopping
 * page brings it up to date from its own answer (noteDeliveries). */
async function loadDeliveries(force = false) {
  if (!state.profile || !seesInventory(HOME_SPACE)) return showDeliveries(0);
  if (shellDeliveries.request) return shellDeliveries.request;
  if (!force && Date.now() - shellDeliveries.at < DELIVERIES_MS) return showDeliveries(shellDeliveries.count);
  shellDeliveries.request = (async () => {
    try {
      noteDeliveries(await api("/api/shopping"));
    } catch (e) {
      shellDeliveries.request = null;         // the Shopping page says what's wrong; the badge just stays
    }
    showDeliveries(shellDeliveries.count);
  })();
  return shellDeliveries.request;
}

/** Count the deliveries waiting in a /api/shopping answer (the Shopping page passes its own, so the badge is
 * as new as the page) and show them. */
function noteDeliveries(data) {
  const count = ((data && data.orders) || []).filter((o) => (o.components || []).some((c) => c.status === "pending")).length;
  shellDeliveries = { at: Date.now(), count, request: null };
  showDeliveries(count);
}

function showDeliveries(count) {
  for (const badge of document.querySelectorAll("[data-deliveries]")) {
    badge.hidden = !count;
    badge.textContent = count ? String(count) : "";
    // The link's name starts with its visible word ("Shopping, 2 deliveries waiting"), so voice control finds it.
    const link = badge.closest("a");
    if (!link) continue;
    if (count) link.setAttribute("aria-label", `${routeFor("shopping").label}, ${plural(count, "delivery", "deliveries")} waiting`);
    else link.removeAttribute("aria-label");
  }
}
