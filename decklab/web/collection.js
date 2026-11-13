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
 * added in one change. "Add a precon" (precon-add.js, lib/api/precons.py)
 * finds a published precon, previews its cards, then adds them and makes its built deck in one go.
 * "Scan cards" (collection-scan.js) reads photos of cards on the PC into a pending list for the import preview.
 * "Record a trade" (collection-trade.js) saves the copies that left and the cards that came in as one change.
 * "Storage setup" (storage-setup.js) says where the space's loose cards are kept (E8-S25).
 * "Precons we could build" (precon-coverage.js) ranks precons by how much of each the free pool covers, and
 * "Commanders we could build" (commander-candidates.js) the free commanders by the role targets it covers. */
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
const COL_AVAILABILITY = [["all", "All"], ["free", "Free now"], ["incoming", "On the way"], ["held", "In decks"], ["spare", "Spare"]];
const COL_IMPORT_MAX = 4 * 1024 * 1024;     // bytes: the server's limit (collection_edit.MAX_IMPORT; 20,000 rows)
const COL_NOTES_MAX = 500;
const COL_ROWS_PAGE = 100;                  // Card list rows a page
const COL_TYPE_MS = 250;                    // wait this long after typing before filtering
const COL_STRIP_FILTER = 12;                // more printings than this: the strip gets a "Find a set" box
const COL_SORTS = { name: "Card", set: "Printing", quantity: "Copies", price: "~A$ each", condition: "Condition",
  language: "Language" };
/** A sort's heading; the price's names the configured currency ("~A$ each", "~€ each", E11-S53) when drawn. */
/** A column's words; the price column's in the saved prices answer's currency (ansSign: A$ until one says otherwise). */
function colSortWords(key, prices = null) { return key === "price" ? `~${ansSign(prices)} each` : COL_SORTS[key]; }
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
  // An older or hand-typed colour (card colour's single letters, another letter order) still loads.
  if (query.has("color")) { const color = colIdentityValue(query.get("color")); if (color) query.set("color", color); else query.delete("color"); }
  const asked = new URLSearchParams(query);
  asked.set("limit", String(colPageSize()));
  const open = params.get("open");
  return load(colPath("/api/collection", space, asked), token, (data) => colOpenAsked(drawCollection(data, query, space, token), open));
}

/** #/collection?open=precon or ?open=import, the empty library's ways to start (E11-S56): that sheet, once, where the
 * visitor may change this collection, after load() has focused the page; the address loses ?open= first, so
 * Back or a reload doesn't reopen it. */
function colOpenAsked(cv, open) {
  if (open) setTimeout(() => {
    if (!colActive(cv)) return;
    history.replaceState(history.state, "", colHash(cv.space, "find", cv.query));
    const sheet = { precon: openPreconSheet, import: openImportSheet }[open];
    if (sheet && cv.editable && !cv.unsupported) sheet(cv);
  });
}

