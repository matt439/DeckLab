/* Deck Lab's page: the deck library (#/library), a shelf of decks (decklab/UI-REVIEW.md WP8). Each deck is a
tile: its cover card's art (GET /api/decks "cover": the commander or the most-copied card, or the one its
Cover card line names; cover.js lets an editor choose it), its colours (ui.js deckColourPieces: a stripe
across the top and pips by the title), a status pill, one meta line, one readiness chip in plain words (only
when there's something to say), and its token state on its own line.
The whole tile is the link: to the deck's cards, filtered to what's missing when it's missing cards.
P1 (design/visual-design.md 4.1-4.6, E11-S30 slice 8): under 1000 px the tiles are casual (the art at the side
with the pips over it, the rest on the deck's tint, a status pill only for Building and Idea, the owned bar with
words; two across from 600 px). From 1000 px (LIB_LAB_QUERY) the lab: each deck a 54 px row under Built, Building
and Ideas headings in a list pane, and the selected deck's overview in a detail pane beside it (libDetail). A
click selects a row (kept in the address as ?deck=), Enter or Open deck opens it, and J and K move the
selection. Products stay tiles in both.

Decks are grouped by whose they are: the home decks first, then each person's (their own space, lib/spaces.py),
by name, in a part that folds away; within each, Commander then 60-card (kind "casual"). Products (sealed decks, read only)
come last, folded until opened (remembered on this device). The filters (whose decks, format, status,
colour identity, archetype, availability) and the sort (Ready first, Recently changed, Name) are kept in the address; on a phone they're
behind a "Filter" sheet. Title search stays in sight, with its query in the address too. "Mine" is the
decks Played by the visitor at home, or a person's own decks.

Loaded after core.js, whose helpers (el, load, state, deckHref, pairingId, warningsBox, ...) it uses, and
library-glance.js (the detail pane's key cards, stats and play guide, libGlance), library-tables.js (the Tables out
of date list, libTablesPanel) and cover.js (openCoverPicker) after it. app.js's route() calls showLibrary(), and its deckPlayerWords() names who
plays each deck. Nothing here runs at load.
*/
"use strict";

const LIB_SORTS = { ready: "Ready first", recent: "Recently changed", name: "Name" };
// The deck kinds' groups, in the order they show (decided 2026-10-27: Commander first).
const LIB_KIND_ORDER = ["commander", "casual"];
// The availability filter's words are the tiles' chips' words: "3 on the way", "8 to get", "Availability
// needs checking"; a deck with every card here has no chip (it's the usual case, and Ready first puts it first).
const LIB_READINESS = { ready: "All cards here", waiting: "Cards on the way", missing: "Cards to get",
  unknown: "Availability needs checking" };
const LIB_PRODUCTS_KEY = "library.products.open";      // "1" when the products part is open (folded by default)
const LIB_LAB_QUERY = "(min-width: 1000px)";           // the lab: rows and the detail pane beside them
const LIB_STATUS_GROUPS = [["built", "Built"], ["building", "Building"], ["idea", "Ideas"]];
let libTitleSearchOwner = null;                    // the exact retained input of the current library draw

/** True at lab width (LIB_LAB_QUERY). */
function libIsLab() {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia(LIB_LAB_QUERY).matches;
}

function libraryFilters(params) {
  const format = params.get("format");
  const status = params.get("status");
  const sort = params.get("sort");
  return {
    all: params.get("all") === "1",
    format: FORMAT_WORDS[format] ? format : "",
    status: STATUS_WORDS[status] ? status : "",
    color: libColourChoice(params.get("color")),
    archetype: libArchetypeQuery(params.get("archetype")),
    ...libBoxFilterParams(params),
    readiness: LIB_READINESS[params.get("readiness")] ? params.get("readiness") : "",
    sort: LIB_SORTS[sort] ? sort : "ready",
    deck: params.get("deck") || "",            // the lab's selected deck
    q: (params.get("q") || "").trim(),        // title text only, never a card/deck-id query
    tables: params.get("tables") === "1",      // scroll to the Tables out of date list (not kept in the address)
  };
}

function filtersHash(filters) {
  const params = new URLSearchParams();
  if (filters.all) params.set("all", "1");
  if (filters.format) params.set("format", filters.format);
  if (filters.status) params.set("status", filters.status);
  const color = libColourChoice(filters.color), archetype = libArchetypeQuery(filters.archetype);
  if (color) params.set("color", color);
  if (archetype) params.set("archetype", archetype);
  libBoxFilterHash(params, filters);
  if (filters.readiness) params.set("readiness", filters.readiness);
  if (filters.sort && filters.sort !== "ready") params.set("sort", filters.sort);
  if (filters.deck) params.set("deck", filters.deck);
  if (filters.q?.trim()) params.set("q", filters.q.trim());
  const query = params.toString();
  return "#/library" + (query ? "?" + query : "");
}

/** How many select filters are set: the phone's "Filter (n)" (title and sort stay independent). */
function libFilterCount(filters) {
  return ["format", "status", "color", "archetype", "readiness"].filter((key) => filters[key]).length + (libBoxMode(filters.box_check) ? 1 : 0);
}

/** A bookmarked identity choice: includes every chosen colour, or explicitly colourless/unknown. */
function libColourChoice(value) {
  if (value === "C" || value === "unknown") return value;
  return typeof value === "string" && /^[WUBRG]{1,5}$/.test(value) && new Set(value).size === value.length
    ? [..."WUBRG"].filter(color => value.includes(color)).join("") : "";
}

function libMatchesColour(deck, value) {
  const choice = libColourChoice(value);
  if (!choice) return true;
  const colors = deck.colors;
  const known = !deck.error && Array.isArray(colors) && colors.length <= 5 && new Set(colors).size === colors.length
    && Array.from(colors).every(color => typeof color === "string" && /^[WUBRG]$/.test(color));
  if (choice === "unknown") return !known;
  if (!known) return false;
  return choice === "C" ? colors.length === 0 : [...choice].every(color => colors.includes(color));
}

/** Archetypes are literal header strings, not a taxonomy or card-name/regular-expression query. */
function libArchetypeQuery(value) {
  return typeof value === "string" ? value.normalize("NFKC").trim().replace(/\s+/g, " ").toLowerCase() : "";
}

function libMatchesMetadata(deck, filters) {
  const archetype = libArchetypeQuery(filters.archetype);
  return libMatchesTitle(deck, filters) && libMatchesColour(deck, filters.color)
    && (!archetype || libArchetypeQuery(deck.archetype) === archetype) && libMatchesBoxCheck(deck, filters);
}

function libColourChoices() {
  const choices = [["", "Any colour identity"]];
  // Single colours first, then pairs, triples, four and five; WUBRG within each choice.
  for (let size = 1; size <= 5; size++) {
    for (let mask = 1; mask < 32; mask++) {
      const colors = [..."WUBRG"].filter((_, index) => mask & (1 << index));
      if (colors.length === size) choices.push([colors.join(""), `Includes ${colors.map(color => COLOUR_WORDS[color]).join(" + ")}`]);
    }
  }
  return [...choices, ["C", "Colourless"], ["unknown", "Colour identity unknown"]];
}

