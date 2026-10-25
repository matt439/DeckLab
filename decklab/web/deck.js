/* Deck Lab's page: the deck view (#/deck?id=<deck id>&v=target|owned[&tab=<tab>][&filter=<filter>]), rebuilt
in WP7 of decklab/UI-REVIEW.md.

The page answers "what is this deck, and can I build it?" first: a head (the title with its colour pips, a
status pill, one line of facts, Edit and a More menu), then the availability banner (Ready to build, on the
way, or what's missing and roughly what it costs, with Show missing; the Planned list / Play-now list picker
folds into it), then five tabs: Overview, Cards, Stats, Practice and Matchups. The tab is in the address
(?tab=), changed in place without a new history entry, and each tab's parts are drawn the first time it
opens: the practice games start when Practice opens, and the matchups (the API's slowest part, asked for
with omit=matchups until then) when Matchups does.

Overview: the stats' verdict strip (stats.js statsVerdict), the key cards as big pictures, a token problem,
the sleeves and deck box of a built deck, and the play guide (guide.js). Cards: the decklist as a list or as
pictures at every width (remembered), filtered to All, Missing, On the way or In other decks, each card
marked from /api/deck's owned rows (missing copies greyed; under Missing, deck-swaps.js's owned stand-ins), then
the Play-now list's swaps (deck-swaps.js), the Tokens part and the price table
(folded; one line when everything is here). Stats: stats.js. Practice: hands.js's "Deal a hand" and
practice.js's practice games. Matchups: deck-tools.js deckMatchupsPart, field.js and variant.js.

A visitor who may not see the deck's space's collection gets no owned, tokens or table from /api/deck, so
the page has no banner, no card marks, no Tokens part and no price table for them.

Loaded after core.js, library.js and deck-availability.js (the banner and incoming-source labels). It uses
core.js's helpers, cards-ui.js's cardRow and cardTile, and once the page runs stats.js's statsSection,
statsVerdict, tile and drawCharts, guide.js, practice.js, hands.js,
deck-tools.js's deckTools pieces and deckMatchupsPart, accessories.js's accessoryThumb, kitChip and kitPicker,
tokens.js's tokenNeedList, editor-deckpage.js's deckActions, savedBox and staleTableBox, and app.js's
playerWords and jumpTo. app.js's route() calls showDeck(), and start() calls setUpPeek(). Its card helpers
(typeGroup, manaCost, cardLink, cardNames, cardThumb, peekLayout, peekable, ...) and pairingLinks() are used
by stats.js, practice.js, the editor's scripts and the matchup scripts. Nothing here runs at load but its
tables and the peek's empty state.
*/
"use strict";

// Decklist groups, in the order they're shown; a card goes in the first of
// TYPE_PRIORITY its front face has (an artifact creature is a creature).
const TYPE_GROUPS = ["Creatures", "Instants", "Sorceries", "Artifacts", "Enchantments",
  "Planeswalkers", "Battles", "Lands", "Other cards"];
const SECTION_CAPTIONS = { Deck: "Main deck", Sideboard: "Sideboard", Commander: "Commander", Companion: "Companion" };
const TYPE_PRIORITY = [["Creature", "Creatures"], ["Land", "Lands"], ["Planeswalker", "Planeswalkers"],
  ["Battle", "Battles"], ["Instant", "Instants"], ["Sorcery", "Sorceries"],
  ["Artifact", "Artifacts"], ["Enchantment", "Enchantments"]];
// The deck page's tabs: [name in the address, words].
const DECK_TABS = [["overview", "Overview"], ["cards", "Cards"], ["stats", "Stats"], ["practice", "Practice"],
  ["matchups", "Matchups"]];
// The Cards tab's filters: [name in the address, words, what a card's marks must have].
const CARD_FILTERS = [["all", "All"], ["missing", "Missing"], ["coming", "On the way"], ["held", "In other decks"]];
const KEY_CARDS = 6;                    // the Overview's big pictures
const CARDS_VIEW_KEY = "deck.cardsView"; // localStorage: "list" or "pictures", the Cards tab's last choice

// The deck on screen: {data, view: {tab, filter, mode}, built: Set of tabs drawn, strip, panels}. null elsewhere.
let deckScreen = null;


// -------------------------------------------------------------- deck view

function showDeck(params, token) {
  const id = addressDeckId(params.get("id"));
  const version = params.get("v") === "owned" ? "owned" : "target";
  const view = deckViewOf(params);
  // The matchups are the answer's slowest part: asked for when their tab opens (deck-tools.js).
  const omit = view.tab === "matchups" ? "" : "&omit=matchups";
  load(`/api/deck?id=${encodeURIComponent(id)}&version=${version}${omit}`, token, (data) => {
    canonicalDeckAddress(data.summary.id);
    drawDeck(data, view);
  });
}

/** The tab and filter an address asks for: ?tab= (an old ?part=field link opens Matchups) and ?filter=. */
function deckViewOf(params) {
  let tab = params.get("tab");
  if (!DECK_TABS.some(([name]) => name === tab)) tab = params.get("part") === "field" ? "matchups" : "overview";
  const filter = params.get("filter");
  return { tab, filter: CARD_FILTERS.some(([name]) => name === filter) ? filter : "all" };
}

function drawDeck(data, view = { tab: "overview", filter: "all" }) {
  const s = data.summary;
  setTitle(s.title);
  state.cards = new Map();
  for (const lines of Object.values(data.sections)) {
    for (const line of lines) {
      if (line.card && !state.cards.has(line.card.name)) state.cards.set(line.card.name, line.card);
    }
  }
  const screen = deckScreen = { data, view: { ...view }, built: new Set(), strip: null, panels: new Map(),
    marks: cardMarks(data) };
  const tabs = deckTabStrip(screen);
  add($("#main"), [peekLayout(`deck:${s.id}:${data.version}`, firstCard(data.sections), [
    // Back to the library as it was left (its filters; the scroll position comes back too).
    crumb(state.libraryHash || "#/library", routeFor("library").label),
    savedBox(s.id),                 // editor-deckpage.js: what the save just made did (null otherwise)
    el("div", { class: "deck-top" },
      deckHeader(data),
      availabilityBanner(data, screen),
      warningsBox(deckWarnings(data), "Warnings")),
    tabs])]);
  selectDeckTab(screen.view.tab, { initial: true });
}

/** The tab strip (role tablist, sticky under the top bar) and an empty panel per tab. */
function deckTabStrip(screen) {
  const strip = el("div", { class: "tabs deck-tabs", role: "tablist", "aria-label": "Parts of this deck" });
  const panels = el("div", { class: "deck-panels" });
  for (const [name, label] of DECK_TABS) {
    strip.append(el("button", { type: "button", role: "tab", id: `deck-tab-${name}`, "data-tab": name,
      "aria-controls": `deck-panel-${name}`, "aria-selected": "false", tabindex: "-1", text: label,
      onclick: () => selectDeckTab(name, { focus: false }) }));
    const panel = el("div", { class: "deck-panel", role: "tabpanel", id: `deck-panel-${name}`,
      "aria-labelledby": `deck-tab-${name}`, hidden: true });
    screen.panels.set(name, panel);
    panels.append(panel);
  }
  // The arrow keys, Home and End move between the tabs (and open them), as a tablist's should.
  strip.addEventListener("keydown", (e) => {
    const names = DECK_TABS.map(([name]) => name);
    const at = names.indexOf(screen.view.tab);
    const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: names.length - 1 }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    selectDeckTab(names[(to + names.length) % names.length], { focus: true });
  });
  screen.strip = strip;
  stackPanels(panels);
  return [strip, panels];
}

