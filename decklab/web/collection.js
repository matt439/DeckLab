/* The Collection page (#/collection): find cards in a space's collection (owned and on the way, with
 * filters) without changing its records, and, where the visitor may change that space's collection,
 * add, edit and remove single rows and import a scanner or collection-app export. Works on phones as
 * well as desktops.
 *
 * Routes:
 *     #/collection[?space=<id>&q=&color=&type=&role=&mv=&availability=&page=]   finding cards
 *     #/collection?space=<id>&view=rows                                       the space's rows, to edit
 * Each space (lib/spaces.py) has its own collection: home's, and each person's. The page opens on
 * the visitor's own space. Home's addresses and requests leave ?space= out.
 *
 * Find cards uses a lab card grid and casual rows, each with its own viewer group so hidden
 * layouts do not duplicate swipe items; its filters apply as they're typed, and the address follows them (replaceState).
 * The viewer's words for a card say how many are owned, free and in which decks, with "Edit copies".
 * The Card list is a dense table of the rows, sortable and paged, with a filter for rows whose
 * condition or language isn't recorded and each row's estimated price (its own printing and finish,
 * collection_edit._prices; the sort puts unpriced rows last both ways) and an "In storage only" filter
 * (collection_edit._storage: each row's copies in built decks and intact products, a guess where the
 * decks' lists name another printing); a row's thumbnail opens the viewer (its own group) and its
 * name selects its printing/finish preview in the lab, with Edit copies opening the existing row sheet.
 * Casual rows open the viewer with recorded notes and an Edit copies action when permitted. "Set condition &
 * language…" sets one condition and/or language on every row shown, in one change (collection-bulk.js).
 *
 * Writes (lib/api/collection_edit.py) carry the rows' sha256 as the page loaded them: a list changed by
 * someone else meanwhile answers 409 with the latest rows, and the page offers to put the change back
 * on top of it (field by field, as the Tokens page does). A row is named by its identity key (set,
 * collector number, finish), which the server merges on: adding a printing that's already listed adds to
 * its quantity ("merged"). An import is previewed first (problems listed, plain basics left out), then
 * added in one change. "Add a precon" (lib/api/precons.py)
 * finds a published precon, previews its cards, then adds them and makes its built deck in one go.
 * "Record a trade" (collection-trade.js) saves the copies that left and the cards that came in as one change. */
"use strict";

const COL_FIELDS = ["name", "set", "collector_number", "finish", "quantity", "condition", "language", "notes"];
const COL_FIELD_WORDS = { name: "Name", set: "Set", collector_number: "Collector number", finish: "Finish",
  quantity: "Quantity", condition: "Condition", language: "Language", notes: "Notes" };
const COL_FINISH_WORDS = { nonfoil: "Non-foil", foil: "Foil", etched: "Etched" };
// Condition: a segmented choice (short words), with the long ones as each button's title.
const COL_CONDITIONS = [["", "?", "Not recorded"], ["NM", "NM", "Near Mint"], ["LP", "LP", "Lightly Played"],
  ["MP", "MP", "Moderately Played"], ["HP", "HP", "Heavily Played"], ["DMG", "DMG", "Damaged"]];
// Supported codes match collection_edit.LANGUAGES; retain the existing display names.
const COL_LANGUAGES = [["", "Not recorded"], ["en", "English"], ["ja", "Japanese"], ["de", "German"],
  ["fr", "French"], ["it", "Italian"], ["es", "Spanish"], ["pt", "Portuguese"],
  ["ru", "Russian"], ["ko", "Korean"], ["zhs", "Chinese (simplified)"], ["zht", "Chinese (traditional)"],
  ["he", "Hebrew"], ["la", "Latin"], ["grc", "Ancient Greek"], ["ar", "Arabic"],
  ["sa", "Sanskrit"], ["ph", "Phyrexian"], ["qya", "Quenya"]];
const COL_FILTER_KEYS = ["q", "color", "type", "role", "mv", "availability", "page"];
const COL_AVAILABILITY = [["all", "All"], ["free", "Free now"], ["incoming", "On the way"], ["held", "In decks"]];
const COL_IMPORT_MAX = 4 * 1024 * 1024;     // bytes: the server's limit (collection_edit.MAX_IMPORT; 20,000 rows)
const COL_NOTES_MAX = 500;
const COL_ROWS_PAGE = 100;                  // Card list rows a page
const COL_TYPE_MS = 250;                    // wait this long after typing before filtering
const COL_STRIP_FILTER = 12;                // more printings than this: the strip gets a "Find a set" box
const COL_SORTS = { name: "Card", set: "Printing", quantity: "Copies", price: "~A$ each", condition: "Condition",
  language: "Language" };
const COL_SORT_FIRST = { price: -1 };       // the first tap on a heading: most valuable first


// ------------------------------------------------------------ shared pieces

/** An API path for a space: home's without ?space=. query: more parameters (URLSearchParams). */
function colPath(base, space, query) {
  const params = new URLSearchParams(query || "");
  if (space && space !== HOME_SPACE) params.set("space", space);
  const text = params.toString();
  return text ? `${base}?${text}` : base;
}

/** The page's own address for a space and view ("find" or "rows"), with the filters when finding. */
function colHash(space, view = "find", query = null) {
  const params = new URLSearchParams(view === "find" && query ? query : "");
  params.delete("space");
  if (space && space !== HOME_SPACE) params.set("space", space);
  else if (space === HOME_SPACE && ownSpace() !== HOME_SPACE) params.set("space", HOME_SPACE);
  if (view === "rows") params.set("view", "rows");
  const text = params.toString();
  return `#/collection${text ? `?${text}` : ""}`;
}

/** The space the address asks for, when there is one by that id; else the visitor's own. */
function colSpace(params) {
  const wanted = params.get("space");
  return wanted && seenSpaces().some((s) => s.id === wanted) ? wanted : ownSpace();
}

/** A row's identity key, as the server merges rows: set, collector number and finish. */
function colKey(row) {
  return [row.set, row.collector_number, row.finish].map((v) => String(v ?? "").toLowerCase()).join("|");
}

/** The row with every field as text: a save's base, and how a row is found again. */
function colBase(row) {
  return Object.fromEntries(COL_FIELDS.map((key) => [key, row[key] == null ? "" : String(row[key])]));
}

function colSameRow(a, b) { return COL_FIELDS.every((key) => String(a[key] ?? "") === String(b[key] ?? "")); }

/** "FDN 227 · Foil", or "Printing not recorded". */
function colPrinting(row) {
  if (!row.set) return "Printing not recorded";
  const finish = row.finish && row.finish !== "nonfoil" ? ` · ${COL_FINISH_WORDS[row.finish] || row.finish}` : "";
  return `${String(row.set).toUpperCase()} ${row.collector_number || ""}`.trim() + finish;
}

/** "Quantity 2 → 3; Notes (blank) → binder" for what someone else changed on a row. */
function colChangedWords(base, row) {
  const shown = (value) => value === "" ? "(blank)" : value;
  return COL_FIELDS.filter((key) => String(base[key] ?? "") !== String(row[key] ?? ""))
    .map((key) => `${COL_FIELD_WORDS[key]} ${shown(String(base[key] ?? ""))} → ${shown(String(row[key] ?? ""))}`).join("; ");
}

/** The space's name for headings: "Collection" at home, "Jordan's collection" for a person. */
function colTitle(space) {
  return space === HOME_SPACE ? routeH1("collection") : `${spaceName(space)}'s collection`;
}

/** "the collection" or "Jordan's collection", inside a sentence. */
function colWhose(space) {
  return space === HOME_SPACE ? "the collection" : `${spaceName(space)}'s collection`;
}

/** Whether a row's condition or language isn't recorded (the Card list's filter). */
function colUnrecorded(row) { return !row.condition || !row.language; }

