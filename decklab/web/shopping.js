/* Shopping (UI-REVIEW.md WP10): a row of links to the parts (a phone's and a portrait tablet's), the deliveries on the way, each a disclosure titled "seller · topic" with a strip
of its cards' pictures, its arrival checks inside it and Receive delivery as its main action; follow-ups left
open on deliveries that have arrived, each with Done (POST /api/shopping/check, an admin's); the cards we've
decided to buy; the decks still missing cards (a link to each deck's missing cards, kept apart from the queue:
AGENTS.md, the queue is only what's been decided); the long-term plan, grouped by deck; and the order history,
folded. A personal wishlist stays a separate place for cards someone likes.

Every picture opens the card viewer over its own list (cards-ui.js viewerGroup), so a phone can swipe through a
delivery's cards or the long-term plan. */
"use strict";

const SHOPPING_STATES = {
  ready: "Ready to buy", waiting_for_stock: "Waiting for stock",
  waiting_for_reprint: "Waiting for reprint", deferred: "Deferred", long_term: "Long-term plan",
  pending: "On the way", partial: "Part received", received: "Received",
  cancelled: "Cancelled", ordered: "Ordered", preordered: "Preordered",
};
const SHOP_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const SHOP_SMALL_WORDS = new Set(["a", "an", "and", "at", "for", "in", "of", "on", "the", "to"]);
const SHOP_STRIP = 8;                   // pictures on a delivery card (6 on a phone)
const SHOP_LONG_TERM_SHOWN = 12;        // a long-term deck group's cards before "Show all"
const SHOP_QUEUE_STATES = ["ready", "waiting_for_stock", "waiting_for_reprint", "deferred", "long_term"];
const shopQueueSheets = new Set();

function shopTrackQueueSheet(sheet, view) {
  for (const old of shopQueueSheets) if (old.closed) shopQueueSheets.delete(old);
  sheet.queueView = view;
  shopQueueSheets.add(sheet);
  sheet.dialog.addEventListener("close", () => shopQueueSheets.delete(sheet));
  return sheet;
}

/** Queue sheets, including their printing picker, belong to the person and page that opened them. */
function shopCloseQueueSheets(view = null) {
  for (const sheet of [...shopQueueSheets].reverse()) {
    if (view && sheet.queueView !== view) continue;
    sheet.close();
    shopQueueSheets.delete(sheet);
  }
}

function showShopping(token) {
  return load("/api/shopping", token, drawShopping, { title: "Shopping couldn't be loaded" });
}

/** "5 Oct" ("5 Oct 2025" in another year) for a YYYY-MM-DD date; the text as it is otherwise. */
function shopDay(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  if (!m) return iso || "";
  const year = Number(m[1]), now = new Date().getFullYear();
  return `${Number(m[3])} ${SHOP_MONTHS[Number(m[2]) - 1]}${year === now ? "" : ` ${year}`}`;
}

/** Words of an order id's topic in title case: "a-night-in-the-woods" -> "A Night in the Woods". */
function shopTitleCase(words) {
  return words.map((w, i) => (i && SHOP_SMALL_WORDS.has(w) ? w : capitalise(w))).join(" ");
}

/** An order's topic: its product's name, else its id after the date with the seller's own words taken off the
 * front ("2026-01-05-ebay-goblins" from eBay -> "Goblins"); "" when nothing is left ("2026-01-08-examplegames"). */