const STACK_ROW = 8;            // px: a stacked .panels grid's row (deck.css), which each panel spans enough of
const STACK_GAP = 24;           // px under each stacked panel (--s-5)

/** From 1,000 px (iPad landscape, MacBook, QHD) the Stats and Practice tabs' panels sit in columns of very
 * different heights (Land count beside Colour sources): each panel spans as many of the grid's small rows as it's
 * tall (it changes as its details open), and dense flow fills each gap with the next panel that fits, so no
 * column leaves a hole the height of its neighbour. Narrower (one column), the grid is as components.css has it. */
function stackPanels(root) {
  if (typeof ResizeObserver === "undefined" || typeof MutationObserver === "undefined" || !window.matchMedia) return;
  const wide = window.matchMedia("(min-width: 1000px)");
  const fit = (panel) => {
    if (!wide.matches) { panel.style.gridRowEnd = ""; return; }
    const h = panel.getBoundingClientRect().height;
    if (h) panel.style.gridRowEnd = `span ${Math.ceil((h + STACK_GAP) / STACK_ROW)}`;
  };
  const sizes = new ResizeObserver((entries) => entries.forEach((e) => fit(e.target)));
  const watch = () => {
    for (const grid of root.querySelectorAll(".panels")) {
      grid.classList.add("is-stacked");
      for (const panel of grid.children) {
        if (panel.dataset.stacked) continue;
        panel.dataset.stacked = "1";
        sizes.observe(panel);
      }
    }
  };
  new MutationObserver(watch).observe(root, { childList: true, subtree: true });
  if (wide.addEventListener) wide.addEventListener("change", () => root.querySelectorAll(".is-stacked > *").forEach(fit));
  watch();
}

/** Show a tab of the deck on screen: its parts are drawn the first time, its charts drawn once it's shown,
 * and the address says which tab (and the Cards filter) without a new history entry. opts: focus (move the
 * focus to its tab), initial (the first draw: no scrolling), to (an element id to scroll to in it), filter
 * (the Cards filter to set). */
function selectDeckTab(name, opts = {}) {
  const screen = deckScreen;
  if (!screen || !screen.panels.has(name)) return;
  if (opts.filter) screen.view.filter = opts.filter;
  screen.view.tab = name;
  for (const button of screen.strip.querySelectorAll("[role=tab]")) {
    const on = button.dataset.tab === name;
    button.setAttribute("aria-selected", String(on));
    button.setAttribute("tabindex", on ? "0" : "-1");
    if (on && opts.focus) button.focus();
    if (on) revealTab(screen.strip, button);
  }
  for (const [tab, panel] of screen.panels) panel.hidden = tab !== name;
  for (const banner of document.querySelectorAll(".deck-avail")) banner.classList.toggle("is-on-cards", name === "cards");
  const panel = screen.panels.get(name);
  if (!screen.built.has(name)) {
    screen.built.add(name);
    add(panel, deckTabParts(name, screen.data, screen));
  } else if (name === "cards" && opts.filter) {
    redrawCards(screen);
  }
  drawCharts();
  deckAddress(screen);
  if (opts.initial) return;
  if (opts.to) {
    const target = document.getElementById(opts.to);
    if (target) { jumpTo(opts.to); return; }
  }
  // A tab chosen with the strip stuck to the top starts at its own top, just under the strip.
  // Where it sticks: under the top bar, or at the screen's top on a phone on its side (shell.css).
  const top = screen.strip.getBoundingClientRect().top;
  const sticksAt = parseFloat(typeof getComputedStyle === "function" && getComputedStyle(screen.strip).top);
  const stuck = top <= (Number.isFinite(sticksAt) ? sticksAt : SHELL_TOP) + 1
    && panel.getBoundingClientRect().top < top + screen.strip.offsetHeight;
  if (stuck) panel.scrollIntoView({ block: "start" });
}

/** Scroll the tab strip sideways (a phone's strip is wider than the screen) so button shows. Only the strip
 * moves: the window stays where it is, even on the first draw with the strip below the fold. */
function revealTab(strip, button) {
  const s = strip.getBoundingClientRect(), b = button.getBoundingClientRect();
  if (!s || !b) return;
  if (b.left < s.left) strip.scrollLeft -= s.left - b.left + 16;
  else if (b.right > s.right) strip.scrollLeft += b.right - s.right + 16;
}

/** The tab name's parts, drawn when it first opens. */
function deckTabParts(name, data, screen) {
  if (name === "overview") return overviewParts(data);
  if (name === "cards") return cardsParts(data, screen);
  if (name === "stats") return [statsSection(data)];
  if (name === "practice") return [manualHandsSection(data), practiceSection(data)];
  return [deckMatchupsPart(data), fieldSection(data), variantTestsSection(data)];     // deck-tools.js, field.js, variant.js
}

/** Write the tab (and the Cards filter) into the address in place: Back still leaves the deck in one step. */
function deckAddress(screen) {
  const { path, params } = parseHash();
  if (path !== "deck") return;
  const { tab, filter } = screen.view;
  if (tab === "overview") params.delete("tab"); else params.set("tab", tab);
  if (tab === "cards" && filter !== "all") params.set("filter", filter); else params.delete("filter");
  params.delete("part");
  const hash = `#/deck?${params.toString()}`;
  if (hash !== location.hash) history.replaceState(history.state, "", hash);
  // The Planned list / Play-now list links open the other list on the same tab (opened in a new tab too).
  for (const [v, link] of screen.versionLinks || []) link.setAttribute("href", versionHref(screen.data, v, tab));
}

/** A list's address on tab (the Overview is the address without one). */
function versionHref(data, version, tab) {
  return deckHref(data.summary.id, version) + (tab && tab !== "overview" ? `&tab=${tab}` : "");
}

/** Open a tab of the deck on screen (the banner's Show missing, the Overview's links). */
function openDeckTab(name, opts = {}) { selectDeckTab(name, { focus: false, ...opts }); }


// ----------------------------------------------------------------- the head

/** The head: the title with its colour pips, then Edit (or Try a change, or Save as a new deck) and More on
 * the same row (More is a compact "⋯" on a phone), a status pill and one line of facts. More holds the packing
 * plan, game log, history, copy, download, print and the library picture, which shows small beside the title.
 * The sentence the editor puts beside
 * a product's or someone else's button goes under the facts, so the title keeps its row. A Beginner Box half
 * links to its pairings. */
function deckHeader(data) {
  const s = data.summary;
  const colours = deckColourPieces(deckPageColours(data));     // ui.js
  const actions = deckActions(data);      // editor-deckpage.js
  // The editor's "build on your computer" sentence isn't for this head: without an Edit there's just More.
  const edit = actions && /desktop-build-note/.test(actions.getAttribute("class") || "") ? null : actions;
  const said = [];
  if (edit) for (const words of edit.querySelectorAll(".sub")) { said.push(words.textContent); words.remove(); }
  const more = menuButton([el("span", { class: "deck-more-words", text: "More" }),
    el("span", { class: "deck-more-dots", "aria-hidden": "true", text: "⋯" })], deckMoreItems(data),
  { aria: "More for this deck" });
  return el("header", { class: "deck-head deck-page-head" },
    el("div", { class: "deck-title-row" },
      deckHeadCover(s),
      el("h1", {}, s.title),
      colours ? colours.pips(22, { cls: "deck-head-pips" }) : null),
    el("div", { class: "actions deck-head-actions" }, edit, more),
    el("p", { class: "deck-meta" }, deckPill(s), deckHeadMeta(data)),
    said.length ? el("p", { class: "sub deck-head-note", text: said.join(" ") }) : null,
    s.id.startsWith(BOX_PREFIX) ? pairingLinks(s.id) : null);
}

