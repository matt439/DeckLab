/* Collection Card list presentation: sorting, metadata, filters and per-copy estimates.
 * Canonical rows and their sha stay unchanged; editing and guards keep their existing shared flows. */
"use strict";

// ---------------------------------------------------------------- Card list

const COL_CASUAL_ROWS = 24;

/** A recorded detail: words in casual layouts and codes in the lab; unknown stays explicit. */
function colDetail(value, kind) {
  const label = kind === "condition" ? "Condition" : "Language";
  if (!value) return el("span", { class: "col-detail" },
    el("span", { class: "cell-unknown", "aria-hidden": "true", text: "\u2014" }),
    el("span", { class: "sr-only", text: `${label} not recorded` }));
  const entry = (kind === "condition" ? COL_CONDITIONS : COL_LANGUAGES).find(([code]) => code === value);
  const words = entry ? entry[kind === "condition" ? 2 : 1] : value;
  return el("span", { class: "col-detail" },
    el("span", { class: "col-detail-code", text: value, title: words }),
    el("span", { class: "col-detail-word", text: words }));
}

/** Non-foil stays plain; only foil and etched use the shared neutral finish pill. */
function colFinishLabel(row) {
  return finishChip(row.finish) || el("span", { text: COL_FINISH_WORDS[row.finish] || row.finish || "Non-foil" });
}

function drawCollectionRows(data, space, token = null) {
  const cv = colView(data, space, token, "rows");
  cv.search = "";
  cv.selectedKey = null;
  cv.casualLimit = COL_CASUAL_ROWS;
  cv.page = 1;
  cv.unrecordedOnly = false;
  cv.storageOnly = false;
  const saved = String(local.get("collection.rowsSort") || "name:1").split(":");
  cv.sort = { key: COL_SORTS[saved[0]] ? saved[0] : "name", dir: saved[1] === "-1" ? -1 : 1 };
  const search = el("input", { id: "col-row-search", type: "search", autocomplete: "off", spellcheck: "false",
    placeholder: "Card name or set", oninput: () => { cv.search = search.value; cv.page = 1; cv.casualLimit = COL_CASUAL_ROWS; drawColRowList(cv); } });
  cv.rowSearch = search;
  cv.unrecorded = el("input", { type: "checkbox", id: "col-unrecorded",
    onchange: () => { cv.unrecordedOnly = cv.unrecorded.checked; cv.page = 1; cv.casualLimit = COL_CASUAL_ROWS; drawColRowList(cv); } });
  cv.unrecordedLabel = el("span");
  cv.unrecordedChoice = el("div", { class: "box box-info col-unrecorded" },
    el("p", {}, cv.unrecordedLabel),
    el("label", { class: "filter-chip", for: cv.unrecorded.id }, cv.unrecorded,
      el("span", { text: "Show only these" })));
  cv.storageBox = el("input", { type: "checkbox", id: "col-storage",
    onchange: () => { cv.storageOnly = cv.storageBox.checked; cv.page = 1; cv.casualLimit = COL_CASUAL_ROWS; drawColRowList(cv); } });
  cv.storageLabel = el("span");
  cv.storageChoice = el("label", { class: "filter-chip col-storage", for: cv.storageBox.id }, cv.storageBox, cv.storageLabel);
  cv.count = el("p", { class: "result-count col-count", role: "status" });
  cv.boxNote = el("p", { class: "sub col-storage-box", hidden: true });
  cv.priceNote = el("p", { class: "price-note col-price-note" });
  cv.list = el("div", { class: "col-row-list" });
  cv.preview = el("aside", { class: "col-preview", role: "region", "aria-label": "Selected collection row" });
  const tools = el("div", { class: "toolbar col-row-tools" },
    el("label", { class: "field col-row-search", for: search.id }, el("span", { class: "sr-only", text: "Search the list" }), search),
    el("button", { type: "button", class: "btn col-row-filter-toggle", "aria-label": "Filter card list",
      onclick: () => colRowFilters(cv) }, svgEl("svg", { viewBox: "0 0 20 20", width: 20, height: 20,
        "aria-hidden": "true", focusable: "false" }, svgEl("path", { d: "M3 4h14l-5.5 6.5V16l-3-1.5v-4L3 4Z",
        fill: "none", stroke: "currentColor", "stroke-width": 1.6, "stroke-linejoin": "round" }))),
    el("div", { class: "filter-chips filter-chips-scroll col-row-filter-options" }, cv.storageChoice));
  const root = el("div", { class: "collection-page col-rows-page" }, colHead(cv),
    cv.unsupported ? null : [cv.boxNote, cv.unrecordedChoice, tools,
      el("div", { class: "actions col-row-actions" }, colBulkButton(cv), colBulkSelectionTools(cv), cv.count),
      el("div", { class: "col-row-layout" }, cv.list, cv.preview), cv.priceNote]);
  cv.root = root;
  $("#main").append(root);
  if (!cv.unsupported) drawColRowList(cv);
  colTakeNotice(cv);
  return cv;
}

