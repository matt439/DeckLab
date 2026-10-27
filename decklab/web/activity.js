/* The Activity page: who changed what in Deck Lab's database, newest first (GET /api/activity).
 * The server decides which changes and which of their rows each viewer may see (lib/api/activity.py) and words
 * each change as a plain headline ("User1 received the Example Games order: 16 cards") from those rows alone. The
 * page shows the first few rows of a change with "Show all", filter chips by kind and person (the server
 * filters, so "Load older" keeps to them), and links to the decks, cards (the card viewer) and orders.
 * Candidate inventory edits can open a server-authorized Undo review; only its explicit save writes. */
"use strict";

const ACTIVITY_VIA = { home: "at home", tunnel: "away" };
const ACTIVITY_SOURCES = { cli: "from the command line", sync: "by a sync", migration: "by an import",
  receipt: "by a receipt", test: "by a test" };
// The kinds a change can be filtered by (activity.py's KINDS), with who sees them as an option.
const ACTIVITY_KINDS = [
  { id: "decks", label: "Decks" },
  { id: "collection", label: "Collection" },
  { id: "tokens", label: "Tokens" },
  { id: "shopping", label: "Shopping", visible: () => seesHomeInventory(state.may) },
  { id: "wishlist", label: "Wishlist" },
  { id: "sleeves", label: "Sleeves & boxes", visible: () => seesAccessoriesAs(state.profile) },
  { id: "games", label: "Games" },
  { id: "settings", label: "Settings" },
];
const ACTIVITY_ROWS_SHOWN = 4;           // rows of a change shown before "Show all"
// Sources whose message Deck Lab wrote from the rows themselves: the headline already says it.
const ACTIVITY_OWN_WORDS = ["web", "receipt"];
// A message that is only a command and an id ("receive 2026-01-05-examplegames", "deck tables casual/burn") says
// less than the headline. The id must have a digit or a slash, so a short note written by hand ("fix typo",
// "tuned sideboard plan") is kept.
const ACTIVITY_COMMAND = /^[a-z]+(?: [a-z]+)? (?=[\w.\/-]*[\d\/])[\w.\/-]+$/;
const ACTIVITY_ORDER_TABLES = ["purchase_order", "order_component", "order_card_item", "order_token_item"];

function showActivity(params, token) {
  const filter = activityFilter(params);
  return load(activityPath(filter), token, (data) => activityDraw(data, token, filter),
    { title: "Activity couldn't be loaded" });
}

/** The filter the address asks for: {kind, actor}, each null for all (an unknown kind is ignored). */
function activityFilter(params) {
  const kind = params.get("kind");
  const actor = params.get("actor");
  return { kind: ACTIVITY_KINDS.some((k) => k.id === kind) ? kind : null,
    actor: actor && /^[a-z0-9-]{1,40}$/.test(actor) ? actor : null };
}

/** The API address for a filter, after an older change set (before) when given. */
function activityPath(filter, before = null) {
  const query = new URLSearchParams();
  if (before != null) query.set("before", before);
  if (filter.kind) query.set("kind", filter.kind);
  if (filter.actor) query.set("actor", filter.actor);
  const text = query.toString();
  return text ? `/api/activity?${text}` : "/api/activity";
}

/** The page's own address for a filter (the chips are links, so Back steps through them). */
function activityHref(filter) {
  const query = new URLSearchParams();
  if (filter.kind) query.set("kind", filter.kind);
  if (filter.actor) query.set("actor", filter.actor);
  const text = query.toString();
  return text ? `#/activity?${text}` : "#/activity";
}