/** The status pill: Idea, Building or Built, or what a read-only deck is. */
function deckPill(s) {
  const words = s.read_only ? (s.id.startsWith("pairing/") ? "Pairing" : "Product")
    : STATUS_WORDS[s.status] || "No status";
  return el("span", { class: "chip chip-plain deck-pill", text: words });
}

/** The head's one line: "Casual 60 · Alex · 60 cards + 2 sideboard · Bracket 2", the halves of a pairing as
 * links, the built list of a two-list deck, and sleeves written as free text the accessories can't read. */
function deckHeadMeta(data) {
  const s = data.summary;
  const parts = [];
  const format = s.kind === "commander" && !s.read_only ? "Commander" : s.kind === "casual" && !s.read_only
    ? `Casual ${s.card_count >= 60 ? 60 : s.card_count}` : s.format;
  if (format) parts.push(format);
  if (!s.read_only) parts.push(deckPlayerWords(s));
  // A product's format already says its size ("Challenger deck (60 cards + 15 sideboard)").
  if (!(s.read_only && /\bcards?\b/.test(s.format || ""))) {
    parts.push(`${plural(s.card_count, "card")}` + (s.sideboard_count ? ` + ${s.sideboard_count} sideboard` : ""));
  }
  if (s.kind === "commander" && s.target_bracket) parts.push(`Bracket ${s.target_bracket}`);
  if (s.built_version && data.versions.length > 1) parts.push(`Built: ${listName(s.built_version, true)}`);
  else if (s.built_version_text) parts.push(`Built: ${s.built_version_text}`);
  if (s.sleeves && !s.kit && mayDo("see_accessories")) parts.push(`Sleeves: ${s.sleeves}`);
  if (s.halves) {
    parts.push(add(el("span", {}), s.halves.map((id, i) => [i ? " + " : "",
      el("a", { href: deckHref(id), text: capitalise(id.split("/").pop()) })])));
  }
  return factLine("deck-facts", parts);
}

/** The deck's colour identity, WUBRG order: the commander's, or every card's in the lists shown ([] for a
 * colourless deck). null when no card in them could be read, so the head shows no colours rather than C. */
function deckPageColours(data) {
  const found = new Set();
  const commanders = (data.sections.Commander || []).filter((l) => l.card);
  const lines = (commanders.length ? commanders : [...(data.sections.Deck || []), ...(data.sections.Companion || [])])
    .filter((l) => l.card);
  if (!lines.length) return null;
  for (const line of lines) for (const c of line.card.color_identity || []) found.add(c);
  return "WUBRG".split("").filter((c) => found.has(c));
}

/** The More menu's items. */
function deckMoreItems(data) {
  const s = data.summary;
  const id = encodeURIComponent(s.id);
  const home = seesInventory(HOME_SPACE) && deckSpaceOf(s.id) === HOME_SPACE;
  const retire = typeof canRetireDeck === "function" && canRetireDeck(data);
  const rename = typeof canRenameDeck === "function" && canRenameDeck(data);
  const token = routeToken, profile = state.profile?.id;
  // POST /api/deck/cover refuses products and pairings, so only a deck text the viewer may change.
  const cover = typeof openCoverPicker === "function" && !s.read_only
    && !/^(product|pairing)\//.test(s.id) && canEditDeck(s);
  return [
    home ? { label: routeH1("assembly"), href: `#/assembly?deck=${id}&version=${data.version}` } : null,
    { label: routeH1("play"), href: `#/play?id=${id}` },
    !s.read_only ? { label: "History", href: `#/history?id=${id}&v=${data.version}` } : null,
    "sep",
    { label: "Copy decklist", onclick: () => copyDeck(data) },
    { label: "Download decklist", onclick: () => downloadDeck(data) },
    { label: "Print play sheet", onclick: () => printDeck(data) },
    cover ? "sep" : null,
    // The library package's cover picker (cover.js), when it's there. A save (or its Undo) draws the page
    // again, so the head shows the new picture; the library is read again when it next opens.
    cover ? { label: "Change library picture…", onclick: () => openCoverPicker(s.id, () => {
      state.library = null;
      const here = parseHash();
      if (here.path === "deck" && addressDeckId(here.params.get("id") || "") === s.id) route();
    }) } : null,
    rename || retire ? "sep" : null,
    rename ? { label: "Rename deck…", onclick: () => {
      if (token === routeToken && profile === state.profile?.id) openRenameDeck(data);
    } } : null,
    retire ? { label: "Retire deck…", onclick: () => {
      if (token === routeToken && profile === state.profile?.id) openRetireDeck(data);
    } } : null,
  ];
}

/** The head's small picture: the deck's library picture (its cover card's art), beside the title from 600 px
 * (a phone's head keeps its row for the title, Edit and ⋯; lazy, so a phone never fetches it). null without
 * one. Decoration only: the title names the deck. */
function deckHeadCover(s) {
  const art = s.cover && s.cover.art;
  if (typeof art !== "string" || !art.startsWith("/img/")) return null;
  const img = el("img", { class: "deck-head-cover-img", src: art, alt: "", loading: "lazy", decoding: "async",
    width: 626, height: 457,
    onerror: () => { box.remove(); } });
  const box = el("span", { class: "deck-head-cover", "aria-hidden": "true", title: `Library picture: ${s.cover.name}` }, img);
  return box;
}


/** The deck page's warnings, without the kit's (too few sleeves and the like) for a profile that doesn't
 * see the home's sleeves: on the home network the server sends them to everyone, and the page hides them. */
function deckWarnings(data) {
  const kit = data.summary.kit;
  if (mayDo("see_accessories") || !kit || !kit.warnings) return data.warnings;
  return (data.warnings || []).filter((w) => !kit.warnings.includes(w));
}


// ----------------------------------------------------------------- overview

/** The Overview tab: the stats' verdict strip, the key cards big, a token problem, the sleeves and deck
 * box, and how to play it. */
function overviewParts(data) {
  const verdict = data.stats ? statsVerdict(data.stats, data.summary) : null;
  const total = copies(Object.entries(data.sections).filter(([name]) => name !== "Sideboard").flatMap(([, l]) => l));
  return [
    commanderReadiness(data),
    deckAssemblySection(data),
    verdict ? el("section", { class: "deck-section deck-overview-stats", "aria-label": "At a glance" }, verdict,
      el("button", { type: "button", class: "btn btn-quiet deck-more-link", text: "All the stats",
        onclick: () => openDeckTab("stats", { to: "deck-panel-stats" }) })) : null,
    keyCardsPart(data, total),
    deckTokensChip(data),
    deckKit(data),
    productStorageSection(data),
    deckStandinsSection(data),
    deckSwapsSection(data),
    deckOpponentsSection(data),
    deckSideboardSection(data),
    guideSection(data)];
}

/** The deck's key cards as big pictures: its commanders, then its spells. In a 60-card deck that's the
 * most-copied spells (dearest first). In a Commander deck, where every card is a single copy, it's the cards
 * its play guide names most (first named first), then the dearest. A swipe goes from one to the next (the
 * "key" viewer group). */