function shopTopic(order) {
  const product = (order.components || []).find((c) => c.kind === "product" && c.label);
  if (product) return product.label;
  const seller = String(order.seller || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  const words = String(order.id || "").replace(/^\d{4}-\d{2}-\d{2}-/, "").replace(/^product-/, "").split("-").filter(Boolean);
  while (seller && words.length && words[0].length >= 2 && seller.includes(words[0])) words.shift();
  return words.length ? shopTitleCase(words) : "";
}

/** "eBay · Goblins", "Example Games", or the topic alone when the seller isn't recorded. */
function shopOrderTitle(order) {
  const topic = shopTopic(order);
  if (!order.seller) return topic || "Order";
  return topic ? `${order.seller} · ${topic}` : order.seller;
}

/** "3 cards", "13 token cards", "100 cards in the product": what a component holds, in plain words. */
function shopUnits(component) {
  if (component.kind === "tokens") return plural(component.quantity, "token card");
  return plural(component.quantity, "card");
}

/** A state worth a chip on a delivery (the section already says "On the way"): part received (a neutral outline:
 * a delivery state isn't teal, visual-design.md section 6 question 2), preordered. */
function shopOrderChip(order) {
  if (order.status === "partial") return status("outline", "Part received");
  const product = (order.components || []).find((c) => c.kind === "product" && c.status === "pending");
  return product && product.product_status === "preordered" ? status("info", "Preordered") : null;
}

/** The pictures strip of a delivery: up to 8 of its cards (6 on a phone, by CSS, so a rotation needs no
 * redraw), each opening the viewer over the strip, then "+N" for the copies not shown, which opens the whole
 * list. A wide screen shows 7 and "+N" when there are more than 8 printings, a phone 5 and "+N" past 6; each
 * "+N" counts the copies after the pictures shown on that screen. */
function shopStrip(order, items) {
  const wideShown = items.length > SHOP_STRIP ? SHOP_STRIP - 1 : items.length;
  const narrowShown = items.length > SHOP_STRIP - 2 ? SHOP_STRIP - 3 : items.length;
  const group = `delivery-${order.id}`;
  const copies = (list) => list.reduce((sum, { item }) => sum + (Number(item.quantity) || 1), 0);
  const all = copies(items);
  const thumbs = items.slice(0, wideShown).map(({ item, component }, n) => {
    const card = item.card || null;
    const label = `${item.quantity > 1 ? `${item.quantity} × ` : ""}${item.name}`;
    const node = el("button", { type: "button", class: "shop-thumb", title: label, "aria-label": label,
      "aria-haspopup": card ? "dialog" : null, onclick: (e) => (card ? openCard(card, e.currentTarget) : shopContents(order)) },
      // The name is always under the picture, so a picture still loading (or one that can't) shows a word tile,
      // never an empty grey box.
      el("span", { class: "shop-thumb-text", "aria-hidden": "true", text: frontName(item.name) }),
      card && card.img_small
        ? el("img", { src: card.img_small, alt: "", loading: "lazy", decoding: "async", width: 61, height: 85,
          onerror: (e) => e.currentTarget.remove() }) : null,
      item.quantity > 1 ? el("span", { class: "shop-thumb-qty", "aria-hidden": "true", text: `×${item.quantity}` }) : null);
    if (card) viewerItem(node, card, group, `${label} · ${shopUnits(component)} in ${shopOrderTitle(order)}`);
    return el("li", { class: n >= narrowShown ? "shop-wide-only" : null }, node);
  });
  const more = (shown, cls) => el("li", { class: cls }, el("button", { type: "button", class: "shop-thumb shop-thumb-more",
    "aria-label": `Show all ${plural(all, "card")}`, onclick: () => shopContents(order) }, `+${copies(items.slice(shown))}`));
  if (narrowShown < items.length) thumbs.push(more(narrowShown, "shop-narrow-only"));
  if (wideShown < items.length) thumbs.push(more(wideShown, "shop-wide-only"));
  return el("ul", { class: "shop-strip", "aria-label": "Cards in this delivery" }, thumbs);
}

/** Every card of an order's components in a sheet, each row opening the viewer over the whole list. */
function shopContents(order) {
  const sheet = openSheet({ title: shopOrderTitle(order), wide: true });
  const group = `contents-${order.id}`;
  for (const component of order.components || []) {
    const items = component.items || [];
    if (!items.length) continue;
    const many = (order.components || []).filter((c) => (c.items || []).length).length > 1;
    add(sheet.body, [
      many ? el("h3", { class: "shop-contents-head", text: shopComponentWords(component) }) : null,
      el("div", { class: "shop-contents" }, items.map((item) => {
        const printing = [item.set && item.set.toUpperCase(), item.collector_number,
          item.finish && item.finish !== "nonfoil" ? capitalise(item.finish) : null].filter(Boolean).join(" ");
        return cardRow(item.card || null, { qty: item.quantity, name: item.name,
          meta: item.card ? (printing || item.card.type_line) : undefined,
          unknownMeta: component.kind === "tokens" ? "Token card" : printing || "No card data",
          viewerGroup: group, caption: `${item.quantity} in ${shopOrderTitle(order)}` });
      }))]);
  }
  sheetActions(sheet, [{ text: "Close", onclick: () => sheet.close() }]);
  return sheet;
}

/** One component in words: "15 cards", "13 token cards", "Goblin Horde: 100 cards", with its arrival. */
function shopComponentWords(component) {
  const what = component.kind === "product" && component.label
    ? `${component.label}: ${shopUnits(component)}` : capitalise(shopUnits(component));
  if (component.status === "received") return `${what} · arrived ${shopDay(component.received_on)}`;
  if (component.status === "cancelled") return `${what} · cancelled`;
  return what;
}

/** A compact delivery row opens its existing contents, checks and actions in place. */
function shopDelivery(order, checks, view = null) {
  const components = order.components || [];
  const pending = components.filter((c) => c.status === "pending");
  const items = pending.flatMap((component) => (component.items || []).map((item) => ({ item, component })));
  const total = pending.reduce((sum, c) => sum + (c.quantity || 0), 0);
  const kinds = new Set(pending.map((c) => c.kind));
  const words = kinds.size === 1 && kinds.has("tokens") ? plural(total, "token card") : plural(total, "card");
  const receive = pending.length && mayDo("receipts");
  const href = `#/receipt?order=${encodeURIComponent(order.id)}`;
  const keyHint = receive && view ? `shop-receive-key-${encodeURIComponent(order.id)}` : null;
  return el("details", { class: "panel shop-delivery" },
    el("summary", { class: "shop-delivery-summary", "aria-keyshortcuts": keyHint ? "R" : null,
      "aria-describedby": keyHint, onkeydown: (event) => shopReceiveKey(view, order, event) }, el("h3", {},
      el("span", { class: "shop-delivery-head" },
        el("span", { class: "shop-delivery-title", text: shopOrderTitle(order) }), shopOrderChip(order)),
      el("span", { class: "sub shop-delivery-meta", text: [order.ordered_on ? `Ordered ${shopDay(order.ordered_on)}` : "Order date not recorded", words]
        .join(" · ") }))),
    el("div", { class: "shop-delivery-body" },
    keyHint ? el("span", { class: "sr-only", id: keyHint,
      text: "Press R from this delivery row to open Receive delivery. Enter or Space expands or collapses the row." }) : null,
    items.length ? shopStrip(order, items) : null,
    components.length > 1 ? el("ul", { class: "shop-parts" }, components.map((c) => el("li", { text: shopComponentWords(c) }))) : null,
    order.notes ? el("p", { class: "shop-notes", text: order.notes, title: order.notes }) : null,
    checks.length ? shopChecks(checks) : null,
    el("div", { class: "actions" },
      receive ? el("a", { class: "btn btn-secondary", href, text: "Receive delivery" })
        : el("a", { class: "btn btn-quiet", href, text: "Delivery details" }),
      receive && view ? el("span", { class: "shop-receive-hint", "aria-hidden": "true",
        title: "With this delivery row focused, press R to receive it." }, el("kbd", { text: "R" })) : null,
      shopOrderEditButton(order, view))));
}

/** R opens only the focused live delivery row; native Enter/Space keep their disclosure behavior. */
function shopReceiveKey(view, order, event) {
  if (event.defaultPrevented || event.isComposing || event.repeat || event.ctrlKey || event.metaKey || event.altKey
      || String(event.key || "").toLowerCase() !== "r") return;
  const summary = event.currentTarget;
  if (!view || !shopQueueActive(view) || view.busy || view.stale || !summary?.isConnected
      || event.target !== summary || document.activeElement !== summary || !view.root.contains(summary)) return;
  const current = (view.data.orders || []).find((item) => item.id === order.id);
  if (current !== order || !mayDo("receipts") || !(current.components || []).some((part) => part.status === "pending")) return;
  event.preventDefault();
  location.hash = `#/receipt?order=${encodeURIComponent(current.id)}`;
}

/** The checks to make when a delivery arrives. Open on a wide screen; folded on a phone ("Check when it
 * arrives · 2"), so the deliveries stay short there and what to buy is near the top (the receipt page shows the
 * checks again). */
function shopChecks(checks) {
  const narrow = typeof matchMedia === "function" && matchMedia("(max-width: 599px)").matches;
  return el("details", { class: "shop-checks", open: !narrow },
    el("summary", {}, el("span", { text: "Check when it arrives" }),
      checks.length > 1 ? el("span", { class: "shop-checks-count", text: ` · ${checks.length}` }) : null),
    el("ul", {}, checks.map((check) => el("li", { text: check.text }))));
}

/** A row of links to the page's parts, for a phone or a tablet in portrait, where the parts are one column:
 * "On the way 8 · To buy 3 · Decks missing cards 5 · Follow-ups 4 · Long-term plan", each with its count. */
function shopJumps(parts) {
  const shown = parts.filter((p) => p.count);
  if (shown.length < 2) return null;
  return el("nav", { class: "shop-jumps", "aria-label": "Parts of this page" },
    el("ul", {}, shown.map((p) => el("li", {}, el("a", { href: `#${p.id}`,
      onclick: (e) => {
        e.preventDefault();
        const target = document.getElementById(p.id);
        if (target) {
          target.setAttribute("tabindex", "-1");
          target.focus({ preventScroll: true });
          target.scrollIntoView({ block: "start" });
        }
      } }, el("span", { text: p.label }), p.number > 1 ? el("span", { class: "shop-count", text: String(p.number) }) : null)))));
}

/** A follow-up left open on a delivery that has arrived: what to check, where it came from, and Done. */
function shopFollowUp(check, order) {
  const title = order ? shopOrderTitle(order) : check.seller || "Delivery";
  const component = order && (order.components || []).find((c) => c.id === check.component_id);
  const row = el("li", { class: "shop-followup" },
    el("div", { class: "shop-followup-text" },
      el("p", { text: check.text }),
      el("p", { class: "sub" }, el("a", { href: `#/receipt?order=${encodeURIComponent(check.order_id)}`, text: title }),
        component && component.received_on ? ` · arrived ${shopDay(component.received_on)}` : "")),
    mayDo("orders") ? el("button", { type: "button", class: "btn", text: "Done",
      "aria-label": `Done: ${check.text}`, onclick: () => shopDone(check, row) }) : null);
  return row;
}

/** The follow-ups marked Done whose Undo time hasn't run out: one toast and one timer for all of them, so a
 * second Done never takes the first one's Undo away. */
let shopPendingDone = null;

/** Done on a follow-up: it leaves the list at once, with Undo for 8 seconds (ui.js showToast); the check is
 * marked done (POST /api/shopping/check) when that time is up, unless Undo was pressed. Dones pressed while
 * the toast is up join it ("2 checks marked done."), restart its time, and Undo puts them all back. The focus
 * moves to the next follow-up's Done (else the previous one's, else the toast's Undo), and back to the row's
 * Done when Undo restores it. Returns {commit, cancel} for this row. */
function shopDone(check, row) {
  const list = row.parentNode;
  const visible = () => Array.from(list.children).filter((n) => !n.hidden);
  const before = visible(), at = before.indexOf(row);
  let phase = "waiting";
  row.hidden = true;
  const button = (node) => node && node.querySelector("button");
  const restore = () => {
    row.hidden = false;
    shopFollowUpsCount(list);
  };
  const work = {
    row,
    cancel() { if (phase !== "waiting") return; phase = "cancelled"; restore(); },
    async commit() {
      if (phase !== "waiting") return;
      phase = "sent";
      try {
        await apiWrite("/api/shopping/check", { order: check.order_id, component: check.component_id, check: check.text });
        row.remove();
        shopFollowUpsCount(list);
      } catch (error) {
        restore();
        toast(`That check couldn't be marked done: ${error.message}`);
      }
    },
  };
  const batch = shopPendingDone || { works: [], timer: null };
  shopPendingDone = batch;
  batch.works.push(work);
  clearTimeout(batch.timer);
  batch.timer = setTimeout(() => {
    if (shopPendingDone === batch) shopPendingDone = null;
    batch.works.forEach((w) => w.commit());
  }, UNDO_MS);
  const words = batch.works.length > 1 ? `${batch.works.length} checks marked done.` : "Check marked done.";
  showToast(words, { undo: () => {
    clearTimeout(batch.timer);
    if (shopPendingDone === batch) shopPendingDone = null;
    batch.works.forEach((w) => w.cancel());
    const first = button(batch.works[0].row);
    if (first && first.isConnected) first.focus();
  } });
  shopFollowUpsCount(list);
  const next = before[at + 1] || before[at - 1];
  const undo = document.getElementById("toast-undo");
  const target = button(next) || (undo && undo.querySelector("button"));
  if (target) target.focus();
  return work;
}

/** Keeps the Follow-ups heading's count in step with the rows still shown (none for a single one), and hides
 * the section when none are left. */
function shopFollowUpsCount(list) {
  const section = list && list.closest ? list.closest("section") : null;
  if (!section) return;
  const left = Array.from(list.children).filter((n) => !n.hidden).length;
  section.hidden = !left;
  const count = section.querySelector(".shop-count");
  if (count) {
    count.textContent = String(left);
    count.setAttribute("aria-label", `${left} items`);
    count.hidden = left <= 1;
  }
}

/** The printing a queued card asks for, in words: "Any printing", "Exact: FDN 2 foil". */
function shopPrinting(card) {
  const finish = card.finish && card.finish !== "nonfoil" ? card.finish : "";
  if (card.printing !== "exact") return finish ? `Any printing, ${finish}` : "Any printing";
  return `Exact: ${[card.set && card.set.toUpperCase(), card.collector_number, finish].filter(Boolean).join(" ")}`;
}

/** A reference price: the lowest price seen and where, never a claim of live stock. null without one. */
function shopPrice(card) {
  if (card.listed_aud === "" || card.listed_aud == null) return null;
  const amount = Number(card.listed_aud);
  if (!Number.isFinite(amount)) return null;
  return `${aud(amount)}${card.listed_at ? ` at ${card.listed_at}` : ""}`;
}

/** A queued card as a row: its picture, copies, what it's for and which printing, a chip for a state that
 * isn't "ready", the reference price at the end. A deck link sits outside the card-viewer button. */
function shopQueueRow(card, group, showFor = true, view = null, showLongTerm = false, grouped = false) {
  const price = shopPrice(card);
  const chips = [!grouped && card.state && card.state !== "ready" && (showLongTerm || card.state !== "long_term") ? status("warn", SHOPPING_STATES[card.state]) : null,
    !view && card.in_stock === "no" && price ? status("plain", "Out of stock when checked") : null].filter(Boolean);
  const deck = showFor ? card.deck : null;
  const reason = grouped && ["waiting_for_stock", "waiting_for_reprint"].includes(card.state) ? SHOPPING_STATES[card.state]
    : grouped && !SHOP_QUEUE_STATES.includes(card.state) ? `State: ${card.state || "not recorded"}` : null;
  const meta = [showFor && !deck && card.for ? card.for : null, shopPrinting(card), reason].filter(Boolean).join(" · ");
  const row = cardRow(card.card || null, { qty: card.quantity, name: card.name, meta, unknownMeta: meta, chips,
    aside: null, viewerGroup: group, caption: shopQueueCaption(card) });
  const metaNode = row.querySelector("small");
  if (metaNode) add(clear(metaNode), [showFor && !deck && card.for ? `${card.for} \u00b7 ` : null,
    shopPrintingMeta(card), reason ? ` \u00b7 ${reason}` : null]);
  if (row.matches("button")) row.setAttribute("aria-label", `${card.name}, ${plural(card.quantity, "copy", "copies")}`);
  const move = view && mayDo("orders") && view.data.queue_revision && card.queue_row
    ? shopQueueMove(card, view) : null;
  const reprints = reprintInfo(card);
  return view || deck || move || price || reprints ? el("div", { class: "shop-queue-row",
    "data-shop-queue": view ? String(card.queue_row || "") : null, "data-shop-name": view ? shopQueueShop(card) : null,
    "data-shop-match": view && shopMatches(view, card) ? "true" : null }, row,
    view ? shopQueueResearch(card) : price ? shopReference(card) : null,
    view ? el("span", { class: "sr-only shop-match-words", text: shopMatches(view, card) ? "Matches selected shop." : "" }) : null,
    deck ? el("a", { class: "shop-queue-deck", href: deckHref(deck.id) }, shopDeckSwatch(deck), deck.title) : null, reprints, move) : row;
}

/** Move controls stay outside the card viewer. Only the existing purchase state changes. */
function shopQueueMove(card, view) {
  const error = el("div", { class: "form-error", role: "alert", hidden: true });
  const menu = menuButton("Move", SHOP_QUEUE_STATES.filter((key) => key !== card.state).map((key) => ({
    label: SHOPPING_STATES[key], onclick: () => shopMoveQueue(card, key, view, error),
  })), { aria: `Move ${card.name} to another category`, buttonClass: "btn btn-quiet shop-category-move" });
  const button = menu.querySelector(".menu-button");
  button.setAttribute("data-queue-row", card.queue_row);
  button.addEventListener("click", () => shopQueueMenuPosition(button, menu.querySelector(".menu")));
  const details = el("button", { type: "button", class: "btn btn-quiet shop-queue-edit shop-queue-write",
    "data-queue-row": card.queue_row, text: "Details…", "aria-label": `Change ${card.name}`,
    onclick: () => shopQueueSheet(view, card) });
  button.disabled = details.disabled = Boolean(view.busy || view.stale);
  button.setAttribute("class", `${button.getAttribute("class")} shop-queue-write`);
  return el("div", { class: "shop-queue-actions" }, el("div", { class: "actions" }, menu, details), error);
}

/** All queue writes share one revision and one pending request, including Move. */
function shopQueueBusy(view, busy) {
  view.busy = busy;
  view.root.querySelectorAll(".shop-queue-write").forEach((button) => { button.disabled = busy || view.stale; });
  for (const sheet of shopQueueSheets) {
    if (sheet.queueView !== view) continue;
    if (sheet.queueBusy) { sheet.queueBusy(); continue; }
    sheet.dialog.querySelectorAll("button").forEach((button) => {
      if (["Save", "Add card", "Remove…", "Remove card"].includes(button.textContent)) button.disabled = busy || view.stale;
    });
  }
}

function shopQueueActive(view) {
  return view.root.isConnected && view.token === routeToken && state.profile && state.profile.id === view.profile;
}

/** Quantity and notes can change without replacing a row's printing or research. */
function shopQueueSheet(view, card = null) {
  if (!shopQueueActive(view) || view.busy || view.stale) return null;
  const sheet = shopTrackQueueSheet(openSheet({ title: card ? card.name : "Add a card to the purchase queue" }), view);
  const form = el("form", { class: "shop-queue-form" });
  const inputs = {};
  const field = (key, label, tag = "input", props = {}, children = []) => {
    const input = el(tag, { id: `shop-${key}-${sheet.heading.id}`, "data-queue-field": key, ...props }, children);
    inputs[key] = input;
    form.append(el("label", { class: "field", for: input.id }, el("span", { text: label }), input));
    return input;
  };
  let printing = null, nameSeq = 0, timer = null;
  const alive = () => !sheet.closed && shopQueueActive(view);
  if (!card) {
    const names = el("datalist", { id: `shop-names-${sheet.heading.id}` });
    const name = field("name", "Card name", "input", { type: "text", required: true, maxlength: 150,
      autocomplete: "off", autocapitalize: "none", spellcheck: "false", list: names.id });
    form.append(names);
    name.addEventListener("input", () => {
      clearTimeout(timer);
      const seq = ++nameSeq, query = name.value.trim();
      printing = null;
      sayPrinting();
      clear(names);
      if (query.length < 2) return;
      timer = setTimeout(async () => {
        if (!alive()) return;
        try {
          const answer = await api(`/api/cards/search?q=${encodeURIComponent(query)}&limit=8`);
          if (alive() && seq === nameSeq && name.value.trim() === query)
            add(names, (answer.cards || []).map((item) => el("option", { value: item.name })));
        } catch (error) { /* The server validates the entered name on Save. */ }
      }, 180);
    });
  } else form.append(el("p", { class: "sub", text: [card.for, shopPrinting(card)].filter(Boolean).join(" · ") }));
  field("quantity", "Copies", "input", { type: "number", inputmode: "numeric", min: 1, max: 9999,
    step: 1, required: true, value: card ? card.quantity : 1 });
  if (!card) {
    const category = field("state", "Category", "select", {}, SHOP_QUEUE_STATES.map((key) =>
      el("option", { value: key, text: SHOPPING_STATES[key] })));
    category.value = "ready";
    const deck = field("deck", "For deck", "select", {}, [el("option", { value: "", text: "Not for a deck" }),
      ...(view.data.queue_decks || []).map((item) => el("option", { value: item.id, text: item.title }))]);
    deck.value = "";
  }
  const notes = field("notes", "Notes", "input", { type: "text", maxlength: 2000 });
  notes.value = card ? card.notes || "" : "";
  const printingWords = el("p", { class: "field-hint" });
  function sayPrinting() {
    printingWords.textContent = printing
      ? `Exact: ${printing.set.toUpperCase()} ${printing.number} ${printing.finish}` : "Any printing, nonfoil";
  }
  sayPrinting();
  if (!card) form.append(el("div", { class: "field" }, el("span", { text: "Printing" }), printingWords,
    el("div", { class: "actions" },
      el("button", { type: "button", class: "btn", text: "Choose exact printing…", onclick: async () => {
        const name = inputs.name.value.trim();
        if (!name || view.busy) { inputs.name.focus(); return; }
        const picked = await pickPrinting(name, { current: printing, title: `Printing for ${name}`,
          onOpen: (picker) => shopTrackQueueSheet(picker, view) });
        if (alive() && inputs.name.value.trim() === name && picked && picked.set) { printing = picked; sayPrinting(); }
      } }),
      el("button", { type: "button", class: "btn btn-quiet", text: "Any printing", onclick: () => { printing = null; sayPrinting(); } }))));
  const error = el("div", { class: "form-error", role: "alert", hidden: true });
  sheet.queueError = error;
  form.append(error);
  sheet.body.append(form);
  const submit = async () => {
    if (!alive() || view.busy || view.stale) return;
    const quantity = Number(inputs.quantity.value);
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 9999) {
      error.textContent = "Copies must be a whole number from 1 to 9999."; error.hidden = false; inputs.quantity.focus(); return;
    }
    let values = { quantity, notes: notes.value };
    if (!card) {
      const name = inputs.name.value.trim();
      if (!name) { error.textContent = "Enter a card name."; error.hidden = false; inputs.name.focus(); return; }
      const deck = (view.data.queue_decks || []).find((item) => item.id === inputs.deck.value);
      values = { ...values, name, state: inputs.state.value, for: deck ? deck.title : "",
        source: deck ? `magic/decks/${deck.id}.md` : "", printing: printing ? "exact" : "any",
        set: printing ? printing.set : "", collector_number: printing ? printing.number : "",
        finish: printing ? printing.finish : "nonfoil" };
    }
    await shopSaveQueue(view, sheet, error, card ? { action: "edit", row: card.queue_row, values }
      : { action: "add", values }, card);
  };
  form.addEventListener("submit", (event) => { event.preventDefault(); submit(); });
  sheetActions(sheet, [card ? { text: "Remove…", kind: "danger btn-quiet", onclick: () => shopRemoveQueueSheet(view, card, sheet) } : null,
    { text: "Cancel", onclick: () => sheet.close() }, { text: card ? "Save" : "Add card", kind: "primary", onclick: submit }]);
  (inputs.name || inputs.quantity).focus();
  return sheet;
}