/** The rows the search and the "in storage" and "not recorded" filters show, sorted. */
function colShownRows(cv) {
  const words = tokFold(cv.search || "");
  const rows = (cv.rows || []).filter((row) => (!words || tokFold(row.name).includes(words) || tokFold(row.set).includes(words))
    && (!cv.unrecordedOnly || colUnrecorded(row)) && (!cv.storageOnly || colInStorage(cv, row)));
  const { key, dir } = cv.sort;
  if (key === "price") {
    // Unpriced rows stay last whichever way it's sorted; equal prices go by name.
    return rows.sort((a, b) => {
      const x = colPrice(cv, a), y = colPrice(cv, b);
      if (x == null || y == null) return (x == null) - (y == null) || String(a.name).localeCompare(String(b.name));
      return (x - y) * dir || String(a.name).localeCompare(String(b.name));
    });
  }
  const value = (row) => key === "quantity" ? Number(row.quantity || 0)
    : key === "set" ? `${row.set || "~"} ${String(row.collector_number || "").padStart(6, "0")}`
      : key === "condition" ? ["NM", "LP", "MP", "HP", "DMG"].indexOf(row.condition) + 1 || 9
        : String(row[key] || "~").toLowerCase();
  return rows.sort((a, b) => {
    const x = value(a), y = value(b);
    const c = typeof x === "number" ? x - y : x.localeCompare(y);
    return c * dir || String(a.name).localeCompare(String(b.name));
  });
}

function drawColRowList(cv) {
  if (!cv.list) return;
  const focused = document.activeElement;
  const sort = cv.list.contains(focused) ? focused?.closest(".th-sort")?.getAttribute("data-col-sort") : null;
  const pager = cv.list.contains(focused) ? focused?.closest(".col-pager") : null;
  const pageFocus = pager && focused.matches("button") ? {
    label: pager.getAttribute("aria-label"), action: focused.getAttribute("aria-label") } : null;
  const rows = cv.rows || [];
  const unrecorded = rows.filter(colUnrecorded).length;
  cv.unrecordedLabel.textContent = `Condition or language not recorded: ${plural(unrecorded, "row")}`;
  cv.unrecordedChoice.hidden = !unrecorded;
  if (!unrecorded) { cv.unrecordedOnly = false; cv.unrecorded.checked = false; }
  // In storage only: offered only when the copies in decks could be worked out.
  const stored = cv.storage && !cv.storage.error ? rows.filter((row) => colInStorage(cv, row)) : null;
  if (cv.storageChoice) {
    cv.storageLabel.textContent = stored ? `In storage only (${plural(stored.length, "row")})` : "";
    cv.storageChoice.hidden = !stored || !rows.length;
    if (!stored) { cv.storageOnly = false; cv.storageBox.checked = false; }
  }
  const shown = colShownRows(cv);
  const selected = shown.find((row) => colKey(row) === cv.selectedKey);
  if (!selected) cv.selectedKey = null;
  colBulkSync(cv, shown);
  const cards = rows.reduce((n, row) => n + Number(row.quantity || 0), 0);
  cv.count.textContent = shown.length === rows.length ? `${plural(rows.length, "row")}, ${plural(cards, "card")}`
    : `${num(shown.length)} of ${plural(rows.length, "row")}`;
  const pages = Math.max(1, Math.ceil(shown.length / COL_ROWS_PAGE));
  cv.page = Math.min(Math.max(1, cv.page), pages);
  const go = (page, control) => {
    if (!colRowControlCurrent(cv, control)) return;
    cv.page = page; drawColRowList(cv); cv.list.scrollIntoView({ block: "start", behavior: "smooth" });
  };
  clear(cv.list);
  if (!rows.length) {
    cv.list.append(el("div", { class: "empty" }, el("p", { text: "No cards recorded yet." }),
      cv.editable ? el("button", { type: "button", class: "btn col-mutate", text: "Add card",
        onclick: () => openCollectionSheet(cv) }) : null));
  } else if (!shown.length) {
    // Emptied by the search or the filters: the one way back is to clear them.
    cv.list.append(emptyBox("No rows match the search and filters.", el("button", { type: "button", class: "btn",
      text: "Clear the search and filters", onclick: () => {
        if (!colActive(cv)) return;
        cv.search = ""; if (cv.rowSearch) cv.rowSearch.value = "";
        cv.unrecordedOnly = false; cv.unrecorded.checked = false;
        cv.storageOnly = false; if (cv.storageBox) cv.storageBox.checked = false;
        cv.page = 1; cv.casualLimit = COL_CASUAL_ROWS; drawColRowList(cv);
        if (cv.rowSearch) cv.rowSearch.focus();
      } }), { live: true }));
  } else {
    const page = shown.slice((cv.page - 1) * COL_ROWS_PAGE, cv.page * COL_ROWS_PAGE);
    add(cv.list, [el("div", { class: "col-row-lab" }, colPager(cv.page, pages, go, "Pages, top"),
      colRowTable(cv, page), colPager(cv.page, pages, go, "Pages, bottom")), colCasualRows(cv, shown)]);
  }
  colDrawPreview(cv, selected);
  drawColPriceNote(cv);
  drawColStorageBox(cv);
  setCollectionBusy(cv, cv.busy);
  registerCollectionKeyboardHelp(cv);
  // A native sort/pager activation removes its own control. Restore only that owned focus.
  if ((sort || pageFocus) && colActive(cv) && cv.root?.contains(cv.list) && !cv.busy
      && !document.querySelector("dialog[open]") && !keyboardMenuOpen()
      && (document.activeElement === focused || document.activeElement === document.body)) {
    let target = sort ? cv.list.querySelector(`[data-col-sort="${sort}"]`) : null;
    if (pageFocus) {
      const fresh = [...cv.list.querySelectorAll(".col-pager")].find(node => node.getAttribute("aria-label") === pageFocus.label);
      target = [...(fresh?.querySelectorAll("button") || [])].find(node => node.getAttribute("aria-label") === pageFocus.action && !node.disabled);
      if (!target) target = cv.list.querySelector(".table-wrap");
    }
    if (target) target.focus({ preventScroll: true });
  }
}