function libArchetypeChoices(data, value) {
  const choices = new Map();
  for (const deck of data?.decks || []) {
    const key = libArchetypeQuery(deck.archetype);
    if (key && !choices.has(key)) choices.set(key, deck.archetype.normalize("NFKC").trim().replace(/\s+/g, " "));
  }
  // Keep an unmatched bookmark visible in the native select, so it can be cleared normally.
  if (value && !choices.has(value)) choices.set(value, value);
  return [["", "Any archetype"], ...[...choices].sort((a, b) => a[1].localeCompare(b[1]))];
}

/** Keep raw typing in the input; only matching ignores outside spaces, case and compatibility forms. */
function libTitleQuery(value) { return (value || "").trim().normalize("NFKC").toLowerCase(); }

function libMatchesTitle(deck, filters) {
  const query = libTitleQuery(filters.q);
  return !query || (deck.title || "").normalize("NFKC").toLowerCase().includes(query);
}

function showLibrary(params, token) {
  load("/api/decks", token, (data) => {
    state.library = data;
    drawLibrary(data, libraryFilters(params));
  });
}

/** A labelled select for the filter row (its words hidden: each option says what it is) or, with shown,
 * for the phone's sheet. */
function libSelect(id, label, entries, value, onchange, shown = false) {
  const select = el("select", { id, onchange: (e) => onchange(e.target.value) },
    entries.map(([v, text]) => el("option", { value: v, text })));
  select.value = value || "";
  return el("label", { class: shown ? "field" : "lib-select", for: id },
    el("span", { class: shown ? null : "sr-only", text: label }), select);
}

/** The filter and sort choices: [key, label, entries]. shown: for the sheet, whose fields show their labels
 * (the row's selects hide theirs, so its sort options say "Sort: ..."). */
function libChoices(shown = false, data = null, filters = {}) {
  return [
    ["format", "Format", [["", "All formats"], ...Object.entries(FORMAT_WORDS)]],
    ["status", "Status", [["", "Any status"], ...Object.entries(STATUS_WORDS)]],
    ["color", "Colour identity", libColourChoices()],
    ["archetype", "Archetype", libArchetypeChoices(data, filters.archetype)],
    ["readiness", `${listName("target")} availability`, [["", "Any availability"], ...Object.entries(LIB_READINESS)]],
    ...libBoxCheckChoices(),
    ["sort", "Sort", Object.entries(LIB_SORTS).map(([v, text]) => [v, shown ? text : `Sort: ${text}`])],
  ];
}

function drawLibrary(data, filters) {
  const main = $("#main");
  const results = el("div", { class: "results", id: "library-results" });
  state.libraryHash = location.hash || "#/library";     // where a deck's "← Decks" comes back to
  const view = { picking: false };
  const keyboardToken = routeToken, keyboardProfile = state.profile?.id;
  // Drawing the decks again: refresh() as they are (a cover chosen; nothing once the library has been left,
  // say by an Undo pressed on another page: false then), redraw() after the filters changed, which also keeps
  // them in the address.
  const refresh = () => {
    if (!results.isConnected) return false;
    drawLibraryResults(results, data, filters, view, refresh);
    registerLibraryKeyboardHelp(results, keyboardToken, keyboardProfile);
    return true;
  };
  const syncAddress = () => {
    // A phone sheet has a temporary history entry. Keep its underlying page address unchanged until Back lands.
    if (view.filterSheet) return;
    history.replaceState(history.state, "", filtersHash(filters));
    state.libraryHash = location.hash;
  };
  const redraw = () => {
    if (!results.isConnected) return;
    syncAddress();
    refresh();
    syncControls();
  };
  // The lab's selection: kept in the address, so "← Decks" comes back to it; the rows and the detail pane follow.
  view.select = (id, focus = false) => {
    if (!results.isConnected || filters.deck === id) return;
    filters.deck = id;
    syncAddress();
    refresh();
    if (focus) {
      const row = Array.from(results.querySelectorAll(".deck-row")).find((r) => r.getAttribute("data-id") === id);
      if (row) row.focus();
    }
  };
  libWatchDensity(results, refresh);
  libKeys(results, view);
  libLoadForge(data, refresh);
  const set = (key, value) => {
    if (!view.current?.()) return;
    if (key === "box_check" && value !== "before") filters.checked_before = "";
    filters[key] = value; redraw();
  };
  const setMany = (values) => { if (!view.current?.()) return; Object.assign(filters, values); redraw(); };
  const who = state.profile;
  const mine = el("button", { type: "button", text: `${who.name}'s decks`,
    onclick: () => set("all", false) });
  const all = el("button", { type: "button", text: "All decks", onclick: () => set("all", true) });
  const choices = libChoices(false, data, filters);
  const selects = choices.map(([key, label, entries]) =>
    libSelect(`filter-${key}`, label, entries, filters[key], (value) => set(key, value)));
  const boxCutoff = libBoxCutoff("filter-checked-before", filters, set, false, () => view.current?.());
  const filterButton = el("button", { type: "button", class: "btn lib-filter-button", "aria-haspopup": "dialog",
    onclick: () => { if (view.current?.()) libOpenFilterSheet(view, data, filters, set, setMany, syncAddress); } });
  let composing = false;
  const titleInput = el("input", { type: "search", id: "library-title-search", value: filters.q || "",
    autocomplete: "off", spellcheck: "false", "aria-controls": "library-results",
    "aria-describedby": "library-title-hint", oninput: event => {
      if (!composing && !event.isComposing) searchTitles();
    }, onsearch: () => { if (!composing) searchTitles(); },
    oncompositionstart: () => { composing = true; }, oncompositionend: () => { composing = false; searchTitles(); } });
  const clearTitle = el("button", { type: "button", class: "btn btn-quiet lib-title-clear", text: "Clear",
    "aria-label": "Clear title search", onclick: () => {
      if (!searchCurrent()) return;
      titleInput.value = ""; composing = false; searchTitles(); titleInput.focus({ preventScroll: true });
    } });
  const titleSearch = el("div", { class: "lib-title-search", role: "search", "aria-label": "Search deck titles" },
    el("label", { class: "field lib-title-field", for: "library-title-search" },
      el("span", { text: "Find a deck by title" }), titleInput), clearTitle,
    el("span", { class: "sr-only", id: "library-title-hint", text: "Search titles in this library. Other filters still apply." }));
  const searchOwner = libTitleSearchOwner = { input: titleInput, root: titleSearch, results };
  const searchCurrent = () => libTitleSearchOwner === searchOwner && results.isConnected && titleInput.isConnected && main.contains(titleSearch)
    && titleSearch.contains(titleInput) && keyboardToken === routeToken && keyboardProfile === state.profile?.id && parseHash().path === "library";
  view.current = searchCurrent;
  function searchTitles() {
    if (!searchCurrent() || filters.q === titleInput.value) return;
    filters.q = titleInput.value; // Never trim or rewrite the live input: a space may start the next word.
    redraw();
  }
  function syncControls() {
    mine.setAttribute("aria-pressed", String(!filters.all));
    all.setAttribute("aria-pressed", String(filters.all));
    for (const [key] of choices) {
      const select = main.querySelector(`#filter-${key}`);
      if (select) select.value = filters[key] || "";
    }
    const n = libFilterCount(filters);
    boxCutoff.sync();
    filterButton.textContent = n ? `Filter (${n})` : "Filter";
    clearTitle.hidden = !titleInput.value;
  }

  // Choosing deck pictures: a mode where a tap on a deck you may change opens its picture picker.
  const pickable = data.decks.some(libCoverEditable);
  const picking = el("div", { class: "box box-info lib-picking", role: "status", hidden: true },
    el("p", { text: "Choose a deck to change its picture." }),
    el("div", { class: "actions" }, el("button", { type: "button", class: "btn btn-primary", text: "Done",
      onclick: () => { view.picking = false; picking.hidden = true; refresh(); } })));
  const more = pickable ? [{ label: "Choose deck pictures", onclick: () => {
    view.picking = true; picking.hidden = false; refresh();
    const first = results.querySelector(".lib-pick");
    if (first) first.focus();
  } }] : [];
  // Compare two decks (compare.js, E1-S13): choose the two from the decks shown here.
  if (data.decks.filter((d) => !d.error).length > 1) more.push({ label: "Compare two decks…", onclick: () => openCompareFirst(data.decks) });
  // New deck is the page's one primary action for whoever may make a deck (on a phone it opens in the Quick
  // edit); without it, More ("⋯") sits at the end of the filter row instead of on a row of its own under the title.
  const primary = createTargets().length
    ? el("a", { class: "btn btn-primary", href: newDeckHref(), text: "New deck" }) : null;
  const rowMore = !primary && more.length
    ? el("div", { class: "lib-more" }, menuButton("⋯", more, { aria: "More" })) : null;

  // The decks whose owned-vs-needed tables are out of date (library-tables.js), filled after the shelf.
  // Asked for in the address (?tables=1), it's scrolled to once; the address then drops the ask.
  const tables = libTablesPanel(filters.tables ? () => {
    filters.tables = false;
    if (!results.isConnected) return;
    syncAddress();
  } : null, () => libReloadShelf(data, refresh));

  // The warnings go first: they say when the missing-card counts can't be trusted.
  add(main, [
    ...pageHead({ title: routeH1("library"), description: "Tap a deck for its cards, play guide and stats.",
      primary, more: rowMore ? [] : more }),
    warningsBox(data.warnings, "Warnings"),
    tables,
    titleSearch,
    el("div", { class: "lib-filters", role: "group", "aria-label": "Filter the decks" },
      el("div", { class: "segmented", role: "group", "aria-label": "Whose decks" }, mine, all),
      el("div", { class: "lib-selects" }, selects, boxCutoff.node),
      el("div", { class: "lib-row-end" + (rowMore ? " has-more" : "") }, filterButton, rowMore)),
    picking,
    results]);
  syncControls();
  drawLibraryResults(results, data, filters, view, refresh);
  registerLibraryKeyboardHelp(results, keyboardToken, keyboardProfile);
}