function shopRemoveQueueSheet(view, card, parentSheet) {
  if (!shopQueueActive(view) || view.busy || view.stale) return null;
  const sheet = shopTrackQueueSheet(openSheet({ title: `Remove ${card.name}?` }), view);
  const reason = el("input", { type: "text", id: `shop-reason-${sheet.heading.id}`, "data-queue-field": "reason",
    maxlength: 2000, required: true });
  const error = el("div", { class: "form-error", role: "alert", hidden: true });
  sheet.queueError = error;
  add(sheet.body, [el("p", { text: `Remove ${card.quantity} ${card.quantity === 1 ? "copy" : "copies"} from the purchase queue.` }),
    el("label", { class: "field", for: reason.id }, el("span", { text: "Reason" }), reason), error]);
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() },
    { text: "Remove card", kind: "danger btn-primary", onclick: async () => {
      if (!reason.value.trim()) { error.textContent = "Enter a reason for removing this card."; error.hidden = false; reason.focus(); return; }
      const saved = await shopSaveQueue(view, sheet, error,
        { action: "remove", row: card.queue_row, reason: reason.value.trim() }, card);
      if (saved) {
        parentSheet.close();
        const addButton = view.root.querySelector(".shop-queue-add");
        if (addButton && shopQueueActive(view)) addButton.focus({ preventScroll: true });
      }
    } }]);
  reason.focus();
  return sheet;
}

