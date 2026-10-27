/* The Collection page's "Record a trade…" (E7-S22): pick the listed rows whose copies left, enter the cards
 * that came in (the add-card sheet's fields: name suggestions, printing strip, finish, copies, condition,
 * language and notes), an optional who-with note and message, then Preview: POST /api/collection/trade/preview
 * says what each row keeps, the built decks or intact products left short and the decks' tables it would
 * leave out of date. Held copies need "Save it anyway" ticked (the preview's review token). Save Trade
 * (POST /api/collection/trade) is one change set; the page then says so with the Tables out of date link
 * (colChanged). No prices anywhere. Shared with collection.js (openTradeSheet). */
"use strict";

const COL_TRADE_FOUND = 8;          // rows the "cards that left" search lists at most
const COL_TRADE_WITH_MAX = 80;      // collection_trade.MAX_WITH
const COL_TRADE_MESSAGE_MAX = 200;  // collection_trade.MAX_MESSAGE

/** Open the sheet (where the visitor may change this collection). Resolves with its context, or null. */
async function openTradeSheet(cv) {
  if (!colActive(cv) || cv.busy || !cv.editable) return null;
  try {
    await colEnsureRows(cv);
  } catch (error) {
    if (colActive(cv)) colSay(cv, `The collection couldn't be loaded: ${error.message}`);
    return null;
  }
  if (!colActive(cv) || cv.busy) return null;
  const sheet = colOpenSheet(`Record a trade in ${colWhose(cv.space)}`, { wide: true });
  const id = (key) => `col-trade-${key}-${sheet.heading.id}`;
  const ctx = { cv, sheet, gave: [], got: [], busy: false, review: null };
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.search = el("input", { id: id("search"), type: "search", autocomplete: "off", spellcheck: "false",
    placeholder: "Card name or set", oninput: () => drawTradeFound(ctx) });
  ctx.found = el("div", { class: "col-trade-found" });
  ctx.gaveList = el("ul", { class: "col-trade-list col-trade-gave" });
  ctx.gotList = el("ul", { class: "col-trade-list col-trade-got" });
  ctx.adder = el("div", { class: "col-trade-adder" });
  ctx.with = el("input", { id: id("with"), type: "text", maxlength: COL_TRADE_WITH_MAX, autocomplete: "off",
    placeholder: "e.g. a friend at the shop" });
  ctx.note = el("input", { id: id("note"), type: "text", maxlength: COL_TRADE_MESSAGE_MAX, autocomplete: "off" });
  ctx.edit = el("div", { class: "col-form col-trade" },
    el("section", { class: "col-trade-side", "aria-labelledby": id("gave-h") },
      el("h3", { id: id("gave-h"), text: "Cards that left" }),
      el("label", { class: "field", for: ctx.search.id }, el("span", { text: "Find a listed card" }), ctx.search),
      ctx.found, ctx.gaveList),
    el("section", { class: "col-trade-side", "aria-labelledby": id("got-h") },
      el("h3", { id: id("got-h"), text: "Cards that came in" }), ctx.gotList, ctx.adder),
    el("label", { class: "field", for: ctx.with.id }, el("span", { text: "Who with (optional)" }), ctx.with),
    el("label", { class: "field", for: ctx.note.id }, el("span", { text: "Note for the history (optional)" }), ctx.note));
  ctx.reviewBox = el("div", { class: "col-trade-review", hidden: true });
  sheet.body.append(ctx.message, ctx.edit, ctx.reviewBox);
  drawTradeFound(ctx);
  drawTradeLists(ctx);
  newTradeCard(ctx);
  drawTradeEdit(ctx);
  ctx.search.focus();
  return ctx;
}

function colTradeSay(ctx, kind, ...paragraphs) {
  clear(ctx.message);
  if (!paragraphs.length) return;
  ctx.message.append(el("div", { class: `box box-${kind}`, role: kind === "info" ? null : "alert" },
    paragraphs.map((text) => el("p", { text }))));
}

