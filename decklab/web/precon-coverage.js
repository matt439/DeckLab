/* The Collection page's "Precons we could build…" (E1-S24, lib/api/precon_coverage.py): MTGJSON's published
 * precons ranked by how much of each the space's free pool already covers (copies not held by built decks or
 * intact products, plain basics left out), best first, filtered by format and kind of deck. Opening one shows
 * its missing cards with their estimated AUD cost (with the rate and the dates it was pulled), and
 * "Start a deck from it" makes a new idea deck with its list (POST /api/precons/start: deck.create, as
 * POST /api/decks), then opens it. Nothing here changes the collection.
 *
 * While MTGJSON's lists are still being read (the first time, a download of about 150 MB on the PC), the
 * ranking shows the precons read so far and asks again every PCOV_POLL_MS while the sheet is open. */
"use strict";

const PCOV_POLL_MS = 5000;
const PCOV_FORMATS = [["", "All"], ["commander", "Commander"], ["casual", "60-card"]];

/** Open the ranking for the Collection page's space (any viewer the page loaded for: it sees the inventory). */
function openCoverageSheet(cv) {
  if (!colActive(cv) || cv.busy) return null;
  const whose = colWhose(cv.space);
  const ctx = { cv, whose, seq: 0, timer: null, detail: null, format: "", type: "", busy: false };
  const sheet = colOpenSheet("Precons we could build", { wide: true, onClose: () => clearTimeout(ctx.timer) });
  ctx.sheet = sheet;
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.area = el("div", { class: "pcov-area" });
  ctx.formats = el("div", { class: "segmented pcov-formats", role: "group", "aria-label": "Format" });
  ctx.typeSelect = el("select", { id: `pcov-type-${sheet.heading.id}` });
  ctx.typeSelect.addEventListener("change", () => { ctx.type = ctx.typeSelect.value; rankPrecons(ctx); });
  ctx.filters = el("div", { class: "pcov-filters" },
    el("p", { class: "sub", text: `Each precon's share of cards (plain basic lands left out) with a copy free in ${whose}: owned or on the way, and not in a built deck or a product kept intact.` }),
    ctx.formats,
    el("label", { class: "field pcov-type", for: ctx.typeSelect.id }, el("span", { text: "Kind of deck" }), ctx.typeSelect));
  ctx.back = { text: "← Back to the ranking", value: "back", onclick: () => backToRanking(ctx) };
  drawCoverageFormats(ctx);
  add(sheet.body, [ctx.filters, ctx.message, ctx.area]);
  sheetActions(sheet, [{ text: "Close", value: "close", onclick: () => sheet.close() }]);
  rankPrecons(ctx);
  return ctx;
}

function drawCoverageFormats(ctx) {
  clear(ctx.formats).append(...PCOV_FORMATS.map(([value, words]) => el("button", { type: "button", text: words,
    "aria-pressed": String(ctx.format === value), onclick: () => {
      if (ctx.format === value) return;
      ctx.format = value;
      ctx.type = "";
      drawCoverageFormats(ctx);
      rankPrecons(ctx);
    } })));
}

function coverageParams(ctx, extra = {}) {
  const params = new URLSearchParams(extra);
  if (ctx.cv.space !== HOME_SPACE) params.set("space", ctx.cv.space);
  return params;
}

function coverageAlive(ctx, seq) {
  return seq === ctx.seq && !ctx.sheet.closed && colActive(ctx.cv);
}

async function rankPrecons(ctx, { poll = false } = {}) {
  if (ctx.sheet.closed || ctx.detail) return;
  clearTimeout(ctx.timer);
  const seq = ++ctx.seq;
  if (!poll) clear(ctx.message).append(loadingBox("Ranking precons…"));
  try {
    const params = coverageParams(ctx);
    if (ctx.format) params.set("format", ctx.format);
    if (ctx.type) params.set("type", ctx.type);
    const answer = await api(`/api/precons/coverage?${params}`);
    if (!coverageAlive(ctx, seq) || ctx.detail) return;
    ctx.ranking = answer;
    clear(ctx.message);
    drawRanking(ctx, answer);
    if (answer.status && answer.status.updating) ctx.timer = setTimeout(() => rankPrecons(ctx, { poll: true }), PCOV_POLL_MS);
  } catch (error) {
    if (!coverageAlive(ctx, seq)) return;
    clear(ctx.message).append(loadFailed("The precon ranking", error, () => rankPrecons(ctx)));
  }
}

