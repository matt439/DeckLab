/* Deck Lab's page: receiving a delivery as a check-off board (decklab/UI-REVIEW.md WP6). Each pending part of
the order has native checks in Pictures or List. Inspect opens the card's sheet (its printing,
finish, condition, language and notes, split copies), whose picture opens the swipe viewer over the whole
grid. A sticky bar at the bottom shows the progress, the arrival date and the one main action: Preview, which
names the checked selection once its required checks are ticked; unticked cards remain pending. The preview opens a dialog in plain
words; Record arrival applies it, and a "Where these go" view replaces the board.

The API (lib/api/receipts.py): preview {order, fingerprint, received_on, components
[{id, verified, rows | intact, take?}]}, then apply {preview}. take selects edited row indexes as [{row: 1}]; unticked rows stay pending. The view also brings each row's picture and decks,
today's date and a product's card list. The check in progress is kept in localStorage per order and inventory
revision, so a reload or a phone going to sleep loses nothing. Someone who can't record arrivals (only an admin
can) sees the same tiles, read only. */
"use strict";

const RCPT_CONDITIONS = ["", "NM", "LP", "MP", "HP", "DMG"];
const RCPT_FILTERS = ["all", "todo", "attention", "ticked"];
const RCPT_LANGUAGES = ["", "en", "ja", "de", "fr", "it", "es", "pt", "ko", "ru", "zhs", "zht"];
const RCPT_LANGUAGE_WORDS = { en: "English", ja: "Japanese", de: "German", fr: "French", it: "Italian", es: "Spanish",
  pt: "Portuguese", ko: "Korean", ru: "Russian", zhs: "Chinese (simplified)", zht: "Chinese (traditional)" };
// Parts of a row's notes that only say what to check on arrival: stale once the card is checked. The "not
// recorded" part stays true while the condition or language is still blank (RCPT_BLANK_NOTE).
const RCPT_ARRIVAL_NOTE = /^(?:condition and language not recorded|(?:check|verify)(?: physical pairing)? on arrival)$/i;
const RCPT_BLANK_NOTE = /^condition and language not recorded$/i;
// A note part that only says what the shop's listing called it: provenance, shown in the sheet, never flagged.
const RCPT_PROVENANCE = /^listed as /i;
const RCPT_LISTING_NOTE = /^listing shows this pairing$/i;
// The incoming rules' unresolved pairing (inventory rules.UNVERIFIED) and the blank reverse's note.
const RCPT_UNVERIFIED = /reverse face unconfirmed|reverse.*(?:unknown|unconfirmed)|pairing.*(?:unknown|unconfirmed)|check physical pairing/i;
const RCPT_SINGLE = "single-sided verified";
const RCPT_BASICS = ["Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"];
const RCPT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
let rcptKeys = 0;

function showReceipt(params, token) {
  return load(`/api/receipt?order=${encodeURIComponent(params.get("order") || "")}`, token,
    data => drawReceipt(data, token));
}


// ------------------------------------------------------------------ small words

/** "8 Oct 2026" for 2026-10-08. */
function rcptDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  return m ? `${Number(m[3])} ${RCPT_MONTHS[Number(m[2]) - 1]} ${m[1]}` : iso || "";
}

/** The day before an ISO date. */
function rcptDayBefore(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const day = new Date(Date.UTC(y, m - 1, d) - 86400000);
  return day.toISOString().slice(0, 10);
}

/** A deck's title for a chip: "Krenko, Mob Boss: Goblin Horde (upgraded)" -> "Krenko". */
function rcptShortTitle(title) { return String(title || "").split(":")[0].split(",")[0].trim(); }

function rcptQty(row) { return Math.max(0, parseInt(row.values.quantity, 10) || 0); }

function rcptIsBasic(name) {
  return RCPT_BASICS.includes(name) || RCPT_BASICS.some((b) => name === `Snow-Covered ${b}`);
}

/** A token's power and toughness from its details ("2/2; green; ..." -> "2/2"), or "". */
function rcptPT(details) {
  const first = String(details || "").split(";")[0].trim();
  return /^[\dX*+-]+\/[\dX*+-]+$/.test(first) ? first : "";
}

/** notes without the parts that only say what to check on arrival: {notes, removed}. kind "tokens" also drops
 * "listing shows this pairing", which the check confirms or corrects. values: the row's values; while its
 * condition or language is blank, "condition and language not recorded" is still true and stays. */
function rcptCleanNotes(notes, kind, values = null) {
  const blank = kind === "cards" && values && (!values.condition || !values.language);
  const parts = String(notes || "").split(/;\s*/).map((p) => p.trim()).filter(Boolean);
  const kept = parts.filter((p) => (blank && RCPT_BLANK_NOTE.test(p))
    || (!RCPT_ARRIVAL_NOTE.test(p) && !(kind === "tokens" && RCPT_LISTING_NOTE.test(p))));
  return { notes: kept.join("; "), removed: kept.length !== parts.length };
}

/** Clears a ticked row's "check on arrival" notes (when that's on), keeping what they were for "Put the note
 * back". Called on a tick, and again when a ticked card's condition and language are filled in. */
function rcptTidyNotes(view, comp, row) {
  if (!row.ticked || !view.cleanOnTick) return;
  const clean = rcptCleanNotes(row.values.notes, comp.kind, row.values);
  if (!clean.removed) return;
  if (row.before == null) row.before = row.values.notes;
  row.values.notes = clean.notes;
}

/** True when a cards row still has no condition or no language. */
function rcptBlank(comp, row) {
  return comp.kind === "cards" && (!row.values.condition || !row.values.language);
}

/** True when no card of a cards part has its condition or language yet (the usual delivery): one line above
 * the grid says so, instead of two chips on every tile. */
function rcptAllBlank(comp) {
  return comp.kind === "cards" && comp.rows.length > 1 && comp.rows.every((row) => !row.values.condition && !row.values.language);
}

function rcptNotesWithout(notes, test) {
  return String(notes || "").split(/;\s*/).map((p) => p.trim()).filter((p) => p && !test(p)).join("; ");
}


// ------------------------------------------------------------------ the page

/** The delivery for a visitor who can't record arrivals (only an admin can): the same tiles, read only. A tap
 * opens the card viewer over the component's tiles. */
function drawReceiptReadOnly(view, data) {
  view.readOnly = true;
  setTitle(`${routeFor("receipt").title}: ${data.seller || data.order}`);
  add(view.root, [rcptHead(data, "Delivery", view),
    el("p", { class: "note receipt-read-only", text: "Only an admin can record a delivery's arrival, so this is read only." })]);
  data.components.forEach((c, index) => {
    const comp = rcptMakeComp(view, c, index);
    const section = el("section", { class: "rcpt-section", "aria-labelledby": `rcpt-h-${index}` },
      el("h2", { id: `rcpt-h-${index}`, text: rcptTitle(c, data) },
        c.status !== "pending" ? el("span", { class: "rcpt-h-state", text: ` · ${c.status}${c.received_on ? ` ${rcptDate(c.received_on)}` : ""}` }) : null));
    if ((c.checks || []).length) {
      section.append(el("div", { class: "box rcpt-checks" }, el("h3", { text: "To check" }),
        el("ul", {}, c.checks.map((text) => el("li", { text })))));
    }
    comp.grid = el("div", { class: "card-tiles card-tiles-printing rcpt-grid" });
    if (c.kind === "product") rcptProductGrid(view, comp, true);
    else comp.grid.append(...comp.rows.map((row) => rcptTile(view, comp, row, true)));
    section.append(comp.grid);
    view.root.append(section);
  });
  $("#main").append(view.root);
  return view;
}

/** A component's heading in plain words: "15 cards from Example Games", "13 token cards", "Goblin Horde (product)";
 * the id only when it isn't the usual one (a split part such as cards-2). */