/** Detached controls never sort, page or reclaim focus in a newer view. */
function colRowControlCurrent(cv, control) {
  return colActive(cv) && !cv.busy && control?.isConnected && !control.disabled && cv.list?.contains(control) && cv.root?.contains(control)
    && !document.querySelector("dialog[open]") && !keyboardMenuOpen();
}

/** What the Card list's prices are: estimates, from when and at what rate, or why there are none. */
function drawColPriceNote(cv) {
  if (!cv.priceNote) return;
  const p = cv.prices || {};
  cv.priceNote.hidden = !(cv.rows || []).length;
  let words = p.rate
    ? `~A$ each is an estimate for that row's own printing and finish, using Scryfall's US prices. `
      + `1 USD = ${p.rate} AUD (ECB rate of ${p.rate_date || "date not recorded"}). A dash means Scryfall has no price for it.`
    : p.price_error ? `No prices: ${p.price_error}` : "No prices: the card data isn't ready yet.";
  const storage = cv.storage;
  if (storage && storage.error) words += ` In storage only isn't offered: ${storage.error}`;
  if (cv.storageOnly) words += " In storage only counts the copies in built decks and products kept"
    + " intact; basic lands are always listed, since their copies in decks aren't tracked.";
  if (storage && Object.values(storage.rows).some((s) => s && s.guess)) words += ` ${COL_GUESS_WORDS}`;
  clear(cv.priceNote).append(el("span", { class: "col-price-copy", text: words }));
  if (p.rate) {
    const stamp = colPriceStamp(p.price_date);
    cv.priceNote.append(stamp || el("span", { class: "sub", text: "Price date not recorded." }));
  }
}

/** The source's calendar date, kept in the device's date rather than shifted from UTC midnight. */
function colPriceStamp(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const when = new Date(`${value}T12:00:00`), [year, month, day] = value.split("-").map(Number);
  if (Number.isNaN(when.getTime()) || when.getFullYear() !== year || when.getMonth() + 1 !== month || when.getDate() !== day) return null;
  const badge = freshnessBadge(when, { verb: "pulled", byDate: true, staleWords: `pulled ${simDay(when)}` });
  badge.setAttribute("title", value);
  return badge;
}

/** The lab table: card selection, identity/type, printing/finish, copies and recorded details,
 * held counts and saved-hint markers, the estimated price of one copy and notes. The casual list is separate. */