/** "82% · 41 of 50 cards", with a meter. */
function coverageShare(d) {
  const pct = Math.round((d.share || 0) * 100);
  return el("span", { class: "pcov-share" },
    el("span", { class: "pcov-share-words", text: `${pct}% · ${num(d.covered)} of ${plural(d.cards, "card")}` }),
    el("span", { class: "meter", "aria-hidden": "true" }, el("span", { style: `width: ${pct}%` })));
}

function drawRanking(ctx, answer) {
  const types = answer.types || [];
  clear(ctx.typeSelect).append(el("option", { value: "", text: "Any kind" }),
    ...types.map((t) => el("option", { value: t, text: t, selected: t === ctx.type || null })));
  ctx.typeSelect.value = types.includes(ctx.type) ? ctx.type : "";
  const status = answer.status || {};
  const decks = answer.decks || [];
  add(clear(ctx.area), [
    status.updating ? el("p", { class: "box box-info" }, el("span", { class: "spinner spinner-small", "aria-hidden": "true" }),
      ` Reading MTGJSON's precon lists: ${num(status.indexed || 0)} of ${num(status.listed || 0)} read so far. The ranking fills in as they arrive.`) : null,
    !status.updating && status.error ? el("p", { class: "box box-warn", text: `Some lists couldn't be read: ${status.error}. They're tried again later.` }) : null,
    decks.length ? el("ol", { class: "pcov-list" }, decks.map((d) => el("li", {},
      el("button", { type: "button", class: "pcov-pick", onclick: () => openCoveragePrecon(ctx, d) },
        el("span", { class: "pcov-pick-words" }, el("strong", { text: d.name }),
          el("small", { text: [d.set_name || d.code.toUpperCase(), d.type, d.released ? String(d.released).slice(0, 4) : null].filter(Boolean).join(" · ") })),
        coverageShare(d),
        el("small", { class: "pcov-missing", text: d.missing ? `${plural(d.missing, "card")} to find` : "Every card is free" })))))
      : status.updating ? null : emptyBox(ctx.format || ctx.type ? "No precon of that kind has a list read yet." : "No precon lists have been read yet.", null, { live: true }),
    answer.total > decks.length ? el("p", { class: "result-count", text: `The best ${num(decks.length)} of ${num(answer.total)}.` }) : null,
    el("p", { class: "result-count", text: `Lists from MTGJSON${answer.date ? ` (updated ${answer.date})` : ""}, most from Wizards' published lists.` })]);
}

function backToRanking(ctx) {
  ctx.detail = null;
  ctx.filters.hidden = false;
  ctx.sheet.heading.textContent = "Precons we could build";
  sheetActions(ctx.sheet, [{ text: "Close", value: "close", onclick: () => ctx.sheet.close() }]);
  rankPrecons(ctx);
}

async function openCoveragePrecon(ctx, deck) {
  clearTimeout(ctx.timer);
  const seq = ++ctx.seq;
  ctx.detail = { deck };
  ctx.filters.hidden = true;
  clear(ctx.area);
  ctx.sheet.heading.textContent = deck.name;
  clear(ctx.message).append(loadingBox(`Reading ${deck.name}…`));
  sheetActions(ctx.sheet, [ctx.back]);
  try {
    const answer = await api(`/api/precons/coverage/deck?${coverageParams(ctx, { file: deck.file })}`);
    if (!coverageAlive(ctx, seq) || !ctx.detail || ctx.detail.deck !== deck) return;
    ctx.detail = { deck, answer };
    clear(ctx.message);
    drawCoveragePrecon(ctx);
  } catch (error) {
    if (!coverageAlive(ctx, seq)) return;
    clear(ctx.message).append(loadFailed(deck.name, error, () => openCoveragePrecon(ctx, deck)));
  }
}

/** The rate and dates the estimates were made with (AGENTS.md: prices in AUD, with the date pulled). */
function coverageRate(p) {
  if (p.price_error) return `No prices: ${p.price_error}`;
  return `Estimates in AUD: Scryfall's cheapest non-foil printing at 1 USD = ${num(p.rate, 4)} AUD (ECB rate of ${p.rate_date}), prices pulled ${p.price_date}.`;
}