function rcptTitle(c, data) {
  const copies = (c.rows || []).reduce((n, row) => n + (parseInt(row.quantity, 10) || 0), 0);
  let text;
  if (c.kind === "product") text = `${(c.product && c.product.name) || c.id} (product)`;
  else if (c.kind === "tokens") text = plural(copies, "token card");
  else text = `${plural(copies, "card")}${data.seller ? ` from ${data.seller}` : ""}`;
  return c.id !== c.kind && c.kind !== "product" ? `${text} · part ${c.id}` : text;
}

function drawReceipt(data, token) {
  const view = { token, profile: state.profile.id, data, busy: false, seq: 0, preview: null, comps: [],
    filter: "all", layout: local.get("receiptLayout") === "list" ? "list" : "pictures", cleanOnTick: true,
    date: { mode: "today", value: data.today || rcptToday() }, sheet: null, done: false, drafting: false };
  view.root = el("div", { class: "receipt-page" });
  if (!mayDo("receipts")) return drawReceiptReadOnly(view, data);
  setTitle(`${routeFor("receipt").title}: ${data.seller || data.order}`);
  const pending = data.components.filter((c) => c.status === "pending");
  add(view.root, [rcptHead(data, null, view)]);
  if (!pending.length) {
    view.root.append(el("div", { class: "empty" }, el("p", { text: "Everything in this order has arrived." }),
      el("a", { class: "btn btn-primary", href: "#/shopping", text: "Back to Shopping" })));
    $("#main").append(view.root);
    return view;
  }
  view.resume = el("div", { class: "rcpt-resume" });
  view.root.append(view.resume);
  for (const c of data.components) {
    if (c.status !== "pending") continue;
    const comp = rcptMakeComp(view, c, view.comps.length);
    comp.selected = pending.length === 1;
    view.comps.push(comp);
  }
  view.board = el("div", { class: "rcpt-board" });
  rcptBuildLayout(view);
  const done = data.components.filter((c) => c.status !== "pending");
  if (done.length) {
    view.root.append(el("p", { class: "sub rcpt-done", text: `Already dealt with: ${done.map((c) =>
      `${rcptTitle(c, data)} (${c.status}${c.received_on ? ` ${rcptDate(c.received_on)}` : ""})`).join(", ")}.` }));
  }
  view.message = el("div", { class: "rcpt-message", role: "status", "aria-live": "polite" });
  view.root.append(view.message);
  rcptBuildBar(view);
  view.root.append(view.bar.node);
  rcptDrawBoard(view);
  rcptOfferDraft(view);
  $("#main").append(view.root);
  rcptSync(view);
  rcptWatchBar(view);
  return view;
}

/** A component's working state: its rows as the board edits them, its checks' ticks and a product's choice. */
function rcptMakeComp(view, c, index) {
  const rows = (c.kind === "product" ? c.items || [] : c.rows || []).map((values, orig) => ({
    key: ++rcptKeys, orig, values: { ...values }, ticked: false, before: null, pic: null }));
  return { c, index, kind: c.kind, rows, checks: (c.checks || []).map(() => false), intact: "", selected: false,
    group: `receipt-${index}`, pictures: c.pictures || null, decks: c.decks || null };
}


// ------------------------------------------------------------------ sections

function rcptDrawBoard(view) {
  clear(view.board);
  for (const comp of view.comps) view.board.append(rcptSection(view, comp));
}

function rcptSection(view, comp) {
  const several = view.comps.length > 1;
  const id = `rcpt-h-${comp.index}`;
  // A part that hasn't arrived still shows its cards (dimmed, without ticks or tools), so the choice can be
  // made by looking at what each part holds.
  const arrived = several ? el("label", { class: "choice rcpt-arrived" },
    el("input", { type: "checkbox", checked: comp.selected || null, onchange: (e) => {
      if (!receiptEditable(view)) return;
      comp.selected = e.currentTarget.checked; rcptMarkSelected(comp);
      if (comp.kind !== "product") rcptDrawGrid(view, comp);
      rcptChanged(view);
    } }), el("span", { text: "This arrived" })) : null;
  comp.body = el("div", { class: "rcpt-body" });
  comp.offNote = several ? el("p", { class: "sub rcpt-off-note", text: "Tick “This arrived” if this part came, to check it off." }) : null;
  comp.section = el("section", { class: "rcpt-section", id: `rcpt-${comp.index}`, "aria-labelledby": id },
    el("div", { class: "rcpt-section-head" }, el("h2", { id, text: rcptTitle(comp.c, view.data) }), arrived),
    comp.offNote, comp.body);
  rcptMarkSelected(comp);
  if (comp.kind === "product") {
    comp.body.append(rcptIntactChoice(view, comp));
    if (comp.checks.length) {
      comp.body.append(el("div", { class: "box rcpt-checks" }, el("h3", { text: "Still to do after it arrives" }),
        el("ul", {}, comp.c.checks.map((text) => el("li", { text }))),
        el("p", { class: "sub" }, "Its token cards are recorded later, on the ",
          el("a", { href: "#/tokens", text: "Tokens page" }), ".")));
    }
    comp.grid = el("div", { class: "card-tiles rcpt-grid" });
    comp.body.append(comp.grid);
    rcptProductGrid(view, comp, true);
    return comp.section;
  }
  comp.body.append(el("p", { class: "sub", text: "Tick only the cards that arrived. Unticked cards stay on the way. Split copies into separate tiles if only some arrived." }));
  if (comp.checks.length) comp.body.append(rcptChecksCard(view, comp));
  comp.body.append(rcptToolbar(view, comp));
  comp.grid = el("div", { class: rcptGridClass(view) });
  comp.body.append(comp.grid);
  rcptDrawGrid(view, comp);
  return comp.section;
}

/** A section's look for whether its part arrived: one that didn't is dimmed, without its ticks and tools. */
function rcptMarkSelected(comp) {
  comp.section.classList.toggle("is-off", !comp.selected);
  if (comp.offNote) comp.offNote.hidden = comp.selected;
}

/** The grid's classes: tiles (with the printing as their meta line), or rows in List. */
function rcptGridClass(view) {
  return view.layout === "list" ? "rcpt-grid rcpt-list" : "card-tiles card-tiles-printing rcpt-grid";
}

/** The order's checks for this component, each with its own tick. */
function rcptChecksCard(view, comp) {
  comp.checkBoxes = comp.c.checks.map((text, i) => el("input", { type: "checkbox", checked: comp.checks[i] || null,
    onchange: (e) => { if (!receiptEditable(view)) return; comp.checks[i] = e.currentTarget.checked; rcptChanged(view); } }));
  return el("div", { class: "box rcpt-checks", id: `rcpt-${comp.index}-checks` }, el("h3", { text: "To check" }),
    comp.c.checks.map((text, i) => el("label", { class: "choice rcpt-check" }, comp.checkBoxes[i], el("span", { text }))));
}

/** The filters and the layout switch above a grid, then the bulk tools (filling in blanks, Tick all, clearing
 * the arrival notes). On a phone the bulk tools and the layout switch are behind one Tools button (a sheet), so
 * the grid starts near the top. */
function rcptToolbar(view, comp) {
  const words = (wide, narrow) => [el("span", { class: "rcpt-wide", text: wide }), el("span", { class: "rcpt-narrow", text: narrow })];
  comp.filterButtons = [["all", "All", "All"], ["todo", "Not checked", "To do"],
    ["attention", "Needs attention", "Attention"], ["ticked", "Ticked", "Ticked"]]
    .map(([key, wide, narrow]) => el("button", { type: "button", "aria-pressed": String(view.filter === key), "data-filter": key,
      onclick: () => rcptSetFilter(view, key) }, words(wide, narrow)));
  comp.layoutButtons = rcptLayoutButtons(view);
  const tools = rcptTools(view, comp, false);
  comp.fill = tools.fill; comp.fillButton = tools.fillButton;
  return el("div", { class: "rcpt-toolbar" },
    el("div", { class: "rcpt-toolbar-row" },
      el("div", { class: "segmented", role: "group", "aria-label": "Show" }, comp.filterButtons),
      el("div", { class: "segmented rcpt-layout", role: "group", "aria-label": "Layout" }, comp.layoutButtons),
      el("button", { type: "button", class: "btn rcpt-tools-button", "aria-haspopup": "dialog", text: "Tools",
        onclick: () => rcptToolsSheet(view, comp) })),
    el("div", { class: "rcpt-toolbar-row rcpt-tools" }, tools.nodes));
}