/** The phone's filter sheet: the same choices with their words, applied as they change. The fields stay put
 * (the focus stays on the one just changed); only the buttons follow the count. */
function libFilterSheet(data, filters, set, setMany, onClose = null, current = () => true) {
  const sheet = openSheet({ title: "Filter decks", onClose });
  const count = () => libVisibleDecks(data, filters).length + libVisibleProducts(data, filters).length;
  const choices = libChoices(true, data, filters);
  const fields = choices.map(([key, label, entries]) =>
    libSelect(`sheet-filter-${key}`, label, entries, filters[key], (value) => { set(key, value); draw(); }, true));
  const cutoff = libBoxCutoff("sheet-filter-checked-before", filters, (key, value) => { set(key, value); draw(); }, true,
    () => !sheet.closed && current());
  const guidance = el("p", { class: "sub lib-box-check-guidance", role: "status" });
  const body = el("div", { class: "lib-sheet-fields" }, fields, cutoff.node, guidance);
  function draw() {
    for (const [key] of choices) {
      const select = body.querySelector(`#sheet-filter-${key}`);
      if (select && select.value !== (filters[key] || "")) select.value = filters[key] || "";
    }
    cutoff.sync();
    const issue = libBoxCheckIssue(data, filters); guidance.textContent = issue.text; guidance.hidden = !issue.text;
    sheetActions(sheet, [
      libFilterCount(filters) ? { text: "Clear filters", onclick: () => {
        setMany({ format: "", status: "", color: "", archetype: "", readiness: "", box_check: "", checked_before: "" });
        draw();
        const first = body.querySelector("select");
        if (first) first.focus();
      } } : null,
      { text: issue.blocking ? "Close filters" : `Show ${plural(count(), "deck")}`, kind: "primary", onclick: () => sheet.close() }]);
  }
  sheet.body.append(body);
  draw();
  return sheet;
}

/** Commit a filter sheet's live changes only after its temporary history entry has closed. */
function libOpenFilterSheet(view, data, filters, set, setMany, syncAddress) {
  if (view.filterSheet || !view.current?.()) return null;
  const owner = view.filterSheet = { hash: location.hash, sheet: null };
  const current = () => view.filterSheet === owner && view.current?.() && location.hash === owner.hash;
  const release = () => {
    window.removeEventListener("popstate", landed);
    window.removeEventListener("hashchange", abandoned);
    if (view.filterSheet === owner) view.filterSheet = null;
  };
  const abandoned = () => release();
  const landed = () => {
    const entry = owner.sheet?.entry;
    const valid = current() && (!entry || history.state?.sheet !== entry.token
      && history.state?.pos === entry.pos - 1);
    release();
    if (valid) syncAddress();
  };
  const closed = () => {
    if (!current()) { release(); return; }
    const entry = owner.sheet?.entry;
    // No-history environments and already-landed native Back need no deferred listener.
    if (!entry || entry.fromHistory || history.state?.sheet !== entry.token) { landed(); return; }
    // Explicit Close/Show waits for releaseSheetEntry's Back, rather than rewriting the departing entry.
    window.addEventListener("popstate", landed);
    window.addEventListener("hashchange", abandoned);
  };
  owner.sheet = libFilterSheet(data, filters, set, setMany, closed, current);
  return owner.sheet;
}

/** Whether a deck is the visitor's: in their own space for a person; at home, Played by them or by either. */
function isMyDeck(d) {
  const who = state.profile;
  const space = d.space || deckSpaceOf(d.id);
  if (ownSpace() !== HOME_SPACE) return space === ownSpace();
  return space === HOME_SPACE && (d.player === "either" || (Boolean(who.plays_as) && d.player === who.plays_as));
}

/** "#/new", with the space when the visitor adds decks somewhere other than home (their own space first). */
function newDeckHref() {
  const targets = createTargets();
  const own = targets.find((t) => t.space === ownSpace());
  const space = own ? own.space : targets.length ? targets[0].space : HOME_SPACE;
  return space === HOME_SPACE ? "#/new" : `#/new?space=${encodeURIComponent(space)}`;
}

/** True for a deck whose picture the visitor may choose: a deck text (not a product or pairing) they may change. */
function libCoverEditable(d) {
  return !d.id.startsWith("product/") && !d.id.startsWith("pairing/") && !d.error && canEditDeck(d);
}

/** The deck files (not products) the filters show. */
function libVisibleDecks(data, filters) {
  return data.decks.filter((d) => !d.id.startsWith("product/") && (filters.all || isMyDeck(d))
    && (!filters.status || d.status === filters.status)
    && (!filters.format || d.kind === filters.format) && matchesReadiness(d, filters.readiness) && libMatchesMetadata(d, filters));
}