function keyCardsPart(data, total) {
  const commanders = (data.sections.Commander || []).filter((l) => l.card);
  const named = guideMentions(data);
  const byGuide = (a, b) => {
    const ra = named.get(a.name), rb = named.get(b.name);
    if (ra && rb) return rb.count - ra.count || ra.first - rb.first;
    return ra ? -1 : rb ? 1 : 0;
  };
  const singleton = data.summary.kind === "commander" || commanders.length > 0;
  const spells = mergedLines(data.sections.Deck || []).filter((l) => l.card && typeGroup(l.card) !== "Lands")
    .filter((l) => !commanders.some((c) => c.name === l.name))
    .sort((a, b) => (singleton ? byGuide(a, b) : 0) || b.qty - a.qty || b.card.cmc - a.card.cmc || a.name.localeCompare(b.name));
  const lines = [...commanders, ...spells].slice(0, Math.max(KEY_CARDS, commanders.length));
  if (!lines.length) return null;
  return el("section", { class: "deck-section deck-key", "aria-labelledby": "h-key" },
    el("div", { class: "deck-section-head" },
      el("h2", { id: "h-key", text: commanders.length ? "Commander and key cards" : "Key cards" }),
      el("button", { type: "button", class: "btn btn-quiet deck-more-link", text: `All ${plural(total, "card")}`,
        onclick: () => openDeckTab("cards", { to: "deck-panel-cards" }) })),
    el("div", { class: "deck-key-cards" }, lines.map((line) => bigTile(line.card, {
      qty: line.qty, name: line.name, viewerGroup: "key",
      caption: commanders.includes(line) ? "Commander" : `${plural(line.qty, "copy", "copies")} in the deck` }))));
}

/** How often the play guide names each of the deck's cards: name -> {count, first} (first: the order of
 * its first mention). Empty without a guide. */
function guideMentions(data) {
  const found = new Map();
  const sections = (data.guide && data.guide.sections) || [];
  const pattern = cardNamePattern();       // deck-tools.js
  if (!pattern || !sections.length) return found;
  for (const part of sections) {
    for (const match of String(part.markdown || "").matchAll(pattern)) {
      const seen = found.get(match[0]);
      if (seen) seen.count += 1; else found.set(match[0], { count: 1, first: found.size });
    }
  }
  return found;
}

/** A card tile drawn big: the large picture where the screen has the pixels for it (the /img/ route's
 * "large" size; cardTile falls back to the normal one when that size isn't there). */
function bigTile(card, opts) {
  return cardTile(card, { sizes: "(max-width: 599px) 46vw, 240px", large: largeImage(card), ...opts });
}

/** A card's /img/ address in another size ("large", "art_crop"), or null for a picture that isn't one. */
function cardImageSize(url, size) {
  return typeof url === "string" && /^\/img\/.+\/(small|normal)$/.test(url) ? url.replace(/(small|normal)$/, size) : null;
}

function largeImage(card) { return card ? cardImageSize(card.img, "large") : null; }


// ---------------------------------------------------------------- decklist

function typeGroup(card) {
  if (!card) return "Other cards";
  const front = card.type_line.split(" // ")[0].split(/\s+[—-]\s+/)[0];
  const words = new Set(front.split(/\s+/));
  for (const [type, group] of TYPE_PRIORITY) if (words.has(type)) return group;
  return "Other cards";
}

function byCostThenName(a, b) {
  const ca = a.card ? a.card.cmc : 99, cb = b.card ? b.card.cmc : 99;
  return ca - cb || a.name.localeCompare(b.name);
}

function copies(lines) { return lines.reduce((n, line) => n + line.qty, 0); }

/** Each card name's marks from the owned rows (only for a visitor who sees the collection): name ->
 * {missing, need, coming, sources, held: [[deck, copies]]}, the same as the price table's labels. */
function cardMarks(data) {
  const marks = new Map();
  if (!data.owned) return marks;
  for (const r of data.owned.rows) {
    const labels = rowLabels(r);
    marks.set(r.name, { missing: r.missing, need: r.need,
      coming: labels.on_the_way.reduce((n, [, qty]) => n + qty, 0),
      sources: rowIncomingSources(r), held: labels.in_use });
  }
  return marks;
}

/** The marks of each line shown: line -> {missing, need, coming, sources, held}.
 * A card in two sections (the main deck and the sideboard) has one owned row, so its copies are shared out:
 * the copies there are fill the first section first, so the missing ones fall on the last (the sideboard),
 * and its "on the way" and "in another deck" marks go on its first line only. */
function lineMarks(groups, marks) {
  const byLine = new Map(), left = new Map(), marked = new Set();
  for (const group of groups) {
    for (const line of group.lines) {
      const mark = marks.get(line.name);
      if (!mark) continue;
      if (!left.has(line.name)) left.set(line.name, Math.max(0, mark.need - mark.missing));
      const here = Math.min(line.qty, left.get(line.name));
      left.set(line.name, left.get(line.name) - here);
      const first = !marked.has(line.name);
      marked.add(line.name);
      byLine.set(line, { missing: line.qty - here, need: line.qty,
        coming: first ? mark.coming : 0, sources: first ? mark.sources : [], held: first ? mark.held : [] });
    }
  }
  return byLine;
}

/** Does a line's mark pass a Cards filter? */
function markPasses(mark, filter) {
  if (filter === "all") return true;
  if (!mark) return false;
  if (filter === "missing") return mark.missing > 0;
  if (filter === "coming") return mark.coming > 0;
  return mark.held.length > 0;
}

/** The copies a mark counts for a filter (the missing copies for Missing, and so on); a line's copies for All. */
function markCopies(mark, filter, line) {
  if (filter === "all") return line.qty;
  if (!mark) return 0;
  if (filter === "missing") return mark.missing;
  if (filter === "coming") return mark.coming;
  return mark.held.reduce((n, [, qty]) => n + qty, 0);
}

/** The chips a card's mark earns: only what's worth noticing ("1 of 2 missing", "1 on the way", "1 in Boros
 * Burn"). A card with every copy missing is greyed on the list already, so it gets the word only for a screen
 * reader; the viewer (full), where the card is shown big in colour, says "Missing · need 2, have 0". */
function markChips(mark, full = false) {
  if (!mark) return [];
  const chips = [];
  if (mark.missing > 0 && full) {
    chips.push(status("crit", `${mark.missing >= mark.need ? "Missing" : `${mark.missing} of ${mark.need} missing`} · ` +
      `need ${mark.need}, have ${Math.max(0, mark.need - mark.missing)}`));
  } else if (mark.missing > 0 && mark.missing >= mark.need) {
    chips.push(el("span", { class: "sr-only", text: "Missing" }));
  } else if (mark.missing > 0) {
    chips.push(status("crit", `${mark.missing} of ${mark.need} missing`));
  }
  if (mark.coming > 0) {
    if (mark.sources && mark.sources.length) chips.push(...mark.sources.map(incomingSourceChip));
    else chips.push(status("info", `${mark.coming} on the way`));
  }
  for (const [deck, n] of mark.held) chips.push(status("warn", `${n} in ${deck}`));
  return chips;
}

/** The decklist's sections in the order shown, each as groups of lines: [{section, title, lines}]. The main
 * deck is split by card type. A card written twice in one section (two printings) is one line, its
 * printings in its subtitle. */
function deckGroups(data) {
  const names = Object.keys(data.sections);
  const order = ["Commander", "Companion", "Deck", ...names.filter((n) => !["Commander", "Companion", "Deck", "Sideboard"].includes(n)), "Sideboard"];
  const groups = [];
  for (const section of order) {
    const lines = mergedLines(data.sections[section] || []);
    if (!lines.length) continue;
    if (section === "Deck") {
      const byType = new Map(TYPE_GROUPS.map((g) => [g, []]));
      for (const line of lines) byType.get(typeGroup(line.card)).push(line);
      for (const [title, members] of byType) if (members.length) groups.push({ section, title, lines: members.sort(byCostThenName) });
    } else {
      groups.push({ section, title: SECTION_CAPTIONS[section] || section, lines: lines.sort(byCostThenName) });
    }
  }
  return groups;
}

