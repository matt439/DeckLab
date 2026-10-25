/* Deck Lab's page: what every screen uses. The shared word tables and the page's one `state`, the
helpers for elements, storage, numbers and deck ids, the page-error box and the toast, and the API
calls with the loading, "card data isn't ready" and error states around them.

Plain JavaScript with no build step and nothing loaded from the internet. The
Python server (decklab/server.py) serves the page's scripts with index.html
and the stylesheets, and every number on the page comes from its JSON API (the
decklab/lib/api package): the page only lays the answers out.

The page's scripts are classic scripts sharing one scope, all deferred, loaded in this order: the
editor's (editor.js first), matchups.js, matchups-cards.js, then this file, library.js, deck.js,
stats.js, practice.js and app.js (app.js's header says what each holds). Every file after this one
uses its helpers, and so do the editor's, matchups.js and matchups-cards.js once the page is
running. It uses nothing from them at load; at run time load() calls app.js's route(),
afterRender() and showFooter().

Every write (POST, PUT) goes through apiWrite(), which sends the headers the server's write check
wants (JSON and "X-Deck-Lab: 1") and, for a POST, the profile making the change.
*/
"use strict";

const RETRY_SECONDS = 15;           // how often to retry while the card data isn't ready
const STORE = "decklab.";           // prefix of every storage key
const BOX_PREFIX = "product/fdn-beginner-box/";     // ids of the ten Beginner Box halves
const SHELL_TOP = 56;               // px of the sticky top bar (48 on a phone): shell.css's --shell-top
const NAV_SPACE = 60 + SHELL_TOP;   // px at the top of a deck page under the top bar and its sticky section nav
const STATUS_WORDS = { idea: "Idea", building: "Building", built: "Built" };
const FORMAT_WORDS = { casual: "Casual", commander: "Commander", product: "Products" };
const COLOUR_WORDS = { W: "white", U: "blue", B: "black", R: "red", G: "green", C: "colourless" };
const POLL_MS = 1000;           // how often to ask how a practice run or a matchup is getting on

const HOME_SPACE = "home";      // the shared pool's space (lib/spaces.py); a person's space is their profile id
const HOME_KINDS = ["casual", "commander", "product", "pairing"];   // first parts of a home deck id

const state = {
  profiles: [],           // GET /api/profiles: the visitor's own space's profiles, plus public spaces' by name (E10-S38)
  admins: [],             // GET /api/profiles' admins: their display names only, for "Ask Alex" wording (adminWords)
  profile: null,          // {id, name, plays_as?, role, space} for this visit
  me: null,               // GET /api/me: {profile, name, remote, may}
  may: null,              // what this visitor may change (permissions.summary on the server); see mayDo()
  remote: false,          // over the tunnel: the login picks the profile, and there's no switching
  forcedTheme: null,      // ?theme= for screenshots
  simulations: null,      // GET /api/simulations for this visitor (version.js renderSimulations)
  status: null,           // the last GET /api/status answer (version.js renderVersionStatus)
  library: null,          // the last /api/decks answer, for re-filtering without a fetch
  cards: new Map(),       // card name -> card data, for the deck on screen
  scroll: new Map(),      // hash -> scroll position, restored when coming back
  practiceSetup: {},      // kind -> the practice games last shown (play, draw, multiplayer)
  saved: null,            // {hash, answer}: the save just made (editor-save.js), shown once on its deck page
                          // (editor-deckpage.js)
  colNotice: null,        // collection.js: what a change said, for the view drawn again after it
  crumb: null,            // {href, label}: this page's way back (crumb()), shown in the phone's top bar too
  firstRender: true,
};
let routeToken = 0;       // bumped on every route change, so a slow answer can't draw over a newer page


// ------------------------------------------------------------------ helpers

function $(selector) { return document.querySelector(selector); }

/** An element: el("a", {href: "#", class: "x", text: "hi"}, child, ...). Text is
 * always set as text, never parsed as HTML (names come from files and Scryfall). */
function el(tag, props, ...children) {
  const node = document.createElement(tag);
  setProps(node, props);
  return add(node, children);
}

/** An SVG element, the same way. */
function svgEl(tag, props, ...children) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  setProps(node, props);
  return add(node, children);
}

function setProps(node, props) {
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === "class") node.setAttribute("class", value);
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
}

function add(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false || child === "") continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

function clear(node) { node.replaceChildren(); return node; }

function storage(kind) {
  // Storage can be blocked (private windows, headless runs): never let that break the page.
  return {
    get(key) { try { return window[kind].getItem(STORE + key); } catch (e) { return null; } },
    set(key, value) { try { window[kind].setItem(STORE + key, value); return true; } catch (e) { return false; } },
    remove(key) { try { window[kind].removeItem(STORE + key); return true; } catch (e) { return false; } },
  };
}
const local = storage("localStorage");
const session = storage("sessionStorage");

/** 22 -> "22", 14.5 -> "14.5", 24.657 -> "24.66". */
function num(x, digits = 2) {
  if (x == null || Number.isNaN(x)) return "?";
  if (Number.isInteger(x)) return String(x);
  return x.toFixed(digits).replace(/0+$/, "").replace(/\.$/, "");
}