function colRowTable(cv, rows) {
  const sortable = (key, cls = "") => {
    const on = cv.sort.key === key;
    return el("th", { scope: "col", class: `col-th-${key} ${cls}`.trim(), "aria-sort": on ? (cv.sort.dir > 0 ? "ascending" : "descending") : null },
      el("button", { type: "button", class: "th-sort", "data-col-sort": key, text: COL_SORTS[key], onclick: (event) => {
        if (!colRowControlCurrent(cv, event.currentTarget)) return;
        cv.sort = { key, dir: on ? -cv.sort.dir : COL_SORT_FIRST[key] || 1 };
        local.set("collection.rowsSort", `${key}:${cv.sort.dir}`);
        cv.page = 1; cv.casualLimit = COL_CASUAL_ROWS;
        drawColRowList(cv);
      } }));
  };
  return el("div", { class: "table-wrap", role: "region", "aria-label": "Collection rows", tabindex: 0, "aria-keyshortcuts": "Enter",
    onkeydown: (event) => colTableKeys(cv, event) },
    el("p", { class: "col-key-hint" }, el("span", {class: "keyboard-character-hint", hidden: true},
      el("kbd", { text: "J" }), " / ", el("kbd", { text: "K" }), " move \u00b7 "), el("kbd", { text: "Enter" }), " opens"),
    el("table", { class: `data col-table${cv.editable && seesInventory(cv.space) && canEditSpace(cv.space) ? " has-bulk-selection" : ""}` },
    el("thead", {}, el("tr", {},
      el("th", { scope: "col", class: "col-th-pic" }, el("span", { class: "sr-only", text: "Picture" })),
      sortable("name"),
      el("th", { scope: "col", class: "col-column-colour col-th-colour", text: "Colour identity" }),
      el("th", { scope: "col", class: "col-column-type col-th-type", text: "Type" }),
      sortable("set", "col-wide"), el("th", { scope: "col", class: "col-th-finish", text: "Finish" }),
      sortable("quantity", "num"), sortable("condition", "col-wide"), sortable("language", "col-wide"),
      el("th", { scope: "col", class: "col-th-held", text: "In decks" }), sortable("price", "num"),
      el("th", { scope: "col", class: "col-notes col-th-notes", text: "Notes" }))),
    el("tbody", {}, rows.map((row) => colRowLine(cv, row)))));
}

function colRowLine(cv, row) {
  const card = cv.pictures[colKey(row)] || null;
  const key = colKey(row);
  const facts = colRowFacts(row);
  const caption = [`×${row.quantity}`, colPrinting(row), facts].filter(Boolean).join(" · ")
    + (card && card.exact === false && row.set ? " (picture of another printing)" : "");
  const thumb = card && card.img_small
    ? viewerItem(el("button", { type: "button", class: "col-thumb", "aria-haspopup": "dialog",
      "aria-label": `Show ${row.name} (${colPrinting(row)})`, onclick: (e) => openCard(card, e.currentTarget) },
      el("img", { src: card.img_small, alt: "", loading: "lazy", decoding: "async", width: 40, height: 56 })), card, "collection-rows", caption)
    : el("span", { class: "col-thumb col-thumb-none thumb-missing", "aria-hidden": "true" });
  const open = () => colSelectRow(cv, key);
  const language = COL_LANGUAGES.find(([v]) => v === row.language);
  const condition = COL_CONDITIONS.find(([v]) => v === row.condition);
  // On a phone the columns fold into one line under the name: the printing, then the condition and language
  // only when they're unusual (not Near Mint, not English) or not recorded. Below 1000px the notes go under it.
  const meta = [colPrinting(row), row.condition === "NM" ? null : row.condition ? condition?.[2] || row.condition : "Condition not recorded",
    !row.language ? "Language not recorded" : row.language === "en" ? null : language ? language[1] : row.language].filter(Boolean).join(" · ");
  const name = [el("span", { class: "col-cell-name", text: row.name }),
    el("small", { class: "col-cell-meta", text: meta }),
    row.notes ? el("small", { class: "col-cell-note", text: row.notes }) : null];
  const hints = colPackingHints(cv, row);
  const choiceCaption = hints ? el("span", { class: "col-viewer-words" },
    el("span", { class: "col-viewer-counts", text: caption }), hints) : caption;
  const choice = viewerItem(el("button", { type: "button", class: "col-open col-mutate", "data-focus": `edit-${key}`,
    "aria-label": `View ${row.name} (${colPrinting(row)})`,
    "aria-current": key === cv.selectedKey ? "true" : null, onclick: open }, name), card, "collection-lab-rows", choiceCaption);
  const bulkChoice = colBulkRowChoice(cv, row);
  return el("tr", { "data-key": key, "data-selected": key === cv.selectedKey ? true : null,
    class: colUnrecorded(row) ? "is-unrecorded" : null },
    el("td", { class: "col-td-pic" }, thumb),
    el("td", { class: "col-td-name" }, bulkChoice
      ? el("div", { class: "col-row-name-choice" }, bulkChoice, choice) : choice),
    colIdentityCell(card), colTypeCell(card),
    el("td", { class: "col-wide col-td-printing", text: colPrinting({ ...row, finish: "nonfoil" }) }),
    el("td", { class: "col-td-finish" }, colFinishLabel(row)),
    el("td", { class: "num col-td-qty" }, el("span", { text: String(row.quantity) })),
    el("td", { class: "col-wide col-td-condition" }, colDetail(row.condition, "condition")),
    el("td", { class: "col-wide col-td-language" }, colDetail(row.language, "language")),
    colHeldCell(cv, row), colPriceCell(cv, row),
    el("td", { class: "col-notes col-td-notes", text: row.notes || "", title: row.notes || null }));
}