/** "Llanowar Elves (FDN 227 · Foil)". */
function colTradeLabel(row) {
  return `${row.name} (${colPrinting(row)})`;
}

/** The listed rows the search finds (those not already picked), each a button that adds it to the cards that left. */
function drawTradeFound(ctx) {
  const words = tokFold(ctx.search.value.trim());
  clear(ctx.found);
  if (!words) {
    ctx.found.append(el("p", { class: "sub", text: (ctx.cv.rows || []).length ? "Type a card's name or set to find its row."
      : "The collection has no cards yet." }));
    return;
  }
  const picked = new Set(ctx.gave.map((g) => colKey(g.row)));
  const rows = (ctx.cv.rows || []).filter((row) => !picked.has(colKey(row))
    && (tokFold(row.name).includes(words) || tokFold(row.set).includes(words)))
    .sort((a, b) => String(a.name).localeCompare(String(b.name)) || colKey(a).localeCompare(colKey(b)));
  if (!rows.length) { ctx.found.append(el("p", { class: "sub", text: "No listed card matches." })); return; }
  add(ctx.found, [el("div", { class: "col-trade-choices", role: "group", "aria-label": "Listed cards" },
    rows.slice(0, COL_TRADE_FOUND).map((row) => el("button", { type: "button", class: "btn btn-quiet col-trade-pick",
      "aria-label": `Gave ${colTradeLabel(row)}, ${plural(Number(row.quantity), "copy", "copies")} listed`,
      onclick: () => {
        if (ctx.busy) return;
        ctx.gave.push({ row, quantity: 1 });
        ctx.search.value = "";
        drawTradeFound(ctx); drawTradeLists(ctx); drawTradeEdit(ctx);
        ctx.search.focus();
      } }, `${colTradeLabel(row)} · ${num(Number(row.quantity))} listed`))),
    rows.length > COL_TRADE_FOUND ? el("p", { class: "sub", text: `${num(rows.length - COL_TRADE_FOUND)} more: type more of the name.` }) : null]);
}

/** Both sides as lists: each given row with a stepper (1 to its listed copies), each card got with Take out. */
function drawTradeLists(ctx) {
  clear(ctx.gaveList);
  ctx.gave.forEach((item, i) => {
    const most = Number(item.row.quantity);
    const input = el("input", { type: "number", class: "col-qty-input", inputmode: "numeric", min: 1, max: most, step: 1,
      value: String(item.quantity), "aria-label": `Copies of ${item.row.name} given`,
      onchange: () => { item.quantity = Math.min(most, Math.max(1, parseInt(input.value, 10) || 1)); input.value = String(item.quantity); } });
    const step = (by) => { item.quantity = Math.min(most, Math.max(1, item.quantity + by)); input.value = String(item.quantity); };
    ctx.gaveList.append(el("li", { class: "col-trade-line" },
      el("span", { class: "col-trade-what", text: colTradeLabel(item.row) }),
      el("span", { class: "sub", text: `of ${num(most)}` }),
      el("div", { class: "stepper col-stepper" },
        el("button", { type: "button", class: "step", "aria-label": "One fewer", onclick: () => step(-1) }, "−"), input,
        el("button", { type: "button", class: "step", "aria-label": "One more", onclick: () => step(1) }, "+")),
      el("button", { type: "button", class: "btn btn-quiet", text: "Take out", "aria-label": `Take ${item.row.name} out of the trade`,
        onclick: () => { if (ctx.busy) return; ctx.gave.splice(i, 1); drawTradeFound(ctx); drawTradeLists(ctx); drawTradeEdit(ctx); ctx.search.focus(); } })));
  });
  if (!ctx.gave.length) ctx.gaveList.append(el("li", { class: "sub", text: "Nothing yet." }));
  clear(ctx.gotList);
  ctx.got.forEach((row, i) => ctx.gotList.append(el("li", { class: "col-trade-line" },
    el("span", { class: "col-trade-what", text: `${row.quantity} × ${colTradeLabel(row)}` }),
    el("span", { class: "sub", text: [row.condition, row.language].filter(Boolean).join(" · ") }),
    el("button", { type: "button", class: "btn btn-quiet", text: "Take out", "aria-label": `Take ${row.name} out of the trade`,
      onclick: () => { if (ctx.busy) return; ctx.got.splice(i, 1); drawTradeLists(ctx); drawTradeEdit(ctx); } }))));
  if (!ctx.got.length) ctx.gotList.append(el("li", { class: "sub", text: "Nothing yet." }));
}