/** Run go once the card viewer has closed and its history entry has gone (a link or a sheet from the
 * viewer's words): straight away when it isn't open. */
function colAfterViewer(go) {
  if (typeof viewerDom === "undefined" || !viewerDom || !viewerDom.dialog.open) { go(); return; }
  let done = false;
  const run = () => {
    if (done) return;
    done = true;
    window.removeEventListener("popstate", run);
    setTimeout(go, 0);
  };
  window.addEventListener("popstate", run);
  closeViewer();
  setTimeout(run, 400);               // no history entry to go back from
}

/** A link in the viewer's words: it closes the viewer first, then goes. */
function colViewerLink(href, text) {
  return el("a", { href, text, onclick: (event) => {
    event.preventDefault();
    colAfterViewer(() => { location.hash = href; });
  } });
}

/** First · Previous · "Page 3 of 30" · Next · Last, or null for a single page. go(page) shows a page. */
function colPager(page, pages, go, label) {
  if (!(pages > 1)) return null;
  const button = (text, to, aria) => el("button", { type: "button", class: "btn btn-quiet", text, "aria-label": aria,
    disabled: to < 1 || to > pages || to === page || null, onclick: (event) => go(to, event.currentTarget) });
  return el("nav", { class: "col-pager", "aria-label": label },
    button("«", 1, "First page"), button("‹", page - 1, "Previous page"),
    el("span", { class: "col-pager-at", text: `Page ${page} of ${pages}` }),
    button("›", page + 1, "Next page"), button("»", pages, "Last page"));
}

/** A segmented choice of buttons (aria-pressed): options [[value, words, title?]]. Returns the group; its
 * value is group.value, and onchange(value) runs on a press. */
function colSegmented(options, value, onchange, aria) {
  const group = el("div", { class: "segmented", role: "group", "aria-label": aria });
  group.value = value;
  const mark = () => { for (const b of group.children) b.setAttribute("aria-pressed", String(b.dataset.value === group.value)); };
  for (const [v, words, title] of options) {
    group.append(el("button", { type: "button", "data-value": v, text: words, title: title || null,
      "aria-label": title && title !== words ? `${words} (${title})` : null,
      onclick: () => { group.value = v; mark(); if (onchange) onchange(v); } }));
  }
  mark();
  return group;
}


// ---------------------------------------------------------------- the page

function showCollection(params, token) {
  const space = colSpace(params);
  setTitle(colTitle(space));
  if (params.get("view") === "rows") {
    return load(colPath("/api/collection/rows", space), token, (data) => drawCollectionRows(data, space, token),
      { title: "The collection couldn't be loaded" });
  }
  const query = new URLSearchParams();
  for (const key of COL_FILTER_KEYS) if (params.get(key)) query.set(key, params.get(key));
  const asked = new URLSearchParams(query);
  asked.set("limit", String(colPageSize()));
  return load(colPath("/api/collection", space, asked), token, (data) => drawCollection(data, query, space, token));
}

/** What a page of the collection holds for its writes: cv ("collection view"). */
function colView(data, space, token, kind) {
  return { token: token == null ? routeToken : token, profile: state.profile && state.profile.id, space, kind,
    data, busy: false, seq: 0,
    // A server that doesn't know spaces yet answers with home's cards and no "space": a person's isn't shown.
    unsupported: space !== HOME_SPACE && data.space === undefined,
    editable: data.editable === true && (data.space === undefined || data.space === space),
    sha256: data.sha256 || null, rows: Array.isArray(data.rows) ? data.rows : null,
    pictures: data.pictures && typeof data.pictures === "object" ? { ...data.pictures } : {},
    prices: colPrices(data.prices),
    storage: colStorage(data.storage),
    message: el("div", { class: "col-message", role: "status", "aria-live": "polite" }) };
}

/** A prices answer (collection_edit._prices) as the page keeps it: its rows always an object. */
function colPrices(prices) {
  const p = prices && typeof prices === "object" ? prices : {};
  return { ...p, rows: p.rows && typeof p.rows === "object" ? p.rows : {} };
}

/** A storage answer (collection_edit._storage) as the page keeps it; null without one (an older server). */
function colStorage(storage) {
  if (!storage || typeof storage !== "object") return null;
  return { error: storage.error || null, rows: storage.rows && typeof storage.rows === "object" ? storage.rows : {} };
}

/** Older refresh answers may retain legacy counts, but cannot renew named packing-list hints. */
function colWithoutHints(storage) {
  if (!storage) return storage;
  return { ...storage, rows: Object.fromEntries(Object.entries(storage.rows).map(([key, value]) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return [key, value];
    const { listed_holders, unattributed, ...counts } = value;
    return [key, counts];
  })) };
}

/** A row's copies in decks: {held (null for a basic land: not tracked), guess}, held 0 when none. */
function colHeld(cv, row) {
  const s = cv.storage && cv.storage.rows[colKey(row)];
  return s ? { held: s.held == null ? null : Number(s.held) || 0, guess: s.guess === true } : { held: 0, guess: false };
}

/** Whether some of a row's copies may be in the storage box (a basic land's always may). */
function colInStorage(cv, row) {
  const { held } = colHeld(cv, row);
  return held == null || Number(row.quantity || 0) > held;
}

/** A row's estimated A$ (its own printing and finish), or null when there's none. */
function colPrice(cv, row) {
  const p = cv.prices && cv.prices.rows[colKey(row)];
  return p && typeof p.aud === "number" ? p.aud : null;
}

/** A 409's latest rows (collection_edit._stale), with their prices so new rows aren't shown unpriced. */
function colTakeRows(cv, data) {
  cv.rows = data.rows;
  if (data.prices) cv.prices = colPrices(data.prices);
  cv.storage = data.storage ? colStorage(data.storage) : colWithoutHints(cv.storage);
}

function colActive(cv) {
  return cv.token === routeToken && state.profile && state.profile.id === cv.profile
    && (!cv.root || cv.root.isConnected);
}

/** Page keys belong to one current view and yield to text composition, menus and dialogs. */
function colKeyboardReady(cv, event) {
  return colActive(cv) && !cv.busy && !event.defaultPrevented && !event.isComposing && event.keyCode !== 229
    && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey
    && event.currentTarget?.isConnected && cv.root?.contains(event.currentTarget)
    && !document.querySelector("dialog[open]") && !keyboardMenuOpen();
}

/** Save the space's collection as a CSV in the collection's columns, named after the space and the date
 * (GET /api/collection/download, guarded as the page is: E7-S30). */