const COL_GUESS_WORDS = "A ? after \"in decks\" means the decks' lists don't say which of this card's printings"
  + " they hold, so the copies are counted against the cheapest: check the decks.";

function colPriceCell(cv, row) {
  const price = colPrice(cv, row);
  return price == null
    ? el("td", { class: "num col-td-price col-unpriced" }, colUnknown("No price"))
    : el("td", { class: "num col-td-price", text: price.toFixed(2) });
}


/** Unknown values have one decorative mark and words a screen reader can read. */
function colUnknown(words) {
  return el("span", {}, el("span", { class: "cell-unknown", "aria-hidden": "true", text: "\u2014" }),
    el("span", { class: "sr-only", text: words }));
}

/** These remain allocated copy counts, separate from saved packing-list hints. */
function colStorageWords(cv, row) {
  if (!cv.storage || cv.storage.error) return colWithLocation(cv, row, "Copies in decks not known");
  const { held, guess } = colHeld(cv, row);
  if (held == null) return colWithLocation(cv, row, "Basic land: deck allocation not tracked");
  if (!held) return colWithLocation(cv, row, "In storage");
  return colWithLocation(cv, row, `${plural(held, "copy", "copies")} in decks${guess ? " (printing uncertain)" : ""}`
    + ` \u00b7 ${Math.max(0, Number(row.quantity) - held)} free`);
}

const COL_PACKING_HINT_WORDS = "Saved packing lists may differ from the boxes and current deck lists. "
  + "Links open current lists.";

/** Validate a route identity without inferring its visibility or consulting the library. */
function colHolderId(id) {
  if (typeof id !== "string" || /[\u0000-\u001f\u007f\\]/.test(id)) return false;
  const parts = id.split("/");
  if (parts.some((part) => !part.trim() || part === "." || part === "..")) return false;
  if (parts[0] === "pairing") return parts.length === 2 && parts[1].split("+").length === 2
    && parts[1].split("+").every((part) => part.trim() && part !== "." && part !== "..");
  return parts[0] === "product" ? parts.length >= 2
    : ["casual", "commander"].includes(parts[0]) ? parts.length === 2
      : parts.length === 3 && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(parts[0])
        && ["casual", "commander"].includes(parts[1]);
}

/** New answers name only visible, uncontested hints. Older/malformed answers stay anonymous. */
function colListedHolders(cv, row) {
  if (!cv.storage || cv.storage.error || cv.unsupported || cv.data?.space !== cv.space) return null;
  if (!Number.isSafeInteger(Number(row.quantity)) || Number(row.quantity) < 0) return null;
  const saved = cv.storage.rows[colKey(row)];
  if (!saved || typeof saved !== "object" || Array.isArray(saved)
      || !Number.isSafeInteger(saved.held) || saved.held < 0
      || !Array.isArray(saved.listed_holders) || !Number.isSafeInteger(saved.unattributed) || saved.unattributed < 0) return null;
  const holders = [], seen = new Set();
  let total = saved.unattributed;
  for (const hint of saved.listed_holders) {
    if (!hint || typeof hint !== "object" || Array.isArray(hint) || !colHolderId(hint.id)
        || typeof hint.title !== "string" || !hint.title.trim() || /[\u0000-\u001f\u007f]/.test(hint.title)
        || !Number.isSafeInteger(hint.quantity) || hint.quantity <= 0 || !["target", "owned"].includes(hint.version)) return null;
    const key = `${hint.id}|${hint.version}`;
    if (seen.has(key)) return null;
    seen.add(key);
    total += hint.quantity;
    if (total > saved.held) return null;
    // Optional colours describe the deck's current Planned identity, independently of the hint's list kind.
    const colors = Array.isArray(hint.colors) && hint.colors.every((color) => typeof color === "string" && /^[WUBRG]$/.test(color))
      ? [...hint.colors] : null;
    holders.push({ id: hint.id, title: hint.title, quantity: hint.quantity, version: hint.version, colors,
      recorded: hint.recorded === true });
  }
  if (holders.length && saved.held > Number(row.quantity)) return null;
  return total === saved.held ? { holders, unattributed: saved.unattributed } : null;
}