/** Products have no player or status; search never broadens those existing visibility choices. */
function libVisibleProducts(data, filters) {
  if (filters.status || filters.format && filters.format !== "product"
      || ownSpace() !== HOME_SPACE && !filters.all && filters.format !== "product") return [];
  return data.decks.filter(d => d.id.startsWith("product/") && matchesReadiness(d, filters.readiness)
    && libMatchesMetadata(d, filters));
}


// ----------------------------------------------------------------- readiness

/** A version's counts from /api/decks: {missing, waiting, known}. */
function libCounts(d, version) {
  const missing = d.missing ? d.missing[version] : null;
  const waiting = d.on_the_way ? d.on_the_way[version] : null;
  const known = !d.error && missing != null && waiting != null && d.availability_confirmed?.[version] !== false;
  return { missing: missing || 0, waiting: waiting || 0, known };
}

/** What a tile says about being able to play the deck: {rank (for Ready first: 0 built, 1 every card here,
 * 2 waiting for a delivery, 3 missing cards, 4 not known), chip (one status chip in plain words, or null when
 * there's nothing worth saying), missing (Planned list cards missing, for the tile's link)}. Nothing for a
 * visitor who may not see the deck's space's collection ("missing" left out of /api/decks). */
function deckReadiness(d) {
  const built = d.status === "built";
  if (!("missing" in d) || d.error) return { rank: built ? 0 : 4, chip: null, missing: 0 };
  const target = libCounts(d, "target");
  if (built) {
    const version = d.built_version === "owned" && (d.versions || []).includes("owned") ? "owned" : "target";
    const held = libCounts(d, version);
    let chip = null;
    if (!held.known) chip = status("plain", "Availability needs checking");
    else if (held.missing) chip = status("warn", `${num(held.missing)} to get`);
    else if (version === "owned" && target.known && target.missing) {
      chip = status("plain", `${listName("target")}: ${num(target.missing)} to get`);
    }
    return { rank: 0, chip, missing: target.known ? target.missing : 0 };
  }
  if (!target.known) return { rank: 4, chip: status("plain", "Availability needs checking"), missing: 0 };
  // Every card here is the usual case: no chip (chips are for exceptions; Ready first puts these first).
  if (!target.missing && !target.waiting) return { rank: 1, chip: null, missing: 0 };
  if (!target.missing) {
    return { rank: 2, chip: status("info", `${num(target.waiting)} on the way`), missing: 0 };
  }
  const parts = [`${num(target.missing)} to get`];
  if (target.waiting) parts.push(`${num(target.waiting)} on the way`);
  if ((d.versions || []).includes("owned")) {
    const owned = libCounts(d, "owned");
    if (owned.known && !owned.missing) {
      parts.push(owned.waiting ? `${listName("owned", true)} once ${num(owned.waiting)} arrive`
        : `${listName("owned", true)} ready`);
    }
  }
  return { rank: 3, chip: status("warn", parts.join(" · ")), missing: target.missing };
}

/** An "edited" time as a number to compare (newest biggest); never edited (or unreadable) is oldest. */
function libTime(at) {
  const t = at ? Date.parse(at) : NaN;
  return Number.isFinite(t) ? t : -Infinity;
}

/** decks sorted by the library's sort: Ready first (built, then ready, waiting, fewest missing, unknown),
 * Recently changed (newest edit first, never-edited last) or Name; by title within a tie. */
function sortDecks(decks, sort) {
  const title = (a, b) => (a.title || a.id).localeCompare(b.title || b.id);
  const keyed = decks.map((d) => ({ d, r: deckReadiness(d) }));
  keyed.sort((a, b) => {
    if (sort === "ready") {
      return a.r.rank - b.r.rank || (a.r.rank === 3 ? a.r.missing - b.r.missing : 0) || title(a.d, b.d);
    }
    if (sort === "recent") {
      const ea = libTime(a.d.edited), eb = libTime(b.d.edited);
      return (ea === eb ? 0 : ea < eb ? 1 : -1) || title(a.d, b.d);
    }
    return title(a.d, b.d);
  });
  return keyed.map((k) => k.d);
}


// ------------------------------------------------------------------ groups

/** The Commander and 60-card (kind "casual") groups of some decks, Commander first, under headings of level tag
 * ("h2" or "h3"): tiles, or in the lab rows under Built, Building and Ideas (statusRows). */
function kindGroups(decks, tag, ctx) {
  const groups = [];
  for (const kind of LIB_KIND_ORDER) {
    const group = decks.filter((d) => d.kind === kind);
    if (!group.length) continue;
    const title = kind === "casual" ? "60-card decks" : "Commander decks";
    groups.push(el("section", { class: "deck-group", "aria-label": title },
      el(tag, {}, title, el("span", { class: "count", text: `(${group.length})` })),
      ctx.lab ? statusRows(group, ctx)
        : el("ul", { class: "deck-grid" }, sortDecks(group, ctx.sort).map((d) => el("li", {}, deckCard(d, null, false, false, ctx))))));
  }
  return groups;
}

/** The lab's rows of some decks under Built, Building and Ideas headings (4.2): the heading says the status, so
 * the rows have no pill. A deck with no status (it can't be read) comes last, under no heading. */
function statusRows(decks, ctx) {
  const known = new Set(LIB_STATUS_GROUPS.map(([status]) => status));
  const parts = [...LIB_STATUS_GROUPS.map(([status, words]) => [status, words, decks.filter((d) => d.status === status)]),
    [null, null, decks.filter((d) => !known.has(d.status))]];
  return parts.filter(([, , group]) => group.length).map(([status, words, group]) => el("div", { class: "deck-rows-group" },
    words ? el("p", { class: `lib-status-head lib-status-${status}` }, words,
      el("span", { class: "lib-status-count", text: String(group.length) })) : null,
    el("ul", { class: "deck-rows", "aria-label": words || "Other decks" },
      sortDecks(group, ctx.sort).map((d) => el("li", {}, deckRow(d, ctx))))));
}

/** A person's decks: a part that folds away (remembered on this device), named for them. */
function personGroup(space, decks, ctx) {
  const key = `library.folded.${space}`;
  const part = el("details", { class: "space-group space-person", "data-space": space,
    open: ctx.searching || local.get(key) !== "1",
    ontoggle: () => { if (!ctx.searching) local.set(key, part.open ? "0" : "1"); } },
    el("summary", {}, el("h2", {}, `${spaceName(space)}'s decks`, el("span", { class: "count", text: `(${decks.length})` }))),
    kindGroups(decks, "h3", { ...ctx, person: true }));
  return part;
}