function aud(x) { return x == null ? "no price" : `A$${x.toFixed(2)}`; }

function plural(n, one, many) { return `${num(n)} ${n === 1 ? one : (many || one + "s")}`; }

/** A line of facts joined by "·" that wraps cleanly: each fact stays whole, and a line never starts with a "·"
 * (each fact carries its dot in front, and the one that starts a line has it clipped off: components.css
 * .fact-line). cls: the line's own class; parts: strings or nodes. */
function factLine(cls, parts) {
  return el("span", { class: `fact-line ${cls || ""}`.trim() }, el("span", { class: "fact-line-in" },
    parts.filter((p) => p != null && p !== "").map((part, i) =>
      // The first fact's dot is always clipped: an empty one of the same width keeps the words clean.
      el("span", { class: "fact" }, el("span", { class: "fact-sep", "aria-hidden": "true", text: i ? " · " : "" }), part))));
}

/** {text, count} naming tokens and reminders on one line, each name once: "Raccoon token", "Dragon or Treasure
 * tokens, The Monarch" (joiner "or"), "Dragon and Treasure tokens" (joiner "and"). The token names share one
 * "tokens"; an emblem or a reminder is named by itself; past three names the rest are counted in words
 * ("and 2 more"), never "+2", which reads like a counter. count is how many different names there are. */
function tokenNamesWords(tokenNames, otherNames, joiner) {
  const once = (list) => Array.from(new Set(list || []));
  const tokens = once(tokenNames), others = once(otherNames).filter((n) => !tokens.includes(n));
  const join = (list) => list.length < 2 ? list.join("") : `${list.slice(0, -1).join(", ")} ${joiner} ${list[list.length - 1]}`;
  const keepT = tokens.slice(0, 3), keepO = others.slice(0, 3 - keepT.length);
  const extra = tokens.length + others.length - keepT.length - keepO.length;
  const groups = keepT.length ? [`${join(keepT)} ${tokens.length > 1 ? "tokens" : "token"}`] : [];
  groups.push(...keepO);
  return { text: groups.join(", ") + (extra ? ` and ${extra} more` : ""), count: tokens.length + others.length };
}

/** 0.8563 -> "85.6%"; tiny and nearly-certain chances say so rather than round to 0 or 100. */
function pct(x, digits = 1) {
  if (x == null || Number.isNaN(x)) return "?";
  const v = x * 100;
  const step = 10 ** -digits;
  if (v > 0 && v < step / 2) return `<${step.toFixed(digits)}%`;
  if (v < 100 && v >= 100 - step / 2) return `>${(100 - step).toFixed(digits)}%`;
  return `${v.toFixed(digits)}%`;
}

/** A chance as a whole percentage, for chart caps and table cells: "86%", "<1%", ">99%". */
function pctShort(x) { return pct(x, 0); }

function thousands(n) { return Number(n).toLocaleString("en-AU"); }

function capitalise(text) { return text ? text[0].toUpperCase() + text.slice(1) : text; }

function status(kind, text) { return el("span", { class: `status status-${kind}`, text }); }

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

/** A progress bar: {node, set(share)}, share from 0 to 1. label names it for screen readers; tag is
 * "span" for one inside a link. */
function progressBar(label, tag = "div") {
  const fill = el("span", { class: "progress-fill" });
  const node = el(tag, { class: "progress", role: "progressbar", "aria-label": label,
    "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": 0 }, fill);
  return {
    node,
    set(share) {
      const n = Math.round(Math.max(0, Math.min(1, share || 0)) * 100);
      fill.style.width = `${n}%`;
      node.setAttribute("aria-valuenow", String(n));
    },
  };
}

// Beginner Box pairings: "pairing/<half>+<half>", where a half is the last part of its id
// ("product/fdn-beginner-box/cats" -> "cats"). Either order names the same 40 cards.

/** The pairing of two halves, by their ids. */
function pairingId(halfA, halfB) {
  const part = (id) => id.split("/").pop();
  return `pairing/${part(halfA)}+${part(halfB)}`;
}

/** A deck id from the address bar, where a "+" typed into it reads as a space. */
function addressDeckId(id) {
  return id && id.startsWith("pairing/") ? id.replace(/ /g, "+") : id;
}

/** A pairing's two half names (["cats", "vampires"]), or null for any other deck id. */
function pairingHalves(id) {
  id = addressDeckId(id);
  return id && id.startsWith("pairing/") ? id.slice("pairing/".length).split("+") : null;
}

/** A deck id to compare with another: a pairing's halves in one order. */
function sameDeckId(id) {
  const halves = pairingHalves(id);
  return halves ? `pairing/${[...halves].sort().join("+")}` : id;
}

function deckHref(id, version) {
  return `#/deck?id=${encodeURIComponent(id)}&v=${version || "target"}`;
}

function note(...paragraphs) {
  return el("div", { class: "note" }, el("div", {}, paragraphs.map((p) => el("p", {}, p))));
}

function warningsBox(warnings, title) {
  if (!warnings || !warnings.length) return null;
  return el("div", { class: "box box-warn" }, el("h2", { text: title }),
    el("ul", {}, warnings.map((w) => el("li", { text: w }))));
}