/** Recheck a retained link before and after the viewer's asynchronous close. */
function colPackingLink(cv, row, hint) {
  const key = colKey(row), href = deckHref(hint.id, hint.version);
  const current = () => {
    if (!colActive(cv)) return false;
    const record = (cv.rows || []).find((item) => colKey(item) === key);
    return record && colListedHolders(cv, record)?.holders.some((item) => item.id === hint.id
      && item.version === hint.version && item.quantity === hint.quantity && item.title === hint.title
      && item.recorded === hint.recorded);
  };
  return el("a", { href, onclick: (event) => {
    event.preventDefault();
    if (!event.currentTarget.isConnected || !current()) return;
    colAfterViewer(() => { if (current()) location.hash = href; });
  } }, deckColourPieces(hint.colors)?.swatch(),
    el("span", { text: hint.recorded ? `${hint.quantity} \u00d7 ${hint.title}`
      : `${hint.quantity} \u00d7 ${hint.title} (${listName(hint.version)})` }));
}

/** A recorded holder is its Printings in box line (what went in the box); the others are saved
 * hints, never verified physical copies or a guaranteed current revision. */
function colPackingHints(cv, row) {
  const listed = colListedHolders(cv, row);
  if (!listed?.holders.length) return null;
  const inBox = listed.holders.filter((hint) => hint.recorded), hints = listed.holders.filter((hint) => !hint.recorded);
  return el("span", { class: "col-viewer-decks col-packing-hints" },
    inBox.length ? el("span", { class: "col-packing-label", text: "Recorded in the box:" }) : null,
    inBox.map((hint) => el("span", { class: "col-packing-hint" }, colPackingLink(cv, row, hint))),
    hints.length ? el("span", { class: "col-packing-label", text: "Saved packing-list hints:" }) : null,
    hints.map((hint) => el("span", { class: "col-packing-hint" }, colPackingLink(cv, row, hint))),
    listed.unattributed ? el("span", { class: "col-viewer-note",
      text: `${plural(listed.unattributed, "held copy", "held copies")} without a named hint.` }) : null,
    hints.length ? el("span", { class: "col-viewer-note", text: COL_PACKING_HINT_WORDS }) : null);
}

/** Resolve the key from the current filtered rows; detached/stale callbacks never restore old details. */
function colSelectRow(cv, key) {
  if (!colActive(cv) || cv.busy || !colShownRows(cv).some((row) => colKey(row) === key)) return;
  cv.selectedKey = key;
  drawColRowList(cv);
  const button = [...cv.list.querySelectorAll(".col-open")].find((node) => node.getAttribute("aria-current") === "true");
  if (button) button.focus();
}

function colEditSelected(cv, key) {
  if (!colActive(cv) || cv.busy || !cv.editable) return;
  const row = (cv.rows || []).find((item) => colKey(item) === key);
  if (row) openCollectionSheet(cv, row);
}

/** The lab's selection is a projection of the current canonical row, never an editable copy. */
function colDrawPreview(cv, row) {
  if (!cv.preview) return;
  clear(cv.preview);
  if (!row) { cv.preview.append(noneSelected("Pick a card to see its copies.")); return; }
  const key = colKey(row), card = cv.pictures[key], price = colPrice(cv, row);
  const colours = deckColourPieces(card?.color_identity);
  const field = (name, value) => [el("dt", { text: name }), el("dd", {}, value)];
  add(cv.preview, [el("h2", { class: "col-preview-title", text: row.name }),
    card?.img ? el("button", { type: "button", class: "col-preview-picture", "aria-label": `Show ${row.name}`,
      onclick: (event) => { if (colActive(cv)) openCard(card, event.currentTarget); } },
    el("img", { src: card.img, alt: "", loading: "lazy", decoding: "async", width: 488, height: 680 }))
      : el("p", { class: "col-preview-no-picture" }, el("span", { class: "col-preview-missing thumb-missing", "aria-hidden": "true" }),
        el("span", { class: "sub", text: "Picture not available" })),
    card?.exact === false ? el("p", { class: "sub", text: "Picture of another printing" }) : null,
    el("dl", { class: "col-preview-facts" },
      field("Printing", el("span", { text: colPrinting(row) })),
      field("Owned", el("span", { text: plural(Number(row.quantity), "copy", "copies") })),
      field("Estimated price per copy", price == null ? colUnknown("No price") : `~A$${price.toFixed(2)} each`),
      field("Condition", colDetail(row.condition, "condition")), field("Language", colDetail(row.language, "language")),
      field("Colour identity", colours ? colours.pips(20) : colUnknown("Colour identity not recorded")),
      field("Type", card?.type_line || colUnknown("Type not recorded"))),
    el("p", { class: "col-preview-storage", text: colStorageWords(cv, row) }), colPackingHints(cv, row),
    row.notes ? el("p", { class: "sub", text: row.notes }) : null,
    card?.oracle_text ? el("div", { class: "col-preview-rules" }, oracleParagraphs(card.oracle_text)) : null,
    cv.editable ? el("button", { type: "button", class: "btn btn-primary col-mutate col-preview-edit", text: "Edit copies",
      onclick: () => colEditSelected(cv, key) }) : null]);
}

