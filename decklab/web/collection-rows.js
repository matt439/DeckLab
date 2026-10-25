/* Collection Card list presentation: sorting, metadata, filters and per-copy estimates.
 * Canonical rows and their sha stay unchanged; editing and guards keep their existing shared flows. */
"use strict";

// ---------------------------------------------------------------- Card list

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
  cv.page = 1;
  cv.unrecordedOnly = false;
  cv.storageOnly = false;
  const saved = String(local.get("collection.rowsSort") || "name:1").split(":");
  cv.sort = { key: COL_SORTS[saved[0]] ? saved[0] : "name", dir: saved[1] === "-1" ? -1 : 1 };
  const search = el("input", { id: "col-row-search", type: "search", autocomplete: "off", spellcheck: "false",
    placeholder: "Card name or set", oninput: () => { cv.search = search.value; cv.page = 1; drawColRowList(cv); } });
  cv.unrecorded = el("input", { type: "checkbox", id: "col-unrecorded",
    onchange: () => { cv.unrecordedOnly = cv.unrecorded.checked; cv.page = 1; drawColRowList(cv); } });
  cv.unrecordedLabel = el("span");
  cv.unrecordedChoice = el("div", { class: "box box-info col-unrecorded" },
    el("p", {}, cv.unrecordedLabel),
    el("label", { class: "filter-chip", for: cv.unrecorded.id }, cv.unrecorded,
      el("span", { text: "Show only these" })));
  cv.storageBox = el("input", { type: "checkbox", id: "col-storage",
    onchange: () => { cv.storageOnly = cv.storageBox.checked; cv.page = 1; drawColRowList(cv); } });
  cv.storageLabel = el("span");
  cv.storageChoice = el("label", { class: "filter-chip col-storage", for: cv.storageBox.id }, cv.storageBox, cv.storageLabel);
  cv.count = el("p", { class: "result-count col-count", role: "status" });
  cv.priceNote = el("p", { class: "price-note col-price-note" });
  cv.list = el("div", { class: "col-row-list" });
  const root = el("div", { class: "collection-page col-rows-page" }, colHead(cv),
    cv.unsupported ? null : [cv.unrecordedChoice, el("div", { class: "toolbar col-row-tools" },
      el("label", { class: "field col-row-search", for: search.id }, el("span", { class: "sr-only", text: "Search the list" }), search),
      cv.storageChoice, colBulkButton(cv), cv.count), cv.list, cv.priceNote]);
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
  colBulkSync(cv, shown);
  const cards = rows.reduce((n, row) => n + Number(row.quantity || 0), 0);
  cv.count.textContent = shown.length === rows.length ? `${plural(rows.length, "row")}, ${plural(cards, "card")}`
    : `${num(shown.length)} of ${plural(rows.length, "row")}`;
  const pages = Math.max(1, Math.ceil(shown.length / COL_ROWS_PAGE));
  cv.page = Math.min(Math.max(1, cv.page), pages);
  const go = (page) => { cv.page = page; drawColRowList(cv); cv.list.scrollIntoView({ block: "start", behavior: "smooth" }); };
  clear(cv.list);
  if (!rows.length) {
    cv.list.append(el("div", { class: "empty" }, el("p", { text: "No cards recorded yet." }),
      cv.editable ? el("button", { type: "button", class: "btn col-mutate", text: "Add card",
        onclick: () => openCollectionSheet(cv) }) : null));
  } else if (!shown.length) {
    cv.list.append(el("div", { class: "empty" }, el("p", { text: "No rows match." })));
  } else {
    const page = shown.slice((cv.page - 1) * COL_ROWS_PAGE, cv.page * COL_ROWS_PAGE);
    add(cv.list, [colPager(cv.page, pages, go, "Pages, top"), colRowTable(cv, page), colPager(cv.page, pages, go, "Pages, bottom")]);
  }
  drawColPriceNote(cv);
  setCollectionBusy(cv, cv.busy);
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

/** The dense table: thumbnail (opens the viewer), the card (opens its sheet, or the viewer when read only),
 * printing, copies, the estimated price of one copy, condition, language and notes. On a phone the last four fold into a line under the name. */