/** What a page of the collection holds for its writes: cv ("collection view"). */
function colView(data, space, token, kind) {
  const { storage_forecast: forecast, ...viewData } = data;
  const cv = { token: token == null ? routeToken : token, profile: state.profile && state.profile.id, space, kind,
    forecastProfile: state.profile, forecastHash: location.hash,
    data: viewData, busy: false, seq: 0,
    // A server that doesn't know spaces yet answers with home's cards and no "space": a person's isn't shown.
    unsupported: space !== HOME_SPACE && data.space === undefined,
    editable: data.editable === true && (data.space === undefined || data.space === space),
    sha256: data.sha256 || null, rows: Array.isArray(data.rows) ? data.rows : null,
    pictures: data.pictures && typeof data.pictures === "object" ? { ...data.pictures } : {},
    prices: colPrices(data.prices),
    storage: colStorage(data.storage), locations: colLocations(data.locations), storageBoxCount: data.storage_box || null,
    storageSetup: colStorageSetup(data.storage_setup),
    message: el("div", { class: "col-message", role: "status", "aria-live": "polite" }) };
  cv.storageForecast = colStorageForecast(forecast, cv);
  return cv;
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

/** A row's estimate in the configured currency (its own printing and finish), or null when there's none. */
function colPrice(cv, row) {
  const p = cv.prices && cv.prices.rows[colKey(row)];
  return p && typeof p.aud === "number" ? p.aud : null;
}

/** A 409's latest rows (collection_edit._stale), with their prices so new rows aren't shown unpriced. */
function colTakeRows(cv, data) {
  cv.rows = data.rows;
  if (data.prices) cv.prices = colPrices(data.prices);
  cv.storage = data.storage ? colStorage(data.storage) : colWithoutHints(cv.storage);
  colTakeLocations(cv, data);
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
 * More (Import cards, Scan cards, Add a precon, Precons we could build, Commanders we could build, Record a trade, Loans, Storage setup, Download), then the space picker and Find cards / Card list. */
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
    cv.editable && !cv.unsupported ? { label: "Scan cards…", onclick: () => openScanSheet(cv) } : null,
    cv.editable ? { label: "Add a precon…", onclick: () => openPreconSheet(cv) } : null,
    cv.unsupported ? null : { label: "Precons we could build…", onclick: () => openCoverageSheet(cv) },
    cv.unsupported ? null : { label: "Commanders we could build…", onclick: () => openCommanderCandidates(cv) },
    cv.editable && !cv.unsupported ? { label: "Record a trade…", onclick: () => openTradeSheet(cv) } : null,
    cv.editable && !cv.unsupported ? { label: "Loans…", onclick: () => openCollectionLoans(cv) } : null,
    cv.editable && !cv.unsupported ? { label: "Storage setup…", onclick: () => openStorageSetup(cv) } : null,
    cv.unsupported ? null : { label: "Download collection (CSV)", onclick: () => downloadCollection(cv) },
    typeof memberOwnSpace === "function" && memberOwnSpace() && cv.space === ownSpace()
      ? { label: "Download my space (zip)", onclick: () => downloadMemberSpace(cv) } : null];
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
  if (cv.kind === "rows") {
    colLocationFiltersSync(cv);
    colLocationBatchSync(cv, colShownRows(cv));
  }
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
  const profile = state.profile, profileId = cv.profile, token = cv.token;
  const hash = location.hash, root = cv.root, revision = cv.forecastRevision || 0;
  const pending = cv.rowsPending;
  if (pending && pending.profile === profile && pending.hash === hash && pending.root === root
      && pending.revision === revision && pending.token === token && pending.profileId === profileId) return pending.promise;
  const request = { profile, profileId, token, hash, root, revision };
  const here = () => colActive(cv) && state.profile === profile && profile.id === profileId && cv.profile === profileId
    && cv.token === token && cv.root === root && location.hash === hash;
  const ready = () => typeof cv.sha256 === "string" && Boolean(cv.sha256) && Array.isArray(cv.rows);
  const moved = () => new Error("The collection view changed. Reload its rows before continuing.");
  request.promise = (async () => {
    let data;
    try { data = await api(colPath("/api/collection/rows", cv.space)); }
    catch (error) {
      if (!colForecastAllowed(cv)) { cv.storageForecast = null; drawColStorageForecast(cv); }
      if (here() && revision !== (cv.forecastRevision || 0) && ready()) return;
      if (!here()) throw moved();
      throw error;
    }
    if (!here()) {
      cv.storageForecast = null; drawColStorageForecast(cv); throw moved();
    }
    if (revision !== (cv.forecastRevision || 0)) {
      if (ready()) return; // a newer saved/checked rows answer is already authoritative
      throw moved();
    }
    if (typeof data?.sha256 !== "string" || !data.sha256 || !Array.isArray(data.rows))
      throw new Error("The current collection rows could not be verified. Reload before continuing.");
    cv.sha256 = data.sha256; cv.rows = data.rows;
    if (data.pictures) Object.assign(cv.pictures, data.pictures);
    if (data.prices) cv.prices = colPrices(data.prices);
    if (data.storage) cv.storage = colStorage(data.storage);
    colTakeLocations(cv, data);
  })();
  cv.rowsPending = request;
  try { await request.promise; }
  finally { if (cv.rowsPending === request) cv.rowsPending = null; }
}