async function downloadCollection(cv) {
  let data;
  try {
    data = await api(colPath("/api/collection/download", cv.space));
  } catch (e) {
    colSay(cv, `The collection couldn't be downloaded: ${e.message}`);
    return;
  }
  const url = URL.createObjectURL(new Blob([data.csv], { type: "text/csv;charset=utf-8" }));
  const link = el("a", { href: url, download: data.filename });
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The head of both views: the title with Add card (where the visitor may change this collection) and
 * More (Import cards, Add a precon, Record a trade, Download, Packing plan), then the space picker and Find cards / Card list. */
function colHead(cv, query) {
  const spaces = sortSpaces(Array.isArray(cv.data.spaces) && cv.data.spaces.length ? cv.data.spaces : spaceList())
    .filter((s) => seesInventory(s.id));
  const picker = spaces.length > 1 ? el("nav", { class: "segmented col-spaces", "aria-label": "Whose collection" },
    spaces.map((s) => el("a", { href: colHash(s.id, cv.kind, query), text: s.id === HOME_SPACE ? "Home" : s.name,
      "aria-current": s.id === cv.space ? "page" : null }))) : null;
  const tabs = el("nav", { class: "segmented col-views", "aria-label": "Collection view" },
    el("a", { href: colHash(cv.space, "find", query), text: "Find cards", "aria-current": cv.kind === "find" ? "page" : null }),
    el("a", { href: colHash(cv.space, "rows"), text: "Card list", "aria-current": cv.kind === "rows" ? "page" : null }));
  const owner = cv.space === HOME_SPACE ? "the people of the home collection" : spaceName(cv.space);
  const more = [
    cv.editable ? { label: "Import cards…", onclick: () => openImportSheet(cv) } : null,
    cv.editable ? { label: "Add a precon…", onclick: () => openPreconSheet(cv) } : null,
    cv.editable && !cv.unsupported ? { label: "Record a trade…", onclick: () => openTradeSheet(cv) } : null,
    cv.unsupported ? null : { label: "Download collection (CSV)", onclick: () => downloadCollection(cv) },
    cv.space === HOME_SPACE && seesInventory(HOME_SPACE) ? { label: routeH1("assembly"), href: "#/assembly" } : null];
  return [
    ...pageHead({ title: colTitle(cv.space),
      description: cv.kind === "rows" ? "Every printing recorded, one row each." : "Cards you own or have on the way.",
      primary: cv.editable ? el("button", { type: "button", class: "btn btn-primary col-mutate", text: "Add card",
        "data-focus": "add", onclick: () => openCollectionSheet(cv) }) : null,
      more }),
    el("div", { class: "col-switches" }, picker, tabs),
    cv.unsupported ? el("p", { class: "box box-info",
      text: `${spaceName(cv.space)}'s collection can't be shown until Deck Lab's server is updated.` })
      : !cv.editable && cv.data.space !== undefined ? el("p", { class: "sub col-read-only",
        text: `Read only: only ${owner} can change ${cv.space === HOME_SPACE ? "the home collection" : "this collection"}.` }) : null,
    cv.message];
}

function setCollectionBusy(cv, busy) {
  cv.busy = busy;
  if (!cv.root) return;
  cv.root.setAttribute("aria-busy", String(busy));
  for (const control of cv.root.querySelectorAll(".col-mutate")) control.disabled = busy;
  refreshKeyboardHints();
}

/** Say what happened (and toast it); stale: a save's stale_tables, the decks' tables it left out of date
 * (library-tables.js's line, linking to the Decks page's list). */
function colSay(cv, words, stale) {
  clear(cv.message);
  if (!words) return;
  add(cv.message, [el("p", { text: words }), staleTablesNote(stale)]);
  toast(words);
}

/** The rows and their sha256 (and pictures), fetched when the page didn't load them (the Find cards view). */
async function colEnsureRows(cv) {
  if (cv.sha256 && cv.rows) return;
  const data = await api(colPath("/api/collection/rows", cv.space));
  cv.sha256 = data.sha256;
  cv.rows = data.rows || [];
  if (data.pictures) Object.assign(cv.pictures, data.pictures);
  if (data.prices) cv.prices = colPrices(data.prices);
  if (data.storage) cv.storage = colStorage(data.storage);
}

/** After a change: the new rows, and the view drawn again (Find cards loads its page again). */
function colChanged(cv, answer, words) {
  if (answer && answer.sha256) cv.sha256 = answer.sha256;
  if (answer && Array.isArray(answer.rows)) cv.rows = answer.rows;
  if (answer && answer.pictures) Object.assign(cv.pictures, answer.pictures);
  if (answer && answer.prices) cv.prices = colPrices(answer.prices);
  cv.storage = answer && answer.storage ? colStorage(answer.storage) : colWithoutHints(cv.storage);
  state.library = null;               // the library's missing-card counts come from the collection
  if (!colActive(cv)) { if (words && state.profile?.id === cv.profile) toast(words); return; }
  if (cv.kind === "rows") {
    drawColRowList(cv);
    colSay(cv, words, answer && answer.stale_tables);
    setCollectionBusy(cv, false);
    return;
  }
  colReload(cv, words, answer && answer.stale_tables);
}

/** Load the view again from the server, then say what happened there: the Find cards counts, or the Card
 * list after an import, come from the server. */
function colReload(cv, words, stale) {
  state.colNotice = { space: cv.space, words, stale };
  route();
}

/** The message a change left for the view drawn after it (colReload), once. */
function colTakeNotice(cv) {
  const notice = state.colNotice;
  state.colNotice = null;
  if (notice && notice.space === cv.space && notice.words) colSay(cv, notice.words, notice.stale);
}


// --------------------------------------------------------------- Find cards

function drawCollection(data, query, space = HOME_SPACE, token = null) {
  const cv = colView(data, space, token, "find");
  cv.query = new URLSearchParams(query);
  cv.findSeq = 0;
  const root = el("div", { class: "collection-page col-find-page" }, colHead(cv, query));
  cv.root = root;
  if (!cv.unsupported) {
    cv.results = el("div", { class: "col-results" });
    // While a search is fetched: a small spinner and words over the dimmed old results.
    cv.findLoading = el("div", { class: "col-find-loading" });
    add(root, [colFilters(cv), cv.findLoading, cv.results]);
    drawCollectionResults(cv, data);
  }
  $("#main").append(root);
  registerCollectionKeyboardHelp(cv);
  colTakeNotice(cv);
  boxCollectionConsume(cv);
  return cv;
}

/** The filters: the search, then colour, type, role and mana value, then where the cards are. Each one
 * filters as it changes (colFilter); the search a moment after typing stops. */
function colFilters(cv) {
  const data = cv.data;
  const q = cv.query;
  const id = (key) => `collection-${key}`;
  const select = (key, options) => {
    const node = el("select", { id: id(key), onchange: () => colFilter(cv, key, node.value) },
      options.map(([value, text]) => el("option", { value, text })));
    node.value = q.get(key) || "";
    return node;
  };
  const search = el("input", { id: id("q"), type: "search", maxlength: 160, autocomplete: "off", spellcheck: "false",
    placeholder: "Name or rules text", value: q.get("q") || "" });
  // Each typed filter has its own timer, so changing one doesn't drop the other's pending change.
  let searchTimer = 0, mvTimer = 0;
  search.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => colFilter(cv, "q", search.value.trim()), COL_TYPE_MS); });
  search.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !colKeyboardReady(cv, event) || event.target !== search
        || document.activeElement !== search) return;
    event.preventDefault();
    if (event.repeat) return;
    clearTimeout(searchTimer); colFilter(cv, "q", search.value.trim());
  });
  const mv = el("input", { id: id("mv"), type: "number", inputmode: "decimal", min: "0", step: "0.5", placeholder: "Any",
    value: q.get("mv") || "" });
  mv.addEventListener("input", () => { clearTimeout(mvTimer); mvTimer = setTimeout(() => colFilter(cv, "mv", mv.value.trim()), COL_TYPE_MS); });
  const field = (key, label, input) => el("label", { class: `field col-filter-${key}`, for: input.id }, el("span", { text: label }), input);
  const availability = colSegmented(COL_AVAILABILITY, q.get("availability") || "all",
    (v) => colFilter(cv, "availability", v === "all" ? "" : v), "Show");
  availability.classList.add("col-availability");
  cv.filterControls = { q: search, mv };
  // Casual widths keep the card filters folded; the button's count follows the current query. Identity
  // pips on results do not change this existing card-colour predicate (colourless lands can have identity).
  const form = el("form", { class: "filters col-filters", role: "search", "aria-label": "Filter the collection",
    onsubmit: (event) => event.preventDefault() });
  cv.filterCount = el("span", { class: "col-filter-count", "aria-hidden": "true" });
  const toggle = el("button", { type: "button", class: "btn col-filter-toggle", "aria-expanded": "false",
    "aria-controls": "col-filter-extra", onclick: () => {
      if (colActive(cv)) toggle.setAttribute("aria-expanded", String(form.classList.toggle("is-open")));
    } }, el("span", { class: "sr-only", text: "Filter cards" }),
    svgEl("svg", { viewBox: "0 0 20 20", width: 20, height: 20, "aria-hidden": "true", focusable: "false" },
      svgEl("path", { d: "M3 4h14l-5.5 6.5V16l-3-1.5v-4L3 4Z", fill: "none", stroke: "currentColor",
        "stroke-width": 1.6, "stroke-linejoin": "round" })), cv.filterCount);
  cv.filterToggle = toggle;
  colFindFilterCount(cv);
  add(form, [
    el("label", { class: "field col-filter-q", for: search.id }, el("span", { class: "sr-only", text: "Search" }), search),
    toggle,
    el("div", { class: "col-filter-row" }, availability),
    el("div", { id: "col-filter-extra", class: "col-filter-extra" },
      field("color", "Card colour", select("color", [["", "Any"], ["W", "White"], ["U", "Blue"], ["B", "Black"],
        ["R", "Red"], ["G", "Green"], ["C", "Colourless"]])),
      field("type", "Type", select("type", [["", "Any"], ...(data.types || []).map((v) => [v, v])])),
      field("role", "Role", select("role", [["", "Any"], ...(data.roles || []).map((v) => [v, capitalise(v)])])),
      field("mv", "Mana value", mv)),
    el("p", { class: "sub col-find-colour-note", text: "Colour filters use card colour; pips show colour identity." })]);
  return form;
}

