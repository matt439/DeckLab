/* A Commander deck's "EDHREC ideas" (E9-S07, lib/api/edhrec.py): the commander's commonly played cards
 * from EDHREC, grouped by EDHREC's categories with the share of its decks playing each, and the date the
 * PC fetched them. A viewer who sees the deck's space's collection gets each card marked in the deck, free,
 * in use (every copy in another deck, which is never named) or to buy with its AUD estimate; anyone else
 * the list alone (the server sends no marks). Whoever may change the deck adds a card to its Considering
 * list from here (POST /api/deck/considering, deck-considering.js), one save each.
 *
 * EDHREC is asked only when the sheet is opened (and then only when the PC's copy is a week old): the Cards
 * tab shows just a button, so a failure or a slow answer never touches the rest of the page.
 *
 * The sheet's Page choice narrows the ideas to one of EDHREC's pages for the commander: Budget or
 * Expensive, a Commander Brackets page, or one of the themes EDHREC lists for it (the answer's "pages").
 * Each choice asks the server again (page=); a page EDHREC hasn't got says so and the choice stays, so
 * another page (or the commander's whole page) can still be picked. */
"use strict";

const EDHREC_FILTERS = [["new", "Not in the deck"], ["free", "Free"], ["to_buy", "To buy"], ["all", "All"]];
const EDHREC_PAGE_GROUPS = [["budget", "Budget"], ["bracket", "Commander Brackets"], ["theme", "Themes"]];