/** After a change: the new rows, and the view drawn again (Find cards loads its page again). */
function colChanged(cv, answer, words, filing = null) {
  if (answer && answer.sha256) cv.sha256 = answer.sha256;
  if (answer && Array.isArray(answer.rows)) cv.rows = answer.rows;
  if (answer && answer.pictures) Object.assign(cv.pictures, answer.pictures);
  if (answer && answer.prices) cv.prices = colPrices(answer.prices);
  cv.storage = answer && answer.storage ? colStorage(answer.storage) : colWithoutHints(cv.storage);
  colTakeLocations(cv, answer);
  invalidateLibrary();               // the library's missing-card counts come from the collection
  if (!colActive(cv)) { if (words && state.profile?.id === cv.profile) toast(words); return; }
  if (cv.kind === "rows") {
    drawColRowList(cv);
    colSay(cv, words, answer && answer.stale_tables);
    if (filing) add(cv.message, [colFilingGuide(cv, filing)]);
    setCollectionBusy(cv, false);
    return;
  }
  colReload(cv, words, answer && answer.stale_tables, filing);
}

/** Load the view again from the server, then say what happened there: the Find cards counts, or the Card
 * list after an import, come from the server. */
function colReload(cv, words, stale, filing = null) {
  state.colNotice = { space: cv.space, profile: cv.profile, words, stale, filing };
  route();
}

/** The message a change left for the view drawn after it (colReload), once. */
function colTakeNotice(cv) {
  const notice = state.colNotice;
  state.colNotice = null;
  if (notice && notice.space === cv.space && (!notice.profile || notice.profile === cv.profile) && notice.words) {
    colSay(cv, notice.words, notice.stale);
    if (notice.filing) add(cv.message, [colFilingGuide(cv, notice.filing)]);
  }
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
    placeholder: "Name or rules text", value: q.get("q") || "",
    title: 'Name or rules text. o: searches rules, t: searches type; -o: and -t: leave matches out. Mana value: mv<=2, mv>=5 or mv=3.' });
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
  // Casual widths keep the card filters folded; the button's count follows the current query. The colour
  // filter matches colour identity, as the result pips show it (E11-S30 question 6, Matt 2026-10-31).
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
      field("color", "Colour identity", select("color", colIdentityChoices())),
      field("type", "Type", select("type", [["", "Any"], ...(data.types || []).map((v) => [v, v])])),
      field("role", "Role", select("role", [["", "Any"], ...(data.roles || []).map((v) => [v, capitalise(v)])])),
      field("mv", "Mana value", mv)),
    el("p", { class: "sub col-find-colour-note",
      text: "Colour identity, as the pips show it: cards within the chosen colours, colourless ones included." }),
    el("p", { class: "sub col-find-search-note", text: 'Search terms: o:"draw a card", t:creature, -o:discard, -t:land; mana value mv<=2, mv>=5 or mv=3.' })]);
  return form;
}

/** The colour identity choices: any, "within" each of the 31 colour sets (singles first, WUBRG order) and
 * colourless only. A card fits when its identity is within the choice, as for a Commander deck's colours. */
function colIdentityChoices() {
  const choices = [["", "Any"]];
  for (let size = 1; size <= 5; size++) {
    for (let mask = 1; mask < 32; mask++) {
      const colors = [..."WUBRG"].filter((_, index) => mask & (1 << index));
      if (colors.length === size) choices.push([colors.join(""), `Within ${colors.map((c) => capitalise(COLOUR_WORDS[c])).join(" + ")}`]);
    }
  }
  return [...choices, ["C", "Colourless only"]];
}