/** Search and availability remain separate from the four extra filters counted on this button. */
function colFindFilterCount(cv) {
  if (!cv.filterToggle || !cv.filterCount) return;
  const count = ["color", "type", "role", "mv"].filter((key) => cv.query.get(key)).length;
  cv.filterCount.textContent = count ? String(count) : "";
  cv.filterCount.hidden = !count;
  cv.filterToggle.setAttribute("aria-label", `Filter cards${count ? `, ${count} active` : ""}`);
}

/** How many cards a page of Find cards shows: more on a wide screen. */
function colPageSize() {
  return typeof matchMedia === "function" && matchMedia("(min-width: 1000px)").matches ? 48 : 24;
}

/** One filter changed: back to page 1, the address follows (no new history entry), and the cards load. */
function colFilter(cv, key, value) {
  if (!colActive(cv)) return;
  const next = new URLSearchParams(cv.query);
  if (value) next.set(key, value); else next.delete(key);
  if (key !== "page") next.delete("page");
  if (next.toString() === cv.query.toString()) return;
  colLoadFind(cv, next, key === "page");
}

async function colLoadFind(cv, query, paging) {
  cv.query = query;
  colFindFilterCount(cv);
  history.replaceState(history.state, "", colHash(cv.space, "find", query));
  const seq = ++cv.findSeq;
  cv.results.setAttribute("aria-busy", "true");
  if (cv.findLoading && !cv.findLoading.firstChild) cv.findLoading.append(loadingBox("Loading cards…", { small: true }));
  try {
    const asked = new URLSearchParams(query);
    asked.set("limit", String(colPageSize()));
    const data = await api(colPath("/api/collection", cv.space, asked));
    if (!colActive(cv) || seq !== cv.findSeq) return;
    // A page past the end (an old address, a narrower screen's page size) comes back as the last page.
    if (Number.isInteger(data.page) && String(data.page) !== (query.get("page") || "1")) {
      cv.query = new URLSearchParams(query);
      if (data.page > 1) cv.query.set("page", String(data.page)); else cv.query.delete("page");
      history.replaceState(history.state, "", colHash(cv.space, "find", cv.query));
    }
    cv.data = { ...cv.data, ...data };
    drawCollectionResults(cv, data);
    if (paging) cv.results.scrollIntoView({ block: "start", behavior: "smooth" });
  } catch (error) {
    if (!colActive(cv) || seq !== cv.findSeq) return;
    clear(cv.results).append(errorBox("The cards couldn't be loaded", error, () => colLoadFind(cv, query, paging)));
  } finally {
    if (colActive(cv) && seq === cv.findSeq) {
      cv.results.removeAttribute("aria-busy");
      if (cv.findLoading) clear(cv.findLoading);
    }
  }
}

/** The count, the pagers and the grid of one page of cards. */
function drawCollectionResults(cv, data) {
  const cards = data.cards || [];
  const filtered = COL_FILTER_KEYS.some((key) => key !== "page" && cv.query.get(key));
  const go = (page) => colFilter(cv, "page", page > 1 ? String(page) : "");
  const counted = filtered ? `${plural(data.total || 0, "card name")} match` : plural(data.total || 0, "card name");
  clear(cv.results);
  add(cv.results, [
    warningsBox(data.warnings, "Collection counts need attention"),
    el("div", { class: "col-result-head" },
      el("p", { class: "result-count", role: "status", text: counted }),
      colPager(data.page, data.pages, go, "Pages, top")),
    cards.length ? [el("div", { class: "col-find-lab" },
      el("div", { class: "card-tiles col-tiles" }, cards.map((row) => colTile(cv, row)))),
      el("div", { class: "col-find-casual" }, colFindRows(cv, cards))] : colFindEmpty(cv, filtered, data.total || 0),
    colPager(data.page, data.pages, go, "Pages, bottom")]);
}

/** An empty page of Find cards: nothing matches, the page is past the cards (total > 0), or there are none. The
 * head's Add card stays the page's one primary button. */
function colFindEmpty(cv, filtered, total = 0) {
  if (total > 0) {
    return el("div", { class: "empty" }, el("p", { text: "No cards on this page." }),
      el("button", { type: "button", class: "btn", text: "Go to the first page", onclick: () => colFilter(cv, "page", "") }));
  }
  if (filtered) {
    return el("div", { class: "empty" }, el("p", { text: "No cards match these filters." }),
      el("a", { class: "btn", href: colHash(cv.space, "find"), text: "Clear the filters" }));
  }
  return el("div", { class: "empty" }, el("p", { text: "No cards recorded yet." }),
    cv.editable ? el("button", { type: "button", class: "btn col-mutate", text: "Add card",
      onclick: () => openCollectionSheet(cv) }) : null);
}

/** "3 owned · 2 free" (or "· all in decks"); "1 on the way" alone for a card with none owned yet. */
function colCountWords(row) {
  if (!row.owned) return row.incoming ? `${row.incoming} on the way` : "";
  if (row.basic || row.free_now == null) return `${row.owned} owned`;
  return `${row.owned} owned · ${row.free_now ? `${row.free_now} free` : "all in decks"}`;
}

/** One card of Find cards: its picture with ×N for the copies owned, one line of counts, and chips only for
 * what's worth noticing (on the way, a name the card data doesn't know). Its viewer words have the decks
 * that hold it and, where the visitor may change the collection, Edit copies. */
/** The same server-supplied count, basic-land and holder facts at both densities. */
function colFindCaption(cv, row) {
  return el("span", { class: "col-viewer-words" },
    el("span", { class: "col-viewer-counts", text: [row.owned ? `${row.owned} owned` : "None owned yet",
      !row.basic && row.owned && row.free_now != null ? `${row.free_now} free now` : null,
      row.incoming ? `${row.incoming} on the way` : null].filter(Boolean).join(" · ") }),
    row.basic ? el("span", { class: "col-viewer-note", text: "Special basic land: which deck uses it isn't tracked." }) : null,
    row.holders && row.holders.length ? el("span", { class: "col-viewer-decks" }, "In decks: ",
      row.holders.map((h, i) => [i ? ", " : "", `${h.quantity} in `, colViewerLink(deckHref(h.id), h.title)])) : null,
    cv.editable && row.owned ? el("button", { type: "button", class: "btn col-viewer-edit", text: "Edit copies",
      onclick: () => colAfterViewer(() => openCopiesSheet(cv, row.name)) }) : null);
}