/** The Pictures / List switch (remembered on this device). */
function rcptLayoutButtons(view) {
  return [["pictures", "Pictures"], ["list", "List"]].map(([key, text]) =>
    el("button", { type: "button", "aria-pressed": String(view.layout === key), "data-layout": key, text, onclick: (e) => {
      view.layout = key; local.set("receiptLayout", key);
      e.currentTarget.parentNode.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget)));
      rcptRefreshAll(view);
    } }));
}

/** The bulk tools of a part: {nodes, fill, fillButton}. inSheet: the phone's Tools sheet (each tool closes it). */
function rcptTools(view, comp, inSheet, done = () => {}) {
  const nodes = [];
  let fill = null, fillButton = null;
  if (comp.kind === "cards") {
    const cond = el("select", { "aria-label": "Condition to fill in" },
      RCPT_CONDITIONS.filter(Boolean).map((v) => el("option", { value: v, text: v })));
    const lang = el("select", { "aria-label": "Language to fill in" },
      RCPT_LANGUAGES.filter(Boolean).map((v) => el("option", { value: v, text: v.toUpperCase() })));
    fillButton = el("button", { type: "button", class: "btn", onclick: () => { done(); rcptFillBlanks(view, comp, cond.value, lang.value); } });
    fill = el("div", { class: "rcpt-fill", role: "group", "aria-label": "Fill in what isn't set yet" },
      el("span", { class: "rcpt-fill-label", text: "Not set yet →" }), cond, lang, fillButton);
    nodes.push(fill);
  }
  nodes.push(el("button", { type: "button", class: "btn", text: "Tick all", onclick: () => { done(); rcptTickAll(view, comp); } }),
    el("label", { class: "choice rcpt-clean" }, el("input", { type: "checkbox", checked: view.cleanOnTick || null,
      onchange: (e) => { if (!receiptEditable(view)) return; view.cleanOnTick = e.currentTarget.checked; rcptSyncCleanBoxes(view); } }),
    el("span", { text: "Clear “check on arrival” notes when ticked" })));
  if (fill) {
    const blanks = comp.rows.filter((row) => rcptBlank(comp, row)).length;
    fill.hidden = !blanks; fillButton.textContent = `Apply to ${plural(blanks, "row")}`;
  }
  if (inSheet) nodes.unshift(rcptField("Layout", el("div", { class: "segmented", role: "group", "aria-label": "Layout" }, rcptLayoutButtons(view))));
  return { nodes, fill, fillButton };
}

/** Keeps every "Clear notes when ticked" box (the toolbars' and the Tools sheet's) in step. */
function rcptSyncCleanBoxes(view) {
  document.querySelectorAll(".rcpt-clean input").forEach((box) => { box.checked = view.cleanOnTick; });
}

/** The phone's Tools sheet: the layout switch and the bulk tools. */
function rcptToolsSheet(view, comp) {
  if (!receiptEditable(view)) return;
  const sheet = openReceiptSheet(view, { title: "Tools" });
  const tools = rcptTools(view, comp, true, () => sheet.close());
  add(sheet.body, [el("div", { class: "rcpt-tools-sheet" }, tools.nodes)]);
  sheetActions(sheet, [{ text: "Done", kind: "primary", onclick: () => sheet.close() }]);
  return sheet;
}

/** A view preference joins an existing draft without changing the checked selection or its preview. */
function rcptSetFilter(view, key) {
  if (!receiptActive(view) || view.done) return;
  view.filter = RCPT_FILTERS.includes(key) ? key : "all";
  rcptRefreshAll(view);
  if (receiptEditable(view)) rcptSaveDraft(view);
}

/** Redraws every grid and toolbar state (a filter or layout change, a resumed draft). */
function rcptRefreshAll(view) {
  for (const comp of view.comps) {
    if (comp.kind === "product") continue;
    (comp.filterButtons || []).forEach((b) => b.setAttribute("aria-pressed", String(b.getAttribute("data-filter") === view.filter)));
    document.querySelectorAll("[data-layout]").forEach((b) => b.setAttribute("aria-pressed", String(b.getAttribute("data-layout") === view.layout)));
    comp.grid.setAttribute("class", rcptGridClass(view));
    rcptDrawGrid(view, comp);
  }
}

function rcptDrawGrid(view, comp) {
  clear(comp.grid);
  comp.allBlank = rcptAllBlank(comp);
  if (comp.allBlank) {
    comp.grid.append(el("p", { class: "sub rcpt-all-blank", text: "No card's condition or language is set yet. " +
      "Set them on each card as you check it, or all at once with “Not set yet”." }));
  }
  for (const row of comp.rows) {
    row.tile = rcptTile(view, comp, row, false);
    comp.grid.append(row.tile);
  }
  rcptEmptyState(view, comp);
  rcptToolbarCounts(view, comp);
}

/** A filter-specific empty message with Show all, when the filter leaves nothing to show. */
function rcptEmptyState(view, comp) {
  const old = comp.grid.querySelector(".rcpt-none");
  if (old) old.remove();
  if (comp.rows.some((row) => !row.tile.hidden)) return null;
  const none = el("div", { class: "empty rcpt-none" },
    el("p", { text: view.filter === "todo" ? "Everything here is checked."
      : view.filter === "ticked" ? "Nothing here is checked yet." : "Nothing here needs attention." }),
    el("button", { type: "button", class: "btn", text: "Show all", onclick: () => rcptSetFilter(view, "all") }));
  comp.grid.append(none);
  return none;
}

function rcptToolbarCounts(view, comp) {
  if (comp.fill) {
    const blanks = comp.rows.filter((row) => rcptBlank(comp, row)).length;
    comp.fill.hidden = !blanks;
    comp.fillButton.textContent = `Apply to ${plural(blanks, "row")}`;
  }
  if (comp.filterButtons) {
    const attention = comp.rows.filter((row) => rcptAttention(view, comp, row).length).length;
    const [wide, narrow] = comp.filterButtons[2].children;
    wide.textContent = attention ? `Needs attention (${plural(attention, "row")})` : "Needs attention";
    narrow.textContent = attention ? `Attention (${plural(attention, "row")})` : "Attention";
  }
}


// ------------------------------------------------------------------ tiles

/** What a row shows: {card, exact, why, set_name, finishes} (pictures from the server, or the printing picked here),
 * or null without card data. A token's comes from its faces' names (rcptTokenPicture). */
function rcptPicture(comp, row) {
  if (comp.kind === "tokens") return rcptTokenPicture(comp, row);
  if (row.pic) return row.pic;
  return comp.pictures ? comp.pictures[row.orig] || null : null;
}

/** A token row's pictures, worked out from the order's: each face named as the order named one of its faces
 * shows that face's picture (so Swap swaps them, and Back is blank drops the back's). A face renamed to
 * something else has no picture ("face changed"); a set or number changed keeps the ordered printing's
 * picture, marked as such ("printing changed"). */