/** The products part: folded until opened (remembered), open when the filter asks for products. */
function productsGroup(data, products, ctx, forced) {
  const caption = ownSpace() === HOME_SPACE
    ? "The decks in your sealed products, as printed. They're read only."
    : "The decks in the home collection's sealed products, as printed. They're read only.";
  const part = el("details", { class: "space-group lib-products", "aria-label": "Products",
    open: forced || local.get(LIB_PRODUCTS_KEY) === "1",
    ontoggle: () => { if (!forced) local.set(LIB_PRODUCTS_KEY, part.open ? "1" : "0"); } },
    el("summary", {}, el("h2", {}, "Products", el("span", { class: "count", text: `(${products.length})` }))),
    el("p", { class: "lib-caption", text: caption }));
  // One group per product ("Foundations Commander" has a file per precon).
  const byProduct = new Map();
  for (const d of products) {
    const key = productName(d.title) || d.source;
    if (!byProduct.has(key)) byProduct.set(key, []);
    byProduct.get(key).push(d);
  }
  for (const decks of byProduct.values()) {
    const name = productName(decks[0].title);
    const isBox = decks[0].id.startsWith(BOX_PREFIX);
    // A product kept intact has one kit for all its decks: shown once, under its name, when the group
    // is one product file (a group of several files shows each deck's own).
    const oneFile = new Set(decks.map((d) => productHolder(d.id))).size === 1;
    part.append(el("div", { class: "product-group" },
      el("h3", { text: name || decks[0].title }),
      oneFile ? deckSleeve(decks[0].kit, "deck-sleeve product-sleeve") : null,
      isBox && data.halves && data.halves.length > 1 ? pairingPicker(data.halves) : null,
      el("ul", { class: "deck-grid" + (isBox ? " compact" : "") },
        sortDecks(decks, ctx.sort).map((d) => el("li", {}, deckCard(d, name, isBox, oneFile, ctx))))));
  }
  return part;
}

function drawLibraryResults(target, data, filters, view = {}, redraw = null) {
  clear(target);
  const lab = libIsLab();
  // The lab's selection: the address's deck while it's shown, else the first deck shown.
  const sorted = lab ? libRowOrder(libVisibleDecks(data, filters), filters.sort || "ready") : [];
  const selected = sorted.find((d) => d.id === filters.deck) || sorted[0] || null;
  const ctx = { sort: filters.sort || "ready", picking: Boolean(view.picking), redraw, lab,
    selected: selected ? selected.id : null, select: view.select || (() => {}),
    searching: !!(libTitleQuery(filters.q) || filters.color || filters.archetype || libBoxMode(filters.box_check)) };
  const results = el("div", { class: "lib-list" });
  target.append(lab && selected ? el("div", { class: "lib-split" }, results, libDetail(selected, ctx)) : results);
  const files = data.decks.filter((d) => !d.id.startsWith("product/"));
  const products = libVisibleProducts(data, filters);
  const shown = libVisibleDecks(data, filters);
  const hiddenOthers = filters.all ? 0 : files.filter((d) => !isMyDeck(d)
    && (!filters.status || d.status === filters.status)
    && (!filters.format || d.kind === filters.format) && matchesReadiness(d, filters.readiness) && libMatchesMetadata(d, filters)).length;
  // Products belong to nobody (they're read-only card lists) and have no status. A person sees the home's
  // only among all decks or when asking for products: they aren't theirs.
  const showProducts = products.length > 0;

  const counts = shown.length ? [plural(shown.length, "deck")] : [];
  const checkIssue = libBoxCheckIssue(data, filters);
  if (checkIssue.text) results.append(el("p", { class: "box box-info lib-box-check-guidance", role: "status", text: checkIssue.text }));
  if (showProducts) counts.push(plural(products.length, "product deck"));
  const othersWords = ownSpace() === HOME_SPACE ? "played only by someone else" : "of other people";
  if (counts.length || hiddenOthers) {
    results.append(el("p", { class: "result-count", role: "status" },
      counts.length ? `Showing ${counts.join(" and ")}.` : "",
      hiddenOthers ? `${counts.length ? " " : ""}${plural(hiddenOthers, "deck")} ${othersWords} ${hiddenOthers === 1 ? "is" : "are"} hidden.` : ""));
  }

  // Home first, then each person's decks by name. With only home decks shown, no extra heading.
  const bySpace = new Map();
  for (const d of shown) {
    const space = d.space || deckSpaceOf(d.id);
    if (!bySpace.has(space)) bySpace.set(space, []);
    bySpace.get(space).push(d);
  }
  const home = bySpace.get(HOME_SPACE) || [];
  const people = [...bySpace.keys()].filter((s) => s !== HOME_SPACE)
    .sort((a, b) => spaceName(a).localeCompare(spaceName(b)));
  if (!people.length || (people.length === 1 && !home.length)) {
    // One part only (home's decks, or one person's own): no heading for it; the filter row says whose.
    add(results, kindGroups(home.length || !people.length ? home : bySpace.get(people[0]), "h2",
      { ...ctx, person: !home.length && people.length > 0 }));
  } else {
    if (home.length) {
      results.append(el("section", { class: "space-group space-home", "data-space": HOME_SPACE, "aria-label": "Home decks" },
        el("h2", {}, "Home decks", el("span", { class: "count", text: `(${home.length})` })),
        kindGroups(home, "h3", ctx)));
    }
    for (const space of people) results.append(personGroup(space, bySpace.get(space), ctx));
  }

  if (showProducts) results.append(productsGroup(data, products, ctx, filters.format === "product" || ctx.searching));

  if (!shown.length && !showProducts) {
    const chosen = libFilterCount(filters) || libTitleQuery(filters.q);
    // A button that clears the given filters and draws the Library again with the rest.
    const reset = (words, cleared) => el("a", { class: "btn", href: filtersHash({ ...filters, ...cleared }), text: words,
      onclick: (e) => { e.preventDefault();
        if (!target.isConnected || view.current && !view.current()) return;
        Object.assign(filters, cleared);
        history.replaceState(history.state, "", filtersHash(filters)); clear($("#main"));
        drawLibrary(state.library || data, filters); } });
    // A blocking check-date filter is already explained by the guidance line above: clear only that filter.
    // The head has the page's New deck primary, so the empty state's is a plain button.
    results.append(checkIssue.blocking
      ? emptyBox("No decks shown.", reset("Clear the check-date filter", { box_check: "", checked_before: "" }), { live: true })
      : chosen || !filters.all
        ? emptyBox(chosen ? "No decks match these filters." : "You don't play any decks yet.",
          reset("Show every deck", { all: true, format: "", status: "", color: "", archetype: "", readiness: "", box_check: "", checked_before: "", q: "" }),
          { live: Boolean(chosen) })
        : emptyBox("There are no decks yet.", createTargets().length ? el("a", { class: "btn", href: newDeckHref(), text: "New deck" }) : null));
  }
  // Decks are seen only in their own space (E10-S30): a member with nothing else to see is told why.
  const others = data.decks.some((d) => (d.space || deckSpaceOf(d.id)) !== ownSpace());
  if (state.profile && ownSpace() !== HOME_SPACE && !others) {
    results.append(el("p", { class: "result-count lib-nothing-public", text: "Nothing else is public yet." }));
  }
}

/** "Foundations Beginner Box" for "Cats (Foundations Beginner Box)". */
function productName(title) {
  const match = /\(([^()]+)\)\s*$/.exec(title);
  return match ? match[1] : "";
}

/** "product/<stem>" for a product deck's id: the product file, which holds one kit for all its decks. */
function productHolder(id) { return id.split("/").slice(0, 2).join("/"); }


// ------------------------------------------------------------------ the tile

/** A deck's colour pieces (ui.js deckColourPieces) from /api/decks' "colors" (its colour identity, worked out
 * from its commander or cards), or null when its list can't be read, has no cards or no card in it could be
 * read ("colors" null), so the tile shows no colours rather than a colourless C. */
function libColours(d) {
  return d.error || !d.card_count ? null : deckColourPieces(d.colors);
}