/** Identity markers are presentation only; Find cards' colour query still matches card.colors. */
function colFindIdentity(card, size = 16) {
  const colours = deckColourPieces(card?.color_identity);
  return colours ? el("span", { class: "col-find-identity", role: "group", "aria-label": "Colour identity" }, colours.pips(size)) : null;
}

function colTile(cv, row) {
  const chips = [];
  if (row.incoming && row.owned) chips.push(status("info", `${row.incoming} on the way`));
  if (!row.card) chips.push(status("warn", "Name not matched"));
  const tile = cardTile(row.card || null, { qty: row.owned, name: row.name, meta: colCountWords(row) || null, chips,
    viewerGroup: "collection", caption: colFindCaption(cv, row),
    label: `${row.name}, ${colCountWords(row) || "none owned"}`,
    onclick: row.card ? null : (cv.editable ? () => openCopiesSheet(cv, row.name) : null) });
  add(tile, [colFindIdentity(row.card)]);
  return tile;
}

/** Casual Find cards is a name-level list, not a printing-level price or an allocation calculation. */
function colFindRows(cv, cards) {
  return el("ul", { class: "col-find-rows" }, cards.map((row) => {
    const caption = colFindCaption(cv, row), words = colCountWords(row) || "None owned";
    const extra = [row.incoming && row.owned ? `${row.incoming} on the way` : null,
      row.basic ? "Deck allocation not tracked" : null,
      !row.basic && !(row.owned && row.free_now === 0 && row.held === row.owned) && Number.isFinite(row.held) && row.held > 0 ? `${row.held} in decks` : null].filter(Boolean);
    const open = row.card ? (event) => { if (colActive(cv)) openCard(row.card, event.currentTarget); }
      : cv.editable ? () => openCopiesSheet(cv, row.name) : null;
    const node = el(open ? "button" : "div", { class: "col-find-open", type: open ? "button" : null,
      "aria-label": open ? `${row.name}, ${words}` : null, "aria-haspopup": open ? "dialog" : null, onclick: open },
      el("span", { class: row.card?.img_small ? "col-find-picture" : "col-find-picture thumb-missing", "aria-hidden": "true" }, row.card?.img_small
        ? el("img", { src: row.card.img_small, alt: "", loading: "lazy", decoding: "async", width: 56, height: 78 }) : null),
      el("span", { class: "col-find-heading" }, el("span", { class: "col-find-name", text: row.name }), colFindIdentity(row.card, 20)),
      el("span", { class: "col-find-count", text: `${row.owned || 0} owned` }),
      el("span", { class: "col-find-meta", text: [words, ...extra].join(" · ") }),
      row.card?.type_line ? el("span", { class: "col-find-type", text: row.card.type_line })
        : el("span", { class: "col-find-type" }, row.card ? "Type not recorded" : status("warn", "Name not matched")));
    if (row.card) viewerItem(node, row.card, "collection-find", caption);
    return el("li", { class: "col-find-row" }, node);
  }));
}

/** "Edit copies": the rows that hold a card (one per printing), each opening its sheet, and Add another
 * printing. */
async function openCopiesSheet(cv, name, opts = {}) {
  const repair = opts.repair;
  const allowed = () => colActive(cv) && !cv.busy && cv.editable && (!repair || repair.here());
  if (!allowed()) return;
  const sheet = colOpenSheet(`${name}: your copies`, { wide: true });
  const body = el("div", { class: "col-copies" }, loadingBox("Loading its rows…"));
  if (repair) sheet.body.append(boxCollectionNotice(repair.difference));
  sheet.body.append(body);
  sheetActions(sheet, [{ text: "Close", onclick: () => sheet.close() }]);
  try {
    if (repair) {
      const fresh = await api(colPath("/api/collection/rows", cv.space));
      if (!allowed() || sheet.closed) return;
      if (fresh?.editable !== true || fresh.space !== HOME_SPACE || !/^[a-f0-9]{64}$/.test(fresh.sha256 || "") || !boxCollectionRows(fresh.rows))
        throw new Error("The current collection rows couldn't be verified.");
      cv.sha256 = fresh.sha256; colTakeRows(cv, fresh);
      if (fresh.pictures) Object.assign(cv.pictures, fresh.pictures);
      const exact = await api(`/api/printings?name=${encodeURIComponent(name)}`);
      if (!allowed() || sheet.closed) return;
      if (!boxCollectionPrintings(exact, name)) throw new Error("The exact card name couldn't be matched.");
    } else await colEnsureRows(cv);
  } catch (error) {
    if (!sheet.closed && allowed()) clear(body).append(repair ? el("div", { class: "box box-crit", role: "alert" }, el("p", { text:
      "This card's copies couldn't be checked. Close this review and search Collection for the exact card name manually; no copies were changed." }))
      : loadFailed("Its rows", error, () => { if (!allowed()) return; sheet.close(); openCopiesSheet(cv, name, opts); }));
    return;
  }
  if (sheet.closed || !allowed()) return;
  const rows = (cv.rows || []).filter((r) => r.name === name);
  let opening = false;
  const open = (row) => {
    if (opening || sheet.closed || !allowed()) return;
    opening = true;
    if (repair) boxCollectionAfterSheet(sheet, allowed, () => openCollectionSheet(cv, row, { name, repair }));
    else { sheet.close(); openCollectionSheet(cv, row); }
  };
  add(clear(body), [
    rows.length ? el("div", { class: "col-copy-rows" }, rows.map((row) => cardRow(cv.pictures[colKey(row)] || null, {
      qty: Number(row.quantity), name: colPrinting(row), meta: colRowFacts(row) || "Condition and language recorded",
      aside: el("span", { class: "col-copy-edit", "aria-hidden": "true", text: "Edit" }),
      onclick: () => open(row) }))) : emptyBox(repair
        ? "No printing is recorded for this card. Count copies across every location before adding a printing."
        : "None of its rows are recorded here: it's only on the way.")]);
  // A row without a known card is a plain div: give it its own button.
  for (const [i, node] of [...body.querySelectorAll(".card-row")].entries()) {
    if (node.tagName !== "BUTTON") node.append(el("button", { type: "button", class: "btn", text: "Edit", onclick: () => open(rows[i]) }));
  }
  sheetActions(sheet, [
    { text: rows.length ? "Add another printing" : "Add a printing", kind: "primary", onclick: () => {
      if (repair) open(null);
      else { sheet.close(); openCollectionSheet(cv, null, { name }); }
    } },
    { text: "Close", onclick: () => sheet.close() }]);
}

/** "NM · English · binder 2", or "" when nothing is recorded; a row's unrecorded parts say so. */
function colRowFacts(row) {
  const language = COL_LANGUAGES.find(([v]) => v === row.language);
  return [row.condition || "Condition ?", row.language ? (language ? language[1] : row.language) : "Language ?",
    row.notes || null].filter(Boolean).join(" · ");
}


// ------------------------------------------------------------------ import

/** The text of a chosen file (FileReader, read here in the browser). */
function readImportFile(file) {
  if (file && typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("The file couldn't be read."));
    reader.readAsText(file);
  });
}