function rcptTokenPicture(comp, row) {
  const base = comp.pictures ? comp.pictures[row.orig] || null : null;
  if (!base) return null;
  const was = comp.c.rows[row.orig] || {}, v = row.values;
  const face = (name) => (name && name === was.front ? [base.img || null, base.img_small || null, was.front_collector_number || ""]
    : name && name === was.back ? [base.back_img || null, base.back_img_small || null, was.back_collector_number || ""] : null);
  const front = face(v.front), back = v.back ? face(v.back) : null;
  const samePrinting = (v.set || "") === (was.set || "") && (!front || (v.front_collector_number || "") === front[2]);
  const why = !front ? "face changed" : !samePrinting ? "printing changed" : base.why;
  return { ...base, img: front ? front[0] : null, img_small: front ? front[1] : null,
    back_img: back ? back[0] : null, back_img_small: back ? back[1] : null,
    exact: Boolean(base.exact && front && samePrinting), why };
}

/** A token row as a card for the tile and the viewer: its front and back pictures as faces. */
function rcptTokenCard(comp, row) {
  const pic = rcptPicture(comp, row) || {};
  const v = row.values;
  const name = v.back ? `${v.front} // ${v.back}` : v.front;
  const faces = v.back ? [
    { name: v.front, type_line: v.front_details || "Front", img: pic.img || null, img_small: pic.img_small || null },
    { name: v.back, type_line: v.back_details || "Back", img: pic.back_img || null, img_small: pic.back_img_small || null }] : null;
  return { name, mana_cost: "", type_line: v.front_details || "Token", oracle_text: null,
    img: pic.img || null, img_small: pic.img_small || null, faces };
}

/** The row's card for a tile, a row or the sheet (a token's faces; a card's printing), or null. */
function rcptCard(comp, row) {
  return comp.kind === "tokens" ? rcptTokenCard(comp, row) : (rcptPicture(comp, row) || {}).card || null;
}

/** A row's printing and finish ("FDN 723 · Nonfoil"). chip: a finish chip shows beside these words (a tile or a
 * list row), so a foil or etched finish isn't said twice; the viewer's caption says it in words. */
function rcptMeta(comp, row, chip = false) {
  const v = row.values;
  if (comp.kind === "tokens") {
    const numbers = [v.front_collector_number, v.back && v.back_collector_number !== v.front_collector_number
      ? v.back_collector_number : ""].filter(Boolean).join("/");
    const printing = v.set ? `${v.set.toUpperCase()} ${numbers}`.trim() : "Printing not recorded";
    return [printing, rcptPT(v.front_details)].filter(Boolean).join(" · ");
  }
  const printing = v.set ? `${v.set.toUpperCase()} ${v.collector_number}` : "Printing not recorded";
  const finish = v.finish || "nonfoil";
  return chip && finishChip(finish) ? printing : `${printing} · ${capitalise(finish)}`;
}

/** The ribbon on a picture that isn't this row's printing, or null. */
function rcptUnrecorded(comp, row) {
  const pic = rcptPicture(comp, row);
  if (!pic || pic.exact) return null;
  if (pic.why === "face changed") return "No picture for this name";
  if (pic.why === "printing changed") return "Picture of the printing ordered";
  if (pic.why === "no picture") return "No picture for this printing";
  const v = row.values;
  const where = (comp.kind === "tokens" ? `${v.set} ${v.front_collector_number}` : `${v.set} ${v.collector_number}`).trim();
  return pic.why === "not recorded" || !v.set ? "Default picture: printing not recorded" : `Default picture: ${where} not in card data`;
}

/** The decks on this row's card: [{id, title, status, uses, waiting}] ([] without the decks). */
function rcptDecks(comp, row) {
  return comp.decks && comp.decks[row.orig] ? comp.decks[row.orig] : [];
}

/** The row's chips: condition and language, Edited, its split part, a note or check naming it, its back to
 * confirm (tokens), and where it goes. Only the exceptions, except the good "NM · EN" once both are known; what
 * isn't set yet is one chip ("Condition, language ?"), and none while no card has either (rcptAllBlank: one
 * line above the grid says it). */
function rcptChips(view, comp, row) {
  const v = row.values, chips = [];
  if (comp.kind === "cards") {
    if (v.condition && v.language) chips.push(status("good", `${v.condition} · ${v.language.toUpperCase()}`));
    else if (!v.condition && !v.language) {
      if (!rcptAllBlank(comp)) chips.push(status("warn", "Condition, language ?"));
    } else chips.push(status("warn", v.condition ? "Language ?" : "Condition ?"));
  } else if (comp.kind === "tokens" && rcptBackOpen(row)) chips.push(status("warn", "Back ?"));
  if (rcptEdited(comp, row)) chips.push(status("info", "Edited"));
  const parts = comp.rows.filter((r) => r.orig === row.orig);
  if (parts.length > 1) chips.push(el("span", { class: "chip chip-plain", text: `Split ${parts.indexOf(row) + 1} of ${parts.length}` }));
  const flag = rcptFlag(comp, row);
  if (flag) chips.push(el("span", { class: "chip chip-plain rcpt-flag", title: flag, text: "⚑ Note" }));
  const decks = rcptDecks(comp, row);
  const waiting = decks.filter((d) => d.waiting > 0);
  for (const d of waiting) chips.push(el("span", { class: "chip chip-info", title: `${d.title} counts on ${d.waiting} from this delivery`, text: `For ${rcptShortTitle(d.title)} ×${d.waiting}` }));
  if (!waiting.length) {
    const using = decks.filter((d) => d.status === "built" || d.status === "building");
    for (const d of using.slice(0, 2)) chips.push(el("span", { class: "chip chip-plain", title: `${d.title} lists ${d.uses}`, text: `${rcptShortTitle(d.title)} ×${d.uses}` }));
    if (using.length > 2) chips.push(el("span", { class: "chip chip-plain", text: `+${using.length - 2}` }));
  }
  return chips;
}

/** A row's notes worth a ⚑ (not the arrival notes, not "listed as …" provenance, not what Condition ? or
 * Back ? already says) and an unticked check that names its card, for the ⚑ chip; "" for none. */
function rcptFlag(comp, row) {
  const v = row.values;
  const backOpen = comp.kind === "tokens" && rcptBackOpen(row);
  const notes = rcptCleanNotes(v.notes, comp.kind, v).notes.split(/;\s*/).filter((p) => p && !RCPT_PROVENANCE.test(p)
    && !RCPT_BLANK_NOTE.test(p) && !(backOpen && (RCPT_UNVERIFIED.test(p) || /\bback\b|reverse|pairing/i.test(p))));
  const check = (comp.c.checks || []).find((text, i) => !comp.checks[i] && rcptCheckNames(comp, row, text));
  return [notes.join("; "), check].filter(Boolean).join(" · ");
}

/** True when a check names this row's card: a card's whole name as words; a token's two faces as a pair
 * (either way round). A single-faced token's check is about its back, which Back ? already shows. */