/** The add-card sheet's fields (collection-cards.js colFields) for the next card that came in, with "Add to the trade". */
function newTradeCard(ctx) {
  const card = { cv: ctx.cv, sheet: ctx.sheet, row: null, editing: false, base: null, busy: false, printings: [], chosen: -1,
    nameSeq: 0, printSeq: 0, suggestTimer: 0, stripFilter: "", boxRepair: null };
  card.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  card.form = el("form", { class: "col-form", novalidate: true, onsubmit: (event) => { event.preventDefault(); addTradeCard(ctx); } });
  card.form.append(card.message, colFields(card, null));
  ctx.card = card;
  clear(ctx.adder).append(el("p", { class: "col-trade-adder-title", text: "Add a card that came in" }), card.form, el("div", { class: "actions" },
    el("button", { type: "button", class: "btn col-sheet-mutate col-trade-add", text: "Add to the trade", onclick: () => addTradeCard(ctx) })));
  colFillFinishes(card);
}

function addTradeCard(ctx) {
  if (ctx.busy || ctx.sheet.closed) return;
  const row = colFormRow(ctx.card);
  if (!row) return;
  const same = ctx.got.find((r) => colKey(r) === colKey(row) && r.condition === row.condition && r.language === row.language
    && r.notes === row.notes);
  if (same) same.quantity = Math.min(9999, Number(same.quantity) + row.quantity);
  else ctx.got.push(row);
  newTradeCard(ctx);
  drawTradeLists(ctx);
  drawTradeEdit(ctx);
  ctx.card.inputs.name.focus();
}

/** The first step's foot: Cancel and Preview, which can't act until both sides have cards (it says why). */
function drawTradeEdit(ctx) {
  const missing = !ctx.gave.length ? "Add the cards that left first." : !ctx.got.length ? "Add the cards that came in first." : "";
  sheetActions(ctx.sheet, [{ text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() },
    { text: "Preview trade", kind: "primary", value: "preview", onclick: () => {
      if (missing) {
        colTradeSay(ctx, "warn", missing);
        (ctx.gave.length ? ctx.card.inputs.name : ctx.search).focus();
        return;
      }
      previewTrade(ctx);
    } }]);
  const button = ctx.sheet.foot.querySelector('[data-action="preview"]');
  if (missing) { button.setAttribute("aria-disabled", "true"); button.title = missing; }
}

function colTradeBody(ctx) {
  const body = { space: ctx.cv.space, sha256: ctx.cv.sha256,
    gave: ctx.gave.map(({ row, quantity }) => ({ set: row.set, collector_number: row.collector_number, finish: row.finish, quantity })),
    got: ctx.got.map((row) => ({ ...row })) };
  const who = ctx.with.value.replace(/\s+/g, " ").trim();
  const note = ctx.note.value.replace(/\s+/g, " ").trim();
  if (who) body.with = who;
  if (note) body.message = note;
  return body;
}

function colTradeBusy(ctx, busy) {
  ctx.busy = busy;
  for (const control of ctx.sheet.body.querySelectorAll("button, input, select")) control.disabled = busy;
  for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = busy;
}