/** "Import cards": choose a .csv or .txt export, see what it adds (and its problems), then add it. */
function openImportSheet(cv) {
  if (!colActive(cv) || cv.busy || !cv.editable) return null;
  const sheet = colOpenSheet(`Import cards into ${colWhose(cv.space)}`, { wide: true });
  const ctx = { cv, sheet, preview: null, busy: false, seq: 0 };
  const input = el("input", { id: `col-file-${sheet.heading.id}`, type: "file", accept: ".csv,.txt,text/csv,text/plain",
    class: "col-file" });
  ctx.input = input;
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.area = el("div", { class: "col-import-preview" });
  input.addEventListener("change", async () => {
    if (ctx.busy) return;
    const selection = ++ctx.seq;
    ctx.preview = null;
    clear(ctx.area);
    sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() }]);
    const file = input.files && input.files[0];
    if (!file) return;
    if (file.size > COL_IMPORT_MAX) {
      clear(ctx.area);
      clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" },
        el("p", { text: "That file is more than 4 MB (about 20,000 rows of cards), too big to import at once. Check it's the right export, or split it into smaller files." })));
      return;
    }
    let text;
    try { text = await readImportFile(file); }
    catch (e) {
      if (selection === ctx.seq && !sheet.closed && colActive(cv)) clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: e.message })));
      return;
    }
    if (selection !== ctx.seq || sheet.closed || !colActive(cv)) return;
    previewImport(ctx, file.name, text);
  });
  sheet.body.append(
    el("p", { text: "A CSV export from ManaBox, Moxfield, Deckbox or the like. Nothing is added until you say so." }),
    el("label", { class: "field col-file-field", for: input.id }, el("span", { text: "File (.csv or .txt)" }), input),
    ctx.message, ctx.area);
  sheetActions(sheet, [{ text: "Cancel", value: "cancel", onclick: () => sheet.close() }]);
  return ctx;
}

/** Send the file's text for a preview and show it. */
async function previewImport(ctx, filename, text) {
  const cv = ctx.cv;
  if (ctx.busy || ctx.sheet.closed || !colActive(cv)) return;
  const seq = ++ctx.seq;
  ctx.source = { filename, text };
  ctx.preview = null;
  clear(ctx.area);
  clear(ctx.message).append(loadingBox(`Reading ${filename}…`));
  sheetActions(ctx.sheet, [{ text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() }]);
  try {
    const preview = await apiWrite("/api/collection/import/preview", { space: cv.space, filename, text });
    if (seq !== ctx.seq || ctx.sheet.closed || !colActive(cv)) return;
    ctx.preview = preview;
    clear(ctx.message);
    drawImportPreview(ctx);
  } catch (error) {
    if (seq !== ctx.seq || ctx.sheet.closed || !colActive(cv)) return;
    clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message })));
  }
}

function drawImportPreview(ctx) {
  const p = ctx.preview;
  const problems = p.problems || [];
  const bad = new Set(problems.map((x) => x.line));
  const rows = p.rows || [];
  const adds = p.adds || { rows: 0, cards: 0 };
  const skip = rows.filter((r) => bad.has(r.line)).length || problems.length;
  clear(ctx.area);
  add(ctx.area, [
    colRepeatImportWarning(p.repeat_imports),
    el("p", { class: "col-import-summary" }, p.format ? `Read as ${p.format}. ` : "",
      `${plural(adds.cards || 0, "card")} to add, in ${plural(adds.rows || 0, "row")}.`,
      p.dropped_basics ? ` ${plural(p.dropped_basics, "plain basic land")} left out (they aren't recorded).` : ""),
    problems.length ? el("div", { class: "box box-warn col-import-problems" },
      el("h3", { text: `${plural(problems.length, "problem")}` }),
      el("ul", {}, problems.map((x) => el("li", { text: x.line ? `Line ${x.line}: ${x.message}` : x.message })))) : null,
    rows.length ? el("div", { class: "col-import-table" }, el("table", { class: "data" },
      el("thead", {}, el("tr", {}, ["Line", "Qty", "Name", "Printing", "Condition", "Language"].map((h) => el("th", { scope: "col", text: h })))),
      el("tbody", {}, rows.map((r) => el("tr", { class: bad.has(r.line) ? "col-problem" : null },
        el("td", { text: r.line != null ? String(r.line) : "" }), el("td", { class: "num", text: String(r.quantity ?? "") }),
        el("td", { text: r.name || "" }), el("td", { text: colPrinting(r) }),
        el("td", { text: r.condition || "–" }), el("td", { text: r.language || "–" })))))) : null]);
  const cards = adds.cards || 0;
  const actions = [{ text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() }];
  if (cards > 0 && !problems.length) {
    actions.push({ text: `Import ${plural(cards, "card")}`, kind: "primary", value: "import", onclick: () => applyImport(ctx, false) });
  } else if (cards > 0) {
    actions.push({ text: `Skip ${plural(skip, "row")} with problems and import ${plural(cards, "card")}`, kind: "primary",
      value: "import", onclick: () => applyImport(ctx, true) });
    ctx.area.append(el("p", { class: "sub", text: "Or fix the file and choose it again to import every row." }));
  } else {
    ctx.area.append(emptyBox("There's nothing in this file to add.", el("button", { type: "button", class: "btn",
      text: "Choose another file", onclick: () => { if (!ctx.busy && !ctx.sheet.closed) ctx.input.click(); } })));
  }
  sheetActions(ctx.sheet, actions);
}

async function applyImport(ctx, skipProblems) {
  const cv = ctx.cv;
  if (ctx.busy || ctx.sheet.closed || !ctx.preview || !colActive(cv)) return;
  const reviewed = ctx.preview, selection = ctx.seq;
  ctx.busy = true;
  ctx.input.disabled = true;
  for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = true;
  clear(ctx.message).append(loadingBox("Importing…"));
  try {
    await colEnsureRows(cv);
    if (ctx.sheet.closed || !colActive(cv) || selection !== ctx.seq || ctx.preview !== reviewed) {
      ctx.busy = false; ctx.input.disabled = false; return;
    }
    const body = { space: cv.space, token: reviewed.token, sha256: cv.sha256 };
    if (skipProblems) body.skip_problems = true;
    const answer = await apiWrite("/api/collection/import/apply", body);
    const added = answer.added || { rows: 0, cards: 0 };
    ctx.sheet.close();
    cv.rows = null;                     // the answer has no rows: the next write fetches them again
    if (answer.sha256) cv.sha256 = answer.sha256;
    state.library = null;
    const words = `Imported ${plural(added.cards || 0, "card")} (${plural(added.rows || 0, "row")}).`
      + (answer.skipped ? ` ${plural(answer.skipped, "row")} with problems skipped.` : "");
    if (colActive(cv)) colReload(cv, words, answer.stale_tables);
    else if (state.profile?.id === cv.profile) toast(words);
  } catch (error) {
    if (ctx.sheet.closed || !colActive(cv)) return;
    ctx.busy = false;
    ctx.input.disabled = false;
    if (error.status === 409 && error.data?.repreview_required) {
      ctx.preview = null;
      clear(ctx.area);
      clear(ctx.message).append(el("p", { class: "box box-warn", text: error.message }));
      sheetActions(ctx.sheet, [{ text: "Cancel", onclick: () => ctx.sheet.close() },
        { text: "Preview again", kind: "primary", onclick: () => previewImport(ctx, ctx.source.filename, ctx.source.text) }]);
      return;
    }
    if (error.status === 409 && error.data && error.data.sha256) {
      // Someone changed the collection meanwhile: the import only adds, so it can go on top of the latest.
      cv.sha256 = error.data.sha256;
      if (Array.isArray(error.data.rows)) colTakeRows(cv, error.data);
      clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" }, el("p", { text: error.message }),
        el("p", { text: "Nothing was imported yet. The import only adds cards, so it can go on top of the latest list." })));
      sheetActions(ctx.sheet, [{ text: "Cancel", onclick: () => ctx.sheet.close() }, { text: "Import into the latest list",
        kind: "primary", value: "import", onclick: () => applyImport(ctx, skipProblems) }]);
      return;
    }
    clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message })));
    for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = false;
  }
}


