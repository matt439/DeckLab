/* A Commander deck's "EDHREC ideas" (E9-S07, lib/api/edhrec.py): the commander's commonly played cards
 * from EDHREC, grouped by EDHREC's categories with the share of its decks playing each, and the date the
 * PC fetched them. A viewer who sees the deck's space's collection gets each card marked in the deck, free,
 * in use (every copy in another deck, which is never named) or to buy with its estimate (E11-S53: in the answer's currency); anyone else
 * the list alone (the server sends no marks). An editable suggestion opens the ordinary Considering draft.
 *
 * EDHREC is asked only when the sheet is opened (and then only when the PC's copy is a week old): the Cards
 * tab shows just a button, so a failure or a slow answer never touches the rest of the page.
 *
 * The sheet's Page choice narrows the ideas to one of EDHREC's pages for the commander: Budget or
 * Expensive, a Commander Brackets page, or one of the themes EDHREC lists for it (the answer's "pages").
 * Each choice asks the server again (page=); a page EDHREC hasn't got says so and the choice stays, so
 * another page (or the commander's whole page) can still be picked.
 *
 * Commanders we could build (E9-S28, commander-candidates.js) opens the same sheet for a commander with no
 * deck yet (openEdhrecSheet(null, {commander, space})): it asks for that commander in that space, as the
 * new-deck editor does, so the marks count the space's pool; there's no "Not in the deck" choice and no
 * Consider button (no deck to add to). */
"use strict";

const EDHREC_FILTERS = [["new", "Outside planned list"], ["free", "Free now"], ["to_buy", "Short in collection"], ["all", "All"], ["cuts", "Cuts"]];
const EDHREC_PAGE_GROUPS = [["budget", "Budget"], ["bracket", "Commander Brackets"], ["theme", "Themes"]];
const edhrecSheets = new Set();

function closeEdhrecSheets() {
  for (const ctx of [...edhrecSheets]) { ctx.closingForRoute = true; ctx.afterClose = null; ctx.seq++; ctx.sheet.close(); }
}