/** Save before changing the page. Structural changes re-number rows in the returned revision's order. */
async function shopSaveQueue(view, sheet, error, body, card) {
  if (sheet.closed || !shopQueueActive(view) || view.busy || view.stale) return false;
  const row = card && card.queue_row, expect = view.data.queue_revision;
  shopQueueBusy(view, true);
  sheet.dialog.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  error.hidden = true;
  let focusAfter = null;
  try {
    const answer = await apiWrite("/api/shopping/queue", { ...body, expect });
    if (!shopQueueActive(view)) { shopCloseQueueSheets(view); return false; }
    const queue = view.data.to_buy;
    if (body.action === "remove") queue.splice(row - 1, 1);
    else if (body.action === "edit") {
      // A corrected identity may change token/playable classification. Metadata-only
      // edits retain positive token evidence while the card cache is unavailable.
      if (["name", "set", "collector_number", "finish"].some(key => (card[key] || "") !== (answer.item[key] || "")))
        delete card.is_token;
      Object.assign(card, answer.item);
      if (Object.hasOwn(answer, "reprints")) card.reprints = answer.reprints;
    }
    else {
      const item = { ...answer.item, card: answer.item.card || null, deck: (view.data.queue_decks || []).find((deck) =>
        answer.item.source === `magic/decks/${deck.id}.md`) || null };
      if (Object.hasOwn(answer, "reprints")) item.reprints = answer.reprints;
      queue.push(item);
      if (item.state === "long_term") view.expanded.add(item.deck ? item.deck.id : item.for || "");
    }
    queue.forEach((item, index) => { item.queue_row = index + 1; });
    view.data.queue_revision = answer.revision;
    view.redraw();
    sheet.close();
    focusAfter = body.action === "edit" ? Array.from(view.root.querySelectorAll(".shop-queue-edit"))
      .find((button) => Number(button.dataset.queueRow) === row) : view.root.querySelector(".shop-queue-add");
    toast(body.action === "remove" ? `${card.name} removed from the purchase queue.`
      : body.action === "edit" ? `${card.name} updated.` : `${answer.item.name} added to the purchase queue.`);
    return true;
  } catch (failure) {
    if (!shopQueueActive(view)) { shopCloseQueueSheets(view); return false; }
    if (sheet.closed) return false;
    view.stale = failure.status === 409;
    const boxes = view.stale ? [...shopQueueSheets].filter((open) => open.queueView === view)
      .map((open) => open.queueError).filter(Boolean) : [error];
    for (const box of boxes) {
      const refresh = el("button", { type: "button", class: "btn btn-quiet", text: "Refresh Shopping",
        onclick: () => { shopCloseQueueSheets(); route(); } });
      clear(box).append(el("p", { text: `The purchase queue couldn't be saved: ${failure.message}` }), refresh);
      box.hidden = false;
      if (box === error) refresh.focus();
    }
    return false;
  } finally {
    shopQueueBusy(view, false);
    if (!sheet.closed) sheet.dialog.querySelectorAll("button").forEach((button) => {
      button.disabled = view.stale && (button.textContent === "Save" || button.textContent === "Add card" || button.textContent === "Remove card");
    });
    if (focusAfter && shopQueueActive(view)) shopQueueFocus(focusAfter);
  }
}