/** The cover banner: the cover card's art on the deck's art placeholder colour while it loads, or (no art, or
 * it fails) the deck's tint, with the deck's pips over its bottom-left corner. wide: the lab's detail pane, wider
 * than the art itself (Scryfall's art crop is about 626 px across), where the art keeps its own size in the middle
 * over a blurred copy of itself filling the rest (decided 2026-10-27: stretched across the pane it looked soft). */
function deckCover(d, colours = libColours(d), wide = false) {
  const art = d.cover && d.cover.art;
  const cover = el("span", { class: "deck-cover" + (art || !colours ? "" : " deck-tint") + (wide ? " deck-cover-wide" : ""),
    style: colours ? colours.vars(135) : null });
  const failed = () => {
    cover.querySelectorAll("img").forEach((i) => i.remove());
    if (colours) cover.classList.add("deck-tint");
  };
  const backdrop = art && wide ? el("img", { class: "deck-cover-backdrop", src: art, alt: "", "aria-hidden": "true",
    loading: "lazy", decoding: "async", draggable: "false" }) : null;
  const img = art ? el("img", { class: "deck-cover-img", src: art, alt: "", loading: "lazy", decoding: "async",
    width: 626, height: 457, draggable: "false", onerror: failed }) : null;
  return add(cover, [backdrop, img, colours ? colours.pips(20, { overArt: true, cls: "deck-pips" }) : null]);
}

/** A deck's status pill (4.4): on a casual tile only Building and Idea (decided 2026-10-25: a Built tile
 * has none, as chips are for exceptions); always in the lab's detail pane. Products have none. */
function deckStatusPill(d, always = false) {
  if (!d.status || d.read_only || (d.status === "built" && !always)) return null;
  return el("span", { class: `deck-status deck-status-${d.status}`, text: STATUS_WORDS[d.status] || d.status });
}

/** The counts a deck's owned bar shows: {owned, waiting, missing, total} of its Planned list, or null when they
 * aren't known (the visitor may not see its space's collection, or it can't be counted) or a built deck holds its
 * Play-now list (whose size isn't in /api/decks: the readiness chip says it). */
function libOwnedCounts(d) {
  if (d.error || !("missing" in d)) return null;
  if (d.status === "built" && d.built_version === "owned" && (d.versions || []).includes("owned")) return null;
  const counts = libCounts(d, "target");
  const total = (d.card_count || 0) + (d.sideboard_count || 0);
  if (!counts.known || !total) return null;
  return { owned: Math.max(0, total - counts.missing - counts.waiting), waiting: counts.waiting, missing: counts.missing, total };
}

/** The owned bar with its words (4.1, 4.2): "52 owned · 4 on the way · 4 to get", on a tile and in a lab row
 * alike (decided 2026-10-27: the lab's shorter "52 +4" didn't say what the +4 was). In the lab they're mono, the
 * on-the-way count in --accent-strong and to get in --missing. null as libOwnedCounts. */
function deckOwned(d, lab = false) {
  const c = libOwnedCounts(d);
  if (!c) return null;
  const words = factLine("deck-owned-words" + (lab ? " sim-num" : ""), [`${num(c.owned)} owned`,
    c.waiting ? (lab ? el("span", { class: "deck-owned-way", text: `${num(c.waiting)} on the way` }) : `${num(c.waiting)} on the way`) : null,
    c.missing ? (lab ? el("span", { class: "deck-owned-get", text: `${num(c.missing)} to get` }) : `${num(c.missing)} to get`) : null]);
  return el("span", { class: "deck-owned" }, ownedBar(c.owned, c.waiting, c.total), words);
}

/** What the readiness chip still has to say beside the owned bar: only that the Play-now list is ready (or
 * will be once its cards arrive); everything else is in the bar's words. */
function deckOwnedExtra(d) {
  const target = libCounts(d, "target");
  if (d.status === "built" || !target.missing || !(d.versions || []).includes("owned")) return null;
  const owned = libCounts(d, "owned");
  if (!owned.known || owned.missing) return null;
  return status("plain", owned.waiting ? `${listName("owned")} once ${num(owned.waiting)} arrive` : `${listName("owned")} ready`);
}

/** The tile's one meta line: who plays it (home decks; "Either" for a deck either of you plays), its size and
 * Commander bracket. */
function deckMeta(d, person) {
  const parts = [];
  if (!d.read_only && !person) parts.push(d.player === "either" ? "Either" : deckPlayerWords(d));
  if (d.card_count) parts.push(d.sideboard_count ? `${num(d.card_count)} + ${num(d.sideboard_count)} sideboard` : plural(d.card_count, "card"));
  if (d.target_bracket) parts.push(`Bracket ${d.target_bracket}`);
  // Each fact stays on one line ("Bracket 2", "60 + 15 sideboard"), and a wrapped line never starts with a "·"
  // (core.js factLine).
  return parts.length ? factLine("deck-meta", parts) : null;
}

/** A deck's tile in the library: the whole tile is one link (or, while choosing pictures, a button for a deck
 * the visitor may change). product: its product's name (left out of the title); compact: the Beginner Box's
 * smaller tiles; kitShown: its product's kit is already on the group's heading. */
function deckCard(d, product, compact, kitShown = false, ctx = {}) {
  const title = product ? d.title.replace(` (${product})`, "") : d.title;
  const ready = d.error ? { chip: null, missing: 0 } : deckReadiness(d);
  const colours = libColours(d);
  const banner = deckCover(d, colours);
  const owned = d.error ? null : deckOwned(d);
  const chip = owned ? deckOwnedExtra(d) : ready.chip;
  const body = [
    colours ? colours.stripe() : null,
    banner,
    el("span", { class: "deck-body" + (colours ? " deck-tint" : ""), style: colours ? colours.vars(135) : null },
      el("span", { class: "deck-title-row" }, el("span", { class: "deck-title", text: title })),
      compact ? null : deckMeta(d, ctx.person),
      deckStatusPill(d),
      d.assembled && "missing" in d && (d.assembled.sideboard_intended || d.assembled.sideboard_count || d.assembled.changed)
        ? el("span", { class: "deck-assembled", text: assembledStateWords(d.assembled) }) : null,
      owned,
      d.error ? el("span", { class: "deck-error", text: `Can't be read: ${d.error}` })
        : chip ? el("span", { class: "deck-missing" }, chip) : null,
      d.error ? null : deckForgeLine(d),
      deckTokens(d.tokens),
      kitShown ? null : deckSleeve(d.kit))];
  if (ctx.picking) {
    if (libCoverEditable(d)) banner.append(el("span", { class: "deck-pick-badge", "aria-hidden": "true", text: "Change picture" }));
    return libPickButton(d, title, body, "deck-card", ctx);
  }
  const href = deckHref(d.id) + (ready.missing > 0 ? "&tab=cards&filter=missing" : "");
  return el("a", { class: "deck-card" + (compact ? " is-compact" : ""), href }, body);
}

/** The picture picker's button for a deck the visitor may change (while choosing deck pictures), or a dimmed
 * stand-in for one they may not: a tile's or a row's body inside. */