/** Lines of one section with each card once: {qty, name, card, printings: [{set, number, finish, qty}]}. */
function mergedLines(lines) {
  const byName = new Map();
  for (const line of lines) {
    const same = byName.get(line.name);
    const printing = { set: line.set, number: line.number, finish: line.finish, qty: line.qty };
    if (same) { same.qty += line.qty; same.printings.push(printing); continue; }
    byName.set(line.name, { qty: line.qty, name: line.name, card: line.card, printings: [printing] });
  }
  return [...byName.values()];
}

/** "LTC 318" for one printing ("· Foil" when it's not the usual), "LTC 318 ×1 · TDC 373 ×1" for several. */
function printingWords(printings) {
  const one = (p) => (p.set ? `${p.set.toUpperCase()}${p.number ? ` ${p.number}` : ""}` : "") +
    (p.finish && p.finish !== "nonfoil" ? `${p.set ? " " : ""}${capitalise(p.finish)}` : "");
  if (printings.length === 1) return one(printings[0]);
  return printings.map((p) => `${one(p) || "any printing"} ×${p.qty}`).join(" · ");
}

/** The Cards tab: the toolbar (filters for a visitor who sees the collection, List or Pictures), the
 * decklist, the Tokens part and the price table. */
function cardsParts(data, screen) {
  screen.view.mode = cardsMode();
  const list = el("div", { class: "deck-cards", id: "sec-cards" });
  screen.cardsHost = list;
  screen.cardsBar = el("div", { class: "toolbar deck-cards-bar" });
  redrawCards(screen);
  return [screen.cardsBar, list, deckSwapsSection(data), tokensSection(data), ownedSection(data)];
}

/** The remembered List or Pictures choice; the first time, pictures where the screen is wide. */
function cardsMode() {
  const saved = local.get(CARDS_VIEW_KEY);
  if (saved === "list" || saved === "pictures") return saved;
  return window.matchMedia && window.matchMedia("(min-width: 1000px)").matches ? "pictures" : "list";
}

/** Draw the Cards tab's toolbar and list again (a filter or the view changed). */
function redrawCards(screen) {
  const { data, view } = screen;
  const groups = deckGroups(data);
  const all = groups.flatMap((g) => g.lines);
  const marks = lineMarks(groups, screen.marks);
  // A filter's count is copies, as the banner's are ("32 missing"); the line under it counts different cards.
  const counts = new Map(CARD_FILTERS.map(([name]) => [name,
    all.reduce((n, l) => n + (markPasses(marks.get(l), name) ? markCopies(marks.get(l), name, l) : 0), 0)]));
  // A filter with nothing in it isn't offered; one asked for that has nothing shows all.
  if (view.filter !== "all" && !counts.get(view.filter)) view.filter = "all";
  const filters = CARD_FILTERS.filter(([name]) => name === "all" || counts.get(name) > 0);
  const choose = (patch) => { Object.assign(view, patch); redrawCards(screen); deckAddress(screen); };
  add(clear(screen.cardsBar), [
    filters.length > 1 ? el("div", { class: "segmented deck-filter", role: "group", "aria-label": "Show" },
      filters.map(([name, words]) => el("button", { type: "button", "aria-pressed": String(view.filter === name),
        onclick: () => choose({ filter: name }) }, words,
        name === "all" ? null : el("span", { class: "deck-filter-n", text: String(counts.get(name)) })))) : null,
    el("div", { class: "segmented deck-mode", role: "group", "aria-label": "Show the cards as" },
      [["list", "List"], ["pictures", "Pictures"]].map(([mode, words]) => el("button", { type: "button",
        "aria-pressed": String(view.mode === mode), text: words,
        onclick: () => { local.set(CARDS_VIEW_KEY, mode); choose({ mode }); } })))]);
  const shown = new Set(), parts = [];
  const filterWords = { missing: "missing", coming: "on the way", held: "in other decks" }[view.filter];
  for (const group of groups) {
    const lines = group.lines.filter((l) => markPasses(marks.get(l), view.filter));
    if (!lines.length) continue;
    for (const line of lines) shown.add(line.name);
    const items = lines.map((line) => (view.mode === "pictures"
      ? deckCardTile(line, group.section, marks.get(line))
      : el("li", {}, deckCardRow(line, group.section, marks.get(line)))));
    // Under a filter the heading counts what the filter is about: "Creatures (12 missing)".
    const count = filterWords ? `(${lines.reduce((n, l) => n + markCopies(marks.get(l), view.filter, l), 0)} ${filterWords})`
      : `(${copies(lines)})`;
    parts.push(el("div", { class: "type-group" },
      el("h3", {}, group.title, el("span", { class: "count", text: count })),
      view.mode === "pictures" ? el("div", { class: "card-tiles deck-tiles" }, items) : el("ul", { class: "card-list" }, items)));
  }
  const names = new Set(all.map((l) => l.name)).size;
  add(clear(screen.cardsHost), [view.filter === "all" ? null : el("p", { class: "result-count", role: "status" },
    `${shown.size} of ${names} different cards. `,
    el("button", { type: "button", class: "btn btn-quiet", text: "Show all", onclick: () => choose({ filter: "all" }) })),
  deckSwapFinder(screen), parts]);
}

/** One decklist line as cards-ui.js's cardRow, in the "deck" viewer group (a tap opens the viewer, which
 * swipes through the list as shown). Its thumbnail is the card's art (the /img/ route's art_crop; the small
 * picture when that size isn't there); a line with every copy missing is greyed, one with some missing
 * half greyed. */
function deckCardRow(line, section, mark) {
  const card = line.card;
  const printing = printingWords(line.printings || [line]);
  const row = cardRow(card, {
    qty: line.qty, name: line.name, meta: card ? card.type_line + (printing ? ` · ${printing}` : "") : undefined,
    unknownMeta: "Not a Scryfall card name, so there's no card data" + (printing ? ` · ${printing}` : ""),
    chips: markChips(mark), viewerGroup: "deck", caption: deckLineCaption(line, section),
    viewerStatus: () => markChips(mark, true) });
  const img = row.querySelector("img.thumb");
  const art = card && cardImageSize(card.img_small, "art_crop");
  if (img && art) {
    img.src = art;
    img.onerror = () => { img.onerror = null; img.src = card.img_small; };
  }
  if (mark && mark.missing > 0) row.classList.add(mark.missing >= mark.need ? "is-missing" : "is-partly-missing");
  return row;
}

/** One decklist line as a picture tile (the Pictures view). */
function deckCardTile(line, section, mark) {
  const tile = cardTile(line.card, { qty: line.qty, name: line.name, meta: printingWords(line.printings || [line]) || null,
    finish: (line.printings || [line]).length === 1 ? (line.printings || [line])[0].finish : null,
    chips: markChips(mark), viewerGroup: "deck", caption: deckLineCaption(line, section),
    viewerStatus: () => markChips(mark, true) });
  if (mark && mark.missing > 0) tile.classList.add(mark.missing >= mark.need ? "is-missing" : "is-partly-missing");
  return tile;
}

function deckLineCaption(line, section) {
  const printing = printingWords(line.printings || [line]);
  return `${plural(line.qty, "copy", "copies")} · ${SECTION_CAPTIONS[section] || section}${printing ? ` · ${printing}` : ""}`;
}

/** A card's small picture, width px wide (its height in proportion). wide is the sizes condition and
 * width it has where it's drawn bigger: the browser then takes the normal image instead. */
