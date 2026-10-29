/* Queue missing cards… (E5-S25): on a home deck's Cards tab under the Missing filter, a home admin puts the
 * Planned list's missing cards on the purchase queue in one reviewed change.
 *
 * The sheet asks POST /api/shopping/queue/missing for the review (nothing is written): each missing card with
 * the copies already queued for this deck and the copies to add, any nonfoil printing. Save sends the reviewed
 * cards with the chosen state (To buy or Long-term) to POST /api/shopping/queue's add_many, with the revision
 * the review read; the server works them out again and refuses (409) when anything moved on, and the sheet
 * then asks for a new review. A card whose identical request is already queued raises that row, which keeps its
 * own state: the review names it (joins), the row says so, a note warns when it isn't the chosen state, and the
 * save sends it back so the server checks it still holds. Never offered to User1, members, products or pairings; the server checks anyway.
 * Token cards are never queued here. */
"use strict";

const QUEUE_MISSING_STATES = [["ready", "To buy"], ["long_term", "Long-term"]];
const QUEUE_MISSING_JOINS = { ready: "To buy", waiting_for_stock: "Waiting for stock",
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

/** The Missing filter's "Queue missing cards…" button, or null. */
function deckQueueMissing(screen) {
  const data = screen.data;
  if (screen.view.filter !== "missing" || !deckQueueMissingOffered(data)) return null;
  return el("div", { class: "toolbar deck-queue-missing" },
    el("button", { type: "button", class: "btn", text: "Queue missing cards…",
      onclick: () => openQueueMissingSheet(data.summary) }));
}

function openQueueMissingSheet(summary) {
  const ctx = { id: summary.id, title: summary.title, state: "ready", answer: null, seq: 0 };
  ctx.sheet = openSheet(`Queue missing cards: ${summary.title}`, { wide: true });
  ctx.sheet.dialog.classList.add("queue-missing-sheet");
  ctx.message = el("div", { role: "status", "aria-live": "polite" });
  ctx.area = el("div", { class: "queue-missing-area" });
  add(ctx.sheet.body, [ctx.message, ctx.area]);
  loadQueueMissing(ctx);
  return ctx;
}

async function loadQueueMissing(ctx) {
  const seq = ++ctx.seq;
  clear(ctx.area);
  clear(ctx.message).append(loadingBox("Counting the missing cards…"));
  sheetActions(ctx.sheet, [{ text: "Close", value: "close", onclick: () => ctx.sheet.close() }]);
  try {
    const answer = await apiWrite("/api/shopping/queue/missing", { deck: ctx.id });
    if (seq !== ctx.seq || ctx.sheet.closed) return;
    ctx.answer = answer;
    clear(ctx.message);
    drawQueueMissing(ctx);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (seq !== ctx.seq || ctx.sheet.closed) return;
    clear(ctx.message).append(loadFailed("The missing cards", error, error.status === 403 || error.status === 404 ? null : () => loadQueueMissing(ctx)));
  }
}

function queueMissingRow(row) {
  const meta = [row.copies ? `${plural(row.copies, "copy", "copies")} to queue` : "Nothing to queue",
    `${num(row.missing)} missing`, row.queued ? `${num(row.queued)} already queued for this deck` : null,
    row.copies && row.joins ? `added to the existing ${queueMissingJoins(row.joins)} row` : null].filter(Boolean).join(" · ");
  return el("li", { class: "queue-missing-row" },
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
      emptyBox(a.rows.length ? "Every missing card is already on the purchase queue for this deck." : "Nothing is missing from the Planned list."),
      done.length ? el("ul", { class: "card-list" }, done.map(queueMissingRow)) : null]);
    return;
  }
  const choices = el("div", { class: "segmented queue-missing-state", role: "group", "aria-label": "Queue them as" },
    QUEUE_MISSING_STATES.map(([key, words]) => el("button", { type: "button", "aria-pressed": String(ctx.state === key), text: words,
      onclick: () => { if (ctx.state !== key) { ctx.state = key; drawQueueMissing(ctx); } } })));
  add(clear(ctx.area), [
    el("p", { class: "sub", text: `The ${listName("target", true)}'s missing copies, less those already queued for this deck. ` +
      "Each is any nonfoil printing, with this deck as its source." }),
    el("div", { class: "toolbar" }, el("span", { text: "Queue them as" }), choices),
    el("ul", { class: "card-list" }, adding.map(queueMissingRow)),
    done.length ? el("details", {}, el("summary", { text: `Already queued (${num(done.length)})` }),
      el("ul", { class: "card-list" }, done.map(queueMissingRow))) : null]);
  const words = QUEUE_MISSING_STATES.find(([key]) => key === ctx.state)[1];
  const others = adding.filter((r) => r.joins && r.joins !== ctx.state);
  if (others.length) {
    ctx.area.insertBefore(el("p", { class: "box box-warn queue-missing-joins",
      text: `${plural(others.length, "card")} already ${others.length === 1 ? "has" : "have"} a row for this deck in another state, ` +
        `and ${others.length === 1 ? "its" : "their"} copies are added there, keeping that state (not ${words}): ` +
        others.map((r) => `${r.name} (${queueMissingJoins(r.joins)})`).join(", ") + "." }), ctx.area.querySelector(".card-list"));
  }
  sheetActions(ctx.sheet, [
    { text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() },
    { text: `Queue ${plural(a.totals.copies, "copy", "copies")} (${words})`, value: "save", kind: "primary",
      onclick: (e) => saveQueueMissing(ctx, e.currentTarget) }]);
}

async function saveQueueMissing(ctx, button) {
  if (button.disabled) return;
  const a = ctx.answer;
  const cards = a.rows.filter((r) => r.copies > 0).map((r) => ({ name: r.name, copies: r.copies, joins: r.joins || null }));
  busy(button, "Queueing…");
  try {
    const saved = await apiWrite("/api/shopping/queue", { action: "add_many", expect: a.revision, deck: a.deck.id,
      state: ctx.state, cards });
    if (ctx.sheet.closed) return;
    ctx.sheet.close("saved");
    toast(`Queued ${plural(saved.copies, "copy", "copies")} of ${plural(saved.cards, "card")} for ${a.deck.title}.`);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (ctx.sheet.closed) return;
    unbusy(button);
    clear(ctx.message).append(el("p", { class: "box box-warn", text: error.message }));
    if (error.status === 409) {
      sheetActions(ctx.sheet, [
        { text: "Close", value: "close", onclick: () => ctx.sheet.close() },
        { text: "Review again", value: "review", kind: "primary", onclick: () => loadQueueMissing(ctx) }]);
    }
  }
}