function libPickButton(d, title, body, cls, ctx) {
  if (!libCoverEditable(d)) return el("div", { class: `${cls} is-unpickable`, "aria-disabled": "true" }, body);
  return el("button", { type: "button", class: `${cls} lib-pick`, "aria-haspopup": "dialog", "data-id": d.id,
    "aria-label": `Change the picture of ${title}`,
    onclick: () => openCoverPicker(d.id, (cover, revision) => {
      d.cover = cover;
      d.revision = revision;
      // Drawn again only while the library is on screen; the focus goes back to this deck's new tile or row.
      if (ctx.redraw && ctx.redraw()) {
        const again = Array.from(document.querySelectorAll(".lib-pick")).find((n) => n.getAttribute("data-id") === d.id);
        if (again) again.focus();
      }
    }) }, body);
}

/** A deck's small art thumbnail (the lab's rows, Matchups' deck picker): the cover art on the deck's art colour
 * while it loads, or (no art, or it fails) the deck's tint, with a thin colour stripe under it. cls sizes it. */
function deckArtThumb(d, colours = libColours(d), cls = "deck-row-art") {
  const art = d.cover && d.cover.art;
  const thumb = el("span", { class: cls + (art || !colours ? "" : " deck-tint"), style: colours ? colours.vars(135) : null },
    art ? el("img", { src: art, alt: "", loading: "lazy", decoding: "async", width: 626, height: 457, draggable: "false",
      onerror: (e) => {
        e.currentTarget.remove();
        if (colours) thumb.classList.add("deck-tint");
      } }) : null,
    colours ? colours.stripe(true) : null);
  return thumb;
}

/** A deck's row in the lab (4.2): a 56 x 38 art thumbnail with a 3 px stripe under it, the title with 16 px
 * pips and the meta line, and the owned bar with mono words. It's a link to the deck page: a click selects it
 * (the detail pane shows it), Enter (a click with no pointer) or a click with a modifier opens it. */