/** The first page: the head, the filters, the changes grouped by day, and "Load older" while there are more. */
function activityDraw(data, token, filter = { kind: null, actor: null }) {
  const view = { token, filter, seq: 0, profile: state.profile?.id, hash: location.hash, loadedPages: 1,
    next: data.next, days: el("div", { class: "activity-days" }),
    lastDay: null, lastList: null, shown: 0, empty: null, everything: data.everything,
    cards: { ...(data.cards || {}) }, people: new Map(), peopleRow: null };
  const note = el("p", { class: "activity-note", role: "status", "aria-live": "polite", tabindex: "-1" });
  const older = el("button", { type: "button", class: "btn", text: "Load older" });
  view.older = older; view.note = note;
  older.addEventListener("click", () => activityOlder(view, older, note));
  view.peopleRow = el("nav", { class: "activity-filter", "aria-label": "Whose changes" });
  activityAppend(view, data.changes);
  older.hidden = !view.next;
  // The server scans only so far back per answer, so a first page can be empty with more beyond it.
  if (!view.shown) view.empty = activityEmpty(view);
  add($("#main"), [
    pageHead({ title: routeH1("activity"), description: data.everything
      ? "Every change saved in Deck Lab, newest first. Other people's wishlists stay theirs."
      : "Changes to the decks, cards and settings you can see, newest first." }),
    // The filters above the changes; from 1600px a rail beside them (activity.css).
    el("div", { class: "activity-layout" },
      el("div", { class: "activity-filters" }, activityKinds(filter), view.peopleRow),
      el("div", { class: "activity-main" }, view.days, view.empty, el("div", { class: "activity-more" }, older, note)))]);
  return view;
}

/** The kind chips: All, then each kind this viewer can have changes of. */
function activityKinds(filter) {
  const kinds = ACTIVITY_KINDS.filter((k) => !k.visible || k.visible());
  const chip = (kind, label) => el("a", { class: "filter-chip", href: activityHref({ ...filter, kind }),
    "aria-current": filter.kind === kind ? "page" : null, text: label });
  return el("nav", { class: "activity-filter", "aria-label": "Kind of change" },
    el("div", { class: "filter-chips filter-chips-scroll" }, chip(null, "All"),
      kinds.map((k) => chip(k.id, k.label))));
}

/** The person chips: Everyone, then each person among the changes shown so far (the one filtered by stays).
 * Only drawn when there's a choice to make. */
function activityPeople(view) {
  const { filter } = view;
  const people = [...view.people];
  clear(view.peopleRow);
  if (people.length < 2 && !filter.actor) return;
  const chip = (actor, label) => el("a", { class: "filter-chip", href: activityHref({ ...filter, actor }),
    "aria-current": filter.actor === actor ? "page" : null, text: label });
  view.peopleRow.append(el("div", { class: "filter-chips filter-chips-scroll" }, chip(null, "Everyone"),
    people.map(([id, name]) => chip(id, name))));
}

/** What the page says while it shows no change, with the one action that helps: there may be more further
 * back (Load older is right below), or there's none at all, or none of this filter's. */
function activityEmpty(view) {
  const box = el("div", { class: "empty activity-empty" }, el("p", { text: activityNothing(view) }));
  if (activityFiltered(view.filter)) box.append(el("a", { class: "btn", href: "#/activity", text: "Show every change" }));
  return box;
}

/** True for a message that is only a command and an id (ACTIVITY_COMMAND); History hides those too. */
function activityCommandOnly(text) { return ACTIVITY_COMMAND.test(String(text || "").trim()); }

function activityFiltered(filter) { return Boolean(filter.kind || filter.actor); }

function activityNothing(view) {
  const filtered = activityFiltered(view.filter);
  if (view.next) {
    return filtered ? "None of these among the latest changes: Load older looks further back."
      : "None you can see among the latest changes: Load older looks further back.";
  }
  if (filtered) return "No changes like these.";
  return view.everything ? "Nothing has changed yet." : "Nothing you can see has changed yet.";
}

/** Add changes (newest first) to the page, continuing the last day shown when they start on it.
 * Returns the first card added, or null. */