/** One casual row opens the existing viewer/edit flow; it has no table roles or nested controls. */
function colCasualRow(cv, row) {
  const key = colKey(row), card = cv.pictures[key], price = colPrice(cv, row);
  const condition = row.condition ? COL_CONDITIONS.find(([value]) => value === row.condition)?.[2] || row.condition : null;
  const language = row.language ? COL_LANGUAGES.find(([value]) => value === row.language)?.[1] || row.language : null;
  const details = [row.condition === "NM" ? null : condition || "Condition not recorded",
    row.language === "en" ? null : language || "Language not recorded"].filter(Boolean);
  const caption = el("span", { class: "col-viewer-words" },
    el("span", { class: "col-viewer-counts", text: `${plural(Number(row.quantity), "copy", "copies")} \u00b7 ${colPrinting(row)}` }),
    el("span", { class: "col-viewer-note", text: colStorageWords(cv, row) }),
    colPackingHints(cv, row),
    card?.exact === false ? el("span", { class: "col-viewer-note", text: "Picture of another printing" }) : null,
    row.notes ? el("span", { class: "col-viewer-note", text: row.notes }) : null,
    cv.editable ? el("button", { type: "button", class: "btn", text: "Edit copies",
      onclick: () => colAfterViewer(() => colEditSelected(cv, key)) }) : null);
  const open = card ? (event) => { if (colActive(cv)) openCard(card, event.currentTarget); }
    : cv.editable ? () => colEditSelected(cv, key) : null;
  const node = el(open ? "button" : "div", { type: open ? "button" : null, class: "col-casual-open",
    "aria-label": open ? `${card ? "Show" : "Edit"} ${row.name} (${colPrinting(row)})` : null, onclick: open },
    el("span", { class: card?.img_small ? "col-casual-picture" : "col-casual-picture thumb-missing", "aria-hidden": "true" }, card?.img_small
      ? el("img", { src: card.img_small, alt: "", loading: "lazy", decoding: "async", width: 56, height: 78 }) : null),
    el("span", { class: "col-casual-name", text: row.name }),
    el("span", { class: "col-casual-price" }, price == null ? colUnknown("No price") : `~A$${price.toFixed(2)} each`),
    el("span", { class: "col-casual-meta", text: [plural(Number(row.quantity), "copy", "copies"), colPrinting(row), ...details].join(" \u00b7 ") }),
    el("span", { class: "col-casual-storage", text: colStorageWords(cv, row) }));
  if (card) viewerItem(node, card, "collection-casual-rows", caption);
  const bulkChoice = colBulkRowChoice(cv, row);
  return el("li", { class: `col-casual-row${bulkChoice ? " has-bulk-choice" : ""}`, "data-key": key },
    bulkChoice, node,
    row.notes ? el("p", { class: "col-casual-note", text: row.notes }) : null);
}

function colCasualRows(cv, shown) {
  const limit = cv.casualLimit || COL_CASUAL_ROWS, rows = shown.slice(0, limit);
  return el("div", { class: "col-row-casual" },
    el("ul", { class: "col-casual-list" }, rows.map((row) => colCasualRow(cv, row))),
    el("p", { class: "result-count", role: "status", text: `${rows.length} of ${plural(shown.length, "row")}` }),
    shown.length > limit ? el("button", { type: "button", class: "btn col-show-more", text: "Show more",
      onclick: () => {
        if (!colActive(cv)) return;
        cv.casualLimit = limit + COL_CASUAL_ROWS; drawColRowList(cv);
        cv.list.querySelectorAll(".col-casual-open")[limit]?.focus();
      } }) : null);
}

/** The casual filter button uses the tracked sheet and the same predicates as the lab toolbar. */
function colRowFilters(cv) {
  if (!colActive(cv) || cv.busy) return;
  const sheet = colOpenSheet("Filter card list");
  const redraw = () => { cv.page = 1; cv.casualLimit = COL_CASUAL_ROWS; drawColRowList(cv); };
  const checkbox = (words, checked, change, disabled = false) => {
    const box = el("input", { type: "checkbox", disabled }); box.checked = checked;
    box.addEventListener("change", () => { if (colActive(cv)) { change(box.checked); redraw(); } });
    return el("label", { class: "choice" }, box, el("span", { text: words }));
  };
  const sort = el("select", { "aria-label": "Sort card list", onchange: () => {
    if (!colActive(cv)) return;
    const [key, dir] = sort.value.split(":"); cv.sort = { key, dir: Number(dir) };
    local.set("collection.rowsSort", sort.value); redraw();
  } }, Object.entries(COL_SORTS).flatMap(([key, words]) => [1, -1].map((dir) =>
    el("option", { value: `${key}:${dir}`, text: `${words}: ${dir === 1 ? "ascending" : "descending"}` }))));
  sort.value = `${cv.sort.key}:${cv.sort.dir}`;
  add(sheet.body, [
    checkbox("Condition or language not recorded", cv.unrecordedOnly, (on) => { cv.unrecordedOnly = on; cv.unrecorded.checked = on; }),
    checkbox("In storage only", cv.storageOnly, (on) => { cv.storageOnly = on; cv.storageBox.checked = on; }, !cv.storage || !!cv.storage.error),
    el("label", { class: "field" }, el("span", { text: "Sort" }), sort)]);
  sheetActions(sheet, [{ text: "Done", onclick: () => sheet.close() }]);
}


