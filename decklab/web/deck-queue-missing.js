/* A home admin's reviewed purchase queue addition from Find and buy cards (E5-S25).
 *
 * The sheet asks POST /api/shopping/queue/missing for the review (nothing is written): each missing card with
 * the copies already queued for this deck and the copies to add, any nonfoil printing. Save sends the reviewed
 * cards and the buyer's selection with the chosen state (Ready to buy or Long-term) to POST /api/shopping/queue's add_many, with the revision
 * the review read; the server works them out again and refuses (409) when anything moved on, and the sheet
 * then asks for a new review. A card whose identical request is already queued raises that row, which keeps its
 * own state: the review names it (joins), the row says so, a note warns when it isn't the chosen state, and the
 * save sends it back so the server checks it still holds. Never offered to User1, members, products or pairings; the server checks anyway.
 * Token cards are never queued here.
 *
 * Shopping's combined shortages (E5-S28) open the same sheet for the chosen decks (openQueueCombinedSheet):
 * POST /api/shopping/queue/combined reviews the decks' combined shortfall less the copies queued for any of them,
 * and add_combined saves it with "for" naming the decks. */
"use strict";

const QUEUE_MISSING_STATES = [["ready", "Ready to buy"], ["long_term", "Long-term"]];
const QUEUE_MISSING_JOINS = { ready: "Ready to buy", waiting_for_stock: "Waiting for stock",
  waiting_for_reprint: "Waiting for a reprint", deferred: "Deferred", long_term: "Long-term" };

function queueMissingJoins(state) {
  return QUEUE_MISSING_JOINS[state] || state;
}