function activityAppend(view, changes) {
  let first = null;
  for (const change of changes) {
    const when = new Date(change.at);
    const day = activityDayKey(when);
    if (day !== view.lastDay) {
      view.lastDay = day;
      view.lastList = el("ol", { class: "activity-list" });
      view.days.append(el("section", { class: "activity-day" },
        el("h2", { class: "activity-day-head", text: activityDayName(when) }), view.lastList));
    }
    const card = activityCard(change, when, view);
    first = first || card;
    view.lastList.append(el("li", {}, card));
    view.shown += 1;
    if (change.actor && change.actor_name && !view.people.has(change.actor)) {
      view.people.set(change.actor, capitalise(change.actor_name));
    }
  }
  if (view.filter.actor && !view.people.has(view.filter.actor)) {
    const known = (state.profiles || []).find((p) => p.id === view.filter.actor);
    view.people.set(view.filter.actor, known ? known.name : capitalise(view.filter.actor));
  }
  activityPeople(view);
  if (view.shown && view.empty) {
    view.empty.remove();
    view.empty = null;
  }
  return first;
}

/** Where a change's headline goes: its deck's page, or its order's receipt details; null for none. */
function activityLink(link) {
  if (!link) return null;
  if (link.history) return `#/history?id=${encodeURIComponent(link.history)}`;
  if (link.deck) return link.retired ? `#/history?id=${encodeURIComponent(link.deck)}` : deckHref(link.deck);
  if (link.order && seesHomeInventory(state.may)) return `#/receipt?order=${encodeURIComponent(link.order)}`;
  return null;
}

/** One change: its headline (a link to what it's about), when and from where, a message written by hand and
 * its reason, and its rows: the first few, with "Show all" for the rest. */
function activityCard(change, when, view) {
  const where = change.source === "web" ? ACTIVITY_VIA[change.via] : ACTIVITY_SOURCES[change.source];
  const headline = change.headline || `${capitalise(change.actor_name || "someone")} made a change`;
  const href = activityLink(change.link);
  const summaries = change.rows.map((row) => row.summary);
  // A message Deck Lab wrote from the rows (a page's save, a receipt) says what the headline says.
  const message = change.message && !ACTIVITY_OWN_WORDS.includes(change.source)
    && change.message !== summaries.join("; ") && !activityCommandOnly(change.message) ? change.message : null;
  const rows = activityRows(change, view);
  return el("article", { class: "activity-change", "data-activity-id": change.id, tabindex: "-1" },
    el("h3", { class: "activity-headline" }, href ? el("a", { href, text: headline }) : headline),
    el("p", { class: "activity-meta" },
      el("time", { class: "activity-when", datetime: change.at, text: activityTime(when) }),
      where ? el("span", { class: "activity-where", text: where }) : null),
    message ? el("p", { class: "activity-message", text: `“${message}”` }) : null,
    change.reason ? el("p", { class: "activity-reason", text: `Why: ${change.reason}` }) : null,
    rows, activityUndoButton(view, change));
}

/** A change's rows as a list, or null when its one row only repeats the headline. The rows past the first
 * few are hidden until "Show all"; the card viewer still swipes through every card of the change, folded or
 * not (cards: the change's {card, caption} in row order, which each card row opens at its own place). */
function activityRows(change, view) {
  const rows = change.rows;
  if (!rows.length) return null;
  const cards = [];
  const parts = rows.map((row) => activityRow(row, change, view, cards));
  if (rows.length === 1 && !parts[0].matches("a") && !parts[0].matches("button")) return null;
  const items = parts.map((part) => el("li", {}, part));
  const list = el("ul", { class: "activity-rows" }, items);
  const hidden = items.slice(ACTIVITY_ROWS_SHOWN);
  if (hidden.length <= 1) return list;             // "Show all" for one more row would be as long as the row
  for (const item of hidden) item.hidden = true;
  // No count: the rows are printings (and past the server's cap one "and N more" line), so a number here would
  // never match the headline's count of cards.
  const toggle = el("button", { type: "button", class: "btn btn-quiet btn-inline activity-all", "aria-expanded": "false",
    text: "Show all" });
  toggle.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") !== "true";
    for (const item of hidden) item.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "Show fewer" : "Show all";
  });
  return el("div", { class: "activity-detail" }, list, toggle);
}