async function previewTrade(ctx) {
  const cv = ctx.cv;
  if (ctx.busy || ctx.sheet.closed || !colActive(cv)) return;
  const body = colTradeBody(ctx);
  colTradeBusy(ctx, true);
  clear(ctx.message).append(loadingBox("Working out the trade…", { small: true }));
  try {
    const answer = await apiWrite("/api/collection/trade/preview", body);
    if (ctx.sheet.closed || !colActive(cv)) return;
    colTradeBusy(ctx, false);
    clear(ctx.message);
    ctx.review = { body, answer };
    drawTradeReview(ctx);
  } catch (error) {
    if (ctx.sheet.closed || !colActive(cv)) return;
    colTradeBusy(ctx, false);
    colTradeFailed(ctx, error);
  }
}

/** A refusal: a collection changed meanwhile shows the latest rows (keeping what's still listed); anything else says why. */
function colTradeFailed(ctx, error) {
  const cv = ctx.cv;
  if (error.status === 409 && error.data && Array.isArray(error.data.rows) && !error.data.in_use) {
    cv.sha256 = error.data.sha256;
    colTakeRows(cv, error.data);
    if (cv.kind === "rows") drawColRowList(cv);
    const now = new Map(cv.rows.map((row) => [colKey(row), row]));
    const dropped = ctx.gave.filter((g) => !now.has(colKey(g.row)));
    ctx.gave = ctx.gave.filter((g) => now.has(colKey(g.row))).map((g) => {
      const row = now.get(colKey(g.row));
      return { row, quantity: Math.min(g.quantity, Number(row.quantity)) };
    });
    showTradeEdit(ctx);
    colTradeSay(ctx, "warn", error.message, dropped.length ? `No longer listed, so taken out of the cards that left: ${dropped.map((g) => g.row.name).join(", ")}.`
      : "The cards that left are still listed.", "Nothing was saved. Check the trade against the latest list, then preview it again.");
    return;
  }
  colTradeSay(ctx, "crit", error.message);
}

function showTradeEdit(ctx) {
  ctx.review = null;
  ctx.reviewBox.hidden = true;
  ctx.edit.hidden = false;
  drawTradeFound(ctx);
  drawTradeLists(ctx);
  drawTradeEdit(ctx);
}

/** The preview: what each side does, the decks left short (with Save it anyway), the tables it leaves out of date
 * and the change history's words; Back and Save trade. */