// ------------------------------------------------------------------ precons

const PRECON_SEARCH_MS = 250;       // wait this long after typing before searching

/** "Add a precon": find a published precon (MTGJSON's lists), see its cards, then add them to this
 * collection and make its built deck, in one save (lib/api/precons.py). */
function openPreconSheet(cv) {
  if (!colActive(cv) || cv.busy || !cv.editable) return null;
  const whose = colWhose(cv.space);
  const sheet = colOpenSheet(`Add a precon to ${whose}`, { wide: true, onClose: () => clearTimeout(ctx.timer) });
  const ctx = { cv, sheet, whose, seq: 0, busy: false, preview: null, timer: null };
  const input = el("input", { id: `precon-q-${sheet.heading.id}`, type: "search", autocomplete: "off",
    placeholder: "Deck or set name" });
  ctx.query = input;
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.area = el("div", { class: "precon-area" });
  ctx.back = { text: "← Back to the list", value: "back", onclick: () => backToPrecons(ctx) };
  input.addEventListener("input", () => {
    clearTimeout(ctx.timer);
    ctx.timer = setTimeout(() => searchPrecons(ctx), PRECON_SEARCH_MS);
  });
  ctx.searchField = el("div", { class: "precon-search-area" },
    el("p", { class: "sub", text: "Its cards go into the collection and its list becomes a built deck, in one go."
      + (cv.space === HOME_SPACE ? ` A product bought through a recorded order arrives through ${routeFor("shopping").label} (${routeFor("receipt").label}) instead.` : "") }),
    el("label", { class: "field precon-search", for: input.id }, el("span", { class: "sr-only", text: "Find a precon" }), input));
  add(sheet.body, [ctx.searchField, ctx.message, ctx.area]);
  sheetActions(sheet, [{ text: "Cancel", value: "cancel", onclick: () => sheet.close() }]);
  searchPrecons(ctx);
  input.focus();
  return ctx;
}

function backToPrecons(ctx) {
  clearTimeout(ctx.timer);
  ctx.preview = null;
  ctx.searchField.hidden = false;
  ctx.sheet.heading.textContent = `Add a precon to ${ctx.whose}`;
  sheetActions(ctx.sheet, [{ text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() }]);
  searchPrecons(ctx);
  ctx.query.focus();
}

/** Whether a deck's source is a page on Wizards' own site (lib/precons.py, from_wizards). */
function fromWizards(source) {
  try { return /(^|\.)wizards\.com$/i.test(new URL(source).hostname); } catch (e) { return false; }
}

async function searchPrecons(ctx) {
  if (ctx.sheet.closed || ctx.preview || ctx.searchField.hidden) return;   // a search typed just before a pick
  const seq = ++ctx.seq;
  const q = ctx.query.value.trim();
  clear(ctx.message).append(loadingBox("Finding precons…"));
  try {
    const answer = await api(`/api/precons?${new URLSearchParams({ q })}`);
    if (seq !== ctx.seq || ctx.sheet.closed) return;
    clear(ctx.message);
    const decks = answer.decks || [];
    add(clear(ctx.area), [
      decks.length ? el("ul", { class: "precon-list" }, decks.map((d) => el("li", {},
        el("button", { type: "button", class: "precon-pick", onclick: () => previewPrecon(ctx, d) },
          el("span", { class: "precon-pick-words" }, el("strong", { text: d.name }),
            el("small", { text: [d.set_name || d.code.toUpperCase(), d.type].filter(Boolean).join(" · ") })),
          d.released ? el("small", { class: "precon-pick-date", text: String(d.released).slice(0, 4) }) : null))))
        : emptyBox(q
          ? "No precon matches that. Only decks whose list has been published are here."
          : "No precons are listed.", null, { live: !!q }),
      answer.more ? el("p", { class: "result-count", text: "More match: type more of the name to narrow the list." }) : null,
      el("p", { class: "result-count", text: `Lists from MTGJSON${answer.date ? ` (updated ${answer.date})` : ""}, most from Wizards' published lists.` })]);
  } catch (error) {
    if (seq !== ctx.seq || ctx.sheet.closed) return;
    clear(ctx.message).append(loadFailed("The list of precons", error, () => searchPrecons(ctx)));
  }
}

async function previewPrecon(ctx, deck, keptTitle = null) {
  const cv = ctx.cv;
  clearTimeout(ctx.timer);            // a search typed just before the pick would cover the preview
  const seq = ++ctx.seq;
  ctx.preview = null;
  clear(ctx.area);
  ctx.searchField.hidden = true;
  ctx.sheet.heading.textContent = deck.name;
  clear(ctx.message).append(loadingBox(`Reading ${deck.name}…`));
  sheetActions(ctx.sheet, [ctx.back]);
  try {
    const params = new URLSearchParams({ file: deck.file });
    if (cv.space !== HOME_SPACE) params.set("space", cv.space);
    const preview = await api(`/api/precons/preview?${params}`);
    if (seq !== ctx.seq || ctx.sheet.closed || !colActive(cv)) return;
    ctx.preview = preview;
    ctx.keptTitle = keptTitle;
    clear(ctx.message);
    drawPreconPreview(ctx);
  } catch (error) {
    if (seq !== ctx.seq || ctx.sheet.closed || !colActive(cv)) return;
    clear(ctx.message).append(loadFailed(deck.name, error, () => previewPrecon(ctx, deck, keptTitle)));
  }
}

/** One card of a precon's list, as the deck's text writes it. */
function preconLine(c) {
  const finish = c.finish === "foil" ? " *F*" : c.finish === "etched" ? " *E*" : "";
  return `${c.qty} ${c.name}${c.set ? ` (${c.set.toUpperCase()}) ${c.number}${finish}` : ""}`;
}