function rcptCheckNames(comp, row, text) {
  const v = row.values;
  if (comp.kind === "tokens") {
    if (!v.back || rcptBackOpen(row)) return false;
    return text.includes(`${v.front} // ${v.back}`) || text.includes(`${v.back} // ${v.front}`);
  }
  const name = frontName(v.name);
  if (!name) return false;
  const quoted = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(^|[^\\w'])${quoted}($|[^\\w'])`).test(text);
}

/** True when a token row's back still has to be confirmed: an unresolved pairing note, or a blank back that isn't
 * marked single-sided (the incoming rules refuse both). */
function rcptBackOpen(row) {
  const v = row.values;
  return RCPT_UNVERIFIED.test(v.notes || "") || (!v.back && !(v.notes || "").toLowerCase().includes(RCPT_SINGLE));
}

/** True when the row differs from what the order recorded: its printing, finish, faces or details, a
 * condition or language that was recorded and changed, or notes changed by hand (filling in a blank condition
 * or language, and clearing the arrival notes, don't count). */
function rcptEdited(comp, row) {
  const before = comp.kind === "product" ? null : comp.c.rows[row.orig];
  if (!before) return false;
  return Object.keys(before).some((key) => {
    if (key === "quantity") return false;
    const was = before[key] || "", now = row.values[key] || "";
    if (was === now) return false;
    if ((key === "condition" || key === "language") && !was) return false;
    if (key === "notes") {
      return now !== rcptCleanNotes(was, comp.kind).notes && now !== rcptCleanNotes(was, comp.kind, row.values).notes
        && now !== row.before;
    }
    return true;
  });
}

/** Why a row needs attention ([] for none): a blank condition or language, a note or check about it, a default
 * picture, an edit, a back to confirm. */
function rcptAttention(view, comp, row) {
  const why = [];
  if (rcptBlank(comp, row)) why.push("condition or language not set");
  if (comp.kind === "tokens" && rcptBackOpen(row)) why.push("back not confirmed");
  if (rcptFlag(comp, row)) why.push("a note");
  if (rcptUnrecorded(comp, row)) why.push("default picture");
  if (rcptEdited(comp, row)) why.push("edited");
  return why;
}

function rcptShown(view, comp, row) {
  if (view.filter === "todo") return !row.ticked;
  if (view.filter === "ticked") return row.ticked;
  if (view.filter === "attention") return rcptAttention(view, comp, row).length > 0;
  return true;
}

/** Replaces one row's tile in place (after a tick or an edit). */
function rcptRefreshTile(view, comp, row) {
  const parent = row.tile && row.tile.parentNode;
  // The first card given a condition or language brings the others' "not set" chips back: draw them all.
  if (!parent || typeof parent.replaceChild !== "function" || rcptAllBlank(comp) !== comp.allBlank) { rcptDrawGrid(view, comp); return; }
  const fresh = rcptTile(view, comp, row, false);
  parent.replaceChild(fresh, row.tile);
  row.tile = fresh;
  rcptEmptyState(view, comp);
  rcptToolbarCounts(view, comp);
}


// ------------------------------------------------------------------ ticks and bulk tools

/** Ticks or unticks a row. Ticking clears its "check on arrival" notes (when that's on); the sheet can put them
 * back. A change that hides the tile under a filter moves the focus to the next tile's tick, or to the empty
 * state's Show all. */
function rcptTick(view, comp, row, value) {
  if (!receiptEditable(view)) return;
  const focused = Boolean(row.tile) && row.tile.querySelector(".rcpt-tick") === document.activeElement;
  row.ticked = value;
  if (value) rcptTidyNotes(view, comp, row);
  rcptRefreshTile(view, comp, row);
  if (focused) rcptFocusAfterTick(view, comp, row);
  rcptChanged(view);
}

function rcptFocusAfterTick(view, comp, row) {
  if (!row.tile.hidden) { const again = row.tile.querySelector(".rcpt-tick"); if (again) again.focus(); return; }
  const at = comp.rows.indexOf(row);
  const visible = (r) => r.tile && !r.tile.hidden;
  const next = comp.rows.slice(at + 1).find(visible) || comp.rows.slice(0, at).reverse().find(visible);
  const target = next ? next.tile.querySelector(".rcpt-tick") : (rcptEmptyState(view, comp) || comp.grid).querySelector("button");
  if (target) target.focus();
}

async function rcptTickAll(view, comp) {
  if (!receiptEditable(view)) return;
  const left = comp.rows.filter((row) => !row.ticked);
  if (!left.length) { toast("Everything here is already ticked."); return; }
  const copies = left.reduce((n, row) => n + rcptQty(row), 0);
  const noun = comp.kind === "tokens" ? "token card" : "card";
  const answer = await askReceiptChoice(view, `Tick all ${plural(copies, noun)}?`,
    [`Only do this once you've checked every ${noun} in your hands against its picture.`],
    [{ text: "Cancel", value: null }, { text: `Tick all ${copies}`, kind: "primary", value: "yes" }]);
  if (answer !== "yes" || !receiptEditable(view)) return;
  for (const row of left) { row.ticked = true; rcptTidyNotes(view, comp, row); }
  rcptDrawGrid(view, comp);
  rcptChanged(view);
}

/** Fills in a condition and language wherever they're blank, with Undo. A ticked card's "not recorded" note
 * goes once both are filled in (and comes back with Undo). */
function rcptFillBlanks(view, comp, condition, language) {
  if (!receiptEditable(view)) return;
  const changed = comp.rows.filter((row) => rcptBlank(comp, row))
    .map((row) => ({ row, condition: row.values.condition, language: row.values.language, notes: row.values.notes, before: row.before }));
  if (!changed.length) return;
  for (const { row } of changed) {
    if (!row.values.condition) row.values.condition = condition;
    if (!row.values.language) row.values.language = language;
    rcptTidyNotes(view, comp, row);
  }
  rcptDrawGrid(view, comp); rcptChanged(view);
  showToast(`${condition} · ${language.toUpperCase()} filled in on ${plural(changed.length, "card")}.`, { undo: () => {
    if (!receiptEditable(view)) return;
    for (const item of changed) {
      Object.assign(item.row.values, { condition: item.condition, language: item.language, notes: item.notes });
      item.row.before = item.before;
    }
    if (receiptActive(view)) { rcptDrawGrid(view, comp); rcptChanged(view); }
  } });
}


// ------------------------------------------------------------------ the sheet

/** Opens a row's sheet (or shows another row in the open one). */
function rcptOpenSheet(view, comp, row) {
  if (!receiptEditable(view)) return;
  if (view.sheet && !view.sheet.sheet.closed) {
    view.sheet.comp = comp; view.sheet.row = row; rcptFillSheet(view); return;
  }
  const sheet = openReceiptSheet(view, { title: "", side: true, onClose: () => {
    const was = view.sheet; view.sheet = null;
    if (was && was.row.tile) {
      if (was.row.tile.hidden) rcptFocusAfterTick(view, was.comp, was.row);
      else if (was.row.open) was.row.open.focus();
    }
  } });
  view.sheet = { sheet, comp, row };
  rcptFillSheet(view);
}

function rcptFillSheet(view) {
  const { sheet, comp, row } = view.sheet;
  const v = row.values;
  sheet.heading.textContent = comp.kind === "tokens" ? (v.back ? `${v.front} // ${v.back}` : v.front) : v.name;
  const body = clear(sheet.body);
  add(body, [rcptSheetPicture(view, comp, row),
    comp.kind === "tokens" ? rcptTokenFields(view, comp, row) : rcptCardFields(view, comp, row),
    rcptCopies(view, comp, row)]);
  const decks = rcptDecks(comp, row);
  if (decks.length) {
    body.append(el("h3", { text: "Decks with this card" }), el("ul", { class: "rcpt-decks" }, decks.map((d) =>
      el("li", {}, el("a", { href: deckHref(d.id), text: d.title }),
        ` · ${STATUS_WORDS[d.status] || "Idea"}, lists ${d.uses}`,
        d.waiting ? el("strong", { text: ` · counts on ${d.waiting} from this delivery` }) : null))));
  }
  const visible = comp.rows.filter((r) => rcptShown(view, comp, r) || r === row);
  const next = visible[visible.indexOf(row) + 1] || null;
  sheetActions(sheet, [
    { text: row.ticked ? "Close" : "Tick and close", kind: "primary", onclick: () => {
      if (!row.ticked) rcptTick(view, comp, row, true);
      sheet.close();
    } },
    next ? { text: "Next card →", onclick: () => { view.sheet.row = next; rcptFillSheet(view); } } : null,
  ]);
}

/** The sheet's large picture: a tap opens the viewer over the grid's cards at this one; a sideways swipe moves to
 * the next or previous card on a phone. */