function drawCoveragePrecon(ctx) {
  const { deck, answer: p } = ctx.detail;
  const d = p.deck || deck;
  const totals = p.totals || {};
  const titleInput = el("input", { id: `pcov-title-${ctx.sheet.heading.id}`, type: "text", maxlength: "100", value: p.title });
  ctx.titleInput = titleInput;
  ctx.titleNote = el("p", { class: "field-problem precon-title-note", role: "status" });
  const missing = p.missing || [];
  add(clear(ctx.area), [
    el("p", { class: "sub precon-meta", text: [d.set_name || d.code.toUpperCase(), d.type, d.released ? `released ${d.released}` : null].filter(Boolean).join(" · ") }),
    el("p", { class: "precon-summary" }, coverageShare(p)),
    missing.length ? el("p", {}, el("b", { text: `${plural(totals.missing || 0, "card")} to find` }),
      totals.aud_missing != null ? `, about ${aud(totals.aud_missing)} to buy` : "",
      totals.unpriced && totals.unpriced.length ? ` (${plural(totals.unpriced.length, "card")} with no price)` : "", ".")
      : el("p", { class: "box box-good", text: `Every card of it has a copy free in ${ctx.whose}.` }),
    missing.length ? el("p", { class: "sub pcov-rate", text: coverageRate(p) }) : null,
    p.problems && p.problems.length ? el("p", { class: "box box-warn", text: `${plural(p.problems.length, "card")} of MTGJSON's list can't be read and isn't counted.` }) : null,
    missing.length ? el("section", { class: "precon-section" }, el("h3", { text: "Missing cards" }),
      el("div", { class: "card-tiles precon-tiles" }, missing.map((c) => cardTile(c.card || null, { qty: c.missing, name: c.name,
        meta: [c.free ? `${num(c.free)} of ${num(c.need)} free` : `${num(c.need)} needed`, c.aud_each != null ? `~${aud(c.aud_each)} each` : "no price"],
        viewerGroup: "precon-coverage", caption: `${c.missing} ${c.name}${c.aud_missing != null ? ` · ~${aud(c.aud_missing)}` : ""}` })))) : null,
    p.may_start ? el("label", { class: "field precon-title", for: titleInput.id }, el("span", { text: "New deck's title" }), titleInput) : null,
    p.may_start ? ctx.titleNote : null,
    p.may_start ? el("p", { class: "sub", text: "Start a deck from it makes an idea deck with this list, to build from what you have. Nothing is added to the collection." })
      : el("p", { class: "box box-info", text: "You can't start decks here." })]);
  sheetActions(ctx.sheet, [ctx.back,
    p.may_start ? { text: "Start a deck from it", kind: "primary", value: "start", onclick: () => startCoverageDeck(ctx) } : null]);
}

async function startCoverageDeck(ctx) {
  const cv = ctx.cv;
  const detail = ctx.detail;
  if (ctx.busy || ctx.sheet.closed || !detail || !detail.answer || !colActive(cv)) return;
  const title = ctx.titleInput.value.trim();
  if (!title) { ctx.titleNote.textContent = "The deck needs a title."; ctx.titleInput.focus(); return; }
  const requestHash = location.hash;
  ctx.busy = true;
  for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = true;
  clear(ctx.message).append(loadingBox(`Starting ${title}…`));
  try {
    const answer = await apiWrite("/api/precons/start", { space: cv.space, file: detail.answer.deck.file, title });
    state.library = null;
    if (ctx.sheet.closed || !colActive(cv) || ctx.detail !== detail || requestHash !== location.hash) return;
    ctx.sheet.close();
    // The deck page's box about a new deck (editor-deckpage.js, savedBox), as the editor's Create leaves it.
    const hash = deckHref(answer.id, "target");
    state.saved = { hash, profile: state.profile?.id, version: "target", mode: "new", answer };
    state.scroll.delete(hash);
    toast("");
    location.hash = hash;
  } catch (error) {
    if (ctx.sheet.closed || !colActive(cv) || ctx.detail !== detail) return;
    ctx.busy = false;
    for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = false;
    const data = error.data || {};
    const problems = data.problems || (data.blocks || []).map((b) => ({ message: b.problem }));
    clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message }),
      problems.length ? el("ul", {}, problems.slice(0, 20).map((x) => el("li", { text: x.message }))) : null));
    if (error.status === 409 && data.conflict) ctx.titleInput.focus();
  }
}