/** The Cards tab's EDHREC part: a Commander deck only (never a product or pairing). */
function deckEdhrecSection(data) {
  const s = data.summary;
  if (s.kind !== "commander" || /^(product|pairing)\//.test(s.id)) return null;
  return el("section", { class: "deck-section deck-edhrec", id: "sec-edhrec", "aria-labelledby": "h-edhrec" },
    el("h2", { id: "h-edhrec", text: "EDHREC ideas" }),
    el("p", { class: "sub", text: "What other decks with this commander commonly play, from EDHREC." }),
    el("button", { type: "button", class: "btn", text: "See EDHREC ideas…", onclick: () => openEdhrecSheet(data) }));
}

/** "In the deck", "Free in the pool", "2 free", "Owned, all in other decks", "To buy · ~A$1.20", with
 * copies on the way and Considering said; for a viewer with no marks only what the deck's list shows. */
function edhrecMarkWords(c, marks) {
  const words = [];
  if (c.in_deck) words.push("In the deck");
  else if (marks && c.status === "free") words.push(c.free > 1 ? `${num(c.free)} free` : "Free in the pool");
  else if (marks && c.status === "in_use") words.push("Owned, all in other decks");
  else if (marks && c.status === "to_buy") words.push(c.aud_each != null ? `To buy · ~${aud(c.aud_each)}` : "To buy · no price");
  if (marks && c.on_the_way) words.push(`${num(c.on_the_way)} on the way`);
  if (c.considering) words.push("Considering");
  return words;
}

function edhrecPasses(c, filter) {
  if (filter === "all") return true;
  if (filter === "new") return !c.in_deck;
  return !c.in_deck && c.status === filter;
}

function openEdhrecSheet(data) {
  const ctx = { data, id: data.summary.id, filter: "new", answer: null, changed: false, seq: 0, page: "", pages: null };
  const sheet = openSheet("EDHREC ideas", { wide: true, onClose: () => {
    const here = parseHash();
    if (ctx.changed && here.path === "deck" && addressDeckId(here.params.get("id") || "") === ctx.id) {
      state.library = null;
      route();                                  // the Considering list, drawn again from the saved deck
    }
  } });
  ctx.sheet = sheet;
  ctx.picker = el("div", { class: "edhrec-page" });
  ctx.message = el("div", { role: "status", "aria-live": "polite" });
  ctx.area = el("div", { class: "edhrec-area" });
  add(sheet.body, [ctx.picker, ctx.message, ctx.area]);
  sheetActions(sheet, [{ text: "Close", value: "close", onclick: () => sheet.close() }]);
  loadEdhrec(ctx);
  return ctx;
}

async function loadEdhrec(ctx) {
  const seq = ++ctx.seq;
  clear(ctx.area);
  clear(ctx.message).append(loadingBox("Asking EDHREC…"));
  try {
    const answer = await api(`/api/deck/edhrec?id=${encodeURIComponent(ctx.id)}`
      + (ctx.page ? `&page=${encodeURIComponent(ctx.page)}` : ""));
    if (seq !== ctx.seq || ctx.sheet.closed) return;
    ctx.answer = answer;
    ctx.sha = answer.sha256;
    ctx.pages = Array.isArray(answer.pages) ? answer.pages : null;
    clear(ctx.message);
    drawEdhrecPicker(ctx);
    drawEdhrec(ctx);
  } catch (error) {
    if (seq !== ctx.seq || ctx.sheet.closed) return;
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

function drawEdhrec(ctx) {
  const a = ctx.answer;
  const marks = Boolean(a.marks);
  const filters = EDHREC_FILTERS.filter(([key]) => marks || key === "new" || key === "all");
  if (!filters.some(([key]) => key === ctx.filter)) ctx.filter = "new";
  // A card EDHREC lists in two categories (its Top Cards and its type) is counted once.
  const all = [...new Map(a.groups.flatMap((g) => g.cards).map((c) => [c.name, c])).values()];
  const bar = el("div", { class: "segmented edhrec-filters", role: "group", "aria-label": "Show" },
    filters.map(([key, words]) => el("button", { type: "button", "aria-pressed": String(ctx.filter === key),
      text: `${words} (${num(all.filter((c) => edhrecPasses(c, key)).length)})`,
      onclick: () => { if (ctx.filter !== key) { ctx.filter = key; drawEdhrec(ctx); } } })));
  const rate = marks && a.price_error ? `No prices: ${a.price_error}`
    : marks && a.rate != null ? `Estimates in AUD: Scryfall's cheapest non-foil printing at 1 USD = ${num(a.rate, 4)} AUD (ECB rate of ${a.rate_date}), prices pulled ${a.price_date}.` : null;
  const groups = a.groups.map((g) => {
    const shown = g.cards.filter((c) => edhrecPasses(c, ctx.filter));
    if (!shown.length) return null;
    return el("section", { class: "edhrec-group" }, el("h3", { text: g.header }),
      el("div", {}, shown.map((c) => edhrecRow(ctx, c, marks))));
  }).filter(Boolean);
  add(clear(ctx.area), [
    edhrecSourceLine(a),
    a.source && a.source.stale ? el("p", { class: "box box-warn", text: a.source.stale }) : null,
    marks ? null : el("p", { class: "box box-info", text: "This deck's collection isn't yours to see, so nothing here says what's owned." }),
    bar,
    rate ? el("p", { class: "sub", text: rate }) : null,
    groups.length ? groups : emptyBox(ctx.filter === "new" ? "Every idea is in the deck already." : "No ideas of that kind."),
    a.left_out && a.left_out.length ? el("p", { class: "result-count", text: `${plural(a.left_out.length, "card")} left out: outside the commander's colour identity, not legal in Commander, or not known to Deck Lab.` }) : null,
    el("p", { class: "result-count", text: "Card lists and percentages from EDHREC: the share of its decks with this commander that play each card." })]);
}

function edhrecRow(ctx, c, marks) {
  const share = c.inclusion != null ? `${c.inclusion}% of decks` : null;
  const row = cardRow(c.card || null, { name: c.name, meta: [share, ...edhrecMarkWords(c, marks)].filter(Boolean).join(" · "),
    viewerGroup: "deck-edhrec", caption: c.name });
  if (!ctx.answer.may_add || c.in_deck) return row;
  const button = el("button", { type: "button", class: "btn btn-quiet", text: c.considering ? "Considering" : "Consider",
    disabled: c.considering || null, "aria-label": `Add ${c.name} to the Considering list`,
    onclick: () => considerEdhrecCard(ctx, c, button) });
  return el("div", { class: "deck-considering-row edhrec-row" }, row, button);
}

/** One card added to the deck's Considering list: one save, from the sha the last save left. */
async function considerEdhrecCard(ctx, c, button) {
  if (button.disabled) return;
  button.disabled = true;
  try {
    const answer = await apiWrite("/api/deck/considering", { id: ctx.id, sha256: ctx.sha, action: "add", line: { name: c.name, qty: 1 } });
    if (answer && typeof answer.sha256 === "string") ctx.sha = answer.sha256;
    ctx.changed = true;
    c.considering = true;
    button.textContent = "Considering";
    toast(`Added ${c.name} to Considering.`);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    button.disabled = false;
    toast(e.message + (e.status === 409 ? " Close this and reload the deck, then try again." : ""));
  }
}