/** Serialise moves on this page; a conflict leaves the row in place until Shopping is refreshed. */
async function shopMoveQueue(card, next, view, error) {
  if (view.busy || view.stale || !shopQueueActive(view) || next === card.state) return;
  shopQueueBusy(view, true);
  error.hidden = true;
  const buttons = view.root.querySelectorAll(".shop-category-move");
  buttons.forEach((button) => { button.disabled = true; });
  let retry = null, focusAfter = null;
  try {
    const answer = await apiWrite("/api/shopping/queue", { row: card.queue_row, state: next, expect: view.data.queue_revision });
    if (!shopQueueActive(view)) return;
    card.state = next;
    if (Object.hasOwn(answer, "reprints")) card.reprints = answer.reprints;
    view.data.queue_revision = answer.revision;
    if (next === "long_term") view.expanded.add(card.deck ? card.deck.id : card.for || "");
    view.redraw();
    focusAfter = Array.from(view.root.querySelectorAll(".shop-category-move"))
      .find((button) => Number(button.dataset.queueRow) === card.queue_row);
    toast(`${card.name} moved to ${SHOPPING_STATES[next]}.`);
  } catch (failure) {
    if (!shopQueueActive(view)) return;
    view.stale = failure.status === 409;
    retry = el("button", { type: "button", class: "btn btn-quiet", text: "Refresh Shopping", onclick: () => route() });
    clear(error).append(el("p", { text: `The card couldn't be moved: ${failure.message}` }),
      retry);
    error.hidden = false;
  } finally {
    shopQueueBusy(view, false);
    if (view.root.isConnected) {
      view.root.querySelectorAll(".shop-category-move").forEach((button) => { button.disabled = Boolean(view.stale); });
      if (retry) shopQueueFocus(retry);
      else if (focusAfter && shopQueueActive(view)) shopQueueFocus(focusAfter);
    }
  }
}