function cardThumb(card, cls, width, wide) {
  return el("img", { class: cls, alt: "", loading: "lazy", decoding: "async",
    srcset: card.img ? `${card.img_small} 146w, ${card.img} 488w` : null,
    sizes: card.img ? `${wide}, ${width}px` : null,
    src: card.img_small, width, height: Math.round(width * 680 / 488) });
}

/** The card the peek starts on: the commander, or the decklist's first card (its first group, cheapest first). */
function firstCard(sections) {
  const has = (line) => line.card && line.card.img;
  const commander = (sections.Commander || []).find(has);
  if (commander) return commander.card;
  const lines = (sections.Deck || []).filter(has);
  const group = (line) => TYPE_GROUPS.indexOf(typeGroup(line.card));
  lines.sort((a, b) => group(a) - group(b) || byCostThenName(a, b));
  return lines.length ? lines[0].card : null;
}

/** A mana cost such as "{2}{R}{R}" (or "{R} // {1}{U}") as Scryfall's symbols (symbols.js symbolImg; a
 * lettered circle when a picture can't load). The words are the cost's own aria-label. */
function manaCost(cost, small) {
  if (!cost) return null;
  const words = [];
  const wrap = el("span", { class: "cost", role: "img" });
  cost.split(" // ").forEach((half, i) => {
    if (i) { wrap.append(el("span", { class: "cost-sep", "aria-hidden": "true", text: "//" })); words.push("or"); }
    for (const [, symbol] of half.matchAll(/\{([^}]+)\}/g)) {
      wrap.append(symbolImg(symbol, { small, alt: "" }));
      words.push(symbolWords(symbol));
    }
  });
  wrap.setAttribute("aria-label", `Mana cost: ${words.join(", ")}`);
  return wrap;
}

/** A symbol drawn in CSS: a lettered circle ("φ" for Phyrexian), where Scryfall's picture can't load. */
function pip(symbol, small) {
  const span = el("span", { class: "pip" + (small ? " pip-small" : ""), "aria-hidden": "true" });
  const parts = symbol.toUpperCase().split("/");
  if (parts.length === 2 && parts.every((p) => COLOUR_WORDS[p])) {
    span.classList.add("pip-hybrid");
    span.style.setProperty("--pip-a", `var(--mana-${parts[0].toLowerCase()})`);
    span.style.setProperty("--pip-b", `var(--mana-${parts[1].toLowerCase()})`);
    span.textContent = parts.join("");
  } else {
    const main = parts[0];
    if ("WUBRG".includes(main) && main.length === 1) span.classList.add(`pip-${main.toLowerCase()}`);
    span.textContent = parts.length === 2 && parts[1] === "P" ? main + "φ" : symbol;
  }
  return span;
}

function symbolWords(symbol) {
  const parts = symbol.toUpperCase().split("/");
  if (/^\d+$/.test(symbol)) return `${symbol} generic`;
  if (parts.length === 2 && parts[1] === "P") return `${COLOUR_WORDS[parts[0]] || parts[0]} or 2 life`;
  if (parts.length === 2) return parts.map((p) => COLOUR_WORDS[p] || p).join(" or ");
  return COLOUR_WORDS[symbol] || symbol;
}

/** "1GG" or "1{W/U}{W/U}" (the stats' cost notation) as "{1}{G}{G}". */
function costToSymbols(text) {
  return (text || "").replace(/\{[^}]+\}|\d+|[WUBRGCXS]/g, (m) => (m.startsWith("{") ? m : `{${m}}`));
}


// --------------------------------------------------------------- card peek

// A wide screen with a mouse (deck.css .peek-layout) shows the deck page and the editor in two columns: the
// page, and on the right the card last pointed at or focused, full size. A click still opens the
// viewer. Elsewhere the peek is display: none, and its lazy image is never fetched.
const peekCards = new WeakMap();          // an element on the page -> the card it shows in the peek
const peek = { key: null, card: null, frame: null, img: null, words: null };

/** node, marked to show card in the peek when it's pointed at or focused (or something inside it is). */
function peekable(node, card) {
  if (card && card.img) peekCards.set(node, card);
  return node;
}

/** The page's parts, with the peek beside them. key names the page ("deck:<id>:<version>", the
 * editor's): drawn again, the same page keeps the card it showed; another starts on first. */
function peekLayout(key, first, parts) {
  if (key !== peek.key) {
    peek.key = key;
    peek.card = first && first.img ? first : null;
  }
  // It repeats what the viewer says, for the eye only: screen readers have the viewer.
  peek.img = el("img", { class: "peek-img", alt: "", width: 488, height: 680, loading: "lazy", decoding: "async" });
  peek.frame = el("div", { class: "peek-frame" }, peek.img);
  peek.words = el("div", { class: "peek-words" });
  const aside = el("aside", { class: "card-peek", "aria-hidden": "true" },
    el("div", { class: "peek-inner" }, peek.frame, peek.words));
  showPeek(peek.card);
  return el("div", { class: "peek-layout" }, el("div", { class: "peek-main" }, parts), aside);
}

function showPeek(card) {
  peek.card = card;
  const img = peek.img;
  if (!card) {
    img.removeAttribute("src");
    peek.frame.style.backgroundImage = "";
    add(clear(peek.words), [el("p", { class: "peek-hint", text: "Point at a card to see it here." })]);
    return;
  }
  // The last card's picture goes at once, so it's never shown with this card's name: the small
  // picture (usually loaded already) fills the frame until the big one comes.
  peek.frame.style.backgroundImage = card.img_small ? `url(${JSON.stringify(card.img_small)})` : "";
  const url = new URL(card.img, location.href).href;
  img.onload = () => { if (img.currentSrc === url) img.classList.remove("is-loading"); };
  img.classList.add("is-loading");
  img.src = card.img;
  if (img.complete && img.naturalWidth && img.currentSrc === url) img.classList.remove("is-loading");
  add(clear(peek.words), [
    el("p", { class: "peek-name" }, el("b", { text: card.name }), manaCost(card.mana_cost, true)),
    el("p", { class: "peek-type", text: card.type_line })]);
}

/** Shows the card of target, or of the peekable element it's inside, when the page has a peek. */
function peekAt(target) {
  if (!peek.img || !peek.img.isConnected) return;
  for (let node = target; node && node !== document.body; node = node.parentNode) {
    const card = peekCards.get(node);
    if (card) {
      if (!peek.card || card.img !== peek.card.img) showPeek(card);
      return;
    }
  }
}

function setUpPeek() {
  document.addEventListener("pointerover", (e) => peekAt(e.target));
  document.addEventListener("focusin", (e) => peekAt(e.target));
}

/** A card name (with its copies) that opens the card viewer when there is one. The names drawn with one
 * group (default "names") are a viewer group in page order (cards-ui.js viewerItem), so a swipe or an arrow
 * key goes from one named card to the next. inline: a link in running text (a dotted underline, not a
 * pill), drawn as a span with the button role so a long name wraps like the words around it; its viewer
 * group has each card once (openDistinct), however often the text names it. */