/** A colour query in the choices' WUBRG order, "C", or "" for anything else (never a refused request). */
function colIdentityValue(value) {
  const letters = String(value || "").trim().toUpperCase();
  if (letters === "C") return "C";
  if (!/^[WUBRG]{1,5}$/.test(letters) || new Set(letters).size !== letters.length) return "";
  return [..."WUBRG"].filter((c) => letters.includes(c)).join("");
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
    const { storage_forecast, ...pageData } = data;
    cv.data = { ...cv.data, ...pageData };
    colTakeLocations(cv, data);
    drawCollectionResults(cv, data);
    if (paging) cv.results.scrollIntoView({ block: "start", behavior: scrollBehaviour() });
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
  const counted = data.spares?.ready === false ? "Spare copies unavailable"
    : filtered ? `${plural(data.total || 0, "card name")} match` : plural(data.total || 0, "card name");
  clear(cv.results);
  add(cv.results, [
    warningsBox(data.warnings, "Collection counts need attention"),
    el("div", { class: "col-result-head" },
      el("p", { class: "result-count", role: "status", text: counted }),
      data.spares?.ready && data.spares.copy?.text && ownSpace() === cv.space && seesInventory(cv.space) ? el("button", {type: "button", class: "btn btn-quiet col-spare-copy", text: "Copy list",
        onclick: event => colCopySpares(cv, data, event.currentTarget)}) : null,
      colPager(data.page, data.pages, go, "Pages, top")),
    data.spares ? el("p", {class: data.spares.ready ? "sub col-spare-note" : "box box-warn col-spare-note", role: "status",
      text: data.spares.message || data.spares.note || "Spare copies couldn't be confirmed."}) : null,
    cards.length ? [el("div", { class: "col-find-lab" },
      el("div", { class: "card-tiles col-tiles" }, cards.map((row) => colTile(cv, row)))),
      el("div", { class: "col-find-casual" }, colFindRows(cv, cards))] : data.spares?.ready === false ? null : colFindEmpty(cv, filtered, data.total || 0),
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
  const ways = cv.editable && !cv.unsupported ? [
    ["Import cards", openImportSheet, "Bring in a collection export."],
    ["Add a precon", openPreconSheet, "Add an opened precon's cards and deck."],
    ["Scan cards", openScanSheet, "Review photos of your cards."],
    ["Add one card", openCollectionSheet, "Choose a card and its printing."]
  ] : [];
  return el("div", { class: "empty lib-start" }, el("p", { text: ways.length ? "No cards recorded yet. Start with one of these:" : "No cards recorded yet." }),
    ways.length ? el("ul", {class: "lib-start-ways"}, ways.map(([text, open, line]) => el("li", {},
      el("button", {type: "button", class: "btn col-mutate", text, onclick: event => {
        if (event.currentTarget.isConnected && colActive(cv) && !cv.busy) open(cv);
      }}), el("span", {class: "lib-start-line", text: line})))) : null);
}

/** "3 owned · 2 free" (or "· all in decks"); "1 on the way" alone for a card with none owned yet. */
function colCountWords(row) {
  if (Number.isSafeInteger(row.spares?.spare) && row.spares.spare > 0) return `${row.spares.spare} spare`;
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
    row.spares ? el("span", {class: "col-viewer-note", text: row.spares.reason
      + (row.spares.printing_uncertain ? " Printing assignment is unconfirmed; check the deck boxes." : "")}) : null,
    row.basic ? el("span", { class: "col-viewer-note", text: "Special basic land: which deck uses it isn't tracked." }) : null,
    row.holders && row.holders.length ? el("span", { class: "col-viewer-decks" }, "In decks: ",
      row.holders.map((h, i) => [i ? ", " : "", `${h.quantity} in `, colViewerLink(deckHref(h.id), h.title)])) : null,
    cv.editable && row.owned ? el("button", { type: "button", class: "btn col-viewer-edit", text: "Edit copies",
      onclick: () => colAfterViewer(() => openCopiesSheet(cv, row.name)) }) : null);
}

/** Identity markers show the colour identity Find cards' colour query matches. */
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
  if (row.spares) add(tile, [el("p", {class: "sub col-spare-reason", text: row.spares.reason})]);
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
      ...(row.spares ? [el("span", {class: "col-find-spare-reason", text: row.spares.reason
        + (row.spares.printing_uncertain ? " Printing assignment unconfirmed." : "")})] : []),
      row.card?.type_line ? el("span", { class: "col-find-type", text: row.card.type_line })
        : el("span", { class: "col-find-type" }, row.card ? "Type not recorded" : status("warn", "Name not matched")));
    if (row.card) viewerItem(node, row.card, "collection-find", caption);
    return el("li", { class: "col-find-row" }, node);
  }));
}