/** A deck's player in words: the home profile who plays it, "Either of you" for both. */
function shopPlayer(player) {
  if (player === "either") return "Either of you";
  const found = (state.profiles || []).find((p) => (p.space || HOME_SPACE) === HOME_SPACE && p.plays_as === player);
  return found ? found.name : null;
}

/** A deck still missing cards: a link to its Cards tab filtered to the missing ones. How many are missing is
 * plain words (an idea deck missing cards is normal, not an error); chips only for what's worth noticing,
 * always under the name: copies on the way, copies in the long-term plan. */
function shopDeckMissing(deck, planned) {
  const meta = [deck.kind === "commander" ? "Commander" : "Casual 60", shopPlayer(deck.player),
    `${plural(deck.missing, "card")} missing`].filter(Boolean).join(" · ");
  const chips = [deck.on_the_way ? status("info", `${deck.on_the_way} on the way`) : null,
    planned ? status("good", `${planned} in the long-term plan`) : null].filter(Boolean);
  return el("li", {}, el("a", { class: "shop-deck", href: `${deckHref(deck.id)}&tab=cards&filter=missing` },
    el("strong", { class: "shop-deck-title", text: deck.title }), el("small", { text: meta }),
    chips.length ? el("span", { class: "chips" }, chips) : null));
}