function rcptSheetPicture(view, comp, row) {
  const card = rcptCard(comp, row);
  const src = card && (card.img || card.img_small);
  const name = comp.kind === "tokens" ? row.values.front : row.values.name;
  const pic = src ? el("img", { src, alt: "", width: 244, height: 340, decoding: "async" })
    : el("span", { class: "rcpt-sheet-text", text: name });
  let drag = null, swiped = false;
  const button = el("button", { type: "button", class: "rcpt-sheet-pic", disabled: card ? null : true,
    "aria-label": card ? `Show ${name} larger, with its rules text` : name,
    onclick: (e) => { if (swiped) { swiped = false; return; } rcptZoom(view, comp, row, e.currentTarget, card); } }, pic);
  const visible = comp.rows.filter((r) => rcptShown(view, comp, r) || r === row);
  const at = visible.indexOf(row);
  const top = el("div", { class: "rcpt-sheet-top", onpointerdown: (e) => {
    if (e.button > 0 || e.isPrimary === false) return;
    // Navigation controls keep their own taps; the picture and surrounding space accept swipes.
    for (let n = e.target; n && n !== top; n = n.parentNode) {
      if (n.tagName === "BUTTON" && n !== button) return;
    }
    drag = { id: e.pointerId, x: e.clientX, y: e.clientY, horizontal: null }; swiped = false;
  }, onpointermove: (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (drag.horizontal == null && Math.max(Math.abs(dx), Math.abs(dy)) > 10) {
      drag.horizontal = Math.abs(dx) > Math.abs(dy);
      if (drag.horizontal) {
        try { top.setPointerCapture(e.pointerId); } catch (err) { /* pointer already gone */ }
      }
    }
    if (drag.horizontal && e.cancelable) e.preventDefault();
  }, onpointerup: (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    const horizontal = drag.horizontal; drag = null;
    if (horizontal !== false && Math.abs(dx) > 60 && Math.abs(dy) < 50) {
      swiped = true; rcptStepSheet(view, dx < 0 ? 1 : -1);
    }
  }, onpointercancel: () => { drag = null; } });
  if (visible.length > 1) top.append(
    el("div", { class: "rcpt-sheet-nav", "aria-label": "Cards in this delivery" },
      el("button", { type: "button", class: "btn", text: "\u2190 Previous", disabled: at === 0 || null,
        onclick: () => rcptStepSheet(view, -1) }),
      el("span", { class: "rcpt-sheet-count", text: `${at + 1} / ${visible.length}` }),
      el("button", { type: "button", class: "btn", text: "Next \u2192", disabled: at === visible.length - 1 || null,
        onclick: () => rcptStepSheet(view, 1) })),
    el("p", { class: "rcpt-sheet-hint", text: "Swipe left or right \u00b7 Tap the card to enlarge" }));
  top.append(button);
  return top;
}

function rcptStepSheet(view, dir) {
  const { comp, row } = view.sheet;
  const visible = comp.rows.filter((r) => rcptShown(view, comp, r) || r === row);
  const next = visible[visible.indexOf(row) + dir];
  if (next) { view.sheet.row = next; rcptFillSheet(view); }
}

/** The viewer over this grid's cards, from this row's (one card when the grid has no group). */
function rcptZoom(view, comp, row, trigger, card) {
  const group = row.open ? viewerGroup(row.open) : null;
  if (group) openCardViewer(group.items, group.index, { trigger });
  else if (card) openCardViewer([card], 0, { trigger });
}

function rcptSegmented(label, options, current, onpick) {
  const buttons = options.map(([value, text]) => el("button", { type: "button", "aria-pressed": String(value === current),
    text, onclick: () => { buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(options[i][0] === value))); onpick(value); } }));
  return el("div", { class: "segmented", role: "group", "aria-label": label }, buttons);
}

function rcptField(label, control, hint) {
  return el("div", { class: "field rcpt-field" }, el("span", { text: label }), control,
    hint ? el("span", { class: "field-hint", text: hint }) : null);
}

/** A cards row's fields: printing (with the picker), finish, condition, language and notes. */
function rcptCardFields(view, comp, row) {
  const v = row.values;
  const pic = rcptPicture(comp, row);
  const update = (changes) => {
    if (!receiptEditable(view)) return;
    Object.assign(v, changes);
    if ("condition" in changes || "language" in changes) rcptTidyNotes(view, comp, row);
    rcptRowChanged(view, comp, row);
  };
  const printing = el("div", { class: "rcpt-printing" },
    el("p", {}, el("strong", { class: "rcpt-mono", text: v.set ? `${v.set.toUpperCase()} ${v.collector_number}` : "Printing not recorded" }),
      pic && pic.set_name ? ` · ${pic.set_name}` : ""),
    el("button", { type: "button", class: "btn", text: "Different printing…", onclick: async () => {
      if (!receiptEditable(view)) return;
      let picker;
      const chosen = await pickPrinting(v.name, { current: { set: v.set, number: v.collector_number, finish: v.finish },
        title: `${frontName(v.name)}: which printing arrived?`, onOpen: sheet => { picker = sheet; receiptSheets.add(sheet); } });
      receiptSheets.delete(picker);
      if (!chosen || !chosen.set || !receiptEditable(view)) return;
      const base = pic && pic.card ? pic.card : { name: v.name, mana_cost: "", type_line: "", oracle_text: "" };
      row.pic = { card: rcptWithPicture(base, chosen), exact: true, why: null, set_name: chosen.set_name || chosen.set.toUpperCase(),
        finishes: null };
      update({ set: chosen.set, collector_number: chosen.number, finish: chosen.finish || "nonfoil" });
      rcptFinishes(view, v.name, chosen.set, chosen.number).then((found) => {
        if (!row.pic || !found || !receiptActive(view)) return;
        row.pic.finishes = found; rcptSaveDraft(view);
        if (view.sheet && view.sheet.row === row) rcptFillSheet(view);
      });
      if (view.sheet && view.sheet.row === row) rcptFillSheet(view);
    } }));
  const finishes = (pic && pic.finishes && pic.finishes.length ? pic.finishes : [v.finish || "nonfoil"]);
  const finish = finishes.length > 1
    ? rcptSegmented("Finish", finishes.map((f) => [f, capitalise(f)]), v.finish, (value) => update({ finish: value }))
    : el("p", { class: "rcpt-fixed", text: capitalise(finishes[0]) });
  const conditions = RCPT_CONDITIONS.includes(v.condition) ? RCPT_CONDITIONS : [...RCPT_CONDITIONS, v.condition];
  const condition = rcptSegmented("Condition", conditions.map((c) => [c, c || "?"]), v.condition || "", (value) => update({ condition: value }));
  const languages = RCPT_LANGUAGES.includes(v.language) ? RCPT_LANGUAGES : [...RCPT_LANGUAGES, v.language];
  const language = el("select", { "aria-label": "Language", onchange: (e) => update({ language: e.currentTarget.value }) },
    languages.map((code) => el("option", { value: code, selected: code === (v.language || "") || null,
      text: code ? `${code.toUpperCase()} · ${RCPT_LANGUAGE_WORDS[code] || code}` : "Not known" })));
  return [rcptField("Printing", printing), rcptField("Finish", finish),
    rcptField("Condition", condition, v.condition ? null : "? means not known: it stays blank."),
    rcptField("Language", language), ...rcptNotesField(view, comp, row)];
}

/** card with another printing's pictures (the picker's /img/ addresses; a double-faced card's back too). */
function rcptWithPicture(card, chosen) {
  const back = (size) => chosen.img && chosen.set ? `/img/${chosen.set}/${encodeURIComponent(chosen.number)}/${size}-back` : null;
  return { ...card, img: chosen.img || null, img_small: chosen.img_small || null,
    faces: card.faces ? card.faces.map((f, i) => ({ ...f,
      img: i === 0 ? chosen.img || null : f.img && f.img !== card.img ? back("normal") : chosen.img || null,
      img_small: i === 0 ? chosen.img_small || null : f.img_small && f.img_small !== card.img_small ? back("small") : chosen.img_small || null })) : card.faces };
}