/** True when the visitor may queue this deck's missing cards: a home admin on an ordinary home deck. */
function deckQueueMissingOffered(data) {
  const s = data.summary;
  if (!state.profile || /^(product|pairing)\//.test(s.id) || (s.space || deckSpaceOf(s.id)) !== HOME_SPACE) return false;
  return isAdminProfile() && Boolean(state.may) && Boolean(state.may.orders) && seesHomeInventory(state.may) && Boolean(data.owned);
}

function openQueueMissingSheet(summary, root) {
  const ctx = { id: summary.id, title: summary.title, state: "ready", answer: null, seq: 0 };
  ctx.view = { root, token: routeToken, profile: state.profile.id };
  return queueMissingOpen(ctx, `Review Planned shortages: ${summary.title}`);
}

/** Queue these (E5-S28): the sheet for decks built together; onSaved(saved) runs after a save. */
function openQueueCombinedSheet(decks, onSaved, view) {
  const ctx = { decks: decks.map((deck) => deck.id), title: decks.map((deck) => deck.title).join(" + "),
    state: "ready", answer: null, seq: 0, onSaved, view };
  return queueMissingOpen(ctx, `Review combined shortages: ${ctx.title}`);
}

function queueMissingOpen(ctx, title) {
  ctx.sheet = shopTrackQueueSheet(openSheet(title, { wide: true }), ctx.view);
  ctx.current = () => !ctx.sheet.closed && ctx.sheet.dialog.isConnected && shopQueueActive(ctx.view);
  ctx.sheet.dialog.classList.add("queue-missing-sheet");
  ctx.message = el("div", { role: "status", "aria-live": "polite" });
  ctx.area = el("div", { class: "queue-missing-area" });
  add(ctx.sheet.body, [ctx.message, ctx.area]);
  loadQueueMissing(ctx);
  return ctx;
}

async function loadQueueMissing(ctx) {
  if (!ctx.current()) return;
  const seq = ++ctx.seq;
  clear(ctx.area);
  clear(ctx.message).append(loadingBox("Counting the missing cards…"));
  sheetActions(ctx.sheet, [{ text: "Close", value: "close", onclick: () => ctx.sheet.close() }]);
  try {
    const answer = ctx.decks ? await apiWrite("/api/shopping/queue/combined", { decks: ctx.decks })
      : await apiWrite("/api/shopping/queue/missing", { deck: ctx.id });
    if (seq !== ctx.seq || !ctx.current()) return;
    ctx.answer = answer;
    // Keep an earlier choice on Review again. Newly missing cards need an explicit check.
    const offered = (answer.rows || []).filter((r) => r.copies > 0).map((r) => r.name);
    ctx.selected = new Set(ctx.selected ? offered.filter((name) => ctx.selected.has(name)) : offered);
    clear(ctx.message);
    drawQueueMissing(ctx);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (seq !== ctx.seq || !ctx.current()) return;
    clear(ctx.message).append(loadFailed("The missing cards", error, error.status === 403 || error.status === 404 ? null : () => loadQueueMissing(ctx)));
  }
}

function queueMissingRow(row, checkbox = null) {
  const meta = [row.copies ? `${plural(row.copies, "copy", "copies")} to queue` : "Nothing to queue",
    `${num(row.missing)} missing`, row.queued ? `${num(row.queued)} already queued for ${row.decks ? "these decks" : "this deck"}` : null,
    row.decks && row.decks.length ? `for ${row.decks.join(", ")}` : null,
    row.copies && row.joins ? `added to the existing ${queueMissingJoins(row.joins)} row` : null].filter(Boolean).join(" · ");
  return el("li", { class: "queue-missing-row" },
    checkbox,
    cardRow(row.card || null, { name: row.name, meta, viewerGroup: "deck-queue-missing", caption: row.name }));
}

function drawQueueMissing(ctx) {
  const a = ctx.answer;
  if (!a || !a.ready) {
    add(clear(ctx.area), [el("p", { class: "box box-warn", text: (a && a.reason) || "The missing cards could not be counted." })]);
    return;
  }
  const adding = a.rows.filter((r) => r.copies > 0);
  const done = a.rows.filter((r) => !r.copies);
  if (!adding.length) {
    add(clear(ctx.area), [
      emptyBox(a.rows.length ? `Every missing card is already on the purchase queue for ${ctx.decks ? "these decks" : "this deck"}.`
        : ctx.decks ? "Nothing to queue for these decks after counting incoming copies." : "Nothing is missing from the Planned list after counting incoming copies."),
      done.length ? el("ul", { class: "card-list" }, done.map((r) => queueMissingRow(r))) : null]);
    return;
  }
  const choices = el("div", { class: "segmented queue-missing-state", role: "group", "aria-label": "Queue them as" },
    QUEUE_MISSING_STATES.map(([key, words]) => el("button", { type: "button", "aria-pressed": String(ctx.state === key), text: words,
      onclick: () => { if (ctx.state !== key) { ctx.state = key; drawQueueMissing(ctx); } } })));
  const warning = el("div");
  const rows = adding.map((row) => {
    const name = row.name;
    const checkbox = el("input", { type: "checkbox", "aria-label": `Queue ${name}`, onchange: () => {
      if (checkbox.checked) ctx.selected.add(name); else ctx.selected.delete(name);
      updateSelection();
    } });
    checkbox.checked = ctx.selected.has(name);
    return queueMissingRow(row, el("label", { class: "queue-missing-check" }, checkbox));
  });
  add(clear(ctx.area), [
    el("p", { class: "sub", text: ctx.decks
      ? `What to buy to build ${a.for} together, less the copies already queued for any of them. ` +
        `Each is any nonfoil printing, for "${a.for}".`
      : `The ${listName("target", true)}'s missing copies, less those already queued for this deck. ` +
        "Each is any nonfoil printing, with this deck as its source." }),
    el("div", { class: "toolbar" }, el("span", { text: "Queue them as" }), choices),
    el("p", { class: "sub", text: "Selected copies go on the shared purchase queue. Record them under Orders & deliveries after you buy them." }),
    warning, el("ul", { class: "card-list" }, rows),
    done.length ? el("details", {}, el("summary", { text: `Already queued (${num(done.length)})` }),
      el("ul", { class: "card-list" }, done.map((r) => queueMissingRow(r)))) : null]);
  updateSelection();

  function updateSelection() {
    const words = QUEUE_MISSING_STATES.find(([key]) => key === ctx.state)[1];
    const chosen = adding.filter((r) => ctx.selected.has(r.name));
    const others = chosen.filter((r) => r.joins && r.joins !== ctx.state);
    clear(warning);
    if (others.length) warning.append(el("p", { class: "box box-warn queue-missing-joins",
      text: `${plural(others.length, "card")} already ${others.length === 1 ? "has" : "have"} a row for ${ctx.decks ? "these decks" : "this deck"} in another state, ` +
        `and ${others.length === 1 ? "its" : "their"} copies are added there, keeping that state (not ${words}): ` +
        others.map((r) => `${r.name} (${queueMissingJoins(r.joins)})`).join(", ") + "." }));
    const copies = chosen.reduce((total, row) => total + row.copies, 0);
    sheetActions(ctx.sheet, [
      { text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() },
      { text: `Queue ${plural(copies, "copy", "copies")} (${words})`, value: "save", kind: "primary", disabled: !copies,
        onclick: (e) => saveQueueMissing(ctx, e.currentTarget) }]);
  }
}

async function saveQueueMissing(ctx, button) {
  if (!ctx.current() || !button.isConnected || button.disabled || !ctx.selected.size) return;
  const a = ctx.answer;
  const cards = a.rows.filter((r) => r.copies > 0).map((r) => ({ name: r.name, copies: r.copies, joins: r.joins || null }));
  const selection = ctx.selected.size === cards.length ? {} : { selected: [...ctx.selected] };
  const controls = [...ctx.area.querySelectorAll("input"), ...ctx.area.querySelector(".queue-missing-state").querySelectorAll("button")];
  for (const control of controls) control.disabled = true;
  busy(button, "Queueing…");
  try {
    const saved = ctx.decks
      ? await apiWrite("/api/shopping/queue", { action: "add_combined", expect: a.revision, decks: ctx.decks, state: ctx.state, cards, ...selection })
      : await apiWrite("/api/shopping/queue", { action: "add_many", expect: a.revision, deck: a.deck.id, state: ctx.state, cards, ...selection });
    if (!ctx.current()) return;
    ctx.sheet.close("saved");
    toast(`Queued ${plural(saved.copies, "copy", "copies")} of ${plural(saved.cards, "card")} for ${ctx.decks ? saved.for : a.deck.title}.`);
    if (ctx.onSaved) ctx.onSaved(saved);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (!ctx.current()) return;
    unbusy(button);
    clear(ctx.message).append(el("p", { class: "box box-warn", text: error.message }));
    if (error.status === 409) {
      sheetActions(ctx.sheet, [
        { text: "Close", value: "close", onclick: () => ctx.sheet.close() },
        { text: "Review again", value: "review", kind: "primary", onclick: () => loadQueueMissing(ctx) }]);
    } else for (const control of controls) control.disabled = false;
  }
}