/** Card identity is separate from its printed colours and the Find cards colour filter. */
function colIdentityCell(card) {
  const pieces = deckColourPieces(card?.color_identity), pips = pieces?.pips(16);
  if (pips) pips.setAttribute("aria-label", `Colour identity: ${pieces.label.replace(/^Colours: /, "")}`);
  return el("td", { class: "col-column-colour col-td-colour" }, pips || colUnknown("Colour identity not recorded"));
}

function colTypeCell(card) {
  return el("td", { class: "col-column-type col-td-type" }, card?.type_line
    ? el("span", { class: "col-type-text", text: card.type_line, title: card.type_line }) : colUnknown("Type not recorded"));
}

/** Counts stay unchanged; the lab's static marker leads to full hints in the selected preview. */
function colHeldCell(cv, row) {
  const cell = el("td", { class: "col-td-held" });
  if (!cv.storage || cv.storage.error) return add(cell, [colUnknown("Copies in decks not known")]);
  const { held, guess } = colHeld(cv, row);
  if (held == null) return add(cell, [el("span", { text: "Not tracked", title: "Basic land: deck allocation not tracked" })]);
  if (!held) return add(cell, [el("span", { text: "In storage" })]);
  const words = `${num(held)} in decks${guess ? "?" : ""} \u00b7 ${num(Math.max(0, Number(row.quantity) - held))} free`;
  return add(cell, [el("span", { class: `col-held${guess ? " col-held-guess" : ""}`,
    title: colStorageWords(cv, row) + (guess ? `. ${COL_GUESS_WORDS}` : "") }, simNumbers(words)),
    guess ? el("span", { class: "sr-only", text: "Printing allocation uncertain." }) : null,
    colPackingMarker(colListedHolders(cv, row)?.holders || [])]);
}

/** "Recorded in boxes" when every named holder's copies are its Printings in box record, else the hints'. */
function colPackingMarker(holders) {
  if (!holders.length) return null;
  return holders.every((hint) => hint.recorded)
    ? el("span", { class: "col-packing-marker", text: "Recorded in boxes" })
    : el("span", { class: "col-packing-marker", text: "Saved list hints", title: COL_PACKING_HINT_WORDS });
}


/** Lab navigation follows the current filtered ordering, including page boundaries. */
function colTableKeys(cv, event) {
  if (!colKeyboardReady(cv, event) || !cv.list.contains(event.currentTarget) || !event.currentTarget.contains(event.target)) return;
  if (keyboardEditing(event.target)) return;
  const key = String(event.key || "").toLowerCase(), shown = colShownRows(cv);
  if (key === "j" || key === "k") {
    if (!keyboardCharactersEnabled()) return;
    if (!shown.length) return;
    const at = shown.findIndex((row) => colKey(row) === cv.selectedKey);
    const next = at < 0 ? (key === "j" ? 0 : shown.length - 1)
      : Math.max(0, Math.min(shown.length - 1, at + (key === "j" ? 1 : -1)));
    event.preventDefault();
    cv.page = Math.floor(next / COL_ROWS_PAGE) + 1;
    colSelectRow(cv, colKey(shown[next]));
    return;
  }
  if (key !== "enter") return;
  const choice = event.target?.closest(".col-open");
  if (!choice && event.target !== event.currentTarget) return; // headers retain their own Enter action
  const rowKey = choice?.closest("tr")?.getAttribute("data-key") || cv.selectedKey;
  const row = shown.find((item) => colKey(item) === rowKey);
  if (!row) return;
  event.preventDefault();
  if (event.repeat) return; // suppress the native button click too; held J/K still navigates
  cv.page = Math.floor(shown.indexOf(row) / COL_ROWS_PAGE) + 1;
  colSelectRow(cv, rowKey);
  const card = cv.pictures[rowKey];
  const trigger = [...cv.list.querySelectorAll(".col-open")]
    .find((node) => node.closest("tr").getAttribute("data-key") === rowKey);
  if (card && trigger) openCard(card, trigger);
  else if (cv.editable) colEditSelected(cv, rowKey);
  else { cv.preview.setAttribute("tabindex", "-1"); cv.preview.focus({ preventScroll: true }); }
}