/** A printing's entries in the printings list, one per finish ([] when it can't be told; asked once per card). */
function rcptLookupPrinting(view, name, set, number) {
  view.printings = view.printings || new Map();
  if (!view.printings.has(name)) {
    view.printings.set(name, api(`/api/cards/printings?name=${encodeURIComponent(name)}`).catch(() => null));
  }
  return view.printings.get(name).then((answer) => answer ? (answer.printings || [])
    .filter((p) => p.set === set && p.number === number) : []);
}

/** The finishes a printing has ([] when it can't be told). */
function rcptFinishes(view, name, set, number) {
  return rcptLookupPrinting(view, name, set, number).then((found) => found.map((p) => p.finish));
}

/** The notes, with a way to clear the "check on arrival" parts or put them back. */
function rcptNotesField(view, comp, row) {
  const v = row.values;
  const area = el("textarea", { "aria-label": "Notes", maxlength: 2000, rows: 3,
    oninput: (e) => { if (!receiptEditable(view)) return; v.notes = e.currentTarget.value; rcptRowChanged(view, comp, row); } });
  area.value = v.notes || "";
  const clean = rcptCleanNotes(v.notes, comp.kind, v);
  const tool = clean.removed
    ? el("button", { type: "button", class: "btn btn-quiet", text: "Remove the “check on arrival” note", onclick: () => {
      if (!receiptEditable(view)) return;
      row.before = v.notes; v.notes = clean.notes; rcptRowChanged(view, comp, row); rcptFillSheet(view);
    } })
    : row.before && row.before !== v.notes
      ? el("button", { type: "button", class: "btn btn-quiet", text: "Put the note back", onclick: () => {
        if (!receiptEditable(view)) return;
        v.notes = row.before; row.before = null; rcptRowChanged(view, comp, row); rcptFillSheet(view);
      } }) : null;
  return [rcptField("Notes", area), tool];
}

/** A token row's fields: its faces (with Swap), Back is blank, its printing and details, and notes. */
function rcptTokenFields(view, comp, row) {
  const v = row.values;
  const listId = `rcpt-faces-${comp.index}`;
  const names = view.data.face_names || [];
  const datalist = names.length && !document.getElementById(listId)
    ? el("datalist", { id: listId }, names.map((name) => el("option", { value: name }))) : null;
  const face = (key, label) => {
    const input = el("input", { type: "text", "aria-label": label, list: names.length ? listId : null, maxlength: 200,
      onchange: (e) => {
        if (!receiptEditable(view)) return;
        const value = e.currentTarget.value.trim();
        const changes = { [key]: value };
        if (key === "back" && value) {
          changes.notes = rcptNotesWithout(v.notes, (p) => RCPT_UNVERIFIED.test(p) || p.toLowerCase() === RCPT_SINGLE);
        }
        Object.assign(v, changes);        // the pictures follow the names (rcptTokenPicture)
        rcptRowChanged(view, comp, row); rcptFillSheet(view);
      } });
    input.value = v[key] || "";
    return input;
  };
  const single = !v.back && (v.notes || "").toLowerCase().includes(RCPT_SINGLE);
  const blank = el("label", { class: "choice rcpt-blank" }, el("input", { type: "checkbox", checked: single || null,
    onchange: (e) => {
      if (!receiptEditable(view)) return;
      if (e.currentTarget.checked) {
        const notes = rcptNotesWithout(v.notes, (p) => RCPT_UNVERIFIED.test(p) || RCPT_ARRIVAL_NOTE.test(p) || RCPT_LISTING_NOTE.test(p));
        Object.assign(v, { back: "", back_collector_number: "", back_details: "",
          notes: [notes, RCPT_SINGLE].filter(Boolean).join("; ") });
      } else {
        v.notes = rcptNotesWithout(v.notes, (p) => p.toLowerCase() === RCPT_SINGLE);
      }
      rcptRowChanged(view, comp, row); rcptFillSheet(view);
    } }), el("span", { text: "Back is blank (a single-sided card)" }));
  const swap = el("button", { type: "button", class: "btn", text: "Swap front and back", disabled: v.back ? null : true,
    onclick: () => {
      if (!receiptEditable(view)) return;
      Object.assign(v, { front: v.back, back: v.front, front_collector_number: v.back_collector_number,
        back_collector_number: v.front_collector_number, front_details: v.back_details, back_details: v.front_details });
      rcptRowChanged(view, comp, row); rcptFillSheet(view);
    } });
  const text = (key, label, extra = {}, hint = null) => {
    const input = el("input", { type: "text", "aria-label": label, maxlength: 200, ...extra,
      oninput: (e) => { if (!receiptEditable(view)) return; v[key] = e.currentTarget.value; rcptRowChanged(view, comp, row); } });
    input.value = v[key] || "";
    return rcptField(label, input, hint);
  };
  // Details, with the "Read as" line under them: typing redraws only that line, so the field keeps its focus.
  const details = (key, label) => {
    const reading = tokReadingLine((fixed) => {
      if (!receiptEditable(view)) return;
      v[key] = fixed; rcptRowChanged(view, comp, row); rcptFillSheet(view);
    }, view.data.keywords || undefined, names);
    const input = el("input", { type: "text", "aria-label": label, maxlength: 200, placeholder: "e.g. 4/4; white; flying",
      oninput: (e) => {
        if (!receiptEditable(view)) return;
        v[key] = e.currentTarget.value; rcptRowChanged(view, comp, row); reading.refresh(v[key]);
      } });
    input.value = v[key] || "";
    reading.refresh(input.value);
    const field = rcptField(label, input);
    field.append(reading);
    return field;
  };
  const open = rcptBackOpen(row);
  return [datalist,
    open ? el("p", { class: "note note-warn", text: v.back ? "Check the back really is this card, or change it." : "Is the back blank, or another token? Say which below." }) : null,
    rcptField("Front: token name", face("front", "Front token name")), rcptNameFix(view, comp, row, "front", names),
    details("front_details", "Front details"),
    rcptField(open && v.back ? "Back is really (token name)" : "Back: token name", face("back", "Back token name"),
      v.back ? null : "Leave it empty only for a single-sided card."),
    rcptNameFix(view, comp, row, "back", names),
    details("back_details", "Back details"),
    el("p", { class: "field-hint", text: "A name is just the token's name, as Scryfall has it (Angel, Fish, Human Soldier). "
      + "Its power/toughness, colour and abilities go in details, separated by ';'. Leave details blank if you haven't checked." }),
    el("div", { class: "actions rcpt-face-tools" }, swap), blank,
    el("details", { class: "rcpt-more-fields" }, el("summary", { text: "Printing" }),
      el("div", { class: "rcpt-fields" }, text("set", "Set code"), text("front_collector_number", "Front number"),
        text("back_collector_number", "Back number"), text("finish", "Finish"))),
    ...rcptNotesField(view, comp, row)];
}

/** Under a face name that isn't a Scryfall token name: what's wrong, and a one-tap fix when the name was
 * typed with its traits ("White Angel 4/4 flying": Angel, with "4/4; white; flying" in its details) or
 * spelt a little differently. Saving still refuses a name Scryfall doesn't have. */
function rcptNameFix(view, comp, row, side, names) {
  const v = row.values;
  const typed = (v[side] || "").trim();
  if (!typed || !names.length || names.includes(typed)) return null;
  const split = tokSplitDescription(typed, names);
  const better = split ? null : tokSuggest(typed, names);
  const words = side === "back" ? "Back" : "Front";
  const apply = (changes) => () => {
    if (!receiptEditable(view)) return;
    Object.assign(v, changes); rcptRowChanged(view, comp, row); rcptFillSheet(view);
  };
  return el("div", { class: "note note-warn", role: "status" },
    el("p", { text: `'${typed}' isn't a token name on Scryfall.` }),
    split ? el("button", { type: "button", class: "btn",
      text: `Use ${split.name}, with "${split.details}" in ${words} details`,
      onclick: apply({ [side]: split.name, [`${side}_details`]: split.details }) })
      : better ? el("button", { type: "button", class: "btn", text: `Did you mean ${better}?`, onclick: apply({ [side]: better }) })
        : el("p", { text: "Type the token's name and pick it from the suggestions." }));
}