function drawTradeReview(ctx) {
  const { answer } = ctx.review;
  ctx.edit.hidden = true;
  ctx.reviewBox.hidden = false;
  const id = `col-trade-anyway-${ctx.sheet.heading.id}`;
  const held = (answer.in_use || []).length > 0;
  const anyway = held ? el("input", { type: "checkbox", id, onchange: () => drawTradeReviewFoot(ctx) }) : null;
  ctx.anyway = anyway;
  const stale = answer.stale_tables;
  add(clear(ctx.reviewBox), [
    el("h3", { text: "Cards that left" }),
    el("ul", { class: "col-trade-list" }, answer.gave.map((g) => el("li", { text: `${g.quantity} × ${colTradeLabel(g)}: `
      + (g.after ? `${num(g.before)} listed, ${num(g.after)} left` : `all ${num(g.before)} go, so its row is removed`) }))),
    el("h3", { text: "Cards that came in" }),
    el("ul", { class: "col-trade-list" }, answer.got.length ? answer.got.map((row) => el("li", { text: `${row.quantity} × ${colTradeLabel(row)}` }))
      : el("li", { class: "sub", text: "Nothing the collection tracks." })),
    answer.skipped_basics ? el("p", { class: "sub", text: `${plural(answer.skipped_basics, "ordinary basic land")} got ${answer.skipped_basics === 1 ? "isn't" : "aren't"} tracked, so ${answer.skipped_basics === 1 ? "it's" : "they're"} left out.` }) : null,
    held ? el("div", { class: "box box-warn col-trade-held" },
      el("p", { text: "Built decks or intact products hold some of these copies:" }),
      el("ul", {}, answer.in_use.map((w) => w.message ? el("li", { text: w.message })
        : el("li", {}, `${w.name}: ${num(w.after)} owned after the trade; ${num(w.in_use)} in use (${num(w.shortage)} short) in `,
          ...w.holders.flatMap((h, i) => [i ? ", " : "", el("a", { href: deckHref(h.id), text: h.title }), ` (${num(h.qty)})`])))),
      el("p", { text: "Take these cards out of the deck or break up the intact product first, or save anyway if the trade really happened." }),
      el("label", { class: "choice", for: id }, anyway, el("span", { text: "Save it anyway: those decks will be short" }))) : null,
    stale == null ? el("p", { class: "sub", text: "Whether decks' tables would go out of date couldn't be worked out." })
      : stale.length ? el("p", { class: "box box-info", text: `Saving leaves ${stale.length === 1 ? "1 deck's owned-vs-needed table"
        : `${num(stale.length)} decks' owned-vs-needed tables`} out of date: ${stale.map((d) => d.title).join(", ")}. Update ${stale.length === 1 ? "it" : "them"} on Decks afterwards.` }) : null,
    el("p", { class: "sub col-trade-words" }, "The change history will say: ", el("q", { text: answer.message }))]);
  drawTradeReviewFoot(ctx);
  const heading = ctx.reviewBox.querySelector("h3");
  if (heading) { heading.tabIndex = -1; heading.focus(); }
}

function drawTradeReviewFoot(ctx) {
  const waiting = ctx.anyway && !ctx.anyway.checked;
  sheetActions(ctx.sheet, [{ text: "Back", value: "back", onclick: () => { if (!ctx.busy) { clear(ctx.message); showTradeEdit(ctx); } } },
    { text: "Save trade", kind: ctx.anyway ? "danger btn-primary" : "primary", value: "save", onclick: () => {
      if (ctx.anyway && !ctx.anyway.checked) { colTradeSay(ctx, "warn", "Tick Save it anyway, or go Back and change the trade."); ctx.anyway.focus(); return; }
      saveTrade(ctx);
    } }]);
  const button = ctx.sheet.foot.querySelector('[data-action="save"]');
  if (waiting) button.setAttribute("aria-disabled", "true");
}

async function saveTrade(ctx) {
  const cv = ctx.cv;
  if (ctx.busy || ctx.sheet.closed || !colActive(cv) || !ctx.review) return;
  const { body, answer } = ctx.review;
  const send = { ...body };
  if (answer.confirm_in_use && ctx.anyway && ctx.anyway.checked) send.confirm_in_use = answer.confirm_in_use;
  colTradeBusy(ctx, true);
  clear(ctx.message).append(loadingBox("Saving the trade…", { small: true }));
  try {
    const saved = await apiWrite("/api/collection/trade", send);
    if (!colActive(cv)) return;
    ctx.sheet.close();
    colChanged(cv, saved, `Trade saved: gave ${plural(saved.gave, "card")}, got ${plural(saved.got, "card")}.`);
  } catch (error) {
    if (ctx.sheet.closed || !colActive(cv)) return;
    colTradeBusy(ctx, false);
    if (error.status === 409 && error.data && error.data.in_use && error.data.confirm_in_use) {
      // The decks changed since the preview: the new warning needs its own tick.
      ctx.review = { body, answer: { ...answer, in_use: error.data.in_use, confirm_in_use: error.data.confirm_in_use } };
      drawTradeReview(ctx);
      colTradeSay(ctx, "warn", "The built decks or intact products changed since the preview. Nothing was saved: check the warning again.");
      return;
    }
    colTradeFailed(ctx, error);
    if (ctx.review) drawTradeReviewFoot(ctx);
  }
}