/** Put my changes to a row (mine, from base) on top of someone else's (theirs), field by field over keys:
 * a field only I changed takes mine, one only they changed takes theirs, and one we both changed
 * differently is a clash to choose ({key, mine, theirs}). Values compare as text. Used by the
 * Accessories and Tokens pages when a save meets a newer list. */
function rebaseFields(mine, base, theirs, keys) {
  const row = {}, clashes = [];
  for (const key of keys) {
    const m = String(mine[key] ?? ""), b = String(base[key] ?? ""), t = String(theirs[key] ?? "");
    if (m === b) row[key] = t;
    else {
      row[key] = m;
      if (t !== b && t !== m) clashes.push({ key, mine: m, theirs: t });
    }
  }
  return { row, clashes };
}

function sourceLink(sources, id) {
  const s = sources && sources[id];
  if (!s) return null;
  return el("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", text: s.title });
}

/** Call draw(width) now and whenever host's width changes (charts are drawn to fit). */
function fitWidth(host, draw) {
  let last = 0;
  const redraw = () => {
    const width = Math.floor(host.clientWidth);
    if (width > 0 && width !== last) { last = width; draw(width); }
  };
  redraw();
  if ("ResizeObserver" in window) new ResizeObserver(redraw).observe(host);
}


// ------------------------------------------------- spaces and permissions

/** Every space: home first, then each person's (a profile whose space isn't home), by name. */
function spaceList() {
  const people = state.profiles.filter((p) => p.space && p.space !== HOME_SPACE)
    .map((p) => ({ id: p.space, name: p.name }))
    .filter((s, i, all) => all.findIndex((t) => t.id === s.id) === i);
  return sortSpaces([{ id: HOME_SPACE, name: "Home" }, ...people]);
}

/** Spaces in the one order every page uses: home first, then each person's by name. */
function sortSpaces(spaces) {
  const name = (s) => (s.id === HOME_SPACE ? "" : String(s.name || s.id));
  return [...spaces].sort((a, b) => (a.id === HOME_SPACE ? -1 : b.id === HOME_SPACE ? 1 : name(a).localeCompare(name(b))));
}

/** The spaces whose collection and tokens the visitor may see (seesInventory), home first. */
function seenSpaces() {
  return spaceList().filter((s) => seesInventory(s.id));
}

/** Who to ask for what only an admin does: "Alex" (GET /api/profiles' admins, the one name a member is told,
 * E10-S38), "Alex or Sam" for two, else "an admin". */