/** The copies (fixed), and splitting them into two tiles or merging the parts back. */
function rcptCopies(view, comp, row) {
  const q = rcptQty(row);
  const parts = comp.rows.filter((r) => r.orig === row.orig);
  const out = [el("h3", { text: "Copies" }), el("p", { text: `${plural(q, "copy", "copies")} in this tile. The order's total stays the same.` })];
  if (q > 1) {
    let k = 1;
    const shown = el("output", { class: "rcpt-k", text: "1" });
    const minus = el("button", { type: "button", class: "step", "aria-label": "One fewer", disabled: true, text: "−" });
    const plusB = el("button", { type: "button", class: "step", "aria-label": "One more", disabled: q - 1 <= 1 || null, text: "+" });
    const set = (n) => { k = Math.max(1, Math.min(q - 1, n)); shown.textContent = String(k);
      minus.disabled = k <= 1; plusB.disabled = k >= q - 1; };
    minus.addEventListener("click", () => set(k - 1)); plusB.addEventListener("click", () => set(k + 1));
    out.push(el("div", { class: "rcpt-split" }, el("span", { text: "Move" }),
      el("div", { class: "stepper", role: "group", "aria-label": "Copies to move" }, minus, shown, plusB),
      el("button", { type: "button", class: "btn", text: "Split into a new tile", onclick: () => rcptSplit(view, comp, row, k) })));
  }
  if (parts.length > 1) {
    out.push(el("button", { type: "button", class: "btn btn-quiet", text: "Merge back", onclick: () => rcptMerge(view, comp, row) }));
  }
  return out;
}

function rcptSplit(view, comp, row, k) {
  if (!receiptEditable(view)) return;
  const q = rcptQty(row);
  if (k < 1 || k >= q) return;
  row.values.quantity = String(q - k);
  const part = { key: ++rcptKeys, orig: row.orig, values: { ...row.values, quantity: String(k) }, ticked: false,
    before: row.before, pic: row.pic };
  comp.rows.splice(comp.rows.indexOf(row) + 1, 0, part);
  rcptDrawGrid(view, comp); rcptChanged(view);
  if (view.sheet) { view.sheet.row = part; rcptFillSheet(view); }
}

/** Merges a card's split parts back into one tile. Parts that differ (a condition, a printing, notes) are only
 * merged once the person agrees to keep the first part's; either way Undo puts the parts back. */
async function rcptMerge(view, comp, row) {
  if (!receiptEditable(view)) return;
  const parts = comp.rows.filter((r) => r.orig === row.orig);
  const first = parts[0];
  const facts = (r) => JSON.stringify({ ...r.values, quantity: "" });
  if (parts.some((r) => facts(r) !== facts(first))) {
    const answer = await askReceiptChoice(view, "Merge parts that differ?", [
      "The parts don't say the same thing (a condition, language, printing or notes). Merging keeps what the first part says for all the copies."],
    [{ text: "Cancel", value: null }, { text: "Merge, keeping the first part's", kind: "primary", value: "yes" }]);
    if (answer !== "yes" || !receiptEditable(view)) return;
  }
  const rowsBefore = comp.rows.slice();
  const saved = parts.map((r) => ({ r, values: { ...r.values }, ticked: r.ticked }));
  first.values.quantity = String(parts.reduce((n, r) => n + rcptQty(r), 0));
  first.ticked = parts.every((r) => r.ticked);
  comp.rows = comp.rows.filter((r) => r.orig !== row.orig || r === first);
  rcptDrawGrid(view, comp); rcptChanged(view);
  if (view.sheet) { view.sheet.row = first; rcptFillSheet(view); }
  showToast(`Merged ${plural(parts.length, "part")} into one tile.`, { undo: () => {
    if (!receiptEditable(view)) return;
    for (const item of saved) { item.r.values = item.values; item.r.ticked = item.ticked; }
    comp.rows = rowsBefore;
    if (receiptActive(view)) { rcptDrawGrid(view, comp); rcptChanged(view); if (view.sheet) rcptFillSheet(view); }
  } });
}

/** After an edit in the sheet: the row's tile, the counts, the draft and the bar. */
function rcptRowChanged(view, comp, row) {
  if (!receiptEditable(view)) return;
  rcptRefreshTile(view, comp, row);
  rcptChanged(view);
}


// ------------------------------------------------------------------ products

/** The two choice cards for a product: keep it as its own deck(s), or break it up into storage. */
function rcptIntactChoice(view, comp) {
  const decks = comp.rows.some((row) => row.values.section || row.values.deck);
  const card = (value, title, words, disabled) => el("button", { type: "button", class: "rcpt-choice-card",
    "aria-pressed": String(comp.intact === value), disabled: disabled || null, "data-intact": value,
    onclick: () => { if (!receiptEditable(view)) return; comp.intact = value; comp.choice.querySelectorAll("button").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.getAttribute("data-intact") === value))); rcptChanged(view); } },
  el("strong", { text: title }), el("span", { text: words }));
  comp.choice = el("div", { class: "rcpt-choices", id: `rcpt-${comp.index}-intact`, role: "group", "aria-label": "What to do with it" },
    card("yes", "Keep it as its own deck(s)", decks ? "In its own sleeves and deck box; its cards stay out of the shared pool."
      : "It has no deck lists, so there's nothing to keep together.", !decks),
    card("no", "Break it up into storage", "Its cards go into the storage box, free for any deck."));
  return comp.choice;
}

/** A product's cards as read-only tiles: by deck, then section with the Commander first; basic lands folded away. */
function rcptProductGrid(view, comp, readOnly) {
  clear(comp.grid);
  comp.grid.setAttribute("class", "rcpt-product");
  const order = (s) => (s === "commander" ? 0 : s === "deck" || !s ? 1 : s === "sideboard" ? 3 : 2);
  const groups = new Map();
  for (const row of comp.rows) {
    const key = `${row.values.deck || ""}|${(row.values.section || "").toLowerCase()}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  const keys = [...groups.keys()].sort((a, b) => {
    const [da, sa] = a.split("|"), [db, sb] = b.split("|");
    return da.localeCompare(db) || order(sa) - order(sb) || sa.localeCompare(sb);
  });
  if (!comp.rows.length) { comp.grid.append(el("p", { class: "sub", text: "Its card list couldn't be read." })); return; }
  for (const key of keys) {
    const [deck, section] = key.split("|");
    const rows = groups.get(key);
    const basics = rows.filter((row) => rcptIsBasic(row.values.name));
    const rest = rows.filter((row) => !basics.includes(row));
    const title = [deck, section ? capitalise(section) : keys.length > 1 ? "Cards" : ""].filter(Boolean).join(" · ");
    const count = rows.reduce((n, row) => n + rcptQty(row), 0);
    comp.grid.append(el("div", { class: "rcpt-product-group" },
      title ? el("h3", { text: `${title} (${count})` }) : null,
      el("div", { class: "card-tiles rcpt-grid" }, rest.map((row) => rcptTile(view, comp, row, true))),
      basics.length ? el("details", { class: "rcpt-basics" },
        el("summary", { text: plural(basics.reduce((n, row) => n + rcptQty(row), 0), "basic land") }),
        el("div", { class: "card-tiles rcpt-grid" }, basics.map((row) => rcptTile(view, comp, row, true)))) : null));
  }
}