function drawPreconPreview(ctx) {
  const p = ctx.preview;
  const d = p.deck;
  const counts = p.counts || {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const leftOut = Object.entries(p.left_out || {}).map(([what, n]) => plural(n, what));
  const adds = p.adds || { rows: 0, cards: 0 };
  const titleInput = el("input", { id: `precon-title-${ctx.sheet.heading.id}`, type: "text", maxlength: "100", value: ctx.keptTitle ?? p.title });
  ctx.keptTitle = null;
  ctx.titleInput = titleInput;
  ctx.titleNote = el("p", { class: "field-problem precon-title-note", role: "status" });
  const sayTaken = () => {
    ctx.titleNote.textContent = p.exists && titleInput.value.trim() === p.title
      ? `There's already a deck with this title (${p.exists}): pick another.` : "";
  };
  titleInput.addEventListener("input", sayTaken);
  sayTaken();
  const lists = p.lists || {};
  const tile = (c, section) => cardTile(c.card || null, { qty: c.qty, name: c.name,
    meta: c.set ? `${c.set.toUpperCase()} ${c.number}` : "Any printing", finish: c.finish,
    viewerGroup: "precon", caption: `${section === "Deck" ? "" : `${section} · `}${preconLine(c)}` });
  clear(ctx.area);
  add(ctx.area, [
    el("p", { class: "sub precon-meta" }, [d.set_name || d.code.toUpperCase(), d.type, d.released ? `released ${d.released}` : null].filter(Boolean).join(" · "),
      d.source ? [" · ", el("a", { href: d.source, target: "_blank", rel: "noopener noreferrer",
        text: fromWizards(d.source) ? "Wizards' list" : "Where the list is from" })] : null),
    el("p", { class: "precon-summary" }, `${p.kind === "commander" ? "Commander deck" : "60-card deck"} · ${plural(total, "card")}. `,
      el("b", { text: `${plural(adds.cards || 0, "card")} go into ${ctx.whose}` }),
      p.dropped_basics ? ` (plain basic lands left out)` : "", "."),
    p.problems && p.problems.length ? el("div", { class: "box box-warn" },
      el("h3", { text: "It can't be added yet" }),
      el("p", { text: "Deck Lab can't match these cards to Scryfall's data, usually because the set is too new. Try again once the card data has caught up (it updates weekly)." }),
      el("ul", {}, p.problems.slice(0, 20).map((x) => el("li", { text: x.message })))) : null,
    p.deck_problems && p.deck_problems.length ? el("div", { class: "box box-warn" },
      el("h3", { text: "Its list can't be made into a deck" }),
      el("ul", {}, p.deck_problems.slice(0, 20).map((x) => el("li", { text: x.message })))) : null,
    el("label", { class: "field precon-title", for: titleInput.id }, el("span", { text: "Deck title" }), titleInput),
    ctx.titleNote,
    leftOut.length || (p.tokens && p.tokens.length) ? el("p", { class: "sub" },
      leftOut.length ? `Not added: ${leftOut.join(", ")}. ` : "",
      !p.token_import && p.tokens && p.tokens.length ? ["Its token cards (", p.tokens.map((t) => `${t.count} ${t.name}`).join(", "),
        ") aren't added: record them on the ", el("a", { href: "#/tokens", text: "Tokens page" }), " once checked."] : null) : null,
    preconTokenChoice(ctx),
    Object.entries(lists).map(([section, lines]) => el("section", { class: "precon-section" },
      el("h3", { text: `${section === "Deck" ? "Deck" : section} (${num(counts[section] || 0)})` }),
      el("div", { class: "card-tiles precon-tiles" }, lines.map((c) => tile(c, section)))))]);
  if (!p.editable) ctx.area.append(el("p", { class: "box box-info", text: "You can't add cards and decks here." }));
  sheetActions(ctx.sheet, [ctx.back,
    p.ready && p.editable ? { text: `Add ${d.name}`, kind: "primary", value: "add", onclick: event => {
      if (preconAddHere(ctx, p, event.currentTarget)) addPrecon(ctx);
    } } : null]);
}

function preconAddHere(ctx, preview, button) {
  return ctx.preview === preview && !ctx.sheet.closed && button?.isConnected && ctx.sheet.foot.contains(button)
    && [...document.querySelectorAll("dialog[open]")].at(-1) === ctx.sheet.dialog;
}

async function addPrecon(ctx) {
  const cv = ctx.cv;
  const p = ctx.preview;
  if (ctx.busy || ctx.sheet.closed || !p || !p.ready || !p.editable || !cv.editable || !canEditSpace(cv.space)
      || !colActive(cv) || ctx.tokenPreviewStale) return;
  const tokensChosen = ctx.tokenChoice?.node.checked === true;
  const tokenReview = ctx.tokenChoice, tokenSelection = tokensChosen ? preconTokenSelection(ctx) : null;
  if (tokensChosen && !tokenSelection) return;
  const requestHash = location.hash;
  const title = ctx.titleInput.value.trim();
  if (!title) { ctx.titleNote.textContent = "The deck needs a title."; ctx.titleInput.focus(); return; }
  ctx.busy = true;
  preconTokensBusy(ctx, true);
  for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = true;
  clear(ctx.message).append(loadingBox(`Adding ${p.deck.name}…`));
  try {
    const answer = await apiWrite("/api/precons/add", { space: cv.space, file: p.deck.file, title, sha256: p.sha256,
      ...(tokensChosen ? { add_tokens: true, tokens_sha256: tokenSelection.offer.sha256,
        tokens_source_sha256: tokenSelection.offer.source_sha256,
        ...(tokenSelection.choices ? { tokens_choices: tokenSelection.choices } : {}) } : {}) });
    cv.rows = null;
    state.library = null; // The confirmed write stands even if its review is no longer the current UI.
    if (ctx.sheet.closed || !colActive(cv) || ctx.preview !== p || requestHash !== location.hash
        || tokensChosen && !preconTokenOwner(ctx, tokenReview)) return;
    const added = answer.collection && answer.collection.added;
    ctx.sheet.close();
    // The deck page's box about a new deck (editor-deckpage.js, savedBox), as the editor's Create leaves it:
    // warnings (no sleeves yet, the deck rules) and other decks' tables now out of date.
    const hash = deckHref(answer.deck.id, "target");
    const tokenCount = tokensChosen && answer.tokens?.cards === tokenSelection.cards && answer.tokens?.rows === tokenSelection.rows
      ? tokenSelection.cards : null;
    state.saved = { hash, profile: state.profile?.id, version: "target", mode: "new", answer: { ...answer.deck,
      precon: { name: p.deck.name, whose: ctx.whose, cards: added ? added.cards : 0,
        ...(tokensChosen ? { tokens: tokenCount, tokens_uncertain: tokenCount === null } : {}) } } };
    state.scroll.delete(hash);        // open the deck at the top, where the box is
    toast("");                        // an older note would cover the box
    location.hash = hash;
  } catch (error) {
    if (error.status >= 500 || !error.data) { cv.rows = null; state.library = null; }
    if (ctx.sheet.closed || !colActive(cv) || ctx.preview !== p || requestHash !== location.hash
        || tokensChosen && !preconTokenOwner(ctx, tokenReview)) return;
    ctx.busy = false;
    preconTokensBusy(ctx, false);
    for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = false;
    const data = error.data || {};
    if (error.status >= 500 || !error.data) {
      // No answer of Deck Lab's own (no connection, a proxy's error page), or an unexpected failure: the
      // save may have gone in, and adding again would add the cards twice.
      cv.rows = null;
      state.library = null;
      ctx.tokenPreviewStale = true;
      preconTokensBusy(ctx, true);
      clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message }),
        el("p", { text: `It isn't known whether its cards went into ${ctx.whose}. Look there (and on the Decks page${tokensChosen ? " and Tokens page" : ""}) before adding it again.` })));
      sheetActions(ctx.sheet, [{ text: "Close", kind: "primary", value: "close",
        onclick: () => { ctx.sheet.close(); if (colActive(cv)) colReload(cv, error.message); } }]);
      return;
    }
    if (error.status === 409 && (data.token_conflict || tokensChosen && data.sha256)) {
      ctx.tokenPreviewStale = true;
      preconTokensBusy(ctx, true);
      clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" }, el("p", { text: error.message }),
        el("p", { text: "Nothing was added. Preview again to review the current collection and token list, then choose whether to add the token cards." })));
      sheetActions(ctx.sheet, [ctx.back, { text: "Preview again", kind: "primary", onclick: () => {
        if (!ctx.sheet.closed && colActive(cv) && !ctx.busy && ctx.preview === p) previewPrecon(ctx, p.deck, ctx.titleInput.value.trim());
      } }]);
      return;
    }
    if (error.status === 409 && data.sha256) {
      // The collection changed since the preview: a precon only adds, so it can go on top of the latest.
      p.sha256 = cv.sha256 = data.sha256;
      if (Array.isArray(data.rows)) colTakeRows(cv, data);
      clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" }, el("p", { text: error.message }),
        el("p", { text: "Nothing was added yet. A precon only adds cards, so it can go on top of the latest list." })));
      sheetActions(ctx.sheet, [ctx.back, { text: "Add to the latest list", kind: "primary", value: "add", onclick: event => {
        if (preconAddHere(ctx, p, event.currentTarget)) addPrecon(ctx);
      } }]);
      return;
    }
    const problems = data.problems || (data.blocks || []).map((b) => ({ message: b.problem }));
    clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message }),
      problems.length ? el("ul", {}, problems.slice(0, 20).map((x) => el("li", { text: x.message }))) : null));
    // Nothing was saved: the cards and the deck go in together or not at all.
    if (error.status === 409 && data.conflict) {
      ctx.titleInput.focus();
    }
  }
}