/** The decks still missing cards in two groups: the ones built or being built, then the ideas. */
function shopDecksMissing(decks, planned) {
  const groups = [["Built and being built", decks.filter((d) => d.status !== "idea")],
    ["Ideas", decks.filter((d) => d.status === "idea")]].filter(([, list]) => list.length);
  return groups.map(([words, list]) => el("div", { class: "shop-deck-group" },
    el("h3", { text: words }),
    el("ul", { class: "shop-decks" }, list.map((deck) => shopDeckMissing(deck, planned.get(deck.id))))));
}

/** The long-term plan as groups by deck, each its cards as rows (12 at first, then "Show all"). */
function shopLongTerm(rows, view = null) {
  const groups = new Map();
  for (const row of rows) {
    const key = row.deck ? row.deck.id : row.for || "";
    if (!groups.has(key)) groups.set(key, { deck: row.deck, name: row.deck ? row.deck.title : row.for || "Not for a deck yet", rows: [] });
    groups.get(key).rows.push(row);
  }
  return [...groups.entries()].map(([key, group]) => {
    const copies = group.rows.reduce((sum, r) => sum + (r.quantity || 0), 0);
    const list = view ? shopQueuePresentation([["long_term", "Long-term", []]], view, {showFor: false, group: "long-term", headings: false})
      : el("div", { class: "shop-rows" });
    let shownCount = 0;
    const draw = (all) => {
      const shown = all ? group.rows : group.rows.slice(0, SHOP_LONG_TERM_SHOWN);
      if (view) list.appendQueueRows(shown.slice(shownCount));
      else add(list, shown.slice(shownCount).map((r) => shopQueueRow(r, "long-term", false)));
      shownCount = shown.length;
    };
    const expanded = view && view.expanded.has(key);
    draw(expanded);
    const more = !expanded && group.rows.length > SHOP_LONG_TERM_SHOWN
      ? el("button", { type: "button", class: "btn btn-quiet btn-inline shop-long-more", text: `Show all ${group.rows.length}`,
        onclick: (e) => {
          if (view && (!e.currentTarget.isConnected || !shopQueueActive(view))) return;
          if (view) view.expanded.add(key); draw(true); e.currentTarget.remove();
        } }) : null;
    return el("div", { class: "shop-group", "data-long-key": key },
      el("h3", {}, group.deck ? el("a", { href: deckHref(group.deck.id) }, shopDeckSwatch(group.deck), group.name) : group.name,
        el("span", { class: "shop-group-count", text: ` · ${plural(copies, "card")}` })),
      list, more);
  });
}

/** A past order in the history: its title and date, what it held, and its delivery details. */
function shopPastOrder(order, view = null) {
  const total = (order.components || []).reduce((sum, c) => sum + (c.quantity || 0), 0);
  return el("li", { class: "shop-past" },
    el("a", { href: `#/receipt?order=${encodeURIComponent(order.id)}` },
      el("strong", { text: shopOrderTitle(order) }),
      el("small", { text: [order.ordered_on ? shopDay(order.ordered_on) : null, plural(total, "card")].filter(Boolean).join(" · ") })),
    order.status === "cancelled" ? status("plain", "Cancelled") : null, shopOrderEditButton(order, view));
}

/** A section with its heading, a count when there's more than one thing in it, and one line saying what it is. */
function shopSection(id, title, count, description, ...content) {
  return el("section", { class: "shop-section", "aria-labelledby": id },
    el("div", { class: "shop-section-head" }, el("h2", { id, text: title }),
      count > 1 ? el("span", { class: "shop-count", text: String(count), "aria-label": `${count} items` }) : null),
    description ? el("p", { class: "shop-description", text: description }) : null, content);
}