/** The Cards tab's EDHREC part: a Commander deck only (never a product or pairing). */
function deckEdhrecSection(data) {
  const s = data.summary;
  if (s.kind !== "commander" || /^(product|pairing)\//.test(s.id)) return null;
  return el("section", { class: "deck-section deck-edhrec", id: "sec-edhrec", "aria-labelledby": "h-edhrec" },
    el("h2", { id: "h-edhrec", text: "EDHREC ideas" }),
    el("p", { class: "sub", text: "What other decks with this commander commonly play, from EDHREC." }),
    el("div", { class: "actions" },
      el("button", { type: "button", class: "btn", text: "See EDHREC ideas…", onclick: () => openEdhrecSheet(data) }),
      el("button", { type: "button", class: "btn btn-quiet", text: "Review cuts…", onclick: () => openDeckCuts(data) })));
}

function edhrecFreeNow(card) { return Math.max(0, (card.free || 0) - (card.on_the_way || 0)); }

/** The planned list, physical/incoming availability, and Considering are distinct scopes. */
function edhrecMarkWords(c, marks, answer = null) {
  const words = [];
  if (c.in_deck) words.push("In planned list");
  else if (marks && c.status === "free" && edhrecFreeNow(c) > 0) words.push(`${num(edhrecFreeNow(c))} free now`);
  else if (marks && c.status === "in_use") words.push("Owned, currently held");
  else if (marks && c.status === "to_buy") words.push(c.aud_each != null ? `Short · ~${ansMoney(c.aud_each, answer)}` : "Short · no price estimate");
  if (marks && c.on_the_way) words.push(`${num(c.on_the_way)} on the way`);
  if (c.considering) words.push("Considering");
  return words;
}

function edhrecPasses(c, filter) {
  if (filter === "all") return true;
  if (filter === "new") return !c.in_deck;
  if (filter === "free") return !c.in_deck && c.status === "free" && edhrecFreeNow(c) > 0;
  return !c.in_deck && c.status === filter;
}

function openEdhrecSheet(data, lead = null, options = {}) {
  const ctx = { data, id: data ? data.summary.id : null, lead, filter: options.cuts ? "cuts" : lead ? "all" : "new", answer: null,
    cutEditor: options.editor || null,
    seq: 0, page: "", pages: null };
  const sheet = openSheet("EDHREC ideas", { wide: true, onClose: () => {
    edhrecSheets.delete(ctx);
    if (ctx.closingForRoute) return;
    if (ctx.afterClose) ctx.afterClose();
  } });
  ctx.sheet = sheet;
  edhrecSheets.add(ctx);
  edhrecCutsContext(ctx);
  ctx.picker = el("div", { class: "edhrec-page" });
  ctx.message = el("div", { role: "status", "aria-live": "polite" });
  ctx.area = el("div", { class: "edhrec-area" });
  add(sheet.body, [ctx.picker, ctx.message, ctx.area]);
  sheetActions(sheet, [{ text: "Close", value: "close", onclick: () => sheet.close() }]);
  loadEdhrec(ctx);
  return ctx;
}

async function loadEdhrec(ctx) {
  if (ctx.filter === "cuts") return loadEdhrecCuts(ctx);
  const seq = ++ctx.seq;
  clear(ctx.area);
  clear(ctx.message).append(loadingBox("Asking EDHREC…"));
  try {
    const address = ctx.lead ? `commander=${encodeURIComponent(ctx.lead.commander)}${ctx.lead.commander2 ? `&commander2=${encodeURIComponent(ctx.lead.commander2)}` : ""}&space=${encodeURIComponent(ctx.lead.space)}`
      : `id=${encodeURIComponent(ctx.id)}`;
    const answer = await api(`/api/deck/edhrec?${address}` + (ctx.page ? `&page=${encodeURIComponent(ctx.page)}` : ""));
    if (seq !== ctx.seq || !edhrecCutsHere(ctx)) return;
    ctx.answer = answer;
    ctx.pages = Array.isArray(answer.pages) ? answer.pages : null;
    clear(ctx.message);
    drawEdhrecPicker(ctx);
    drawEdhrec(ctx);
  } catch (error) {
    if (seq !== ctx.seq || !edhrecCutsHere(ctx)) return;
    drawEdhrecPicker(ctx);                    // still there, so another page can be chosen
    const again = error && (error.status === 404 || error.status === 400) ? null : () => loadEdhrec(ctx);
    clear(ctx.message).append(loadFailed("EDHREC ideas", error, again));
  }
}

/** The Page choice: the commander's whole page, then the narrowed pages the last answer offered, grouped. */
function drawEdhrecPicker(ctx) {
  const pages = ctx.pages || [];
  if (!pages.length) { clear(ctx.picker); return; }
  // Drawn again after every answer: the choice just changed keeps its focus on the new control.
  const focused = document.activeElement && ctx.picker.contains(document.activeElement);
  const select = el("select", { id: "edhrec-page", onchange: (e) => {
    if (e.target.value === ctx.page) return;
    ctx.page = e.target.value;
    loadEdhrec(ctx);
  } },
  el("option", { value: "", selected: !ctx.page || null, text: "All decks with this commander" }),
  EDHREC_PAGE_GROUPS.map(([group, label]) => {
    const members = pages.filter((p) => p.group === group);
    return members.length ? el("optgroup", { label }, members.map((p) => el("option", { value: p.page,
      selected: ctx.page === p.page || null,
      text: p.decks ? `${p.label} (${plural(p.decks, "deck")})` : p.label }))) : null;
  }));
  add(clear(ctx.picker), [el("label", { class: "field", for: "edhrec-page" }, el("span", { text: "Page" }), select)]);
  if (focused) select.focus();
}

/** The answer's facts: where from, when fetched, and (with marks) the rate the estimates use. */
function edhrecSourceLine(a) {
  const src = a.source || {};
  const fetched = src.fetched ? String(src.fetched).slice(0, 10) : null;
  const page = a.page ? (a.pages || []).find((p) => p.page === a.page) : null;
  return el("p", { class: "sub edhrec-source" },
    `${a.commanders.join(" & ")} on EDHREC`, a.page ? ` (${page ? page.label : a.page} page)` : "", src.decks ? `, from ${plural(src.decks, "deck")}` : "",
    fetched ? `, fetched ${fetched}` : "", ". ",
    src.url ? el("a", { href: src.url, target: "_blank", rel: "noopener noreferrer", text: "Open on EDHREC" }) : null);
}

function edhrecSourceWarning(view, answer) {
  const warning = answer.source?.stale;
  if (!warning || view.dismissedSourceWarning === answer) return null;
  return dismissibleWarning(el("div", { class: "box box-warn" }, el("p", { text: warning })),
    "Dismiss EDHREC warning", () => { view.dismissedSourceWarning = answer; });
}

function drawEdhrec(ctx) {
  if (ctx.answer?.cuts) return drawEdhrecCuts(ctx);
  ctx.sheet.heading.textContent = "EDHREC ideas";
  const a = ctx.answer;
  const marks = Boolean(a.marks);
  const filters = EDHREC_FILTERS.filter(([key]) => (marks || ["new", "all", "cuts"].includes(key)) && !(ctx.lead && ["new", "cuts"].includes(key)));
  if (!filters.some(([key]) => key === ctx.filter)) ctx.filter = filters[0][0];
  // A card EDHREC lists in two categories (its Top Cards and its type) is counted once.
  const all = [...new Map(a.groups.flatMap((g) => g.cards).map((c) => [c.name, c])).values()];
  const bar = el("div", { class: "segmented edhrec-filters", role: "group", "aria-label": "Show" },
    filters.map(([key, words]) => el("button", { type: "button", "aria-pressed": String(ctx.filter === key),
      text: key === "cuts" ? words : `${words} (${num(all.filter((c) => edhrecPasses(c, key)).length)})`,
      onclick: () => { if (ctx.filter !== key) { ctx.filter = key; if (key === "cuts") loadEdhrecCuts(ctx); else drawEdhrec(ctx); } } })));
  const rate = marks && a.price_error ? `No prices: ${a.price_error}`
    : marks && a.rate != null ? estimateRateWords(a) : null;
  const groups = a.groups.map((g) => {
    const shown = g.cards.filter((c) => edhrecPasses(c, ctx.filter));
    if (!shown.length) return null;
    return el("section", { class: "edhrec-group" }, el("h3", { text: g.header }),
      el("div", {}, shown.map((c) => edhrecRow(ctx, c, marks))));
  }).filter(Boolean);
  add(clear(ctx.area), [
    edhrecSourceLine(a),
    edhrecSourceWarning(ctx, a),
    marks ? null : el("p", { class: "box box-info", text: "This deck's collection isn't yours to see, so nothing here says what's owned." }),
    bar,
    rate ? el("p", { class: "sub", text: rate }) : null,
    groups.length ? groups : emptyBox(ctx.filter === "new" ? "Every idea is in the deck already." : "No ideas of that kind."),
    a.left_out && a.left_out.length ? el("p", { class: "result-count", text: `${plural(a.left_out.length, "card")} left out: outside the commander's colour identity, not legal in Commander, or not known to Deck Lab.` }) : null,
    el("p", { class: "result-count", text: "Card lists and percentages from EDHREC: the share of its decks with this commander that play each card." })]);
}

function edhrecRow(ctx, c, marks) {
  const share = c.inclusion != null ? `${c.inclusion}% of decks` : null;
  const row = cardRow(c.card || null, { name: c.name, meta: [share, ...edhrecMarkWords(c, marks, ctx.answer)].filter(Boolean).join(" · "),
    viewerGroup: "deck-edhrec", caption: c.name });
  if (!ctx.answer.may_add || !ctx.data || c.in_deck || c.considering) return row;
  const link = el("a", { class: "btn btn-quiet", text: "Consider in editor", href: consideringEditHref(ctx.data, c.name),
    "aria-label": `Consider ${c.name} in the editor` });
  link.addEventListener("click", event => { if (!edhrecCutsHere(ctx, link)) event.preventDefault(); });
  return el("div", { class: "deck-considering-row edhrec-row" }, row, link);
}