function deckRow(d, ctx) {
  const colours = libColours(d);
  const thumb = deckArtThumb(d, colours);
  const ready = d.error ? { chip: null, missing: 0 } : deckReadiness(d);
  const owned = d.error ? null : deckOwned(d, true);
  const chip = d.error ? el("span", { class: "deck-error", text: "Can't be read" }) : owned ? null : ready.chip;
  const body = [thumb,
    el("span", { class: "deck-row-main" },
      el("span", { class: "deck-row-title" }, el("span", { class: "deck-title", text: d.title }),
        colours ? colours.pips(16, { cls: "deck-pips" }) : null),
      deckMeta(d, ctx.person)),
    el("span", { class: "deck-row-end" }, owned, chip),
    deckRowForge(d)];
  if (ctx.picking) return libPickButton(d, d.title, body, "deck-row", ctx);
  const selected = ctx.selected === d.id;
  return el("a", { class: "deck-row", href: deckHref(d.id) + (ready.missing > 0 ? "&tab=cards&filter=missing" : ""),
    "data-id": d.id, "aria-current": selected ? "true" : null,
    onclick: (event) => {
      if (event.detail === 0 || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      ctx.select(d.id);
    } }, body);
}

/** The lab's detail pane (5, Library): the selected deck's overview, with its art, colours, status, who plays
 * it, its owned bar, what's missing, tokens and kit, and the ways in: Edit deck (the pane's one primary, for a
 * deck the visitor may change) and Open deck. */
function libDetail(d, ctx) {
  const colours = libColours(d);
  const ready = d.error ? { chip: null, missing: 0 } : deckReadiness(d);
  const owned = d.error ? null : deckOwned(d);
  const chip = owned ? deckOwnedExtra(d) : ready.chip;
  const open = deckHref(d.id) + (ready.missing > 0 ? "&tab=cards&filter=missing" : "");
  const edit = canEditDeck(d) && !d.error ? el("a", { class: "btn btn-primary", href: editHref(d.id), text: "Edit deck" }) : null;
  const glance = libGlance(d);                                  // library-glance.js
  return el("section", { class: "lib-detail", "aria-label": `Selected deck: ${d.title}`, "data-id": d.id },
    el("div", { class: "lib-detail-card" },
      colours ? colours.stripe() : null,
      deckCover(d, colours, true),
      el("div", { class: "lib-detail-body" + (colours ? " deck-tint" : ""), style: colours ? colours.vars(90) : null },
       el("div", { class: "lib-detail-main" },
        el("h2", { class: "lib-detail-title", text: d.title }),
        el("div", { class: "lib-detail-chips" }, deckStatusPill(d, true), deckMeta(d, ctx.person)),
        owned,
        d.error ? el("p", { class: "deck-error", text: `Can't be read: ${d.error}` })
          : chip ? el("div", { class: "deck-missing" }, chip) : null,
        d.assembled && "missing" in d && (d.assembled.sideboard_intended || d.assembled.sideboard_count || d.assembled.changed)
          ? el("p", { class: "deck-assembled", text: assembledStateWords(d.assembled) }) : null,
        d.error ? null : libDetailForge(d),
        deckTokens(d.tokens),
        deckSleeve(d.kit),
        libBoxSelectedNote(d),
        el("div", { class: "actions lib-detail-actions" }, edit,
          el("a", { class: edit ? "btn btn-secondary" : "btn btn-primary", href: open, text: "Open deck" }))),
       glance.facts, glance.cards)));
}

/** The library's Forge numbers (GET /api/library/forge: each casual list's field average and when it was tested,
 * worked out on the PC from the saved games and cached there), fetched once the shelf is drawn and drawn in when
 * they come. Until then, or when they can't be worked out, the Forge lines are left out (never shown as untested). */
function libLoadForge(data, refresh) {
  if (!data.decks.some((d) => d.kind === "casual")) return;
  const profile = state.profile ? state.profile.id : null;
  api("/api/library/forge").then((answer) => {
    if (!answer || answer.error) return;
    state.libraryForge = { profile, decks: answer.decks || {} };
    refresh();
  }).catch(() => {});
}

/** A deck's Forge numbers ({version, rate, partial, counted, of, games, tested}), null for a casual deck with none
 * (not in the field, or not tested), or undefined while they aren't known or for a Commander deck (4.2: blank). */
function libForge(d) {
  const known = state.libraryForge;
  if (!known || known.profile !== (state.profile ? state.profile.id : null) || d.kind !== "casual") return undefined;
  return known.decks[d.id] || null;
}

/** A tile's Forge line (4.1), only when the deck has been tested: the field win rate (mono 16 / 600, "Forge field")
 * and the freshness badge. */
function deckForgeLine(d) {
  const n = libForge(d);
  if (!n || !n.rate) return null;
  return el("span", { class: "deck-forge" },
    winRateFigure(n.rate, { size: "tile", what: "Forge field win rate", games: n.games }),
    freshnessBadge(n.tested, { size: "casual", onTint: true }));
}

/** A lab row's Forge field column (4.2): the inline win rate, its range and the freshness; "—" for a casual deck
 * without a field result; blank for a Commander deck (and while the numbers are on their way). */
function deckRowForge(d) {
  const cell = el("span", { class: "deck-row-forge" });
  const n = libForge(d);
  if (n === undefined) return cell;
  if (!n || !n.rate) {
    cell.append(el("span", { class: "deck-row-untested", role: "img", "aria-label": "Not tested against the Forge field",
      text: "—" }));
    return cell;
  }
  add(cell, [winRateFigure(n.rate, { what: "Forge field win rate", games: n.games, barred: true }),
    rangeBar(n.rate, { compact: true, decorative: true }),
    freshnessBadge(n.tested, { size: "row", compact: true })]);
  return cell;
}

/** The detail pane's Forge field summary (5, Library): the hero figure with its games, the range bar on the 20-80%
 * scale, the freshness, how much of the field it has played, and the way to the deck's field view. */
function libDetailForge(d) {
  const n = libForge(d);
  if (!n || !n.rate) return null;
  return el("div", { class: "lib-detail-forge", role: "group", "aria-label": "Forge field" },
    el("p", { class: "lib-detail-label", text: "Forge field" }),
    el("div", { class: "lib-detail-forge-figure" },
      winRateFigure(n.rate, { size: "hero", what: "Forge field win rate", games: n.games, barred: true }),
      freshnessBadge(n.tested, { size: "panel", onTint: true })),
    rangeBar(n.rate, { axis: true, decorative: true }),
    n.partial && n.of ? el("p", { class: "lib-detail-forge-note", text: `Against ${num(n.counted)} of the ${plural(n.of, "deck")} in the field so far.` }) : null,
    el("a", { class: "btn btn-quiet btn-inline", href: `${deckHref(d.id, n.version)}&part=field`, text: "Field view" }));
}

/** The order the lab's rows show in (home first, then each person's; Commander then 60-card; Built, Building,
 * Ideas; then the sort): its first deck is selected when the address names none that's shown. */
function libRowOrder(decks, sort) {
  const spaceKey = (d) => { const space = d.space || deckSpaceOf(d.id); return space === HOME_SPACE ? "" : spaceName(space); };
  const kindAt = (d) => LIB_KIND_ORDER.indexOf(d.kind);
  const statusAt = (d) => { const i = LIB_STATUS_GROUPS.findIndex(([status]) => status === d.status); return i < 0 ? 9 : i; };
  const at = new Map(sortDecks(decks, sort).map((d, i) => [d.id, i]));
  return decks.filter((d) => kindAt(d) >= 0).sort((a, b) => spaceKey(a).localeCompare(spaceKey(b))
    || kindAt(a) - kindAt(b) || statusAt(a) - statusAt(b) || at.get(a.id) - at.get(b.id));
}

/** Draw the shelf again when the window crosses the lab's width (tiles one side, rows and the detail pane the
 * other); it stops listening once the library has been left. */
function libWatchDensity(results, refresh) {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
  const query = window.matchMedia(LIB_LAB_QUERY);
  if (typeof query.addEventListener !== "function") return;
  const changed = () => { if (!refresh()) query.removeEventListener("change", changed); };
  query.addEventListener("change", changed);
}

/** J and K in the lab: select the next or previous row and move the focus to it (Enter then opens it). Not
 * while typing, with a modifier, or once the library has been left. */
function libKeys(results, view) {
  const token = routeToken, profile = state.profile ? state.profile.id : null;
  const keys = (event) => {
    if (!results.isConnected) { document.removeEventListener("keydown", keys); return; }
    if (token !== routeToken || profile !== (state.profile ? state.profile.id : null) || !libIsLab()
        || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey || event.defaultPrevented
        || event.isComposing || event.keyCode === 229 || keyboardDialog() || keyboardMenuOpen()) return;
    const key = (event.key || "").toLowerCase();
    if ((key !== "j" && key !== "k") || !keyboardCharactersEnabled(profile)) return;
    const target = event.target;
    if ((target && target.isConnected === false) || keyboardEditing(target)) return;
    const rows = Array.from(results.querySelectorAll(".deck-row"));
    if (!rows.length) return;
    const at = rows.findIndex((r) => r.getAttribute("aria-current") === "true");
    const next = rows[Math.max(0, Math.min(rows.length - 1, at + (key === "j" ? 1 : -1)))];
    event.preventDefault();
    view.select(next.getAttribute("data-id"), true);
  };
  document.addEventListener("keydown", keys);
}

/** A deck card's (or a product's) sleeves and deck box from /api/decks' brief kit ({sleeves, deck_box:
 * {name, image_url, state} or null, short}): a 32 px picture beside each name, and a warning chip when
 * the sleeves are short or a value names the wrong kind. null when nothing is recorded. */
function deckSleeve(kit, cls = "deck-sleeve") {
  if (!kit || (!kit.sleeves && !kit.deck_box) || !mayDo("see_accessories")) return null;
  const part = (ref, what, wrong) => ref ? el("span", { class: "deck-sleeve-part" },
    accessoryThumb(ref, 32), el("span", {}, `${what} `, el("b", { text: ref.name })),
    ref.state === "kind_mismatch" ? status("warn", wrong) : null) : null;
  return el("span", { class: cls },
    part(kit.sleeves, "Sleeves", "Not sleeves"),
    kit.short ? status("warn", `${plural(kit.short, "sleeve")} short`) : null,
    part(kit.deck_box, "Deck box", "Not a deck box"));
}

/** A deck card's token line from /api/decks' brief ({kinds, none, differs, incoming, reminders}: token names, one
 * per token the deck makes, so a name can come more than once; reminders names the emblems and reminders among
 * them), only when something is wrong: "No Raccoon token", "No Dragon or Treasure tokens, The Monarch", "Insect
 * token differs", "Fish token on the way". A deck with every token, or none, gets nothing (null), and so does one
 * whose tokens couldn't be worked out. */
function deckTokens(brief) {
  if (!brief) return null;
  const reminders = new Set(brief.reminders || []);
  const words = (list, joiner) => tokenNamesWords((list || []).filter((n) => !reminders.has(n)),
    (list || []).filter((n) => reminders.has(n)), joiner);
  const none = words(brief.none, "or"), differs = words(brief.differs, "and"), incoming = words(brief.incoming, "and");
  const chips = [none.count ? status("warn", `No ${none.text}`) : null,
    differs.count ? status("warn", `${differs.text} ${differs.count > 1 ? "differ" : "differs"}`) : null,
    incoming.count ? status("info", `${incoming.text} on the way`) : null].filter(Boolean);
  return chips.length ? el("span", { class: "deck-tokens" }, chips) : null;
}

function pairingPicker(halves) {
  const pick = (id, label, selected) => {
    const select = el("select", { id, name: id },
      halves.map((h, i) => el("option", { value: h.id, text: h.title, selected: i === selected })));
    return [el("label", { class: "field", for: id }, el("span", { text: label }), select), select];
  };
  const [firstField, first] = pick("half-a", "First half", 0);
  const [secondField, second] = pick("half-b", "Second half", 1);
  const error = el("p", { class: "form-error", role: "alert" });
  const form = el("form", { class: "pairing-form", novalidate: true,
    onsubmit: (event) => {
      event.preventDefault();
      if (first.value === second.value) {
        error.textContent = "Pick two different halves: a pairing can't use the same half twice.";
        second.focus();
        return;
      }
      error.textContent = "";
      location.hash = deckHref(pairingId(first.value, second.value));
    } },
    firstField, secondField,
    el("button", { type: "submit", class: "btn", text: "Open the 40-card deck" }));
  return el("div", { class: "pairing" },
    el("h4", { text: "Try a Beginner Box pairing" }),
    el("p", { text: "Shuffle any two of the 20-card halves together to make a 40-card deck." }),
    form, error);
}