/** The response owns every matching line across pages; changes invalidate a pending copy/fallback. */
async function colCopySpares(cv, data, button) {
  const copy = data.spares?.copy, text = copy?.text, seq = cv.findSeq, query = cv.query.toString(), hash = location.hash;
  const current = () => colActive(cv) && cv.query.get("availability") === "spare" && cv.findSeq === seq
    && cv.query.toString() === query && location.hash === hash && button.isConnected && cv.results.contains(button)
    && !cv.busy && ownSpace() === cv.space && seesInventory(cv.space) && !document.querySelector("dialog[open]")
    && cv.results.getAttribute("aria-busy") !== "true" && data.spares?.copy === copy && copy?.text === text;
  if (!current() || button.disabled || data.spares?.ready !== true || typeof copy?.text !== "string"
      || !copy.text || copy.text.length > 2 * 1024 * 1024) return;
  button.disabled = true;
  try {
    if (!navigator.clipboard?.writeText) throw Error("Clipboard unavailable");
    await navigator.clipboard.writeText(text);
    if (current()) toast("Spare list copied.");
  } catch (_) {
    if (!current()) return;
    const sheet = colOpenSheet("Copy spare list", {wide: true});
    const area = el("textarea", {readonly: "", rows: 12, class: "export-copy col-spare-copy-text", spellcheck: "false",
      "aria-label": "Spare cards list"});
    area.value = text;
    sheet.body.append(el("p", {text: "Select and copy this price-free list. Untagged lines need a physical printing check."}), area);
    sheetActions(sheet, [{text: "Close", onclick: () => sheet.close()}]);
    area.focus(); area.select();
  } finally {
    if (button.isConnected) button.disabled = false;
  }
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

/** Export locations link to the source app; no export or external request happens here. */
function colImportHelp(cv, sheet) {
  const sources = [
    ["ManaBox", "Collection tab → top-right menu → export CSV; a binder can be exported from its own menu.", "https://manabox.app/guides/collection/import-export/"],
    ["Moxfield", "Open Collection and use its Export CSV control, rather than a deck export.", "https://moxfield.com/help"],
    ["Deckbox", "Open your Inventory and use Export for a collection CSV.", "https://deckbox.org/help/exports_and_imports"],
    ["Archidekt", "Open Collection and choose Export with quantity, name, set code and collector number included.", "https://archidekt.com/"],
    ["Dragon Shield", "Open the collection folder and use its export option for a CSV.", "https://mtg.dragonshield.com/"],
    ["Delver Lens", "Use Export's CSV/site preset with set and collector number; see Exporting to sites in its tutorial.", "https://www.delverlab.com/"],
    ["TCGplayer", "Account → Settings → Sharing: choose CSV and identifying output columns, then share/export the collection list.", "https://help.tcgplayer.com/hc/en-us/articles/115010308788-Choosing-Your-Settings"]
  ];
  return el("details", {class: "col-import-help"}, el("summary", {text: "Where to export, or start a CSV"}),
    el("ul", {}, sources.map(([name, text, href]) => el("li", {},
      el("strong", {text: name + ": "}), text, " ", el("a", {href, target: "_blank", rel: "noopener noreferrer", text: "Source app/help"})))),
    el("p", {class: "sub", text: "Keep card name, quantity, set code, collector number and finish. ID-only exports need printing details added first. Menus can change; use the source app's help if a control moved."}),
    el("button", {type: "button", class: "btn", text: "Download blank collection CSV", onclick: event => {
      if (sheet.closed || !event.currentTarget.isConnected || !colActive(cv)) return;
      const url = URL.createObjectURL(new Blob([COL_FIELDS.join(",") + "\n"], {type: "text/csv;charset=utf-8"}));
      const link = el("a", {href: url, download: "decklab-collection-template.csv"});
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }}));
}

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
    ctx.groupReview = null;
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
    el("p", { text: "Choose a collection CSV or a text list including printings, such as 4 Lightning Bolt (M11) 149. A name-only list such as 4 Lightning Bolt needs its set and number first: use Add one card to choose them. Nothing is added until you review it. Unknown condition and language stay blank; spending and location columns aren't imported." }),
    colImportHelp(cv, sheet),
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
  ctx.groupReview = null;
  clear(ctx.area);
  clear(ctx.message).append(loadingBox(`Reading ${filename}…`));
  sheetActions(ctx.sheet, [{ text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() }, colScanBack(ctx)]);
  try {
    const preview = await apiWrite("/api/collection/import/preview", { space: cv.space, filename, text });
    if (seq !== ctx.seq || ctx.sheet.closed || !colActive(cv)) return;
    ctx.preview = preview;
    clear(ctx.message);
    drawImportPreview(ctx);
  } catch (error) {
    if (seq !== ctx.seq || ctx.sheet.closed || !colActive(cv)) return;
    clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message })));
    sheetActions(ctx.sheet, [{ text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() }, colScanBack(ctx)]);
  }
}