function cardLink(entry, group = "names", { inline = false } = {}) {
  const name = entry.name;
  // A face is named like "Fire // Ice (Fire)": look the card up without the face.
  const card = entry.card || state.cards.get(name) || state.cards.get(name.replace(/ \([^()]+\)$/, ""));
  const qty = entry.qty && entry.qty !== 1 ? el("span", { class: "x", text: `×${entry.qty}` }) : null;
  const cls = inline ? "card-link card-link-text" : "card-link";
  if (!card) return el("span", { class: cls }, name, qty);
  if (inline) {
    const open = (e) => { e.preventDefault(); openDistinct(card, e.currentTarget); };
    return peekable(viewerItem(el("span", { class: cls, role: "button", tabindex: "0", "aria-haspopup": "dialog",
      onclick: open, onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") open(e); } }, name, qty), card, group), card);
  }
  return peekable(viewerItem(el("button", { type: "button", class: cls, "aria-haspopup": "dialog",
    onclick: (e) => openCard(card, e.currentTarget) }, name, qty), card, group), card);
}

/** Open the viewer on card over node's viewer group with each card in it once (the first time it's named),
 * so a swipe through the guide's names never shows the same card twice. */
function openDistinct(card, node) {
  const group = viewerGroup(node);
  if (!group) return openCard(card, node);
  const at = new Map(), items = [];
  for (const item of group.items) {
    if (at.has(item.card.name)) continue;
    at.set(item.card.name, items.length);
    items.push(item);
  }
  return openCardViewer(items, at.get(card.name) || 0, { trigger: node });
}

function cardNames(entries) {
  if (!entries || !entries.length) return null;
  return el("ul", { class: "card-names" }, entries.map((entry) => el("li", {}, cardLink(entry))));
}


// -------------------------------------------------------- sleeves, deck box

/** The deck's sleeves and deck box (summary.kit, accessories.kit() on the server): a tile each with its
 * picture, name and how it fits ("75 needed · 100 owned · 25 spare"), and Choose…, which opens
 * accessories.js's kitPicker and so works on a phone too. A built deck can choose; a product only when it's
 * owned and kept intact, which the accessories list says (its holders_options), so a product's Choose…
 * buttons come when that answer does. An editable unbuilt deck explains when to choose its kit;
 * a pairing gets nothing. info (free text Deck Lab can't check) is a note under the tiles. */
function deckKit(data) {
  const s = data.summary, kit = s.kit;
  if (!kit || (s.space || deckSpaceOf(s.id)) !== HOME_SPACE
    || s.id.startsWith("pairing/") || !mayDo("see_accessories")) return null;
  const product = s.id.startsWith("product/");
  if (!product && s.status !== "built") {
    if (!canEditDeck(s)) return null;
    return el("section", { class: "deck-section deck-kit", "aria-labelledby": "h-kit" },
      el("h2", { id: "h-kit", text: "Sleeves and deck box" }),
      el("p", { class: "sub" }, "Choose sleeves and a deck box when you mark this deck built in the ",
        el("a", { href: `#/assembly?deck=${encodeURIComponent(s.id)}&version=${data.version}`, text: "Packing plan" }), "."));
  }
  const box = el("section", { class: "deck-section deck-kit", "aria-labelledby": "h-kit" },
    el("h2", { id: "h-kit", text: "Sleeves and deck box" }));
  const tiles = el("div");
  box.append(tiles);
  const draw = (choose) => {
    add(clear(tiles), [el("div", { class: "deck-kit-tiles" }, ["sleeves", "deck_box"].map((field) => deckKitTile(data, field, choose))),
      data.info && data.info.length ? note(...data.info) : null]);
  };
  if (!product) {
    draw(kit.editable !== false && !s.read_only && Boolean(s.holder_sha256) && canEditDeck(s));
    return box;
  }
  if (kit.editable === false || (!mayDo("products") && !mayDo("accessories"))) {
    if (!kit.sleeves && !kit.deck_box) return null;
    draw(false);
    return box;
  }
  // A product shows what it records at once; whether it can choose comes with the accessories list.
  const holder = s.id.split("/").slice(0, 2).join("/");
  if (kit.sleeves || kit.deck_box) draw(false);
  else box.hidden = true;
  api("/api/accessories").then((answer) => {
    if (box.isConnected && (answer.holders_options || []).some((o) => o.id === holder)) { box.hidden = false; draw(true); }
  }).catch(() => {});      // the tiles stay without Choose…; the Accessories page says what's wrong
  return box;
}

/** One tile of deckKit: "Sleeves" or "Deck box", the picture (96 px, 128 px on a wider screen; the name
 * beside it says what it is), the name, kitChip's words and, when choose, Choose…. */
function deckKitTile(data, field, choose) {
  const s = data.summary, kit = s.kit, ref = kit[field];
  const what = field === "sleeves" ? "Sleeves" : "Deck box";
  const name = !ref ? "None chosen" : ref.state === "linked" ? ref.label : `“${ref.value}”`;
  const holderTitle = s.id.startsWith("product/") ? kit.title || s.title : s.title;
  return el("div", { class: "deck-kit-tile" + (ref ? "" : " is-empty") },
    el("div", { class: "deck-kit-pic" }, accessoryThumb(ref || { label: what })),
    el("div", { class: "deck-kit-text" },
      el("span", { class: "deck-kit-what", text: what }),
      el("strong", { class: ref ? null : "deck-kit-none", text: name }),
      el("span", { class: "deck-kit-chip" }, kitChip(kit, field)),
      // Shared sleeves are allowed (E8-S20): said plainly, not as a warning; the picker warned when they were chosen.
      field === "sleeves" && ref && (kit.shared_with || []).length
        ? el("small", { class: "deck-kit-shared", text: `Also sleeves ${kit.shared_with.join(", ")}` }) : null,
      choose ? el("button", { type: "button", class: "btn deck-kit-choose", text: "Choose…",
        "aria-label": `Choose ${field === "sleeves" ? "sleeves" : "a deck box"} for ${holderTitle}`,
        onclick: () => kitPicker({ holder: s.id, field, need: kit.need, current: ref, holderSha: s.holder_sha256,
          title: holderTitle, onPicked: () => route() }) }) : null));
}

/** Links to a Beginner Box half's nine 40-card pairings (the halves come from /api/decks), each named
 * in full ("Cats + Vampires"). marks: a promise of a function (pairing id) -> a few words to add to its
 * link, or "" (the Matchups part's "1 result"); they're added when it comes. */
function pairingLinks(halfId, label = "Shuffle it with another half:", marks = null) {
  const list = el("ul", { class: "chips pair-links" });
  const box = el("div", { class: "pairings-of" }, el("p", { class: "sub", text: label }), list);
  // The links work without their marks: one that can't be had is left out (and isn't a page error).
  const marking = marks ? marks.catch(() => null) : null;
  const fill = (halves) => {
    const own = (halves || []).find((h) => h.id === halfId);
    const links = [];
    for (const h of halves || []) {
      if (h.id === halfId) continue;
      const id = pairingId(halfId, h.id);
      const link = el("a", { class: "card-link", href: deckHref(id), text: `${own ? own.title : "This half"} + ${h.title}` });
      links.push([id, link]);
      list.append(el("li", {}, link));
    }
    if (!list.children.length) box.remove();
    if (marking) {
      marking.then((mark) => {
        for (const [id, link] of links) {
          const words = mark ? mark(id) : "";
          if (words) link.append(el("span", { class: "pair-mark", text: words }));
        }
      });
    }
  };
  if (state.library) fill(state.library.halves);
  else api("/api/decks").then((data) => { state.library = data; fill(data.halves); }).catch(() => box.remove());
  return box;
}


// ------------------------------------------------------------------ tokens

/** A line on the Overview when the deck's tokens need a look, in the library chip's words ("No Raccoon token ·
 * Insect token differs"), a button to the Tokens part on the Cards tab. null when every token is covered (or on
 * the way), or when the deck makes no tokens Scryfall links. */
function deckTokensChip(data) {
  const t = data.tokens, counts = t && t.counts;
  if (!counts || !(counts.kinds > 0) || !(counts.none || counts.differs)) return null;
  const needs = t.needs || [];
  const named = (state) => needs.filter((n) => n.state === state);
  const words = (list, joiner) => tokenNamesWords(list.filter((n) => n.kind === "token").map((n) => n.name),
    list.filter((n) => n.kind !== "token").map((n) => n.name), joiner);
  const none = named("none"), differs = named("differs");
  const parts = [];
  if (counts.none) parts.push(none.length ? `No ${words(none, "or").text}` : `${plural(counts.none, "token")} you don't have`);
  const differ = words(differs, "and");
  if (counts.differs) parts.push(differs.length ? `${differ.text} ${differ.count > 1 ? "differ" : "differs"}`
    : `${plural(counts.differs, "token")} different`);
  return el("p", { class: "deck-tokens-chip" }, el("button", { type: "button", class: "btn btn-quiet",
    onclick: () => openDeckTab("cards", { to: "sec-tokens" }) }, status("warn", parts.join(" · "))));
}

/** The Tokens part: the tokens and reminders the list's cards make (lib/tokens deck_tokens, for the
 * version shown), each against the token cards owned, then what Scryfall's links can't say. Missing or
 * different tokens are never warnings: at home a stand-in is fine. null for a pairing (no tokens). */
function tokensSection(data) {
  const t = data.tokens;
  if (!t) return null;
  const section = el("section", { class: "deck-section token-part", id: "sec-tokens", "aria-labelledby": "h-tokens" },
    el("h2", { id: "h-tokens", text: "Tokens and reminders" }));
  const edit = el("p", { class: "deck-tokens-edit" }, el("a", { href: "#/tokens", text: "Edit your tokens" }));
  if (t.unavailable || t.error) {
    section.append(el("p", { class: "sub", text: t.unavailable || t.error }));
    return section;
  }
  const needs = t.needs || [], copies = t.copies || [], unlisted = t.unlisted || [];
  if (!needs.length) {
    section.append(el("p", { class: "sub", text: "No tokens or reminders are linked to this list's cards on Scryfall." }));
  } else {
    const faces = tokFacesUsed(needs);
    const merged = needs.map(mergedTokenCards);
    const main = merged.filter((n) => !n.sideboard_only), side = merged.filter((n) => n.sideboard_only);
    const words = tokCountWords(t.counts);
    if (words) section.append(el("p", { class: "deck-tokens-summary", text: words }));
    if (t.packed) section.append(deckPackedTokens(data, faces));
    if (main.length) section.append(tokenNeedList(main, faces));
    if (side.length) {
      section.append(el("h3", { class: "deck-tokens-group", text: "Only for sideboard cards" }), tokenNeedList(side, faces));
    }
  }
  if (copies.length) {
    section.append(el("details", { class: "more deck-tokens-more" }, el("summary", { text: `Makes copies: ${plural(copies.length, "card")}` }),
      el("p", { text: `${copies.join(", ")}. Use a Copy token card, or any spare token, and say what it copies.` })));
  }
  if (unlisted.length) {
    section.append(el("details", { class: "more deck-tokens-more" },
      el("summary", { text: `May also make things Scryfall doesn't link: ${plural(unlisted.length, "card")}` }),
      el("p", { text: `${unlisted.join(", ")}. Their text mentions a token or reminder that isn't listed above.` })));
  }
  if (t.note) section.append(el("details", { class: "more token-note" }, el("summary", { text: "How are these worked out?" }),
    el("p", { class: "sub", text: t.note })));
  section.append(edit);
  return section;
}

/** A built deck's packed token cards (its text's Token cards line, lib/api/deck_page.py _packed): what its
 * deck box holds, which the other decks count as in use, with "Change…" for whoever may change the deck.
 * faces (tokFacesUsed of the deck's needs) says of each double-sided card whether the deck needs both
 * sides or only one, which can be sleeved. */
function deckPackedTokens(data, faces = null) {
  const p = data.tokens.packed;
  const lines = p.lines || [];
  const sides = (line) => [...new Set(line.rows.map((row) => tokSides(row, faces)).filter(Boolean))];
  const label = (line) => !line.rows.length ? `${line.text} (no token card matches)`
    : sides(line).length ? `${line.text} (${sides(line).join("; ")})` : line.text;
  const words = p.error ? `The Token cards line can't be read: ${p.error}`
    : lines.length ? `Packed: ${lines.map(label).join("; ")}`
    : p.written ? "Packed: no token cards." : "Packed token cards aren't recorded yet.";
  const may = canEditDeck(data.summary) && (p.choices || []).length && !p.error;
  return el("div", { class: "deck-tokens-packed" },
    el("p", { class: p.error ? "box box-warn" : "sub", text: words }),
    may ? el("button", { type: "button", class: "btn btn-quiet", text: "Change packed token cards…",
      onclick: () => openPackedTokens(data) }) : null);
}

/** The sheet choosing a built deck's packed token cards: a count per token card it could use (at most what
 * other decks leave of it), saved as one change (POST /api/deck/token-cards). */
function openPackedTokens(data) {
  const p = data.tokens.packed, s = data.summary;
  const sheet = openSheet({ title: "Packed token cards" });
  const inputs = [];
  sheet.body.append(el("p", { class: "sub", text: "The token cards in this deck's box. Other decks count them as in use." }),
    el("ul", { class: "pack-plain deck-packed-choices" }, (p.choices || []).map((c) => {
      const id = `packed-${sheet.heading.id}-${c.row}`;
      const input = el("input", { id, type: "number", inputmode: "numeric", min: 0, max: c.free, step: 1,
        value: String(Math.min(c.packed, c.free)) });
      inputs.push([c, input]);
      const name = `${c.back ? `${c.front} / ${c.back}` : c.front}${c.set ? ` (${c.set.toUpperCase()} ${c.number})` : ""}`;
      const rest = c.free < c.quantity ? `, ${num(c.quantity - c.free)} in other decks` : "";
      return el("li", {}, el("label", { for: id, text: `${name}: ${plural(c.quantity, "card")}${rest}` }), " ", input);
    })));
  const message = el("p", { class: "box box-crit", hidden: true });
  sheet.body.append(message);
  const save = () => {
    const cards = [];
    for (const [c, input] of inputs) {
      const n = Number(input.value);
      if (!Number.isInteger(n) || n < 0 || n > c.free) {
        message.textContent = `Choose 0 to ${c.free} for ${c.front}.`;
        message.hidden = false;
        input.focus();
        return;
      }
      if (n) cards.push({ row: c.row, quantity: n });
    }
    apiWrite("/api/deck/token-cards", { id: s.id, expect: p.expect, tokens_sha256: p.tokens_sha256, cards })
      .then(() => {
        sheet.close();
        toast("Packed token cards saved");
        const here = parseHash();
        if (here.path === "deck" && addressDeckId(here.params.get("id") || "") === s.id) route();
      })
      .catch((e) => {
        if (!(e instanceof ApiError)) throw e;
        message.textContent = e.message;
        message.hidden = false;
      });
  };
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() },
    { text: "Save", kind: "primary", value: "save", onclick: save }]);
  return sheet;
}

/** A token need with its token cards to grab that read the same ("Dog / Beast ×1, Dog side", for two rows
 * whose printings aren't recorded) as one line with their copies added up. */
function mergedTokenCards(need) {
  const cards = need.cards || [];
  if (cards.length < 2) return need;
  const byWords = new Map();
  for (const card of cards) {
    const key = JSON.stringify([card.front, card.back || "", card.side || "", card.verdict || "", card.why || [],
      card.also_for || [], (card.shared || []).map((h) => h.deck || h.title)]);
    const same = byWords.get(key);
    if (same) same.quantity = (Number(same.quantity) || 0) + (Number(card.quantity) || 0);
    else byWords.set(key, { ...card });
  }
  return byWords.size === cards.length ? need : { ...need, cards: [...byWords.values()] };
}