function adminWords() {
  const names = (state.admins || []).filter(Boolean);
  if (!names.length) return "an admin";
  return names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} or ${names[names.length - 1]}`;
}

/** "Home", or the person's name ("Jordan") for their space. */
function spaceName(id) {
  if (!id || id === HOME_SPACE) return "Home";
  const found = spaceList().find((s) => s.id === id);
  return found ? found.name : capitalise(id);
}

/** A deck's space from its id: "jordan/casual/elves" -> "jordan"; a home id ("casual/elves") -> "home". */
function deckSpaceOf(id) {
  const first = String(id || "").split("/")[0];
  return !first || HOME_KINDS.includes(first) ? HOME_SPACE : first;
}

/** The visitor's own space: a person's, or home. */
function ownSpace() {
  return (state.profile && state.profile.space) || HOME_SPACE;
}

/** What a profile may change, by lib/permissions.py's summary() rules: a fallback for when /api/me doesn't
 * say (an older server, or its answer couldn't be had), since /api/me answers for the profile chosen on the
 * home network as it does for the login over the tunnel. A chosen profile has its own rights wherever it is
 * (admin by role only), and an admin's only in his own space (E10-S29); with nobody chosen, nothing anywhere
 * (only a script on the PC, never this page, may do everything). */
function deriveMay(profile, remote) {
  const admin = Boolean(profile) && profile.role === "admin";
  const sees = Boolean(profile) && seesAccessoriesAs(profile);
  const own = profile ? profile.space || HOME_SPACE : null;
  const homeAdmin = admin && own === HOME_SPACE;
  const base = { admin, runs: true, accessories: sees, receipts: homeAdmin, products: homeAdmin, orders: homeAdmin,
    see_accessories: sees, see_inventory: profile ? inventorySpacesAs(profile) : [],
    see_home_records: own === HOME_SPACE };
  if (!own) return { ...base, spaces: [], deck_spaces: [], home_player: null, create: [] };
  if (own !== HOME_SPACE || admin) {
    return { ...base, spaces: [own], deck_spaces: [own], home_player: null, create: [{ space: own, player: null }] };
  }
  const player = profile.plays_as && profile.plays_as !== "either" ? profile.plays_as : null;
  return { ...base, spaces: [HOME_SPACE], deck_spaces: [], home_player: player,
    create: player ? [{ space: HOME_SPACE, player }] : [] };
}

/** Whether a profile sees any sleeves, deck boxes and playmats (lib/permissions.py's sees_accessories):
 * a home profile does (its own and the shared ones), a person with their own space (Jordan, say) doesn't. */
function seesAccessoriesAs(profile) {
  return !profile || (profile.space || HOME_SPACE) === HOME_SPACE;
}

/** The spaces whose inventory a profile sees (lib/permissions.py's inventory_spaces): its own space's, an
 * admin's too (E10-S29), so home's collection, tokens, shopping and receipts only for a home profile (Alex,
 * Sam) and Jordan's only for Jordan. deriveMay gives nobody chosen none. */
function inventorySpacesAs(profile) {
  if (!profile) return null;
  return [profile.space || HOME_SPACE];
}

/** True when the visitor may see a space's inventory: its collection and tokens, and for home also the
 * shopping list, receipts and packing plan (/api/me's "may".see_inventory; the server answers 403 otherwise).
 * Without an answer yet, nothing is hidden. */
function seesInventory(space) {
  const seen = state.may ? state.may.see_inventory : null;
  return !Array.isArray(seen) || seen.includes(space || HOME_SPACE);
}

/** The owner of a home deck's accessories (lib/accessories.py's player_owner): the home profile whose
 * plays_as is its Played by, or "shared" for "either" (and products). */
function accessoryOwnerOf(player) {
  const found = player && player !== "either"
    ? state.profiles.find((p) => (p.space || HOME_SPACE) === HOME_SPACE && p.plays_as === player) : null;
  return found ? found.id : "shared";
}

/** True when a deck of owner may take an accessory row of row.owner: its owner's own, or a shared one. */
function accessoryUsable(row, owner) {
  return !row.owner || row.owner === "shared" || row.owner === owner;
}

/** True when the visitor may do this (a key of /api/me's "may": admin, accessories, receipts, products,
 * orders, runs, see_accessories). Without an answer yet, nothing is hidden (the server checks every write
 * anyway). see_accessories and accessories are each home profile's own (its accessories and the shared
 * ones), so an admin's "may" doesn't override them (deriveMay and /api/me give them per profile). */
function mayDo(key) {
  const may = state.may;
  if (!may) return true;
  if (key === "see_accessories") return may.see_accessories !== false;
  if (key === "accessories") return may.accessories !== false && may.see_accessories !== false;
  return Boolean(may.admin || may[key]);
}

/** True when the visitor may change the collection and tokens of a space: its own space's ("may".spaces),
 * home's for a home member as for an admin (E10-S43); an admin's role opens no other space (E10-S29). */
function canEditSpace(space) {
  const may = state.may;
  return !may || (may.spaces || []).includes(space || HOME_SPACE);
}

/** True when the visitor may change a deck: a library summary, a deck page's summary or an editor view
 * ({space, player, read_only}). Products and pairings are never changed in place. An admin changes every
 * deck of his own space ("may".deck_spaces) and none of another's (E10-S29). */
function canEditDeck(deck) {
  if (!deck || deck.read_only) return false;
  const may = state.may;
  if (!may) return true;
  const space = deck.space || deckSpaceOf(deck.id);
  if ((may.deck_spaces || []).includes(space)) return true;
  return space === HOME_SPACE && Boolean(may.home_player) && deck.player === may.home_player;
}

/** canEditDeck for a deck known only by its id: looked up in the last library answer. */
function canEditDeckId(id) {
  if (!state.may) return true;
  const deck = state.library && (state.library.decks || []).find((d) => d.id === id);
  return deck ? canEditDeck(deck) : false;
}

/** Where the visitor may add decks: [{space, player}] (player null: any). */
function createTargets() {
  const may = state.may;
  if (!may) return spaceList().map((s) => ({ space: s.id, player: null }));
  return may.create || [];
}


// ------------------------------------------------- routes, names, titles

/* Every page's one name (decklab/UI-REVIEW.md 2.2), and where it sits: the routes table drives the top bar and
the phone's tab bar (shell.js), the crumbs, document.title and who sees which page. A route is
  {path, label (in the nav), h1 (the page heading), title (the tab title), icon (shell.js's ICONS),
   nav: "main" (the top bar and the phone's tab bar) | "more" (the More menu and sheet) | "account" (the avatar
   menu), visible(profile, may) (absent: everyone), parent (a child page's parent route)}.
Pages refine the tab title with their subject (setTitle). */
const ROUTES = [
  { path: "library", label: "Decks", h1: "Decks", title: "Decks", icon: "decks", nav: "main" },
  { path: "collection", label: "Collection", h1: "Collection", title: "Collection", icon: "collection", nav: "main" },
  { path: "shopping", label: "Shopping", h1: "Shopping", title: "Shopping", icon: "shopping", nav: "main",
    visible: (profile, may) => seesHomeInventory(may) },
  { path: "matchups", label: "Matchups", h1: "Matchups", title: "Matchups", icon: "matchups", nav: "main" },
  { path: "tokens", label: "Tokens", h1: "Tokens", title: "Tokens", icon: "tokens", nav: "more" },
  { path: "accessories", label: "Sleeves & boxes", h1: "Sleeves & boxes", title: "Sleeves & boxes", icon: "sleeves",
    nav: "more", visible: (profile, may) => may ? may.see_accessories !== false : seesAccessoriesAs(profile) },
  { path: "assembly", label: "Build decks", h1: "Build decks", title: "Build decks", icon: "plan", nav: "more",
    visible: (profile, may) => seesHomeInventory(may) },
  { path: "play", label: "Game log", h1: "Game log", title: "Game log", icon: "log", nav: "more" },
  { path: "wishlist", label: "Wishlist", h1: "Wishlist", title: "Wishlist", icon: "wishlist", nav: "more" },
  { path: "activity", label: "Activity", h1: "Activity", title: "Activity", icon: "activity", nav: "more" },
  { path: "visibility", label: "Who sees what", h1: "Who sees what", title: "Who sees what", icon: "settings", nav: "account",
    visible: (profile, may) => Boolean(profile) && Boolean(may && may.visibility && may.visibility.length) },
  { path: "settings", label: "Settings", h1: "Settings", title: "Settings", icon: "settings", nav: "account",
    visible: (profile, may) => isAdminProfile(profile, may) },
  // Child pages: reached from a page above, never from the nav.
  { path: "deck", label: "Deck", h1: "Deck", title: "Deck", parent: "library" },
  { path: "edit", label: "Edit deck", h1: "Edit deck", title: "Edit deck", parent: "deck" },
  { path: "new", label: "New deck", h1: "New deck", title: "New deck", parent: "library" },
  { path: "history", label: "History", h1: "History", title: "Deck history", parent: "deck" },
  { path: "variant", label: "Test of a change", h1: "Test of a change", title: "Test of a change", parent: "deck" },
  { path: "receipt", label: "Receive delivery", h1: "Receive delivery", title: "Receive delivery", parent: "shopping" },
  { path: "matchup", label: "Matchup", h1: "Matchup", title: "Matchup", parent: "matchups" },
];

/** The route of a path ("library", "deck", ...); the library's for an unknown one, as route() shows it. */
function routeFor(path) {
  return ROUTES.find((r) => r.path === path) || ROUTES[0];
}

/** The route a page belongs to in the nav: itself for a top-level page, else its nearest parent with a place
 * in the nav (a deck page is under Decks, a receipt under Shopping). */
function routeSection(path) {
  let route = routeFor(path);
  for (let step = 0; !route.nav && route.parent && step < 5; step += 1) route = routeFor(route.parent);
  return route;
}

/** True when the visitor may see a route (its visible() with the profile chosen and /api/me's "may"). */
function routeVisible(route, profile = state.profile, may = state.may) {
  return !route.visible || Boolean(route.visible(profile, may));
}

/** The routes of one nav group ("main", "more", "account") that the visitor sees, in order. */
function navRoutes(group, profile = state.profile, may = state.may) {
  return ROUTES.filter((r) => r.nav === group && routeVisible(r, profile, may));
}

/** A route's heading ("Build decks"), for the pages' h1. */
function routeH1(path) { return routeFor(path).h1; }

/** Whether a "may" lets its visitor see home's records: the shopping list, receipts and packing plan
 * ("may".see_home_records, the home profiles only, E10-S29; an older server's answer by see_inventory). */
function seesHomeInventory(may) {
  if (may && typeof may.see_home_records === "boolean") return may.see_home_records;
  const seen = may ? may.see_inventory : null;
  return !Array.isArray(seen) || seen.includes(HOME_SPACE);
}

/** True for an admin profile (config.json's role); with no roles at all, by /api/me's "may" as before. The role
 * decides wherever the page is opened, as the server's checks do (lib/permissions.py). */
function isAdminProfile(profile = state.profile, may = state.may) {
  if (profile && profile.role) return profile.role === "admin";
  return !may || Boolean(may.admin);
}

/** Each run's server answer decides Stop: its starter, a participant's space, or an admin. Older answers
 * without a per-run decision retain the admin-only fallback. The server rechecks every stop. */
function mayStopRuns(run = null, profile = state.profile, may = state.may) {
  if (!profile) return false;
  return typeof run?.may_stop === "boolean" ? run.may_stop : isAdminProfile(profile, may);
}

/** The tab title, "Boros Burn – Deck Lab" (just "Deck Lab" for none); the phone's top bar shows it too. */
function setTitle(text) {
  document.title = text ? `${text} – Deck Lab` : "Deck Lab";
  const shown = document.getElementById("topbar-title");
  if (shown) shown.textContent = text || "Deck Lab";
}

/* The two lists a deck can have, in all of the page's wording (decision 2 of the review). The deck text's own
headings ("## Decklist", "### Substitute version (owned and incoming cards)") and the version keys (target,
owned) don't change. */
const LIST_NAME = { target: "Planned list", owned: "Play-now list" };

/** "Planned list" or "Play-now list" for a version key; lower: "planned list", inside a sentence. */
function listName(version, lower = false) {
  const name = LIST_NAME[version] || LIST_NAME.target;
  return lower ? name[0].toLowerCase() + name.slice(1) : name;
}

/** A child page's way back, top left: "← Shopping", "← Boros Burn" (named after the parent). The phone's top
 * bar shows the same link (shell.js), so the page's own copy is hidden there. */
function crumb(href, label) {
  state.crumb = { href, label };
  if (typeof syncShellBack === "function") syncShellBack();
  return el("nav", { class: "crumbs shell-crumb", "aria-label": "Breadcrumb" },
    el("a", { href, text: `← ${label}` }));
}

/** A page's head: an optional crumb ([href, label]), the h1 and a one-line description, then one primary
 * action and the rest in a "More" menu (menuButton's items). Returns the nodes to add. */
function pageHead({ crumb: back = null, title, description = null, primary = null, more = null, id = null, badge = null } = {}) {
  const extra = (more || []).filter(Boolean);
  return [
    back ? crumb(back[0], back[1]) : null,
    el("div", { class: "page-head page-head-actions" },
      el("div", {}, badge ? el("div", { class: "page-head-title" }, el("h1", { id, text: title }), badge)
        : el("h1", { id, text: title }), description ? el("p", { text: description }) : null),
      primary || extra.length ? el("div", { class: "actions page-head-buttons" }, primary,
        extra.length ? menuButton("More", extra) : null) : null),
  ];
}

let menuSeq = 0;

/** A button that opens a menu of actions under it ("More ▾", a row's "⋯"). items: {label, href} links and
 * {label, onclick} buttons ({danger, current} optional), and "sep" for a line between groups. Esc, a click
 * outside and choosing an item close it; the arrow keys move through it. aria names a button whose label
 * is only a symbol. */
function menuButton(label, items, { aria = null, buttonClass = "btn btn-secondary" } = {}) {
  const id = `menu-${++menuSeq}`;
  const menu = el("div", { class: "menu", id, role: "menu", hidden: true },
    items.filter(Boolean).map((item) => {
      if (item === "sep") return el("div", { class: "menu-sep", role: "separator" });
      const props = { role: "menuitem", class: item.danger ? "menu-danger" : null, text: item.label,
        "aria-current": item.current ? "page" : null };
      return item.href ? el("a", { ...props, href: item.href, onclick: () => closeMenus() })
        : el("button", { ...props, type: "button", onclick: (event) => { closeMenus(); item.onclick(event); } });
    }));
  const button = el("button", { type: "button", class: `${buttonClass} menu-button`, "aria-haspopup": "menu",
    "aria-expanded": "false", "aria-controls": id, "aria-label": aria },
    label, el("span", { class: "menu-caret", "aria-hidden": "true" }));
  return el("span", { class: "menu-wrap" }, wireMenu(button, menu), menu);
}

/** Open and close a popover (a menu) from its button: aria-expanded follows it, Esc and a click outside close
 * it, focus moves into it on opening and the arrow keys move through its items. Returns the button. */
function wireMenu(button, menu) {
  menu.setAttribute("data-popover", "");
  button.addEventListener("click", () => {
    const opening = menu.hidden;
    closeMenus();
    if (!opening) return;
    menu.hidden = false;
    keepInWindow(menu);
    button.setAttribute("aria-expanded", "true");
    const first = menu.querySelector("[role=menuitem]") || menu.querySelector("button") || menu.querySelector("a");
    if (first && first.focus) first.focus();
  });
  menu.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMenus();
      button.focus();
      event.preventDefault();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const items = [...menu.querySelectorAll("[role=menuitem]")];
    if (!items.length) return;
    const at = items.indexOf(document.activeElement), down = event.key === "ArrowDown";
    items[at < 0 ? (down ? 0 : items.length - 1) : (at + (down ? 1 : -1) + items.length) % items.length].focus();
    event.preventDefault();
  });
  return button;
}

/** Shift an open menu sideways so it stays 8 px inside the window (a More at the right end of a row would
 * otherwise run off the edge). Its CSS place is kept; only a translate is added. */
function keepInWindow(menu) {
  if (!menu.style || !menu.getBoundingClientRect || !document.documentElement) return;
  menu.style.translate = "";
  const box = menu.getBoundingClientRect(), width = document.documentElement.clientWidth;
  if (!(width > 0) || !(box.width > 0)) return;
  const shift = box.right > width - 8 ? Math.max(width - 8 - box.right, 8 - box.left) : box.left < 8 ? 8 - box.left : 0;
  if (shift) menu.style.translate = `${Math.round(shift)}px 0`;
}

/** Close every open popover menu. */
function closeMenus() {
  for (const menu of document.querySelectorAll("[data-popover]")) {
    if (menu.hidden) continue;
    menu.hidden = true;
    for (const button of document.querySelectorAll(`[aria-controls="${menu.id}"]`)) {
      button.setAttribute("aria-expanded", "false");
    }
  }
}

// A click anywhere but in an open menu or on its own button closes it; so does Esc. Only a popover's own
// button is left to its handler (which opens or closes it): other things with aria-haspopup, such as card
// rows and tiles that open the card viewer, close an open menu like any other click.
// On a touch screen the tap that closes a menu does only that: it isn't also a tap on whatever was under the
// finger (a deck tile, a link), which the person couldn't see was there. A mouse click goes on through.
document.addEventListener("click", (event) => {
  const target = event.target;
  if (target && target.closest && (target.closest("[data-popover]") || opensPopover(target.closest("[aria-controls]")))) return;
  const open = [...document.querySelectorAll("[data-popover]")].some((menu) => !menu.hidden);
  closeMenus();
  if (open && coarsePointer()) { event.preventDefault(); event.stopPropagation(); }
}, true);

/** True on a touch screen (the primary pointer is a finger). */
function coarsePointer() {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(pointer: coarse)").matches;
}

/** True when button is the button of a popover menu (wireMenu's): its aria-controls names a [data-popover]. */
function opensPopover(button) {
  if (!button) return false;
  const menu = document.getElementById(button.getAttribute("aria-controls"));
  return Boolean(menu && menu.getAttribute("data-popover") !== null);
}
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeMenus(); });


// ------------------------------------------------- history entries: Back closes

/** A new history entry at the same address, at the next place (app.js entryPos), marked with mark ({cardViewer}
 * or {sheet}), so a phone's Back closes what opened it instead of leaving the page. Returns the entry's place, or
 * null where history can't take one. A mark left on the entry this one starts from is dropped. The page's only
 * pushState: everything else replaces. */
function pushHistoryEntry(mark) {
  if (typeof history === "undefined" || typeof history.pushState !== "function") return null;
  const here = typeof entryPos === "function" ? entryPos() : history.length - 1;
  const now = history.state && typeof history.state === "object" ? history.state : {};
  const { cardViewer, sheet, ...rest } = now;
  history.pushState({ ...rest, pos: here + 1, ...mark }, "");
  return here + 1;
}

// The open sheets that have a history entry, oldest first: {token, pos, close, done, fromHistory}.
const sheetEntries = [];
let sheetEntrySeq = 0;
let sheetBackWired = false;

/** Gives an opening sheet (openSheet's, the phone's More sheet) a history entry, so Back closes it; close() is
 * how to close it. Returns the entry for releaseSheetEntry, or null without history. An entry a closed sheet left
 * behind (it closed and something else opened before Back could step off it) is reused rather than stacked. */
function pushSheetEntry(close) {
  if (typeof history === "undefined" || typeof history.pushState !== "function") return null;
  if (!sheetBackWired && typeof window !== "undefined" && window.addEventListener) {
    sheetBackWired = true;
    // Back (or Forward) onto an earlier place closes the sheets opened after it, the newest first.
    window.addEventListener("popstate", () => {
      const s = history.state;
      const pos = s && typeof s === "object" && typeof s.pos === "number" ? s.pos : -1;
      for (const entry of [...sheetEntries].reverse()) {
        if (entry.pos > pos && !entry.done) { entry.fromHistory = true; entry.close(); }
      }
    });
  }
  const entry = { token: ++sheetEntrySeq, pos: null, close, done: false, fromHistory: false };
  const now = history.state && typeof history.state === "object" ? history.state : null;
  if (now && now.sheet && typeof now.pos === "number" && !sheetEntries.some((e) => e.token === now.sheet)) {
    history.replaceState({ ...now, sheet: entry.token }, "");
    entry.pos = now.pos;
  } else {
    entry.pos = pushHistoryEntry({ sheet: entry.token });
  }
  if (entry.pos == null) return null;
  sheetEntries.push(entry);
  return entry;
}

/** A sheet with an entry has closed. Closed by Back, there's nothing more to do; closed any other way, Back steps
 * off its entry, unless the page has already moved on (a link in it, a save that went to another page). */
function releaseSheetEntry(entry) {
  if (!entry || entry.done) return;
  entry.done = true;
  sheetEntries.splice(sheetEntries.indexOf(entry), 1);
  if (entry.fromHistory) return;
  setTimeout(() => {
    if (history.state && history.state.sheet === entry.token) history.back();
  }, 0);
}

/** A link inside a sheet with an entry: the sheet's entry becomes the link's page (location.replace), so Back
 * from there goes to the page under the sheet, not to the sheet's entry first. Call it from the dialog's click. */
function sheetLinkClick(event, entry, close) {
  if (!entry || entry.done || event.defaultPrevented || event.button > 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
  const link = event.target && event.target.closest ? event.target.closest("a[href^='#']") : null;
  if (!link || link.target || !(history.state && history.state.sheet === entry.token)) return;
  event.preventDefault();
  entry.fromHistory = true;           // its entry is taken over, not stepped off
  close();
  location.replace(link.getAttribute("href"));
}


// ------------------------------------------------------------ errors, toast

function showPageError(message) {
  const box = el("div", { class: "box box-crit" },
    el("h2", { text: "Something went wrong on this page" }),
    el("p", { text: message }),
    el("div", { class: "actions" }, el("button", { type: "button", class: "btn", text: "Reload the page",
      onclick: () => location.reload() })));
  $("#page-errors").append(box);
}

/** A masked browser/cross-origin report has no information linking it to our page code.
 * Keep it in the console; real exceptions and reports with a source still use the page panel. */
function opaqueWindowError(event) {
  return /^Script error\.?$/i.test((event.message || "").trim())
    && !event.filename && !event.lineno && !event.colno && !event.error;
}

window.addEventListener("error", (event) => {
  if (opaqueWindowError(event)) {
    console.warn("Browser reported an opaque script error; no page source was supplied.", event);
    return;
  }
  const where = event.filename ? ` (${event.filename.split("/").pop()}:${event.lineno})` : "";
  showPageError(`${event.message || "Unknown error"}${where}`);
});
window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  showPageError(reason && reason.message ? reason.message : String(reason));
});

let toastTimer = 0;
function toast(message) {
  const box = $("#toast");
  box.textContent = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.textContent = ""; }, 5000);
}


// --------------------------------------------------------------------- API

class ApiError extends Error {
  /** data: the whole error answer, for its extra keys ("blocks", "conflict"). */
  constructor(status, message, data) { super(message); this.status = status; this.data = data || null; }
}

/** The JSON answer of a Deck Lab API call; ApiError(status, message) otherwise. Every call names the
 * profile chosen (X-Deck-Lab-Viewer), so on the home network the server answers with what that profile
 * sees: its own and the shared sleeves, deck boxes and playmats (through the tunnel the login decides). */
async function api(path, options = {}) {
  let response;
  const viewer = state.profile ? { "X-Deck-Lab-Viewer": state.profile.id } : {};
  try {
    response = await fetch(path, { ...options,
      headers: { Accept: "application/json", ...viewer, ...(options.headers || {}) } });
  } catch (e) {
    throw new ApiError(0, "The Deck Lab server can't be reached. Check that it's running on the PC " +
      "and that this device is on the home network.");
  }
  let data = null;
  try { data = await response.json(); } catch (e) { /* not JSON: handled below */ }
  if (!response.ok) {
    throw new ApiError(response.status, (data && data.error) || `The server answered ${response.status}.`, data);
  }
  if (data === null) throw new ApiError(response.status, "The server's answer wasn't JSON.");
  return data;
}

/** A write to the Deck Lab API: JSON with the header the server's write check needs (so another web
 * page open on the phone can't make changes), and for a POST the profile making the change. */
function apiWrite(path, body, method = "POST") {
  const data = method === "POST" ? { profile: state.profile && state.profile.id, ...body } : body;
  return api(path, {
    method,
    headers: { Accept: "application/json", "Content-Type": "application/json", "X-Deck-Lab": "1" },
    body: JSON.stringify(data),
  });
}

function loadingBox(text) {
  return el("p", { class: "loading", role: "status" },
    el("span", { class: "spinner", "aria-hidden": "true" }), text || "Loading...");
}

/** Fetch path and hand the answer to draw(); a list of paths is fetched at once, and draw() gets the
 * list of answers. Shows a loading state; while the card data isn't ready (503) it says so and retries;
 * any other error shows the server's message (errorBox), the database being down included (a 503 with
 * reason "database": waiting for the card data wouldn't help). token: the route it's for. title and back
 * (errorBox's) are for that error. */
async function load(path, token, draw, { title = "This page couldn't be loaded", back } = {}) {
  const main = $("#main");
  clear(main).append(loadingBox());
  let waited = false;
  for (;;) {
    try {
      const data = Array.isArray(path) ? await Promise.all(path.map((p) => api(p))) : await api(path);
      if (token !== routeToken) return;
      clear(main);
      draw(data);
      afterRender();
      if (waited) showFooter();       // the card data has arrived: say so at the bottom too
      return;
    } catch (e) {
      if (token !== routeToken) return;
      if (!(e instanceof ApiError)) throw e;
      if (e.status === 503 && e.data?.reason !== "database") {
        waited = true;
        await waitForCards(main, e.message, token,
          e.data?.reason === "off" ? "Deck Lab is off" : "The card data isn't ready yet");
        if (token !== routeToken) return;
        continue;
      }
      clear(main).append(errorBox(title, e, route, back));
      afterRender();
      return;
    }
  }
}

/** An error in place of a page: the message, "Try again" (retry; none when it's null, or when loading
 * the page again can't help: a bad address, 400, or something that isn't there, 404; another retry,
 * like Deck Lab's start-up, is always offered), and a way back: back is [href, words]. */
function errorBox(title, error, retry = route, back = ["#/library", "Back to the library"]) {
  const code = error.status ? ` (error ${error.status})` : "";
  const again = retry && (retry !== route || (error.status !== 400 && error.status !== 404));
  return el("div", { class: "box box-crit" },
    el("h2", { class: "box-head", text: title }),
    el("p", { text: error.message + code }),
    el("div", { class: "actions" },
      again ? el("button", { type: "button", class: "btn btn-primary", text: "Try again", onclick: () => retry() }) : null,
      el("a", { class: again ? "btn" : "btn btn-primary", href: back[0], text: back[1] })));
}

/** Show why the card data isn't ready (or, with reason "off" from the off page's Worker, that Deck Lab
 * isn't running at home), count down, and resolve when it's time to retry. */
function waitForCards(main, message, token, title = "The card data isn't ready yet") {
  return new Promise((resolve) => {
    let left = RETRY_SECONDS;
    const counter = el("span", { text: String(left) });
    let timer = 0;
    const done = () => { clearInterval(timer); resolve(); };
    clear(main).append(el("div", { class: "box box-info", role: "status" },
      el("h2", { text: title }),
      el("p", { text: message }),
      el("p", {}, "Trying again in ", counter, " seconds."),
      el("div", { class: "actions" }, el("button", { type: "button", class: "btn", text: "Try now", onclick: done }))));
    timer = setInterval(() => {
      if (token !== routeToken) return done();
      left -= 1;
      counter.textContent = String(Math.max(left, 0));
      if (left <= 0) done();
    }, 1000);
  });
}