function drawImportPreview(ctx) {
  const p = ctx.preview;
  if (colImportHasGroups(p)) return drawImportGroups(ctx);
  ctx.groupReview = null;
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
  const actions = [{ text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() }, colScanBack(ctx)];
  if (cards > 0 && !problems.length) {
    actions.push({ text: `Import ${plural(cards, "card")}`, kind: "primary", value: "import", onclick: () => applyImport(ctx, false) });
  } else if (cards > 0) {
    actions.push({ text: `Skip ${plural(skip, "row")} with problems and import ${plural(cards, "card")}`, kind: "primary",
      value: "import", onclick: () => applyImport(ctx, true) });
    ctx.area.append(el("p", { class: "sub", text: ctx.scanned ? "Or go back to the scanned list to fix them and import every card."
      : "Or fix the file and choose it again to import every row." }));
  } else {
    ctx.area.append(emptyBox("There's nothing in this file to add.", el("button", { type: "button", class: "btn",
      text: "Choose another file", onclick: () => { if (!ctx.busy && !ctx.sheet.closed) ctx.input.click(); } })));
  }
  sheetActions(ctx.sheet, actions);
}

async function applyImport(ctx, skipProblems) {
  const cv = ctx.cv;
  if (ctx.busy || ctx.sheet.closed || !ctx.preview || !colActive(cv)) return;
  const groups = colImportGroupRequest(ctx);
  if (groups?.blocked) return;
  const reviewed = ctx.preview, selection = ctx.seq;
  ctx.busy = true;
  ctx.input.disabled = true;
  colImportGroupBusy(ctx, true, reviewed);
  for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = true;
  clear(ctx.message).append(loadingBox("Importing…"));
  try {
    await colEnsureRows(cv);
    if (ctx.sheet.closed || !colActive(cv) || selection !== ctx.seq || ctx.preview !== reviewed
      || (groups && (!ctx.groupReview || !colImportGroupsHere(ctx, ctx.groupReview)))) {
      ctx.busy = false; ctx.input.disabled = false; colImportGroupBusy(ctx, false, reviewed); return;
    }
    const body = { space: cv.space, token: reviewed.token, sha256: cv.sha256 };
    if (groups) body.skip_groups = groups.ids;
    else if (skipProblems) body.skip_problems = true;
    const answer = await apiWrite("/api/collection/import/apply", body);
    const added = answer.added || { rows: 0, cards: 0 };
    const here = !ctx.sheet.closed && colActive(cv) && selection === ctx.seq && ctx.preview === reviewed;
    ctx.busy = false;
    ctx.sheet.close();
    cv.rows = null;                     // the next write fetches rows for its own current view
    if (answer.sha256) cv.sha256 = answer.sha256;
    invalidateLibrary();
    const words = `Imported ${plural(added.cards || 0, "card")} (${plural(added.rows || 0, "row")}).`
      + (answer.skipped ? ` ${plural(answer.skipped, "row")} with problems skipped.` : "") + colImportExcludedWords(answer);
    if (here && !document.querySelector("dialog[open]")) colReload(cv, words, answer.stale_tables, colFilingSnapshot(answer, cv));
    else if (state.profile?.id === cv.profile) toast(words);
  } catch (error) {
    if (ctx.sheet.closed || !colActive(cv) || selection !== ctx.seq || ctx.preview !== reviewed) return;
    ctx.busy = false;
    ctx.input.disabled = false;
    colImportGroupBusy(ctx, false, reviewed);
    if (error.status === 409 && error.data?.repreview_required) {
      ctx.preview = null;
      ctx.groupReview = null;
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