function colRowTable(cv, rows) {
  const sortable = (key, cls = "") => {
    const on = cv.sort.key === key;
    return el("th", { scope: "col", class: `col-th-${key} ${cls}`.trim(), "aria-sort": on ? (cv.sort.dir > 0 ? "ascending" : "descending") : null },
      el("button", { type: "button", class: "th-sort", text: COL_SORTS[key], onclick: () => {
        cv.sort = { key, dir: on ? -cv.sort.dir : COL_SORT_FIRST[key] || 1 };
        local.set("collection.rowsSort", `${key}:${cv.sort.dir}`);
        cv.page = 1;
        drawColRowList(cv);
      } }));
  };
  return el("div", { class: "table-wrap" }, el("table", { class: "data col-table" },
    el("thead", {}, el("tr", {},
      el("th", { scope: "col", class: "col-th-pic" }, el("span", { class: "sr-only", text: "Picture" })),
      sortable("name"), sortable("set", "col-wide"), sortable("quantity", "num"), sortable("price", "num"),
      sortable("condition", "col-wide"),
      sortable("language", "col-wide"), el("th", { scope: "col", class: "col-notes col-th-notes", text: "Notes" }))),
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
    : el("span", { class: "col-thumb col-thumb-none", "aria-hidden": "true" });
  const open = cv.editable ? () => openCollectionSheet(cv, row)
    : card ? () => openCard(card, thumb) : null;
  const language = COL_LANGUAGES.find(([v]) => v === row.language);
  const condition = COL_CONDITIONS.find(([v]) => v === row.condition);
  // On a phone the columns fold into one line under the name: the printing, then the condition and language
  // only when they're unusual (not Near Mint, not English) or not recorded. Below 1000px the notes go under it.
  const meta = [colPrinting(row), row.condition === "NM" ? null : row.condition ? condition?.[2] || row.condition : "Condition not recorded",
    !row.language ? "Language not recorded" : row.language === "en" ? null : language ? language[1] : row.language].filter(Boolean).join(" · ");
  const name = [el("span", { class: "col-cell-name", text: row.name }),
    el("small", { class: "col-cell-meta", text: meta }),
    row.notes ? el("small", { class: "col-cell-note", text: row.notes }) : null];
  return el("tr", { "data-key": key, class: colUnrecorded(row) ? "is-unrecorded" : null },
    el("td", { class: "col-td-pic" }, thumb),
    el("td", { class: "col-td-name" }, open ? el("button", { type: "button", class: "col-open col-mutate", "data-focus": `edit-${key}`,
      "aria-label": cv.editable ? `Edit ${row.name} (${colPrinting(row)})` : null, onclick: open }, name) : name),
    el("td", { class: "col-wide col-td-printing" }, colPrinting({ ...row, finish: "nonfoil" }), " · ", colFinishLabel(row)),
    el("td", { class: "num col-td-qty" }, el("span", { text: String(row.quantity) }), colHeldNote(cv, row)),
    colPriceCell(cv, row),
    el("td", { class: "col-wide col-td-condition" }, colDetail(row.condition, "condition")),
    el("td", { class: "col-wide col-td-language" }, colDetail(row.language, "language")),
    el("td", { class: "col-notes col-td-notes", text: row.notes || "", title: row.notes || null }));
}

const COL_GUESS_WORDS = "A ? after \"in decks\" means the decks' lists don't say which of this card's printings"
  + " they hold, so the copies are counted against the cheapest: check the decks.";

/** Under a row's copies: how many are in decks ("1 in a deck", "all in decks"), "in decks?" with a
 * title when the decks' lists name another printing (a guess), nothing when all are in storage. */
function colHeldNote(cv, row) {
  const { held, guess } = colHeld(cv, row);
  if (!held) return null;
  const all = held >= Number(row.quantity || 0);
  const words = all ? "all in decks" : held === 1 ? "1 in a deck" : `${num(held)} in decks`;
  return el("small", { class: `col-held${guess ? " col-held-guess" : ""}`, text: guess ? `${words}?` : words,
    title: guess ? COL_GUESS_WORDS : null });
}

function colPriceCell(cv, row) {
  const price = colPrice(cv, row);
  return price == null
    ? el("td", { class: "num col-td-price col-unpriced" }, el("span", { text: "–", "aria-label": "No price" }))
    : el("td", { class: "num col-td-price", text: price.toFixed(2) });
}