/** One row: a card it names opens the card viewer (swiping through the change's cards, those folded away
 * included: cards collects them), a deck links to its page, an order to its receipt details; anything else is
 * its summary in words. */
function activityRow(row, change, view, cards = []) {
  const record = row.after || row.before || {};
  const card = activityRowCard(row, record, view);
  if (card) {
    const index = cards.push({ card, caption: row.summary }) - 1;
    const node = cardRow(card, { qty: null, name: row.summary, meta: null, aside: null,
      onclick: (e) => openCardViewer(cards, index, { trigger: e.currentTarget }) });
    node.setAttribute("aria-haspopup", "dialog");
    return viewerItem(node, card, `activity-${change.id}`, row.summary);
  }
  if (row.table === "deck" && record.id) {
    return el("a", { class: "activity-link", href: row.op === "DELETE" ? `#/history?id=${encodeURIComponent(record.id)}` : deckHref(record.id), text: row.summary });
  }
  const order = row.table === "purchase_order" ? record.id : ACTIVITY_ORDER_TABLES.includes(row.table) ? record.order_id : null;
  if (order && row.op !== "DELETE" && seesHomeInventory(state.may)) {
    return el("a", { class: "activity-link", href: `#/receipt?order=${encodeURIComponent(order)}`, text: row.summary });
  }
  return el("span", { text: row.summary });
}

/** The card data the answer sent for a row that names a card (activity.py's card_key), or null. */
function activityRowCard(row, record, view) {
  if (!["collection_card", "watchlist_item", "wishlist_entry"].includes(row.table) || !record.name) return null;
  return view.cards[`${record.name}|${record.set_code || ""}|${record.collector_number || ""}`] || null;
}

/** The next page, after the oldest change shown; an answer for a page left, or an older click, is dropped.
 * When the button had focus and goes (the end of the trail), focus moves to the first change it
 * added, or to the note, rather than falling back to the top of the page. */
async function activityOlder(view, button, note) {
  if (view.undoBusy || view.undoRefreshNeeded) return;
  const seq = ++view.seq;
  const hadFocus = document.activeElement === button;
  button.disabled = true;
  note.textContent = "Loading older changes…";
  try {
    const data = await api(activityPath(view.filter, view.next));
    if (view.token !== routeToken || seq !== view.seq) return;
    Object.assign(view.cards, data.cards || {});
    const first = activityAppend(view, data.changes);
    view.loadedPages = (view.loadedPages || 1) + 1;
    view.next = data.next;
    button.hidden = !view.next;
    if (view.empty) view.empty.querySelector("p").textContent = activityNothing(view);
    note.textContent = data.changes.length ? (view.next ? "" : "That's every change.")
      : view.next ? "None you can see in that stretch: Load older looks further back." : "There are no older changes.";
    const stillOwned = document.activeElement === button || !document.activeElement || document.activeElement === document.body;
    if (hadFocus && button.hidden && stillOwned) (first || note).focus({ preventScroll: !first });
  } catch (e) {
    if (view.token !== routeToken || seq !== view.seq) return;
    note.textContent = `Older changes couldn't be loaded: ${e.message}`;
  } finally {
    if (view.token === routeToken && seq === view.seq) {
      button.disabled = false;
      // Disabling it may have dropped the focus: give it back while the button stays.
      const lost = !document.activeElement || document.activeElement === document.body;
      if (hadFocus && !button.hidden && lost) button.focus({ preventScroll: true });
    }
  }
}

function activityDayKey(when) { return `${when.getFullYear()}-${when.getMonth()}-${when.getDate()}`; }

/** "Today", "Yesterday", or the date in words. */
function activityDayName(when) {
  const today = new Date();
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  if (activityDayKey(when) === activityDayKey(today)) return "Today";
  if (activityDayKey(when) === activityDayKey(yesterday)) return "Yesterday";
  return when.toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

function activityTime(when) {
  return when.toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit" }).replace(/\s/g, " ");
}