function drawShopping(data) {
  if (typeof noteDeliveries === "function") noteDeliveries(data);     // the top bar's badge (shell.js)
  if (!data.to_buy) data.to_buy = [];
  const view = { data, expanded: new Set(), queuePresentations: [], queueOrder: "state", busy: false, stale: false, root: null, redraw: null,
    token: routeToken, profile: state.profile && state.profile.id };
  view.addButton = mayDo("orders") && data.queue_revision ? el("button", { type: "button",
    class: `btn ${isAdminProfile() ? "" : "btn-primary "}shop-queue-add shop-queue-write`,
    "aria-label": "Add card to the purchase queue", onclick: () => shopQueueSheet(view) },
    el("span", {class: "shop-queue-add-label", text: "Add card"})) : null;
  view.addHome = view.addButton ? el("span", {class: "shop-add-home"}, view.addButton) : null;
  const queue = data.to_buy || [], orders = data.orders || [], checks = data.checks || [];
  const waiting = orders.filter((order) => (order.components || []).some((c) => c.status === "pending"));
  const history = orders.filter((order) => !waiting.includes(order));
  const followUps = checks.filter((check) => check.status === "received");
  const onArrival = (order) => checks.filter((check) => check.order_id === order.id && check.status === "pending");
  const decks = data.decks_missing || [];
  const emptyBox = el("div", { class: "empty shop-empty" }, el("p", { text: "Nothing to buy, and nothing on the way." }),
    el("a", { class: "btn", href: "#/wishlist", text: "Open your wishlist" }));
  const buySlot = el("div", { class: "shop-queue-slot" });
  const deckSlot = el("div", { class: "shop-queue-slot" });
  const longSlot = el("div", { class: "shop-long-slot" });
  const missingSlot = el("div", { class: "shop-buying-slot shop-missing-slot" });
  const storeSlot = el("div", { class: "shop-buying-slot shop-store-slot" });
  const matchSlot = el("div", { class: "shop-match-slot", role: "status", "aria-live": "polite" });
  view.matchSlot = matchSlot;
  const jumpSlot = el("div");

  // The list pane owns deliveries, follow-ups and the current shop research. Buying stays in the detail
  // pane; below 1281 px they stack, with links to each part. Keep delivery/Undo/history nodes across writes.
  const main = [
    shopSection("shop-on-the-way", "On the way", waiting.length, null,
      waiting.length ? el("div", { class: "shop-deliveries" }, waiting.map((order) => shopDelivery(order, onArrival(order), view)))
        : el("div", { class: "empty" }, el("p", { text: "Nothing is on the way." }))),
    followUps.length ? shopSection("shop-follow-ups", "Follow-ups", followUps.length,
      "Checks left open on deliveries that have arrived.",
      el("ul", { class: "shop-followups" }, followUps.map((check) => shopFollowUp(check, orders.find((o) => o.id === check.order_id))))) : null,
    storeSlot,
  ];
  const sideNode = el("div", { class: "shop-side shop-detail-pane" }, matchSlot, buySlot, missingSlot, deckSlot, longSlot);
  // Redraw only buying controls and their counts. Deliveries and pending follow-up Undo keep their nodes.
  view.redraw = () => {
    shopReturnQueueAdd(view);
    view.queueControls = view.queueAddSlot = null;
    view.queuePresentations = [];
    shopNormalizeChoice(view);
    const immediate = queue.filter((card) => card.state !== "long_term");
    const later = queue.filter((card) => card.state === "long_term");
    const planned = new Map();
    for (const row of later) if (row.deck) planned.set(row.deck.id, (planned.get(row.deck.id) || 0) + (row.quantity || 0));
    clear(buySlot);
    if (immediate.length) buySlot.append(shopSection("shop-to-buy", "To buy", immediate.length,
      "Cards we've decided to buy. Prices are the lowest seen when checked, not live stock.",
      shopQueueControls(view), shopQueueGroups(immediate, view)));
    clear(deckSlot);
    if (decks.length) deckSlot.append(shopSection("shop-decks", "Decks still missing cards", decks.length,
      "Not a shopping list: open a deck to see its missing cards and decide what to buy.", shopDecksMissing(decks, planned)));
    clear(longSlot);
    if (later.length) longSlot.append(shopSection("shop-long-term", "Long-term plan", 0,
      `${plural(later.reduce((sum, r) => sum + (r.quantity || 0), 0), "card")} for decks to build later. Add them to an order when the shop has them, to share its postage.`,
      shopLongTerm(later, view)));
    clear(missingSlot); add(missingSlot, [shopMissingCards(view)]);
    clear(storeSlot); add(storeSlot, [shopByShop(view)]);
    clear(jumpSlot);
    const missing = data.missing_cards;
    const missingShown = missing && (!missing.ready || (missing.rows || []).length || (missing.errors || []).length || (missing.warnings || []).length);
    sideNode.hidden = !immediate.length && !decks.length && !later.length && !missingShown;
    emptyBox.hidden = Boolean(waiting.length || followUps.length || immediate.length || later.length || decks.length || missingShown);
    const jumps = shopJumps([
      { id: "shop-on-the-way", label: "On the way", count: waiting.length, number: waiting.length },
      { id: "shop-to-buy", label: "To buy", count: immediate.length, number: immediate.length },
      { id: "shop-decks", label: "Decks missing cards", count: decks.length, number: decks.length },
      { id: "shop-missing-cards", label: "Missing cards", count: missingShown, number: (missing?.rows || []).length },
      { id: "shop-by-shop", label: "By shop", count: queue.length, number: 0 },
      { id: "shop-follow-ups", label: "Follow-ups", count: followUps.length, number: followUps.length },
      { id: "shop-long-term", label: "Long-term plan", count: later.length, number: 0 },
    ]);
    if (jumps) jumpSlot.append(jumps);
    shopApplyMatches(view);
  };
  view.redraw();
  const layout = el("div", { class: "shop-layout" }, el("div", { class: "shop-main shop-list-pane" }, main), sideNode);
  const layoutSlot = el("div");
  if (emptyBox.hidden) layoutSlot.append(layout);
  const root = el("div", { class: "shop-page" },
    pageHead({ title: routeH1("shopping"), description: "What's on the way, what to check and what to buy.",
      primary: mayDo("orders") && data.queue_revision ? [
        isAdminProfile() ? el("button", { type: "button", class: "btn btn-primary shop-order-add shop-queue-write",
          text: "New order", onclick: () => shopOrderSheet(view) }) : null,
        view.addHome,
      ] : null,
      more: [{ label: routeFor("wishlist").label, href: "#/wishlist" }, { label: "Refresh", onclick: () => route() }] }),
    warningsBox(data.warnings, "Some shopping records need attention"),
    jumpSlot,
    emptyBox,
    layoutSlot,
    history.length ? el("details", { class: "shop-history" },
      el("summary", { text: `Order history · ${plural(history.length, "order")}` }),
      el("ul", { class: "shop-pasts" }, history.map(order => shopPastOrder(order, view)))) : null);
  view.root = root;
  $("#main").append(root);
  const redraw = view.redraw;
  view.redraw = () => {
    redraw();
    if (!emptyBox.hidden) layout.remove();
    else if (!layout.parentNode) layoutSlot.append(layout);
    shopSyncQueueControls(view);
  };
  shopSyncQueueControls(view);
  shopWatchQueueDensity(view);
  return view;
}
